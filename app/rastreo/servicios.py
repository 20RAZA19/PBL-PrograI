"""Lógica compartida del rastreo de pedidos (usada por Kanban y por el módulo de rastreo)."""
from datetime import datetime

from flask import current_app, url_for
from flask_login import current_user

from app.extensions import db
from app.models import EventoRastreo, Pedido, fase_por_estado, ROLES_STAFF


def registrar_evento(pedido, estado=None, ubicacion=None, latitud=None, longitud=None,
                     nota=None, usuario=None):
    """Actualiza el pedido y agrega un evento a su línea de tiempo.

    Si no se envían coordenadas se conservan las últimas conocidas del pedido;
    si el pedido no tiene ninguna, se usa la ubicación del taller.
    """
    if estado:
        pedido.cambiar_estado(estado)

    if ubicacion:
        pedido.ubicacion_actual = ubicacion
    if latitud is not None and longitud is not None:
        pedido.latitud, pedido.longitud = latitud, longitud
    elif not pedido.tiene_coordenadas:
        pedido.latitud = current_app.config["TALLER_LAT"]
        pedido.longitud = current_app.config["TALLER_LNG"]

    evento = EventoRastreo(
        pedido=pedido,
        estado=pedido.estado,
        fase=fase_por_estado(pedido.estado),
        ubicacion=pedido.ubicacion_actual,
        latitud=pedido.latitud,
        longitud=pedido.longitud,
        nota=nota,
        usuario=usuario,
    )
    db.session.add(evento)
    _avisar_cliente(pedido, evento)
    return evento


MENSAJES_CLIENTE = {
    "Recibido": "Recibimos tu pedido y ya está en la cola de producción.",
    "En Corte": "Comenzamos el corte de la tela.",
    "En Costura": "Tu pedido está en confección.",
    "Terminado": "Tu pedido pasó control de calidad y está empacado.",
    "En Ruta": "Tu pedido va en camino.",
    "Entregado": "Tu pedido fue entregado. ¡Gracias por confiar en Arte y Color!",
}


def _avisar_cliente(pedido, evento):
    """Notifica a los usuarios de la empresa cliente cada cambio de fase."""
    from app.notificaciones.servicios import notificar, usuarios_del_cliente
    usuarios = usuarios_del_cliente(pedido.cliente_id or (pedido.cliente.id if pedido.cliente else None))
    if not usuarios:
        return
    db.session.flush()
    notificar(usuarios, "pedido", f"{pedido.folio}: {evento.estado}",
              mensaje=evento.nota or MENSAJES_CLIENTE.get(evento.estado),
              url=url_for("rastreo.detalle", folio=pedido.folio),
              nivel="ok" if evento.estado == "Entregado" else "info",
              clave=f"pedido-{pedido.id}-evento-{evento.id}")


def nuevo_folio_pedido():
    """ORD-AAAAMMDD-NNN, consecutivo por día."""
    prefijo = f"ORD-{datetime.now().strftime('%Y%m%d')}-"
    usados = {f for (f,) in Pedido.query.with_entities(Pedido.folio).filter(Pedido.folio.like(prefijo + "%"))}
    n = len(usados) + 1
    while f"{prefijo}{n:03d}" in usados:
        n += 1
    return f"{prefijo}{n:03d}"


def puede_ver_pedido(pedido, usuario=None):
    """Staff ve todo; un cliente solo los pedidos de su empresa."""
    usuario = usuario or current_user
    if usuario.rol in ROLES_STAFF:
        return True
    return (
        usuario.rol == "cliente"
        and usuario.cliente_id is not None
        and pedido.cliente_id == usuario.cliente_id
    )


def pedidos_visibles(usuario=None):
    """Query base de pedidos filtrada según el rol."""
    usuario = usuario or current_user
    query = Pedido.query
    if usuario.rol == "cliente":
        if usuario.cliente_id is None:
            return query.filter(db.false())
        query = query.filter(Pedido.cliente_id == usuario.cliente_id)
    return query
