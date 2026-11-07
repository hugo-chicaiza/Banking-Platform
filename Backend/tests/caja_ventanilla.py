"""Apoyo de pruebas de ventanilla (CAJ-09, CAJ-11): dependencias contables falsas."""

from decimal import Decimal
from typing import Any

from app.modules.transacciones import repository as trx_repo
from app.modules.transacciones.dependencias import (
    DatosAsiento,
    Numeracion,
    dependencias_operacion,
)
from tests.caja_contexto import JORNADA, TRANSACCION, Contexto

CUERPO_DEPOSITO = {
    "idCuenta": 501,
    "monto": 150.0,
    "registroUnico": "A1B2C3D4E5F6",
    "desglose": [{"idDenominacion": 1, "cantidad": 3}],
}


class DependenciasFalsas:
    """Configuración de prueba de las brechas G-06/G-11 (no es la real)."""

    def __init__(self) -> None:
        self.asientos: list[DatosAsiento] = []
        self.comisiones: list[tuple[int, Decimal]] = []
        self.revertidas: list[tuple[int, int]] = []

    def verificar_habilitadas(self) -> None:
        return None

    @property
    def id_canal_ventanilla(self) -> int:
        return 4

    @property
    def codigo_pais_origen(self) -> str:
        return "ECU"

    def codigo_tipo_movimiento_caja(
        self, tipo_transaccion: str, naturaleza: str
    ) -> str:
        return f"{tipo_transaccion[:3].upper()}_{naturaleza}"

    def numerar(
        self, conn: Any, tipo_transaccion: str, tipo_operacion: str
    ) -> Numeracion:
        return Numeracion(
            "COMP-000123",
            "000123",
            "210000",
            "000001",
            "000000000001",
            "123456",
            "REV000000001",
        )

    def contabilizar(self, conn: Any, datos: DatosAsiento) -> int | None:
        self.asientos.append(datos)
        return 777

    def registrar_comision(
        self, conn: Any, id_transaccion: int, monto: Decimal
    ) -> None:
        self.comisiones.append((id_transaccion, monto))

    def revertir_comisiones(self, conn: Any, id_original: int, id_reverso: int) -> None:
        self.revertidas.append((id_original, id_reverso))


def preparar_ventanilla(ctx: Contexto, tipo: str = "Deposito") -> DependenciasFalsas:
    deps = DependenciasFalsas()
    ctx.app.dependency_overrides[dependencias_operacion] = lambda: deps
    ctx.fake("buscar_por_registro_unico", None, trx_repo)
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("dotacion_inicial_registrada", True)
    ctx.fake("obtener_cuadre_de_jornada", None)
    ctx.fake("valores_denominaciones", {1: Decimal("50.00")})
    ctx.fake(
        "obtener_cuenta",
        {
            "IdCuenta": 501,
            "IdAgencia": "001",
            "Saldo": Decimal(1000),
            "SaldoRetenido": Decimal(0),
            "Estado": "Activa",
        },
        trx_repo,
    )
    ctx.fake("id_fecha_contable", 20261104)
    ctx.fake("insertar_transaccion", 5001, trx_repo)
    ctx.fake("aplicar_movimiento_cuenta", 1, trx_repo)
    ctx.fake("id_tipo_movimiento_caja", 2, trx_repo)
    ctx.fake("insertar_movimiento_caja", None, trx_repo)
    ctx.fake("obtener_transaccion", {**TRANSACCION, "TipoTransaccion": tipo}, trx_repo)
    ctx.fake("comision_de", Decimal(0), trx_repo)
    ctx.fake("saldo_disponible", Decimal("1150.00"), trx_repo)
    return deps
