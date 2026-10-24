"""Builders for synthetic normalized matches.

Unit tests are written against hand-made rows rather than a real demo so that each one
states a single rule and runs in milliseconds. These helpers keep the tests readable:
a test about trade windows should show the two kills that matter, not thirty lines of
dataclass construction.
"""

from __future__ import annotations

from app.parsing.model import (
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
    RosterEntry,
    RoundNorm,
    Side,
    UtilityThrowNorm,
)
from app.parsing.normalize import apply_damage_caps

TICK_RATE = 64.0
#: 5.25 s at 64 tick — the exact trade-window boundary in ticks.
TRADE_WINDOW_TICKS = 336


def player(name: str, steamid: int | None = None) -> PlayerRef:
    """A player whose Steam ID defaults to a stable hash of the name."""
    if steamid is None:
        steamid = 76561190000000000 + (abs(hash(name)) % 10_000_000)
    return PlayerRef.create(steamid, name)


def bot(name: str) -> PlayerRef:
    """A bot — Steam ID 0, so keyed by name."""
    return PlayerRef.create(0, name)


def meta(**overrides: object) -> MatchMeta:
    base: dict[str, object] = {
        "map_name": "de_test",
        "tick_rate": TICK_RATE,
        "tick_rate_source": "header",
        "parser_version": "test",
        "roster_source": "snapshots",
    }
    base.update(overrides)
    return MatchMeta(**base)  # type: ignore[arg-type]


def round_(
    num: int,
    *,
    start: int | None = None,
    end: int | None = None,
    freeze_end: int | None = None,
    winner_side: Side | None = "CT",
    team_ct: str | None = "A",
    winner_team: str | None = None,
    knife: bool = False,
    reason: str | None = "ct_win",
    **extra: object,
) -> RoundNorm:
    """A round on a simple 10 000-tick-per-round grid."""
    span = 10_000
    start = start if start is not None else (num - 1) * span + 1
    end = end if end is not None else start + span - 100
    freeze = freeze_end if freeze_end is not None else start + 100
    if winner_team is None and winner_side is not None and team_ct is not None:
        winner_team = team_ct if winner_side == "CT" else ("B" if team_ct == "A" else "A")
    return RoundNorm(
        round_num=num,
        start_tick=start,
        end_tick=end,
        freeze_end_tick=freeze,
        official_end_tick=end + 50,
        winner_side=winner_side,
        reason_name=reason,
        is_knife_round=knife,
        team_ct=team_ct,  # type: ignore[arg-type]
        winner_team=winner_team,  # type: ignore[arg-type]
        **extra,  # type: ignore[arg-type]
    )


def kill(
    src_idx: int,
    tick: int,
    round_num: int,
    attacker: PlayerRef | None,
    victim: PlayerRef,
    *,
    attacker_side: Side | None = "CT",
    victim_side: Side | None = "T",
    headshot: bool = False,
    weapon: str = "ak47",
    assister: PlayerRef | None = None,
    assister_side: Side | None = None,
    assist_is_flash: bool = False,
    post_round: bool = False,
) -> KillNorm:
    return KillNorm(
        src_idx=src_idx,
        tick=tick,
        round_num=round_num,
        victim=victim,
        victim_side=victim_side,
        attacker=attacker,
        attacker_side=attacker_side if attacker is not None else None,
        assister=assister,
        assister_side=assister_side or (attacker_side if assister else None),
        assist_is_flash=assist_is_flash,
        weapon=weapon,
        headshot=headshot,
        is_post_round=post_round,
    )


def damage(
    src_idx: int,
    tick: int,
    round_num: int,
    attacker: PlayerRef | None,
    victim: PlayerRef,
    raw: int,
    *,
    health_post: int | None = None,
    attacker_side: Side | None = "CT",
    victim_side: Side | None = "T",
    weapon: str = "ak47",
) -> DamageNorm:
    """A damage row with ``dmg_health_effective`` left at 0 for the capper to fill."""
    return DamageNorm(
        src_idx=src_idx,
        tick=tick,
        round_num=round_num,
        victim=victim,
        victim_side=victim_side,
        dmg_health_raw=raw,
        dmg_health_effective=0,
        attacker=attacker,
        attacker_side=attacker_side if attacker is not None else None,
        weapon=weapon,
        health_post=health_post,
    )


def blind(
    src_idx: int,
    tick: int,
    round_num: int,
    attacker: PlayerRef | None,
    victim: PlayerRef,
    duration: float,
    *,
    attacker_side: Side | None = "CT",
    victim_side: Side | None = "T",
) -> BlindNorm:
    return BlindNorm(
        src_idx=src_idx,
        tick=tick,
        round_num=round_num,
        victim=victim,
        victim_side=victim_side,
        duration=duration,
        attacker=attacker,
        attacker_side=attacker_side,
    )


