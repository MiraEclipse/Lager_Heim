// Systemseiten: Startbild, Protokoll, Prüfung/Quittung, Passwort, Benutzer, Backup.
import { get, post, put, qs } from "../api.js";
import { STORE_NAMES, clear, fmtDateTime, h } from "../dom.js";
import { alertBox, btn, confirmBox, errorStatus, formDialog, group, input, modal, status, table } from "../ui.js";
import { CUSTOMIZING_PAGES } from "./customizing.js";

// ------------------------------------------------------------------ Startbild
function renderStart(ctx, c) {
  const me = ctx.me;
  const tcodes = ctx.config.tcodes.filter((t) => ctx.canOpen(ctx.config.pages.find((p) => p.code === t.target)));
  c.append(
    group("Willkommen",
      h("p", {}, `Angemeldet als ${me.user.username}. Mit dem Befehlsfeld oben links (F6) springen Sie direkt in eine Transaktion, z. B. ZE01 für Einchecken. Mit /o vor dem Code öffnet sich ein neues Fenster.`),
      me.ablaufend > 0 ? h("p", { class: "note warn" }, `${me.ablaufend} Bestandsposition(en) erreichen in den nächsten ${me.ablauf_tage} Tagen das MHD.`,
        " ", btn("Anzeigen (ZB02)", () => ctx.navigate("ABLAUF_LISTE"))) : null,
      h("p", { class: "hint" }, `Protokoll: ${me.head.seq} Einträge · Kettenspitze ${me.head.hash}`)),
    group("Transaktionen", table([
      { key: "code", label: "T-Code" }, { key: "description", label: "Beschreibung" },
    ], tcodes, { actions: (t) => btn("Öffnen", () => ctx.navigate(t.target)), sort: { field: "code", dir: "asc" } })),
  );
}

// ------------------------------------------------------------------ Protokoll
const ACTION_LABELS = {
  EINCHECKEN: "Einchecken", AUSCHECKEN: "Auschecken", LOGIN: "Anmeldung", LOGOUT: "Abmeldung",
  LOGIN_FEHLGESCHLAGEN: "Anmeldung fehlgeschlagen", LOGIN_GESPERRT: "Anmeldung gesperrt",
  SITZUNG_ABGELAUFEN: "Sitzung abgelaufen", BENUTZER_ANGELEGT: "Benutzer angelegt",
  BENUTZER_GESPERRT: "Benutzer gesperrt", BENUTZER_ENTSPERRT: "Benutzer entsperrt",
  PASSWORT_GEAENDERT: "Passwort geändert", PASSWORT_ZURUECKGESETZT: "Passwort zurückgesetzt",
  LOGINSPERRE_AUFGEHOBEN: "Loginsperre aufgehoben", ARTIKEL_ANGELEGT: "Artikel angelegt",
  ARTIKEL_GEAENDERT: "Artikel geändert", CUSTOMIZING_ANGELEGT: "Customizing: angelegt",
  CUSTOMIZING_GEAENDERT: "Customizing: geändert", CUSTOMIZING_GELOESCHT: "Customizing: gelöscht",
  CUSTOMIZING_RUECKSETZUNG: "Customizing: Rücksetzung", RECHT_GEAENDERT: "Recht geändert",
  EINSTELLUNG_GEAENDERT: "Einstellung geändert", BACKUP_ERSTELLT: "Backup erstellt",
  BACKUP_HERUNTERGELADEN: "Backup heruntergeladen", BACKUP_ROTATION: "Backup-Rotation",
  WIEDERHERSTELLUNG: "Wiederherstellung", NOTFALL_WIEDERHERSTELLUNG: "Notfall-Wiederherstellung",
  INSTALLATION: "Installation",
};

function short(json) {
  if (!json) return "";
  try {
    const o = JSON.parse(json);
    if (o && typeof o === "object") {
      return Object.entries(o).filter(([k]) => !k.startsWith("_") || k === "_version")
        .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(", ");
    }
    return String(o);
  } catch { return json; }
}

