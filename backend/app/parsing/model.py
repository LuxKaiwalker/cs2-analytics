"""The normalized match model — parser-independent by construction.

Everything downstream (analytics, persistence, the API) reads these dataclasses and
never a parser's native output. Replacing the parser means writing one new module
that produces a :class:`NormalizedMatch`; nothing else changes.

Design notes that are load-bearing rather than stylistic:

* **Players are keyed by** :attr:`PlayerRef.key`, never by Steam ID. Bots and the
  SourceTV recorder all report Steam ID 0, so keying on Steam ID would collapse them
  into a single player and corrupt the scoreboard.
* **Every combat row carries** :attr:`src_idx`, the parser's original row index. Within
  one source table, row order *is* demo message order, which makes it the only correct
  tiebreaker for same-tick events. The real demo contains 25 same-tick damage groups, so
  this is not hypothetical.
* **Sides are normalized to** ``"T"`` / ``"CT"``. A player's side changes at halftime;
  the persistent identities are ``key`` (player) and ``team`` (``"A"`` / ``"B"``).
* **Missing data is represented, not defaulted.** :class:`Availability` records whether
  each source dataset was present, empty or unsupported, so a metric with no source can
  render as "unknown" instead of zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

Side = Literal["T", "CT"]
Team = Literal["A", "B"]

#: Normalized schema version. Bumping it invalidates persisted analytics
#: (matches are re-ingested rather than migrated — the DB is a derived cache).
ANALYTICS_VERSION = 1


class DatasetState(StrEnum):
    """Whether a source dataset yielded usable data."""

    AVAILABLE = "available"
    """Present with rows."""

    EMPTY = "empty"
    """Present in the parser's API but contained no rows for this demo."""

    PARTIAL = "partial"
    """Present with rows, but a field this app needs is missing or null throughout."""

    UNSUPPORTED = "unsupported"
    """The parser could not produce it at all (raised, or the demo variant lacks it)."""


@dataclass(frozen=True, slots=True)
class DatasetAvailability:
    """Provenance for one source dataset."""

    state: DatasetState
    row_count: int = 0
    reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.state in (DatasetState.AVAILABLE, DatasetState.PARTIAL)


Availability = dict[str, DatasetAvailability]


@dataclass(frozen=True, slots=True)
class Anomaly:
    """Something unexpected but non-fatal, surfaced to the user rather than hidden."""

    code: str
    message: str
    context: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PlayerRef:
    """A player identity that is stable across a match.

    ``key`` is the join key everywhere in the application. Steam ID is retained for
    display and for future cross-match profiles, but is **not** the identity: bots and
    the demo recorder share Steam ID 0.
    """

    key: str
    name: str
    steamid: int | None = None
    is_bot: bool = False

    @classmethod
    def create(cls, steamid: int | None, name: str) -> PlayerRef:
        """Build a reference, deriving a safe key for bots and unidentified players."""
        clean = (name or "").strip() or "unknown"
        if steamid is None or steamid == 0:
            return cls(key=f"bot:{clean}", name=clean, steamid=None, is_bot=True)
        return cls(key=str(steamid), name=clean, steamid=steamid, is_bot=False)


@dataclass(frozen=True, slots=True)
class MatchMeta:
    """Match-level facts. ``None`` means "the demo did not tell us", never zero."""

    map_name: str | None
    tick_rate: float
    tick_rate_source: Literal["header", "fallback"]
    demo_version_name: str | None = None
    server_name: str | None = None
    build_num: int | None = None
    playback_ticks: int | None = None
    playback_frames: int | None = None
    playback_time: float | None = None
    parser_name: str = "awpy"
    parser_version: str = "unknown"
    analytics_version: int = ANALYTICS_VERSION
    roster_source: str = "unknown"
    regulation_rounds: int | None = None
    """Rounds per regulation match, inferred from the observed halftime swap."""
    has_overtime: bool = False
    team_a_name: str | None = None
    team_b_name: str | None = None

    @property
    def match_duration_s(self) -> float | None:
        """Recording length in seconds, or ``None`` when the demo omits playback timing."""
        return self.playback_time


