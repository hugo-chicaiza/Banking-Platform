"""Solicitudes de dotación y ejecución atómica en CooperativaDB."""

import hashlib
import json
from datetime import UTC
from decimal import Decimal

from sqlalchemy import Connection, bindparam, text

from app.core.api.errors import problema
from app.core.security.auth import Usuario
from app.core.security.operador import (
    auditar,
    exigir_agencia,
    exigir_agencia_autorizada,
)
from app.modules.boveda.repository import vincular_asiento
from app.modules.caja import repository as repo
from app.modules.caja import service
from app.modules.caja.repository import Fila
from app.modules.caja.schemas import (
    AutorizadorDotacion,
    Desglose,
    Dotacion,
    SolicitarDotacion,
    SolicitudDotacion,
)
from app.modules.contabilidad.asientos import OperacionContable, generar_asiento
from app.modules.contabilidad.service import ahora_ecuador


def _fila(conn: Connection, id_solicitud: int, bloquear: bool = False) -> Fila:
    consulta = (
        "SELECT * FROM Caja.SolicitudDotacion WITH(UPDLOCK,HOLDLOCK) WHERE IdSolicitud=:id"
        if bloquear
        else "SELECT * FROM Caja.SolicitudDotacion WHERE IdSolicitud=:id"
    )
    fila = conn.execute(text(consulta), {"id": id_solicitud}).mappings().first()
    if fila is None:
        raise problema(
            404, "SOLICITUD_DOTACION_NO_ENCONTRADA", "La solicitud no existe."
        )
    return dict(fila)


def _alcance(usuario: Usuario, agencia: str) -> None:
    exigir_agencia_autorizada(usuario, agencia)
    if exigir_agencia(usuario) != agencia:
        raise problema(403, "SIN_ACCESO_AGENCIA", "La agencia operativa no coincide.")


def _supervisor(usuario: Usuario, actor: int, fila: Fila) -> None:
    if actor == fila["SolicitadoPor"]:
        raise problema(403, "DOBLE_CUSTODIA", "Debe confirmar otra persona.")
    if "SUPERVISOR" not in usuario.roles:
        raise problema(403, "SIN_PERMISO", "Se requiere un supervisor autorizado.")
    agencia = fila["IdAgencia"].strip()
    _alcance(usuario, agencia)
    if actor != fila["AutorizadoPor"]:
        raise problema(
            403,
            "AUTORIZADOR_NO_ASIGNADO",
            "La solicitud está asignada a otro autorizador.",
        )
    if not repo.autorizadores_dotacion(agencia, fila["SolicitadoPor"], actor):
        raise problema(
            403,
            "AUTORIZADOR_NO_VALIDO",
            "El autorizador ya no está habilitado en la agencia.",
        )


def _abierta(jornada: Fila) -> None:
    if jornada["Estado"] != "ABIERTA":
        raise problema(409, "JORNADA_NO_ABIERTA", "La jornada no está ABIERTA.")


def _boveda(conn: Connection, id_boveda: int, agencia: str) -> None:
    fila = (
        conn.execute(
            text(
                "SELECT IdAgencia,Estado FROM Boveda.Boveda WITH(UPDLOCK,HOLDLOCK) WHERE IdBoveda=:id"
            ),
            {"id": id_boveda},
        )
        .mappings()
        .first()
    )
    if fila is None:
        raise problema(404, "BOVEDA_NO_ENCONTRADA", "La bóveda no existe.")
    if fila["IdAgencia"].strip() != agencia:
        raise problema(
            409, "BOVEDA_OTRA_AGENCIA", "La bóveda pertenece a otra agencia."
        )
    if fila["Estado"] != "A":
        raise problema(409, "BOVEDA_NO_ACTIVA", "La bóveda no está activa.")


def _valores(conn: Connection, detalle: list[Desglose]) -> dict[str, str]:
    consulta = text("""
        SELECT IdDenominacion,Valor FROM Catalogo.Denominacion WITH(HOLDLOCK)
        WHERE IdDenominacion IN :ids AND Estado='A'
    """).bindparams(bindparam("ids", expanding=True))
    filas = conn.execute(consulta, {"ids": [d.id_denominacion for d in detalle]})
    valores = {str(i): format(Decimal(valor), ".2f") for i, valor in filas}
    if len(valores) != len(detalle):
        raise problema(
            422,
            "DENOMINACION_NO_DISPONIBLE",
            "Hay denominaciones inexistentes o inactivas.",
        )
    return valores


