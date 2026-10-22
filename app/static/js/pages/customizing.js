// Customizing ohne Programmieren: Felder, Kategorien, Seiten/Masken, Menüs/T-Codes, Regeln, Rechte,
// Versionen, Einstellungen. Jede Änderung wird serverseitig versioniert und protokolliert.
import { del, get, post, put } from "../api.js";
import { STORE_NAMES, clear, fmtDateTime, h } from "../dom.js";
import { btn, confirmBox, errorStatus, formDialog, group, input, modal, status, table } from "../ui.js";
import { FILTER_LABELS } from "./list.js";

const yesNo = (v) => (v ? "ja" : "");
const opts = (obj) => Object.entries(obj).map(([value, label]) => ({ value, label }));

async function afterChange(ctx, msg, reload) {
  status(msg + " (neue Customizing-Version, protokolliert)", "ok");
  await ctx.reloadConfig();
  if (reload) reload();
}

async function remove(ctx, table_, pk, label, reload) {
  if (!(await confirmBox("Löschen", `${label} wirklich löschen? (Über „Versionen“ wiederherstellbar.)`))) return;
  try { await del(`/api/customizing/${table_}/${encodeURIComponent(pk)}`); await afterChange(ctx, "Gelöscht.", reload); }
  catch (e) { errorStatus(e); }
}

// ------------------------------------------------------------------ Felder
function renderFields(ctx, c) {
  const result = h("div");
  const cat = ctx.config.catalog;
  async function load() {
    const rows = await get("/api/customizing/meta_field");
    clear(result).append(table([
      { key: "code", label: "Feldcode" }, { key: "label", label: "Bezeichnung" },
      { key: "entity", label: "Gehört zu", fmt: (v) => cat.entities[v] },
      { key: "type", label: "Typ", fmt: (v) => cat.field_types[v] },
      { key: "required", label: "Pflicht", fmt: yesNo },
      { key: "options", label: "Auswahlwerte", fmt: (v) => v.join("; ") },
      { key: "default_value", label: "Vorschlagswert" }, { key: "sort", label: "Sort." },
      { key: "active", label: "Aktiv", fmt: yesNo },
    ], rows, {
      rowClass: (r) => (r.active ? "" : "disabled"),
      actions: (r) => [btn("Bearbeiten", () => edit(r)), btn("Löschen", () => remove(ctx, "meta_field", r.id, `Feld ${r.code}`, load))],
      emptyText: "Noch keine eigenen Felder angelegt.",
    }));
  }
  function edit(r) {
    const isNew = !r;
    r = r || { entity: "buchung", type: "TEXT", required: 0, options: [], default_value: "", sort: 0, active: 1 };
    formDialog(isNew ? "Feld anlegen" : `Feld ${r.code} bearbeiten`, [
      { key: "entity", label: "Gehört zu", type: "select", options: opts(cat.entities), value: r.entity, disabled: !isNew },
      { key: "code", label: "Feldcode", value: r.code || "", disabled: !isNew, required: true,
        hint: "technischer Name: klein, z. B. preis_euro (nicht änderbar)" },
      { key: "label", label: "Bezeichnung", value: r.label || "", required: true },
      { key: "type", label: "Typ", type: "select", options: opts(cat.field_types), value: r.type, disabled: !isNew },
      { key: "required", label: "Pflichtfeld", type: "checkbox", value: r.required },
      { key: "options", label: "Auswahlwerte", value: r.options.join("; "), hint: "nur für Auswahlliste, getrennt durch ;" },
      { key: "default_value", label: "Vorschlagswert", value: r.default_value },
      { key: "sort", label: "Sortierung", type: "number", value: r.sort },
      { key: "active", label: "Aktiv", type: "checkbox", value: r.active },
    ], async (v) => {
      if (isNew) await post("/api/customizing/meta_field", v);
      else await put(`/api/customizing/meta_field/${r.id}`, v);
      await afterChange(ctx, "Feld gespeichert.", load);
    }, { intro: "Neue Felder erscheinen erst in einer Maske/Liste, wenn sie unter „Seiten und Masken“ (ZC03) hinzugefügt werden." });
  }
  c.append(h("div", { class: "btnrow" }, btn("Feld anlegen", () => edit(null), { primary: true, icon: "+" })), result);
  load().catch(errorStatus);
}

