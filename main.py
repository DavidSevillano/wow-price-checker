import os
import time
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

# Límites máximos permitidos por ilvl real (en oro)
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

# Mapa de bonus_list IDs conocidos de Blizzard a su incremento o ilvl exacto
# Para ítems de raid BoE, si no hay bonus especial se asume el ilvl base de la dificultad
BONUS_ILVL_MAP = {
    # Mapeo estándar de bonus IDs a ilvls/modificadores
    10887: 298,
    10888: 305,
    10889: 308,
    10890: 311,
}

ITEM_DATA_CACHE = {}
REALM_NAME_CACHE = {}

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
    url = "https://eu.api.blizzard.com/data/wow/connected-realm/index?namespace=dynamic-eu&locale=en_GB"
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            realms_data = res.json().get("connected_realms", [])
            return [int(r["href"].split("connected-realm/")[1].split("?")[0]) for r in realms_data]
    except Exception as e:
        print(f"❌ Error obteniendo lista de reinos: {e}")
    return [1305, 1403, 581, 1303, 1402]

def get_realm_name(realm_id, headers):
    if realm_id in REALM_NAME_CACHE:
        return REALM_NAME_CACHE[realm_id]

    url = f"https://eu.api.blizzard.com/data/wow/connected-realm/{realm_id}?namespace=dynamic-eu&locale=en_GB"
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            realms = res.json().get("realms", [])
            names = [r.get("name") for r in realms if r.get("name")]
            full_name = " / ".join(names) if names else f"Reino {realm_id}"
            REALM_NAME_CACHE[realm_id] = full_name
            return full_name
    except Exception:
        pass

    fallback = f"Reino {realm_id}"
    REALM_NAME_CACHE[realm_id] = fallback
    return fallback

def get_item_base_data(item_id, headers):
    """Obtiene el nombre en inglés del objeto."""
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
    """Calcula el ilvl real del objeto inspeccionando sus bonus_lists."""
    bonus_lists = item_data.get("bonus_lists", [])
    
    # 1. Buscar coincidencia directa de bonus conocidos
    for b_id in bonus_lists:
        if b_id in BONUS_ILVL_MAP:
            return BONUS_ILVL_MAP[b_id]

    # 2. Si no encuentra bonus conocidos, intenta extraer modificadores de contexto
    modifiers = item_data.get("modifiers", [])
    for mod in modifiers:
        if mod.get("type") == 9: # Type 9 suele representar el nivel de objeto forzado
            return mod.get("value", base_ilvl)

    # 3. Fallback: Si no tiene bonus registrados que alteren nivel, devolver el base
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

def check_prices():
    token = get_blizzard_token()
    if not token:
        print("❌ Token no disponible.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    all_realms = get_all_eu_connected_realms(headers)
    print(f"Escaneando {len(all_realms)} reinos de Europa...\n")

    max_global_price = max(MAX_PRICES_BY_ILVL.values())
    total_found = 0

    for realm_id in all_realms:
        realm_name = get_realm_name(realm_id, headers)
        url = f"https://eu.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions?namespace=dynamic-eu&locale=en_GB"

        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue

            auctions = res.json().get("auctions", [])

            for auction in auctions:
                buyout = auction.get("buyout", 0) or auction.get("unit_price", 0)
                price_gold = int(buyout / 10000)

                # Comprobación de precio antes de hacer consultas HTTP
                if 1000 <= price_gold <= max_global_price:
                    item_obj = auction.get("item", {})
                    item_id = item_obj.get("id")
                    
                    item_name, base_ilvl = get_item_base_data(item_id, headers)

                    if item_name and item_name.lower() in TARGET_NAMES:
                        # Calcular el ilvl real del ítem instanciado
                        real_ilvl = calculate_real_ilvl(item_obj, base_ilvl)

                        # Verificar si el precio entra en el tope para su ilvl
                        max_allowed = MAX_PRICES_BY_ILVL.get(real_ilvl, max_global_price)

                        if price_gold <= max_allowed:
                            print(f"  🎯 ¡CHOLLO!: {item_name} (ilvl {real_ilvl}) por {price_gold}g en {realm_name}")
                            send_discord_alert(item_name, price_gold, realm_name, real_ilvl)
                            total_found += 1

        except Exception as e:
            print(f"❌ Error en reino {realm_id}: {e}")

        time.sleep(0.3)

    print(f"\nEscaneo finalizado. Total chollos detectados: {total_found}")

if __name__ == "__main__":
    check_prices()
