"""Acceso a Organizacion.Agencia y lecturas de dependencias (solo SELECT en otros esquemas).

SQL parametrizado; los nombres de columna salen de constantes de este archivo, nunca de
la petición.
"""

from typing import Any

from sqlalchemy import Connection, column, select, table, text, update

_COLUMNAS_ENTIDAD = {
    "id_entidad": "IdEntidad",
    "ruc": "RUC",
    "razon_social": "RazonSocial",
    "nombre_comercial": "NombreComercial",
    "tipo_organizacion": "TipoOrganizacion",
    "segmento": "Segmento",
    "numero_resolucion_seps": "NumeroResolucionSEPS",
    "fecha_constitucion": "FechaConstitucion",
    "representante_legal": "RepresentanteLegal",
    "identificacion_representante": "IdentificacionRepresentante",
    "telefono": "Telefono",
    "email": "Email",
    "sitio_web": "SitioWeb",
    "estado": "Estado",
    "fecha_registro": "FechaRegistro",
    "modificado_por": "ModificadoPor",
}
_TABLA_ENTIDAD = table(
    "Entidad",
    *(column(nombre) for nombre in _COLUMNAS_ENTIDAD.values()),
    schema="Organizacion",
)

Fila = dict[str, Any]

# Campo de la API -> columna. Solo estos se pueden actualizar con el PATCH.
COLUMNAS_EDITABLES = {
    "codigo": "Codigo",
    "tipo_agencia": "TipoAgencia",
    "estado": "Estado",
    "id_ciudad": "IdCiudad",
    "telefono": "Telefono",
    "direccion": "Direccion",
    "key_agencia": "KeyAgencia",
}


def _fila(conn: Connection, sql: str, parametros: dict[str, Any]) -> Fila | None:
    fila = conn.execute(text(sql), parametros).mappings().first()
    return dict(fila) if fila is not None else None


_SELECT_AGENCIA = """
    SELECT IdAgencia, Codigo, TipoAgencia, Estado, IdCiudad, Telefono, Direccion,
           FechaCreacion,
           CAST(CASE WHEN KeyAgencia IS NULL THEN 0 ELSE 1 END AS bit) AS VinculadaWorkos
    FROM Organizacion.Agencia {pista}
    WHERE IdAgencia = :id
"""
_LEER_AGENCIA = text(_SELECT_AGENCIA.replace("{pista}", ""))
# Bloqueo exclusivo hasta el commit: dos PATCH de la misma agencia se serializan
_LEER_AGENCIA_BLOQUEADA = text(
    _SELECT_AGENCIA.replace("{pista}", "WITH (UPDLOCK, HOLDLOCK)")
)


def obtener_agencia(
    conn: Connection, id_agencia: str, *, bloquear: bool = False
) -> Fila | None:
    sentencia = _LEER_AGENCIA_BLOQUEADA if bloquear else _LEER_AGENCIA
    fila = conn.execute(sentencia, {"id": id_agencia}).mappings().first()
    return dict(fila) if fila is not None else None


def existe_ciudad(conn: Connection, id_ciudad: int) -> bool:
    """Catalogo.Ciudad no tiene columna de estado: solo se puede validar que exista."""
    return (
        conn.execute(
            text("SELECT 1 FROM Catalogo.Ciudad WHERE IdCiudad = :id"),
            {"id": id_ciudad},
        ).first()
        is not None
    )


