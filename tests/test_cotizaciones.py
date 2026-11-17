"""Cotizaciones: creación, validación, envío, respuesta del cliente, PDF y conversión en pedidos."""
from datetime import date, timedelta
from decimal import Decimal

from app.extensions import db
from app.models import Cotizacion, Notificacion, Pedido, Usuario


def _datos(ids, **extra):
    datos = {
        "cliente_id": ids.colegio, "fecha_entrega": (date.today() + timedelta(days=30)).isoformat(),
        "validez_dias": "15", "descuento_pct": "10", "iva_pct": "13", "condiciones": "50 % de anticipo",
        "linea_diseno": [str(ids.camisa), ""], "linea_descripcion": ["Camisa Prueba", "Pantalón a la medida"],
        "linea_tallas": ["S, M", ""], "linea_cantidad": ["100", "50"], "linea_precio": ["10", "12"],
    }
    datos.update(extra)
    return datos


def _crear(c, ids, **extra):
    r = c.post("/cotizaciones/nueva", data=_datos(ids, **extra))
    return r


def test_ventas_crea_cotizacion_con_totales(app, ids, entrar):
    r = _crear(entrar("ventas"), ids)
    assert r.status_code == 302
    with app.app_context():
        cot = Cotizacion.query.one()
        assert cot.estado == "borrador"
        assert cot.folio.startswith(f"COT-{date.today().year}-")
        assert len(cot.lineas) == 2 and cot.lineas[0].diseno_id == ids.camisa
        assert cot.total == Decimal("1627.20")
        assert cot.usuario.email == "ventas@test.com"


def test_filas_vacias_se_ignoran(app, ids, entrar):
    _crear(entrar("ventas"), ids, linea_diseno=["", ""], linea_descripcion=["Gorra", ""],
           linea_tallas=["", ""], linea_cantidad=["10", ""], linea_precio=["3", ""])
    with app.app_context():
        assert len(Cotizacion.query.one().lineas) == 1


def test_validaciones_de_lineas(app, ids, entrar):
    c = entrar("ventas")
    for malo in [dict(linea_cantidad=["0", "50"]), dict(linea_precio=["-1", "12"]),
                 dict(linea_descripcion=["", "Pantalón"]), dict(linea_precio=["abc", "12"]),
                 dict(linea_diseno=[], linea_descripcion=[], linea_tallas=[], linea_cantidad=[], linea_precio=[])]:
        r = _crear(c, ids, **malo)
        assert r.status_code == 200, malo  # se vuelve a mostrar el formulario con el error
    r = _crear(c, ids, fecha_entrega=(date.today() - timedelta(days=1)).isoformat())
    assert "no puede estar en el pasado" in r.get_data(as_text=True)
    with app.app_context():
        assert Cotizacion.query.count() == 0


def test_taller_consulta_pero_no_cotiza(app, ids, entrar):
    c = entrar("gestor")
    assert c.get("/cotizaciones/").status_code == 200
    assert c.get("/cotizaciones/nueva").status_code == 403
    assert _crear(c, ids).status_code == 403


def test_flujo_completo_hasta_pedidos(app, ids, entrar):
    ventas = entrar("ventas")
    _crear(ventas, ids)
    with app.app_context():
        cot_id = Cotizacion.query.one().id

    cliente = entrar("cliente")
    assert cliente.get(f"/cotizaciones/{cot_id}").status_code == 404  # el borrador no se muestra al cliente

    ventas.post(f"/cotizaciones/{cot_id}/enviar")
    with app.app_context():
        assert db.session.get(Cotizacion, cot_id).estado == "enviada"
        avisos = Notificacion.query.filter_by(usuario_id=ids.usuarios["cliente"], tipo="cotizacion").all()
        assert len(avisos) == 1

    r = cliente.get(f"/cotizaciones/{cot_id}")
    assert r.status_code == 200 and "Aceptar" in r.get_data(as_text=True)
    assert "Costo estimado" not in r.get_data(as_text=True)  # el cliente no ve costos internos

    cliente.post(f"/cotizaciones/{cot_id}/aceptar")
    with app.app_context():
        cot = db.session.get(Cotizacion, cot_id)
        assert cot.estado == "aceptada" and cot.respondida_en is not None
        aviso_ventas = Notificacion.query.filter_by(usuario_id=ids.usuarios["ventas"], tipo="cotizacion").first()
        assert aviso_ventas and "aceptó" in aviso_ventas.titulo

    ventas.post(f"/cotizaciones/{cot_id}/convertir")
    ventas.post(f"/cotizaciones/{cot_id}/convertir")  # repetir no duplica pedidos
    with app.app_context():
        pedidos = Pedido.query.filter_by(cotizacion_id=cot_id).all()
        assert len(pedidos) == 2
        camisa = next(p for p in pedidos if p.diseno_id == ids.camisa)
        assert camisa.cantidad == 100 and camisa.precio_unitario == Decimal("10.00")
        assert camisa.estado == "Recibido" and len(camisa.eventos) == 1
        assert camisa.fecha_limite == date.today() + timedelta(days=30)


