import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection

from app.core.api.errors import problema
from app.modules.clientes import repository
from app.modules.clientes.schemas import (
    Cliente,
    ClienteCreate,
    ClienteEstadoUpdate,
    ClienteHistorial,
    ClientePerfil,
    ClienteUpdate,
    CreditoPerfil,
    CuentaPerfil,
    Direccion,
    DireccionNueva,
    DireccionUpdate,
    EstadoCliente,
    PageCliente,
    PageClienteHistorial,
    Riesgo,
    RiesgoCreate,
    RiesgoRegistrado,
    TarjetaPerfil,
    TipoCliente,
    TipoDocumento,
    ValidacionIdentificacion,
)
from app.modules.cuentas.schemas import ID_MONEDA_USD

_COEFICIENTES_MOD10 = [2, 1, 2, 1, 2, 1, 2, 1, 2]

CAMPOS_ORDEN_CLIENTES = {
    "idCliente": "IdCliente",
    "identificacion": "Identificacion",
    "tipoCliente": "TipoCliente",
    "nombres": "Nombres",
    "apellidos": "Apellidos",
    "razonSocial": "RazonSocial",
    "estado": "Estado",
    "fechaRegistro": "FechaRegistro",
}


def _problema(status: int, code: str, detail: str) -> HTTPException:
    return problema(status, code, detail)


def _orden_clientes(sort: str | None) -> tuple[str, str]:
    return _orden_permitido(sort, CAMPOS_ORDEN_CLIENTES, ("IdCliente", "asc"))


def _orden_permitido(
    sort: str | None, campos: dict[str, str], defecto: tuple[str, str]
) -> tuple[str, str]:
    if sort is None:
        return defecto
    partes = sort.split(",")
    if len(partes) != 2 or partes[0] not in campos or partes[1] not in ("asc", "desc"):
        raise _problema(
            400, "SORT_INVALIDO", "Use un campo permitido y la dirección asc o desc."
        )
    return campos[partes[0]], partes[1]


def listar_historial_cliente(
    conn: Connection,
    id_cliente: int,
    *,
    page: int = 1,
    page_size: int = 20,
    sort: str | None = None,
) -> PageClienteHistorial:
    """Historial de cualquier cliente, incluidos los eliminados (CLI-07)."""
    campo, direccion = _orden_permitido(
        sort,
        {
            "idHistorial": "IdHistorial",
            "fechaModificacion": "FechaModificacion",
            "tipoOperacion": "TipoOperacion",
            "campoModificado": "CampoModificado",
            "modificadoPor": "ModificadoPor",
        },
        ("FechaModificacion", "desc"),
    )
    if page < 1 or not 1 <= page_size <= 100:
        raise problema(422, "PAGINACION_INVALIDA", "La paginación no es válida.")
    _validar_cliente_existe(conn, id_cliente)
    filas, total = repository.listar_historial_cliente(
        conn,
        id_cliente,
        page=page,
        page_size=page_size,
        campo=campo,
        direccion=direccion,
    )
    return PageClienteHistorial(
        items=[_historial_desde_fila(fila) for fila in filas],
        page=page,
        page_size=page_size,
        total=total,
    )


def _historial_desde_fila(fila: dict[str, Any]) -> ClienteHistorial:
    datos = {**fila, "valor_anterior": None}
    try:
        observaciones = json.loads(fila["observaciones"])
    except (ValueError, TypeError):
        observaciones = None
    if (
        isinstance(observaciones, dict)
        and type(observaciones.get("v")) is int
        and observaciones["v"] == 1
        and {"valorAnterior", "valorNuevo", "motivo"} <= observaciones.keys()
        and isinstance(observaciones["motivo"], str)
    ):
        anterior = observaciones["valorAnterior"]
        if anterior is None or type(anterior) in (str, int):
            datos["valor_anterior"] = None if anterior is None else str(anterior)
            fecha: datetime = datos["fecha_modificacion"]
            # Solo nuestros registros v1 se escriben en UTC; el legado no se reinterpreta.
            if fecha.tzinfo is None:
                datos["fecha_modificacion"] = fecha.replace(tzinfo=UTC)
    return ClienteHistorial(**datos)


