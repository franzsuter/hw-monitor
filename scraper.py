import asyncio
import json
import os
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# --- KONFIGURATION ---
URL = "https://www.hagelregister.ch/bauherren-architekten/bauteil-suche.html" 
SUCHBEGRIFF = "ja solar" 
DATEN_DATEI = "hagelregister_daten.json"

async def hole_html_von_seite():
    print(f"🚀 Starte Browser und suche nach '{SUCHBEGRIFF}'...")
    async with async_playwright() as p:
        # Browser unsichtbar starten
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto(URL)
        await page.wait_for_load_state("networkidle")
        
        try:
            # Suchfeld finden und Begriff eintippen
            suchfeld = page.get_by_placeholder("Hier Suchbegriff(e) eingeben")
            await suchfeld.clear()
            await suchfeld.press_sequentially(SUCHBEGRIFF, delay=150)
            
            # Kurz warten, bis die Tabelle aufgebaut ist
            await page.wait_for_timeout(3000) 
        except Exception as e:
            print(f"⚠️ Fehler bei der Eingabe: {e}")
            await browser.close()
            return None

        # Das fertige HTML auslesen
        html = await page.content()
        await browser.close()
        return html

def extrahiere_alle_daten(html):
    """Extrahiert alle Spalten für sichtbare Zeilen."""
    soup = BeautifulSoup(html, 'html.parser')
    ergebnisse = {}
    
    zeilen = soup.find_all('tr')
    
    for zeile in zeilen:
        # Versteckte Zeilen ignorieren
        style = zeile.get('style', '').lower().replace(' ', '')
        if 'display:none' in style:
            continue
            
        vkf_zelle = zeile.find('td', attrs={'data-heading': 'VKF Nummer'})
        
        if vkf_zelle:
            # VKF-Nummer extrahieren (ohne PDF-Icon)
            nr = vkf_zelle.get_text(separator=" ").strip().split(" ")[0]
            
            # Die restlichen Daten der Zeile auslesen
            ergebnisse[nr] = {
                "Bezeichnung": zeile.find('td', attrs={'data-heading': 'Bezeichnung'}).get_text(strip=True),
                "Beschreibung": zeile.find('td', attrs={'data-heading': 'Beschreibung'}).get_text(strip=True),
                "Gesuchsteller": zeile.find('td', attrs={'data-heading': 'Gesuchsteller'}).get_text(strip=True),
                "Gültig bis": zeile.find('td', attrs={'data-heading': 'Gültig bis'}).get_text(strip=True),
                "Klassierung": zeile.find('td', attrs={'data-heading': 'Klassierung'}).get_text(separator=" | ", strip=True)
            }
                
    return ergebnisse

async def main():
    # 1. Neues HTML holen
    html = await hole_html_von_seite()
    if not html: 
        return
    
    neue_daten_gesamt = extrahiere_alle_daten(html)
    print(f"🔎 {len(neue_daten_gesamt)} sichtbare Einträge gefunden.")

    # 2. Bestehende Daten aus der JSON-Datei laden
    alte_daten_gesamt = {}
    if os.path.exists(DATEN_DATEI):
        with open(DATEN_DATEI, 'r', encoding='utf-8') as f:
            alte_daten_gesamt = json.load(f)

    # 3. Vergleichen
    neue_eintraege = []
    geanderte_eintraege = []

    for nr, daten in neue_daten_gesamt.items():
        if nr not in alte_daten_gesamt:
            neue_eintraege.append((nr, daten))
        elif alte_daten_gesamt[nr] != daten:
            geanderte_eintraege.append((nr, alte_daten_gesamt[nr], daten))

    # 4. Änderungen ausgeben (diese landen in den GitHub Actions Logs)
    if neue_eintraege:
        print("\n✨ NEUE ZERTIFIKATE:")
        for nr, d in neue_eintraege:
            print(f"ID {nr}: {d['Bezeichnung']} ({d['Klassierung']})")

    if geanderte_eintraege:
        print("\n🔄 GEÄNDERTE ZERTIFIKATE:")
        for nr, alt, neu in geanderte_eintraege:
            print(f"ID {nr} ({neu['Bezeichnung']}) hat sich geändert!")
            for key in alt:
                if alt[key] != neu[key]:
                    print(f"  - {key}: '{alt[key]}' ➡️ '{neu[key]}'")

    if not neue_eintraege and not geanderte_eintraege:
        print("\n✅ Alles unverändert.")

    # 5. Neuen Stand abspeichern
    with open(DATEN_DATEI, 'w', encoding='utf-8') as f:
        json.dump(neue_daten_gesamt, f, ensure_ascii=False, indent=4)
    print(f"\n💾 Daten in {DATEN_DATEI} aktualisiert.")

# Skript starten
if __name__ == "__main__":
    asyncio.run(main())
