"""Per-round alive/dead reconstruction.

Two metrics need to know who was alive when: KAST's "survived" component and clutch
detection. Both are derived here from the round roster plus the ordered death list, so
there is a single place where "was this player playing this round?" is answered.

The subtle part is the roster gate. A player who was not in a round produces no death
row, so a naive "no death means survived" would hand them KAST credit for every round
they sat out — silently inflating the stat for anyone who joined late or left early.
Survival therefore requires *presence*, not merely the absence of a death.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.analytics.constants import MAX_CLUTCH_OPPONENTS
from app.parsing.model import KillNorm, NormalizedMatch, RosterEntry, Side


@dataclass(frozen=True, slots=True)
class Clutch:
    """A player left alone against a live enemy side."""

    round_num: int
    player_key: str
    opponents: int
    """Enemies alive at the moment the player was left alone, clamped to 5."""
    won: bool


@dataclass(slots=True)
class RoundState:
    """Reconstructed participation and outcome for one round."""

    round_num: int
    roster: dict[str, Side] = field(default_factory=dict)
    """Players present at freeze end, and the side they played."""
    deaths: dict[str, int] = field(default_factory=dict)
    """Player key -> tick of their (first) death this round."""
    clutch: Clutch | None = None

    def survived(self, player_key: str) -> bool:
        """Present for the round and never killed in it."""
        return player_key in self.roster and player_key not in self.deaths


def build_round_states(match: NormalizedMatch) -> dict[int, RoundState]:
    """Reconstruct every round's participation, deaths and clutch situation."""
    rosters: dict[int, dict[str, Side]] = defaultdict(dict)
    for entry in match.roster:
        if entry.present_at_freeze:
            rosters[entry.round_num][entry.player_key] = entry.side

    kills_by_round: dict[int, list[KillNorm]] = defaultdict(list)
    for kill in match.kills:
        kills_by_round[kill.round_num].append(kill)

    states: dict[int, RoundState] = {}
    for round_ in match.rounds:
        state = RoundState(round_num=round_.round_num, roster=dict(rosters[round_.round_num]))
        ordered = sorted(kills_by_round[round_.round_num], key=lambda k: (k.tick, k.src_idx))
        for kill in ordered:
            state.deaths.setdefault(kill.victim.key, kill.tick)
        state.clutch = _detect_clutch(state, ordered, round_.winner_side)
        states[round_.round_num] = state
    return states


def _detect_clutch(
    state: RoundState, ordered_kills: list[KillNorm], winner_side: Side | None
) -> Clutch | None:
    """Find the first player left as the sole survivor of their side.

    A side that fielded one player for the whole round never "becomes" the last
    survivor and does not register a clutch. Simultaneous deaths do not either: if the
    would-be clutcher dies on the same tick as their last teammate, they were never
    actually alone.
    """
    alive: dict[str, Side] = dict(state.roster)
    if not alive:
        return None
    # A side must start with more than one player for a clutch to be possible.
    starting: dict[Side, int] = defaultdict(int)
    for side in alive.values():
        starting[side] += 1

    for kill in ordered_kills:
        if kill.victim.key not in alive:
            continue
        del alive[kill.victim.key]
        counts: dict[Side, list[str]] = {"T": [], "CT": []}
        for key, side in alive.items():
            counts[side].append(key)
        for side in ("T", "CT"):
            mine, theirs = counts[side], counts["CT" if side == "T" else "T"]
            if len(mine) != 1 or not theirs or starting[side] < 2:  # noqa: PLR2004
                continue
            survivor = mine[0]
            if state.deaths.get(survivor) == kill.tick:
                continue  # died in the same tick as the last teammate: never alone
            return Clutch(
                round_num=state.round_num,
                player_key=survivor,
                opponents=min(len(theirs), MAX_CLUTCH_OPPONENTS),
                won=winner_side is not None and winner_side == side,
            )
    return None


def rounds_present(match: NormalizedMatch) -> dict[str, int]:
    """How many scored rounds each player was actually present for.

    Reported alongside the metrics for transparency. It is deliberately *not* the ADR or
    KAST denominator: both use the match's scored round count, matching the convention
    every public scoreboard uses, which understates a mid-match substitute.
    """
    scored = {r.round_num for r in match.scored_rounds}
    counts: dict[str, int] = defaultdict(int)
    for entry in match.roster:
        if entry.round_num in scored and entry.present_at_freeze:
            counts[entry.player_key] += 1
    return dict(counts)


def roster_entries_by_round(match: NormalizedMatch) -> dict[int, list[RosterEntry]]:
    out: dict[int, list[RosterEntry]] = defaultdict(list)
    for entry in match.roster:
        out[entry.round_num].append(entry)
    return dict(out)
