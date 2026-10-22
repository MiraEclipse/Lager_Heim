// Wiederverwendbare Oberflächenbausteine: Statusleiste, Tabellen, Dialoge, Eingabefelder.
import { clear, h } from "./dom.js";

// ------------------------------------------------------------------ Statusleiste
let statusEl = null;
export function bindStatus(el) { statusEl = el; }

export function status(message, type = "info") {
  if (!statusEl) return;
  clear(statusEl);
  const icon = { ok: "✔", error: "✖", warn: "!", info: "i" }[type] || "i";
  statusEl.className = "sb-msg sb-" + type;
  statusEl.append(h("span", { class: "sb-icon" }, icon), h("span", {}, message || ""));
  statusEl.title = message || "";
}

export function errorStatus(err) {
  status(err && err.message ? err.message : String(err), "error");
}

// ------------------------------------------------------------------ Gruppenrahmen
export function group(title, ...children) {
  return h("fieldset", { class: "group" }, h("legend", {}, title), ...children);
}

export function btn(label, onclick, opts = {}) {
  return h("button", {
    type: opts.submit ? "submit" : "button", class: "btn" + (opts.primary ? " btn-primary" : "") +
      (opts.danger ? " btn-danger" : ""), onclick, title: opts.title, disabled: opts.disabled,
  }, opts.icon ? h("span", { class: "ico" }, opts.icon) : null, label);
}

// ------------------------------------------------------------------ Eingabefelder
// def: {key, label, type: text|number|date|select|checkbox|textarea|password, options:[{value,label}],
//       value, required, disabled, hint, maxlength}
export function input(def) {
  const id = "f_" + def.key + "_" + Math.random().toString(36).slice(2, 7);
  let el;
  if (def.type === "select") {
    el = h("select", { id, disabled: def.disabled, required: def.required },
      (def.options || []).map((o) => h("option", { value: o.value }, o.label)));
    el.value = def.value ?? "";
  } else if (def.type === "checkbox") {
    el = h("input", { id, type: "checkbox", checked: !!def.value, disabled: def.disabled });
  } else if (def.type === "textarea") {
    el = h("textarea", { id, rows: def.rows || 4, disabled: def.disabled, maxlength: def.maxlength },
      def.value ?? "");
  } else {
    el = h("input", {
      id, type: def.type || "text", value: def.value ?? "", disabled: def.disabled,
      required: def.required, maxlength: def.maxlength, inputmode: def.inputmode,
      autocomplete: def.autocomplete || "off", min: def.min, max: def.max, step: def.step,
      placeholder: def.placeholder,
    });
  }
  const label = h("label", { for: id, class: def.required ? "req" : "" }, def.label);
  const row = h("div", { class: "frow" }, label, h("div", { class: "fcell" }, el,
    def.hint ? h("span", { class: "hint" }, def.hint) : null));
  return { row, el, get: () => readValue(def, el) };
}

function readValue(def, el) {
  if (def.type === "checkbox") return el.checked;
  if (def.type === "number") return el.value === "" ? "" : Number(el.value);
  return el.value;
}

// ------------------------------------------------------------------ Tabelle
// columns: [{key, label, fmt?(value,row), cls?}], rows, opts: {rowClass(row), rowTitle(row),
//   actions(row)->[Node], onRowDblClick(row), sort:{field,dir}, emptyText}
export function table(columns, rows, opts = {}) {
  let sort = opts.sort ? { ...opts.sort } : null;
  let filterText = "";
  const tbody = h("tbody");
  const counter = h("span", { class: "tcount" });
  const heads = columns.map((c) => {
    const th = h("th", { class: "sortable", onclick: () => {
      sort = sort && sort.field === c.key ? { field: c.key, dir: sort.dir === "asc" ? "desc" : "asc" }
        : { field: c.key, dir: "asc" };
      render();
    } }, c.label);
    th.dataset.key = c.key;
    return th;
  });
  if (opts.actions) heads.push(h("th", {}, ""));
  const thead = h("thead", {}, h("tr", {}, heads));

  function sorted() {
    let list = rows;
    if (filterText) {
      const f = filterText.toLowerCase();
      list = list.filter((r) => columns.some((c) => String(display(c, r)).toLowerCase().includes(f)));
    }
    if (!sort) return list;
    const dir = sort.dir === "desc" ? -1 : 1;
    return [...list].sort((a, b) => {
      const x = a[sort.field], y = b[sort.field];
      if (x === y) return 0;
      if (x === null || x === undefined || x === "") return 1;
      if (y === null || y === undefined || y === "") return -1;
      if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
      return String(x).localeCompare(String(y), "de", { numeric: true }) * dir;
    });
  }

  function display(c, r) {
    const v = r[c.key];
    return c.fmt ? c.fmt(v, r) : (v === null || v === undefined ? "" : v);
  }

  function render() {
    clear(tbody);
    heads.forEach((th) => {
      th.classList.remove("asc", "desc");
      if (sort && th.dataset.key === sort.field) th.classList.add(sort.dir);
    });
    const list = sorted();
    if (!list.length) {
      tbody.append(h("tr", {}, h("td", { colspan: columns.length + (opts.actions ? 1 : 0), class: "empty" },
        opts.emptyText || "Keine Einträge vorhanden.")));
    }
    for (const r of list) {
      const tr = h("tr", { class: opts.rowClass ? opts.rowClass(r) : "", title: opts.rowTitle ? opts.rowTitle(r) : null },
        columns.map((c) => {
          const v = display(c, r);
          return h("td", { class: c.cls || (typeof r[c.key] === "number" ? "num" : "") },
            v instanceof Node ? v : String(v));
        }));
      if (opts.actions) tr.append(h("td", { class: "actions" }, opts.actions(r)));
      if (opts.onRowDblClick) tr.addEventListener("dblclick", () => opts.onRowDblClick(r));
      tbody.append(tr);
    }
    counter.textContent = list.length === rows.length ? `${rows.length} Einträge`
      : `${list.length} von ${rows.length} Einträgen`;
  }
  render();

  const quick = h("input", { type: "search", class: "quickfilter", placeholder: "Schnellfilter …",
    oninput: (e) => { filterText = e.target.value; render(); } });
  const tools = h("div", { class: "ttools" }, quick, counter, opts.tools || null);
  return h("div", { class: "tablewrap" }, tools, h("div", { class: "tscroll" }, h("table", { class: "grid" }, thead, tbody)));
}

