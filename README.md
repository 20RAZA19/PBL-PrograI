# PBL-PrograI — AyC Control

Sistema de gestión de inventario, producción y rastreo de pedidos para **Arte y Color**.

## Cómo ejecutar
1. `python -m venv venv`
2. `venv\Scripts\Activate`
3. `pip install -r requirements.txt`
4. `flask db upgrade` &nbsp;← aplica las migraciones (rastreo, contactos, cotizaciones, compras, calidad, notificaciones, bitácora, WhatsApp y mensajes, solicitudes con aprobación, metas e incentivos y periodo de metas)
5. `flask seed` &nbsp;← datos mínimos de ejemplo (idempotente, solo crea lo que falte)
6. *(Opcional)* `flask demo` &nbsp;← datos de **demostración** para presentar el sistema: clientes, proveedores, insumos con costo y foto, diseños con precio y ficha completa, pedidos con recorrido en el mapa, seis meses de historial para los gráficos, cotizaciones, órdenes de compra, registros de calidad, **solicitudes de prendas en todos sus estados** (pendiente, cotización lista, en producción, denegada, declinada y vencida) **tokens de seguimiento** para los dos clientes, **metas e incentivos** de ejemplo (con y sin periodo) y conversaciones con el asistente de ventas. No duplica nada: si ya lo corriste antes, solo completa lo nuevo. Al terminar imprime el token y los últimos 4 dígitos de cada cliente para probar `/seguimiento`.
7. `python run.py`
8. `python -m pytest` &nbsp;← corre las pruebas automáticas (ver más abajo)

## Cuentas de prueba (después de `flask seed`)
| Rol | Usuario | Contraseña |
|---|---|---|
| Administrador *(solo en tu computadora; en el servidor ver la nota de abajo)* | `admin123` | `admin123` |
| Encargado de Taller | `gestor@arteycolor.com` | `gestor123` |
| Asistente de Ventas *(con `flask demo`)* | `ventas@arteycolor.com` | `ventas123` |
| Cliente | `cliente@banconacional.com` | `cliente123` |
| Cliente 2 *(con `flask demo`)* | `colegio@sanjose.edu.sv` | `cliente123` |

También se crea una solicitud pendiente (`nuevo.gestor@arteycolor.com`) para probar el panel de usuarios.

> **Estas contraseñas son públicas (están en este README).** Solo sirven en tu computadora. En el servidor en línea corre `flask claves-demo` para cambiarlas por claves aleatorias, y crea tu propio administrador con `flask crear-admin` (ver «Seguridad»).

## Módulos y permisos (RBAC)
Roles según la sección 3 del documento de requerimientos.

