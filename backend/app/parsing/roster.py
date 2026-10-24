"""Per-round rosters, sides and team identity.

Why this module exists: a player's **side** flips at halftime and in overtime, so side
is not an identity. The identity that persists is the **team** (``"A"`` / ``"B"``), and
no CS2 demo states it directly — it has to be reconstructed.

Reconstruction is deliberately not done from combat events. A player who dies early can
produce zero events in a round, and the parser's roster table reports only each player's
*last* observed side, so carrying that backwards is wrong across a swap. Instead the
primary signal is a state sample at every round's freeze end, which yields each
connected player's side *and* whether they were present — the latter being required to
avoid handing absent players free KAST credit for "surviving" rounds they never played.

Team labelling is a two-colouring: players seen on the same side in some round are
same-team, players on opposite sides are opposite-team. Union-find the same-team
relation, then check the result against the opposite-team relation. A genuine mid-match
team change breaks bipartiteness, so that case falls back to anchoring on round 1 and
records an anomaly rather than silently producing nonsense.
"""

from __future__ import annotations

from collections import defaultdict

from app.parsing.model import Anomaly, RosterEntry, Side, Team

# Sides as the parser reports them, mapped to the normalized short form.
_SIDE_ALIASES = {
    "t": "T",
    "terrorist": "T",
    "terrorists": "T",
    "ct": "CT",
    "counter-terrorist": "CT",
    "counter-terrorists": "CT",
    "counterterrorist": "CT",
}

#: A CS2 match has exactly two teams; anything else means reconstruction failed.
EXPECTED_TEAMS = 2

#: Engine team numbers (``m_iTeamNum``).
TEAM_NUM_T = 2
TEAM_NUM_CT = 3


def normalize_side(value: object) -> Side | None:
    """Map any parser spelling of a side to ``"T"`` / ``"CT"``, or ``None`` if unknown."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        if value == TEAM_NUM_T:
            return "T"
        if value == TEAM_NUM_CT:
            return "CT"
        return None
    text = str(value).strip().lower()
    return _SIDE_ALIASES.get(text)  # type: ignore[return-value]


def opposite(side: Side) -> Side:
    return "CT" if side == "T" else "T"


class _UnionFind:
    """Minimal union-find over player keys."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def add(self, key: str) -> None:
        self._parent.setdefault(key, key)

    def find(self, key: str) -> str:
        self.add(key)
        root = key
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression.
        while self._parent[key] != root:
            self._parent[key], key = root, self._parent[key]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb

    def groups(self) -> dict[str, set[str]]:
        out: dict[str, set[str]] = defaultdict(set)
        for key in self._parent:
            out[self.find(key)].add(key)
        return dict(out)


def assign_teams(
    sides_by_round: dict[int, dict[str, Side]],
    anomalies: list[Anomaly],
) -> dict[str, Team]:
    """Label every player ``"A"`` or ``"B"`` from their per-round sides.

    Args:
        sides_by_round: ``{round_num: {player_key: side}}``.
        anomalies: appended to when the relation is not cleanly two-colourable.

    Returns:
        ``{player_key: team}``. Empty if there is nothing to label.
    """
    if not sides_by_round:
        return {}

    union = _UnionFind()
    opposite_pairs: set[tuple[str, str]] = set()

    for sides in sides_by_round.values():
        by_side: dict[Side, list[str]] = {"T": [], "CT": []}
        for key, side in sides.items():
            by_side[side].append(key)
            union.add(key)
        for side_members in by_side.values():
            for other in side_members[1:]:
                union.union(side_members[0], other)
        for t_player in by_side["T"]:
            for ct_player in by_side["CT"]:
                opposite_pairs.add(tuple(sorted((t_player, ct_player))))  # type: ignore[arg-type]

    components = union.groups()
    # Two-colourability: no "opposite" pair may land in the same component.
    conflicts = [pair for pair in opposite_pairs if union.find(pair[0]) == union.find(pair[1])]
    roots = sorted(components)

    if conflicts or len(roots) != EXPECTED_TEAMS:
        anomalies.append(
            Anomaly(
                code="team_assignment_fallback",
                message=(
                    "Team membership could not be derived cleanly (a player appears to have "
                    "changed teams mid-match, or only one team was observed). Teams were "
                    "anchored to the first round instead."
                ),
                context={"components": len(roots), "conflicts": len(conflicts)},
            )
        )
        return _anchor_on_first_round(sides_by_round)

    first_round = min(sides_by_round)
    anchor = next(
        (key for key, side in sides_by_round[first_round].items() if side == "CT"),
        None,
    )
    anchor_root = union.find(anchor) if anchor is not None else roots[0]
    team_of_root: dict[str, Team] = {}
    for root in roots:
        team_of_root[root] = "A" if root == anchor_root else "B"
    return {
        key: team_of_root[union.find(key)] for component in components.values() for key in component
    }


