"""End-to-end checks against a genuine CS2 demo.

Two independent oracles are used, which is the point of this file:

1. **The parser's own scoreboard.** We reimplement its documented definitions rather
   than calling its aggregation, so an exact match across every counting metric is
   strong evidence that our implementation is right — and any divergence is listed
   explicitly below rather than absorbed into a tolerance.
2. **A published third-party scoreboard** (csstats.gg, recorded in the fixture
   manifest). This catches the case where we and the parser agree with each other but
   both disagree with the game.

The demo is a Valve matchmaking match on de_mirage that finished 13-0. Despite the
one-sided score it is a 13-round MR12 match, so it does contain the halftime side swap —
the per-round team mapping is genuinely exercised here, not only in the synthetic tests.
"""

from __future__ import annotations

import pytest

from app.analytics.compute import MatchAnalytics
from app.analytics.events import build_events
from app.analytics.trades import detect_trades
from app.parsing.model import NormalizedMatch

pytestmark = pytest.mark.fixture_demo

#: Metrics where our definition intentionally differs from the parser's aggregation.
#: Each is a decision recorded in docs/METRICS.md, not an unexplained mismatch.
EXPECTED_DIVERGENCES = {
    "headshot_pct": "we report null with no kills; the parser reports 0.0",
    "assists": "we report kill assists only; the parser's total includes flash assists",
}


# --------------------------------------------------------------- metadata


def test_the_demo_parses_and_reports_the_expected_match(
    normalized: NormalizedMatch, analytics: MatchAnalytics
) -> None:
    assert normalized.meta.map_name == "de_mirage"
    assert normalized.meta.parser_name == "awpy"
    assert normalized.meta.tick_rate == 64.0
    assert normalized.meta.tick_rate_source == "header", "real timing, not the fallback"
    assert analytics.round_count == 13
    assert len(analytics.players) == 10, "ten players, excluding the SourceTV recorder"


def test_the_demo_recorder_is_not_on_the_scoreboard(
    normalized: NormalizedMatch, analytics: MatchAnalytics
) -> None:
    """The recorder appears in the parser's roster with Steam ID 0 and must be excluded."""
    assert "DemoRecorder" not in {p.name for p in analytics.players}
    assert all(not p.is_bot for p in analytics.players)


def test_the_published_scoreline_is_reconstructed(
    analytics: MatchAnalytics, fixture_entry: object
) -> None:
    """13-0 as published, with team identity surviving the halftime swap."""
    scores = sorted((analytics.team_a_score, analytics.team_b_score), reverse=True)
    assert scores == [13, 0]
    expected = getattr(fixture_entry, "result", None)
    if expected:
        assert sorted(int(p) for p in expected.split("-"))[::-1] == scores
    assert analytics.team_a_score + analytics.team_b_score == analytics.round_count


def test_the_halftime_side_swap_is_detected(normalized: NormalizedMatch) -> None:
    """Every player changes side at round 13, but not team.

    This is the path most likely to be wrong, and the reason this demo is worth testing
    against despite the lopsided score.
    """
    by_round = {r.round_num: r for r in normalized.rounds}
    assert by_round[12].team_ct != by_round[13].team_ct, "sides swap at the half"
    assert by_round[12].half_index == 0
    assert by_round[13].half_index == 1
    assert normalized.meta.regulation_rounds == 24, "MR12, derived from the observed swap"
    assert normalized.meta.has_overtime is False

    first_half_sides = {e.player_key: e.side for e in normalized.roster if e.round_num == 1}
    second_half_sides = {e.player_key: e.side for e in normalized.roster if e.round_num == 13}
    assert first_half_sides and second_half_sides
    for key, side in first_half_sides.items():
        assert second_half_sides[key] != side, f"{key} should have swapped side"

    teams = {}
    for entry in normalized.roster:
        teams.setdefault(entry.player_key, set()).add(entry.team)
    assert all(len(v) == 1 for v in teams.values()), "team identity must never change"


def test_the_match_parses_without_anomalies(analytics: MatchAnalytics) -> None:
    assert [a.code for a in analytics.anomalies] == []


def test_dataset_availability_is_recorded(normalized: NormalizedMatch) -> None:
    for name in ("rounds", "kills", "damages", "blinds", "shots", "bomb"):
        entry = normalized.availability.get(name)
        assert entry is not None, f"{name} availability must be recorded"
        assert entry.usable, f"{name} should be usable in this demo"
        assert entry.row_count > 0


# ------------------------------------------------------- oracle 1: the parser


