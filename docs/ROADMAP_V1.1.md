# BIZGRIPS TERRITORY INTELLIGENCE SYSTEM — ROADMAP V1.1 (CLAUDE CODE READY)

> This is the master roadmap supplied by BizGrips, stored verbatim so the
> repository, not chat history, is the source of truth. The specification
> documents in this folder (`BIZGRIPS_TERRITORY_STANDARD.md`, `SCORING_SPEC.md`,
> `DATA_DICTIONARY.md`, `TERRITORY_ALGORITHM.md`, `MILESTONES.md`) refine it.
> Where they conflict, the specification documents win and this file should be
> updated in the same change.

PURPOSE

Build an internal BizGrips territory intelligence system that can:

1. Take a contractor's location or starting ZIP code.
2. Identify nearby ZIP codes that are still available.
3. Estimate how attractive each ZIP is for bathroom conversion opportunities using public demographic and housing data.
4. Build a contiguous territory with roughly equivalent economic opportunity.
5. Check for exclusivity conflicts with current BizGrips clients.
6. Allow human approval before a territory becomes protected.
7. Track which ZIP codes are available, reserved, active, or pending release.
8. Produce clear market outputs that can be used during sales calls with prospective clients.
9. Eventually feed the same approved territory into contracts, onboarding, client records, and Meta ad targeting.
10. Later, once BizGrips has enough historical performance data, improve the scoring model using real lead, consultation, and sales outcomes.

The long-term goal is to move from simple population-based exclusivity to a proprietary BizGrips system that allocates territory based on estimated bathroom-conversion opportunity.

==================================================
CORE PRODUCT PRINCIPLES
==================================================

1. V1 AND V2 MUST WORK WITHOUT BIZGRIPS PERFORMANCE DATA.

BizGrips currently has limited historical data. Early versions of the system must rely on high-quality public data and transparent business rules.

The engine should already be useful for:
- Sales calls
- Market availability checks
- Territory recommendations
- Exclusivity planning
- Conflict prevention
- Client organization

BizGrips performance data is a future enhancement, not a dependency.

2. OWNER-OCCUPIED HOUSEHOLDS MATTER MORE THAN RAW POPULATION.

A territory with more qualified homeowner households may be more valuable than a more populated territory with a high renter concentration.

3. HOMEOWNER AGE 45+ IS THE PRIMARY AGE SIGNAL FOR V1.

For V1, prioritize owner-occupied households with householders age 45+.

Additional age brackets may still be stored for analysis later, but the main early scoring input should be 45+ homeowners.

4. TERRITORY FAIRNESS SHOULD MEAN COMPARABLE ECONOMIC OPPORTUNITY.

The system should not assume that equal population means equal value.

5. THE ENGINE RECOMMENDS. HUMANS APPROVE.

No territory should become contractually protected solely because an algorithm generated it.

6. ONE TERRITORY DEFINITION SHOULD BECOME THE SOURCE OF TRUTH.

The approved ZIP list should eventually drive:
- Contract exclusivity
- Internal client records
- Client Portal
- Meta targeting
- Reporting

==================================================
PHASE 0 — DEFINE THE BIZGRIPS TERRITORY STANDARD
==================================================

Before writing the main application, define the business rules the software will enforce.

Do not define territory fairness only by total population.

V1 territory opportunity should be evaluated primarily through:
- Owner-occupied households
- Owner households age 45+
- Age of housing stock
- Household income / purchasing power
- Geographic practicality
- Territory availability

DELIVERABLE

Create:

docs/BIZGRIPS_TERRITORY_STANDARD.md

It should define:
- Minimum viable territory
- Standard territory
- Large territory
- Target opportunity range for each size
- Maximum territory size
- Maximum reasonable drive radius or serviceability rule
- Variables used to evaluate territory quality
- ZIP conflict rules
- Exclusivity rules
- Reservation rules
- Manual exception rules
- Human approval requirements
- Territory release rules

IMPORTANT

The values used in V1 are hypotheses.

They should be easy to change later through configuration rather than hard-coded throughout the application.

