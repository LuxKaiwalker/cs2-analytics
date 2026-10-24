"""Trade detection: window boundaries, one-death-one-trade, and the posthumous case."""

from __future__ import annotations

from app.analytics.trades import detect_trades
from tests import factories as f
from tests.factories import TICK_RATE, TRADE_WINDOW_TICKS


def _victim_keys(kills: list, result: object) -> set[str]:
    return {kills[i].victim.key for i in result.traded_death_indices}  # type: ignore[attr-defined]


def test_revenge_exactly_on_the_window_boundary_is_a_trade() -> None:
    """5.25 s is inclusive: at exactly 336 ticks (64 tick) the trade counts."""
    ct, ct2, t = f.player("ct"), f.player("ct2"), f.player("t")
    kills = [
        f.kill(0, 1000, 1, t, ct, attacker_side="T", victim_side="CT"),
        f.kill(1, 1000 + TRADE_WINDOW_TICKS, 1, ct2, t, attacker_side="CT", victim_side="T"),
    ]
    result = detect_trades(kills, TICK_RATE)
    assert result.traded_death_indices == frozenset({0})
    assert result.trade_kill_indices == frozenset({1})


def test_one_tick_past_the_window_is_not_a_trade() -> None:
    ct, ct2, t = f.player("ct"), f.player("ct2"), f.player("t")
    kills = [
        f.kill(0, 1000, 1, t, ct, attacker_side="T", victim_side="CT"),
        f.kill(1, 1000 + TRADE_WINDOW_TICKS + 1, 1, ct2, t, attacker_side="CT", victim_side="T"),
    ]
    result = detect_trades(kills, TICK_RATE)
    assert not result.traded_death_indices
    assert not result.trade_kill_indices


def test_window_scales_with_tick_rate() -> None:
    """The window is 5.25 seconds, not a fixed tick count, so 128-tick demos differ."""
    ct, ct2, t = f.player("ct"), f.player("ct2"), f.player("t")
    gap = TRADE_WINDOW_TICKS + 10  # inside 5.25 s at 128 tick, outside it at 64
    kills = [
        f.kill(0, 1000, 1, t, ct, attacker_side="T", victim_side="CT"),
        f.kill(1, 1000 + gap, 1, ct2, t, attacker_side="CT", victim_side="T"),
    ]
    assert not detect_trades(kills, 64.0).traded_death_indices
    assert detect_trades(kills, 128.0).traded_death_indices == frozenset({0})


def test_revenge_must_kill_the_player_who_got_the_kill() -> None:
    """Killing some other enemy does not trade the teammate's death."""
    ct, ct2, t, t2 = f.player("ct"), f.player("ct2"), f.player("t"), f.player("t2")
    kills = [
        f.kill(0, 1000, 1, t, ct, attacker_side="T", victim_side="CT"),
        f.kill(1, 1100, 1, ct2, t2, attacker_side="CT", victim_side="T"),
    ]
    assert not detect_trades(kills, TICK_RATE).traded_death_indices


def test_each_death_is_traded_only_once() -> None:
    """Two avengers cannot both claim the same death."""
    ct, ct2, ct3, t = f.player("ct"), f.player("ct2"), f.player("ct3"), f.player("t")
    kills = [
        f.kill(0, 1000, 1, t, ct, attacker_side="T", victim_side="CT"),
        f.kill(1, 1100, 1, ct2, t, attacker_side="CT", victim_side="T"),
        f.kill(2, 1150, 1, ct3, t, attacker_side="CT", victim_side="T"),
    ]
    result = detect_trades(kills, TICK_RATE)
    assert result.traded_death_indices == frozenset({0})
    assert result.trade_kill_indices == frozenset({1}), "the first avenger claims the death"


def test_revenge_claims_the_earliest_qualifying_death() -> None:
    """With two eligible teammate deaths, the earlier one is the one traded."""
    ct, ct2, ct3, t = f.player("ct"), f.player("ct2"), f.player("ct3"), f.player("t")
    kills = [
        f.kill(0, 1000, 1, t, ct, attacker_side="T", victim_side="CT"),
        f.kill(1, 1050, 1, t, ct2, attacker_side="T", victim_side="CT"),
        f.kill(2, 1100, 1, ct3, t, attacker_side="CT", victim_side="T"),
    ]
    result = detect_trades(kills, TICK_RATE)
    assert result.traded_death_indices == frozenset({0})


