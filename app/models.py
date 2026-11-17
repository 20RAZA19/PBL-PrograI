import json
from datetime import datetime, date, timedelta
from decimal import Decimal
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db, login_manager


# ---------------------------------------------------------------------------
# Constantes de dominio
# ---------------------------------------------------------------------------
ROLES = {
    "admin": "Administrador",
    "gestor": "Encargado de Taller",
    "ventas": "Asistente de Ventas",
    "cliente": "Cliente",
}

# Roles internos de la empresa (ven el dashboard general)
ROLES_STAFF = ("admin", "gestor", "ventas")

TIPOS_NOTA = {
    "comunicacion": "Comunicación",
    "acuerdo": "Acuerdo",
    "requerimiento": "Requerimiento",
}

ESTADOS_PERMISO = {
    "aprobado": "Aprobado",
    "pendiente": "Pendiente",
    "rechazado": "Rechazado",
}

# Impuesto al valor agregado de El Salvador (se puede cambiar por cotización)
IVA_PCT = Decimal("13")

ESTADOS_COTIZACION = {
    "borrador": "Borrador",
    "enviada": "Enviada al cliente",
    "aceptada": "Aceptada",
    "rechazada": "Rechazada",
}

ESTADOS_ORDEN_COMPRA = {
    "borrador": "Borrador",
    "enviada": "Enviada al proveedor",
    "recibida": "Recibida",
    "cancelada": "Cancelada",
}

# Control de calidad: línea (área) donde se detectó el problema y la fase que la representa
LINEAS_PRODUCCION = {
    "Corte": 2,
    "Costura": 3,
    "Bordado y Estampado": 3,
    "Acabados y Empaque": 4,
}
TIPOS_DEFECTO = [
    "Costura defectuosa", "Medida incorrecta", "Mancha o suciedad", "Color distinto al aprobado",
    "Bordado o estampado mal ubicado", "Tela dañada", "Botón o cierre defectuoso", "Otro",
]
TIPOS_REGISTRO_CALIDAD = {"defecto": "Defecto", "reproceso": "Reproceso"}
# Porcentaje máximo de prendas con defectos aceptado por línea
META_DEFECTOS_PCT = 3.0


def _dinero(valor):
    """Convierte a Decimal con 2 decimales (acepta None, float, int, str)."""
    return Decimal(str(valor or 0)).quantize(Decimal("0.01"))


# Fases de producción / rastreo. El índice + 1 es el valor de fase_tracking.
FASES = [
    {"nombre": "Recibido",   "icono": "inbox",          "descripcion": "Orden registrada y validada por el taller."},
    {"nombre": "En Corte",   "icono": "scissors",       "descripcion": "Tendido y corte de tela según ficha técnica."},
    {"nombre": "En Costura", "icono": "shirt",          "descripcion": "Ensamble, confección y acabados."},
    {"nombre": "Terminado",  "icono": "package-check",  "descripcion": "Control de calidad, planchado y empaque."},
    {"nombre": "En Ruta",    "icono": "truck",          "descripcion": "El pedido va en camino a su destino."},
    {"nombre": "Entregado",  "icono": "circle-check-big", "descripcion": "Pedido recibido por el cliente."},
]
NOMBRES_FASES = [f["nombre"] for f in FASES]


def fase_por_estado(estado):
    """Devuelve el número de fase (1..N) para un estado de pedido."""
    try:
        return NOMBRES_FASES.index(estado) + 1
    except ValueError:
        return 1


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
ALFABETO_TOKEN = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sin 0/O, 1/I/L: se dicta sin confusiones


def nuevo_token_seguimiento():
    """Token tipo AYC-7K3P-9WQ2 generado con el módulo secrets (no adivinable)."""
    import secrets
    bloque = lambda: "".join(secrets.choice(ALFABETO_TOKEN) for _ in range(4))
    return f"AYC-{bloque()}-{bloque()}"


