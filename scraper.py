import asyncio
import json
import os
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# --- KONFIGURATION ---
URL = "https://www.hagelregister.ch/bauherren-architekten/bauteil-suche.html" 
DATEN_DATEI = "hagelregister_daten.json"
HISTORY_DATEI = "history.json"
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
    "victron"
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
                await suchfeld.clear()
                await page.wait_for_timeout(500) 
                await suchfeld.press_sequentially(begriff, delay=150)
                await page.wait_for_timeout(3000) 
                
                html = await page.content()
                neue_eintraege = extrahiere_alle_daten(html)
                
                print(f"   => {len(neue_eintraege)} Einträge für '{begriff}' gefunden.")
                gesammelte_daten.update(neue_eintraege)
                
            except Exception as e:
                print(f"⚠️ Fehler bei der Suche nach '{begriff}': {e}")
        
        await browser.close()
        
    return gesammelte_daten

async def main():
    # 1. Daten holen
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
    neue_funde = []
    anderungen = []

    for nr, daten in neue_daten_gesamt.items():
        if nr not in alte_daten_gesamt:
            neue_funde.append({"nr": nr, "bezeichnung": daten['Bezeichnung'], "typ": "NEU"})
        elif alte_daten_gesamt[nr] != daten:
            anderungen.append({"nr": nr, "bezeichnung": daten['Bezeichnung'], "typ": "UPDATE"})

    # 4. Ausgabe fürs Log
    if neue_funde or anderungen:
        print(f"\n✨ {len(neue_funde)} neue und {len(anderungen)} geänderte Zertifikate gefunden!")
    else:
        print("\n✅ Alles unverändert.")

    # --- 5. HISTORIE AKTUALISIEREN (JETZT IMMER AUSFÜHREN) ---
    history = []
    if os.path.exists(HISTORY_DATEI):
        with open(HISTORY_DATEI, 'r', encoding='utf-8') as f:
            history = json.load(f)
    
    # Dieser Eintrag wird JEDEN Tag erstellt (auch wenn 'funde' leer ist)
    eintrag = {
        "datum": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "funde": neue_funde + anderungen
    }
    
    history.insert(0, eintrag)
    # Da wir jetzt jeden Tag loggen, heben wir das Gedächtnis auf 30 Einträge an
    history = history[:30] 
    
    with open(HISTORY_DATEI, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=4)
    print(f"💾 Historie in {HISTORY_DATEI} gespeichert.")

    # 6. Aktuellen Stand speichern
    with open(DATEN_DATEI, 'w', encoding='utf-8') as f:
        json.dump(neue_daten_gesamt, f, ensure_ascii=False, indent=4)
    print(f"💾 Daten in {DATEN_DATEI} aktualisiert.")

if __name__ == "__main__":
    asyncio.run(main())
