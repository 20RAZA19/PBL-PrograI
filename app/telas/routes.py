from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from sqlalchemy import or_

from app.extensions import db
from app.models import Tela, Movimiento, Usuario
from app.telas.forms import TelaForm, NuevaTelaForm, MovimientoForm

telas = Blueprint("telas", __name__)


def usuario_actual():
    """TEMPORAL: mientras no exista el inicio de sesión,
    los movimientos se registran a nombre del primer administrador."""
    if current_user.is_authenticated:
        return current_user
    return Usuario.query.filter_by(rol="admin").first()


def aplicar_formulario(tela, form):
    tela.nombre = form.nombre.data.strip()
    tela.tipo = (form.tipo.data or "").strip() or "Textil Premium"
    tela.codigo_pantone = (form.codigo_pantone.data or "").strip() or None
    tela.color_hex = form.color_hex.data.upper()
    tela.stock_minimo = form.stock_minimo.data


@telas.route("/")
def lista():
    q = request.args.get("q", "").strip()
    estado = request.args.get("estado", "")

    consulta = Tela.query.filter_by(activo=True)
    if q:
        patron = f"%{q}%"
        consulta = consulta.filter(
            or_(Tela.nombre.ilike(patron), Tela.codigo_pantone.ilike(patron))
        )
    resultado = consulta.order_by(Tela.nombre).all()
    if estado:
        resultado = [t for t in resultado if t.estado == estado]

    return render_template("telas/lista.html", telas=resultado, q=q, estado=estado)


@telas.route("/<int:tela_id>")
def detalle(tela_id):
    tela = db.get_or_404(Tela, tela_id)
    movimientos = (
        Movimiento.query.filter_by(tela_id=tela.id)
        .order_by(Movimiento.fecha.desc())
        .all()
    )
    return render_template("telas/detalle.html", tela=tela, movimientos=movimientos)


@telas.route("/nueva", methods=["GET", "POST"])
def nueva():
    form = NuevaTelaForm()
    volver = url_for("telas.lista")

    if form.validate_on_submit():
        metros = form.metros_iniciales.data or 0
        usuario = usuario_actual()
        if metros > 0 and usuario is None:
            flash("No hay usuarios registrados. Ejecuta 'flask seed' primero.", "danger")
            return render_template("telas/form.html", form=form, titulo="Nueva Tela", volver=volver)

        tela = Tela(metros_disponibles=metros)
        aplicar_formulario(tela, form)
        db.session.add(tela)

        if metros > 0:
            db.session.add(Movimiento(
                tela=tela, usuario=usuario, tipo="entrada",
                metros=metros, motivo="Inventario inicial",
            ))

        db.session.commit()
        flash(f"Tela «{tela.nombre}» registrada correctamente.", "ok")
        return redirect(url_for("telas.detalle", tela_id=tela.id))

    return render_template("telas/form.html", form=form, titulo="Nueva Tela", volver=volver)


@telas.route("/<int:tela_id>/editar", methods=["GET", "POST"])
def editar(tela_id):
    tela = db.get_or_404(Tela, tela_id)
    form = TelaForm(obj=tela)
    volver = url_for("telas.detalle", tela_id=tela.id)

    if form.validate_on_submit():
        aplicar_formulario(tela, form)
        db.session.commit()
        flash("Cambios guardados.", "ok")
        return redirect(volver)

    return render_template("telas/form.html", form=form,
                           titulo=f"Editar: {tela.nombre}", volver=volver)


@telas.route("/<int:tela_id>/desactivar", methods=["POST"])
def desactivar(tela_id):
    tela = db.get_or_404(Tela, tela_id)
    tela.activo = False
    db.session.commit()
    flash(f"La tela «{tela.nombre}» fue desactivada.", "ok")
    return redirect(url_for("telas.lista"))


@telas.route("/movimiento", methods=["GET", "POST"])
def movimiento():
    form = MovimientoForm()
    activas = Tela.query.filter_by(activo=True).order_by(Tela.nombre).all()
    form.tela_id.choices = [
        (t.id, f"{t.nombre} — {t.metros_disponibles:,.2f} mts") for t in activas
    ]

    # Preseleccionar tela y tipo si vienen en la URL (desde el menú de la tabla)
    if request.method == "GET":
        tela_id = request.args.get("tela_id", type=int)
        if tela_id:
            form.tela_id.data = tela_id
        if request.args.get("tipo") in ("entrada", "salida"):
            form.tipo.data = request.args["tipo"]

    if form.validate_on_submit():
        usuario = usuario_actual()
        if usuario is None:
            flash("No hay usuarios registrados. Ejecuta 'flask seed' primero.", "danger")
            return render_template("telas/movimiento.html", form=form)

        tela = db.get_or_404(Tela, form.tela_id.data)
        metros = form.metros.data

        if form.tipo.data == "salida":
            if metros > tela.metros_disponibles:
                form.metros.errors.append(
                    f"Solo hay {tela.metros_disponibles:,.2f} mts disponibles."
                )
                return render_template("telas/movimiento.html", form=form)
            tela.metros_disponibles -= metros
        else:
            tela.metros_disponibles += metros

        db.session.add(Movimiento(
            tela=tela, usuario=usuario, tipo=form.tipo.data,
            metros=metros, motivo=(form.motivo.data or "").strip() or None,
        ))
        db.session.commit()

        accion = "Entrada" if form.tipo.data == "entrada" else "Salida"
        flash(f"{accion} de {metros:,.2f} mts registrada en «{tela.nombre}».", "ok")
        return redirect(url_for("telas.detalle", tela_id=tela.id))

    return render_template("telas/movimiento.html", form=form)