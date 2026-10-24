# Metric definitions

Every number in the product is defined here, and the same definitions are served from
`GET /api/metrics` — the UI's tooltips read from that endpoint, so a metric cannot be
documented as one thing and computed as another. A test asserts that every field on the
computed scoreboard has an entry in the registry.

## Two conventions that apply everywhere

**A `null` means unknown, never zero.** If a metric's denominator is zero, or the demo
simply did not contain the data it needs, the value is `null` and the UI renders an em
dash with the reason in a tooltip. Zero is a real measurement and reserving it for
"we don't know" would misrepresent the match. This is why a player with no kills has a
`null` headshot percentage rather than `0%`.

**Rates divide by the match's scored round count** — every round except knife rounds —
not by the rounds a particular player was present for. That is the convention every
public scoreboard uses, and it understates a mid-match substitute. The rounds a player
was actually present for are reported separately as `rounds_present`.

## Combat

| Metric | Definition |
|---|---|
| `kills` | Enemy kills. Suicides, world deaths and team kills are excluded and counted separately as `self_kills` / `team_kills`. |
| `deaths` | Every death, **including** suicides and world deaths. |
| `assists` | Kill assists credited by the game, **excluding** flash assists. |
| `flash_assists` | Assists where the player's flashbang set up the kill. |
| `kd` | `kills / deaths`. **`null` when the player has no deaths** — the ratio is undefined, not infinite and not zero. |
| `kpr` | `kills / scored rounds`. |
| `headshot_kills` | Kills whose fatal hit was to the head. |
| `headshot_pct` | `headshot_kills / kills × 100`. The denominator is **kills**, not shots or hits. **`null` with no kills.** |
| `opening_kills` / `opening_deaths` | Attacker and victim of the first *enemy* kill of a round. A suicide that happens to open a round is skipped, so it neither takes the opening nor hands anyone a phantom opening death. |
| `team_kills` / `self_kills` | Kills on a teammate; suicides, fall damage and world deaths. |
| `multikill_2k … 5k` | Rounds with **exactly** 2/3/4 kills, and 5-or-more for `5k`. Mutually exclusive. |

### Validity rules

A kill counts only if both participants resolve, they are different players, and they
are on opposite sides. The order of these checks matters: **a suicide is tested before a
team kill**, because a suicide trivially shares the victim's side and would otherwise be
miscounted as a team kill. The reference demo ends with five post-match world suicides,
all of which would have been reported as team kills under the naive ordering.

## Damage

**ADR** is the average *capped* enemy damage per scored round.

The capping is the single most consequential calculation in the app. Demos report raw
damage that routinely exceeds the victim's remaining health — a Deagle hit in the
reference demo reports **199** against a 100 HP target — so summing the raw values
inflates ADR substantially. On that demo, capping takes 12 642 raw damage down to
**7 748**: a 39% difference.

Within each `(round, victim)` the hits are walked in `(tick, src_idx)` order and each is
credited at most the health still standing. The next cap is the *lower* of the victim's
reported `health_post` and what remains after crediting the hit, which makes
"at most 100 health absorbed per victim per round" hold unconditionally. That invariant
is asserted both as a property test and against the real demo.

The parser's own `health_pre` field is deliberately **not** used: upstream documents it
as a reconstruction (`health_post + damage`, clamped to 100), so two 80-damage hits would
each see a full-health target and credit 160.

`src_idx` — the parser's original row index — is the tiebreaker for simultaneous hits.
When two attackers land lethal damage on the same tick, the earlier source row takes the
remaining health and the later is credited nothing. Without it the result would differ
between runs. The reference demo contains 25 same-tick damage groups, so this is not
hypothetical.

| Metric | Definition |
|---|---|
| `adr` | Capped enemy damage ÷ scored rounds. Team, self and world damage excluded. |
| `damage_total` | The numerator of ADR. |
| `utility_damage` | Capped enemy damage from `hegrenade`, `inferno`, `molotov`, `incgrenade`, `firebomb`. Unknown grenade-like weapon strings raise a visible anomaly rather than silently dropping out. |

**Post-round damage is included.** Damage genuinely occurs after a round is decided (8 of
209 in-round damage rows in the reference demo). Those events are flagged `is_post_round`
so the UI can mark them, but they are counted — which matches upstream and HLTV. Some
sites exclude them, which accounts for a few points of ADR difference.

## Trades

A **trade** is a kill that avenges a teammate killed within **5.25 seconds**, measured in
ticks using the demo's own tick rate.

- The avenged death must have been caused by the player the avenger just killed.
- Each death is traded at most once; each revenge kill claims the **earliest** qualifying
  death; ties break on `src_idx`.
