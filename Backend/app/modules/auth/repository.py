"""SQL de AUT-01 (vínculo) y AUT-05..09 (usuarios internos).

SeguridadDB: Organizacion.Usuarios y Seguridad.Bloqueos. CooperativaDB: agencias y
Caja.CajerosAsignadosAgencia. Solo consultas fijas: los filtros opcionales van como
`(:x IS NULL OR ...)` y el orden con CASE, nunca texto concatenado.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, RowMapping, bindparam, text

Fila = RowMapping


# --- AUT-01: vínculo con WorkOS ------------------------------------------------------


def vincular(conn: Connection, id_workos: str, email: str) -> bool:
    """Guarda KeyUsuario en el usuario Activo de ese email que aún no tiene vínculo.

    False si no hay a quién vincular o si el id de WorkOS ya está vinculado.
    """
    resultado = conn.execute(
        text(
            """
            UPDATE Organizacion.Usuarios
            SET KeyUsuario = :id_workos
            WHERE Email = :email
              AND KeyUsuario IS NULL
              AND Estado = 'Activo'
              AND NOT EXISTS (
                  SELECT 1 FROM Organizacion.Usuarios WHERE KeyUsuario = :id_workos
              )
            """
        ),
        {"id_workos": id_workos, "email": email},
    )
    return resultado.rowcount == 1


def vinculado_a_otro(conn: Connection, id_workos: str, id_usuario: int) -> bool:
    """True si ese id de WorkOS ya es el KeyUsuario de otro usuario interno."""
    return (
        conn.execute(
            text(
                "SELECT 1 FROM Organizacion.Usuarios "
                "WHERE KeyUsuario = :id_workos AND UsuarioID <> :id_usuario"
            ),
            {"id_workos": id_workos, "id_usuario": id_usuario},
        ).first()
        is not None
    )


def vincular_por_id(conn: Connection, id_usuario: int, id_workos: str) -> bool:
    """Guarda KeyUsuario en ese usuario si aún no tiene vínculo (AUT-08/09)."""
    resultado = conn.execute(
        text(
            "UPDATE Organizacion.Usuarios SET KeyUsuario = :id_workos "
            "WHERE UsuarioID = :id_usuario AND KeyUsuario IS NULL"
        ),
        {"id_workos": id_workos, "id_usuario": id_usuario},
    )
    return resultado.rowcount == 1


def registrar_acceso(conn: Connection, id_workos: str) -> None:
    conn.execute(
        text(
            "UPDATE Organizacion.Usuarios SET UltimoAcceso = GETDATE() "
            "WHERE KeyUsuario = :id_workos"
        ),
        {"id_workos": id_workos},
    )


# --- AUT-05: listado -----------------------------------------------------------------

# Los mismos filtros en las dos consultas: si cambia uno, cambiar el otro
_CONTAR = text(
    """
    SELECT COUNT_BIG(*)
    FROM Organizacion.Usuarios
    WHERE (:q IS NULL
           OR NombreUsuario LIKE :q ESCAPE '\\'
           OR Nombres LIKE :q ESCAPE '\\'
           OR Apellidos LIKE :q ESCAPE '\\'
           OR Email LIKE :q ESCAPE '\\')
      AND (:estado IS NULL OR Estado = :estado)
      AND (:agencia IS NULL OR AgenciaID = :agencia)
      AND (:rol IS NULL OR ',' + RolesWorkOS + ',' LIKE '%,' + :rol + ',%')
      AND (:vinculado IS NULL
           OR (:vinculado = 1 AND KeyUsuario IS NOT NULL)
           OR (:vinculado = 0 AND KeyUsuario IS NULL))
    """
)

_LISTAR = text(
    """
    SELECT UsuarioID, NombreUsuario, Nombres, Apellidos, Email, Estado, FechaCreacion,
           UltimoAcceso, Cedula, AgenciaID, KeyUsuario, RolesWorkOS
    FROM Organizacion.Usuarios
    WHERE (:q IS NULL
           OR NombreUsuario LIKE :q ESCAPE '\\'
           OR Nombres LIKE :q ESCAPE '\\'
           OR Apellidos LIKE :q ESCAPE '\\'
           OR Email LIKE :q ESCAPE '\\')
      AND (:estado IS NULL OR Estado = :estado)
      AND (:agencia IS NULL OR AgenciaID = :agencia)
      AND (:rol IS NULL OR ',' + RolesWorkOS + ',' LIKE '%,' + :rol + ',%')
      AND (:vinculado IS NULL
           OR (:vinculado = 1 AND KeyUsuario IS NOT NULL)
           OR (:vinculado = 0 AND KeyUsuario IS NULL))
    ORDER BY
        CASE WHEN :orden = 'username,asc' THEN NombreUsuario END ASC,
        CASE WHEN :orden = 'username,desc' THEN NombreUsuario END DESC,
        CASE WHEN :orden = 'nombres,asc' THEN Nombres END ASC,
        CASE WHEN :orden = 'nombres,desc' THEN Nombres END DESC,
        CASE WHEN :orden = 'apellidos,asc' THEN Apellidos END ASC,
        CASE WHEN :orden = 'apellidos,desc' THEN Apellidos END DESC,
        CASE WHEN :orden = 'email,asc' THEN Email END ASC,
        CASE WHEN :orden = 'email,desc' THEN Email END DESC,
        CASE WHEN :orden = 'estado,asc' THEN Estado END ASC,
        CASE WHEN :orden = 'estado,desc' THEN Estado END DESC,
        CASE WHEN :orden = 'fechaCreacion,asc' THEN FechaCreacion END ASC,
        CASE WHEN :orden = 'fechaCreacion,desc' THEN FechaCreacion END DESC,
        UsuarioID DESC
    OFFSET :offset ROWS FETCH NEXT :page_size ROWS ONLY
    """
)


def _patron(q: str | None) -> str | None:
    if not q:
        return None
    # Comodines de LIKE en SQL Server: % _ [ (se escapan con ESCAPE '\')
    escapado = q
    for caracter in ("\\", "%", "_", "["):
        escapado = escapado.replace(caracter, "\\" + caracter)
    return "%" + escapado + "%"


def listar_usuarios(
    conn: Connection,
    *,
    q: str | None,
    estado: str | None,
    agencia_id: int | None,
    rol: str | None,
    vinculado: bool | None,
    orden: str,
    page: int,
    page_size: int,
) -> tuple[list[Fila], int]:
    filtros: dict[str, Any] = {
        "q": _patron(q),
        "estado": estado,
        "agencia": agencia_id,
        "rol": rol,
        "vinculado": None if vinculado is None else int(vinculado),
    }
    total = conn.execute(_CONTAR, filtros).scalar_one()
    filas = (
        conn.execute(
            _LISTAR,
            {
                **filtros,
                "orden": orden,
                "offset": (page - 1) * page_size,
                "page_size": page_size,
            },
        )
        .mappings()
        .all()
    )
    return list(filas), int(total)


# --- AUT-06..09: un usuario ----------------------------------------------------------

_OBTENER = text(
    """
    SELECT UsuarioID, NombreUsuario, Nombres, Apellidos, Email, Estado, FechaCreacion,
           UltimoAcceso, Cedula, AgenciaID, KeyUsuario, RolesWorkOS
    FROM Organizacion.Usuarios
    WHERE UsuarioID = :id
    """
)
# UPDLOCK: dos administradores no editan el mismo usuario a la vez
_OBTENER_BLOQUEANDO = text(
    """
    SELECT UsuarioID, NombreUsuario, Nombres, Apellidos, Email, Estado, FechaCreacion,
           UltimoAcceso, Cedula, AgenciaID, KeyUsuario, RolesWorkOS
    FROM Organizacion.Usuarios WITH (UPDLOCK, ROWLOCK)
    WHERE UsuarioID = :id
    """
)


def obtener_usuario(
    conn: Connection, id_usuario: int, bloquear: bool = False
) -> Fila | None:
    consulta = _OBTENER_BLOQUEANDO if bloquear else _OBTENER
    return conn.execute(consulta, {"id": id_usuario}).mappings().first()


def existe_duplicado(
    conn: Connection,
    *,
    username: str | None,
    email: str | None,
    cedula: str | None,
    excluir_id: int | None = None,
) -> bool:
    fila = conn.execute(
        text(
            """
            SELECT TOP (1) 1
            FROM Organizacion.Usuarios
            WHERE (:excluir IS NULL OR UsuarioID <> :excluir)
              AND (NombreUsuario = :username OR Email = :email OR Cedula = :cedula)
            """
        ),
        {
            "username": username,
            "email": email,
            "cedula": cedula,
            "excluir": excluir_id,
        },
    ).first()
    return fila is not None


def insertar_usuario(
    conn: Connection,
    *,
    username: str,
    nombres: str,
    apellidos: str,
    email: str,
    cedula: str,
    agencia_id: int,
    rol: str,
) -> int:
    """KeyUsuario queda NULL hasta el primer login (vínculo)."""
    return int(
        conn.execute(
            text(
                """
                INSERT INTO Organizacion.Usuarios (
                    NombreUsuario, Nombres, Apellidos, Email, Estado,
                    IntentosFallidos, Cedula, AgenciaID, RolesWorkOS
                )
                OUTPUT INSERTED.UsuarioID
                VALUES (
                    :username, :nombres, :apellidos, :email, 'Activo',
                    0, :cedula, :agencia, :rol
                )
                """
            ),
            {
                "username": username,
                "nombres": nombres,
                "apellidos": apellidos,
                "email": email,
                "cedula": cedula,
                "agencia": agencia_id,
                "rol": rol,
            },
        ).scalar_one()
    )


def actualizar_usuario(
    conn: Connection,
    id_usuario: int,
    *,
    nombres: str | None,
    apellidos: str | None,
    email: str | None,
    estado: str | None,
    agencia_id: int | None,
) -> None:
    """None = sin cambio. Al desbloquear se reinician los intentos fallidos."""
    conn.execute(
        text(
            """
            UPDATE Organizacion.Usuarios
            SET Nombres = COALESCE(:nombres, Nombres),
                Apellidos = COALESCE(:apellidos, Apellidos),
                Email = COALESCE(:email, Email),
                IntentosFallidos = CASE
                    WHEN :estado = 'Activo' AND Estado = 'Bloqueado' THEN 0
                    ELSE IntentosFallidos
                END,
                Estado = COALESCE(:estado, Estado),
                AgenciaID = COALESCE(:agencia, AgenciaID)
            WHERE UsuarioID = :id
            """
        ),
        {
            "id": id_usuario,
            "nombres": nombres,
            "apellidos": apellidos,
            "email": email,
            "estado": estado,
            "agencia": agencia_id,
        },
    )


def actualizar_rol(conn: Connection, id_usuario: int, rol: str) -> None:
    conn.execute(
        text(
            "UPDATE Organizacion.Usuarios SET RolesWorkOS = :rol WHERE UsuarioID = :id"
        ),
        {"id": id_usuario, "rol": rol},
    )


def contar_activos_vinculados(
    conn: Connection, ids_workos: Sequence[str], excluir_id: int
) -> int:
    """Usuarios Activo cuya KeyUsuario está en la lista, sin contar a excluir_id."""
    if not ids_workos:
        return 0
    consulta = text(
        """
        SELECT COUNT_BIG(*)
        FROM Organizacion.Usuarios
        WHERE Estado = 'Activo'
          AND KeyUsuario IN :ids
          AND UsuarioID <> :excluir
        """
    ).bindparams(bindparam("ids", expanding=True))
    return int(
        conn.execute(
            consulta, {"ids": list(ids_workos), "excluir": excluir_id}
        ).scalar_one()
    )


# --- Seguridad.Bloqueos (AUT-08) -----------------------------------------------------


def bloqueo_vigente(conn: Connection, id_usuario: int) -> Fila | None:
    return (
        conn.execute(
            text(
                """
                SELECT TOP (1) BloqueoID, MotivoBloqueo, FechaBloqueo, Observaciones
                FROM Seguridad.Bloqueos
                WHERE UsuarioID = :id AND FechaDesbloqueo IS NULL
                ORDER BY FechaBloqueo DESC, BloqueoID DESC
                """
            ),
            {"id": id_usuario},
        )
        .mappings()
        .first()
    )


def abrir_bloqueo(
    conn: Connection,
    id_usuario: int,
    *,
    motivo: str,
    observaciones: str | None,
    bloqueado_por: int,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO Seguridad.Bloqueos (
                UsuarioID, MotivoBloqueo, BloqueadoPor, Observaciones
            )
            VALUES (:id, :motivo, :por, :observaciones)
            """
        ),
        {
            "id": id_usuario,
            "motivo": motivo,
            "por": bloqueado_por,
            "observaciones": observaciones,
        },
    )


