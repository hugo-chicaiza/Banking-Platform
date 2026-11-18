"""Servicio E0-09. La transaccion pertenece al consumidor, no se hace commit aqui."""

import hashlib
import json
import re
from datetime import date, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import (
    Connection,
    text,
)
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema
from app.modules.parametros.tipos import convertir


def _sql(contenido: str):
    # SQLDescribeParam debe poder inferir los tipos incluso en ``? IS NULL``.
    # XACT_ABORT puede revertir la transaccion si esa descripcion falla.
    # Solo se transforman nombres internos de parametros; los valores siguen ligados.
    for nombre, tipo in {
        "agencia": "char(3)",
        "hasta": "date",
        "solicitud": "bigint",
    }.items():
        contenido = re.sub(
            r":" + nombre + r"\b", "CAST(:" + nombre + " AS " + tipo + ")", contenido
        )
    return text(contenido)


def definicion(
    conn: Connection, clave: str, *, bloquear: bool = False
) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Z0-9_]{1,60}", clave):
        raise problema(404, "PARAMETRO_NO_ENCONTRADO", "El parametro no existe.")
    consulta = (
        _sql(
            "SELECT * FROM Parametros.Parametro WITH (UPDLOCK,HOLDLOCK) WHERE Clave=:clave"
        )
        if bloquear
        else _sql("SELECT * FROM Parametros.Parametro WHERE Clave=:clave")
    )
    fila = (
        conn.execute(
            consulta,
            {"clave": clave},
        )
        .mappings()
        .first()
    )
    if fila is None:
        raise problema(404, "PARAMETRO_NO_ENCONTRADO", "El parametro no existe.")
    return dict(fila)


def historial(
    conn: Connection, clave: str, agencia: str | None = None
) -> list[dict[str, Any]]:
    _validar_agencia(agencia)
    p = definicion(conn, clave)
    filas = (
        conn.execute(
            _sql("""SELECT * FROM Parametros.ParametroValor WHERE IdParametro=:id
        AND (IdAgencia=:agencia OR IdAgencia IS NULL) ORDER BY VigenciaDesde DESC,IdParametroValor DESC"""),
            {"id": p["IdParametro"], "agencia": agencia},
        )
        .mappings()
        .all()
    )
    return [dict(f) for f in filas]


def valor(
    conn: Connection, clave: str, fecha: date, agencia: str | None = None
) -> object:
    _validar_agencia(agencia)
    p = definicion(conn, clave)
    if p["Estado"] != "A":
        raise problema(404, "PARAMETRO_NO_DISPONIBLE", "El parametro esta inactivo.")
    filas = conn.execute(
        _sql("""SELECT TOP(1) Valor FROM Parametros.ParametroValor
        WHERE IdParametro=:id AND Estado='A' AND VigenciaDesde<=:fecha
        AND (VigenciaHasta IS NULL OR VigenciaHasta>=:fecha)
        AND (IdAgencia=:agencia OR IdAgencia IS NULL)
        ORDER BY CASE WHEN IdAgencia IS NULL THEN 0 ELSE 1 END DESC,VigenciaDesde DESC"""),
        {"id": p["IdParametro"], "fecha": fecha, "agencia": agencia},
    ).first()
    if filas is None:
        raise problema(
            404, "VALOR_NO_DISPONIBLE", "No hay valor vigente para esa fecha."
        )
    return convertir(p, filas.Valor)


def verificar_funcion(
    conn: Connection, clave: str, fecha: date, agencia: str | None = None
) -> None:
    try:
        habilitada = valor(conn, clave, fecha, agencia)
    except HTTPException as error:
        if error.status_code not in (404, 422):
            raise
        habilitada = False
    if habilitada is not True:
        raise problema(404, "FUNCION_NO_DISPONIBLE", "La funcion no esta disponible.")


def _validar_agencia(agencia: str | None) -> None:
    if agencia is not None and (
        not re.fullmatch(r"[0-9]{3}", agencia) or agencia == "000"
    ):
        raise problema(422, "AGENCIA_INVALIDA", "La agencia no es valida.")


