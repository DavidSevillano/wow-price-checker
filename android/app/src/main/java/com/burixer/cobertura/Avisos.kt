package com.burixer.cobertura

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * El interruptor de avisos: pausar o reanudar lo que se manda a Discord.
 *
 * Igual que los topes, la app no escribe config.yaml: abre una issue
 * "Avisos: pausar" o "Avisos: reanudar" y el workflow avisos.yml la aplica.
 * Asi el token sigue sin permiso de escritura sobre el codigo.
 *
 * El estado de verdad es la linea `avisos_pausados:` de config.yaml, que se
 * lee en cada descarga. Mientras el workflow no la cambia, lo pedido queda como
 * pendiente, para que el interruptor no vuelva atras nada mas tocarlo.
 */
object Avisos {

    private const val PREFS = "cobertura"
    private const val CLAVE_REAL = "avisos_pausados"
    private const val CLAVE_PENDIENTE = "avisos_pendiente"

    /**
     * Cuanto se cree un pendiente. El workflow tarda un minuto en aplicarlo;
     * si a la media hora config.yaml sigue sin reflejarlo es que algo fallo, y
     * vale mas ensenar lo que dice config.yaml que un pendiente eterno.
     */
    private const val CADUCIDAD_MS = 30 * 60 * 1000L

    private val LINEA = Regex("""(?m)^\s+avisos_pausados:\s*(true|false)\b""")

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** Lo que dice config.yaml en la ultima descarga. Sin la linea, activos. */
    fun pausadosEnConfig(texto: String): Boolean =
        LINEA.find(texto)?.groupValues?.get(1) == "true"

    /** Apunta el estado de verdad y olvida el pendiente si ya coincide. */
    fun apuntarConfig(context: Context, config: String) {
        val real = pausadosEnConfig(config)
        val editor = prefs(context).edit().putBoolean(CLAVE_REAL, real)
        if (pendiente(context) == real) editor.remove(CLAVE_PENDIENTE)
        editor.apply()
    }

    /** Lo pedido desde el movil y todavia no aplicado, o null. */
    fun pendiente(context: Context): Boolean? {
        val bruto = prefs(context).getString(CLAVE_PENDIENTE, "") ?: ""
        if (bruto.isBlank()) return null
        val fila = runCatching { JSONObject(bruto) }.getOrNull() ?: return null
        if (System.currentTimeMillis() - fila.optLong("cuando") > CADUCIDAD_MS) return null
        return fila.optBoolean("pausar")
    }

    /** Lo que hay que ensenar: lo pedido si esta en camino, si no lo real. */
    fun pausados(context: Context): Boolean =
        pendiente(context) ?: prefs(context).getBoolean(CLAVE_REAL, false)

    /** El cuerpo de la issue. La etiqueta es el contrato con aplicar_avisos.py. */
    fun cuerpo(pausar: Boolean): String =
        "### Avisos\n\n" + (if (pausar) "Pausar" else "Reanudar") + "\n"

    suspend fun enviar(context: Context, pausar: Boolean): Result<Unit> =
        withContext(Dispatchers.IO) {
            val token = Repositorio.token(context)
            if (token.isBlank()) {
                return@withContext Result.failure(
                    IllegalStateException(
                        "Falta el token de GitHub. Abre los ajustes y pega uno con " +
                            "permiso de Issues: Read and write."
                    )
                )
            }
            val peticion = JSONObject()
                .put("title", if (pausar) "Avisos: pausar" else "Avisos: reanudar")
                .put("body", cuerpo(pausar))

            runCatching {
                Topes.abrirIssue(Repositorio.repo(context), token, peticion.toString())
                prefs(context).edit()
                    .putString(
                        CLAVE_PENDIENTE,
                        JSONObject()
                            .put("pausar", pausar)
                            .put("cuando", System.currentTimeMillis())
                            .toString(),
                    )
                    .apply()
            }
        }
}
