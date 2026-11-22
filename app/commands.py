from datetime import date, datetime, timedelta
import click
from flask.cli import with_appcontext
from app.extensions import db
from app.models import Usuario, Tela, Cliente, Diseno, DisenoTela, Pedido, EventoRastreo


@click.command("seed")
@with_appcontext
def seed():
    """Carga datos de ejemplo. Es idempotente: solo crea lo que falte."""
    _seed_base()
    _seed_usuarios_demo()
    _seed_pedidos_demo()
    db.session.commit()
    click.echo("Datos de ejemplo listos.")
    click.echo("  admin123 / admin123                     (Administrador)")
    click.echo("  gestor@arteycolor.com / gestor123       (Gestor de Taller)")
    click.echo("  cliente@banconacional.com / cliente123  (Cliente)")


def _seed_base():
    """Datos originales del proyecto (usuario admin123, telas, cliente, diseño y pedido)."""
    if Usuario.query.filter_by(email="admin123").first():
        click.echo("El usuario admin123 ya existe en la base de datos.")
        return

    admin = Usuario(
        nombre="Administrador General",
        email="admin123",
        cargo="Jefe de Producción",
        rol="admin",
        estado_permiso="aprobado"
    )
    admin.set_password("admin123")

    algodon = Tela(
        nombre="Algodón Pima Verde Gras",
        codigo_pantone="Pantone 348 C",
        color_hex="#2D5128",
        cantidad_disponible=320,
        stock_minimo=100
    )
    poliester_azul = Tela(
        nombre="Poliéster Secado Rápido Azul",
        codigo_pantone="Pantone 2925 C",
        color_hex="#0085CA",
        cantidad_disponible=85,
        stock_minimo=100
    )
    oxford = Tela(
        nombre="Oxford Blanco Premium",
        codigo_pantone="Pantone White C",
        color_hex="#F4F5F7",
        cantidad_disponible=540,
        stock_minimo=100
    )
    gabardina = Tela(
        nombre="Gabardina Roja Institucional",
        codigo_pantone="Pantone 186 C",
        color_hex="#C8102E",
        cantidad_disponible=190,
        stock_minimo=100
    )
    drifit = Tela(
        nombre="Dri-Fit Marino Deportivo",
        codigo_pantone="Pantone 289 C",
        color_hex="#0C2340",
        cantidad_disponible=42,
        stock_minimo=100
    )
    cuello = Tela(
        nombre="Poliéster Cuello Blanco",
        codigo_pantone="Pantone White C",
        color_hex="#FFFFFF",
        cantidad_disponible=150,
        stock_minimo=100
    )

    cliente = Cliente(nombre="Banco Nacional de México")

    polo = Diseno(
        nombre="Polo Corporativa Banco Nacional 2025",
        tipo_prenda="Polo manga corta, corte slim",
        tallas="S, M, L, XL, XXL",
        imagen="img/disenos/polo-corporativa.png",
        cliente=cliente
    )
    polo.telas.append(DisenoTela(tela=algodon, metros_por_unidad=1.2))
    polo.telas.append(DisenoTela(tela=cuello, metros_por_unidad=0.3))

    pedido = Pedido(
        folio="ORD-20261026-001",
        modelo_prenda="Polo Corporativa Banco Nacional 2025",
        diseno=polo,
        cliente=cliente,
        cantidad=500,
        estado="En Corte",
        fase_tracking=2,
        fecha_limite=date(2026, 11, 15)
    )

    db.session.add_all([
        admin, algodon, poliester_azul, oxford, gabardina,
        drifit, cuello, cliente, polo, pedido
    ])
    db.session.flush()
    for i, tela in enumerate([algodon, poliester_azul, oxford, gabardina, drifit, cuello], start=1):
        tela.codigo = tela.codigo or f"TEL-{tela.id:04d}"
    click.echo("Datos base y usuario admin123 creados exitosamente.")


def _seed_usuarios_demo():
    banco = Cliente.query.filter_by(nombre="Banco Nacional de México").first()

    demo = [
        dict(email="gestor@arteycolor.com", nombre="Marta López", rol="gestor",
             cargo="Supervisora de Taller", password="gestor123", cliente=None),
        dict(email="cliente@banconacional.com", nombre="Carlos Méndez", rol="cliente",
             cargo="Compras Corporativas", password="cliente123", cliente=banco),
    ]
    for d in demo:
        if Usuario.query.filter_by(email=d["email"]).first():
            continue
        u = Usuario(nombre=d["nombre"], email=d["email"], rol=d["rol"],
                    cargo=d["cargo"], estado_permiso="aprobado", cliente=d["cliente"])
        u.set_password(d["password"])
        db.session.add(u)

    # Una solicitud pendiente para probar el panel de administración
    if not Usuario.query.filter_by(email="nuevo.gestor@arteycolor.com").first():
        u = Usuario(nombre="Diego Ramírez", email="nuevo.gestor@arteycolor.com",
                    rol="gestor", estado_permiso="pendiente", cargo="Cortador")
        u.set_password("gestor123")
        db.session.add(u)
    db.session.flush()


def _seed_pedidos_demo():
    banco = Cliente.query.filter_by(nombre="Banco Nacional de México").first()
    polo = Diseno.query.filter_by(nombre="Polo Corporativa Banco Nacional 2025").first()
    if banco is None:
        return

    taller = (13.6929, -89.2182)
    hoy = date.today()
    ahora = datetime.now()

    # Rutas de ejemplo: (estado, ubicación, lat, lng, horas atrás)
    pedidos_demo = [
        {
            "folio": "ORD-DEMO-0002", "modelo": "Camisa Oxford Ejecutiva", "cantidad": 220,
            "estado": "En Costura", "limite": hoy + timedelta(days=12),
            "ruta": [("Recibido", "Taller Principal", *taller, 96),
                     ("En Corte", "Área de Corte · Taller Principal", *taller, 70),
                     ("En Costura", "Línea de Costura 2", *taller, 20)],
        },
        {
            "folio": "ORD-DEMO-0003", "modelo": "Polo Corporativa Banco Nacional 2025", "cantidad": 350,
            "estado": "En Ruta", "limite": hoy + timedelta(days=2), "diseno": polo,
            "ruta": [("Recibido", "Taller Principal", *taller, 240),
                     ("En Corte", "Área de Corte · Taller Principal", *taller, 200),
                     ("En Costura", "Línea de Costura 1", *taller, 150),
                     ("Terminado", "Bodega de Empaque", *taller, 30),
                     ("En Ruta", "Carretera Panamericana · Santa Tecla", 13.6740, -89.2890, 2)],
        },
        {
            "folio": "ORD-DEMO-0004", "modelo": "Gabacha Institucional Roja", "cantidad": 120,
            "estado": "Entregado", "limite": hoy - timedelta(days=3),
            "ruta": [("Recibido", "Taller Principal", *taller, 400),
                     ("En Corte", "Área de Corte · Taller Principal", *taller, 360),
                     ("En Costura", "Línea de Costura 3", *taller, 300),
                     ("Terminado", "Bodega de Empaque", *taller, 200),
                     ("En Ruta", "Bulevar Los Próceres", 13.6880, -89.2330, 100),
                     ("Entregado", "Oficinas Centrales del Cliente", 13.7010, -89.2440, 90)],
        },
    ]

    for d in pedidos_demo:
        if Pedido.query.filter_by(folio=d["folio"]).first():
            continue
        ultimo = d["ruta"][-1]
        p = Pedido(folio=d["folio"], modelo_prenda=d["modelo"], cantidad=d["cantidad"],
                   cliente=banco, diseno=d.get("diseno"), fecha_limite=d["limite"],
                   ubicacion_actual=ultimo[1], latitud=ultimo[2], longitud=ultimo[3],
                   creado_en=ahora - timedelta(hours=d["ruta"][0][4]))
        p.cambiar_estado(d["estado"])
        db.session.add(p)
        for i, (estado, ubic, lat, lng, horas) in enumerate(d["ruta"], start=1):
            db.session.add(EventoRastreo(
                pedido=p, estado=estado, fase=i, ubicacion=ubic, latitud=lat, longitud=lng,
                fecha=ahora - timedelta(hours=horas),
                nota="Pedido en camino al cliente." if estado == "En Ruta" else None,
            ))

    # El pedido original sin historial recibe sus eventos iniciales
    original = Pedido.query.filter_by(folio="ORD-20261026-001").first()
    if original and not original.eventos:
        original.cambiar_estado(original.estado)
        original.latitud, original.longitud = original.latitud or taller[0], original.longitud or taller[1]
        db.session.add(EventoRastreo(pedido=original, estado="Recibido", fase=1,
                                     ubicacion="Taller Principal", latitud=taller[0], longitud=taller[1],
                                     fecha=ahora - timedelta(hours=30)))
        if original.fase_actual >= 2:
            db.session.add(EventoRastreo(pedido=original, estado=original.estado, fase=original.fase_actual,
                                         ubicacion=original.ubicacion_actual or "Taller Principal",
                                         latitud=taller[0], longitud=taller[1],
                                         fecha=ahora - timedelta(hours=6)))


