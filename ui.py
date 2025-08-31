import os
import sys
import json
import time
import threading
import queue
import io
import re

import tkinter as tk
from tkinter import ttk, messagebox

import numpy as np
import cv2
import mss
import pytesseract
from PIL import Image, ImageTk
import httpx
from dotenv import load_dotenv

# --- Tesseract suchen (einfach & robust) -------------------------------------
TESS = os.getenv("TESSERACT_CMD")
if TESS:
    pytesseract.pytesseract.tesseract_cmd = TESS
elif os.name == "nt":
    for cand in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if os.path.exists(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
            break
# ------------------------------------------------------------------------------

# --- Clash Royale API Helpers -------------------------------------------------
from cr_api import (
    ClashAPI,
    resolve_clan_tag_by_name,
    resolve_player_tag_in_clan,
    extract_player_cards_from_battle,  # für History-Decks aus Battlelog
)

CONF_PATH = "config.json"


# --------------------------- OCR: Name/Clan getrennt --------------------------
def preprocess_name(img):
    """Goldene, leuchtende Schrift → L-Kanal + lokale Kontrastverstärkung."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L, _, _ = cv2.split(lab)
    L = cv2.resize(L, None, fx=3.5, fy=3.5, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    L = clahe.apply(L)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    L = cv2.morphologyEx(L, cv2.MORPH_TOPHAT, kernel, iterations=1)
    L = cv2.GaussianBlur(L, (3, 3), 0)
    _, bw = cv2.threshold(L, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Tesseract mag schwarze Schrift auf weiß – ggf. invertieren
    if np.mean(bw) < 127:
        bw = cv2.bitwise_not(bw)
    return bw


def preprocess_clan(img):
    """Weiße, schlichte Schrift → Graustufe + adaptives Threshold."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    g = cv2.GaussianBlur(g, (3, 3), 0)
    bw = cv2.adaptiveThreshold(
        g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5
    )
    if np.mean(bw) < 127:
        bw = cv2.bitwise_not(bw)
    return bw


def _ocr_psm(img, psm):
    cfg = f"--oem 3 --psm {psm}"
    data = pytesseract.image_to_data(
        img, output_type=pytesseract.Output.DICT, config=cfg, lang="eng"
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
    text = re.sub(r"\s+", " ", " ".join(words).strip())
    conf = float(np.mean(confs)) if confs else 0.0
    return text, conf


def ocr_name(img):  # einzelnes Wort
    return _ocr_psm(img, 8)


def ocr_clan(img):  # einzelne Zeile; fallback Block
    t, c = _ocr_psm(img, 7)
    if c >= 30:
        return t, c
    return _ocr_psm(img, 6)


def plausible(s: str, minlen=3):
    return bool(s) and len(s) >= minlen and re.search(r"[A-Za-z0-9]", s) is not None


# ------------------- Ladder/Ranked PvP Filter + Stats -------------------------
def _is_ranked_or_trophy_pvp_1v1(b: dict) -> bool:
    """
    True für Trophäenpfad/Ranked 1v1:
    - type == 'PvP'
    - kein Draft/Megadraft
    - keine Friendlies, keine Challenges, kein Clanwar
    """
    if (b.get("type") or "").lower() != "pvp":
        return False
    if len(b.get("team") or []) != 1 or len(b.get("opponent") or []) != 1:
        return False

    gm = ((b.get("gameMode") or {}).get("name") or "").lower()
    ds = (b.get("deckSelection") or "").lower()

    if "draft" in ds:
        return False
    if b.get("challengeId") or b.get("challengeTitle") or b.get("isFriendly"):
        return False
    if any(k in gm for k in ("river", "boat", "clan war")):
        return False

    allowed = ("ranked", "path of legends", "ladder", "trophy road", "league")
    return any(k in gm for k in allowed)


def _avg_elixir(deck: list[dict]) -> float:
    costs = []
    for c in deck or []:
        v = c.get("elixirCost", c.get("elixir"))
        if isinstance(v, (int, float)):
            costs.append(float(v))
    return round(sum(costs) / len(costs), 1) if costs else 0.0


def _four_card_cycle(deck: list[dict]) -> int:
    costs = []
    for c in deck or []:
        v = c.get("elixirCost", c.get("elixir"))
        if isinstance(v, (int, float)):
            costs.append(float(v))
    costs.sort()
    return int(round(sum(costs[:4]))) if len(costs) >= 4 else 0


def _favorite_card(player: dict) -> dict | None:
    fav = player.get("currentFavouriteCard")
    if fav:
        return fav
    deck = player.get("currentDeck") or []
    return deck[0] if deck else None


def _find_icon_url(card_obj: dict) -> str | None:
    icon = (card_obj or {}).get("iconUrls") or {}
    for k in ("medium", "evolutionMedium", "evolutionSmall", "large", "small"):
        if icon.get(k):
            return icon[k]
    return None


def _pvp_stats_last_n(battles: list[dict], n: int = 10) -> tuple[int, int, float, int, int]:
    """Gibt (wins, losses, wr, crowns_for, crowns_against) über die letzten n Ladder-PvP zurück."""
    wins = losses = crowns_for = crowns_against = 0
    for b in battles[:n]:
        t = (b.get("team") or [{}])[0]
        o = (b.get("opponent") or [{}])[0]
        cf = int(t.get("crowns", 0))
        ca = int(o.get("crowns", 0))
        crowns_for += cf
        crowns_against += ca
        if cf > ca:
            wins += 1
        elif cf < ca:
            losses += 1
    total = wins + losses
    wr = (wins / total) if total else 0.0
    return wins, losses, wr, crowns_for, crowns_against


# ------------------------------- Scanner-Thread -------------------------------
class Scanner(threading.Thread):
    def __init__(
        self,
        q_out: queue.Queue,
        stop_ev: threading.Event,
        conf_min=35.0,
        interval=0.4,
        stable_need=1,
    ):
        super().__init__(daemon=True)
        self.q_out = q_out
        self.stop_ev = stop_ev
        self.conf_min = conf_min
        self.interval = interval
        self.stable_need = stable_need
        self.last_pair = ("", "")
        self.stable = 0
        self.last_resolved = None

        # load cfg
        if not os.path.exists(CONF_PATH):
            raise FileNotFoundError(
                "config.json fehlt. Bitte zuerst calibrate_roi.py ausführen."
            )
        with open(CONF_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.roi_name = cfg["roi_name"]
        self.roi_clan = cfg["roi_clan"]

        load_dotenv()
        token = os.getenv("CLASH_TOKEN")
        if not token:
            raise RuntimeError("Fehlt: CLASH_TOKEN in .env")
        self.api = ClashAPI(token)

    @staticmethod
    def crop(img, roi):
        x, y, w, h = map(int, roi)
        return img[y : y + h, x : x + w]

    def run(self):
        with mss.mss() as sct:
            mon = sct.monitors[0]  # gesamter virtueller Desktop
            self.q_out.put(("status", "Scan gestartet."))
            while not self.stop_ev.is_set():
                try:
                    frame = np.array(sct.grab(mon))[:, :, :3]
                    name_img_raw = self.crop(frame, self.roi_name)
                    clan_img_raw = self.crop(frame, self.roi_clan)

                    name_img = preprocess_name(name_img_raw)
                    clan_img = preprocess_clan(clan_img_raw)

                    n_txt, n_conf = ocr_name(name_img)
                    c_txt, c_conf = ocr_clan(clan_img)

                    self.q_out.put(
                        ("ocr", f"[{n_conf:.0f}/{c_conf:.0f}] name='{n_txt}' clan='{c_txt}'")
                    )

                    if (
                        plausible(n_txt)
                        and plausible(c_txt)
                        and n_conf >= self.conf_min
                        and c_conf >= self.conf_min
                    ):
                        pair = (n_txt, c_txt)
                        self.stable = self.stable + 1 if pair == self.last_pair else 1
                        self.last_pair = pair

                        if self.stable >= self.stable_need and self.last_resolved != pair:
                            self.last_resolved = pair
                            # „Loading“ an
                            self.q_out.put(("loading", True))
                            self.q_out.put(("resolved", {"name": n_txt, "clan": c_txt}))
                            self.q_out.put(
                                ("status", f"Erkannt: Gegner='{n_txt}' | Clan='{c_txt}'")
                            )
                            # Lookup
                            try:
                                ctag, csugg, cdisp = resolve_clan_tag_by_name(self.api, c_txt)
                                if not ctag:
                                    self.q_out.put(
                                        ("status", f"Clan nicht eindeutig. Vorschläge: {csugg[:5]}")
                                    )
                                else:
                                    ptag, nsugg, pname = resolve_player_tag_in_clan(
                                        self.api, ctag, n_txt
                                    )
                                    if not ptag:
                                        self.q_out.put(
                                            ("status", f"Spieler nicht im Clan. Mitglieder (Auszug): {nsugg[:10]}")
                                        )
                                    else:
                                        pdata = self.api.get_player(ptag)
                                        self.q_out.put(("deck", pdata))
                            except Exception as e:
                                self.q_out.put(("status", f"API-Fehler: {e}"))
                            finally:
                                # „Loading“ aus
                                self.q_out.put(("loading", False))
                    else:
                        self.stable = 0

                    time.sleep(self.interval)
                except Exception as e:
                    self.q_out.put(("status", f"Fehler: {e}"))
                    time.sleep(self.interval)
            self.q_out.put(("status", "Scan gestoppt."))


# ----------------------------------- UI --------------------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DeckFinder")
        self.geometry("1100x820")
        self.minsize(1100, 820)

        self.q = queue.Queue()
        self.stop_ev = threading.Event()
        self.scanner = None
        self.http = httpx.Client(timeout=10.0)

        load_dotenv()
        token = os.getenv("CLASH_TOKEN")
        if not token:
            messagebox.showerror("Fehlt", "CLASH_TOKEN in .env nicht gesetzt.")
            self.destroy()
            return
        self.api = ClashAPI(token)

        self.last_clan_detected = ""  # vom Scanner erkannt (für manuellen Fallback)

        # Topbar
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        self.topbar = top  # für Loading-Bar

        self.btn_start = ttk.Button(top, text="Scan starten", command=self.start_scan)
        self.btn_start.pack(side="left", padx=(0, 8))

        self.btn_stop = ttk.Button(
            top, text="Scan stoppen", command=self.stop_scan, state="disabled"
        )
        self.btn_stop.pack(side="left", padx=(0, 12))

        self.btn_cal = ttk.Button(top, text="Kalibrieren…", command=self.run_calibrate)
        self.btn_cal.pack(side="left", padx=(0, 16))

        # Manueller Lookup
        ttk.Label(top, text="Spieler:").pack(side="left")
        self.ent_player = ttk.Entry(top, width=18)
        self.ent_player.pack(side="left", padx=(4, 12))
        self.ent_player.bind("<Return>", lambda e: self.manual_lookup())

        ttk.Label(top, text="Clan (optional):").pack(side="left")
        self.ent_clan = ttk.Entry(top, width=18)
        self.ent_clan.pack(side="left", padx=(4, 8))
        self.ent_clan.bind("<Return>", lambda e: self.manual_lookup())

        self.btn_lookup = ttk.Button(top, text="Deck suchen", command=self.manual_lookup)
        self.btn_lookup.pack(side="left", padx=(0, 8))

        # Loading-Bar (indeterminate), wird bei Bedarf eingeblendet
        self.loading = ttk.Progressbar(top, mode="indeterminate", length=120)

        # Status
        self.status = tk.StringVar(value="Bereit.")
        ttk.Label(top, textvariable=self.status).pack(side="left", padx=12)

        # --- Spieler-Info Panel ------------------------------------------------
        self.profile = ttk.Labelframe(self, text="Spieler-Info")
        self.profile.pack(fill="x", padx=10, pady=(6, 2))

        self.p_name   = tk.StringVar(value="—")
        self.p_king   = tk.StringVar(value="—")
        self.p_troph  = tk.StringVar(value="—")
        self.p_clan   = tk.StringVar(value="—")
        self.p_deck   = tk.StringVar(value="—")
        self.p_wr     = tk.StringVar(value="—")
        self.p_crowns = tk.StringVar(value="—")

        row = ttk.Frame(self.profile); row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text="Name/Tag:", width=14).grid(row=0, column=0, sticky="w")
        ttk.Label(row, textvariable=self.p_name).grid(row=0, column=1, sticky="w", padx=(0,16))
        ttk.Label(row, text="King-Level:", width=14).grid(row=0, column=2, sticky="w")
        ttk.Label(row, textvariable=self.p_king).grid(row=0, column=3, sticky="w", padx=(0,16))
        ttk.Label(row, text="Trophäen:", width=14).grid(row=0, column=4, sticky="w")
        ttk.Label(row, textvariable=self.p_troph).grid(row=0, column=5, sticky="w", padx=(0,16))

        row2 = ttk.Frame(self.profile); row2.pack(fill="x", padx=8, pady=(0,6))
        ttk.Label(row2, text="Clan:", width=14).grid(row=0, column=0, sticky="w")
        ttk.Label(row2, textvariable=self.p_clan).grid(row=0, column=1, sticky="w", padx=(0,16))
        ttk.Label(row2, text="Deck:", width=14).grid(row=0, column=2, sticky="w")
        ttk.Label(row2, textvariable=self.p_deck).grid(row=0, column=3, sticky="w", padx=(0,16))
        ttk.Label(row2, text="WR (letzte 10 PvP):", width=18).grid(row=0, column=4, sticky="w")
        ttk.Label(row2, textvariable=self.p_wr).grid(row=0, column=5, sticky="w", padx=(0,16))
        ttk.Label(row2, text="Kronen (F/A):", width=14).grid(row=0, column=6, sticky="w")
        ttk.Label(row2, textvariable=self.p_crowns).grid(row=0, column=7, sticky="w")

        right = ttk.Frame(self.profile); right.pack(anchor="e", padx=8, pady=(0,6))
        self.p_fav_icon_img = None
        self.p_fav_icon = ttk.Label(right, text="Lieblingskarte")
        self.p_fav_icon.pack(side="right")

        # Karten-Grid (aktuelles Deck)
        grid = ttk.Frame(self, padding=10)
        grid.pack(fill="both", expand=True)

        self.card_labels = []
        self.card_images = [None] * 8
        self.card_name_labels = []
        for i in range(8):
            frame = ttk.Frame(grid)
            frame.grid(row=i // 4, column=i % 4, padx=3, pady=3, sticky="nsew")
            grid.columnconfigure(i % 4, weight=1)
            lbl_img = ttk.Label(frame, text=f"{i+1}", anchor="center", width=22)
            lbl_img.pack(pady=(0, 2))
            lbl_name = ttk.Label(frame, text="", anchor="center", width=22, font=(None, 10))
            lbl_name.pack()
            self.card_labels.append(lbl_img)
            self.card_name_labels.append(lbl_name)
        for r in range(2):
            grid.rowconfigure(r, weight=1)

        # Log
        bottom = ttk.Frame(self, padding=(10, 0, 10, 10))
        bottom.pack(fill="both")
        ttk.Label(bottom, text="Log").pack(anchor="w")
        self.txt = tk.Text(bottom, height=7)
        self.txt.pack(fill="both", expand=True)
        self.txt.configure(state="disabled")

        # „Letzte 10 Decks“ – UI wird lazy aufgebaut
        self.hist_frame = None
        self.hist_rows = None

        # Queue poller
        self.after(100, self.process_queue)

    # --------------------------- kleine Helfer --------------------------------
    def log(self, msg: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", msg.strip() + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def set_status(self, s: str):
        self.status.set(s)
        self.log(s)

    def _set_loading(self, on: bool):
        if on:
            if not self.loading.winfo_ismapped():
                self.loading.pack(side="left", padx=8)
            self.loading.start(12)
        else:
            self.loading.stop()
            if self.loading.winfo_ismapped():
                self.loading.pack_forget()

    def _ensure_history_ui(self):
        if self.hist_frame is not None:
            return
        # Äußerer Frame für den scrollbaren Bereich
        outer_frame = ttk.Frame(self)
        outer_frame.pack(fill="both", expand=True, padx=10, pady=6)

        ttk.Label(outer_frame, text="Letzte 10 Decks", font=(None, 12, "bold")).pack(
            anchor="w", padx=6, pady=(0, 4)
        )

        canvas = tk.Canvas(outer_frame, height=300)
        scrollbar = ttk.Scrollbar(outer_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.hist_frame = scrollable_frame

        self.hist_rows = []
        for r in range(10):
            row = {}
            row_frame = ttk.Frame(self.hist_frame)
            row_frame.pack(fill="x", padx=6, pady=4)

            row["text"] = ttk.Label(row_frame, text=f"D{r+1}", width=16, anchor="w")
            row["text"].grid(row=0, column=0, sticky="w", padx=(0, 8))

            row["pb"] = ttk.Progressbar(row_frame, mode="determinate", length=180, maximum=100)
            row["pb"].grid(row=0, column=1, sticky="w")

            row["icons"] = []
            row["images"] = [None] * 8
            for c in range(8):
                lbl = ttk.Label(row_frame, text="", width=10, anchor="center")
                lbl.grid(row=0, column=2 + c, padx=4)
                row["icons"].append(lbl)

            self.hist_rows.append(row)

    def _get_tkimg(self, url: str, size: tuple[int, int]):
        if not hasattr(self, "_icon_cache"):
            self._icon_cache = {}
        key = f"{url}|{size[0]}x{size[1]}"
        if key in self._icon_cache:
            return self._icon_cache[key]
        resp = self.http.get(url)
        resp.raise_for_status()
        im = Image.open(io.BytesIO(resp.content)).convert("RGBA")
        im = im.resize(size, Image.LANCZOS)
        tkimg = ImageTk.PhotoImage(im)
        self._icon_cache[key] = tkimg
        return tkimg

    # ----------------------------- Scan-Buttons -------------------------------
    def start_scan(self):
        if not os.path.exists(CONF_PATH):
            messagebox.showerror("Fehlt", "config.json nicht gefunden. Bitte zuerst kalibrieren.")
            return
        try:
            self.stop_ev.clear()
            self.scanner = Scanner(self.q, self.stop_ev, conf_min=35.0, interval=0.4, stable_need=1)
            self.scanner.start()
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.set_status("Scanner gestartet…")
        except Exception as e:
            messagebox.showerror("Fehler", str(e))

    def stop_scan(self):
        if self.scanner and self.scanner.is_alive():
            self.stop_ev.set()
            self.scanner.join(timeout=2.0)
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.set_status("Scanner gestoppt.")

    def run_calibrate(self):
        import subprocess

        try:
            subprocess.run([sys.executable, "calibrate_roi.py"], check=True)
            self.set_status("Kalibrierung abgeschlossen.")
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Kalibrierung fehlgeschlagen", str(e))

    # ----------------------------- Manuelle Suche -----------------------------
    def manual_lookup(self):
        player = self.ent_player.get().strip()
        clan = self.ent_clan.get().strip()

        if not player:
            messagebox.showwarning("Eingabe fehlt", "Bitte mindestens den Spielernamen eingeben.")
            return

        if not clan and self.last_clan_detected:
            clan = self.last_clan_detected
            self.set_status(f"Kein Clan eingegeben – verwende erkannten Clan: {clan}")

        if not clan:
            messagebox.showwarning(
                "Clan benötigt",
                "Die API erlaubt keine globale Namenssuche. Bitte Clan angeben (oder zuerst scannen).",
            )
            return

        self.btn_lookup.configure(state="disabled")
        t = threading.Thread(target=self._manual_lookup_worker, args=(player, clan), daemon=True)
        t.start()

    def _manual_lookup_worker(self, player: str, clan: str):
        try:
            self.q.put(("status", f"Suche Deck: Spieler='{player}', Clan='{clan}' …"))
            self.q.put(("loading", True))
            ctag, csugg, cdisp = resolve_clan_tag_by_name(self.api, clan)
            if not ctag:
                self.q.put(("status", f"Clan nicht eindeutig. Vorschläge: {csugg[:5]}"))
                return
            ptag, nsugg, pname = resolve_player_tag_in_clan(self.api, ctag, player)
            if not ptag:
                self.q.put(("status", f"Spieler nicht im Clan gefunden. Mitglieder (Auszug): {nsugg[:10]}"))
                return
            pdata = self.api.get_player(ptag)
            self.q.put(("deck", pdata))
            self.q.put(("status", f"Deck geladen: {pname} {ptag} (Clan: {cdisp or clan})"))
        except Exception as e:
            self.q.put(("status", f"Fehler bei manueller Suche: {e}"))
        finally:
            self.q.put(("loading", False))
            self.after(0, lambda: self.btn_lookup.configure(state="normal"))

    # ----------------------------- Queue-Events -------------------------------
    def process_queue(self):
        try:
            while True:
                what, payload = self.q.get_nowait()
                if what == "status":
                    self.set_status(str(payload))
                elif what == "ocr":
                    self.log(str(payload))
                elif what == "resolved":
                    self.last_clan_detected = (payload.get("clan") or "").strip()
                elif what == "loading":
                    self._set_loading(bool(payload))
                elif what == "deck":
                    self.show_deck(payload)
        except queue.Empty:
            pass
        self.after(100, self.process_queue)

    # ------------------------ Player-Info Aktualisierung ----------------------
    def update_player_info(self, player: dict, ladder_battles: list[dict], current_deck: list[dict]):
        name = player.get("name", "Unbekannt")
        tag  = player.get("tag", "")
        lvl  = player.get("expLevel") or "?"
        trophies = player.get("trophies", "?")
        best     = player.get("bestTrophies", None)
        trophies_txt = f"{trophies}" + (f" (PB {best})" if isinstance(best, int) else "")

        clan = player.get("clan") or {}
        role = (player.get("role") or "").replace("_", " ").title()
        clan_txt = "—"
        if clan:
            cname = clan.get("name", "?")
            ctag  = clan.get("tag", "")
            clan_txt = f"{cname} {ctag}" + (f" · {role}" if role else "")

        avg_elix = _avg_elixir(current_deck)
        cycle4   = _four_card_cycle(current_deck)
        deck_txt = f"Ø {avg_elix} | 4-Cycle {cycle4}"

        wins, losses, wr, cf, ca = _pvp_stats_last_n(ladder_battles, n=10)
        wr_txt     = f"{wr*100:.0f}% ({wins}-{losses})"
        crowns_txt = f"{cf}/{ca}"

        self.p_name.set(f"{name} {tag}")
        self.p_king.set(f"{lvl}")
        self.p_troph.set(trophies_txt)
        self.p_clan.set(clan_txt)
        self.p_deck.set(deck_txt)
        self.p_wr.set(wr_txt)
        self.p_crowns.set(crowns_txt)

        fav = _favorite_card(player)
        if fav:
            url = _find_icon_url(fav)
            if url:
                try:
                    tkimg = self._get_tkimg(url, (54, 64))
                    self.p_fav_icon_img = tkimg
                    self.p_fav_icon.configure(image=tkimg, text="")
                except Exception:
                    self.p_fav_icon.configure(text=fav.get("name", "Fav"))
            else:
                self.p_fav_icon.configure(text=fav.get("name", "Fav"))
        else:
            self.p_fav_icon.configure(text="Lieblingskarte")

    # ----------------------------- Deck-Anzeige -------------------------------
    def _find_card_icon_url(self, card_obj: dict) -> str | None:
        icon = card_obj.get("iconUrls") or {}
        for k in ("medium", "evolutionMedium", "evolutionSmall", "large", "small"):
            if icon.get(k):
                return icon[k]
        return None

    def show_deck(self, player_payload: dict):
        name = player_payload.get("name", "Unbekannt")
        tag = player_payload.get("tag", "")
        deck = player_payload.get("currentDeck") or []

        # --- aktuelles Deck groß rendern ---
        self.card_images = [None] * 8
        for i in range(8):
            lbl_img = self.card_labels[i]
            lbl_name = self.card_name_labels[i]
            lbl_img.configure(image="", text=f"{i+1}")
            lbl_name.configure(text="")
            if i >= len(deck):
                continue

            card = deck[i] or {}
            title = card.get("name", f"Karte {i+1}")
            url = self._find_card_icon_url(card)
            try:
                if url:
                    tkimg = self._get_tkimg(url, (120, 144))
                    self.card_images[i] = tkimg
                    lbl_img.configure(image=tkimg, text="")
                else:
                    lbl_img.configure(text=title)
            except Exception:
                lbl_img.configure(text=title)
            lbl_name.configure(text=title)

        # --- Battlelog holen & nur Ladder/Ranked-PvP verwenden ---
        self._set_loading(True)
        try:
            battles = self.api.get_battlelog(tag)
        except Exception as e:
            self._set_loading(False)
            self.set_status(f"Battlelog konnte nicht geladen werden: {e}")
            return

        recent_cards: list[list[dict]] = []
        ladder_battles: list[dict] = []
        for b in battles:
            if not _is_ranked_or_trophy_pvp_1v1(b):
                continue
            ladder_battles.append(b)
            cards = extract_player_cards_from_battle(b, tag)
            if cards:
                recent_cards.append(cards)
            if len(recent_cards) >= 10:
                break

        # --- Player-Info Panel updaten (nutzt Ladder-Battles) ---
        self.update_player_info(player_payload, ladder_battles, deck)

        def card_key_set(cards: list[dict]) -> set[str]:
            keys = []
            for c in cards or []:
                cid = c.get("id") or c.get("key") or c.get("name")
                if cid is not None:
                    keys.append(str(cid).lower())
            return set(keys)

        cur_keys = card_key_set(deck)
        sims: list[tuple[float, int]] = []
        for rc in recent_cards:
            hk = card_key_set(rc)
            inter = len(cur_keys & hk)
            pct = inter / 8.0
            sims.append((pct, inter))

        if sims:
            avg = sum(s for s, _ in sims) / len(sims)
            best = max(s for s, _ in sims)
            exact = sum(1 for s, _ in sims if s >= 0.999)
            self.set_status(
                f"Übereinstimmung (letzte {len(sims)} Ladder-PvP): Ø {avg*100:.0f}% | Best {best*100:.0f}% | exakt {exact}/{len(sims)}"
            )
        else:
            self.set_status("Keine letzten Ladder-PvP-Kämpfe im Battlelog gefunden.")

        self._ensure_history_ui()

        # Reset History
        for r in range(10):
            self.hist_rows[r]["text"].configure(text=f"D{r+1}")
            self.hist_rows[r]["pb"]["value"] = 0
            for c in range(8):
                self.hist_rows[r]["icons"][c].configure(image="", text="")
                self.hist_rows[r]["images"][c] = None

        # Füllen
        for r, rcards in enumerate(recent_cards[:10]):
            pct, inter = sims[r]
            self.hist_rows[r]["text"].configure(text=f"D{r+1}  {pct*100:.0f}% ({inter}/8)")
            self.hist_rows[r]["pb"]["value"] = int(round(pct * 100))

            for c in range(min(8, len(rcards))):
                card = rcards[c] or {}
                url = self._find_card_icon_url(card)
                title = card.get("name", f"K{c+1}")
                lbl = self.hist_rows[r]["icons"][c]
                try:
                    if url:
                        tkimg = self._get_tkimg(url, (72, 86))
                        self.hist_rows[r]["images"][c] = tkimg
                        lbl.configure(image=tkimg, text="")
                    else:
                        lbl.configure(text=title)
                except Exception:
                    lbl.configure(text=title)

        self._set_loading(False)
        self.set_status(f"Deck geladen: {name} {tag} (Letzte {len(recent_cards)} Ladder-PvP Decks)")

    # ------------------------------ Schließen ---------------------------------
    def on_close(self):
        self.stop_scan()
        try:
            self.http.close()
        except Exception:
            pass
        try:
            self.api.close()  # harmless wenn nicht vorhanden
        except Exception:
            pass
        self.destroy()


def main():
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