def _cliente_bloqueado(conn: Connection, id_cliente: int) -> Cliente:
    if repository.bloquear_cliente(conn, id_cliente) is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "No se encontró el cliente.")
    return obtener_cliente(conn, id_cliente)


def _validar_tipo_persona(datos: dict[str, Any]) -> None:
    if datos["tipo_cliente"] == "Natural":
        valido = (
            bool(datos["apellidos"] and datos["genero"] and datos["estado_civil"])
            and datos["razon_social"] is None
        )
    else:
        valido = bool(datos["razon_social"]) and all(
            datos[campo] is None for campo in ("apellidos", "genero", "estado_civil")
        )
    if not valido:
        raise problema(
            422,
            "TIPO_PERSONA_INVALIDO",
            "Los datos finales no cumplen las reglas del tipo de persona.",
        )


def _guardar_cambios_cliente(
    conn: Connection,
    actual: Cliente,
    cambios: dict[str, Any],
    *,
    modificado_por: int,
    direccion_ip: str,
    motivo: str,
) -> Cliente:
    # Serializar todas las auditorías ANTES de la primera escritura.
    anteriores = actual.model_dump()
    auditorias = [
        (
            repository.CAMPOS_EDICION_CLIENTE.get(campo, "Estado"),
            repository.observaciones_cambio(anteriores[campo], valor, motivo),
        )
        for campo, valor in cambios.items()
    ]
    if "estado" in cambios:
        repository.actualizar_estado_cliente(conn, actual.id_cliente, cambios["estado"])
    else:
        repository.actualizar_cliente(conn, actual.id_cliente, cambios)
    for campo, observaciones in auditorias:
        repository.insertar_historial_cliente(
            conn,
            id_cliente=actual.id_cliente,
            tipo_operacion="U",
            campo=campo,
            modificado_por=modificado_por,
            direccion_ip=direccion_ip,
            observaciones=observaciones,
        )
    resultado = obtener_cliente(conn, actual.id_cliente)
    conn.commit()
    return resultado


def editar_cliente(
    conn: Connection,
    id_cliente: int,
    payload: ClienteUpdate,
    modificado_por: int,
    direccion_ip: str,
) -> Cliente:
    """CLI-05: snapshot, modificación, auditoría y lectura en una transacción."""
    try:
        actual = _cliente_bloqueado(conn, id_cliente)
        if actual.estado == "Eliminado":
            raise problema(
                409, "CLIENTE_NO_EDITABLE", "El cliente eliminado no se puede editar."
            )
        enviados = payload.model_dump(exclude_unset=True)
        finales = actual.model_dump() | enviados
        _validar_tipo_persona(finales)
        cambios = {
            campo: valor
            for campo, valor in enviados.items()
            if valor != getattr(actual, campo)
        }
        actividad = cambios.get("id_actividad_economica")
        if actividad is not None and not repository.existe_actividad_economica(
            conn, actividad
        ):
            raise problema(
                422, "CATALOGO_INVALIDO", "La actividad económica no existe."
            )
        if not cambios:
            conn.rollback()  # Libera el bloqueo de la lectura sin escrituras ni auditorías.
            return actual
        return _guardar_cambios_cliente(
            conn,
            actual,
            cambios,
            modificado_por=modificado_por,
            direccion_ip=direccion_ip,
            motivo="Actualización de datos",
        )
    except Exception:
        conn.rollback()
        raise


