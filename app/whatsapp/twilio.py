"""Integración mínima con Twilio sin librerías externas.

* `firma_valida` comprueba la cabecera X-Twilio-Signature que Twilio envía con cada
  webhook: HMAC-SHA1 (con el Auth Token) de la URL completa seguida de los
  parámetros POST ordenados por nombre, en Base64. Sin esa firma cualquiera podría
  hacerse pasar por Twilio y pedir tokens de clientes.
* `twiml` arma la respuesta XML que Twilio reenvía al usuario.
* `enviar_whatsapp` manda un mensaje por iniciativa propia (requiere Twilio
  configurado; en PythonAnywhere gratuito puede no estar permitido, así que
  nunca interrumpe la operación si falla).
"""
import base64
import hashlib
import hmac
import logging
import urllib.error
import urllib.parse
import urllib.request
from xml.sax.saxutils import escape

from flask import current_app

log = logging.getLogger(__name__)


def calcular_firma(url, params, auth_token):
    cadena = url + "".join(k + str(v) for k, v in sorted(params.items()))
    digest = hmac.new(auth_token.encode("utf-8"), cadena.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def firma_valida(url, params, firma, auth_token):
    if not (auth_token and firma):
        return False
    esperada = calcular_firma(url, params, auth_token)
    if hmac.compare_digest(esperada, firma):
        return True
    # Detrás de un proxy la URL puede llegar con o sin puerto explícito; Twilio firma la pública.
    partes = urllib.parse.urlsplit(url)
    if partes.port and partes.port in (80, 443):
        sin_puerto = partes._replace(netloc=partes.hostname).geturl()
        return hmac.compare_digest(calcular_firma(sin_puerto, params, auth_token), firma)
    return False


def twiml(texto):
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(texto)}</Message></Response>'


def configurado():
    cfg = current_app.config
    return bool(cfg.get("TWILIO_ACCOUNT_SID") and cfg.get("TWILIO_AUTH_TOKEN") and cfg.get("TWILIO_WHATSAPP_FROM"))


def enviar_whatsapp(telefono_digitos, texto, timeout=6):
    """Envía un mensaje saliente. Devuelve True si Twilio lo aceptó; False en cualquier otro caso."""
    if not (configurado() and telefono_digitos and texto):
        return False
    cfg = current_app.config
    sid, token = cfg["TWILIO_ACCOUNT_SID"], cfg["TWILIO_AUTH_TOKEN"]
    datos = urllib.parse.urlencode({
        "From": cfg["TWILIO_WHATSAPP_FROM"],
        "To": f"whatsapp:+{telefono_digitos}",
        "Body": texto[:1500],
    }).encode("utf-8")
    peticion = urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=datos)
    credencial = base64.b64encode(f"{sid}:{token}".encode()).decode("ascii")
    peticion.add_header("Authorization", f"Basic {credencial}")
    try:
        with urllib.request.urlopen(peticion, timeout=timeout) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError, ValueError) as e:  # sin red, credenciales malas, etc.
        log.warning("No se pudo enviar el WhatsApp: %s", e)
        return False
