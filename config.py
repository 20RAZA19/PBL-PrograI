import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))


def _activado(nombre, por_defecto="0"):
    return os.environ.get(nombre, por_defecto).strip().lower() in ("1", "true", "si", "sí", "yes")


def _clave_secreta():
    """SECRET_KEY firma las cookies de sesión: si alguien la conoce puede hacerse pasar por
    cualquier usuario. Se toma de la variable de entorno; si no existe, se genera una al azar
    y se guarda en instance/secret_key (carpeta que no se sube a GitHub)."""
    clave = os.environ.get("SECRET_KEY", "").strip()
    if clave:
        return clave
    carpeta = os.path.join(basedir, "instance")
    ruta = os.path.join(carpeta, "secret_key")
    try:
        with open(ruta, encoding="utf-8") as f:
            clave = f.read().strip()
    except OSError:
        clave = ""
    if not clave:
        clave = secrets.token_hex(32)
        os.makedirs(carpeta, exist_ok=True)
        with open(ruta, "w", encoding="utf-8") as f:
            f.write(clave)
        try:
            os.chmod(ruta, 0o600)
        except OSError:
            pass
    return clave


class Config:
    SECRET_KEY = _clave_secreta()

    # --- Seguridad de la sesión ---
    SESSION_COOKIE_HTTPONLY = True            # JavaScript no puede leer la cookie
    SESSION_COOKIE_SAMESITE = "Lax"           # no se envía en formularios de otros sitios
    SESSION_COOKIE_SECURE = _activado("SESSION_COOKIE_SECURE")  # 1 en producción (HTTPS)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=10)
    # 1 cuando la app corre detrás de un proxy (PythonAnywhere, Render…): toma la IP real del cliente
    DETRAS_DE_PROXY = _activado("DETRAS_DE_PROXY")

    # Bloqueo por intentos fallidos de inicio de sesión
    LOGIN_MAX_INTENTOS_CUENTA = int(os.environ.get("LOGIN_MAX_INTENTOS_CUENTA", 5))
    LOGIN_MAX_INTENTOS_IP = int(os.environ.get("LOGIN_MAX_INTENTOS_IP", 20))
    LOGIN_BLOQUEO_MIN = int(os.environ.get("LOGIN_BLOQUEO_MIN", 15))
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Ubicación del taller (punto de partida de los pedidos en el mapa de rastreo)
    TALLER_NOMBRE = os.environ.get("TALLER_NOMBRE", "Taller Principal Arte y Color")
    TALLER_LAT = float(os.environ.get("TALLER_LAT", 13.6929))
    TALLER_LNG = float(os.environ.get("TALLER_LNG", -89.2182))

    # Segundos entre cada consulta automática de la vista de rastreo
    RASTREO_REFRESCO_SEG = int(os.environ.get("RASTREO_REFRESCO_SEG", 20))

    # Fotos de diseños e insumos (máximo 5 MB por archivo)
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(basedir, "app", "static", "uploads"))
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024

    # Datos de la empresa que aparecen en cotizaciones y órdenes de compra
    EMPRESA_NOMBRE = os.environ.get("EMPRESA_NOMBRE", "Arte y Color")
    EMPRESA_DIRECCION = os.environ.get("EMPRESA_DIRECCION", "Taller Principal · San Salvador, El Salvador")
    EMPRESA_TELEFONO = os.environ.get("EMPRESA_TELEFONO", "Tel. +503 2222 0000")
    EMPRESA_EMAIL = os.environ.get("EMPRESA_EMAIL", "ventas@arteycolor.com")
    EMPRESA_NIT = os.environ.get("EMPRESA_NIT", "")

    # Vigencia (en días) de la cotización que se publica al aprobar una solicitud
    COTIZACION_VIGENCIA_DIAS = int(os.environ.get("COTIZACION_VIGENCIA_DIAS", 15))

    # Bitácora de auditoría automática (ver app/auditoria.py)
    AUDITORIA_ACTIVA = True
    # La bitácora conserva estos días; lo más antiguo se respalda en un CSV comprimido y se borra
    AUDITORIA_RETENCION_DIAS = int(os.environ.get("AUDITORIA_RETENCION_DIAS", 90))
    # Los respaldos (instance/respaldos) se eliminan solos pasado este tiempo; 0 = nunca
    AUDITORIA_RESPALDOS_DIAS = int(os.environ.get("AUDITORIA_RESPALDOS_DIAS", 365))

    # Bot de WhatsApp (Twilio). Sin TWILIO_AUTH_TOKEN el webhook queda apagado;
    # el simulador interno (/whatsapp/simulador, solo admin) funciona siempre.
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # número del sandbox
    # Frase para unirse al sandbox de Twilio (p. ej. «join silver-tiger»). Se muestra en la guía del cliente.
    # Hora local del negocio (el servidor de PythonAnywhere usa UTC)
    ZONA_HORARIA = os.environ.get("ZONA_HORARIA", "America/El_Salvador")
    WHATSAPP_CODIGO_UNION = os.environ.get("WHATSAPP_CODIGO_UNION", "").strip()
    # Mensajes que acepta el bot por número en 15 minutos (frena a quien prueba comandos sin parar)
    WHATSAPP_MAX_MENSAJES = int(os.environ.get("WHATSAPP_MAX_MENSAJES", 20))
    # Avisos salientes por WhatsApp (cotización lista, etc.). Requiere Twilio configurado.
    WHATSAPP_AVISOS = _activado("WHATSAPP_AVISOS", "0")

    # Recuperación de contraseña: el código llega por correo (Gmail)
    RECUPERACION_MINUTOS = int(os.environ.get("RECUPERACION_MINUTOS", 15))
    RECUPERACION_MAX_INTENTOS = int(os.environ.get("RECUPERACION_MAX_INTENTOS", 5))
    # Correos de código que una cuenta puede recibir por hora (evita usar el sitio para llenar un buzón)
    RECUPERACION_MAX_CORREOS_HORA = int(os.environ.get("RECUPERACION_MAX_CORREOS_HORA", 3))

    # Correo saliente (Gmail con contraseña de aplicación). Ver app/correo.py
    MAIL_SERVER = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", 587))
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD", "").replace(" ", "")  # Google la muestra en grupos de 4
    MAIL_REMITENTE = os.environ.get("MAIL_REMITENTE", "Arte y Color")

    # Mensajería asistente–cliente: una conversación sin actividad se borra pasados estos días,
    # salvo que el cliente la haya marcado «Guardar conversación»
    MENSAJES_RETENCION_DIAS = int(os.environ.get("MENSAJES_RETENCION_DIAS", 30))
    MENSAJES_REFRESCO_SEG = int(os.environ.get("MENSAJES_REFRESCO_SEG", 8))
