from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.core.security import audit
from app.core.security.auth import Usuario
from app.core.security.operador import encolar_evento
from app.modules.clientes import repository as clientes_repository
from app.modules.clientes import service as clientes_service
from app.modules.clientes.habilitacion import cliente_habilitado
from app.modules.clientes.relaciones import (
    RolRelacion,
    edad_en,
    edad_mayoria,
    relacion_vigente,
)
from app.modules.contabilidad.service import ZONA_ECUADOR
from app.modules.cuentas import repository
from app.modules.cuentas.schemas import (
    ID_MONEDA_USD,
    AutorizadoCuenta,
    Cuenta,
    CuentaDetalle,
    CuentaEstadoUpdate,
    CuentaPendienteCreate,
    CuentaResumen,
    CupoEfectivo,
    CupoHistorial,
    CupoSolicitado,
    EstadoCuenta,
    EventoCuenta,
    MovimientoCuenta,
    PageCuenta,
    PageCupoHistorial,
    PageMovimientoCuenta,
    SaldoCuenta,
)
from app.modules.parametros import general
from app.modules.parametros.service import hoy
from app.modules.productos import service as productos_service
from app.modules.productos.numeracion import siguiente_numero_cuenta
from app.modules.transacciones import repository as transacciones_repo

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


def obtener_detalle(conn: Connection, id_cuenta: int) -> CuentaDetalle:
    cuenta = obtener_cuenta(conn, id_cuenta)
    datos = repository.obtener_titular_y_motivo(conn, id_cuenta, cuenta.estado)
    return CuentaDetalle(**cuenta.model_dump(), **datos)


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


def disponible(conn: Connection, id_cuenta: int) -> Decimal:
    """Saldo disponible para operaciones, leído en la transacción del consumidor."""
    return Decimal(transacciones_repo.saldo_disponible(conn, id_cuenta))


def cupo_efectivo(
    conn: Connection,
    id_cuenta: int,
    id_canal: int,
    fecha: date,
    *,
    tipo: str,
    grupo: int | None,
    agencia: str,
) -> dict | None:
    """Combina el cupo del canal con el límite institucional más específico."""
    fila = (
        conn.execute(
            text("""
                SELECT CupoMensual, MaxTransaccionesDia, MontoMaxTransaccion, CupoDiario
                FROM Canal.fn_CupoVigenteFecha(:cuenta, :canal, :fecha)
            """),
            {"cuenta": id_cuenta, "canal": id_canal, "fecha": fecha},
        )
        .mappings()
        .one_or_none()
    )
    if fila is None:
        return None
    limite = (
        repository.limite_institucional(
            conn, id_canal, fecha, tipo=tipo, grupo=grupo, agencia=agencia
        )
        or {}
    )
    cupo = dict(fila)
    for campo, institucional in (
        ("MontoMaxTransaccion", "MontoMaximoOperacion"),
        ("CupoDiario", "MontoMaximoDiario"),
    ):
        maximo = limite.get(institucional)
        if maximo is not None:
            cupo[campo] = min(cupo[campo], maximo)
    cupo["MontoRequiereAprobacion"] = limite.get("MontoRequiereAprobacion")
    return cupo


