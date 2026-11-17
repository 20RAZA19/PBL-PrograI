"""Token de seguimiento: llave de solo lectura para ver el estado de los pedidos."""
import pytest

from app.extensions import db
from app.models import Auditoria, Pedido, Solicitud, Usuario, normalizar_token, nuevo_token_seguimiento


@pytest.fixture
def con_token(app, ctx):
    u = Usuario.query.filter_by(email="cliente@test.com").one()
    u.telefono = "+503 7123-4567"
    token = u.generar_token()
    db.session.commit()
    return u, token


def _consultar(app, token, digitos="4567"):
    return app.test_client().post("/seguimiento/", data={"token": token, "digitos": digitos})


def test_formato_y_normalizacion_del_token():
    token = nuevo_token_seguimiento()
    assert len(token) == 13 and token.startswith("AYC-")
    assert not set(token[4:].replace("-", "")) & set("0O1IL")
    assert normalizar_token(token.lower().replace("-", " ")) == token
    assert normalizar_token(token[4:]) == token
    assert normalizar_token("AYC-123") is None and normalizar_token("") is None
    assert len({nuevo_token_seguimiento() for _ in range(200)}) == 200


def test_consulta_muestra_solo_los_pedidos_de_su_empresa(app, con_token):
    _, token = con_token
    r = _consultar(app, token)
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "ORD-T-001" in html and "Camisa Prueba" in html and "En Corte" in html
    assert "ORD-T-002" not in html                     # pedido de otra empresa
    assert r.headers["Cache-Control"] == "no-store"


def test_consulta_no_muestra_precios(app, con_token):
    _, token = con_token
    pedido = Pedido.query.filter_by(folio="ORD-T-001").one()
    pedido.precio_unitario = 77.77
    db.session.commit()
    html = _consultar(app, token).get_data(as_text=True)
    assert "77.77" not in html and "7,777" not in html and "$" not in html


@pytest.mark.parametrize("token, digitos", [
    ("AYC-AAAA-BBBB", "4567"),     # token inexistente
    ("bueno", "0000"),              # dígitos incorrectos
    ("bueno", "567"),               # dígitos incompletos
    ("", "4567"),
])
def test_datos_incorrectos_no_revelan_nada(app, con_token, token, digitos):
    _, real = con_token
    r = _consultar(app, real if token == "bueno" else token, digitos)
    assert r.status_code in (200, 403)
    assert "ORD-T-001" not in r.get_data(as_text=True)


def test_mismo_mensaje_para_token_falso_y_digitos_falsos(app, con_token):
    _, real = con_token
    a = _consultar(app, "AYC-AAAA-BBBB").get_data(as_text=True)
    b = _consultar(app, real, "0000").get_data(as_text=True)
    assert "Los datos no coinciden" in a and "Los datos no coinciden" in b


def test_el_token_no_sirve_sin_telefono_ni_con_cuenta_inactiva(app, con_token):
    u, token = con_token
    u.activo = False
    db.session.commit()
    assert "ORD-T-001" not in _consultar(app, token).get_data(as_text=True)
    u.activo, u.telefono = True, None
    db.session.commit()
    assert "ORD-T-001" not in _consultar(app, token, "----").get_data(as_text=True)


def test_bloqueo_por_intentos(app, con_token):
    _, token = con_token
    for _ in range(8):
        assert _consultar(app, "AYC-AAAA-BBBB").status_code == 403
    r = _consultar(app, token)       # ni el token correcto pasa durante el bloqueo
    assert r.status_code == 429 and "ORD-T-001" not in r.get_data(as_text=True)


def test_el_token_es_de_solo_lectura(app, con_token):
    """Con el token no hay sesión: no se puede solicitar, cotizar ni entrar al portal."""
    _, token = con_token
    c = app.test_client()
    c.post("/seguimiento/", data={"token": token, "digitos": "4567"})
    assert c.get("/solicitudes/nueva").status_code == 302
    assert "/auth/login" in c.get("/dashboard").headers["Location"]
    antes = Solicitud.query.count()
    c.post("/solicitudes/nueva", data={"linea_descripcion": ["Camisa"], "linea_cantidad": ["5"]})
    assert Solicitud.query.count() == antes


def test_consultas_quedan_en_bitacora_sin_exponer_el_token(app, con_token):
    _, token = con_token
    _consultar(app, token)
    _consultar(app, "AYC-AAAA-BBBB")
    registros = Auditoria.query.filter_by(accion="consulta").all()
    assert len(registros) == 2
    todo = " ".join((r.descripcion or "") + (r.cambios or "") for r in Auditoria.query.all())
    assert token not in todo


def test_regenerar_invalida_el_anterior(app, entrar, con_token):
    u, viejo = con_token
    admin = entrar("admin")
    assert viejo in admin.get(f"/admin/usuarios/{u.id}/editar").get_data(as_text=True)
    assert admin.post(f"/admin/usuarios/{u.id}/token").status_code == 302
    db.session.refresh(u)
    assert u.token_seguimiento != viejo
    assert "ORD-T-001" not in _consultar(app, viejo).get_data(as_text=True)
    assert "ORD-T-001" in _consultar(app, u.token_seguimiento).get_data(as_text=True)


def test_token_requiere_telefono_y_rol_cliente(app, entrar, ctx, ids):
    admin = entrar("admin")
    cliente = Usuario.query.filter_by(email="cliente@test.com").one()
    cliente.telefono = None
    db.session.commit()
    admin.post(f"/admin/usuarios/{cliente.id}/token")
    admin.post(f"/admin/usuarios/{ids.usuarios['gestor']}/token")
    assert Usuario.query.filter(Usuario.token_seguimiento.isnot(None)).count() == 0


@pytest.mark.parametrize("rol", ["gestor", "ventas", "cliente"])
def test_solo_el_admin_gestiona_tokens(entrar, ids, rol):
    assert entrar(rol).post(f"/admin/usuarios/{ids.usuarios['cliente']}/token").status_code == 403


def test_el_cliente_no_ve_su_token_en_el_sitio(entrar, con_token):
    _, token = con_token
    c = entrar("cliente")
    for url in ("/dashboard", "/auth/perfil", "/solicitudes/"):
        assert token not in c.get(url).get_data(as_text=True)
