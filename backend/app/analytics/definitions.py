"""The canonical definition of every metric, served over the API.

This registry is the single source of truth for what each number means. It drives the
tooltips in the UI and the metrics table in the documentation, and a test asserts that
every field on the computed player statistics has an entry here — so a metric can never
quietly appear in the product without a definition attached to it.

Two conventions are applied throughout and called out per metric:

* **Nullable means unknown.** A metric whose denominator is zero, or whose source
  dataset the demo did not contain, is ``None`` — never ``0``. Zero is a real value and
  reserving it for "we don't know" would misrepresent the match.
* **Denominators are stated.** Rate metrics differ between sites mainly in what they
  divide by, so each one names its denominator explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MetricFormat(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    PERCENT = "percent"
    RATIO = "ratio"


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """What a metric is, how it is computed, and how to render it."""

    key: str
    label: str
    short_label: str
    description: str
    fmt: MetricFormat = MetricFormat.INTEGER
    denominator: str | None = None
    nullable: bool = False
    higher_is_better: bool = True
    caveat: str | None = None
    source_datasets: tuple[str, ...] = ()
    default_visible: bool = True


_D = MetricDefinition
_F = MetricFormat

PLAYER_METRICS: tuple[MetricDefinition, ...] = (
    _D(
        key="rounds_present",
        label="Rounds present",
        short_label="RNDS",
        description=(
            "Scored rounds the player was present for at freeze time. Shown for "
            "transparency: it is not the denominator of ADR or KAST."
        ),
        source_datasets=("rounds",),
        default_visible=False,
    ),
    _D(
        key="kills",
        label="Kills",
        short_label="K",
        description=(
            "Enemy kills. Suicides, world deaths and team kills are excluded and counted "
            "separately."
        ),
        source_datasets=("kills",),
    ),
    _D(
        key="deaths",
        label="Deaths",
        short_label="D",
        description=(
            "Every death, including suicides and world deaths. Some scoreboards omit "
            "self-inflicted deaths, so this can read one higher than them."
        ),
        higher_is_better=False,
        source_datasets=("kills",),
    ),
    _D(
        key="assists",
        label="Assists",
        short_label="A",
        description=(
            "Kill assists credited by the game, excluding flash assists, which are "
            "reported separately."
        ),
        source_datasets=("kills",),
    ),
    _D(
        key="flash_assists",
        label="Flash assists",
        short_label="FA",
        description="Assists where the player's flashbang set up the kill.",
        source_datasets=("kills",),
        default_visible=False,
    ),
    _D(
        key="kd",
        label="K/D ratio",
        short_label="K/D",
        description="Kills divided by deaths.",
        fmt=_F.RATIO,
        denominator="deaths",
        nullable=True,
        caveat="Undefined when the player has no deaths; shown as a dash rather than as 0.",
        source_datasets=("kills",),
    ),
    _D(
        key="kpr",
        label="Kills per round",
        short_label="KPR",
        description="Kills divided by the match's scored round count.",
        fmt=_F.DECIMAL,
        denominator="scored rounds in the match",
        nullable=True,
        source_datasets=("kills", "rounds"),
    ),
    _D(
        key="adr",
        label="Average damage per round",
        short_label="ADR",
        description=(
            "Enemy damage per scored round. Each hit is capped at the victim's remaining "
            "health, because demos report raw damage that can far exceed it (up to 199 "
            "against a 100 HP target in our reference demo). Team, self and world damage "
            "are excluded."
        ),
        fmt=_F.DECIMAL,
        denominator="scored rounds in the match",
        nullable=True,
        caveat=(
            "Damage dealt after a round is decided is included, matching common practice; "
            "some sites exclude it, which can account for a few points of difference."
        ),
        source_datasets=("damages", "rounds"),
    ),
    _D(
        key="headshot_kills",
        label="Headshot kills",
        short_label="HSK",
        description="Kills whose fatal hit was to the head.",
        source_datasets=("kills",),
        default_visible=False,
    ),
    _D(
        key="headshot_pct",
        label="Headshot percentage",
        short_label="HS%",
        description=(
            "Headshot kills as a share of kills. The denominator is kills, not shots or "
            "hits — a player with 1 of 2 kills to the head reads 50%."
        ),
        fmt=_F.PERCENT,
        denominator="kills",
        nullable=True,
        caveat="Undefined with no kills; shown as a dash rather than as 0%.",
        source_datasets=("kills",),
    ),
    _D(
        key="kast",
        label="KAST",
        short_label="KAST",
        description=(
            "Share of scored rounds in which the player got a Kill, an Assist, Survived, "
            "or had their death Traded. Survival requires being on that round's roster, so "
            "rounds a player sat out never count as survived."
        ),
        fmt=_F.PERCENT,
        denominator="scored rounds in the match",
        nullable=True,
        source_datasets=("kills", "rounds"),
    ),
    _D(
        key="opening_kills",
        label="Opening kills",
        short_label="OK",
        description="First enemy kill of a round. Suicides opening a round are skipped.",
        source_datasets=("kills",),
    ),
    _D(
        key="opening_deaths",
        label="Opening deaths",
        short_label="OD",
        description="Victim of the first enemy kill of a round.",
        higher_is_better=False,
        source_datasets=("kills",),
    ),
    _D(
        key="traded_deaths",
        label="Traded deaths",
        short_label="TD",
        description=(
            "Deaths avenged by a teammate within 5.25 seconds. Each death can be traded once."
        ),
        source_datasets=("kills",),
    ),
    _D(
        key="trade_kills",
        label="Trade kills",
        short_label="TK",
        description="Kills that avenged a teammate's death within 5.25 seconds.",
        source_datasets=("kills",),
    ),
    _D(
        key="damage_total",
        label="Total damage",
        short_label="DMG",
        description="Capped enemy damage over the match — the numerator of ADR.",
        nullable=True,
        source_datasets=("damages",),
        default_visible=False,
    ),
    _D(
        key="utility_damage",
        label="Utility damage",
        short_label="UD",
        description=(
            "Capped enemy damage from HE grenades and fire (molotov / incendiary), using "
            "the same capping rule as ADR."
        ),
        nullable=True,
        source_datasets=("damages",),
    ),
    _D(
        key="flashes_thrown",
        label="Flashes thrown",
        short_label="FT",
        description="Flashbangs the player threw.",
        nullable=True,
        caveat="Unknown when the demo does not attribute thrown grenades to a player.",
        source_datasets=("shots",),
        default_visible=False,
    ),
    _D(
        key="enemies_flashed",
        label="Enemies flashed",
        short_label="EF",
        description=(
            "Times an enemy was blinded by this player's flashbang. Self-flashes and "
            "team-flashes are excluded; both occur in real demos."
        ),
        nullable=True,
        caveat=(
            "Unknown when the demo omits flash events. Sites that apply a minimum blind "
            "duration will report slightly lower numbers."
        ),
        source_datasets=("blinds",),
    ),
    _D(
        key="flash_duration_dealt",
        label="Enemy blind time",
        short_label="BLIND",
        description="Total seconds of blindness inflicted on enemies.",
        fmt=_F.DECIMAL,
        nullable=True,
        source_datasets=("blinds",),
        default_visible=False,
    ),
    _D(
        key="clutches_played",
        label="Clutches played",
        short_label="CL",
        description=(
            "Rounds in which the player became the last survivor on their side with at "
            "least one enemy alive. A side that fielded one player all round does not count."
        ),
        source_datasets=("kills", "rounds"),
        default_visible=False,
    ),
    _D(
        key="clutches_won",
        label="Clutches won",
        short_label="CLW",
        description="Clutch situations whose round the player's side went on to win.",
        source_datasets=("kills", "rounds"),
        default_visible=False,
    ),
    _D(
        key="team_kills",
        label="Team kills",
        short_label="TmK",
        description="Kills on a teammate. Never counted as kills.",
        higher_is_better=False,
        source_datasets=("kills",),
        default_visible=False,
    ),
    _D(
        key="self_kills",
        label="Self kills",
        short_label="SK",
        description="Suicides, fall damage and other world deaths.",
        higher_is_better=False,
        source_datasets=("kills",),
        default_visible=False,
    ),
    *(
        _D(
            key=f"multikill_{n}k",
            label=f"{n}K rounds",
            short_label=f"{n}K",
            description=f"Rounds with exactly {n} kills" + (" or more." if n == 5 else "."),  # noqa: PLR2004
            source_datasets=("kills",),
            default_visible=False,
        )
        for n in (2, 3, 4, 5)
    ),
    *(
        _D(
            key=f"clutch_1v{n}",
            label=f"1v{n} won",
            short_label=f"1v{n}",
            description=f"Clutches won where {n} enemies were alive when the player was "
            "left alone.",
            source_datasets=("kills", "rounds"),
            default_visible=False,
        )
        for n in (1, 2, 3, 4, 5)
    ),
)

PLAYER_METRICS_BY_KEY: dict[str, MetricDefinition] = {m.key: m for m in PLAYER_METRICS}

#: Why there is no rating column. Served over the API so the absence reads as a decision.
OMITTED_METRICS: tuple[dict[str, str], ...] = (
    {
        "key": "hltv_rating",
        "label": "HLTV Rating",
        "reason": (
            "Deliberately omitted. HLTV Rating 2.0 is an unpublished, proprietary formula; "
            "approximating it from K/D and labelling the result 'HLTV Rating' would be "
            "misleading. A rating will only be added if an actual documented formula is "
            "implemented, stated with its version."
        ),
    },
)