_TRANSICIONES_CLIENTE = {
    "Activo": {"Inactivo", "Suspendido", "Bloqueado", "Eliminado"},
    "Inactivo": {"Activo", "Eliminado"},
    "Suspendido": {"Activo", "Eliminado"},
    "Bloqueado": {"Activo", "Eliminado"},
    "Pendiente": {"Eliminado"},
    "Cerrado": {"Eliminado"},
    "Eliminado": set(),
}


def _deuda_no_verificable() -> HTTPException:
    return problema(
        503,
        "DEUDA_CLIENTE_NO_VERIFICABLE",
        "No se pudo comprobar la deuda vigente del cliente; revise el plan, cuotas y pagos.",
    )


def _importe(valor: Any) -> Decimal:
    try:
        importe = Decimal(str(valor))
    except InvalidOperation:
        raise _deuda_no_verificable() from None
    if not importe.is_finite() or importe < 0:
        raise _deuda_no_verificable()
    return importe


def _credito_tiene_deuda(conn: Connection, id_solicitud: int) -> bool:
    """CR-06/CR-07: cuotas vigentes menos abonos, pagos comprobados y mora.

    Un plan incompleto o un pago que no justifica sus componentes no demuestra
    deuda cero; se informa la brecha en lugar de autorizar la baja.
    """
    resumenes = repository.resumen_para_cambio_estado(conn, id_solicitud)
    cuotas = repository.cuotas_para_cambio_estado(conn, id_solicitud)
    if len(resumenes) != 1:
        raise _deuda_no_verificable()
    resumen = resumenes[0]
    cantidad = resumen["numero_total_cuotas"]
    if (
        cantidad < 1
        or len(cuotas) != cantidad
        or {c["numero"] for c in cuotas} != set(range(1, cantidad + 1))
        or any(
            c["version"] != resumen["version"] or c["id_cuota"] is None for c in cuotas
        )
    ):
        raise _deuda_no_verificable()
    # La mora agregada de toda la solicitud se repite por fila del plan.
    deuda = max(_importe(c["mora_pendiente"]) for c in cuotas)
    for cuota in cuotas:
        componentes = ("capital_pendiente", "interes", "seguros", "impuestos")
        importes = [_importe(cuota[c]) for c in componentes]
        if cuota["estado"] in ("PENDIENTE", "VENCIDA"):
            deuda += sum(importes, Decimal(0))
        elif cuota["estado"] == "PAGADA":
            pagos = (
                "capital_pagado",
                "interes_pagado",
                "seguros_pagados",
                "impuestos_pagados",
            )
            if any(cuota[c] is None for c in pagos) or any(
                _importe(cuota[c]) < requerido
                for c, requerido in zip(pagos, importes, strict=True)
            ):
                raise _deuda_no_verificable()
        else:
            raise _deuda_no_verificable()
    return deuda > 0


def credito_tiene_deuda(conn: Connection, id_solicitud: int) -> bool:
    """Regla de deuda compartida con CTA-05 hasta disponer del módulo créditos.

    Conserva los bloqueos y el rechazo de planes incompletos de CLI-06.
    """
    return _credito_tiene_deuda(conn, id_solicitud)


def _validar_productos_cliente(conn: Connection, id_cliente: int) -> None:
    cuentas = repository.cuentas_para_cambio_estado(conn, id_cliente)
    tiene_productos = any(
        c["estado"] in ("Activa", "Bloqueada")
        or _importe(c["saldo"]) > 0
        or _importe(c["saldo_retenido"]) > 0
        for c in cuentas
    )
    if not tiene_productos:
        desembolsos = repository.desembolsos_para_cambio_estado(conn, id_cliente)
        solicitudes = sorted(
            {d["id_solicitud"] for d in desembolsos if d["estado"] == "DESEMBOLSADO"}
        )
        tiene_productos = any(
            _credito_tiene_deuda(conn, solicitud) for solicitud in solicitudes
        )
    if tiene_productos:
        raise problema(
            409,
            "CLIENTE_CON_PRODUCTOS_VIGENTES",
            "El cliente conserva cuentas o créditos vigentes.",
        )


def cambiar_estado_cliente(
    conn: Connection,
    id_cliente: int,
    payload: ClienteEstadoUpdate,
    modificado_por: int,
    direccion_ip: str,
    roles: tuple[str, ...],
) -> Cliente:
    """CLI-06: roles de una identidad autenticada; mismo estado es conflicto."""
    if not set(roles) & {"ASESOR", "SUPERVISOR", "ADMIN"}:
        raise problema(403, "SIN_PERMISO", "No tiene permiso para esta operación.")
    try:
        actual = _cliente_bloqueado(conn, id_cliente)
        if payload.estado not in _TRANSICIONES_CLIENTE.get(actual.estado, set()):
            raise problema(
                409,
                "TRANSICION_CLIENTE_INVALIDA",
                "El cambio de estado no está permitido.",
            )
        if payload.estado in ("Inactivo", "Eliminado"):
            _validar_productos_cliente(conn, id_cliente)
        return _guardar_cambios_cliente(
            conn,
            actual,
            {"estado": payload.estado},
            modificado_por=modificado_por,
            direccion_ip=direccion_ip,
            motivo=payload.motivo,
        )
    except Exception:
        conn.rollback()
        raise


def listar_clientes(
    conn: Connection,
    *,
    q: str | None = None,
    identificacion: str | None = None,
    tipo_cliente: TipoCliente | None = None,
    estado: EstadoCliente | None = None,
    page: int = 1,
    page_size: int = 20,
    sort: str | None = None,
) -> PageCliente:
    """Busca clientes con filtros combinados y ordenamiento permitido (CLI-03)."""
    campo, direccion = _orden_clientes(sort)
    filas, total = repository.consultar_clientes(
        conn,
        q=q,
        identificacion=identificacion,
        tipo_cliente=tipo_cliente,
        estado=estado,
        page=page,
        page_size=page_size,
        campo=campo,
        direccion=direccion,
    )
    return PageCliente(
        items=[Cliente(**fila) for fila in filas],
        page=page,
        page_size=page_size,
        total=total,
    )


def obtener_cliente(conn: Connection, id_cliente: int) -> Cliente:
    """Detalle con direcciones exclusivamente activas, compartido con CLI-08."""
    fila = repository.obtener_cliente_detalle(conn, id_cliente)
    if fila is None:
        raise _problema(
            404,
            "CLIENTE_NO_ENCONTRADO",
            f"No se encontró un cliente con id {id_cliente}.",
        )
    return Cliente(**fila)


def obtener_perfil_cliente(conn: Connection, id_cliente: int) -> ClientePerfil:
    """Consulta integral de solo lectura; la ausencia de productos es válida."""
    cliente = obtener_cliente(conn, id_cliente)
    riesgos = repository.listar_evaluaciones_riesgo(conn, id_cliente, solo_vigente=True)
    return ClientePerfil(
        cliente=cliente,
        riesgo_vigente=Riesgo(**riesgos[0]) if riesgos else None,
        cuentas=[
            CuentaPerfil(**{**fila, "id_moneda": ID_MONEDA_USD})
            for fila in repository.listar_cuentas_perfil(conn, id_cliente)
        ],
        tarjetas=[
            TarjetaPerfil(**fila)
            for fila in repository.listar_tarjetas_perfil(conn, id_cliente)
        ],
        creditos=[
            CreditoPerfil(**fila)
            for fila in repository.listar_creditos_perfil(conn, id_cliente)
        ],
    )


# ---------------------------------------------------------------------------
# CLI-01 · Validación de Identificación
# ---------------------------------------------------------------------------


