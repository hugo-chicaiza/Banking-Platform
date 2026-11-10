"""Pruebas unitarias del reverso de transacciones TRX-03."""

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import Mock

import pytest

from app.modules.caja import repository as caja_repo
from app.modules.transacciones import repository as repo
from app.modules.transacciones import service
from app.modules.transacciones.dependencias import (
    DatosAsiento,
    Numeracion,
    dependencias_operacion,
)
from app.modules.transacciones.router import router
from tests.caja_contexto import (
    ID_SUPERVISOR,
    TOTALES,
    Contexto,
    code,
    crear_contexto,
    usuario,
)

BASE = "/api/v1/transacciones"
ID_ORIGINAL = 2001
ID_REVERSO = 2002
MONTO = Decimal("40.00")
FECHA = 20261104


def crear_fila_original(**cambios: Any) -> dict[str, Any]:
    """Genera una transacción normal con valores controlados."""
    fila = {
        "IdTransaccion": ID_ORIGINAL,
        "NumeroComprobante": "COMP-001",
        "RegistroUnico": "ATM000000002",
        "MTI": "0200",
        "STAN": "000001",
        "RRN": "000000000001",
        "TipoOperacion": "Normal",
        "TipoTransaccion": "Retiro",
        "IdCuenta": 501,
        "IdCuentaDestino": None,
        "IdTarjeta": None,
        "IdCanal": 4,
        "IdTerminal": None,
        "IdAgencia": "001",
        "IdJornadaCaja": None,
        "IdTransaccionRelacionada": None,
        "Monto": MONTO,
        "CodigoRespuesta": "00",
        "Estado": "Completada",
        "IdFechaContable": FECHA,
        "FechaHoraSistema": datetime(2026, 11, 4, 10, 15),
        "CreadoPor": 7,
        "NumeroAutorizacion": None,
        "AgenciaOperacion": "001",
    }
    return {**fila, **cambios}


def crear_fila_reverso() -> dict[str, Any]:
    """Construye la respuesta esperada del reverso."""
    return crear_fila_original(
        IdTransaccion=ID_REVERSO,
        NumeroComprobante="COMP-REV-001",
        RegistroUnico="REV000000005",
        MTI="0400",
        TipoOperacion="Reverso",
        IdTransaccionRelacionada=ID_ORIGINAL,
        CreadoPor=ID_SUPERVISOR,
    )


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(
        monkeypatch,
        router,
        repo,
        roles=("SUPERVISOR",),
        id_interno=ID_SUPERVISOR,
    )


def crear_dependencias() -> Mock:
    """Simula los servicios externos utilizados por TRX-03."""
    deps = Mock()

    deps.verificar_habilitadas.return_value = None
    deps.id_canal_ventanilla = 4
    deps.codigo_pais_origen = "ECU"

    deps.codigo_tipo_movimiento_caja.side_effect = lambda tipo, naturaleza: (
        f"{tipo[:3].upper()}_{naturaleza}"
    )

    deps.numerar.return_value = Numeracion(
        "COMP-REV-001",
        "000005",
        "210000",
        "000005",
        "000000000005",
        None,
        "REV000000005",
    )

    deps.contabilizar.return_value = 778

    deps.registrar_comision.side_effect = AssertionError(
        "No debe registrar comisiones en el reverso"
    )

    return deps