function pretty(json) {
  if (!json) return "–";
  try { return JSON.stringify(JSON.parse(json), null, 2); } catch { return json; }
}

function renderLog(ctx, c) {
  const defs = [
    { key: "aktion", label: "Aktion enthält" }, { key: "benutzer", label: "Benutzer" },
    { key: "bestand", label: "Bestand", type: "select", options: [{ value: "", label: "(alle)" },
      { value: "KELLER", label: "Keller" }, { value: "PRIVAT", label: "Mein Bestand" }] },
    { key: "objekt", label: "Suchtext (Objekt/Werte)" },
    { key: "von", label: "Datum von", type: "date" }, { key: "bis", label: "Datum bis", type: "date" },
    { key: "nur_admin", label: "Nur Admin-Eingriffe", type: "checkbox" },
  ];
  const inputs = defs.map((d) => ({ d, i: input(d) }));
  const result = h("div");
  const columns = [
    { key: "seq", label: "Nr." },
    { key: "ts", label: "Zeitpunkt", fmt: fmtDateTime },
    { key: "username", label: "Benutzer" },
    { key: "action", label: "Aktion", fmt: (v) => ACTION_LABELS[v] || v },
    { key: "store_code", label: "Bestand", fmt: (v) => STORE_NAMES[v] || v },
    { key: "admin_eingriff", label: "Admin-Eingriff", fmt: (v) => (v ? "JA" : "") },
    { key: "object_id", label: "Objekt", fmt: (v, r) => `${r.object_type} ${v}` },
    { key: "old_value", label: "Alter Wert", fmt: short, cls: "clip" },
    { key: "new_value", label: "Neuer Wert", fmt: short, cls: "clip" },
    { key: "hash", label: "Hash", fmt: (v) => v.slice(0, 10) },
  ];
  async function run() {
    const q = {};
    for (const { d, i } of inputs) q[d.key] = i.get();
    try {
      const rows = await get("/api/protokoll" + qs(q));
      clear(result).append(table(columns, rows, {
        sort: { field: "seq", dir: "desc" },
        rowClass: (r) => (r.admin_eingriff ? "admin" : r.action.includes("FEHL") || r.action.includes("GESPERRT") ? "hl" : ""),
        onRowDblClick: detail,
        actions: (r) => btn("Details", () => detail(r)),
        emptyText: "Keine Protokolleinträge zur Selektion.",
      }));
      status(`${rows.length} Protokolleinträge (max. 1000, neueste zuerst). Doppelklick zeigt Details.`, "ok");
    } catch (e) { errorStatus(e); }
  }
  function detail(r) {
    const rowsDl = [
      ["Nr.", r.seq], ["Zeitpunkt", fmtDateTime(r.ts) + "  (" + r.ts + ")"], ["Benutzer", r.username],
      ["Aktion", (ACTION_LABELS[r.action] || r.action) + "  (" + r.action + ")"],
      ["Objekt", r.object_type + " " + r.object_id], ["Bestand", STORE_NAMES[r.store_code] || r.store_code || "–"],
      ["Admin-Eingriff", r.admin_eingriff ? "JA" : "nein"], ["IP-Adresse", r.ip || "–"],
      ["Vorgänger-Hash", r.prev_hash], ["Hash", r.hash],
    ];
    modal(`Protokolleintrag ${r.seq}`, h("div", {},
      h("dl", { class: "dl" }, rowsDl.map(([k, v]) => [h("dt", {}, k), h("dd", { class: "mono" }, String(v))])),
      h("div", { class: "cols2" },
        h("div", {}, h("h4", {}, "Alter Wert"), h("pre", {}, pretty(r.old_value))),
        h("div", {}, h("h4", {}, "Neuer Wert"), h("pre", {}, pretty(r.new_value))))),
    [{ label: "Schließen", primary: true, value: true }], { wide: true });
  }
  c.append(
    group("Selektion", h("form", { class: "form selection", onsubmit: (e) => { e.preventDefault(); run(); } },
      h("div", { class: "fgrid" }, inputs.map((x) => x.i.row)),
      h("div", { class: "btnrow" }, btn("Ausführen (F8)", null, { submit: true, primary: true, icon: "▶" }),
        btn("Prüfen / Quittung (ZP02)", () => ctx.navigate("SYS_PRUEFUNG"))))),
    h("p", { class: "hint" }, "Das Protokoll ist unveränderlich (append-only). Es kann weder über die Oberfläche noch durch den Admin geändert oder gelöscht werden. Jeder Eintrag ist per Hash mit seinem Vorgänger verkettet."),
    result);
  ctx.onExecute = run;
  run();
}

