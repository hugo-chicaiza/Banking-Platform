"""Arnés opt-in de ATM-09: solo revocaciones ficticias, nunca datos bancarios.

Los commits son reales. No hay limpieza ni reintentos. Importar este módulo no
crea motores ni conexiones. Las claves solo se transmiten en memoria entre hijos.
"""

import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import URL, create_engine, event, text
from sqlalchemy.pool import NullPool

from app.core.config.settings import Settings, get_settings
from app.modules.atm import router, session
from app.modules.atm.schemas import CuentaATM
from app.modules.atm.service import AccesoATMValidado

ROW_SQL = (
    "SELECT Jti, FechaRevocacion, FechaExpiracion "
    "FROM Seguridad.SesionesATMRevocadas WHERE Jti = :jti"
)
READ = "select 1 from seguridad.sesionesatmrevocadas where jti = ?"
LOCK = "select 1 from seguridad.sesionesatmrevocadas with (updlock, holdlock) where jti = ?"
INSERT = (
    "insert into seguridad.sesionesatmrevocadas (jti, fechaexpiracion) values (?, ?)"
)
ROWS = (
    "select jti, fecharevocacion, fechaexpiracion "
    "from seguridad.sesionesatmrevocadas where jti = ?"
)
DEADLINE = 35


def require_opt_in(variable: str) -> None:
    import pytest

    if os.getenv(variable) != "1":
        pytest.skip(f"Deshabilitada: autorizar explícitamente {variable}=1")
    if os.getenv("ATM09_EXPECTED_DATABASE") != "SeguridadDB":
        raise RuntimeError("Confirmar ATM09_EXPECTED_DATABASE=SeguridadDB")
    expected = os.getenv("ATM09_EXPECTED_SQL_SERVER", "")
    if not expected or expected != get_settings().seguridad_db_server:
        raise RuntimeError("El servidor no coincide con la confirmación explícita")


def laboratory_session() -> tuple[str, str, str, datetime]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    with patch.object(session, "get_settings", return_value=jwt_settings(pem)):
        token = session.emitir_sesion_atm(
            AccesoATMValidado(
                900000001,
                900000002,
                "Laboratorio ficticio ATM-09",
                [
                    CuentaATM(
                        id_cuenta=900000003,
                        numero_cuenta_enmascarado="******0000",
                        tipo_cuenta="Ahorro",
                    )
                ],
            )
        ).session_token
        validated = session.validar_jwt_atm(token)
    return pem, token, validated.jti, validated.fecha_expiracion.replace(tzinfo=None)


def jwt_settings(pem: str) -> Settings:
    return Settings.model_construct(
        atm_jwt_private_key_pem=SecretStr(pem),
        atm_jwt_issuer="urn:lab:atm09:integration",
        atm_jwt_audience="urn:lab:atm09:integration:logout",
    )