def normalizar_token(texto):
    """Acepta el token con o sin guiones, espacios o minúsculas."""
    limpio = "".join(c for c in (texto or "").upper() if c.isalnum())
    if limpio.startswith("AYC"):
        limpio = limpio[3:]
    if len(limpio) != 8:
        return None
    return f"AYC-{limpio[:4]}-{limpio[4:]}"


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    telefono = db.Column(db.String(20))
    fecha_nacimiento = db.Column(db.Date)
    cargo = db.Column(db.String(80))
    rol = db.Column(db.String(20), nullable=False, default="cliente")
    estado_permiso = db.Column(db.String(20), default="aprobado")
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.now)

    # Vínculo opcional con la empresa cliente (solo para rol 'cliente')
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True)
    # Llave de solo lectura para consultar el estado de los pedidos sin iniciar sesión
    token_seguimiento = db.Column(db.String(20), unique=True, nullable=True)
    # Código temporal para recuperar la contraseña (se guarda solo su hash)
    recuperacion_hash = db.Column(db.String(256), nullable=True)
    recuperacion_expira = db.Column(db.DateTime, nullable=True)
    recuperacion_intentos = db.Column(db.Integer, default=0)

    movimientos = db.relationship("Movimiento", back_populates="usuario")
    cliente = db.relationship("Cliente", back_populates="usuarios")
    eventos_rastreo = db.relationship("EventoRastreo", back_populates="usuario")

    def generar_token(self):
        """Crea (o reemplaza) el token de seguimiento. El anterior deja de servir."""
        while True:
            token = nuevo_token_seguimiento()
            if not Usuario.query.filter_by(token_seguimiento=token).first():
                self.token_seguimiento = token
                return token

    @property
    def telefono_digitos(self):
        return "".join(c for c in (self.telefono or "") if c.isdigit())

    # --- Recuperación de contraseña -------------------------------------------------
    def emitir_codigo_recuperacion(self, minutos=15):
        """Genera un código de 6 dígitos válido unos minutos. Se guarda solo su hash,
        así ni la base de datos ni la bitácora revelan el código."""
        import secrets
        codigo = f"{secrets.randbelow(1_000_000):06d}"
        self.recuperacion_hash = generate_password_hash(codigo)
        self.recuperacion_expira = datetime.now() + timedelta(minutes=minutos)
        self.recuperacion_intentos = 0
        return codigo

    def limpiar_codigo_recuperacion(self):
        self.recuperacion_hash = None
        self.recuperacion_expira = None
        self.recuperacion_intentos = 0

    @property
    def codigo_recuperacion_vigente(self):
        return bool(self.recuperacion_hash and self.recuperacion_expira and self.recuperacion_expira > datetime.now())

    def verificar_codigo_recuperacion(self, codigo, max_intentos=5):
        """True si el código coincide y sigue vigente. Cada fallo cuenta; al llegar al
        máximo el código se invalida (hay que pedir otro)."""
        if not self.codigo_recuperacion_vigente:
            return False
        if check_password_hash(self.recuperacion_hash, (codigo or "").strip()):
            return True
        self.recuperacion_intentos = (self.recuperacion_intentos or 0) + 1
        if self.recuperacion_intentos >= max_intentos:
            self.limpiar_codigo_recuperacion()
        return False

    @property
    def puede_solicitar(self):
        """Cliente verificado: cuenta aprobada y vinculada a una empresa."""
        return bool(self.rol == "cliente" and self.activo and self.estado_permiso == "aprobado" and self.cliente_id)

    @property
    def puede_atender_solicitudes(self):
        return self.rol in ("admin", "ventas")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # --- Ayudas de rol (RBAC) ---
    @property
    def es_admin(self):
        return self.rol == "admin"

    @property
    def es_gestor(self):
        return self.rol == "gestor"

    @property
    def es_cliente(self):
        return self.rol == "cliente"

    @property
    def es_ventas(self):
        return self.rol == "ventas"

    @property
    def es_staff(self):
        return self.rol in ROLES_STAFF

    # --- Permisos según el documento de requerimientos (sección 3) ---
    @property
    def puede_editar_inventario(self):
        """Registrar insumos y actualizar stock: Administrador y Encargado de Taller."""
        return self.rol in ("admin", "gestor")

    @property
    def puede_mover_pedidos(self):
        """Cambiar la fase de producción / rastreo: solo el Encargado de Taller.

        El Administrador se concentra en la parte administrativa (usuarios, bitácora,
        aprobaciones); la gestión del taller es del Encargado.
        """
        return self.rol == "gestor"

    @property
    def puede_crear_pedidos(self):
        """Convertir cotizaciones aceptadas en pedidos. Ya no existe el registro manual:
        los pedidos nacen de una cotización o de una solicitud aceptada por el cliente."""
        return self.rol in ROLES_STAFF

    @property
    def puede_gestionar_contactos(self):
        """Registrar clientes/proveedores: Administrador y Asistente de Ventas."""
        return self.rol in ("admin", "ventas")

    @property
    def puede_cotizar(self):
        """Crear y enviar cotizaciones: Administrador y Asistente de Ventas."""
        return self.rol in ("admin", "ventas")

    @property
    def puede_comprar(self):
        """Generar y recibir órdenes de compra: Administrador y Encargado de Taller."""
        return self.rol in ("admin", "gestor")

    @property
    def puede_ver_costos(self):
        """Costos, precios y márgenes: Administrador y Asistente de Ventas."""
        return self.rol in ("admin", "ventas")

    @property
    def puede_registrar_calidad(self):
        return self.rol in ("admin", "gestor")

    @property
    def puede_editar_disenos(self):
        return self.rol in ROLES_STAFF

    @property
    def rol_legible(self):
        return ROLES.get(self.rol, self.rol)

    @property
    def iniciales(self):
        partes = [p for p in (self.nombre or "").split() if p]
        if not partes:
            return "?"
        if len(partes) == 1:
            return partes[0][:2].upper()
        return (partes[0][0] + partes[1][0]).upper()

    @property
    def edad(self):
        if not self.fecha_nacimiento:
            return None
        hoy = date.today()
        n = self.fecha_nacimiento
        return hoy.year - n.year - ((hoy.month, hoy.day) < (n.month, n.day))

    @property
    def puede_ingresar(self):
        return bool(self.activo) and self.estado_permiso == "aprobado"