def test_cliente_de_otra_empresa_no_ve_la_cotizacion(app, ids, entrar):
    ventas = entrar("ventas")
    _crear(ventas, ids)
    with app.app_context():
        cot_id = Cotizacion.query.one().id
    ventas.post(f"/cotizaciones/{cot_id}/enviar")
    otro = entrar("cliente_b")
    assert otro.get(f"/cotizaciones/{cot_id}").status_code == 404
    assert otro.get(f"/cotizaciones/{cot_id}/pdf").status_code == 404
    assert otro.post(f"/cotizaciones/{cot_id}/aceptar").status_code == 404
    assert "COT-" not in otro.get("/cotizaciones/").get_data(as_text=True)


def test_cliente_no_puede_convertir_ni_enviar(app, ids, entrar):
    ventas = entrar("ventas")
    _crear(ventas, ids)
    with app.app_context():
        cot_id = Cotizacion.query.one().id
    ventas.post(f"/cotizaciones/{cot_id}/enviar")
    cliente = entrar("cliente")
    assert cliente.post(f"/cotizaciones/{cot_id}/convertir").status_code == 403
    assert cliente.post(f"/cotizaciones/{cot_id}/duplicar").status_code == 403


def test_cotizacion_vencida_no_se_puede_aceptar(app, ids, entrar):
    ventas = entrar("ventas")
    _crear(ventas, ids)
    with app.app_context():
        cot = Cotizacion.query.one()
        cot.estado = "enviada"
        cot.fecha = date.today() - timedelta(days=40)
        db.session.commit()
        cot_id = cot.id
    entrar("cliente").post(f"/cotizaciones/{cot_id}/aceptar")
    with app.app_context():
        assert db.session.get(Cotizacion, cot_id).estado == "enviada"


def test_solo_el_borrador_se_edita_y_se_puede_duplicar(app, ids, entrar):
    ventas = entrar("ventas")
    _crear(ventas, ids)
    with app.app_context():
        cot_id = Cotizacion.query.one().id
    ventas.post(f"/cotizaciones/{cot_id}/enviar")
    r = ventas.get(f"/cotizaciones/{cot_id}/editar")
    assert r.status_code == 302
    ventas.post(f"/cotizaciones/{cot_id}/duplicar")
    with app.app_context():
        copia = Cotizacion.query.filter(Cotizacion.id != cot_id).one()
        assert copia.estado == "borrador" and len(copia.lineas) == 2


def test_editar_borrador_reemplaza_lineas(app, ids, entrar):
    ventas = entrar("ventas")
    _crear(ventas, ids)
    with app.app_context():
        cot_id = Cotizacion.query.one().id
    ventas.post(f"/cotizaciones/{cot_id}/editar", data=_datos(
        ids, linea_diseno=[str(ids.camisa)], linea_descripcion=["Camisa Prueba"], linea_tallas=["M"],
        linea_cantidad=["300"], linea_precio=["9.50"], descuento_pct="0"))
    with app.app_context():
        cot = db.session.get(Cotizacion, cot_id)
        assert len(cot.lineas) == 1 and cot.subtotal == Decimal("2850.00")


def test_pdf_de_cotizacion(app, ids, entrar):
    ventas = entrar("ventas")
    _crear(ventas, ids)
    with app.app_context():
        cot = Cotizacion.query.one()
        cot_id, folio = cot.id, cot.folio
    r = ventas.get(f"/cotizaciones/{cot_id}/pdf?descargar=1")
    assert r.status_code == 200
    try:
        import reportlab  # noqa: F401
        assert r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
        assert f'attachment; filename="{folio}.pdf"' == r.headers["Content-Disposition"]
    except ImportError:
        assert b"COTIZACI" in r.data


def test_version_imprimible_sin_reportlab(app, ids, entrar):
    app.config["DOCUMENTOS_HTML"] = True
    ventas = entrar("ventas")
    _crear(ventas, ids)
    with app.app_context():
        cot_id = Cotizacion.query.one().id
    html = ventas.get(f"/cotizaciones/{cot_id}/pdf").get_data(as_text=True)
    assert "COTIZACIÓN" in html and "$1,627.20" in html and "Colegio Prueba" in html


def test_cotizar_desde_un_diseno_precarga_el_precio(app, ids, entrar):
    html = entrar("ventas").get(f"/cotizaciones/nueva?diseno_id={ids.camisa}&cantidad=250").get_data(as_text=True)
    assert '"cantidad": 250' in html and '"descripcion": "Camisa Prueba"' in html
