"""Typed API request and response models.

These are the contract the frontend generates its TypeScript from, so the shapes here
are deliberately explicit about optionality: a ``None`` in a metric field means "this
demo could not tell us", and the client renders it as unknown rather than as zero.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from app.analytics.definitions import OMITTED_METRICS, PLAYER_METRICS
from app.models import Match, MatchEvent, MatchPlayer, MatchRound, MatchRoundPlayer


def _loads(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    """The single error shape every failing endpoint returns."""

    error: ErrorDetail


class DatasetAvailabilityOut(BaseModel):
    """Whether a source dataset yielded usable data, and why not when it did not."""

    state: Literal["available", "empty", "partial", "unsupported"]
    row_count: int = 0
    reason: str | None = None


class AnomalyOut(BaseModel):
    """A non-fatal oddity worth showing the user instead of hiding."""

    code: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


class ImportRequest(BaseModel):
    """Import a demo from a publicly reachable URL."""

    url: HttpUrl
    filename: str | None = Field(default=None, max_length=255)


class MatchSummaryOut(BaseModel):
    """A row in the match library."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    stage: str | None = None
    stage_started_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    original_filename: str | None = None
    size_bytes: int | None = None
    source: str
    map_name: str | None = None
    round_count: int | None = None
    team_a_name: str | None = None
    team_b_name: str | None = None
    team_a_score: int | None = None
    team_b_score: int | None = None
    winner_team: str | None = None
    has_overtime: bool = False
    uploaded_at: datetime
    """When the file was uploaded. A demo header carries no wall-clock match date, so
    there is deliberately no "played at" field to invent."""
    completed_at: datetime | None = None

    @classmethod
    def from_model(cls, record: Match) -> MatchSummaryOut:
        return cls(
            id=record.id,
            status=record.status,
            stage=record.stage,
            stage_started_at=record.stage_started_at,
            error_code=record.error_code,
            error_message=record.error_message,
            original_filename=record.original_filename,
            size_bytes=record.size_bytes,
            source=record.source,
            map_name=record.map_name,
            round_count=record.round_count,
            team_a_name=record.team_a_name,
            team_b_name=record.team_b_name,
            team_a_score=record.team_a_score,
            team_b_score=record.team_b_score,
            winner_team=record.winner_team,
            has_overtime=record.has_overtime,
            uploaded_at=record.created_at,
            completed_at=record.completed_at,
        )


class MatchDetailOut(MatchSummaryOut):
    """Everything about one match except its per-player and per-round tables."""

    tick_rate: float | None = None
    tick_rate_source: str | None = None
    regulation_rounds: int | None = None
    demo_version_name: str | None = None
    server_name: str | None = None
    playback_time: float | None = None
    parser_name: str | None = None
    parser_version: str | None = None
    analytics_version: int | None = None
    roster_source: str | None = None
    parse_seconds: float | None = None
    peak_rss_mb: int | None = None
    sha256: str | None = None
    availability: dict[str, DatasetAvailabilityOut] = Field(default_factory=dict)
    anomalies: list[AnomalyOut] = Field(default_factory=list)

    @classmethod
    def from_model(cls, record: Match) -> MatchDetailOut:
        base = MatchSummaryOut.from_model(record).model_dump()
        availability_raw = _loads(record.availability_json) or {}
        anomalies_raw = _loads(record.anomalies_json) or []
        return cls(
            **base,
            tick_rate=record.tick_rate,
            tick_rate_source=record.tick_rate_source,
            regulation_rounds=record.regulation_rounds,
            demo_version_name=record.demo_version_name,
            server_name=record.server_name,
            playback_time=record.playback_time,
            parser_name=record.parser_name,
            parser_version=record.parser_version,
            analytics_version=record.analytics_version,
            roster_source=record.roster_source,
            parse_seconds=record.parse_seconds,
            peak_rss_mb=record.peak_rss_mb,
            sha256=record.sha256,
            availability={
                name: DatasetAvailabilityOut(**entry) for name, entry in availability_raw.items()
            },
            anomalies=[AnomalyOut(**a) for a in anomalies_raw],
        )


