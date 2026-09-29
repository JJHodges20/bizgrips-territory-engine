"""Client-facing proposal documents (PDF) for saved territories and unsaved proposals."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from fastapi import APIRouter, Path, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import SessionDep
from app.api.territories import make_service
from app.config import get_business_rules
from app.config.census_variables import get_census_variables
from app.documents.brand.pdf import render_pdf
from app.repositories.markets import get_markets, neighbour_zctas
from app.schemas.territory import TerritoryProposal
from app.services.group_evaluator import build_aggregates
from app.services.market import connected_components
from app.services.proposal_document import ProposalDocumentInput, proposal_markup
from app.services.registry import InvalidProposal

router = APIRouter(tags=["documents"])
AS_OF = Query(None, description="date printed on the document; defaults to today (UTC)")
FORMAT = Query("pdf", pattern=r"^(pdf|md)$", description="pdf, or md for the source markup")


class ProposalDocumentRequest(BaseModel):
    proposal: TerritoryProposal
    client_business_name: str = Field(min_length=1, max_length=200)
    prepared_by: str | None = Field(default=None, max_length=120)


def filename_for(client: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9 _-]+", "", client).strip() or "Client"
    return f"{safe} - Territory Proposal.pdf"


def build_markup(
    session: Session,
    *,
    zips: list[str],
    starting_zip: str,
    size_class: str,
    client: str,
    prepared_on: date,
    prepared_by: str | None,
    territory_id: str | None,
) -> str:
    rules = get_business_rules()
    by_code = get_markets(session, zips)
    records = [by_code[z] for z in zips if z in by_code]
    if not records:
        raise InvalidProposal("NO_MARKET_DATA", "none of the territory's ZIPs has market data")
    adjacency = {r.zcta: frozenset(neighbour_zctas(session, r.zcta)) for r in records}
    contiguous = len(connected_components([r.zcta for r in records], adjacency)) <= 1
    payload = ProposalDocumentInput(
        client_business_name=client,
        prepared_on=prepared_on,
        starting_zip=starting_zip if starting_zip in by_code else records[0].zcta,
        size_class=size_class,
        records=records,
        aggregates=build_aggregates(records, rules),
        contiguous=contiguous,
        release_label=get_census_variables().release_label,
        prepared_by=prepared_by,
        territory_id=territory_id,
    )
    return proposal_markup(payload, rules)


def respond(markup: str, client: str, fmt: str) -> Response:
    if fmt == "md":
        return PlainTextResponse(markup, media_type="text/markdown; charset=utf-8")
    return Response(
        render_pdf(markup),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename_for(client)}"'},
    )


@router.get("/territories/{territory_id}/proposal.pdf")
def territory_proposal_pdf(
    session: SessionDep,
    territory_id: str = Path(pattern=r"^T-\d{6}$"),
    as_of: date | None = AS_OF,
    prepared_by: str | None = Query(None, max_length=120),
    format: str = FORMAT,
) -> Response:
    """Branded, client-facing proposal for a saved territory.

    Public-data facts and the ZIP list only: no scores, tiers, Opportunity Units or other
    clients' names ever appear in it.
    """
    effective = as_of or datetime.now(UTC).date()
    record = make_service(session, effective).get(territory_id)
    markup = build_markup(
        session,
        zips=record.zips,
        starting_zip=record.starting_zip,
        size_class=record.territory_size_class.value,
        client=record.client_business_name,
        prepared_on=effective,
        prepared_by=prepared_by,
        territory_id=record.territory_id,
    )
    return respond(markup, record.client_business_name, format)


@router.post("/documents/proposal.pdf")
def proposal_pdf(
    session: SessionDep,
    body: ProposalDocumentRequest,
    as_of: date | None = AS_OF,
    format: str = FORMAT,
) -> Response:
    """The same document for a proposal that has not been saved yet (sales check, map)."""
    proposal = body.proposal
    if proposal.status != "PROPOSED" or not proposal.zips:
        raise InvalidProposal("NOT_A_PROPOSAL", "only a PROPOSED territory can be documented")
    effective = as_of or datetime.now(UTC).date()
    markup = build_markup(
        session,
        zips=proposal.zip_codes,
        starting_zip=proposal.starting_zip,
        size_class=proposal.size_class.value,
        client=body.client_business_name,
        prepared_on=effective,
        prepared_by=body.prepared_by,
        territory_id=proposal.territory_id,
    )
    return respond(markup, body.client_business_name, format)
