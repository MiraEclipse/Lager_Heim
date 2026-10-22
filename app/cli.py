"""Kommandozeile: python -m app.cli <befehl>"""
import argparse
import getpass
import json
import os
import shutil
import sys
from datetime import datetime, timezone

from . import audit, backup, perms, security, users
from .config import Config
from .db import connect, init_db, one, write_tx
from .errors import AppError
from .seed import seed


def _open(cfg):
    cfg.ensure_dirs()
    init_db(cfg.db_path)
    conn = connect(cfg.db_path)
    seed(conn)
    return conn


def _ask_password() -> str:
    pw = getpass.getpass("Passwort: ")
    if pw != getpass.getpass("Passwort wiederholen: "):
        sys.exit("Passwörter stimmen nicht überein.")
    return pw


def cmd_serve(cfg, args):
    import uvicorn

    from .main import create_app
    from .tls import ensure_cert

    app = create_app(cfg)
    kw = {}
    if not args.http:
        cert, key = ensure_cert(cfg.tls_dir)
        kw = {"ssl_certfile": cert, "ssl_keyfile": key}
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False, server_header=False,
                log_level="info", **kw)


def cmd_admin(cfg, args):
    conn = _open(cfg)
    name = args.benutzer or input("Benutzername des Admins: ").strip()
    pw = os.environ.get("LAGER_ADMIN_PASSWORT") or _ask_password()
    try:
        users.create_user(conn, None, name, pw, "cli", role=perms.ADMIN)
    except AppError as e:
        sys.exit(e.message)
    print(f"Admin „{name}“ angelegt.")


def cmd_passwort(cfg, args):
    conn = _open(cfg)
    u = one(conn.execute("SELECT * FROM users WHERE username = ?", (args.benutzer,)))
    if not u:
        sys.exit("Benutzer nicht gefunden.")
    pw = _ask_password()
    err = security.check_password_policy(pw)
    if err:
        sys.exit(err)
    with write_tx(conn):
        conn.execute("UPDATE users SET pw_hash = ?, must_change_pw = ? WHERE id = ?",
                     (security.hash_password(pw), 0 if u["role"] == perms.ADMIN else 1, u["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (u["id"],))
        security.clear_failures(conn, [f"u:{u['username'].lower()}"])
        audit.append(conn, None, "PASSWORT_ZURUECKGESETZT", "BENUTZER", u["id"],
                     new={"benutzer": u["username"], "ueber": "Kommandozeile"}, ip="cli")
    print("Passwort gesetzt.")


def cmd_pruefen(cfg, args):
    conn = _open(cfg)
    chain, stock = audit.verify_chain(conn), audit.verify_stock(conn)
    print(("OK    " if chain["ok"] else "FEHLER") + "  " + chain["message"])
    print(("OK    " if stock["ok"] else "FEHLER") + "  " + stock["message"])
    ok = chain["ok"] and stock["ok"]
    if chain["ok"]:
        print(f"Kettenspitze: Eintrag {chain['head_seq']}  {chain['head_hash']}")
    if args.quittung:
        with open(args.quittung, encoding="utf-8") as f:
            q = json.load(f)
        r = audit.check_receipt(conn, int(q["seq"]), str(q["hash"]))
        print(("OK    " if r["ok"] else "FEHLER") + "  " + r["message"])
        ok = ok and r["ok"]
    sys.exit(0 if ok else 1)


def cmd_backup(cfg, args):
    conn = _open(cfg)
    info = backup.create_backup(cfg, conn, None, "manuell", "cli")
    print(f"Backup erstellt: {cfg.backup_dir / info['name']}")


def cmd_notfall(cfg, args):
    """Ersetzt eine beschädigte Datenbank durch ein Backup (ohne Zusammenführung des Protokolls)."""
    src = backup.resolve(cfg, args.name)
    if input(f"Datenbank durch {src.name} ersetzen? Tippe JA: ").strip() != "JA":
        sys.exit("Abgebrochen.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        p = cfg.db_path.with_name(cfg.db_path.name + suffix)
        if p.exists():
            shutil.move(p, cfg.data_dir / f"defekt-{stamp}-{p.name}")
    shutil.copy2(src, cfg.db_path)
    conn = _open(cfg)
    with write_tx(conn):
        audit.append(conn, None, "NOTFALL_WIEDERHERSTELLUNG", "BACKUP", src.name,
                     new={"backup": src.name, "alte_datenbank": f"defekt-{stamp}-lager.db"}, ip="cli")
    print("Wiederhergestellt. Alte Datenbank wurde aufbewahrt (defekt-…).")


def cmd_demo(cfg, args):
    from . import booking
    conn = _open(cfg)
    admin = one(conn.execute("SELECT * FROM users WHERE role = 'ADMIN'"))
    if not admin:
        sys.exit("Bitte zuerst den Admin anlegen.")
    if not one(conn.execute("SELECT 1 FROM users WHERE username = 'test'")):
        users.create_user(conn, admin, "test", "test1234", "cli")
        print("Benutzer test / test1234 angelegt (muss Passwort beim ersten Login ändern).")
    today = datetime.now().date()
    samples = [("2000000000015", "Schokolade Vollmilch", 1, 120, "L2401", 5, "KELLER"),
               ("2000000000022", "Fruchtgummi Bären", 2, 5, "C88", 3, "KELLER"),
               ("2000000000015", "Schokolade Vollmilch", 1, 200, "L2507", 4, "PRIVAT"),
               ("20000011", "Kaubonbons", 5, 60, "", 10, "PRIVAT")]
    from datetime import timedelta
    for ean, name, cat, days, charge, qty, store in samples:
        booking.checkin(conn, admin, {"bestand": store, "ean": ean, "bezeichnung": name, "kategorie_id": cat,
                                      "mhd": (today + timedelta(days=days)).isoformat(), "charge": charge,
                                      "menge": qty, "begruendung": "Demodaten", "trotz_warnung": True}, "cli")
    print("Demodaten gebucht.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m app.cli", description="Lager Heim – Verwaltung")
    p.add_argument("--daten", help="Datenverzeichnis (Standard: $LAGER_DATA oder ./data)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="Server starten")
    s.add_argument("--host", default=os.environ.get("LAGER_HOST", "0.0.0.0"))
    s.add_argument("--port", type=int, default=int(os.environ.get("LAGER_PORT", "8443")))
    s.add_argument("--http", action="store_true", help="ohne HTTPS (nur für Tests)")
    s.set_defaults(fn=cmd_serve)
    s = sub.add_parser("admin-anlegen", help="den (einzigen) Admin anlegen")
    s.add_argument("--benutzer")
    s.set_defaults(fn=cmd_admin)
    s = sub.add_parser("passwort-setzen", help="Passwort eines Benutzers setzen (Notfall)")
    s.add_argument("benutzer")
    s.set_defaults(fn=cmd_passwort)
    s = sub.add_parser("pruefen", help="Hash-Kette und Bestände prüfen")
    s.add_argument("--quittung", help="Quittungsdatei (JSON) gegen das Protokoll prüfen")
    s.set_defaults(fn=cmd_pruefen)
    sub.add_parser("backup", help="Backup erstellen").set_defaults(fn=cmd_backup)
    s = sub.add_parser("notfall-wiederherstellen", help="defekte Datenbank durch Backup ersetzen")
    s.add_argument("name")
    s.set_defaults(fn=cmd_notfall)
    sub.add_parser("demo-daten", help="Testbenutzer und Beispielbuchungen anlegen").set_defaults(fn=cmd_demo)
    args = p.parse_args(argv)
    args.fn(Config(args.daten), args)


if __name__ == "__main__":
    main()
