"""Auditoría 2026-11-09 de Caja y Transacciones: una prueba por hallazgo corregido.

Sin BD: los repositorios se reemplazan con Contexto.fake. Cada prueba nombra el
hallazgo del INFORME_AUDITORIA_CAJA_TRX.md que protege.
"""

from collections.abc import Iterator
from dataclasses import replace
from decimal import Decimal
from typing import Any, Self
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError

from app.core.security.operador import auditar
from app.modules.caja import repository as caja_repo
from app.modules.caja.router import router as caja_router
from app.modules.caja.schemas import Desglose, Jornada
from app.modules.transacciones import repository as trx_repo
from app.modules.transacciones.router import router as trx_router
from tests.caja_contexto import (
    BASE,
    CUADRE,
    DOTACION,
    ID_CAJERO,
    ID_SUPERVISOR,
    JORNADA,
    TOTALES,
    Contexto,
    code,
    crear_contexto,
    cuadre,
    usuario,
)
from tests.caja_ventanilla import CUERPO_DEPOSITO, preparar_ventanilla
from tests.unit.test_trx03 import (
    MONTO,
    crear_fila_original,
    preparar_reverso,
    solicitar_reverso,
)

TRX = "/api/v1/transacciones"


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, caja_router)


@pytest.fixture
def trx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(
        monkeypatch,
        trx_router,
        trx_repo,
        roles=("SUPERVISOR",),
        id_interno=ID_SUPERVISOR,
    )


# --- H-01 · TRX sin require_auth ----------------------------------------------------


@pytest.mark.parametrize("ruta", [TRX, f"{TRX}/2001"])
def test_h01_trx_rechaza_usuario_no_registrado(trx: Contexto, ruta: str) -> None:
    """Un SUPERVISOR de WorkOS sin fila Activa en Organizacion.Usuarios no consulta."""
    trx.usuario = replace(usuario("SUPERVISOR"), id_interno=None)
    trx.fake("listar_transacciones", AssertionError("No debe consultar"))
    trx.fake("obtener_transaccion", AssertionError("No debe consultar"))

    r = trx.cliente.get(ruta)

    assert r.status_code == 403
    assert code(r) == "USUARIO_NO_REGISTRADO"


def test_h01_trx03_rechaza_usuario_no_registrado(trx: Contexto) -> None:
    preparar_reverso(trx)
    trx.usuario = replace(usuario("SUPERVISOR"), id_interno=None)

    r = solicitar_reverso(trx)

    assert r.status_code == 403
    assert code(r) == "USUARIO_NO_REGISTRADO"
    assert (
        "insertar_transaccion" not in trx.llamadas
        or not trx.llamadas["insertar_transaccion"]
    )


# --- H-02 · CAJ-17 autorizaba un conteo desactualizado -------------------------------


def _preparar_autorizacion(ctx: Contexto, totales_actuales: dict[str, Any]) -> None:
    ctx.como("SUPERVISOR", id_interno=ID_SUPERVISOR)
    contado = cuadre(
        SaldoFinalFisico=Decimal("150.00"),
        DiferenciaDinero=Decimal("0.00"),
        EstadoCuadre="CUADRADO",
    )
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("obtener_cuadre_de_jornada", contado)
    ctx.fake("calcular_totales", totales_actuales)
    ctx.fake("autorizar_cuadre", True)
    ctx.fake("obtener_cuadre", {**contado, "IdAutorizadoPor": ID_SUPERVISOR})


def test_h02_caj17_rechaza_conteo_desactualizado(ctx: Contexto) -> None:
    """Devolución después del conteo: autorizarlo dejaría la jornada sin cierre."""
    _preparar_autorizacion(
        ctx, {**TOTALES, "TotalDevolucionesBoveda": Decimal("150.00")}
    )

    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/cuadre/autorizacion",
        json={"autorizadoPor": ID_SUPERVISOR},
    )

    assert r.status_code == 409
    assert code(r) == "CUADRE_DESACTUALIZADO"
    assert not ctx.llamadas["autorizar_cuadre"]


