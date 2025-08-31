# calibrate_roi.py – minimal: nur Spielername- und Clanname-ROI erfassen

import json
import os
import sys
import numpy as np
import cv2
import mss

CONF_PATH = "config.json"


def grab_fullscreen() -> np.ndarray:
    """Screenshot des gesamten virtuellen Desktops (alle Monitore)."""
    with mss.mss() as sct:
        mon = sct.monitors[0]  # [0] = full virtual screen
        img = np.array(sct.grab(mon))[:, :, :3]  # BGRA -> BGR
        return img


def pick_roi(window_title: str, base_img: np.ndarray, hint: str) -> tuple[int, int, int, int]:
    """ROI mit Maus ziehen und ENTER drücken. Gibt (x,y,w,h) als int zurück."""
    view = base_img.copy()
    cv2.putText(
        view, hint, (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2, cv2.LINE_AA
    )
    # Auswahlfenster
    r = cv2.selectROI(window_title, view, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(window_title)

    x, y, w, h = map(int, r)
    if w <= 0 or h <= 0:
        print(f"❌ Keine Auswahl fuer '{window_title}' getroffen.", file=sys.stderr)
        sys.exit(1)
    return x, y, w, h


def main():
    img = grab_fullscreen()

    # 1) Spielername-ROI
    roi_name = pick_roi(
        "ROI: Spielername",
        img,
        "Ziehe ein Rechteck NUR um den SPIELERNAMEN und druecke ENTER"
    )

    # 2) Clanname-ROI
    roi_clan = pick_roi(
        "ROI: Clanname",
        img,
        "Ziehe ein Rechteck NUR um den CLANNAMEN und druecke ENTER"
    )

    cfg = {
        "roi_name": [int(v) for v in roi_name],
        "roi_clan": [int(v) for v in roi_clan],
    }

    with open(CONF_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    print("✅ Gespeichert:", os.path.abspath(CONF_PATH))
    print("   roi_name:", cfg["roi_name"])
    print("   roi_clan:", cfg["roi_clan"])


if __name__ == "__main__":
    main()
