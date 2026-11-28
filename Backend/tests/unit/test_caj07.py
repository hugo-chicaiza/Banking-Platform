"""CAJ-07 · POST /api/v1/caja/jornadas/{idJornada}/dotaciones (pruebas sin BD)."""

from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import traducir_error_bd
from app.core.database.procedimientos import ejecutar_con_salidas
from app.modules.caja import dotaciones
from app.modules.caja.router import router
from app.modules.caja.schemas import Desglose
from app.modules.caja.service import desglose_json, validar_custodia
from tests.caja_contexto import (
    BASE,
    DOTACION,
    ID_CAJERO,
    ID_SUPERVISOR,
    JORNADA,
    Contexto,
    code,
    crear_contexto,
    error_bd,
)


@pytest.fixture
def ctx(monkeypatch: pytest.MonkeyPatch) -> Iterator[Contexto]:
    yield crear_contexto(monkeypatch, router)


SOLICITUD = {
    "IdSolicitud": 8,
    "IdJornada": 55,
    "IdBoveda": 2,
    "IdAgencia": "001",
    "IdFechaContable": 20261104,
    "SolicitadoPor": ID_CAJERO,
    "AutorizadoPor": ID_SUPERVISOR,
    "FechaSolicitud": datetime(2026, 11, 4, 12),
    "TipoDotacion": "INICIAL",
    "Desglose": '[{"IdDenominacion": 1, "Cantidad": 10}]',
    "Valores": '{"1": "10.05"}',
    "Monto": Decimal("100.50"),
    "Observacion": None,
    "Estado": "PENDIENTE",
    "ResueltoPor": None,
    "FechaResolucion": None,
    "Motivo": None,
    "IdDotacionCaja": None,
    "BovedaBajoMinimo": None,
}
CUERPO = {
    "idBoveda": 2,
    "autorizadoPor": ID_SUPERVISOR,
    "tipoDotacion": "INICIAL",
    "desglose": [{"idDenominacion": 1, "cantidad": 10}],
}
RUTA = f"{BASE}/solicitudes-dotacion/8/confirmacion"


def test_post_legado_retirado(ctx: Contexto) -> None:
    r = ctx.cliente.post(f"{BASE}/jornadas/55/dotaciones", json=CUERPO)
    assert r.status_code == 410
    assert code(r) == "SOLICITUD_DOTACION_REQUERIDA"


@pytest.mark.parametrize(
    "cambio", [{"autorizadoPor": 0}, {"desglose": []}, {"tipoDotacion": "OTRA"}]
)
def test_solicitud_rechaza_datos_invalidos(
    ctx: Contexto, cambio: dict[str, Any]
) -> None:
    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/solicitudes-dotacion",
        json={**CUERPO, **cambio},
        headers={"Idempotency-Key": "xyz"},
    )
    assert r.status_code == 400


def test_cajero_solicita_sin_ejecutar(ctx: Contexto) -> None:
    ctx.fake("solicitar", dotaciones._respuesta(SOLICITUD, 20261104), dotaciones)
    r = ctx.cliente.post(
        f"{BASE}/jornadas/55/solicitudes-dotacion",
        json=CUERPO,
        headers={"Idempotency-Key": "xyz"},
    )
    assert r.status_code == 202
    assert r.json()["estado"] == "PENDIENTE"


@pytest.mark.parametrize(
    ("rol", "actor", "agencia", "codigo"),
    [
        ("SUPERVISOR", ID_CAJERO, "001", "DOBLE_CUSTODIA"),
        ("CAJERO", 99, "001", "SIN_PERMISO"),
        ("SUPERVISOR", ID_SUPERVISOR, "002", "SIN_ACCESO_AGENCIA"),
        ("SUPERVISOR", 99, "001", "AUTORIZADOR_NO_ASIGNADO"),
    ],
)
def test_confirmacion_comprueba_actor(
    ctx: Contexto, rol: str, actor: int, agencia: str, codigo: str
) -> None:
    ctx.como(rol, id_interno=actor, agencia=agencia)
    ctx.fake("_fila", SOLICITUD, dotaciones)
    ctx.fake("obtener_jornada", JORNADA)
    r = ctx.cliente.post(RUTA)
    assert r.status_code == 403
    assert code(r) == codigo


