import json
import re
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.security import audit
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.catalogos.tipos_direccion import (
    validar_activo as validar_tipo_direccion,
)
from app.modules.clientes import repository
from app.modules.clientes.habilitacion import activar_si_cumple
from app.modules.clientes.schemas import (
    CAMPOS_CON_RESPALDO,
    CAMPOS_SENSIBLES,
    CambiosSensibles,
    Cliente,
    ClienteBusqueda,
    ClienteCreate,
    ClienteEstadoUpdate,
    ClienteHistorial,
    ClientePerfil,
    ClienteUpdate,
    ConsultaDocumentoBody,
    ContenidoEdicion,
    ContenidoRiesgo,
    CreditoPerfil,
    CuentaPerfil,
    Direccion,
    DireccionNueva,
    DireccionUpdate,
    PageCliente,
    PageClienteHistorial,
    Riesgo,
    RiesgoCreate,
    RiesgoRegistrado,
    TarjetaPerfil,
    TipoDocumento,
    ValidacionIdentificacion,
)
from app.modules.contabilidad.service import ZONA_ECUADOR
from app.modules.cuentas.schemas import ID_MONEDA_USD
from app.modules.parametros import general
from app.modules.parametros.service import hoy

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
    columna = fila.get("valor_anterior_columna")
    datos = {**fila, "valor_anterior": None}
    if columna is not None:
        # E5-04: antes/después en columnas propias; el JSON queda para el legado.
        datos["valor_anterior"] = columna
        fecha_columna: datetime = datos["fecha_modificacion"]
        if fecha_columna.tzinfo is None:
            datos["fecha_modificacion"] = fecha_columna.replace(tzinfo=UTC)
        return ClienteHistorial(**datos)
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
            texto_historial(anteriores[campo]),
            texto_historial(valor),
        )
        for campo, valor in cambios.items()
    ]
    if "estado" in cambios:
        repository.actualizar_estado_cliente(
            conn, actual.id_cliente, cambios["estado"], motivo=motivo
        )
    else:
        repository.actualizar_cliente(conn, actual.id_cliente, cambios)
    for campo, observaciones, anterior, nuevo in auditorias:
        repository.insertar_historial_cliente(
            conn,
            id_cliente=actual.id_cliente,
            tipo_operacion="U",
            campo=campo,
            modificado_por=modificado_por,
            direccion_ip=direccion_ip,
            observaciones=observaciones,
            valor_anterior=anterior,
            valor_nuevo=nuevo,
        )
    resultado = obtener_cliente(conn, actual.id_cliente)
    conn.commit()
    return resultado


def texto_historial(valor: Any) -> str | None:
    """Valor de ClientesHis.ValorAnterior/ValorNuevo: texto, fechas en ISO."""
    if valor is None:
        return None
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor)


def validar_estado_editable(estado: str) -> None:
    """E5-04: nada se edita con el cliente bloqueado o eliminado."""
    if estado == "Eliminado":
        raise problema(
            409, "CLIENTE_NO_EDITABLE", "El cliente eliminado no se puede editar."
        )
    if estado == "Bloqueado":
        raise problema(
            423, "CLIENTE_BLOQUEADO", "El cliente bloqueado no se puede editar."
        )


def cambios_sensibles_efectivos(
    actual: dict[str, Any], enviados: dict[str, Any]
) -> dict[str, Any]:
    """Solo lo que difiere del valor guardado; el correo se compara en minúsculas."""
    cambios: dict[str, Any] = {}
    for campo, valor in enviados.items():
        if campo == "email" and isinstance(valor, str):
            valor = valor.lower()
        if valor != actual[campo]:
            cambios[campo] = valor
    return cambios


