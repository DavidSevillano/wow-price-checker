import os
import time
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

# Límite máximo de alerta por precio (en oro)
MAX_ALERT_PRICE_GOLD = 100000

# Diccionario de reinos a escanear: ID de realm -> Nombre legible
REALMS_TO_SCAN = {
    1305: "EU - Macrorreino Español (Dun Modr/Sanguino/C'Thun)",
    1301: "EU - Outland",
    1399: "EU - Rag",
    1303: "EU - Tarren Mill",
    1403: "EU - Draenor",
    1300: "EU - Frostmane",
    581:  "EU - Kazzak",
    1329: "EU - Ravencrest",
    1402: "EU - Silvermoon",
}

# Objetos objetivo con su ID numérica de la API
TARGET_ITEMS = {
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

def send_discord_alert(item_name, price_gold, realm_name):
    if not DISCORD_WEBHOOK_URL:
        return
    msg = (
        f"🚨 **¡CHOLLO DETECTADO!** 🚨\n"
        f"**Objeto:** {item_name}\n"
        f"**Precio:** {price_gold:,} oro\n"
        f"**Reino:** {realm_name}\n"
        f"-----------------------------------"
    )
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    time.sleep(1)

def check_prices():
    print("Iniciando escaneo multirreino...")
    token = get_blizzard_token()
    if not token:
        print("Token no disponible.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    total_deals = 0

    for realm_id, realm_name in REALMS_TO_SCAN.items():
        url = f"https://eu.api.blizzard.com/data/wow/connected-realm/{realm_id}/auctions?namespace=dynamic-eu&locale=en_GB"
        
        try:
            res = requests.get(url, headers=headers, timeout=20)
            if res.status_code != 200:
                print(f"Error {res.status_code} escaneando {realm_name}")
                continue

            auctions = res.json().get("auctions", [])
            print(f"Escaneando {realm_name} ({len(auctions)} subastas)...")

            for auction in auctions:
                item_info = auction.get("item", {})
                item_id = item_info.get("id")

                if item_id in TARGET_ITEMS:
                    buyout = auction.get("buyout", 0) or auction.get("unit_price", 0)
                    price_gold = int(buyout / 10000)

                    # Filtramos por precio mínimo razonable (evita recetas de 99g) y máximo fijado
                    if 1000 <= price_gold <= MAX_ALERT_PRICE_GOLD:
                        item_name = TARGET_ITEMS[item_id]
                        print(f"¡CHOLLO ENCONTRADO! {item_name} por {price_gold}g en {realm_name}")
                        send_discord_alert(item_name, price_gold, realm_name)
                        total_deals += 1

        except Exception as e:
            print(f"Error en el reino {realm_name}: {e}")

    print(f"Escaneo finalizado. Chollos totales notificados: {total_deals}")

if __name__ == "__main__":
    check_prices()
