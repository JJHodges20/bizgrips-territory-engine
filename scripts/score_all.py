"""Score every ZCTA in the database and cache the results (Milestone 3).

    venv/Scripts/python.exe scripts/score_all.py [--dry-run] [--database-url URL]

Loads app/config/business_rules.yaml, scores each zcta_markets row with
app.services.scoring.score_zcta (pure, deterministic), writes opportunity_score, market_tier,
opportunity_units, score_config_version and scored_at back, and snapshots the rules version in
scoring_configs so historical scores can be reproduced. Re-run after any import or rules change.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_business_rules  # noqa: E402
from app.db import create_db_engine, create_session_factory, init_db  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.repositories.scoring import (  # noqa: E402
    all_market_records,
    record_scoring_config,
    write_score_cache,
)
from app.services.scoring import score_zcta  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--database-url", default=None, help="override DATABASE_URL")
    parser.add_argument("--dry-run", action="store_true", help="score and report, write nothing")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    rules = load_business_rules()
    engine = create_db_engine(args.database_url)
    init_db(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        records = all_market_records(session)
        scores = [score_zcta(record, rules) for record in records]
        tiers = Counter(score.tier for score in scores)
        reasons = Counter(score.unscored_reason for score in scores if score.unscored_reason)
        partial = sum(1 for s in scores if s.score is not None and s.missing_components)
        ou_missing = sum(1 for s in scores if s.opportunity_units is None)
        total_ou = sum(s.opportunity_units or 0.0 for s in scores)
        elapsed = time.perf_counter() - started
        print(f"Scored {len(scores):,} ZCTAs with rules {rules.version} ({elapsed:.1f}s)")
        print(
            "  tiers: "
            + ", ".join(
                f"{t}={tiers[t]:,}"
                for t in (*rules.scoring.tier_order, rules.scoring.unscored_tier)
            )
        )
        print(
            "  unscored reasons: "
            + (", ".join(f"{r}={n:,}" for r, n in reasons.most_common()) or "none")
        )
        print(f"  scored with missing components (renormalised): {partial:,}")
        print(f"  opportunity units: total {total_ou:,.0f}; ZCTAs without OU: {ou_missing:,}")
        if args.dry_run:
            print("Dry run: nothing written.")
            engine.dispose()
            return 0
        snapshot = record_scoring_config(session, rules)
        written = write_score_cache(
            session, scores, config_version=rules.version, scored_at=utcnow()
        )
        session.commit()
    engine.dispose()
    print(f"Cached {written:,} rows; scoring_configs has version {snapshot.config_version}")
    print(f"Done in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