DEFINITION OF DONE

- Territory size classes are clearly defined.
- Conflict behavior is clearly defined.
- Reservation and release rules are clearly defined.
- Human approval requirements are clear.
- Claude Code can implement later phases without guessing what "fair territory" means.

==================================================
PHASE 1 — BUILD THE NATIONAL ZIP / ZCTA MARKET DATABASE
==================================================

Create a master database containing the public market information required to score territories.

PRIMARY DATA SOURCES

Use Census ACS 5-Year data for demographic and housing information.

Use Census TIGER/Line files for ZCTA geographic boundaries and adjacency.

IMPORTANT NOTE

Census demographic information is generally published for ZCTAs, which approximate USPS ZIP codes.

ZCTAs are suitable for market intelligence.

Before a territory becomes contractually protected or is pushed into Meta targeting, the final ZIP list should eventually be validated against currently usable postal ZIP codes.

INITIAL DATA MODEL

GEOGRAPHY
- zcta
- postal_zip_if_available
- primary_city
- state
- latitude
- longitude
- geometry
- neighboring_zctas

HOUSEHOLDS
- total_households
- owner_occupied_households
- owner_occupancy_percent

HOMEOWNER AGE
- owner_households_age_45_plus
- owner_households_age_55_plus_optional
- owner_households_age_65_plus_optional

HOUSING STOCK
- total_housing_units
- homes_built_before_2000
- homes_built_before_1990
- homes_built_before_1980

ECONOMICS
- median_household_income
- median_home_value

TERRITORY STATE
- territory_status
- assigned_client_id
- territory_id

DATA PROVENANCE

Every imported demographic field should retain enough metadata to identify:
- Source dataset
- Source year / release
- Table or variable identifier
- Last updated timestamp

This makes the engine auditable and easier to update when Census releases change.

DEFINITION OF DONE

- A repeatable import process loads the required public data.
- Data can be refreshed without rebuilding the application manually.
- ZIP / ZCTA records can be queried by state, city, and code.
- Adjacency relationships can be calculated or stored.
- Source provenance is recorded.

==================================================
PHASE 2 — CREATE BATH CONVERSION OPPORTUNITY SCORE V1
==================================================

Create a simple, transparent score that works entirely from public data.

Do not use BizGrips historical performance in V1.

The purpose of this score is comparison and sales intelligence, not scientific prediction.

POSSIBLE V1 WEIGHTS

35% — Owner-occupied household concentration
25% — Owner households age 45+
20% — Older housing stock
15% — Household income / purchasing capacity
5% — Geographic / serviceability factors

These weights are starting assumptions and should be stored in configuration.

EXAMPLE OUTPUT

ZIP: 80123

Owner households: 13,400
Owner households age 45+: 9,300
Homes built before 2000: 9,800
Median household income: $108,000

Bath Opportunity Score: 87 / 100
Market Tier: A

SCORING REQUIREMENTS

- Individual component scores should be visible.
- Weighting should be configurable.
- Missing public data should be handled explicitly.
- The system should never imply that the score guarantees marketing performance.
- Score calculations should be deterministic and testable.

DEFINITION OF DONE

Given the same source data and configuration, the same ZIP always produces the same score.

==================================================
PHASE 3 — CREATE THE ADDRESSABLE HOMEOWNER INDEX
==================================================

Move beyond raw population as the main territory-sizing metric.

Instead of:

"This territory has 180,000 people."

The system should be able to say:

"This territory contains approximately 48,000 desirable homeowner households."

Create an internal metric such as:

BATH CONVERSION OPPORTUNITY UNITS

V1 inputs may include:
- Owner-occupied households
- Owner household age 45+ factor
- Housing age factor
- Purchasing power factor

IMPORTANT

This is an internal comparative index.

Do not present it as the literal number of homeowners who will buy a bath conversion.

INITIAL TERRITORY TARGETS

Use configurable target bands.

For example:
- Small territory: lower target opportunity range
- Standard territory: middle target opportunity range
- Large territory: higher target opportunity range

