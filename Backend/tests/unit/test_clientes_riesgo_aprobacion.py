"""Pruebas unitarias de E5-06 (#58): evaluación de riesgo con aprobación y habilitación.

Sin base de datos real (monkeypatching de repositorio y general.valor).
"""

from datetime import UTC, date, datetime
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import Connection
from starlette.requests import Request

from app.core.api.errors import problema
from app.main import app
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.clientes import (
    aprobacion_riesgo,
    habilitacion,
    repository,
    router,
    service,
)
from app.modules.clientes.aprobacion_riesgo import (
    CODIGO_RIESGO,
    EvaluacionRiesgo,
    validar_aprobador_riesgo,
)
from app.modules.clientes.schemas import (
    ContenidoRiesgo,
    RiesgoCreate,
    RiesgoRegistrado,
)
from app.modules.parametros import general
from tests.sesion import USUARIO

HOY = date(2026, 11, 25)
MANEJADOR = EvaluacionRiesgo()
OBJETIVO = aprobacion_riesgo.objetivo(10)


def _assert_problema(
    exc: pytest.ExceptionInfo[HTTPException], status: int, code: str
) -> None:
    assert exc.value.status_code == status
    assert cast(dict[str, Any], exc.value.detail)["code"] == code


def _payload(**overrides: Any) -> RiesgoCreate:
    defaults: dict[str, Any] = {
        "nivel_riesgo_laft": "Bajo",
        "es_pep": False,
        "resultado_evaluacion": "Aprobado",
        "tiene_antecedentes": False,
        "id_tipo_antecedente": None,
        "observaciones": None,
    }
    defaults.update(overrides)
    return RiesgoCreate(**defaults)


def _contenido(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "nivelRiesgoLAFT": "Alto",
        "esPEP": True,
        "resultadoEvaluacion": "Aprobado",
        "tieneAntecedentes": False,
        "idTipoAntecedente": None,
        "observaciones": "Revisión PEP",
        "evaluador": 12,
        "direccionIp": "192.0.2.10",
    }
    defaults.update(overrides)
    return defaults


def _riesgo_row(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "id_evaluacion": 25,
        "id_cliente": 10,
        "nivel_riesgo_laft": "Bajo",
        "es_pep": False,
        "resultado_evaluacion": "Aprobado",
        "fecha_evaluacion": datetime(2026, 11, 25, 12, tzinfo=UTC),
        "evaluador": 12,
        "tiene_antecedentes": False,
        "id_tipo_antecedente": None,
        "observaciones": None,
        "es_vigente": True,
        "vigente_hasta": date(2029, 11, 25),
        "id_solicitud": None,
        "estado_cliente": "Activo",
    }
    defaults.update(overrides)
    return defaults


def _request() -> Request:
    return Request({"type": "http", "client": ("192.0.2.10", 1), "headers": []})


# ---------------------------------------------------------------------------
# Tarea 1 y 2: Aprobación para PEP, Alto o Rechazado vs Directo (201)
# ---------------------------------------------------------------------------


@pytest.fixture
def mocks_servicio(monkeypatch):
    conn = MagicMock()
    cliente = {"id_cliente": 10, "estado": "Activo"}
    monkeypatch.setattr(
        service, "_validar_cliente_existe", lambda _c, _i, **_k: cliente
    )
    monkeypatch.setattr(service, "_validar_cliente_no_eliminado", lambda _cl, _i: None)
    monkeypatch.setattr(general, "valor", lambda _c, _k, _f: 36)
    insertar = MagicMock(return_value=_riesgo_row())
    monkeypatch.setattr(repository, "insertar_evaluacion_riesgo", insertar)
    monkeypatch.setattr(service, "activar_si_cumple", lambda *args, **kwargs: False)
    return conn, insertar


