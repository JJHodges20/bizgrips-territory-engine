# BizGrips Territory Standard v1.0

**Status:** Adopted for Milestone 0 as a set of working hypotheses. Every number in this document
lives in `app/config/business_rules.yaml`; that file is the operational source of truth and this
document explains it. Change both together.

**Purpose:** Define what a fair, sellable, protectable BizGrips territory is, so the software can
enforce it consistently and so nobody has to guess what "fair territory" means.

---

## 1. Definitions

| Term | Definition |
|------|------------|
| ZCTA | Census ZIP Code Tabulation Area, a 5-digit area approximating a USPS ZIP code. All market data is keyed by ZCTA. "ZIP" in outputs means ZCTA unless a postal ZIP is explicitly stated. |
| Postal ZIP | A currently deliverable USPS ZIP code. Territories are validated against postal ZIPs before contracting or ad targeting. |
| Household | An occupied housing unit (ACS B25003_001E). |
| Owner household | An owner-occupied housing unit (ACS B25003_002E). |
| Owner 45+ | An owner household whose householder is 45 years or older (ACS B25007_006E–B25007_011E). Primary age signal for V1. |
| Older housing stock | Housing units built before 2000 (ACS B25034_005E–B25034_011E). 1990 and 1980 cut-offs are stored for analysis. |
| Purchasing power | Median household income (ACS B19013_001E). Median home value is stored for analysis but not scored in V1. |
| Opportunity Score | A 0–100 comparative score per ZCTA built from weighted component scores. See `SCORING_SPEC.md`. |
| Market Tier | A/B/C/D from Opportunity Score thresholds; U means unscored. |
| Opportunity Units (OU) | Comparative index of addressable homeowner opportunity: owner households, weighted toward 45+, discounted for newer housing stock and lower purchasing power. Territory size is measured in OU, not population. |
| Territory | A named, approved set of ZCTAs assigned to one client under one status. |
| Contiguity | Rook adjacency: two ZCTAs are adjacent if they share a boundary of non-zero length. A territory must form one connected component. |
| Serviceability | Whether a contractor can realistically serve a ZCTA from the starting ZIP: distance and land area. |
| Availability | A ZCTA is AVAILABLE when no assignment in a blocking status exists for it. |

## 2. Variables used to evaluate territory quality

V1 evaluates opportunity from public data only, in this priority:

1. Owner-occupied households (count and concentration)
2. Owner households age 45+ (count and share of owner households)
3. Age of housing stock (share built before 2000)
4. Household income / purchasing power (median household income)
5. Geographic practicality (household density, land area, distance from the starting ZIP)
6. Territory availability (registry status)

Population is displayed for context but is never a sizing or fairness metric.

Weights (hypothesis): owner concentration 35%, owner 45+ 25%, housing age 20%, purchasing power
15%, serviceability 5%. Formulas are in `SCORING_SPEC.md`.

## 3. Territory size classes

Territory size is measured in Opportunity Units so that two territories in the same class carry
comparable economic opportunity even if their populations differ.

| Class | Target OU band | Typical owner households* | Typical population* | Typical ZCTA count* |
|-------|----------------|---------------------------|---------------------|---------------------|
| Minimum viable | 10,000 (floor of Small) | ~17,000 | ~65,000 | 2–5 |
| Small | 10,000 – 20,000 | 17,000 – 35,000 | 65,000 – 135,000 | 2–8 |
| Standard (default) | 20,000 – 32,000 | 35,000 – 55,000 | 135,000 – 215,000 | 4–12 |
| Large | 32,000 – 45,000 | 55,000 – 78,000 | 215,000 – 300,000 | 6–18 |
| Absolute maximum | 50,000 OU or 40 ZCTAs, whichever comes first | | | |

\*Typical figures assume roughly 70% of owner households are 45+, an average OU discount factor
of about 0.82, 65% owner occupancy and 2.5 persons per household. They are illustrative only;
the OU band is the rule.

Rules:

- The generator stops adding ZCTAs once the territory's OU is inside the class band. It may
  overshoot `target_max` by at most `target_tolerance` (10%) to include a final ZCTA.
- A proposal below `minimum_viable_units` (10,000 OU) is flagged `BELOW_MINIMUM_VIABLE` and must
  not be reserved without a manual exception.
- A proposal above `absolute_max_units` (50,000 OU) or `max_zctas_per_territory` (40) is
  flagged `EXCEEDS_MAX_SIZE` and requires a manual exception.
- The 40,000–50,000 owner-household heuristic from earlier practice is deliberately not locked
  in. Bands will be revisited once BizGrips has operational evidence.

## 4. Serviceability rules

| Rule | Value | Behaviour |
|------|-------|-----------|
| Default service radius | 30 miles from the starting ZCTA centroid | Generator considers ZCTAs within this radius unless the request sets its own. |
| Maximum service radius | 45 miles | A request may raise the radius up to this; beyond it requires an `OUTSIDE_SERVICE_RADIUS` exception. |
| Very large ZCTA | Land area > 400 sq mi | Flagged `UNSERVICEABLE_LAND_AREA`; never auto-selected; included only as a starting ZIP or by exception. |
| Household density | Log ramp 10–1,000 households/sq mi | Feeds the 5% serviceability score component. |
| State lines | Crossing allowed | Cross-state territories are permitted but flagged `CROSSES_STATE_LINE` for contract review. `allow_cross_state: false` disables. |