Do not permanently lock the system to 40,000–50,000 households until BizGrips has validated that range operationally.

DEFINITION OF DONE

The system can aggregate the opportunity index across multiple ZIPs and compare two proposed territories.

==================================================
PHASE 4 — BUILD THE TERRITORY GENERATOR
==================================================

Create the first truly useful engine.

INPUT

- Client / prospect name
- Starting ZIP
- Territory size class
- Optional requested ZIPs
- Optional maximum service distance

PROCESS

1. Start with the prospect's starting ZIP.
2. Check whether the starting ZIP is available.
3. Find geographically adjacent available ZIPs.
4. Evaluate opportunity scores.
5. Add contiguous ZIPs in a rational outward expansion.
6. Exclude protected or reserved ZIPs.
7. Continue until the territory reaches the configured opportunity target.
8. Return the recommended territory.
9. Require human approval.

PRIORITY ORDER

The generator should prioritize:
1. Availability
2. Geographic contiguity
3. Reasonable serviceability
4. Opportunity quality
5. Target opportunity size

It should not grab disconnected ZIPs simply because their scores add up correctly.

EXAMPLE OUTPUT

PROPOSED TERRITORY

80123
80127
80128
80120
80121

Total Owner Households: 45,200
Owner Households Age 45+: 31,700
Territory Opportunity Score: 83
Conflict Status: No Conflict

EXPLANATION OUTPUT

The system should also explain why ZIPs were selected.

Example:
- Starting ZIP included.
- 80127 selected because it is adjacent, available, and Tier A.
- 80128 selected because it maintains contiguity and moves the territory toward the Standard target.
- 80129 excluded because it is already protected.

DEFINITION OF DONE

Entering a valid starting ZIP returns:
- A contiguous proposed territory
- Aggregate demographics
- Opportunity score
- Conflict status
- Selection explanation
- Human approval requirement

==================================================
PHASE 5 — BUILD THE EXCLUSIVITY REGISTRY
==================================================

Create the source of truth for territory ownership.

TERRITORY STATUSES

- AVAILABLE
- RESERVED
- ACTIVE_PROTECTED
- PENDING_RELEASE

Every territory assignment should track:
- territory_id
- client_id
- client_business_name
- starting_zip
- territory_size_class
- status
- approved_by
- reservation_date
- contract_start_date
- contract_end_date
- release_date
- notes

Every ZIP assignment should track:
- territory_id
- client_id
- zip
- status
- date_assigned
- date_released

CORE RULE

Sales should never manually guess whether a market is available.

Before exclusivity is promised:

Enter location
→ Generate territory
→ Check conflicts
→ Human approval
→ Reserve territory

DEFINITION OF DONE

The system prevents the same active ZIP from being assigned to two protected clients.

==================================================
PHASE 6 — BUILD THE SALES CALL MARKET CHECKER
==================================================

This should be prioritized early because it creates immediate value before BizGrips has a large client dataset.

The goal is to give sales fast, credible market intelligence.

INPUT OPTIONS

A salesperson can:
- Enter one starting ZIP
- Paste requested ZIPs
- Search by city / market

OUTPUT

Show:
- Market availability
- Suggested territory
- Available ZIPs
- Reserved ZIPs
- Protected ZIPs
- Conflicting client where internally appropriate
- Nearby replacement ZIPs
- Owner households
- Owner households age 45+
- Housing-age profile
- Median household income
- Opportunity score
- Market tier

EXAMPLE

MARKET AVAILABLE

Recommended Territory: 11 ZIPs
Owner Households: 46,120
Owner Households Age 45+: 32,840
Opportunity Score: 82
Market Tier: A
Conflicts: None

SALES VALUE

This lets a salesperson say:

"We currently have availability in your market, and the territory we're looking at has a strong concentration of homeowners and older housing stock."

The application should help the salesperson make factual statements based on the underlying public data.

DEFINITION OF DONE

A salesperson can evaluate a prospect's market in less than one minute without opening contracts or manually searching demographic websites.