@pytest.mark.parametrize(
    "payload_cambios",
    [
        {"es_pep": True},
        {"nivel_riesgo_laft": "Alto"},
        {"resultado_evaluacion": "Rechazado"},
        {
            "es_pep": True,
            "nivel_riesgo_laft": "Alto",
            "resultado_evaluacion": "Rechazado",
        },
    ],
)
def test_pep_alto_o_rechazado_envia_a_cola_y_no_se_inserta(
    mocks_servicio, payload_cambios
):
    conn, insertar = mocks_servicio
    solicitar = MagicMock(return_value=SolicitudAceptada(id_solicitud=99))
    payload = _payload(**payload_cambios)

    resultado = service.registrar_evaluacion_riesgo(
        cast(Connection, conn),
        10,
        payload,
        12,
        "192.0.2.10",
        solicitar=solicitar,
    )

    assert isinstance(resultado, SolicitudAceptada)
    assert resultado.id_solicitud == 99
    insertar.assert_not_called()
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()

    contenido_enviado = solicitar.call_args.args[0]
    assert contenido_enviado["evaluador"] == 12
    assert contenido_enviado["direccionIp"] == "192.0.2.10"
    assert contenido_enviado["esPEP"] == payload.es_pep
    assert contenido_enviado["nivelRiesgoLAFT"] == payload.nivel_riesgo_laft
    assert contenido_enviado["resultadoEvaluacion"] == payload.resultado_evaluacion


def test_evaluacion_directa_bajo_aprobado_inserta_y_audita(
    mocks_servicio, eventos_auditados
):
    conn, insertar = mocks_servicio
    payload = _payload(
        nivel_riesgo_laft="Bajo", es_pep=False, resultado_evaluacion="Aprobado"
    )

    resultado = service.registrar_evaluacion_riesgo(
        cast(Connection, conn),
        10,
        payload,
        12,
        "192.0.2.10",
    )

    assert isinstance(resultado, RiesgoRegistrado)
    assert resultado.id_evaluacion == 25
    assert resultado.vigente_hasta == date(2029, 11, 25)
    assert resultado.id_solicitud is None
    insertar.assert_called_once()
    conn.commit.assert_called_once()

    evento = next(
        (e for e in eventos_auditados if e.accion == "CLI_RIESGO_EVALUADO"), None
    )
    assert evento is not None
    assert evento.resultado == "Exitoso"
    assert evento.tabla == "Clientes.RiesgoCliente"
    assert "Nivel=Bajo; PEP=no; Resultado=Aprobado" in evento.descripcion


def test_requiere_aprobacion_sin_servicio_solicitar_falla(mocks_servicio):
    conn, insertar = mocks_servicio
    payload = _payload(nivel_riesgo_laft="Alto")
    with pytest.raises(RuntimeError, match="E0-08"):
        service.registrar_evaluacion_riesgo(
            cast(Connection, conn),
            10,
            payload,
            12,
            "192.0.2.10",
            solicitar=None,
        )
    insertar.assert_not_called()


# ---------------------------------------------------------------------------
# Router: 202 con SolicitudAceptada, 201 directo y EVALUACION_PENDIENTE
# ---------------------------------------------------------------------------


def test_router_devuelve_202_cuando_requiere_aprobacion(monkeypatch):
    monkeypatch.setattr(
        service,
        "registrar_evaluacion_riesgo",
        MagicMock(return_value=SolicitudAceptada(id_solicitud=42)),
    )
    usuario = USUARIO
    respuesta = router.registrar_evaluacion_riesgo(
        10,
        _payload(es_pep=True),
        _request(),
        Response(),
        usuario,
        12,
        MagicMock(),
    )
    assert isinstance(respuesta, Response)
    assert respuesta.status_code == 202
    assert b'"idSolicitud":42' in respuesta.body
    assert b'"requiereAprobacion":true' in respuesta.body


def test_router_devuelve_201_en_registro_directo(monkeypatch):
    riesgo = RiesgoRegistrado(**_riesgo_row())
    monkeypatch.setattr(
        service,
        "registrar_evaluacion_riesgo",
        MagicMock(return_value=riesgo),
    )
    respuesta = router.registrar_evaluacion_riesgo(
        10,
        _payload(),
        _request(),
        Response(),
        USUARIO,
        12,
        MagicMock(),
    )
    assert isinstance(respuesta, RiesgoRegistrado)
    assert respuesta.id_evaluacion == 25


