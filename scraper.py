import asyncio
import json
import os
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# --- KONFIGURATION ---
URL = "https://www.hagelregister.ch/bauherren-architekten/bauteil-suche.html" 
DATEN_DATEI = "hagelregister_daten.json"

# HIER KANNST DU DEINE LISTE ANPASSEN (in Anführungszeichen, getrennt durch Kommata):
SUCHBEGRIFFE = [
    "ja solar", 
    "jinko", 
    "trina", 
    "meyer burger"
] 

def extrahiere_alle_daten(html):
    """Extrahiert alle Spalten für sichtbare Zeilen aus dem HTML."""
    soup = BeautifulSoup(html, 'html.parser')
    ergebnisse = {}
    zeilen = soup.find_all('tr')
    
    for zeile in zeilen:
        style = zeile.get('style', '').lower().replace(' ', '')
        if 'display:none' in style:
            continue
            
        vkf_zelle = zeile.find('td', attrs={'data-heading': 'VKF Nummer'})
        if vkf_zelle:
            nr = vkf_zelle.get_text(separator=" ").strip().split(" ")[0]
            ergebnisse[nr] = {
                "Bezeichnung": zeile.find('td', attrs={'data-heading': 'Bezeichnung'}).get_text(strip=True),
                "Beschreibung": zeile.find('td', attrs={'data-heading': 'Beschreibung'}).get_text(strip=True),
                "Gesuchsteller": zeile.find('td', attrs={'data-heading': 'Gesuchsteller'}).get_text(strip=True),
                "Gültig bis": zeile.find('td', attrs={'data-heading': 'Gültig bis'}).get_text(strip=True),
                "Klassierung": zeile.find('td', attrs={'data-heading': 'Klassierung'}).get_text(separator=" | ", strip=True)
            }
    return ergebnisse

async def hole_alle_daten():
    """Startet den Browser und klappert alle Suchbegriffe nacheinander ab."""
    print(f"🚀 Starte Browser für {len(SUCHBEGRIFFE)} Suchbegriffe...")
    gesammelte_daten = {}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        await page.goto(URL)
        await page.wait_for_load_state("networkidle")
        
        for begriff in SUCHBEGRIFFE:
            print(f"\n🔍 Suche nach '{begriff}'...")
            try:
                suchfeld = page.get_by_placeholder("Hier Suchbegriff(e) eingeben")
                
                # Feld leeren (wichtig für den 2., 3., 4. Suchbegriff)
                await suchfeld.clear()
                await page.wait_for_timeout(500) 
                
                # Begriff wie ein Mensch eintippen
                await suchfeld.press_sequentially(begriff, delay=150)
                
                # Kurz warten, bis die Tabelle aufgebaut ist
                await page.wait_for_timeout(3000) 
                
                # HTML auslesen und direkt extrahieren
                html = await page.content()
                neue_eintraege = extrahiere_alle_daten(html)
                
                print(f"   => {len(neue_eintraege)} Einträge für '{begriff}' gefunden.")
                
                # Die gefundenen Einträge in unser großes Gesamt-Lexikon packen
                gesammelte_daten.update(neue_eintraege)
                
            except Exception as e:
                print(f"⚠️ Fehler bei der Suche nach '{begriff}': {e}")
        
        await browser.close()
        
    return gesammelte_daten

async def main():
    # 1. Alle Daten frisch von der Website holen
    neue_daten_gesamt = await hole_alle_daten()
    
    if not neue_daten_gesamt: 
        print("❌ Keine Daten gefunden.")
        return
        
    print(f"\n✅ Insgesamt {len(neue_daten_gesamt)} eindeutige Einträge gesammelt.")

    # 2. Bestehende Daten laden
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

    # 4. Änderungen ausgeben (für das GitHub Log)
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

if __name__ == "__main__":
    asyncio.run(main())
