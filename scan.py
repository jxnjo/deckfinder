import os, sys, time, json, re
import numpy as np
import cv2
import mss
import pytesseract
from dotenv import load_dotenv

# aus deinem CLI-Projekt:
from cr_api import ClashAPI, resolve_clan_tag_by_name, resolve_player_tag_in_clan, fmt_player_deck

CONF_PATH = "config.json"

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
    # OCR-freundliche Vorverarbeitung
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_LINEAR)
    g = cv2.GaussianBlur(g, (3,3), 0)
    # adaptive threshold ist häufig robuster als OTSU bei UI-Glows
    g = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 5)
    return g

def ocr_line(img):
    # Whitelist: inkl. Space am ENDE der Zeichenkette
    whitelist = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789#[](){}|\\-_.!,&+/ '
    # Wichtig: den Value in Anführungszeichen setzen, damit Space & Sonderzeichen korrekt sind
    cfg = f'--psm 7 -c tessedit_char_whitelist="{whitelist}"'
    data = pytesseract.image_to_data(
        img,
        output_type=pytesseract.Output.DICT,
        config=cfg,
        lang="eng",
    )
    words, confs = [], []
    for i, txt in enumerate(data["text"]):
        t = (txt or "").strip()
        if t:
            words.append(t)
            try:
                confs.append(float(data["conf"][i]))
            except Exception:
                pass
    import re, numpy as np
    text = re.sub(r"\s+", " ", " ".join(words).strip())
    avg_conf = float(np.mean(confs)) if confs else 0.0
    return text, avg_conf

def plausible(s: str, minlen=3):
    return bool(s) and len(s) >= minlen and re.search(r"[A-Za-z0-9]", s) is not None

def main():
    load_dotenv()
    token = os.getenv("CLASH_TOKEN")
    if not token:
        print("Fehlt: CLASH_TOKEN in .env", file=sys.stderr)
        sys.exit(1)

    cfg = load_cfg()
    roi_name = cfg["roi_name"]
    roi_clan = cfg["roi_clan"]

    # Optional: capture only a sub-region of the screen to improve performance
    # and OCR quality. Config key `capture_region` may be provided as
    # [left, top, width, height]. If absent, compute minimal box covering
    # both ROIs with a small padding.
    cap = cfg.get("capture_region")
    if cap:
        left, top, width, height = map(int, cap)
    else:
        # compute bounding box around both ROIs
        xs = [roi_name[0], roi_name[0] + roi_name[2], roi_clan[0], roi_clan[0] + roi_clan[2]]
        ys = [roi_name[1], roi_name[1] + roi_name[3], roi_clan[1], roi_clan[1] + roi_clan[3]]
        pad = 10
        left = max(0, min(xs) - pad)
        top = max(0, min(ys) - pad)
        right = max(xs) + pad
        bottom = max(ys) + pad
        width = max(1, right - left)
        height = max(1, bottom - top)

    # helper to convert absolute ROI coords -> coords relative to the capture origin
    def rel_roi(roi, left, top):
        x, y, w, h = map(int, roi)
        return [x - left, y - top, w, h]

    api = ClashAPI(token)
    stable_needed = 1       # wie viele identische Frames in Folge nötig
    interval = 0.5         # Sekunden zwischen Scans
    conf_min = 40.0        # minimale mittlere OCR-Confidence

    last_pair = ("","")
    stable = 0
    last_resolved = None   # (name, clan)

    with mss.mss() as sct:
        # capture only the region we computed/configured
        monitor = {"left": left, "top": top, "width": width, "height": height}
        print(f"Scanner läuft. Capture region: left={left},top={top},w={width},h={height} - STRG+C zum Beenden.")
        while True:
            try:
                frame = np.array(sct.grab(monitor))[:, :, :3]

                # ROIs must be relative to the grabbed frame's origin
                name_img = crop(frame, rel_roi(roi_name, left, top))
                clan_img = crop(frame, rel_roi(roi_clan, left, top))

                n_txt, n_conf = ocr_line(preprocess(name_img))
                c_txt, c_conf = ocr_line(preprocess(clan_img))

                # Debug-Print (kommentiere aus, wenn zu viel)
                print(f"[{n_conf:.0f}/{c_conf:.0f}] name='{n_txt}' clan='{c_txt}'")

                if plausible(n_txt) and plausible(c_txt) and n_conf>=conf_min and c_conf>=conf_min:
                    pair = (n_txt, c_txt)
                    if pair == last_pair:
                        stable += 1
                    else:
                        stable = 1
                        last_pair = pair

                    if stable >= stable_needed and last_resolved != pair:
                        print(f"\nErkannt: Gegner='{n_txt}' | Clan='{c_txt}' (conf ~{(n_conf+c_conf)/2:.0f})")
                        last_resolved = pair
                        # --- API Lookup ---
                        ctag, csugg, cdisp = resolve_clan_tag_by_name(api, c_txt)
                        if not ctag:
                            print("Clan nicht eindeutig. Vorschläge:", csugg[:5])
                            time.sleep(interval); continue

                        ptag, nsugg, pname = resolve_player_tag_in_clan(api, ctag, n_txt)
                        if not ptag:
                            print("Spieler nicht im Clan gefunden. Mitglieder (Auszug):", nsugg[:10])
                            time.sleep(interval); continue

                        pdata = api.get_player(ptag)
                        out = fmt_player_deck(pdata, clan_name=cdisp or c_txt)
                        print(out)
                        print("-"*60)
                else:
                    stable = 0

                time.sleep(interval)
            except KeyboardInterrupt:
                print("\nBeendet.")
                break
            except Exception as e:
                print("Fehler im Loop:", e)
                time.sleep(interval)

if __name__ == "__main__":
    main()
