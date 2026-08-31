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
2. Sube los cambios. El workflow `.github/workflows/monitor.yml` ya se ejecuta
   solo: su `schedule` corre cada 3 horas como red de seguridad, y la pasada de
   cada hora la dispara el cron externo del apartado 3.1, que es puntual.

   Blizzard regenera los datos de la casa de subastas una vez por hora y para
   toda la region a la vez (comprobado: 30 reinos de EU compartian el volcado de
   las 11:31 UTC). Escanear mas a menudo devuelve datos identicos. Cada pasada
   escribe en el log la antiguedad del volcado; si ves que se acerca a los 60
   minutos, Blizzard ha movido su horario y conviene retrasar el minuto.
3. Para probarlo a mano: pestana `Actions > WoW Price Monitor > Run workflow`
   (tiene una casilla para hacer una pasada en seco).

La memoria de avisos se guarda entre ejecuciones con la cache de Actions, asi
que no ensucia el repositorio con commits.

---

## 3.1 Disparo puntual desde un cron externo

Los eventos `schedule` de Actions entran en una cola compartida y se retrasan
entre 20 y 40 minutos, cuando no se descartan. Un `workflow_dispatch`, en
cambio, arranca en segundos (medido en este repositorio: 12 s). Por eso la
ejecucion de cada hora la dispara un cron externo llamando a la API de GitHub,
y el `schedule` del workflow se queda como red de seguridad cada 3 horas.

Hace falta un token, asi que conviene que sea lo mas limitado posible.

### El token

En <https://github.com/settings/personal-access-tokens/new> crea un token
**fine-grained** (no uno clasico):

- **Repository access**: *Only select repositories* -> `wow-price-checker`.
- **Permissions** -> *Repository permissions* -> **Actions: Read and write**.
  Nada mas. (Si la llamada devolviera 403, anade *Contents: Read*.)
- **Expiration**: pon una fecha y apuntala; habra que renovarlo.

Asi acotado, el token solo puede lanzar workflows en ese repositorio. No puede
leer tu codigo ni tocar ningun otro repo.

### El cron externo

En un servicio de cron por HTTP (cron-job.org o equivalente), crea un trabajo
con exactamente esto:

| Campo | Valor |
|---|---|
| URL | `https://api.github.com/repos/DavidSevillano/wow-price-checker/actions/workflows/monitor.yml/dispatches` |
| Metodo | `POST` |
| Horario | cada hora, minuto **33** |
| Cuerpo | `{"ref":"main"}` |

Cabeceras:

```
Accept: application/vnd.github+json
Authorization: Bearer TU_TOKEN_AQUI
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

La respuesta correcta es **HTTP 204 sin cuerpo**. Un 404 suele significar que
el token no tiene acceso al repositorio; un 422, que la rama `main` o el nombre
del workflow no coinciden.

El minuto 33 sale de que Blizzard regenera los datos a y 31 y el disparo es
inmediato: dos minutos de margen bastan.

### Si Blizzard llega tarde

Dos minutos son suficientes casi siempre, pero no son garantia. Si al escanear
resulta que el volcado de esta hora todavia no ha salido, la pasada **espera
dos minutos y vuelve a mirar**, hasta dos veces, en vez de perder la hora
entera. Lo veras en el log:

```
⏳ Blizzard aun no ha publicado el volcado de las 13:31 UTC: lo leido es de la
   hora anterior. Espero 120 s y vuelvo a mirar (quedan 2 intento(s)).
```

Cada intento envia sus propios avisos, asi que un chollo que solo aparezca en
el primero se manda igual: reintentar nunca se traga una alerta.

La comparacion se hace contra el horario de Blizzard, no contra una antiguedad
fija. Por eso una pasada lanzada a mano a y 58 no reintenta: su volcado de y 31
tiene 27 minutos, pero es el ultimo que existe.

Se ajusta en `config.yaml` con `dump_minute`, `stale_retries` y
`stale_retry_wait_seconds`. Con `stale_retries: 0` se desactiva.

## 3.2 Saber si esta corriendo de verdad

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
| `--ventas` | Avisa de tus subastas vendidas, en su propio canal. |
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
  ventas.py            Que cuenta como venta y que como caducidad
  snapshot.py          Si el volcado leido es el de esta hora
tests/                 347 tests, sin tocar la red
```

Para pasar los tests:

