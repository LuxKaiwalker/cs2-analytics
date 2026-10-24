"""Damage capping — the single most consequential calculation in the app.

Demos report raw damage that routinely exceeds the victim's remaining health (up to 199
against a 100 HP target in the reference demo), so summing raw values inflates ADR
substantially. On the real demo, capping takes 12 642 raw damage down to 7 748.
"""

from __future__ import annotations

from app.parsing.normalize import apply_damage_caps
from tests import factories as f


def test_two_overkill_hits_cap_at_one_hundred() -> None:
    """Two 80-damage hits on a 100 HP target total 100, not 160."""
    victim, attacker = f.player("victim"), f.player("attacker")
    rows = apply_damage_caps(
        [
            f.damage(0, 100, 1, attacker, victim, 80, health_post=20),
            f.damage(1, 200, 1, attacker, victim, 80, health_post=0),
        ]
    )
    assert [r.dmg_health_effective for r in rows] == [80, 20]
    assert sum(r.dmg_health_effective for r in rows) == 100


def test_single_hit_exceeding_health_is_truncated() -> None:
    """A 199-damage Deagle hit on a full-health target credits 100."""
    victim, attacker = f.player("victim"), f.player("attacker")
    rows = apply_damage_caps([f.damage(0, 100, 1, attacker, victim, 199, health_post=0)])
    assert rows[0].dmg_health_effective == 100
    assert rows[0].dmg_health_raw == 199, "the raw value must be preserved for display"


def test_same_tick_overkill_is_resolved_by_source_order() -> None:
    """Two simultaneous lethal hits: the earlier source row takes the health.

    Without a deterministic tiebreaker this would be arbitrary, and ADR would differ
    between runs. ``src_idx`` is the demo's own message order and settles it.
    """
    victim = f.player("victim")
    first, second = f.player("first"), f.player("second")
    rows = apply_damage_caps(
        [
            f.damage(0, 500, 1, first, victim, 100, health_post=0),
            f.damage(1, 500, 1, second, victim, 100, health_post=0),
        ]
    )
    assert [r.dmg_health_effective for r in rows] == [100, 0]


def test_same_tick_order_is_independent_of_list_order() -> None:
    """Shuffling the input list must not change the outcome — only ``src_idx`` decides."""
    victim = f.player("victim")
    first, second = f.player("first"), f.player("second")
    rows = apply_damage_caps(
        [
            f.damage(1, 500, 1, second, victim, 100, health_post=0),
            f.damage(0, 500, 1, first, victim, 100, health_post=0),
        ]
    )
    by_idx = {r.src_idx: r.dmg_health_effective for r in rows}
    assert by_idx == {0: 100, 1: 0}


def test_missing_health_post_falls_back_to_subtraction() -> None:
    """With no reported health, the cap is tracked by subtracting what was credited."""
    victim, attacker = f.player("victim"), f.player("attacker")
    rows = apply_damage_caps(
        [
            f.damage(0, 100, 1, attacker, victim, 30, health_post=None),
            f.damage(1, 200, 1, attacker, victim, 200, health_post=None),
        ]
    )
    assert [r.dmg_health_effective for r in rows] == [30, 70]


def test_health_post_resets_each_round() -> None:
    """A victim starts every round at full health."""
    victim, attacker = f.player("victim"), f.player("attacker")
    rows = apply_damage_caps(
        [
            f.damage(0, 100, 1, attacker, victim, 100, health_post=0),
            f.damage(1, 10_100, 2, attacker, victim, 100, health_post=0),
        ]
    )
    assert [r.dmg_health_effective for r in rows] == [100, 100]


def test_damage_is_capped_per_victim_not_globally() -> None:
    """Two victims each absorb up to 100 in the same round."""
    attacker = f.player("attacker")
    v1, v2 = f.player("v1"), f.player("v2")
    rows = apply_damage_caps(
        [
            f.damage(0, 100, 1, attacker, v1, 150, health_post=0),
            f.damage(1, 150, 1, attacker, v2, 150, health_post=0),
        ]
    )
    assert sum(r.dmg_health_effective for r in rows) == 200


def test_health_post_above_previous_cap_does_not_grant_extra_health() -> None:
    """A rising reported health (healing, or a bad read) cannot exceed 100 per round."""
    victim, attacker = f.player("victim"), f.player("attacker")
    rows = apply_damage_caps(
        [
            f.damage(0, 100, 1, attacker, victim, 50, health_post=50),
            f.damage(1, 200, 1, attacker, victim, 500, health_post=0),
        ]
    )
    assert sum(r.dmg_health_effective for r in rows) == 100


def test_capped_damage_never_exceeds_full_health_per_victim_round() -> None:
    """Property: no (round, victim) pair can absorb more than 100 health."""
    import random

    rng = random.Random(1234)
    attackers = [f.player(f"a{i}") for i in range(3)]
    victims = [f.player(f"v{i}") for i in range(3)]
    rows = [
        f.damage(
            i,
            rng.randrange(1, 9000),
            rng.randrange(1, 4),
            rng.choice(attackers),
            rng.choice(victims),
            rng.randrange(1, 250),
            health_post=rng.choice([None, 0, 10, 50, 99]),
        )
        for i in range(400)
    ]
    capped = apply_damage_caps(rows)
    totals: dict[tuple[int, str], int] = {}
    for row in capped:
        key = (row.round_num, row.victim.key)
        totals[key] = totals.get(key, 0) + row.dmg_health_effective
    assert totals, "the property test must actually exercise some rows"
    assert all(total <= 100 for total in totals.values()), totals
