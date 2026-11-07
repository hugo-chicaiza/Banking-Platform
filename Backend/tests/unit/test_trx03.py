"""TRX-03 · POST /api/v1/transacciones/{idTransaccion}/reverso (pruebas sin BD)."""

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest

from app.modules.caja import repository as caja_repo
from app.modules.transacciones import repository as repo
from app.modules.transacciones.dependencias import (
    DatosAsiento,
    Numeracion,
    dependencias_operacion,
)
from app.modules.transacciones.router import router
from tests.caja_contexto import ID_SUPERVISOR, Contexto, code, crear_contexto, usuario

BASE = "/api/v1/transacciones"


def crear_fila_original(**cambios: Any) -> dict[str, Any]:
    """Construye una transacción de prueba para los escenarios de reverso."""
    fila = dict(
        zip(
            (
                "IdTransaccion",
                "NumeroComprobante",
                "RegistroUnico",
                "MTI",
                "STAN",
                "RRN",
                "TipoOperacion",
                "TipoTransaccion",
                "IdCuenta",
                "IdCuentaDestino",
                "IdTarjeta",
                "IdCanal",
                "IdTerminal",
                "IdAgencia",
                "IdJornadaCaja",
                "IdTransaccionRelacionada",
                "Monto",
                "CodigoRespuesta",
                "Estado",
                "IdFechaContable",
                "FechaHoraSistema",
                "CreadoPor",
                "NumeroAutorizacion",
                "AgenciaOperacion",
            ),
            (
                2001,
                "COMP-001",
                "ATM000000002",
                "0200",
                "000001",
                "000000000001",
                "Normal",
                "Retiro",
                501,
                None,
                None,
                4,
                None,
                "001",
                None,
                None,
                Decimal("40.00"),
                "00",
                "Completada",
                20261104,
                datetime(2026, 11, 4, 10, 15),
                7,
                None,
                "001",
            ),
            strict=True,
        )
    )
    fila.update(cambios)
    return fila


FILA = crear_fila_original()

@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(
        monkeypatch, router, repo, roles=("SUPERVISOR",), id_interno=ID_SUPERVISOR
    )


class DependenciasFalsas:
    def __init__(self) -> None:
        self.asientos: list[DatosAsiento] = []
        self.revertidas: list[tuple[int, int]] = []

    def verificar_habilitadas(self) -> None:
        return None

    @property
    def id_canal_ventanilla(self) -> int:
        return 4

    @property
    def codigo_pais_origen(self) -> str:
        return "ECU"

    def codigo_tipo_movimiento_caja(
        self, tipo_transaccion: str, naturaleza: str
    ) -> str:
        return f"{tipo_transaccion[:3].upper()}_{naturaleza}"

    def numerar(
        self, conn: Any, tipo_transaccion: str, tipo_operacion: str
    ) -> Numeracion:
        return Numeracion(
            "COMP-REV-001",
            "000005",
            "210000",
            "000005",
            "000000000005",
            None,
            "REV000000005",
        )

    def contabilizar(self, conn: Any, datos: DatosAsiento) -> int | None:
        self.asientos.append(datos)
        return 778

    def registrar_comision(
        self, conn: Any, id_transaccion: int, monto: Decimal
    ) -> None:
        raise AssertionError("no aplica al reverso")

    def revertir_comisiones(self, conn: Any, id_original: int, id_reverso: int) -> None:
        self.revertidas.append((id_original, id_reverso))


REVERSO = {
    **FILA,
    "IdTransaccion": 2002,
    "NumeroComprobante": "COMP-REV-001",
    "RegistroUnico": "REV000000005",
    "MTI": "0400",
    "TipoOperacion": "Reverso",
    "IdTransaccionRelacionada": 2001,
    "CreadoPor": ID_SUPERVISOR,
}


def preparar_reverso(
    ctx: Contexto,
    original: dict[str, Any] | None = None,
) -> DependenciasFalsas:
    deps = DependenciasFalsas()

    ctx.app.dependency_overrides[dependencias_operacion] = lambda: deps

    filas = iter(
        [
            FILA if original is None else original,
            REVERSO,
        ]
    )

    valores = {
        "existe_reverso": False,
        "movimientos_de_transaccion": [
            {
                "IdMovimiento": 1,
                "IdCuenta": 501,
                "TipoMovimiento": "D",
                "RolCuenta": None,
                "Monto": Decimal("40.00"),
            }
        ],
        "insertar_transaccion": 2002,
        "aplicar_movimiento_cuenta": 10,
        "movimiento_caja_de_transaccion": {
            "IdJornadaCaja": 55,
            "IdAgencia": "001",
            "Monto": Decimal("40.00"),
            "Codigo": "RET_E",
            "Naturaleza": "E",
        },
        "id_tipo_movimiento_caja": 3,
        "insertar_movimiento_caja": None,
        "marcar_reversada": True,
    }

    ctx.fake("obtener_transaccion", lambda *args: next(filas))

    for nombre, valor in valores.items():
        ctx.fake(nombre, valor)

    ctx.fake("id_fecha_contable", 20261104, caja_repo)
    ctx.fake("obtener_jornada", {"Estado": "ABIERTA"}, caja_repo)
    ctx.fake("obtener_cuadre_de_jornada", None, caja_repo)

    return deps