class MatchCreatedOut(BaseModel):
    """Acknowledgement that a demo was accepted for processing."""

    id: str
    status: str
    message: str = "The demo was accepted and queued for processing."


class PlayerStatsOut(BaseModel):
    """One scoreboard row. Null numeric fields mean unknown, not zero."""

    model_config = ConfigDict(from_attributes=True)

    player_key: str
    steamid: int | None = None
    name: str
    is_bot: bool = False
    team: str | None = None
    last_side: str | None = None
    rounds_present: int = 0

    kills: int = 0
    deaths: int = 0
    assists: int = 0
    flash_assists: int = 0
    team_kills: int = 0
    self_kills: int = 0
    headshot_kills: int = 0
    opening_kills: int = 0
    opening_deaths: int = 0
    traded_deaths: int = 0
    trade_kills: int = 0

    kd: float | None = None
    kpr: float | None = None
    adr: float | None = None
    headshot_pct: float | None = None
    kast: float | None = None

    damage_total: int | None = None
    utility_damage: int | None = None
    flashes_thrown: int | None = None
    enemies_flashed: int | None = None
    flash_duration_dealt: float | None = None

    multikill_2k: int = 0
    multikill_3k: int = 0
    multikill_4k: int = 0
    multikill_5k: int = 0
    clutches_played: int = 0
    clutches_won: int = 0
    clutch_1v1: int = 0
    clutch_1v2: int = 0
    clutch_1v3: int = 0
    clutch_1v4: int = 0
    clutch_1v5: int = 0

    @classmethod
    def from_model(cls, row: MatchPlayer) -> PlayerStatsOut:
        return cls.model_validate(row)


class RoundPlayerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    player_key: str
    name: str
    side: str | None = None
    team: str | None = None
    present_at_freeze: bool = True
    survived: bool = False
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    damage: int = 0
    utility_damage: int = 0
    equipment_value: int | None = None
    is_clutch: bool = False
    clutch_opponents: int | None = None
    clutch_won: bool | None = None

    @classmethod
    def from_model(cls, row: MatchRoundPlayer) -> RoundPlayerOut:
        return cls.model_validate(row)


class RoundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    round_num: int
    start_tick: int
    freeze_end_tick: int | None = None
    end_tick: int
    official_end_tick: int | None = None
    duration_s: float | None = None
    winner_side: str | None = None
    winner_team: str | None = None
    reason_name: str | None = None
    is_knife_round: bool = False
    half_index: int = 0
    is_overtime: bool = False
    team_ct: str | None = None
    score_a_after: int = 0
    score_b_after: int = 0
    kills_count: int = 0
    bomb_planted: bool = False
    bomb_plant_tick: int | None = None
    bombsite: str | None = None
    bomb_defused: bool = False
    bomb_exploded: bool = False
    ct_equipment_value: int | None = None
    t_equipment_value: int | None = None
    ct_buy_type: str | None = None
    t_buy_type: str | None = None
    players: list[RoundPlayerOut] = Field(default_factory=list)

    @classmethod
    def from_model(cls, row: MatchRound, players: list[MatchRoundPlayer]) -> RoundOut:
        out = cls.model_validate(row)
        out.players = [RoundPlayerOut.from_model(p) for p in players]
        return out


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    round_seq: int
    round_num: int
    tick: int
    time_in_round_s: float | None = None
    is_post_round: bool = False
    event_type: str
    subtype: str | None = None
    actor_key: str | None = None
    actor_name: str | None = None
    actor_side: str | None = None
    victim_key: str | None = None
    victim_name: str | None = None
    victim_side: str | None = None
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
    extra: dict[str, Any] | None = None

    @classmethod
    def from_model(cls, row: MatchEvent) -> EventOut:
        out = cls.model_validate(row)
        out.extra = _loads(row.extra_json)
        return out


class PageMeta(BaseModel):
    total: int
    limit: int
    offset: int


class EventPageOut(BaseModel):
    items: list[EventOut]
    total: int
    limit: int
    offset: int


class MatchListOut(BaseModel):
    items: list[MatchSummaryOut]
    total: int
    limit: int
    offset: int


