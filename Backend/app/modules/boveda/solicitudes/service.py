"""Solicitud, reserva, entrega y confirmación física de efectivo."""

import hashlib
import json
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.security.auth import Usuario
from app.core.security.operador import auditar, exigir_agencia, exigir_id_interno
from app.modules.boveda import repository as boveda_repo
from app.modules.boveda import service as boveda
from app.modules.boveda.solicitudes import repository as repo
from app.modules.boveda.solicitudes.repository import Fila
from app.modules.boveda.solicitudes.schemas import (
    CierreRequest,
    DespachoRequest,
    DestinoBoveda,
    DetalleSolicitud,
    DevolucionRequest,
    PageSolicitudMovimiento,
    RecepcionRequest,
    SolicitudMovimiento,
    SolicitudMovimientoRequest,
)
from app.modules.contabilidad import repository as contable_repo
from app.modules.contabilidad import service as contabilidad
from app.modules.contabilidad.asientos import ErrorContable, resolver_lineas
from app.modules.contabilidad.boveda_versionada import codigo_boveda

_MAX_DINERO = Decimal("9999999999999999.99")


def _huella(id_boveda: int, datos: SolicitudMovimientoRequest) -> str:
    contenido = {**datos.model_dump(mode="json"), "boveda": id_boveda}
    contenido["desglose"] = sorted(
        contenido["desglose"], key=lambda d: d["id_denominacion"]
    )
    return hashlib.sha256(json.dumps(contenido, sort_keys=True).encode()).hexdigest()


def _modelos(conn: Connection, filas: list[Fila]) -> list[SolicitudMovimiento]:
    ids = [f["id_solicitud_movimiento"] for f in filas]
    detalles = repo.detalles(conn, ids)
    conteos = repo.conteos(conn, ids)
    movimientos = repo.movimientos(conn, ids)
    return [
        SolicitudMovimiento(
            **{
                k: v
                for k, v in f.items()
                if k
                not in {
                    "huella_peticion",
                    "id_cuenta_transito",
                    "usa_plantilla_versionada",
                }
            },
            desglose=[
                DetalleSolicitud(**d) for d in detalles[f["id_solicitud_movimiento"]]
            ],
            conteo_confirmado=[
                DetalleSolicitud(**d) for d in conteos[f["id_solicitud_movimiento"]]
            ],
            ids_movimientos=movimientos[f["id_solicitud_movimiento"]],
        )
        for f in filas
    ]


def _exigir(fila: Fila | None) -> Fila:
    if fila is None:
        raise problema(
            404,
            "SOLICITUD_MOVIMIENTO_NO_ENCONTRADA",
            "La solicitud de movimiento no existe.",
        )
    return fila


def _estado(fila: Fila, esperado: str) -> None:
    if fila["estado"] != esperado:
        raise problema(
            409,
            "ESTADO_SOLICITUD_INVALIDO",
            "El estado actual no admite esta operación.",
        )


def _agencia_operativa(usuario: Usuario, agencia: str) -> None:
    if exigir_agencia(usuario) != agencia:
        raise problema(
            403,
            "SIN_ACCESO_AGENCIA",
            "La agencia operativa no puede realizar esta acción.",
        )


def _distinto(actor: int, anterior: int | None, codigo: str, mensaje: str) -> None:
    if actor == anterior:
        raise problema(409, codigo, mensaje)


def _bovedas(
    conn: Connection, id_boveda: int, contraparte: int | None, activas: bool = True
) -> dict[int, Fila]:
    ids = sorted({id_boveda, contraparte} if contraparte is not None else {id_boveda})
    return {
        i: boveda._exigir_boveda(
            boveda_repo.obtener_boveda(conn, i, bloquear=True),
            estado=activas,
            cuerpo=i != id_boveda,
        )
        for i in ids
    }


def _contraparte(id_boveda: int, datos: SolicitudMovimientoRequest) -> None:
    if datos.tipo_movimiento == "Traslado" and datos.id_boveda_contraparte is None:
        raise problema(
            422,
            "TRASLADO_REQUIERE_CONTRAPARTE",
            "El traslado requiere una bóveda destino.",
        )
    if datos.id_boveda_contraparte == id_boveda or (
        datos.tipo_movimiento != "Traslado" and datos.id_boveda_contraparte is not None
    ):
        raise problema(
            422,
            "CONTRAPARTE_INVALIDA",
            "La contraparte no es válida para esta operación.",
        )


