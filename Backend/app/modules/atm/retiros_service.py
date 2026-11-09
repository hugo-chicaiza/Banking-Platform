"""ATM-03 parcial. Preparacion de lectura, sin debitador ni dispensador."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import gcd
from typing import Any, NoReturn

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.database.session_scope import ERRORES_SQL, sesion_sql_acotada
from app.modules.atm import repository, saldo_repository, service, session
from app.modules.atm import retiros_repository as repo
from app.modules.atm.schemas import AtmRetiroRequest
from app.modules.atm.session import SesionATM
from app.modules.atm.terminal_auth import TerminalAutenticado, revalidar_terminal
from app.modules.cuentas.schemas import ID_MONEDA_USD
from app.modules.transacciones.dependencias import DependenciasOperacion
from app.modules.transacciones.repository import autorizar_operacion


def no_habilitada():
    return problema(
        501,
        "OPERACION_NO_HABILITADA",
        "La operación aún no está habilitada en este ambiente.",
    )


def _no_disponible():
    return problema(503, "RETIRO_NO_DISPONIBLE", "No se pudo comprobar la operación.")


def _sin_efectivo():
    return problema(422, "ATM_SIN_EFECTIVO", "No se puede armar el monto solicitado.")


def _dinero(valor: object) -> Decimal:
    try:
        n = Decimal(str(valor))
        if not n.is_finite() or n < 0 or n != n.quantize(Decimal("0.01")):
            raise ValueError
        return n
    except (ValueError, InvalidOperation):
        raise _no_disponible() from None


def exigir_cuenta(sesion: SesionATM, cuenta: int) -> None:
    if cuenta not in sesion.cuentas:
        raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no está disponible.")


def solicitar_retiro(
    sesion: SesionATM,
    terminal: TerminalAutenticado,
    entrada: AtmRetiroRequest,
    dependencias: DependenciasOperacion,
) -> NoReturn:
    revalidar_terminal(terminal)
    exigir_cuenta(sesion, entrada.id_cuenta)
    dependencias.verificar_habilitadas()
    # Configurar dependencias de otro modulo NO habilita el retiro ni la dispensa.
    raise no_habilitada()


@dataclass(frozen=True)
class BilletesPreparados:
    id_gaveta: int
    id_denominacion: int
    cantidad: int


@dataclass(frozen=True, repr=False)
class PreparacionRetiro:
    id_moneda: int
    comision_calculada: Decimal
    id_transaccion_candidata: int | None
    billetes: tuple[BilletesPreparados, ...]


def seleccionar_billetes(
    monto: Decimal, gavetas: list[dict[str, Any]]
) -> tuple[BilletesPreparados, ...]:
    """Combinacion exacta acotada, no greedy, sin elegir una politica de dispensa.

    Limite tecnico de 100000 estados: si se supera, 503, nunca falso sin efectivo.
    No se promete minimizar billetes o desgaste ni se reservan unidades.
    """
    objetivo = int(_dinero(monto) * 100)
    if objetivo <= 0:
        raise _sin_efectivo()
    opciones = []
    vistos = set()
    for g in sorted(gavetas, key=lambda g: g["IdGaveta"]):
        if (
            g["Estado"] != "A"
            or g["EstadoDenominacion"] != "A"
            or g["TipoPieza"] != "Billete"
        ):
            continue
        valor = int(_dinero(g["Valor"]) * 100)
        cantidad, capacidad = g["CantidadActual"], g["Capacidad"]
        if (
            valor <= 0
            or type(cantidad) is not int
            or type(capacidad) is not int
            or not 0 <= cantidad <= capacidad
            or g["IdGaveta"] in vistos
        ):
            raise _no_disponible()
        vistos.add(g["IdGaveta"])
        opciones.append((g, valor, cantidad))
    if not opciones:
        raise _sin_efectivo()
    minimo = min(v for _, v, _ in opciones)
    if objetivo % minimo:
        raise problema(
            400,
            "DATOS_INVALIDOS",
            "El monto no respeta la denominación mínima configurada.",
        )
    divisor = 0
    for _, valor, _ in opciones:
        divisor = gcd(divisor, valor)
    objetivo //= divisor
    # Descomposicion binaria de existencias: no itera una vez por cada billete.
    alcanzables: dict[int, tuple[tuple[int, int], ...]] = {0: ()}
    for i, (_, valor, cantidad) in enumerate(opciones):
        valor //= divisor
        restante, bloque = min(cantidad, objetivo // valor), 1
        while restante:
            n = min(bloque, restante)
            peso = n * valor
            for suma, camino in list(alcanzables.items()):
                total = suma + peso
                if total <= objetivo and total not in alcanzables:
                    alcanzables[total] = (*camino, (i, n))
                    if len(alcanzables) > 100000:
                        raise _no_disponible()
            restante -= n
            bloque *= 2
    camino = alcanzables.get(objetivo)
    if camino is None:
        raise _sin_efectivo()
    cantidades: dict[int, int] = {}
    for i, n in camino:
        cantidades[i] = cantidades.get(i, 0) + n
    return tuple(
        BilletesPreparados(
            opciones[i][0]["IdGaveta"], opciones[i][0]["IdDenominacion"], n
        )
        for i, n in sorted(cantidades.items())
    )


def validar_reutilizacion(anterior, sesion, entrada, canal) -> int | None:
    if anterior is None:
        return None
    if not (
        anterior["TipoOperacion"] == "Normal"
        and anterior["TipoTransaccion"] == "Retiro"
        and anterior["MTI"] == "0200"
        and anterior["IdCuenta"] == entrada.id_cuenta
        and anterior["IdTarjeta"] == sesion.id_tarjeta
        and anterior["IdATM"] == sesion.id_atm
        and anterior["IdCanal"] == canal
        and _dinero(anterior["Monto"]) == entrada.monto
    ):
        raise problema(
            409,
            "REGISTRO_UNICO_REUTILIZADO",
            "El registroUnico ya se usó en otra operación.",
        )
    # Solo candidato: faltan evidencia de dispensa y contrato del comprobante.
    return int(anterior["IdTransaccion"])


def prevalidar_retiro(
    conn: Connection,
    sesion: SesionATM,
    terminal: TerminalAutenticado,
    entrada: AtmRetiroRequest,
) -> PreparacionRetiro:
    exigir_cuenta(sesion, entrada.id_cuenta)
    revalidar_terminal(terminal)
    try:
        with sesion_sql_acotada(conn):
            tx = conn.begin()
            try:
                return _prevalidar(conn, sesion, terminal, entrada)
            finally:
                tx.rollback()
    except ERRORES_SQL:
        raise _no_disponible() from None


def _prevalidar(conn, sesion, terminal, entrada) -> PreparacionRetiro:
    anterior = repo.leer_registro(conn, entrada.registro_unico)
    saldo_repository.bloquear_contexto(conn, sesion.id_atm, sesion.id_tarjeta)
    atm = service.validar_terminal(conn, terminal.codigo_atm)
    if atm["id_atm"] != sesion.id_atm:
        raise problema(403, "TERMINAL_NO_AUTORIZADO", "El terminal no permite operar.")
    tarjeta = repository.obtener_tarjeta(conn, sesion.id_tarjeta)
    cuenta = saldo_repository.leer_cuenta(conn, entrada.id_cuenta)
    if tarjeta is None or cuenta is None or tarjeta["id_cuenta"] != entrada.id_cuenta:
        raise problema(404, "CUENTA_NO_ENCONTRADA", "La cuenta no está disponible.")
    ahora, vencimiento = cuenta["Ahora"], tarjeta.get("fecha_expiracion")
    if not isinstance(ahora, datetime):
        raise _no_disponible()
    if isinstance(vencimiento, datetime):
        vencimiento = vencimiento.date()
    if (
        tarjeta["estado_tarjeta"] != "Activa"
        or not tarjeta["pin_asignado"]
        or vencimiento is None
        or vencimiento < ahora.date()
    ):
        raise problema(403, "TARJETA_NO_ACTIVA", "La tarjeta no permite operar.")
    session.require_sesion_operativa(
        session.require_sesion_pin_actual(session.require_sesion_atm(sesion))
    )
    if cuenta["Estado"] != "Activa":
        raise problema(409, "CUENTA_NO_ACTIVA", "La cuenta no está activa.")
    candidato = validar_reutilizacion(anterior, sesion, entrada, atm["id_canal"])
    autorizacion = autorizar_operacion(
        conn,
        entrada.id_cuenta,
        atm["id_canal"],
        "Retiro",
        entrada.monto,
        fecha_hora=ahora,
    )
    codigo = autorizacion.get("CodigoRespuesta")
    if codigo == "51":
        raise problema(
            422, "FONDOS_INSUFICIENTES", "El disponible no cubre monto y comisión."
        )
    if codigo in {"05", "61", "65"}:
        # 05 tambien puede ser restriccion de producto; 61 es ambiguo. No adivinar.
        raise no_habilitada()
    if codigo != "00":
        raise _no_disponible()
    comision = _dinero(autorizacion.get("Comision"))
    if (
        _dinero(cuenta["Saldo"]) - _dinero(cuenta["SaldoRetenido"])
        < entrada.monto + comision
    ):
        raise problema(
            422, "FONDOS_INSUFICIENTES", "El disponible no cubre monto y comisión."
        )
    billetes = seleccionar_billetes(
        entrada.monto, repo.leer_gavetas(conn, sesion.id_atm)
    )
    return PreparacionRetiro(ID_MONEDA_USD, comision, candidato, billetes)
