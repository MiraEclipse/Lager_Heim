"""Erstbefüllung: Rollen, Bestände, Einstellungen und die Standard-Konfiguration."""
import json

from . import audit, meta
from .config import VERSION
from .db import now_iso, write_tx

SYSTEM_PAGES = [
    ("SYS_START", "Startbild"),
    ("SYS_PROTOKOLL", "Protokoll anzeigen"),
    ("SYS_PRUEFUNG", "Protokoll prüfen / Quittung"),
    ("SYS_BENUTZER", "Benutzerverwaltung"),
    ("SYS_PASSWORT", "Passwort ändern"),
    ("SYS_FELDER", "Customizing: Felder"),
    ("SYS_KATEGORIEN", "Customizing: Kategorien"),
    ("SYS_SEITEN", "Customizing: Seiten und Masken"),
    ("SYS_MENUES", "Customizing: Menüs und T-Codes"),
    ("SYS_REGELN", "Customizing: Regeln"),
    ("SYS_RECHTE", "Customizing: Rechte"),
    ("SYS_VERSIONEN", "Customizing: Versionen"),
    ("SYS_EINSTELLUNGEN", "Customizing: Einstellungen"),
    ("SYS_BACKUP", "Backup und Wiederherstellung"),
]

LOT_COLS = ["bestand", "ean", "bezeichnung", "kategorie", "mhd", "tage_bis_mhd", "charge", "menge"]
LOT_FILTERS = ["bestand", "ean", "bezeichnung", "kategorie", "mhd_von", "mhd_bis", "charge"]

PAGES = [
    ("BESTAND_LISTE", "Bestandsliste", "LIST", {
        "source": "lots", "columns": LOT_COLS, "filters": LOT_FILTERS,
        "sort": {"field": "mhd", "dir": "asc"}, "preset": {"nur_bestand": True}, "row_action": "auschecken"}),
    ("ABLAUF_LISTE", "Bald ablaufende Artikel", "LIST", {
        "source": "lots", "columns": LOT_COLS, "filters": ["bestand", "kategorie"],
        "sort": {"field": "mhd", "dir": "asc"}, "preset": {"ablauf_tage": 14}, "row_action": "auschecken"}),
    ("BUCHUNGEN", "Buchungen", "LIST", {
        "source": "movements",
        "columns": ["id", "zeitpunkt", "benutzer", "typ", "bestand", "ean", "bezeichnung", "mhd", "charge",
                    "menge", "menge_danach", "admin_eingriff", "begruendung", "gekauft_bei"],
        "filters": ["bestand", "ean", "benutzer", "typ", "von", "bis", "charge"],
        "sort": {"field": "id", "dir": "desc"}, "preset": {}, "row_action": ""}),
    ("ARTIKEL", "Artikelstamm", "LIST", {
        "source": "articles",
        "columns": ["ean", "bezeichnung", "kategorie", "bestand_keller", "bestand_privat", "angelegt_am",
                    "angelegt_von"],
        "filters": ["ean", "bezeichnung", "kategorie"],
        "sort": {"field": "bezeichnung", "dir": "asc"}, "preset": {}, "row_action": "bearbeiten"}),
    ("EINCHECKEN", "Einchecken (Zugang)", "FORM", {
        "action": "einchecken",
        "fields": ["bestand", "ean", "bezeichnung", "kategorie", "mhd", "charge", "menge", "gekauft_bei",
                   "begruendung"], "store": ""}),
    ("AUSCHECKEN", "Auschecken (Abgang)", "FORM", {
        "action": "auschecken", "fields": ["bestand", "ean", "position", "menge", "begruendung"], "store": ""}),
]

TCODES = [
    ("ZS00", "SYS_START", "Startbild"),
    ("ZE01", "EINCHECKEN", "Einchecken"), ("ZA01", "AUSCHECKEN", "Auschecken"),
    ("ZB01", "BESTAND_LISTE", "Bestandsliste"), ("ZB02", "ABLAUF_LISTE", "Bald ablaufende Artikel"),
    ("ZB03", "BUCHUNGEN", "Buchungen"), ("ZB04", "ARTIKEL", "Artikelstamm"),
    ("ZP01", "SYS_PROTOKOLL", "Protokoll"), ("ZP02", "SYS_PRUEFUNG", "Protokoll prüfen / Quittung"),
    ("ZU01", "SYS_BENUTZER", "Benutzerverwaltung"), ("ZU02", "SYS_PASSWORT", "Passwort ändern"),
    ("ZC01", "SYS_FELDER", "Felder"), ("ZC02", "SYS_KATEGORIEN", "Kategorien"),
    ("ZC03", "SYS_SEITEN", "Seiten und Masken"), ("ZC04", "SYS_MENUES", "Menüs und T-Codes"),
    ("ZC05", "SYS_REGELN", "Regeln"), ("ZC06", "SYS_RECHTE", "Rechte"), ("ZC07", "SYS_VERSIONEN", "Versionen"),
    ("ZS01", "SYS_BACKUP", "Backup"), ("ZS02", "SYS_EINSTELLUNGEN", "Einstellungen"),
]

