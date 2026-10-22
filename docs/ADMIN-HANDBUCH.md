# Admin-Handbuch

## Bedienung in Kürze

- **Befehlsfeld** (oben links, Taste F6): Transaktionscode eingeben und Enter, z. B. `ZE01`.
  `/oZE01` öffnet die Transaktion in einem neuen Fenster.
- **F3** zurück, **F8** ausführen (Liste laden bzw. Buchung absenden).
- **Statusleiste**: Meldungen, angemeldeter Benutzer, aktuelle Kettenspitze des Protokolls, Restzeit der Sitzung.
- Listen: Klick auf den Spaltenkopf sortiert, das Feld „Schnellfilter“ filtert, „CSV“ exportiert.

| T-Code | Funktion | T-Code | Funktion |
|---|---|---|---|
| ZS00 | Startbild | ZC01 | Felder |
| ZE01 | Einchecken | ZC02 | Kategorien |
| ZA01 | Auschecken | ZC03 | Seiten und Masken |
| ZB01 | Bestandsliste | ZC04 | Menüs und T-Codes |
| ZB02 | Bald ablaufende Artikel | ZC05 | Regeln |
| ZB03 | Buchungen | ZC06 | Rechte |
| ZB04 | Artikelstamm | ZC07 | Versionen |
| ZP01 | Protokoll | ZS01 | Backup |
| ZP02 | Protokoll prüfen / Quittung | ZS02 | Einstellungen |
| ZU01 | Benutzerverwaltung | ZU02 | Passwort ändern |

## Grundregeln (fest eingebaut)

- **Mein Bestand** kann ausschließlich der Admin ändern. Das lässt sich auch per Customizing nicht ändern.
- Bucht der Admin im **Keller**, gilt das als **Admin-Eingriff**: Eine Begründung ist Pflicht, und die Buchung wird
  in Listen und im Protokoll rot markiert.
- Benutzerverwaltung, Customizing und Backup darf nur der Admin.
- Alle Benutzer dürfen das Protokoll einsehen, prüfen und exportieren.
- Das Protokoll kann niemand ändern oder löschen, auch der Admin nicht.

## Benutzer verwalten (ZU01)

1. **Benutzer anlegen**: Benutzername und Startpasswort eingeben. Neue Konten haben die Rolle „Benutzer“.
   Beim ersten Login muss der Benutzer das Passwort ändern.
2. **Sperren/Entsperren**: Ein gesperrter Benutzer kann sich nicht mehr anmelden. Laufende Sitzungen enden sofort.
3. **Passwort zurücksetzen**: Startpasswort neu setzen. Der Benutzer muss es danach ändern.
4. **Loginsperre aufheben**: Nach 5 Fehlversuchen sperrt das System den Login zunächst für 60 Sekunden.
   Jeder weitere Fehlversuch verdoppelt die Sperre (höchstens 1 Stunde). Hier lässt sie sich vorzeitig aufheben.

Alle Aktionen werden protokolliert. Ein Benutzerkonto wird nie gelöscht, sondern nur gesperrt. So bleiben die
Protokolleinträge eindeutig zuordenbar.

## Buchen

- **Einchecken (ZE01)**: Bestand wählen und EAN eingeben. Ist die EAN bekannt, werden Bezeichnung und Kategorie
  vorbelegt und gesperrt. Änderungen am Artikelstamm laufen über ZB04. Dann MHD, Charge und Menge eingeben.
  Artikel gleicher EAN mit anderem MHD oder anderer Charge werden als eigene Position geführt.
- **Auschecken (ZA01)**: EAN eingeben und die Position wählen (älteste MHD zuerst), dann die Menge.
  Alternativ in der Bestandsliste bei der Position auf „Auschecken“ klicken.
- Löst eine Regel eine Warnung aus (z. B. MHD in weniger als 7 Tagen), muss die Buchung bestätigt werden.

Korrekturen: Buchungen sind unveränderlich. Eine Fehlbuchung wird durch eine Gegenbuchung mit Begründung
korrigiert. Beide Vorgänge bleiben im Protokoll sichtbar.

## Customizing

Jede Änderung erzeugt eine neue **Version** (ZC07) und einen Protokolleintrag mit altem und neuem Wert.

### Eigene Felder (ZC01)

1. „Feld anlegen“: Wählen, wozu das Feld gehört. **Artikel** bedeutet ein Wert je EAN, gepflegt im Artikelstamm.
   **Buchung** bedeutet ein Wert je Ein- oder Auschecken.
2. Feldcode (technisch, z. B. `preis`), Bezeichnung, Typ (Text, Zahl, Datum, Auswahlliste, Ja/Nein) und
   Pflichtfeld festlegen. Bei einer Auswahlliste die Werte mit `;` trennen.
3. Das Feld anschließend unter **ZC03** in die gewünschte Maske oder Liste aufnehmen.

Feldcode, Typ und Zuordnung lassen sich später nicht mehr ändern. Ein Feld, das nicht mehr gebraucht wird,
deaktivieren. Löschen geht nur, wenn keine Seite das Feld verwendet.

### Kategorien (ZC02)

Kategorien anlegen, umbenennen, sortieren und deaktivieren. Sie werden nie gelöscht, damit vorhandene Artikel
ihre Kategorie behalten.

### Seiten und Masken (ZC03)

- **Listen**: Datenquelle (Bestandspositionen, Buchungen, Artikelstamm), Spalten mit Reihenfolge und eigener
  Bezeichnung, Filter des Selektionsbilds, Sortierung und Vorbelegungen (z. B. nur Keller, nur MHD innerhalb von
  14 Tagen) sowie die Zeilenaktion.
