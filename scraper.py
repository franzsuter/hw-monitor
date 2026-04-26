import asyncio
import json
import os
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# --- KONFIGURATION ---
URL = "https://www.hagelregister.ch/bauherren-architekten/bauteil-suche.html" 
DATEN_DATEI = "hagelregister_daten.json"
HISTORY_DATEI = "history.json" # NEU: Hier landen die News
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

# ... (Funktionen extrahiere_alle_daten und hole_alle_daten bleiben gleich wie vorher) ...

async def main():
    neue_daten_gesamt = await hole_alle_daten()
    if not neue_daten_gesamt: return
    
    alte_daten_gesamt = {}
    if os.path.exists(DATEN_DATEI):
        with open(DATEN_DATEI, 'r', encoding='utf-8') as f:
            alte_daten_gesamt = json.load(f)

    neue_funde = []
    anderungen = []

    for nr, daten in neue_daten_gesamt.items():
        if nr not in alte_daten_gesamt:
            neue_funde.append({"nr": nr, "bezeichnung": daten['Bezeichnung'], "typ": "NEU"})
        elif alte_daten_gesamt[nr] != daten:
            anderungen.append({"nr": nr, "bezeichnung": daten['Bezeichnung'], "typ": "UPDATE"})

    # --- HISTORIE AKTUALISIEREN ---
    if neue_funde or anderungen:
        history = []
        if os.path.exists(HISTORY_DATEI):
            with open(HISTORY_DATEI, 'r', encoding='utf-8') as f:
                history = json.load(f)
        
        eintrag = {
            "datum": datetime.now().strftime("%d.%m.%Y"),
            "funde": neue_funde + anderungen
        }
        
        # Neuen Eintrag oben hinzufügen und Liste auf 20 begrenzen
        history.insert(0, eintrag)
        history = history[:20] 
        
        with open(HISTORY_DATEI, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=4)

    # Aktuellen Stand speichern
    with open(DATEN_DATEI, 'w', encoding='utf-8') as f:
        json.dump(neue_daten_gesamt, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    asyncio.run(main())
