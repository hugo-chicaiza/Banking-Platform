import hashlib
import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta, timezone
from itertools import pairwise
from typing import Any

from argon2 import PasswordHasher
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.core.security import audit
from app.modules.tarjetas import repository
from app.modules.tarjetas.schemas import (
    PageTarjeta,
    PageTarjetaHistorial,
    Tarjeta,
    TarjetaCreate,
    TarjetaEstadoUpdate,
    TarjetaHistorial,
    TarjetaResumen,
)

logger = logging.getLogger(__name__)

# Parámetros por defecto de argon2-cffi. La salt queda dentro del hash
_hasher = PasswordHasher()

_LONGITUD_PAN = 16
_ESTADOS_TERMINALES = {"Cancelada", "Anulada", "Vencida", "Cerrada"}
# TarjetaHis guarda hora de Ecuador, UTC-5 todo el año
_ZONA_BD = timezone(timedelta(hours=-5))


@contextmanager
def _transaccion(*conexiones: Connection) -> Iterator[None]:
    """Hace commit en el orden recibido y rollback de todas si algo falla."""
    try:
        yield
        for conn in conexiones:
            conn.commit()
    except DBAPIError as exc:
        for conn in conexiones:
            conn.rollback()
        # from None para que la traza no arrastre los parámetros de la consulta
        raise traducir_error_bd(exc) from None
    except Exception:
        for conn in conexiones:
            conn.rollback()
        raise


@dataclass
class _Auditado:
    id_registro: int | None


@contextmanager
def _auditado(
    accion: str,
    tabla: str,
    descripcion: str,
    id_registro: int | None,
    usuario: int,
    ip: str | None,
) -> Iterator[_Auditado]:
    """Registra el resultado de una escritura cuando ya terminó su transacción."""
    operacion = _Auditado(id_registro)

    def registrar(resultado: audit.Resultado, texto: str) -> None:
        audit.registrar(
            audit.EventoAuditoria(
                accion=accion,
                tabla=tabla,
                id_registro=(
                    None
                    if operacion.id_registro is None
                    else str(operacion.id_registro)
                ),
                resultado=resultado,
                # UsuarioID tiene FK a Usuarios, así que hasta F-03 va NULL
                usuario=usuario or None,
                ip=ip,
                descripcion=texto,
            )
        )

    try:
        yield operacion
    except HTTPException as exc:
        detalle = exc.detail if isinstance(exc.detail, dict) else {}
        registrar("Fallido", f"{descripcion}: {detalle.get('code', exc.status_code)}")
        raise
    except Exception:
        registrar("Fallido", f"{descripcion}: ERROR_INTERNO")
        raise
    registrar("Exitoso", descripcion)


def _ordenamiento(
    sort: str | None, permitidos: dict[str, str], por_defecto: tuple[str, str]
) -> tuple[str, str]:
    if sort is None:
        return por_defecto
    campo, _, direccion = sort.partition(",")
    direccion = direccion or "asc"
    if campo not in permitidos or direccion not in {"asc", "desc"}:
        raise problema(400, "SORT_INVALIDO", "El ordenamiento solicitado no es válido.")
    return campo, direccion


# TAR-01


def _digito_luhn(parcial: str) -> str:
    total = 0
    for posicion, caracter in enumerate(reversed(parcial)):
        digito = int(caracter)
        if posicion % 2 == 0:
            digito *= 2
            digito = digito - 9 if digito > 9 else digito
        total += digito
    return str((10 - total % 10) % 10)


def _generar_pan(codigo_bin: str) -> str:
    """BIN + dígitos aleatorios + dígito verificador de Luhn."""
    aleatorios = _LONGITUD_PAN - len(codigo_bin) - 1
    parcial = codigo_bin + "".join(
        secrets.choice("0123456789") for _ in range(aleatorios)
    )
    return parcial + _digito_luhn(parcial)


def _enmascarar(pan: str) -> str:
    """Deja los 6 primeros y los 4 últimos: 5000 00** **** 1234."""
    return f"{pan[:4]} {pan[4:6]}** **** {pan[-4:]}"


