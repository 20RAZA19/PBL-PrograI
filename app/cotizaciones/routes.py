from datetime import date, datetime, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.cotizaciones.forms import CotizacionForm, leer_lineas
from app.decorators import roles_required
from app.documentos import documento_cotizacion, respuesta_documento
from app.extensions import db
from app.forms import AccionForm
from app.models import (ESTADOS_COTIZACION, Cliente, Cotizacion, CotizacionLinea, Diseno, Pedido)
from app.notificaciones.servicios import notificar, usuarios_con_rol, usuarios_del_cliente
from app.rastreo.servicios import nuevo_folio_pedido, registrar_evento
from app.utils import generar_folio

cotizaciones = Blueprint("cotizaciones", __name__)

TODOS = ("admin", "gestor", "ventas", "cliente")


def _visible_o_404(cotizacion_id):
    cot = db.get_or_404(Cotizacion, cotizacion_id)
    if current_user.rol == "cliente":
        if cot.cliente_id != current_user.cliente_id or cot.estado == "borrador":
            abort(404)
    return cot


def _disenos_para_selector():
    disenos = Diseno.query.filter(Diseno.archivado.is_(False)).order_by(Diseno.nombre).all()
    return [{"id": d.id, "nombre": d.nombre, "cliente_id": d.cliente_id, "tallas": d.tallas or "",
             "precio": float(d.precio_venta) if d.tiene_precio else None,
             "costo": float(d.costo_por_prenda)} for d in disenos]


def _preparar_form(form):
    form.cliente_id.choices = [(c.id, c.nombre) for c in Cliente.query.order_by(Cliente.nombre).all()]


@cotizaciones.route("/")
@login_required
@roles_required(*TODOS)
def lista():
    estado = request.args.get("estado", "")
    q = request.args.get("q", "").strip()
    query = Cotizacion.query.join(Cliente)
    if current_user.rol == "cliente":
        query = query.filter(Cotizacion.cliente_id == current_user.cliente_id, Cotizacion.estado != "borrador")
    if estado in ESTADOS_COTIZACION:
        query = query.filter(Cotizacion.estado == estado)
    if q:
        query = query.filter(or_(Cotizacion.folio.ilike(f"%{q}%"), Cliente.nombre.ilike(f"%{q}%")))
    lista_cot = query.order_by(Cotizacion.creado_en.desc()).all()

    # Cotizaciones nacidas de solicitudes aprobadas: el cliente decide desde aquí también
    sol_cotizadas = []
    if current_user.rol == "cliente" and current_user.cliente_id:
        from app.models import Solicitud
        sol_cotizadas = (Solicitud.query.filter_by(cliente_id=current_user.cliente_id, estado="aprobada")
                         .order_by(Solicitud.aprobada_en.desc()).limit(20).all())

    resumen = None
    if current_user.es_staff:
        todas = Cotizacion.query.all()
        respondidas = [c for c in todas if c.estado in ("aceptada", "rechazada")]
        aceptadas = [c for c in todas if c.estado == "aceptada"]
        resumen = {
            "abiertas": sum(1 for c in todas if c.estado == "enviada" and not c.vencida),
            "monto_abierto": sum((c.total for c in todas if c.estado == "enviada" and not c.vencida), 0),
            "conversion": round(len(aceptadas) / len(respondidas) * 100) if respondidas else None,
            "monto_aceptado": sum((c.total for c in aceptadas), 0),
        }
    return render_template("cotizaciones/lista.html", cotizaciones=lista_cot, estado=estado, q=q,
                           estados=ESTADOS_COTIZACION, resumen=resumen, sol_cotizadas=sol_cotizadas)


def _guardar(form, cot=None):
    """Valida cabecera + líneas y guarda. Devuelve la cotización o None si hubo errores."""
    lineas, errores = leer_lineas(request.form)
    form_ok = form.validate_on_submit()
    if errores or not form_ok:
        for e in errores:
            flash(e, "danger")
        return None, lineas

    nueva = cot is None
    if nueva:
        cot = Cotizacion(folio=generar_folio(Cotizacion, "COT"), usuario=current_user, fecha=date.today())
        db.session.add(cot)
    cot.cliente_id = form.cliente_id.data
    cot.fecha_entrega = form.fecha_entrega.data
    cot.validez_dias = form.validez_dias.data
    cot.descuento_pct = form.descuento_pct.data
    cot.iva_pct = form.iva_pct.data
    cot.condiciones = (form.condiciones.data or "").strip() or None
    cot.notas = (form.notas.data or "").strip() or None
    cot.lineas.clear()
    for l in lineas:
        diseno = db.session.get(Diseno, l["diseno_id"]) if l["diseno_id"] else None
        cot.lineas.append(CotizacionLinea(diseno=diseno, descripcion=l["descripcion"], tallas=l["tallas"],
                                          cantidad=l["cantidad"], precio_unitario=l["precio_unitario"]))
    db.session.commit()
    return cot, lineas


