"""Pruebas unitarias de E5-07 / ASVS 14.2.1:

- Tarea 1: Alta de cliente que detecta cliente Eliminado (409 CLIENTE_ELIMINADO).
- Tarea 2: Reincorporación con aprobación (POST /reincorporaciones, 202, validaciones, manejador).
- Tarea 3: Documento fuera de la URL (POST /validaciones/documento, CLI-01).
- Tarea 4: Cobertura completa sin base de datos real.
"""

import hashlib
from datetime import date
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Connection
from starlette.requests import Request

from app.core.api.errors import problema
from app.core.database.db import cooperativa
from app.main import app
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.clientes import (
    repository,
    router,
    service,
)
from app.modules.clientes.aprobacion_reincorporacion import (
    CODIGO_REINCORPORACION,
    MANEJADOR_REINCORPORACION,
    ContenidoReincorporacion,
    objetivo,
)
from app.modules.clientes.schemas import (
    ClienteCreate,
    DireccionCreate,
    ValidacionIdentificacion,
)
from tests.sesion import USUARIO, simular_sesion

HOY = date(2026, 11, 26)
OBJETIVO_10 = objetivo(10)


def _assert_problema(
    exc: pytest.ExceptionInfo[HTTPException], status: int, code: str
) -> None:
    assert exc.value.status_code == status
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == code


def _request() -> Request:
    return Request({"type": "http", "client": ("192.0.2.10", 1), "headers": []})


def _payload_reincorporacion(**overrides: Any) -> ClienteCreate:
    defaults: dict[str, Any] = {
        "identificacion": "1710034065",
        "tipo_documento": "C",
        "tipo_cliente": "Natural",
        "nombres": "Juan Carlos",
        "apellidos": "Pérez Gómez",
        "razon_social": None,
        "nombre_comercial": None,
        "id_actividad_economica": 1,
        "fecha_nacimiento": date(1990, 1, 1),
        "genero": "M",
        "estado_civil": "Soltero",
        "codigo_pais_nacionalidad": "ECU",
        "telefono_convencional": "022345678",
        "telefono_celular": "0991234567",
        "email": "juan.perez@correo.ec",
        "consentimiento_datos": True,
        "direccion": DireccionCreate(
            tipo_direccion="Domicilio",
            codigo_pais="ECU",
            id_ciudad=1,
            sector="La Floresta",
            calle_direccion="Av. 12 de Octubre N24-100",
            referencia_ubicacion="Frente al redondel",
            codigo_postal="170143",
            es_principal=True,
        ),
    }
    defaults.update(overrides)
    return ClienteCreate(**defaults)


def _patch_catalogos_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repository, "existe_pais", lambda _c, _p: True)
    monkeypatch.setattr(repository, "existe_ciudad", lambda _c, _cid, _p: True)
    monkeypatch.setattr(repository, "existe_actividad_economica", lambda _c, _a: True)
    monkeypatch.setattr(service, "validar_tipo_direccion", lambda _c, _t: None)


# ---------------------------------------------------------------------------
# 1. Alta con documento de cliente Eliminado vs Activo (Tarea 1)
# ---------------------------------------------------------------------------


def test_alta_con_documento_eliminado_409_y_activo_duplicado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    _patch_catalogos_ok(monkeypatch)
    payload = _payload_reincorporacion()

    from app.modules.clientes import documentos_identidad

    monkeypatch.setattr(
        documentos_identidad,
        "validar",
        lambda *_: {
            "Activo": True,
            "PermitePrincipal": True,
            "AplicaNatural": True,
            "RequiereVencimiento": False,
        },
    )
    monkeypatch.setattr(documentos_identidad, "bloquear_identidad", lambda *_: None)
    monkeypatch.setattr(
        documentos_identidad,
        "buscar",
        MagicMock(
            side_effect=[
                ValidacionIdentificacion(
                    valida=True,
                    existe=True,
                    id_cliente=10,
                    mensaje="Encontrado",
                    reincorporable=True,
                ),
                ValidacionIdentificacion(
                    valida=True, existe=True, id_cliente=10, mensaje="Encontrado"
                ),
            ]
        ),
    )
    with pytest.raises(HTTPException) as exc1:
        service.registrar_cliente(conn, payload, 1, "192.0.2.10")
    _assert_problema(exc1, 409, "CLIENTE_ELIMINADO")

    with pytest.raises(HTTPException) as exc2:
        service.registrar_cliente(conn, payload, 1, "192.0.2.10")
    _assert_problema(exc2, 409, "DOCUMENTO_DUPLICADO")


