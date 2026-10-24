"""Compute the match's statistics from the normalized model.

Everything here is a pure function of :class:`~app.parsing.model.NormalizedMatch`, which
is what makes the numbers testable with a dozen hand-written rows instead of a 84 MB
demo. The metric definitions these implement are in :mod:`app.analytics.definitions` and
are served over the API so documentation and behaviour stay in step.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.analytics.constants import (
    FLASH_WEAPONS,
    MAX_CLUTCH_OPPONENTS,
    MAX_MULTIKILL,
    MIN_MULTIKILL,
    NON_DAMAGING_UTILITY,
    UTILITY_DAMAGE_WEAPONS,
)
from app.analytics.round_state import Clutch, RoundState, build_round_states, rounds_present
from app.analytics.trades import TradeResult, detect_trades
from app.parsing.model import (
    Anomaly,
    BlindNorm,
    DamageNorm,
    KillNorm,
    NormalizedMatch,
    ObjectiveNorm,
    PlayerRef,
    RoundNorm,
    Side,
    Team,
)


@dataclass(slots=True)
class PlayerStats:
    """One row of the scoreboard.

    ``None`` always means "not knowable from this demo", never zero — see
    :mod:`app.analytics.definitions`.
    """

    player_key: str
    name: str
    steamid: int | None
    is_bot: bool
    team: Team | None
    last_side: Side | None
    rounds_present: int = 0

    kills: int = 0
    deaths: int = 0
    assists: int = 0
    flash_assists: int = 0
    team_kills: int = 0
    self_kills: int = 0
    headshot_kills: int = 0
    opening_kills: int = 0
    opening_deaths: int = 0
    traded_deaths: int = 0
    trade_kills: int = 0

    kd: float | None = None
    kpr: float | None = None
    adr: float | None = None
    headshot_pct: float | None = None
    kast: float | None = None

    damage_total: int | None = None
    utility_damage: int | None = None
    flashes_thrown: int | None = None
    enemies_flashed: int | None = None
    flash_duration_dealt: float | None = None

    multikill_2k: int = 0
    multikill_3k: int = 0
    multikill_4k: int = 0
    multikill_5k: int = 0

    clutches_played: int = 0
    clutches_won: int = 0
    clutch_1v1: int = 0
    clutch_1v2: int = 0
    clutch_1v3: int = 0
    clutch_1v4: int = 0
    clutch_1v5: int = 0


@dataclass(slots=True)
class RoundPlayerStats:
    """A single player's contribution to a single round."""

    round_num: int
    player_key: str
    name: str
    side: Side | None
    team: Team | None
    present_at_freeze: bool
    survived: bool
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    damage: int = 0
    utility_damage: int = 0
    equipment_value: int | None = None
    is_clutch: bool = False
    clutch_opponents: int | None = None
    clutch_won: bool | None = None


@dataclass(slots=True)
class RoundSummary:
    """A round, with its outcome and objective events resolved."""

    round_num: int
    start_tick: int
    freeze_end_tick: int | None
    end_tick: int
    official_end_tick: int | None
    duration_s: float | None
    winner_side: Side | None
    winner_team: Team | None
    reason_name: str | None
    is_knife_round: bool
    half_index: int
    is_overtime: bool
    team_ct: Team | None
    score_a_after: int
    score_b_after: int
    kills_count: int
    bomb_planted: bool
    bomb_plant_tick: int | None
    bombsite: str | None
    bomb_defused: bool
    bomb_exploded: bool
    ct_equipment_value: int | None
    t_equipment_value: int | None
    ct_buy_type: str | None
    t_buy_type: str | None
    players: list[RoundPlayerStats] = field(default_factory=list)


@dataclass(slots=True)
class MatchAnalytics:
    """The complete computed result for one match."""

    players: list[PlayerStats]
    rounds: list[RoundSummary]
    anomalies: list[Anomaly]
    round_count: int
    team_a_score: int
    team_b_score: int
    winner_team: Team | None


