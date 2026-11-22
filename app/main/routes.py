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


LIMITE_DASHBOARD = 6   # filas por lista: lo más importante; el resto está en su sección


def _dashboard_staff():
    """Resumen de «qué hago hoy» según el rol. Cada lista trae como máximo
    LIMITE_DASHBOARD filas directamente desde la base de datos (LIMIT) y enlaza a su
    sección para ver el resto. Los gráficos de tendencia viven en Reportes."""
    from app.models import Solicitud
    from app.mensajes.servicios import sin_leer_total
    from app.indicadores import recomendaciones, kpis

    hoy = date.today()
    rol = current_user.rol
    sin_entregar = Pedido.query.filter(Pedido.estado != "Entregado")
    vencidos = sin_entregar.filter(Pedido.fecha_limite < hoy).count()
    semana = sin_entregar.filter(Pedido.fecha_limite >= hoy,
                                 Pedido.fecha_limite <= hoy + timedelta(days=7)).count()

    # Próximas entregas: primero lo vencido, luego lo que vence antes
    proximas = (sin_entregar.options(selectinload(Pedido.cliente))
                .order_by(Pedido.fecha_limite, Pedido.folio).limit(LIMITE_DASHBOARD).all())
    total_sin_entregar = sin_entregar.count()

    solicitudes_nuevas, total_solicitudes, esperando_cliente = [], 0, 0
    if current_user.puede_atender_solicitudes:
        base_sol = Solicitud.query.filter_by(estado="enviada")
        total_solicitudes = base_sol.count()
        solicitudes_nuevas = (base_sol.options(selectinload(Solicitud.lineas), selectinload(Solicitud.cliente))
                              .order_by(Solicitud.creado_en).limit(LIMITE_DASHBOARD).all())
        esperando_cliente = (Solicitud.query.filter_by(estado="aprobada")
                             .filter(Solicitud.vence_en >= hoy).count())

    # Insumos por reponer: solo los más críticos (menor stock respecto al mínimo)
    insumos_reponer, total_reponer = [], 0
    if rol in ("gestor", "admin"):
        base_ins = Insumo.query.filter(Insumo.activo.is_(True), Insumo.stock_minimo > 0,
                                       Insumo.cantidad_disponible <= Insumo.stock_minimo)
        total_reponer = base_ins.count()
        if rol == "gestor":
            insumos_reponer = (base_ins.order_by(Insumo.cantidad_disponible / Insumo.stock_minimo)
                               .limit(LIMITE_DASHBOARD).all())

    # Tarjetas «Para hoy»: cuatro números que llevan directo a su sección
    def tarjeta(titulo, valor, icono, url, nivel, detalle):
        return {"titulo": titulo, "valor": valor, "icono": icono, "url": url,
                "nivel": nivel if valor else "ok", "detalle": detalle}

    t_aprob = tarjeta("Aprobaciones pendientes", total_solicitudes, "clipboard-check",
                      url_for("solicitudes.lista", estado="enviada"), "warn", "propuestas de clientes por revisar")
    t_venc = tarjeta("Pedidos vencidos", vencidos, "alarm-clock",
                     url_for("main.kanban_pedidos", plazo="vencido"), "danger", "pasaron su fecha sin entregarse")
    t_semana = tarjeta("Entregas en 7 días", semana, "calendar-clock",
                       url_for("main.kanban_pedidos"), "info", "pedidos que vencen esta semana")
    if rol == "ventas":
        tarjetas = [t_aprob,
                    tarjeta("Esperando al cliente", esperando_cliente, "hourglass",
                            url_for("solicitudes.lista", estado="aprobada"), "info", "cotizaciones por aceptar"),
                    tarjeta("Mensajes sin leer", sin_leer_total(current_user), "messages-square",
                            url_for("mensajes.lista"), "warn", "conversaciones con clientes"),
                    t_semana]
    elif rol == "gestor":
        tarjetas = [t_venc, t_semana,
                    tarjeta("Insumos por reponer", total_reponer, "package-x",
                            url_for("telas.lista", estado="Stock Bajo"), "warn", "en o bajo su stock mínimo"),
                    tarjeta("En producción", Pedido.query.filter(Pedido.estado.in_(
                        ("Recibido", "En Corte", "En Costura", "Terminado"))).count(), "factory",
                            url_for("main.kanban_pedidos"), "info", "pedidos en el taller")]
    else:
        tarjetas = [t_aprob, t_venc, t_semana,
                    tarjeta("Cuentas por aprobar", Usuario.query.filter_by(estado_permiso="pendiente").count(),
                            "user-check", url_for("admin.usuarios"), "warn", "usuarios esperando acceso")]

    recs = recomendaciones(current_user)
    ahora = datetime.now()
    return render_template(
        "dashboard.html", tarjetas=tarjetas, proximas=proximas, total_sin_entregar=total_sin_entregar,
        solicitudes_nuevas=solicitudes_nuevas, total_solicitudes=total_solicitudes,
        esperando_cliente=esperando_cliente, insumos_reponer=insumos_reponer, total_reponer=total_reponer,
        recomendaciones=recs, indicadores=kpis(current_user),
        saludo=("Buenos días" if ahora.hour < 12 else "Buenas tardes" if ahora.hour < 19 else "Buenas noches"),
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
        "dashboard_cliente.html", pedidos=pedidos, activos=activos[:LIMITE_DASHBOARD], total_activos=len(activos),
        disenos=disenos[:3], resumen=resumen, proxima=proxima, cotizaciones=cotizaciones[:LIMITE_DASHBOARD],
        solicitudes=solicitudes[:LIMITE_DASHBOARD], visual=_visual_cliente(pedidos, activos),
    )


