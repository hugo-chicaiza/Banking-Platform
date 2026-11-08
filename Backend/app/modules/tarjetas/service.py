import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.core.security import audit
from app.core.security.hsm import (
    ClaveNoAutorizada,
    ErrorHsm,
    Hsm,
    PinBlockInvalido,
    PinDebil,
    obtener_hsm,
)
from app.modules.tarjetas import repository
from app.modules.tarjetas.identificacion import hash_pan
from app.modules.tarjetas.schemas import (
    PageTarjeta,
    PageTarjetaHistorial,
    PinBlockPrueba,
    Tarjeta,
    TarjetaCreate,
    TarjetaEstadoUpdate,
    TarjetaHistorial,
    TarjetaResumen,
)

logger = logging.getLogger(__name__)

_LONGITUD_PAN = 16
_ESTADOS_TERMINALES = {"Cancelada", "Anulada", "Vencida", "Cerrada"}
# Estados en los que existe (o puede regenerarse) un PIN: desde la aprobación
_ESTADOS_CON_PIN = {"Aprobada", "Generada", "Activa", "Inactiva", "Bloqueada"}
# A-05: una tarjeta de crédito Generada se activa sola tras estos días laborables
DIAS_LABORABLES_ACTIVACION_CREDITO = 3
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
                usuario=usuario,
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


# HSM y PAN ficticio (TAR-01, TAR-05, ATM-01)


def _error_hsm(exc: ErrorHsm, code_no_disponible: str) -> HTTPException:
    """Traduce el error del HSM sin detalles criptográficos."""
    if isinstance(exc, ClaveNoAutorizada):
        return problema(
            422, "CLAVE_NO_AUTORIZADA", "La referencia de clave no está autorizada."
        )
    if isinstance(exc, PinBlockInvalido):
        return problema(422, "PIN_BLOCK_INVALIDO", "El PIN Block no es válido.")
    if isinstance(exc, PinDebil):
        return problema(422, "PIN_DEBIL", "El PIN es demasiado simple.")
    return problema(
        503, code_no_disponible, "No se pudo completar el procesamiento criptográfico."
    )


def _hsm(code_no_disponible: str) -> Hsm:
    try:
        return obtener_hsm()
    except ErrorHsm as exc:
        raise _error_hsm(exc, code_no_disponible) from None


def pan_de_prueba(conn_seguridad: Connection, id_tarjeta: int, hsm: Hsm) -> str:
    """Interfaz controlada del PAN ficticio (TAR-05, PIN pad simulado y ATM-01).

    Solo existe fuera de producción. Nunca se registra ni se devuelve en la API.
    """
    guardado = repository.obtener_pan_ficticio(conn_seguridad, id_tarjeta)
    if guardado is None:
        raise problema(
            503, "PAN_NO_DISPONIBLE", "La tarjeta no tiene un PAN ficticio custodiado."
        )
    try:
        return hsm.descifrar_pan(guardado[0], guardado[1], id_tarjeta)
    except ErrorHsm:
        raise problema(
            503, "PAN_NO_DISPONIBLE", "No se pudo recuperar el PAN ficticio."
        ) from None


def _rollback(*conexiones: Connection) -> None:
    for conn in conexiones:
        conn.rollback()


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
    conn: Connection,
    conn_seguridad: Connection,
    payload: TarjetaCreate,
    usuario: int,
    ip: str | None,
) -> Tarjeta:
    """Emite la tarjeta y custodia su PAN ficticio cifrado (repositorio de pruebas).

    _transaccion confirma primero SeguridadDB (PAN) y luego CooperativaDB (tarjeta):
    nunca queda una tarjeta sin PAN recuperable. Si falla la confirmación de
    CooperativaDB, _compensar_pan borra el PAN ya guardado.
    """
    hsm = _hsm("PAN_NO_DISPONIBLE")
    custodiado: list[int] = []
    try:
        return _emitir(conn, conn_seguridad, payload, usuario, ip, hsm, custodiado)
    except BaseException:
        if custodiado:
            _compensar_pan(conn_seguridad, custodiado[0])
        raise


def _compensar_pan(conn_seguridad: Connection, id_tarjeta: int) -> None:
    """Si SeguridadDB ya confirmó el PAN y la tarjeta no, borra el PAN. Si también
    falla, queda un PAN de un IdTarjeta que no existe (los IDENTITY no se reutilizan).
    """
    try:
        repository.borrar_pan_ficticio(conn_seguridad, id_tarjeta)
        conn_seguridad.commit()
    except DBAPIError:
        conn_seguridad.rollback()
        logger.error(
            "tarjetas: PAN ficticio huérfano por limpiar id_tarjeta=%s", id_tarjeta
        )


