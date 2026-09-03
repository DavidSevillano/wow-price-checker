package com.burixer.cobertura

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import kotlinx.coroutines.launch
import java.text.NumberFormat
import java.util.Locale

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

    val cobertura = remember(datos) { Calculo.cobertura(catalogo, datos) }
    val elegido = cobertura.firstOrNull { it.objeto.id == abierto }

    BackHandler(enabled = elegido != null) { abierto = null }

    fun actualizar() {
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
                    avisos.showSnackbar("Datos actualizados desde GitHub.")
                }
                .onFailure { fallo ->
                    avisos.showSnackbar(fallo.message ?: "No he podido actualizar.")
                }
            cargando = false
        }
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
            if (elegido == null) {
                Listado(
                    cobertura = cobertura,
                    orden = catalogo.orden,
                    exportado = datos.exportado,
                    conDescarga = Repositorio.hayDescarga(context),
                    alPulsar = { abierto = it.objeto.id },
                )
            } else {
                Detalle(elegido, datos, precios, catalogo.orden.size)
            }
        }
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
        Veredicto(variante, personajes)

        Spacer(Modifier.height(18.dp))
        if (variante.faltan.isNotEmpty()) {
            Titulo(
                if (variante.ilvl != null) "Le falta a — ilvl ${variante.ilvl}" else "Le falta a",
                "${variante.faltan.size}",
            )
            Spacer(Modifier.height(8.dp))
            variante.faltan.forEach { nombre ->
                // Lo que costaria ser el mas barato de SU reino: sin eso, saber
                // que le falta no dice si merece la pena entrar.
                val reino = datos.personajes[nombre]?.reino.orEmpty()
                FichaPersonaje(
                    nombre = nombre,
                    datos = datos,
                    puesta = null,
                    consulta = precios.de(
                        reino = reino,
                        itemId = cobertura.objeto.id,
                        ilvl = variante.ilvl,
                        escala = cobertura.objeto.escala,
                    ),
                )
            }
            Spacer(Modifier.height(18.dp))
        }

        Titulo("Ya lo tiene puesto", "${variante.tienen.size}")
        Spacer(Modifier.height(8.dp))
        if (variante.tienen.isEmpty()) {
            Text(
                text = if (variante.ilvl != null)
                    "Nadie lo tiene a ilvl ${variante.ilvl} en el mercado."
                else "Nadie. Este objeto no está en el mercado con ninguno de tus personajes.",
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            variante.tienen.forEach { puesta ->
                FichaPersonaje(puesta.personaje, datos, puesta, null)
            }
        }
        Spacer(Modifier.height(32.dp))
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
private fun Veredicto(variante: Variante, total: Int) {
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
            variante.tope?.let {
                Text(
                    text = "tope ${oro(it)}",
                    fontFamily = FontFamily.Monospace,
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
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
private fun FichaPersonaje(
    nombre: String,
    datos: Datos,
    puesta: Puesta?,
    consulta: Precios.Consulta?,
) {
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
        } else if (consulta != null) {
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
                    text = "Un token de acceso personal de solo lectura sobre el " +
                        "repositorio. Se queda en este móvil.",
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