def test_our_scoreboard_matches_the_parsers_exactly(
    normalized: NormalizedMatch, analytics: MatchAnalytics, demo_path: object
) -> None:
    """Every counting metric must agree with the parser's own aggregation.

    Our analytics are computed independently from the normalized event model, so this is
    a genuine cross-check rather than a tautology.
    """
    from awpy import Demo

    reference = {row["name"]: row for row in Demo(demo_path).stats.iter_rows(named=True)}
    assert set(reference) == {p.name for p in analytics.players}

    mismatches: list[str] = []
    for player in analytics.players:
        expected = reference[player.name]
        for field in (
            "kills",
            "deaths",
            "headshot_kills",
            "opening_kills",
            "opening_deaths",
            "traded_deaths",
            "utility_damage",
            "flashes_thrown",
            "enemies_flashed",
            "flash_assists",
            "rounds_played",
        ):
            ours = getattr(player, "rounds_present" if field == "rounds_played" else field)
            if ours != expected[field]:
                mismatches.append(f"{player.name}.{field}: ours={ours} parser={expected[field]}")
        for field in ("adr", "kast", "flash_duration_dealt"):
            ours = getattr(player, field)
            if ours is None or abs(ours - expected[field]) > 0.05:
                mismatches.append(f"{player.name}.{field}: ours={ours} parser={expected[field]}")
        # Documented divergence: the parser's assist total includes flash assists.
        total_assists = player.assists + player.flash_assists
        if total_assists != expected["assists"]:
            mismatches.append(
                f"{player.name}.assists_total: ours={total_assists} parser={expected['assists']}"
            )
        # Documented divergence: null rather than 0.0 when there are no kills.
        if player.kills and abs((player.headshot_pct or 0) - expected["headshot_pct"]) > 0.05:
            mismatches.append(
                f"{player.name}.headshot_pct: ours={player.headshot_pct} "
                f"parser={expected['headshot_pct']}"
            )
        elif not player.kills:
            assert player.headshot_pct is None, EXPECTED_DIVERGENCES["headshot_pct"]

    assert not mismatches, "scoreboard diverges from the parser:\n  " + "\n  ".join(mismatches)


def test_our_trade_detection_matches_the_parsers_row_for_row(
    normalized: NormalizedMatch, demo_path: object
) -> None:
    """Not just the totals — the same individual kills must be flagged.

    Equal counts could hide two compensating errors, so this compares the actual rows.
    """
    import polars as pl
    from awpy import Demo

    kills = Demo(demo_path).kills.with_row_index("src_idx")
    parser_traded = {
        (row["tick"], row["src_idx"])
        for row in kills.filter(pl.col("victim_traded")).iter_rows(named=True)
    }
    parser_trades = {
        (row["tick"], row["src_idx"])
        for row in kills.filter(pl.col("is_trade")).iter_rows(named=True)
    }

    result = detect_trades(normalized.kills, normalized.meta.tick_rate)
    ours_traded = {
        (normalized.kills[i].tick, normalized.kills[i].src_idx) for i in result.traded_death_indices
    }
    ours_trades = {
        (normalized.kills[i].tick, normalized.kills[i].src_idx) for i in result.trade_kill_indices
    }

    assert ours_traded == parser_traded, (
        f"traded deaths differ: only ours {sorted(ours_traded - parser_traded)}, "
        f"only parser {sorted(parser_traded - ours_traded)}"
    )
    assert ours_trades == parser_trades
    assert len(ours_traded) == len(ours_trades), "each trade avenges exactly one death"


# -------------------------------------------- oracle 2: the published scoreboard


def test_our_scoreboard_matches_the_published_one(
    analytics: MatchAnalytics, ground_truth: dict
) -> None:
    """Check against csstats.gg, with each tolerance justified in the manifest notes.

    This catches the failure mode where we and the parser agree but both differ from the
    game. Tolerances are per-metric and deliberately tight.
    """
    by_name = {p.name: p for p in analytics.players}
    checks = {
        "kills": (lambda p: p.kills, 0),
        "deaths": (lambda p: p.deaths, 0),
        # Published assists are kill assists only, which is exactly our `assists`.
        "assists": (lambda p: p.assists, 0),
        # ADR differs by a few points because post-round damage is counted here, as the
        # parser does; the published figure appears to exclude it.
        "adr": (lambda p: p.adr, 4.0),
        "hs_pct": (lambda p: p.headshot_pct, 1.0),
        "kast": (lambda p: p.kast, 0.1),
        # The published count appears to apply a minimum blind duration.
        "enemies_flashed": (lambda p: p.enemies_flashed, 1),
    }

    checked = 0
    failures: list[str] = []
    for expected in ground_truth["players"]:
        player = by_name.get(expected["name"])
        assert player is not None, f"{expected['name']} missing from our scoreboard"
        for key, (accessor, tolerance) in checks.items():
            if key not in expected:
                continue
            ours = accessor(player)
            assert ours is not None, f"{expected['name']}.{key} should not be unknown"
            if abs(ours - expected[key]) > tolerance:
                failures.append(
                    f"{expected['name']}.{key}: ours={ours} published={expected[key]} "
                    f"(tolerance {tolerance})"
                )
            checked += 1
    assert checked >= 10, "the ground truth should cover a meaningful number of values"
    assert not failures, "published scoreboard diverges:\n  " + "\n  ".join(failures)


