"""E5-05 · Buscar clientes y ver su ficha con datos enmascarados (#49).

Un caso por criterio: datos enmascarados del servidor (AC1), documento fuera de la URL
(AC2), búsqueda sin filtro 400 (AC3), revelación auditada con MFA (AC4) y no-store (AC5).
"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Connection
from workos.exceptions import BadRequestException

from app.core.api.rate_limit import _clasificar
from app.core.database.db import cooperativa
from app.main import app
from app.modules.clientes import correos, repository, revelacion, service
from app.modules.clientes.schemas import (
    Cliente,
    ClienteBusqueda,
    ClientePerfil,
    Direccion,
    PageCliente,
)
from app.modules.clientes.visibilidad import (
    aplicar_visibilidad,
    enmascarar_email,
    enmascarar_telefono,
)
from tests.sesion import USUARIO, simular_sesion, usuario_con_roles

BASE = "/api/v1/clientes"
FECHA = datetime(2026, 11, 3, 15, tzinfo=UTC)


def _cliente(**cambios: Any) -> Cliente:
    datos: dict[str, Any] = {
        "id_cliente": 10,
        "identificacion": "1710034065",
        "tipo_documento": "C",
        "tipo_cliente": "Natural",
        "nombres": "María José",
        "apellidos": "López",
        "fecha_nacimiento": date(1990, 5, 14),
        "genero": "F",
        "estado_civil": "Soltero",
        "codigo_pais_nacionalidad": "ECU",
        "telefono_convencional": "022345678",
        "telefono_celular": "0991234567",
        "email": "maria.lopez@correo.ec",
        "consentimiento_datos": True,
        "fecha_consentimiento": FECHA,
        "estado": "Activo",
        "fecha_registro": FECHA,
        "creado_por": 1,
        "id_agencia_registro": "001",
        "direcciones": [
            Direccion(
                id_direccion=1,
                tipo_direccion="Domicilio",
                codigo_pais="ECU",
                id_ciudad=1,
                calle_direccion="Av. 1",
                referencia_ubicacion="Parque",
                es_principal=True,
            )
        ],
    }
    return Cliente(**(datos | cambios))


@pytest.fixture
def http() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def _sesion(*roles: str, permisos: tuple[str, ...] = ()) -> None:
    usuario = usuario_con_roles(*roles)
    simular_sesion(app, replace(usuario, permisos=usuario.permisos + permisos))
    app.dependency_overrides[cooperativa] = lambda: MagicMock()


# ---------------------------------------------------------------------------
# AC1 · enmascarado en el servidor y ficha reducida del cajero
# ---------------------------------------------------------------------------


def test_mascaras_dejan_solo_lo_necesario_para_reconocer():
    assert enmascarar_email("maria.lopez@correo.ec") == "m***@correo.ec"
    assert enmascarar_email("a@x.ec") == "***@x.ec"
    assert enmascarar_telefono("0991234567") == "******4567"
    assert enmascarar_telefono(None) is None


@pytest.mark.parametrize(
    "roles", [("ASESOR",), ("SUPERVISOR",), ("ADMIN",), ("CAJERO",)]
)
def test_ningun_rol_recibe_datos_completos(roles, monkeypatch):
    monkeypatch.setattr("app.modules.seguridad.funciones.activa", lambda: False)
    visto = aplicar_visibilidad(_cliente(), usuario_con_roles(*roles))
    assert visto.identificacion == "******4065"
    assert visto.email == "m***@correo.ec"
    assert visto.telefono_celular == "******4567"
    assert visto.telefono_convencional == "*****5678"
    assert "1710034065" not in visto.model_dump_json()


def test_cajero_ve_ficha_reducida_sin_direcciones(monkeypatch):
    monkeypatch.setattr("app.modules.seguridad.funciones.activa", lambda: False)
    assert (
        aplicar_visibilidad(_cliente(), usuario_con_roles("CAJERO")).direcciones == []
    )
    assert aplicar_visibilidad(_cliente(), usuario_con_roles("ASESOR")).direcciones


def test_listado_y_perfil_tambien_se_enmascaran(monkeypatch):
    monkeypatch.setattr("app.modules.seguridad.funciones.activa", lambda: False)
    usuario = usuario_con_roles("ASESOR")
    pagina = aplicar_visibilidad(
        PageCliente(items=[_cliente()], page=1, page_size=20, total=1), usuario
    )
    perfil = aplicar_visibilidad(ClientePerfil(cliente=_cliente()), usuario)
    assert pagina.items[0].identificacion == "******4065"
    assert perfil.cliente.email == "m***@correo.ec"


def test_ficha_http_llega_enmascarada_y_sin_cache(http, monkeypatch):
    _sesion("ASESOR")
    monkeypatch.setattr(service, "obtener_cliente", lambda conn, i: _cliente())
    respuesta = http.get(f"{BASE}/10")
    assert respuesta.status_code == 200
    assert respuesta.json()["identificacion"] == "******4065"
    assert respuesta.headers["cache-control"] == "no-store"  # AC5


def test_correos_secundarios_tambien_se_enmascaran(http, monkeypatch):
    _sesion("ASESOR")
    monkeypatch.setattr(
        repository, "obtener_cliente_por_id", lambda c, i: {"id_cliente": 10}
    )
    monkeypatch.setattr(
        correos,
        "listar_activos",
        lambda c, i: [
            {
                "id_cliente_email": 1,
                "email": "otro.correo@example.com",
                "etiqueta": "Trabajo",
                "verificado": False,
                "fecha_verificacion": None,
                "fecha_creacion": FECHA,
            }
        ],
    )
    respuesta = http.get(f"{BASE}/10/emails")
    assert respuesta.json()[0]["email"] == "o***@example.com"
    assert respuesta.headers["cache-control"] == "no-store"


# ---------------------------------------------------------------------------
# AC2 y AC3 · búsqueda por POST y siempre con filtro
# ---------------------------------------------------------------------------


def test_la_busqueda_ya_no_acepta_filtros_en_la_url(http):
    _sesion("ASESOR")
    assert http.get(f"{BASE}?identificacion=1710034065").status_code == 405
    contrato = app.openapi()["paths"][f"{BASE}/busqueda"]
    assert set(contrato) == {"post"}
    assert "parameters" not in contrato["post"]


def test_busqueda_por_documento_va_en_el_cuerpo(http, monkeypatch):
    _sesion("CAJERO")
    llamada = MagicMock(return_value=([], 0))
    monkeypatch.setattr(repository, "consultar_clientes", llamada)
    respuesta = http.post(f"{BASE}/busqueda", json={"identificacion": "1710034065"})
    assert respuesta.status_code == 200
    assert respuesta.json() == {"items": [], "page": 1, "pageSize": 20, "total": 0}
    assert llamada.call_args.kwargs["identificacion"] == "1710034065"
    assert respuesta.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("cuerpo", [{}, {"tipoCliente": "Natural"}, {"page": 2}])
def test_busqueda_sin_filtro_es_400(http, cuerpo):
    _sesion("ASESOR")
    respuesta = http.post(f"{BASE}/busqueda", json=cuerpo)
    assert respuesta.status_code == 400
    assert respuesta.json()["code"] == "FILTRO_REQUERIDO"


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"nombre": "Ma"},
        {"nombre": "Mar\x00ia"},
        {"email": "sin-arroba"},
        {"idAgenciaRegistro": "1"},
        {"identificacion": "1710034065", "extra": 1},
        {"identificacion": "1710034065", "pageSize": 101},
    ],
)
def test_busqueda_valida_el_cuerpo(http, cuerpo):
    _sesion("ASESOR")
    assert (
        http.post(f"{BASE}/busqueda", json=cuerpo).json()["code"] == "DATOS_INVALIDOS"
    )


def test_correo_de_busqueda_se_compara_en_minusculas():
    assert ClienteBusqueda(email="Maria@Correo.EC").email == "maria@correo.ec"


def test_busqueda_por_nombre_escapa_comodines():
    assert repository.patron_inicio("mar_ía%") == "MAR\\_ÍA\\%%"
    assert repository.patron_inicio("a[b]") == "A\\[B]%"


def test_sql_de_nombre_busca_inicio_de_palabra_sin_concatenar_texto():
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value = []
    repository.consultar_clientes(cast(Connection, conn), nombre="lop", estado="Activo")
    sql = str(conn.execute.call_args.args[0])
    params = conn.execute.call_args.args[1]
    assert "NombreBusqueda LIKE :nombre_inicio ESCAPE" in sql
    assert params["nombre_inicio"] == "LOP%"
    assert params["nombre_palabra"] == "% LOP%"
    assert "lop" not in sql.lower().replace(":nombre", "")


def test_sin_permiso_de_consulta_es_403(http):
    _sesion("CONTADOR")
    assert http.post(f"{BASE}/busqueda", json={"estado": "Activo"}).status_code == 403


# ---------------------------------------------------------------------------
# AC4 · revelación con MFA y auditoría
# ---------------------------------------------------------------------------


class _WorkOS:
    def __init__(
        self, factores=("auth_factor_1",), valido=True, factor_reto="auth_factor_1"
    ):
        self.factores = factores
        self.valido = valido
        self.factor_reto = factor_reto
        self.verificado: list[tuple[str, str]] = []
        self.user_management = SimpleNamespace(list_auth_factors=self._listar)
        self.mfa = SimpleNamespace(
            challenge_factor=self._retar, verify_challenge=self._verificar
        )

    def _listar(self, *, user_id):
        assert user_id == USUARIO.id_usuario
        return [SimpleNamespace(id=f, type="totp") for f in self.factores]

    def _retar(self, *, authentication_factor_id):
        return SimpleNamespace(
            id="auth_challenge_1",
            expires_at=None,
            code="999999",
            authentication_factor_id=authentication_factor_id,
        )

    def _verificar(self, *, authentication_challenge_id, code):
        self.verificado.append((authentication_challenge_id, code))
        if self.valido is None:
            raise BadRequestException(MagicMock(status_code=400), {"message": "x"})
        return SimpleNamespace(
            valid=self.valido,
            challenge=SimpleNamespace(authentication_factor_id=self.factor_reto),
        )


@pytest.fixture
def mfa(monkeypatch):
    def instalar(**kw):
        falso = _WorkOS(**kw)
        monkeypatch.setattr(revelacion, "get_workos", lambda: falso)
        monkeypatch.setattr(service, "obtener_cliente", lambda conn, i: _cliente())
        monkeypatch.setattr(
            correos, "listar_activos", lambda c, i: [{"email": "otro@example.com"}]
        )
        return falso

    return instalar


SOLICITUD = {
    "campos": ["identificacion", "email"],
    "idDesafio": "auth_challenge_1",
    "codigo": "123456",
}


def test_desafio_no_entrega_el_codigo(http, mfa):
    _sesion("ASESOR")
    mfa()
    cuerpo = http.post(f"{BASE}/10/revelacion/desafio").json()
    assert cuerpo == {"idDesafio": "auth_challenge_1", "expiraEn": None}


def test_sin_factor_mfa_no_hay_revelacion(http, mfa):
    _sesion("ASESOR")
    mfa(factores=())
    respuesta = http.post(f"{BASE}/10/revelacion/desafio")
    assert (respuesta.status_code, respuesta.json()["code"]) == (
        409,
        "MFA_NO_CONFIGURADO",
    )


def test_revelacion_valida_devuelve_solo_lo_pedido_y_audita(
    http, mfa, eventos_auditados
):
    _sesion("ASESOR")
    falso = mfa()
    respuesta = http.post(f"{BASE}/10/revelacion", json=SOLICITUD)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["identificacion"] == "1710034065"
    assert cuerpo["email"] == "maria.lopez@correo.ec"
    assert cuerpo["telefonoCelular"] is None and cuerpo["correosSecundarios"] is None
    assert falso.verificado == [("auth_challenge_1", "123456")]
    assert respuesta.headers["cache-control"] == "no-store"
    (evento,) = eventos_auditados
    assert (evento.accion, evento.resultado, evento.id_registro) == (
        "CLI_DATO_REVELADO",
        "Exitoso",
        "10",
    )
    assert evento.descripcion == "Campos: identificacion, email"
    assert "1710034065" not in evento.descripcion
    assert "maria" not in evento.descripcion


@pytest.mark.parametrize(
    "caso",
    [{"valido": False}, {"valido": None}, {"factor_reto": "auth_factor_de_otro"}],
)
def test_codigo_invalido_o_ajeno_se_rechaza_y_audita(
    http, mfa, eventos_auditados, caso
):
    _sesion("ASESOR")
    mfa(**caso)
    respuesta = http.post(f"{BASE}/10/revelacion", json=SOLICITUD)
    assert (respuesta.status_code, respuesta.json()["code"]) == (422, "MFA_INVALIDO")
    assert "1710034065" not in respuesta.text
    (evento,) = eventos_auditados
    assert (evento.accion, evento.resultado) == ("CLI_DATO_REVELADO", "Fallido")


def test_correos_secundarios_se_revelan_si_se_piden(http, mfa):
    _sesion("SUPERVISOR")
    mfa()
    cuerpo = http.post(
        f"{BASE}/10/revelacion", json={**SOLICITUD, "campos": ["correosSecundarios"]}
    ).json()
    assert cuerpo["correosSecundarios"] == ["otro@example.com"]


@pytest.mark.parametrize("roles", [("CAJERO",), ("AUDITOR",), ("CONTADOR",)])
def test_solo_asesor_supervisor_y_admin_revelan(http, mfa, roles):
    _sesion(*roles)
    mfa()
    assert http.post(f"{BASE}/10/revelacion", json=SOLICITUD).status_code == 403


@pytest.mark.parametrize(
    "cuerpo",
    [
        {**SOLICITUD, "codigo": "12345"},
        {**SOLICITUD, "campos": []},
        {**SOLICITUD, "campos": ["email", "email"]},
        {**SOLICITUD, "campos": ["fechaNacimiento"]},
        {**SOLICITUD, "idDesafio": "x;drop"},
    ],
)
def test_solicitud_de_revelacion_invalida(cuerpo):
    from app.modules.clientes.schemas import SolicitudRevelacion

    with pytest.raises(ValidationError):
        SolicitudRevelacion.model_validate(cuerpo)


def test_revelacion_cuenta_como_ruta_sensible_en_el_limite():
    assert _clasificar("POST", f"{BASE}/10/revelacion") == "sensible"
    assert _clasificar("POST", f"{BASE}/10/revelacion/desafio") == "sensible"


# ---------------------------------------------------------------------------
# Exportación CSV (org-exportar, enmascarada, CLI_EXPORTACION)
# ---------------------------------------------------------------------------


def test_exportar_exige_org_exportar(http):
    _sesion("SUPERVISOR")
    respuesta = http.post(f"{BASE}/busqueda/exportacion", json={"estado": "Activo"})
    assert respuesta.status_code == 403


def test_exportacion_enmascarada_y_auditada(http, monkeypatch):
    from contextlib import nullcontext

    from app.core.csv import exportacion as herramienta

    registrados: list[Any] = []
    # Sin base real: la auditoría de la exportación usa su propia conexión.
    monkeypatch.setattr(
        herramienta,
        "get_engine",
        lambda _: SimpleNamespace(begin=lambda: nullcontext()),
    )
    monkeypatch.setattr(
        herramienta, "registrar_en_transaccion", lambda _, e: registrados.append(e)
    )
    _sesion("SUPERVISOR", permisos=("org-exportar",))
    monkeypatch.setattr(
        service,
        "listar_clientes",
        lambda conn, f: PageCliente(
            items=[_cliente(nombres="=CMD")], page=f.page, page_size=100, total=1
        ),
    )
    respuesta = http.post(f"{BASE}/busqueda/exportacion", json={"estado": "Activo"})
    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith("text/csv")
    assert respuesta.headers["cache-control"] == "no-store"
    texto = respuesta.text
    assert "1710034065" not in texto and "******4065" in texto
    assert "'=CMD" in texto  # inyección de fórmulas neutralizada
    (evento,) = registrados
    assert evento.accion == "CLI_EXPORTACION"
    assert "1710034065" not in evento.descripcion


def test_exportar_sin_filtro_es_400(http):
    _sesion("ADMIN", permisos=("org-exportar",))
    respuesta = http.post(f"{BASE}/busqueda/exportacion", json={})
    assert respuesta.json()["code"] == "FILTRO_REQUERIDO"
