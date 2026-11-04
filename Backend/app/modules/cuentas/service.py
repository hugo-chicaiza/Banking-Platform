from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.modules.cuentas import repository
from app.modules.cuentas.schemas import (
    ID_MONEDA_USD,
    Cuenta,
    CuentaCreate,
    CuentaResumen,
    EstadoCuenta,
    PageCuenta,
    SaldoCuenta,
)

CAMPOS_ORDEN_CUENTAS = {
    "idCuenta": "IdCuenta",
    "numeroCuenta": "NumeroCuenta",
    "idCliente": "IdCliente",
    "idProducto": "IdProducto",
    "idAgencia": "IdAgencia",
    "tipoCuenta": "TipoCuenta",
    "estado": "Estado",
}


def _orden_cuentas(sort: str | None) -> tuple[str, str]:
    if sort is None:
        return "IdCuenta", "asc"
    partes = sort.split(",")
    if (
        len(partes) != 2
        or partes[0] not in CAMPOS_ORDEN_CUENTAS
        or partes[1] not in ("asc", "desc")
    ):
        raise problema(
            400, "SORT_INVALIDO", "Use un campo permitido y la dirección asc o desc."
        )
    return CAMPOS_ORDEN_CUENTAS[partes[0]], partes[1]


def listar_cuentas(
    conn: Connection,
    *,
    id_cliente: int | None = None,
    numero_cuenta: str | None = None,
    estado: EstadoCuenta | None = None,
    id_agencia: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort: str | None = None,
) -> PageCuenta:
    """Consulta paginada con filtros combinados y orden seguro (CTA-02)."""
    campo, direccion = _orden_cuentas(sort)
    filas, total = repository.consultar_cuentas(
        conn,
        id_cliente=id_cliente,
        numero_cuenta=numero_cuenta,
        estado=estado,
        id_agencia=id_agencia,
        page=page,
        page_size=page_size,
        campo=campo,
        direccion=direccion,
    )
    return PageCuenta(
        items=[CuentaResumen(**fila) for fila in filas],
        page=page,
        page_size=page_size,
        total=total,
    )


def obtener_cuenta(conn: Connection, id_cuenta: int) -> Cuenta:
    """Lectura única compartida por detalle y saldo, sin filtrar estados."""
    fila = repository.obtener_cuenta_por_id(conn, id_cuenta)
    if fila is None:
        raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe.")
    # Regla global aprobada: todas las cuentas operan en USD. No se persiste por fila.
    return Cuenta(**{**fila, "id_moneda": ID_MONEDA_USD})


def obtener_saldo(conn: Connection, id_cuenta: int) -> SaldoCuenta:
    """Calcula el disponible sin modificar los importes persistidos (CTA-04)."""
    cuenta = obtener_cuenta(conn, id_cuenta)
    saldo = cuenta.saldo
    retenido = cuenta.saldo_retenido
    if cuenta.estado == "CERRADA":
        saldo = retenido = Decimal("0.00")
    return SaldoCuenta(
        id_cuenta=cuenta.id_cuenta,
        saldo=saldo,
        saldo_retenido=retenido,
        saldo_disponible=saldo - retenido,
        id_moneda=cuenta.id_moneda,
        fecha_consulta=datetime.now(UTC),
    )


# Generación de NumeroCuenta

# Formato acordado mientras se resuelve G-11 con negocio:
# prefijo de tipo (AH / CC) + secuencial de 8 dígitos.
# Ejemplo: AH00000501. Único garantizado por UQ_Cuenta_Numero.
_PREFIJOS: dict[str, str] = {"Ahorro": "AH", "Corriente": "CC"}