def cuenta_operable(
    conn: Connection, id_cuenta: int, tipo_movimiento: str, canal: str
) -> tuple[bool, list[str]]:
    datos = transacciones_repo.restricciones_cuenta(conn, id_cuenta)
    if datos is None:
        return False, ["CUENTA_NO_ENCONTRADA"]

    if tipo_movimiento not in {"C", "D"}:
        raise ValueError("La naturaleza del movimiento debe ser C o D.")
    es_debito = tipo_movimiento == "D"
    estados = (
        {"Activa"}
        if es_debito
        else {"Activa", "PendienteDeposito", "Inactiva", "Bloqueada"}
    )
    motivos = []
    if datos["EstadoCuenta"] not in estados:
        motivos.append("CUENTA_NO_ACTIVA")
    if datos["EstadoCliente"] != "Activo":
        motivos.append("CLIENTE_NO_ACTIVO")
    if canal == "VENT" and not datos["PermiteOperacionesPresenciales"]:
        motivos.append("PRODUCTO_SIN_OPERACION_PRESENCIAL")

    nacimiento = datos["FechaNacimiento"]
    if es_debito and datos["TipoCliente"] == "Natural" and nacimiento is not None:
        fecha = hoy()
        if edad_en(nacimiento, fecha) < edad_mayoria(conn, fecha):
            tutor = relacion_vigente(conn, datos["IdCliente"], "Tutor", fecha)
            if (
                tutor is None
                or not conn.execute(
                    text("""
                    SELECT 1 FROM Cuentas.CuentaAutorizado WITH (HOLDLOCK)
                    WHERE IdCuenta=:cuenta AND IdClienteAutorizado=:tutor
                      AND IdClienteRelacion=:relacion
                      AND Rol='Tutor' AND RevocadoEn IS NULL AND FechaInicio<=:fecha
                      AND (FechaFin IS NULL OR FechaFin>=:fecha)
                """),
                    {
                        "cuenta": id_cuenta,
                        "tutor": tutor["IdClienteRelacionado"],
                        "relacion": tutor["IdRelacion"],
                        "fecha": fecha,
                    },
                ).first()
            ):
                motivos.append("MENOR_SIN_TUTOR")
    return not motivos, motivos


def listar_autorizados(
    conn: Connection, id_cuenta: int, agencia: str
) -> list[AutorizadoCuenta]:
    cuenta = obtener_cuenta(conn, id_cuenta)
    if cuenta.id_agencia != agencia:
        raise problema(
            404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia activa."
        )
    return [
        AutorizadoCuenta.model_validate(dict(fila))
        for fila in conn.execute(
            text("""
                SELECT a.IdCuentaAutorizado AS id_cuenta_autorizado,
                       a.IdClienteAutorizado AS id_cliente_autorizado,
                       NULLIF(TRIM(CONCAT_WS(' ', cl.Nombres, cl.Apellidos)), '') AS nombre_autorizado,
                       a.Rol AS rol,a.FechaInicio AS fecha_inicio,a.FechaFin AS fecha_fin,
                       CAST(CASE WHEN a.RevocadoEn IS NULL AND a.FechaInicio<=:fecha
                         AND (a.FechaFin IS NULL OR a.FechaFin>=:fecha) THEN 1 ELSE 0 END AS bit) AS vigente
                FROM Cuentas.CuentaAutorizado AS a
                LEFT JOIN Clientes.Cliente AS cl ON cl.IdCliente=a.IdClienteAutorizado
                WHERE a.IdCuenta=:id
                ORDER BY a.FechaInicio DESC,a.IdCuentaAutorizado DESC;
            """),
            {"id": id_cuenta, "fecha": hoy()},
        ).mappings()
    ]


def listar_eventos(
    conn: Connection, id_cuenta: int, agencia: str
) -> list[EventoCuenta]:
    cuenta = obtener_cuenta(conn, id_cuenta)
    if cuenta.id_agencia != agencia:
        raise problema(
            404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia activa."
        )
    filas = conn.execute(
        text("""
            SELECT IdCuentaEvento AS id_cuenta_evento, TipoEvento AS tipo_evento,
                   EstadoAnterior AS estado_anterior, EstadoActual AS estado_actual,
                   Detalle AS detalle, RealizadoPor AS realizado_por,
                   IdAgencia AS id_agencia, FechaEvento AS fecha_evento
            FROM Cuentas.CuentaEvento WHERE IdCuenta=:id
            ORDER BY FechaEvento DESC, IdCuentaEvento DESC
        """),
        {"id": id_cuenta},
    ).mappings()
    return [
        EventoCuenta.model_validate(
            {**fila, "fecha_evento": fila["fecha_evento"].replace(tzinfo=UTC)}
        )
        for fila in filas
    ]


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