def validar_cambios_sensibles(
    conn: Connection, actual: dict[str, Any], cambios: dict[str, Any], hoy: date
) -> None:
    """Reglas de E5-04 sobre los datos finales; se repiten al aplicar la aprobación."""
    validar_estado_editable(actual["estado"])
    finales = actual | cambios
    _validar_tipo_persona(finales)
    if "fecha_nacimiento" in cambios and cambios["fecha_nacimiento"] >= hoy:
        raise problema(
            422,
            "FECHA_NACIMIENTO_INVALIDA",
            "La fecha de nacimiento o constitución debe ser anterior a la fecha actual.",
        )
    if {"identificacion", "tipo_documento"} & cambios.keys():
        valido, motivo = validar_formato_documento(
            finales["tipo_documento"], finales["identificacion"]
        )
        if not valido:
            raise problema(
                422,
                "DOCUMENTO_INVALIDO",
                f"El documento de identificación no cumple el formato requerido: {motivo}",
            )


def verificar_respaldo(
    conn: Connection,
    id_cliente: int,
    cambios: dict[str, Any],
    id_archivo: int | None,
    hoy: date,
) -> None:
    """Respaldo de un cambio de nombre o documento (E5-04 con archivos de E5-08)."""
    if id_archivo is None:
        if not CAMPOS_CON_RESPALDO & cambios.keys():
            return
        exige = general.valor(conn, "CLI_EXIGE_ARCHIVOS", hoy)
        if type(exige) is not bool:
            raise problema(
                503, "PARAMETRO_INVALIDO", "No se pudo verificar la regla de archivos."
            )
        if exige:
            raise problema(
                422,
                "RESPALDO_REQUERIDO",
                "Adjunte el documento que respalda el cambio de nombre o documento.",
            )
        return
    valido = repository.archivo_respaldo_valido(conn, id_cliente, id_archivo)
    if valido is None:
        raise problema(
            503,
            "EVIDENCIA_NO_DISPONIBLE",
            "El almacenamiento de archivos del cliente no está disponible.",
        )
    if not valido:
        raise problema(
            422,
            "RESPALDO_NO_VALIDO",
            "El archivo de respaldo no existe, no es del cliente o no está aprobado.",
        )


SolicitarCambio = Callable[[dict[str, Any]], SolicitudAceptada]


