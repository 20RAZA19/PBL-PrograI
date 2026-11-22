from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.models import Usuario, Cliente, ROLES, ESTADOS_PERMISO, telefonos_duplicados
from app.decorators import roles_required
from app.utils import fila_csv, paginar, volver_a
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

    pendientes = Usuario.query.filter_by(estado_permiso="pendiente").count()

    query = Usuario.query
    if vista == "pendientes":
        query = query.filter_by(estado_permiso="pendiente")
    if q:
        query = query.filter(or_(Usuario.nombre.ilike(f"%{q}%"),
                                 Usuario.email.ilike(f"%{q}%"),
                                 Usuario.cargo.ilike(f"%{q}%")))
    if rol in ROLES:
        query = query.filter_by(rol=rol)
    pagina = paginar(query.order_by(Usuario.creado_en.desc()))
    lista_usuarios = pagina.items

    stats = {
        "total": Usuario.query.count(),
        "pendientes": pendientes,
        "activos": Usuario.query.filter_by(activo=True, estado_permiso="aprobado").count(),
        "por_rol": {r: Usuario.query.filter_by(rol=r).count() for r in ROLES},
    }
    return render_template("admin/usuarios.html", usuarios=lista_usuarios, pagina=pagina, vista=vista,
                           q=q, rol=rol, stats=stats, ROLES=ROLES, duplicados=telefonos_duplicados(),
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
    pagina = paginar(query, por_defecto=50)
    entidades = [e for (e,) in db.session.query(Auditoria.entidad).distinct().order_by(Auditoria.entidad)]
    usuarios_lista = Usuario.query.filter(Usuario.rol != "cliente").order_by(Usuario.nombre).all()
    retencion = {"dias": current_app.config.get("AUDITORIA_RETENCION_DIAS", 90),
                 "total": Auditoria.query.count(), "antiguos": antiguos()[0].count(),
                 "respaldos": listar_respaldos()}
    return render_template("admin/bitacora.html", pagina=pagina, filtros=filtros, entidades=entidades,
                           usuarios=usuarios_lista, acciones=ACCIONES, retencion=retencion,
                           accion_form=AccionForm(), actividad=_actividad_bitacora())


def _actividad_bitacora(dias=14):
    """Registros por día (últimos 14 días) y los módulos con más cambios, para los gráficos."""
    from collections import Counter
    from datetime import date, datetime, timedelta
    from app.models import Auditoria
    hoy = date.today()
    desde = datetime.combine(hoy - timedelta(days=dias - 1), datetime.min.time())
    por_modulo, cambios, sesiones = Counter(), Counter(), Counter()
    filas = (db.session.query(Auditoria.fecha, Auditoria.accion, Auditoria.entidad)
             .filter(Auditoria.fecha >= desde).all())
    for fecha, accion, entidad in filas:
        if accion in ("sesion", "consulta", "whatsapp", "recuperacion"):
            sesiones[fecha.date()] += 1
        else:
            cambios[fecha.date()] += 1
            por_modulo[entidad] += 1
    dias_lista = [hoy - timedelta(days=d) for d in range(dias - 1, -1, -1)]
    meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    top = por_modulo.most_common(6)
    return {
        "total": len(filas),
        "diario": {"tipo": "barras", "apilado": True, "unidad": "registros",
                   "etiquetas": [f"{d.day} {meses[d.month - 1]}" for d in dias_lista],
                   "series": [{"nombre": "Cambios (crear, editar, eliminar)", "valores": [cambios[d] for d in dias_lista]},
                              {"nombre": "Accesos y consultas", "valores": [sesiones[d] for d in dias_lista]}]},
        "modulos": {"tipo": "barras-h", "unidad": "cambios", "etiquetas": [e for e, _ in top],
                    "series": [{"nombre": "Cambios", "valores": [n for _, n in top]}]},
    }


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


# ---------------------------------------------------------------------------
# Diagnóstico del correo: muestra la configuración y envía un correo de prueba
# con el error real de Gmail si falla. Sirve para saber por qué no llega la
# recuperación de contraseña.
# ---------------------------------------------------------------------------
@admin.route("/correo", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def correo():
    from app.auditoria import registrar_accion
    from app.correo import correo_de_prueba, estado_configuracion
    from app.models import Auditoria

    resultado = None
    destino = (request.form.get("destino") or current_user.email or "").strip()
    if request.method == "POST":
        if not AccionForm().validate_on_submit():
            abort(400)
        if "@" not in destino or len(destino) > 120:
            flash("Escribe un correo válido para la prueba.", "danger")
        else:
            enviado, motivo = correo_de_prueba(destino)
            resultado = {"enviado": enviado, "motivo": motivo, "destino": destino}
            registrar_accion("recuperacion", "Acceso",
                             (f"Prueba de correo enviada a «{destino}»" if enviado
                              else f"Prueba de correo fallida: {motivo}")[:300], usuario=current_user)
            db.session.commit()

    recientes = (Auditoria.query.filter(Auditoria.accion == "recuperacion")
                 .order_by(Auditoria.fecha.desc()).limit(12).all())
    return render_template("admin/correo.html", estado=estado_configuracion(), resultado=resultado,
                           destino=destino, recientes=recientes, accion_form=AccionForm())
