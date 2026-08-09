#!/usr/bin/env python3
"""
communauto_cost.py — Communauto (Québec: Montréal/Québec City) trip cost calculator.

Rates last confirmed against https://communauto.com/wp-content/uploads/pdf/qc/grille-tarifaire-qc.pdf
(document dated 31 janvier 2025). See ../references/tarifs.md for the full source table,
caveats, and things this script deliberately doesn't model (Tarif Longue distance, minivan/
family surcharges, damage waiver options, etc).

Three subcommands:

  trip-cost         Cost of a single trip, station or FLEX, for a given package.
  extend-vs-new     Compare keeping the same car into a next-day trip vs returning it
                     and booking a fresh one, in terms of $/marginal hour.
  plateau           Given hours/km used so far, find when the price stops climbing
                     (hits the daily cap) and how much longer you can keep the car
                     for under a given extra-dollar threshold (default $5).

All subcommands print a JSON object to stdout so the calling agent can parse and
explain it in plain language — the numbers here are exact, the prose wrapper is not.

Run with -h on any subcommand for its arguments, e.g.:
    python3 communauto_cost.py trip-cost -h
"""

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# Rate tables
# ---------------------------------------------------------------------------

@dataclass
class Package:
    key: str
    label: str
    hourly: float
    day1_cap: float
    day_add_cap: float  # for packages with a flat daily cap, equal to day1_cap
    km_included: int = 0
    km_tier1_limit: int = 0       # km at which the tier-1 rate stops applying (0 = no tiering)
    km_tier1_rate: float = 0.0
    km_tier2_rate: float = 0.0
    weekend_surcharge_per_hour: float = 0.0
    weekend_surcharge_cap: float = 0.0


PACKAGES = {
    "liberte": Package(
        key="liberte", label="Liberté",
        hourly=13.50, day1_cap=55.0, day_add_cap=50.0,
        km_included=75, km_tier1_limit=0, km_tier1_rate=0.0, km_tier2_rate=0.27,
        weekend_surcharge_per_hour=0.35, weekend_surcharge_cap=3.50,
    ),
    "liberte_plus": Package(
        key="liberte_plus", label="Liberté Plus",
        hourly=6.85, day1_cap=50.0, day_add_cap=35.0,
        km_included=0, km_tier1_limit=50, km_tier1_rate=0.25, km_tier2_rate=0.22,
    ),
    "economique": Package(
        key="economique", label="Économique",
        hourly=3.60, day1_cap=30.0, day_add_cap=30.0,
        km_included=0, km_tier1_limit=50, km_tier1_rate=0.45, km_tier2_rate=0.32,
    ),
    "economique_plus": Package(
        key="economique_plus", label="Économique Plus",
        hourly=3.20, day1_cap=26.0, day_add_cap=26.0,
        km_included=0, km_tier1_limit=50, km_tier1_rate=0.37, km_tier2_rate=0.29,
    ),
    "economique_extra": Package(
        key="economique_extra", label="Économique Extra",
        hourly=2.90, day1_cap=23.0, day_add_cap=23.0,
        km_included=0, km_tier1_limit=0, km_tier1_rate=0.0, km_tier2_rate=0.29,
    ),
}

DEFAULT_PACKAGE = "economique_extra"

FLEX_PER_MINUTE = 0.41
FLEX_HOURLY_EQUIV = 13.50
FLEX_DAY_CAP = 50.0
FLEX_KM_INCLUDED = 75
FLEX_KM_RATE = 0.27

TARIF_TRAVAIL_DAILY = 22.0
TARIF_TRAVAIL_KM_INCLUDED = 40
TARIF_TRAVAIL_KM_RATE = 0.32
TARIF_TRAVAIL_MAX_HOURS = 10


