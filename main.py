import os
import time
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

# Límites máximos por ilvl (en oro)
MAX_PRICES_BY_ILVL = {
    305: 70000,
    308: 50000,
    311: 450000,
}

# Nombres exactos en inglés según la captura
SEARCH_ITEMS = {
    "Greaves of the Noxious Depths": 210817,
    "Temple Delver's Mystic Helm": 210818,
    "Slitherscale Girdle": 210819,
    "Slippers of the Hissing Cult": 210820,
    "Pauldrons of the Forgotten Sacrifice": 210821,
    "Venom Rite Mantle": 210822,
    "Crushing Coiler Coif": 210823,
    "Fanged Brute's Greatbelt": 210824,
    "Bound Serpent's Jade Eye": 210825,
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
        print(f"Error obteniendo token: {e}")
    return None

def send_discord_alert(item_name, price_gold):
    if not DISCORD_WEBHOOK_URL:
        return
    msg = (
        f"🚨 **¡CHOLLO DETECTADO EN EU!** 🚨\n"
        f"**Objeto:** {item_name}\n"
        f"**Precio:** {price_gold:,} oro\n"
        f"-----------------------------------"
    )
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    time.sleep(1)

def check_prices():
    print("Iniciando escaneo por nombre en inglés...")
    token = get_blizzard_token()
    if not token:
        print("Token no disponible.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    
    # Obtenemos las subastas del macrorreino 1305
    url = "https://eu.api.blizzard.com/data/wow/connected-realm/1305/auctions?namespace=dynamic-eu&locale=en_GB"

    try:
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code != 200:
            print(f"Error {res.status_code} al consultar Blizzard.")
            return

        auctions = res.json().get("auctions", [])
        print(f"Analizando {len(auctions)} subastas del reino...")

        target_ids = set(SEARCH_ITEMS.values())
        id_to_name = {v: k for k, v in SEARCH_ITEMS.items()}
        found_deals = 0

        for auction in auctions:
            item_id = auction.get("item", {}).get("id")

            if item_id in target_ids:
                buyout = auction.get("buyout", 0) or auction.get("unit_price", 0)
                price_gold = int(buyout / 10000)
                item_name = id_to_name[item_id]

                # Aplicamos el filtro con el límite global máximo (70k para 305, etc.)
                if 1000 <= price_gold <= max(MAX_PRICES_BY_ILVL.values()):
                    print(f"¡CHOLLO DETECTADO!: {item_name} por {price_gold}g")
                    send_discord_alert(item_name, price_gold)
                    found_deals += 1

        print(f"Escaneo finalizado. Chollos informados: {found_deals}")

    except Exception as e:
        print(f"Excepción: {e}")

if __name__ == "__main__":
    check_prices()
