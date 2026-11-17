from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask_wtf import FlaskForm
from wtforms import DateField, DecimalField, IntegerField, SelectField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional, ValidationError

CONDICIONES_PREDETERMINADAS = (
    "Anticipo del 50 % para iniciar producción y 50 % contra entrega.\n"
    "Precios por prenda incluyen confección, etiquetado y empaque individual.\n"
    "El tiempo de entrega corre a partir de la aprobación de la muestra física."
)


class CotizacionForm(FlaskForm):
    cliente_id = SelectField("Cliente", coerce=int, validators=[DataRequired("Selecciona el cliente.")])
    fecha_entrega = DateField("Fecha de entrega propuesta", validators=[Optional()],
                              default=lambda: date.today() + timedelta(days=30))
    validez_dias = IntegerField("Validez (días)", default=15,
                                validators=[InputRequired(), NumberRange(min=1, max=180, message="Entre 1 y 180 días.")])
    descuento_pct = DecimalField("Descuento (%)", places=2, default=0,
                                 validators=[InputRequired(), NumberRange(min=0, max=100, message="Entre 0 y 100.")])
    iva_pct = DecimalField("IVA (%)", places=2, default=13,
                           validators=[InputRequired(), NumberRange(min=0, max=100, message="Entre 0 y 100.")])
    condiciones = TextAreaField("Condiciones comerciales", default=CONDICIONES_PREDETERMINADAS,
                                validators=[Optional(), Length(max=2000)])
    notas = TextAreaField("Notas para el cliente", validators=[Optional(), Length(max=2000)])

    def validate_fecha_entrega(self, field):
        if field.data and field.data < date.today():
            raise ValidationError("La fecha de entrega no puede estar en el pasado.")


def leer_lineas(formdata):
    """Lee las filas dinámicas del formulario.

    Devuelve (lineas, errores). Cada línea es un dict con diseno_id, descripcion,
    tallas, cantidad (int) y precio_unitario (Decimal). Las filas vacías se ignoran.
    """
    disenos = formdata.getlist("linea_diseno")
    descripciones = formdata.getlist("linea_descripcion")
    tallas = formdata.getlist("linea_tallas")
    cantidades = formdata.getlist("linea_cantidad")
    precios = formdata.getlist("linea_precio")

    lineas, errores = [], []
    for i, descripcion in enumerate(descripciones):
        descripcion = (descripcion or "").strip()
        cantidad_txt = (cantidades[i] if i < len(cantidades) else "").strip()
        precio_txt = (precios[i] if i < len(precios) else "").strip()
        if not descripcion and not cantidad_txt and not precio_txt:
            continue
        n = i + 1
        if not descripcion:
            errores.append(f"Línea {n}: escribe la descripción de la prenda.")
        try:
            cantidad = int(cantidad_txt)
            if cantidad < 1:
                raise ValueError
        except ValueError:
            errores.append(f"Línea {n}: la cantidad debe ser un número entero mayor a 0.")
            cantidad = None
        try:
            precio = Decimal(precio_txt.replace(",", "").replace("$", ""))
            if precio < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            errores.append(f"Línea {n}: el precio unitario no es válido.")
            precio = None
        try:
            diseno_id = int(disenos[i]) if i < len(disenos) and disenos[i] else None
        except ValueError:
            diseno_id = None
        lineas.append({"diseno_id": diseno_id or None, "descripcion": descripcion[:200],
                       "tallas": ((tallas[i] if i < len(tallas) else "") or "").strip()[:100] or None,
                       "cantidad": cantidad, "precio_unitario": precio})
    if not lineas:
        errores.append("Agrega al menos una prenda a la cotización.")
    return lineas, errores