| Módulo | Ruta | Admin | Taller | Ventas | Cliente |
|---|---|:-:|:-:|:-:|:-:|
| Dashboard con KPIs y gráficos | `/dashboard` | ✔ | ✔ | ✔ | Portal propio |
| Inventario: consultar | `/telas/` | ✔ | ✔ | ✔ | — |
| Inventario: registrar / mover stock | `/telas/nueva`, `/telas/movimiento` | ✔ | ✔ | — | — |
| Tablero de producción: consultar | `/pedidos/kanban` | ✔ | ✔ | ✔ | — |
| Tablero de producción: cambiar fase | | — | ✔ | — | — |
| Contactos (RF-04): consultar | `/contactos/` | ✔ | ✔ | ✔ | — |
| Contactos: registrar, editar y añadir notas | | ✔ | — | ✔ | — |
| Rastreo (mapa + línea de tiempo) | `/rastreo/` | editar | editar | ver | sus pedidos |
| Ficha imprimible de la orden | `/rastreo/<folio>/ficha` | ✔ | ✔ | ✔ | sus pedidos |
| Catálogo de diseños | `/catalogo/` | ✔ | ✔ | ✔ | su empresa |
| Búsqueda global | `/reportes/buscar` | ✔ | ✔ | ✔ | sus pedidos |
| Reportes globales + exportar CSV | `/reportes/` | ✔ | — | — | — |
| Metas e incentivos: mis metas | `/metas/` | — | ✔ | ✔ | — |
| Metas e incentivos: equipo, crear, editar, activar, cerrar mes y pagar | `/metas/equipo` | ✔ | — | — | — |
| Gestión de usuarios | `/admin/usuarios` | ✔ | — | — | — |
| Asistente virtual (botón «¿Necesitas ayuda?») | `/asistente/preguntar` | ✔ | ✔ | ✔ | ✔ |
| Solicitudes de prendas: consultar | `/solicitudes/` | ✔ | ✔ | ✔ | las suyas |
| Solicitudes: proponer, retirar, aceptar o declinar | `/solicitudes/nueva` | — | — | — | ✔ |
| Solicitudes: aprobar con tramos, denegar, renovar vigencia | `/solicitudes/<id>` | ✔ | — | ✔ | — |
| Seguimiento con token (sin sesión) | `/seguimiento` | público | | | con su token |
| Token de seguimiento: generar / regenerar | `/admin/usuarios/<id>/editar` | ✔ | — | — | por WhatsApp |
| Bot de WhatsApp: simulador | `/whatsapp/simulador` | ✔ | — | — | — |
| Recuperar contraseña con código | `/auth/recuperar` | público | | | código por correo |
| Mensajes con el asistente de ventas | `/mensajes/` | ✔ | — | ✔ | los de su empresa (abrir, guardar, eliminar) |
| Cotizaciones en PDF: consultar | `/cotizaciones/` | ✔ | ✔ | ✔ | las suyas (aceptar / rechazar) |
| Cotizaciones: crear, enviar y convertir en pedidos | `/cotizaciones/nueva` | ✔ | — | ✔ | — |
| Compras sugeridas y órdenes de compra | `/compras/` | ✔ | ✔ | — | — |
| Costos y márgenes por prenda / pedido | `/costos/` | ✔ | — | ✔ | — |
| Control de calidad: consultar | `/calidad/` | ✔ | ✔ | ✔ | — |
| Control de calidad: registrar y resolver | `/calidad/nuevo` | ✔ | ✔ | — | — |
| Diseños: crear / editar con foto y ficha técnica | `/catalogo/nuevo` | ✔ | ✔ | ✔ | — |
| Notificaciones (campana del menú) | `/notificaciones/` | ✔ | ✔ | ✔ | ✔ |
| Bitácora de auditoría + CSV | `/admin/bitacora` | ✔ | — | — | — |

## Reglas de validación destacadas
- **Colores únicos:** el color (hex) y el código Pantone no se repiten dentro de la misma categoría de insumo (sin distinguir mayúsculas ni espacios).
- Cantidades y stock mínimo no aceptan valores negativos (RF-01).
- Nombres de clientes/proveedores y correos de usuarios no se repiten.
- Las notas de contacto y el historial de movimientos no se editan ni se eliminan (auditoría).

## Módulos de gestión

### Dashboard: indicadores y Centro de Atención
Lo primero que ve el equipo al entrar:
- **Indicadores con semáforo** (verde / amarillo / rojo contra una meta): entregas a tiempo (meta ≥ 90 %),
  margen de ganancia (≥ 25 %), prendas con defecto (≤ 3 %), inventario sin alertas (≥ 85 %) y
  cotizaciones ganadas (≥ 50 %). Las metas están en `app/indicadores.py`.
- **Centro de Atención**: lista ordenada por urgencia (crítico → alerta → sugerencia) con un botón para
  resolver cada punto: pedidos vencidos o en riesgo de atraso, material insuficiente para los pedidos
  activos, insumos críticos, líneas de producción sobre la meta de defectos, casos de calidad abiertos,
  pedidos sin avance en 7 días, márgenes menores al 15 %, diseños sin costo, concentración en un solo
  cliente, cotizaciones por vencer, proveedores atrasados, puntualidad baja y solicitudes de acceso.
  Cada rol ve solo lo que le corresponde.
