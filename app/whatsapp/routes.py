"""Webhook de Twilio y simulador interno del bot de WhatsApp."""
from flask import Blueprint, Response, abort, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import login_required
from flask_wtf import FlaskForm
from wtforms import StringField
from wtforms.validators import DataRequired, Length

from app.decorators import roles_required
from app.extensions import csrf, db
from app.whatsapp.bot import procesar
from app.whatsapp.twilio import configurado, firma_valida, twiml

whatsapp = Blueprint("whatsapp", __name__)


@whatsapp.route("/webhook", methods=["POST"])
@csrf.exempt  # lo llama Twilio, no un formulario del sitio; la firma HMAC es la protección
def webhook():
    token = current_app.config.get("TWILIO_AUTH_TOKEN")
    if not token:
        abort(503)  # bot apagado: falta configurar Twilio
    if not firma_valida(request.url, request.form.to_dict(), request.headers.get("X-Twilio-Signature", ""), token):
        abort(403)
    respuesta, _ = procesar(request.form.get("From", ""), request.form.get("Body", ""))
    db.session.commit()
    return Response(twiml(respuesta), mimetype="text/xml")


class SimuladorForm(FlaskForm):
    telefono = StringField("Número que escribe", validators=[DataRequired("Escribe un número."), Length(max=25)])
    mensaje = StringField("Mensaje", validators=[DataRequired("Escribe el mensaje."), Length(max=300)])


@whatsapp.route("/simulador", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def simulador():
    """Prueba el bot sin WhatsApp real: misma lógica, misma bitácora."""
    form = SimuladorForm()
    charla = session.get("wa_simulador", [])
    if form.validate_on_submit():
        respuesta, _ = procesar(form.telefono.data, form.mensaje.data)
        db.session.commit()
        charla = (charla + [{"de": "cliente", "texto": form.mensaje.data},
                            {"de": "bot", "texto": respuesta}])[-20:]
        session["wa_simulador"] = charla
        session["wa_telefono"] = form.telefono.data
        return redirect(url_for("whatsapp.simulador"))
    if request.method == "GET" and not form.telefono.data:
        form.telefono.data = session.get("wa_telefono", "")
    return render_template("whatsapp/simulador.html", form=form, charla=charla, twilio_listo=configurado(),
                           url_webhook=url_for("whatsapp.webhook", _external=True))


@whatsapp.route("/simulador/limpiar", methods=["POST"])
@login_required
@roles_required("admin")
def simulador_limpiar():
    session.pop("wa_simulador", None)
    flash("Conversación del simulador reiniciada.", "info")
    return redirect(url_for("whatsapp.simulador"))


@whatsapp.route("/guia")
@login_required
@roles_required("cliente")
def guia():
    """Cómo pedir datos al bot, paso a paso. Al cliente le muestra su propia situación
    (si su número está listo) y la respuesta real que recibiría a ESTADO."""
    from flask_login import current_user
    from app.models import usuario_con_telefono
    from app.whatsapp.bot import _estado, digitos, usuario_por_telefono

    numero = digitos(current_app.config.get("TWILIO_WHATSAPP_FROM", ""))
    union = (current_app.config.get("WHATSAPP_CODIGO_UNION", "") or "").strip()
    # El código del sandbox lo asigna Twilio y siempre empieza con «join» (p. ej. «join thought-not»)
    if union and not union.lower().startswith("join "):
        union = "join " + union
    revision, vista_estado = None, None
    if current_user.rol == "cliente":
        tiene = len(current_user.telefono_digitos) >= 8
        revision = {
            "telefono": current_user.telefono,
            "tiene_telefono": tiene,
            "codigo_pais": current_user.telefono_digitos.startswith("503") or (current_user.telefono or "").strip().startswith("+"),
            "repetido": bool(tiene and usuario_con_telefono(current_user.telefono, excluir_id=current_user.id)),
            "aprobada": current_user.estado_permiso == "aprobado" and current_user.activo and bool(current_user.cliente_id),
        }
        revision["listo"] = tiene and not revision["repetido"] and revision["aprobada"] and \
            usuario_por_telefono(current_user.telefono) is not None
        if current_user.cliente_id:
            vista_estado = _estado(current_user)
    enlace = f"https://wa.me/{numero}?text={(union or 'MENU').replace(' ', '%20')}" if numero else None
    return render_template("whatsapp/guia.html", numero=numero, union=union, enlace=enlace,
                           revision=revision, vista_estado=vista_estado,
                           bot_activo=bool(current_app.config.get("TWILIO_AUTH_TOKEN")),
                           max_mensajes=current_app.config.get("WHATSAPP_MAX_MENSAJES", 20))
