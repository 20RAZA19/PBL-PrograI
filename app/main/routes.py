from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash, Blueprint, abort
from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from flask_login import login_required, current_user
from app.models import (
    db, Pedido, Insumo, Movimiento, Cliente, Diseno, Usuario, FASES, NOMBRES_FASES,
)
from app.forms import AsociarInsumoForm, AccionForm
from app.decorators import roles_required
from app.rastreo.servicios import registrar_evento, pedidos_visibles

main = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Dashboard (contenido según el rol)
# ---------------------------------------------------------------------------
@main.route("/")
@main.route("/dashboard")
@login_required
def dashboard():
    if current_user.rol == "cliente":
        return _dashboard_cliente()
    return _dashboard_staff()


def _dashboard_staff():
    q = request.args.get("q", "")
    estado = request.args.get("estado", "")

    activos = Insumo.query.filter(Insumo.activo.is_(True)).all()

    # Tabla de materia prima (con búsqueda y filtro)
    insumos = activos
    if q:
        termino = q.lower()
        insumos = [i for i in insumos if termino in (i.nombre or "").lower()
                   or termino in (i.codigo_pantone or "").lower()
                   or termino in (i.codigo or "").lower()]
    if estado:
        insumos = [i for i in insumos if i.estado == estado]

    pedidos = Pedido.query.all()
    en_produccion = [p for p in pedidos if p.en_produccion]

    resumen = {
        "metros_totales": sum(float(i.cantidad_disponible or 0) for i in activos if i.unidad_medida == "Metros"),
        "telas_bajo_stock": sum(1 for i in activos if i.alerta_stock != "ok"),
        "telas_criticas": sum(1 for i in activos if i.alerta_stock == "critico"),
        "pedidos_produccion": len(en_produccion),
        "pedidos_en_ruta": sum(1 for p in pedidos if p.estado == "En Ruta"),
        "total_disenos": Diseno.query.filter(Diseno.archivado.is_(False)).count(),
        "unidades_produccion": sum(p.cantidad for p in en_produccion),
    }

    # Gráfico 1: pedidos por fase (barras verticales)
    conteo_fases = {nombre: 0 for nombre in NOMBRES_FASES}
    for p in pedidos:
        if p.estado in conteo_fases:
            conteo_fases[p.estado] += 1
    max_fase = max(conteo_fases.values()) or 1
    grafico_fases = [
        {"nombre": f["nombre"], "icono": f["icono"], "valor": conteo_fases[f["nombre"]],
         "altura": round(conteo_fases[f["nombre"]] / max_fase * 100)}
        for f in FASES
    ]

    # Gráfico 2: salud del inventario (dona)
    salud = {
        "ok": sum(1 for i in activos if i.alerta_stock == "ok"),
        "bajo": sum(1 for i in activos if i.alerta_stock == "bajo"),
        "critico": sum(1 for i in activos if i.alerta_stock == "critico"),
    }
    total_salud = sum(salud.values()) or 1
    salud["pct_ok"] = round(salud["ok"] / total_salud * 100)
    salud["pct_bajo"] = round(salud["bajo"] / total_salud * 100)
    salud["pct_critico"] = round(salud["critico"] / total_salud * 100)
    salud["total"] = salud["ok"] + salud["bajo"] + salud["critico"]

    # Gráfico 3: stock vs mínimo (las 6 telas con menor cobertura)
    escala = max([float(i.cantidad_disponible or 0) for i in activos]
                 + [float(i.stock_minimo or 0) for i in activos] + [1])
    grafico_stock = [
        {"tela": i, "ancho": round(float(i.cantidad_disponible or 0) / escala * 100),
         "minimo": round(float(i.stock_minimo or 0) / escala * 100)}
        for i in sorted(activos, key=lambda i: i.cobertura)[:6]
    ]

    # Gráfico 4: movimientos de los últimos 7 días
    hoy = date.today()
    desde = datetime.combine(hoy - timedelta(days=6), datetime.min.time())
    movs = Movimiento.query.filter(Movimiento.fecha >= desde).all()
    dias = []
    for n in range(7):
        dia = hoy - timedelta(days=6 - n)
        entradas = sum(float(m.metros or m.cantidad or 0) for m in movs if m.fecha.date() == dia and m.tipo == "entrada")
        salidas = sum(float(m.metros or m.cantidad or 0) for m in movs if m.fecha.date() == dia and m.tipo == "salida")
        dias.append({"dia": dia, "entradas": entradas, "salidas": salidas})
    max_mov = max([d["entradas"] for d in dias] + [d["salidas"] for d in dias] + [1])
    for d in dias:
        d["alto_entradas"] = round(d["entradas"] / max_mov * 100)
        d["alto_salidas"] = round(d["salidas"] / max_mov * 100)

    # Próximas entregas
    proximas = sorted(
        [p for p in pedidos if not p.entregado],
        key=lambda p: p.fecha_limite or date.max,
    )[:5]

    # Propuestas de prendas por revisar: primero las que llevan más tiempo esperando
    from app.models import Solicitud
    solicitudes_nuevas = (Solicitud.query.filter_by(estado="enviada")
                          .options(selectinload(Solicitud.lineas), selectinload(Solicitud.cliente))
                          .order_by(Solicitud.creado_en).limit(6).all())
    # Cotizaciones de solicitudes publicadas que esperan la decisión del cliente
    esperando_cliente = (Solicitud.query.filter_by(estado="aprobada")
                         .filter(Solicitud.vence_en >= date.today()).count())

    # KPIs exclusivos del administrador
    admin_kpis = None
    if current_user.rol == "admin":
        admin_kpis = {
            "pendientes": Usuario.query.filter_by(estado_permiso="pendiente").count(),
            "usuarios": Usuario.query.count(),
            "por_rol": {r: Usuario.query.filter_by(rol=r).count() for r in ("admin", "gestor", "ventas", "cliente")},
        }

    from app.indicadores import recomendaciones, kpis, graficos
    recs = recomendaciones(current_user)

    return render_template(
        "dashboard.html", q=q, estado=estado, resumen=resumen, solicitudes_nuevas=solicitudes_nuevas,
        esperando_cliente=esperando_cliente, telas=insumos,
        grafico_fases=grafico_fases, salud=salud, grafico_stock=grafico_stock,
        movimientos_semana=dias, proximas=proximas, admin_kpis=admin_kpis,
        recomendaciones=recs, indicadores=kpis(current_user), graficos=graficos(current_user),
        saludo=("Buenos días" if datetime.now().hour < 12 else
                "Buenas tardes" if datetime.now().hour < 19 else "Buenas noches"),
        conteo_recs={n: sum(1 for r in recs if r["nivel"] == n) for n in ("critico", "alerta", "sugerencia")},
    )