def _anchor_on_first_round(sides_by_round: dict[int, dict[str, Side]]) -> dict[str, Team]:
    """Fallback: team A is whoever started on CT; later players join by majority overlap."""
    first_round = min(sides_by_round)
    teams: dict[str, Team] = {
        key: ("A" if side == "CT" else "B") for key, side in sides_by_round[first_round].items()
    }
    for round_num in sorted(sides_by_round):
        sides = sides_by_round[round_num]
        # Which side each known team is playing this round, by majority.
        votes: dict[Side, dict[Team, int]] = {"T": defaultdict(int), "CT": defaultdict(int)}
        for key, side in sides.items():
            if key in teams:
                votes[side][teams[key]] += 1
        side_team: dict[Side, Team] = {}
        for side in ("T", "CT"):
            if votes[side]:
                side_team[side] = max(votes[side].items(), key=lambda kv: kv[1])[0]
        for key, side in sides.items():
            if key not in teams and side in side_team:
                teams[key] = side_team[side]
    return teams


def ct_team_by_round(
    sides_by_round: dict[int, dict[str, Side]],
    teams: dict[str, Team],
) -> dict[int, Team | None]:
    """Which team played CT in each round, by majority vote of that round's roster."""
    out: dict[int, Team | None] = {}
    for round_num, sides in sides_by_round.items():
        votes: dict[Team, int] = defaultdict(int)
        for key, side in sides.items():
            team = teams.get(key)
            if team is not None and side == "CT":
                votes[team] += 1
        out[round_num] = max(votes.items(), key=lambda kv: kv[1])[0] if votes else None
    # Carry forward through rounds with no roster information at all.
    last: Team | None = None
    for round_num in sorted(out):
        if out[round_num] is None:
            out[round_num] = last
        else:
            last = out[round_num]
    return out


def derive_halves(
    ct_by_round: dict[int, Team | None],
    anomalies: list[Anomaly],
    *,
    convar_maxrounds: int | None = None,
) -> tuple[dict[int, int], int | None, set[int]]:
    """Split rounds into halves from observed side swaps.

    Swaps are read from the data — the round at which ``team_ct`` flips — rather than
    from convars, which hold only final-state values and can be changed mid-match.
    ``mp_maxrounds`` is used to cross-check and to raise an anomaly on disagreement.

    Returns:
        ``(half_index_by_round, regulation_rounds, overtime_round_nums)``.
    """
    rounds = sorted(ct_by_round)
    half_index: dict[int, int] = {}
    swaps: list[int] = []
    current = 0
    previous: Team | None = None
    for round_num in rounds:
        team_ct = ct_by_round[round_num]
        if previous is not None and team_ct is not None and team_ct != previous:
            current += 1
            swaps.append(round_num)
        if team_ct is not None:
            previous = team_ct
        half_index[round_num] = current

    regulation: int | None = None
    if swaps:
        # The first swap happens after the first half, so regulation is twice its length.
        regulation = (swaps[0] - 1) * 2

    overtime: set[int] = set()
    if regulation is not None:
        overtime = {r for r in rounds if r > regulation}

    if convar_maxrounds and regulation and convar_maxrounds != regulation:
        anomalies.append(
            Anomaly(
                code="maxrounds_mismatch",
                message=(
                    f"mp_maxrounds reports {convar_maxrounds} regulation rounds but the "
                    f"observed halftime swap implies {regulation}. The observed value was used."
                ),
                context={"convar": convar_maxrounds, "observed": regulation},
            )
        )
    return half_index, regulation, overtime


def build_roster(
    sides_by_round: dict[int, dict[str, Side]],
    teams: dict[str, Team],
    present: dict[tuple[int, str], bool],
    equipment: dict[tuple[int, str], int | None] | None = None,
) -> list[RosterEntry]:
    """Flatten the reconstructed per-round state into roster rows."""
    equipment = equipment or {}
    entries: list[RosterEntry] = []
    for round_num in sorted(sides_by_round):
        for key, side in sorted(sides_by_round[round_num].items()):
            entries.append(
                RosterEntry(
                    round_num=round_num,
                    player_key=key,
                    side=side,
                    team=teams.get(key),
                    present_at_freeze=present.get((round_num, key), True),
                    equipment_value=equipment.get((round_num, key)),
                )
            )
    return entries
