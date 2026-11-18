"""Evidencia Azure explicita sobre registros QA propios; nunca se activa en CI."""

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config.settings import get_settings
from app.modules.aprobaciones.motores import motor
from app.modules.parametros import general

pytestmark = pytest.mark.skipif(
    not os.environ.get("E008_AZURE_MANIFEST"),
    reason="Requiere manifiesto QA propio y Azure de desarrollo autorizado",
)


class EntornoAzureQA:
    """Pytest no debe representar conexiones ni identidades en un fallo."""

    def __init__(self, contenido):
        self._contenido = contenido

    def __iter__(self):
        return iter(self._contenido)

    def __repr__(self):
        return "EntornoAzureQA(datos privados)"


@pytest.fixture(scope="module")
def azure():
    ruta = Path(os.environ["E008_AZURE_MANIFEST"])
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    identidades = json.loads((ruta.parent / "identidades-qa.json").read_text())
    s = get_settings()
    if (
        s.app_env != "development"
        or s.cooperativa_db_server != "enquohub.database.windows.net"
    ):
        raise RuntimeError("Este entorno no esta autorizado para pruebas Azure")
    coop, seg = motor("cooperativa"), motor("seguridad")
    for engine, nombre in ((coop, "CooperativaDB"), (seg, "SeguridadDB")):
        with engine.connect() as c:
            servidor, base = c.execute(
                text(
                    "SELECT CONVERT(varchar(128),SERVERPROPERTY('ServerName')),DB_NAME()"
                )
            ).one()
            if servidor != "enquohub" or base != nombre:
                raise RuntimeError("Servidor o base inesperados")
    with coop.connect() as c:
        for p in datos["parametros"]:
            descripcion = c.execute(
                text(
                    "SELECT Descripcion FROM Parametros.Parametro WHERE IdParametro=:id AND Clave=:clave"
                ),
                {"id": p["idParametro"], "clave": p["clave"]},
            ).scalar_one()
            if descripcion not in (p["descripcion"], p["descripcion"] + " - cambio QA"):
                raise RuntimeError("No se pudo acreditar propiedad del parametro QA")
    with seg.connect() as c:
        for solicitud in datos["solicitudes"]:
            fila = (
                c.execute(
                    text(
                        "SELECT IdObjetivo,SolicitadoPor,IdOrganizacion FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"
                    ),
                    {"id": solicitud["idSolicitud"]},
                )
                .mappings()
                .one()
            )
            propio = (
                fila["IdObjetivo"] == solicitud["clave"]
                and fila["IdOrganizacion"] == identidades["organizacion"]
                and fila["SolicitadoPor"]
                in {a["sujeto"] for a in identidades["cuentas"].values()}
            )
            if not propio:
                raise RuntimeError("No se pudo acreditar propiedad de la solicitud QA")
    return EntornoAzureQA((datos, identidades, coop, seg, ruta.parent))


def test_migraciones_azure_coinciden_con_los_scripts_validados(azure):
    *_, ruta = azure
    ejecutadas = json.loads((ruta / "azure-migraciones.json").read_text())
    assert ejecutadas["completo"] and len(ejecutadas["migraciones"]) == 6
    backend = Path(__file__).resolve().parents[2]
    for m in ejecutadas["migraciones"]:
        actual = (backend / "migrations" / m["base"] / m["archivo"]).read_text(
            encoding="utf-8"
        )
        assert hashlib.sha256(actual.encode()).hexdigest() == m["sha256"]
        assert m["objetosPreviosSinCambios"]


@pytest.mark.parametrize(
    "escenario,estado,valor",
    [
        ("normal", "Ejecutada", 20),
        ("rechazo", "Rechazada", 10),
        ("cancelacion", "Cancelada", 10),
        ("concurrencia", "Ejecutada", 20),
        ("desactualizada", "Fallida", 10),
    ],
)
def test_resultados_reales_persistidos(azure, escenario, estado, valor):
    datos, _, coop, seg, _ = azure
    solicitud = next(s for s in datos["solicitudes"] if s["escenario"] == escenario)
    with seg.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT Estado FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"
                ),
                {"id": solicitud["idSolicitud"]},
            ).scalar_one()
            == estado
        )
    with coop.connect() as c:
        assert (
            general.valor(c, solicitud["clave"], date.today() + timedelta(days=2))
            == valor
        )
        aplicados = c.execute(
            text(
                "SELECT COUNT(*) FROM Seguridad.AprobacionAplicada WHERE IdSolicitud=:id"
            ),
            {"id": solicitud["idSolicitud"]},
        ).scalar_one()
        assert aplicados == (1 if estado == "Ejecutada" else 0)