# ---------------------------------------------------------------------------
# Inventario
# ---------------------------------------------------------------------------
class Insumo(db.Model):
    __tablename__ = "insumos"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=True)
    nombre = db.Column(db.String(150), nullable=False)
    categoria = db.Column(db.String(50), nullable=False, default="Tela")
    unidad_medida = db.Column(db.String(20), nullable=False, default="Metros")
    cantidad_disponible = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    stock_minimo = db.Column(db.Numeric(10, 2), nullable=False, default=10)
    color_hex = db.Column(db.String(7), default="#CCCCCC")
    codigo_pantone = db.Column(db.String(30))
    tipo = db.Column(db.String(80), default="Textil")
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.now)
    actualizado_en = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    # Costo de compra por unidad de medida (USD) y proveedor habitual
    costo_unitario = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    proveedor_id = db.Column(db.Integer, db.ForeignKey("proveedores.id"), nullable=True)
    imagen = db.Column(db.String(255))

    movimientos = db.relationship("Movimiento", back_populates="insumo")
    disenos = db.relationship("DisenoTela", back_populates="tela")
    proveedor = db.relationship("Proveedor", back_populates="insumos")

    @property
    def metros_disponibles(self):
        return self.cantidad_disponible

    @metros_disponibles.setter
    def metros_disponibles(self, value):
        self.cantidad_disponible = value

    @property
    def alerta_stock(self):
        if self.cantidad_disponible <= (self.stock_minimo / 2):
            return "critico"
        elif self.cantidad_disponible <= self.stock_minimo:
            return "bajo"
        return "ok"

    @property
    def estado(self):
        if self.cantidad_disponible <= self.stock_minimo / 2:
            return "Crítico"
        if self.cantidad_disponible <= self.stock_minimo:
            return "Stock Bajo"
        return "Disponible"

    @property
    def cobertura(self):
        """Porcentaje del stock actual respecto al mínimo (100 = justo en el mínimo)."""
        minimo = float(self.stock_minimo or 0)
        if minimo <= 0:
            return 100
        return round(float(self.cantidad_disponible or 0) / minimo * 100)

    @property
    def valor_inventario(self):
        return _dinero(Decimal(str(self.cantidad_disponible or 0)) * _dinero(self.costo_unitario))

    @property
    def tiene_costo(self):
        return _dinero(self.costo_unitario) > 0


Tela = Insumo


# ---------------------------------------------------------------------------
# Directorio
# ---------------------------------------------------------------------------
class Cliente(db.Model):
    __tablename__ = "clientes"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    contacto = db.Column(db.String(100))
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(120))
    notas = db.Column(db.Text)

    creado_en = db.Column(db.DateTime, default=datetime.now)

    disenos = db.relationship("Diseno", back_populates="cliente")
    pedidos = db.relationship("Pedido", back_populates="cliente")
    usuarios = db.relationship("Usuario", back_populates="cliente")
    historial = db.relationship("NotaContacto", back_populates="cliente",
                                order_by="NotaContacto.fecha.desc()")
    cotizaciones = db.relationship("Cotizacion", back_populates="cliente")
    solicitudes = db.relationship("Solicitud", back_populates="cliente")

    @property
    def pedidos_activos(self):
        return [p for p in self.pedidos if not p.entregado]


class Proveedor(db.Model):
    __tablename__ = "proveedores"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    contacto = db.Column(db.String(100))
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(120))
    notas_acuerdos = db.Column(db.Text)
    rubro = db.Column(db.String(100))
    creado_en = db.Column(db.DateTime, default=datetime.now)

    historial = db.relationship("NotaContacto", back_populates="proveedor",
                                order_by="NotaContacto.fecha.desc()")
    insumos = db.relationship("Insumo", back_populates="proveedor")
    ordenes_compra = db.relationship("OrdenCompra", back_populates="proveedor")


# ---------------------------------------------------------------------------
# Diseños y fichas técnicas
# ---------------------------------------------------------------------------
class Diseno(db.Model):
    __tablename__ = "disenos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    tipo_prenda = db.Column(db.String(150))
    tallas = db.Column(db.String(50))
    imagen = db.Column(db.String(255))
    archivado = db.Column(db.Boolean, default=False)
    creado_en = db.Column(db.DateTime, default=datetime.now)

    # Precio de venta por prenda y costo de confección (mano de obra) por prenda, en USD
    precio_venta = db.Column(db.Numeric(10, 2))
    costo_mano_obra = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))

    cliente = db.relationship("Cliente", back_populates="disenos")
    telas = db.relationship("DisenoTela", back_populates="diseno", cascade="all, delete-orphan")
    pedidos = db.relationship("Pedido", back_populates="diseno")

    @property
    def metros_por_prenda(self):
        """Metros de TELA por prenda (no suma hilos ni botones)."""
        return sum(float(dt.metros_por_unidad or 0) for dt in self.telas
                   if dt.tela and dt.tela.unidad_medida in ("Metros", "Yardas") and dt.tela.categoria == "Tela")

    # --- Costeo (costo por prenda) ---
    @property
    def desglose_costos(self):
        """Una fila por insumo de la ficha técnica: cantidad por prenda × costo unitario."""
        filas = []
        for dt in self.telas:
            costo = _dinero(dt.tela.costo_unitario if dt.tela else 0)
            cantidad = Decimal(str(dt.metros_por_unidad or 0))
            filas.append({
                "insumo": dt.tela,
                "cantidad": cantidad,
                "costo_unitario": costo,
                "subtotal": _dinero(cantidad * costo),
            })
        return filas

    @property
    def costo_materiales(self):
        return _dinero(sum((f["subtotal"] for f in self.desglose_costos), Decimal("0")))

    @property
    def costo_por_prenda(self):
        return _dinero(self.costo_materiales + _dinero(self.costo_mano_obra))

    @property
    def tiene_precio(self):
        return self.precio_venta is not None and _dinero(self.precio_venta) > 0

    @property
    def insumos_sin_costo(self):
        return [dt.tela for dt in self.telas if dt.tela and not dt.tela.tiene_costo]

    @property
    def costeable(self):
        """Se puede calcular la ganancia: tiene precio, ficha técnica y todos sus insumos tienen costo."""
        return self.tiene_precio and bool(self.telas) and not self.insumos_sin_costo

    @property
    def margen_unitario(self):
        if not self.tiene_precio:
            return None
        return _dinero(_dinero(self.precio_venta) - self.costo_por_prenda)

    @property
    def margen_pct(self):
        if not self.tiene_precio:
            return None
        return round(float(self.margen_unitario) / float(self.precio_venta) * 100, 1)