def test_h02_caj17_autoriza_conteo_vigente(ctx: Contexto) -> None:
    _preparar_autorizacion(ctx, TOTALES)

    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/cuadre/autorizacion",
        json={"autorizadoPor": ID_SUPERVISOR},
    )

    assert r.status_code == 200, r.text
    assert ctx.llamadas["autorizar_cuadre"] == [(70, ID_SUPERVISOR, None)]


def test_h02_caj18_sigue_rechazando_cuadre_desactualizado(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake(
        "obtener_cuadre_de_jornada",
        cuadre(SaldoFinalFisico=Decimal("150.00"), DiferenciaDinero=Decimal(0)),
    )
    ctx.fake("calcular_totales", {**TOTALES, "TotalDepositos": Decimal("80.00")})
    ctx.fake("cerrar_jornada", AssertionError("No debe cerrar"))

    r = ctx.cliente.post(f"{BASE}/jornadas/55/cierre")

    assert r.status_code == 409
    assert code(r) == "CUADRE_DESACTUALIZADO"


# --- H-03 · CAJ-07 INICIAL distinta del DineroInicial --------------------------------

CUERPO_INICIAL = {
    "idBoveda": 2,
    "autorizadoPor": ID_SUPERVISOR,
    "tipoDotacion": "INICIAL",
    "desglose": [{"idDenominacion": 1, "cantidad": 3}],
}


def _preparar_dotacion(ctx: Contexto, valor: str) -> None:
    ctx.fake("obtener_jornada", JORNADA)  # DineroInicial 100.50
    ctx.fake("valores_denominaciones", {1: Decimal(valor)})
    ctx.fake("autorizador_vigente", True)
    ctx.fake("id_fecha_contable", 20261104)
    ctx.fake(
        "registrar_dotacion",
        {"IdDotacionCaja": 801, "IdMovimientoBoveda": 9001, "BovedaBajoMinimo": False},
    )
    ctx.fake("obtener_dotacion", DOTACION)


def test_h03_caj07_inicial_distinta_del_dinero_inicial_422(ctx: Contexto) -> None:
    _preparar_dotacion(ctx, "50.00")  # 3 x 50 = 150 != 100.50

    r = ctx.cliente.post(f"{BASE}/jornadas/55/dotaciones", json=CUERPO_INICIAL)

    assert r.status_code == 422
    assert code(r) == "DOTACION_INICIAL_NO_COINCIDE"
    assert not ctx.llamadas["registrar_dotacion"]


def test_h03_caj07_inicial_igual_al_dinero_inicial_201(ctx: Contexto) -> None:
    _preparar_dotacion(ctx, "33.50")  # 3 x 33.50 = 100.50

    r = ctx.cliente.post(f"{BASE}/jornadas/55/dotaciones", json=CUERPO_INICIAL)

    assert r.status_code == 201, r.text
    assert len(ctx.llamadas["registrar_dotacion"]) == 1


def test_h03_caj07_adicional_no_se_compara_con_dinero_inicial(ctx: Contexto) -> None:
    _preparar_dotacion(ctx, "50.00")

    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/dotaciones",
        json={**CUERPO_INICIAL, "tipoDotacion": "ADICIONAL"},
    )

    assert r.status_code == 201, r.text
    assert (
        "valores_denominaciones" not in ctx.llamadas
        or not ctx.llamadas["valores_denominaciones"]
    )


def test_h03_caj07_inicial_con_denominacion_inexistente_422(ctx: Contexto) -> None:
    _preparar_dotacion(ctx, "50.00")
    ctx.fake("valores_denominaciones", {})

    r = ctx.cliente.post(f"{BASE}/jornadas/55/dotaciones", json=CUERPO_INICIAL)

    assert r.status_code == 422
    assert code(r) == "DENOMINACION_NO_ENCONTRADA"
    assert not ctx.llamadas["registrar_dotacion"]


# --- H-04 · autorizadoPor sin validar (CAJ-07 y CAJ-15 con el cajero como actor) ----


