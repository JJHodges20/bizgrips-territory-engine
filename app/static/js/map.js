// Map view: ZCTA polygons by availability or tier, hover details, custom groupings and scoring.

import { api } from "./api.js";
import { clear, context, debounce, el, emptyState, errorMessage, flagEl, fmt, formModal, statusBadge, tierBadge, toast } from "./ui.js";

const CFG = window.BG_CONFIG;
const AVAIL_COLORS = { AVAILABLE: "#1f7a3a", RESERVED: "#c98a04", ACTIVE_PROTECTED: "#b42318", PENDING_RELEASE: "#6d4bc2" };
const TIER_COLORS = { A: "#0b4f6c", B: "#1b7fa6", C: "#5fb0d2", D: "#b9dbe9", U: "#cfd6dd" };
const state = { map: null, layer: null, highlight: null, mode: "availability", selected: new Set(), features: {}, evaluation: null, hover: null, sizeClass: "", territory: null };
let nodes = {};

function colorFor(props) {
  if (state.mode === "tier") return TIER_COLORS[props.market_tier || "U"] || TIER_COLORS.U;
  return AVAIL_COLORS[props.availability] || "#8a94a0";
}

function styleFor(feature) {
  const props = feature.properties;
  const selected = state.selected.has(props.zcta);
  return { color: selected ? "#111827" : "#ffffff", weight: selected ? 3 : 1, opacity: selected ? 1 : 0.8,
    fillColor: colorFor(props), fillOpacity: selected ? 0.75 : (props.unserviceable_land_area ? 0.18 : 0.45), dashArray: props.unserviceable_land_area ? "4 3" : null };
}

function restyle() { if (state.layer) state.layer.setStyle(styleFor); }

function legend() {
  const rows = state.mode === "tier"
    ? [["A", "Tier A (75+)"], ["B", "Tier B (60-74)"], ["C", "Tier C (45-59)"], ["D", "Tier D"], ["U", "Unscored"]].map(([k, l]) => [TIER_COLORS[k], l])
    : [[AVAIL_COLORS.AVAILABLE, "Available"], [AVAIL_COLORS.RESERVED, "Reserved"], [AVAIL_COLORS.ACTIVE_PROTECTED, "Active protected"], [AVAIL_COLORS.PENDING_RELEASE, "Pending release"], ["#8a94a0", "No market data"]];
  clear(nodes.legend);
  rows.forEach(([color, label]) => nodes.legend.appendChild(el("div", { class: "legend-row" }, el("span", { class: "swatch", style: `background:${color}` }), label)));
  nodes.legend.appendChild(el("div", { class: "legend-row muted" }, el("span", { class: "swatch", style: "border:1px dashed #555;background:#fff" }), "over land-area cap"));
}

function infoCard(props) {
  const card = nodes.info;
  if (!props) { card.hidden = true; return; }
  clear(card);
  card.hidden = false;
  card.appendChild(el("div", { class: "title" }, `${props.zcta} · ${props.primary_city || "—"}, ${props.state || ""}`, tierBadge(props.market_tier)));
  card.appendChild(el("div", { class: "row", style: "margin:6px 0" }, statusBadge(props.availability), props.own ? el("span", { class: "flag good" }, "own client") : null, props.flags.map(flagEl)));
  const kv = el("dl", { class: "kv" });
  [["Score", props.opportunity_score === null ? "n/a" : fmt.num(props.opportunity_score, 1)], ["Opportunity Units", fmt.int(props.opportunity_units)],
    ["Owner households", fmt.int(props.owner_occupied_households)], ["Owner 45+", fmt.int(props.owner_households_age_45_plus)],
    ["Median income", fmt.money(props.median_household_income)]].forEach(([k, v]) => { kv.appendChild(el("dt", {}, k)); kv.appendChild(el("dd", {}, v)); });
  if (props.client_business_name) { kv.appendChild(el("dt", {}, "Held by")); kv.appendChild(el("dd", {}, `${props.client_business_name} (${props.territory_id}, internal)`)); }
  card.appendChild(kv);
  card.appendChild(el("div", { class: "muted", style: "margin-top:6px" }, "click to add or remove from the selection"));
}

