# Scoring Specification v1.0

Defines the Bath Conversion Opportunity Score (Phase 2) and Opportunity Units (Phase 3). Both
are computed only from public data and configuration. Nothing here uses BizGrips performance
data. The score is a comparative index for sales intelligence; it does not predict or guarantee
marketing results and output wording must never imply that it does.

Implementation target: `app/services/scoring.py` (Milestone 3), pure functions:

```
score_zcta(record: ZctaRecord, rules: BusinessRules) -> ZctaScore
opportunity_units(record: ZctaRecord, rules: BusinessRules) -> OpportunityUnits
score_territory(records: list[ZctaRecord], rules: BusinessRules) -> TerritoryScore
```

Configuration: `app/config/business_rules.yaml` (`scoring`, `opportunity_units`).

---

## 1. Inputs per ZCTA

| Input | Source field | Used by |
|-------|--------------|---------|
| total_households | ACS B25003_001E | owner share, density |
| owner_occupied_households | ACS B25003_002E | owner share, OU base |
| owner_households_age_45_plus | ACS B25007_006E–011E | 45+ share |
| total_housing_units | ACS B25034_001E | pre-2000 share |
| homes_built_before_2000 | ACS B25034_005E–011E | pre-2000 share |
| median_household_income | ACS B19013_001E | purchasing power |
| land_area_sq_miles | TIGER ALAND20 / 2,589,988.11 | density |

Any input may be `None` (missing). Missing handling is explicit (section 4).

## 2. Derived metrics

```
owner_occupancy_share   = owner_occupied_households / total_households        (None if either missing or total = 0)
owner_45_plus_share     = owner_households_age_45_plus / owner_occupied_households (None if missing or owner = 0)
pre_2000_share          = homes_built_before_2000 / total_housing_units      (None if missing or total = 0)
households_per_sq_mile  = total_households / land_area_sq_miles              (None if missing or area = 0)
```

## 3. Component scores (0–100)

Each component maps one metric through a clamped ramp defined in
`scoring.components.<name>`:

```
linear:  component = clamp(100 * (value - floor) / (ceiling - floor), 0, 100)
log10:   component = clamp(100 * (log10(value) - log10(floor)) / (log10(ceiling) - log10(floor)), 0, 100)
```

For `log10`, a value <= 0 scores 0.

| Component | Metric | Scale | Floor → 0 | Ceiling → 100 | Weight |
|-----------|--------|-------|-----------|---------------|--------|
| owner_concentration | owner_occupancy_share | linear | 0.40 | 0.85 | 0.35 |
| owner_age_45_plus | owner_45_plus_share | linear | 0.50 | 0.80 | 0.25 |
| housing_age | pre_2000_share | linear | 0.30 | 0.85 | 0.20 |
| purchasing_power | median_household_income | linear | 40,000 | 120,000 | 0.15 |
| serviceability | households_per_sq_mile | log10 | 10 | 1,000 | 0.05 |

Ramps are hypotheses chosen to span roughly the 10th–90th percentile of US ZCTAs. Milestone 3
includes a calibration step that reports the actual percentiles from imported data so the
ramps can be adjusted in configuration.

## 4. Missing data

1. If `total_households < scoring.min_households_for_scoring` (50) or is missing, the ZCTA is
   **unscored**: `score = None`, `tier = "U"`, reason `INSUFFICIENT_HOUSEHOLDS`.
2. If any component listed in `scoring.required_components` (default: `owner_concentration`)
   is missing, the ZCTA is unscored with reason `MISSING_REQUIRED_<COMPONENT>`.
3. Otherwise each missing component is handled by `scoring.missing_data_policy`:
   - `renormalize` (default): the component is dropped and the remaining weights are rescaled
     to sum to 1.0. `data_completeness` = sum of weights of available components (0–1).
   - `zero`: the component scores 0 and `data_completeness` is reported the same way.
4. The output always lists `missing_components` so the UI can show why a score is partial.

## 5. Opportunity Score and tier

```
score = sum(weight_i * component_i for available components) / sum(weight_i for available components)   # renormalize
score = round(score, scoring.rounding_decimals)   # 1 decimal; display as integer
tier  = first tier in scoring.tiers (top-down) whose threshold <= score
```

Tiers: A ≥ 75, B ≥ 60, C ≥ 45, D ≥ 0, U = unscored.

## 6. Opportunity Units (OU)

OU approximates "desirable homeowner households" for territory sizing and comparison:

