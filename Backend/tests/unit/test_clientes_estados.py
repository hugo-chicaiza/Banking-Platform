"""Pruebas unitarias de E5-07 (#388): estados del cliente con aprobación, motivo y anonimización.

Sin base de datos real (monkeypatching de repositorio y funciones, conexión MagicMock, sesión de tests/sesion.py).
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
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.clientes import (
    aprobacion_estado,
    habilitacion,
    repository,
    router,
    service,
)
from app.modules.clientes.aprobacion_estado import (
    CODIGO_ESTADO,
    MANEJADOR_ESTADO,
    validar_aprobador_estado,
)
from app.modules.clientes.schemas import (
    Cliente,
    ClienteEstadoUpdate,
)
from tests.sesion import USUARIO

HOY = date(2026, 11, 25)
OBJETIVO = aprobacion_estado.objetivo(10)


def _assert_problema(
    exc: pytest.ExceptionInfo[HTTPException], status: int, code: str
) -> None:
    assert exc.value.status_code == status
    assert cast(dict[str, Any], exc.value.detail)["code"] == code


def _request() -> Request:
    return Request({"type": "http", "client": ("192.0.2.10", 1), "headers": []})


def _cliente_row(**overrides: Any) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "id_cliente": 10,
        "identificacion": "1710034065",
        "tipo_documento": "C",
        "tipo_cliente": "Natural",
        "nombres": "Juan",
        "apellidos": "Pérez",
        "razon_social": None,
        "nombre_comercial": None,
        "id_actividad_economica": 1,
        "fecha_nacimiento": date(1990, 1, 1),
        "genero": "M",
        "estado_civil": "Soltero",
        "codigo_pais_nacionalidad": "ECU",
        "telefono_convencional": None,
        "telefono_celular": "0991234567",
        "email": "juan.perez@correo.ec",
        "consentimiento_datos": True,
        "fecha_consentimiento": datetime(2026, 1, 1, tzinfo=UTC),
        "estado": "Activo",
        "motivo_estado": None,
        "fecha_registro": datetime(2026, 1, 1, tzinfo=UTC),
        "creado_por": 1,
        "direcciones": [],
        "email_verificado": False,
        "fecha_email_verificado": None,
        "id_agencia_registro": None,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Tarea 1 y 2: Sin aprobación (200) vs Con aprobación (202)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origen", "destino"),
    [
        ("Activo", "Inactivo"),
        ("Activo", "Suspendido"),
        ("Inactivo", "Activo"),
        ("Suspendido", "Activo"),
    ],
)
def test_cambio_estado_sin_aprobacion_200_inactivo_suspendido_reactivar(
    monkeypatch, eventos_auditados, origen, destino
):
    conn = MagicMock()
    actual = _cliente_row(estado=origen)
    actualizado = _cliente_row(estado=destino, motivo_estado="Pausa temporal")

    monkeypatch.setattr(repository, "bloquear_cliente", lambda _c, _i: actual)
    monkeypatch.setattr(service, "_cliente_bloqueado", lambda _c, _i: Cliente(**actual))
    monkeypatch.setattr(
        service, "obtener_cliente", lambda _c, _i: Cliente(**actualizado)
    )
    actualizar_mock = MagicMock()
    monkeypatch.setattr(repository, "actualizar_estado_cliente", actualizar_mock)
    insertar_hist_mock = MagicMock()
    monkeypatch.setattr(repository, "insertar_historial_cliente", insertar_hist_mock)
    monkeypatch.setattr(service, "_validar_productos_cliente", lambda _c, _i: None)

    solicitar_mock = MagicMock()
    payload = ClienteEstadoUpdate(estado=destino, motivo="Pausa temporal")

    resultado = service.cambiar_estado_cliente(
        cast(Connection, conn),
        10,
        payload,
        12,
        "192.0.2.10",
        ("ASESOR",),
        solicitar=solicitar_mock,
    )

    assert isinstance(resultado, Cliente)
    assert resultado.estado == destino
    solicitar_mock.assert_not_called()
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    actualizar_mock.assert_called_once_with(conn, 10, destino, motivo="Pausa temporal")

    evento = next((e for e in eventos_auditados if e.accion == "CLI_ESTADO"), None)
    assert evento is not None
    assert evento.resultado == "Exitoso"
    assert evento.tabla == "Clientes.Cliente"
    assert evento.descripcion == f"Estado: {origen} -> {destino}"
    assert "Pausa temporal" not in evento.descripcion


@pytest.mark.parametrize(
    ("origen", "destino"),
    [
        ("Activo", "Bloqueado"),
        ("Bloqueado", "Activo"),
        ("Activo", "Eliminado"),
        ("Inactivo", "Eliminado"),
        ("Suspendido", "Eliminado"),
        ("Bloqueado", "Eliminado"),
        ("Pendiente", "Eliminado"),
    ],
)
def test_cambio_estado_con_aprobacion_202_bloquear_desbloquear_eliminar(
    monkeypatch, origen, destino
):
    conn = MagicMock()
    actual = _cliente_row(estado=origen)

    monkeypatch.setattr(repository, "bloquear_cliente", lambda _c, _i: actual)
    monkeypatch.setattr(service, "_cliente_bloqueado", lambda _c, _i: Cliente(**actual))
    actualizar_mock = MagicMock()
    monkeypatch.setattr(repository, "actualizar_estado_cliente", actualizar_mock)
    monkeypatch.setattr(service, "_validar_productos_cliente", lambda _c, _i: None)

    solicitar_mock = MagicMock(return_value=SolicitudAceptada(id_solicitud=88))
    payload = ClienteEstadoUpdate(estado=destino, motivo="Motivo de prueba")

    resultado = service.cambiar_estado_cliente(
        cast(Connection, conn),
        10,
        payload,
        12,
        "192.0.2.10",
        ("ASESOR",),
        solicitar=solicitar_mock,
    )

    assert isinstance(resultado, SolicitudAceptada)
    assert resultado.id_solicitud == 88
    solicitar_mock.assert_called_once()
    contenido = solicitar_mock.call_args.args[0]
    assert contenido["estado"] == destino
    assert contenido["motivo"] == "Motivo de prueba"
    assert contenido["modificadoPor"] == 12
    assert contenido["direccionIp"] == "192.0.2.10"

    actualizar_mock.assert_not_called()
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()


def test_requiere_aprobacion_sin_solicitar_falla(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(
        repository, "bloquear_cliente", lambda _c, _i: _cliente_row(estado="Activo")
    )
    monkeypatch.setattr(
        service,
        "_cliente_bloqueado",
        lambda _c, _i: Cliente(**_cliente_row(estado="Activo")),
    )
    payload = ClienteEstadoUpdate(estado="Bloqueado", motivo="Bloqueo preventivo")
    with pytest.raises(RuntimeError, match="E0-08"):
        service.cambiar_estado_cliente(
            cast(Connection, conn),
            10,
            payload,
            12,
            "192.0.2.10",
            ("ASESOR",),
            solicitar=None,
        )


# ---------------------------------------------------------------------------
# Tarea 1: Transición inválida y productos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origen", "destino"),
    [
        ("Activo", "Activo"),
        ("Bloqueado", "Bloqueado"),
        ("Inactivo", "Inactivo"),
        ("Inactivo", "Bloqueado"),
        ("Inactivo", "Suspendido"),
        ("Suspendido", "Bloqueado"),
        ("Suspendido", "Inactivo"),
        ("Eliminado", "Activo"),
        ("Eliminado", "Eliminado"),
        ("Pendiente", "Activo"),
        ("Pendiente", "Bloqueado"),
    ],
)
def test_transicion_invalida_repetir_o_fuera_de_matriz(monkeypatch, origen, destino):
    conn = MagicMock()
    monkeypatch.setattr(
        repository, "bloquear_cliente", lambda _c, _i: _cliente_row(estado=origen)
    )
    monkeypatch.setattr(
        service,
        "_cliente_bloqueado",
        lambda _c, _i: Cliente(**_cliente_row(estado=origen)),
    )
    payload = ClienteEstadoUpdate(estado=destino, motivo="Intento inválido")

    with pytest.raises(HTTPException) as exc:
        service.cambiar_estado_cliente(
            cast(Connection, conn),
            10,
            payload,
            12,
            "192.0.2.10",
            ("ASESOR",),
            solicitar=MagicMock(),
        )
    _assert_problema(exc, 409, "TRANSICION_INVALIDA")


def test_cliente_con_productos_antes_de_encolar_eliminado(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(
        repository, "bloquear_cliente", lambda _c, _i: _cliente_row(estado="Activo")
    )
    monkeypatch.setattr(
        service,
        "_cliente_bloqueado",
        lambda _c, _i: Cliente(**_cliente_row(estado="Activo")),
    )
    monkeypatch.setattr(
        repository,
        "cuentas_para_cambio_estado",
        lambda _c, _i: [{"estado": "Activa", "saldo": 100, "saldo_retenido": 0}],
    )

    solicitar_mock = MagicMock()
    payload = ClienteEstadoUpdate(estado="Eliminado", motivo="Eliminar con saldo")

    with pytest.raises(HTTPException) as exc:
        service.cambiar_estado_cliente(
            cast(Connection, conn),
            10,
            payload,
            12,
            "192.0.2.10",
            ("ADMIN",),
            solicitar=solicitar_mock,
        )
    _assert_problema(exc, 409, "CLIENTE_CON_PRODUCTOS")
    solicitar_mock.assert_not_called()
    conn.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# Router: 202 con SolicitudAceptada, 200 directo y CAMBIO_ESTADO_PENDIENTE
# ---------------------------------------------------------------------------


def test_router_devuelve_202_cuando_requiere_aprobacion(monkeypatch):
    monkeypatch.setattr(
        service,
        "cambiar_estado_cliente",
        MagicMock(return_value=SolicitudAceptada(id_solicitud=50)),
    )
    respuesta = router.cambiar_estado_cliente(
        10,
        ClienteEstadoUpdate(estado="Bloqueado", motivo="Bloqueo"),
        _request(),
        Response(),
        USUARIO,
        12,
        MagicMock(),
    )
    assert isinstance(respuesta, Response)
    assert respuesta.status_code == 202
    assert b'"idSolicitud":50' in respuesta.body
    assert b'"requiereAprobacion":true' in respuesta.body


def test_router_devuelve_200_en_cambio_directo(monkeypatch):
    cliente_esperado = Cliente(**_cliente_row(estado="Inactivo"))
    monkeypatch.setattr(
        service,
        "cambiar_estado_cliente",
        MagicMock(return_value=cliente_esperado),
    )
    respuesta = router.cambiar_estado_cliente(
        10,
        ClienteEstadoUpdate(estado="Inactivo", motivo="Inactivar"),
        _request(),
        Response(),
        USUARIO,
        12,
        MagicMock(),
    )
    assert isinstance(respuesta, Cliente)
    assert respuesta.estado == "Inactivo"


def test_solicitar_estado_traduce_solicitud_pendiente_a_409(monkeypatch):
    cola = MagicMock()
    cola.solicitar.side_effect = problema(409, "SOLICITUD_YA_PENDIENTE", "Ya existe")
    monkeypatch.setattr(router.aprobaciones, "servicio", lambda: cola)
    monkeypatch.setattr(router.aprobaciones, "actual", lambda _u: MagicMock())
    monkeypatch.setattr(router.aprobaciones, "contexto", lambda _r, _u: MagicMock())

    solicitar = router._solicitar_estado(_request(), USUARIO, 10)
    contenido = {
        "estado": "Bloqueado",
        "motivo": "Bloqueo",
        "modificadoPor": 12,
        "direccionIp": "192.0.2.10",
    }
    with pytest.raises(HTTPException) as exc:
        solicitar(contenido)
    _assert_problema(exc, 409, "CAMBIO_ESTADO_PENDIENTE")
    assert cola.solicitar.call_args.args[1] == CODIGO_ESTADO
    obj = cola.solicitar.call_args.args[2]
    assert (obj.tipo, obj.id, obj.agencia) == ("ClienteEstado", "10", None)


# ---------------------------------------------------------------------------
# Tarea 1: Validación Pydantic de motivo (máximo 300, mínimo 1, no solo espacios)
# ---------------------------------------------------------------------------


def test_motivo_301_caracteres_400():
    # Longitud máxima 300: 301 falla en validación Pydantic
    with pytest.raises(ValidationError):
        ClienteEstadoUpdate(estado="Inactivo", motivo="a" * 301)

    # 300 caracteres es válido
    valido = ClienteEstadoUpdate(estado="Inactivo", motivo="a" * 300)
    assert len(valido.motivo) == 300

    # Vacío falla
    with pytest.raises(ValidationError):
        ClienteEstadoUpdate(estado="Inactivo", motivo="")

    # Solo espacios falla
    with pytest.raises(ValidationError):
        ClienteEstadoUpdate(estado="Inactivo", motivo="    ")


# ---------------------------------------------------------------------------
# Tarea 2: Manejador (preparar, version, aplicar, validar_aprobador)
# ---------------------------------------------------------------------------


def test_manejador_contenido_invalido_422():
    conn = MagicMock()

    # Contenido con campos extra (extra="forbid")
    with pytest.raises(HTTPException) as exc1:
        MANEJADOR_ESTADO.preparar(
            conn,
            OBJETIVO,
            {
                "estado": "Bloqueado",
                "motivo": "Bloqueo",
                "modificadoPor": 12,
                "direccionIp": "192.0.2.10",
                "campoInvalido": 123,
            },
            HOY,
        )
    _assert_problema(exc1, 422, "CONTENIDO_INVALIDO")

    # modificado_por <= 0
    with pytest.raises(HTTPException) as exc2:
        MANEJADOR_ESTADO.preparar(
            conn,
            OBJETIVO,
            {
                "estado": "Bloqueado",
                "motivo": "Bloqueo",
                "modificadoPor": 0,
                "direccionIp": "192.0.2.10",
            },
            HOY,
        )
    _assert_problema(exc2, 422, "CONTENIDO_INVALIDO")

    # estado no permitido en cola (ej. Inactivo)
    with pytest.raises(HTTPException) as exc3:
        MANEJADOR_ESTADO.preparar(
            conn,
            OBJETIVO,
            {
                "estado": "Inactivo",
                "motivo": "Inactivar",
                "modificadoPor": 12,
                "direccionIp": "192.0.2.10",
            },
            HOY,
        )
    _assert_problema(exc3, 422, "CONTENIDO_INVALIDO")

    # En aplicar con contenido inválido
    with pytest.raises(HTTPException) as exc4:
        MANEJADOR_ESTADO.aplicar(
            conn,
            OBJETIVO,
            {"estado": "Bloqueado"},
            "user",
            1,
        )
    _assert_problema(exc4, 422, "CONTENIDO_INVALIDO")


def test_manejador_preparar_y_version(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(
        repository, "bloquear_cliente", lambda _c, _i: _cliente_row(estado="Activo")
    )
    monkeypatch.setattr(
        service,
        "_cliente_bloqueado",
        lambda _c, _i: Cliente(**_cliente_row(estado="Activo")),
    )

    contenido = {
        "estado": "Bloqueado",
        "motivo": "Bloqueo preventivo",
        "modificadoPor": 12,
        "direccionIp": "192.0.2.10",
    }
    plan = MANEJADOR_ESTADO.preparar(conn, OBJETIVO, contenido, HOY)

    assert plan.antes == {"estado": "Activo"}
    assert plan.despues == {"estado": "Bloqueado"}
    assert plan.version == MANEJADOR_ESTADO.version(conn, OBJETIVO)


def test_manejador_aplicar_bloqueado_guarda_estado_y_motivo(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(
        repository, "bloquear_cliente", lambda _c, _i: _cliente_row(estado="Activo")
    )
    monkeypatch.setattr(
        service,
        "_cliente_bloqueado",
        lambda _c, _i: Cliente(**_cliente_row(estado="Activo")),
    )
    actualizar_mock = MagicMock()
    monkeypatch.setattr(repository, "actualizar_estado_cliente", actualizar_mock)
    historial_mock = MagicMock()
    monkeypatch.setattr(repository, "insertar_historial_cliente", historial_mock)
    anonimizar_mock = MagicMock()
    monkeypatch.setattr(repository, "anonimizar_cliente", anonimizar_mock)

    contenido = {
        "estado": "Bloqueado",
        "motivo": "Bloqueo preventivo",
        "modificadoPor": 12,
        "direccionIp": "192.0.2.10",
    }
    MANEJADOR_ESTADO.aplicar(conn, OBJETIVO, contenido, "asesor1", 42)

    actualizar_mock.assert_called_once_with(
        conn, 10, "Bloqueado", motivo="Bloqueo preventivo (solicitud 42)"
    )
    historial_mock.assert_called_once()
    h_kwargs = historial_mock.call_args.kwargs
    assert h_kwargs["id_cliente"] == 10
    assert h_kwargs["campo"] == "Estado"
    assert h_kwargs["valor_anterior"] == "Activo"
    assert h_kwargs["valor_nuevo"] == "Bloqueado"
    assert h_kwargs["id_solicitud"] == 42
    assert h_kwargs["modificado_por"] == 12

    # Bloqueado NO llama a anonimizar
    anonimizar_mock.assert_not_called()
    conn.commit.assert_not_called()


def test_manejador_aplicar_eliminado_llama_anonimizar(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(
        repository,
        "bloquear_cliente",
        lambda _c, _i: _cliente_row(estado="Activo", tipo_cliente="Natural"),
    )
    monkeypatch.setattr(
        service,
        "_cliente_bloqueado",
        lambda _c, _i: Cliente(**_cliente_row(estado="Activo", tipo_cliente="Natural")),
    )
    monkeypatch.setattr(service, "_validar_productos_cliente", lambda _c, _i: None)
    actualizar_mock = MagicMock()
    monkeypatch.setattr(repository, "actualizar_estado_cliente", actualizar_mock)
    historial_mock = MagicMock()
    monkeypatch.setattr(repository, "insertar_historial_cliente", historial_mock)
    anonimizar_mock = MagicMock()
    monkeypatch.setattr(repository, "anonimizar_cliente", anonimizar_mock)

    contenido = {
        "estado": "Eliminado",
        "motivo": "Solicitud de baja voluntaria",
        "modificadoPor": 15,
        "direccionIp": "192.0.2.20",
    }
    MANEJADOR_ESTADO.aplicar(conn, OBJETIVO, contenido, "supervisor1", 99)

    actualizar_mock.assert_called_once_with(
        conn, 10, "Eliminado", motivo="Solicitud de baja voluntaria (solicitud 99)"
    )
    anonimizar_mock.assert_called_once_with(
        conn,
        10,
        "Natural",
        modificado_por=15,
        direccion_ip="192.0.2.20",
        id_solicitud=99,
    )
    conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Tarea 3: Anonimizar cliente al eliminar
# ---------------------------------------------------------------------------


def test_anonimizar_cliente_sql_no_contiene_identificacion_set_y_usa_parametros():
    # 1. Verificar constantes SQL estáticas
    for sql in (
        repository.SQL_ANONIMIZAR_NATURAL,
        repository.SQL_ANONIMIZAR_JURIDICO,
        repository.SQL_ANONIMIZAR_DIRECCIONES,
        repository.SQL_ANONIMIZAR_EMAILS,
    ):
        sql_upper = sql.upper()
        # SET no debe contener Identificacion =
        if "SET" in sql_upper:
            set_clause = sql_upper.split("SET", 1)[1].split("WHERE", 1)[0]
            assert "IDENTIFICACION =" not in set_clause
            assert "IDENTIFICACION=" not in set_clause

    # 2. Verificar ejecución con parámetros para persona Natural
    conn = MagicMock()
    repository.anonimizar_cliente(
        conn,
        10,
        "Natural",
        modificado_por=12,
        direccion_ip="192.0.2.10",
        id_solicitud=7,
    )

    # 3 sentencias SQL (Cliente, Direcciones, ClienteEmail) + 1 insert de historial
    assert conn.execute.call_count == 4

    llamada_cliente = conn.execute.call_args_list[0]
    sql_ejecutado = str(llamada_cliente.args[0]).upper()
    params = llamada_cliente.args[1]
    assert "IDENTIFICACION =" not in sql_ejecutado
    assert params["id_cliente"] == 10
    assert params["email"] == "eliminado.10@anonimizado.invalid"

    # Historial insertado (4ta llamada)
    llamada_hist = conn.execute.call_args_list[3]
    params_hist = llamada_hist.args[1]
    assert params_hist["id_cliente"] == 10
    assert params_hist["tipo_operacion"] == "D"
    assert params_hist["campo"] == "ANONIMIZACION"
    assert params_hist["valor_anterior"] is None
    assert params_hist["valor_nuevo"] == "Datos personales anonimizados"
    assert params_hist["id_solicitud"] == 7


def test_anonimizar_cliente_juridico():
    conn = MagicMock()
    repository.anonimizar_cliente(
        conn,
        20,
        "Juridico",
        modificado_por=14,
        direccion_ip="10.0.0.1",
        id_solicitud=11,
    )

    llamada_cliente = conn.execute.call_args_list[0]
    sql_ejecutado = str(llamada_cliente.args[0]).upper()
    params = llamada_cliente.args[1]
    assert "RAZONSOCIAL = 'CLIENTE ELIMINADO'" in sql_ejecutado
    assert "NOMBRECOMERCIAL = NULL" in sql_ejecutado
    assert params["id_cliente"] == 20
    assert params["email"] == "eliminado.20@anonimizado.invalid"


# ---------------------------------------------------------------------------
# Validar aprobador incompatible
# ---------------------------------------------------------------------------


def test_validar_aprobador_incompatible(monkeypatch):
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn

    # CreadoPor coincide con id_interno
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "CreadoPor": 5
    }
    monkeypatch.setattr(aprobacion_estado, "get_engine", lambda _db: engine)

    with pytest.raises(HTTPException) as exc:
        validar_aprobador_estado(OBJETIVO, 5)
    _assert_problema(exc, 403, "APROBADOR_INCOMPATIBLE")

    # CreadoPor distinto de id_interno -> no lanza excepción
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "CreadoPor": 8
    }
    validar_aprobador_estado(OBJETIVO, 5)


# ---------------------------------------------------------------------------
# Registro inicial de la operación
# ---------------------------------------------------------------------------


def test_operacion_estado_en_registro_inicial():
    operacion = registro_inicial().obtener("CLI-ESTADO", "ClienteEstado")
    assert operacion.codigo == "CLI-ESTADO"
    assert operacion.tipo_objetivo == "ClienteEstado"
    assert operacion.base == "cooperativa"
    assert operacion.roles_ejecucion == frozenset({"ADMIN", "ASESOR", "SUPERVISOR"})
    assert operacion.permiso_aprobacion == "clientes:aprobar"
    assert operacion.solicitud_directa is False
    assert operacion.tabla_auditada == "Clientes.Cliente"
    assert operacion.evento_ejecucion == "CLI_ESTADO"
    assert operacion.validar_aprobador is not None


# ---------------------------------------------------------------------------
# Habilitación: Cliente bloqueado da "no"
# ---------------------------------------------------------------------------


def test_cliente_bloqueado_da_no_en_habilitacion(monkeypatch):
    conn = MagicMock()
    # Cliente en estado Bloqueado
    fila = {
        "Estado": "Bloqueado",
        "ConsentimientoDatos": True,
        "FechaConsentimiento": datetime(2026, 1, 1),
        "TipoCliente": "Natural",
        "IdEvaluacion": 1,
        "ResultadoEvaluacion": "Aprobado",
        "EsPEP": False,
        "NivelRiesgoLAFT": "Bajo",
        "IdSolicitud": None,
        "AntecedenteImpeditivo": 0,
    }
    conn.execute.return_value.mappings.return_value.first.return_value = fila
    monkeypatch.setattr(habilitacion.general, "valor", lambda _c, _k, _f: False)

    motivos = habilitacion.requisitos_cliente(conn, 10, HOY)
    assert "CLIENTE_NO_ACTIVO" in motivos

    resultado = habilitacion.cliente_habilitado(conn, 10, HOY)
    assert resultado.habilitado is False
    assert "CLIENTE_NO_ACTIVO" in resultado.motivos