function onEachFeature(feature, layer) {
  const props = feature.properties;
  state.features[props.zcta] = feature;
  layer.on("mouseover", () => { layer.setStyle({ weight: 2.5, color: "#111827" }); infoCard(props); });
  layer.on("mouseout", () => { layer.setStyle(styleFor(feature)); infoCard(null); });
  layer.on("click", () => toggle(props.zcta));
}

const loadViewport = debounce(async () => {
  const map = state.map;
  if (!map) return;
  if (map.getZoom() < CFG.dataMinZoom) { nodes.hint.hidden = false; nodes.hint.textContent = "Zoom in to see ZIP areas"; if (state.layer) { state.layer.remove(); state.layer = null; } return; }
  const b = map.getBounds();
  const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(4)).join(",");
  const ctx = context();
  try {
    nodes.hint.hidden = false; nodes.hint.textContent = "Loading ZIP areas…";
    const collection = await api.mapZctas(bbox, { as_of: ctx.as_of, client_id: ctx.client_id });
    if (state.layer) state.layer.remove();
    state.layer = L.geoJSON(collection, { style: styleFor, onEachFeature }).addTo(state.map);
    if (state.highlight) state.highlight.bringToFront();
    nodes.hint.hidden = true;
    nodes.count.textContent = `${collection.meta.count} ZIP areas in view` + (collection.meta.without_geometry ? ` · ${collection.meta.without_geometry} without geometry` : "");
  } catch (err) {
    nodes.hint.hidden = false; nodes.hint.textContent = errorMessage(err);
  }
}, 250);

function toggle(zcta) {
  if (state.selected.has(zcta)) state.selected.delete(zcta); else state.selected.add(zcta);
  restyle();
  renderSelection();
  evaluateSelection();
}

function renderSelection() {
  const list = nodes.selList;
  clear(list);
  const codes = Array.from(state.selected).sort();
  if (!codes.length) { list.appendChild(el("span", { class: "muted" }, "Click ZIP areas on the map to build a custom grouping.")); }
  const blocked = new Set((state.evaluation ? state.evaluation.per_zip : []).filter((z) => z.availability !== "AVAILABLE").map((z) => z.zcta));
  codes.forEach((z) => list.appendChild(el("span", { class: `sel-pill ${blocked.has(z) ? "blocked" : ""}` }, z, el("button", { type: "button", "aria-label": `remove ${z}`, onClick: () => toggle(z) }, "×"))));
  nodes.selCount.textContent = codes.length ? `${codes.length} selected` : "";
  nodes.btnSave.disabled = !(state.evaluation && state.evaluation.can_save);
  nodes.btnGenerate.disabled = !codes.length;
  nodes.btnClear.disabled = !codes.length;
}

const evaluateSelection = debounce(async () => {
  const codes = Array.from(state.selected).sort();
  const panel = nodes.evalBody;
  if (!codes.length) { state.evaluation = null; clear(panel); panel.appendChild(el("div", { class: "muted" }, "Score, tier, Opportunity Units, contiguity and conflicts appear here.")); renderSelection(); return; }
  const ctx = context();
  try {
    const ev = await api.evaluate({ zips: codes, client_id: ctx.client_id, size_class: state.sizeClass || null }, { as_of: ctx.as_of });
    state.evaluation = ev;
    renderEvaluation(ev);
  } catch (err) { clear(panel); panel.appendChild(el("div", { class: "muted" }, errorMessage(err))); }
  renderSelection();
}, 200);

function metric(label, value) { return el("div", { class: "metric-row" }, el("span", {}, label), el("b", {}, value)); }

