"""End-to-end checks against genuine CS2 demos.

Every downloaded fixture becomes its own set of test cases, so adding a demo extends
coverage without editing a test.

Two independent oracles are used, which is the point of this file:

1. **The parser's own scoreboard.** We reimplement its documented definitions rather than
   calling its aggregation, so an exact match across every counting metric is strong
   evidence — and any divergence is listed explicitly rather than absorbed into a
   tolerance.
2. **A published third-party scoreboard** recorded in the fixture manifest. This catches
   the case where we and the parser agree with each other but both disagree with the game.

Each platform reports a slightly different set of statistics (and computes assists
differently), so the ground-truth comparison is driven by a field registry and silently
skips what a given source does not publish.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from app.analytics.compute import PlayerStats
from app.analytics.events import build_events
from app.analytics.trades import detect_trades
from tests.integration.conftest import DemoCase

pytestmark = pytest.mark.fixture_demo


# --------------------------------------------------------------- ground truth


def _multikill_rounds(player: PlayerStats) -> int:
    """Rounds with two or more kills — what the league sites call "multi kills"."""
    return player.multikill_2k + player.multikill_3k + player.multikill_4k + player.multikill_5k


#: Ground-truth key -> (accessor, tolerance). Sources publish different fields and
#: different units (a headshot *count* versus a *percentage*), so each is mapped
#: explicitly and anything a source omits is simply not compared.
GROUND_TRUTH_FIELDS: dict[str, tuple[Callable[[PlayerStats], float | None], float]] = {
    "kills": (lambda p: p.kills, 0),
    "deaths": (lambda p: p.deaths, 0),
    # Published assists are kill assists only, which is exactly our `assists`.
    "assists": (lambda p: p.assists, 0),
    "headshots": (lambda p: p.headshot_kills, 0),
    "hs_pct": (lambda p: p.headshot_pct, 1.0),
    "flash_assists": (lambda p: p.flash_assists, 0),
    "multikill_rounds": (_multikill_rounds, 0),
    # ADR differs by a few points because post-round damage is counted here, as the
    # parser does; some sites appear to exclude it.
    "adr": (lambda p: p.adr, 4.0),
    "kast": (lambda p: p.kast, 1.0),
    # Some sites apply a minimum blind duration before counting an enemy flashed.
    "enemies_flashed": (lambda p: p.enemies_flashed, 1),
}


# ------------------------------------------------------------------- metadata


def test_the_demo_parses_into_a_usable_match(case: DemoCase) -> None:
    meta = case.normalized.meta
    assert meta.map_name == case.entry.map_name
    assert meta.parser_name == "awpy"
    assert meta.tick_rate > 0
    assert case.analytics.round_count > 0
    assert case.analytics.players, "a parsed match must have players"


def test_the_published_scoreline_is_reconstructed(case: DemoCase) -> None:
    expected = case.expected_scores()
    if expected is None:
        pytest.skip(f"{case.name} records no published result")
    actual = sorted((case.analytics.team_a_score, case.analytics.team_b_score), reverse=True)
    assert actual == expected


def test_team_wins_account_for_every_scored_round(case: DemoCase) -> None:
    total = case.analytics.team_a_score + case.analytics.team_b_score
    assert total == case.analytics.round_count


def test_the_demo_recorder_is_not_on_the_scoreboard(case: DemoCase) -> None:
    """The recorder appears in the parser's roster with Steam ID 0 and must be excluded."""
    assert "DemoRecorder" not in {p.name for p in case.analytics.players}


def test_dataset_availability_is_recorded(case: DemoCase) -> None:
    for name in ("rounds", "kills", "damages"):
        entry = case.normalized.availability.get(name)
        assert entry is not None, f"{name} availability must be recorded"
        assert entry.usable, f"{name} should be usable in this demo"
        assert entry.row_count > 0


