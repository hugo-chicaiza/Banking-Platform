"""Consultas de la bitácora de auditoría (SeguridadDB, E8-01).

Solo consultas fijas: los filtros opcionales van como `(:x IS NULL OR ...)` y el alcance
de agencia como lista enlazada (`:todas = 1 OR a.IdAgencia IN :agencias`), nunca texto
concatenado. Lee la vista activa + archivo (E8-02). Las filas del formato anterior no tienen FechaHoraUTC: se filtran por
FechaHora (hora local).
"""

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import Connection, bindparam, text

# Ecuador: UTC-5 todo el año
_DESFASE_UTC = timedelta(hours=5)

_COLUMNAS = """
    a.AuditoriaID, a.IdEvento, COALESCE(a.CodigoEvento, a.NombreAccion) AS CodigoEvento,
    t.Modulo, t.Severidad, a.FechaHoraUTC, a.FechaHora, a.UsuarioID,
    u.Nombres + ' ' + u.Apellidos AS NombreUsuario, a.IdAgencia, a.Canal, a.DireccionIP,
    a.Resultado, COALESCE(a.TipoObjetivo, a.TablaAfectada) AS TipoObjetivo,
    COALESCE(a.IdObjetivo, a.IDRegistro) AS IdObjetivo, a.IdCorrelacion, a.Descripcion,
    a.FormatoAnterior"""
_ORIGEN = """
    FROM Auditoria.vw_Bitacora AS a
    LEFT JOIN Auditoria.TipoEvento AS t ON t.CodigoEvento = COALESCE(a.CodigoEvento, a.NombreAccion)
    LEFT JOIN Organizacion.Usuarios AS u ON u.UsuarioID = a.UsuarioID"""
_ALCANCE = "(:todas = 1 OR a.IdAgencia IN :agencias)"
_BUSQUEDA = (
    _ORIGEN
    + """
    LEFT JOIN Auditoria.vw_EventoDetalle AS ed ON ed.AuditoriaID = a.AuditoriaID
    WHERE ((a.FechaHoraUTC >= :utc_desde AND a.FechaHoraUTC < :utc_hasta)
           OR (a.FechaHoraUTC IS NULL AND a.FechaHora >= :local_desde AND a.FechaHora < :local_hasta))
      AND (:usuario IS NULL OR a.UsuarioID = :usuario)
      AND (:agencia IS NULL OR a.IdAgencia = :agencia)
      AND (:modulo IS NULL OR t.Modulo = :modulo)
      AND (:codigo_evento IS NULL OR COALESCE(a.CodigoEvento, a.NombreAccion) = :codigo_evento)
      AND (:resultado IS NULL OR a.Resultado = :resultado)
      AND (:tipo_objetivo IS NULL OR COALESCE(a.TipoObjetivo, a.TablaAfectada) = :tipo_objetivo)
      AND (:id_objetivo IS NULL OR COALESCE(a.IdObjetivo, a.IDRegistro) = :id_objetivo)
      AND (:origen IS NULL OR a.DireccionIP = :origen)
      AND (:canal IS NULL OR a.Canal = :canal)
      AND (:correlacion IS NULL OR a.IdCorrelacion = :correlacion)
      AND (:id_solicitud IS NULL
           OR JSON_VALUE(ed.Contenido, '$.idSolicitud') = :id_solicitud
           OR (COALESCE(a.TipoObjetivo, a.TablaAfectada) = 'Seguridad.SolicitudAprobacion'
               AND COALESCE(a.IdObjetivo, a.IDRegistro) = :id_solicitud))
      AND """
    + _ALCANCE
)
_OBJETIVO = (
    _ORIGEN
    + """
    WHERE ((a.TipoObjetivo = :tipo AND a.IdObjetivo = :id_objetivo)
           OR (a.TipoObjetivo IS NULL AND a.TablaAfectada = :tipo AND a.IDRegistro = :id_objetivo))
      AND """
    + _ALCANCE
)
_PAGINA = """
    ORDER BY COALESCE(a.FechaHoraUTC, DATEADD(hour, 5, a.FechaHora)) DESC, a.AuditoriaID DESC
    OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY"""