def preparar_reverso(
    ctx: Contexto,
    original: dict[str, Any] | None = None,
) -> Mock:
    """Prepara las respuestas simuladas para ejecutar un reverso."""
    deps = crear_dependencias()

    ctx.app.dependency_overrides[dependencias_operacion] = lambda: deps

    transacciones = iter(
        (
            crear_fila_original() if original is None else original,
            crear_fila_reverso(),
        )
    )

    ctx.fake(
        "obtener_transaccion",
        lambda *args: next(transacciones),
    )

    respuestas = {
        "existe_reverso": False,
        "movimientos_de_transaccion": [
            {
                "IdMovimiento": 1,
                "IdCuenta": 501,
                "TipoMovimiento": "D",
                "RolCuenta": None,
                "Monto": MONTO,
            }
        ],
        "insertar_transaccion": ID_REVERSO,
        "aplicar_movimiento_cuenta": 10,
        "movimiento_caja_de_transaccion": {
            "IdJornadaCaja": 55,
            "IdAgencia": "001",
            "Monto": MONTO,
            "Codigo": "RET_E",
            "Naturaleza": "E",
        },
        "id_tipo_movimiento_caja": 3,
        "insertar_movimiento_caja": None,
        "marcar_reversada": True,
    }

    for metodo, respuesta in respuestas.items():
        ctx.fake(metodo, respuesta)

    ctx.fake(
        "obtener_cuenta",
        {
            "IdCuenta": 501,
            "IdAgencia": "001",
            "Saldo": Decimal("1000.00"),
            "SaldoRetenido": Decimal("0.00"),
            "Estado": "Activa",
        },
    )

    for metodo, respuesta in (
        ("id_fecha_contable", FECHA),
        ("calcular_totales", TOTALES),
        ("obtener_jornada", {"Estado": "ABIERTA"}),
        ("obtener_cuadre_de_jornada", None),
    ):
        ctx.fake(metodo, respuesta, caja_repo)

    return deps


def solicitar_reverso(
    ctx: Contexto,
    motivo: str = "Solicitud",
    cuerpo: dict[str, Any] | None = None,
) -> Any:
    """Envía una solicitud al endpoint TRX-03."""
    datos = {"motivo": motivo} if cuerpo is None else cuerpo

    return ctx.cliente.post(
        f"{BASE}/{ID_ORIGINAL}/reverso",
        json=datos,
    )


def test_reverso_comparte_instante_con_el_calendario(
    ctx: Contexto, monkeypatch: pytest.MonkeyPatch
) -> None:
    preparar_reverso(ctx)
    instante = datetime(2026, 11, 6, 19)
    reloj = Mock(side_effect=[instante, AssertionError("Se volvió a leer el reloj")])
    monkeypatch.setattr(service, "ahora_ecuador", reloj)

    respuesta = solicitar_reverso(ctx)

    assert respuesta.status_code == 201, respuesta.text
    reloj.assert_called_once_with()
    assert ctx.llamadas["id_fecha_contable"] == [(instante,)]
    assert ctx.llamadas["insertar_transaccion"][0][0]["fecha_hora"] == instante


def test_trx03_sin_configuracion_501(ctx: Contexto) -> None:
    respuesta = solicitar_reverso(ctx)

    assert respuesta.status_code == 501
    assert code(respuesta) == "OPERACION_NO_HABILITADA"
    ctx.conn.begin.assert_not_called()
    assert ctx.eventos[-1].resultado == "Fallido"


def test_trx03_reverso_atm(ctx: Contexto) -> None:
    deps = preparar_reverso(ctx)

    respuesta = solicitar_reverso(ctx)

    assert respuesta.status_code == 201, respuesta.text

    cuerpo = respuesta.json()
    assert cuerpo["tipoOperacion"] == "Reverso"
    assert cuerpo["idTransaccionRelacionada"] == ID_ORIGINAL

    datos = ctx.llamadas["insertar_transaccion"][0][0]

    assert datos["mti"] == "0400"
    assert datos["id_relacionada"] == ID_ORIGINAL
    assert datos["creado_por"] == ID_SUPERVISOR
    assert datos["registro_unico"] == "REV000000005"

    assert ctx.llamadas["aplicar_movimiento_cuenta"] == [
        (ID_REVERSO, 501, "C", None, MONTO, FECHA)
    ]

    deps.revertir_comisiones.assert_called_once_with(
        ctx.conn,
        ID_ORIGINAL,
        ID_REVERSO,
    )

    deps.contabilizar.assert_called_once()
    asiento = deps.contabilizar.call_args.args[1]

    assert isinstance(asiento, DatosAsiento)
    assert asiento.id_transaccion_original == ID_ORIGINAL

    assert ctx.llamadas["marcar_reversada"] == [(ID_ORIGINAL,)]
    assert not ctx.llamadas["insertar_movimiento_caja"]
    assert "motivo=Solicitud" in ctx.eventos[-1].descripcion


