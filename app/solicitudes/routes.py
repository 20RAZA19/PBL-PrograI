"""Solicitudes de prendas: propuesta → aprobación → cotización → producción.

El cliente propone una prenda desde su portal. La empresa la revisa: la aprueba
con precios por cantidad (rebajas por mayoreo) y condiciones de cambio, o la
deniega con motivo. Al aprobarla se publica una cotización con vigencia limitada
que el cliente ve en su portal; los pedidos de producción se crean única y
exclusivamente cuando el cliente acepta esa cotización vigente.
"""
from datetime import date, datetime, timedelta

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.decorators import roles_required
from app.extensions import db
from app.forms import AccionForm
from app.models import (ESTADOS_SOLICITUD, ETIQUETAS_CONDICION, Cliente, Diseno, Pedido, Solicitud,
                        SolicitudLinea, SolicitudTramo)
from app.notificaciones.servicios import notificar, usuarios_con_rol, usuarios_del_cliente
from app.rastreo.servicios import nuevo_folio_pedido, registrar_evento
from app.solicitudes.forms import (AprobarForm, DeclinarForm, DenegarForm, SolicitudForm,
                                   leer_etiquetas, leer_lineas, leer_tramos)
from app.utils import generar_folio
from app.whatsapp.twilio import enviar_whatsapp


def _aviso_whatsapp(sol, texto):
    """Aviso saliente opcional (WHATSAPP_AVISOS=1 y Twilio configurado). Nunca interrumpe el flujo."""
    if not current_app.config.get("WHATSAPP_AVISOS"):
        return
    for u in usuarios_del_cliente(sol.cliente_id):
        if u.telefono_digitos:
            enviar_whatsapp(u.telefono_digitos, texto)

solicitudes = Blueprint("solicitudes", __name__)

TODOS = ("admin", "gestor", "ventas", "cliente")
MAX_ABIERTAS = 10  # propuestas sin revisar por empresa (evita saturar a Ventas)


def _visible_o_404(solicitud_id):
    sol = db.get_or_404(Solicitud, solicitud_id)
    if current_user.rol == "cliente" and sol.cliente_id != current_user.cliente_id:
        abort(404)  # no revelar que existe la solicitud de otra empresa
    return sol


def _disenos_del_cliente(cliente_id):
    if not cliente_id:
        return {}
    disenos = Diseno.query.filter_by(cliente_id=cliente_id, archivado=False).order_by(Diseno.nombre).all()
    return {d.id: d for d in disenos}


def _url(sol):
    return url_for("solicitudes.detalle", solicitud_id=sol.id)


def _vigencia_dias():
    return current_app.config.get("COTIZACION_VIGENCIA_DIAS", 15)


def _pagina_detalle(sol, aprobar_form=None, codigo=200):
    """Renderiza el detalle con todos sus formularios (y los valores escritos si hubo error)."""
    form = aprobar_form or AprobarForm(prefix="apro")
    if request.method == "GET" and not form.fecha_entrega.data:
        form.fecha_entrega.data = sol.fecha_entrega or (
            sol.fecha_deseada if sol.fecha_deseada and sol.fecha_deseada >= date.today() else None)
    pagina = render_template("solicitudes/detalle.html", sol=sol, accion_form=AccionForm(),
                             aprobar_form=form, denegar_form=DenegarForm(prefix="den"),
                             declinar_form=DeclinarForm(prefix="dec"), etiquetas_condicion=ETIQUETAS_CONDICION,
                             vigencia_dias=_vigencia_dias(),
                             valores=request.form if aprobar_form is not None else None)
    return (pagina, codigo) if codigo != 200 else pagina


@solicitudes.route("/")
@login_required
@roles_required(*TODOS)
def lista():
    estado = request.args.get("estado", "")
    q = request.args.get("q", "").strip()
    query = Solicitud.query.join(Cliente)
    if current_user.rol == "cliente":
        if not current_user.cliente_id:
            query = query.filter(db.false())
        else:
            query = query.filter(Solicitud.cliente_id == current_user.cliente_id)
    if estado in ESTADOS_SOLICITUD:
        query = query.filter(Solicitud.estado == estado)
    if q:
        query = query.filter(or_(Solicitud.folio.ilike(f"%{q}%"), Cliente.nombre.ilike(f"%{q}%")))
    todas = query.order_by(Solicitud.creado_en.desc()).limit(300).all()

    resumen = None
    if current_user.es_staff:
        resumen = {e: Solicitud.query.filter_by(estado=e).count() for e in ("enviada", "aprobada", "convertida")}
    return render_template("solicitudes/lista.html", solicitudes=todas, estado=estado, q=q,
                           estados=ESTADOS_SOLICITUD, resumen=resumen)


