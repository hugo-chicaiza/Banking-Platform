"""BOV-01..06. Inventario e historial siempre se confirman junto con el asiento."""

import hashlib
import json
from datetime import date
from decimal import Decimal

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.security.auth import Usuario
from app.core.security.operador import auditar, exigir_agencia, exigir_id_interno
from app.modules.auth.service import validar_participante_boveda
from app.modules.boveda import repository as repo
from app.modules.boveda.repository import Fila
from app.modules.boveda.schemas import (
    INT32_MAX,
    ArqueoBoveda,
    ArqueoBovedaRequest,
    Boveda,
    DenominacionBoveda,
    Desglose,
    DiferenciaDenominacion,
    MovimientoBoveda,
    MovimientoBovedaRequest,
    PageMovimientoBoveda,
)
from app.modules.contabilidad import service as contabilidad

_GLOBALES = frozenset({"ADMIN", "CONTADOR", "AUDITOR"})
_SUPERVISOR = frozenset({"SUPERVISOR"})
_TESTIGOS = frozenset({"SUPERVISOR", "AUDITOR"})
_MAX_DINERO = Decimal("9999999999999999.99")


def _agencia(usuario: Usuario, pedida: str | None) -> str | None:
    if set(usuario.roles) & _GLOBALES:
        return pedida
    propia = exigir_agencia(usuario)
    if pedida is not None and pedida != propia:
        raise problema(403, "SIN_ACCESO_AGENCIA", "No tiene acceso a esa agencia.")
    return propia


def _alcance(usuario: Usuario, agencia: str, escritura: bool = False) -> None:
    if not escritura and set(usuario.roles) & _GLOBALES:
        return
    if exigir_agencia(usuario) != agencia:
        raise problema(403, "SIN_ACCESO_AGENCIA", "No tiene acceso a esa agencia.")


def _exigir_boveda(
    fila: Fila | None, estado: bool = False, cuerpo: bool = False
) -> Fila:
    if fila is None:
        raise problema(
            422 if cuerpo else 404, "BOVEDA_NO_ENCONTRADA", "La bóveda no existe."
        )
    if estado and fila["estado"] != "A":
        raise problema(409, "BOVEDA_NO_ACTIVA", "La bóveda no está activa.")
    return fila


def _boveda(fila: Fila, inventario: list[Fila]) -> Boveda:
    piezas = [
        {
            "id_denominacion": d["id_denominacion"],
            "cantidad_actual": d["cantidad_actual"],
            "valor": d["valor"],
            "subtotal": d["valor"] * d["cantidad_actual"],
        }
        for d in inventario
    ]
    return Boveda(
        **fila,
        denominaciones=[DenominacionBoveda(**p) for p in piezas],
        total_desglose=sum((p["subtotal"] for p in piezas), Decimal(0)),
    )


def listar_bovedas(
    conn: Connection, usuario: Usuario, agencia: str | None, tipo: str | None
) -> list[Boveda]:
    agencia_autorizada = _agencia(usuario, agencia)
    with conn.begin():
        filas = repo.listar_bovedas(conn, agencia_autorizada, tipo)
        inventarios = repo.inventarios(conn, [f["id_boveda"] for f in filas])
        return [_boveda(f, inventarios[f["id_boveda"]]) for f in filas]


def obtener_boveda(conn: Connection, usuario: Usuario, id_boveda: int) -> Boveda:
    with conn.begin():
        fila = _exigir_boveda(repo.obtener_boveda(conn, id_boveda, bloquear=True))
        _alcance(usuario, fila["id_agencia"])
        return _boveda(fila, repo.inventarios(conn, [id_boveda])[id_boveda])


def _movimientos(conn: Connection, filas: list[Fila]) -> list[MovimientoBoveda]:
    detalles = repo.desgloses_movimientos(conn, [f["id_movimiento"] for f in filas])
    return [
        MovimientoBoveda(
            **f,
            desglose=[
                Desglose(id_denominacion=d["id_denominacion"], cantidad=d["cantidad"])
                for d in detalles[f["id_movimiento"]]
            ],
        )
        for f in filas
    ]