# ===========================================================================
# Datos de demostración (solo para visualizar el sistema con información)
# ===========================================================================
@click.command("demo")
@with_appcontext
def demo():
    """Carga datos de DEMOSTRACIÓN: clientes, proveedores, insumos, pedidos, notas y movimientos.

    Es idempotente (no duplica nada si se ejecuta dos veces). Úsalo para
    presentar el sistema; no lo ejecutes sobre la base de datos de producción.
    """
    from app.models import Proveedor, Movimiento, NotaContacto

    _seed_base()
    _seed_usuarios_demo()
    _seed_pedidos_demo()
    db.session.flush()

    ahora = datetime.now()
    hoy = date.today()
    admin = Usuario.query.filter_by(email="admin123").first()
    gestor = Usuario.query.filter_by(email="gestor@arteycolor.com").first()

    # --- Usuarios de demostración -------------------------------------------
    if not Usuario.query.filter_by(email="ventas@arteycolor.com").first():
        u = Usuario(nombre="Lucía Hernández", email="ventas@arteycolor.com", rol="ventas",
                    cargo="Asistente de Ventas", telefono="+503 7012 3344", estado_permiso="aprobado")
        u.set_password("ventas123")
        db.session.add(u)
    ventas = Usuario.query.filter_by(email="ventas@arteycolor.com").first() or u

    # Corrige el Pantone duplicado de los datos originales (dos telas con «Pantone White C»)
    cuello = Tela.query.filter_by(nombre="Poliéster Cuello Blanco").first()
    if cuello and cuello.codigo_pantone == "Pantone White C":
        cuello.codigo_pantone = "Pantone 11-0601 TCX"

    # --- Clientes -----------------------------------------------------------
    clientes_demo = [
        ("Colegio San José", "Hna. Marta Ayala", "+503 2243 1100", "compras@colegiosanjose.edu.sv",
         "Uniformes escolares de primaria y bachillerato. Logo bordado en el pecho izquierdo. Entregas en enero y julio."),
        ("Hospital Divina Providencia", "Lic. Roberto Pineda", "+503 2260 4410", "suministros@hdp.org.sv",
         "Filipinas y gabachas antifluido. Colores por área: azul quirófano, verde emergencias."),
        ("Alcaldía de Santa Tecla", "Ing. Karla Menjívar", "+503 2500 1200", "uaci@santatecla.gob.sv",
         "Licitaciones públicas: requiere ficha técnica impresa y muestras físicas antes de producción."),
        ("Club Deportivo Los Halcones", "Diego Portillo", "+503 7890 2211", "halcones.club@gmail.com",
         "Camisetas Dri-Fit con sublimación de números. Tallas juveniles y adulto."),
        ("Supermercados La Económica", "Andrea Flores", "+503 2121 7788", "rrhh@laeconomica.com.sv",
         "Polos y gabachas para cajeros y bodega. Pedido trimestral."),
    ]
    clientes = {}
    for nombre, contacto, tel, email, notas in clientes_demo:
        c = Cliente.query.filter_by(nombre=nombre).first()
        if c is None:
            c = Cliente(nombre=nombre, contacto=contacto, telefono=tel, email=email, notas=notas,
                        creado_en=ahora - timedelta(days=60))
            db.session.add(c)
        clientes[nombre] = c
    banco = Cliente.query.filter_by(nombre="Banco Nacional de México").first()
    if banco and not banco.contacto:
        banco.contacto, banco.telefono, banco.email = "Carlos Méndez", "+52 55 5100 2000", "compras@banconacional.mx"
        banco.notas = "Polo corporativo verde institucional. Bordado del logo en pecho derecho."
    clientes["Banco Nacional de México"] = banco

    # Usuario cliente adicional (Colegio)
    if not Usuario.query.filter_by(email="colegio@sanjose.edu.sv").first():
        u = Usuario(nombre="Marta Ayala", email="colegio@sanjose.edu.sv", rol="cliente",
                    cargo="Compras", estado_permiso="aprobado", cliente=clientes["Colegio San José"])
        u.set_password("cliente123")
        db.session.add(u)

    # --- Proveedores --------------------------------------------------------
    proveedores_demo = [
        ("Textiles del Pacífico", "Telas de algodón, gabardina y poliéster", "Mario Aguilar", "+503 2440 9000",
         "ventas@textilespacifico.com", "Precio preferencial en pedidos mayores a 500 m. Entrega en 5 días hábiles."),
        ("Hilos y Avíos Centroamérica", "Hilos, botones y elásticos", "Sofía Rivas", "+503 2233 4455",
         "pedidos@hilosca.com", "Crédito a 30 días. Pedido mínimo: 20 conos de hilo."),
        ("Cierres y Accesorios La Unión", "Cierres, etiquetas y broches", "José Martínez", "+503 2675 1122",
         "launion.accesorios@gmail.com", "Etiquetas tejidas con logo: 10 días de fabricación."),
    ]
    proveedores = {}
    for nombre, rubro, contacto, tel, email, acuerdos in proveedores_demo:
        p = Proveedor.query.filter_by(nombre=nombre).first()
        if p is None:
            p = Proveedor(nombre=nombre, rubro=rubro, contacto=contacto, telefono=tel, email=email,
                          notas_acuerdos=acuerdos, creado_en=ahora - timedelta(days=90))
            db.session.add(p)
        proveedores[nombre] = p

    # --- Insumos (colores y Pantone únicos por categoría) -------------------
    insumos_demo = [
        # nombre, categoría, unidad, tipo, pantone, color, disponible, mínimo
        ("Piqué Azul Rey", "Tela", "Metros", "Piqué 100% algodón", "Pantone 286 C", "#0033A0", 410, 120),
        ("Gabardina Caqui", "Tela", "Metros", "Gabardina stretch", "Pantone 4525 C", "#B9A66B", 260, 100),
        ("Popelina Celeste", "Tela", "Metros", "Popelina para camisa", "Pantone 290 C", "#B9D9EB", 75, 100),
        ("Antifluido Azul Quirófano", "Tela", "Metros", "Poliéster antifluido", "Pantone 3015 C", "#00629B", 180, 80),
        ("Jersey Negro", "Tela", "Metros", "Jersey de algodón", "Pantone Black 6 C", "#101820", 35, 90),
        ("Hilo Poliéster Blanco", "Hilo", "Conos", "Calibre 40/2 · 5000 yd", "Pantone 11-0601 TCX", "#FAFAFA", 64, 20),
        ("Hilo Poliéster Verde", "Hilo", "Conos", "Calibre 40/2 · 5000 yd", "Pantone 348 C", "#2D5128", 12, 20),
        ("Hilo Poliéster Azul Marino", "Hilo", "Conos", "Calibre 40/2 · 5000 yd", "Pantone 289 C", "#0C2340", 28, 20),
        ("Botón Nácar 4 Hoyos", "Botón", "Unidades", "18 líneas", None, "#F2EFE6", 2400, 500),
        ("Botón Negro Polo", "Botón", "Unidades", "16 líneas", None, "#1C1C1C", 380, 500),
        ("Cierre Invisible 20 cm", "Cierre", "Unidades", "Nylon", None, "#3A3A3A", 650, 200),
        ("Elástico Plano 2 cm", "Elástico", "Metros", "Poliéster", None, "#FFFFFF", 140, 50),
        ("Etiqueta Tejida Arte y Color", "Etiqueta", "Unidades", "Talla y composición", None, "#537B2F", 1800, 300),
    ]
    insumos = {}
    nuevos_insumos = []
    for nombre, cat, unidad, tipo, pantone, color, disp, minimo in insumos_demo:
        i = Tela.query.filter_by(nombre=nombre).first()
        if i is None:
            i = Tela(nombre=nombre, categoria=cat, unidad_medida=unidad, tipo=tipo, codigo_pantone=pantone,
                     color_hex=color, cantidad_disponible=disp, stock_minimo=minimo,
                     creado_en=ahora - timedelta(days=45))
            db.session.add(i)
            nuevos_insumos.append(i)
        insumos[nombre] = i
    for nombre in ["Algodón Pima Verde Gras", "Poliéster Secado Rápido Azul", "Oxford Blanco Premium",
                   "Gabardina Roja Institucional", "Dri-Fit Marino Deportivo", "Poliéster Cuello Blanco"]:
        insumos[nombre] = Tela.query.filter_by(nombre=nombre).first()
    db.session.flush()
    prefijos = {"Tela": "TEL", "Hilo": "HIL", "Botón": "BOT", "Cierre": "CIE", "Elástico": "ELA", "Etiqueta": "ETI"}
    for i in Tela.query.filter(Tela.codigo.is_(None)).all():
        i.codigo = f"{prefijos.get(i.categoria, 'INS')}-{i.id:04d}"

    # --- Diseños ------------------------------------------------------------
    disenos_demo = [
        ("Camisa Escolar Oxford Celeste", "Colegio San José", "Camisa manga corta escolar", "6, 8, 10, 12, 14, S, M",
         [("Popelina Celeste", 1.1)]),
        ("Pantalón Escolar Caqui", "Colegio San José", "Pantalón corte recto", "6, 8, 10, 12, 14, 28, 30, 32",
         [("Gabardina Caqui", 1.3)]),
        ("Filipina Quirúrgica", "Hospital Divina Providencia", "Filipina cuello V unisex", "XS, S, M, L, XL",
         [("Antifluido Azul Quirófano", 1.4)]),
        ("Camiseta Oficial Halcones", "Club Deportivo Los Halcones", "Camiseta deportiva sublimada", "YS, YM, S, M, L, XL",
         [("Dri-Fit Marino Deportivo", 1.0)]),
        ("Polo Cajero La Económica", "Supermercados La Económica", "Polo manga corta", "S, M, L, XL",
         [("Piqué Azul Rey", 1.2), ("Poliéster Cuello Blanco", 0.25)]),
    ]
    disenos = {}
    for nombre, cliente, tipo, tallas, telas in disenos_demo:
        d = Diseno.query.filter_by(nombre=nombre).first()
        if d is None:
            d = Diseno(nombre=nombre, cliente=clientes[cliente], tipo_prenda=tipo, tallas=tallas,
                       creado_en=ahora - timedelta(days=40))
            for tela, metros in telas:
                d.telas.append(DisenoTela(tela=insumos[tela], metros_por_unidad=metros))
            db.session.add(d)
        disenos[nombre] = d

    # --- Pedidos con recorrido en el mapa ------------------------------------
    taller = (13.6929, -89.2182)
    lugares = {
        "Colegio San José": ("Colegio San José · Colonia Escalón", 13.7050, -89.2400),
        "Hospital Divina Providencia": ("Hospital Divina Providencia · San Salvador", 13.7045, -89.2235),
        "Alcaldía de Santa Tecla": ("Alcaldía de Santa Tecla · Centro", 13.6769, -89.2797),
        "Club Deportivo Los Halcones": ("Complejo Deportivo · Soyapango", 13.7100, -89.1400),
        "Supermercados La Económica": ("Bodega Central · Antiguo Cuscatlán", 13.6667, -89.2500),
    }
    ruta_intermedia = {
        "Alcaldía de Santa Tecla": ("Carretera Panamericana · Santa Tecla", 13.6790, -89.2650),
        "Club Deportivo Los Halcones": ("Bulevar del Ejército · Soyapango", 13.7020, -89.1700),
        "Supermercados La Económica": ("Bulevar Merliot · Antiguo Cuscatlán", 13.6750, -89.2420),
        "Colegio San José": ("Paseo General Escalón", 13.7010, -89.2330),
        "Hospital Divina Providencia": ("Alameda Juan Pablo II", 13.7030, -89.2200),
    }
    pedidos_demo = [
        # folio, cliente, diseño, prenda, cantidad, estado, días hasta límite, días desde creación, tallas, colores, obs
        ("ORD-DEMO-0101", "Colegio San José", "Camisa Escolar Oxford Celeste", None, 320, "En Costura", 9, 12,
         "6-14", "Celeste", "Bordar escudo del colegio en bolsillo izquierdo."),
        ("ORD-DEMO-0102", "Colegio San José", "Pantalón Escolar Caqui", None, 280, "En Corte", 16, 6,
         "6-14, 28-32", "Caqui", "Ruedo con 4 cm de reserva para ajustes."),
        ("ORD-DEMO-0103", "Hospital Divina Providencia", "Filipina Quirúrgica", None, 150, "Terminado", 3, 18,
         "XS-XL", "Azul quirófano", "Empaque individual con talla visible."),
        ("ORD-DEMO-0104", "Alcaldía de Santa Tecla", None, "Chaleco Reflectivo Institucional", 90, "En Ruta", 1, 25,
         "M, L, XL", "Naranja con franjas plateadas", "Entregar en bodega municipal con acta de recepción."),
        ("ORD-DEMO-0105", "Club Deportivo Los Halcones", "Camiseta Oficial Halcones", None, 60, "Recibido", 21, 1,
         "YS-XL", "Azul marino / blanco", "Sublimar números del 1 al 60 y apellido en la espalda."),
        ("ORD-DEMO-0106", "Supermercados La Económica", "Polo Cajero La Económica", None, 200, "Entregado", -5, 35,
         "S-XL", "Azul rey", None),
        ("ORD-DEMO-0107", "Hospital Divina Providencia", None, "Gabacha Antifluido Verde", 80, "Entregado", -12, 40,
         "S-XL", "Verde emergencias", None),
        ("ORD-DEMO-0108", "Alcaldía de Santa Tecla", None, "Camisa Oxford Institucional", 120, "En Costura", -2, 30,
         "S-XXL", "Blanco", "Logo municipal bordado. Cliente solicitó adelantar entrega."),
        ("ORD-DEMO-0109", "Supermercados La Económica", None, "Gabacha de Bodega", 150, "En Ruta", 4, 14,
         "M, L, XL", "Gris", None),
    ]
    nuevos_pedidos = []
    for folio, cli, dis, prenda, cant, estado, dias_lim, dias_crea, tallas, colores, obs in pedidos_demo:
        if Pedido.query.filter_by(folio=folio).first():
            continue
        cliente = clientes[cli]
        diseno = disenos.get(dis) if dis else None
        p = Pedido(folio=folio, cliente=cliente, diseno=diseno,
                   modelo_prenda=diseno.nombre if diseno else prenda, cantidad=cant, tallas=tallas,
                   colores=colores, observaciones=obs, fecha_limite=hoy + timedelta(days=dias_lim),
                   creado_en=ahora - timedelta(days=dias_crea))
        p.cambiar_estado(estado)
        db.session.add(p)
        nuevos_pedidos.append(p)

        fase_final = p.fase_actual
        destino = lugares[cli]
        intermedio = ruta_intermedia[cli]
        ubicaciones_taller = ["Taller Principal", "Área de Corte · Taller Principal", "Línea de Costura",
                              "Bodega de Empaque"]
        total_horas = dias_crea * 24
        for n in range(1, fase_final + 1):
            nombre_fase = ["Recibido", "En Corte", "En Costura", "Terminado", "En Ruta", "Entregado"][n - 1]
            if n <= 4:
                ubic, lat, lng = ubicaciones_taller[n - 1], *taller
            elif n == 5:
                ubic, lat, lng = intermedio
            else:
                ubic, lat, lng = destino
            horas = total_horas - int(total_horas * (n - 1) / max(fase_final, 1))
            if estado == "Entregado" and n == 6:
                horas = max(int((-dias_lim + 1) * 24), 2)  # entregado antes de la fecha límite
            db.session.add(EventoRastreo(
                pedido=p, estado=nombre_fase, fase=n, ubicacion=ubic, latitud=lat, longitud=lng,
                fecha=ahora - timedelta(hours=max(horas, 1)), usuario=gestor if n > 1 else ventas,
                nota={5: "Pedido en camino al cliente.", 6: "Recibido conforme por el cliente."}.get(n),
            ))
        ultimo = p.eventos[-1] if p.eventos else None
        p.ubicacion_actual = ultimo.ubicacion if ultimo else "Taller Principal"
        p.latitud = ultimo.latitud if ultimo else taller[0]
        p.longitud = ultimo.longitud if ultimo else taller[1]

    # --- Movimientos de inventario de las últimas dos semanas ---------------
    if nuevos_insumos or nuevos_pedidos:
        movimientos = [
            # días atrás, tipo, insumo, cantidad, motivo, folio
            (13, "entrada", "Piqué Azul Rey", 300, "Compra a Textiles del Pacífico", None),
            (12, "salida", "Piqué Azul Rey", 240, "Consumo para pedido ORD-DEMO-0106", "ORD-DEMO-0106"),
            (10, "entrada", "Hilo Poliéster Blanco", 40, "Compra a Hilos y Avíos Centroamérica", None),
            (9, "salida", "Antifluido Azul Quirófano", 210, "Consumo para pedido ORD-DEMO-0103", "ORD-DEMO-0103"),
            (6, "entrada", "Popelina Celeste", 200, "Compra a Textiles del Pacífico", None),
            (6, "salida", "Popelina Celeste", 352, "Consumo para pedido ORD-DEMO-0101", "ORD-DEMO-0101"),
            (5, "salida", "Oxford Blanco Premium", 150, "Consumo para pedido ORD-DEMO-0108", "ORD-DEMO-0108"),
            (4, "entrada", "Gabardina Caqui", 250, "Compra a Textiles del Pacífico", None),
            (3, "salida", "Gabardina Caqui", 180, "Consumo para pedido ORD-DEMO-0102", "ORD-DEMO-0102"),
            (3, "salida", "Hilo Poliéster Verde", 14, "Costura de polos corporativos", None),
            (2, "entrada", "Botón Nácar 4 Hoyos", 1200, "Compra a Hilos y Avíos Centroamérica", None),
            (2, "salida", "Botón Negro Polo", 420, "Consumo para pedido ORD-DEMO-0106", "ORD-DEMO-0106"),
            (1, "entrada", "Cierre Invisible 20 cm", 300, "Compra a Cierres y Accesorios La Unión", None),
            (1, "salida", "Jersey Negro", 55, "Muestras para Club Los Halcones", None),
            (0, "entrada", "Dri-Fit Marino Deportivo", 40, "Compra urgente", None),
            (0, "salida", "Etiqueta Tejida Arte y Color", 320, "Etiquetado de pedido ORD-DEMO-0103", "ORD-DEMO-0103"),
        ]
        for dias, tipo, nombre, cant, motivo, folio in movimientos:
            pedido = Pedido.query.filter_by(folio=folio).first() if folio else None
            db.session.add(Movimiento(
                tipo=tipo, cantidad=cant, metros=cant, motivo=motivo, insumo=insumos[nombre],
                pedido=pedido, usuario=gestor,
                fecha=ahora - timedelta(days=dias, hours=(dias * 3) % 7 + 1),
            ))

    # --- Notas de comunicación ---------------------------------------------
    if not NotaContacto.query.first():
        notas = [
            ("cliente", "Colegio San José", "requerimiento", "El colegio confirma que el escudo va bordado, no estampado. Enviarán el archivo vectorial.", "ORD-DEMO-0101", 11),
            ("cliente", "Colegio San José", "comunicacion", "Llamada: preguntan si se puede adelantar la entrega de pantalones una semana.", "ORD-DEMO-0102", 2),
            ("cliente", "Hospital Divina Providencia", "acuerdo", "Se acuerda empaque individual por talla y entrega en dos lotes.", "ORD-DEMO-0103", 15),
            ("cliente", "Alcaldía de Santa Tecla", "requerimiento", "Requieren ficha técnica impresa firmada para el acta de recepción.", "ORD-DEMO-0104", 20),
            ("cliente", "Alcaldía de Santa Tecla", "comunicacion", "Pedido ORD-DEMO-0108 va con 2 días de retraso; se informó a la Ing. Menjívar.", "ORD-DEMO-0108", 1),
            ("cliente", "Club Deportivo Los Halcones", "comunicacion", "Enviaron lista de nombres y números para sublimar por correo.", "ORD-DEMO-0105", 1),
            ("proveedor", "Textiles del Pacífico", "acuerdo", "Precio acordado: $3.10/m de piqué para compras mayores a 500 m.", None, 30),
            ("proveedor", "Hilos y Avíos Centroamérica", "comunicacion", "Avisan que el hilo verde 348 C llega la próxima semana.", None, 3),
            ("proveedor", "Cierres y Accesorios La Unión", "acuerdo", "Etiquetas tejidas: lote mínimo de 1000 unidades, 10 días de fabricación.", None, 25),
        ]
        for tipo_contacto, nombre, tipo, contenido, folio, dias in notas:
            pedido_nota = Pedido.query.filter_by(folio=folio).first() if folio else None
            nota = NotaContacto(tipo=tipo, contenido=contenido, usuario=ventas, pedido=pedido_nota,
                                fecha=ahora - timedelta(days=dias, hours=2))
            db.session.add(nota)
            if tipo_contacto == "cliente":
                nota.cliente = clientes[nombre]
            else:
                nota.proveedor = proveedores[nombre]

    db.session.flush()
    _demo_gestion()
    db.session.flush()
    _demo_solicitudes()
    db.session.flush()
    _demo_conversaciones()
    db.session.flush()
    _demo_metas()

    db.session.commit()
    click.echo("Datos de demostración cargados.")
    click.echo("  Cuentas: admin123/admin123 · gestor@arteycolor.com/gestor123 · "
               "ventas@arteycolor.com/ventas123 · cliente@banconacional.com/cliente123 · "
               "colegio@sanjose.edu.sv/cliente123")
    for email in ("colegio@sanjose.edu.sv", "cliente@banconacional.com"):
        u = Usuario.query.filter_by(email=email).first()
        if u and u.token_seguimiento:
            digitos = u.telefono_digitos[-4:] if u.telefono_digitos else "----"
            click.echo(f"  Seguimiento → {email}: token {u.token_seguimiento} · últimos 4 dígitos {digitos}")



