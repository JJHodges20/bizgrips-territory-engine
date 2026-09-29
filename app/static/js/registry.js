// Registry board: every territory, its flags and the human actions that change its state.

import { api } from "./api.js";
import { clear, confirmModal, context, drawer, el, emptyState, errorMessage, flagEl, fmt, formModal, loading, statusBadge, toast } from "./ui.js";

const STATUSES = ["ALL", "PROPOSED", "RESERVED", "ACTIVE_PROTECTED", "PENDING_RELEASE", "RELEASED", "CANCELLED"];
const EXCEPTIONS = ["NON_CONTIGUOUS_ZCTA", "EXCEEDS_MAX_SIZE", "UNSERVICEABLE_ZCTA", "OUTSIDE_SERVICE_RADIUS", "CROSS_STATE", "OVERRIDE_EXPIRED_RESERVATION"];
const state = { items: [], flags: null, status: "ALL", q: "" };
let root = null;
let listNode = null;
let statsNode = null;
let chipsNode = null;

function counts() {
  const by = {};
  state.items.forEach((t) => { by[t.status] = (by[t.status] || 0) + 1; });
  return by;
}

function visible() {
  const q = state.q.toLowerCase();
  return state.items.filter((t) => (state.status === "ALL" || t.status === state.status) &&
    (!q || `${t.territory_id} ${t.client_id} ${t.client_business_name} ${t.starting_zip} ${t.zips.join(" ")}`.toLowerCase().includes(q)));
}

function renderStats() {
  clear(statsNode);
  const by = counts();
  const flags = state.flags || { expired_reservations: [], releases_due: [] };
  const stat = (label, value, sub, cls) => el("div", { class: "stat" }, el("div", { class: "label" }, label), el("div", { class: `value ${cls || ""}` }, String(value)), sub ? el("div", { class: "sub" }, sub) : null);
  statsNode.appendChild(stat("Active protected", by.ACTIVE_PROTECTED || 0, "territories under contract"));
  statsNode.appendChild(stat("Reserved", by.RESERVED || 0, `${flags.expired_reservations.length} expired, waiting on a human`));
  statsNode.appendChild(stat("Proposed", by.PROPOSED || 0, "awaiting a named approver"));
  statsNode.appendChild(stat("Pending release", by.PENDING_RELEASE || 0, `${flags.releases_due.length} due now`));
}

function renderChips() {
  clear(chipsNode);
  const by = counts();
  STATUSES.forEach((s) => {
    const n = s === "ALL" ? state.items.length : (by[s] || 0);
    chipsNode.appendChild(el("button", { class: `chip ${state.status === s ? "active" : ""}`, type: "button", onClick: () => { state.status = s; renderChips(); renderList(); } }, fmt.words(s) || "all", el("span", { class: "count" }, String(n))));
  });
}

function dateCell(t) {
  if (t.status === "RESERVED") return `expires ${fmt.date(t.reservation_expires_at)}`;
  if (t.status === "ACTIVE_PROTECTED") return `${fmt.date(t.contract_start_date)} → ${fmt.date(t.contract_end_date)}`;
  if (t.status === "PENDING_RELEASE") return `releases ${fmt.date(t.release_date)}`;
  if (t.status === "RELEASED" || t.status === "CANCELLED") return `released ${fmt.date(t.release_date)}`;
  return `created ${fmt.date(t.created_at)}`;
}

function renderList() {
  clear(listNode);
  const rows = visible();
  if (!rows.length) { listNode.appendChild(emptyState("No territories", state.items.length ? "Nothing matches the current filter." : "Create one from the map, the sales check, or the New territory button.")); return; }
  const head = el("tr", {}, ["Territory", "Client", "Status", "Flags", "ZIPs", "Start", "Size", "Dates", "Approved by"].map((h) => el("th", {}, h)));
  const body = el("tbody", {}, rows.map((t) => el("tr", { class: "clickable", onClick: () => openTerritory(t.territory_id) },
    el("td", { class: "mono" }, t.territory_id), el("td", {}, el("div", {}, t.client_business_name), el("div", { class: "muted mono" }, t.client_id)),
    el("td", {}, statusBadge(t.status)), el("td", {}, t.flags.length ? t.flags.map(flagEl) : el("span", { class: "muted" }, "—")),
    el("td", { class: "num" }, String(t.zip_count)), el("td", { class: "mono" }, t.starting_zip), el("td", {}, fmt.words(t.territory_size_class)),
    el("td", { class: "small" }, dateCell(t)), el("td", { class: "small" }, t.approved_by || "—"))));
  listNode.appendChild(el("div", { class: "table-wrap" }, el("table", { class: "table" }, el("thead", {}, head), body)));
}

export async function refresh() {
  if (!root) return;
  const ctx = context();
  try {
    const [list, flags] = await Promise.all([api.territories({ as_of: ctx.as_of }), api.flags({ as_of: ctx.as_of })]);
    state.items = list.items; state.flags = flags;
    renderStats(); renderChips(); renderList();
  } catch (err) { clear(listNode); listNode.appendChild(emptyState("Could not load the registry", errorMessage(err))); }
}

