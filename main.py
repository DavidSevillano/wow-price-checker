import os
import time
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

MAX_ALERT_PRICE_GOLD = 100000

# Nombres en inglés que queremos buscar
TARGET_NAMES = {
    "greaves of the noxious depths",
    "temple delver's mystic helm",
    "slitherscale girdle",
    "slippers of the hissing cult",
    "pauldrons of the forgotten sacrifice",
    "venom rite mantle",
    "crushing coiler coif",
    "fanged brute's greatbelt",
    "bound serpent's jade eye",
}

# Caché en memoria para no pedir el nombre del mismo item varias veces
ITEM_NAME_CACHE = {}

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

def get_item_name(item_id, headers):
    """Consulta a la API de Blizzard el nombre real de cualquier ID desconocida."""
    if item_id in ITEM_NAME_CACHE:
        return ITEM_NAME_CACHE[item_id]

    url = f"https://eu.api.blizzard.com/data/wow/item/{item_id}?namespace=static-eu&locale=en_GB"
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            name = res.json().get("name", "")
            ITEM_NAME_CACHE[item_id] = name
            return name
    except Exception:
        pass
    
    ITEM_NAME_CACHE[item_id] = None
    return None

def send_discord_alert(item_name, price_gold, realm_id):
    if not DISCORD_WEBHOOK_URL:
        return
    msg = (
        f"🚨 **¡CHOLLO DETECTADO!** 🚨\n"
        f"**Objeto:** {item_name}\n"
        f"**Precio:** {price_gold:,} oro\n"
        f"**ID Reino:** {realm_id}\n"
        f"-----------------------------------"
    )
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})

def check_prices():
    token = get_blizzard_token()
    if not token:
        print("❌ Token no disponible.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    main_realms = [1305, 1403, 581, 1303, 1402]
    
    print(f"Buscando objetos por nombre real en {len(main_realms)} reinos...\n")
    total_found = 0

    for realm_id in main_realms:
        url = f"https://eu.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions?namespace=dynamic-eu&locale=en_GB"
        print(f"🔍 Escaneando reino {realm_id}...")

        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code != 200:
                continue

            auctions = res.json().get("auctions", [])
            print(f"   ↳ Subastas analizadas: {len(auctions)}")

            for auction in auctions:
                buyout = auction.get("buyout", 0) or auction.get("unit_price", 0)
                price_gold = int(buyout / 10000)

                # Solo inspeccionamos objetos cuyo precio sea relevante para ahorrar peticiones
                if 1000 <= price_gold <= MAX_ALERT_PRICE_GOLD:
                    item_id = auction.get("item", {}).get("id")
                    item_name = get_item_name(item_id, headers)

                    if item_name and item_name.lower() in TARGET_NAMES:
                        print(f"  🎯 ¡MATCH ENCONTRADO!: {item_name} a {price_gold}g en Realm {realm_id}")
                        send_discord_alert(item_name, price_gold, realm_id)
                        total_found += 1

        except Exception as e:
            print(f"❌ Error en reino {realm_id}: {e}")

        time.sleep(1)

    print(f"\nEscaneo finalizado. Total chollos detectados: {total_found}")

if __name__ == "__main__":
    check_prices()