def _catalogo(conn: Connection, ids: list[int]) -> dict[int, Fila]:
    filas = boveda_repo.denominaciones(conn, ids)
    if len(filas) != len(ids):
        raise problema(422, "DENOMINACION_NO_ENCONTRADA", "Una denominación no existe.")
    if any(f["estado"] != "A" for f in filas.values()):
        raise problema(
            409, "DENOMINACION_NO_ACTIVA", "Una denominación no está activa."
        )
    return filas


def _detalle(conn: Connection, datos: Any) -> list[Fila]:
    cantidades = {d.id_denominacion: d.cantidad for d in datos.desglose}
    catalogo = _catalogo(conn, list(cantidades))
    return [
        {
            "id_denominacion": i,
            "cantidad": cantidad,
            "valor_unitario": catalogo[i]["valor"],
        }
        for i, cantidad in sorted(cantidades.items())
        if cantidad
    ]


def _total(detalle: list[Fila]) -> Decimal:
    monto = sum((d["cantidad"] * d["valor_unitario"] for d in detalle), Decimal(0))
    if monto > _MAX_DINERO:
        raise problema(422, "MONTO_FUERA_RANGO", "El monto excede el rango permitido.")
    return monto


def _confirmar_propuesta(conn: Connection, fila: Fila) -> list[Fila]:
    detalle = repo.detalles(conn, [fila["id_solicitud_movimiento"]])[
        fila["id_solicitud_movimiento"]
    ]
    catalogo = _catalogo(conn, [d["id_denominacion"] for d in detalle])
    datos = SolicitudMovimientoRequest.model_validate(
        {
            "tipo_movimiento": fila["tipo_movimiento"],
            "id_boveda_contraparte": fila["id_boveda_contraparte"],
            "observaciones": fila["observaciones"],
            "desglose": [
                {"id_denominacion": d["id_denominacion"], "cantidad": d["cantidad"]}
                for d in detalle
            ],
        }
    )
    if (
        _huella(fila["id_boveda"], datos) != fila["huella_peticion"]
        or _total(detalle) != fila["monto"]
        or any(
            catalogo[d["id_denominacion"]]["valor"] != d["valor_unitario"]
            for d in detalle
        )
    ):
        raise problema(
            409,
            "SOLICITUD_MOVIMIENTO_DESACTUALIZADA",
            "Cambió la información de la solicitud.",
        )
    return detalle


def _vigencia(bovedas: dict[int, Fila], fila: Fila) -> None:
    contraparte = fila["id_boveda_contraparte"]
    if bovedas[fila["id_boveda"]]["id_agencia"] != fila["id_agencia"] or (
        contraparte is not None
        and bovedas[contraparte]["id_agencia"] != fila["id_agencia_destino"]
    ):
        raise problema(
            409,
            "SOLICITUD_MOVIMIENTO_DESACTUALIZADA",
            "Cambió la agencia de una bóveda.",
        )


def _bloquear(conn: Connection, solicitud: int) -> tuple[Fila, dict[int, Fila]]:
    # Todas las mutaciones bloquean bóvedas en orden de id antes de la solicitud.
    inicial = _exigir(repo.obtener(conn, solicitud))
    bovedas = _bovedas(
        conn, inicial["id_boveda"], inicial["id_boveda_contraparte"], activas=False
    )
    fila = _exigir(repo.obtener(conn, solicitud, bloquear=True))
    return fila, bovedas


def destinos(conn: Connection, usuario: Usuario, origen: int) -> list[DestinoBoveda]:
    with conn.begin():
        fila = boveda._exigir_boveda(
            boveda_repo.obtener_boveda(conn, origen), estado=True
        )
        _agencia_operativa(usuario, fila["id_agencia"])
        return [DestinoBoveda.model_validate(f) for f in repo.destinos(conn, origen)]