// ------------------------------------------------------------------ Prüfung / Quittung
function renderVerify(ctx, c) {
  const out = h("div");
  const receiptOut = h("div");
  async function check() {
    clear(out).append(h("p", { class: "hint" }, "Prüfung läuft …"));
    try {
      const r = await get("/api/protokoll/pruefen");
      clear(out).append(
        h("p", { class: "note " + (r.kette.ok ? "good" : "bad") }, (r.kette.ok ? "✔ " : "✖ ") + r.kette.message),
        h("p", { class: "note " + (r.bestand.ok ? "good" : "bad") }, (r.bestand.ok ? "✔ " : "✖ ") + r.bestand.message),
        r.kette.ok ? h("p", { class: "mono small" }, `Kettenspitze: Eintrag ${r.kette.head_seq} · ${r.kette.head_hash}`) : null,
        h("p", { class: "hint" }, "Geprüft am " + fmtDateTime(r.geprueft_am)));
      status(r.kette.ok && r.bestand.ok ? "Prüfung erfolgreich." : "Prüfung hat Abweichungen gefunden!",
        r.kette.ok && r.bestand.ok ? "ok" : "error");
    } catch (e) { errorStatus(e); }
  }
  const file = h("input", { type: "file", accept: "application/json,.json" });
  async function checkReceipt() {
    const f = file.files[0];
    if (!f) { status("Bitte zuerst eine Quittungsdatei wählen.", "warn"); return; }
    try {
      const q = JSON.parse(await f.text());
      const r = await post("/api/protokoll/quittung", { seq: q.seq, hash: q.hash });
      clear(receiptOut).append(h("p", { class: "note " + (r.ok ? "good" : "bad") }, (r.ok ? "✔ " : "✖ ") + r.message),
        h("p", { class: "hint" }, `Quittung vom ${fmtDateTime(q.ausgestellt_am)} für ${q.ausgestellt_fuer || "?"}: Eintrag ${q.seq}`));
      status(r.message, r.ok ? "ok" : "error");
    } catch (e) {
      clear(receiptOut).append(h("p", { class: "note bad" }, "Quittung konnte nicht geprüft werden: " + e.message));
    }
  }
  c.append(
    group("Integritätsprüfung",
      h("p", {}, "Rechnet die gesamte Hash-Kette nach und prüft, ob jeder Bestand exakt der Summe seiner Buchungen entspricht."),
      h("div", { class: "btnrow" }, btn("Jetzt prüfen", check, { primary: true, icon: "✔" })), out),
    group("Quittung",
      h("p", {}, "Eine Quittung hält den aktuellen Stand des Protokolls fest (Nummer und Hash des letzten Eintrags). Jeder Benutzer kann sie herunterladen und aufbewahren. Würde das Protokoll später nachträglich verändert – selbst mit vollständig neu berechneter Kette –, schlägt die Prüfung der Quittung fehl."),
      h("div", { class: "btnrow" },
        h("a", { class: "btn", href: "/api/protokoll/quittung", download: "" }, h("span", { class: "ico" }, "⇩"), "Quittung herunterladen"),
        h("a", { class: "btn", href: "/api/protokoll/export", download: "" }, h("span", { class: "ico" }, "⇩"), "Gesamtes Protokoll exportieren (JSON)")),
      h("div", { class: "frow" }, h("label", {}, "Quittung prüfen"), h("div", { class: "fcell" }, file, btn("Prüfen", checkReceipt))),
      receiptOut));
  ctx.onExecute = check;
  check();
}

