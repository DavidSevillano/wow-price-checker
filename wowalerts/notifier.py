"""Envio de avisos a Discord.

La construccion de los embeds es una funcion pura (`build_messages`) para poder
comprobar el formato en los tests sin enviar nada, y el envio real es una capa
fina encima.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

import requests

from .scanner import Deal
from .undercut import Undercut
from .ventas import Venta

log = logging.getLogger(__name__)

# Limites del webhook de Discord.
MAX_EMBEDS_PER_MESSAGE = 10
# Tope propio: mas de esto en una pasada es ruido, no una oportunidad.
MAX_DEALS_PER_RUN = 50

COLOR_UNCONFIRMED = 0x95A5A6  # gris: ilvl sin confirmar
COLOR_GOOD = 0xE67E22        # naranja: por debajo del umbral
COLOR_GREAT = 0xF1C40F       # amarillo: bastante por debajo
COLOR_STEAL = 0x2ECC71       # verde: chollo serio
COLOR_WARNING = 0xE74C3C     # rojo: aviso de salud del bot
COLOR_UNDERCUT = 0xC0392B    # rojo oscuro: te han adelantado
COLOR_VENTA = 0xD4AF37       # oro viejo: dinero que entra
COLOR_REPETIDO = 0x7F8C8D    # gris: siguen adelantadas, ya avisadas
# Limite duro de Discord para la descripcion de un embed.
MAX_EMBED_DESCRIPTION = 4096
# Tope propio de lineas por mensaje: mas de esto ya no se lee de un vistazo.
MAX_UNDERCUT_LINES_PER_MESSAGE = 20
# Los nombres de objeto de WoW no pasan de 60 caracteres, pero recortarlos
# garantiza que una linea suelta nunca pueda desbordar un mensaje entero.
MAX_ITEM_NAME = 100

TIME_LEFT_ES = {
    "SHORT": "menos de 30 min",
    "MEDIUM": "30 min - 2 h",
    "LONG": "2 - 12 h",
    "VERY_LONG": "mas de 12 h",
}


class DiscordError(Exception):
    """No se ha podido entregar el aviso a Discord."""


def format_gold(amount: int) -> str:
    """120000 -> '120.000' (separador de miles a la espanola)."""
    return f"{amount:,}".replace(",", ".")


def _time_left_label(raw: str) -> str:
    return TIME_LEFT_ES.get(raw.upper(), raw or "desconocido")


def _color_for(deal: Deal) -> int:
    if not deal.ilvl_confirmed:
        return COLOR_UNCONFIRMED
    if deal.discount_pct >= 50:
        return COLOR_STEAL
    if deal.discount_pct >= 25:
        return COLOR_GREAT
    return COLOR_GOOD


def build_embed(
    deal: Deal,
    realm_name: str,
    icon_url: str | None = None,
    snapshot_at: datetime | None = None,
    quien_compra: str | None = None,
) -> dict[str, Any]:
    """Tarjeta de Discord para un chollo."""
    if deal.ilvl_confirmed:
        ilvl_text = f"ilvl **{deal.ilvl}**"
    else:
        ilvl_text = "ilvl **sin confirmar**"

    description = (
        f"**{format_gold(deal.price_gold)} de oro**  ·  {ilvl_text}\n"
        f"Un {deal.discount_pct:.0f}% por debajo de tu limite "
        f"({format_gold(deal.threshold_gold)} de oro)."
    )
    if not deal.ilvl_confirmed:
        description += (
            "\n\n> No he podido determinar el ilvl de esta subasta, asi que la "
            "he comparado con tu precio mas bajo para ese objeto. Comprueba el "
            "ilvl en el juego antes de comprar."
        )

    fields = [
        {"name": "Reino", "value": realm_name, "inline": True},
        {
            "name": "Tiempo restante",
            "value": _time_left_label(deal.time_left),
            "inline": True,
        },
    ]
    if deal.quantity > 1:
        fields.append(
            {"name": "Cantidad", "value": str(deal.quantity), "inline": True}
        )
    if quien_compra:
        # Un chollo en un reino donde no tienes a nadie no se puede comprar, y
        # saberlo antes de abrir el juego ahorra el viaje.
        fields.append({"name": "Ir con", "value": quien_compra, "inline": False})

    embed: dict[str, Any] = {
        "title": deal.item_name,
        # El ancla final no le dice nada a Wowhead, pero hace que cada embed
        # tenga una url distinta. Discord fusiona en uno solo los embeds de un
        # mismo mensaje que comparten url (es su galeria de imagenes), y sin
        # esto varias subastas del mismo objeto se veian como una sola.
        "url": f"https://www.wowhead.com/item={deal.item_id}#a{deal.auction_id}",
        "color": _color_for(deal),
        "description": description,
        "fields": fields,
        "footer": {"text": f"Subasta {deal.auction_id} · reino {deal.realm_id}"},
    }

    if icon_url:
        embed["thumbnail"] = {"url": icon_url}

    if snapshot_at:
        # Discord lo pinta junto al pie y lo convierte a la zona horaria de cada
        # lector. Es la hora del volcado de Blizzard, no la del envio: lo que
        # importa es cuando se vio ese precio.
        # Discord pinta el pie como "texto • fecha", asi que el texto se corta
        # aqui para que se lea "... · precio visto • 30/08/2026 13:31".
        embed["timestamp"] = snapshot_at.isoformat()
        embed["footer"]["text"] += " · precio visto"

    return embed


def deals_to_send(deals: Sequence[Deal]) -> list[Deal]:
    """Los chollos que caben en un aviso.

    Lo que sobre NO se pierde: al no marcarse como avisado, la pasada siguiente
    lo vuelve a encontrar y lo envia entonces.
    """
    return list(deals[:MAX_DEALS_PER_RUN])


def build_messages(
    deals: Sequence[Deal],
    realm_names: Mapping[int, str],
    icon_urls: Mapping[int, str] | None = None,
    snapshot_at: datetime | None = None,
    compradores: Mapping[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Convierte los chollos en mensajes listos para el webhook.

    Se agrupan de diez en diez (el maximo que admite Discord por mensaje) y se
    recorta a `MAX_DEALS_PER_RUN`, avisando de cuantos quedan pendientes.
    """
    if not deals:
        return []

    shown = deals_to_send(deals)
    omitted = len(deals) - len(shown)

    plural = "chollos" if len(shown) != 1 else "chollo"
    header = f"🚨 **{len(shown)} {plural}** por debajo de tus precios"
    if omitted:
        header += f" (y {omitted} mas que te envio en la proxima pasada)"

    messages: list[dict[str, Any]] = []
    for start in range(0, len(shown), MAX_EMBEDS_PER_MESSAGE):
        chunk = shown[start : start + MAX_EMBEDS_PER_MESSAGE]
        message: dict[str, Any] = {
            "embeds": [
                build_embed(
                    deal,
                    realm_names.get(deal.realm_id, f"Reino {deal.realm_id}"),
                    (icon_urls or {}).get(deal.item_id),
                    snapshot_at,
                    (compradores or {}).get(deal.realm_id),
                )
                for deal in chunk
            ]
        }
        if start == 0:
            message["content"] = header
        messages.append(message)

    return messages


