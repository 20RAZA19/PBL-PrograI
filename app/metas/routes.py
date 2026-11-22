"""Metas e incentivos del equipo.

* Cada trabajador (taller y ventas) ve sus metas del mes, cuánto lleva y cuánto
  incentivo le corresponde si el mes cerrara hoy.
* El administrador define las metas, revisa al equipo, cierra el mes (fija los
  montos) y marca los incentivos como pagados. También descarga la nómina en CSV.
"""
import csv
import io
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import BooleanField, DateField, DecimalField, IntegerField, SelectField, StringField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError

from app.auditoria import registrar_accion
from app.decorators import roles_required
from app.extensions import db
from app.forms import AccionForm
from app.metas.indicadores import (INDICADORES, cerrar_mes, dias_restantes, evaluar, formatear, mes_actual,
                                   mes_terminado, metas_de, monto_del_mes, mover_mes, nombre_mes, resumen_equipo)
from app.models import ROLES_CON_METAS, Meta, PagoIncentivo, Usuario
from app.utils import fila_csv

metas = Blueprint("metas", __name__)
ETIQUETA_ROL = {"gestor": "Taller", "ventas": "Ventas"}


# --- Formulario ------------------------------------------------------------------
class MetaForm(FlaskForm):
    nombre = StringField("Nombre de la meta", validators=[DataRequired("Ponle un nombre."), Length(max=120)])
    indicador = SelectField("Qué se mide", validators=[DataRequired()])
    destino = SelectField("Para quién", validators=[DataRequired()],
                          description="Solo aparece el personal del área que mide la meta.")
    fecha_inicio = DateField("Desde", validators=[DataRequired("Elige la fecha de inicio.")])
    fecha_fin = DateField("Hasta", validators=[DataRequired("Elige la fecha de fin.")],
                          description="Solo cuenta lo ocurrido entre estas fechas, ambas incluidas.")
    objetivo = DecimalField("Objetivo del periodo", places=2, validators=[
        DataRequired("Escribe el objetivo."), NumberRange(min=0.01, message="Debe ser mayor que cero.")])
    incentivo = DecimalField("Incentivo al cumplirla ($)", places=2, validators=[
        DataRequired("Escribe el monto."), NumberRange(min=0, max=100000, message="Entre 0 y 100,000.")])
    umbral_parcial = IntegerField("Pago parcial desde (% de avance)", validators=[
        Optional(), NumberRange(min=50, max=99, message="Entre 50 y 99.")],
        description="Opcional. Si la persona llega a este avance sin cumplir la meta, recibe la mitad del incentivo.")
    descripcion = StringField("Nota para el equipo", validators=[Optional(), Length(max=255)])
    activa = BooleanField("Meta activa", default=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.indicador.choices = [(clave, f"{ETIQUETA_ROL.get(i['rol'], i['rol'])} · {i['nombre']}")
                                  for clave, i in INDICADORES.items()]
        personas = (Usuario.query.filter(Usuario.rol.in_(ROLES_CON_METAS), Usuario.activo.is_(True))
                    .order_by(Usuario.nombre).all())
        self.destino.choices = ([(f"rol:{r}", f"Todo el equipo de {ETIQUETA_ROL[r].lower()}") for r in ROLES_CON_METAS]
                                + [(f"u:{u.id}", u.nombre) for u in personas])
        # Área de cada opción de «Para quién», para filtrar la lista según «Qué se mide».
        self.area_destino = {f"rol:{r}": r for r in ROLES_CON_METAS}
        self.area_destino.update({f"u:{u.id}": u.rol for u in personas})

    def validate_destino(self, campo):
        info = INDICADORES.get(self.indicador.data)
        if info and self.area_destino.get(campo.data) != info["rol"]:
            raise ValidationError(f"Esta meta mide al área de {ETIQUETA_ROL[info['rol']].lower()}: "
                                  "elige a alguien de esa área.")

    def validate_fecha_fin(self, campo):
        if self.fecha_inicio.data and campo.data:
            if campo.data < self.fecha_inicio.data:
                raise ValidationError("La fecha de fin no puede ser antes del inicio.")
            if (campo.data - self.fecha_inicio.data).days > 366:
                raise ValidationError("El periodo puede durar hasta un año.")


def _aplicar(form, meta):
    meta.nombre = form.nombre.data.strip()
    meta.indicador = form.indicador.data
    tipo, _, valor = form.destino.data.partition(":")
    meta.rol, meta.usuario_id = (valor, None) if tipo == "rol" else (None, int(valor))
    meta.objetivo = form.objetivo.data
    meta.incentivo = form.incentivo.data
    meta.umbral_parcial = form.umbral_parcial.data
    meta.descripcion = (form.descripcion.data or "").strip() or None
    meta.activa = form.activa.data
    meta.fecha_inicio, meta.fecha_fin = form.fecha_inicio.data, form.fecha_fin.data


def _mes_en_curso():
    hoy = date.today()
    return hoy.replace(day=1), hoy.replace(day=monthrange(hoy.year, hoy.month)[1])


# --- Mes elegido -------------------------------------------------------------------
def _mes_pedido():
    """?mes=AAAA-MM, limitado a los últimos 24 meses y nunca al futuro."""
    actual = mes_actual()
    try:
        anio, mes = (int(x) for x in request.args.get("mes", "").split("-"))
        if not 1 <= mes <= 12:
            raise ValueError
    except ValueError:
        return actual
    if (anio, mes) > actual or (anio, mes) < mover_mes(*actual, -24):
        return actual
    return anio, mes


def _contexto_mes(anio, mes):
    actual = mes_actual()
    return {"anio": anio, "mes": mes, "nombre_mes": nombre_mes(anio, mes), "clave_mes": f"{anio}-{mes:02d}",
            "es_actual": (anio, mes) == actual, "terminado": mes_terminado(anio, mes),
            "dias_restantes": dias_restantes(anio, mes),
            "anterior": "%d-%02d" % mover_mes(anio, mes, -1),
            "siguiente": "%d-%02d" % mover_mes(anio, mes, 1) if (anio, mes) < actual else None}


# --- Vista del trabajador ------------------------------------------------------------
@metas.route("/")
@login_required
@roles_required("admin", "gestor", "ventas")
def mis_metas():
    anio, mes = _mes_pedido()
    pagos = {p.meta_id: p for p in PagoIncentivo.query.filter_by(usuario_id=current_user.id, anio=anio, mes=mes)}
    evaluaciones = []
    for meta in metas_de(current_user, anio, mes):
        ev = evaluar(meta, current_user, anio, mes)
        ev["pago"] = pagos.get(meta.id)
        evaluaciones.append(ev)
    total = sum((monto_del_mes(e) for e in evaluaciones), Decimal("0"))
    historial = (PagoIncentivo.query.filter_by(usuario_id=current_user.id)
                 .order_by(PagoIncentivo.anio.desc(), PagoIncentivo.mes.desc(), PagoIncentivo.id).limit(36).all())
    por_mes = {}
    for p in historial:
        fila = por_mes.setdefault((p.anio, p.mes), {"nombre": nombre_mes(p.anio, p.mes), "monto": Decimal("0"),
                                                    "pagado": True, "metas": 0, "cumplidas": 0})
        fila["monto"] += p.monto
        fila["metas"] += 1
        fila["cumplidas"] += p.avance >= 100
        fila["pagado"] = fila["pagado"] and p.estado == "pagado"
    return render_template("metas/mis_metas.html", evaluaciones=evaluaciones, total=total,
                           maximo=sum((e["incentivo"] for e in evaluaciones if e["liquida_aqui"]), Decimal("0")),
                           historial=list(por_mes.values())[:12], **_contexto_mes(anio, mes))


# --- Panel del administrador ------------------------------------------------------------
@metas.route("/equipo")
@login_required
@roles_required("admin")
def equipo():
    anio, mes = _mes_pedido()
    filas = resumen_equipo(anio, mes)
    cerrado = PagoIncentivo.query.filter_by(anio=anio, mes=mes).count() > 0
    todas = Meta.query.order_by(Meta.activa.desc(), Meta.rol, Meta.nombre).all()
    return render_template("metas/equipo.html", filas=filas, todas=todas, cerrado=cerrado,
                           total=sum((f["total"] for f in filas), Decimal("0")),
                           por_pagar=sum((p.monto for p in PagoIncentivo.query.filter_by(
                               anio=anio, mes=mes, estado="pendiente")), Decimal("0")),
                           INDICADORES=INDICADORES, formatear=formatear, accion_form=AccionForm(),
                           **_contexto_mes(anio, mes))


@metas.route("/nueva", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def nueva():
    form = MetaForm()
    if request.method == "GET":
        form.indicador.data = request.args.get("indicador") if request.args.get("indicador") in INDICADORES else None
        form.activa.data = True
        form.fecha_inicio.data, form.fecha_fin.data = _mes_en_curso()
    if form.validate_on_submit():
        meta = Meta(creada_por=current_user._get_current_object())
        _aplicar(form, meta)
        db.session.add(meta)
        db.session.commit()
        flash(f"Meta «{meta.nombre}» creada. El equipo ya la ve en «Mis metas».", "ok")
        return redirect(url_for("metas.equipo"))
    return render_template("metas/form.html", form=form, meta=None, INDICADORES=INDICADORES)


@metas.route("/<int:meta_id>/editar", methods=["GET", "POST"])
@login_required
@roles_required("admin")
def editar(meta_id):
    meta = db.get_or_404(Meta, meta_id)
    form = MetaForm(obj=meta)
    if request.method == "GET":
        form.destino.data = f"u:{meta.usuario_id}" if meta.usuario_id else f"rol:{meta.rol}"
        if not meta.tiene_periodo:
            form.fecha_inicio.data, form.fecha_fin.data = _mes_en_curso()
    if form.validate_on_submit():
        _aplicar(form, meta)
        db.session.commit()
        flash("Meta actualizada. Los meses ya cerrados conservan lo que se calculó al cerrarlos.", "ok")
        return redirect(url_for("metas.equipo"))
    return render_template("metas/form.html", form=form, meta=meta, INDICADORES=INDICADORES)


@metas.route("/<int:meta_id>/activar", methods=["POST"])
@login_required
@roles_required("admin")
def activar(meta_id):
    meta = db.get_or_404(Meta, meta_id)
    if AccionForm().validate_on_submit():
        meta.activa = not meta.activa
        db.session.commit()
        flash(f"Meta «{meta.nombre}» {'activada' if meta.activa else 'pausada'}.", "ok")
    return redirect(url_for("metas.equipo"))


@metas.route("/cerrar", methods=["POST"])
@login_required
@roles_required("admin")
def cerrar():
    anio, mes = _mes_pedido()
    if not AccionForm().validate_on_submit():
        abort(400)
    if not mes_terminado(anio, mes):
        flash(f"{nombre_mes(anio, mes).capitalize()} aún no termina: podrás cerrarlo desde el día 1 del mes siguiente.", "warn")
        return redirect(url_for("metas.equipo", mes=f"{anio}-{mes:02d}"))
    creados, total = cerrar_mes(anio, mes)
    registrar_accion("editar", "Pago de incentivo",
                     f"Cerró {nombre_mes(anio, mes)}: incentivos por ${total:,.2f}", usuario=current_user)
    db.session.commit()
    flash(f"{nombre_mes(anio, mes).capitalize()} cerrado. Incentivos fijados por ${total:,.2f}. "
          "Márcalos como pagados cuando los entregues.", "ok")
    return redirect(url_for("metas.equipo", mes=f"{anio}-{mes:02d}"))


@metas.route("/pagar/<int:usuario_id>", methods=["POST"])
@login_required
@roles_required("admin")
def pagar(usuario_id):
    anio, mes = _mes_pedido()
    if not AccionForm().validate_on_submit():
        abort(400)
    persona = db.get_or_404(Usuario, usuario_id)
    pendientes = PagoIncentivo.query.filter_by(usuario_id=persona.id, anio=anio, mes=mes, estado="pendiente").all()
    if not pendientes:
        flash("No hay incentivos pendientes para esa persona en ese mes. Cierra el mes primero.", "warn")
    else:
        ahora = datetime.now()
        for p in pendientes:
            p.estado, p.pagado_en, p.pagado_por_id = "pagado", ahora, current_user.id
        total = sum((p.monto for p in pendientes), Decimal("0"))
        db.session.commit()
        flash(f"Incentivos de {persona.nombre} de {nombre_mes(anio, mes)} marcados como pagados (${total:,.2f}).", "ok")
    return redirect(url_for("metas.equipo", mes=f"{anio}-{mes:02d}"))


@metas.route("/equipo.csv")
@login_required
@roles_required("admin")
def equipo_csv():
    """Detalle del mes para nómina: una fila por persona y meta."""
    anio, mes = _mes_pedido()
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["Mes", "Persona", "Correo", "Rol", "Meta", "Periodo", "Resultado", "Objetivo", "Avance %",
                       "Incentivo", "Estado"])
    for fila in resumen_equipo(anio, mes):
        u = fila["usuario"]
        for ev in fila["evaluaciones"]:
            pago = ev["pago"]
            escritor.writerow(fila_csv([
                nombre_mes(anio, mes), u.nombre, u.email, u.rol_legible, ev["meta"].nombre, ev["meta"].periodo_texto, ev["valor_texto"],
                ev["objetivo_texto"], ev["avance"], f"{monto_del_mes(ev):.2f}",
                pago.estado_legible if pago else ("Estimado (mes sin cerrar)" if ev["liquida_aqui"]
                                                  else f"Se paga en {ev['mes_liquidacion']}")]))
    return Response("﻿" + salida.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=incentivos-{anio}-{mes:02d}.csv"})