def crear(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_boveda: int,
    datos: SolicitudMovimientoRequest,
    ip: str,
    clave: str | None,
) -> SolicitudMovimiento:
    with auditar(
        "SOLICITAR_MOVIMIENTO_BOVEDA",
        "Boveda.SolicitudMovimientoBoveda",
        usuario,
        ip,
        f"boveda={id_boveda}",
    ) as registro:
        actor = exigir_id_interno(id_interno)
        _contraparte(id_boveda, datos)
        huella = _huella(id_boveda, datos)
        with conn.begin():
            bovedas = _bovedas(
                conn, id_boveda, datos.id_boveda_contraparte, activas=False
            )
            origen = bovedas[id_boveda]["id_agencia"]
            _agencia_operativa(usuario, origen)
            if clave:
                repetida = repo.repeticion(conn, actor, clave)
                if repetida is not None:
                    if repetida["huella_peticion"] != huella:
                        raise problema(
                            409,
                            "IDEMPOTENCIA_CONFLICTO",
                            "La clave ya se utilizó con otros datos.",
                        )
                    registro.id_registro = str(repetida["id_solicitud_movimiento"])
                    return _modelos(conn, [repetida])[0]
            if datos.tipo_movimiento in {"AjusteFaltante", "AjusteSobrante"}:
                raise problema(
                    422,
                    "AJUSTE_REQUIERE_ARQUEO",
                    "Registre un arqueo para ajustar el efectivo.",
                )
            for fila_boveda in bovedas.values():
                boveda._exigir_boveda(fila_boveda, estado=True)
            destino = (
                bovedas[datos.id_boveda_contraparte]["id_agencia"]
                if datos.id_boveda_contraparte
                else None
            )
            agencias = sorted({origen, destino} if destino else {origen})
            for agencia in agencias:
                if repo.cupo_ocupado(conn, agencia):
                    raise problema(
                        409,
                        "AGENCIA_CON_SOLICITUD_ACTIVA",
                        "Una agencia ya participa en otro movimiento.",
                    )
            detalle = _detalle(conn, datos)
            monto = _total(detalle)
            solicitud = repo.crear(
                conn,
                {
                    "boveda": id_boveda,
                    "contraparte": datos.id_boveda_contraparte,
                    "agencia": origen,
                    "agencia_destino": destino,
                    "tipo": datos.tipo_movimiento,
                    "monto": monto,
                    "actor": actor,
                    "ahora": contabilidad.ahora_ecuador(),
                    "observaciones": datos.observaciones,
                    "clave": clave,
                    "huella": huella,
                },
                detalle,
            )
            repo.reservar_cupo(conn, solicitud, agencias)
            registro.id_registro = str(solicitud)
            registro.confirmar(conn, cambios={"monto": str(monto)})
            return _modelos(conn, [_exigir(repo.obtener(conn, solicitud))])[0]


def listar(
    conn: Connection,
    usuario: Usuario,
    agencia: str | None,
    estado: str | None,
    page: int,
    page_size: int,
) -> PageSolicitudMovimiento:
    with conn.begin():
        filas, total = repo.listar(
            conn, boveda._agencia(usuario, agencia), estado, page, page_size
        )
        return PageSolicitudMovimiento(
            items=_modelos(conn, filas), total=total, page=page, page_size=page_size
        )


def obtener(
    conn: Connection, usuario: Usuario, id_solicitud: int
) -> SolicitudMovimiento:
    with conn.begin():
        fila = _exigir(repo.obtener(conn, id_solicitud))
        agencia = usuario.agencia()
        alcance = (
            agencia
            if agencia and agencia == fila.get("id_agencia_destino")
            else fila["id_agencia"]
        )
        boveda._alcance(usuario, alcance)
        return _modelos(conn, [fila])[0]


def _plantilla(conn: Connection, agencia: str, tipo: str, naturaleza: str) -> Fila:
    plantilla = contable_repo.plantilla_boveda(conn, agencia, tipo, naturaleza)
    if plantilla is None or plantilla["estado_tipo"] != "A":
        raise problema(
            409,
            "PLANTILLA_BOVEDA_NO_CONFIGURADA",
            "Falta configurar la plantilla contable de la etapa.",
        )
    for cuenta_id in sorted({plantilla["debito"], plantilla["credito"]}):
        cuenta = contable_repo.cuenta_boveda(conn, cuenta_id)
        if cuenta is None or not cuenta["estado"] or not cuenta["imputable"]:
            raise problema(
                409,
                "CUENTA_CONTABLE_NO_HABILITADA",
                "La plantilla contiene una cuenta inactiva o no imputable.",
            )
    return plantilla


def _misma_cuenta(esperada: int, actual: int) -> None:
    if esperada != actual:
        raise problema(
            409,
            "CUENTA_TRANSITO_INCONSISTENTE",
            "Las etapas deben usar la misma cuenta de efectivo en tránsito.",
        )


def _misma_boveda(esperada: int, actual: int) -> None:
    if esperada != actual:
        raise problema(
            409,
            "CUENTA_RETORNO_INCONSISTENTE",
            "La devolución debe usar la cuenta de la bóveda de origen para el reingreso.",
        )


def _plantilla_versionada(
    conn: Connection, agencia: str, tipo: str, naturaleza: str, fecha: int
) -> Fila | None:
    dia = contable_repo.obtener_por_id(conn, fecha)
    if dia is None:
        return None
    return contable_repo.obtener_plantilla(
        conn, codigo_boveda(agencia, tipo, naturaleza), dia["fecha"]
    )


