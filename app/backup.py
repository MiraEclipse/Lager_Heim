"""Backups (SQLite-Online-Backup) und Wiederherstellung.

Bei einer Wiederherstellung werden Bestands-, Benutzer- und Konfigurationsdaten auf den
Stand des Backups gesetzt. Das Protokoll bleibt vollständig erhalten: Alle Einträge nach
dem Backup-Zeitpunkt werden übernommen und ein Eintrag WIEDERHERSTELLUNG angehängt.
"""
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from . import audit, perms
from .db import WRITE_LOCK, connect, init_db, write_tx
from .errors import AppError, NotFound

log = logging.getLogger("lager.backup")
NAME_RE = re.compile(r"^lager-(\d{8})-(\d{6})-(auto|manuell|vor-wiederherstellung)(?:-\d+)?\.db$")


def _create_file(cfg, reason: str) -> Path:
    cfg.ensure_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = cfg.backup_dir / f"lager-{stamp}-{reason}.db"
    n = 1
    while target.exists():  # mehrere Backups in derselben Sekunde
        target = cfg.backup_dir / f"lager-{stamp}-{reason}-{n}.db"
        n += 1
    src, dst = connect(cfg.db_path), connect(target)
    try:
        with WRITE_LOCK:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def create_backup(cfg, conn, user: dict | None, reason: str, ip: str = "") -> dict:
    if user is not None:
        perms.require(conn, user, perms.BACKUP)
    path = _create_file(cfg, reason)
    info = describe(path)
    with write_tx(conn):
        audit.append(conn, user, "BACKUP_ERSTELLT", "BACKUP", path.name,
                     new={"datei": path.name, "protokoll_stand": info["head_seq"], "anlass": reason}, ip=ip)
    if reason == "auto":
        rotate(cfg, conn)
    return info


def describe(path: Path) -> dict:
    info = {"name": path.name, "size": path.stat().st_size, "head_seq": None, "head_hash": None}
    try:
        c = connect(path)
        try:
            h = audit.head(c)
            info["head_seq"], info["head_hash"] = h["seq"], h["hash"]
        finally:
            c.close()
    except Exception:  # beschädigte Datei – trotzdem auflisten
        pass
    m = NAME_RE.match(path.name)
    if m:
        info["ts"] = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        info["anlass"] = m.group(3)
    return info


def list_backups(cfg, conn, user: dict) -> list[dict]:
    perms.require(conn, user, perms.BACKUP)
    cfg.ensure_dirs()
    return [describe(p) for p in sorted(cfg.backup_dir.glob("lager-*.db"), reverse=True)]


def resolve(cfg, name: str) -> Path:
    if not re.match(r"^lager-[0-9a-z-]+\.db$", name or ""):
        raise AppError("Ungültiger Dateiname.")
    p = (cfg.backup_dir / name).resolve()
    if p.parent != cfg.backup_dir.resolve() or not p.is_file():
        raise NotFound("Backup nicht gefunden.")
    return p


def rotate(cfg, conn) -> None:
    """Behält die letzten N täglichen und je Woche das jüngste von M Wochen (nur automatische Backups)."""
    autos = sorted(cfg.backup_dir.glob("lager-*-auto*.db"), reverse=True)
    keep = set(autos[:cfg.backup_keep_daily])
    weeks = {}
    for p in autos:
        m = re.match(r"^lager-(\d{8})", p.name)
        if not m:
            continue
        week = datetime.strptime(m.group(1), "%Y%m%d").isocalendar()[:2]
        if week not in weeks and len(weeks) < cfg.backup_keep_weekly:
            weeks[week] = p
    keep |= set(weeks.values())
    removed = [p for p in autos if p not in keep]
    for p in removed:
        p.unlink(missing_ok=True)
    if removed:
        with write_tx(conn):
            audit.append(conn, None, "BACKUP_ROTATION", "BACKUP", "", new={"entfernt": [p.name for p in removed]})


def restore(cfg, conn, user: dict, name: str, ip: str) -> dict:
    perms.require(conn, user, perms.BACKUP)
    src = resolve(cfg, name)
    safety = _create_file(cfg, "vor-wiederherstellung")
    tmp = cfg.data_dir / "restore-tmp.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(tmp) + suffix).unlink(missing_ok=True)
    s, t = connect(src), connect(tmp)
    try:
        s.backup(t)
    finally:
        s.close()
        t.close()
    init_db(tmp)  # Schema auf aktuellen Stand bringen (Trigger etc.)
    t = connect(tmp)
    try:
        chk = audit.verify_chain(t)
        if not chk["ok"]:
            raise AppError("Protokoll im Backup ist fehlerhaft: " + chk["message"])
        b_head = audit.head(t)
        with WRITE_LOCK:
            cur = conn.execute("SELECT hash FROM audit_log WHERE seq = ?", (b_head["seq"],)).fetchone()
            if b_head["seq"] and (not cur or cur["hash"] != b_head["hash"]):
                raise AppError("Backup passt nicht zum aktuellen Protokoll – Wiederherstellung abgebrochen.")
            # Protokolleinträge nach dem Backup-Stand übernehmen (nichts geht verloren)
            later = [dict(r) for r in conn.execute("SELECT * FROM audit_log WHERE seq > ? ORDER BY seq",
                                                   (b_head["seq"],))]
            with write_tx(t):
                for e in later:
                    audit.insert_raw(t, e)
                audit.append(t, user, "WIEDERHERSTELLUNG", "BACKUP", name, old={"protokoll_stand": b_head["seq"]},
                             new={"backup": name, "sicherung_vorher": safety.name,
                                  "uebernommene_protokolleintraege": len(later)}, ip=ip)
            chk = audit.verify_chain(t)
            if not chk["ok"]:
                raise AppError("Kette nach Zusammenführung fehlerhaft: " + chk["message"])
            t.backup(conn)
    finally:
        t.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(tmp) + suffix).unlink(missing_ok=True)
    return {"ok": True, "sicherung_vorher": safety.name, "message": "Wiederherstellung abgeschlossen."}


# ---------------------------------------------------------------- Zeitsteuerung
def _today_auto_exists(cfg) -> bool:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return any(cfg.backup_dir.glob(f"lager-{today}-*-auto*.db"))


def start_scheduler(cfg, stop: threading.Event) -> threading.Thread:
    def loop():
        while not stop.wait(600):
            try:
                conn = connect(cfg.db_path)
                try:
                    r = conn.execute("SELECT value FROM settings WHERE key = 'backup_stunde'").fetchone()
                    hour = int(r["value"]) if r else 3
                    if datetime.now(timezone.utc).hour >= hour and not _today_auto_exists(cfg):
                        create_backup(cfg, conn, None, "auto")
                        log.info("Automatisches Backup erstellt")
                finally:
                    conn.close()
            except Exception:
                log.exception("Automatisches Backup fehlgeschlagen")

    th = threading.Thread(target=loop, name="backup", daemon=True)
    th.start()
    return th
