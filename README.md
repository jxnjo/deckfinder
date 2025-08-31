# DeckFinder — Clash Royale Gegner-Deck per Bildschirm-OCR erkennen

DeckFinder liest **Spielername** und **Clanname** live von deinem Bildschirm (OCR) und ruft über die **Clash Royale API** das **aktuelle Deck** des Spielers ab. Zusätzlich zeigt es die **letzten 10** 1v1 **Ladder/Ranked** (Trophy Road / Path of Legends) Decks – **ohne** Friendlies, Clanwar, Draft/Megadraft – mit **Übereinstimmungs‑Quote** zum aktuellen Deck. Eine kleine GUI bietet **Start/Stop**, **Kalibrierung**, **Ladebalken** und **manuelle Suche**.

> Hinweis: Dieses Tool ist ein inoffizielles Hilfs‑UI. Halte dich an die AGB des Spiels und nutze es verantwortungsvoll.

---

## Inhalt
- [Features](#features)
- [Systemvoraussetzungen](#systemvoraussetzungen)
- [Installation](#installation)
- [Konfiguration (.env)](#konfiguration-env)
- [Kalibrierung (ROIs festlegen)](#kalibrierung-rois-festlegen)
- [Starten & Nutzung](#starten--nutzung)
- [Filterlogik: Nur 1v1 Ranked/Trophy](#filterlogik-nur-1v1-rankedtrophy)
- [Tipps zur OCR-Qualität](#tipps-zur-ocr-qualität)
- [Troubleshooting](#troubleshooting)
- [Projektstruktur](#projektstruktur)
- [Roadmap / Ideen](#roadmap--ideen)
- [Lizenz](#lizenz)

---

## Features

- 🔍 **OCR-Scan** (Name/Clan) aus frei kalibrierbaren Bildschirmbereichen
- 🃏 **Aktuelles Deck** als Kartenbilder + Namen
- 🧠 **History**: letzte **10** validierte 1v1 Ladder/Ranked-Decks (Mini-PNGs)
- 📊 **Match-Score**: Übereinstimmungsquote zwischen aktuellem und Historien-Deck
- ⏳ **Loading-Bar** für API-Requests
- ⌨️ **Manuelle Suche** (Spielername + Clanname), falls OCR nicht greift
- 🖥️ **Windows & macOS** unterstützt

---

## Systemvoraussetzungen

- **Python** 3.11 oder 3.12
- **Tesseract OCR**
  - **Windows:** Installer (UB Mannheim) – Standardpfad `C:\Program Files\Tesseract-OCR\tesseract.exe`
  - **macOS (Homebrew):** `brew install tesseract`
- Abhängigkeiten aus `requirements.txt` (u. a. `opencv-python`, `mss`, `pytesseract`, `httpx`, `Pillow`, `python-dotenv`, `tkinter` (ist bei Python für Windows/macOS enthalten))

---

## Installation

```bash
# 1) Projekt klonen
git clone https://github.com/<DEIN-USER>/deckfinder.git
cd deckfinder

# 2) Virtuelle Umgebung (empfohlen)
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 3) Abhängigkeiten installieren
pip install -r requirements.txt
```

### Tesseract installieren

- **Windows:** Lade den Installer herunter (z. B. von UB Mannheim), installiere nach `C:\Program Files\Tesseract-OCR\`.  
- **macOS:**  
  ```bash
  brew install tesseract
  ```

---

## Konfiguration (.env)

Erstelle eine Datei **`.env`** im Projekt‑Root:

```ini
CLASH_TOKEN=dein_clash_royale_api_token

# Optional: Wenn Tesseract nicht automatisch gefunden wird
# TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

> Deinen API‑Token erhältst du im **Clash Royale Developer Portal**.  
> `.env` steht in `.gitignore` – **nicht committen!**

---

## Kalibrierung (ROIs festlegen)

Starte den Kalibrier‑Assistenten, um die Regionen für **Spielername** und **Clanname** festzulegen (und optional eine **Capture‑Region**):

```bash
python calibrate_roi.py
```

- **Capture‑Region** (optional) ziehen → ENTER (ohne Auswahl: ganzer Screen).  
- **ROI Spielername** ziehen → ENTER.  
- **ROI Clanname** ziehen → ENTER.

Es entsteht eine `config.json`, z. B.:

```json
{
  "roi_name": [952, 126, 120, 40],
  "roi_clan": [952, 170, 140, 32],
  "capture_region": [900, 100, 300, 200]
}
```

> Tipp: Ziehe die Boxen **eng** um den Text, ohne Icons/Glows.

---

## Starten & Nutzung

```bash
python ui.py
```

**UI‑Elemente:**
- **Scan starten/stoppen**: OCR‑Loop an/aus
- **Kalibrieren…**: Assistent erneut starten
- **Spieler/Clan + Deck suchen**: Manuelle Suche (ENTER in Feldern möglich)
- **Anzeige**:
  - aktuelles Deck (8 große Icons + Namen)
  - **Letzte 10 Decks** (nur 1v1 Ladder/Ranked) mit Mini‑Icons & **Fortschrittsbalken** (Match‑%)
  - Status/Log‑Ausgabe unten

---

## Filterlogik: Nur 1v1 Ranked/Trophy

Die Historie filtert so, dass nur echte 1v1‑Ladder/Ranked‑Kämpfe einfließen:

- `type == "PvP"`
- genau **1 vs 1**
- **kein** Draft/Megadraft, **keine** Friendlies/Challenges/Clanwar
- Whitelist über GameMode‑Namen: enthält eines von  
  `ranked`, `path of legends`, `ladder`, `trophy road`, `league`

Dadurch bleiben Testspiele/Clanwars/Megadraft zuverlässig außen vor.

---

## Tipps zur OCR‑Qualität

- **ROIs enger ziehen** (nur Text)
- Spielgrafik: **hohe Auflösung**, klare Schrift, ggf. Gamma/Helligkeit erhöhen
- **Name**: Kontrastreiche Darstellung (goldene Schrift → gut sichtbar)
- In `ui.py` kann die Schwelle `conf_min` (Standard ≈ 35) angepasst werden

---

## Troubleshooting

### „Tesseract nicht gefunden“
- Windows: Prüfe `C:\Program Files\Tesseract-OCR\tesseract.exe` und setze ggf. in `.env`:
  ```ini
  TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
  ```
- macOS: `brew install tesseract` und sicherstellen, dass `tesseract` im `PATH` liegt.

### „Battlelog konnte nicht geladen werden“
- Token korrekt? Rate‑Limit? Internet verfügbar? Nochmals versuchen.

### OCR erkennt „Oo“ / „Be“ statt Name/Clan
- ROIs enger ziehen.
- In‑Game‑UI größer stellen, Anti‑Aliasing reduzieren.
- Beleuchtung/Monitor‑Helligkeit prüfen.

### Keine Historie zu sehen
- Der Spieler hat evtl. nur Friendlies/Clanwar/Draft in den letzten Kämpfen.  
  Die Filterlogik blendet diese **absichtlich** aus.

---

## Projektstruktur

```
deckfinder/
├─ ui.py              # GUI + OCR + Anzeige (aktuelles Deck, Historie, Match-Score)
├─ calibrate_roi.py   # Assistent zur Festlegung der ROIs (Name/Clan + optional Capture-Region)
├─ cr_api.py          # Clash Royale API Wrapper + Helpers
├─ config.json        # erzeugt durch Kalibrieren (nicht committen)
├─ .env               # API-Token (nicht committen)
└─ requirements.txt
```

---

## Roadmap / Ideen

- Spieler‑Panel mit Statistiken (Winrate, meistgespielte Karten, Trophäen‑Verlauf)
- Export (PNG/CSV), Dark‑Mode, Hotkeys
- Auto‑Update‑Hinweise im UI

---

## Lizenz

MIT (siehe `LICENSE`). Dieses Projekt steht in keinem Zusammenhang mit Supercell.

---

## Mitwirken

PRs/Issues sind willkommen. Bitte **keine sensiblen Daten** hochladen (`.env`, `config.json`, Token, private Screenshots).