Distances are great-circle distances between ZCTA centroids. Drive-time is a future refinement.

## 5. Contiguity rule

Every ZCTA in a territory must share a boundary with at least one other ZCTA in the territory,
and the territory as a whole must be a single connected component of the adjacency graph.

- The generator only ever adds ZCTAs adjacent to the current territory.
- A requested ZCTA that cannot be connected is reported as `NOT_CONTIGUOUS` and excluded.
- A human may include it with a `NON_CONTIGUOUS_ZCTA` exception (for example a satellite town the
  contractor already serves). The exception is recorded on the territory.

## 6. ZIP conflict rules

A ZCTA is in **conflict** for a prospect when an assignment for it exists with a blocking status
(RESERVED, ACTIVE_PROTECTED or PENDING_RELEASE) belonging to a **different** client.

- The same client re-requesting its own ZCTAs is not a conflict.
- PENDING_RELEASE ZCTAs remain conflicts until their `release_date` has passed.
- Expired reservations remain conflicts until a human releases them (the engine flags
  `RESERVATION_EXPIRED` so the sales manager can act).
- No buffer zone is required between territories in V1 (`buffer_zone_required: false`).
- Conflicts are never resolved automatically. The engine excludes conflicting ZCTAs and
  suggests nearby available replacements.

## 7. Exclusivity rules

- Exclusivity is granted at the ZCTA level. A ZCTA can belong to at most one territory in a
  blocking status at any time. The registry enforces this with a database constraint and a
  service-level check.
- The approved ZCTA list is the single definition of the territory. Contracts, client records,
  the client portal and ad targeting all consume that list; none of them may redefine it.
- Changing an ACTIVE_PROTECTED territory's ZCTA list creates a new territory version with its own
  approval; the previous list is retained for audit.
- Postal validation: before a territory is contracted or pushed to ad targeting, each ZCTA must
  map to a deliverable postal ZIP; ZCTAs without one are listed for human review.

## 8. Reservation rules

| Rule | Value |
|------|-------|
| Reservation created | When an approver moves a PROPOSED territory to RESERVED during the sales/contracting window. |
| Reservation length | 30 days from `reservation_date`. |
| Extension | One extension of 15 days, recorded with approver and reason. |
| Effect | Reserved ZCTAs are conflicts for every other prospect. |
| Expiry | After expiry the reservation is flagged `RESERVATION_EXPIRED`. ZCTAs stay blocked until a human releases or converts the reservation. Automated expiry handling is a Phase 11 (n8n) concern. |
| Conversion | A signed agreement moves RESERVED to ACTIVE_PROTECTED with `contract_start_date` set. |

## 9. Manual exception rules

Humans may record an exception only from this list, always with `approved_by` and a reason:

| Exception | Meaning |
|-----------|---------|
| NON_CONTIGUOUS_ZCTA | Include a ZCTA that does not touch the territory. |
| EXCEEDS_MAX_SIZE | Approve a territory above the absolute maximum. |
| UNSERVICEABLE_ZCTA | Include a ZCTA flagged unserviceable (land area). |
| OUTSIDE_SERVICE_RADIUS | Include a ZCTA beyond the maximum radius. |
| CROSS_STATE | Explicitly acknowledge a cross-state territory where policy disallows it. |
| OVERRIDE_EXPIRED_RESERVATION | Release another prospect's expired reservation in favour of this one. |

Never allowed: assigning a ZCTA that is ACTIVE_PROTECTED for another client. There is no
exception for that; the protected client's contract must end or be amended first.

## 10. Human approval requirements

- The engine only ever produces PROPOSED territories.
- Moving to RESERVED or ACTIVE_PROTECTED requires `approved_by` (a named person) and an approval
  timestamp. The API rejects status changes without them.
- Approvals, extensions, exceptions and releases are written to the territory's audit trail
  (notes plus timestamps) and are never deleted.
- Sales staff do not decide availability by memory or by reading contracts: the workflow is
  enter location → generate → check conflicts → human approval → reserve.

## 11. Territory release rules

- Contract end, cancellation or offboarding moves a territory to PENDING_RELEASE with a
  `release_date` (default: 30 days' notice from the decision, or the contract end date if later).
- On the release date the territory becomes RELEASED and its ZCTAs become AVAILABLE. History is
  retained: assignments keep `date_released`, and the territory record is never deleted.
- Released ZCTAs may be re-sold immediately after the release date.
- A client returning after release receives a new territory record; the old one stays for audit.

## 12. Configuration map

| Rule | Key in `business_rules.yaml` |
|------|------------------------------|
| Score weights and component ramps | `scoring.weights`, `scoring.components` |
| Missing-data behaviour | `scoring.missing_data_policy`, `scoring.required_components`, `scoring.min_households_for_scoring` |
| Tier thresholds | `scoring.tiers` |
| Opportunity Unit factors | `opportunity_units.*` |
| Size bands, minimum viable, absolute maximum | `territory_sizes.*` |
| Radius, land-area cap, cross-state | `serviceability.*` |
| Selection priority and tie-breakers | `generator.*` |
| Blocking statuses, reservation timings, exceptions, approvals | `registry.*` |

## 13. Change log

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-09-29 | Initial standard adopted with Milestone 0. All values are hypotheses pending calibration in Milestone 3 and operational validation. |
