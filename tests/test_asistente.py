"""Asistente virtual local: reconoce las gestiones nuevas sin perder las anteriores."""
import pytest

from app.asistente.motor import clasificar

CASOS = {
    # Módulos nuevos
    "como hago una cotizacion": "cotizacion",
    "quiero cotizar 200 camisas": "cotizacion",
    "necesito un presupuesto para un cliente": "cotizacion",
    "como acepto una cotizacion": "responder_cotizacion",
    "cuanto gano por prenda": "costos",
    "cual es el margen de ganancia": "costos",
    "cuanto debo comprar": "compras",
    "como genero una orden de compra": "compras",
    "como recibo la mercaderia del proveedor": "compras",
    "como registro un defecto": "calidad",
    "hubo prendas defectuosas": "calidad",
    "que es la campana de notificaciones": "notificaciones",
    "quien hizo un cambio": "bitacora",
    "donde esta la bitacora": "bitacora",
    "como subo la foto de un diseño": "fotos",
    "como creo un diseño nuevo": "nuevo_diseno",
    "que debo revisar hoy": "centro_atencion",
    "que significan los indicadores": "centro_atencion",
    # Gestiones que ya existían (no deben romperse)
    "como registro una tela nueva": "registrar_insumo",
    "registrar entrada de material": "movimiento",
    "como creo un pedido": "crear_pedido",
    "donde esta mi pedido": "rastrear",
    "como muevo un pedido de fase": "mover_fase",
    "que insumos estan en alerta": "dato_alertas",
    "como registro un cliente": "registrar_cliente",
    "como cambio mi contraseña": "perfil",
    "como imprimo la ficha de la orden": "ficha",
    "que puedo hacer": "opciones",
    "como descuento tela de un pedido": "descontar_material",
    "como apruebo un usuario": "aprobar_usuarios",
    "como exporto a excel": "reportes",
    "por que no me deja guardar un color": "color_repetido",
}


@pytest.mark.parametrize("pregunta, esperado", CASOS.items())
def test_clasificacion(pregunta, esperado):
    intencion, _ = clasificar(pregunta)
    assert intencion is not None and intencion["id"] == esperado


@pytest.mark.parametrize("pregunta, esperado", [
    ("quiero una nueva cotisacion", "cotizacion"), ("registar defecto", "calidad"),
    ("conpras sugeridas", "compras"), ("bitakora de auditoria", "bitacora"),
])
def test_tolera_errores_de_tipeo(pregunta, esperado):
    intencion, _ = clasificar(pregunta)
    assert intencion is not None and intencion["id"] == esperado


@pytest.mark.parametrize("pregunta", ["cual es la capital de francia", "dame una receta de pupusas",
                                      "cuentame un chiste"])
def test_rechaza_temas_ajenos(pregunta):
    intencion, _ = clasificar(pregunta)
    assert intencion is None


def test_respuesta_segun_rol(entrar):
    r = entrar("cliente").post("/asistente/preguntar", json={"mensaje": "cuanto debo comprar"})
    datos = r.get_json()
    assert datos["intencion"] == "compras" and datos.get("restringido")

    r = entrar("gestor").post("/asistente/preguntar", json={"mensaje": "cuanto debo comprar"})
    datos = r.get_json()
    assert not datos.get("restringido") and datos["pasos"]
    assert any("/compras/" in e["url"] for e in datos["enlaces"])
