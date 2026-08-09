---
name: communauto-trip-cost
description: Calculate the cost of a Communauto car-sharing trip in Québec (Montréal or Québec City) — station vehicles or FLEX (free-floating) — for any subscription package, defaulting to Économique Extra when none is given. Use this whenever the user asks about Communauto pricing, wants to compare FLEX vs station-vehicle cost, is deciding whether to extend a rental into a next-day trip vs returning the car and booking a fresh one, or wants to know how much longer they can keep a car before the price goes up (or before it stops going up entirely because they've hit the daily cap). Trigger on mentions of Communauto, auto-partage, car-sharing trip cost in Québec/Montréal, FLEX pricing, or "how much will it cost to keep the car until X".
---

# Communauto trip cost calculator

Communauto's pricing has several moving parts — hourly rate, a daily cap that
the hourly rate stops mattering past, per-km tiers that differ by package, and
a rule where FLEX vehicles are automatically billed at whichever is cheaper
(FLEX per-minute rate vs. the rider's own station-vehicle rate). Doing this
math by hand is error-prone, especially the "when does the price stop
climbing" question, which depends on exactly where you are inside a 24-hour
billing block. Use `scripts/communauto_cost.py` for the arithmetic — it's
been checked against every worked example Communauto itself publishes in the
official tariff PDF, so trust its numbers over a hand calculation.

Read `references/tarifs.md` for the full rate table and things the script
intentionally doesn't model (Tarif Longue distance, minivan/family vehicle
surcharges, damage-waiver options) — mention those in words if they're
relevant to what the user is asking, rather than trying to compute them.

**Rates were last confirmed against a PDF dated 31 janvier 2025.** If a
computed number seems inconsistent with something the user tells you they
were actually charged, or it's been a while, re-fetch
https://montreal.communauto.com/tarifs/ (or the linked grille tarifaire PDF)
and update the constants at the top of `scripts/communauto_cost.py` before
proceeding — don't silently keep using stale numbers.

## Gathering inputs

Default the subscription package to **Économique Extra** if the user doesn't
say otherwise — that's their usual package. Valid package keys for the
script: `liberte`, `liberte_plus`, `economique`, `economique_plus`,
`economique_extra` (aliases `extra`, `plus`, `eco` also work).

You'll generally need: hours (or a start/end time you can convert), km
(estimate is fine if the user doesn't have an exact number — ask if it
meaningfully changes the answer), and whether it's a FLEX vehicle or a
station car. Don't block on a missing km estimate for short local trips —
proceed with a reasonable assumption and say so.

## Three things this skill answers

### 1. What will this trip cost? (`trip-cost`)

```bash
python3 scripts/communauto_cost.py trip-cost --package economique_extra --hours 2.5 --km 35 --flex
```

Drop `--flex` for a station vehicle. This reports the station price, and for
FLEX trips, the FLEX price, the station price used as the comparison
(4-hour minimum applies only on the station side of that comparison, per
Communauto's rule), and `final_price` / `billed_as` showing which one wins.
It also flags when the "aller-retour rapide" fallback (Liberté Plus pricing)
would beat the rider's own Économique-family rate.

### 2. Extend the same rental, or return and book a new one? (`extend-vs-new`)

```bash
python3 scripts/communauto_cost.py extend-vs-new --package economique_extra \
  --day1-hours 6 --day1-km 40 --day2-hours 5 --day2-km 25
```

This is the core of what makes this decision non-obvious: for Liberté and
Liberté Plus, a fresh booking's first day is capped *higher* than an
additional day on an existing rental, so extending is usually cheaper. For
the Économique family and FLEX, the daily cap is flat every day, so
mathematically it often doesn't matter cost-wise whether it's a
continuation or a new booking — the real trade-off there is about
availability and convenience (is a car actually free where you need it
tomorrow?), which is worth naming explicitly rather than implying the math
alone settles it.

If the package is Économique Extra and day 2 is a weekday with ≤10 hours of
use, the script also flags Tarif Travail (22$ flat) as a likely-cheaper
third option — check it against both computed totals and mention it if it
wins, since it can beat extending in cases where the car would otherwise sit
overnight only lightly used.

### 3. How much longer can I keep it before the price moves? (`plateau`)

```bash
python3 scripts/communauto_cost.py plateau --package economique_extra \
  --hours-so-far 5 --km-so-far 30 --start-time 2026-08-09T14:00
```

Use `--flex` if it's a FLEX vehicle. `--threshold` defaults to 5 (dollars) —
override it if the user asks for a different "worth it" amount. This
reports:
- Whether the day's time cost is already capped (past this point, more time
  costs nothing until the 24h mark — only added km would show up).
- If not yet capped: the elapsed-hours point (and clock time, if
  `--start-time` was given) where it *will* cap, and how much longer they
  can keep the car before the running cost rises by the threshold amount.

Include `--start-time` whenever you know when the rental began — clock
times are much easier for the user to act on than "1.9 more hours."

## Presenting results

Lead with the number the user actually asked for, then show the reasoning
briefly (station vs FLEX comparison, or the two day-by-day totals) so it's
clear the number isn't a guess. Round to cents. If a Tarif Travail or
aller-retour-rapide note appears in the JSON, mention it — those are exactly
the kind of "you're overpaying and don't know it" catches this skill exists
to surface. Don't dump the raw JSON on the user; translate it into plain
sentences (in French or English, whichever they're using).