# ===========================================================================
# Demo de los módulos de gestión: costos, precios, fotos, historial para los
# gráficos, cotizaciones, órdenes de compra, control de calidad y bitácora.
# Solo completa lo que falta, así que se puede ejecutar sobre una base ya cargada.
# ===========================================================================
def _demo_gestion():
    from decimal import Decimal
    from app.models import (Auditoria, Cotizacion, CotizacionLinea, Insumo, Movimiento, Notificacion,
                            OrdenCompra, OrdenCompraLinea, Proveedor, RegistroCalidad)

    ahora = datetime.now()
    hoy = date.today()
    usuario = lambda email: Usuario.query.filter_by(email=email).first()
    admin, gestor, ventas = usuario("admin123"), usuario("gestor@arteycolor.com"), usuario("ventas@arteycolor.com")
    insumo = lambda nombre: Insumo.query.filter_by(nombre=nombre).first()
    cliente = lambda nombre: Cliente.query.filter_by(nombre=nombre).first()
    proveedor = lambda nombre: Proveedor.query.filter_by(nombre=nombre).first()
    pedido = lambda folio: Pedido.query.filter_by(folio=folio).first()

    # --- Costos, proveedor habitual y fotos de los insumos --------------------
    telas_pac, avios, accesorios = (proveedor("Textiles del Pacífico"), proveedor("Hilos y Avíos Centroamérica"),
                                    proveedor("Cierres y Accesorios La Unión"))
    datos_insumos = {
        # nombre: (costo por unidad, proveedor, foto)
        "Algodón Pima Verde Gras": ("4.20", telas_pac, "algodon-pima-verde"),
        "Poliéster Secado Rápido Azul": ("3.40", telas_pac, "poliester-azul"),
        "Oxford Blanco Premium": ("3.80", telas_pac, "oxford-blanco"),
        "Gabardina Roja Institucional": ("3.90", telas_pac, "gabardina-roja"),
        "Dri-Fit Marino Deportivo": ("3.60", telas_pac, "drifit-marino"),
        "Poliéster Cuello Blanco": ("2.80", telas_pac, None),
        "Piqué Azul Rey": ("3.10", telas_pac, "pique-azul-rey"),
        "Gabardina Caqui": ("3.70", telas_pac, "gabardina-caqui"),
        "Popelina Celeste": ("2.60", telas_pac, "popelina-celeste"),
        "Antifluido Azul Quirófano": ("4.50", telas_pac, "antifluido-azul"),
        "Jersey Negro": ("3.20", telas_pac, None),
        "Hilo Poliéster Blanco": ("4.50", avios, "hilo-blanco"),
        "Hilo Poliéster Verde": ("4.50", avios, "hilo-verde"),
        "Hilo Poliéster Azul Marino": ("4.50", avios, "hilo-marino"),
        "Botón Nácar 4 Hoyos": ("0.06", avios, "boton-nacar"),
        "Botón Negro Polo": ("0.05", avios, "boton-negro"),
        "Elástico Plano 2 cm": ("0.40", avios, "elastico-plano"),
        "Cierre Invisible 20 cm": ("0.35", accesorios, "cierre-invisible"),
        "Etiqueta Tejida Arte y Color": ("0.08", accesorios, "etiqueta-tejida"),
    }
    for nombre, (costo, prov, foto) in datos_insumos.items():
        i = insumo(nombre)
        if i is None:
            continue
        if not i.costo_unitario:
            i.costo_unitario = Decimal(costo)
        if i.proveedor_id is None and prov is not None:
            i.proveedor = prov
        if not i.imagen and foto:
            i.imagen = f"img/insumos/{foto}.png"

    # --- Precio, mano de obra, foto y ficha completa de cada diseño ------------
    banco = cliente("Banco Nacional de México")
    if banco and not Diseno.query.filter_by(nombre="Camisa Oxford Ejecutiva").first():
        d = Diseno(nombre="Camisa Oxford Ejecutiva", cliente=banco, tipo_prenda="Camisa manga larga, cuello italiano",
                   tallas="S, M, L, XL, XXL", creado_en=ahora - timedelta(days=50))
        db.session.add(d)
        d.telas.append(DisenoTela(tela=insumo("Oxford Blanco Premium"), metros_por_unidad=1.6))
    datos_disenos = {
        # nombre: (precio, mano de obra, foto, [(insumo extra, cantidad por prenda)])
        "Polo Corporativa Banco Nacional 2025": ("13.50", "3.20", None,
            [("Hilo Poliéster Verde", "0.02"), ("Botón Negro Polo", "3"), ("Etiqueta Tejida Arte y Color", "1")]),
        "Camisa Oxford Ejecutiva": ("15.00", "3.60", "camisa-oxford-ejecutiva",
            [("Botón Nácar 4 Hoyos", "9"), ("Hilo Poliéster Blanco", "0.03"), ("Etiqueta Tejida Arte y Color", "1")]),
        "Camisa Escolar Oxford Celeste": ("11.00", "2.80", "camisa-escolar-celeste",
            [("Botón Nácar 4 Hoyos", "7"), ("Hilo Poliéster Blanco", "0.02"), ("Etiqueta Tejida Arte y Color", "1")]),
        "Pantalón Escolar Caqui": ("12.50", "3.10", "pantalon-escolar-caqui",
            [("Cierre Invisible 20 cm", "1"), ("Botón Nácar 4 Hoyos", "1"), ("Hilo Poliéster Blanco", "0.03"),
             ("Etiqueta Tejida Arte y Color", "1")]),
        "Filipina Quirúrgica": ("10.00", "3.00", "filipina-quirurgica",
            [("Hilo Poliéster Azul Marino", "0.02"), ("Etiqueta Tejida Arte y Color", "1")]),
        "Camiseta Oficial Halcones": ("9.00", "2.50", "camiseta-halcones",
            [("Hilo Poliéster Azul Marino", "0.02"), ("Etiqueta Tejida Arte y Color", "1")]),
        "Polo Cajero La Económica": ("12.00", "3.00", "polo-cajero-la-economica",
            [("Botón Negro Polo", "3"), ("Hilo Poliéster Blanco", "0.02"), ("Etiqueta Tejida Arte y Color", "1")]),
    }
    db.session.flush()
    for nombre, (precio, mano, foto, extras) in datos_disenos.items():
        d = Diseno.query.filter_by(nombre=nombre).first()
        if d is None:
            continue
        if d.precio_venta is None:
            d.precio_venta = Decimal(precio)
        if not d.costo_mano_obra:
            d.costo_mano_obra = Decimal(mano)
        if not d.imagen and foto:
            d.imagen = f"img/disenos/{foto}.png"
        if all(dt.tela and dt.tela.categoria == "Tela" for dt in d.telas):
            presentes = {dt.tela_id for dt in d.telas}
            for nombre_insumo, cantidad in extras:
                i = insumo(nombre_insumo)
                if i and i.id not in presentes:
                    d.telas.append(DisenoTela(tela=i, metros_por_unidad=Decimal(cantidad)))

    oxford_ejecutiva = Diseno.query.filter_by(nombre="Camisa Oxford Ejecutiva").first()
    p = pedido("ORD-DEMO-0002")
    if p and p.diseno_id is None and oxford_ejecutiva:
        p.diseno = oxford_ejecutiva

    # Precios acordados de pedidos sin diseño del catálogo (o con precio especial)
    for folio, precio in [("ORD-DEMO-0104", "9.50"), ("ORD-DEMO-0107", "10.50"), ("ORD-DEMO-0108", "14.00"),
                          ("ORD-DEMO-0109", "8.00"), ("ORD-DEMO-0004", "9.00"), ("ORD-DEMO-0106", "11.50")]:
        p = pedido(folio)
        if p and p.precio_unitario is None:
            p.precio_unitario = Decimal(precio)

    # --- Historial de seis meses (alimenta los gráficos por mes) --------------
    taller = (13.6929, -89.2182)
    historicos = [
        # folio, cliente, diseño, cantidad, días desde creación, días que tardó, días de holgura (negativo = tarde)
        ("ORD-HIST-0001", "Banco Nacional de México", "Polo Corporativa Banco Nacional 2025", 420, 172, 20, 3),
        ("ORD-HIST-0002", "Colegio San José", "Camisa Escolar Oxford Celeste", 380, 160, 24, 2),
        ("ORD-HIST-0003", "Supermercados La Económica", "Polo Cajero La Económica", 160, 141, 18, 4),
        ("ORD-HIST-0004", "Colegio San José", "Pantalón Escolar Caqui", 350, 128, 26, 1),
        ("ORD-HIST-0005", "Hospital Divina Providencia", "Filipina Quirúrgica", 180, 112, 15, 2),
        ("ORD-HIST-0006", "Club Deportivo Los Halcones", "Camiseta Oficial Halcones", 90, 98, 12, 5),
        ("ORD-HIST-0007", "Banco Nacional de México", "Camisa Oxford Ejecutiva", 240, 86, 21, -3),
        ("ORD-HIST-0008", "Supermercados La Económica", "Polo Cajero La Económica", 220, 74, 17, 2),
        ("ORD-HIST-0009", "Colegio San José", "Camisa Escolar Oxford Celeste", 300, 63, 22, -2),
        ("ORD-HIST-0010", "Hospital Divina Providencia", "Filipina Quirúrgica", 140, 52, 16, 1),
        ("ORD-HIST-0011", "Banco Nacional de México", "Polo Corporativa Banco Nacional 2025", 260, 44, 19, 2),
        ("ORD-HIST-0012", "Club Deportivo Los Halcones", "Camiseta Oficial Halcones", 40, 8, 5, 2),
        ("ORD-HIST-0013", "Supermercados La Económica", "Polo Cajero La Económica", 120, 6, 4, 1),
    ]
    for folio, nombre_cliente, nombre_diseno, cantidad, dias, duracion, holgura in historicos:
        if pedido(folio):
            continue
        c, d = cliente(nombre_cliente), Diseno.query.filter_by(nombre=nombre_diseno).first()
        if c is None or d is None:
            continue
        creado = ahora - timedelta(days=dias)
        entregado = creado + timedelta(days=duracion)
        p = Pedido(folio=folio, cliente=c, diseno=d, modelo_prenda=d.nombre, cantidad=cantidad, tallas=d.tallas,
                   creado_en=creado, fecha_limite=(entregado + timedelta(days=holgura)).date(),
                   ubicacion_actual="Entregado al cliente", latitud=taller[0], longitud=taller[1])
        p.cambiar_estado("Entregado")
        db.session.add(p)
        pasos = [("Recibido", 0, ventas), ("En Corte", 0.15, gestor), ("En Costura", 0.35, gestor),
                 ("Terminado", 0.8, gestor), ("En Ruta", 0.95, gestor), ("Entregado", 1, gestor)]
        for n, (estado, avance, quien) in enumerate(pasos, start=1):
            db.session.add(EventoRastreo(pedido=p, estado=estado, fase=n, latitud=taller[0], longitud=taller[1],
                                         ubicacion="Taller Principal" if n < 5 else "Oficinas del cliente",
                                         fecha=creado + (entregado - creado) * avance, usuario=quien))
        # Consumo de material registrado al pasar a corte
        for dt in d.telas:
            db.session.add(Movimiento(tipo="salida", cantidad=Decimal(str(dt.metros_por_unidad)) * cantidad,
                                      metros=Decimal(str(dt.metros_por_unidad)) * cantidad, insumo=dt.tela, pedido=p,
                                      usuario=gestor, motivo=f"Consumo para pedido {folio}",
                                      fecha=creado + timedelta(days=duracion * 0.15)))

    # --- Cotizaciones ----------------------------------------------------------
    def cotizacion(folio, nombre_cliente, estado, dias, lineas, validez=15, descuento="0", respondida=None,
                   entrega=30, notas=None):
        if Cotizacion.query.filter_by(folio=folio).first():
            return None
        c = cliente(nombre_cliente)
        if c is None:
            return None
        cot = Cotizacion(folio=folio, cliente=c, usuario=ventas, estado=estado, fecha=hoy - timedelta(days=dias),
                         validez_dias=validez, descuento_pct=Decimal(descuento), fecha_entrega=hoy + timedelta(days=entrega),
                         creado_en=ahora - timedelta(days=dias, hours=3), notas=notas,
                         condiciones="Anticipo del 50 % para iniciar producción y 50 % contra entrega.\n"
                                     "Precios por prenda incluyen confección, etiquetado y empaque individual.",
                         respondida_en=(ahora - timedelta(days=respondida)) if respondida is not None else None)
        db.session.add(cot)
        for nombre_diseno, cantidad, precio in lineas:
            d = Diseno.query.filter_by(nombre=nombre_diseno).first()
            cot.lineas.append(CotizacionLinea(diseno=d, descripcion=nombre_diseno, tallas=d.tallas if d else None,
                                              cantidad=cantidad, precio_unitario=Decimal(precio)))
        db.session.add(cot)
        return cot

    halcones = cotizacion("COT-DEMO-0001", "Club Deportivo Los Halcones", "aceptada", 3,
                          [("Camiseta Oficial Halcones", 60, "9.00")], respondida=2, entrega=21,
                          notas="Incluye sublimación de número y apellido en la espalda.")
    if halcones and pedido("ORD-DEMO-0105"):
        pedido("ORD-DEMO-0105").cotizacion = halcones
    colegio = cotizacion("COT-DEMO-0002", "Colegio San José", "enviada", 13,
                         [("Camisa Escolar Oxford Celeste", 400, "11.00"), ("Pantalón Escolar Caqui", 350, "12.50")],
                         descuento="5", entrega=45, notas="Uniformes para el ciclo escolar 2027. Escudo bordado.")
    cotizacion("COT-DEMO-0003", "Hospital Divina Providencia", "borrador", 1,
               [("Filipina Quirúrgica", 200, "10.00")], notas="Pedido de reposición para el área de quirófano.")
    cotizacion("COT-DEMO-0004", "Supermercados La Económica", "rechazada", 30,
               [("Polo Cajero La Económica", 150, "13.50")], respondida=24)
    db.session.flush()
    usuario_colegio = usuario("colegio@sanjose.edu.sv")
    if colegio and usuario_colegio:
        db.session.add(Notificacion(usuario=usuario_colegio, tipo="cotizacion", nivel="info",
                                    titulo=f"Nueva cotización {colegio.folio}",
                                    mensaje=f"{colegio.total_prendas:,} prendas · total ${colegio.total:,.2f}. "
                                            "Revísala y respóndenos desde el portal.",
                                    url=f"/cotizaciones/{colegio.id}", clave=f"cot-enviada-{colegio.id}",
                                    creada_en=ahora - timedelta(days=13)))

    # --- Órdenes de compra -----------------------------------------------------
    if not OrdenCompra.query.filter_by(folio="OC-DEMO-0001").first() and telas_pac:
        oc = OrdenCompra(folio="OC-DEMO-0001", proveedor=telas_pac, usuario=gestor, estado="recibida",
                         fecha=ahora - timedelta(days=18), fecha_esperada=hoy - timedelta(days=13),
                         fecha_recepcion=ahora - timedelta(days=13), notas="Compra quincenal de piqué.")
        db.session.add(oc)
        oc.lineas.append(OrdenCompraLinea(insumo=insumo("Piqué Azul Rey"), cantidad=300, costo_unitario=Decimal("3.10")))
        db.session.add(oc)
    if not OrdenCompra.query.filter_by(folio="OC-DEMO-0002").first() and avios:
        oc = OrdenCompra(folio="OC-DEMO-0002", proveedor=avios, usuario=gestor, estado="enviada",
                         fecha=ahora - timedelta(days=8), fecha_esperada=hoy - timedelta(days=2),
                         notas="Urgente: el hilo verde está en nivel crítico.")
        db.session.add(oc)
        oc.lineas.append(OrdenCompraLinea(insumo=insumo("Hilo Poliéster Verde"), cantidad=40, costo_unitario=Decimal("4.50")))
        db.session.add(oc)

    # --- Control de calidad ----------------------------------------------------
    if not RegistroCalidad.query.first():
        registros = [
            # folio, línea, tipo, defecto, prendas, días atrás, resuelto, descripción, acción
            ("ORD-DEMO-0101", "Costura", "defecto", "Costura defectuosa", 48, 3, False,
             "Costura del hombro torcida en tallas 10 y 12.", None),
            ("ORD-DEMO-0101", "Bordado y Estampado", "reproceso", "Bordado o estampado mal ubicado", 6, 4, True,
             "Escudo bordado 1 cm más abajo de lo indicado.", "Se descosió y se volvió a bordar."),
            ("ORD-DEMO-0108", "Costura", "defecto", "Medida incorrecta", 21, 2, False,
             "Mangas 2 cm más cortas en talla XXL.", None),
            ("ORD-DEMO-0103", "Acabados y Empaque", "reproceso", "Mancha o suciedad", 4, 6, True,
             "Manchas de aceite de máquina.", "Lavado y planchado; se limpió la máquina 3."),
            ("ORD-DEMO-0003", "Corte", "defecto", "Tela dañada", 3, 8, True,
             "Rollo con hilos jalados.", "Se reemplazaron las piezas y se reportó al proveedor."),
            ("ORD-DEMO-0003", "Costura", "reproceso", "Botón o cierre defectuoso", 12, 7, True,
             "Botones flojos.", "Se recosieron y se ajustó la botonadora."),
            ("ORD-DEMO-0102", "Corte", "defecto", "Medida incorrecta", 4, 1, False,
             "Piezas del ruedo cortadas 1 cm cortas.", None),
            ("ORD-HIST-0009", "Costura", "defecto", "Costura defectuosa", 15, 50, True,
             "Puntadas saltadas en el cuello.", "Mantenimiento a la máquina 4."),
            ("ORD-HIST-0010", "Acabados y Empaque", "defecto", "Color distinto al aprobado", 5, 40, True,
             "Lote con tono más claro.", "Se separó el lote y se repuso con tela del rollo nuevo."),
        ]
        for folio, linea, tipo, categoria, cantidad, dias, resuelto, desc, accion in registros:
            p = pedido(folio)
            if p is None:
                continue
            db.session.add(RegistroCalidad(
                pedido=p, linea=linea, tipo=tipo, categoria=categoria, cantidad=cantidad, descripcion=desc,
                accion_correctiva=accion, resuelto=resuelto, usuario=gestor,
                fecha=ahora - timedelta(days=dias, hours=2),
                resuelto_en=(ahora - timedelta(days=max(dias - 1, 0))) if resuelto else None))

    # --- Bitácora (algunos movimientos previos a la demo) ------------------------
    if not Auditoria.query.first():
        entradas = [
            (ventas, 3, "crear", "Cotización", "Creó cotización «COT-DEMO-0001»", {"estado": "borrador"}),
            (ventas, 2, "editar", "Cotización", "Editó cotización «COT-DEMO-0001»", {"estado": ["enviada", "aceptada"]}),
            (gestor, 2, "editar", "Pedido", "Editó pedido «ORD-DEMO-0108»", {"estado": ["En Corte", "En Costura"], "fase_tracking": ["2", "3"]}),
            (gestor, 1, "crear", "Movimiento de inventario", "Creó movimiento de inventario «salida de 55 en «Jersey Negro»»",
             {"tipo": "salida", "cantidad": "55", "motivo": "Muestras para Club Los Halcones"}),
            (admin, 1, "editar", "Insumo", "Editó insumo «TEL-0003 · Oxford Blanco Premium»", {"costo_unitario": ["3.60", "3.80"]}),
            (admin, 0, "editar", "Diseño", "Editó diseño «Filipina Quirúrgica»", {"precio_venta": ["9.50", "10"]}),
        ]
        for quien, dias, accion, entidad, descripcion, cambios in entradas:
            if quien is None:
                continue
            import json
            db.session.add(Auditoria(fecha=ahora - timedelta(days=dias, hours=1 + dias), accion=accion, entidad=entidad,
                                     descripcion=descripcion, cambios=json.dumps(cambios, ensure_ascii=False),
                                     usuario_id=quien.id, usuario_nombre=quien.nombre, ip="127.0.0.1"))


