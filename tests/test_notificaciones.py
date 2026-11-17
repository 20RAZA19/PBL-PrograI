"""Notificaciones internas: avisos automáticos, de evento, lectura y privacidad."""
from datetime import date, timedelta

from app.extensions import db
from app.models import Insumo, Notificacion, Pedido, Usuario
from app.notificaciones.servicios import sincronizar
from app.rastreo.servicios import registrar_evento


def _claves(usuario_id):
    return {n.clave for n in Notificacion.query.filter_by(usuario_id=usuario_id)}


def test_avisos_automaticos_por_rol(app, ids):
    with app.test_request_context():
        for rol in ("admin", "gestor", "ventas", "cliente"):
            sincronizar(db.session.get(Usuario, ids.usuarios[rol]))
        vence = f"vence-{ids.activo}-{(date.today() + timedelta(days=2)).isoformat()}"
        critico = f"stock-critico-{ids.gabardina}"

        assert {vence, critico} <= _claves(ids.usuarios["gestor"])
        assert vence in _claves(ids.usuarios["ventas"]) and critico not in _claves(ids.usuarios["ventas"])
        assert any(c.startswith("usuarios-pendientes") for c in _claves(ids.usuarios["admin"]))
        assert _claves(ids.usuarios["cliente"]) == set()


def test_aviso_desaparece_cuando_se_resuelve(app, ids):
    with app.test_request_context():
        gestor = db.session.get(Usuario, ids.usuarios["gestor"])
        sincronizar(gestor)
        assert f"stock-critico-{ids.gabardina}" in _claves(gestor.id)
        db.session.get(Insumo, ids.gabardina).cantidad_disponible = 500
        db.session.get(Pedido, ids.activo).cambiar_estado("Entregado")
        db.session.commit()
        sincronizar(gestor)
        assert _claves(gestor.id) == set()


def test_sincronizar_dos_veces_no_duplica(app, ids):
    with app.test_request_context():
        gestor = db.session.get(Usuario, ids.usuarios["gestor"])
        sincronizar(gestor)
        antes = Notificacion.query.filter_by(usuario_id=gestor.id).count()
        sincronizar(gestor)
        assert Notificacion.query.filter_by(usuario_id=gestor.id).count() == antes


def test_cliente_recibe_aviso_de_cambio_de_fase(app, ids):
    with app.test_request_context():
        pedido = db.session.get(Pedido, ids.activo)
        registrar_evento(pedido, estado="En Costura", nota="Ya estamos cosiendo",
                         usuario=db.session.get(Usuario, ids.usuarios["gestor"]))
        db.session.commit()
        avisos = Notificacion.query.filter_by(usuario_id=ids.usuarios["cliente"], tipo="pedido").all()
        assert len(avisos) == 1 and avisos[0].titulo == "ORD-T-001: En Costura"
        assert avisos[0].mensaje == "Ya estamos cosiendo"
        assert Notificacion.query.filter_by(usuario_id=ids.usuarios["cliente_b"]).count() == 0


def test_campana_y_marcar_como_leida(app, ids, entrar):
    c = entrar("gestor")
    html = c.get("/dashboard").get_data(as_text=True)
    assert "avisos__contador" in html and "ORD-T-001 vence" in html
    with app.app_context():
        aviso = Notificacion.query.filter_by(usuario_id=ids.usuarios["gestor"]).first()
        aviso_id, destino = aviso.id, aviso.url
    r = c.get(f"/notificaciones/{aviso_id}/ir")
    assert r.status_code == 302 and r.headers["Location"].endswith(destino)
    with app.app_context():
        assert db.session.get(Notificacion, aviso_id).leida

    c.post("/notificaciones/leer-todas", data={"volver": "/dashboard"})
    with app.app_context():
        assert Notificacion.query.filter_by(usuario_id=ids.usuarios["gestor"], leida=False).count() == 0


def test_no_se_puede_abrir_el_aviso_de_otro(app, ids, entrar):
    entrar("gestor").get("/notificaciones/")
    with app.app_context():
        ajeno = Notificacion.query.filter_by(usuario_id=ids.usuarios["gestor"]).first().id
    c = entrar("ventas")
    assert c.get(f"/notificaciones/{ajeno}/ir").status_code == 404
    assert c.post(f"/notificaciones/{ajeno}/leer").status_code == 404


def test_redireccion_externa_bloqueada(app, ids, entrar):
    with app.app_context():
        n = Notificacion(usuario_id=ids.usuarios["ventas"], tipo="pedido", titulo="x", clave="x",
                         url="https://sitio-malicioso.example")
        db.session.add(n)
        db.session.commit()
        n_id = n.id
    r = entrar("ventas").get(f"/notificaciones/{n_id}/ir")
    assert r.headers["Location"].endswith("/notificaciones/")
