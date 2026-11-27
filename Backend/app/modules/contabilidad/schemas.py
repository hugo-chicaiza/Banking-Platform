from datetime import date, time
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints

from app.core.api.schemas import CamelModel, Money

# CON-01 / CON-02 · Fecha contable


class FechaContable(CamelModel):
    """Una fila del calendario contable (Contabilidad.FechaContable)."""

    id_fecha_contable: int
    fecha: date
    es_dia_contable: bool
    es_feriado: bool
    es_fin_de_semana: bool
    hora_corte: time  # se serializa como HH:mm:ss


# CON-03 · Plan de cuentas (CUC)


class CuentaContable(CamelModel):
    """Una cuenta del plan de cuentas (Contabilidad.CuentasContables)."""

    id_cuenta_contable: int
    codigo_cuenta: str
    nombre_cuenta: str
    naturaleza: str  # "DEUDORA" o "ACREEDORA"
    tipo_cuenta: str
    id_cuenta_superior: int | None  # None en las cuentas de primer nivel
    es_imputable: bool  # solo las imputables reciben movimientos
    # E4-04: solo recibe asientos automáticos (no se usa en un asiento manual)
    solo_automatica: bool
    saldo: Money
    estado: str


# CON-04 / CON-05 · Asientos contables

INT32_MAX = 2_147_483_647


# #206 · Alta, edición, estado y baja de cuentas contables (contrato)
# Tamaños tomados de la base de desarrollo: CodigoCuenta varchar(30), solo dígitos
# en los datos actuales; NombreCuenta varchar(150).

CodigoCuenta = Annotated[str, StringConstraints(pattern=r"^[0-9]{1,30}$")]
NombreCuenta = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
]


class CuentaContableCrear(CamelModel):
    """Alta de una cuenta. El código debe empezar con el del padre (422
    CODIGO_NO_CORRESPONDE_AL_PADRE); la naturaleza y el tipo salen del padre."""

    model_config = ConfigDict(extra="forbid")

    codigo_cuenta: CodigoCuenta
    nombre_cuenta: NombreCuenta
    id_cuenta_superior: Annotated[int, Field(strict=True, ge=1, le=INT32_MAX)]
    es_imputable: Annotated[bool, Field(strict=True)]


class CuentaContableEditar(CamelModel):
    """Solo el nombre es editable; el código y la jerarquía no cambian."""

    model_config = ConfigDict(extra="forbid")

    nombre_cuenta: NombreCuenta


class CuentaContableEstado(CamelModel):
    """Mismos textos que publica CON-03 a partir del bit Estado."""

    model_config = ConfigDict(extra="forbid")

    estado: Literal["Activo", "Inactivo"]


class MovimientoAsiento(CamelModel):
    """Una línea del asiento (Contabilidad.MovimientosContables)."""

    id_movimiento_contable: int
    id_cuenta_contable: int
    codigo_cuenta: str
    tipo_movimiento: str  # "DEBITO" o "CREDITO"
    monto: Money
    id_transaccion: int | None
    id_agencia: str | None


class Asiento(CamelModel):
    """Cabecera de Contabilidad.AsientoContable con su detalle.

    En CON-04 `detalle` va vacío; el detalle completo se pide a CON-05.
    """

    id_asiento_contable: int
    numero_asiento: str
    fecha_asiento: date
    id_tipo_asiento: int
    origen: str
    concepto: str
    total_debito: Money
    total_credito: Money
    estado: str
    id_asiento_reversion: int | None
    id_agencia: str
    detalle: list[MovimientoAsiento]


class PageAsiento(CamelModel):
    items: list[Asiento]
    page: int
    page_size: int
    total: int


# E4-04 (#383) · Asientos manuales con aprobación y reverso (contrato)
# Tamaños tomados de la base de desarrollo: AsientoContable.Concepto varchar(500),
# IdAgencia char(3); MovimientosContables.Monto decimal(18,2) con CHECK Monto > 0 y
# TipoMovimiento DEBITO/CREDITO. El concepto se limita a 200 (provisional).
# El borrador puede guardarse incompleto: "al menos dos líneas, débitos = créditos,
# cuentas activas e imputables, día y mes abiertos" se validan al enviarlo.

MAX_CONCEPTO_ASIENTO = 200
MAX_MOTIVO_ASIENTO = 300
MAX_LINEAS_ASIENTO = 100  # provisional: tope del cuerpo, no regla contable

ConceptoAsiento = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_CONCEPTO_ASIENTO
    ),
]
MotivoAsiento = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_MOTIVO_ASIENTO
    ),
]
MontoLinea = Annotated[
    Money,
    Field(
        gt=0,
        max_digits=18,
        decimal_places=2,
        description="Mayor que 0, con hasta 2 decimales (decimal(18,2)).",
    ),
]


class LineaAsientoManual(CamelModel):
    """Una línea del borrador; la cuenta se valida (activa, imputable, no solo
    automática) al enviar el asiento."""

    model_config = ConfigDict(extra="forbid")

    id_cuenta_contable: Annotated[int, Field(strict=True, ge=1, le=INT32_MAX)]
    tipo_movimiento: Literal["DEBITO", "CREDITO"]
    monto: MontoLinea


class AsientoManual(CamelModel):
    """Cuerpo de POST /asientos y PUT /asientos/{idAsiento}: el borrador completo."""

    model_config = ConfigDict(extra="forbid")

    concepto: ConceptoAsiento
    id_agencia: Annotated[str, StringConstraints(pattern=r"^[0-9]{3}$")]
    lineas: Annotated[list[LineaAsientoManual], Field(max_length=MAX_LINEAS_ASIENTO)]


class AsientoManualCreado(CamelModel):
    """201 de POST /asientos: el asiento queda en BORRADOR."""

    id_asiento_contable: int


class MotivoAsientoManual(CamelModel):
    """Cuerpo de la anulación de un borrador y del reverso de un asiento manual."""

    model_config = ConfigDict(extra="forbid")

    motivo: MotivoAsiento
