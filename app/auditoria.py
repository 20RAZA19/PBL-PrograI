"""Bitácora de auditoría automática.

Cada vez que SQLAlchemy guarda cambios (flush) dentro de una petición web,
se registra en la tabla `auditoria` quién creó, editó o eliminó cada registro
y qué campos cambiaron. No hace falta llamar nada desde las vistas.

Los comandos de consola (flask seed / flask demo) no se auditan porque no hay
un usuario que haya hecho el cambio.
"""
import json
from datetime import date, datetime
from decimal import Decimal

from flask import current_app, g, has_request_context, request
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.extensions import db

# Entidades que se auditan y su nombre legible
ENTIDADES = {
    "Usuario": "Usuario",
    "Insumo": "Insumo",
    "Cliente": "Cliente",
    "Proveedor": "Proveedor",
    "Diseno": "Diseño",
    "DisenoTela": "Ficha técnica",
    "Pedido": "Pedido",
    "EventoRastreo": "Rastreo",
    "Movimiento": "Movimiento de inventario",
    "NotaContacto": "Nota de contacto",
    "Solicitud": "Solicitud",
    "SolicitudLinea": "Prenda solicitada",
    "SolicitudTramo": "Tramo de precio",
    "Cotizacion": "Cotización",
    "CotizacionLinea": "Línea de cotización",
    "OrdenCompra": "Orden de compra",
    "OrdenCompraLinea": "Línea de orden de compra",
    "RegistroCalidad": "Control de calidad",
    "Meta": "Meta de incentivo",
    "PagoIncentivo": "Pago de incentivo",
}

# Campos que no aportan información (o que no deben mostrarse)
CAMPOS_IGNORADOS = {"id", "creado_en", "actualizado_en"}
CAMPOS_SENSIBLES = {"password_hash", "token_seguimiento", "recuperacion_hash", "recuperacion_expira", "recuperacion_intentos"}

ACCIONES = {"crear": "Creó", "editar": "Editó", "eliminar": "Eliminó", "sesion": "Sesión", "consulta": "Consulta",
            "whatsapp": "WhatsApp", "recuperacion": "Recuperación"}


def _texto(valor):
    if valor is None:
        return None
    if isinstance(valor, Decimal):
        return format(valor.normalize(), "f") if valor == valor.to_integral() else str(valor)
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    if isinstance(valor, bool):
        return "Sí" if valor else "No"
    texto = str(valor)
    return texto if len(texto) <= 120 else texto[:117] + "…"


def _etiqueta(obj):
    """Nombre corto y reconocible del registro (sin consultar la base de datos)."""
    datos = obj.__dict__
    for campo in ("folio", "email", "nombre", "codigo", "descripcion"):
        if datos.get(campo):
            if campo == "nombre" and datos.get("codigo"):
                return f"{datos['codigo']} · {datos['nombre']}"
            return str(datos[campo])
    nombre = type(obj).__name__
    if nombre == "Movimiento":
        insumo = datos.get("insumo")
        sufijo = f" en «{insumo.nombre}»" if insumo is not None else ""
        return f"{datos.get('tipo', '')} de {_texto(datos.get('cantidad'))}{sufijo}"
    if nombre == "EventoRastreo":
        pedido = datos.get("pedido")
        return f"{pedido.folio if pedido is not None else 'pedido'} → {datos.get('estado', '')}"
    if nombre == "RegistroCalidad":
        return f"{datos.get('categoria', '')} ({datos.get('cantidad', 0)} prendas · {datos.get('linea', '')})"
    if nombre == "NotaContacto":
        return (datos.get("contenido") or "")[:60]
    return f"#{getattr(obj, 'id', '')}"


