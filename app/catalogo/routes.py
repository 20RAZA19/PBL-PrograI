from flask import Blueprint, render_template, request, abort, flash, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.archivos import ImagenInvalida, eliminar_imagen, guardar_imagen
from app.catalogo.forms import DisenoForm, leer_ficha
from app.extensions import db
from app.forms import AccionForm
from app.models import Diseno, DisenoTela, Cliente, Insumo, Pedido
from app.decorators import roles_required

catalogo = Blueprint("catalogo", __name__)


def _disenos_visibles(archivados=False):
    query = Diseno.query.filter(Diseno.archivado.is_(archivados))
    if current_user.rol == "cliente":
        if current_user.cliente_id is None:
            return query.filter(db.false())
        query = query.filter(Diseno.cliente_id == current_user.cliente_id)
    return query


@catalogo.route("/")
@login_required
@roles_required("admin", "gestor", "ventas", "cliente")
def lista():
    q = request.args.get("q", "").strip()
    cliente_id = request.args.get("cliente", type=int)
    archivados = request.args.get("archivados") == "1" and current_user.es_staff

    query = _disenos_visibles(archivados)
    if q:
        query = query.filter(or_(Diseno.nombre.ilike(f"%{q}%"),
                                 Diseno.tipo_prenda.ilike(f"%{q}%")))
    if cliente_id and current_user.es_staff:
        query = query.filter(Diseno.cliente_id == cliente_id)

    disenos = query.order_by(Diseno.creado_en.desc()).all()
    clientes = Cliente.query.order_by(Cliente.nombre).all() if current_user.es_staff else []
    return render_template("catalogo/lista.html", disenos=disenos, q=q, archivados=archivados,
                           clientes=clientes, cliente_id=cliente_id)


@catalogo.route("/<int:diseno_id>")
@login_required
@roles_required("admin", "gestor", "ventas", "cliente")
def detalle(diseno_id):
    diseno = db.get_or_404(Diseno, diseno_id)
    if current_user.rol == "cliente" and (
        current_user.cliente_id is None or diseno.cliente_id != current_user.cliente_id
    ):
        abort(403)

    pedidos = (Pedido.query.filter_by(diseno_id=diseno.id)
               .order_by(Pedido.creado_en.desc()).all())
    cantidad = request.args.get("cantidad", type=int) or (pedidos[0].cantidad if pedidos else 100)
    cantidad = max(1, min(cantidad, 100000))

    consumo = []
    for dt in diseno.telas:
        requeridos = float(dt.metros_por_unidad or 0) * cantidad
        disponibles = float(dt.tela.cantidad_disponible or 0)
        consumo.append({
            "tela": dt.tela,
            "por_unidad": float(dt.metros_por_unidad or 0),
            "requeridos": requeridos,
            "disponibles": disponibles,
            "alcanza": disponibles >= requeridos,
        })

    return render_template("catalogo/detalle.html", diseno=diseno, pedidos=pedidos,
                           consumo=consumo, cantidad=cantidad, accion_form=AccionForm())


def _insumos_para_ficha():
    return [{"id": i.id, "nombre": i.nombre, "categoria": i.categoria, "unidad": i.unidad_medida,
             "costo": float(i.costo_unitario or 0), "color": i.color_hex}
            for i in Insumo.query.filter(Insumo.activo.is_(True)).order_by(Insumo.categoria, Insumo.nombre).all()]


