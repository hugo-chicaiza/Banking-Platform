import re
from datetime import date
from hashlib import sha256

from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.modules.clientes import repository, service
from app.modules.clientes.schemas import (
    ClienteCreate,
    ConsultaDocumentoBody,
    TipoDocumentoIdentidad,
    ValidacionIdentificacion,
)

CODIGOS = {"C": "CED", "R": "RUC", "P": "PAS"}
ANTERIORES = {codigo: anterior for anterior, codigo in CODIGOS.items()}


def listar_tipos(conn: Connection) -> list[TipoDocumentoIdentidad]:
    filas = conn.execute(
        text("""
            SELECT Codigo AS codigo, Nombre AS nombre, Algoritmo AS algoritmo,
                   PatronCaracteres AS patron_caracteres, LongitudMinima AS longitud_minima,
                   LongitudMaxima AS longitud_maxima, AplicaNatural AS aplica_natural,
                   AplicaJuridico AS aplica_juridico, RequierePais AS requiere_pais,
                   RequiereVencimiento AS requiere_vencimiento,
                   DigitoVerificadorBloquea AS digito_verificador_bloquea,
                   PermitePrincipal AS permite_principal, AccionAlVencer AS accion_al_vencer,
                   Activo AS activo, CONVERT(varchar(16), Version, 2) AS version
            FROM Catalogo.TipoDocumentoIdentidad
            ORDER BY Nombre, Codigo
        """)
    ).mappings()
    return [TipoDocumentoIdentidad.model_validate(fila) for fila in filas]


def consultar(
    conn: Connection, payload: ConsultaDocumentoBody, fecha: date
) -> ValidacionIdentificacion:
    regla = validar(conn, payload)
    resultado = buscar(
        conn,
        payload,
        fecha,
        requiere_vencimiento=regla["RequiereVencimiento"],
        requiere_pais=regla.get("RequierePais", False),
    )
    return resultado.model_copy(
        update={
            "advertencias": regla["Advertencias"],
            "version_reglas": regla.get("VersionReglas"),
        }
    )


def validar(conn: Connection, payload: ConsultaDocumentoBody):
    tipo = payload.tipo_documento
    numero = payload.numero.upper()
    emisor = payload.codigo_pais_emision
    regla = (
        conn.execute(
            text("""
            SELECT Algoritmo, PatronCaracteres, LongitudMinima, LongitudMaxima,
                   RequierePais, RequiereVencimiento, Activo, PermitePrincipal, AplicaNatural, AplicaJuridico,
                   DigitoVerificadorBloquea, CONVERT(varchar(16), Version, 2) AS VersionReglas
            FROM Catalogo.TipoDocumentoIdentidad WITH (HOLDLOCK) WHERE Codigo = :tipo
        """),
            {"tipo": tipo},
        )
        .mappings()
        .first()
    )
    if regla is None:
        raise problema(422, "DOCUMENTO_INVALIDO", "Tipo de documento desconocido.")
    patron = r"[0-9]+" if regla["PatronCaracteres"] == "DIGITOS" else r"[A-Za-z0-9]+"
    if not (
        regla["LongitudMinima"] <= len(payload.numero) <= regla["LongitudMaxima"]
        and re.fullmatch(patron, payload.numero)
    ):
        raise problema(422, "DOCUMENTO_INVALIDO", "Longitud o caracteres no admitidos.")
    advertencias: list[str] = []
    algoritmo = regla["Algoritmo"]
    if algoritmo in {"EC_CEDULA", "EC_RUC"}:
        validador = (
            service.validar_cedula_ecuatoriana
            if algoritmo == "EC_CEDULA"
            else service.validar_ruc
        )
        valido, motivo = validador(numero)
        if not valido:
            if (
                tipo not in {"CED", "RUC"}
                and not regla.get("DigitoVerificadorBloquea", True)
                and motivo.endswith(service.ERROR_DIGITO_CEDULA)
            ):
                advertencias.append(motivo)
            else:
                raise problema(422, "DOCUMENTO_INVALIDO", motivo)
    if (regla["RequierePais"] and not emisor) or (
        emisor is not None and not repository.existe_pais(conn, emisor)
    ):
        raise problema(422, "DOCUMENTO_INVALIDO", "Indica un país emisor del catálogo.")

    return {**regla, "Advertencias": advertencias}


