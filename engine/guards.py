"""Grid Gauge — centralised build-time guards (Stage 9).

Every public figure is checked here before it is written. A guard either passes
silently or raises GuardError with a message that names the figure and the breach,
so a corrupt or implausible value FAILS THE BUILD LOUDLY rather than being
published. This is the project's honesty bargain made executable: shares must sum
to ~100%, capacity factors stay in range, counters stay monotonic, the nameplate
denominators stay sane, and dates stay sorted and unique.

These are deliberately small, named, message-bearing predicates rather than bare
`assert`s so the build steps (engine.derived.build, engine.sharecards.build) can
share one vocabulary and a `python -O` run can never strip them. The live verdict's
own guards (engine.grid_engine.sanity_check) predate this module and stay where they
are; the shared numeric checks below are reused there too.

One value that LOOKS wrong but is correct: a NEGATIVE net-import share on an export
year (e.g. 2022). Shares still sum to 100% — the export volume nets off — so
check_shares_sum_100 validates the SUM, never the sign of an individual share. See
engine/NOTES.md §8.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


class GuardError(Exception):
    """A published figure failed a build-time sanity guard. Fatal by design."""


def require(cond: object, msg: str) -> None:
    """Raise GuardError(msg) unless cond is truthy. The one primitive."""
    if not cond:
        raise GuardError(msg)


def check_finite(name: str, value: float) -> None:
    """Reject NaN / ±inf — a divide-by-zero or bad feed leaking into a figure."""
    require(isinstance(value, (int, float)) and math.isfinite(value),
            f"{name} is not a finite number: {value!r}")


# Shares are rounded to 2dp before summing; a handful of groups can drift a few
# hundredths from 100. The guard's job is to catch a GROSS failure (a dropped or
# doubled group), not rounding — so the tolerance is loose in absolute terms but
# far tighter than any real corruption.
SHARES_SUM_TOL_PCT = 0.5


def check_shares_sum_100(name: str, shares: Mapping[str, float],
                         tol_pct: float = SHARES_SUM_TOL_PCT) -> None:
    """Assert a share dict (values in percent) sums to 100 ± tol_pct.

    Individual shares MAY be negative (a net-export year's net_imports); only the
    sum is constrained. Every value must be finite.
    """
    for group, v in shares.items():
        check_finite(f"{name} share[{group}]", v)
    total = sum(shares.values())
    require(abs(total - 100.0) <= tol_pct,
            f"{name}: shares sum to {total:.4f}%, not 100% (±{tol_pct}%) — "
            f"a group is dropped, doubled or corrupt")


def check_counts_monotonic(year: int, observed: int, below_10: int,
                           below_5: int) -> None:
    """Assert the failure counters nest: 0 ≤ below_5 ≤ below_10 ≤ observed."""
    require(observed >= 0 and below_10 >= 0 and below_5 >= 0,
            f"{year}: negative day count (observed={observed}, "
            f"below_10={below_10}, below_5={below_5})")
    require(below_5 <= below_10,
            f"{year}: below_5pct ({below_5}) exceeds below_10pct ({below_10})")
    require(below_10 <= observed,
            f"{year}: below_10pct ({below_10}) exceeds days_observed ({observed})")


# A wind capacity factor on this project is a CONSERVATIVE LOWER BOUND
# (transmission-only output ÷ total installed nameplate), so it cannot physically
# exceed 1.0 — output can never exceed installed capacity. A tiny epsilon absorbs
# float rounding; anything above is a wrong-unit or doubled feed, or a collapsed
# nameplate denominator.
CF_MAX = 1.0
CF_EPS = 1e-6


def check_cf_range(date: str, cf: float) -> None:
    """Assert a daily wind capacity factor sits in [0, 1] (lower-bound basis)."""
    check_finite(f"cf {date}", cf)
    require(-CF_EPS <= cf <= CF_MAX + CF_EPS,
            f"cf {date} out of range: {cf} (expected 0..{CF_MAX})")


def check_dates_sorted_unique(dates: Sequence[str]) -> None:
    """Assert an ISO date sequence is strictly ascending (sorted and unique)."""
    if len(dates) != len(set(dates)):
        raise GuardError("duplicate date in series")
    if list(dates) != sorted(dates):
        raise GuardError("dates not in ascending order")


# Sanity envelope for the installed-capacity denominators. GB wind+solar is tens of
# GW; a wrong-unit feed (MW pasted as GW) lands in the thousands. The window is wide
# enough never to trip on a real DUKES/Energy-Trends refresh, tight enough to catch a
# unit error or a zeroed feed.
NAMEPLATE_MIN_GW = 1.0
NAMEPLATE_MAX_GW = 500.0
NAMEPLATE_RECONCILE_TOL_GW = 0.02


def check_nameplate_sane(nameplate: Mapping[str, float]) -> None:
    """Assert the published nameplate denominators are positive, in-envelope and
    self-reconciling (wind + solar == total, onshore + offshore == wind)."""
    wind = nameplate["wind_gw"]
    solar = nameplate["solar_gw"]
    total = nameplate["wind_plus_solar_gw"]
    for label, gw in (("wind_gw", wind), ("solar_gw", solar),
                      ("wind_plus_solar_gw", total)):
        check_finite(label, gw)
        require(NAMEPLATE_MIN_GW <= gw <= NAMEPLATE_MAX_GW,
                f"nameplate {label} {gw} GW outside sane envelope "
                f"[{NAMEPLATE_MIN_GW}, {NAMEPLATE_MAX_GW}] — wrong unit or zeroed feed")
    require(abs(total - (wind + solar)) <= NAMEPLATE_RECONCILE_TOL_GW,
            f"nameplate does not reconcile: wind_plus_solar_gw {total} != "
            f"wind {wind} + solar {solar}")
    if "wind_onshore_gw" in nameplate and "wind_offshore_gw" in nameplate:
        on, off = nameplate["wind_onshore_gw"], nameplate["wind_offshore_gw"]
        require(abs(wind - (on + off)) <= NAMEPLATE_RECONCILE_TOL_GW,
                f"nameplate wind does not reconcile: wind_gw {wind} != "
                f"onshore {on} + offshore {off}")
