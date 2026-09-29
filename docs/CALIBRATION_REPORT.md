# Calibration Report

Generated 2026-09-29 from ACS 5-Year vintage 2023 with business rules 1.0.0. 33,791 ZCTAs in the database, 30,983 with at least 50 households (the population below). Nothing here changes a rule; edit `business_rules.yaml`.

## 1. Metric percentiles versus ramp floors and ceilings

| Component | Metric | p5 | p10 | p25 | p50 | p75 | p90 | p95 | Floor (scores 0) | Ceiling (scores 100) | Below floor | Above ceiling | Missing |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| owner_concentration | owner_occupancy_share (linear) | 0.406 | 0.525 | 0.672 | 0.781 | 0.864 | 0.926 | 0.961 | 0.400 | 0.850 | 4.9% | 29.0% | 0 |
| owner_age_45_plus | owner_45_plus_share (linear) | 0.584 | 0.634 | 0.698 | 0.757 | 0.821 | 0.895 | 0.950 | 0.500 | 0.800 | 1.9% | 32.0% | 109 |
| housing_age | pre_2000_share (linear) | 0.504 | 0.603 | 0.729 | 0.826 | 0.900 | 0.951 | 0.976 | 0.300 | 0.850 | 1.4% | 41.6% | 0 |
| purchasing_power | median_household_income (linear) | 37,830 | 44,511 | 55,938 | 70,024 | 89,139 | 115,690 | 136,647 | 40,000 | 120,000 | 6.4% | 8.6% | 1,132 |
| serviceability | households_per_sq_mile (log10) | 1 | 3 | 9 | 33 | 292 | 1,360 | 2,282 | 10 | 1,000 | 27.4% | 13.2% | 0 |

## 2. Component score percentiles (0-100)

| Component | p5 | p10 | p25 | p50 | p75 | p90 | p95 | Mean |
|---|---|---|---|---|---|---|---|---|
| owner_concentration | 1.3 | 27.7 | 60.5 | 84.7 | 100.0 | 100.0 | 100.0 | 74.6 |
| owner_age_45_plus | 28.0 | 44.7 | 66.0 | 85.7 | 100.0 | 100.0 | 100.0 | 78.7 |
| housing_age | 37.1 | 55.1 | 78.0 | 95.6 | 100.0 | 100.0 | 100.0 | 85.1 |
| purchasing_power | 0.0 | 5.6 | 19.9 | 37.5 | 61.4 | 94.6 | 100.0 | 42.6 |
| serviceability | 0.0 | 0.0 | 0.0 | 26.2 | 73.3 | 100.0 | 100.0 | 38.2 |

## 3. Opportunity Score distribution

| p5 | p10 | p25 | p50 | p75 | p90 | p95 | Mean |
|---|---|---|---|---|---|---|---|
| 45.8 | 52.5 | 63.6 | 73.0 | 80.9 | 87.1 | 91.6 | 71.2 |

| Tier | ZCTAs | Share |
|---|---|---|
| A | 13,552 | 40.1% |
| B | 11,584 | 34.3% |
| C | 4,452 | 13.2% |
| D | 1,395 | 4.1% |
| U | 2,808 | 8.3% |

Unscored reasons: INSUFFICIENT_HOUSEHOLDS 2,808.

## 4. Opportunity Units per ZCTA

| p5 | p10 | p25 | p50 | p75 | p90 | p95 | Total | ZCTAs with OU |
|---|---|---|---|---|---|---|---|---|
| 6 | 25 | 98 | 396 | 1,734 | 4,165 | 5,735 | 44,835,352 | 33,772 |

At the median ZCTA (396 OU) a Standard territory (20,000-32,000 OU) needs about 51-81 median ZCTAs; suburban ZCTAs in the top quartile need fewer.

