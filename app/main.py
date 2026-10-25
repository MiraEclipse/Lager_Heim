"""FastAPI-Anwendung: HTTP-Schicht, Sitzungen, CSRF, Sicherheits-Header."""
import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import audit, backup, booking, meta, perms, security, users
from .config import VERSION, Config
from .db import connect, init_db, now_iso, one, rows, write_tx
from .errors import AppError, NotFound
from .seed import seed

STATIC = Path(__file__).with_name("static")
COOKIE = "lh_sitzung"
CSRF_HEADER = "x-csrf-token"
# Erlaubt, solange ein Passwortwechsel aussteht
PW_CHANGE_PATHS = {"/api/me", "/api/passwort", "/api/logout", "/api/config"}

CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")

log = logging.getLogger("lager")


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config()
    cfg.ensure_dirs()
    init_db(cfg.db_path)
    c = connect(cfg.db_path)
    try:
        seed(c)
    finally:
        c.close()
    stop = threading.Event()

    @asynccontextmanager
    async def lifespan(app):
        if cfg.backup_auto:
            backup.start_scheduler(cfg, stop)
        yield
        stop.set()

    app = FastAPI(title="Lager Heim", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.cfg = cfg

    # ------------------------------------------------------------ Querschnitt
    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        body = {"detail": exc.message}
        if isinstance(exc, booking.NeedsConfirm):
            body["warnings"] = exc.warnings
        return JSONResponse(body, status_code=exc.status)

    def get_conn():
        conn = connect(cfg.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def ip_of(request: Request) -> str:
        return request.client.host if request.client else ""

    def current(request: Request, conn=Depends(get_conn)) -> dict:
        token = request.cookies.get(COOKIE)
        if not token:
            raise AppError("Nicht angemeldet.", 401)
        s = one(conn.execute(
            "SELECT s.*, u.username, u.role, u.active, u.must_change_pw FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?", (security.token_hash(token),)))
        if not s or not s["active"]:
            raise AppError("Nicht angemeldet.", 401)
        user = {"id": s["user_id"], "username": s["username"], "role": s["role"],
                "must_change_pw": bool(s["must_change_pw"]), "token": token, "csrf": s["csrf_token"]}
        timeout = meta.setting_int(conn, "session_timeout_min", 15)
        if security.session_expired(s["last_seen"], timeout):
            users.logout(conn, user, token, ip_of(request), "SITZUNG_ABGELAUFEN")
            raise AppError("Sitzung wegen Inaktivität abgelaufen. Bitte neu anmelden.", 401)
        if request.method not in ("GET", "HEAD"):
            sent = request.headers.get(CSRF_HEADER, "")
            if not sent or not security.tokens_equal(sent, s["csrf_token"]):
                raise AppError("Sicherheitsprüfung (CSRF) fehlgeschlagen. Bitte Seite neu laden.", 403)
        if user["must_change_pw"] and request.url.path not in PW_CHANGE_PATHS:
            raise AppError("Bitte zuerst das Passwort ändern (T-Code ZU02).", 403)
        # Leseanfragen im Hintergrund (Statusleiste) verlängern die Sitzung nicht
        if request.headers.get("x-lh-hintergrund") != "1":
            with write_tx(conn):
                conn.execute("UPDATE sessions SET last_seen = ? WHERE token_hash = ?",
                             (now_iso(), security.token_hash(token)))
        return user

    # ------------------------------------------------------------ Ersteinrichtung (PC-Version)
    def setup_needed(conn) -> bool:
        return cfg.setup_allowed and not one(conn.execute("SELECT 1 FROM users WHERE role = 'ADMIN'"))

    @app.get("/api/setup")
    def setup_status(conn=Depends(get_conn)):
        return {"needed": setup_needed(conn)}

    @app.post("/api/setup")
    def setup(request: Request, data: dict = Body(...), conn=Depends(get_conn)):
        if not setup_needed(conn):
            raise AppError("Ersteinrichtung ist nicht verfügbar.", 403)
        users.create_user(conn, None, str(data.get("username", "")), str(data.get("password", "")),
                          ip_of(request), role=perms.ADMIN)
        return {"ok": True, "message": "Admin angelegt. Bitte anmelden."}

    # ------------------------------------------------------------ Anmeldung
    @app.post("/api/login")
    def login(request: Request, data: dict = Body(...), conn=Depends(get_conn)):
        user, token, csrf = users.login(conn, cfg, str(data.get("username", "")), str(data.get("password", "")),
                                        ip_of(request))
        resp = JSONResponse({"user": users.public(user), "csrf": csrf})
        resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/",
                        secure=request.url.scheme == "https")
        return resp

    @app.post("/api/logout")
    def logout(request: Request, user=Depends(current), conn=Depends(get_conn)):
        users.logout(conn, user, user["token"], ip_of(request))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/api/me")
    def me(user=Depends(current), conn=Depends(get_conn)):
        days = meta.setting_int(conn, "mhd_warn_tage", 7)
        return {"user": {k: user[k] for k in ("id", "username", "role", "must_change_pw")},
                "csrf": user["csrf"], "head": audit.head(conn),
                "timeout_min": meta.setting_int(conn, "session_timeout_min", 15),
                "ablaufend": booking.expiring_count(conn, user, days), "ablauf_tage": days, "version": VERSION}

    @app.post("/api/passwort")
    def change_pw(request: Request, data: dict = Body(...), user=Depends(current), conn=Depends(get_conn)):
        users.change_own_password(conn, user, str(data.get("alt", "")), str(data.get("neu", "")), ip_of(request))
        return {"ok": True, "message": "Passwort geändert."}

    @app.get("/api/config")
    def config(user=Depends(current), conn=Depends(get_conn)):
        return meta.client_config(conn, user)

    # ------------------------------------------------------------ Bestand
    @app.get("/api/artikel/{ean}")
    def get_article(ean: str, user=Depends(current), conn=Depends(get_conn)):
        a = booking.article(conn, ean)
        if not a:
            raise NotFound("Artikel unbekannt – bitte Bezeichnung und Kategorie erfassen.")
        return {"ean": a["ean"], "bezeichnung": a["name"], "kategorie_id": a["category_id"],
                "kategorie": a["kategorie"], "custom": a["custom"]}

    @app.put("/api/artikel/{ean}")
    def put_article(ean: str, request: Request, data: dict = Body(...), user=Depends(current),
                    conn=Depends(get_conn)):
        booking.update_article(conn, user, ean, data, ip_of(request))
        return {"ok": True, "message": "Artikel gespeichert."}

    @app.get("/api/daten/{source}")
    def data_list(source: str, request: Request, user=Depends(current), conn=Depends(get_conn)):
        params = dict(request.query_params)
        fn = {"lots": booking.list_lots, "movements": booking.list_movements,
              "articles": booking.list_articles}.get(source)
        if not fn:
            raise NotFound()
        return fn(conn, user, params)

    @app.get("/api/positionen")
    def positions(bestand: str, ean: str, user=Depends(current), conn=Depends(get_conn)):
        return booking.lots_for_checkout(conn, user, bestand, ean)

    @app.post("/api/buchung/einchecken")
    def checkin(request: Request, data: dict = Body(...), user=Depends(current), conn=Depends(get_conn)):
        r = booking.checkin(conn, user, data, ip_of(request))
        r["message"] = f"Zugang gebucht, Beleg {r['beleg']}, neuer Bestand {r['menge_danach']}."
        return r

    @app.post("/api/buchung/auschecken")
    def checkout(request: Request, data: dict = Body(...), user=Depends(current), conn=Depends(get_conn)):
        r = booking.checkout(conn, user, data, ip_of(request))
        r["message"] = f"Abgang gebucht, Beleg {r['beleg']}, Restbestand {r['menge_danach']}."
        return r

    # ------------------------------------------------------------ Protokoll
    @app.get("/api/protokoll")
    def log_list(request: Request, user=Depends(current), conn=Depends(get_conn)):
        perms.require(conn, user, perms.PROTOKOLL_LESEN)
        p = request.query_params
        where, args = ["1=1"], []
        if p.get("aktion"):
            where.append("action LIKE ?")
            args.append("%" + p["aktion"].upper() + "%")
        if p.get("benutzer"):
            where.append("username LIKE ?")
            args.append("%" + p["benutzer"] + "%")
        if p.get("bestand"):
            where.append("store_code = ?")
            args.append(p["bestand"])
        if p.get("objekt"):
            where.append("(object_id LIKE ? OR old_value LIKE ? OR new_value LIKE ?)")
            args += ["%" + p["objekt"] + "%"] * 3
        if p.get("von"):
            where.append("ts >= ?")
            args.append(p["von"])
        if p.get("bis"):
            where.append("ts < date(?, '+1 day')")
            args.append(p["bis"])
        if p.get("nur_admin") == "1":
            where.append("admin_eingriff = 1")
        limit = min(max(int(p.get("limit", 1000) or 1000), 1), 5000)
        return rows(conn.execute(f"SELECT * FROM audit_log WHERE {' AND '.join(where)} ORDER BY seq DESC "
                                 f"LIMIT ?", [*args, limit]))

    @app.get("/api/protokoll/pruefen")
    def log_verify(user=Depends(current), conn=Depends(get_conn)):
        perms.require(conn, user, perms.PROTOKOLL_LESEN)
        return {"kette": audit.verify_chain(conn), "bestand": audit.verify_stock(conn), "geprueft_am": now_iso()}

    @app.get("/api/protokoll/quittung")
    def receipt(user=Depends(current), conn=Depends(get_conn)):
        perms.require(conn, user, perms.PROTOKOLL_LESEN)
        h = audit.head(conn)
        body = {"art": "Lager-Heim-Protokollquittung", "seq": h["seq"], "hash": h["hash"],
                "eintrag_zeitpunkt": h["ts"], "ausgestellt_am": now_iso(), "ausgestellt_fuer": user["username"]}
        name = f"quittung-{h['seq']}.json"
        return Response(json.dumps(body, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    @app.post("/api/protokoll/quittung")
    def receipt_check(data: dict = Body(...), user=Depends(current), conn=Depends(get_conn)):
        perms.require(conn, user, perms.PROTOKOLL_LESEN)
        try:
            seq, h = int(data.get("seq")), str(data.get("hash", ""))
        except (TypeError, ValueError):
            raise AppError("Quittung unvollständig (seq und hash erforderlich).")
        return audit.check_receipt(conn, seq, h)

    @app.get("/api/protokoll/export")
    def log_export(user=Depends(current), conn=Depends(get_conn)):
        perms.require(conn, user, perms.PROTOKOLL_LESEN)
        data = rows(conn.execute("SELECT * FROM audit_log ORDER BY seq"))
        name = f"protokoll-{len(data)}.json"
        return Response(json.dumps(data, ensure_ascii=False, indent=1), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ------------------------------------------------------------ Benutzer
    @app.get("/api/benutzer")
    def user_list(user=Depends(current), conn=Depends(get_conn)):
        return users.list_users(conn, user)

    @app.post("/api/benutzer")
    def user_create(request: Request, data: dict = Body(...), user=Depends(current), conn=Depends(get_conn)):
        return users.create_user(conn, user, str(data.get("username", "")), str(data.get("password", "")),
                                 ip_of(request))

    @app.put("/api/benutzer/{user_id}")
    def user_update(user_id: int, request: Request, data: dict = Body(...), user=Depends(current),
                    conn=Depends(get_conn)):
        return users.update_user(conn, user, user_id, data, ip_of(request))

    # ------------------------------------------------------------ Customizing
    @app.get("/api/customizing/{table}")
    def cust_list(table: str, user=Depends(current), conn=Depends(get_conn)):
        perms.require(conn, user, perms.CUSTOMIZING)
        if table not in meta.PK:
            raise NotFound()
        return meta.table_rows(conn, table)

    @app.post("/api/customizing/{table}")
    def cust_create(table: str, request: Request, data: dict = Body(...), user=Depends(current),
                    conn=Depends(get_conn)):
        return meta.save(conn, user, table, data, ip_of(request))

    @app.put("/api/customizing/{table}/{pk}")
    def cust_update(table: str, pk: str, request: Request, data: dict = Body(...), user=Depends(current),
                    conn=Depends(get_conn)):
        return meta.save(conn, user, table, data, ip_of(request), pk=_pk(table, pk))

    @app.delete("/api/customizing/{table}/{pk}")
    def cust_delete(table: str, pk: str, request: Request, user=Depends(current), conn=Depends(get_conn)):
        meta.delete(conn, user, table, _pk(table, pk), ip_of(request))
        return {"ok": True}

    def _pk(table, pk):
        if meta.PK.get(table) == "id":
            try:
                return int(pk)
            except ValueError:
                raise NotFound()
        return pk

    @app.get("/api/rechte")
    def rights(user=Depends(current), conn=Depends(get_conn)):
        perms.require(conn, user, perms.CUSTOMIZING)
        return {"matrix": [{"store": s, "function": f, "label": perms.FUNCTIONS[f][0],
                            "allowed": perms.can(conn, {"role": perms.USER}, f, None if s == "*" else s)}
                           for s, f in perms.CONFIGURABLE],
                "privat_lesbar": meta.get_setting(conn, "privat_lesbar") == "1"}

    @app.put("/api/rechte")
    def rights_set(request: Request, data: dict = Body(...), user=Depends(current), conn=Depends(get_conn)):
        meta.set_permission(conn, user, str(data.get("store")), str(data.get("function")),
                            bool(data.get("allowed")), ip_of(request))
        return {"ok": True, "message": "Recht gespeichert."}

    @app.put("/api/einstellungen")
    def settings_set(request: Request, data: dict = Body(...), user=Depends(current), conn=Depends(get_conn)):
        meta.set_setting(conn, user, str(data.get("key")), data.get("value"), ip_of(request))
        return {"ok": True, "message": "Einstellung gespeichert."}

    @app.get("/api/versionen")
    def version_list(user=Depends(current), conn=Depends(get_conn)):
        perms.require(conn, user, perms.CUSTOMIZING)
        return meta.versions(conn)

    @app.post("/api/versionen/{vid}/ruecksetzen")
    def version_rollback(vid: int, request: Request, user=Depends(current), conn=Depends(get_conn)):
        perms.require(conn, user, perms.CUSTOMIZING)
        new_id = meta.rollback(conn, user, vid, ip_of(request))
        return {"ok": True, "message": f"Konfiguration auf Version {vid} zurückgesetzt (neue Version {new_id})."}

    # ------------------------------------------------------------ Backup
    @app.get("/api/backup")
    def backup_list(user=Depends(current), conn=Depends(get_conn)):
        return backup.list_backups(cfg, conn, user)

    @app.post("/api/backup")
    def backup_create(request: Request, user=Depends(current), conn=Depends(get_conn)):
        info = backup.create_backup(cfg, conn, user, "manuell", ip_of(request))
        return {**info, "message": f"Backup {info['name']} erstellt."}

    @app.get("/api/backup/{name}")
    def backup_download(name: str, request: Request, user=Depends(current), conn=Depends(get_conn)):
        perms.require(conn, user, perms.BACKUP)
        path = backup.resolve(cfg, name)
        with write_tx(conn):
            audit.append(conn, user, "BACKUP_HERUNTERGELADEN", "BACKUP", name, ip=ip_of(request))
        return FileResponse(path, filename=name, media_type="application/octet-stream")

    @app.post("/api/backup/{name}/wiederherstellen")
    def backup_restore(name: str, request: Request, data: dict = Body(...), user=Depends(current),
                       conn=Depends(get_conn)):
        if data.get("bestaetigung") != "WIEDERHERSTELLEN":
            raise AppError("Bitte zur Bestätigung WIEDERHERSTELLEN eingeben.")
        return backup.restore(cfg, conn, user, name, ip_of(request))

    # ------------------------------------------------------------ Oberfläche
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")

    return app
