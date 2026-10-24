"""Metric values, zero denominators, and the null-not-zero contract."""

from __future__ import annotations

from app.analytics.compute import compute
from app.analytics.definitions import PLAYER_METRICS_BY_KEY
from tests import factories as f


def _stats(match: object) -> dict:
    return {p.name: p for p in compute(match).players}  # type: ignore[arg-type]


def test_kd_is_none_rather_than_zero_when_a_player_never_died() -> None:
    """A flawless player has an undefined ratio, not a zero one."""
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1)]
    kills = [f.kill(0, 500, 1, attacker, victim)]
    stats = _stats(f.match(rounds=rounds, kills=kills))
    assert stats["attacker"].deaths == 0
    assert stats["attacker"].kd is None
    assert stats["victim"].kd == 0.0, "zero kills over one death is a real 0.0"


def test_headshot_percentage_is_none_without_kills() -> None:
    """0 of 0 kills to the head is unknown, not 0%."""
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1)]
    kills = [f.kill(0, 500, 1, attacker, victim)]
    stats = _stats(f.match(rounds=rounds, kills=kills))
    assert stats["victim"].kills == 0
    assert stats["victim"].headshot_pct is None


def test_headshot_percentage_uses_kills_as_the_denominator() -> None:
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1)]
    kills = [
        f.kill(0, 500, 1, attacker, victim, headshot=True),
        f.kill(1, 600, 1, attacker, victim, headshot=False),
        f.kill(2, 700, 1, attacker, victim, headshot=True),
        f.kill(3, 800, 1, attacker, victim, headshot=False),
    ]
    stats = _stats(f.match(rounds=rounds, kills=kills))
    assert stats["attacker"].headshot_pct == 50.0


def test_rate_metrics_are_none_when_no_rounds_are_scored() -> None:
    """An all-knife-round demo has no eligible rounds; rates must not read as 0."""
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1, knife=True)]
    kills = [f.kill(0, 500, 1, attacker, victim)]
    damages = [f.damage(0, 500, 1, attacker, victim, 100, health_post=0)]
    result = compute(f.match(rounds=rounds, kills=kills, damages=damages))
    assert result.round_count == 0
    stats = {p.name: p for p in result.players}
    assert stats["attacker"].adr is None
    assert stats["attacker"].kpr is None
    assert stats["attacker"].kast is None


def test_flash_metrics_are_none_when_the_demo_has_no_flash_data() -> None:
    """An empty source dataset must surface as unknown, never as a confident zero.

    GOTV and matchmaking recordings routinely strip flash events, and reporting 0
    enemies flashed would be indistinguishable from a player who threw nothing.
    """
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1)]
    kills = [f.kill(0, 500, 1, attacker, victim)]
    match = f.match(
        rounds=rounds,
        kills=kills,
        availability=f.available("rounds", "kills", "damages", empty=("blinds", "shots")),
    )
    stats = _stats(match)
    assert stats["attacker"].enemies_flashed is None
    assert stats["attacker"].flash_duration_dealt is None
    assert stats["attacker"].flashes_thrown is None


def test_damage_metrics_are_none_when_the_damage_dataset_is_missing() -> None:
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1)]
    kills = [f.kill(0, 500, 1, attacker, victim)]
    match = f.match(
        rounds=rounds,
        kills=kills,
        availability=f.available("rounds", "kills", empty=("damages",)),
    )
    stats = _stats(match)
    assert stats["attacker"].adr is None
    assert stats["attacker"].damage_total is None
    assert stats["attacker"].utility_damage is None


def test_adr_denominator_is_the_match_round_count() -> None:
    """Three rounds, 150 damage in one of them, so ADR is 50 — not 150."""
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1), f.round_(2), f.round_(3)]
    damages = [
        f.damage(0, 500, 1, attacker, victim, 100, health_post=0),
        f.damage(1, 600, 1, attacker, f.player("other"), 50, health_post=50),
    ]
    stats = _stats(f.match(rounds=rounds, damages=damages))
    assert stats["attacker"].adr == 50.0


def test_kast_counts_a_round_once_however_many_credits_it_earns() -> None:
    """Kill plus assist plus survival in one round is one KAST round, not three."""
    ct, t = [f.player(f"ct{i}") for i in range(1, 6)], [f.player(f"t{i}") for i in range(1, 6)]
    rounds = [f.round_(1), f.round_(2)]
    kills = [
        f.kill(0, 500, 1, ct[0], t[0], attacker_side="CT", victim_side="T", assister=ct[0]),
    ]
    match = f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills)
    stats = _stats(match)
    assert stats["ct1"].kast == 100.0, "survived both rounds"
    assert stats["t1"].kast == 50.0, "died in round 1, survived round 2"