export function toCsv(columns, rows) {
  const esc = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    // Formel-Injektion in Tabellenkalkulationen verhindern
    const safe = /^[=+\-@\t\r]/.test(s) ? "'" + s : s;
    return /[";\n]/.test(safe) ? '"' + safe.replace(/"/g, '""') + '"' : safe;
  };
  const lines = [columns.map((c) => esc(c.label)).join(";")];
  for (const r of rows) {
    lines.push(columns.map((c) => {
      const v = c.fmt ? c.fmt(r[c.key], r) : r[c.key];
      return esc(v instanceof Node ? v.textContent : v);
    }).join(";"));
  }
  return lines.join("\r\n");
}

// ------------------------------------------------------------------ Dialoge
export function modal(title, body, buttons, opts = {}) {
  return new Promise((resolve) => {
    const prevFocus = document.activeElement;
    const close = (val) => {
      overlay.remove();
      document.removeEventListener("keydown", onKey, true);
      if (prevFocus && prevFocus.focus) prevFocus.focus();
      resolve(val);
    };
    const onKey = (e) => {
      if (e.key === "Escape") { e.stopPropagation(); close(null); }
    };
    const bar = h("div", { class: "dlg-buttons" }, buttons.map((b) =>
      btn(b.label, async () => {
        if (b.action) {
          const r = await b.action();
          if (r === false) return;
          close(r === undefined ? b.value : r);
        } else close(b.value);
      }, { primary: b.primary, danger: b.danger })));
    const win = h("div", { class: "window dialog" + (opts.wide ? " wide" : ""), role: "dialog", "aria-modal": "true" },
      h("div", { class: "titlebar" }, h("span", {}, title),
        h("button", { class: "tb-close", type: "button", title: "Schließen", onclick: () => close(null) }, "×")),
      h("div", { class: "dlg-body" }, body), bar);
    const overlay = h("div", { class: "overlay" }, win);
    document.body.append(overlay);
    document.addEventListener("keydown", onKey, true);
    const first = win.querySelector("input, select, textarea, .btn-primary");
    if (first) first.focus();
  });
}

export const alertBox = (title, text) =>
  modal(title, h("p", { class: "dlg-text" }, text), [{ label: "OK", value: true, primary: true }]);

export const confirmBox = (title, text, okLabel = "Ja") =>
  modal(title, h("p", { class: "dlg-text" }, text),
    [{ label: okLabel, value: true, primary: true }, { label: "Abbrechen", value: false }]).then((v) => !!v);

// Formular-Dialog: defs wie input(); onSave(values) -> Promise; Fehler bleiben im Dialog sichtbar
export function formDialog(title, defs, onSave, opts = {}) {
  const inputs = defs.map((d) => ({ d, i: input(d) }));
  const err = h("div", { class: "dlg-error" });
  const body = h("form", { class: "form", onsubmit: (e) => e.preventDefault() },
    opts.intro ? h("p", { class: "dlg-text" }, opts.intro) : null, inputs.map((x) => x.i.row), err);
  return modal(title, body, [
    { label: opts.saveLabel || "Speichern", primary: true, action: async () => {
      const values = {};
      for (const { d, i } of inputs) values[d.key] = i.get();
      try {
        const r = await onSave(values);
        return r === undefined ? true : r;
      } catch (e) {
        err.textContent = e.message;
        return false;
      }
    } },
    { label: "Abbrechen", value: null },
  ], opts);
}