def _validar_extension(conn: Connection, payload: TarjetaCreate) -> None:
    """La titular debe ser de la misma cuenta, no ser extensión y seguir vigente."""
    if not payload.es_extension:
        if payload.id_tarjeta_titular is not None:
            raise problema(
                422,
                "EXTENSION_REQUIERE_TITULAR",
                "Solo una extensión puede indicar tarjeta titular.",
            )
        return
    if payload.id_tarjeta_titular is None:
        raise problema(
            422,
            "EXTENSION_REQUIERE_TITULAR",
            "Una extensión necesita una tarjeta titular vigente de la misma cuenta.",
        )
    titular = repository.obtener_titular(conn, payload.id_tarjeta_titular)
    if titular is None:
        raise problema(
            422, "TARJETA_TITULAR_NO_ENCONTRADA", "La tarjeta titular no existe."
        )
    if (
        titular["es_extension"]
        or titular["id_cuenta"] != payload.id_cuenta
        or titular["estado"] in _ESTADOS_TERMINALES
    ):
        raise problema(
            422,
            "EXTENSION_REQUIERE_TITULAR",
            "Una extensión necesita una tarjeta titular vigente de la misma cuenta.",
        )


def _validar_envio(conn: Connection, payload: TarjetaCreate) -> None:
    if not payload.requiere_envio:
        return
    if payload.direccion_envio is None:
        raise problema(
            422, "DIRECCION_ENVIO_REQUERIDA", "El envío necesita una dirección."
        )
    if payload.id_ciudad_envio is not None and not repository.existe_ciudad(
        conn, payload.id_ciudad_envio
    ):
        raise problema(422, "CIUDAD_NO_ENCONTRADA", "La ciudad de envío no existe.")


def crear_tarjeta(
    conn: Connection, payload: TarjetaCreate, usuario: int, ip: str | None
) -> Tarjeta:
    with (
        _auditado(
            "INSERT", "Tarjeta.Tarjeta", "TAR-01 Emisión de tarjeta", None, usuario, ip
        ) as operacion,
        _transaccion(conn),
    ):
        # Un id del cuerpo que no existe es 422 con su propio code; el 404 queda para
        # el recurso de la URL. "No existe" y "no está activa" nunca comparten code.
        cuenta = repository.obtener_cuenta(conn, payload.id_cuenta)
        if cuenta is None:
            raise problema(422, "CUENTA_NO_ENCONTRADA", "La cuenta no existe.")
        if cuenta["estado"] != "Activa":
            raise problema(409, "CUENTA_NO_ACTIVA", "La cuenta no está Activa.")

        producto = repository.obtener_producto(conn, payload.id_producto)
        if producto is None:
            raise problema(422, "PRODUCTO_NO_ENCONTRADO", "El producto no existe.")
        if producto["tipo_producto"] != "Tarjeta" or producto["estado"] != "A":
            raise problema(
                422, "PRODUCTO_NO_ES_TARJETA", "El producto no es de tipo Tarjeta."
            )

        subproducto = repository.obtener_subproducto_con_bin(conn, payload.id_producto)
        if subproducto is None:
            raise problema(
                422, "BIN_INVALIDO", "El producto no tiene un BIN activo asociado."
            )

        _validar_extension(conn, payload)
        _validar_envio(conn, payload)

        # El PAN solo se usa en esta función: no se guarda ni va a los logs
        pan = _generar_pan(subproducto["codigo_bin"])
        id_tarjeta = repository.insertar_tarjeta(
            conn,
            {
                "token": f"tok_{secrets.token_urlsafe(32)}",
                "mascara": _enmascarar(pan),
                "hash_pan": hashlib.sha256(pan.encode()).digest(),
                "nombre_tarjeta": payload.nombre_tarjeta,
                "tipo_tarjeta": payload.tipo_tarjeta,
                "nombres": cuenta["nombres"],
                "apellidos": cuenta["apellidos"] or "",
                "id_cliente": cuenta["id_cliente"],
                "id_cuenta": payload.id_cuenta,
                "id_producto": payload.id_producto,
                "id_agencia": cuenta["id_agencia"],
                "es_extension": payload.es_extension,
                "id_titular": payload.id_tarjeta_titular,
                "creado_por": usuario,
                "id_bin": subproducto["id_bin"],
                "id_sub_producto": subproducto["id_sub_producto"],
            },
        )
        del pan
        operacion.id_registro = id_tarjeta

        if payload.requiere_envio and payload.direccion_envio is not None:
            repository.insertar_envio(
                conn,
                id_tarjeta,
                cuenta["id_cliente"],
                payload.direccion_envio,
                payload.id_ciudad_envio,
            )
        repository.insertar_historial(
            conn,
            id_tarjeta,
            "CambioEstado",
            None,
            "Generada",
            "Emisión de tarjeta",
            usuario,
            ip,
        )
        fila = repository.obtener_tarjeta(conn, id_tarjeta)
        if fila is None:  # pragma: no cover
            raise RuntimeError("La tarjeta emitida no se encontró")

    logger.info("tarjetas: emitida id_tarjeta=%s usuario=%s", id_tarjeta, usuario)
    return Tarjeta(**fila)