def test_solicitar_riesgo_traduce_solicitud_pendiente_a_409(monkeypatch):
    cola = MagicMock()
    cola.solicitar.side_effect = problema(409, "SOLICITUD_YA_PENDIENTE", "Ya existe")
    monkeypatch.setattr(router.aprobaciones, "servicio", lambda: cola)
    monkeypatch.setattr(router.aprobaciones, "actual", lambda _u: MagicMock())
    monkeypatch.setattr(router.aprobaciones, "contexto", lambda _r, _u: MagicMock())

    solicitar = router._solicitar_riesgo(_request(), USUARIO, 10)
    with pytest.raises(HTTPException) as exc:
        solicitar(_contenido())
    _assert_problema(exc, 409, "EVALUACION_PENDIENTE")
    assert cola.solicitar.call_args.args[1] == CODIGO_RIESGO
    obj = cola.solicitar.call_args.args[2]
    assert (obj.tipo, obj.id, obj.agencia) == ("ClienteRiesgo", "10", None)


# ---------------------------------------------------------------------------
# Tarea 1: Manejador (preparar, version, aplicar, validar_aprobador)
# ---------------------------------------------------------------------------


def test_contenido_riesgo_validacion_pydantic():
    base = _contenido()
    assert ContenidoRiesgo.model_validate(base).evaluador == 12

    # Extra field
    with pytest.raises(ValidationError):
        ContenidoRiesgo.model_validate({**base, "campoExtra": "no"})

    # Evaluador <= 0
    with pytest.raises(ValidationError):
        ContenidoRiesgo.model_validate({**base, "evaluador": 0})

    # Falta direccionIp
    sin_ip = {k: v for k, v in base.items() if k != "direccionIp"}
    with pytest.raises(ValidationError):
        ContenidoRiesgo.model_validate(sin_ip)


@pytest.fixture
def bd_manejador(monkeypatch):
    estado: dict[str, Any] = {
        "cliente": {"id_cliente": 10, "estado": "Activo"},
        "vigente": _riesgo_row(),
        "insertar": MagicMock(),
        "activar": MagicMock(return_value=False),
    }
    monkeypatch.setattr(
        repository, "bloquear_cliente", lambda _c, _i: estado["cliente"]
    )
    monkeypatch.setattr(service, "_validar_cliente_no_eliminado", lambda _cl, _i: None)
    monkeypatch.setattr(
        repository,
        "listar_evaluaciones_riesgo",
        lambda _c, _i, solo_vigente=False, **_k: (
            [estado["vigente"]] if estado["vigente"] and solo_vigente else []
        ),
    )
    monkeypatch.setattr(repository, "insertar_evaluacion_riesgo", estado["insertar"])
    monkeypatch.setattr(aprobacion_riesgo, "activar_si_cumple", estado["activar"])
    monkeypatch.setattr(general, "valor", lambda _c, _k, _f: 12)
    return estado


def test_manejador_contenido_invalido_422():
    with pytest.raises(HTTPException) as exc:
        MANEJADOR.preparar(MagicMock(), OBJETIVO, {"campoInvalido": 123}, HOY)
    _assert_problema(exc, 422, "CONTENIDO_INVALIDO")

    with pytest.raises(HTTPException) as exc2:
        MANEJADOR.preparar(MagicMock(), OBJETIVO, _contenido(evaluador=0), HOY)
    _assert_problema(exc2, 422, "CONTENIDO_INVALIDO")

    with pytest.raises(HTTPException) as exc3:
        MANEJADOR.aplicar(
            MagicMock(), OBJETIVO, {**_contenido(), "extra": "no"}, "user", 1
        )
    _assert_problema(exc3, 422, "CONTENIDO_INVALIDO")


def test_manejador_preparar_con_antes_y_despues(bd_manejador):
    contenido = _contenido(
        nivelRiesgoLAFT="Alto", esPEP=True, resultadoEvaluacion="Aprobado"
    )
    plan = MANEJADOR.preparar(MagicMock(), OBJETIVO, contenido, HOY)

    assert plan.antes == {
        "nivel": "Bajo",
        "pep": False,
        "resultado": "Aprobado",
        "vigenteHasta": "2029-11-25",
    }
    assert plan.despues["nivelRiesgoLAFT"] == "Alto"
    assert plan.despues["esPEP"] is True
    assert plan.version == MANEJADOR.version(MagicMock(), OBJETIVO)


def test_manejador_preparar_sin_evaluacion_vigente_antes_vacio(bd_manejador):
    bd_manejador["vigente"] = None
    plan = MANEJADOR.preparar(MagicMock(), OBJETIVO, _contenido(), HOY)
    assert plan.antes == {}


