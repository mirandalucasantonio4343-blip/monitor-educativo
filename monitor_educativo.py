import feedparser
import telebot
import time
import calendar
import os
from urllib.parse import quote_plus

# ==================================================================
#   MONITOR EDUCATIVO - PROVINCIA DE BUENOS AIRES + NACIÓN
#   Fuentes oficiales, sindicatos (FUDB), Legal y Técnica y normativa
#
#   Funciona en dos modos:
#   - LOCAL: corre en bucle infinito (para tu PC o un servidor propio).
#   - NUBE (GitHub Actions): con la variable RUN_ONCE=1 hace UN escaneo
#     y termina; el cron de GitHub lo vuelve a lanzar cada 15 minutos.
# ==================================================================

# ------------------------- CONFIGURACIÓN --------------------------
# En la nube, el token y el chat_id se leen de variables de entorno (Secrets).
# En local, si no existen, usa los valores de abajo.
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "PEGA_TU_NUEVO_TOKEN_AQUI")
CHAT_ID_TELEGRAM = os.environ.get("CHAT_ID_TELEGRAM", "6631546663")

# RUN_ONCE=1 -> un solo escaneo y sale (modo nube). Vacío -> bucle infinito (local).
RUN_ONCE = os.environ.get("RUN_ONCE") == "1"

INTERVALO_MINUTOS = 15      # cada cuánto escanea en modo local
HORAS_ANTIGUEDAD = 48       # solo envía noticias más nuevas que esto (evita avalancha)
MAX_POR_CICLO = 25          # tope de mensajes por ronda (seguridad anti-flood)
MAX_VISTOS = 8000           # cantidad de enlaces recordados (evita archivo infinito)

ARCHIVO_VISTOS = "enlaces_vistos.txt"

# User-Agent de navegador real: evita bloqueos 403 en varios servidores.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

bot = telebot.TeleBot(TOKEN_TELEGRAM)


def google_news(consulta):
    """Convierte una búsqueda en un feed RSS de Google News (Argentina, español).
    Forma confiable de monitorear entidades sin RSS propio (sindicatos, direcciones)."""
    return (f"https://news.google.com/rss/search?q={quote_plus(consulta)}"
            f"&hl=es-419&gl=AR&ceid=AR:es-419")


