"""Bot de WhatsApp: firma de Twilio, identificación por teléfono, comandos y simulador."""
import re

import pytest

from app.extensions import db
from app.models import Auditoria, Usuario
from app.whatsapp.bot import MENSAJE_NO_REGISTRADO, procesar, usuario_por_telefono
from app.whatsapp.twilio import calcular_firma, firma_valida, twiml

TELEFONO = "+503 7777 1234"
REMITENTE = "whatsapp:+50377771234"
TOKEN_TWILIO = "token-de-prueba-twilio"


@pytest.fixture
def cliente_con_telefono(app, ctx):
    u = Usuario.query.filter_by(email="cliente@test.com").one()
    u.telefono = TELEFONO
    db.session.commit()
    return u


def _webhook(app, body, remitente=REMITENTE, firmar=True, token=TOKEN_TWILIO):
    app.config["TWILIO_AUTH_TOKEN"] = token
    c = app.test_client()
    datos = {"From": remitente, "Body": body, "MessageSid": "SM123"}
    url = "http://localhost/whatsapp/webhook"
    cabeceras = {"X-Twilio-Signature": calcular_firma(url, datos, TOKEN_TWILIO)} if firmar else {}
    return c.post("/whatsapp/webhook", data=datos, headers=cabeceras)


# --- Twilio -------------------------------------------------------------------
def test_firma_de_twilio():
    params = {"From": "whatsapp:+1", "Body": "hola"}
    firma = calcular_firma("https://x.test/w", params, "secreto")
    assert firma_valida("https://x.test/w", params, firma, "secreto")
    assert not firma_valida("https://x.test/w", params, firma, "otro")
    assert not firma_valida("https://x.test/w", {"Body": "cambiado"}, firma, "secreto")
    assert not firma_valida("https://x.test/w", params, "", "secreto")
    # La URL firmada sin puerto explícito también vale cuando llega con :443
    assert firma_valida("https://x.test:443/w", params, firma, "secreto")


def test_twiml_escapa_xml():
    assert "&lt;b&gt;" in twiml("<b>")
    assert twiml("hola").startswith('<?xml version="1.0"')


def test_webhook_apagado_sin_token(app):
    app.config["TWILIO_AUTH_TOKEN"] = ""
    r = app.test_client().post("/whatsapp/webhook", data={"From": REMITENTE, "Body": "MENÚ"})
    assert r.status_code == 503


def test_webhook_rechaza_sin_firma(app, cliente_con_telefono):
    assert _webhook(app, "TOKEN", firmar=False).status_code == 403
    r = app.test_client().post("/whatsapp/webhook", data={"From": REMITENTE, "Body": "TOKEN"},
                               headers={"X-Twilio-Signature": "firma-falsa"})
    assert r.status_code == 403


def test_webhook_responde_twiml(app, cliente_con_telefono):
    r = _webhook(app, "menú")
    assert r.status_code == 200
    assert r.mimetype == "text/xml"
    assert "ESTADO" in r.get_data(as_text=True) and "Carla" in r.get_data(as_text=True)


# --- Identificación -----------------------------------------------------------
def test_numero_no_registrado_recibe_mensaje_generico(app, ctx):
    respuesta, usuario = procesar("whatsapp:+50399990000", "TOKEN")
    assert usuario is None and respuesta == MENSAJE_NO_REGISTRADO
    assert "AYC-" not in respuesta


def test_telefono_sin_codigo_de_pais_coincide(app, ctx):
    u = Usuario.query.filter_by(email="cliente@test.com").one()
    u.telefono = "7777-1234"     # guardado sin +503
    db.session.commit()
    assert usuario_por_telefono("whatsapp:+50377771234") is u
    assert usuario_por_telefono("whatsapp:+50377771299") is None


def test_cuenta_inactiva_o_de_equipo_no_responde(app, ctx):
    gestor = Usuario.query.filter_by(email="gestor@test.com").one()
    gestor.telefono = TELEFONO
    db.session.commit()
    assert usuario_por_telefono(REMITENTE) is None          # solo clientes
    cliente = Usuario.query.filter_by(email="cliente@test.com").one()
    cliente.telefono, gestor.telefono = TELEFONO, None
    cliente.activo = False
    db.session.commit()
    assert usuario_por_telefono(REMITENTE) is None


# --- Comandos -----------------------------------------------------------------
def test_token_se_crea_y_se_regenera(app, cliente_con_telefono):
    u = cliente_con_telefono
    assert u.token_seguimiento is None
    respuesta, _ = procesar(REMITENTE, "token")
    db.session.commit()
    assert u.token_seguimiento and u.token_seguimiento in respuesta
    anterior = u.token_seguimiento
    respuesta, _ = procesar(REMITENTE, "Nuevo Token")
    db.session.commit()
    assert u.token_seguimiento != anterior and u.token_seguimiento in respuesta
    # El token no queda escrito en la bitácora
    assert not Auditoria.query.filter(Auditoria.descripcion.contains(anterior)).count()


