"""Matriz de permisos (RBAC) de los módulos nuevos y existentes."""
import pytest

PERMITIDO, PROHIBIDO = 200, 403

# url: {rol: código esperado}
MATRIZ = {
    "/cotizaciones/":         dict(admin=200, gestor=200, ventas=200, cliente=200),
    "/cotizaciones/nueva":    dict(admin=200, gestor=403, ventas=200, cliente=403),
    "/compras/":              dict(admin=200, gestor=200, ventas=403, cliente=403),
    "/compras/ordenes":       dict(admin=200, gestor=200, ventas=403, cliente=403),
    "/costos/":               dict(admin=200, gestor=403, ventas=200, cliente=403),
    "/calidad/":              dict(admin=200, gestor=200, ventas=200, cliente=403),
    "/calidad/nuevo":         dict(admin=200, gestor=200, ventas=403, cliente=403),
    "/notificaciones/":       dict(admin=200, gestor=200, ventas=200, cliente=200),
    "/admin/bitacora":        dict(admin=200, gestor=403, ventas=403, cliente=403),
    "/catalogo/nuevo":        dict(admin=200, gestor=200, ventas=200, cliente=403),
    "/telas/nueva":           dict(admin=200, gestor=200, ventas=403, cliente=403),
    "/reportes/":             dict(admin=200, gestor=403, ventas=403, cliente=403),
    "/admin/usuarios":        dict(admin=200, gestor=403, ventas=403, cliente=403),
    "/dashboard":             dict(admin=200, gestor=200, ventas=200, cliente=200),
}
CASOS = [(url, rol, codigo) for url, roles in MATRIZ.items() for rol, codigo in roles.items()]


@pytest.mark.parametrize("url, rol, esperado", CASOS, ids=[f"{r}:{u}" for u, r, _ in CASOS])
def test_matriz_de_permisos(entrar, url, rol, esperado):
    assert entrar(rol).get(url).status_code == esperado


@pytest.mark.parametrize("url", ["/cotizaciones/", "/compras/", "/costos/", "/calidad/", "/notificaciones/",
                                 "/admin/bitacora", "/dashboard"])
def test_sin_sesion_redirige_al_login(app, url):
    r = app.test_client().get(url)
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]


def test_menu_muestra_solo_los_modulos_del_rol(entrar):
    ventas = entrar("ventas").get("/dashboard").get_data(as_text=True)
    assert "Costos y Márgenes" in ventas and ">\n                <i data-lucide=\"shopping-cart\"></i> Compras" not in ventas
    gestor = entrar("gestor").get("/dashboard").get_data(as_text=True)
    assert "Compras" in gestor and "Costos y Márgenes" not in gestor and "Bitácora" not in gestor
    cliente = entrar("cliente").get("/dashboard").get_data(as_text=True)
    assert "Mis Cotizaciones" in cliente and "Control de Calidad" not in cliente


def test_cliente_no_ve_detalles_de_costo_en_su_pedido(entrar):
    html = entrar("cliente").get("/rastreo/ORD-T-001").get_data(as_text=True)
    assert "Rentabilidad" not in html and "Control de Calidad" not in html
    html = entrar("ventas").get("/rastreo/ORD-T-001").get_data(as_text=True)
    assert "Rentabilidad" in html and "$387.00" in html