def listar_movimientos(
    conn: Connection,
    usuario: Usuario,
    id_boveda: int,
    tipo: str | None,
    desde: date | None,
    hasta: date | None,
    page: int,
    page_size: int,
    sort: str,
) -> PageMovimientoBoveda:
    partes = sort.split(",")
    if (
        len(partes) != 2
        or partes[0] not in repo.ORDEN_MOVIMIENTOS
        or partes[1] not in {"asc", "desc"}
    ):
        raise problema(400, "ORDEN_INVALIDO", "El ordenamiento no es válido.")
    if desde and hasta and desde > hasta:
        raise problema(
            400, "RANGO_FECHAS_INVALIDO", "Desde no puede ser posterior a hasta."
        )
    if hasta == date.max:
        raise problema(
            400,
            "FECHA_HASTA_INVALIDA",
            "La fecha hasta está fuera del rango permitido.",
        )
    fila = _exigir_boveda(repo.obtener_boveda(conn, id_boveda))
    _alcance(usuario, fila["id_agencia"])
    filas, total = repo.listar_movimientos(
        conn, id_boveda, tipo, desde, hasta, page, page_size, sort
    )
    return PageMovimientoBoveda(
        items=_movimientos(conn, filas), page=page, page_size=page_size, total=total
    )


def _inventario_valido(conn: Connection, fila: Fila) -> dict[int, Fila]:
    inventario = repo.inventarios(conn, [fila["id_boveda"]])[fila["id_boveda"]]
    total = sum((d["cantidad_actual"] * d["valor"] for d in inventario), Decimal(0))
    if total != fila["saldo_actual"]:
        raise problema(
            409,
            "BOVEDA_DESCUADRADA",
            "El saldo de bóveda no coincide con sus denominaciones.",
        )
    return {d["id_denominacion"]: d for d in inventario}


def _aplicar(
    conn: Connection,
    boveda: Fila,
    tipo: str,
    ingreso: bool,
    piezas: dict[int, int],
    valores: dict[int, Decimal],
    actor: int,
    autorizador: int,
    fecha_contable: int,
    observaciones: str | None,
    *,
    contraparte: int | None = None,
    relacionado: int | None = None,
    arqueo: int | None = None,
    clave: str | None = None,
    huella: str | None = None,
) -> int:
    inventario = _inventario_valido(conn, boveda)
    monto = sum((valores[i] * n for i, n in piezas.items()), Decimal(0))
    saldo = boveda["saldo_actual"] + (monto if ingreso else -monto)
    if monto <= 0 or monto > _MAX_DINERO or saldo > _MAX_DINERO:
        raise problema(422, "MONTO_FUERA_RANGO", "El monto excede el rango permitido.")
    if saldo < 0 or (
        not ingreso
        and any(
            inventario.get(i, {}).get("cantidad_actual", 0) < n
            for i, n in piezas.items()
        )
    ):
        raise problema(
            422,
            "SALDO_INSUFICIENTE",
            "No hay efectivo suficiente en las denominaciones solicitadas.",
        )
    if ingreso and any(
        inventario.get(i, {}).get("cantidad_actual", 0) + n > INT32_MAX
        for i, n in piezas.items()
    ):
        raise problema(
            422,
            "CANTIDAD_FUERA_RANGO",
            "El inventario excedería el rango de cantidades permitido.",
        )
    ahora = contabilidad.ahora_ecuador()
    movimiento = repo.crear_movimiento(
        conn,
        {
            "id_boveda": boveda["id_boveda"],
            "contraparte": contraparte,
            "tipo": tipo,
            "naturaleza": "I" if ingreso else "E",
            "monto": monto,
            "anterior": boveda["saldo_actual"],
            "posterior": saldo,
            "autorizador": autorizador,
            "actor": actor,
            "observaciones": observaciones,
            "ahora": ahora,
            "relacionado": relacionado,
            "fecha_contable": fecha_contable,
            "arqueo": arqueo,
            "clave": clave,
            "huella": huella,
        },
    )
    repo.actualizar_inventario(
        conn, boveda["id_boveda"], movimiento, piezas, ingreso, ahora, saldo
    )
    asiento = contabilidad.contabilizar_boveda(
        conn,
        agencia=boveda["id_agencia"],
        tipo=tipo,
        naturaleza="I" if ingreso else "E",
        monto=monto,
        fecha_contable=fecha_contable,
        actor=actor,
        movimiento=movimiento,
        ahora=ahora,
    )
    repo.vincular_asiento(conn, movimiento, asiento)
    boveda["saldo_actual"] = saldo
    return movimiento


