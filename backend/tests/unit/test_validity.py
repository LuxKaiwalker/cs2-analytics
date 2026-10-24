"""Which events count: team damage, world damage, suicides and bots."""

from __future__ import annotations

from app.analytics.compute import compute
from tests import factories as f


def _stats(match: object) -> dict:
    return {p.name: p for p in compute(match).players}  # type: ignore[arg-type]


def test_suicide_is_a_death_but_not_a_kill() -> None:
    """A world death costs the victim a death and credits nobody with a kill."""
    victim = f.player("victim")
    rounds = [f.round_(1)]
    kills = [
        f.kill(0, 500, 1, victim, victim, attacker_side="CT", victim_side="CT", weapon="world")
    ]
    stats = _stats(f.match(rounds=rounds, kills=kills, players=[victim]))
    assert stats["victim"].deaths == 1
    assert stats["victim"].kills == 0
    assert stats["victim"].self_kills == 1
    assert stats["victim"].team_kills == 0, "a suicide must not be miscounted as a team kill"


def test_team_kill_is_not_a_kill() -> None:
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1)]
    kills = [f.kill(0, 500, 1, attacker, victim, attacker_side="CT", victim_side="CT")]
    stats = _stats(f.match(rounds=rounds, kills=kills))
    assert stats["attacker"].kills == 0
    assert stats["attacker"].team_kills == 1
    assert stats["victim"].deaths == 1


def test_team_and_self_damage_are_excluded_from_adr() -> None:
    attacker, mate, enemy = f.player("attacker"), f.player("mate"), f.player("enemy")
    rounds = [f.round_(1)]
    damages = [
        f.damage(
            0, 100, 1, attacker, mate, 50, health_post=50, attacker_side="CT", victim_side="CT"
        ),
        f.damage(
            1, 200, 1, attacker, attacker, 30, health_post=70, attacker_side="CT", victim_side="CT"
        ),
        f.damage(2, 300, 1, attacker, enemy, 40, health_post=60),
    ]
    stats = _stats(f.match(rounds=rounds, damages=damages))
    assert stats["attacker"].damage_total == 40, "only the enemy hit counts"
    assert stats["attacker"].adr == 40.0


def test_world_damage_has_no_attacker_and_is_excluded() -> None:
    """Fall damage appears with a null attacker and an empty weapon string."""
    victim = f.player("victim")
    rounds = [f.round_(1)]
    damages = [f.damage(0, 100, 1, None, victim, 10, health_post=90, weapon="")]
    result = compute(f.match(rounds=rounds, damages=damages, players=[victim]))
    stats = {p.name: p for p in result.players}
    assert stats["victim"].damage_total == 0


def test_two_bots_with_the_same_steam_id_stay_distinct_players() -> None:
    """Bots and the demo recorder all report Steam ID 0.

    Keying the scoreboard on Steam ID would collapse them into one row and corrupt
    every number, so identity is a derived key that falls back to the name.
    """
    bot_a, bot_b = f.bot("BOT Ada"), f.bot("BOT Bob")
    assert bot_a.key != bot_b.key
    rounds = [f.round_(1)]
    kills = [
        f.kill(0, 500, 1, bot_a, bot_b, attacker_side="CT", victim_side="T"),
        f.kill(1, 600, 1, bot_a, bot_b, attacker_side="CT", victim_side="T"),
    ]
    stats = _stats(f.match(rounds=rounds, kills=kills))
    assert len(stats) == 2
    assert stats["BOT Ada"].kills == 2
    assert stats["BOT Bob"].deaths == 2
    assert all(p.is_bot for p in stats.values())


def test_knife_round_is_excluded_from_every_denominator() -> None:
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1, knife=True), f.round_(2)]
    kills = [
        f.kill(0, 500, 1, attacker, victim, weapon="knife"),
        f.kill(1, 10_500, 2, attacker, victim),
    ]
    damages = [
        f.damage(0, 500, 1, attacker, victim, 100, health_post=0),
        f.damage(1, 10_500, 2, attacker, victim, 100, health_post=0),
    ]
    result = compute(f.match(rounds=rounds, kills=kills, damages=damages))
    stats = {p.name: p for p in result.players}
    assert result.round_count == 1, "only the non-knife round is scored"
    assert stats["attacker"].kills == 1
    assert stats["attacker"].adr == 100.0, "one scored round, 100 damage in it"


def test_assists_are_split_from_flash_assists() -> None:
    """csstats-style scoreboards count kill assists only, so the two are kept apart."""
    attacker, victim = f.player("attacker"), f.player("victim")
    helper = f.player("helper")
    rounds = [f.round_(1)]
    kills = [
        f.kill(0, 500, 1, attacker, victim, assister=helper),
        f.kill(1, 600, 1, attacker, victim, assister=helper, assist_is_flash=True),
    ]
    stats = _stats(f.match(rounds=rounds, kills=kills))
    assert stats["helper"].assists == 1
    assert stats["helper"].flash_assists == 1


def test_assist_on_a_team_kill_is_not_credited() -> None:
    attacker, victim, helper = f.player("attacker"), f.player("victim"), f.player("helper")
    rounds = [f.round_(1)]
    kills = [
        f.kill(0, 500, 1, attacker, victim, attacker_side="CT", victim_side="CT", assister=helper)
    ]
    stats = _stats(f.match(rounds=rounds, kills=kills))
    assert stats["helper"].assists == 0