def test_team_identity_never_changes_even_though_sides_do(case: DemoCase) -> None:
    """The whole point of reconstructing teams separately from sides."""
    teams: dict[str, set[str | None]] = {}
    sides: dict[str, set[str]] = {}
    for entry in case.normalized.roster:
        teams.setdefault(entry.player_key, set()).add(entry.team)
        sides.setdefault(entry.player_key, set()).add(entry.side)
    assert teams, "the roster must not be empty"
    assert all(len(v) == 1 for v in teams.values()), "a player's team must be stable"


# ------------------------------------------------- side swaps, halves, overtime


def test_a_match_that_reaches_halftime_swaps_sides(case: DemoCase) -> None:
    """Sides must flip for everyone at the half, while teams stay put."""
    rounds = {r.round_num: r for r in case.normalized.rounds}
    swap_rounds = [
        number
        for number in sorted(rounds)
        if number > 1
        and rounds[number].team_ct is not None
        and rounds[number - 1].team_ct is not None
        and rounds[number].team_ct != rounds[number - 1].team_ct
    ]
    if not swap_rounds:
        pytest.skip(f"{case.name} ended before any side swap")

    first_swap = swap_rounds[0]
    before = {e.player_key: e.side for e in case.normalized.roster if e.round_num == first_swap - 1}
    after = {e.player_key: e.side for e in case.normalized.roster if e.round_num == first_swap}
    shared = set(before) & set(after)
    assert shared, "the roster must span the swap"
    assert all(before[key] != after[key] for key in shared), "every player changes side"
    assert case.normalized.meta.regulation_rounds == (first_swap - 1) * 2


def test_overtime_is_detected_and_follows_regulation(case: DemoCase) -> None:
    overtime = [r for r in case.normalized.rounds if r.is_overtime]
    if not overtime:
        pytest.skip(f"{case.name} did not go to overtime")

    regulation = case.normalized.meta.regulation_rounds
    assert regulation is not None
    assert case.normalized.meta.has_overtime is True
    assert all(r.round_num > regulation for r in overtime)
    # Overtime swaps sides more often than regulation, so it spans several halves.
    assert len({r.half_index for r in overtime}) >= 1
    assert max(r.half_index for r in case.normalized.rounds) >= 2


def test_knife_rounds_are_excluded_from_every_denominator(case: DemoCase) -> None:
    knife = [r for r in case.normalized.rounds if r.is_knife_round]
    if not knife:
        pytest.skip(f"{case.name} has no knife round")

    assert case.analytics.round_count == len(case.normalized.rounds) - len(knife)
    knife_numbers = {r.round_num for r in knife}
    # No statistic may draw on a knife round.
    for player in case.analytics.players:
        assert player.rounds_present <= case.analytics.round_count
    knife_kills = sum(
        1 for k in case.normalized.kills if k.round_num in knife_numbers and k.is_valid_kill
    )
    scoreboard_kills = sum(p.kills for p in case.analytics.players)
    all_valid_kills = sum(1 for k in case.normalized.kills if k.is_valid_kill)
    assert scoreboard_kills == all_valid_kills - knife_kills


# -------------------------------------------------- oracle 1: the parser itself

#: Fields where our definition intentionally differs from the parser's aggregation.
#: Each is a decision recorded in docs/METRICS.md, not an unexplained mismatch.
EXPECTED_DIVERGENCES = {
    "headshot_pct": "we report null with no kills; the parser reports 0.0",
    "assists": "we report kill assists only; the parser's total includes flash assists",
    "never_present": (
        "a player who never took the field (a league coach occupies a slot and never "
        "spawns) has no eligible rounds, so we report null rates and 0 rounds present; "
        "the parser credits them every round and 100% KAST for never dying"
    ),
}


