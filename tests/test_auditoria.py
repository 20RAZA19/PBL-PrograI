"""Bitácora de auditoría automática."""
import json

from app.extensions import db
from app.models import Auditoria, Insumo


def test_editar_un_insumo_queda_registrado_con_sus_cambios(app, ids, entrar):
    c = entrar("admin")
    c.post(f"/telas/{ids.popelina}/editar", data={
        "nombre": "Popelina", "categoria": "Tela", "unidad_medida": "Metros", "tipo": "Textil",
        "codigo_pantone": "P 100 C", "color_hex": "#111111", "stock_minimo": "80",
        "costo_unitario": "2.90", "proveedor_id": str(ids.proveedor)})
    with app.app_context():
        reg = Auditoria.query.filter_by(accion="editar", entidad="Insumo").one()
        assert reg.usuario_nombre == "Ada Admin" and reg.entidad_id == ids.popelina
        assert reg.cambios_dict["stock_minimo"] == ["50", "80"]
        assert reg.cambios_dict["costo_unitario"] == ["2.50", "2.90"]
        assert "nombre" not in reg.cambios_dict  # no cambió
        assert reg.ip == "127.0.0.1"


def test_crear_y_eliminar_quedan_registrados(app, ids, entrar):
    c = entrar("ventas")
    c.post("/cotizaciones/nueva", data={
        "cliente_id": ids.colegio, "validez_dias": "15", "descuento_pct": "0", "iva_pct": "13",
        "linea_descripcion": ["Gorra"], "linea_cantidad": ["10"], "linea_precio": ["3"], "linea_diseno": [""],
        "linea_tallas": [""]})
    with app.app_context():
        from app.models import Cotizacion
        cot_id = Cotizacion.query.one().id
        assert Auditoria.query.filter_by(accion="crear", entidad="Cotización").count() == 1
    c.post(f"/cotizaciones/{cot_id}/eliminar")
    with app.app_context():
        assert Auditoria.query.filter_by(accion="eliminar", entidad="Cotización").count() == 1


def test_inicios_de_sesion_y_fallidos(app, ids, entrar):
    entrar("gestor")
    app.test_client().post("/auth/login", data={"email": "gestor@test.com", "password": "incorrecta"})
    with app.app_context():
        sesiones = Auditoria.query.filter_by(accion="sesion").all()
        textos = [s.descripcion for s in sesiones]
        assert any("Inició sesión" in t for t in textos)
        assert any("Intento fallido" in t and "gestor@test.com" in t for t in textos)


def test_la_contrasena_nunca_se_guarda(app, ids, entrar):
    c = entrar("ventas")
    c.post("/auth/perfil", data={"pwd-password_actual": "clave123", "pwd-password_nueva": "nueva456",
                                 "pwd-password_confirmar": "nueva456", "pwd-submit": "1"})
    with app.app_context():
        for reg in Auditoria.query.all():
            assert "pbkdf2" not in (reg.cambios or "") and "scrypt" not in (reg.cambios or "")
        cambio = Auditoria.query.filter_by(accion="editar", entidad="Usuario").one()
        assert cambio.cambios_dict == {"contraseña": ["••••", "actualizada"]}


def test_cambios_fuera_de_una_peticion_no_se_auditan(app, ids, ctx):
    db.session.get(Insumo, ids.hilo).stock_minimo = 15
    db.session.commit()
    assert Auditoria.query.count() == 0


def test_solo_el_administrador_ve_la_bitacora(app, ids, entrar):
    admin = entrar("admin")
    r = admin.get("/admin/bitacora")
    assert r.status_code == 200 and "Inició sesión" in r.get_data(as_text=True)
    csv = admin.get("/admin/bitacora.csv?accion=sesion")
    assert csv.mimetype == "text/csv" and "Inició sesión" in csv.get_data(as_text=True)
    for rol in ("gestor", "ventas", "cliente"):
        assert entrar(rol).get("/admin/bitacora").status_code == 403


def test_filtros_de_la_bitacora(app, ids, entrar):
    admin = entrar("admin")
    entrar("gestor")
    html = admin.get(f"/admin/bitacora?usuario={ids.usuarios['gestor']}").get_data(as_text=True)
    assert "Gael Gestor" in html and "Ada Admin" not in html.split("<tbody>")[1]
