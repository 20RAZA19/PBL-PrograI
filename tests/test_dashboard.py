"""Centro de atención, indicadores con semáforo y datos de los gráficos del dashboard."""
import json
import re

from app.extensions import db
from app.indicadores import graficos, kpis, recomendaciones
from app.models import Pedido, Usuario


def _titulos(app, ids, rol):
    with app.test_request_context():
        return [r["titulo"] for r in recomendaciones(db.session.get(Usuario, ids.usuarios[rol]))]


def test_recomendaciones_del_administrador(app, ids):
    titulos = _titulos(app, ids, "admin")
    assert any("Falta material" in t for t in titulos)
    assert any("riesgo de atraso" in t for t in titulos)
    assert any("nivel crítico" in t for t in titulos)
    assert any("solicitud" in t for t in titulos)


def test_recomendaciones_ordenadas_por_urgencia(app, ids):
    with app.test_request_context():
        recs = recomendaciones(db.session.get(Usuario, ids.usuarios["admin"]))
        orden = {"critico": 0, "alerta": 1, "sugerencia": 2}
        niveles = [orden[r["nivel"]] for r in recs]
        assert niveles == sorted(niveles)


def test_cada_rol_ve_solo_lo_suyo(app, ids):
    ventas = _titulos(app, ids, "ventas")
    assert not any("Falta material" in t for t in ventas)
    assert not any("solicitud" in t for t in ventas)
    gestor = _titulos(app, ids, "gestor")
    assert any("Falta material" in t for t in gestor)
    assert not any("margen" in t.lower() for t in gestor)


def test_margen_bajo_genera_alerta(app, ids):
    with app.app_context():
        db.session.get(Pedido, ids.activo).precio_unitario = 6  # pierde dinero
        db.session.commit()
    titulos = _titulos(app, ids, "ventas")
    assert any("margen menor al 15%" in t for t in titulos)


def test_pedido_vencido_es_critico(app, ids):
    from datetime import date, timedelta
    with app.app_context():
        db.session.get(Pedido, ids.activo).fecha_limite = date.today() - timedelta(days=3)
        db.session.commit()
    with app.test_request_context():
        recs = recomendaciones(db.session.get(Usuario, ids.usuarios["gestor"]))
        assert recs[0]["nivel"] == "critico" and "vencido" in recs[0]["titulo"]


def test_indicadores_con_semaforo(app, ids):
    with app.test_request_context():
        admin = kpis(db.session.get(Usuario, ids.usuarios["admin"]))
        gestor = kpis(db.session.get(Usuario, ids.usuarios["gestor"]))
    titulos = [k["titulo"] for k in admin]
    assert "Margen de ganancia" in titulos and "Cotizaciones ganadas" in titulos
    assert "Margen de ganancia" not in [k["titulo"] for k in gestor]
    for k in admin:
        assert k["nivel"] in ("ok", "warn", "danger", "neutral")
    entregas = next(k for k in admin if k["titulo"] == "Entregas a tiempo")
    # ORD-T-002 se entregó hace 2 días y vencía ayer: a tiempo
    assert entregas["valor"] == "100%" and entregas["nivel"] == "ok"


def test_entrega_tardia_baja_la_puntualidad(app, ids):
    from datetime import date, timedelta
    with app.app_context():
        db.session.get(Pedido, ids.entregado).fecha_limite = date.today() - timedelta(days=5)
        db.session.commit()
    with app.test_request_context():
        entregas = kpis(db.session.get(Usuario, ids.usuarios["gestor"]))[0]
    assert entregas["valor"] == "0%" and entregas["nivel"] == "danger"


def test_datos_de_graficos(app, ids):
    with app.test_request_context():
        datos = graficos(db.session.get(Usuario, ids.usuarios["admin"]))
        sin_finanzas = graficos(db.session.get(Usuario, ids.usuarios["gestor"]))
    assert len(datos["etiquetas"]) == 6
    assert datos["pedidos"]["recibidos"][-1] == 2  # los dos pedidos de prueba son de este mes
    assert datos["pedidos"]["prendas"][-1] == 150
    assert datos["pedidos"]["entregados"][-1] == 1
    assert datos["finanzas"]["ingresos"][-1] == 1400.0
    assert "finanzas" not in sin_finanzas


def test_dashboard_muestra_centro_de_atencion_y_graficos(app, ids, entrar):
    for rol in ("admin", "gestor", "ventas"):
        html = entrar(rol).get("/dashboard").get_data(as_text=True)
        assert "Centro de Atención" in html and 'id="grafico-pedidos"' in html
        datos = json.loads(re.search(r'id="datos-graficos">(.*?)</script>', html, re.S).group(1))
        assert len(datos["etiquetas"]) == 6
        assert ('id="grafico-finanzas"' in html) == (rol != "gestor")
    # Lo primero que ve el administrador: indicadores y centro de atención antes que el resto
    html = entrar("admin").get("/dashboard").get_data(as_text=True)
    assert html.index("Centro de Atención") < html.index("Materia Prima Registrada")


def test_portal_del_cliente_no_muestra_indicadores_internos(app, ids, entrar):
    html = entrar("cliente").get("/dashboard").get_data(as_text=True)
    assert "Centro de Atención" not in html and "Margen" not in html
