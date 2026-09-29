"""Client-facing proposal PDF: markup content rules, rendering, and the endpoints."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_business_rules
from app.db import create_session_factory
from app.documents.brand import brand
from app.documents.brand.pdf import render_pdf
from app.fixtures import load_scenario
from app.ingest.seed import seed_scenario
from app.main import create_app
from app.services.group_evaluator import build_aggregates
from app.services.proposal_document import ProposalDocumentInput, proposal_markup

RULES = load_business_rules()
FIXTURES = Path(__file__).parent / "fixtures"
INTERNAL_TERMS = ("Opportunity Score", "Opportunity Units", "Tier A", "Tier B", "score", "tier")
FORBIDDEN = ("lead", "leads", "cost per", "guaranteed", "expected", "ROI", "revenue")


def denver_doc(client: str = "Peak Bath Solutions") -> ProposalDocumentInput:
    market = load_scenario("denver_suburban_available").market
    zips = ["80123", "80120", "80128"]
    records = [market.records[z] for z in zips]
    return ProposalDocumentInput(
        client_business_name=client,
        prepared_on=date(2026, 9, 29),
        starting_zip="80123",
        size_class="STANDARD",
        records=records,
        aggregates=build_aggregates(records, RULES),
        prepared_by="Sales Manager",
        territory_id="T-000001",
    )


def test_markup_is_client_facing_and_factual() -> None:
    markup = proposal_markup(denver_doc(), RULES)
    assert markup.startswith("---\ntitle: Exclusive Territory Proposal")
    assert "subtitle: Prepared for Peak Bath Solutions" in markup
    assert "Prepared on :: September 29, 2026" in markup
    assert "Prepared by :: Sales Manager" in markup and "Reference :: T-000001" in markup
    assert "80123 :: Littleton, CO" in markup and "80128 :: Littleton, CO" in markup
    assert "Owner-occupied households: 30,700" in markup  # 13,400 + 6,900 + 10,400
    assert "a 30-day reservation" in markup  # from business_rules.yaml
    assert "ACS 2019-2023 5-Year Estimates" not in markup  # default label when not supplied
    assert "not a forecast" in markup
    for term in INTERNAL_TERMS:
        assert term not in markup, term
    lowered = markup.lower()
    for word in FORBIDDEN:
        assert word.lower() not in lowered, word


def test_markup_never_names_other_clients_or_breaks_on_gaps() -> None:
    doc = denver_doc(client="New Prospect LLC")
    markup = proposal_markup(doc, RULES)
    assert "Peak Bath Solutions" not in markup and "Front Range Showers" not in markup
    gappy = load_scenario("missing_census_fields").market
    records = [gappy.records[z] for z in ("80123", "80124", "80126")]
    markup = proposal_markup(
        ProposalDocumentInput(
            client_business_name="Gap Aware Baths",
            prepared_on=date(2026, 9, 29),
            starting_zip="80123",
            size_class="SMALL",
            records=records,
            aggregates=build_aggregates(records, RULES),
            contiguous=False,
        ),
        RULES,
    )
    assert "more than one area" in markup and "Small territory" in markup


def test_render_pdf_embeds_brand_fonts_and_logo() -> None:
    registered, missing = brand.register_fonts()
    assert missing == [] and "Poppins" in registered and "Montserrat-Bold" in registered
    pdf = render_pdf(proposal_markup(denver_doc(), RULES))
    assert pdf.startswith(b"%PDF") and b"Poppins" in pdf and b"Montserrat" in pdf
    pages = pdf.count(b"/Type /Page") - pdf.count(b"/Type /Pages")
    assert 3 <= pages <= 5
    example = render_pdf((FIXTURES / "brand_example.md").read_text(encoding="utf-8"))
    assert example.startswith(b"%PDF")
    memo = render_pdf("# Memo\n\nPlain prose.", cover=False)
    assert memo.count(b"/Type /Page") - memo.count(b"/Type /Pages") == 1


def test_document_endpoints(engine) -> None:
    with create_session_factory(engine)() as session, session.begin():
        seed_scenario(session, load_scenario("reserved_expired"))
    with TestClient(create_app(engine=engine)) as client:
        saved = client.get(
            "/territories/T-000002/proposal.pdf", params={"as_of": "2026-09-29", "format": "md"}
        )
        assert saved.status_code == 200 and saved.headers["content-type"].startswith(
            "text/markdown"
        )
        assert "Prepared for Front Range Showers" in saved.text and "80127 ::" in saved.text
        pdf = client.get(
            "/territories/T-000002/proposal.pdf", params={"prepared_by": "Sales Manager"}
        )
        assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
        assert pdf.headers["content-disposition"].endswith(
            '"Front Range Showers - Territory Proposal.pdf"'
        )
        assert pdf.content.startswith(b"%PDF")
        assert client.get("/territories/T-000009/proposal.pdf").status_code == 404

        proposal = client.post(
            "/territories/propose", params={"as_of": "2026-09-29"},
            json={"client_name": "Late Arrival Baths", "starting_zip": "80123"},
        ).json()  # fmt: skip
        assert proposal.get("status") == "PROPOSED"
        unsaved = client.post(
            "/documents/proposal.pdf",
            params={"as_of": "2026-09-29", "format": "md"},
            json={"proposal": proposal, "client_business_name": "Late Arrival Baths"},
        )
        assert unsaved.status_code == 200
        assert "Front Range Showers" not in unsaved.text  # the blocked ZIP's holder stays internal
        assert "80127" not in unsaved.text  # the reserved ZIP is not part of the proposal
        failed = dict(proposal, status="FAILED", zips=[])
        rejected = client.post(
            "/documents/proposal.pdf", json={"proposal": failed, "client_business_name": "X"}
        )
        assert rejected.status_code == 422
