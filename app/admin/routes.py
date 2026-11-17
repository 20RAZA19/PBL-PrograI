from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.models import Usuario, Cliente, ROLES, ESTADOS_PERMISO
from app.decorators import roles_required
from app.utils import fila_csv, volver_a
from app.forms import UsuarioAdminForm, AccionForm

admin = Blueprint("admin", __name__)


def _admins_activos_restantes(excluir_id):
    return Usuario.query.filter(
        Usuario.rol == "admin", Usuario.activo.is_(True),
        Usuario.estado_permiso == "aprobado", Usuario.id != excluir_id,
    ).count()


@admin.route("/usuarios")
@login_required
@roles_required("admin")
def usuarios():
    vista = request.args.get("vista", "pendientes")
    q = request.args.get("q", "").strip()
    rol = request.args.get("rol", "")

    pendientes = (Usuario.query.filter_by(estado_permiso="pendiente")
                  .order_by(Usuario.creado_en.desc()).all())

    query = Usuario.query
    if vista == "pendientes":
        query = query.filter_by(estado_permiso="pendiente")
    if q:
        query = query.filter(or_(Usuario.nombre.ilike(f"%{q}%"),
                                 Usuario.email.ilike(f"%{q}%"),
                                 Usuario.cargo.ilike(f"%{q}%")))
    if rol in ROLES:
        query = query.filter_by(rol=rol)
    lista_usuarios = query.order_by(Usuario.creado_en.desc()).all()

    stats = {
        "total": Usuario.query.count(),
        "pendientes": len(pendientes),
        "activos": Usuario.query.filter_by(activo=True, estado_permiso="aprobado").count(),
        "por_rol": {r: Usuario.query.filter_by(rol=r).count() for r in ROLES},
    }
    return render_template("admin/usuarios.html", usuarios=lista_usuarios, vista=vista,
                           q=q, rol=rol, stats=stats, ROLES=ROLES,
                           ESTADOS_PERMISO=ESTADOS_PERMISO, accion_form=AccionForm())


@admin.route("/usuarios/<int:usuario_id>/aprobar", methods=["POST"])
@login_required
@roles_required("admin")
def aprobar(usuario_id):
    usuario = db.get_or_404(Usuario, usuario_id)
    if AccionForm().validate_on_submit():
        usuario.estado_permiso = "aprobado"
        usuario.activo = True
        db.session.commit()
        flash(f"{usuario.nombre} ahora tiene acceso como {usuario.rol_legible}.", "ok")
    return redirect(volver_a(url_for("admin.usuarios")))


@admin.route("/usuarios/<int:usuario_id>/rechazar", methods=["POST"])
@login_required
@roles_required("admin")
def rechazar(usuario_id):
    usuario = db.get_or_404(Usuario, usuario_id)
    if usuario.id == current_user.id:
        flash("No puedes rechazar tu propia cuenta.", "danger")
        return redirect(url_for("admin.usuarios"))
    if AccionForm().validate_on_submit():
        usuario.estado_permiso = "rechazado"
        db.session.commit()
        flash(f"La solicitud de {usuario.nombre} fue rechazada.", "warn")
    return redirect(volver_a(url_for("admin.usuarios")))


@admin.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def editar_usuario(usuario_id):
    usuario = db.get_or_404(Usuario, usuario_id)
    form = UsuarioAdminForm(obj=usuario, usuario_id=usuario.id)
    form.cliente_id.choices = [(0, "— Sin empresa —")] + [
        (c.id, c.nombre) for c in Cliente.query.order_by(Cliente.nombre).all()
    ]
    if request.method == "GET":
        form.cliente_id.data = usuario.cliente_id or 0

    es_uno_mismo = usuario.id == current_user.id

    if form.validate_on_submit():
        # Protecciones: el admin no puede quitarse privilegios a sí mismo,
        # y el sistema nunca se queda sin administradores.
        pierde_admin = usuario.rol == "admin" and (
            form.rol.data != "admin" or not form.activo.data or form.estado_permiso.data != "aprobado"
        )
        if es_uno_mismo and pierde_admin:
            flash("No puedes quitarte el rol de administrador ni desactivar tu propia cuenta.", "danger")
            return redirect(url_for("admin.editar_usuario", usuario_id=usuario.id))
        if pierde_admin and _admins_activos_restantes(usuario.id) == 0:
            flash("Debe existir al menos un administrador activo.", "danger")
            return redirect(url_for("admin.editar_usuario", usuario_id=usuario.id))

        usuario.nombre = form.nombre.data.strip()
        usuario.email = form.email.data.strip().lower()
        usuario.cargo = form.cargo.data or None
        usuario.telefono = form.telefono.data or None
        usuario.rol = form.rol.data
        usuario.estado_permiso = form.estado_permiso.data
        usuario.activo = form.activo.data
        usuario.cliente_id = form.cliente_id.data or None
        db.session.commit()
        flash(f"Datos de {usuario.nombre} actualizados.", "ok")
        return redirect(url_for("admin.usuarios", vista="todos"))

    return render_template("admin/editar_usuario.html", form=form, usuario=usuario,
                           es_uno_mismo=es_uno_mismo, accion_form=AccionForm())


