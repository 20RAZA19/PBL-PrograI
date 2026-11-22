from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models import db, Usuario, Cliente, Auditoria
from app.forms import LoginForm, RegistroForm, PerfilForm, CambiarPasswordForm, RecuperarForm, PedirCodigoForm
from app.auditoria import registrar_accion

auth = Blueprint('auth', __name__)


@auth.before_app_request
def expulsar_cuentas_bloqueadas():
    """Si un admin desactiva o rechaza una cuenta, la sesión activa se cierra."""
    if current_user.is_authenticated and not current_user.puede_ingresar:
        logout_user()
        flash('Tu cuenta fue desactivada o está pendiente de aprobación.', 'warn')
        return redirect(url_for('auth.login'))


PREFIJO_FALLO = "Intento fallido de inicio de sesión con «"


def _bloqueo_activo(email):
    """Frena los ataques de fuerza bruta: demasiados intentos fallidos recientes
    para la misma cuenta o desde la misma IP bloquean el acceso unos minutos."""
    cfg = current_app.config
    minutos = cfg.get("LOGIN_BLOQUEO_MIN", 15)
    desde = datetime.now() - timedelta(minutes=minutos)
    fallos = Auditoria.query.filter(Auditoria.accion == "sesion", Auditoria.fecha >= desde,
                                    Auditoria.descripcion.startswith(PREFIJO_FALLO, autoescape=True))
    por_cuenta = fallos.filter(Auditoria.descripcion == f"{PREFIJO_FALLO}{email[:60]}»").count()
    por_ip = fallos.filter(Auditoria.ip == (request.remote_addr or "")[:45]).count() if request.remote_addr else 0
    return por_cuenta >= cfg.get("LOGIN_MAX_INTENTOS_CUENTA", 5) or por_ip >= cfg.get("LOGIN_MAX_INTENTOS_IP", 20)


@auth.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if _bloqueo_activo(email):
            minutos = current_app.config.get("LOGIN_BLOQUEO_MIN", 15)
            flash(f'Demasiados intentos fallidos. Espera {minutos} minutos e inténtalo de nuevo.', 'danger')
            return render_template('auth/login.html', form=form), 429
        user = Usuario.query.filter(db.func.lower(Usuario.email) == email).first()
        if user and user.check_password(form.password.data):
            if user.estado_permiso == 'pendiente':
                flash('Tu cuenta está pendiente de aprobación por un administrador.', 'warn')
                return redirect(url_for('auth.login'))
            if user.estado_permiso == 'rechazado' or not user.activo:
                flash('Tu cuenta no tiene acceso al sistema. Contacta al administrador.', 'danger')
                return redirect(url_for('auth.login'))
            session.clear()  # sesión nueva al entrar (evita fijación de sesión)
            login_user(user)
            registrar_accion("sesion", "Acceso", f"Inició sesión ({user.rol_legible})", user.id, usuario=user)
            db.session.commit()
            destino = request.args.get('next')
            if destino and destino.startswith('/') and not destino.startswith('//'):
                return redirect(destino)
            return redirect(url_for('main.dashboard'))
        registrar_accion("sesion", "Acceso", f"{PREFIJO_FALLO}{email[:60]}»",
                         user.id if user else None, usuario=None)
        db.session.commit()
        flash('Correo o contraseña incorrectos.', 'danger')
    return render_template('auth/login.html', form=form)


@auth.route('/registro', methods=['GET', 'POST'])
def registro():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = RegistroForm()
    if form.validate_on_submit():
        estado = 'aprobado' if form.rol_solicitado.data == 'cliente' else 'pendiente'
        empresa_existente = False
        user = Usuario(
            nombre=form.nombre.data.strip(),
            email=form.email.data.strip().lower(),
            rol=form.rol_solicitado.data,
            estado_permiso=estado
        )
        user.set_password(form.password.data)

        # Los clientes quedan vinculados a una empresa para ver solo lo suyo.
        if user.rol == 'cliente':
            nombre_empresa = (form.empresa.data or '').strip() or user.nombre
            empresa = Cliente.query.filter(db.func.lower(Cliente.nombre) == nombre_empresa.lower()).first()
            if empresa is not None:
                # Cualquiera podría escribir el nombre de una empresa ajena para ver sus pedidos:
                # vincularse a una empresa que ya existe necesita la aprobación del administrador.
                user.estado_permiso = 'pendiente'
                empresa_existente = True
            else:
                empresa = Cliente(nombre=nombre_empresa, contacto=user.nombre, email=user.email)
                db.session.add(empresa)
            user.cliente = empresa

        db.session.add(user)
        db.session.commit()
        if user.estado_permiso == 'pendiente':
            motivo = (f'Un administrador debe confirmar que perteneces a {user.cliente.nombre}.' if empresa_existente
                      else 'Un administrador debe aprobar el rol que solicitaste.')
            flash(f'Registro recibido. {motivo}', 'info')
        else:
            flash('Registro exitoso. Ya puedes iniciar sesión.', 'ok')
        return redirect(url_for('auth.login'))
    return render_template('auth/registro.html', form=form)


