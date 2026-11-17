"""Control de calidad: registro de defectos, tasa por línea y permisos."""
from app.extensions import db
from app.indicadores import tasas_por_linea
from app.models import Notificacion, RegistroCalidad


def _registrar(c, ids, **extra):
    datos = {"pedido_id": ids.entregado, "linea": "Costura", "tipo": "defecto",
             "categoria": "Costura defectuosa", "cantidad": "6", "descripcion": "Hombro torcido"}
    datos.update(extra)
    return c.post("/calidad/nuevo", data=datos)


def test_taller_registra_un_defecto(app, ids, entrar):
    r = _registrar(entrar("gestor"), ids)
    assert r.status_code == 302
    with app.app_context():
        reg = RegistroCalidad.query.one()
        assert reg.cantidad == 6 and reg.linea == "Costura" and not reg.resuelto
        assert reg.usuario.email == "gestor@test.com"
        # El administrador recibe un aviso; quien lo registró no
        assert Notificacion.query.filter_by(usuario_id=ids.usuarios["admin"], tipo="calidad").count() == 1
        assert Notificacion.query.filter_by(usuario_id=ids.usuarios["gestor"], tipo="calidad").count() == 0


def test_no_se_registran_mas_prendas_que_las_del_pedido(app, ids, entrar):
    r = _registrar(entrar("gestor"), ids, cantidad="51")
    assert r.status_code == 200 and "solo tiene 50 prendas" in r.get_data(as_text=True)
    with app.app_context():
        assert RegistroCalidad.query.count() == 0


def test_cantidad_debe_ser_positiva(app, ids, entrar):
    assert _registrar(entrar("gestor"), ids, cantidad="0").status_code == 200
    with app.app_context():
        assert RegistroCalidad.query.count() == 0


def test_ventas_consulta_pero_no_registra(app, ids, entrar):
    c = entrar("ventas")
    assert c.get("/calidad/").status_code == 200
    assert c.get("/calidad/nuevo").status_code == 403
    assert _registrar(c, ids).status_code == 403
    assert entrar("cliente").get("/calidad/").status_code == 403


def test_resolver_un_caso(app, ids, entrar):
    c = entrar("gestor")
    _registrar(c, ids)
    with app.app_context():
        reg_id = RegistroCalidad.query.one().id
    c.post(f"/calidad/{reg_id}/resolver", data={"accion_correctiva": "Se recosieron las prendas"})
    with app.app_context():
        reg = db.session.get(RegistroCalidad, reg_id)
        assert reg.resuelto and reg.resuelto_en is not None
        assert reg.accion_correctiva == "Se recosieron las prendas"


def test_tasa_de_defectos_por_linea(app, ids, entrar):
    _registrar(entrar("gestor"), ids)  # 6 prendas en Costura sobre el pedido entregado
    with app.app_context():
        lineas = {l["linea"]: l for l in tasas_por_linea()}
        # Corte: ORD-T-001 (100, en corte) + ORD-T-002 (50, entregado) pasaron por la línea
        assert lineas["Corte"]["producidas"] == 150 and lineas["Corte"]["tasa"] == 0
        # Costura: solo ORD-T-002 llegó a esa fase → 6 / 50 = 12 %
        assert lineas["Costura"]["producidas"] == 50
        assert lineas["Costura"]["tasa"] == 12.0
        assert lineas["Costura"]["nivel"] == "danger"


def test_pagina_de_calidad_muestra_la_meta(app, ids, entrar):
    c = entrar("gestor")
    _registrar(c, ids)
    html = c.get("/calidad/").get_data(as_text=True)
    assert "Tasa de defectos por línea" in html and "12.0%" in html and "Costura defectuosa" in html
