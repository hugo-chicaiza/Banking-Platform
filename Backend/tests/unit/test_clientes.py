"""Pruebas unitarias de:

- CLI-01 · GET /api/v1/clientes/validar-identificacion
- CLI-02 · POST /api/v1/clientes
- CLI-09 · GET /api/v1/clientes/{idCliente}/direcciones
- CLI-10 · POST /api/v1/clientes/{idCliente}/direcciones
- CLI-11 · PATCH /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
- CLI-12 · DELETE /api/v1/clientes/{idCliente}/direcciones/{idDireccion}

No requieren base de datos: se monkeypatcha el repositorio.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection

from app.core.db import cooperativa
from app.main import app
from app.modules.clientes import repository, service
from app.modules.clientes.schemas import ClienteCreate, DireccionCreate

# Cédulas y RUCs válidos conocidos
CEDULA_VALIDA_1 = "1710034065"
CEDULA_VALIDA_2 = "0926687856"
CEDULA_VALIDA_EXTERIOR = "3000000012"
RUC_VALIDO = "1710034065001"
PASAPORTE_VALIDO = "A12345678"


class _FakeConn:
    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


@pytest.fixture()
def client():
    """Cliente HTTP sin base de datos real; inyecta FakeConn como conexión."""
    app.dependency_overrides[cooperativa] = lambda: _FakeConn()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _fake_conn() -> Connection:
    """Retorna un _FakeConn casteado a Connection para pyright."""
    return cast(Connection, _FakeConn())


def _assert_http_error(
    exc_info: pytest.ExceptionInfo[service.HTTPException], status: int, code: str
) -> None:
    """Verifica status y code asegurando tipo dict para Pyright."""
    assert exc_info.value.status_code == status
    detail = exc_info.value.detail
    assert isinstance(detail, dict)
    assert detail.get("code") == code


# ---------------------------------------------------------------------------
# Pruebas de Algoritmo Módulo 10 (Lógica Pura en Service)
# ---------------------------------------------------------------------------


def test_modulo10_cedula_valida():
    valida, motivo = service.validar_cedula_ecuatoriana(CEDULA_VALIDA_1)
    assert valida is True
    assert "válida" in motivo.lower()

    valida, _ = service.validar_cedula_ecuatoriana(CEDULA_VALIDA_2)
    assert valida is True

    valida, _ = service.validar_cedula_ecuatoriana(CEDULA_VALIDA_EXTERIOR)
    assert valida is True


def test_modulo10_cedula_longitud_incorrecta():
    valida, motivo = service.validar_cedula_ecuatoriana("171003406")
    assert valida is False
    assert "10 dígitos" in motivo

    valida, motivo = service.validar_cedula_ecuatoriana("17100340655")
    assert valida is False
    assert "10 dígitos" in motivo


def test_modulo10_cedula_no_numerica():
    valida, motivo = service.validar_cedula_ecuatoriana("171003406A")
    assert valida is False
    assert "10 dígitos numéricos" in motivo


def test_modulo10_cedula_provincia_invalida():
    valida, motivo = service.validar_cedula_ecuatoriana("0010034065")
    assert valida is False
    assert "provincia" in motivo.lower()

    valida, motivo = service.validar_cedula_ecuatoriana("2510034065")
    assert valida is False
    assert "provincia" in motivo.lower()


def test_modulo10_cedula_tercer_digito_invalido():
    valida, motivo = service.validar_cedula_ecuatoriana("1760034065")
    assert valida is False
    assert "tercer dígito" in motivo.lower()


def test_modulo10_cedula_digito_verificador_incorrecto():
    valida, motivo = service.validar_cedula_ecuatoriana("1710034064")
    assert valida is False
    assert "dígito verificador" in motivo.lower()


# ---------------------------------------------------------------------------
# Pruebas de RUC
# ---------------------------------------------------------------------------


def test_validar_ruc_valido():
    valida, motivo = service.validar_ruc(RUC_VALIDO)
    assert valida is True
    assert "válido" in motivo.lower()


def test_validar_ruc_no_termina_en_001():
    valida, motivo = service.validar_ruc("1710034065002")
    assert valida is False
    assert "001" in motivo


def test_validar_ruc_longitud_incorrecta():
    valida, motivo = service.validar_ruc("171003406500")
    assert valida is False
    assert "13 dígitos" in motivo


def test_validar_ruc_base_cedula_invalida():
    valida, motivo = service.validar_ruc("1710034064001")
    assert valida is False
    assert "Base de cédula" in motivo


# ---------------------------------------------------------------------------
# Pruebas de Pasaporte
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pasaporte", ["ABC12", "A12345678", "PASS123456789"])
def test_validar_pasaporte_valido(pasaporte):
    valida, motivo = service.validar_pasaporte(pasaporte)
    assert valida is True
    assert "válido" in motivo.lower()


@pytest.mark.parametrize(
    "pasaporte",
    [
        "A12",
        "PASS1234567890123",
        "PASS-1234",
        "PASS 1234",
    ],
)
def test_validar_pasaporte_invalido(pasaporte):
    valida, motivo = service.validar_pasaporte(pasaporte)
    assert valida is False
    assert "alfanuméricos" in motivo


# ---------------------------------------------------------------------------
# Pruebas de Servicio CLI-01 (Validación + BD Mockeada)
# ---------------------------------------------------------------------------


def test_service_documento_valido_y_disponible(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(
        repository, "obtener_cliente_por_identificacion", lambda c, doc: None
    )

    resultado = service.validar_identificacion(conn, "C", CEDULA_VALIDA_1)

    assert resultado.valida is True
    assert resultado.existe is False
    assert resultado.id_cliente is None
    assert "disponible" in resultado.mensaje.lower()


def test_service_documento_valido_pero_ya_registrado(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(
        repository,
        "obtener_cliente_por_identificacion",
        lambda c, doc: {"id_cliente": 77, "estado": "Activo"},
    )

    resultado = service.validar_identificacion(conn, "C", CEDULA_VALIDA_1)

    assert resultado.valida is True
    assert resultado.existe is True
    assert resultado.id_cliente == 77
    assert "registrada" in resultado.mensaje.lower()


def test_service_documento_invalido_no_consulta_db(monkeypatch):
    conn = MagicMock()
    resultado = service.validar_identificacion(conn, "C", "1710034064")

    assert resultado.valida is False
    assert resultado.existe is False
    assert resultado.id_cliente is None
    assert "dígito verificador" in resultado.mensaje.lower()


# ---------------------------------------------------------------------------
# Pruebas de Servicio CLI-02 (Registro de Clientes)
# ---------------------------------------------------------------------------


def _payload_natural_valido() -> ClienteCreate:
    return ClienteCreate(
        identificacion=CEDULA_VALIDA_1,
        tipo_documento="C",
        tipo_cliente="Natural",
        nombres="María José",
        apellidos="López Pérez",
        id_actividad_economica=1,
        fecha_nacimiento=date(1990, 5, 14),
        genero="F",
        estado_civil="Soltero",
        codigo_pais_nacionalidad="ECU",
        telefono_convencional="022345678",
        telefono_celular="0991234567",
        email="maria.lopez@correo.ec",
        consentimiento_datos=True,
        direccion=DireccionCreate(
            tipo_direccion="Domicilio",
            codigo_pais="ECU",
            id_ciudad=1,
            sector="La Mariscal",
            calle_direccion="Av. Amazonas N24-123",
            referencia_ubicacion="Frente al parque",
            codigo_postal="170143",
            es_principal=True,
        ),
    )


def _patch_repo_catalogos_ok(monkeypatch):
    monkeypatch.setattr(repository, "existe_pais", lambda conn, codigo: True)
    monkeypatch.setattr(repository, "existe_ciudad", lambda conn, id_c, codigo: True)
    monkeypatch.setattr(
        repository, "existe_actividad_economica", lambda conn, id_act: True
    )


def test_registrar_cliente_natural_exitoso(monkeypatch):
    conn = _fake_conn()
    payload = _payload_natural_valido()

    _patch_repo_catalogos_ok(monkeypatch)
    monkeypatch.setattr(
        repository, "obtener_cliente_por_identificacion", lambda conn, doc: None
    )

    ahora = datetime.now(UTC)
    mock_db_res = {
        "id_cliente": 101,
        "identificacion": payload.identificacion,
        "tipo_documento": payload.tipo_documento,
        "tipo_cliente": payload.tipo_cliente,
        "nombres": payload.nombres,
        "apellidos": payload.apellidos,
        "razon_social": None,
        "nombre_comercial": None,
        "id_actividad_economica": payload.id_actividad_economica,
        "fecha_nacimiento": payload.fecha_nacimiento,
        "genero": payload.genero,
        "estado_civil": payload.estado_civil,
        "codigo_pais_nacionalidad": payload.codigo_pais_nacionalidad,
        "telefono_convencional": payload.telefono_convencional,
        "telefono_celular": payload.telefono_celular,
        "email": payload.email,
        "consentimiento_datos": True,
        "fecha_consentimiento": ahora,
        "estado": "Pendiente",
        "fecha_registro": ahora,
        "creado_por": 1,
        "direcciones": [
            {
                "id_direccion": 55,
                "tipo_direccion": payload.direccion.tipo_direccion,
                "codigo_pais": payload.direccion.codigo_pais,
                "id_ciudad": payload.direccion.id_ciudad,
                "sector": payload.direccion.sector,
                "calle_direccion": payload.direccion.calle_direccion,
                "referencia_ubicacion": payload.direccion.referencia_ubicacion,
                "codigo_postal": payload.direccion.codigo_postal,
                "es_principal": True,
                "estado": "Activo",
            }
        ],
    }
    monkeypatch.setattr(
        repository, "crear_cliente", lambda *args, **kwargs: mock_db_res
    )

    cliente = service.registrar_cliente(conn, payload, 1, "127.0.0.1")

    assert cliente.id_cliente == 101
    assert cliente.estado == "Pendiente"
    assert cliente.nombres == "María José"
    assert len(cliente.direcciones) == 1
    assert cliente.direcciones[0].id_direccion == 55


def test_registrar_cliente_juridico_exitoso(monkeypatch):
    conn = _fake_conn()
    payload = _payload_natural_valido()
    payload.tipo_cliente = "Juridico"
    payload.identificacion = RUC_VALIDO
    payload.tipo_documento = "R"
    payload.razon_social = "Empresa Ejemplo S.A."
    payload.apellidos = None
    payload.genero = None
    payload.estado_civil = None

    _patch_repo_catalogos_ok(monkeypatch)
    monkeypatch.setattr(
        repository, "obtener_cliente_por_identificacion", lambda conn, doc: None
    )

    ahora = datetime.now(UTC)
    mock_db_res = {
        "id_cliente": 202,
        "identificacion": payload.identificacion,
        "tipo_documento": payload.tipo_documento,
        "tipo_cliente": payload.tipo_cliente,
        "nombres": payload.nombres,
        "apellidos": None,
        "razon_social": payload.razon_social,
        "nombre_comercial": "Ejemplo Comercial",
        "id_actividad_economica": payload.id_actividad_economica,
        "fecha_nacimiento": payload.fecha_nacimiento,
        "genero": None,
        "estado_civil": None,
        "codigo_pais_nacionalidad": payload.codigo_pais_nacionalidad,
        "telefono_convencional": payload.telefono_convencional,
        "telefono_celular": payload.telefono_celular,
        "email": payload.email,
        "consentimiento_datos": True,
        "fecha_consentimiento": ahora,
        "estado": "Pendiente",
        "fecha_registro": ahora,
        "creado_por": 1,
        "direcciones": [],
    }
    monkeypatch.setattr(
        repository, "crear_cliente", lambda *args, **kwargs: mock_db_res
    )

    cliente = service.registrar_cliente(conn, payload, 1, "127.0.0.1")

    assert cliente.id_cliente == 202
    assert cliente.razon_social == "Empresa Ejemplo S.A."
    assert cliente.apellidos is None


def test_registrar_cliente_validaciones_negocio_422(monkeypatch):
    conn = _fake_conn()
    _patch_repo_catalogos_ok(monkeypatch)
    monkeypatch.setattr(
        repository, "obtener_cliente_por_identificacion", lambda c, doc: None
    )

    # 1. Sin consentimiento
    p_consent = _payload_natural_valido()
    p_consent.consentimiento_datos = False
    with pytest.raises(service.HTTPException) as exc1:
        service.registrar_cliente(conn, p_consent, 1, "127.0.0.1")
    _assert_http_error(exc1, 422, "CONSENTIMIENTO_REQUERIDO")

    # 2. Fecha nacimiento futura
    p_fecha = _payload_natural_valido()
    p_fecha.fecha_nacimiento = date.today() + timedelta(days=1)
    with pytest.raises(service.HTTPException) as exc2:
        service.registrar_cliente(conn, p_fecha, 1, "127.0.0.1")
    _assert_http_error(exc2, 422, "FECHA_NACIMIENTO_INVALIDA")

    # 3. Documento con formato inválido
    p_doc = _payload_natural_valido()
    p_doc.identificacion = "1710034064"
    with pytest.raises(service.HTTPException) as exc3:
        service.registrar_cliente(conn, p_doc, 1, "127.0.0.1")
    _assert_http_error(exc3, 422, "DOCUMENTO_INVALIDO")

    # 4. Tipo persona Natural con razonSocial prohibida
    p_nat = _payload_natural_valido()
    p_nat.razon_social = "No permitida"
    with pytest.raises(service.HTTPException) as exc4:
        service.registrar_cliente(conn, p_nat, 1, "127.0.0.1")
    _assert_http_error(exc4, 422, "TIPO_PERSONA_INVALIDO")

    # 5. Tipo persona Juridico con apellidos prohibidos
    p_jur = _payload_natural_valido()
    p_jur.tipo_cliente = "Juridico"
    p_jur.identificacion = RUC_VALIDO
    p_jur.tipo_documento = "R"
    p_jur.razon_social = "Empresa S.A."
    p_jur.apellidos = "No permitidos"
    with pytest.raises(service.HTTPException) as exc5:
        service.registrar_cliente(conn, p_jur, 1, "127.0.0.1")
    _assert_http_error(exc5, 422, "TIPO_PERSONA_INVALIDO")


def test_registrar_cliente_duplicado_409(monkeypatch):
    conn = _fake_conn()
    monkeypatch.setattr(
        repository,
        "obtener_cliente_por_identificacion",
        lambda c, doc: {"id_cliente": 99},
    )

    with pytest.raises(service.HTTPException) as exc:
        service.registrar_cliente(conn, _payload_natural_valido(), 1, "127.0.0.1")

    _assert_http_error(exc, 409, "CLIENTE_DUPLICADO")


def test_registrar_cliente_catalogos_invalidos_422(monkeypatch):
    conn = _fake_conn()
    _patch_repo_catalogos_ok(monkeypatch)
    monkeypatch.setattr(
        repository, "obtener_cliente_por_identificacion", lambda c, doc: None
    )

    # 1. Pais no existe
    monkeypatch.setattr(repository, "existe_pais", lambda c, cod: False)
    with pytest.raises(service.HTTPException) as exc1:
        service.registrar_cliente(conn, _payload_natural_valido(), 1, "127.0.0.1")
    _assert_http_error(exc1, 422, "CATALOGO_INVALIDO")

    # 2. Ciudad no existe
    monkeypatch.setattr(repository, "existe_pais", lambda c, cod: True)
    monkeypatch.setattr(repository, "existe_ciudad", lambda c, cid, cod: False)
    with pytest.raises(service.HTTPException) as exc2:
        service.registrar_cliente(conn, _payload_natural_valido(), 1, "127.0.0.1")
    _assert_http_error(exc2, 422, "CATALOGO_INVALIDO")


# ===========================================================================
# CLI-09..CLI-12 · Direcciones del cliente
# ===========================================================================


def _direccion_row(**overrides: Any) -> dict[str, Any]:
    """Fábrica de fila de dirección para evitar duplicación (SonarQube)."""
    base: dict[str, Any] = {
        "id_direccion": 1,
        "tipo_direccion": "Domicilio",
        "codigo_pais": "ECU",
        "id_ciudad": 1,
        "sector": "La Mariscal",
        "calle_direccion": "Av. Amazonas N24-123",
        "referencia_ubicacion": "Frente al parque",
        "codigo_postal": "170143",
        "es_principal": True,
        "estado": "Activo",
    }
    base.update(overrides)
    return base


def _patch_cliente_existe(
    monkeypatch, *, estado: str = "Activo", id_cliente: int = 10
) -> None:
    """Mockea obtener_cliente_por_id para que retorne un cliente existente."""
    monkeypatch.setattr(
        repository,
        "obtener_cliente_por_id",
        lambda conn, cid: {"id_cliente": id_cliente, "estado": estado},
    )


def _patch_cliente_no_existe(monkeypatch) -> None:
    """Mockea obtener_cliente_por_id para que retorne None."""
    monkeypatch.setattr(repository, "obtener_cliente_por_id", lambda conn, cid: None)


# ---------------------------------------------------------------------------
# CLI-09 · Listar direcciones
# ---------------------------------------------------------------------------


def test_cli09_listar_direcciones_caso_feliz(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)

    filas = [
        _direccion_row(id_direccion=1, es_principal=True),
        _direccion_row(id_direccion=2, es_principal=False, estado="Inactivo"),
    ]
    monkeypatch.setattr(repository, "listar_direcciones", lambda conn, cid: filas)

    resultado = service.listar_direcciones(conn, 10)

    assert len(resultado) == 2
    assert resultado[0].id_direccion == 1
    assert resultado[0].es_principal is True
    assert resultado[1].estado == "Inactivo"


def test_cli09_listar_direcciones_cliente_no_existe(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_no_existe(monkeypatch)

    with pytest.raises(service.HTTPException) as exc:
        service.listar_direcciones(conn, 999)

    _assert_http_error(exc, 404, "CLIENTE_NO_ENCONTRADO")


def test_cli09_listar_direcciones_vacia(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)
    monkeypatch.setattr(repository, "listar_direcciones", lambda conn, cid: [])

    resultado = service.listar_direcciones(conn, 10)
    assert resultado == []


# ---------------------------------------------------------------------------
# CLI-10 · Agregar dirección
# ---------------------------------------------------------------------------


def _payload_direccion_nueva(**overrides: Any) -> service.DireccionNueva:
    """Fábrica de payload DireccionNueva para evitar duplicación."""
    defaults: dict[str, Any] = {
        "tipo_direccion": "Domicilio",
        "codigo_pais": "ECU",
        "id_ciudad": 1,
        "sector": "La Mariscal",
        "calle_direccion": "Av. Amazonas N24-123",
        "referencia_ubicacion": "Frente al parque",
        "codigo_postal": "170143",
        "es_principal": False,
    }
    defaults.update(overrides)
    return service.DireccionNueva(**defaults)


def _patch_insertar_direccion(monkeypatch, **overrides: Any) -> None:
    """Mockea insertar_direccion para retornar una dirección con overrides."""

    def _insertar(conn, cid, datos, *, modificado_por, direccion_ip):
        return _direccion_row(
            id_direccion=10,
            es_principal=datos.get("es_principal", False),
            **overrides,
        )

    monkeypatch.setattr(repository, "insertar_direccion", _insertar)


def test_cli10_agregar_direccion_caso_feliz(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)
    monkeypatch.setattr(repository, "existe_ciudad", lambda c, cid, cod: True)
    _patch_insertar_direccion(monkeypatch)

    resultado = service.agregar_direccion(
        conn, 10, _payload_direccion_nueva(), 1, "127.0.0.1"
    )

    assert resultado.id_direccion == 10
    assert resultado.estado == "Activo"


def test_cli10_agregar_direccion_como_principal(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)
    monkeypatch.setattr(repository, "existe_ciudad", lambda c, cid, cod: True)
    _patch_insertar_direccion(monkeypatch)

    resultado = service.agregar_direccion(
        conn, 10, _payload_direccion_nueva(es_principal=True), 1, "127.0.0.1"
    )

    assert resultado.es_principal is True


def test_cli10_agregar_direccion_cliente_no_existe(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_no_existe(monkeypatch)

    with pytest.raises(service.HTTPException) as exc:
        service.agregar_direccion(conn, 999, _payload_direccion_nueva(), 1, "127.0.0.1")

    _assert_http_error(exc, 404, "CLIENTE_NO_ENCONTRADO")


def test_cli10_agregar_direccion_cliente_eliminado(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch, estado="Eliminado")

    with pytest.raises(service.HTTPException) as exc:
        service.agregar_direccion(conn, 10, _payload_direccion_nueva(), 1, "127.0.0.1")

    _assert_http_error(exc, 409, "CLIENTE_ELIMINADO")


def test_cli10_agregar_direccion_ciudad_invalida(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)
    monkeypatch.setattr(repository, "existe_ciudad", lambda c, cid, cod: False)

    with pytest.raises(service.HTTPException) as exc:
        service.agregar_direccion(conn, 10, _payload_direccion_nueva(), 1, "127.0.0.1")

    _assert_http_error(exc, 422, "CATALOGO_INVALIDO")


# ---------------------------------------------------------------------------
# CLI-11 · Editar dirección
# ---------------------------------------------------------------------------


def _payload_direccion_update(**overrides: Any) -> service.DireccionUpdate:
    """Fábrica de payload DireccionUpdate para evitar duplicación."""
    return service.DireccionUpdate(**overrides)


def test_cli11_editar_direccion_caso_feliz(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)

    dir_actual = _direccion_row(id_direccion=5, sector="Centro")
    monkeypatch.setattr(repository, "obtener_direccion", lambda c, cid, did: dir_actual)

    dir_actualizada = _direccion_row(id_direccion=5, sector="Norte")
    monkeypatch.setattr(
        repository,
        "actualizar_direccion",
        lambda c, cid, did, cambios, **kw: dir_actualizada,
    )

    resultado = service.editar_direccion(
        conn, 10, 5, _payload_direccion_update(sector="Norte"), 1, "127.0.0.1"
    )

    assert resultado.id_direccion == 5
    assert resultado.sector == "Norte"


def test_cli11_editar_direccion_promover_principal(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)

    dir_actual = _direccion_row(id_direccion=5, es_principal=False)
    monkeypatch.setattr(repository, "obtener_direccion", lambda c, cid, did: dir_actual)

    dir_actualizada = _direccion_row(id_direccion=5, es_principal=True)
    monkeypatch.setattr(
        repository,
        "actualizar_direccion",
        lambda c, cid, did, cambios, **kw: dir_actualizada,
    )

    resultado = service.editar_direccion(
        conn, 10, 5, _payload_direccion_update(es_principal=True), 1, "127.0.0.1"
    )

    assert resultado.es_principal is True


def test_cli11_editar_direccion_sin_cambios(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)

    dir_actual = _direccion_row(id_direccion=5, sector="La Mariscal")
    monkeypatch.setattr(repository, "obtener_direccion", lambda c, cid, did: dir_actual)

    # Enviar el mismo sector → no debería llamar a actualizar_direccion
    resultado = service.editar_direccion(
        conn, 10, 5, _payload_direccion_update(sector="La Mariscal"), 1, "127.0.0.1"
    )

    assert resultado.id_direccion == 5
    assert resultado.sector == "La Mariscal"


def test_cli11_editar_direccion_cliente_no_existe(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_no_existe(monkeypatch)

    with pytest.raises(service.HTTPException) as exc:
        service.editar_direccion(
            conn, 999, 5, _payload_direccion_update(sector="X"), 1, "127.0.0.1"
        )

    _assert_http_error(exc, 404, "CLIENTE_NO_ENCONTRADO")


def test_cli11_editar_direccion_no_encontrada(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)
    monkeypatch.setattr(repository, "obtener_direccion", lambda c, cid, did: None)

    with pytest.raises(service.HTTPException) as exc:
        service.editar_direccion(
            conn, 10, 999, _payload_direccion_update(sector="X"), 1, "127.0.0.1"
        )

    _assert_http_error(exc, 404, "DIRECCION_NO_ENCONTRADA")


def test_cli11_editar_direccion_ciudad_invalida(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)

    dir_actual = _direccion_row(id_direccion=5)
    monkeypatch.setattr(repository, "obtener_direccion", lambda c, cid, did: dir_actual)
    monkeypatch.setattr(repository, "existe_ciudad", lambda c, cid, cod: False)

    with pytest.raises(service.HTTPException) as exc:
        service.editar_direccion(
            conn, 10, 5, _payload_direccion_update(id_ciudad=999), 1, "127.0.0.1"
        )

    _assert_http_error(exc, 422, "CATALOGO_INVALIDO")


# ---------------------------------------------------------------------------
# CLI-12 · Eliminar dirección (baja lógica)
# ---------------------------------------------------------------------------


def test_cli12_eliminar_direccion_caso_feliz(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)

    dir_actual = _direccion_row(id_direccion=5, es_principal=False)
    monkeypatch.setattr(repository, "obtener_direccion", lambda c, cid, did: dir_actual)
    monkeypatch.setattr(
        repository, "eliminar_direccion_logica", lambda c, cid, did: None
    )

    # No lanza excepción
    service.eliminar_direccion(conn, 10, 5)


def test_cli12_eliminar_direccion_principal_activa_409(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)

    dir_actual = _direccion_row(id_direccion=5, es_principal=True, estado="Activo")
    monkeypatch.setattr(repository, "obtener_direccion", lambda c, cid, did: dir_actual)

    with pytest.raises(service.HTTPException) as exc:
        service.eliminar_direccion(conn, 10, 5)

    _assert_http_error(exc, 409, "NO_SE_PUEDE_ELIMINAR_PRINCIPAL")


def test_cli12_eliminar_direccion_cliente_no_existe(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_no_existe(monkeypatch)

    with pytest.raises(service.HTTPException) as exc:
        service.eliminar_direccion(conn, 999, 5)

    _assert_http_error(exc, 404, "CLIENTE_NO_ENCONTRADO")


def test_cli12_eliminar_direccion_no_encontrada(monkeypatch):
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)
    monkeypatch.setattr(repository, "obtener_direccion", lambda c, cid, did: None)

    with pytest.raises(service.HTTPException) as exc:
        service.eliminar_direccion(conn, 10, 999)

    _assert_http_error(exc, 404, "DIRECCION_NO_ENCONTRADA")


def test_cli12_eliminar_direccion_principal_inactiva_ok(monkeypatch):
    """Una dirección principal con estado Inactivo SÍ se puede eliminar."""
    conn = _fake_conn()
    _patch_cliente_existe(monkeypatch)

    dir_actual = _direccion_row(id_direccion=5, es_principal=True, estado="Inactivo")
    monkeypatch.setattr(repository, "obtener_direccion", lambda c, cid, did: dir_actual)
    monkeypatch.setattr(
        repository, "eliminar_direccion_logica", lambda c, cid, did: None
    )

    # No lanza excepción
    service.eliminar_direccion(conn, 10, 5)
