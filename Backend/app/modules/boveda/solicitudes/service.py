"""Solicitar y resolver sin confiar identidades enviadas por el cliente."""

import hashlib
import json
from decimal import Decimal

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.security.auth import Usuario
from app.core.security.operador import auditar, exigir_id_interno
from app.modules.boveda import repository as boveda_repo
from app.modules.boveda import service as boveda
from app.modules.boveda.schemas import MovimientoBoveda
from app.modules.boveda.solicitudes import repository as repo
from app.modules.boveda.solicitudes.repository import Fila
from app.modules.boveda.solicitudes.schemas import (
    DetalleSolicitud,
    PageSolicitudMovimiento,
    SolicitudMovimiento,
    SolicitudMovimientoRequest,
)
from app.modules.contabilidad import service as contabilidad

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
    movimientos = repo.movimientos(conn, ids)
    return [
        SolicitudMovimiento(
            **{k: v for k, v in f.items() if k != "huella_peticion"},
            desglose=[
                DetalleSolicitud(**d) for d in detalles[f["id_solicitud_movimiento"]]
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


def _pendiente(fila: Fila) -> None:
    if fila["estado"] != "PENDIENTE":
        raise problema(
            409, "SOLICITUD_MOVIMIENTO_RESUELTA", "La solicitud ya fue resuelta."
        )


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
            origen = bovedas[id_boveda]
            boveda._alcance(usuario, origen["id_agencia"], escritura=True)
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
            for fila_boveda in bovedas.values():
                boveda._exigir_boveda(fila_boveda, estado=True)
            catalogo = _catalogo(conn, [d.id_denominacion for d in datos.desglose])
            detalle = [
                {
                    "id_denominacion": d.id_denominacion,
                    "cantidad": d.cantidad,
                    "valor_unitario": catalogo[d.id_denominacion]["valor"],
                }
                for d in datos.desglose
            ]
            monto = sum(
                (d["cantidad"] * d["valor_unitario"] for d in detalle), Decimal(0)
            )
            if monto <= 0 or monto > _MAX_DINERO:
                raise problema(
                    422, "MONTO_FUERA_RANGO", "El monto excede el rango permitido."
                )
            solicitud_id = repo.crear(
                conn,
                {
                    "boveda": id_boveda,
                    "contraparte": datos.id_boveda_contraparte,
                    "agencia": origen["id_agencia"],
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
            registro.id_registro = str(solicitud_id)
            return _modelos(conn, [_exigir(repo.obtener(conn, solicitud_id))])[0]


def listar(
    conn: Connection,
    usuario: Usuario,
    agencia: str | None,
    estado: str | None,
    page: int,
    page_size: int,
) -> PageSolicitudMovimiento:
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
        fila = _exigir(repo.obtener(conn, id_solicitud, bloquear=True))
        boveda._alcance(usuario, fila["id_agencia"])
        return _modelos(conn, [fila])[0]


def _repetir_aprobacion(
    conn: Connection, fila: Fila, actor: int
) -> list[MovimientoBoveda]:
    if actor != fila["id_usuario_resolucion"]:
        raise problema(
            409, "SOLICITUD_MOVIMIENTO_RESUELTA", "La solicitud ya fue resuelta."
        )
    ids = repo.movimientos(conn, [fila["id_solicitud_movimiento"]])[
        fila["id_solicitud_movimiento"]
    ]
    return boveda._movimientos(
        conn, [boveda_repo.obtener_movimiento(conn, i) for i in ids]
    )


def aprobar(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_solicitud: int,
    ip: str,
) -> list[MovimientoBoveda]:
    with auditar(
        "APROBAR_SOLICITUD_BOVEDA",
        "Boveda.SolicitudMovimientoBoveda",
        usuario,
        ip,
        f"solicitud={id_solicitud}",
        str(id_solicitud),
    ):
        actor = exigir_id_interno(id_interno)
        with conn.begin():
            inicial = _exigir(repo.obtener(conn, id_solicitud))
            boveda._alcance(usuario, inicial["id_agencia"], escritura=True)
            if inicial["estado"] == "EJECUTADA":
                return _repetir_aprobacion(conn, inicial, actor)
            # Mismo orden de bloqueo que las otras operaciones financieras de bóveda.
            bovedas = _bovedas(
                conn, inicial["id_boveda"], inicial["id_boveda_contraparte"]
            )
            fila = _exigir(repo.obtener(conn, id_solicitud, bloquear=True))
            if actor == fila["id_usuario_solicitante"]:
                raise problema(
                    409,
                    "APROBADOR_IGUAL_SOLICITANTE",
                    "El aprobador debe ser distinto del solicitante.",
                )
            if fila["estado"] == "EJECUTADA":
                return _repetir_aprobacion(conn, fila, actor)
            _pendiente(fila)
            if bovedas[fila["id_boveda"]]["id_agencia"] != fila["id_agencia"]:
                raise problema(
                    409,
                    "SOLICITUD_MOVIMIENTO_DESACTUALIZADA",
                    "La bóveda cambió de agencia; registre una nueva solicitud.",
                )
            detalle = repo.detalles(conn, [id_solicitud])[id_solicitud]
            catalogo = _catalogo(conn, [d["id_denominacion"] for d in detalle])
            datos = SolicitudMovimientoRequest.model_validate(
                {
                    "tipo_movimiento": fila["tipo_movimiento"],
                    "id_boveda_contraparte": fila["id_boveda_contraparte"],
                    "observaciones": fila["observaciones"],
                    "desglose": [
                        {
                            "id_denominacion": d["id_denominacion"],
                            "cantidad": d["cantidad"],
                        }
                        for d in detalle
                    ],
                }
            )
            total = sum(
                (d["cantidad"] * d["valor_unitario"] for d in detalle), Decimal(0)
            )
            if (
                _huella(fila["id_boveda"], datos) != fila["huella_peticion"]
                or total != fila["monto"]
                or any(
                    catalogo[d["id_denominacion"]]["valor"] != d["valor_unitario"]
                    for d in detalle
                )
            ):
                raise problema(
                    409,
                    "SOLICITUD_MOVIMIENTO_DESACTUALIZADA",
                    "Los datos o valores cambiaron; registre una nueva solicitud.",
                )
            piezas = {d["id_denominacion"]: d["cantidad"] for d in detalle}
            valores = {d["id_denominacion"]: d["valor_unitario"] for d in detalle}
            movimientos = boveda.ejecutar_movimiento_autorizado(
                conn, bovedas, fila, actor, piezas, valores
            )
            repo.vincular(conn, id_solicitud, [m.id_movimiento for m in movimientos])
            for movimiento in movimientos:
                movimiento.id_solicitud_movimiento = id_solicitud
            repo.resolver(
                conn,
                id_solicitud,
                "EJECUTADA",
                actor,
                contabilidad.ahora_ecuador(),
                None,
            )
            return movimientos


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
    ):
        actor = exigir_id_interno(id_interno)
        with conn.begin():
            fila = _exigir(repo.obtener(conn, id_solicitud, bloquear=True))
            boveda._alcance(usuario, fila["id_agencia"], escritura=True)
            _pendiente(fila)
            if estado == "CANCELADA" and actor != fila["id_usuario_solicitante"]:
                raise problema(
                    403,
                    "SOLO_SOLICITANTE_CANCELA",
                    "Solo el solicitante puede cancelar su solicitud.",
                )
            if estado == "RECHAZADA" and actor == fila["id_usuario_solicitante"]:
                raise problema(
                    409,
                    "APROBADOR_IGUAL_SOLICITANTE",
                    "El revisor debe ser distinto del solicitante.",
                )
            repo.resolver(
                conn, id_solicitud, estado, actor, contabilidad.ahora_ecuador(), motivo
            )
            return _modelos(conn, [_exigir(repo.obtener(conn, id_solicitud))])[0]