def _undercut_line(undercut: Undercut) -> str:
    """Una linea del aviso: que objeto y a que precio hay que batir."""
    nombre = undercut.mine.item_name
    if len(nombre) > MAX_ITEM_NAME:
        nombre = nombre[: MAX_ITEM_NAME - 1].rstrip() + "…"

    if undercut.tied:
        return f"• {nombre} — te igualan a {format_gold(undercut.rival_price_gold)} g"
    return (
        f"• {nombre} — ~~{format_gold(undercut.my_price_gold)}~~ "
        f"**{format_gold(undercut.rival_price_gold)} g**"
    )


def _repartir(lineas: list[str], presupuesto: int) -> list[list[str]]:
    """Parte las lineas en grupos que quepan en un mensaje de Discord."""
    grupos: list[list[str]] = []
    actual: list[str] = []
    largo = 0

    for linea in lineas:
        cabe = largo + len(linea) + 1 <= presupuesto
        if actual and (not cabe or len(actual) >= MAX_UNDERCUT_LINES_PER_MESSAGE):
            grupos.append(actual)
            actual, largo = [], 0
        actual.append(linea)
        largo += len(linea) + 1

    if actual:
        grupos.append(actual)
    return grupos


# Cuantas de las ya avisadas se nombran antes de remitir al panel. Mas de esto
# en una linea de cabecera deja de leerse.
MAX_YA_AVISADAS_NOMBRADAS = 6