def test_manejador_version_cambia_al_cambiar_vigente_o_estado(bd_manejador):
    v_inicial = MANEJADOR.version(MagicMock(), OBJETIVO)

    # Cambiar id de evaluación vigente
    bd_manejador["vigente"] = _riesgo_row(id_evaluacion=999)
    assert MANEJADOR.version(MagicMock(), OBJETIVO) != v_inicial

    # Cambiar estado del cliente
    bd_manejador["vigente"] = _riesgo_row(id_evaluacion=25)
    bd_manejador["cliente"] = {"id_cliente": 10, "estado": "Bloqueado"}
    assert MANEJADOR.version(MagicMock(), OBJETIVO) != v_inicial


def test_manejador_aplicar_inserta_con_id_solicitud_y_llama_activacion(bd_manejador):
    conn = MagicMock()
    contenido = _contenido(evaluador=33, direccionIp="10.0.0.1")

    MANEJADOR.aplicar(conn, OBJETIVO, contenido, "solicitante_prueba", 77)

    bd_manejador["insertar"].assert_called_once()
    args, kwargs = bd_manejador["insertar"].call_args
    assert args[0] == conn
    assert args[1] == 10
    assert kwargs["id_solicitud"] == 77
    assert kwargs["evaluador"] == 33
    assert kwargs["direccion_ip"] == "10.0.0.1"
    assert kwargs["meses_vigencia"] == 12

    bd_manejador["activar"].assert_called_once()
    act_args, act_kwargs = bd_manejador["activar"].call_args
    assert act_args[0] == conn
    assert act_args[1] == 10
    assert act_kwargs["actor"] == 33
    assert act_kwargs["ip"] == "10.0.0.1"
    conn.commit.assert_not_called()


def test_validar_aprobador_incompatible(monkeypatch):
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn

    # CreadoPor coincide con id_interno
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "CreadoPor": 5
    }
    monkeypatch.setattr(aprobacion_riesgo, "get_engine", lambda _db: engine)

    with pytest.raises(HTTPException) as exc:
        validar_aprobador_riesgo(OBJETIVO, 5)
    _assert_problema(exc, 403, "APROBADOR_INCOMPATIBLE")

    # CreadoPor distinto de id_interno -> no lanza excepción
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "CreadoPor": 8
    }
    validar_aprobador_riesgo(OBJETIVO, 5)


# ---------------------------------------------------------------------------
# Tarea 3: activar_si_cumple
# ---------------------------------------------------------------------------


def test_activar_si_cumple_activa_con_historial_cuando_no_hay_motivos(monkeypatch):
    conn = MagicMock()
    # Cliente en estado Pendiente
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "Estado": "Pendiente"
    }
    conn.execute.return_value.rowcount = 1

    monkeypatch.setattr(
        habilitacion,
        "requisitos_cliente",
        lambda _c, _i, _f, _s=None: ["CLIENTE_NO_ACTIVO"],
    )
    historial = MagicMock()
    monkeypatch.setattr(repository, "insertar_historial_cliente", historial)

    resultado = habilitacion.activar_si_cumple(conn, 10, HOY, actor=12, ip="192.0.2.10")

    assert resultado is True
    historial.assert_called_once()
    h_kwargs = historial.call_args.kwargs
    assert h_kwargs["id_cliente"] == 10
    assert h_kwargs["tipo_operacion"] == "U"
    assert h_kwargs["campo"] == "Estado"
    assert h_kwargs["valor_anterior"] == "Pendiente"
    assert h_kwargs["valor_nuevo"] == "Activo"
    assert h_kwargs["modificado_por"] == 12
    assert h_kwargs["direccion_ip"] == "192.0.2.10"
    assert "Habilitado: requisitos cumplidos" in h_kwargs["observaciones"]
    conn.commit.assert_not_called()


def test_activar_si_cumple_ignora_archivos_no_exigidos(monkeypatch):
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "Estado": "Pendiente"
    }
    conn.execute.return_value.rowcount = 1

    monkeypatch.setattr(
        habilitacion,
        "requisitos_cliente",
        lambda _c, _i, _f, _s=None: ["CLIENTE_NO_ACTIVO", "ARCHIVOS_NO_EXIGIDOS"],
    )
    monkeypatch.setattr(repository, "insertar_historial_cliente", MagicMock())

    resultado = habilitacion.activar_si_cumple(conn, 10, HOY, actor=1, ip="1.1.1.1")
    assert resultado is True


