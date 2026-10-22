"""Protokoll: Vollständigkeit, Unveränderlichkeit, Hash-Kette, Quittung."""
import json
import sqlite3

import pytest

from app import audit
from conftest import checkin


def actions(db):
    return [r[0] for r in db.execute("SELECT action FROM audit_log ORDER BY seq")]


def test_every_booking_is_logged_with_old_and_new(user, db):
    lot = checkin(user, qty=4).json()["position"]
    user.post("/api/buchung/auschecken", {"position": lot, "menge": 1})
    rows = [dict(r) for r in db.execute(
        "SELECT * FROM audit_log WHERE object_type='BUCHUNG' ORDER BY seq")]
    assert [r["action"] for r in rows] == ["EINCHECKEN", "AUSCHECKEN"]
    out = rows[1]
    assert out["username"] == "benutzer1" and out["store_code"] == "KELLER" and out["ts"]
    assert json.loads(out["old_value"])["menge"] == 4
    assert json.loads(out["new_value"])["menge"] == 3
    assert "ARTIKEL_ANGELEGT" in actions(db)


def test_logins_user_admin_and_customizing_are_logged(admin, user, db):
    admin.post("/api/benutzer", {"username": "neu2", "password": "passwort-1"})
    admin.put("/api/rechte", {"store": "KELLER", "function": "AUSCHECKEN", "allowed": False})
    admin.put("/api/einstellungen", {"key": "privat_lesbar", "value": 1})
    admin.post("/api/customizing/categories", {"name": "Lakritz"})
    admin.post("/api/logout")
    a = actions(db)
    for expected in ["INSTALLATION", "LOGIN", "BENUTZER_ANGELEGT", "RECHT_GEAENDERT",
                     "CUSTOMIZING_ANGELEGT", "LOGOUT"]:
        assert expected in a, expected
    assert a.count("RECHT_GEAENDERT") == 2  # Rechtematrix + Lesbarkeit "Mein Bestand"


def test_log_cannot_be_changed_or_deleted_in_db(user, db):
    checkin(user)
    with pytest.raises(sqlite3.IntegrityError, match="unveränderlich"):
        db.execute("UPDATE audit_log SET username = 'jemand' WHERE seq = 1")
    with pytest.raises(sqlite3.IntegrityError, match="unveränderlich"):
        db.execute("DELETE FROM audit_log WHERE seq = 1")
    with pytest.raises(sqlite3.IntegrityError, match="unveränderlich"):
        db.execute("UPDATE movements SET qty = 99")
    with pytest.raises(sqlite3.IntegrityError, match="unveränderlich"):
        db.execute("DELETE FROM movements")


def test_no_api_to_modify_log(admin):
    for method in ("put", "delete"):
        r = getattr(admin.c, method)("/api/protokoll/1", headers={"X-CSRF-Token": admin.csrf})
        assert r.status_code in (404, 405)


def test_chain_valid(user, db):
    checkin(user)
    r = user.get("/api/protokoll/pruefen").json()
    assert r["kette"]["ok"] and r["bestand"]["ok"]
    assert r["kette"]["head_seq"] == db.execute("SELECT MAX(seq) FROM audit_log").fetchone()[0]


def _tamper(db, sql, args=()):
    """Simuliert einen Angreifer mit direktem Dateizugriff (Trigger entfernt)."""
    db.execute("DROP TRIGGER audit_log_no_update")
    db.execute("DROP TRIGGER audit_log_no_delete")
    db.execute(sql, args)


def test_detects_modified_entry(user, db):
    checkin(user)
    seq = db.execute("SELECT seq FROM audit_log WHERE action='EINCHECKEN'").fetchone()[0]
    _tamper(db, "UPDATE audit_log SET username = 'jemand_anders' WHERE seq = ?", (seq,))
    r = audit.verify_chain(db)
    assert not r["ok"] and r["error_seq"] == seq


def test_detects_deleted_entry(user, db):
    checkin(user)
    _tamper(db, "DELETE FROM audit_log WHERE seq = 3")
    r = audit.verify_chain(db)
    assert not r["ok"] and r["error_seq"] == 3


def test_detects_recomputed_hash_without_relinking(user, db):
    checkin(user)
    e = dict(db.execute("SELECT * FROM audit_log WHERE seq = 2").fetchone())
    e["username"] = "jemand_anders"
    new_hash = audit.compute_hash(e)
    _tamper(db, "UPDATE audit_log SET username = ?, hash = ? WHERE seq = 2", (e["username"], new_hash))
    r = audit.verify_chain(db)
    assert not r["ok"] and r["error_seq"] == 3


def test_receipt_detects_full_chain_rewrite(user, db):
    checkin(user)
    receipt = user.get("/api/protokoll/quittung").json()
    assert user.post("/api/protokoll/quittung", receipt).json()["ok"]
    checkin(user, qty=1)
    assert user.post("/api/protokoll/quittung", receipt).json()["ok"]  # Kette wächst weiter: ok

    # Angreifer schreibt Eintrag 2 um und berechnet die GESAMTE Kette neu
    rows = [dict(r) for r in db.execute("SELECT * FROM audit_log ORDER BY seq")]
    _tamper(db, "DELETE FROM audit_log")
    prev = audit.GENESIS
    for e in rows:
        if e["seq"] == 2:
            e["username"] = "jemand_anders"
        e["prev_hash"] = prev
        e["hash"] = audit.compute_hash(e)
        prev = e["hash"]
        audit.insert_raw(db, e)
    assert audit.verify_chain(db)["ok"]  # Kette in sich wieder schlüssig …
    r = user.post("/api/protokoll/quittung", receipt).json()
    assert not r["ok"]  # … aber die Quittung entlarvt die Fälschung


def test_stock_tampering_detected(user, db):
    checkin(user, qty=5)
    db.execute("UPDATE lots SET qty = 2")
    assert not audit.verify_stock(db)["ok"]


def test_export_contains_all_entries(user, db):
    checkin(user)
    data = user.get("/api/protokoll/export").json()
    assert len(data) == db.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]


def test_concurrent_bookings_keep_chain_intact(app, cfg):
    import threading

    from conftest import USER_PW, Session
    from app.db import connect
    sessions = []
    for _ in range(4):
        s = Session(app)
        s.login("benutzer1", USER_PW)
        sessions.append(s)
    errors = []

    def work(s):
        for _ in range(5):
            r = checkin(s, qty=1)
            if r.status_code != 200:
                errors.append(r.text)

    threads = [threading.Thread(target=work, args=(s,)) for s in sessions]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    conn = connect(cfg.db_path)
    assert audit.verify_chain(conn)["ok"] and audit.verify_stock(conn)["ok"]
    assert conn.execute("SELECT qty FROM lots").fetchone()[0] == 20