def build_undercut_messages(
    undercuts: Sequence[Undercut], ya_avisados: Sequence[Undercut] = ()
) -> list[dict[str, Any]]:
    """Un mensaje por personaje, con sus subastas adelantadas en una tarjeta.

    Agrupar por personaje es lo que hace el aviso accionable: cada mensaje es
    un viaje al buzon de un personaje concreto, y dice todo lo que hay que
    cambiar alli.

    Va en un embed y no en texto suelto porque Discord encadena los mensajes
    seguidos de un mismo webhook: le quita al segundo el avatar y el nombre, y
    dos avisos se leen como uno. El borde de color de la tarjeta los separa sin
    gastar una linea en decirlo.
    """
    if not undercuts:
        return []

    shown = list(undercuts[:MAX_DEALS_PER_RUN])

    # dict normal: conserva el orden de llegada, que ya viene por diferencia de
    # precio, asi que el personaje con el undercut mas gordo sale primero.
    por_personaje: dict[tuple[str, str, object], list[Undercut]] = {}
    for undercut in shown:
        clave = (
            undercut.mine.character,
            undercut.mine.realm,
            undercut.mine.account,
        )
        por_personaje.setdefault(clave, []).append(undercut)

    messages: list[dict[str, Any]] = []
    for (character, _realm, account), suyas in por_personaje.items():
        # El reino no hace falta: lo que necesitas para ir a cambiarlo es a que
        # cuenta entrar y con que personaje.
        quien = f"⚔️ {character}"
        if account is not None:
            quien += f" · WoW {account}"

        # "1 subasta" se leia como el total de ese personaje, y no lo es: aqui
        # solo van las que no se hayan avisado ya. Decir "nueva" evita creer que
        # un personaje con tres adelantadas solo tiene una.
        plural = "nuevas" if len(suyas) != 1 else "nueva"
        titulo = f"{quien} — {len(suyas)} {plural}"
        continuacion = f"{quien} · sigue"

        grupos = _repartir(
            [_undercut_line(u) for u in suyas], MAX_EMBED_DESCRIPTION
        )
        for indice, grupo in enumerate(grupos):
            messages.append(
                {
                    "embeds": [
                        {
                            "title": titulo if indice == 0 else continuacion,
                            "description": "\n".join(grupo),
                            "color": COLOR_UNDERCUT,
                        }
                    ]
                }
            )

    if ya_avisados and messages:
        # Sin esto, un personaje con tres adelantadas de las que dos ya se
        # avisaron aparece con una sola y parece que las otras se arreglaron.
        # Van en su propio bloque y agrupadas por personaje: una lista corrida
        # repitiendo el mismo nombre no se lee.
        messages.append(_resumen_ya_avisadas(ya_avisados))

    return messages


def _resumen_ya_avisadas(ya_avisados: Sequence[Undercut]) -> dict[str, Any]:
    """Un bloque con las que siguen adelantadas y ya se avisaron.

    Agrupado por personaje, que es como se actua: cada linea es un viaje al
    buzon de uno. El ilvl va detras del objeto porque el mismo objeto puesto a
    dos ilvl salia dos veces identico y parecia un fallo.
    """
    por_personaje: dict[tuple[str, object], list[Undercut]] = {}
    for undercut in ya_avisados:
        clave = (undercut.mine.character, undercut.mine.account)
        por_personaje.setdefault(clave, []).append(undercut)

    lineas: list[str] = []
    for (character, account), suyas in por_personaje.items():
        quien = character
        if account is not None:
            quien += f" · WoW {account}"
        objetos = ", ".join(
            f"{u.mine.item_name} ({u.mine.ilvl})" if u.mine.ilvl else u.mine.item_name
            for u in suyas
        )
        lineas.append(f"**{quien}** — {objetos}")

    grupos = _repartir(lineas, MAX_EMBED_DESCRIPTION)
    dentro = grupos[0] if grupos else []
    fuera = len(lineas) - len(dentro)
    if fuera:
        dentro = dentro + [f"_y {fuera} personaje(s) mas: mira el panel fijado._"]

    plural = "siguen" if len(ya_avisados) != 1 else "sigue"
    return {
        "embeds": [
            {
                "title": f"🔁 {len(ya_avisados)} que ya te avise y {plural} adelantadas",
                "description": "\n".join(dentro),
                "color": COLOR_REPETIDO,
            }
        ]
    }