- **Gráficos con Chart.js** (se cargan desde cdnjs solo en las páginas que los usan; sin internet se muestra un aviso en lugar del gráfico):
  - *Reportes*: pedidos por estado, entregas a tiempo, pedidos por mes, prendas, consumo de telas y, para Administración y Ventas, finanzas. Todo sigue el periodo elegido (7, 30, 90 o 365 días) y compara las cifras con el periodo anterior.
  - *Dashboard del cliente*: pedidos por fase, prendas por mes y porcentaje de entregas a tiempo.
  - *Telas*: existencia de los últimos 60 días frente al stock mínimo.
  - *Solicitudes*: solicitudes recibidas y aceptadas por semana.
  - *Costos*: los 10 pedidos con menor margen.
  - *Bitácora*: actividad de los últimos 14 días y módulos con más cambios.
  - *Metas*: incentivo por persona e historial.
  - Cada gráfico tiene «Ver datos» para ver las cifras en tabla. Los colores se distinguen también con daltonismo.

### Metas e incentivos
Cada meta mide un indicador («Qué se mide») y el indicador define el área: Taller (gestor) o Ventas.
«Para quién» solo muestra personas de esa área, y el servidor lo valida también.

- **Indicadores de Taller:** prendas entregadas, prendas terminadas, avances de fase, entregas a tiempo y prendas con defecto (de todo el taller).
- **Indicadores de Ventas:** solicitudes respondidas, solicitudes que pasaron a producción, monto vendido y tiempo de respuesta promedio.
- **Periodo:** cada meta tiene «Desde» y «Hasta» (máximo 366 días). Solo cuentan los hechos dentro del periodo; por ejemplo, un pedido que se entregó antes del periodo no suma en «Prendas entregadas».
- **Pago:** una meta se paga al cerrar el mes en que termina su periodo. Administración cierra el mes en **Metas e incentivos** y puede exportar el resumen en CSV (`/metas/equipo.csv`).
- Taller y Ventas ven sus metas en **Mis metas**, con el avance del mes y el historial de incentivos.

### Costo por prenda
`costo = Σ (cantidad del insumo en la ficha técnica × costo unitario del insumo) + mano de obra`.
La ficha técnica de cada diseño admite telas, hilos, botones, cierres y etiquetas (en la unidad de
cada insumo). Con el precio de venta se obtiene la ganancia y el margen por prenda y por pedido.

### Cotizaciones en PDF
Folio `COT-AAAA-NNNN`, descuento, IVA (13 % por defecto), validez y fecha de entrega. Flujo:
borrador → enviada (el cliente la ve en su portal y recibe un aviso) → aceptada / rechazada →
**convertir en pedidos** (uno por prenda, con el precio acordado). El PDF se genera con
`reportlab`; si no está instalado se muestra una versión imprimible en HTML.

### Órdenes de compra automáticas
`sugerido = stock mínimo × 1.5 − (disponible + en camino − consumo pendiente de los pedidos en
Recibido, Corte y Costura)`, redondeado (metros de 5 en 5, unidades de 10 en 10). Se agrupa por el
proveedor habitual de cada insumo. Al **recibir** la orden se suma el stock, se registra la entrada
y se actualiza el costo del insumo.

### Control de calidad
Defectos y reprocesos por pedido y por línea (Corte, Costura, Bordado y Estampado, Acabados y
Empaque). Tasa por línea = prendas afectadas ÷ prendas que pasaron por esa línea.

### Notificaciones
Automáticas (desaparecen al resolverse): pedidos que vencen en ≤ 3 días o vencidos, insumos
críticos, órdenes de compra atrasadas, cotizaciones por vencer y solicitudes de acceso.
De evento: cambio de fase del pedido (para el cliente), cotización recibida / respondida y defectos.

