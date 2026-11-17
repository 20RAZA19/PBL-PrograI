from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, SubmitField
from wtforms.validators import DataRequired, Length, Optional, Email, Regexp, ValidationError

from app.extensions import db
from app.models import Cliente, Proveedor, TIPOS_NOTA

TELEFONO = Regexp(r'^[0-9+\-\s()]{7,20}$', message='Usa solo números, espacios, +, - o paréntesis.')


class _ContactoBase(FlaskForm):
    modelo = None  # se define en cada subclase

    nombre = StringField('Nombre / Razón social', validators=[DataRequired('Escribe el nombre.'), Length(max=150)])
    contacto = StringField('Persona de contacto', validators=[Optional(), Length(max=100)])
    telefono = StringField('Teléfono', validators=[Optional(), Length(max=20), TELEFONO])
    email = StringField('Correo electrónico', validators=[Optional(), Email('Correo no válido.'), Length(max=120)])
    submit = SubmitField('Guardar')

    def __init__(self, *args, registro_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._registro_id = registro_id

    def validate_nombre(self, field):
        existente = self.modelo.query.filter(
            db.func.lower(self.modelo.nombre) == field.data.strip().lower()
        ).first()
        if existente and existente.id != self._registro_id:
            raise ValidationError('Ya existe un registro con este nombre.')


class ClienteForm(_ContactoBase):
    modelo = Cliente
    notas = TextAreaField('Requerimientos generales', validators=[Optional(), Length(max=2000)],
                          description='Tallas habituales, colores institucionales, condiciones de entrega…')


class ProveedorForm(_ContactoBase):
    modelo = Proveedor
    rubro = StringField('Rubro / Qué provee', validators=[Optional(), Length(max=100)],
                        description='Ej. Telas de algodón, hilos, botones y cierres.')
    notas_acuerdos = TextAreaField('Acuerdos de materia prima', validators=[Optional(), Length(max=2000)],
                                   description='Precios pactados, tiempos de entrega, condiciones de pago…')


class NotaForm(FlaskForm):
    tipo = SelectField('Tipo de nota', choices=list(TIPOS_NOTA.items()), validators=[DataRequired()])
    pedido_id = SelectField('Pedido relacionado (opcional)', coerce=int, validators=[Optional()], default=0)
    contenido = TextAreaField('Detalle', validators=[DataRequired('Escribe el contenido de la nota.'), Length(max=2000)])
    submit = SubmitField('Agregar nota')
