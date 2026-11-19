"""E0-05 B: el evento de cada operación de dinero se escribe en la bandeja dentro de su
transacción (ninguno de los dos queda sin el otro)."""

import ast
import json
from pathlib import Path

import pytest

from app.core.config.logs import trace_id_actual
from app.core.security import operador
from app.core.security.auth import Usuario

BACKEND = Path(__file__).resolve().parents[2]
SERVICIOS_DINERO = [
    "app/modules/caja/service.py",
    "app/modules/boveda/service.py",
    "app/modules/boveda/solicitudes/service.py",
    "app/modules/transacciones/service.py",
]


def _es(item: ast.withitem, nombre: str) -> bool:
    f = getattr(item.context_expr, "func", None)
    return getattr(f, "id", None) == nombre or getattr(f, "attr", None) == nombre


@pytest.mark.parametrize("ruta", SERVICIOS_DINERO)
def test_cada_operacion_de_dinero_confirma_dentro_de_su_transaccion(ruta):
    # Prueba del pipeline (criterio 6): una operación nueva con auditar() debe llamar
    # registro.confirmar(conn) dentro de su `with conn.begin()`.
    arbol = ast.parse((BACKEND / ruta).read_text(encoding="utf-8"))
    bloques = [
        n
        for n in ast.walk(arbol)
        if isinstance(n, ast.With) and any(_es(i, "auditar") for i in n.items)
    ]
    assert bloques
    sin_confirmar = []
    for bloque in bloques:
        transacciones = [
            m
            for m in ast.walk(bloque)
            if isinstance(m, ast.With) and any(_es(i, "begin") for i in m.items)
        ]
        if not any(".confirmar(" in ast.unparse(m) for m in transacciones):
            sin_confirmar.append(bloque.lineno)
    assert not sin_confirmar, (
        f"{ruta}: auditar() sin confirmar en su transacción, líneas {sin_confirmar}"
    )


class _Filas:
    def __init__(self, filas):
        self.filas = filas

    def mappings(self):
        return self

    def all(self):
        return self.filas


class _Conn:
    def __init__(self, en_transaccion=True, filas=None):
        self.en_transaccion, self.sql, self.params = en_transaccion, "", {}
        self.filas = filas or []

    def in_transaction(self):
        return self.en_transaccion

    def execute(self, sql, params):
        if str(sql).startswith("SELECT"):
            return _Filas(self.filas)
        self.sql, self.params = str(sql), params
        return None


def _usuario() -> Usuario:
    return Usuario(
        id_usuario="user_01",
        id_sesion="session_1",
        id_organizacion="org_1",
        nombre="Cajero",
        email="cajero@example.com",
        roles=("CAJERO",),
        permisos=(),
        id_agencia="001",
    )


def test_confirmar_escribe_en_la_bandeja_y_no_duplica(monkeypatch):
    registrados = []
    monkeypatch.setattr(operador.audit, "registrar", registrados.append)
    conn = _Conn()
    token = trace_id_actual.set("traza-9")
    try:
        with operador.auditar(
            "REGISTRAR_DEPOSITO",
            "Transacciones.Transaccion",
            _usuario(),
            "10.0.0.1",
            "monto=10.00",
        ) as registro:
            registro.id_registro = "55"
            registro.confirmar(conn)  # type: ignore[arg-type]
    finally:
        trace_id_actual.reset(token)
    assert (
        "Auditoria.EventoPendiente" in conn.sql
        and conn.params["codigo"] == "REGISTRAR_DEPOSITO"
    )
    contenido = json.loads(conn.params["contenido"])
    assert (
        contenido["idObjetivo"] == "55"
        and contenido["tablaAfectada"] == "Transacciones.Transaccion"
    )
    assert contenido["agencia"] == "001" and contenido["correlacion"] == "traza-9"
    assert "monto=10.00" in contenido["descripcion"]
    assert registrados == []  # el éxito ya quedó en la bandeja: no se escribe dos veces


def test_confirmar_apunta_a_la_tabla_de_movimiento():
    conn = _Conn()
    with operador.auditar(
        "REGISTRAR_DOTACION", "Caja.DotacionesCaja", _usuario(), "ip", "x"
    ) as registro:
        registro.id_registro = "7"
        registro.confirmar(
            conn,  # type: ignore[arg-type]
            objetivo="Boveda.MovimientoBoveda",
            id_objetivo="900",
            cambios={"idDotacionCaja": "7"},
        )
    contenido = json.loads(conn.params["contenido"])
    assert (contenido["tablaAfectada"], contenido["idObjetivo"]) == (
        "Boveda.MovimientoBoveda",
        "900",
    )
    assert contenido["cambios"] == {"idDotacionCaja": "7"}


def test_confirmar_exige_transaccion_abierta():
    with (
        pytest.raises(RuntimeError),
        operador.auditar(
            "ABRIR_JORNADA", "Caja.JornadasCaja", _usuario(), "ip", "x"
        ) as registro,
    ):
        registro.confirmar(_Conn(en_transaccion=False))  # type: ignore[arg-type]


