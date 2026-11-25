"""E5-04: cambios sensibles del cliente con aprobación de otra persona (CLI-EDITAR)."""

from datetime import date
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
from app.modules.clientes import aprobacion, repository, router, service
from app.modules.clientes.schemas import (
    CambiosSensibles,
    Cliente,
    ClienteUpdate,
    ContenidoEdicion,
)
from app.modules.parametros import general

HOY = date(2026, 11, 24)


def _fila(**cambios: Any) -> dict[str, Any]:
    return {
        "id_cliente": 10,
        "estado": "Activo",
        "tipo_cliente": "Natural",
        "identificacion": "1710034065",
        "tipo_documento": "C",
        "nombres": "María José",
        "apellidos": "López Pérez",
        "razon_social": None,
        "fecha_nacimiento": date(1990, 5, 14),
        "genero": "F",
        "estado_civil": "Soltero",
        "email": "maria@correo.ec",
        **cambios,
    }


def _cliente(**cambios: Any) -> Cliente:
    fila = _fila(**cambios)
    return Cliente(
        **{k: v for k, v in fila.items() if k != "estado"},
        estado=fila["estado"],
        nombre_comercial=None,
        id_actividad_economica=None,
        codigo_pais_nacionalidad="ECU",
        telefono_convencional=None,
        telefono_celular="0991234567",
        consentimiento_datos=True,
        fecha_consentimiento="2026-11-03T15:00:00Z",
        fecha_registro="2026-11-03T15:00:00Z",
        creado_por=1,
        direcciones=[],
    )


def _contenido(**cambios: Any) -> dict[str, Any]:
    return service.congelar_contenido(
        ContenidoEdicion(
            cambios=CambiosSensibles(**cambios),
            id_archivo_respaldo=None,
            modificado_por=12,
            direccion_ip="192.0.2.10",
        )
    )


def _assert_problema(exc: pytest.ExceptionInfo[HTTPException], status: int, code: str):
    assert exc.value.status_code == status
    assert cast(dict[str, Any], exc.value.detail)["code"] == code


# ---------------------------------------------------------------------------
# Servicio: clasificación ordinario / sensible
# ---------------------------------------------------------------------------


@pytest.fixture
def conn_edicion(monkeypatch):
    conn = MagicMock()
    actual = {"cliente": _cliente()}
    monkeypatch.setattr(
        service, "_cliente_bloqueado", lambda _conn, _id: actual["cliente"]
    )
    guardar = MagicMock(side_effect=AssertionError("no debe escribir"))
    monkeypatch.setattr(service, "_guardar_cambios_cliente", guardar)
    return conn, actual


def test_cambio_sensible_va_a_la_cola_sin_escribir(conn_edicion):
    conn, _ = conn_edicion
    solicitar = MagicMock(return_value=SolicitudAceptada(id_solicitud=77))
    resultado = service.editar_cliente(
        cast(Connection, conn),
        10,
        ClienteUpdate(apellidos="López Andrade"),
        12,
        "192.0.2.10",
        solicitar,
    )
    assert resultado == SolicitudAceptada(id_solicitud=77)
    conn.rollback.assert_called_once()  # El bloqueo se libera antes de llamar a la cola.
    conn.commit.assert_not_called()
    assert solicitar.call_args.args[0] == {
        "cambios": {"apellidos": "López Andrade"},
        "idArchivoRespaldo": None,
        "modificadoPor": 12,
        "direccionIp": "192.0.2.10",
    }


def test_correo_se_compara_y_congela_en_minusculas(conn_edicion):
    conn, _ = conn_edicion
    solicitar = MagicMock(return_value=SolicitudAceptada(id_solicitud=1))
    service.editar_cliente(
        cast(Connection, conn),
        10,
        ClienteUpdate(email="Nuevo@Correo.EC"),
        12,
        "192.0.2.10",
        solicitar,
    )
    assert solicitar.call_args.args[0]["cambios"] == {"email": "nuevo@correo.ec"}


def test_mismo_correo_con_mayusculas_no_es_un_cambio(conn_edicion):
    conn, _ = conn_edicion
    solicitar = MagicMock()
    resultado = service.editar_cliente(
        cast(Connection, conn),
        10,
        ClienteUpdate(email="MARIA@correo.ec"),
        12,
        "192.0.2.10",
        solicitar,
    )
    assert isinstance(resultado, Cliente)
    solicitar.assert_not_called()


def test_cambio_mixto_se_rechaza(conn_edicion):
    conn, _ = conn_edicion
    with pytest.raises(HTTPException) as exc:
        service.editar_cliente(
            cast(Connection, conn),
            10,
            ClienteUpdate(apellidos="Otro", telefono_celular="0987654321"),
            12,
            "192.0.2.10",
            MagicMock(),
        )
    _assert_problema(exc, 422, "CAMBIO_MIXTO")
    conn.rollback.assert_called()


def test_respaldo_sin_cambio_sensible_no_aplica(conn_edicion):
    conn, _ = conn_edicion
    with pytest.raises(HTTPException) as exc:
        service.editar_cliente(
            cast(Connection, conn),
            10,
            ClienteUpdate(telefono_celular="0987654321", id_archivo_respaldo=5),
            12,
            "192.0.2.10",
            MagicMock(),
        )
    _assert_problema(exc, 422, "RESPALDO_NO_APLICA")


@pytest.mark.parametrize(
    ("estado", "status", "code"),
    [
        ("Bloqueado", 423, "CLIENTE_BLOQUEADO"),
        ("Eliminado", 409, "CLIENTE_NO_EDITABLE"),
    ],
)
def test_cliente_bloqueado_o_eliminado_no_solicita(conn_edicion, estado, status, code):
    conn, actual = conn_edicion
    actual["cliente"] = _cliente(estado=estado)
    solicitar = MagicMock()
    with pytest.raises(HTTPException) as exc:
        service.editar_cliente(
            cast(Connection, conn),
            10,
            ClienteUpdate(apellidos="Otro"),
            12,
            "192.0.2.10",
            solicitar,
        )
    _assert_problema(exc, status, code)
    solicitar.assert_not_called()


def test_cambio_ordinario_audita_solo_nombres_de_campos(monkeypatch, eventos_auditados):
    conn = MagicMock()
    monkeypatch.setattr(service, "_cliente_bloqueado", lambda _c, _i: _cliente())
    monkeypatch.setattr(
        service,
        "_guardar_cambios_cliente",
        lambda _c, actual, cambios, **_k: actual.model_copy(update=cambios),
    )
    resultado = service.editar_cliente(
        cast(Connection, conn),
        10,
        ClienteUpdate(telefono_celular="0987654321"),
        12,
        "192.0.2.10",
    )
    assert isinstance(resultado, Cliente)
    assert resultado.telefono_celular == "0987654321"
    (evento,) = eventos_auditados
    assert evento.accion == "CLI_EDITADO"
    assert evento.descripcion == "Campos: telefono_celular"
    assert "0987654321" not in evento.descripcion


@pytest.mark.parametrize(
    "campo", ["fechaNacimiento", "tipoDocumento", "identificacion"]
)
def test_campos_sensibles_nuevos_no_admiten_null(campo):
    with pytest.raises(ValidationError):
        ClienteUpdate.model_validate({campo: None})


def test_contenido_sin_cambios_o_con_campo_ordinario_se_rechaza():
    base = {"idArchivoRespaldo": None, "modificadoPor": 12, "direccionIp": "1.1.1.1"}
    with pytest.raises(ValidationError):
        ContenidoEdicion.model_validate({**base, "cambios": {}})
    with pytest.raises(ValidationError):
        ContenidoEdicion.model_validate(
            {**base, "cambios": {"telefonoCelular": "0987654321"}}
        )
    with pytest.raises(ValidationError):
        ContenidoEdicion.model_validate({**base, "cambios": {"estado": "Activo"}})


# ---------------------------------------------------------------------------
# Router: 202 y CAMBIO_PENDIENTE
# ---------------------------------------------------------------------------


