from typing import Any

from sqlalchemy import Connection, text

# Lista blanca de columnas permitidas para ordenar.
# Debe contrastarse con los valores autorizados en openapi.yaml.
SORT_COLUMNS = {
    "idCliente": "c.IdCliente",
    "identificacion": "c.Identificacion",
    "nombres": "c.Nombres",
    "apellidos": "c.Apellidos",
    "fechaRegistro": "c.FechaRegistro",
    "estado": "c.Estado",
}


def listar_clientes(
    conn: Connection,
    *,
    q: str | None = None,
    identificacion: str | None = None,
    tipo_cliente: str | None = None,
    estado: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort: str = "idCliente,asc",
) -> dict[str, Any]:
    filtros = []
    params: dict[str, Any] = {}

    if q:
        filtros.append(
            """(
                c.Nombres LIKE :q
                OR c.Apellidos LIKE :q
                OR c.RazonSocial LIKE :q
                OR c.Identificacion LIKE :q
            )"""
        )
        params["q"] = f"%{q}%"

    if identificacion:
        filtros.append("c.Identificacion = :identificacion")
        params["identificacion"] = identificacion

    if tipo_cliente:
        filtros.append("c.TipoCliente = :tipo_cliente")
        params["tipo_cliente"] = tipo_cliente

    if estado:
        filtros.append("c.Estado = :estado")
        params["estado"] = estado

    where_clause = "WHERE " + " AND ".join(filtros) if filtros else ""

    campo, direccion = sort.split(",", maxsplit=1)

    if campo not in SORT_COLUMNS:
        raise ValueError("Campo de ordenamiento no permitido")

    direccion = direccion.lower()

    if direccion not in ("asc", "desc"):
        raise ValueError("Dirección de ordenamiento no permitida")

    order_column = SORT_COLUMNS[campo]
    order_direction = direccion.upper()

    params["offset"] = (page - 1) * page_size
    params["page_size"] = page_size

    total = conn.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM Clientes.Cliente c
            {where_clause}
            """
        ),
        params,
    ).scalar_one()

    clientes = (
        conn.execute(
            text(
                f"""
            SELECT
                c.IdCliente AS id_cliente,
                c.Identificacion AS identificacion,
                c.TipoDocumento AS tipo_documento,
                c.TipoCliente AS tipo_cliente,
                c.Nombres AS nombres,
                c.Apellidos AS apellidos,
                c.IdActividadEconomica AS id_actividad_economica,
                c.FechaNacimiento AS fecha_nacimiento,
                c.Genero AS genero,
                c.EstadoCivil AS estado_civil,
                c.CodigoPaisNacionalidad AS codigo_pais_nacionalidad,
                c.TelefonoConvencional AS telefono_convencional,
                c.TelefonoCelular AS telefono_celular,
                c.Email AS email,
                c.ConsentimientoDatos AS consentimiento_datos,
                c.FechaConsentimiento AS fecha_consentimiento,
                c.Estado AS estado,
                c.FechaRegistro AS fecha_registro,
                c.CreadoPor AS creado_por
            FROM Clientes.Cliente c
            {where_clause}
            ORDER BY {order_column} {order_direction},
                     c.IdCliente ASC
            OFFSET :offset ROWS
            FETCH NEXT :page_size ROWS ONLY
            """
            ),
            params,
        )
        .mappings()
        .all()
    )

    items = [dict(cliente) for cliente in clientes]

    if items:
        ids = [cliente["id_cliente"] for cliente in items]

        # Los IDs son valores parametrizados, no SQL concatenado
        from sqlalchemy import bindparam

        direcciones_query = text(
            """
            SELECT
                IdDireccion AS id_direccion,
                IdCliente AS id_cliente,
                TipoDireccion AS tipo_direccion,
                IdCiudad AS id_ciudad,
                Sector AS sector,
                CalleDireccion AS calle_direccion,
                ReferenciaUbicacion AS referencia_ubicacion,
                CodigoPostal AS codigo_postal,
                EsPrincipal AS es_principal,
                Estado AS estado
            FROM Clientes.Direcciones
            WHERE IdCliente IN :ids
            ORDER BY IdCliente, EsPrincipal DESC, IdDireccion
            """
        ).bindparams(bindparam("ids", expanding=True))

        direcciones = (
            conn.execute(
                direcciones_query,
                {"ids": ids},
            )
            .mappings()
            .all()
        )

        direcciones_por_cliente: dict[int, list[dict[str, Any]]] = {
            cliente_id: [] for cliente_id in ids
        }

        for direccion in direcciones:
            dato = dict(direccion)
            cliente_id = dato.pop("id_cliente")
            dato["codigo_pais"] = None

            direcciones_por_cliente[cliente_id].append(dato)

        for cliente in items:
            cliente["direcciones"] = direcciones_por_cliente[cliente["id_cliente"]]

    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }
