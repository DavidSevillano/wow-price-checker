import os
import time
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

# IDs base
TARGET_IDS = {210817, 210818, 210819, 210820, 210821, 210822, 210823, 210824, 210825}

ITEM_NAMES = {
    210817: "Greaves of the Noxious Depths",
    210818: "Temple Delver's Mystic Helm",
    210819: "Slitherscale Girdle",
    210820: "Slippers of the Hissing Cult",
    210821: "Pauldrons of the Forgotten Sacrifice",
    210822: "Venom Rite Mantle",
    210823: "Crushing Coiler Coif",
    210824: "Fanged Brute's Greatbelt",
    210825: "Bound Serpent's Jade Eye",
}

def get_blizzard_token():
    url = "https://oauth.battle.net/token"
    try:
        response = requests.post(
            url, 
            data={"grant_type": "client_credentials"}, 
            auth=(CLIENT_ID, CLIENT_SECRET),
            timeout=10
        )
        if response.status_code == 200:
            return response.json().get("access_token")
    except Exception as e:
        print(f"❌ Error token: {e}")
    return None

def send_discord_alert(item_name, price_gold, realm_id):
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ No hay DISCORD_WEBHOOK_URL configurada.")
        return
    msg = (
        f"🚨 **[TEST LOG] ¡OBJETO ENCONTRADO!** 🚨\n"
        f"**Objeto:** {item_name}\n"
        f"**Precio:** {price_gold:,} oro\n"
        f"**ID Reino:** {realm_id}\n"
        f"-----------------------------------"
    )
    res = requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    print(f"-> Discord status code: {res.status_code}")

def check_prices():
    token = get_blizzard_token()
    if not token:
        print("❌ Token no disponible.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    
    # Probamos únicamente en los 5 reinos más grandes de EU para evitar Rate Limit
    main_realms = [1305, 1403, 581, 1303, 1402]
    
    print(f"Iniciando escaneo controlado en {len(main_realms)} reinos de EU...\n")
    total_found = 0

    for realm_id in main_realms:
        url = f"https://eu.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions?namespace=dynamic-eu&locale=en_GB"
        print(f"🔍 Consultando reino {realm_id}...")

        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 429:
                print(f"⚠️ Rate limit (429) alcanzado en reino {realm_id}. Esperando 5s...")
                time.sleep(5)
                continue
            elif res.status_code != 200:
                print(f"❌ Error HTTP {res.status_code} en reino {realm_id}")
                continue

            auctions = res.json().get("auctions", [])
            print(f"   ↳ Subastas obtenidas: {len(auctions)}")

            for auction in auctions:
                item_id = auction.get("item", {}).get("id")

                if item_id in TARGET_IDS:
                    buyout = auction.get("buyout", 0) or auction.get("unit_price", 0)
                    price_gold = int(buyout / 10000)
                    item_name = ITEM_NAMES.get(item_id, f"Item {item_id}")

                    print(f"  MATCH ENCONTRADO: {item_name} a {price_gold}g en Realm {realm_id}")
                    send_discord_alert(item_name, price_gold, realm_id)
                    total_found += 1

        except Exception as e:
            print(f"❌ Excepción en realm {realm_id}: {e}")

        # Pausa para respetar la cuota de la API
        time.sleep(1)

    print(f"\nEscaneo finalizado. Total objetos detectados: {total_found}")

if __name__ == "__main__":
    check_prices()