class DisenoTela(db.Model):
    __tablename__ = "diseno_telas"

    id = db.Column(db.Integer, primary_key=True)
    metros_por_unidad = db.Column(db.Numeric(6, 2), nullable=False)

    diseno_id = db.Column(db.Integer, db.ForeignKey("disenos.id"), nullable=False)
    tela_id = db.Column(db.Integer, db.ForeignKey("insumos.id"), nullable=False)

    diseno = db.relationship("Diseno", back_populates="telas")
    tela = db.relationship("Insumo", back_populates="disenos")


# ---------------------------------------------------------------------------
# Pedidos y rastreo
# ---------------------------------------------------------------------------
class Pedido(db.Model):
    __tablename__ = "pedidos"

    id = db.Column(db.Integer, primary_key=True)
    folio = db.Column(db.String(20), unique=True, nullable=False)
    modelo_prenda = db.Column(db.String(150), nullable=False)
    tallas = db.Column(db.String(100))
    colores = db.Column(db.String(100))
    cantidad = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.String(50), nullable=False, default="Recibido")
    fase_tracking = db.Column(db.Integer, default=1)
    ubicacion_actual = db.Column(db.String(255), default="Taller Principal")
    latitud = db.Column(db.Float)
    longitud = db.Column(db.Float)
    fecha_limite = db.Column(db.Date, nullable=False)
    observaciones = db.Column(db.Text)
    creado_en = db.Column(db.DateTime, default=datetime.now)

    # Precio de venta acordado por prenda (si es None se usa el del diseño)
    precio_unitario = db.Column(db.Numeric(10, 2))

    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    diseno_id = db.Column(db.Integer, db.ForeignKey("disenos.id"), nullable=True)
    cotizacion_id = db.Column(db.Integer, db.ForeignKey("cotizaciones.id"), nullable=True)
    solicitud_id = db.Column(db.Integer, db.ForeignKey("solicitudes.id"), nullable=True)

    cliente = db.relationship("Cliente", back_populates="pedidos")
    diseno = db.relationship("Diseno", back_populates="pedidos")
    cotizacion = db.relationship("Cotizacion", back_populates="pedidos")
    solicitud = db.relationship("Solicitud", back_populates="pedidos")
    movimientos = db.relationship("Movimiento", back_populates="pedido")
    notas = db.relationship("NotaContacto", back_populates="pedido")
    registros_calidad = db.relationship("RegistroCalidad", back_populates="pedido",
                                        order_by="RegistroCalidad.fecha.desc()",
                                        cascade="all, delete-orphan")
    eventos = db.relationship(
        "EventoRastreo", back_populates="pedido",
        order_by="EventoRastreo.fecha", cascade="all, delete-orphan",
    )

    # --- Fases ---
    def cambiar_estado(self, nuevo_estado):
        """Sincroniza estado textual y número de fase."""
        self.estado = nuevo_estado
        self.fase_tracking = fase_por_estado(nuevo_estado)

    @property
    def fase_actual(self):
        return fase_por_estado(self.estado)

    @property
    def total_fases(self):
        return len(FASES)

    @property
    def progreso(self):
        """Porcentaje de avance (0-100)."""
        if self.total_fases <= 1:
            return 100
        return round((self.fase_actual - 1) / (self.total_fases - 1) * 100)

    @property
    def entregado(self):
        return self.estado == "Entregado"

    @property
    def en_produccion(self):
        return self.estado in ("Recibido", "En Corte", "En Costura", "Terminado")

    @property
    def dias_restantes(self):
        if not self.fecha_limite:
            return None
        return (self.fecha_limite - date.today()).days

    @property
    def alerta_entrega(self):
        """ok | pronto | vencido (solo aplica si no ha sido entregado)."""
        if self.entregado or self.dias_restantes is None:
            return "ok"
        if self.dias_restantes < 0:
            return "vencido"
        if self.dias_restantes <= 7:
            return "pronto"
        return "ok"

    @property
    def ultimo_evento(self):
        return self.eventos[-1] if self.eventos else None

    @property
    def tiene_coordenadas(self):
        return self.latitud is not None and self.longitud is not None

    # --- Rentabilidad ---
    @property
    def precio_efectivo(self):
        if self.precio_unitario is not None:
            return _dinero(self.precio_unitario)
        if self.diseno and self.diseno.tiene_precio:
            return _dinero(self.diseno.precio_venta)
        return None

    @property
    def ingreso(self):
        precio = self.precio_efectivo
        return None if precio is None else _dinero(precio * self.cantidad)

    @property
    def costo_estimado(self):
        """Costo según la ficha técnica del diseño (materiales + mano de obra)."""
        if not self.diseno:
            return None
        return _dinero(self.diseno.costo_por_prenda * self.cantidad)

    @property
    def costo_materiales_real(self):
        """Materiales efectivamente descontados del inventario para este pedido."""
        total = Decimal("0")
        for m in self.movimientos:
            if m.tipo == "salida" and m.insumo is not None:
                total += Decimal(str(m.cantidad or 0)) * _dinero(m.insumo.costo_unitario)
        return _dinero(total)

    @property
    def ganancia_estimada(self):
        if self.ingreso is None or self.costo_estimado is None:
            return None
        return _dinero(self.ingreso - self.costo_estimado)

    @property
    def margen_pct(self):
        if not self.ingreso or self.ganancia_estimada is None:
            return None
        return round(float(self.ganancia_estimada) / float(self.ingreso) * 100, 1)

    # --- Calidad ---
    @property
    def prendas_con_defecto(self):
        return sum(r.cantidad or 0 for r in self.registros_calidad)

    @property
    def defectos_abiertos(self):
        return [r for r in self.registros_calidad if not r.resuelto]


