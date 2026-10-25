// Anwendungsrahmen: Anmeldung, Menüleiste, Symbolleiste, Befehlsfeld, Statusleiste, Navigation.
import { ApiError, get, post, setCsrf, setHandlers } from "./api.js";
import { clear, h } from "./dom.js";
import { renderForm } from "./pages/form.js";
import { renderList } from "./pages/list.js";
import { SYSTEM_PAGES } from "./pages/system.js";
import { bindStatus, errorStatus, status } from "./ui.js";

const root = document.getElementById("app");

export const ctx = {
  me: null, config: null, history: [], current: null, lastActivity: Date.now(), onExecute: null,
  navigate, reloadConfig, canOpen, fieldLabel, fieldDef, refreshHead,
};

let timerHandle = null;
let menuListener = null;
let headHandle = null;
let sbUser, sbHead, sbTimer, workTitle, workBody, menubar;

setHandlers({
  unauthorized: (msg) => showLogin(msg || "Bitte anmelden."),
  activity: () => { ctx.lastActivity = Date.now(); },
});

// ------------------------------------------------------------------ Anmeldung
function showLogin(message) {
  clearInterval(timerHandle);
  clearInterval(headHandle);
  ctx.me = null;
  setCsrf(null);
  clear(root);
  const user = h("input", { id: "lg_user", autocomplete: "username", required: true, maxlength: 64 });
  const pass = h("input", { id: "lg_pass", type: "password", autocomplete: "current-password", required: true });
  const msg = h("div", { class: "login-msg" }, message || "");
  const form = h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    msg.textContent = "Anmeldung läuft …";
    try {
      const r = await post("/api/login", { username: user.value, password: pass.value });
      setCsrf(r.csrf);
      await start();
    } catch (err) {
      msg.textContent = err.message;
      pass.value = "";
      pass.focus();
    }
  } },
  h("div", { class: "frow" }, h("label", { for: "lg_user" }, "Benutzer"), h("div", { class: "fcell" }, user)),
  h("div", { class: "frow" }, h("label", { for: "lg_pass" }, "Passwort"), h("div", { class: "fcell" }, pass)),
  msg,
  h("div", { class: "dlg-buttons" }, h("button", { type: "submit", class: "btn btn-primary" }, "Anmelden")));
  root.append(h("div", { class: "login-screen" },
    h("div", { class: "window login" },
      h("div", { class: "titlebar" }, h("span", {}, "Lager Heim – Anmeldung")),
      h("div", { class: "login-body" },
        h("div", { class: "login-logo", "aria-hidden": "true" }, h("div", { class: "logo-box" }), h("div", { class: "logo-box b2" })),
        form))));
  user.focus();
}

// ------------------------------------------------------------------ Start
async function start() {
  const me = await get("/api/me", { noRedirect: true });
  setCsrf(me.csrf);
  ctx.me = me;
  ctx.config = await get("/api/config");
  buildShell();
  startTimers();
  const t = new URLSearchParams(location.search).get("t");
  if (me.user.must_change_pw) {
    navigate("SYS_PASSWORT");
    status("Bitte zuerst ein eigenes Passwort vergeben.", "warn");
  } else if (t && !runTcode(t)) {
    navigate("SYS_START");
  } else if (!t) {
    navigate("SYS_START");
    if (me.ablaufend > 0) {
      status(`${me.ablaufend} Bestandsposition(en) mit MHD in den nächsten ${me.ablauf_tage} Tagen (T-Code ZB02).`, "warn");
    } else status(`Angemeldet als ${me.user.username}.`, "ok");
  }
}

async function reloadConfig() {
  ctx.config = await get("/api/config");
  buildMenu();
}

async function refreshHead(background = true) {
  try {
    const me = await get("/api/me", { background });
    ctx.me = me;
    sbHead.textContent = `Protokoll #${me.head.seq} · ${me.head.hash.slice(0, 12)}`;
    sbHead.title = "Aktuelle Kettenspitze des Protokolls:\n" + me.head.hash;
  } catch { /* 401 wird zentral behandelt */ }
}

