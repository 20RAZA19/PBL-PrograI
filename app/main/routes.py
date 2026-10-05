from flask import Blueprint, render_template, request
from sqlalchemy import or_

from app.models import Tela, Pedido, Diseno

main = Blueprint("main", __name__)


@main.route("/")
def dashboard():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "")

    # Tabla de telas, con búsqueda por nombre o código Pantone
    consulta = Tela.query.filter_by(activo=True)
    if q:
        patron = f"%{q}%"
        consulta = consulta.filter(
            or_(Tela.nombre.ilike(patron), Tela.codigo_pantone.ilike(patron))
        )
    telas = consulta.order_by(Tela.nombre).all()

    # El estado se calcula en Python, así que se filtra aquí
    if estado:
        telas = [t for t in telas if t.estado == estado]

    # Tarjetas de resumen (siempre sobre todas las telas, sin filtros)
    todas = Tela.query.filter_by(activo=True).all()
    resumen = {
        "metros_totales": sum((t.metros_disponibles for t in todas), 0),
        "telas_bajo_stock": sum(1 for t in todas if t.estado != "Disponible"),
        "pedidos_produccion": Pedido.query.filter_by(estado="En Producción").count(),
        "total_disenos": Diseno.query.count(),
    }

    # Ficha técnica: el pedido en producción con entrega más próxima
    pedido = (
        Pedido.query.filter_by(estado="En Producción")
        .order_by(Pedido.fecha_entrega)
        .first()
    )

    return render_template(
        "dashboard.html",
        telas=telas,
        resumen=resumen,
        pedido=pedido,
        q=q,
        estado=estado,
    )