# WoW Price Checker

Vigila la Casa de Subastas de World of Warcraft y avisa por Discord cuando
alguno de tus objetos esta en **compra directa** por debajo del precio que hayas
fijado.

- Escanea todos los reinos conectados de una region (por defecto EU).
- Precio maximo **por objeto y por ilvl**, configurable en `config.yaml`.
- No repite avisos: recuerda que subastas ya te ha notificado.
- Avisos con embed, enlace a Wowhead y cuanto esta por debajo de tu limite.
- Si el escaneo va mal (muchos reinos caidos) te lo dice, en vez de callarse.

---

## 1. Puesta en marcha (en local)

### 1.1 Credenciales

Necesitas dos cosas:

**API de Blizzard** — entra en <https://develop.battle.net/access/clients>, crea
un cliente (cualquier nombre; como URL de redireccion vale
`https://localhost`) y apunta el *Client ID* y el *Client Secret*.

**Webhook de Discord** — en el canal donde quieras los avisos: `Editar canal >
Integraciones > Webhooks > Nuevo webhook > Copiar URL del webhook`.

### 1.2 Instalacion

Desde la carpeta del proyecto, en PowerShell:

```bash
py -m venv .venv
```

```bash
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copia `.env.example` a `.env` y rellena los tres valores. Ese fichero no se sube
a git nunca.

### 1.3 Comprobar que todo esta bien

Primero, que el webhook funcione:

```bash
.venv\Scripts\python.exe main.py --test-discord
```

Deberia aparecerte un mensaje de prueba en el canal de Discord.

Despues, una pasada de prueba sobre un par de reinos, sin enviar nada:

```bash
.venv\Scripts\python.exe main.py --dry-run --realms 1305,1378
```

Y por ultimo, el escaneo completo de verdad:

```bash
.venv\Scripts\python.exe main.py
```

Tarda unos segundos: son los 92 connected realms de EU y unos 2,8 millones de
subastas, pero solo se mira lo que interesa.

---

## 2. Configurar que vigilar

Todo se edita en `config.yaml`; no hay que tocar codigo.

```yaml
items:
  - name: "Greaves of the Noxious Depths"
    max_price_by_ilvl: { 298: 9000, 311: 90000 }
```

Puntos importantes:

- El **nombre debe ser exacto y en ingles**, tal cual aparece en el juego.
- Los precios van **en oro**.
- **Solo se avisa de los ilvl que aparezcan en la tabla.** En el ejemplo, una
  subasta de ilvl 305 se ignora aunque este tirada de precio.
- Si un nombre da problemas, puedes fijar el id a mano:
  `item_id: 213456`. Lo ves en la URL de Wowhead del objeto.

Si cambias algo mal, el script te lo dice al arrancar y no llega a escanear.

### Cuando no se puede saber el ilvl

Blizzard no publica el ilvl de una subasta: lo codifica en unos "bonus ids" que
el fichero traduce en `bonus_ilvl_map`. Si Blizzard los cambia en un parche, el
script no se queda mudo: avisa igualmente cuando el precio este por debajo de tu
umbral **mas barato** para ese objeto, marcando el aviso como *ilvl sin
confirmar*. Comprueba el ilvl en el juego antes de comprar.

Para actualizar el mapa, ejecuta con `-v` y mira los bonus ids que salen:

```bash
.venv\Scripts\python.exe main.py --dry-run --realms 1305 -v
```

---

## 3. Ponerlo en GitHub Actions

Cuando funcione en local:

1. En el repositorio: `Settings > Secrets and variables > Actions > New
   repository secret`, y crea `DISCORD_WEBHOOK_URL`, `BLIZZARD_CLIENT_ID` y
   `BLIZZARD_CLIENT_SECRET`.
2. Sube los cambios. El workflow `.github/workflows/monitor.yml` se ejecuta cada
   hora por su cuenta, al minuto 35.

   Blizzard regenera los datos de la casa de subastas una vez por hora y para
   toda la region a la vez (comprobado: 30 reinos de EU compartian el volcado de
   las 11:31 UTC). Escanear mas a menudo devuelve datos identicos. Cada pasada
   escribe en el log la antiguedad del volcado; si ves que se acerca a los 60
   minutos, Blizzard ha movido su horario y conviene retrasar el minuto del cron.
3. Para probarlo a mano: pestana `Actions > WoW Price Monitor > Run workflow`
   (tiene una casilla para hacer una pasada en seco).

La memoria de avisos se guarda entre ejecuciones con la cache de Actions, asi
que no ensucia el repositorio con commits.

---

## 3.1 Saber si esta corriendo de verdad

Cuando no llega ningun aviso a Discord hay dos explicaciones muy distintas: que
no haya chollos, o que la pasada no se haya ejecutado. Para distinguirlas:

```bash
.venv\Scripts\python.exe estado.py
```

Lista las ejecuciones programadas de las ultimas 24 horas, marca las que
faltan, y dice cuanto se retraso cada una respecto al minuto del cron. Con
`--detalle` descarga ademas el log de cada pasada y resume que encontro (mas
lento). Necesita el cliente `gh` autenticado.

Para revisar una sola ejecucion a fondo, la pestana Actions del repositorio, o:

```bash
gh run list --workflow="WoW Price Monitor" --limit 10
```

## 4. Opciones de la linea de comandos

| Opcion | Para que sirve |
|---|---|
| `--dry-run` | Escanea y muestra los chollos, pero no envia nada ni guarda estado. |
| `--realms 1305,1378` | Escanea solo esos reinos. Ideal para probar rapido. |
| `--test-discord` | Manda un mensaje de prueba al webhook y termina. |
| `--ignore-state` | Avisa tambien de chollos ya notificados antes. |
| `--config otro.yaml` | Usa otro fichero de configuracion. |
| `--state-dir ruta` | Cambia donde se guarda la memoria (por defecto `.state/`). |
| `-v` | Muestra cada subasta vista, con sus bonus ids. |

Codigos de salida: `0` todo bien · `1` error de configuracion o credenciales ·
`2` demasiados reinos han fallado y el resultado esta incompleto.

---

## 5. Estructura del proyecto

```
config.yaml            Lo unico que editas normalmente
main.py                Linea de comandos y orquestacion
estado.py              Comprueba si Actions esta ejecutando el cron
wowalerts/
  config.py            Carga y validacion del config
  blizzard.py          API de Blizzard: OAuth, reintentos, endpoints
  items.py             Nombres de objeto -> ids
  ilvl.py              Deduccion del ilvl de una subasta
  scanner.py           Que cuenta como chollo (logica pura)
  state.py             Memoria entre ejecuciones
  notifier.py          Embeds y envio a Discord
tests/                 123 tests, sin tocar la red
```

Para pasar los tests:

```bash
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

```bash
.venv\Scripts\python.exe -m pytest -q
```
