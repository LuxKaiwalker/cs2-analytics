"""Trade detection.

A **trade** is a kill that avenges a teammate who died moments earlier. It matters twice
over: it is a KAST component, and "did my death get traded?" is one of the clearest
behavioural signals in the game — so this is computed here rather than taken from the
parser, both to keep the analytics parser-independent and because the result is
cross-checked against the parser's own flags in the integration test.

Rules, each of which has a test:

* The revenge kill must land within :data:`TRADE_WINDOW_S` of the death, measured in
  ticks using the demo's own tick rate.
* The avenged death must have been caused by the player the avenger just killed.
* Each death is traded at most once, and each revenge kill claims the **earliest**
  qualifying death.
* A player **can** trade their own death. This is not a quirk: a grenade thrown before
  dying can kill the thrower's killer moments later, which restores the man advantage
  exactly as a teammate's revenge kill would. The reference demo contains one (darkness01
  dies at tick 18107 and their grenade kills the killer at 18182), and excluding it
  would put us one trade short of upstream for no conceptual gain.
* World deaths and suicides are untradeable — there is no killer to avenge them on.
* Ordering and ties use ``(tick, src_idx)``, so the outcome is deterministic even when
  several kills land on the same tick.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.analytics.constants import TRADE_WINDOW_S
from app.parsing.model import KillNorm


@dataclass(frozen=True, slots=True)
class TradeResult:
    """Which kills were trades, and whose deaths they avenged."""

    trade_kill_indices: frozenset[int]
    """Indices into the kill list of kills that *are* trades."""

    traded_death_indices: frozenset[int]
    """Indices of kills whose victim *was* traded."""

    def traded_deaths_by_player(self, kills: list[KillNorm]) -> dict[str, int]:
        """How many of each player's deaths were avenged."""
        counts: dict[str, int] = defaultdict(int)
        for index in self.traded_death_indices:
            counts[kills[index].victim.key] += 1
        return dict(counts)

    def trade_kills_by_player(self, kills: list[KillNorm]) -> dict[str, int]:
        """How many trade kills each player made."""
        counts: dict[str, int] = defaultdict(int)
        for index in self.trade_kill_indices:
            attacker = kills[index].attacker
            if attacker is not None:
                counts[attacker.key] += 1
        return dict(counts)


def detect_trades(kills: list[KillNorm], tick_rate: float) -> TradeResult:
    """Identify trade kills and traded deaths across a whole match."""
    window_ticks = TRADE_WINDOW_S * max(tick_rate, 1.0)

    by_round: dict[int, list[int]] = defaultdict(list)
    for index, kill in enumerate(kills):
        by_round[kill.round_num].append(index)

    trade_kills: set[int] = set()
    traded_deaths: set[int] = set()

    for indices in by_round.values():
        indices.sort(key=lambda i: (kills[i].tick, kills[i].src_idx))
        traded: set[int] = set()
        for position, kill_index in enumerate(indices):
            kill = kills[kill_index]
            if not kill.is_valid_kill or kill.attacker is None:
                continue
            avenger = kill.attacker.key
            # The player just killed is the one whose earlier kills we can avenge.
            slain = kill.victim.key
            if avenger == slain:
                continue  # a suicide avenges nothing
            candidates = [
                death_index
                for death_index in indices[:position]
                if death_index not in traded
                and _qualifies(kills[death_index], kill, slain, window_ticks)
            ]
            if not candidates:
                continue
            chosen = min(candidates, key=lambda i: (kills[i].tick, kills[i].src_idx))
            traded.add(chosen)
            traded_deaths.add(chosen)
            trade_kills.add(kill_index)

    return TradeResult(frozenset(trade_kills), frozenset(traded_deaths))


def _qualifies(
    death: KillNorm,
    revenge: KillNorm,
    slain: str,
    window_ticks: float,
) -> bool:
    """Whether ``death`` is a teammate death that ``revenge`` avenges."""
    if death.attacker is None or death.is_self_kill:
        return False  # nothing to avenge a world death on
    if death.attacker.key != slain:
        return False  # the avenged death must have been caused by the player just killed
    if death.victim_side is None or revenge.attacker_side is None:
        return False
    if death.victim_side != revenge.attacker_side:
        return False  # the victim must be the avenger's teammate
    return revenge.tick - death.tick <= window_ticks