def _visual_cliente(pedidos, activos):
    """Datos de los gráficos del portal del cliente: sus pedidos por fase, prendas por mes y puntualidad."""
    from app.indicadores import MESES, _meses_atras, fecha_entrega_real
    fases = list(NOMBRES_FASES[:-1])                     # «Entregado» no es un pedido en curso
    por_fase = [sum(1 for p in activos if p.estado == f) for f in fases]

    periodos = _meses_atras(12)
    indice = {p: i for i, p in enumerate(periodos)}
    prendas = [0] * len(periodos)
    for p in pedidos:
        i = indice.get((p.creado_en.year, p.creado_en.month)) if p.creado_en else None
        if i is not None:
            prendas[i] += p.cantidad

    entregados = [p for p in pedidos if p.entregado]
    a_tiempo = 0
    for p in entregados:
        real = fecha_entrega_real(p)
        if real is None or p.fecha_limite is None or real <= p.fecha_limite:
            a_tiempo += 1
    return {
        "fases": {"tipo": "barras", "unidad": "pedidos", "etiquetas": fases,
                  "series": [{"nombre": "Pedidos", "valores": por_fase}]},
        "prendas": {"tipo": "barras", "unidad": "prendas",
                    "etiquetas": [f"{MESES[m - 1]} {str(a)[2:]}" for a, m in periodos],
                    "series": [{"nombre": "Prendas pedidas", "valores": prendas}]},
        "hay_prendas": any(prendas),
        "entregados": len(entregados), "a_tiempo": a_tiempo,
        "puntualidad": round(a_tiempo / len(entregados) * 100) if entregados else None,
    }


# ---------------------------------------------------------------------------
# Producción (Kanban) — admin y gestor
# ---------------------------------------------------------------------------
@main.route('/pedidos/kanban')
@login_required
@roles_required("admin", "gestor", "ventas")
def kanban_pedidos():
    q = (request.args.get('q') or '').strip()
    cliente_id = request.args.get('cliente', type=int)
    prioridad = request.args.get('prioridad', '')
    responsable_id = request.args.get('responsable', type=int)
    plazo = request.args.get('plazo', '')

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
    if cliente_id:
        consulta = consulta.filter(Pedido.cliente_id == cliente_id)
    # Lo más urgente arriba en cada columna
    todos = consulta.order_by(Pedido.fecha_limite, Pedido.folio).all()

    # Entregados: solo los de los últimos 7 días; los anteriores están en el historial
    limite = datetime.now() - timedelta(days=7)

    def ultimo_mov(p):
        return max(p.eventos, key=lambda e: e.fecha) if p.eventos else None

    activos = [p for p in todos
               if not (p.entregado and (ultimo_mov(p) is None or ultimo_mov(p).fecha < limite))]

    def plazo_de(p):
        if p.entregado:
            return 'entregado'
        if p.dias_restantes is None:
            return 'tiempo'
        if p.dias_restantes < 0:
            return 'vencido'
        if p.dias_restantes <= 3:
            return 'pronto'
        return 'tiempo'

    def prioridad_de(p):
        return {'vencido': 'alta', 'pronto': 'media'}.get(plazo_de(p), 'normal')

    def responsable_de(p):
        ev = ultimo_mov(p)
        return ev.usuario if ev and ev.usuario else None

    # Filtros de la barra (prioridad y responsable se derivan: la app no los guarda por pedido)
    base = activos
    if prioridad:
        base = [p for p in base if prioridad_de(p) == prioridad]
    if responsable_id:
        base = [p for p in base if (responsable_de(p) and responsable_de(p).id == responsable_id)]

    conteos = {'todos': len(base), 'vencido': 0, 'pronto': 0, 'tiempo': 0}
    for p in base:
        if plazo_de(p) in conteos:
            conteos[plazo_de(p)] += 1
    vista = [p for p in base if not plazo or plazo_de(p) == plazo]

    responsables = {}
    for p in activos:
        u = responsable_de(p)
        if u:
            responsables[u.id] = u
    clientes = Cliente.query.order_by(Cliente.nombre).all()

    return render_template('pedidos/kanban.html', pedidos=vista, q=q, estados=NOMBRES_FASES,
                           accion_form=AccionForm(), plazo_de=plazo_de, prioridad_de=prioridad_de,
                           responsable_de=responsable_de, conteos=conteos, plazo=plazo,
                           prioridad=prioridad, responsable_id=responsable_id, cliente_id=cliente_id,
                           clientes=clientes, responsables=sorted(responsables.values(), key=lambda u: u.nombre),
                           limite_entregados=limite)


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
