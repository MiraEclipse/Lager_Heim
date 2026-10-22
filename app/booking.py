"""Einchecken, Auschecken und Bestandsabfragen."""
import json
from datetime import date

from . import audit, ean as ean_mod, meta, perms
from . import rules as rules_mod
from .db import now_iso, one, rows, write_tx
from .errors import AppError, NotFound


def _clean_text(v, label: str, maxlen: int, required: bool = False) -> str:
    v = str(v or "").strip()
    if required and not v:
        raise AppError(f"{label} fehlt.")
    if len(v) > maxlen:
        raise AppError(f"{label} ist zu lang (max. {maxlen} Zeichen).")
    return v


def _qty(v) -> int:
    try:
        q = int(v)
    except (TypeError, ValueError):
        raise AppError("Menge muss eine ganze Zahl sein.")
    if q < 1 or q > 100000:
        raise AppError("Menge muss zwischen 1 und 100000 liegen.")
    return q


def _mhd(v) -> str:
    try:
        return date.fromisoformat(str(v or "")).isoformat()
    except ValueError:
        raise AppError("MHD fehlt oder ist kein gültiges Datum.")


def article(conn, ean: str) -> dict | None:
    a = one(conn.execute(
        "SELECT a.*, c.name AS kategorie FROM articles a LEFT JOIN categories c ON c.id = a.category_id "
        "WHERE a.ean = ?", (ean,)))
    if a:
        a["custom"] = json.loads(a["custom"])
    return a


def _rule_row(lot: dict, art: dict, extra: dict) -> dict:
    row = {"ean": lot["ean"], "mhd": lot["mhd"], "charge": lot["charge"], "bestand": lot["store_code"],
           "bezeichnung": art["name"], "kategorie": art.get("kategorie") or "",
           "tage_bis_mhd": rules_mod.days_until(lot["mhd"])}
    row.update(art["custom"])
    row.update(extra)
    return row


def _apply_rules(conn, row: dict, force: bool) -> list[dict]:
    hits = rules_mod.evaluate(meta.active_rules(conn), row, "BUCHUNG")
    blocks = [h for h in hits if h["type"] == "BLOCK"]
    if blocks:
        raise AppError("Buchung durch Regel verhindert: " + blocks[0]["message"], 409)
    warns = [h for h in hits if h["type"] == "WARN"]
    return warns if not force else []


def checkin(conn, user: dict, data: dict, ip: str) -> dict:
    store = data.get("bestand")
    if store not in perms.STORES:
        raise AppError("Ungültiger Bestand.")
    perms.require(conn, user, perms.EINCHECKEN, store)
    ean = _clean_text(data.get("ean"), "EAN", 13, True)
    err = ean_mod.validate(ean)
    if err:
        raise AppError("EAN ungültig: " + err)
    mhd = _mhd(data.get("mhd"))
    charge = _clean_text(data.get("charge"), "Charge", 40)
    qty = _qty(data.get("menge"))
    admin_eingriff = perms.is_admin_intervention(user, store)
    begruendung = _clean_text(data.get("begruendung"), "Begründung", 300, required=admin_eingriff)
    custom = meta.validate_custom(conn, "buchung", data.get("custom_buchung"))

    with write_tx(conn):
        art = article(conn, ean)
        if not art:
            name = _clean_text(data.get("bezeichnung"), "Bezeichnung", 100, True)
            cat_id = data.get("kategorie_id") or None
            if cat_id is not None and not one(conn.execute(
                    "SELECT 1 FROM categories WHERE id = ? AND active = 1", (cat_id,))):
                raise AppError("Ungültige Kategorie.")
            art_custom = meta.validate_custom(conn, "artikel", data.get("custom_artikel"))
            conn.execute(
                "INSERT INTO articles(ean, name, category_id, custom, created_at, created_by) VALUES (?,?,?,?,?,?)",
                (ean, name, cat_id, json.dumps(art_custom, ensure_ascii=False), now_iso(), user["username"]))
            art = article(conn, ean)
            audit.append(conn, user, "ARTIKEL_ANGELEGT", "ARTIKEL", ean, store_code="", old=None,
                         new={"ean": ean, "bezeichnung": name, "kategorie": art["kategorie"],
                              "custom": art_custom}, ip=ip)

        lot = one(conn.execute("SELECT * FROM lots WHERE store_code = ? AND ean = ? AND mhd = ? AND charge = ?",
                               (store, ean, mhd, charge)))
        if not lot:
            cur = conn.execute("INSERT INTO lots(store_code, ean, mhd, charge, qty, created_at) VALUES (?,?,?,?,0,?)",
                               (store, ean, mhd, charge, now_iso()))
            lot = one(conn.execute("SELECT * FROM lots WHERE id = ?", (cur.lastrowid,)))

        warnings = _apply_rules(conn, _rule_row(lot, art, {"typ": "IN", "menge": qty, **custom}),
                                bool(data.get("trotz_warnung")))
        if warnings:
            raise NeedsConfirm(warnings)
        return _book(conn, user, lot, art, "IN", qty, admin_eingriff, begruendung, custom, ip)