def _cuentas_versionadas(conn: Connection, plantilla: Fila, monto: Decimal) -> Fila:
    lineas = contable_repo.obtener_lineas_plantilla(
        conn, plantilla["IdPlantillaAsiento"]
    )
    try:
        resueltas = resolver_lineas(lineas, {"PRINCIPAL": monto}, conn=conn)
        cuentas = {l["lado"].lower(): l["cuenta"] for l in resueltas}
        if len(resueltas) != 2 or cuentas["debito"] == cuentas["credito"]:
            raise ErrorContable("La etapa usa dos cuentas distintas.")
    except ErrorContable as exc:
        raise problema(
            409,
            "MATRIZ_BOVEDA_INVALIDA",
            "La plantilla vigente de la etapa no permite cuadrar el efectivo.",
        ) from exc
    return cuentas


def _validar_cuentas(conn: Connection, fila: Fila) -> tuple[int | None, bool]:
    contable_repo.bloquear_contabilizacion(conn)
    tipo, origen, destino = (
        fila["tipo_movimiento"],
        fila["id_agencia"],
        fila["id_agencia_destino"],
    )
    if tipo == "ProvisionExterna":
        fecha = contabilidad.resolver_id_fecha_contable(
            conn, contabilidad.ahora_ecuador()
        )
        version = _plantilla_versionada(conn, origen, tipo, "I", fecha)
        if version:
            _cuentas_versionadas(conn, version, fila["monto"])
        else:
            _plantilla(conn, origen, tipo, "I")
        return None, bool(version)
    if tipo == "EnvioExcedente":
        transito = _plantilla(conn, origen, "DespachoExcedente", "E")["debito"]
        _misma_cuenta(
            transito, _plantilla(conn, origen, "CierreExcedente", "I")["credito"]
        )
        return transito, False
    fecha = contabilidad.resolver_id_fecha_contable(conn, contabilidad.ahora_ecuador())
    sale = _plantilla_versionada(conn, origen, "Traslado", "E", fecha)
    entra = _plantilla_versionada(conn, destino, "Traslado", "I", fecha)
    if sale is not None and entra is not None:
        cuentas_salida = _cuentas_versionadas(conn, sale, fila["monto"])
        transito = cuentas_salida["debito"]
        _misma_cuenta(
            transito, _cuentas_versionadas(conn, entra, fila["monto"])["credito"]
        )
    else:
        cuentas_salida = _plantilla(conn, origen, "Traslado", "E")
        transito = cuentas_salida["debito"]
        _misma_cuenta(transito, _plantilla(conn, destino, "Traslado", "I")["credito"])
    cuentas_retorno = _plantilla(conn, origen, "RetornoRemesa", "I")
    _misma_cuenta(transito, cuentas_retorno["credito"])
    _misma_boveda(cuentas_salida["credito"], cuentas_retorno["debito"])
    for agencia in sorted({origen, destino}):
        _misma_cuenta(
            transito, _plantilla(conn, agencia, "FaltanteTransito", "E")["credito"]
        )
        _misma_cuenta(
            transito, _plantilla(conn, agencia, "SobranteTransito", "I")["debito"]
        )
    return transito, sale is not None and entra is not None


def _reservar_efectivo(
    conn: Connection, fila: Fila, bovedas: dict[int, Fila], detalle: list[Fila]
) -> None:
    origen = bovedas[fila["id_boveda"]]
    tipo = fila["tipo_movimiento"]
    if tipo != "ProvisionExterna":
        inventario = boveda._inventario_valido(conn, origen)
        if origen["saldo_actual"] < fila["monto"] or any(
            inventario.get(d["id_denominacion"], {}).get("cantidad_actual", 0)
            < d["cantidad"]
            for d in detalle
        ):
            raise problema(
                422,
                "SALDO_INSUFICIENTE",
                "No hay efectivo suficiente en las denominaciones solicitadas.",
            )
    destino = (
        origen
        if tipo == "ProvisionExterna"
        else bovedas.get(fila["id_boveda_contraparte"])
    )
    if destino:
        inventario_destino = boveda._inventario_valido(conn, destino)
        if destino["saldo_actual"] + fila["monto"] > destino["limite_maximo"]:
            raise problema(
                409,
                "LIMITE_BOVEDA_EXCEDIDO",
                "La recepción prevista excede el límite de la bóveda.",
            )
        if any(
            inventario_destino.get(d["id_denominacion"], {}).get("cantidad_actual", 0)
            + d["cantidad"]
            > boveda.INT32_MAX
            for d in detalle
        ):
            raise problema(
                422,
                "CANTIDAD_FUERA_RANGO",
                "La recepción excedería el rango de inventario.",
            )