def _emitir(
    conn: Connection,
    conn_seguridad: Connection,
    payload: TarjetaCreate,
    usuario: int,
    ip: str | None,
    hsm: Hsm,
    custodiado: list[int],
) -> Tarjeta:
    with (
        _auditado(
            "INSERT", "Tarjeta.Tarjeta", "TAR-01 Emisión de tarjeta", None, usuario, ip
        ) as operacion,
        _transaccion(conn_seguridad, conn),
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

        subproducto = repository.obtener_subproducto_con_bin(
            conn, payload.id_producto, payload.id_sub_producto
        )
        if subproducto is None:
            raise problema(
                422,
                "SUBPRODUCTO_NO_ENCONTRADO",
                "El subproducto no existe o no pertenece al producto.",
            )
        if (
            subproducto["estado"] != "A"
            or subproducto["id_bin"] is None
            or subproducto["estado_bin"] != "A"
        ):
            raise problema(
                422, "BIN_INVALIDO", "El subproducto no tiene un BIN activo asociado."
            )

        _validar_extension(conn, payload)
        _validar_envio(conn, payload)

        # El PAN en claro solo vive aquí: se custodia cifrado por el HSM
        pan = _generar_pan(subproducto["codigo_bin"])
        id_tarjeta = repository.insertar_tarjeta(
            conn,
            {
                "token": f"tok_{secrets.token_urlsafe(32)}",
                "mascara": _enmascarar(pan),
                "hash_pan": hash_pan(pan),
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
        try:
            cifrado, referencia = hsm.cifrar_pan(pan, id_tarjeta)
        except ErrorHsm as exc:
            raise _error_hsm(exc, "PAN_NO_DISPONIBLE") from None
        finally:
            del pan
        repository.guardar_pan_ficticio(conn_seguridad, id_tarjeta, cifrado, referencia)
        # Si algo falla desde aquí, crear_tarjeta borra el PAN (no-op si no llegó al commit)
        custodiado.append(id_tarjeta)
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
            "Solicitada",
            "Solicitud de tarjeta",
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


def credito_cumple_plazo(conn: Connection, fecha_emision: date) -> bool:
    """A-05: la tarjeta de crédito se activa a los 3 días laborables de su emisión."""
    return (
        repository.dias_laborables_desde(conn, fecha_emision)
        >= DIAS_LABORABLES_ACTIVACION_CREDITO
    )


def _generar_pin(
    conn_seguridad: Connection, id_tarjeta: int, tipo_tarjeta: str, hsm: Hsm
) -> None:
    """El HSM genera el PIN y solo se guarda su Offset, confirmado en SeguridadDB.

    Débito: PIN temporal (RequiereCambio), llega impreso con la tarjeta.
    Crédito: PIN asignado que no se entrega; el cliente lo pide al servicio al cliente.
    """
    pan = pan_de_prueba(conn_seguridad, id_tarjeta, hsm)
    try:
        offset, referencia_pvk = hsm.generar_pin(pan)
    except ErrorHsm as exc:
        raise _error_hsm(exc, "HSM_NO_DISPONIBLE") from None
    finally:
        del pan
    try:
        repository.guardar_pin_generado(
            conn_seguridad,
            id_tarjeta,
            offset,
            referencia_pvk,
            requiere_cambio=tipo_tarjeta == "Debito",
        )
        conn_seguridad.commit()
    except DBAPIError as exc:
        conn_seguridad.rollback()
        raise traducir_error_bd(exc) from None


def cambiar_estado(
    conn: Connection,
    conn_seguridad: Connection,
    id_tarjeta: int,
    payload: TarjetaEstadoUpdate,
    usuario: int,
    ip: str | None,
) -> Tarjeta:
    """Cambia el estado según Tarjeta.TransicionEstado (A-05).

    Aprobar genera el PIN en el HSM. Su Offset se confirma en SeguridadDB antes que el
    estado en CooperativaDB: si esta falla, la tarjeta sigue Solicitada (inutilizable)
    y repetir la aprobación genera un PIN nuevo que reemplaza al anterior.
    """
    destino = payload.estado
    with (
        _auditado(
            "UPDATE",
            "Tarjeta.Tarjeta",
            f"TAR-04 Cambio de estado a {destino}",
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
        if anterior == "Generada" and destino == "Activa":
            raise problema(
                409,
                "ACTIVACION_AUTOMATICA",
                "La tarjeta se activa con el primer cambio de PIN (débito) "
                "o a los 3 días laborables (crédito).",
            )
        if not repository.existe_transicion(conn, anterior, destino):
            raise problema(
                409,
                "TRANSICION_INVALIDA",
                "El cambio de estado no está permitido.",
            )
        if destino == "Activa" and not actual["pin_asignado"]:
            raise problema(
                409, "PIN_NO_ASIGNADO", "Asigne un PIN antes de activar la tarjeta."
            )
        aprobar = destino == "Aprobada"
        if aprobar:
            _generar_pin(
                conn_seguridad,
                id_tarjeta,
                actual["tipo_tarjeta"],
                _hsm("HSM_NO_DISPONIBLE"),
            )
        repository.actualizar_estado(
            conn,
            id_tarjeta,
            destino,
            resolucion=anterior == "Solicitada",
            emision=destino == "Generada",
            pin_asignado=aprobar,
        )
        repository.insertar_historial(
            conn,
            id_tarjeta,
            _tipo_evento(anterior, destino),
            anterior,
            destino,
            payload.motivo,
            usuario,
            ip,
        )
        if aprobar:
            repository.insertar_historial(
                conn,
                id_tarjeta,
                "CambioPin",
                None,
                None,
                "PIN generado automáticamente",
                usuario,
                ip,
            )
        fila = repository.obtener_tarjeta(conn, id_tarjeta)
        if fila is None:  # pragma: no cover
            raise RuntimeError("La tarjeta actualizada no se encontró")

    logger.info(
        "tarjetas: estado id_tarjeta=%s destino=%s usuario=%s",
        id_tarjeta,
        destino,
        usuario,
    )
    return Tarjeta(**fila)


# TAR-05


def regenerar_pin(
    conn: Connection,
    conn_seguridad: Connection,
    id_tarjeta: int,
    usuario: int,
    ip: str | None,
) -> None:
    """Reposición del PIN: el HSM genera uno nuevo (nadie lo conoce).

    Reinicia los intentos y desbloquea el PIN, sin cambiar el estado de la tarjeta.
    El Offset se confirma primero en SeguridadDB; si luego falla CooperativaDB, el PIN
    nuevo ya rige y se puede repetir la operación.
    """
    with _auditado(
        "UPDATE",
        "Tarjeta.Tarjeta",
        "TAR-05 Regeneración de PIN",
        id_tarjeta,
        usuario,
        ip,
    ):
        try:
            actual = repository.obtener_tarjeta(conn, id_tarjeta, bloquear=True)
            if actual is None:
                raise _tarjeta_no_encontrada()
            if actual["estado_actual"] not in _ESTADOS_CON_PIN:
                raise problema(
                    409,
                    "PIN_NO_PERMITIDO",
                    "La tarjeta no admite PIN en su estado actual.",
                )
            _generar_pin(
                conn_seguridad,
                id_tarjeta,
                actual["tipo_tarjeta"],
                _hsm("HSM_NO_DISPONIBLE"),
            )
        except DBAPIError as exc:
            _rollback(conn_seguridad, conn)
            raise traducir_error_bd(exc) from None
        except BaseException:
            _rollback(conn_seguridad, conn)
            raise

        try:
            repository.marcar_pin_asignado(conn, id_tarjeta)
            repository.insertar_historial(
                conn,
                id_tarjeta,
                "CambioPin",
                None,
                None,
                "Regeneración de PIN",
                usuario,
                ip,
            )
            conn.commit()
        except DBAPIError:
            conn.rollback()
            logger.error(
                "tarjetas: pin regenerado sin historial id_tarjeta=%s", id_tarjeta
            )
            raise problema(
                503,
                "PIN_ASIGNACION_NO_CONFIRMADA",
                "No se pudo confirmar la regeneración del PIN.",
            ) from None

    logger.info(
        "tarjetas: pin regenerado id_tarjeta=%s usuario=%s", id_tarjeta, usuario
    )


def construir_pin_block_prueba(
    conn: Connection, conn_seguridad: Connection, id_tarjeta: int, pin: SecretStr
) -> PinBlockPrueba:
    """Simula el PIN pad (componente seguro de captura) para probar TAR-05 y ATM-01."""
    if not repository.existe_tarjeta(conn, id_tarjeta):
        raise _tarjeta_no_encontrada()
    hsm = _hsm("HSM_NO_DISPONIBLE")
    pan = pan_de_prueba(conn_seguridad, id_tarjeta, hsm)
    try:
        bloque, referencia = hsm.construir_pin_block(pin.get_secret_value(), pan)
    except ErrorHsm as exc:
        raise _error_hsm(exc, "HSM_NO_DISPONIBLE") from None
    finally:
        del pan
    return PinBlockPrueba(encrypted_pin_block=bloque, key_reference=referencia)


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