# ===========================================================================
# Solicitudes de prendas en todos sus estados: presenta el flujo completo
# propuesta → aprobación → cotización → producción. Idempotente por folio.
# ===========================================================================
def _demo_solicitudes():
    from decimal import Decimal
    from app.models import Solicitud, SolicitudLinea, SolicitudTramo

    if Solicitud.query.filter(Solicitud.folio.like("SOL-DEMO-%")).first():
        return

    ahora, hoy = datetime.now(), date.today()
    usuario = lambda email: Usuario.query.filter_by(email=email).first()
    cliente = lambda nombre: Cliente.query.filter_by(nombre=nombre).first()
    diseno = lambda nombre: Diseno.query.filter_by(nombre=nombre).first()
    ventas, admin = usuario("ventas@arteycolor.com"), usuario("admin123")
    colegio, banco = cliente("Colegio San José"), cliente("Banco Nacional de México")
    u_colegio, u_banco = usuario("colegio@sanjose.edu.sv"), usuario("cliente@banconacional.com")
    if not (colegio and banco and u_colegio and u_banco):
        return

    # Teléfono y token de seguimiento para que /seguimiento sea demostrable
    if not u_colegio.telefono:
        u_colegio.telefono = "+503 2243 1100"
    if not u_banco.telefono:
        u_banco.telefono = "+52 55 5100 2000"
    for u in (u_colegio, u_banco):
        if not u.token_seguimiento:
            u.generar_token()

    def crear(folio, cli, usu, dias, estado, lineas, **kw):
        """lineas = [(descripcion, diseño|None, cantidad, tallas, colores, medidas, [(desde, precio)...])]"""
        s = Solicitud(folio=folio, cliente=cli, usuario=usu, origen="portal",
                      creado_en=ahora - timedelta(days=dias), fecha_deseada=kw.get("fecha_deseada"),
                      notas=kw.get("notas"))
        s.estado = estado
        db.session.add(s)
        for desc, dnom, cant, tallas, colores, medidas, tramos in lineas:
            l = SolicitudLinea(descripcion=desc, diseno=diseno(dnom) if dnom else None, cantidad=cant,
                               tallas=tallas, colores=colores, medidas=medidas)
            for desde, precio in tramos:
                l.tramos.append(SolicitudTramo(desde_cantidad=desde, precio_unitario=Decimal(precio)))
            if tramos:
                l.precio_unitario = l.precio_para(cant)
            s.lineas.append(l)
        return s

    # 1) Pendiente de revisión (la más antigua, aparece arriba en el dashboard)
    crear("SOL-DEMO-0001", colegio, u_colegio, 4, "enviada",
          [("Camisa Escolar Oxford Celeste", "Camisa Escolar Oxford Celeste", 180, "6, 8, 10, 12, 14", "Celeste", "Escudo bordado en el pecho izquierdo.", []),
           ("Pantalón Escolar Caqui", "Pantalón Escolar Caqui", 160, "28, 30, 32", "Caqui", None, [])],
          fecha_deseada=hoy + timedelta(days=35), notas="Uniformes para el ciclo escolar 2027.")

    # 2) Otra pendiente, más reciente
    crear("SOL-DEMO-0002", banco, u_banco, 1, "enviada",
          [("Camisa Oxford Ejecutiva", "Camisa Oxford Ejecutiva", 240, "S, M, L, XL, XXL", "Blanco", "Logo bordado en el puño derecho.", [])],
          fecha_deseada=hoy + timedelta(days=25), notas="Reposición para gerencia regional.")

    # 3) Cotización lista y vigente: el cliente puede aceptarla
    s3 = crear("SOL-DEMO-0003", banco, u_banco, 6, "aprobada",
               [("Polo Corporativa Banco Nacional 2025", "Polo Corporativa Banco Nacional 2025", 300,
                 "S, M, L, XL, XXL", "Verde institucional", "Bordado del logo en el pecho derecho.",
                 [(1, "13.50"), (100, "12.75"), (300, "12.00")])])
    s3.aprobada_en = ahora - timedelta(days=2)
    s3.respondida_en = ahora - timedelta(days=2)
    s3.vence_en = hoy + timedelta(days=13)
    s3.fecha_entrega = hoy + timedelta(days=22)
    s3.atendida_por = ventas
    s3.condiciones = "Pedido mínimo de 50 unidades por talla. Anticipo del 50 % para iniciar producción."
    s3.etiquetas = "Mínimo de pedido, Anticipo requerido"
    s3.respuesta = "Gracias por su propuesta. Precio con rebaja por volumen a partir de 300 unidades."

    # 4) Aceptada y en producción (con su pedido)
    s4 = crear("SOL-DEMO-0004", colegio, u_colegio, 20, "convertida",
               [("Camisa Escolar Oxford Celeste", "Camisa Escolar Oxford Celeste", 500,
                 "6, 8, 10, 12, 14", "Celeste", "Escudo bordado.", [(1, "11.00"), (300, "10.25"), (500, "9.90")])])
    s4.aprobada_en = ahora - timedelta(days=16)
    s4.respondida_en = ahora - timedelta(days=16)
    s4.vence_en = hoy - timedelta(days=1)   # ya se aceptó dentro de su vigencia
    s4.fecha_entrega = hoy + timedelta(days=10)
    s4.atendida_por = ventas
    s4.decidida_en = ahora - timedelta(days=14)
    s4.condiciones = "El celeste se confirma contra muestra física aprobada."
    db.session.flush()
    linea4 = s4.lineas[0]
    taller = (13.6929, -89.2182)
    ped = Pedido(folio="ORD-DEMO-0110", cliente=colegio, diseno=linea4.diseno,
                 modelo_prenda=linea4.descripcion, tallas=linea4.tallas, colores=linea4.colores,
                 cantidad=linea4.cantidad, precio_unitario=linea4.precio_unitario,
                 fecha_limite=hoy + timedelta(days=10), solicitud=s4,
                 ubicacion_actual="Línea de Costura 1", latitud=taller[0], longitud=taller[1],
                 observaciones=f"Cotización {s4.folio} aceptada por el cliente.",
                 creado_en=ahora - timedelta(days=14))
    ped.cambiar_estado("En Costura")
    db.session.add(ped)
    for n, (estado, horas) in enumerate([("Recibido", 14 * 24), ("En Corte", 9 * 24), ("En Costura", 2 * 24)], start=1):
        db.session.add(EventoRastreo(pedido=ped, estado=estado, fase=n, ubicacion="Taller Principal",
                                     latitud=taller[0], longitud=taller[1], usuario=ventas if n == 1 else None,
                                     fecha=ahora - timedelta(hours=horas),
                                     nota=f"Orden creada al aceptar la cotización {s4.folio}." if n == 1 else None))

    # 5) Cotización vencida (Ventas puede renovarla)
    s5 = crear("SOL-DEMO-0005", colegio, u_colegio, 30, "aprobada",
               [("Pantalón Escolar Caqui", "Pantalón Escolar Caqui", 200, "28, 30, 32", "Caqui", None,
                 [(1, "12.50"), (150, "11.75")])])
    s5.aprobada_en = ahora - timedelta(days=25)
    s5.respondida_en = ahora - timedelta(days=25)
    s5.vence_en = hoy - timedelta(days=10)   # vencida
    s5.fecha_entrega = hoy + timedelta(days=5)
    s5.atendida_por = ventas

    # 6) Denegada con motivo
    crear("SOL-DEMO-0006", banco, u_banco, 10, "denegada",
          [("Chaqueta ejecutiva con forro térmico", None, 40, "S, M, L, XL", "Gris Oxford", "Forro interior acolchado.", [])],
          notas="Para el personal de la sucursal de montaña.")
    s6 = Solicitud.query.filter_by(folio="SOL-DEMO-0006").first()
    s6.respondida_en = ahora - timedelta(days=8)
    s6.atendida_por = ventas
    s6.respuesta = ("Por ahora no trabajamos prendas con forro térmico acolchado; requiere maquinaria "
                    "de la que no disponemos. Con gusto cotizamos una chaqueta en gabardina sin forro.")

    # 7) Cotización declinada por el cliente
    s7 = crear("SOL-DEMO-0007", colegio, u_colegio, 18, "declinada",
               [("Camisa Escolar Oxford Celeste", "Camisa Escolar Oxford Celeste", 120, "6, 8, 10", "Celeste", None,
                 [(1, "11.50")])])
    s7.aprobada_en = ahora - timedelta(days=15)
    s7.respondida_en = ahora - timedelta(days=15)
    s7.vence_en = hoy + timedelta(days=0)
    s7.fecha_entrega = hoy + timedelta(days=12)
    s7.atendida_por = ventas
    s7.decidida_en = ahora - timedelta(days=12)
    s7.motivo_cliente = "El presupuesto de este trimestre no alcanza; lo retomamos en enero."

    # Aviso al cliente de la cotización lista (panel de notificaciones del portal)
    from app.models import Notificacion
    if s3 and u_banco and not Notificacion.query.filter_by(clave=f"sol-aprobada-{s3.id}").first():
        db.session.add(Notificacion(usuario=u_banco, tipo="solicitud", nivel="ok",
                                    titulo=f"Tu propuesta {s3.folio} fue aprobada",
                                    mensaje=f"Cotización por ${s3.total:,.2f} + IVA, vigente hasta el {s3.vence_en:%d/%m/%Y}. "
                                            "Acéptala en tu portal para que entre a producción.",
                                    url=f"/solicitudes/{s3.id}", clave=f"sol-aprobada-{s3.id}",
                                    creada_en=ahora - timedelta(days=2)))


