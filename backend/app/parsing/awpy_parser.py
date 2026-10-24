"""The awpy backend: the single place in the application that imports ``awpy``.

awpy 3.x parses CS2 demos in Rust and returns typed Polars DataFrames. The reference
demo showed why that matters: Valve matchmaking demos contain **no** ``round_start`` /
``round_end`` / ``item_purchase`` events at all, and awpy reconstructs rounds and item
transactions from game-rules and inventory state instead. Anything built on raw events
would simply produce nothing for those demos.

This module's job is translation only — it reads awpy's tables and emits the normalized
model. It computes no statistics. Observed quirks it has to absorb are documented inline
and in ``docs/awpy-probe.md``.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import polars as pl

from app.parsing import errors
from app.parsing.model import (
    ANALYTICS_VERSION,
    Anomaly,
    Availability,
    BlindNorm,
    DamageNorm,
    DatasetAvailability,
    DatasetState,
    KillNorm,
    MatchMeta,
    NormalizedMatch,
    ObjectiveNorm,
    PlayerRef,
    RoundNorm,
    Side,
    UtilityThrowNorm,
)
from app.parsing.normalize import RoundLocator, apply_damage_caps
from app.parsing.roster import (
    assign_teams,
    build_roster,
    ct_team_by_round,
    derive_halves,
    normalize_side,
)

logger = logging.getLogger(__name__)

#: Datasets this app reads. Probed individually so one failure cannot hide the rest.
_DATASETS = (
    "rounds",
    "kills",
    "damages",
    "blinds",
    "shots",
    "bomb",
    "round_economy",
    "players",
)

#: Grenade weapons as they appear in the shots table, with its ``weapon_`` prefix
#: stripped. Note the schema inconsistency: ``shots.weapon`` is prefixed
#: (``weapon_flashbang``) while ``kills.weapon`` / ``damages.weapon`` are not
#: (``hegrenade``). Mixing the two silently matches nothing.
UTILITY_THROW_WEAPONS = frozenset(
    {"flashbang", "hegrenade", "smokegrenade", "molotov", "incgrenade", "decoy"}
)
_WEAPON_PREFIX = "weapon_"

_EMPTY_TO_NONE = ("", "null", "none")


def _text(value: Any) -> str | None:
    """Normalize a parser string cell: blanks and sentinels become ``None``.

    The reference demo has a world-damage row whose ``weapon`` is the empty string;
    carrying that through as a weapon name would be a small lie in every UI that shows it.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in _EMPTY_TO_NONE:
        return None
    return text


def _int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _bool(value: Any) -> bool:
    return bool(value) if value is not None else False


