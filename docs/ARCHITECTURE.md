# Architecture

## Shape

```
browser ──HTTP──► FastAPI ──enqueue──► supervisor thread ──spawn──► parse worker process
                     │                                                      │
                     └──────────────── SQLite (WAL) ◄───────────────────────┘
```

One process serves the API. Parsing happens in a **separate, short-lived process** per
demo. Everything is stored in one SQLite file; there is no broker, no cache server and no
second service.

## Why the worker is a subprocess

Three independent reasons, any one of which would be sufficient:

- **Latency.** It is not established that the parser's native core releases the GIL. A
  30-second parse that held it would stall the event loop and every status poll with it.
  *Measured:* p95 poll latency is **8 ms** while an 84 MB demo is being parsed.
- **Cancellation.** A Python thread cannot be killed, so "delete a match while it is
  processing" would be unimplementable in-thread. A process can be terminated.
- **Isolation.** The input is an untrusted binary file by design. A malformed demo that
  aborts inside the native parser takes down only the worker.

A fourth, measured benefit: the child's memory returns to the OS when it exits.

Measured peak RSS, which is where the upload cap comes from:

| Demo | Size | Parse | Peak RSS | Ratio |
|---|---|---|---|---|
| valve de_mirage | 84 MB | 1.3 s | 213 MB | 2.5× |
| esea de_dust2 | 408 MB | 21 s | 528 MB | 1.3× |
| faceit de_mirage | 438 MB | 22 s | 567 MB | 1.3× |

The ratio *falls* with size — the small demo's figure is dominated by fixed interpreter
and library overhead. Extrapolating the small demo's 2.5× would have set the cap far
lower than the data supports, which is why it is set from the large-demo measurement
(600 MiB → roughly 800 MB RSS).

The context is `spawn`, never `fork` — forking a process that owns an event loop, a
connection pool and open SQLite handles duplicates all of them into the child.

## Layers

| Layer | Module | Responsibility |
|---|---|---|
| Ingestion | `app/ingest/` | Validate by content, store under generated names, guarded URL import |
| Parsing | `app/parsing/` | Third-party parser → the normalized model |
| Analytics | `app/analytics/` | Statistics from the normalized model |
| Persistence | `app/persist/`, `app/models.py` | Write and read the derived cache |
| API | `app/api/`, `app/schemas.py` | Typed routes and one error envelope |
| Pipeline | `app/pipeline/` | Queue, supervise, recover |

### Two rules enforced by tests

1. **`import awpy` appears in exactly two modules** — `parsing/awpy_parser.py` and
   `maps/data.py` (which uses it purely as a map-asset client). Replacing the parser means
   writing one new module that produces a `NormalizedMatch`; nothing else changes.
2. **The statistics never read the database.** They are computed from the normalized model
   in memory, so `match_events` is purely a presentation store and its schema cannot
   affect a single number on the scoreboard.

A third convention, not enforceable but deliberate: normalization is vectorized, while
every *sequential* algorithm (damage capping, trade detection, round state) is plain
Python over small dataclasses. A match is a few thousand events, so readability and
unit-testability win over expression gymnastics — and those algorithms are exactly where
correctness bugs live.

## The normalized model

`app/parsing/model.py` defines a parser-independent representation. Three decisions in it
are load-bearing rather than stylistic:

**Players are keyed by a derived `key`, never by Steam ID.** Bots and the SourceTV
recorder all report Steam ID 0; keying on it would collapse them into one player and
corrupt the scoreboard. The key is the Steam ID when real, else `bot:<name>`.

**Every combat row carries `src_idx`**, the parser's original row index, captured before
any sort or filter. Within one source table the row order *is* the demo's message order,
making it the only correct tiebreaker for same-tick events.

**Missing data is represented, not defaulted.** An `Availability` map records whether each
source dataset was present, empty, partial or unsupported, and that provenance travels all
the way to the UI so a metric with no source renders as "unknown" instead of zero.

```
NormalizedMatch
├── meta          map, tick rate (+ provenance), parser version, regulation length
├── players       key → PlayerRef
├── rounds        timings, winner side *and team*, half index, economy
├── roster        per-round side, team, present_at_freeze
├── kills         src_idx, participants, weapon, positions, post-round flag
├── damages       raw *and* capped damage, health_post
├── blinds        thrower, victim, duration
├── utility       one row per thrown grenade
├── objectives    bomb actions
├── availability  per-dataset provenance
└── anomalies     non-fatal oddities, surfaced to the user
```