def test_self_flashes_and_team_flashes_do_not_count_as_enemies_flashed() -> None:
    thrower, mate, enemy = f.player("thrower"), f.player("mate"), f.player("enemy")
    rounds = [f.round_(1)]
    blinds = [
        f.blind(0, 100, 1, thrower, thrower, 2.0, attacker_side="CT", victim_side="CT"),
        f.blind(1, 200, 1, thrower, mate, 2.0, attacker_side="CT", victim_side="CT"),
        f.blind(2, 300, 1, thrower, enemy, 1.5, attacker_side="CT", victim_side="T"),
    ]
    stats = _stats(f.match(rounds=rounds, blinds=blinds))
    assert stats["thrower"].enemies_flashed == 1
    assert stats["thrower"].flash_duration_dealt == 1.5


def test_utility_damage_counts_only_grenade_weapons() -> None:
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1)]
    damages = [
        f.damage(0, 100, 1, attacker, victim, 30, health_post=70, weapon="hegrenade"),
        f.damage(1, 200, 1, attacker, victim, 20, health_post=50, weapon="molotov"),
        f.damage(2, 300, 1, attacker, victim, 10, health_post=40, weapon="inferno"),
        f.damage(3, 400, 1, attacker, victim, 40, health_post=0, weapon="ak47"),
    ]
    stats = _stats(f.match(rounds=rounds, damages=damages))
    assert stats["attacker"].utility_damage == 60
    assert stats["attacker"].damage_total == 100


def test_an_assist_on_a_suicide_is_still_credited() -> None:
    """A player who takes enemy damage and then falls to their death is a suicide.

    The enemy the game credited as assister still contributed to the death, and real
    demos contain exactly this — gating assists on "was this a valid kill" silently
    dropped them.
    """
    victim, helper = f.player("victim"), f.player("helper")
    rounds = [f.round_(1)]
    kills = [
        f.kill(
            0,
            500,
            1,
            victim,  # attacker is the victim: a suicide
            victim,
            attacker_side="T",
            victim_side="T",
            weapon="world",
            assister=helper,
            assister_side="CT",
        )
    ]
    stats = _stats(f.match(rounds=rounds, kills=kills))
    assert stats["victim"].deaths == 1
    assert stats["victim"].self_kills == 1
    assert stats["helper"].assists == 1, "the enemy assister is credited"


def test_an_assist_is_not_credited_to_the_victims_own_side() -> None:
    """A teammate of the victim cannot have assisted in killing them."""
    attacker, victim, mate = f.player("attacker"), f.player("victim"), f.player("mate")
    rounds = [f.round_(1)]
    kills = [
        f.kill(
            0,
            500,
            1,
            attacker,
            victim,
            attacker_side="CT",
            victim_side="T",
            assister=mate,
            assister_side="T",
        )
    ]
    stats = _stats(f.match(rounds=rounds, kills=kills))
    assert stats["mate"].assists == 0


def test_the_killer_does_not_also_receive_an_assist() -> None:
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1)]
    kills = [
        f.kill(
            0,
            500,
            1,
            attacker,
            victim,
            attacker_side="CT",
            victim_side="T",
            assister=attacker,
            assister_side="CT",
        )
    ]
    stats = _stats(f.match(rounds=rounds, kills=kills))
    assert stats["attacker"].kills == 1
    assert stats["attacker"].assists == 0


def test_an_assist_only_round_still_earns_kast_when_the_kill_was_a_suicide() -> None:
    """The assist predicate feeds KAST, so the two must agree."""
    ct = [f.player(f"ct{i}") for i in range(1, 6)]
    t = [f.player(f"t{i}") for i in range(1, 6)]
    rounds = [f.round_(1)]
    kills = [
        f.kill(
            0,
            500,
            1,
            t[0],
            t[0],
            attacker_side="T",
            victim_side="T",
            weapon="world",
            assister=ct[0],
            assister_side="CT",
        ),
        # ct1 then dies, so neither a kill nor survival can be the source of the credit.
        f.kill(1, 900, 1, t[1], ct[0], attacker_side="T", victim_side="CT"),
    ]
    match = f.match(rounds=rounds, roster=f.roster_for(rounds, ct, t), kills=kills)
    stats = _stats(match)
    assert stats["ct1"].kills == 0
    assert stats["ct1"].assists == 1
    assert stats["ct1"].kast == 100.0


def test_smoke_impact_damage_is_not_counted_as_utility_damage() -> None:
    """A smoke that strikes a player deals a point of impact damage.

    No published scoreboard counts it as utility damage, which means HE and fire — and it
    must not trip the unknown-weapon warning either.
    """
    attacker, victim = f.player("attacker"), f.player("victim")
    rounds = [f.round_(1)]
    damages = [
        f.damage(0, 100, 1, attacker, victim, 1, health_post=99, weapon="smokegrenade"),
        f.damage(1, 200, 1, attacker, victim, 40, health_post=59, weapon="hegrenade"),
    ]
    result = compute(f.match(rounds=rounds, damages=damages))
    stats = {p.name: p for p in result.players}
    assert stats["attacker"].utility_damage == 40
    assert stats["attacker"].damage_total == 41, "impact damage still counts as damage"
    assert [a.code for a in result.anomalies] == []