def test_si_la_operacion_falla_despues_se_registra_el_fallo(monkeypatch):
    registrados = []
    monkeypatch.setattr(operador.audit, "registrar", registrados.append)
    with (
        pytest.raises(ValueError),
        operador.auditar(
            "CERRAR_JORNADA", "Caja.JornadasCaja", _usuario(), "ip", "x"
        ) as registro,
    ):
        registro.confirmar(_Conn())  # type: ignore[arg-type]
        raise ValueError("la transacción se revierte con el evento")
    assert [e.resultado for e in registrados] == ["Fallido"]


def test_sin_confirmar_sigue_el_registro_directo(monkeypatch):
    registrados = []
    monkeypatch.setattr(operador.audit, "registrar", registrados.append)
    with operador.auditar("LOGIN", "x", _usuario(), "ip", "x"):
        pass
    assert [e.resultado for e in registrados] == ["Exitoso"]


def test_el_evento_lleva_los_montos_del_registro():
    from decimal import Decimal

    conn = _Conn(
        filas=[
            {
                "monto": Decimal("80.00"),
                "rolCuenta": "Origen",
                "tipo": "D",
                "montoCuenta": Decimal("80.00"),
                "saldoAnterior": Decimal("100.00"),
                "saldoPosterior": Decimal("20.00"),
            }
        ]
    )
    with operador.auditar(
        "REGISTRAR_RETIRO", "Transacciones.Transaccion", _usuario(), "ip", "x"
    ) as registro:
        registro.id_registro = "12"
        registro.confirmar(conn)  # type: ignore[arg-type]
    cambios = json.loads(conn.params["contenido"])["cambios"]
    assert cambios["monto"] == "80.00"
    assert cambios["cuentas"] == [
        {
            "rolCuenta": "Origen",
            "tipo": "D",
            "montoCuenta": "80.00",
            "saldoAnterior": "100.00",
            "saldoPosterior": "20.00",
        }
    ]


def test_montos_de_varios_movimientos_y_tabla_sin_montos():
    from decimal import Decimal

    conn = _Conn(filas=[{"monto": Decimal("5.00"), "tipo": "AjusteSobrante"}])
    assert operador.montos(conn, "Boveda.MovimientoBoveda", "1,2") == {  # type: ignore[arg-type]
        "movimientos": [{"monto": "5.00", "tipo": "AjusteSobrante"}] * 2
    }
    assert operador.montos(conn, "Boveda.BilleteSerie", "1") == {}  # type: ignore[arg-type]
    assert operador.montos(conn, "Transacciones.Transaccion", "1;DROP") == {}  # type: ignore[arg-type]


# ── ATM: listo para activar ──────────────────────────────────────────────────

SERVICIOS_ATM = [
    "app/modules/atm/retiros_service.py",
    "app/modules/atm/transferencias_service.py",
    "app/modules/atm/reversos_service.py",
]


@pytest.mark.parametrize("ruta", SERVICIOS_ATM)
def test_atm_al_activarse_exige_evento_en_la_transaccion(ruta):
    """Mientras `solicitar_*` responda «no habilitada» no hay nada que auditar; en cuanto
    se active, el servicio debe llamar confirmar_atm() (dentro de su transacción)."""
    arbol = ast.parse((BACKEND / ruta).read_text(encoding="utf-8"))
    solicitudes = [
        f
        for f in arbol.body
        if isinstance(f, ast.FunctionDef) and f.name.startswith("solicitar_")
    ]
    assert solicitudes
    pendiente = all("raise no_habilitada()" in ast.unparse(f) for f in solicitudes)
    assert pendiente or "confirmar_atm(" in ast.unparse(arbol), (
        f"{ruta}: operación de dinero ATM sin confirmar_atm()"
    )


def test_confirmar_atm_escribe_el_evento_del_terminal():
    from datetime import datetime

    from app.modules.atm.auditoria import confirmar_atm
    from app.modules.atm.session import SesionATM
    from app.modules.atm.terminal_auth import TerminalAutenticado

    sesion = SesionATM(
        jti="jti-1",
        fecha_expiracion=datetime(2030, 1, 1),
        id_atm=3,
        id_tarjeta=44,
        cuentas=(9,),
    )
    terminal = TerminalAutenticado(
        credential_id="c", codigo_atm="ATM00001", audit_user_id=1, digest=b"x"
    )
    conn = _Conn()
    confirmar_atm(conn, "retiro", sesion, terminal, 501)  # type: ignore[arg-type]
    contenido = json.loads(conn.params["contenido"])
    assert conn.params["codigo"] == "ATM_RETIRO"
    assert (contenido["canal"], contenido["sujeto"], contenido["idObjetivo"]) == (
        "ATM",
        "atm:ATM00001",
        "501",
    )
    assert (
        contenido["tablaAfectada"] == "Transacciones.Transaccion"
        and contenido["cambios"]["idAtm"] == 3
    )
    with pytest.raises(RuntimeError):
        confirmar_atm(_Conn(en_transaccion=False), "retiro", sesion, terminal, 501)  # type: ignore[arg-type]