def validar_cedula_ecuatoriana(cedula: str) -> tuple[bool, str]:
    """Valida una cédula ecuatoriana con el algoritmo Módulo 10"""

    if len(cedula) != 10 or not cedula.isdigit():
        return False, "La cédula debe tener exactamente 10 dígitos numéricos."

    provincia = int(cedula[:2])
    if not (1 <= provincia <= 24 or provincia == 30):
        return (
            False,
            "Provincia inválida (los dos primeros dígitos deben estar entre 01-24 o ser 30).",
        )

    tercer_digito = int(cedula[2])
    if tercer_digito >= 6:
        return (
            False,
            "Tercer dígito inválido para persona natural (debe ser menor a 6).",
        )

    suma = 0
    for i in range(9):
        mult = int(cedula[i]) * _COEFICIENTES_MOD10[i]
        if mult >= 10:
            mult -= 9
        suma += mult

    digito_verificador_calculado = (10 - (suma % 10)) % 10
    digito_verificador_real = int(cedula[9])

    if digito_verificador_calculado != digito_verificador_real:
        return False, "Dígito verificador de la cédula no coincide."

    return True, "Cédula válida."


def validar_ruc(ruc: str) -> tuple[bool, str]:
    """Valida un RUC ecuatoriano de persona natural"""

    if len(ruc) != 13 or not ruc.isdigit():
        return False, "El RUC debe tener exactamente 13 dígitos numéricos."

    if not ruc.endswith("001"):
        return False, "El RUC de persona natural debe terminar en 001."

    base_cedula = ruc[:10]
    valida, motivo = validar_cedula_ecuatoriana(base_cedula)
    if not valida:
        return False, f"Base de cédula del RUC no es válida: {motivo}"

    return True, "RUC válido."


def validar_pasaporte(pasaporte: str) -> tuple[bool, str]:
    """Valida pasaporte: 5 a 13 caracteres alfanuméricos."""
    if not (5 <= len(pasaporte) <= 13 and pasaporte.isalnum()):
        return (
            False,
            "El pasaporte debe tener entre 5 y 13 caracteres alfanuméricos.",
        )
    return True, "Pasaporte válido."


def validar_formato_documento(
    tipo_documento: TipoDocumento, identificacion: str
) -> tuple[bool, str]:
    """Valida el formato offline del documento según su tipo."""
    doc = identificacion.strip()
    if tipo_documento == "C":
        return validar_cedula_ecuatoriana(doc)
    if tipo_documento == "R":
        return validar_ruc(doc)
    if tipo_documento == "P":
        return validar_pasaporte(doc)
    return False, f"Tipo de documento '{tipo_documento}' no reconocido."


def validar_identificacion(
    conn: Connection,
    tipo_documento: TipoDocumento,
    identificacion: str,
) -> ValidacionIdentificacion:
    """Ejecuta la validación de formato y verifica existencia en Clientes.Cliente"""
    doc = identificacion.strip()
    valida, motivo = validar_formato_documento(tipo_documento, doc)

    if not valida:
        return ValidacionIdentificacion(
            valida=False,
            existe=False,
            id_cliente=None,
            mensaje=motivo,
        )

    cliente = repository.obtener_cliente_por_identificacion(conn, doc)
    if cliente is not None:
        return ValidacionIdentificacion(
            valida=True,
            existe=True,
            id_cliente=cliente["id_cliente"],
            mensaje="Identificación ya registrada en el sistema.",
        )

    return ValidacionIdentificacion(
        valida=True,
        existe=False,
        id_cliente=None,
        mensaje="Identificación válida y disponible.",
    )


# ---------------------------------------------------------------------------
# CLI-02 · Registro de cliente
# ---------------------------------------------------------------------------


