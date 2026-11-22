"""Un número de teléfono solo puede estar en una cuenta."""
from app.extensions import db
from app.models import Usuario, telefonos_coinciden, telefonos_duplicados, usuario_con_telefono


def _perfil(c, telefono, nombre="Carla Cliente"):
    return c.post("/auth/perfil", data={"perfil-nombre": nombre, "perfil-telefono": telefono,
                                        "perfil-submit": "1"})


def test_regla_de_coincidencia():
    assert telefonos_coinciden("+503 7777-1234", "7777 1234")
    assert telefonos_coinciden("(503) 7777.1234", "+50377771234")
    assert not telefonos_coinciden("+503 7777-1234", "+503 7777-1235")
    assert not telefonos_coinciden("1234567", "1234567")       # menos de 8 dígitos: no se compara


def test_perfil_rechaza_un_numero_de_otra_cuenta(app, entrar, ctx):
    gestor = Usuario.query.filter_by(email="gestor@test.com").one()
    gestor.telefono = "+503 7777-1234"
    db.session.commit()
    r = _perfil(entrar("cliente"), "7777-1234")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and "ya está registrado en otra cuenta" in html
    assert gestor.nombre not in html                       # no revela de quién es
    assert Usuario.query.filter_by(email="cliente@test.com").one().telefono is None


def test_perfil_acepta_su_propio_numero(app, entrar, ctx):
    c = entrar("cliente")
    assert _perfil(c, "+503 7000-0001").status_code == 302
    assert _perfil(c, "+503 7000-0001").status_code == 302   # volver a guardar el mismo no choca consigo


def test_admin_no_puede_duplicar_y_ve_de_quien_es(app, entrar, ctx, ids):
    gestor = Usuario.query.filter_by(email="gestor@test.com").one()
    gestor.telefono = "+503 7777-1234"
    db.session.commit()
    cliente = Usuario.query.filter_by(email="cliente@test.com").one()
    r = entrar("admin").post(f"/admin/usuarios/{cliente.id}/editar", data={
        "nombre": cliente.nombre, "email": cliente.email, "telefono": "77771234", "rol": "cliente",
        "estado_permiso": "aprobado", "cliente_id": cliente.cliente_id, "activo": "y"})
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and gestor.nombre in html and "ya está registrado" in html
    db.session.refresh(cliente)
    assert cliente.telefono is None


def test_admin_ve_aviso_de_duplicados_existentes(app, entrar, ctx):
    # Datos heredados de antes de la validación
    for email in ("gestor@test.com", "cliente@test.com"):
        Usuario.query.filter_by(email=email).one().telefono = "+503 7777-1234"
    db.session.commit()
    assert len(telefonos_duplicados()) == 1
    assert usuario_con_telefono("7777 1234") is not None
    html = entrar("admin").get("/admin/usuarios?vista=todos").get_data(as_text=True)
    assert "número de teléfono repetido" in html
