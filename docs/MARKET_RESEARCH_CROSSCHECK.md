# Market Research Cross-Check (2026-09-29)

Twelve BizGrips client market-research briefs (bath-conversion contractors in the markets
BizGrips has worked so far) were compared against the V1 opportunity signals in
`BIZGRIPS_TERRITORY_STANDARD.md` section 2, `SCORING_SPEC.md` and
`app/config/business_rules.yaml`. The question was whether the Opportunity Score rewards the
households those contractors actually sell to, and in particular whether the homeowner age
floor should stay at 45+.

**Outcome: no rule values changed.** The 45+ floor stays. Every scoring signal matches the
briefs. One signal the briefs use and the engine does not (length of home ownership) is
recorded below as a V2 candidate.

## 1. Homeowner age: keep 45+

Ideal-customer age ranges stated in the briefs:

| Client brief | Stated age range | Also named |
|--------------|------------------|------------|
| All County | 45–75 | |
| Blue Zone | 50–75 | |
| Carolina | 55–80 | adult children 35–60 deciding for parents |
| Coast 2 Coast | 55–80 | |
| Liberty | 50–78 | |
| Littleton | 50–75 | |
| Milan | 45–75 | |
| Peach | 40–70 | |
| Pure Bath | 45–75 | |
| Sanford | 45–75 | |
| Smart Choice | 45–75 | |
| Tag Bath | 55–80 | adult children 35–60 deciding for parents |

Reading of the evidence:

- Six of the twelve briefs put the floor at 45 or lower, three at 50 and three at 55. A 45+
  floor is a superset of every profile except Peach's 40–44 band, which no ACS owner-age
  bucket isolates anyway (buckets are 35–44 and 45–54).
- The two briefs with the highest floor (Carolina, Tag Bath) also name adult children aged
  35–60 as the decision makers for aging parents. Those buyers mostly own their own homes and
  fall inside the 45–54 bucket, so the 45+ count captures a real decision-maker segment even
  for the 55+ profiles.
- Design-driven and "aging in place early" segments described in several briefs
  (remodel-for-comfort, walk-in shower before mobility declines) sit in the 45–60 band.
- Raising the floor to 55+ would shrink Opportunity Units in every market by roughly the same
  proportion, which lowers the absolute numbers without improving the ranking of one ZCTA
  against another. It would also drop the 45–54 core audience of half the clients. There is
  therefore no evidence that a stricter floor would help the contractors BizGrips serves.

Decision: `owner_age_45_plus` remains the primary age signal (weight 0.25) and the OU age
factor keeps `age_45_plus_floor = 0`, so OU ≈ owner 45+ households discounted by housing age and
purchasing power. The stored 55+ and 65+ counts remain analysis columns for the
accessibility-priority segment (Carolina, Coast 2 Coast, Tag Bath) and can be surfaced in the
sales-call checker later without changing the score.

## 2. Signal-by-signal check

| V1 signal (weight) | What the briefs say | Verdict |
|--------------------|---------------------|---------|
| Owner-occupied households, 0.35 | Every brief targets homeowners; several exclude renters outright and flag renter-heavy urban cores (e.g. New Brunswick) and brand-new subdivisions (e.g. Brighton) as poor fits. | Lines up. Owner concentration is the required component; renter-heavy cores score low on it and new subdivisions score low on housing age. |
| Owner households 45+, 0.25 | See section 1. | Lines up at 45+. |
| Housing age (share built before 2000), 0.20 | All twelve cite older housing stock: "pre-1980", "25+ years", "40+ years", "50+ years", "mid-century", "postwar", "original bathrooms". | Lines up. At the 2023 vintage, built before 2000 means 24+ years old; the ramp (30%→85%) rewards older stock comparatively. Pre-1990 and pre-1980 counts are stored for analysis. |
| Purchasing power (median household income), 0.15 | Wide spread: Sun Belt suburb briefs (Phoenix area) expect $100K–$250K+ incomes and $400K–$1M+ home values; Rust Belt briefs (Akron, Jeannette, Grand Blanc) describe moderate-income households buying with financing. | Lines up with a modest weight. The $40K ramp floor and the 0.5 OU factor floor keep moderate-income client markets scoreable instead of zeroing them. `median_home_value` (B25077) is stored as an equity proxy for the cash-pay profiles (All County, Blue Zone). |
| Serviceability (household density), 0.05 | Briefs describe 30–45 minute drive radii and suburban/exurban density as the sweet spot. | Lines up with the 30 mi default / 45 mi maximum radius and the 400 sq mi land-area cap. |

## 3. Signals the briefs use that V1 does not measure

| Brief signal | Frequency | Status |
|--------------|-----------|--------|
| Length of home ownership (5+, 7+, 8+ or 10+ years in the home) | 11 of 12 briefs | **V2 candidate.** ACS table B25038 (Tenure by Year Householder Moved Into Unit) gives owner households by move-in period at the ZCTA level. Recommended first step: import `B25038` as an analysis column (owners who moved in before 2018 ≈ 5+ years at vintage 2023), then calibrate it in Milestone 3 before giving it any weight. Adding it changes no current rule. |
| Single-bathroom homes (Liberty) | 1 brief | Not available from ACS at ZCTA level. Out of scope. |
| Owner-occupants in 2–4 unit buildings (Newark) | 1 brief | Measurable from ACS B25032 but market-specific; not a V1 signal. |
| Adult children living outside the market | 2 briefs | Not measurable from public data. |

## 4. How this was used

- No change to `business_rules.yaml` (version stays 1.0.0).
- Recorded in the Territory Standard change log and the implementation status decisions log.

## 5. Measured with ACS 2019-2023 (after the Milestone 1 import)

Across the 19,844 ZCTAs with at least 500 owner households:

| Measure | Owner 45+ | Owner 55+ |
|---------|-----------|-----------|
| National share of owner households | 73.2% (59.5 M) | 54.5% (44.3 M) |
| Share per ZCTA, 10th / 50th / 90th percentile | 0.645 / 0.746 / 0.846 | 0.448 / 0.563 / 0.693 |
| Spread (90th / 10th percentile) | 1.31× | 1.54× |

- The 45–54 band adds 15.2 M owner households nationally, about a third more countable
  opportunity than a 55+ definition would give. That is business the 45+ floor keeps for the
  six clients whose profile starts at 45 and for the adult-child decision makers of the rest.
- The 45+ share varies less between ZCTAs than the 55+ share, so it keeps Opportunity Units
  comparable across markets (the fairness goal of territory sizing) rather than swinging
  territory size on how retiree-heavy a ZCTA is.
- The 55+ share is stored for every ZCTA. If BizGrips ever sees evidence that 55+ households
  convert materially better, it can be calibrated in as a secondary component in Milestone 3
  without re-importing anything.