def registrar_cliente(
    conn: Connection,
    payload: ClienteCreate,
    creado_por: int,
    direccion_ip: str,
) -> Cliente:
    """Valida reglas de negocio e inserta el cliente en la base de datos (CLI-02).

    Raises:
        HTTPException 422 CONSENTIMIENTO_REQUERIDO
        HTTPException 422 FECHA_NACIMIENTO_INVALIDA
        HTTPException 422 DOCUMENTO_INVALIDO
        HTTPException 409 CLIENTE_DUPLICADO
        HTTPException 422 TIPO_PERSONA_INVALIDO
        HTTPException 422 CATALOGO_INVALIDO
    """
    # 1. Consentimiento de datos debe ser True
    if not payload.consentimiento_datos:
        raise _problema(
            422,
            "CONSENTIMIENTO_REQUERIDO",
            "El consentimiento para el tratamiento de datos personales es obligatorio.",
        )

    # 2. Fecha de nacimiento o constitución anterior a hoy
    if payload.fecha_nacimiento >= date.today():
        raise _problema(
            422,
            "FECHA_NACIMIENTO_INVALIDA",
            "La fecha de nacimiento o constitución debe ser anterior a la fecha actual.",
        )

    # 3. Validación de formato de documento
    doc = payload.identificacion.strip()
    valido_formato, motivo_doc = validar_formato_documento(payload.tipo_documento, doc)
    if not valido_formato:
        raise _problema(
            422,
            "DOCUMENTO_INVALIDO",
            f"El documento de identificación no cumple el formato requerido: {motivo_doc}",
        )

    # 4. Identificación única (duplicados)
    existente = repository.obtener_cliente_por_identificacion(conn, doc)
    if existente is not None:
        raise _problema(
            409,
            "CLIENTE_DUPLICADO",
            "Ya existe un cliente registrado con esa identificación.",
        )

    # 5. Validación de tipo de persona
    if payload.tipo_cliente == "Natural":
        if (
            not payload.apellidos
            or not payload.genero
            or not payload.estado_civil
            or payload.razon_social is not None
        ):
            raise _problema(
                422,
                "TIPO_PERSONA_INVALIDO",
                "Cliente Natural exige 'apellidos', 'genero' y 'estadoCivil'; y no admite 'razonSocial'.",
            )
    elif payload.tipo_cliente == "Juridico" and (
        not payload.razon_social
        or payload.apellidos is not None
        or payload.genero is not None
        or payload.estado_civil is not None
    ):
        raise _problema(
            422,
            "TIPO_PERSONA_INVALIDO",
            "Cliente Jurídico exige 'razonSocial'; y no admite 'apellidos', 'genero' ni 'estadoCivil'.",
        )

    # 6. Validación de Catálogos
    if (
        payload.id_actividad_economica is not None
        and not repository.existe_actividad_economica(
            conn, payload.id_actividad_economica
        )
    ):
        raise _problema(
            422,
            "CATALOGO_INVALIDO",
            f"La actividad económica con id {payload.id_actividad_economica} no existe en el catálogo.",
        )

    for codigo, etiqueta in (
        (payload.codigo_pais_nacionalidad, "nacionalidad"),
        (payload.direccion.codigo_pais, "la dirección"),
    ):
        if not repository.existe_pais(conn, codigo):
            raise _problema(
                422,
                "CATALOGO_INVALIDO",
                f"El país de {etiqueta} '{codigo}' no existe en el catálogo.",
            )

    direccion = payload.direccion
    if not repository.existe_ciudad(conn, direccion.id_ciudad, direccion.codigo_pais):
        raise _problema(
            422,
            "CATALOGO_INVALIDO",
            f"La ciudad con id {direccion.id_ciudad} no existe o no pertenece al país '{direccion.codigo_pais}'.",
        )

    # 7. Inserción en Base de Datos
    try:
        cliente_dict: dict[str, Any] = repository.crear_cliente(
            conn,
            payload=payload,
            creado_por=creado_por,
            direccion_ip=direccion_ip,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return Cliente(**cliente_dict)


# ---------------------------------------------------------------------------
# Helpers compartidos
# ---------------------------------------------------------------------------


def _validar_cliente_existe(conn: Connection, id_cliente: int) -> dict[str, Any]:
    """Retorna datos del cliente o lanza 404."""
    cliente = repository.obtener_cliente_por_id(conn, id_cliente)
    if cliente is None:
        raise _problema(
            404,
            "CLIENTE_NO_ENCONTRADO",
            f"No se encontró un cliente con id {id_cliente}.",
        )
    return cliente


def _validar_cliente_no_eliminado(cliente: dict[str, Any], id_cliente: int) -> None:
    """Lanza 409 si el cliente está en estado Eliminado."""
    if cliente.get("estado") == "Eliminado":
        raise _problema(
            409,
            "CLIENTE_ELIMINADO",
            f"El cliente {id_cliente} está en estado Eliminado.",
        )


def _validar_ciudad_pais(conn: Connection, id_ciudad: int, codigo_pais: str) -> None:
    """Valida que la ciudad exista y pertenezca al país."""
    if not repository.existe_ciudad(conn, id_ciudad, codigo_pais):
        raise _problema(
            422,
            "CATALOGO_INVALIDO",
            f"La ciudad con id {id_ciudad} no existe o no pertenece al país '{codigo_pais}'.",
        )


# ---------------------------------------------------------------------------
# GET /api/v1/clientes/{idCliente}/direcciones
# ---------------------------------------------------------------------------


def listar_direcciones(conn: Connection, id_cliente: int) -> list[Direccion]:
    """Retorna las direcciones activas e inactivas del cliente (CLI-09)."""
    _validar_cliente_existe(conn, id_cliente)
    filas = repository.listar_direcciones(conn, id_cliente)
    return [Direccion(**fila) for fila in filas]


# ---------------------------------------------------------------------------
# CLI-10 · POST /api/v1/clientes/{idCliente}/direcciones
# ---------------------------------------------------------------------------


def agregar_direccion(
    conn: Connection,
    id_cliente: int,
    payload: DireccionNueva,
    modificado_por: int,
    direccion_ip: str,
) -> Direccion:
    """Agrega una dirección al cliente (CLI-10).

    Raises:
        HTTPException 404 CLIENTE_NO_ENCONTRADO
        HTTPException 409 CLIENTE_ELIMINADO
        HTTPException 422 CATALOGO_INVALIDO
    """
    cliente = _validar_cliente_existe(conn, id_cliente)
    _validar_cliente_no_eliminado(cliente, id_cliente)
    _validar_ciudad_pais(conn, payload.id_ciudad, payload.codigo_pais)

    datos = {
        "tipo_direccion": payload.tipo_direccion,
        "codigo_pais": payload.codigo_pais,
        "id_ciudad": payload.id_ciudad,
        "sector": payload.sector,
        "calle_direccion": payload.calle_direccion,
        "referencia_ubicacion": payload.referencia_ubicacion,
        "codigo_postal": payload.codigo_postal,
        "es_principal": payload.es_principal,
    }

    try:
        row = repository.insertar_direccion(
            conn,
            id_cliente,
            datos,
            modificado_por=modificado_por,
            direccion_ip=direccion_ip,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return Direccion(**row)


# ---------------------------------------------------------------------------
# PATCH /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
# ---------------------------------------------------------------------------


def editar_direccion(
    conn: Connection,
    id_cliente: int,
    id_direccion: int,
    payload: DireccionUpdate,
    modificado_por: int,
    direccion_ip: str,
) -> Direccion:
    """Edita una dirección o la promueve a principal (CLI-11).

    Raises:
        HTTPException 404 CLIENTE_NO_ENCONTRADO
        HTTPException 404 DIRECCION_NO_ENCONTRADA
        HTTPException 422 CATALOGO_INVALIDO
    """
    _validar_cliente_existe(conn, id_cliente)

    actual = repository.obtener_direccion(conn, id_cliente, id_direccion)
    if actual is None:
        raise _problema(
            404,
            "DIRECCION_NO_ENCONTRADA",
            f"No se encontró la dirección {id_direccion} para el cliente {id_cliente}.",
        )

    # Construir dict solo con campos enviados
    cambios: dict[str, Any] = {}
    enviados = payload.model_dump(exclude_unset=True)

    # Si envían codigo_pais o id_ciudad, validar la combinación
    codigo_pais_final = enviados.get("codigo_pais", actual["codigo_pais"])
    id_ciudad_final = enviados.get("id_ciudad", actual["id_ciudad"])
    if "codigo_pais" in enviados or "id_ciudad" in enviados:
        _validar_ciudad_pais(conn, id_ciudad_final, codigo_pais_final)

    for campo, valor in enviados.items():
        if valor != actual.get(campo):
            cambios[campo] = valor

    if not cambios:
        return Direccion(**actual)

    try:
        row = repository.actualizar_direccion(
            conn,
            id_cliente,
            id_direccion,
            cambios,
            modificado_por=modificado_por,
            direccion_ip=direccion_ip,
            valores_anteriores=actual,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return Direccion(**row)


# ---------------------------------------------------------------------------
# DELETE /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
# ---------------------------------------------------------------------------


def eliminar_direccion(
    conn: Connection,
    id_cliente: int,
    id_direccion: int,
) -> None:
    """Baja lógica de una dirección (CLI-12).

    Raises:
        HTTPException 404 CLIENTE_NO_ENCONTRADO
        HTTPException 404 DIRECCION_NO_ENCONTRADA
        HTTPException 409 NO_SE_PUEDE_ELIMINAR_PRINCIPAL
    """
    _validar_cliente_existe(conn, id_cliente)

    actual = repository.obtener_direccion(conn, id_cliente, id_direccion)
    if actual is None:
        raise _problema(
            404,
            "DIRECCION_NO_ENCONTRADA",
            f"No se encontró la dirección {id_direccion} para el cliente {id_cliente}.",
        )

    if actual.get("es_principal") and actual.get("estado") == "Activo":
        raise _problema(
            409,
            "NO_SE_PUEDE_ELIMINAR_PRINCIPAL",
            "No se puede eliminar la dirección principal activa. Asigne otra dirección como principal primero.",
        )

    try:
        repository.eliminar_direccion_logica(conn, id_cliente, id_direccion)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def registrar_evaluacion_riesgo(
    conn: Connection,
    id_cliente: int,
    payload: RiesgoCreate,
    evaluador: int,
    direccion_ip: str,
) -> RiesgoRegistrado:
    """Valida y registra una evaluación con auditoría en una transacción."""
    cliente = _validar_cliente_existe(conn, id_cliente)
    _validar_cliente_no_eliminado(cliente, id_cliente)

    if payload.tiene_antecedentes != (payload.id_tipo_antecedente is not None):
        raise _problema(
            422,
            "ANTECEDENTE_REQUERIDO",
            "El tipo de antecedente es obligatorio solo si tieneAntecedentes es true.",
        )
    if (
        payload.id_tipo_antecedente is not None
        and not repository.existe_tipo_antecedente_activo(
            conn, payload.id_tipo_antecedente
        )
    ):
        raise _problema(
            422,
            "CATALOGO_INVALIDO",
            "El tipo de antecedente no existe o está inactivo.",
        )

    try:
        row = repository.insertar_evaluacion_riesgo(
            conn,
            id_cliente,
            payload.model_dump(),
            evaluador=evaluador,
            direccion_ip=direccion_ip,
        )
        resultado = RiesgoRegistrado(**row)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return resultado


def listar_evaluaciones_riesgo(conn: Connection, id_cliente: int) -> list[Riesgo]:
    """Historial descendente con la vigencia persistida por el trigger (CLI-14)."""
    _validar_cliente_existe(conn, id_cliente)
    return [
        Riesgo(**row) for row in repository.listar_evaluaciones_riesgo(conn, id_cliente)
    ]