def _desglose(fila: Fila) -> list[Desglose]:
    return [
        Desglose(id_denominacion=linea["IdDenominacion"], cantidad=linea["Cantidad"])
        for linea in json.loads(fila["Desglose"])
    ]


def _respuesta(fila: Fila, fecha: int) -> SolicitudDotacion:
    estado = fila["Estado"]
    if estado == "PENDIENTE" and fila["IdFechaContable"] != fecha:
        estado = "CADUCADA"
    resuelta = fila["FechaResolucion"]
    return SolicitudDotacion(
        id_solicitud=fila["IdSolicitud"],
        id_jornada=fila["IdJornada"],
        id_boveda=fila["IdBoveda"],
        id_agencia=fila["IdAgencia"].strip(),
        id_fecha_contable=fila["IdFechaContable"],
        solicitado_por=fila["SolicitadoPor"],
        autorizado_por=fila["AutorizadoPor"],
        fecha_solicitud=fila["FechaSolicitud"].replace(tzinfo=UTC),
        tipo_dotacion=fila["TipoDotacion"],
        desglose=_desglose(fila),
        monto=fila["Monto"],
        observacion=fila["Observacion"],
        estado=estado,
        resuelto_por=fila["ResueltoPor"],
        fecha_resolucion=resuelta.replace(tzinfo=UTC) if resuelta else None,
        motivo=fila["Motivo"],
        id_dotacion_caja=fila["IdDotacionCaja"],
    )


def consultar_autorizadores(
    conn: Connection, usuario: Usuario, actor: int, id_jornada: int
) -> list[AutorizadorDotacion]:
    jornada = repo.obtener_jornada(conn, id_jornada)
    if jornada is None:
        raise service.jornada_no_encontrada()
    service.verificar_alcance(usuario, actor, jornada, ("CAJERO",))
    agencia = jornada["IdAgencia"].strip()
    _alcance(usuario, agencia)
    return [
        AutorizadorDotacion(
            id_usuario=fila["UsuarioID"], nombre_completo=fila["NombreCompleto"]
        )
        for fila in repo.autorizadores_dotacion(agencia, actor)
    ]


def solicitar(
    conn: Connection,
    usuario: Usuario,
    actor: int,
    id_jornada: int,
    datos: SolicitarDotacion,
    clave: str,
) -> SolicitudDotacion:
    detalle = sorted(datos.desglose, key=lambda d: d.id_denominacion)
    desglose = service.desglose_json(detalle)
    contenido = json.dumps(
        [
            id_jornada,
            datos.id_boveda,
            datos.tipo_dotacion,
            desglose,
            datos.observacion,
            datos.autorizado_por,
        ]
    )
    huella = hashlib.sha256(contenido.encode()).hexdigest()
    with conn.begin():
        jornada = service.jornada_bloqueada(conn, id_jornada)
        service.verificar_alcance(usuario, actor, jornada, ("CAJERO",))
        agencia = jornada["IdAgencia"].strip()
        _alcance(usuario, agencia)
        fecha = service.fecha_contable(conn, ahora_ecuador())
        previa = (
            conn.execute(
                text("""
            SELECT * FROM Caja.SolicitudDotacion WITH(UPDLOCK,HOLDLOCK)
            WHERE SolicitadoPor=:actor AND Clave=:clave
        """),
                {"actor": actor, "clave": clave},
            )
            .mappings()
            .first()
        )
        if previa is not None:
            if previa["Huella"] != huella:
                raise problema(
                    409,
                    "IDEMPOTENCIA_CONFLICTO",
                    "La clave ya corresponde a otra solicitud.",
                )
            return _respuesta(dict(previa), fecha)
        _abierta(jornada)
        if datos.autorizado_por == actor:
            raise problema(403, "DOBLE_CUSTODIA", "Debe asignar a otra persona.")
        if not repo.autorizadores_dotacion(agencia, actor, datos.autorizado_por):
            raise problema(
                422,
                "AUTORIZADOR_NO_VALIDO",
                "Seleccione un supervisor habilitado de la agencia.",
            )
        _boveda(conn, datos.id_boveda, agencia)
        valores = _valores(conn, detalle)
        monto = sum(
            (Decimal(valores[str(d.id_denominacion)]) * d.cantidad for d in detalle),
            Decimal(0),
        )
        if not Decimal(0) < monto < Decimal(10000000000000000):
            raise problema(
                422,
                "MONTO_DOTACION_INVALIDO",
                "El monto está fuera del rango permitido.",
            )
        fila = (
            conn.execute(
                text("""
            INSERT Caja.SolicitudDotacion (IdJornada,IdBoveda,IdAgencia,IdFechaContable,
                SolicitadoPor,AutorizadoPor,TipoDotacion,Desglose,Valores,Monto,Observacion,Clave,Huella)
            OUTPUT inserted.*
            VALUES (:jornada,:boveda,:agencia,:fecha,:actor,:autorizado,:tipo,:desglose,:valores,:monto,:observacion,:clave,:huella)
        """),
                {
                    "jornada": id_jornada,
                    "boveda": datos.id_boveda,
                    "agencia": agencia,
                    "fecha": fecha,
                    "actor": actor,
                    "autorizado": datos.autorizado_por,
                    "tipo": datos.tipo_dotacion,
                    "desglose": desglose,
                    "valores": json.dumps(valores),
                    "monto": monto,
                    "observacion": datos.observacion,
                    "clave": clave,
                    "huella": huella,
                },
            )
            .mappings()
            .one()
        )
        return _respuesta(dict(fila), fecha)