def _demo_conversaciones():
    """Dos conversaciones con el asistente de ventas: una reciente y otra guardada por el cliente."""
    from app.models import Conversacion, Mensaje
    if Conversacion.query.filter(Conversacion.asunto.like("%(demo)%")).first():
        return
    ahora = datetime.now()
    u_colegio = Usuario.query.filter_by(email="colegio@sanjose.edu.sv").first()
    u_banco = Usuario.query.filter_by(email="cliente@banconacional.com").first()
    ventas = Usuario.query.filter_by(email="ventas@arteycolor.com").first()
    colegio = Cliente.query.filter_by(nombre="Colegio San José").first()
    banco = Cliente.query.filter_by(nombre="Banco Nacional de México").first()
    if not all((u_colegio, u_banco, ventas, colegio, banco)):
        return
    hilos = [
        (banco, u_banco, "Entrega de las polos corporativas (demo)", False, [
            (True, 26, "Buenas tardes. ¿Podemos recibir las polos en la sucursal centro en lugar de las oficinas centrales?"),
            (False, 25, "¡Hola, Carlos! Sí, sin problema. Lo dejo anotado en ORD-DEMO-0003 para que el repartidor vaya a la sucursal centro."),
            (True, 2, "Perfecto, muchas gracias. ¿A qué hora suelen llegar?"),
        ]),
        (colegio, u_colegio, "Tallas del uniforme 2027 (demo)", True, [
            (True, 72, "Les compartimos el conteo de tallas por grado para la propuesta SOL-DEMO-0001: 6 (30), 8 (45), 10 (50), 12 (35), 14 (20)."),
            (False, 70, "Recibido, Marta. Con ese conteo armamos la cotización. Guarden esta conversación por si necesitan el detalle más adelante."),
        ]),
    ]
    for cli, usu, asunto, guardada, mensajes in hilos:
        c = Conversacion(asunto=asunto, cliente=cli, creada_por=usu, guardada=guardada,
                         creada_en=ahora - timedelta(hours=mensajes[0][1]),
                         ultima_actividad=ahora - timedelta(hours=mensajes[-1][1]))
        db.session.add(c)
        for de_cliente, horas, texto in mensajes:
            c.mensajes.append(Mensaje(autor=usu if de_cliente else ventas, de_cliente=de_cliente, texto=texto,
                                      creado_en=ahora - timedelta(hours=horas), leido=horas > 3))