def _solicitud_actual(conn: Connection, solicitud: int) -> SolicitudMovimiento:
    return _modelos(conn, [_exigir(repo.obtener(conn, solicitud))])[0]


def aprobar(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_solicitud: int,
    ip: str,
) -> SolicitudMovimiento:
    with auditar(
        "APROBAR_SOLICITUD_BOVEDA",
        "Boveda.SolicitudMovimientoBoveda",
        usuario,
        ip,
        f"solicitud={id_solicitud}",
        str(id_solicitud),
    ) as registro:
        actor = exigir_id_interno(id_interno)
        with conn.begin():
            fila, bovedas = _bloquear(conn, id_solicitud)
            _agencia_operativa(usuario, fila["id_agencia"])
            _distinto(
                actor,
                fila["id_usuario_solicitante"],
                "APROBADOR_IGUAL_SOLICITANTE",
                "El aprobador debe ser distinto del solicitante.",
            )
            if (
                fila["estado"]
                in {"APROBADO", "DESPACHADO", "RECIBIDO", "DEVUELTO", "EJECUTADA"}
                and fila["id_usuario_resolucion"] == actor
            ):
                return _modelos(conn, [fila])[0]
            _estado(fila, "PENDIENTE")
            if fila["tipo_movimiento"] in {"AjusteFaltante", "AjusteSobrante"}:
                raise problema(
                    409,
                    "AJUSTE_REQUIERE_ARQUEO",
                    "Resuelva la solicitud y registre un arqueo.",
                )
            _vigencia(bovedas, fila)
            for fila_boveda in bovedas.values():
                boveda._exigir_boveda(fila_boveda, estado=True)
            _reservar_efectivo(conn, fila, bovedas, _confirmar_propuesta(conn, fila))
            cuenta, version = _validar_cuentas(conn, fila)
            repo.resolver(
                conn,
                id_solicitud,
                "APROBADO",
                actor,
                contabilidad.ahora_ecuador(),
                None,
                cuenta,
                version,
            )
            registro.confirmar(
                conn,
                cambios={"estado": "APROBADO", "montoReservado": str(fila["monto"])},
            )
            return _solicitud_actual(conn, id_solicitud)


def _asiento(
    conn: Connection,
    fila: Fila,
    agencia: str,
    tipo: str,
    naturaleza: str,
    monto: Decimal,
    actor: int,
    movimiento: int,
    contexto: tuple[Any, int],
    lado_transito: str | None = None,
) -> int:
    ahora, fecha = contexto
    usar_version = fila["usa_plantilla_versionada"] and tipo in {
        "Traslado",
        "ProvisionExterna",
    }
    if usar_version:
        version = _plantilla_versionada(conn, agencia, tipo, naturaleza, fecha)
        if version is None:
            raise problema(
                409,
                "PLANTILLA_BOVEDA_NO_CONFIGURADA",
                "Falta la plantilla versionada de la etapa.",
            )
        cuentas = _cuentas_versionadas(conn, version, monto)
    else:
        cuentas = _plantilla(conn, agencia, tipo, naturaleza)
    if lado_transito is not None:
        _misma_cuenta(fila["id_cuenta_transito"], cuentas[lado_transito])
    if tipo == "Traslado" and naturaleza == "E":
        retorno = _plantilla(conn, agencia, "RetornoRemesa", "I")
        _misma_cuenta(cuentas["debito"], retorno["credito"])
        _misma_boveda(cuentas["credito"], retorno["debito"])
    if tipo == "RetornoRemesa":
        partida = contable_repo.movimientos_asiento(conn, fila["id_asiento_despacho"])
        salidas = [
            l["id_cuenta_contable"]
            for l in partida
            if l["tipo_movimiento"] == "CREDITO"
        ]
        if len(salidas) != 1:
            raise problema(
                409,
                "CUENTA_RETORNO_INCONSISTENTE",
                "No se pudo identificar la cuenta del despacho de origen.",
            )
        _misma_boveda(salidas[0], cuentas["debito"])
    return contabilidad.contabilizar_boveda(
        conn,
        agencia=agencia,
        tipo=tipo,
        naturaleza=naturaleza,
        monto=monto,
        fecha_contable=fecha,
        actor=actor,
        movimiento=movimiento,
        ahora=ahora,
        usar_version=usar_version,
    )