def activar_si_corresponde(
    conn: Connection, id_cuenta: int, monto: Decimal, realizado_por: int
) -> bool:
    """Activa una pendiente sin confirmar la transacción del depósito."""
    cuenta = (
        conn.execute(
            text("""
            SELECT Estado, IdCliente, IdSubProducto, MontoAperturaAplicado
            FROM Cuentas.Cuenta WITH (UPDLOCK, HOLDLOCK)
            WHERE IdCuenta = :id
        """),
            {"id": id_cuenta},
        )
        .mappings()
        .first()
    )
    if cuenta is None:
        raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe.")
    if cuenta["Estado"] != "PendienteDeposito":
        return False
    producto = repository.obtener_subproducto(conn, cuenta["IdSubProducto"])
    if (
        producto is None
        or producto["estado_producto"] != "A"
        or producto["estado_subproducto"] != "A"
    ):
        raise problema(
            409,
            "APERTURA_DESACTUALIZADA",
            "El producto o subproducto dejó de estar activo.",
        )
    if monto <= 0 or monto < cuenta["MontoAperturaAplicado"]:
        raise problema(
            422, "MONTO_BAJO_APERTURA", "El depósito no alcanza el mínimo de apertura."
        )
    habilitacion = cliente_habilitado(conn, cuenta["IdCliente"], hoy())
    if not habilitacion.habilitado:
        raise problema(
            409,
            "CLIENTE_NO_HABILITADO",
            "El titular perdió la habilitación para activar la cuenta.",
            bloqueos=habilitacion.motivos,
        )
    conn.execute(
        text("""
            DECLARE @Fecha datetime2 = SYSUTCDATETIME();
            UPDATE Cuentas.Cuenta SET Estado='Activa', FechaActivacion=@Fecha
            WHERE IdCuenta = :id AND Estado='PendienteDeposito';
            IF @@ROWCOUNT = 1
                INSERT Cuentas.CuentaEvento
                    (IdCuenta, TipoEvento, EstadoAnterior, EstadoActual, Detalle, RealizadoPor, IdAgencia, FechaEvento)
                SELECT IdCuenta, 'Activacion', 'PendienteDeposito', 'Activa', N'Primer depósito',
                       :actor, IdAgencia, @Fecha
                FROM Cuentas.Cuenta WHERE IdCuenta = :id;
        """),
        {"id": id_cuenta, "actor": realizado_por},
    )
    return True


def rol_para_apertura(
    conn: Connection, tipo_cliente: str, nacimiento: date | None, fecha: date
) -> RolRelacion | None:
    """Identifica la relación obligatoria para ofrecer o abrir una cuenta."""
    if tipo_cliente == "Juridico":
        return "RepresentanteLegal"
    if nacimiento is not None and edad_en(nacimiento, fecha) < edad_mayoria(
        conn, fecha
    ):
        return "Tutor"
    return None