_AGENCIAS = bindparam("agencias", expanding=True)
_CONTAR_BUSQUEDA = text("SELECT COUNT(*)" + _BUSQUEDA).bindparams(_AGENCIAS)
_PAGINA_BUSQUEDA = text("SELECT" + _COLUMNAS + _BUSQUEDA + _PAGINA).bindparams(
    _AGENCIAS
)
_CONTAR_OBJETIVO = text("SELECT COUNT(*)" + _OBJETIVO).bindparams(_AGENCIAS)
_PAGINA_OBJETIVO = text("SELECT" + _COLUMNAS + _OBJETIVO + _PAGINA).bindparams(
    _AGENCIAS
)
_EVENTO = text(
    "SELECT" + _COLUMNAS + ", a.Cambios" + _ORIGEN + " WHERE a.AuditoriaID = :id"
)
_RELACIONADOS = text(
    "SELECT TOP (200)"
    + _COLUMNAS
    + _ORIGEN
    + " WHERE a.IdCorrelacion = :correlacion AND a.AuditoriaID <> :id AND "
    + _ALCANCE
    + " ORDER BY COALESCE(a.FechaHoraUTC, DATEADD(hour, 5, a.FechaHora)), a.AuditoriaID"
).bindparams(_AGENCIAS)
_APROBACION = text("""
    SELECT s.IdSolicitud, s.CodigoTransaccion, s.Estado, s.NombreSolicitante,
           s.IdInternoSolicitante, s.FechaSolicitud, s.NombreResolutor,
           s.IdInternoResolutor, s.FechaResolucion
    FROM Seguridad.SolicitudAprobacion AS s
    WHERE s.IdSolicitud = TRY_CONVERT(bigint, COALESCE(
        (SELECT JSON_VALUE(ed.Contenido, '$.idSolicitud') FROM Auditoria.vw_EventoDetalle AS ed
         WHERE ed.AuditoriaID = :id),
        (SELECT a.IdObjetivo FROM Auditoria.vw_Bitacora AS a
         WHERE a.AuditoriaID = :id AND a.TipoObjetivo = 'Seguridad.SolicitudAprobacion')))""")
_TIPOS = text(
    "SELECT CodigoEvento, Modulo, Severidad FROM Auditoria.TipoEvento "
    "WHERE Estado = 'A' ORDER BY Modulo, CodigoEvento"
)


def _alcance(agencias: tuple[str, ...] | None) -> dict[str, Any]:
    """None = todas las agencias. Una lista vacía no ve ninguna fila con agencia."""
    return {"todas": int(agencias is None), "agencias": list(agencias or ("",))}


def _rango(desde: date, hasta: date) -> dict[str, datetime]:
    """Días de la institución [desde, hasta] en UTC y en hora local (formato anterior)."""
    inicio = datetime.combine(desde, time())
    fin = datetime.combine(hasta + timedelta(days=1), time())
    return {
        "utc_desde": inicio + _DESFASE_UTC,
        "utc_hasta": fin + _DESFASE_UTC,
        "local_desde": inicio,
        "local_hasta": fin,
    }


def buscar_eventos(
    conn: Connection,
    filtros: dict[str, Any],
    agencias: tuple[str, ...] | None,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    """`filtros` trae desde y hasta (obligatorios) y los demás filtros opcionales."""
    params: dict[str, Any] = {
        clave: filtros.get(clave)
        for clave in (
            "usuario",
            "agencia",
            "modulo",
            "codigo_evento",
            "resultado",
            "tipo_objetivo",
            "id_objetivo",
            "origen",
            "canal",
            "correlacion",
        )
    }
    solicitud = filtros.get("id_solicitud")
    params["id_solicitud"] = None if solicitud is None else str(solicitud)
    params |= _rango(filtros["desde"], filtros["hasta"]) | _alcance(agencias)
    total = conn.execute(_CONTAR_BUSQUEDA, params).scalar_one()
    params |= {"offset": (page - 1) * page_size, "page_size": page_size}
    filas = conn.execute(_PAGINA_BUSQUEDA, params).mappings().all()
    return [dict(f) for f in filas], int(total)


def eventos_objetivo(
    conn: Connection,
    tipo: str,
    id_objetivo: str,
    agencias: tuple[str, ...] | None,
    page: int,
    page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    params: dict[str, Any] = {"tipo": tipo, "id_objetivo": id_objetivo} | _alcance(
        agencias
    )
    total = conn.execute(_CONTAR_OBJETIVO, params).scalar_one()
    params |= {"offset": (page - 1) * page_size, "page_size": page_size}
    filas = conn.execute(_PAGINA_OBJETIVO, params).mappings().all()
    return [dict(f) for f in filas], int(total)


def obtener_evento(conn: Connection, id_auditoria: int) -> dict[str, Any] | None:
    fila = conn.execute(_EVENTO, {"id": id_auditoria}).mappings().first()
    return dict(fila) if fila else None


def obtener_aprobacion(conn: Connection, id_auditoria: int) -> dict[str, Any] | None:
    """Solicitud vinculada por el detalle del relevo (E0-08) o porque es el objetivo."""
    fila = conn.execute(_APROBACION, {"id": id_auditoria}).mappings().first()
    return dict(fila) if fila else None


def obtener_relacionados(
    conn: Connection,
    correlacion: str,
    id_auditoria: int,
    agencias: tuple[str, ...] | None,
) -> list[dict[str, Any]]:
    """Los demás eventos de la misma petición, del más antiguo al más reciente."""
    params = {"correlacion": correlacion, "id": id_auditoria} | _alcance(agencias)
    return [dict(f) for f in conn.execute(_RELACIONADOS, params).mappings().all()]


def listar_tipos_evento(conn: Connection) -> list[dict[str, Any]]:
    return [dict(f) for f in conn.execute(_TIPOS).mappings().all()]