def test_our_scoreboard_matches_the_parsers_exactly(case: DemoCase) -> None:
    """Every counting metric must agree with the parser's own aggregation.

    Our analytics are computed independently from the normalized event model, so this is
    a genuine cross-check rather than a tautology.
    """
    from awpy import Demo

    # Join on Steam ID, not on name. Names are not stable: players rename mid-match, and
    # one ESEA demo carries a coach whose name reads as empty in the parser's own
    # aggregation while we keep the last non-empty one. Steam ID is the identity.
    reference = {row["steamid"]: row for row in Demo(case.path).stats.iter_rows(named=True)}
    ours = {p.steamid: p for p in case.analytics.players if p.steamid is not None}
    assert set(reference) == set(ours), (
        f"player sets differ: only ours {sorted(set(ours) - set(reference))}, "
        f"only parser {sorted(set(reference) - set(ours))}"
    )

    mismatches: list[str] = []
    for steamid, player in ours.items():
        expected = reference[steamid]
        name = player.name
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
        ):
            if getattr(player, field) != expected[field]:
                mismatches.append(
                    f"{name}.{field}: ours={getattr(player, field)} parser={expected[field]}"
                )
        if player.rounds_present == 0:
            # Documented divergence: see EXPECTED_DIVERGENCES["never_present"].
            assert player.kast is None and player.adr is None, (
                f"{name} never played, so rates must be unknown rather than 0"
            )
            assert player.kills == 0 and player.deaths == 0
            continue

        if player.rounds_present != expected["rounds_played"]:
            mismatches.append(
                f"{name}.rounds_present: ours={player.rounds_present} "
                f"parser={expected['rounds_played']}"
            )
        for field in ("adr", "kast", "flash_duration_dealt"):
            value = getattr(player, field)
            if value is None or abs(value - expected[field]) > 0.05:
                mismatches.append(f"{name}.{field}: ours={value} parser={expected[field]}")

        # Documented divergence: the parser's assist total includes flash assists.
        if player.assists + player.flash_assists != expected["assists"]:
            mismatches.append(
                f"{name}.assists_total: ours={player.assists + player.flash_assists} "
                f"parser={expected['assists']}"
            )
        # Documented divergence: null rather than 0.0 when there are no kills.
        if player.kills:
            if abs((player.headshot_pct or 0) - expected["headshot_pct"]) > 0.05:
                mismatches.append(
                    f"{name}.headshot_pct: ours={player.headshot_pct} "
                    f"parser={expected['headshot_pct']}"
                )
        else:
            assert player.headshot_pct is None, EXPECTED_DIVERGENCES["headshot_pct"]

    assert not mismatches, "scoreboard diverges from the parser:\n  " + "\n  ".join(mismatches)


def test_pre_match_events_are_excluded_and_reported(case: DemoCase) -> None:
    """Events before the first recorded round must be dropped *and* surfaced.

    A knife round is frequently played before the round the demo starts recording, so its
    kills belong to no round. Excluding them from the statistics is correct; doing it
    silently would leave a user unable to explain why the scoreboard differs from what
    they watched.
    """
    from awpy import Demo

    first_round_tick = min(r.start_tick for r in case.normalized.rounds)
    parser_rows = Demo(case.path).kills
    pre_match = parser_rows.filter(parser_rows["tick"] < first_round_tick).height

    in_round_kills = sum(1 for k in case.normalized.kills)
    assert in_round_kills == parser_rows.height - pre_match, (
        "every kill from the first round onwards must be normalized"
    )

    codes = [a.code for a in case.analytics.anomalies]
    if pre_match:
        assert "pre_match_events_excluded" in codes, (
            f"{pre_match} pre-match events were dropped without being reported"
        )
    else:
        assert "pre_match_events_excluded" not in codes