@dataclass(frozen=True, slots=True)
class RoundNorm:
    """One round. Ticks are absolute demo ticks; ``None`` where unobserved."""

    round_num: int
    start_tick: int
    end_tick: int
    freeze_end_tick: int | None = None
    official_end_tick: int | None = None
    winner_side: Side | None = None
    reason_name: str | None = None
    is_knife_round: bool = False
    half_index: int = 0
    is_overtime: bool = False
    team_ct: Team | None = None
    """Which team played CT this round — the key to surviving halftime and overtime."""
    winner_team: Team | None = None
    ct_equipment_value: int | None = None
    t_equipment_value: int | None = None
    ct_buy_type: str | None = None
    t_buy_type: str | None = None

    @property
    def play_start_tick(self) -> int:
        """When play actually began: freeze end if known, else round start."""
        return self.freeze_end_tick if self.freeze_end_tick is not None else self.start_tick


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """A player's participation in one round."""

    round_num: int
    player_key: str
    side: Side
    team: Team | None = None
    present_at_freeze: bool = True
    equipment_value: int | None = None


@dataclass(frozen=True, slots=True)
class KillNorm:
    """One death event, with its attacker and assister resolved.

    ``attacker`` is ``None`` for pure world deaths. When attacker and victim are the
    same player the kill is a suicide — :attr:`is_self_kill` is checked **before**
    :attr:`is_team_kill`, because a suicide trivially shares the victim's side and
    would otherwise be miscounted as a team kill.
    """

    src_idx: int
    tick: int
    round_num: int
    victim: PlayerRef
    victim_side: Side | None
    attacker: PlayerRef | None = None
    attacker_side: Side | None = None
    assister: PlayerRef | None = None
    assister_side: Side | None = None
    assist_is_flash: bool = False
    weapon: str | None = None
    headshot: bool = False
    hitgroup_name: str | None = None
    noscope: bool = False
    penetrated: int | None = None
    thru_smoke: bool = False
    is_post_round: bool = False
    attacker_x: float | None = None
    attacker_y: float | None = None
    attacker_z: float | None = None
    victim_x: float | None = None
    victim_y: float | None = None
    victim_z: float | None = None

    @property
    def is_self_kill(self) -> bool:
        """Suicide, fall damage or other world death."""
        return self.attacker is None or self.attacker.key == self.victim.key

    @property
    def is_team_kill(self) -> bool:
        """A kill on a teammate — never a suicide."""
        if self.is_self_kill:
            return False
        return self.attacker_side is not None and self.attacker_side == self.victim_side

    @property
    def is_valid_kill(self) -> bool:
        """An enemy kill: the only kind that counts toward ``kills``."""
        return not self.is_self_kill and not self.is_team_kill and self.attacker is not None

    @property
    def is_valid_assist(self) -> bool:
        """Whether the recorded assister should be credited.

        Deliberately **not** gated on :attr:`is_valid_kill`. A player who takes enemy
        damage and then falls to their death is recorded as a suicide, but the enemy the
        game credited still contributed to it — and real demos contain exactly that. The
        requirement is that the assister is an enemy of the victim, and is neither the
        victim nor the player who got the kill.
        """
        if self.assister is None:
            return False
        if self.assister.key == self.victim.key:
            return False
        if self.attacker is not None and self.assister.key == self.attacker.key:
            return False
        return (
            self.assister_side is not None
            and self.victim_side is not None
            and self.assister_side != self.victim_side
        )


