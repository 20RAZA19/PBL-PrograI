from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.archivos import ImagenInvalida, eliminar_imagen, guardar_imagen
from app.extensions import db
from app.models import Insumo, Movimiento, Proveedor
from app.decorators import roles_required
from app.forms import AccionForm
from app.telas.forms import TelaForm, NuevaTelaForm, MovimientoForm, DEFAULTS_CATEGORIA, normalizar_hex, normalizar_pantone

PREFIJOS = {"Tela": "TEL", "Hilo": "HIL", "Botón": "BOT", "Cierre": "CIE", "Elástico": "ELA", "Etiqueta": "ETI", "Otro": "INS"}

telas = Blueprint("telas", __name__)


def _preparar(form):
    form.proveedor_id.choices = [(0, "— Sin proveedor asignado —")] + [
        (p.id, p.nombre) for p in Proveedor.query.order_by(Proveedor.nombre).all()]


def _aplicar_extras(form, tela):
    """Costo, proveedor y foto. Devuelve False si la imagen no es válida."""
    tela.costo_unitario = form.costo_unitario.data or 0
    tela.proveedor_id = form.proveedor_id.data or None
    archivo = form.imagen.data
    if archivo and getattr(archivo, "filename", ""):
        try:
            ruta = guardar_imagen(archivo, "insumos")
        except ImagenInvalida as e:
            form.imagen.errors.append(str(e))
            return False
        eliminar_imagen(tela.imagen)
        tela.imagen = ruta
    elif form.quitar_imagen.data and tela.imagen:
        eliminar_imagen(tela.imagen)
        tela.imagen = None
    return True


@telas.route("/")
@login_required
@roles_required("admin", "gestor", "ventas")
def lista():
    q = request.args.get("q", "")
    estado = request.args.get("estado", "")
    ver_inactivos = request.args.get("inactivos") == "1"
    categoria = request.args.get("categoria", "")

    query = Insumo.query
    if not ver_inactivos:
        query = query.filter(Insumo.activo.is_(True))

    if q:
        query = query.filter(
            or_(
                Insumo.nombre.ilike(f"%{q}%"),
                Insumo.codigo.ilike(f"%{q}%"),
                Insumo.categoria.ilike(f"%{q}%"),
                Insumo.codigo_pantone.ilike(f"%{q}%"),
            )
        )

    if categoria:
        query = query.filter(Insumo.categoria == categoria)
    insumos = query.order_by(Insumo.categoria, Insumo.nombre).all()

    if estado:
        insumos = [i for i in insumos if i.estado == estado]

    categorias = [c for (c,) in db.session.query(Insumo.categoria).distinct().order_by(Insumo.categoria)]
    return render_template("telas/lista.html", telas=insumos, q=q, estado=estado,
                           ver_inactivos=ver_inactivos, categoria=categoria, categorias=categorias)


@telas.route("/nueva", methods=["GET", "POST"])
@login_required
@roles_required("admin", "gestor")
def nueva():
    form = NuevaTelaForm()
    _preparar(form)
    if request.method == "GET":
        # HU-01.3: si la búsqueda no encontró el insumo, se precarga su nombre
        form.nombre.data = request.args.get("nombre", "") or None
        categoria = request.args.get("categoria")
        if categoria in DEFAULTS_CATEGORIA:
            form.categoria.data = categoria
            form.unidad_medida.data = DEFAULTS_CATEGORIA[categoria]["unidad"]
            form.stock_minimo.data = DEFAULTS_CATEGORIA[categoria]["minimo"]
    if form.validate_on_submit():
        tela = Insumo(
            nombre=form.nombre.data.strip(),
            categoria=form.categoria.data,
            unidad_medida=form.unidad_medida.data,
            tipo=form.tipo.data or "Textil",
            codigo_pantone=(form.codigo_pantone.data or "").strip() or None,
            color_hex=normalizar_hex(form.color_hex.data),
            stock_minimo=form.stock_minimo.data,
            cantidad_disponible=0,
        )
        if not _aplicar_extras(form, tela):
            return render_template("telas/form.html", form=form, titulo="Registrar Nuevo Insumo",
                                   volver=url_for("telas.lista"), defaults=DEFAULTS_CATEGORIA, tela=None)
        db.session.add(tela)
        db.session.flush()
        tela.codigo = f"{PREFIJOS.get(tela.categoria, 'INS')}-{tela.id:04d}"

        iniciales = form.metros_iniciales.data or 0
        if iniciales > 0:
            tela.cantidad_disponible = iniciales
            db.session.add(Movimiento(
                tipo="entrada", cantidad=iniciales, metros=iniciales,
                motivo="Inventario inicial", insumo=tela, usuario_id=current_user.id,
            ))
        db.session.commit()
        flash(f"«{tela.nombre}» registrado con el código {tela.codigo}.", "ok")
        return redirect(url_for("telas.detalle", tela_id=tela.id))

    return render_template("telas/form.html", form=form, titulo="Registrar Nuevo Insumo",
                           volver=url_for("telas.lista"), defaults=DEFAULTS_CATEGORIA, tela=None)