def _mover(
    conn: Connection,
    fila: Fila,
    vault: Fila,
    tipo: str,
    ingreso: bool,
    detalle: list[Fila],
    actor: int,
    fecha: int,
    *,
    contraparte: int | None,
    relacionado: int | None = None,
) -> int:
    with repo.afectar_reserva(conn, fila["id_solicitud_movimiento"]):
        movimiento = boveda._aplicar(
            conn,
            vault,
            tipo,
            ingreso,
            {d["id_denominacion"]: d["cantidad"] for d in detalle},
            {d["id_denominacion"]: d["valor_unitario"] for d in detalle},
            fila["id_usuario_solicitante"],
            actor,
            fecha,
            fila["observaciones"],
            contraparte=contraparte,
            relacionado=relacionado,
            contabilizar=False,
        )
    repo.vincular(conn, fila["id_solicitud_movimiento"], [movimiento])
    if relacionado is not None:
        boveda_repo.relacionar_movimiento(conn, relacionado, movimiento)
    return movimiento


def _documentos_requeridos(datos: DespachoRequest) -> None:
    if datos.numero_guia is None or datos.precinto is None:
        raise problema(
            422,
            "GUIA_PRECINTO_REQUERIDOS",
            "Indique la guía y el precinto de la remesa.",
        )


def despachar(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    solicitud: int,
    datos: DespachoRequest,
    ip: str,
) -> SolicitudMovimiento:
    with auditar(
        "DESPACHAR_SOLICITUD_BOVEDA",
        "Boveda.SolicitudMovimientoBoveda",
        usuario,
        ip,
        f"solicitud={solicitud}",
        str(solicitud),
    ) as registro:
        actor = exigir_id_interno(id_interno)
        with conn.begin():
            fila, bovedas = _bloquear(conn, solicitud)
            _agencia_operativa(usuario, fila["id_agencia"])
            _estado(fila, "APROBADO")
            _distinto(
                actor,
                fila["id_usuario_solicitante"],
                "CONFIRMADOR_IGUAL_SOLICITANTE",
                "El despacho requiere un usuario distinto del solicitante.",
            )
            tipo = fila["tipo_movimiento"]
            if tipo == "ProvisionExterna":
                raise problema(
                    409,
                    "ETAPA_NO_APLICA",
                    "La provisión se confirma mediante recepción.",
                )
            if tipo == "EnvioExcedente":
                _documentos_requeridos(datos)
            _vigencia(bovedas, fila)
            for vault in bovedas.values():
                boveda._exigir_boveda(vault, estado=True)
            detalle = _confirmar_propuesta(conn, fila)
            contable_repo.bloquear_contabilizacion(conn)
            ahora = contabilidad.ahora_ecuador()
            fecha = contabilidad.resolver_id_fecha_contable(conn, ahora)
            movimiento = _mover(
                conn,
                fila,
                bovedas[fila["id_boveda"]],
                tipo,
                False,
                detalle,
                actor,
                fecha,
                contraparte=fila["id_boveda_contraparte"],
            )
            asiento = _asiento(
                conn,
                fila,
                fila["id_agencia"],
                "DespachoExcedente" if tipo == "EnvioExcedente" else tipo,
                "E",
                fila["monto"],
                actor,
                movimiento,
                (ahora, fecha),
                "debito",
            )
            boveda_repo.vincular_asiento(conn, movimiento, asiento)
            repo.despachar(
                conn,
                {
                    "solicitud": solicitud,
                    "actor": actor,
                    "ahora": ahora,
                    "guia": datos.numero_guia,
                    "precinto": datos.precinto,
                    "asiento": asiento,
                },
            )
            registro.confirmar(
                conn,
                cambios={"estado": "DESPACHADO", "montoEnTransito": str(fila["monto"])},
            )
            return _solicitud_actual(conn, solicitud)


def _preparar_recepcion(
    fila: Fila, usuario: Usuario, actor: int, devolver: bool
) -> bool:
    tipo = fila["tipo_movimiento"]
    provision = tipo == "ProvisionExterna"
    if tipo == "EnvioExcedente" or (devolver and tipo != "Traslado"):
        raise problema(
            409,
            "ETAPA_NO_APLICA",
            "La confirmación solicitada no corresponde a esta operación.",
        )
    _agencia_operativa(
        usuario,
        fila["id_agencia"] if provision or devolver else fila["id_agencia_destino"],
    )
    _estado(fila, "APROBADO" if provision else "DESPACHADO")
    _distinto(
        actor,
        fila["id_usuario_solicitante"],
        "CONFIRMADOR_IGUAL_SOLICITANTE",
        "La recepción requiere un usuario distinto del solicitante.",
    )
    if not devolver:
        previo = (
            fila["id_usuario_resolucion"] if provision else fila["id_usuario_despacho"]
        )
        _distinto(
            actor,
            previo,
            "DOBLE_CUSTODIA_VIOLADA",
            "La recepción requiere un custodio distinto del que autorizó la provisión o despachó la remesa.",
        )
    return provision


