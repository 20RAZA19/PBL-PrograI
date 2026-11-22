"""Búsqueda global (Módulo de Búsqueda) y reportes globales del administrador."""
import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request, Response, abort
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.models import (
    Pedido, Cliente, Proveedor, Insumo, Diseno, Movimiento, Usuario, EventoRastreo,
    NOMBRES_FASES, ROLES,
)
from app.decorators import roles_required
from app.utils import fila_csv
from app.rastreo.servicios import pedidos_visibles

reportes = Blueprint("reportes", __name__)


# ---------------------------------------------------------------------------
# Búsqueda global
# ---------------------------------------------------------------------------
@reportes.route("/buscar")
@login_required
@roles_required("admin", "gestor", "ventas", "cliente")
def buscar():
    q = request.args.get("q", "").strip()
    resultados = {"pedidos": [], "insumos": [], "clientes": [], "proveedores": [], "disenos": []}

    if len(q) >= 2:
        termino = f"%{q}%"
        resultados["pedidos"] = (
            pedidos_visibles().join(Cliente)
            .filter(or_(Pedido.folio.ilike(termino), Pedido.modelo_prenda.ilike(termino),
                        Cliente.nombre.ilike(termino), Pedido.colores.ilike(termino)))
            .order_by(Pedido.creado_en.desc()).limit(25).all()
        )
        disenos = Diseno.query.filter(or_(Diseno.nombre.ilike(termino), Diseno.tipo_prenda.ilike(termino)))
        if current_user.rol == "cliente":
            disenos = disenos.filter(Diseno.cliente_id == current_user.cliente_id) if current_user.cliente_id else disenos.filter(db.false())
        resultados["disenos"] = disenos.limit(10).all()

        if current_user.es_staff:
            resultados["insumos"] = Insumo.query.filter(or_(
                Insumo.nombre.ilike(termino), Insumo.codigo.ilike(termino),
                Insumo.codigo_pantone.ilike(termino), Insumo.categoria.ilike(termino),
            )).limit(15).all()
            resultados["clientes"] = Cliente.query.filter(or_(
                Cliente.nombre.ilike(termino), Cliente.contacto.ilike(termino), Cliente.email.ilike(termino),
            )).limit(10).all()
            resultados["proveedores"] = Proveedor.query.filter(or_(
                Proveedor.nombre.ilike(termino), Proveedor.rubro.ilike(termino), Proveedor.contacto.ilike(termino),
            )).limit(10).all()

    total = sum(len(v) for v in resultados.values())
    return render_template("reportes/buscar.html", q=q, r=resultados, total=total)


# ---------------------------------------------------------------------------
# Reportes globales (Administrador)
# ---------------------------------------------------------------------------
@reportes.route("/")
@login_required
@roles_required("admin")
def index():
    from app.indicadores import graficos
    dias = request.args.get("dias", 30, type=int)
    dias = dias if dias in (7, 30, 90, 365) else 30
    hoy = date.today()
    desde = datetime.combine(hoy - timedelta(days=dias - 1), datetime.min.time())
    antes = desde - timedelta(days=dias)          # periodo anterior, para comparar

    # Todo lo que se muestra depende del periodo elegido (salvo «vencidos», que es la foto de hoy).
    pedidos = Pedido.query.filter(Pedido.creado_en >= desde).all()
    previos = Pedido.query.filter(Pedido.creado_en >= antes, Pedido.creado_en < desde).all()

    # Entregas hechas en el periodo (primer «Entregado» de cada pedido) y su puntualidad
    entregas = {}
    for e in (EventoRastreo.query.filter(EventoRastreo.estado == "Entregado", EventoRastreo.fecha >= desde)
              .order_by(EventoRastreo.fecha)):
        entregas.setdefault(e.pedido_id, e)
    a_tiempo = sum(1 for e in entregas.values()
                   if e.pedido.fecha_limite is None or e.fecha.date() <= e.pedido.fecha_limite)

    vencidos = [p for p in Pedido.query.filter(Pedido.fecha_limite < hoy).order_by(Pedido.fecha_limite)
                if p.alerta_entrega == "vencido"]

    por_estado = Counter(p.estado for p in pedidos)
    max_estado = max(por_estado.values() or [1])

    # Clientes con más unidades pedidas en el periodo
    unidades_cliente = defaultdict(int)
    for p in pedidos:
        unidades_cliente[p.cliente.nombre] += p.cantidad
    top_clientes = sorted(unidades_cliente.items(), key=lambda x: x[1], reverse=True)[:5]
    max_cliente = top_clientes[0][1] if top_clientes else 1

    # Consumo por insumo en el periodo
    salidas = Movimiento.query.filter(Movimiento.fecha >= desde, Movimiento.tipo == "salida").all()
    entradas = Movimiento.query.filter(Movimiento.fecha >= desde, Movimiento.tipo == "entrada").all()
    consumo = defaultdict(float)
    for m in salidas:
        consumo[m.insumo] += float(m.metros or m.cantidad or 0)
    top_consumo = sorted(consumo.items(), key=lambda x: x[1], reverse=True)[:6]
    max_consumo = top_consumo[0][1] if top_consumo else 1

    # Actividad por usuario (movimientos + eventos de rastreo en el periodo)
    actividad = Counter()
    for m in salidas + entradas:
        if m.usuario:
            actividad[m.usuario.nombre] += 1
    for e in EventoRastreo.query.filter(EventoRastreo.fecha >= desde).all():
        if e.usuario:
            actividad[e.usuario.nombre] += 1

    def variacion(actual, anterior):
        if not anterior:
            return None
        return round((actual - anterior) / anterior * 100)

    unidades = sum(p.cantidad for p in pedidos)
    resumen = {
        "pedidos": len(pedidos),
        "pedidos_var": variacion(len(pedidos), len(previos)),
        "activos": sum(1 for p in pedidos if not p.entregado),
        "entregados": len(entregas),
        "puntualidad": round(a_tiempo / len(entregas) * 100) if entregas else None,
        "vencidos": len(vencidos),
        "unidades": unidades,
        "unidades_var": variacion(unidades, sum(p.cantidad for p in previos)),
        "insumos_alerta": sum(1 for i in Insumo.query.filter(Insumo.activo.is_(True)) if i.alerta_stock != "ok"),
        "movimientos": len(salidas) + len(entradas),
        "clientes": Cliente.query.count(),
        "proveedores": Proveedor.query.count(),
        "usuarios": Usuario.query.count(),
    }
    datos = graficos(current_user, dias=dias)
    datos["estados"] = {"etiquetas": list(NOMBRES_FASES), "valores": [por_estado.get(f, 0) for f in NOMBRES_FASES]}
    datos["puntualidad"] = {"a_tiempo": a_tiempo, "tarde": len(entregas) - a_tiempo}
    return render_template(
        "reportes/index.html", resumen=resumen, dias=dias, desde=desde, por_estado=por_estado,
        max_estado=max_estado, top_clientes=top_clientes, max_cliente=max_cliente,
        top_consumo=top_consumo, max_consumo=max_consumo, actividad=actividad.most_common(6),
        vencidos=vencidos[:6], total_vencidos=len(vencidos), NOMBRES_FASES=NOMBRES_FASES, graficos=datos,
        tramo={7: "por día", 30: "por día", 90: "por semana", 365: "por mes"}[dias],
    )


