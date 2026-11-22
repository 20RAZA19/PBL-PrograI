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
        texto = ("El inicio muestra «Para hoy»: cuatro números de lo que tienes que atender según tu rol (aprobaciones, "
                 "vencidos, entregas de la semana, mensajes o insumos por reponer) y dos listas cortas con lo más urgente. "
                 "Debajo están el Centro de Atención y los indicadores de 90 días.")
        if usuario.rol == "admin":
            texto += " Las gráficas de tendencia están en «Reportes»."
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


def _respuesta_token(usuario):
    url = url_for("seguimiento.consulta")
    base = ("El token de seguimiento te deja consultar tus pedidos sin iniciar sesión: entra a «Consulta con tu token» "
            "en la pantalla de inicio y escribe el token junto con los últimos 4 dígitos de tu teléfono. Es solo de lectura.")
    if usuario.rol != "cliente":
        return {"texto": "El token de seguimiento es de cada cliente. " + base.replace("tus pedidos", "sus pedidos").replace("te deja", "le deja").replace("tu teléfono", "su teléfono"),
                "pasos": ["Un administrador lo genera o regenera en «Gestión de Usuarios» → editar al cliente."],
                "enlaces": [{"texto": "Consulta con token", "url": url}]}
    if usuario.token_seguimiento:
        tel = "".join(c for c in (usuario.telefono or "") if c.isdigit())
        pasos = [f"Tu token es: {usuario.token_seguimiento}",
                 f"Te pedirá los últimos 4 dígitos de tu teléfono ({'…' + tel[-4:] if len(tel) >= 4 else 'regístralo en Mi Perfil'})."]
        return {"texto": base, "pasos": pasos,
                "nota": "No lo compartas con personas ajenas a tu empresa. Si crees que alguien más lo tiene, pide a Arte y Color que lo regenere.",
                "enlaces": [{"texto": "Consultar con mi token", "url": url}]}
    return {"texto": "Todavía no tienes un token de seguimiento. " + base,
            "pasos": ["Pídelo a Arte y Color desde «Mensajes»: un administrador lo genera para tu cuenta."],
            "enlaces": [{"texto": "Escribir a ventas", "url": url_for("mensajes.lista")}]}


def _respuesta_solicitudes(usuario):
    from app.models import Solicitud
    q = Solicitud.query
    if usuario.rol == "cliente":
        if not usuario.cliente_id:
            return {"texto": "Tu cuenta aún no está vinculada a una empresa, por eso no tienes solicitudes. Pide a Arte y Color que la vincule."}
        q = q.filter_by(cliente_id=usuario.cliente_id)
        abiertas = q.filter(Solicitud.estado.in_(("enviada", "aprobada"))).order_by(Solicitud.creado_en.desc()).limit(5).all()
        if not abiertas:
            return {"texto": "No tienes solicitudes en curso. Puedes pedir prendas nuevas cuando quieras.",
                    "enlaces": [{"texto": "Solicitar prendas", "url": url_for("solicitudes.nueva")}]}
        return {"texto": f"Tienes {len(abiertas)} solicitud{'es' if len(abiertas) != 1 else ''} en curso:",
                "pasos": [f"{s.folio}: {s.estado_legible}" + (f" · acéptala antes del {s.vence_en.strftime('%d/%m/%Y')}"
                                                              if s.estado == "aprobada" and s.vence_en and not s.vencida else "")
                          for s in abiertas],
                "enlaces": [{"texto": s.folio, "url": url_for("solicitudes.detalle", solicitud_id=s.id)} for s in abiertas[:3]]}
    pendientes = q.filter_by(estado="enviada").order_by(Solicitud.creado_en).limit(5).all()
    total = q.filter_by(estado="enviada").count()
    esperando = q.filter_by(estado="aprobada").count()
    if not total:
        return {"texto": f"No hay solicitudes por revisar. {esperando} cotización{'es' if esperando != 1 else ''} espera{'n' if esperando != 1 else ''} respuesta del cliente."}
    return {"texto": f"Hay {total} solicitud{'es' if total != 1 else ''} por revisar (las más antiguas primero) y {esperando} esperando al cliente:",
            "pasos": [f"{s.folio} · {s.cliente.nombre if s.cliente else 'Cliente'} · {s.total_prendas:,} prendas" for s in pendientes],
            "enlaces": [{"texto": s.folio, "url": url_for("solicitudes.detalle", solicitud_id=s.id)} for s in pendientes[:3]]}


