"""Motor local del Asistente AyC (sin servicios externos).

1. Normaliza la pregunta (minúsculas, sin acentos ni signos).
2. Puntúa cada intención: frases completas, palabras clave y tolerancia a errores
   de tipeo (difflib).
3. Responde según el rol del usuario: si la gestión no le corresponde, se lo dice
   y le muestra lo que sí puede hacer.
"""
import re
import unicodedata
from difflib import SequenceMatcher

from flask import url_for

from app.asistente.conocimiento import (
    INTENCIONES, NOMBRES_ROL, OPCIONES_POR_ROL, SUGERENCIAS_INICIALES, TODOS,
)

UMBRAL = 1.0          # puntaje mínimo para considerar que entendimos la pregunta
SIMILITUD = 0.84      # tolerancia para errores de escritura

STOPWORDS = {
    "a", "al", "algo", "como", "con", "cual", "de", "del", "el", "en", "es", "esta", "este", "hacer",
    "hago", "la", "las", "lo", "los", "me", "mi", "mis", "para", "pero", "por", "puedo", "que", "quiero",
    "se", "si", "su", "sus", "un", "una", "uno", "y", "o", "tengo", "hay", "debo", "necesito", "favor",
    "ayudame", "ayuda", "dime", "explica", "explicame", "sistema", "pagina", "web", "ayc", "control",
}
# "ayuda" y "puedo" están como stopwords para palabras sueltas, pero siguen
# funcionando dentro de frases completas como "que puedo hacer".

PATRON_FOLIO = re.compile(r"\b(ord-[a-z0-9-]+)\b", re.IGNORECASE)


def normalizar(texto):
    texto = unicodedata.normalize("NFD", (texto or "").lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9ñ\s-]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


SUFIJOS = ("aciones", "acion", "amos", "emos", "imos", "ando", "iendo", "ados", "idos",
           "ada", "ado", "ida", "ido", "ar", "er", "ir", "as", "es", "os", "a", "e", "o", "s")


def raiz(palabra):
    """Lematizador ligero en español: 'registro', 'registrar' y 'registros' -> 'registr'."""
    for sufijo in SUFIJOS:
        if palabra.endswith(sufijo) and len(palabra) - len(sufijo) >= 3:
            return palabra[: -len(sufijo)]
    return palabra


def tokens(texto, quitar_stop=True):
    salida = []
    for t in normalizar(texto).split():
        if quitar_stop and t in STOPWORDS:
            continue
        salida.append(raiz(t))
    return salida


def _coincide(token, clave):
    if token == clave:
        return 1.0
    # En palabras largas se tolera un error más (ej. «cotisacion» → «cotizacion»)
    umbral = SIMILITUD - 0.04 if min(len(token), len(clave)) >= 5 else SIMILITUD
    if len(token) >= 3 and len(clave) >= 3 and SequenceMatcher(None, token, clave).ratio() >= umbral:
        return 0.75
    return 0.0


def _mejor_coincidencia(token, claves):
    return max((_coincide(token, c) for c in claves), default=0.0)


# Precalcula las claves normalizadas de cada intención
for _i in INTENCIONES:
    _i["_palabras"] = {raiz(normalizar(p)) for p in _i.get("palabras", [])}
    _i["_frases"] = [normalizar(f) for f in _i.get("frases", [])]
    _i["_frases_tokens"] = [tokens(f, quitar_stop=False) for f in _i.get("frases", [])]
    _i["_requiere"] = {raiz(normalizar(p)) for p in _i.get("requiere", [])}


def puntuar(intencion, texto_norm, toks):
    puntaje = 0.0
    # Frases: coincidencia exacta o todas sus palabras presentes
    for frase, ftoks in zip(intencion["_frases"], intencion["_frases_tokens"]):
        contenido = [ft for ft in ftoks if ft not in STOPWORDS]
        if frase and re.search(rf"\b{re.escape(frase)}\b", texto_norm):
            puntaje = max(puntaje, 3.0 + 0.6 * len(ftoks))
        elif len(contenido) >= 2 and all(_mejor_coincidencia(ft, toks) >= 0.75 for ft in contenido):
            puntaje = max(puntaje, 2.2 + 0.5 * len(contenido))
    # Palabras clave sueltas
    for t in toks:
        puntaje += _mejor_coincidencia(t, intencion["_palabras"])
    # Si la intención exige un tema y la pregunta no lo menciona, se penaliza
    if intencion["_requiere"] and not any(_mejor_coincidencia(t, intencion["_requiere"]) for t in toks):
        puntaje *= 0.35
    return puntaje