def _csv(nombre, encabezados, filas):
    salida = io.StringIO()
    salida.write("﻿")  # BOM: Excel abre los acentos correctamente
    escritor = csv.writer(salida)
    escritor.writerow(encabezados)
    escritor.writerows(fila_csv(f) for f in filas)
    fecha = date.today().strftime("%Y%m%d")
    return Response(
        salida.getvalue(), mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="ayc_{nombre}_{fecha}.csv"'},
    )


@reportes.route("/exportar/<tipo>.csv")
@login_required
@roles_required("admin")
def exportar(tipo):
    if tipo == "pedidos":
        filas = [(p.folio, p.cliente.nombre, p.modelo_prenda, p.cantidad, p.tallas or "", p.colores or "",
                  p.estado, p.progreso, p.ubicacion_actual or "", p.fecha_limite.isoformat(),
                  p.creado_en.strftime("%Y-%m-%d %H:%M") if p.creado_en else "", p.observaciones or "")
                 for p in Pedido.query.order_by(Pedido.creado_en).all()]
        return _csv("pedidos", ["Folio", "Cliente", "Prenda", "Cantidad", "Tallas", "Colores", "Estado",
                                "Avance %", "Ubicación", "Fecha límite", "Registrado", "Observaciones"], filas)
    if tipo == "inventario":
        filas = [(i.codigo or "", i.nombre, i.categoria, i.unidad_medida, float(i.cantidad_disponible or 0),
                  float(i.stock_minimo or 0), i.estado, i.codigo_pantone or "", i.color_hex or "",
                  "Sí" if i.activo else "No")
                 for i in Insumo.query.order_by(Insumo.categoria, Insumo.nombre).all()]
        return _csv("inventario", ["Código", "Insumo", "Categoría", "Unidad", "Disponible", "Stock mínimo",
                                   "Estado", "Pantone", "Color", "Activo"], filas)
    if tipo == "movimientos":
        filas = [(m.fecha.strftime("%Y-%m-%d %H:%M") if m.fecha else "", m.tipo, m.insumo.nombre,
                  float(m.metros or m.cantidad or 0), m.insumo.unidad_medida, m.motivo or "",
                  m.pedido.folio if m.pedido else "", m.usuario.nombre if m.usuario else "Sistema")
                 for m in Movimiento.query.order_by(Movimiento.fecha).all()]
        return _csv("movimientos", ["Fecha", "Tipo", "Insumo", "Cantidad", "Unidad", "Motivo", "Pedido",
                                    "Registrado por"], filas)
    if tipo == "contactos":
        filas = [("Cliente", c.nombre, c.contacto or "", c.telefono or "", c.email or "", "", len(c.pedidos))
                 for c in Cliente.query.order_by(Cliente.nombre).all()]
        filas += [("Proveedor", p.nombre, p.contacto or "", p.telefono or "", p.email or "", p.rubro or "", "")
                  for p in Proveedor.query.order_by(Proveedor.nombre).all()]
        return _csv("contactos", ["Tipo", "Nombre", "Contacto", "Teléfono", "Correo", "Rubro", "Pedidos"], filas)
    abort(404)
