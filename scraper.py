import asyncio
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Error as PlaywrightError


class ScanError(RuntimeError):
    """Ein unvollständiger Scan darf den letzten guten Stand nicht ersetzen."""


class ExtractionError(ScanError):
    """Die Quelltabelle enthält unvollständige oder widersprüchliche Zeilen."""


def load_json(filepath, default_value):
    """Lädt JSON-Daten aus einer Datei oder gibt den Standardwert zurück."""
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default_value


def save_json(filepath, data):
    """Ersetzt die Zieldatei erst, wenn das vollständige JSON geschrieben ist."""
    target = Path(filepath)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', dir=target.parent,
            prefix=f'.{target.name}.', suffix='.tmp', delete=False,
        ) as f:
            temporary = Path(f.name)
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


# --- KONFIGURATION ---
URL = "https://www.hagelregister.ch/bauherren-architekten/bauteil-suche.html" 
DATEN_DATEI = "hagelregister_daten.json"
HISTORY_DATEI = "history.json"
ZEITZONE = ZoneInfo("Europe/Zurich")
FELDER = ("Bezeichnung", "Beschreibung", "Gesuchsteller", "Gültig bis", "Klassierung")
SUCHBEGRIFFE = [
    "ja solar", 
    "jinko", 
    "trina", 
    "aiko",
    "aleo",
    "das energy",
    "goodwe",
    "longi",
    "solitek",
    "soluxtec",
    "sunpower",
    "victron",
    "SolarRoof",
    "Gokin"
]


def extrahiere_alle_daten(html):
    """Extrahiert alle Spalten für sichtbare Zeilen aus dem HTML."""
    soup = BeautifulSoup(html, 'html.parser')
    ergebnisse = {}
    fehler = []
    zeilen = soup.find_all('tr')
    
    for zeile in zeilen:
        if any(
            node.has_attr('hidden')
            or re.search(r'display\s*:\s*none\b', node.get('style', ''), re.I)
            for node in [zeile, *zeile.parents]
            if node.name is not None
        ):
            continue
            
        vkf_zelle = zeile.find('td', attrs={'data-heading': 'VKF Nummer'})
        if vkf_zelle is None and any(
            zeile.find('td', attrs={'data-heading': feld}) is not None for feld in FELDER
        ):
            fehler.append("Datenzeile ohne VKF-Nummernfeld")
            continue
        if vkf_zelle:
            nummerntext = vkf_zelle.get_text(separator=" ", strip=True).split()
            if not nummerntext:
                fehler.append("Zeile ohne VKF Nummer")
                continue
            nr = nummerntext[0]
            zellen = {feld: zeile.find('td', attrs={'data-heading': feld}) for feld in FELDER}
            fehlende_felder = [feld for feld, zelle in zellen.items() if zelle is None]
            if fehlende_felder:
                fehler.append(f"VKF {nr}: fehlende Felder {', '.join(fehlende_felder)}")
                continue
            daten = {
                feld: (
                    zelle.get_text(separator=" | ", strip=True)
                    if feld == "Klassierung" else " ".join(zelle.get_text().split())
                )
                for feld, zelle in zellen.items()
            }
            if nr in ergebnisse and ergebnisse[nr] != daten:
                fehler.append(f"VKF {nr}: widersprüchliche doppelte Zeilen")
                continue
            ergebnisse[nr] = daten
    if fehler:
        raise ExtractionError("; ".join(fehler))
    return ergebnisse