// ------------------------------------------------------------------ Kategorien
function renderCategories(ctx, c) {
  const result = h("div");
  async function load() {
    const rows = await get("/api/customizing/categories");
    clear(result).append(table([
      { key: "id", label: "ID" }, { key: "name", label: "Kategorie" }, { key: "sort", label: "Sort." },
      { key: "active", label: "Aktiv", fmt: yesNo },
    ], rows, { sort: { field: "sort", dir: "asc" }, rowClass: (r) => (r.active ? "" : "disabled"),
      actions: (r) => btn("Bearbeiten", () => edit(r)) }));
  }
  function edit(r) {
    const isNew = !r;
    r = r || { name: "", sort: 0, active: 1 };
    formDialog(isNew ? "Kategorie anlegen" : "Kategorie bearbeiten", [
      { key: "name", label: "Name", value: r.name, required: true, maxlength: 60 },
      { key: "sort", label: "Sortierung", type: "number", value: r.sort },
      { key: "active", label: "Aktiv", type: "checkbox", value: r.active },
    ], async (v) => {
      if (isNew) await post("/api/customizing/categories", v);
      else await put(`/api/customizing/categories/${r.id}`, v);
      await afterChange(ctx, "Kategorie gespeichert.", load);
    }, { intro: "Kategorien werden nicht gelöscht, sondern deaktiviert – bestehende Artikel behalten ihre Kategorie." });
  }
  c.append(h("div", { class: "btnrow" }, btn("Kategorie anlegen", () => edit(null), { primary: true, icon: "+" })), result);
  load().catch(errorStatus);
}

// ------------------------------------------------------------------ Seiten und Masken
function orderEditor(available, selected, locked = new Set()) {
  // available: [{key,label}], selected: [{field,label?}]
  let sel = selected.map((s) => ({ ...s }));
  const left = h("select", { size: 12, multiple: true, class: "olist", "aria-label": "Verfügbar" });
  const right = h("select", { size: 12, class: "olist", "aria-label": "Angezeigt" });
  const labelIn = h("input", { placeholder: "eigene Bezeichnung (optional)", maxlength: 60 });
  const name = (k) => (available.find((a) => a.key === k) || { label: k }).label;
  function render(focus) {
    clear(left);
    clear(right);
    for (const a of available.filter((a) => !sel.some((s) => s.field === a.key))) left.append(h("option", { value: a.key }, `${a.label} (${a.key})`));
    sel.forEach((s, i) => right.append(h("option", { value: String(i) },
      `${s.label || name(s.field)}${s.label ? " ← " + name(s.field) : ""}${locked.has(s.field) ? "  [System]" : ""}`)));
    if (focus !== undefined && right.options[focus]) right.selectedIndex = focus;
  }
  const idx = () => right.selectedIndex;
  const move = (d) => {
    const i = idx();
    if (i < 0 || i + d < 0 || i + d >= sel.length) return;
    [sel[i], sel[i + d]] = [sel[i + d], sel[i]];
    render(i + d);
  };
  right.addEventListener("change", () => { labelIn.value = sel[idx()] ? sel[idx()].label || "" : ""; });
  const el = h("div", { class: "order" },
    h("div", {}, h("div", { class: "olabel" }, "Verfügbar"), left),
    h("div", { class: "obuttons" },
      btn("→", () => { for (const o of [...left.selectedOptions]) sel.push({ field: o.value }); render(sel.length - 1); }, { title: "hinzufügen" }),
      btn("←", () => { const i = idx(); if (i >= 0 && !locked.has(sel[i].field)) { sel.splice(i, 1); render(); } }, { title: "entfernen" }),
      btn("↑", () => move(-1), { title: "nach oben" }), btn("↓", () => move(1), { title: "nach unten" })),
    h("div", {}, h("div", { class: "olabel" }, "Angezeigt (Reihenfolge)"), right,
      h("div", { class: "olabelrow" }, labelIn, btn("Bezeichnung übernehmen", () => {
        const i = idx();
        if (i < 0) return;
        if (labelIn.value.trim()) sel[i].label = labelIn.value.trim(); else delete sel[i].label;
        render(i);
      }))));
  render();
  return { el, value: () => sel };
}

