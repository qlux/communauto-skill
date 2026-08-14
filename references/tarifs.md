# Communauto Québec — grille tarifaire (source data)

Source: https://montreal.communauto.com/tarifs/ and the linked PDF
https://communauto.com/wp-content/uploads/pdf/qc/grille-tarifaire-qc.pdf
(applies to Montréal and Québec City — same province-wide grid).
**Station-vehicle table below updated 2026-08-11 from pricing screenshots the user
provided directly (their own account view), superseding the 31 janvier 2025 PDF grid
previously used.** FLEX section further down was NOT part of that update and still
reflects the older PDF — reconfirm if a FLEX number looks off.
Communauto changes these numbers from time to time — if a computed price looks
off, or the user mentions a specific number that disagrees with this file, prefer
re-fetching https://montreal.communauto.com/tarifs/ or the PDF above (or asking the
user for a fresh screenshot of their plan page) and update `scripts/communauto_cost.py`
accordingly rather than trusting stale numbers.

Gas and maintenance are always included in the rates below; taxes are extra.

## Forfaits (subscription packages) — station vehicles

| Forfait | Frais d'abonnement | $/heure | Max 1er jour | Max jour additionnel | Km |
|---|---|---|---|---|---|
| Liberté | Gratuit | 14,25 $ | 55 $ | 50 $ | 75 km inclus/trajet, 31¢/km après |
| Liberté Plus | 45 $/année | 7,05 $ | 50 $ | 35,50 $ | +29¢/km (km 1-50), 26¢/km après 50 |
| Économique | 45 $/année | 3,80 $ | 31,50 $/jour (flat) | — | +49¢/km (km 1-50), 36¢/km après 50 |
| Économique Plus | 12,50 $/mois | 3,30 $ | 26,50 $/jour (flat) | — | +41¢/km (km 1-50), 33¢/km après 50 |
| Économique Extra | 30 $/mois | 3,00 $ | 23 $/jour (flat) | — | +33¢/km (flat, no tiers) |

* All forfaits: add 35¢/heure or 3,50$/jour (whichever lower) on Saturday/Sunday
  — this weekend surcharge does NOT apply when the trip ends up billed at FLEX
  rates. (Confirmed against a real Économique Extra receipt on 2026-08-11 — it's
  not Liberté-exclusive as earlier notes here assumed.)
* Droit d'adhésion remboursable (refundable membership deposit, not a fee): 500$
  individual / 750$ family, for Économique / Économique Plus / Économique Extra.
  Fully refunded after 1 year if you leave (3-month notice required). Not relevant
  to per-trip cost, only mentioned here in case the user asks.

## FLEX (free-floating vehicles)

**Updated 2026-08-11 from the user's own account/plan page:**

- 43¢/minute, capped at the equivalent of 14,25$/heure, capped again at 50$/jour
  (time cost only — km billed separately).
- 75 km included per trip, 31¢/km after 75 km.
- A FLEX trip is **always billed at whichever is lower**: the FLEX price above, or
  the price it would have cost on a station vehicle at the rider's own subscribed
  package rate. This comparison happens regardless of trip duration. If the
  station-price comparison is what ends up being charged, a 4-hour minimum
  duration is used for that calculation (even if the real trip was shorter) — but
  only in that case, not when the FLEX per-minute price wins.
- 30 min free "blocking" time to walk to a spotted vehicle.
- 20 min credit for fueling up (min $20 paid at the pump), on trips ≤ 1h.
- Up to 15 min credit for de-icing/snow removal in winter.

## Tarif Travail (flat workday rate) — Économique Extra holders only

**Updated 2026-08-11 from the user's own account/plan page** (supersedes the older
22$/32¢ figures from the Jan 2025 PDF):

- 24 $/day flat, 40 km included, 36¢/km beyond that.
- Weekdays only (Monday–Friday).
- Max 10 **consecutive** hours of use — if the trip exceeds this, the *entire*
  trip is billed at the normal Économique Extra hourly rate instead (not just
  the excess).
- Midnight–6am doesn't count toward the 10-hour window (one hour more than the
  uncounted window for standard Économique Extra billing), so in practice you
  can take a car at 5pm and return it at 9am the next day (16 real hours) and
  still only pay the 24$ flat rate, as long as actual "counted" usage stays ≤10h.
- Applied automatically by Communauto when it's cheaper — worth flagging to a
  Économique Extra subscriber who's asking about an overnight trip on a weekday,
  since it can beat both "extend the same rental" and "book a new one."
- **Applies to FLEX bookings too, but only on the station-comparison side**:
  if a FLEX trip would otherwise end up billed at the station-equivalent
  price (rather than the raw per-minute FLEX price), Tarif Travail competes
  against that station price the same way it would for a station vehicle.
  It never competes against the FLEX per-minute price directly. Confirmed
  with the user 2026-08-11; `trip-cost --weekday` now models this.

## Tarif Longue distance (long-distance flat rate) — Économique* holders only

Applied automatically when cheaper than the regular per-km rate. Not modeled in
the calculator script (low ROI relative to complexity — flag it in words if the
user mentions long highway trips, > ~150-200 km).

Basse saison (Oct 16 – Jun 14): 40$ 1er jour / 29,95$ jour additionnel / 185$
semaine. 300 premiers km à 23¢, puis 15¢/km. (+15$/heure supplément par heure
excédentaire au tarif journalier, jusqu'à concurrence du prix journalier.)

Haute saison (Jun 15 – Oct 15): 50$ 1er jour / 42$ jour additionnel / 220$
semaine. Mêmes paliers km.

## Aller-retour rapide (quick round-trip preferential rate)

Économique / Économique Plus / Économique Extra holders automatically get billed
at Liberté Plus rates if that's cheaper for a given trip — mostly matters for
short trips with a lot of km (e.g. 1h / 60km). Rarely beats Économique Extra's
own rate since it's already so low; the script's `trip-cost` command checks this
automatically and reports if Liberté Plus pricing would be applied.

## Vehicle class surcharge — now modeled in the calculator

- **Minivan surcharge: +15%** on trip cost (time and km combined).
- **Family-category vehicle surcharge: +10%** on trip cost (time and km
  combined). Confirmed against a real receipt on 2026-08-11.
- Use `--vehicle-class family` or `--vehicle-class minivan` on `trip-cost`
  (default `standard`, no surcharge). Applied as a final multiplier on top of
  the winning price (station or FLEX, whichever applies).

## Other fees (not modeled in the calculator, mention if relevant)

- Trips longer than 28 days: +5$/additional day.
- Phone reservations/changes: 1,50$ (day) / 2,50$ (evening). Free via app/web.
- Damage waiver (collision): default deductible 750$/event, costs
  1,15$ at trip start + 0,50$/hour, capped 5$/day and 10$/week. Buy-down options:
  350$ deductible for 100$/year, or 0$ deductible for 135$/year (or 36$/year with
  qualifying credit-card insurance).
