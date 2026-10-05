from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, SelectField
from wtforms.validators import (
    DataRequired, InputRequired, Length, NumberRange, Optional, Regexp
)


class TelaForm(FlaskForm):
    nombre = StringField(
        "Nombre de la tela",
        validators=[DataRequired("Escribe el nombre de la tela."), Length(max=150)],
    )
    tipo = StringField(
        "Tipo", default="Textil Premium",
        validators=[Optional(), Length(max=80)],
    )
    codigo_pantone = StringField(
        "Código Pantone",
        validators=[Optional(), Length(max=30)],
    )
    color_hex = StringField(
        "Color de muestra", default="#CCCCCC",
        validators=[DataRequired(), Regexp(r"^#[0-9A-Fa-f]{6}$", message="Color no válido.")],
    )
    stock_minimo = DecimalField(
        "Stock mínimo (mts)", places=2, default=100,
        validators=[InputRequired("Indica el stock mínimo."),
                    NumberRange(min=0, message="No puede ser negativo.")],
        description="Debajo de este valor la tela pasa a Stock Bajo; a la mitad, a Crítico.",
    )


class NuevaTelaForm(TelaForm):
    metros_iniciales = DecimalField(
        "Metros iniciales", places=2, default=0,
        validators=[Optional(), NumberRange(min=0, message="No puede ser negativo.")],
        description="Se registra como entrada de inventario inicial.",
    )


class MovimientoForm(FlaskForm):
    tela_id = SelectField("Tela", coerce=int, validators=[InputRequired("Selecciona una tela.")])
    tipo = SelectField(
        "Tipo de movimiento",
        choices=[("entrada", "Entrada de material"), ("salida", "Salida de material")],
    )
    metros = DecimalField(
        "Metros", places=2,
        validators=[InputRequired("Indica los metros."),
                    NumberRange(min=Decimal("0.01"), message="Debe ser mayor a 0.")],
    )
    motivo = StringField("Motivo o nota", validators=[Optional(), Length(max=255)])