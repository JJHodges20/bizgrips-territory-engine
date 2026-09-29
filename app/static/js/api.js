// Thin JSON client for the engine's API. Every call returns parsed JSON or throws ApiError.

export class ApiError extends Error {
  constructor(status, detail) {
    const message = detail && detail.message ? detail.message : (typeof detail === "string" ? detail : `HTTP ${status}`);
    super(message);
    this.status = status;
    this.detail = detail;
    this.code = detail && detail.code ? detail.code : null;
  }
}

function buildQuery(params) {
  if (!params) return "";
  const pairs = [];
  Object.keys(params).forEach((key) => {
    const value = params[key];
    if (value === undefined || value === null || value === "") return;
    pairs.push(`${encodeURIComponent(key)}=${encodeURIComponent(value)}`);
  });
  return pairs.length ? `?${pairs.join("&")}` : "";
}

async function request(method, path, params, body) {
  const options = { method, headers: { Accept: "application/json" } };
  if (body !== undefined && body !== null) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path + buildQuery(params), options);
  let payload = null;
  const text = await response.text();
  if (text) {
    try { payload = JSON.parse(text); } catch (err) { payload = text; }
  }
  if (!response.ok) {
    const detail = payload && payload.detail !== undefined ? payload.detail : payload;
    throw new ApiError(response.status, Array.isArray(detail) ? { code: "VALIDATION", message: detail.map((d) => d.msg).join("; ") } : detail);
  }
  return payload;
}

const get = (path, params) => request("GET", path, params);
const post = (path, body, params) => request("POST", path, params, body);

export const api = {
  health: () => get("/health"),
  rules: () => get("/config/business-rules"),
  territories: (params) => get("/territories", params),
  territory: (id, params) => get(`/territories/${id}`, params),
  createTerritory: (body, params) => post("/territories", body, params),
  transition: (id, action, body, params) => post(`/territories/${id}/${action}`, body, params),
  propose: (body, params) => post("/territories/propose", body, params),
  evaluate: (body, params) => post("/territories/evaluate", body, params),
  flags: (params) => get("/registry/flags", params),
  sweep: (params) => post("/registry/sweep", null, params),
  availability: (zip, params) => get(`/zips/${zip}/availability`, params),
  conflicts: (body, params) => post("/conflicts/check", body, params),
  marketCheck: (body, params) => post("/market/check", body, params),
  zcta: (zcta) => get(`/zctas/${zcta}`),
  zctaScore: (zcta) => get(`/zctas/${zcta}/score`),
  mapZctas: (bbox, params) => get("/map/zctas", Object.assign({ bbox }, params || {})),
  mapTerritory: (id, params) => get(`/map/territories/${id}`, params),
  locate: (q) => get("/map/locate", { q }),
};