def _request() -> Request:
    return Request({"type": "http", "client": ("192.0.2.10", 1), "headers": []})


def test_router_devuelve_202_con_la_solicitud(monkeypatch):
    monkeypatch.setattr(
        service,
        "editar_cliente",
        MagicMock(return_value=SolicitudAceptada(id_solicitud=9)),
    )
    usuario = MagicMock()
    monkeypatch.setattr(router, "puede_ver_direcciones", lambda _u: True)
    respuesta = router.editar_cliente(
        10,
        ClienteUpdate(apellidos="Otro"),
        _request(),
        Response(),
        usuario,
        12,
        MagicMock(),
    )
    assert isinstance(respuesta, Response)
    assert respuesta.status_code == 202
    assert respuesta.body == (
        b'{"idSolicitud":9,"estado":"Pendiente","requiereAprobacion":true}'
    )


@pytest.mark.parametrize(
    ("code", "esperado"),
    [("SOLICITUD_YA_PENDIENTE", "CAMBIO_PENDIENTE"), ("SIN_PERMISO", "SIN_PERMISO")],
)
def test_solicitar_traduce_solo_la_pendiente(monkeypatch, code, esperado):
    cola = MagicMock()
    cola.solicitar.side_effect = problema(
        409 if code != "SIN_PERMISO" else 403, code, "x"
    )
    monkeypatch.setattr(router.aprobaciones, "servicio", lambda: cola)
    monkeypatch.setattr(router.aprobaciones, "actual", lambda _u: MagicMock())
    monkeypatch.setattr(router.aprobaciones, "contexto", lambda _r, _u: MagicMock())
    solicitar = router._solicitar_cambio(_request(), MagicMock(), 10)
    with pytest.raises(HTTPException) as exc:
        solicitar(_contenido(apellidos="Otro"))
    assert cast(dict[str, Any], exc.value.detail)["code"] == esperado
    objetivo = cola.solicitar.call_args.args[2]
    assert (objetivo.tipo, objetivo.id, objetivo.agencia) == ("Cliente", "10", None)
    assert cola.solicitar.call_args.args[1] == "CLI-EDITAR"


def test_operacion_registrada_en_la_cola():
    operacion = registro_inicial().obtener("CLI-EDITAR", "Cliente")
    assert operacion.base == "cooperativa"
    assert operacion.roles_ejecucion == frozenset({"ADMIN", "ASESOR"})
    assert operacion.permiso_aprobacion == "clientes:aprobar"
    assert operacion.evento_ejecucion == "CLI_CAMBIO_SENSIBLE"
    assert operacion.solicitud_directa is False


def test_openapi_documenta_202():
    ruta = app.openapi()["paths"]["/api/v1/clientes/{idCliente}"]["patch"]
    assert "202" in ruta["responses"]


# ---------------------------------------------------------------------------
# Manejador de la cola: preparar, versión y aplicar
# ---------------------------------------------------------------------------


@pytest.fixture
def bd(monkeypatch):
    estado: dict[str, Any] = {
        "fila": _fila(),
        "duplicado": False,
        "archivo": True,
        "exige": False,
    }
    monkeypatch.setattr(
        repository, "bloquear_datos_sensibles", lambda _c, _i: estado["fila"]
    )
    monkeypatch.setattr(
        repository,
        "otro_cliente_con_identificacion",
        lambda _c, _ident, _id: estado["duplicado"],
    )
    monkeypatch.setattr(
        repository, "archivo_respaldo_valido", lambda _c, _i, _a: estado["archivo"]
    )
    monkeypatch.setattr(general, "valor", lambda _c, _clave, _f: estado["exige"])
    estado["actualizar"] = MagicMock()
    estado["historial"] = MagicMock()
    monkeypatch.setattr(repository, "actualizar_cliente_sensible", estado["actualizar"])
    monkeypatch.setattr(repository, "insertar_historial_cliente", estado["historial"])
    monkeypatch.setattr(aprobacion, "hoy", lambda: HOY)
    return estado


MANEJADOR = aprobacion.EdicionCliente()
OBJETIVO = aprobacion.objetivo(10)