// ------------------------------------------------------------------ Passwort
function renderPassword(ctx, c) {
  const alt = input({ key: "alt", label: "Bisheriges Passwort", type: "password", required: true, autocomplete: "current-password" });
  const neu = input({ key: "neu", label: "Neues Passwort", type: "password", required: true, autocomplete: "new-password", hint: "mindestens 8 Zeichen" });
  const neu2 = input({ key: "neu2", label: "Wiederholung", type: "password", required: true, autocomplete: "new-password" });
  c.append(h("form", { class: "form mask", onsubmit: async (e) => {
    e.preventDefault();
    if (neu.get() !== neu2.get()) { status("Die neuen Passwörter stimmen nicht überein.", "error"); return; }
    try {
      await post("/api/passwort", { alt: alt.get(), neu: neu.get() });
      status("Passwort geändert.", "ok");
      if (ctx.me.user.must_change_pw) location.reload();
      alt.el.value = neu.el.value = neu2.el.value = "";
    } catch (err) { errorStatus(err); }
  } }, group("Passwort ändern", alt.row, neu.row, neu2.row),
  h("div", { class: "btnrow" }, btn("Speichern", null, { submit: true, primary: true, icon: "✔" }))));
  alt.el.focus();
}

// ------------------------------------------------------------------ Benutzer
function renderUsers(ctx, c) {
  const result = h("div");
  async function load() {
    try {
      const list = await get("/api/benutzer");
      clear(result).append(table([
        { key: "id", label: "ID" }, { key: "username", label: "Benutzer" },
        { key: "role", label: "Rolle", fmt: (v) => (v === "ADMIN" ? "Admin" : "Benutzer") },
        { key: "active", label: "Status", fmt: (v) => (v ? "aktiv" : "GESPERRT") },
        { key: "must_change_pw", label: "Passwortwechsel offen", fmt: (v) => (v ? "ja" : "") },
        { key: "created_at", label: "Angelegt", fmt: fmtDateTime },
        { key: "last_login", label: "Letzte Anmeldung", fmt: fmtDateTime },
      ], list, {
        rowClass: (u) => (u.active ? "" : "disabled"),
        actions: (u) => (u.role === "ADMIN" ? h("span", { class: "hint" }, "Admin") : [
          btn(u.active ? "Sperren" : "Entsperren", () => toggle(u)),
          btn("Passwort zurücksetzen", () => resetPw(u)),
          btn("Loginsperre aufheben", () => change(u, { unlock: true }, "Loginsperre aufgehoben.")),
        ]),
      }));
    } catch (e) { errorStatus(e); }
  }
  async function change(u, body, msg) {
    try { await put(`/api/benutzer/${u.id}`, body); status(msg, "ok"); load(); } catch (e) { errorStatus(e); }
  }
  async function toggle(u) {
    if (u.active && !(await confirmBox("Benutzer sperren", `Benutzer ${u.username} sperren? Laufende Sitzungen werden beendet.`))) return;
    change(u, { active: !u.active }, u.active ? "Benutzer gesperrt." : "Benutzer entsperrt.");
  }
  function resetPw(u) {
    formDialog(`Passwort für ${u.username} zurücksetzen`, [
      { key: "password", label: "Startpasswort", type: "password", required: true, hint: "Benutzer muss es bei der nächsten Anmeldung ändern." },
    ], async (v) => { await put(`/api/benutzer/${u.id}`, { password: v.password }); status("Passwort zurückgesetzt.", "ok"); load(); });
  }
  function create() {
    formDialog("Benutzer anlegen", [
      { key: "username", label: "Benutzername", required: true, maxlength: 32, hint: "3–32 Zeichen: Buchstaben, Ziffern, . - _" },
      { key: "password", label: "Startpasswort", type: "password", required: true, hint: "mind. 8 Zeichen, muss beim ersten Login geändert werden" },
    ], async (v) => { await post("/api/benutzer", v); status(`Benutzer ${v.username} angelegt.`, "ok"); load(); },
    { intro: "Neue Konten erhalten die Rolle „Benutzer“. Es gibt genau einen Admin." });
  }
  c.append(h("div", { class: "btnrow" }, btn("Benutzer anlegen", create, { primary: true, icon: "+" })), result);
  load();
}