def make_engine(jti: str, budget: Any, hook: Any = None) -> Any:
    # Cada proceso construye su propio motor; no hereda pools ni conexiones.
    cfg = get_settings().model_copy(update={"db_connection_timeout": 5})
    if (
        os.getenv("ATM09_EXPECTED_DATABASE") != "SeguridadDB"
        or not os.getenv("ATM09_EXPECTED_SQL_SERVER")
        or os.getenv("ATM09_EXPECTED_SQL_SERVER") != cfg.seguridad_db_server
    ):
        raise RuntimeError("Destino no confirmado explícitamente")
    if cfg.seguridad_db_name != "SeguridadDB":
        raise RuntimeError("Base inesperada")
    if (
        cfg.db_encrypt.lower() != "yes"
        or cfg.db_trust_server_certificate.lower() != "no"
    ):
        raise RuntimeError("Se requiere TLS con validación del certificado SQL")
    engine = create_engine(
        URL.create(
            "mssql+pyodbc",
            query={"odbc_connect": cfg.odbc_connection_string("seguridad")},
        ),
        poolclass=NullPool,
        hide_parameters=True,
        echo=False,
    )

    @event.listens_for(engine, "connect")
    def timeouts(dbapi: Any, _record: Any) -> None:
        dbapi.timeout = 10
        cursor = dbapi.cursor()
        try:
            cursor.execute("SET LOCK_TIMEOUT 4000")
        finally:
            cursor.close()

    try:
        with engine.connect() as conn:
            state = (
                conn.execute(
                    text("""
                    SELECT DB_NAME() AS db,
                    HAS_PERMS_BY_NAME(N'Seguridad.SesionesATMRevocadas',
                        N'OBJECT', N'SELECT') AS can_read,
                    HAS_PERMS_BY_NAME(N'Seguridad.SesionesATMRevocadas',
                        N'OBJECT', N'INSERT') AS can_insert,
                    (SELECT COUNT(*) FROM sys.triggers WHERE parent_id =
                        OBJECT_ID(N'Seguridad.SesionesATMRevocadas')) AS triggers
                """)
                )
                .mappings()
                .one()
            )
            if (
                state["db"] != "SeguridadDB"
                or state["can_read"] != 1
                or state["can_insert"] != 1
                or state["triggers"] != 0
            ):
                raise RuntimeError("Precondiciones SQL inesperadas")
            columns = conn.execute(
                text("""
                    SELECT c.name, t.name AS tipo, c.is_nullable, c.scale
                    FROM sys.columns c JOIN sys.types t
                        ON t.user_type_id = c.user_type_id
                    WHERE c.object_id = OBJECT_ID(N'Seguridad.SesionesATMRevocadas')
                    ORDER BY c.column_id
                """)
            ).all()
            if [tuple(row) for row in columns] != [
                ("Jti", "uniqueidentifier", False, 0),
                ("FechaRevocacion", "datetime2", False, 7),
                ("FechaExpiracion", "datetime2", False, 0),
            ]:
                raise RuntimeError("Estructura SQL inesperada")
            primary = (
                conn.execute(
                    text("""
                    SELECT c.name FROM sys.indexes i
                    JOIN sys.index_columns ic
                      ON ic.object_id = i.object_id AND ic.index_id = i.index_id
                    JOIN sys.columns c
                      ON c.object_id = ic.object_id AND c.column_id = ic.column_id
                    WHERE i.object_id = OBJECT_ID(N'Seguridad.SesionesATMRevocadas')
                      AND i.is_primary_key = 1 AND ic.key_ordinal > 0
                """)
                )
                .scalars()
                .all()
            )
            if primary != ["Jti"]:
                raise RuntimeError("Clave primaria inesperada")
    except Exception:  # noqa: BLE001 -- frontera: nunca exponer DSN ni secretos SQL
        engine.dispose()
        raise RuntimeError("Preflight SQL fallido; no ejecutar logout") from None

    @event.listens_for(engine, "before_cursor_execute")
    def guard(
        _conn: Any,
        _cursor: Any,
        statement: str,
        params: Any,
        _context: Any,
        many: bool,
    ) -> None:
        normalized = " ".join(statement.split()).lower()
        if normalized not in {READ, LOCK, INSERT, ROWS}:
            raise RuntimeError("SQL fuera del alcance autorizado")
        if many or not params or str(params[0]) != jti:
            raise RuntimeError("Jti fuera del alcance autorizado")
        if len(params) != (2 if normalized == INSERT else 1):
            raise RuntimeError("Número inesperado de parámetros")
        if normalized == INSERT:
            with budget.get_lock():
                if budget.value != 0:
                    raise RuntimeError("Segundo INSERT prohibido; detener prueba")
                budget.value += 1
        if hook:
            hook("before", normalized)

    @event.listens_for(engine, "after_cursor_execute")
    def after(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _params: Any,
        _context: Any,
        _many: bool,
    ) -> None:
        if hook:
            hook("after", " ".join(statement.split()).lower())

    return engine


@contextmanager
def client(engine: Any, pem: str):
    def only_security(name: str) -> Any:
        if name != "seguridad":
            raise RuntimeError("Base no autorizada")
        return engine

    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")

    @app.get("/lab/protected", dependencies=[Depends(session.require_sesion_atm)])
    def protected():
        return {"ok": True}

    with (
        patch.object(session, "get_settings", return_value=jwt_settings(pem)),
        patch.object(session, "get_engine", side_effect=only_security),
        TestClient(app, base_url="https://testserver") as http,
    ):
        yield http


def snapshot(engine: Any, jti: str) -> list[tuple[Any, ...]]:
    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(ROW_SQL), {"jti": jti})]


def request(http: TestClient, token: str, operation: str) -> int:
    headers = {"Authorization": "Bearer " + token}
    if operation == "logout":
        response = http.post("/api/v1/atm/logout", headers=headers)
        if response.status_code == 204 and response.content:
            raise RuntimeError("204 con cuerpo inesperado")
    else:
        response = http.get("/lab/protected", headers=headers)
    return response.status_code


