"""Client-facing territory proposal: data -> BizGrips document markup (rendered by
app.documents.brand.pdf). Positive and professional, facts only, never another client's name,
never internal scores, tiers or Opportunity Units, never a performance claim."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.config.business_rules import BusinessRules
from app.schemas.market import ZctaRecord
from app.schemas.territory import ProposalAggregates

FOOTER = "BizGrips · Customer Acquisition Systems for Bath Conversion Companies"
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico",
}  # fmt: skip


@dataclass(frozen=True)
class ProposalDocumentInput:
    client_business_name: str
    prepared_on: date
    starting_zip: str
    size_class: str  # SMALL / STANDARD / LARGE
    records: list[ZctaRecord]  # the territory's ZCTAs, in proposal order
    aggregates: ProposalAggregates
    contiguous: bool = True
    release_label: str = "American Community Survey 5-Year Estimates"
    prepared_by: str | None = None
    territory_id: str | None = None
    notes: list[str] = field(default_factory=list)


def _int(n: float | int | None) -> str:
    return "n/a" if n is None else f"{int(round(n)):,}"


def _pct(numerator: int | None, denominator: int | None) -> str:
    if not numerator or not denominator:
        return "n/a"
    return f"{numerator / denominator:.0%}"


def _place(record: ZctaRecord) -> str:
    city = record.primary_city or "ZIP area"
    return f"{city}, {record.state}" if record.state else city


def _states(records: list[ZctaRecord]) -> str:
    codes = sorted({r.state for r in records if r.state})
    names = [STATE_NAMES.get(c, c) for c in codes]
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + f" and {names[-1]}"


def _housing_phrase(share: float | None) -> str:
    if share is None:
        return "a housing stock"
    if share >= 0.75:
        return "a well-established housing stock"
    if share >= 0.5:
        return "a mature housing stock"
    return "a mix of established and newer neighborhoods"


def _date(value: date) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def proposal_markup(doc: ProposalDocumentInput, rules: BusinessRules) -> str:
    """Build the document markup understood by app.documents.brand (SKILL.md dialect)."""
    a = doc.aggregates
    start = next((r for r in doc.records if r.zcta == doc.starting_zip), doc.records[0])
    n = len(doc.records)
    plural = "s" if n != 1 else ""
    units = a.total_housing_units
    pre_2000 = a.homes_built_before_2000 / units if units else None
    size_word = doc.size_class.lower()
    days = rules.registry.reservation_days
    client = doc.client_business_name
    owners, owners_45 = a.owner_occupied_households, a.owner_households_age_45_plus

    intro_1 = (
        f"We have mapped a {size_word} territory of {n} ZIP code{plural} around {_place(start)} "
        f"for {client}: about {_int(owners)} owner-occupied households, {_int(owners_45)} of them "
        f"with a householder age 45 or older, in {_housing_phrase(pre_2000)}."
    )
    intro_2 = (
        "Every ZIP code in this proposal is currently available, and once reserved it is "
        f"protected for {client} alone. The pages that follow show what the territory covers, "
        "why we believe it is a strong fit, and how to secure it."
    )
    contiguity = (
        "Every ZIP code connects to the others, so your marketing footprint is one continuous area."
        if doc.contiguous
        else "The ZIP codes form more than one area; your BizGrips contact will walk you through "
        "the layout."
    )
    lines: list[str] = [
        "---",
        "title: Exclusive Territory Proposal",
        f"subtitle: Prepared for {client}",
        "header: Territory Proposal",
        f"footer: {FOOTER}",
        "intro: |",
        f"  {intro_1}",
        f"  {intro_2}",
        "---",
        "",
        "^ YOUR TERRITORY",
        "# Territory overview",
        "",
        f"Prepared for :: {client}",
        f"Prepared on :: {_date(doc.prepared_on)}",
    ]
    if doc.prepared_by:
        lines.append(f"Prepared by :: {doc.prepared_by}")
    if doc.territory_id:
        lines.append(f"Reference :: {doc.territory_id}")
    lines += [
        f"Starting area :: {doc.starting_zip} · {_place(start)}",
        f"Territory size :: {n} ZIP code{plural} · {size_word.title()} territory",
        f"Coverage :: {_int(a.land_area_sq_miles)} square miles in {_states(doc.records)}",
        f"Contiguity :: {contiguity}",
        "",
        "^ WHY THIS MARKET",
        "# Market highlights",
        "",
        "## 01 A large base of homeowners",
        f"Bath conversion demand starts with homeowners, and this territory has {_int(owners)} "
        f"owner-occupied households. {_int(owners_45)} of them ({_pct(owners_45, owners)}) have a "
        "householder age 45 or older, the age range that most often invests in accessible, "
        "updated bathrooms.",
        "",
        f"- Owner-occupied households: {_int(owners)}",
        f"- Households with a householder age 45 or older: {_int(owners_45)}",
        f"- Households with a householder age 65 or older: {_int(a.owner_households_age_65_plus)}",
        "",
        "## 02 Established housing stock",
        f"{_pct(a.homes_built_before_2000, units)} of the homes in this territory were built "
        "before 2000, so many bathrooms are reaching the age at which homeowners replace tubs, "
        "showers and surrounds.",
        "",
        f"- Built before 2000: {_pct(a.homes_built_before_2000, units)}",
        f"- Built before 1990: {_pct(a.homes_built_before_1990, units)}",
        f"- Built before 1980: {_pct(a.homes_built_before_1980, units)}",
        "",
        "## 03 Purchasing power",
        "The household-weighted median household income across the territory is "
        f"${_int(a.median_household_income)}, supporting projects that are financed as well as "
        "paid outright.",
        "",
        "^ THE ZIP CODES",
        "# What is included",
        "",
    ]
    for r in doc.records:
        lines.append(
            f"{r.zcta} :: {_place(r)} — {_int(r.owner_occupied_households)} owner-occupied "
            f"households, {_int(r.owner_households_age_45_plus)} age 45 or older"
        )
    lines += [
        "",
        "::: green | EXCLUSIVITY",
        f"Once reserved, these ZIP codes are protected for {client}: BizGrips will not provision "
        "them for another bath conversion client for the term of your agreement.",
        f"- A reservation holds the territory exclusively for {days} days while the agreement is "
        "completed.",
        "- Signing the agreement activates full protection for its term.",
        ":::",
        "",
        "::: blue | HOW WE BUILT THIS TERRITORY",
        "BizGrips maps every ZIP code in the country with public U.S. Census data. Starting from "
        "your location, we add neighboring ZIP codes that are available and practical to serve, "
        "and stop when the territory holds a comparable amount of homeowner opportunity to every "
        "other BizGrips territory of its size. A BizGrips team member reviews and approves each "
        "territory before it is reserved.",
        ":::",
        "",
        "^ NEXT STEPS",
        "# Securing your territory",
        "",
        "1. Review the ZIP codes with your BizGrips contact and request any adjustments.",
        f"2. Reserve the territory: a {days}-day reservation holds it exclusively while the "
        "agreement is finalized.",
        "3. Sign the agreement to activate protection for its full term.",
        "4. Launch your customer acquisition system in a market that is yours alone.",
        "",
    ]
    for note in doc.notes:
        lines += [note, ""]
    lines += [
        "::: grey | ABOUT THE FIGURES",
        "Household, homeowner, housing-age and income figures are estimates from the U.S. Census "
        f"Bureau's {doc.release_label} for the ZIP Code Tabulation Areas that make up this "
        "territory. They describe the market as measured by the Census Bureau and are not a "
        "forecast of marketing results.",
        ":::",
        "",
    ]
    return "\n".join(lines)
