"""Ejecutor de tareas programadas (E0-06).

Cada tarea es un comando del backend: `python -m app.core.tareas ejecutar <codigo>`.
El disparo vive fuera del producto (web jobs de App Service o el ciclo de la app). El
ejecutor:
- toma un bloqueo por código (`sp_getapplock`): si otra instancia la está corriendo,
  termina sin hacer nada (M8 AC 15);
- registra inicio, fin, resultado (`Exitoso`, `Fallido`, `Parcial`), procesados,
  modificados y código de error en `Sistema.TareaEjecucion`, sin datos personales (AC 16);
- una ejecución manual exige quién y motivo, y que la tarea la permita (AC 4).
Las tareas de aprobaciones (APR_*) ya tienen su ejecutor con el mismo bloqueo y registro
(E0-08): se delegan a él.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from app.core.database.db import get_engine

logger = logging.getLogger(__name__)


@dataclass
class Conteo:
    procesados: int = 0
    modificados: int = 0
    errores: int = 0


@dataclass(frozen=True)
class Tarea:
    codigo: str
    funcion: Callable[[], Conteo] = field(repr=False)


class TareaRechazada(RuntimeError):
    """No se ejecuta: código desconocido, deshabilitada, sin permiso manual o sin motivo."""


class TareaEnCurso(RuntimeError):
    """Otra instancia tiene el bloqueo de la tarea."""


def _tomar_bloqueo(conn: Connection, recurso: str) -> bool:
    resultado = conn.execute(
        text(
            "DECLARE @r int; EXEC @r=sys.sp_getapplock @Resource=:recurso,@LockMode='Exclusive',"
            "@LockOwner='Session',@LockTimeout=0; SELECT @r"
        ),
        {"recurso": recurso},
    ).scalar_one()
    conn.commit()
    return resultado >= 0


def _soltar_bloqueo(conn: Connection, recurso: str) -> None:
    conn.execute(
        text("EXEC sys.sp_releaseapplock @Resource=:recurso,@LockOwner='Session'"),
        {"recurso": recurso},
    )
    conn.commit()


def _tarea(conn: Connection, codigo: str) -> dict | None:
    fila = (
        conn.execute(
            text(
                "SELECT Estado, PermiteManual FROM Sistema.Tarea WHERE Codigo=:codigo"
            ),
            {"codigo": codigo},
        )
        .mappings()
        .first()
    )
    return dict(fila) if fila else None


def _iniciar(conn: Connection, codigo: str, por: str | None, motivo: str | None) -> int:
    id_ = conn.execute(
        text(
            "INSERT Sistema.TareaEjecucion(Codigo,EjecutadaPor,Motivo) OUTPUT inserted.IdEjecucion "
            "VALUES(:codigo,:por,:motivo)"
        ),
        {"codigo": codigo, "por": por, "motivo": motivo},
    ).scalar_one()
    conn.commit()
    return int(id_)


def _terminar(
    conn: Connection, id_: int, resultado: str, conteo: Conteo, error: str | None
) -> None:
    conn.execute(
        text(
            "UPDATE Sistema.TareaEjecucion SET FinUTC=SYSUTCDATETIME(),Resultado=:resultado,"
            "Procesados=:procesados,Modificados=:modificados,CodigoError=:error WHERE IdEjecucion=:id"
        ),
        {
            "id": id_,
            "resultado": resultado,
            "procesados": conteo.procesados,
            "modificados": conteo.modificados,
            "error": error,
        },
    )
    conn.commit()


def ejecutar(
    tarea: Tarea, *, por: str | None = None, motivo: str | None = None
) -> Conteo:
    """Corre la tarea una sola vez con bloqueo y registro. Lanza TareaEnCurso si otra
    instancia la tiene, TareaRechazada si no corresponde ejecutarla."""
    if por is not None and not (motivo or "").strip():
        raise TareaRechazada("una ejecución manual exige motivo")
    with get_engine("seguridad").connect() as conn:
        if not _tomar_bloqueo(conn, tarea.codigo):
            raise TareaEnCurso(tarea.codigo)
        try:
            datos = _tarea(conn, tarea.codigo)
            if datos is None or datos["Estado"] != "A":
                raise TareaRechazada(
                    f"{tarea.codigo} no está habilitada en Sistema.Tarea"
                )
            if por is not None and not datos["PermiteManual"]:
                raise TareaRechazada(f"{tarea.codigo} no admite ejecución manual")
            id_ = _iniciar(conn, tarea.codigo, por, (motivo or "").strip() or None)
            conteo, resultado, error = Conteo(), "Fallido", "TAREA_ERROR"
            try:
                conteo = tarea.funcion()
                resultado = "Parcial" if conteo.errores else "Exitoso"
                error = "TAREA_PARCIAL" if conteo.errores else None
                return conteo
            finally:
                if conn.in_transaction():
                    conn.rollback()
                _terminar(conn, id_, resultado, conteo, error)
                logger.info(
                    "tarea %s resultado=%s procesados=%d",
                    tarea.codigo,
                    resultado,
                    conteo.procesados,
                )
        finally:
            if conn.in_transaction():
                conn.rollback()
            _soltar_bloqueo(conn, tarea.codigo)