def test_trx03_sin_configuracion_501(ctx: Contexto) -> None:
    r = ctx.cliente.post(f"{BASE}/2001/reverso", json={"motivo": "Solicitud"})
    assert r.status_code == 501
    assert code(r) == "OPERACION_NO_HABILITADA"
    ctx.conn.begin.assert_not_called()
    assert ctx.eventos[-1].resultado == "Fallido"


def test_trx03_reverso_atm(ctx: Contexto) -> None:
    deps = preparar_reverso(ctx)
    r = ctx.cliente.post(f"{BASE}/2001/reverso", json={"motivo": "Solicitud"})
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["tipoOperacion"] == "Reverso"
    assert cuerpo["idTransaccionRelacionada"] == 2001
    datos = ctx.llamadas["insertar_transaccion"][0][0]
    assert datos["mti"] == "0400"
    assert datos["id_relacionada"] == 2001
    assert datos["creado_por"] == ID_SUPERVISOR
    assert datos["registro_unico"] == "REV000000005"
    # Débito original → crédito en el reverso
    assert ctx.llamadas["aplicar_movimiento_cuenta"] == [
        (2002, 501, "C", None, Decimal("40.00"), 20261104)
    ]
    assert deps.revertidas == [(2001, 2002)]
    assert deps.asientos[0].id_transaccion_original == 2001
    assert ctx.llamadas["marcar_reversada"] == [(2001,)]
    # Sin jornada (ATM): no hay movimiento de caja
    assert not ctx.llamadas["insertar_movimiento_caja"]
    assert "motivo=Solicitud" in ctx.eventos[-1].descripcion


def test_trx03_reverso_de_ventanilla_mueve_caja(ctx: Contexto) -> None:
    preparar_reverso(ctx, {**FILA, "IdJornadaCaja": 55})
    r = ctx.cliente.post(f"{BASE}/2001/reverso", json={"motivo": "Error de digitación"})
    assert r.status_code == 201, r.text
    assert ctx.llamadas["id_tipo_movimiento_caja"] == [("RET_I",)]
    assert ctx.llamadas["insertar_movimiento_caja"][0][:2] == (2002, 55)


@pytest.mark.parametrize(
    ("original", "fake", "codigo"),
    [
        ({**FILA, "Estado": "Reversada"}, None, "TRANSACCION_YA_REVERSADA"),
        (FILA, ("existe_reverso", True), "TRANSACCION_YA_REVERSADA"),
        ({**FILA, "TipoOperacion": "Reverso"}, None, "TRANSACCION_NO_REVERSABLE"),
        ({**FILA, "Estado": "Rechazada"}, None, "TRANSACCION_NO_REVERSABLE"),
        (FILA, ("movimientos_de_transaccion", []), "TRANSACCION_NO_REVERSABLE"),
        (
            {**FILA, "IdJornadaCaja": 55},
            ("obtener_jornada", {"Estado": "CERRADA"}, caja_repo),
            "JORNADA_CERRADA",
        ),
        (FILA, ("marcar_reversada", False), "TRANSACCION_YA_REVERSADA"),
    ],
)
def test_trx03_conflictos_409(
    ctx: Contexto, original: dict[str, Any], fake: Any, codigo: str
) -> None:
    preparar_reverso(ctx, original)
    if fake:
        ctx.fake(*fake)
    r = ctx.cliente.post(f"{BASE}/2001/reverso", json={"motivo": "Solicitud"})
    assert r.status_code == 409
    assert code(r) == codigo


def test_trx03_reglas_de_acceso(ctx: Contexto) -> None:
    preparar_reverso(ctx, {**FILA, "AgenciaOperacion": "002"})
    r = ctx.cliente.post(f"{BASE}/2001/reverso", json={"motivo": "x"})
    assert r.status_code == 404
    ctx.id_interno = None
    r = ctx.cliente.post(f"{BASE}/2001/reverso", json={"motivo": "x"})
    assert code(r) == "USUARIO_INTERNO_NO_VINCULADO"
    ctx.usuario = usuario("AUDITOR")
    assert (
        ctx.cliente.post(f"{BASE}/2001/reverso", json={"motivo": "x"}).status_code
        == 403
    )


@pytest.mark.parametrize("cuerpo", [{}, {"motivo": ""}, {"motivo": "x", "monto": 1}])
def test_trx03_validacion_400(ctx: Contexto, cuerpo: dict[str, Any]) -> None:
    assert ctx.cliente.post(f"{BASE}/2001/reverso", json=cuerpo).status_code == 400


def _operaciones() -> dict[tuple[str, str], str]:
    """(método, ruta) → operationId según el OpenAPI que genera main.py."""
    from app.main import app

    return {
        (metodo.upper(), ruta): operacion.get("operationId", "")
        for ruta, metodos in app.openapi()["paths"].items()
        for metodo, operacion in metodos.items()
    }


def test_main_tiene_las_3_operaciones_de_transacciones() -> None:
    ids = {
        op
        for (_, ruta), op in _operaciones().items()
        if "/api/v1/transacciones" in ruta
    }
    assert ids == {"TRX01", "TRX02", "TRX03"}