### Bitácora de auditoría
`app/auditoria.py` escucha cada guardado de SQLAlchemy dentro de una petición y registra quién creó,
editó o eliminó cada registro, con los valores antes → después (las contraseñas nunca se guardan).
También registra inicios y cierres de sesión e intentos fallidos. Los comandos `flask seed/demo` no se auditan.
La pantalla muestra una gráfica de actividad de los últimos 14 días y los módulos con más cambios. Las fechas se muestran en hora local (`ZONA_HORARIA`), no en la hora UTC del servidor.

### Fotos
Diseños e insumos aceptan PNG, JPG, WEBP o GIF de hasta 5 MB. Se valida el contenido real del archivo
(no solo la extensión) y se guardan en `app/static/uploads/` con un nombre aleatorio.

## Pruebas automáticas
```
pip install -r requirements.txt
python -m pytest
```
Las pruebas (`tests/`) usan una base de datos en memoria con datos conocidos, así que no tocan
`instance/inventario.db`. Cubren cálculos de costos y totales, compras sugeridas, flujo completo de
cotizaciones, control de calidad, notificaciones, bitácora, subida de fotos, indicadores del dashboard,
la matriz de permisos por rol, el asistente, las metas y su periodo, la validación de teléfonos repetidos, el tablero kanban y la paginación.

## Asistente virtual
Funciona **localmente** (sin APIs externas): `app/asistente/conocimiento.py` contiene las gestiones
del sistema y `app/asistente/motor.py` las reconoce aunque haya conjugaciones o errores de tipeo.
Responde según el rol, avisa cuando una gestión no le corresponde al usuario, consulta datos
rápidos (pedidos activos, insumos en alerta, estado de un folio) y rechaza temas ajenos a la web.
Para agregar una respuesta nueva basta con añadir un diccionario a `INTENCIONES`.

Además de las gestiones, responde con datos reales de quien pregunta: el cliente ve su propio token de seguimiento (el personal nunca ve el de otra persona), cuándo le entregan sus pedidos, el estado de sus solicitudes y cotizaciones, sus mensajes y cómo va con sus metas.

Los roles se validan con `@login_required` + `@roles_required(...)` (ver `app/decorators.py`).

## Solicitudes de prendas (propuesta → aprobación → cotización → producción)
El cliente **propone** prendas desde su portal (**Mis Solicitudes → Solicitar prendas**): por cada prenda indica diseño (opcional), cantidad, tallas, colores y medidas, más la fecha en que la necesita. Solo pueden proponer las cuentas de cliente aprobadas y vinculadas a una empresa.

Ya **no existe el registro manual de pedidos** («Nuevo Pedido»): un pedido nace únicamente cuando el cliente acepta una cotización vigente (de una solicitud aprobada o de una cotización en PDF aceptada).

| Estado | Quién | Qué pasa |
|---|---|---|
| Pendiente de revisión | Cliente | Llega al panel **«Aprobaciones pendientes»** del dashboard y como aviso a Ventas y Administración. El cliente puede retirarla. |
| Cotización lista | Ventas / Admin | Aprueba con **precios por cantidad** (precio base + hasta 3 rebajas por volumen) y, si aplica, **condiciones de cambio** (texto libre + etiquetas: mínimo de pedido, color no disponible…). Se publica una cotización con **15 días de vigencia** (`COTIZACION_VIGENCIA_DIAS`) que el cliente ve en «Mis Solicitudes» y «Mis Cotizaciones». |
| En producción | **Cliente** | Solo si **él acepta** la cotización vigente se crea un pedido por prenda, con el precio del tramo que alcanza su cantidad. Una propuesta pendiente o denegada jamás entra a producción. |
| Denegada | Ventas / Admin | Con motivo obligatorio, visible para el cliente. |
| Declinada | Cliente | Rechaza la cotización (motivo opcional). Ventas recibe el aviso. |
| Cotización vencida | Sistema | Pasados los 15 días ya no se puede aceptar; Ventas puede **renovar la vigencia** y se avisa al cliente. |

