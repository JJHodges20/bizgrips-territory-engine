"""scripts/score_all.py caches scores with a config snapshot; /zctas/{zcta}/score is live."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import load_business_rules
from app.db import create_db_engine, create_session_factory, init_db
from app.fixtures import load_scenario
from app.ingest.seed import seed_scenario
from app.main import create_app
from app.models import ScoringConfig, ZctaMarket

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "score_all.py"


def seeded_file_db(tmp_path: Path) -> str:
    url = f"sqlite:///{(tmp_path / 'score.db').as_posix()}"
    engine = create_db_engine(url)
    init_db(engine)
    with create_session_factory(engine)() as session, session.begin():
        seed_scenario(session, load_scenario("denver_suburban_available"))
    engine.dispose()
    return url


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=ROOT, capture_output=True, text=True, check=False
    )


def test_score_all_caches_scores_and_snapshots_rules(tmp_path: Path) -> None:
    url = seeded_file_db(tmp_path)
    dry = run_script("--database-url", url, "--dry-run")
    assert dry.returncode == 0 and "Dry run" in dry.stdout, dry.stderr
    engine = create_db_engine(url)
    with create_session_factory(engine)() as session:
        assert session.get(ZctaMarket, "80123").market_tier is None
    result = run_script("--database-url", url)
    assert result.returncode == 0, result.stderr
    assert "Scored 12 ZCTAs" in result.stdout and "Cached 12 rows" in result.stdout
    rules = load_business_rules()
    with create_session_factory(engine)() as session:
        row = session.get(ZctaMarket, "80123")
        assert (row.opportunity_score, row.market_tier, row.opportunity_units) == (
            75.8,
            "A",
            7299.0,
        )
        assert row.score_config_version == rules.version and row.scored_at is not None
        tiers = set(session.scalars(select(ZctaMarket.market_tier)))
        assert None not in tiers and tiers <= {"A", "B", "C", "D", "U"}
        snapshot = session.get(ScoringConfig, rules.version)
        assert snapshot is not None and snapshot.owner_household_weight == 0.35
    engine.dispose()
    again = run_script("--database-url", url)  # idempotent: same version, same cache
    assert again.returncode == 0 and "Cached 12 rows" in again.stdout


def test_score_endpoint_is_live_and_reports_cache(engine) -> None:
    with create_session_factory(engine)() as session, session.begin():
        seed_scenario(session, load_scenario("denver_suburban_available"))
    with TestClient(create_app(engine=engine)) as client:
        body = client.get("/zctas/80123/score").json()
        assert (body["score"], body["tier"], body["opportunity_units"]) == (75.8, "A", 7299.0)
        assert body["components"]["purchasing_power"]["score"] == 85.0
        assert body["cached"]["market_tier"] is None  # score_all has not run on this database
        assert "not a prediction" in body["disclaimer"]
        assert client.get("/zctas/00000/score").status_code == 404
        assert client.get("/zctas/12/score").status_code == 422
