from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.core.security import audit
from app.modules.clientes import service as clientes_service
from app.modules.contabilidad.service import ZONA_ECUADOR
from app.modules.cuentas import repository
from app.modules.cuentas.schemas import (
    ID_MONEDA_USD,
    Cuenta,
    CuentaCreate,
    CuentaEstadoUpdate,
    CuentaResumen,
    CupoEfectivo,
    CupoHistorial,
    CupoUpdate,
    EstadoCuenta,
    MovimientoCuenta,
    PageCuenta,
    PageCupoHistorial,
    PageMovimientoCuenta,
    SaldoCuenta,
)

CAMPOS_ORDEN_CUENTAS = {
    "idCuenta": "IdCuenta",
    "numeroCuenta": "NumeroCuenta",
    "idCliente": "IdCliente",
    "idProducto": "IdProducto",
    "idAgencia": "IdAgencia",
    "tipoCuenta": "TipoCuenta",
    "estado": "Estado",
}


def _orden_cuentas(sort: str | None) -> tuple[str, str]:
    if sort is None:
        return "IdCuenta", "asc"
    partes = sort.split(",")
    if (
        len(partes) != 2
        or partes[0] not in CAMPOS_ORDEN_CUENTAS
        or partes[1] not in ("asc", "desc")
    ):
        raise problema(
            400, "SORT_INVALIDO", "Use un campo permitido y la dirección asc o desc."
        )
    return CAMPOS_ORDEN_CUENTAS[partes[0]], partes[1]


def listar_cuentas(
    conn: Connection,
    *,
    id_cliente: int | None = None,
    numero_cuenta: str | None = None,
    estado: EstadoCuenta | None = None,
    id_agencia: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort: str | None = None,
) -> PageCuenta:
    """Consulta paginada con filtros combinados y orden seguro (CTA-02)."""
    campo, direccion = _orden_cuentas(sort)
    filas, total = repository.consultar_cuentas(
        conn,
        id_cliente=id_cliente,
        numero_cuenta=numero_cuenta,
        estado=estado,
        id_agencia=id_agencia,
        page=page,
        page_size=page_size,
        campo=campo,
        direccion=direccion,
    )
    return PageCuenta(
        items=[CuentaResumen(**fila) for fila in filas],
        page=page,
        page_size=page_size,
        total=total,
    )


def obtener_cuenta(conn: Connection, id_cuenta: int) -> Cuenta:
    """Lectura única compartida por detalle y saldo, sin filtrar estados."""
    fila = repository.obtener_cuenta_por_id(conn, id_cuenta)
    if fila is None:
        raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe.")
    # Regla global aprobada: todas las cuentas operan en USD. No se persiste por fila.
    return Cuenta(**{**fila, "id_moneda": ID_MONEDA_USD})


def obtener_saldo(conn: Connection, id_cuenta: int) -> SaldoCuenta:
    """Calcula el disponible sin modificar los importes persistidos (CTA-04)."""
    cuenta = obtener_cuenta(conn, id_cuenta)
    saldo = cuenta.saldo
    retenido = cuenta.saldo_retenido
    if cuenta.estado == "CERRADA":
        saldo = retenido = Decimal("0.00")
    return SaldoCuenta(
        id_cuenta=cuenta.id_cuenta,
        saldo=saldo,
        saldo_retenido=retenido,
        saldo_disponible=saldo - retenido,
        id_moneda=cuenta.id_moneda,
        fecha_consulta=datetime.now(UTC),
    )