# TAR-02


def buscar_tarjetas(
    conn: Connection,
    id_cliente: int | None,
    id_cuenta: int | None,
    estado: str | None,
    page: int,
    page_size: int,
    sort: str | None,
) -> PageTarjeta:
    campo, direccion = _ordenamiento(
        sort, repository.CAMPOS_ORDEN_TARJETAS, ("idTarjeta", "desc")
    )
    with _transaccion(conn):
        filas, total = repository.listar_tarjetas(
            conn, id_cliente, id_cuenta, estado, campo, direccion, page, page_size
        )
    return PageTarjeta(
        items=[TarjetaResumen(**fila) for fila in filas],
        page=page,
        page_size=page_size,
        total=total,
    )


# TAR-03


def _tarjeta_no_encontrada() -> HTTPException:
    return problema(404, "TARJETA_NO_ENCONTRADA", "La tarjeta no existe.")


def obtener_tarjeta(conn: Connection, id_tarjeta: int) -> Tarjeta:
    with _transaccion(conn):
        fila = repository.obtener_tarjeta(conn, id_tarjeta)
    if fila is None:
        raise _tarjeta_no_encontrada()
    return Tarjeta(**fila)


# TAR-04


def _tipo_evento(anterior: str, nuevo: str) -> str:
    if nuevo == "Activa":
        return "Desbloqueo" if anterior == "Bloqueada" else "Activacion"
    return {"Bloqueada": "Bloqueo", "Anulada": "Anulacion"}.get(nuevo, "CambioEstado")


def cambiar_estado(
    conn: Connection,
    id_tarjeta: int,
    payload: TarjetaEstadoUpdate,
    usuario: int,
    ip: str | None,
) -> Tarjeta:
    with (
        _auditado(
            "UPDATE",
            "Tarjeta.Tarjeta",
            f"TAR-04 Cambio de estado a {payload.estado}",
            id_tarjeta,
            usuario,
            ip,
        ),
        _transaccion(conn),
    ):
        actual = repository.obtener_tarjeta(conn, id_tarjeta, bloquear=True)
        if actual is None:
            raise _tarjeta_no_encontrada()
        anterior = actual["estado_actual"]
        if not repository.existe_transicion(conn, anterior, payload.estado):
            raise problema(
                409,
                "TRANSICION_TARJETA_INVALIDA",
                "El cambio de estado no está permitido.",
            )
        if payload.estado == "Activa" and not actual["pin_asignado"]:
            raise problema(
                409, "PIN_NO_ASIGNADO", "Asigne un PIN antes de activar la tarjeta."
            )
        repository.actualizar_estado(conn, id_tarjeta, payload.estado)
        repository.insertar_historial(
            conn,
            id_tarjeta,
            _tipo_evento(anterior, payload.estado),
            anterior,
            payload.estado,
            payload.motivo,
            usuario,
            ip,
        )
        fila = repository.obtener_tarjeta(conn, id_tarjeta)
        if fila is None:  # pragma: no cover
            raise RuntimeError("La tarjeta actualizada no se encontró")

    logger.info(
        "tarjetas: estado id_tarjeta=%s destino=%s usuario=%s",
        id_tarjeta,
        payload.estado,
        usuario,
    )
    return Tarjeta(**fila)