@telas.route("/<int:tela_id>")
@login_required
@roles_required("admin", "gestor", "ventas")
def detalle(tela_id):
    tela = db.get_or_404(Insumo, tela_id)
    movimientos = (Movimiento.query.filter_by(insumo_id=tela.id)
                   .order_by(Movimiento.fecha.desc()).all())
    return render_template("telas/detalle.html", tela=tela, movimientos=movimientos,
                           accion_form=AccionForm())


@telas.route("/<int:tela_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("admin", "gestor")
def editar(tela_id):
    tela = db.get_or_404(Insumo, tela_id)
    form = TelaForm(obj=tela, insumo_id=tela.id)
    _preparar(form)
    if request.method == "GET":
        form.proveedor_id.data = tela.proveedor_id or 0
    if form.validate_on_submit() and _aplicar_extras(form, tela):
        tela.nombre = form.nombre.data.strip()
        tela.categoria = form.categoria.data
        tela.unidad_medida = form.unidad_medida.data
        tela.tipo = form.tipo.data or "Textil"
        tela.codigo_pantone = (form.codigo_pantone.data or "").strip() or None
        tela.color_hex = normalizar_hex(form.color_hex.data)
        tela.stock_minimo = form.stock_minimo.data
        db.session.commit()
        flash("Cambios guardados.", "ok")
        return redirect(url_for("telas.detalle", tela_id=tela.id))

    return render_template("telas/form.html", form=form, titulo=f"Editar {tela.nombre}",
                           volver=url_for("telas.detalle", tela_id=tela.id), defaults=DEFAULTS_CATEGORIA, tela=tela)


@telas.route("/movimiento", methods=["GET", "POST"])
@telas.route("/movimiento/<tipo>", methods=["GET", "POST"])
@login_required
@roles_required("admin", "gestor")
def movimiento(tipo=None):
    form = MovimientoForm()
    activas = Insumo.query.filter(Insumo.activo.is_(True)).order_by(Insumo.nombre).all()
    form.tela_id.choices = [
        (t.id, f"{t.nombre} — {float(t.cantidad_disponible or 0):,.2f} {t.unidad_medida.lower()}") for t in activas
    ]

    if request.method == "GET":
        tipo = tipo or request.args.get("tipo", "entrada")
        if tipo in ("entrada", "salida"):
            form.tipo.data = tipo
        tela_id = request.args.get("tela_id", type=int)
        if tela_id:
            form.tela_id.data = tela_id

    if form.validate_on_submit():
        tela = db.session.get(Insumo, form.tela_id.data)
        if tela is None or not tela.activo:
            abort(404)
        metros = form.metros.data

        if form.tipo.data == "salida" and metros > tela.cantidad_disponible:
            form.metros.errors.append(
                f"Solo hay {float(tela.cantidad_disponible):,.2f} {tela.unidad_medida.lower()} disponibles."
            )
        else:
            if form.tipo.data == "entrada":
                tela.cantidad_disponible += metros
            else:
                tela.cantidad_disponible -= metros
            db.session.add(Movimiento(
                tipo=form.tipo.data, cantidad=metros, metros=metros,
                motivo=form.motivo.data or None, insumo=tela, usuario_id=current_user.id,
            ))
            db.session.commit()
            accion = "Entrada" if form.tipo.data == "entrada" else "Salida"
            flash(f"{accion} de {float(metros):,.2f} {tela.unidad_medida.lower()} registrada en «{tela.nombre}».", "ok")
            return redirect(url_for("telas.detalle", tela_id=tela.id))

    return render_template("telas/movimiento.html", form=form)


@telas.route("/<int:tela_id>/desactivar", methods=["POST"])
@login_required
@roles_required("admin", "gestor")
def desactivar(tela_id):
    tela = db.get_or_404(Insumo, tela_id)
    form = AccionForm()
    if form.validate_on_submit():
        tela.activo = False
        db.session.commit()
        flash(f"«{tela.nombre}» fue desactivada. Su historial se conserva.", "ok")
    return redirect(url_for("telas.lista"))


@telas.route("/<int:tela_id>/reactivar", methods=["POST"])
@login_required
@roles_required("admin", "gestor")
def reactivar(tela_id):
    tela = db.get_or_404(Insumo, tela_id)
    form = AccionForm()
    if form.validate_on_submit():
        tela.activo = True
        db.session.commit()
        flash(f"«{tela.nombre}» vuelve a estar activa.", "ok")
    return redirect(url_for("telas.detalle", tela_id=tela.id))