def preparar_confirmacion(ctx: Contexto, fila: dict[str, Any] | None = None) -> None:
    ctx.como("SUPERVISOR", id_interno=ID_SUPERVISOR)
    ctx.fake("_fila", SOLICITUD if fila is None else fila, dotaciones)
    ctx.fake("_boveda", None, dotaciones)
    ctx.fake("_valores", {"1": "10.05"}, dotaciones)
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("id_fecha_contable", 20261104)
    ctx.fake("obtener_dotacion", DOTACION)
    ctx.fake(
        "registrar_dotacion",
        {"IdDotacionCaja": 801, "IdMovimientoBoveda": 9001, "BovedaBajoMinimo": True},
    )
    ctx.fake("vincular_asiento", None, dotaciones)
    ctx.fake("autorizadores_dotacion", [{"UsuarioID": ID_SUPERVISOR}])
    ctx.fake("preparar_dotacion_inicial")
    ctx.fake("limite_efectivo_caja")
    ctx.fake("vincular_asiento_dotacion")


def test_custodio_confirma_con_identidad_y_asiento(ctx: Contexto) -> None:
    preparar_confirmacion(ctx)
    ctx.fake("generar_asiento", 1, dotaciones)
    r = ctx.cliente.post(RUTA)
    assert r.status_code == 201, r.text
    assert r.json()["bovedaBajoMinimo"] is True
    assert ctx.llamadas["registrar_dotacion"][0][2] == ID_SUPERVISOR
    asiento = ctx.llamadas["generar_asiento"][0][0]
    assert (asiento.codigo_plantilla, asiento.id_usuario, asiento.clave_evento) == (
        "DOT_CAJA",
        ID_SUPERVISOR,
        "DOTACION_CAJA:801",
    )
    assert ctx.llamadas["vincular_asiento"] == [(9001, 1)]
    assert ctx.llamadas["vincular_asiento_dotacion"] == [(801, 1)]
    assert ctx.llamadas["preparar_dotacion_inicial"] == [(55, Decimal("100.50"))]
    assert r.json()["idAsientoContable"] == 1


def test_reintento_confirmado(ctx: Contexto) -> None:
    preparar_confirmacion(
        ctx,
        {
            **SOLICITUD,
            "Estado": "CONFIRMADA",
            "IdDotacionCaja": 801,
            "BovedaBajoMinimo": True,
        },
    )
    assert ctx.cliente.post(RUTA).status_code == 200
    assert not ctx.llamadas["registrar_dotacion"]


@pytest.mark.parametrize(
    ("numero", "status"),
    [(51008, 409), (51009, 409), (51010, 422), (51014, 422), (51015, 422)],
)
def test_confirmacion_conserva_reglas_sql(
    ctx: Contexto, numero: int, status: int
) -> None:
    preparar_confirmacion(ctx)
    ctx.fake("registrar_dotacion", error_bd(numero))
    r = ctx.cliente.post(RUTA)
    assert r.status_code == status, r.text
    assert code(r) == f"DB_{numero}"


def test_confirmacion_caduca_al_cambiar_dia(ctx: Contexto) -> None:
    preparar_confirmacion(ctx)
    ctx.fake("id_fecha_contable", 20261105)
    r = ctx.cliente.post(RUTA)
    assert r.status_code == 409
    assert code(r) == "SOLICITUD_DOTACION_CADUCADA"
    assert not ctx.llamadas["registrar_dotacion"]


def test_desglose_json_formato_del_procedimiento() -> None:
    texto = desglose_json([Desglose(id_denominacion=3, cantidad=20)])
    assert texto == '[{"IdDenominacion": 3, "Cantidad": 20}]'


def test_validar_custodia() -> None:
    validar_custodia("CAJERO", actor=7, autorizado_por=9, id_cajero=7)
    validar_custodia("SUPERVISOR", actor=9, autorizado_por=9, id_cajero=7)
    with pytest.raises(HTTPException) as exc:
        validar_custodia("CAJERO", actor=7, autorizado_por=7, id_cajero=7)
    assert exc.value.detail["code"] == "DOBLE_CUSTODIA_VIOLADA"  # type: ignore[index]
    with pytest.raises(HTTPException) as exc:
        validar_custodia("SUPERVISOR", actor=9, autorizado_por=10, id_cajero=7)
    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    ("numero", "status", "codigo"),
    [
        (51006, 409, "DB_51006"),
        (51014, 422, "DB_51014"),
        (51005, 404, "DB_51005"),
        (52002, 409, "CUENTA_NO_ACTIVA"),  # regresión: lo previo no cambia
        (51201, 422, "DB_51201"),
    ],
)
def test_traduccion_de_throw_caja(numero: int, status: int, codigo: str) -> None:
    exc = traducir_error_bd(
        DBAPIError("EXEC", None, Exception(f"Texto ({numero}) (SQLExecDirectW)"))
    )
    assert exc.status_code == status
    assert exc.detail["code"] == codigo  # type: ignore[index]


