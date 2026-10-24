"""Parser-independent normalization helpers.

These operate on the normalized model and contain no parser imports, so they are
unit-testable with hand-written rows and reusable by any future parser backend.
"""

from __future__ import annotations

import bisect
from collections import defaultdict
from dataclasses import replace

from app.parsing.model import DamageNorm, RoundNorm

#: A player's health at the start of a round, used as the initial damage cap.
FULL_HEALTH = 100


class RoundLocator:
    """Maps an arbitrary demo tick to a round number.

    The tick timeline is **partitioned**, not treated as a set of
    ``[start_tick, end_tick]`` intervals: a round owns every tick from its start up to
    the next round's start, and the final round extends forever. Interval matching would
    silently drop the kills and damage that occur after a round is decided — 4% of
    in-round damage rows in the reference demo — and those losses would land straight in
    ADR. Ticks before the first round are warmup and map to ``None``.
    """

    def __init__(self, rounds: list[RoundNorm]) -> None:
        ordered = sorted(rounds, key=lambda r: r.start_tick)
        self._starts = [r.start_tick for r in ordered]
        self._numbers = [r.round_num for r in ordered]
        self._decided = {r.round_num: r.end_tick for r in ordered}

    def round_for(self, tick: int) -> int | None:
        """The round owning ``tick``, or ``None`` for pre-match warmup."""
        if not self._starts or tick < self._starts[0]:
            return None
        index = bisect.bisect_right(self._starts, tick) - 1
        return self._numbers[index]

    def is_post_round(self, round_num: int, tick: int) -> bool:
        """Whether ``tick`` falls after the round was decided.

        The window between a round being decided (``end_tick``) and officially ending
        (``official_end_tick``, roughly the next freeze start) is real playtime: players
        keep shooting, and the reference demo has 8 damage rows and 5 world deaths there.
        Those events are kept — they count toward damage, as they do upstream — but
        flagged so the UI can distinguish them from live play.
        """
        decided = self._decided.get(round_num)
        return decided is not None and tick > decided


def apply_damage_caps(damages: list[DamageNorm]) -> list[DamageNorm]:
    """Fill :attr:`DamageNorm.dmg_health_effective` by capping each hit at remaining health.

    Reported damage routinely exceeds the victim's remaining health — a Deagle hit in the
    reference demo reports 199 against a 100 HP target — so summing the raw values would
    inflate ADR substantially. Within each ``(round, victim)`` the hits are walked in
    ``(tick, src_idx)`` order and each is credited at most the health still standing.

    The victim's reported ``health_post`` is the authority for the next cap when present.
    The parser's ``health_pre`` is deliberately **not** used: upstream documents it as a
    reconstruction (``health_post + damage``, clamped to 100), so two 80-damage hits
    would both see a 100 HP target and credit 160.

    ``src_idx`` ordering is what makes simultaneous hits deterministic: when two attackers
    land lethal damage on the same tick, the earlier source row takes the remaining
    health and the later one is credited nothing.

    The next cap is the *lower* of the reported health and what remains after crediting
    the hit. CS2 has no mid-round healing, so a health value that rises within a round is
    always bad data — and trusting it would let a single victim absorb unbounded damage,
    silently inflating someone's ADR. Clamping makes "at most 100 health per victim per
    round" hold unconditionally, which is asserted as a property test.
    """
    by_victim_round: dict[tuple[int, str], list[int]] = defaultdict(list)
    for index, row in enumerate(damages):
        by_victim_round[(row.round_num, row.victim.key)].append(index)

    result = list(damages)
    for indices in by_victim_round.values():
        indices.sort(key=lambda i: (damages[i].tick, damages[i].src_idx))
        cap = FULL_HEALTH
        for i in indices:
            row = damages[i]
            effective = max(0, min(row.dmg_health_raw, cap))
            result[i] = replace(row, dmg_health_effective=effective)
            remaining = cap - effective
            if row.health_post is not None:
                remaining = min(row.health_post, remaining)
            cap = max(0, remaining)
    return result
