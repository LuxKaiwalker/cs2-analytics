"""Side swaps, team identity and overtime — reconstructed, since no demo states them.

The reference demo exercises a single halftime swap (MR12, 13-0). Overtime, mid-match
joiners, substitutions and genuine team changes only appear here.
"""

from __future__ import annotations

from app.parsing.model import Side
from app.parsing.roster import (
    assign_teams,
    ct_team_by_round,
    derive_halves,
    normalize_side,
    opposite,
)


def _sides(
    rounds: int, ct: list[str], t: list[str], *, swap_every: int | None = None
) -> dict[int, dict[str, Side]]:
    """Per-round sides, flipping both groups every ``swap_every`` rounds."""
    out: dict[int, dict[str, Side]] = {}
    for round_num in range(1, rounds + 1):
        flipped = swap_every is not None and ((round_num - 1) // swap_every) % 2 == 1
        ct_side: Side = "T" if flipped else "CT"
        out[round_num] = {
            **dict.fromkeys(ct, ct_side),
            **{key: opposite(ct_side) for key in t},
        }
    return out


A_TEAM = ["a1", "a2", "a3", "a4", "a5"]
B_TEAM = ["b1", "b2", "b3", "b4", "b5"]


def test_side_strings_and_engine_team_numbers_both_normalize() -> None:
    assert normalize_side("terrorist") == "T"
    assert normalize_side("counter-terrorist") == "CT"
    assert normalize_side(2) == "T"
    assert normalize_side(3) == "CT"
    assert normalize_side("spectator") is None
    assert normalize_side(None) is None


def test_team_a_is_the_side_that_started_on_ct() -> None:
    anomalies: list = []
    teams = assign_teams(_sides(6, A_TEAM, B_TEAM), anomalies)
    assert not anomalies
    assert {teams[k] for k in A_TEAM} == {"A"}
    assert {teams[k] for k in B_TEAM} == {"B"}


def test_teams_survive_a_halftime_swap() -> None:
    """The whole point: a player's team must not change when their side does."""
    sides = _sides(24, A_TEAM, B_TEAM, swap_every=12)
    anomalies: list = []
    teams = assign_teams(sides, anomalies)
    assert not anomalies
    assert {teams[k] for k in A_TEAM} == {"A"}

    ct_by_round = ct_team_by_round(sides, teams)
    assert ct_by_round[1] == "A"
    assert ct_by_round[12] == "A"
    assert ct_by_round[13] == "B", "sides swap at the half, teams do not"


def test_regulation_length_is_derived_from_the_observed_swap() -> None:
    sides = _sides(24, A_TEAM, B_TEAM, swap_every=12)
    anomalies: list = []
    teams = assign_teams(sides, anomalies)
    halves, regulation, overtime = derive_halves(ct_team_by_round(sides, teams), anomalies)
    assert regulation == 24
    assert not overtime
    assert halves[12] == 0
    assert halves[13] == 1


def test_overtime_rounds_are_flagged_after_regulation() -> None:
    """MR12 going to overtime: swaps every 12, then every 3 from round 25."""
    sides = _sides(24, A_TEAM, B_TEAM, swap_every=12)
    for offset, round_num in enumerate(range(25, 31)):
        flipped = (offset // 3) % 2 == 1
        ct_side: Side = "T" if flipped else "CT"
        sides[round_num] = {
            **dict.fromkeys(A_TEAM, ct_side),
            **{k: opposite(ct_side) for k in B_TEAM},
        }
    anomalies: list = []
    teams = assign_teams(sides, anomalies)
    halves, regulation, overtime = derive_halves(ct_team_by_round(sides, teams), anomalies)
    assert regulation == 24
    assert overtime == set(range(25, 31))
    assert halves[25] != halves[28], "overtime halves are distinct"


def test_convar_disagreement_is_reported_not_silently_trusted() -> None:
    """Convars hold final-state values and can be changed mid-match.

    The observed swap wins; the disagreement becomes a visible anomaly.
    """
    sides = _sides(24, A_TEAM, B_TEAM, swap_every=12)
    anomalies: list = []
    teams = assign_teams(sides, anomalies)
    _halves, regulation, _ot = derive_halves(
        ct_team_by_round(sides, teams), anomalies, convar_maxrounds=30
    )
    assert regulation == 24, "the data wins over the convar"
    assert [a.code for a in anomalies] == ["maxrounds_mismatch"]


def test_a_player_joining_mid_match_is_assigned_to_a_team() -> None:
    sides = _sides(10, A_TEAM, B_TEAM)
    for round_num in range(6, 11):
        sides[round_num]["sub1"] = "T"
    anomalies: list = []
    teams = assign_teams(sides, anomalies)
    assert not anomalies
    assert teams["sub1"] == "B", "the T side in round 1 is team B"


def test_a_substitution_keeps_both_teams_intact() -> None:
    """a5 leaves after round 5 and sub1 takes their place on CT."""
    sides = _sides(10, A_TEAM, B_TEAM)
    for round_num in range(6, 11):
        del sides[round_num]["a5"]
        sides[round_num]["sub1"] = "CT"
    anomalies: list = []
    teams = assign_teams(sides, anomalies)
    assert not anomalies
    assert teams["sub1"] == "A"
    assert teams["a5"] == "A"


def test_a_genuine_team_change_falls_back_and_reports_an_anomaly() -> None:
    """A player appearing on both sides breaks two-colourability.

    Rather than emit nonsense, the reconstruction anchors on round 1 and says so.
    """
    sides = _sides(10, A_TEAM, B_TEAM)
    for round_num in range(6, 11):
        sides[round_num]["a1"] = "T"  # defects to the other side
    anomalies: list = []
    teams = assign_teams(sides, anomalies)
    assert [a.code for a in anomalies] == ["team_assignment_fallback"]
    assert teams["a1"] == "A", "anchored to the first round"
    assert {teams[k] for k in B_TEAM} == {"B"}


def test_a_single_observed_team_reports_an_anomaly() -> None:
    """A warmup-only or broken demo must not silently produce one team."""
    anomalies: list = []
    teams = assign_teams({1: dict.fromkeys(A_TEAM, "CT")}, anomalies)
    assert [a.code for a in anomalies] == ["team_assignment_fallback"]
    assert {teams[k] for k in A_TEAM} == {"A"}


def test_no_swap_still_yields_two_teams_and_no_regulation_length() -> None:
    """A match that ends before halftime (like a 13-0) has no observable swap."""
    sides = _sides(12, A_TEAM, B_TEAM)
    anomalies: list = []
    teams = assign_teams(sides, anomalies)
    halves, regulation, overtime = derive_halves(ct_team_by_round(sides, teams), anomalies)
    assert regulation is None, "unknown, rather than guessed from a convar"
    assert not overtime
    assert set(halves.values()) == {0}


def test_rounds_without_roster_information_carry_the_previous_side_forward() -> None:
    sides = _sides(5, A_TEAM, B_TEAM)
    del sides[3]
    anomalies: list = []
    teams = assign_teams(sides, anomalies)
    ct_by_round = ct_team_by_round({**sides, 3: {}}, teams)
    assert ct_by_round[3] == "A"
