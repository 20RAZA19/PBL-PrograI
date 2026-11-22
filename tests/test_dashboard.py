"""Centro de atención, indicadores con semáforo y datos de los gráficos del dashboard."""
import json
import re

from app.extensions import db
from app.indicadores import graficos, kpis, recomendaciones
from app.models import Pedido, Usuario


def _titulos(app, ids, rol):
    with app.test_request_context():
        return [r["titulo"] for r in recomendaciones(db.session.get(Usuario, ids.usuarios[rol]))]


def test_recomendaciones_del_administrador(app, ids):
    titulos = _titulos(app, ids, "admin")
    assert any("Falta material" in t for t in titulos)
    assert any("riesgo de atraso" in t for t in titulos)
    assert any("nivel crítico" in t for t in titulos)
    assert any("solicitud" in t for t in titulos)


def test_recomendaciones_ordenadas_por_urgencia(app, ids):
    with app.test_request_context():
        recs = recomendaciones(db.session.get(Usuario, ids.usuarios["admin"]))
        orden = {"critico": 0, "alerta": 1, "sugerencia": 2}
        niveles = [orden[r["nivel"]] for r in recs]
        assert niveles == sorted(niveles)


def test_cada_rol_ve_solo_lo_suyo(app, ids):
    ventas = _titulos(app, ids, "ventas")
    assert not any("Falta material" in t for t in ventas)
    assert not any("solicitud" in t for t in ventas)
    gestor = _titulos(app, ids, "gestor")
    assert any("Falta material" in t for t in gestor)
    assert not any("margen" in t.lower() for t in gestor)


def test_margen_bajo_genera_alerta(app, ids):
    with app.app_context():
        db.session.get(Pedido, ids.activo).precio_unitario = 6  # pierde dinero
        db.session.commit()
    titulos = _titulos(app, ids, "ventas")
    assert any("margen menor al 15%" in t for t in titulos)


def test_pedido_vencido_es_critico(app, ids):
    from datetime import date, timedelta
    with app.app_context():
        db.session.get(Pedido, ids.activo).fecha_limite = date.today() - timedelta(days=3)
        db.session.commit()
    with app.test_request_context():
        recs = recomendaciones(db.session.get(Usuario, ids.usuarios["gestor"]))
        assert recs[0]["nivel"] == "critico" and "vencido" in recs[0]["titulo"]


def test_indicadores_con_semaforo(app, ids):
    with app.test_request_context():
        admin = kpis(db.session.get(Usuario, ids.usuarios["admin"]))
        gestor = kpis(db.session.get(Usuario, ids.usuarios["gestor"]))
    titulos = [k["titulo"] for k in admin]
    assert "Margen de ganancia" in titulos and "Cotizaciones ganadas" in titulos
    assert "Margen de ganancia" not in [k["titulo"] for k in gestor]
    for k in admin:
        assert k["nivel"] in ("ok", "warn", "danger", "neutral")
    entregas = next(k for k in admin if k["titulo"] == "Entregas a tiempo")
    # ORD-T-002 se entregó hace 2 días y vencía ayer: a tiempo
    assert entregas["valor"] == "100%" and entregas["nivel"] == "ok"


def test_entrega_tardia_baja_la_puntualidad(app, ids):
    from datetime import date, timedelta
    with app.app_context():
        db.session.get(Pedido, ids.entregado).fecha_limite = date.today() - timedelta(days=5)
        db.session.commit()
    with app.test_request_context():
        entregas = kpis(db.session.get(Usuario, ids.usuarios["gestor"]))[0]
    assert entregas["valor"] == "0%" and entregas["nivel"] == "danger"


def test_datos_de_graficos(app, ids):
    with app.test_request_context():
        datos = graficos(db.session.get(Usuario, ids.usuarios["admin"]))
        sin_finanzas = graficos(db.session.get(Usuario, ids.usuarios["gestor"]))
    assert len(datos["etiquetas"]) == 6
    assert datos["pedidos"]["recibidos"][-1] == 2  # los dos pedidos de prueba son de este mes
    assert datos["pedidos"]["prendas"][-1] == 150
    assert datos["pedidos"]["entregados"][-1] == 1
    assert datos["finanzas"]["ingresos"][-1] == 1400.0
    assert "finanzas" not in sin_finanzas


def test_dashboard_muestra_para_hoy_y_centro_de_atencion(app, ids, entrar):
    for rol in ("admin", "gestor", "ventas"):
        html = entrar(rol).get("/dashboard").get_data(as_text=True)
        assert "Centro de Atención" in html and 'class="hoy"' in html
        assert len(re.findall(r'<a class="hoy-tarjeta ', html)) == 4
        assert "Próximas entregas" in html
        # Ya no se cargan la tabla completa de materia prima ni los gráficos de tendencia
        assert "Materia Prima Registrada" not in html and 'id="grafico-pedidos"' not in html
    # Lo accionable arriba: «Para hoy» y las listas antes del Centro de Atención
    html = entrar("admin").get("/dashboard").get_data(as_text=True)
    assert html.index('class="hoy"') < html.index("Aprobaciones pendientes") < html.index("Centro de Atención")
    # Ventas no ve inventario; el gestor no ve aprobaciones
    assert "Insumos por reponer" not in entrar("ventas").get("/dashboard").get_data(as_text=True)
    gestor = entrar("gestor").get("/dashboard").get_data(as_text=True)
    assert "Insumos por reponer" in gestor and 'id="solicitudes-nuevas"' not in gestor


