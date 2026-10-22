// Generische Eingabemasken für Einchecken und Auschecken (Feldreihenfolge aus meta_page.config).
import { ApiError, get, post, qs } from "../api.js";
import { STORE_NAMES, clear, eanError, fmtDate, h } from "../dom.js";
import { btn, confirmBox, errorStatus, group, input, status } from "../ui.js";

export function customInputDef(f, value) {
  const base = { key: "c_" + f.code, label: f.label, required: !!f.required,
    value: value ?? (f.default_value || "") };
  switch (f.type) {
    case "NUMBER": return { ...base, type: "number", step: "any" };
    case "DATE": return { ...base, type: "date" };
    case "BOOL": return { ...base, type: "checkbox", value: value ?? ["1", "true", "ja"].includes(String(f.default_value).toLowerCase()) };
    case "SELECT": return { ...base, type: "select",
      options: [{ value: "", label: "" }, ...f.options.map((o) => ({ value: o, label: o }))] };
    default: return { ...base, type: "text", maxlength: 500 };
  }
}

export function readCustom(fields, values) {
  const out = {};
  for (const f of fields) {
    const v = values["c_" + f.code];
    if (f.type === "BOOL") out[f.code] = !!v;
    else if (v !== "" && v !== undefined && v !== null) out[f.code] = v;
  }
  return out;
}

export function renderForm(ctx, page, container, params) {
  if (page.config.action === "einchecken") renderCheckin(ctx, page, container, params);
  else renderCheckout(ctx, page, container, params);
}

function storeOptions(ctx, fn, fixed) {
  const stores = ctx.config.capabilities[fn].filter((s) => !fixed || s === fixed);
  return stores.map((s) => ({ value: s, label: STORE_NAMES[s] }));
}

function adminBanner(ctx, inputs) {
  const banner = h("div", { class: "admin-banner" },
    "Admin-Eingriff im Keller: Diese Buchung wird im Protokoll deutlich als Admin-Eingriff gekennzeichnet. Begründung ist Pflicht.");
  const update = () => {
    const show = ctx.me.user.role === "ADMIN" && inputs.bestand.get() === "KELLER";
    banner.hidden = !show;
    if (inputs.begruendung) {
      inputs.begruendung.row.querySelector("label").classList.toggle("req", show);
      inputs.begruendung.el.required = show;
    }
  };
  inputs.bestand.el.addEventListener("change", update);
  update();
  return banner;
}

async function submitWithConfirm(url, body) {
  try {
    return await post(url, body);
  } catch (e) {
    if (e instanceof ApiError && e.status === 409 && e.body.warnings) {
      if (await confirmBox("Warnung", e.message, "Trotzdem buchen")) return post(url, { ...body, trotz_warnung: true });
      status("Buchung abgebrochen.", "warn");
      return null;
    }
    throw e;
  }
}

