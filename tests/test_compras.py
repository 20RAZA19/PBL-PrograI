"""Órdenes de compra sugeridas según stock, pedidos activos y mercadería en camino."""
from decimal import Decimal

import pytest

from app.compras.servicios import (analizar_insumos, crear_orden, demanda_pendiente, faltantes_para_pedidos,
                                   recibir_orden, redondear_compra)
from app.extensions import db
from app.models import Insumo, Movimiento, OrdenCompra, Pedido, Proveedor, Usuario


def _fila(nombre):
    return next(f for f in analizar_insumos(solo_necesarios=False) if f["insumo"].nombre == nombre)


@pytest.mark.parametrize("cantidad, unidad, esperado", [
    (12.3, "Metros", 15), (125, "Metros", 125), (3.2, "Conos", 4), (123, "Unidades", 130),
    (42, "Unidades", 42), (0, "Metros", 0), (-8, "Metros", 0),
])
def test_redondeo_de_cantidades(cantidad, unidad, esperado):
    assert redondear_compra(cantidad, unidad) == Decimal(esperado)


def test_demanda_de_pedidos_activos(ctx, ids):
    demanda = demanda_pendiente()
    assert demanda[ids.popelina]["total"] == Decimal("150")  # 100 prendas × 1.5 m
    assert demanda[ids.boton]["total"] == Decimal("600")
    assert ids.gabardina not in demanda


def test_lo_ya_descontado_reduce_la_demanda(ctx, ids):
    db.session.add(Movimiento(tipo="salida", cantidad=30, insumo_id=ids.popelina, pedido_id=ids.activo))
    db.session.commit()
    assert demanda_pendiente()[ids.popelina]["total"] == Decimal("120")


def test_pedidos_terminados_no_generan_demanda(ctx, ids):
    db.session.get(Pedido, ids.activo).cambiar_estado("Terminado")
    db.session.commit()
    assert demanda_pendiente() == {}


def test_sugerencia_cubre_pedidos_y_deja_colchon(ctx, ids):
    fila = _fila("Popelina")
    # disponible 100 − demanda 150 = −50; objetivo 50 × 1.5 = 75 → 125 m
    assert fila["proyectado"] == Decimal("-50")
    assert fila["faltante"] == Decimal("50")
    assert fila["sugerido"] == Decimal("125")
    assert fila["costo"] == Decimal("312.50")


def test_insumo_critico_sin_pedidos(ctx, ids):
    fila = _fila("Gabardina")
    assert fila["sugerido"] == Decimal("130")  # 150 − 20


def test_insumo_sano_no_se_sugiere(ctx, ids):
    nombres = [f["insumo"].nombre for f in analizar_insumos()]
    assert "Hilo Blanco" not in nombres  # 30 conos, demanda 2, mínimo 10


def test_mercaderia_en_camino_reduce_la_sugerencia(ctx, ids):
    crear_orden(db.session.get(Proveedor, ids.proveedor), [(db.session.get(Insumo, ids.popelina), Decimal("80"))],
                db.session.get(Usuario, ids.usuarios["gestor"]))
    db.session.commit()
    fila = _fila("Popelina")
    # 100 + 80 en camino − 150 = 30 → faltan 45 para llegar a 75
    assert fila["en_camino"] == Decimal("80")
    assert fila["proyectado"] == Decimal("30")
    assert fila["sugerido"] == Decimal("45")
    assert all(f["insumo"].nombre != "Popelina" for f in faltantes_para_pedidos())


def test_si_lo_que_viene_alcanza_no_se_sugiere(ctx, ids):
    crear_orden(None, [(db.session.get(Insumo, ids.popelina), Decimal("150"))],
                db.session.get(Usuario, ids.usuarios["gestor"]))
    db.session.commit()
    assert all(f["insumo"].nombre != "Popelina" for f in analizar_insumos())


def test_recibir_orden_actualiza_stock_y_costo(ctx, ids):
    gestor = db.session.get(Usuario, ids.usuarios["gestor"])
    popelina = db.session.get(Insumo, ids.popelina)
    orden = crear_orden(None, [(popelina, Decimal("80"))], gestor)
    orden.lineas[0].costo_unitario = Decimal("2.75")
    db.session.flush()
    recibir_orden(orden, gestor)
    db.session.commit()
    assert popelina.cantidad_disponible == Decimal("180")
    assert popelina.costo_unitario == Decimal("2.75")
    assert orden.estado == "recibida" and orden.fecha_recepcion is not None
    mov = Movimiento.query.filter_by(tipo="entrada", insumo_id=popelina.id).one()
    assert orden.folio in mov.motivo


def test_folios_consecutivos(ctx, ids):
    gestor = db.session.get(Usuario, ids.usuarios["gestor"])
    a = crear_orden(None, [(db.session.get(Insumo, ids.hilo), 5)], gestor)
    db.session.flush()
    b = crear_orden(None, [(db.session.get(Insumo, ids.hilo), 5)], gestor)
    assert a.folio.startswith("OC-") and a.folio != b.folio
    assert int(b.folio[-4:]) == int(a.folio[-4:]) + 1


def test_generar_orden_desde_la_pantalla(app, ids, entrar):
    c = entrar("gestor")
    assert "Telas Prueba" in c.get("/compras/").get_data(as_text=True)
    r = c.post("/compras/generar", data={"proveedor_id": ids.proveedor, f"cantidad_{ids.popelina}": "125",
                                         f"cantidad_{ids.gabardina}": "0", "fecha_esperada": "2030-01-15"})
    assert r.status_code == 302
    with app.app_context():
        orden = OrdenCompra.query.one()
        assert orden.estado == "borrador" and len(orden.lineas) == 1
        assert orden.lineas[0].cantidad == Decimal("125")
        assert str(orden.fecha_esperada) == "2030-01-15"
        orden_id = orden.id

    c.post(f"/compras/ordenes/{orden_id}/enviar")
    c.post(f"/compras/ordenes/{orden_id}/recibir")
    with app.app_context():
        assert db.session.get(OrdenCompra, orden_id).estado == "recibida"
        assert db.session.get(Insumo, ids.popelina).cantidad_disponible == Decimal("225")


def test_orden_sin_cantidades_no_se_crea(app, ids, entrar):
    c = entrar("gestor")
    c.post("/compras/generar", data={"proveedor_id": ids.proveedor, f"cantidad_{ids.popelina}": "0"})
    with app.app_context():
        assert OrdenCompra.query.count() == 0


def test_no_se_recibe_dos_veces(app, ids, entrar):
    c = entrar("gestor")
    c.post("/compras/generar", data={f"cantidad_{ids.hilo}": "10"})
    with app.app_context():
        orden_id = OrdenCompra.query.one().id
    c.post(f"/compras/ordenes/{orden_id}/recibir")
    c.post(f"/compras/ordenes/{orden_id}/recibir")
    with app.app_context():
        assert db.session.get(Insumo, ids.hilo).cantidad_disponible == Decimal("40")


def test_pdf_de_orden_de_compra(app, ids, entrar):
    c = entrar("gestor")
    c.post("/compras/generar", data={f"cantidad_{ids.hilo}": "10"})
    with app.app_context():
        orden_id = OrdenCompra.query.one().id
    r = c.get(f"/compras/ordenes/{orden_id}/pdf")
    assert r.status_code == 200
    try:
        import reportlab  # noqa: F401
        assert r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
    except ImportError:
        assert b"ORDEN DE COMPRA" in r.data
