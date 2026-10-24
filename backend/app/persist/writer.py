"""Persist a parsed and computed match.

Writes are idempotent per match: children are deleted and rewritten, so re-ingesting a
demo after an analytics change produces a clean result rather than duplicated rows.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from app.analytics.compute import MatchAnalytics
from app.analytics.events import EventRow, build_events
from app.models import (
    SCHEMA_VERSION,
    Match,
    MatchEvent,
    MatchPlayer,
    MatchRound,
    MatchRoundPlayer,
    MatchStatus,
)
from app.parsing.model import NormalizedMatch

logger = logging.getLogger(__name__)

#: Events are inserted in batches; a competitive match yields only a few thousand rows,
#: so one transaction with modest chunks keeps memory flat without extra machinery.
_EVENT_CHUNK = 1000


def _json_or_none(value: object) -> str | None:
    if value in (None, {}, []):
        return None
    return json.dumps(value, default=str, ensure_ascii=False)


def persist_match(
    session: Session,
    match_id: str,
    normalized: NormalizedMatch,
    analytics: MatchAnalytics,
    *,
    peak_rss_mb: int | None = None,
    parse_seconds: float | None = None,
) -> None:
    """Write metadata, scoreboard, rounds and the event feed for ``match_id``."""
    record = session.get(Match, match_id)
    if record is None:
        msg = f"match {match_id} does not exist"
        raise LookupError(msg)

    meta = normalized.meta
    record.map_name = meta.map_name
    record.tick_rate = meta.tick_rate
    record.tick_rate_source = meta.tick_rate_source
    record.round_count = analytics.round_count
    record.regulation_rounds = meta.regulation_rounds
    record.has_overtime = meta.has_overtime
    record.team_a_name = meta.team_a_name
    record.team_b_name = meta.team_b_name
    record.team_a_score = analytics.team_a_score
    record.team_b_score = analytics.team_b_score
    record.winner_team = analytics.winner_team
    record.demo_version_name = meta.demo_version_name
    record.server_name = meta.server_name
    record.playback_time = meta.playback_time
    record.playback_ticks = meta.playback_ticks
    record.parser_name = meta.parser_name
    record.parser_version = meta.parser_version
    record.analytics_version = meta.analytics_version
    record.schema_version = SCHEMA_VERSION
    record.roster_source = meta.roster_source
    record.availability_json = _json_or_none(
        {name: asdict(entry) for name, entry in normalized.availability.items()}
    )
    record.anomalies_json = _json_or_none([asdict(a) for a in analytics.anomalies])
    record.peak_rss_mb = peak_rss_mb
    record.parse_seconds = parse_seconds
    record.status = MatchStatus.COMPLETED
    record.stage = None
    record.stage_started_at = None
    record.error_code = None
    record.error_message = None
    record.completed_at = datetime.now(UTC)

    _replace_children(session, match_id)

    session.add_all(
        [
            MatchPlayer(
                match_id=match_id,
                player_key=p.player_key,
                steamid=p.steamid,
                name=p.name,
                is_bot=p.is_bot,
                team=p.team,
                last_side=p.last_side,
                rounds_present=p.rounds_present,
                kills=p.kills,
                deaths=p.deaths,
                assists=p.assists,
                flash_assists=p.flash_assists,
                team_kills=p.team_kills,
                self_kills=p.self_kills,
                headshot_kills=p.headshot_kills,
                opening_kills=p.opening_kills,
                opening_deaths=p.opening_deaths,
                traded_deaths=p.traded_deaths,
                trade_kills=p.trade_kills,
                kd=p.kd,
                kpr=p.kpr,
                adr=p.adr,
                headshot_pct=p.headshot_pct,
                kast=p.kast,
                damage_total=p.damage_total,
                utility_damage=p.utility_damage,
                flashes_thrown=p.flashes_thrown,
                enemies_flashed=p.enemies_flashed,
                flash_duration_dealt=p.flash_duration_dealt,
                multikill_2k=p.multikill_2k,
                multikill_3k=p.multikill_3k,
                multikill_4k=p.multikill_4k,
                multikill_5k=p.multikill_5k,
                clutches_played=p.clutches_played,
                clutches_won=p.clutches_won,
                clutch_1v1=p.clutch_1v1,
                clutch_1v2=p.clutch_1v2,
                clutch_1v3=p.clutch_1v3,
                clutch_1v4=p.clutch_1v4,
                clutch_1v5=p.clutch_1v5,
            )
            for p in analytics.players
        ]
    )

    for summary in analytics.rounds:
        session.add(
            MatchRound(
                match_id=match_id,
                round_num=summary.round_num,
                start_tick=summary.start_tick,
                freeze_end_tick=summary.freeze_end_tick,
                end_tick=summary.end_tick,
                official_end_tick=summary.official_end_tick,
                duration_s=summary.duration_s,
                winner_side=summary.winner_side,
                winner_team=summary.winner_team,
                reason_name=summary.reason_name,
                is_knife_round=summary.is_knife_round,
                half_index=summary.half_index,
                is_overtime=summary.is_overtime,
                team_ct=summary.team_ct,
                score_a_after=summary.score_a_after,
                score_b_after=summary.score_b_after,
                kills_count=summary.kills_count,
                bomb_planted=summary.bomb_planted,
                bomb_plant_tick=summary.bomb_plant_tick,
                bombsite=summary.bombsite,
                bomb_defused=summary.bomb_defused,
                bomb_exploded=summary.bomb_exploded,
                ct_equipment_value=summary.ct_equipment_value,
                t_equipment_value=summary.t_equipment_value,
                ct_buy_type=summary.ct_buy_type,
                t_buy_type=summary.t_buy_type,
            )
        )
        session.add_all(
            [
                MatchRoundPlayer(
                    match_id=match_id,
                    round_num=row.round_num,
                    player_key=row.player_key,
                    name=row.name,
                    side=row.side,
                    team=row.team,
                    present_at_freeze=row.present_at_freeze,
                    survived=row.survived,
                    kills=row.kills,
                    deaths=row.deaths,
                    assists=row.assists,
                    damage=row.damage,
                    utility_damage=row.utility_damage,
                    equipment_value=row.equipment_value,
                    is_clutch=row.is_clutch,
                    clutch_opponents=row.clutch_opponents,
                    clutch_won=row.clutch_won,
                )
                for row in summary.players
            ]
        )

    _insert_events(session, match_id, build_events(normalized))
    logger.info(
        "persisted match %s: %d players, %d rounds",
        match_id,
        len(analytics.players),
        len(analytics.rounds),
    )


def _replace_children(session: Session, match_id: str) -> None:
    """Clear derived rows so a re-ingest cannot leave stale ones behind."""
    for model in (MatchEvent, MatchRoundPlayer, MatchRound, MatchPlayer):
        session.execute(delete(model).where(model.match_id == match_id))
    session.flush()


def _insert_events(session: Session, match_id: str, events: list[EventRow]) -> None:
    """Bulk-insert the event feed in chunks within the caller's transaction."""
    if not events:
        return
    rows = [
        {
            "match_id": match_id,
            "seq": e.seq,
            "round_seq": e.round_seq,
            "round_num": e.round_num,
            "tick": e.tick,
            "time_in_round_s": e.time_in_round_s,
            "is_post_round": e.is_post_round,
            "event_type": str(e.event_type),
            "subtype": e.subtype,
            "actor_key": e.actor_key,
            "actor_name": e.actor_name,
            "actor_side": e.actor_side,
            "victim_key": e.victim_key,
            "victim_name": e.victim_name,
            "victim_side": e.victim_side,
            "weapon": e.weapon,
            "is_headshot": e.is_headshot,
            "damage_health": e.damage_health,
            "damage_armor": e.damage_armor,
            "hitgroup": e.hitgroup,
            "actor_x": e.actor_x,
            "actor_y": e.actor_y,
            "actor_z": e.actor_z,
            "victim_x": e.victim_x,
            "victim_y": e.victim_y,
            "victim_z": e.victim_z,
            "extra_json": _json_or_none(e.extra),
        }
        for e in events
    ]
    for start in range(0, len(rows), _EVENT_CHUNK):
        session.execute(insert(MatchEvent), rows[start : start + _EVENT_CHUNK])
