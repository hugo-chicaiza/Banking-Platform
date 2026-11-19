"""Reglas y contador compartido E3-04 dentro de la transaccion de apertura."""

import hashlib
import json
from typing import Any

from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.modules.parametros.service import hoy
from app.modules.productos.numeracion_formato import formar_numero, formatos_intersectan
from app.modules.productos.numeracion_schemas import ReglaEntrada


def bloqueo(conn: Connection, exclusivo: bool = False) -> None:
    resultado = conn.execute(
        text(
            "DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource=N'E304_NUMERACION',@LockMode=:modo,@LockOwner='Transaction',@LockTimeout=10000; SELECT @r"
        ),
        {"modo": "Exclusive" if exclusivo else "Shared"},
    ).scalar_one()
    if resultado < 0:
        raise problema(
            409, "NUMERACION_OCUPADA", "La numeracion esta ocupada. Intente nuevamente."
        )


def configuracion(fila: dict[str, Any]) -> ReglaEntrada:
    return ReglaEntrada(
        prefijo=fila["Prefijo"],
        incluye_agencia=bool(fila["IncluyeAgencia"]),
        longitud_secuencia=fila["LongitudSecuencia"],
        algoritmo_verificador=fila["AlgoritmoVerificador"],
    )


def reglas(conn: Connection, id_sub: int) -> list[dict[str, Any]]:
    return [
        dict(v)
        for v in conn.execute(
            text(
                "SELECT * FROM ProductosFinancieros.ReglaNumeracion WITH(UPDLOCK,HOLDLOCK) WHERE IdSubProducto=:id ORDER BY IdReglaNumeracion"
            ),
            {"id": id_sub},
        ).mappings()
    ]


def cuentas_existentes(conn: Connection, id_sub: int) -> bool:
    return (
        conn.execute(
            text(
                "SELECT TOP(1) 1 FROM Cuentas.Cuenta WITH(UPDLOCK,HOLDLOCK) WHERE IdSubProducto=:id"
            ),
            {"id": id_sub},
        ).scalar()
        is not None
    )


def impedir_edicion_usada(conn: Connection, id_sub: int, filas: list[dict]) -> None:
    if any(v["Usada"] for v in filas) or cuentas_existentes(conn, id_sub):
        raise problema(
            409, "REGLA_EN_USO", "La regla ya tiene cuentas y no se puede cambiar."
        )


def vigente(conn: Connection, id_sub: int) -> dict[str, Any] | None:
    return next(
        (
            v
            for v in reversed(reglas(conn, id_sub))
            if v["Estado"] == "A"
            and v["VigenciaDesde"] <= hoy()
            and (v["VigenciaHasta"] is None or v["VigenciaHasta"] >= hoy())
        ),
        None,
    )


def version(conn: Connection, id_sub: int) -> str:
    valor = {
        "reglas": reglas(conn, id_sub),
        "conCuentas": cuentas_existentes(conn, id_sub),
    }
    return hashlib.sha256(
        json.dumps(valor, default=str, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def serie_compatible(
    conn: Connection, regla: ReglaEntrada, ignorar_sub: int | None = None
) -> int | None:
    todas = conn.execute(
        text(
            "SELECT r.*,s.UltimoNumero FROM ProductosFinancieros.ReglaNumeracion r WITH(UPDLOCK,HOLDLOCK) LEFT JOIN ProductosFinancieros.SecuenciaCuenta s WITH(UPDLOCK,HOLDLOCK) ON s.IdReglaNumeracion=COALESCE(r.IdReglaSecuencia,r.IdReglaNumeracion) ORDER BY r.IdReglaNumeracion"
        )
    ).mappings()
    serie = None
    for registro in todas:
        anterior = configuracion(dict(registro))
        if anterior == regla:
            serie = (
                serie or registro["IdReglaSecuencia"] or registro["IdReglaNumeracion"]
            )
        elif (
            registro["IdSubProducto"] == ignorar_sub
            and not registro["Usada"]
            and not (registro["UltimoNumero"] or 0)
        ):
            continue
        elif (
            registro["Estado"] == "A"
            or registro["Usada"]
            or (registro["UltimoNumero"] or 0) > 0
        ) and formatos_intersectan(anterior, regla):
            raise problema(
                422,
                "FORMATO_NUMERACION_SOLAPADO",
                "El formato puede producir numeros de otra regla. Cambie el prefijo o la longitud.",
            )
    return serie


def inicial(conn: Connection, regla: ReglaEntrada) -> int:
    longitud = (
        len(regla.prefijo)
        + (3 if regla.incluye_agencia else 0)
        + regla.longitud_secuencia
        + (regla.algoritmo_verificador != "NINGUNO")
    )
    posicion = len(regla.prefijo) + (3 if regla.incluye_agencia else 0) + 1
    return int(
        conn.execute(
            text(
                "SELECT COALESCE(MAX(TRY_CONVERT(bigint,SUBSTRING(NumeroCuenta,:posicion,:digitos))),0) FROM Cuentas.Cuenta WITH(UPDLOCK,HOLDLOCK) WHERE LEN(NumeroCuenta)=:longitud AND NumeroCuenta LIKE :prefijo AND NumeroCuenta NOT LIKE '%[^0-9]%'"
            ),
            {
                "posicion": posicion,
                "digitos": regla.longitud_secuencia,
                "longitud": longitud,
                "prefijo": regla.prefijo + "%",
            },
        ).scalar_one()
    )


def siguiente_numero_cuenta(conn: Connection, id_sub: int, id_agencia: str) -> str:
    """No hace commit: contador, marca de uso y apertura pertenecen al llamador."""
    bloqueo(conn)
    fila = vigente(conn, id_sub)
    if fila is None:
        raise problema(
            409,
            "REGLA_NUMERACION_NO_DISPONIBLE",
            "El subproducto necesita una regla de numeracion aprobada.",
        )
    regla = configuracion(fila)
    # Validar el formato/agencia antes de consumir el contador.
    formar_numero(regla, 1, id_agencia)
    serie = fila["IdReglaSecuencia"] or fila["IdReglaNumeracion"]
    numero = conn.execute(
        text(
            "UPDATE ProductosFinancieros.SecuenciaCuenta WITH(UPDLOCK,ROWLOCK) SET UltimoNumero=UltimoNumero+1,FechaActualizacion=SYSUTCDATETIME() OUTPUT inserted.UltimoNumero WHERE IdReglaNumeracion=:id AND UltimoNumero<:maximo"
        ),
        {"id": serie, "maximo": 10**regla.longitud_secuencia - 1},
    ).scalar()
    if numero is None:
        existe = conn.execute(
            text(
                "SELECT 1 FROM ProductosFinancieros.SecuenciaCuenta WHERE IdReglaNumeracion=:id"
            ),
            {"id": serie},
        ).scalar()
        raise problema(
            409,
            "SECUENCIA_AGOTADA" if existe else "SECUENCIA_NO_DISPONIBLE",
            "La secuencia esta agotada."
            if existe
            else "La secuencia requiere revision.",
        )
    conn.execute(
        text(
            "UPDATE ProductosFinancieros.ReglaNumeracion SET Usada=1 WHERE IdReglaNumeracion=:id"
        ),
        {"id": fila["IdReglaNumeracion"]},
    )
    return formar_numero(regla, int(numero), id_agencia)