Al aceptar, el cliente acepta también las condiciones de la aprobación. Límites: 20 prendas distintas por solicitud y 10 propuestas sin revisar por empresa. Las cotizaciones en PDF siguen disponibles en «Mis Cotizaciones».

## Seguimiento con token
Cada cliente puede tener un **token de seguimiento** (por ejemplo `AYC-7K3P-9WQ2`). Es una llave de **solo lectura**: en `/seguimiento`, con el token y los últimos 4 dígitos de su teléfono, ve el estado de todos los pedidos de su empresa sin iniciar sesión. No muestra precios y no permite solicitar ni cotizar.

- Lo genera y regenera el Administrador en **Gestión de usuarios → editar cliente** (hace falta tener registrado el teléfono), o el propio cliente escribiendo `TOKEN` / `NUEVO TOKEN` al bot de WhatsApp. Al regenerar, el anterior deja de servir.
- El sitio nunca se lo muestra al cliente: se le entrega por un canal aparte (WhatsApp).
- 8 intentos fallidos desde la misma conexión bloquean la consulta 15 minutos. Cada consulta queda en la bitácora, sin guardar el token.

## Bot de WhatsApp
Responde a los clientes desde su teléfono registrado, sin dar precios ni permitir solicitar nada:

| Comando | Respuesta |
|---|---|
| `ESTADO` | Avance de los pedidos en proceso de su empresa (folio, prenda, fase, entrega) |
| `TOKEN` | Su token de seguimiento (lo crea si no existe) y el enlace a `/seguimiento` |
| `NUEVO TOKEN` | Reemplaza el token; el anterior deja de servir |
| `RECUPERAR` | Indica que la contraseña se recupera por correo en el sitio |
| `MENÚ` o cualquier otro texto | Lista de opciones |

- Solo contesta con datos a un número que coincide con **un** cliente activo y aprobado (sirve con o sin código de país). A cualquier otro número le responde un mensaje genérico, sin revelar si existe.
- Cada mensaje queda en la bitácora con el número enmascarado; nunca el token ni el código. Un mismo número puede mandar 20 mensajes cada 15 minutos (`WHATSAPP_MAX_MENSAJES`).
- **Simulador** (solo Administración → *Bot de WhatsApp*): misma lógica sin WhatsApp real. Sirve para la demo y para probar antes de conectar Twilio.
- **Conectar Twilio Sandbox**: crea la cuenta, une tu teléfono al sandbox, pega `https://<tu-sitio>/whatsapp/webhook` (POST) en *Sandbox settings* y define `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` y `TWILIO_WHATSAPP_FROM` en `.env`. El webhook valida la firma `X-Twilio-Signature` y rechaza todo lo demás; sin `TWILIO_AUTH_TOKEN` responde 503.
- Avisos salientes (cotización lista): `WHATSAPP_AVISOS=1`. Necesitan salida a internet hacia `api.twilio.com`; si falla, el sistema sigue normal.

## Recuperar contraseña (por correo)
En el login, **«Recupérala por correo»** lleva a `/auth/recuperar`. La persona escribe su correo y recibe un código de 6 dígitos desde la cuenta de Gmail del sistema; en `/auth/recuperar/codigo` lo escribe junto con su nueva contraseña. Sirve para clientes y para el equipo.

- El código vale **15 minutos** y **una sola vez**; tras **5** intentos fallidos se invalida (`RECUPERACION_MINUTOS`, `RECUPERACION_MAX_INTENTOS`). Viene en el asunto del correo para verlo sin abrirlo.
- Máximo **3 correos por hora** por cuenta y uno por minuto (`RECUPERACION_MAX_CORREOS_HORA`); además, bloqueo por IP como en el login.
- La respuesta es la misma exista o no el correo. En la base solo se guarda el hash del código y nunca aparece en la bitácora.
- **Configurar Gmail**: activa la verificación en dos pasos en la cuenta que envía, crea una *contraseña de aplicación* en <https://myaccount.google.com/apppasswords> y ponla en `.env` como `MAIL_USERNAME` y `MAIL_PASSWORD`. PythonAnywhere gratuito permite `smtp.gmail.com:587`.
- Sin Gmail configurado, en local el correo se imprime en la terminal donde corre `python run.py` (para probar); en producción no se envía nada.