def listar_movimientos(
    conn: Connection,
    id_cuenta: int,
    *,
    desde: date,
    hasta: date,
    tipo_transaccion: str | None = None,
    page: int = 1,
    page_size: int = 20,
    sort: str | None = None,
) -> PageMovimientoCuenta:
    if desde > hasta:
        raise problema(
            400, "RANGO_FECHAS_INVALIDO", "desde debe ser anterior o igual a hasta."
        )
    if page < 1 or not 1 <= page_size <= 100:
        raise problema(400, "PAGINACION_INVALIDA", "La paginación no es válida.")
    campo, direccion = "FechaHoraSistema", "desc"
    if sort is not None:
        partes = sort.split(",")
        campos = {
            "fechaHoraSistema": "FechaHoraSistema",
            "fechaContable": "FechaContable",
            "idMovimiento": "IdMovimiento",
            "monto": "Monto",
        }
        if (
            len(partes) != 2
            or partes[0] not in campos
            or partes[1] not in ("asc", "desc")
        ):
            raise problema(
                400,
                "SORT_INVALIDO",
                "Use un campo permitido y la dirección asc o desc.",
            )
        campo, direccion = campos[partes[0]], partes[1]
    obtener_cuenta(conn, id_cuenta)
    filas, total = repository.consultar_movimientos(
        conn,
        id_cuenta,
        desde=desde,
        hasta=hasta,
        tipo_transaccion=tipo_transaccion,
        page=page,
        page_size=page_size,
        campo=campo,
        direccion=direccion,
    )
    return PageMovimientoCuenta(
        items=[
            MovimientoCuenta(
                **{
                    **fila,
                    "fecha_hora_sistema": (
                        fila["fecha_hora_sistema"].replace(tzinfo=ZONA_ECUADOR)
                        if fila["fecha_hora_sistema"].tzinfo is None
                        else fila["fecha_hora_sistema"]
                    ),
                }
            )
            for fila in filas
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


# Generación de NumeroCuenta

# Formato acordado mientras se resuelve G-11 con negocio:
# prefijo de tipo (AH / CC) + secuencial de 8 dígitos.
# Ejemplo: AH00000501. Único garantizado por UQ_Cuenta_Numero.
_PREFIJOS: dict[str, str] = {"Ahorro": "AH", "Corriente": "CC"}


def _generar_numero_cuenta(conn: Connection, tipo_cuenta: str) -> str:
    """Genera el próximo NumeroCuenta libre.

    La lectura toma un bloqueo de rango hasta el commit para serializar aperturas
    del mismo prefijo. La unicidad final la garantiza UQ_Cuenta_Numero.
    """
    prefijo = _PREFIJOS.get(tipo_cuenta, "XX")
    patron = f"{prefijo}%"

    from sqlalchemy import text

    ultimo = conn.execute(
        text(
            """
            SELECT ISNULL(MAX(TRY_CONVERT(
                       bigint, SUBSTRING(NumeroCuenta, 3, LEN(NumeroCuenta))
                   )), 0) AS ultimo
            FROM Cuentas.Cuenta WITH (UPDLOCK, HOLDLOCK)
            WHERE NumeroCuenta LIKE :patron
            """
        ),
        {"patron": patron},
    ).scalar_one()
    return f"{prefijo}{str(ultimo + 1).zfill(8)}"


# CTA-01 · Apertura de cuenta


def abrir_cuenta(
    conn: Connection,
    payload: CuentaCreate,
    creado_por: int,
) -> Cuenta:
    """Ejecuta las validaciones previas y llama al repositorio.

    Raises:
        HTTPException 409 CLIENTE_NO_ACTIVO
        HTTPException 409 RIESGO_RECHAZADO
        HTTPException 422 PRODUCTO_NO_ES_CUENTA
        HTTPException 409 AGENCIA_INACTIVA
    """
    # 1. Cliente existe y está Activo
    cliente = repository.obtener_cliente(conn, payload.id_cliente)
    if cliente is None or cliente["estado"] != "Activo":
        raise problema(409, "CLIENTE_NO_ACTIVO", "El cliente no está Activo.")

    # 2. Riesgo vigente no rechazado
    riesgo = repository.obtener_riesgo_vigente(conn, payload.id_cliente)
    if riesgo is not None and riesgo["estado"] == "Rechazado":
        raise problema(
            409, "RIESGO_RECHAZADO", "El cliente tiene riesgo vigente rechazado."
        )

    # 3. Subproducto y producto padre existen, son de Cuenta y están activos.
    producto = repository.obtener_subproducto(conn, payload.id_sub_producto)
    if (
        producto is None
        or producto["tipo_producto"] != "Cuenta"
        or producto["estado_producto"] != "A"
        or producto["estado_subproducto"] != "A"
    ):
        raise problema(
            422,
            "PRODUCTO_NO_ES_CUENTA",
            "El subproducto no corresponde a una cuenta activa.",
        )

    # 4. Monto de apertura cubre el mínimo; el SP repite esta validación.
    monto_minimo = producto["monto_apertura_minimo"] or Decimal("0.00")
    if payload.monto_inicial < monto_minimo:
        raise problema(
            422,
            "MONTO_APERTURA_INSUFICIENTE",
            "El monto inicial no cubre el mínimo de apertura.",
        )

    # 5. Agencia existe y está activa
    agencia = repository.obtener_agencia(conn, payload.id_agencia)
    if agencia is None or agencia["estado"] != "A":
        raise problema(
            409, "AGENCIA_INACTIVA", "La agencia no existe o no está activa."
        )

    # 6. Generar NumeroCuenta
    numero_cuenta = _generar_numero_cuenta(conn, producto["tipo_cuenta"])

    # 7. Ejecutar la firma real del SP y traducir sus THROW sin exponer SQL.
    try:
        row = repository.abrir_cuenta(
            conn,
            numero_cuenta=numero_cuenta,
            id_cliente=payload.id_cliente,
            id_subproducto=payload.id_sub_producto,
            id_agencia=payload.id_agencia,
            monto_inicial=payload.monto_inicial,
            creado_por=creado_por,
        )
        conn.commit()
    except DBAPIError as exc:
        conn.rollback()
        raise traducir_error_bd(exc) from exc
    except Exception:
        conn.rollback()
        raise

    # CTA-01 conserva idMoneda en el contrato aunque la moneda no se persista por cuenta.
    return Cuenta(**{**row, "id_moneda": ID_MONEDA_USD})


_TRANSICIONES_CUENTA = {
    "ACTIVA": {"INACTIVA", "BLOQUEADA", "CERRADA"},
    "INACTIVA": {"ACTIVA", "CERRADA"},
    "BLOQUEADA": {"ACTIVA"},
    "CERRADA": set(),
}


def cambiar_estado_cuenta(
    conn: Connection,
    id_cuenta: int,
    payload: CuentaEstadoUpdate,
    modificado_por: int,
    ip: str | None,
    trace_id: str,
) -> Cuenta:
    anterior: str | None = None

    def auditar(resultado: audit.Resultado) -> None:
        audit.registrar(
            audit.EventoAuditoria(
                accion="UPDATE",
                tabla="Cuentas.Cuenta",
                id_registro=str(id_cuenta),
                resultado=resultado,
                usuario=modificado_por,
                ip=ip,
                descripcion=(
                    f"CTA05 estadoAnterior={anterior} estadoNuevo={payload.estado}; "
                    f"traceId={trace_id[:64]}; motivo={payload.motivo}"
                ),
            )
        )

    try:
        if payload.estado == "ACTIVA":
            # Mismo orden que CLI-06: cliente -> cuenta. El titular es inmutable en la API.
            id_cliente = repository.obtener_titular_cuenta(conn, id_cuenta)
            if id_cliente is None:
                raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe.")
            clientes_service.validar_activacion_cuenta(conn, id_cliente)
        actual = repository.bloquear_cuenta(conn, id_cuenta)
        if actual is None:
            raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe.")
        anterior = str(actual["estado"])
        if payload.estado not in _TRANSICIONES_CUENTA.get(anterior, set()):
            raise problema(
                409, "TRANSICION_INVALIDA", "El cambio de estado no está permitido."
            )
        if payload.estado == "CERRADA":
            if actual["saldo"] != 0 or actual["saldo_retenido"] != 0:
                raise problema(
                    409, "CUENTA_CON_SALDO", "La cuenta tiene saldo o saldo retenido."
                )
            desembolsos = repository.desembolsos_de_cuenta(conn, id_cuenta)
            # PENDIENTE reserva un desembolso; DESEMBOLSADO requiere verificar deuda,
            # no el estado APROBADA de la solicitud ni un saldo ficticio del resumen.
            pendiente = any(d["estado"] == "PENDIENTE" for d in desembolsos)
            solicitudes = sorted(
                {
                    d["id_solicitud"]
                    for d in desembolsos
                    if d["estado"] == "DESEMBOLSADO"
                }
            )
            if pendiente or any(
                clientes_service.credito_tiene_deuda(conn, s) for s in solicitudes
            ):
                raise problema(
                    409,
                    "CUENTA_CON_CREDITO_VIGENTE",
                    "La cuenta respalda un crédito vigente o un desembolso pendiente.",
                )
        repository.actualizar_estado_cuenta(conn, id_cuenta, payload.estado)
        resultado = obtener_cuenta(conn, id_cuenta)
        conn.commit()
    except DBAPIError as exc:
        conn.rollback()
        auditar("Fallido")
        raise traducir_error_bd(exc) from None
    except Exception:
        conn.rollback()
        auditar("Fallido")
        raise
    auditar("Exitoso")
    return resultado


def _cupos_efectivos(
    conn: Connection, id_cuenta: int, id_canal: int | None = None
) -> list[CupoEfectivo]:
    return [
        CupoEfectivo(**f)
        for f in repository.consultar_cupos_efectivos(conn, id_cuenta, id_canal)
    ]


def obtener_cupos(conn: Connection, id_cuenta: int) -> list[CupoEfectivo]:
    obtener_cuenta(conn, id_cuenta)
    return _cupos_efectivos(conn, id_cuenta)


def _validar_canal(conn: Connection, id_canal: int) -> None:
    if repository.obtener_canal(conn, id_canal) is None:
        raise problema(404, "CANAL_NO_ENCONTRADO", "El canal no existe.")


def actualizar_cupo(
    conn: Connection,
    id_cuenta: int,
    id_canal: int,
    payload: CupoUpdate,
    modificado_por: int,
) -> CupoEfectivo:
    try:
        if repository.bloquear_cuenta(conn, id_cuenta) is None:
            raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe.")
        _validar_canal(conn, id_canal)
        producto = repository.bloquear_cupo_producto(conn, id_cuenta, id_canal)
        if producto is None:
            raise problema(
                422,
                "CUPO_PRODUCTO_NO_CONFIGURADO",
                "El subproducto no tiene cupo para este canal.",
            )
        if (
            not payload.monto_max_transaccion
            <= payload.cupo_diario
            <= payload.cupo_mensual
        ):
            raise problema(
                422,
                "CUPOS_INCONSISTENTES",
                "El máximo por transacción debe ser menor o igual al diario y este al mensual.",
            )
        if any(
            getattr(payload, campo) > producto[campo]
            for campo in (
                "cupo_diario",
                "cupo_mensual",
                "monto_max_transaccion",
                "max_transacciones_dia",
            )
        ):
            raise problema(
                422,
                "CUPO_SUPERA_MAXIMO_PRODUCTO",
                "El cupo supera el máximo del subproducto en ese canal.",
            )
        anterior = repository.bloquear_cupo_personalizado(conn, id_cuenta, id_canal)
        repository.guardar_cupo_personalizado(
            conn,
            id_cuenta,
            id_canal,
            payload,
            modificado_por,
            existe=anterior is not None,
        )
        repository.insertar_historial_cupo(
            conn,
            id_cuenta,
            id_canal,
            anterior,
            payload,
            modificado_por,
        )
        efectivos = _cupos_efectivos(conn, id_cuenta, id_canal)
        if len(efectivos) != 1:
            raise problema(
                503,
                "CUPO_EFECTIVO_NO_VERIFICABLE",
                "No se pudo comprobar el cupo efectivo del canal.",
            )
        resultado = efectivos[
            0
        ]  # Puede ser Producto si se guardó una fecha ya vencida.
        conn.commit()
        return resultado
    except DBAPIError as exc:
        conn.rollback()
        raise traducir_error_bd(exc, operacion="CTA08") from None
    except Exception:
        conn.rollback()
        raise


def obtener_historial_cupo(
    conn: Connection,
    id_cuenta: int,
    id_canal: int,
    *,
    page: int = 1,
    page_size: int = 20,
    sort: str | None = None,
) -> PageCupoHistorial:
    campo, direccion = "FechaModificacion", "desc"
    if sort is not None:
        partes = sort.split(",")
        campos = {
            "fechaModificacion": "FechaModificacion",
            "idCupoModHis": "IdCupoModHis",
        }
        if (
            len(partes) != 2
            or partes[0] not in campos
            or partes[1] not in ("asc", "desc")
        ):
            raise problema(
                400,
                "SORT_INVALIDO",
                "Use un campo permitido y la dirección asc o desc.",
            )
        campo, direccion = campos[partes[0]], partes[1]
    if page < 1 or not 1 <= page_size <= 100:
        raise problema(400, "PAGINACION_INVALIDA", "La paginación no es válida.")
    obtener_cuenta(conn, id_cuenta)
    _validar_canal(conn, id_canal)
    filas, total = repository.consultar_historial_cupo(
        conn,
        id_cuenta,
        id_canal,
        page=page,
        page_size=page_size,
        campo=campo,
        direccion=direccion,
    )
    return PageCupoHistorial(
        items=[
            CupoHistorial(
                **{
                    **f,
                    "fecha_modificacion": (
                        f["fecha_modificacion"].replace(tzinfo=ZONA_ECUADOR)
                        if f["fecha_modificacion"].tzinfo is None
                        else f["fecha_modificacion"]
                    ),
                }
            )
            for f in filas
        ],
        page=page,
        page_size=page_size,
        total=total,
    )