def _dashboard_cliente():
    pedidos = pedidos_visibles().order_by(Pedido.creado_en.desc()).all()
    activos = [p for p in pedidos if not p.entregado]
    disenos = []
    if current_user.cliente_id:
        disenos = Diseno.query.filter_by(cliente_id=current_user.cliente_id, archivado=False).all()

    resumen = {
        "activos": len(activos),
        "en_ruta": sum(1 for p in pedidos if p.estado == "En Ruta"),
        "entregados": sum(1 for p in pedidos if p.entregado),
        "disenos": len(disenos),
        "unidades": sum(p.cantidad for p in activos),
    }
    proxima = min(activos, key=lambda p: p.fecha_limite or date.max) if activos else None
    from app.models import Cotizacion
    cotizaciones = []
    if current_user.cliente_id:
        cotizaciones = [c for c in Cotizacion.query.filter_by(cliente_id=current_user.cliente_id, estado="enviada")
                        .order_by(Cotizacion.fecha.desc()).all() if not c.vencida]
    solicitudes = []
    if current_user.cliente_id:
        from app.models import Solicitud
        solicitudes = (Solicitud.query.filter_by(cliente_id=current_user.cliente_id)
                       .filter(Solicitud.estado.in_(("enviada", "aprobada")))
                       .order_by(Solicitud.creado_en.desc()).all())
    return render_template(
        "dashboard_cliente.html", pedidos=pedidos, activos=activos,
        disenos=disenos[:3], resumen=resumen, proxima=proxima, cotizaciones=cotizaciones,
        solicitudes=solicitudes,
    )