function startTimers() {
  clearInterval(timerHandle);
  clearInterval(headHandle);
  ctx.lastActivity = Date.now();
  timerHandle = setInterval(() => {
    const left = ctx.me.timeout_min * 60 - Math.floor((Date.now() - ctx.lastActivity) / 1000);
    if (left <= 0) {
      showLogin("Sitzung wegen Inaktivität abgelaufen. Bitte neu anmelden.");
      return;
    }
    const m = Math.floor(left / 60), s = String(left % 60).padStart(2, "0");
    sbTimer.textContent = `Sitzung ${m}:${s}`;
  }, 1000);
  headHandle = setInterval(() => refreshHead(true), 60000);
}

// ------------------------------------------------------------------ Rahmen
function buildShell() {
  clear(root);
  menubar = h("nav", { class: "menubar", "aria-label": "Hauptmenü" });
  const cmd = h("input", { class: "cmdfield", id: "cmdfield", placeholder: "T-Code", maxlength: 14,
    "aria-label": "Befehlsfeld (Transaktionscode)", autocomplete: "off",
    onkeydown: (e) => { if (e.key === "Enter") { runTcode(cmd.value); cmd.value = ""; } } });
  const tb = (icon, title, fn) => h("button", { class: "tbtn", type: "button", title, "aria-label": title, onclick: fn },
    h("span", { class: "ico" }, icon));
  const toolbar = h("div", { class: "toolbar" },
    h("div", { class: "cmdwrap" },
      h("button", { class: "tbtn ok", type: "button", title: "Ausführen (Enter)", onclick: () => { runTcode(cmd.value); cmd.value = ""; } }, h("span", { class: "ico" }, "✔")),
      cmd),
    h("span", { class: "tsep" }),
    tb("◀", "Zurück (F3)", back),
    tb("⌂", "Startbild (ZS00)", () => navigate("SYS_START")),
    h("span", { class: "tsep" }),
    tb("+", "Einchecken (ZE01)", () => runTcode("ZE01")),
    tb("−", "Auschecken (ZA01)", () => runTcode("ZA01")),
    tb("▤", "Bestandsliste (ZB01)", () => runTcode("ZB01")),
    tb("§", "Protokoll (ZP01)", () => runTcode("ZP01")),
    h("span", { class: "tsep" }),
    tb("⟳", "Aktualisieren", () => ctx.current && navigate(ctx.current.code, ctx.current.params, { push: false })),
    h("span", { class: "tspacer" }),
    tb("⏻", "Abmelden", logout));

  workTitle = h("span", {});
  workBody = h("div", { class: "work-body" });
  const work = h("main", { class: "window work" }, h("div", { class: "titlebar" }, workTitle), workBody);

  const msg = h("div", { class: "sb-msg" });
  bindStatus(msg);
  sbUser = h("div", { class: "sb-panel" }, `${ctx.me.user.username} (${ctx.me.user.role === "ADMIN" ? "Admin" : "Benutzer"})`);
  sbHead = h("div", { class: "sb-panel sb-head" });
  sbTimer = h("div", { class: "sb-panel" });
  const statusbar = h("footer", { class: "statusbar" }, msg, sbUser, sbHead, sbTimer);

  root.append(h("div", { class: "shell" },
    h("header", { class: "apptitle" }, h("span", { class: "app-ico", "aria-hidden": "true" }), "Lager Heim",
      h("span", { class: "apptitle-right" }, "Mandant HEIM · v" + ctx.me.version)),
    menubar, toolbar, work, statusbar));
  buildMenu();
  refreshHead(true);
}