def test_our_trade_detection_matches_the_parsers_row_for_row(case: DemoCase) -> None:
    """Not just the totals — the same individual kills must be flagged.

    Equal counts could hide two compensating errors, so this compares the actual rows.
    """
    import polars as pl
    from awpy import Demo

    kills = Demo(case.path).kills.with_row_index("src_idx")
    # Scope the comparison to kills that belong to a recorded round. The parser computes
    # its row-level flags over *every* kill row, including any played before the first
    # recorded round — a knife round often sits there — whereas our normalized model only
    # holds in-round events. Its own aggregated statistics exclude them too, so comparing
    # the full row set would compare different populations.
    first_round_tick = min(r.start_tick for r in case.normalized.rounds)
    kills = kills.filter(pl.col("tick") >= first_round_tick)
    parser_traded = {
        (row["tick"], row["src_idx"])
        for row in kills.filter(pl.col("victim_traded")).iter_rows(named=True)
    }
    parser_trades = {
        (row["tick"], row["src_idx"])
        for row in kills.filter(pl.col("is_trade")).iter_rows(named=True)
    }

    result = detect_trades(case.normalized.kills, case.normalized.meta.tick_rate)
    rows = case.normalized.kills
    ours_traded = {(rows[i].tick, rows[i].src_idx) for i in result.traded_death_indices}
    ours_trades = {(rows[i].tick, rows[i].src_idx) for i in result.trade_kill_indices}

    assert ours_traded == parser_traded, (
        f"traded deaths differ: only ours {sorted(ours_traded - parser_traded)[:5]}, "
        f"only parser {sorted(parser_traded - ours_traded)[:5]}"
    )
    assert ours_trades == parser_trades
    assert len(ours_traded) == len(ours_trades), "each trade avenges exactly one death"


# ------------------------------------------ oracle 2: the published scoreboard


def test_our_scoreboard_matches_the_published_one(scored_case: DemoCase) -> None:
    """Check against the platform's own scoreboard, within documented tolerances.

    This catches the failure mode where we and the parser agree but both differ from the
    game. Fields a given platform does not publish — or computes to a different
    definition, which the manifest notes record — are simply not compared.
    """
    by_name = {p.name: p for p in scored_case.analytics.players}
    checked = 0
    failures: list[str] = []

    for expected in scored_case.ground_truth_players:
        player = by_name.get(expected["name"])
        assert player is not None, (
            f"{expected['name']} missing from our scoreboard; we have {sorted(by_name)}"
        )
        for key, (accessor, tolerance) in GROUND_TRUTH_FIELDS.items():
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

    assert checked >= 4, f"{scored_case.name} compared only {checked} values"
    assert not failures, "published scoreboard diverges:\n  " + "\n  ".join(failures)


# ------------------------------------------------------------------ invariants


def test_no_victim_absorbs_more_than_full_health_in_a_round(case: DemoCase) -> None:
    """The capping invariant, checked against real overkill data."""
    totals: dict[tuple[int, str], int] = {}
    for damage in case.normalized.damages:
        key = (damage.round_num, damage.victim.key)
        totals[key] = totals.get(key, 0) + damage.dmg_health_effective
    offenders = {k: v for k, v in totals.items() if v > 100}
    assert not offenders, dict(list(offenders.items())[:5])

    raw = sum(d.dmg_health_raw for d in case.normalized.damages)
    capped = sum(d.dmg_health_effective for d in case.normalized.damages)
    assert capped < raw, "real demos contain overkill damage, so capping must reduce the total"


def test_self_kills_are_not_misclassified_as_team_kills(case: DemoCase) -> None:
    """A suicide shares the victim's side, so predicate order matters."""
    for kill in case.normalized.kills:
        if kill.is_self_kill:
            assert not kill.is_team_kill
            assert not kill.is_valid_kill


def test_every_event_is_assigned_to_exactly_one_round(case: DemoCase) -> None:
    round_numbers = {r.round_num for r in case.normalized.rounds}
    for collection in (case.normalized.kills, case.normalized.damages, case.normalized.blinds):
        for row in collection:
            assert row.round_num in round_numbers


