from datetime import date

from flask import request


def generar_folio(modelo, prefijo):
    """Folio consecutivo por año: COT-2026-0001, OC-2026-0007…"""
    anio = date.today().year
    base = f"{prefijo}-{anio}-"
    existentes = [f for (f,) in modelo.query.with_entities(modelo.folio)
                  .filter(modelo.folio.like(base + "%")).all()]
    numeros = [int(f[len(base):]) for f in existentes if f[len(base):].isdigit()]
    return f"{base}{(max(numeros) + 1 if numeros else 1):04d}"


def destino_seguro(valor, por_defecto):
    """Solo permite redirigir a rutas internas (evita redirecciones abiertas)."""
    if valor and valor.startswith("/") and not valor.startswith("//"):
        return valor
    return por_defecto


def volver_a(por_defecto):
    return destino_seguro(request.form.get("volver") or request.args.get("volver"), por_defecto)


def celda_csv(valor):
    """Evita la «inyección de fórmulas»: Excel ejecuta celdas que empiezan con = + - @."""
    if isinstance(valor, str) and valor[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + valor
    return valor


def fila_csv(valores):
    return [celda_csv(v) for v in valores]


# --- Paginación -------------------------------------------------------------------
# Las listas consultan solo una página de registros (LIMIT/OFFSET en la base de datos)
# en lugar de traer la tabla completa. El tamaño se elige con ?por= y la página con ?pagina=.
TAMANOS_PAGINA = (10, 25, 50, 100)


def paginar(query, por_defecto=25, ordenes=None):
    """Pagina una consulta de SQLAlchemy y devuelve el objeto Pagination.

    `ordenes` es un dict {clave: (etiqueta, [expresiones de orden])}; el primero es el
    predeterminado. Se elige con ?orden=. Si piden una página que ya no existe (p. ej.
    tras filtrar), devuelve la última.
    """
    por = request.args.get("por", por_defecto, type=int)
    if por not in TAMANOS_PAGINA and por != por_defecto:
        por = por_defecto
    orden_actual = None
    if ordenes:
        orden_actual = request.args.get("orden")
        if orden_actual not in ordenes:
            orden_actual = next(iter(ordenes))
        query = query.order_by(*ordenes[orden_actual][1])
    numero = max(request.args.get("pagina", 1, type=int) or 1, 1)
    pagina = query.paginate(page=numero, per_page=por, error_out=False)
    if pagina.pages and numero > pagina.pages:
        pagina = query.paginate(page=pagina.pages, per_page=por, error_out=False)
    if ordenes:
        pagina.orden_actual = orden_actual
        pagina.opciones_orden = [(k, etiqueta) for k, (etiqueta, _) in ordenes.items()]
    return pagina
