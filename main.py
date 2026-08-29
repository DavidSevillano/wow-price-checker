import os
import time
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

MAX_PRICES_BY_ILVL = {
    305: 70000,
    308: 50000,
    311: 450000,
}

ITEMS_TO_WATCH = {
    210817: "Grebas de las profundidades nocivas",
    210818: "Yelmo místico de explorador de templos",
    210819: "Faja de Reptaescama",
    210820: "Zapatillas del culto siseante",
    210821: "Espaldares del sacrificio olvidado",
    210822: "Manto de rito venenoso",
    210823: "Almófar de volutador aplastante",
    210824: "Gran cinturón de bruto colmilludo",
    210825: "Ojo de jade de sierpe atada",
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

def extract_ilvl(item_info):
    # En la API de Blizzard, los modificadores de tipo 9 indican el nivel de objeto dinámico
    modifiers = item_info.get("modifiers", [])
    for mod in modifiers:
        if mod.get("type") == 9:
            return mod.get("value")
    
    # Si no tiene modificador explícito de ilvl, no es una pieza equipable válida
    return None

def send_discord_alert(item_name, ilvl, price_gold):
    if not DISCORD_WEBHOOK_URL:
        return
    msg = (
        f"🚨 **¡CHOLLO DETECTADO EN EU!** 🚨\n"
        f"**Objeto:** {item_name} (ilvl {ilvl})\n"
        f"**Precio:** {price_gold:,} oro\n"
        f"-----------------------------------"
    )
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    time.sleep(1)

def check_prices():
    print("Iniciando escaneo dinámico...")
    token = get_blizzard_token()
    if not token:
        print("Token no disponible.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    
    # Consultamos las subastas del macrorreino 1305
    url = "https://eu.api.blizzard.com/data/wow/connected-realm/1305/auctions?namespace=dynamic-eu&locale=es_ES"

    try:
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code != 200:
            print(f"Error {res.status_code} al consultar Blizzard.")
            return

        auctions = res.json().get("auctions", [])
        print(f"Analizando {len(auctions)} subastas totales...")
        found_deals = 0

        for auction in auctions:
            item_info = auction.get("item", {})
            item_id = item_info.get("id")

            if item_id in ITEMS_TO_WATCH:
                ilvl = extract_ilvl(item_info)

                # Si el ilvl detectado coincide exactamente con nuestras reglas
                if ilvl in MAX_PRICES_BY_ILVL:
                    buyout = auction.get("buyout", 0) or auction.get("unit_price", 0)
                    price_gold = int(buyout / 10000)
                    max_price = MAX_PRICES_BY_ILVL[ilvl]

                    if 1000 <= price_gold <= max_price:
                        item_name = ITEMS_TO_WATCH[item_id]
                        print(f"¡ENCONTRADO!: {item_name} (ilvl {ilvl}) a {price_gold}g (Máx: {max_price}g)")
                        send_discord_alert(item_name, ilvl, price_gold)
                        found_deals += 1

        print(f"Escaneo finalizado. Chollos reales informados: {found_deals}")

    except Exception as e:
        print(f"Excepción: {e}")

if __name__ == "__main__":
    check_prices()
