package com.burixer.cobertura

import android.content.Context

/** Algo que tienes que comprar: un objeto a un ilvl, para ponerlo con un personaje. */
data class Encargo(val itemId: Int, val ilvl: Int?, val personaje: String)

/** Lo apuntado de un mismo objeto e ilvl, que se compra junto. */
data class Pedido(val itemId: Int, val ilvl: Int?, val personajes: List<String>)

/**
 * La lista de la compra.
 *
 * Vive solo en el movil: es tu lista de trabajo del momento, no configuracion,
 * y asi no depende de GitHub ni de tener conexion.
 */
object Compra {

    private const val PREFS = "compra"
    private const val CLAVE = "encargos"

    fun leer(context: Context): List<Encargo> =
        deTexto(prefs(context).getString(CLAVE, "") ?: "")

    fun guardar(context: Context, lista: List<Encargo>) {
        prefs(context).edit().putString(CLAVE, aTexto(lista)).apply()
    }

    fun alternar(lista: List<Encargo>, encargo: Encargo): List<Encargo> =
        if (encargo in lista) lista - encargo else lista + encargo

    /** Los encargos que forman `pedido`, que es lo que quita "Comprado". */
    fun delPedido(lista: List<Encargo>, pedido: Pedido): List<Encargo> =
        lista.filter { it.itemId == pedido.itemId && it.ilvl == pedido.ilvl }

    /**
     * Deshacer: vuelve a poner lo quitado en el sitio que tenia en `antes`, sin
     * repetir nada. Lo apuntado entre medias se queda, al final.
     */
    fun devolver(
        lista: List<Encargo>,
        quitados: List<Encargo>,
        antes: List<Encargo>,
    ): List<Encargo> {
        val vuelven = antes.filter { it in lista || it in quitados }
        return vuelven + lista.filter { it !in vuelven }
    }

    /**
     * Los encargos que ya estan puestos: ese personaje tiene ese objeto a ese
     * ilvl en la casa de subastas. Ya no hay que comprarlos.
     */
    fun yaPuestos(lista: List<Encargo>, cobertura: List<Cobertura>): List<Encargo> =
        lista.filter { encargo ->
            val variante = cobertura.firstOrNull { it.objeto.id == encargo.itemId }
                ?.variantes?.firstOrNull { it.ilvl == encargo.ilvl }
            variante?.tienen?.any { it.personaje == encargo.personaje } == true
        }

    /** En el orden en que los apuntaste. */
    fun agrupar(lista: List<Encargo>): List<Pedido> =
        lista.groupBy { it.itemId to it.ilvl }
            .map { (clave, encargos) -> Pedido(clave.first, clave.second, encargos.map { it.personaje }) }

    // Una linea por encargo, "id|ilvl|personaje". El ilvl va vacio en lo que no
    // escala. Los nombres de personaje no llevan '|' ni saltos de linea.
    fun aTexto(lista: List<Encargo>): String =
        lista.joinToString("\n") { "${it.itemId}|${it.ilvl ?: ""}|${it.personaje}" }

    fun deTexto(texto: String): List<Encargo> =
        texto.lines().mapNotNull { linea ->
            val partes = linea.split("|")
            if (partes.size != 3) return@mapNotNull null
            val id = partes[0].toIntOrNull() ?: return@mapNotNull null
            if (partes[2].isBlank()) return@mapNotNull null
            Encargo(id, partes[1].toIntOrNull(), partes[2])
        }

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
