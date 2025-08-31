import os, sys, time, json, re, shutil
import numpy as np
import cv2, mss, pytesseract
from dotenv import load_dotenv

# --- Tesseract finden (simpel) ---
TESS = os.getenv("TESSERACT_CMD")
if TESS:
    pytesseract.pytesseract.tesseract_cmd = TESS
elif os.name == "nt":
    cand = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(cand):
        pytesseract.pytesseract.tesseract_cmd = cand
cmd = pytesseract.pytesseract.tesseract_cmd or "tesseract"
if not (os.path.exists(cmd) or shutil.which(cmd)):
    print("Tesseract nicht gefunden. Installiere es oder setze TESSERACT_CMD.", file=sys.stderr)
    sys.exit(1)

# --- Clash-API Helfer ---
from cr_api import ClashAPI, resolve_clan_tag_by_name, resolve_player_tag_in_clan, fmt_player_deck

CONF_PATH   = "config.json"
CONF_MIN    = 35    # benötigte OCR-Confidence je Zeile
STABLE_NEED = 1       # gleiche Erkennung so oft hintereinander
INTERVAL    = 0.4     # Sekunden zwischen Scans

def load_cfg():
    if not os.path.exists(CONF_PATH):
        print("config.json fehlt. Erst 'python calibrate_roi.py' ausfuehren.", file=sys.stderr)
        sys.exit(1)
    with open(CONF_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def crop(img, roi):
    x, y, w, h = map(int, roi)
    return img[y:y+h, x:x+w]

def preprocess(img):
    # Auf OCR optimieren: groß, glatt, schwellen, bei Bedarf invertieren
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    g = cv2.bilateralFilter(g, d=7, sigmaColor=75, sigmaSpace=75)
    g = cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX)
    _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if np.mean(bw) < 127:
        bw = cv2.bitwise_not(bw)
    return bw

def ocr_line(img):
    # bewusst OHNE Whitelist (vermeidet Quote-Probleme auf Windows)
    best_text, best_conf = "", 0.0
    for psm in (7, 6):  # 7=Zeile, 6=Block
        cfg = f"--oem 3 --psm {psm}"
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config=cfg, lang="eng")
        words, confs = [], []
        for i, txt in enumerate(data["text"]):
            t = (txt or "").strip()
            if t:
                words.append(t)
                try:
                    confs.append(float(data["conf"][i]))
                except:
                    pass
        text = re.sub(r"\s+", " ", " ".join(words).strip())
        conf = float(np.mean(confs)) if confs else 0.0
        if conf > best_conf:
            best_text, best_conf = text, conf
    return best_text, best_conf

def plausible(s: str, minlen=3):
    return bool(s) and len(s) >= minlen and re.search(r"[A-Za-z0-9]", s) is not None

def main():
    load_dotenv()
    token = os.getenv("CLASH_TOKEN")
    if not token:
        print("Fehlt: CLASH_TOKEN in .env", file=sys.stderr); sys.exit(1)

    cfg = load_cfg()
    roi_name = cfg["roi_name"]
    roi_clan = cfg["roi_clan"]

    api = ClashAPI(token)
    last_pair, stable, last_resolved = ("",""), 0, None

    with mss.mss() as sct:
        monitor = sct.monitors[0]  # gesamter virtueller Desktop
        print("Scanner läuft – STRG+C zum Beenden.")
        while True:
            try:
                frame = np.array(sct.grab(monitor))[:, :, :3]

                name_img = crop(frame, roi_name)
                clan_img = crop(frame, roi_clan)

                n_txt, n_conf = ocr_line(preprocess(name_img))
                c_txt, c_conf = ocr_line(preprocess(clan_img))

                print(f"[{n_conf:.0f}/{c_conf:.0f}] name='{n_txt}' clan='{c_txt}'")

                if plausible(n_txt) and plausible(c_txt) and n_conf >= CONF_MIN and c_conf >= CONF_MIN:
                    pair = (n_txt, c_txt)
                    stable = stable + 1 if pair == last_pair else 1
                    last_pair = pair

                    if stable >= STABLE_NEED and last_resolved != pair:
                        print(f"\nErkannt: Gegner='{n_txt}' | Clan='{c_txt}' (conf ~{(n_conf+c_conf)/2:.0f})")
                        last_resolved = pair

                        ctag, csugg, cdisp = resolve_clan_tag_by_name(api, c_txt)
                        if not ctag:
                            print("Clan nicht eindeutig. Vorschläge:", csugg[:5])
                            time.sleep(INTERVAL); continue

                        ptag, nsugg, pname = resolve_player_tag_in_clan(api, ctag, n_txt)
                        if not ptag:
                            print("Spieler nicht im Clan gefunden. Mitglieder (Auszug):", nsugg[:10])
                            time.sleep(INTERVAL); continue

                        pdata = api.get_player(ptag)
                        print(fmt_player_deck(pdata, clan_name=cdisp or c_txt))
                        print("-"*60)
                else:
                    stable = 0

                time.sleep(INTERVAL)
            except KeyboardInterrupt:
                print("\nBeendet."); break
            except Exception as e:
                print("Fehler im Loop:", e)
                time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