def registrar_movimiento(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_boveda: int,
    datos: MovimientoBovedaRequest,
    ip: str,
    clave: str | None = None,
) -> list[MovimientoBoveda]:
    with auditar(
        "MOVIMIENTO_BOVEDA",
        "Boveda.MovimientoBoveda",
        usuario,
        ip,
        f"boveda={id_boveda} tipo={datos.tipo_movimiento}",
    ) as auditado:
        actor = exigir_id_interno(id_interno)
        if actor == datos.autorizado_por:
            raise problema(
                409,
                "DOBLE_CUSTODIA_VIOLADA",
                "Quien autoriza debe ser distinto de quien opera.",
            )
        traslado = datos.tipo_movimiento == "Traslado"
        destino = datos.id_boveda_contraparte
        if traslado and destino is None:
            raise problema(
                422,
                "TRASLADO_REQUIERE_CONTRAPARTE",
                "El traslado requiere una bóveda destino.",
            )
        if destino == id_boveda or (not traslado and destino is not None):
            raise problema(
                422,
                "CONTRAPARTE_INVALIDA",
                "La bóveda contraparte no es válida para esta operación.",
            )
        canonico = {
            **datos.model_dump(mode="json"),
            "desglose": sorted(
                [d.model_dump() for d in datos.desglose],
                key=lambda d: d["id_denominacion"],
            ),
            "boveda": id_boveda,
        }
        huella = hashlib.sha256(
            json.dumps(canonico, sort_keys=True).encode()
        ).hexdigest()
        with conn.begin():
            # Orden de ids estable: traslados opuestos no bloquean A->B y B->A a la vez.
            ids = sorted(
                {id_boveda, destino}
                if traslado and destino is not None
                else {id_boveda}
            )
            bovedas = {
                i: _exigir_boveda(
                    repo.obtener_boveda(conn, i, bloquear=True), cuerpo=i != id_boveda
                )
                for i in ids
            }
            origen = bovedas[id_boveda]
            _alcance(usuario, origen["id_agencia"], escritura=True)
            if clave:
                anterior = repo.repeticion(conn, actor, clave)
                if anterior is not None:
                    if (
                        repo.huella_movimiento(conn, anterior["id_movimiento"])
                        != huella
                    ):
                        raise problema(
                            409,
                            "IDEMPOTENCIA_CONFLICTO",
                            "La clave ya se utilizó con otros datos.",
                        )
                    repetidos = [anterior]
                    if anterior["tipo_movimiento"] == "Traslado":
                        repetidos.append(
                            repo.obtener_movimiento(
                                conn, anterior["id_movimiento_relacionado"]
                            )
                        )
                    auditado.id_registro = str(anterior["id_movimiento"])
                    return _movimientos(conn, repetidos)
            for boveda in bovedas.values():
                _exigir_boveda(boveda, estado=True)
            validar_participante_boveda(
                datos.autorizado_por, origen["id_agencia"], _SUPERVISOR
            )
            catalogo = repo.denominaciones(
                conn, [d.id_denominacion for d in datos.desglose]
            )
            if len(catalogo) != len(datos.desglose):
                raise problema(
                    422, "DENOMINACION_NO_ENCONTRADA", "Una denominación no existe."
                )
            if any(d["estado"] != "A" for d in catalogo.values()):
                raise problema(
                    409, "DENOMINACION_NO_ACTIVA", "Una denominación no está activa."
                )
            valores = {i: d["valor"] for i, d in catalogo.items()}
            piezas = {d.id_denominacion: d.cantidad for d in datos.desglose}
            fecha = contabilidad.resolver_id_fecha_contable(
                conn, contabilidad.ahora_ecuador()
            )
            id_origen = _aplicar(
                conn,
                origen,
                datos.tipo_movimiento,
                datos.tipo_movimiento in {"ProvisionExterna", "AjusteSobrante"},
                piezas,
                valores,
                actor,
                datos.autorizado_por,
                fecha,
                datos.observaciones,
                contraparte=destino,
                clave=clave,
                huella=huella if clave else None,
            )
            movimientos = [id_origen]
            if traslado and destino is not None:
                id_destino = _aplicar(
                    conn,
                    bovedas[destino],
                    "Traslado",
                    True,
                    piezas,
                    valores,
                    actor,
                    datos.autorizado_por,
                    fecha,
                    datos.observaciones,
                    contraparte=id_boveda,
                    relacionado=id_origen,
                )
                # También se vincula la salida para recuperar el par en un reintento.
                repo.relacionar_movimiento(conn, id_origen, id_destino)
                movimientos.append(id_destino)
            auditado.id_registro = str(id_origen)
            return _movimientos(
                conn, [repo.obtener_movimiento(conn, i) for i in movimientos]
            )


