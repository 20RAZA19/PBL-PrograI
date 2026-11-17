"""Diseños con precio y ficha técnica, fotos de diseños e insumos, y validaciones de inventario."""
import io
import os
from decimal import Decimal

from app.archivos import eliminar_imagen
from app.extensions import db
from app.models import Diseno, Insumo

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


def _diseno(ids, **extra):
    datos = {"nombre": "Polo Nuevo", "cliente_id": str(ids.colegio), "tipo_prenda": "Polo", "tallas": "M",
             "precio_venta": "12.00", "costo_mano_obra": "3.00",
             "ficha_insumo": [str(ids.popelina), str(ids.boton)], "ficha_cantidad": ["1.2", "3"]}
    datos.update(extra)
    return datos


def test_crear_diseno_con_ficha_y_foto(app, ids, entrar):
    datos = _diseno(ids)
    datos["imagen"] = (io.BytesIO(PNG), "boceto.png")
    r = entrar("ventas").post("/catalogo/nuevo", data=datos, content_type="multipart/form-data")
    assert r.status_code == 302
    with app.app_context():
        d = Diseno.query.filter_by(nombre="Polo Nuevo").one()
        assert len(d.telas) == 2
        assert d.costo_por_prenda == Decimal("6.15")  # 1.2 × 2.50 + 3 × 0.05 + 3.00
        assert d.imagen.startswith("uploads/disenos/") and d.imagen.endswith(".png")
        assert os.path.isfile(os.path.join(app.config["UPLOAD_FOLDER"], d.imagen[len("uploads/"):]))


def test_ficha_con_insumo_repetido_se_rechaza(app, ids, entrar):
    r = entrar("ventas").post("/catalogo/nuevo", data=_diseno(
        ids, ficha_insumo=[str(ids.popelina), str(ids.popelina)], ficha_cantidad=["1", "2"]))
    assert r.status_code == 200 and "ya está en la ficha" in r.get_data(as_text=True)
    with app.app_context():
        assert Diseno.query.filter_by(nombre="Polo Nuevo").count() == 0


def test_precio_negativo_se_rechaza(app, ids, entrar):
    r = entrar("ventas").post("/catalogo/nuevo", data=_diseno(ids, precio_venta="-5"))
    assert r.status_code == 200
    with app.app_context():
        assert Diseno.query.filter_by(nombre="Polo Nuevo").count() == 0


def test_editar_ficha_quita_y_cambia_insumos(app, ids, entrar):
    entrar("gestor").post(f"/catalogo/{ids.camisa}/editar", data=_diseno(
        ids, nombre="Camisa Prueba", ficha_insumo=[str(ids.popelina)], ficha_cantidad=["1.8"]))
    with app.app_context():
        d = db.session.get(Diseno, ids.camisa)
        assert [(dt.tela.nombre, float(dt.metros_por_unidad)) for dt in d.telas] == [("Popelina", 1.8)]


def test_archivo_que_no_es_imagen_se_rechaza(app, ids, entrar):
    c = entrar("ventas")
    for contenido, nombre in [(b"MZ ejecutable", "virus.exe"), (b"no soy una imagen", "falso.png")]:
        datos = _diseno(ids)
        datos["imagen"] = (io.BytesIO(contenido), nombre)
        r = c.post("/catalogo/nuevo", data=datos, content_type="multipart/form-data")
        assert r.status_code == 200, nombre
    with app.app_context():
        assert Diseno.query.filter_by(nombre="Polo Nuevo").count() == 0
    assert not os.path.isdir(os.path.join(app.config["UPLOAD_FOLDER"], "disenos")) or \
        not os.listdir(os.path.join(app.config["UPLOAD_FOLDER"], "disenos"))


def test_foto_de_insumo_y_quitarla(app, ids, entrar):
    c = entrar("gestor")
    base = {"nombre": "Popelina", "categoria": "Tela", "unidad_medida": "Metros", "tipo": "Textil",
            "codigo_pantone": "P 100 C", "color_hex": "#111111", "stock_minimo": "50",
            "costo_unitario": "2.50", "proveedor_id": str(ids.proveedor)}
    c.post(f"/telas/{ids.popelina}/editar", data=dict(base, imagen=(io.BytesIO(JPG), "muestra.jpeg")),
           content_type="multipart/form-data")
    with app.app_context():
        ruta = db.session.get(Insumo, ids.popelina).imagen
        assert ruta.startswith("uploads/insumos/") and ruta.endswith(".jpg")
    archivo = os.path.join(app.config["UPLOAD_FOLDER"], ruta[len("uploads/"):])
    assert os.path.isfile(archivo)

    c.post(f"/telas/{ids.popelina}/editar", data=dict(base, quitar_imagen="y"))
    with app.app_context():
        assert db.session.get(Insumo, ids.popelina).imagen is None
    assert not os.path.exists(archivo)


def test_eliminar_imagen_no_toca_archivos_del_proyecto(app, tmp_path):
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("no borrar")
    with app.app_context():
        eliminar_imagen("img/logo.png")
        eliminar_imagen("uploads/../secreto.txt")
    assert secreto.exists()
    assert os.path.exists(os.path.join(app.static_folder, "img", "logo.png"))


def test_costo_y_proveedor_del_insumo(app, ids, entrar):
    entrar("gestor").post("/telas/nueva", data={
        "nombre": "Lino Natural", "categoria": "Tela", "unidad_medida": "Metros", "tipo": "Lino",
        "codigo_pantone": "", "color_hex": "#C2B280", "stock_minimo": "40", "metros_iniciales": "60",
        "costo_unitario": "5.25", "proveedor_id": str(ids.proveedor)})
    with app.app_context():
        lino = Insumo.query.filter_by(nombre="Lino Natural").one()
        assert lino.costo_unitario == Decimal("5.25") and lino.proveedor_id == ids.proveedor
        assert lino.cantidad_disponible == Decimal("60")


def test_color_repetido_sigue_bloqueado(app, ids, entrar):
    r = entrar("gestor").post("/telas/nueva", data={
        "nombre": "Otra tela", "categoria": "Tela", "unidad_medida": "Metros", "tipo": "x",
        "codigo_pantone": "p  100 c", "color_hex": "#111111", "stock_minimo": "10", "costo_unitario": "1",
        "proveedor_id": "0"})
    texto = r.get_data(as_text=True)
    assert "ya está asignado" in texto and "ya pertenece" in texto


def test_pagina_de_costos(app, ids, entrar):
    html = entrar("ventas").get("/costos/").get_data(as_text=True)
    assert "Camisa Prueba" in html and "$6.13" in html and "38.7%" in html
    assert "ORD-T-001" in html and "$387.00" in html


def test_archivar_y_restaurar_diseno(app, ids, entrar):
    c = entrar("gestor")
    c.post(f"/catalogo/{ids.camisa}/archivar")
    assert "Camisa Prueba" not in c.get("/catalogo/").get_data(as_text=True)
    assert "Camisa Prueba" in c.get("/catalogo/?archivados=1").get_data(as_text=True)
    c.post(f"/catalogo/{ids.camisa}/archivar")
    assert "Camisa Prueba" in c.get("/catalogo/").get_data(as_text=True)