class EventoRastreo(db.Model):
    """Historial de fases y ubicaciones de un pedido (línea de tiempo)."""
    __tablename__ = "eventos_rastreo"

    id = db.Column(db.Integer, primary_key=True)
    estado = db.Column(db.String(50), nullable=False)
    fase = db.Column(db.Integer, nullable=False, default=1)
    ubicacion = db.Column(db.String(255))
    latitud = db.Column(db.Float)
    longitud = db.Column(db.Float)
    nota = db.Column(db.String(255))
    fecha = db.Column(db.DateTime, default=datetime.now, nullable=False)

    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)

    pedido = db.relationship("Pedido", back_populates="eventos")
    usuario = db.relationship("Usuario", back_populates="eventos_rastreo")

    @property
    def tiene_coordenadas(self):
        return self.latitud is not None and self.longitud is not None


class Movimiento(db.Model):
    __tablename__ = "movimientos"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(10), nullable=False)
    cantidad = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    metros = db.Column(db.Numeric(10, 2))
    motivo = db.Column(db.String(255))
    fecha = db.Column(db.DateTime, default=datetime.now)

    insumo_id = db.Column(db.Integer, db.ForeignKey("insumos.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=True)

    insumo = db.relationship("Insumo", back_populates="movimientos")
    tela = db.relationship("Insumo", overlaps="insumo,movimientos")
    usuario = db.relationship("Usuario", back_populates="movimientos")
    pedido = db.relationship("Pedido", back_populates="movimientos")


class NotaContacto(db.Model):
    """Historial de comunicación y acuerdos con clientes y proveedores (RF-04).

    Las notas no se editan ni se eliminan: funcionan como registro de auditoría.
    """
    __tablename__ = "notas_contacto"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False, default="comunicacion")
    contenido = db.Column(db.Text, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.now, nullable=False)

    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey("proveedores.id"), nullable=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=True)

    usuario = db.relationship("Usuario")
    cliente = db.relationship("Cliente", back_populates="historial")
    proveedor = db.relationship("Proveedor", back_populates="historial")
    pedido = db.relationship("Pedido", back_populates="notas")

    @property
    def tipo_legible(self):
        return TIPOS_NOTA.get(self.tipo, self.tipo)


# ---------------------------------------------------------------------------
# Cotizaciones
# ---------------------------------------------------------------------------
class Cotizacion(db.Model):
    """Propuesta de precio para un cliente. Puede convertirse en pedidos al ser aceptada."""
    __tablename__ = "cotizaciones"

    id = db.Column(db.Integer, primary_key=True)
    folio = db.Column(db.String(20), unique=True, nullable=False)
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    validez_dias = db.Column(db.Integer, nullable=False, default=15)
    fecha_entrega = db.Column(db.Date)
    estado = db.Column(db.String(20), nullable=False, default="borrador")
    descuento_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    iva_pct = db.Column(db.Numeric(5, 2), nullable=False, default=IVA_PCT)
    condiciones = db.Column(db.Text)
    notas = db.Column(db.Text)
    creado_en = db.Column(db.DateTime, default=datetime.now)
    respondida_en = db.Column(db.DateTime)

    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)

    cliente = db.relationship("Cliente", back_populates="cotizaciones")
    usuario = db.relationship("Usuario")
    lineas = db.relationship("CotizacionLinea", back_populates="cotizacion",
                             cascade="all, delete-orphan", order_by="CotizacionLinea.id")
    pedidos = db.relationship("Pedido", back_populates="cotizacion")

    @property
    def subtotal(self):
        return _dinero(sum((l.importe for l in self.lineas), Decimal("0")))

    @property
    def descuento(self):
        return _dinero(self.subtotal * _dinero(self.descuento_pct) / 100)

    @property
    def base_imponible(self):
        return _dinero(self.subtotal - self.descuento)

    @property
    def iva(self):
        return _dinero(self.base_imponible * _dinero(self.iva_pct) / 100)

    @property
    def total(self):
        return _dinero(self.base_imponible + self.iva)

    @property
    def total_prendas(self):
        return sum(l.cantidad or 0 for l in self.lineas)

    @property
    def fecha_vencimiento(self):
        return (self.fecha or date.today()) + timedelta(days=self.validez_dias or 0)

    @property
    def vencida(self):
        return self.estado in ("borrador", "enviada") and self.fecha_vencimiento < date.today()

    @property
    def dias_para_vencer(self):
        return (self.fecha_vencimiento - date.today()).days

    @property
    def estado_legible(self):
        if self.vencida:
            return "Vencida"
        return ESTADOS_COTIZACION.get(self.estado, self.estado)

    @property
    def editable(self):
        return self.estado == "borrador"

    @property
    def costo_estimado(self):
        total = Decimal("0")
        for l in self.lineas:
            if l.diseno is None:
                return None
            total += l.diseno.costo_por_prenda * (l.cantidad or 0)
        return _dinero(total)

    @property
    def margen_pct(self):
        costo = self.costo_estimado
        if costo is None or not self.base_imponible:
            return None
        return round(float(self.base_imponible - costo) / float(self.base_imponible) * 100, 1)