def consultar(
    conn: Connection,
    usuario: Usuario,
    actor: int,
    id_jornada: int,
    antes_de: int | None,
) -> list[SolicitudDotacion]:
    jornada = repo.obtener_jornada(conn, id_jornada)
    if jornada is None:
        raise service.jornada_no_encontrada()
    service.verificar_alcance(usuario, actor, jornada, ("CAJERO", "SUPERVISOR"))
    _alcance(usuario, jornada["IdAgencia"].strip())
    fecha = service.fecha_contable(conn, ahora_ecuador())
    filas = conn.execute(
        text("""
        SELECT TOP(100) * FROM Caja.SolicitudDotacion
        WHERE IdJornada=:id AND (:antes IS NULL OR IdSolicitud<:antes)
        ORDER BY IdSolicitud DESC
    """),
        {"id": id_jornada, "antes": antes_de},
    ).mappings()
    return [_respuesta(dict(fila), fecha) for fila in filas]


def _pendiente(fila: Fila) -> None:
    if fila["Estado"] != "PENDIENTE":
        raise problema(
            409, "SOLICITUD_DOTACION_RESUELTA", "La solicitud ya fue resuelta."
        )


def _efectiva(conn: Connection, id_dotacion: int, alerta: bool) -> Dotacion:
    dotacion = repo.obtener_dotacion(conn, id_dotacion)
    if dotacion is None:
        raise RuntimeError("No se encontró la dotación efectiva.")
    return service._dotacion(dotacion, alerta)


