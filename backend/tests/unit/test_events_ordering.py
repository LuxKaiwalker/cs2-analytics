"""The unified event feed: round assignment and deterministic ordering."""

from __future__ import annotations

from app.analytics.events import EventType, build_events
from app.parsing.model import RoundNorm
from app.parsing.normalize import RoundLocator
from tests import factories as f


class TestRoundLocator:
    """Round assignment partitions the tick timeline rather than matching intervals."""

    def _locator(self) -> RoundLocator:
        return RoundLocator(
            [
                RoundNorm(round_num=1, start_tick=65, end_tick=2993, official_end_tick=3441),
                RoundNorm(round_num=2, start_tick=3441, end_tick=6202, official_end_tick=6650),
            ]
        )

    def test_warmup_ticks_belong_to_no_round(self) -> None:
        assert self._locator().round_for(10) is None

    def test_a_tick_after_the_round_was_decided_still_belongs_to_it(self) -> None:
        """Kills and damage do happen after a round is won.

        Interval matching would drop them, and they would vanish from ADR — 4% of
        in-round damage rows in the reference demo.
        """
        locator = self._locator()
        assert locator.round_for(3000) == 1
        assert locator.is_post_round(1, 3000) is True

    def test_the_last_round_extends_indefinitely(self) -> None:
        """Post-match world deaths land in the final round, matching upstream."""
        assert self._locator().round_for(999_999) == 2

    def test_round_boundaries_are_half_open(self) -> None:
        locator = self._locator()
        assert locator.round_for(3440) == 1
        assert locator.round_for(3441) == 2

    def test_live_play_is_not_flagged_post_round(self) -> None:
        locator = self._locator()
        assert locator.is_post_round(1, 2000) is False
        assert locator.is_post_round(1, 2993) is False, "the deciding tick is still live"


def _sample_match() -> object:
    ct, t = [f.player(f"ct{i}") for i in range(1, 6)], [f.player(f"t{i}") for i in range(1, 6)]
    rounds = [f.round_(1), f.round_(2)]
    kills = [f.kill(0, 1_500, 1, ct[0], t[0], attacker_side="CT", victim_side="T")]
    damages = [
        f.damage(0, 1_500, 1, ct[0], t[0], 100, health_post=0),
        f.damage(1, 1_400, 1, ct[1], t[1], 30, health_post=70),
    ]
    blinds = [f.blind(0, 1_200, 1, ct[0], t[0], 2.0)]
    utility = [f.throw(0, 1_100, 1, ct[0], "flashbang")]
    objectives = [f.objective(0, 1_800, 1, "finish_plant", t[1], bombsite="A")]
    return f.match(
        rounds=rounds,
        roster=f.roster_for(rounds, ct, t),
        kills=kills,
        damages=damages,
        blinds=blinds,
        utility=utility,
        objectives=objectives,
    )


def test_seq_is_dense_unique_and_starts_at_zero() -> None:
    events = build_events(_sample_match())  # type: ignore[arg-type]
    assert [e.seq for e in events] == list(range(len(events)))


def test_events_are_non_decreasing_in_round_then_tick() -> None:
    events = build_events(_sample_match())  # type: ignore[arg-type]
    keys = [(e.round_num, e.tick) for e in events]
    assert keys == sorted(keys)


def test_round_seq_restarts_within_each_round() -> None:
    events = build_events(_sample_match())  # type: ignore[arg-type]
    for round_num in {e.round_num for e in events}:
        in_round = [e.round_seq for e in events if e.round_num == round_num]
        assert in_round == list(range(len(in_round)))


def test_damage_is_listed_before_the_kill_it_caused() -> None:
    """Same tick, so no evidence decides it; the reading convention does."""
    events = build_events(_sample_match())  # type: ignore[arg-type]
    same_tick = [e for e in events if e.tick == 1_500]
    types = [e.event_type for e in same_tick]
    assert types.index(EventType.DAMAGE) < types.index(EventType.KILL)


def test_every_round_is_bracketed_by_a_start_and_an_end() -> None:
    events = build_events(_sample_match())  # type: ignore[arg-type]
    for round_num in (1, 2):
        in_round = [e for e in events if e.round_num == round_num]
        assert in_round[0].event_type == EventType.ROUND_START
        assert in_round[-1].event_type == EventType.ROUND_END


def test_time_in_round_is_negative_during_freeze_time() -> None:
    """Kept signed on purpose: a buy-time event genuinely precedes play."""
    events = build_events(_sample_match())  # type: ignore[arg-type]
    start = next(e for e in events if e.event_type == EventType.ROUND_START)
    assert start.time_in_round_s is not None
    assert start.time_in_round_s < 0


def test_damage_rows_carry_both_raw_and_effective_values() -> None:
    """Showing only one invites the wrong conclusion, so the feed keeps both."""
    ct, t = f.player("ct"), f.player("t")
    rounds = [f.round_(1)]
    damages = [f.damage(0, 1_000, 1, ct, t, 199, health_post=0)]
    events = build_events(f.match(rounds=rounds, damages=damages))
    row = next(e for e in events if e.event_type == EventType.DAMAGE)
    assert row.damage_health == 100, "the summable, capped value"
    assert row.extra["damage_raw"] == 199, "what the demo reported"


def test_every_normalized_event_appears_exactly_once() -> None:
    """Nothing is silently dropped between the model and the feed."""
    match = _sample_match()
    events = build_events(match)  # type: ignore[arg-type]
    counts = {t: sum(1 for e in events if e.event_type == t) for t in EventType}
    assert counts[EventType.KILL] == len(match.kills)  # type: ignore[attr-defined]
    assert counts[EventType.DAMAGE] == len(match.damages)  # type: ignore[attr-defined]
    assert counts[EventType.FLASH] == len(match.blinds)  # type: ignore[attr-defined]
    assert counts[EventType.UTILITY_THROWN] == len(match.utility)  # type: ignore[attr-defined]
    assert counts[EventType.BOMB] == len(match.objectives)  # type: ignore[attr-defined]
    assert counts[EventType.ROUND_START] == len(match.rounds)  # type: ignore[attr-defined]