function buildMenu() {
  clear(menubar);
  const menus = ctx.config.menus;
  const tops = menus.filter((m) => m.parent_id === null).sort((a, b) => a.sort - b.sort);
  const closeAll = () => menubar.querySelectorAll(".menu.open").forEach((m) => m.classList.remove("open"));
  for (const top of tops) {
    const items = menus.filter((m) => m.parent_id === top.id && pageByCode(m.target) && canOpen(pageByCode(m.target)))
      .sort((a, b) => a.sort - b.sort);
    if (!items.length && !top.target) continue;
    const drop = h("ul", { class: "dropdown", role: "menu" }, items.map((it) => {
      const tc = ctx.config.tcodes.find((t) => t.target === it.target);
      return h("li", { role: "none" }, h("button", { type: "button", role: "menuitem", onclick: () => { closeAll(); navigate(it.target); } },
        h("span", {}, it.label), h("span", { class: "mi-tcode" }, tc ? tc.code : "")));
    }));
    const menu = h("div", { class: "menu" },
      h("button", { type: "button", class: "menu-title", "aria-haspopup": "true", onclick: (e) => {
        e.stopPropagation();
        const wasOpen = menu.classList.contains("open");
        closeAll();
        if (top.target && !items.length) { navigate(top.target); return; }
        if (!wasOpen) menu.classList.add("open");
      }, onmouseenter: () => { if (menubar.querySelector(".menu.open") && !menu.classList.contains("open")) { closeAll(); menu.classList.add("open"); } } }, top.label),
      drop);
    menubar.append(menu);
  }
  if (!menuListener) {
    menuListener = () => menubar.querySelectorAll(".menu.open").forEach((m) => m.classList.remove("open"));
    document.addEventListener("click", menuListener);
  }
}

// ------------------------------------------------------------------ Navigation
function pageByCode(code) { return ctx.config.pages.find((p) => p.code === code); }

const SYSTEM_FUNCTION = (code) => (SYSTEM_PAGES[code] || {}).fn;

function canOpen(page) {
  const caps = ctx.config.capabilities;
  if (!page) return false;
  if (page.kind === "SYSTEM") {
    const fn = SYSTEM_FUNCTION(page.code);
    return !fn || (Array.isArray(caps[fn]) ? caps[fn].length > 0 : !!caps[fn]);
  }
  if (page.kind === "FORM") {
    const f = page.config.action === "einchecken" ? "EINCHECKEN" : "AUSCHECKEN";
    return caps[f].length > 0;
  }
  if (page.config.source === "articles") return true;
  return caps.BESTAND_LESEN.length > 0;
}

function runTcode(text) {
  let t = String(text || "").trim().toUpperCase();
  if (!t) return false;
  let newWindow = false;
  if (t.startsWith("/N")) t = t.slice(2);
  else if (t.startsWith("/O")) { t = t.slice(2); newWindow = true; }
  const tc = ctx.config.tcodes.find((x) => x.code === t);
  if (!tc) {
    status(`Transaktion ${t} existiert nicht.`, "error");
    return false;
  }
  if (newWindow) {
    window.open(location.pathname + "?t=" + encodeURIComponent(t), "_blank", "noopener");
    return true;
  }
  return navigate(tc.target);
}

function navigate(code, params = {}, opts = {}) {
  const page = pageByCode(code);
  if (!page) { status(`Seite ${code} existiert nicht.`, "error"); return false; }
  if (!canOpen(page)) { status("Keine Berechtigung für diese Transaktion.", "error"); return false; }
  if (opts.push !== false && ctx.current && ctx.current.code !== code) ctx.history.push(ctx.current);
  if (ctx.history.length > 30) ctx.history.shift();
  ctx.current = { code, params };
  ctx.onExecute = null;
  if (opts.keepStatus !== true) status("");
  const tc = ctx.config.tcodes.find((t) => t.target === code);
  workTitle.textContent = page.title + (tc ? `  (${tc.code})` : "");
  document.title = page.title + " – Lager Heim";
  clear(workBody);
  const container = h("div", { class: "page" });
  workBody.append(container);
  try {
    if (page.kind === "LIST") renderList(ctx, page, container, params);
    else if (page.kind === "FORM") renderForm(ctx, page, container, params);
    else SYSTEM_PAGES[page.code].render(ctx, container, params);
  } catch (e) { errorStatus(e); }
  return true;
}