class _CursorFalso:
    """Simula pyodbc: un conjunto del SP y luego el SELECT de las salidas."""

    def __init__(
        self, conjuntos: list[tuple[list[str], list[tuple[Any, ...]]]]
    ) -> None:
        self._conjuntos = conjuntos
        self._i = 0
        self.ejecutado: tuple[str, tuple[Any, ...]] | None = None
        self.cerrado = False

    @property
    def description(self) -> list[tuple[str]] | None:
        columnas = self._conjuntos[self._i][0]
        return [(c,) for c in columnas] if columnas else None

    def execute(self, sql: str, parametros: tuple[Any, ...]) -> None:
        self.ejecutado = (sql, parametros)

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._conjuntos[self._i][1]

    def nextset(self) -> bool:
        self._i += 1
        return self._i < len(self._conjuntos)

    def close(self) -> None:
        self.cerrado = True


class _ErrorDbapi(Exception):
    pass


def _conexion(cursor: Any) -> MagicMock:
    conn = MagicMock()
    conn.connection.cursor.return_value = cursor
    conn.dialect.loaded_dbapi.Error = _ErrorDbapi
    return conn


def test_ejecutar_con_salidas_toma_el_ultimo_resultado() -> None:
    cursor = _CursorFalso(
        [
            (["Interno"], [(1,)]),
            ([], []),
            (["IdDotacionCaja", "BovedaBajoMinimo"], [(5, True)]),
        ]
    )
    salida = ejecutar_con_salidas(_conexion(cursor), "EXEC x ?", [10])
    assert salida == {"IdDotacionCaja": 5, "BovedaBajoMinimo": True}
    assert cursor.ejecutado == ("EXEC x ?", (10,))
    assert cursor.cerrado


def test_ejecutar_con_salidas_envuelve_el_throw() -> None:
    class _CursorQueFalla(_CursorFalso):
        def execute(self, sql: str, parametros: tuple[Any, ...]) -> None:
            raise _ErrorDbapi("Mensaje (51007) (SQLExecDirectW)")

    cursor = _CursorQueFalla([([], [])])
    with pytest.raises(DBAPIError) as exc:
        ejecutar_con_salidas(_conexion(cursor), "EXEC x ?", [1])
    assert traducir_error_bd(exc.value).status_code == 409
    assert cursor.cerrado


def test_ejecutar_con_salidas_sin_resultado_falla() -> None:
    with pytest.raises(RuntimeError):
        ejecutar_con_salidas(_conexion(_CursorFalso([([], [])])), "EXEC x", [])


def test_selector_solo_expone_nombre_e_id(ctx: Contexto) -> None:
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake(
        "autorizadores_dotacion",
        [
            {
                "UsuarioID": ID_SUPERVISOR,
                "NombreCompleto": "Ana Perez",
                "RolesWorkOS": "SUPERVISOR",
            }
        ],
    )
    respuesta = ctx.cliente.get(f"{BASE}/jornadas/55/autorizadores-dotacion")
    assert respuesta.status_code == 200
    assert respuesta.json() == [
        {"idUsuario": ID_SUPERVISOR, "nombreCompleto": "Ana Perez"}
    ]


@pytest.mark.parametrize(
    ("rol", "actor", "agencia", "estado"),
    [
        ("ADMIN", 9, "001", 403),
        ("CAJERO", 99, "001", 404),
        ("CAJERO", ID_CAJERO, "002", 403),
    ],
)
def test_selector_restringe_la_jornada_y_agencia(ctx, rol, actor, agencia, estado):
    ctx.como(rol, id_interno=actor, agencia=agencia)
    ctx.fake("obtener_jornada", JORNADA)
    ctx.fake("autorizadores_dotacion", [])
    respuesta = ctx.cliente.get(f"{BASE}/jornadas/55/autorizadores-dotacion")
    assert respuesta.status_code == estado
    assert not ctx.llamadas["autorizadores_dotacion"]


def test_confirmacion_falla_si_se_revoca_autorizacion(ctx: Contexto) -> None:
    preparar_confirmacion(ctx)
    ctx.fake("autorizadores_dotacion", [])
    respuesta = ctx.cliente.post(RUTA)
    assert respuesta.status_code == 403
    assert code(respuesta) == "AUTORIZADOR_NO_VALIDO"
    assert not ctx.llamadas["registrar_dotacion"]
