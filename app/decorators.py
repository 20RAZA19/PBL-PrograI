"""Control de acceso basado en roles (RBAC).

Uso (siempre junto a @login_required):

    @bp.route("/ruta")
    @login_required
    @roles_required("admin", "gestor")
    def vista():
        ...
"""
from functools import wraps

from flask import abort, request, jsonify
from flask_login import current_user


def roles_required(*roles):
    """Permite el acceso solo si current_user.rol está en `roles`.

    Responde 403 (página de error con el diseño del sistema, o JSON si la
    petición es a un endpoint .json).
    """
    def decorator(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if not current_user.is_authenticated or current_user.rol not in roles:
                if request.path.endswith(".json"):
                    return jsonify(error="No autorizado"), 403
                abort(403)
            return vista(*args, **kwargs)
        return envoltura
    return decorator


def staff_required(vista):
    """Atajo para admin + gestor."""
    return roles_required("admin", "gestor")(vista)


def admin_required(vista):
    """Atajo para solo administradores."""
    return roles_required("admin")(vista)