==================================================
PHASE 7 — BUILD THE CONFLICT CHECKER
==================================================

Create a dedicated way to test custom requested ZIPs.

INPUT

- One ZIP
- List of ZIPs
- Proposed territory

OUTPUT

- Available ZIPs
- Reserved ZIPs
- Protected ZIPs
- Conflict count
- Suggested nearby replacements

EXAMPLE

Requested ZIPs: 12
10 Available
2 Protected

Conflicts:
80127 — Protected
80128 — Protected

Suggested replacements:
80129
80130

DEFINITION OF DONE

The checker produces deterministic results against the territory registry.

==================================================
PHASE 8 — ADD THE VISUAL TERRITORY MAP
==================================================

Do not build the map before the underlying data and territory logic are reliable.

LONG-TERM MAP

Green = Available
Red = Active / Protected
Yellow = Reserved
Gray = Low Priority / Unserviceable

Clicking an active territory may show:
- Client business
- Territory ID
- ZIP list
- Owner households
- Owner households age 45+
- Opportunity score
- Contract status
- Active since date

Clicking an available market may show:
- Available opportunity
- Suggested territory
- Estimated owner households
- Owner households age 45+
- Market score
- Nearby protected territories

The map should support:
- Sales
- Strategic expansion
- Territory planning
- Conflict resolution
- National market visibility

==================================================
PHASE 9 — CONNECT THE SYSTEM TO CLIENT ONBOARDING
==================================================

Once a deal signs:

Approved Territory
→ Contracted Territory
→ Create Territory ID
→ Mark ZIPs Active / Protected
→ Save ZIPs to Client Record
→ Add territory to Client Portal
→ Feed territory into downstream systems

CORE PRINCIPLE

One territory definition everywhere.

==================================================
PHASE 10 — CONNECT THE SYSTEM TO META CAMPAIGN PROVISIONING
==================================================

Only after territory generation and registry logic are trusted:

Approved client territory
→ Retrieve canonical ZIP list
→ Meta campaign automation
→ Use the same ZIPs for geographic targeting

BENEFIT

If a ZIP is contractually protected for Client A, Client B's automated campaign should not target that ZIP.

Meta integration is a downstream consumer of the territory engine.

It should not become the source of truth.

==================================================
PHASE 11 — OPTIONAL AUTOMATION / N8N INTEGRATION
==================================================

Use n8n for business-process orchestration after the core territory logic is stable.

Possible uses:
- New signed client triggers territory activation
- Territory reservation expiration
- Client offboarding releases territory
- Client Portal updates
- CRM updates
- Meta campaign provisioning
- Internal notifications

Do not put core scoring or geographic logic only inside opaque n8n workflows.

The canonical territory calculation should live in testable application code.

==================================================
PHASE 12 — FUTURE: BIZGRIPS PERFORMANCE LEARNING
==================================================

THIS PHASE IS DELIBERATELY NOT REQUIRED FOR V1 OR V2.

The territory engine must be useful before BizGrips has substantial historical data.

When sufficient performance data exists, add:
- ZIP
- Ad spend
- Leads
- Cost per lead
- Contact rate
- Scheduled consultations
- Booking rate
- Show rate
- Sales
- Close rate
- Cost per sale
- Revenue
- Average ticket

Then analyze:
- Do owner-heavy ZIPs perform better?
- Do owner households age 45+ correlate with stronger conversion?
- Are particular homeowner age bands especially valuable?
- Do older homes correlate with better bath conversion performance?
- Which housing construction eras perform best?
- Does median income correlate with closing rate?
- Is there a useful income threshold?
- Which variables correlate with lower acquisition cost?
- Which variables correlate with higher close rates?

Only after enough observations exist should BizGrips data affect territory scoring.

FUTURE EXAMPLE

BizGrips Bath Market Score v4.x

Possible future factors:
- Historical cost per acquisition
- Historical close rate
- Owner household age profile
- Housing stock age
- Household purchasing power
- Market competition

At that point the system evolves from:

"What public market characteristics suggest a strong bath market?"

to:

"What does the BizGrips network's real performance show makes a strong bath market?"