@solicitudes.route("/nueva", methods=["GET", "POST"])
@login_required
@roles_required("cliente")
def nueva():
    if not current_user.puede_solicitar:
        flash("Tu cuenta aún no está vinculada a una empresa aprobada. Contacta a Arte y Color para activarla.", "warn")
        return redirect(url_for("main.dashboard"))

    abiertas = Solicitud.query.filter_by(cliente_id=current_user.cliente_id, estado="enviada").count()
    if abiertas >= MAX_ABIERTAS:
        flash(f"Tu empresa ya tiene {abiertas} propuestas esperando revisión. "
              "Espera la respuesta de Ventas o retira alguna antes de enviar otra.", "warn")
        return redirect(url_for("solicitudes.lista"))

    disenos = _disenos_del_cliente(current_user.cliente_id)
    form = SolicitudForm()
    lineas = []
    if request.method == "GET":
        diseno = disenos.get(request.args.get("diseno_id", type=int))
        if diseno:
            lineas = [{"diseno_id": diseno.id, "descripcion": diseno.nombre, "tallas": diseno.tallas,
                       "cantidad": request.args.get("cantidad", type=int) or None}]
    else:
        lineas, errores = leer_lineas(request.form, disenos)
        valido = form.validate_on_submit()
        for e in errores:
            flash(e, "danger")
        if valido and not errores:
            sol = Solicitud(folio=generar_folio(Solicitud, "SOL"), cliente_id=current_user.cliente_id,
                            usuario=current_user, origen="portal", fecha_deseada=form.fecha_deseada.data,
                            notas=(form.notas.data or "").strip() or None)
            for l in lineas:
                sol.lineas.append(SolicitudLinea(**l))
            db.session.add(sol)
            db.session.flush()
            notificar(usuarios_con_rol("admin", "ventas"), "solicitud",
                      f"Nueva propuesta {sol.folio} de {sol.cliente.nombre}",
                      mensaje=f"{sol.total_prendas:,} prendas: {sol.resumen_prendas}. "
                              "Apruébala con sus precios por cantidad o deniégala con motivo.",
                      url=_url(sol), clave=f"sol-nueva-{sol.id}")
            db.session.commit()
            flash(f"Propuesta {sol.folio} enviada. Cuando la aprobemos verás la cotización en tu portal.", "ok")
            return redirect(_url(sol))

    return render_template("solicitudes/form.html", form=form, lineas=lineas,
                           disenos=[{"id": d.id, "nombre": d.nombre, "tallas": d.tallas or ""} for d in disenos.values()])


@solicitudes.route("/<int:solicitud_id>")
@login_required
@roles_required(*TODOS)
def detalle(solicitud_id):
    return _pagina_detalle(_visible_o_404(solicitud_id))


