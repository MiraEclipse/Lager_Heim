import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

os.environ["LAGER_BACKUP_AUTO"] = "0"

from app import perms, users  # noqa: E402
from app.config import Config  # noqa: E402
from app.db import connect  # noqa: E402
from app.main import create_app  # noqa: E402

ADMIN_PW = "admin-pass-1"
USER_PW = "user-pass-1"
EAN_A = "2000000000015"
EAN_B = "2000000000022"


def in_days(n: int) -> str:
    return (date.today() + timedelta(days=n)).isoformat()


class Session:
    """TestClient mit Anmeldung und CSRF-Header."""

    def __init__(self, app):
        self.c = TestClient(app)
        self.csrf = None

    def login(self, username, password):
        r = self.c.post("/api/login", json={"username": username, "password": password})
        if r.status_code == 200:
            self.csrf = r.json()["csrf"]
        return r

    def _h(self):
        return {"X-CSRF-Token": self.csrf} if self.csrf else {}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None):
        return self.c.post(url, json=json if json is not None else {}, headers=self._h())

    def put(self, url, json=None):
        return self.c.put(url, json=json if json is not None else {}, headers=self._h())

    def delete(self, url):
        return self.c.delete(url, headers=self._h())


@pytest.fixture
def cfg(tmp_path):
    c = Config(str(tmp_path / "daten"))
    c.backup_auto = False
    return c


@pytest.fixture
def app(cfg):
    application = create_app(cfg)
    conn = connect(cfg.db_path)
    users.create_user(conn, None, "admin", ADMIN_PW, "test", role=perms.ADMIN)
    admin = dict(conn.execute("SELECT * FROM users WHERE username='admin'").fetchone())
    users.create_user(conn, admin, "benutzer1", USER_PW, "test")
    # Passwortwechsel-Pflicht für Tests aufheben
    conn.execute("UPDATE users SET must_change_pw = 0")
    conn.close()
    return application


@pytest.fixture
def db(cfg, app):
    conn = connect(cfg.db_path)
    yield conn
    conn.close()


@pytest.fixture
def admin(app):
    s = Session(app)
    assert s.login("admin", ADMIN_PW).status_code == 200
    return s


@pytest.fixture
def user(app):
    s = Session(app)
    assert s.login("benutzer1", USER_PW).status_code == 200
    return s


def checkin(s, store="KELLER", ean=EAN_A, qty=5, mhd=None, charge="C1", **extra):
    body = {"bestand": store, "ean": ean, "bezeichnung": "Testschokolade", "kategorie_id": 1,
            "mhd": mhd or in_days(100), "charge": charge, "menge": qty}
    body.update(extra)
    return s.post("/api/buchung/einchecken", body)
