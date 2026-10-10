# Hagelregister-Monitor

Der Monitor sucht nach PV-Modulen im Hagelregister, vergleicht den Bestand und
zeigt neue, geänderte und entfernte Zertifikate in einer statischen Webseite an.

## Entwicklung

Python 3.11 oder neuer ist erforderlich:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
playwright install --with-deps chromium
```

Die Anzeige startet mit `python -m http.server 8000`. Sie lädt die JSON-Dateien
per HTTP; ein direktes Öffnen von `index.html` als Datei reicht nicht aus.

`python scraper.py` muss im Repository-Verzeichnis ausgeführt werden und
aktualisiert `hagelregister_daten.json` und `history.json`. Ein fehlgeschlagener
oder insgesamt leerer Scan endet mit Fehlerstatus. Ergebnisse werden nur nach
erfolgreichen Suchabfragen und vollständiger Tabellenextraktion übernommen.
Einzelne Suchbegriffe dürfen keine Treffer haben. Entfernte Einträge werden
nur nach einem vollständigen Scan protokolliert. Die JSON-Dateien werden
einzeln atomar ersetzt; die beiden Dateien bilden keine gemeinsame Transaktion.

Der Scraper nutzt den synchronen Enter-Filter der Hagelregister-Tabelle statt
fester Wartezeiten. Die Extraktion berücksichtigt die vom Browser tatsächlich
sichtbaren Zeilen. Änderungen am Filter der Quellseite können eine Anpassung
erfordern. Die TLS-Zertifikatsprüfung bleibt aktiviert.

Erfolgreiche Scans speichern zusätzlich `scan_at` als ISO-Zeitpunkt mit
Zeitzonenoffset. Neue Zeitangaben werden für `Europe/Zurich` angezeigt;
historische Einträge ohne Zeitzone behalten ihre ursprüngliche Darstellung.
Nach 48 Stunden ohne erfolgreichen Scan zeigt die Anzeige eine Warnung.

## Tests

```sh
python -m unittest discover -s tests -v
RUN_BROWSER_TESTS=1 python -m unittest discover -s tests -v
```

Die zweite Variante prüft zusätzlich Anzeige und Suchablauf mit Chromium und
lokalen Testdaten. Sie braucht den installierten Playwright-Browser, jedoch
keinen Zugriff auf das Hagelregister. Die produktiven JSON-Dateien bleiben
unverändert. GitHub Actions führt diese Tests vor jedem Scan aus und verhindert
parallele Scan-Läufe. Der Zeitplan `0 7 * * *` verwendet UTC (08:00 Uhr im
Schweizer Winter, 09:00 Uhr im Sommer).
