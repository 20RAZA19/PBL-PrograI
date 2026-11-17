from datetime import date
from decimal import Decimal, InvalidOperation

from flask_wtf import FlaskForm
from wtforms import DateField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

MAX_LINEAS = 20
MAX_CANTIDAD = 100_000
MAX_TRAMOS = 4  # tramos de precio por prenda (precio base + hasta 3 rebajas por volumen)


class SolicitudForm(FlaskForm):
    """Lo que llena el cliente. Las prendas llegan como filas dinámicas (ver leer_lineas)."""
    fecha_deseada = DateField("¿Para cuándo lo necesitas?", validators=[Optional()],
                              description="Opcional. La fecha de entrega real se compromete al aprobar tu propuesta.")
    notas = TextAreaField("Indicaciones generales", validators=[Optional(), Length(max=2000)],
                          description="Bordados, empaque, dirección de entrega u otros detalles.")

    def validate_fecha_deseada(self, field):
        if field.data and field.data < date.today():
            raise ValidationError("La fecha no puede estar en el pasado.")


class AprobarForm(FlaskForm):
    """La empresa aprueba la prenda. Los tramos de precio llegan como tramo_desde_<id> / tramo_precio_<id>
    (ver leer_tramos) y las etiquetas de condición como casillas `etiqueta`."""
    fecha_entrega = DateField("Entrega estimada", validators=[DataRequired("Indica la fecha estimada de entrega.")],
                              description="Fecha a la que se compromete el taller si el cliente acepta hoy.")
    condiciones = TextAreaField("Condiciones de cambio", validators=[Optional(), Length(max=1000)],
                                description="Según las políticas de la empresa. El cliente las acepta junto con la cotización.")
    respuesta = TextAreaField("Mensaje para el cliente", validators=[Optional(), Length(max=1000)])

    def validate_fecha_entrega(self, field):
        if field.data and field.data < date.today():
            raise ValidationError("La fecha de entrega no puede estar en el pasado.")


class DenegarForm(FlaskForm):
    respuesta = TextAreaField("Motivo", validators=[DataRequired("Explica al cliente por qué se deniega su propuesta."),
                                                    Length(max=1000)])


class DeclinarForm(FlaskForm):
    """El cliente declina la cotización; el motivo es opcional pero ayuda a Ventas."""
    motivo = TextAreaField("¿Por qué la declinas? (opcional)", validators=[Optional(), Length(max=500)])


def _texto(lista, i, largo):
    return ((lista[i] if i < len(lista) else "") or "").strip()[:largo] or None


def leer_lineas(formdata, disenos_permitidos):
    """Lee las prendas del formulario del cliente.

    `disenos_permitidos` es {id: Diseno} con los diseños que ese cliente puede pedir:
    un id que no esté ahí se ignora (nadie puede solicitar el diseño de otra empresa).
    Devuelve (lineas, errores).
    """
    disenos = formdata.getlist("linea_diseno")
    descripciones = formdata.getlist("linea_descripcion")
    cantidades = formdata.getlist("linea_cantidad")
    tallas = formdata.getlist("linea_tallas")
    colores = formdata.getlist("linea_colores")
    medidas = formdata.getlist("linea_medidas")

    lineas, errores = [], []
    for i, descripcion in enumerate(descripciones):
        descripcion = (descripcion or "").strip()
        cantidad_txt = (cantidades[i] if i < len(cantidades) else "").strip()
        if not descripcion and not cantidad_txt and not _texto(medidas, i, 500):
            continue
        n = len(lineas) + 1
        try:
            diseno_id = int(disenos[i]) if i < len(disenos) and disenos[i] else None
        except ValueError:
            diseno_id = None
        diseno = disenos_permitidos.get(diseno_id) if diseno_id else None
        if not descripcion and diseno:
            descripcion = diseno.nombre
        if not descripcion:
            errores.append(f"Prenda {n}: escribe qué prenda necesitas.")
        try:
            cantidad = int(cantidad_txt)
            if not 1 <= cantidad <= MAX_CANTIDAD:
                raise ValueError
        except ValueError:
            errores.append(f"Prenda {n}: la cantidad debe ser un número entero entre 1 y {MAX_CANTIDAD:,}.")
            cantidad = None
        lineas.append({"diseno_id": diseno.id if diseno else None, "descripcion": descripcion[:200],
                       "cantidad": cantidad, "tallas": _texto(tallas, i, 100), "colores": _texto(colores, i, 100),
                       "medidas": _texto(medidas, i, 500)})
    if not lineas:
        errores.append("Agrega al menos una prenda a la solicitud.")
    elif len(lineas) > MAX_LINEAS:
        errores.append(f"Una solicitud admite hasta {MAX_LINEAS} prendas distintas. Divide el pedido en dos solicitudes.")
    return lineas, errores


def leer_tramos(formdata, solicitud):
    """Tramos de precio por cantidad para cada línea (rebajas por mayoreo).

    Llegan como filas paralelas tramo_desde_<id> / tramo_precio_<id>. El primer tramo
    siempre cubre desde 1 unidad (precio base); los demás son opcionales y, como son
    rebajas, su precio no puede subir. Devuelve ({linea_id: [(desde, precio), ...]}, errores).
    """
    tramos, errores = {}, []
    for n, linea in enumerate(solicitud.lineas, start=1):
        quien = f"Prenda {n} ({linea.descripcion})"
        desdes = formdata.getlist(f"tramo_desde_{linea.id}")
        precios = formdata.getlist(f"tramo_precio_{linea.id}")
        filas, con_error = [], False
        for i in range(min(len(desdes), len(precios), MAX_TRAMOS)):
            d_txt = (desdes[i] or "").strip().replace(",", "")
            p_txt = (precios[i] or "").strip().replace(",", "").replace("$", "")
            if not d_txt and not p_txt:
                continue  # fila opcional vacía
            try:
                desde = int(d_txt)
                if not 1 <= desde <= MAX_CANTIDAD:
                    raise ValueError
            except ValueError:
                errores.append(f"{quien}: el «desde» de cada tramo debe ser un entero entre 1 y {MAX_CANTIDAD:,}.")
                con_error = True
                continue
            try:
                precio = Decimal(p_txt)
                if not precio.is_finite() or precio <= 0 or precio > Decimal("99999.99"):
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                errores.append(f"{quien}: indica un precio mayor a 0 para el tramo desde {desde:,} unidades.")
                con_error = True
                continue
            filas.append((desde, precio.quantize(Decimal("0.01"))))
        if con_error:
            continue
        filas.sort()
        if not filas or filas[0][0] != 1:
            errores.append(f"{quien}: define el precio base (tramo desde 1 unidad).")
            continue
        if len({d for d, _ in filas}) != len(filas):
            errores.append(f"{quien}: hay dos tramos con el mismo «desde».")
            continue
        for (_, p1), (d2, p2) in zip(filas, filas[1:]):
            if p2 > p1:
                errores.append(f"{quien}: el precio desde {d2:,} unidades no puede ser mayor que el del tramo "
                               "anterior; los tramos son rebajas por cantidad.")
                break
        else:
            tramos[linea.id] = filas
    return tramos, errores


def leer_etiquetas(formdata):
    """Etiquetas de condición marcadas (solo se aceptan las predefinidas)."""
    from app.models import ETIQUETAS_CONDICION
    elegidas = [e for e in formdata.getlist("etiqueta") if e in ETIQUETAS_CONDICION]
    return ", ".join(dict.fromkeys(elegidas)) or None
