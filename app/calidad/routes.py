from collections import Counter
from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.calidad.forms import RegistroCalidadForm, ResolverForm
from app.decorators import roles_required
from app.extensions import db
from app.indicadores import tasas_por_linea
from app.models import META_DEFECTOS_PCT, Pedido, RegistroCalidad
from app.notificaciones.servicios import notificar, usuarios_con_rol
from app.utils import paginar, volver_a

calidad = Blueprint("calidad", __name__)


@calidad.route("/")
@login_required
@roles_required("admin", "gestor", "ventas")
def index():
    dias = request.args.get("dias", 90, type=int)
    if dias not in (30, 90, 365):
        dias = 90
    estado = request.args.get("estado", "")
    linea = request.args.get("linea", "")

    desde = datetime.now() - timedelta(days=dias)
    query = RegistroCalidad.query.filter(RegistroCalidad.fecha >= desde)
    if estado == "abiertos":
        query = RegistroCalidad.query.filter_by(resuelto=False)  # los abiertos se ven sin importar la fecha
    if linea:
        query = query.filter(RegistroCalidad.linea == linea)
    pagina = paginar(query.order_by(RegistroCalidad.resuelto, RegistroCalidad.fecha.desc()))
    registros = pagina.items

    # Totales del periodo con SUM/GROUP BY: no hace falta traer cada registro
    en_periodo = RegistroCalidad.fecha >= desde
    por_categoria = Counter(dict(
        db.session.query(RegistroCalidad.categoria, db.func.sum(RegistroCalidad.cantidad))
        .filter(en_periodo).group_by(RegistroCalidad.categoria).all()))
    afectadas = db.session.query(db.func.coalesce(db.func.sum(RegistroCalidad.cantidad), 0)).filter(en_periodo).scalar()
    reprocesos = (db.session.query(db.func.coalesce(db.func.sum(RegistroCalidad.cantidad), 0))
                  .filter(en_periodo, RegistroCalidad.tipo == "reproceso").scalar())
    lineas = tasas_por_linea(dias)
    producidas = max((l["producidas"] for l in lineas), default=0)
    resumen = {
        "afectadas": int(afectadas or 0),
        "reprocesos": int(reprocesos or 0),
        "abiertos": RegistroCalidad.query.filter_by(resuelto=False).count(),
        "peor": max((l for l in lineas if l["tasa"] is not None), key=lambda l: l["tasa"], default=None),
        "producidas": producidas,
    }
    return render_template("calidad/index.html", registros=registros, pagina=pagina, lineas=lineas, resumen=resumen,
                           por_categoria=por_categoria.most_common(), dias=dias, estado=estado,
                           linea=linea, meta=META_DEFECTOS_PCT, resolver_form=ResolverForm())


@calidad.route("/nuevo", methods=["GET", "POST"])
@login_required
@roles_required("admin", "gestor")
def nuevo():
    form = RegistroCalidadForm()
    pedidos = (Pedido.query.filter(Pedido.estado.in_(("En Corte", "En Costura", "Terminado", "En Ruta", "Entregado")))
               .order_by(Pedido.creado_en.desc()).limit(200).all())
    form.pedido_id.choices = [(p.id, f"{p.folio} · {p.modelo_prenda} · {p.cliente.nombre} ({p.estado})") for p in pedidos]
    if request.method == "GET":
        pedido_id = request.args.get("pedido_id", type=int)
        if pedido_id:
            form.pedido_id.data = pedido_id
            pedido = db.session.get(Pedido, pedido_id)
            # Sugerir la línea según la fase en la que está el pedido
            if pedido:
                form.linea.data = {"En Corte": "Corte", "En Costura": "Costura"}.get(pedido.estado, "Acabados y Empaque")

    if not form.pedido_id.choices:
        flash("Aún no hay pedidos que hayan pasado por producción.", "info")
        return redirect(url_for("calidad.index"))

    if form.validate_on_submit():
        pedido = db.session.get(Pedido, form.pedido_id.data)
        registro = RegistroCalidad(
            pedido=pedido, linea=form.linea.data, tipo=form.tipo.data, categoria=form.categoria.data,
            cantidad=form.cantidad.data, descripcion=(form.descripcion.data or "").strip() or None,
            accion_correctiva=(form.accion_correctiva.data or "").strip() or None, usuario=current_user,
        )
        db.session.add(registro)
        db.session.flush()
        notificar([u for u in usuarios_con_rol("admin", "gestor") if u.id != current_user.id], "calidad",
                  f"{registro.tipo_legible} en {pedido.folio}: {registro.categoria}",
                  mensaje=f"{registro.cantidad} prenda(s) · línea de {registro.linea} · registrado por {current_user.nombre}",
                  url=url_for("calidad.index", estado="abiertos"), nivel="warn", clave=f"calidad-{registro.id}")
        db.session.commit()
        flash(f"Registro de calidad guardado para {pedido.folio}.", "ok")
        return redirect(volver_a(url_for("calidad.index")))
    return render_template("calidad/form.html", form=form)


@calidad.route("/<int:registro_id>/resolver", methods=["POST"])
@login_required
@roles_required("admin", "gestor")
def resolver(registro_id):
    registro = db.get_or_404(RegistroCalidad, registro_id)
    form = ResolverForm()
    if not form.validate_on_submit():
        abort(400)
    if form.accion_correctiva.data and form.accion_correctiva.data.strip():
        registro.accion_correctiva = form.accion_correctiva.data.strip()
    registro.resuelto = True
    registro.resuelto_en = datetime.now()
    db.session.commit()
    flash("Caso de calidad marcado como resuelto.", "ok")
    return redirect(volver_a(url_for("calidad.index")))