def buscar(
    conn: Connection,
    payload: ConsultaDocumentoBody,
    fecha: date,
    *,
    requiere_vencimiento: bool,
    requiere_pais: bool = False,
) -> ValidacionIdentificacion:
    tipo = payload.tipo_documento
    numero = payload.numero.upper()
    emisor = payload.codigo_pais_emision
    exacta = True
    fila = _buscar(conn, tipo, numero, emisor if tipo == "PAS" else None)
    if fila is None and tipo in {"CED", "RUC"}:
        cedula = numero if tipo == "CED" else numero[:10]
        if service.validar_cedula_ecuatoriana(cedula)[0]:
            exacta = False
            equivalente = _buscar(
                conn,
                "RUC" if tipo == "CED" else "CED",
                cedula + "001" if tipo == "CED" else cedula,
                None,
            )
            if equivalente is not None and equivalente["tipo_cliente"] == "Natural":
                fila = equivalente
    if fila is None:
        return ValidacionIdentificacion(
            valida=True, existe=False, mensaje="Formato correcto."
        )

    estado = fila["estado_documento"]
    if estado in {"POR_CORREGIR", "ANULADO"} or (
        tipo == "PAS" and fila["emisor"] is None
    ):
        return ValidacionIdentificacion(
            valida=True,
            existe=True,
            mensaje="La identificación requiere revisión.",
            estado_documento=(
                estado if estado in {"POR_CORREGIR", "ANULADO"} else "POR_COMPLETAR"
            ),
        )
    vencimiento = fila["vencimiento"]
    estado_documento = None
    if exacta:
        if vencimiento is not None and vencimiento < fecha:
            estado_documento = "VENCIDO"
        elif (
            requiere_pais
            and fila["emisor"] != emisor
            or vencimiento is None
            and requiere_vencimiento
        ):
            estado_documento = "POR_COMPLETAR"
        else:
            estado_documento = "VIGENTE"
    return ValidacionIdentificacion(
        valida=True,
        existe=True,
        id_cliente=fila["id_cliente"],
        mensaje="Se encontró una ficha con esta identificación.",
        reincorporable=fila["estado_cliente"] == "Eliminado",
        estado=fila["estado_cliente"],
        tipo_coincidencia="EXACTA" if exacta else "EQUIVALENCIA",
        estado_documento=estado_documento,
    )


def _buscar(conn: Connection, tipo: str, numero: str, emisor: str | None):
    return (
        conn.execute(
            text("""
            SELECT TOP (1) id_cliente, estado_cliente, tipo_cliente,
                           estado_documento, emisor, vencimiento
            FROM (
                SELECT c.IdCliente AS id_cliente, c.Estado AS estado_cliente,
                       c.TipoCliente AS tipo_cliente, d.Estado AS estado_documento,
                       d.CodigoPaisEmision AS emisor, d.FechaVencimiento AS vencimiento,
                       CASE WHEN :tipo = 'PAS' AND d.CodigoPaisEmision IS NULL THEN 0 ELSE 1 END AS orden
                FROM Clientes.ClienteDocumento d
                JOIN Clientes.Cliente c ON c.IdCliente = d.IdCliente
                WHERE d.TipoDocumento = :tipo AND d.Numero = :numero
                  AND (:tipo <> 'PAS' OR d.CodigoPaisEmision = :emisor OR d.CodigoPaisEmision IS NULL)
                UNION ALL
                SELECT c.IdCliente, c.Estado, c.TipoCliente, 'REGISTRADO', NULL, NULL,
                       CASE WHEN :tipo = 'PAS' THEN 0 ELSE 2 END
                FROM Clientes.Cliente c
                WHERE c.TipoDocumento = :tipo_anterior AND c.Identificacion = :numero
                  AND NOT EXISTS (
                      SELECT 1 FROM Clientes.ClienteDocumento d
                      WHERE d.IdCliente = c.IdCliente AND d.Principal = 1
                  )
            ) coincidencias
            ORDER BY orden, id_cliente
        """),
            {
                "tipo": tipo,
                "numero": numero,
                "emisor": emisor,
                "tipo_anterior": ANTERIORES.get(tipo),
            },
        )
        .mappings()
        .first()
    )


