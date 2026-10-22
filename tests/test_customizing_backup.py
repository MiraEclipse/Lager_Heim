"""Customizing (Versionierung, Validierung) sowie Backup und Wiederherstellung."""
from app import audit
from conftest import checkin


def test_config_is_served(user):
    cfg = user.get("/api/config").json()
    codes = {t["code"] for t in cfg["tcodes"]}
    assert {"ZE01", "ZA01", "ZB01", "ZP01"} <= codes
    assert cfg["capabilities"]["EINCHECKEN"] == ["KELLER"]
    assert cfg["capabilities"]["CUSTOMIZING"] is False


def test_create_page_menu_tcode(admin):
    r = admin.post("/api/customizing/meta_page", {
        "code": "NUR_KELLER", "title": "Kellerbestand", "kind": "LIST",
        "config": {"source": "lots", "columns": ["ean", "bezeichnung", "menge"], "filters": ["ean"],
                   "preset": {"bestand": "KELLER", "nur_bestand": True}}})
    assert r.status_code == 200, r.text
    assert admin.post("/api/customizing/meta_tcode", {"code": "ZK01", "target": "NUR_KELLER"}).status_code == 200
    menus = admin.get("/api/customizing/meta_menu").json()
    parent = [m for m in menus if m["parent_id"] is None][0]["id"]
    r = admin.post("/api/customizing/meta_menu", {"parent_id": parent, "label": "Kellerbestand",
                                                  "target": "NUR_KELLER"})
    assert r.status_code == 200
    # Seite in Verwendung kann nicht gelöscht werden
    assert admin.delete("/api/customizing/meta_page/NUR_KELLER").status_code == 400


def test_page_validation(admin):
    bad = admin.post("/api/customizing/meta_page", {
        "code": "X1", "title": "x", "kind": "LIST",
        "config": {"source": "lots", "columns": ["gibt_es_nicht"]}})
    assert bad.status_code == 400
    bad = admin.post("/api/customizing/meta_page", {
        "code": "X2", "title": "x", "kind": "FORM", "config": {"action": "einchecken", "fields": ["ean"]}})
    assert bad.status_code == 400 and "Systemfelder" in bad.json()["detail"]
    bad = admin.post("/api/customizing/meta_field", {"entity": "buchung", "code": "DROP TABLE", "label": "x",
                                                     "type": "TEXT"})
    assert bad.status_code == 400


def test_versioning_and_rollback(admin, db):
    v0 = admin.get("/api/versionen").json()[0]["id"]
    assert admin.post("/api/customizing/categories", {"name": "Lakritz"}).status_code == 200
    assert admin.put("/api/einstellungen", {"key": "session_timeout_min", "value": 30}).status_code == 200
    names = [c["name"] for c in admin.get("/api/customizing/categories").json() if c["active"]]
    assert "Lakritz" in names
    r = admin.post(f"/api/versionen/{v0}/ruecksetzen")
    assert r.status_code == 200, r.text
    cats = {c["name"]: c["active"] for c in admin.get("/api/customizing/categories").json()}
    assert cats["Lakritz"] == 0  # deaktiviert, nicht gelöscht (Artikel könnten sie nutzen)
    assert admin.get("/api/config").json()["settings"]["session_timeout_min"] == "15"
    versions = admin.get("/api/versionen").json()
    assert versions[0]["kommentar"].startswith("Rücksetzung auf Version")
    assert "CUSTOMIZING_RUECKSETZUNG" in [r[0] for r in db.execute("SELECT action FROM audit_log")]


def test_backup_and_restore_keeps_log(admin, user, db, cfg):
    checkin(user, qty=5)
    b = admin.post("/api/backup").json()
    head_at_backup = b["head_seq"]
    checkin(user, qty=3, charge="NACH")  # nach dem Backup
    seq_before = audit.head(db)["seq"]

    r = admin.post(f"/api/backup/{b['name']}/wiederherstellen", {"bestaetigung": "WIEDERHERSTELLEN"})
    assert r.status_code == 200, r.text
    # Bestand ist auf Backup-Stand …
    charges = [x[0] for x in db.execute("SELECT charge FROM lots")]
    assert "NACH" not in charges
    # … das Protokoll aber vollständig, mit Wiederherstellungs-Eintrag am Ende
    assert audit.verify_chain(db)["ok"]
    h = audit.head(db)
    assert h["seq"] == seq_before + 1
    last = db.execute("SELECT action FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()[0]
    assert last == "WIEDERHERSTELLUNG"
    assert head_at_backup < seq_before
    # Sicherheits-Backup vor der Wiederherstellung existiert
    assert any("vor-wiederherstellung" in p.name for p in cfg.backup_dir.iterdir())


def test_restore_requires_confirmation_and_valid_name(admin):
    b = admin.post("/api/backup").json()
    assert admin.post(f"/api/backup/{b['name']}/wiederherstellen", {}).status_code == 400
    r = admin.post("/api/backup/..%2F..%2Fetc%2Fpasswd/wiederherstellen", {"bestaetigung": "WIEDERHERSTELLEN"})
    assert r.status_code in (400, 404)


def test_backup_rotation(admin, cfg, db):
    from app import backup
    cfg.backup_keep_daily, cfg.backup_keep_weekly = 2, 1
    for day in ("20260101", "20260102", "20260103", "20260110"):
        (cfg.backup_dir / f"lager-{day}-020000-auto.db").write_bytes(b"")
    backup.rotate(cfg, db)
    left = sorted(p.name for p in cfg.backup_dir.glob("*auto*"))
    assert left == ["lager-20260103-020000-auto.db", "lager-20260110-020000-auto.db"]