def test_h04_caj07_cajero_con_autorizador_no_valido_422(ctx: Contexto) -> None:
    _preparar_dotacion(ctx, "33.50")
    ctx.fake("autorizador_vigente", False)

    r = ctx.cliente.post(f"{BASE}/jornadas/55/dotaciones", json=CUERPO_INICIAL)

    assert r.status_code == 422
    assert code(r) == "AUTORIZADOR_NO_VALIDO"
    assert not ctx.llamadas["registrar_dotacion"]


def test_h04_caj07_supervisor_no_consulta_autorizador(ctx: Contexto) -> None:
    _preparar_dotacion(ctx, "33.50")
    ctx.fake("autorizador_vigente", AssertionError("No aplica al supervisor"))
    ctx.como("SUPERVISOR", id_interno=ID_SUPERVISOR)

    r = ctx.cliente.post(f"{BASE}/jornadas/55/dotaciones", json=CUERPO_INICIAL)

    assert r.status_code == 201, r.text


def test_h04_caj15_cajero_con_autorizador_no_valido_422(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake(
        "obtener_cuadre_de_jornada",
        cuadre(SaldoFinalFisico=Decimal("150.00"), DiferenciaDinero=Decimal(0)),
    )
    ctx.fake("autorizador_vigente", False)
    ctx.fake("registrar_devolucion", AssertionError("No debe llamar al SP"))

    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/devoluciones",
        json={
            "idCuadreCaja": 70,
            "idBovedaDestino": 2,
            "autorizadoPor": ID_SUPERVISOR,
            "desglose": [{"idDenominacion": 1, "cantidad": 3}],
        },
    )

    assert r.status_code == 422
    assert code(r) == "AUTORIZADOR_NO_VALIDO"


class _MotorFalso:
    """get_engine("seguridad") con el valor que devolvería RolesWorkOS."""

    def __init__(self, roles: Any) -> None:
        self.roles = roles
        self.sql: list[str] = []

    def connect(self) -> Any:
        motor = self

        class _Conexion:
            def __enter__(self) -> Self:
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def execute(self, sentencia: Any, parametros: dict[str, Any]) -> Any:
                motor.sql.append(str(sentencia))
                assert parametros == {"id": ID_SUPERVISOR}
                if isinstance(motor.roles, BaseException):
                    raise motor.roles
                resultado = MagicMock()
                resultado.scalar.return_value = motor.roles
                return resultado

        return _Conexion()


@pytest.mark.parametrize(
    ("roles", "esperado"),
    [
        ("CAJERO,SUPERVISOR", True),
        ("SUPERVISOR", True),
        ("CAJERO", False),
        ("SUPERVISORA", False),
        (None, False),
        (OperationalError("SELECT", None, Exception("caida")), False),
    ],
)
def test_h04_autorizador_vigente_falla_cerrada(
    monkeypatch: pytest.MonkeyPatch, roles: Any, esperado: bool
) -> None:
    motores: dict[str, _MotorFalso] = {}

    def motor(nombre: str) -> _MotorFalso:
        motores[nombre] = _MotorFalso(roles)
        return motores[nombre]

    monkeypatch.setattr(caja_repo, "get_engine", motor)

    assert caja_repo.autorizador_vigente(ID_SUPERVISOR) is esperado
    # Organizacion.Usuarios vive en SeguridadDB, la misma base del vínculo de auth
    assert set(motores) == {"seguridad"}
    assert "Estado = 'Activo'" in motores["seguridad"].sql[0]


# --- H-05 · ventanilla sin validar titular ni producto (CAJ-09 y CAJ-11) -------------


