# Lager Heim

Selbst gehostete Bestandsverwaltung für Süßigkeiten im Haushalt. Die Anwendung dokumentiert lückenlos
und nachvollziehbar, welche Artikel im **Keller** (gemeinsamer Haushaltsbestand) liegen und welche zu
**Mein Bestand** (persönlicher Bestand des Admins) gehören.

- Ein- und Auschecken je Bestand, getrennte Positionen je EAN, MHD und Charge
- Unveränderliches Protokoll mit SHA-256-Hash-Kette, Prüffunktion und Protokoll-Quittung
- Customizing ohne Programmieren: Felder, Kategorien, Seiten/Masken, Menüs, T-Codes, Regeln, Rechte – versioniert
- Klassische Desktop-Optik mit Menüleiste, Symbolleiste, Befehlsfeld (z. B. `ZE01`) und Statusleiste
- Läuft auf dem Raspberry Pi (ARM64), SQLite, HTTPS, keine externen Abhängigkeiten zur Laufzeit

## PC-App für Windows (ohne Docker, ohne Python)

1. Auf GitHub im Repository **Actions → CI** den neuesten erfolgreichen Lauf öffnen und unten unter
   *Artifacts* **LagerHeim-Windows** herunterladen (ZIP mit `LagerHeim.exe`).
2. ZIP entpacken und `LagerHeim.exe` doppelklicken. Beim ersten Start warnt Windows SmartScreen, weil das
   Programm nicht signiert ist: **Weitere Informationen → Trotzdem ausführen**.
3. Beim ersten Start das Admin-Konto anlegen (Ersteinrichtung), danach anmelden.

Die App öffnet ein eigenes Fenster (Microsoft Edge WebView2, bei Windows 10/11 vorinstalliert) und ist
nur auf diesem PC erreichbar (127.0.0.1). Beim Schließen des Fensters wird sie beendet.
Daten, Backups und Logdatei liegen unter `%LOCALAPPDATA%\LagerHeim`.

Selbst bauen (unter Windows):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-pc.txt
pyinstaller --noconfirm --clean LagerHeim.spec    # Ergebnis: dist\LagerHeim.exe
```

## Lokal auf dem PC testen (Server-Variante)

### Variante A: mit Docker Desktop (Windows/macOS/Linux)

```bash
git clone <repo-url> lager_heim
cd lager_heim
mkdir data
docker compose up -d --build
docker compose exec lager python -m app.cli admin-anlegen
# optional Beispieldaten (Benutzer "test", Passwort "test1234"):
docker compose exec lager python -m app.cli demo-daten
```

Danach im Browser **https://localhost:8443** öffnen. Die Zertifikatswarnung (selbstsigniertes
Zertifikat) einmalig bestätigen.

### Variante B: ohne Docker, direkt mit Python 3.12+

Linux/macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m app.cli admin-anlegen
python -m app.cli demo-daten        # optional
python -m app.cli serve             # https://localhost:8443
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.cli admin-anlegen
python -m app.cli serve
```

Die Daten liegen im Ordner `data/` (Datenbank, Backups, Zertifikat). Zum Zurücksetzen des Testsystems
den Server beenden und `data/` löschen.

### Tests ausführen

```bash
pip install -r requirements-dev.txt
pytest
```

## Dokumentation

- [Installation auf dem Raspberry Pi](docs/INSTALLATION.md)
- [Admin-Handbuch](docs/ADMIN-HANDBUCH.md)
- [Architektur und Datenmodell](docs/ARCHITEKTUR.md)
