"""SQL parametrizado de asignaciones y contexto; sin cambios WorkOS."""

from typing import Any

from sqlalchemy import Connection, text


def principal_asignada(conn: Connection, usuario: int) -> str | None:
    """Agencia principal explícita y activa, sin recurrir a datos anteriores."""
    return conn.scalar(
        text("""
            SELECT RTRIM(a.IdAgencia)
            FROM Organizacion.UsuarioAgencia a
            JOIN Organizacion.Usuarios u ON u.UsuarioID = a.UsuarioID
            WHERE a.UsuarioID = :id AND a.Activo = 1
              AND TRY_CONVERT(int, a.IdAgencia) = u.AgenciaID
        """),
        {"id": usuario},
    )


def tiene_cajeros_vigentes(conn: Connection, agencia: str) -> bool:
    return (
        conn.scalar(
            text("""
            SELECT TOP (1) 1
            FROM Organizacion.UsuarioAgencia a
            JOIN Organizacion.Usuarios u ON u.UsuarioID = a.UsuarioID
            WHERE a.IdAgencia = :agencia AND a.Activo = 1 AND u.Estado = 'Activo'
              AND TRY_CONVERT(int, a.IdAgencia) = u.AgenciaID
              AND ',' + COALESCE(u.RolesWorkOS, '') + ',' LIKE '%,CAJERO,%'
        """),
            {"agencia": agencia},
        )
        == 1
    )


def asignaciones(conn: Connection, usuario: int) -> list[str]:
    return list(
        conn.scalars(
            text(
                """SELECT RTRIM(IdAgencia) AS IdAgencia FROM Organizacion.UsuarioAgencia WHERE UsuarioID=:id AND Activo=1
                UNION ALL SELECT RIGHT('000'+CONVERT(varchar(3),u.AgenciaID),3) AS IdAgencia
                FROM Organizacion.Usuarios u WHERE u.UsuarioID=:id AND u.AgenciaID IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM Organizacion.UsuarioAgencia a WHERE a.UsuarioID=u.UsuarioID)
                ORDER BY IdAgencia"""
            ),
            {"id": usuario},
        )
    )


def usuario_por_llave(conn: Connection, llave: str) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text(
                "SELECT UsuarioID, AgenciaID, Estado FROM Organizacion.Usuarios WHERE KeyUsuario=:llave"
            ),
            {"llave": llave},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def agencias(conn: Connection) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            text(
                "SELECT RTRIM(IdAgencia) AS id_agencia, Codigo AS codigo, "
                "Estado AS estado, TipoAgencia AS tipo_agencia "
                "FROM Organizacion.Agencia ORDER BY IdAgencia"
            )
        ).mappings()
    ]


def es_matriz(conn: Connection, agencia: str) -> bool:
    return (
        conn.scalar(
            text("""
            SELECT 1 FROM Organizacion.Agencia
            WHERE IdAgencia = :agencia AND Estado = 'A' AND TipoAgencia = 'Matriz'
        """),
            {"agencia": agencia},
        )
        == 1
    )


def version(conn: Connection, usuario: int) -> int:
    return int(
        conn.scalar(
            text(
                "SELECT ISNULL(MAX(IdHistorial),0) FROM Organizacion.UsuarioAgenciaHistorial WHERE UsuarioID=:id"
            ),
            {"id": usuario},
        )
        or 0
    )


def historico(
    conn: Connection,
    usuario: int,
    accion: str,
    agencia: str | None,
    anterior: str | None,
    nueva: str | None,
    actor: int,
    agencia_actor: str | None,
) -> None:
    conn.execute(
        text("""INSERT Organizacion.UsuarioAgenciaHistorial(UsuarioID,IdAgencia,Accion,PrincipalAnterior,PrincipalNueva,RealizadoPor,AgenciaActor)
        VALUES (:id,:agencia,:accion,:anterior,:nueva,:actor,:agencia_actor)"""),
        {
            "id": usuario,
            "agencia": agencia,
            "accion": accion,
            "anterior": anterior,
            "nueva": nueva,
            "actor": actor,
            "agencia_actor": agencia_actor,
        },
    )


def guardar_asignacion(
    conn: Connection, usuario: int, agencia: str, activa: bool, actor: int
) -> None:
    params = {"id": usuario, "agencia": agencia, "activa": activa, "actor": actor}
    conn.execute(
        text("""UPDATE Organizacion.UsuarioAgencia SET Activo=:activa, AsignadoPor=:actor,
        Origen='Administrador', FechaAsignacion=SYSUTCDATETIME() WHERE UsuarioID=:id AND IdAgencia=:agencia;
        IF @@ROWCOUNT=0 INSERT Organizacion.UsuarioAgencia(UsuarioID,IdAgencia,Activo,AsignadoPor,Origen)
        VALUES (:id,:agencia,:activa,:actor,'Administrador');"""),
        params,
    )