// ------------------------------------------------------------------ Backup
function renderBackup(ctx, c) {
  const result = h("div");
  async function load() {
    try {
      const list = await get("/api/backup");
      clear(result).append(table([
        { key: "name", label: "Datei" }, { key: "ts", label: "Zeitpunkt", fmt: fmtDateTime },
        { key: "anlass", label: "Anlass" },
        { key: "size", label: "Größe", fmt: (v) => (v / 1024).toFixed(0) + " KB", cls: "num" },
        { key: "head_seq", label: "Protokollstand", cls: "num" },
      ], list, {
        sort: { field: "name", dir: "desc" },
        actions: (b) => [
          h("a", { class: "btn", href: `/api/backup/${encodeURIComponent(b.name)}`, download: b.name }, "Herunterladen"),
          btn("Wiederherstellen", () => restore(b), { danger: true }),
        ],
        emptyText: "Noch keine Backups vorhanden.",
      }));
    } catch (e) { errorStatus(e); }
  }
  async function create() {
    try { const r = await post("/api/backup"); status(r.message, "ok"); load(); } catch (e) { errorStatus(e); }
  }
  function restore(b) {
    formDialog(`Wiederherstellung aus ${b.name}`, [
      { key: "bestaetigung", label: "Zur Bestätigung WIEDERHERSTELLEN eingeben", required: true },
    ], async (v) => {
      const r = await post(`/api/backup/${encodeURIComponent(b.name)}/wiederherstellen`, { bestaetigung: v.bestaetigung });
      await alertBox("Wiederherstellung", `${r.message} Vorher wurde automatisch das Sicherheits-Backup ${r.sicherung_vorher} erstellt. Bitte neu anmelden.`);
      location.reload();
    }, { saveLabel: "Wiederherstellen", intro: "Bestände, Benutzer und Customizing werden auf den Stand des Backups gesetzt. Das Protokoll bleibt vollständig erhalten; die Wiederherstellung wird darin vermerkt. Vorher wird automatisch ein Sicherheits-Backup erstellt." });
  }
  c.append(
    h("p", { class: "hint" }, "Automatische Backups laufen täglich (Uhrzeit unter Einstellungen). Aufbewahrt werden die letzten 7 täglichen und 4 wöchentlichen Backups; manuelle Backups bleiben erhalten."),
    h("div", { class: "btnrow" }, btn("Backup jetzt erstellen", create, { primary: true, icon: "+" })), result);
  load();
}

export const SYSTEM_PAGES = {
  SYS_START: { render: renderStart },
  SYS_PROTOKOLL: { fn: "PROTOKOLL_LESEN", render: renderLog },
  SYS_PRUEFUNG: { fn: "PROTOKOLL_LESEN", render: renderVerify },
  SYS_PASSWORT: { render: renderPassword },
  SYS_BENUTZER: { fn: "BENUTZER", render: renderUsers },
  SYS_BACKUP: { fn: "BACKUP", render: renderBackup },
  ...CUSTOMIZING_PAGES,
};
