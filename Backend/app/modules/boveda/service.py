"""BOV-01..06. Inventario e historial siempre se confirman junto con el asiento."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Never

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import problema
from app.core.security.auth import Usuario
from app.core.security.operador import (
    agencia_de_consulta,
    auditar,
    exigir_agencia,
    exigir_agencia_autorizada,
    exigir_id_interno,
)
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
    EstadoArqueo,
    MovimientoBoveda,
    NovedadCajero,
    PageArqueoBoveda,
    PageMovimientoBoveda,
    ResolucionNovedadRequest,
    ResumenArqueoBoveda,
    TipoArqueo,
)
from app.modules.contabilidad import repository as repo_contable
from app.modules.contabilidad import service as contabilidad

_GLOBALES = frozenset({"ADMIN", "CONTADOR", "AUDITOR"})
_CAJERO = frozenset({"CAJERO"})
_MAX_DINERO = Decimal("9999999999999999.99")


def _agencia(usuario: Usuario, pedida: str | None) -> str | None:
    return agencia_de_consulta(usuario, pedida)


def _alcance(usuario: Usuario, agencia: str, escritura: bool = False) -> None:
    # ADMIN conserva acceso total; la agencia de la operacion procede del recurso.
    if "ADMIN" in usuario.roles and not ({"CAJERO", "ASESOR"} & set(usuario.roles)):
        exigir_agencia_autorizada(usuario, agencia)
        return
    if escritura or ("ADMIN" not in usuario.roles and usuario.agencia() is None):
        exigir_agencia(usuario)
    exigir_agencia_autorizada(usuario, agencia)
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
    usar_version: bool | None = None,
    contabilizar: bool = True,
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
    contexto = (
        text("EXEC sys.sp_set_session_context @key=N'BovedaArqueo', @value=:id")
        if arqueo is not None
        else None
    )
    if contexto is not None:
        conn.execute(contexto, {"id": arqueo})
    try:
        repo.actualizar_inventario(
            conn, boveda["id_boveda"], movimiento, piezas, ingreso, ahora, saldo
        )
    finally:
        if contexto is not None:
            try:
                conn.execute(contexto, {"id": None})
            except SQLAlchemyError:
                conn.invalidate()
                raise
    if contabilizar:
        opciones_contables = (
            {} if usar_version is None else {"usar_version": usar_version}
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
            **opciones_contables,
        )
        repo.vincular_asiento(conn, movimiento, asiento)
    boveda["saldo_actual"] = saldo
    return movimiento


def registrar_movimiento() -> Never:
    """BOV04 legado. El movimiento requiere una solicitud y otra sesión."""
    raise problema(
        410,
        "SOLICITUD_AUTORIZACION_REQUERIDA",
        "Registre una solicitud de movimiento y solicite su aprobación independiente.",
    )


def listar_arqueos(
    conn: Connection,
    usuario: Usuario,
    id_boveda: int,
    desde: date | None,
    hasta: date | None,
    estado: EstadoArqueo | None,
    tipo: TipoArqueo | None,
    page: int,
    page_size: int,
) -> PageArqueoBoveda:
    if desde and hasta and desde > hasta:
        raise problema(
            400, "RANGO_FECHAS_INVALIDO", "Desde no puede ser posterior a hasta."
        )
    if hasta == date.max or any(d and d.year < 1753 for d in (desde, hasta)):
        raise problema(
            400, "FECHA_FUERA_RANGO", "La fecha está fuera del rango permitido."
        )
    with conn.begin():
        # Mismo orden que registro/aprobación: cabeceras y ajustes de una sola versión.
        boveda = _exigir_boveda(repo.obtener_boveda(conn, id_boveda, bloquear=True))
        _alcance(usuario, boveda["id_agencia"])
        filas, total = repo.listar_arqueos(
            conn, id_boveda, desde, hasta, estado, tipo, page, page_size
        )
        ids = [f["id_arqueo_boveda"] for f in filas]
        ajustes = repo.ajustes_arqueos(conn, ids)
        novedades = repo.novedades_arqueos(conn, ids, contabilidad.ahora_ecuador())
        items = []
        for fila in filas:
            teorico, fisico = fila["saldo_teorico"], fila["saldo_fisico"]
            vinculados = set(ajustes[fila["id_arqueo_boveda"]])
            if fila["id_movimiento_ajuste"] is not None:
                # El legado puede tener solo el vínculo desde la cabecera del arqueo.
                vinculados.add(fila["id_movimiento_ajuste"])
            datos = {
                k: v
                for k, v in fila.items()
                if k not in {"id_movimiento_corte", "numero_fila", "total"}
            }
            items.append(
                ResumenArqueoBoveda(
                    **datos,
                    diferencia=fisico - teorico
                    if fisico is not None and teorico is not None
                    else None,
                    ids_movimientos_ajuste=sorted(vinculados),
                    novedad=_novedad(novedades.get(fila["id_arqueo_boveda"])),
                )
            )
        return PageArqueoBoveda(
            items=items, page=page, page_size=page_size, total=total
        )


def _novedad(fila: Fila | None) -> NovedadCajero | None:
    return NovedadCajero(**fila) if fila is not None else None


def _arqueo(conn: Connection, fila: Fila) -> ArqueoBoveda:
    id_arqueo = fila["id_arqueo_boveda"]
    detalle = repo.detalle_arqueo(conn, id_arqueo)
    novedades = repo.novedades_arqueos(conn, [id_arqueo], contabilidad.ahora_ecuador())
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
        ids_movimientos_ajuste=repo.ajustes_arqueo(conn, id_arqueo),
        novedad=_novedad(novedades.get(id_arqueo)),
    )


def _agencia_arqueo(usuario: Usuario, boveda: Fila) -> str:
    agencia = exigir_agencia(usuario)
    if agencia != boveda["id_agencia"]:
        raise problema(403, "SIN_ACCESO_AGENCIA", "No tiene acceso a esa agencia.")
    return agencia


def _cuenta_neta(
    conn: Connection, asiento: int, lado: str, monto: Decimal, elemento: str = "1"
) -> int:
    lineas = [
        linea
        for linea in repo_contable.movimientos_asiento(conn, asiento)
        if linea["tipo_movimiento"] == lado
    ]
    if (
        len(lineas) != 1
        or lineas[0]["monto"] != monto
        or not lineas[0]["codigo_cuenta"].startswith(elemento)
    ):
        raise problema(
            409,
            "CUENTA_ARQUEO_INVALIDA",
            "La cuenta contable del arqueo no corresponde a la operación.",
        )
    return lineas[0]["id_cuenta_contable"]


def _ajustar_conteo(
    conn: Connection,
    boveda: Fila,
    id_arqueo: int,
    detalle: list[Fila],
    diferencia: Decimal,
    actor: int,
) -> tuple[list[int], int | None]:
    cambios = {
        d["id_denominacion"]: d["cantidad"] - d["cantidad_esperada"] for d in detalle
    }
    if not any(cambios.values()):
        return [], None

    valores = {d["id_denominacion"]: d["valor"] for d in detalle}
    ahora = contabilidad.ahora_ecuador()
    fecha = contabilidad.resolver_id_fecha_contable(conn, ahora)
    ajustes = []
    for ingreso, tipo in ((False, "AjusteFaltante"), (True, "AjusteSobrante")):
        piezas = {i: abs(n) for i, n in cambios.items() if n and (n > 0) == ingreso}
        if piezas:
            ajustes.append(
                _aplicar(
                    conn,
                    boveda,
                    tipo,
                    ingreso,
                    piezas,
                    valores,
                    actor,
                    actor,
                    fecha,
                    f"Conteo del arqueo {id_arqueo}",
                    arqueo=id_arqueo,
                    contabilizar=False,
                )
            )
    repo.vincular_ajuste_arqueo(conn, id_arqueo, ajustes[0])
    if not diferencia:
        return ajustes, None

    falta = diferencia < 0
    monto = abs(diferencia)
    asiento = contabilidad.contabilizar_boveda(
        conn,
        agencia=boveda["id_agencia"],
        tipo="AjusteFaltante" if falta else "AjusteSobrante",
        naturaleza="E" if falta else "I",
        monto=monto,
        fecha_contable=fecha,
        actor=actor,
        movimiento=ajustes[0] if falta else ajustes[-1],
        ahora=ahora,
    )
    _cuenta_neta(
        conn, asiento, "DEBITO" if falta else "CREDITO", monto, "1" if falta else "2"
    )
    for ajuste in ajustes:
        repo.vincular_asiento(conn, ajuste, asiento)
    return ajustes, asiento


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
        with conn.begin():
            boveda = _exigir_boveda(
                repo.obtener_boveda(conn, id_boveda, bloquear=True), estado=True
            )
            agencia = _agencia_arqueo(usuario, boveda)
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
            diferencia = fisico - boveda["saldo_actual"]
            responsable = datos.id_usuario_responsable
            estado = "CUADRADO"
            if diferencia < 0:
                estado = "FALTANTE"
                if responsable is None or responsable == actor:
                    raise problema(
                        422,
                        "CAJERO_RESPONSABLE_REQUERIDO",
                        "Indique el cajero responsable del faltante, distinto del arqueador.",
                    )
                validar_participante_boveda(responsable, agencia, _CAJERO)
            elif responsable is not None:
                raise problema(
                    422,
                    "CAJERO_RESPONSABLE_NO_APLICA",
                    "Solo un arqueo con faltante requiere un cajero responsable.",
                )
            elif diferencia > 0:
                estado = "SOBRANTE"
            ahora = contabilidad.ahora_ecuador()
            id_arqueo = repo.crear_arqueo(
                conn,
                {
                    "id_boveda": id_boveda,
                    "ahora": ahora,
                    "tipo": datos.tipo_arqueo,
                    "actor": actor,
                    "estado": estado,
                    "observaciones": datos.observaciones,
                    "teorico": boveda["saldo_actual"],
                    "fisico": fisico,
                    "corte": repo.ultimo_movimiento(conn, id_boveda),
                },
                detalle,
            )
            ajustes, asiento = _ajustar_conteo(
                conn, boveda, id_arqueo, detalle, diferencia, actor
            )
            if responsable is not None:
                repo.crear_novedad(
                    conn,
                    {
                        "arqueo": id_arqueo,
                        "responsable": responsable,
                        "monto": -diferencia,
                        "vence": ahora + timedelta(hours=48),
                        "asiento": asiento,
                    },
                )
            fila = repo.obtener_arqueo(conn, id_arqueo)
            if fila is None:
                raise RuntimeError("No se encontró el arqueo recién registrado")
            auditado.id_registro = str(id_arqueo)
            auditado.confirmar(
                conn,
                cambios={
                    "estado": estado,
                    "diferencia": str(diferencia),
                    "idUsuarioResponsable": responsable,
                    "idsMovimientos": ajustes,
                    "idAsientoContable": asiento,
                },
            )
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
    ) as registro:
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
            if ajustes:
                # Con diferencia: el evento apunta a los movimientos de ajuste
                registro.confirmar(
                    conn,
                    objetivo="Boveda.MovimientoBoveda",
                    id_objetivo=",".join(str(a) for a in ajustes),
                    cambios={"idArqueoBoveda": id_arqueo},
                )
            else:
                registro.confirmar(conn)
            return _arqueo(conn, aprobada)


def _resolucion_contable(
    conn: Connection,
    boveda: Fila,
    novedad: Fila,
    datos: ResolucionNovedadRequest,
    actor: int,
) -> tuple[int, int | None]:
    ahora = contabilidad.ahora_ecuador()
    fecha = contabilidad.resolver_id_fecha_contable(conn, ahora)
    monto = novedad["monto"]
    cuenta_por_cobrar = _cuenta_neta(
        conn, novedad["id_asiento_contable"], "DEBITO", monto
    )
    tipo = {
        "REPOSICION": "ReposicionFaltante",
        "JUSTIFICACION": "JustificaFaltante",
        "DESCUENTO_ROL": "DescuentoFaltante",
    }[datos.tipo_resolucion]
    movimiento = None
    if datos.tipo_resolucion == "REPOSICION":
        piezas = {d.id_denominacion: d.cantidad for d in datos.desglose}
        catalogo = repo.denominaciones(conn, list(piezas))
        if len(catalogo) != len(piezas) or any(
            d["estado"] != "A" for d in catalogo.values()
        ):
            raise problema(
                422,
                "DENOMINACION_NO_HABILITADA",
                "Una denominación no está habilitada.",
            )
        valores = {i: d["valor"] for i, d in catalogo.items()}
        if sum((n * valores[i] for i, n in piezas.items()), Decimal(0)) != monto:
            raise problema(
                422,
                "MONTO_REPOSICION_INCORRECTO",
                "El efectivo de reposición debe cubrir exactamente el faltante.",
            )
        movimiento = _aplicar(
            conn,
            boveda,
            tipo,
            True,
            piezas,
            valores,
            novedad["id_usuario_responsable"],
            actor,
            fecha,
            f"Reposición de la novedad {novedad['id_novedad']}",
            contabilizar=False,
        )
    asiento = contabilidad.contabilizar_boveda(
        conn,
        agencia=boveda["id_agencia"],
        tipo=tipo,
        naturaleza="I" if movimiento else "E",
        monto=monto,
        fecha_contable=fecha,
        actor=actor,
        movimiento=movimiento,
        ahora=ahora,
        novedad=novedad["id_novedad"] if movimiento is None else None,
    )
    if _cuenta_neta(conn, asiento, "CREDITO", monto) != cuenta_por_cobrar:
        raise problema(
            409,
            "CUENTA_POR_COBRAR_NO_COMPENSADA",
            "La resolución debe compensar la cuenta por cobrar del faltante.",
        )
    if datos.tipo_resolucion == "DESCUENTO_ROL":
        _cuenta_neta(conn, asiento, "DEBITO", monto, "2")
    if movimiento is not None:
        if _cuenta_neta(conn, asiento, "DEBITO", monto) != _cuenta_neta(
            conn, novedad["id_asiento_contable"], "CREDITO", monto
        ):
            raise problema(
                409,
                "CUENTA_ARQUEO_INVALIDA",
                "La reposición debe ingresar a la cuenta de bóveda.",
            )
        repo.vincular_asiento(conn, movimiento, asiento)
    return asiento, movimiento


def resolver_novedad(
    conn: Connection,
    usuario: Usuario,
    id_interno: int | None,
    id_arqueo: int,
    datos: ResolucionNovedadRequest,
    ip: str,
) -> ArqueoBoveda:
    with auditar(
        "RESOLVER_NOVEDAD_CAJERO",
        "Boveda.NovedadCajero",
        usuario,
        ip,
        f"arqueo={id_arqueo}",
    ) as registro:
        actor = exigir_id_interno(id_interno)
        with conn.begin():
            fila = repo.obtener_arqueo(conn, id_arqueo)
            if fila is None:
                raise problema(404, "ARQUEO_NO_ENCONTRADO", "El arqueo no existe.")
            # La misma fila de bóveda serializa el cierre, la reposición y sus reintentos.
            boveda = _exigir_boveda(
                repo.obtener_boveda(conn, fila["id_boveda"], bloquear=True)
            )
            _agencia_arqueo(usuario, boveda)
            ahora = contabilidad.ahora_ecuador()
            novedad = repo.novedades_arqueos(conn, [id_arqueo], ahora).get(id_arqueo)
            if novedad is None:
                raise problema(
                    404,
                    "NOVEDAD_NO_ENCONTRADA",
                    "El arqueo no tiene novedad de cajero.",
                )
            if actor == novedad["id_usuario_responsable"]:
                raise problema(
                    403,
                    "RESPONSABLE_NO_RESUELVE_NOVEDAD",
                    "El responsable no puede resolver su novedad.",
                )
            if novedad["estado"] == "RESUELTA":
                raise problema(
                    409, "NOVEDAD_YA_RESUELTA", "La novedad ya fue resuelta."
                )
            if datos.tipo_resolucion == "REPOSICION":
                _exigir_boveda(boveda, estado=True)
            asiento, movimiento = _resolucion_contable(
                conn, boveda, novedad, datos, actor
            )
            repo.resolver_novedad(
                conn,
                {
                    "id": novedad["id_novedad"],
                    "tipo": datos.tipo_resolucion,
                    "ahora": ahora,
                    "actor": actor,
                    "referencia": datos.referencia_resolucion,
                    "observaciones": datos.observaciones,
                    "asiento": asiento,
                    "movimiento": movimiento,
                },
            )
            registro.id_registro = str(novedad["id_novedad"])
            registro.confirmar(
                conn,
                cambios={
                    "idArqueoBoveda": id_arqueo,
                    "tipoResolucion": datos.tipo_resolucion,
                    "idAsientoContable": asiento,
                    "idMovimientoReposicion": movimiento,
                },
            )
            return _arqueo(conn, fila)