```bash
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

```bash
.venv\Scripts\python.exe -m pytest -q
```

---

## 5. Avisos de undercut en tus propias subastas

Ademas de buscar chollos ajenos, el proyecto puede avisarte cuando **alguien
publica el mismo objeto que tu, a tu precio o por debajo**, para que vayas a
repostear. Solo mira los objetos que ya vigila `config.yaml`: el resto de lo que
tengas puesto (monturas, mochilas, decoracion) se ignora.

La API de Blizzard no dice quien publica cada subasta, asi que hace falta un
addon que exporte las tuyas desde dentro del juego.

### 5.1 Instalar el addon

Copia la carpeta `addon/WowAlertsExport` a tu carpeta de addons:

```bash
Copy-Item -Recurse -Force addon/WowAlertsExport "D:/Juegos/World of Warcraft/_retail_/Interface/AddOns/"
```

En la Steam Deck no hace falta saberse la ruta: hay un script que se la
pregunta a `sync_subastas.py`, que ya sabe buscarla.

```bash
bash instalar_addon_deck.sh
```

Vuelve a ejecutarlo **cada vez que cambie el addon**. Para saber que version
tienes cargada, dentro del juego: `/wa`.

Entra al juego y **abre la Casa de Subastas**: en el chat general te dira
cuantas subastas tuyas ha registrado. Si tienes personajes vendiendo en varios
reinos, repitelo con cada uno; el addon los va acumulando.

Para comprobarlo en cualquier momento: `/wowalerts`.

**Dos cosas que conviene saber:**

- El juego solo conoce tus subastas **mientras la Casa de Subastas esta
  abierta**. Con ella cerrada, el addon no puede leer nada y no toca lo que ya
  tenia guardado.
- WoW solo escribe los datos del addon a disco al salir del juego, al volver al
  selector de personajes o al hacer `/reload`. Si posteas y sigues jugando, el
  vigilante todavia no lo sabe. El addon te lo recuerda en pantalla.

### 5.2 Canal propio para los undercuts

Los avisos de undercut son de otra naturaleza que los chollos, asi que van a su
propio canal. Crea un webhook en el canal que quieras (`Editar canal >
Integraciones > Webhooks > Nuevo webhook`) y ponlo en `.env`:

```
DISCORD_UNDERCUT_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Si lo dejas vacio, los undercuts van al mismo canal que los chollos.

Para comprobar que ese canal funciona:

```bash
.venv\Scripts\python.exe main.py --undercut --test-discord
```

En GitHub Actions hace falta el mismo valor como secret del repositorio, con
ese mismo nombre.

### 5.3 Instalar la sincronizacion

```bash
powershell -ExecutionPolicy Bypass -File instalar_tarea_sync.ps1
```

Crea una tarea de Windows que cada 15 minutos mira si el volcado ha cambiado y,
si si, lo sube a GitHub. A partir de ahi el vigilante funciona **aunque apagues
el PC**.

Para forzarlo a mano:

```bash
.venv\Scripts\python.exe sync_subastas.py
```

Para quitar la tarea:

```bash
schtasks /delete /tn "WoW subastas sync" /f
```

### 5.4 Probarlo

```bash
.venv\Scripts\python.exe main.py --undercut --dry-run
```

Te lista quien te ha adelantado y en que personaje tienes que ir a cambiarlo,
sin enviar nada a Discord.

### 5.5 Como decide que dos subastas compiten

Del mismo objeto, una subasta ajena compite con la tuya si:

- su ilvl **se puede determinar** y es el tuyo, **o**
- su ilvl no se puede determinar pero sus **bonus ids son los mismos** que los
  de tu objeto.

Si no se puede saber ninguna de las dos cosas, **no se avisa**. Comparar contra
rivales de ilvl desconocido generaba solo falsas alarmas: el equipo de Legion
Remix publica un dato que parece ilvl pero es el nivel del personaje, y esas
subastas de 100 g salian compitiendo contra listados de 10.000 g.

### 5.6 Que esperar

- **Latencia de hasta una hora.** Blizzard regenera los datos de subastas una
  vez por hora. No hay forma de esquivarlo con la API oficial.
- **Un aviso por rival.** Mientras sea el mismo el que te adelanta, no se
  repite. Si reposteas y te vuelven a adelantar, aviso nuevo.

  Ojo a lo que eso significa al leer el aviso: **ahi solo van las nuevas**. Si
  un personaje tiene tres adelantadas y dos ya te las avise, veras "1 nueva", no
  "3". Por eso el titulo dice *nueva* y, cuando hay omitidas, el mensaje las
  **nombra** en la cabecera:

  ```
  🔁 Y 1 que ya te avise y sigue adelantada: Ebardan — Zapatillas del culto siseante
  ```

  Se nombran hasta seis; a partir de ahi se dice cuantas faltan y se remite al
  panel. Un recuento a secas no servia de nada: sin saber cual es, no puedes ir
  a arreglarla. **La foto completa esta siempre en el panel fijado**, que se
  reescribe cada hora con todas.