def _generar_numero_cuenta(conn: Connection, tipo_cuenta: str) -> str:
    """Genera el próximo NumeroCuenta libre.

    La lectura toma un bloqueo de rango hasta el commit para serializar aperturas
    del mismo prefijo. La unicidad final la garantiza UQ_Cuenta_Numero.
    """
    prefijo = _PREFIJOS.get(tipo_cuenta, "XX")
    patron = f"{prefijo}%"

    from sqlalchemy import text

    ultimo = conn.execute(
        text(
            """
            SELECT ISNULL(MAX(TRY_CONVERT(
                       bigint, SUBSTRING(NumeroCuenta, 3, LEN(NumeroCuenta))
                   )), 0) AS ultimo
            FROM Cuentas.Cuenta WITH (UPDLOCK, HOLDLOCK)
            WHERE NumeroCuenta LIKE :patron
            """
        ),
        {"patron": patron},
    ).scalar_one()
    return f"{prefijo}{str(ultimo + 1).zfill(8)}"


# CTA-01 · Apertura de cuenta


def abrir_cuenta(
    conn: Connection,
    payload: CuentaCreate,
    creado_por: int,
) -> Cuenta:
    """Ejecuta las validaciones previas y llama al repositorio.

    Raises:
        HTTPException 409 CLIENTE_NO_ACTIVO
        HTTPException 409 RIESGO_RECHAZADO
        HTTPException 422 PRODUCTO_NO_ES_CUENTA
        HTTPException 409 AGENCIA_INACTIVA
    """
    # 1. Cliente existe y está Activo
    cliente = repository.obtener_cliente(conn, payload.id_cliente)
    if cliente is None or cliente["estado"] != "Activo":
        raise problema(409, "CLIENTE_NO_ACTIVO", "El cliente no está Activo.")

    # 2. Riesgo vigente no rechazado
    riesgo = repository.obtener_riesgo_vigente(conn, payload.id_cliente)
    if riesgo is not None and riesgo["estado"] == "Rechazado":
        raise problema(
            409, "RIESGO_RECHAZADO", "El cliente tiene riesgo vigente rechazado."
        )

    # 3. Subproducto y producto padre existen, son de Cuenta y están activos.
    producto = repository.obtener_subproducto(conn, payload.id_sub_producto)
    if (
        producto is None
        or producto["tipo_producto"] != "Cuenta"
        or producto["estado_producto"] != "A"
        or producto["estado_subproducto"] != "A"
    ):
        raise problema(
            422,
            "PRODUCTO_NO_ES_CUENTA",
            "El subproducto no corresponde a una cuenta activa.",
        )

    # 4. Monto de apertura cubre el mínimo; el SP repite esta validación.
    monto_minimo = producto["monto_apertura_minimo"] or Decimal("0.00")
    if payload.monto_inicial < monto_minimo:
        raise problema(
            422,
            "MONTO_APERTURA_INSUFICIENTE",
            "El monto inicial no cubre el mínimo de apertura.",
        )

    # 5. Agencia existe y está activa
    agencia = repository.obtener_agencia(conn, payload.id_agencia)
    if agencia is None or agencia["estado"] != "A":
        raise problema(
            409, "AGENCIA_INACTIVA", "La agencia no existe o no está activa."
        )

    # 6. Generar NumeroCuenta
    numero_cuenta = _generar_numero_cuenta(conn, producto["tipo_cuenta"])

    # 7. Ejecutar la firma real del SP y traducir sus THROW sin exponer SQL.
    try:
        row = repository.abrir_cuenta(
            conn,
            numero_cuenta=numero_cuenta,
            id_cliente=payload.id_cliente,
            id_subproducto=payload.id_sub_producto,
            id_agencia=payload.id_agencia,
            monto_inicial=payload.monto_inicial,
            creado_por=creado_por,
        )
        conn.commit()
    except DBAPIError as exc:
        conn.rollback()
        raise traducir_error_bd(exc) from exc
    except Exception:
        conn.rollback()
        raise

    # CTA-01 conserva idMoneda en el contrato aunque la moneda no se persista por cuenta.
    return Cuenta(**{**row, "id_moneda": ID_MONEDA_USD})
