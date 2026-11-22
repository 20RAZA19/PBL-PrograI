"""Indicadores de las metas: cómo se mide el avance de cada persona en un mes.

Todo sale de datos que el sistema ya registra (quién movió cada pedido, quién
atendió cada solicitud, los registros de calidad). Nadie captura su propio avance.
"""
from calendar import monthrange
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.extensions import db
from app.models import (Cotizacion, EventoRastreo, Meta, PagoIncentivo, Pedido, RegistroCalidad,
                        ROLES_CON_METAS, Solicitud, Usuario)

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
CERO = Decimal("0")


# --- Periodos ------------------------------------------------------------------
def rango_mes(anio, mes):
    inicio = datetime(anio, mes, 1)
    fin = datetime(anio + (mes == 12), 1 if mes == 12 else mes + 1, 1)
    return inicio, fin


def mes_actual():
    hoy = datetime.now()
    return hoy.year, hoy.month


def mover_mes(anio, mes, pasos):
    total = anio * 12 + (mes - 1) + pasos
    return total // 12, total % 12 + 1


def nombre_mes(anio, mes):
    return f"{MESES[mes - 1]} {anio}"


def mes_terminado(anio, mes):
    return rango_mes(anio, mes)[1] <= datetime.now()


def dias_restantes(anio, mes):
    if (anio, mes) != mes_actual():
        return 0
    return monthrange(anio, mes)[1] - datetime.now().day + 1


# --- Cálculo de cada indicador ---------------------------------------------------
def _decimal(valor, decimales="0.01"):
    return Decimal(str(valor or 0)).quantize(Decimal(decimales), rounding=ROUND_HALF_UP)


def _eventos(usuario, inicio, fin, estado=None):
    q = EventoRastreo.query.filter(EventoRastreo.usuario_id == usuario.id,
                                   EventoRastreo.fecha >= inicio, EventoRastreo.fecha < fin)
    return q.filter(EventoRastreo.estado == estado) if estado else q


def _prendas_de(pedidos_ids):
    return db.session.query(db.func.coalesce(db.func.sum(Pedido.cantidad), 0)).filter(Pedido.id.in_(pedidos_ids)).scalar()


def prendas_terminadas(usuario, inicio, fin):
    ids = _eventos(usuario, inicio, fin, "Terminado").with_entities(EventoRastreo.pedido_id).distinct()
    return _decimal(_prendas_de(ids))


def fases_avanzadas(usuario, inicio, fin):
    return _decimal(_eventos(usuario, inicio, fin).filter(EventoRastreo.fase >= 2).count())


def prendas_entregadas(usuario, inicio, fin):
    """Prendas de los pedidos que la persona marcó «Entregado» dentro del periodo.

    Un pedido entregado antes del periodo no vuelve a contar aunque se marque otra vez.
    """
    ids = {i for (i,) in _eventos(usuario, inicio, fin, "Entregado").with_entities(EventoRastreo.pedido_id)}
    if not ids:
        return _decimal(0)
    antes = {i for (i,) in EventoRastreo.query.filter(EventoRastreo.estado == "Entregado", EventoRastreo.fecha < inicio,
                                                       EventoRastreo.pedido_id.in_(ids))
             .with_entities(EventoRastreo.pedido_id)}
    validos = ids - antes
    return _decimal(_prendas_de(list(validos))) if validos else _decimal(0)


def entregas_a_tiempo(usuario, inicio, fin):
    entregas = _eventos(usuario, inicio, fin, "Entregado").all()
    por_pedido = {}
    for e in entregas:                       # si se marcó dos veces, cuenta la primera
        if e.pedido_id not in por_pedido or e.fecha < por_pedido[e.pedido_id].fecha:
            por_pedido[e.pedido_id] = e
    if not por_pedido:
        return None
    a_tiempo = sum(1 for e in por_pedido.values()
                   if e.pedido.fecha_limite is None or e.fecha.date() <= e.pedido.fecha_limite)
    return _decimal(a_tiempo / len(por_pedido) * 100, "0.1")


