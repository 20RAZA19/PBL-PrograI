from flask import Blueprint, render_template
from flask_login import login_required, current_user

faq = Blueprint("faq", __name__)

# Cada pregunta indica qué roles la ven. "todos" = cualquier usuario autenticado.
PREGUNTAS = [
    # --- General ---
    {"categoria": "General", "roles": "todos",
     "pregunta": "¿Qué es AyC Control?",
     "respuesta": "Es la plataforma de Arte y Color para gestionar el inventario de telas, la producción de uniformes y el seguimiento de pedidos en tiempo real."},
    {"categoria": "General", "roles": "todos",
     "pregunta": "¿Cómo activo el modo oscuro?",
     "respuesta": "Usa el botón de luna/sol en la parte superior del menú lateral. Tu preferencia se guarda en este navegador."},
    {"categoria": "Cuenta", "roles": "todos",
     "pregunta": "¿Cómo cambio mi contraseña o mis datos de contacto?",
     "respuesta": "Entra a «Mi Perfil» (haz clic en tu nombre al pie del menú). Ahí puedes actualizar teléfono, cargo, fecha de nacimiento y contraseña."},
    {"categoria": "Cuenta", "roles": "todos",
     "pregunta": "Me registré con un rol interno y no puedo entrar. ¿Por qué?",
     "respuesta": "Las cuentas de Encargado de Taller, Asistente de Ventas y Administrador requieren aprobación. Un administrador revisará tu solicitud; cuando sea aprobada podrás iniciar sesión normalmente."},

    # --- Clientes ---
    {"categoria": "Pedidos", "roles": ["cliente", "admin"],
     "pregunta": "¿Cómo sé en qué fase está mi pedido?",
     "respuesta": "En «Rastrear Pedido» verás cada orden con su barra de progreso. Al abrirla tendrás el mapa con la ubicación actual y la línea de tiempo con cada cambio de fase."},
    {"categoria": "Pedidos", "roles": ["cliente", "admin"],
     "pregunta": "¿Cada cuánto se actualiza el rastreo?",
     "respuesta": "La vista de detalle consulta el estado automáticamente cada pocos segundos. Si el taller registra un cambio, la página se actualiza sola."},
    {"categoria": "Pedidos", "roles": "todos",
     "pregunta": "¿Qué significa cada fase?",
     "respuesta": "Recibido → Corte → Costura → Terminado (control de calidad y empaque) → En Ruta (en camino) → Entregado."},
    {"categoria": "Diseños", "roles": ["cliente", "admin"],
     "pregunta": "¿Dónde veo los diseños de mi empresa?",
     "respuesta": "En «Catálogo de Diseños» aparecen solo las fichas técnicas asociadas a tu empresa, con tallas, telas y una calculadora de consumo."},
    {"categoria": "Diseños", "roles": ["cliente"],
     "pregunta": "No veo ningún pedido ni diseño. ¿Qué hago?",
     "respuesta": "Tu cuenta debe estar vinculada a tu empresa. Si no ves información, contacta a Arte y Color para que un administrador haga la vinculación."},

    # --- Staff ---
    {"categoria": "Inventario", "roles": ["admin", "gestor", "ventas"],
     "pregunta": "¿Cuándo una tela pasa a «Stock Bajo» o «Crítico»?",
     "respuesta": "Cuando sus metros disponibles son iguales o menores al stock mínimo pasa a «Stock Bajo». Si caen a la mitad del mínimo o menos, se marca como «Crítico»."},
    {"categoria": "Inventario", "roles": ["admin", "gestor"],
     "pregunta": "¿Cómo registro una compra de tela?",
     "respuesta": "Desde «Inventario de Insumos» → «Registrar Movimiento», elige la tela y el tipo «Entrada». El historial queda guardado con tu usuario."},
    {"categoria": "Producción", "roles": ["admin", "gestor", "ventas"],
     "pregunta": "¿Cómo avanzo un pedido de fase?",
     "respuesta": "En el «Tablero de Producción» usa las flechas de cada tarjeta. Para registrar una ubicación exacta (por ejemplo, cuando el pedido sale a ruta) abre el rastreo del pedido y haz clic en el mapa."},
    {"categoria": "Producción", "roles": ["admin", "gestor"],
     "pregunta": "¿Cómo descuento tela consumida por un pedido?",
     "respuesta": "En el detalle de rastreo del pedido encontrarás «Consumo de material». La salida se registra en el historial de la tela y queda ligada al pedido."},
    {"categoria": "Inventario", "roles": ["admin", "gestor"],
     "pregunta": "¿Por qué no me deja guardar un color o código Pantone?",
     "respuesta": "Para evitar confusiones en las especificaciones, cada color y cada código Pantone deben ser únicos dentro de la misma categoría de insumo. El formulario te indica qué insumo ya lo usa."},
    {"categoria": "Inventario", "roles": ["admin", "gestor"],
     "pregunta": "¿Qué pasa si busco un insumo que no existe?",
     "respuesta": "La lista te ofrece registrarlo en ese momento con el nombre que buscaste. Al elegir la categoría, el sistema sugiere la unidad de medida y el stock mínimo habituales."},
    {"categoria": "Contactos", "roles": ["admin", "ventas", "gestor"],
     "pregunta": "¿Dónde registro clientes y proveedores?",
     "respuesta": "En «Contactos». Ventas y el Administrador pueden registrarlos y editarlos; el Encargado de Taller los consulta. Cada ficha guarda un historial de notas que no se puede borrar."},
    {"categoria": "Contactos", "roles": ["admin", "ventas"],
     "pregunta": "Estoy tomando un pedido y el cliente no está registrado. ¿Qué hago?",
     "respuesta": "En el formulario de nuevo pedido usa «¿Cliente nuevo? Regístralo primero». Al guardar sus datos vuelves al pedido con el cliente ya seleccionado."},
    {"categoria": "Pedidos", "roles": "todos",
     "pregunta": "¿Puedo imprimir o guardar en PDF la ficha de una orden?",
     "respuesta": "Sí. Abre el pedido en «Rastrear Pedido» y pulsa «Ficha de la orden». Usa «Imprimir / Guardar PDF» en la hoja que se abre."},
    {"categoria": "General", "roles": "todos",
     "pregunta": "¿Qué es el asistente del botón «¿Necesitas ayuda?»?",
     "respuesta": "Es un asistente que funciona dentro del sistema, sin servicios externos. Te explica paso a paso cómo hacer cualquier gestión según tu rol, y responde datos rápidos como cuántos pedidos tienes o en qué fase va un folio."},
    {"categoria": "Ventas", "roles": ["admin", "ventas"],
     "pregunta": "¿Cómo preparo una cotización en PDF?",
     "respuesta": "En «Cotizaciones» → «Nueva Cotización» elige el cliente y agrega prendas (al elegir un diseño se trae su precio). Guarda el borrador, revisa el PDF y márcala como enviada. Cuando el cliente la acepte, pulsa «Convertir en pedidos»."},
    {"categoria": "Ventas", "roles": ["cliente"],
     "pregunta": "¿Cómo acepto una cotización?",
     "respuesta": "En «Mis Cotizaciones» abre la propuesta. Mientras esté vigente verás los botones «Aceptar» y «Rechazar», además del PDF para descargar."},
    {"categoria": "Ventas", "roles": ["admin", "ventas"],
     "pregunta": "¿Cómo se calcula el costo y la ganancia por prenda?",
     "respuesta": "Costo = Σ (cantidad de cada insumo de la ficha técnica × su costo) + mano de obra. Ganancia = precio de venta − costo. Se consulta en «Costos y Márgenes»; los márgenes menores al 15 % aparecen como alerta."},
    {"categoria": "Inventario", "roles": ["admin", "gestor"],
     "pregunta": "¿Cómo sabe el sistema cuánto comprar?",
     "respuesta": "En «Compras» se suma lo que necesitan los pedidos en Recibido, Corte y Costura según su ficha técnica, se resta el stock y lo que ya viene en camino, y se propone lo necesario para quedar en 1.5 veces el stock mínimo. Al recibir la orden, el inventario se actualiza solo."},
    {"categoria": "Producción", "roles": ["admin", "gestor", "ventas"],
     "pregunta": "¿Cómo se mide la calidad por línea de producción?",
     "respuesta": "Cada defecto o reproceso se registra con la línea donde se originó. La tasa es prendas afectadas ÷ prendas que pasaron por esa línea; la meta es 3 % como máximo."},
    {"categoria": "General", "roles": "todos",
     "pregunta": "¿Qué son las notificaciones de la campana?",
     "respuesta": "Avisos sobre lo que requiere tu atención: pedidos que vencen en 3 días o menos, insumos críticos, compras atrasadas, defectos, cotizaciones y cambios de fase de tus pedidos. Los automáticos desaparecen cuando se resuelve la situación."},
    {"categoria": "Diseños", "roles": ["admin", "gestor", "ventas"],
     "pregunta": "¿Cómo subo la foto de un diseño o de una tela?",
     "respuesta": "Edita el diseño o el insumo y usa el campo «Foto». Se aceptan PNG, JPG, WEBP o GIF de hasta 5 MB."},
    {"categoria": "Administración", "roles": ["admin"],
     "pregunta": "¿Qué muestra el Centro de Atención del dashboard?",
     "respuesta": "Los indicadores con semáforo (entregas a tiempo, margen, defectos, inventario y cotizaciones ganadas) y una lista priorizada de lo que conviene revisar: pedidos vencidos o en riesgo, falta de material, insumos críticos, líneas con muchos defectos, márgenes bajos, proveedores atrasados y más."},
    {"categoria": "Administración", "roles": ["admin"],
     "pregunta": "¿Cómo veo quién hizo un cambio?",
     "respuesta": "En «Bitácora de Auditoría» cada alta, cambio o baja queda registrada con el usuario, la fecha, la IP y el valor anterior y nuevo de cada campo. También se registran los inicios de sesión."},
    {"categoria": "Administración", "roles": ["admin"],
     "pregunta": "¿Dónde veo reportes y exporto la información a Excel?",
     "respuesta": "En «Reportes» tienes puntualidad de entregas, pedidos vencidos, consumo de insumos y actividad del equipo, además de botones para descargar pedidos, inventario, movimientos y contactos en CSV."},
    {"categoria": "Administración", "roles": ["admin"],
     "pregunta": "¿Cómo apruebo a un nuevo empleado?",
     "respuesta": "En «Gestión de Usuarios» verás las solicitudes pendientes. Puedes aprobarlas, rechazarlas o editar el rol antes de aprobar."},
    {"categoria": "Administración", "roles": ["admin"],
     "pregunta": "¿Cómo vinculo un cliente con su empresa?",
     "respuesta": "Edita el usuario en «Gestión de Usuarios» y selecciona la empresa en «Empresa vinculada». Solo verá los pedidos y diseños de esa empresa."},
]


@faq.route("/")
@login_required
def index():
    visibles = [p for p in PREGUNTAS
                if p["roles"] == "todos" or current_user.rol in p["roles"]]
    categorias = []
    for p in visibles:
        if p["categoria"] not in categorias:
            categorias.append(p["categoria"])
    return render_template("faq/index.html", preguntas=visibles, categorias=categorias)
