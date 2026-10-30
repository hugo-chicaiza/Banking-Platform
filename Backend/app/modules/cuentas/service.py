import re

from fastapi import HTTPException
from sqlalchemy import Connection

from app.modules.cuentas import repository
from app.modules.cuentas.schemas import Cuenta, CuentaCreate

# Generación de NumeroCuenta

# Formato acordado mientras se resuelve G-11 con negocio:
# prefijo de tipo (AH / CC) + IdProducto 2 dígitos + secuencial 6 dígitos.
# Ejemplo: AH02000501.  Único garantizado por el UNIQUE de la DB.
_PREFIJOS: dict[str, str] = {"Ahorro": "AH", "Corriente": "CC"}


def _generar_numero_cuenta(conn: Connection, tipo_cuenta: str, id_producto: int) -> str:
    """Genera el próximo NumeroCuenta libre.

    Estrategia: leer el MAX de cuentas con el mismo prefijo y sumar 1.
    La unicidad definitiva la garantiza el índice UNIQUE de Cuentas.Cuenta.
    """
    prefijo = _PREFIJOS.get(tipo_cuenta, "XX")
    patron = f"{prefijo}%"

    from sqlalchemy import text

    fila = conn.execute(
        text(
            """
            SELECT ISNULL(MAX(CAST(SUBSTRING(NumeroCuenta, 3, LEN(NumeroCuenta)) AS BIGINT)), 0)
                   AS ultimo
            FROM Cuentas.Cuenta
            WHERE NumeroCuenta LIKE :patron
              AND NumeroCuenta NOT LIKE '%[^0-9]%'
              -- solo cuentas cuyo sufijo sea numérico puro
            """
        ),
        {"patron": patron},
    ).fetchone()

    ultimo = fila[0] if fila else 0
    return f"{prefijo}{str(ultimo + 1).zfill(8)}"


# CTA-01 · Apertura de cuenta

# Códigos de error THROW que el SP o los triggers pueden lanzar.
# Los capturamos via pyodbc y los convertimos a ProblemDetails.
_DB_CODE_RE = re.compile(r"\b5(2[01]\d{2})\b")

_DB_CODE_MAP: dict[int, tuple[int, str]] = {
    52001: (409, "CLIENTE_NO_ACTIVO"),
    52002: (409, "CUENTA_NO_ACTIVA"),
    52003: (422, "CUPO_EXCEDE_PRODUCTO"),
    52101: (409, "CLIENTE_NO_ACTIVO"),
    52102: (409, "CLIENTE_NO_ACTIVO"),
    52103: (422, "PRODUCTO_NO_ES_CUENTA"),
    52104: (422, "PRODUCTO_NO_ES_CUENTA"),
    52105: (422, "MONTO_APERTURA_INSUFICIENTE"),
}


def _problema(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": detail},
    )


def abrir_cuenta(
    conn: Connection,
    payload: CuentaCreate,
    creado_por: str,
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
        raise _problema(409, "CLIENTE_NO_ACTIVO", "El cliente no está Activo.")

    # 2. Riesgo vigente no rechazado
    riesgo = repository.obtener_riesgo_vigente(conn, payload.id_cliente)
    if riesgo is not None and riesgo["estado"] == "Rechazado":
        raise _problema(
            409, "RIESGO_RECHAZADO", "El cliente tiene riesgo vigente rechazado."
        )

    # 3. Producto existe, es de tipo Cuenta y está activo
    producto = repository.obtener_producto(conn, payload.id_producto)
    if (
        producto is None
        or producto["tipo_producto"] != "Cuenta"
        or producto["estado"] != "A"
    ):
        raise _problema(
            422,
            "PRODUCTO_NO_ES_CUENTA",
            "El producto no es de tipo Cuenta o no está activo.",
        )

    # 4. Monto de apertura cubre el mínimo
    # El monto declarado no viaja en el payload de CTA-01; la validación
    # definitiva la hace usp_AbrirCuenta (THROW 52105).  Si el producto
    # tiene un mínimo explícito y el cliente no declara monto, el SP rechazará.

    # 5. Agencia existe y está activa
    agencia = repository.obtener_agencia(conn, payload.id_agencia)
    if agencia is None or agencia["estado"] != "A":
        raise _problema(
            409, "AGENCIA_INACTIVA", "La agencia no existe o no está activa."
        )

    # 6. Generar NumeroCuenta
    numero_cuenta = _generar_numero_cuenta(
        conn, payload.tipo_cuenta, payload.id_producto
    )

    # 7. Ejecutar el SP; captura THROWs de la DB
    try:
        row = repository.abrir_cuenta(
            conn,
            numero_cuenta=numero_cuenta,
            id_cliente=payload.id_cliente,
            id_producto=payload.id_producto,
            id_agencia=payload.id_agencia,
            tipo_cuenta=payload.tipo_cuenta,
            id_moneda=payload.id_moneda,
            creado_por=creado_por,
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        # Traducir THROW 5xxxx → ProblemDetails
        msg = str(exc)
        m = _DB_CODE_RE.search(msg)
        if m:
            db_code = int("5" + m.group(1))
            http_status, err_code = _DB_CODE_MAP.get(db_code, (422, f"DB_{db_code}"))
            raise _problema(http_status, err_code, msg) from exc
        raise  # re-raise para que el handler global lo capture como 500

    return Cuenta(**row)
