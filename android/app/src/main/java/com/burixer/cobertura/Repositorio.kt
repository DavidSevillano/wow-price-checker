package com.burixer.cobertura

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * De donde salen los datos.
 *
 * La app arranca con la foto que lleva dentro, para servir de algo antes de
 * configurar nada. Con un token de GitHub se baja el volcado de verdad del repo
 * privado y lo guarda en disco, asi que a partir de ahi tambien funciona sin
 * cobertura.
 */
object Repositorio {

    private const val PREFS = "cobertura"
    private const val CLAVE_TOKEN = "token"
    private const val CLAVE_REPO = "repo"
    private const val CLAVE_DESCARGA = "descargado_en"
    private const val FICHERO = "datos.json"
    private const val CATALOGO = "catalogo.json"
    private const val PRECIOS = "precios.json"

    // El catalogo y los precios los publica el workflow en su propia rama, para
    // no ensuciar el historial de main con un commit por hora.
    private const val RAMA_DATOS = "datos"

    const val REPO_POR_DEFECTO = "DavidSevillano/wow-price-checker"

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun token(context: Context): String = prefs(context).getString(CLAVE_TOKEN, "").orEmpty()

    fun repo(context: Context): String =
        prefs(context).getString(CLAVE_REPO, REPO_POR_DEFECTO).orEmpty().ifBlank { REPO_POR_DEFECTO }

    fun descargadoEn(context: Context): Long = prefs(context).getLong(CLAVE_DESCARGA, 0L)

    fun guardarAjustes(context: Context, token: String, repo: String) {
        prefs(context).edit()
            .putString(CLAVE_TOKEN, token.trim())
            .putString(CLAVE_REPO, repo.trim().ifBlank { REPO_POR_DEFECTO })
            .apply()
    }

    /** El catalogo descargado; si no hay ninguno todavia, el que trae la app. */
    fun catalogo(context: Context): Catalogo = Parser.catalogo(
        leerCache(context, CATALOGO)
            ?: context.assets.open("catalogo.json").bufferedReader().use { it.readText() }
    )

    /** Los precios de los reinos. Sin descarga todavia no hay ninguno. */
    fun precios(context: Context): Precios =
        leerCache(context, PRECIOS)?.let { runCatching { parsearPrecios(it) }.getOrNull() }
            ?: Precios.VACIOS

    private fun leerCache(context: Context, nombre: String): String? {
        val fichero = File(context.filesDir, nombre)
        if (!fichero.isFile) return null
        return runCatching { fichero.readText() }.getOrNull()
    }

    /** Lo ultimo descargado; si no hay nada todavia, la foto de la app. */
    fun datos(context: Context): Datos {
        val cache = File(context.filesDir, FICHERO)
        val texto = if (cache.isFile) {
            runCatching { cache.readText() }.getOrNull()
        } else {
            null
        } ?: context.assets.open("snapshot.json").bufferedReader().use { it.readText() }
        return Parser.datos(texto)
    }

    fun hayDescarga(context: Context): Boolean = File(context.filesDir, FICHERO).isFile

    /**
     * Baja el volcado del repo privado y lo deja guardado.
     *
     * Se leen las dos carpetas enteras porque cada maquina tuya escribe su
     * propio fichero: quedarse con uno solo perderia los personajes de la otra.
     */
    suspend fun actualizar(context: Context): Result<Datos> = withContext(Dispatchers.IO) {
        val token = token(context)
        if (token.isBlank()) {
            return@withContext Result.failure(
                IllegalStateException(
                    "Falta el token de GitHub. Abre los ajustes y pega uno de solo " +
                        "lectura para el repositorio."
                )
            )
        }
        val repo = repo(context)

        runCatching {
            val subastas = JSONArray()
            var exportado = 0L
            for (nombre in listar(repo, "mis_subastas", token)) {
                val fichero = JSONObject(leer(repo, "mis_subastas/$nombre", token))
                val array = fichero.optJSONArray("auctions") ?: JSONArray()
                for (i in 0 until array.length()) {
                    val subasta = array.getJSONObject(i)
                    exportado = maxOf(exportado, subasta.optLong("exportedAt", 0L))
                    subastas.put(subasta)
                }
            }

            val personajes = JSONArray()
            for (nombre in listar(repo, "mis_personajes", token)) {
                val fichero = JSONObject(leer(repo, "mis_personajes/$nombre", token))
                val array = fichero.optJSONArray("characters") ?: JSONArray()
                for (i in 0 until array.length()) personajes.put(array.getJSONObject(i))
            }

            val fusion = JSONObject()
                .put("version", 1)
                .put("exportado", exportado)
                .put("auctions", subastas)
                .put("characters", personajes)

            File(context.filesDir, FICHERO).writeText(fusion.toString())

            // El catalogo y los precios viven en otra rama y son opcionales: si
            // el workflow no los ha publicado todavia, las subastas que acabamos
            // de bajar siguen sirviendo.
            for (nombre in listOf(CATALOGO, PRECIOS)) {
                runCatching { leer(repo, nombre, token, RAMA_DATOS) }
                    .onSuccess { File(context.filesDir, nombre).writeText(it) }
            }

            // Un tope que enviaste y que el catalogo recien bajado ya trae deja
            // de estar pendiente. Va aqui y no en la pantalla porque el catalogo
            // solo cambia cuando se descarga.
            runCatching { Topes.limpiarConfirmados(context, catalogo(context)) }

            prefs(context).edit().putLong(CLAVE_DESCARGA, System.currentTimeMillis()).apply()
            Parser.datos(fusion.toString())
        }
    }

    private fun listar(repo: String, carpeta: String, token: String): List<String> {
        val cuerpo = peticion(
            "https://api.github.com/repos/$repo/contents/$carpeta",
            token,
            "application/vnd.github+json",
        )
        val array = JSONArray(cuerpo)
        return (0 until array.length())
            .map { array.getJSONObject(it) }
            .filter { it.optString("type") == "file" && it.optString("name").endsWith(".json") }
            .map { it.getString("name") }
    }

    private fun leer(
        repo: String,
        ruta: String,
        token: String,
        rama: String? = null,
    ): String = peticion(
        "https://api.github.com/repos/$repo/contents/$ruta" +
            if (rama != null) "?ref=$rama" else "",
        token,
        // Con este Accept, GitHub devuelve el fichero tal cual en vez de un
        // JSON con el contenido en base64.
        "application/vnd.github.raw",
    )

    private fun peticion(url: String, token: String, accept: String): String {
        val conexion = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("Accept", accept)
            setRequestProperty("X-GitHub-Api-Version", "2022-11-28")
            setRequestProperty("User-Agent", "cobertura-app")
            connectTimeout = 15_000
            readTimeout = 30_000
        }
        try {
            val codigo = conexion.responseCode
            if (codigo == 401 || codigo == 403) {
                throw IllegalStateException(
                    "GitHub rechaza el token ($codigo). Comprueba que no ha caducado y " +
                        "que da permiso de lectura de contenido sobre ese repositorio."
                )
            }
            if (codigo == 404) {
                throw IllegalStateException(
                    "GitHub no encuentra $url. Revisa el usuario y el nombre del " +
                        "repositorio en los ajustes."
                )
            }
            if (codigo !in 200..299) {
                throw IllegalStateException("GitHub ha respondido $codigo.")
            }
            return conexion.inputStream.bufferedReader().use { it.readText() }
        } finally {
            conexion.disconnect()
        }
    }
}