def test_trx03_reverso_de_ventanilla_mueve_caja(
    ctx: Contexto,
) -> None:
    preparar_reverso(
        ctx,
        crear_fila_original(IdJornadaCaja=55),
    )

    respuesta = solicitar_reverso(
        ctx,
        motivo="Error de digitación",
    )

    assert respuesta.status_code == 201, respuesta.text

    assert ctx.llamadas["id_tipo_movimiento_caja"] == [("RET_I",)]

    assert ctx.llamadas["insertar_movimiento_caja"][0][:2] == (
        ID_REVERSO,
        55,
    )


@pytest.mark.parametrize(
    ("cambios", "simulacion", "codigo"),
    [
        (
            {"Estado": "Reversada"},
            None,
            "TRANSACCION_YA_REVERSADA",
        ),
        (
            {},
            ("existe_reverso", True),
            "TRANSACCION_YA_REVERSADA",
        ),
        (
            {"TipoOperacion": "Reverso"},
            None,
            "TRANSACCION_NO_REVERSABLE",
        ),
        (
            {"Estado": "Rechazada"},
            None,
            "TRANSACCION_NO_REVERSABLE",
        ),
        (
            {},
            ("movimientos_de_transaccion", []),
            "TRANSACCION_NO_REVERSABLE",
        ),
        (
            {"IdJornadaCaja": 55},
            (
                "obtener_jornada",
                {"Estado": "CERRADA"},
                caja_repo,
            ),
            "JORNADA_CERRADA",
        ),
        (
            {},
            ("marcar_reversada", False),
            "TRANSACCION_YA_REVERSADA",
        ),
    ],
)
def test_trx03_conflictos_409(
    ctx: Contexto,
    cambios: dict[str, Any],
    simulacion: tuple[Any, ...] | None,
    codigo: str,
) -> None:
    preparar_reverso(
        ctx,
        crear_fila_original(**cambios),
    )

    if simulacion is not None:
        ctx.fake(*simulacion)

    respuesta = solicitar_reverso(ctx)

    assert respuesta.status_code == 409
    assert code(respuesta) == codigo


def test_trx03_reglas_de_acceso(ctx: Contexto) -> None:
    preparar_reverso(
        ctx,
        crear_fila_original(AgenciaOperacion="002"),
    )

    respuesta = solicitar_reverso(ctx)
    assert respuesta.status_code == 404

    ctx.id_interno = None

    respuesta = solicitar_reverso(ctx)
    assert code(respuesta) == "USUARIO_INTERNO_NO_VINCULADO"

    ctx.usuario = usuario("AUDITOR")

    respuesta = solicitar_reverso(ctx)
    assert respuesta.status_code == 403


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"motivo": ""},
        {"motivo": "x", "monto": 1},
    ],
)
def test_trx03_validacion_400(
    ctx: Contexto,
    cuerpo: dict[str, Any],
) -> None:
    respuesta = solicitar_reverso(
        ctx,
        cuerpo=cuerpo,
    )

    assert respuesta.status_code == 400


def test_main_tiene_las_3_operaciones_de_transacciones() -> None:
    """Comprueba que las operaciones TRX estén registradas."""
    from app.main import app

    operaciones = {
        operacion.get("operationId")
        for ruta, metodos in app.openapi()["paths"].items()
        if ruta.startswith(BASE)
        for operacion in metodos.values()
    }

    assert operaciones == {
        "TRX01",
        "TRX02",
        "TRX03",
    }
