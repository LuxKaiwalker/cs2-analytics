# Roadmap

This MVP implements level 1 of a three-level product: **what happened**. Levels 2 and 3
are not built, and the point of this document is to record what in the current design
makes them reachable without re-doing the ingestion pipeline.

## A. Behavioural analytics — *why do these outcomes recur?*

Descriptive statistics answer "who fragged"; behavioural analysis answers "why does this
keep happening". Examples: repeated early deaths in the same situation, poor trade
conversion, predictable aggression, utility thrown too late, performance that collapses on
eco rounds.

**What already supports it.** The normalized model deliberately keeps per-event context
that match totals would discard:

- `match_round_players` holds every player's contribution to every round, with side, team,
  `present_at_freeze`, `survived`, damage, utility damage, equipment value and clutch
  state. Round-level patterns cannot be recovered from match totals.
- Kill rows retain positions, weapon, headshot, no-scope, through-smoke, the assister and
  whether the assist was a flash — the raw material for "where and how do I die".
- `match_rounds` carries buy type and equipment value per side, joined through `team_ct`,
  so "performance by economic condition" is a group-by rather than a re-parse.
- Trade detection already produces per-death outcomes, so trade *conversion* is a ratio
  over data that exists.

**What is missing.** Nothing structural — a `behaviour` module reading `NormalizedMatch`
plus the stored round-player rows, and a UI surface for patterns rather than values. The
honest constraint is statistical, not architectural: one match is a small sample, so
pattern claims need either many matches or explicit confidence language.

## B. LLM post-match analyst

The intended pipeline:

```
raw events → validated statistics → behavioural hypotheses → evidence-backed conclusions
           → prioritized training recommendations
```

**The separation that matters is already enforced.** Every number is computed by tested,
deterministic code with a published definition. A language model would consume those
outputs — never produce them — so a generated narrative can be checked against the table
it describes.

Design constraints to carry forward when it is built:

- Conclusions must cite specific rounds, events or metrics. `match_events.seq` is a stable
  citation anchor.
- Hypotheses and evidence must stay visually distinct. A pattern over 13 rounds is a
  hypothesis; a KAST of 23.1% is a measurement.
- No unsupported causal claims. "You died first in 5 of 13 rounds" is evidence; "you are
  overaggressive" is an inference that should be labelled as one.

**Deliberately absent from this MVP:** no LLM dependency, no API key requirement, no
vector database, no agent framework. Adding any of them now would be speculative weight.

## C. Wearable and physiological data

Eventually heart rate, HRV and similar signals could be aligned to the match timeline.

**What supports it.** Every event carries an absolute `tick` and the match records its
`tick_rate` and `tick_rate_source`, so demo time can be converted to wall-clock-relative
seconds and joined against an external time series. A future table keyed by
`(match_id, player_key, t, metric, value)` would attach cleanly without touching the
parsing or analytics layers.

**No such table exists yet**, and that is intentional — an unused schema is speculation.
Two honesty constraints for whoever builds it: not every user owns a wearable, so it must
be strictly optional; and heart rate is not a measurement of stress, nor a predictor of
performance. Presenting a correlation as a cause would be exactly the failure this project
avoids elsewhere.

## D. Training plans and longitudinal improvement

The eventual goal: cross-match statistics, persistent player profiles, trend analysis,
evidence-backed weakness identification, prioritized drills, progress tracking.

**What already supports it.** `match_players` is keyed by `(match_id, player_key)` and
indexed on both `player_key` and `steamid`, so "every match this player appears in" is a
single query today. The analytics layer takes a `NormalizedMatch` and returns plain data,
so a cross-match aggregator composes over it rather than replacing it.

**What is deliberately absent.** There is no global `players` table. Player identity
across matches is a real problem — bots share Steam ID 0, names change, and the same
person can appear under different accounts — and the right time to model it is when the
product actually spans matches, not before. The index makes it cheap to add later.

## Near-term, highest value

1. **A second real demo fixture with a longer scoreline.** The current one is a 13-0 that
   does contain the halftime swap, but overtime and knife rounds are covered only by
   synthetic fixtures.
2. **Per-round behavioural primitives** — trade conversion rate, opening-duel win rate by
   map area, utility timing relative to round start. All computable from stored data.
3. **Cross-match aggregation** over `player_key`, which turns a single report into a trend
   and is the precondition for everything in section D.