class CotizacionLinea(db.Model):
    __tablename__ = "cotizacion_lineas"

    id = db.Column(db.Integer, primary_key=True)
    descripcion = db.Column(db.String(200), nullable=False)
    tallas = db.Column(db.String(100))
    cantidad = db.Column(db.Integer, nullable=False)
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)

    cotizacion_id = db.Column(db.Integer, db.ForeignKey("cotizaciones.id"), nullable=False)
    diseno_id = db.Column(db.Integer, db.ForeignKey("disenos.id"), nullable=True)

    cotizacion = db.relationship("Cotizacion", back_populates="lineas")
    diseno = db.relationship("Diseno")

    @property
    def importe(self):
        return _dinero(_dinero(self.precio_unitario) * (self.cantidad or 0))


# ---------------------------------------------------------------------------
# Órdenes de compra a proveedores
# ---------------------------------------------------------------------------
class OrdenCompra(db.Model):
    __tablename__ = "ordenes_compra"

    id = db.Column(db.Integer, primary_key=True)
    folio = db.Column(db.String(20), unique=True, nullable=False)
    estado = db.Column(db.String(20), nullable=False, default="borrador")
    fecha = db.Column(db.DateTime, nullable=False, default=datetime.now)
    fecha_esperada = db.Column(db.Date)
    fecha_recepcion = db.Column(db.DateTime)
    notas = db.Column(db.Text)

    proveedor_id = db.Column(db.Integer, db.ForeignKey("proveedores.id"), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)

    proveedor = db.relationship("Proveedor", back_populates="ordenes_compra")
    usuario = db.relationship("Usuario")
    lineas = db.relationship("OrdenCompraLinea", back_populates="orden",
                             cascade="all, delete-orphan", order_by="OrdenCompraLinea.id")

    @property
    def total(self):
        return _dinero(sum((l.importe for l in self.lineas), Decimal("0")))

    @property
    def estado_legible(self):
        return ESTADOS_ORDEN_COMPRA.get(self.estado, self.estado)

    @property
    def pendiente(self):
        """Mercadería pedida que aún no llega (cuenta como «en camino»)."""
        return self.estado in ("borrador", "enviada")

    @property
    def atrasada(self):
        return (self.estado == "enviada" and self.fecha_esperada is not None
                and self.fecha_esperada < date.today())


class OrdenCompraLinea(db.Model):
    __tablename__ = "orden_compra_lineas"

    id = db.Column(db.Integer, primary_key=True)
    cantidad = db.Column(db.Numeric(10, 2), nullable=False)
    costo_unitario = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    orden_id = db.Column(db.Integer, db.ForeignKey("ordenes_compra.id"), nullable=False)
    insumo_id = db.Column(db.Integer, db.ForeignKey("insumos.id"), nullable=False)

    orden = db.relationship("OrdenCompra", back_populates="lineas")
    insumo = db.relationship("Insumo")

    @property
    def importe(self):
        return _dinero(Decimal(str(self.cantidad or 0)) * _dinero(self.costo_unitario))


# ---------------------------------------------------------------------------
# Control de calidad
# ---------------------------------------------------------------------------
class RegistroCalidad(db.Model):
    """Defecto o reproceso detectado en un pedido, por línea de producción."""
    __tablename__ = "registros_calidad"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, nullable=False, default=datetime.now)
    linea = db.Column(db.String(40), nullable=False)
    tipo = db.Column(db.String(20), nullable=False, default="defecto")
    categoria = db.Column(db.String(60), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    descripcion = db.Column(db.Text)
    accion_correctiva = db.Column(db.Text)
    resuelto = db.Column(db.Boolean, nullable=False, default=False)
    resuelto_en = db.Column(db.DateTime)

    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)

    pedido = db.relationship("Pedido", back_populates="registros_calidad")
    usuario = db.relationship("Usuario")

    @property
    def tipo_legible(self):
        return TIPOS_REGISTRO_CALIDAD.get(self.tipo, self.tipo)


# ---------------------------------------------------------------------------
# Notificaciones internas
# ---------------------------------------------------------------------------
class Notificacion(db.Model):
    __tablename__ = "notificaciones"
    __table_args__ = (db.UniqueConstraint("usuario_id", "clave", name="uq_notificacion_usuario_clave"),)

    id = db.Column(db.Integer, primary_key=True)
    # vencimiento | stock | pedido | calidad | cotizacion | compra | usuarios
    tipo = db.Column(db.String(20), nullable=False)
    nivel = db.Column(db.String(10), nullable=False, default="info")  # danger | warn | info | ok
    titulo = db.Column(db.String(150), nullable=False)
    mensaje = db.Column(db.String(300))
    url = db.Column(db.String(255))
    # Identifica la situación que originó el aviso para no repetirlo
    clave = db.Column(db.String(120), nullable=False)
    # Las automáticas desaparecen solas cuando la situación se resuelve
    automatica = db.Column(db.Boolean, nullable=False, default=False)
    leida = db.Column(db.Boolean, nullable=False, default=False)
    creada_en = db.Column(db.DateTime, nullable=False, default=datetime.now)

    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    usuario = db.relationship("Usuario")

    @property
    def icono(self):
        return {"vencimiento": "alarm-clock", "stock": "package-x", "pedido": "truck",
                "calidad": "shield-alert", "cotizacion": "file-text", "solicitud": "clipboard-list", "compra": "shopping-cart",
                "usuarios": "user-check"}.get(self.tipo, "bell")


