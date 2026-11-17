"""Seguridad: cabeceras, fuerza bruta, registro, contraseñas, redirecciones y CSV."""
import pytest

from app.extensions import db
from app.forms import clave_robusta
from app.models import Usuario
from app.utils import celda_csv
from tests.conftest import CLAVE


def test_cabeceras_de_seguridad(app):
    r = app.test_client().get("/auth/login")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "strict-origin" in r.headers["Referrer-Policy"]


def test_paginas_privadas_no_se_guardan_en_cache(entrar):
    r = entrar("gestor").get("/dashboard")
    assert r.headers.get("Cache-Control") == "no-store"


def test_cookie_de_sesion_protegida(app):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["SECRET_KEY"] and app.config["SECRET_KEY"] != "pblprogra2"


def test_bloqueo_por_intentos_fallidos(app):
    c = app.test_client()
    for _ in range(app.config["LOGIN_MAX_INTENTOS_CUENTA"]):
        r = c.post("/auth/login", data={"email": "gestor@test.com", "password": "incorrecta1"})
        assert r.status_code == 200
    # Con la cuenta bloqueada ni siquiera la contraseña correcta deja entrar
    r = c.post("/auth/login", data={"email": "gestor@test.com", "password": CLAVE})
    assert r.status_code == 429
    assert "Demasiados intentos" in r.get_data(as_text=True)
    # Otra cuenta sigue funcionando
    assert c.post("/auth/login", data={"email": "ventas@test.com", "password": CLAVE}).status_code == 302


def test_bloqueo_por_ip(app):
    app.config["LOGIN_MAX_INTENTOS_IP"] = 3
    c = app.test_client()
    for i in range(3):
        c.post("/auth/login", data={"email": f"x{i}@test.com", "password": "nada1234"})
    r = c.post("/auth/login", data={"email": "ventas@test.com", "password": CLAVE})
    assert r.status_code == 429


def test_redireccion_externa_tras_login_se_ignora(app):
    c = app.test_client()
    r = c.post("/auth/login?next=//sitio-malicioso.com", data={"email": "gestor@test.com", "password": CLAVE})
    assert r.status_code == 302
    assert "sitio-malicioso" not in r.headers["Location"]


def _registrar(app, empresa, email="nuevo@test.com", password="Segura2026"):
    return app.test_client().post("/auth/registro", data={
        "nombre": "Nuevo Cliente", "email": email, "password": password, "confirm_password": password,
        "rol_solicitado": "cliente", "empresa": empresa})


def test_unirse_a_empresa_existente_requiere_aprobacion(app, ctx):
    r = _registrar(app, "colegio prueba")  # sin importar mayúsculas
    assert r.status_code == 302
    u = Usuario.query.filter_by(email="nuevo@test.com").one()
    assert u.estado_permiso == "pendiente"
    assert u.cliente.nombre == "Colegio Prueba"
    # Mientras esté pendiente no puede entrar a ver los pedidos de esa empresa
    r = app.test_client().post("/auth/login", data={"email": "nuevo@test.com", "password": "Segura2026"},
                               follow_redirects=True)
    assert "pendiente" in r.get_data(as_text=True)


def test_empresa_nueva_queda_aprobada(app, ctx):
    _registrar(app, "Empresa Nueva S.A.")
    u = Usuario.query.filter_by(email="nuevo@test.com").one()
    assert u.estado_permiso == "aprobado"
    assert u.cliente.nombre == "Empresa Nueva S.A."


@pytest.mark.parametrize("clave", ["corta1", "solo-letras-aqui", "12345678901", "admin123"])
def test_contrasenas_debiles_se_rechazan_en_registro(app, ctx, clave):
    r = _registrar(app, "Otra Empresa", password=clave)
    assert r.status_code == 200
    assert Usuario.query.filter_by(email="nuevo@test.com").first() is None


def test_clave_robusta():
    assert clave_robusta("Segura2026") is None
    assert clave_robusta("password1")
    assert clave_robusta("sinnumeros")
    assert clave_robusta("ana2026@x.com", "ana2026@x.com")


def test_csv_no_permite_formulas():
    assert celda_csv("=HYPERLINK(\"http://x\")").startswith("'")
    assert celda_csv("+50") == "'+50"
    assert celda_csv("Normal") == "Normal"
    assert celda_csv(-5) == -5


def test_bitacora_csv_neutraliza_formulas(app, entrar):
    c = app.test_client()
    c.post("/auth/login", data={"email": "=1+1", "password": "x"})
    texto = entrar("admin").get("/admin/bitacora.csv").get_data(as_text=True)
    assert "«=1+1»" in texto  # la descripción empieza con texto, no con «=»
    for linea in texto.splitlines()[1:]:
        for celda in linea.split(","):
            assert not celda.startswith("=")


def test_comando_claves_demo_cambia_contrasenas(app, ctx):
    u = Usuario(email="gestor@arteycolor.com", nombre="Demo", rol="gestor", estado_permiso="aprobado")
    u.set_password("gestor123")
    db.session.add(u)
    db.session.commit()
    salida = app.test_cli_runner().invoke(args=["claves-demo"]).output
    db.session.refresh(u)
    assert not u.check_password("gestor123")
    clave = salida.split("gestor@arteycolor.com")[1].split()[0]
    assert u.check_password(clave)


def test_comando_crear_admin(app, ctx):
    r = app.test_cli_runner().invoke(args=["crear-admin", "--email", "Jefa@Arteycolor.com", "--nombre", "Jefa",
                                           "--password", "Taller2026x"])
    assert r.exit_code == 0, r.output
    u = Usuario.query.filter_by(email="jefa@arteycolor.com").one()
    assert u.rol == "admin" and u.check_password("Taller2026x")
    debil = app.test_cli_runner().invoke(args=["crear-admin", "--email", "b@x.com", "--nombre", "B",
                                               "--password", "admin123"])
    assert debil.exit_code != 0


def test_tablero_compacto_con_detalle(entrar, ids):
    html = entrar("gestor").get("/pedidos/kanban").get_data(as_text=True)
    assert 'class="kcard kcard--pronto"' in html          # vence en 2 días
    assert f'data-detalle="det-{ids.activo}"' in html
    assert f'<template id="det-{ids.activo}">' in html
    assert "Avanzar a En Costura" in html                   # acción dentro de la ventana
    assert '<dialog class="kmodal"' in html


@pytest.mark.parametrize("rol", ["ventas", "admin"])
def test_tablero_sin_botones_de_mover_para_ventas_y_admin(entrar, ids, rol):
    """Mover pedidos es gestión del taller; el administrador y ventas solo consultan."""
    html = entrar(rol).get("/pedidos/kanban").get_data(as_text=True)
    assert f'<template id="det-{ids.activo}">' in html
    assert "Avanzar a" not in html and "Nuevo Pedido" not in html


def test_ya_no_existe_el_registro_manual_de_pedidos(entrar, ids):
    assert entrar("admin").get("/pedidos/nuevo").status_code == 404
    # Y mover por URL directa tampoco lo puede hacer el administrador
    assert entrar("admin").post(f"/pedidos/{ids.activo}/mover/siguiente").status_code == 403
    assert entrar("gestor").post(f"/pedidos/{ids.activo}/mover/siguiente").status_code == 302
