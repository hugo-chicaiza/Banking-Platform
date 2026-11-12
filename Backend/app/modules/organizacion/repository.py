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
