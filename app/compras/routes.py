from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.compras.servicios import analizar_insumos, crear_orden, recibir_orden, sugerencias_por_proveedor
from app.decorators import roles_required
from app.documentos import documento_orden_compra, respuesta_documento
from app.extensions import db
from app.forms import AccionForm
from app.models import ESTADOS_ORDEN_COMPRA, Insumo, OrdenCompra, Proveedor

compras = Blueprint("compras", __name__)


def _decimal(valor):
    try:
        numero = Decimal(str(valor).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None
    return numero if numero >= 0 else None


@compras.route("/")
@login_required
@roles_required("admin", "gestor")
def index():
    grupos = sugerencias_por_proveedor()
    cubiertos = [f for f in analizar_insumos() if f["cubierto"]]
    pendientes = (OrdenCompra.query.filter(OrdenCompra.estado.in_(("borrador", "enviada")))
                  .order_by(OrdenCompra.fecha.desc()).all())
    return render_template("compras/index.html", grupos=grupos, cubiertos=cubiertos,
                           pendientes=pendientes, accion_form=AccionForm(),
                           fecha_sugerida=date.today() + timedelta(days=5))


@compras.route("/generar", methods=["POST"])
@login_required
@roles_required("admin", "gestor")
def generar():
    form = AccionForm()
    if not form.validate_on_submit():
        abort(400)
    proveedor_id = request.form.get("proveedor_id", type=int)
    proveedor = db.session.get(Proveedor, proveedor_id) if proveedor_id else None

    items = []
    for clave, valor in request.form.items():
        if not clave.startswith("cantidad_"):
            continue
        insumo = db.session.get(Insumo, int(clave.split("_", 1)[1]))
        cantidad = _decimal(valor)
        if insumo and cantidad and cantidad > 0:
            items.append((insumo, cantidad))
    if not items:
        flash("Indica al menos una cantidad mayor a cero.", "warn")
        return redirect(url_for("compras.index"))

    fecha = request.form.get("fecha_esperada")
    try:
        fecha_esperada = date.fromisoformat(fecha) if fecha else None
    except ValueError:
        fecha_esperada = None

    orden = crear_orden(proveedor, items, current_user, fecha_esperada=fecha_esperada,
                        notas=(request.form.get("notas") or "").strip() or None)
    db.session.commit()
    flash(f"Orden de compra {orden.folio} creada en borrador. Revísala y envíala al proveedor.", "ok")
    return redirect(url_for("compras.detalle", orden_id=orden.id))


@compras.route("/ordenes")
@login_required
@roles_required("admin", "gestor")
def ordenes():
    estado = request.args.get("estado", "")
    query = OrdenCompra.query
    if estado in ESTADOS_ORDEN_COMPRA:
        query = query.filter_by(estado=estado)
    lista = query.order_by(OrdenCompra.fecha.desc()).all()
    return render_template("compras/ordenes.html", ordenes=lista, estado=estado, estados=ESTADOS_ORDEN_COMPRA)


@compras.route("/ordenes/<int:orden_id>", methods=["GET", "POST"])
@login_required
@roles_required("admin", "gestor")
def detalle(orden_id):
    orden = db.get_or_404(OrdenCompra, orden_id)
    if request.method == "POST":
        # Ajuste de cantidades / costos mientras la orden está en borrador
        form = AccionForm()
        if not form.validate_on_submit() or orden.estado != "borrador":
            abort(400)
        for linea in list(orden.lineas):
            cantidad = _decimal(request.form.get(f"cantidad_{linea.id}"))
            costo = _decimal(request.form.get(f"costo_{linea.id}"))
            if cantidad is not None:
                if cantidad == 0:
                    orden.lineas.remove(linea)
                    continue
                linea.cantidad = cantidad
            if costo is not None:
                linea.costo_unitario = costo
        fecha = request.form.get("fecha_esperada")
        if fecha:
            try:
                orden.fecha_esperada = date.fromisoformat(fecha)
            except ValueError:
                pass
        orden.notas = (request.form.get("notas") or "").strip() or None
        if not orden.lineas:
            db.session.delete(orden)
            db.session.commit()
            flash("La orden quedó sin líneas y se eliminó.", "info")
            return redirect(url_for("compras.index"))
        db.session.commit()
        flash("Orden actualizada.", "ok")
        return redirect(url_for("compras.detalle", orden_id=orden.id))
    return render_template("compras/detalle.html", orden=orden, accion_form=AccionForm())


@compras.route("/ordenes/<int:orden_id>/<accion>", methods=["POST"])
@login_required
@roles_required("admin", "gestor")
def cambiar_estado(orden_id, accion):
    orden = db.get_or_404(OrdenCompra, orden_id)
    form = AccionForm()
    if not form.validate_on_submit():
        abort(400)

    if accion == "enviar" and orden.estado == "borrador":
        orden.estado = "enviada"
        flash(f"{orden.folio} marcada como enviada. Descarga el PDF para mandarlo al proveedor.", "ok")
    elif accion == "recibir" and orden.estado in ("borrador", "enviada"):
        recibir_orden(orden, current_user)
        flash(f"Mercadería de {orden.folio} ingresada al inventario.", "ok")
    elif accion == "cancelar" and orden.estado in ("borrador", "enviada"):
        orden.estado = "cancelada"
        flash(f"{orden.folio} cancelada.", "info")
    else:
        flash("Esa acción no aplica al estado actual de la orden.", "warn")
        return redirect(url_for("compras.detalle", orden_id=orden.id))
    db.session.commit()
    return redirect(url_for("compras.detalle", orden_id=orden.id))


@compras.route("/ordenes/<int:orden_id>/pdf")
@login_required
@roles_required("admin", "gestor")
def pdf(orden_id):
    orden = db.get_or_404(OrdenCompra, orden_id)
    return respuesta_documento(documento_orden_compra(orden), descargar=request.args.get("descargar") == "1")