function renderEvaluation(ev) {
  const panel = nodes.evalBody;
  clear(panel);
  const a = ev.aggregates;
  panel.appendChild(el("div", { class: "row" }, ev.flags.map(flagEl)));
  if (a) {
    panel.appendChild(el("div", {},
      metric("Opportunity Score", a.opportunity_score === null ? "n/a" : `${fmt.num(a.opportunity_score, 1)} · Tier ${a.market_tier}`),
      metric("Opportunity Units", `${fmt.int(a.opportunity_units)} of ${fmt.int(ev.target.band_min)}–${fmt.int(ev.target.band_max)} (${fmt.words(ev.size_class)})`),
      metric("Owner households", fmt.int(a.owner_occupied_households)), metric("Owner households 45+", fmt.int(a.owner_households_age_45_plus)),
      metric("Households", fmt.int(a.total_households)), metric("Built before 2000", a.total_housing_units ? fmt.pct(a.homes_built_before_2000 / a.total_housing_units) : "n/a"),
      metric("Median income", fmt.money(a.median_household_income)), metric("Land area", `${fmt.num(a.land_area_sq_miles, 0)} sq mi`),
      metric("Contiguous", ev.contiguous ? "yes" : `no · ${ev.components.length} pieces`)));
  }
  const rows = ev.per_zip.map((z) => el("tr", {}, el("td", { class: "mono" }, z.zcta), el("td", {}, z.primary_city || "—"), el("td", {}, tierBadge(z.tier)), el("td", { class: "num" }, fmt.int(z.opportunity_units)),
    el("td", {}, z.availability === "AVAILABLE" ? el("span", { class: "flag good" }, "available") : el("span", { class: "flag bad", title: z.blocking_client || "" }, fmt.words(z.availability)))));
  panel.appendChild(el("table", { class: "zip-table" }, el("thead", {}, el("tr", {}, ["ZIP", "City", "Tier", "OU", "Status"].map((h) => el("th", {}, h)))), el("tbody", {}, rows)));
  if (ev.conflicts.conflict_count) {
    const held = [...ev.conflicts.reserved, ...ev.conflicts.protected, ...ev.conflicts.pending_release];
    panel.appendChild(el("div", { class: "muted" }, "Held by other clients (internal): " + held.map((h) => `${h.zcta} ${fmt.words(h.status)} · ${h.client_business_name}`).join("; ")));
    if (ev.conflicts.suggestions.length) panel.appendChild(el("div", { class: "muted" }, "Nearest available alternatives: " + Array.from(new Set(ev.conflicts.suggestions.map((s) => s.zcta))).join(", ")));
  }
  if (ev.unknown_zips.length) panel.appendChild(el("div", { class: "muted" }, "No market data: " + ev.unknown_zips.join(", ")));
  panel.appendChild(el("div", { class: "muted" }, ev.disclaimer));
}

async function generateFromSelection() {
  const codes = Array.from(state.selected).sort();
  if (!codes.length) return;
  const ctx = context();
  const values = await formModal({ title: "Generate a territory", submitLabel: "Generate", intro: "Runs the generator from a starting ZIP with the rest of the selection as requested ZIPs. Nothing is saved.", fields: [
    { name: "starting_zip", label: "Starting ZIP", type: "select", options: codes.map((z) => ({ value: z, label: z })) },
    { name: "size_class", label: "Size class", type: "select", options: [{ value: "", label: "Standard (default)" }, { value: "SMALL", label: "Small" }, { value: "STANDARD", label: "Standard" }, { value: "LARGE", label: "Large" }], value: state.sizeClass },
  ] });
  if (!values) return;
  try {
    const proposal = await api.propose({ client_name: ctx.client_id || "Prospect", client_id: ctx.client_id || null, starting_zip: values.starting_zip, size_class: values.size_class || null, requested_zips: codes.filter((z) => z !== values.starting_zip) }, { as_of: ctx.as_of });
    if (proposal.status !== "PROPOSED") { toast(`${proposal.failure.code}: ${proposal.failure.message}`, "warn", 7000); return; }
    state.selected = new Set(proposal.zips.map((z) => z.zcta));
    restyle(); renderSelection(); evaluateSelection();
    toast(`Proposal: ${proposal.zips.length} ZIPs, ${fmt.int(proposal.aggregates.opportunity_units)} OU, ${fmt.words(proposal.target.status)}. The selection now shows the proposal.`, "ok", 7000);
  } catch (err) { toast(errorMessage(err), "error", 7000); }
}