@pytest.mark.parametrize("ruta", ["depositos", "retiros"])
@pytest.mark.parametrize(
    ("restricciones", "codigo"),
    [
        (
            {"EstadoCliente": "Bloqueado", "PermiteOperacionesPresenciales": True},
            "CLIENTE_NO_ACTIVO",
        ),
        (
            {"EstadoCliente": "Suspendido", "PermiteOperacionesPresenciales": True},
            "CLIENTE_NO_ACTIVO",
        ),
        (None, "CLIENTE_NO_ACTIVO"),
        (
            {"EstadoCliente": "Activo", "PermiteOperacionesPresenciales": False},
            "PRODUCTO_SIN_OPERACION_PRESENCIAL",
        ),
    ],
)
def test_h05_ventanilla_rechaza_titular_o_producto(
    ctx: Contexto, ruta: str, restricciones: dict[str, Any] | None, codigo: str
) -> None:
    preparar_ventanilla(ctx, "Deposito" if ruta == "depositos" else "Retiro")
    ctx.fake("restricciones_cuenta", restricciones, trx_repo)
    ctx.fake("autorizar_operacion", AssertionError("No debe autorizar"), trx_repo)

    r = ctx.cliente.post(f"{BASE}/jornadas/55/{ruta}", json=CUERPO_DEPOSITO)

    assert r.status_code == 409
    assert code(r) == codigo
    assert not ctx.llamadas["insertar_transaccion"]
    assert not ctx.llamadas["aplicar_movimiento_cuenta"]


def test_h05_deposito_con_titular_activo_sigue_igual(ctx: Contexto) -> None:
    preparar_ventanilla(ctx)

    r = ctx.cliente.post(f"{BASE}/jornadas/55/depositos", json=CUERPO_DEPOSITO)

    assert r.status_code == 201, r.text
    assert ctx.llamadas["restricciones_cuenta"] == [(501,)]


# --- H-06 · CAJ-16 reescribía el conteo sin rastro -----------------------------------


