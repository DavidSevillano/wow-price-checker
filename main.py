import os
import time
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

MAX_PRICES_BY_ILVL = {
    305: 80000,
    308: 50000,
    311: 450000,
}

ITEMS_TO_WATCH = [
    {"name": "Grebas de las profundidades nocivas", "id": 210817},
    {"name": "Yelmo místico de explorador de templos", "id": 210818},
    {"name": "Faja de Reptaescama", "id": 210819},
    {"name": "Zapatillas del culto siseante", "id": 210820},
    {"name": "Espaldares del sacrificio olvidado", "id": 210821},
    {"name": "Manto de rito venenoso", "id": 210822},
    {"name": "Almófar de volutador aplastante", "id": 210823},
    {"name": "Gran cinturón de bruto colmilludo", "id": 210824},
    {"name": "Ojo de jade de sierpe atada", "id": 210825},
]

def send_discord_alert(message_text):
    if not DISCORD_WEBHOOK_URL:
        print("Error: No hay URL de Webhook configurada.")
        return
    requests.post(DISCORD_WEBHOOK_URL, json={"content": message_text})
    time.sleep(1)

def check_prices():
    print("Iniciando escaneo de precios...")
    found_deals = 0

    # Headers para simular una petición válida de cliente
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }

    for item in ITEMS_TO_WATCH:
        # Endpoint directo de consulta de item por ID en Undermine
        url = f"https://undermine.exchange/api/item?house=eu&item={item['id']}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            
            # Si falla la llamada principal, intentamos con el endpoint alternativo regional
            if response.status_code != 200:
                url = f"https://api.undermine.exchange/item/{item['id']}?region=eu"
                response = requests.get(url, headers=headers, timeout=10)

            if response.status_code != 200:
                print(f"Error {response.status_code} al consultar {item['name']} (ID: {item['id']})")
                continue
                
            data = response.json()
            auctions = data.get("auctions", []) or data.get("current", [])
            print(f"Procesando {item['name']}: {len(auctions)} subastas encontradas.")
            
            for auction in auctions:
                # Extraemos el nivel de objeto (ilvl)
                ilvl = (
                    auction.get("bonusStats", {}).get("itemLevel") or 
                    auction.get("stats", {}).get("itemLevel") or
                    auction.get("itemLevel") or
                    auction.get("ilvl")
                )
                
                if ilvl in MAX_PRICES_BY_ILVL:
                    max_allowed = MAX_PRICES_BY_ILVL[ilvl]
                    buyout = (auction.get("buyout", 0) or auction.get("price", 0)) / 10000
                    
                    if 0 < buyout <= max_allowed:
                        realm = auction.get("realmName") or auction.get("realm") or "Desconocido"
                        msg = (
                            f"🚨 **¡CHOLLO DETECTADO EN EU!** 🚨\n"
                            f"**Objeto:** {item['name']} (ilvl {ilvl})\n"
                            f"**Precio:** {int(buyout):,} oro\n"
                            f"**Reino:** {realm}"
                        )
                        print(f"¡CHOLLO!: {item['name']} (ilvl {ilvl}) por {int(buyout)}g en {realm}")
                        send_discord_alert(msg)
                        found_deals += 1

        except Exception as e:
            print(f"Excepción procesando {item['name']}: {e}")

    print(f"Escaneo finalizado. Chollos encontrados e informados: {found_deals}")

if __name__ == "__main__":
    check_prices()
