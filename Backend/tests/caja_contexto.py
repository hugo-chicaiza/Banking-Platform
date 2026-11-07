"""Apoyo de pruebas de Caja y Transacciones (sin BD).

La sesión se simula sobrescribiendo `usuario_actual`, la dependencia real
de la que cuelgan `UsuarioActual` y `require_roles`.

El vínculo interno se simula sobrescribiendo `resolver_id_interno`.

Solo en pruebas: la aplicación real exige sesión WorkOS y, mientras no
exista el vínculo D-01, responde 403 donde corresponda.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.core.api.middleware import TraceIdMiddleware
from app.core.database.db import cooperativa
from app.core.security import audit
from app.core.security.auth import Usuario, usuario_actual
from app.core.security.operador import resolver_id_interno
from app.modules.caja import repository as caja_repo

BASE = "/api/v1/caja"

ID_CAJERO = 7
ID_SUPERVISOR = 9


def usuario(
    *roles: str,
    agencia: str | None = "001",
) -> Usuario:
    """Crea un usuario simulado con los roles indicados."""
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
    """Contexto compartido para pruebas unitarias de Caja."""

    def __init__(
        self,
        app: FastAPI,
        monkeypatch: pytest.MonkeyPatch,
        modulo: Any = caja_repo,
    ) -> None:
        self.modulo = modulo
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

        monkeypatch.setattr(
            audit,
            "registrar",
            self.eventos.append,
        )

    def como(
        self,
        *roles: str,
        id_interno: int | None = None,
        agencia: str = "001",
    ):
        """Cambia el usuario y su identificador interno."""
        self.usuario = usuario(
            *roles,
            agencia=agencia,
        )
        self.id_interno = id_interno
        return self

    def sin_sesion(self) -> None:
        """Elimina las simulaciones de autenticación."""
        del self.app.dependency_overrides[usuario_actual]
        del self.app.dependency_overrides[resolver_id_interno]

    def fake(
        self,
        nombre: str,
        resultado: Any = None,
        modulo: Any = None,
    ) -> None:
        """Reemplaza una función del repositorio y registra sus argumentos."""
        llamadas = self.llamadas.setdefault(nombre, [])

        def falso(
            *args: Any,
            **kwargs: Any,
        ) -> Any:
            llamadas.append(args[1:])

            if isinstance(resultado, BaseException):
                raise resultado

            if callable(resultado):
                return resultado(*args)

            return resultado

        self.monkeypatch.setattr(
            modulo or self.modulo,
            nombre,
            falso,
        )

    def resultado_auditoria(self) -> str | None:
        """Devuelve el resultado del último evento de auditoría."""
        if not self.eventos:
            return None

        return self.eventos[-1].resultado


def crear_contexto(
    monkeypatch: pytest.MonkeyPatch,
    router: APIRouter,
    modulo: Any = caja_repo,
    roles: tuple[str, ...] = ("CAJERO",),
    id_interno: int | None = ID_CAJERO,
) -> Contexto:
    """Construye una aplicación FastAPI aislada para pruebas."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.add_middleware(TraceIdMiddleware)

    ctx = Contexto(
        app,
        monkeypatch,
        modulo,
    )

    ctx.usuario = usuario(*roles)
    ctx.id_interno = id_interno

    return ctx


def code(respuesta: Any) -> str:
    """Obtiene el código de error de una respuesta."""
    return respuesta.json()["code"]


def error_bd(numero: int) -> DBAPIError:
    """Simula un error de SQL Server."""
    return DBAPIError(
        "EXEC ...",
        None,
        Exception(f"[SQL Server]Regla. ({numero}) (SQLExecDirectW)"),
    )


# ============================================================
# Datos simulados
# ============================================================

CAJA = {
    "IdCajaFisica": 3,
    "IdAgencia": "001",
    "CodigoCaja": "C01",
    "Estado": True,
    "DescripcionEstado": None,
    "LimiteEfectivoCaja": Decimal("5000.00"),
}


JORNADA = {
    "IdJornadaCaja": 55,
    "IdUsuario": ID_CAJERO,
    "IdCajaFisica": 3,
    "IdAgencia": "001",
    "FechaHoraApertura": datetime(2026, 11, 4, 8, 30),
    "FechaHoraCierre": None,
    "DineroInicial": Decimal("100.50"),
    "Estado": "ABIERTA",
    "Observacion": None,
}


DOTACION = {
    "IdDotacionCaja": 801,
    "IdJornadaCaja": 55,
    "IdBoveda": 2,
    "TipoDotacion": "INICIAL",
    "Monto": Decimal("100.50"),
    "IdMovimientoBoveda": 9001,
    "Estado": "REGISTRADA",
    "AutorizadoPor": ID_SUPERVISOR,
}


MOVIMIENTO = {
    "IdMovimientoCaja": 1,
    "IdTransaccion": 5001,
    "IdJornadaCaja": 55,
    "IdTipoMovimiento": 2,
    "CodigoTipoMovimiento": "DEP",
    "Naturaleza": "I",
    "Monto": Decimal("20.00"),
    "FechaHora": datetime(2026, 11, 4, 9, 0),
    "Observacion": None,
    "IdAsientoContable": None,
}


TOTALES = {
    "SaldoInicial": Decimal("100.00"),
    "TotalDotaciones": Decimal("50.00"),
    "TotalDepositos": Decimal("30.00"),
    "TotalPagos": Decimal("0.00"),
    "TotalRetiros": Decimal("30.00"),
    "TotalDevolucionesBoveda": Decimal("0.00"),
}


CUADRE = {
    "IdCuadreCaja": 70,
    "IdJornadaCaja": 55,
    "IdUsuario": ID_CAJERO,
    "FechaHoraCuadre": datetime(2026, 11, 4, 17, 0),
    **TOTALES,
    "SaldoFinalFisico": None,
    "DiferenciaDinero": None,
    "EstadoCuadre": "PENDIENTE",
    "IdAutorizadoPor": None,
    "IdFechaContable": 20261104,
    "Observaciones": None,
}


TRANSACCION = {
    "IdTransaccion": 5001,
    "NumeroComprobante": "COMP-000123",
    "RegistroUnico": "A1B2C3D4E5F6",
    "MTI": "0200",
    "STAN": "000001",
    "RRN": "000000000001",
    "TipoOperacion": "Normal",
    "TipoTransaccion": "Deposito",
    "IdCuenta": 501,
    "IdCuentaDestino": None,
    "IdTarjeta": None,
    "IdCanal": 4,
    "IdTerminal": None,
    "IdAgencia": "001",
    "IdJornadaCaja": 55,
    "IdTransaccionRelacionada": None,
    "Monto": Decimal("150.00"),
    "CodigoRespuesta": "00",
    "Estado": "Completada",
    "IdFechaContable": 20261104,
    "FechaHoraSistema": datetime(2026, 11, 4, 10, 15),
    "CreadoPor": ID_CAJERO,
    "NumeroAutorizacion": "123456",
    "AgenciaOperacion": "001",
}


# ============================================================
# Funciones reutilizables para datos de prueba
# ============================================================


def crear_registro(
    base: dict[str, Any],
    **cambios: Any,
) -> dict[str, Any]:
    """Crea una copia de un registro con los campos modificados."""
    return {**base, **cambios}


def jornada(**cambios: Any) -> dict[str, Any]:
    """Genera una jornada de prueba."""
    return crear_registro(JORNADA, **cambios)


def cuadre(**cambios: Any) -> dict[str, Any]:
    """Genera un cuadre de prueba."""
    return crear_registro(CUADRE, **cambios)
