"""Retención de la bitácora: lo antiguo se respalda en CSV y se borra."""
import csv
import gzip
import io
import os
from datetime import datetime, timedelta

import pytest

from app.auditoria import listar_respaldos, purgar_bitacora, ruta_respaldo
from app.extensions import db
from app.models import Auditoria


@pytest.fixture
def con_historial(app, ctx, tmp_path):
    app.instance_path = str(tmp_path / "instance")
    Auditoria.query.delete()
    ahora = datetime.now()
    for dias, texto in [(200, "muy viejo"), (91, "=FORMULA() viejo"), (89, "reciente"), (1, "de ayer")]:
        db.session.add(Auditoria(fecha=ahora - timedelta(days=dias), accion="editar", entidad="Pedido",
                                 descripcion=texto, usuario_nombre="Ana", cambios='{"cantidad": ["1", "2"]}'))
    db.session.commit()
    return app


def _leer(nombre):
    with gzip.open(ruta_respaldo(nombre), "rt", encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def test_purga_respalda_y_borra_solo_lo_antiguo(con_historial):
    borrados, nombre = purgar_bitacora()
    assert borrados == 2
    filas = _leer(nombre)
    assert filas[0][0] == "Fecha" and len(filas) == 3
    assert [f[5] for f in filas[1:]] == ["muy viejo", "'=FORMULA() viejo"]      # orden cronológico, sin fórmulas
    assert "cantidad: 1 → 2" in filas[1][6]
    restantes = {r.descripcion for r in Auditoria.query.filter_by(entidad="Pedido")}
    assert restantes == {"reciente", "de ayer"}
    # La propia depuración queda registrada
    assert Auditoria.query.filter(Auditoria.descripcion.like("Depuración de bitácora: 2 registros%")).count() == 1


def test_purga_sin_antiguos_no_crea_archivo(con_historial):
    purgar_bitacora()
    assert purgar_bitacora() == (0, None)
    assert len(listar_respaldos()) == 1


def test_retencion_configurable(con_historial):
    borrados, _ = purgar_bitacora(dias=30)
    assert borrados == 3


def test_comando_cli(con_historial):
    salida = con_historial.test_cli_runner().invoke(args=["purgar-bitacora"]).output
    assert "2 registros respaldados" in salida
    assert "Nada que depurar" in con_historial.test_cli_runner().invoke(args=["purgar-bitacora"]).output


def test_admin_depura_descarga_y_elimina(con_historial, entrar):
    admin = entrar("admin")
    html = admin.get("/admin/bitacora").get_data(as_text=True)
    assert "Respaldar y depurar" in html and "listos para depurar" in html
    assert admin.post("/admin/bitacora/depurar").status_code == 302
    nombre = listar_respaldos()[0]["nombre"]
    r = admin.get(f"/admin/bitacora/respaldos/{nombre}")
    assert r.status_code == 200
    contenido = gzip.decompress(r.data).decode("utf-8-sig")
    assert "muy viejo" in contenido
    assert admin.post(f"/admin/bitacora/respaldos/{nombre}/eliminar").status_code == 302
    assert listar_respaldos() == []
    assert admin.get(f"/admin/bitacora/respaldos/{nombre}").status_code == 404


@pytest.mark.parametrize("nombre", ["..%2F..%2Fconfig.py", "inventario.db", "bitacora_x.csv", "secret_key"])
def test_descarga_no_permite_otros_archivos(con_historial, entrar, nombre):
    os.makedirs(con_historial.instance_path, exist_ok=True)
    with open(os.path.join(con_historial.instance_path, "secret_key"), "w") as f:
        f.write("secreto")
    assert entrar("admin").get(f"/admin/bitacora/respaldos/{nombre}").status_code == 404
    assert ruta_respaldo("../secret_key") is None


@pytest.mark.parametrize("rol", ["gestor", "ventas", "cliente"])
def test_solo_el_admin_depura(con_historial, entrar, rol):
    c = entrar(rol)
    assert c.post("/admin/bitacora/depurar").status_code == 403
    assert c.get("/admin/bitacora/respaldos/bitacora_x.csv.gz").status_code == 403
    assert Auditoria.query.filter_by(descripcion="muy viejo").count() == 1


def test_respaldos_viejos_se_eliminan_solos(con_historial):
    _, nombre = purgar_bitacora()
    viejo = (datetime.now() - timedelta(days=400)).timestamp()
    os.utime(ruta_respaldo(nombre), (viejo, viejo))
    purgar_bitacora()
    assert listar_respaldos() == []
