"""Metadaten-Customizing: Felder, Kategorien, Seiten, Menüs, T-Codes, Regeln, Rechte,
Einstellungen – inklusive Versionierung und Rücksetzung."""
import hashlib
import json
import re
from datetime import date

from . import audit, perms
from . import rules as rules_mod
from .db import now_iso, one, rows, write_tx
from .errors import AppError, NotFound

FIELD_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
PAGE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,30}$")
TCODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}$")
FIELD_TYPES = {"TEXT": "Text", "NUMBER": "Zahl", "DATE": "Datum", "SELECT": "Auswahlliste", "BOOL": "Ja/Nein"}
ENTITIES = {"artikel": "Artikel (Stammdaten je EAN)", "buchung": "Buchung (je Ein-/Auschecken)"}

# Feste Systemspalten je Datenquelle (Code, Standardbezeichnung)
SYSTEM_COLUMNS = {
    "lots": [("id", "Pos."), ("bestand", "Bestand"), ("ean", "EAN"), ("bezeichnung", "Bezeichnung"),
             ("kategorie", "Kategorie"), ("mhd", "MHD"), ("tage_bis_mhd", "Tage bis MHD"),
             ("charge", "Charge"), ("menge", "Menge")],
    "movements": [("id", "Beleg"), ("zeitpunkt", "Zeitpunkt"), ("benutzer", "Benutzer"), ("typ", "Art"),
                  ("bestand", "Bestand"), ("ean", "EAN"), ("bezeichnung", "Bezeichnung"),
                  ("kategorie", "Kategorie"), ("mhd", "MHD"), ("charge", "Charge"), ("menge", "Menge"),
                  ("menge_danach", "Bestand danach"), ("admin_eingriff", "Admin-Eingriff"),
                  ("begruendung", "Begründung")],
    "articles": [("ean", "EAN"), ("bezeichnung", "Bezeichnung"), ("kategorie", "Kategorie"),
                 ("bestand_keller", "Menge Keller"), ("bestand_privat", "Menge Mein Bestand"),
                 ("angelegt_am", "Angelegt am"), ("angelegt_von", "Angelegt von")],
}
SOURCE_ENTITIES = {"lots": ["artikel"], "movements": ["buchung", "artikel"], "articles": ["artikel"]}
SOURCE_NAMES = {"lots": "Bestandspositionen", "movements": "Buchungen", "articles": "Artikelstamm"}
FILTERS = {
    "lots": ["bestand", "ean", "bezeichnung", "kategorie", "mhd_von", "mhd_bis", "charge"],
    "movements": ["bestand", "ean", "bezeichnung", "kategorie", "mhd_von", "mhd_bis", "charge",
                  "benutzer", "typ", "von", "bis"],
    "articles": ["ean", "bezeichnung", "kategorie"],
}
ROW_ACTIONS = {"lots": "auschecken", "articles": "bearbeiten"}
PRESETS = {"nur_bestand": bool, "ablauf_tage": int, "bestand": str, "nur_admin_eingriffe": bool}

# Systemfelder der Formulare (Code, Bezeichnung, Pflicht im Layout)
FORM_SYSTEM_FIELDS = {
    "einchecken": [("bestand", "Bestand", True), ("ean", "EAN", True), ("bezeichnung", "Bezeichnung", True),
                   ("kategorie", "Kategorie", True), ("mhd", "MHD", True), ("charge", "Charge", True),
                   ("menge", "Menge", True), ("begruendung", "Begründung/Notiz", True)],
    "auschecken": [("bestand", "Bestand", True), ("ean", "EAN", True), ("position", "Position", True),
                   ("menge", "Menge", True), ("begruendung", "Begründung/Notiz", True)],
}
FORM_ENTITIES = {"einchecken": ["buchung", "artikel"], "auschecken": ["buchung"]}

SETTINGS = {
    # Schlüssel: (Bezeichnung, Typ, min, max)
    "privat_lesbar": ("Andere Benutzer dürfen „Mein Bestand“ lesen", "BOOL", 0, 1),
    "session_timeout_min": ("Sitzungs-Timeout bei Inaktivität (Minuten)", "NUMBER", 5, 240),
    "mhd_warn_tage": ("Hinweis auf ablaufende Artikel (Tage vorher)", "NUMBER", 1, 365),
    "backup_stunde": ("Uhrzeit des täglichen Backups (Stunde, UTC)", "NUMBER", 0, 23),
}

