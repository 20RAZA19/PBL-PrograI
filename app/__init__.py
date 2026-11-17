import os
from flask import Flask, render_template
from config import Config
from app.extensions import db, migrate, login_manager, csrf

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
         "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]

def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    if app.config.get("DETRAS_DE_PROXY"):
        # El proxy agrega la IP real y el protocolo (https) en las cabeceras X-Forwarded-*
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.config["SQLALCHEMY_DATABASE_URI"] = (
            "sqlite:///" + os.path.join(app.instance_path, "inventario.db")
        )

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Por favor, inicie sesión para acceder a esta página.'
    login_manager.login_message_category = 'info'

    from app import models

    from app.main.routes import main
    app.register_blueprint(main)

    from app.telas.routes import telas
    app.register_blueprint(telas, url_prefix="/telas")

    from app.auth import auth
    app.register_blueprint(auth, url_prefix="/auth")

    from app.rastreo.routes import rastreo
    app.register_blueprint(rastreo, url_prefix="/rastreo")

    from app.admin.routes import admin
    app.register_blueprint(admin, url_prefix="/admin")

    from app.catalogo.routes import catalogo
    app.register_blueprint(catalogo, url_prefix="/catalogo")

    from app.faq.routes import faq
    app.register_blueprint(faq, url_prefix="/faq")

    from app.contactos.routes import contactos
    app.register_blueprint(contactos, url_prefix="/contactos")

    from app.reportes.routes import reportes
    app.register_blueprint(reportes, url_prefix="/reportes")

    from app.asistente.routes import asistente
    app.register_blueprint(asistente, url_prefix="/asistente")

    from app.cotizaciones.routes import cotizaciones
    app.register_blueprint(cotizaciones, url_prefix="/cotizaciones")

    from app.compras.routes import compras
    app.register_blueprint(compras, url_prefix="/compras")

    from app.costos.routes import costos
    app.register_blueprint(costos, url_prefix="/costos")

    from app.calidad.routes import calidad
    app.register_blueprint(calidad, url_prefix="/calidad")

    from app.notificaciones.routes import notificaciones
    app.register_blueprint(notificaciones, url_prefix="/notificaciones")

    from app.seguimiento.routes import seguimiento
    app.register_blueprint(seguimiento, url_prefix="/seguimiento")

    from app.solicitudes.routes import solicitudes
    app.register_blueprint(solicitudes, url_prefix="/solicitudes")

    from app.whatsapp.routes import whatsapp
    app.register_blueprint(whatsapp, url_prefix="/whatsapp")

    from app.mensajes.routes import mensajes
    app.register_blueprint(mensajes, url_prefix="/mensajes")

    from app.auditoria import activar_auditoria
    activar_auditoria()

    from app.commands import seed, demo, crear_admin, claves_demo, purgar_bitacora_cmd, purgar_mensajes_cmd
    app.cli.add_command(purgar_bitacora_cmd)
    app.cli.add_command(purgar_mensajes_cmd)
    app.cli.add_command(seed)
    app.cli.add_command(demo)
    app.cli.add_command(crear_admin)
    app.cli.add_command(claves_demo)

    @app.template_filter("fecha_es")
    def fecha_es(fecha):
        if not fecha:
            return "—"
        return f"{fecha.day} {MESES[fecha.month - 1]} {fecha.year}"

    @app.template_filter("metros")
    def formato_metros(valor):
        valor = float(valor or 0)
        return f"{valor:,.0f}" if valor.is_integer() else f"{valor:,.2f}"

    UNIDADES_CORTAS = {"Metros": "mts", "Yardas": "yds", "Unidades": "und.", "Conos": "conos",
                       "Rollos": "rollos", "Docenas": "doc."}

    @app.template_filter("unidad_corta")
    def unidad_corta(unidad):
        return UNIDADES_CORTAS.get(unidad or "", (unidad or "").lower())

    @app.template_filter("iniciales")
    def iniciales(texto):
        palabras = [p for p in (texto or "").split() if len(p) > 2 or p[:1].isupper()]
        if not palabras:
            return (texto or "?")[:2].upper()
        return "".join(p[0] for p in palabras[:2]).upper()

    @app.template_filter("dinero")
    def formato_dinero(valor):
        from app.documentos import dinero
        return dinero(valor)

    @app.template_filter("hace")
    def hace(fecha):
        """«hace 5 min», «hace 3 h», «hace 2 d»."""
        from datetime import datetime as _dt
        if not fecha:
            return ""
        seg = int((_dt.now() - fecha).total_seconds())
        if seg < 60:
            return "hace un momento"
        if seg < 3600:
            return f"hace {seg // 60} min"
        if seg < 86400:
            return f"hace {seg // 3600} h"
        return f"hace {seg // 86400} d"

    @app.template_filter("hora")
    def formato_hora(fecha):
        return fecha.strftime("%H:%M") if fecha else ""

    @app.context_processor
    def inyectar_globales():
        from flask_login import current_user
        from app.models import Usuario, FASES
        pendientes = 0
        if current_user.is_authenticated and current_user.rol == "admin":
            pendientes = Usuario.query.filter_by(estado_permiso="pendiente").count()
        from datetime import datetime
        from app.asistente.motor import sugerencias_iniciales
        ahora = datetime.now()

        avisos, avisos_sin_leer, prendas_por_atender, mensajes_sin_leer = [], 0, 0, 0
        if current_user.is_authenticated and current_user.rol in ("admin", "ventas"):
            from app.models import Solicitud
            prendas_por_atender = Solicitud.query.filter_by(estado="enviada").count()
        if current_user.is_authenticated and current_user.rol in ("admin", "ventas", "cliente"):
            from app.mensajes.servicios import sin_leer_total
            mensajes_sin_leer = sin_leer_total(current_user)
        if current_user.is_authenticated:
            from flask import session
            from app.models import Notificacion
            from app.notificaciones.servicios import sincronizar
            # Recalcula los avisos automáticos como máximo una vez por minuto
            ultima = session.get("avisos_sync", 0)
            # (solo si la vista no dejó cambios sin guardar, para no confirmarlos por accidente)
            sesion_limpia = not (db.session.new or db.session.dirty or db.session.deleted)
            if sesion_limpia and ahora.timestamp() - ultima > app.config.get("AVISOS_REFRESCO_SEG", 60):
                sincronizar(current_user)
                session["avisos_sync"] = ahora.timestamp()
            base = Notificacion.query.filter_by(usuario_id=current_user.id)
            avisos_sin_leer = base.filter_by(leida=False).count()
            avisos = base.order_by(Notificacion.leida, Notificacion.creada_en.desc()).limit(6).all()
        return {
            "avisos": avisos,
            "avisos_sin_leer": avisos_sin_leer,
            "now_es": f"{ahora.day} {MESES[ahora.month - 1]} {ahora.year} · {ahora:%H:%M}",
            "asistente_sugerencias": sugerencias_iniciales(current_user.rol) if current_user.is_authenticated else [],
            "solicitudes_pendientes": pendientes,
            "prendas_por_atender": prendas_por_atender,
            "mensajes_sin_leer": mensajes_sin_leer,
            "FASES": FASES,
            "TALLER": {
                "nombre": app.config["TALLER_NOMBRE"],
                "lat": app.config["TALLER_LAT"],
                "lng": app.config["TALLER_LNG"],
            },
        }

    @app.errorhandler(403)
    def acceso_denegado(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(413)
    def archivo_grande(error):
        from flask import flash, redirect, request
        from app.utils import destino_seguro
        flash("La imagen supera el límite de 5 MB. Redúcela e inténtalo de nuevo.", "danger")
        return redirect(destino_seguro(request.path, "/"))

    @app.after_request
    def cabeceras_seguridad(respuesta):
        """Cabeceras HTTP que endurecen el navegador frente a ataques comunes."""
        from flask_login import current_user
        h = respuesta.headers
        h.setdefault("X-Content-Type-Options", "nosniff")          # no adivinar tipos de archivo
        h.setdefault("X-Frame-Options", "SAMEORIGIN")              # evita clickjacking con iframes
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), payment=(), usb=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if app.config.get("SESSION_COOKIE_SECURE"):
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        # Páginas con datos privados: que el navegador no las guarde (botón «atrás» tras cerrar sesión)
        if respuesta.mimetype == "text/html" and current_user and current_user.is_authenticated:
            h.setdefault("Cache-Control", "no-store")
        return respuesta

    @app.errorhandler(404)
    def no_encontrado(error):
        return render_template("errors/404.html"), 404

    return app
