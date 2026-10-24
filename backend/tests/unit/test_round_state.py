"""Round-state reconstruction: the KAST survival gate and clutch detection."""

from __future__ import annotations

from app.analytics.round_state import build_round_states, rounds_present
from tests import factories as f


def _five(prefix: str) -> list:
    return [f.player(f"{prefix}{i}") for i in range(1, 6)]


def test_player_absent_from_a_round_is_not_credited_with_surviving_it() -> None:
    """The gate that stops KAST being inflated for rounds a player sat out.

    An absent player produces no death row, so "no death means survived" would hand them
    free credit. Survival requires presence.
    """
    ct, t = _five("ct"), _five("t")
    rounds = [f.round_(1), f.round_(2)]
    latecomer = ct[4]
    roster = f.roster_for(rounds, ct, t, absent={(1, latecomer.key)})
    match = f.match(rounds=rounds, roster=roster)
    states = build_round_states(match)

    assert not states[1].survived(latecomer.key), "absent in round 1, so cannot have survived"
    assert states[2].survived(latecomer.key), "present in round 2 and never killed"


def test_survival_requires_not_dying() -> None:
    ct, t = _five("ct"), _five("t")
    rounds = [f.round_(1)]
    kills = [f.kill(0, 500, 1, t[0], ct[0], attacker_side="T", victim_side="CT")]
    match = f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills)
    states = build_round_states(match)
    assert not states[1].survived(ct[0].key)
    assert states[1].survived(ct[1].key)


def test_rounds_present_excludes_knife_rounds_and_absences() -> None:
    ct, t = _five("ct"), _five("t")
    rounds = [f.round_(1, knife=True), f.round_(2), f.round_(3)]
    roster = f.roster_for(rounds, ct, t, absent={(3, ct[0].key)})
    match = f.match(rounds=rounds, roster=roster)
    counts = rounds_present(match)
    assert counts[ct[0].key] == 1, "knife round excluded, round 3 absent"
    assert counts[ct[1].key] == 2, "both scored rounds"


def test_clutch_is_detected_when_a_player_is_left_alone() -> None:
    """Four CT deaths leave one CT against three live Ts: a 1v3."""
    ct, t = _five("ct"), _five("t")
    rounds = [f.round_(1, winner_side="CT")]
    kills = [
        f.kill(i, 500 + i * 10, 1, t[0], ct[i], attacker_side="T", victim_side="CT")
        for i in range(4)
    ]
    kills += [
        f.kill(10 + i, 700 + i * 10, 1, ct[4], t[i], attacker_side="CT", victim_side="T")
        for i in range(3)
    ]
    match = f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills)
    clutch = build_round_states(match)[1].clutch
    assert clutch is not None
    assert clutch.player_key == ct[4].key
    assert clutch.opponents == 5, "all five Ts were alive when the clutcher was left alone"
    assert clutch.won is True


def test_clutch_opponent_count_is_fixed_when_the_clutch_starts() -> None:
    """Killing opponents afterwards does not turn a 1v3 into a 1v1."""
    ct, t = _five("ct"), _five("t")
    rounds = [f.round_(1, winner_side="CT")]
    kills = [
        # Two Ts die first, so three are alive when the last CT is left alone.
        f.kill(0, 100, 1, ct[0], t[0], attacker_side="CT", victim_side="T"),
        f.kill(1, 150, 1, ct[0], t[1], attacker_side="CT", victim_side="T"),
        *[
            f.kill(2 + i, 300 + i * 10, 1, t[2], ct[i], attacker_side="T", victim_side="CT")
            for i in range(4)
        ],
        f.kill(20, 500, 1, ct[4], t[2], attacker_side="CT", victim_side="T"),
        f.kill(21, 520, 1, ct[4], t[3], attacker_side="CT", victim_side="T"),
        f.kill(22, 540, 1, ct[4], t[4], attacker_side="CT", victim_side="T"),
    ]
    match = f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills)
    clutch = build_round_states(match)[1].clutch
    assert clutch is not None
    assert clutch.opponents == 3


def test_lost_clutch_is_counted_as_played_but_not_won() -> None:
    ct, t = _five("ct"), _five("t")
    rounds = [f.round_(1, winner_side="T")]
    kills = [
        f.kill(i, 500 + i * 10, 1, t[0], ct[i], attacker_side="T", victim_side="CT")
        for i in range(5)
    ]
    match = f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills)
    clutch = build_round_states(match)[1].clutch
    assert clutch is not None
    assert clutch.player_key == ct[4].key
    assert clutch.won is False


def test_dying_on_the_same_tick_as_the_last_teammate_is_not_a_clutch() -> None:
    """Two players killed by the same grenade were never alone together."""
    ct, t = _five("ct"), _five("t")
    rounds = [f.round_(1, winner_side="T")]
    kills = [
        f.kill(i, 500 + i * 10, 1, t[0], ct[i], attacker_side="T", victim_side="CT")
        for i in range(3)
    ]
    # The last two CTs die on the same tick.
    kills += [
        f.kill(10, 900, 1, t[0], ct[3], attacker_side="T", victim_side="CT"),
        f.kill(11, 900, 1, t[0], ct[4], attacker_side="T", victim_side="CT"),
    ]
    match = f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills)
    assert build_round_states(match)[1].clutch is None


def test_a_side_that_fields_one_player_all_round_is_not_a_clutch() -> None:
    """A clutch requires *becoming* the last survivor, not starting as one."""
    ct, t = [f.player("solo")], _five("t")
    rounds = [f.round_(1, winner_side="T")]
    match = f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t))
    assert build_round_states(match)[1].clutch is None


def test_clutch_opponent_count_is_clamped_to_five() -> None:
    """A malformed roster with six live enemies still reports at most 1v5."""
    ct, t = _five("ct"), [f.player(f"t{i}") for i in range(1, 7)]
    rounds = [f.round_(1, winner_side="CT")]
    kills = [
        f.kill(i, 500 + i * 10, 1, t[0], ct[i], attacker_side="T", victim_side="CT")
        for i in range(4)
    ]
    match = f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills)
    clutch = build_round_states(match)[1].clutch
    assert clutch is not None
    assert clutch.opponents == 5
