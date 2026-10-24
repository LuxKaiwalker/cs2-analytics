"""The filterable, paginated event feed."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app import errors
from app.db import get_db
from app.models import Match, MatchEvent
from app.schemas import EventFilters, EventOut, EventPageOut

router = APIRouter(prefix="/matches", tags=["events"])

#: Only these columns may be sorted on. Accepting an arbitrary column name from the
#: query string would hand the client control over the query plan.
_SORTABLE = {
    "seq": MatchEvent.seq,
    "tick": MatchEvent.tick,
    "round_num": MatchEvent.round_num,
    "damage_health": MatchEvent.damage_health,
}


def _apply_filters(stmt: Select, match_id: str, filters: EventFilters) -> Select:
    stmt = stmt.where(MatchEvent.match_id == match_id)
    if filters.round_num is not None:
        stmt = stmt.where(MatchEvent.round_num == filters.round_num)
    if filters.event_type:
        stmt = stmt.where(MatchEvent.event_type == filters.event_type)
    if filters.player_key:
        # "Involving this player" covers both sides of a duel, which is what a user
        # filtering by name actually wants.
        stmt = stmt.where(
            or_(
                MatchEvent.actor_key == filters.player_key,
                MatchEvent.victim_key == filters.player_key,
            )
        )
    if filters.side:
        stmt = stmt.where(
            or_(MatchEvent.actor_side == filters.side, MatchEvent.victim_side == filters.side)
        )
    if filters.weapon:
        stmt = stmt.where(MatchEvent.weapon == filters.weapon)
    if filters.min_damage is not None:
        stmt = stmt.where(MatchEvent.damage_health >= filters.min_damage)
    if not filters.include_post_round:
        stmt = stmt.where(MatchEvent.is_post_round.is_(False))
    if filters.search:
        pattern = f"%{filters.search}%"
        stmt = stmt.where(
            or_(
                MatchEvent.actor_name.ilike(pattern),
                MatchEvent.victim_name.ilike(pattern),
                MatchEvent.weapon.ilike(pattern),
                MatchEvent.event_type.ilike(pattern),
                MatchEvent.subtype.ilike(pattern),
            )
        )
    return stmt


@router.get("/{match_id}/events", response_model=EventPageOut)
def get_events(
    match_id: str,
    # A query model rather than Depends(): FastAPI then reports a bad filter as a 422
    # through the normal validation path, instead of letting a raw ValidationError
    # escape as a 500.
    filters: Annotated[EventFilters, Query()],
    session: Session = Depends(get_db),
) -> EventPageOut:
    """A page of the match's event feed.

    Filtering and sorting happen in the database so the client never has to download a
    whole match to narrow it down. ``total`` is the count *after* filtering, which is
    what a pager needs.
    """
    if session.get(Match, match_id) is None:
        raise errors.not_found()

    total = (
        session.scalar(
            _apply_filters(select(func.count()).select_from(MatchEvent), match_id, filters)
        )
        or 0
    )
    column = _SORTABLE[filters.sort]
    ordering = column.asc() if filters.order == "asc" else column.desc()
    rows = session.scalars(
        _apply_filters(select(MatchEvent), match_id, filters)
        # seq is the deterministic tiebreaker, so paging is stable even when the primary
        # sort column has duplicates.
        .order_by(ordering, MatchEvent.seq.asc())
        .limit(filters.limit)
        .offset(filters.offset)
    ).all()
    return EventPageOut(
        items=[EventOut.from_model(r) for r in rows],
        total=total,
        limit=filters.limit,
        offset=filters.offset,
    )


@router.get("/{match_id}/weapons", response_model=list[str])
def get_weapons(match_id: str, session: Session = Depends(get_db)) -> list[str]:
    """Distinct weapons in this match, to populate the event filter without guessing."""
    if session.get(Match, match_id) is None:
        raise errors.not_found()
    rows = session.scalars(
        select(MatchEvent.weapon)
        .where(MatchEvent.match_id == match_id, MatchEvent.weapon.is_not(None))
        .distinct()
        .order_by(MatchEvent.weapon)
    ).all()
    return [r for r in rows if r]


@router.get("/{match_id}/events/count", response_model=dict[str, int])
def count_by_type(match_id: str, session: Session = Depends(get_db)) -> dict[str, int]:
    """Event counts per type, used for the filter chips."""
    if session.get(Match, match_id) is None:
        raise errors.not_found()
    rows = session.execute(
        select(MatchEvent.event_type, func.count())
        .where(MatchEvent.match_id == match_id)
        .group_by(MatchEvent.event_type)
    ).all()
    return {str(event_type): int(count) for event_type, count in rows}
