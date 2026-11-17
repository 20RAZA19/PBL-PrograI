from decimal import Decimal, InvalidOperation

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import BooleanField, DecimalField, SelectField, StringField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional

from app.archivos import EXTENSIONES


class DisenoForm(FlaskForm):
    nombre = StringField("Nombre del diseño", validators=[DataRequired("Escribe el nombre."), Length(max=150)])
    cliente_id = SelectField("Cliente", coerce=int, default=0, validators=[Optional()])
    tipo_prenda = StringField("Tipo de prenda", validators=[Optional(), Length(max=150)])
    tallas = StringField("Tallas", validators=[Optional(), Length(max=50)])
    precio_venta = DecimalField("Precio de venta por prenda (USD)", places=2,
                                validators=[Optional(), NumberRange(min=0, message="No puede ser negativo.")],
                                description="Se usa como precio sugerido en cotizaciones y pedidos.")
    costo_mano_obra = DecimalField("Mano de obra por prenda (USD)", places=2, default=0,
                                   validators=[Optional(), NumberRange(min=0, message="No puede ser negativo.")],
                                   description="Corte, confección y acabado de una prenda.")
    imagen = FileField("Foto o boceto", validators=[FileAllowed(EXTENSIONES, "Usa PNG, JPG, WEBP o GIF.")])
    quitar_imagen = BooleanField("Quitar la foto actual")


def leer_ficha(formdata):
    """Filas de la ficha técnica: [(insumo_id, Decimal cantidad por prenda)], errores."""
    insumos = formdata.getlist("ficha_insumo")
    cantidades = formdata.getlist("ficha_cantidad")
    filas, errores, vistos = [], [], set()
    for i, insumo_txt in enumerate(insumos):
        cantidad_txt = (cantidades[i] if i < len(cantidades) else "").strip()
        if not insumo_txt and not cantidad_txt:
            continue
        try:
            insumo_id = int(insumo_txt)
        except ValueError:
            errores.append(f"Fila {i + 1}: elige el insumo.")
            continue
        try:
            cantidad = Decimal(cantidad_txt)
            if cantidad <= 0:
                raise InvalidOperation
        except InvalidOperation:
            errores.append(f"Fila {i + 1}: la cantidad por prenda debe ser mayor a 0.")
            continue
        if insumo_id in vistos:
            errores.append(f"Fila {i + 1}: ese insumo ya está en la ficha.")
            continue
        vistos.add(insumo_id)
        filas.append((insumo_id, cantidad))
    return filas, errores
