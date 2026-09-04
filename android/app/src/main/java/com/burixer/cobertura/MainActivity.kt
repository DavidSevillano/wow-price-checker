package com.burixer.cobertura

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.SizeTransform
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.launch
import java.text.NumberFormat
import java.util.Locale

// Cortas a proposito: esto se usa con el juego abierto y a medio repartir un
// chollo, no es una app de contemplar. Si apagas las animaciones del sistema,
// Compose las salta solo.
private const val ENTRADA_MS = 260
private const val SALIDA_MS = 120

private val Oro = Color(0xFF8A6410)
private val OroOscuro = Color(0xFFDFB349)
private val Falta = Color(0xFFA83E30)
private val FaltaOscuro = Color(0xFFE08678)

private val EsquemaClaro = lightColorScheme(
    primary = Oro,
    onPrimary = Color.White,
    background = Color(0xFFEBEEF2),
    onBackground = Color(0xFF171A21),
    surface = Color.White,
    onSurface = Color(0xFF171A21),
    surfaceVariant = Color(0xFFE2E6EC),
    onSurfaceVariant = Color(0xFF5B6472),
    error = Falta,
    outline = Color(0xFFD5DAE1),
)

private val EsquemaOscuro = darkColorScheme(
    primary = OroOscuro,
    onPrimary = Color(0xFF171A21),
    background = Color(0xFF101317),
    onBackground = Color(0xFFE7EAF0),
    surface = Color(0xFF181C22),
    onSurface = Color(0xFFE7EAF0),
    surfaceVariant = Color(0xFF13161B),
    onSurfaceVariant = Color(0xFF99A2B1),
    error = FaltaOscuro,
    outline = Color(0xFF262C35),
)

/** '18,6k', '1,2M': lo justo para que quepan tres escalones en una fila. */
private fun oroCorto(valor: Long): String = when {
    valor >= 1_000_000 -> String.format(Locale("es", "ES"), "%.1fM", valor / 1_000_000.0)
    valor >= 1_000 -> String.format(Locale("es", "ES"), "%.1fk", valor / 1_000.0)
    else -> "$valor g"
}

private fun oro(valor: Long): String =
    NumberFormat.getIntegerInstance(Locale("es", "ES")).format(valor) + " g"