def abrir_cuenta_pendiente(
    conn: Connection, payload: CuentaPendienteCreate, agencia: str, actor: int
) -> Cuenta:
    """Apertura E6-01, sin contabilización ni depósito inicial."""
    fecha = hoy()
    try:
        # Una apertura por cliente a la vez. El máximo incluye otras pendientes.
        cliente = clientes_repository.bloquear_cliente(conn, payload.id_cliente)
        if cliente is None:
            raise problema(404, "CLIENTE_NO_ENCONTRADO", "El cliente no existe.")
        habilitacion = cliente_habilitado(conn, payload.id_cliente, fecha)
        if not habilitacion.habilitado:
            raise problema(
                409,
                "CLIENTE_NO_HABILITADO",
                "El cliente no está habilitado para abrir una cuenta.",
                bloqueos=habilitacion.motivos,
            )
        producto = repository.obtener_subproducto(conn, payload.id_sub_producto)
        if producto is None or producto["tipo_producto"] != "Cuenta":
            raise problema(
                422, "PRODUCTO_NO_ES_CUENTA", "Seleccione un subproducto de cuenta."
            )
        elegible, motivos = productos_service.cliente_elegible(
            conn, payload.id_cliente, payload.id_sub_producto, fecha
        )
        if not elegible:
            codigo = (
                "MAXIMO_POR_CLIENTE"
                if "MAXIMO_POR_CLIENTE_ALCANZADO" in motivos
                else "MENOR_SIN_TUTOR"
                if "TUTOR_NO_VERIFICABLE" in motivos
                else "SUBPRODUCTO_NO_ELEGIBLE"
            )
            raise problema(
                422,
                codigo,
                "El subproducto no es elegible para este cliente.",
                bloqueos=motivos,
            )
        rol = rol_para_apertura(
            conn, cliente["tipo_cliente"], cliente["fecha_nacimiento"], fecha
        )
        relacion = (
            None
            if rol is None
            else relacion_vigente(conn, payload.id_cliente, rol, fecha)
        )
        if rol is not None and relacion is None:
            codigo = (
                "MENOR_SIN_TUTOR" if rol == "Tutor" else "REPRESENTANTE_NO_VERIFICABLE"
            )
            raise problema(422, codigo, "El cliente requiere una relación vigente.")
        condiciones = productos_service.condiciones_vigentes(
            conn, payload.id_sub_producto, fecha, "FICHA"
        )
        if condiciones is None:
            raise problema(
                409,
                "CONDICIONES_NO_VIGENTES",
                "El subproducto carece de condiciones vigentes.",
            )
        agencia_bd = repository.obtener_agencia(conn, agencia)
        if agencia_bd is None or agencia_bd["estado"] != "A":
            raise problema(
                409, "AGENCIA_INACTIVA", "La agencia activa no admite aperturas."
            )
        numero = siguiente_numero_cuenta(conn, payload.id_sub_producto, agencia)
        cuenta_id = repository.registrar_apertura(
            conn,
            numero,
            payload.id_cliente,
            payload.id_sub_producto,
            agencia,
            condiciones["monto_apertura_minimo"],
            actor,
        )
        if relacion is not None:
            conn.execute(
                text("""
                    INSERT Cuentas.CuentaAutorizado
                        (IdCuenta, IdClienteAutorizado, Rol, IdClienteRelacion, FechaInicio, FechaFin, CreadoPor)
                    VALUES (:cuenta,:cliente,:rol,:relacion,:inicio,:fin,:actor);
                """),
                {
                    "cuenta": cuenta_id,
                    "cliente": relacion["IdClienteRelacionado"],
                    "rol": rol,
                    "relacion": relacion["IdRelacion"],
                    "inicio": fecha,
                    "fin": relacion["FechaFin"],
                    "actor": actor,
                },
            )
        cuenta = obtener_cuenta(conn, cuenta_id)
        conn.commit()
        return cuenta
    except Exception:
        conn.rollback()
        raise