def checkout(conn, user: dict, data: dict, ip: str) -> dict:
    try:
        lot_id = int(data.get("position"))
    except (TypeError, ValueError):
        raise AppError("Bitte eine Bestandsposition wählen.")
    qty = _qty(data.get("menge"))
    custom = meta.validate_custom(conn, "buchung", data.get("custom_buchung"))
    with write_tx(conn):
        lot = one(conn.execute("SELECT * FROM lots WHERE id = ?", (lot_id,)))
        if not lot:
            raise NotFound("Bestandsposition nicht gefunden.")
        perms.require(conn, user, perms.AUSCHECKEN, lot["store_code"])
        admin_eingriff = perms.is_admin_intervention(user, lot["store_code"])
        begruendung = _clean_text(data.get("begruendung"), "Begründung", 300, required=admin_eingriff)
        if qty > lot["qty"]:
            raise AppError(f"Nicht genug Bestand (vorhanden: {lot['qty']}).")
        art = article(conn, lot["ean"])
        warnings = _apply_rules(conn, _rule_row(lot, art, {"typ": "OUT", "menge": qty, **custom}),
                                bool(data.get("trotz_warnung")))
        if warnings:
            raise NeedsConfirm(warnings)
        return _book(conn, user, lot, art, "OUT", qty, admin_eingriff, begruendung, custom, ip)


class NeedsConfirm(AppError):
    """Regel-Warnung: Buchung erst nach Bestätigung (trotz_warnung) ausführen."""

    def __init__(self, warnings):
        super().__init__("Warnung: " + "; ".join(w["message"] for w in warnings) +
                         " – Buchung trotzdem ausführen?", 409)
        self.warnings = warnings


def _book(conn, user, lot, art, typ, qty, admin_eingriff, begruendung, custom, ip) -> dict:
    new_qty = lot["qty"] + qty if typ == "IN" else lot["qty"] - qty
    conn.execute("UPDATE lots SET qty = ? WHERE id = ?", (new_qty, lot["id"]))
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO movements(ts, user_id, username, store_code, lot_id, ean, mhd, charge, type, qty, qty_after,"
        " admin_eingriff, begruendung, custom) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, user["id"], user["username"], lot["store_code"], lot["id"], lot["ean"], lot["mhd"], lot["charge"],
         typ, qty, new_qty, 1 if admin_eingriff else 0, begruendung, json.dumps(custom, ensure_ascii=False)))
    mov_id = cur.lastrowid
    base = {"position": lot["id"], "ean": lot["ean"], "bezeichnung": art["name"], "mhd": lot["mhd"],
            "charge": lot["charge"]}
    entry = audit.append(
        conn, user, "EINCHECKEN" if typ == "IN" else "AUSCHECKEN", "BUCHUNG", mov_id,
        store_code=lot["store_code"], admin_eingriff=admin_eingriff,
        old={**base, "menge": lot["qty"]},
        new={**base, "menge": new_qty, "buchungsmenge": qty, "begruendung": begruendung, "custom": custom},
        ip=ip)
    return {"beleg": mov_id, "position": lot["id"], "menge_danach": new_qty, "admin_eingriff": admin_eingriff,
            "protokoll_seq": entry["seq"]}


