// Sales check view: one input, the full market view from POST /market/check.

import { api } from "./api.js";
import { badge, clear, context, el, emptyState, errorMessage, flagEl, fmt, formModal, loading, statusBadge, tierBadge, toast } from "./ui.js";

let results = null;
let prospectNode = null;

function prospectLabel() {
  const id = context().client_id;
  return id ? `${id} (from the header)` : "none set (add a client id in the header to treat its own ZIPs as available)";
}

export function parseInput(text) {
  const trimmed = (text || "").trim();
  if (!trimmed) return null;
  const codes = trimmed.match(/\d{5}/g) || [];
  if (codes.length && !trimmed.replace(/[\d\s,;]/g, "")) {
    const unique = Array.from(new Set(codes));
    return unique.length === 1 ? { starting_zip: unique[0] } : { requested_zips: unique };
  }
  const parts = trimmed.split(",").map((p) => p.trim()).filter(Boolean);
  if (parts.length >= 2 && /^[A-Za-z]{2}$/.test(parts[parts.length - 1])) {
    return { city: parts.slice(0, -1).join(", "), state: parts[parts.length - 1].toUpperCase() };
  }
  return null;
}

function stat(label, value, sub) {
  return el("div", { class: "stat" }, el("div", { class: "label" }, label), el("div", { class: "value" }, value), sub ? el("div", { class: "sub" }, sub) : null);
}

function table(headers, rows) {
  return el("div", { class: "table-wrap" }, el("table", { class: "table" },
    el("thead", {}, el("tr", {}, headers.map((h) => el("th", { class: h.num ? "num" : "" }, h.label)))),
    el("tbody", {}, rows)));
}

function heldTable(title, entries, extraKey) {
  if (!entries || !entries.length) return null;
  const headers = ["ZIP", "Status", "Client", "Territory", fmt.words(extraKey)].map((label) => ({ label }));
  const rows = entries.map((e) => el("tr", {}, el("td", { class: "mono" }, e.zcta), el("td", {}, statusBadge(e.status)),
    el("td", {}, e.client_business_name), el("td", { class: "mono" }, e.territory_id), el("td", {}, fmt.date(e[extraKey]))));
  return el("div", { class: "card" }, el("div", { class: "card-head" }, el("h2", {}, title), el("span", { class: "muted" }, "client names: internal use only")), table(headers, rows));
}

function render(check) {
  clear(results);
  const stats = check.market_stats;
  const proposal = check.suggested_territory;
  results.appendChild(el("div", { class: "avail-banner" }, badge(fmt.words(check.market_availability), check.market_availability),
    el("div", {}, el("div", {}, check.resolution.note), el("div", { class: "muted" }, `as of ${check.as_of} · rules ${check.rules_version} · a named approver must reserve any territory`))));
  results.appendChild(el("div", { class: "card" }, el("div", { class: "card-head" }, el("h2", {}, "Talking points"), el("span", { class: "muted" }, "public-data facts only")),
    el("div", { class: "card-body" }, el("ul", { class: "points" }, check.talking_points.map((p) => el("li", {}, p))))));
  if (stats) {
    const n = stats.zcta_count;
    results.appendChild(el("div", { class: "stat-grid" },
      stat("Owner households", fmt.int(stats.owner_occupied_households), `${n} ZIP${n === 1 ? "" : "s"} · ${fmt.int(stats.total_households)} households`),
      stat("Owner households 45+", fmt.int(stats.owner_households_age_45_plus), `55+: ${fmt.int(stats.owner_households_age_55_plus)} · 65+: ${fmt.int(stats.owner_households_age_65_plus)}`),
      stat("Built before 2000", fmt.pct(stats.pre_2000_share), `before 1990: ${fmt.pct(stats.pre_1990_share)} · before 1980: ${fmt.pct(stats.pre_1980_share)}`),
      stat("Median household income", fmt.money(stats.median_household_income), "household-weighted"),
      stat("Opportunity Score", stats.opportunity_score === null ? "n/a" : fmt.num(stats.opportunity_score, 1), tierBadge(stats.market_tier)),
      stat("Opportunity Units", fmt.int(stats.opportunity_units), `${fmt.num(stats.land_area_sq_miles, 0)} sq mi`)));
  }
  if (proposal) {
    const zips = proposal.zips.map((z) => z.zcta);
    const headers = ["#", "ZIP", "State", "Reason", "Tier", "Score", "OU", "Miles"].map((label, i) => ({ label, num: i >= 5 }));
    const rows = proposal.zips.map((z) => el("tr", {}, el("td", {}, String(z.order)), el("td", { class: "mono" }, z.zcta), el("td", {}, z.state || ""),
      el("td", {}, fmt.words(z.reason)), el("td", {}, tierBadge(z.tier)), el("td", { class: "num" }, fmt.num(z.score, 1)),
      el("td", { class: "num" }, fmt.int(z.opportunity_units)), el("td", { class: "num" }, fmt.num(z.miles_from_start, 1))));
    results.appendChild(el("div", { class: "card" },
      el("div", { class: "card-head" },
        el("div", {}, el("h2", {}, `Suggested territory · ${zips.length} ZIPs`), el("div", { class: "row", style: "margin-top:6px" }, proposal.flags.map(flagEl))),
        el("div", { class: "row" },
          el("button", { class: "btn btn-sm", type: "button", onClick: () => window.bgGo("map", { zips: zips.join(",") }) }, "Show on map"),
          el("button", { class: "btn btn-sm btn-primary", type: "button", onClick: () => saveProposal(check, zips) }, "Save as proposal"))),
      table(headers, rows),
      proposal.excluded.length ? el("div", { class: "card-body muted" }, "Excluded: " + proposal.excluded.map((e) => `${e.zcta} ${fmt.words(e.reason)}`).join("; ")) : null));
  }
  [heldTable("Reserved ZIPs", check.reserved_zips, "expires_at"), heldTable("Protected ZIPs", check.protected_zips, "contract_end_date"),
    heldTable("Pending release", check.pending_release_zips, "release_date")].forEach((node) => { if (node) results.appendChild(node); });
  if (check.replacement_zips.length) {
    const headers = ["For", "ZIP", "Miles", "Tier", "Score"].map((label) => ({ label }));
    const rows = check.replacement_zips.map((s) => el("tr", {}, el("td", { class: "mono" }, s.for_zcta), el("td", { class: "mono" }, s.zcta), el("td", {}, fmt.num(s.miles, 1)), el("td", {}, tierBadge(s.tier)), el("td", {}, fmt.num(s.score, 1))));
    results.appendChild(el("div", { class: "card" }, el("div", { class: "card-head" }, el("h2", {}, "Nearby replacement ZIPs")), table(headers, rows)));
  }
  results.appendChild(el("p", { class: "muted" }, check.disclaimer));
}

