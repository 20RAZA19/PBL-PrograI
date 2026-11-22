"""Reglas de la mensajería asistente de ventas ↔ cliente."""
from datetime import datetime, timedelta

from flask import current_app, url_for
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Conversacion, Mensaje
from app.notificaciones.servicios import notificar, usuarios_con_rol, usuarios_del_cliente

MAX_TEXTO = 1000


def dias_retencion():
    return current_app.config.get("MENSAJES_RETENCION_DIAS", 30)


def purgar_conversaciones(dias=None):
    """Borra las conversaciones no guardadas sin actividad en `dias`. Devuelve cuántas se fueron.

    Se llama al abrir la bandeja (barato) y desde `flask purgar-mensajes`, así no
    depende de una tarea programada para cumplir la promesa de los 30 días.
    """
    dias = dias_retencion() if dias is None else dias
    limite = datetime.now() - timedelta(days=dias)
    viejas = Conversacion.query.filter(Conversacion.guardada.is_(False),
                                       Conversacion.ultima_actividad < limite).all()
    for c in viejas:
        db.session.delete(c)
    if viejas:
        db.session.commit()
    return len(viejas)


def conversaciones_de(usuario):
    """Bandeja según el rol (consulta sin ejecutar, para paginarla): el cliente ve las
    de su empresa; Ventas y Admin, todas."""
    q = Conversacion.query.options(selectinload(Conversacion.mensajes), selectinload(Conversacion.cliente))
    if usuario.rol == "cliente":
        q = q.filter_by(cliente_id=usuario.cliente_id)
    return q


def sin_leer_total(usuario):
    """Para el contador del menú."""
    if usuario.rol == "cliente":
        if not usuario.cliente_id:
            return 0
        return (Mensaje.query.join(Conversacion).filter(Conversacion.cliente_id == usuario.cliente_id,
                                                          Mensaje.de_cliente.is_(False), Mensaje.leido.is_(False)).count())
    if usuario.rol in ("admin", "ventas"):
        return Mensaje.query.filter(Mensaje.de_cliente.is_(True), Mensaje.leido.is_(False)).count()
    return 0


def marcar_leidos(conversacion, usuario):
    """Los mensajes del otro lado quedan leídos cuando este usuario abre la conversación."""
    de_cliente = usuario.rol != "cliente"
    cambios = False
    for m in conversacion.mensajes:
        if m.de_cliente == de_cliente and not m.leido:
            m.leido = True
            cambios = True
    return cambios


def enviar(conversacion, autor, texto):
    """Agrega un mensaje, actualiza la actividad y avisa al otro lado (sin commit)."""
    texto = " ".join(texto.split("\r")).strip()[:MAX_TEXTO]
    if not texto:
        return None
    m = Mensaje(conversacion=conversacion, autor=autor, de_cliente=(autor.rol == "cliente"), texto=texto)
    db.session.add(m)
    conversacion.ultima_actividad = datetime.now()
    db.session.flush()
    url = url_for("mensajes.detalle", conversacion_id=conversacion.id)
    extracto = texto if len(texto) <= 120 else texto[:117] + "…"
    if m.de_cliente:
        notificar(usuarios_con_rol("ventas", "admin"), "mensaje",
                  f"{conversacion.cliente.nombre} escribió: {conversacion.asunto}", extracto, url,
                  clave=f"msg-{m.id}")
    else:
        notificar(usuarios_del_cliente(conversacion.cliente_id), "mensaje",
                  f"Arte y Color respondió: {conversacion.asunto}", extracto, url, nivel="ok",
                  clave=f"msg-{m.id}")
    return m