// ------------------------------------------------------------------ Einchecken
function renderCheckin(ctx, page, container, params) {
  const cfg = page.config;
  const fields = ctx.config.fields.filter((f) => f.active);
  const cats = ctx.config.categories.filter((c) => c.active);
  const inputs = {};
  const customDefs = [];
  const eanMsg = h("span", { class: "fieldmsg" });
  let knownArticle = null;

  for (const item of cfg.fields) {
    const k = item.field;
    const label = ctx.fieldLabel(k, item);
    let def;
    switch (k) {
      case "bestand":
        def = { key: k, label, type: "select", options: storeOptions(ctx, "EINCHECKEN", cfg.store),
          value: params.bestand || (ctx.me.user.role === "ADMIN" ? "PRIVAT" : "KELLER"), required: true };
        break;
      case "ean": def = { key: k, label, required: true, maxlength: 13, inputmode: "numeric", value: params.ean || "" }; break;
      case "bezeichnung": def = { key: k, label, required: true, maxlength: 100 }; break;
      case "kategorie": def = { key: k, label, type: "select",
        options: [{ value: "", label: "(keine)" }, ...cats.map((c) => ({ value: c.id, label: c.name }))] }; break;
      case "mhd": def = { key: k, label, type: "date", required: true }; break;
      case "charge": def = { key: k, label, maxlength: 40, hint: "Chargen-/Produktionsnummer, falls aufgedruckt" }; break;
      case "menge": def = { key: k, label, type: "number", required: true, min: 1, step: 1, value: 1 }; break;
      case "begruendung": def = { key: k, label, maxlength: 300 }; break;
      default: {
        const f = fields.find((x) => x.code === k);
        if (!f) continue;
        def = { ...customInputDef(f), label: item.label || f.label };
        customDefs.push(f);
      }
    }
    inputs[def.key] = input(def);
  }
  const art = (k) => inputs[k] && inputs[k].el;

  const banner = adminBanner(ctx, inputs);
  inputs.ean.el.parentElement.append(eanMsg);

  const articleFields = customDefs.filter((f) => f.entity === "artikel");
  const bookingFields = customDefs.filter((f) => f.entity === "buchung");

  function setArticleLocked(locked) {
    for (const k of ["bezeichnung", "kategorie", ...articleFields.map((f) => "c_" + f.code)]) {
      if (art(k)) art(k).disabled = locked;
    }
  }

  async function lookup() {
    const ean = inputs.ean.get().trim();
    knownArticle = null;
    setArticleLocked(false);
    if (!ean) { eanMsg.textContent = ""; return; }
    const err = eanError(ean);
    if (err) { eanMsg.textContent = err; eanMsg.className = "fieldmsg bad"; return; }
    try {
      const a = await get(`/api/artikel/${encodeURIComponent(ean)}`);
      knownArticle = a;
      if (art("bezeichnung")) art("bezeichnung").value = a.bezeichnung;
      if (art("kategorie")) art("kategorie").value = a.kategorie_id ?? "";
      for (const f of articleFields) {
        const el = art("c_" + f.code);
        if (!el) continue;
        if (f.type === "BOOL") el.checked = !!a.custom[f.code];
        else el.value = a.custom[f.code] ?? "";
      }
      setArticleLocked(true);
      eanMsg.textContent = "Artikel bekannt – Stammdaten vorbelegt.";
      eanMsg.className = "fieldmsg good";
    } catch (e) {
      if (e.status === 404) {
        eanMsg.textContent = "Neuer Artikel – bitte Bezeichnung und Kategorie erfassen.";
        eanMsg.className = "fieldmsg";
      } else errorStatus(e);
    }
  }
  inputs.ean.el.addEventListener("change", lookup);

  const form = h("form", { class: "form mask", onsubmit: async (e) => {
    e.preventDefault();
    const values = {};
    for (const [k, i] of Object.entries(inputs)) values[k] = i.get();
    const ean = String(values.ean || "").trim();
    const err = eanError(ean);
    if (err) { status("EAN ungültig: " + err, "error"); inputs.ean.el.focus(); return; }
    const body = {
      bestand: values.bestand, ean, bezeichnung: values.bezeichnung,
      kategorie_id: values.kategorie ? Number(values.kategorie) : null, mhd: values.mhd,
      charge: values.charge || "", menge: values.menge, begruendung: values.begruendung || "",
      custom_buchung: readCustom(bookingFields, values),
      custom_artikel: knownArticle ? {} : readCustom(articleFields, values),
    };
    try {
      const r = await submitWithConfirm("/api/buchung/einchecken", body);
      if (!r) return;
      status(r.message + (r.admin_eingriff ? " (Admin-Eingriff protokolliert)" : ""), "ok");
      ctx.refreshHead(false);
      for (const [k, i] of Object.entries(inputs)) {
        if (k === "bestand") continue;
        if (k === "menge") i.el.value = 1;
        else if (i.el.type === "checkbox") i.el.checked = false;
        else i.el.value = "";
      }
      knownArticle = null;
      setArticleLocked(false);
      eanMsg.textContent = "";
      inputs.ean.el.focus();
    } catch (e2) { errorStatus(e2); }
  } },
  banner,
  group("Zugang erfassen", Object.values(inputs).map((i) => i.row)),
  h("div", { class: "btnrow" }, btn("Buchen", null, { submit: true, primary: true, icon: "✔" })));
  container.append(form);
  ctx.onExecute = () => form.requestSubmit();
  if (params.ean) lookup();
  inputs.ean.el.focus();
}

