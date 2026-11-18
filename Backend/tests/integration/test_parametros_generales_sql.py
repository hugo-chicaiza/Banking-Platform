"""E0-09: pruebas reales con manifiesto de destino autorizado, sin credenciales en Git."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

import pyodbc
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.config.settings import Settings
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, usuario_actual
from app.modules.parametros import general as Parametros
from app.modules.parametros.banderas import requiere_funcion

pytestmark = pytest.mark.skipif(
    not os.environ.get("E009_TEST_MANIFEST"),
    reason="Requiere destino SQL E0-09 explicitamente autorizado",
)
INICIO = date(2026, 11, 17)
ACTOR = "user_fixture_e009"


@pytest.fixture(scope="module")
def motor():
    m = json.loads(Path(os.environ["E009_TEST_MANIFEST"]).read_text(encoding="utf-8"))
    assert m["autorizado"] is True and m["app_env"] == "development"
    base = m["base"]
    if m["transporte"] == "lpc:.":
        assert base.startswith("BankingE009_")
        cadena = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER=lpc:.;DATABASE={base};Trusted_Connection=yes;Encrypt=no;APP=E009_SQL_QA"
    else:
        opciones: dict[str, Any] = {"_env_file": os.environ["E009_SETTINGS_FILE"]}
        s = Settings(**opciones)
        assert (
            s.app_env == "development"
            and s.cooperativa_db_name == base
            and (s.cooperativa_db_server == m["servidor_dns"])
        )
        cadena = s.odbc_connection_string("cooperativa")

    def conectar():
        c = pyodbc.connect(cadena, autocommit=False)
        r = c.execute(
            "SELECT DB_NAME(),CONVERT(varchar(128),SERVERPROPERTY('ServerName'))"
        ).fetchone()
        if r is None or r[0] != base or r[1] != m["servidor"]:
            c.close()
            raise RuntimeError("Destino SQL inesperado")
        return c

    e = create_engine("mssql+pyodbc://", creator=conectar, hide_parameters=True)
    yield e
    e.dispose()


@pytest.fixture
def parametro(motor):
    clave = "QA_E009_" + uuid4().hex[:20].upper()
    with motor.begin() as conn:
        id_ = int(
            conn.execute(
                text(
                    "INSERT Parametros.Parametro(Clave,Modulo,Descripcion,TipoDato,ValorMinimo,ValorMaximo,AdmiteAgencia)\n          OUTPUT inserted.IdParametro VALUES (:clave,'QA','Prueba SQL E0-09','Entero',1,100,1)"
                ),
                {"clave": clave},
            ).scalar_one()
        )
    r = Path(os.environ["E009_TEST_MANIFEST"]).parent / "datos-qa-e009.jsonl"
    with r.open("a", encoding="utf-8") as archivo:
        archivo.write(
            json.dumps({"idParametro": id_, "clave": clave, "actorFixture": ACTOR})
            + "\n"
        )
    yield clave
    with motor.begin() as conn:
        propia = conn.execute(
            text(
                "SELECT IdParametro FROM Parametros.Parametro WHERE IdParametro=:id AND Clave=:clave"
            ),
            {"id": id_, "clave": clave},
        ).scalar()
        ajenos = conn.execute(
            text(
                "SELECT COUNT(*) FROM Parametros.ParametroValor WHERE IdParametro=:id AND (CreadoPor IS NULL OR CreadoPor<>:actor)"
            ),
            {"id": id_, "actor": ACTOR},
        ).scalar_one()
        if propia != id_ or ajenos:
            raise RuntimeError("Limpieza detenida: identidad o propiedad no coincide")
        conn.execute(
            text("DELETE Parametros.ParametroValor WHERE IdParametro=:id"), {"id": id_}
        )
        conn.execute(
            text("DELETE Parametros.Parametro WHERE IdParametro=:id AND Clave=:clave"),
            {"id": id_, "clave": clave},
        )


def test_cambio_fecha_y_limites_inclusivos(motor, parametro):
    cambio = INICIO + timedelta(days=10)
    with motor.begin() as c:
        Parametros.registrar(
            c,
            parametro,
            "10",
            INICIO,
            hasta=cambio - timedelta(days=1),
            agencia=None,
            actor=ACTOR,
        )
        Parametros.registrar(
            c, parametro, "20", cambio, hasta=None, agencia=None, actor=ACTOR
        )
        assert Parametros.valor(c, parametro, INICIO) == 10
        assert Parametros.valor(c, parametro, cambio - timedelta(days=1)) == 10
        assert Parametros.valor(c, parametro, cambio) == 20
        assert Parametros.valor(c, parametro, date.max) == 20
        with pytest.raises(HTTPException, match="VALOR_NO_DISPONIBLE"):
            Parametros.valor(c, parametro, INICIO - timedelta(days=1))


def test_override_y_fallback_global_por_fecha(motor, parametro):
    with motor.begin() as c:
        agencia = c.execute(
            text(
                "SELECT TOP(1) IdAgencia FROM Organizacion.Agencia WHERE Estado='A' ORDER BY IdAgencia"
            )
        ).scalar_one()
        Parametros.registrar(
            c, parametro, "10", INICIO, hasta=None, agencia=None, actor=ACTOR
        )
        Parametros.registrar(
            c,
            parametro,
            "20",
            INICIO + timedelta(days=1),
            hasta=INICIO + timedelta(days=2),
            agencia=agencia,
            actor=ACTOR,
        )
        assert Parametros.valor(c, parametro, INICIO, agencia) == 10
        assert Parametros.valor(c, parametro, INICIO + timedelta(days=1), agencia) == 20
        assert Parametros.valor(c, parametro, INICIO + timedelta(days=3), agencia) == 10


@pytest.mark.parametrize("desfase,hasta", [(0, None), (1, None), (-1, 1)])
def test_solape_422_y_transaccion_revertida(motor, parametro, desfase, hasta):
    with motor.begin() as c:
        Parametros.registrar(
            c, parametro, "10", INICIO, hasta=None, agencia=None, actor=ACTOR
        )
    with pytest.raises(HTTPException, match="VIGENCIA_SOLAPADA"), motor.begin() as c:
        Parametros.registrar(
            c,
            parametro,
            "20",
            INICIO + timedelta(days=desfase),
            hasta=INICIO + timedelta(days=hasta) if hasta is not None else None,
            agencia=None,
            actor=ACTOR,
        )
    with motor.connect() as c:
        assert len(Parametros.historial(c, parametro)) == 1


def test_trigger_rechaza_sql_directo(motor, parametro):
    with motor.begin() as c:
        Parametros.registrar(
            c, parametro, "10", INICIO, hasta=None, agencia=None, actor=ACTOR
        )
    with pytest.raises(DBAPIError, match="57101"), motor.begin() as c:
        c.execute(
            text(
                "INSERT Parametros.ParametroValor(IdParametro,Valor,VigenciaDesde,CreadoPor)\n        SELECT IdParametro,'20',:fecha,:actor FROM Parametros.Parametro WHERE Clave=:clave"
            ),
            {"clave": parametro, "fecha": INICIO, "actor": ACTOR},
        )


def test_escritores_concurrentes_solo_un_intervalo(motor, parametro):
    barrera = Barrier(2)

    def guardar(_):
        barrera.wait(timeout=10)
        try:
            with motor.begin() as c:
                Parametros.registrar(
                    c, parametro, "10", INICIO, hasta=None, agencia=None, actor=ACTOR
                )
            return 201
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(guardar, [1, 2]))
    assert sorted(resultados) == [201, 422]
    with motor.connect() as c:
        assert len(Parametros.historial(c, parametro)) == 1


def test_rango_y_estado_no_producen_escritura(motor, parametro):
    with motor.begin() as c:
        with pytest.raises(HTTPException, match="VALOR_FUERA_DE_RANGO"):
            Parametros.registrar(
                c, parametro, "101", INICIO, hasta=None, agencia=None, actor=ACTOR
            )
        with pytest.raises(HTTPException, match="TIPO_PARAMETRO_INVALIDO"):
            Parametros.registrar(
                c, parametro, "true", INICIO, hasta=None, agencia=None, actor=ACTOR
            )
        c.execute(
            text("UPDATE Parametros.Parametro SET Estado='I' WHERE Clave=:clave"),
            {"clave": parametro},
        )
        with pytest.raises(HTTPException, match="PARAMETRO_INACTIVO"):
            Parametros.registrar(
                c, parametro, "10", INICIO, hasta=None, agencia=None, actor=ACTOR
            )
        assert Parametros.historial(c, parametro) == []


def test_bandera_apagada_impide_efectos_de_ruta(motor, parametro, monkeypatch):
    with motor.begin() as c:
        c.execute(
            text(
                "UPDATE Parametros.Parametro SET TipoDato='Booleano',ValorMinimo=NULL,ValorMaximo=NULL WHERE Clave=:clave"
            ),
            {"clave": parametro},
        )
        Parametros.registrar(
            c, parametro, "false", INICIO, hasta=None, agencia=None, actor=ACTOR
        )
    app = FastAPI()
    ejecutado = []

    @app.post("/funcion", dependencies=[Depends(requiere_funcion(parametro))])
    def efecto():
        ejecutado.append(True)

    def conexion():
        with motor.connect() as c:
            yield c

    app.dependency_overrides[cooperativa] = conexion
    app.dependency_overrides[usuario_actual] = lambda: Usuario(
        "user_fixture_e009",
        "session_fixture",
        None,
        "QA",
        "qa@example.invalid",
        ("ADMIN",),
        (),
        id_interno=1,
    )
    with TestClient(app) as client:
        respuesta = client.post("/funcion")
    assert respuesta.status_code == 404
    assert respuesta.json()["detail"]["code"] == "FUNCION_NO_DISPONIBLE"
    assert ejecutado == []


def test_semilla_preserva_valores_y_no_duplica(motor):
    archivo = (
        Path(__file__).parents[2]
        / "migrations/cooperativa/202611172001_parametros_semillas.up.sql"
    )
    # El script administra su propia transaccion; agotar todos los resultados
    # antes de devolver la conexion al pool de operaciones de negocio.
    with motor.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        base = c.execute(text("SELECT DB_NAME()")).scalar_one()
        c.execute(
            text(
                "EXEC sys.sp_set_session_context @key=N'migration_database',@value=:base"
            ),
            {"base": base},
        )
        antes = c.execute(
            text(
                "SELECT COUNT(*) FROM Parametros.ParametroValor WHERE CreadoPor IS NULL"
            )
        ).scalar_one()
        resultado = c.exec_driver_sql(archivo.read_text(encoding="utf-8"))
        if resultado.cursor is not None:
            while resultado.cursor.nextset():
                pass
        resultado.close()
        despues = c.execute(
            text(
                "SELECT COUNT(*) FROM Parametros.ParametroValor WHERE CreadoPor IS NULL"
            )
        ).scalar_one()
        assert despues == antes


@pytest.mark.parametrize("xact_abort", [False, True])
def test_programar_sucesor_e_idempotencia(motor, parametro, xact_abort):
    solicitud = int(uuid4().hex[:12], 16)
    cambio = INICIO + timedelta(days=5)
    with motor.begin() as c:
        c.exec_driver_sql("SET XACT_ABORT ON" if xact_abort else "SET XACT_ABORT OFF")
        anterior = Parametros.registrar(c, parametro, "10", INICIO, actor=ACTOR)
        id_ = Parametros.programar(
            c, parametro, "20", cambio, actor=ACTOR, solicitud=solicitud
        )
        assert (
            Parametros.programar(
                c, parametro, "20", cambio, actor=ACTOR, solicitud=solicitud
            )
            == id_
        )
        assert Parametros.valor(c, parametro, cambio - timedelta(days=1)) == 10
        assert Parametros.valor(c, parametro, cambio) == 20
        assert len(Parametros.historial(c, parametro)) == 2
        fila = (
            c.execute(
                text(
                    "SELECT IdValorAnterior,VigenciaHastaAnterior FROM Parametros.ParametroValor WHERE IdParametroValor=:id"
                ),
                {"id": id_},
            )
            .mappings()
            .one()
        )
        assert (
            fila["IdValorAnterior"] == anterior
            and fila["VigenciaHastaAnterior"] is None
        )
        with pytest.raises(HTTPException, match="IDEMPOTENCIA_CONFLICTIVA"):
            Parametros.programar(
                c, parametro, "30", cambio, actor=ACTOR, solicitud=solicitud
            )


def test_agencia_inactiva_y_alcance_global_rechazan_escritura(motor, parametro):
    with motor.begin() as c:
        with pytest.raises(HTTPException, match="AGENCIA_NO_DISPONIBLE"):
            Parametros.registrar(c, parametro, "10", INICIO, agencia="999", actor=ACTOR)
        c.execute(
            text("UPDATE Parametros.Parametro SET AdmiteAgencia=0 WHERE Clave=:clave"),
            {"clave": parametro},
        )
        with pytest.raises(HTTPException, match="ALCANCE_NO_ADMITIDO"):
            Parametros.registrar(c, parametro, "10", INICIO, agencia="001", actor=ACTOR)
        assert Parametros.historial(c, parametro) == []


def test_registrar_replay_conserva_actor_y_contenido(motor, parametro):
    solicitud = int(uuid4().hex[:12], 16)
    with motor.begin() as c:
        id_ = Parametros.registrar(
            c, parametro, "10", INICIO, actor=ACTOR, solicitud=solicitud
        )
        assert (
            Parametros.registrar(
                c, parametro, "10", INICIO, actor=ACTOR, solicitud=solicitud
            )
            == id_
        )
        with pytest.raises(HTTPException, match="IDEMPOTENCIA_CONFLICTIVA"):
            Parametros.registrar(
                c,
                parametro,
                "10",
                INICIO,
                actor="user_fixture_otro",
                solicitud=solicitud,
            )
        with pytest.raises(HTTPException, match="IDEMPOTENCIA_CONFLICTIVA"):
            Parametros.registrar(
                c, parametro, "11", INICIO, actor=ACTOR, solicitud=solicitud
            )
        assert len(Parametros.historial(c, parametro)) == 1