def test_the_event_feed_is_dense_ordered_and_complete(case: DemoCase) -> None:
    events = build_events(case.normalized)
    assert [e.seq for e in events] == list(range(len(events)))
    keys = [(e.round_num, e.tick) for e in events]
    assert keys == sorted(keys)
    counts = {
        "kill": len(case.normalized.kills),
        "damage": len(case.normalized.damages),
        "flash": len(case.normalized.blinds),
        "utility_thrown": len(case.normalized.utility),
        "bomb": len(case.normalized.objectives),
    }
    for event_type, expected in counts.items():
        actual = sum(1 for e in events if e.event_type == event_type)
        assert actual == expected, f"{event_type}: {actual} in feed, {expected} normalized"


def test_utility_is_attributed_to_players(case: DemoCase) -> None:
    """Throws come from weapon-fire rows; if that sourcing regressed they would be zero."""
    if not case.normalized.utility:
        pytest.skip(f"{case.name} records no utility throws")
    attributed = sum(1 for u in case.normalized.utility if u.thrower is not None)
    assert attributed == len(case.normalized.utility)


def test_kast_never_exceeds_one_hundred_percent(case: DemoCase) -> None:
    """A roster-gating bug would show up here first."""
    for player in case.analytics.players:
        if player.kast is not None:
            assert 0 <= player.kast <= 100, f"{player.name} KAST={player.kast}"


def test_kill_positions_land_inside_the_radar_image(case: DemoCase) -> None:
    """The world-to-radar transform must put real positions on the actual map.

    A wrong transform is the failure mode this view most needs protecting from, because a
    picture is persuasive. Positions from a real match are spread over the playable area,
    so if the transform were wrong — a bad origin, the wrong scale, or an unapplied
    rotation — a meaningful share of them would fall outside the image.

    Some maps publish non-zero ``rotate`` / ``zoom`` values that this build ignores
    (matching the reference implementation). This test is what tells us whether that is
    defensible for a given map rather than assuming it.
    """
    from app.maps.data import get_assets, world_to_radar

    assets = get_assets(case.normalized.meta.map_name or "")
    if not assets.available or assets.image_width is None:
        pytest.skip(f"no radar assets for {case.normalized.meta.map_name}")
    assert assets.pos_x is not None and assets.pos_y is not None and assets.scale

    points = [
        (k.victim_x, k.victim_y)
        for k in case.normalized.kills
        if k.victim_x is not None and k.victim_y is not None
    ]
    assert len(points) > 20, "a real match should yield plenty of death positions"

    width, height = assets.image_width, assets.image_height or assets.image_width
    inside = 0
    for x, y in points:
        rx, ry = world_to_radar(x, y, assets.pos_x, assets.pos_y, assets.scale)
        if 0 <= rx <= width and 0 <= ry <= height:
            inside += 1
    share = inside / len(points)
    assert share >= 0.98, (
        f"{case.normalized.meta.map_name}: only {share:.1%} of {len(points)} death "
        f"positions fall inside the {width}x{height} radar image — the transform is wrong"
    )

    # The positions must also be spread out, not collapsed into a corner, which is what a
    # wrong scale would produce while still technically landing inside the image.
    xs = [world_to_radar(x, y, assets.pos_x, assets.pos_y, assets.scale)[0] for x, y in points]
    ys = [world_to_radar(x, y, assets.pos_x, assets.pos_y, assets.scale)[1] for x, y in points]
    assert max(xs) - min(xs) > width * 0.25, "positions are suspiciously narrow horizontally"
    assert max(ys) - min(ys) > height * 0.25, "positions are suspiciously narrow vertically"


def test_resource_use_stays_within_the_measured_envelope(case: DemoCase) -> None:
    """Guards the upload cap, which is derived from what a parse actually costs."""
    import resource

    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    size_mb = case.path.stat().st_size / 1e6
    # The measured ratio is ~2.6x; allow generous headroom but catch a blow-up.
    assert peak_mb < max(2048, size_mb * 6), (
        f"peak RSS {peak_mb:.0f} MB for a {size_mb:.0f} MB demo"
    )