- World deaths and suicides are untradeable — there is nobody to avenge them on.
- **A player can trade their own death.** A grenade thrown before dying can kill the
  thrower's killer moments later, which restores the man advantage exactly as a
  teammate's revenge would. The reference demo contains one (darkness01 dies at tick
  18107; their grenade kills the killer at 18182).

Our trade flags match the parser's own `is_trade` / `victim_traded` columns **row for
row** on the reference demo — all 11 traded deaths and 11 trade kills.

## KAST

The percentage of scored rounds in which the player got a **K**ill, an **A**ssist,
**S**urvived, or had their death **T**raded.

The subtle part is survival. A player who was not in a round produces no death row, so a
naive "no death means survived" would hand them KAST credit for every round they sat out.
**Survival therefore requires presence**: the player must be on that round's roster, which
is reconstructed from a state sample at each round's freeze end.

## Clutches

A clutch begins the first moment a player becomes the **last survivor** on their side with
at least one enemy alive.

- The opponent count is fixed when the clutch starts — killing opponents afterwards does
  not turn a 1v3 into a 1v1.
- A side that fielded one player for the whole round never *becomes* the last survivor and
  does not register a clutch.
- Dying on the same tick as the last teammate is not a clutch: they were never alone.

## Utility

| Metric | Definition |
|---|---|
| `flashes_thrown` | Flashbangs thrown, taken from weapon-fire rows. |
| `enemies_flashed` | Times an enemy was blinded by this player. Self-flashes and team-flashes are excluded — both occur in real demos. |
| `flash_duration_dealt` | Total seconds of blindness inflicted on enemies. |

Thrown grenades come from **weapon-fire rows, not the grenade trajectory table**. The
trajectory table samples each projectile on every airborne tick (6 682 rows for 63 actual
grenades in the reference demo) *and* its thrower column is null for every row in that
demo — so counting it would both overstate usage and attribute nothing to anyone.

## Sides, teams and halftime

A player's **side** flips at halftime; their **team** does not. No demo states team
membership, so it is reconstructed:

1. Per-round sides come from a player-state sample at each round's freeze end. This is
   the only signal that reports a player who was present but produced no events, and it
   simultaneously yields the `present_at_freeze` flag KAST needs.
2. Players seen on the same side in some round are same-team; players on opposite sides
   are opposite-team. Union-find the same-team relation, then verify the result is
   two-colourable against the opposite-team relation. Team A is the component containing
   round 1's CT side.
3. A genuine mid-match team change breaks two-colourability. That case falls back to
   anchoring on round 1 and emits a visible anomaly rather than producing nonsense.

Halftime and overtime are derived from **where `team_ct` actually flips**, not from
convars — `mp_maxrounds` holds a final-state value that can be changed mid-match. The
convar is read only to cross-check, and a disagreement becomes an anomaly.

## No rating

There is deliberately **no HLTV Rating column**. HLTV Rating 2.0 is an unpublished,
proprietary formula; approximating it from K/D and labelling the result "HLTV Rating"
would be misleading. `GET /api/metrics` returns this as an explicit `omitted` entry so the
absence reads as a decision rather than an oversight. A rating will only be added if an
actual documented formula is implemented and stated with its version.

## Known limitations

- **Kills and damage use different weapon vocabularies.** CS2 reports damage under a base
  weapon class and kills under the specific variant: the R8 Revolver's damage appears as
  `deagle` while its kills appear as `revolver`, and likewise `m4a1`/`m4a1_silencer`,
  `hkp2000`/`usp_silencer`, `knife`/`knife_t`. The event table shows what the demo said.
  No statistic depends on this, because utility damage matches on grenade names, which are
  consistent across both tables.
- **Deaths include self-inflicted ones**, so a scoreboard that omits them (csstats.gg does)
  can read one lower.
- **`enemies_flashed`** may read slightly higher than sites that apply a minimum blind
  duration. The reference demo differs by one.
- **Match date is unknown.** A demo header carries no wall-clock date, so the UI shows
  `uploaded_at` and never invents a "played at".
- **Tick rate can be assumed.** When a demo omits playback timing the parser falls back to
  64, which would skew the tick-expressed trade window. The provenance is recorded as
  `tick_rate_source` and surfaced in the UI.
- **The radar transform ignores `rotate` and `zoom`.** A few maps (de_dust2, cs_italy,
  ar_baggage) carry non-zero values inherited from the old radar metadata format. The
  reference plotting implementation ignores them and uses `pos_x`/`pos_y`/`scale` alone,
  and its output is known-good, so this build does the same rather than apply a transform
  it has never verified. Verified visually on de_mirage, whose values are the identity.