- **Masken**: Feldreihenfolge, eigene Bezeichnungen, Zusatzfelder und optional ein fester Bestand.
  Systemfelder wie EAN, MHD und Menge können verschoben, aber nicht entfernt werden.
- „Neue Seite“ legt eine Seite an. Damit sie erreichbar ist, unter ZC04 einen Menüeintrag und/oder T-Code zuordnen.

### Menüs und T-Codes (ZC04)

Hauptmenüs und Einträge anlegen, umbenennen, sortieren und deaktivieren. Transaktionscodes bestehen aus
2–10 Zeichen, Großbuchstaben und Ziffern, z. B. `ZK01`.

### Regeln (ZC05)

Eine Regel besteht aus einem Auslöser, einer oder mehreren Bedingungen (alle müssen zutreffen) und einer Aktion.

- Auslöser: **Bei Buchung** oder **Bei Anzeige** (Listen).
- Bedingungen z. B. `MHD` · `Tage bis Datum kleiner` · `7`, `Menge` · `größer` · `50`, `Bestand` · `gleich` · `KELLER`.
- Aktionen: **Warnung** (Buchung nur nach Bestätigung), **Buchung verhindern**, **Zeile markieren**.

Beispiel „Wenn MHD in weniger als 7 Tagen, dann Warnung“ ist vorinstalliert.

### Rechte (ZC06)

Für die Rolle „Benutzer“ einstellbar:
- Keller: Bestand anzeigen, Einchecken, Auschecken
- Artikelstamm pflegen
- „Mein Bestand“ lesen (Standard: aus)

Fest vorgegebene Rechte sind auf derselben Seite aufgelistet.

### Versionen (ZC07)

Liste aller Customizing-Stände. „Auf diesen Stand zurücksetzen“ stellt eine frühere Version wieder her und legt
dafür eine **neue** Version an. Es geht nichts verloren. Bestände, Buchungen und Protokoll bleiben unberührt.

### Einstellungen (ZS02)

Sitzungs-Timeout (Standard 15 Minuten), Vorlaufzeit für den Ablaufhinweis, Uhrzeit des täglichen Backups (UTC)
und „Mein Bestand“ für andere lesbar.

## Protokoll prüfen

**ZP01** zeigt alle Einträge mit Zeitstempel, Benutzer, Aktion, Bestand, Objekt sowie altem und neuem Wert.
Admin-Eingriffe sind rot hinterlegt. „Details“ zeigt den vollständigen Eintrag mit Hash-Werten.

**ZP02**:
1. **Jetzt prüfen**: rechnet die komplette Hash-Kette nach und prüft, ob jeder Bestand exakt der Summe seiner
   Buchungen entspricht. Ein Fehler nennt die Nummer des ersten manipulierten Eintrags.
2. **Quittung herunterladen**: Eine kleine Datei mit Nummer und Hash des letzten Eintrags. Jedes
   Familienmitglied kann sie jederzeit selbst herunterladen und aufbewahren.
3. **Quittung prüfen**: Prüft, ob das heutige Protokoll den Stand der Quittung unverändert fortsetzt.

Warum Quittungen wichtig sind: Wer direkten Zugriff auf die Datenbankdatei hat, könnte theoretisch die gesamte
Hash-Kette neu berechnen. Die Kette wäre dann in sich wieder stimmig. Eine früher ausgestellte Quittung passt dann
aber nicht mehr, und die Fälschung wird sichtbar. Je mehr Familienmitglieder gelegentlich eine Quittung
herunterladen, desto stärker ist der Nachweis.

Auf dem Pi geht die Prüfung auch per Kommandozeile:

```bash
docker compose exec lager python -m app.cli pruefen
docker compose exec lager python -m app.cli pruefen --quittung /data/quittung-123.json
```

## Backup und Wiederherstellung (ZS01)

- **Automatisch**: täglich zur eingestellten Stunde. Aufbewahrt werden die letzten 7 täglichen und 4 wöchentlichen
  Backups. Manuelle Backups bleiben dauerhaft erhalten.
- **Backup jetzt erstellen**: legt sofort ein Backup an.
- **Herunterladen**: speichert die Backup-Datei auf dem eigenen Rechner. Der Download wird protokolliert.
- **Wiederherstellen**: setzt Bestände, Benutzer und Customizing auf den Stand des Backups.
  - Vorher wird automatisch ein Sicherheits-Backup angelegt („vor-wiederherstellung“).
  - Das **Protokoll bleibt vollständig erhalten**. Einträge nach dem Backup-Zeitpunkt werden übernommen, und die
    Wiederherstellung wird als eigener Eintrag vermerkt.
  - Passt ein Backup nicht zum aktuellen Protokoll (z. B. aus einer fremden Installation), bricht die
    Wiederherstellung ab.
  - Nach der Wiederherstellung müssen sich alle Benutzer neu anmelden.

**Notfall** (Datenbank defekt, Anwendung startet nicht):

```bash
docker compose stop lager
docker compose run --rm lager python -m app.cli notfall-wiederherstellen lager-JJJJMMTT-HHMMSS-auto.db
docker compose start lager
```

Die defekte Datenbank wird dabei nicht gelöscht, sondern als `data/defekt-…` aufbewahrt. Weil hier das Protokoll
auf den Backup-Stand zurückgeht, wird das als `NOTFALL_WIEDERHERSTELLUNG` vermerkt. Fehlende Einträge erkennt man
an den Quittungen.
