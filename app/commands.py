from datetime import date

import click
from flask.cli import with_appcontext

from app.extensions import db
from app.models import Usuario, Tela, Cliente, Diseno, DisenoTela, Pedido


@click.command("seed")
@with_appcontext
def seed():
    """Carga datos de ejemplo para desarrollo."""
    if Tela.query.first():
        click.echo("La base ya tiene datos. No se cargó nada.")
        return

    admin = Usuario(
        nombre="Carlos M.",
        email="admin@arteycolor.com",
        cargo="Jefe de Producción",
        rol="admin",
    )
    admin.set_password("admin123")

    algodon = Tela(nombre="Algodón Pima Verde Gras", codigo_pantone="Pantone 348 C",
                   color_hex="#00843D", metros_disponibles=320)
    poliester_azul = Tela(nombre="Poliéster Secado Rápido Azul", codigo_pantone="Pantone 2925 C",
                          color_hex="#0085CA", metros_disponibles=85)
    oxford = Tela(nombre="Oxford Blanco Premium", codigo_pantone="Pantone White C",
                  color_hex="#F4F5F7", metros_disponibles=540)
    gabardina = Tela(nombre="Gabardina Roja Institucional", codigo_pantone="Pantone 186 C",
                     color_hex="#C8102E", metros_disponibles=190)
    drifit = Tela(nombre="Dri-Fit Marino Deportivo", codigo_pantone="Pantone 289 C",
                  color_hex="#0C2340", metros_disponibles=42)
    cuello = Tela(nombre="Poliéster Cuello Blanco", codigo_pantone="Pantone White C",
                  color_hex="#FFFFFF", metros_disponibles=150)

    cliente = Cliente(nombre="Banco Nacional de México")

    polo = Diseno(
        nombre="Polo Corporativa Banco Nacional 2025",
        tipo_prenda="Polo manga corta, corte slim",
        tallas="S, M, L, XL, XXL",
        imagen="img/disenos/polo-corporativa.png",
        cliente=cliente,
    )
    polo.telas.append(DisenoTela(tela=algodon, metros_por_unidad=1.2))
    polo.telas.append(DisenoTela(tela=cuello, metros_por_unidad=0.3))

    pedido = Pedido(
        diseno=polo,
        cliente=cliente,
        cantidad=500,
        estado="En Producción",
        fecha_entrega=date(2026, 11, 15),
    )

    db.session.add_all([admin, algodon, poliester_azul, oxford, gabardina,
                        drifit, cuello, cliente, polo, pedido])
    db.session.commit()
    click.echo("Datos de ejemplo cargados.")