"""Calibration report: where the V1 ramps sit against the imported ACS distribution (M3).

    venv/Scripts/python.exe scripts/calibration_report.py [--output docs/CALIBRATION_REPORT.md]

For every scoring metric it reports percentiles over scorable ZCTAs, the share of ZCTAs the
ramp pins to 0 or 100, the resulting component and total score distributions, the tier mix and
Opportunity Unit percentiles. It changes nothing; ramps are adjusted in business_rules.yaml.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_business_rules, load_census_variables  # noqa: E402
from app.config.business_rules import COMPONENT_NAMES, BusinessRules  # noqa: E402
from app.db import create_db_engine, create_session_factory  # noqa: E402
from app.repositories.scoring import all_market_records  # noqa: E402
from app.schemas.market import ZctaRecord  # noqa: E402
from app.services.scoring import ramp_score, score_zcta  # noqa: E402

PERCENTILES = (5, 10, 25, 50, 75, 90, 95)


def percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return float("nan")
    index = min(len(sorted_values) - 1, max(0, round(pct / 100 * (len(sorted_values) - 1))))
    return sorted_values[index]


def fmt(value: float, metric: str) -> str:
    if metric in ("median_household_income", "households_per_sq_mile"):
        return f"{value:,.0f}"
    return f"{value:.3f}"


def build_report(records: list[ZctaRecord], rules: BusinessRules, vintage: int) -> str:
    scorable = [
        r for r in records if (r.total_households or 0) >= rules.scoring.min_households_for_scoring
    ]
    lines = [
        "# Calibration Report",
        "",
        f"Generated {datetime.now(UTC).date().isoformat()} from ACS 5-Year vintage {vintage} "
        f"with business rules {rules.version}. {len(records):,} ZCTAs in the database, "
        f"{len(scorable):,} with at least {rules.scoring.min_households_for_scoring} households "
        "(the population below). Nothing here changes a rule; edit `business_rules.yaml`.",
        "",
        "## 1. Metric percentiles versus ramp floors and ceilings",
        "",
        "| Component | Metric | "
        + " | ".join(f"p{p}" for p in PERCENTILES)
        + " | Floor (scores 0) | Ceiling (scores 100) | Below floor | Above ceiling | Missing |",
        "|---|---|" + "---|" * len(PERCENTILES) + "---|---|---|---|---|",
    ]
    component_values: dict[str, list[float]] = {}
    for name in COMPONENT_NAMES:
        ramp = rules.scoring.components.get(name)
        values = [r.metric(ramp.metric) for r in scorable]
        present = sorted(v for v in values if v is not None)
        missing = len(values) - len(present)
        below = sum(1 for v in present if v <= ramp.floor)
        above = sum(1 for v in present if v >= ramp.ceiling)
        component_values[name] = [ramp_score(v, ramp) for v in present]  # type: ignore[misc]
        cells = [fmt(percentile(present, p), ramp.metric) for p in PERCENTILES]
        lines.append(
            f"| {name} | {ramp.metric} ({ramp.scale}) | "
            + " | ".join(cells)
            + f" | {fmt(ramp.floor, ramp.metric)} | {fmt(ramp.ceiling, ramp.metric)}"
            + f" | {below / len(present):.1%} | {above / len(present):.1%} | {missing:,} |"
        )
    lines += [
        "",
        "## 2. Component score percentiles (0-100)",
        "",
        "| Component | " + " | ".join(f"p{p}" for p in PERCENTILES) + " | Mean |",
        "|---|" + "---|" * (len(PERCENTILES) + 1),
    ]
    for name, comp in component_values.items():
        ordered = sorted(comp)
        mean = sum(ordered) / len(ordered) if ordered else float("nan")
        lines.append(
            f"| {name} | "
            + " | ".join(f"{percentile(ordered, p):.1f}" for p in PERCENTILES)
            + f" | {mean:.1f} |"
        )

    scores = [score_zcta(r, rules) for r in records]
    scored = sorted(s.score for s in scores if s.score is not None)
    tiers = Counter(s.tier for s in scores)
    reasons = Counter(s.unscored_reason for s in scores if s.unscored_reason)
    lines += [
        "",
        "## 3. Opportunity Score distribution",
        "",
        "| " + " | ".join(f"p{p}" for p in PERCENTILES) + " | Mean |",
        "|" + "---|" * (len(PERCENTILES) + 1),
        "| "
        + " | ".join(f"{percentile(scored, p):.1f}" for p in PERCENTILES)
        + f" | {sum(scored) / len(scored):.1f} |"
        if scored
        else "| no scored ZCTAs |",
        "",
        "| Tier | ZCTAs | Share |",
        "|---|---|---|",
    ]
    for tier in (*rules.scoring.tier_order, rules.scoring.unscored_tier):
        lines.append(f"| {tier} | {tiers[tier]:,} | {tiers[tier] / len(scores):.1%} |")
    lines += [
        "",
        "Unscored reasons: "
        + (", ".join(f"{r} {n:,}" for r, n in reasons.most_common()) or "none")
        + ".",
    ]

    ou = sorted(s.opportunity_units for s in scores if s.opportunity_units is not None)
    lines += [
        "",
        "## 4. Opportunity Units per ZCTA",
        "",
        "| " + " | ".join(f"p{p}" for p in PERCENTILES) + " | Total | ZCTAs with OU |",
        "|" + "---|" * (len(PERCENTILES) + 2),
        "| "
        + " | ".join(f"{percentile(ou, p):,.0f}" for p in PERCENTILES)
        + f" | {sum(ou):,.0f} | {len(ou):,} |",
    ]
    bands = rules.territory_sizes.bands
    median_ou = percentile(ou, 50) if ou else float("nan")
    lines += [
        "",
        f"At the median ZCTA ({median_ou:,.0f} OU) a Standard territory "
        f"({bands.standard.target_min:,.0f}-{bands.standard.target_max:,.0f} OU) needs about "
        f"{bands.standard.target_min / median_ou:.0f}-{bands.standard.target_max / median_ou:.0f} "
        "median ZCTAs; suburban ZCTAs in the top quartile need fewer.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--output", default="docs/CALIBRATION_REPORT.md")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    rules = load_business_rules()
    vintage = load_census_variables().vintage
    engine = create_db_engine(args.database_url)
    with create_session_factory(engine)() as session:
        records = all_market_records(session)
    engine.dispose()
    report = build_report(records, rules, vintage)
    Path(args.output).write_text(report, encoding="utf-8")
    print(report)
    print(f"Written to {args.output} in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