def clasificar(texto):
    texto_norm = normalizar(texto)
    toks = tokens(texto)
    if not texto_norm:
        return None, 0.0
    # Saludo corto: evita confundir "hola" con otras intenciones
    resultados = sorted(((puntuar(i, texto_norm, toks), i) for i in INTENCIONES),
                        key=lambda x: x[0], reverse=True)
    mejor_puntaje, mejor = resultados[0]
    return (mejor if mejor_puntaje >= UMBRAL else None), mejor_puntaje


def _puede(roles, rol):
    return roles == TODOS or rol in roles


def _enlaces(lista):
    salida = []
    for texto, endpoint, kwargs in lista or []:
        try:
            salida.append({"texto": texto, "url": url_for(endpoint, **kwargs)})
        except Exception:  # pragma: no cover - endpoint inexistente
            continue
    return salida


def _quien_puede(roles):
    nombres = [NOMBRES_ROL[r] for r in ("gestor", "ventas", "admin") if r in roles]
    if len(nombres) > 1:
        return ", el ".join(nombres[:-1]) + " o el " + nombres[-1]
    return nombres[0] if nombres else "otro rol"


# ---------------------------------------------------------------------------
# Respuestas dinámicas
# ---------------------------------------------------------------------------
def _respuesta_opciones(usuario):
    opciones = OPCIONES_POR_ROL.get(usuario.rol, [])
    return {
        "texto": f"Como {NOMBRES_ROL.get(usuario.rol, usuario.rol)} puedes:",
        "pasos": [texto for texto, _, _ in opciones],
        "enlaces": _enlaces([(t.split(":")[0].split(" y ")[0][:34], e, k) for t, e, k in opciones[:3]]),
        "sugerencias": SUGERENCIAS_INICIALES.get(usuario.rol, [])[1:],
    }


def _respuesta_dashboard(usuario):
    if usuario.rol == "cliente":
        texto = ("«Mi Portal» resume tus pedidos activos, los que van en ruta, los entregados y tus diseños, "
                 "además de la próxima entrega con su porcentaje de avance.")
    else:
        texto = ("El Dashboard muestra los indicadores principales (metraje disponible, insumos en alerta, "
                 "pedidos en producción y diseños), gráficas de pedidos por fase, salud del inventario, stock "
                 "contra mínimo y movimientos de la semana, las próximas entregas y la tabla de materia prima.")
        if usuario.rol == "admin":
            texto += " Como administrador también ves las solicitudes de acceso pendientes."
    return {"texto": texto}


def _respuesta_pedidos(usuario):
    from app.rastreo.servicios import pedidos_visibles
    pedidos = pedidos_visibles(usuario).all()
    activos = [p for p in pedidos if not p.entregado]
    en_ruta = [p for p in activos if p.estado == "En Ruta"]
    vencidos = [p for p in activos if p.alerta_entrega == "vencido"]
    sujeto = "Tienes" if usuario.rol == "cliente" else "Hay"
    texto = f"{sujeto} {len(activos)} pedido{'s' if len(activos) != 1 else ''} activo{'s' if len(activos) != 1 else ''}"
    texto += f", {len(en_ruta)} en ruta" if en_ruta else ""
    texto += f" y {len(vencidos)} vencido{'s' if len(vencidos) != 1 else ''}." if vencidos else "."
    proximos = sorted(activos, key=lambda p: p.fecha_limite)[:3]
    return {
        "texto": texto,
        "pasos": [f"{p.folio}: {p.estado} · límite {p.fecha_limite.strftime('%d/%m/%Y')}" for p in proximos],
        "enlaces": [{"texto": p.folio, "url": url_for("rastreo.detalle", folio=p.folio)} for p in proximos],
    }


def _respuesta_alertas(usuario):
    from app.models import Insumo
    alerta = [i for i in Insumo.query.filter(Insumo.activo.is_(True)).all() if i.alerta_stock != "ok"]
    alerta.sort(key=lambda i: i.cobertura)
    if not alerta:
        return {"texto": "¡Todo en orden! Ningún insumo está por debajo de su stock mínimo."}
    return {
        "texto": f"{len(alerta)} insumo{'s' if len(alerta) != 1 else ''} necesita{'n' if len(alerta) != 1 else ''} reabastecimiento:",
        "pasos": [f"{i.nombre}: {float(i.cantidad_disponible):,.2f} de {float(i.stock_minimo):,.0f} {i.unidad_medida.lower()} ({i.estado})"
                  for i in alerta[:6]],
    }


