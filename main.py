import os
import time
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

# Configura tus límites por ilvl
MAX_PRICES_BY_ILVL = {
    305: 70000,
    308: 50000,
    311: 450000,
}

# Nombres exactos de las piezas BoE
SEARCH_ITEMS = [
    "Grebas de las profundidades nocivas",
    "Yelmo místico de explorador de templos",
    "Faja de Reptaescama",
    "Zapatillas del culto siseante",
    "Espaldares del sacrificio olvidado",
    "Manto de rito venenoso",
    "Almófar de volutador aplastante",
    "Gran cinturón de bruto colmilludo",
    "Ojo de jade de sierpe atada",
]

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
    print("Iniciando búsqueda directa por nombre...")
    token = get_blizzard_token()
    if not token:
        print("Token no disponible.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    found_deals = 0

    for item_name in SEARCH_ITEMS:
        # Búsqueda directa por nombre en la API de subastas
        url = (
            f"https://eu.api.blizzard.com/data/wow/search/connected-realm/index"
            f"?namespace=dynamic-eu&locale=es_ES&name.es_ES={item_name}&_page=1&_orderby=id:asc"
        )
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                print(f"Error {res.status_code} buscando {item_name}")
                continue

            results = res.json().get("results", [])
            print(f"Encontrados {len(results)} registros para '{item_name}'")

            for result in results:
                # Extraemos el precio del resultado
                auctions = result.get("data", {}).get("auctions", [])
                for auction in auctions:
                    buyout = auction.get("buyout", 0) or auction.get("unit_price", 0)
                    price_gold = int(buyout / 10000)

                    # Si el precio entra dentro de nuestros márgenes máximos
                    if 1000 <= price_gold <= max(MAX_PRICES_BY_ILVL.values()):
                        print(f"¡CHOLLO!: {item_name} a {price_gold}g")
                        send_discord_alert(item_name, price_gold)
                        found_deals += 1

        except Exception as e:
            print(f"Error procesando {item_name}: {e}")

    print(f"Escaneo finalizado. Chollos encontrados: {found_deals}")

if __name__ == "__main__":
    check_prices()