# ---------------------------------------------------------------------------
# Comandos para el servidor en línea
# ---------------------------------------------------------------------------
CUENTAS_DEMO = ("admin123", "gestor@arteycolor.com", "ventas@arteycolor.com",
                "cliente@banconacional.com", "colegio@sanjose.edu.sv", "nuevo.gestor@arteycolor.com")


def _demo_metas():
    """Metas de ejemplo para el taller y ventas, con el mes anterior ya cerrado y pagado."""
    from app.metas.indicadores import cerrar_mes, mes_actual, mover_mes
    from app.models import Meta, PagoIncentivo
    if Meta.query.filter(Meta.nombre.like("%(demo)%")).first():
        return
    admin = Usuario.query.filter_by(rol="admin").order_by(Usuario.id).first()
    ventas = Usuario.query.filter_by(email="ventas@arteycolor.com").first()
    metas = [
        Meta(nombre="Producción del mes (demo)", indicador="prendas_terminadas", rol="gestor", objetivo=600,
             incentivo=40, umbral_parcial=80, descripcion="Prendas que pasas a «Terminado» en el tablero."),
        Meta(nombre="Entregas puntuales (demo)", indicador="entregas_a_tiempo", rol="gestor", objetivo=90,
             incentivo=25, descripcion="Que al menos 9 de cada 10 entregas lleguen a tiempo."),
        Meta(nombre="Calidad del taller (demo)", indicador="defectos_taller", rol="gestor", objetivo=3,
             incentivo=20, descripcion="Meta de equipo: máximo 3 % de prendas con defecto."),
        Meta(nombre="Ventas cerradas (demo)", indicador="monto_vendido", rol="ventas", objetivo=4000,
             incentivo=60, umbral_parcial=75),
        Meta(nombre="Respuesta en menos de un día (demo)", indicador="respuesta_horas", rol="ventas", objetivo=24,
             incentivo=20, descripcion="Responde las solicitudes de clientes en menos de 24 horas en promedio."),
    ]
    if ventas:
        metas.append(Meta(nombre="Solicitudes atendidas (demo)", indicador="solicitudes_respondidas",
                          usuario_id=ventas.id, objetivo=5, incentivo=15))
    for m in metas:
        m.creada_por = admin
        db.session.add(m)
    db.session.flush()
    anio, mes = mover_mes(*mes_actual(), -1)
    cerrar_mes(anio, mes)
    db.session.flush()
    for pago in PagoIncentivo.query.filter_by(anio=anio, mes=mes):
        pago.estado, pago.pagado_en = "pagado", datetime.now()


