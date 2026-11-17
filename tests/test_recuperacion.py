"""Recuperación de contraseña con un código enviado por correo."""
import re
from datetime import datetime, timedelta

import pytest

from app.extensions import db
from app.models import Usuario
from tests.conftest import CLAVE

NUEVA = "NuevaClave2026"


@pytest.fixture
def buzon(app):
    app.extensions["correos_enviados"] = []
    return app.extensions["correos_enviados"]


def _pedir(app, email="cliente@test.com", c=None):
    c = c or app.test_client()
    return c, c.post("/auth/recuperar", data={"email": email})


def _codigo_de(correo):
    texto = correo.get_body(preferencelist=("plain",)).get_content()
    return re.search(r"\b(\d{6})\b", texto).group(1)


def _cambiar(app, email, codigo, clave=NUEVA, c=None):
    c = c or app.test_client()
    return c.post("/auth/recuperar/codigo", data={
        "email": email, "codigo": codigo, "password_nueva": clave, "password_confirmar": clave})


def _entra(app, email, clave):
    return app.test_client().post("/auth/login", data={"email": email, "password": clave}).status_code == 302


def test_flujo_completo_por_correo(app, ctx, buzon):
    c, r = _pedir(app)
    assert r.status_code == 302 and r.headers["Location"].endswith("/auth/recuperar/codigo")
    assert len(buzon) == 1
    correo = buzon[0]
    assert correo["To"] == "cliente@test.com"
    assert "código" in correo["Subject"]
    codigo = _codigo_de(correo)
    assert codigo in correo["Subject"]                      # visible en la bandeja sin abrirlo
    # El paso 2 trae el correo ya escrito (guardado en la sesión, no en la URL)
    assert 'value="cliente@test.com"' in c.get("/auth/recuperar/codigo").get_data(as_text=True)

    r = _cambiar(app, "cliente@test.com", codigo, c=c)
    assert r.status_code == 302 and r.headers["Location"].endswith("/auth/login")
    assert _entra(app, "cliente@test.com", NUEVA)
    assert not _entra(app, "cliente@test.com", CLAVE)
    # Un solo uso
    r = _cambiar(app, "cliente@test.com", codigo, "OtraClave2026")
    assert r.status_code == 200 and "no es válido" in r.get_data(as_text=True)


def test_sirve_tambien_para_el_equipo(app, ctx, buzon):
    _pedir(app, "gestor@test.com")
    assert len(buzon) == 1 and buzon[0]["To"] == "gestor@test.com"


def test_correo_inexistente_responde_igual_y_no_envia(app, ctx, buzon):
    _, r1 = _pedir(app, "nadie@test.com")
    _, r2 = _pedir(app, "cliente@test.com")
    assert r1.status_code == r2.status_code == 302
    assert r1.headers["Location"] == r2.headers["Location"]
    assert [m["To"] for m in buzon] == ["cliente@test.com"]


def test_cuenta_pendiente_o_inactiva_no_recibe(app, ctx, buzon):
    u = Usuario.query.filter_by(email="cliente@test.com").one()
    u.activo = False
    db.session.commit()
    _pedir(app)
    assert buzon == []


def test_limite_de_correos_por_cuenta(app, ctx, buzon):
    u = Usuario.query.filter_by(email="cliente@test.com").one()
    _pedir(app)
    _pedir(app)                       # menos de un minuto después: no se reenvía
    assert len(buzon) == 1
    for _ in range(4):                # simula que pasó el minuto entre pedidos
        u.recuperacion_expira -= timedelta(minutes=2)
        db.session.commit()
        _pedir(app)
    assert len(buzon) == app.config["RECUPERACION_MAX_CORREOS_HORA"]


def test_cinco_fallos_invalidan_el_codigo(app, ctx, buzon):
    _pedir(app)
    codigo = _codigo_de(buzon[0])
    for _ in range(5):
        _cambiar(app, "cliente@test.com", "000000")
    assert _cambiar(app, "cliente@test.com", codigo).status_code == 200
    assert _entra(app, "cliente@test.com", CLAVE)


def test_codigo_expirado(app, ctx, buzon):
    _pedir(app)
    codigo = _codigo_de(buzon[0])
    u = Usuario.query.filter_by(email="cliente@test.com").one()
    u.recuperacion_expira = datetime.now() - timedelta(minutes=1)
    db.session.commit()
    assert _cambiar(app, "cliente@test.com", codigo).status_code == 200
    assert _entra(app, "cliente@test.com", CLAVE)


def test_codigo_de_otra_cuenta_no_sirve(app, ctx, buzon):
    _pedir(app, "gestor@test.com")
    codigo = _codigo_de(buzon[0])
    assert _cambiar(app, "cliente@test.com", codigo).status_code == 200
    assert _entra(app, "cliente@test.com", CLAVE)


def test_contrasena_debil_se_rechaza(app, ctx, buzon):
    _pedir(app)
    assert _cambiar(app, "cliente@test.com", _codigo_de(buzon[0]), "password1").status_code == 200
    assert _entra(app, "cliente@test.com", CLAVE)


def test_bloqueo_por_ip(app, ctx, buzon):
    app.config["LOGIN_MAX_INTENTOS_IP"] = 3
    for _ in range(3):
        _pedir(app, "nadie@test.com")
    _, r = _pedir(app)
    assert r.status_code == 429 and buzon == []


def test_el_codigo_no_queda_en_la_base_ni_en_la_bitacora(app, ctx, buzon):
    from app.models import Auditoria
    _pedir(app)
    codigo = _codigo_de(buzon[0])
    u = Usuario.query.filter_by(email="cliente@test.com").one()
    assert codigo not in (u.recuperacion_hash or "")
    assert not Auditoria.query.filter(Auditoria.descripcion.contains(codigo)).count()


def test_sin_configurar_no_envia_en_produccion(app, ctx):
    from app.correo import enviar_correo
    app.config.update(TESTING=False, MAIL_USERNAME="", MAIL_PASSWORD="", SESSION_COOKIE_SECURE=True)
    with app.test_request_context():
        assert enviar_correo("x@test.com", "Asunto", "Texto") is False


def test_usuario_con_sesion_no_ve_el_formulario(entrar):
    for url in ("/auth/recuperar", "/auth/recuperar/codigo"):
        r = entrar("cliente").get(url)
        assert r.status_code == 302 and "/auth/perfil" in r.headers["Location"]


def test_login_enlaza_a_recuperar(app):
    html = app.test_client().get("/auth/login").get_data(as_text=True)
    assert "/auth/recuperar" in html and "por correo" in html