def _asiento_diferencia(
    conn: Connection,
    fila: Fila,
    agencia: str,
    diferencia: Decimal,
    actor: int,
    salida: int,
    contexto: tuple[Any, int],
) -> int | None:
    if diferencia < 0:
        return _asiento(
            conn,
            fila,
            agencia,
            "FaltanteTransito",
            "E",
            -diferencia,
            actor,
            salida,
            contexto,
            "credito",
        )
    if diferencia > 0:
        return _asiento(
            conn,
            fila,
            agencia,
            "SobranteTransito",
            "I",
            diferencia,
            actor,
            salida,
            contexto,
            "debito",
        )
    return None


def recibir(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    solicitud: int,
    datos: RecepcionRequest | DevolucionRequest,
    ip: str,
    *,
    devolver: bool = False,
) -> SolicitudMovimiento:
    with auditar(
        "DEVOLVER_REMESA_BOVEDA" if devolver else "RECIBIR_SOLICITUD_BOVEDA",
        "Boveda.SolicitudMovimientoBoveda",
        usuario,
        ip,
        f"solicitud={solicitud}",
        str(solicitud),
    ) as registro:
        actor = exigir_id_interno(id_interno)
        with conn.begin():
            fila, bovedas = _bloquear(conn, solicitud)
            provision = _preparar_recepcion(fila, usuario, actor, devolver)
            _vigencia(bovedas, fila)
            id_vault = (
                fila["id_boveda"]
                if provision or devolver
                else fila["id_boveda_contraparte"]
            )
            vault = boveda._exigir_boveda(bovedas[id_vault], estado=True)
            detalle = _detalle(conn, datos)
            monto = _total(detalle)
            diferencia = monto - fila["monto"]
            esperado = repo.detalles(conn, [solicitud])[solicitud]
            cambia_conteo = {
                d["id_denominacion"]: (d["cantidad"], d["valor_unitario"])
                for d in detalle
            } != {
                d["id_denominacion"]: (d["cantidad"], d["valor_unitario"])
                for d in esperado
            }
            if provision:
                _documentos_requeridos(datos)
                if diferencia:
                    raise problema(
                        409,
                        "PROVISION_NO_COINCIDE",
                        "El importe contado debe coincidir con la provisión autorizada.",
                    )
            elif (datos.numero_guia or datos.precinto) and (
                datos.numero_guia != fila["numero_guia"]
                or datos.precinto != fila["precinto"]
            ):
                raise problema(
                    409,
                    "DOCUMENTOS_REMESA_NO_COINCIDEN",
                    "La guía y el precinto no coinciden con el despacho.",
                )
            if (devolver or cambia_conteo) and not datos.acta_novedad:
                raise problema(
                    422,
                    "ACTA_NOVEDAD_REQUERIDA",
                    "Indique el acta que respalda la diferencia o devolución.",
                )
            salida = (
                None if provision else repo.movimientos(conn, [solicitud])[solicitud][0]
            )
            tipo = "RetornoRemesa" if devolver else fila["tipo_movimiento"]
            contable_repo.bloquear_contabilizacion(conn)
            ahora = contabilidad.ahora_ecuador()
            fecha = contabilidad.resolver_id_fecha_contable(conn, ahora)
            asiento = None
            if monto > 0:
                contraparte = (
                    fila["id_boveda_contraparte"] if devolver else fila["id_boveda"]
                )
                movimiento = _mover(
                    conn,
                    fila,
                    vault,
                    tipo,
                    True,
                    detalle,
                    actor,
                    fecha,
                    contraparte=None if provision else contraparte,
                    relacionado=salida,
                )
                asiento = _asiento(
                    conn,
                    fila,
                    vault["id_agencia"],
                    tipo,
                    "I",
                    monto,
                    actor,
                    movimiento,
                    (ahora, fecha),
                    None if provision else "credito",
                )
                boveda_repo.vincular_asiento(conn, movimiento, asiento)
            novedad = (
                None
                if salida is None
                else _asiento_diferencia(
                    conn,
                    fila,
                    vault["id_agencia"],
                    diferencia,
                    actor,
                    salida,
                    (ahora, fecha),
                )
            )
            repo.guardar_conteo(conn, solicitud, detalle)
            estado = "DEVUELTO" if devolver else "RECIBIDO"
            repo.confirmar(
                conn,
                {
                    "solicitud": solicitud,
                    "estado": estado,
                    "actor": actor,
                    "ahora": ahora,
                    "monto": monto,
                    "acta": datos.acta_novedad,
                    "comprobante": None,
                    "guia": datos.numero_guia,
                    "precinto": datos.precinto,
                    "asiento": asiento,
                    "novedad": novedad,
                },
            )
            repo.liberar_cupo(conn, solicitud)
            registro.confirmar(
                conn,
                cambios={
                    "estado": estado,
                    "montoConfirmado": str(monto),
                    "diferencia": str(diferencia),
                },
            )
            return _solicitud_actual(conn, solicitud)


