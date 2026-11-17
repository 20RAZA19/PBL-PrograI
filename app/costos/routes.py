from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required

from app.decorators import roles_required
from app.indicadores import MARGEN_MINIMO_PEDIDO, META_MARGEN
from app.models import Diseno, Pedido

costos = Blueprint("costos", __name__)


@costos.route("/")
@login_required
@roles_required("admin", "ventas")
def index():
    vista = request.args.get("vista", "activos")
    disenos = Diseno.query.filter(Diseno.archivado.is_(False)).order_by(Diseno.nombre).all()

    query = Pedido.query
    if vista == "activos":
        query = query.filter(Pedido.estado != "Entregado")
    pedidos = query.order_by(Pedido.creado_en.desc()).all()

    costeables = [p for p in pedidos if p.ganancia_estimada is not None]
    ingreso = sum((p.ingreso for p in costeables), Decimal("0"))
    ganancia = sum((p.ganancia_estimada for p in costeables), Decimal("0"))
    resumen = {
        "ingreso": ingreso,
        "costo": sum((p.costo_estimado for p in costeables), Decimal("0")),
        "ganancia": ganancia,
        "margen": round(float(ganancia / ingreso * 100), 1) if ingreso else None,
        "sin_costeo": len(pedidos) - len(costeables),
        "disenos_incompletos": sum(1 for d in disenos if not d.costeable),
    }
    return render_template("costos/index.html", disenos=disenos, pedidos=pedidos, resumen=resumen,
                           vista=vista, margen_minimo=MARGEN_MINIMO_PEDIDO, meta_margen=META_MARGEN[0])
