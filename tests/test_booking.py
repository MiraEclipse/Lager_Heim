"""Buchungen: EAN-Prüfung, Positionen je MHD/Charge, Vorbelegung, Regeln, Filter."""
import pytest

from app.ean import validate
from conftest import EAN_A, EAN_B, checkin, in_days


@pytest.mark.parametrize("ean,ok", [
    ("2000000000015", True), ("20000011", True), ("4006381333931", True), ("96385074", True),
    ("2000000000016", False), ("20000012", False), ("123", False), ("abcdefgh", False),
    ("200000000001", False), ("２０００００１１", False),
])
def test_ean_validation(ean, ok):
    assert (validate(ean) is None) == ok


def test_invalid_ean_rejected(user):
    r = checkin(user, ean="2000000000016")
    assert r.status_code == 400 and "Prüfziffer" in r.json()["detail"]


def test_same_ean_mhd_charge_is_merged(user):
    a = checkin(user, qty=2, mhd=in_days(50), charge="X").json()
    b = checkin(user, qty=3, mhd=in_days(50), charge="X").json()
    assert a["position"] == b["position"] and b["menge_danach"] == 5


def test_different_mhd_or_charge_are_separate(user):
    p1 = checkin(user, mhd=in_days(50), charge="X").json()["position"]
    p2 = checkin(user, mhd=in_days(60), charge="X").json()["position"]
    p3 = checkin(user, mhd=in_days(50), charge="Y").json()["position"]
    assert len({p1, p2, p3}) == 3
    lots = user.get(f"/api/positionen?bestand=KELLER&ean={EAN_A}").json()
    assert len(lots) == 3


def test_same_article_in_both_stores_separate(admin):
    p1 = checkin(admin, "KELLER", begruendung="x").json()["position"]
    p2 = checkin(admin, "PRIVAT").json()["position"]
    assert p1 != p2


def test_known_ean_prefill_and_master_data_kept(user):
    assert user.get(f"/api/artikel/{EAN_A}").status_code == 404
    checkin(user)
    a = user.get(f"/api/artikel/{EAN_A}").json()
    assert a["bezeichnung"] == "Testschokolade" and a["kategorie_id"] == 1
    # Bei bekannter EAN wird der Stamm nicht überschrieben
    checkin(user, bezeichnung="Anderer Name")
    assert user.get(f"/api/artikel/{EAN_A}").json()["bezeichnung"] == "Testschokolade"


def test_new_article_requires_name(user):
    r = user.post("/api/buchung/einchecken", {"bestand": "KELLER", "ean": EAN_B, "mhd": in_days(30),
                                              "menge": 1})
    assert r.status_code == 400 and "Bezeichnung" in r.json()["detail"]


def test_checkout_more_than_stock(user):
    lot = checkin(user, qty=2).json()["position"]
    r = user.post("/api/buchung/auschecken", {"position": lot, "menge": 3})
    assert r.status_code == 400 and "Nicht genug" in r.json()["detail"]


def test_invalid_quantity_and_date(user):
    assert checkin(user, qty=0).status_code == 400
    assert checkin(user, qty="abc").status_code == 400
    assert checkin(user, mhd="31.12.2030").status_code == 400


def test_expiry_warning_needs_confirmation(user):
    r = checkin(user, mhd=in_days(3))
    assert r.status_code == 409 and r.json()["warnings"]
    assert user.get("/api/daten/lots").json() == []  # nichts gebucht
    r = checkin(user, mhd=in_days(3), trotz_warnung=True)
    assert r.status_code == 200


def test_block_rule(admin, user):
    r = admin.post("/api/customizing/meta_rule", {
        "name": "Keine Großmengen", "trigger": "BUCHUNG",
        "conditions": [{"field": "menge", "op": "gt", "value": 50}],
        "action": {"type": "BLOCK", "message": "Mehr als 50 Stück"}})
    assert r.status_code == 200, r.text
    r = checkin(user, qty=51, trotz_warnung=True)
    assert r.status_code == 409 and "verhindert" in r.json()["detail"]


def test_display_rule_highlights_expiring(user):
    checkin(user, mhd=in_days(2), trotz_warnung=True)
    checkin(user, mhd=in_days(90), charge="Z")
    rows = user.get("/api/daten/lots").json()
    flagged = [r for r in rows if r["_hinweise"]]
    assert len(flagged) == 1 and flagged[0]["mhd"] == in_days(2)
    assert len(user.get("/api/daten/lots?ablauf_tage=7").json()) == 1
    assert user.get("/api/me").json()["ablaufend"] == 1


def test_filters(user):
    checkin(user, ean=EAN_A, charge="AB1", mhd=in_days(30))
    checkin(user, ean=EAN_B, charge="CD2", mhd=in_days(60), bezeichnung="Gummi", kategorie_id=2)
    get = lambda q: user.get("/api/daten/lots?" + q).json()  # noqa: E731
    assert len(get(f"ean={EAN_B}")) == 1
    assert len(get("charge=AB")) == 1
    assert len(get("kategorie=Fruchtgummi")) == 1
    assert len(get(f"mhd_bis={in_days(40)}")) == 1
    assert len(get("bestand=KELLER")) == 2
    assert len(user.get("/api/daten/movements?typ=IN").json()) == 2


def test_custom_field_validation(admin, user):
    r = admin.post("/api/customizing/meta_field", {"entity": "buchung", "code": "zustand", "label": "Zustand",
                                                   "type": "SELECT", "options": "gut;beschädigt",
                                                   "required": True})
    assert r.status_code == 200, r.text
    assert checkin(user).status_code == 400  # Pflichtfeld fehlt
    assert checkin(user, custom_buchung={"zustand": "kaputt"}).status_code == 400
    assert checkin(user, custom_buchung={"zustand": "gut", "unbekannt": 1}).status_code == 400
    r = checkin(user, custom_buchung={"zustand": "gut"})
    assert r.status_code == 200
    mv = user.get("/api/daten/movements").json()[0]
    assert mv["zustand"] == "gut"


def test_sql_injection_in_filters_is_harmless(user):
    checkin(user)
    rows = user.get("/api/daten/lots?ean=' OR 1=1 --&charge=%'; DROP TABLE lots; --").json()
    assert rows == []
    assert len(user.get("/api/daten/lots").json()) == 1