# --------------------------- FUENTES ------------------------------
FUENTES = [
    # ============ PROVINCIA DE BUENOS AIRES ============
    # -- Sindicatos del Frente de Unidad Docente Bonaerense (FUDB) --
    {"nombre": "SUTEBA", "ambito": "PBA", "filtrar": False,
     "url": google_news('"SUTEBA"'), "etiqueta": "🟦🏴 [SUTEBA]"},
    {"nombre": "FEB", "ambito": "PBA", "filtrar": False,
     "url": google_news('"FEB" docentes bonaerenses'), "etiqueta": "🟦🏴 [FEB]"},
    {"nombre": "UDOCBA", "ambito": "PBA", "filtrar": False,
     "url": google_news('"UDOCBA"'), "etiqueta": "🟦🏴 [UDOCBA]"},
    {"nombre": "SADOP", "ambito": "PBA", "filtrar": False,
     "url": google_news('"SADOP" Buenos Aires'), "etiqueta": "🟦🏴 [SADOP]"},
    {"nombre": "AMET", "ambito": "PBA", "filtrar": False,
     "url": google_news('"AMET" docentes Buenos Aires'), "etiqueta": "🟦🏴 [AMET]"},

    # -- Salario / paritarias provinciales --
    {"nombre": "Paritarias PBA", "ambito": "PBA", "filtrar": False,
     "url": google_news('paritaria docente provincia Buenos Aires'),
     "etiqueta": "🟦💰 [PARITARIAS PBA]"},

    # -- DGCyE y Dirección de Legal y Técnica Educativa --
    {"nombre": "DGCyE", "ambito": "PBA", "filtrar": False,
     "url": google_news('DGCyE OR "Dirección General de Cultura y Educación" Buenos Aires'),
     "etiqueta": "🟦📄 [DGCyE]"},
    {"nombre": "Legal y Técnica", "ambito": "PBA", "filtrar": False,
     "url": google_news('resolución OR disposición DGCyE educación provincia Buenos Aires'),
     "etiqueta": "🟦⚖️ [LEGAL Y TÉCNICA]"},
    {"nombre": "Calendario/Normativa", "ambito": "PBA", "filtrar": False,
     "url": google_news('calendario escolar OR normativa educación provincia Buenos Aires'),
     "etiqueta": "🟦📄 [NORMATIVA EDUCATIVA]"},

    # -- Boletín Oficial provincial (vía Google News; no tiene RSS propio) --
    {"nombre": "Boletín Oficial PBA", "ambito": "PBA", "filtrar": False,
     "url": google_news('"Boletín Oficial" provincia Buenos Aires educación docente'),
     "etiqueta": "🟦📑 [BOLETÍN OFICIAL PBA]"},

    # -- Feed oficial nativo del Portal ABC (si responde; si no, se saltea) --
   {"nombre": "Portal ABC", "ambito": "PBA", "filtrar": False,
 "url": google_news('site:abc.gob.ar'), "etiqueta": "🟦🏫 [PORTAL ABC]"},

    # ============ EDUCACIÓN NACIONAL ============
    {"nombre": "Secretaría Educación Nación", "ambito": "NACIÓN", "filtrar": False,
     "url": google_news('Secretaría de Educación Nación Argentina OR "Ministerio de Educación" Argentina'),
     "etiqueta": "🟥🏛️ [EDUCACIÓN NACIÓN]"},
    {"nombre": "Consejo Federal Educación", "ambito": "NACIÓN", "filtrar": False,
     "url": google_news('"Consejo Federal de Educación" resolución'),
     "etiqueta": "🟥📄 [CONSEJO FEDERAL - CFE]"},
    {"nombre": "Paritaria Nacional / FONID", "ambito": "NACIÓN", "filtrar": False,
     "url": google_news('paritaria nacional docente OR FONID Argentina'),
     "etiqueta": "🟥💰 [PARITARIA NACIONAL]"},
    {"nombre": "Financiamiento educativo", "ambito": "NACIÓN", "filtrar": False,
     "url": google_news('financiamiento educativo OR presupuesto educación Nación Argentina'),
     "etiqueta": "🟥💵 [FINANCIAMIENTO EDUCATIVO]"},

    # -- Boletín Oficial de la Nación (RSS nativo; si no responde, se saltea) --
    {"nombre": "Boletín Oficial Nación", "ambito": "NACIÓN", "filtrar": True,
     "url": "https://www.boletinoficial.gob.ar/rss/seccion_primera.xml",
     "etiqueta": "🟥📑 [BOLETÍN OFICIAL NACIÓN]"},
]

# --- Filtro de palabras clave (solo para las fuentes con filtrar=True) ---
PALABRAS_CLAVE = [
    "paritaria", "sueldo", "salario", "docente", "aumento", "haberes", "gremio", "bono",
    "resolución", "decreto", "disposición", "circular", "calendario escolar", "escuela",
    "educación", "educativo", "licitación", "subsidio", "infraestructura", "obra",
    "inscripción", "acto público", "licencia", "titularización", "estatuto",
]


# ----------------------- PERSISTENCIA DE VISTOS -------------------
def cargar_vistos():
    if not os.path.exists(ARCHIVO_VISTOS):
        return []
    with open(ARCHIVO_VISTOS, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]


def guardar_vistos(lista):
    """Guarda solo los últimos MAX_VISTOS enlaces (evita crecimiento infinito)."""
    recorte = lista[-MAX_VISTOS:]
    with open(ARCHIVO_VISTOS, "w", encoding="utf-8") as f:
        f.write("\n".join(recorte) + "\n")


# ------------------------- CONEXIÓN TELEGRAM ---------------------
def probar_conexion(enviar_aviso=True):
    """Verifica token y chat_id. En la nube no manda aviso (evita spam cada 15 min)."""
    try:
        info = bot.get_me(timeout=10)
        print(f"✅ Bot conectado: @{info.username}")
    except Exception as e:
        print(f"❌ ERROR: el TOKEN es inválido o fue revocado -> {e}")
        return False

    if not enviar_aviso:
        return True

    try:
        bot.send_message(
            CHAT_ID_TELEGRAM,
            "🟢 Monitor educativo iniciado.\n\n"
            "🟦 PBA: SUTEBA, FEB, UDOCBA, SADOP, AMET, DGCyE, Legal y Técnica, "
            "Boletín Oficial y paritarias.\n"
            "🟥 Nación: Secretaría de Educación, Consejo Federal, FONID/paritaria "
            "y Boletín Oficial nacional.\n\n"
            f"Escaneo cada {INTERVALO_MINUTOS} minutos."
        )
        print("✅ Mensaje de prueba enviado a tu chat.")
        return True
    except Exception as e:
        print(f"❌ ERROR al enviar mensaje de prueba: {e}")
        print("   Causa más común: nunca le mandaste /start al bot desde tu Telegram.")
        print("   Abrí el chat con tu bot, mandale /start y volvé a correr el script.")
        return False


