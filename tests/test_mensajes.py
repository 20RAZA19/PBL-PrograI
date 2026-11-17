"""Mensajería asistente de ventas ↔ cliente."""
from datetime import datetime, timedelta

from app.extensions import db
from app.mensajes.servicios import purgar_conversaciones, sin_leer_total
from app.models import Conversacion, Mensaje, Notificacion, Usuario


def _abrir(entrar, asunto="Duda sobre mi pedido", texto="¿Cuándo llega ORD-T-001?"):
    c = entrar("cliente")
    r = c.post("/mensajes/nueva", data={"asunto": asunto, "texto": texto})
    assert r.status_code == 302, r.data
    return c, int(r.headers["Location"].rstrip("/").split("/")[-1])


def test_cliente_abre_y_ventas_responde(app, entrar, ctx):
    cliente, cid = _abrir(entrar)
    ventas = entrar("ventas")
    html = ventas.get("/mensajes/").get_data(as_text=True)
    assert "Duda sobre mi pedido" in html and "Colegio Prueba" in html
    assert sin_leer_total(Usuario.query.filter_by(email="ventas@test.com").one()) == 1
    assert ventas.get(f"/mensajes/{cid}").status_code == 200          # al abrirla queda leída
    assert sin_leer_total(Usuario.query.filter_by(email="ventas@test.com").one()) == 0

    r = ventas.post(f"/mensajes/{cid}/enviar", data={"texto": "Llega el viernes."})
    assert r.status_code == 302
    datos = cliente.get(f"/mensajes/{cid}/mensajes.json?desde=0").get_json()
    assert [m["texto"] for m in datos["mensajes"]] == ["¿Cuándo llega ORD-T-001?", "Llega el viernes."]
    assert datos["mensajes"][1]["de_cliente"] is False and datos["mensajes"][1]["autor"] == "Vera Ventas"
    # Solo los posteriores a `desde`
    assert cliente.get(f"/mensajes/{cid}/mensajes.json?desde={datos['ultimo']}").get_json()["mensajes"] == []


def test_envio_json_devuelve_el_mensaje(app, entrar, ctx):
    cliente, cid = _abrir(entrar)
    r = cliente.post(f"/mensajes/{cid}/enviar", data={"texto": "Otra duda"}, headers={"Accept": "application/json"})
    assert r.status_code == 200 and r.get_json()["mensaje"]["texto"] == "Otra duda"


def test_notificaciones_a_ambos_lados(app, entrar, ctx):
    cliente, cid = _abrir(entrar)
    ventas_id = Usuario.query.filter_by(email="ventas@test.com").one().id
    assert Notificacion.query.filter_by(usuario_id=ventas_id, tipo="mensaje").count() == 1
    entrar("ventas").post(f"/mensajes/{cid}/enviar", data={"texto": "Respuesta"})
    cliente_id = Usuario.query.filter_by(email="cliente@test.com").one().id
    n = Notificacion.query.filter_by(usuario_id=cliente_id, tipo="mensaje").one()
    assert "respondió" in n.titulo and n.url.endswith(f"/mensajes/{cid}")


def test_otra_empresa_y_taller_no_ven_la_conversacion(app, entrar, ctx):
    _, cid = _abrir(entrar)
    assert entrar("cliente_b").get(f"/mensajes/{cid}").status_code == 404
    assert entrar("cliente_b").get(f"/mensajes/{cid}/mensajes.json").status_code == 404
    assert "Duda sobre mi pedido" not in entrar("cliente_b").get("/mensajes/").get_data(as_text=True)
    assert entrar("gestor").get("/mensajes/").status_code == 403
    assert entrar("gestor").get(f"/mensajes/{cid}").status_code == 403


def test_solo_el_cliente_abre_guarda_y_elimina(app, entrar, ctx):
    cliente, cid = _abrir(entrar)
    ventas = entrar("ventas")
    assert ventas.get("/mensajes/nueva").status_code == 403
    assert ventas.post(f"/mensajes/{cid}/guardar").status_code == 403
    assert ventas.post(f"/mensajes/{cid}/eliminar").status_code == 403

    cliente.post(f"/mensajes/{cid}/guardar")
    assert db.session.get(Conversacion, cid).guardada is True
    cliente.post(f"/mensajes/{cid}/guardar")
    assert db.session.get(Conversacion, cid).guardada is False

    assert cliente.post(f"/mensajes/{cid}/eliminar").status_code == 302
    assert db.session.get(Conversacion, cid) is None
    assert Mensaje.query.filter_by(conversacion_id=cid).count() == 0


def test_caducidad_respeta_las_guardadas(app, entrar, ctx):
    _, vieja = _abrir(entrar, "Vieja")
    _, guardada = _abrir(entrar, "Guardada")
    _, reciente = _abrir(entrar, "Reciente")
    hace_40 = datetime.now() - timedelta(days=40)
    db.session.get(Conversacion, vieja).ultima_actividad = hace_40
    g = db.session.get(Conversacion, guardada)
    g.ultima_actividad, g.guardada = hace_40, True
    db.session.commit()

    assert purgar_conversaciones() == 1
    assert db.session.get(Conversacion, vieja) is None
    assert db.session.get(Conversacion, guardada) is not None
    assert db.session.get(Conversacion, reciente) is not None
    assert Mensaje.query.join(Conversacion).count() == 2


def test_comando_purgar_mensajes(app, entrar, ctx):
    _, cid = _abrir(entrar)
    db.session.get(Conversacion, cid).ultima_actividad = datetime.now() - timedelta(days=31)
    db.session.commit()
    salida = app.test_cli_runner().invoke(args=["purgar-mensajes"]).output
    assert "1 conversación" in salida


def test_mensaje_vacio_o_muy_largo(app, entrar, ctx):
    cliente, cid = _abrir(entrar)
    cliente.post(f"/mensajes/{cid}/enviar", data={"texto": "   "})
    cliente.post(f"/mensajes/{cid}/enviar", data={"texto": "x" * 1001})
    assert Mensaje.query.filter_by(conversacion_id=cid).count() == 1


def test_contador_en_el_menu(app, entrar, ctx):
    _abrir(entrar)
    html = entrar("ventas").get("/dashboard").get_data(as_text=True)
    assert 'Mensajes\n                <span class="nav-badge">1</span>' in html or ("Mensajes" in html and "nav-badge" in html)
    assert "/mensajes/" not in entrar("gestor").get("/dashboard").get_data(as_text=True)