// ------------------------------------------------------------------ Auschecken
function renderCheckout(ctx, page, container, params) {
  const cfg = page.config;
  const fields = ctx.config.fields.filter((f) => f.active && f.entity === "buchung");
  const inputs = {};
  const customDefs = [];
  const info = h("span", { class: "fieldmsg" });

  for (const item of cfg.fields) {
    const k = item.field;
    const label = ctx.fieldLabel(k, item);
    let def;
    switch (k) {
      case "bestand":
        def = { key: k, label, type: "select", options: storeOptions(ctx, "AUSCHECKEN", cfg.store),
          value: params.bestand || (ctx.me.user.role === "ADMIN" ? "PRIVAT" : "KELLER"), required: true };
        break;
      case "ean": def = { key: k, label, required: true, maxlength: 13, inputmode: "numeric", value: params.ean || "" }; break;
      case "position": def = { key: k, label, type: "select", options: [], required: true }; break;
      case "menge": def = { key: k, label, type: "number", required: true, min: 1, step: 1, value: 1 }; break;
      case "begruendung": def = { key: k, label, maxlength: 300 }; break;
      default: {
        const f = fields.find((x) => x.code === k);
        if (!f) continue;
        def = { ...customInputDef(f), label: item.label || f.label };
        customDefs.push(f);
      }
    }
    inputs[def.key] = input(def);
  }
  inputs.ean.el.parentElement.append(info);
  const banner = adminBanner(ctx, inputs);

  async function loadPositions(select) {
    const sel = inputs.position.el;
    clear(sel);
    info.textContent = "";
    const ean = inputs.ean.get().trim();
    if (!ean) return;
    const err = eanError(ean);
    if (err) { info.textContent = err; info.className = "fieldmsg bad"; return; }
    try {
      const lots = await get(`/api/positionen${qs({ bestand: inputs.bestand.get(), ean })}`);
      if (!lots.length) {
        info.textContent = "Kein Bestand zu dieser EAN in diesem Bestand.";
        info.className = "fieldmsg bad";
        return;
      }
      for (const l of lots) {
        sel.append(h("option", { value: l.id },
          `Pos. ${l.id} · MHD ${fmtDate(l.mhd)} · Charge ${l.charge || "–"} · Menge ${l.qty}`));
      }
      if (select) sel.value = String(select);
      info.textContent = `${lots.length} Position(en) gefunden – älteste MHD zuerst.`;
      info.className = "fieldmsg good";
    } catch (e) { errorStatus(e); }
  }
  inputs.ean.el.addEventListener("change", () => loadPositions());
  inputs.bestand.el.addEventListener("change", () => loadPositions());

  const form = h("form", { class: "form mask", onsubmit: async (e) => {
    e.preventDefault();
    const values = {};
    for (const [k, i] of Object.entries(inputs)) values[k] = i.get();
    if (!values.position) { status("Bitte eine Bestandsposition wählen.", "error"); return; }
    const body = { position: Number(values.position), menge: values.menge, begruendung: values.begruendung || "",
      custom_buchung: readCustom(customDefs, values) };
    try {
      const r = await submitWithConfirm("/api/buchung/auschecken", body);
      if (!r) return;
      status(r.message + (r.admin_eingriff ? " (Admin-Eingriff protokolliert)" : ""), "ok");
      ctx.refreshHead(false);
      inputs.menge.el.value = 1;
      if (inputs.begruendung) inputs.begruendung.el.value = "";
      loadPositions(r.menge_danach > 0 ? r.position : null);
    } catch (e2) { errorStatus(e2); }
  } },
  banner,
  group("Abgang erfassen", Object.values(inputs).map((i) => i.row)),
  h("div", { class: "btnrow" }, btn("Buchen", null, { submit: true, primary: true, icon: "✔" })));
  container.append(form);
  ctx.onExecute = () => form.requestSubmit();
  if (params.ean) loadPositions(params.position);
  (params.ean ? inputs.menge.el : inputs.ean.el).focus();
}