def _venta_line(venta: Venta) -> str:
    """Una linea del aviso: que se ha vendido y cuanto llega al buzon."""
    nombre = venta.subasta.item_name
    if len(nombre) > MAX_ITEM_NAME:
        nombre = nombre[: MAX_ITEM_NAME - 1].rstrip() + "…"
    if venta.subasta.ilvl:
        # Con el mismo objeto puesto a varios ilvl, sin esto no sabes cual se ha
        # vendido y la unica forma de comprobarlo es el buzon.
        nombre += f" ({venta.subasta.ilvl})"
    if venta.subasta.quantity > 1:
        nombre += f" ×{venta.subasta.quantity}"
    return f"• {nombre} — **{format_gold(venta.neto_gold)} g**"


def build_venta_messages(ventas: Sequence[Venta]) -> list[dict[str, Any]]:
    """Un mensaje por personaje, con lo que se le ha vendido esta hora.

    Se agrupa por personaje por el mismo motivo que los undercuts: cada mensaje
    es un viaje al buzon de un personaje concreto. Las cifras van en neto, que
    es lo que de verdad te llega tras la comision de la casa de subastas.
    """
    if not ventas:
        return []

    shown = list(ventas[:MAX_DEALS_PER_RUN])

    por_personaje: dict[tuple[str, str, object], list[Venta]] = {}
    for venta in shown:
        clave = (
            venta.subasta.character,
            venta.subasta.realm,
            venta.subasta.account,
        )
        por_personaje.setdefault(clave, []).append(venta)

    messages: list[dict[str, Any]] = []
    for (character, _realm, account), suyas in por_personaje.items():
        quien = f"💰 {character}"
        if account is not None:
            quien += f" · WoW {account}"

        plural = "ventas" if len(suyas) != 1 else "venta"
        titulo = f"{quien} — {len(suyas)} {plural}"
        continuacion = f"{quien} · sigue"

        lineas = [_venta_line(v) for v in suyas]
        if len(suyas) > 1:
            total = sum(v.neto_gold for v in suyas)
            lineas.append(f"**Total: {format_gold(total)} g**")

        grupos = _repartir(lineas, MAX_EMBED_DESCRIPTION)
        for indice, grupo in enumerate(grupos):
            messages.append(
                {
                    "embeds": [
                        {
                            "title": titulo if indice == 0 else continuacion,
                            "description": "\n".join(grupo),
                            "color": COLOR_VENTA,
                            # La hora del volcado en que se noto la
                            # desaparicion, no la del envio. Discord la pinta en
                            # la zona horaria de quien lee.
                            "timestamp": suyas[0].detectada_at.isoformat(),
                        }
                    ]
                }
            )

    return messages