function back() {
  const prev = ctx.history.pop();
  if (prev) navigate(prev.code, prev.params, { push: false });
  else navigate("SYS_START", {}, { push: false });
}

async function logout() {
  try { await post("/api/logout"); } catch { /* ignorieren */ }
  showLogin("Abgemeldet.");
}

// ------------------------------------------------------------------ Felder
function fieldDef(code) { return ctx.config.fields.find((f) => f.code === code); }

function fieldLabel(code, item) {
  if (item && item.label) return item.label;
  const cat = ctx.config.catalog;
  for (const cols of Object.values(cat.system_columns)) {
    const c = cols.find(([k]) => k === code);
    if (c) return c[1];
  }
  for (const fs of Object.values(cat.form_system_fields)) {
    const c = fs.find(([k]) => k === code);
    if (c) return c[1];
  }
  const f = fieldDef(code);
  return f ? f.label : code;
}

// ------------------------------------------------------------------ Tastatur
document.addEventListener("keydown", (e) => {
  if (!ctx.me) return;
  if (e.key === "F3") { e.preventDefault(); back(); }
  if (e.key === "F8") { e.preventDefault(); if (ctx.onExecute) ctx.onExecute(); }
  if (e.key === "F6" || (e.ctrlKey && e.key === "/")) { e.preventDefault(); document.getElementById("cmdfield")?.focus(); }
});

// ------------------------------------------------------------------ Boot
// ------------------------------------------------------------------ Ersteinrichtung (PC-Version)
function showSetup() {
  clear(root);
  const user = h("input", { id: "su_user", autocomplete: "username", required: true, maxlength: 32 });
  const pass = h("input", { id: "su_pass", type: "password", autocomplete: "new-password", required: true });
  const pass2 = h("input", { id: "su_pass2", type: "password", autocomplete: "new-password", required: true });
  const msg = h("div", { class: "login-msg" });
  const row = (id, label, el) => h("div", { class: "frow" }, h("label", { for: id }, label), h("div", { class: "fcell" }, el));
  const form = h("form", { class: "form", onsubmit: async (e) => {
    e.preventDefault();
    if (pass.value !== pass2.value) { msg.textContent = "Die Passwörter stimmen nicht überein."; return; }
    try {
      await post("/api/setup", { username: user.value, password: pass.value });
      const r = await post("/api/login", { username: user.value, password: pass.value });
      setCsrf(r.csrf);
      await start();
    } catch (err) { msg.textContent = err.message; }
  } },
  h("p", { class: "dlg-text" }, "Willkommen! Bitte zuerst das Admin-Konto anlegen. Es gibt genau einen Admin; weitere Benutzer legt der Admin später unter ZU01 an."),
  row("su_user", "Benutzer", user), row("su_pass", "Passwort", pass), row("su_pass2", "Wiederholung", pass2),
  h("p", { class: "hint" }, "Passwort: mindestens 8 Zeichen."), msg,
  h("div", { class: "dlg-buttons" }, h("button", { type: "submit", class: "btn btn-primary" }, "Admin anlegen")));
  root.append(h("div", { class: "login-screen" }, h("div", { class: "window login" },
    h("div", { class: "titlebar" }, h("span", {}, "Lager Heim – Ersteinrichtung")),
    h("div", { class: "login-body" }, form))));
  user.focus();
}

(async function boot() {
  try {
    await start();
  } catch (e) {
    let setup = { needed: false };
    try { setup = await get("/api/setup", { noRedirect: true }); } catch { /* ignorieren */ }
    if (setup.needed) showSetup();
    else showLogin(e instanceof ApiError && e.status === 401 ? "" : e.message);
  }
})();
