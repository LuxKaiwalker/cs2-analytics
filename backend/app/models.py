"""Persistence schema.

The database is a **derived cache** of the demo files, not a system of record: every row
can be recomputed by re-parsing the ``.dem``. That is why there are no migrations —
a schema change bumps :data:`SCHEMA_VERSION` and affected matches are re-ingested, which
is both simpler and more honest than migrating data whose source is still on disk.

Two shape decisions worth stating:

* ``match_events`` is one table across all event types rather than a table per type. The
  dashboard's primary need is a single chronological, cross-type, filterable feed, which
  per-type tables would turn into a UNION plus a re-sort on every read. Type-specific
  fields live in ``extra_json``, except anything filterable, which gets a real column.
* It is declared ``WITHOUT ROWID`` with primary key ``(match_id, seq)``, so rows are
  physically clustered per match in chronological order and the default feed is a range
  scan instead of a scan-and-sort.

**The statistics never read this table.** They are computed from the normalized model in
memory, so ``match_events`` is purely presentational and its schema cannot affect a
single number on the scoreboard.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

#: Bumping this invalidates stored analytics; affected matches are re-ingested.
SCHEMA_VERSION = 1


class Base(DeclarativeBase):
    pass


class MatchStatus(StrEnum):
    """The processing lifecycle."""

    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in (MatchStatus.COMPLETED, MatchStatus.FAILED, MatchStatus.CANCELLED)


class ProcessingStage(StrEnum):
    """Where a running job has got to.

    There is deliberately no percentage: the parser exposes no progress signal, so any
    number would be invented. The UI shows the stage and how long it has been running.
    """

    VALIDATING = "validating"
    DOWNLOADING = "downloading"
    PARSING = "parsing"
    NORMALIZING = "normalizing"
    COMPUTING = "computing"
    PERSISTING = "persisting"


def _now() -> datetime:
    return datetime.now(UTC)


class SchemaVersion(Base):
    """Single row recording the schema the stored analytics were written with."""

    __tablename__ = "schema_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)


class Match(Base):
    """One uploaded demo and everything known about processing it."""

    __tablename__ = "matches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)

    # --- source -------------------------------------------------------------
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    """Content hash. Uniqueness gives idempotent uploads: re-posting the same demo
    returns the existing match instead of duplicating the work."""
    original_filename: Mapped[str | None] = mapped_column(String(255))
    stored_path: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(16), default="upload")
    source_url: Mapped[str | None] = mapped_column(Text)

    # --- lifecycle ----------------------------------------------------------
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    stage: Mapped[str | None] = mapped_column(String(24))
    stage_started_at: Mapped[datetime | None] = mapped_column()
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """Incremented on restart recovery. Without it, a crash loop would re-parse forever."""
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(48))
    error_message: Mapped[str | None] = mapped_column(Text)

    # --- match metadata -----------------------------------------------------
    map_name: Mapped[str | None] = mapped_column(String(64), index=True)
    tick_rate: Mapped[float | None] = mapped_column(Float)
    tick_rate_source: Mapped[str | None] = mapped_column(String(16))
    """``header`` or ``fallback``. A fallback rate makes the trade window approximate,
    so the provenance is surfaced rather than hidden."""
    round_count: Mapped[int | None] = mapped_column(Integer)
    regulation_rounds: Mapped[int | None] = mapped_column(Integer)
    has_overtime: Mapped[bool] = mapped_column(Boolean, default=False)
    team_a_name: Mapped[str | None] = mapped_column(String(64))
    team_b_name: Mapped[str | None] = mapped_column(String(64))
    team_a_score: Mapped[int | None] = mapped_column(Integer)
    team_b_score: Mapped[int | None] = mapped_column(Integer)
    winner_team: Mapped[str | None] = mapped_column(String(1))
    demo_version_name: Mapped[str | None] = mapped_column(String(64))
    server_name: Mapped[str | None] = mapped_column(Text)
    playback_time: Mapped[float | None] = mapped_column(Float)
    playback_ticks: Mapped[int | None] = mapped_column(Integer)

    # --- provenance ---------------------------------------------------------
    parser_name: Mapped[str | None] = mapped_column(String(32))
    parser_version: Mapped[str | None] = mapped_column(String(32))
    analytics_version: Mapped[int | None] = mapped_column(Integer)
    schema_version: Mapped[int | None] = mapped_column(Integer)
    roster_source: Mapped[str | None] = mapped_column(String(24))
    availability_json: Mapped[str | None] = mapped_column(Text)
    """Per-dataset availability. The UI needs this to render "unknown" instead of 0."""
    anomalies_json: Mapped[str | None] = mapped_column(Text)
    peak_rss_mb: Mapped[int | None] = mapped_column(Integer)
    parse_seconds: Mapped[float | None] = mapped_column(Float)

    created_at: Mapped[datetime] = mapped_column(default=_now, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=_now, onupdate=_now)
    completed_at: Mapped[datetime | None] = mapped_column()

    players: Mapped[list[MatchPlayer]] = relationship(
        back_populates="match", cascade="all, delete-orphan", passive_deletes=True
    )
    rounds: Mapped[list[MatchRound]] = relationship(
        back_populates="match", cascade="all, delete-orphan", passive_deletes=True
    )


class MatchPlayer(Base):
    """A scoreboard row. Nullable numeric columns mean "unknown", never zero."""

    __tablename__ = "match_players"

    match_id: Mapped[str] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    player_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Derived identity, not the Steam ID: bots and the demo recorder all report 0."""
    steamid: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    team: Mapped[str | None] = mapped_column(String(1))
    last_side: Mapped[str | None] = mapped_column(String(2))
    rounds_present: Mapped[int] = mapped_column(Integer, default=0)

    kills: Mapped[int] = mapped_column(Integer, default=0)
    deaths: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    flash_assists: Mapped[int] = mapped_column(Integer, default=0)
    team_kills: Mapped[int] = mapped_column(Integer, default=0)
    self_kills: Mapped[int] = mapped_column(Integer, default=0)
    headshot_kills: Mapped[int] = mapped_column(Integer, default=0)
    opening_kills: Mapped[int] = mapped_column(Integer, default=0)
    opening_deaths: Mapped[int] = mapped_column(Integer, default=0)
    traded_deaths: Mapped[int] = mapped_column(Integer, default=0)
    trade_kills: Mapped[int] = mapped_column(Integer, default=0)

    kd: Mapped[float | None] = mapped_column(Float)
    kpr: Mapped[float | None] = mapped_column(Float)
    adr: Mapped[float | None] = mapped_column(Float)
    headshot_pct: Mapped[float | None] = mapped_column(Float)
    kast: Mapped[float | None] = mapped_column(Float)

    damage_total: Mapped[int | None] = mapped_column(Integer)
    utility_damage: Mapped[int | None] = mapped_column(Integer)
    flashes_thrown: Mapped[int | None] = mapped_column(Integer)
    enemies_flashed: Mapped[int | None] = mapped_column(Integer)
    flash_duration_dealt: Mapped[float | None] = mapped_column(Float)

    multikill_2k: Mapped[int] = mapped_column(Integer, default=0)
    multikill_3k: Mapped[int] = mapped_column(Integer, default=0)
    multikill_4k: Mapped[int] = mapped_column(Integer, default=0)
    multikill_5k: Mapped[int] = mapped_column(Integer, default=0)

    clutches_played: Mapped[int] = mapped_column(Integer, default=0)
    clutches_won: Mapped[int] = mapped_column(Integer, default=0)
    clutch_1v1: Mapped[int] = mapped_column(Integer, default=0)
    clutch_1v2: Mapped[int] = mapped_column(Integer, default=0)
    clutch_1v3: Mapped[int] = mapped_column(Integer, default=0)
    clutch_1v4: Mapped[int] = mapped_column(Integer, default=0)
    clutch_1v5: Mapped[int] = mapped_column(Integer, default=0)

    match: Mapped[Match] = relationship(back_populates="players")

    __table_args__ = (
        # Cross-match lookups for a single player: the index that makes longitudinal
        # profiles possible later without changing the ingestion pipeline.
        Index("idx_player_steamid", "steamid"),
        Index("idx_player_key", "player_key"),
    )


