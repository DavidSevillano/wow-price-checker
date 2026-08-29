import os
import requests
from concurrent.futures import ThreadPoolExecutor

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
CLIENT_ID = os.getenv("BLIZZARD_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLIZZARD_CLIENT_SECRET")

# Solo los ilvl deseados con sus precios máximos en oro.
# Cualquier ilvl que no esté aquí (como 219, 279 o 292) será ignorado.
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

# MAPA COMPLETO DE LOS 92 CONNECTED REALMS DE EUROPA
REALM_NAMES_STATIC = {
    # España
    1305: "EU - Dun Modr / Sanguino / C'Thun / Shen'dralar / Zul'jin / Uldum",
    1378: "EU - Exodar / Minahonda",
    1388: "EU - Colinas Pardas / Los Errantes / Tyrande",

    # Internacional / Reino Unido (EU English)
    509:  "EU - Silvermoon",
    581:  "EU - Kazzak",
    631:  "EU - Frostmane / Aggra (Portuguese)",
    1080: "EU - Aggramar / Hellscream",
    1081: "EU - Al'Akir / Skullcrusher / Xavius",
    1082: "EU - Arathor / Aszune",
    1083: "EU - Azjol-Nerub / Quel'Thalas",
    1084: "EU - Bloodhoof / Khadgar",
    1085: "EU - Moonglade / Steamwheedle Cartel / The Sha'tar",
    1086: "EU - Boulderfist / Daggerspine / Laughing Skull / Sunstrider / Talnivarr",
    1087: "EU - Bronze Dragonflight / Nordrassil",
    1088: "EU - Burning Blade / Drak'thul",
    1089: "EU - Burning Steppes / Kor'gall / Executus / Shattered Hand",
    1090: "EU - Chromaggus / Shattered Halls / Sunstrider",
    1091: "EU - Aerie Peak / Bronzebeard",
    1092: "EU - Blade's Edge / Eonar / Vek'nilash",
    1093: "EU - Cult of the Damned / The Venture Co",
    1096: "EU - Doomhammer / Turalyon",
    1300: "EU - Frostmane / Grim Batol / Jaedenar",
    1301: "EU - Outland",
    1303: "EU - Tarren Mill / Dentarg",
    1304: "EU - Ghostlands / Dragonblight",
    1307: "EU - Chamber of Aspects",
    1309: "EU - Argent Dawn",
    1310: "EU - Darkmoon Faire / Earthen Ring",
    1312: "EU - Hakkar / Emeriss / Agamaggan",
    1313: "EU - Terenas / Emerald Dream",
    1325: "EU - Scarshield Legion / Cult of the Damned",
    1329: "EU - Defias Brotherhood / Ravenholdt / Sporeggar",
    1331: "EU - Magtheridon",
    1332: "EU - Lightbringer / Mazrigos",
    1389: "EU - Wildhammer / Thunderhorn",
    1396: "EU - Stormscale",
    1400: "EU - Nordrassil",
    1401: "EU - Sylvanas",
    1402: "EU - Silvermoon",
    1403: "EU - Draenor",
    1415: "EU - Ragnaros",
    1416: "EU - Lightbringer",
    1417: "EU - Kul Tiras / Alonsus / Anachronos",
    1587: "EU - Saurfang",
    1596: "EU - Ravencrest",
    1597: "EU - Shattered Hand",
    1598: "EU - Skullcrusher",
    1614: "EU - Twisting Nether",

    # Alemania (EU German)
    561:  "EU - Antonidas",
    570:  "EU - Blackrock",
    578:  "EU - Frostwolf",
    580:  "EU - Aegwynn",
    612:  "EU - Eredar",
    1104: "EU - Anetheron / Festung der Stürme / Gul'dan / Nathrezim / Onyxia",
    1105: "EU - Dalvengyr / Frostmourne / Mal'Ganis / Nazjatar / Zuluhed",
    1106: "EU - Arthas / Blutkessel / Kel'Thuzad / Vek'lor / Wrathbringer",
    1121: "EU - Alleria / Rexxar",
    1122: "EU - Aman'Thul / Khaz'goroth",
    1123: "EU - Ambossar / Kargath",
    1125: "EU - Area 52 / Sen'jin",
    1127: "EU - Baelgun / Lothar",
    1393: "EU - Thrall",
    1405: "EU - Blackhand",
    1406: "EU - Malfurion / Malygos",
    1407: "EU - Un'Goro / Area 52",
    1408: "EU - Ysera / Malorne",
    1409: "EU - Die Aldor",
    1621: "EU - Blackmoore / Lordaeron",
    1626: "EU - Die Silberne Hand / Die ewige Wacht",
    1922: "EU - Perenolde / Teldrassil",
    1923: "EU - Garrosh / Nozdormu / Shattrath",
    1925: "EU - Norgannon / Dun Morogh",

    # Francia (EU French)
    1097: "EU - Hyjal",
    1098: "EU - Vol'jin",
    1099: "EU - Chants éternels",
    1100: "EU - Arak-arahm",
    1334: "EU - Archimonde",
    1335: "EU - Ysondre",
    1336: "EU - Varimathras / Elune",
    1337: "EU - Naxxramas / Arathi / Illidan / Temple noir",
    1390: "EU - Suramar / Medivh",
    1604: "EU - Uldaman / Drek'Thar",
    1623: "EU - Eitrigg / Krasus",
    1624: "EU - Dalaran / Marécage de Zangar",
    1625: "EU - Conseil des Ombres / Culte de la Rive noire",

    # Rusia (EU Russian)
    1602: "EU - Gordunni (Гордунни)",
    1605: "EU - Howling Fjord (Ревущий фьорд)",
    1615: "EU - Soulflayer (Свежеватель Душ)",
    1618: "EU - Deathweaver (Страж смерти)",

    # Italia (EU Italian)
    1308: "EU - Nemesis",
    1311: "EU - Well of Eternity",
}