# ---------------------------------------------------------------------------
# 2. Reincorporación -> 202 y no escribe nada (Tarea 2)
# ---------------------------------------------------------------------------


def test_reincorporacion_202_y_no_escribe_nada(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    _patch_catalogos_ok(monkeypatch)
    payload = _payload_reincorporacion()

    monkeypatch.setattr(
        repository,
        "obtener_cliente_por_identificacion",
        lambda _c, _doc: {
            "id_cliente": 10,
            "estado": "Eliminado",
            "tipo_cliente": "Natural",
            "tipo_documento": "C",
        },
    )
    monkeypatch.setattr(
        repository,
        "obtener_cliente_tipos",
        lambda _c, _id: {
            "tipo_cliente": "Natural",
            "tipo_documento": "C",
            "estado": "Eliminado",
        },
    )

    solicitar_mock = MagicMock(return_value=SolicitudAceptada(id_solicitud=99))

    resultado = service.solicitar_reincorporacion(
        conn,
        payload,
        modificado_por=15,
        direccion_ip="192.0.2.10",
        id_agencia="001",
        solicitar=solicitar_mock,
    )

    assert isinstance(resultado, SolicitudAceptada)
    assert resultado.id_solicitud == 99
    solicitar_mock.assert_called_once()
    # Verifica que la llamada solo validó y no escribió en base de datos
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# 3. 404 CLIENTE_NO_ENCONTRADO (Tarea 2)
# ---------------------------------------------------------------------------


def test_reincorporacion_404_cliente_no_encontrado(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    _patch_catalogos_ok(monkeypatch)
    payload = _payload_reincorporacion()

    monkeypatch.setattr(
        repository, "obtener_cliente_por_identificacion", lambda _c, _doc: None
    )

    with pytest.raises(HTTPException) as exc:
        service.solicitar_reincorporacion(
            conn,
            payload,
            modificado_por=15,
            direccion_ip="192.0.2.10",
            solicitar=MagicMock(),
        )
    _assert_problema(exc, 404, "CLIENTE_NO_ENCONTRADO")


# ---------------------------------------------------------------------------
# 4. 409 CLIENTE_NO_ELIMINADO (Tarea 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("estado", ["Activo", "Bloqueado", "Inactivo", "Suspendido"])
def test_reincorporacion_409_cliente_no_eliminado(
    monkeypatch: pytest.MonkeyPatch, estado: str
) -> None:
    conn = MagicMock()
    _patch_catalogos_ok(monkeypatch)
    payload = _payload_reincorporacion()

    monkeypatch.setattr(
        repository,
        "obtener_cliente_por_identificacion",
        lambda _c, _doc: {
            "id_cliente": 10,
            "estado": estado,
            "tipo_cliente": "Natural",
            "tipo_documento": "C",
        },
    )

    with pytest.raises(HTTPException) as exc:
        service.solicitar_reincorporacion(
            conn,
            payload,
            modificado_por=15,
            direccion_ip="192.0.2.10",
            solicitar=MagicMock(),
        )
    _assert_problema(exc, 409, "CLIENTE_NO_ELIMINADO")


# ---------------------------------------------------------------------------
# 5. 422 DATOS_NO_COINCIDEN (Tarea 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tipo_cli_guardado", "tipo_doc_guardado"),
    [
        ("Juridico", "C"),
        ("Natural", "P"),
        ("Juridico", "R"),
    ],
)
def test_reincorporacion_422_datos_no_coinciden(
    monkeypatch: pytest.MonkeyPatch,
    tipo_cli_guardado: str,
    tipo_doc_guardado: str,
) -> None:
    conn = MagicMock()
    _patch_catalogos_ok(monkeypatch)
    # Payload envía Natural y C
    payload = _payload_reincorporacion(tipo_cliente="Natural", tipo_documento="C")

    monkeypatch.setattr(
        repository,
        "obtener_cliente_por_identificacion",
        lambda _c, _doc: {
            "id_cliente": 10,
            "estado": "Eliminado",
            "tipo_cliente": tipo_cli_guardado,
            "tipo_documento": tipo_doc_guardado,
        },
    )
    monkeypatch.setattr(
        repository,
        "obtener_cliente_tipos",
        lambda _c, _id: {
            "tipo_cliente": tipo_cli_guardado,
            "tipo_documento": tipo_doc_guardado,
            "estado": "Eliminado",
        },
    )

    with pytest.raises(HTTPException) as exc:
        service.solicitar_reincorporacion(
            conn,
            payload,
            modificado_por=15,
            direccion_ip="192.0.2.10",
            solicitar=MagicMock(),
        )
    _assert_problema(exc, 422, "DATOS_NO_COINCIDEN")


# ---------------------------------------------------------------------------
# 6. 409 REINCORPORACION_PENDIENTE (traducción de SOLICITUD_YA_PENDIENTE)
# ---------------------------------------------------------------------------


def test_reincorporacion_409_reincorporacion_pendiente(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    req = _request()
    usuario = USUARIO

    servicio_mock = MagicMock()
    servicio_mock.solicitar.side_effect = problema(
        409, "SOLICITUD_YA_PENDIENTE", "Ya existe solicitud pendiente"
    )
    # El router usa su propio alias del módulo de aprobaciones.
    monkeypatch.setattr(router.aprobaciones, "servicio", lambda: servicio_mock)
    monkeypatch.setattr(router.aprobaciones, "actual", lambda _u: MagicMock())
    monkeypatch.setattr(router.aprobaciones, "contexto", lambda _r, _u: MagicMock())

    solicitar_fn = router._solicitar_reincorporacion(req, usuario)

    with pytest.raises(HTTPException) as exc:
        solicitar_fn(10, {"datos": {}})
    _assert_problema(exc, 409, "REINCORPORACION_PENDIENTE")


# ---------------------------------------------------------------------------
# 7. Consentimiento falso -> 422 (Tarea 2)
# ---------------------------------------------------------------------------


def test_reincorporacion_422_consentimiento_falso() -> None:
    conn = MagicMock()
    payload = _payload_reincorporacion(consentimiento_datos=False)

    with pytest.raises(HTTPException) as exc:
        service.solicitar_reincorporacion(
            conn,
            payload,
            modificado_por=15,
            direccion_ip="192.0.2.10",
            solicitar=MagicMock(),
        )
    _assert_problema(exc, 422, "CONSENTIMIENTO_REQUERIDO")


# ---------------------------------------------------------------------------
# 8. Manejador: contenido inválido 422 (Tarea 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "contenido_invalido",
    [
        {},
        {"datos": {}, "modificado_por": 1, "direccion_ip": "127.0.0.1"},
        {"modificado_por": -1, "direccion_ip": "127.0.0.1"},
        {
            "datos": _payload_reincorporacion().model_dump(mode="json"),
            "modificado_por": 0,
            "direccion_ip": "127.0.0.1",
        },
        {
            "datos": _payload_reincorporacion().model_dump(mode="json"),
            "modificado_por": 1,
            "direccion_ip": "127.0.0.1",
            "campo_prohibido": "valor_extra",
        },
    ],
)
def test_manejador_contenido_invalido_422(
    contenido_invalido: dict[str, Any],
) -> None:
    conn = MagicMock()
    manejador = MANEJADOR_REINCORPORACION

    with pytest.raises(HTTPException) as exc:
        manejador.preparar(conn, OBJETIVO_10, contenido_invalido, hoy=HOY)
    _assert_problema(exc, 422, "CONTENIDO_INVALIDO")


# ---------------------------------------------------------------------------
# 9. preparar sin datos personales en antes/después (Tarea 2)
# ---------------------------------------------------------------------------


def test_preparar_sin_datos_personales_en_antes_despues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    payload = _payload_reincorporacion()
    contenido = ContenidoReincorporacion(
        datos=payload,
        modificado_por=15,
        direccion_ip="192.0.2.10",
    ).model_dump(mode="json", by_alias=True)

    monkeypatch.setattr(
        repository,
        "bloquear_datos_sensibles",
        lambda _c, _id: {
            "id_cliente": 10,
            "estado": "Eliminado",
            "tipo_cliente": "Natural",
            "tipo_documento": "C",
        },
    )

    plan = MANEJADOR_REINCORPORACION.preparar(conn, OBJETIVO_10, contenido, hoy=HOY)

    assert plan.antes == {"estado": "Eliminado"}
    assert plan.despues == {"estado": "Pendiente"}
    # Verifica que antes y después no contengan datos personales
    for campo in (
        "identificacion",
        "nombres",
        "apellidos",
        "email",
        "telefono_celular",
    ):
        assert campo not in plan.antes
        assert campo not in plan.despues

    assert plan.version == hashlib.sha256(b"Eliminado").hexdigest()


# ---------------------------------------------------------------------------
# 10. aplicar llama a reincorporar_cliente, inserta dirección, invalida evaluaciones
#     y deja historial sin datos personales (Tarea 2)
# ---------------------------------------------------------------------------


def test_aplicar_reincorporacion_completa(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()
    payload = _payload_reincorporacion()
    contenido = ContenidoReincorporacion(
        datos=payload,
        modificado_por=15,
        direccion_ip="192.0.2.10",
        id_agencia="002",
    ).model_dump(mode="json", by_alias=True)

    monkeypatch.setattr(
        repository,
        "bloquear_datos_sensibles",
        lambda _c, _id: {
            "id_cliente": 10,
            "estado": "Eliminado",
            "tipo_cliente": "Natural",
            "tipo_documento": "C",
        },
    )

    reincorporar_mock = MagicMock()
    monkeypatch.setattr(repository, "reincorporar_cliente", reincorporar_mock)

    insertar_dir_mock = MagicMock()
    monkeypatch.setattr(repository, "insertar_direccion", insertar_dir_mock)

    invalidar_mock = MagicMock()
    monkeypatch.setattr(repository, "invalidar_riesgos_cliente", invalidar_mock)

    historiales: list[dict[str, Any]] = []

    def mock_historial(_c: Connection, **kwargs: Any) -> None:
        historiales.append(kwargs)

    monkeypatch.setattr(repository, "insertar_historial_cliente", mock_historial)

    MANEJADOR_REINCORPORACION.aplicar(
        conn, OBJETIVO_10, contenido, solicitante="asesor@banco.ec", id_solicitud=77
    )

    # 1. reincorporar_cliente llamado
    reincorporar_mock.assert_called_once_with(
        conn,
        10,
        payload,
        id_agencia="002",
        id_solicitud=77,
    )

    # 2. insertar_direccion llamado con datos de dirección principal
    insertar_dir_mock.assert_called_once()
    call_dir_args = insertar_dir_mock.call_args
    assert call_dir_args[0][1] == 10  # id_cliente
    assert call_dir_args[1]["modificado_por"] == 15
    # snake_case, como lee repository.insertar_direccion (con camelCase fallaba al aprobar)
    assert {"tipo_direccion", "id_ciudad", "calle_direccion"} <= set(
        call_dir_args[0][2]
    )
    assert call_dir_args[1]["direccion_ip"] == "192.0.2.10"

    # 3. invalidar_riesgos_cliente llamado
    invalidar_mock.assert_called_once_with(conn, 10)

    # 4. Historial: 2 filas sin datos personales
    assert len(historiales) == 2

    # Fila 1: Cambio de estado Eliminado -> Pendiente
    h_estado = historiales[0]
    assert h_estado["id_cliente"] == 10
    assert h_estado["tipo_operacion"] == "U"
    assert h_estado["campo"] == "Estado"
    assert h_estado["valor_anterior"] == "Eliminado"
    assert h_estado["valor_nuevo"] == "Pendiente"
    assert h_estado["id_solicitud"] == 77
    assert h_estado["modificado_por"] == 15
    assert payload.identificacion not in h_estado["observaciones"]
    assert payload.nombres not in h_estado["observaciones"]

    # Fila 2: REINCORPORACION
    h_reinc = historiales[1]
    assert h_reinc["id_cliente"] == 10
    assert h_reinc["tipo_operacion"] == "U"
    assert h_reinc["campo"] == "REINCORPORACION"
    assert h_reinc["valor_anterior"] is None
    assert h_reinc["valor_nuevo"] == "Datos personales registrados de nuevo"
    assert h_reinc["id_solicitud"] == 77
    assert payload.identificacion not in h_reinc["observaciones"]
    assert payload.nombres not in h_reinc["observaciones"]

    # Sin commit
    conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 11. SQL de reincorporar_cliente tiene Estado = 'Eliminado' y no actualiza Identificacion
# ---------------------------------------------------------------------------


def test_sql_reincorporar_cliente_where_eliminado_y_no_actualiza_identificacion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = MagicMock()
    conn.execute.return_value = MagicMock(rowcount=1)
    payload = _payload_reincorporacion()

    repository.reincorporar_cliente(
        cast(Connection, conn), 10, payload, id_agencia="001", id_solicitud=50
    )

    conn.execute.assert_called_once()
    call_args = conn.execute.call_args
    sql_text = str(call_args[0][0])

    # El WHERE debe exigir Estado = 'Eliminado'
    assert "Estado = 'Eliminado'" in sql_text
    assert "WHERE IdCliente = :id_cliente AND Estado = 'Eliminado'" in sql_text

    # No debe modificar Identificacion, TipoDocumento, TipoCliente, CreadoPor, FechaRegistro
    # en la cláusula SET
    set_clause = sql_text.split("WHERE")[0]
    assert "Identificacion" not in set_clause
    assert "TipoDocumento" not in set_clause
    assert "TipoCliente" not in set_clause
    assert "CreadoPor" not in set_clause
    assert "FechaRegistro" not in set_clause

    # Debe actualizar Estado = 'Pendiente' y ConsentimientoDatos = 1
    assert "Estado = 'Pendiente'" in set_clause
    assert "ConsentimientoDatos = 1" in set_clause
    assert "EmailVerificadoPor = NULL" in set_clause


# ---------------------------------------------------------------------------
# 12. La operación está en registro_inicial() (Tarea 2)
# ---------------------------------------------------------------------------


def test_operacion_reincorporacion_en_registro_inicial() -> None:
    registro = registro_inicial()
    op = registro.obtener(CODIGO_REINCORPORACION, "ClienteReincorporacion")

    assert op.codigo == "CLI-REINCORPORAR"
    assert op.tipo_objetivo == "ClienteReincorporacion"
    assert op.base == "cooperativa"
    assert op.roles_ejecucion == frozenset({"ADMIN", "ASESOR", "SUPERVISOR"})
    assert op.permiso_aprobacion == "clientes:aprobar"
    assert op.tabla_auditada == "Clientes.Cliente"
    assert op.evento_ejecucion == "CLI_REINCORPORADO"
    assert op.solicitud_directa is False


# ---------------------------------------------------------------------------
# 13. POST /validaciones/documento valida con el cuerpo, devuelve reincorporable
#     y el GET ya no existe (405) (Tarea 3)
# ---------------------------------------------------------------------------


def test_post_validaciones_documento_valida_con_cuerpo_y_get_no_existe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides[cooperativa] = lambda: None
    simular_sesion(app, USUARIO)

    # Mock del service.validar_identificacion
    def mock_validar(_conn: Any, tipo_doc: str, ident: str) -> ValidacionIdentificacion:
        return ValidacionIdentificacion(
            valida=True,
            existe=True,
            id_cliente=10,
            mensaje="Identificación ya registrada en el sistema.",
            reincorporable=True,
            estado="Eliminado",
        )

    monkeypatch.setattr(service, "validar_identificacion", mock_validar)

    with TestClient(app, raise_server_exceptions=False) as client:
        # POST /validaciones/documento funciona con el cuerpo
        resp_post = client.post(
            "/api/v1/clientes/validaciones/documento",
            json={"tipoDocumento": "C", "identificacion": "1710034065"},
        )
        assert resp_post.status_code == 200
        body = resp_post.json()
        assert body["valida"] is True
        assert body["existe"] is True
        assert body["reincorporable"] is True
        assert body["estado"] == "Eliminado"

        # GET a la nueva ruta devuelve 405 Method Not Allowed
        resp_get_nueva = client.get("/api/v1/clientes/validaciones/documento")
        assert resp_get_nueva.status_code == 405

        # GET a la ruta antigua ya no existe (404 o 405)
        resp_get_antigua = client.get(
            "/api/v1/clientes/validar-identificacion?tipoDocumento=C&identificacion=1710034065"
        )
        assert resp_get_antigua.status_code in (400, 404, 405)

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 14. El documento no aparece en la URL (OpenAPI no declara parámetros de query)
# ---------------------------------------------------------------------------


def test_documento_no_aparece_en_url_openapi() -> None:
    schema = app.openapi()
    paths = schema["paths"]

    # 1. POST /api/v1/clientes/validaciones/documento (CLI-01)
    assert "/api/v1/clientes/validar-identificacion" not in paths
    assert "/api/v1/clientes/validaciones/documento" in paths
    op_doc = paths["/api/v1/clientes/validaciones/documento"]["post"]
    assert op_doc["operationId"] == "CLI01"
    # No declara parámetros de query
    assert op_doc.get("parameters") in (None, [])
    # Tiene requestBody
    assert "requestBody" in op_doc

    # 2. POST /api/v1/clientes/reincorporaciones (CLIReincorporar)
    assert "/api/v1/clientes/reincorporaciones" in paths
    op_reinc = paths["/api/v1/clientes/reincorporaciones"]["post"]
    assert op_reinc["operationId"] == "CLIReincorporar"
    # No declara parámetros de query ni path para identificación
    reinc_params = op_reinc.get("parameters") or []
    param_names = [p["name"] for p in reinc_params]
    assert "identificacion" not in param_names
    assert "tipoDocumento" not in param_names
    assert "idCliente" not in param_names
    # Tiene requestBody
    assert "requestBody" in op_reinc
