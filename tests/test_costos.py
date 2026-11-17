"""Costo por prenda, márgenes y totales de documentos (cálculos en los modelos)."""
from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import (Cotizacion, CotizacionLinea, Diseno, Insumo, OrdenCompra, OrdenCompraLinea,
                        Pedido, Movimiento)


def test_costo_por_prenda_suma_materiales_y_mano_de_obra(ctx, ids):
    camisa = db.session.get(Diseno, ids.camisa)
    assert camisa.costo_materiales == Decimal("4.13")
    assert camisa.costo_por_prenda == Decimal("6.13")
    assert camisa.margen_unitario == Decimal("3.87")
    assert camisa.margen_pct == 38.7
    assert camisa.costeable


def test_desglose_por_insumo(ctx, ids):
    filas = {f["insumo"].nombre: f["subtotal"] for f in db.session.get(Diseno, ids.camisa).desglose_costos}
    assert filas == {"Popelina": Decimal("3.75"), "Hilo Blanco": Decimal("0.08"), "Botón": Decimal("0.30")}


def test_metros_por_prenda_solo_cuenta_tela(ctx, ids):
    # Hilo (conos) y botones (unidades) no son metros de tela
    assert db.session.get(Diseno, ids.camisa).metros_por_prenda == 1.5


def test_diseno_sin_precio_no_es_costeable(ctx, ids):
    camisa = db.session.get(Diseno, ids.camisa)
    camisa.precio_venta = None
    assert camisa.margen_pct is None
    assert not camisa.costeable


def test_insumo_sin_costo_impide_costear(ctx, ids):
    db.session.get(Insumo, ids.hilo).costo_unitario = 0
    camisa = db.session.get(Diseno, ids.camisa)
    assert [i.nombre for i in camisa.insumos_sin_costo] == ["Hilo Blanco"]
    assert not camisa.costeable


def test_rentabilidad_del_pedido(ctx, ids):
    pedido = db.session.get(Pedido, ids.activo)
    assert pedido.precio_efectivo == Decimal("10.00")  # hereda el precio del diseño
    assert pedido.ingreso == Decimal("1000.00")
    assert pedido.costo_estimado == Decimal("613.00")
    assert pedido.ganancia_estimada == Decimal("387.00")
    assert pedido.margen_pct == 38.7


def test_precio_acordado_reemplaza_al_del_diseno(ctx, ids):
    pedido = db.session.get(Pedido, ids.activo)
    pedido.precio_unitario = Decimal("6.00")
    assert pedido.ganancia_estimada == Decimal("-13.00")
    assert pedido.margen_pct < 0


def test_pedido_sin_diseno_no_tiene_costo(ctx, ids):
    pedido = db.session.get(Pedido, ids.entregado)
    assert pedido.ingreso == Decimal("400.00")
    assert pedido.costo_estimado is None
    assert pedido.ganancia_estimada is None


def test_costo_real_de_materiales(ctx, ids):
    pedido = db.session.get(Pedido, ids.activo)
    db.session.add(Movimiento(tipo="salida", cantidad=40, insumo_id=ids.popelina, pedido=pedido))
    db.session.add(Movimiento(tipo="entrada", cantidad=999, insumo_id=ids.popelina, pedido=pedido))
    db.session.flush()
    assert pedido.costo_materiales_real == Decimal("100.00")  # solo salidas: 40 m × $2.50


def test_valor_del_inventario(ctx, ids):
    assert db.session.get(Insumo, ids.popelina).valor_inventario == Decimal("250.00")


def test_totales_de_cotizacion(ctx, ids):
    cot = Cotizacion(folio="COT-X", cliente_id=ids.colegio, descuento_pct=Decimal("10"), iva_pct=Decimal("13"))
    cot.lineas.append(CotizacionLinea(descripcion="Camisa", cantidad=100, precio_unitario=Decimal("10")))
    cot.lineas.append(CotizacionLinea(descripcion="Pantalón", cantidad=50, precio_unitario=Decimal("12")))
    assert cot.subtotal == Decimal("1600.00")
    assert cot.descuento == Decimal("160.00")
    assert cot.base_imponible == Decimal("1440.00")
    assert cot.iva == Decimal("187.20")
    assert cot.total == Decimal("1627.20")
    assert cot.total_prendas == 150


def test_margen_de_cotizacion_solo_con_disenos(ctx, ids):
    cot = Cotizacion(folio="COT-Y", cliente_id=ids.colegio, descuento_pct=0, iva_pct=13)
    cot.lineas.append(CotizacionLinea(descripcion="Camisa", cantidad=10, precio_unitario=Decimal("10"),
                                      diseno=db.session.get(Diseno, ids.camisa)))
    assert cot.costo_estimado == Decimal("61.30")
    assert cot.margen_pct == 38.7
    cot.lineas.append(CotizacionLinea(descripcion="A la medida", cantidad=5, precio_unitario=Decimal("9")))
    assert cot.costo_estimado is None


def test_vencimiento_de_cotizacion(ctx, ids):
    cot = Cotizacion(folio="COT-Z", cliente_id=ids.colegio, estado="enviada",
                     fecha=date.today() - timedelta(days=20), validez_dias=15)
    assert cot.vencida
    assert cot.estado_legible == "Vencida"
    cot.estado = "aceptada"
    assert not cot.vencida  # una cotización respondida ya no vence


def test_total_de_orden_de_compra(ctx, ids):
    oc = OrdenCompra(folio="OC-X", estado="enviada", fecha_esperada=date.today() - timedelta(days=1))
    oc.lineas.append(OrdenCompraLinea(insumo_id=ids.popelina, cantidad=Decimal("120"), costo_unitario=Decimal("2.5")))
    oc.lineas.append(OrdenCompraLinea(insumo_id=ids.hilo, cantidad=Decimal("3"), costo_unitario=Decimal("4")))
    assert oc.total == Decimal("312.00")
    assert oc.atrasada
    assert oc.pendiente
