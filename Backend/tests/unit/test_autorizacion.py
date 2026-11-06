"""F-03 en todos los módulos: sesión obligatoria, roles de cada tarea y auditoría de
los accesos denegados.

Las rutas salen del OpenAPI de la app, así que una ruta nueva sin require_auth hace
fallar test_toda_ruta_de_la_api_exige_sesion.
"""

import re

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.core.security.auth import ROLES, Usuario, require_auth
from app.main import app
from app.modules.tarjetas import router as tarjetas_router
from tests.sesion import USUARIO, simular_sesion, usuario_con_roles

AUTH = ()  # Cualquier usuario autenticado, sin rol específico
_PUBLICAS = {
    ("GET", "/api/v1/auth/login"),
    ("GET", "/api/v1/auth/callback"),
    ("POST", "/api/v1/auth/logout"),  # AUT-03: idempotente, sin sesión responde 200
}
_VALORES_PATH = {"codigo_pais": "ECU", "fecha": "2026-11-04"}

# Roles de cada tarea (GitHubProject_Files)
ROLES_POR_RUTA: dict[tuple[str, str], tuple[str, ...]] = {
    ("GET", "/api/v1/auth/me"): AUTH,
    **{
        ("GET", f"/api/v1/catalogos/{ruta}"): AUTH
        for ruta in (
            "paises",
            "paises/{codigo_pais}/ciudades",
            "actividades-economicas",
            "tipos-antecedente",
            "denominaciones",
            "agencias",
            "productos",
            "canales",
            "tipos-credito",
            "tipos-movimiento-caja",
        )
    },
    ("GET", "/api/v1/contabilidad/fechas-contables/actual"): AUTH,
    ("GET", "/api/v1/contabilidad/fechas-contables/{fecha}"): AUTH,
    ("GET", "/api/v1/clientes/validar-identificacion"): ("ASESOR", "ADMIN"),
    ("POST", "/api/v1/clientes"): ("ASESOR", "ADMIN"),
    ("GET", "/api/v1/clientes"): ("ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/clientes/{idCliente}"): (
        "ASESOR",
        "CAJERO",
        "SUPERVISOR",
        "ADMIN",
    ),
    ("PATCH", "/api/v1/clientes/{idCliente}"): ("ASESOR", "ADMIN"),
    ("PATCH", "/api/v1/clientes/{idCliente}/estado"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/clientes/{idCliente}/historial"): (
        "SUPERVISOR",
        "AUDITOR",
        "ADMIN",
    ),
    ("GET", "/api/v1/clientes/{idCliente}/perfil"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/clientes/{idCliente}/direcciones"): ("ASESOR", "ADMIN"),
    ("POST", "/api/v1/clientes/{idCliente}/direcciones"): ("ASESOR", "ADMIN"),
    ("PATCH", "/api/v1/clientes/{idCliente}/direcciones/{idDireccion}"): (
        "ASESOR",
        "ADMIN",
    ),
    ("DELETE", "/api/v1/clientes/{idCliente}/direcciones/{idDireccion}"): (
        "ASESOR",
        "ADMIN",
    ),
    ("POST", "/api/v1/clientes/{idCliente}/evaluaciones-riesgo"): (
        "ASESOR",
        "SUPERVISOR",
        "ADMIN",
    ),
    ("GET", "/api/v1/clientes/{idCliente}/evaluaciones-riesgo"): (
        "ASESOR",
        "SUPERVISOR",
        "AUDITOR",
        "ADMIN",
    ),
    ("GET", "/api/v1/creditos/tipos/{idTipoCredito}/condiciones"): ("ASESOR", "ADMIN"),
    ("POST", "/api/v1/creditos/simulaciones"): ("ASESOR", "ADMIN"),
    ("POST", "/api/v1/cuentas"): ("ASESOR", "ADMIN"),
    ("GET", "/api/v1/cuentas"): ("ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/cuentas/{idCuenta}"): ("ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/cuentas/{idCuenta}/saldo"): (
        "ASESOR",
        "CAJERO",
        "SUPERVISOR",
        "ADMIN",
    ),
    ("PATCH", "/api/v1/cuentas/{idCuenta}/estado"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/cuentas/{idCuenta}/cupos"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("PUT", "/api/v1/cuentas/{idCuenta}/cupos/{idCanal}"): ("SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/cuentas/{idCuenta}/cupos/{idCanal}/historial"): (
        "SUPERVISOR",
        "AUDITOR",
        "ADMIN",
    ),
    ("POST", "/api/v1/tarjetas"): ("ASESOR", "ADMIN"),
    ("GET", "/api/v1/tarjetas"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/tarjetas/{idTarjeta}"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("POST", "/api/v1/tarjetas/{idTarjeta}/estado"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("POST", "/api/v1/tarjetas/{idTarjeta}/pin"): ("ASESOR", "ADMIN"),
    ("GET", "/api/v1/tarjetas/{idTarjeta}/historial"): (
        "SUPERVISOR",
        "AUDITOR",
        "ADMIN",
    ),
    # CAJ-01: listado de cajas físicas
    ("GET", "/api/v1/caja/cajas-fisicas"): (
        "CAJERO",
        "SUPERVISOR",
        "ADMIN",
    ),
    # CAJ-02: consulta de jornadas
    ("GET", "/api/v1/caja/jornadas"): (
        "SUPERVISOR",
        "CONTADOR",
        "AUDITOR",
    ),
    # CAJ-05:
    ("GET", "/api/v1/caja/jornadas/{idJornada}"): (
        "CAJERO",
        "SUPERVISOR",
        "CONTADOR",
    ),
    # CAJ-08
    ("GET", "/api/v1/caja/jornadas/{idJornada}/dotaciones"): (
        "CAJERO",
        "SUPERVISOR",
        "CONTADOR",
    ),
    # CAJ-12
    ("GET", "/api/v1/caja/jornadas/{idJornada}/movimientos"): (
        "CAJERO",
        "SUPERVISOR",
        "CONTADOR",
    ),
    # CAJ-14
    ("GET", "/api/v1/caja/jornadas/{idJornada}/cuadre"): (
        "CAJERO",
        "SUPERVISOR",
        "CONTADOR",
    ),
    # TRX - 01
    ("GET", "/api/v1/transacciones"): (
        "SUPERVISOR",
        "AUDITOR",
        "CONTADOR",
        "ADMIN",
    ),
    # TRX - 02
    ("GET", "/api/v1/transacciones/{idTransaccion}"): (
        "SUPERVISOR",
        "AUDITOR",
        "CONTADOR",
        "ADMIN",
    ),
}


def _rutas_api() -> list[tuple[str, str]]:
    return [
        (metodo.upper(), ruta)
        for ruta, operaciones in app.openapi()["paths"].items()
        if ruta.startswith("/api/")
        for metodo in operaciones
        if metodo in {"get", "post", "put", "patch", "delete"}
    ]


def _concreta(ruta: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: _VALORES_PATH.get(m.group(1), "1"), ruta)


@pytest.fixture
def client():
    # Sin BD real: lo que llegue al repositorio falla, pero el control de acceso ya pasó
    app.dependency_overrides[cooperativa] = lambda: None
    app.dependency_overrides[tarjetas_router.seguridad] = lambda: None
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _llamar(client: TestClient, metodo: str, ruta: str):
    return client.request(metodo, _concreta(ruta))


def _code(respuesta) -> str:
    # Clientes (gestión) y contabilidad aún no usan ProblemDetailsRoute (F-04): ahí
    # FastAPI responde {"detail": {"code": ...}}. Cuando migren, basta con ["code"].
    cuerpo = respuesta.json()
    return cuerpo.get("code") or cuerpo["detail"]["code"]


def test_tabla_de_roles_cubre_todas_las_rutas_protegidas():
    protegidas = set(_rutas_api()) - _PUBLICAS - {("POST", "/api/v1/auth/refresh")}
    assert protegidas == set(ROLES_POR_RUTA)


@pytest.mark.parametrize("ruta", sorted(set(_rutas_api()) - _PUBLICAS))
def test_toda_ruta_de_la_api_exige_sesion(client, eventos_auditados, ruta):
    metodo, path = ruta

    r = _llamar(client, metodo, path)

    assert r.status_code == 401
    assert _code(r) == "NO_AUTENTICADO"
    evento = eventos_auditados[-1]
    assert (evento.accion, evento.resultado, evento.usuario) == (
        "ACCESO_DENEGADO",
        "Fallido",
        None,
    )
    assert evento.descripcion.startswith(f"401 {metodo} {_concreta(path)} trace=")


@pytest.mark.parametrize(
    ("ruta", "roles"),
    [(r, roles) for r, roles in ROLES_POR_RUTA.items() if roles],
    ids=lambda v: " ".join(v) if isinstance(v, tuple) else v,
)
def test_rol_fuera_de_la_tarea_recibe_403(client, ruta, roles):
    simular_sesion(app, usuario_con_roles(*(r for r in ROLES if r not in roles)))

    r = _llamar(client, *ruta)

    assert r.status_code == 403
    assert _code(r) == "SIN_PERMISO"


@pytest.mark.parametrize("ruta", list(ROLES_POR_RUTA), ids=" ".join)
def test_roles_de_la_tarea_pasan_el_control(client, ruta):
    roles = ROLES_POR_RUTA[ruta]
    # AUTH: un usuario sin ningún rol del sistema también entra
    simular_sesion(app, usuario_con_roles(*roles))

    r = _llamar(client, *ruta)

    assert r.status_code not in {401, 403}


def test_require_auth_entrega_el_usuario_de_la_sesion():
    assert require_auth(USUARIO) is USUARIO


def test_403_auditado_con_el_usuario_vinculado(client, eventos_auditados, monkeypatch):
    from app.core.security import audit

    usuario = usuario_con_roles("CAJERO")
    # La sesión real deja el usuario en request.state; aquí se simula ese paso
    monkeypatch.setattr(
        audit,
        "get_settings",
        lambda: type("S", (), {"workos_audit_user_ids": {usuario.id_usuario: 12}})(),
    )

    def sesion(request: Request) -> Usuario:
        request.state.usuario = usuario
        return usuario

    from app.core.security.auth import usuario_actual

    app.dependency_overrides[usuario_actual] = sesion

    r = client.get("/api/v1/tarjetas/1/historial?fechaDesde=2026-01-01")

    assert r.status_code == 403
    evento = eventos_auditados[-1]
    assert evento.usuario == 12
    # Sin query string: puede traer datos personales
    assert "fechaDesde" not in evento.descripcion
    assert "usuario=" not in evento.descripcion


def test_403_de_usuario_sin_vinculo_registra_su_id_de_workos(client, eventos_auditados):
    usuario = usuario_con_roles("CAJERO")

    def sesion(request: Request) -> Usuario:
        request.state.usuario = usuario
        return usuario

    from app.core.security.auth import usuario_actual

    app.dependency_overrides[usuario_actual] = sesion

    client.get("/api/v1/tarjetas/1")

    evento = eventos_auditados[-1]
    assert evento.usuario is None
    assert evento.descripcion.endswith(f"usuario={usuario.id_usuario}")


def test_respuestas_que_no_son_401_ni_403_no_se_auditan(client, eventos_auditados):
    simular_sesion(app)

    client.get("/api/v1/clientes", params={"page": "0"})

    assert eventos_auditados == []


def test_smoke_test_sigue_siendo_publico(client, eventos_auditados, monkeypatch):
    from app import smoke_test

    monkeypatch.setattr(smoke_test, "_db_ok", lambda _db: True)

    r = client.get("/smoke-test")

    assert r.status_code == 200
    assert eventos_auditados == []
