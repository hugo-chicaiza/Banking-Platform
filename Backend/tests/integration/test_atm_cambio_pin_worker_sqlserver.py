"""WebJob SQL real opt-in: reutiliza exclusivamente el laboratorio local ATM06."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.core.security import audit
from app.modules.atm import cambio_pin_service as svc
from app.modules.atm import cambio_pin_worker as worker
from app.modules.atm import repository
from tests.integration.test_atm_cambio_pin_sqlserver import laboratorio_sql, sql  # noqa: F401 -- fixtures compartidos.


@pytest.fixture
def job_sql(request, monkeypatch):
    lab = request.getfixturevalue("sql")
    monkeypatch.setattr(worker, "get_engine", lab.engines.__getitem__)

    def guardar(evento):
        with lab.engines["seguridad"].begin() as c:
            audit._insertar(c, evento)

    monkeypatch.setattr(worker.audit, "_persistir", guardar)

    def pendiente(edad=31):
        op = str(uuid4())
        fecha = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=edad)
        with lab.engines["seguridad"].begin() as c:
            c.execute(
                text(
                    "UPDATE Tarjetas.TarjetaPIN SET FechaAsignacion='20260101 00:00:01',FechaUltimoCambio='20260101 00:00:01',RequiereCambio=1 WHERE ID_Tarjeta=:id"
                ),
                {"id": lab.tarjeta},
            )
            c.execute(
                text("""
                INSERT Tarjetas.CambioPINATMOperacion(
                    IdOperacion,ID_TarjetaPIN,ID_Tarjeta,IdATM,IdCanal,
                    ActorAuditoria,JtiOrigen,ExpiracionSesionUTC,VersionAnterior,
                    VersionNueva,RequiereActivacion,Estado,FechaInicioUTC)
                SELECT :op,ID_TarjetaPIN,ID_Tarjeta,1,1,900,:jti,:exp,
                    '20260101','20260101 00:00:01',0,'PIN_CONFIRMADO',:fecha
                FROM Tarjetas.TarjetaPIN WHERE ID_Tarjeta=:id;
            """),
                {
                    "op": op,
                    "jti": lab.sesion.jti,
                    "exp": lab.sesion.fecha_expiracion.replace(tzinfo=None),
                    "fecha": fecha,
                    "id": lab.tarjeta,
                },
            )
            repository.revocar_sesion_atm(
                c, lab.sesion.jti, lab.sesion.fecha_expiracion
            )
        return op

    lab.pendiente = pendiente
    return lab


def test_sql_worker_recupera_y_audita_sin_usuario_humano(job_sql):
    op = job_sql.pendiente()
    assert worker.ejecutar_lote(worker.Politica()) == 0
    job_sql.comprobar()
    with job_sql.engines["seguridad"].connect() as c:
        rows = c.execute(
            text(
                "SELECT UsuarioID,NombreAccion,Descripcion,Resultado FROM Auditoria.Auditoria WHERE IDRegistro=:id"
            ),
            {"id": op},
        ).all()
    assert len(rows) == 2
    assert all(r.UsuarioID is None for r in rows)
    assert rows[-1].NombreAccion == "ATM06_REC_OK"
    assert all("ejecutor=ATM06_WEBJOB" in r.Descripcion for r in rows)


def test_sql_worker_ignora_nuevas_y_vencidas_sin_tocar_pin(job_sql):
    op = job_sql.pendiente(edad=3600)
    with worker.lease() as conn:
        assert conn is not None
        operaciones, vencidas = worker.pendientes(conn, worker.Politica())
        assert op not in operaciones and vencidas >= 1
    assert worker.ejecutar_lote(worker.Politica()) == 1
    with job_sql.engines["seguridad"].connect() as c:
        assert c.scalar(
            text("SELECT RequiereCambio FROM Tarjetas.TarjetaPIN WHERE ID_Tarjeta=:id"),
            {"id": job_sql.tarjeta},
        )
    with pytest.raises(svc.RecuperacionFueraVentana):
        svc.recuperar_cambio_pin(op, max_edad_segundos=1800)
    # La intervencion manual explicita conserva todos los controles de evidencia.
    svc.recuperar_cambio_pin(op)
    job_sql.comprobar()


def test_sql_worker_antiguedad_minima(job_sql):
    op = job_sql.pendiente(edad=0)
    assert worker.ejecutar_lote(worker.Politica()) == 0
    with job_sql.engines["seguridad"].connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT Estado FROM Tarjetas.CambioPINATMOperacion WHERE IdOperacion=:id"
                ),
                {"id": op},
            )
            == "PIN_CONFIRMADO"
        )


def test_sql_lease_excluye_otro_proceso_y_se_libera(job_sql):
    with worker.lease() as primero:
        assert primero is not None
        worker.comprobar_lease(primero)
        with worker.lease() as segundo:
            assert segundo is None
    with worker.lease() as tercero:
        assert tercero is not None
        worker.comprobar_lease(tercero)


def test_sql_lease_perdida_se_detecta(job_sql):
    with pytest.raises(worker.LeasePerdida), worker.lease() as conn:
        assert conn is not None
        conn.invalidate()
        worker.comprobar_lease(conn)


def test_sql_dos_ejecutores_no_duplican(job_sql, monkeypatch):
    job_sql.pendiente()
    original = worker.recuperar_cambio_pin
    listo, continuar = Event(), Event()

    def esperar(*a, **kw):
        listo.set()
        assert continuar.wait(5)
        return original(*a, **kw)

    monkeypatch.setattr(worker, "recuperar_cambio_pin", esperar)
    with ThreadPoolExecutor(2) as executor:
        primero = executor.submit(worker.ejecutar_lote, worker.Politica())
        assert listo.wait(5)
        segundo = executor.submit(worker.ejecutar_lote, worker.Politica())
        assert segundo.result(timeout=5) == 0
        continuar.set()
        assert primero.result(timeout=10) == 0
    job_sql.comprobar()


def test_sql_reintento_commit_ambiguo_no_repite_hsm_ni_historial(job_sql, monkeypatch):
    job_sql.pendiente()
    original = svc.repo.aplicar_cooperativa
    fallar = True

    def ambiguo(*a, **kw):
        nonlocal fallar
        original(*a, **kw)
        if fallar:
            job_sql.fallos["cooperativa"] = True
            fallar = False

    monkeypatch.setattr(svc.repo, "aplicar_cooperativa", ambiguo)

    def prohibido():
        pytest.fail("La recuperacion no debe utilizar el HSM")

    monkeypatch.setattr(svc, "obtener_hsm", prohibido)
    assert worker.ejecutar_lote(worker.Politica(espera=0)) == 0
    job_sql.comprobar()
    with job_sql.engines["seguridad"].connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT IntentosFallidos FROM Tarjetas.TarjetaPIN WHERE ID_Tarjeta=:id"
                ),
                {"id": job_sql.tarjeta},
            )
            == 0
        )


def test_sql_inconsistente_no_se_finaliza(job_sql):
    op = job_sql.pendiente()
    with job_sql.engines["seguridad"].begin() as c:
        c.execute(
            text(
                "UPDATE Tarjetas.TarjetaPIN SET Estado='Bloqueado',IntentosFallidos=3 WHERE ID_Tarjeta=:id"
            ),
            {"id": job_sql.tarjeta},
        )
    assert worker.ejecutar_lote(worker.Politica(intentos=3)) == 1
    with job_sql.engines["seguridad"].connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT Estado FROM Tarjetas.CambioPINATMOperacion WHERE IdOperacion=:id"
                ),
                {"id": op},
            )
            == "PIN_CONFIRMADO"
        )
        assert (
            c.scalar(
                text(
                    "SELECT IntentosFallidos FROM Tarjetas.TarjetaPIN WHERE ID_Tarjeta=:id"
                ),
                {"id": job_sql.tarjeta},
            )
            == 3
        )
