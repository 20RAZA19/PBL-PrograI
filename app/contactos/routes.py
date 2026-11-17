"""Módulo de Contactos (RF-04): directorio de clientes y proveedores con historial de notas."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import or_

from app.extensions import db
from app.models import Cliente, Proveedor, NotaContacto, Pedido
from app.decorators import roles_required
from app.contactos.forms import ClienteForm, ProveedorForm, NotaForm

contactos = Blueprint("contactos", __name__)

TIPOS = {
    "clientes": {"modelo": Cliente, "form": ClienteForm, "singular": "cliente", "icono": "building-2"},
    "proveedores": {"modelo": Proveedor, "form": ProveedorForm, "singular": "proveedor", "icono": "truck"},
}


def _tipo_o_404(tipo):
    if tipo not in TIPOS:
        abort(404)
    return TIPOS[tipo]


@contactos.route("/")
@login_required
@roles_required("admin", "gestor", "ventas")
def lista():
    tab = request.args.get("tab", "clientes")
    if tab not in TIPOS:
        tab = "clientes"
    q = request.args.get("q", "").strip()
    modelo = TIPOS[tab]["modelo"]

    query = modelo.query
    if q:
        filtros = [modelo.nombre.ilike(f"%{q}%"), modelo.contacto.ilike(f"%{q}%"),
                   modelo.email.ilike(f"%{q}%"), modelo.telefono.ilike(f"%{q}%")]
        if modelo is Proveedor:
            filtros.append(Proveedor.rubro.ilike(f"%{q}%"))
        query = query.filter(or_(*filtros))
    registros = query.order_by(modelo.nombre).all()

    totales = {"clientes": Cliente.query.count(), "proveedores": Proveedor.query.count()}
    return render_template("contactos/lista.html", registros=registros, tab=tab, q=q, totales=totales)


@contactos.route("/<tipo>/nuevo", methods=["GET", "POST"])
@login_required
@roles_required("admin", "ventas")
def nuevo(tipo):
    cfg = _tipo_o_404(tipo)
    form = cfg["form"]()
    if request.method == "GET" and request.args.get("nombre"):
        form.nombre.data = request.args.get("nombre")
    if form.validate_on_submit():
        registro = cfg["modelo"]()
        form.populate_obj(registro)
        registro.nombre = registro.nombre.strip()
        db.session.add(registro)
        db.session.commit()
        flash(f"{cfg['singular'].capitalize()} «{registro.nombre}» registrado.", "ok")
        return redirect(url_for("contactos.detalle", tipo=tipo, registro_id=registro.id))
    return render_template("contactos/form.html", form=form, tipo=tipo, cfg=cfg,
                           titulo=f"Registrar {cfg['singular']}",
                           volver=url_for("contactos.lista", tab=tipo))


# Atajo con nombre propio (lo usan Kanban, dashboard y el asistente)
@contactos.route("/clientes/nuevo-cliente", methods=["GET", "POST"])
@login_required
@roles_required("admin", "ventas")
def nuevo_cliente():
    return nuevo("clientes")


@contactos.route("/<tipo>/<int:registro_id>", methods=["GET", "POST"])
@login_required
@roles_required("admin", "gestor", "ventas")
def detalle(tipo, registro_id):
    cfg = _tipo_o_404(tipo)
    registro = db.get_or_404(cfg["modelo"], registro_id)

    nota_form = None
    if current_user.puede_gestionar_contactos:
        nota_form = NotaForm()
        if tipo == "clientes":
            nota_form.pedido_id.choices = [(0, "— Ninguno —")] + [
                (p.id, f"{p.folio} · {p.modelo_prenda}") for p in
                sorted(registro.pedidos, key=lambda p: p.creado_en or 0, reverse=True)
            ]
        else:
            nota_form.pedido_id.choices = [(0, "— No aplica —")]

        if request.method == "POST" and nota_form.validate_on_submit():
            nota = NotaContacto(
                tipo=nota_form.tipo.data,
                contenido=nota_form.contenido.data.strip(),
                usuario_id=current_user.id,
                pedido_id=nota_form.pedido_id.data or None,
            )
            if tipo == "clientes":
                nota.cliente_id = registro.id
            else:
                nota.proveedor_id = registro.id
            db.session.add(nota)
            db.session.commit()
            flash("Nota agregada al historial.", "ok")
            return redirect(url_for("contactos.detalle", tipo=tipo, registro_id=registro.id))
    elif request.method == "POST":
        abort(403)

    pedidos = []
    if tipo == "clientes":
        pedidos = sorted(registro.pedidos, key=lambda p: p.creado_en or 0, reverse=True)
    return render_template("contactos/detalle.html", registro=registro, tipo=tipo, cfg=cfg,
                           nota_form=nota_form, pedidos=pedidos)


@contactos.route("/<tipo>/<int:registro_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("admin", "ventas")
def editar(tipo, registro_id):
    cfg = _tipo_o_404(tipo)
    registro = db.get_or_404(cfg["modelo"], registro_id)
    form = cfg["form"](obj=registro, registro_id=registro.id)
    if form.validate_on_submit():
        form.populate_obj(registro)
        registro.nombre = registro.nombre.strip()
        db.session.commit()
        flash("Datos de contacto actualizados.", "ok")
        return redirect(url_for("contactos.detalle", tipo=tipo, registro_id=registro.id))
    return render_template("contactos/form.html", form=form, tipo=tipo, cfg=cfg,
                           titulo=f"Editar {registro.nombre}",
                           volver=url_for("contactos.detalle", tipo=tipo, registro_id=registro.id))