```
age_factor              = age_45_plus_floor + (1 - age_45_plus_floor) * owner_45_plus_share
housing_age_factor      = hf.floor + (1 - hf.floor) * min(pre_2000_share / hf.share_at_full_credit, 1)
purchasing_power_factor = clamp(pf.floor + (1 - pf.floor) * (income - pf.income_at_floor)
                                / (pf.income_at_full_credit - pf.income_at_floor), pf.floor, 1)
OU = owner_occupied_households * age_factor * housing_age_factor * purchasing_power_factor
OU = round(OU, opportunity_units.rounding_decimals)
```

With the V1 defaults (`age_45_plus_floor = 0.0`, housing floor 0.5, income floor 0.5 between
$45k and $90k), OU equals owner households 45+ discounted by up to 50% for newer housing and up
to 50% for lower purchasing power. OU is at most the owner 45+ count.

Missing inputs:
- `owner_occupied_households` missing → `OU = None` (`INSUFFICIENT_DATA`); the ZCTA can still be
  displayed but cannot count toward a territory size target.
- `owner_45_plus_share` missing → age_factor falls back to `age_45_plus_floor` if > 0, else OU is
  None. (Owner 45+ is the primary signal; without it the index is not meaningful.)
- housing or income input missing → `missing_factor_policy`: `neutral` (factor 1.0) or `floor`.
  The output lists `missing_factors`.

OU is an internal comparative index. Never present it as the number of homeowners who will buy.

## 7. Territory aggregation

A territory's figures are computed from the sum of its ZCTAs, not by averaging ZCTA scores:

```
totals: households, owner households, owner 45+, housing units, pre-2000 homes, land area, population
territory metrics: owner_occupancy_share, owner_45_plus_share, pre_2000_share, households_per_sq_mile from totals
territory median_household_income: household-weighted mean of ZCTA medians (documented approximation)
territory score: same ramps and weights applied to the territory metrics
territory OU: sum of ZCTA OU (ZCTAs with OU = None contribute 0 and are listed in missing_ou_zctas)
```

Two proposed territories are compared on OU, score, tier and totals side by side
(`compare_territories(a, b)`), which is the Phase 3 definition of done.

## 8. Determinism requirements

- Pure functions; inputs are plain records plus `BusinessRules`. No I/O, no clock, no randomness.
- Floating-point arithmetic in a fixed order; rounding only at the end (`round half even`).
- Same record + same rules ⇒ identical output, asserted by tests in Milestone 3.
- Changing a weight changes the score predictably: tests assert direction and magnitude.

## 9. Worked example (fixture ZCTA 80123, synthetic values)

Inputs: households 16,500; owner households 13,400; owner 45+ 9,300; housing units 17,200;
pre-2000 homes 9,800; median income $108,000; land area 11.2 sq mi.

| Component | Metric value | Ramp | Component score | Weight | Contribution |
|-----------|--------------|------|-----------------|--------|--------------|
| owner_concentration | 13,400 / 16,500 = 0.8121 | (0.8121 − 0.40) / 0.45 | 91.6 | 0.35 | 32.05 |
| owner_age_45_plus | 9,300 / 13,400 = 0.6940 | (0.6940 − 0.50) / 0.30 | 64.7 | 0.25 | 16.17 |
| housing_age | 9,800 / 17,200 = 0.5698 | (0.5698 − 0.30) / 0.55 | 49.0 | 0.20 | 9.81 |
| purchasing_power | 108,000 | (108,000 − 40,000) / 80,000 | 85.0 | 0.15 | 12.75 |
| serviceability | 16,500 / 11.2 = 1,473/sq mi | log ramp, clamped | 100.0 | 0.05 | 5.00 |

Score = 75.8 → Tier A. If median income were missing, weights renormalise over 0.85:
(32.05 + 16.17 + 9.81 + 5.00) / 0.85 = 74.2 → Tier B, `data_completeness = 0.85`,
`missing_components = [purchasing_power]`.

OU = 13,400 × (0 + 1 × 0.6940) × (0.5 + 0.5 × 0.5698) × 1.0 = 9,300 × 0.7849 × 1.0 = 7,299.

## 10. Output schema (ZctaScore)

```
zcta, score (float|None), tier (A|B|C|D|U), components: {name: {metric, value, score, weight, missing}},
data_completeness (0..1), missing_components [..], unscored_reason (str|None),
opportunity_units (float|None), ou_factors: {age, housing_age, purchasing_power}, missing_factors [..],
config_version
```