- **Nada de avisos fantasma.** Si una subasta tuya ya no aparece en la casa de
  subastas (vendida, caducada o cancelada), se descarta sola.
- **Tus otros personajes cuentan como rivales hasta que los visites.** Si
  vendes lo mismo con dos personajes y solo has abierto la Casa de Subastas con
  uno, el otro parece competencia. Abre la CdS con cada personaje que venda y el
  problema desaparece.

### 5.7 Con que personaje ir a por un chollo

Los avisos de chollo llevan un campo **Ir con** que dice con que personaje
tuyo, y de que cuenta, puedes comprarlo:

```
Ir con: Hbarfel · WoW 3
```

Y cuando el chollo esta en un reino donde no tienes a nadie, tambien lo dice,
que es igual de util: te ahorra abrir el juego para nada.

La lista sale de las carpetas de WoW, no del addon, asi que incluye tambien los
personajes que no tienen ninguna subasta puesta. La genera `sync_subastas.py`
junto al volcado de subastas, en `mis_personajes.json`, y se actualiza sola
cuando creas un personaje nuevo.

### 5.8 El panel de estado

Ademas de los avisos, el vigilante mantiene **un unico mensaje** en el canal de
undercuts que reescribe cada hora con el estado de todas tus subastas:

```
📊 Tus subastas
Tus 57 subastas vigiladas van primeras. Nada que hacer.

**Mbarval · WoW 2** — 6 vigiladas, todas primeras ✅
**Dbardan · WoW 2** — 4 vigiladas, 1 adelantada
⚠️ Zapatillas del culto siseante — ~~50.000~~ **30.000 g**
```

**Fijalo en el canal** (clic derecho en el mensaje > Fijar) y lo tienes a un
toque desde el movil. Los avisos te cuentan lo que ha cambiado; el panel te
cuenta como estas.

Los personajes que tienen algo que atender salen arriba, y de cada uno solo se
detallan las subastas adelantadas: listar las que van bien seria ilegible.

No se publica uno nuevo cada hora: se reescribe el mismo, cuyo id se guarda en
`.state/panel.json`. Si lo borras, la pasada siguiente crea otro.

## 6. Avisos de venta

Ademas de avisarte de los undercuts, el vigilante te dice **que se te ha
vendido**, en su propio canal, sin tener que entrar al juego a mirar el buzon.
Como los undercuts, solo mira los objetos que vigila `config.yaml`.

### 6.1 Como sabe que se ha vendido

La API de Blizzard **no publica ventas**: solo una foto por hora de lo que sigue
vivo. Una subasta tuya que desaparece pudo venderse, caducar o cancelarse, y
desde fuera las tres se ven igual.

Se separan asi: de cada subasta tuya se guarda **la fecha mas temprana en la que
podria caducar**. Si desaparece antes de esa fecha, es imposible que haya
caducado. Esa fecha se afina cada hora con dos pistas:

- **El tramo de tiempo restante.** Blizzard publica si a una subasta le quedan
  mas de 12 h, entre 2 y 12 h, entre 30 min y 2 h, o menos de 30 min. Verla en
  el tramo de 2-12 h garantiza dos horas de vida: si a la hora siguiente no
  esta, no ha caducado.
- **La ventana de nacimiento.** Si no estaba en el volcado de las 14:31 y si en
  el de las 15:31, se publico entre esas dos horas. Con `listing_hours: 12`, no
  puede caducar antes de las 02:31.

La segunda pista es la buena, y solo vale para las subastas que se publican
estando el vigilante en marcha. Las que ya estaban puestas cuando lo montaste se
apoyan solo en la primera hasta que las reposteas.

Que una subasta sea nueva se decide por su **id**, que crece con el tiempo
dentro de un reino, y no por si el addon la habia exportado ya: el addon puede
tardar dias en volcarla, y tomarla por recien nacida el dia que aparece
convertiria su caducacion en una venta falsa.

### 6.2 Lo que no vas a ver

- **Las ventas de la ultima hora del listado.** Ahi una venta y una caducacion
  producen exactamente el mismo dato, y avisar de todas seria peor: **toda
  subasta que no se vende acaba desapareciendo justo ahi**, asi que el canal se
  llenaria de falsas alarmas.
- **Las ventas de una subasta que te estaban adelantando**, ni las de una que
  hayas cancelado. Ver mas abajo.
- **Objetos que no esten en `config.yaml`.**

### 6.3 Los reposteos no cuentan como ventas

