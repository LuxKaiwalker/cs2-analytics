"""Tunable constants with the reasoning behind each value."""

from __future__ import annotations

#: Seconds within which a revenge kill counts as trading a teammate's death.
#: Matches the upstream parser's documented window so our trade flags stay comparable
#: with theirs; expressed in seconds and converted using the demo's own tick rate.
TRADE_WINDOW_S = 5.25

#: Weapon strings that represent grenade damage, as they appear in the *damage* table.
#: Observed in the reference demo: ``hegrenade``, ``inferno``, ``molotov``. CS2 reports
#: fire damage inconsistently (``inferno`` for both molotov and incendiary in some
#: demos), so the set is a superset and unknown strings raise a warning, never a failure.
UTILITY_DAMAGE_WEAPONS = frozenset({"hegrenade", "inferno", "molotov", "incgrenade", "firebomb"})

#: Weapon strings that represent a flashbang throw, in the *throw* table.
FLASH_WEAPONS = frozenset({"flashbang"})

#: Largest clutch bucket reported; 1vN beyond this is clamped into it.
MAX_CLUTCH_OPPONENTS = 5

#: Multi-kill buckets reported (2k..5k).
MIN_MULTIKILL = 2
MAX_MULTIKILL = 5
