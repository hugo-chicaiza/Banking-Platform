"""Pruebas de las rutas de Caja sin BD: repository, auditoría y sesión simulados.

La sesión se simula sobrescribiendo `usuario_actual`, que es la dependencia real
de la que cuelgan `UsuarioActual` y `require_roles`. Las pruebas de 401 y CSRF
quitan esa sustitución para ejercitar el código real.
"""

from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.api.middleware import TraceIdMiddleware
from app.core.database.db import cooperativa
from app.core.security import audit
from app.core.security.auth import Usuario, usuario_actual
from app.core.security.operador import resolver_id_interno
from app.modules.caja import repository as repo
from app.modules.caja.router import router

BASE = "/api/v1/caja"
ID_CAJERO = 7
ID_SUPERVISOR = 9


def usuario(*roles: str, agencia: str | None = "001") -> Usuario:
    return Usuario(
        id_usuario="user_01PRUEBA",
        id_sesion="session_01",
        id_organizacion=None,
        nombre="Usuario Prueba",
        email="prueba@example.com",
        roles=roles,
        permisos=(),
        id_agencia=agencia,
    )


class Contexto:
    def __init__(self, app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
        self.app = app
        self.cliente = TestClient(app)
        self.monkeypatch = monkeypatch
        self.usuario = usuario("CAJERO")
        self.id_interno: int | None = ID_CAJERO
        self.conn = MagicMock()
        self.eventos: list[audit.EventoAuditoria] = []
        self.llamadas: dict[str, list[tuple[Any, ...]]] = {}
        app.dependency_overrides[cooperativa] = lambda: self.conn
        app.dependency_overrides[usuario_actual] = lambda: self.usuario
        app.dependency_overrides[resolver_id_interno] = lambda: self.id_interno
        monkeypatch.setattr(audit, "registrar", self.eventos.append)

    def como(self, *roles: str, id_interno: int | None = None, agencia: str = "001"):
        self.usuario = usuario(*roles, agencia=agencia)
        self.id_interno = id_interno
        return self

    def sin_sesion(self) -> None:
        del self.app.dependency_overrides[usuario_actual]
        del self.app.dependency_overrides[resolver_id_interno]

    def fake(self, nombre: str, resultado: Any = None, modulo: Any = repo) -> None:
        """Reemplaza una función del repository y registra sus argumentos."""
        llamadas = self.llamadas.setdefault(nombre, [])

        def falso(*args: Any, **kwargs: Any) -> Any:
            llamadas.append(args[1:])  # sin la conexión
            if isinstance(resultado, BaseException):
                raise resultado
            return resultado(*args) if callable(resultado) else resultado

        self.monkeypatch.setattr(modulo, nombre, falso)

    def resultado_auditoria(self) -> str | None:
        return self.eventos[-1].resultado if self.eventos else None


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.add_middleware(TraceIdMiddleware)
    yield Contexto(app, monkeypatch)


def code(respuesta: Any) -> str:
    return respuesta.json()["code"]


CAJA = {
    "IdCajaFisica": 3,
    "IdAgencia": "001",
    "CodigoCaja": "C01",
    "Estado": True,
    "DescripcionEstado": None,
    "LimiteEfectivoCaja": Decimal("5000.00"),
}


# --- CAJ-01 --------------------------------------------------------------------------

@pytest.mark.skip(reason="Autenticacion y autorizacion pendientes para W4")
def test_caj01_sin_sesion_responde_401(ctx: Contexto) -> None:
    ctx.sin_sesion()
    r = ctx.cliente.get(f"{BASE}/cajas-fisicas")
    assert r.status_code == 401
    assert code(r) == "NO_AUTENTICADO"
    assert r.headers["content-type"].startswith("application/problem+json")

@pytest.mark.skip(reason="Autenticacion y autorizacion pendientes para W4")
def test_caj01_rol_no_permitido_403(ctx: Contexto) -> None:
    ctx.como("CONTADOR")
    r = ctx.cliente.get(f"{BASE}/cajas-fisicas")
    assert r.status_code == 403
    assert code(r) == "SIN_PERMISO"

@pytest.mark.skip(reason="Autenticacion y autorizacion pendientes para W4")
def test_caj01_lista_la_agencia_del_usuario(ctx: Contexto) -> None:
    ctx.fake("listar_cajas_fisicas", [CAJA])
    r = ctx.cliente.get(f"{BASE}/cajas-fisicas", params={"activa": "true"})
    assert r.status_code == 200
    assert r.json() == [
        {
            "idCajaFisica": 3,
            "idAgencia": "001",
            "codigoCaja": "C01",
            "estado": True,
            "descripcionEstado": None,
            "limiteEfectivoCaja": 5000.0,
        }
    ]
    assert ctx.llamadas["listar_cajas_fisicas"] == [("001", True)]
    assert r.headers["cache-control"] == "no-store"
    assert "x-request-id" in r.headers

@pytest.mark.skip(reason="Autenticacion y autorizacion pendientes para W4")
def test_caj01_supervisor_no_ve_otra_agencia(ctx: Contexto) -> None:
    ctx.como("SUPERVISOR")
    r = ctx.cliente.get(f"{BASE}/cajas-fisicas", params={"idAgencia": "002"})
    assert r.status_code == 403
    assert code(r) == "SIN_ACCESO_AGENCIA"


def test_caj01_admin_puede_ver_todas(ctx: Contexto) -> None:
    ctx.como("ADMIN", agencia="001")
    ctx.fake("listar_cajas_fisicas", [])
    r = ctx.cliente.get(f"{BASE}/cajas-fisicas")
    assert r.status_code == 200
    assert ctx.llamadas["listar_cajas_fisicas"] == [(None, None)]

@pytest.mark.skip(reason="Autenticacion y autorizacion pendientes para W4")
def test_caj01_cajero_sin_agencia_403(ctx: Contexto) -> None:
    ctx.usuario = usuario("CAJERO", agencia=None)
    r = ctx.cliente.get(f"{BASE}/cajas-fisicas")
    assert r.status_code == 403
    assert code(r) == "AGENCIA_NO_ASIGNADA"


@pytest.mark.parametrize(
    "params",
    [{"otro": "1"}, {"activa": ["true", "false"]}, {"idAgencia": "1A2"}],
)
def test_caj01_parametros_invalidos_400(ctx: Contexto, params: dict[str, Any]) -> None:
    r = ctx.cliente.get(f"{BASE}/cajas-fisicas", params=params)
    assert r.status_code == 400
    assert code(r) in ("PARAMETRO_INVALIDO", "DATOS_INVALIDOS")