def test_estado_lista_pedidos_sin_precios(app, cliente_con_telefono):
    respuesta, _ = procesar(REMITENTE, "ESTADO")
    assert "ORD-T-001" in respuesta and "En Corte" in respuesta
    assert "$" not in respuesta
    assert "ORD-T-002" not in respuesta   # pedido de otra empresa


def test_recuperar_ya_no_emite_codigo_por_whatsapp(app, cliente_con_telefono):
    respuesta, _ = procesar(REMITENTE, "RECUPERAR")
    db.session.commit()
    assert "/auth/recuperar" in respuesta and "correo" in respuesta
    assert not re.search(r"\b\d{6}\b", respuesta)
    assert not cliente_con_telefono.codigo_recuperacion_vigente


def test_texto_desconocido_devuelve_menu(app, cliente_con_telefono):
    respuesta, _ = procesar(REMITENTE, "buenas tardes, ¿cómo va mi pedido?")
    assert "ESTADO" in respuesta and "TOKEN" in respuesta


def test_limite_de_mensajes_por_numero(app, cliente_con_telefono):
    app.config["WHATSAPP_MAX_MENSAJES"] = 3
    for _ in range(3):
        procesar(REMITENTE, "MENÚ")
        db.session.commit()
    respuesta, usuario = procesar(REMITENTE, "TOKEN")
    assert usuario is None and "demasiados" in respuesta.lower()


# --- Simulador ----------------------------------------------------------------
def test_simulador_solo_admin(entrar):
    assert entrar("ventas").get("/whatsapp/simulador").status_code == 403
    assert entrar("cliente").get("/whatsapp/simulador").status_code == 403
    assert entrar("admin").get("/whatsapp/simulador").status_code == 200


def test_simulador_conversa(app, entrar, cliente_con_telefono):
    c = entrar("admin")
    r = c.post("/whatsapp/simulador", data={"telefono": TELEFONO, "mensaje": "ESTADO"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "ORD-T-001" in html and "wa-msg--bot" in html
    r = c.post("/whatsapp/simulador/limpiar", follow_redirects=True)
    assert "wa-msg--bot" not in r.get_data(as_text=True)


# --- Guía para clientes -----------------------------------------------------------
def test_guia_solo_para_clientes(entrar):
    r = entrar("cliente").get("/whatsapp/guia")
    assert r.status_code == 200 and "Qué puedes pedir" in r.get_data(as_text=True)
    for rol in ("ventas", "gestor", "admin"):
        assert entrar(rol).get("/whatsapp/guia").status_code == 403
        assert "/whatsapp/guia" not in entrar(rol).get("/dashboard").get_data(as_text=True)


def test_guia_antepone_join_al_codigo_del_sandbox(app, entrar):
    app.config["WHATSAPP_CODIGO_UNION"] = "thought-not"
    html = entrar("cliente").get("/whatsapp/guia").get_data(as_text=True)
    assert "join thought-not" in html
    app.config["WHATSAPP_CODIGO_UNION"] = "join thought-not"
    html = entrar("cliente").get("/whatsapp/guia").get_data(as_text=True)
    assert "join join" not in html and "join thought-not" in html


def test_guia_revisa_el_numero_del_cliente(app, entrar, ctx):
    html = entrar("cliente").get("/whatsapp/guia").get_data(as_text=True)
    assert "Antes de escribir, revisa tu número" in html and "Agrega tu número de WhatsApp" in html
    u = Usuario.query.filter_by(email="cliente@test.com").one()
    u.telefono = TELEFONO
    db.session.commit()
    html = entrar("cliente").get("/whatsapp/guia").get_data(as_text=True)
    assert "Tu número está listo" in html
    # Respuesta real a ESTADO con sus pedidos, sin precios
    assert "Así te respondería ahora mismo" in html and "ORD-T-001" in html and "ORD-T-002" not in html


def test_guia_avisa_numero_repetido(app, entrar, ctx):
    for email in ("cliente@test.com", "gestor@test.com"):
        Usuario.query.filter_by(email=email).one().telefono = TELEFONO
    db.session.commit()
    html = entrar("cliente").get("/whatsapp/guia").get_data(as_text=True)
    assert "también está en otra cuenta" in html and "Tu número está listo" not in html


def test_guia_muestra_la_frase_de_union(app, entrar):
    app.config.update(WHATSAPP_CODIGO_UNION="join silver-tiger", TWILIO_WHATSAPP_FROM="whatsapp:+14155238886")
    html = entrar("cliente").get("/whatsapp/guia").get_data(as_text=True)
    assert "join silver-tiger" in html and "wa.me/14155238886?text=join%20silver-tiger" in html