@pytest.mark.parametrize(
    "motivos",
    [
        ["CLIENTE_NO_ACTIVO", "RIESGO_NO_APROBADO_VIGENTE"],
        ["CLIENTE_NO_ACTIVO", "ARCHIVO_OBLIGATORIO_FALTANTE:CED"],
        ["CLIENTE_NO_ACTIVO", "CONSENTIMIENTO_NO_VIGENTE"],
        ["CLIENTE_NO_ACTIVO", "ANTECEDENTE_IMPIDE_VINCULACION"],
    ],
)
def test_activar_si_cumple_no_activa_con_motivos_pendientes(monkeypatch, motivos):
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "Estado": "Pendiente"
    }

    monkeypatch.setattr(
        habilitacion, "requisitos_cliente", lambda _c, _i, _f, _s=None: motivos
    )
    historial = MagicMock()
    monkeypatch.setattr(repository, "insertar_historial_cliente", historial)

    resultado = habilitacion.activar_si_cumple(conn, 10, HOY, actor=1, ip="1.1.1.1")

    assert resultado is False
    historial.assert_not_called()


def test_activar_si_cumple_no_hace_nada_si_no_esta_pendiente():
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "Estado": "Activo"
    }

    resultado = habilitacion.activar_si_cumple(conn, 10, HOY, actor=1, ip="1.1.1.1")
    assert resultado is False


# ---------------------------------------------------------------------------
# Verificaciones del registro de operaciones y documentación OpenAPI
# ---------------------------------------------------------------------------


def test_operacion_riesgo_registrada_en_cola():
    operacion = registro_inicial().obtener("CLI-RIESGO", "ClienteRiesgo")
    assert operacion.codigo == "CLI-RIESGO"
    assert operacion.tipo_objetivo == "ClienteRiesgo"
    assert operacion.base == "cooperativa"
    assert operacion.roles_ejecucion == frozenset({"ADMIN", "ASESOR", "SUPERVISOR"})
    assert operacion.permiso_aprobacion == "clientes:aprobar"
    assert operacion.solicitud_directa is False
    assert operacion.tabla_auditada == "Clientes.RiesgoCliente"
    assert operacion.evento_ejecucion == "CLI_RIESGO_EVALUADO"
    assert operacion.validar_aprobador is not None


def test_openapi_documenta_201_y_202():
    ruta = app.openapi()["paths"]["/api/v1/clientes/{idCliente}/evaluaciones-riesgo"][
        "post"
    ]
    assert "201" in ruta["responses"]
    assert "202" in ruta["responses"]
    assert "409" in ruta["responses"]
    assert "422" in ruta["responses"]


def test_pep_aprobada_cuenta_mientras_la_cola_la_aplica(monkeypatch):
    # La cola escribe AprobacionAplicada DESPUÉS de aplicar: sin este caso, el cliente
    # nunca pasaría a Activo tras aprobarse una evaluación PEP o de riesgo Alto.
    from datetime import datetime as _dt

    fila = {
        "Estado": "Pendiente",
        "ConsentimientoDatos": True,
        "FechaConsentimiento": _dt(2026, 1, 1),
        "TipoCliente": "Natural",
        "IdEvaluacion": 9,
        "ResultadoEvaluacion": "Aprobado",
        "EsPEP": True,
        "NivelRiesgoLAFT": "Medio",
        "IdSolicitud": 55,
        "AntecedenteImpeditivo": 0,
    }
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = fila
    conn.execute.return_value.first.return_value = None  # aún sin AprobacionAplicada
    monkeypatch.setattr(habilitacion.general, "valor", lambda _c, _k, _f: False)
    sin = habilitacion.requisitos_cliente(conn, 10, HOY)
    con = habilitacion.requisitos_cliente(conn, 10, HOY, solicitud_en_aplicacion=55)
    assert "RIESGO_NO_APROBADO_VIGENTE" in sin
    assert "RIESGO_NO_APROBADO_VIGENTE" not in con
    otra = habilitacion.requisitos_cliente(conn, 10, HOY, solicitud_en_aplicacion=99)
    assert "RIESGO_NO_APROBADO_VIGENTE" in otra
