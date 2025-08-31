import os
import sys
import argparse
from dotenv import load_dotenv
from cr_api import (
    ClashAPI,
    resolve_clan_tag_by_name,
    resolve_player_tag_in_clan,
    fmt_player_deck,
)

def main():
    load_dotenv()
    token = os.getenv("CLASH_TOKEN")
    if not token:
        print("Fehlt: CLASH_TOKEN in .env", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Clash Royale Deck Lookup")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_deck = sub.add_parser("deck", help="Aktuelles Deck über Clan- und Spielernamen finden")
    p_deck.add_argument("--clan", required=True, help="Clanname (z. B. Drablibe)")
    p_deck.add_argument("--player", required=True, help="Spielername (z. B. Max Mustermann)")

    args = parser.parse_args()
    api = ClashAPI(token)

    if args.cmd == "deck":
        clan_tag, sugg, clan_disp = resolve_clan_tag_by_name(api, args.clan)
        if not clan_tag:
            print(f"Clan „{args.clan}“ nicht gefunden.")
            if sugg:
                print("Mögliche Treffer:")
                for s in sugg:
                    print("  •", s)
            sys.exit(2)

        ptag, names, best_name = resolve_player_tag_in_clan(api, clan_tag, args.player)
        if not ptag:
            print(f"Spieler „{args.player}“ nicht im Clan {clan_disp or args.clan} gefunden.")
            if names:
                print("Mitglieder (Auszug):")
                for n in names:
                    print("  •", n)
            sys.exit(3)

        pdata = api.get_player(ptag)
        print(fmt_player_deck(pdata, clan_name=clan_disp or args.clan))

if __name__ == "__main__":
    main()