def _cambios(obj):
    """{campo: [antes, después]} para los atributos de columna que cambiaron."""
    estado = inspect(obj)
    cambios = {}
    for col in estado.mapper.column_attrs:
        nombre = col.key
        if nombre in CAMPOS_IGNORADOS:
            continue
        historia = estado.attrs[nombre].history
        if not historia.has_changes():
            continue
        antes = historia.deleted[0] if historia.deleted else None
        despues = historia.added[0] if historia.added else None
        if antes == despues:
            continue
        if nombre in CAMPOS_SENSIBLES:
            cambios["contraseña"] = ["••••", "actualizada"]
        else:
            cambios[nombre] = [_texto(antes), _texto(despues)]
    return cambios


def _usuario_actual():
    usuario = g.get("_login_user") if has_request_context() else None
    if usuario is not None and getattr(usuario, "is_authenticated", False):
        return usuario.id, usuario.nombre
    return None, None


def _ip():
    if not has_request_context():
        return None
    return (request.remote_addr or "")[:45] or None


def _al_guardar(session, flush_context):
    """Escucha after_flush: los objetos nuevos ya tienen id y el historial sigue disponible."""
    if not has_request_context() or not current_app.config.get("AUDITORIA_ACTIVA", True):
        return
    from app.models import Auditoria

    usuario_id, usuario_nombre = _usuario_actual()
    filas = []

    def agregar(obj, accion, cambios=None):
        nombre = type(obj).__name__
        if nombre not in ENTIDADES:
            return
        entidad = ENTIDADES[nombre]
        etiqueta = _etiqueta(obj)
        filas.append({
            "fecha": datetime.now(),
            "accion": accion,
            "entidad": entidad,
            "entidad_id": getattr(obj, "id", None),
            "descripcion": f"{ACCIONES[accion]} {entidad.lower()} «{etiqueta}»"[:255],
            "cambios": json.dumps(cambios, ensure_ascii=False) if cambios else None,
            "ip": _ip(),
            "usuario_id": usuario_id,
            "usuario_nombre": usuario_nombre or "Sistema",
        })

    for obj in session.new:
        agregar(obj, "crear", {k: v[1] for k, v in _cambios(obj).items() if v[1] not in (None, "")} or None)
    for obj in session.dirty:
        if session.is_modified(obj, include_collections=False):
            cambios = _cambios(obj)
            if cambios:
                agregar(obj, "editar", cambios)
    for obj in session.deleted:
        agregar(obj, "eliminar")

    if filas:
        session.connection().execute(Auditoria.__table__.insert(), filas)


def registrar_accion(accion, entidad, descripcion, entidad_id=None, usuario=None):
    """Agrega manualmente una entrada (por ejemplo, inicios de sesión). No hace commit."""
    from app.models import Auditoria
    if usuario is None:
        usuario_id, usuario_nombre = _usuario_actual()
    else:
        usuario_id, usuario_nombre = usuario.id, usuario.nombre
    db.session.add(Auditoria(
        accion=accion, entidad=entidad, entidad_id=entidad_id, descripcion=descripcion[:255],
        usuario_id=usuario_id, usuario_nombre=usuario_nombre or "Anónimo", ip=_ip(),
    ))


def activar_auditoria():
    """Registra el listener una sola vez por proceso."""
    if not event.contains(Session, "after_flush", _al_guardar):
        event.listen(Session, "after_flush", _al_guardar)


# ---------------------------------------------------------------------------
# Retención: la bitácora no crece sin límite
# ---------------------------------------------------------------------------
ENCABEZADO_CSV = ["Fecha", "Usuario", "Acción", "Entidad", "ID", "Descripción", "Cambios", "IP"]


def fila_bitacora(r):
    """Un registro de auditoría como fila de CSV (ya protegida contra fórmulas de Excel)."""
    from app.utils import fila_csv
    cambios = "; ".join(f"{k}: {v[0] if isinstance(v, list) else ''} → {v[1] if isinstance(v, list) else v}"
                        for k, v in r.cambios_dict.items())
    return fila_csv([r.fecha.strftime("%Y-%m-%d %H:%M:%S"), r.usuario_nombre or "", r.accion, r.entidad,
                     r.entidad_id or "", r.descripcion, cambios, r.ip or ""])


