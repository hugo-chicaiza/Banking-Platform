"""Piezas que las operaciones de dinero necesitan y que la BD/negocio aún no definen.

Depósito (CAJ-09), retiro (CAJ-11) y reverso (TRX-03) solo pueden ejecutarse cuando
estén resueltas estas brechas, todas documentadas en los contratos:

- G-11: formato y generación de NumeroComprobante, Secuencial, CodigoProcesamiento,
  STAN, RRN y NumeroAutorizacion.
- G-06 / AC-01: qué cuentas contables mueve cada operación (asiento en la misma
  transacción de BD).
- Canal de ventanilla (IdCanal), código de país de origen y códigos de
  Caja.TipoMovimientoCaja para ingreso/egreso de ventanilla.
- Registro y devolución de comisiones (TransaccionComision necesita IdComision, que
  usp_AutorizarOperacion no devuelve).

Mientras `dependencias_operacion` entregue DependenciasNoConfiguradas, esas rutas
responden 501 OPERACION_NO_HABILITADA antes de tocar la BD. Para habilitarlas se
implementa una clase con este Protocol y se devuelve desde `dependencias_operacion`.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from sqlalchemy import Connection

from app.core.api.errors import problema


@dataclass(frozen=True)
class Numeracion:
    numero_comprobante: str  # varchar(30)
    secuencial: str  # char(6)
    codigo_procesamiento: str  # char(6)
    stan: str | None  # char(6)
    rrn: str | None  # char(12)
    numero_autorizacion: str | None  # char(6)
    # char(12). Solo para filas que genera el sistema (reversos); en ventanilla el
    # registroUnico lo envía el cliente para la idempotencia.
    registro_unico: str | None = None


@dataclass(frozen=True)
class DatosAsiento:
    id_transaccion: int
    tipo_transaccion: str
    tipo_operacion: str  # Normal | Reverso
    monto: Decimal
    id_agencia: str | None
    id_fecha_contable: int
    id_transaccion_original: int | None = None


class DependenciasOperacion(Protocol):
    def verificar_habilitadas(self) -> None:
        """Lanza 501 si alguna pieza no está configurada."""
        ...

    @property
    def id_canal_ventanilla(self) -> int: ...

    @property
    def codigo_pais_origen(self) -> str: ...

    def codigo_tipo_movimiento_caja(
        self, tipo_transaccion: str, naturaleza: str
    ) -> str:
        """Código de Caja.TipoMovimientoCaja; naturaleza 'I' ingreso, 'E' egreso."""
        ...

    def numerar(
        self, conn: Connection, tipo_transaccion: str, tipo_operacion: str
    ) -> Numeracion: ...

    def contabilizar(self, conn: Connection, datos: DatosAsiento) -> int | None:
        """Crea el asiento (o el inverso) en la misma transacción; devuelve su id."""
        ...

    def registrar_comision(
        self, conn: Connection, id_transaccion: int, monto: Decimal
    ) -> None: ...

    def revertir_comisiones(
        self, conn: Connection, id_original: int, id_reverso: int
    ) -> None: ...


def _no_habilitada() -> Exception:
    return problema(
        501,
        "OPERACION_NO_HABILITADA",
        "La operación aún no está habilitada en este ambiente.",
    )


class DependenciasNoConfiguradas:
    """Falla cerrada: ninguna operación de dinero corre sin las brechas resueltas."""

    def verificar_habilitadas(self) -> None:
        raise _no_habilitada()

    @property
    def id_canal_ventanilla(self) -> int:
        raise _no_habilitada()

    @property
    def codigo_pais_origen(self) -> str:
        raise _no_habilitada()

    def codigo_tipo_movimiento_caja(
        self, tipo_transaccion: str, naturaleza: str
    ) -> str:
        raise _no_habilitada()

    def numerar(
        self, conn: Connection, tipo_transaccion: str, tipo_operacion: str
    ) -> Numeracion:
        raise _no_habilitada()

    def contabilizar(self, conn: Connection, datos: DatosAsiento) -> int | None:
        raise _no_habilitada()

    def registrar_comision(
        self, conn: Connection, id_transaccion: int, monto: Decimal
    ) -> None:
        raise _no_habilitada()

    def revertir_comisiones(
        self, conn: Connection, id_original: int, id_reverso: int
    ) -> None:
        raise _no_habilitada()


def dependencias_operacion() -> DependenciasOperacion:
    """Dependencia FastAPI. Las pruebas la reemplazan con dependency_overrides."""
    return DependenciasNoConfiguradas()
