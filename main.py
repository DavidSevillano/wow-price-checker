import os
import time
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

MAX_PRICES_BY_ILVL = {
    305: 80000,
    308: 50000,
    311: 450000,
}

# IDs de los objetos a monitorear
WATCHED_ITEM_IDS = [210817, 210818, 210819, 210820, 210821, 210822, 210823, 210824, 210825]

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
        print(f"Error obteniendo token de Blizzard: {response.status_code}")
    except Exception as e:
        print(f"Excepción al autenticar con Blizzard: {e}")
    return None

def send_discord_alert(message_text):
    if not DISCORD_WEBHOOK_URL:
        return
    requests.post(DISCORD_WEBHOOK_URL, json={"content": message_text})
    time.sleep(1)

def check_prices():
    print("Iniciando escaneo con API de Blizzard...")
    token = get_blizzard_token()
    if not token:
        print("No se pudo obtener el token. Cancelando escaneo.")
        return

    # Usamos la subasta conectada de EU (Commodities/AH Regional)
    headers = {"Authorization": f"Bearer {token}"}
    url = "https://eu.api.blizzard.com/data/wow/auctions/commodities?namespace=dynamic-eu&locale=en_US"

    try:
        print("Descargando archivo de subastas de EU...")
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code != 200:
            print(f"Error {res.status_code} al descargar subastas de Blizzard.")
            return

        auctions = res.json().get("auctions", [])
        print(f"Subastas totales descargadas: {len(auctions)}. Filtrando objetos...")

        found_deals = 0
        for auction in auctions:
            item_id = auction.get("item", {}).get("id")

            if item_id in WATCHED_ITEM_IDS:
                # Comprobar si tiene el modificador de ilvl
                bonus_lists = auction.get("item", {}).get("bonus_lists", [])
                
                # Obtener buyout (en cobre, convertir a oro)
                unit_price = auction.get("unit_price", 0) or auction.get("buyout", 0)
                price_gold = int(unit_price / 10000)

                # Si el precio cumple con nuestros límites globales
                if price_gold > 0 and price_gold <= max(MAX_PRICES_BY_ILVL.values()):
                    msg = (
                        f"🚨 **¡CHOLLO DETECTADO EN EU!** 🚨\n"
                        f"**ID del Objeto:** {item_id}\n"
                        f"**Precio:** {price_gold:,} oro\n"
                        f"-----------------------------------"
                    )
                    print(f"¡CHOLLO!: ID {item_id} por {price_gold}g")
                    send_discord_alert(msg)
                    found_deals += 1

        print(f"Escaneo finalizado. Chollos encontrados e informados: {found_deals}")

    except Exception as e:
        print(f"Excepción procesando datos de Blizzard: {e}")

if __name__ == "__main__":
    check_prices()