def compute(match: NormalizedMatch) -> MatchAnalytics:
    """Compute every MVP statistic for ``match``."""
    anomalies = list(match.anomalies)
    scored_rounds = {r.round_num for r in match.scored_rounds}
    denominator = match.round_count

    states = build_round_states(match)
    trades = detect_trades(match.kills, match.meta.tick_rate)
    traded_by_player = trades.traded_deaths_by_player(match.kills)
    trade_kills_by_player = trades.trade_kills_by_player(match.kills)

    teams = {entry.player_key: entry.team for entry in match.roster}
    last_side = _last_sides(match)
    _warn_unknown_weapons(match, anomalies)

    damage_available = match.is_available("damages")
    flash_available = match.is_available("blinds")
    throws_available = match.is_available("shots")

    credits = assist_credits(match)
    kills_by_player, deaths_by_player, assist_counts = _combat_counts(match, scored_rounds, credits)
    damage_by_player, utility_by_player = _damage_counts(match, scored_rounds)
    openings = _openings(match, scored_rounds)
    multikills = _multikills(match, scored_rounds)
    flash_stats = _flash_counts(match, scored_rounds)
    throws = _throw_counts(match, scored_rounds)
    kast_rounds = _kast_rounds(match, states, trades, scored_rounds, credits)
    clutches = _clutches(states, scored_rounds)
    present = rounds_present(match)

    participants = participant_keys(match)
    players: list[PlayerStats] = []
    for key, ref in sorted(match.players.items(), key=lambda kv: kv[1].name.lower()):
        if key not in participants:
            continue  # e.g. the SourceTV recorder, which appears in no event
        kills = kills_by_player.get(key, 0)
        deaths = deaths_by_player.get(key, 0)
        damage = damage_by_player.get(key, 0)
        hs = _headshots(match, key, scored_rounds)
        stats = PlayerStats(
            player_key=key,
            name=ref.name,
            steamid=ref.steamid,
            is_bot=ref.is_bot,
            team=teams.get(key),
            last_side=last_side.get(key),
            rounds_present=present.get(key, 0),
            kills=kills,
            deaths=deaths,
            assists=assist_counts["kill"].get(key, 0),
            flash_assists=assist_counts["flash"].get(key, 0),
            team_kills=_count_kill_flag(match, key, scored_rounds, "team"),
            self_kills=_count_kill_flag(match, key, scored_rounds, "self"),
            headshot_kills=hs,
            opening_kills=openings["kills"].get(key, 0),
            opening_deaths=openings["deaths"].get(key, 0),
            traded_deaths=traded_by_player.get(key, 0),
            trade_kills=trade_kills_by_player.get(key, 0),
            kd=_safe_ratio(kills, deaths),
            kpr=_safe_ratio(kills, denominator),
            adr=_safe_ratio(damage, denominator) if damage_available else None,
            headshot_pct=_safe_ratio(hs * 100, kills),
            kast=_safe_ratio(len(kast_rounds.get(key, set())) * 100, denominator),
            damage_total=damage if damage_available else None,
            utility_damage=utility_by_player.get(key, 0) if damage_available else None,
            flashes_thrown=throws.get(key, 0) if throws_available else None,
            enemies_flashed=flash_stats.count.get(key, 0) if flash_available else None,
            flash_duration_dealt=(
                round(flash_stats.duration.get(key, 0.0), 3) if flash_available else None
            ),
        )
        if _never_played(stats):
            # Someone who was in the server but never took the field — a league coach
            # occupies a player slot and never spawns. Rates over the match's round count
            # would read as a confident 0.0 for a player with no basis for a rate at all,
            # which is exactly the "unknown is not zero" case. (Upstream instead credits
            # them every round and 100% KAST for "surviving" rounds they never played.)
            #
            # The test is participation, not roster presence alone: a demo whose roster
            # could not be reconstructed still has players, and their damage proves it.
            stats.kast = None
            stats.adr = None
            stats.kpr = None

        for n in range(MIN_MULTIKILL, MAX_MULTIKILL + 1):
            setattr(stats, f"multikill_{n}k", multikills.get(key, {}).get(n, 0))
        clutch = clutches.get(key)
        if clutch is not None:
            stats.clutches_played = clutch.played
            stats.clutches_won = clutch.won
            for n in range(1, MAX_CLUTCH_OPPONENTS + 1):
                setattr(stats, f"clutch_1v{n}", clutch.by_opponents.get(n, 0))
        players.append(stats)

    rounds = _round_summaries(match, states, scored_rounds, credits)
    team_a, team_b = match.team_score("A"), match.team_score("B")
    winner: Team | None = None
    if team_a != team_b:
        winner = "A" if team_a > team_b else "B"

    return MatchAnalytics(
        players=players,
        rounds=rounds,
        anomalies=anomalies,
        round_count=denominator,
        team_a_score=team_a,
        team_b_score=team_b,
        winner_team=winner,
    )