def _respuesta_cotizaciones(usuario):
    from app.models import Cotizacion
    q = Cotizacion.query.filter_by(estado="enviada")
    if usuario.rol == "cliente":
        q = q.filter_by(cliente_id=usuario.cliente_id or 0)
    vigentes = sorted((c for c in q.order_by(Cotizacion.fecha.desc()).limit(30) if not c.vencida),
                      key=lambda c: c.fecha_vencimiento)[:5]
    if not vigentes:
        return {"texto": "No hay cotizaciones esperando respuesta." if usuario.rol != "cliente"
                else "No tienes cotizaciones por responder."}
    sujeto = "Tienes" if usuario.rol == "cliente" else "Hay"
    return {"texto": f"{sujeto} {len(vigentes)} cotización{'es' if len(vigentes) != 1 else ''} por responder:",
            "pasos": [f"{c.folio}: {float(c.total):,.2f} $ · vence el {c.fecha_vencimiento.strftime('%d/%m/%Y')}" for c in vigentes],
            "enlaces": [{"texto": c.folio, "url": url_for("cotizaciones.detalle", cotizacion_id=c.id)} for c in vigentes[:3]]}


def _respuesta_entrega(usuario):
    from datetime import date
    from app.rastreo.servicios import pedidos_visibles
    from app.models import Pedido
    activos = [p for p in pedidos_visibles(usuario).order_by(Pedido.fecha_limite).limit(40) if not p.entregado][:5]
    if not activos:
        return {"texto": "No hay pedidos pendientes de entrega."}
    hoy = date.today()

    def cuando(p):
        d = (p.fecha_limite - hoy).days
        return "vencido" if d < 0 else ("hoy" if d == 0 else (f"en {d} día{'s' if d != 1 else ''}"))
    return {"texto": "Próximas entregas, de la más cercana a la más lejana:",
            "pasos": [f"{p.folio} · {p.modelo_prenda}: {p.fecha_limite.strftime('%d/%m/%Y')} ({cuando(p)}) · va en «{p.estado}», {p.progreso} %"
                      for p in activos],
            "enlaces": [{"texto": p.folio, "url": url_for("rastreo.detalle", folio=p.folio)} for p in activos[:3]]}


def _respuesta_mensajes(usuario):
    from app.mensajes.servicios import sin_leer_total
    n = sin_leer_total(usuario)
    if usuario.rol == "cliente":
        texto = "En «Mensajes» puedes escribir al equipo de ventas de Arte y Color y ver sus respuestas."
    else:
        texto = "En «Mensajes» respondes a los clientes. Las conversaciones se borran a los 30 días salvo que las marques como «Guardada»."
    texto += f" Ahora tienes {n} mensaje{'s' if n != 1 else ''} sin leer." if n else " No tienes mensajes sin leer."
    return {"texto": texto}


def _respuesta_metas(usuario):
    from app.metas.indicadores import evaluar, mes_actual, metas_de, monto_del_mes, nombre_mes
    anio, mes = mes_actual()
    evaluaciones = [evaluar(m, usuario, anio, mes) for m in metas_de(usuario, anio, mes)]
    if not evaluaciones:
        if usuario.rol == "admin":
            return {"texto": "Las metas del equipo se definen en «Metas e incentivos». Ahí ves el avance de cada persona y cierras el mes.",
                    "enlaces": [{"texto": "Metas e incentivos", "url": url_for("metas.equipo")}]}
        return {"texto": f"No tienes metas activas en {nombre_mes(anio, mes)}. El administrador las define."}
    total = sum(monto_del_mes(e) for e in evaluaciones)
    return {"texto": f"En {nombre_mes(anio, mes)} llevas {sum(e['cumplida'] for e in evaluaciones)} de {len(evaluaciones)} metas cumplidas "
                     f"y ${total:,.2f} de incentivo si el mes cerrara hoy:",
            "pasos": [f"{e['meta'].nombre}: {e['valor_texto']} de {e['objetivo_texto']} ({e['avance']} %)" for e in evaluaciones[:5]]}


DINAMICAS = {
    "__opciones__": _respuesta_opciones,
    "__dashboard__": _respuesta_dashboard,
    "__dato_pedidos__": _respuesta_pedidos,
    "__dato_alertas__": _respuesta_alertas,
    "__dato_token__": _respuesta_token,
    "__dato_solicitudes__": _respuesta_solicitudes,
    "__dato_cotizaciones__": _respuesta_cotizaciones,
    "__dato_entrega__": _respuesta_entrega,
    "__dato_mensajes__": _respuesta_mensajes,
    "__dato_metas__": _respuesta_metas,
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
            "texto": ("Solo puedo ayudarte con el uso de AyC Control: pedidos, rastreo, solicitudes, cotizaciones, mensajes, "
                      "inventario, compras, calidad, metas, diseños y tu cuenta (contraseña, token, WhatsApp). ¿Puedes reformular tu pregunta? Por ejemplo:"),
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
