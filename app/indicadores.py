"""Indicadores de gestión, recomendaciones del dashboard y datos de los gráficos.

Todo se calcula al vuelo con los datos actuales: no hay tablas extra.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import url_for

from app.models import (LINEAS_PRODUCCION, META_DEFECTOS_PCT, Cotizacion, Diseno, EventoRastreo, Insumo,
                        Movimiento, OrdenCompra, Pedido, RegistroCalidad, Usuario)

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

# Metas de cada indicador: (verde si ≥, amarillo si ≥) — o al revés cuando menor es mejor
META_PUNTUALIDAD = (90, 75)
META_MARGEN = (25, 15)
META_INVENTARIO = (85, 70)
META_CONVERSION = (50, 30)
MARGEN_MINIMO_PEDIDO = 15
DIAS_ESTANCADO = 7


def _semaforo(valor, verde, amarillo, menor_es_mejor=False):
    if valor is None:
        return "neutral"
    if menor_es_mejor:
        return "ok" if valor <= verde else ("warn" if valor <= amarillo else "danger")
    return "ok" if valor >= verde else ("warn" if valor >= amarillo else "danger")


# ---------------------------------------------------------------------------
# Indicadores base
# ---------------------------------------------------------------------------
def fecha_entrega_real(pedido):
    for e in reversed(pedido.eventos):
        if e.estado == "Entregado":
            return e.fecha.date()
    return None


def puntualidad(dias=90):
    """% de pedidos entregados a tiempo en el periodo. None si no hubo entregas."""
    desde = date.today() - timedelta(days=dias)
    entregados = [(p, fecha_entrega_real(p)) for p in Pedido.query.filter_by(estado="Entregado").all()]
    entregados = [(p, f) for p, f in entregados if f and f >= desde]
    if not entregados:
        return None, 0
    a_tiempo = sum(1 for p, f in entregados if f <= p.fecha_limite)
    return round(a_tiempo / len(entregados) * 100), len(entregados)


def margen_global(dias=90):
    """Margen ponderado (ganancia / ingreso) de los pedidos del periodo que se pueden costear."""
    desde = datetime.now() - timedelta(days=dias)
    ingreso, ganancia = Decimal("0"), Decimal("0")
    for p in Pedido.query.filter(Pedido.creado_en >= desde).all():
        if p.ingreso and p.ganancia_estimada is not None:
            ingreso += p.ingreso
            ganancia += p.ganancia_estimada
    if not ingreso:
        return None, Decimal("0")
    return round(float(ganancia / ingreso * 100), 1), ingreso


def tasas_por_linea(dias=90):
    """[{linea, producidas, afectadas, tasa, nivel, registros}] para el periodo."""
    desde = datetime.now() - timedelta(days=dias)
    pedidos = [p for p in Pedido.query.all() if (p.creado_en and p.creado_en >= desde) or not p.entregado]
    ids = {p.id for p in pedidos}
    registros = [r for r in RegistroCalidad.query.all() if r.pedido_id in ids]
    filas = []
    for linea, fase in LINEAS_PRODUCCION.items():
        producidas = sum(p.cantidad for p in pedidos if p.fase_actual >= fase)
        de_linea = [r for r in registros if r.linea == linea]
        afectadas = sum(r.cantidad for r in de_linea)
        tasa = round(afectadas / producidas * 100, 1) if producidas else None
        filas.append({
            "linea": linea, "producidas": producidas, "afectadas": afectadas, "tasa": tasa,
            "registros": len(de_linea), "abiertos": sum(1 for r in de_linea if not r.resuelto),
            "nivel": _semaforo(tasa, META_DEFECTOS_PCT, META_DEFECTOS_PCT * 2, menor_es_mejor=True)
            if tasa is not None else "neutral",
        })
    return filas


def tasa_defectos_global(dias=90):
    filas = tasas_por_linea(dias)
    desde = datetime.now() - timedelta(days=dias)
    pedidos = [p for p in Pedido.query.all() if (p.creado_en and p.creado_en >= desde) or not p.entregado]
    producidas = sum(p.cantidad for p in pedidos)
    afectadas = sum(f["afectadas"] for f in filas)
    return (round(afectadas / producidas * 100, 1) if producidas else None), afectadas


def conversion_cotizaciones():
    respondidas = Cotizacion.query.filter(Cotizacion.estado.in_(("aceptada", "rechazada"))).all()
    if not respondidas:
        return None
    return round(sum(1 for c in respondidas if c.estado == "aceptada") / len(respondidas) * 100)


def kpis(usuario):
    """Tarjetas de indicadores con semáforo para el dashboard."""
    insumos = Insumo.query.filter(Insumo.activo.is_(True)).all()
    sanos = round(sum(1 for i in insumos if i.alerta_stock == "ok") / len(insumos) * 100) if insumos else None
    valor_inv = sum((i.valor_inventario for i in insumos), Decimal("0"))
    punt, entregas = puntualidad()
    tasa, afectadas = tasa_defectos_global()

    tarjetas = [
        {"titulo": "Entregas a tiempo", "valor": f"{punt}%" if punt is not None else "—",
         "nivel": _semaforo(punt, *META_PUNTUALIDAD), "icono": "calendar-check",
         "detalle": f"{entregas} entregas · últimos 90 días", "meta": f"Meta ≥ {META_PUNTUALIDAD[0]}%"},
        {"titulo": "Prendas con defecto", "valor": f"{tasa}%" if tasa is not None else "—",
         "nivel": _semaforo(tasa, META_DEFECTOS_PCT, META_DEFECTOS_PCT * 2, menor_es_mejor=True),
         "icono": "shield-check", "detalle": f"{afectadas} prendas afectadas · 90 días",
         "meta": f"Meta ≤ {META_DEFECTOS_PCT:g}%"},
        {"titulo": "Inventario sin alertas", "valor": f"{sanos}%" if sanos is not None else "—",
         "nivel": _semaforo(sanos, *META_INVENTARIO), "icono": "boxes",
         "detalle": f"Valor en bodega ${valor_inv:,.0f}", "meta": f"Meta ≥ {META_INVENTARIO[0]}%"},
    ]
    if usuario.puede_ver_costos:
        margen, ingreso = margen_global()
        conv = conversion_cotizaciones()
        tarjetas.insert(1, {"titulo": "Margen de ganancia", "valor": f"{margen}%" if margen is not None else "—",
                            "nivel": _semaforo(margen, *META_MARGEN), "icono": "trending-up",
                            "detalle": f"Sobre ${ingreso:,.0f} vendidos · 90 días",
                            "meta": f"Meta ≥ {META_MARGEN[0]}%"})
        tarjetas.append({"titulo": "Cotizaciones ganadas", "valor": f"{conv}%" if conv is not None else "—",
                         "nivel": _semaforo(conv, *META_CONVERSION), "icono": "handshake",
                         "detalle": "Aceptadas / respondidas", "meta": f"Meta ≥ {META_CONVERSION[0]}%"})
    return tarjetas


# ---------------------------------------------------------------------------
# Recomendaciones (lo primero que ve el administrador)
# ---------------------------------------------------------------------------
NIVELES = {"critico": 0, "alerta": 1, "sugerencia": 2}


def _rec(nivel, icono, titulo, detalle, accion=None, items=None, roles=("admin",)):
    return {"nivel": nivel, "icono": icono, "titulo": titulo, "detalle": detalle,
            "accion": accion, "lista": items or [], "roles": roles}


def recomendaciones(usuario):
    """Lista priorizada de situaciones que requieren atención, filtrada por rol."""
    from app.compras.servicios import faltantes_para_pedidos

    hoy = date.today()
    recs = []
    activos = Pedido.query.filter(Pedido.estado != "Entregado").all()

    # 1. Pedidos vencidos
    vencidos = sorted([p for p in activos if p.fecha_limite < hoy], key=lambda p: p.fecha_limite)
    if vencidos:
        recs.append(_rec(
            "critico", "alarm-clock",
            f"{len(vencidos)} pedido{'s' if len(vencidos) != 1 else ''} vencido{'s' if len(vencidos) != 1 else ''} sin entregar",
            "Informa al cliente una nueva fecha y prioriza estas órdenes en el tablero.",
            ("Ver tablero", url_for("main.kanban_pedidos")),
            [f"{p.folio} · {p.cliente.nombre} · {-(p.fecha_limite - hoy).days} d de atraso · {p.estado}" for p in vencidos[:4]],
            roles=("admin", "gestor", "ventas")))

    # 2. Riesgo de atraso: vence en ≤ 3 días y aún no está terminado
    riesgo = sorted([p for p in activos if 0 <= (p.fecha_limite - hoy).days <= 3
                     and p.estado in ("Recibido", "En Corte", "En Costura")], key=lambda p: p.fecha_limite)
    if riesgo:
        recs.append(_rec(
            "critico" if any((p.fecha_limite - hoy).days <= 1 for p in riesgo) else "alerta", "hourglass",
            f"{len(riesgo)} pedido{'s' if len(riesgo) != 1 else ''} en riesgo de atraso",
            "Vencen en 3 días o menos y todavía no salen de producción. Considera horas extra o entregas parciales.",
            ("Ver tablero", url_for("main.kanban_pedidos")),
            [f"{p.folio} · vence en {(p.fecha_limite - hoy).days} d · {p.estado}" for p in riesgo[:4]],
            roles=("admin", "gestor")))

    # 3. Material insuficiente para producir los pedidos activos
    faltantes = faltantes_para_pedidos()
    if faltantes:
        recs.append(_rec(
            "critico", "package-x",
            f"Falta material para {len({p.folio for f in faltantes for p, _ in f['pedidos']})} pedido(s) activo(s)",
            "Con el stock actual y lo que viene en camino no alcanza para terminar lo que ya está comprometido.",
            ("Generar orden de compra", url_for("compras.index")),
            [f"{f['insumo'].nombre}: faltan {float(f['faltante']):,.0f} {f['insumo'].unidad_medida.lower()}" for f in faltantes[:4]],
            roles=("admin", "gestor")))

    # 4. Insumos críticos
    criticos = [i for i in Insumo.query.filter(Insumo.activo.is_(True)).all() if i.alerta_stock == "critico"]
    if criticos:
        recs.append(_rec(
            "alerta", "triangle-alert",
            f"{len(criticos)} insumo{'s' if len(criticos) != 1 else ''} en nivel crítico",
            "Están a la mitad del stock mínimo o menos. Revisa las compras sugeridas por proveedor.",
            ("Ver compras sugeridas", url_for("compras.index")),
            [f"{i.nombre}: {float(i.cantidad_disponible):,.0f} de {float(i.stock_minimo):,.0f} {i.unidad_medida.lower()}" for i in criticos[:4]],
            roles=("admin", "gestor")))

    # 5. Calidad: líneas sobre la meta y defectos abiertos
    for fila in tasas_por_linea():
        if fila["tasa"] is not None and fila["tasa"] > META_DEFECTOS_PCT:
            recs.append(_rec(
                "alerta" if fila["tasa"] <= META_DEFECTOS_PCT * 2 else "critico", "shield-alert",
                f"Línea de {fila['linea']}: {fila['tasa']}% de prendas con defectos",
                f"Supera la meta de {META_DEFECTOS_PCT:g}%. Revisa causas con el equipo y el estado de las máquinas.",
                ("Ver control de calidad", url_for("calidad.index")),
                [f"{fila['afectadas']} de {fila['producidas']:,} prendas · {fila['abiertos']} caso(s) sin resolver"],
                roles=("admin", "gestor")))
    abiertos = RegistroCalidad.query.filter_by(resuelto=False).count()
    if abiertos:
        recs.append(_rec(
            "sugerencia", "clipboard-check", f"{abiertos} caso{'s' if abiertos != 1 else ''} de calidad sin cerrar",
            "Registra la acción correctiva y márcalos como resueltos para medir el tiempo de respuesta.",
            ("Ver casos", url_for("calidad.index", estado="abiertos")), roles=("admin", "gestor")))

    # 6. Pedidos estancados (sin movimiento en la línea de tiempo)
    limite = datetime.now() - timedelta(days=DIAS_ESTANCADO)
    estancados = [p for p in activos if p.estado in ("Recibido", "En Corte", "En Costura", "Terminado")
                  and p.ultimo_evento and p.ultimo_evento.fecha < limite]
    if estancados:
        recs.append(_rec(
            "alerta", "pause-circle",
            f"{len(estancados)} pedido{'s' if len(estancados) != 1 else ''} sin avance en {DIAS_ESTANCADO}+ días",
            "No registran cambios de fase recientemente. Confirma si están detenidos o si falta actualizar el tablero.",
            ("Ver tablero", url_for("main.kanban_pedidos")),
            [f"{p.folio} · {p.estado} desde {p.ultimo_evento.fecha.strftime('%d/%m')}" for p in estancados[:4]],
            roles=("admin", "gestor")))

    # 7. Rentabilidad
    bajo_margen = [p for p in activos if p.margen_pct is not None and p.margen_pct < MARGEN_MINIMO_PEDIDO]
    if bajo_margen:
        recs.append(_rec(
            "critico" if any(p.margen_pct < 0 for p in bajo_margen) else "alerta", "trending-down",
            f"{len(bajo_margen)} pedido{'s' if len(bajo_margen) != 1 else ''} con margen menor al {MARGEN_MINIMO_PEDIDO}%",
            "El precio acordado apenas cubre materiales y mano de obra. Revisa precios antes de cotizar de nuevo a estos clientes.",
            ("Ver costos y márgenes", url_for("costos.index")),
            [f"{p.folio} · {p.cliente.nombre} · margen {p.margen_pct}%" for p in sorted(bajo_margen, key=lambda p: p.margen_pct)[:4]],
            roles=("admin", "ventas")))
    sin_costeo = [d for d in Diseno.query.filter(Diseno.archivado.is_(False)).all() if not d.costeable]
    if sin_costeo:
        recs.append(_rec(
            "sugerencia", "calculator",
            f"{len(sin_costeo)} diseño{'s' if len(sin_costeo) != 1 else ''} sin costo o precio completo",
            "Sin precio de venta, ficha técnica o costo de sus insumos no se puede calcular cuánto se gana.",
            ("Completar en costos", url_for("costos.index")),
            [d.nombre + (" · sin precio" if not d.tiene_precio else "") +
             (" · sin ficha técnica" if not d.telas else "") +
             (f" · {len(d.insumos_sin_costo)} insumo(s) sin costo" if d.insumos_sin_costo else "") for d in sin_costeo[:4]],
            roles=("admin", "ventas")))

    # 8. Concentración de clientes (dependencia de un solo cliente)
    prendas_activas = sum(p.cantidad for p in activos)
    if prendas_activas:
        por_cliente = defaultdict(int)
        for p in activos:
            por_cliente[p.cliente.nombre] += p.cantidad
        nombre, cantidad = max(por_cliente.items(), key=lambda x: x[1])
        pct = round(cantidad / prendas_activas * 100)
        if pct >= 50 and len(por_cliente) > 1:
            recs.append(_rec(
                "sugerencia", "pie-chart", f"{nombre} concentra el {pct}% de la producción activa",
                "Depender de un solo cliente es un riesgo: si retrasa pagos o cancela, el taller queda sin carga.",
                ("Ver reportes", url_for("reportes.index")), roles=("admin",)))

    # 9. Cotizaciones por vencer sin respuesta
    por_vencer = [c for c in Cotizacion.query.filter_by(estado="enviada").all()
                  if not c.vencida and c.dias_para_vencer <= 3]
    if por_vencer:
        recs.append(_rec(
            "sugerencia", "file-clock", f"{len(por_vencer)} cotización(es) por vencer sin respuesta",
            "Llama al cliente antes de que venzan; una cotización vencida obliga a recalcular precios.",
            ("Ver cotizaciones", url_for("cotizaciones.lista", estado="enviada")),
            [f"{c.folio} · {c.cliente.nombre} · ${c.total:,.0f} · vence en {c.dias_para_vencer} d" for c in por_vencer[:4]],
            roles=("admin", "ventas")))

    # 10. Proveedores atrasados
    atrasadas = [oc for oc in OrdenCompra.query.filter_by(estado="enviada").all() if oc.atrasada]
    if atrasadas:
        recs.append(_rec(
            "alerta", "truck", f"{len(atrasadas)} orden(es) de compra atrasada(s)",
            "El proveedor no ha entregado en la fecha acordada. Confirma la nueva fecha o busca otro proveedor.",
            ("Ver órdenes", url_for("compras.ordenes", estado="enviada")),
            [f"{oc.folio} · {oc.proveedor.nombre if oc.proveedor else '—'} · esperada {oc.fecha_esperada.strftime('%d/%m')}" for oc in atrasadas[:4]],
            roles=("admin", "gestor")))

    # 11. Puntualidad por debajo de la meta
    punt, entregas = puntualidad()
    if punt is not None and punt < META_PUNTUALIDAD[0] and entregas >= 3:
        recs.append(_rec(
            "alerta", "calendar-x", f"Puntualidad de entrega en {punt}% (meta {META_PUNTUALIDAD[0]}%)",
            "Revisa si las fechas comprometidas son realistas para la capacidad del taller.",
            ("Ver reportes", url_for("reportes.index")), roles=("admin",)))

    # 12. Solicitudes de acceso
    pendientes = Usuario.query.filter_by(estado_permiso="pendiente").count()
    if pendientes:
        recs.append(_rec(
            "sugerencia", "user-check", f"{pendientes} solicitud{'es' if pendientes != 1 else ''} de acceso pendiente{'s' if pendientes != 1 else ''}",
            "Aprueba o rechaza las cuentas de empleados que pidieron un rol interno.",
            ("Revisar solicitudes", url_for("admin.usuarios")), roles=("admin",)))

    visibles = [r for r in recs if usuario.rol in r["roles"]]
    visibles.sort(key=lambda r: NIVELES[r["nivel"]])
    return visibles


# ---------------------------------------------------------------------------
# Gráficos (Chart.js)
# ---------------------------------------------------------------------------
def _meses_atras(n):
    hoy = date.today()
    anio, mes = hoy.year, hoy.month
    salida = []
    for _ in range(n):
        salida.append((anio, mes))
        mes -= 1
        if mes == 0:
            anio, mes = anio - 1, 12
    return list(reversed(salida))


def graficos(usuario, meses=6):
    periodos = _meses_atras(meses)
    etiquetas = [f"{MESES[m - 1]} {str(a)[2:]}" for a, m in periodos]
    indice = {p: i for i, p in enumerate(periodos)}
    desde = datetime(periodos[0][0], periodos[0][1], 1)

    recibidos, entregados, prendas = [0] * meses, [0] * meses, [0] * meses
    ingresos, ganancias = [0.0] * meses, [0.0] * meses
    for p in Pedido.query.filter(Pedido.creado_en >= desde).all():
        i = indice.get((p.creado_en.year, p.creado_en.month))
        if i is None:
            continue
        recibidos[i] += 1
        prendas[i] += p.cantidad
        if p.ingreso:
            ingresos[i] += float(p.ingreso)
            ganancias[i] += float(p.ganancia_estimada or 0)
    for e in EventoRastreo.query.filter(EventoRastreo.estado == "Entregado", EventoRastreo.fecha >= desde).all():
        i = indice.get((e.fecha.year, e.fecha.month))
        if i is not None:
            entregados[i] += 1

    # Consumo de tela (salidas) por mes: las 4 telas más usadas + total
    consumo = defaultdict(lambda: [0.0] * meses)
    totales = defaultdict(float)
    movs = (Movimiento.query.join(Insumo).filter(Movimiento.tipo == "salida", Movimiento.fecha >= desde,
                                                  Insumo.categoria == "Tela").all())
    for m in movs:
        i = indice.get((m.fecha.year, m.fecha.month))
        if i is None:
            continue
        valor = float(m.cantidad or 0)
        consumo[m.insumo.nombre][i] += valor
        totales[m.insumo.nombre] += valor
    top = sorted(totales, key=totales.get, reverse=True)[:4]
    total_mes = [round(sum(consumo[n][i] for n in consumo), 2) for i in range(meses)]
    colores = {n: (Insumo.query.filter_by(nombre=n).first().color_hex or "#888888") for n in top}

    datos = {
        "etiquetas": etiquetas,
        "pedidos": {"recibidos": recibidos, "entregados": entregados, "prendas": prendas},
        "consumo": {"series": [{"nombre": n, "color": colores[n], "valores": [round(v, 2) for v in consumo[n]]}
                               for n in top],
                    "total": total_mes},
    }
    if usuario.puede_ver_costos:
        datos["finanzas"] = {"ingresos": [round(v, 2) for v in ingresos],
                             "ganancias": [round(v, 2) for v in ganancias]}
    return datos
