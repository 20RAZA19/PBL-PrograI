from flask_wtf import FlaskForm
from wtforms import (
    StringField, IntegerField, SelectField, DateField, TextAreaField, DecimalField,
    PasswordField, SubmitField, BooleanField, FloatField,
)
from wtforms.validators import (
    DataRequired, NumberRange, Email, EqualTo, Length, Optional, ValidationError, Regexp,
)

from app.models import Usuario, ROLES, ESTADOS_PERMISO, NOMBRES_FASES


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------
# Contraseñas demasiado comunes que se rechazan aunque cumplan el largo
CLAVES_COMUNES = {"12345678", "123456789", "password", "contraseña", "qwerty123", "admin123", "abc12345",
                  "password1", "11111111", "arteycolor", "iloveyou"}


def clave_robusta(valor, email=""):
    """Devuelve un mensaje de error o None si la contraseña es aceptable."""
    v = valor or ""
    if v.lower() in CLAVES_COMUNES:
        return "Esa contraseña es demasiado común."
    if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
        return "Combina letras y números."
    if email and v.lower() == email.strip().lower():
        return "La contraseña no puede ser igual al correo."
    return None


class LoginForm(FlaskForm):
    # Sin validador Email(): el login solo busca el usuario. Así también
    # funcionan cuentas heredadas como "admin123".
    email = StringField('Correo Electrónico', validators=[DataRequired(), Length(max=120)])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    submit = SubmitField('Iniciar Sesión')