def test_kast_credits_an_assist_only_round() -> None:
    ct, t = [f.player(f"ct{i}") for i in range(1, 6)], [f.player(f"t{i}") for i in range(1, 6)]
    rounds = [f.round_(1)]
    kills = [
        # ct2 assists, then dies — so neither a kill nor survival earns the credit.
        f.kill(0, 500, 1, ct[0], t[0], attacker_side="CT", victim_side="T", assister=ct[1]),
        f.kill(1, 600, 1, t[1], ct[1], attacker_side="T", victim_side="CT"),
    ]
    match = f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills)
    stats = _stats(match)
    assert stats["ct2"].kills == 0
    assert stats["ct2"].assists == 1
    assert stats["ct2"].kast == 100.0


def test_kast_credits_a_traded_death_only_round() -> None:
    ct, t = [f.player(f"ct{i}") for i in range(1, 6)], [f.player(f"t{i}") for i in range(1, 6)]
    rounds = [f.round_(1)]
    kills = [
        f.kill(0, 500, 1, t[0], ct[0], attacker_side="T", victim_side="CT"),
        f.kill(1, 600, 1, ct[1], t[0], attacker_side="CT", victim_side="T"),
    ]
    match = f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills)
    stats = _stats(match)
    assert stats["ct1"].kills == 0
    assert stats["ct1"].traded_deaths == 1
    assert stats["ct1"].kast == 100.0, "a traded death earns the T in KAST"


def test_opening_kill_and_death_go_to_the_first_duel_of_the_round() -> None:
    ct, t = [f.player(f"ct{i}") for i in range(1, 6)], [f.player(f"t{i}") for i in range(1, 6)]
    rounds = [f.round_(1)]
    kills = [
        f.kill(0, 500, 1, ct[0], t[0], attacker_side="CT", victim_side="T"),
        f.kill(1, 600, 1, ct[1], t[1], attacker_side="CT", victim_side="T"),
    ]
    stats = _stats(f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills))
    assert (stats["ct1"].opening_kills, stats["t1"].opening_deaths) == (1, 1)
    assert (stats["ct2"].opening_kills, stats["t2"].opening_deaths) == (0, 0)


def test_a_suicide_opening_a_round_does_not_take_the_opening_duel() -> None:
    """A player falling to their death is not an entry frag.

    Counting it would hand a phantom opening death to the victim and deny the real entry
    its credit.
    """
    ct, t = [f.player(f"ct{i}") for i in range(1, 6)], [f.player(f"t{i}") for i in range(1, 6)]
    rounds = [f.round_(1)]
    kills = [
        f.kill(0, 300, 1, t[4], t[4], attacker_side="T", victim_side="T", weapon="world"),
        f.kill(1, 500, 1, ct[0], t[0], attacker_side="CT", victim_side="T"),
    ]
    stats = _stats(f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills))
    assert stats["t5"].opening_deaths == 0
    assert stats["ct1"].opening_kills == 1
    assert stats["t1"].opening_deaths == 1


def test_multikill_buckets_are_exclusive_and_clamped() -> None:
    attacker = f.player("attacker")
    victims = [f.player(f"v{i}") for i in range(7)]
    rounds = [f.round_(1), f.round_(2)]
    kills = [f.kill(i, 500 + i * 10, 1, attacker, victims[i]) for i in range(6)]
    kills += [f.kill(10 + i, 10_500 + i * 10, 2, attacker, victims[i]) for i in range(3)]
    stats = _stats(f.match(rounds=rounds, kills=kills))
    player = stats["attacker"]
    assert player.multikill_2k == 0
    assert player.multikill_3k == 1, "the 3-kill round"
    assert player.multikill_4k == 0
    assert player.multikill_5k == 1, "6 kills clamps into the 5K bucket"


def test_flashes_thrown_counts_only_flashbangs() -> None:
    thrower = f.player("thrower")
    rounds = [f.round_(1)]
    utility = [
        f.throw(0, 100, 1, thrower, "flashbang"),
        f.throw(1, 200, 1, thrower, "flashbang"),
        f.throw(2, 300, 1, thrower, "smokegrenade"),
        f.throw(3, 400, 1, thrower, "hegrenade"),
    ]
    stats = _stats(f.match(rounds=rounds, utility=utility, players=[thrower]))
    assert stats["thrower"].flashes_thrown == 2


def test_every_player_stat_field_has_a_published_definition() -> None:
    """Guards ``/api/metrics`` against drift.

    If a metric can appear in the product without a definition attached, the tooltips and
    the docs stop being trustworthy. This fails the build instead.
    """
    from app.analytics.compute import PlayerStats

    identity = {"player_key", "name", "steamid", "is_bot", "team", "last_side"}
    fields = {name for name in PlayerStats.__slots__ if name not in identity}
    undefined = sorted(fields - set(PLAYER_METRICS_BY_KEY))
    assert not undefined, f"metrics without a definition: {undefined}"
    stale = sorted(set(PLAYER_METRICS_BY_KEY) - fields)
    assert not stale, f"definitions with no corresponding metric: {stale}"