async function saveProposal(check, zips) {
  const ctx = context();
  const values = await formModal({ title: "Save as PROPOSED territory", submitLabel: "Create proposal", intro: "Creates a PROPOSED record. A named approver must still reserve it.", fields: [
    { name: "client_id", label: "Client id", required: true, value: ctx.client_id || "" },
    { name: "client_business_name", label: "Business name", required: true, value: check.query.client_name !== "Prospect" ? check.query.client_name : "" },
    { name: "notes", label: "Notes", type: "textarea", span2: true, placeholder: "optional" },
  ] });
  if (!values) return;
  try {
    const territory = await api.createTerritory({ client_id: values.client_id, client_business_name: values.client_business_name, starting_zip: check.suggested_territory.starting_zip,
      territory_size_class: check.suggested_territory.size_class, zips, notes: values.notes, generation_snapshot: check.suggested_territory }, { as_of: ctx.as_of });
    toast(`Created ${territory.territory_id} (PROPOSED). Find it on the Registry board.`, "ok", 6000);
  } catch (err) { toast(errorMessage(err), "error", 6000); }
}

async function run(q, sizeClass) {
  const query = parseInput(q);
  if (!query) { toast("Enter a 5-digit ZIP, a list of ZIPs, or 'City, ST'.", "warn"); return; }
  const ctx = context();
  if (sizeClass) query.size_class = sizeClass;
  if (ctx.client_id) query.client_id = ctx.client_id;
  clear(results);
  results.appendChild(loading("Checking the market…"));
  try { render(await api.marketCheck(query, { as_of: ctx.as_of })); }
  catch (err) { clear(results); results.appendChild(emptyState("Check failed", errorMessage(err))); }
}

export async function mount(container, params) {
  prospectNode = el("div", { class: "muted", style: "padding:9px 0" }, prospectLabel());
  const input = el("input", { class: "input", type: "text", placeholder: "80123   ·   80123, 80127, 80128   ·   Littleton, CO", value: params.q || "" });
  const size = el("select", { class: "select" }, [["", "Standard (default)"], ["SMALL", "Small"], ["STANDARD", "Standard"], ["LARGE", "Large"]].map(([v, l]) => el("option", { value: v }, l)));
  const form = el("form", { class: "sales-form", onSubmit: (e) => { e.preventDefault(); run(input.value, size.value); } },
    el("div", { class: "field" }, el("label", {}, "Starting ZIP, pasted ZIPs, or City, ST"), input),
    el("div", { class: "field" }, el("label", {}, "Size class"), size),
    el("div", { class: "field" }, el("label", {}, "Prospect"), prospectNode),
    el("button", { class: "btn btn-primary", type: "submit" }, "Check market"));
  results = el("div", { class: "stack" }, emptyState("Ready", "One input gives availability, the suggested territory, statistics and talking points."));
  container.appendChild(el("div", { class: "card" }, el("div", { class: "card-body sales-hero" }, form)));
  container.appendChild(results);
  if (params.q) run(params.q, "");
}

export function refresh() { if (prospectNode) prospectNode.textContent = prospectLabel(); }

export function unmount() { results = null; prospectNode = null; }