## Event ordering

Rows are sorted by `(round_num, tick, type_rank, src_idx)` and assigned a dense `seq`.

Within one source table `src_idx` is real evidence. **Across tables it is not** — when a
damage row and a kill row share a tick, nothing in the demo says which came first.
`type_rank` therefore encodes a *reading convention* (the damage that killed you is listed
before the kill), and the invariant that keeps this honest is that **no statistic depends
on cross-type ordering**. Every rule reads exactly one source table plus the static roster.

## Round assignment

The tick timeline is **partitioned**, not matched against `[start_tick, end_tick]`
intervals: a round owns every tick from its start to the next round's start, and the final
round extends indefinitely. Interval matching would silently drop the kills and damage
that occur after a round is decided — 4% of in-round damage rows in the reference demo —
and those losses would land straight in ADR.

## Persistence

SQLite as a **derived cache**: every row can be recomputed by re-parsing the `.dem`, which
is still on disk. That is why there is no migration tool — a schema change bumps
`SCHEMA_VERSION` and affected matches are re-ingested.

Tables: `matches`, `match_players`, `match_rounds`, `match_round_players`, `match_events`.

`match_events` is one table across all event types rather than a table per type, because
the dashboard's primary need is a single chronological, cross-type, filterable feed that
per-type tables would turn into a UNION plus a re-sort on every read. It is declared
`WITHOUT ROWID` with primary key `(match_id, seq)`, so rows are physically clustered per
match in chronological order and the default feed is a range scan — verified with
`EXPLAIN QUERY PLAN`, which shows `SEARCH match_events USING PRIMARY KEY` and no sort.

Required pragmas, applied on every connection: `journal_mode=WAL` (the worker writes
progress while the API reads), `foreign_keys=ON` (**per-connection in SQLite** — without
it every `ON DELETE CASCADE` silently does nothing, so a test proves deletes cascade), and
`busy_timeout=5000`.

## Processing lifecycle

```
uploaded → queued → processing → completed | failed | cancelled
```

The database is the source of truth for status; the in-memory queue only decides order.
That split is what makes restart recovery possible: rows still marked `queued` or
`processing` are re-enqueued with an incremented attempt counter, and anything past the
limit is failed as `abandoned_after_restart`. Without the counter, a demo that reliably
crashes the worker would be retried forever on every restart.

There is a `stage` but **no percentage** — the parser exposes no progress signal, so a
progress bar would be a fabrication. The UI shows the stage and how long it has been
running.

## Upload path

The upload route takes a **raw request body, not multipart**. By the time a multipart
handler runs, the framework has already spooled the whole body to disk, so a size check
there reports the problem without preventing it. Reading the raw stream lets the cap be
enforced mid-transfer and the partial file deleted at once. In layers:

1. ASGI middleware rejects an over-long `Content-Length` before the body is read.
2. The handler streams into a staging file on the **same filesystem** as the final
   directory (so promotion is an atomic rename), hashing as it goes and aborting the
   moment the cap is exceeded — which also covers chunked bodies with no declared length.
3. The leading bytes decide what the file is. The extension is never trusted.
4. The SHA-256 is unique, so re-uploading a demo returns the existing match (409 with its
   id) instead of parsing it twice.

Stored filenames are the match's own UUID; the client-supplied name is kept for display
only and never used to build a path, so traversal is structurally impossible rather than
filtered.

## Frontend

React + TypeScript + Vite, Tailwind v4 tokens, Radix primitives for tooltips and tabs,
Recharts for the score chart. Served same-origin in both modes — Vite proxies `/api` in
development, FastAPI serves the built assets in production — so there is **no CORS
middleware at all**.

Tabs are lazily loaded: the charting library alone is most of the bundle, and a user who
only wants the scoreboard should not download the chart and map code. Initial bundle
363 kB (116 kB gzipped), down from 757 kB.

The UI contract that makes "never silently zero" real: every stat cell reads the match's
`availability` map and renders an em dash plus the reason when its source dataset is
empty.