@auth.route('/logout')
@login_required
def logout():
    if current_user.is_authenticated:
        registrar_accion("sesion", "Acceso", "Cerró sesión", current_user.id, usuario=current_user)
        db.session.commit()
    logout_user()
    return redirect(url_for('auth.login'))


@auth.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    form = PerfilForm(obj=current_user, prefix='perfil', usuario_id=current_user.id)
    pwd_form = CambiarPasswordForm(prefix='pwd')

    if form.submit.data and form.validate_on_submit():
        current_user.nombre = form.nombre.data.strip()
        current_user.telefono = form.telefono.data or None
        current_user.fecha_nacimiento = form.fecha_nacimiento.data
        current_user.cargo = form.cargo.data or None
        db.session.commit()
        flash('Perfil actualizado exitosamente.', 'ok')
        return redirect(url_for('auth.perfil'))

    if pwd_form.submit.data and pwd_form.validate_on_submit():
        if not current_user.check_password(pwd_form.password_actual.data):
            pwd_form.password_actual.errors.append('La contraseña actual no es correcta.')
        else:
            current_user.set_password(pwd_form.password_nueva.data)
            db.session.commit()
            flash('Contraseña actualizada. Úsala en tu próximo inicio de sesión.', 'ok')
            return redirect(url_for('auth.perfil'))

    return render_template('auth/perfil.html', form=form, pwd_form=pwd_form)


# ---------------------------------------------------------------------------
# Recuperar contraseña con un código enviado por correo
#   1) /auth/recuperar         → el usuario escribe su correo y se le envía un código
#   2) /auth/recuperar/codigo  → escribe el código y su contraseña nueva
# Las respuestas son idénticas exista o no el correo, para no revelar quién tiene cuenta.
# ---------------------------------------------------------------------------
PREFIJO_RECUPERACION_FALLIDA = "Intento fallido de recuperación"
PREFIJO_CODIGO_ENVIADO = "Código de recuperación enviado"
PREFIJO_CODIGO_PEDIDO = "Pidió código de recuperación"
MENSAJE_RECUPERACION = "El código no es válido o ya expiró. Pide uno nuevo y usa el más reciente."
MENSAJE_ENVIADO = ("Si el correo está registrado, te enviamos un código de 6 dígitos. "
                   "Revisa también la carpeta de spam o promociones.")


def _cuenta_ip(prefijo, minutos):
    if not request.remote_addr:
        return 0
    desde = datetime.now() - timedelta(minutes=minutos)
    return Auditoria.query.filter(Auditoria.accion == "recuperacion", Auditoria.fecha >= desde,
                                  Auditoria.ip == request.remote_addr[:45],
                                  Auditoria.descripcion.startswith(prefijo, autoescape=True)).count()


def _recuperacion_bloqueada():
    """Una misma conexión no puede probar códigos ni pedir correos sin parar."""
    cfg = current_app.config
    minutos, maximo = cfg.get("LOGIN_BLOQUEO_MIN", 15), cfg.get("LOGIN_MAX_INTENTOS_IP", 20)
    return (_cuenta_ip(PREFIJO_RECUPERACION_FALLIDA, minutos) >= maximo
            or _cuenta_ip(PREFIJO_CODIGO_PEDIDO, minutos) >= maximo)


def _puede_recibir_correo(user):
    """Máximo RECUPERACION_MAX_CORREOS_HORA por cuenta y uno por minuto."""
    cfg = current_app.config
    minutos = cfg.get("RECUPERACION_MINUTOS", 15)
    if user.recuperacion_expira and user.recuperacion_expira - timedelta(minutes=minutos) > datetime.now() - timedelta(seconds=60):
        return False
    hora = datetime.now() - timedelta(hours=1)
    enviados = Auditoria.query.filter(Auditoria.accion == "recuperacion", Auditoria.entidad_id == user.id,
                                      Auditoria.fecha >= hora,
                                      Auditoria.descripcion.startswith(PREFIJO_CODIGO_ENVIADO, autoescape=True)).count()
    return enviados < cfg.get("RECUPERACION_MAX_CORREOS_HORA", 3)


def _demasiados():
    minutos = current_app.config.get("LOGIN_BLOQUEO_MIN", 15)
    flash(f'Demasiados intentos. Espera {minutos} minutos e inténtalo de nuevo.', 'danger')


