"""Lógica del bot de WhatsApp, independiente de Twilio.

`procesar(telefono, texto)` recibe el número que escribe y su mensaje, y devuelve
el texto de respuesta. Lo usan el webhook real y el simulador interno, así que
ambos se comportan exactamente igual.

Reglas:
* Solo responde con datos a un número registrado en un perfil de cliente activo
  y aprobado. A cualquier otro número le contesta lo mismo, sin revelar si existe.
* Nunca da precios ni permite solicitar o cambiar nada: el token y ESTADO son de
  solo lectura. La contraseña se recupera por correo, no por el bot.
* Cada mensaje queda en la bitácora con el número enmascarado (nunca el token ni
  el código), y un número no puede mandar más de WHATSAPP_MAX_MENSAJES en 15 min.
"""
import hashlib
import unicodedata
from datetime import datetime, timedelta

from flask import current_app, has_request_context, url_for

from app.auditoria import registrar_accion
from app.models import Auditoria, Usuario
from app.seguimiento.routes import pedidos_del_token

VENTANA_MIN = 15
MENSAJE_NO_REGISTRADO = ("Hola 👋 Este número no está vinculado a ningún perfil de cliente de Arte y Color. "
                         "Pide al equipo que lo registre en tu perfil y vuelve a escribir.")
MENSAJE_SATURADO = f"Has enviado demasiados mensajes. Espera {VENTANA_MIN} minutos e inténtalo de nuevo."


def digitos(texto):
    return "".join(c for c in (texto or "") if c.isdigit())


def normalizar(texto):
    sin_acentos = "".join(c for c in unicodedata.normalize("NFD", texto or "") if unicodedata.category(c) != "Mn")
    return " ".join(sin_acentos.upper().split())


def _coincide(registrado, remitente):
    """El teléfono guardado puede carecer de código de país: basta con que uno termine en el otro."""
    if len(registrado) < 8 or len(remitente) < 8:
        return False
    corto, largo = sorted((registrado, remitente), key=len)
    return largo.endswith(corto)


def usuario_por_telefono(telefono):
    """Perfil de cliente dueño del número, o None si no hay exactamente uno."""
    remitente = digitos(telefono)
    if len(remitente) < 8:
        return None
    candidatos = [u for u in Usuario.query.filter(Usuario.rol == "cliente", Usuario.activo.is_(True),
                                                  Usuario.estado_permiso == "aprobado",
                                                  Usuario.cliente_id.isnot(None),
                                                  Usuario.telefono.isnot(None)).all()
                  if _coincide(u.telefono_digitos, remitente)]
    return candidatos[0] if len(candidatos) == 1 else None


def _huella(remitente):
    return hashlib.sha256(remitente.encode()).hexdigest()[:8]


def _saturado(remitente):
    desde = datetime.now() - timedelta(minutes=VENTANA_MIN)
    enviados = Auditoria.query.filter(Auditoria.accion == "whatsapp", Auditoria.fecha >= desde,
                                      Auditoria.descripcion.contains(f"[{_huella(remitente)}]", autoescape=True)).count()
    return enviados >= current_app.config.get("WHATSAPP_MAX_MENSAJES", 20)


def _registrar(remitente, detalle, usuario=None):
    mascara = f"···{remitente[-4:]}" if remitente else "(sin número)"
    registrar_accion("whatsapp", "WhatsApp", f"WhatsApp {mascara} [{_huella(remitente)}]: {detalle}"[:300],
                     usuario=usuario)


def _enlace(endpoint):
    """URL pública del sitio; fuera de una petición (pruebas, CLI) devuelve solo la ruta."""
    if has_request_context():
        return url_for(endpoint, _external=True)
    return current_app.url_map.bind(current_app.config.get("SERVER_NAME") or "localhost").build(endpoint)


# --- Comandos ------------------------------------------------------------------
def _menu(usuario):
    return (f"Hola, {usuario.nombre.split()[0]} ({usuario.cliente.nombre}). Escribe una palabra:\n"
            "• ESTADO – avance de tus pedidos\n"
            "• TOKEN – tu llave de seguimiento para la web\n"
            "• NUEVO TOKEN – reemplazar la llave (la anterior deja de servir)\n"

            "• MENÚ – ver estas opciones")


def _token(usuario, nuevo=False):
    if nuevo or not usuario.token_seguimiento:
        usuario.generar_token()
    enlace = _enlace("seguimiento.consulta")
    cabecera = "Tu nuevo token es" if nuevo else "Tu token de seguimiento es"
    return (f"{cabecera}: {usuario.token_seguimiento}\n"
            f"Úsalo junto con los últimos 4 dígitos de este teléfono en {enlace} "
            "para ver el estado de tus pedidos. Es de solo lectura: no sirve para solicitar ni ver precios.")


def _estado(usuario):
    activos, entregados = pedidos_del_token(usuario)
    if not activos:
        texto = f"{usuario.cliente.nombre} no tiene pedidos en proceso."
    else:
        lineas = [f"Pedidos en proceso de {usuario.cliente.nombre}:"]
        for p in activos[:8]:
            entrega = p.fecha_limite.strftime("%d/%m") if p.fecha_limite else "sin fecha"
            lineas.append(f"• {p.folio} · {p.modelo_prenda} · {p.estado} ({p.fase_actual}/{p.total_fases}) · entrega {entrega}")
        if len(activos) > 8:
            lineas.append(f"…y {len(activos) - 8} más.")
        texto = "\n".join(lineas)
    if entregados:
        texto += f"\nEntregados: {len(entregados)}."
    return texto + f"\nDetalle con tu token en {_enlace('seguimiento.consulta')}"


def _recuperar(usuario):
    """La recuperación ya no pasa por WhatsApp: el código llega al correo registrado."""
    return ("Por seguridad, la contraseña se recupera por correo. Entra a "
            f"{_enlace('auth.recuperar')} y escribe tu correo: te enviaremos un código de 6 dígitos.")


COMANDOS = {
    "ESTADO": _estado, "PEDIDOS": _estado, "AVANCE": _estado,
    "TOKEN": _token, "MI TOKEN": _token, "LLAVE": _token,
    "NUEVO TOKEN": lambda u: _token(u, nuevo=True), "REGENERAR": lambda u: _token(u, nuevo=True),
    "RECUPERAR": _recuperar, "CONTRASENA": _recuperar, "CLAVE": _recuperar,
}


def procesar(telefono, texto):
    """Devuelve (respuesta, usuario). No hace commit: quien llama decide cuándo guardar."""
    remitente = digitos(telefono)
    if _saturado(remitente):
        return MENSAJE_SATURADO, None
    usuario = usuario_por_telefono(telefono)
    comando = normalizar(texto)
    if usuario is None:
        _registrar(remitente, "número no registrado")
        return MENSAJE_NO_REGISTRADO, None
    accion = COMANDOS.get(comando)
    _registrar(remitente, comando[:40] if accion else "menú", usuario=usuario)
    return (accion(usuario) if accion else _menu(usuario)), usuario