def _clave_aleatoria():
    import secrets
    import string
    # Sin caracteres que se confunden (0/O, 1/l/I) para poder dictarla o copiarla a mano
    alfabeto = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    while True:
        clave = "".join(secrets.choice(alfabeto) for _ in range(14))
        if any(c.isdigit() for c in clave) and any(c.isalpha() for c in clave):
            return clave


@click.command("crear-admin")
@click.option("--email", prompt="Correo del administrador")
@click.option("--nombre", prompt="Nombre completo")
@click.password_option("--password", prompt="Contraseña", help="Mínimo 8 caracteres con letras y números.")
@with_appcontext
def crear_admin(email, nombre, password):
    """Crea (o actualiza) una cuenta de Administrador con la contraseña indicada."""
    from app.forms import clave_robusta
    email = email.strip().lower()
    error = clave_robusta(password, email) or (None if len(password) >= 8 else "Usa al menos 8 caracteres.")
    if error:
        raise click.ClickException(error)
    usuario = Usuario.query.filter(db.func.lower(Usuario.email) == email).first()
    if usuario is None:
        usuario = Usuario(email=email, nombre=nombre.strip(), rol="admin", cargo="Administración")
        db.session.add(usuario)
    usuario.nombre = nombre.strip() or usuario.nombre
    usuario.rol, usuario.estado_permiso, usuario.activo = "admin", "aprobado", True
    usuario.set_password(password)
    db.session.commit()
    click.echo(f"Administrador listo: {email}")