class RegistroForm(FlaskForm):
    nombre = StringField('Nombre Completo', validators=[DataRequired(), Length(max=100)])
    email = StringField('Correo Electrónico', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('Contraseña', validators=[DataRequired(), Length(min=8, max=128, message='Usa entre 8 y 128 caracteres.')],
                             description='Mínimo 8 caracteres, con letras y números.')
    confirm_password = PasswordField('Confirmar Contraseña', validators=[DataRequired(), EqualTo('password', message='Las contraseñas no coinciden.')])
    rol_solicitado = SelectField('Solicitar Rol', choices=[('cliente', 'Cliente (Ver Catálogo)'), ('ventas', 'Asistente de Ventas'), ('gestor', 'Encargado de Taller'), ('admin', 'Administrador')], validators=[DataRequired()])
    empresa = StringField(
        'Empresa / Institución', validators=[Optional(), Length(max=150)],
        description='Solo para clientes: se usará para vincular tus pedidos y diseños.',
    )
    submit = SubmitField('Registrarse')

    def validate_password(self, field):
        error = clave_robusta(field.data, self.email.data)
        if error:
            raise ValidationError(error)

    def validate_email(self, field):
        if Usuario.query.filter(db_lower(Usuario.email) == field.data.strip().lower()).first():
            raise ValidationError('Ya existe una cuenta con este correo.')


def db_lower(columna):
    from app.extensions import db
    return db.func.lower(columna)


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------
class PerfilForm(FlaskForm):
    nombre = StringField('Nombre Completo', validators=[DataRequired(), Length(max=100)])
    telefono = StringField('Teléfono de Contacto', validators=[
        Optional(), Length(max=20),
        Regexp(r'^[0-9+\-\s()]{7,20}$', message='Usa solo números, espacios, +, - o paréntesis.'),
    ])
    fecha_nacimiento = DateField('Fecha de Nacimiento', validators=[Optional()])
    cargo = StringField('Cargo / Ocupación', validators=[Optional(), Length(max=80)])
    submit = SubmitField('Actualizar Perfil')


class CambiarPasswordForm(FlaskForm):
    password_actual = PasswordField('Contraseña actual', validators=[DataRequired('Escribe tu contraseña actual.')])
    password_nueva = PasswordField('Nueva contraseña', validators=[DataRequired(), Length(min=8, max=128, message='Usa entre 8 y 128 caracteres.')],
                                   description='Mínimo 8 caracteres, con letras y números.')
    password_confirmar = PasswordField('Confirmar nueva contraseña', validators=[
        DataRequired(), EqualTo('password_nueva', message='Las contraseñas no coinciden.'),
    ])
    submit = SubmitField('Cambiar Contraseña')

    def validate_password_nueva(self, field):
        error = clave_robusta(field.data)
        if error:
            raise ValidationError(error)


class PedirCodigoForm(FlaskForm):
    """Paso 1 de la recuperación: el correo al que se envía el código."""
    email = StringField('Correo electrónico', validators=[DataRequired('Escribe tu correo.'), Email('Correo no válido.')])
    submit = SubmitField('Enviarme el código')


class RecuperarForm(FlaskForm):
    """Paso 2: el código que llegó por correo y la contraseña nueva."""
    email = StringField('Correo electrónico', validators=[DataRequired('Escribe tu correo.'), Email('Correo no válido.')])
    codigo = StringField('Código de 6 dígitos', validators=[
        DataRequired('Escribe el código que recibiste.'), Regexp(r'^\s*\d{6}\s*$', message='Son exactamente 6 números.')])
    password_nueva = PasswordField('Nueva contraseña', validators=[DataRequired(), Length(min=8, max=128, message='Usa entre 8 y 128 caracteres.')],
                                   description='Mínimo 8 caracteres, con letras y números.')
    password_confirmar = PasswordField('Confirmar nueva contraseña', validators=[
        DataRequired(), EqualTo('password_nueva', message='Las contraseñas no coinciden.'),
    ])
    submit = SubmitField('Cambiar contraseña')

    def validate_password_nueva(self, field):
        error = clave_robusta(field.data, self.email.data or "")
        if error:
            raise ValidationError(error)


# ---------------------------------------------------------------------------
# Pedidos (ya no hay registro manual: nacen de cotizaciones o solicitudes aceptadas)
# ---------------------------------------------------------------------------
class AsociarInsumoForm(FlaskForm):
    insumo_id = SelectField('Insumo', coerce=int, validators=[DataRequired()])
    cantidad_usar = DecimalField('Cantidad a descontar', validators=[DataRequired(), NumberRange(min=0.1)])


class AccionForm(FlaskForm):
    """Formulario vacío: solo aporta protección CSRF a botones de acción (POST)."""
    submit = SubmitField('Confirmar')


class RastreoForm(FlaskForm):
    estado = SelectField('Fase del pedido', choices=[(f, f) for f in NOMBRES_FASES], validators=[DataRequired()])
    ubicacion_actual = StringField('Ubicación actual', validators=[DataRequired('Indica la ubicación.'), Length(max=255)])
    latitud = FloatField('Latitud', validators=[Optional(), NumberRange(min=-90, max=90, message='Entre -90 y 90.')])
    longitud = FloatField('Longitud', validators=[Optional(), NumberRange(min=-180, max=180, message='Entre -180 y 180.')])
    nota = StringField('Nota para el cliente', validators=[Optional(), Length(max=255)])
    submit = SubmitField('Actualizar Rastreo')


# ---------------------------------------------------------------------------
# Administración de usuarios
# ---------------------------------------------------------------------------
class UsuarioAdminForm(FlaskForm):
    nombre = StringField('Nombre Completo', validators=[DataRequired(), Length(max=100)])
    email = StringField('Correo Electrónico', validators=[DataRequired(), Length(max=120)])
    cargo = StringField('Cargo', validators=[Optional(), Length(max=80)])
    telefono = StringField('Teléfono', validators=[Optional(), Length(max=20)])
    rol = SelectField('Rol', choices=list(ROLES.items()), validators=[DataRequired()])
    estado_permiso = SelectField('Estado de la cuenta', choices=list(ESTADOS_PERMISO.items()), validators=[DataRequired()])
    cliente_id = SelectField(
        'Empresa vinculada', coerce=int, validators=[Optional()], default=0,
        description='Obligatorio para clientes: define qué pedidos y diseños pueden ver.',
    )
    activo = BooleanField('Cuenta activa')
    submit = SubmitField('Guardar Cambios')

    def __init__(self, *args, usuario_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._usuario_id = usuario_id

    def validate_email(self, field):
        existente = Usuario.query.filter(db_lower(Usuario.email) == field.data.strip().lower()).first()
        if existente and existente.id != self._usuario_id:
            raise ValidationError('Otro usuario ya usa este correo.')

    def validate_cliente_id(self, field):
        if self.rol.data == 'cliente' and not field.data:
            raise ValidationError('Selecciona la empresa del cliente.')