async function saveSelection() {
  const ev = state.evaluation;
  if (!ev || !ev.can_save) return;
  const ctx = context();
  const values = await formModal({ title: "Save selection as PROPOSED territory", submitLabel: "Create proposal", intro: "A named approver must still reserve it.", fields: [
    { name: "client_id", label: "Client id", required: true, value: ctx.client_id || "" }, { name: "client_business_name", label: "Business name", required: true },
    { name: "starting_zip", label: "Starting ZIP", type: "select", options: ev.zips.map((z) => ({ value: z, label: z })) }, { name: "notes", label: "Notes", type: "textarea", span2: true }] });
  if (!values) return;
  try {
    const t = await api.createTerritory({ client_id: values.client_id, client_business_name: values.client_business_name, starting_zip: values.starting_zip, territory_size_class: ev.size_class, zips: ev.zips, notes: values.notes, generation_snapshot: { source: "map_selection", evaluation: ev } }, { as_of: ctx.as_of });
    toast(`Created ${t.territory_id} (PROPOSED).`, "ok", 6000);
    loadViewport();
  } catch (err) { toast(errorMessage(err), "error", 7000); }
}

async function showTerritory(id) {
  const ctx = context();
  try {
    const shape = await api.mapTerritory(id, { as_of: ctx.as_of });
    if (state.highlight) state.highlight.remove();
    state.highlight = L.geoJSON(shape, { style: { color: "#111827", weight: 4, fillOpacity: 0.08, dashArray: "6 4" }, interactive: false }).addTo(state.map);
    state.territory = shape.territory;
    if (shape.bounds) state.map.fitBounds(shape.bounds, { padding: [40, 40], maxZoom: 13 });
    const t = shape.territory;
    clear(nodes.territoryBox);
    nodes.territoryBox.hidden = false;
    nodes.territoryBox.appendChild(el("div", { class: "row" }, el("b", {}, t.territory_id), statusBadge(t.status), t.flags.map(flagEl)));
    nodes.territoryBox.appendChild(el("div", { class: "muted" }, `${t.client_business_name} · ${t.zips.length} ZIPs (internal)`));
    nodes.territoryBox.appendChild(el("div", { class: "row" },
      el("button", { class: "btn btn-sm", type: "button", onClick: () => { state.selected = new Set(t.zips); restyle(); renderSelection(); evaluateSelection(); } }, "Use as selection"),
      el("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => window.bgGo("registry", { territory: t.territory_id }) }, "Open in registry"),
      el("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => { state.highlight.remove(); state.highlight = null; nodes.territoryBox.hidden = true; } }, "Hide")));
  } catch (err) { toast(errorMessage(err), "error"); }
}

async function locate(q) {
  if (!q.trim()) return;
  try {
    const hit = await api.locate(q.trim());
    if (hit.bounds) state.map.fitBounds(hit.bounds, { padding: [30, 30], maxZoom: 13 }); else state.map.setView(hit.center, 12);
    toast(`${hit.label}: ${hit.zctas.length} ZIP area${hit.zctas.length === 1 ? "" : "s"}`, "info", 2500);
  } catch (err) { toast(errorMessage(err), "warn"); }
}

async function preselect(codes) {
  state.selected = new Set(codes);
  const boxes = [];
  for (const z of codes.slice(0, 40)) {
    try { const hit = await api.locate(z); if (hit.bounds) boxes.push(hit.bounds); } catch (err) { /* skipped: no market data */ }
  }
  if (boxes.length) {
    const south = Math.min(...boxes.map((b) => b[0][0])), west = Math.min(...boxes.map((b) => b[0][1]));
    const north = Math.max(...boxes.map((b) => b[1][0])), east = Math.max(...boxes.map((b) => b[1][1]));
    state.map.fitBounds([[south, west], [north, east]], { padding: [40, 40], maxZoom: 13 });
  }
  renderSelection();
  evaluateSelection();
}

export async function mount(container, params) {
  const mapNode = el("div", { id: "map", class: "map" });
  const search = el("input", { class: "input", type: "search", placeholder: "Go to ZIP or City, ST", onKeydown: (e) => { if (e.key === "Enter") locate(e.target.value); } });
  const mode = el("select", { class: "select", onChange: (e) => { state.mode = e.target.value; legend(); restyle(); } },
    el("option", { value: "availability" }, "Colour: availability"), el("option", { value: "tier" }, "Colour: market tier"));
  nodes = {
    hint: el("div", { class: "map-hint" }, "Zoom in to see ZIP areas"), legend: el("div", { class: "legend" }), info: el("div", { class: "info-card", hidden: true }),
    count: el("span", { class: "muted" }), selList: el("div", { class: "sel-list" }), selCount: el("span", { class: "muted" }), evalBody: el("div", { class: "stack" }),
    territoryBox: el("div", { class: "panel-section", hidden: true }),
    btnClear: el("button", { class: "btn btn-sm", type: "button", disabled: true, onClick: () => { state.selected.clear(); restyle(); renderSelection(); evaluateSelection(); } }, "Clear"),
    btnGenerate: el("button", { class: "btn btn-sm", type: "button", disabled: true, onClick: generateFromSelection }, "Generate from…"),
    btnSave: el("button", { class: "btn btn-sm btn-primary", type: "button", disabled: true, onClick: saveSelection }, "Save as proposal"),
  };
  const size = el("select", { class: "select", onChange: (e) => { state.sizeClass = e.target.value; evaluateSelection(); } },
    [["", "Standard (default)"], ["SMALL", "Small"], ["STANDARD", "Standard"], ["LARGE", "Large"]].map(([v, l]) => el("option", { value: v }, l)));
  mapNode.appendChild(el("div", { class: "map-toolbar" }, search, mode));
  mapNode.appendChild(nodes.hint); mapNode.appendChild(nodes.legend); mapNode.appendChild(nodes.info);
  const panel = el("aside", { class: "map-panel" },
    el("div", { class: "panel-section" }, el("div", { class: "section-title" }, el("h2", {}, "Custom grouping"), nodes.selCount), nodes.selList,
      el("div", { class: "row" }, el("div", { class: "field", style: "flex:1" }, el("label", {}, "Size class"), size)),
      el("div", { class: "row" }, nodes.btnGenerate, nodes.btnSave, nodes.btnClear)),
    nodes.territoryBox,
    el("div", { class: "panel-section" }, el("h2", {}, "Evaluation"), nodes.evalBody),
    el("div", { class: "panel-section" }, nodes.count, el("div", { class: "muted" }, "Availability comes from the registry as of the date in the header; client names are internal.")));
  container.appendChild(el("div", { class: "map-layout" }, mapNode, panel));
  state.map = L.map(mapNode, { center: CFG.defaultCenter, zoom: CFG.defaultZoom, minZoom: CFG.minZoom, maxZoom: CFG.maxZoom, zoomControl: true });
  L.tileLayer(CFG.tileUrl, { attribution: CFG.tileAttribution, maxZoom: CFG.maxZoom }).addTo(state.map);
  state.map.on("moveend", loadViewport);
  legend();
  clear(nodes.evalBody); nodes.evalBody.appendChild(el("div", { class: "muted" }, "Score, tier, Opportunity Units, contiguity and conflicts appear here."));
  renderSelection();
  if (params.territory) await showTerritory(params.territory);
  else if (params.zips) await preselect(params.zips.split(",").map((z) => z.trim()).filter(Boolean));
  else if (params.q) await locate(params.q);
  loadViewport();
}

export function refresh() { if (state.map) { loadViewport(); evaluateSelection(); } }

export function unmount() {
  if (state.map) { state.map.remove(); state.map = null; }
  state.layer = null; state.highlight = null; state.features = {}; state.evaluation = null; state.selected = new Set();
  nodes = {};
}