function renderPages(ctx, c) {
  const cat = ctx.config.catalog;
  const result = h("div");
  const editor = h("div");
  async function load() {
    const rows = await get("/api/customizing/meta_page");
    clear(result).append(table([
      { key: "code", label: "Seitencode" }, { key: "title", label: "Titel" },
      { key: "kind", label: "Typ", fmt: (v) => ({ LIST: "Liste", FORM: "Eingabemaske", SYSTEM: "Systemseite" })[v] },
      { key: "config", label: "Datenquelle / Aktion", fmt: (v) => cat.source_names[v.source] || v.action || "" },
    ], rows, {
      sort: { field: "code", dir: "asc" },
      actions: (r) => [
        btn("Bearbeiten", () => openEditor(r)),
        btn("Öffnen", () => ctx.navigate(r.code)),
        r.system ? null : btn("Löschen", () => remove(ctx, "meta_page", r.code, `Seite ${r.code}`, load)),
      ],
    }));
  }

  function create() {
    formDialog("Neue Seite", [
      { key: "code", label: "Seitencode", required: true, hint: "Großbuchstaben, z. B. MEINE_LISTE" },
      { key: "title", label: "Titel", required: true },
      { key: "kind", label: "Typ", type: "select", options: [{ value: "LIST", label: "Liste" }, { value: "FORM", label: "Eingabemaske" }] },
      { key: "source", label: "Datenquelle (Liste)", type: "select", options: opts(cat.source_names) },
      { key: "action", label: "Aktion (Maske)", type: "select", options: [{ value: "einchecken", label: "Einchecken" }, { value: "auschecken", label: "Auschecken" }] },
    ], async (v) => {
      const config = v.kind === "LIST"
        ? { source: v.source, columns: cat.system_columns[v.source].map(([k]) => ({ field: k })), filters: [], sort: {}, preset: {} }
        : { action: v.action, fields: cat.form_system_fields[v.action].map(([k]) => ({ field: k })) };
      const page = await post("/api/customizing/meta_page", { code: v.code.toUpperCase(), title: v.title, kind: v.kind, config });
      await afterChange(ctx, `Seite ${page.code} angelegt.`, load);
      openEditor(page);
    }, { intro: "Danach Spalten/Felder anordnen und die Seite unter „Menüs und T-Codes“ (ZC04) einhängen." });
  }

  function openEditor(page) {
    clear(editor);
    const title = input({ key: "title", label: "Titel", value: page.title, required: true });
    const parts = [title.row];
    let collect = () => ({});
    const cfg = page.config;
    if (page.kind === "LIST") {
      const avail = [...cat.system_columns[cfg.source].map(([k, l]) => ({ key: k, label: l })),
        ...ctx.config.fields.filter((f) => cat.source_entities[cfg.source].includes(f.entity)).map((f) => ({ key: f.code, label: f.label }))];
      const cols = orderEditor(avail, cfg.columns);
      const filterBoxes = cat.filters[cfg.source].map((f) => ({ f, i: input({ key: "flt_" + f, label: FILTER_LABELS[f] || f, type: "checkbox", value: cfg.filters.includes(f) }) }));
      const sortField = input({ key: "sf", label: "Sortierung nach", type: "select", value: cfg.sort.field, options: avail.map((a) => ({ value: a.key, label: a.label })) });
      const sortDir = input({ key: "sd", label: "Richtung", type: "select", value: cfg.sort.dir, options: [{ value: "asc", label: "aufsteigend" }, { value: "desc", label: "absteigend" }] });
      const p = cfg.preset || {};
      const presetStore = input({ key: "pb", label: "Vorbelegung Bestand", type: "select", value: p.bestand || "",
        options: [{ value: "", label: "(keine)" }, ...Object.entries(STORE_NAMES).map(([value, label]) => ({ value, label }))] });
      const presetOnly = cfg.source === "lots" ? input({ key: "pn", label: "Nur Positionen mit Bestand", type: "checkbox", value: p.nur_bestand }) : null;
      const presetDays = cfg.source === "lots" ? input({ key: "pa", label: "Nur MHD innerhalb von … Tagen", type: "number", value: p.ablauf_tage ?? "", hint: "leer = keine Einschränkung" }) : null;
      const presetAdmin = cfg.source === "movements" ? input({ key: "pe", label: "Nur Admin-Eingriffe", type: "checkbox", value: p.nur_admin_eingriffe }) : null;
      const rowAction = cat.row_actions[cfg.source] ? input({ key: "ra", label: `Zeilenaktion „${cat.row_actions[cfg.source]}“`, type: "checkbox", value: !!cfg.row_action }) : null;
      parts.push(
        group("Spalten", cols.el),
        group("Filter (Selektionsbild)", h("div", { class: "fgrid" }, filterBoxes.map((x) => x.i.row))),
        group("Sortierung und Vorbelegung", h("div", { class: "fgrid" }, [sortField, sortDir, presetStore, presetOnly, presetDays, presetAdmin, rowAction].filter(Boolean).map((x) => x.row))));
      collect = () => ({
        source: cfg.source, columns: cols.value(),
        filters: filterBoxes.filter((x) => x.i.get()).map((x) => x.f),
        sort: { field: sortField.get(), dir: sortDir.get() },
        preset: { bestand: presetStore.get() || undefined, nur_bestand: presetOnly ? presetOnly.get() : undefined,
          ablauf_tage: presetDays && presetDays.get() !== "" ? presetDays.get() : undefined,
          nur_admin_eingriffe: presetAdmin ? presetAdmin.get() : undefined },
        row_action: rowAction && rowAction.get() ? cat.row_actions[cfg.source] : "",
      });
    } else if (page.kind === "FORM") {
      const sys = cat.form_system_fields[cfg.action];
      const avail = [...sys.map(([k, l]) => ({ key: k, label: l })),
        ...ctx.config.fields.filter((f) => cat.form_entities[cfg.action].includes(f.entity)).map((f) => ({ key: f.code, label: f.label }))];
      const flds = orderEditor(avail, cfg.fields, new Set(sys.map(([k]) => k)));
      const store = input({ key: "st", label: "Fester Bestand", type: "select", value: cfg.store || "",
        options: [{ value: "", label: "(wählbar)" }, ...Object.entries(STORE_NAMES).map(([value, label]) => ({ value, label }))] });
      parts.push(group("Felder der Maske", flds.el, h("p", { class: "hint" }, "Systemfelder können umsortiert und umbenannt, aber nicht entfernt werden.")),
        group("Optionen", store.row));
      collect = () => ({ action: cfg.action, fields: flds.value(), store: store.get() });
    } else {
      parts.push(h("p", { class: "hint" }, "Systemseite: nur der Titel ist änderbar."));
      collect = () => ({});
    }
    editor.append(group(`Seite ${page.code} bearbeiten`, h("form", { class: "form", onsubmit: (e) => e.preventDefault() }, parts),
      h("div", { class: "btnrow" },
        btn("Speichern", async () => {
          try {
            await put(`/api/customizing/meta_page/${page.code}`, { title: title.get(), kind: page.kind, config: collect() });
            await afterChange(ctx, `Seite ${page.code} gespeichert.`, load);
          } catch (e) { errorStatus(e); }
        }, { primary: true, icon: "✔" }),
        btn("Vorschau öffnen", () => ctx.navigate(page.code)),
        btn("Schließen", () => clear(editor)))));
    editor.scrollIntoView({ behavior: "smooth" });
  }

  c.append(h("div", { class: "btnrow" }, btn("Neue Seite", create, { primary: true, icon: "+" })), result, editor);
  load().catch(errorStatus);
}

