"""Rechteprüfung.

Reihenfolge:
1. Feste Regeln im Code (durch Customizing nicht aushebelbar).
2. Konfigurierbare Rechte aus der Tabelle `permissions`.
"""
from .errors import Forbidden

ADMIN = "ADMIN"
USER = "USER"
KELLER = "KELLER"
PRIVAT = "PRIVAT"
STORES = (KELLER, PRIVAT)

# Funktionen mit Bestandsbezug
BESTAND_LESEN = "BESTAND_LESEN"
EINCHECKEN = "EINCHECKEN"
AUSCHECKEN = "AUSCHECKEN"
# Funktionen ohne Bestandsbezug
ARTIKEL_PFLEGEN = "ARTIKEL_PFLEGEN"
PROTOKOLL_LESEN = "PROTOKOLL_LESEN"
BENUTZER = "BENUTZER"
CUSTOMIZING = "CUSTOMIZING"
BACKUP = "BACKUP"

FUNCTIONS = {
    BESTAND_LESEN: ("Bestand anzeigen", True),
    EINCHECKEN: ("Einchecken (Zugang)", True),
    AUSCHECKEN: ("Auschecken (Abgang)", True),
    ARTIKEL_PFLEGEN: ("Artikelstamm pflegen", False),
    PROTOKOLL_LESEN: ("Protokoll einsehen", False),
    BENUTZER: ("Benutzerverwaltung", False),
    CUSTOMIZING: ("Customizing", False),
    BACKUP: ("Backup/Wiederherstellung", False),
}

# Fest: nur der Admin
ADMIN_ONLY = {BENUTZER, CUSTOMIZING, BACKUP}
# Fest: alle angemeldeten Benutzer (Transparenz)
ALWAYS = {PROTOKOLL_LESEN}
# In der Rechtematrix für Benutzer einstellbar
CONFIGURABLE = [
    (KELLER, BESTAND_LESEN), (KELLER, EINCHECKEN), (KELLER, AUSCHECKEN), ("*", ARTIKEL_PFLEGEN),
]


def _setting(conn, key: str, default: str = "") -> str:
    r = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return r["value"] if r else default


def can(conn, user: dict, function: str, store: str | None = None) -> bool:
    if function not in FUNCTIONS:
        return False
    if FUNCTIONS[function][1] and store not in STORES:
        return False
    if user["role"] == ADMIN:
        return True  # Admin behält technisch volle Rechte
    if function in ADMIN_ONLY:
        return False
    if function in ALWAYS:
        return True
    if store == PRIVAT:
        # "Mein Bestand": Schreiben ausschließlich durch den Admin
        if function in (EINCHECKEN, AUSCHECKEN):
            return False
        if function == BESTAND_LESEN:
            return _setting(conn, "privat_lesbar", "0") == "1"
    r = conn.execute(
        "SELECT allowed FROM permissions WHERE role = ? AND store_code = ? AND function = ?",
        (user["role"], store or "*", function),
    ).fetchone()
    return bool(r and r["allowed"])


def require(conn, user: dict, function: str, store: str | None = None) -> None:
    if not can(conn, user, function, store):
        raise Forbidden()


def stores_for(conn, user: dict, function: str) -> list[str]:
    return [s for s in STORES if can(conn, user, function, s)]


def is_admin_intervention(user: dict, store: str) -> bool:
    """Jede Admin-Buchung im Keller ist ein gekennzeichneter Admin-Eingriff."""
    return user["role"] == ADMIN and store == KELLER


def capabilities(conn, user: dict) -> dict:
    caps = {}
    for f, (_, store_bound) in FUNCTIONS.items():
        if store_bound:
            caps[f] = stores_for(conn, user, f)
        else:
            caps[f] = can(conn, user, f)
    return caps