# --------------------------------------------------------------------------- helpers


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    """Divide, returning ``None`` rather than 0 when the denominator is empty.

    Every rate metric routes through here, which is what makes "no eligible rounds" and
    "genuinely zero" distinguishable all the way to the UI.
    """
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def _never_played(stats: PlayerStats) -> bool:
    """Whether a player shows no evidence of having taken the field at all."""
    return (
        stats.rounds_present == 0
        and stats.kills == 0
        and stats.deaths == 0
        and stats.assists == 0
        and not stats.damage_total
    )


def participant_keys(match: NormalizedMatch) -> set[str]:
    """Players who actually took part, as opposed to artefacts of the recording.

    The demo recorder appears in the parser's player table with Steam ID 0, but is never
    on a roster and never in any event, so it must not reach the scoreboard. Anyone who
    appears in *any* event does belong there — including a player who only dealt damage
    or threw utility and never recorded a kill or a death.
    """
    keys = {entry.player_key for entry in match.roster}
    for kill in match.kills:
        keys.add(kill.victim.key)
        for ref in (kill.attacker, kill.assister):
            if ref is not None:
                keys.add(ref.key)
    for damage in match.damages:
        keys.add(damage.victim.key)
        if damage.attacker is not None:
            keys.add(damage.attacker.key)
    for blind in match.blinds:
        keys.add(blind.victim.key)
        if blind.attacker is not None:
            keys.add(blind.attacker.key)
    for throw in match.utility:
        if throw.thrower is not None:
            keys.add(throw.thrower.key)
    return keys


def _last_sides(match: NormalizedMatch) -> dict[str, Side]:
    out: dict[str, Side] = {}
    for entry in sorted(match.roster, key=lambda e: e.round_num):
        out[entry.player_key] = entry.side
    return out


def _warn_unknown_weapons(match: NormalizedMatch, anomalies: list[Anomaly]) -> None:
    """Flag damage weapons we do not recognise so utility damage cannot silently drift.

    CS2 has changed fire-damage weapon strings before. A new string would otherwise just
    stop counting toward utility damage with no indication anything was missed, so it is
    surfaced as a warning rather than discovered later.
    """
    seen: set[str] = set()
    for damage in match.damages:
        if damage.weapon is None:
            continue
        if damage.weapon in UTILITY_DAMAGE_WEAPONS or damage.weapon in NON_DAMAGING_UTILITY:
            continue
        seen.add(damage.weapon)
    suspicious = {w for w in seen if "nade" in w or "molo" in w or "fire" in w or "burn" in w}
    if suspicious:
        anomalies.append(
            Anomaly(
                code="unrecognised_utility_weapon",
                message=(
                    "Damage from grenade-like weapons that are not in the utility list was "
                    "found; utility damage may be understated."
                ),
                context={"weapons": sorted(suspicious)},
            )
        )


@dataclass(frozen=True, slots=True)
class AssistCredit:
    """One assist credited to one player for one kill."""

    kill_index: int
    player_key: str
    is_flash: bool


def assist_credits(match: NormalizedMatch) -> list[AssistCredit]:
    """Every assist credited across the match.

    An assist comes from either of two sources, and a player gets **at most one per
    kill**:

    1. The assister the game recorded, when they are an enemy of the victim and are
       neither the victim nor the player who got the kill.
    2. Any enemy who had a flashbang blind **still active on the victim at the moment of
       the kill**. The game does not always record such a player as the assister, but
       they demonstrably set the kill up.

    The second source is why this is not simply a column read. On two of our three
    reference demos the recorded assister is the whole story; on the third it misses six
    flash assists across two players, which also costs them KAST credit.

    When a player qualifies through both routes the assist is counted once, as a flash
    assist — flash assists are a subset of assists, not a separate tally.
    """
    rate = match.meta.tick_rate or 64.0

    # Blinds indexed by victim so each kill only scans that victim's flashes.
    blinds_by_victim: dict[str, list[BlindNorm]] = defaultdict(list)
    for blind in match.blinds:
        blinds_by_victim[blind.victim.key].append(blind)

    credits: list[AssistCredit] = []
    for index, kill in enumerate(match.kills):
        per_kill: dict[str, bool] = {}

        if kill.is_valid_assist and kill.assister is not None:
            per_kill[kill.assister.key] = kill.assist_is_flash

        killer_key = kill.attacker.key if kill.attacker is not None else None
        for blind in blinds_by_victim.get(kill.victim.key, ()):
            flasher = blind.attacker
            if flasher is None or not blind.is_enemy_flash:
                continue
            if flasher.key == kill.victim.key or flasher.key == killer_key:
                continue
            if blind.round_num != kill.round_num:
                continue
            if not (blind.tick <= kill.tick <= blind.tick + blind.duration * rate):
                continue
            per_kill[flasher.key] = True

        credits.extend(
            AssistCredit(kill_index=index, player_key=key, is_flash=is_flash)
            for key, is_flash in per_kill.items()
        )
    return credits


