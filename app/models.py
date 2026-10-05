from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions import db, login_manager


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    cargo = db.Column(db.String(80))  # Ej. "Jefe de Producción"
    rol = db.Column(db.String(20), nullable=False, default="empleado")  # admin / empleado
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.now)

    movimientos = db.relationship("Movimiento", back_populates="usuario")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<Usuario {self.email}>"


@login_manager.user_loader
def cargar_usuario(user_id):
    return db.session.get(Usuario, int(user_id))


class Tela(db.Model):
    """Materia prima: telas e hilos, medidos en metros."""
    __tablename__ = "telas"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)       # Algodón Pima Verde Gras
    tipo = db.Column(db.String(80), default="Textil Premium")
    codigo_pantone = db.Column(db.String(30))                # Pantone 348 C
    color_hex = db.Column(db.String(7), default="#CCCCCC")   # Para la muestra de color
    metros_disponibles = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    stock_minimo = db.Column(db.Numeric(10, 2), nullable=False, default=100)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.now)
    actualizado_en = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    movimientos = db.relationship("Movimiento", back_populates="tela")
    disenos = db.relationship("DisenoTela", back_populates="tela")

    @property
    def estado(self):
        """Disponible, Stock Bajo o Crítico (menos de la mitad del mínimo)."""
        if self.metros_disponibles <= self.stock_minimo / 2:
            return "Crítico"
        if self.metros_disponibles <= self.stock_minimo:
            return "Stock Bajo"
        return "Disponible"

    def __repr__(self):
        return f"<Tela {self.nombre}>"


class Cliente(db.Model):
    __tablename__ = "clientes"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)  # Banco Nacional de México
    contacto = db.Column(db.String(100))
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(120))

    disenos = db.relationship("Diseno", back_populates="cliente")
    pedidos = db.relationship("Pedido", back_populates="cliente")

    def __repr__(self):
        return f"<Cliente {self.nombre}>"


class Diseno(db.Model):
    """Diseño de una prenda, con su render y ficha técnica."""
    __tablename__ = "disenos"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)  # Polo Corporativa Banco Nacional 2025
    tipo_prenda = db.Column(db.String(150))             # Polo manga corta, corte slim
    tallas = db.Column(db.String(50))                   # S, M, L, XL, XXL
    imagen = db.Column(db.String(255))                  # Ruta del render
    archivado = db.Column(db.Boolean, default=False)
    creado_en = db.Column(db.DateTime, default=datetime.now)

    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))

    cliente = db.relationship("Cliente", back_populates="disenos")
    telas = db.relationship("DisenoTela", back_populates="diseno", cascade="all, delete-orphan")
    pedidos = db.relationship("Pedido", back_populates="diseno")

    def __repr__(self):
        return f"<Diseno {self.nombre}>"


class DisenoTela(db.Model):
    """Qué telas usa un diseño y cuántos metros por unidad."""
    __tablename__ = "diseno_telas"

    id = db.Column(db.Integer, primary_key=True)
    metros_por_unidad = db.Column(db.Numeric(6, 2), nullable=False)  # 1.2 mts/u

    diseno_id = db.Column(db.Integer, db.ForeignKey("disenos.id"), nullable=False)
    tela_id = db.Column(db.Integer, db.ForeignKey("telas.id"), nullable=False)

    diseno = db.relationship("Diseno", back_populates="telas")
    tela = db.relationship("Tela", back_populates="disenos")


class Pedido(db.Model):
    """Orden de producción: un diseño encargado por un cliente."""
    __tablename__ = "pedidos"

    ESTADOS = ["Pendiente", "En Producción", "Terminado", "Entregado", "Cancelado"]

    id = db.Column(db.Integer, primary_key=True)
    cantidad = db.Column(db.Integer, nullable=False)  # 500 unidades
    estado = db.Column(db.String(20), nullable=False, default="Pendiente")
    fecha_entrega = db.Column(db.Date)
    notas = db.Column(db.Text)
    creado_en = db.Column(db.DateTime, default=datetime.now)

    diseno_id = db.Column(db.Integer, db.ForeignKey("disenos.id"), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)

    diseno = db.relationship("Diseno", back_populates="pedidos")
    cliente = db.relationship("Cliente", back_populates="pedidos")
    movimientos = db.relationship("Movimiento", back_populates="pedido")

    def telas_necesarias(self):
        """Metros de cada tela que consume este pedido."""
        return [
            (dt.tela, dt.metros_por_unidad * self.cantidad)
            for dt in self.diseno.telas
        ]

    def __repr__(self):
        return f"<Pedido {self.id} - {self.estado}>"


class Movimiento(db.Model):
    """Historial de entradas y salidas de tela."""
    __tablename__ = "movimientos"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(10), nullable=False)  # entrada / salida / ajuste
    metros = db.Column(db.Numeric(10, 2), nullable=False)
    motivo = db.Column(db.String(255))
    fecha = db.Column(db.DateTime, default=datetime.now)

    tela_id = db.Column(db.Integer, db.ForeignKey("telas.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"))  # Si la salida es para un pedido

    tela = db.relationship("Tela", back_populates="movimientos")
    usuario = db.relationship("Usuario", back_populates="movimientos")
    pedido = db.relationship("Pedido", back_populates="movimientos")

    def __repr__(self):
        return f"<Movimiento {self.tipo} {self.metros} mts>"