==================================================
RECOMMENDED TECHNICAL ARCHITECTURE
==================================================

The exact implementation can be chosen during repository setup, but the following architecture is recommended because it is straightforward for Claude Code to build and test incrementally.

BACKEND

Recommended:
- Python
- FastAPI

WHY
- Strong data-processing ecosystem
- Good Census / geospatial library support
- Simple API development
- Easy automated testing
- Claude Code can work effectively with a conventional Python project

DATABASE

Recommended:
- PostgreSQL
- PostGIS extension

WHY
- Reliable relational storage
- Geospatial polygon support
- Adjacency and overlap queries
- Scales well beyond the initial version

DATA PROCESSING

Possible libraries:
- pandas
- geopandas
- shapely
- SQLAlchemy / SQLModel
- psycopg
- requests or Census API client

FRONT END

Do not prioritize a sophisticated front end initially.

V1 may use:
- Minimal internal web UI
- Simple admin dashboard

A richer map UI can come later.

AUTOMATION

Use n8n for workflow orchestration, not the canonical scoring engine.

==================================================
CLAUDE CODE IMPLEMENTATION STRATEGY
==================================================

This roadmap is intentionally structured so Claude Code can build it incrementally.

1. CREATE A PROJECT CLAUDE.md

At repository root, create:

CLAUDE.md

It should contain:
- Project purpose
- Current architecture
- Business rules
- Canonical terminology
- Common commands
- Testing commands
- Coding conventions
- Important constraints
- Current milestone
- Files Claude should read before changing territory logic

Keep CLAUDE.md concise and update it as architecture decisions change.

2. KEEP BUSINESS RULES OUTSIDE PROMPTS

Store business definitions in version-controlled files such as:

docs/BIZGRIPS_TERRITORY_STANDARD.md
docs/SCORING_SPEC.md
docs/DATA_DICTIONARY.md
docs/TERRITORY_ALGORITHM.md

Claude Code should implement against these specifications rather than relying on remembered chat context.

3. BUILD ONE MILESTONE AT A TIME

Recommended order:

Milestone 0 — Repository + development environment
Milestone 1 — Public data ingestion
Milestone 2 — ZIP/ZCTA data API
Milestone 3 — Opportunity scoring
Milestone 4 — Territory registry
Milestone 5 — Territory generator
Milestone 6 — Conflict checker
Milestone 7 — Sales call interface
Milestone 8 — Map
Milestone 9 — Onboarding / n8n
Milestone 10 — Meta integration
Milestone 11 — Historical BizGrips learning

Do not ask Claude Code to build the entire system in one run.

4. EACH MILESTONE NEEDS A SPEC

Before implementation, define:
- Inputs
- Outputs
- Business rules
- Edge cases
- Acceptance criteria
- Test fixtures
- Out-of-scope items

5. USE PLAN MODE BEFORE LARGE CHANGES

For major milestones:
- Ask Claude Code to inspect the repository.
- Ask for an implementation plan.
- Review the plan.
- Then authorize implementation.

6. REQUIRE TESTABLE, DETERMINISTIC LOGIC

Scoring and territory generation should be functions/services that can be tested without the UI.

Example:

score_zcta(data, config) -> score

generate_territory(start_zip, size_class, exclusions) -> proposed_territory

check_conflicts(zip_list) -> conflict_result

7. USE FIXTURE MARKETS

Create a small deterministic test dataset with several known scenarios.

Examples:
- Available suburban market
- Starting ZIP already protected
- Market surrounded by protected ZIPs
- Rural ZIP with very large land area
- Missing Census fields
- Requested territory that is disconnected
- ZIP on a state border
- Territory that reaches target with multiple valid paths

Do not test only one local market.

8. DEFINE ACCEPTANCE TESTS BEFORE EACH BUILD

Examples:

Scoring:
- Same data + same config always produces same score.
- Changing a configured weight changes score predictably.
- Missing data behavior is explicit.

Registry:
- Active ZIP cannot be assigned to another active territory.
- Released ZIP becomes available.
- Reserved ZIP is identified as unavailable to another prospect.