## Mensajes con el asistente de ventas
El cliente abre conversaciones desde **Mensajes** en su portal; Ventas y Administración las ven todas y responden. El taller no participa.

- Los mensajes nuevos aparecen sin recargar la página (cada 8 s, `MENSAJES_REFRESCO_SEG`) y cada mensaje genera una notificación al otro lado. El menú muestra cuántos hay sin leer.
- **Privacidad**: una conversación se borra sola **30 días** después del último mensaje (`MENSAJES_RETENCION_DIAS`), salvo que el cliente pulse **«Guardar conversación»**. El cliente también puede eliminarla cuando quiera. Su contenido no se copia a la bitácora.
- La limpieza corre sola al abrir la bandeja; para programarla, `flask purgar-mensajes`.

## Retención de la bitácora
La bitácora conserva **90 días** (`AUDITORIA_RETENCION_DIAS`). Lo más antiguo se guarda primero en un CSV comprimido en `instance/respaldos/` y después se borra; la base se compacta para liberar espacio.

- Manual: **Bitácora → Respaldar y depurar**. Ahí mismo se descargan y eliminan los respaldos.
- Automático: programa `flask purgar-bitacora` como tarea diaria (pestaña *Tasks* de PythonAnywhere).
- Los respaldos con más de un año se eliminan solos (`AUDITORIA_RESPALDOS_DIAS`; 0 = nunca).

## Tablero de Producción
Cada tarjeta muestra solo el **folio, el cliente y el tiempo restante**, con un borde de color según la urgencia (rojo = vencido, amarillo = vence en 3 días o menos, verde = a tiempo). En cada columna van primero los pedidos que vencen antes.

Al tocar una tarjeta se abre una **ventana emergente** con toda la información (prenda, cantidad, tallas, colores, fecha límite, avance, diseño, último movimiento, observaciones, defectos de calidad y, para Administración y Ventas, el monto y el margen). Desde ahí el Encargado de Taller mueve el pedido de fase (Administración y Ventas consultan). Con Ctrl + clic (o sin JavaScript) la tarjeta abre la página de rastreo completa.

## Seguridad
| Riesgo | Protección |
|---|---|
| Robo o falsificación de sesión | `SECRET_KEY` aleatoria (variable de entorno o `instance/secret_key`, que no se sube a GitHub); cookie `HttpOnly`, `SameSite=Lax` y, en el servidor, `Secure` (solo HTTPS). La sesión se renueva al iniciar sesión. |
| Adivinar contraseñas (fuerza bruta) | 5 intentos fallidos por cuenta o 20 por IP en 15 minutos bloquean el acceso durante 15 minutos (`LOGIN_MAX_INTENTOS_CUENTA`, `LOGIN_MAX_INTENTOS_IP`, `LOGIN_BLOQUEO_MIN`). Los intentos quedan en la bitácora. |
| Contraseñas débiles | Mínimo 8 caracteres con letras y números; se rechazan las más comunes. Se guardan con hash (nunca en texto plano). |
| Ver pedidos de otra empresa | Un cliente que se registra con el nombre de una empresa que **ya existe** queda pendiente hasta que el administrador lo aprueba. Cada consulta filtra por la empresa del cliente. |
| Formularios falsos desde otro sitio (CSRF) | Token CSRF en todos los formularios y acciones POST (Flask-WTF). |
| Inyección SQL / XSS | Consultas con el ORM (sin SQL armado a mano) y plantillas Jinja con escape automático. |
| Archivos maliciosos | Solo imágenes PNG/JPG/WEBP/GIF verificadas por su contenido, nombre aleatorio y límite de 5 MB. |
| Clickjacking, rastreo de tipos, caché | Cabeceras `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` y HSTS; las páginas privadas se envían con `Cache-Control: no-store`. |
| Redirecciones a sitios externos | Solo se aceptan rutas internas en `next` y `volver`. |
| Fórmulas en Excel | Los CSV exportados neutralizan celdas que empiezan con `= + - @`. |
| Librerías externas | Versiones fijas de Chart.js, Leaflet y Lucide (nada de `@latest`). |

