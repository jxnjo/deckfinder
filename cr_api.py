import os
import time
import httpx
from typing import Dict, Any, List, Tuple, Optional
from urllib.parse import quote
import unicodedata, difflib

CLASH_BASE = "https://api.clashroyale.com/v1"

def _norm(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()

def _best_name_match(candidates: List[str], query: str) -> Optional[str]:
    qn = _norm(query)
    exact = [c for c in candidates if _norm(c) == qn]
    if exact:
        return exact[0]
    if not candidates:
        return None
    # fuzzy fallback
    return difflib.get_close_matches(query, candidates, n=1, cutoff=0.0)[0]

class ClashAPI:
    def __init__(self, token: str, timeout: int = 15):
        self.token = token
        self.timeout = timeout
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def _clan_path(self, clan_tag: str, suffix: str = "") -> str:
        return f"{CLASH_BASE}/clans/%23{clan_tag.lstrip('#').upper()}{suffix}"

    def _player_path(self, player_tag: str) -> str:
        return f"{CLASH_BASE}/players/%23{player_tag.lstrip('#').upper()}"

    def _get(self, url: str, params: Dict[str, Any] | None = None, cache_bust: bool = True) -> Dict[str, Any]:
        headers = {
            **self.headers,
            "Cache-Control": "no-store, max-age=0",
            "Pragma": "no-cache",
        }
        p = dict(params or {})
        if cache_bust:
            p["ts"] = int(time.time() * 1000)
        with httpx.Client(timeout=self.timeout) as client:
            r = client.get(url, headers=headers, params=p)
            # kleine 429/5xx-Retry-Logik
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(1.0)
                r = client.get(url, headers=headers, params=p)
            r.raise_for_status()
            return r.json()

    # --- API Endpoints ---
    def search_clans(self, name: str, limit: int = 20) -> Dict[str, Any]:
        url = f"{CLASH_BASE}/clans?name={quote(name)}&limit={limit}"
        return self._get(url)

    def get_clan_members(self, clan_tag: str) -> Dict[str, Any]:
        return self._get(self._clan_path(clan_tag, "/members"))

    def get_player(self, player_tag: str) -> Dict[str, Any]:
        return self._get(self._player_path(player_tag))

# ---- Resolver/Formatter ----
def resolve_clan_tag_by_name(api: ClashAPI, clan_name: str) -> Tuple[Optional[str], List[str], str]:
    """gibt (tag, vorschlaege, display_name) zurück"""
    res = api.search_clans(clan_name, limit=20)
    items = res.get("items", [])
    if not items:
        return None, [], ""

    exact = [c for c in items if _norm(c.get("name","")) == _norm(clan_name)]
    pool = exact or items
    best = max(pool, key=lambda c: int(c.get("members") or 0))
    tag = (best.get("tag") or "").lstrip("#").upper()
    disp = best.get("name", "?")
    suggestions = [f"{c.get('name','?')} ({c.get('tag','?')})" for c in items[:5]]
    return (tag if tag else None), suggestions, disp

def resolve_player_tag_in_clan(api: ClashAPI, clan_tag: str, player_name: str) -> Tuple[Optional[str], List[str], str]:
    """gibt (player_tag, namensvorschlaege, display_name) zurück"""
    members = api.get_clan_members(clan_tag)
    items = members.get("items", [])
    if not items:
        return None, [], ""

    names = [m.get("name","") for m in items]
    best_name = _best_name_match(names, player_name)
    if not best_name:
        return None, names[:10], ""
    m = next(m for m in items if m.get("name","") == best_name)
    tag = (m.get("tag") or "").lstrip("#").upper()
    return (tag if tag else None), names[:10], best_name

def fmt_player_deck(player_payload: Dict[str, Any], clan_name: str | None = None) -> str:
    pname = player_payload.get("name", "Unbekannt")
    ptag  = player_payload.get("tag", "")
    deck  = player_payload.get("currentDeck") or []

    header = f"🃏 Aktuelles Deck von {pname} {ptag}\n"
    if clan_name:
        header += f"Clan: {clan_name}\n"
    if not deck:
        return header + "Kein aktuelles Deck verfügbar."

    lines = [header]
    for i, card in enumerate(deck, start=1):
        cname = card.get("name", f"Karte {i}")
        lvl   = card.get("level")
        lvl_s = f" (Lvl {lvl})" if lvl is not None else ""
        lines.append(f"{i:>2}. {cname}{lvl_s}")
    return "\n".join(lines)
