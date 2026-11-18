"""SQL real en dos bases locales propias; identidades sinteticas solo en esta suite.

No acredita login WorkOS ni integracion Azure; esas evidencias son independientes.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier, Event
from uuid import uuid4

import pyodbc
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.modules.aprobaciones.auditoria import ContextoAuditoria
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.aprobaciones.registro import Objetivo
from app.modules.aprobaciones.relevo import entregar
from app.modules.aprobaciones.servicio import Servicio
from app.modules.parametros import general

pytestmark = pytest.mark.skipif(
    not os.environ.get("E008_LOCAL_MANIFEST"),
    reason="Requiere dos bases locales propias y manifiesto E0-08",
)
HOY = date(2026, 11, 18)
ORG = "org_fixture_e008"
CREADOR = Actor(
    "user_fixture_maker",
    ORG,
    "Solicitante QA",
    900801,
    ("ADMIN",),
    frozenset(),
    ("001", "002"),
)
APROBADOR = Actor(
    "user_fixture_checker",
    ORG,
    "Aprobador QA",
    900802,
    ("SUPERVISOR",),
    frozenset({"parametros:aprobar"}),
    ("001",),
)
CONTEXTO = ContextoAuditoria("session_fixture", "127.0.0.1", "qa-e008", "QA_SQL_LOCAL")


@pytest.fixture(scope="module")
def motores():
    m = json.loads(Path(os.environ["E008_LOCAL_MANIFEST"]).read_text(encoding="utf-8"))
    assert m["transporte"] == "lpc:." and m["propias"] is True
    motores = {}
    for k, nombre in m["bases"].items():
        assert nombre.startswith("BankingE008_")

        def conectar(base=nombre):
            c = pyodbc.connect(
                "DRIVER={ODBC Driver 18 for SQL Server};SERVER=lpc:.;Trusted_Connection=yes;Encrypt=no;DATABASE="
                + base,
                autocommit=False,
            )
            assert c.execute("SELECT DB_NAME()").fetchval() == base
            return c

        motores[k] = create_engine(
            "mssql+pyodbc://", creator=conectar, hide_parameters=True
        )
    yield motores
    for m in motores.values():
        m.dispose()


@pytest.fixture
def caso(motores):
    clave = "QA_E008_" + uuid4().hex[:20].upper()
    with motores["cooperativa"].begin() as c:
        c.execute(
            text(
                "INSERT Parametros.Parametro(Clave,Modulo,Descripcion,TipoDato,ValorMinimo,ValorMaximo,EsSensible,AdmiteAgencia) VALUES(:clave,'QA','Fixture SQL E0-08','Entero',1,100,1,1)"
            ),
            {"clave": clave},
        )
        general.registrar(c, clave, "10", HOY - timedelta(days=1), actor=CREADOR.sujeto)
    actores = {a.sujeto: a for a in (CREADOR, APROBADOR)}
    servicio = Servicio(
        motores["seguridad"],
        motores["cooperativa"],
        registro_inicial(),
        lambda sujeto, org: actores[sujeto],
    )
    objetivo = Objetivo("Parametro", clave, None)
    id_ = servicio.solicitar(
        CREADOR,
        "PAR-EDITAR",
        objetivo,
        {"valor": "20", "vigenciaDesde": (HOY + timedelta(days=1)).isoformat()},
        HOY,
        CONTEXTO,
    )
    return servicio, id_, clave, actores


def fila(motores, id_):
    with motores["seguridad"].connect() as c:
        return dict(
            c.execute(
                text(
                    "SELECT * FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"
                ),
                {"id": id_},
            )
            .mappings()
            .one()
        )


def valor(motores, clave):
    with motores["cooperativa"].connect() as c:
        return general.valor(c, clave, HOY + timedelta(days=2))


def test_solicitar_persiste_sin_ejecutar(motores, caso):
    _, id_, clave, _ = caso
    assert fila(motores, id_)["Estado"] == "Pendiente"
    assert valor(motores, clave) == 10


def test_pagina_vacia_conserva_total_para_volver_a_solicitudes(motores, caso):
    from app.modules.aprobaciones.lecturas import listar

    servicio, _, _, _ = caso
    primera = listar(servicio, CREADOR, "mias", 1, 20)
    ultima = listar(servicio, CREADOR, "mias", 100000, 20)
    assert primera.total > 0
    assert ultima.items == [] and ultima.total == primera.total


def test_propia_403_y_evento_persistido(motores, caso):
    servicio, id_, clave, _ = caso
    with pytest.raises(HTTPException, match="APROBADOR_ES_SOLICITANTE") as e:
        servicio.aprobar(CREADOR, id_, None, CONTEXTO)
    assert e.value.status_code == 403 and valor(motores, clave) == 10
    with motores["seguridad"].connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT COUNT(*) FROM Auditoria.EventoPendiente WHERE CodigoEvento='APR_AUTOAPROBACION_INTENTO' AND JSON_VALUE(Contenido,'$.idObjetivo')=:id"
                ),
                {"id": str(id_)},
            ).scalar_one()
            == 1
        )


def test_otra_persona_aplica_con_auditoria_y_relevo(motores, caso):
    servicio, id_, clave, _ = caso
    assert servicio.aprobar(APROBADOR, id_, None, CONTEXTO)["estado"] == "Ejecutada"
    assert (
        valor(motores, clave) == 20
        and fila(motores, id_)["ResueltoPor"] == APROBADOR.sujeto
    )
    entregar(motores["cooperativa"], motores["seguridad"])
    entregar(motores["seguridad"], motores["seguridad"])
    with motores["seguridad"].connect() as c:
        eventos = (
            c.execute(
                text(
                    "SELECT Contenido FROM Auditoria.EventoDetalle WHERE JSON_VALUE(Contenido,'$.idObjetivo')=:id"
                ),
                {"id": str(id_)},
            )
            .scalars()
            .all()
        )
    assert any(CREADOR.sujeto in e for e in eventos) and any(
        APROBADOR.sujeto in e for e in eventos
    )


def test_dos_aprobadores_exactamente_uno(motores, caso):
    servicio, id_, clave, _ = caso
    barrera = Barrier(2)

    def aprobar(indice):
        barrera.wait(timeout=10)
        try:
            otro = Actor(
                "user_fixture_checker2",
                ORG,
                "Segundo aprobador QA",
                900803,
                ("SUPERVISOR",),
                APROBADOR.permisos,
                ("001",),
            )
            servicio.aprobar(APROBADOR if indice == 1 else otro, id_, None, CONTEXTO)
            return 200
        except HTTPException as e:
            assert isinstance(e.detail, dict)
            assert "SOLICITUD_NO_PENDIENTE" in str(e.detail)
            return e.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(aprobar, [1, 2])) == [200, 409]
    assert valor(motores, clave) == 20


def test_objetivo_desactualizado_no_se_aplica(motores, caso):
    servicio, id_, clave, _ = caso
    with motores["cooperativa"].begin() as c:
        c.execute(
            text(
                "UPDATE Parametros.ParametroValor SET Valor='11' WHERE IdParametro=(SELECT IdParametro FROM Parametros.Parametro WHERE Clave=:clave)"
            ),
            {"clave": clave},
        )
    with pytest.raises(HTTPException, match="SOLICITUD_DESACTUALIZADA") as e:
        servicio.aprobar(APROBADOR, id_, None, CONTEXTO)
    assert e.value.status_code == 409 and valor(motores, clave) == 11
    assert fila(motores, id_)["Estado"] == "Fallida"


def test_recuperar_despues_commit_destino_sin_duplicar(motores, caso, monkeypatch):
    servicio, id_, clave, _ = caso
    terminar = servicio._terminar

    def fallo(*args):
        raise SQLAlchemyError("Fallo controlado antes de confirmar SeguridadDB")

    monkeypatch.setattr(servicio, "_terminar", fallo)
    with pytest.raises(HTTPException, match="APROBACION_PENDIENTE_RECUPERACION"):
        servicio.aprobar(APROBADOR, id_, None, CONTEXTO)
    assert valor(motores, clave) == 20 and fila(motores, id_)["Estado"] == "Aprobada"
    monkeypatch.setattr(servicio, "_terminar", terminar)
    assert servicio.ejecutar(id_, ORG, APROBADOR, CONTEXTO)["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT COUNT(*) FROM Parametros.ParametroValor WHERE IdSolicitud=:id"
                ),
                {"id": id_},
            ).scalar_one()
            == 1
        )


def test_comprobante_de_otro_contenido_no_autoriza_repetir_el_efecto(motores, caso):
    from app.modules.aprobaciones.congelacion import congelar

    servicio, id_, clave, _ = caso
    servicio.aprobar(APROBADOR, id_, None, CONTEXTO)
    copia = fila(motores, id_)
    contenido = json.loads(copia["Contenido"])
    contenido["cambio"]["valor"] = "30"
    alterado = congelar(contenido)
    copia["Contenido"], copia["HashContenido"] = alterado.texto, alterado.huella
    operacion = servicio.registro.obtener("PAR-EDITAR", "Parametro")
    with motores["cooperativa"].begin() as c:
        with pytest.raises(HTTPException, match="CONTENIDO_ALTERADO") as e:
            servicio._aplicar(c, copia, operacion, APROBADOR, CONTEXTO)
        assert e.value.status_code == 409
    assert valor(motores, clave) == 20


def test_hash_invalido_denegado_tras_fault_injection_solo_local(motores, caso):
    servicio, id_, clave, _ = caso
    # Esta suite y sus motores estan limitados a lpc y bases propias. Nunca Azure.
    with motores["seguridad"].begin() as c:
        c.exec_driver_sql(
            "DISABLE TRIGGER Seguridad.trg_SA_E008_Inmutable ON Seguridad.SolicitudAprobacion"
        )
        try:
            c.execute(
                text(
                    "UPDATE Seguridad.SolicitudAprobacion SET HashContenido=:hash WHERE IdSolicitud=:id"
                ),
                {"id": id_, "hash": bytes(32)},
            )
        finally:
            c.exec_driver_sql(
                "ENABLE TRIGGER Seguridad.trg_SA_E008_Inmutable ON Seguridad.SolicitudAprobacion"
            )
    with pytest.raises(HTTPException, match="CONTENIDO_ALTERADO"):
        servicio.aprobar(APROBADOR, id_, None, CONTEXTO)
    assert valor(motores, clave) == 10 and fila(motores, id_)["Estado"] == "Pendiente"


def test_perdida_permisos_cancela(motores, caso):
    servicio, id_, clave, actores = caso
    actores[CREADOR.sujeto] = Actor(
        CREADOR.sujeto,
        ORG,
        CREADOR.nombre,
        CREADOR.id_interno,
        ("CONTADOR",),
        frozenset(),
        ("001",),
    )
    with pytest.raises(HTTPException, match="SOLICITANTE_SIN_PERMISO"):
        servicio.aprobar(APROBADOR, id_, None, CONTEXTO)
    assert fila(motores, id_)["Estado"] == "Cancelada" and valor(motores, clave) == 10


def test_sin_permiso_no_aprueba_y_admin_no_lo_implica(motores, caso):
    servicio, id_, clave, _ = caso
    actor = Actor(
        "user_fixture_admin2",
        ORG,
        "Administrador QA",
        900803,
        ("ADMIN",),
        frozenset(),
        (),
    )
    with pytest.raises(HTTPException, match="SIN_PERMISO"):
        servicio.aprobar(actor, id_, None, CONTEXTO)
    assert fila(motores, id_)["Estado"] == "Pendiente" and valor(motores, clave) == 10


def test_bandeja_sin_evento_revierte_cambio(motores, caso, monkeypatch):
    from app.modules.aprobaciones import servicio as modulo

    servicio, id_, clave, _ = caso
    original = modulo.encolar

    def fallar(conn, codigo, *args, **kwargs):
        if codigo == "APR_OPERACION_EJECUTADA":
            raise SQLAlchemyError("Fallo controlado de outbox")
        return original(conn, codigo, *args, **kwargs)

    monkeypatch.setattr(modulo, "encolar", fallar)
    with pytest.raises(HTTPException, match="APROBACION_PENDIENTE_RECUPERACION"):
        servicio.aprobar(APROBADOR, id_, None, CONTEXTO)
    assert valor(motores, clave) == 10 and fila(motores, id_)["Estado"] == "Aprobada"
    monkeypatch.setattr(modulo, "encolar", original)
    servicio.ejecutar(id_, ORG, APROBADOR, CONTEXTO)
    assert valor(motores, clave) == 20


def test_trigger_no_afecta_insert_ni_update_legacy(motores, caso):
    servicio, id_, _, _ = caso
    servicio.aprobar(APROBADOR, id_, None, CONTEXTO)
    entregar(motores["seguridad"], motores["seguridad"])
    with motores["seguridad"].begin() as c:
        legacy = c.execute(
            text(
                "INSERT Auditoria.Auditoria(NombreAccion,FechaHora,Resultado) OUTPUT inserted.AuditoriaID VALUES('QA_LEGACY',GETDATE(),'Exitoso')"
            )
        ).scalar_one()
        c.execute(
            text(
                "UPDATE Auditoria.Auditoria SET Descripcion='Cambio legitimo legacy' WHERE AuditoriaID=:id"
            ),
            {"id": legacy},
        )
    with motores["seguridad"].connect() as c:
        protegido = c.execute(
            text("SELECT TOP(1) AuditoriaID FROM Auditoria.EventoDetalle")
        ).scalar_one()
    with pytest.raises(DBAPIError, match="57201"), motores["seguridad"].begin() as c:
        c.execute(
            text(
                "UPDATE Auditoria.Auditoria SET Descripcion='No debe permitirse' WHERE AuditoriaID=:id"
            ),
            {"id": protegido},
        )


def test_relevo_repetido_no_duplica(motores, caso):
    servicio, id_, _, _ = caso
    servicio.aprobar(APROBADOR, id_, None, CONTEXTO)
    entregar(motores["seguridad"], motores["seguridad"])
    with motores["seguridad"].begin() as c:
        antes = c.execute(
            text("SELECT COUNT(*) FROM Auditoria.EventoDetalle")
        ).scalar_one()
        c.execute(
            text(
                "UPDATE Auditoria.EventoPendiente SET Enviado=0 WHERE JSON_VALUE(Contenido,'$.idObjetivo')=:id"
            ),
            {"id": str(id_)},
        )
    entregar(motores["seguridad"], motores["seguridad"])
    with motores["seguridad"].connect() as c:
        assert (
            c.execute(text("SELECT COUNT(*) FROM Auditoria.EventoDetalle")).scalar_one()
            == antes
        )


def test_solicitud_antigua_no_vence(motores, caso):
    servicio, id_, clave, _ = caso
    servicio.resolver(
        CREADOR, id_, "Cancelada", "Fixture de solicitud antigua", CONTEXTO
    )
    with motores["seguridad"].begin() as c:
        antiguo = c.execute(
            text("""INSERT Seguridad.SolicitudAprobacion
            (IdOrganizacion,CodigoTransaccion,TipoObjetivo,IdObjetivo,IdAgencia,Contenido,HashContenido,Antes,Despues,VersionObjetivo,SolicitadoPor,NombreSolicitante,IdInternoSolicitante,FechaSolicitud)
            OUTPUT inserted.IdSolicitud
            SELECT IdOrganizacion,CodigoTransaccion,TipoObjetivo,IdObjetivo,IdAgencia,Contenido,HashContenido,Antes,Despues,VersionObjetivo,SolicitadoPor,NombreSolicitante,IdInternoSolicitante,DATEADD(year,-2,SYSUTCDATETIME())
            FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"""),
            {"id": id_},
        ).scalar_one()
    assert servicio.aprobar(APROBADOR, antiguo, None, CONTEXTO)["estado"] == "Ejecutada"
    assert valor(motores, clave) == 20


def test_rechazo_comentado_y_cancelacion_solo_del_creador(motores, caso):
    servicio, id_, clave, _ = caso
    with pytest.raises(HTTPException, match="SIN_PERMISO"):
        servicio.resolver(APROBADOR, id_, "Cancelada", "No corresponde", CONTEXTO)
    with pytest.raises(HTTPException, match="COMENTARIO_REQUERIDO"):
        servicio.resolver(APROBADOR, id_, "Rechazada", " ", CONTEXTO)
    assert (
        servicio.resolver(APROBADOR, id_, "Rechazada", "Fuera de politica", CONTEXTO)[
            "estado"
        ]
        == "Rechazada"
    )
    assert valor(motores, clave) == 10


def test_recuperacion_real_y_resumen_no_expira_pendientes(motores, caso):
    from app.modules.aprobaciones.tareas import ejecutar

    servicio, id_, clave, actores = caso
    # Revocar el acceso en la fuente de identidad sintetica del laboratorio.
    actores[CREADOR.sujeto] = Actor(
        CREADOR.sujeto,
        ORG,
        CREADOR.nombre,
        CREADOR.id_interno,
        ("CONTADOR",),
        frozenset(),
        ("001",),
    )
    resultado = ejecutar(servicio, ORG, "APR_RECUPERACION")
    assert resultado.procesados >= 1
    assert fila(motores, id_)["Estado"] == "Cancelada" and valor(motores, clave) == 10
    ejecutar(servicio, ORG, "APR_RESUMEN_ANTIGUAS")
    with motores["seguridad"].connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT COUNT(*) FROM Sistema.ResumenAprobaciones WHERE IdOrganizacion=:org"
                ),
                {"org": ORG},
            ).scalar_one()
            == 1
        )


def test_recurso_eliminado_falla_sin_quedar_aprobada_indefinidamente(motores, caso):
    servicio, id_, clave, _ = caso
    with motores["cooperativa"].begin() as c:
        id_parametro = c.execute(
            text("SELECT IdParametro FROM Parametros.Parametro WHERE Clave=:clave"),
            {"clave": clave},
        ).scalar_one()
        c.execute(
            text("DELETE Parametros.ParametroValor WHERE IdParametro=:id"),
            {"id": id_parametro},
        )
        c.execute(
            text("DELETE Parametros.Parametro WHERE IdParametro=:id AND Clave=:clave"),
            {"id": id_parametro, "clave": clave},
        )
    with pytest.raises(HTTPException, match="PARAMETRO_NO_ENCONTRADO"):
        servicio.aprobar(APROBADOR, id_, None, CONTEXTO)
    assert fila(motores, id_)["Estado"] == "Fallida"


def test_trabajador_no_cancela_operaciones_no_registradas(motores, caso):
    from app.modules.aprobaciones.tareas import recuperar

    servicio, id_, _, actores = caso
    with motores["seguridad"].begin() as c:
        otro = c.execute(
            text("""INSERT Seguridad.SolicitudAprobacion
            (IdOrganizacion,CodigoTransaccion,TipoObjetivo,IdObjetivo,Contenido,HashContenido,Antes,Despues,VersionObjetivo,SolicitadoPor)
            OUTPUT inserted.IdSolicitud
            SELECT IdOrganizacion,'ORG-AGENCIA-EDITAR','Agencia',:objetivo,Contenido,HashContenido,Antes,Despues,VersionObjetivo,SolicitadoPor
            FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"""),
            {"id": id_, "objetivo": "QA_" + uuid4().hex},
        ).scalar_one()
    actores[CREADOR.sujeto] = Actor(
        CREADOR.sujeto,
        ORG,
        CREADOR.nombre,
        CREADOR.id_interno,
        ("CONTADOR",),
        frozenset(),
        ("001",),
    )
    recuperar(servicio, ORG)
    assert fila(motores, otro)["Estado"] == "Pendiente"


def test_operacion_en_seguridad_es_atomica_con_su_aprobacion(motores):
    from app.modules.aprobaciones.registro import Operacion, Plan, Registro

    objetivo = Objetivo("ObjetoQA", "QA_" + uuid4().hex, None)
    maker = Actor(
        "user_fixture_seg_maker",
        ORG,
        "Solicitante SQL QA",
        900811,
        ("ADMIN",),
        frozenset(),
        (),
    )
    with motores["seguridad"].begin() as c:
        c.exec_driver_sql(
            "IF OBJECT_ID('Seguridad.ObjetivoQA','U') IS NULL CREATE TABLE Seguridad.ObjetivoQA(Id varchar(60) PRIMARY KEY,Valor int NOT NULL,Version rowversion)"
        )
        c.execute(
            text("INSERT Seguridad.ObjetivoQA(Id,Valor) VALUES(:id,10)"),
            {"id": objetivo.id},
        )
        c.exec_driver_sql(
            "IF NOT EXISTS(SELECT 1 FROM Seguridad.TransaccionesInterfaz WHERE CodigoTransaccion='QA-SEG-EDITAR') INSERT Seguridad.TransaccionesInterfaz(CodigoTransaccion,NombreTransaccion,Modulo,BaseObjetivo,RolesEjecucion,PermisoAprobacion) VALUES('QA-SEG-EDITAR','Fixture local','QA','seguridad','[\"ADMIN\"]','parametros:aprobar')"
        )

    class ManejadorQA:
        fallo = True

        def version(self, conn, objetivo):
            return bytes(
                conn.execute(
                    text(
                        "SELECT Version FROM Seguridad.ObjetivoQA WITH(UPDLOCK,HOLDLOCK) WHERE Id=:id"
                    ),
                    {"id": objetivo.id},
                ).scalar_one()
            ).hex()

        def preparar(self, conn, objetivo, contenido, hoy):
            return Plan(
                contenido, {"valor": 10}, {"valor": 20}, self.version(conn, objetivo)
            )

        def aplicar(self, conn, objetivo, contenido, solicitante, id_solicitud):
            conn.execute(
                text("UPDATE Seguridad.ObjetivoQA SET Valor=20 WHERE Id=:id"),
                {"id": objetivo.id},
            )
            if self.fallo:
                raise SQLAlchemyError("Fallo local despues de escribir el objetivo")

    manejador = ManejadorQA()
    registro = Registro()
    registro.agregar(
        Operacion(
            "QA-SEG-EDITAR",
            "ObjetoQA",
            "seguridad",
            frozenset({"ADMIN"}),
            "parametros:aprobar",
            manejador,
        )
    )
    servicio = Servicio(
        motores["seguridad"],
        motores["cooperativa"],
        registro,
        lambda sujeto, org: maker,
    )
    id_ = servicio.solicitar(
        maker, "QA-SEG-EDITAR", objetivo, {"valor": 20}, HOY, CONTEXTO
    )
    with pytest.raises(SQLAlchemyError):
        servicio.aprobar(APROBADOR, id_, None, CONTEXTO)
    with motores["seguridad"].connect() as c:
        assert (
            c.execute(
                text("SELECT Valor FROM Seguridad.ObjetivoQA WHERE Id=:id"),
                {"id": objetivo.id},
            ).scalar_one()
            == 10
        )
    assert fila(motores, id_)["Estado"] == "Pendiente"
    manejador.fallo = False
    assert servicio.aprobar(APROBADOR, id_, None, CONTEXTO)["estado"] == "Ejecutada"
    with motores["seguridad"].connect() as c:
        assert (
            c.execute(
                text("SELECT Valor FROM Seguridad.ObjetivoQA WHERE Id=:id"),
                {"id": objetivo.id},
            ).scalar_one()
            == 20
        )


def test_dos_trabajadores_no_ejecutan_la_misma_tarea_a_la_vez(
    motores, caso, monkeypatch
):
    from app.modules.aprobaciones import tareas

    servicio, _, _, _ = caso
    original = tareas.resumir
    iniciado, continuar = Event(), Event()

    def demorar(servicio, org):
        iniciado.set()
        assert continuar.wait(timeout=15)
        return original(servicio, org)

    monkeypatch.setattr(tareas, "resumir", demorar)
    with ThreadPoolExecutor(max_workers=2) as pool:
        primera = pool.submit(tareas.ejecutar, servicio, ORG, "APR_RESUMEN_ANTIGUAS")
        try:
            assert iniciado.wait(timeout=15)
            with pytest.raises(HTTPException, match="TAREA_EN_EJECUCION") as e:
                tareas.ejecutar(servicio, ORG, "APR_RESUMEN_ANTIGUAS")
            assert e.value.status_code == 409
        finally:
            continuar.set()
        assert primera.result(timeout=15).errores == 0
    # El bloqueo se libero: otra ejecucion legitima puede completar su registro.
    assert tareas.ejecutar(servicio, ORG, "APR_RESUMEN_ANTIGUAS").errores == 0