@dataclass(frozen=True, slots=True)
class DamageNorm:
    """One damage event.

    :attr:`dmg_health_raw` is what the demo reported and routinely exceeds the victim's
    remaining health (observed up to 199). :attr:`dmg_health_effective` is the value
    after sequential capping and is the only one that may be summed.
    """

    src_idx: int
    tick: int
    round_num: int
    victim: PlayerRef
    victim_side: Side | None
    dmg_health_raw: int
    dmg_health_effective: int
    attacker: PlayerRef | None = None
    attacker_side: Side | None = None
    dmg_armor: int = 0
    weapon: str | None = None
    hitgroup_name: str | None = None
    health_post: int | None = None
    is_post_round: bool = False
    attacker_x: float | None = None
    attacker_y: float | None = None
    attacker_z: float | None = None
    victim_x: float | None = None
    victim_y: float | None = None
    victim_z: float | None = None

    @property
    def is_self_damage(self) -> bool:
        return self.attacker is None or self.attacker.key == self.victim.key

    @property
    def is_team_damage(self) -> bool:
        if self.is_self_damage:
            return False
        return self.attacker_side is not None and self.attacker_side == self.victim_side

    @property
    def is_valid_damage(self) -> bool:
        """Damage dealt to an enemy: the only kind that counts toward ADR."""
        return not self.is_self_damage and not self.is_team_damage and self.attacker is not None


@dataclass(frozen=True, slots=True)
class BlindNorm:
    """A player blinded by a flashbang."""

    src_idx: int
    tick: int
    round_num: int
    victim: PlayerRef
    victim_side: Side | None
    duration: float
    attacker: PlayerRef | None = None
    attacker_side: Side | None = None

    @property
    def is_enemy_flash(self) -> bool:
        """Excludes self-flashes and team-flashes, both of which occur in real demos."""
        if self.attacker is None or self.attacker.key == self.victim.key:
            return False
        return (
            self.attacker_side is not None
            and self.victim_side is not None
            and self.attacker_side != self.victim_side
        )


@dataclass(frozen=True, slots=True)
class UtilityThrowNorm:
    """One thrown grenade, collapsed from the parser's per-tick trajectory rows."""

    src_idx: int
    tick: int
    round_num: int
    thrower: PlayerRef | None
    thrower_side: Side | None
    utility_type: str
    """``flashbang`` | ``he`` | ``smoke`` | ``molotov`` | ``decoy``."""
    x: float | None = None
    y: float | None = None
    z: float | None = None


@dataclass(frozen=True, slots=True)
class ObjectiveNorm:
    """A bomb action: pickup, drop, start_plant, interrupt_plant, finish_plant, defuse."""

    src_idx: int
    tick: int
    round_num: int
    event: str
    player: PlayerRef | None = None
    player_side: Side | None = None
    bombsite: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None


@dataclass(slots=True)
class NormalizedMatch:
    """A complete, parser-independent match.

    Row counts are small — a competitive match is a few thousand events — so plain
    Python lists are used deliberately. The sequential algorithms that compute the
    statistics (damage capping, trade detection, round state) are far easier to read
    and unit-test this way, and that is exactly where correctness bugs live.
    """

    meta: MatchMeta
    players: dict[str, PlayerRef]
    rounds: list[RoundNorm]
    roster: list[RosterEntry]
    kills: list[KillNorm]
    damages: list[DamageNorm]
    blinds: list[BlindNorm]
    utility: list[UtilityThrowNorm]
    objectives: list[ObjectiveNorm]
    availability: Availability = field(default_factory=dict)
    anomalies: list[Anomaly] = field(default_factory=list)

    @property
    def scored_rounds(self) -> list[RoundNorm]:
        """Rounds that count toward statistics: everything but knife rounds."""
        return [r for r in self.rounds if not r.is_knife_round]

    @property
    def round_count(self) -> int:
        """The denominator for ADR and KAST."""
        return len(self.scored_rounds)

    def team_score(self, team: Team) -> int:
        return sum(1 for r in self.scored_rounds if r.winner_team == team)

    def is_available(self, dataset: str) -> bool:
        """Whether ``dataset`` yielded data we can derive metrics from."""
        entry = self.availability.get(dataset)
        return entry is not None and entry.usable


@runtime_checkable
class DemoParser(Protocol):
    """The replaceable parser seam.

    Implementations own all third-party imports and must raise
    :class:`app.parsing.errors.DemoParseError` for anything the user should see.
    """

    name: str

    def version(self) -> str:
        """Version string of the underlying parser, recorded on the match."""
        ...

    def parse(self, path: str) -> NormalizedMatch:
        """Parse a demo file into the normalized model."""
        ...
