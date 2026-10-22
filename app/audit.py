"""Append-only-Protokoll mit SHA-256-Hash-Kette."""
import hashlib
import json

from .db import now_iso

GENESIS = "0" * 64
HASH_FIELDS = (
    "seq", "ts", "user_id", "username", "action", "object_type", "object_id",
    "store_code", "admin_eingriff", "old_value", "new_value", "ip", "prev_hash",
)


def _dump(value) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(entry: dict) -> str:
    payload = {k: entry[k] for k in HASH_FIELDS}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def head(conn) -> dict:
    r = conn.execute("SELECT seq, hash, ts FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
    if not r:
        return {"seq": 0, "hash": GENESIS, "ts": None}
    return {"seq": r["seq"], "hash": r["hash"], "ts": r["ts"]}


def append(conn, actor: dict | None, action: str, object_type: str, object_id="",
           store_code: str = "", admin_eingriff: bool = False, old=None, new=None, ip: str = "") -> dict:
    """Hängt einen Eintrag an. Muss innerhalb einer Schreibtransaktion aufgerufen werden."""
    last = head(conn)
    entry = {
        "seq": last["seq"] + 1,
        "ts": now_iso(),
        "user_id": actor["id"] if actor else None,
        "username": actor["username"] if actor else "SYSTEM",
        "action": action,
        "object_type": object_type,
        "object_id": str(object_id),
        "store_code": store_code or "",
        "admin_eingriff": 1 if admin_eingriff else 0,
        "old_value": _dump(old),
        "new_value": _dump(new),
        "ip": ip or "",
        "prev_hash": last["hash"],
    }
    entry["hash"] = compute_hash(entry)
    insert_raw(conn, entry)
    return entry


def insert_raw(conn, entry: dict) -> None:
    cols = HASH_FIELDS + ("hash",)
    conn.execute(
        f"INSERT INTO audit_log ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [entry[c] for c in cols],
    )


def verify_chain(conn) -> dict:
    """Rechnet die komplette Kette nach. Liefert den ersten Fehler oder OK."""
    prev = GENESIS
    expected_seq = 1
    count = 0
    for r in conn.execute("SELECT * FROM audit_log ORDER BY seq"):
        e = dict(r)
        if e["seq"] != expected_seq:
            return _fail(count, expected_seq, f"Lücke in der Kette: Eintrag {expected_seq} fehlt.")
        if e["prev_hash"] != prev:
            return _fail(count, e["seq"], "Verkettung gebrochen (Vorgänger-Hash passt nicht).")
        if compute_hash(e) != e["hash"]:
            return _fail(count, e["seq"], "Inhalt verändert (Hash stimmt nicht).")
        prev = e["hash"]
        expected_seq += 1
        count += 1
    return {"ok": True, "count": count, "head_seq": expected_seq - 1, "head_hash": prev,
            "error_seq": None, "message": f"Hash-Kette in Ordnung ({count} Einträge)."}


def _fail(count, seq, message) -> dict:
    return {"ok": False, "count": count, "head_seq": None, "head_hash": None,
            "error_seq": seq, "message": f"Eintrag {seq}: {message}"}


def verify_stock(conn) -> dict:
    """Prüft, ob jede Bestandsposition exakt der Summe ihrer Buchungen entspricht."""
    bad = conn.execute(
        """SELECT l.id, l.qty,
                  COALESCE(SUM(CASE m.type WHEN 'IN' THEN m.qty ELSE -m.qty END), 0) AS soll
           FROM lots l LEFT JOIN movements m ON m.lot_id = l.id
           GROUP BY l.id HAVING l.qty <> soll"""
    ).fetchall()
    if bad:
        ids = ", ".join(str(b["id"]) for b in bad)
        return {"ok": False, "message": f"Bestand weicht von Buchungen ab (Positionen: {ids})."}
    # Jede Buchung muss im Protokoll stehen
    missing = conn.execute(
        """SELECT COUNT(*) FROM movements m WHERE NOT EXISTS (
               SELECT 1 FROM audit_log a WHERE a.object_type = 'BUCHUNG'
               AND a.object_id = CAST(m.id AS TEXT))"""
    ).fetchone()[0]
    if missing:
        return {"ok": False, "message": f"{missing} Buchung(en) ohne Protokolleintrag."}
    return {"ok": True, "message": "Bestände stimmen mit den Buchungen überein."}


def check_receipt(conn, seq: int, hash_: str) -> dict:
    """Prüft, ob das aktuelle Protokoll eine früher ausgestellte Quittung unverändert fortsetzt."""
    chain = verify_chain(conn)
    if not chain["ok"]:
        return {"ok": False, "message": "Kette fehlerhaft – " + chain["message"]}
    r = conn.execute("SELECT hash FROM audit_log WHERE seq = ?", (seq,)).fetchone()
    if not r:
        return {"ok": False, "message": f"Eintrag {seq} der Quittung existiert nicht mehr."}
    if r["hash"] != hash_:
        return {"ok": False, "message": f"Eintrag {seq} wurde seit der Quittung verändert."}
    return {"ok": True, "message": f"Quittung bestätigt: Protokoll bis Eintrag {seq} unverändert, "
                                   f"aktuell {chain['head_seq']} Einträge."}