# ---------------------------------------------------------------------------
# Bitácora de auditoría
# ---------------------------------------------------------------------------
class Auditoria(db.Model):
    """Quién hizo qué cambio y cuándo. Se llena automáticamente (ver app/auditoria.py)."""
    __tablename__ = "auditoria"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    accion = db.Column(db.String(20), nullable=False)  # crear | editar | eliminar | sesion
    entidad = db.Column(db.String(40), nullable=False)
    entidad_id = db.Column(db.Integer)
    descripcion = db.Column(db.String(255), nullable=False)
    cambios = db.Column(db.Text)  # JSON: {"campo": ["antes", "después"]}
    ip = db.Column(db.String(45))

    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    usuario_nombre = db.Column(db.String(100))
    usuario = db.relationship("Usuario")

    @property
    def cambios_dict(self):
        try:
            return json.loads(self.cambios) if self.cambios else {}
        except ValueError:
            return {}


@login_manager.user_loader
def cargar_usuario(user_id):
    return db.session.get(Usuario, int(user_id))


# ---------------------------------------------------------------------------
# Solicitudes de prendas (las crea el cliente desde su portal)
# ---------------------------------------------------------------------------
ESTADOS_SOLICITUD = {
    "enviada": "Pendiente de revisión",
    "aprobada": "Cotización lista",
    "convertida": "En producción",
    "denegada": "Denegada",
    "declinada": "Declinada",
    "cancelada": "Cancelada",
}

# Etiquetas rápidas para las condiciones de cambio que la empresa fija al aprobar
ETIQUETAS_CONDICION = [
    "Mínimo de pedido", "Color no disponible", "Tela alternativa",
    "Cambio de medidas", "Anticipo requerido", "Fecha ajustada",
]


class Solicitud(db.Model):
    """Propuesta de prenda del cliente.

    La empresa la revisa: la aprueba con precios por cantidad (y condiciones de cambio
    si aplican) o la deniega con motivo. Al aprobarla se publica una cotización con
    vigencia limitada; los pedidos se crean solo cuando el cliente la acepta.
    """
    __tablename__ = "solicitudes"

    id = db.Column(db.Integer, primary_key=True)
    folio = db.Column(db.String(20), unique=True, nullable=False)
    estado = db.Column(db.String(20), nullable=False, default="enviada", index=True)
    origen = db.Column(db.String(20), nullable=False, default="portal")
    fecha_deseada = db.Column(db.Date)
    fecha_entrega = db.Column(db.Date)          # entrega estimada que compromete la empresa al aprobar
    notas = db.Column(db.Text)                  # del cliente
    respuesta = db.Column(db.Text)              # de la empresa (mensaje o motivo de la denegación)
    condiciones = db.Column(db.Text)            # condiciones de cambio según las políticas de la empresa
    etiquetas = db.Column(db.String(200))       # etiquetas de condición separadas por coma
    motivo_cliente = db.Column(db.String(500))  # por qué el cliente declinó la cotización
    creado_en = db.Column(db.DateTime, default=datetime.now, nullable=False)
    respondida_en = db.Column(db.DateTime)      # cuándo revisó la empresa
    aprobada_en = db.Column(db.DateTime)
    vence_en = db.Column(db.Date)               # vigencia de la cotización (15 días desde la aprobación)
    decidida_en = db.Column(db.DateTime)        # cuándo el cliente aceptó o declinó

    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)
    atendida_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id", ondelete="SET NULL"), nullable=True)

    cliente = db.relationship("Cliente", back_populates="solicitudes")
    usuario = db.relationship("Usuario", foreign_keys=[usuario_id])
    atendida_por = db.relationship("Usuario", foreign_keys=[atendida_por_id])
    lineas = db.relationship("SolicitudLinea", back_populates="solicitud", cascade="all, delete-orphan",
                             order_by="SolicitudLinea.id")
    pedidos = db.relationship("Pedido", back_populates="solicitud")

    @property
    def estado_legible(self):
        if self.vencida:
            return "Cotización vencida"
        return ESTADOS_SOLICITUD.get(self.estado, self.estado)

    @property
    def total_prendas(self):
        return sum(l.cantidad or 0 for l in self.lineas)

    @property
    def total(self):
        """Importe sin IVA; None mientras la empresa no haya aprobado los precios."""
        if not self.lineas or any(l.precio_unitario is None for l in self.lineas):
            return None
        return _dinero(sum(l.importe for l in self.lineas))

    @property
    def vigente(self):
        """La cotización se puede aceptar: aprobada y dentro de su vigencia."""
        return self.estado == "aprobada" and self.vence_en is not None and date.today() <= self.vence_en

    @property
    def vencida(self):
        return self.estado == "aprobada" and self.vence_en is not None and date.today() > self.vence_en

    @property
    def dias_para_vencer(self):
        if self.estado != "aprobada" or not self.vence_en:
            return None
        return (self.vence_en - date.today()).days

    @property
    def abierta(self):
        """Pendiente de que la empresa la revise."""
        return self.estado == "enviada"

    @property
    def cancelable(self):
        """El cliente puede retirarla mientras la empresa no la haya revisado.
        Una cotización publicada se declina, no se cancela."""
        return self.estado == "enviada"

    @property
    def lista_etiquetas(self):
        return [e.strip() for e in (self.etiquetas or "").split(",") if e.strip()]

    @property
    def dias_esperando(self):
        return (datetime.now() - self.creado_en).days if self.creado_en else 0

    @property
    def resumen_prendas(self):
        nombres = [l.descripcion for l in self.lineas]
        return ", ".join(nombres[:2]) + (f" y {len(nombres) - 2} más" if len(nombres) > 2 else "")