// ------------------------------------------------------------------ Menüs und T-Codes
function renderMenus(ctx, c) {
  const menuBox = h("div");
  const tcBox = h("div");
  let pages = [];
  const pageOpts = () => [{ value: "", label: "(keine – Hauptmenü)" }, ...pages.map((p) => ({ value: p.code, label: `${p.code} – ${p.title}` }))];
  async function load() {
    pages = await get("/api/customizing/meta_page");
    const menus = await get("/api/customizing/meta_menu");
    const name = (id) => (menus.find((m) => m.id === id) || {}).label || "";
    const sorted = menus.map((m) => ({ ...m, _pos: m.parent_id === null
      ? `${String(m.sort).padStart(5, "0")}` : `${String((menus.find((x) => x.id === m.parent_id) || {}).sort).padStart(5, "0")}.${String(m.sort).padStart(5, "0")}` }));
    clear(menuBox).append(table([
      { key: "_pos", label: "Pos.", fmt: (v, r) => (r.parent_id === null ? "▸ " : "    ") + r.sort },
      { key: "label", label: "Menütext", fmt: (v, r) => (r.parent_id === null ? v.toUpperCase() : v) },
      { key: "parent_id", label: "Hauptmenü", fmt: (v) => name(v) },
      { key: "target", label: "Zielseite" }, { key: "active", label: "Aktiv", fmt: yesNo },
    ], sorted, { sort: { field: "_pos", dir: "asc" }, rowClass: (r) => (r.active ? "" : "disabled"),
      actions: (r) => [btn("Bearbeiten", () => editMenu(r, menus)), btn("Löschen", () => remove(ctx, "meta_menu", r.id, `Menüeintrag ${r.label}`, load))] }));
    const tcodes = await get("/api/customizing/meta_tcode");
    clear(tcBox).append(table([
      { key: "code", label: "T-Code" }, { key: "target", label: "Zielseite" }, { key: "description", label: "Beschreibung" },
    ], tcodes, { sort: { field: "code", dir: "asc" },
      actions: (r) => [btn("Bearbeiten", () => editTcode(r)), btn("Löschen", () => remove(ctx, "meta_tcode", r.code, `T-Code ${r.code}`, load))] }));
    c._menus = menus;
  }
  function editMenu(r, menus) {
    const isNew = !r;
    r = r || { parent_id: null, label: "", target: "", sort: 100, active: 1 };
    const tops = menus.filter((m) => m.parent_id === null);
    formDialog(isNew ? "Menüeintrag anlegen" : "Menüeintrag bearbeiten", [
      { key: "parent_id", label: "Hauptmenü", type: "select", value: r.parent_id ?? "",
        options: [{ value: "", label: "(ist selbst Hauptmenü)" }, ...tops.filter((t) => t.id !== r.id).map((t) => ({ value: t.id, label: t.label }))] },
      { key: "label", label: "Menütext", value: r.label, required: true, maxlength: 40 },
      { key: "target", label: "Zielseite", type: "select", value: r.target, options: pageOpts() },
      { key: "sort", label: "Sortierung", type: "number", value: r.sort },
      { key: "active", label: "Aktiv", type: "checkbox", value: r.active },
    ], async (v) => {
      const body = { ...v, parent_id: v.parent_id ? Number(v.parent_id) : null };
      if (isNew) await post("/api/customizing/meta_menu", body);
      else await put(`/api/customizing/meta_menu/${r.id}`, body);
      await afterChange(ctx, "Menü gespeichert.", load);
    });
  }
  function editTcode(r) {
    const isNew = !r;
    r = r || { code: "", target: "", description: "" };
    formDialog(isNew ? "T-Code anlegen" : `T-Code ${r.code} bearbeiten`, [
      { key: "code", label: "T-Code", value: r.code, disabled: !isNew, required: true, maxlength: 10, hint: "z. B. ZK01" },
      { key: "target", label: "Zielseite", type: "select", value: r.target, options: pageOpts().slice(1) },
      { key: "description", label: "Beschreibung", value: r.description, maxlength: 80 },
    ], async (v) => {
      if (isNew) await post("/api/customizing/meta_tcode", v);
      else await put(`/api/customizing/meta_tcode/${r.code}`, v);
      await afterChange(ctx, "T-Code gespeichert.", load);
    });
  }
  c.append(
    group("Menüleiste", h("div", { class: "btnrow" }, btn("Menüeintrag anlegen", () => editMenu(null, c._menus || []), { primary: true, icon: "+" })), menuBox),
    group("Transaktionscodes (Befehlsfeld)", h("div", { class: "btnrow" }, btn("T-Code anlegen", () => editTcode(null), { primary: true, icon: "+" })), tcBox));
  load().catch(errorStatus);
}