def cerrar_bloqueos(conn: Connection, id_usuario: int, desbloqueado_por: int) -> None:
    conn.execute(
        text(
            """
            UPDATE Seguridad.Bloqueos
            SET FechaDesbloqueo = GETDATE(), DesbloqueadoPor = :por
            WHERE UsuarioID = :id AND FechaDesbloqueo IS NULL
            """
        ),
        {"id": id_usuario, "por": desbloqueado_por},
    )


# --- CooperativaDB: agencias y asignación de cajeros ---------------------------------


def agencia_activa(conn: Connection, id_agencia: str) -> bool:
    fila = conn.execute(
        text(
            "SELECT 1 FROM Organizacion.Agencia WHERE IdAgencia = :id AND Estado = 'A'"
        ),
        {"id": id_agencia},
    ).first()
    return fila is not None


def asignacion_vigente(conn: Connection, id_usuario: int) -> Fila | None:
    return (
        conn.execute(
            text(
                """
                SELECT TOP (1) IdHistorialUsuarioAgencia, RTRIM(IdAgencia) AS IdAgencia
                FROM Caja.CajerosAsignadosAgencia
                WHERE IdUsuario = :id AND Estado = 1 AND FechaFin IS NULL
                ORDER BY FechaInicio DESC
                """
            ),
            {"id": id_usuario},
        )
        .mappings()
        .first()
    )


