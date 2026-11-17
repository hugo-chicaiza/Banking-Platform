"""#450 SQL real, opt-in, cuentas autorizadas y rollback; sin DDL."""

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.modules.auth import agencias_repository as repo
from app.modules.auth.agencias import hash_sesion

pytestmark = pytest.mark.skipif(
    os.getenv("MULTIAGENCIA_SQL_PRUEBAS") != "1",
    reason="Requiere autorizacion y manifiesto QA local",
)


@pytest.fixture
def entorno():
    assert get_settings().app_env == "development"
    manifiesto = json.loads(
        Path(os.environ["MULTIAGENCIA_QA_MANIFIESTO"]).read_text(encoding="utf-8")
    )
    ids = {a["cuenta"]: a["id_usuario"] for a in manifiesto["cuentas_autorizadas"]}
    with get_engine("seguridad").connect() as conn:
        assert (
            conn.scalar(text("SELECT DB_NAME()")) == manifiesto["base"] == "SeguridadDB"
        )
        assert (
            conn.scalar(
                text("SELECT CONVERT(varchar(128),SERVERPROPERTY('ServerName'))")
            )
            == manifiesto["servidor"]
        )
    return ids


@pytest.fixture
def conn(entorno):
    with get_engine("seguridad").connect() as conn:
        tx = conn.begin()
        try:
            yield conn, entorno
        finally:
            tx.rollback()


def test_sql_asignacion_historial_y_rollback(conn):
    c, ids = conn
    usuario, actor = ids["contador"], ids["administrador"]
    original = repo.asignaciones(c, usuario)
    version = repo.version(c, usuario)
    with c.begin_nested() as tx:
        repo.guardar_asignacion(c, usuario, "002", False, actor)
        assert "002" not in repo.asignaciones(c, usuario)
        repo.guardar_asignacion(c, usuario, "002", True, actor)
        repo.historico(c, usuario, "ASIGNAR", "002", "001", "001", actor, "001")
        assert repo.version(c, usuario) > version
        rows, total = repo.historial(c, usuario, 1, 20)
        assert total >= 1 and rows[0]["realizado_por"] == actor
        esperado = c.scalar(
            text(
                "SELECT NULLIF(LTRIM(RTRIM(CONCAT(Nombres,' ',Apellidos))), '') FROM Organizacion.Usuarios WHERE UsuarioID=:id"
            ),
            {"id": actor},
        )
        assert rows[0]["nombre_actor"] == esperado and esperado
        assert (
            c.scalar(
                text(
                    "SELECT Origen FROM Organizacion.UsuarioAgencia WHERE UsuarioID=:id AND IdAgencia='002'"
                ),
                {"id": usuario},
            )
            == "Administrador"
        )
        tx.rollback()
    assert repo.asignaciones(c, usuario) == original
    assert repo.version(c, usuario) == version


def test_sql_revocacion_no_resucita_principal(conn):
    c, ids = conn
    usuario, actor = ids["contador"], ids["administrador"]
    for agencia in repo.asignaciones(c, usuario):
        repo.guardar_asignacion(c, usuario, agencia, False, actor)
    assert repo.asignaciones(c, usuario) == []
    assert (
        c.scalar(
            text("SELECT AgenciaID FROM Organizacion.Usuarios WHERE UsuarioID=:id"),
            {"id": usuario},
        )
        is not None
    )


def test_sql_contextos_separados_y_inicializacion_no_sobrescribe(conn):
    c, ids = conn
    usuario = ids["contador"]
    a, b = hash_sesion(str(uuid4())), hash_sesion(str(uuid4()))
    repo.guardar_contexto(c, a, usuario, "002")
    repo.inicializar_contexto(c, a, usuario, "001")
    repo.inicializar_contexto(c, b, usuario, "001")
    contexto_a = repo.contexto(c, a, usuario)
    contexto_b = repo.contexto(c, b, usuario)
    assert contexto_a is not None and contexto_a["agencia"] == "002"
    assert contexto_b is not None and contexto_b["agencia"] == "001"
    assert repo.contexto(c, a, ids["administrador"]) is None


def test_sql_cambios_usuario_serializan_con_bloqueo(entorno):
    params = {"id": entorno["contador"]}
    engine = get_engine("seguridad")
    with engine.connect() as a, engine.connect() as b:
        try:
            a.execute(
                text(
                    "SELECT UsuarioID FROM Organizacion.Usuarios WITH (UPDLOCK,ROWLOCK) WHERE UsuarioID=:id"
                ),
                params,
            ).all()
            b.execute(text("SET LOCK_TIMEOUT 250"))
            with pytest.raises(DBAPIError):
                b.execute(
                    text(
                        "SELECT UsuarioID FROM Organizacion.Usuarios WITH (UPDLOCK,ROWLOCK) WHERE UsuarioID=:id"
                    ),
                    params,
                ).all()
        finally:
            a.rollback()
            b.rollback()
            b.execute(text("SET LOCK_TIMEOUT -1"))
            b.commit()