# ---------------------------------------------------------------------------
# Producción (Kanban) — admin y gestor
# ---------------------------------------------------------------------------
@main.route('/pedidos/kanban')
@login_required
@roles_required("admin", "gestor", "ventas")
def kanban_pedidos():
    q = (request.args.get('q') or '').strip()
    consulta = Pedido.query.join(Cliente).options(
        selectinload(Pedido.cliente), selectinload(Pedido.diseno), selectinload(Pedido.eventos),
        selectinload(Pedido.registros_calidad),
    )
    if q:
        consulta = consulta.filter(
            or_(
                Pedido.folio.ilike(f'%{q}%'),
                Pedido.modelo_prenda.ilike(f'%{q}%'),
                Cliente.nombre.ilike(f'%{q}%')
            )
        )
    # Lo más urgente arriba en cada columna
    pedidos = consulta.order_by(Pedido.fecha_limite, Pedido.folio).all()
    return render_template('pedidos/kanban.html', pedidos=pedidos, q=q,
                           estados=NOMBRES_FASES, accion_form=AccionForm())


# Ya no existe el registro manual de pedidos («Nuevo Pedido»): los pedidos nacen
# únicamente de una cotización aceptada o de una solicitud que el cliente aceptó.

@main.route('/pedidos/<int:id_pedido>/mover/<direccion>', methods=['POST'])
@login_required
@roles_required("gestor")
def mover_pedido(id_pedido, direccion):
    pedido = db.get_or_404(Pedido, id_pedido)
    form = AccionForm()
    if not form.validate_on_submit():
        abort(400)

    indice = pedido.fase_actual - 1
    if direccion == "siguiente" and indice < len(NOMBRES_FASES) - 1:
        indice += 1
    elif direccion == "anterior" and indice > 0:
        indice -= 1
    else:
        flash('El pedido ya está en la fase límite.', 'warn')
        return redirect(url_for('main.kanban_pedidos'))

    nuevo_estado = NOMBRES_FASES[indice]
    registrar_evento(pedido, estado=nuevo_estado,
                     nota=f'Movido a "{nuevo_estado}" desde el tablero de producción.',
                     usuario=current_user)
    db.session.commit()
    flash(f'{pedido.folio} pasó a "{nuevo_estado}".', 'ok')
    return redirect(url_for('main.kanban_pedidos', q=request.args.get('q') or None))


@main.route('/pedidos/<int:id_pedido>/descontar_insumo', methods=['POST'])
@login_required
@roles_required("admin", "gestor")
def descontar_insumo(id_pedido):
    pedido = db.get_or_404(Pedido, id_pedido)
    form = AsociarInsumoForm()
    form.insumo_id.choices = [(i.id, f"{i.nombre} ({i.cantidad_disponible} {i.unidad_medida})") for i in Insumo.query.all()]

    if form.validate_on_submit():
        insumo = db.session.get(Insumo, form.insumo_id.data)
        cantidad_req = form.cantidad_usar.data

        if insumo.cantidad_disponible < cantidad_req:
            flash(f'Error: Stock insuficiente de {insumo.nombre}.', 'danger')
        else:
            insumo.cantidad_disponible -= cantidad_req
            mov = Movimiento(tipo='salida', cantidad=cantidad_req, metros=cantidad_req,
                             motivo=f'Consumo para pedido {pedido.folio}', insumo_id=insumo.id,
                             pedido_id=pedido.id, usuario_id=current_user.id)
            db.session.add(mov)
            db.session.commit()
            flash('Inventario descontado exitosamente.', 'ok')
    else:
        flash('Revisa el insumo y la cantidad a descontar.', 'danger')

    destino = request.form.get('volver')
    if destino and destino.startswith('/') and not destino.startswith('//'):
        return redirect(destino)
    return redirect(url_for('main.kanban_pedidos'))