# TAR-05


def es_pin_debil(pin: str) -> bool:
    """True para repetidos (0000) y secuencias (1234, 4321)."""
    saltos = {int(b) - int(a) for a, b in pairwise(pin)}
    return saltos in ({0}, {1}, {-1})


def asignar_pin(
    conn: Connection,
    conn_seguridad: Connection,
    id_tarjeta: int,
    pin: SecretStr,
    usuario: int,
    ip: str | None,
) -> None:
    # SeguridadDB hace commit primero. Si luego falla CooperativaDB queda un hash con
    # PinAsignado = 0: la tarjeta no se puede activar y el reintento sobrescribe el hash.
    with (
        _auditado(
            "UPDATE",
            "Tarjeta.Tarjeta",
            "TAR-05 Asignación de PIN inicial",
            id_tarjeta,
            usuario,
            ip,
        ),
        _transaccion(conn_seguridad, conn),
    ):
        actual = repository.obtener_tarjeta(conn, id_tarjeta)
        if actual is None:
            raise _tarjeta_no_encontrada()
        if actual["pin_asignado"]:
            raise problema(409, "PIN_YA_ASIGNADO", "La tarjeta ya tiene PIN.")
        if es_pin_debil(pin.get_secret_value()):
            raise problema(422, "PIN_DEBIL", "El PIN es demasiado simple.")

        # Antes de bloquear la fila, porque Argon2id es lento
        hash_pin = _hasher.hash(pin.get_secret_value())
        if not repository.marcar_pin_asignado(conn, id_tarjeta):
            raise problema(409, "PIN_YA_ASIGNADO", "La tarjeta ya tiene PIN.")
        repository.insertar_historial(
            conn,
            id_tarjeta,
            "CambioPin",
            None,
            None,
            "Asignación de PIN inicial",
            usuario,
            ip,
        )
        repository.guardar_hash_pin(conn_seguridad, id_tarjeta, hash_pin)

    logger.info("tarjetas: pin asignado id_tarjeta=%s usuario=%s", id_tarjeta, usuario)


# TAR-06


def _evento(fila: dict[str, Any]) -> TarjetaHistorial:
    """En CambioPin la respuesta lleva resultado en lugar de motivo."""
    es_pin = fila["tipo_evento"] == "CambioPin"
    return TarjetaHistorial(
        id_historial=fila["id_historial"],
        id_tarjeta=fila["id_tarjeta"],
        tipo_evento=fila["tipo_evento"],
        estado_anterior=fila["estado_anterior"],
        estado_nuevo=fila["estado_nuevo"],
        motivo=None if es_pin else fila["descripcion"],
        resultado="COMPLETADO" if es_pin else None,
        fecha_cambio=fila["fecha_evento"].replace(tzinfo=_ZONA_BD),
        realizado_por=fila["realizado_por"],
    )


def obtener_historial(
    conn: Connection,
    id_tarjeta: int,
    page: int,
    page_size: int,
    sort: str | None,
    fecha_desde: date | None = None,
    fecha_hasta: date | None = None,
) -> PageTarjetaHistorial:
    campo, direccion = _ordenamiento(
        sort, repository.CAMPOS_ORDEN_HISTORIAL, ("fechaCambio", "desc")
    )
    if fecha_desde and fecha_hasta and fecha_desde > fecha_hasta:
        raise problema(
            400,
            "RANGO_FECHAS_INVALIDO",
            "fechaDesde no puede ser mayor que fechaHasta.",
        )
    with _transaccion(conn):
        if not repository.existe_tarjeta(conn, id_tarjeta):
            raise _tarjeta_no_encontrada()
        filas, total = repository.listar_historial(
            conn,
            id_tarjeta,
            fecha_desde,
            fecha_hasta,
            campo,
            direccion,
            page,
            page_size,
        )
    return PageTarjetaHistorial(
        items=[_evento(fila) for fila in filas],
        page=page,
        page_size=page_size,
        total=total,
    )