// ------------------------------------------------------------------ Regeln
const RULE_FIELDS = { mhd: "MHD", tage_bis_mhd: "Tage bis MHD", menge: "Menge (Buchung)", charge: "Charge", ean: "EAN",
  bezeichnung: "Bezeichnung", kategorie: "Kategorie", bestand: "Bestand (KELLER/PRIVAT)", typ: "Art (IN/OUT, nur Buchung)" };

function renderRules(ctx, c) {
  const cat = ctx.config.catalog;
  const result = h("div");
  const fieldOpts = () => [...Object.entries(RULE_FIELDS).map(([value, label]) => ({ value, label })),
    ...ctx.config.fields.map((f) => ({ value: f.code, label: f.label + " (eigenes Feld)" }))];
  const describe = (r) => r.conditions.map((x) => `${RULE_FIELDS[x.field] || x.field} ${cat.rule_ops[x.op]} ${["empty", "notempty"].includes(x.op) ? "" : x.value}`).join(" UND ");
  async function load() {
    const rows = await get("/api/customizing/meta_rule");
    clear(result).append(table([
      { key: "name", label: "Regel" }, { key: "trigger", label: "Auslöser", fmt: (v) => cat.rule_triggers[v] },
      { key: "conditions", label: "Wenn", fmt: (v, r) => describe(r) },
      { key: "action", label: "Dann", fmt: (v) => `${cat.rule_actions[v.type]}: ${v.message}` },
      { key: "active", label: "Aktiv", fmt: yesNo },
    ], rows, { rowClass: (r) => (r.active ? "" : "disabled"),
      actions: (r) => [btn("Bearbeiten", () => edit(r)), btn("Löschen", () => remove(ctx, "meta_rule", r.id, `Regel ${r.name}`, load))] }));
  }
  function edit(r) {
    const isNew = !r;
    r = r || { name: "", trigger: "BUCHUNG", conditions: [{ field: "mhd", op: "days_until_lt", value: 7 }], action: { type: "WARN", message: "" }, active: 1 };
    const name = input({ key: "name", label: "Name", value: r.name, required: true, maxlength: 100 });
    const trigger = input({ key: "trigger", label: "Auslöser", type: "select", value: r.trigger, options: opts(cat.rule_triggers) });
    const condBox = h("div", { class: "conds" });
    const conds = [];
    const addCond = (cnd) => {
      const f = input({ key: "cf", label: "Feld", type: "select", value: cnd.field, options: fieldOpts() });
      const o = input({ key: "co", label: "Bedingung", type: "select", value: cnd.op, options: opts(cat.rule_ops) });
      const v = input({ key: "cv", label: "Wert", value: cnd.value ?? "" });
      const entry = { f, o, v };
      const row = h("div", { class: "condrow" }, f.row, o.row, v.row, btn("Entfernen", () => {
        conds.splice(conds.indexOf(entry), 1);
        row.remove();
      }));
      conds.push(entry);
      condBox.append(row);
    };
    r.conditions.forEach(addCond);
    const type = input({ key: "type", label: "Aktion", type: "select", value: r.action.type, options: opts(cat.rule_actions) });
    const message = input({ key: "message", label: "Meldungstext", value: r.action.message, maxlength: 200 });
    const active = input({ key: "active", label: "Aktiv", type: "checkbox", value: r.active });
    const err = h("div", { class: "dlg-error" });
    modal(isNew ? "Regel anlegen" : "Regel bearbeiten", h("form", { class: "form", onsubmit: (e) => e.preventDefault() },
      name.row, trigger.row, h("h4", {}, "Wenn (alle Bedingungen erfüllt)"), condBox,
      btn("Bedingung hinzufügen", () => addCond({ field: "menge", op: "gt", value: "" })),
      h("h4", {}, "Dann"), type.row, message.row, active.row,
      h("p", { class: "hint" }, "Warnung: Buchung erst nach Bestätigung. Verhindern: Buchung wird abgelehnt. Markieren: Zeile in Listen hervorheben (Auslöser „Bei Anzeige“)."),
      err),
    [{ label: "Speichern", primary: true, action: async () => {
      const body = { name: name.get(), trigger: trigger.get(), active: active.get(),
        conditions: conds.map((x) => ({ field: x.f.get(), op: x.o.get(), value: x.v.get() })),
        action: { type: type.get(), message: message.get() } };
      try {
        if (isNew) await post("/api/customizing/meta_rule", body);
        else await put(`/api/customizing/meta_rule/${r.id}`, body);
        await afterChange(ctx, "Regel gespeichert.", load);
        return true;
      } catch (e) { err.textContent = e.message; return false; }
    } }, { label: "Abbrechen", value: null }], { wide: true });
  }
  c.append(h("div", { class: "btnrow" }, btn("Regel anlegen", () => edit(null), { primary: true, icon: "+" })), result);
  load().catch(errorStatus);
}

