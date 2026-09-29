// DOM helpers, formatting, toasts, modals, drawer and the shared as-of / client context.

export function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  const props = attrs || {};
  Object.keys(props).forEach((key) => {
    const value = props[key];
    if (value === null || value === undefined || value === false) return;
    if (key === "class" || key === "className") node.className = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "dataset") Object.keys(value).forEach((k) => { node.dataset[k] = value[k]; });
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "hidden") node.hidden = Boolean(value);
    else if (key === "disabled" || key === "checked" || key === "selected") node[key] = Boolean(value);
    else node.setAttribute(key, value);
  });
  append(node, children);
  return node;
}

export function append(node, children) {
  (Array.isArray(children) ? children : [children]).forEach((child) => {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) append(node, child);
    else node.appendChild(typeof child === "string" || typeof child === "number" ? document.createTextNode(String(child)) : child);
  });
  return node;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

export const fmt = {
  int: (n) => (n === null || n === undefined ? "n/a" : Math.round(n).toLocaleString("en-US")),
  money: (n) => (n === null || n === undefined ? "n/a" : "$" + Math.round(n).toLocaleString("en-US")),
  pct: (x, digits) => (x === null || x === undefined ? "n/a" : (x * 100).toFixed(digits || 0) + "%"),
  num: (n, digits) => (n === null || n === undefined ? "n/a" : Number(n).toFixed(digits === undefined ? 1 : digits)),
  date: (iso) => (iso ? String(iso).slice(0, 10) : "—"),
  miles: (n) => (n === null || n === undefined ? "n/a" : Number(n).toFixed(1) + " mi"),
  words: (s) => (s ? String(s).replace(/_/g, " ").toLowerCase() : ""),
};

export function badge(text, cls) { return el("span", { class: `badge ${cls || ""}` }, text); }
export function tierBadge(tier) { return badge(`Tier ${tier || "U"}`, `tier ${tier || "U"}`); }
export function statusBadge(status) { return badge(fmt.words(status), status || ""); }
const GOOD_FLAGS = ["WITHIN_TARGET", "AVAILABLE"];
const BAD_FLAGS = ["BELOW_MINIMUM_VIABLE", "EXCEEDS_MAX_SIZE", "CONTAINS_BLOCKED", "NOT_CONTIGUOUS", "RESERVATION_EXPIRED", "CONTAINS_UNKNOWN"];
export function flagEl(flag) {
  const cls = GOOD_FLAGS.includes(flag) ? "good" : (BAD_FLAGS.includes(flag) ? "bad" : "");
  return el("span", { class: `flag ${cls}` }, fmt.words(flag));
}
export function emptyState(title, text) { return el("div", { class: "empty" }, el("strong", {}, title), text || ""); }
export function loading(text) { return el("div", { class: "loading" }, el("span", { class: "spinner" }), text || "Loading…"); }
export function errorMessage(err) { return err && err.message ? err.message : String(err); }
export function debounce(fn, ms) { let t = null; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); }; }

export function toast(message, kind, ms) {
  const root = document.getElementById("toasts");
  const node = el("div", { class: `toast ${kind || "info"}` }, message);
  root.appendChild(node);
  setTimeout(() => { node.style.opacity = "0"; setTimeout(() => node.remove(), 250); }, ms || 4000);
}

export function openModal(options) {
  const root = document.getElementById("modal-root");
  const backdrop = el("div", { class: "modal-backdrop" });
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const close = () => { backdrop.remove(); document.removeEventListener("keydown", onKey); };
  const foot = el("div", { class: "modal-foot" });
  (options.actions || []).forEach((action) => {
    foot.appendChild(el("button", { class: `btn ${action.cls || ""}`, type: "button", onClick: () => action.onClick(close) }, action.label));
  });
  const modal = el("div", { class: "modal", role: "dialog", "aria-modal": "true" },
    el("div", { class: "modal-head" }, el("h2", {}, options.title), el("button", { class: "close", type: "button", "aria-label": "Close", onClick: close }, "×")),
    el("div", { class: "modal-body" }, options.body), foot);
  backdrop.appendChild(modal);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  document.addEventListener("keydown", onKey);
  root.appendChild(backdrop);
  const first = modal.querySelector("input, select, textarea, button.btn-primary");
  if (first) first.focus();
  return { close, node: modal };
}