class MetricDefinitionOut(BaseModel):
    """A metric's published definition, used for the UI's tooltips."""

    key: str
    label: str
    short_label: str
    description: str
    format: str
    denominator: str | None = None
    nullable: bool = False
    higher_is_better: bool = True
    caveat: str | None = None
    source_datasets: list[str] = Field(default_factory=list)
    default_visible: bool = True


class OmittedMetricOut(BaseModel):
    """A metric intentionally not provided, with the reason."""

    key: str
    label: str
    reason: str


class MetricsOut(BaseModel):
    player_metrics: list[MetricDefinitionOut]
    omitted: list[OmittedMetricOut]
    notes: list[str]


def metrics_payload() -> MetricsOut:
    """Publish the metric registry so the UI and the docs cannot drift from the code."""
    return MetricsOut(
        player_metrics=[
            MetricDefinitionOut(
                key=m.key,
                label=m.label,
                short_label=m.short_label,
                description=m.description,
                format=str(m.fmt),
                denominator=m.denominator,
                nullable=m.nullable,
                higher_is_better=m.higher_is_better,
                caveat=m.caveat,
                source_datasets=list(m.source_datasets),
                default_visible=m.default_visible,
            )
            for m in PLAYER_METRICS
        ],
        omitted=[OmittedMetricOut(**m) for m in OMITTED_METRICS],
        notes=[
            "A null value means the demo did not contain the data needed for that "
            "metric. It is never a substitute for zero.",
            "Rate metrics (ADR, KAST, kills per round) divide by the match's scored "
            "round count, excluding knife rounds. Rounds a player was present for are "
            "reported separately as 'rounds present'.",
            "Deaths include suicides and world deaths, so a scoreboard that omits "
            "self-inflicted deaths may read one lower.",
        ],
    )


class MapLevelOut(BaseModel):
    """One radar image for a map, with the altitude band it covers."""

    id: str
    radar_url: str
    altitude_min: float | None = None
    altitude_max: float | None = None


class MapInfoOut(BaseModel):
    """The world-to-radar transform for drawing positions on a map image.

    The client computes ``rx = (x - pos_x) / scale`` and ``ry = (pos_y - y) / scale``,
    then scales by the rendered size. The transform lives in exactly one place — here —
    so the server and the client cannot disagree about it.
    """

    map_name: str
    available: bool
    pos_x: float | None = None
    pos_y: float | None = None
    scale: float | None = None
    image_width: int | None = None
    image_height: int | None = None
    levels: list[MapLevelOut] = Field(default_factory=list)
    reason: str | None = None
    """Why the map is unavailable, when it is. The UI says so rather than drawing a
    plausible-looking but wrong map."""


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    worker_alive: bool
    queue_depth: int
    processing_match_id: str | None = None
    disk_free_bytes: int | None = None
    demo_bytes_stored: int | None = None
    max_demo_bytes: int
    parser: str
    parser_version: str | None = None
    schema_version: int


EventSort = Annotated[
    Literal["seq", "tick", "round_num", "damage_health"],
    Field(description="Whitelisted sort columns; arbitrary columns are rejected."),
]


class EventFilters(BaseModel):
    """Validated filters for the event feed."""

    round_num: int | None = Field(default=None, ge=1)
    event_type: str | None = None
    player_key: str | None = None
    side: Literal["T", "CT"] | None = None
    weapon: str | None = None
    min_damage: int | None = Field(default=None, ge=0)
    search: str | None = Field(default=None, max_length=100)
    include_post_round: bool = True
    sort: EventSort = "seq"
    order: Literal["asc", "desc"] = "asc"
    limit: int = Field(default=100, ge=1, le=200)
    offset: int = Field(default=0, ge=0, le=100_000)

    @field_validator("event_type")
    @classmethod
    def _known_event_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        from app.analytics.events import EventType  # noqa: PLC0415

        allowed = {str(t) for t in EventType}
        if value not in allowed:
            msg = f"unknown event type; expected one of {sorted(allowed)}"
            raise ValueError(msg)
        return value