// ------------------------------------------------------------------ Rechte
function renderRights(ctx, c) {
  const box = h("div");
  async function load() {
    const r = await get("/api/rechte");
    const rows = r.matrix.map((m) => ({ ...m, bestand: m.store === "*" ? "(alle)" : STORE_NAMES[m.store] }));
    const privat = h("input", { type: "checkbox", checked: r.privat_lesbar, onchange: async (e) => {
      try { await put("/api/einstellungen", { key: "privat_lesbar", value: e.target.checked ? 1 : 0 }); await afterChange(ctx, "Recht gespeichert.", load); }
      catch (err) { errorStatus(err); load(); }
    } });
    clear(box).append(
      group("Rolle „Benutzer“ – einstellbare Rechte", table([
        { key: "bestand", label: "Bestand" }, { key: "label", label: "Funktion" },
        { key: "allowed", label: "Erlaubt", fmt: (v, row) => h("input", { type: "checkbox", checked: v, "aria-label": row.label, onchange: async (e) => {
          try { await put("/api/rechte", { store: row.store, function: row.function, allowed: e.target.checked }); await afterChange(ctx, "Recht gespeichert.", load); }
          catch (err) { errorStatus(err); load(); }
        } }) },
      ], rows), h("div", { class: "frow" }, h("label", {}, "„Mein Bestand“ lesen"), h("div", { class: "fcell" }, privat))),
      group("Fest vorgegeben (nicht einstellbar)", h("ul", { class: "fixed" },
        h("li", {}, "„Mein Bestand“ darf ausschließlich der Admin ändern (Ein-/Auschecken)."),
        h("li", {}, "Benutzerverwaltung, Customizing und Backup: nur Admin."),
        h("li", {}, "Protokoll einsehen und prüfen: alle Benutzer (Transparenz)."),
        h("li", {}, "Der Admin behält technisch volle Rechte; jede Admin-Buchung im Keller wird als Admin-Eingriff gekennzeichnet und erfordert eine Begründung."),
        h("li", {}, "Das Protokoll ist für niemanden änderbar oder löschbar."))));
  }
  c.append(box);
  load().catch(errorStatus);
}

