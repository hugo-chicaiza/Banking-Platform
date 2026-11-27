"""E8-02 · Integridad y archivo de la bitácora (#413).

Cada registro nuevo lleva una secuencia sin huecos y un hash que cubre el registro y el hash
anterior (`Auditoria.usp_RegistrarEvento` y `Auditoria.fn_HashRegistro`, la misma función para
escribir y para verificar). La verificación recalcula cada eslabón del rango, comprueba la unión
con el anterior y que los últimos eslabones ya verificados (anclas) sigan iguales, así también se
nota si alguien borra el final de la cadena. Una ruptura deja `Rota` con la primera secuencia
rota, una línea de error en el log y el evento AUD_INTEGRIDAD_ROTA (ASVS 16.4.2, 16.4.3).

El archivo anual mueve a `Auditoria.AuditoriaArchivo` (y su detalle) los registros más antiguos que
AUD_EDAD_ARCHIVO_ANIOS; los disparadores solo dejan salir de la tabla activa lo que ya tiene una copia
idéntica en el archivo. No hay purga (AU-8).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Connection, text

from app.core.database.db import get_engine
from app.core.security import audit
from app.core.tareas.ejecutor import Conteo
from app.modules.parametros import general

logger = logging.getLogger(__name__)

_DESFASE_UTC = timedelta(hours=5)  # Ecuador, UTC-5 todo el año
PARAMETRO_EDAD_ARCHIVO = "AUD_EDAD_ARCHIVO_ANIOS"
LOTE_ARCHIVO = 1000

_RANGO = text("""
    SELECT MIN(Secuencia), MAX(Secuencia) FROM Auditoria.vw_Bitacora
    WHERE Secuencia IS NOT NULL AND FechaHoraUTC >= :desde AND FechaHoraUTC < :hasta""")
_PRIMERA_ROTA = text("""
    WITH r AS (
      SELECT Secuencia, HashAnterior, Hash,
             Auditoria.fn_HashRegistro(Secuencia, HashAnterior, IdEvento, CodigoEvento, NombreAccion,
           FechaHoraUTC, FechaHora, UsuarioID, TablaAfectada, IDRegistro, DireccionIP, Descripcion, Resultado,
           RolesWorkOS, IdAgencia, IdSesion, Canal, IdCorrelacion, TipoObjetivo, IdObjetivo, Cambios, FormatoAnterior) AS Calculado,
             LAG(Secuencia) OVER (ORDER BY Secuencia) AS Previa,
             LAG(Hash) OVER (ORDER BY Secuencia) AS HashPrevio
      FROM Auditoria.vw_Bitacora WHERE Secuencia BETWEEN :desde - 1 AND :hasta)
    SELECT MIN(CASE WHEN Previa IS NOT NULL AND Secuencia <> Previa + 1 THEN Previa + 1 ELSE Secuencia END)
    FROM r
    WHERE Secuencia >= :desde
      AND (Hash IS NULL OR Calculado <> Hash
           OR (Secuencia = 1 AND HashAnterior IS NOT NULL)
           OR (Secuencia > 1 AND (Previa IS NULL OR Secuencia <> Previa + 1
                                  OR HashAnterior IS NULL OR HashAnterior <> HashPrevio)))""")
# Un eslabón ya verificado que cambió o desapareció (p. ej. borraron el final de la cadena)
_ANCLA_ROTA = text("""
    SELECT MIN(v.SecuenciaHasta) FROM Auditoria.VerificacionIntegridad AS v
    LEFT JOIN Auditoria.vw_Bitacora AS a ON a.Secuencia = v.SecuenciaHasta
    WHERE v.Resultado = 'Integra' AND v.HashHasta IS NOT NULL AND (a.Hash IS NULL OR a.Hash <> v.HashHasta)""")
_REGISTRAR = text("""
    INSERT Auditoria.VerificacionIntegridad (SecuenciaDesde, SecuenciaHasta, Resultado, PrimeraRota, HashHasta, EjecutadaPor)
    OUTPUT inserted.IdVerificacion, inserted.SecuenciaDesde, inserted.SecuenciaHasta, inserted.Resultado,
           inserted.PrimeraRota, inserted.EjecutadaPor, inserted.FechaUTC
    SELECT :desde, :hasta, :resultado, :primera,
           CASE WHEN :resultado = 'Integra'
                THEN (SELECT Hash FROM Auditoria.vw_Bitacora WHERE Secuencia = :hasta) END,
           :por""")
_LISTAR = text("""
    SELECT IdVerificacion, SecuenciaDesde, SecuenciaHasta, Resultado, PrimeraRota, EjecutadaPor, FechaUTC
    FROM Auditoria.VerificacionIntegridad
    ORDER BY IdVerificacion DESC OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY""")
_CONTAR = text("SELECT COUNT(*) FROM Auditoria.VerificacionIntegridad")
# Copia idéntica y luego salida de la tabla activa (los disparadores lo comprueban)
_ARCHIVAR = text("""
    SET NOCOUNT ON; SET XACT_ABORT ON;
    DECLARE @ids TABLE (AuditoriaID int PRIMARY KEY);
    INSERT @ids SELECT TOP (:lote) AuditoriaID FROM Auditoria.Auditoria
    WHERE COALESCE(FechaHoraUTC, DATEADD(hour, 5, CONVERT(datetime2, FechaHora))) < :corte
    ORDER BY AuditoriaID;
    EXEC sys.sp_set_session_context @key = N'auditoria_archivo', @value = 1;
    INSERT Auditoria.AuditoriaArchivo (AuditoriaID, UsuarioID, NombreAccion, TablaAfectada, IDRegistro, FechaHora, DireccionIP,
    Descripcion, Resultado, RolesWorkOS, IdEvento, CodigoEvento, FechaHoraUTC, IdAgencia, IdSesion, Canal,
    IdCorrelacion, TipoObjetivo, IdObjetivo, Cambios, FormatoAnterior, Secuencia, HashAnterior, Hash)
    SELECT a.AuditoriaID, a.UsuarioID, a.NombreAccion, a.TablaAfectada, a.IDRegistro, a.FechaHora, a.DireccionIP, a.Descripcion, a.Resultado, a.RolesWorkOS, a.IdEvento, a.CodigoEvento, a.FechaHoraUTC, a.IdAgencia, a.IdSesion, a.Canal, a.IdCorrelacion, a.TipoObjetivo, a.IdObjetivo, a.Cambios, a.FormatoAnterior, a.Secuencia, a.HashAnterior, a.Hash
    FROM Auditoria.Auditoria AS a JOIN @ids AS i ON i.AuditoriaID = a.AuditoriaID;
    INSERT Auditoria.EventoDetalleArchivo (IdEvento, AuditoriaID, CodigoEvento, Contenido, FechaHoraUTC)
    SELECT d.IdEvento, d.AuditoriaID, d.CodigoEvento, d.Contenido, d.FechaHoraUTC
    FROM Auditoria.EventoDetalle AS d JOIN @ids AS i ON i.AuditoriaID = d.AuditoriaID;
    DELETE d FROM Auditoria.EventoDetalle AS d JOIN @ids AS i ON i.AuditoriaID = d.AuditoriaID;
    DELETE a FROM Auditoria.Auditoria AS a JOIN @ids AS i ON i.AuditoriaID = a.AuditoriaID;
    EXEC sys.sp_set_session_context @key = N'auditoria_archivo', @value = NULL;
    SELECT COUNT(*) FROM @ids;""")


@dataclass(frozen=True)
class Verificacion:
    id_verificacion: int
    secuencia_desde: int
    secuencia_hasta: int
    resultado: str
    primera_rota: int | None
    ejecutada_por: int | None
    fecha_utc: datetime


def _verificacion(fila: Any) -> Verificacion:
    fecha = fila[6]
    return Verificacion(
        id_verificacion=int(fila[0]),
        secuencia_desde=int(fila[1]),
        secuencia_hasta=int(fila[2]),
        resultado=str(fila[3]),
        primera_rota=None if fila[4] is None else int(fila[4]),
        ejecutada_por=None if fila[5] is None else int(fila[5]),
        fecha_utc=fecha.replace(tzinfo=UTC) if fecha.tzinfo is None else fecha,
    )


def rango_de_secuencias(
    conn: Connection, desde: date, hasta: date
) -> tuple[int, int] | None:
    """Secuencias encadenadas de los días [desde, hasta] de la institución."""
    inicio = datetime.combine(desde, time()) + _DESFASE_UTC
    fin = datetime.combine(hasta + timedelta(days=1), time()) + _DESFASE_UTC
    minimo, maximo = conn.execute(_RANGO, {"desde": inicio, "hasta": fin}).one()
    return None if minimo is None else (int(minimo), int(maximo))


def primera_rota(conn: Connection, desde: int, hasta: int) -> int | None:
    rotas = [
        conn.execute(_PRIMERA_ROTA, {"desde": desde, "hasta": hasta}).scalar(),
        conn.execute(_ANCLA_ROTA).scalar(),
    ]
    return min((int(r) for r in rotas if r is not None), default=None)


def verificar(
    desde: date, hasta: date, ejecutada_por: int | None
) -> Verificacion | None:
    """None si el rango no tiene registros encadenados. `ejecutada_por` None = tarea nocturna."""
    with get_engine("seguridad").begin() as conn:
        rango = rango_de_secuencias(conn, desde, hasta)
        if rango is None:
            return None
        rota = primera_rota(conn, *rango)
        resultado = _verificacion(
            conn.execute(
                _REGISTRAR,
                {
                    "desde": rango[0],
                    "hasta": rango[1],
                    "resultado": "Rota" if rota is not None else "Integra",
                    "primera": rota,
                    "por": ejecutada_por,
                },
            ).one()
        )
    if rota is not None:
        # La alerta: línea de error para el monitoreo y evento en la propia bitácora
        logger.error(
            "AUD_INTEGRIDAD_ROTA verificacion=%d primera_rota=%d rango=%d-%d",
            resultado.id_verificacion,
            rota,
            *rango,
        )
        audit.registrar(
            audit.EventoAuditoria(
                accion="AUD_INTEGRIDAD_ROTA",
                tabla="Auditoria.VerificacionIntegridad",
                id_registro=str(resultado.id_verificacion),
                resultado="Fallido",
                usuario=ejecutada_por,
                ip=None,
                descripcion=f"primera secuencia rota={rota} rango={rango[0]}-{rango[1]}",
                canal="SISTEMA" if ejecutada_por is None else "API",
            )
        )
    return resultado


def listar(page: int, page_size: int) -> tuple[list[Verificacion], int]:
    with get_engine("seguridad").connect() as conn:
        total = int(conn.execute(_CONTAR).scalar_one())
        filas = conn.execute(
            _LISTAR, {"offset": (page - 1) * page_size, "page_size": page_size}
        ).all()
    return [_verificacion(f) for f in filas], total


def _ayer() -> date:
    return (datetime.now(UTC) - _DESFASE_UTC).date() - timedelta(days=1)


def tarea_verificar() -> Conteo:
    """AUD_VERIFICAR_INTEGRIDAD: la cadena del día anterior (hora de Ecuador)."""
    ayer = _ayer()
    resultado = verificar(ayer, ayer, None)
    if resultado is None:
        return Conteo()
    procesados = resultado.secuencia_hasta - resultado.secuencia_desde + 1
    return Conteo(procesados=procesados, errores=int(resultado.resultado == "Rota"))


def tarea_archivar() -> Conteo:
    """AUD_ARCHIVAR: lotes de LOTE_ARCHIVO registros, cada uno en su transacción."""
    hoy = (datetime.now(UTC) - _DESFASE_UTC).date()
    with get_engine("cooperativa").connect() as coop:
        anios = int(str(general.valor(coop, PARAMETRO_EDAD_ARCHIVO, hoy)))
    # 29 de febrero: el corte cae el 28 de un año no bisiesto
    limite = hoy.replace(
        year=hoy.year - anios, day=min(hoy.day, 28) if hoy.month == 2 else hoy.day
    )
    corte = datetime.combine(limite, time()) + _DESFASE_UTC
    movidos = 0
    while True:
        with get_engine("seguridad").begin() as conn:
            lote = int(
                conn.execute(
                    _ARCHIVAR, {"lote": LOTE_ARCHIVO, "corte": corte}
                ).scalar_one()
            )
        movidos += lote
        if lote < LOTE_ARCHIVO:
            break
    audit.registrar(
        audit.EventoAuditoria(
            accion="AUD_ARCHIVO",
            tabla="Auditoria.AuditoriaArchivo",
            id_registro=None,
            resultado="Exitoso",
            usuario=None,
            ip=None,
            descripcion=f"registros archivados={movidos} anteriores a {corte:%Y-%m-%d} UTC ({anios} años)",
            canal="SISTEMA",
        )
    )
    return Conteo(procesados=movidos, modificados=movidos)
