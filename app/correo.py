"""Envío de correo por SMTP (Gmail) con la librería estándar.

Configuración (.env):
    MAIL_USERNAME   cuenta de Gmail que envía, p. ej. arteycolor.sistema@gmail.com
    MAIL_PASSWORD   contraseña de aplicación de Google (16 letras), NO la contraseña normal
    MAIL_SERVER / MAIL_PORT   por defecto smtp.gmail.com:587 (STARTTLS); PythonAnywhere gratuito lo permite
    MAIL_REMITENTE  nombre visible, por defecto «Arte y Color»

Sin MAIL_USERNAME/MAIL_PASSWORD no se envía nada. En ese caso, solo si la app NO
está en producción (SESSION_COOKIE_SECURE apagado), el contenido se escribe en la
consola del servidor para poder probar en local.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from flask import current_app

log = logging.getLogger(__name__)


def configurado():
    cfg = current_app.config
    return bool(cfg.get("MAIL_USERNAME") and cfg.get("MAIL_PASSWORD"))


def _construir(destino, asunto, texto, html=None):
    cfg = current_app.config
    m = EmailMessage()
    m["Subject"] = asunto
    m["From"] = formataddr((cfg.get("MAIL_REMITENTE") or "Arte y Color", cfg.get("MAIL_USERNAME") or "no-reply@localhost"))
    m["To"] = destino
    m["Message-ID"] = make_msgid(domain="aycontrol")
    m.set_content(texto)
    if html:
        m.add_alternative(html, subtype="html")
    return m


def enviar_correo(destino, asunto, texto, html=None):
    """Devuelve True si el servidor SMTP aceptó el correo. Nunca lanza excepción."""
    cfg = current_app.config
    mensaje = _construir(destino, asunto, texto, html)

    if cfg.get("TESTING"):
        current_app.extensions.setdefault("correos_enviados", []).append(mensaje)
        return True

    if not configurado():
        if not cfg.get("SESSION_COOKIE_SECURE"):
            log.warning("[correo sin configurar] Para %s · %s\n%s", destino, asunto, texto)
            print(f"\n=== CORREO (sin configurar, solo local) para {destino} ===\n{asunto}\n{texto}\n", flush=True)
        else:
            log.error("Correo sin configurar: no se envió «%s» a %s", asunto, destino)
        return False

    try:
        with smtplib.SMTP(cfg.get("MAIL_SERVER", "smtp.gmail.com"), int(cfg.get("MAIL_PORT", 587)), timeout=15) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(cfg["MAIL_USERNAME"], cfg["MAIL_PASSWORD"])
            s.send_message(mensaje)
        return True
    except (smtplib.SMTPException, OSError) as e:
        log.error("No se pudo enviar el correo a %s: %s", destino, e)
        return False


def correo_codigo_recuperacion(usuario, codigo, minutos, enlace):
    nombre = usuario.nombre.split()[0] if usuario.nombre else ""
    asunto = f"{codigo} es tu código para cambiar la contraseña · AyC Control"
    texto = (f"Hola {nombre}:\n\n"
             f"Tu código para cambiar la contraseña de AyC Control es:\n\n    {codigo}\n\n"
             f"Vale {minutos} minutos y solo se puede usar una vez. Escríbelo en:\n{enlace}\n\n"
             "Si no pediste cambiar tu contraseña, ignora este correo: tu cuenta sigue igual.\n\n"
             "Arte y Color")
    html = f"""<!doctype html><html><body style="margin:0;background:#f4f6f3;font-family:Arial,Helvetica,sans-serif;color:#1f2a1f;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border-radius:14px;overflow:hidden;">
<tr><td style="background:#2d5a27;color:#ffffff;padding:20px 28px;font-size:18px;font-weight:bold;">AyC Control · Arte y Color</td></tr>
<tr><td style="padding:28px;">
<p style="margin:0 0 12px;font-size:15px;">Hola {nombre}:</p>
<p style="margin:0 0 18px;font-size:15px;line-height:1.5;">Tu código para cambiar la contraseña es:</p>
<p style="margin:0 0 18px;text-align:center;font-size:34px;letter-spacing:8px;font-weight:bold;color:#2d5a27;">{codigo}</p>
<p style="margin:0 0 18px;font-size:14px;line-height:1.5;color:#55604f;">Vale <strong>{minutos} minutos</strong> y solo se puede usar una vez.</p>
<p style="margin:0 0 22px;text-align:center;"><a href="{enlace}" style="display:inline-block;background:#2d5a27;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:10px;font-weight:bold;font-size:14px;">Escribir el código</a></p>
<p style="margin:0;font-size:12px;line-height:1.5;color:#7a8475;">Si no pediste cambiar tu contraseña, ignora este correo: tu cuenta sigue igual. Nadie de Arte y Color te pedirá este código.</p>
</td></tr></table></td></tr></table></body></html>"""
    return enviar_correo(usuario.email, asunto, texto, html)