def _guardar_diseno(form, diseno):
    filas, errores = leer_ficha(request.form)
    valido = form.validate_on_submit()
    for e in errores:
        flash(e, "danger")
    if not valido or errores:
        return False

    nueva_imagen = None
    if form.imagen.data and getattr(form.imagen.data, "filename", ""):
        try:
            nueva_imagen = guardar_imagen(form.imagen.data, "disenos")
        except ImagenInvalida as e:
            form.imagen.errors.append(str(e))
            return False

    diseno.nombre = form.nombre.data.strip()
    diseno.cliente_id = form.cliente_id.data or None
    diseno.tipo_prenda = (form.tipo_prenda.data or "").strip() or None
    diseno.tallas = (form.tallas.data or "").strip() or None
    diseno.precio_venta = form.precio_venta.data
    diseno.costo_mano_obra = form.costo_mano_obra.data or 0
    if nueva_imagen:
        eliminar_imagen(diseno.imagen)
        diseno.imagen = nueva_imagen
    elif form.quitar_imagen.data and diseno.imagen:
        eliminar_imagen(diseno.imagen)
        diseno.imagen = None

    actuales = {dt.tela_id: dt for dt in diseno.telas}
    nuevos = dict(filas)
    for tela_id, dt in actuales.items():
        if tela_id not in nuevos:
            diseno.telas.remove(dt)
    for tela_id, cantidad in filas:
        if tela_id in actuales:
            actuales[tela_id].metros_por_unidad = cantidad
        elif db.session.get(Insumo, tela_id):
            diseno.telas.append(DisenoTela(tela_id=tela_id, metros_por_unidad=cantidad))
    return True


def _preparar(form):
    form.cliente_id.choices = [(0, "— Diseño general (sin cliente) —")] + [
        (c.id, c.nombre) for c in Cliente.query.order_by(Cliente.nombre).all()]


@catalogo.route("/nuevo", methods=["GET", "POST"])
@login_required
@roles_required("admin", "gestor", "ventas")
def nuevo():
    form = DisenoForm()
    _preparar(form)
    if request.method == "GET":
        form.cliente_id.data = request.args.get("cliente_id", type=int) or 0
    if request.method == "POST":
        diseno = Diseno()
        if _guardar_diseno(form, diseno):
            db.session.add(diseno)
            db.session.commit()
            flash(f"Diseño «{diseno.nombre}» registrado.", "ok")
            return redirect(url_for("catalogo.detalle", diseno_id=diseno.id))
        db.session.rollback()
    ficha = [{"insumo_id": int(i) if i.isdigit() else None, "cantidad": c}
             for i, c in zip(request.form.getlist("ficha_insumo"), request.form.getlist("ficha_cantidad"))]
    return render_template("catalogo/form.html", form=form, diseno=None, ficha=ficha,
                           insumos=_insumos_para_ficha(), titulo="Nuevo Diseño")


@catalogo.route("/<int:diseno_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("admin", "gestor", "ventas")
def editar(diseno_id):
    diseno = db.get_or_404(Diseno, diseno_id)
    form = DisenoForm(obj=diseno)
    _preparar(form)
    if request.method == "GET":
        form.cliente_id.data = diseno.cliente_id or 0
    if request.method == "POST":
        if _guardar_diseno(form, diseno):
            db.session.commit()
            flash("Diseño actualizado.", "ok")
            return redirect(url_for("catalogo.detalle", diseno_id=diseno.id))
        db.session.rollback()
        ficha = [{"insumo_id": int(i) if i.isdigit() else None, "cantidad": c}
                 for i, c in zip(request.form.getlist("ficha_insumo"), request.form.getlist("ficha_cantidad"))]
    else:
        ficha = [{"insumo_id": dt.tela_id, "cantidad": dt.metros_por_unidad} for dt in diseno.telas]
    return render_template("catalogo/form.html", form=form, diseno=diseno, ficha=ficha,
                           insumos=_insumos_para_ficha(), titulo=f"Editar {diseno.nombre}")


@catalogo.route("/<int:diseno_id>/archivar", methods=["POST"])
@login_required
@roles_required("admin", "gestor", "ventas")
def archivar(diseno_id):
    diseno = db.get_or_404(Diseno, diseno_id)
    if not AccionForm().validate_on_submit():
        abort(400)
    diseno.archivado = not diseno.archivado
    db.session.commit()
    flash("Diseño archivado: ya no aparece en el catálogo." if diseno.archivado else "Diseño restaurado.", "ok")
    return redirect(url_for("catalogo.lista") if diseno.archivado else url_for("catalogo.detalle", diseno_id=diseno.id))