class MatchRound(Base):
    """One round's outcome, economy and objective state."""

    __tablename__ = "match_rounds"

    match_id: Mapped[str] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    round_num: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_tick: Mapped[int] = mapped_column(Integer)
    freeze_end_tick: Mapped[int | None] = mapped_column(Integer)
    end_tick: Mapped[int] = mapped_column(Integer)
    official_end_tick: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float)
    winner_side: Mapped[str | None] = mapped_column(String(2))
    winner_team: Mapped[str | None] = mapped_column(String(1))
    reason_name: Mapped[str | None] = mapped_column(String(32))
    is_knife_round: Mapped[bool] = mapped_column(Boolean, default=False)
    half_index: Mapped[int] = mapped_column(Integer, default=0)
    is_overtime: Mapped[bool] = mapped_column(Boolean, default=False)
    team_ct: Mapped[str | None] = mapped_column(String(1))
    """Which team played CT. Without it, a side-keyed score is wrong after halftime."""
    score_a_after: Mapped[int] = mapped_column(Integer, default=0)
    score_b_after: Mapped[int] = mapped_column(Integer, default=0)
    kills_count: Mapped[int] = mapped_column(Integer, default=0)
    bomb_planted: Mapped[bool] = mapped_column(Boolean, default=False)
    bomb_plant_tick: Mapped[int | None] = mapped_column(Integer)
    bombsite: Mapped[str | None] = mapped_column(String(1))
    bomb_defused: Mapped[bool] = mapped_column(Boolean, default=False)
    bomb_exploded: Mapped[bool] = mapped_column(Boolean, default=False)
    ct_equipment_value: Mapped[int | None] = mapped_column(Integer)
    t_equipment_value: Mapped[int | None] = mapped_column(Integer)
    ct_buy_type: Mapped[str | None] = mapped_column(String(8))
    t_buy_type: Mapped[str | None] = mapped_column(String(8))

    match: Mapped[Match] = relationship(back_populates="rounds")


