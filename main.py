import os
import time
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

# Límite máximo general en oro para avisar si encontramos algún chollo de estos items
MAX_PRICE_GOLD = 70000

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

def send_discord_alert(item_name, item_id, price_gold, bonus_lists):
    if not DISCORD_WEBHOOK_URL:
        return
    msg = (
        f"🚨 **¡CHOLLO DETECTADO!** 🚨\n"
        f"**Objeto:** {item_name} (ID: {item_id})\n"
        f"**Precio:** {price_gold:,} oro\n"
        f"**Bonus IDs:** {bonus_lists}\n"
        f"-----------------------------------"
    )
    requests.post(DISCORD_WEBHOOK_URL, json={"content": msg})
    time.sleep(1)

def check_prices():
    print("Iniciando escaneo de prueba...")
    token = get_blizzard_token()
    if not token:
        print("Token no disponible.")
        return

    headers = {"Authorization": f"Bearer {token}"}
    url = "https://eu.api.blizzard.com/data/wow/connected-realm/1305/auctions?namespace=dynamic-eu&locale=es_ES"

    try:
        res = requests.get(url, headers=headers, timeout=30)
        if res.status_code != 200:
            print(f"Error {res.status_code} al consultar Blizzard.")
            return

        auctions = res.json().get("auctions", [])
        print(f"Analizando {len(auctions)} subastas del reino 1305...")
        
        found_deals = 0
        matching_items_debug = 0

        for auction in auctions:
            item_info = auction.get("item", {})
            item_id = item_info.get("id")

            if item_id in ITEMS_TO_WATCH:
                buyout = auction.get("buyout", 0) or auction.get("unit_price", 0)
                price_gold = int(buyout / 10000)
                bonus_lists = item_info.get("bonus_lists", [])
                item_name = ITEMS_TO_WATCH[item_id]

                # Imprimir en la consola los primeros 5 encontrados para ver sus datos reales
                if matching_items_debug < 5:
                    print(f"[DEBUG] {item_name} encontrado a {price_gold}g | Bonus: {bonus_lists}")
                    matching_items_debug += 1

                # Filtrar descartando recetas/patrones muy baratos (menores a 1,000g)
                if 1000 <= price_gold <= MAX_PRICE_GOLD:
                    send_discord_alert(item_name, item_id, price_gold, bonus_lists)
                    found_deals += 1

        print(f"Escaneo finalizado. Chollos informados: {found_deals}")

    except Exception as e:
        print(f"Excepción: {e}")

if __name__ == "__main__":
    check_prices()