/** El sufijo comun de tus personajes no distingue nada, asi que estorba. */
private fun mote(nombre: String): String =
    if (nombre.length > 5 && nombre.lowercase().endsWith("sufij")) nombre.dropLast(5) else nombre

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(
                colorScheme = if (isSystemInDarkTheme()) EsquemaOscuro else EsquemaClaro
            ) {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    App()
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun App() {
    val context = LocalContext.current
    val alcance = rememberCoroutineScope()
    val avisos = remember { SnackbarHostState() }

    var catalogo by remember { mutableStateOf(Repositorio.catalogo(context)) }
    var datos by remember { mutableStateOf(Repositorio.datos(context)) }
    var precios by remember { mutableStateOf(Repositorio.precios(context)) }
    var cargando by remember { mutableStateOf(false) }
    var ajustes by remember { mutableStateOf(false) }
    var abierto by remember { mutableStateOf<Int?>(null) }

    // Topes enviados y todavia no confirmados. Se leen de disco porque la app se
    // muere al salir: en memoria moririan con ella y volverias a ver el numero
    // viejo justo despues de cambiarlo.
    var pendientes by remember { mutableStateOf(Topes.pendientes(context)) }
    var editando by remember { mutableStateOf<Variante?>(null) }

    val cobertura = remember(datos) { Calculo.cobertura(catalogo, datos) }
    val elegido = cobertura.firstOrNull { it.objeto.id == abierto }

    BackHandler(enabled = elegido != null) { abierto = null }

    // La descarga de al abrir no dice nada cuando sale bien: no has pedido nada,
    // y un aviso cada vez que entras acaba siendo ruido que se ignora. Los
    // fallos si se cuentan siempre, porque significan que lo que estas viendo no
    // es de ahora.
    fun actualizar(avisar: Boolean = true) {
        if (cargando) return
        cargando = true
        alcance.launch {
            Repositorio.actualizar(context)
                .onSuccess {
                    datos = it
                    // La misma descarga trae el catalogo y los precios, asi que
                    // se releen: si has tocado config.yaml, aqui aparece.
                    catalogo = Repositorio.catalogo(context)
                    precios = Repositorio.precios(context)
                    // La descarga ya ha borrado los pendientes que el catalogo
                    // nuevo confirma; esto releele lo que queda vivo.
                    pendientes = Topes.pendientes(context)
                    if (avisar) avisos.showSnackbar("Datos actualizados desde GitHub.")
                }
                .onFailure { fallo ->
                    avisos.showSnackbar(fallo.message ?: "No he podido actualizar.")
                }
            cargando = false
        }
    }

    // Al abrir, siempre. La activity muere al salir (ver el manifiesto), asi que
    // esto corre una vez por vez que entras y no en cada recomposicion.
    //
    // Sin token no se intenta: no hay de donde bajar, y saltaria el mismo error
    // cada vez que abres hasta que lo configuras.
    LaunchedEffect(Unit) {
        if (Repositorio.token(context).isNotBlank()) actualizar(avisar = false)
    }

    Scaffold(
        snackbarHost = { SnackbarHost(avisos) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface,
                ),
                navigationIcon = {
                    if (elegido != null) {
                        IconButton(onClick = { abierto = null }) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver")
                        }
                    }
                },
                title = {
                    Text(
                        text = elegido?.objeto?.es ?: "Quién no lo tiene",
                        fontWeight = FontWeight.Medium,
                        fontSize = if (elegido != null) 17.sp else 20.sp,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                },
                actions = {
                    if (cargando) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(22.dp).padding(end = 4.dp),
                            strokeWidth = 2.dp,
                            color = MaterialTheme.colorScheme.primary,
                        )
                    } else {
                        IconButton(onClick = { actualizar() }) {
                            Icon(Icons.Filled.Refresh, contentDescription = "Actualizar")
                        }
                    }
                    IconButton(onClick = { ajustes = true }) {
                        Icon(Icons.Filled.Settings, contentDescription = "Ajustes")
                    }
                },
            )
        },
    ) { relleno ->
        Box(Modifier.padding(relleno)) {
            // La pantalla entra por el lado hacia el que vas, como en cualquier
            // app: sin eso, abrir un objeto es un parpadeo y no se sabe si has
            // entrado o si se ha recargado la lista.
            AnimatedContent(
                targetState = abierto,
                transitionSpec = {
                    val entrada = tween<Float>(ENTRADA_MS, easing = FastOutSlowInEasing)
                    val salida = tween<Float>(SALIDA_MS, easing = FastOutSlowInEasing)
                    val haciaDentro = targetState != null
                    val desplazamiento = tween<IntOffset>(
                        ENTRADA_MS, easing = FastOutSlowInEasing
                    )
                    (slideInHorizontally(desplazamiento) { ancho ->
                        if (haciaDentro) ancho / 5 else -ancho / 5
                    } + fadeIn(entrada)) togetherWith
                        fadeOut(salida) using SizeTransform(clip = false)
                },
                label = "pantalla",
            ) { id ->
                val abiertoAhora = cobertura.firstOrNull { it.objeto.id == id }
                if (abiertoAhora == null) {
                    Listado(
                        cobertura = cobertura,
                        orden = catalogo.orden,
                        exportado = datos.exportado,
                        conDescarga = Repositorio.hayDescarga(context),
                        alPulsar = { abierto = it.objeto.id },
                    )
                } else {
                    Detalle(
                        cobertura = abiertoAhora,
                        datos = datos,
                        precios = precios,
                        personajes = catalogo.orden.size,
                        pendientes = pendientes,
                        // Sin token no se ofrece: el envio fallaria y el boton
                        // solo serviria para descubrirlo a base de tocarlo.
                        alTocarTope = if (Repositorio.token(context).isBlank()) null
                        else ({ editando = it }),
                    )
                }
            }
        }
    }

    editando?.let { variante ->
        val objeto = cobertura.first { c -> c.variantes.any { it === variante } }.objeto
        DialogoTope(
            objeto = objeto,
            variante = variante,
            pendiente = pendientes[Topes.clave(objeto.id, variante.ilvl)],
            alCerrar = { editando = null },
            alEnviar = { tope ->
                editando = null
                alcance.launch {
                    Topes.enviar(context, objeto, variante.ilvl, tope)
                        .onSuccess {
                            pendientes = Topes.pendientes(context)
                            avisos.showSnackbar(
                                "Tope enviado. Entra en vigor en la pasada siguiente."
                            )
                        }
                        .onFailure { fallo ->
                            avisos.showSnackbar(fallo.message ?: "No he podido enviarlo.")
                        }
                }
            },
        )
    }

    if (ajustes) {
        DialogoAjustes(
            tokenInicial = Repositorio.token(context),
            repoInicial = Repositorio.repo(context),
            alCerrar = { ajustes = false },
            alGuardar = { token, repo ->
                Repositorio.guardarAjustes(context, token, repo)
                ajustes = false
                actualizar()
            },
        )
    }
}

