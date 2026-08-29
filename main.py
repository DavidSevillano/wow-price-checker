import os
import requests
from concurrent.futures import ThreadPoolExecutor

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

# Límites máximos por ilvl (en oro)
MAX_PRICES_BY_ILVL = {
    298: 9999,
    305: 70000,
    308: 50000,
    311: 450000,
}

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

ITEM_DATA_CACHE = {}

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

def get_all_eu_connected_realms(headers):
    """Obtiene rápidamente la lista de IDs de reinos conectados."""
    url = "https://eu.api.blizzard.com/data/wow/connected-realm/index?namespace=dynamic-eu&locale=en_GB"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            realms_data = res.json().get("connected_realms", [])
            return [int(r["href"].split("connected-realm/")[1].split("?")[0]) for r in realms_data]
    except Exception as e:
        print(f"❌ Error reinos: {e}")
    return [1305, 1403, 581, 1303, 1402]

def get_item_base_data(item_id, headers):
    if item_id in ITEM_DATA_CACHE:
        return ITEM_DATA_CACHE[item_id]

    url = f"https://eu.api.blizzard.com/data/wow/item/{item_id}?namespace=static-eu&locale=en_GB"
    try:
        res = requests.get(url, headers=headers, timeout=3)
        if res.status_code == 200:
            data = res.json()
            name = data.get("name", "")
            base_ilvl = data.get("level", 0)
            result = (name, base_ilvl)
            ITEM_DATA_CACHE[item_id] = result
            return result
    except Exception:
        pass
    
    ITEM_DATA_CACHE[item_id] = (None, 0)
    return (None, 0)

def calculate_real_ilvl(item_data, base_ilvl):
    modifiers = item_data.get("modifiers", [])
    for mod in modifiers:
        if mod.get("type") == 9:
            return mod.get("value", base_ilvl)

    return 305 if base_ilvl > 0 else base_ilvl

def send_discord_alert(item_name, price_gold, realm_id, ilvl):
    if not DISCORD_WEBHOOK_URL:
        return
    msg = (
        f"🚨 **¡CHOLLO DETECTADO EN EU!** 🚨\n"
        f"**Objeto:** {item_name} (ilvl {ilvl})\n"
        f"**Precio:** {price_gold:,} oro\n"
        f"**Reino ID:** {realm_id}\n"
        f"-----------------------------------"
    )
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})

def scan_realm(realm_id, headers, max_global_price):
    """Escanea un reino individual de forma independiente para ejecución paralela."""
    url = f"https://eu.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions?namespace=dynamic-eu&locale=en_GB"
    found_count = 0

    try:
        res = requests.get(url, headers=headers, timeout=8)
        if res.status_code != 200:
            return 0

        auctions = res.json().get("auctions", [])

        for auction in auctions:
            buyout = auction.get("buyout", 0) or auction.get("unit_price", 0)
            price_gold = int(buyout / 10000)

            if 1000 <= price_gold <= max_global_price:
                item_obj = auction.get("item", {})
                item_id = item_obj.get("id")
                
                item_name, base_ilvl = get_item_base_data(item_id, headers)

                if item_name and item_name.lower() in TARGET_NAMES:
                    real_ilvl = calculate_real_ilvl(item_obj, base_ilvl)
                    max_allowed = MAX_PRICES_BY_ILVL.get(real_ilvl, MAX_PRICES_BY_ILVL[305])

                    if price_gold <= max_allowed:
                        print(f"  🎯 ¡MATCH!: {item_name} (ilvl {real_ilvl}) por {price_gold}g en Reino ID {realm_id}")
                        send_discord_alert(item_name, price_gold, realm_id, real_ilvl)
                        found_count += 1

    except Exception:
        pass

    return found_count

def check_prices():
    token = get_blizzard_token()
    if not token:
        print("❌ Token no disponible.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    all_realms = get_all_eu_connected_realms(headers)
    print(f"🚀 Escaneando los {len(all_realms)} reinos de EU en paralelo...")

    max_global_price = max(MAX_PRICES_BY_ILVL.values())

    # Usar 15 hilos concurrentes para procesar Europa en segundos
    with ThreadPoolExecutor(max_workers=15) as executor:
        results = list(executor.map(lambda r_id: scan_realm(r_id, headers, max_global_price), all_realms))

    total_found = sum(results)
    print(f"\n✅ Escaneo completado. Total chollos enviados: {total_found}")

if __name__ == "__main__":
    check_prices()
