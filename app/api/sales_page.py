"""Server-rendered internal sales page: one input box, the full market view. No JavaScript."""

from __future__ import annotations

from html import escape

from app.schemas.market_check import MarketCheck

_CSS = """
body{font-family:system-ui,Segoe UI,Arial,sans-serif;margin:2rem auto;max-width:960px;
padding:0 1rem;color:#1b1b1b}
h1{font-size:1.4rem}h2{font-size:1.1rem;margin-top:1.6rem}
form{display:flex;gap:.5rem;flex-wrap:wrap;margin:1rem 0}
input[type=text]{flex:1;min-width:16rem;padding:.5rem;font-size:1rem}
select,button{padding:.5rem;font-size:1rem}
.badge{display:inline-block;padding:.3rem .7rem;border-radius:.4rem;font-weight:600;color:#fff}
.AVAILABLE{background:#1f7a3a}.PARTIALLY_AVAILABLE{background:#b7791f}
.UNAVAILABLE{background:#b42318}.NO_MARKET_DATA{background:#555}
table{border-collapse:collapse;width:100%;font-size:.95rem}
th,td{border-bottom:1px solid #ddd;padding:.35rem .5rem;text-align:left}
th{background:#f4f4f4}.muted{color:#666;font-size:.9rem}.err{color:#b42318}
ul.points li{margin:.35rem 0}
"""


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.0f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def _num(value: float | None) -> str:
    return "n/a" if value is None else f"{value}"


def _entries(title: str, entries: list, extra: str) -> str:
    if not entries:
        return ""
    rows = "".join(
        f"<tr><td>{escape(e.zcta)}</td><td>{escape(e.status.value)}</td>"
        f"<td>{escape(e.client_business_name)}</td><td>{escape(e.territory_id)}</td>"
        f"<td>{escape(str(getattr(e, extra) or ''))}</td></tr>"
        for e in entries
    )
    return (
        f"<h2>{escape(title)} <span class='muted'>(client names: internal use only)</span></h2>"
        f"<table><tr><th>ZIP</th><th>Status</th><th>Client</th><th>Territory</th>"
        f"<th>{escape(extra.replace('_', ' '))}</th></tr>{rows}</table>"
    )


def render_sales_page(q: str, check: MarketCheck | None, error: str | None) -> str:
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>BizGrips Market Check</title><style>{_CSS}</style></head><body>",
        "<h1>BizGrips Market Check <span class='muted'>internal</span></h1>",
        "<form method='get' action='/sales'>",
        f"<input type='text' name='q' value='{escape(q, quote=True)}' "
        "placeholder='ZIP, a list of ZIPs, or City, ST' autofocus>",
        "<select name='size_class'><option value=''>Standard (default)</option>"
        "<option value='SMALL'>Small</option><option value='STANDARD'>Standard</option>"
        "<option value='LARGE'>Large</option></select>",
        "<button type='submit'>Check market</button></form>",
    ]
    if error:
        parts.append(f"<p class='err'>{escape(error)}</p>")
    if check is not None:
        parts.append(render_check(check))
    parts.append("</body></html>")
    return "".join(parts)


def render_check(check: MarketCheck) -> str:
    label = escape(check.market_availability.replace("_", " "))
    out = [
        f"<p><span class='badge {check.market_availability}'>{label}</span> "
        f"<span class='muted'>as of {check.as_of.isoformat()}, rules "
        f"{escape(check.rules_version)}. {escape(check.resolution.note)}</span></p>",
        "<h2>Talking points</h2><ul class='points'>"
        + "".join(f"<li>{escape(p)}</li>" for p in check.talking_points)
        + "</ul>",
    ]
    stats = check.market_stats
    if stats is not None:
        out.append(
            "<h2>Market statistics</h2><table>"
            f"<tr><th>ZIPs</th><td>{stats.zcta_count}</td>"
            f"<th>Households</th><td>{stats.total_households:,}</td></tr>"
            f"<tr><th>Owner households</th><td>{stats.owner_occupied_households:,}</td>"
            f"<th>Owner households 45+</th><td>{stats.owner_households_age_45_plus:,}</td></tr>"
            f"<tr><th>Built before 2000 / 1990 / 1980</th><td>{_pct(stats.pre_2000_share)} / "
            f"{_pct(stats.pre_1990_share)} / {_pct(stats.pre_1980_share)}</td>"
            f"<th>Median household income</th><td>{_money(stats.median_household_income)}</td></tr>"
            f"<tr><th>Opportunity Score / Tier</th><td>{_num(stats.opportunity_score)} / "
            f"{escape(stats.market_tier)}</td>"
            f"<th>Opportunity Units</th><td>{stats.opportunity_units:,.0f}</td></tr></table>"
        )
    proposal = check.suggested_territory
    if proposal is not None:
        rows = "".join(
            f"<tr><td>{z.order}</td><td>{escape(z.zcta)}</td><td>{escape(z.state or '')}</td>"
            f"<td>{escape(z.reason)}</td><td>{escape(z.tier)}</td><td>{_num(z.score)}</td>"
            f"<td>{(z.opportunity_units or 0):,.0f}</td><td>{z.miles_from_start:.1f}</td></tr>"
            for z in proposal.zips
        )
        target = proposal.target.status.replace("_", " ") if proposal.target else ""
        flags = ", ".join(escape(f) for f in proposal.flags)
        out.append(
            f"<h2>Suggested territory <span class='muted'>{len(proposal.zips)} ZIPs, "
            f"{escape(target)}, {flags}</span></h2>"
            "<table><tr><th>#</th><th>ZIP</th><th>State</th><th>Reason</th><th>Tier</th>"
            f"<th>Score</th><th>OU</th><th>Miles</th></tr>{rows}</table>"
        )
        if proposal.excluded:
            excluded = "; ".join(f"{escape(e.zcta)} {escape(e.reason)}" for e in proposal.excluded)
            out.append(f"<p class='muted'>Excluded: {excluded}</p>")
    out.append(_entries("Reserved ZIPs", check.reserved_zips, "expires_at"))
    out.append(_entries("Protected ZIPs", check.protected_zips, "contract_end_date"))
    out.append(_entries("Pending release", check.pending_release_zips, "release_date"))
    if check.replacement_zips:
        rows = "".join(
            f"<tr><td>{escape(s.for_zcta)}</td><td>{escape(s.zcta)}</td><td>{s.miles:.1f}</td>"
            f"<td>{escape(s.tier)}</td><td>{_num(s.score)}</td></tr>"
            for s in check.replacement_zips
        )
        out.append(
            "<h2>Nearby replacement ZIPs</h2><table><tr><th>For</th><th>ZIP</th><th>Miles</th>"
            f"<th>Tier</th><th>Score</th></tr>{rows}</table>"
        )
    if check.available_zips:
        out.append(
            f"<p class='muted'>Available ZIPs: {escape(', '.join(check.available_zips))}</p>"
        )
    out.append(f"<p class='muted'>{escape(check.disclaimer)}</p>")
    return "".join(out)