def defectos_taller(usuario, inicio, fin):
    """Indicador de equipo: el mismo valor para todo el taller."""
    ids = (EventoRastreo.query.filter(EventoRastreo.estado == "Terminado", EventoRastreo.fecha >= inicio,
                                      EventoRastreo.fecha < fin)
           .with_entities(EventoRastreo.pedido_id).distinct())
    terminadas = _prendas_de(ids)
    if not terminadas:
        return None
    defectos = (db.session.query(db.func.coalesce(db.func.sum(RegistroCalidad.cantidad), 0))
                .filter(RegistroCalidad.tipo == "defecto", RegistroCalidad.fecha >= inicio,
                        RegistroCalidad.fecha < fin).scalar())
    return _decimal(defectos / terminadas * 100, "0.1")


def _atendidas(usuario, inicio, fin):
    return Solicitud.query.filter(Solicitud.atendida_por_id == usuario.id, Solicitud.respondida_en >= inicio,
                                  Solicitud.respondida_en < fin)


def _convertidas(usuario, inicio, fin):
    return Solicitud.query.filter(Solicitud.atendida_por_id == usuario.id, Solicitud.estado == "convertida",
                                  Solicitud.decidida_en >= inicio, Solicitud.decidida_en < fin)


def solicitudes_respondidas(usuario, inicio, fin):
    return _decimal(_atendidas(usuario, inicio, fin).count())


def solicitudes_convertidas(usuario, inicio, fin):
    return _decimal(_convertidas(usuario, inicio, fin).count())


def monto_vendido(usuario, inicio, fin):
    total = sum((s.total or CERO for s in _convertidas(usuario, inicio, fin)), CERO)
    cotizaciones = Cotizacion.query.filter(Cotizacion.usuario_id == usuario.id, Cotizacion.estado == "aceptada",
                                           Cotizacion.respondida_en >= inicio, Cotizacion.respondida_en < fin)
    total += sum((c.total for c in cotizaciones), CERO)
    return _decimal(total)


def respuesta_horas(usuario, inicio, fin):
    tiempos = [(s.respondida_en - s.creado_en).total_seconds() / 3600
               for s in _atendidas(usuario, inicio, fin) if s.creado_en]
    if not tiempos:
        return None
    return _decimal(sum(tiempos) / len(tiempos), "0.1")


INDICADORES = {
    "prendas_entregadas": {
        "nombre": "Prendas entregadas", "rol": "gestor", "unidad": "prendas", "formato": "entero",
        "mayor_mejor": True, "equipo": False, "calcular": prendas_entregadas,
        "descripcion": "Prendas de los pedidos que la persona marcó como «Entregado» dentro del periodo de la meta. "
                       "No cuentan las entregas anteriores ni posteriores."},
    "prendas_terminadas": {
        "nombre": "Prendas terminadas", "rol": "gestor", "unidad": "prendas", "formato": "entero",
        "mayor_mejor": True, "equipo": False, "calcular": prendas_terminadas,
        "descripcion": "Prendas de los pedidos que la persona pasó a «Terminado» durante el periodo."},
    "fases_avanzadas": {
        "nombre": "Avances de fase registrados", "rol": "gestor", "unidad": "avances", "formato": "entero",
        "mayor_mejor": True, "equipo": False, "calcular": fases_avanzadas,
        "descripcion": "Veces que la persona movió un pedido a corte, costura, terminado, ruta o entregado."},
    "entregas_a_tiempo": {
        "nombre": "Entregas a tiempo", "rol": "gestor", "unidad": "%", "formato": "porcentaje",
        "mayor_mejor": True, "equipo": False, "calcular": entregas_a_tiempo,
        "descripcion": "De los pedidos que la persona marcó como entregados, cuántos llegaron en o antes de la fecha límite."},
    "defectos_taller": {
        "nombre": "Prendas con defecto (todo el taller)", "rol": "gestor", "unidad": "%", "formato": "porcentaje",
        "mayor_mejor": False, "equipo": True, "calcular": defectos_taller,
        "descripcion": "Prendas con defecto del periodo entre las prendas terminadas por el taller. Mientras más bajo, mejor."},
    "solicitudes_respondidas": {
        "nombre": "Solicitudes respondidas", "rol": "ventas", "unidad": "solicitudes", "formato": "entero",
        "mayor_mejor": True, "equipo": False, "calcular": solicitudes_respondidas,
        "descripcion": "Solicitudes de clientes que la persona aprobó o denegó durante el periodo."},
    "solicitudes_convertidas": {
        "nombre": "Solicitudes que pasaron a producción", "rol": "ventas", "unidad": "solicitudes",
        "formato": "entero", "mayor_mejor": True, "equipo": False, "calcular": solicitudes_convertidas,
        "descripcion": "Solicitudes atendidas por la persona que el cliente aceptó durante el periodo."},
    "monto_vendido": {
        "nombre": "Monto vendido", "rol": "ventas", "unidad": "$", "formato": "dinero",
        "mayor_mejor": True, "equipo": False, "calcular": monto_vendido,
        "descripcion": "Total de las solicitudes y cotizaciones de la persona que el cliente aceptó durante el periodo."},
    "respuesta_horas": {
        "nombre": "Tiempo de respuesta promedio", "rol": "ventas", "unidad": "horas", "formato": "decimal",
        "mayor_mejor": False, "equipo": False, "calcular": respuesta_horas,
        "descripcion": "Horas entre que llega una solicitud y la persona la responde. Mientras más bajo, mejor."},
}