@solicitudes.route("/<int:solicitud_id>/aprobar", methods=["POST"])
@login_required
@roles_required("admin", "ventas")
def aprobar(solicitud_id):
    sol = db.get_or_404(Solicitud, solicitud_id)
    form = AprobarForm(prefix="apro")
    if sol.estado != "enviada":
        flash("Esta propuesta ya fue revisada.", "info")
        return redirect(_url(sol))
    tramos, errores = leer_tramos(request.form, sol)
    if not form.validate_on_submit() or errores:
        for e in errores + [m for campo in form.errors.values() for m in campo]:
            flash(e, "danger")
        return _pagina_detalle(sol, aprobar_form=form, codigo=400)

    for linea in sol.lineas:
        linea.tramos = [SolicitudTramo(desde_cantidad=d, precio_unitario=p) for d, p in tramos[linea.id]]
        linea.precio_unitario = linea.precio_para(linea.cantidad)
    sol.estado = "aprobada"
    sol.aprobada_en = datetime.now()
    sol.vence_en = date.today() + timedelta(days=_vigencia_dias())
    sol.fecha_entrega = form.fecha_entrega.data
    sol.condiciones = (form.condiciones.data or "").strip() or None
    sol.etiquetas = leer_etiquetas(request.form)
    sol.respuesta = (form.respuesta.data or "").strip() or None
    sol.respondida_en = datetime.now()
    sol.atendida_por = current_user
    con_condiciones = " con condiciones" if (sol.condiciones or sol.etiquetas) else ""
    notificar(usuarios_del_cliente(sol.cliente_id), "solicitud",
              f"Tu propuesta {sol.folio} fue aprobada{con_condiciones}",
              mensaje=f"Cotización por ${sol.total:,.2f} + IVA, vigente hasta el {sol.vence_en:%d/%m/%Y}. "
                      "Acéptala en tu portal para que entre a producción.",
              nivel="ok", url=_url(sol), clave=f"sol-aprobada-{sol.id}")
    db.session.commit()
    _aviso_whatsapp(sol, f"Arte y Color aprobó tu propuesta {sol.folio}{con_condiciones}. "
                         f"La cotización vence el {sol.vence_en:%d/%m/%Y}: acéptala en tu portal para que entre a producción.")
    flash(f"{sol.folio} aprobada. La cotización vence el {sol.vence_en:%d/%m/%Y}; "
          "los pedidos se crearán cuando el cliente la acepte.", "ok")
    return redirect(_url(sol))


@solicitudes.route("/<int:solicitud_id>/denegar", methods=["POST"])
@login_required
@roles_required("admin", "ventas")
def denegar(solicitud_id):
    sol = db.get_or_404(Solicitud, solicitud_id)
    form = DenegarForm(prefix="den")
    if sol.estado != "enviada":
        flash("Esta propuesta ya fue revisada; no se puede denegar.", "info")
        return redirect(_url(sol))
    if not form.validate_on_submit():
        flash("Escribe el motivo para que el cliente sepa por qué se deniega.", "danger")
        return redirect(_url(sol))
    sol.estado = "denegada"
    sol.respuesta = form.respuesta.data.strip()
    sol.respondida_en = datetime.now()
    sol.atendida_por = current_user
    notificar(usuarios_del_cliente(sol.cliente_id), "solicitud", f"Tu propuesta {sol.folio} fue denegada",
              mensaje=sol.respuesta[:200], nivel="warn", url=_url(sol), clave=f"sol-denegada-{sol.id}")
    db.session.commit()
    flash(f"{sol.folio} denegada. El cliente ya ve el motivo en su portal.", "info")
    return redirect(_url(sol))


@solicitudes.route("/<int:solicitud_id>/aceptar", methods=["POST"])
@login_required
@roles_required("cliente")
def aceptar(solicitud_id):
    """El cliente acepta la cotización: SOLO entonces (y solo si está aprobada y
    vigente) se crean los pedidos de producción."""
    sol = _visible_o_404(solicitud_id)
    if not AccionForm().validate_on_submit():
        abort(400)
    if sol.estado != "aprobada":
        flash("Solo puedes aceptar una cotización aprobada. Una propuesta pendiente o denegada no entra a producción.", "warn")
        return redirect(_url(sol))
    if not sol.vigente:
        flash(f"Esta cotización venció el {sol.vence_en:%d/%m/%Y}. Escríbenos y la renovamos con precios al día.", "warn")
        return redirect(_url(sol))
    if sol.pedidos:
        flash("Esta cotización ya generó sus pedidos.", "info")
        return redirect(_url(sol))

    limite = max(sol.fecha_entrega or date.today(), date.today())
    folios = []
    for l in sol.lineas:
        detalle_medidas = f" Medidas/indicaciones: {l.medidas}" if l.medidas else ""
        pedido = Pedido(folio=nuevo_folio_pedido(), cliente_id=sol.cliente_id, diseno=l.diseno,
                        modelo_prenda=l.descripcion, tallas=l.tallas, colores=l.colores, cantidad=l.cantidad,
                        precio_unitario=l.precio_unitario, fecha_limite=limite, solicitud=sol,
                        observaciones=f"Cotización {sol.folio} aceptada por el cliente.{detalle_medidas}")
        db.session.add(pedido)
        db.session.flush()
        registrar_evento(pedido, estado="Recibido", ubicacion="Taller Principal",
                         nota=f"Orden creada al aceptar el cliente la cotización {sol.folio}.", usuario=current_user)
        folios.append(pedido.folio)
    sol.estado = "convertida"
    sol.decidida_en = datetime.now()
    notificar(usuarios_con_rol("admin", "ventas", "gestor"), "solicitud",
              f"{sol.cliente.nombre} aceptó la cotización {sol.folio}",
              mensaje=f"{', '.join(folios)} entraron a producción por ${sol.total:,.2f} + IVA.",
              nivel="ok", url=url_for("main.kanban_pedidos"), clave=f"sol-aceptada-{sol.id}")
    db.session.commit()
    flash(f"¡Gracias! Se crearon {len(folios)} pedido(s): {', '.join(folios)}. Puedes rastrearlos desde tu portal.", "ok")
    return redirect(_url(sol))


@solicitudes.route("/<int:solicitud_id>/declinar", methods=["POST"])
@login_required
@roles_required("cliente")
def declinar(solicitud_id):
    sol = _visible_o_404(solicitud_id)
    form = DeclinarForm(prefix="dec")
    if sol.estado != "aprobada" or not form.validate_on_submit():
        flash("Solo puedes declinar una cotización publicada.", "warn")
        return redirect(_url(sol))
    sol.estado = "declinada"
    sol.motivo_cliente = (form.motivo.data or "").strip() or None
    sol.decidida_en = datetime.now()
    notificar(usuarios_con_rol("admin", "ventas"), "solicitud",
              f"{sol.cliente.nombre} declinó la cotización {sol.folio}",
              mensaje=(sol.motivo_cliente or f"${sol.total:,.2f} + IVA en {sol.total_prendas:,} prendas.")[:200],
              nivel="warn", url=_url(sol), clave=f"sol-declinada-{sol.id}")
    db.session.commit()
    flash(f"Cotización {sol.folio} declinada. Si cambias de opinión, envía una nueva propuesta.", "info")
    return redirect(_url(sol))


@solicitudes.route("/<int:solicitud_id>/renovar", methods=["POST"])
@login_required
@roles_required("admin", "ventas")
def renovar(solicitud_id):
    """Vuelve a poner en vigencia una cotización vencida (o extiende una vigente)."""
    sol = db.get_or_404(Solicitud, solicitud_id)
    if not AccionForm().validate_on_submit():
        abort(400)
    if sol.estado != "aprobada":
        flash("Solo se renueva la vigencia de una cotización aprobada.", "warn")
        return redirect(_url(sol))
    sol.vence_en = date.today() + timedelta(days=_vigencia_dias())
    notificar(usuarios_del_cliente(sol.cliente_id), "solicitud", f"Renovamos la cotización {sol.folio}",
              mensaje=f"Vuelve a estar vigente hasta el {sol.vence_en:%d/%m/%Y}. Acéptala en tu portal.",
              nivel="ok", url=_url(sol), clave=f"sol-renovada-{sol.id}-{sol.vence_en:%Y%m%d}")
    db.session.commit()
    flash(f"Vigencia renovada hasta el {sol.vence_en:%d/%m/%Y}. El cliente ya recibió el aviso.", "ok")
    return redirect(_url(sol))


@solicitudes.route("/<int:solicitud_id>/cancelar", methods=["POST"])
@login_required
@roles_required("cliente")
def cancelar(solicitud_id):
    sol = _visible_o_404(solicitud_id)
    if not AccionForm().validate_on_submit():
        abort(400)
    if not sol.cancelable:
        flash("Esta propuesta ya fue revisada. Si tiene una cotización publicada puedes declinarla; "
              "para cualquier otro cambio contacta a Ventas.", "warn")
        return redirect(_url(sol))
    sol.estado = "cancelada"
    sol.respondida_en = sol.respondida_en or datetime.now()
    notificar(usuarios_con_rol("admin", "ventas"), "solicitud", f"{sol.cliente.nombre} retiró {sol.folio}",
              mensaje=f"{sol.total_prendas:,} prendas: {sol.resumen_prendas}.", nivel="warn", url=_url(sol),
              clave=f"sol-cancelada-{sol.id}")
    db.session.commit()
    flash(f"Propuesta {sol.folio} retirada.", "info")
    return redirect(url_for("solicitudes.lista"))
