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


class Categoria(db.Model):
    __tablename__ = "categorias"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), unique=True, nullable=False)
    descripcion = db.Column(db.String(255))

    productos = db.relationship("Producto", back_populates="categoria")

    def __repr__(self):
        return f"<Categoria {self.nombre}>"


class Proveedor(db.Model):
    __tablename__ = "proveedores"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(120))
    direccion = db.Column(db.String(255))

    productos = db.relationship("Producto", back_populates="proveedor")

    def __repr__(self):
        return f"<Proveedor {self.nombre}>"


class Producto(db.Model):
    __tablename__ = "productos"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, nullable=False)  # SKU o código interno
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    precio_compra = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    precio_venta = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    stock = db.Column(db.Integer, nullable=False, default=0)
    stock_minimo = db.Column(db.Integer, nullable=False, default=5)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.now)
    actualizado_en = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    categoria_id = db.Column(db.Integer, db.ForeignKey("categorias.id"), nullable=False)
    proveedor_id = db.Column(db.Integer, db.ForeignKey("proveedores.id"))

    categoria = db.relationship("Categoria", back_populates="productos")
    proveedor = db.relationship("Proveedor", back_populates="productos")
    movimientos = db.relationship("Movimiento", back_populates="producto")

    @property
    def bajo_stock(self):
        return self.stock <= self.stock_minimo

    def __repr__(self):
        return f"<Producto {self.codigo} - {self.nombre}>"


class Movimiento(db.Model):
    """Registro de cada entrada o salida de inventario."""
    __tablename__ = "movimientos"

    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(10), nullable=False)  # entrada / salida / ajuste
    cantidad = db.Column(db.Integer, nullable=False)
    motivo = db.Column(db.String(255))
    fecha = db.Column(db.DateTime, default=datetime.now)

    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)

    producto = db.relationship("Producto", back_populates="movimientos")
    usuario = db.relationship("Usuario", back_populates="movimientos")

    def __repr__(self):
        return f"<Movimiento {self.tipo} {self.cantidad}>"