def resolve_package(key: str) -> Package:
    key = key.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "extra": "economique_extra",
        "eco_extra": "economique_extra",
        "econimique_extra": "economique_extra",
        "plus": "economique_plus",
        "eco_plus": "economique_plus",
        "eco": "economique",
        "liberte+": "liberte_plus",
        "libertyplus": "liberte_plus",
    }
    key = aliases.get(key, key)
    if key not in PACKAGES:
        raise ValueError(
            f"Unknown package '{key}'. Valid: {', '.join(PACKAGES)} "
            f"(or aliases: extra, plus, eco, liberte+)"
        )
    return PACKAGES[key]


# ---------------------------------------------------------------------------
# Km cost
# ---------------------------------------------------------------------------

def km_cost(pkg: Package, km: float) -> float:
    """Km cost under a given station package's own rate schedule."""
    if km <= 0:
        return 0.0
    billable_km = max(0.0, km - pkg.km_included)
    if billable_km <= 0:
        return 0.0
    if pkg.km_tier1_limit and pkg.km_tier1_limit > 0:
        tier1_km = min(billable_km, pkg.km_tier1_limit)
        tier2_km = max(0.0, billable_km - pkg.km_tier1_limit)
        return round(tier1_km * pkg.km_tier1_rate + tier2_km * pkg.km_tier2_rate, 2)
    return round(billable_km * pkg.km_tier2_rate, 2)


def flex_km_cost(km: float) -> float:
    billable_km = max(0.0, km - FLEX_KM_INCLUDED)
    return round(billable_km * FLEX_KM_RATE, 2)


# ---------------------------------------------------------------------------
# Time cost (station), day-block model
# ---------------------------------------------------------------------------

def station_time_cost(pkg: Package, hours: float, weekend_days: int = 0) -> dict:
    """
    Split `hours` into 24h blocks starting from pickup. Block 1 uses day1_cap,
    subsequent blocks use day_add_cap (equal to day1_cap for flat-rate packages).
    Returns total time cost plus a per-day breakdown.
    Note: this is an approximation of Communauto's real day-boundary logic (which
    is closer to calendar-day / midnight resets in practice); it's exact for
    trips that fit in one day and a good estimate for multi-day trips.
    """
    if hours <= 0:
        return {"total": 0.0, "days": []}

    days = []
    remaining = hours
    day_index = 1
    total = 0.0
    while remaining > 1e-9:
        block_hours = min(remaining, 24.0)
        cap = pkg.day1_cap if day_index == 1 else pkg.day_add_cap
        raw = block_hours * pkg.hourly
        block_cost = min(raw, cap)
        total += block_cost
        days.append({
            "day": day_index,
            "hours": round(block_hours, 2),
            "cap": cap,
            "raw_hourly_cost": round(raw, 2),
            "cost": round(block_cost, 2),
            "capped": raw > cap,
        })
        remaining -= block_hours
        day_index += 1

    # Weekend surcharge (Liberté only, station rate — not applied when the
    # winning price ends up being the FLEX rate).
    surcharge = 0.0
    if pkg.weekend_surcharge_per_hour and weekend_days > 0:
        # crude allocation: surcharge per weekend day, based on that day's hours
        per_day_hours = hours / max(1, len(days))
        per_weekend_day = min(per_day_hours * pkg.weekend_surcharge_per_hour, pkg.weekend_surcharge_cap)
        surcharge = round(per_weekend_day * weekend_days, 2)
        total += surcharge

    return {"total": round(total, 2), "days": days, "weekend_surcharge": surcharge}