def formatear(valor, indicador):
    if valor is None:
        return "Sin datos"
    info = INDICADORES[indicador]
    v = Decimal(valor)
    if info["formato"] == "dinero":
        return f"${v:,.2f}"
    if info["formato"] == "porcentaje":
        return f"{v:.1f} %".replace(".0 %", " %")
    if info["formato"] == "decimal":
        return f"{v:.1f} {info['unidad']}"
    return f"{int(v):,} {info['unidad']}"


# --- Evaluación de una meta --------------------------------------------------------
def ventana(meta, anio, mes):
    """Fechas que mide la meta: su periodo completo, o el mes si no tiene periodo."""
    if meta.tiene_periodo:
        return (datetime.combine(meta.fecha_inicio, datetime.min.time()),
                datetime.combine(meta.fecha_fin, datetime.min.time()) + timedelta(days=1))
    return rango_mes(anio, mes)


def se_liquida_en(meta, anio, mes):
    """El incentivo de una meta con periodo se paga en el mes en que termina."""
    return not meta.tiene_periodo or (meta.fecha_fin.year, meta.fecha_fin.month) == (anio, mes)


def evaluar(meta, usuario, anio, mes):
    """Avance de `usuario` en `meta` (en su periodo, o en el mes) y el incentivo que le corresponde."""
    info = INDICADORES[meta.indicador]
    inicio, fin = ventana(meta, anio, mes)
    valor = info["calcular"](usuario, inicio, fin)
    objetivo = Decimal(meta.objetivo or 0)
    incentivo = Decimal(meta.incentivo or 0)

    if valor is None:
        avance, cumplida = 0, False
    elif info["mayor_mejor"]:
        avance = 100 if objetivo <= 0 else min(100, float(valor / objetivo * 100))
        cumplida = valor >= objetivo
    else:
        cumplida = valor <= objetivo
        avance = 100 if cumplida else (float(objetivo / valor * 100) if valor > 0 else 100)

    parcial = bool(not cumplida and meta.umbral_parcial and valor is not None and avance >= meta.umbral_parcial)
    ganado = incentivo if cumplida else (_decimal(incentivo / 2) if parcial else CERO)
    falta = None
    if valor is not None and not cumplida:
        falta = formatear(objetivo - valor if info["mayor_mejor"] else valor - objetivo, meta.indicador)
    return {
        "meta": meta, "info": info, "valor": valor, "objetivo": objetivo,
        "valor_texto": formatear(valor, meta.indicador), "objetivo_texto": formatear(objetivo, meta.indicador),
        "avance": int(avance), "cumplida": cumplida, "parcial": parcial, "sin_datos": valor is None,
        "ganado": ganado, "incentivo": incentivo, "falta": falta,
        "liquida_aqui": se_liquida_en(meta, anio, mes),
        "mes_liquidacion": nombre_mes(meta.fecha_fin.year, meta.fecha_fin.month) if meta.tiene_periodo else None,
        "por_empezar": meta.tiene_periodo and inicio > datetime.now(),
    }