MENUS = [
    ("Bestand", ["EINCHECKEN", "AUSCHECKEN", "BESTAND_LISTE", "ABLAUF_LISTE", "BUCHUNGEN", "ARTIKEL"]),
    ("Protokoll", ["SYS_PROTOKOLL", "SYS_PRUEFUNG"]),
    ("Customizing", ["SYS_FELDER", "SYS_KATEGORIEN", "SYS_SEITEN", "SYS_MENUES", "SYS_REGELN", "SYS_RECHTE",
                     "SYS_VERSIONEN", "SYS_EINSTELLUNGEN"]),
    ("System", ["SYS_BENUTZER", "SYS_PASSWORT", "SYS_BACKUP"]),
]

CATEGORIES = ["Schokolade", "Fruchtgummi", "Chips und Snacks", "Kekse und Gebäck", "Bonbons", "Sonstiges"]


def _labels():
    labels = dict(SYSTEM_PAGES)
    labels.update({c: t for c, t, _, _ in PAGES})
    return labels


def seed(conn) -> bool:
    """Befüllt eine leere Datenbank. Liefert True, wenn befüllt wurde."""
    if conn.execute("SELECT 1 FROM schema_info WHERE key = 'seeded'").fetchone():
        return False
    labels = _labels()
    with write_tx(conn):
        ins = conn.execute
        ins("INSERT INTO roles(code, name) VALUES ('ADMIN','Administrator'), ('USER','Benutzer')")
        ins("INSERT INTO stores(code, name) VALUES ('KELLER','Keller'), ('PRIVAT','Mein Bestand')")
        for k, v in {"privat_lesbar": "0", "session_timeout_min": "15", "mhd_warn_tage": "7",
                     "backup_stunde": "2"}.items():
            ins("INSERT INTO settings(key, value) VALUES (?,?)", (k, v))
        for i, name in enumerate(CATEGORIES):
            ins("INSERT INTO categories(name, active, sort) VALUES (?,1,?)", (name, i * 10))
        for store, fn, allowed in [("KELLER", "BESTAND_LESEN", 1), ("KELLER", "EINCHECKEN", 1),
                                   ("KELLER", "AUSCHECKEN", 1), ("*", "ARTIKEL_PFLEGEN", 0)]:
            ins("INSERT INTO permissions(role, store_code, function, allowed) VALUES ('USER',?,?,?)",
                (store, fn, allowed))
        ins("INSERT INTO meta_field(entity, code, label, type, required, options, sort) "
            "VALUES ('buchung','gekauft_bei','Gekauft bei','TEXT',0,'[]',10)")
        for code, title in SYSTEM_PAGES:
            ins("INSERT INTO meta_page(code, title, kind, config, system) VALUES (?,?,'SYSTEM','{}',1)",
                (code, title))
        for code, title, kind, cfg in PAGES:
            clean = meta.validate_page_config(conn, kind, cfg)
            ins("INSERT INTO meta_page(code, title, kind, config, system) VALUES (?,?,?,?,0)",
                (code, title, kind, json.dumps(clean, ensure_ascii=False)))
        for code, target, desc in TCODES:
            ins("INSERT INTO meta_tcode(code, target, description) VALUES (?,?,?)", (code, target, desc))
        for i, (label, targets) in enumerate(MENUS):
            pid = ins("INSERT INTO meta_menu(parent_id, label, target, sort) VALUES (NULL,?, '',?)",
                      (label, i * 10)).lastrowid
            for j, t in enumerate(targets):
                ins("INSERT INTO meta_menu(parent_id, label, target, sort) VALUES (?,?,?,?)",
                    (pid, labels[t].replace("Customizing: ", ""), t, j * 10))
        ins("INSERT INTO meta_rule(name, trigger, conditions, action) VALUES (?,?,?,?)",
            ("MHD läuft bald ab (Liste)", "ANZEIGE",
             json.dumps([{"field": "mhd", "op": "days_until_lt", "value": 7}]),
             json.dumps({"type": "HIGHLIGHT", "message": "MHD in weniger als 7 Tagen"}, ensure_ascii=False)))
        ins("INSERT INTO meta_rule(name, trigger, conditions, action) VALUES (?,?,?,?)",
            ("MHD läuft bald ab (Buchung)", "BUCHUNG",
             json.dumps([{"field": "mhd", "op": "days_until_lt", "value": 7}]),
             json.dumps({"type": "WARN", "message": "MHD läuft in weniger als 7 Tagen ab"}, ensure_ascii=False)))
        version = meta.create_version(conn, None, "Initiale Konfiguration")
        ins("INSERT INTO schema_info(key, value) VALUES ('seeded', ?), ('version', ?)", (now_iso(), VERSION))
        audit.append(conn, None, "INSTALLATION", "SYSTEM", "lager-heim",
                     new={"version": VERSION, "konfigurationsversion": version})
    return True
