from datetime import date
from typing import Any

from fastapi import HTTPException
from sqlalchemy import Connection

from app.modules.clientes import repository
from app.modules.clientes.schemas import (
    Cliente,
    ClienteCreate,
    TipoDocumento,
    ValidacionIdentificacion,
)

_COEFICIENTES_MOD10 = [2, 1, 2, 1, 2, 1, 2, 1, 2]


def _problema(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": detail},
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

    if not repository.existe_pais(conn, payload.codigo_pais_nacionalidad):
        raise _problema(
            422,
            "CATALOGO_INVALIDO",
            f"El país de nacionalidad '{payload.codigo_pais_nacionalidad}' no existe en el catálogo.",
        )

    dir_payload = payload.direccion
    if not repository.existe_pais(conn, dir_payload.codigo_pais):
        raise _problema(
            422,
            "CATALOGO_INVALIDO",
            f"El país de la dirección '{dir_payload.codigo_pais}' no existe en el catálogo.",
        )

    if not repository.existe_ciudad(
        conn, dir_payload.id_ciudad, dir_payload.codigo_pais
    ):
        raise _problema(
            422,
            "CATALOGO_INVALIDO",
            f"La ciudad con id {dir_payload.id_ciudad} no existe o no pertenece al país '{dir_payload.codigo_pais}'.",
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
