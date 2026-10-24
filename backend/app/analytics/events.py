"""Build the unified, chronologically ordered event feed.

The dashboard needs one searchable timeline spanning kills, damage, utility, flashes and
objectives, plus a map overlay drawn across several of those types. Separate per-type
tables would force a UNION and a re-sort on every read, so the feed is materialized once
as a single ordered list.

Nothing here feeds the statistics. Those are computed from the normalized model in
:mod:`app.analytics.compute`, which means this representation is purely presentational
and its shape cannot affect a single number on the scoreboard.

**Ordering.** Rows are sorted by ``(round_num, tick, type_rank, src_idx)`` and then
assigned a dense ``seq``. Within one source table ``src_idx`` is real evidence — it is
the demo's own message order. Across tables it is not: when a damage row and a kill row
share a tick, nothing in the demo says which came first. ``type_rank`` therefore encodes
a *reading convention* (the damage that killed you is listed before the kill), and the
invariant that keeps this honest is that **no statistic depends on cross-type ordering**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from app.parsing.model import NormalizedMatch, Side


class EventType(StrEnum):
    """Event kinds in the unified feed."""

    ROUND_START = "round_start"
    FREEZE_END = "freeze_end"
    UTILITY_THROWN = "utility_thrown"
    FLASH = "flash"
    DAMAGE = "damage"
    KILL = "kill"
    BOMB = "bomb"
    ROUND_END = "round_end"


#: Reading order for events sharing a tick. A presentation convention, not evidence.
TYPE_RANK: dict[str, int] = {
    EventType.ROUND_START: 0,
    EventType.FREEZE_END: 5,
    EventType.UTILITY_THROWN: 10,
    EventType.FLASH: 20,
    EventType.DAMAGE: 30,
    EventType.KILL: 40,
    EventType.BOMB: 50,
    EventType.ROUND_END: 90,
}


@dataclass(slots=True)
class EventRow:
    """One row of the unified feed."""

    seq: int
    round_seq: int
    round_num: int
    tick: int
    time_in_round_s: float | None
    is_post_round: bool
    event_type: str
    subtype: str | None = None
    actor_key: str | None = None
    actor_name: str | None = None
    actor_side: Side | None = None
    victim_key: str | None = None
    victim_name: str | None = None
    victim_side: Side | None = None
    weapon: str | None = None
    is_headshot: bool = False
    damage_health: int | None = None
    damage_armor: int | None = None
    hitgroup: str | None = None
    actor_x: float | None = None
    actor_y: float | None = None
    actor_z: float | None = None
    victim_x: float | None = None
    victim_y: float | None = None
    victim_z: float | None = None
    extra: dict[str, object] = field(default_factory=dict)


def build_events(match: NormalizedMatch) -> list[EventRow]:
    """Materialize the match's full event feed in chronological order."""
    rate = match.meta.tick_rate or 64.0
    play_start = {r.round_num: r.play_start_tick for r in match.rounds}

    def seconds(round_num: int, tick: int) -> float | None:
        origin = play_start.get(round_num)
        if origin is None:
            return None
        # Kept signed: events during freeze time legitimately read negative.
        return round((tick - origin) / rate, 3)

    # (round_num, tick, type_rank, src_idx, partial row)
    staged: list[tuple[int, int, int, int, EventRow]] = []

    def stage(row: EventRow, src_idx: int) -> None:
        staged.append((row.round_num, row.tick, TYPE_RANK[row.event_type], src_idx, row))

    def blank(event_type: EventType, round_num: int, tick: int, *, post: bool = False) -> EventRow:
        return EventRow(
            seq=-1,
            round_seq=-1,
            round_num=round_num,
            tick=tick,
            time_in_round_s=seconds(round_num, tick),
            is_post_round=post,
            event_type=event_type,
        )

    for round_ in match.rounds:
        start = blank(EventType.ROUND_START, round_.round_num, round_.start_tick)
        start.extra = {
            "half_index": round_.half_index,
            "is_overtime": round_.is_overtime,
            "team_ct": round_.team_ct,
        }
        stage(start, -2)
        if round_.freeze_end_tick is not None:
            stage(blank(EventType.FREEZE_END, round_.round_num, round_.freeze_end_tick), -1)
        end = blank(EventType.ROUND_END, round_.round_num, round_.end_tick)
        end.subtype = round_.reason_name
        end.extra = {
            "winner_side": round_.winner_side,
            "winner_team": round_.winner_team,
            "reason": round_.reason_name,
        }
        stage(end, 1 << 30)

    for kill in match.kills:
        row = blank(EventType.KILL, kill.round_num, kill.tick, post=kill.is_post_round)
        row.actor_key = kill.attacker.key if kill.attacker else None
        row.actor_name = kill.attacker.name if kill.attacker else None
        row.actor_side = kill.attacker_side
        row.victim_key = kill.victim.key
        row.victim_name = kill.victim.name
        row.victim_side = kill.victim_side
        row.weapon = kill.weapon
        row.is_headshot = kill.headshot
        row.hitgroup = kill.hitgroup_name
        row.actor_x, row.actor_y, row.actor_z = kill.attacker_x, kill.attacker_y, kill.attacker_z
        row.victim_x, row.victim_y, row.victim_z = kill.victim_x, kill.victim_y, kill.victim_z
        row.subtype = (
            "self_kill" if kill.is_self_kill else "team_kill" if kill.is_team_kill else "kill"
        )
        row.extra = {
            "assister_key": kill.assister.key if kill.assister else None,
            "assister_name": kill.assister.name if kill.assister else None,
            "assist_is_flash": kill.assist_is_flash,
            "noscope": kill.noscope,
            "thru_smoke": kill.thru_smoke,
            "penetrated": kill.penetrated,
        }
        stage(row, kill.src_idx)

    for damage in match.damages:
        row = blank(EventType.DAMAGE, damage.round_num, damage.tick, post=damage.is_post_round)
        row.actor_key = damage.attacker.key if damage.attacker else None
        row.actor_name = damage.attacker.name if damage.attacker else None
        row.actor_side = damage.attacker_side
        row.victim_key = damage.victim.key
        row.victim_name = damage.victim.name
        row.victim_side = damage.victim_side
        row.weapon = damage.weapon
        row.hitgroup = damage.hitgroup_name
        row.damage_health = damage.dmg_health_effective
        row.damage_armor = damage.dmg_armor
        row.actor_x, row.actor_y, row.actor_z = (
            damage.attacker_x,
            damage.attacker_y,
            damage.attacker_z,
        )
        row.victim_x, row.victim_y, row.victim_z = (
            damage.victim_x,
            damage.victim_y,
            damage.victim_z,
        )
        row.extra = {
            # Both are kept: the raw figure is what the demo said, the effective figure is
            # what may be summed. Showing only one of them invites the wrong conclusion.
            "damage_raw": damage.dmg_health_raw,
            "health_post": damage.health_post,
            "is_team_damage": damage.is_team_damage,
            "is_self_damage": damage.is_self_damage,
        }
        stage(row, damage.src_idx)

    for blind in match.blinds:
        row = blank(EventType.FLASH, blind.round_num, blind.tick)
        row.actor_key = blind.attacker.key if blind.attacker else None
        row.actor_name = blind.attacker.name if blind.attacker else None
        row.actor_side = blind.attacker_side
        row.victim_key = blind.victim.key
        row.victim_name = blind.victim.name
        row.victim_side = blind.victim_side
        row.weapon = "flashbang"
        row.subtype = "enemy" if blind.is_enemy_flash else "team_or_self"
        row.extra = {"duration": round(blind.duration, 3)}
        stage(row, blind.src_idx)

    for throw in match.utility:
        row = blank(EventType.UTILITY_THROWN, throw.round_num, throw.tick)
        row.actor_key = throw.thrower.key if throw.thrower else None
        row.actor_name = throw.thrower.name if throw.thrower else None
        row.actor_side = throw.thrower_side
        row.weapon = throw.utility_type
        row.subtype = throw.utility_type
        row.actor_x, row.actor_y, row.actor_z = throw.x, throw.y, throw.z
        stage(row, throw.src_idx)

    for objective in match.objectives:
        row = blank(EventType.BOMB, objective.round_num, objective.tick)
        row.actor_key = objective.player.key if objective.player else None
        row.actor_name = objective.player.name if objective.player else None
        row.actor_side = objective.player_side
        row.subtype = objective.event
        row.actor_x, row.actor_y, row.actor_z = objective.x, objective.y, objective.z
        row.extra = {"bombsite": objective.bombsite}
        stage(row, objective.src_idx)

    staged.sort(key=lambda item: item[:4])
    rows: list[EventRow] = []
    round_counters: dict[int, int] = {}
    for seq, (round_num, _tick, _rank, _idx, row) in enumerate(staged):
        row.seq = seq
        row.round_seq = round_counters.get(round_num, 0)
        round_counters[round_num] = row.round_seq + 1
        rows.append(row)
    return rows