def anular_apertura(
    conn: Connection, id_cuenta: int, id_agencia: str, motivo: str, actor: int
) -> Cuenta:
    """Anula una pendiente de la agencia activa durante su día de apertura."""
    try:
        fila = (
            conn.execute(
                text("""
                SELECT Estado, CONVERT(date,FechaApertura) AS Fecha
                FROM Cuentas.Cuenta WITH (UPDLOCK,HOLDLOCK)
                WHERE IdCuenta=:id AND IdAgencia=:agencia
            """),
                {"id": id_cuenta, "agencia": id_agencia},
            )
            .mappings()
            .first()
        )
        if fila is None:
            raise problema(
                404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia activa."
            )
        if fila["Estado"] != "PendienteDeposito" or fila["Fecha"] != hoy():
            raise problema(
                409,
                "APERTURA_NO_ANULABLE",
                "Solo se anula una apertura pendiente en su día de creación.",
            )
        conn.execute(
            text("""
                UPDATE Cuentas.Cuenta SET Estado='Anulada' WHERE IdCuenta=:id;
                INSERT Cuentas.CuentaEvento
                    (IdCuenta,TipoEvento,EstadoAnterior,EstadoActual,Detalle,RealizadoPor,IdAgencia)
                VALUES (:id,'Anulacion','PendienteDeposito','Anulada',:motivo,:actor,:agencia);
            """),
            {"id": id_cuenta, "agencia": id_agencia, "motivo": motivo, "actor": actor},
        )
        cuenta = obtener_cuenta(conn, id_cuenta)
        conn.commit()
        return cuenta
    except Exception:
        conn.rollback()
        raise


def anular_pendientes_vencidas(conn: Connection, fecha: date) -> int:
    """Cancela las pendientes vencidas y deja un evento por cuenta en la misma transacción."""
    dias = general.valor(conn, "CTA_DIAS_SIN_DEPOSITO", fecha)
    if type(dias) is not int or dias < 1:
        raise problema(
            503, "PARAMETRO_INVALIDO", "No se pudo obtener el plazo de apertura."
        )
    return conn.execute(
        text("""
            SET NOCOUNT ON;
            DECLARE @Anuladas TABLE (IdCuenta int, IdAgencia char(3));
            UPDATE Cuentas.Cuenta SET Estado='Anulada'
            OUTPUT inserted.IdCuenta, inserted.IdAgencia INTO @Anuladas
            WHERE Estado='PendienteDeposito'
              AND FechaApertura < DATEADD(day, -:dias, CAST(:fecha AS date));
            INSERT Cuentas.CuentaEvento
                (IdCuenta,TipoEvento,EstadoAnterior,EstadoActual,Detalle,RealizadoPor,IdAgencia)
            SELECT IdCuenta,'Anulacion','PendienteDeposito','Anulada',N'Sin primer depósito',0,IdAgencia
            FROM @Anuladas;
            SELECT COUNT(*) FROM @Anuladas;
        """),
        {"dias": dias, "fecha": fecha},
    ).scalar_one()


_TRANSICIONES_CUENTA = {
    "ACTIVA": {"INACTIVA", "BLOQUEADA"},
    "INACTIVA": {"ACTIVA"},
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
    payload: CupoSolicitado,
    modificado_por: int,
    *,
    agencia: str | None = None,
    usuario: Usuario | None = None,
    ip: str = "",
) -> CupoEfectivo:
    try:
        cuenta = repository.bloquear_cuenta(conn, id_cuenta)
        if cuenta is None or (agencia is not None and cuenta["id_agencia"] != agencia):
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
                "CUPO_SOBRE_TOPE",
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
        encolar_evento(
            conn,
            codigo="CTA_CUPO_CAMBIADO",
            sujeto=usuario.id_usuario if usuario else str(modificado_por),
            organizacion=usuario.id_organizacion if usuario else None,
            roles=list(usuario.roles) if usuario else [],
            agencia=cuenta["id_agencia"],
            sesion=usuario.id_sesion if usuario else "",
            origen=ip,
            canal="API",
            tabla="Canal.CanalCupoClienteCustom",
            id_objetivo=str(id_cuenta),
            descripcion=f"Cupo del canal {id_canal} ajustado a pedido del cliente.",
            cambios={
                "idCanal": id_canal,
                "modificadoPor": modificado_por,
                "cupoNuevo": payload.model_dump(mode="json", by_alias=True),
            },
        )
        conn.commit()
    except DBAPIError as exc:
        conn.rollback()
        raise traducir_error_bd(exc, operacion="CTA08") from None
    except Exception:
        conn.rollback()
        raise

    return resultado


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