@cotizaciones.route("/nueva", methods=["GET", "POST"])
@login_required
@roles_required("admin", "ventas")
def nueva():
    form = CotizacionForm()
    _preparar_form(form)
    if not form.cliente_id.choices:
        flash("Registra primero al cliente para poder cotizarle.", "info")
        return redirect(url_for("contactos.nuevo_cliente"))
    lineas = []
    if request.method == "GET":
        form.cliente_id.data = request.args.get("cliente_id", type=int)
        diseno = db.session.get(Diseno, request.args.get("diseno_id", type=int) or 0)
        if diseno:
            form.cliente_id.data = form.cliente_id.data or diseno.cliente_id
            lineas = [{"diseno_id": diseno.id, "descripcion": diseno.nombre, "tallas": diseno.tallas,
                       "cantidad": request.args.get("cantidad", type=int) or 100,
                       "precio_unitario": diseno.precio_venta}]
    else:
        cot, lineas = _guardar(form)
        if cot:
            flash(f"Cotización {cot.folio} guardada como borrador.", "ok")
            return redirect(url_for("cotizaciones.detalle", cotizacion_id=cot.id))
    return render_template("cotizaciones/form.html", form=form, lineas=lineas, cot=None,
                           disenos=_disenos_para_selector(), titulo="Nueva Cotización")


