"""Tablero de producción: filtros, pastillas de plazo y columnas."""
import re
from datetime import datetime, timedelta

from app.extensions import db
from app.models import EventoRastreo, Pedido, Usuario


def _tarjetas(html):
    return re.findall(r'class="kcard(?:\s[^"]*)?"', html)      # solo la tarjeta, no sus partes


def test_tablero_carga_con_seis_columnas_y_pastillas(entrar):
    html = entrar("admin").get("/pedidos/kanban").get_data(as_text=True)
    assert "Tablero de Producción" in html
    assert html.count('class="tp-columna"') == 6 or html.count('tp-columna" aria-label') == 6
    for pastilla in ("Vencido", "Por vencer (≤ 3 días)", "A tiempo"):
        assert pastilla in html


def test_filtro_por_plazo_reduce_las_tarjetas(entrar, app, ctx):
    c = entrar("admin")
    pedido = Pedido.query.filter_by(folio="ORD-T-001").one()
    pedido.fecha_limite = datetime.now().date() - timedelta(days=2)     # vencido
    db.session.commit()
    todas = _tarjetas(c.get("/pedidos/kanban").get_data(as_text=True))
    vencidas = _tarjetas(c.get("/pedidos/kanban?plazo=vencido").get_data(as_text=True))
    assert len(vencidas) >= 1 and len(vencidas) <= len(todas)
    assert all("kcard--vencido" in t for t in vencidas)


def test_plazo_desconocido_no_rompe(entrar):
    r = entrar("admin").get("/pedidos/kanban?plazo=raro&prioridad=x&cliente=abc&responsable=zz")
    assert r.status_code == 200


def test_entregados_viejos_no_aparecen_en_el_tablero(entrar, app, ctx):
    pedido = Pedido.query.filter_by(folio="ORD-T-002").one()
    pedido.estado = "Entregado"
    for ev in pedido.eventos:                       # todo su historial es de hace un mes
        ev.fecha = datetime.now() - timedelta(days=30)
    db.session.add(EventoRastreo(pedido=pedido, estado="Entregado", fase=6,
                                 fecha=datetime.now() - timedelta(days=30)))
    db.session.commit()
    html = entrar("admin").get("/pedidos/kanban").get_data(as_text=True)
    assert "ORD-T-002" not in html
    assert "Ver historial completo" in html


def test_responsable_se_toma_del_ultimo_movimiento(entrar, app, ctx):
    gestor = Usuario.query.filter_by(email="gestor@test.com").one()
    pedido = Pedido.query.filter_by(folio="ORD-T-001").one()
    db.session.add(EventoRastreo(pedido=pedido, estado=pedido.estado, fase=pedido.fase_actual,
                                 fecha=datetime.now(), usuario=gestor))
    db.session.commit()
    c = entrar("admin")
    html = c.get("/pedidos/kanban").get_data(as_text=True)
    assert gestor.nombre in html
    filtrado = c.get(f"/pedidos/kanban?responsable={gestor.id}").get_data(as_text=True)
    assert "ORD-T-001" in filtrado