def test_preparar_congela_solo_lo_que_cambia(bd):
    plan = MANEJADOR.preparar(
        MagicMock(),
        OBJETIVO,
        _contenido(apellidos="López Andrade", nombres="María José"),
        HOY,
    )
    assert plan.antes == {"apellidos": "López Pérez"}
    assert plan.despues == {"apellidos": "López Andrade"}
    assert plan.contenido["modificadoPor"] == 12
    assert plan.version == MANEJADOR.version(MagicMock(), OBJETIVO)


def test_version_ignora_ordinarios_y_detecta_sensibles(bd):
    inicial = MANEJADOR.version(MagicMock(), OBJETIVO)
    bd["fila"] = _fila(estado_civil="Casado")  # Campo ordinario: no invalida.
    assert MANEJADOR.version(MagicMock(), OBJETIVO) == inicial
    bd["fila"] = _fila(apellidos="Otro")
    assert MANEJADOR.version(MagicMock(), OBJETIVO) != inicial
    bd["fila"] = _fila(estado="Bloqueado")
    assert MANEJADOR.version(MagicMock(), OBJETIVO) != inicial


@pytest.mark.parametrize(
    ("fila", "cambios", "status", "code"),
    [
        ({}, {"apellidos": "López Pérez"}, 409, "SOLICITUD_DESACTUALIZADA"),
        ({"estado": "Bloqueado"}, {"apellidos": "Otro"}, 423, "CLIENTE_BLOQUEADO"),
        ({"estado": "Eliminado"}, {"apellidos": "Otro"}, 409, "CLIENTE_NO_EDITABLE"),
        ({}, {"razon_social": "Empresa"}, 422, "TIPO_PERSONA_INVALIDO"),
        ({}, {"fecha_nacimiento": HOY}, 422, "FECHA_NACIMIENTO_INVALIDA"),
        ({}, {"identificacion": "1710034066"}, 422, "DOCUMENTO_INVALIDO"),
        ({}, {"tipo_documento": "R"}, 422, "DOCUMENTO_INVALIDO"),
    ],
)
def test_preparar_rechaza(bd, fila, cambios, status, code):
    bd["fila"] = _fila(**fila)
    with pytest.raises(HTTPException) as exc:
        MANEJADOR.preparar(MagicMock(), OBJETIVO, _contenido(**cambios), HOY)
    _assert_problema(exc, status, code)


def test_preparar_rechaza_documento_de_otro_cliente(bd):
    bd["duplicado"] = True
    with pytest.raises(HTTPException) as exc:
        MANEJADOR.preparar(
            MagicMock(), OBJETIVO, _contenido(identificacion="1713175071"), HOY
        )
    _assert_problema(exc, 409, "CLIENTE_DUPLICADO")


def test_cliente_inexistente(bd):
    bd["fila"] = None
    with pytest.raises(HTTPException) as exc:
        MANEJADOR.preparar(MagicMock(), OBJETIVO, _contenido(apellidos="Otro"), HOY)
    _assert_problema(exc, 404, "CLIENTE_NO_ENCONTRADO")


def test_contenido_alterado_es_422(bd):
    contenido = {**_contenido(apellidos="Otro"), "extra": 1}
    with pytest.raises(HTTPException) as exc:
        MANEJADOR.preparar(MagicMock(), OBJETIVO, contenido, HOY)
    _assert_problema(exc, 422, "CONTENIDO_INVALIDO")


@pytest.mark.parametrize(
    ("exige", "archivo", "id_archivo", "status", "code"),
    [
        (True, True, None, 422, "RESPALDO_REQUERIDO"),
        (False, None, 5, 503, "EVIDENCIA_NO_DISPONIBLE"),
        (False, False, 5, 422, "RESPALDO_NO_VALIDO"),
        ("si", True, None, 503, "PARAMETRO_INVALIDO"),
    ],
)
def test_respaldo_de_cambio_de_nombre(bd, exige, archivo, id_archivo, status, code):
    bd["exige"], bd["archivo"] = exige, archivo
    contenido = {**_contenido(apellidos="Otro"), "idArchivoRespaldo": id_archivo}
    with pytest.raises(HTTPException) as exc:
        MANEJADOR.preparar(MagicMock(), OBJETIVO, contenido, HOY)
    _assert_problema(exc, status, code)