def flex_time_cost(hours: float) -> dict:
    """FLEX time cost. Billed per minute at 41c, but each *elapsed clock hour*
    is capped at the 13.50$ hourly-equivalent (confirmed against the PDF's
    worked examples: 15min/20km -> 6.15$, 2h -> 27$, 3h -> 40.50$ -- none of
    which match a naive "total minutes vs total hours" comparison, only an
    hour-by-hour cap). The running total within a 24h block is additionally
    capped at the daily FLEX cap."""
    if hours <= 0:
        return {"total": 0.0, "days": []}
    days = []
    remaining_minutes = hours * 60
    day_index = 1
    total = 0.0
    while remaining_minutes > 1e-9:
        day_minutes = min(remaining_minutes, 24 * 60)
        day_cost = 0.0
        rem = day_minutes
        hour_blocks = 0
        while rem > 1e-9:
            m = min(60.0, rem)
            hour_cost = min(m * FLEX_PER_MINUTE, FLEX_HOURLY_EQUIV)
            if day_cost + hour_cost > FLEX_DAY_CAP:
                hour_cost = max(0.0, FLEX_DAY_CAP - day_cost)
            day_cost += hour_cost
            rem -= m
            hour_blocks += 1
        total += day_cost
        days.append({
            "day": day_index,
            "hours": round(day_minutes / 60, 2),
            "cap": FLEX_DAY_CAP,
            "cost": round(day_cost, 2),
        })
        remaining_minutes -= day_minutes
        day_index += 1
    return {"total": round(total, 2), "days": days}


# ---------------------------------------------------------------------------
# Aller-retour rapide (quick round-trip -> Liberté Plus pricing if cheaper)
# ---------------------------------------------------------------------------

def quick_roundtrip_price(hours: float, km: float) -> float:
    lp = PACKAGES["liberte_plus"]
    return station_time_cost(lp, hours)["total"] + km_cost(lp, km)


# ---------------------------------------------------------------------------
# trip-cost
# ---------------------------------------------------------------------------

def trip_cost(package: str, hours: float, km: float, is_flex: bool,
              weekend_days: int = 0) -> dict:
    pkg = resolve_package(package)

    station = station_time_cost(pkg, hours, weekend_days)
    station_km = km_cost(pkg, km)
    station_total = round(station["total"] + station_km, 2)

    result = {
        "package": pkg.label,
        "vehicle": "FLEX" if is_flex else "station",
        "hours": hours,
        "km": km,
        "station_price": {
            "time_cost": station["total"],
            "km_cost": station_km,
            "total": station_total,
            "breakdown": station,
        },
    }

    # Quick-round-trip check (Liberté Plus fallback), only meaningful for the
    # Économique family which qualifies automatically.
    if pkg.key in ("economique", "economique_plus", "economique_extra"):
        qrt = round(quick_roundtrip_price(hours, km), 2)
        if qrt < station_total:
            result["quick_roundtrip_price"] = qrt
            result["quick_roundtrip_note"] = (
                "Cheaper billed automatically at Liberté Plus rates (aller-retour "
                "rapide) than at your own package's rate."
            )

    if not is_flex:
        best = min(station_total, result.get("quick_roundtrip_price", station_total))
        result["final_price"] = best
        return result

    # FLEX: compare per-minute FLEX price vs station price of the rider's own
    # package, using a 4h minimum ONLY for the station-side of the comparison.
    flex = flex_time_cost(hours)
    flex_km = flex_km_cost(km)
    flex_total = round(flex["total"] + flex_km, 2)

    station_hours_for_comparison = max(hours, 4.0)
    station_cmp = station_time_cost(pkg, station_hours_for_comparison, weekend_days)
    station_cmp_total = round(station_cmp["total"] + station_km, 2)

    result["flex_price"] = {
        "time_cost": flex["total"],
        "km_cost": flex_km,
        "total": flex_total,
        "breakdown": flex,
    }
    result["station_price_for_comparison_4h_min"] = station_cmp_total

    candidates = {
        "flex": flex_total,
        "station_4h_min": station_cmp_total,
    }
    if "quick_roundtrip_price" in result:
        candidates["quick_roundtrip"] = result["quick_roundtrip_price"]

    winner = min(candidates, key=candidates.get)
    result["final_price"] = candidates[winner]
    result["billed_as"] = winner
    return result


# ---------------------------------------------------------------------------
# extend-vs-new
# ---------------------------------------------------------------------------

