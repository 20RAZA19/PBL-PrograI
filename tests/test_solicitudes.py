"""Solicitudes: el cliente propone, la empresa aprueba con precios por cantidad
(o deniega con motivo) y el pedido se crea solo cuando el cliente acepta la
cotización vigente."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Diseno, Notificacion, Pedido, Solicitud, Usuario
from tests.conftest import CLAVE

EN_15 = (date.today() + timedelta(days=15)).isoformat()


def _datos(**extra):
    datos = {"linea_diseno": [""], "linea_descripcion": ["Camisa Oxford manga larga"], "linea_cantidad": ["120"],
             "linea_tallas": ["40 S, 80 M"], "linea_colores": ["Blanco"], "linea_medidas": ["Manga 62 cm"],
             "fecha_deseada": EN_15, "notas": "Bordado en el pecho"}
    datos.update(extra)
    return datos


def _crear(entrar, **extra):
    c = entrar("cliente")
    r = c.post("/solicitudes/nueva", data=_datos(**extra))
    return c, r


def _solicitud():
    """Última solicitud, releída de la base (sin caché de la sesión anterior)."""
    db.session.expire_all()
    return Solicitud.query.order_by(Solicitud.id.desc()).first()


def _aprobar(c, sol, fecha=EN_15, tramos=None, **extra):
    """Aprueba con rebajas por cantidad: 1 → $15, 100 → $12.50, 500 → $10."""
    datos = {"apro-fecha_entrega": fecha, "apro-respuesta": "Incluye bordado"}
    for l in sol.lineas:
        desde, precios = tramos or (["1", "100", "500"], ["15.00", "12.50", "10.00"])
        datos[f"tramo_desde_{l.id}"] = desde
        datos[f"tramo_precio_{l.id}"] = precios
    datos.update(extra)
    return c.post(f"/solicitudes/{sol.id}/aprobar", data=datos)


# ---------------------------------------------------------------------------
# Propuesta del cliente
# ---------------------------------------------------------------------------
def test_cliente_crea_solicitud(entrar, ctx):
    c, r = _crear(entrar)
    assert r.status_code == 302
    sol = _solicitud()
    assert sol.folio == f"SOL-{date.today().year}-0001"
    assert sol.estado == "enviada" and sol.origen == "portal"
    assert sol.total_prendas == 120 and sol.total is None
    linea = sol.lineas[0]
    assert (linea.descripcion, linea.tallas, linea.colores, linea.medidas) == (
        "Camisa Oxford manga larga", "40 S, 80 M", "Blanco", "Manga 62 cm")
    # Ventas y administración reciben el aviso
    ventas = Usuario.query.filter_by(email="ventas@test.com").one()
    assert Notificacion.query.filter_by(usuario_id=ventas.id, tipo="solicitud").count() == 1
    assert sol.folio in c.get("/dashboard").get_data(as_text=True)


@pytest.mark.parametrize("cambio, mensaje", [
    ({"linea_cantidad": ["0"]}, "cantidad"),
    ({"linea_cantidad": ["abc"]}, "cantidad"),
    ({"linea_descripcion": [""], "linea_cantidad": ["5"]}, "qué prenda"),
    ({"linea_descripcion": [""], "linea_cantidad": [""], "linea_medidas": [""]}, "al menos una prenda"),
    ({"fecha_deseada": (date.today() - timedelta(days=1)).isoformat()}, "pasado"),
])
def test_solicitud_invalida_no_se_guarda(entrar, ctx, cambio, mensaje):
    c, r = _crear(entrar, **cambio)
    assert r.status_code == 200
    assert mensaje in r.get_data(as_text=True)
    assert Solicitud.query.count() == 0


def test_no_se_puede_pedir_el_diseno_de_otra_empresa(entrar, ctx, ids):
    ajeno = Diseno(nombre="Diseño ajeno", cliente_id=ids.ajena)
    db.session.add(ajeno)
    db.session.commit()
    _crear(entrar, linea_diseno=[str(ajeno.id)])
    assert _solicitud().lineas[0].diseno_id is None


def test_cliente_sin_empresa_o_pendiente_no_solicita(app, ctx):
    u = Usuario(nombre="Sin Empresa", email="suelto@test.com", rol="cliente", estado_permiso="aprobado")
    u.set_password(CLAVE)
    db.session.add(u)
    db.session.commit()
    c = app.test_client()
    c.post("/auth/login", data={"email": "suelto@test.com", "password": CLAVE})
    r = c.post("/solicitudes/nueva", data=_datos())
    assert r.status_code == 302 and Solicitud.query.count() == 0


@pytest.mark.parametrize("rol", ["admin", "gestor", "ventas"])
def test_el_equipo_no_crea_solicitudes(entrar, rol):
    assert entrar(rol).get("/solicitudes/nueva").status_code == 403


def test_limite_de_solicitudes_abiertas(entrar, ctx):
    c = entrar("cliente")
    for _ in range(10):
        assert c.post("/solicitudes/nueva", data=_datos()).status_code == 302
    c.post("/solicitudes/nueva", data=_datos())
    assert Solicitud.query.count() == 10


def test_cliente_no_ve_solicitudes_de_otra_empresa(entrar, ctx, ids):
    _crear(entrar)
    sol = _solicitud()
    sol.cliente_id = ids.ajena
    db.session.commit()
    c = entrar("cliente")
    assert c.get(f"/solicitudes/{sol.id}").status_code == 404
    assert sol.folio not in c.get("/solicitudes/").get_data(as_text=True)
    assert c.post(f"/solicitudes/{sol.id}/cancelar").status_code == 404
    assert c.post(f"/solicitudes/{sol.id}/aceptar").status_code == 404


# ---------------------------------------------------------------------------
# Aprobación de la empresa: tramos de precio por cantidad
# ---------------------------------------------------------------------------
def test_aprobar_aplica_el_tramo_de_la_cantidad_pedida(entrar, ctx):
    _crear(entrar)
    sol = _solicitud()
    antes = Pedido.query.count()
    assert _aprobar(entrar("ventas"), sol).status_code == 302
    db.session.refresh(sol)
    assert sol.estado == "aprobada" and sol.atendida_por.email == "ventas@test.com"
    # 120 unidades caen en el tramo «desde 100» → $12.50
    linea = sol.lineas[0]
    assert linea.precio_unitario == Decimal("12.50")
    assert [(t.desde_cantidad, t.precio_unitario) for t in linea.tramos] == [
        (1, Decimal("15.00")), (100, Decimal("12.50")), (500, Decimal("10.00"))]
    assert sol.total == Decimal("1500.00")
    assert sol.vence_en == date.today() + timedelta(days=15) and sol.vigente
    assert sol.fecha_entrega.isoformat() == EN_15
    # Aprobar NO crea pedidos: eso solo pasa cuando el cliente acepta
    assert Pedido.query.count() == antes
    cliente = Usuario.query.filter_by(email="cliente@test.com").one()
    assert Notificacion.query.filter_by(usuario_id=cliente.id, clave=f"sol-aprobada-{sol.id}").count() == 1


def test_aprobar_guarda_condiciones_y_etiquetas(entrar, ctx):
    _crear(entrar)
    sol = _solicitud()
    _aprobar(entrar("admin"), sol, **{"apro-condiciones": "Pedido mínimo de 50 unidades",
                                      "etiqueta": ["Mínimo de pedido", "Color no disponible", "Inventada"]})
    db.session.refresh(sol)
    assert sol.condiciones == "Pedido mínimo de 50 unidades"
    assert sol.lista_etiquetas == ["Mínimo de pedido", "Color no disponible"]  # la inventada se descarta
    html = entrar("cliente").get(f"/solicitudes/{sol.id}").get_data(as_text=True)
    assert "Condiciones de la aprobación" in html and "Mínimo de pedido" in html


@pytest.mark.parametrize("desde, precios, fecha, pista", [
    (["1"], [""], EN_15, "precio"),                       # sin precio base
    (["5"], ["10.00"], EN_15, "precio base"),             # el primer tramo debe cubrir desde 1
    (["1", "100"], ["10.00", "12.00"], EN_15, "mayor"),   # la «rebaja» sube el precio
    (["1", "1"], ["10.00", "9.00"], EN_15, "mismo"),      # «desde» repetido
    (["1", "abc"], ["10.00", "9.00"], EN_15, "entero"),   # «desde» no numérico
    (["1"], ["10.00"], "", "fecha"),                      # sin fecha de entrega
    (["1"], ["10.00"], (date.today() - timedelta(days=1)).isoformat(), "pasado"),
])
def test_aprobar_valida_tramos_y_fecha(entrar, ctx, desde, precios, fecha, pista):
    _crear(entrar)
    sol = _solicitud()
    r = _aprobar(entrar("ventas"), sol, fecha=fecha, tramos=(desde, precios))
    assert r.status_code == 400
    assert pista.lower() in r.get_data(as_text=True).lower()
    db.session.refresh(sol)
    assert sol.estado == "enviada" and sol.lineas[0].precio_unitario is None and not sol.lineas[0].tramos


@pytest.mark.parametrize("rol", ["gestor", "cliente"])
def test_solo_ventas_y_admin_aprueban(entrar, ctx, rol):
    _crear(entrar)
    sol = _solicitud()
    c = entrar(rol)
    assert _aprobar(c, sol).status_code == 403
    assert c.post(f"/solicitudes/{sol.id}/denegar", data={"den-respuesta": "no"}).status_code == 403
    assert c.post(f"/solicitudes/{sol.id}/renovar").status_code == 403


def test_denegar_requiere_motivo_y_cierra_la_propuesta(entrar, ctx):
    _crear(entrar)
    sol = _solicitud()
    ventas = entrar("ventas")
    ventas.post(f"/solicitudes/{sol.id}/denegar", data={"den-respuesta": ""})
    assert _solicitud().estado == "enviada"
    ventas.post(f"/solicitudes/{sol.id}/denegar", data={"den-respuesta": "No manejamos esa tela"})
    assert _solicitud().estado == "denegada"
    assert "No manejamos esa tela" in entrar("cliente").get(f"/solicitudes/{sol.id}").get_data(as_text=True)


# ---------------------------------------------------------------------------
# Decisión del cliente: el pedido nace si y solo si él acepta una cotización vigente
# ---------------------------------------------------------------------------
def test_cliente_acepta_y_entonces_se_crean_los_pedidos(entrar, ctx):
    c, _ = _crear(entrar)
    sol = _solicitud()
    _aprobar(entrar("ventas"), sol)
    antes = Pedido.query.count()
    assert c.post(f"/solicitudes/{sol.id}/aceptar").status_code == 302
    db.session.refresh(sol)
    assert sol.estado == "convertida" and sol.decidida_en is not None
    assert Pedido.query.count() == antes + 1
    pedido = sol.pedidos[0]
    assert (pedido.cantidad, pedido.precio_unitario, pedido.estado) == (120, Decimal("12.50"), "Recibido")
    assert pedido.fecha_limite.isoformat() == EN_15 and "Manga 62 cm" in pedido.observaciones
    assert pedido.eventos, "el pedido nace con su primer evento de rastreo"
    # El equipo recibe el aviso y el cliente puede rastrear
    gestor = Usuario.query.filter_by(email="gestor@test.com").one()
    assert Notificacion.query.filter_by(usuario_id=gestor.id, clave=f"sol-aceptada-{sol.id}").count() == 1
    assert entrar("cliente").get(f"/rastreo/{pedido.folio}").status_code == 200
    # Aceptar dos veces no duplica pedidos
    c.post(f"/solicitudes/{sol.id}/aceptar")
    assert Pedido.query.count() == antes + 1


@pytest.mark.parametrize("estado", ["enviada", "denegada"])
def test_pendiente_o_denegada_jamas_entra_a_produccion(entrar, ctx, estado):
    c, _ = _crear(entrar)
    sol = _solicitud()
    if estado == "denegada":
        entrar("ventas").post(f"/solicitudes/{sol.id}/denegar", data={"den-respuesta": "No por ahora"})
    antes = Pedido.query.count()
    c.post(f"/solicitudes/{sol.id}/aceptar")
    db.session.expire_all()
    assert Pedido.query.count() == antes and _solicitud().estado == estado


def test_el_equipo_no_acepta_por_el_cliente(entrar, ctx):
    _crear(entrar)
    sol = _solicitud()
    _aprobar(entrar("ventas"), sol)
    for rol in ("admin", "ventas", "gestor"):
        assert entrar(rol).post(f"/solicitudes/{sol.id}/aceptar").status_code == 403
    assert _solicitud().estado == "aprobada" and Pedido.query.filter_by(solicitud_id=sol.id).count() == 0


def test_cotizacion_vencida_no_se_acepta_hasta_renovarla(entrar, ctx):
    c, _ = _crear(entrar)
    sol = _solicitud()
    _aprobar(entrar("ventas"), sol)
    sol = _solicitud()
    sol.vence_en = date.today() - timedelta(days=1)
    db.session.commit()
    antes = Pedido.query.count()
    c.post(f"/solicitudes/{sol.id}/aceptar")
    db.session.expire_all()
    assert Pedido.query.count() == antes and _solicitud().estado == "aprobada"
    assert "vencida" in c.get(f"/solicitudes/{sol.id}").get_data(as_text=True).lower()
    # Ventas renueva la vigencia y entonces sí se puede aceptar
    entrar("ventas").post(f"/solicitudes/{sol.id}/renovar")
    assert _solicitud().vence_en == date.today() + timedelta(days=15)
    assert c.post(f"/solicitudes/{sol.id}/aceptar").status_code == 302
    assert _solicitud().estado == "convertida"


def test_cliente_declina_con_motivo(entrar, ctx):
    c, _ = _crear(entrar)
    sol = _solicitud()
    # No se puede declinar lo que aún no tiene cotización
    c.post(f"/solicitudes/{sol.id}/declinar", data={"dec-motivo": "x"})
    assert _solicitud().estado == "enviada"
    _aprobar(entrar("ventas"), sol)
    c.post(f"/solicitudes/{sol.id}/declinar", data={"dec-motivo": "Queda fuera de presupuesto"})
    sol = _solicitud()
    assert sol.estado == "declinada" and sol.motivo_cliente == "Queda fuera de presupuesto"
    ventas = Usuario.query.filter_by(email="ventas@test.com").one()
    assert Notificacion.query.filter_by(usuario_id=ventas.id, clave=f"sol-declinada-{sol.id}").count() == 1


def test_cliente_solo_retira_antes_de_la_revision(entrar, ctx):
    c, _ = _crear(entrar)
    sol = _solicitud()
    assert c.post(f"/solicitudes/{sol.id}/cancelar").status_code == 302
    assert _solicitud().estado == "cancelada"
    # Con la cotización publicada ya no se cancela (se declina)
    _crear(entrar)
    sol2 = _solicitud()
    _aprobar(entrar("ventas"), sol2)
    c.post(f"/solicitudes/{sol2.id}/cancelar")
    assert _solicitud().estado == "aprobada"


# ---------------------------------------------------------------------------
# Lo que se ve en las pantallas
# ---------------------------------------------------------------------------
def test_dashboard_muestra_aprobaciones_y_ya_no_hay_nuevo_pedido(entrar, ctx):
    _crear(entrar)
    html = entrar("admin").get("/dashboard").get_data(as_text=True)
    assert "Aprobaciones pendientes" in html and _solicitud().folio in html
    assert "Diseños Previos" not in html and "Nuevo Pedido" not in html
    assert 'class="nav-badge">1<' in html


def test_cotizaciones_del_cliente_incluyen_solicitudes_aprobadas(entrar, ctx):
    _crear(entrar)
    sol = _solicitud()
    _aprobar(entrar("ventas"), sol)
    html = entrar("cliente").get("/cotizaciones/").get_data(as_text=True)
    assert "Cotizaciones de tus solicitudes" in html and sol.folio in html
