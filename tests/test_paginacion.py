"""Las listas consultan una página a la vez y conservan los filtros al cambiar de página."""
import re
from decimal import Decimal

import pytest

from app.extensions import db
from app.models import Insumo


@pytest.fixture
def muchos_insumos(app, ctx):
    for i in range(40):
        # 0..9 críticos, 10..19 bajos, 20..39 disponibles (mínimo 100)
        cantidad = 20 if i < 10 else (80 if i < 20 else 300)
        db.session.add(Insumo(nombre=f"Hilo prueba {i:02d}", codigo=f"HP-{i:04d}", categoria="Hilo",
                              unidad_medida="Conos", cantidad_disponible=cantidad, stock_minimo=100,
                              costo_unitario=Decimal("1.00")))
    db.session.commit()


def _codigos(html):
    return set(re.findall(r"HP-\d{4}|HIL-0002", html))


def test_inventario_trae_una_pagina(entrar, muchos_insumos):
    c = entrar("gestor")
    html = c.get("/telas/?categoria=Hilo&por=10").get_data(as_text=True)
    assert len(_codigos(html)) == 10
    assert "de <strong>41</strong> insumos" in html               # 40 de prueba + el hilo base
    # Los enlaces a otras páginas conservan el filtro
    assert "categoria=Hilo" in re.search(r'href="([^"]*pagina=2[^"]*)"', html).group(1)
    segunda = c.get("/telas/?categoria=Hilo&por=10&pagina=2").get_data(as_text=True)
    assert len(_codigos(segunda)) == 10 and not (_codigos(segunda) & _codigos(html))


def test_pagina_inexistente_muestra_la_ultima(entrar, muchos_insumos):
    html = entrar("gestor").get("/telas/?categoria=Hilo&por=25&pagina=99").get_data(as_text=True)
    assert 'aria-current="page">2<' in html


def test_tamano_de_pagina_no_admite_cualquier_valor(entrar, muchos_insumos):
    html = entrar("gestor").get("/telas/?categoria=Hilo&por=100000").get_data(as_text=True)
    assert len(_codigos(html)) == 24                                # vuelve al valor por defecto


@pytest.mark.parametrize("estado", ["Crítico", "Stock Bajo", "Disponible"])
def test_filtro_de_estado_en_la_base_coincide_con_el_modelo(entrar, muchos_insumos, estado):
    html = entrar("gestor").get(f"/telas/?categoria=Hilo&estado={estado}&por=100").get_data(as_text=True)
    codigos = _codigos(html)
    esperados = {i.codigo for i in Insumo.query.filter_by(categoria="Hilo") if i.estado == estado}
    assert codigos == esperados and len(codigos) >= 10
    assert all(i.estado == estado for i in Insumo.query.filter(Insumo.codigo.in_(codigos)))


@pytest.mark.parametrize("url", ["/solicitudes/", "/cotizaciones/", "/admin/usuarios?vista=todos",
                                 "/contactos/", "/compras/ordenes", "/calidad/", "/mensajes/",
                                 "/catalogo/", "/notificaciones/", "/rastreo/", "/admin/bitacora"])
def test_las_listas_muestran_la_barra_de_paginas(entrar, url):
    r = entrar("admin").get(url)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    if "paginacion__info" in html:                                   # solo aparece si hay registros
        assert 'name="por"' in html


@pytest.mark.parametrize("url, orden", [
    ("/solicitudes/", "folio"), ("/cotizaciones/", "cliente"), ("/rastreo/", "entrega"),
    ("/mensajes/", "antigua"), ("/contactos/", "nombre_desc"),
])
def test_ordenar_por_respeta_la_eleccion_y_no_rompe_con_valores_raros(entrar, url, orden):
    c = entrar("admin")
    html = c.get(f"{url}?orden={orden}").get_data(as_text=True)
    assert 'name="orden"' in html or "paginacion__info" not in html
    if 'name="orden"' in html:
        assert f'value="{orden}" selected' in html
    # un valor inventado no debe romper la página: vuelve al orden predeterminado
    r = c.get(f"{url}?orden=no_existe&por=10")
    assert r.status_code == 200


def test_valor_por_defecto_es_diez_en_las_listas_de_trabajo(entrar, muchos_insumos):
    from app.models import Cliente, Pedido
    c = entrar("admin")
    html = c.get("/contactos/?tab=clientes").get_data(as_text=True)
    if "paginacion__info" in html and Cliente.query.count() > 10:
        assert 'value="10" selected' in html
