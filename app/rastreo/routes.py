from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, current_app
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.models import Pedido, Cliente, Insumo, NOMBRES_FASES
from app.decorators import roles_required
from app.forms import RastreoForm, AsociarInsumoForm
from app.rastreo.servicios import registrar_evento, puede_ver_pedido, pedidos_visibles
from app.utils import paginar

rastreo = Blueprint("rastreo", __name__)


def _pedido_o_404(folio):
    pedido = Pedido.query.filter_by(folio=folio).first_or_404()
    if not puede_ver_pedido(pedido):
        abort(403)
    return pedido


def _serializar(pedido):
    return {
        "folio": pedido.folio,
        "estado": pedido.estado,
        "fase": pedido.fase_actual,
        "progreso": pedido.progreso,
        "ubicacion": pedido.ubicacion_actual,
        "lat": pedido.latitud,
        "lng": pedido.longitud,
        "cliente": pedido.cliente.nombre if pedido.cliente else "",
        "modelo": pedido.modelo_prenda,
        "url": url_for("rastreo.detalle", folio=pedido.folio),
        "eventos": len(pedido.eventos),
        "ultimo_evento_id": pedido.ultimo_evento.id if pedido.ultimo_evento else None,
        "ruta": [
            {"lat": e.latitud, "lng": e.longitud, "estado": e.estado,
             "ubicacion": e.ubicacion, "fecha": e.fecha.strftime("%d/%m/%Y %H:%M")}
            for e in pedido.eventos if e.tiene_coordenadas
        ],
    }


@rastreo.route("/")
@login_required
@roles_required("admin", "gestor", "ventas", "cliente")
def lista():
    q = request.args.get("q", "").strip()
    fase = request.args.get("fase", "")
    vista = request.args.get("vista", "activos")

    query = pedidos_visibles()
    if q:
        query = query.join(Cliente).filter(or_(
            Pedido.folio.ilike(f"%{q}%"),
            Pedido.modelo_prenda.ilike(f"%{q}%"),
            Cliente.nombre.ilike(f"%{q}%"),
        ))
    if fase in NOMBRES_FASES:
        query = query.filter(Pedido.estado == fase)
    elif vista == "activos":
        query = query.filter(Pedido.estado != "Entregado")

    pagina = paginar(query, por_defecto=10, ordenes={
        "entrega": ("Fecha de entrega", [Pedido.fecha_limite]),
        "reciente": ("Más reciente", [Pedido.creado_en.desc()]),
        "folio": ("Folio", [Pedido.folio]),
        "cliente": ("Cliente A→Z", [Cliente.nombre, Pedido.fecha_limite]),
    })
    pedidos = pagina.items
    marcadores = [_serializar(p) for p in pedidos if p.tiene_coordenadas]
    return render_template("rastreo/lista.html", pedidos=pedidos, pagina=pagina, q=q, fase=fase,
                           vista=vista, marcadores=marcadores)


@rastreo.route("/<folio>", methods=["GET", "POST"])
@login_required
@roles_required("admin", "gestor", "ventas", "cliente")
def detalle(folio):
    pedido = _pedido_o_404(folio)

    form = None
    insumo_form = None
    if current_user.puede_mover_pedidos:
        form = RastreoForm(obj=pedido)
        if request.method == "GET":
            form.nota.data = ""
        # Formulario de consumo de material: se envía a main.descontar_insumo
        insumo_form = AsociarInsumoForm(formdata=None)
        insumo_form.insumo_id.choices = [
            (i.id, f"{i.nombre} ({float(i.cantidad_disponible or 0):,.2f} {i.unidad_medida})")
            for i in Insumo.query.filter(Insumo.activo.is_(True)).order_by(Insumo.nombre).all()
        ]

        if request.method == "POST" and form.validate_on_submit():
            registrar_evento(
                pedido,
                estado=form.estado.data,
                ubicacion=form.ubicacion_actual.data.strip(),
                latitud=form.latitud.data,
                longitud=form.longitud.data,
                nota=(form.nota.data or "").strip() or None,
                usuario=current_user,
            )
            db.session.commit()
            flash("Rastreo actualizado. El cliente ya puede ver el cambio.", "ok")
            return redirect(url_for("rastreo.detalle", folio=pedido.folio))
    elif request.method == "POST":
        abort(403)

    eventos = list(reversed(pedido.eventos))
    return render_template(
        "rastreo/detalle.html", pedido=pedido, eventos=eventos, form=form,
        insumo_form=insumo_form, datos=_serializar(pedido),
        refresco=current_app.config["RASTREO_REFRESCO_SEG"],
    )


@rastreo.route("/<folio>/estado.json")
@login_required
@roles_required("admin", "gestor", "ventas", "cliente")
def estado_json(folio):
    pedido = Pedido.query.filter_by(folio=folio).first()
    if pedido is None:
        return jsonify(error="No encontrado"), 404
    if not puede_ver_pedido(pedido):
        return jsonify(error="No autorizado"), 403
    return jsonify(_serializar(pedido))


@rastreo.route("/<folio>/ficha")
@login_required
@roles_required("admin", "gestor", "ventas", "cliente")
def ficha(folio):
    """Ficha resumen de la orden de confección, lista para imprimir o guardar como PDF."""
    pedido = _pedido_o_404(folio)
    consumo = []
    if pedido.diseno:
        for dt in pedido.diseno.telas:
            consumo.append({
                "tela": dt.tela,
                "por_unidad": float(dt.metros_por_unidad or 0),
                "total": float(dt.metros_por_unidad or 0) * pedido.cantidad,
            })
    return render_template("rastreo/ficha.html", pedido=pedido, consumo=consumo,
                           eventos=list(reversed(pedido.eventos)))