def _respuesta_folio(folio, usuario):
    from app.models import Pedido
    from app.rastreo.servicios import puede_ver_pedido
    pedido = Pedido.query.filter(Pedido.folio.ilike(folio)).first()
    if pedido is None or not puede_ver_pedido(pedido, usuario):
        return {"texto": f"No encontré el pedido {folio.upper()} entre los que puedes consultar. Revisa que el folio esté completo, por ejemplo ORD-20261026-001."}
    return {
        "texto": f"El pedido {pedido.folio} ({pedido.modelo_prenda}) está en «{pedido.estado}», con {pedido.progreso}% de avance.",
        "pasos": [f"Ubicación actual: {pedido.ubicacion_actual or 'Taller Principal'}",
                  f"Fecha límite: {pedido.fecha_limite.strftime('%d/%m/%Y')}"],
        "enlaces": [{"texto": "Ver rastreo", "url": url_for("rastreo.detalle", folio=pedido.folio)},
                    {"texto": "Ficha de la orden", "url": url_for("rastreo.ficha", folio=pedido.folio)}],
    }


DINAMICAS = {
    "__opciones__": _respuesta_opciones,
    "__dashboard__": _respuesta_dashboard,
    "__dato_pedidos__": _respuesta_pedidos,
    "__dato_alertas__": _respuesta_alertas,
}


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------
def responder(texto, usuario):
    """Devuelve un dict serializable: texto, pasos, enlaces, sugerencias, intencion."""
    texto = (texto or "").strip()[:300]
    if not texto:
        return {"texto": "Escríbeme tu pregunta sobre AyC Control.", "intencion": None}

    folio = PATRON_FOLIO.search(texto)
    if folio:
        r = _respuesta_folio(folio.group(1), usuario)
        r["intencion"] = "folio"
        return r

    # Mensajes como "ayuda" o "¿qué hago?" (sin palabras de contenido) -> opciones del rol
    if not tokens(texto) and any(p in normalizar(texto).split() for p in ("ayuda", "ayudame", "hacer", "hago", "puedo")):
        texto = "que opciones tengo"
    intencion, puntaje = clasificar(texto)
    if intencion is None:
        return {
            "texto": ("Solo puedo ayudarte con el uso de AyC Control: inventario, pedidos, rastreo, contactos, cotizaciones, compras, calidad, "
                      "diseños y tu cuenta. ¿Puedes reformular tu pregunta? Por ejemplo:"),
            "sugerencias": SUGERENCIAS_INICIALES.get(usuario.rol, SUGERENCIAS_INICIALES["cliente"]),
            "intencion": None,
        }

    if not _puede(intencion["roles"], usuario.rol):
        return {
            "texto": (f"Esa gestión la realiza el {_quien_puede(intencion['roles'])}. "
                      f"Con tu rol de {NOMBRES_ROL.get(usuario.rol, usuario.rol)} no tienes acceso a ella."),
            "sugerencias": ["¿Qué puedo hacer?"] + SUGERENCIAS_INICIALES.get(usuario.rol, [])[1:3],
            "intencion": intencion["id"],
            "restringido": True,
        }

    if intencion["respuesta"] in DINAMICAS:
        r = DINAMICAS[intencion["respuesta"]](usuario)
        r.setdefault("enlaces", _enlaces(intencion.get("enlaces")))
    else:
        r = {"texto": intencion["respuesta"], "pasos": intencion.get("pasos", []),
             "enlaces": _enlaces(intencion.get("enlaces"))}

    # Si puede ver la sección pero no ejecutar la acción, se lo aclaramos
    accion = intencion.get("accion_roles")
    if accion and usuario.rol not in accion:
        r["enlaces"] = [e for e in r.get("enlaces", [])]
        r["nota"] = f"Con tu rol puedes consultar esta sección; la acción la realiza el {_quien_puede(accion)}."

    r.setdefault("sugerencias", intencion.get("sugerencias", []))
    r["intencion"] = intencion["id"]
    return r


def sugerencias_iniciales(rol):
    return SUGERENCIAS_INICIALES.get(rol, SUGERENCIAS_INICIALES["cliente"])