def principal(conn: Connection, usuario: int, agencia: str | None) -> None:
    conn.execute(
        text("UPDATE Organizacion.Usuarios SET AgenciaID=:agencia WHERE UsuarioID=:id"),
        {"id": usuario, "agencia": int(agencia) if agencia else None},
    )


def contexto(conn: Connection, sid: bytes, usuario: int) -> dict[str, Any] | None:
    row = (
        conn.execute(
            text(
                "SELECT RTRIM(IdAgencia) AS agencia, CASE WHEN ExpiraUTC>SYSUTCDATETIME() THEN 1 ELSE 0 END AS vigente FROM Seguridad.ContextoAgenciaSesion WHERE IdSesionHash=:sid AND UsuarioID=:id"
            ),
            {"sid": sid, "id": usuario},
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def guardar_contexto(conn: Connection, sid: bytes, usuario: int, agencia: str) -> None:
    conn.execute(
        text("""UPDATE Seguridad.ContextoAgenciaSesion WITH (UPDLOCK, SERIALIZABLE) SET IdAgencia=:agencia, FechaCambioUTC=SYSUTCDATETIME(),
        ExpiraUTC=DATEADD(hour,8,SYSUTCDATETIME()) WHERE IdSesionHash=:sid AND UsuarioID=:id;
        IF @@ROWCOUNT=0 INSERT Seguridad.ContextoAgenciaSesion(IdSesionHash,UsuarioID,IdAgencia,ExpiraUTC)
        VALUES (:sid,:id,:agencia,DATEADD(hour,8,SYSUTCDATETIME()));"""),
        {"sid": sid, "id": usuario, "agencia": agencia},
    )


def trasladar_contextos_vigentes(
    conn: Connection, usuario: int, anterior: str, nueva: str
) -> None:
    conn.execute(
        text("""
            UPDATE Seguridad.ContextoAgenciaSesion
            SET IdAgencia = :nueva, FechaCambioUTC = SYSUTCDATETIME()
            WHERE UsuarioID = :usuario AND IdAgencia = :anterior
              AND ExpiraUTC > SYSUTCDATETIME()
        """),
        {"usuario": usuario, "anterior": anterior, "nueva": nueva},
    )


def historial(
    conn: Connection, usuario: int, page: int, size: int
) -> tuple[list[dict[str, Any]], int]:
    params = {"id": usuario, "offset": (page - 1) * size, "size": size}
    rows = (
        conn.execute(
            text("""SELECT h.IdHistorial AS id_historial, RTRIM(h.IdAgencia) AS id_agencia, h.Accion AS accion,
        RTRIM(h.PrincipalAnterior) AS principal_anterior,RTRIM(h.PrincipalNueva) AS principal_nueva,
        h.RealizadoPor AS realizado_por,
        NULLIF(LTRIM(RTRIM(CONCAT(a.Nombres,' ',a.Apellidos))), '') AS nombre_actor,
        RTRIM(h.AgenciaActor) AS agencia_actor,h.FechaUTC AS fecha_utc
        FROM Organizacion.UsuarioAgenciaHistorial h
        LEFT JOIN Organizacion.Usuarios a ON a.UsuarioID=h.RealizadoPor
        WHERE h.UsuarioID=:id ORDER BY h.IdHistorial DESC
        OFFSET :offset ROWS FETCH NEXT :size ROWS ONLY"""),
            params,
        )
        .mappings()
        .all()
    )
    total = conn.scalar(
        text(
            "SELECT COUNT(*) FROM Organizacion.UsuarioAgenciaHistorial WHERE UsuarioID=:id"
        ),
        {"id": usuario},
    )
    return [dict(r) for r in rows], int(total or 0)


def inicializar_contexto(
    conn: Connection, sid: bytes, usuario: int, agencia: str
) -> None:
    conn.execute(
        text("""INSERT Seguridad.ContextoAgenciaSesion(IdSesionHash,UsuarioID,IdAgencia,ExpiraUTC)
        SELECT :sid,:id,:agencia,DATEADD(hour,8,SYSUTCDATETIME())
        WHERE NOT EXISTS (SELECT 1 FROM Seguridad.ContextoAgenciaSesion WITH (UPDLOCK,HOLDLOCK)
                          WHERE IdSesionHash=:sid)"""),
        {"sid": sid, "id": usuario, "agencia": agencia},
    )


def eliminar_contexto(conn: Connection, sid: bytes, usuario: int) -> None:
    conn.execute(
        text(
            "DELETE FROM Seguridad.ContextoAgenciaSesion WHERE IdSesionHash=:sid AND UsuarioID=:id"
        ),
        {"sid": sid, "id": usuario},
    )