export function formModal(options) {
  return new Promise((resolve) => {
    const form = el("form", { class: "form-grid", onSubmit: (e) => e.preventDefault() });
    if (options.intro) form.appendChild(el("p", { class: "muted span-2" }, options.intro));
    const inputs = {};
    options.fields.forEach((f) => {
      let input;
      if (f.type === "select") {
        input = el("select", { class: "select", name: f.name }, (f.options || []).map((o) => el("option", { value: o.value, selected: o.value === f.value }, o.label)));
      } else if (f.type === "textarea") {
        input = el("textarea", { class: "textarea", name: f.name, placeholder: f.placeholder || "" }, f.value || "");
      } else {
        input = el("input", { class: "input", name: f.name, type: f.type || "text", value: f.value || "", placeholder: f.placeholder || "" });
      }
      inputs[f.name] = input;
      form.appendChild(el("div", { class: `field ${f.span2 ? "span-2" : ""}` }, el("label", {}, f.label + (f.required ? " *" : "")), input, f.hint ? el("span", { class: "hint" }, f.hint) : null));
    });
    const submit = (close) => {
      const values = {};
      let ok = true;
      options.fields.forEach((f) => {
        const value = inputs[f.name].value.trim();
        if (f.required && !value && ok) { ok = false; inputs[f.name].focus(); }
        values[f.name] = value || null;
      });
      if (!ok) { toast("Please fill in the required fields.", "warn"); return; }
      close();
      resolve(values);
    };
    const modal = openModal({ title: options.title, body: form, actions: [
      { label: "Cancel", onClick: (close) => { close(); resolve(null); } },
      { label: options.submitLabel || "Save", cls: options.danger ? "btn-danger" : "btn-primary", onClick: submit },
    ] });
    form.addEventListener("submit", () => submit(modal.close));
  });
}

export function confirmModal(options) {
  return new Promise((resolve) => {
    openModal({ title: options.title, body: el("p", {}, options.message), actions: [
      { label: "Cancel", onClick: (close) => { close(); resolve(false); } },
      { label: options.confirmLabel || "Confirm", cls: options.danger ? "btn-danger" : "btn-primary", onClick: (close) => { close(); resolve(true); } },
    ] });
  });
}

export const drawer = {
  open(options) {
    const node = document.getElementById("drawer");
    clear(node);
    node.appendChild(el("div", { class: "drawer-head" },
      el("div", {}, el("h2", {}, options.title), options.subtitle ? el("div", { class: "muted" }, options.subtitle) : null),
      el("button", { class: "close", type: "button", "aria-label": "Close", onClick: () => drawer.close() }, "×")));
    node.appendChild(el("div", { class: "drawer-body" }, options.body));
    if (options.actions && options.actions.length) node.appendChild(el("div", { class: "drawer-actions" }, options.actions));
    node.hidden = false;
  },
  close() { const node = document.getElementById("drawer"); node.hidden = true; clear(node); },
  isOpen() { return !document.getElementById("drawer").hidden; },
};

const listeners = [];
export function context() {
  const asOf = document.getElementById("ctx-as-of").value;
  const clientId = document.getElementById("ctx-client-id").value.trim();
  return { as_of: asOf || undefined, client_id: clientId || undefined };
}
export function onContextChange(fn) { listeners.push(fn); }
export function initContext() {
  const asOf = document.getElementById("ctx-as-of");
  const client = document.getElementById("ctx-client-id");
  asOf.value = localStorage.getItem("bg.as_of") || new Date().toISOString().slice(0, 10);
  client.value = localStorage.getItem("bg.client_id") || "";
  const notify = () => {
    localStorage.setItem("bg.as_of", asOf.value);
    localStorage.setItem("bg.client_id", client.value);
    listeners.forEach((fn) => fn(context()));
  };
  asOf.addEventListener("change", notify);
  client.addEventListener("change", notify);
}