BONUS_TO_ILVL = {
    10885: 279,
    10886: 292,
    10887: 298,
    10888: 305,
    10889: 308,
    10890: 311,
}

ITEM_DATA_CACHE = {}

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
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            realms_data = res.json().get("connected_realms", [])
            return [int(r["href"].split("connected-realm/")[1].split("?")[0]) for r in realms_data]
    except Exception as e:
        print(f"❌ Error reinos: {e}")
    return list(REALM_NAMES_STATIC.keys())

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
    # 1. Modificador explícito en la API (type 9)
    modifiers = item_obj.get("modifiers", [])
    for mod in modifiers:
        if mod.get("type") == 9:
            return mod.get("value")

    # 2. Mapeo de bonus_lists conocidos
    bonus_lists = item_obj.get("bonus_lists", [])
    for b_id in bonus_lists:
        if b_id in BONUS_TO_ILVL:
            return BONUS_TO_ILVL[b_id]

    # 3. Retorna el ilvl base original sin inventar un 305
    return base_ilvl

def send_discord_alert(item_name, price_gold, realm_str, ilvl):
    if not DISCORD_WEBHOOK_URL:
        return
    msg = (
        f"🚨 **¡CHOLLO DETECTADO EN EU!** 🚨\n"
        f"**Objeto:** {item_name} (ilvl {ilvl})\n"
        f"**Precio:** {price_gold:,} oro\n"
        f"**Reino:** {realm_str}\n"
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

                    # Si entra en el rango de precio pero no se reconoce su ilvl de la lista,
                    # se imprime en consola para capturar nuevos bonus_ids sin enviar alerta falsa
                    if exact_ilvl not in MAX_PRICES_BY_ILVL:
                        print(f"  🔍 Ignorado por ilvl ({exact_ilvl}): {item_name} | Pre: {price_gold}g | Bonus: {item_obj.get('bonus_lists')}")
                        continue

                    max_allowed = MAX_PRICES_BY_ILVL[exact_ilvl]
                    if price_gold <= max_allowed:
                        realm_str = REALM_NAMES_STATIC.get(realm_id, f"EU - Reino ID {realm_id}")
                        print(f"  🎯 ¡CHOLLO!: {item_name} (ilvl {exact_ilvl}) por {price_gold}g en {realm_str}")
                        send_discord_alert(item_name, price_gold, realm_str, exact_ilvl)
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
    all_realms = get_all_eu_connected_realms(headers)
    
    print(f"🚀 Escaneando los {len(all_realms)} reinos de EU a máxima velocidad...")
    max_global_price = max(MAX_PRICES_BY_ILVL.values())

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(lambda r_id: scan_realm(r_id, headers, max_global_price), all_realms))

    total_found = sum(results)
    print(f"\n✅ Escaneo completado. Total chollos enviados: {total_found}")

if __name__ == "__main__":
    check_prices()