def _arqueo(conn: Connection, fila: Fila) -> ArqueoBoveda:
    detalle = repo.detalle_arqueo(conn, fila["id_arqueo_boveda"])
    datos = {k: v for k, v in fila.items() if k != "id_movimiento_corte"}
    return ArqueoBoveda(
        **datos,
        diferencia=fila["saldo_fisico"] - fila["saldo_teorico"],
        diferencia_por_denominacion=[
            DiferenciaDenominacion(
                id_denominacion=d["id_denominacion"],
                cantidad=d["cantidad"] - d["cantidad_esperada"],
            )
            for d in detalle
        ],
        ids_movimientos_ajuste=repo.ajustes_arqueo(conn, fila["id_arqueo_boveda"]),
    )


def registrar_arqueo(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_boveda: int,
    datos: ArqueoBovedaRequest,
    ip: str,
) -> ArqueoBoveda:
    with auditar(
        "ARQUEO_BOVEDA", "Boveda.ArqueoBoveda", usuario, ip, f"boveda={id_boveda}"
    ) as auditado:
        actor = exigir_id_interno(id_interno)
        if actor == datos.id_usuario_testigo:
            raise problema(
                409,
                "ARQUEADOR_IGUAL_TESTIGO",
                "El arqueador y el testigo deben ser distintos.",
            )
        with conn.begin():
            boveda = _exigir_boveda(
                repo.obtener_boveda(conn, id_boveda, bloquear=True), estado=True
            )
            _alcance(usuario, boveda["id_agencia"])
            validar_participante_boveda(
                datos.id_usuario_testigo, boveda["id_agencia"], _TESTIGOS
            )
            esperado = _inventario_valido(conn, boveda)
            contado = {d.id_denominacion: d.cantidad for d in datos.desglose}
            ids = sorted(set(esperado) | set(contado))
            if len(ids) > 100:
                raise problema(
                    422,
                    "DESGLOSE_EXCEDE_LIMITE",
                    "El arqueo excede el máximo de denominaciones.",
                )
            catalogo = repo.denominaciones(conn, ids)
            if len(catalogo) != len(ids):
                raise problema(
                    422, "DENOMINACION_NO_ENCONTRADA", "Una denominación no existe."
                )
            detalle = [
                {
                    "id_denominacion": i,
                    "cantidad": contado.get(i, 0),
                    "cantidad_esperada": esperado.get(i, {}).get("cantidad_actual", 0),
                    "valor": catalogo[i]["valor"],
                }
                for i in ids
            ]
            fisico = sum((d["cantidad"] * d["valor"] for d in detalle), Decimal(0))
            if fisico > _MAX_DINERO:
                raise problema(
                    422, "MONTO_FUERA_RANGO", "El conteo excede el rango permitido."
                )
            id_arqueo = repo.crear_arqueo(
                conn,
                {
                    "id_boveda": id_boveda,
                    "ahora": contabilidad.ahora_ecuador(),
                    "tipo": datos.tipo_arqueo,
                    "actor": actor,
                    "testigo": datos.id_usuario_testigo,
                    "observaciones": datos.observaciones,
                    "teorico": boveda["saldo_actual"],
                    "fisico": fisico,
                    "corte": repo.ultimo_movimiento(conn, id_boveda),
                },
                detalle,
            )
            fila = repo.obtener_arqueo(conn, id_arqueo)
            if fila is None:
                raise RuntimeError("No se encontró el arqueo recién registrado")
            auditado.id_registro = str(id_arqueo)
            return _arqueo(conn, fila)