def cerrar_asignacion(conn: Connection, id_usuario: int) -> None:
    """FechaFin y Estado = 0 a la vez: lo exige CK_CajerosAsignadosAgencia_Vigente.
    Hora de Ecuador, igual que Caja (datetime2 sin zona).
    """
    conn.execute(
        text(
            """
            UPDATE Caja.CajerosAsignadosAgencia
            SET FechaFin = CAST(
                    SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'
                    AS datetime2
                ),
                Estado = 0
            WHERE IdUsuario = :id AND Estado = 1 AND FechaFin IS NULL
            """
        ),
        {"id": id_usuario},
    )


def abrir_asignacion(
    conn: Connection,
    id_usuario: int,
    id_agencia: str,
    *,
    asignado_por: int,
    motivo: str,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO Caja.CajerosAsignadosAgencia (
                IdUsuario, IdAgencia, FechaInicio, AsignadoPor, Motivo, Estado
            )
            VALUES (
                :id,
                :agencia,
                CAST(
                    SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time'
                    AS datetime2
                ),
                :por,
                :motivo,
                1
            )
            """
        ),
        {
            "id": id_usuario,
            "agencia": id_agencia,
            "por": asignado_por,
            "motivo": motivo,
        },
    )


def fecha(valor: object) -> datetime | None:
    return valor if isinstance(valor, datetime) else None