def validar(
    conn: Connection,
    clave: str,
    valor_: str,
    desde: date,
    hasta: date | None,
    agencia: str | None,
) -> dict[str, Any]:
    p = definicion(conn, clave, bloquear=True)
    if p["Estado"] != "A":
        raise problema(409, "PARAMETRO_INACTIVO", "El parametro esta inactivo.")
    if hasta is not None and hasta < desde:
        raise problema(422, "VIGENCIA_INVALIDA", "El fin no puede preceder al inicio.")
    convertir(p, valor_)
    if agencia is not None:
        if not p["AdmiteAgencia"]:
            raise problema(
                422, "ALCANCE_NO_ADMITIDO", "El parametro solo admite alcance global."
            )
        if not re.fullmatch(r"[0-9]{3}", agencia) or agencia == "000":
            raise problema(422, "AGENCIA_INVALIDA", "La agencia no es valida.")
        if (
            conn.execute(
                _sql(
                    "SELECT 1 FROM Organizacion.Agencia WHERE IdAgencia=:id AND Estado='A'"
                ),
                {"id": agencia},
            ).scalar()
            is None
        ):
            raise problema(404, "AGENCIA_NO_DISPONIBLE", "La agencia no esta activa.")
    return p


def registrar(
    conn: Connection,
    clave: str,
    valor_: str,
    desde: date,
    *,
    hasta: date | None = None,
    agencia: str | None = None,
    actor: str,
    solicitud: int | None = None,
) -> int:
    p = validar(conn, clave, valor_, desde, hasta, agencia)
    if not re.fullmatch(r"user_[A-Za-z0-9_-]{1,59}", actor):
        raise problema(
            422,
            "ACTOR_INVALIDO",
            "Se requiere el sujeto WorkOS validado por el servidor.",
        )
    if solicitud is not None:
        existente = (
            conn.execute(
                _sql(
                    "SELECT IdParametroValor,IdParametro,IdAgencia,Valor,VigenciaDesde,VigenciaHasta,CreadoPor FROM Parametros.ParametroValor WHERE IdSolicitud=:id"
                ),
                {"id": solicitud},
            )
            .mappings()
            .first()
        )
        if existente is not None:
            if (
                existente["IdParametro"] != p["IdParametro"]
                or existente["IdAgencia"] != agencia
                or existente["Valor"] != valor_
                or existente["VigenciaDesde"] != desde
                or existente["VigenciaHasta"] != hasta
                or existente["CreadoPor"] != actor
            ):
                raise problema(
                    409,
                    "IDEMPOTENCIA_CONFLICTIVA",
                    "La solicitud ya se aplico con otro contenido.",
                )
            return existente["IdParametroValor"]
    solape = conn.execute(
        _sql("""SELECT 1 FROM Parametros.ParametroValor
        WHERE IdParametro=:id AND (IdAgencia=:agencia OR (IdAgencia IS NULL AND :agencia IS NULL))
        AND Estado='A' AND VigenciaDesde<=COALESCE(:hasta,CONVERT(date,'99991231',112))
        AND :desde<=COALESCE(VigenciaHasta,CONVERT(date,'99991231',112))"""),
        {"id": p["IdParametro"], "agencia": agencia, "desde": desde, "hasta": hasta},
    ).scalar()
    if solape is not None:
        raise problema(
            422,
            "VIGENCIA_SOLAPADA",
            "La vigencia se solapa con otro valor del mismo alcance.",
        )
    try:
        conn.execute(
            _sql("""INSERT Parametros.ParametroValor
            (IdParametro,IdAgencia,Valor,VigenciaDesde,VigenciaHasta,CreadoPor,IdSolicitud)
            VALUES (:id,:agencia,:valor,:desde,:hasta,:actor,:solicitud)"""),
            {
                "id": p["IdParametro"],
                "agencia": agencia,
                "valor": valor_,
                "desde": desde,
                "hasta": hasta,
                "actor": actor,
                "solicitud": solicitud,
            },
        )
        # Una sola sentencia de escritura: no devolver OUTPUT de un lote que
        # pueda contener resultados pendientes de un trigger. El lock del
        # parametro y el trigger garantizan un unico intervalo activo.
        return int(
            conn.execute(
                _sql("""SELECT IdParametroValor FROM Parametros.ParametroValor
            WHERE IdParametro=:id AND (IdAgencia=:agencia OR (IdAgencia IS NULL AND :agencia IS NULL))
            AND VigenciaDesde=:desde AND Estado='A'"""),
                {"id": p["IdParametro"], "agencia": agencia, "desde": desde},
            ).scalar_one()
        )
    except DBAPIError as error:
        if "57101" in str(error.orig):
            raise problema(
                422, "VIGENCIA_SOLAPADA", "La vigencia se solapa con otro valor."
            ) from None
        raise