const ACTIONS = {
  reserve: { label: "Reserve", cls: "btn-primary", statuses: ["PROPOSED"], fields: [
    { name: "approved_by", label: "Approved by", required: true, hint: "named person; starts the 30-day reservation" }] },
  extend: { label: "Extend reservation", statuses: ["RESERVED"], fields: [
    { name: "approved_by", label: "Approved by", required: true }, { name: "reason", label: "Reason", required: true, span2: true }] },
  activate: { label: "Activate (contract signed)", cls: "btn-accent", statuses: ["RESERVED"], fields: [
    { name: "approved_by", label: "Approved by", required: true }, { name: "contract_start_date", label: "Contract start", type: "date", required: true },
    { name: "contract_end_date", label: "Contract end", type: "date" }] },
  cancel: { label: "Cancel", cls: "btn-danger", statuses: ["PROPOSED", "RESERVED"], danger: true, fields: [
    { name: "actor", label: "Your name", required: true }, { name: "reason", label: "Reason", required: true, span2: true }] },
  "pending-release": { label: "Start release", cls: "btn-danger", statuses: ["ACTIVE_PROTECTED"], danger: true, fields: [
    { name: "actor", label: "Your name", required: true }, { name: "release_date", label: "Release date", type: "date", hint: "default: 30 days' notice or contract end" },
    { name: "reason", label: "Reason", required: true, span2: true }] },
  release: { label: "Complete release", cls: "btn-danger", statuses: ["PENDING_RELEASE"], danger: true, fields: [
    { name: "actor", label: "Your name", required: true }] },
  exceptions: { label: "Record exception", statuses: ["PROPOSED", "RESERVED", "ACTIVE_PROTECTED", "PENDING_RELEASE"], fields: [
    { name: "exception_type", label: "Exception", type: "select", options: EXCEPTIONS.map((e) => ({ value: e, label: fmt.words(e) })) },
    { name: "approved_by", label: "Approved by", required: true }, { name: "reason", label: "Reason", required: true, span2: true }] },
};

async function act(id, key) {
  const spec = ACTIONS[key];
  const values = await formModal({ title: `${spec.label} · ${id}`, submitLabel: spec.label, danger: spec.danger, fields: spec.fields });
  if (!values) return;
  try {
    const updated = await api.transition(id, key, values, { as_of: context().as_of });
    toast(`${id} is now ${fmt.words(updated.status)}.`, "ok");
    await refresh();
    openTerritory(id);
  } catch (err) { toast(errorMessage(err), "error", 7000); }
}

function tabbed(sections) {
  const tabs = el("div", { class: "tabs" });
  const body = el("div", {});
  const show = (i) => { clear(body); body.appendChild(sections[i].content); Array.from(tabs.children).forEach((t, j) => t.classList.toggle("active", i === j)); };
  sections.forEach((s, i) => tabs.appendChild(el("button", { class: "tab", type: "button", onClick: () => show(i) }, s.title)));
  show(0);
  return el("div", {}, tabs, body);
}

async function sweep() {
  const ok = await confirmModal({ title: "Run registry sweep", message: "Completes PENDING_RELEASE territories whose release date has passed. Expired reservations are only listed, never released." });
  if (!ok) return;
  try {
    const r = await api.sweep({ as_of: context().as_of });
    toast(`Released ${r.released.length}; ${r.expired_reservations.length} expired reservation(s) need a decision.`, "ok", 6000);
    await refresh();
  } catch (err) { toast(errorMessage(err), "error"); }
}