def cerrar_excedente(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    solicitud: int,
    datos: CierreRequest,
    ip: str,
) -> SolicitudMovimiento:
    with auditar(
        "CERRAR_EXCEDENTE_BOVEDA",
        "Boveda.SolicitudMovimientoBoveda",
        usuario,
        ip,
        f"solicitud={solicitud}",
        str(solicitud),
    ) as registro:
        actor = exigir_id_interno(id_interno)
        with conn.begin():
            fila, _ = _bloquear(conn, solicitud)
            _agencia_operativa(usuario, fila["id_agencia"])
            _estado(fila, "DESPACHADO")
            if fila["tipo_movimiento"] != "EnvioExcedente":
                raise problema(
                    409,
                    "ETAPA_NO_APLICA",
                    "Solo el excedente se cierra con comprobante bancario.",
                )
            salida = repo.movimientos(conn, [solicitud])[solicitud][0]
            contable_repo.bloquear_contabilizacion(conn)
            ahora = contabilidad.ahora_ecuador()
            fecha = contabilidad.resolver_id_fecha_contable(conn, ahora)
            asiento = _asiento(
                conn,
                fila,
                fila["id_agencia"],
                "CierreExcedente",
                "I",
                fila["monto"],
                actor,
                salida,
                (ahora, fecha),
                "credito",
            )
            repo.confirmar(
                conn,
                {
                    "solicitud": solicitud,
                    "estado": "RECIBIDO",
                    "actor": actor,
                    "ahora": ahora,
                    "monto": fila["monto"],
                    "acta": None,
                    "comprobante": datos.comprobante_banco,
                    "guia": None,
                    "precinto": None,
                    "asiento": asiento,
                    "novedad": None,
                },
            )
            repo.liberar_cupo(conn, solicitud)
            registro.confirmar(
                conn,
                cambios={"estado": "RECIBIDO", "montoConfirmado": str(fila["monto"])},
            )
            return _solicitud_actual(conn, solicitud)


def resolver_sin_ejecucion(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_solicitud: int,
    estado: str,
    motivo: str,
    ip: str,
) -> SolicitudMovimiento:
    with auditar(
        "RESOLVER_SOLICITUD_BOVEDA",
        "Boveda.SolicitudMovimientoBoveda",
        usuario,
        ip,
        f"estado={estado}",
        str(id_solicitud),
    ) as registro:
        actor = exigir_id_interno(id_interno)
        with conn.begin():
            fila, _ = _bloquear(conn, id_solicitud)
            _agencia_operativa(usuario, fila["id_agencia"])
            ahora = contabilidad.ahora_ecuador()
            if estado == "RECHAZADA" and fila["estado"] == "APROBADO":
                repo.anular(conn, id_solicitud, actor, ahora, motivo)
            else:
                _estado(fila, "PENDIENTE")
                if estado == "CANCELADA" and actor != fila["id_usuario_solicitante"]:
                    raise problema(
                        403,
                        "SOLO_SOLICITANTE_CANCELA",
                        "Solo el solicitante puede cancelar su solicitud.",
                    )
                if estado == "RECHAZADA":
                    _distinto(
                        actor,
                        fila["id_usuario_solicitante"],
                        "APROBADOR_IGUAL_SOLICITANTE",
                        "El revisor debe ser distinto del solicitante.",
                    )
                repo.resolver(conn, id_solicitud, estado, actor, ahora, motivo)
            repo.liberar_cupo(conn, id_solicitud)
            registro.confirmar(conn)
            return _solicitud_actual(conn, id_solicitud)
