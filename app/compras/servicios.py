"""Cálculo de compras sugeridas a partir del inventario y de los pedidos activos.

Para cada insumo:

    demanda pendiente = Σ (prendas del pedido × consumo por prenda de la ficha técnica)
                        − lo que ya se descontó del inventario para ese pedido
                        (solo pedidos en Recibido, En Corte o En Costura)
    en camino         = cantidades de órdenes de compra aún no recibidas
    proyectado        = disponible + en camino − demanda pendiente

Si el insumo está en alerta o el proyectado queda bajo el stock mínimo, se
sugiere comprar lo necesario para cubrir los pedidos y dejar el stock en
FACTOR_OBJETIVO veces el mínimo (colchón de seguridad).
"""
import math
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

from app.extensions import db
from app.models import Insumo, Movimiento, OrdenCompra, OrdenCompraLinea, Pedido, Proveedor
from app.utils import generar_folio

FASES_CON_DEMANDA = ("Recibido", "En Corte", "En Costura")
FACTOR_OBJETIVO = Decimal("1.5")


def _d(valor):
    return Decimal(str(valor or 0))


def redondear_compra(cantidad, unidad):
    """Cantidades cómodas de pedir: metros de 5 en 5, unidades de 10 en 10, conos enteros."""
    cantidad = float(cantidad)
    if cantidad <= 0:
        return Decimal("0")
    if unidad in ("Metros", "Yardas"):
        paso = 5
    elif unidad == "Unidades" and cantidad > 50:
        paso = 10
    else:
        paso = 1
    return Decimal(math.ceil(cantidad / paso) * paso)


def demanda_pendiente():
    """{insumo_id: {"total": Decimal, "pedidos": [(pedido, Decimal)]}}"""
    demanda = defaultdict(lambda: {"total": Decimal("0"), "pedidos": []})
    pedidos = Pedido.query.filter(Pedido.estado.in_(FASES_CON_DEMANDA), Pedido.diseno_id.isnot(None)).all()
    for pedido in pedidos:
        consumido = defaultdict(Decimal)
        for m in pedido.movimientos:
            if m.tipo == "salida":
                consumido[m.insumo_id] += _d(m.cantidad)
        for dt in pedido.diseno.telas:
            requerido = _d(dt.metros_por_unidad) * pedido.cantidad - consumido[dt.tela_id]
            if requerido > 0:
                demanda[dt.tela_id]["total"] += requerido
                demanda[dt.tela_id]["pedidos"].append((pedido, requerido))
    return demanda


def en_camino():
    """{insumo_id: Decimal} con lo pedido a proveedores que aún no llega."""
    total = defaultdict(Decimal)
    lineas = (OrdenCompraLinea.query.join(OrdenCompra)
              .filter(OrdenCompra.estado.in_(("borrador", "enviada"))).all())
    for l in lineas:
        total[l.insumo_id] += _d(l.cantidad)
    return total


def analizar_insumos(solo_necesarios=True):
    """Lista de diccionarios con la situación de compra de cada insumo activo."""
    demanda = demanda_pendiente()
    camino = en_camino()
    resultado = []
    for insumo in Insumo.query.filter(Insumo.activo.is_(True)).order_by(Insumo.nombre).all():
        disponible = _d(insumo.cantidad_disponible)
        minimo = _d(insumo.stock_minimo)
        dem = demanda[insumo.id]["total"] if insumo.id in demanda else Decimal("0")
        llega = camino.get(insumo.id, Decimal("0"))
        proyectado = disponible + llega - dem
        en_alerta = insumo.alerta_stock != "ok"
        necesita = en_alerta or proyectado < minimo
        sugerido = Decimal("0")
        if necesita:
            sugerido = redondear_compra(minimo * FACTOR_OBJETIVO - proyectado, insumo.unidad_medida)
        if solo_necesarios and not necesita:
            continue
        resultado.append({
            "insumo": insumo,
            "disponible": disponible,
            "minimo": minimo,
            "demanda": dem,
            "pedidos": demanda[insumo.id]["pedidos"] if insumo.id in demanda else [],
            "en_camino": llega,
            "proyectado": proyectado,
            "faltante": max(Decimal("0"), dem - disponible - llega),
            "sugerido": sugerido,
            "costo": (sugerido * _d(insumo.costo_unitario)).quantize(Decimal("0.01")),
            "cubierto": necesita and sugerido == 0,
        })
    return resultado


def sugerencias_por_proveedor():
    """[(proveedor | None, [filas con sugerido > 0], total)] ordenado por urgencia."""
    grupos = defaultdict(list)
    for fila in analizar_insumos():
        if fila["sugerido"] > 0:
            grupos[fila["insumo"].proveedor_id].append(fila)
    salida = []
    for proveedor_id, filas in grupos.items():
        proveedor = db.session.get(Proveedor, proveedor_id) if proveedor_id else None
        filas.sort(key=lambda f: (f["insumo"].alerta_stock != "critico", -f["faltante"]))
        salida.append((proveedor, filas, sum((f["costo"] for f in filas), Decimal("0"))))
    salida.sort(key=lambda g: (g[0] is None, -sum(1 for f in g[1] if f["insumo"].alerta_stock == "critico")))
    return salida


def faltantes_para_pedidos():
    """Insumos que no alcanzan para producir los pedidos activos (ni con lo que viene en camino)."""
    return [f for f in analizar_insumos(solo_necesarios=False) if f["faltante"] > 0]


def crear_orden(proveedor, items, usuario, fecha_esperada=None, notas=None):
    """items: [(insumo, cantidad)] → OrdenCompra en borrador (sin commit)."""
    orden = OrdenCompra(folio=generar_folio(OrdenCompra, "OC"), proveedor=proveedor, usuario=usuario,
                        fecha_esperada=fecha_esperada, notas=notas, estado="borrador")
    for insumo, cantidad in items:
        if cantidad and cantidad > 0:
            orden.lineas.append(OrdenCompraLinea(insumo=insumo, cantidad=cantidad,
                                                 costo_unitario=insumo.costo_unitario or 0))
    db.session.add(orden)
    return orden


def recibir_orden(orden, usuario):
    """Suma al inventario lo recibido y actualiza el costo del insumo (sin commit)."""
    for linea in orden.lineas:
        insumo = linea.insumo
        insumo.cantidad_disponible = _d(insumo.cantidad_disponible) + _d(linea.cantidad)
        if _d(linea.costo_unitario) > 0:
            insumo.costo_unitario = linea.costo_unitario
        db.session.add(Movimiento(
            tipo="entrada", cantidad=linea.cantidad, metros=linea.cantidad, insumo=insumo,
            usuario=usuario, motivo=f"Recepción de {orden.folio}"
            + (f" · {orden.proveedor.nombre}" if orden.proveedor else ""),
        ))
    orden.estado = "recibida"
    orden.fecha_recepcion = datetime.now()
