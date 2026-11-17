"""Documentos para clientes y proveedores: cotizaciones y órdenes de compra.

Cada documento se describe una sola vez como un diccionario y luego se dibuja
como PDF (con reportlab) o, si reportlab no está instalado, como una página
HTML lista para imprimir / guardar como PDF desde el navegador.
"""
import os
from decimal import Decimal
from io import BytesIO

from flask import current_app, render_template, make_response

MESES_LARGOS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

VERDE = "#2D5128"
VERDE_CLARO = "#EEF3E8"


def dinero(valor):
    if valor is None:
        return "—"
    valor = Decimal(str(valor))
    signo = "-" if valor < 0 else ""
    return f"{signo}${abs(valor):,.2f}"


def fecha_larga(fecha):
    if not fecha:
        return "—"
    return f"{fecha.day} de {MESES_LARGOS[fecha.month - 1]} de {fecha.year}"


def cantidad(valor):
    valor = float(valor or 0)
    return f"{valor:,.0f}" if valor.is_integer() else f"{valor:,.2f}"


def _empresa():
    cfg = current_app.config
    return {
        "nombre": cfg.get("EMPRESA_NOMBRE", "Arte y Color"),
        "lineas": [l for l in (cfg.get("EMPRESA_DIRECCION"), cfg.get("EMPRESA_TELEFONO"),
                               cfg.get("EMPRESA_EMAIL"), cfg.get("EMPRESA_NIT")) if l],
    }


# ---------------------------------------------------------------------------
# Descripción de cada documento
# ---------------------------------------------------------------------------
def documento_cotizacion(cot):
    cliente = cot.cliente
    filas = [[l.descripcion, l.tallas or "—", cantidad(l.cantidad), dinero(l.precio_unitario), dinero(l.importe)]
             for l in cot.lineas]
    totales = [("Subtotal", dinero(cot.subtotal))]
    if cot.descuento_pct:
        totales.append((f"Descuento ({cantidad(cot.descuento_pct)}%)", "-" + dinero(cot.descuento)))
    totales.append((f"IVA ({cantidad(cot.iva_pct)}%)", dinero(cot.iva)))
    totales.append(("TOTAL", dinero(cot.total)))
    notas = []
    if cot.condiciones:
        notas.append(("Condiciones", cot.condiciones))
    if cot.notas:
        notas.append(("Notas", cot.notas))
    return {
        "tipo": "COTIZACIÓN",
        "folio": cot.folio,
        "nombre_archivo": f"{cot.folio}.pdf",
        "empresa": _empresa(),
        "datos": [
            ("Fecha", fecha_larga(cot.fecha)),
            ("Válida hasta", fecha_larga(cot.fecha_vencimiento)),
            ("Entrega estimada", fecha_larga(cot.fecha_entrega)),
            ("Estado", cot.estado_legible),
        ],
        "destinatario": {
            "titulo": "Cliente",
            "nombre": cliente.nombre,
            "lineas": [l for l in (cliente.contacto and f"Atención: {cliente.contacto}",
                                   cliente.telefono, cliente.email) if l],
        },
        "columnas": ["Descripción", "Tallas", "Cantidad", "Precio unit.", "Importe"],
        "anchos": [0.38, 0.2, 0.12, 0.15, 0.15],
        "alinear": ["L", "L", "R", "R", "R"],
        "filas": filas,
        "totales": totales,
        "notas": notas,
        "pie": f"Elaborada por {cot.usuario.nombre if cot.usuario else 'Arte y Color'} · "
               f"{cot.total_prendas:,} prendas · Precios en dólares de EE. UU.",
    }