def _emitir_y_enviar(email):
    """Genera y envía el código si corresponde. Lo que pasó queda en la bitácora con su
    motivo (para que el administrador sepa por qué no llegó), pero la respuesta al
    usuario es siempre la misma, exista o no la cuenta."""
    user = Usuario.query.filter(db.func.lower(Usuario.email) == email).first()
    registrar_accion("recuperacion", "Acceso", f"{PREFIJO_CODIGO_PEDIDO} para «{email[:60]}»",
                     user.id if user else None, usuario=None)
    if user is None:
        return
    if not user.puede_ingresar:
        motivo = ("la cuenta está pendiente de aprobación" if user.estado_permiso == "pendiente"
                  else "la cuenta está rechazada o desactivada")
        registrar_accion("recuperacion", "Acceso", f"No se envió el código: {motivo}", user.id, usuario=None)
        return
    if not _puede_recibir_correo(user):
        registrar_accion("recuperacion", "Acceso",
                         "No se envió el código: pidió otro hace menos de un minuto o llegó al límite por hora",
                         user.id, usuario=None)
        return
    from app.correo import correo_codigo_recuperacion
    minutos = current_app.config.get("RECUPERACION_MINUTOS", 15)
    codigo = user.emitir_codigo_recuperacion(minutos)
    db.session.commit()   # el código queda guardado antes de intentar el envío
    enviado, motivo = correo_codigo_recuperacion(user, codigo, minutos,
                                                 url_for('auth.recuperar_codigo', _external=True), detalle=True)
    if enviado:
        registrar_accion("recuperacion", "Acceso", PREFIJO_CODIGO_ENVIADO, user.id, usuario=user)
    else:
        registrar_accion("recuperacion", "Acceso", f"No se pudo enviar el correo de recuperación: {motivo}"[:300],
                         user.id, usuario=user)


@auth.route('/recuperar', methods=['GET', 'POST'])
def recuperar():
    if current_user.is_authenticated:
        return redirect(url_for('auth.perfil'))
    form = PedirCodigoForm()
    if form.validate_on_submit():
        if _recuperacion_bloqueada():
            _demasiados()
            return render_template('auth/recuperar.html', form=form), 429
        email = form.email.data.strip().lower()
        _emitir_y_enviar(email)
        db.session.commit()
        session['recuperar_email'] = email
        session['recuperar_pedido_en'] = datetime.now().timestamp()
        flash(MENSAJE_ENVIADO, 'info')
        return redirect(url_for('auth.recuperar_codigo'))
    return render_template('auth/recuperar.html', form=form)


@auth.route('/recuperar/reenviar', methods=['POST'])
def recuperar_reenviar():
    """Pide un código nuevo para el correo que ya se escribió (mismos límites que el primero)."""
    if current_user.is_authenticated:
        return redirect(url_for('auth.perfil'))
    form = PedirCodigoForm()
    if not form.validate_on_submit():
        flash('Escribe tu correo para reenviar el código.', 'danger')
        return redirect(url_for('auth.recuperar'))
    if _recuperacion_bloqueada():
        _demasiados()
        return redirect(url_for('auth.recuperar_codigo')), 303
    email = form.email.data.strip().lower()
    _emitir_y_enviar(email)
    db.session.commit()
    session['recuperar_email'] = email
    session['recuperar_pedido_en'] = datetime.now().timestamp()
    flash('Si el correo está registrado, te enviamos un código nuevo. El anterior ya no sirve; '
          'usa el más reciente y revisa spam o promociones.', 'info')
    return redirect(url_for('auth.recuperar_codigo'))


@auth.route('/recuperar/codigo', methods=['GET', 'POST'])
def recuperar_codigo():
    if current_user.is_authenticated:
        return redirect(url_for('auth.perfil'))
    form = RecuperarForm()
    if request.method == 'GET' and not form.email.data:
        form.email.data = session.get('recuperar_email', '')
    if form.validate_on_submit():
        if _recuperacion_bloqueada():
            _demasiados()
            return render_template('auth/recuperar_codigo.html', form=form), 429
        email = form.email.data.strip().lower()
        user = Usuario.query.filter(db.func.lower(Usuario.email) == email).first()
        maximo = current_app.config.get("RECUPERACION_MAX_INTENTOS", 5)
        if user and user.puede_ingresar and user.verificar_codigo_recuperacion(form.codigo.data, maximo):
            user.set_password(form.password_nueva.data)
            user.limpiar_codigo_recuperacion()   # el código es de un solo uso
            registrar_accion("recuperacion", "Acceso", "Cambió su contraseña con el código enviado por correo",
                             user.id, usuario=user)
            db.session.commit()
            session.pop('recuperar_email', None)
            flash('Contraseña cambiada. Ya puedes iniciar sesión con la nueva.', 'ok')
            return redirect(url_for('auth.login'))
        registrar_accion("recuperacion", "Acceso", f"{PREFIJO_RECUPERACION_FALLIDA} para «{email[:60]}»",
                         user.id if user else None, usuario=None)
        db.session.commit()
        flash(MENSAJE_RECUPERACION, 'danger')
    email = (form.email.data or session.get('recuperar_email') or '').strip().lower()
    # La espera sale de la sesión (cuándo lo pidió este navegador), no de la cuenta:
    # así es idéntica exista o no el correo. El límite real lo aplica _puede_recibir_correo.
    pedido = session.get('recuperar_pedido_en', 0)
    espera = max(0, int(60 - (datetime.now().timestamp() - pedido))) if pedido else 0
    return render_template('auth/recuperar_codigo.html', form=form, reenviar_form=PedirCodigoForm(formdata=None, email=email),
                           espera=espera)
