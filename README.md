# Deckfinder für ClashRoyale

OCR-basierter Scanner, der auf deinem Bildschirm den **Gegner-Namen** und **Clan-Namen** (im „VS“-Screen) erkennt und über die **offizielle Clash Royale API** das **aktuelle Deck** des Spielers abruft.

> ⚠️ Hinweis: Das offizielle API liefert keine Live-Gegner direkt. Wir erkennen Namen/Clan am Bildschirm (OCR) und holen damit das „Current Deck“ des Spielers.

---

## Features

- Bildschirmaufnahme (macOS/Windows/Linux) via `mss`
- OCR für Gegner- und Clan-Namen mit `pytesseract` + `opencv`
- Clan per Name suchen → Spieler im Clan matchen → Player-Endpoint → **aktuelles Deck**
- Stabilitätslogik: nur auslösen, wenn OCR 1–n Frames hintereinander gleich ist
- Debug-Fenster mit Live-ROI-Vorschau (optional)

---

## Voraussetzungen

- **Python 3.10+**
- **Tesseract OCR**
  - macOS: `brew install tesseract`
  - Ubuntu/Debian: `sudo apt-get install tesseract-ocr`
  - Windows: Installer von <https://github.com/UB-Mannheim/tesseract/wiki>
- **Clash Royale API Token** (Developer-Key mit freigeschalteter IP)

---

## Installation

```bash
# 1) Projekt klonen / in Ordner wechseln
cd deckfinder

# 2) Virtuelle Umgebung & Dependencies
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3) .env anlegen
cp .env.example .env                 # CLASH_TOKEN in .env eintragen
```

---

## Konfiguration

`.env` (geheim, nicht committen):
```dotenv
CLASH_TOKEN=YOUR_CLASH_API_TOKEN
```

**Bildschirmrechte (macOS):**  
Systemeinstellungen → Datenschutz & Sicherheit → **Bildschirmaufnahme** → Terminal/IDE anhaken.

---

## Nutzung

### 1) ROI kalibrieren
Zuerst die Bereiche (ROIs) für **Gegnername** und **Clanname** einmalig markieren.

```bash
python calibrate_roi.py
```

- Es öffnet sich ein Fenster → Bereich für **Gegner-Name** ziehen → **Enter**
- Danach Bereich für **Clan-Name** → **Enter**
- Speichert `config.json` mit den Koordinaten

### 2) Live-Scan starten
```bash
python scan.py --monitor 0 --debug --show
```

- `--show`: Fenster mit Bildschirm & markierten ROIs + OCR-Crops
- `--debug`: zeigt pro Frame erkannte Texte + Confidence
- Sobald Name & Clan stabil erkannt wurden, wird das Deck im Terminal ausgegeben

Beispiel ohne Debug/GUI (wenn alles passt):
```bash
python scan.py --monitor 0 --conf-min 40 --stable 2
```

---

## CLI-Optionen (scan.py)

| Option            | Typ    | Default | Beschreibung                                                                 |
|-------------------|--------|---------|------------------------------------------------------------------------------|
| `--monitor`       | int    | `0`     | `mss`-Monitorindex: `0`=alle, `1`=Hauptmonitor, `2…` weitere Monitore        |
| `--conf-min`      | float  | `35.0`  | Mindest-Confidence je OCR-Zeile (Name/Clan), sonst wird verworfen            |
| `--stable`        | int    | `1`     | Anzahl identischer Frames in Folge, bevor der Lookup ausgelöst wird          |
| `--interval`      | float  | `0.4`   | Sekunden zwischen Scans                                                      |
| `--debug`         | flag   | —       | Verbose OCR-Ausgabe im Terminal                                              |
| `--show`          | flag   | —       | Zeigt Fenster mit Screen/ROI/Crops (zum Justieren der Bereiche)             |

> Tipp: Wenn nichts passiert, teste erstmal **locker**:  
> `python scan.py --monitor 0 --conf-min 30 --stable 1 --debug --show`

---

## Ordnerstruktur

```
deckfinder/
├─ cr_api.py              # Clash Royale API Client + Resolver + Deck-Formatter
├─ calibrate_roi.py       # ROI-Kalibrierung (Name/Clan ziehen, config.json speichern)
├─ scan.py                # Live-Scanner (OCR -> Clan/Player -> Deck)
├─ requirements.txt
├─ .env.example
└─ README.md
# wird erzeugt:
└─ config.json            # ROIs aus der Kalibrierung
```

---

## Troubleshooting

- **Es passiert nichts / keine Ausgabe**
  - Rechte für Bildschirmaufnahme setzen (macOS)
  - `--monitor 0` probieren (gesamter Desktop)
  - ROIs neu kalibrieren (`python calibrate_roi.py`)
  - `--conf-min 30` und `--stable 1` zum Testen
- **„No closing quotation“ (Tesseract)**
  - Du nutzt die aktuelle `ocr_line`-Funktion mit korrekt gequoteter Whitelist (im Repo enthalten)
- **Schwarzer Frame**
  - Terminal/IDE bei Bildschirmaufnahme freigeben; ggf. anderen Monitorindex
- **Clan/Spieler nicht gefunden**
  - Schreibweise prüfen; Clan-Suche liefert mehrere Treffer – wir wählen den mit meisten Mitgliedern  
    (kannst du in `cr_api.resolve_clan_tag_by_name` anpassen)

---

## Sicherheit & Datenschutz

- **Leake keinen API-Token.** `.env` ist in `.gitignore` – nutze `.env.example` für Platzhalter.
- Bildschirmdaten werden **nicht** gespeichert – nur live ausgewertet (außer du baust Logging ein).

---

## Lizenz

MIT – siehe `LICENSE` (optional hinzufügen).

---

## Danksagung

- OCR: [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)  
- Screen Capture: [`mss`](https://github.com/BoboTiG/python-mss)  
- API: Offizielles **Clash Royale API** (Supercell)

---

### Beispielausgabe

```
Erkannt: Gegner='Beispielname' | Clan='Testclan' (conf ~82)

🃏 Aktuelles Deck von Beispielname #QP09P82R
Clan: Drablibe
 1. Hog Rider (Lvl 14)
 2. Cannon (Lvl 14)
 3. Ice Spirit (Lvl 14)
 4. Fireball (Lvl 14)
 5. The Log (Lvl 14)
 6. Musketeer (Lvl 14)
 7. Skeletons (Lvl 14)
 8. Valkyrie (Lvl 14)
------------------------------------------------------------
```