def test_auditoria_real_incluye_solicitante_y_aprobador(azure):
    datos, identidades, _, seg, _ = azure
    solicitud = next(s for s in datos["solicitudes"] if s["escenario"] == "normal")
    with seg.connect() as c:
        eventos = (
            c.execute(
                text(
                    "SELECT Contenido FROM Auditoria.EventoDetalle WHERE CodigoEvento='APR_OPERACION_EJECUTADA' AND JSON_VALUE(Contenido,'$.idObjetivo')=:id"
                ),
                {"id": str(solicitud["idSolicitud"])},
            )
            .scalars()
            .all()
        )
    assert len(eventos) == 1
    contenido = json.loads(eventos[0])
    comprobado = (
        contenido["cambios"]["solicitante"] == identidades["cuentas"]["admin"]["sujeto"]
        and contenido["cambios"]["aprobador"]
        == identidades["cuentas"]["supervisor"]["sujeto"]
    )
    assert comprobado, "No coincide la trazabilidad de las dos identidades reales"


def test_solicitud_propia_azure_no_permite_alterar_su_hash(azure):
    datos, _, _, seg, _ = azure
    id_ = next(
        s["idSolicitud"] for s in datos["solicitudes"] if s["escenario"] == "normal"
    )
    with seg.connect() as c:
        original = c.execute(
            text(
                "SELECT HashContenido FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"
            ),
            {"id": id_},
        ).scalar_one()
        c.rollback()
        with pytest.raises(DBAPIError) as e, c.begin():
            c.execute(
                text(
                    "UPDATE Seguridad.SolicitudAprobacion SET HashContenido=HASHBYTES('SHA2_256','QA_NO_PERMITIDO') WHERE IdSolicitud=:id"
                ),
                {"id": id_},
            )
        assert "57001" in str(e.value.orig)
        assert (
            c.execute(
                text(
                    "SELECT HashContenido FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"
                ),
                {"id": id_},
            ).scalar_one()
            == original
        )


def test_trigger_azure_protege_solo_el_evento_qa_vinculado(azure):
    datos, _, _, seg, _ = azure
    id_ = next(
        s["idSolicitud"] for s in datos["solicitudes"] if s["escenario"] == "normal"
    )
    with seg.connect() as c:
        id_auditoria = c.execute(
            text(
                "SELECT TOP(1) AuditoriaID FROM Auditoria.EventoDetalle WHERE JSON_VALUE(Contenido,'$.idObjetivo')=:id ORDER BY FechaHoraUTC"
            ),
            {"id": str(id_)},
        ).scalar_one()
        c.rollback()
        with pytest.raises(DBAPIError) as e, c.begin():
            c.execute(
                text(
                    "UPDATE Auditoria.Auditoria SET Descripcion=Descripcion WHERE AuditoriaID=:id"
                ),
                {"id": id_auditoria},
            )
        assert "57201" in str(e.value.orig)


def test_trabajador_real_cancela_al_perder_admin(azure):
    datos, _, coop, seg, _ = azure
    solicitud = next(
        s for s in datos["solicitudes"] if s["escenario"] == "perdida_permiso"
    )
    with seg.connect() as c:
        fila = c.execute(
            text(
                "SELECT Estado,CodigoError FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"
            ),
            {"id": solicitud["idSolicitud"]},
        ).one()
        assert (
            fila.Estado == "Cancelada" and fila.CodigoError == "SOLICITANTE_SIN_PERMISO"
        )
    with coop.connect() as c:
        assert (
            general.valor(c, solicitud["clave"], date.today() + timedelta(days=2)) == 10
        )


def test_recuperacion_real_aplica_una_sola_vez(azure):
    datos, _, coop, seg, _ = azure
    solicitud = next(
        s for s in datos["solicitudes"] if s["escenario"] == "recuperacion"
    )
    with seg.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT Estado FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"
                ),
                {"id": solicitud["idSolicitud"]},
            ).scalar_one()
            == "Ejecutada"
        )
        eventos = (
            c.execute(
                text(
                    "SELECT EstadoNuevo FROM Seguridad.SolicitudAprobacionEvento WHERE IdSolicitud=:id ORDER BY IdEvento"
                ),
                {"id": solicitud["idSolicitud"]},
            )
            .scalars()
            .all()
        )
        assert eventos == ["Pendiente", "Aprobada", "Ejecutada"]
    with coop.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT COUNT(*) FROM Seguridad.AprobacionAplicada WHERE IdSolicitud=:id"
                ),
                {"id": solicitud["idSolicitud"]},
            ).scalar_one()
            == 1
        )
        assert (
            c.execute(
                text(
                    "SELECT COUNT(*) FROM Parametros.ParametroValor WHERE IdSolicitud=:id"
                ),
                {"id": solicitud["idSolicitud"]},
            ).scalar_one()
            == 1
        )


def test_fixture_antigua_real_no_vencio(azure):
    datos, _, coop, seg, _ = azure
    fixture = datos["fixtureAntiguedad"]
    assert fixture["diasSimulados"] == 730 and not fixture["auditoriaHumanaHistorica"]
    with seg.connect() as c:
        fila = c.execute(
            text(
                "SELECT Estado,DATEDIFF(day,FechaSolicitud,SYSUTCDATETIME()) AS Dias FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"
            ),
            {"id": fixture["idSolicitud"]},
        ).one()
        assert fila.Estado == "Ejecutada" and fila.Dias >= 730
    with coop.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT COUNT(*) FROM Parametros.ParametroValor WHERE IdSolicitud=:id"
                ),
                {"id": fixture["idSolicitud"]},
            ).scalar_one()
            == 1
        )