Comandos para el servidor:
- `flask crear-admin` → crea tu administrador con la contraseña que elijas.
- `flask claves-demo` → cambia las contraseñas de las cuentas de demostración por claves aleatorias y las muestra una sola vez (`--desactivar` para apagarlas).

## Publicar en PythonAnywhere
1. **Consola Bash:** `git clone <url-del-repo> PBL-PrograI`, luego `mkvirtualenv ayc --python=python3.13` y `pip install -r PBL-PrograI/requirements.txt`.
2. **Archivo `.env`** dentro de `PBL-PrograI` (pestaña *Files*), tomando `.env.example` como base: una `SECRET_KEY` nueva, `SESSION_COOKIE_SECURE=1` y `DETRAS_DE_PROXY=1`.
3. **Base de datos:** en la consola, dentro de la carpeta: `flask db upgrade`, `flask demo` (si quieres datos de demostración), `flask claves-demo` y `flask crear-admin`.
4. **Pestaña *Web* → Add a new web app → Manual configuration** (misma versión de Python). En *Virtualenv* escribe `ayc`. En el archivo WSGI deja solo:
   ```python
   import sys
   sys.path.insert(0, "/home/<usuario>/PBL-PrograI")
   from run import app as application
   ```
5. En *Static files*: URL `/static/` → carpeta `/home/<usuario>/PBL-PrograI/app/static`.
6. Activa **Force HTTPS** y pulsa **Reload**.

Para actualizar después: `git pull` en la consola, `flask db upgrade` si hubo migraciones y **Reload** en la pestaña *Web*.

## Configuración opcional (`.env`)
- `TALLER_LAT`, `TALLER_LNG`, `TALLER_NOMBRE`: punto de partida de los pedidos en el mapa (por defecto San Salvador).
- `RASTREO_REFRESCO_SEG`: cada cuántos segundos la vista de rastreo consulta cambios (por defecto 20).
- `EMPRESA_NOMBRE`, `EMPRESA_DIRECCION`, `EMPRESA_TELEFONO`, `EMPRESA_EMAIL`, `EMPRESA_NIT`: datos que aparecen en los PDF.
- `UPLOAD_FOLDER`: carpeta de las fotos subidas (por defecto `app/static/uploads`).
- `COTIZACION_VIGENCIA_DIAS`: días de vigencia de la cotización que se publica al aprobar una solicitud (por defecto 15).
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM`, `WHATSAPP_AVISOS`, `WHATSAPP_MAX_MENSAJES`: bot de WhatsApp (ver arriba).
- `RECUPERACION_MINUTOS`, `RECUPERACION_MAX_INTENTOS`, `RECUPERACION_MAX_CORREOS_HORA`: código para recuperar la contraseña (15, 5 y 3).
- `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_REMITENTE` (y `MAIL_SERVER`, `MAIL_PORT`): Gmail que envía los códigos.
- `MENSAJES_RETENCION_DIAS`, `MENSAJES_REFRESCO_SEG`: mensajería con el asistente de ventas (30 y 8).
- `ZONA_HORARIA`: zona horaria del negocio para mostrar fechas y horas (por defecto `America/El_Salvador`; PythonAnywhere usa UTC).
- `WHATSAPP_CODIGO_UNION`: frase para unirse al sandbox de Twilio (por ejemplo «join silver-tiger»); se muestra en la guía del cliente.