def extend_vs_new(package: str, day1_hours: float, day1_km: float,
                   day2_hours: float, day2_km: float,
                   day2_is_weekday: bool = True) -> dict:
    """
    Compare two options for a two-day usage pattern:
      A) Extend the same rental across both days (one continuous booking).
      B) Return the car after day 1, book a fresh one for day 2 (two separate
         bookings, each starting its own "day 1").
    Also flags Tarif Travail as a likely-cheaper option when eligible
    (Économique Extra, weekday, <=10 consecutive hours).
    """
    pkg = resolve_package(package)
    total_hours = day1_hours + day2_hours
    total_km = day1_km + day2_km

    extend = station_time_cost(pkg, total_hours)
    extend_total = round(extend["total"] + km_cost(pkg, total_km), 2)

    day1 = station_time_cost(pkg, day1_hours)
    day2 = station_time_cost(pkg, day2_hours)  # each booking restarts at day1_cap
    new_total = round(
        day1["total"] + km_cost(pkg, day1_km) + day2["total"] + km_cost(pkg, day2_km), 2
    )

    result = {
        "package": pkg.label,
        "extend_same_rental": {"total": extend_total, "breakdown": extend},
        "return_and_rebook": {"total": new_total,
                               "day1": day1, "day2": day2,
                               "km_cost": round(km_cost(pkg, day1_km) + km_cost(pkg, day2_km), 2)},
    }

    if extend_total <= new_total:
        result["cheaper_option"] = "extend_same_rental"
        result["savings"] = round(new_total - extend_total, 2)
    else:
        result["cheaper_option"] = "return_and_rebook"
        result["savings"] = round(extend_total - new_total, 2)

    if pkg.key == "economique_extra" and day2_is_weekday and day2_hours <= TARIF_TRAVAIL_MAX_HOURS:
        travail_cost = TARIF_TRAVAIL_DAILY + max(0.0, day2_km - TARIF_TRAVAIL_KM_INCLUDED) * TARIF_TRAVAIL_KM_RATE
        result["tarif_travail_note"] = (
            f"Day 2 alone likely qualifies for Tarif Travail: ~{travail_cost:.2f}$ flat "
            f"(22$ + km beyond 40), applied automatically by Communauto if cheaper. "
            f"Worth checking against both options above."
        )

    return result


# ---------------------------------------------------------------------------
# plateau
# ---------------------------------------------------------------------------