Generator:
- Returned ZIPs are contiguous.
- Protected ZIPs are excluded.
- Starting ZIP is included when available.
- Target opportunity range is respected within configured tolerance.

9. MAINTAIN SOURCE TRACEABILITY

Data-import code should record:
- Dataset
- Release year
- Table / variable
- Import date

Do not silently mix Census releases without documenting them.

10. SEPARATE CONFIGURATION FROM CODE

Put changeable business assumptions in configuration.

Examples:
- Scoring weights
- Age threshold
- Territory target bands
- Maximum service distance
- Score tier thresholds

Do not scatter these values as hard-coded constants across the project.

11. USE GIT MILESTONE BOUNDARIES

Commit when a milestone:
- Passes tests
- Meets acceptance criteria
- Has updated documentation

This gives Claude Code safe rollback points and makes future sessions easier.

12. CREATE STANDARD PROJECT COMMANDS

Claude Code should be able to quickly discover and run commands such as:

make setup
make test
make lint
make dev
make import-data

Exact commands can vary, but there should be one obvious path for setup and verification.

13. DO NOT OVER-ENGINEER EARLY

V1 does not need:
- Machine learning
- Automated score optimization
- Perfect national map UI
- Real-time Meta integration
- Complex microservices
- Multiple cloud services
- Historical BizGrips performance ingestion

The first objective is a reliable internal territory recommendation and availability tool.

14. DOCUMENT PROGRESS FOR LONGER BUILDS

For long-running implementation work, keep lightweight project state such as:

docs/IMPLEMENTATION_STATUS.md

It should record:
- Current milestone
- Completed work
- Known issues
- Next task
- Important decisions

This makes it easy for a fresh Claude Code session to resume by reading the repository instead of relying on chat history.

==================================================
RECOMMENDED REPOSITORY STRUCTURE
==================================================

Example:

bizgrips-territory-intelligence/
|
|-- CLAUDE.md
|-- README.md
|-- .env.example
|-- Makefile
|
|-- docs/
|   |-- BIZGRIPS_TERRITORY_STANDARD.md
|   |-- SCORING_SPEC.md
|   |-- DATA_DICTIONARY.md
|   |-- TERRITORY_ALGORITHM.md
|   |-- IMPLEMENTATION_STATUS.md
|
|-- app/
|   |-- api/
|   |-- models/
|   |-- services/
|   |   |-- scoring.py
|   |   |-- territory_generator.py
|   |   |-- conflict_checker.py
|   |-- repositories/
|   |-- config/
|   |-- main.py
|
|-- data/
|   |-- raw/
|   |-- processed/
|   |-- fixtures/
|
|-- scripts/
|   |-- import_census.py
|   |-- import_geography.py
|
|-- tests/
|   |-- test_scoring.py
|   |-- test_territory_generator.py
|   |-- test_conflicts.py
|   |-- fixtures/
|
|-- migrations/
|
|-- docker-compose.yml
|-- pyproject.toml

The exact structure can evolve, but keeping domain logic separate from API/UI code will make Claude Code much more effective.

==================================================
INITIAL DATABASE STRUCTURE
==================================================

TABLE 1 — ZIP / ZCTA MARKET DATA

Suggested fields:
zcta
postal_zip
city
state
latitude
longitude
geometry
total_population
total_households
owner_households
owner_occupancy_percent
owner_households_age_45_plus
owner_households_age_55_plus_optional
owner_households_age_65_plus_optional
homes_pre_2000
homes_pre_1990
homes_pre_1980
median_household_income
median_home_value
opportunity_score
market_tier
source_release
last_updated

TABLE 2 — CLIENT TERRITORIES

territory_id
client_id
client_business
starting_zip
territory_size_class
status
approved_by
reservation_date
contract_start
contract_end
release_date
notes

TABLE 3 — TERRITORY ZIP ASSIGNMENTS

territory_id
client_id
zip
status
date_assigned
date_released

TABLE 4 — SCORING CONFIGURATION