def editar_cliente(
    conn: Connection,
    id_cliente: int,
    payload: ClienteUpdate,
    modificado_por: int,
    direccion_ip: str,
    solicitar: SolicitarCambio | None = None,
) -> Cliente | SolicitudAceptada:
    """CLI-05 / E5-04: ordinarios al instante (200), sensibles a la cola (202)."""
    try:
        actual = _cliente_bloqueado(conn, id_cliente)
        validar_estado_editable(actual.estado)
        enviados = payload.model_dump(exclude_unset=True)
        id_archivo = enviados.pop("id_archivo_respaldo", None)
        if "email" in enviados:
            enviados["email"] = enviados["email"].lower()
        cambios = {
            campo: valor
            for campo, valor in enviados.items()
            if valor != getattr(actual, campo)
        }
        sensibles = {c: v for c, v in cambios.items() if c in CAMPOS_SENSIBLES}
        if sensibles and len(sensibles) != len(cambios):
            raise problema(
                422,
                "CAMBIO_MIXTO",
                "Guarde por separado los datos que requieren aprobación.",
            )
        if id_archivo is not None and not sensibles:
            raise problema(
                422,
                "RESPALDO_NO_APLICA",
                "El respaldo solo acompaña cambios que requieren aprobación.",
            )
        if sensibles:
            conn.rollback()  # La cola vuelve a bloquear y validar en su propia transacción.
            if solicitar is None:
                raise RuntimeError("Falta el servicio de aprobación de E0-08.")
            contenido = ContenidoEdicion(
                cambios=CambiosSensibles(**sensibles),
                id_archivo_respaldo=id_archivo,
                modificado_por=modificado_por,
                direccion_ip=direccion_ip,
            )
            return solicitar(congelar_contenido(contenido))
        finales = actual.model_dump() | enviados
        _validar_tipo_persona(finales)
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
        resultado = _guardar_cambios_cliente(
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
    _auditar_edicion(id_cliente, modificado_por, direccion_ip, cambios.keys())
    return resultado


def congelar_contenido(contenido: ContenidoEdicion) -> dict[str, Any]:
    """Forma JSON del contenido: solo los cambios enviados, en camelCase."""
    datos = contenido.model_dump(mode="json", by_alias=True, exclude={"cambios"})
    datos["cambios"] = contenido.cambios.model_dump(
        mode="json", by_alias=True, exclude_unset=True
    )
    return datos


def _auditar_edicion(
    id_cliente: int, usuario: int, ip: str, campos: Iterable[str]
) -> None:
    # Solo los nombres de los campos: los valores son datos personales (ASVS 16.2.5).
    audit.registrar(
        audit.EventoAuditoria(
            accion="CLI_EDITADO",
            tabla="Clientes.Cliente",
            id_registro=str(id_cliente),
            resultado="Exitoso",
            usuario=usuario,
            ip=ip,
            descripcion="Campos: " + ", ".join(sorted(campos)),
        )
    )


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
        tiene_productos = any(d["estado"] == "PENDIENTE" for d in desembolsos) or any(
            _credito_tiene_deuda(conn, solicitud) for solicitud in solicitudes
        )
    if tiene_productos:
        raise problema(
            409,
            "CLIENTE_CON_PRODUCTOS",
            "El cliente conserva cuentas o créditos vigentes.",
        )


SolicitarEstado = Callable[[dict[str, Any]], SolicitudAceptada]
SolicitarReincorporacion = Callable[[int, dict[str, Any]], SolicitudAceptada]


def _validar_datos_alta(
    payload: ClienteCreate, *, validar_documento: bool = True
) -> str:
    """Validaciones comunes del alta y la reincorporación; devuelve el documento."""
    # 1. Consentimiento de datos debe ser True
    if not payload.consentimiento_datos:
        raise _problema(
            422,
            "CONSENTIMIENTO_REQUERIDO",
            "El consentimiento para el tratamiento de datos personales es obligatorio.",
        )

    # 2. Fecha de nacimiento o constitución anterior a hoy (Ecuador)
    if payload.fecha_nacimiento >= hoy():
        raise _problema(
            422,
            "FECHA_NACIMIENTO_INVALIDA",
            "La fecha de nacimiento o constitución debe ser anterior a la fecha actual.",
        )

    # 3. Validación de formato de documento
    doc = payload.identificacion.strip()
    if not validar_documento:
        return doc
    valido_formato, motivo_doc = validar_formato_documento(payload.tipo_documento, doc)
    if not valido_formato:
        raise _problema(
            422,
            "DOCUMENTO_INVALIDO",
            f"El documento de identificación no cumple el formato requerido: {motivo_doc}",
        )
    return doc


def _validar_persona_y_catalogos(conn: Connection, payload: ClienteCreate) -> None:
    """Tipo de persona y catálogos, iguales para el alta y la reincorporación."""
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
    validar_tipo_direccion(conn, direccion.tipo_direccion)
    if not repository.existe_ciudad(conn, direccion.id_ciudad, direccion.codigo_pais):
        raise _problema(
            422,
            "CATALOGO_INVALIDO",
            f"La ciudad con id {direccion.id_ciudad} no existe o no pertenece al país '{direccion.codigo_pais}'.",
        )


def solicitar_reincorporacion(
    conn: Connection,
    payload: ClienteCreate,
    modificado_por: int,
    direccion_ip: str,
    id_agencia: str | None = None,
    *,
    solicitar: SolicitarReincorporacion | None = None,
) -> SolicitudAceptada:
    """E5-07: valida y envía la reincorporación a la cola de aprobación (202).

    Raises:
        HTTPException 422 CONSENTIMIENTO_REQUERIDO
        HTTPException 422 FECHA_NACIMIENTO_INVALIDA
        HTTPException 422 DOCUMENTO_INVALIDO
        HTTPException 404 CLIENTE_NO_ENCONTRADO
        HTTPException 409 CLIENTE_NO_ELIMINADO
        HTTPException 422 DATOS_NO_COINCIDEN
        HTTPException 422 TIPO_PERSONA_INVALIDO
        HTTPException 422 CATALOGO_INVALIDO
    """
    from app.modules.clientes import documentos_identidad

    doc = _validar_datos_alta(payload)
    if payload.tipo_documento == "P":
        consulta = documentos_identidad.consultar(
            conn,
            ConsultaDocumentoBody(
                tipo_documento="PAS",
                numero=doc,
                codigo_pais_emision=payload.codigo_pais_emision,
            ),
            hoy(),
        )
        existente = (
            repository.obtener_cliente_tipos(conn, consulta.id_cliente)
            if consulta.id_cliente
            else None
        )
        if existente is not None:
            existente["id_cliente"] = consulta.id_cliente
    else:
        existente = repository.obtener_cliente_por_identificacion(conn, doc)
    if existente is None:
        raise _problema(
            404,
            "CLIENTE_NO_ENCONTRADO",
            "No se encontró un cliente con esa identificación.",
        )
    if existente["estado"] != "Eliminado":
        raise _problema(
            409,
            "CLIENTE_NO_ELIMINADO",
            "El cliente no está en estado Eliminado.",
        )

    # 5. Tipos deben coincidir con los guardados
    id_cliente = existente["id_cliente"]
    if not isinstance(id_cliente, int):
        raise _problema(
            404,
            "CLIENTE_NO_ENCONTRADO",
            "No se encontró un cliente con esa identificación.",
        )
    tipo_cliente_guardado = existente.get("tipo_cliente")
    tipo_documento_guardado = existente.get("tipo_documento")
    if tipo_cliente_guardado is None or tipo_documento_guardado is None:
        datos_guardados = repository.obtener_cliente_tipos(conn, id_cliente)
        if datos_guardados is None:
            raise _problema(
                404,
                "CLIENTE_NO_ENCONTRADO",
                "No se encontró un cliente con esa identificación.",
            )
        tipo_cliente_guardado = datos_guardados.get("tipo_cliente")
        tipo_documento_guardado = datos_guardados.get("tipo_documento")

    if (
        payload.tipo_cliente != tipo_cliente_guardado
        or payload.tipo_documento != tipo_documento_guardado
    ):
        raise _problema(
            422,
            "DATOS_NO_COINCIDEN",
            "El tipo de cliente y el tipo de documento deben coincidir con los registrados.",
        )

    _validar_persona_y_catalogos(conn, payload)

    # 8. Enviar a cola de aprobación
    if solicitar is None:
        raise RuntimeError("Falta el servicio de aprobación de E0-08.")

    from app.modules.clientes.aprobacion_reincorporacion import ContenidoReincorporacion

    datos_payload = payload.model_dump(mode="json", by_alias=True)
    contenido = ContenidoReincorporacion.model_validate(
        {
            "datos": datos_payload,
            "modificado_por": modificado_por,
            "direccion_ip": direccion_ip,
            "id_agencia": id_agencia,
        }
    )
    return solicitar(id_cliente, contenido.model_dump(mode="json", by_alias=True))


def cambiar_estado_cliente(
    conn: Connection,
    id_cliente: int,
    payload: ClienteEstadoUpdate,
    modificado_por: int,
    direccion_ip: str,
    roles: tuple[str, ...],
    *,
    funcion_autorizada: bool = False,
    solicitar: SolicitarEstado | None = None,
) -> Cliente | SolicitudAceptada:
    """CLI-06: roles de una identidad autenticada; mismo estado es conflicto."""
    if not funcion_autorizada and not set(roles) & {"ASESOR", "SUPERVISOR", "ADMIN"}:
        raise problema(403, "SIN_PERMISO", "No tiene permiso para esta operación.")
    try:
        actual = _cliente_bloqueado(conn, id_cliente)
        if payload.estado not in _TRANSICIONES_CLIENTE.get(actual.estado, set()):
            raise problema(
                409,
                "TRANSICION_INVALIDA",
                "El cambio de estado no está permitido.",
            )
        if payload.estado in ("Inactivo", "Eliminado"):
            _validar_productos_cliente(conn, id_cliente)

        requiere_aprobacion = (
            payload.estado == "Bloqueado"
            or (payload.estado == "Activo" and actual.estado == "Bloqueado")
            or payload.estado == "Eliminado"
        )
        if requiere_aprobacion:
            conn.rollback()
            if solicitar is None:
                raise RuntimeError("Falta el servicio de aprobación de E0-08.")
            from app.modules.clientes.aprobacion_estado import ContenidoEstado

            # Ya validado arriba: un destino fuera de Bloqueado/Activo/Eliminado no llega aquí.
            contenido = ContenidoEstado.model_validate(
                {
                    "estado": payload.estado,
                    "motivo": payload.motivo,
                    "modificado_por": modificado_por,
                    "direccion_ip": direccion_ip,
                }
            )
            return solicitar(contenido.model_dump(mode="json", by_alias=True))

        resultado = _guardar_cambios_cliente(
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
    audit.registrar(
        audit.EventoAuditoria(
            accion="CLI_ESTADO",
            tabla="Clientes.Cliente",
            id_registro=str(id_cliente),
            resultado="Exitoso",
            usuario=modificado_por,
            ip=direccion_ip,
            descripcion=f"Estado: {actual.estado} -> {payload.estado}",
        )
    )
    return resultado


def listar_clientes(conn: Connection, filtros: ClienteBusqueda) -> PageCliente:
    """E5-05 · búsqueda siempre filtrada y paginada (CLI-03)."""
    if not filtros.tiene_filtro():
        raise problema(
            400,
            "FILTRO_REQUERIDO",
            "Indica documento, nombre, correo, estado o agencia para buscar.",
        )
    campo, direccion = _orden_clientes(filtros.sort)
    filas, total = repository.consultar_clientes(
        conn,
        nombre=filtros.nombre,
        identificacion=filtros.identificacion,
        email=filtros.email,
        id_agencia_registro=filtros.id_agencia_registro,
        tipo_cliente=filtros.tipo_cliente,
        estado=filtros.estado,
        page=filtros.page,
        page_size=filtros.page_size,
        campo=campo,
        direccion=direccion,
    )
    return PageCliente(
        items=[Cliente(**fila) for fila in filas],
        page=filtros.page,
        page_size=filtros.page_size,
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


ERROR_DIGITO_CEDULA = "Dígito verificador de la cédula no coincide."


def validar_cedula_ecuatoriana(cedula: str) -> tuple[bool, str]:
    """Valida una cédula ecuatoriana con el algoritmo Módulo 10"""

    if re.fullmatch(r"[0-9]{10}", cedula) is None:
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
        return False, ERROR_DIGITO_CEDULA

    return True, "Cédula válida."


def validar_ruc(ruc: str) -> tuple[bool, str]:
    """Valida formato offline; no certifica inscripción ni estado ante el SRI.

    Los RUC de sociedades emitidos por el SRI no siempre tienen un dígito
    verificador algorítmico. No aplicarles el módulo 10 de una cédula natural.
    """

    if re.fullmatch(r"[0-9]{13}", ruc) is None:
        return False, "El RUC debe tener exactamente 13 dígitos numéricos."

    if not ruc.endswith("001"):
        return False, "El RUC debe terminar en 001."

    provincia = int(ruc[:2])
    if not (1 <= provincia <= 24 or provincia == 30):
        return False, "Provincia inválida en el RUC."
    if ruc[2] in ("6", "9"):
        return True, "Formato de RUC válido; la inscripción se verifica ante el SRI."

    base_cedula = ruc[:10]
    valida, motivo = validar_cedula_ecuatoriana(base_cedula)
    if not valida:
        return False, f"Base de cédula del RUC no es válida: {motivo}"

    return True, "RUC válido."


def validar_pasaporte(pasaporte: str) -> tuple[bool, str]:
    """Valida pasaporte: 5 a 13 caracteres alfanuméricos."""
    if re.fullmatch(r"[A-Za-z0-9]{5,13}", pasaporte) is None:
        return (
            False,
            "El pasaporte debe tener entre 5 y 13 caracteres alfanuméricos.",
        )
    return True, "Pasaporte válido."


def validar_formato_documento(
    tipo_documento: str, identificacion: str
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
        estado = cliente["estado"]
        return ValidacionIdentificacion(
            valida=True,
            existe=True,
            id_cliente=cliente["id_cliente"],
            mensaje="Identificación ya registrada en el sistema.",
            reincorporable=estado == "Eliminado",
            estado=estado,
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
    id_agencia: str | None = None,
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
    from app.modules.clientes import documentos_identidad

    _validar_datos_alta(payload, validar_documento=False)
    consulta = documentos_identidad.preparar_alta(conn, payload, hoy())
    payload = payload.model_copy(
        update={
            "identificacion": consulta.numero,
            "tipo_documento": documentos_identidad.ANTERIORES.get(
                consulta.tipo_documento, consulta.tipo_documento
            ),
        }
    )

    _validar_persona_y_catalogos(conn, payload)

    # 7. Inserción en Base de Datos
    try:
        cliente_dict: dict[str, Any] = repository.crear_cliente(
            conn,
            payload=payload,
            creado_por=creado_por,
            direccion_ip=direccion_ip,
            id_agencia=id_agencia,
        )
        documentos_identidad.insertar(
            conn,
            cliente_dict["id_cliente"],
            consulta,
            payload.fecha_emision,
            payload.fecha_vencimiento,
            principal=True,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return Cliente(**cliente_dict)


# ---------------------------------------------------------------------------
# Helpers compartidos
# ---------------------------------------------------------------------------


def _validar_cliente_existe(
    conn: Connection, id_cliente: int, *, bloquear: bool = False
) -> dict[str, Any]:
    """Retorna datos del cliente o lanza 404."""
    cliente = (
        repository.bloquear_cliente(conn, id_cliente)
        if bloquear
        else repository.obtener_cliente_por_id(conn, id_cliente)
    )
    if cliente is None:
        raise _problema(
            404,
            "CLIENTE_NO_ENCONTRADO",
            f"No se encontró un cliente con id {id_cliente}.",
        )
    return cliente


def validar_activacion_cuenta(conn: Connection, id_cliente: int) -> None:
    """Serializa la reactivación con bajas y evaluaciones de riesgo del titular.

    El llamador conserva la transacción: primero cliente, después cuenta.
    """
    cliente = _validar_cliente_existe(conn, id_cliente, bloquear=True)
    if cliente["estado"] != "Activo":
        raise problema(409, "CLIENTE_NO_ACTIVO", "El cliente no está Activo.")
    riesgos = repository.listar_evaluaciones_riesgo(conn, id_cliente, solo_vigente=True)
    if any(r["resultado_evaluacion"] == "Rechazado" for r in riesgos):
        raise problema(
            409, "RIESGO_RECHAZADO", "El cliente tiene riesgo vigente rechazado."
        )


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
        cliente = _validar_cliente_existe(conn, id_cliente, bloquear=True)
        _validar_cliente_no_eliminado(cliente, id_cliente)
        _validar_ciudad_pais(conn, payload.id_ciudad, payload.codigo_pais)
        validar_tipo_direccion(conn, payload.tipo_direccion)
        row = repository.insertar_direccion(
            conn,
            id_cliente,
            datos,
            modificado_por=modificado_por,
            direccion_ip=direccion_ip,
        )
        resultado = Direccion(**row)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return resultado


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
    try:
        cliente = _validar_cliente_existe(conn, id_cliente, bloquear=True)
        _validar_cliente_no_eliminado(cliente, id_cliente)
        actual = repository.obtener_direccion(conn, id_cliente, id_direccion)
        if actual is None:
            raise problema(404, "DIRECCION_NO_ENCONTRADA", "La dirección no existe.")
        if actual["estado"] == "Eliminado":
            raise problema(409, "DIRECCION_NO_EDITABLE", "La dirección está eliminada.")
        enviados = payload.model_dump(exclude_unset=True)
        if enviados.get("es_principal") is True and actual["estado"] != "Activo":
            raise problema(
                409, "DIRECCION_NO_ACTIVA", "La dirección principal debe estar activa."
            )
        if (
            actual["es_principal"]
            and actual["estado"] == "Activo"
            and enviados.get("es_principal") is False
        ):
            raise problema(
                409,
                "DIRECCION_PRINCIPAL_REQUERIDA",
                "Seleccione otra dirección como principal antes de desmarcar la actual.",
            )
        if "codigo_pais" in enviados or "id_ciudad" in enviados:
            _validar_ciudad_pais(
                conn,
                enviados.get("id_ciudad", actual["id_ciudad"]),
                enviados.get("codigo_pais", actual["codigo_pais"]),
            )
        cambios = {
            campo: valor
            for campo, valor in enviados.items()
            if valor != actual.get(campo)
        }
        if not cambios:
            resultado = Direccion(**actual)
            conn.rollback()
            return resultado
        if "tipo_direccion" in cambios:
            validar_tipo_direccion(conn, cambios["tipo_direccion"])
        row = repository.actualizar_direccion(
            conn,
            id_cliente,
            id_direccion,
            cambios,
            modificado_por=modificado_por,
            direccion_ip=direccion_ip,
            valores_anteriores=actual,
        )
        resultado = Direccion(**row)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return resultado


# ---------------------------------------------------------------------------
# DELETE /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
# ---------------------------------------------------------------------------


def eliminar_direccion(
    conn: Connection,
    id_cliente: int,
    id_direccion: int,
    modificado_por: int,
    direccion_ip: str,
) -> None:
    """Baja lógica y su historial en una sola transacción (CLI-12).

    Raises:
        HTTPException 404 CLIENTE_NO_ENCONTRADO
        HTTPException 404 DIRECCION_NO_ENCONTRADA
        HTTPException 409 NO_SE_PUEDE_ELIMINAR_PRINCIPAL
    """
    try:
        _validar_cliente_existe(conn, id_cliente, bloquear=True)
        actual = repository.obtener_direccion(conn, id_cliente, id_direccion)
        if actual is None:
            raise problema(404, "DIRECCION_NO_ENCONTRADA", "La dirección no existe.")
        if actual["estado"] == "Eliminado":
            conn.rollback()  # Reintento idempotente: no hay otra baja que auditar.
            return
        if actual.get("es_principal") and actual.get("estado") == "Activo":
            raise problema(
                409,
                "NO_SE_PUEDE_ELIMINAR_PRINCIPAL",
                "Asigne otra dirección como principal antes de eliminar la actual.",
            )
        repository.eliminar_direccion_logica(
            conn,
            id_cliente,
            id_direccion,
            modificado_por=modificado_por,
            direccion_ip=direccion_ip,
            estado_anterior=actual["estado"],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def validar_datos_riesgo(
    conn: Connection,
    datos: RiesgoCreate | ContenidoRiesgo,
    fecha_operativa: date,
) -> int:
    """Valida antecedentes, catálogos y vigencia de la evaluación de riesgo."""
    if datos.tiene_antecedentes != (datos.id_tipo_antecedente is not None):
        raise _problema(
            422,
            "ANTECEDENTE_REQUERIDO",
            "El tipo de antecedente es obligatorio solo si tieneAntecedentes es true.",
        )
    if datos.id_tipo_antecedente is not None:
        antecedente = repository.tipo_antecedente_activo(
            conn, datos.id_tipo_antecedente
        )
        if antecedente is None:
            raise _problema(
                422,
                "CATALOGO_INVALIDO",
                "El tipo de antecedente no existe o está inactivo.",
            )
        if (
            antecedente["impide_vinculacion"]
            and datos.resultado_evaluacion == "Aprobado"
        ):
            raise _problema(
                422,
                "ANTECEDENTE_IMPIDE_VINCULACION",
                "El antecedente impide registrar una evaluación aprobada.",
            )
    clave = f"CLI_RIESGO_VIGENCIA_{datos.nivel_riesgo_laft.upper()}_MESES"
    try:
        meses_vigencia = general.valor(conn, clave, fecha_operativa)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        raise _problema(
            503,
            "PARAMETRO_NO_DISPONIBLE",
            "La vigencia del riesgo no está configurada.",
        ) from exc
    if type(meses_vigencia) is not int or meses_vigencia < 1:
        raise _problema(
            503, "PARAMETRO_INVALIDO", "La vigencia del riesgo no está configurada."
        )
    return meses_vigencia


SolicitarRiesgo = Callable[[dict[str, Any]], SolicitudAceptada]


def registrar_evaluacion_riesgo(
    conn: Connection,
    id_cliente: int,
    payload: RiesgoCreate,
    evaluador: int,
    direccion_ip: str,
    solicitar: SolicitarRiesgo | None = None,
) -> RiesgoRegistrado | SolicitudAceptada:
    """Valida y registra una evaluación o la envía a aprobación de CLI-RIESGO."""
    try:
        cliente = _validar_cliente_existe(conn, id_cliente, bloquear=True)
        _validar_cliente_no_eliminado(cliente, id_cliente)
        fecha_evaluacion = datetime.now(UTC)
        fecha_operativa = fecha_evaluacion.astimezone(ZONA_ECUADOR).date()
        meses_vigencia = validar_datos_riesgo(conn, payload, fecha_operativa)

        requiere_aprobacion = (
            payload.es_pep
            or payload.nivel_riesgo_laft == "Alto"
            or payload.resultado_evaluacion == "Rechazado"
        )
        if requiere_aprobacion:
            conn.rollback()
            if solicitar is None:
                raise RuntimeError("Falta el servicio de aprobación de E0-08.")
            contenido = ContenidoRiesgo.model_validate(
                {
                    **payload.model_dump(),
                    "evaluador": evaluador,
                    "direccion_ip": direccion_ip,
                }
            )
            return solicitar(contenido.model_dump(mode="json", by_alias=True))

        row = repository.insertar_evaluacion_riesgo(
            conn,
            id_cliente,
            payload.model_dump(),
            evaluador=evaluador,
            direccion_ip=direccion_ip,
            fecha_evaluacion=fecha_evaluacion,
            fecha_operativa=fecha_operativa,
            meses_vigencia=meses_vigencia,
        )
        habilitado = activar_si_cumple(
            conn,
            id_cliente,
            fecha_operativa,
            actor=evaluador,
            ip=direccion_ip,
        )
        if habilitado:
            filas = repository.listar_evaluaciones_riesgo(
                conn, id_cliente, id_evaluacion=row["id_evaluacion"]
            )
            if filas:
                row = filas[0]
        resultado = RiesgoRegistrado(**row)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    audit.registrar(
        audit.EventoAuditoria(
            accion="CLI_RIESGO_EVALUADO",
            tabla="Clientes.RiesgoCliente",
            id_registro=str(resultado.id_evaluacion),
            resultado="Exitoso",
            usuario=evaluador,
            ip=direccion_ip,
            descripcion=f"Nivel={payload.nivel_riesgo_laft}; PEP={'si' if payload.es_pep else 'no'}; Resultado={payload.resultado_evaluacion}",
        )
    )
    if habilitado:
        audit.registrar(
            audit.EventoAuditoria(
                accion="CLI_HABILITADO",
                tabla="Clientes.Cliente",
                id_registro=str(id_cliente),
                resultado="Exitoso",
                usuario=evaluador,
                ip=direccion_ip,
                descripcion="Cliente habilitado automáticamente tras evaluación de riesgo",
            )
        )
    return resultado


def listar_evaluaciones_riesgo(conn: Connection, id_cliente: int) -> list[Riesgo]:
    """Historial descendente con la vigencia persistida por el trigger (CLI-14)."""
    _validar_cliente_existe(conn, id_cliente)
    return [
        Riesgo(**row) for row in repository.listar_evaluaciones_riesgo(conn, id_cliente)
    ]