def conflictos_de_unicidad(
    conn: Connection,
    *,
    id_agencia: str,
    codigo: str | None,
    key_agencia: str | None,
    matriz: bool,
) -> set[str]:
    """Qué restricciones únicas violaría la fila (sin contar la propia agencia).

    UPDLOCK + HOLDLOCK: otra creación con el mismo código, clave o una segunda Matriz
    espera a este commit. Los índices únicos siguen siendo la garantía final.
    """
    fila = _fila(
        conn,
        """
        SELECT
            CAST(CASE WHEN :codigo IS NOT NULL AND EXISTS (
                SELECT 1 FROM Organizacion.Agencia WITH (UPDLOCK, HOLDLOCK)
                WHERE Codigo = :codigo AND IdAgencia <> :id) THEN 1 ELSE 0 END AS bit)
                AS Codigo,
            CAST(CASE WHEN :key IS NOT NULL AND EXISTS (
                SELECT 1 FROM Organizacion.Agencia WITH (UPDLOCK, HOLDLOCK)
                WHERE KeyAgencia = :key AND IdAgencia <> :id) THEN 1 ELSE 0 END AS bit)
                AS KeyAgencia,
            CAST(CASE WHEN :matriz = 1 AND EXISTS (
                SELECT 1 FROM Organizacion.Agencia WITH (UPDLOCK, HOLDLOCK)
                WHERE TipoAgencia = 'Matriz' AND IdAgencia <> :id) THEN 1 ELSE 0 END
                AS bit) AS Matriz
        """,
        {"id": id_agencia, "codigo": codigo, "key": key_agencia, "matriz": int(matriz)},
    )
    return {nombre for nombre, valor in (fila or {}).items() if valor}


def insertar_agencia(conn: Connection, datos: dict[str, Any]) -> None:
    """Estado y FechaCreacion quedan con los defaults de la tabla."""
    conn.execute(
        text(
            """
            INSERT INTO Organizacion.Agencia (
                IdAgencia, Codigo, TipoAgencia, IdCiudad, Telefono, Direccion,
                KeyAgencia
            )
            VALUES (
                :id_agencia, :codigo, :tipo_agencia, :id_ciudad, :telefono,
                :direccion, :key_agencia
            )
            """
        ),
        datos,
    )


_UPDATE_AGENCIA = text(
    """
    UPDATE Organizacion.Agencia
    SET Codigo = CASE WHEN :con_codigo = 1 THEN :codigo ELSE Codigo END,
        TipoAgencia = CASE WHEN :con_tipo_agencia = 1 THEN :tipo_agencia
                           ELSE TipoAgencia END,
        Estado = CASE WHEN :con_estado = 1 THEN :estado ELSE Estado END,
        IdCiudad = CASE WHEN :con_id_ciudad = 1 THEN :id_ciudad ELSE IdCiudad END,
        Telefono = CASE WHEN :con_telefono = 1 THEN :telefono ELSE Telefono END,
        Direccion = CASE WHEN :con_direccion = 1 THEN :direccion ELSE Direccion END,
        KeyAgencia = CASE WHEN :con_key_agencia = 1 THEN :key_agencia
                          ELSE KeyAgencia END
    WHERE IdAgencia = :id_agencia_actual
    """
)


def actualizar_agencia(
    conn: Connection, id_agencia: str, cambios: dict[str, Any]
) -> int:
    """SQL fijo: cada columna se escribe solo si su campo viene en `cambios`."""
    desconocidos = set(cambios) - set(COLUMNAS_EDITABLES)
    if desconocidos:
        raise ValueError(f"Campos no editables: {sorted(desconocidos)}")
    parametros: dict[str, Any] = {"id_agencia_actual": id_agencia}
    for campo in COLUMNAS_EDITABLES:
        parametros[f"con_{campo}"] = int(campo in cambios)
        parametros[campo] = cambios.get(campo)
    return int(conn.execute(_UPDATE_AGENCIA, parametros).rowcount)


