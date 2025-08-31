import json
import os
import numpy as np
import cv2
import mss

CONF_PATH = "config.json"

def grab_screen():
    # Prüfe config.json auf eine optionale capture_region: [left, top, width, height]
    cfg = {}
    if os.path.exists(CONF_PATH):
        try:
            with open(CONF_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}

    cap = cfg.get("capture_region")
    with mss.mss() as sct:
        if cap:
            left, top, width, height = map(int, cap)
            monitor = {"left": left, "top": top, "width": width, "height": height}
        else:
            monitor = sct.monitors[1]  # primärer Monitor

        img = np.array(sct.grab(monitor))[:, :, :3]  # BGRA -> BGR
        return img

def main():
    img = grab_screen()

    # Schritt 1: optional Capture-Region wählen
    view = img.copy()
    cv2.putText(view, "Ziehe optional eine Capture-Region. ENTER ohne Auswahl = ganzer Bildschirm",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
    rcap = cv2.selectROI("Capture-Region (optional)", view, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow("Capture-Region (optional)")

    # Falls keine Auswahl (w oder h == 0), verwenden wir den ganzen Bildschirm
    if int(rcap[2]) == 0 or int(rcap[3]) == 0:
        left, top, width, height = 0, 0, img.shape[1], img.shape[0]
        capture_region = None
        print("Keine Capture-Region gewählt: ganzer Bildschirm wird verwendet.")
    else:
        left, top, width, height = map(int, rcap)
        capture_region = [left, top, width, height]
        print(f"Capture-Region gesetzt: left={left}, top={top}, w={width}, h={height}")

    # Ausschnitt zum Kalibrieren (für die ROI-Auswahl anzeigen)
    crop = img[top:top+height, left:left+width].copy()

    # Schritt 2: ROI für Gegner-Namen wählen (relativ zur Capture-Region)
    view = crop.copy()
    cv2.putText(view, "Ziehe ROI fuer GEGNER-NAME und druecke ENTER",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
    r1 = cv2.selectROI("ROI: Gegner-Name", view, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow("ROI: Gegner-Name")

    # Schritt 3: ROI für Clan-Namen wählen (relativ zur Capture-Region)
    view = crop.copy()
    cv2.putText(view, "Ziehe ROI fuer CLAN-NAME und druecke ENTER",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
    r2 = cv2.selectROI("ROI: Clan-Name", view, showCrosshair=True, fromCenter=False)
    cv2.destroyAllWindows()

    # Konvertiere die in der Auswahl relativen Koordinaten in absolute Bildschirm-Koordinaten
    def abs_roi(rel, left, top):
        x, y, w, h = map(int, rel)
        return [int(x + left), int(y + top), int(w), int(h)]

    roi_name_abs = abs_roi(r1, left, top)
    roi_clan_abs = abs_roi(r2, left, top)

    cfg = {"roi_name": roi_name_abs, "roi_clan": roi_clan_abs}
    if capture_region is not None:
        cfg["capture_region"] = capture_region

    os.makedirs(os.path.dirname(CONF_PATH) or ".", exist_ok=True)
    with open(CONF_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    print("Gespeichert:", os.path.abspath(CONF_PATH), cfg)

if __name__ == "__main__":
    main()