SNAPSHOT_TABLES = ["categories", "meta_field", "meta_page", "meta_menu", "meta_tcode", "meta_rule",
                   "permissions", "settings"]
JSON_COLUMNS = {"meta_field": ["options"], "meta_page": ["config"], "meta_rule": ["conditions", "action"]}


# ---------------------------------------------------------------- Lesen
def _decode(table: str, row: dict) -> dict:
    for c in JSON_COLUMNS.get(table, []):
        row[c] = json.loads(row[c])
    return row


def fields(conn, entity: str | None = None, active_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM meta_field WHERE 1=1"
    args = []
    if entity:
        sql += " AND entity = ?"
        args.append(entity)
    if active_only:
        sql += " AND active = 1"
    return [_decode("meta_field", r) for r in rows(conn.execute(sql + " ORDER BY sort, id", args))]


def get_setting(conn, key: str) -> str:
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else ""


def setting_int(conn, key: str, default: int) -> int:
    try:
        return int(get_setting(conn, key))
    except ValueError:
        return default


def active_rules(conn) -> list[dict]:
    return [_decode("meta_rule", r) for r in rows(conn.execute("SELECT * FROM meta_rule WHERE active = 1"))]


def table_rows(conn, table: str) -> list[dict]:
    order = {"meta_page": "code", "meta_tcode": "code", "settings": "key",
             "permissions": "role, store_code, function"}.get(table, "id")
    return [_decode(table, r) for r in rows(conn.execute(f"SELECT * FROM {table} ORDER BY {order}"))]


def client_config(conn, user: dict) -> dict:
    """Komplette Laufzeitkonfiguration, aus der sich die Oberfläche aufbaut."""
    return {
        "pages": table_rows(conn, "meta_page"),
        "menus": [m for m in table_rows(conn, "meta_menu") if m["active"]],
        "tcodes": table_rows(conn, "meta_tcode"),
        "fields": fields(conn, active_only=False),
        "categories": table_rows(conn, "categories"),
        "rules": active_rules(conn),
        "settings": {k: get_setting(conn, k) for k in SETTINGS},
        "catalog": {
            "system_columns": SYSTEM_COLUMNS, "source_entities": SOURCE_ENTITIES,
            "source_names": SOURCE_NAMES, "filters": FILTERS, "row_actions": ROW_ACTIONS,
            "form_system_fields": FORM_SYSTEM_FIELDS, "form_entities": FORM_ENTITIES,
            "field_types": FIELD_TYPES, "entities": ENTITIES, "rule_ops": rules_mod.OPS,
            "rule_actions": rules_mod.ACTIONS, "rule_triggers": rules_mod.TRIGGERS,
            "functions": {k: v[0] for k, v in perms.FUNCTIONS.items()},
            "configurable": perms.CONFIGURABLE, "settings": SETTINGS,
        },
        "capabilities": perms.capabilities(conn, user),
    }


# ---------------------------------------------------------------- Eigene Feldwerte
def validate_custom(conn, entity: str, values: dict | None) -> dict:
    values = values or {}
    if not isinstance(values, dict):
        raise AppError("Ungültige Zusatzfelder.")
    defs = {f["code"]: f for f in fields(conn, entity)}
    unknown = set(values) - set(defs)
    if unknown:
        raise AppError(f"Unbekanntes Feld: {sorted(unknown)[0]}")
    out = {}
    for code, f in defs.items():
        v = values.get(code, f["default_value"])
        if v in (None, ""):
            if f["required"]:
                raise AppError(f"Pflichtfeld „{f['label']}“ ist leer.")
            continue
        out[code] = _convert(f, v)
    return out


def _convert(f: dict, v):
    t, label = f["type"], f["label"]
    if t == "TEXT":
        v = str(v)
        if len(v) > 500:
            raise AppError(f"„{label}“ ist zu lang.")
        return v
    if t == "NUMBER":
        try:
            n = float(v)
        except (TypeError, ValueError):
            raise AppError(f"„{label}“ muss eine Zahl sein.")
        return int(n) if n.is_integer() else n
    if t == "DATE":
        try:
            return date.fromisoformat(str(v)).isoformat()
        except ValueError:
            raise AppError(f"„{label}“ muss ein Datum sein.")
    if t == "SELECT":
        if str(v) not in [str(o) for o in f["options"]]:
            raise AppError(f"„{label}“: Wert nicht in der Auswahlliste.")
        return str(v)
    if t == "BOOL":
        if isinstance(v, bool):
            return v
        if str(v).lower() in ("1", "true", "ja"):
            return True
        if str(v).lower() in ("0", "false", "nein"):
            return False
        raise AppError(f"„{label}“ muss Ja oder Nein sein.")
    raise AppError("Unbekannter Feldtyp.")


# ---------------------------------------------------------------- Versionierung
def snapshot(conn) -> dict:
    return {t: rows(conn.execute(f"SELECT * FROM {t}")) for t in SNAPSHOT_TABLES}


def create_version(conn, user: dict | None, kommentar: str) -> int:
    snap = json.dumps(snapshot(conn), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256(snap.encode()).hexdigest()
    cur = conn.execute(
        "INSERT INTO config_version(ts, user_id, username, kommentar, snapshot, hash) VALUES (?,?,?,?,?,?)",
        (now_iso(), user["id"] if user else None, user["username"] if user else "SYSTEM", kommentar, snap, h),
    )
    return cur.lastrowid


def _apply_snapshot(conn, snap: dict) -> None:
    for t in SNAPSHOT_TABLES:
        data = snap.get(t, [])
        if t == "categories":
            # Kategorien werden von Artikeln referenziert: nie löschen, nur deaktivieren
            keep = [c["id"] for c in data]
            conn.execute(f"UPDATE categories SET active = 0 WHERE id NOT IN ({','.join('?' * len(keep))})", keep)
            for c in data:
                conn.execute(
                    "INSERT INTO categories(id, name, active, sort) VALUES (?,?,?,?) ON CONFLICT(id) DO "
                    "UPDATE SET name = excluded.name, active = excluded.active, sort = excluded.sort",
                    (c["id"], c["name"], c["active"], c["sort"]),
                )
            continue
        conn.execute(f"DELETE FROM {t}")
        for r in data:
            cols = list(r.keys())
            conn.execute(f"INSERT INTO {t} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                         [r[c] for c in cols])


def versions(conn) -> list[dict]:
    return rows(conn.execute(
        "SELECT id, ts, username, kommentar, hash FROM config_version ORDER BY id DESC"))


def rollback(conn, user: dict, version_id: int, ip: str) -> int:
    with write_tx(conn):
        v = one(conn.execute("SELECT * FROM config_version WHERE id = ?", (version_id,)))
        if not v:
            raise NotFound("Version nicht gefunden.")
        snap = json.loads(v["snapshot"])
        if hashlib.sha256(v["snapshot"].encode()).hexdigest() != v["hash"]:
            raise AppError("Version ist beschädigt (Prüfsumme falsch).")
        _apply_snapshot(conn, snap)
        new_id = create_version(conn, user, f"Rücksetzung auf Version {version_id}")
        audit.append(conn, user, "CUSTOMIZING_RUECKSETZUNG", "config_version", new_id,
                     old=None, new={"zurueckgesetzt_auf": version_id, "neue_version": new_id}, ip=ip)
    return new_id


# ---------------------------------------------------------------- Pflege (CRUD)
TABLE_LABELS = {"categories": "Kategorie", "meta_field": "Feld", "meta_page": "Seite",
                "meta_menu": "Menüeintrag", "meta_tcode": "Transaktionscode", "meta_rule": "Regel"}
PK = {"categories": "id", "meta_field": "id", "meta_page": "code", "meta_menu": "id",
      "meta_tcode": "code", "meta_rule": "id"}


def _clean(table: str, data: dict, old: dict | None, conn) -> dict:
    s = lambda k, d="": str(data.get(k, d) if data.get(k) is not None else d).strip()  # noqa: E731
    b = lambda k, d=0: 1 if data.get(k, d) in (1, True, "1", "true") else 0  # noqa: E731

    def i(k, d=0):
        try:
            return int(data.get(k, d))
        except (TypeError, ValueError):
            raise AppError(f"„{k}“ muss eine Zahl sein.")

    if table == "categories":
        name = s("name")
        if not name or len(name) > 60:
            raise AppError("Kategoriename fehlt oder ist zu lang.")
        return {"name": name, "active": b("active", 1), "sort": i("sort")}

    if table == "meta_field":
        code = old["code"] if old else s("code")
        entity = old["entity"] if old else s("entity")
        ftype = old["type"] if old else s("type")
        if not FIELD_CODE_RE.match(code):
            raise AppError("Feldcode: Kleinbuchstaben, Ziffern, _ (2–31 Zeichen, beginnt mit Buchstabe).")
        reserved = {c for cols in SYSTEM_COLUMNS.values() for c, _ in cols} | \
                   {c for fs in FORM_SYSTEM_FIELDS.values() for c, _, _ in fs}
        if not old and code in reserved:
            raise AppError("Feldcode ist für ein Systemfeld reserviert.")
        if entity not in ENTITIES:
            raise AppError("Ungültige Entität.")
        if ftype not in FIELD_TYPES:
            raise AppError("Ungültiger Feldtyp.")
        label = s("label")
        if not label or len(label) > 60:
            raise AppError("Bezeichnung fehlt oder ist zu lang.")
        options = data.get("options", [])
        if isinstance(options, str):
            options = [o.strip() for o in options.split(";") if o.strip()]
        if not isinstance(options, list) or len(options) > 100:
            raise AppError("Ungültige Auswahlliste.")
        options = [str(o)[:60] for o in options]
        if ftype == "SELECT" and not options:
            raise AppError("Auswahlliste braucht mindestens einen Wert (getrennt mit ;).")
        row = {"entity": entity, "code": code, "label": label, "type": ftype, "required": b("required"),
               "options": options, "default_value": s("default_value"), "active": b("active", 1),
               "sort": i("sort"), "system": 0}
        if row["default_value"]:
            _convert(row, row["default_value"])
        row["options"] = json.dumps(options, ensure_ascii=False)
        return row

    if table == "meta_page":
        code = old["code"] if old else s("code")
        if not PAGE_CODE_RE.match(code):
            raise AppError("Seitencode: Großbuchstaben, Ziffern, _ (2–31 Zeichen).")
        title = s("title")
        if not title or len(title) > 80:
            raise AppError("Titel fehlt oder ist zu lang.")
        if old and old["kind"] == "SYSTEM":
            return {"code": code, "title": title, "kind": "SYSTEM", "config": json.dumps(old["config"]),
                    "system": 1}
        kind = s("kind")
        if kind not in ("LIST", "FORM"):
            raise AppError("Seitentyp muss Liste oder Formular sein.")
        cfg = validate_page_config(conn, kind, data.get("config") or {})
        return {"code": code, "title": title, "kind": kind, "config": json.dumps(cfg, ensure_ascii=False),
                "system": 0}

    if table == "meta_menu":
        label = s("label")
        if not label or len(label) > 40:
            raise AppError("Menütext fehlt oder ist zu lang.")
        parent = data.get("parent_id") or None
        target = s("target")
        if parent is not None:
            p = one(conn.execute("SELECT parent_id FROM meta_menu WHERE id = ?", (parent,)))
            if not p or p["parent_id"] is not None:
                raise AppError("Übergeordnetes Menü muss ein Hauptmenü sein.")
            if not target:
                raise AppError("Menüeintrag braucht eine Zielseite.")
        if target and not one(conn.execute("SELECT 1 FROM meta_page WHERE code = ?", (target,))):
            raise AppError("Zielseite existiert nicht.")
        return {"parent_id": parent, "label": label, "target": target, "sort": i("sort"),
                "active": b("active", 1)}

    if table == "meta_tcode":
        code = (old["code"] if old else s("code")).upper()
        if not TCODE_RE.match(code):
            raise AppError("T-Code: Großbuchstaben/Ziffern, 2–10 Zeichen, beginnt mit Buchstabe.")
        target = s("target")
        if not one(conn.execute("SELECT 1 FROM meta_page WHERE code = ?", (target,))):
            raise AppError("Zielseite existiert nicht.")
        return {"code": code, "target": target, "description": s("description")[:80]}

    if table == "meta_rule":
        name, trigger = s("name"), s("trigger")
        conditions, action = data.get("conditions"), data.get("action")
        err = rules_mod.validate_rule(name, trigger, conditions, action)
        if err:
            raise AppError(err)
        action = {"type": action["type"], "message": str(action.get("message", ""))}
        conditions = [{"field": c["field"], "op": c["op"], "value": c.get("value", "")} for c in conditions]
        return {"name": name, "trigger": trigger, "conditions": json.dumps(conditions, ensure_ascii=False),
                "action": json.dumps(action, ensure_ascii=False), "active": b("active", 1)}

    raise AppError("Unbekannte Tabelle.")


def _known_fields(conn, entities: list[str]) -> set[str]:
    return {f["code"] for e in entities for f in fields(conn, e, active_only=False)}


def validate_page_config(conn, kind: str, cfg: dict) -> dict:
    if not isinstance(cfg, dict):
        raise AppError("Ungültige Seitenkonfiguration.")
    if kind == "LIST":
        source = cfg.get("source")
        if source not in SYSTEM_COLUMNS:
            raise AppError("Ungültige Datenquelle.")
        allowed = {c for c, _ in SYSTEM_COLUMNS[source]} | _known_fields(conn, SOURCE_ENTITIES[source])
        cols = _field_list(cfg.get("columns"), allowed)
        if not cols:
            raise AppError("Liste braucht mindestens eine Spalte.")
        filters = [f for f in cfg.get("filters", []) if f in FILTERS[source]]
        sort = cfg.get("sort") or {}
        sort = {"field": sort.get("field") if sort.get("field") in allowed else cols[0]["field"],
                "dir": "desc" if sort.get("dir") == "desc" else "asc"}
        preset = {}
        for k, v in (cfg.get("preset") or {}).items():
            if k in PRESETS and v not in (None, "", False):
                try:
                    preset[k] = PRESETS[k](v)
                except (TypeError, ValueError):
                    raise AppError(f"Ungültige Vorbelegung: {k}")
        if "bestand" in preset and preset["bestand"] not in perms.STORES:
            raise AppError("Ungültiger Bestand in der Vorbelegung.")
        row_action = cfg.get("row_action") if cfg.get("row_action") == ROW_ACTIONS.get(source) else ""
        return {"source": source, "columns": cols, "filters": filters, "sort": sort, "preset": preset,
                "row_action": row_action}
    if kind == "FORM":
        action = cfg.get("action")
        if action not in FORM_SYSTEM_FIELDS:
            raise AppError("Ungültige Formular-Aktion.")
        system = {c for c, _, _ in FORM_SYSTEM_FIELDS[action]}
        allowed = system | _known_fields(conn, FORM_ENTITIES[action])
        flds = _field_list(cfg.get("fields"), allowed)
        missing = system - {f["field"] for f in flds}
        if missing:
            raise AppError("Systemfelder dürfen nicht entfernt werden: " + ", ".join(sorted(missing)))
        store = cfg.get("store") if cfg.get("store") in perms.STORES else ""
        return {"action": action, "fields": flds, "store": store}
    raise AppError("Ungültiger Seitentyp.")


def _field_list(items, allowed: set[str]) -> list[dict]:
    out, seen = [], set()
    for it in items or []:
        if isinstance(it, str):
            it = {"field": it}
        f = it.get("field") if isinstance(it, dict) else None
        if f not in allowed:
            raise AppError(f"Unbekanntes Feld in der Seite: {f}")
        if f in seen:
            continue
        seen.add(f)
        entry = {"field": f}
        label = str(it.get("label") or "").strip()[:60]
        if label:
            entry["label"] = label
        out.append(entry)
    return out


def _check_delete(conn, table: str, old: dict) -> None:
    if table == "categories":
        raise AppError("Kategorien werden nicht gelöscht, sondern deaktiviert.")
    if table == "meta_page":
        if old["system"]:
            raise AppError("Systemseiten können nicht gelöscht werden.")
        if one(conn.execute("SELECT 1 FROM meta_menu WHERE target = ?", (old["code"],))) or \
                one(conn.execute("SELECT 1 FROM meta_tcode WHERE target = ?", (old["code"],))):
            raise AppError("Seite wird noch in Menü oder T-Code verwendet.")
    if table == "meta_menu" and one(conn.execute("SELECT 1 FROM meta_menu WHERE parent_id = ?", (old["id"],))):
        raise AppError("Menü hat noch Untereinträge.")
    if table == "meta_field":
        for p in table_rows(conn, "meta_page"):
            items = p["config"].get("columns", []) + p["config"].get("fields", [])
            if any(i.get("field") == old["code"] for i in items):
                raise AppError(f"Feld wird noch in Seite {p['code']} verwendet. Bitte zuerst dort entfernen "
                               f"oder das Feld deaktivieren.")


def save(conn, user: dict, table: str, data: dict, ip: str, pk=None) -> dict:
    if table not in PK:
        raise NotFound()
    perms.require(conn, user, perms.CUSTOMIZING)
    key = PK[table]
    with write_tx(conn):
        old = None
        if pk is not None:
            old = one(conn.execute(f"SELECT * FROM {table} WHERE {key} = ?", (pk,)))
            if not old:
                raise NotFound()
            old = _decode(table, old)
        row = _clean(table, data, old, conn)
        try:
            if old:
                sets = ",".join(f"{c} = ?" for c in row)
                conn.execute(f"UPDATE {table} SET {sets} WHERE {key} = ?", [*row.values(), pk])
                obj_id = pk
            else:
                cols = list(row)
                cur = conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                                   list(row.values()))
                obj_id = row.get(key, cur.lastrowid)
        except Exception as e:  # sqlite3.IntegrityError
            if "UNIQUE" in str(e):
                raise AppError(f"{TABLE_LABELS[table]} existiert bereits.")
            raise
        new = _decode(table, one(conn.execute(f"SELECT * FROM {table} WHERE {key} = ?", (obj_id,))))
        verb = "GEAENDERT" if old else "ANGELEGT"
        version = create_version(conn, user, f"{TABLE_LABELS[table]} {obj_id} {verb.lower()}")
        audit.append(conn, user, f"CUSTOMIZING_{verb}", table, obj_id, old=old,
                     new={**new, "_version": version}, ip=ip)
    return new


def delete(conn, user: dict, table: str, pk, ip: str) -> None:
    if table not in PK:
        raise NotFound()
    perms.require(conn, user, perms.CUSTOMIZING)
    key = PK[table]
    with write_tx(conn):
        old = one(conn.execute(f"SELECT * FROM {table} WHERE {key} = ?", (pk,)))
        if not old:
            raise NotFound()
        old = _decode(table, old)
        _check_delete(conn, table, old)
        conn.execute(f"DELETE FROM {table} WHERE {key} = ?", (pk,))
        version = create_version(conn, user, f"{TABLE_LABELS[table]} {pk} gelöscht")
        audit.append(conn, user, "CUSTOMIZING_GELOESCHT", table, pk, old=old, new={"_version": version}, ip=ip)


def set_permission(conn, user: dict, store: str, function: str, allowed: bool, ip: str) -> None:
    perms.require(conn, user, perms.CUSTOMIZING)
    if (store, function) not in [tuple(c) for c in perms.CONFIGURABLE]:
        raise AppError("Dieses Recht ist fest vorgegeben und nicht einstellbar.")
    with write_tx(conn):
        r = one(conn.execute("SELECT allowed FROM permissions WHERE role = ? AND store_code = ? AND function = ?",
                             (perms.USER, store, function)))
        old = bool(r and r["allowed"])
        if old == allowed:
            return
        conn.execute(
            "INSERT INTO permissions(role, store_code, function, allowed) VALUES (?,?,?,?) "
            "ON CONFLICT(role, store_code, function) DO UPDATE SET allowed = excluded.allowed",
            (perms.USER, store, function, 1 if allowed else 0),
        )
        version = create_version(conn, user, f"Recht {function}/{store} für Benutzer geändert")
        audit.append(conn, user, "RECHT_GEAENDERT", "permissions", f"{perms.USER}/{store}/{function}",
                     old={"erlaubt": old}, new={"erlaubt": allowed, "_version": version}, ip=ip)


def set_setting(conn, user: dict, key: str, value, ip: str) -> None:
    perms.require(conn, user, perms.CUSTOMIZING)
    if key not in SETTINGS:
        raise AppError("Unbekannte Einstellung.")
    label, typ, lo, hi = SETTINGS[key]
    try:
        n = int(value if not isinstance(value, bool) else int(value))
    except (TypeError, ValueError):
        raise AppError(f"„{label}“: ungültiger Wert.")
    if not lo <= n <= hi:
        raise AppError(f"„{label}“: erlaubt {lo} bis {hi}.")
    with write_tx(conn):
        old = get_setting(conn, key)
        if old == str(n):
            return
        conn.execute("INSERT INTO settings(key, value) VALUES (?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(n)))
        version = create_version(conn, user, f"Einstellung {key} geändert")
        action = "RECHT_GEAENDERT" if key == "privat_lesbar" else "EINSTELLUNG_GEAENDERT"
        audit.append(conn, user, action, "settings", key, old={key: old},
                     new={key: str(n), "_version": version}, ip=ip)