def test_same_tick_ties_break_on_source_order() -> None:
    """Two teammate deaths on one tick: the lower source index is traded."""
    ct, ct2, ct3, t = f.player("ct"), f.player("ct2"), f.player("ct3"), f.player("t")
    kills = [
        f.kill(0, 1000, 1, t, ct, attacker_side="T", victim_side="CT"),
        f.kill(1, 1000, 1, t, ct2, attacker_side="T", victim_side="CT"),
        f.kill(2, 1100, 1, ct3, t, attacker_side="CT", victim_side="T"),
    ]
    assert detect_trades(kills, TICK_RATE).traded_death_indices == frozenset({0})


def test_world_deaths_are_untradeable() -> None:
    """A fall death has no killer, so there is nobody to avenge it on."""
    ct, ct2, t = f.player("ct"), f.player("ct2"), f.player("t")
    kills = [
        f.kill(0, 1000, 1, None, ct, victim_side="CT"),
        f.kill(1, 1100, 1, ct2, t, attacker_side="CT", victim_side="T"),
    ]
    assert not detect_trades(kills, TICK_RATE).traded_death_indices


def test_a_player_can_trade_their_own_death_posthumously() -> None:
    """A grenade thrown before dying can kill the killer, restoring the man advantage.

    The reference demo contains exactly this: darkness01 dies at tick 18107 and their
    already-airborne grenade kills the killer at 18182. Upstream counts it, and so do we.
    """
    ct, t = f.player("ct"), f.player("t")
    kills = [
        f.kill(0, 18107, 6, t, ct, attacker_side="T", victim_side="CT"),
        f.kill(1, 18182, 6, ct, t, attacker_side="CT", victim_side="T", weapon="hegrenade"),
    ]
    result = detect_trades(kills, TICK_RATE)
    assert result.traded_death_indices == frozenset({0})
    assert result.trade_kill_indices == frozenset({1})


def test_a_suicide_avenges_nothing() -> None:
    """Falling to your death is not a revenge kill, even inside the window."""
    ct, ct2, t = f.player("ct"), f.player("ct2"), f.player("t")
    kills = [
        f.kill(0, 1000, 1, t, ct, attacker_side="T", victim_side="CT"),
        f.kill(1, 1100, 1, t, t, attacker_side="T", victim_side="T", weapon="world"),
        f.kill(2, 1150, 1, ct2, t, attacker_side="CT", victim_side="T"),
    ]
    result = detect_trades(kills, TICK_RATE)
    assert result.trade_kill_indices == frozenset({2}), "only the real revenge kill trades"


def test_trades_do_not_cross_round_boundaries() -> None:
    """A kill early in round 2 cannot trade a death at the end of round 1."""
    ct, ct2, t = f.player("ct"), f.player("ct2"), f.player("t")
    kills = [
        f.kill(0, 9_900, 1, t, ct, attacker_side="T", victim_side="CT"),
        f.kill(1, 10_050, 2, ct2, t, attacker_side="CT", victim_side="T"),
    ]
    assert not detect_trades(kills, TICK_RATE).traded_death_indices


def test_killing_an_enemy_who_killed_nobody_is_not_a_trade() -> None:
    ct, t = f.player("ct"), f.player("t")
    kills = [f.kill(0, 1000, 1, ct, t, attacker_side="CT", victim_side="T")]
    assert not detect_trades(kills, TICK_RATE).trade_kill_indices


def test_team_kills_are_not_avenged() -> None:
    """A teammate killing a teammate is not an enemy death to avenge."""
    ct, ct2, ct3 = f.player("ct"), f.player("ct2"), f.player("ct3")
    kills = [
        f.kill(0, 1000, 1, ct, ct2, attacker_side="CT", victim_side="CT"),
        f.kill(1, 1100, 1, ct3, ct, attacker_side="CT", victim_side="CT"),
    ]
    assert not detect_trades(kills, TICK_RATE).traded_death_indices
