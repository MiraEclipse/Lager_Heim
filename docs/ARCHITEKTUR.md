# Architektur und Datenmodell

## Technologie

| Schicht | Wahl | Begründung |
|---|---|---|
| Backend | Python 3.12+, FastAPI, Uvicorn | ressourcenschonend (ca. 60–90 MB RAM), ARM64-tauglich, gut wartbar |
| Datenbank | SQLite (WAL), reines SQL mit Parametern | kein DB-Server, einfache Backups, Trigger für append-only |
| Frontend | Plain JavaScript (ES-Module), eigenes CSS | kein Build, kein CDN; Oberfläche wird zur Laufzeit aus Metadaten aufgebaut |
| Sicherheit | Argon2id, DB-Sitzungen, CSRF-Token, CSP, HTTPS (selbstsigniert) | siehe unten |
| Betrieb | Docker Compose, ein Container, Volume `/data` | einfache Installation und Updates |

PHP wurde wegen der kritischen, aktiv ausgenutzten Lücken „PHP2Shell“ (CVE-2026-109618/-109619, Oktober 2026)
bewusst nicht verwendet.

## Module (`app/`)

| Datei | Aufgabe |
|---|---|
| `main.py` | HTTP-API, Sitzungsprüfung, CSRF, Sicherheits-Header |
| `perms.py` | Rechteprüfung: feste Regeln im Code, danach konfigurierbare Rechte |
| `booking.py` | Ein-/Auschecken, Positionen, Abfragen |
| `audit.py` | Protokoll mit Hash-Kette, Prüfung, Quittung |
| `meta.py` | Customizing, Validierung, Versionierung/Rücksetzung |
| `rules.py` | Regel-Engine (Bedingungen als Daten, keine Codeausführung) |
| `users.py`, `security.py` | Login, Brute-Force-Schutz, Benutzerverwaltung, Passwörter |
| `backup.py` | Online-Backup, Rotation, Wiederherstellung mit Erhalt des Protokolls |
| `seed.py` | Erstbefüllung (Menüs, T-Codes, Seiten, Regeln, Kategorien) |
| `cli.py` | Kommandozeile (Server, Admin anlegen, Prüfen, Backup, Notfall) |

## Datenmodell

**Benutzer und Bestände**: `roles`, `users`, `sessions` (nur SHA-256 des Tokens), `login_attempts`, `stores`
(KELLER, PRIVAT), `settings`.

**Artikel und Buchungen**
- `articles`: Stammdaten je EAN (Bezeichnung, Kategorie, eigene Artikelfelder als JSON).
- `lots`: Bestandsposition, eindeutig je (Bestand, EAN, MHD, Charge).
- `movements`: jede Buchung (Zugang/Abgang, Menge, Bestand danach, Admin-Eingriff, Begründung, eigene
  Buchungsfelder). Per Trigger unveränderlich. Jeder Bestand lässt sich aus den Buchungen nachrechnen.

**Metadaten**
- `meta_field`: eigene Felder (Typ, Pflicht, Auswahlwerte, Vorschlagswert, aktiv).
- `meta_page`: Seiten. LIST mit Datenquelle, Spalten, Filtern, Sortierung, Vorbelegung, Zeilenaktion;
  FORM mit Aktion und Feldreihenfolge; SYSTEM für eingebaute Seiten.
- `meta_menu`, `meta_tcode`: Menüleiste und Transaktionscodes.
- `meta_rule`: Auslöser, Bedingungen (JSON), Aktion (WARN/BLOCK/HIGHLIGHT).
- `permissions`: konfigurierbare Rechte je Rolle, Bestand und Funktion.
- `config_version`: vollständiger Snapshot aller Customizing-Tabellen mit Prüfsumme je Änderung.

**Protokoll** `audit_log`: `seq, ts, user_id, username, action, object_type, object_id, store_code,
admin_eingriff, old_value, new_value, ip, prev_hash, hash`

- `hash = SHA-256(kanonisches JSON aller Felder inkl. prev_hash)`, Genesis-`prev_hash` = 64 Nullen.
- Buchung und Protokolleintrag entstehen in derselben Transaktion (`BEGIN IMMEDIATE`).
- Trigger verhindern `UPDATE` und `DELETE`. Es gibt keine API dafür.
- Quittungen (Nummer und Hash) machen auch eine komplett neu berechnete Kette erkennbar.

## Sicherheit

- Passwörter mit Argon2id. Gleiche Laufzeit bei unbekanntem Benutzer.
- Brute-Force-Schutz je Benutzer und IP mit exponentieller Sperre. Jeder Fehlversuch wird protokolliert.
- Sitzungs-Cookie `HttpOnly`, `SameSite=Strict`, über HTTPS `Secure`. Timeout bei Inaktivität.
- CSRF-Token für jede ändernde Anfrage (Header `X-CSRF-Token`).
- XSS: Daten werden nur über `textContent` eingefügt. Strikte Content-Security-Policy (`default-src 'self'`).
- SQL-Injection: ausschließlich gebundene Parameter. Feld- und Tabellennamen kommen nur aus Whitelists.
- Container: Nicht-Root-Benutzer, schreibgeschütztes Dateisystem, `cap_drop: ALL`, `no-new-privileges`.
