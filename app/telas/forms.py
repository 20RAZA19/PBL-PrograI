import re
from decimal import Decimal

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import BooleanField, StringField, DecimalField, SelectField
from wtforms.validators import (
    DataRequired, InputRequired, Length, NumberRange, Optional, Regexp, ValidationError
)

CATEGORIAS = ["Tela", "Hilo", "Botón", "Cierre", "Elástico", "Etiqueta", "Otro"]
UNIDADES = ["Metros", "Yardas", "Unidades", "Conos", "Rollos", "Docenas"]

# Valores sugeridos (punto pendiente del documento de requerimientos):
# stock mínimo y unidad por defecto según el tipo de material.
DEFAULTS_CATEGORIA = {
    "Tela":     {"unidad": "Metros",   "minimo": 100},
    "Hilo":     {"unidad": "Conos",    "minimo": 20},
    "Botón":    {"unidad": "Unidades", "minimo": 500},
    "Cierre":   {"unidad": "Unidades", "minimo": 200},
    "Elástico": {"unidad": "Metros",   "minimo": 50},
    "Etiqueta": {"unidad": "Unidades", "minimo": 300},
    "Otro":     {"unidad": "Unidades", "minimo": 10},
}


def normalizar_pantone(valor):
    """'pantone  348 c' -> 'PANTONE 348 C' (para comparar sin importar espacios/mayúsculas)."""
    return re.sub(r"\s+", " ", (valor or "").strip()).upper()


def normalizar_hex(valor):
    return (valor or "").strip().upper()


class TelaForm(FlaskForm):
    nombre = StringField(
        "Nombre del insumo",
        validators=[DataRequired("Escribe el nombre del insumo."), Length(max=150)],
    )
    categoria = SelectField(
        "Categoría", choices=[(c, c) for c in CATEGORIAS], default="Tela",
        validators=[DataRequired()],
    )
    unidad_medida = SelectField(
        "Unidad de medida", choices=[(u, u) for u in UNIDADES], default="Metros",
        validators=[DataRequired()],
    )
    tipo = StringField(
        "Tipo / Material", default="Textil Premium",
        validators=[Optional(), Length(max=80)],
    )
    codigo_pantone = StringField(
        "Código Pantone",
        validators=[Optional(), Length(max=30)],
        description="No puede repetirse dentro de la misma categoría.",
    )
    color_hex = StringField(
        "Color de muestra", default="#CCCCCC",
        validators=[DataRequired(), Regexp(r"^#[0-9A-Fa-f]{6}$", message="Color no válido.")],
        description="Cada color debe ser único dentro de la categoría.",
    )
    stock_minimo = DecimalField(
        "Stock mínimo", places=2, default=100,
        validators=[InputRequired("Indica el stock mínimo."),
                    NumberRange(min=0, message="No puede ser negativo.")],
        description="Debajo de este valor pasa a Stock Bajo; a la mitad, a Crítico.",
    )
    costo_unitario = DecimalField(
        "Costo por unidad (USD)", places=2, default=0,
        validators=[Optional(), NumberRange(min=0, message="No puede ser negativo.")],
        description="Precio de compra por metro, cono, unidad… Se usa para el costo por prenda.",
    )
    proveedor_id = SelectField(
        "Proveedor habitual", coerce=int, default=0, validators=[Optional()],
        description="Las compras sugeridas se agrupan por proveedor.",
    )
    imagen = FileField("Foto de la muestra", validators=[
        FileAllowed(["png", "jpg", "jpeg", "webp", "gif"], "Usa PNG, JPG, WEBP o GIF.")])
    quitar_imagen = BooleanField("Quitar la foto actual")

    def __init__(self, *args, insumo_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._insumo_id = insumo_id

    def _otros_insumos(self):
        from app.models import Insumo
        query = Insumo.query.filter(Insumo.categoria == self.categoria.data)
        if self._insumo_id:
            query = query.filter(Insumo.id != self._insumo_id)
        return query.all()

    def validate_color_hex(self, field):
        color = normalizar_hex(field.data)
        for otro in self._otros_insumos():
            if normalizar_hex(otro.color_hex) == color:
                raise ValidationError(
                    f"El color {color} ya está asignado a «{otro.nombre}». Elige otro tono."
                )

    def validate_codigo_pantone(self, field):
        codigo = normalizar_pantone(field.data)
        if not codigo:
            return
        for otro in self._otros_insumos():
            if normalizar_pantone(otro.codigo_pantone) == codigo:
                raise ValidationError(
                    f"El código «{field.data.strip()}» ya pertenece a «{otro.nombre}»."
                )


class NuevaTelaForm(TelaForm):
    metros_iniciales = DecimalField(
        "Cantidad inicial", places=2, default=0,
        validators=[Optional(), NumberRange(min=0, message="No puede ser negativo.")],
        description="Se registra como entrada de inventario inicial.",
    )


class MovimientoForm(FlaskForm):
    tela_id = SelectField("Insumo", coerce=int, validators=[InputRequired("Selecciona un insumo.")])
    tipo = SelectField(
        "Tipo de movimiento",
        choices=[("entrada", "Entrada de material"), ("salida", "Salida de material")],
    )
    metros = DecimalField(
        "Cantidad", places=2,
        validators=[InputRequired("Indica la cantidad."),
                    NumberRange(min=Decimal("0.01"), message="Debe ser mayor a 0.")],
    )
    motivo = StringField("Motivo o nota", validators=[Optional(), Length(max=255)])
