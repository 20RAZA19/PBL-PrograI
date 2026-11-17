from flask_wtf import FlaskForm
from wtforms import IntegerField, SelectField, TextAreaField
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional, ValidationError

from app.models import LINEAS_PRODUCCION, TIPOS_DEFECTO, TIPOS_REGISTRO_CALIDAD


class RegistroCalidadForm(FlaskForm):
    pedido_id = SelectField("Pedido", coerce=int, validators=[DataRequired("Selecciona el pedido.")])
    linea = SelectField("Línea de producción", choices=[(l, l) for l in LINEAS_PRODUCCION],
                        validators=[DataRequired()],
                        description="Área donde se originó el problema.")
    tipo = SelectField("Tipo", choices=list(TIPOS_REGISTRO_CALIDAD.items()), default="defecto",
                       description="Defecto: la prenda no cumple. Reproceso: se corrigió en el taller.")
    categoria = SelectField("Defecto encontrado", choices=[(c, c) for c in TIPOS_DEFECTO],
                            validators=[DataRequired()])
    cantidad = IntegerField("Prendas afectadas", default=1,
                            validators=[InputRequired("Indica cuántas prendas."),
                                        NumberRange(min=1, message="Debe ser al menos 1.")])
    descripcion = TextAreaField("Descripción", validators=[Optional(), Length(max=1000)])
    accion_correctiva = TextAreaField("Acción correctiva", validators=[Optional(), Length(max=1000)],
                                      description="Qué se hizo o se hará para corregirlo.")

    def validate_cantidad(self, field):
        from app.extensions import db
        from app.models import Pedido
        pedido = db.session.get(Pedido, self.pedido_id.data or 0)
        if pedido and field.data and field.data > pedido.cantidad:
            raise ValidationError(f"El pedido solo tiene {pedido.cantidad} prendas.")


class ResolverForm(FlaskForm):
    accion_correctiva = TextAreaField("Acción correctiva", validators=[Optional(), Length(max=1000)])