// ------------------------------------------------------------------ Versionen
function renderVersions(ctx, c) {
  const result = h("div");
  async function load() {
    const rows = await get("/api/versionen");
    clear(result).append(table([
      { key: "id", label: "Version" }, { key: "ts", label: "Zeitpunkt", fmt: fmtDateTime },
      { key: "username", label: "Benutzer" }, { key: "kommentar", label: "Änderung" },
      { key: "hash", label: "Prüfsumme", fmt: (v) => v.slice(0, 12) },
    ], rows, { sort: { field: "id", dir: "desc" },
      actions: (r) => (r.id === rows[0].id ? h("span", { class: "hint" }, "aktuell") : btn("Auf diesen Stand zurücksetzen", async () => {
        if (!(await confirmBox("Rücksetzen", `Customizing auf Version ${r.id} zurücksetzen? Es entsteht eine neue Version; nichts geht verloren.`))) return;
        try { const x = await post(`/api/versionen/${r.id}/ruecksetzen`); await afterChange(ctx, x.message, load); } catch (e) { errorStatus(e); }
      })) }));
  }
  c.append(h("p", { class: "hint" }, "Jede Customizing-Änderung (Felder, Kategorien, Seiten, Menüs, T-Codes, Regeln, Rechte, Einstellungen) erzeugt eine vollständige Version. Bestände, Buchungen und Protokoll sind davon nicht betroffen."), result);
  load().catch(errorStatus);
}

