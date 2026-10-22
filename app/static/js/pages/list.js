// Generische Liste: Aufbau vollständig aus der Seitenkonfiguration (meta_page.config).
import { get, put, qs } from "../api.js";
import { STORE_NAMES, clear, download, fmtDate, fmtDateTime, h } from "../dom.js";
import { btn, errorStatus, formDialog, group, input, status, table, toCsv } from "../ui.js";
import { customInputDef, readCustom } from "./form.js";

export const FILTER_LABELS = {
  bestand: "Bestand", ean: "EAN", bezeichnung: "Bezeichnung", kategorie: "Kategorie", mhd_von: "MHD von",
  mhd_bis: "MHD bis", charge: "Charge", benutzer: "Benutzer", typ: "Art", von: "Datum von", bis: "Datum bis",
};

function filterDef(ctx, key, value) {
  const base = { key, label: FILTER_LABELS[key], value: value ?? "" };
  if (key === "bestand") {
    return { ...base, type: "select", options: [{ value: "", label: "(alle)" },
      ...ctx.config.capabilities.BESTAND_LESEN.map((s) => ({ value: s, label: STORE_NAMES[s] }))] };
  }
  if (key === "kategorie") {
    return { ...base, type: "select", options: [{ value: "", label: "(alle)" },
      ...ctx.config.categories.map((c) => ({ value: c.name, label: c.name }))] };
  }
  if (key === "typ") {
    return { ...base, type: "select", options: [{ value: "", label: "(alle)" }, { value: "IN", label: "Zugang" },
      { value: "OUT", label: "Abgang" }] };
  }
  if (["mhd_von", "mhd_bis", "von", "bis"].includes(key)) return { ...base, type: "date" };
  return { ...base, type: "text", inputmode: key === "ean" ? "numeric" : undefined };
}

export function columnFormatter(ctx, key) {
  const def = ctx.fieldDef(key);
  if (["mhd", "angelegt_am"].includes(key)) return (v) => fmtDate(v);
  if (key === "zeitpunkt") return (v) => fmtDateTime(v);
  if (key === "bestand") return (v) => STORE_NAMES[v] || v;
  if (key === "admin_eingriff") return (v) => (v ? "JA" : "");
  if (key === "bestand_keller" || key === "bestand_privat") return (v) => (v === null ? "–" : v);
  if (def && def.type === "DATE") return (v) => fmtDate(v);
  if (def && def.type === "BOOL") return (v) => (v === true ? "Ja" : v === false ? "Nein" : "");
  return null;
}

export function renderList(ctx, page, container, params) {
  const cfg = page.config;
  const caps = ctx.config.capabilities;
  const preset = cfg.preset || {};
  const filters = cfg.filters.map((key) => {
    const initial = params[key] ?? (key === "bestand" ? preset.bestand : "");
    return { key, i: input(filterDef(ctx, key, initial)) };
  });
  const extras = [];
  if (cfg.source === "lots") {
    extras.push({ key: "nur_bestand", i: input({ key: "nur_bestand", label: "Nur mit Bestand", type: "checkbox",
      value: preset.nur_bestand ?? true }) });
  }
  if (cfg.source === "movements") {
    extras.push({ key: "nur_admin_eingriffe", i: input({ key: "nur_admin_eingriffe", label: "Nur Admin-Eingriffe",
      type: "checkbox", value: !!preset.nur_admin_eingriffe }) });
  }
  const result = h("div", { class: "result" });
  const form = h("form", { class: "form selection", onsubmit: (e) => { e.preventDefault(); run(); } },
    h("div", { class: "fgrid" }, [...filters, ...extras].map((f) => f.i.row)),
    preset.ablauf_tage !== undefined ? h("p", { class: "hint" }, `Zeigt Positionen mit Bestand, deren MHD in höchstens ${preset.ablauf_tage} Tagen erreicht ist (auch bereits abgelaufene).`) : null,
    h("div", { class: "btnrow" }, btn("Ausführen (F8)", null, { submit: true, primary: true, icon: "▶" })));
  container.append(group("Selektion", form), result);

  const columns = cfg.columns.map((c) => ({ key: c.field, label: ctx.fieldLabel(c.field, c),
    fmt: columnFormatter(ctx, c.field) }));
  const checkoutPage = ctx.config.pages.find((p) => p.kind === "FORM" && p.config.action === "auschecken");

  async function run() {
    const q = {};
    for (const f of [...filters, ...extras]) q[f.key] = f.i.get();
    if (preset.ablauf_tage !== undefined) q.ablauf_tage = preset.ablauf_tage;
    if (preset.bestand && !cfg.filters.includes("bestand")) q.bestand = preset.bestand;
    clear(result).append(h("p", { class: "hint" }, "Daten werden geladen …"));
    try {
      const rows = await get(`/api/daten/${cfg.source}${qs(q)}`);
      clear(result).append(table(columns, rows, {
        sort: cfg.sort,
        rowClass: (r) => [
          (r._hinweise || []).some((x) => x.type === "HIGHLIGHT" || x.type === "WARN") ? "hl" : "",
          r.admin_eingriff ? "admin" : "",
          typeof r.tage_bis_mhd === "number" && r.tage_bis_mhd < 0 && r.menge > 0 ? "expired" : "",
        ].join(" "),
        rowTitle: (r) => (r._hinweise || []).map((x) => x.message).join("\n") || null,
        actions: cfg.row_action ? (r) => rowActions(r) : null,
        tools: btn("CSV", () => download(`${page.code.toLowerCase()}.csv`, toCsv(columns, rows)),
          { title: "Als CSV exportieren", icon: "⇩" }),
      }));
      status(`${rows.length} Einträge selektiert.`, "ok");
    } catch (e) {
      clear(result);
      errorStatus(e);
    }
  }

  function rowActions(r) {
    if (cfg.row_action === "auschecken" && checkoutPage && caps.AUSCHECKEN.includes(r.bestand) && r.menge > 0) {
      return btn("Auschecken", () => ctx.navigate(checkoutPage.code, { bestand: r.bestand, ean: r.ean, position: r.id }),
        { icon: "−" });
    }
    if (cfg.row_action === "bearbeiten" && caps.ARTIKEL_PFLEGEN) {
      return btn("Bearbeiten", () => editArticle(ctx, r, run), { icon: "✎" });
    }
    return null;
  }

  ctx.onExecute = run;
  run();
}

function editArticle(ctx, row, reload) {
  const custom = ctx.config.fields.filter((f) => f.entity === "artikel" && f.active);
  const defs = [
    { key: "ean", label: "EAN", value: row.ean, disabled: true },
    { key: "bezeichnung", label: "Bezeichnung", value: row.bezeichnung, required: true, maxlength: 100 },
    { key: "kategorie_id", label: "Kategorie", type: "select", value: row.kategorie_id ?? "",
      options: [{ value: "", label: "(keine)" }, ...ctx.config.categories.filter((c) => c.active || c.id === row.kategorie_id)
        .map((c) => ({ value: c.id, label: c.name }))] },
    ...custom.map((f) => customInputDef(f, row._custom[f.code])),
  ];
  formDialog(`Artikel ${row.ean} bearbeiten`, defs, async (v) => {
    await put(`/api/artikel/${encodeURIComponent(row.ean)}`, {
      bezeichnung: v.bezeichnung, kategorie_id: v.kategorie_id ? Number(v.kategorie_id) : null,
      custom_artikel: readCustom(custom, v),
    });
    await reload();
    status("Artikel gespeichert (protokolliert).", "ok");
  }, { intro: "Änderungen am Artikelstamm werden mit altem und neuem Wert protokolliert." });
}
