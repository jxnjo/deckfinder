# cr_api.py
import time
import httpx
import unicodedata
import difflib
from typing import Any, Dict, List, Tuple, Optional

CLASH_BASE = "https://api.clashroyale.com/v1"


# ------------------------------ String-Utils ---------------------------------
def _norm(s: str) -> str:
    """Klein-/Akzent-normalisieren für robuste Namensvergleiche."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower().strip()


def _best_name_match(candidates: List[str], query: str) -> Optional[str]:
    """Exakt → sonst fuzzy best match über difflib."""
    qn = _norm(query)
    exact = [c for c in candidates if _norm(c) == qn]
    if exact:
        return exact[0]
    if not candidates:
        return None
    return difflib.get_close_matches(query, candidates, n=1, cutoff=0.0)[0]


# --------------------------------- API-Client --------------------------------
class ClashAPI:
    """
    Leichter Wrapper um die Clash Royale API.
    - Persistent httpx.Client mit base_url (vermeidet 'missing protocol'-Fehler)
    - Cache-Busting via ts=... (Millis)
    - Simple Retry bei 429/5xx
    """

    def __init__(self, token: str, timeout: float = 15.0):
        self.timeout = timeout
        self.client = httpx.Client(
            base_url=CLASH_BASE,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
                "User-Agent": "deckfinder/1.0",
            },
        )

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass

    # ---- interne Helfer ----
    @staticmethod
    def _clan_path(clan_tag: str, suffix: str = "") -> str:
        return f"/clans/%23{clan_tag.lstrip('#').upper()}{suffix}"

    @staticmethod
    def _player_path(player_tag: str) -> str:
        return f"/players/%23{player_tag.lstrip('#').upper()}"

    def _get(self, path_or_url: str, params: Optional[Dict[str, Any]] = None, cache_bust: bool = True) -> Any:
        """
        GET mit optionalem Cache-Busting & einfachem Retry.
        `path_or_url` kann relativer Pfad (nutzt base_url) oder volle URL sein.
        """
        p = dict(params or {})
        if cache_bust:
            p["ts"] = int(time.time() * 1000)

        r = self.client.get(path_or_url, params=p)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(1.0)
            r = self.client.get(path_or_url, params=p)

        r.raise_for_status()
        # Einige Endpunkte liefern Listen (z. B. battlelog), andere Dicts → Any zurückgeben
        return r.json()

    # ---- Endpunkte ----
    def search_clans(self, name: str, limit: int = 20) -> Dict[str, Any]:
        return self._get("/clans", params={"name": name, "limit": limit})

    def get_clan_members(self, clan_tag: str) -> Dict[str, Any]:
        return self._get(self._clan_path(clan_tag, "/members"))

    def get_player(self, player_tag: str) -> Dict[str, Any]:
        return self._get(self._player_path(player_tag))

    def get_battlelog(self, player_tag: str) -> List[Dict[str, Any]]:
        return self._get(self._player_path(player_tag) + "/battlelog")


# ----------------------------- Resolver/Formatter -----------------------------
def resolve_clan_tag_by_name(api: ClashAPI, clan_name: str) -> Tuple[Optional[str], List[str], str]:
    """
    Sucht Clans per Name.
    Rückgabe: (tag, vorschlaege, display_name)
    """
    res = api.search_clans(clan_name, limit=20)
    items = res.get("items", [])
    if not items:
        return None, [], ""

    # Exakte Normalisierung bevorzugen, sonst bestes (meist größtes) Ergebnis
    exact = [c for c in items if _norm(c.get("name", "")) == _norm(clan_name)]
    pool = exact or items
    best = max(pool, key=lambda c: int(c.get("members") or 0))

    tag = (best.get("tag") or "").lstrip("#").upper()
    disp = best.get("name", "?")
    suggestions = [f"{c.get('name','?')} ({c.get('tag','?')})" for c in items[:5]]
    return (tag if tag else None), suggestions, disp


def resolve_player_tag_in_clan(api: ClashAPI, clan_tag: str, player_name: str) -> Tuple[Optional[str], List[str], str]:
    """
    Findet den Player-Tag in einem Clan über den (ggf. fuzzy) Spielernamen.
    Rückgabe: (player_tag, namensvorschlaege, display_name)
    """
    members = api.get_clan_members(clan_tag)
    items = members.get("items", [])
    if not items:
        return None, [], ""

    names = [m.get("name", "") for m in items]
    best_name = _best_name_match(names, player_name)
    if not best_name:
        return None, names[:10], ""

    m = next(m for m in items if m.get("name", "") == best_name)
    tag = (m.get("tag") or "").lstrip("#").upper()
    return (tag if tag else None), names[:10], best_name


def fmt_player_deck(player_payload: Dict[str, Any], clan_name: Optional[str] = None) -> str:
    """Einfaches Text-Format des aktuellen Decks eines Spielers."""
    pname = player_payload.get("name", "Unbekannt")
    ptag = player_payload.get("tag", "")
    deck = player_payload.get("currentDeck") or []

    header = f"🃏 Aktuelles Deck von {pname} {ptag}\n"
    if clan_name:
        header += f"Clan: {clan_name}\n"
    if not deck:
        return header + "Kein aktuelles Deck verfügbar."

    lines = [header]
    for i, card in enumerate(deck, start=1):
        cname = card.get("name", f"Karte {i}")
        lvl = card.get("level")
        lvl_s = f" (Lvl {lvl})" if lvl is not None else ""
        lines.append(f"{i:>2}. {cname}{lvl_s}")
    return "\n".join(lines)


# ------------------------ Deck-Analyse (Battlelog) ----------------------------
def _norm_tag(tag: str) -> str:
    return (tag or "").strip().upper().lstrip("#")


def _deck_keys(deck_cards: List[Dict[str, Any]]) -> List[str]:
    """Extrahiert robuste Karten-Keys pro Karte (id/key/name), lower-case."""
    keys: List[str] = []
    for c in deck_cards or []:
        cid = c.get("id") or c.get("key") or c.get("name")
        if cid is not None:
            keys.append(str(cid).lower())
    return keys


def _deck_similarity(cur_keys: List[str], hist_keys: List[str]) -> float:
    """Anteil gleicher Karten bezogen auf 8 Slots (0.0–1.0)."""
    if not cur_keys or not hist_keys:
        return 0.0
    a, b = set(cur_keys), set(hist_keys)
    return len(a & b) / 8.0


def extract_player_cards_from_battle(battle: Dict[str, Any], player_tag: str) -> List[Dict[str, Any]]:
    """Findet die Karten des Spielers in einem Battlelog-Eintrag (team/opponent)."""
    pt = _norm_tag(player_tag)
    for side in ("team", "opponent"):
        for pl in (battle.get(side) or []):
            if _norm_tag(pl.get("tag")) == pt:
                return pl.get("cards") or []
    return []


def last_n_decks_from_battlelog(battles: List[Dict[str, Any]], player_tag: str, n: int = 5) -> List[List[str]]:
    """Gibt bis zu n vergangene Decks (als Karten-Keys) aus dem Battlelog zurück."""
    decks: List[List[str]] = []
    for b in battles:
        cards = extract_player_cards_from_battle(b, player_tag)
        if cards:
            decks.append(_deck_keys(cards))
        if len(decks) >= n:
            break
    return decks


def deck_match_report(current_deck: List[Dict[str, Any]], recent_decks_keys: List[List[str]]) -> Dict[str, Any]:
    """
    current_deck: Liste von Kartenobjekten aus player['currentDeck']
    recent_decks_keys: Liste von Key-Listen, wie von last_n_decks_from_battlelog()
    Rückgabe: {'count', 'avg', 'best', 'exact'}
    """
    cur = _deck_keys(current_deck)
    if not recent_decks_keys:
        return {"count": 0, "avg": 0.0, "best": 0.0, "exact": 0}
    sims = [_deck_similarity(cur, hist) for hist in recent_decks_keys]
    exact = sum(1 for s in sims if s >= 0.999)
    return {
        "count": len(sims),
        "avg": (sum(sims) / len(sims)) if sims else 0.0,
        "best": max(sims) if sims else 0.0,
        "exact": exact,
    }