export async function openTerritory(id) {
  let t;
  try { t = await api.territory(id, { as_of: context().as_of }); } catch (err) { toast(errorMessage(err), "error"); return; }
  const kv = el("dl", { class: "kv" });
  const extensions = `${t.reservation_extensions} extension${t.reservation_extensions === 1 ? "" : "s"}`;
  [["Client", `${t.client_business_name} (${t.client_id})`], ["Starting ZIP", t.starting_zip], ["Size class", fmt.words(t.territory_size_class)],
    ["Approved by", t.approved_by ? `${t.approved_by} on ${fmt.date(t.approved_at)}` : "—"],
    ["Reservation", t.reservation_date ? `${fmt.date(t.reservation_date)} → ${fmt.date(t.reservation_expires_at)} (${extensions})` : "—"],
    ["Contract", t.contract_start_date ? `${fmt.date(t.contract_start_date)} → ${fmt.date(t.contract_end_date)}` : "—"],
    ["Release date", fmt.date(t.release_date)], ["Updated", fmt.date(t.updated_at)]]
    .forEach(([k, v]) => { kv.appendChild(el("dt", {}, k)); kv.appendChild(el("dd", {}, v)); });
  const overview = el("div", { class: "stack" }, el("div", { class: "row" }, statusBadge(t.status), t.flags.map(flagEl)), kv);
  const zipRows = t.assignments.length
    ? t.assignments.map((a) => el("tr", {}, el("td", { class: "mono" }, a.zip), el("td", {}, statusBadge(a.status)), el("td", {}, fmt.date(a.date_assigned)), el("td", {}, fmt.date(a.date_released))))
    : t.zips.map((z) => el("tr", {}, el("td", { class: "mono" }, z), el("td", {}, el("span", { class: "muted" }, "proposed")), el("td", {}, "—"), el("td", {}, "—")));
  const zips = el("div", { class: "table-wrap" }, el("table", { class: "table" },
    el("thead", {}, el("tr", {}, ["ZIP", "Status", "Assigned", "Released"].map((h) => el("th", {}, h)))), el("tbody", {}, zipRows)));
  const audit = el("pre", { class: "audit" }, t.notes || "(no notes yet)");
  const exceptions = t.exceptions.length
    ? el("div", { class: "stack" }, t.exceptions.map((e) => el("div", { class: "card" }, el("div", { class: "card-body" }, el("b", {}, fmt.words(e.type)), el("div", { class: "muted" }, `${e.approved_by} · ${e.at}`), el("div", {}, e.reason)))))
    : emptyState("No exceptions", "Exceptions need a named approver and a reason.");
  const actions = Object.keys(ACTIONS).filter((k) => ACTIONS[k].statuses.includes(t.status))
    .map((k) => el("button", { class: `btn btn-sm ${ACTIONS[k].cls || ""}`, type: "button", onClick: () => act(id, k) }, ACTIONS[k].label));
  actions.push(el("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => window.bgGo("map", { territory: id }) }, "Show on map"));
  if (["PROPOSED", "RESERVED", "ACTIVE_PROTECTED"].includes(t.status)) {
    actions.push(el("button", { class: "btn btn-sm btn-ghost", type: "button", onClick: () => openProposalPdf(id) }, "Client proposal (PDF)"));
  }
  drawer.open({ title: id, subtitle: `${t.client_business_name} · ${t.zip_count} ZIPs`, actions, body: tabbed([
    { title: "Overview", content: overview }, { title: `ZIPs (${t.zip_count})`, content: zips },
    { title: "Audit trail", content: audit }, { title: `Exceptions (${t.exceptions.length})`, content: exceptions }]) });
}

function openProposalPdf(id) {
  const ctx = context();
  const query = ctx.as_of ? `?as_of=${encodeURIComponent(ctx.as_of)}` : "";
  window.open(`/territories/${id}/proposal.pdf${query}`, "_blank", "noopener");
}

async function newTerritory() {
  const ctx = context();
  const values = await formModal({ title: "New territory (manual)", submitLabel: "Create PROPOSED", intro: "Creates a PROPOSED record from an explicit ZIP list; ZIPs held by other clients are refused.", fields: [
    { name: "client_id", label: "Client id", required: true, value: ctx.client_id || "" }, { name: "client_business_name", label: "Business name", required: true },
    { name: "starting_zip", label: "Starting ZIP", required: true },
    { name: "territory_size_class", label: "Size class", type: "select", options: [{ value: "STANDARD", label: "Standard" }, { value: "SMALL", label: "Small" }, { value: "LARGE", label: "Large" }] },
    { name: "zips", label: "ZIPs", type: "textarea", required: true, span2: true, placeholder: "80123, 80127 80128 …" }, { name: "notes", label: "Notes", type: "textarea", span2: true }] });
  if (!values) return;
  const zips = values.zips.match(/\d{5}/g) || [];
  try {
    const t = await api.createTerritory({ client_id: values.client_id, client_business_name: values.client_business_name, starting_zip: values.starting_zip,
      territory_size_class: values.territory_size_class, zips, notes: values.notes }, { as_of: ctx.as_of });
    toast(`Created ${t.territory_id}.`, "ok");
    await refresh();
    openTerritory(t.territory_id);
  } catch (err) { toast(errorMessage(err), "error", 7000); }
}

export async function mount(container, params) {
  root = container;
  statsNode = el("div", { class: "stat-grid" });
  chipsNode = el("div", { class: "row" });
  const search = el("input", { class: "input", type: "search", placeholder: "Search id, client, ZIP…", onInput: (e) => { state.q = e.target.value; renderList(); } });
  listNode = el("div", {}, loading("Loading territories…"));
  container.appendChild(statsNode);
  container.appendChild(el("div", { class: "toolbar" }, chipsNode, el("div", { class: "grow" }, search),
    el("button", { class: "btn", type: "button", onClick: sweep }, "Run sweep"), el("button", { class: "btn btn-primary", type: "button", onClick: newTerritory }, "New territory")));
  container.appendChild(listNode);
  await refresh();
  if (params.territory) openTerritory(params.territory);
}

export function unmount() { root = null; }