def documento_orden_compra(oc):
    prov = oc.proveedor
    filas = [[l.insumo.codigo or "—", l.insumo.nombre, f"{cantidad(l.cantidad)} {l.insumo.unidad_medida.lower()}",
              dinero(l.costo_unitario), dinero(l.importe)] for l in oc.lineas]
    notas = [("Notas", oc.notas)] if oc.notas else []
    return {
        "tipo": "ORDEN DE COMPRA",
        "folio": oc.folio,
        "nombre_archivo": f"{oc.folio}.pdf",
        "empresa": _empresa(),
        "datos": [
            ("Fecha", fecha_larga(oc.fecha)),
            ("Entrega solicitada", fecha_larga(oc.fecha_esperada)),
            ("Estado", oc.estado_legible),
        ],
        "destinatario": {
            "titulo": "Proveedor",
            "nombre": prov.nombre if prov else "Proveedor por asignar",
            "lineas": [l for l in ((prov.contacto and f"Atención: {prov.contacto}") if prov else None,
                                   prov.telefono if prov else None, prov.email if prov else None) if l],
        },
        "columnas": ["Código", "Insumo", "Cantidad", "Costo unit.", "Importe"],
        "anchos": [0.14, 0.38, 0.18, 0.15, 0.15],
        "alinear": ["L", "L", "R", "R", "R"],
        "filas": filas,
        "totales": [("TOTAL", dinero(oc.total))],
        "notas": notas,
        "pie": f"Solicitada por {oc.usuario.nombre if oc.usuario else 'Arte y Color'} · "
               "Favor confirmar disponibilidad y fecha de entrega.",
    }


# ---------------------------------------------------------------------------
# Salida
# ---------------------------------------------------------------------------
def reportlab_disponible():
    try:
        import reportlab  # noqa: F401
        return True
    except ImportError:
        return False


def respuesta_documento(doc, descargar=False):
    """PDF si hay reportlab; si no, la versión HTML imprimible."""
    if not reportlab_disponible() or current_app.config.get("DOCUMENTOS_HTML"):
        return render_template("documentos/imprimible.html", doc=doc)
    pdf = generar_pdf(doc)
    resp = make_response(pdf)
    resp.headers["Content-Type"] = "application/pdf"
    modo = "attachment" if descargar else "inline"
    resp.headers["Content-Disposition"] = f'{modo}; filename="{doc["nombre_archivo"]}"'
    return resp


