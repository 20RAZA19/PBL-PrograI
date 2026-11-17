"""Configuración compartida de las pruebas automáticas.

Cada prueba recibe una aplicación nueva con una base de datos SQLite en
memoria y un conjunto pequeño de datos conocidos, así los resultados
esperados se pueden calcular a mano:

    Diseño «Camisa Prueba» (precio $10.00, mano de obra $2.00)
        Popelina    1.5 m  × $2.50 = $3.75
        Hilo        0.02   × $4.00 = $0.08
        Botón       6      × $0.05 = $0.30
        ---------------------------------
        Materiales               $4.13
        Costo por prenda         $6.13   → ganancia $3.87 (38.7 %)

    Pedido ORD-T-001: 100 camisas, «En Corte», vence en 2 días
        → necesita 150 m de Popelina y solo hay 100 (faltan 50)
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import create_app
from app.extensions import db
from app.models import (Cliente, Diseno, DisenoTela, EventoRastreo, Insumo, Pedido, Proveedor, Usuario)
from config import Config

CLAVE = "clave123"


class ConfigPrueba(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SECRET_KEY = "pruebas"
    AVISOS_REFRESCO_SEG = 0  # sincroniza las notificaciones en cada página


def _usuario(email, rol, nombre, cliente=None, estado="aprobado"):
    u = Usuario(email=email, rol=rol, nombre=nombre, cliente=cliente, estado_permiso=estado)
    u.set_password(CLAVE)
    db.session.add(u)
    return u


def poblar():
    hoy = date.today()
    colegio = Cliente(nombre="Colegio Prueba", contacto="Ana Pérez", email="compras@colegio.test")
    ajena = Cliente(nombre="Empresa Ajena")
    proveedor = Proveedor(nombre="Telas Prueba", rubro="Telas")
    db.session.add_all([colegio, ajena, proveedor])

    usuarios = {
        "admin": _usuario("admin@test.com", "admin", "Ada Admin"),
        "gestor": _usuario("gestor@test.com", "gestor", "Gael Gestor"),
        "ventas": _usuario("ventas@test.com", "ventas", "Vera Ventas"),
        "cliente": _usuario("cliente@test.com", "cliente", "Carla Cliente", cliente=colegio),
        "cliente_b": _usuario("otro@test.com", "cliente", "Otto Otro", cliente=ajena),
        "pendiente": _usuario("pendiente@test.com", "gestor", "Pedro Pendiente", estado="pendiente"),
    }

    popelina = Insumo(nombre="Popelina", codigo="TEL-0001", categoria="Tela", unidad_medida="Metros",
                      cantidad_disponible=100, stock_minimo=50, costo_unitario=Decimal("2.50"),
                      color_hex="#111111", codigo_pantone="P 100 C", proveedor=proveedor)
    hilo = Insumo(nombre="Hilo Blanco", codigo="HIL-0002", categoria="Hilo", unidad_medida="Conos",
                  cantidad_disponible=30, stock_minimo=10, costo_unitario=Decimal("4.00"), color_hex="#FFFFFF")
    boton = Insumo(nombre="Botón", codigo="BOT-0003", categoria="Botón", unidad_medida="Unidades",
                   cantidad_disponible=1000, stock_minimo=200, costo_unitario=Decimal("0.05"), color_hex="#EEEEEE")
    gabardina = Insumo(nombre="Gabardina", codigo="TEL-0004", categoria="Tela", unidad_medida="Metros",
                       cantidad_disponible=20, stock_minimo=100, costo_unitario=Decimal("3.00"),
                       color_hex="#222222", proveedor=proveedor)
    db.session.add_all([popelina, hilo, boton, gabardina])

    camisa = Diseno(nombre="Camisa Prueba", cliente=colegio, tallas="S, M, L",
                    precio_venta=Decimal("10.00"), costo_mano_obra=Decimal("2.00"))
    db.session.add(camisa)
    camisa.telas.append(DisenoTela(tela=popelina, metros_por_unidad=Decimal("1.5")))
    camisa.telas.append(DisenoTela(tela=hilo, metros_por_unidad=Decimal("0.02")))
    camisa.telas.append(DisenoTela(tela=boton, metros_por_unidad=Decimal("6")))

    activo = Pedido(folio="ORD-T-001", modelo_prenda="Camisa Prueba", cantidad=100, cliente=colegio,
                    diseno=camisa, fecha_limite=hoy + timedelta(days=2))
    activo.cambiar_estado("En Corte")
    entregado = Pedido(folio="ORD-T-002", modelo_prenda="Gabacha", cantidad=50, cliente=ajena,
                       fecha_limite=hoy - timedelta(days=1), precio_unitario=Decimal("8.00"))
    entregado.cambiar_estado("Entregado")
    db.session.add_all([activo, entregado])
    db.session.add(EventoRastreo(pedido=activo, estado="Recibido", fase=1, fecha=datetime.now() - timedelta(days=1)))
    db.session.add(EventoRastreo(pedido=activo, estado="En Corte", fase=2, fecha=datetime.now()))
    db.session.add(EventoRastreo(pedido=entregado, estado="Entregado", fase=6,
                                 fecha=datetime.now() - timedelta(days=2)))
    db.session.commit()

    return SimpleNamespace(
        usuarios={rol: u.id for rol, u in usuarios.items()},
        colegio=colegio.id, ajena=ajena.id, proveedor=proveedor.id,
        popelina=popelina.id, hilo=hilo.id, boton=boton.id, gabardina=gabardina.id,
        camisa=camisa.id, activo=activo.id, entregado=entregado.id,
    )


@pytest.fixture
def app(tmp_path):
    aplicacion = create_app(ConfigPrueba)
    aplicacion.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")

    @aplicacion.teardown_request
    def _olvidar_usuario(_error):
        # Flask-Login guarda al usuario en `g`. Las pruebas que mantienen un contexto abierto (fixture
        # `ctx`) y usan dos sesiones HTTP compartirían ese usuario; en producción cada petición tiene su `g`.
        from flask import g
        g.pop("_login_user", None)
    with aplicacion.app_context():
        db.create_all()
        aplicacion.ids = poblar()
    yield aplicacion
    with aplicacion.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def ids(app):
    return app.ids


@pytest.fixture
def ctx(app):
    """Contexto de aplicación para consultar la base de datos desde la prueba."""
    with app.app_context():
        yield


EMAILS = {"admin": "admin@test.com", "gestor": "gestor@test.com", "ventas": "ventas@test.com",
          "cliente": "cliente@test.com", "cliente_b": "otro@test.com"}


@pytest.fixture
def entrar(app):
    """entrar("ventas") → cliente HTTP con la sesión iniciada en ese rol."""
    def _entrar(rol):
        c = app.test_client()
        r = c.post("/auth/login", data={"email": EMAILS[rol], "password": CLAVE})
        assert r.status_code == 302, f"No se pudo iniciar sesión como {rol}"
        return c
    return _entrar
