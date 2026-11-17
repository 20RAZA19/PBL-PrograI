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
