from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app.decorators import roles_required
from app.asistente.motor import responder

asistente = Blueprint("asistente", __name__)


@asistente.route("/preguntar", methods=["POST"])
@login_required
@roles_required("admin", "gestor", "ventas", "cliente")
def preguntar():
    """Recibe {"mensaje": "..."} y responde con la gestión correspondiente.

    Protegido con CSRF (cabecera X-CSRFToken) por Flask-WTF.
    """
    datos = request.get_json(silent=True) or {}
    mensaje = str(datos.get("mensaje", ""))
    return jsonify(responder(mensaje, current_user))