// ------------------------------------------------------------------ Einstellungen
function renderSettings(ctx, c) {
  const defs = ctx.config.catalog.settings;
  const values = ctx.config.settings;
  const inputs = Object.entries(defs).map(([key, [label, type, min, max]]) => ({
    key, i: input({ key, label, type: type === "BOOL" ? "checkbox" : "number", min, max, step: 1,
      value: type === "BOOL" ? values[key] === "1" : values[key], hint: type === "BOOL" ? null : `${min}–${max}` }),
  }));
  c.append(h("form", { class: "form mask", onsubmit: async (e) => {
    e.preventDefault();
    let changed = 0;
    try {
      for (const { key, i } of inputs) {
        const v = typeof i.get() === "boolean" ? (i.get() ? 1 : 0) : i.get();
        if (String(v) !== String(ctx.config.settings[key])) { await put("/api/einstellungen", { key, value: v }); changed++; }
      }
      if (changed) await afterChange(ctx, `${changed} Einstellung(en) gespeichert.`);
      else status("Keine Änderungen.", "info");
    } catch (err) { errorStatus(err); }
  } }, group("Einstellungen", inputs.map((x) => x.i.row)),
  h("div", { class: "btnrow" }, btn("Speichern", null, { submit: true, primary: true, icon: "✔" }))));
}

export const CUSTOMIZING_PAGES = {
  SYS_FELDER: { fn: "CUSTOMIZING", render: renderFields },
  SYS_KATEGORIEN: { fn: "CUSTOMIZING", render: renderCategories },
  SYS_SEITEN: { fn: "CUSTOMIZING", render: renderPages },
  SYS_MENUES: { fn: "CUSTOMIZING", render: renderMenus },
  SYS_REGELN: { fn: "CUSTOMIZING", render: renderRules },
  SYS_RECHTE: { fn: "CUSTOMIZING", render: renderRights },
  SYS_VERSIONEN: { fn: "CUSTOMIZING", render: renderVersions },
  SYS_EINSTELLUNGEN: { fn: "CUSTOMIZING", render: renderSettings },
};
