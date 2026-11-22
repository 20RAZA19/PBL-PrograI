"""Metas e incentivos: el avance se calcula con los datos del sistema y el mes se cierra para pagar."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.metas.indicadores import cerrar_mes, evaluar, mes_actual, mover_mes, rango_mes
from app.models import Cliente, EventoRastreo, Meta, PagoIncentivo, Pedido, Solicitud, Usuario
from tests.conftest import CLAVE


def _usuario(email):
    return Usuario.query.filter_by(email=email).one()


def _terminar(pedido_folio, usuario, fecha=None):
    pedido = Pedido.query.filter_by(folio=pedido_folio).one()
    db.session.add(EventoRastreo(pedido=pedido, estado="Terminado", fase=4, usuario=usuario,
                                 fecha=fecha or datetime.now()))
    db.session.commit()
    return pedido


def _meta(**datos):
    base = dict(nombre="Producción", indicador="prendas_terminadas", rol="gestor", objetivo=100, incentivo=50)
    base.update(datos)
    meta = Meta(**base)
    db.session.add(meta)
    db.session.commit()
    return meta


# --- Cálculo ------------------------------------------------------------------------
def test_prendas_terminadas_cumple_y_paga_completo(app, ctx):
    gestor = _usuario("gestor@test.com")
    _terminar("ORD-T-001", gestor)                         # 100 camisas
    ev = evaluar(_meta(), gestor, *mes_actual())
    assert ev["valor"] == Decimal("100") and ev["cumplida"] and ev["ganado"] == Decimal("50")


def test_pago_parcial_desde_el_umbral(app, ctx):
    gestor = _usuario("gestor@test.com")
    _terminar("ORD-T-001", gestor)
    ev = evaluar(_meta(objetivo=125, umbral_parcial=80), gestor, *mes_actual())   # 100 de 125 = 80 %
    assert not ev["cumplida"] and ev["parcial"] and ev["avance"] == 80 and ev["ganado"] == Decimal("25.00")


def test_solo_cuenta_lo_que_hizo_esa_persona_en_ese_mes(app, ctx):
    gestor, admin = _usuario("gestor@test.com"), _usuario("admin@test.com")
    _terminar("ORD-T-001", admin)                                       # lo hizo otra persona
    pasado = rango_mes(*mover_mes(*mes_actual(), -1))[0] + timedelta(days=3)
    _terminar("ORD-T-001", gestor, fecha=pasado)                         # lo hizo el mes anterior
    ev = evaluar(_meta(), gestor, *mes_actual())
    assert ev["valor"] == 0 and ev["ganado"] == 0


def test_tiempo_de_respuesta_menos_es_mejor(app, ctx):
    ventas = _usuario("ventas@test.com")
    cliente = Cliente.query.first()
    ahora = datetime.now()
    db.session.add(Solicitud(folio="SOL-T-9", cliente=cliente, estado="aprobada", atendida_por=ventas,
                             creado_en=ahora - timedelta(hours=10), respondida_en=ahora))
    db.session.commit()
    meta = _meta(nombre="Responder rápido", indicador="respuesta_horas", rol="ventas", objetivo=24, incentivo=30)
    ev = evaluar(meta, ventas, *mes_actual())
    assert ev["valor"] == Decimal("10.0") and ev["cumplida"] and ev["ganado"] == Decimal("30")
    meta.objetivo = 5
    ev = evaluar(meta, ventas, *mes_actual())
    assert not ev["cumplida"] and ev["avance"] == 50                   # 5 de 10 horas


def test_sin_datos_no_paga(app, ctx):
    ventas = _usuario("ventas@test.com")
    meta = _meta(nombre="Responder rápido", indicador="respuesta_horas", rol="ventas", objetivo=24, incentivo=30)
    ev = evaluar(meta, ventas, *mes_actual())
    assert ev["sin_datos"] and ev["ganado"] == 0


# --- Pantallas ----------------------------------------------------------------------
def test_trabajador_ve_su_avance(app, entrar, ctx):
    _terminar("ORD-T-001", _usuario("gestor@test.com"))
    _meta()
    html = entrar("gestor").get("/metas/").get_data(as_text=True)
    assert "Producción" in html and "Cumplida" in html and "$50.00" in html


def test_meta_personal_solo_la_ve_esa_persona(app, entrar, ctx):
    otro = Usuario(email="gestor2@test.com", rol="gestor", nombre="Gabriel Taller", estado_permiso="aprobado")
    otro.set_password(CLAVE)
    db.session.add(otro)
    db.session.commit()
    _meta(nombre="Meta solo de Gabriel", rol=None, usuario_id=otro.id)
    assert "Meta solo de Gabriel" not in entrar("gestor").get("/metas/").get_data(as_text=True)


def test_permisos(entrar):
    assert entrar("cliente").get("/metas/").status_code == 403
    assert entrar("gestor").get("/metas/equipo").status_code == 403
    assert entrar("ventas").post("/metas/nueva", data={}).status_code == 403
    assert entrar("admin").get("/metas/equipo").status_code == 200


def test_admin_crea_meta_desde_el_formulario(app, entrar, ctx):
    r = entrar("admin").post("/metas/nueva", data={
        "nombre": "Ventas del mes", "indicador": "monto_vendido", "destino": "rol:ventas",
        "objetivo": "5000", "incentivo": "75", "umbral_parcial": "80", "activa": "y",
        "fecha_inicio": date.today().replace(day=1).isoformat(), "fecha_fin": date.today().isoformat()})
    assert r.status_code == 302
    meta = Meta.query.filter_by(nombre="Ventas del mes").one()
    assert meta.rol == "ventas" and meta.usuario_id is None and meta.umbral_parcial == 80
    assert "Ventas del mes" in entrar("ventas").get("/metas/").get_data(as_text=True)


# --- Cierre del mes y pago ------------------------------------------------------------
def test_no_se_cierra_el_mes_en_curso(app, entrar, ctx):
    _meta()
    anio, mes = mes_actual()
    entrar("admin").post(f"/metas/cerrar?mes={anio}-{mes:02d}")
    assert PagoIncentivo.query.count() == 0


def test_cerrar_pagar_y_el_monto_queda_fijo(app, entrar, ctx):
    gestor = _usuario("gestor@test.com")
    anio, mes = mover_mes(*mes_actual(), -1)
    _terminar("ORD-T-001", gestor, fecha=rango_mes(anio, mes)[0] + timedelta(days=5))
    meta = _meta()
    admin = entrar("admin")
    clave = f"{anio}-{mes:02d}"
    admin.post(f"/metas/cerrar?mes={clave}")
    pago = PagoIncentivo.query.filter_by(usuario_id=gestor.id).one()
    assert pago.monto == Decimal("50") and pago.estado == "pendiente" and pago.avance == 100

    meta.incentivo = 999                                         # editar después no cambia el mes cerrado
    db.session.commit()
    html = entrar("gestor").get(f"/metas/?mes={clave}").get_data(as_text=True)
    assert "$50.00" in html and "Por pagar" in html

    admin.post(f"/metas/pagar/{gestor.id}?mes={clave}")
    db.session.refresh(pago)
    assert pago.estado == "pagado" and pago.pagado_en is not None
    admin.post(f"/metas/cerrar?mes={clave}")                     # recalcular no toca lo pagado
    db.session.refresh(pago)
    assert pago.monto == Decimal("50")

    csv = admin.get(f"/metas/equipo.csv?mes={clave}").get_data(as_text=True)
    assert "Producción" in csv and "Pagado" in csv and gestor.nombre in csv


def test_mes_futuro_o_invalido_vuelve_al_actual(entrar):
    html = entrar("gestor").get("/metas/?mes=2999-01").get_data(as_text=True)
    anio, mes = mes_actual()
    from app.metas.indicadores import nombre_mes
    assert nombre_mes(anio, mes).capitalize() in html


# --- Área y periodo de la meta ----------------------------------------------------------
def _entregar(pedido_folio, usuario, fecha):
    pedido = Pedido.query.filter_by(folio=pedido_folio).one()
    db.session.add(EventoRastreo(pedido=pedido, estado="Entregado", fase=6, usuario=usuario, fecha=fecha))
    db.session.commit()
    return pedido


def test_solo_cuentan_entregas_dentro_del_periodo(app, ctx):
    gestor = _usuario("gestor@test.com")
    hoy = date.today()
    inicio, fin = hoy - timedelta(days=10), hoy - timedelta(days=2)
    pedido = _entregar("ORD-T-001", gestor, datetime.combine(inicio, datetime.min.time()) + timedelta(hours=9))
    meta = _meta(indicador="prendas_entregadas", fecha_inicio=inicio, fecha_fin=fin)
    ev = evaluar(meta, gestor, *mes_actual())
    assert ev["valor"] == Decimal(pedido.cantidad)

    # Una entrega antes del periodo o después de su fin no cuenta.
    meta.fecha_inicio = inicio + timedelta(days=1)
    db.session.commit()
    assert evaluar(meta, gestor, *mes_actual())["valor"] == 0
    meta.fecha_inicio, meta.fecha_fin = inicio - timedelta(days=5), inicio - timedelta(days=1)
    db.session.commit()
    assert evaluar(meta, gestor, *mes_actual())["valor"] == 0


def test_la_meta_con_periodo_se_paga_en_el_mes_que_termina(app, ctx):
    gestor = _usuario("gestor@test.com")
    anio, mes = mover_mes(*mes_actual(), -1)
    inicio_mes = rango_mes(anio, mes)[0].date()
    meta = _meta(fecha_inicio=inicio_mes + timedelta(days=10), fecha_fin=date.today())
    _terminar("ORD-T-001", gestor, fecha=datetime.combine(inicio_mes, datetime.min.time()) + timedelta(days=12))
    ev_pasado = evaluar(meta, gestor, anio, mes)
    assert ev_pasado["cumplida"] and not ev_pasado["liquida_aqui"]
    cerrar_mes(anio, mes)                                # el mes anterior no la paga
    assert PagoIncentivo.query.count() == 0
    assert evaluar(meta, gestor, *mes_actual())["liquida_aqui"]


def test_meta_fuera_de_su_periodo_no_se_muestra(app, entrar, ctx):
    _meta(nombre="Meta vieja", fecha_inicio=date(2020, 1, 1), fecha_fin=date(2020, 1, 31))
    assert "Meta vieja" not in entrar("gestor").get("/metas/").get_data(as_text=True)


def test_para_quien_debe_ser_del_area_que_se_mide(app, entrar, ctx):
    ventas = _usuario("ventas@test.com")
    hoy = date.today().isoformat()
    datos = {"nombre": "Producción cruzada", "indicador": "prendas_entregadas", "objetivo": "10",
             "incentivo": "5", "activa": "y", "fecha_inicio": hoy, "fecha_fin": hoy}
    r = entrar("admin").post("/metas/nueva", data={**datos, "destino": f"u:{ventas.id}"})
    assert r.status_code == 200 and "área de taller" in r.get_data(as_text=True)
    r = entrar("admin").post("/metas/nueva", data={**datos, "destino": "rol:ventas"})
    assert r.status_code == 200
    assert entrar("admin").post("/metas/nueva", data={**datos, "destino": "rol:gestor"}).status_code == 302


def test_fecha_fin_no_puede_ser_antes_del_inicio(app, entrar, ctx):
    r = entrar("admin").post("/metas/nueva", data={
        "nombre": "Al revés", "indicador": "prendas_entregadas", "destino": "rol:gestor", "objetivo": "10",
        "incentivo": "5", "fecha_inicio": "2026-11-20", "fecha_fin": "2026-11-01"})
    assert r.status_code == 200 and "antes del inicio" in r.get_data(as_text=True)
