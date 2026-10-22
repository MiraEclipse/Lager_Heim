// Zugriff auf die Server-API inklusive CSRF-Token.

let csrf = null;
let onUnauthorized = () => {};
let onActivity = () => {};

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body || {};
  }
}

export function setCsrf(token) { csrf = token; }
export function setHandlers(h) {
  onUnauthorized = h.unauthorized || onUnauthorized;
  onActivity = h.activity || onActivity;
}

export async function api(method, url, body, opts = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrf) headers["X-CSRF-Token"] = csrf;
  if (opts.background) headers["X-LH-Hintergrund"] = "1";
  const res = await fetch(url, {
    method, headers, credentials: "same-origin",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { data = null; }
  if (!res.ok) {
    const msg = (data && data.detail) || `Fehler ${res.status}`;
    if (res.status === 401 && !opts.noRedirect) onUnauthorized(typeof msg === "string" ? msg : "");
    throw new ApiError(res.status, typeof msg === "string" ? msg : "Ungültige Eingabe.", data);
  }
  if (!opts.background) onActivity();
  return data;
}

export const get = (url, opts) => api("GET", url, undefined, opts);
export const post = (url, body = {}) => api("POST", url, body);
export const put = (url, body = {}) => api("PUT", url, body);
export const del = (url) => api("DELETE", url);

export function qs(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== "" && v !== null && v !== undefined && v !== false) p.set(k, v === true ? "1" : v);
  }
  const s = p.toString();
  return s ? "?" + s : "";
}
