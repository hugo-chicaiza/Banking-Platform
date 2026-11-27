import logging
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, NoReturn

from fastapi import HTTPException
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.core.security.auth import Usuario
from app.core.security.operador import auditar
from app.modules.contabilidad import repository
from app.modules.contabilidad.schemas import (
    AsientoManual,
    CuentaContableCrear,
    CuentaContableEditar,
    CuentaContableEstado,
    MotivoAsientoManual,
)

log = logging.getLogger(__name__)

# Ecuador continental: UTC-5 todo el año (sin horario de verano). El servidor de la
# API puede correr en UTC, pero la hora de corte (19:00) es hora local de Ecuador.
ZONA_ECUADOR = timezone(timedelta(hours=-5))

_FECHA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# TODO(F-04): reemplazar por ProblemDetails cuando exista core/errors.py.


def _problema(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def ahora_ecuador() -> datetime:
    """Hora actual de Ecuador, sin zona (como la compara la función de la DB)."""
    return datetime.now(ZONA_ECUADOR).replace(tzinfo=None)


def resolver_id_fecha_contable(conn: Connection, fecha_hora: datetime) -> int:
    """IdFechaContable al que pertenece una operación hecha en `fecha_hora` (AC-02).

    Punto de entrada para que otros módulos (caja, ATM, créditos) registren cada
    operación en el día contable correcto sin reimplementar la regla.
    Una fecha sin zona ya representa hora local de Ecuador; si trae zona, se
    convierte antes de pasarla al datetime2 de SQL Server.

    Raises:
        HTTPException 500 CALENDARIO_SIN_FECHA si el calendario no cubre el período.
    """
    if fecha_hora.utcoffset() is not None:
        fecha_hora = fecha_hora.astimezone(ZONA_ECUADOR).replace(tzinfo=None)
    id_fecha = repository.id_fecha_contable(conn, fecha_hora)
    if id_fecha is None:
        # Alerta operativa: hay que cargar más fechas en Contabilidad.FechaContable.
        log.error(
            "ALERTA calendario contable sin fechas para %s (DB 51016)", fecha_hora
        )
        raise _problema(
            500,
            "CALENDARIO_SIN_FECHA",
            "El calendario contable no tiene fechas cargadas para este período",
        )
    return id_fecha


def obtener_fecha_contable(conn: Connection, fecha: str) -> dict[str, Any]:
    """CON-01: fila del calendario contable de un día calendario (YYYY-MM-DD).

    Raises:
        HTTPException 400 FECHA_INVALIDA
        HTTPException 404 FECHA_NO_ENCONTRADA
    """
    try:
        if not _FECHA_RE.match(fecha):
            raise ValueError(fecha)
        dia = date.fromisoformat(fecha)
    except ValueError:
        raise _problema(
            400, "FECHA_INVALIDA", "La fecha debe tener el formato YYYY-MM-DD"
        ) from None

    fila = repository.obtener_por_fecha(conn, dia)
    if fila is None:
        raise _problema(
            404, "FECHA_NO_ENCONTRADA", "El calendario contable no tiene esa fecha"
        )
    return fila


def obtener_fecha_contable_actual(conn: Connection) -> dict[str, Any]:
    """CON-02: fecha contable vigente ahora (según la hora de corte).

    Raises:
        HTTPException 500 CALENDARIO_SIN_FECHA
    """
    id_fecha = resolver_id_fecha_contable(conn, ahora_ecuador())
    fila = repository.obtener_por_id(conn, id_fecha)
    if fila is None:
        # La función devolvió un id que no existe: inconsistencia del calendario.
        log.error(
            "ALERTA IdFechaContable %s devuelto por la función no existe", id_fecha
        )
        raise _problema(
            500,
            "CALENDARIO_SIN_FECHA",
            "El calendario contable no tiene fechas cargadas para este período",
        )
    return fila


def listar_cuentas_contables(
    conn: Connection, q: str | None, imputable: bool | None
) -> list[dict[str, Any]]:
    """CON-03: plan de cuentas con filtro por texto (código o nombre) y por imputable.

    La jerarquía se expresa con idCuentaSuperior; el front arma el árbol. El estado
    de la DB (bit) se publica como "Activo"/"Inactivo".
    """
    return [
        {**fila, "estado": "Activo" if fila["estado"] else "Inactivo"}
        for fila in repository.listar_cuentas_contables(conn, q, imputable)
    ]


# #206 · Alta, edición, estado y baja de cuentas. Alta y estado tienen lógica; edición
# y baja siguen solo con contrato (501). Aún no hay flujo de aprobación (202).

# Las cuentas que se crean por API son auxiliares: código de exactamente 8 dígitos.
NIVEL_AUXILIAR = 8

_TABLA_CUENTAS = "Contabilidad.CuentasContables"
_DUPLICADO_RE = re.compile(r"\((2627|2601)\)")
# THROW de trg_CuentasContables_PadreNoImputable cuando el código no corresponde al
# padre. El 51100 (padre imputable) no tiene código propio en el contrato: lo
# traduce traducir_error_bd (422 DB_51100, mensaje genérico).
_CODIGO_PADRE_BD = 56010
_DB_NUMERO_RE = re.compile(r"\((\d+)\) \(SQL\w+\)")


def _no_habilitada() -> HTTPException:
    return problema(
        501,
        "OPERACION_NO_HABILITADA",
        "La operación aún no está habilitada en este ambiente.",
    )


def _subcuenta_de_ultimo_nivel(
    conn: Connection, padre: dict[str, Any], codigo: str
) -> bool:
    """E3-05: el CUC permite "adicionar dígitos a las subcuentas de los últimos niveles"
    cuando el catálogo no trae ese nivel. Una cuenta de 4 dígitos sin hijas (p. ej. 2105)
    admite una subcuenta de 6; las que ya tienen subcuentas del regulador, no."""
    return (
        len(padre["codigo_cuenta"]) == 4
        and len(codigo) == 6
        and not repository.tiene_hijas(conn, padre["id_cuenta_contable"])
    )


def _codigo_no_corresponde() -> HTTPException:
    return problema(
        422,
        "CODIGO_NO_CORRESPONDE_AL_PADRE",
        "El código no corresponde a la cuenta superior.",
    )


def _codigo_duplicado() -> HTTPException:
    return problema(409, "CODIGO_DUPLICADO", "Ya existe una cuenta con ese código.")


def _padre_con_movimientos() -> HTTPException:
    return problema(
        409,
        "CUENTA_SUPERIOR_CON_MOVIMIENTOS",
        "La cuenta superior tiene movimientos o saldo.",
    )


def _cuenta_respuesta(fila: dict[str, Any]) -> dict[str, Any]:
    """Fila de la BD -> CuentaContable de CON-03 (estado bit como Activo/Inactivo)."""
    respuesta = {k: v for k, v in fila.items() if k != "es_cuenta_valuacion"}
    respuesta["estado"] = "Activo" if fila["estado"] else "Inactivo"
    return respuesta


def _error_bd_cuenta(exc: DBAPIError) -> HTTPException:
    """Errores de la BD al escribir una cuenta -> códigos del contrato.

    Solo se lee exc.orig para sacar el número; str(exc) trae SQL y parámetros.
    """
    original = str(exc.orig)
    if _DUPLICADO_RE.search(original):
        return _codigo_duplicado()
    if "CK_CuentasContables_InactivaSinSaldo" in original:
        return _cuenta_con_saldo()
    numeros = {int(n) for n in _DB_NUMERO_RE.findall(original)}
    if _CODIGO_PADRE_BD in numeros:
        return _codigo_no_corresponde()
    return traducir_error_bd(exc)


def crear_cuenta_contable(
    conn: Connection, usuario: Usuario, ip: str, datos: CuentaContableCrear
) -> dict[str, Any]:
    """Alta de una cuenta auxiliar bajo `idCuentaSuperior`; 201 con la cuenta.

    Valida en este orden: el padre existe, el código empieza con el del padre, el
    código tiene NIVEL_AUXILIAR dígitos y el código no existe. Hereda del padre la
    naturaleza y si es cuenta de valuación; el elemento CUC y el tipo salen solos
    del código. Entra con Estado = 1 y Saldo = 0.

    Una cuenta con hijas no puede ser imputable (trigger de la BD, THROW 51100). Si
    el padre es imputable y no tiene movimientos ni saldo, en la misma transacción
    se pone EsImputable = 0 en el padre y luego se inserta la hija; la auditoría
    registra `padre_desmarcado=<id>`. Si el padre ya no es imputable, no se toca.

    Raises:
        HTTPException 404 CUENTA_SUPERIOR_NO_ENCONTRADA
        HTTPException 422 CODIGO_NO_CORRESPONDE_AL_PADRE
        HTTPException 409 CODIGO_DUPLICADO (también si otra petición gana la carrera)
        HTTPException 409 CUENTA_SUPERIOR_CON_MOVIMIENTOS (padre imputable con
            movimientos o saldo distinto de 0)
    """
    codigo = datos.codigo_cuenta
    with auditar(
        "CON_CUENTA_CREADA",
        _TABLA_CUENTAS,
        usuario,
        ip,
        f"padre={datos.id_cuenta_superior} codigo={codigo}",
    ) as auditado:
        try:
            with conn.begin():
                padre = repository.bloquear_cuenta(conn, datos.id_cuenta_superior)
                if padre is None:
                    raise problema(
                        404,
                        "CUENTA_SUPERIOR_NO_ENCONTRADA",
                        "La cuenta superior no existe.",
                    )
                if not codigo.startswith(padre["codigo_cuenta"]):
                    raise _codigo_no_corresponde()
                if len(codigo) != NIVEL_AUXILIAR and not _subcuenta_de_ultimo_nivel(
                    conn, padre, codigo
                ):
                    raise _codigo_no_corresponde()
                if repository.existe_codigo(conn, codigo):
                    raise _codigo_duplicado()
                desmarcar = bool(padre["es_imputable"])
                if desmarcar:
                    if padre["saldo"] != 0 or repository.tiene_movimientos(
                        conn, padre["id_cuenta_contable"]
                    ):
                        raise _padre_con_movimientos()
                    repository.desmarcar_imputable(conn, padre["id_cuenta_contable"])
                id_cuenta = repository.insertar_cuenta(
                    conn,
                    {
                        "codigo": codigo,
                        "nombre": datos.nombre_cuenta,
                        "naturaleza": padre["naturaleza"],
                        "id_superior": padre["id_cuenta_contable"],
                        "imputable": 1 if datos.es_imputable else 0,
                        "valuacion": 1 if padre["es_cuenta_valuacion"] else 0,
                    },
                )
                auditado.id_registro = str(id_cuenta)
                if desmarcar:
                    auditado.detalle = (
                        f"padre_desmarcado={padre['id_cuenta_contable']}"
                        " padre_es_imputable=1->0"
                    )
                fila = repository.obtener_cuenta(conn, id_cuenta)
        except DBAPIError as exc:
            raise _error_bd_cuenta(exc) from None
        if fila is None:  # recién insertada en la misma transacción: no debería pasar
            raise problema(500, "ERROR_INTERNO", "Error interno del servidor.")
        return _cuenta_respuesta(fila)


def editar_cuenta_contable(
    conn: Connection, id_cuenta: int, datos: CuentaContableEditar, actor: int
) -> dict[str, Any]:
    """Renombra un auxiliar conservando su identidad y trazabilidad."""
    with conn.begin():
        cuenta = (
            conn.execute(
                text("""
            SELECT CodigoCuenta, EsCatalogoRegulador
            FROM Contabilidad.CuentasContables WITH (UPDLOCK,HOLDLOCK)
            WHERE IdCuentaContable=:id
        """),
                {"id": id_cuenta},
            )
            .mappings()
            .one_or_none()
        )
        if cuenta is None:
            raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe.")
        if cuenta["EsCatalogoRegulador"] or len(cuenta["CodigoCuenta"]) not in (8, 10):
            raise problema(
                409,
                "CUENTA_DEL_REGULADOR",
                "Edite el catálogo mediante una importación.",
            )
        conn.execute(
            text("""
            UPDATE Contabilidad.CuentasContables
            SET NombreCuenta=:nombre, ModificadoPor=:actor, FechaModificacion=SYSDATETIME()
            WHERE IdCuentaContable=:id AND NombreCuenta COLLATE Latin1_General_100_BIN2<>:nombre
        """),
            {"id": id_cuenta, "actor": actor, "nombre": datos.nombre_cuenta},
        )
        recargadas = listar_cuentas_contables(conn, cuenta["CodigoCuenta"], None)
        return next(
            fila for fila in recargadas if fila["id_cuenta_contable"] == id_cuenta
        )


def _cuenta_con_saldo() -> HTTPException:
    return problema(
        409, "CUENTA_CON_SALDO", "No se puede desactivar una cuenta con saldo."
    )


def cambiar_estado_cuenta_contable(
    conn: Connection,
    usuario: Usuario,
    ip: str,
    id_cuenta: int,
    datos: CuentaContableEstado,
) -> dict[str, Any]:
    """Activa o desactiva la cuenta; 200 con la cuenta.

    Desactivar exige saldo 0 (la BD lo exige también con
    CK_CuentasContables_InactivaSinSaldo). Activar no tiene bloqueo. Si ya está en
    ese estado, responde la cuenta sin escribir.

    Raises:
        HTTPException 404 CUENTA_NO_ENCONTRADA
        HTTPException 409 CUENTA_CON_SALDO
    """
    activar = datos.estado == "Activo"
    with auditar(
        "CON_CUENTA_ESTADO",
        _TABLA_CUENTAS,
        usuario,
        ip,
        f"cuenta={id_cuenta} estado={datos.estado}",
        id_registro=str(id_cuenta),
    ) as auditado:
        try:
            with conn.begin():
                cuenta = repository.bloquear_cuenta(conn, id_cuenta)
                if cuenta is None:
                    raise problema(
                        404, "CUENTA_NO_ENCONTRADA", "La cuenta contable no existe."
                    )
                if bool(cuenta["estado"]) == activar:
                    auditado.detalle = "sin_cambio"
                    return _cuenta_respuesta(cuenta)
                if not activar and cuenta["saldo"] != 0:
                    raise _cuenta_con_saldo()
                repository.actualizar_estado_cuenta(conn, id_cuenta, activar)
                fila = repository.obtener_cuenta(conn, id_cuenta)
        except DBAPIError as exc:
            raise _error_bd_cuenta(exc) from None
        if fila is None:
            raise problema(500, "ERROR_INTERNO", "Error interno del servidor.")
        return _cuenta_respuesta(fila)


def eliminar_cuenta_contable(conn: Connection, id_cuenta: int) -> NoReturn:
    """Baja: 204, o 202 si queda pendiente de aprobación.

    Raises:
        HTTPException 501 OPERACION_NO_HABILITADA (contrato sin lógica)
    """
    raise _no_habilitada()


def _texto_filtro(valor: str | None) -> str | None:
    """Origen y estado son texto libre (pueden aparecer valores nuevos): se
    normalizan a mayúsculas sin espacios alrededor, como se guardan en la DB."""
    if valor is None:
        return None
    normalizado = valor.strip().upper()
    if not normalizado:
        raise problema(
            400, "PARAMETRO_INVALIDO", "Un filtro de la consulta está vacío."
        )
    return normalizado


def listar_asientos(
    conn: Connection,
    *,
    fecha: str | None,
    origen: str | None,
    id_agencia: str | None,
    estado: str | None,
    page: int,
    page_size: int,
    sort: str | None,
) -> dict[str, Any]:
    """CON-04: asientos paginados, con filtros opcionales y sort de lista blanca.

    Sin `sort`, el orden es fechaAsiento desc, idAsientoContable desc. En la lista
    `detalle` va vacío: el detalle completo está en CON-05.

    Raises:
        HTTPException 400 FECHA_INVALIDA, ORDEN_INVALIDO, PARAMETRO_INVALIDO
    """
    dia: date | None = None
    if fecha is not None:
        try:
            if not _FECHA_RE.match(fecha):
                raise ValueError(fecha)
            dia = date.fromisoformat(fecha)
        except ValueError:
            raise problema(
                400, "FECHA_INVALIDA", "La fecha debe tener el formato YYYY-MM-DD."
            ) from None

    campo, direccion = "fechaAsiento", "desc"
    if sort is not None:
        partes = sort.split(",")
        if (
            len(partes) != 2
            or partes[0] not in repository.ORDEN_ASIENTOS
            or partes[1] not in {"asc", "desc"}
        ):
            raise problema(400, "ORDEN_INVALIDO", "El ordenamiento no es válido.")
        campo, direccion = partes

    filtros = {
        "fecha": dia,
        "origen": _texto_filtro(origen),
        "id_agencia": id_agencia,
        "estado": _texto_filtro(estado),
    }
    filas, total = repository.listar_asientos(
        conn, filtros, page, page_size, campo, direccion
    )
    return {
        "items": [{**fila, "detalle": []} for fila in filas],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def obtener_asiento(conn: Connection, id_asiento: int) -> dict[str, Any]:
    """CON-05: un asiento con sus líneas, ordenadas por IdMovimientoContable.

    Raises:
        HTTPException 404 ASIENTO_NO_ENCONTRADO
    """
    asiento = repository.obtener_asiento(conn, id_asiento)
    if asiento is None:
        raise problema(404, "ASIENTO_NO_ENCONTRADO", "El asiento contable no existe.")
    return {**asiento, "detalle": repository.movimientos_asiento(conn, id_asiento)}


# ---------------------------------------------------------------------------
# E4-04 (#383) · Asientos manuales con aprobación y reverso: solo contrato
# ---------------------------------------------------------------------------
# Cada función lanza el 501 interno; el router lo cierra con funcion_pendiente
# (E0-09) y responde 404 FUNCION_NO_DISPONIBLE.
# Reglas que implementará la lógica (no se validan todavía):
# - Alta y edición guardan un BORRADOR, aunque esté incompleto o no cuadre.
# - Solo un BORRADOR se edita, se envía o se anula (409 ASIENTO_NO_EDITABLE).
# - El envío exige al menos dos líneas y débitos = créditos (422
#   ASIENTO_NO_CUADRA); cuentas activas, imputables y sin subcuentas (409
#   CUENTA_CONTABLE_NO_HABILITADA) que no sean solo automáticas (422
#   CUENTA_SOLO_AUTOMATICA); día y mes contables abiertos (409
#   PERIODO_CONTABLE_NO_ABIERTO). Queda PENDIENTE_APROBACION en E0-08 (202).
# - Solo se reversa un asiento MANUAL contabilizado; los de una operación se
#   reversan desde la operación de origen (409 ASIENTO_DE_OPERACION).
# - Quien envía no aprueba su propio asiento (403 en /aprobaciones).


def crear_asiento_manual(conn: Connection, datos: AsientoManual) -> NoReturn:
    """POST /asientos: 201 {idAsientoContable} con el asiento en BORRADOR.

    Raises:
        HTTPException 501 OPERACION_NO_HABILITADA (contrato sin lógica; el router
            responde 404 FUNCION_NO_DISPONIBLE)
    """
    raise _no_habilitada()


def editar_asiento_manual(
    conn: Connection, id_asiento: int, datos: AsientoManual
) -> NoReturn:
    """PUT /asientos/{idAsiento}: reemplaza el borrador completo; 200.

    Raises:
        HTTPException 501 OPERACION_NO_HABILITADA (contrato sin lógica; el router
            responde 404 FUNCION_NO_DISPONIBLE)
    """
    raise _no_habilitada()


def enviar_asiento_manual(conn: Connection, id_asiento: int) -> NoReturn:
    """POST /asientos/{idAsiento}/envio: valida el borrador y lo deja pendiente de
    aprobación; 202 con la solicitud.

    Raises:
        HTTPException 501 OPERACION_NO_HABILITADA (contrato sin lógica; el router
            responde 404 FUNCION_NO_DISPONIBLE)
    """
    raise _no_habilitada()


def anular_asiento_manual(
    conn: Connection, id_asiento: int, datos: MotivoAsientoManual
) -> NoReturn:
    """POST /asientos/{idAsiento}/anulacion: anula un borrador; 200.

    Raises:
        HTTPException 501 OPERACION_NO_HABILITADA (contrato sin lógica; el router
            responde 404 FUNCION_NO_DISPONIBLE)
    """
    raise _no_habilitada()


def reversar_asiento_manual(
    conn: Connection, id_asiento: int, datos: MotivoAsientoManual
) -> NoReturn:
    """POST /asientos/{idAsiento}/reverso (CON-06): pide el reverso de un asiento
    manual contabilizado; 202 con la solicitud.

    Raises:
        HTTPException 501 OPERACION_NO_HABILITADA (contrato sin lógica; el router
            responde 404 FUNCION_NO_DISPONIBLE)
    """
    raise _no_habilitada()


def contabilizar_boveda(
    conn: Connection,
    *,
    agencia: str,
    tipo: str,
    naturaleza: str,
    monto: Decimal,
    fecha_contable: int,
    actor: int,
    movimiento: int,
    ahora: datetime,
    usar_version: bool | None = None,
) -> int:
    """Asiento real de BOV-04/06 en la misma transacción que el efectivo.

    Las cuentas y el tipo de asiento se configuran en PlantillaBoveda por agencia,
    tipo y naturaleza. No se inventa la matriz G-06 ni se confirma efectivo sin ella.
    """
    if not conn.in_transaction():
        raise RuntimeError("La contabilización de bóveda requiere una transacción")
    repository.bloquear_contabilizacion(conn)
    from .asientos import OperacionContable, generar_asiento
    from .boveda_versionada import codigo_boveda

    periodo = repository.periodo_boveda(conn, fecha_contable)
    if periodo is None or periodo["estado"] != "ABIERTO":
        raise problema(
            409, "PERIODO_CONTABLE_NO_ABIERTO", "El período contable no está abierto."
        )
    codigo = codigo_boveda(agencia, tipo, naturaleza)
    if usar_version is True or (
        usar_version is None
        and tipo != "Traslado"
        and repository.obtener_plantilla(conn, codigo, periodo["fecha"]) is not None
    ):
        base = "DIFERENCIA" if tipo.startswith("Ajuste") else "PRINCIPAL"
        return generar_asiento(
            conn,
            OperacionContable(
                codigo_plantilla=codigo,
                clave_evento=f"BOVEDA:MOVIMIENTO:{movimiento}",
                id_agencia=agencia,
                id_fecha_contable=fecha_contable,
                id_usuario=actor,
                fecha_hora=ahora,
                importes={base: monto},
            ),
        )
    plantilla = repository.plantilla_boveda(conn, agencia, tipo, naturaleza)
    if plantilla is None or plantilla["estado_tipo"] != "A":
        raise problema(
            409,
            "PLANTILLA_BOVEDA_NO_CONFIGURADA",
            "Falta una plantilla contable activa para esta operación y agencia.",
        )
    for id_cuenta in sorted({plantilla["debito"], plantilla["credito"]}):
        cuenta = repository.cuenta_boveda(conn, id_cuenta)
        if cuenta is None or not cuenta["estado"] or not cuenta["imputable"]:
            raise problema(
                409,
                "CUENTA_CONTABLE_NO_HABILITADA",
                "La plantilla contiene una cuenta inactiva o no imputable.",
            )
    asiento = repository.crear_asiento_boveda(
        conn,
        {
            "fecha": periodo["fecha"],
            "ahora": ahora,
            "agencia": agencia,
            "tipo_asiento": plantilla["tipo_asiento"],
            "actor": actor,
            "fecha_contable": fecha_contable,
            "concepto": f"Bóveda: {tipo}; movimiento {movimiento}",
        },
    )
    for campo, lado in (("debito", "DEBITO"), ("credito", "CREDITO")):
        cuenta = plantilla[campo]
        repository.linea_boveda(
            conn,
            asiento,
            cuenta,
            agencia,
            monto,
            lado,
            ahora,
        )
    repository.contabilizar_asiento(conn, asiento)
    return asiento