@admin.route("/usuarios/<int:usuario_id>/token", methods=["POST"])
@login_required
@roles_required("admin")
def token_usuario(usuario_id):
    """Genera (o reemplaza) el token de seguimiento de un cliente. El anterior deja de funcionar."""
    usuario = db.get_or_404(Usuario, usuario_id)
    if not AccionForm().validate_on_submit():
        abort(400)
    if usuario.rol != "cliente":
        flash("El token de seguimiento es solo para cuentas de cliente.", "warn")
    elif len(usuario.telefono_digitos) < 4:
        flash("Registra primero el teléfono del cliente: sus últimos 4 dígitos se piden junto con el token.", "warn")
    else:
        tenia = bool(usuario.token_seguimiento)
        usuario.generar_token()
        db.session.commit()
        flash("Token regenerado: el anterior ya no funciona." if tenia else "Token de seguimiento generado.", "ok")
    return redirect(url_for("admin.editar_usuario", usuario_id=usuario.id))


# ---------------------------------------------------------------------------
# Bitácora de auditoría
# ---------------------------------------------------------------------------
def _consulta_bitacora():
    from datetime import date, datetime, timedelta
    from app.models import Auditoria

    q = request.args.get("q", "").strip()
    usuario_id = request.args.get("usuario", type=int)
    entidad = request.args.get("entidad", "")
    accion = request.args.get("accion", "")
    dias = request.args.get("dias", 30, type=int)

    query = Auditoria.query
    if q:
        query = query.filter(or_(Auditoria.descripcion.ilike(f"%{q}%"), Auditoria.cambios.ilike(f"%{q}%")))
    if usuario_id:
        query = query.filter(Auditoria.usuario_id == usuario_id)
    if entidad:
        query = query.filter(Auditoria.entidad == entidad)
    if accion:
        query = query.filter(Auditoria.accion == accion)
    if dias and dias > 0:
        query = query.filter(Auditoria.fecha >= datetime.now() - timedelta(days=dias))
    filtros = {"q": q, "usuario": usuario_id, "entidad": entidad, "accion": accion, "dias": dias}
    return query.order_by(Auditoria.fecha.desc(), Auditoria.id.desc()), filtros


@admin.route("/bitacora")
@login_required
@roles_required("admin")
def bitacora():
    from flask import current_app
    from app.auditoria import ACCIONES, antiguos, listar_respaldos
    from app.models import Auditoria

    query, filtros = _consulta_bitacora()
    pagina = query.paginate(page=request.args.get("pagina", 1, type=int), per_page=40, error_out=False)
    entidades = [e for (e,) in db.session.query(Auditoria.entidad).distinct().order_by(Auditoria.entidad)]
    usuarios_lista = Usuario.query.filter(Usuario.rol != "cliente").order_by(Usuario.nombre).all()
    retencion = {"dias": current_app.config.get("AUDITORIA_RETENCION_DIAS", 90),
                 "total": Auditoria.query.count(), "antiguos": antiguos()[0].count(),
                 "respaldos": listar_respaldos()}
    return render_template("admin/bitacora.html", pagina=pagina, filtros=filtros, entidades=entidades,
                           usuarios=usuarios_lista, acciones=ACCIONES, retencion=retencion,
                           accion_form=AccionForm())


@admin.route("/bitacora.csv")
@login_required
@roles_required("admin")
def bitacora_csv():
    import csv
    import io
    from flask import Response
    from app.auditoria import ENCABEZADO_CSV, fila_bitacora

    query, _ = _consulta_bitacora()
    salida = io.StringIO()
    salida.write("\ufeff")
    escritor = csv.writer(salida)
    escritor.writerow(ENCABEZADO_CSV)
    for r in query.limit(10000).all():
        escritor.writerow(fila_bitacora(r))
    return Response(salida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=bitacora_auditoria.csv"})


@admin.route("/bitacora/depurar", methods=["POST"])
@login_required
@roles_required("admin")
def bitacora_depurar():
    from app.auditoria import purgar_bitacora
    if not AccionForm().validate_on_submit():
        abort(400)
    borrados, nombre = purgar_bitacora()
    if borrados:
        flash(f"Se respaldaron y eliminaron {borrados:,} registros antiguos. Descarga el respaldo «{nombre}» "
              "y guárdalo fuera del servidor.", "ok")
    else:
        flash("No hay registros más antiguos que el periodo de retención.", "info")
    return redirect(url_for("admin.bitacora"))


@admin.route("/bitacora/respaldos/<nombre>")
@login_required
@roles_required("admin")
def bitacora_respaldo(nombre):
    from flask import send_file
    from app.auditoria import ruta_respaldo
    ruta = ruta_respaldo(nombre)
    if not ruta:
        abort(404)
    return send_file(ruta, as_attachment=True, download_name=nombre, mimetype="application/gzip")


@admin.route("/bitacora/respaldos/<nombre>/eliminar", methods=["POST"])
@login_required
@roles_required("admin")
def bitacora_respaldo_eliminar(nombre):
    import os
    from app.auditoria import registrar_accion, ruta_respaldo
    if not AccionForm().validate_on_submit():
        abort(400)
    ruta = ruta_respaldo(nombre)
    if not ruta:
        abort(404)
    os.remove(ruta)
    registrar_accion("eliminar", "Bitácora", f"Respaldo eliminado del servidor: {nombre}")
    db.session.commit()
    flash("Respaldo eliminado del servidor.", "info")
    return redirect(url_for("admin.bitacora"))