def worker(
    pipe: Any,
    budget: Any,
    jti: str,
    pem: str,
    token: str,
    mode: str,
    locked: Any,
    attempted: Any,
    completed: Any,
) -> None:
    """Proceso spawn: no imprimir excepciones, tokens ni parámetros SQL."""
    logging.disable(logging.CRITICAL)
    engine = None
    timer = threading.Timer(DEADLINE, lambda: os._exit(2))
    timer.daemon = True
    timer.start()

    def hook(phase: str, sql: str) -> None:
        if mode == "first" and phase == "after" and sql == LOCK:
            locked.set()
            if not attempted.wait(3):
                raise RuntimeError("Segundo proceso no inició la consulta")
            if completed.wait(0.3):
                raise RuntimeError("Segunda consulta no esperó al lock")
        if mode == "second" and sql == LOCK:
            if phase == "before":
                if not locked.wait(3):
                    raise RuntimeError("Primer proceso no adquirió el lock")
                attempted.set()
            else:
                completed.set()

    try:
        engine = make_engine(jti, budget, hook if mode != "sequential" else None)
        with client(engine, pem) as http:
            pipe.send(("ready", os.getpid()))
            while pipe.poll(DEADLINE):
                command = pipe.recv()
                if command == "stop":
                    return
                if command not in {"logout", "check"}:
                    raise RuntimeError("Comando no autorizado")
                pipe.send(("status", request(http, token, command)))
            raise TimeoutError("Coordinador inactivo")
    except Exception:  # noqa: BLE001 -- IPC solo transmite errores sanitizados
        pipe.send(("error", "Prueba detenida; no reintentar automáticamente"))
    finally:
        timer.cancel()
        if engine is not None:
            engine.dispose()
        pipe.close()


def receive(pipe: Any, expected: str) -> Any:
    if not pipe.poll(DEADLINE):
        raise RuntimeError("Tiempo máximo excedido; no reintentar")
    kind, value = pipe.recv()
    if kind != expected:
        raise RuntimeError("Proceso de prueba detenido; no reintentar")
    return value


def run(mode: str) -> None:
    import multiprocessing

    # Los hijos tienen límite duro; todas las esperas del coordinador son acotadas.
    logging_before = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    ctx = multiprocessing.get_context("spawn")
    budget = ctx.Value("i", 0)
    locked, attempted, completed = ctx.Event(), ctx.Event(), ctx.Event()
    children: list[Any] = []
    pipes: list[Any] = []
    engine = None
    try:
        pem, token, jti, expiry = laboratory_session()
        print(f"ATM09 laboratorio: inicio modo={mode} jti={jti}; sin reintentos")
        engine = make_engine(jti, budget)
        if snapshot(engine, jti):
            raise RuntimeError("Jti ya existente; no continuar")
        for role in ["first", "second"] if mode == "concurrent" else ["sequential"] * 2:
            parent, child = ctx.Pipe()
            process = ctx.Process(
                target=worker,
                args=(
                    child,
                    budget,
                    jti,
                    pem,
                    token,
                    role,
                    locked,
                    attempted,
                    completed,
                ),
            )
            process.start()
            child.close()
            children.append(process)
            pipes.append(parent)
        pids = [receive(pipe, "ready") for pipe in pipes]
        if len(set(pids)) != 2 or os.getpid() in pids:
            raise RuntimeError("No hay dos procesos independientes")
        if mode == "concurrent":
            for pipe in pipes:
                pipe.send("logout")
            if [receive(pipe, "status") for pipe in pipes] != [204, 204]:
                raise RuntimeError("Logout concurrente inesperado")
            if not (locked.is_set() and attempted.is_set() and completed.is_set()):
                raise RuntimeError("Solapamiento no demostrado")
        else:
            pipes[1].send("check")
            if receive(pipes[1], "status") != 200:
                raise RuntimeError("Sesión inicial no aceptada")
            pipes[0].send("logout")
            if receive(pipes[0], "status") != 204:
                raise RuntimeError("Primera revocación fallida")
            initial = snapshot(engine, jti)
            pipes[1].send("check")
            if receive(pipes[1], "status") != 401:
                raise RuntimeError("Revocación no visible en proceso B")
            pipes[1].send("logout")
            if receive(pipes[1], "status") != 204:
                raise RuntimeError("Logout repetido fallido")
            if snapshot(engine, jti) != initial:
                raise RuntimeError("Fechas modificadas")
        rows = snapshot(engine, jti)
        if len(rows) != 1 or rows[0][2] != expiry or budget.value != 1:
            raise RuntimeError("Persistencia inesperada")
        print(f"ATM09 laboratorio: modo={mode} jti={jti} filas=1 procesos=2")
    except Exception:  # noqa: BLE001 -- no propagar excepciones con parámetros SQL
        raise RuntimeError(
            "ATM09 detenida: resultado ambiguo o inesperado. "
            "Puede existir una fila ficticia; no reintentar automáticamente."
        ) from None
    finally:
        for pipe, process in zip(pipes, children, strict=True):
            if process.is_alive():
                try:
                    pipe.send("stop")
                except (BrokenPipeError, EOFError, OSError):
                    pass
            process.join(timeout=2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            pipe.close()
        if engine is not None:
            engine.dispose()
        logging.disable(logging_before)
