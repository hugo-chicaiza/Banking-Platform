from datetime import date

from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.core.api.schemas import CamelModel
from app.core.csv import enmascarar_documento
from app.modules.clientes import documentos_identidad as identidad
from app.modules.clientes import repository, service
from app.modules.clientes.schemas import (
    ConsultaDocumentoBody,
    DocumentoCambio,
    DocumentoNuevo,
    DocumentoPrincipal,
)


class DocumentoFicha(CamelModel):
    id_documento: int
    tipo_documento: str
    nombre_tipo: str
    numero: str
    codigo_pais_emision: str | None
    fecha_emision: date | None
    fecha_vencimiento: date | None
    principal: bool
    tipo_activo: bool
    permite_principal: bool
    estado: str
    version: str


def _documentos(conn: Connection, id_cliente: int, id_documento: int | None = None):
    return conn.execute(
        text("""
            SELECT d.IdDocumento AS id_documento, d.TipoDocumento AS tipo_documento,
                t.Nombre AS nombre_tipo, d.Numero AS numero, d.CodigoPaisEmision AS codigo_pais_emision,
                d.FechaEmision AS fecha_emision, d.FechaVencimiento AS fecha_vencimiento,
                d.Principal AS principal, t.Activo AS tipo_activo, t.PermitePrincipal AS permite_principal,
                d.Estado AS estado, CONVERT(varchar(16), d.Version, 2) AS version,
                t.RequiereVencimiento AS requiere_vencimiento, t.RequierePais AS requiere_pais,
                t.AplicaNatural AS aplica_natural, t.AplicaJuridico AS aplica_juridico
            FROM Clientes.ClienteDocumento d
            JOIN Catalogo.TipoDocumentoIdentidad t WITH (HOLDLOCK) ON t.Codigo = d.TipoDocumento
            WHERE d.IdCliente = :cliente AND (:documento IS NULL OR d.IdDocumento = :documento)
            ORDER BY d.Principal DESC, d.IdDocumento
        """),
        {"cliente": id_cliente, "documento": id_documento},
    ).mappings()


def _estado(fila, fecha: date) -> str:
    if fila["estado"] != "REGISTRADO":
        return fila["estado"]
    vencimiento = fila["fecha_vencimiento"]
    if vencimiento is not None and vencimiento < fecha:
        return "VENCIDO"
    if (fila["requiere_vencimiento"] and vencimiento is None) or (
        fila["requiere_pais"] and fila["codigo_pais_emision"] is None
    ):
        return "POR_COMPLETAR"
    return "VIGENTE"


def _vista(fila, fecha: date) -> DocumentoFicha:
    return DocumentoFicha.model_validate(
        {
            **fila,
            "numero": enmascarar_documento(fila["numero"]),
            "estado": _estado(fila, fecha),
        }
    )


def listar(conn: Connection, id_cliente: int, fecha: date) -> list[DocumentoFicha]:
    service._validar_cliente_existe(conn, id_cliente)
    return [_vista(fila, fecha) for fila in _documentos(conn, id_cliente)]


def _cliente_editable(conn: Connection, id_cliente: int):
    cliente = service._validar_cliente_existe(conn, id_cliente, bloquear=True)
    service._validar_cliente_no_eliminado(cliente, id_cliente)
    return cliente


def _leer(conn: Connection, cliente: int, documento: int):
    fila = _documentos(conn, cliente, documento).first()
    if fila is None:
        raise problema(
            404, "DOCUMENTO_NO_ENCONTRADO", "El documento no pertenece a esta ficha."
        )
    return fila


def _historial(
    conn, cliente, actor, ip, motivo, anterior=None, nuevo=None, solicitud=None
):
    repository.insertar_historial_cliente(
        conn,
        id_cliente=cliente,
        tipo_operacion="U",
        campo="DocumentoIdentidad",
        modificado_por=actor,
        direccion_ip=ip,
        observaciones=motivo,
        valor_anterior=anterior,
        valor_nuevo=nuevo,
        id_solicitud=solicitud,
    )


