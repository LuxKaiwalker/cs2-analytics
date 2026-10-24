/**
 * API types.
 *
 * These mirror the backend's Pydantic schemas. `npm run gen:api` regenerates an exact
 * copy from the live OpenAPI document into `generated.ts`; these hand-written types are
 * what the app imports so it still typechecks without a running server, and the
 * generated file is the check that they have not drifted.
 *
 * `null` in a metric field means the demo could not supply it. It is never a stand-in
 * for zero, and the UI renders it as an em dash with the reason in a tooltip.
 */

export type MatchStatus =
  | 'uploaded'
  | 'queued'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type ProcessingStage =
  | 'validating'
  | 'downloading'
  | 'parsing'
  | 'normalizing'
  | 'computing'
  | 'persisting'

export type Side = 'T' | 'CT'
export type Team = 'A' | 'B'

export type DatasetState = 'available' | 'empty' | 'partial' | 'unsupported'

export interface DatasetAvailability {
  state: DatasetState
  row_count: number
  reason: string | null
}

export interface Anomaly {
  code: string
  message: string
  context: Record<string, unknown>
}

export interface MatchSummary {
  id: string
  status: MatchStatus
  stage: ProcessingStage | null
  stage_started_at: string | null
  error_code: string | null
  error_message: string | null
  original_filename: string | null
  size_bytes: number | null
  source: string
  map_name: string | null
  round_count: number | null
  team_a_name: string | null
  team_b_name: string | null
  team_a_score: number | null
  team_b_score: number | null
  winner_team: Team | null
  has_overtime: boolean
  uploaded_at: string
  completed_at: string | null
}

export interface MatchDetail extends MatchSummary {
  tick_rate: number | null
  tick_rate_source: string | null
  regulation_rounds: number | null
  demo_version_name: string | null
  server_name: string | null
  playback_time: number | null
  parser_name: string | null
  parser_version: string | null
  analytics_version: number | null
  roster_source: string | null
  parse_seconds: number | null
  peak_rss_mb: number | null
  sha256: string | null
  availability: Record<string, DatasetAvailability>
  anomalies: Anomaly[]
}

export interface PlayerStats {
  player_key: string
  steamid: number | null
  name: string
  is_bot: boolean
  team: Team | null
  last_side: Side | null
  rounds_present: number

  kills: number
  deaths: number
  assists: number
  flash_assists: number
  team_kills: number
  self_kills: number
  headshot_kills: number
  opening_kills: number
  opening_deaths: number
  traded_deaths: number
  trade_kills: number

  kd: number | null
  kpr: number | null
  adr: number | null
  headshot_pct: number | null
  kast: number | null

  damage_total: number | null
  utility_damage: number | null
  flashes_thrown: number | null
  enemies_flashed: number | null
  flash_duration_dealt: number | null

  multikill_2k: number
  multikill_3k: number
  multikill_4k: number
  multikill_5k: number
  clutches_played: number
  clutches_won: number
  clutch_1v1: number
  clutch_1v2: number
  clutch_1v3: number
  clutch_1v4: number
  clutch_1v5: number
}

export interface RoundPlayer {
  player_key: string
  name: string
  side: Side | null
  team: Team | null
  present_at_freeze: boolean
  survived: boolean
  kills: number
  deaths: number
  assists: number
  damage: number
  utility_damage: number
  equipment_value: number | null
  is_clutch: boolean
  clutch_opponents: number | null
  clutch_won: boolean | null
}

export interface Round {
  round_num: number
  start_tick: number
  freeze_end_tick: number | null
  end_tick: number
  official_end_tick: number | null
  duration_s: number | null
  winner_side: Side | null
  winner_team: Team | null
  reason_name: string | null
  is_knife_round: boolean
  half_index: number
  is_overtime: boolean
  team_ct: Team | null
  score_a_after: number
  score_b_after: number
  kills_count: number
  bomb_planted: boolean
  bomb_plant_tick: number | null
  bombsite: string | null
  bomb_defused: boolean
  bomb_exploded: boolean
  ct_equipment_value: number | null
  t_equipment_value: number | null
  ct_buy_type: string | null
  t_buy_type: string | null
  players: RoundPlayer[]
}

export type EventType =
  | 'round_start'
  | 'freeze_end'
  | 'utility_thrown'
  | 'flash'
  | 'damage'
  | 'kill'
  | 'bomb'
  | 'round_end'

export interface MatchEvent {
  seq: number
  round_seq: number
  round_num: number
  tick: number
  time_in_round_s: number | null
  is_post_round: boolean
  event_type: EventType
  subtype: string | null
  actor_key: string | null
  actor_name: string | null
  actor_side: Side | null
  victim_key: string | null
  victim_name: string | null
  victim_side: Side | null
  weapon: string | null
  is_headshot: boolean
  damage_health: number | null
  damage_armor: number | null
  hitgroup: string | null
  actor_x: number | null
  actor_y: number | null
  actor_z: number | null
  victim_x: number | null
  victim_y: number | null
  victim_z: number | null
  extra: Record<string, unknown> | null
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface MetricDefinition {
  key: string
  label: string
  short_label: string
  description: string
  format: 'integer' | 'decimal' | 'percent' | 'ratio'
  denominator: string | null
  nullable: boolean
  higher_is_better: boolean
  caveat: string | null
  source_datasets: string[]
  default_visible: boolean
}

export interface OmittedMetric {
  key: string
  label: string
  reason: string
}

export interface Metrics {
  player_metrics: MetricDefinition[]
  omitted: OmittedMetric[]
  notes: string[]
}

export interface MapLevel {
  id: string
  radar_url: string
  altitude_min: number | null
  altitude_max: number | null
}

export interface MapInfo {
  map_name: string
  available: boolean
  pos_x: number | null
  pos_y: number | null
  scale: number | null
  image_width: number | null
  image_height: number | null
  levels: MapLevel[]
  reason: string | null
}

export interface Health {
  status: 'ok' | 'degraded'
  database: boolean
  worker_alive: boolean
  queue_depth: number
  processing_match_id: string | null
  disk_free_bytes: number | null
  demo_bytes_stored: number | null
  max_demo_bytes: number
  parser: string
  parser_version: string | null
  schema_version: number
}

export interface EventQuery {
  round_num?: number
  event_type?: EventType
  player_key?: string
  side?: Side
  weapon?: string
  min_damage?: number
  search?: string
  include_post_round?: boolean
  sort?: 'seq' | 'tick' | 'round_num' | 'damage_health'
  order?: 'asc' | 'desc'
  limit?: number
  offset?: number
}