def monto_del_mes(ev):
    """Lo que la evaluación aporta al mes: lo fijado al cerrar, o lo estimado si se liquida ese mes."""
    if ev.get("pago"):
        return ev["pago"].monto
    return ev["ganado"] if ev["liquida_aqui"] else CERO


def metas_de(usuario, anio=None, mes=None):
    """Metas activas que aplican a la persona (las de su rol y las personales).

    Con `anio` y `mes`, solo las que tienen su periodo dentro de ese mes (o no tienen periodo).
    """
    metas = [m for m in Meta.query.filter(Meta.activa.is_(True)).order_by(Meta.id)
             if m.aplica_a(usuario) and m.indicador in INDICADORES]
    if anio and mes:
        inicio, fin = (f.date() for f in rango_mes(anio, mes))
        metas = [m for m in metas if m.vigente_en(inicio, fin)]
    return metas


def personas_con_metas():
    """Equipo con alguna meta activa: roles con metas y personas con metas propias."""
    personales = {m.usuario_id for m in Meta.query.filter(Meta.activa.is_(True), Meta.usuario_id.isnot(None))}
    roles = {m.rol for m in Meta.query.filter(Meta.activa.is_(True), Meta.usuario_id.is_(None))}
    return (Usuario.query.filter(Usuario.activo.is_(True), Usuario.estado_permiso == "aprobado",
                                 db.or_(Usuario.rol.in_(list(roles & set(ROLES_CON_METAS)) or ["__ninguno__"]),
                                        Usuario.id.in_(list(personales) or [0])))
            .order_by(Usuario.rol, Usuario.nombre).all())


def resumen_equipo(anio, mes):
    """Por persona: sus metas con el avance del mes y el total de incentivos.

    Si el mes ya se cerró, el monto viene de los pagos guardados (no cambia aunque
    luego se editen las metas); si no, es una estimación con los datos actuales.
    """
    pagos = {(p.usuario_id, p.meta_id): p for p in PagoIncentivo.query.filter_by(anio=anio, mes=mes)}
    filas = []
    for persona in personas_con_metas():
        evaluaciones = []
        for meta in metas_de(persona, anio, mes):
            ev = evaluar(meta, persona, anio, mes)
            ev["pago"] = pagos.get((persona.id, meta.id))
            evaluaciones.append(ev)
        if not evaluaciones:
            continue
        cerrados = [e["pago"] for e in evaluaciones if e["pago"]]
        total = sum((monto_del_mes(e) for e in evaluaciones), CERO)
        filas.append({"usuario": persona, "evaluaciones": evaluaciones, "total": total,
                      "cumplidas": sum(1 for e in evaluaciones if e["cumplida"]),
                      "pagado": bool(cerrados) and all(p.estado == "pagado" for p in cerrados)})
    return filas


def cerrar_mes(anio, mes):
    """Fija el incentivo de cada persona y meta en el mes. Los ya pagados no se tocan;
    los pendientes se recalculan con los datos actuales."""
    creados, total = 0, CERO
    for fila in resumen_equipo(anio, mes):
        for ev in fila["evaluaciones"]:
            pago = ev["pago"]
            if not ev["liquida_aqui"] or (pago and pago.estado == "pagado"):
                continue
            if pago is None:
                pago = PagoIncentivo(usuario_id=fila["usuario"].id, meta_id=ev["meta"].id, anio=anio, mes=mes)
                db.session.add(pago)
                creados += 1
            pago.meta_nombre = ev["meta"].nombre
            pago.valor = ev["valor"]
            pago.objetivo = ev["objetivo"]
            pago.avance = ev["avance"]
            pago.monto = ev["ganado"]
            total += ev["ganado"]
    return creados, total