def carpeta_respaldos():
    import os
    from flask import current_app
    ruta = os.path.join(current_app.instance_path, "respaldos")
    os.makedirs(ruta, exist_ok=True)
    return ruta


def listar_respaldos():
    """Respaldos disponibles, del más reciente al más antiguo."""
    import os
    carpeta = carpeta_respaldos()
    archivos = []
    for nombre in os.listdir(carpeta):
        if nombre.startswith("bitacora_") and nombre.endswith(".csv.gz"):
            ruta = os.path.join(carpeta, nombre)
            archivos.append({"nombre": nombre, "bytes": os.path.getsize(ruta),
                             "fecha": datetime.fromtimestamp(os.path.getmtime(ruta))})
    return sorted(archivos, key=lambda a: a["nombre"], reverse=True)


def ruta_respaldo(nombre):
    """Ruta de un respaldo existente o None. Solo acepta nombres generados por el sistema."""
    import os
    import re
    if not re.fullmatch(r"bitacora_[0-9A-Za-z_\-]+\.csv\.gz", nombre or ""):
        return None
    ruta = os.path.join(carpeta_respaldos(), nombre)
    return ruta if os.path.isfile(ruta) else None


def antiguos(dias=None):
    """Consulta de los registros que ya superaron el periodo de retención."""
    from datetime import timedelta
    from flask import current_app
    from app.models import Auditoria
    dias = dias if dias is not None else current_app.config.get("AUDITORIA_RETENCION_DIAS", 90)
    corte = datetime.now() - timedelta(days=max(int(dias), 1))
    return Auditoria.query.filter(Auditoria.fecha < corte), corte


def purgar_bitacora(dias=None):
    """Respalda en CSV comprimido los registros más antiguos que la retención y luego los borra.

    Devuelve (cantidad_borrada, nombre_del_respaldo). El archivo se escribe ANTES de borrar:
    si el respaldo falla, no se elimina nada.
    """
    import csv
    import gzip
    import os
    from datetime import timedelta
    from flask import current_app
    from app.extensions import db
    from app.models import Auditoria

    consulta, corte = antiguos(dias)
    total = consulta.count()
    _limpiar_respaldos_viejos()
    if not total:
        return 0, None

    primero = consulta.order_by(Auditoria.fecha).first().fecha
    nombre = f"bitacora_{primero:%Y-%m-%d}_a_{corte - timedelta(days=1):%Y-%m-%d}_{datetime.now():%H%M%S}.csv.gz"
    ruta = os.path.join(carpeta_respaldos(), nombre)
    escritos = 0
    with gzip.open(ruta, "wt", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(ENCABEZADO_CSV)
        for r in consulta.order_by(Auditoria.fecha, Auditoria.id).yield_per(500):
            escritor.writerow(fila_bitacora(r))
            escritos += 1

    borrados = Auditoria.query.filter(Auditoria.fecha < corte).delete(synchronize_session=False)
    db.session.commit()
    registrar_accion("eliminar", "Bitácora",
                     f"Depuración de bitácora: {borrados} registros anteriores al {corte:%d/%m/%Y} "
                     f"respaldados en {nombre}")
    db.session.commit()
    _compactar_base()
    return borrados, nombre


def _limpiar_respaldos_viejos():
    import os
    from datetime import timedelta
    from flask import current_app
    dias = current_app.config.get("AUDITORIA_RESPALDOS_DIAS", 365)
    if not dias:
        return
    limite = datetime.now() - timedelta(days=dias)
    for r in listar_respaldos():
        if r["fecha"] < limite:
            os.remove(os.path.join(carpeta_respaldos(), r["nombre"]))


def _compactar_base():
    """SQLite no devuelve el espacio al disco al borrar filas: VACUUM reduce el archivo."""
    from sqlalchemy import text
    from app.extensions import db
    if db.engine.dialect.name != "sqlite":
        return
    try:
        with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conexion:
            conexion.execute(text("VACUUM"))
    except Exception:  # compactar es una mejora, nunca debe tumbar la depuración
        pass
