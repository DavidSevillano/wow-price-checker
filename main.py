import os
import requests

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# Umbrales máximos de precio según el ilvl
MAX_PRICES_BY_ILVL = {
    305: 40000,
    308: 50000,
    311: 450000,
}

# Objetos a monitorear en EU
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

def send_discord_alert(item_name, ilvl, price, realm):
    message = {
        "content": (
            f"🚨 **¡CHOLLO DETECTADO EN EU!** 🚨\n"
            f"**Objeto:** {item_name} (ilvl {ilvl})\n"
            f"**Precio:** {price:,} oro\n"
            f"**Reino:** {realm}\n"
            f"-----------------------------------"
        )
    }
    requests.post(DISCORD_WEBHOOK_URL, json=message)

def check_prices():
    if not DISCORD_WEBHOOK_URL:
        print("Error: No se ha encontrado la variable DISCORD_WEBHOOK_URL")
        return

    for item in ITEMS_TO_WATCH:
        url = f"https://api.undermine.exchange/api/item/{item['id']}?region=eu"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                continue
                
            data = response.json()
            
            for auction in data.get("auctions", []):
                ilvl = auction.get("bonusStats", {}).get("itemLevel")
                
                if ilvl in MAX_PRICES_BY_ILVL:
                    max_allowed_price = MAX_PRICES_BY_ILVL[ilvl]
                    buyout = auction.get("buyout", 0) / 10000
                    
                    if buyout <= max_allowed_price:
                        realm = auction.get("realmName", "Desconocido")
                        send_discord_alert(item["name"], ilvl, int(buyout), realm)
                        
        except Exception as e:
            print(f"Error procesando {item['name']}: {e}")

if __name__ == "__main__":
    check_prices()