def _combat_counts(
    match: NormalizedMatch, scored: set[int], credits: list[AssistCredit]
) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, int]]]:
    kills: dict[str, int] = defaultdict(int)
    deaths: dict[str, int] = defaultdict(int)
    assists: dict[str, dict[str, int]] = {"kill": defaultdict(int), "flash": defaultdict(int)}
    for kill in match.kills:
        if kill.round_num not in scored:
            continue
        deaths[kill.victim.key] += 1
        if kill.is_valid_kill and kill.attacker is not None:
            kills[kill.attacker.key] += 1
    for credit in credits:
        if match.kills[credit.kill_index].round_num not in scored:
            continue
        assists["flash" if credit.is_flash else "kill"][credit.player_key] += 1
    return dict(kills), dict(deaths), {k: dict(v) for k, v in assists.items()}


def _count_kill_flag(match: NormalizedMatch, key: str, scored: set[int], flag: str) -> int:
    total = 0
    for kill in match.kills:
        if kill.round_num not in scored:
            continue
        if (flag == "self" and kill.is_self_kill and kill.victim.key == key) or (
            flag == "team"
            and kill.is_team_kill
            and kill.attacker is not None
            and kill.attacker.key == key
        ):
            total += 1
    return total


def _headshots(match: NormalizedMatch, key: str, scored: set[int]) -> int:
    return sum(
        1
        for kill in match.kills
        if kill.round_num in scored
        and kill.headshot
        and kill.is_valid_kill
        and kill.attacker is not None
        and kill.attacker.key == key
    )


def _damage_counts(
    match: NormalizedMatch, scored: set[int]
) -> tuple[dict[str, int], dict[str, int]]:
    """Capped enemy damage, in total and from utility, per attacker."""
    total: dict[str, int] = defaultdict(int)
    utility: dict[str, int] = defaultdict(int)
    for damage in match.damages:
        attacker = damage.attacker
        if damage.round_num not in scored or not damage.is_valid_damage or attacker is None:
            continue
        total[attacker.key] += damage.dmg_health_effective
        if damage.weapon in UTILITY_DAMAGE_WEAPONS:
            utility[attacker.key] += damage.dmg_health_effective
    return dict(total), dict(utility)


def _openings(match: NormalizedMatch, scored: set[int]) -> dict[str, dict[str, int]]:
    """First enemy kill of each round, by attacker and by victim.

    Self-kills are skipped rather than treated as the opening: a player falling to their
    death is not an entry duel, and counting it would hand a phantom opening death to
    someone and deny the real entry its credit.
    """
    kills: dict[str, int] = defaultdict(int)
    deaths: dict[str, int] = defaultdict(int)
    by_round: dict[int, list[KillNorm]] = defaultdict(list)
    for kill in match.kills:
        if kill.round_num in scored:
            by_round[kill.round_num].append(kill)
    for round_kills in by_round.values():
        for kill in sorted(round_kills, key=lambda k: (k.tick, k.src_idx)):
            if not kill.is_valid_kill or kill.attacker is None:
                continue
            kills[kill.attacker.key] += 1
            deaths[kill.victim.key] += 1
            break
    return {"kills": dict(kills), "deaths": dict(deaths)}


def _multikills(match: NormalizedMatch, scored: set[int]) -> dict[str, dict[int, int]]:
    per_round: dict[tuple[int, str], int] = defaultdict(int)
    for kill in match.kills:
        if kill.round_num in scored and kill.is_valid_kill and kill.attacker is not None:
            per_round[(kill.round_num, kill.attacker.key)] += 1
    out: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for (_round, key), count in per_round.items():
        if count >= MIN_MULTIKILL:
            out[key][min(count, MAX_MULTIKILL)] += 1
    return {k: dict(v) for k, v in out.items()}