def version(conn: Connection, clave: str, agencia: str | None = None) -> str:
    contenido = {
        "definicion": definicion(conn, clave, bloquear=True),
        "valores": historial(conn, clave, agencia),
    }
    return hashlib.sha256(
        json.dumps(contenido, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def programar(
    conn: Connection,
    clave: str,
    valor_: str,
    desde: date,
    *,
    agencia: str | None = None,
    actor: str,
    solicitud: int | None = None,
) -> int:
    if not re.fullmatch(r"user_[A-Za-z0-9_-]{1,59}", actor):
        raise problema(
            422,
            "ACTOR_INVALIDO",
            "Se requiere el sujeto WorkOS validado por el servidor.",
        )
    p = validar(conn, clave, valor_, desde, None, agencia)
    if solicitud is not None:
        existente = (
            conn.execute(
                _sql(
                    "SELECT IdParametroValor,IdParametro,IdAgencia,Valor,VigenciaDesde,CreadoPor FROM Parametros.ParametroValor WHERE IdSolicitud=:id"
                ),
                {"id": solicitud},
            )
            .mappings()
            .first()
        )
        if existente is not None:
            if (
                existente["IdParametro"] != p["IdParametro"]
                or existente["IdAgencia"] != agencia
                or existente["Valor"] != valor_
                or existente["VigenciaDesde"] != desde
                or existente["CreadoPor"] != actor
            ):
                raise problema(
                    409,
                    "IDEMPOTENCIA_CONFLICTIVA",
                    "La solicitud ya se aplico con otro contenido.",
                )
            return int(existente["IdParametroValor"])
    futuro = conn.execute(
        _sql("""SELECT 1 FROM Parametros.ParametroValor WHERE IdParametro=:id
       AND (IdAgencia=:agencia OR (IdAgencia IS NULL AND :agencia IS NULL)) AND Estado='A' AND VigenciaDesde>=:desde"""),
        {"id": p["IdParametro"], "agencia": agencia, "desde": desde},
    ).scalar()
    if futuro is not None:
        raise problema(
            422,
            "VIGENCIA_SOLAPADA",
            "Existe un valor con inicio igual o posterior. Cancelelo antes de reprogramar.",
        )
    anterior = (
        conn.execute(
            _sql("""SELECT TOP(1) * FROM Parametros.ParametroValor WHERE IdParametro=:id
       AND (IdAgencia=:agencia OR (IdAgencia IS NULL AND :agencia IS NULL)) AND Estado='A' AND VigenciaDesde<:desde
       AND (VigenciaHasta IS NULL OR VigenciaHasta>=:desde) ORDER BY VigenciaDesde DESC"""),
            {"id": p["IdParametro"], "agencia": agencia, "desde": desde},
        )
        .mappings()
        .first()
    )
    if anterior is not None:
        conn.execute(
            _sql(
                "UPDATE Parametros.ParametroValor SET VigenciaHasta=:hasta WHERE IdParametroValor=:id"
            ),
            {"hasta": desde - timedelta(days=1), "id": anterior["IdParametroValor"]},
        )
    id_ = registrar(
        conn, clave, valor_, desde, agencia=agencia, actor=actor, solicitud=solicitud
    )
    if anterior is not None:
        conn.execute(
            _sql(
                "UPDATE Parametros.ParametroValor SET IdValorAnterior=:anterior,VigenciaHastaAnterior=:hasta WHERE IdParametroValor=:id"
            ),
            {
                "id": id_,
                "anterior": anterior["IdParametroValor"],
                "hasta": anterior["VigenciaHasta"],
            },
        )
    return id_