def plateau(package: str, hours_so_far: float, km_so_far: float, is_flex: bool = False,
            threshold: float = 5.0, start_time: str = None) -> dict:
    """
    Given usage so far, find:
      - the elapsed-hours point at which time-cost hits the current day's cap
        (after which more time costs nothing extra, only added km would)
      - how much longer the car can be kept before the price rises by
        `threshold` dollars (bounded by the plateau point)
    """
    pkg = resolve_package(package)
    hourly = FLEX_HOURLY_EQUIV if is_flex else pkg.hourly

    day_index = int(hours_so_far // 24) + 1
    hours_into_day = hours_so_far - (day_index - 1) * 24

    if is_flex:
        cap = FLEX_DAY_CAP
    else:
        cap = pkg.day1_cap if day_index == 1 else pkg.day_add_cap

    cost_so_far = min(hours_into_day * hourly, cap)
    already_capped = cost_so_far >= cap - 1e-9

    result = {
        "package": "FLEX" if is_flex else pkg.label,
        "hours_so_far": hours_so_far,
        "day_index_of_rental": day_index,
        "hours_into_current_day": round(hours_into_day, 2),
        "time_cost_so_far": round(cost_so_far, 2),
        "day_cap": cap,
        "already_at_plateau": already_capped,
    }

    if already_capped:
        hours_left_in_day = 24 - hours_into_day
        result["plateau_message"] = (
            f"Time cost is already flat at {cap:.2f}$ for this day — you can keep the car "
            f"for up to {hours_left_in_day:.1f} more hour(s) (until this rental's 24h mark) "
            f"with no extra time cost, only additional km would add to the bill."
        )
        result["hours_until_next_day_boundary"] = round(hours_left_in_day, 2)
    else:
        hours_to_cap = cap / hourly
        hours_left_to_plateau = hours_to_cap - hours_into_day
        result["hours_until_plateau"] = round(hours_left_to_plateau, 2)
        result["plateau_message"] = (
            f"Price keeps climbing by {hourly:.2f}$/hour until you hit {hours_to_cap:.2f} total "
            f"hours for this day (i.e. about {hours_left_to_plateau:.2f} more hour(s) from now), "
            f"at which point the day's time cost is capped at {cap:.2f}$ and any further time "
            f"today is free (km still adds up)."
        )
        hours_for_threshold = min(threshold / hourly, hours_left_to_plateau)
        result["hours_until_next_threshold"] = round(hours_for_threshold, 2)
        result["threshold_message"] = (
            f"You can keep the car about {hours_for_threshold:.2f} more hour(s) before the "
            f"price goes up by {threshold:.2f}$ or more."
        )

    if start_time:
        try:
            start_dt = datetime.fromisoformat(start_time)
            now_point = start_dt + timedelta(hours=hours_so_far)
            result["current_clock_time"] = now_point.isoformat()
            if already_capped:
                boundary = start_dt + timedelta(hours=(day_index) * 24)
                result["plateau_clock_time"] = boundary.isoformat()
            else:
                plateau_point = now_point + timedelta(hours=result["hours_until_plateau"])
                threshold_point = now_point + timedelta(hours=result["hours_until_next_threshold"])
                result["plateau_clock_time"] = plateau_point.isoformat()
                result["next_threshold_clock_time"] = threshold_point.isoformat()
        except ValueError:
            result["start_time_parse_error"] = (
                "Couldn't parse start_time; expected ISO format like 2026-08-09T17:00"
            )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Communauto Québec trip cost calculator")
    sub = parser.add_subparsers(dest="command", required=True)

    p1 = sub.add_parser("trip-cost", help="Cost of a single trip")
    p1.add_argument("--package", default=DEFAULT_PACKAGE,
                     help=f"Subscription package (default: {DEFAULT_PACKAGE}). "
                          f"One of: {', '.join(PACKAGES)}")
    p1.add_argument("--hours", type=float, required=True)
    p1.add_argument("--km", type=float, required=True)
    p1.add_argument("--flex", action="store_true", help="Vehicle is a FLEX (free-floating) car")
    p1.add_argument("--weekend-days", type=int, default=0,
                     help="Number of weekend days covered (Liberté surcharge only)")

    p2 = sub.add_parser("extend-vs-new",
                         help="Compare extending a rental vs returning + rebooking next day")
    p2.add_argument("--package", default=DEFAULT_PACKAGE)
    p2.add_argument("--day1-hours", type=float, required=True)
    p2.add_argument("--day1-km", type=float, required=True)
    p2.add_argument("--day2-hours", type=float, required=True)
    p2.add_argument("--day2-km", type=float, required=True)
    p2.add_argument("--day2-weekend", action="store_true",
                     help="Day 2 falls on a Saturday/Sunday (disqualifies Tarif Travail)")

    p3 = sub.add_parser("plateau",
                         help="Find when the price stops climbing / next $ threshold")
    p3.add_argument("--package", default=DEFAULT_PACKAGE)
    p3.add_argument("--hours-so-far", type=float, required=True)
    p3.add_argument("--km-so-far", type=float, default=0.0)
    p3.add_argument("--flex", action="store_true")
    p3.add_argument("--threshold", type=float, default=5.0)
    p3.add_argument("--start-time", default=None,
                     help="ISO datetime the rental started, e.g. 2026-08-09T17:00")

    args = parser.parse_args()

    if args.command == "trip-cost":
        out = trip_cost(args.package, args.hours, args.km, args.flex, args.weekend_days)
    elif args.command == "extend-vs-new":
        out = extend_vs_new(args.package, args.day1_hours, args.day1_km,
                             args.day2_hours, args.day2_km,
                             day2_is_weekday=not args.day2_weekend)
    elif args.command == "plateau":
        out = plateau(args.package, args.hours_so_far, args.km_so_far, args.flex,
                       args.threshold, args.start_time)
    else:
        parser.error("unknown command")
        return

    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