def update_article(conn, user: dict, ean: str, data: dict, ip: str) -> dict:
    perms.require(conn, user, perms.ARTIKEL_PFLEGEN)
    with write_tx(conn):
        old = article(conn, ean)
        if not old:
            raise NotFound("Artikel nicht gefunden.")
        name = _clean_text(data.get("bezeichnung"), "Bezeichnung", 100, True)
        cat_id = data.get("kategorie_id") or None
        if cat_id is not None and not one(conn.execute("SELECT 1 FROM categories WHERE id = ?", (cat_id,))):
            raise AppError("Ungültige Kategorie.")
        custom = meta.validate_custom(conn, "artikel", data.get("custom_artikel"))
        conn.execute("UPDATE articles SET name = ?, category_id = ?, custom = ? WHERE ean = ?",
                     (name, cat_id, json.dumps(custom, ensure_ascii=False), ean))
        new = article(conn, ean)
        strip = lambda a: {"bezeichnung": a["name"], "kategorie": a["kategorie"], "custom": a["custom"]}  # noqa
        audit.append(conn, user, "ARTIKEL_GEAENDERT", "ARTIKEL", ean, old=strip(old), new=strip(new), ip=ip)
    return new


# ---------------------------------------------------------------- Abfragen
def _filters(conn, user, params: dict, source: str):
    where, args = [], []
    readable = perms.stores_for(conn, user, perms.BESTAND_LESEN)
    store = params.get("bestand")
    stores = [store] if store in readable else ([] if store else readable)
    if not stores:
        return None, None
    where.append(f"x.store_code IN ({','.join('?' * len(stores))})")
    args += stores
    if params.get("ean"):
        where.append("x.ean LIKE ?")
        args.append(str(params["ean"]).strip() + "%")
    if params.get("bezeichnung"):
        where.append("a.name LIKE ?")
        args.append("%" + str(params["bezeichnung"]).strip() + "%")
    if params.get("kategorie"):
        where.append("c.name = ?")
        args.append(params["kategorie"])
    if params.get("charge"):
        where.append("x.charge LIKE ?")
        args.append("%" + str(params["charge"]).strip() + "%")
    if params.get("mhd_von"):
        where.append("x.mhd >= ?")
        args.append(params["mhd_von"])
    if params.get("mhd_bis"):
        where.append("x.mhd <= ?")
        args.append(params["mhd_bis"])
    if source == "lots":
        if params.get("nur_bestand") in ("1", "true", True):
            where.append("x.qty > 0")
        if params.get("ablauf_tage") not in (None, ""):
            try:
                days = int(params["ablauf_tage"])
            except ValueError:
                raise AppError("Ungültige Tageszahl.")
            where.append("x.qty > 0 AND x.mhd <= date('now', ?)")
            args.append(f"+{days} days")
    if source == "movements":
        if params.get("benutzer"):
            where.append("x.username LIKE ?")
            args.append("%" + str(params["benutzer"]).strip() + "%")
        if params.get("typ") in ("IN", "OUT"):
            where.append("x.type = ?")
            args.append(params["typ"])
        if params.get("von"):
            where.append("x.ts >= ?")
            args.append(params["von"])
        if params.get("bis"):
            where.append("x.ts < date(?, '+1 day')")
            args.append(params["bis"])
        if params.get("nur_admin_eingriffe") in ("1", "true", True):
            where.append("x.admin_eingriff = 1")
    return " AND ".join(where), args


def list_lots(conn, user: dict, params: dict) -> list[dict]:
    where, args = _filters(conn, user, params, "lots")
    if where is None:
        return []
    out = []
    rule_list = meta.active_rules(conn)
    for r in rows(conn.execute(
            "SELECT x.*, a.name, c.name AS kategorie, a.custom FROM lots x JOIN articles a ON a.ean = x.ean "
            f"LEFT JOIN categories c ON c.id = a.category_id WHERE {where} ORDER BY x.mhd, x.id LIMIT 5000", args)):
        row = {"id": r["id"], "bestand": r["store_code"], "ean": r["ean"], "bezeichnung": r["name"],
               "kategorie": r["kategorie"] or "", "mhd": r["mhd"], "tage_bis_mhd": rules_mod.days_until(r["mhd"]),
               "charge": r["charge"], "menge": r["qty"]}
        row.update(json.loads(r["custom"]))
        row["_hinweise"] = rules_mod.evaluate(rule_list, row, "ANZEIGE") if r["qty"] > 0 else []
        out.append(row)
    return out