def test_h06_caj16_audita_conteo_anterior(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake(
        "obtener_cuadre_de_jornada",
        cuadre(SaldoFinalFisico=Decimal("149.00"), EstadoCuadre="FALTANTE"),
    )
    ctx.fake("calcular_totales", TOTALES)
    ctx.fake("registrar_conteo", True)
    ctx.fake("obtener_cuadre", CUADRE)

    r = ctx.cliente.put(
        f"{BASE}/jornadas/55/cuadre/conteo", json={"saldoFinalFisico": 150}
    )

    assert r.status_code == 200, r.text
    descripcion = ctx.eventos[-1].descripcion
    assert "conteoAnterior=149.00 conteo=150 diferencia=0.00" in descripcion


def test_h06_detalle_extra_tambien_en_el_fallo() -> None:
    eventos: list[Any] = []
    with pytest.MonkeyPatch.context() as mp:
        from app.core.security import audit

        mp.setattr(audit, "registrar", eventos.append)
        with (
            pytest.raises(RuntimeError),
            auditar("X", "T", usuario("CAJERO"), "127.0.0.1", "jornada=1") as reg,
        ):
            reg.detalle = "conteoAnterior=None conteo=1"
            raise RuntimeError
    assert eventos[-1].descripcion == (
        "usuario=user_01PRUEBA jornada=1 conteoAnterior=None conteo=1"
        " motivo=RuntimeError"
    )


# --- H-07 · GETDATE() (UTC en Azure SQL) en cuadre y cierre --------------------------


def _sql_de(funcion: Any, *args: Any) -> str:
    conn = MagicMock()
    conn.execute.return_value.rowcount = 1
    conn.execute.return_value.first.return_value = (70,)
    funcion(conn, *args)
    return str(conn.execute.call_args.args[0])


@pytest.mark.parametrize(
    ("funcion", "args"),
    [
        (caja_repo.insertar_cuadre, (55, ID_CAJERO, TOTALES, 20261104, None)),
        (caja_repo.cerrar_jornada, (55,)),
    ],
)
def test_h07_fechas_de_cuadre_y_cierre_en_hora_de_ecuador(
    funcion: Any, args: tuple[Any, ...]
) -> None:
    sql = _sql_de(funcion, *args)

    assert "GETDATE()" not in sql.replace("GETDATE() es UTC", "")
    assert "AT TIME ZONE 'SA Pacific Standard Time'" in sql


# --- H-08 · TRX-03 sin guardas de reverso ---------------------------------------------


@pytest.mark.parametrize(
    "cambios",
    [
        {"TipoTransaccion": "Transferencia_Enviada", "IdCuentaDestino": 502},
        {"TipoTransaccion": "Pago_Credito"},
        {"TipoTransaccion": "Desembolso_Credito"},
        {"TipoTransaccion": "Pago_Tarjeta"},
        {"IdTerminal": 12},
        {"IdTarjeta": 33},
        {"IdCuentaDestino": 502},
    ],
)
def test_h08_trx03_no_reversa_lo_que_no_sabe_deshacer(
    trx: Contexto, cambios: dict[str, Any]
) -> None:
    preparar_reverso(trx, crear_fila_original(**cambios))

    r = solicitar_reverso(trx)

    assert r.status_code == 409
    assert code(r) == "REVERSO_NO_SOPORTADO"
    assert (
        "insertar_transaccion" not in trx.llamadas
        or not trx.llamadas["insertar_transaccion"]
    )


def test_h08_trx03_no_permite_autorreverso(trx: Contexto) -> None:
    preparar_reverso(trx, crear_fila_original(CreadoPor=ID_SUPERVISOR))

    r = solicitar_reverso(trx)

    assert r.status_code == 409
    assert code(r) == "AUTORREVERSO_NO_PERMITIDO"


def _reverso_de_deposito(trx: Contexto, **cuenta: Any) -> None:
    preparar_reverso(
        trx, crear_fila_original(TipoTransaccion="Deposito", IdJornadaCaja=55)
    )
    trx.fake(
        "movimientos_de_transaccion",
        [
            {
                "IdMovimiento": 1,
                "IdCuenta": 501,
                "TipoMovimiento": "C",
                "RolCuenta": None,
                "Monto": MONTO,
            }
        ],
    )
    trx.fake(
        "movimiento_caja_de_transaccion",
        {
            "IdJornadaCaja": 55,
            "IdAgencia": "001",
            "Monto": MONTO,
            "Codigo": "DEP_I",
            "Naturaleza": "I",
        },
    )
    trx.fake(
        "obtener_cuenta",
        {
            "IdCuenta": 501,
            "IdAgencia": "001",
            "Saldo": Decimal("1000.00"),
            "SaldoRetenido": Decimal("0.00"),
            "Estado": "Activa",
            **cuenta,
        },
    )


def test_h08_reverso_de_deposito_sin_disponible_422(trx: Contexto) -> None:
    """Depósito 40, el cliente ya retiró: el reverso no deja la cuenta en negativo."""
    _reverso_de_deposito(trx, Saldo=Decimal("50.00"), SaldoRetenido=Decimal("20.00"))

    r = solicitar_reverso(trx)

    assert r.status_code == 422
    assert code(r) == "FONDOS_INSUFICIENTES"
    assert not trx.llamadas["insertar_transaccion"]
    assert not trx.llamadas["aplicar_movimiento_cuenta"]


def test_h08_reverso_de_deposito_con_disponible_exacto_201(trx: Contexto) -> None:
    _reverso_de_deposito(trx, Saldo=Decimal("40.00"))

    r = solicitar_reverso(trx, motivo="Cuenta equivocada")

    assert r.status_code == 201, r.text
    assert trx.llamadas["aplicar_movimiento_cuenta"][0][2] == "D"
    # Reversar un depósito saca efectivo: egreso de caja con el motivo
    assert trx.llamadas["id_tipo_movimiento_caja"] == [("DEP_E",)]
    assert (
        trx.llamadas["insertar_movimiento_caja"][0][5] == "Reverso: Cuenta equivocada"
    )


@pytest.mark.parametrize("estado", ["Bloqueada", "Cerrada", "Inactiva"])
def test_h08_reverso_hacia_cuenta_no_activa_409(trx: Contexto, estado: str) -> None:
    preparar_reverso(trx)
    trx.fake(
        "obtener_cuenta",
        {"Saldo": Decimal(0), "SaldoRetenido": Decimal(0), "Estado": estado},
    )

    r = solicitar_reverso(trx)

    assert r.status_code == 409
    assert code(r) == "CUENTA_NO_ACTIVA"
    assert not trx.llamadas["insertar_transaccion"]


def test_h08_reverso_de_deposito_sin_efectivo_en_caja_409(trx: Contexto) -> None:
    _reverso_de_deposito(trx)
    trx.fake(
        "calcular_totales",
        {**TOTALES, "TotalDevolucionesBoveda": Decimal("130.00")},  # esperado 20
        caja_repo,
    )

    r = solicitar_reverso(trx)

    assert r.status_code == 409
    assert code(r) == "EFECTIVO_INSUFICIENTE_EN_CAJA"
    assert not trx.llamadas["insertar_transaccion"]


def test_h08_ventanilla_sin_movimiento_de_caja_409(trx: Contexto) -> None:
    preparar_reverso(trx, crear_fila_original(IdJornadaCaja=55))
    trx.fake("movimiento_caja_de_transaccion", None)

    r = solicitar_reverso(trx)

    assert r.status_code == 409
    assert code(r) == "TRANSACCION_INCONSISTENTE"
    assert not trx.llamadas["insertar_transaccion"]


def test_h08_debitos_de_la_misma_cuenta_se_suman(trx: Contexto) -> None:
    _reverso_de_deposito(trx, Saldo=Decimal("70.00"))
    trx.fake(
        "movimientos_de_transaccion",
        [
            {
                "IdMovimiento": i,
                "IdCuenta": 501,
                "TipoMovimiento": "C",
                "RolCuenta": None,
                "Monto": MONTO,
            }
            for i in (1, 2)
        ],
    )

    r = solicitar_reverso(trx)

    assert r.status_code == 422  # 40 + 40 > 70
    assert code(r) == "FONDOS_INSUFICIENTES"


def test_h08_motivo_largo_se_recorta_al_tamano_de_la_columna(trx: Contexto) -> None:
    preparar_reverso(trx, crear_fila_original(IdJornadaCaja=55))

    r = solicitar_reverso(trx, motivo="x" * 500)

    assert r.status_code == 201, r.text
    assert len(trx.llamadas["insertar_movimiento_caja"][0][5]) == 300


# --- H-09 · contratos de entrada y salida ---------------------------------------------


def test_h09_desglose_rechaza_campos_desconocidos(ctx: Contexto) -> None:
    preparar_ventanilla(ctx)
    cuerpo = {
        **CUERPO_DEPOSITO,
        "desglose": [{"idDenominacion": 1, "cantidad": 3, "valor": 999}],
    }

    r = ctx.cliente.post(f"{BASE}/jornadas/55/depositos", json=cuerpo)

    assert r.status_code == 400
    assert not ctx.llamadas["insertar_transaccion"]


def test_h09_desglose_sigue_sirviendo_de_salida() -> None:
    assert Desglose(id_denominacion=1, cantidad=2).model_dump(by_alias=True) == {
        "idDenominacion": 1,
        "cantidad": 2,
    }


def test_h09_jornada_sale_con_desfase_de_ecuador() -> None:
    jornada = Jornada(
        id_jornada_caja=55,
        id_usuario=ID_CAJERO,
        id_caja_fisica=3,
        id_agencia="001",
        fecha_hora_apertura=JORNADA["FechaHoraApertura"],
        fecha_hora_cierre=JORNADA["FechaHoraApertura"],
        dinero_inicial=Decimal(1),
        estado="CERRADA",
    ).model_dump(mode="json", by_alias=True)

    assert jornada["fechaHoraApertura"] == "2026-11-04T08:30:00-05:00"
    assert jornada["fechaHoraCierre"] == "2026-11-04T08:30:00-05:00"


def test_h09_caj02_id_usuario_fuera_de_int32_400(ctx: Contexto) -> None:
    ctx.como("SUPERVISOR", id_interno=ID_SUPERVISOR)
    ctx.fake("listar_jornadas", AssertionError("No debe consultar"))

    r = ctx.cliente.get(f"{BASE}/jornadas", params={"idUsuario": 2_147_483_648})

    assert r.status_code == 400