class MatchRoundPlayer(Base):
    """A player's contribution to one round.

    Retained because round-level per-player context is the raw material for the
    behavioural analytics on the roadmap (repeated early deaths, trade conversion,
    performance by buy type) — none of which can be recovered from match totals.
    """

    __tablename__ = "match_round_players"

    match_id: Mapped[str] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    round_num: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    side: Mapped[str | None] = mapped_column(String(2))
    team: Mapped[str | None] = mapped_column(String(1))
    present_at_freeze: Mapped[bool] = mapped_column(Boolean, default=True)
    survived: Mapped[bool] = mapped_column(Boolean, default=False)
    kills: Mapped[int] = mapped_column(Integer, default=0)
    deaths: Mapped[int] = mapped_column(Integer, default=0)
    assists: Mapped[int] = mapped_column(Integer, default=0)
    damage: Mapped[int] = mapped_column(Integer, default=0)
    utility_damage: Mapped[int] = mapped_column(Integer, default=0)
    equipment_value: Mapped[int | None] = mapped_column(Integer)
    is_clutch: Mapped[bool] = mapped_column(Boolean, default=False)
    clutch_opponents: Mapped[int | None] = mapped_column(Integer)
    clutch_won: Mapped[bool | None] = mapped_column(Boolean)

    __table_args__ = (Index("idx_rp_match_round", "match_id", "round_num"),)


class MatchEvent(Base):
    """One row of the unified chronological event feed."""

    __tablename__ = "match_events"

    match_id: Mapped[str] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    round_seq: Mapped[int] = mapped_column(Integer)
    round_num: Mapped[int] = mapped_column(Integer)
    tick: Mapped[int] = mapped_column(Integer)
    time_in_round_s: Mapped[float | None] = mapped_column(Float)
    is_post_round: Mapped[bool] = mapped_column(Boolean, default=False)
    event_type: Mapped[str] = mapped_column(String(20))
    subtype: Mapped[str | None] = mapped_column(String(24))
    actor_key: Mapped[str | None] = mapped_column(String(64))
    actor_name: Mapped[str | None] = mapped_column(String(128))
    actor_side: Mapped[str | None] = mapped_column(String(2))
    victim_key: Mapped[str | None] = mapped_column(String(64))
    victim_name: Mapped[str | None] = mapped_column(String(128))
    victim_side: Mapped[str | None] = mapped_column(String(2))
    weapon: Mapped[str | None] = mapped_column(String(32))
    is_headshot: Mapped[bool] = mapped_column(Boolean, default=False)
    damage_health: Mapped[int | None] = mapped_column(Integer)
    damage_armor: Mapped[int | None] = mapped_column(Integer)
    hitgroup: Mapped[str | None] = mapped_column(String(16))
    actor_x: Mapped[float | None] = mapped_column(Float)
    actor_y: Mapped[float | None] = mapped_column(Float)
    actor_z: Mapped[float | None] = mapped_column(Float)
    victim_x: Mapped[float | None] = mapped_column(Float)
    victim_y: Mapped[float | None] = mapped_column(Float)
    victim_z: Mapped[float | None] = mapped_column(Float)
    extra_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        # Each index leads with match_id and trails with seq, so a filtered feed stays a
        # single ordered range scan rather than a scan plus a sort.
        Index("idx_ev_round", "match_id", "round_num", "seq"),
        Index("idx_ev_type", "match_id", "event_type", "seq"),
        Index("idx_ev_actor", "match_id", "actor_key", "seq"),
        Index("idx_ev_victim", "match_id", "victim_key", "seq"),
        UniqueConstraint("match_id", "seq", name="uq_event_seq"),
        {"sqlite_with_rowid": False},
    )