@dataclass(frozen=True, slots=True)
class _FlashTotals:
    """Enemy flashes landed and blind seconds inflicted, per thrower."""

    count: dict[str, int]
    duration: dict[str, float]


def _flash_counts(match: NormalizedMatch, scored: set[int]) -> _FlashTotals:
    count: dict[str, int] = defaultdict(int)
    duration: dict[str, float] = defaultdict(float)
    for blind in match.blinds:
        thrower = blind.attacker
        if blind.round_num not in scored or not blind.is_enemy_flash or thrower is None:
            continue
        count[thrower.key] += 1
        duration[thrower.key] += blind.duration
    return _FlashTotals(count=dict(count), duration=dict(duration))


def _throw_counts(match: NormalizedMatch, scored: set[int]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for throw in match.utility:
        if throw.round_num not in scored or throw.thrower is None:
            continue
        if throw.utility_type in FLASH_WEAPONS:
            out[throw.thrower.key] += 1
    return dict(out)


def _kast_rounds(
    match: NormalizedMatch,
    states: dict[int, RoundState],
    trades: TradeResult,
    scored: set[int],
    credits: list[AssistCredit],
) -> dict[str, set[int]]:
    """Which scored rounds each player earned a KAST credit in."""
    traded_pairs: set[tuple[int, str]] = set()
    for index in trades.traded_death_indices:
        kill = match.kills[index]
        traded_pairs.add((kill.round_num, kill.victim.key))

    credit: dict[str, set[int]] = defaultdict(set)
    for kill in match.kills:
        if kill.round_num not in scored:
            continue
        if kill.is_valid_kill and kill.attacker is not None:
            credit[kill.attacker.key].add(kill.round_num)
    for assist in credits:
        assisted = match.kills[assist.kill_index]
        if assisted.round_num in scored:
            credit[assist.player_key].add(assisted.round_num)
    for round_num, player_key in traded_pairs:
        if round_num in scored:
            credit[player_key].add(round_num)
    for round_num, state in states.items():
        if round_num not in scored:
            continue
        for player_key in state.roster:
            if state.survived(player_key):
                credit[player_key].add(round_num)
    return dict(credit)


@dataclass(slots=True)
class _ClutchTotals:
    """Clutch situations entered and won, bucketed by live opponent count."""

    played: int = 0
    won: int = 0
    by_opponents: dict[int, int] = field(default_factory=dict)


def _clutches(states: dict[int, RoundState], scored: set[int]) -> dict[str, _ClutchTotals]:
    out: dict[str, _ClutchTotals] = {}
    for round_num, state in states.items():
        if round_num not in scored or state.clutch is None:
            continue
        clutch = state.clutch
        entry = out.setdefault(clutch.player_key, _ClutchTotals())
        entry.played += 1
        if clutch.won:
            entry.won += 1
            entry.by_opponents[clutch.opponents] = entry.by_opponents.get(clutch.opponents, 0) + 1
    return out


def _round_summaries(
    match: NormalizedMatch,
    states: dict[int, RoundState],
    scored: set[int],
    credits: list[AssistCredit],
) -> list[RoundSummary]:
    teams = {entry.player_key: entry.team for entry in match.roster}
    equipment = {
        (entry.round_num, entry.player_key): entry.equipment_value for entry in match.roster
    }
    kills_by_round: dict[int, list[KillNorm]] = defaultdict(list)
    for kill in match.kills:
        kills_by_round[kill.round_num].append(kill)
    damage_by_round: dict[int, list[DamageNorm]] = defaultdict(list)
    for damage in match.damages:
        damage_by_round[damage.round_num].append(damage)
    objectives_by_round: dict[int, list[ObjectiveNorm]] = defaultdict(list)
    for objective in match.objectives:
        objectives_by_round[objective.round_num].append(objective)

    clutch_lookup: dict[tuple[int, str], Clutch] = {
        (state.clutch.round_num, state.clutch.player_key): state.clutch
        for state in states.values()
        if state.clutch is not None
    }

    # Assists per (round, player), from the same credits the scoreboard uses, so a round
    # row can never disagree with the match total it rolls up into.
    assists_by_round: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for credit in credits:
        assisted = match.kills[credit.kill_index]
        assists_by_round[assisted.round_num][credit.player_key] += 1

    summaries: list[RoundSummary] = []
    score_a = score_b = 0
    for round_ in match.rounds:
        if round_.round_num in scored:
            if round_.winner_team == "A":
                score_a += 1
            elif round_.winner_team == "B":
                score_b += 1

        objectives = objectives_by_round[round_.round_num]
        plant = next((o for o in objectives if o.event == "finish_plant"), None)
        duration = None
        if round_.freeze_end_tick is not None and match.meta.tick_rate:
            duration = round((round_.end_tick - round_.freeze_end_tick) / match.meta.tick_rate, 2)

        per_player = _round_players(
            match,
            round_,
            states.get(round_.round_num),
            kills_by_round[round_.round_num],
            damage_by_round[round_.round_num],
            teams,
            equipment,
            clutch_lookup,
            dict(assists_by_round.get(round_.round_num, {})),
        )
        summaries.append(
            RoundSummary(
                round_num=round_.round_num,
                start_tick=round_.start_tick,
                freeze_end_tick=round_.freeze_end_tick,
                end_tick=round_.end_tick,
                official_end_tick=round_.official_end_tick,
                duration_s=duration,
                winner_side=round_.winner_side,
                winner_team=round_.winner_team,
                reason_name=round_.reason_name,
                is_knife_round=round_.is_knife_round,
                half_index=round_.half_index,
                is_overtime=round_.is_overtime,
                team_ct=round_.team_ct,
                score_a_after=score_a,
                score_b_after=score_b,
                kills_count=sum(1 for k in kills_by_round[round_.round_num] if k.is_valid_kill),
                bomb_planted=plant is not None,
                bomb_plant_tick=plant.tick if plant else None,
                bombsite=plant.bombsite if plant else None,
                bomb_defused=any(o.event == "defuse" for o in objectives),
                bomb_exploded=round_.reason_name == "target_bombed",
                ct_equipment_value=round_.ct_equipment_value,
                t_equipment_value=round_.t_equipment_value,
                ct_buy_type=round_.ct_buy_type,
                t_buy_type=round_.t_buy_type,
                players=per_player,
            )
        )
    return summaries


def _round_players(
    match: NormalizedMatch,
    round_: RoundNorm,
    state: RoundState | None,
    kills: list[KillNorm],
    damages: list[DamageNorm],
    teams: dict[str, Team | None],
    equipment: dict[tuple[int, str], int | None],
    clutch_lookup: dict[tuple[int, str], Clutch],
    round_assists: dict[str, int],
) -> list[RoundPlayerStats]:
    round_num = round_.round_num
    rows: dict[str, RoundPlayerStats] = {}

    def ensure(key: str, ref: PlayerRef | None, side: Side | None) -> RoundPlayerStats:
        if key not in rows:
            name = ref.name if ref else match.players.get(key, PlayerRef(key, key)).name
            rows[key] = RoundPlayerStats(
                round_num=round_num,
                player_key=key,
                name=name,
                side=side,
                team=teams.get(key),
                present_at_freeze=bool(state and key in state.roster),
                survived=bool(state and state.survived(key)),
                equipment_value=equipment.get((round_num, key)),
            )
        return rows[key]

    if state is not None:
        for key, side in state.roster.items():
            ensure(key, match.players.get(key), side)

    for kill in kills:
        victim = ensure(kill.victim.key, kill.victim, kill.victim_side)
        victim.deaths += 1
        if kill.is_valid_kill and kill.attacker is not None:
            attacker = ensure(kill.attacker.key, kill.attacker, kill.attacker_side)
            attacker.kills += 1
    for key, count in round_assists.items():
        if key in rows:
            rows[key].assists = count
        else:
            ensure(key, match.players.get(key), None).assists = count

    for damage in damages:
        if not damage.is_valid_damage or damage.attacker is None:
            continue
        row = ensure(damage.attacker.key, damage.attacker, damage.attacker_side)
        row.damage += damage.dmg_health_effective
        if damage.weapon in UTILITY_DAMAGE_WEAPONS:
            row.utility_damage += damage.dmg_health_effective

    for (clutch_round, key), clutch in clutch_lookup.items():
        if clutch_round == round_num and key in rows:
            rows[key].is_clutch = True
            rows[key].clutch_opponents = clutch.opponents
            rows[key].clutch_won = clutch.won

    return sorted(rows.values(), key=lambda r: (-r.kills, -r.damage, r.name.lower()))