# --------------------------- FILTROS -----------------------------
def es_reciente(entry):
    """True si la noticia fue publicada dentro de la ventana de antigüedad."""
    fecha = entry.get("published_parsed") or entry.get("updated_parsed")
    if not fecha:
        return False
    epoch = calendar.timegm(fecha)
    return (time.time() - epoch) <= HORAS_ANTIGUEDAD * 3600


def pasa_palabras_clave(entry, fuente):
    if not fuente["filtrar"]:
        return True
    texto = (entry.get("title", "") + " " + entry.get("summary", "")).lower()
    return any(palabra in texto for palabra in PALABRAS_CLAVE)


# -------------------------- ESCANEO PRINCIPAL --------------------
def obtener_feed(url, reintentos=2):
    """Descarga un feed con reintentos ante fallos de red."""
    feed = None
    for intento in range(reintentos + 1):
        feed = feedparser.parse(url, agent=USER_AGENT)
        if feed.entries:
            return feed
        if intento < reintentos:
            time.sleep(3)
    return feed


def monitorear(vistos_set, vistos_lista):
    print("\n" + "=" * 55)
    print(f"Escaneo iniciado ({time.strftime('%d/%m %H:%M')})")
    enviados = 0

    for fuente in FUENTES:
        if enviados >= MAX_POR_CICLO:
            print("Tope de mensajes por ciclo alcanzado. Corto acá.")
            break

        print(f"→ [{fuente['ambito']}] {fuente['nombre']}")
        feed = obtener_feed(fuente["url"])
        if not feed or not feed.entries:
            print("   ⚠️ Sin entradas (feed caído, bloqueado o sin resultados).")
            continue

        for entry in feed.entries:
            if enviados >= MAX_POR_CICLO:
                break
            enlace = entry.get("link", "")
            if not enlace or enlace in vistos_set:
                continue
            if not es_reciente(entry):
                continue
            if not pasa_palabras_clave(entry, fuente):
                continue

            titulo = entry.get("title", "Sin título")
            medio = ""
            if hasattr(entry, "source") and hasattr(entry.source, "title"):
                medio = f"\n🗞️ Medio: {entry.source.title}"

            mensaje = (
                f"{fuente['etiqueta']}\n\n"
                f"📌 {titulo}"
                f"{medio}\n\n"
                f"🔗 {enlace}"
            )

            try:
                bot.send_message(CHAT_ID_TELEGRAM, mensaje)
                print(f"   ✔️ {titulo[:65]}")
                vistos_set.add(enlace)
                vistos_lista.append(enlace)
                enviados += 1
                time.sleep(1)
            except Exception as e:
                print(f"   ❌ Error al enviar a Telegram: {e}")
                time.sleep(3)

    if enviados:
        guardar_vistos(vistos_lista)
        print(f"Ciclo terminado: {enviados} alerta(s) nueva(s).")
    else:
        # Guardamos igual para persistir la memoria en la nube.
        guardar_vistos(vistos_lista)
        print("Sin novedades nuevas en este ciclo.")


# ---------------------------- EJECUCIÓN --------------------------
if __name__ == "__main__":
    print("=== Monitor Educativo - PBA + Nación ===")
    print("Modo:", "NUBE (un escaneo)" if RUN_ONCE else "LOCAL (bucle)")

    # En la nube no mandamos el aviso de arranque en cada corrida.
    if not probar_conexion(enviar_aviso=not RUN_ONCE):
        raise SystemExit(1)

    vistos_lista = cargar_vistos()
    vistos_set = set(vistos_lista)
    print(f"Enlaces recordados: {len(vistos_set)}")

    if RUN_ONCE:
        monitorear(vistos_set, vistos_lista)
    else:
        while True:
            try:
                monitorear(vistos_set, vistos_lista)
            except Exception as e:
                print(f"Error controlado en el ciclo principal: {e}")
            print(f"Esperando {INTERVALO_MINUTOS} minutos...\n")
            time.sleep(INTERVALO_MINUTOS * 60)