def test_listas_del_dashboard_tienen_maximo_seis_filas(app, ids, ctx, entrar):
    from datetime import date, timedelta
    from app.models import Cliente, Pedido
    cliente = Cliente.query.first()
    for n in range(10):
        db.session.add(Pedido(folio=f"ORD-LIM-{n:03d}", modelo_prenda="Camisa", cantidad=10, estado="Recibido",
                              fecha_limite=date.today() + timedelta(days=n + 1), cliente=cliente))
    db.session.commit()
    html = entrar("admin").get("/dashboard").get_data(as_text=True)
    filas = re.findall(r'href="/rastreo/ORD-[^"]+"', html)
    assert len(filas) <= 6
    assert "en el tablero" in html                     # enlace para ver el resto


def test_graficos_de_tendencia_estan_en_reportes(app, ids, entrar):
    html = entrar("admin").get("/reportes/").get_data(as_text=True)
    assert 'id="grafico-pedidos"' in html and 'id="grafico-finanzas"' in html
    datos = json.loads(re.search(r'id="datos-graficos">(.*?)</script>', html, re.S).group(1))
    assert len(datos["etiquetas"]) == 30                # 30 días por defecto, un punto por día
    anual = entrar("admin").get("/reportes/?dias=365").get_data(as_text=True)
    datos = json.loads(re.search(r'id="datos-graficos">(.*?)</script>', anual, re.S).group(1))
    assert len(datos["etiquetas"]) == 12


def test_portal_del_cliente_no_muestra_indicadores_internos(app, ids, entrar):
    html = entrar("cliente").get("/dashboard").get_data(as_text=True)
    assert "Centro de Atención" not in html and "Margen" not in html


# --- Reportes: el periodo cambia los datos ---------------------------------------------
def test_reportes_cambian_con_el_periodo(app, entrar, ctx):
    from datetime import datetime, timedelta
    from app.extensions import db
    from app.models import Pedido
    viejo = Pedido.query.first()
    viejo.creado_en = datetime.now() - timedelta(days=60)
    for p in Pedido.query.filter(Pedido.id != viejo.id):
        p.creado_en = datetime.now() - timedelta(days=200)
    db.session.commit()
    admin = entrar("admin")
    html7 = admin.get("/reportes/?dias=7").get_data(as_text=True)
    html90 = admin.get("/reportes/?dias=90").get_data(as_text=True)
    assert 'Pedidos recibidos' in html7
    import re
    def recibidos(h):
        return int(re.search(r'Pedidos recibidos <span.*?kpi__valor">(\d+)', h, re.S).group(1))
    assert recibidos(html7) == 0 and recibidos(html90) == 1
    assert "por día" in html7 and "por semana" in html90
    assert '"etiquetas"' in html90


def test_reportes_periodo_invalido_usa_30_dias(entrar):
    assert "últimos 30 días" in entrar("admin").get("/reportes/?dias=999").get_data(as_text=True)


# --- Gráficos en las secciones (fase 11) -----------------------------------------------
def _datos_grafico(html, id_):
    return json.loads(re.search(rf'id="{id_}-datos">(.*?)</script>', html, re.S).group(1))


def test_portal_del_cliente_tiene_graficos(app, ids, entrar):
    html = entrar("cliente").get("/dashboard").get_data(as_text=True)
    fases = _datos_grafico(html, "grafico-fases")
    assert "Entregado" not in fases["etiquetas"] and len(fases["etiquetas"]) == 5
    assert "Entregas a tiempo" in html


def test_detalle_de_insumo_muestra_existencia(app, ids, entrar):
    html = entrar("gestor").get(f"/telas/{ids.popelina}").get_data(as_text=True)
    datos = _datos_grafico(html, "grafico-stock")
    assert len(datos["etiquetas"]) == 60 and datos["series"][1]["nombre"] == "Stock mínimo"


def test_graficos_de_bitacora_metas_y_solicitudes(app, ids, entrar):
    admin = entrar("admin")
    assert 'data-grafico="grafico-bitacora-datos"' in admin.get("/admin/bitacora").get_data(as_text=True)
    assert 'data-grafico="grafico-solicitudes-datos"' in admin.get("/solicitudes/").get_data(as_text=True)
    assert "grafico-solicitudes-datos" not in entrar("cliente").get("/solicitudes/").get_data(as_text=True)
