"""Einfache Regel-Engine. Bedingungen sind Daten (JSON), es wird kein Code ausgeführt."""
from datetime import date

OPS = {
    "eq": "gleich", "ne": "ungleich", "lt": "kleiner", "le": "kleiner gleich",
    "gt": "größer", "ge": "größer gleich", "contains": "enthält",
    "empty": "ist leer", "notempty": "ist nicht leer",
    "days_until_lt": "Tage bis Datum kleiner", "days_until_le": "Tage bis Datum kleiner gleich",
}
ACTIONS = {"WARN": "Warnung anzeigen", "BLOCK": "Buchung verhindern", "HIGHLIGHT": "Zeile markieren"}
TRIGGERS = {"ANZEIGE": "Bei Anzeige (Listen)", "BUCHUNG": "Bei Buchung"}


def days_until(value, today: date | None = None) -> int | None:
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
    return (d - (today or date.today())).days


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cmp(a, b):
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return (na > nb) - (na < nb)
    sa, sb = str(a if a is not None else ""), str(b if b is not None else "")
    return (sa > sb) - (sa < sb)


def condition_true(cond: dict, row: dict, today: date | None = None) -> bool:
    v = row.get(cond.get("field"))
    op, ref = cond.get("op"), cond.get("value")
    if op == "empty":
        return v in (None, "", False)
    if op == "notempty":
        return v not in (None, "", False)
    if op in ("days_until_lt", "days_until_le"):
        d, n = days_until(v, today), _num(ref)
        if d is None or n is None:
            return False
        return d < n if op == "days_until_lt" else d <= n
    if op == "contains":
        return str(ref or "").lower() in str(v or "").lower()
    if v is None:
        return False
    c = _cmp(v, ref)
    return {"eq": c == 0, "ne": c != 0, "lt": c < 0, "le": c <= 0, "gt": c > 0, "ge": c >= 0}.get(op, False)


def evaluate(rules: list[dict], row: dict, trigger: str, today: date | None = None) -> list[dict]:
    hits = []
    for r in rules:
        if not r["active"] or r["trigger"] != trigger:
            continue
        conds = r["conditions"]
        if conds and all(condition_true(c, row, today) for c in conds):
            hits.append({"rule": r["name"], "type": r["action"].get("type", "WARN"),
                         "message": r["action"].get("message") or r["name"]})
    return hits


def validate_rule(name: str, trigger: str, conditions, action) -> str | None:
    if not name or len(name) > 100:
        return "Regelname fehlt oder ist zu lang."
    if trigger not in TRIGGERS:
        return "Ungültiger Auslöser."
    if not isinstance(conditions, list) or not conditions or len(conditions) > 10:
        return "Mindestens eine (höchstens zehn) Bedingung(en) erforderlich."
    for c in conditions:
        if not isinstance(c, dict) or c.get("op") not in OPS or not isinstance(c.get("field"), str):
            return "Ungültige Bedingung."
        if not isinstance(c.get("value", ""), (str, int, float)):
            return "Ungültiger Vergleichswert."
    if not isinstance(action, dict) or action.get("type") not in ACTIONS:
        return "Ungültige Aktion."
    if len(str(action.get("message", ""))) > 200:
        return "Meldungstext ist zu lang."
    return None
