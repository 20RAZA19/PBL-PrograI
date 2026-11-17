"""Notificaciones internas.

Hay dos clases de avisos:

* Automáticos: se calculan a partir del estado actual del sistema (pedidos que
  vencen en 3 días o menos, insumos en nivel crítico, solicitudes de acceso…).
  Desaparecen solos cuando la situación se resuelve.
* De evento: se crean cuando algo ocurre (un pedido cambió de fase, se
  registró un defecto, el cliente aceptó una cotización…). Se conservan
  30 días después de leídos.
"""
from datetime import date, datetime, timedelta

from flask import url_for
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Cotizacion, Insumo, Notificacion, OrdenCompra, Pedido, Usuario

DIAS_AVISO_VENCIMIENTO = 3


def _avisos_automaticos(usuario):
    """Situaciones vigentes que le importan a este usuario: {clave: datos}."""
    avisos = {}
    rol = usuario.rol
    hoy = date.today()

    if rol in ("admin", "gestor", "ventas"):
        pedidos = Pedido.query.filter(Pedido.estado != "Entregado",
                                      Pedido.fecha_limite <= hoy + timedelta(days=DIAS_AVISO_VENCIMIENTO)).all()
        for p in pedidos:
            dias = (p.fecha_limite - hoy).days
            if dias < 0:
                avisos[f"vencido-{p.id}-{p.fecha_limite.isoformat()}"] = dict(
                    tipo="vencimiento", nivel="danger",
                    titulo=f"{p.folio} está vencido",
                    mensaje=f"Superó su fecha límite hace {-dias} día{'s' if dias != -1 else ''} · "
                            f"{p.cliente.nombre} · fase {p.estado}",
                    url=url_for("rastreo.detalle", folio=p.folio))
            else:
                cuando = "hoy" if dias == 0 else ("mañana" if dias == 1 else f"en {dias} días")
                avisos[f"vence-{p.id}-{p.fecha_limite.isoformat()}"] = dict(
                    tipo="vencimiento", nivel="danger" if dias <= 1 else "warn",
                    titulo=f"{p.folio} vence {cuando}",
                    mensaje=f"{p.cliente.nombre} · {p.cantidad} prendas · fase {p.estado}",
                    url=url_for("rastreo.detalle", folio=p.folio))

    if rol in ("admin", "gestor"):
        for i in Insumo.query.filter(Insumo.activo.is_(True)).all():
            if i.alerta_stock == "critico":
                avisos[f"stock-critico-{i.id}"] = dict(
                    tipo="stock", nivel="danger",
                    titulo=f"{i.nombre} en nivel crítico",
                    mensaje=f"Quedan {float(i.cantidad_disponible):,.0f} {i.unidad_medida.lower()} "
                            f"(mínimo {float(i.stock_minimo):,.0f}). Revisa las compras sugeridas.",
                    url=url_for("compras.index"))
        for oc in OrdenCompra.query.filter_by(estado="enviada").all():
            if oc.atrasada:
                avisos[f"oc-atrasada-{oc.id}"] = dict(
                    tipo="compra", nivel="warn",
                    titulo=f"{oc.folio} no ha llegado",
                    mensaje=f"{oc.proveedor.nombre if oc.proveedor else 'Proveedor'} debía entregar el "
                            f"{oc.fecha_esperada.strftime('%d/%m/%Y')}.",
                    url=url_for("compras.detalle", orden_id=oc.id))

    if rol in ("admin", "ventas"):
        for c in Cotizacion.query.filter_by(estado="enviada").all():
            if not c.vencida and c.dias_para_vencer <= 2:
                avisos[f"cot-vence-{c.id}"] = dict(
                    tipo="cotizacion", nivel="info",
                    titulo=f"{c.folio} vence pronto sin respuesta",
                    mensaje=f"{c.cliente.nombre} · {c.total_prendas:,} prendas. Da seguimiento al cliente.",
                    url=url_for("cotizaciones.detalle", cotizacion_id=c.id))

    if rol == "admin":
        pendientes = Usuario.query.filter_by(estado_permiso="pendiente").order_by(Usuario.id).all()
        if pendientes:
            n = len(pendientes)
            avisos[f"usuarios-pendientes-{pendientes[-1].id}"] = dict(
                tipo="usuarios", nivel="info",
                titulo=f"{n} solicitud{'es' if n != 1 else ''} de acceso pendiente{'s' if n != 1 else ''}",
                mensaje=", ".join(u.nombre for u in pendientes[:3]) + ("…" if n > 3 else ""),
                url=url_for("admin.usuarios"))
    return avisos


def sincronizar(usuario):
    """Crea, actualiza o elimina los avisos automáticos del usuario. Hace commit."""
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return
    vigentes = _avisos_automaticos(usuario)
    existentes = {n.clave: n for n in Notificacion.query.filter_by(usuario_id=usuario.id, automatica=True)}

    for clave, n in existentes.items():
        if clave not in vigentes:
            db.session.delete(n)
    for clave, datos in vigentes.items():
        if clave in existentes:
            n = existentes[clave]
            n.titulo, n.mensaje, n.nivel, n.url = datos["titulo"], datos["mensaje"], datos["nivel"], datos["url"]
        else:
            db.session.add(Notificacion(usuario_id=usuario.id, clave=clave, automatica=True, **datos))

    # Limpieza: avisos de evento leídos hace más de 30 días
    limite = datetime.now() - timedelta(days=30)
    Notificacion.query.filter(Notificacion.usuario_id == usuario.id, Notificacion.automatica.is_(False),
                              Notificacion.leida.is_(True), Notificacion.creada_en < limite
                              ).delete(synchronize_session=False)
    try:
        db.session.commit()
    except IntegrityError:  # otra petición simultánea ya creó el mismo aviso
        db.session.rollback()


def notificar(usuarios, tipo, titulo, mensaje=None, url=None, nivel="info", clave=None):
    """Aviso de evento para una lista de usuarios (sin commit)."""
    clave = clave or f"{tipo}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    for u in {u.id: u for u in usuarios if u is not None}.values():
        if Notificacion.query.filter_by(usuario_id=u.id, clave=clave).first():
            continue
        db.session.add(Notificacion(usuario_id=u.id, tipo=tipo, nivel=nivel, titulo=titulo[:150],
                                    mensaje=(mensaje or "")[:300] or None, url=url, clave=clave[:120]))


def usuarios_con_rol(*roles):
    return Usuario.query.filter(Usuario.rol.in_(roles), Usuario.activo.is_(True),
                                Usuario.estado_permiso == "aprobado").all()


def usuarios_del_cliente(cliente_id):
    if not cliente_id:
        return []
    return Usuario.query.filter_by(rol="cliente", cliente_id=cliente_id, activo=True).all()
