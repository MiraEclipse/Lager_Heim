"""Zentrale Konfiguration über Umgebungsvariablen."""
import os
from pathlib import Path

VERSION = "1.0.0"


class Config:
    def __init__(self, data_dir: str | None = None):
        self.data_dir = Path(data_dir or os.environ.get("LAGER_DATA", "./data")).resolve()
        self.db_path = self.data_dir / "lager.db"
        self.backup_dir = self.data_dir / "backups"
        self.tls_dir = self.data_dir / "tls"
        # Automatische Backups (Hintergrund-Thread) – in Tests abgeschaltet
        self.backup_auto = os.environ.get("LAGER_BACKUP_AUTO", "1") == "1"
        self.backup_keep_daily = int(os.environ.get("LAGER_BACKUP_TAEGLICH", "7"))
        self.backup_keep_weekly = int(os.environ.get("LAGER_BACKUP_WOECHENTLICH", "4"))
        # Brute-Force-Schutz
        self.login_max_fails = int(os.environ.get("LAGER_LOGIN_MAX_FEHLVERSUCHE", "5"))
        self.login_lock_base_s = int(os.environ.get("LAGER_LOGIN_SPERRE_SEKUNDEN", "60"))
        self.login_lock_max_s = 3600

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.backup_dir, self.tls_dir):
            d.mkdir(parents=True, exist_ok=True)