def throw(
    src_idx: int,
    tick: int,
    round_num: int,
    thrower: PlayerRef | None,
    utility_type: str = "flashbang",
    *,
    side: Side | None = "CT",
) -> UtilityThrowNorm:
    return UtilityThrowNorm(
        src_idx=src_idx,
        tick=tick,
        round_num=round_num,
        thrower=thrower,
        thrower_side=side,
        utility_type=utility_type,
    )


def objective(
    src_idx: int,
    tick: int,
    round_num: int,
    event: str,
    actor: PlayerRef | None = None,
    bombsite: str | None = None,
) -> ObjectiveNorm:
    return ObjectiveNorm(
        src_idx=src_idx,
        tick=tick,
        round_num=round_num,
        event=event,
        player=actor,
        player_side="T",
        bombsite=bombsite,
    )


def roster_for(
    rounds: list[RoundNorm],
    ct: list[PlayerRef],
    t: list[PlayerRef],
    *,
    absent: set[tuple[int, str]] | None = None,
    swap_at: int | None = None,
) -> list[RosterEntry]:
    """A roster for every round, optionally swapping sides from ``swap_at`` onward.

    ``absent`` marks ``(round_num, player_key)`` pairs as not present at freeze, which is
    how tests exercise the roster gate that stops absent players collecting KAST credit.
    """
    absent = absent or set()
    entries: list[RosterEntry] = []
    for round_ in rounds:
        swapped = swap_at is not None and round_.round_num >= swap_at
        for group, side in ((ct, "CT"), (t, "T")):
            actual: Side = side  # type: ignore[assignment]
            if swapped:
                actual = "T" if side == "CT" else "CT"
            for ref in group:
                entries.append(
                    RosterEntry(
                        round_num=round_.round_num,
                        player_key=ref.key,
                        side=actual,
                        team="A" if group is ct else "B",
                        present_at_freeze=(round_.round_num, ref.key) not in absent,
                    )
                )
    return entries


def available(*datasets: str, empty: tuple[str, ...] = ()) -> Availability:
    """An availability map marking ``datasets`` present and ``empty`` ones empty."""
    out: Availability = {
        name: DatasetAvailability(state=DatasetState.AVAILABLE, row_count=1) for name in datasets
    }
    for name in empty:
        out[name] = DatasetAvailability(
            state=DatasetState.EMPTY, row_count=0, reason="no rows in this demo"
        )
    return out


def match(
    *,
    rounds: list[RoundNorm] | None = None,
    roster: list[RosterEntry] | None = None,
    kills: list[KillNorm] | None = None,
    damages: list[DamageNorm] | None = None,
    blinds: list[BlindNorm] | None = None,
    utility: list[UtilityThrowNorm] | None = None,
    objectives: list[ObjectiveNorm] | None = None,
    players: list[PlayerRef] | None = None,
    availability: Availability | None = None,
    meta_overrides: dict[str, object] | None = None,
    apply_caps: bool = True,
) -> NormalizedMatch:
    """Assemble a normalized match, deriving the player registry from the rows given."""
    rounds = rounds if rounds is not None else [round_(1)]
    kills = kills or []
    damages = damages or []
    blinds = blinds or []
    utility = utility or []
    objectives = objectives or []
    roster = roster if roster is not None else []

    registry: dict[str, PlayerRef] = {}
    for ref in players or []:
        registry[ref.key] = ref
    for k in kills:
        for ref in (k.attacker, k.victim, k.assister):
            if ref is not None:
                registry.setdefault(ref.key, ref)
    for d in damages:
        for ref in (d.attacker, d.victim):
            if ref is not None:
                registry.setdefault(ref.key, ref)
    for b in blinds:
        for ref in (b.attacker, b.victim):
            if ref is not None:
                registry.setdefault(ref.key, ref)
    for u in utility:
        if u.thrower is not None:
            registry.setdefault(u.thrower.key, u.thrower)

    if availability is None:
        availability = available("rounds", "kills", "damages", "blinds", "shots", "bomb")

    return NormalizedMatch(
        meta=meta(**(meta_overrides or {})),
        players=registry,
        rounds=rounds,
        roster=roster,
        kills=kills,
        damages=apply_damage_caps(damages) if apply_caps else damages,
        blinds=blinds,
        utility=utility,
        objectives=objectives,
        availability=availability,
    )