def test_respaldo_valido_o_no_exigido(bd):
    bd["exige"] = True
    contenido = {**_contenido(apellidos="Otro"), "idArchivoRespaldo": 5}
    assert MANEJADOR.preparar(MagicMock(), OBJETIVO, contenido, HOY).despues
    bd["exige"] = False
    assert MANEJADOR.preparar(
        MagicMock(), OBJETIVO, _contenido(apellidos="Otro"), HOY
    ).despues


def test_correo_no_exige_respaldo(bd):
    bd["exige"] = True
    plan = MANEJADOR.preparar(
        MagicMock(), OBJETIVO, _contenido(email="nuevo@correo.ec"), HOY
    )
    assert plan.despues == {"email": "nuevo@correo.ec"}


def test_aplicar_actualiza_e_historial_enlaza_la_solicitud(bd):
    conn = MagicMock()
    MANEJADOR.aplicar(
        conn,
        OBJETIVO,
        _contenido(apellidos="López Andrade", email="nuevo@correo.ec"),
        "user_01",
        55,
    )
    bd["actualizar"].assert_called_once_with(
        conn, 10, {"apellidos": "López Andrade", "email": "nuevo@correo.ec"}
    )
    filas = [c.kwargs for c in bd["historial"].call_args_list]
    assert {f["campo"] for f in filas} == {"Apellidos", "Email"}
    for fila in filas:
        assert fila["id_solicitud"] == 55
        assert fila["modificado_por"] == 12  # El asesor que pidió el cambio.
        assert fila["direccion_ip"] == "192.0.2.10"
        assert fila["tipo_operacion"] == "U"
        assert "solicitud 55" in fila["observaciones"]
    apellido = next(f for f in filas if f["campo"] == "Apellidos")
    assert (apellido["valor_anterior"], apellido["valor_nuevo"]) == (
        "López Pérez",
        "López Andrade",
    )


def test_aplicar_revalida_el_estado_actual(bd):
    bd["fila"] = _fila(estado="Bloqueado")
    with pytest.raises(HTTPException) as exc:
        MANEJADOR.aplicar(MagicMock(), OBJETIVO, _contenido(apellidos="Otro"), "u", 1)
    _assert_problema(exc, 423, "CLIENTE_BLOQUEADO")
    bd["actualizar"].assert_not_called()


def test_fecha_de_nacimiento_se_guarda_en_iso(bd):
    MANEJADOR.aplicar(
        MagicMock(), OBJETIVO, _contenido(fecha_nacimiento=date(1991, 1, 2)), "u", 3
    )
    (llamada,) = bd["historial"].call_args_list
    assert llamada.kwargs["valor_nuevo"] == "1991-01-02"
    assert bd["actualizar"].call_args.args[2] == {"fecha_nacimiento": date(1991, 1, 2)}


def test_sql_de_cambio_de_correo_borra_la_verificacion():
    conn = MagicMock()
    conn.execute.return_value.rowcount = 1
    repository.actualizar_cliente_sensible(conn, 10, {"email": "nuevo@correo.ec"})
    sql = str(conn.execute.call_args.args[0])
    params = conn.execute.call_args.args[1]
    assert "EmailVerificadoPor = CASE WHEN :enviado_email = 1 THEN NULL" in sql
    assert "FechaEmailVerificado = CASE WHEN :enviado_email = 1 THEN NULL" in sql
    assert params["enviado_email"] is True and params["enviado_nombres"] is False
    assert "nuevo@correo.ec" not in sql


def test_sql_sensible_exige_una_fila():
    conn = MagicMock()
    conn.execute.return_value.rowcount = 0
    with pytest.raises(RuntimeError):
        repository.actualizar_cliente_sensible(conn, 10, {"nombres": "X"})