class SolicitudLinea(db.Model):
    __tablename__ = "solicitud_lineas"

    id = db.Column(db.Integer, primary_key=True)
    solicitud_id = db.Column(db.Integer, db.ForeignKey("solicitudes.id", ondelete="CASCADE"), nullable=False)
    diseno_id = db.Column(db.Integer, db.ForeignKey("disenos.id"), nullable=True)
    descripcion = db.Column(db.String(200), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False)
    tallas = db.Column(db.String(100))
    colores = db.Column(db.String(100))
    medidas = db.Column(db.String(500))         # medidas especiales o indicaciones de la prenda
    # Precio aplicado a la cantidad solicitada (se calcula de los tramos al aprobar)
    precio_unitario = db.Column(db.Numeric(10, 2))

    solicitud = db.relationship("Solicitud", back_populates="lineas")
    diseno = db.relationship("Diseno")
    tramos = db.relationship("SolicitudTramo", back_populates="linea", cascade="all, delete-orphan",
                             order_by="SolicitudTramo.desde_cantidad")

    @property
    def importe(self):
        return _dinero(Decimal(self.cantidad or 0) * Decimal(self.precio_unitario or 0))

    def precio_para(self, cantidad):
        """Precio unitario según los tramos: aplica el mayor «desde» que la cantidad alcance."""
        precio = None
        for t in self.tramos:  # vienen ordenados por desde_cantidad
            if (cantidad or 0) >= t.desde_cantidad:
                precio = t.precio_unitario
        return _dinero(precio) if precio is not None else None

    @property
    def tramo_aplicado(self):
        aplicado = None
        for t in self.tramos:
            if (self.cantidad or 0) >= t.desde_cantidad:
                aplicado = t
        return aplicado


class SolicitudTramo(db.Model):
    """Rebaja por cantidad: precio unitario cuando se piden al menos `desde_cantidad` unidades."""
    __tablename__ = "solicitud_tramos"
    __table_args__ = (db.UniqueConstraint("linea_id", "desde_cantidad", name="uq_tramo_linea_desde"),)

    id = db.Column(db.Integer, primary_key=True)
    linea_id = db.Column(db.Integer, db.ForeignKey("solicitud_lineas.id", ondelete="CASCADE"), nullable=False)
    desde_cantidad = db.Column(db.Integer, nullable=False, default=1)
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)

    linea = db.relationship("SolicitudLinea", back_populates="tramos")


# ---------------------------------------------------------------------------
# Mensajería asistente de ventas ↔ cliente
#
# Los mensajes viven en el servidor solo mientras la conversación está activa:
# si nadie escribe en MENSAJES_RETENCION_DIAS (30) se borra entera, salvo que el
# cliente la haya marcado como «guardada». El cliente puede borrarla cuando quiera.
# No se registra en la bitácora de auditoría: su contenido es privado.
# ---------------------------------------------------------------------------
class Conversacion(db.Model):
    __tablename__ = "conversaciones"

    id = db.Column(db.Integer, primary_key=True)
    asunto = db.Column(db.String(120), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False, index=True)
    creada_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    creada_en = db.Column(db.DateTime, default=datetime.now, nullable=False)
    ultima_actividad = db.Column(db.DateTime, default=datetime.now, nullable=False, index=True)
    guardada = db.Column(db.Boolean, default=False, nullable=False)

    cliente = db.relationship("Cliente")
    creada_por = db.relationship("Usuario", foreign_keys=[creada_por_id])
    mensajes = db.relationship("Mensaje", back_populates="conversacion", cascade="all, delete-orphan",
                               order_by="Mensaje.id")

    @property
    def ultimo_mensaje(self):
        return self.mensajes[-1] if self.mensajes else None

    def sin_leer_para(self, usuario):
        """Mensajes del otro lado que este usuario aún no ha visto."""
        de_cliente = usuario.rol != "cliente"   # el equipo cuenta lo que escribió el cliente, y viceversa
        return sum(1 for m in self.mensajes if m.de_cliente == de_cliente and not m.leido)

    def caduca_en(self, dias):
        return None if self.guardada else (self.ultima_actividad + timedelta(days=dias))

    def puede_ver(self, usuario):
        if usuario.rol in ("admin", "ventas"):
            return True
        return usuario.rol == "cliente" and usuario.cliente_id == self.cliente_id


class Mensaje(db.Model):
    __tablename__ = "mensajes"

    id = db.Column(db.Integer, primary_key=True)
    conversacion_id = db.Column(db.Integer, db.ForeignKey("conversaciones.id", ondelete="CASCADE"),
                                nullable=False, index=True)
    autor_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    de_cliente = db.Column(db.Boolean, nullable=False, default=False)
    texto = db.Column(db.Text, nullable=False)
    creado_en = db.Column(db.DateTime, default=datetime.now, nullable=False)
    leido = db.Column(db.Boolean, default=False, nullable=False)

    conversacion = db.relationship("Conversacion", back_populates="mensajes")
    autor = db.relationship("Usuario", foreign_keys=[autor_id])

    def como_dict(self):
        return {
            "id": self.id,
            "de_cliente": self.de_cliente,
            "autor": self.autor.nombre if self.autor else ("Cliente" if self.de_cliente else "Arte y Color"),
            "texto": self.texto,
            "hora": self.creado_en.strftime("%d/%m %H:%M"),
        }
