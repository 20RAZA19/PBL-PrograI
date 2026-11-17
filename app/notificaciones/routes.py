from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.forms import AccionForm
from app.models import Notificacion
from app.notificaciones.servicios import sincronizar
from app.utils import destino_seguro

notificaciones = Blueprint("notificaciones", __name__)


def _propia(notificacion_id):
    n = db.get_or_404(Notificacion, notificacion_id)
    if n.usuario_id != current_user.id:
        abort(404)
    return n


@notificaciones.route("/")
@login_required
def lista():
    sincronizar(current_user)
    filtro = request.args.get("filtro", "todas")
    query = Notificacion.query.filter_by(usuario_id=current_user.id)
    if filtro == "no-leidas":
        query = query.filter_by(leida=False)
    avisos = query.order_by(Notificacion.leida, Notificacion.creada_en.desc()).all()
    return render_template("notificaciones/lista.html", avisos=avisos, filtro=filtro, accion_form=AccionForm())


@notificaciones.route("/<int:notificacion_id>/ir")
@login_required
def ir(notificacion_id):
    """Marca el aviso como leído y lleva a la pantalla relacionada."""
    n = _propia(notificacion_id)
    if not n.leida:
        n.leida = True
        db.session.commit()
    return redirect(destino_seguro(n.url, url_for("notificaciones.lista")))


@notificaciones.route("/<int:notificacion_id>/leer", methods=["POST"])
@login_required
def leer(notificacion_id):
    if not AccionForm().validate_on_submit():
        abort(400)
    n = _propia(notificacion_id)
    n.leida = True
    db.session.commit()
    return redirect(url_for("notificaciones.lista", filtro=request.args.get("filtro")))


@notificaciones.route("/leer-todas", methods=["POST"])
@login_required
def leer_todas():
    if not AccionForm().validate_on_submit():
        abort(400)
    Notificacion.query.filter_by(usuario_id=current_user.id, leida=False).update({"leida": True})
    db.session.commit()
    return redirect(destino_seguro(request.form.get("volver"), url_for("notificaciones.lista")))