@click.command("claves-demo")
@click.option("--desactivar", is_flag=True, help="Desactiva las cuentas de demostración en lugar de cambiar su clave.")
@with_appcontext
def claves_demo(desactivar):
    """Cambia las contraseñas conocidas de las cuentas de demostración por claves aleatorias.
    Úsalo siempre que la base con datos de demo quede publicada en internet."""
    cuentas = Usuario.query.filter(Usuario.email.in_(CUENTAS_DEMO)).order_by(Usuario.rol).all()
    if not cuentas:
        click.echo("No hay cuentas de demostración en esta base.")
        return
    click.echo("Guarda estas credenciales en un lugar seguro (no se vuelven a mostrar):\n")
    for u in cuentas:
        if desactivar:
            u.activo = False
            click.echo(f"  {u.email:<32} desactivada")
        else:
            clave = _clave_aleatoria()
            u.set_password(clave)
            click.echo(f"  {u.email:<32} {clave:<16} ({u.rol_legible})")
    db.session.commit()


@click.command("purgar-bitacora")
@click.option("--dias", type=int, default=None, help="Días a conservar (por defecto AUDITORIA_RETENCION_DIAS = 90).")
@with_appcontext
def purgar_bitacora_cmd(dias):
    """Respalda en CSV y borra los registros de auditoría más antiguos que la retención.
    Prográmalo como tarea diaria en PythonAnywhere (pestaña Tasks)."""
    from app.auditoria import purgar_bitacora
    borrados, nombre = purgar_bitacora(dias)
    if borrados:
        click.echo(f"{borrados} registros respaldados en instance/respaldos/{nombre} y eliminados.")
    else:
        click.echo("Nada que depurar.")


@click.command("purgar-mensajes")
@click.option("--dias", type=int, default=None, help="Días sin actividad (por defecto MENSAJES_RETENCION_DIAS = 30).")
@with_appcontext
def purgar_mensajes_cmd(dias):
    """Borra las conversaciones asistente–cliente no guardadas y sin actividad.
    También se ejecuta sola al abrir la bandeja de mensajes; este comando sirve para programarlo."""
    from app.mensajes.servicios import purgar_conversaciones
    borradas = purgar_conversaciones(dias)
    click.echo(f"{borradas} conversación(es) eliminada(s)." if borradas else "Nada que depurar.")