@Composable
private fun Listado(
    cobertura: List<Cobertura>,
    orden: List<String>,
    exportado: Long,
    conDescarga: Boolean,
    alPulsar: (Cobertura) -> Unit,
) {
    LazyColumn(contentPadding = PaddingValues(bottom = 24.dp)) {
        item {
            Column(Modifier.padding(16.dp, 12.dp, 16.dp, 6.dp)) {
                Text(
                    text = "De lo que más tienes puesto a lo que menos. Elige el objeto y " +
                        "el ilvl que llevas encima.",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (!conDescarga) {
                    Spacer(Modifier.height(8.dp))
                    // Sin decir la fecha, un aviso de "datos viejos" no dice
                    // nada: lo que importa es cuanto de viejos.
                    Text(
                        text = "Sin conectar. Estás viendo una copia del " +
                            "${fecha(exportado)} que vino dentro de la app y no cambia " +
                            "sola. Toca el engranaje y pega un token de GitHub para bajar " +
                            "tus subastas de ahora.",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        }

        items(cobertura, key = { it.objeto.id }) { fila ->
            Column(
                Modifier
                    .fillMaxWidth()
                    .clickable { alPulsar(fila) }
                    .padding(horizontal = 16.dp, vertical = 10.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icono(fila.objeto.icono, 40.dp)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(
                            text = fila.objeto.es,
                            fontSize = 15.sp,
                            fontWeight = FontWeight.Medium,
                            maxLines = 2,
                        )
                        Spacer(Modifier.height(5.dp))
                        Rejilla(fila, orden)
                    }
                    Spacer(Modifier.width(10.dp))
                    Column(horizontalAlignment = Alignment.End) {
                        Text(
                            text = "${fila.puestas}",
                            fontFamily = FontFamily.Monospace,
                            fontSize = 15.sp,
                            fontWeight = FontWeight.Medium,
                            color = if (fila.puestas == 0) MaterialTheme.colorScheme.error
                            else MaterialTheme.colorScheme.primary,
                        )
                        Text(
                            text = "${fila.conAlgo.size}/${orden.size}",
                            fontFamily = FontFamily.Monospace,
                            fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outline)
        }

        item {
            Text(
                text = "${orden.size} personajes vigilados · volcado del addon " +
                    fecha(exportado),
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(16.dp),
            )
        }
    }
}

/**
 * Un cuadrito por personaje, en tu orden. Dorado = lo tiene a algun ilvl.
 *
 * La posicion importa: asi el mismo hueco cae siempre en el mismo sitio y se
 * reconoce de un vistazo quien es sin leer nombres.
 */
@Composable
private fun Rejilla(fila: Cobertura, orden: List<String>) {
    Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        orden.forEach { personaje ->
            Box(
                Modifier
                    .size(6.dp)
                    .background(
                        color = if (personaje in fila.conAlgo) MaterialTheme.colorScheme.primary
                        else MaterialTheme.colorScheme.outline,
                        shape = RoundedCornerShape(1.dp),
                    )
            )
        }
    }
}

@Composable
private fun Detalle(
    cobertura: Cobertura,
    datos: Datos,
    precios: Precios,
    personajes: Int,
    pendientes: Map<String, Long> = emptyMap(),
    alTocarTope: ((Variante) -> Unit)? = null,
) {
    var variante by remember(cobertura.objeto.id) { mutableStateOf(cobertura.porDefecto) }

    Column(
        Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icono(cobertura.objeto.icono, 56.dp)
            Spacer(Modifier.width(12.dp))
            Column {
                Text(cobertura.objeto.es, fontSize = 17.sp, fontWeight = FontWeight.Medium)
                if (cobertura.objeto.en != cobertura.objeto.es) {
                    Text(
                        text = cobertura.objeto.en,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        if (cobertura.objeto.escala) {
            Spacer(Modifier.height(14.dp))
            Fichas(cobertura, variante) { variante = it }
        }

        Spacer(Modifier.height(14.dp))

        // Al cambiar de ilvl cambia todo lo de abajo. Cruzarlo, en vez de
        // sustituirlo de golpe, es lo que deja claro que sigues en el mismo
        // objeto y solo has movido el nivel.
        AnimatedContent(
            targetState = variante,
            transitionSpec = {
                val sube = (targetState.ilvl ?: 0) > (initialState.ilvl ?: 0)
                (slideInVertically(
                    tween(ENTRADA_MS, easing = FastOutSlowInEasing)
                ) { alto -> if (sube) alto / 12 else -alto / 12 } +
                    fadeIn(tween(ENTRADA_MS, easing = FastOutSlowInEasing))) togetherWith
                    fadeOut(tween(SALIDA_MS)) using SizeTransform(clip = false)
            },
            label = "variante",
        ) { actual ->
            Column {
                Veredicto(
                    variante = actual,
                    total = personajes,
                    pendiente = pendientes[Topes.clave(cobertura.objeto.id, actual.ilvl)],
                    // Solo se deja tocar un escalon que ya esta en tu tabla.
                    // Anadir uno nuevo es otra operacion, y esa sigue siendo
                    // trabajo de config.yaml.
                    alTocarTope = if (actual.vigilado && alTocarTope != null) {
                        { alTocarTope(actual) }
                    } else null,
                )

                Spacer(Modifier.height(18.dp))
                if (actual.faltan.isNotEmpty()) {
                    Titulo(
                        if (actual.ilvl != null) "Le falta a — ilvl ${actual.ilvl}"
                        else "Le falta a",
                        "${actual.faltan.size}",
                    )
                    Spacer(Modifier.height(8.dp))
                    actual.faltan.forEach { nombre ->
                        FichaFalta(nombre, datos, precios, cobertura.objeto, actual)
                    }
                    Spacer(Modifier.height(18.dp))
                }

                Titulo("Ya lo tiene puesto", "${actual.tienen.size}")
                Spacer(Modifier.height(8.dp))
                if (actual.tienen.isEmpty()) {
                    Text(
                        text = if (actual.ilvl != null)
                            "Nadie lo tiene a ilvl ${actual.ilvl} en el mercado."
                        else "Nadie. Este objeto no está en el mercado con ninguno de tus " +
                            "personajes.",
                        fontSize = 13.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                } else {
                    actual.tienen.forEach { puesta ->
                        FichaPersonaje(puesta.personaje, datos, puesta)
                    }
                }
                Spacer(Modifier.height(32.dp))
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Fichas(
    cobertura: Cobertura,
    elegida: Variante,
    alElegir: (Variante) -> Unit,
) {
    Column {
        cobertura.variantes.chunked(4).forEach { grupo ->
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                grupo.forEach { variante ->
                    FilterChip(
                        selected = variante === elegida,
                        onClick = { alElegir(variante) },
                        label = {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    text = "${variante.ilvl}",
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 13.sp,
                                )
                                Spacer(Modifier.width(5.dp))
                                Text(
                                    text = "${variante.tienen.size}",
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = 11.sp,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                            }
                        },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor =
                                MaterialTheme.colorScheme.primary.copy(alpha = 0.18f),
                            selectedLabelColor = MaterialTheme.colorScheme.onSurface,
                        ),
                        border = FilterChipDefaults.filterChipBorder(
                            enabled = true,
                            selected = variante === elegida,
                            borderColor = MaterialTheme.colorScheme.outline,
                            selectedBorderColor = MaterialTheme.colorScheme.primary,
                        ),
                    )
                }
            }
            Spacer(Modifier.height(6.dp))
        }
        if (cobertura.variantes.any { !it.vigilado }) {
            Text(
                text = "Los ilvl que no están en tu tabla de precios salen igual, " +
                    "porque tienes subastas puestas a ese nivel.",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun Veredicto(
    variante: Variante,
    total: Int,
    pendiente: Long? = null,
    alTocarTope: (() -> Unit)? = null,
) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (variante.faltan.isEmpty())
                MaterialTheme.colorScheme.surfaceVariant
            else MaterialTheme.colorScheme.error.copy(alpha = 0.12f)
        ),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            Modifier.padding(14.dp, 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (variante.faltan.isEmpty()) {
                Text(
                    text = "Lo tienen los $total. No hay hueco donde meterlo.",
                    fontSize = 14.sp,
                )
            } else {
                Text(
                    text = "${variante.faltan.size}",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.error,
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    text = if (variante.faltan.size == 1) "personaje sin ponerlo, de $total"
                    else "personajes sin ponerlo, de $total",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.error,
                    modifier = Modifier.weight(1f),
                )
            }
            // El tope y el mercado, juntos: es la comparacion que te dice si el
            // limite esta alto, y por eso este es el sitio para cambiarlo.
            //
            // Mientras el cambio esta en vuelo se ensena el enviado, no el del
            // catalogo, que sigue siendo el viejo hasta la pasada siguiente.
            (pendiente ?: variante.tope)?.let {
                Text(
                    text = "tope ${oro(it)}" + if (pendiente != null) " (pendiente)" else "",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                    color = if (pendiente != null) MaterialTheme.colorScheme.primary
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = if (alTocarTope != null) {
                        Modifier
                            .clickable(onClick = alTocarTope)
                            .padding(6.dp, 4.dp)
                    } else Modifier,
                )
            }
        }
    }
}

@Composable
private fun Titulo(texto: String, contador: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(
            text = texto.uppercase(),
            fontSize = 11.sp,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = contador,
            fontSize = 11.sp,
            fontFamily = FontFamily.Monospace,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun FichaPersonaje(nombre: String, datos: Datos, puesta: Puesta?) {
    val ficha = datos.personajes[nombre]
    val donde = buildString {
        ficha?.reino?.takeIf { it.isNotBlank() }?.let { append(it) }
        ficha?.cuenta?.let { if (isNotEmpty()) append(" · "); append("WoW $it") }
    }
    Row(
        Modifier
            .fillMaxWidth()
            .padding(vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier
                .width(3.dp)
                .height(34.dp)
                .background(
                    if (puesta == null) MaterialTheme.colorScheme.error
                    else MaterialTheme.colorScheme.primary
                )
        )
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(mote(nombre), fontSize = 15.sp, fontWeight = FontWeight.Medium)
            Text(
                text = donde,
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (puesta != null) {
            Column(horizontalAlignment = Alignment.End) {
                Text(
                    text = "desde ${oro(puesta.minOro)}",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.primary,
                )
                Text(
                    text = if (puesta.cuantas == 1) "1 subasta" else "${puesta.cuantas} subastas",
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

/**
 * Un personaje al que le falta el objeto, con lo que cuesta entrar en su reino.
 *
 * Que falte no basta para decidir. Si de tu ilvl no hay nada puesto pero al lado
 * hay uno mejor mas barato, el tuyo no lo compra nadie: eso sale cantado sin
 * tener que desplegar. Y al tocar aparece la escalera entera de ilvl del reino,
 * que es lo que deja poner precio con criterio.
 */
@Composable
private fun FichaFalta(
    nombre: String,
    datos: Datos,
    precios: Precios,
    objeto: Objeto,
    variante: Variante,
) {
    var desplegado by remember(nombre, variante.ilvl) { mutableStateOf(false) }

    val ficha = datos.personajes[nombre]
    val reino = ficha?.reino.orEmpty()
    val donde = buildString {
        reino.takeIf { it.isNotBlank() }?.let { append(it) }
        ficha?.cuenta?.let { if (isNotEmpty()) append(" · "); append("WoW $it") }
    }

    val consulta = precios.de(reino, objeto.id, variante.ilvl, objeto.escala)
    val pisa = if (objeto.escala) precios.pisa(reino, objeto.id, variante.ilvl) else null

    // Todos los ilvl del objeto, no solo los que tienen algo puesto: que uno
    // este vacio es justo lo que quieres ver, y por ausencia no se ve.
    val conPrecio = precios.escalera(reino, objeto.id).toMap()
    val escalera = if (objeto.escala) {
        (objeto.escalones.map { it.ilvl } + conPrecio.keys).distinct().sorted()
    } else {
        emptyList()
    }

    Column(
        Modifier
            .fillMaxWidth()
            .clickable(enabled = escalera.isNotEmpty()) { desplegado = !desplegado }
            .padding(vertical = 7.dp)
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier
                    .width(3.dp)
                    .height(34.dp)
                    .background(MaterialTheme.colorScheme.error)
            )
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(mote(nombre), fontSize = 15.sp, fontWeight = FontWeight.Medium)
                Text(
                    text = donde,
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            Column(horizontalAlignment = Alignment.End) {
                when (consulta) {
                    is Precios.Consulta.Hay -> {
                        Text(
                            text = "hay a ${oro(consulta.precio.oro)}",
                            fontFamily = FontFamily.Monospace,
                            fontSize = 13.sp,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        Text(
                            text = if (consulta.precio.cuantas == 1) "1 en venta"
                            else "${consulta.precio.cuantas} en venta",
                            fontSize = 11.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    is Precios.Consulta.Vacio -> Text(
                        text = "nadie lo vende ahí",
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.primary,
                    )
                    Precios.Consulta.SinDato -> Text(
                        text = "sin precio",
                        fontSize = 11.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }

        AnimatedVisibility(
            visible = pisa != null,
            enter = expandVertically(tween(ENTRADA_MS, easing = FastOutSlowInEasing)) +
                fadeIn(tween(ENTRADA_MS)),
            exit = shrinkVertically(tween(SALIDA_MS)) + fadeOut(tween(SALIDA_MS)),
        ) {
            Text(
                text = pisa?.let { "te pisa el ${it.first} a ${oro(it.second.oro)}" }.orEmpty(),
                fontSize = 12.sp,
                color = MaterialTheme.colorScheme.error,
                modifier = Modifier.padding(start = 13.dp, top = 3.dp),
            )
        }

        AnimatedVisibility(
            visible = desplegado && escalera.isNotEmpty(),
            enter = expandVertically(tween(ENTRADA_MS, easing = FastOutSlowInEasing)) +
                fadeIn(tween(ENTRADA_MS)),
            exit = shrinkVertically(tween(SALIDA_MS)) + fadeOut(tween(SALIDA_MS)),
        ) {
            Column(Modifier.padding(start = 13.dp, top = 6.dp)) {
                escalera.chunked(3).forEach { grupo ->
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        grupo.forEach { ilvl ->
                            Escalon(
                                ilvl = ilvl,
                                precio = conPrecio[ilvl],
                                tuyo = ilvl == variante.ilvl,
                                // Rojo el que te deja sin sitio: mejor que el
                                // tuyo y mas barato.
                                estorba = pisa != null && ilvl == pisa.first,
                            )
                        }
                    }
                    Spacer(Modifier.height(5.dp))
                }
            }
        }
    }
}

@Composable
private fun Escalon(ilvl: Int, precio: Precio?, tuyo: Boolean, estorba: Boolean) {
    val color = when {
        estorba -> MaterialTheme.colorScheme.error
        tuyo -> MaterialTheme.colorScheme.primary
        precio == null -> MaterialTheme.colorScheme.onSurfaceVariant
        else -> MaterialTheme.colorScheme.onSurface
    }
    Column(
        Modifier
            .width(88.dp)
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(6.dp))
            .padding(horizontal = 8.dp, vertical = 5.dp)
    ) {
        Text(
            text = if (tuyo) "$ilvl ←" else "$ilvl",
            fontFamily = FontFamily.Monospace,
            fontSize = 12.sp,
            fontWeight = if (tuyo) FontWeight.Medium else FontWeight.Normal,
            color = color,
        )
        Text(
            text = if (precio == null) "—" else oroCorto(precio.oro),
            fontFamily = FontFamily.Monospace,
            fontSize = 13.sp,
            color = color,
        )
        Text(
            text = if (precio == null) "vacío" else "${precio.cuantas} en venta",
            fontSize = 10.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun Icono(url: String?, tamano: androidx.compose.ui.unit.Dp) {
    Box(
        Modifier
            .size(tamano)
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(6.dp))
    ) {
        if (url != null) {
            AsyncImage(
                model = url,
                contentDescription = null,
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}

/**
 * Cambiar el tope de una variante.
 *
 * No escribe config.yaml: abre una issue que un workflow aplica. Por eso el
 * boton dice "Enviar" y no "Guardar", y por eso avisa de que tarda: prometer un
 * cambio inmediato seria mentir, y volverias a tocarlo creyendo que fallo.
 */
@Composable
private fun DialogoTope(
    objeto: Objeto,
    variante: Variante,
    pendiente: Long?,
    alCerrar: () -> Unit,
    alEnviar: (Long) -> Unit,
) {
    val actual = pendiente ?: variante.tope
    var texto by remember { mutableStateOf(actual?.toString().orEmpty()) }

    val nuevo = texto.filter { it.isDigit() }.toLongOrNull()
    val valido = nuevo != null && nuevo > 0

    AlertDialog(
        onDismissRequest = alCerrar,
        title = {
            Text(
                if (variante.ilvl != null) "Tope · ilvl ${variante.ilvl}" else "Tope"
            )
        },
        text = {
            Column {
                Text(
                    text = objeto.es,
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    text = if (actual != null) {
                        "Ahora: ${oro(actual)}" + if (pendiente != null) " (pendiente)" else ""
                    } else "Sin tope puesto.",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 13.sp,
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = texto,
                    onValueChange = { texto = it },
                    label = { Text("tope nuevo, en oro") },
                    singleLine = true,
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    text = "Se manda como una issue a GitHub. El tope entra en vigor " +
                        "en la pasada siguiente, como mucho dentro de una hora.",
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = { nuevo?.let(alEnviar) },
                enabled = valido && nuevo != actual,
            ) { Text("Enviar") }
        },
        dismissButton = {
            TextButton(onClick = alCerrar) { Text("Cancelar") }
        },
    )
}

@Composable
private fun DialogoAjustes(
    tokenInicial: String,
    repoInicial: String,
    alCerrar: () -> Unit,
    alGuardar: (String, String) -> Unit,
) {
    var token by remember { mutableStateOf(tokenInicial) }
    var repo by remember { mutableStateOf(repoInicial) }

    AlertDialog(
        onDismissRequest = alCerrar,
        title = { Text("Conectar con GitHub") },
        text = {
            Column {
                Text(
                    text = "Un token de acceso personal sobre el repositorio, que se " +
                        "queda en este móvil. Necesita Contents: Read-only para ver " +
                        "los datos, y Issues: Read and write para cambiar topes.",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Spacer(Modifier.height(12.dp))
                OutlinedTextField(
                    value = repo,
                    onValueChange = { repo = it },
                    label = { Text("usuario/repositorio") },
                    singleLine = true,
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it },
                    label = { Text("token") },
                    singleLine = true,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { alGuardar(token, repo) }) { Text("Guardar y actualizar") }
        },
        dismissButton = {
            TextButton(onClick = alCerrar) { Text("Cancelar") }
        },
    )
}

private fun fecha(exportado: Long): String {
    if (exportado <= 0L) return "desconocido"
    val formato = java.text.SimpleDateFormat("d MMM HH:mm", Locale("es", "ES"))
    return formato.format(java.util.Date(exportado * 1000))
}
