"""Create tables and detect stale stored analytics.

There is no migration tool here on purpose: every row is derived from a ``.dem`` that is
still on disk, so the correct response to a schema change is to re-ingest, not to migrate
data whose source of truth has not moved.
"""

from __future__ import annotations

import logging

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import SCHEMA_VERSION, Base, SchemaVersion

logger = logging.getLogger(__name__)


def init_schema(engine: Engine) -> int | None:
    """Create any missing tables and return the previously stored schema version."""
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        row = session.scalar(select(SchemaVersion).where(SchemaVersion.id == 1))
        previous = row.version if row else None
        if row is None:
            session.add(SchemaVersion(id=1, version=SCHEMA_VERSION))
        else:
            row.version = SCHEMA_VERSION
        session.commit()
    if previous is not None and previous != SCHEMA_VERSION:
        logger.warning(
            "stored analytics were written with schema v%s but this build expects v%s; "
            "re-ingest affected matches to refresh them",
            previous,
            SCHEMA_VERSION,
        )
    return previous