# --- Dependencias que impiden desactivar ------------------------------------------
# Recursos activos y operaciones en curso, no historial. Solo columnas y valores que
# ya usan los módulos dueños (anexo B y su código): Caja ('ABIERTA', Estado bit),
# Boveda/ATM ('A'), Cuentas ('Activa'), Credito ('PENDIENTE'). HOLDLOCK: una nueva
# jornada, caja, asignación o cuenta en la agencia espera a que termine el cambio.
DEPENDENCIAS_ACTIVAS: dict[str, str] = {
    "jornadas abiertas": (
        "SELECT TOP (1) 1 FROM Caja.JornadasCaja WITH (HOLDLOCK) "
        "WHERE IdAgencia = :id AND Estado = 'ABIERTA'"
    ),
    "cajas físicas activas": (
        "SELECT TOP (1) 1 FROM Caja.CajaFisica WITH (HOLDLOCK) "
        "WHERE IdAgencia = :id AND Estado = 1"
    ),
    "cajeros asignados vigentes": (
        "SELECT TOP (1) 1 FROM Caja.CajerosAsignadosAgencia WITH (HOLDLOCK) "
        "WHERE IdAgencia = :id AND Estado = 1 AND (FechaFin IS NULL OR FechaFin > "
        "CAST(SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time' AS datetime2))"
    ),
    "bóvedas activas": (
        "SELECT TOP (1) 1 FROM Boveda.Boveda WITH (HOLDLOCK) "
        "WHERE IdAgencia = :id AND Estado = 'A'"
    ),
    "ATM activos": (
        "SELECT TOP (1) 1 FROM ATM.ATM WITH (HOLDLOCK) "
        "WHERE IdAgencia = :id AND Estado = 'A'"
    ),
    "cuentas activas": (
        "SELECT TOP (1) 1 FROM Cuentas.Cuenta WITH (HOLDLOCK) "
        "WHERE IdAgencia = :id AND Estado = 'Activa'"
    ),
    "desembolsos de crédito pendientes": (
        "SELECT TOP (1) 1 FROM Credito.CreditoDesembolso WITH (HOLDLOCK) "
        "WHERE IdAgencia = :id AND Estado = 'PENDIENTE'"
    ),
}


def dependencias_activas(conn: Connection, id_agencia: str) -> list[str]:
    """Nombres (en el orden de DEPENDENCIAS_ACTIVAS) de lo que sigue activo."""
    return [
        nombre
        for nombre, sql in DEPENDENCIAS_ACTIVAS.items()
        if conn.execute(text(sql), {"id": id_agencia}).first() is not None
    ]


# Compatibilidad con endpoint de estado y guard de asignación existentes.
def bloquear_agencia(conn: Connection, id_agencia: str) -> dict[str, Any] | None:
    fila = (
        conn.execute(
            text("""
            SELECT IdAgencia AS id_agencia, Estado AS estado
            FROM Organizacion.Agencia WITH (UPDLOCK, HOLDLOCK)
            WHERE IdAgencia = :id
        """),
            {"id": id_agencia},
        )
        .mappings()
        .one_or_none()
    )
    return dict(fila) if fila is not None else None


def actualizar_estado(
    conn: Connection, id_agencia: str, anterior: str, nuevo: str
) -> bool:
    resultado = conn.execute(
        text("""
            UPDATE Organizacion.Agencia SET Estado = :nuevo
            WHERE IdAgencia = :id AND Estado = :anterior
        """),
        {"id": id_agencia, "anterior": anterior, "nuevo": nuevo},
    )
    return resultado.rowcount == 1


def obtener_entidad(
    conn: Connection, *, bloquear: bool = False
) -> dict[str, Any] | None:
    consulta = select(
        *(
            _TABLA_ENTIDAD.c[nombre].label(campo)
            for campo, nombre in _COLUMNAS_ENTIDAD.items()
        )
    ).where(_TABLA_ENTIDAD.c.IdEntidad == 1)
    if bloquear:
        consulta = consulta.with_hint(
            _TABLA_ENTIDAD, "WITH (UPDLOCK, HOLDLOCK)", dialect_name="mssql"
        )
    fila = conn.execute(consulta).mappings().one_or_none()
    return dict(fila) if fila is not None else None


def actualizar_entidad(
    conn: Connection, cambios: dict[str, Any], modificado_por: int
) -> None:
    """Actualiza únicamente columnas permitidas mediante parámetros de SQLAlchemy."""
    editables = _COLUMNAS_ENTIDAD.keys() - {
        "id_entidad",
        "fecha_registro",
        "modificado_por",
    }
    valores = {
        _COLUMNAS_ENTIDAD[campo]: valor
        for campo, valor in cambios.items()
        if campo in editables
    }
    valores["ModificadoPor"] = modificado_por
    conn.execute(
        update(_TABLA_ENTIDAD).where(_TABLA_ENTIDAD.c.IdEntidad == 1).values(valores)
    )