class DiscordNotifier:
    """Cliente minimo del webhook de Discord."""

    def __init__(
        self,
        webhook_url: str,
        session: requests.Session | None = None,
        timeout: int = 15,
        max_retries: int = 3,
        sleep: Any = None,
    ) -> None:
        if not webhook_url:
            raise DiscordError(
                "Falta DISCORD_WEBHOOK_URL.\n"
                "En Discord: Ajustes del canal > Integraciones > Webhooks > "
                "Nuevo webhook > Copiar URL. Ponlo en el fichero .env (en local) "
                "o en los secrets del repositorio (en GitHub Actions)."
            )
        self.webhook_url = webhook_url
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep if sleep is not None else time.sleep

    def send_deals(
        self,
        deals: Sequence[Deal],
        realm_names: Mapping[int, str],
        icon_urls: Mapping[int, str] | None = None,
        snapshot_at: datetime | None = None,
        compradores: Mapping[int, str] | None = None,
    ) -> list[Deal]:
        """Envia los chollos y devuelve exactamente los que se han entregado.

        Devolver la lista, y no un simple recuento, es lo que permite a quien
        llama marcar como avisados solo los que de verdad han salido. Marcarlos
        todos haria desaparecer para siempre los que no cupieron en el aviso.
        """
        messages = build_messages(
            deals, realm_names, icon_urls, snapshot_at, compradores
        )
        for message in messages:
            self._post(message)
        return deals_to_send(deals)

    def send_undercuts(
        self, undercuts: Sequence[Undercut], ya_avisados: Sequence[Undercut] = ()
    ) -> list[Undercut]:
        """Envia los undercuts y devuelve los que de verdad han salido.

        Como en `send_deals`, lo que no cabe no se marca como avisado y sale en
        la pasada siguiente.
        """
        for message in build_undercut_messages(undercuts, ya_avisados):
            self._post(message)
        return list(undercuts[:MAX_DEALS_PER_RUN])

    def send_ventas(self, ventas: Sequence[Venta]) -> list[Venta]:
        """Envia las ventas y devuelve las que de verdad han salido."""
        for message in build_venta_messages(ventas):
            self._post(message)
        return list(ventas[:MAX_DEALS_PER_RUN])

    def upsert_panel(self, payload: Mapping[str, Any], message_id: str | None) -> str | None:
        """Crea el mensaje del panel o reescribe el que ya existe.

        Devuelve el id del mensaje, que hay que guardar para poder reescribirlo
        en la pasada siguiente en vez de ir dejando uno nuevo cada hora.

        Si el guardado ya no existe (lo borraste, o se perdio la memoria), se
        crea uno nuevo en vez de fallar: el panel es informativo y no merece
        tumbar la pasada.
        """
        if message_id:
            respuesta = self._post_raw(
                f"{self.webhook_url}/messages/{message_id}", payload, method="PATCH"
            )
            if respuesta is not None and respuesta.status_code in (200, 204):
                return message_id
            log.warning(
                "El mensaje del panel %s ya no existe; creo uno nuevo.", message_id
            )

        # wait=true hace que Discord devuelva el mensaje creado, que es de donde
        # sale el id para poder reescribirlo despues.
        respuesta = self._post_raw(f"{self.webhook_url}?wait=true", payload)
        if respuesta is None or respuesta.status_code not in (200, 204):
            log.warning("No he podido publicar el panel.")
            return None

        try:
            return str(respuesta.json().get("id") or "") or None
        except requests.exceptions.JSONDecodeError:
            return None

    def _post_raw(
        self, url: str, payload: Mapping[str, Any], method: str = "POST"
    ) -> requests.Response | None:
        """Peticion suelta al webhook, sin reintentos ni excepciones.

        El panel es un extra: si falla, se avisa en el log y la pasada sigue.
        Los avisos de verdad usan `_post`, que si reintenta y protesta.
        """
        try:
            return self.session.request(
                method, url, json=payload, timeout=self.timeout
            )
        except requests.RequestException as exc:
            log.warning("Fallo hablando con Discord para el panel: %s", exc)
            return None

    def send_warning(self, title: str, text: str) -> None:
        """Aviso sobre el estado del propio bot, no sobre precios."""
        self._post(
            {
                "embeds": [
                    {"title": f"⚠️ {title}", "description": text, "color": COLOR_WARNING}
                ]
            }
        )

    def send_test(self) -> None:
        self._post(
            {
                "content": "✅ Prueba de conexion",
                "embeds": [
                    {
                        "title": "El vigilante de precios puede escribir aqui",
                        "description": (
                            "Si ves este mensaje, el webhook esta bien configurado. "
                            "Los avisos de chollos llegaran a este canal."
                        ),
                        "color": COLOR_STEAL,
                    }
                ],
            }
        )

    def _post(self, payload: Mapping[str, Any]) -> None:
        last_error = "motivo desconocido"

        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(
                    self.webhook_url, json=payload, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = str(exc)
            else:
                if response.status_code in (200, 204):
                    return
                if response.status_code == 429:
                    self._sleep(_discord_retry_after(response))
                    last_error = "Discord esta limitando los envios (HTTP 429)"
                    continue
                if response.status_code in (401, 403, 404):
                    raise DiscordError(
                        f"Discord rechaza el webhook (HTTP {response.status_code}). "
                        "Comprueba que la URL es correcta y que el webhook no se "
                        "ha borrado."
                    )
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"

            if attempt < self.max_retries:
                self._sleep(2**attempt)

        raise DiscordError(f"No he podido enviar el aviso a Discord: {last_error}")


def _discord_retry_after(response: requests.Response) -> float:
    """Segundos que Discord pide esperar tras un 429."""
    try:
        value = float(response.json().get("retry_after", 1.0))
    except (ValueError, AttributeError, requests.exceptions.JSONDecodeError):
        value = 1.0
    return min(max(value, 0.5), 60.0)


def realm_names_for(deals: Iterable[Deal], lookup) -> dict[int, str]:
    """Resuelve el nombre de cada reino implicado, una sola vez por reino."""
    names: dict[int, str] = {}
    for deal in deals:
        if deal.realm_id not in names:
            names[deal.realm_id] = lookup(deal.realm_id)
    return names