def agregar(
    conn: Connection,
    cliente: int,
    datos: DocumentoNuevo,
    fecha: date,
    actor: int,
    ip: str,
):
    ficha = _cliente_editable(conn, cliente)
    regla = identidad.validar(conn, datos)
    aplicable = (
        "AplicaNatural" if ficha["tipo_cliente"] == "Natural" else "AplicaJuridico"
    )
    if not regla["Activo"] or not regla[aplicable]:
        raise problema(
            422, "DOCUMENTO_INVALIDO", "El tipo no está habilitado para esta ficha."
        )
    identidad.validar_fechas(
        datos.fecha_emision,
        datos.fecha_vencimiento,
        fecha,
        regla["RequiereVencimiento"],
    )
    identidad.bloquear_identidad(conn, datos)
    resultado = identidad.buscar(
        conn, datos, fecha, requiere_vencimiento=regla["RequiereVencimiento"]
    )
    if resultado.existe and not (
        resultado.tipo_coincidencia == "EQUIVALENCIA"
        and resultado.id_cliente == cliente
    ):
        raise problema(
            409,
            "DOCUMENTO_DUPLICADO",
            "La identificación ya está registrada o requiere revisión.",
        )
    nuevo = identidad.insertar(
        conn,
        cliente,
        datos.model_copy(update={"numero": datos.numero.upper()}),
        datos.fecha_emision,
        datos.fecha_vencimiento,
        principal=False,
    )
    _historial(conn, cliente, actor, ip, datos.motivo, nuevo=str(nuevo))
    return _vista(_leer(conn, cliente, nuevo), fecha)


def actualizar(
    conn: Connection,
    cliente: int,
    documento: int,
    datos: DocumentoCambio,
    fecha: date,
    actor: int,
    ip: str,
) -> DocumentoFicha:
    _cliente_editable(conn, cliente)
    fila = _leer(conn, cliente, documento)
    if fila["version"].upper() != datos.version.upper():
        raise problema(
            409, "SOLICITUD_DESACTUALIZADA", "Recarga la ficha antes de modificarla."
        )
    if fila["estado"] == "ANULADO":
        raise problema(409, "DOCUMENTO_ANULADO", "El documento ya está anulado.")
    if datos.accion == "RENOVAR":
        if fila["estado"] != "REGISTRADO":
            raise problema(
                409,
                "DOCUMENTO_POR_CORREGIR",
                "Registra el documento correcto para reemplazarlo.",
            )
        emisor = datos.codigo_pais_emision or fila["codigo_pais_emision"]
        if (
            fila["codigo_pais_emision"] is not None
            and emisor != fila["codigo_pais_emision"]
        ):
            raise problema(
                422,
                "DOCUMENTO_INVALIDO",
                "El emisor de un documento registrado no se cambia.",
            )
        consulta = ConsultaDocumentoBody(
            tipo_documento=fila["tipo_documento"],
            numero=fila["numero"],
            codigo_pais_emision=emisor,
        )
        identidad.validar(conn, consulta)
        identidad.validar_fechas(
            datos.fecha_emision,
            datos.fecha_vencimiento,
            fecha,
            fila["requiere_vencimiento"],
        )
        if emisor != fila["codigo_pais_emision"]:
            identidad.bloquear_identidad(conn, consulta)
            existe = conn.execute(
                text("""SELECT 1 FROM Clientes.ClienteDocumento
                        WHERE TipoDocumento = :tipo AND Numero = :numero
                          AND CodigoPaisEmision = :emisor AND IdDocumento <> :documento"""),
                {
                    "tipo": fila["tipo_documento"],
                    "numero": fila["numero"],
                    "emisor": emisor,
                    "documento": documento,
                },
            ).scalar()
            if existe:
                raise problema(
                    409, "DOCUMENTO_DUPLICADO", "El documento ya está registrado."
                )
        sql = """UPDATE Clientes.ClienteDocumento
            SET FechaEmision=:FechaEmision, FechaVencimiento=:FechaVencimiento,
                CodigoPaisEmision=:CodigoPaisEmision
            WHERE IdDocumento=:documento"""
        cambios = {
            "FechaEmision": datos.fecha_emision,
            "FechaVencimiento": datos.fecha_vencimiento,
            "CodigoPaisEmision": emisor,
        }
    else:
        if datos.accion == "ANULAR" and fila["principal"]:
            raise problema(
                409,
                "DOCUMENTO_PRINCIPAL",
                "Solicita una corrección con otro documento vigente.",
            )
        sql = "UPDATE Clientes.ClienteDocumento SET Estado=:Estado WHERE IdDocumento=:documento"
        cambios = {"Estado": "ANULADO" if datos.accion == "ANULAR" else "POR_CORREGIR"}

    conn.execute(text(sql), {"documento": documento, **cambios})
    anterior = f"{documento} · {fila['fecha_emision']} · {fila['fecha_vencimiento']} · {fila['estado']}"
    nuevo = f"{documento} · {datos.fecha_emision} · {datos.fecha_vencimiento} · {datos.accion}"
    _historial(conn, cliente, actor, ip, datos.motivo, anterior, nuevo)
    return _vista(_leer(conn, cliente, documento), fecha)