def list_movements(conn, user: dict, params: dict) -> list[dict]:
    where, args = _filters(conn, user, params, "movements")
    if where is None:
        return []
    out = []
    for r in rows(conn.execute(
            "SELECT x.*, a.name, c.name AS kategorie, a.custom AS acustom FROM movements x "
            "JOIN articles a ON a.ean = x.ean LEFT JOIN categories c ON c.id = a.category_id "
            f"WHERE {where} ORDER BY x.id DESC LIMIT 5000", args)):
        row = {"id": r["id"], "zeitpunkt": r["ts"], "benutzer": r["username"],
               "typ": "Zugang" if r["type"] == "IN" else "Abgang", "bestand": r["store_code"], "ean": r["ean"],
               "bezeichnung": r["name"], "kategorie": r["kategorie"] or "", "mhd": r["mhd"],
               "charge": r["charge"], "menge": r["qty"], "menge_danach": r["qty_after"],
               "admin_eingriff": bool(r["admin_eingriff"]), "begruendung": r["begruendung"]}
        row.update(json.loads(r["acustom"]))
        row.update(json.loads(r["custom"]))
        row["_hinweise"] = [{"type": "HIGHLIGHT", "message": "Admin-Eingriff"}] if r["admin_eingriff"] else []
        out.append(row)
    return out


def list_articles(conn, user: dict, params: dict) -> list[dict]:
    readable = perms.stores_for(conn, user, perms.BESTAND_LESEN)
    where, args = ["1=1"], []
    if params.get("ean"):
        where.append("a.ean LIKE ?")
        args.append(str(params["ean"]).strip() + "%")
    if params.get("bezeichnung"):
        where.append("a.name LIKE ?")
        args.append("%" + str(params["bezeichnung"]).strip() + "%")
    if params.get("kategorie"):
        where.append("c.name = ?")
        args.append(params["kategorie"])
    out = []
    for r in rows(conn.execute(
            "SELECT a.*, c.name AS kategorie, "
            "(SELECT COALESCE(SUM(qty),0) FROM lots WHERE ean = a.ean AND store_code = 'KELLER') AS mk, "
            "(SELECT COALESCE(SUM(qty),0) FROM lots WHERE ean = a.ean AND store_code = 'PRIVAT') AS mp "
            f"FROM articles a LEFT JOIN categories c ON c.id = a.category_id WHERE {' AND '.join(where)} "
            "ORDER BY a.name LIMIT 5000", args)):
        row = {"ean": r["ean"], "bezeichnung": r["name"], "kategorie": r["kategorie"] or "",
               "kategorie_id": r["category_id"],
               "bestand_keller": r["mk"] if perms.KELLER in readable else None,
               "bestand_privat": r["mp"] if perms.PRIVAT in readable else None,
               "angelegt_am": r["created_at"], "angelegt_von": r["created_by"]}
        row.update(json.loads(r["custom"]))
        row["_custom"] = json.loads(r["custom"])
        row["_hinweise"] = []
        out.append(row)
    return out


def lots_for_checkout(conn, user: dict, store: str, ean: str) -> list[dict]:
    if not perms.can(conn, user, perms.AUSCHECKEN, store):
        return []
    return rows(conn.execute(
        "SELECT id, mhd, charge, qty FROM lots WHERE store_code = ? AND ean = ? AND qty > 0 ORDER BY mhd, id",
        (store, ean)))


def expiring_count(conn, user: dict, days: int) -> int:
    stores = perms.stores_for(conn, user, perms.BESTAND_LESEN)
    if not stores:
        return 0
    return conn.execute(
        f"SELECT COUNT(*) FROM lots WHERE qty > 0 AND mhd <= date('now', ?) "
        f"AND store_code IN ({','.join('?' * len(stores))})", [f"+{days} days", *stores]).fetchone()[0]