class AwpyParser:
    """Translates an awpy ``Demo`` into a :class:`NormalizedMatch`."""

    name = "awpy"

    def version(self) -> str:
        import awpy

        return str(awpy.__version__)

    # ------------------------------------------------------------------ public
    def parse(self, path: str) -> NormalizedMatch:
        """Parse ``path``, raising :mod:`app.parsing.errors` types on failure."""
        demo = self._open(path)
        availability: Availability = {}
        anomalies: list[Anomaly] = []
        frames = self._load_frames(demo, availability, anomalies)

        meta_header = self._header(demo)
        tick_rate, tick_rate_source = self._tick_rate(demo)

        rounds_frame = frames.get("rounds")
        if rounds_frame is None or rounds_frame.is_empty():
            raise errors.EmptyDemoError(detail=f"rounds frame empty for {Path(path).name}")

        rounds = self._rounds(rounds_frame)
        locator = RoundLocator(rounds)

        # --- roster: the basis for sides, teams and round participation ------
        registry: dict[str, PlayerRef] = {}
        sides_by_round, present, equipment, roster_source = self._roster_state(
            demo, rounds, registry, anomalies
        )
        teams = assign_teams(sides_by_round, anomalies)
        ct_by_round = ct_team_by_round(sides_by_round, teams)
        convars = self._convars(demo)
        half_index, regulation, overtime = derive_halves(
            ct_by_round, anomalies, convar_maxrounds=_int(convars.get("mp_maxrounds"))
        )
        economy = self._economy(frames.get("round_economy"))

        rounds = [
            self._finalize_round(r, ct_by_round, half_index, overtime, economy) for r in rounds
        ]
        roster = build_roster(sides_by_round, teams, present, equipment)
        side_lookup = {(entry.round_num, entry.player_key): entry.side for entry in roster}

        # --- combat ----------------------------------------------------------
        kills = self._kills(frames.get("kills"), locator, registry, side_lookup)
        damages = apply_damage_caps(
            self._damages(frames.get("damages"), locator, registry, side_lookup)
        )
        blinds = self._blinds(frames.get("blinds"), locator, registry, side_lookup)
        utility = self._utility(frames.get("shots"), locator, registry, side_lookup)
        objectives = self._objectives(frames.get("bomb"), locator, registry, side_lookup)

        self._note_missing_thrower(frames.get("shots"), availability)
        team_names = self._team_names(frames.get("players"), teams, registry)

        meta = MatchMeta(
            map_name=_text(meta_header.get("map_name")),
            tick_rate=tick_rate,
            tick_rate_source=tick_rate_source,
            demo_version_name=_text(meta_header.get("demo_version_name")),
            server_name=_text(meta_header.get("server_name")),
            build_num=_int(meta_header.get("build_num")),
            playback_ticks=_int(meta_header.get("playback_ticks")),
            playback_frames=_int(meta_header.get("playback_frames")),
            playback_time=_float(meta_header.get("playback_time")),
            parser_name=self.name,
            parser_version=self.version(),
            analytics_version=ANALYTICS_VERSION,
            roster_source=roster_source,
            regulation_rounds=regulation,
            has_overtime=bool(overtime),
            team_a_name=team_names.get("A"),
            team_b_name=team_names.get("B"),
        )

        match = NormalizedMatch(
            meta=meta,
            players=registry,
            rounds=rounds,
            roster=roster,
            kills=kills,
            damages=damages,
            blinds=blinds,
            utility=utility,
            objectives=objectives,
            availability=availability,
            anomalies=anomalies,
        )
        self._sanity_checks(match, anomalies)
        return match

    # ------------------------------------------------------------- open/load
    def _open(self, path: str) -> Any:
        from awpy import Demo
        from awpy import InvalidDemoError as AwpyInvalidDemo

        try:
            return Demo(path)
        except FileNotFoundError as exc:
            raise errors.DemoParseError(
                "The stored demo file is missing.", detail=str(exc)
            ) from exc
        except AwpyInvalidDemo as exc:
            raise errors.InvalidDemoError(detail=str(exc)) from exc
        except ValueError as exc:
            raise errors.UnsupportedDemoError(detail=str(exc)) from exc

    def _load_frames(
        self, demo: Any, availability: Availability, anomalies: list[Anomaly]
    ) -> dict[str, pl.DataFrame]:
        """Read each dataset, recording availability instead of letting one failure win."""
        from awpy import InvalidDemoError as AwpyInvalidDemo

        frames: dict[str, pl.DataFrame] = {}
        for name in _DATASETS:
            try:
                frame = getattr(demo, name)
            except AwpyInvalidDemo as exc:
                raise errors.InvalidDemoError(detail=f"{name}: {exc}") from exc
            except Exception as exc:  # noqa: BLE001 - one dataset must not sink the parse
                logger.warning("dataset %s unavailable: %s: %s", name, type(exc).__name__, exc)
                availability[name] = DatasetAvailability(
                    state=DatasetState.UNSUPPORTED,
                    reason=f"{type(exc).__name__}: {exc}"[:300],
                )
                anomalies.append(
                    Anomaly(
                        code="dataset_unavailable",
                        message=f"The parser could not produce the '{name}' dataset.",
                        context={"dataset": name, "error": type(exc).__name__},
                    )
                )
                continue
            # `.with_row_index` BEFORE any sort or filter: within one source table the
            # row order is the demo's message order, and it is the only tiebreaker for
            # same-tick events (25 same-tick damage groups in the reference demo).
            frames[name] = frame.with_row_index("src_idx")
            availability[name] = DatasetAvailability(
                state=DatasetState.AVAILABLE if frame.height else DatasetState.EMPTY,
                row_count=frame.height,
                reason=None if frame.height else "The demo contains no rows for this dataset.",
            )
        return frames

    def _header(self, demo: Any) -> dict[str, Any]:
        try:
            return dict(demo.header)
        except Exception:
            logger.warning("demo header unavailable", exc_info=True)
            return {}

    def _convars(self, demo: Any) -> dict[str, str]:
        try:
            return dict(demo.convars)
        except Exception:
            logger.warning("convars unavailable", exc_info=True)
            return {}

    def _tick_rate(self, demo: Any) -> tuple[float, Literal["header", "fallback"]]:
        """Tick rate plus whether it came from real playback timing.

        awpy silently falls back to 64.0 when the demo omits timing. That matters: the
        5.25-second trade window is expressed in ticks, so a wrong rate would quietly
        skew trades and KAST. Recording the provenance lets the UI say so.
        """
        header = self._header(demo)
        rate = _float(getattr(demo, "tick_rate", None)) or 64.0
        source: Literal["header", "fallback"] = (
            "header" if _float(header.get("playback_time")) else "fallback"
        )
        return rate, source

    # ----------------------------------------------------------------- rounds
    def _rounds(self, frame: pl.DataFrame) -> list[RoundNorm]:
        rounds: list[RoundNorm] = []
        for row in frame.iter_rows(named=True):
            start = _int(row.get("start_tick"))
            end = _int(row.get("end_tick"))
            if end is None:
                continue
            freeze = _int(row.get("freeze_end_tick"))
            rounds.append(
                RoundNorm(
                    round_num=int(row["round_num"]),
                    start_tick=start if start is not None else (freeze or end),
                    end_tick=end,
                    freeze_end_tick=freeze,
                    official_end_tick=_int(row.get("official_end_tick")),
                    winner_side=normalize_side(row.get("winner_side")),
                    reason_name=_text(row.get("reason_name")),
                    is_knife_round=_bool(row.get("is_knife_round")),
                )
            )
        rounds.sort(key=lambda r: r.round_num)
        return rounds

    def _finalize_round(
        self,
        round_: RoundNorm,
        ct_by_round: dict[int, Any],
        half_index: dict[int, int],
        overtime: set[int],
        economy: dict[tuple[int, Side], tuple[int | None, str | None]],
    ) -> RoundNorm:
        """Attach team identity, half and economy to a round."""
        team_ct = ct_by_round.get(round_.round_num)
        winner_team = None
        if round_.winner_side is not None and team_ct is not None:
            if round_.winner_side == "CT":
                winner_team = team_ct
            else:
                winner_team = "B" if team_ct == "A" else "A"
        ct_value, ct_buy = economy.get((round_.round_num, "CT"), (None, None))
        t_value, t_buy = economy.get((round_.round_num, "T"), (None, None))
        return replace(
            round_,
            team_ct=team_ct,
            winner_team=winner_team,
            half_index=half_index.get(round_.round_num, 0),
            is_overtime=round_.round_num in overtime,
            ct_equipment_value=ct_value,
            t_equipment_value=t_value,
            ct_buy_type=ct_buy,
            t_buy_type=t_buy,
        )

    def _economy(
        self, frame: pl.DataFrame | None
    ) -> dict[tuple[int, Side], tuple[int | None, str | None]]:
        """Per-(round, side) equipment value and buy type.

        Keyed by side, not team — so it is useless as a team signal and is only joined
        onto rounds through the independently-derived ``team_ct``.
        """
        out: dict[tuple[int, Side], tuple[int | None, str | None]] = {}
        if frame is None or frame.is_empty():
            return out
        for row in frame.iter_rows(named=True):
            side = normalize_side(row.get("side"))
            number = _int(row.get("round_num"))
            if side is None or number is None:
                continue
            out[(number, side)] = (_int(row.get("equipment_value")), _text(row.get("buy_type")))
        return out

    # ----------------------------------------------------------------- roster
    def _roster_state(
        self,
        demo: Any,
        rounds: list[RoundNorm],
        registry: dict[str, PlayerRef],
        anomalies: list[Anomaly],
    ) -> tuple[
        dict[int, dict[str, Side]],
        dict[tuple[int, str], bool],
        dict[tuple[int, str], int | None],
        str,
    ]:
        """Sample player state at each round's freeze end to get sides and presence.

        This is the primary roster signal because it is the only one that reports a
        player who was present but produced no events — and ``present_at_freeze`` is what
        stops absent players from being credited with "surviving" rounds they never
        played, which would inflate KAST.
        """
        tick_to_round = {r.play_start_tick: r.round_num for r in rounds}
        ticks = sorted(tick_to_round)
        sides: dict[int, dict[str, Side]] = {}
        present: dict[tuple[int, str], bool] = {}
        equipment: dict[tuple[int, str], int | None] = {}

        snapshot: pl.DataFrame | None = None
        if ticks:
            try:
                snapshot = demo.snapshots(ticks=ticks)
            except Exception as exc:  # noqa: BLE001 - fall back to event-derived sides
                logger.warning("snapshots() unavailable: %s: %s", type(exc).__name__, exc)

        if snapshot is not None and not snapshot.is_empty():
            for row in snapshot.iter_rows(named=True):
                side = normalize_side(row.get("side"))
                round_num = tick_to_round.get(_int(row.get("tick")) or -1)
                if side is None or round_num is None:
                    continue
                player = PlayerRef.create(_int(row.get("steamid")), str(row.get("name") or ""))
                registry[player.key] = player
                sides.setdefault(round_num, {})[player.key] = side
                health = _int(row.get("health"))
                present[(round_num, player.key)] = health is None or health > 0
                equipment[(round_num, player.key)] = _int(row.get("equipment_value"))
            if sides:
                return sides, present, equipment, "snapshots"

        anomalies.append(
            Anomaly(
                code="roster_fallback",
                message=(
                    "Per-round player state was unavailable, so sides were inferred from "
                    "combat events. Players who were present but inactive in a round may be "
                    "missing from that round's roster."
                ),
                context={},
            )
        )
        return self._roster_from_events(demo, rounds, registry)

    def _roster_from_events(
        self, demo: Any, rounds: list[RoundNorm], registry: dict[str, PlayerRef]
    ) -> tuple[
        dict[int, dict[str, Side]],
        dict[tuple[int, str], bool],
        dict[tuple[int, str], int | None],
        str,
    ]:
        """Fallback: infer each round's sides from who appears in that round's events.

        Weaker than state sampling — a player with no events in a round is invisible —
        so sides observed in neighbouring rounds are carried forward within the same half.
        """
        locator = RoundLocator(rounds)
        sides: dict[int, dict[str, Side]] = {}

        def record(tick: Any, steamid: Any, name: Any, side_value: Any) -> None:
            side = normalize_side(side_value)
            round_num = locator.round_for(_int(tick) or -1)
            if side is None or round_num is None:
                return
            player = PlayerRef.create(_int(steamid), str(name or ""))
            registry[player.key] = player
            sides.setdefault(round_num, {})[player.key] = side

        for dataset, columns in (
            (
                "kills",
                (
                    ("attacker_steamid", "attacker_name", "attacker_side"),
                    ("victim_steamid", "victim_name", "victim_side"),
                ),
            ),
            (
                "damages",
                (
                    ("attacker_steamid", "attacker_name", "attacker_side"),
                    ("victim_steamid", "victim_name", "victim_side"),
                ),
            ),
        ):
            try:
                frame = getattr(demo, dataset)
            except Exception:
                logger.warning("roster fallback: %s unavailable", dataset, exc_info=True)
                continue
            for row in frame.iter_rows(named=True):
                for sid, nm, sd in columns:
                    record(row.get("tick"), row.get(sid), row.get(nm), row.get(sd))

        present = {
            (round_num, key): True for round_num, members in sides.items() for key in members
        }
        return sides, present, {}, "events"

    def _team_names(
        self,
        frame: pl.DataFrame | None,
        teams: dict[str, Any],
        registry: dict[str, PlayerRef],
    ) -> dict[str, str | None]:
        """Organisation names when the server set them, otherwise ``None``.

        Matchmaking servers leave ``team_clan_name`` null for every player (as in the
        reference demo), so the UI falls back to neutral labels rather than inventing one.
        """
        names: dict[str, str | None] = {"A": None, "B": None}
        if frame is None or frame.is_empty():
            return names
        votes: dict[str, dict[str, int]] = {"A": {}, "B": {}}
        for row in frame.iter_rows(named=True):
            clan = _text(row.get("team_clan_name"))
            if clan is None:
                continue
            player = PlayerRef.create(_int(row.get("steamid")), str(row.get("name") or ""))
            team = teams.get(player.key)
            if team in ("A", "B"):
                votes[team][clan] = votes[team].get(clan, 0) + 1
                registry.setdefault(player.key, player)
        for team, tally in votes.items():
            if tally:
                names[team] = max(tally.items(), key=lambda kv: kv[1])[0]
        if names["A"] is not None and names["A"] == names["B"]:
            # One shared name tells us nothing; neutral labels are more honest.
            names["A"] = names["B"] = None
        return names

    # ----------------------------------------------------------------- combat
    def _player(self, registry: dict[str, PlayerRef], steamid: Any, name: Any) -> PlayerRef | None:
        """Resolve (and remember) a participant; ``None`` when the row has no player."""
        sid = _int(steamid)
        label = _text(name)
        if sid is None and label is None:
            return None
        player = PlayerRef.create(sid, label or "unknown")
        existing = registry.get(player.key)
        if existing is None:
            registry[player.key] = player
            return player
        if label and existing.name != label:
            # Names change mid-match; keep the most recent one for display.
            player = PlayerRef(
                key=existing.key, name=label, steamid=existing.steamid, is_bot=existing.is_bot
            )
            registry[player.key] = player
            return player
        return existing

    def _side(
        self,
        value: Any,
        round_num: int,
        player: PlayerRef | None,
        side_lookup: dict[tuple[int, str], Side],
    ) -> Side | None:
        """Side from the event, falling back to the round roster."""
        side = normalize_side(value)
        if side is not None:
            return side
        if player is None:
            return None
        return side_lookup.get((round_num, player.key))

    def _kills(
        self,
        frame: pl.DataFrame | None,
        locator: RoundLocator,
        registry: dict[str, PlayerRef],
        side_lookup: dict[tuple[int, str], Side],
    ) -> list[KillNorm]:
        if frame is None or frame.is_empty():
            return []
        out: list[KillNorm] = []
        has_assist_flash = "assist_flash" in frame.columns
        for row in frame.iter_rows(named=True):
            tick = _int(row.get("tick"))
            round_num = locator.round_for(tick) if tick is not None else None
            victim = self._player(registry, row.get("victim_steamid"), row.get("victim_name"))
            if tick is None or round_num is None or victim is None:
                continue  # warmup, or a row with no identifiable victim
            attacker = self._player(registry, row.get("attacker_steamid"), row.get("attacker_name"))
            assister = self._player(registry, row.get("assister_steamid"), row.get("assister_name"))
            out.append(
                KillNorm(
                    src_idx=int(row["src_idx"]),
                    tick=tick,
                    round_num=round_num,
                    victim=victim,
                    victim_side=self._side(row.get("victim_side"), round_num, victim, side_lookup),
                    attacker=attacker,
                    attacker_side=self._side(
                        row.get("attacker_side"), round_num, attacker, side_lookup
                    ),
                    assister=assister,
                    assister_side=self._side(
                        row.get("assister_side"), round_num, assister, side_lookup
                    ),
                    assist_is_flash=_bool(row.get("assist_flash")) if has_assist_flash else False,
                    weapon=_text(row.get("weapon")),
                    headshot=_bool(row.get("headshot")),
                    hitgroup_name=_text(row.get("hitgroup_name")),
                    noscope=_bool(row.get("noscope")),
                    penetrated=_int(row.get("penetrated")),
                    thru_smoke=_bool(row.get("thrusmoke")),
                    is_post_round=locator.is_post_round(round_num, tick),
                    attacker_x=_float(row.get("attacker_x")),
                    attacker_y=_float(row.get("attacker_y")),
                    attacker_z=_float(row.get("attacker_z")),
                    victim_x=_float(row.get("victim_x")),
                    victim_y=_float(row.get("victim_y")),
                    victim_z=_float(row.get("victim_z")),
                )
            )
        return out

    def _damages(
        self,
        frame: pl.DataFrame | None,
        locator: RoundLocator,
        registry: dict[str, PlayerRef],
        side_lookup: dict[tuple[int, str], Side],
    ) -> list[DamageNorm]:
        if frame is None or frame.is_empty():
            return []
        out: list[DamageNorm] = []
        for row in frame.iter_rows(named=True):
            tick = _int(row.get("tick"))
            round_num = locator.round_for(tick) if tick is not None else None
            victim = self._player(registry, row.get("victim_steamid"), row.get("victim_name"))
            if tick is None or round_num is None or victim is None:
                continue
            attacker = self._player(registry, row.get("attacker_steamid"), row.get("attacker_name"))
            out.append(
                DamageNorm(
                    src_idx=int(row["src_idx"]),
                    tick=tick,
                    round_num=round_num,
                    victim=victim,
                    victim_side=self._side(row.get("victim_side"), round_num, victim, side_lookup),
                    dmg_health_raw=_int(row.get("dmg_health")) or 0,
                    dmg_health_effective=0,  # filled by apply_damage_caps
                    attacker=attacker,
                    attacker_side=self._side(
                        row.get("attacker_side"), round_num, attacker, side_lookup
                    ),
                    dmg_armor=_int(row.get("dmg_armor")) or 0,
                    weapon=_text(row.get("weapon")),
                    hitgroup_name=_text(row.get("hitgroup_name")),
                    health_post=_int(row.get("health_post")),
                    is_post_round=locator.is_post_round(round_num, tick),
                    attacker_x=_float(row.get("attacker_x")),
                    attacker_y=_float(row.get("attacker_y")),
                    attacker_z=_float(row.get("attacker_z")),
                    victim_x=_float(row.get("victim_x")),
                    victim_y=_float(row.get("victim_y")),
                    victim_z=_float(row.get("victim_z")),
                )
            )
        return out

    def _blinds(
        self,
        frame: pl.DataFrame | None,
        locator: RoundLocator,
        registry: dict[str, PlayerRef],
        side_lookup: dict[tuple[int, str], Side],
    ) -> list[BlindNorm]:
        if frame is None or frame.is_empty():
            return []
        out: list[BlindNorm] = []
        for row in frame.iter_rows(named=True):
            tick = _int(row.get("tick"))
            round_num = locator.round_for(tick) if tick is not None else None
            victim = self._player(registry, row.get("victim_steamid"), row.get("victim_name"))
            if tick is None or round_num is None or victim is None:
                continue
            attacker = self._player(registry, row.get("attacker_steamid"), row.get("attacker_name"))
            out.append(
                BlindNorm(
                    src_idx=int(row["src_idx"]),
                    tick=tick,
                    round_num=round_num,
                    victim=victim,
                    victim_side=self._side(row.get("victim_side"), round_num, victim, side_lookup),
                    duration=_float(row.get("duration")) or 0.0,
                    attacker=attacker,
                    attacker_side=self._side(
                        row.get("attacker_side"), round_num, attacker, side_lookup
                    ),
                )
            )
        return out

    def _utility(
        self,
        frame: pl.DataFrame | None,
        locator: RoundLocator,
        registry: dict[str, PlayerRef],
        side_lookup: dict[tuple[int, str], Side],
    ) -> list[UtilityThrowNorm]:
        """One row per thrown grenade, taken from weapon-fire rows.

        The obvious source — the grenade *trajectory* table — is the wrong one twice
        over. It samples each projectile on every airborne tick (6682 rows for 63 actual
        grenades), and in the reference demo its ``thrower_steamid`` is null for every
        single row, so nothing could be attributed to a player. Weapon-fire rows carry a
        populated Steam ID, side and throw position, and counting flashbangs this way
        reproduces upstream's own ``flashes_thrown`` exactly.
        """
        if frame is None or frame.is_empty() or "weapon" not in frame.columns:
            return []
        out: list[UtilityThrowNorm] = []
        for row in frame.iter_rows(named=True):
            weapon = _text(row.get("weapon"))
            if weapon is None:
                continue
            kind = weapon.removeprefix(_WEAPON_PREFIX)
            if kind not in UTILITY_THROW_WEAPONS:
                continue
            tick = _int(row.get("tick"))
            round_num = locator.round_for(tick) if tick is not None else None
            if tick is None or round_num is None:
                continue
            thrower = self._player(registry, row.get("steamid"), row.get("name"))
            out.append(
                UtilityThrowNorm(
                    src_idx=int(row["src_idx"]),
                    tick=tick,
                    round_num=round_num,
                    thrower=thrower,
                    thrower_side=self._side(row.get("side"), round_num, thrower, side_lookup),
                    utility_type=kind,
                    x=_float(row.get("x")),
                    y=_float(row.get("y")),
                    z=_float(row.get("z")),
                )
            )
        out.sort(key=lambda u: (u.tick, u.src_idx))
        return out

    def _objectives(
        self,
        frame: pl.DataFrame | None,
        locator: RoundLocator,
        registry: dict[str, PlayerRef],
        side_lookup: dict[tuple[int, str], Side],
    ) -> list[ObjectiveNorm]:
        if frame is None or frame.is_empty():
            return []
        out: list[ObjectiveNorm] = []
        for row in frame.iter_rows(named=True):
            tick = _int(row.get("tick"))
            round_num = locator.round_for(tick) if tick is not None else None
            event = _text(row.get("event"))
            if tick is None or round_num is None or event is None:
                continue
            player = self._player(registry, row.get("steamid"), row.get("name"))
            out.append(
                ObjectiveNorm(
                    src_idx=int(row["src_idx"]),
                    tick=tick,
                    round_num=round_num,
                    event=event,
                    player=player,
                    player_side=self._side(None, round_num, player, side_lookup),
                    bombsite=_text(row.get("bombsite")),
                    x=_float(row.get("x")),
                    y=_float(row.get("y")),
                    z=_float(row.get("z")),
                )
            )
        return out

    def _note_missing_thrower(self, frame: pl.DataFrame | None, availability: Availability) -> None:
        """Downgrade ``shots`` to PARTIAL when throws carry no owner.

        Some demos record actions without an attributable player. Utility counts built on
        such a table would be silently zero for everyone, so the state is recorded and the
        UI shows "unknown" rather than a confident 0.
        """
        if frame is None or frame.is_empty() or "steamid" not in frame.columns:
            return
        if frame["steamid"].null_count() == frame.height:
            availability["shots"] = DatasetAvailability(
                state=DatasetState.PARTIAL,
                row_count=frame.height,
                reason="Weapon-fire rows carry no player, so utility cannot be attributed.",
            )

    # ------------------------------------------------------------ consistency
    def _sanity_checks(self, match: NormalizedMatch, anomalies: list[Anomaly]) -> None:
        """Assert the invariants we rely on, reporting instead of silently proceeding."""
        numbers = [r.round_num for r in match.rounds]
        duplicates = {n for n in numbers if numbers.count(n) > 1}
        if duplicates:
            anomalies.append(
                Anomaly(
                    code="duplicate_round_numbers",
                    message="The demo reports repeated round numbers, which usually means a "
                    "match restart. Statistics may double-count those rounds.",
                    context={"rounds": sorted(duplicates)},
                )
            )
        scored = match.round_count
        total = match.team_score("A") + match.team_score("B")
        if scored and total != scored:
            anomalies.append(
                Anomaly(
                    code="score_mismatch",
                    message=f"Team wins sum to {total} but {scored} rounds were scored; some "
                    "rounds could not be attributed to a team.",
                    context={"scored_rounds": scored, "attributed": total},
                )
            )
        if not match.players:
            anomalies.append(
                Anomaly(
                    code="no_players",
                    message="No players could be identified in this demo.",
                    context={},
                )
            )


def get_parser() -> AwpyParser:
    """The parser backend in use. The single swap point for an alternative implementation."""
    return AwpyParser()
