package com.burixer.cobertura

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
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AddShoppingCart
import androidx.compose.material.icons.filled.ShoppingCart
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Cuantos reinos se ensenan por pedido: los mas baratos, que es donde compras. */
private const val REINOS_POR_PEDIDO = 5

/**
 * El boton de apuntar a la lista de la compra, en las filas de lo que le falta
 * a un personaje. Relleno y dorado cuando ya esta apuntado.
 */
@Composable
internal fun BotonCompra(apuntado: Boolean, alPulsar: () -> Unit) {
    IconButton(onClick = alPulsar, modifier = Modifier.size(36.dp)) {
        Icon(
            imageVector = if (apuntado) Icons.Filled.ShoppingCart
            else Icons.Filled.AddShoppingCart,
            contentDescription = if (apuntado) "Quitar de la compra" else "Apuntar a la compra",
            tint = if (apuntado) MaterialTheme.colorScheme.primary
            else MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp),
        )
    }
}

@Composable
internal fun ListaCompra(
    encargos: List<Encargo>,
    catalogo: Catalogo,
    mercado: Mercado?,
    datos: Datos,
    precios: Precios,
    alComprar: (Pedido) -> Unit,
) {
    val pedidos = remember(encargos) { Compra.agrupar(encargos) }
    val mios = remember(datos, catalogo) { misReinos(datos, catalogo) }

    if (pedidos.isEmpty()) {
        Text(
            text = "No tienes nada apuntado. En «Le falta a» de un objeto, o en «Sin poner» " +
                "de un personaje, toca el carrito de la fila para apuntarlo aquí.",
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(16.dp),
        )
        return
    }
    if (mercado == null) {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(color = MaterialTheme.colorScheme.primary)
        }
        return
    }

    // Una tarjeta que vuelve (deshacer) por encima de lo que estas viendo
    // entraria fuera de la pantalla y pareceria que no ha vuelto: se lleva la
    // lista hasta ella.
    val estado = rememberLazyListState()
    var vistas by remember { mutableStateOf(pedidos.map { clave(it) }.toSet()) }
    LaunchedEffect(pedidos) {
        val nueva = pedidos.indexOfFirst { clave(it) !in vistas }
        vistas = pedidos.map { clave(it) }.toSet()
        if (nueva >= 0) estado.animateScrollToItem(nueva)
    }

    LazyColumn(
        state = estado,
        contentPadding = PaddingValues(16.dp, 12.dp, 16.dp, 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        items(pedidos, key = { clave(it) }) { pedido ->
            TarjetaPedido(pedido, catalogo, mercado, mios, datos, precios) { alComprar(pedido) }
        }
    }
}

@Composable
private fun TarjetaPedido(
    pedido: Pedido,
    catalogo: Catalogo,
    mercado: Mercado,
    mios: Map<String, List<Personaje>>,
    datos: Datos,
    precios: Precios,
    alComprar: () -> Unit,
) {
    val objeto = catalogo.objetos.firstOrNull { it.id == pedido.itemId }
    val producto = mercado.productos.firstOrNull { !it.mascota && it.id == pedido.itemId }
    val ofertas = producto?.variantes
        ?.firstOrNull { it.valor == pedido.ilvl }?.ofertas.orEmpty()
        .take(REINOS_POR_PEDIDO)
    val tope = when {
        objeto == null -> null
        objeto.escala -> objeto.escalones.firstOrNull { it.ilvl == pedido.ilvl }?.tope
        else -> objeto.tope
    }

    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        shape = RoundedCornerShape(10.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(14.dp, 12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icono(objeto?.icono ?: producto?.icono, 40.dp)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        text = objeto?.es ?: producto?.es ?: "Objeto ${pedido.itemId}",
                        fontSize = 15.sp,
                        fontWeight = FontWeight.Medium,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (pedido.ilvl != null) {
                        Text(
                            text = "ilvl ${pedido.ilvl}",
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                TextButton(onClick = alComprar) { Text("Comprado") }
            }

            // Lo que vale en el reino de cada uno: contra los reinos de abajo
            // es lo que te dice si sale a cuenta comprarlo.
            Spacer(Modifier.height(10.dp))
            Titulo("Para", "${pedido.personajes.size}")
            pedido.personajes.forEach { nombre ->
                val ficha = datos.personajes[nombre]
                Row(
                    Modifier
                        .fillMaxWidth()
                        .padding(vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Column(Modifier.weight(1f)) {
                        Text(mote(nombre), fontSize = 14.sp, fontWeight = FontWeight.Medium)
                        Text(
                            text = donde(ficha),
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    if (objeto != null) {
                        Column(horizontalAlignment = Alignment.End) {
                            DelReino(objeto, ficha?.reino.orEmpty(), precios, pedido.ilvl)
                        }
                    }
                }
            }

            Spacer(Modifier.height(10.dp))
            Titulo("Dónde comprarlo", "${ofertas.size}")
            if (ofertas.isEmpty()) {
                Text(
                    text = "Nadie lo vende ahora mismo en ningún reino de la región.",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
            ofertas.forEach { FilaOferta(it, mios, tope) }
        }
    }
}

private fun clave(pedido: Pedido) = "${pedido.itemId}|${pedido.ilvl}"
