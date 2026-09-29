// Hash router for the workspace: #/registry, #/map?territory=T-000001, #/sales?q=80123

import { api } from "./api.js";
import { clear, drawer, initContext, onContextChange, toast } from "./ui.js";
import * as registry from "./registry.js";
import * as map from "./map.js";
import * as sales from "./sales.js";

const views = { registry, map, sales };
const titles = { registry: "Registry", map: "Map", sales: "Sales check" };
let current = null;
let currentRoute = null;

export function parseHash() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [path, query] = hash.split("?");
  const params = {};
  (query || "").split("&").filter(Boolean).forEach((pair) => {
    const [k, v] = pair.split("=");
    params[decodeURIComponent(k)] = decodeURIComponent(v || "");
  });
  return { route: path || "registry", params };
}

export function go(route, params) {
  const query = Object.keys(params || {}).filter((k) => params[k] !== undefined && params[k] !== null && params[k] !== "")
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`).join("&");
  location.hash = `#/${route}${query ? "?" + query : ""}`;
}

async function navigate() {
  const { route, params } = parseHash();
  const view = views[route] || views.registry;
  const container = document.getElementById("view");
  if (current && current.unmount) { try { current.unmount(); } catch (err) { console.error(err); } }
  drawer.close();
  currentRoute = views[route] ? route : "registry";
  document.getElementById("view-title").textContent = titles[currentRoute];
  document.querySelectorAll(".rail-link[data-route]").forEach((link) => link.classList.toggle("active", link.dataset.route === currentRoute));
  container.className = "view" + (currentRoute === "map" ? " view-map" : "");
  clear(container);
  current = view;
  try {
    await view.mount(container, params);
  } catch (err) {
    console.error(err);
    toast(`Could not load the ${titles[currentRoute]} view: ${err.message}`, "error");
  }
}

async function showHealth() {
  try {
    const health = await api.health();
    document.getElementById("rail-foot").textContent = `rules ${health.business_rules_version} · ${health.database.dialect} ${health.database.status}`;
  } catch (err) {
    document.getElementById("rail-foot").textContent = "API unreachable";
  }
}

initContext();
onContextChange(() => { if (current && current.refresh) current.refresh(); });
window.addEventListener("hashchange", navigate);
window.bgGo = go;
showHealth();
navigate();
