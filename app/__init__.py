import os

from flask import Flask

from config import Config
from app.extensions import db, migrate, login_manager, csrf

MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
         "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    # Si no hay DATABASE_URL en el .env, usa SQLite en la carpeta instance/
    os.makedirs(app.instance_path, exist_ok=True)
    if not app.config.get("SQLALCHEMY_DATABASE_URI"):
        app.config["SQLALCHEMY_DATABASE_URI"] = (
            "sqlite:///" + os.path.join(app.instance_path, "inventario.db")
        )

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app import models  # noqa: F401  (registra los modelos)

    from app.main.routes import main
    app.register_blueprint(main)

    from app.telas.routes import telas
    app.register_blueprint(telas, url_prefix="/telas")

    from app.commands import seed
    app.cli.add_command(seed)

    @app.template_filter("fecha_es")
    def fecha_es(fecha):
        if not fecha:
            return "—"
        return f"{fecha.day} {MESES[fecha.month - 1]} {fecha.year}"
    
    @app.template_filter("metros")
    def formato_metros(valor):
        valor = float(valor or 0)
        return f"{valor:,.0f}" if valor.is_integer() else f"{valor:,.2f}"
    return app