Cancelar una subasta y venderla se ven **exactamente igual** desde la API: en
las dos desaparece. Y si reprecias a menudo, cada reposteo tuyo saldria como una
venta. Paso: el 2026-08-31 llegaron 13 avisos de venta, todos falsos, todos
reposteos.

Hay dos defensas, y hacen falta las dos.

**La lista de cancelaciones del addon.** El addon apunta el id de cada subasta
que cancelas y lo sube con el volcado. Es el dato preciso: una cancelacion es
una cancelacion, no hay que adivinar nada. Necesita el addon **v1.9 o
posterior**; si vienes de una version anterior, vuelve a copiarlo (apartado
5.1).

**La espera de una pasada.** Aqui esta el problema que obliga a esperar:

```
16:20  cancelas          -> desaparece del volcado de Blizzard de las 16:31
16:33  pasada            -> cantaria la venta falsa
16:35  el sync sube la cancelacion desde el juego   <- llega tarde
```

Blizzard se entera de tus cancelaciones **antes** que el addon, porque WoW solo
escribe a disco al hacer `/reload`. Por eso una subasta que desaparece no se
canta en el acto: se queda pendiente y solo se anuncia en la pasada siguiente,
si para entonces no ha aparecido en la lista de cancelaciones. Eso le da al
sync una hora entera de margen.

**Coste: las ventas llegan con una hora mas de retraso**, entre 1 y 2 horas en
vez de hasta 1. A cambio, no te mienten.

La fecha de caducidad se sigue juzgando por **cuando desaparecio la subasta**,
no por cuando se toma la decision. Si no, la espera empujaria a la subasta mas
alla de su plazo y se perderian ventas buenas.

Como tercera red queda la marca de undercut: si la ultima vez que se vio viva le
estaban adelantando, se da por reposteada sin esperar. Cubre el caso en que
reposteas por mi aviso, que es el unico que puedo anticipar.

Todo lo que se tapa queda escrito en el log de la pasada:

```
↩️  Dbardan de Zapatillas del culto siseante: la cancelaste tu, asi que no
    la cuento como venta.
```

**Ojo con varias cuentas de WoW.** `/reload` recarga **solo la sesion en la que
lo haces**. Si tienes WoW 1, WoW 2 y WoW 3, recargar en una deja a las otras
corriendo el addon viejo, que no apunta nada: sus reposteos siguen saliendo como
ventas y no hay forma de notarlo mirando el aviso. Paso el 2026-08-31 con
Adanlin, de WoW 3, mientras las 19 cancelaciones registradas eran todas de
WoW 2.

Por eso `sync_subastas.py` lo canta en cada pasada:

```
⚠️  Estas cuentas de WoW siguen con el addon viejo y no apuntan tus
    cancelaciones: 403840080#1, 403840080#3. Entra con cada una y haz /reload,
    o sus reposteos saldran como ventas.
```

Lo detecta por la clave `canceladas` del volcado, que el addon nuevo escribe
siempre, tenga o no cancelaciones dentro.

**Lo que sigue sin cubrirse:** que canceles y no vuelvas a entrar al juego a
hacer `/reload` antes de la pasada siguiente. Ahi la cancelacion no llega a
tiempo y sale como venta.

### 6.4 Canal propio

Crea un webhook en el canal que quieras y ponlo en `.env`:

```
DISCORD_VENTAS_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Si lo dejas vacio, las ventas van al canal general. Para comprobarlo:

```bash
.venv\Scripts\python.exe main.py --ventas --test-discord
```

En GitHub Actions hace falta el mismo valor como secret del repositorio, con ese
mismo nombre.

### 6.5 Probarlo

```bash
.venv\Scripts\python.exe main.py --ventas --dry-run
```

La **primera pasada nunca detecta ventas**, y es lo correcto: solo puede
declarar vendida una subasta que haya visto viva antes. Sin esa regla, el primer
arranque cantaria como vendidas todas las que el addon tiene apuntadas y hace
dias que no existen.

Para hacer las dos vigilancias con una sola descarga, que es como corre en
Actions:

```bash
.venv\Scripts\python.exe main.py --undercut --ventas
```

### 6.6 Las cifras

Van **en neto**: el precio al que estaba puesta menos la comision que se queda
la casa de subastas, que es lo que de verdad te llega al buzon. El porcentaje se
ajusta en `config.yaml` con `ah_cut_pct`.

El aviso lleva el **ilvl** entre parentesis. Con el mismo objeto puesto a 292,
295, 298 y 305 a la vez, sin eso no se sabe cual se ha ido, y al mirar la casa
de subastas ves otro del mismo nombre y crees que no se ha vendido nada.