def generar_pdf(doc):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (Image, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle)
    from xml.sax.saxutils import escape

    verde = colors.HexColor(VERDE)
    verde_claro = colors.HexColor(VERDE_CLARO)
    gris = colors.HexColor("#64748B")
    borde = colors.HexColor("#D9E2D4")

    estilos = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=estilos["Normal"], fontName="Helvetica", fontSize=9, leading=12)
    pequeno = ParagraphStyle("p", parent=normal, fontSize=8, leading=10, textColor=gris)
    negrita = ParagraphStyle("b", parent=normal, fontName="Helvetica-Bold")
    titulo = ParagraphStyle("t", parent=normal, fontName="Helvetica-Bold", fontSize=16, leading=20,
                            textColor=verde, alignment=TA_RIGHT)
    derecha = ParagraphStyle("r", parent=normal, alignment=TA_RIGHT)
    celda_head = ParagraphStyle("h", parent=normal, fontName="Helvetica-Bold", textColor=colors.white)

    def p(texto, estilo=normal):
        return Paragraph(escape(str(texto)).replace("\n", "<br/>"), estilo)

    buffer = BytesIO()
    ancho_util = letter[0] - 3.6 * cm

    def pie_pagina(canvas, documento):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(gris)
        canvas.drawString(1.8 * cm, 1.2 * cm, f"{doc['tipo'].capitalize()} {doc['folio']} · Generado con AyC Control")
        canvas.drawRightString(letter[0] - 1.8 * cm, 1.2 * cm, f"Página {documento.page}")
        canvas.setStrokeColor(verde)
        canvas.setLineWidth(3)
        canvas.line(0, letter[1] - 4, letter[0], letter[1] - 4)
        canvas.restoreState()

    pdf = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
                            topMargin=1.6 * cm, bottomMargin=2 * cm,
                            title=f"{doc['tipo'].capitalize()} {doc['folio']}", author=doc["empresa"]["nombre"])
    elementos = []

    # Encabezado: logo + empresa | tipo y folio
    logo_ruta = os.path.join(current_app.static_folder, "img", "logo.png")
    izquierda = []
    if os.path.exists(logo_ruta):
        try:
            from reportlab.lib.utils import ImageReader
            iw, ih = ImageReader(logo_ruta).getSize()
            alto = 1.5 * cm
            izquierda.append(Image(logo_ruta, width=alto * iw / ih, height=alto))
            izquierda.append(Spacer(1, 4))
        except Exception:  # sin Pillow o imagen dañada: el documento sigue sin logo
            pass
    izquierda.append(p(doc["empresa"]["nombre"], negrita))
    for linea in doc["empresa"]["lineas"]:
        izquierda.append(p(linea, pequeno))
    derecha_col = [p(doc["tipo"], titulo), p(doc["folio"], ParagraphStyle("f", parent=derecha, fontSize=11,
                                                                       fontName="Helvetica-Bold"))]
    cab = Table([[izquierda, derecha_col]], colWidths=[ancho_util * 0.55, ancho_util * 0.45])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    elementos += [cab, Spacer(1, 14)]

    # Destinatario | datos del documento
    dest = doc["destinatario"]
    bloque_dest = [p(dest["titulo"].upper(), pequeno), p(dest["nombre"], negrita)] + [p(l) for l in dest["lineas"]]
    filas_datos = [[p(k, pequeno), p(v, derecha)] for k, v in doc["datos"]]
    tabla_datos = Table(filas_datos, colWidths=[ancho_util * 0.16, ancho_util * 0.22])
    tabla_datos.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                     ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    info = Table([[bloque_dest, tabla_datos]], colWidths=[ancho_util * 0.58, ancho_util * 0.42])
    info.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, -1), verde_claro),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    elementos += [info, Spacer(1, 16)]

    # Detalle
    estilos_col = [derecha if a == "R" else normal for a in doc["alinear"]]
    filas = [[Paragraph(escape(c), ParagraphStyle(f"h{i}", parent=celda_head,
                                                  alignment=TA_RIGHT if doc["alinear"][i] == "R" else 0))
              for i, c in enumerate(doc["columnas"])]]
    for fila in doc["filas"]:
        filas.append([p(valor, estilos_col[i]) for i, valor in enumerate(fila)])
    if len(filas) == 1:
        filas.append([p("Sin líneas registradas.", pequeno)] + [""] * (len(doc["columnas"]) - 1))
    detalle = Table(filas, colWidths=[ancho_util * a for a in doc["anchos"]], repeatRows=1)
    estilo_tabla = [
        ("BACKGROUND", (0, 0), (-1, 0), verde),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, borde),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(2, len(filas), 2):
        estilo_tabla.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F7F9F7")))
    detalle.setStyle(TableStyle(estilo_tabla))
    elementos += [detalle, Spacer(1, 10)]

    # Totales
    tot = []
    for i, (k, v) in enumerate(doc["totales"]):
        ultimo = i == len(doc["totales"]) - 1
        est = ParagraphStyle(f"tt{i}", parent=derecha, fontName="Helvetica-Bold" if ultimo else "Helvetica",
                             fontSize=11 if ultimo else 9, textColor=colors.white if ultimo else colors.black)
        tot.append([p(k, est), p(v, est)])
    tabla_tot = Table(tot, colWidths=[ancho_util * 0.2, ancho_util * 0.18], hAlign="RIGHT")
    tabla_tot.setStyle(TableStyle([
        ("BACKGROUND", (0, len(tot) - 1), (-1, len(tot) - 1), verde),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elementos += [tabla_tot, Spacer(1, 18)]

    for nombre, texto in doc["notas"]:
        elementos += [p(nombre.upper(), pequeno), p(texto), Spacer(1, 8)]
    if doc.get("pie"):
        elementos += [Spacer(1, 6), p(doc["pie"], pequeno)]

    pdf.build(elementos, onFirstPage=pie_pagina, onLaterPages=pie_pagina)
    return buffer.getvalue()