def confirmar(
    conn: Connection,
    usuario: Usuario,
    actor: int,
    id_solicitud: int,
    ip: str,
) -> tuple[Dotacion, bool]:
    with (
        auditar(
            "REGISTRAR_DOTACION",
            "Caja.DotacionesCaja",
            usuario,
            ip,
            f"solicitud={id_solicitud}",
        ) as auditoria,
        conn.begin(),
    ):
        referencia = _fila(conn, id_solicitud)
        jornada = service.jornada_bloqueada(conn, referencia["IdJornada"])
        fila = _fila(conn, id_solicitud, bloquear=True)
        _supervisor(usuario, actor, fila)
        if fila["Estado"] == "CONFIRMADA":
            return _efectiva(
                conn, fila["IdDotacionCaja"], fila["BovedaBajoMinimo"]
            ), True
        _pendiente(fila)
        _abierta(jornada)
        agencia = jornada["IdAgencia"].strip()
        if (
            agencia != fila["IdAgencia"].strip()
            or jornada["IdUsuario"] != fila["SolicitadoPor"]
        ):
            raise problema(
                409,
                "SOLICITUD_DOTACION_DESACTUALIZADA",
                "Cambió la jornada de la solicitud.",
            )
        _boveda(conn, fila["IdBoveda"], agencia)
        detalle = _desglose(fila)
        if _valores(conn, detalle) != json.loads(fila["Valores"]):
            raise problema(
                409,
                "SOLICITUD_DOTACION_DESACTUALIZADA",
                "Cambió el valor de las denominaciones.",
            )
        ahora = ahora_ecuador()
        fecha = service.fecha_contable(conn, ahora)
        if fecha != fila["IdFechaContable"]:
            raise problema(
                409,
                "SOLICITUD_DOTACION_CADUCADA",
                "La solicitud corresponde a otro día contable.",
            )
        inicial = fila["TipoDotacion"] == "INICIAL"
        if inicial:
            repo.preparar_dotacion_inicial(conn, fila["IdJornada"], fila["Monto"])
        limite = repo.limite_efectivo_caja(conn, jornada["IdCajaFisica"])
        if limite is not None:
            saldo = service.saldo_esperado(service._totales(conn, fila["IdJornada"]))
            saldo_resultante = saldo if inicial else saldo + fila["Monto"]
            if saldo_resultante > limite:
                raise problema(
                    409,
                    "LIMITE_EFECTIVO_CAJA_EXCEDIDO",
                    "La dotación excedería el límite de efectivo de la ventanilla.",
                )
        salida = repo.registrar_dotacion(
            conn,
            fila["IdJornada"],
            fila["IdBoveda"],
            actor,
            fila["TipoDotacion"],
            fila["Desglose"],
            fila["Observacion"],
            fecha,
        )
        id_dotacion = int(salida["IdDotacionCaja"])
        alerta = bool(salida["BovedaBajoMinimo"])
        dotacion = _efectiva(conn, id_dotacion, alerta)
        monto = dotacion.monto
        if monto is None or monto != fila["Monto"]:
            raise RuntimeError("El monto aplicado difiere de la solicitud.")
        id_asiento = generar_asiento(
            conn,
            OperacionContable(
                codigo_plantilla="DOT_CAJA",
                clave_evento=f"DOTACION_CAJA:{id_dotacion}",
                id_agencia=agencia,
                id_fecha_contable=fecha,
                id_usuario=actor,
                fecha_hora=ahora,
                importes={"PRINCIPAL": monto},
            ),
        )
        movimiento = int(salida["IdMovimientoBoveda"])
        vincular_asiento(conn, movimiento, id_asiento)
        repo.vincular_asiento_dotacion(conn, id_dotacion, id_asiento)
        conn.execute(
            text("""
            UPDATE Caja.SolicitudDotacion SET Estado='CONFIRMADA',ResueltoPor=:actor,
                FechaResolucion=SYSUTCDATETIME(),IdDotacionCaja=:dotacion,BovedaBajoMinimo=:alerta
            WHERE IdSolicitud=:id
        """),
            {
                "id": id_solicitud,
                "actor": actor,
                "dotacion": id_dotacion,
                "alerta": alerta,
            },
        )
        auditoria.id_registro = str(id_dotacion)
        auditoria.confirmar(
            conn,
            objetivo="Boveda.MovimientoBoveda",
            id_objetivo=str(movimiento),
            cambios={
                "idSolicitudDotacion": id_solicitud,
                "idDotacionCaja": id_dotacion,
            },
        )
        return dotacion.model_copy(update={"id_asiento_contable": id_asiento}), False


def rechazar(
    conn: Connection,
    usuario: Usuario,
    actor: int,
    id_solicitud: int,
    motivo: str,
) -> SolicitudDotacion:
    with conn.begin():
        fila = _fila(conn, id_solicitud, bloquear=True)
        _supervisor(usuario, actor, fila)
        fecha = service.fecha_contable(conn, ahora_ecuador())
        if (
            fila["Estado"] == "RECHAZADA"
            and fila["ResueltoPor"] == actor
            and fila["Motivo"] == motivo
        ):
            return _respuesta(fila, fecha)
        _pendiente(fila)
        resuelta = (
            conn.execute(
                text("""
            UPDATE Caja.SolicitudDotacion SET Estado='RECHAZADA',ResueltoPor=:actor,
                FechaResolucion=SYSUTCDATETIME(),Motivo=:motivo
            OUTPUT inserted.* WHERE IdSolicitud=:id
        """),
                {"id": id_solicitud, "actor": actor, "motivo": motivo},
            )
            .mappings()
            .one()
        )
        return _respuesta(dict(resuelta), fecha)
