import os
import time
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

# Límite máximo general para alertas (en oro)
MAX_ALERT_PRICE_GOLD = 100000

# IDs base esperadas
TARGET_IDS = {210817, 210818, 210819, 210820, 210821, 210822, 210823, 210824, 210825}

# Mapeo descriptivo para las alertas
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
        print(f"Error obteniendo token: {e}")
    return None

def get_all_eu_connected_realms(headers):
    """Obtiene automáticamente la lista completa de reinos conectados de la región EU."""
    url = "https://eu.api.blizzard.com/data/wow/connected-realm/index?namespace=dynamic-eu&locale=en_GB"
    try:
        res = requests.get(url, headers=headers, timeout=15)
        if res.status_code == 200:
            realms_data = res.json().get("connected_realms", [])
            # Extraemos la ID del conectado de cada URL devuelta
            realm_ids = [int(r["href"].split("connected-realm/")[1].split("?")[0]) for r in realms_data]
            return realm_ids
    except Exception as e:
        print(f"Error obteniendo lista de reinos: {e}")
    
    # Lista fallback de reinos principales si falla el índice
    return [1305, 1301, 1303, 1403, 581, 1329, 1402]

def send_discord_alert(item_name, price_gold, realm_id):
    if not DISCORD_WEBHOOK_URL:
        return
    msg = (
        f"🚨 **¡CHOLLO DETECTADO EN EU!** 🚨\n"
        f"**Objeto:** {item_name}\n"
        f"**Precio:** {price_gold:,} oro\n"
        f"**ID Reino Conectado:** {realm_id}\n"
        f"-----------------------------------"
    )
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    time.sleep(1)

def check_prices():
    token = get_blizzard_token()
    if not token:
        print("Token no disponible.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    
    print("Obteniendo todos los reinos conectados de EU...")
    connected_realms = get_all_eu_connected_realms(headers)
    print(f"Se escanearán {len(connected_realms)} reinos conectados en total.\n")

    total_deals = 0

    for realm_id in connected_realms:
        url = f"https://eu.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions?namespace=dynamic-eu&locale=en_GB"
        
        try:
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code != 200:
                continue

            auctions = res.json().get("auctions", [])

            for auction in auctions:
                item_info = auction.get("item", {})
                item_id = item_info.get("id")

                # Comprobación de la ID base
                if item_id in TARGET_IDS:
                    buyout = auction.get("buyout", 0) or auction.get("unit_price", 0)
                    price_gold = int(buyout / 10000)
                    item_name = ITEM_NAMES.get(item_id, f"Item {item_id}")

                    print(f"¡ENCONTRADO MATCH! {item_name} a {price_gold}g en Realm {realm_id}")

                    if 1000 <= price_gold <= MAX_ALERT_PRICE_GOLD:
                        send_discord_alert(item_name, price_gold, realm_id)
                        total_deals += 1

        except Exception as e:
            continue

    print(f"\nEscaneo completo finalizado. Chollos informados: {total_deals}")

if __name__ == "__main__":
    check_prices()
