# ClashRoyale Deckfinder Bot
OCR-basierter Gegner-/Clan-Scan + aktuelles Deck via Clash Royale API.

## Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # CLASH_TOKEN eintragen

## Nutzung
python calibrate_roi.py
python scan.py --monitor 0 --debug --show