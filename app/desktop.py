"""PC-Version: startet den Server nur lokal (127.0.0.1) und öffnet ein eigenes Programmfenster.

Kein Netzwerkzugriff von anderen Geräten, kein HTTPS-Zertifikat nötig. Daten liegen unter
%LOCALAPPDATA%\\LagerHeim (Windows) bzw. ~/.local/share/LagerHeim.
"""
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

from .config import Config

log = logging.getLogger("lager.desktop")


def data_dir() -> str:
    if os.environ.get("LAGER_DATA"):
        return os.environ["LAGER_DATA"]
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return str(Path(base) / "LagerHeim")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(cfg: Config):
    import uvicorn

    from .main import create_app

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(cfg), host="127.0.0.1", port=port, log_config=None,
                                           access_log=False, server_header=False))
    thread = threading.Thread(target=server.run, name="server", daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Server konnte nicht gestartet werden.")
    return server, thread, f"http://127.0.0.1:{port}/"


def self_test(server, thread, url) -> int:
    """Prüft das gebaute Programm ohne Fenster: Server antwortet, Oberfläche wird ausgeliefert."""
    import json
    import urllib.request
    try:
        ok = json.load(urllib.request.urlopen(url + "api/setup", timeout=10)) == {"needed": True}
        ok = ok and b"app.js" in urllib.request.urlopen(url, timeout=10).read()
        ok = ok and urllib.request.urlopen(url + "static/js/app.js", timeout=10).status == 200
    except Exception:
        log.exception("Selbsttest fehlgeschlagen")
        ok = False
    log.info("Selbsttest %s", "OK" if ok else "FEHLGESCHLAGEN")
    server.should_exit = True
    thread.join(timeout=5)
    return 0 if ok else 1


def main() -> None:
    cfg = Config(data_dir())
    cfg.setup_allowed = True
    cfg.ensure_dirs()
    if sys.stdout is None or sys.stderr is None:  # Programm ohne Konsole (PyInstaller --windowed)
        logfile = open(cfg.data_dir / "lager-heim.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or logfile
        sys.stderr = sys.stderr or logfile
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    server, thread, url = start_server(cfg)
    log.info("Lager Heim läuft auf %s, Daten in %s", url, cfg.data_dir)
    if os.environ.get("LAGER_SELBSTTEST") == "1":
        sys.exit(self_test(server, thread, url))
    try:
        import webview
    except ImportError:
        webview = None

    if webview is not None:
        webview.create_window("Lager Heim", url, width=1280, height=820, min_size=(800, 560))
        webview.start()
        server.should_exit = True  # Fenster geschlossen → Server beenden
        thread.join(timeout=5)
    else:
        print(f"Lager Heim läuft auf {url} – Beenden mit Strg+C.")
        webbrowser.open(url)
        try:
            thread.join()
        except KeyboardInterrupt:
            server.should_exit = True
            thread.join(timeout=5)


if __name__ == "__main__":
    main()