def aprobar_arqueo(
    conn: Connection, usuario: Usuario, id_interno: int | None, id_arqueo: int, ip: str
) -> ArqueoBoveda:
    with auditar(
        "APROBAR_ARQUEO_BOVEDA",
        "Boveda.ArqueoBoveda",
        usuario,
        ip,
        f"arqueo={id_arqueo}",
        str(id_arqueo),
    ):
        actor = exigir_id_interno(id_interno)
        with conn.begin():
            inicial = repo.obtener_arqueo(conn, id_arqueo)
            if inicial is None:
                raise problema(404, "ARQUEO_NO_ENCONTRADO", "El arqueo no existe.")
            # Igual que Caja y los traslados, primero se bloquea la bóveda.
            boveda = _exigir_boveda(
                repo.obtener_boveda(conn, inicial["id_boveda"], bloquear=True),
                estado=True,
            )
            _alcance(usuario, boveda["id_agencia"], escritura=True)
            fila = repo.obtener_arqueo(conn, id_arqueo, bloquear=True)
            if fila is None:
                raise problema(404, "ARQUEO_NO_ENCONTRADO", "El arqueo no existe.")
            if fila["estado"] != "REGISTRADO":
                raise problema(
                    409,
                    "ARQUEO_NO_REGISTRADO",
                    "Solo se puede aprobar un arqueo registrado.",
                )
            if actor == fila["id_usuario_arqueador"]:
                raise problema(
                    409,
                    "APROBADOR_IGUAL_ARQUEADOR",
                    "El aprobador debe ser distinto del arqueador.",
                )
            detalle = repo.detalle_arqueo(conn, id_arqueo)
            if (
                fila["saldo_teorico"] is None
                or fila["id_movimiento_corte"] is None
                or any(
                    d["cantidad_esperada"] is None or d["valor"] is None
                    for d in detalle
                )
            ):
                raise problema(
                    409,
                    "ARQUEO_SIN_REFERENCIA",
                    "Este arqueo histórico no tiene una referencia verificable.",
                )
            inventario = _inventario_valido(conn, boveda)
            catalogo = repo.denominaciones(
                conn, [d["id_denominacion"] for d in detalle]
            )
            cantidades_esperadas = {
                d["id_denominacion"]: d["cantidad_esperada"]
                for d in detalle
                if d["cantidad_esperada"] != 0
            }
            cantidades_actuales = {
                i: d["cantidad_actual"]
                for i, d in inventario.items()
                if d["cantidad_actual"] != 0
            }
            if (
                repo.ultimo_movimiento(conn, boveda["id_boveda"])
                != fila["id_movimiento_corte"]
                or boveda["saldo_actual"] != fila["saldo_teorico"]
                or cantidades_actuales != cantidades_esperadas
                or any(
                    inventario.get(d["id_denominacion"], {}).get("cantidad_actual", 0)
                    != d["cantidad_esperada"]
                    or catalogo.get(d["id_denominacion"], {}).get("valor") != d["valor"]
                    for d in detalle
                )
            ):
                raise problema(
                    409,
                    "ARQUEO_DESACTUALIZADO",
                    "Hubo cambios después del conteo; registre un nuevo arqueo antes de ajustar.",
                )
            valores = {d["id_denominacion"]: d["valor"] for d in detalle}
            ajustes: list[int] = []
            fecha_contable: int | None = None
            for ingreso, tipo in ((False, "AjusteFaltante"), (True, "AjusteSobrante")):
                piezas = {
                    d["id_denominacion"]: abs(d["cantidad"] - d["cantidad_esperada"])
                    for d in detalle
                    if (
                        d["cantidad"] > d["cantidad_esperada"]
                        if ingreso
                        else d["cantidad"] < d["cantidad_esperada"]
                    )
                }
                if piezas:
                    if fecha_contable is None:
                        fecha_contable = contabilidad.resolver_id_fecha_contable(
                            conn, contabilidad.ahora_ecuador()
                        )
                    ajustes.append(
                        _aplicar(
                            conn,
                            boveda,
                            tipo,
                            ingreso,
                            piezas,
                            valores,
                            fila["id_usuario_arqueador"],
                            actor,
                            fecha_contable,
                            f"Regularización del arqueo {id_arqueo}",
                            arqueo=id_arqueo,
                        )
                    )
            repo.aprobar_arqueo(
                conn,
                id_arqueo,
                actor,
                contabilidad.ahora_ecuador(),
                ajustes[0] if ajustes else None,
            )
            aprobada = repo.obtener_arqueo(conn, id_arqueo)
            if aprobada is None:
                raise RuntimeError("No se encontró el arqueo aprobado")
            return _arqueo(conn, aprobada)
