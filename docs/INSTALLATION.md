# Installation auf dem Raspberry Pi

Voraussetzungen: Raspberry Pi 3, 4 oder 5 mit **64-Bit**-Raspberry-Pi-OS (Bookworm oder neuer), Netzwerkzugang
im Heimnetz, ca. 1 GB freier Speicher.

## 1. System aktualisieren

```bash
sudo apt update && sudo apt full-upgrade -y
uname -m          # muss "aarch64" ausgeben (64-Bit)
```

## 2. Docker installieren

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
sudo usermod -aG docker $USER
```

Danach einmal ab- und wieder anmelden (oder `newgrp docker`). Prüfen:

```bash
docker run --rm hello-world
docker compose version
```

## 3. Feste IP-Adresse für den Pi

Im Router dem Pi eine feste IP-Adresse zuweisen (DHCP-Reservierung), z. B. `192.168.178.50`.
Die Adresse wird unten für das Zertifikat und die Firewall gebraucht.

## 4. Anwendung herunterladen

```bash
cd ~
git clone <repo-url> lager_heim
cd lager_heim
mkdir -p data
sudo chown 1000:1000 data      # der Container läuft als Benutzer mit UID 1000
```

## 5. Konfiguration

Datei `.env` im Ordner `lager_heim` anlegen (Werte anpassen):

```bash
cat > .env <<'EOF'
# Nur auf der LAN-Adresse des Pi lauschen
LAGER_BIND=192.168.178.50
# Namen/Adressen für das HTTPS-Zertifikat
LAGER_TLS_SAN=192.168.178.50,lager.fritz.box
EOF
```

## 6. Starten

```bash
docker compose up -d --build
docker compose ps                 # Status "healthy" nach ca. 30 Sekunden
docker compose logs -f            # Protokollausgabe, Abbruch mit Strg+C
```

## 7. Admin anlegen

Es gibt genau einen Admin. Er wird einmalig über die Kommandozeile angelegt:

```bash
docker compose exec lager python -m app.cli admin-anlegen
```

Benutzername und Passwort (mind. 8 Zeichen) eingeben.

## 8. Aufrufen

Im Browser: `https://192.168.178.50:8443`

Beim ersten Aufruf warnt der Browser vor dem selbstsignierten Zertifikat. Die Warnung pro Gerät einmal
bestätigen. Optional kann das Zertifikat `data/tls/zertifikat.pem` auf den Geräten als vertrauenswürdig
importiert werden, dann entfällt die Warnung.

## 9. Nur im Heimnetz erreichbar machen

- **Im Router keine Portfreigabe/Port-Weiterleitung** für Port 8443 einrichten.
- Firewall auf dem Pi (Subnetz anpassen):

```bash
sudo apt install -y ufw
sudo ufw default deny incoming
sudo ufw allow from 192.168.178.0/24 to any port 22 proto tcp
sudo ufw allow from 192.168.178.0/24 to any port 8443 proto tcp
sudo ufw enable
```

Hinweis: Docker kann ufw-Regeln für veröffentlichte Ports umgehen. Deshalb bindet die Anwendung über
`LAGER_BIND` ausschließlich an die LAN-Adresse. Ohne Portfreigabe im Router ist sie von außen nicht erreichbar.

## 10. Autostart

`restart: unless-stopped` in `docker-compose.yml` startet die Anwendung nach einem Neustart des Pi automatisch.
Docker selbst startet per systemd automatisch (`sudo systemctl is-enabled docker` → `enabled`).

## 11. Updates einspielen

```bash
cd ~/lager_heim
docker compose exec lager python -m app.cli backup     # vorher sichern
git pull
docker compose up -d --build --pull always             # holt auch Sicherheitsupdates des Basis-Images
docker image prune -f
```

Empfehlung: Basis-Image und Betriebssystem monatlich aktualisieren (`sudo apt full-upgrade`, dann obiger Ablauf).

## 12. Backups auf ein anderes Gerät kopieren

Die automatischen Backups liegen in `~/lager_heim/data/backups/`. Fällt die SD-Karte aus, sind sie mit
weg. Daher regelmäßig ein Backup auf einen USB-Stick oder NAS kopieren, z. B. per Cronjob:

```bash
crontab -e
# täglich 04:00 auf USB-Stick kopieren:
0 4 * * * rsync -a ~/lager_heim/data/backups/ /media/usb/lager-backups/
```

## Fehlerbehebung

| Problem | Lösung |
|---|---|
| `permission denied` auf `/data` | `sudo chown -R 1000:1000 ~/lager_heim/data` |
| Seite nicht erreichbar | `docker compose ps`, `docker compose logs`, IP und `LAGER_BIND` prüfen |
| Zertifikat passt nicht zur Adresse | `LAGER_TLS_SAN` anpassen, `data/tls/` löschen, `docker compose restart` |
| Admin-Passwort vergessen | `docker compose exec lager python -m app.cli passwort-setzen <admin-name>` (wird protokolliert) |
