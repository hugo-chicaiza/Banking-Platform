from datetime import date, datetime
from typing import Any

from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.modules.transacciones.dependencias import Numeracion

CODIGOS_CONSULTA = {"Ahorro": "311000", "Corriente": "312000"}


def bloquear_numeracion(conn: Connection) -> bool:
    # Recurso global compartible por futuros proveedores de numeración. El bloqueo
    # pertenece a la transacción, se libera con commit/rollback, nunca con el proceso.
    resultado = conn.execute(
        text("""
        IF @@TRANCOUNT = 0 BEGIN TRANSACTION;
        DECLARE @resultado int;
        EXEC @resultado = sys.sp_getapplock
            @Resource = 'Transacciones.Numeracion', @LockMode = 'Exclusive',
            @LockOwner = 'Transaction', @LockTimeout = 5000;
        SELECT @resultado;
    """)
    ).scalar_one()
    return type(resultado) is int and resultado >= 0


def siguiente_secuencial(conn: Connection, fecha: date) -> int | None:
    # Sin asumir que el histórico respeta nuestra convención. Un valor ajeno
    # cancela la numeración; nunca se ignora para reiniciar silenciosamente.
    fila = (
        conn.execute(
            text("""
        SELECT COALESCE(MAX(TRY_CONVERT(int, Secuencial)), 0) AS Maximo,
               COALESCE(SUM(CAST(CASE
                   WHEN Secuencial IS NULL OR LEN(Secuencial) <> 6
                     OR Secuencial COLLATE Latin1_General_100_BIN2 LIKE '%[^0-9]%'
                   THEN 1 ELSE 0 END AS bigint)), 0) AS Invalidos
        FROM Transacciones.Transaccion WITH (UPDLOCK, HOLDLOCK)
        WHERE FechaSistema = :fecha
    """),
            {"fecha": fecha},
        )
        .mappings()
        .one()
    )
    return None if fila["Invalidos"] else int(fila["Maximo"]) + 1


def identificadores_ocupados(conn: Connection, datos: dict[str, Any]) -> bool:
    return (
        conn.execute(
            text("""
        SELECT TOP (1) 1 FROM Transacciones.Transaccion WITH (UPDLOCK, HOLDLOCK)
        WHERE NumeroComprobante = :comprobante OR RRN = :rrn
           OR (FechaSistema = :fecha AND (STAN = :stan OR Secuencial = :secuencial))
    """),
            datos,
        ).scalar_one_or_none()
        is not None
    )


def numerar_consulta(conn: Connection, ahora: datetime, tipo_cuenta: str) -> Numeracion:
    """Secuencia diaria no cíclica; STAN/DE11 de seis dígitos y RRN/DE37 de doce.

    Convención interna, no algoritmo impuesto por ISO. FechaSistema procede del
    reloj SQL del llamador; no usar la fecha contable ni un contador en memoria.
    El applock se conserva hasta el commit. No habilita otras operaciones.
    """
    siguiente = siguiente_secuencial(conn, ahora.date())
    if siguiente is None:
        raise problema(
            503, "NUMERACION_NO_DISPONIBLE", "El histórico requiere revisión."
        )
    if not 1 <= siguiente <= 999999:
        raise problema(503, "NUMERACION_AGOTADA", "La numeración no está disponible.")
    secuencial = f"{siguiente:06d}"
    rrn = ahora.strftime("%y%m%d") + secuencial
    comprobante = "ATM-" + ahora.strftime("%Y%m%d") + "-" + secuencial
    if identificadores_ocupados(
        conn,
        {
            "comprobante": comprobante,
            "rrn": rrn,
            "stan": secuencial,
            "secuencial": secuencial,
            "fecha": ahora.date(),
        },
    ):
        raise problema(
            503, "NUMERACION_NO_DISPONIBLE", "El histórico requiere revisión."
        )
    if tipo_cuenta not in CODIGOS_CONSULTA:
        raise problema(
            409, "TIPO_CUENTA_NO_PERMITIDO", "La cuenta no permite consultas ATM."
        )
    return Numeracion(
        comprobante,
        secuencial,
        CODIGOS_CONSULTA[tipo_cuenta],
        secuencial,
        rrn,
        None,
    )
