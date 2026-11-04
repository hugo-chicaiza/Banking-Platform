"""Pruebas unitarias de:

- CLI-01 · GET /api/v1/clientes/validar-identificacion
- CLI-02 · POST /api/v1/clientes
- CLI-03 / CLI-04 / CLI-08 · Listado, detalle y perfil del cliente
- CLI-09 · GET /api/v1/clientes/{idCliente}/direcciones
- CLI-10 · POST /api/v1/clientes/{idCliente}/direcciones
- CLI-11 · PATCH /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
- CLI-12 · DELETE /api/v1/clientes/{idCliente}/direcciones/{idDireccion}
- CLI-13 / CLI-14 · Registro e historial de evaluaciones de riesgo

No requieren base de datos: se monkeypatcha el repositorio.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection

from app.main import app
from app.modules.clientes import repository, router, service
from app.modules.clientes.schemas import ClienteCreate, DireccionCreate, RiesgoCreate

# Cédulas y RUCs válidos conocidos
CEDULA_VALIDA_1 = "1710034065"
CEDULA_VALIDA_2 = "0926687856"
CEDULA_VALIDA_EXTERIOR = "3000000012"
RUC_VALIDO = "1710034065001"
PASAPORTE_VALIDO = "A12345678"


class _FakeConn:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


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


# CLI-13 / CLI-14 · Riesgo: respuestas SQL programadas, sin BD ni sockets.
def _payload_riesgo_create(**overrides: Any) -> RiesgoCreate:
    return RiesgoCreate(
        **{
            "nivel_riesgo_laft": "Bajo",
            "resultado_evaluacion": "Aprobado",
            **overrides,
        }
    )


def _riesgo_row(**overrides: Any) -> dict[str, Any]:
    return {
        **_payload_riesgo_create().model_dump(),
        "id_evaluacion": 20,
        "id_cliente": 10,
        "fecha_evaluacion": datetime(2026, 11, 3, 15, tzinfo=UTC),
        "evaluador": 1,
        "es_vigente": True,
        "estado_cliente": "Activo",
        **overrides,
    }


class _RiesgoConn(_FakeConn):
    """Respuestas de SQL Server; no implementa ni prueba el trigger real."""

    def __init__(self, respuestas: list[list[dict[str, Any]]]) -> None:
        super().__init__()
        self.respuestas = respuestas.copy()
        self.consultas: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: Any, params: dict[str, Any]) -> MagicMock:
        self.consultas.append((str(statement), params))
        resultado = MagicMock()
        resultado.mappings.return_value = self.respuestas.pop(0)
        return resultado


@pytest.mark.parametrize(
    ("estado_inicial", "resultado", "estado_final"),
    [
        ("Pendiente", "Aprobado", "Activo"),
        ("Pendiente", "Rechazado", "Bloqueado"),
        ("Activo", "Rechazado", "Bloqueado"),
        ("Pendiente", "Observado", "Pendiente"),
        ("Activo", "Observado", "Activo"),
        ("Bloqueado", "Aprobado", "Bloqueado"),
    ],
)
def test_cli13_lee_vigencia_y_estado_posteriores_al_trigger(
    estado_inicial: str, resultado: str, estado_final: str
):
    fila = _riesgo_row(resultado_evaluacion=resultado, estado_cliente=estado_final)
    db = _RiesgoConn(
        [
            [{"id_cliente": 10, "estado": estado_inicial}],
            [{"id_evaluacion": 20}],
            [fila],
            [],
        ]
    )
    riesgo = service.registrar_evaluacion_riesgo(
        cast(Connection, db),
        10,
        _payload_riesgo_create(resultado_evaluacion=resultado),
        1,
        "192.0.2.10",
    )

    assert riesgo.estado_cliente == estado_final
    assert riesgo.es_vigente is True
    assert riesgo.id_evaluacion == 20
    assert riesgo.fecha_evaluacion == fila["fecha_evaluacion"]
    assert (db.commits, db.rollbacks) == (1, 0)
    assert not db.respuestas
    insert_sql, insert_params = db.consultas[1]
    assert "OUTPUT INSERTED.IdEvaluacion INTO" in insert_sql
    assert ":observaciones, 0" in insert_sql
    assert insert_params["evaluador"] == 1
    assert insert_params["id_cliente"] == 10
    assert db.consultas[2][1]["id_evaluacion"] == 20
    audit_sql, audit_params = db.consultas[3]
    assert "INSERT INTO Clientes.ClientesHis" in audit_sql
    assert audit_params["tipo_operacion"] == "I"
    assert audit_params["direccion_ip"] == "192.0.2.10"
    assert audit_params["modificado_por"] == 1


def test_cli13_antecedente_activo_y_parametros_ligados():
    observaciones = "Revisión 'PEP'; -- texto sin interpolar"
    payload = _payload_riesgo_create(
        nivel_riesgo_laft="Alto",
        es_pep=True,
        tiene_antecedentes=True,
        id_tipo_antecedente=2,
        observaciones=observaciones,
    )
    db = _RiesgoConn(
        [
            [{"id_cliente": 10, "estado": "Pendiente"}],
            [{"existe": 1}],
            [{"id_evaluacion": 20}],
            [_riesgo_row(**payload.model_dump(), evaluador=12)],
            [],
        ]
    )
    riesgo = service.registrar_evaluacion_riesgo(
        cast(Connection, db), 10, payload, 12, "192.0.2.10"
    )
    assert riesgo.tiene_antecedentes is True
    assert riesgo.id_tipo_antecedente == 2
    assert riesgo.es_pep is True
    catalogo_sql, catalogo_params = db.consultas[1]
    assert "Estado = 'Activo'" in catalogo_sql
    assert catalogo_params == {"id_tipo_antecedente": 2}
    insert_sql, insert_params = db.consultas[2]
    assert observaciones not in insert_sql
    assert insert_params["observaciones"] == observaciones
    assert insert_params["evaluador"] == 12


@pytest.mark.parametrize(
    "cambios",
    [
        {"tiene_antecedentes": True},
        {"tiene_antecedentes": True, "id_tipo_antecedente": None},
        {"tiene_antecedentes": False, "id_tipo_antecedente": 1},
        {"id_tipo_antecedente": 1},
        {"id_tipo_antecedente": 0},
    ],
)
def test_cli13_antecedentes_incoherentes_422(monkeypatch, cambios):
    _patch_cliente_existe(monkeypatch)
    insertar = MagicMock()
    catalogo = MagicMock()
    monkeypatch.setattr(repository, "insertar_evaluacion_riesgo", insertar)
    monkeypatch.setattr(repository, "existe_tipo_antecedente_activo", catalogo)
    with pytest.raises(service.HTTPException) as exc:
        service.registrar_evaluacion_riesgo(
            _fake_conn(), 10, _payload_riesgo_create(**cambios), 1, "192.0.2.10"
        )
    _assert_http_error(exc, 422, "ANTECEDENTE_REQUERIDO")
    insertar.assert_not_called()
    catalogo.assert_not_called()


@pytest.mark.parametrize("id_tipo", [999, 2])
def test_cli13_catalogo_inexistente_o_inactivo_422(id_tipo):
    db = _RiesgoConn([[{"id_cliente": 10, "estado": "Activo"}], []])
    with pytest.raises(service.HTTPException) as exc:
        service.registrar_evaluacion_riesgo(
            cast(Connection, db),
            10,
            _payload_riesgo_create(
                tiene_antecedentes=True, id_tipo_antecedente=id_tipo
            ),
            1,
            "192.0.2.10",
        )
    _assert_http_error(exc, 422, "CATALOGO_INVALIDO")
    assert len(db.consultas) == 2
    assert db.commits == 0


@pytest.mark.parametrize(
    ("cliente", "status", "code"),
    [
        (None, 404, "CLIENTE_NO_ENCONTRADO"),
        ({"id_cliente": 10, "estado": "Eliminado"}, 409, "CLIENTE_ELIMINADO"),
    ],
)
def test_cli13_cliente_invalido(cliente, status, code):
    db = _RiesgoConn([[cliente] if cliente else []])
    with pytest.raises(service.HTTPException) as exc:
        service.registrar_evaluacion_riesgo(
            cast(Connection, db), 10, _payload_riesgo_create(), 1, "192.0.2.10"
        )
    _assert_http_error(exc, status, code)
    assert len(db.consultas) == 1
    assert db.commits == 0


@pytest.mark.parametrize("etapa", ["insertar", "leer", "auditar", "commit"])
def test_cli13_revierte_transaccion_ante_fallos(etapa):
    class _FallaConn(_RiesgoConn):
        def execute(self, statement: Any, params: dict[str, Any]) -> MagicMock:
            if len(self.consultas) == {"insertar": 1, "leer": 2, "auditar": 3}.get(
                etapa, -1
            ):
                raise RuntimeError("Fallo simulado")
            return super().execute(statement, params)

        def commit(self) -> None:
            if etapa == "commit":
                raise RuntimeError("Fallo simulado")
            super().commit()

    db = _FallaConn(
        [
            [{"id_cliente": 10, "estado": "Pendiente"}],
            [{"id_evaluacion": 20}],
            [_riesgo_row()],
            [],
        ]
    )
    with pytest.raises(RuntimeError, match="Fallo simulado"):
        service.registrar_evaluacion_riesgo(
            cast(Connection, db), 10, _payload_riesgo_create(), 1, "192.0.2.10"
        )
    assert (db.commits, db.rollbacks) == (0, 1)


@pytest.mark.parametrize("respuestas", [[[]], [[{"id_evaluacion": 20}], []]])
def test_cli13_no_confirma_si_no_se_recupera_la_evaluacion(respuestas):
    db = _RiesgoConn([[{"id_cliente": 10, "estado": "Pendiente"}], *respuestas])
    with pytest.raises(RuntimeError, match="evaluación"):
        service.registrar_evaluacion_riesgo(
            cast(Connection, db), 10, _payload_riesgo_create(), 1, "192.0.2.10"
        )
    assert (db.commits, db.rollbacks) == (0, 1)


def test_cli14_historial_ordenado_y_vigencia():
    filas = [
        _riesgo_row(),
        _riesgo_row(id_evaluacion=19, es_vigente=False),
        _riesgo_row(
            id_evaluacion=18,
            fecha_evaluacion=datetime(2026, 11, 2, 15, tzinfo=UTC),
            es_vigente=False,
        ),
    ]
    db = _RiesgoConn([[{"id_cliente": 10, "estado": "Activo"}], filas])
    historial = service.listar_evaluaciones_riesgo(cast(Connection, db), 10)
    assert [r.id_evaluacion for r in historial] == [20, 19, 18]
    assert [r.es_vigente for r in historial] == [True, False, False]
    sql, params = db.consultas[1]
    assert "ORDER BY r.FechaEvaluacion DESC, r.IdEvaluacion DESC" in sql
    assert params == {
        "id_cliente": 10,
        "id_evaluacion": None,
        "solo_vigente": False,
    }
    assert (db.commits, db.rollbacks) == (0, 0)


@pytest.mark.parametrize("estado", ["Activo", "Eliminado"])
def test_cli14_historial_vacio(estado):
    db = _RiesgoConn([[{"id_cliente": 10, "estado": estado}], []])
    assert service.listar_evaluaciones_riesgo(cast(Connection, db), 10) == []


def test_cli14_cliente_no_encontrado_404():
    db = _RiesgoConn([[]])
    with pytest.raises(service.HTTPException) as exc:
        service.listar_evaluaciones_riesgo(cast(Connection, db), 999)
    _assert_http_error(exc, 404, "CLIENTE_NO_ENCONTRADO")


@pytest.mark.parametrize(
    "cambios",
    [
        {"nivel_riesgo_laft": "Critico"},
        {"resultado_evaluacion": "Pendiente"},
        {"observaciones": "x" * 251},
    ],
)
def test_riesgo_rechaza_valores_fuera_del_contrato(cambios):
    with pytest.raises(ValidationError):
        _payload_riesgo_create(**cambios)


def test_riesgo_aliases_defaults_y_limite_observaciones():
    payload = RiesgoCreate.model_validate(
        {
            "nivelRiesgoLAFT": "Medio",
            "resultadoEvaluacion": "Observado",
            "observaciones": "x" * 250,
        }
    )
    assert payload.es_pep is False
    assert payload.tiene_antecedentes is False
    assert payload.id_tipo_antecedente is None
    serializado = payload.model_dump(by_alias=True)
    assert serializado["nivelRiesgoLAFT"] == "Medio"
    assert serializado["esPEP"] is False
    assert "nivelRiesgoLaft" not in serializado


def test_riesgo_contrato_openapi_sin_sockets():
    from app.core.errors import ProblemDetailsRoute

    contrato = app.openapi()
    path = contrato["paths"]["/api/v1/clientes/{idCliente}/evaluaciones-riesgo"]
    for metodo, operacion, status in [
        ("post", "CLI13", "201"),
        ("get", "CLI14", "200"),
    ]:
        assert path[metodo]["operationId"] == operacion
        assert status in path[metodo]["responses"]
        assert "application/problem+json" in path[metodo]["responses"]["404"]["content"]
    assert path["post"]["x-roles"] == ["ASESOR", "SUPERVISOR", "ADMIN"]
    assert "AUDITOR" in path["get"]["x-roles"]
    assert "AUDITOR" not in path["post"]["x-roles"]
    rutas = [
        r
        for r in router._riesgo_router.routes
        if isinstance(r, ProblemDetailsRoute) and "evaluaciones-riesgo" in r.path
    ]
    assert len(rutas) == 2
    assert all(isinstance(r, ProblemDetailsRoute) for r in rutas)


def test_cli13_router_propaga_evaluador_e_ip(monkeypatch):
    from starlette.requests import Request

    registrar = MagicMock(return_value=service.RiesgoRegistrado(**_riesgo_row()))
    monkeypatch.setattr(service, "registrar_evaluacion_riesgo", registrar)
    request = Request(
        {
            "type": "http",
            "headers": [(b"x-forwarded-for", b"192.0.2.10, 192.0.2.20")],
        }
    )
    conn = _fake_conn()
    payload = _payload_riesgo_create()
    resultado = router.registrar_evaluacion_riesgo(10, payload, request, conn)
    registrar.assert_called_once_with(conn, 10, payload, 1, "192.0.2.10")
    assert resultado.es_vigente is True


def _cliente_row(**overrides: Any) -> dict[str, Any]:
    datos = _payload_natural_valido().model_dump(exclude={"direccion"})
    return {
        **datos,
        "id_cliente": 10,
        "estado": "Activo",
        "fecha_consentimiento": datetime(2026, 11, 3, 15, tzinfo=UTC),
        "fecha_registro": datetime(2026, 11, 3, 15, tzinfo=UTC),
        "creado_por": 1,
        **overrides,
    }


def _perfil_mock(**overrides: Any) -> dict[str, Any]:
    return {
        "cuentas": [
            {
                "id_cuenta": 30,
                "numero_cuenta": "100200300401",
                "id_cliente": 10,
                "id_agencia": "001",
                "id_producto": 1,
                "tipo_cuenta": "Ahorro",
                "id_moneda": 840,
                "saldo": "150.25",
                "saldo_retenido": "20.00",
                "saldo_disponible": "130.25",
                "estado": "ACTIVA",
                "fecha_apertura": datetime(2026, 11, 1, 15, tzinfo=UTC),
            }
        ],
        "tarjetas": [
            {
                "id_tarjeta": 40,
                "token_tarjeta": "TOKEN_FICTICIO",
                "numero_enmascarado": "************1234",
                "tipo_tarjeta": "Debito",
                "nombre_tarjeta": "MARIA LOPEZ",
                "id_cliente": 10,
                "id_cuenta": 30,
                "id_producto": 2,
                "estado_actual": "Activa",
                "pin_asignado": True,
                "fecha_emision": date(2026, 11, 1),
                "fecha_expiracion": date(2030, 11, 1),
            }
        ],
        "creditos": [
            {
                "id_solicitud": 50,
                "numero_solicitud": "SOL-50",
                "tipo_credito": "Consumo",
                "monto_desembolsado": "1000.00",
                "saldo_capital": "500.00",
                "proxima_cuota": date(2026, 12, 1),
                "estado": "DESEMBOLSADA",
            }
        ],
        **overrides,
    }


def _assert_solo_lectura(db: _RiesgoConn) -> None:
    assert not db.respuestas
    assert (db.commits, db.rollbacks) == (0, 0)
    assert all(
        palabra not in sql.upper()
        for sql, _ in db.consultas
        for palabra in ("INSERT ", "UPDATE ", "DELETE ")
    )


def test_cli03_filtros_combinados_y_direcciones_en_lote():
    db = _RiesgoConn(
        [
            [_cliente_row(total=2), _cliente_row(id_cliente=11, total=2)],
            [
                _direccion_row(id_cliente=10),
                _direccion_row(id_cliente=10, id_direccion=2),
            ],
        ]
    )
    resultado = service.listar_clientes(
        cast(Connection, db),
        q="María",
        identificacion=CEDULA_VALIDA_1,
        tipo_cliente="Natural",
        estado="Activo",
    )
    assert (resultado.page, resultado.page_size, resultado.total) == (1, 20, 2)
    assert [c.id_cliente for c in resultado.items] == [10, 11]
    assert [d.id_direccion for d in resultado.items[0].direcciones] == [1, 2]
    assert resultado.items[1].direcciones == []
    sql, params = db.consultas[0]
    assert params["q_like"] == "%María%"
    assert params["identificacion"] == CEDULA_VALIDA_1
    assert params["tipo_cliente"] == "Natural"
    assert params["estado"] == "Activo"
    assert "Identificacion = :identificacion" in sql
    assert "TipoCliente = :tipo_cliente" in sql
    assert "Estado = :estado" in sql
    for columna in ("Identificacion", "Nombres", "Apellidos", "RazonSocial"):
        assert f"{columna} LIKE :q_like" in sql
    assert db.consultas[1][1] == {"ids_clientes": [10, 11], "solo_activas": False}
    assert resultado.model_dump(by_alias=True)["pageSize"] == 20
    _assert_solo_lectura(db)


@pytest.mark.parametrize("q", [None, "Lopez", "1710", "Empresa", "' OR 1=1 --"])
def test_cli03_q_usa_parametros_ligados(q):
    db = _RiesgoConn([[{"id_cliente": None, "total": 0}]])
    resultado = service.listar_clientes(cast(Connection, db), q=q)
    sql, params = db.consultas[0]
    assert params["q_like"] == (None if q is None else f"%{q}%")
    assert (params["campo"], params["direccion"]) == ("IdCliente", "asc")
    if q is not None:
        assert q not in sql
    assert resultado.items == []
    assert resultado.total == 0
    _assert_solo_lectura(db)


@pytest.mark.parametrize(("page", "page_size", "total"), [(1, 20, 0), (3, 2, 4)])
def test_cli03_pagina_vacia_conserva_total(page, page_size, total):
    db = _RiesgoConn([[{"id_cliente": None, "total": total}]])
    resultado = service.listar_clientes(
        cast(Connection, db), page=page, page_size=page_size
    )
    assert resultado.items == []
    assert (resultado.page, resultado.page_size, resultado.total) == (
        page,
        page_size,
        total,
    )
    params = db.consultas[0][1]
    assert params["offset"] == (page - 1) * page_size
    assert params["limite"] == page * page_size
    _assert_solo_lectura(db)


@pytest.mark.parametrize("campo", list(service.CAMPOS_ORDEN_CLIENTES))
@pytest.mark.parametrize("direccion", ["asc", "desc"])
def test_cli03_orden_valido_y_paginacion(campo, direccion):
    db = _RiesgoConn([[_cliente_row(total=7)], []])
    resultado = service.listar_clientes(
        cast(Connection, db), page=2, page_size=3, sort=f"{campo},{direccion}"
    )
    sql, params = db.consultas[0]
    assert params["campo"] == service.CAMPOS_ORDEN_CLIENTES[campo]
    assert params["direccion"] == direccion
    assert (params["offset"], params["limite"]) == (3, 6)
    assert f":campo = '{params['campo']}' AND :direccion = '{direccion}'" in sql
    assert "IdCliente ASC" in sql
    assert (resultado.page, resultado.page_size, resultado.total) == (2, 3, 7)
    _assert_solo_lectura(db)


@pytest.mark.parametrize(
    "sort",
    [
        "",
        "nombres",
        "nombres,",
        ",asc",
        "nombres,ASC",
        "nombres,otro",
        "desconocido,asc",
        "nombres,asc,desc",
        "nombres; DROP TABLE Cliente,asc",
        "nombres,desc;--",
        " nombres,asc",
    ],
)
def test_cli03_sort_invalido_400_antes_de_consultar(sort):
    db = _RiesgoConn([])
    with pytest.raises(service.HTTPException) as exc:
        service.listar_clientes(cast(Connection, db), sort=sort)
    _assert_http_error(exc, 400, "SORT_INVALIDO")
    assert db.consultas == []


@pytest.mark.parametrize("direcciones", [[], [_direccion_row(id_cliente=10)]])
def test_cli04_detalle_solicita_solo_direcciones_activas(direcciones):
    db = _RiesgoConn([[_cliente_row(total=1)], direcciones])
    cliente = service.obtener_cliente(cast(Connection, db), 10)
    assert cliente.id_cliente == 10
    assert len(cliente.direcciones) == len(direcciones)
    assert all(d.estado == "Activo" for d in cliente.direcciones)
    assert db.consultas[0][1]["id_cliente"] == 10
    sql, params = db.consultas[1]
    assert "Estado = 'Activo'" in sql
    assert params == {"ids_clientes": [10], "solo_activas": True}
    _assert_solo_lectura(db)


@pytest.mark.parametrize(
    "consulta", [service.obtener_cliente, service.obtener_perfil_cliente]
)
def test_consulta_cliente_inexistente_404_sin_consultar_productos(consulta):
    db = _RiesgoConn([[{"id_cliente": None, "total": 0}]])
    with pytest.raises(service.HTTPException) as exc:
        consulta(cast(Connection, db), 999)
    _assert_http_error(exc, 404, "CLIENTE_NO_ENCONTRADO")
    assert len(db.consultas) == 1
    _assert_solo_lectura(db)


@pytest.mark.parametrize("con_productos", [True, False])
def test_cli08_perfil_integral_con_y_sin_productos(con_productos):
    productos = (
        _perfil_mock()
        if con_productos
        else _perfil_mock(cuentas=[], tarjetas=[], creditos=[])
    )
    riesgos = [_riesgo_row()] if con_productos else []
    db = _RiesgoConn(
        [
            [_cliente_row(total=1)],
            [_direccion_row(id_cliente=10)],
            riesgos,
            productos["cuentas"],
            productos["tarjetas"],
            productos["creditos"],
        ]
    )
    perfil = service.obtener_perfil_cliente(cast(Connection, db), 10)
    assert perfil.cliente.id_cliente == 10
    assert [d.estado for d in perfil.cliente.direcciones] == ["Activo"]
    assert db.consultas[1][1]["solo_activas"] is True
    riesgo_sql, riesgo_params = db.consultas[2]
    assert "r.EsVigente = 1" in riesgo_sql
    assert riesgo_params["solo_vigente"] is True
    for (sql, params), tabla in zip(
        db.consultas[3:],
        ["Cuentas.Cuenta", "Tarjeta.Tarjeta", "Credito.CreditoSolicitud"],
        strict=True,
    ):
        assert tabla in sql
        assert params == {"id_cliente": 10}
        assert ":id_cliente" in sql
    assert "RTRIM(NumeroEnmascarado)" in db.consultas[4][0]
    assert "HashNumeroTarjeta" not in db.consultas[4][0]
    assert "LEFT JOIN Credito.CreditoResumen" in db.consultas[5][0]
    serializado = perfil.model_dump(mode="json", by_alias=True)
    if con_productos:
        assert perfil.riesgo_vigente is not None
        assert perfil.riesgo_vigente.id_evaluacion == 20
        assert serializado["riesgoVigente"]["nivelRiesgoLAFT"] == "Bajo"
        assert serializado["cuentas"][0]["saldoDisponible"] == 130.25
        assert serializado["tarjetas"][0]["numeroEnmascarado"] == "************1234"
        assert serializado["creditos"][0]["saldoCapital"] == 500.0
        assert "pan" not in {k.lower() for k in serializado["tarjetas"][0]}
    else:
        assert serializado["riesgoVigente"] is None
        assert all(
            serializado[campo] == [] for campo in ("cuentas", "tarjetas", "creditos")
        )
    _assert_solo_lectura(db)


def test_cli08_solicitud_sin_desembolso_admite_resumen_nulo():
    productos = _perfil_mock()
    credito = productos["creditos"][0]
    credito.update(monto_desembolsado=None, saldo_capital=None, proxima_cuota=None)
    db = _RiesgoConn([[_cliente_row(total=1)], [], [], [], [], [credito]])
    perfil = service.obtener_perfil_cliente(cast(Connection, db), 10)
    assert len(perfil.creditos) == 1
    assert perfil.creditos[0].monto_desembolsado is None
    assert perfil.creditos[0].saldo_capital is None
    assert perfil.creditos[0].proxima_cuota is None
    _assert_solo_lectura(db)


def test_consultas_contrato_openapi_sin_sockets():
    from app.core.errors import ProblemDetailsRoute

    contrato = app.openapi()
    for sufijo, operacion, modelo, roles in [
        ("", "CLI03", "PageCliente", router._ROLES_CONSULTA),
        ("/{idCliente}", "CLI04", "Cliente", router._ROLES_CONSULTA),
        (
            "/{idCliente}/perfil",
            "CLI08",
            "ClientePerfil",
            ["ASESOR", "SUPERVISOR", "ADMIN"],
        ),
    ]:
        ruta = contrato["paths"][f"/api/v1/clientes{sufijo}"]["get"]
        assert ruta["operationId"] == operacion
        assert ruta["x-roles"] == roles
        respuesta = ruta["responses"]["200"]["content"]["application/json"]["schema"]
        assert respuesta["$ref"].endswith(f"/{modelo}")
        for status in ("400", "401", "403", "404"):
            assert "application/problem+json" in ruta["responses"][status]["content"]
    parametros = {
        p["name"]: p["schema"]
        for p in contrato["paths"]["/api/v1/clientes"]["get"]["parameters"]
    }
    assert set(parametros) == {
        "q",
        "identificacion",
        "tipoCliente",
        "estado",
        "page",
        "pageSize",
        "sort",
    }
    assert parametros["page"]["default"] == 1
    assert parametros["page"]["minimum"] == 1
    assert parametros["pageSize"]["default"] == 20
    assert parametros["pageSize"]["minimum"] == 1
    assert parametros["pageSize"]["maximum"] == 100
    assert all(
        isinstance(r, ProblemDetailsRoute) for r in router._consultas_router.routes
    )