async def hole_alle_daten(url=URL, suchbegriffe=None):
    """Startet den Browser und klappert alle Suchbegriffe nacheinander ab."""
    suchbegriffe = SUCHBEGRIFFE if suchbegriffe is None else suchbegriffe
    print(f"🚀 Starte Browser für {len(suchbegriffe)} Suchbegriffe...")
    gesammelte_daten = {}
    fehler = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            response = await page.goto(url, wait_until="domcontentloaded")
            if response is None or not response.ok:
                raise ScanError(f"Quellseite nicht verfügbar: HTTP {response.status if response else 'unbekannt'}")
            suchfeld = page.get_by_placeholder("Hier Suchbegriff(e) eingeben")
            await suchfeld.wait_for(state="visible")
            datentabelle = page.locator('table:has(td[data-heading="VKF Nummer"])')
            if await datentabelle.count() != 1:
                raise ScanError("Die Quellseite enthält keine eindeutige Zertifikatstabelle.")
            # Das Hagelregister verwendet TableFilter. Enter wendet den Filter
            # synchron an; dadurch sind weder Tippverzögerung noch feste Sleeps nötig.
            for begriff in suchbegriffe:
                print(f"\n🔍 Suche nach '{begriff}'...")
                try:
                    await suchfeld.fill(begriff)
                    await suchfeld.press("Enter")
                    html = await datentabelle.locator(
                        'tr:visible:has(td[data-heading])'
                    ).evaluate_all("rows => rows.map(row => row.outerHTML).join('')")
                    neue_eintraege = extrahiere_alle_daten(html)
                    for nr, daten in neue_eintraege.items():
                        if nr in gesammelte_daten and gesammelte_daten[nr] != daten:
                            raise ExtractionError(f"VKF {nr}: widersprüchliche Suchergebnisse")
                    print(f"   => {len(neue_eintraege)} Einträge für '{begriff}' gefunden.")
                    gesammelte_daten.update(neue_eintraege)
                except (PlaywrightError, ExtractionError) as e:
                    fehler.append(begriff)
                    print(f"❌ Suche nach '{begriff}' fehlgeschlagen: {e}", file=sys.stderr)
        finally:
            await browser.close()
    if fehler:
        raise ScanError(f"Scan unvollständig: {', '.join(fehler)}. Vorhandene Daten bleiben erhalten.")
    if not gesammelte_daten:
        raise ScanError("Keine Daten gefunden. Vorhandene Daten bleiben erhalten.")
    return gesammelte_daten


async def main():
    # 1. Daten holen
    neue_daten_gesamt = await hole_alle_daten()
    if not neue_daten_gesamt:
        raise ScanError("Keine Daten gefunden. Vorhandene Daten bleiben erhalten.")
        
    print(f"\n✅ Insgesamt {len(neue_daten_gesamt)} eindeutige Einträge gesammelt.")

    # 2. Bestehende Daten laden
    alte_daten_gesamt = load_json(DATEN_DATEI, {})

    # 3. Vergleichen
    neue_funde = []
    anderungen = []
    entfernte = []

    for nr, daten in neue_daten_gesamt.items():
        if nr not in alte_daten_gesamt:
            neue_funde.append({"nr": nr, "bezeichnung": daten['Bezeichnung'], "typ": "NEU"})
        elif alte_daten_gesamt[nr] != daten:
            anderungen.append({"nr": nr, "bezeichnung": daten['Bezeichnung'], "typ": "UPDATE"})
    for nr, daten in alte_daten_gesamt.items():
        if nr not in neue_daten_gesamt:
            entfernte.append({"nr": nr, "bezeichnung": daten['Bezeichnung'], "typ": "ENTFERNT"})

    # 4. Ausgabe fürs Log
    if neue_funde or anderungen or entfernte:
        print(f"\n✨ {len(neue_funde)} neue, {len(anderungen)} geänderte und {len(entfernte)} entfernte Zertifikate gefunden!")
    else:
        print("\n✅ Alles unverändert.")

    # --- 5. HISTORIE AKTUALISIEREN (JETZT IMMER AUSFÜHREN) ---
    history = load_json(HISTORY_DATEI, [])
    
    # Dieser Eintrag wird JEDEN Tag erstellt (auch wenn 'funde' leer ist)
    scan_zeit = datetime.now(ZEITZONE)
    eintrag = {
        "datum": scan_zeit.strftime("%d.%m.%Y %H:%M"),
        "scan_at": scan_zeit.isoformat(),
        "funde": neue_funde + anderungen + entfernte
    }
    
    history.insert(0, eintrag)
    # Da wir jetzt jeden Tag loggen, heben wir das Gedächtnis auf 30 Einträge an
    history = history[:30] 
    
    # Die Historie meldet einen Erfolg erst, nachdem der Bestand gespeichert ist.
    save_json(DATEN_DATEI, neue_daten_gesamt)
    print(f"💾 Daten in {DATEN_DATEI} aktualisiert.")
    save_json(HISTORY_DATEI, history)
    print(f"💾 Historie in {HISTORY_DATEI} gespeichert.")


def cli():
    """Liefert auch bei abgefangenen Scanfehlern einen Fehlerstatus an den Runner."""
    try:
        asyncio.run(main())
    except (ScanError, PlaywrightError, OSError, ValueError) as e:
        print(f"❌ Scan fehlgeschlagen: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(cli())
