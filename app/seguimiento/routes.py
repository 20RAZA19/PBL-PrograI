"""Consulta pública del estado de los pedidos con el token de seguimiento.

El token es una llave de SOLO LECTURA: muestra el avance de los pedidos de la empresa
del cliente (sin precios) y no permite solicitar, cotizar ni cambiar nada.
"""
import hmac
from datetime import datetime, timedelta

from flask import Blueprint, current_app, render_template, request
from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Length, Regexp

from app.auditoria import registrar_accion
from app.extensions import db
from app.models import Auditoria, Pedido, Usuario, normalizar_token

seguimiento = Blueprint("seguimiento", __name__)

FALLO = "Consulta de seguimiento rechazada"
MAX_FALLOS_IP = 8          # intentos fallidos por IP…
VENTANA_MIN = 15           # …en esta ventana de minutos
MENSAJE_GENERICO = "Los datos no coinciden. Revisa tu token y los últimos 4 dígitos de tu teléfono."


class SeguimientoForm(FlaskForm):
    token = StringField("Token de seguimiento", validators=[DataRequired("Escribe tu token."), Length(max=30)])
    digitos = StringField("Últimos 4 dígitos de tu teléfono", validators=[
        DataRequired("Escribe los últimos 4 dígitos del teléfono registrado."),
        Regexp(r"^\d{4}$", message="Son exactamente 4 números."),
    ])


def _ip():
    return (request.remote_addr or "")[:45]


def _bloqueado():
    """Demasiados intentos fallidos desde la misma conexión: frena a quien prueba tokens al azar."""
    desde = datetime.now() - timedelta(minutes=VENTANA_MIN)
    fallos = Auditoria.query.filter(Auditoria.accion == "consulta", Auditoria.fecha >= desde,
                                    Auditoria.ip == _ip(),
                                    Auditoria.descripcion.startswith(FALLO, autoescape=True)).count()
    return fallos >= current_app.config.get("SEGUIMIENTO_MAX_FALLOS_IP", MAX_FALLOS_IP)


def verificar(token_texto, digitos):
    """Devuelve el usuario dueño del token si los 4 dígitos coinciden; si no, None.

    Siempre compara en tiempo constante y no distingue «token inexistente» de
    «dígitos incorrectos», para no dar pistas.
    """
    token = normalizar_token(token_texto)
    usuario = Usuario.query.filter_by(token_seguimiento=token).first() if token else None
    esperado = usuario.telefono_digitos[-4:] if usuario else ""
    coincide = hmac.compare_digest((esperado or "----").encode(), (digitos or "").encode())
    if not (usuario and coincide and len(esperado) == 4):
        return None
    if not (usuario.rol == "cliente" and usuario.activo and usuario.estado_permiso == "aprobado" and usuario.cliente_id):
        return None
    return usuario


def pedidos_del_token(usuario):
    """Pedidos de la empresa del usuario: primero los activos (por fecha de entrega) y luego los entregados."""
    pedidos = Pedido.query.filter_by(cliente_id=usuario.cliente_id).all()
    activos = sorted([p for p in pedidos if not p.entregado], key=lambda p: (p.fecha_limite, p.folio))
    entregados = sorted([p for p in pedidos if p.entregado], key=lambda p: p.creado_en or datetime.min, reverse=True)
    return activos, entregados[:20]


@seguimiento.route("/", methods=["GET", "POST"])
def consulta():
    form = SeguimientoForm()
    contexto = {"form": form, "usuario": None, "activos": [], "entregados": []}
    estado = 200
    if form.validate_on_submit():
        if _bloqueado():
            form.token.errors.append(f"Demasiados intentos. Espera {VENTANA_MIN} minutos e inténtalo de nuevo.")
            estado = 429
        else:
            usuario = verificar(form.token.data, form.digitos.data)
            if usuario is None:
                registrar_accion("consulta", "Seguimiento", FALLO)
                db.session.commit()
                form.token.errors.append(MENSAJE_GENERICO)
                estado = 403
            else:
                activos, entregados = pedidos_del_token(usuario)
                registrar_accion("consulta", "Seguimiento",
                                 f"Consulta de pedidos de «{usuario.cliente.nombre}» con token", usuario=usuario)
                db.session.commit()
                contexto.update(usuario=usuario, activos=activos, entregados=entregados)
    respuesta = current_app.make_response((render_template("seguimiento/consulta.html", **contexto), estado))
    respuesta.headers["Cache-Control"] = "no-store"   # datos del cliente: que el navegador no los guarde
    respuesta.headers["X-Robots-Tag"] = "noindex"
    return respuesta
