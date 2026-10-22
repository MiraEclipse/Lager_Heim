"""Rechte: Keller, Mein Bestand, Admin-Funktionen, Admin-Eingriffe."""
import json

from conftest import EAN_A, checkin


def test_user_can_book_in_keller(user):
    r = checkin(user, "KELLER")
    assert r.status_code == 200, r.text
    lot = r.json()["position"]
    r = user.post("/api/buchung/auschecken", {"position": lot, "menge": 2})
    assert r.status_code == 200, r.text
    assert r.json()["menge_danach"] == 3


def test_user_cannot_write_privat(user, admin):
    assert checkin(user, "PRIVAT").status_code == 403
    lot = checkin(admin, "PRIVAT").json()["position"]
    r = user.post("/api/buchung/auschecken", {"position": lot, "menge": 1})
    assert r.status_code == 403


def test_privat_write_stays_forbidden_even_if_permission_row_is_injected(user, admin, db):
    # Selbst ein manipulierter Rechteeintrag hebelt die feste Regel nicht aus
    db.execute("INSERT INTO permissions VALUES ('USER','PRIVAT','EINCHECKEN',1)")
    assert checkin(user, "PRIVAT").status_code == 403
    r = admin.put("/api/rechte", {"store": "PRIVAT", "function": "EINCHECKEN", "allowed": True})
    assert r.status_code == 400


def test_privat_read_is_configurable(user, admin):
    checkin(admin, "PRIVAT")
    assert user.get("/api/daten/lots?bestand=PRIVAT").json() == []
    assert user.get("/api/daten/lots").json() == []
    assert admin.put("/api/einstellungen", {"key": "privat_lesbar", "value": 1}).status_code == 200
    rows = user.get("/api/daten/lots?bestand=PRIVAT").json()
    assert len(rows) == 1 and rows[0]["bestand"] == "PRIVAT"
    # Lesen ja, Schreiben weiterhin nein
    assert checkin(user, "PRIVAT").status_code == 403


def test_keller_rights_configurable(user, admin):
    assert admin.put("/api/rechte", {"store": "KELLER", "function": "EINCHECKEN", "allowed": False}).status_code == 200
    assert checkin(user, "KELLER").status_code == 403
    assert admin.put("/api/rechte", {"store": "KELLER", "function": "EINCHECKEN", "allowed": True}).status_code == 200
    assert checkin(user, "KELLER").status_code == 200


def test_admin_only_functions(user):
    assert user.get("/api/benutzer").status_code == 403
    assert user.post("/api/benutzer", {"username": "neu", "password": "abcdefgh1"}).status_code == 403
    assert user.get("/api/customizing/meta_field").status_code == 403
    assert user.post("/api/customizing/categories", {"name": "X"}).status_code == 403
    assert user.put("/api/rechte", {"store": "KELLER", "function": "EINCHECKEN", "allowed": True}).status_code == 403
    assert user.put("/api/einstellungen", {"key": "privat_lesbar", "value": 1}).status_code == 403
    assert user.get("/api/backup").status_code == 403
    assert user.post("/api/backup").status_code == 403
    assert user.put(f"/api/artikel/{EAN_A}", {"bezeichnung": "x"}).status_code in (403, 404)


def test_everyone_reads_log(user):
    assert user.get("/api/protokoll").status_code == 200
    assert user.get("/api/protokoll/pruefen").json()["kette"]["ok"]


def test_admin_booking_in_keller_is_flagged_and_needs_reason(admin, db):
    r = checkin(admin, "KELLER")
    assert r.status_code == 400 and "Begründung" in r.json()["detail"]
    r = checkin(admin, "KELLER", begruendung="Inventurkorrektur")
    assert r.status_code == 200 and r.json()["admin_eingriff"] is True
    e = dict(db.execute("SELECT * FROM audit_log WHERE action='EINCHECKEN' ORDER BY seq DESC").fetchone())
    assert e["admin_eingriff"] == 1 and e["store_code"] == "KELLER"
    assert json.loads(e["new_value"])["begruendung"] == "Inventurkorrektur"


def test_admin_booking_in_privat_is_not_an_intervention(admin):
    r = checkin(admin, "PRIVAT")
    assert r.status_code == 200 and r.json()["admin_eingriff"] is False


def test_only_one_admin_and_ui_creates_only_users(admin, db):
    r = admin.post("/api/benutzer", {"username": "benutzer2", "password": "geheim-123", "role": "ADMIN"})
    assert r.status_code == 200 and r.json()["role"] == "USER"
    assert db.execute("SELECT COUNT(*) FROM users WHERE role='ADMIN'").fetchone()[0] == 1


def test_locked_user_cannot_login_and_loses_session(app, admin, user):
    uid = [u for u in admin.get("/api/benutzer").json() if u["username"] == "benutzer1"][0]["id"]
    assert admin.put(f"/api/benutzer/{uid}", {"active": False}).status_code == 200
    assert user.get("/api/me").status_code == 401
    from conftest import USER_PW, Session
    assert Session(app).login("benutzer1", USER_PW).status_code == 401


def test_csrf_required(user):
    user.csrf = "falsch"
    assert checkin(user).status_code == 403
    user.csrf = None
    assert checkin(user).status_code == 403


def test_unauthenticated(app):
    from conftest import Session
    s = Session(app)
    assert s.get("/api/daten/lots").status_code == 401
    assert s.get("/api/protokoll").status_code == 401


def test_bruteforce_lock(app, db):
    from conftest import USER_PW, Session
    s = Session(app)
    for _ in range(5):
        assert s.login("benutzer1", "falsch").status_code == 401
    r = s.login("benutzer1", USER_PW)
    assert r.status_code == 429
    actions = [r[0] for r in db.execute("SELECT action FROM audit_log")]
    assert actions.count("LOGIN_FEHLGESCHLAGEN") == 5 and "LOGIN_GESPERRT" in actions


def test_session_timeout(user, db):
    db.execute("UPDATE sessions SET last_seen = '2000-01-01T00:00:00.000Z'")
    r = user.get("/api/me")
    assert r.status_code == 401 and "abgelaufen" in r.json()["detail"]


def test_must_change_password(app, admin, db):
    admin.post("/api/benutzer", {"username": "neu1", "password": "start-pw-1"})
    from conftest import Session
    s = Session(app)
    assert s.login("neu1", "start-pw-1").status_code == 200
    assert s.get("/api/daten/lots").status_code == 403
    assert s.post("/api/passwort", {"alt": "start-pw-1", "neu": "eigenes-pw-1"}).status_code == 200
    assert s.get("/api/daten/lots").status_code == 200


def test_security_headers(app):
    from conftest import Session
    r = Session(app).get("/")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
