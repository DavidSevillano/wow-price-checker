import os
import requests
from concurrent.futures import ThreadPoolExecutor

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

# Límites máximos por ilvl real (en oro)
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

# Tabla de conversión exacta de Bonus IDs de WoW a su ilvl real
BONUS_TO_ILVL = {
    10887: 298,
    10888: 305,
    10889: 308,
    10890: 311,
}

ITEM_DATA_CACHE = {}
REALM_NAMES_CACHE = {}

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

def fetch_all_realm_names(headers):
    """Carga los nombres de todos los reinos conectados de EU antes de escanear."""
    url = "https://eu.api.blizzard.com/data/wow/connected-realm/index?namespace=dynamic-eu&locale=en_GB"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            realms_data = res.json().get("connected_realms", [])
            for r in realms_data:
                r_id = int(r["href"].split("connected-realm/")[1].split("?")[0])
                # Petición rápida para mapear el nombre del reino
                try:
                    r_res = requests.get(f"https://eu.api.blizzard.com/data/wow/connected-realm/{r_id}?namespace=dynamic-eu&locale=en_GB", headers=headers, timeout=3)
                    if r_res.status_code == 200:
                        names = [realm.get("name") for realm in r_res.json().get("realms", []) if realm.get("name")]
                        REALM_NAMES_CACHE[r_id] = " / ".join(names) if names else f"Reino {r_id}"
                except Exception:
                    REALM_NAMES_CACHE[r_id] = f"Reino {r_id}"
    except Exception as e:
        print(f"❌ Error al cargar reinos: {e}")

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

def extract_exact_ilvl(item_obj, base_ilvl):
    """Lee las bonus_lists de la subasta para extraer el ilvl exacto sin asumir nada."""
    # 1. Comprobar si incluye modificador directo de nivel (Type 9)
    modifiers = item_obj.get("modifiers", [])
    for mod in modifiers:
        if mod.get("type") == 9:
            return mod.get("value")

    # 2. Comprobar tabla de bonus_lists
    bonus_lists = item_obj.get("bonus_lists", [])
    for b_id in bonus_lists:
        if b_id in BONUS_TO_ILVL:
            return BONUS_TO_ILVL[b_id]

    # 3. Si no trae ningún bono de escalado, devolver el ilvl base o descartar
    return base_ilvl if base_ilvl > 250 else 298

def send_discord_alert(item_name, price_gold, realm_name, ilvl):
    if not DISCORD_WEBHOOK_URL:
        return
    msg = (
        f"🚨 **¡CHOLLO DETECTADO EN EU!** 🚨\n"
        f"**Objeto:** {item_name} (ilvl {ilvl})\n"
        f"**Precio:** {price_gold:,} oro\n"
        f"**Reino:** {realm_name}\n"
        f"-----------------------------------"
    )
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})

def scan_realm(realm_id, headers, max_global_price):
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
                    exact_ilvl = extract_exact_ilvl(item_obj, base_ilvl)
                    
                    # Validar si este ilvl exacto tiene regla de precio fijada
                    if exact_ilvl in MAX_PRICES_BY_ILVL:
                        max_allowed = MAX_PRICES_BY_ILVL[exact_ilvl]

                        if price_gold <= max_allowed:
                            realm_name = REALM_NAMES_CACHE.get(realm_id, f"Reino {realm_id}")
                            print(f"  🎯 ¡CHOLLO REAL!: {item_name} (ilvl {exact_ilvl}) por {price_gold}g en {realm_name}")
                            send_discord_alert(item_name, price_gold, realm_name, exact_ilvl)
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
    
    print("⏳ Cargando nombres de reinos...")
    fetch_all_realm_names(headers)
    all_realms = list(REALM_NAMES_CACHE.keys())
    
    print(f"🚀 Escaneando los {len(all_realms)} reinos de EU en paralelo...")
    max_global_price = max(MAX_PRICES_BY_ILVL.values())

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda r_id: scan_realm(r_id, headers, max_global_price), all_realms))

    total_found = sum(results)
    print(f"\n✅ Escaneo completado. Total chollos enviados: {total_found}")

if __name__ == "__main__":
    check_prices()
