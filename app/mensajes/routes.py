"""Mensajería entre el cliente y el asistente de ventas.

* Cliente: abre conversaciones sobre lo que necesite, las guarda o las borra.
* Ventas y Admin: ven todas las conversaciones y responden.
* Gestor (taller) no participa.
"""
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField
from wtforms.validators import DataRequired, Length

from app.decorators import roles_required
from app.extensions import db
from app.mensajes.servicios import (MAX_TEXTO, conversaciones_de, dias_retencion, enviar, marcar_leidos,
                                    purgar_conversaciones)
from app.models import Conversacion, Mensaje
from app.utils import paginar

mensajes = Blueprint("mensajes", __name__)
PARTICIPANTES = ("admin", "ventas", "cliente")


class NuevaConversacionForm(FlaskForm):
    asunto = StringField("Asunto", validators=[DataRequired("Escribe de qué trata."), Length(max=120)])
    texto = TextAreaField("Mensaje", validators=[DataRequired("Escribe tu mensaje."), Length(max=MAX_TEXTO)])


class MensajeForm(FlaskForm):
    texto = TextAreaField("Mensaje", validators=[DataRequired("Escribe tu mensaje."), Length(max=MAX_TEXTO)])


class AccionForm(FlaskForm):
    pass


def _conversacion(conversacion_id):
    c = db.session.get(Conversacion, conversacion_id)
    if c is None or not c.puede_ver(current_user):
        abort(404)   # una empresa no debe saber siquiera que existe la conversación de otra
    return c


@mensajes.route("/")
@login_required
@roles_required(*PARTICIPANTES)
def lista():
    purgar_conversaciones()
    pagina = paginar(conversaciones_de(current_user), por_defecto=10, ordenes={
        "reciente": ("Más reciente", [Conversacion.ultima_actividad.desc()]),
        "antigua": ("Más antigua", [Conversacion.ultima_actividad]),
        "asunto": ("Asunto A→Z", [Conversacion.asunto]),
    })
    return render_template("mensajes/lista.html", conversaciones=pagina.items, pagina=pagina, dias=dias_retencion(),
                           accion_form=AccionForm())


@mensajes.route("/nueva", methods=["GET", "POST"])
@login_required
@roles_required("cliente")
def nueva():
    if not current_user.cliente_id:
        flash("Tu cuenta aún no está vinculada a una empresa.", "warn")
        return redirect(url_for("mensajes.lista"))
    form = NuevaConversacionForm()
    if form.validate_on_submit():
        c = Conversacion(asunto=form.asunto.data.strip(), cliente_id=current_user.cliente_id, creada_por=current_user)
        db.session.add(c)
        db.session.flush()
        enviar(c, current_user, form.texto.data)
        db.session.commit()
        flash("Mensaje enviado. El asistente de ventas te responderá aquí mismo.", "ok")
        return redirect(url_for("mensajes.detalle", conversacion_id=c.id))
    return render_template("mensajes/nueva.html", form=form)


@mensajes.route("/<int:conversacion_id>")
@login_required
@roles_required(*PARTICIPANTES)
def detalle(conversacion_id):
    c = _conversacion(conversacion_id)
    if marcar_leidos(c, current_user):
        db.session.commit()
    return render_template("mensajes/detalle.html", c=c, form=MensajeForm(), accion_form=AccionForm(),
                           dias=dias_retencion(), refresco=current_app.config.get("MENSAJES_REFRESCO_SEG", 8))


@mensajes.route("/<int:conversacion_id>/enviar", methods=["POST"])
@login_required
@roles_required(*PARTICIPANTES)
def enviar_mensaje(conversacion_id):
    c = _conversacion(conversacion_id)
    form = MensajeForm()
    if form.validate_on_submit():
        m = enviar(c, current_user, form.texto.data)
        db.session.commit()
        if request.accept_mimetypes.best == "application/json" or request.path.endswith(".json"):
            return jsonify(ok=True, mensaje=m.como_dict() if m else None)
    else:
        for e in form.texto.errors:
            flash(e, "danger")
    return redirect(url_for("mensajes.detalle", conversacion_id=c.id))


@mensajes.route("/<int:conversacion_id>/mensajes.json")
@login_required
@roles_required(*PARTICIPANTES)
def mensajes_json(conversacion_id):
    """Mensajes posteriores a `desde` (id). Marca como leídos los que llegan del otro lado."""
    c = _conversacion(conversacion_id)
    desde = request.args.get("desde", 0, type=int)
    nuevos = [m for m in c.mensajes if m.id > desde]
    if marcar_leidos(c, current_user):
        db.session.commit()
    return jsonify(mensajes=[m.como_dict() for m in nuevos], guardada=c.guardada,
                   ultimo=c.mensajes[-1].id if c.mensajes else desde)


@mensajes.route("/<int:conversacion_id>/guardar", methods=["POST"])
@login_required
@roles_required("cliente")
def guardar(conversacion_id):
    c = _conversacion(conversacion_id)
    if AccionForm().validate_on_submit():
        c.guardada = not c.guardada
        db.session.commit()
        flash("Conversación guardada: no se borrará sola." if c.guardada
              else f"La conversación se borrará {dias_retencion()} días después del último mensaje.", "info")
    return redirect(url_for("mensajes.detalle", conversacion_id=c.id))


@mensajes.route("/<int:conversacion_id>/eliminar", methods=["POST"])
@login_required
@roles_required("cliente")
def eliminar(conversacion_id):
    c = _conversacion(conversacion_id)
    if AccionForm().validate_on_submit():
        db.session.delete(c)
        db.session.commit()
        flash("Conversación eliminada.", "info")
    return redirect(url_for("mensajes.lista"))