def bloquear_identidad(conn: Connection, consulta: ConsultaDocumentoBody) -> None:
    tipo, numero = consulta.tipo_documento, consulta.numero.upper()
    if tipo in {"CED", "RUC"} and service.validar_cedula_ecuatoriana(numero[:10])[0]:
        clave = f"CED-RUC:{numero[:10]}"
    else:
        emisor = consulta.codigo_pais_emision if tipo == "PAS" else ""
        clave = f"{tipo}:{emisor}:{numero}"
    recurso = "clientes-documento:" + sha256(clave.encode()).hexdigest()
    resultado = conn.execute(
        text("""
            SET NOCOUNT ON;
            DECLARE @resultado int;
            EXEC @resultado = sys.sp_getapplock @Resource=:recurso, @LockMode='Exclusive',
                @LockOwner='Transaction', @LockTimeout=5000;
            SELECT @resultado;
        """),
        {"recurso": recurso},
    ).scalar_one()
    if resultado < 0:
        raise problema(
            409, "DOCUMENTO_EN_PROCESO", "Otra operación está validando el documento."
        )


def preparar_alta(
    conn: Connection, payload: ClienteCreate, fecha: date
) -> ConsultaDocumentoBody:
    consulta = ConsultaDocumentoBody(
        tipo_documento=CODIGOS.get(payload.tipo_documento, payload.tipo_documento),
        numero=payload.identificacion.upper(),
        codigo_pais_emision=payload.codigo_pais_emision,
    )
    regla = validar(conn, consulta)
    aplicable = (
        "AplicaNatural" if payload.tipo_cliente == "Natural" else "AplicaJuridico"
    )
    if not (regla["Activo"] and regla["PermitePrincipal"] and regla[aplicable]):
        raise problema(
            422,
            "DOCUMENTO_INVALIDO",
            "El tipo no puede ser principal para este cliente.",
        )
    validar_fechas(
        payload.fecha_emision,
        payload.fecha_vencimiento,
        fecha,
        regla["RequiereVencimiento"],
    )
    if payload.fecha_vencimiento is not None and payload.fecha_vencimiento < fecha:
        raise problema(
            422, "DOCUMENTO_VENCIDO", "El documento principal debe estar vigente."
        )
    bloquear_identidad(conn, consulta)
    coincidencia = buscar(
        conn, consulta, fecha, requiere_vencimiento=regla["RequiereVencimiento"]
    )
    if coincidencia.reincorporable:
        raise problema(
            409, "CLIENTE_ELIMINADO", "Puede solicitar la reincorporación del cliente."
        )
    if coincidencia.existe:
        raise problema(
            409,
            "DOCUMENTO_DUPLICADO",
            "La identificación ya está registrada o requiere revisión.",
        )
    return consulta


def validar_fechas(
    emision: date | None, vencimiento: date | None, hoy: date, requerido: bool
) -> None:
    if requerido and vencimiento is None:
        raise problema(422, "VENCIMIENTO_REQUERIDO", "Indica la fecha de vencimiento.")
    if emision and (emision > hoy or (vencimiento and emision > vencimiento)):
        raise problema(
            422, "FECHAS_DOCUMENTO_INVALIDAS", "Revisa las fechas del documento."
        )


def insertar(
    conn: Connection,
    id_cliente: int,
    consulta: ConsultaDocumentoBody,
    emision: date | None,
    vencimiento: date | None,
    *,
    principal: bool,
) -> int:
    return conn.execute(
        text("""
            SET NOCOUNT ON;
            DECLARE @nuevo TABLE (IdDocumento bigint);
            INSERT INTO Clientes.ClienteDocumento
                (IdCliente, TipoDocumento, Numero, CodigoPaisEmision, FechaEmision,
                 FechaVencimiento, Principal)
            OUTPUT inserted.IdDocumento INTO @nuevo
            VALUES (:cliente, :tipo, :numero, :pais, :emision, :vencimiento, :principal);
            SELECT IdDocumento FROM @nuevo;
        """),
        {
            "cliente": id_cliente,
            "tipo": consulta.tipo_documento,
            "numero": consulta.numero,
            "pais": consulta.codigo_pais_emision,
            "emision": emision,
            "vencimiento": vencimiento,
            "principal": principal,
        },
    ).scalar_one()