def validar_principal(
    conn: Connection,
    cliente: int,
    documento: int,
    datos: DocumentoPrincipal,
    fecha: date,
):
    ficha = _cliente_editable(conn, cliente)
    fila = _leer(conn, cliente, documento)
    aplicable = (
        "aplica_natural" if ficha["tipo_cliente"] == "Natural" else "aplica_juridico"
    )
    if fila["version"].upper() != datos.version.upper() or fila["principal"]:
        raise problema(
            409, "SOLICITUD_DESACTUALIZADA", "Cambió el documento seleccionado."
        )
    if (
        not (fila["tipo_activo"] and fila["permite_principal"] and fila[aplicable])
        or _estado(fila, fecha) != "VIGENTE"
    ):
        raise problema(
            409,
            "DOCUMENTO_NO_HABILITADO",
            "El documento debe estar vigente y su tipo activo.",
        )
    return fila


def aplicar_principal(
    conn: Connection,
    cliente: int,
    documento: int,
    datos: DocumentoPrincipal,
    fecha: date,
    actor: int,
    ip: str,
    solicitud: int,
) -> None:
    fila = validar_principal(conn, cliente, documento, datos, fecha)
    anteriores = (
        conn.execute(
            text("""SELECT IdDocumento FROM Clientes.ClienteDocumento
                WHERE IdCliente = :cliente AND Principal = 1"""),
            {"cliente": cliente},
        )
        .scalars()
        .all()
    )
    conn.execute(
        text("""UPDATE Clientes.ClienteDocumento
                SET Principal = 0, Estado = CASE WHEN :anular = 1 THEN 'ANULADO' ELSE Estado END
                WHERE IdCliente = :cliente AND Principal = 1"""),
        {"cliente": cliente, "anular": datos.anular_anterior},
    )
    conn.execute(
        text(
            "UPDATE Clientes.ClienteDocumento SET Principal = 1 WHERE IdDocumento = :documento"
        ),
        {"documento": documento},
    )
    conn.execute(
        text("""UPDATE Clientes.Cliente SET Identificacion = :numero, TipoDocumento = :tipo
                WHERE IdCliente = :cliente"""),
        {
            "numero": fila["numero"],
            "tipo": identidad.ANTERIORES.get(
                fila["tipo_documento"], fila["tipo_documento"]
            ),
            "cliente": cliente,
        },
    )
    _historial(
        conn,
        cliente,
        actor,
        ip,
        datos.motivo,
        ",".join(map(str, anteriores)),
        str(documento),
        solicitud,
    )