@cotizaciones.route("/<int:cotizacion_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("admin", "ventas")
def editar(cotizacion_id):
    cot = db.get_or_404(Cotizacion, cotizacion_id)
    if not cot.editable:
        flash("Solo se pueden editar cotizaciones en borrador. Usa «Duplicar» para crear una nueva versión.", "warn")
        return redirect(url_for("cotizaciones.detalle", cotizacion_id=cot.id))
    form = CotizacionForm(obj=cot)
    _preparar_form(form)
    lineas = [{"diseno_id": l.diseno_id, "descripcion": l.descripcion, "tallas": l.tallas,
               "cantidad": l.cantidad, "precio_unitario": l.precio_unitario} for l in cot.lineas]
    if request.method == "POST":
        guardada, lineas = _guardar(form, cot)
        if guardada:
            flash("Cotización actualizada.", "ok")
            return redirect(url_for("cotizaciones.detalle", cotizacion_id=cot.id))
    return render_template("cotizaciones/form.html", form=form, lineas=lineas, cot=cot,
                           disenos=_disenos_para_selector(), titulo=f"Editar {cot.folio}")


@cotizaciones.route("/<int:cotizacion_id>")
@login_required
@roles_required(*TODOS)
def detalle(cotizacion_id):
    cot = _visible_o_404(cotizacion_id)
    return render_template("cotizaciones/detalle.html", cot=cot, accion_form=AccionForm())


@cotizaciones.route("/<int:cotizacion_id>/pdf")
@login_required
@roles_required(*TODOS)
def pdf(cotizacion_id):
    cot = _visible_o_404(cotizacion_id)
    return respuesta_documento(documento_cotizacion(cot), descargar=request.args.get("descargar") == "1")


@cotizaciones.route("/<int:cotizacion_id>/<accion>", methods=["POST"])
@login_required
@roles_required(*TODOS)
def accion(cotizacion_id, accion):
    cot = _visible_o_404(cotizacion_id)
    if not AccionForm().validate_on_submit():
        abort(400)
    detalle_url = url_for("cotizaciones.detalle", cotizacion_id=cot.id)
    es_cliente = current_user.rol == "cliente"
    vendedor = current_user.puede_cotizar

    if accion == "enviar" and vendedor and cot.estado == "borrador":
        if not cot.lineas:
            flash("La cotización no tiene prendas.", "warn")
            return redirect(detalle_url)
        cot.estado = "enviada"
        cot.fecha = date.today()  # la validez corre desde el envío
        notificar(usuarios_del_cliente(cot.cliente_id), "cotizacion",
                  f"Nueva cotización {cot.folio}",
                  mensaje=f"{cot.total_prendas:,} prendas · total ${cot.total:,.2f}. Revísala y respóndenos desde el portal.",
                  url=detalle_url, clave=f"cot-enviada-{cot.id}")
        flash(f"{cot.folio} marcada como enviada. El cliente ya la ve en su portal; descarga el PDF para enviarla por correo.", "ok")

    elif accion in ("aceptar", "rechazar") and (vendedor or es_cliente) and cot.estado == "enviada":
        if cot.vencida:
            flash("La cotización está vencida. Pide una nueva versión.", "warn")
            return redirect(detalle_url)
        cot.estado = "aceptada" if accion == "aceptar" else "rechazada"
        cot.respondida_en = datetime.now()
        if es_cliente:
            notificar(usuarios_con_rol("admin", "ventas") + ([cot.usuario] if cot.usuario else []), "cotizacion",
                      f"{cot.cliente.nombre} {'aceptó' if accion == 'aceptar' else 'rechazó'} {cot.folio}",
                      mensaje=f"Total ${cot.total:,.2f} · {cot.total_prendas:,} prendas.",
                      nivel="ok" if accion == "aceptar" else "warn", url=detalle_url,
                      clave=f"cot-respuesta-{cot.id}")
        flash("¡Cotización aceptada!" if accion == "aceptar" else "Cotización marcada como rechazada.",
              "ok" if accion == "aceptar" else "info")

    elif accion == "convertir" and current_user.puede_crear_pedidos and cot.estado == "aceptada":
        if cot.pedidos:
            flash("Esta cotización ya generó sus pedidos.", "info")
            return redirect(detalle_url)
        limite = cot.fecha_entrega if cot.fecha_entrega and cot.fecha_entrega >= date.today() \
            else date.today() + timedelta(days=30)
        folios = []
        for l in cot.lineas:
            pedido = Pedido(folio=nuevo_folio_pedido(), cliente_id=cot.cliente_id, diseno=l.diseno,
                            modelo_prenda=l.descripcion, tallas=l.tallas, cantidad=l.cantidad,
                            precio_unitario=l.precio_unitario, fecha_limite=limite, cotizacion=cot,
                            colores=None, observaciones=f"Generado desde la cotización {cot.folio}.")
            db.session.add(pedido)
            db.session.flush()
            registrar_evento(pedido, estado="Recibido", ubicacion="Taller Principal",
                             nota=f"Orden creada a partir de {cot.folio}.", usuario=current_user)
            folios.append(pedido.folio)
        flash(f"Se crearon {len(folios)} pedido(s): {', '.join(folios)}.", "ok")

    elif accion == "duplicar" and vendedor:
        copia = Cotizacion(folio=generar_folio(Cotizacion, "COT"), cliente_id=cot.cliente_id, usuario=current_user,
                           fecha=date.today(), validez_dias=cot.validez_dias, descuento_pct=cot.descuento_pct,
                           iva_pct=cot.iva_pct, condiciones=cot.condiciones, notas=cot.notas,
                           fecha_entrega=cot.fecha_entrega if cot.fecha_entrega and cot.fecha_entrega >= date.today() else None)
        for l in cot.lineas:
            copia.lineas.append(CotizacionLinea(diseno_id=l.diseno_id, descripcion=l.descripcion, tallas=l.tallas,
                                                cantidad=l.cantidad, precio_unitario=l.precio_unitario))
        db.session.add(copia)
        db.session.commit()
        flash(f"Se creó {copia.folio} como copia en borrador.", "ok")
        return redirect(url_for("cotizaciones.editar", cotizacion_id=copia.id))

    elif accion == "eliminar" and vendedor and cot.estado == "borrador":
        db.session.delete(cot)
        db.session.commit()
        flash("Borrador eliminado.", "info")
        return redirect(url_for("cotizaciones.lista"))
    else:
        if es_cliente:
            abort(403)
        flash("Esa acción no aplica al estado actual de la cotización o a tu rol.", "warn")
        return redirect(detalle_url)

    db.session.commit()
    return redirect(detalle_url)
