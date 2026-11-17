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