config_version
owner_household_weight
age_45_plus_weight
housing_age_weight
income_weight
serviceability_weight
small_target_min
small_target_max
standard_target_min
standard_target_max
large_target_min
large_target_max
effective_date

TABLE 5 — FUTURE ZIP PERFORMANCE

Do not require this table for V1.

Future fields:
zip
client_id
meta_spend
leads
cpl
contacts
consultations
booking_rate
show_rate
sales
close_rate
cost_per_sale
revenue
average_ticket
reporting_period

==================================================
INITIAL PRODUCT WORKFLOW
==================================================

STEP 1
Prospect enters the sales process.

STEP 2
Sales enters prospect location or starting ZIP.

STEP 3
System checks current protected and reserved territories.

STEP 4
System loads public demographic and housing intelligence.

STEP 5
System generates a recommended contiguous ZIP package.

STEP 6
System calculates:
- Owner households
- Owner households age 45+
- Housing age
- Income
- Opportunity score

STEP 7
System presents:
- Market availability
- Territory recommendation
- Supporting market statistics
- Conflicts
- Explanation

STEP 8
Human reviews recommendation.

STEP 9
If the prospect requests specific ZIPs, run the conflict checker and adjust the package.

STEP 10
Approve territory.

STEP 11
Set territory to RESERVED during sales / contracting.

STEP 12
Once the agreement is signed, set territory to ACTIVE_PROTECTED.

STEP 13
Push approved ZIP list to client records.

STEP 14
Later, use the same territory for Meta targeting.

==================================================
INITIAL MILESTONE
==================================================

DO NOT START BY BUILDING THE MAP.

The first high-value version should do one thing extremely well:

ENTER STARTING ZIP
→ CHECK AVAILABILITY
→ LOAD PUBLIC MARKET DATA
→ RETURN THE BEST CONTIGUOUS AVAILABLE TERRITORY
→ TARGET THE CONFIGURED OWNER-HOUSEHOLD OPPORTUNITY RANGE
→ PRIORITIZE OWNER HOUSEHOLDS AGE 45+
→ SHOW CONFLICTS
→ SHOW THE SALES-USEFUL MARKET DATA
→ EXPLAIN THE RECOMMENDATION
→ REQUIRE HUMAN APPROVAL

This version should require ZERO BizGrips historical performance data.

If this works reliably, the map, onboarding integrations, Meta provisioning, and future performance learning can be layered on afterward.

==================================================
IMMEDIATE NEXT STEPS BEFORE CLAUDE CODE
==================================================

1. Write BizGrips Territory Standard v1.0.
2. Define Small, Standard, and Large territory target ranges.
3. Confirm the V1 demographic variables.
4. Confirm homeowner age 45+ as the primary age variable.
5. Agree on V1 scoring weights.
6. Identify the exact Census ACS tables / variables required.
7. Choose 5–10 test markets with different characteristics.
8. Define expected behavior for each test market.
9. Create the repository.
10. Create CLAUDE.md.
11. Create the core specification documents.
12. Ask Claude Code to build Milestone 0 only.
13. Review and test.
14. Move to Milestone 1.

==================================================
LONG-TERM VISION
==================================================

The BizGrips Territory Intelligence System should ultimately become a proprietary market allocation and intelligence platform.

It should answer:
- Where can BizGrips still sell exclusivity?
- How attractive is a market for bathroom conversions?
- How large should a fair exclusive territory be?
- Which ZIPs should belong together?
- Which markets are already protected?
- Which areas should BizGrips prospect next?
- What public demographic characteristics make one bath market more attractive than another?
- Which territories are under-served?
- Later, which market characteristics correlate with BizGrips sales performance?
- Later, how should territory sizing change based on actual customer acquisition economics?

The goal is not simply to create a ZIP map.

The goal is to create a system that lets BizGrips allocate exclusive territories using measurable market opportunity, gives the sales team useful market intelligence immediately, prevents territory conflicts, stays organized as the client base grows, and eventually becomes smarter using the performance of the entire BizGrips network.