# ------------------------------------------------------------- invariants


def test_no_victim_absorbs_more_than_full_health_in_a_round(
    normalized: NormalizedMatch,
) -> None:
    """The capping invariant, checked against real overkill data.

    Raw damage in this demo totals far more than the capped figure, so this is a live
    check rather than a formality.
    """
    totals: dict[tuple[int, str], int] = {}
    for damage in normalized.damages:
        key = (damage.round_num, damage.victim.key)
        totals[key] = totals.get(key, 0) + damage.dmg_health_effective
    offenders = {k: v for k, v in totals.items() if v > 100}
    assert not offenders, offenders

    raw = sum(d.dmg_health_raw for d in normalized.damages)
    capped = sum(d.dmg_health_effective for d in normalized.damages)
    assert capped < raw, "this demo contains overkill damage, so capping must reduce the total"


def test_self_kills_are_not_misclassified_as_team_kills(
    normalized: NormalizedMatch,
) -> None:
    """This demo ends with five post-match world suicides.

    They share the victim's side, so a predicate that checked team kills first would
    report five team kills that never happened.
    """
    self_kills = [k for k in normalized.kills if k.is_self_kill]
    assert len(self_kills) == 5
    assert all(not k.is_team_kill for k in self_kills)
    assert all(not k.is_valid_kill for k in self_kills)
    assert sum(1 for k in normalized.kills if k.is_team_kill) == 0


def test_post_round_events_are_flagged_but_retained(normalized: NormalizedMatch) -> None:
    """Dropping them would silently remove real damage from ADR."""
    assert sum(1 for d in normalized.damages if d.is_post_round) > 0
    assert sum(1 for k in normalized.kills if k.is_post_round) == 5


def test_every_event_is_assigned_to_exactly_one_round(
    normalized: NormalizedMatch,
) -> None:
    round_numbers = {r.round_num for r in normalized.rounds}
    for collection in (normalized.kills, normalized.damages, normalized.blinds):
        for row in collection:
            assert row.round_num in round_numbers


def test_the_event_feed_is_dense_and_ordered(normalized: NormalizedMatch) -> None:
    events = build_events(normalized)
    assert [e.seq for e in events] == list(range(len(events)))
    keys = [(e.round_num, e.tick) for e in events]
    assert keys == sorted(keys)
    counts = {
        "kill": len(normalized.kills),
        "damage": len(normalized.damages),
        "flash": len(normalized.blinds),
        "utility_thrown": len(normalized.utility),
        "bomb": len(normalized.objectives),
    }
    for event_type, expected in counts.items():
        actual = sum(1 for e in events if e.event_type == event_type)
        assert actual == expected, f"{event_type}: {actual} in feed, {expected} normalized"


def test_utility_is_attributed_to_players(normalized: NormalizedMatch) -> None:
    """The trajectory table has no thrower in this demo, so throws come from weapon fire.

    If that sourcing regressed, every utility statistic would silently read zero.
    """
    assert normalized.utility
    assert all(u.thrower is not None for u in normalized.utility)
    flashes = [u for u in normalized.utility if u.utility_type == "flashbang"]
    assert len(flashes) == 9, "nine flashbangs were thrown in this match"


def test_performance_is_within_the_measured_envelope(demo_path: object) -> None:
    """Guards the upload cap, which is derived from the memory this parse actually uses."""
    import resource
    import time

    from app.analytics.compute import compute
    from app.parsing.awpy_parser import get_parser

    started = time.perf_counter()
    match = get_parser().parse(str(demo_path))
    compute(match)
    elapsed = time.perf_counter() - started
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    size_mb = demo_path.stat().st_size / 1e6  # type: ignore[attr-defined]

    assert elapsed < 60, f"parse took {elapsed:.1f}s for an {size_mb:.0f} MB demo"
    assert peak_mb < 2048, f"peak RSS {peak_mb:.0f} MB exceeds the expected envelope"
