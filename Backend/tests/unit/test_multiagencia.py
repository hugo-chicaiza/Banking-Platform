"""#450: contrato API, matriz y revocacion. Dobles sin SQL ni WorkOS reales."""

import copy
from dataclasses import replace

import pytest
from fastapi import HTTPException
from workos.exceptions import ServerException

from app.core.security.operador import agencia_de_consulta, exigir_agencia_autorizada
from app.main import app
from app.modules.auth import agencias
from app.modules.auth import agencias_repository as repo
from tests.sesion import ID_AUDITORIA, simular_sesion, usuario_con_roles
from tests.unit import test_usuarios as fixtures_usuarios
from tests.unit.test_usuarios import ADMIN, BASE, NUEVO, _http_error

base_original = fixtures_usuarios.base
workos_original = fixtures_usuarios.workos
conn_original = fixtures_usuarios.conn
client_original = fixtures_usuarios.client


@pytest.fixture
def base(request):
    return request.getfixturevalue("base_original")


@pytest.fixture
def conn(request):
    return request.getfixturevalue("conn_original")


@pytest.fixture
def workos(request):
    return request.getfixturevalue("workos_original")


@pytest.fixture
def client(request):
    return request.getfixturevalue("client_original")


def test_admin_no_modifica_sus_propias_asignaciones(client, base):
    antes = copy.deepcopy(base.estado())
    r = client.put(
        f"{BASE}/{ID_AUDITORIA}/agencias",
        json={"idAgencias": ["002"], "idAgenciaPrincipal": "002", "version": 0},
    )

    assert r.status_code == 403
    assert r.json()["code"] == "AUTOGESTION_NO_PERMITIDA"
    assert base.estado() == antes


def test_admin_agrega_revoca_y_cambia_principal(client, base, workos):
    base.usuarios[3]["RolesWorkOS"] = "CONTADOR"
    body = {"idAgencias": ["001", "002"], "idAgenciaPrincipal": "002", "version": 0}
    r = client.put(BASE + "/3/agencias", json=body)
    assert r.status_code == 200, r.text
    assert {a["idAgencia"] for a in r.json()["agencias"]} == {"001", "002"}
    assert r.json()["idAgenciaPrincipal"] == "002"
    assert workos.llamadas == []
    r = client.put(
        BASE + "/3/agencias",
        json={**body, "idAgencias": ["002"], "version": r.json()["version"]},
    )
    assert r.status_code == 200
    assert [a["idAgencia"] for a in r.json()["agencias"]] == ["002"]
    history = client.get(BASE + "/3/agencias/historial").json()
    assert {i["accion"] for i in history["items"]} >= {
        "ASIGNAR",
        "REVOCAR",
        "PRINCIPAL",
    }
    assert all(i["realizadoPor"] == 1 for i in history["items"])


@pytest.mark.parametrize(
    "rol", ["ADMIN", "CONTADOR", "SUPERVISOR", "AUDITOR", "APROBADOR_CREDITO"]
)
def test_roles_multiples(client, base, rol):
    base.usuarios[3]["RolesWorkOS"] = rol
    r = client.put(
        BASE + "/3/agencias",
        json={"idAgencias": ["001", "002"], "idAgenciaPrincipal": "001", "version": 0},
    )
    assert r.status_code == 200


@pytest.mark.parametrize("rol", ["CAJERO", "ASESOR", "ADMIN,CAJERO", "CONTADOR,ASESOR"])
def test_roles_unicos_y_combinados_no_amplian_asignaciones(client, base, rol):
    base.usuarios[3]["RolesWorkOS"] = rol
    r = client.put(
        BASE + "/3/agencias",
        json={"idAgencias": ["001", "002"], "idAgenciaPrincipal": "001", "version": 0},
    )
    assert r.status_code == 422 and r.json()["code"] == "MULTIAGENCIA_NO_PERMITIDA"
    assert base.multi[3] == ["001"]


@pytest.mark.parametrize(
    "cambio,code",
    [
        (
            {"idAgencias": ["001", "001"], "idAgenciaPrincipal": "001"},
            "ASIGNACIONES_INVALIDAS",
        ),
        ({"idAgencias": ["001"], "idAgenciaPrincipal": "002"}, "PRINCIPAL_NO_ASIGNADA"),
        ({"idAgencias": ["999"], "idAgenciaPrincipal": "999"}, "AGENCIA_INVALIDA"),
    ],
)
def test_rechazos_no_mutan(client, base, cambio, code):
    base.usuarios[3]["RolesWorkOS"] = "CONTADOR"
    antes = copy.deepcopy(base.estado())
    r = client.put(BASE + "/3/agencias", json={**cambio, "version": 0})
    assert r.status_code == 422 and r.json()["code"] == code
    assert base.estado() == antes


def test_agencia_inactiva_no_se_asigna(client, base, monkeypatch):
    base.usuarios[3]["RolesWorkOS"] = "CONTADOR"
    monkeypatch.setattr(
        repo,
        "agencias",
        lambda _c: [
            {"id_agencia": "001", "codigo": "001", "estado": "A"},
            {"id_agencia": "002", "codigo": "002", "estado": "I"},
        ],
    )
    r = client.put(
        BASE + "/3/agencias",
        json={"idAgencias": ["001", "002"], "idAgenciaPrincipal": "001", "version": 0},
    )
    assert r.status_code == 422 and r.json()["code"] == "AGENCIA_INVALIDA"


def test_version_impide_sobrescritura(client, base):
    base.usuarios[3]["RolesWorkOS"] = "CONTADOR"
    body = {"idAgencias": ["001", "002"], "idAgenciaPrincipal": "002", "version": 0}
    assert client.put(BASE + "/3/agencias", json=body).status_code == 200
    r = client.put(
        BASE + "/3/agencias",
        json={**body, "idAgencias": ["001"], "idAgenciaPrincipal": "001"},
    )
    assert (
        r.status_code == 409 and r.json()["code"] == "VERSION_ASIGNACION_DESACTUALIZADA"
    )
    assert set(base.multi[3]) == {"001", "002"}


def test_permiso_sin_admin_no_basta(client):
    actor = replace(usuario_con_roles("CONTADOR"), permisos=("prd-editar",))
    simular_sesion(app, actor)
    r = client.put(
        BASE + "/3/agencias",
        json={"idAgencias": ["001"], "idAgenciaPrincipal": "001", "version": 0},
    )
    assert r.status_code == 403


def test_fallo_invitacion_revierte_asignaciones(client, base, workos):
    workos.errores["send_invitation"] = _http_error(ServerException)
    antes = copy.deepcopy(base.estado())
    r = client.post(
        BASE, json={**NUEVO, "rol": "CONTADOR", "idAgencias": ["001", "002"]}
    )
    assert r.status_code == 503
    assert base.estado() == antes


def test_jornada_abierta_bloquea_asignaciones_y_cambio_rol(client, base):
    base.jornadas[2] = {"IdAgencia": "001"}
    r = client.put(
        BASE + "/2/agencias",
        json={"idAgencias": ["002"], "idAgenciaPrincipal": "002", "version": 0},
    )
    assert r.status_code == 409 and r.json()["code"] == "USUARIO_CON_JORNADA_ABIERTA"
    r = client.put(BASE + "/2/roles", json={"rol": "CONTADOR"})
    assert r.status_code == 409 and r.json()["code"] == "CAJERO_CON_JORNADA_ABIERTA"


def test_no_convierte_multiagencia_en_cajero_silenciosamente(client, base, workos):
    base.usuarios[3]["RolesWorkOS"] = "CONTADOR"
    base.multi[3] = ["001", "002"]
    r = client.put(BASE + "/3/roles", json={"rol": "CAJERO"})
    assert r.status_code == 422
    assert all(llamada[0] == "list_users" for llamada in workos.llamadas)


def actor_contador(base, sid="sid-a"):
    base.usuarios[2]["RolesWorkOS"] = "CONTADOR"
    return replace(
        ADMIN,
        id_usuario="user_2",
        id_sesion=sid,
        id_interno=2,
        roles=("CONTADOR",),
        permisos=(),
        cargar_agencia=lambda: agencias.resolver_sesion("user_2", sid, ("CONTADOR",)),
        cargar_agencias=lambda: agencias.alcance_sesion("user_2", ("CONTADOR",)),
    )


def test_contexto_confirmado_y_revocacion_no_hacen_fallback(client, base):
    base.multi[2] = ["001", "002"]
    simular_sesion(app, actor_contador(base))
    assert client.get("/api/v1/auth/agencias").json()["idAgencia"] == "001"
    r = client.post("/api/v1/auth/agencia-activa", json={"idAgencia": "002"})
    assert r.status_code == 200 and r.json()["idAgencia"] == "002"
    assert client.get("/api/v1/auth/me").json()["idAgencia"] == "002"
    base.multi[2] = ["001"]
    simular_sesion(app, actor_contador(base))
    r = client.get("/api/v1/auth/agencias")
    assert r.status_code == 200 and r.json()["idAgencia"] is None
    assert r.json()["requiereSeleccionAgencia"] is True


def test_traslado_actualiza_misma_sesion_y_registra_ambas_agencias(client, base):
    roles = ("CAJERO",)
    sid = "sid-traslado"
    cajero = replace(
        ADMIN,
        id_usuario="user_2",
        id_sesion=sid,
        id_interno=2,
        roles=roles,
        permisos=(),
        cargar_agencia=lambda: agencias.resolver_sesion("user_2", sid, roles),
        cargar_agencias=lambda: agencias.alcance_sesion("user_2", roles),
    )
    simular_sesion(app, cajero)
    assert client.get("/api/v1/auth/me").json()["idAgencia"] == "001"

    simular_sesion(app, ADMIN)
    r = client.put(BASE + "/2/agencia", json={"idAgencia": "002"})
    assert r.status_code == 200, r.text
    eventos = client.get(BASE + "/2/historial").json()["items"]
    assert {(e["accion"], e["idAgencia"]) for e in eventos} >= {
        ("REVOCAR", "001"),
        ("ASIGNAR", "002"),
    }
    assert all(e["fechaUtc"] for e in eventos)

    siguiente_peticion = replace(cajero)
    simular_sesion(app, siguiente_peticion)
    assert client.get("/api/v1/auth/me").json()["idAgencia"] == "002"
    assert agencia_de_consulta(siguiente_peticion, "002") == "002"
    with pytest.raises(HTTPException) as error:
        agencia_de_consulta(siguiente_peticion, "001")
    assert error.value.status_code == 403


def test_principal_y_sesiones_no_se_confunden(client, base):
    base.multi[2] = ["001", "002"]
    simular_sesion(app, actor_contador(base, "sid-a"))
    assert client.get("/api/v1/auth/agencias").json()["idAgencia"] == "001"
    base.usuarios[2]["AgenciaID"] = 2
    assert client.get("/api/v1/auth/agencias").json()["idAgencia"] == "001"
    simular_sesion(app, actor_contador(base, "sid-b"))
    assert client.get("/api/v1/auth/agencias").json()["idAgencia"] == "002"


def test_contexto_ajeno_no_se_adopta(client, base):
    simular_sesion(app, actor_contador(base))
    r = client.post("/api/v1/auth/agencia-activa", json={"idAgencia": "002"})
    assert r.status_code == 403 and r.json()["code"] == "SIN_ACCESO_AGENCIA"
    assert client.get("/api/v1/auth/me").json()["idAgencia"] == "001"


def test_consulta_no_admin_respetan_asignaciones_y_admin_global():
    actor = replace(usuario_con_roles("CONTADOR"), id_agencias=("001", "002"))
    assert agencia_de_consulta(actor, "002") == "002"
    with pytest.raises(HTTPException) as err:
        exigir_agencia_autorizada(actor, "003")
    assert err.value.status_code == 403
    assert agencia_de_consulta(usuario_con_roles("ADMIN"), "003") == "003"


def actor_admin_global():
    return replace(
        ADMIN,
        id_usuario="user_1",
        cargar_agencia=lambda: agencias.resolver_sesion(
            "user_1", ADMIN.id_sesion, ("ADMIN",)
        ),
        cargar_agencias=lambda: agencias.alcance_sesion("user_1", ("ADMIN",)),
    )


def test_admin_todas_agencias_sin_seleccion_y_filtro_explicito(client, base):
    simular_sesion(app, actor_admin_global())
    initial = client.get("/api/v1/auth/agencias").json()
    assert initial["alcanceGlobal"] is True
    assert initial["accesoTodasAgencias"] is True
    assert initial["idAgencia"] is None
    assert initial["requiereSeleccionAgencia"] is False
    assert initial["idAgenciaPrincipal"] == "001"
    assert agencia_de_consulta(actor_admin_global(), None) is None
    assert agencia_de_consulta(actor_admin_global(), "002") == "002"
    r = client.post("/api/v1/auth/agencia-activa", json={"idAgencia": "002"})
    assert r.status_code == 409 and r.json()["code"] == "ADMIN_ACCESO_TODAS_AGENCIAS"
    r = client.post("/api/v1/auth/agencia-activa", json={"idAgencia": None})
    assert r.status_code == 200 and r.json()["idAgenciaPrincipal"] == "001"


def test_contador_no_puede_seleccionar_global(client, base):
    simular_sesion(app, actor_contador(base))
    r = client.post("/api/v1/auth/agencia-activa", json={"idAgencia": None})
    assert r.status_code == 403 and r.json()["code"] == "SIN_ACCESO_AGENCIA"


def test_admin_contexto_anterior_no_limita_acceso_total(client, base):
    base.contextos[(agencias.hash_sesion(ADMIN.id_sesion), 1)] = {
        "agencia": "001",
        "vigente": 0,
    }
    simular_sesion(app, actor_admin_global())
    data = client.get("/api/v1/auth/agencias").json()
    assert data["alcanceGlobal"] is True and data["requiereSeleccionAgencia"] is False


def test_multiples_asignaciones_cubren_todas_sin_conceder_rol_admin(client, base):
    base.multi[2] = ["001", "002"]
    actor = actor_contador(base)
    simular_sesion(app, actor)
    data = client.get("/api/v1/auth/agencias").json()
    assert data["accesoTodasAgencias"] is True and data["alcanceGlobal"] is False
    assert data["idAgencia"] == "001"
    assert agencia_de_consulta(actor, None) == "001"
    base.agencias.add("003")
    simular_sesion(app, actor_contador(base))
    assert client.get("/api/v1/auth/agencias").json()["accesoTodasAgencias"] is False


def test_asientos_parametro_no_cambia_agencia_operativa(client, base, monkeypatch):
    from app.modules.contabilidad import service as contabilidad

    recibidos = []

    def listado(_conn, **params):
        recibidos.append(params["id_agencia"])
        return {"items": [], "total": 0, "page": 1, "page_size": 20}

    monkeypatch.setattr(contabilidad, "listar_asientos", listado)
    base.agencias.add("003")
    base.multi[2] = ["001", "002"]
    simular_sesion(app, actor_contador(base))
    r = client.get("/api/v1/contabilidad/asientos?idAgencia=002")
    assert r.status_code == 403 and r.json()["code"] == "AGENCIA_OPERATIVA_REQUERIDA"
    assert recibidos == []
    assert client.get("/api/v1/contabilidad/asientos").status_code == 200
    assert recibidos == ["001"]
    assert (
        client.post(
            "/api/v1/auth/agencia-activa", json={"idAgencia": "002"}
        ).status_code
        == 200
    )
    simular_sesion(app, actor_contador(base))
    assert client.get("/api/v1/contabilidad/asientos?idAgencia=001").status_code == 403
    assert client.get("/api/v1/contabilidad/asientos?idAgencia=002").status_code == 200
    assert recibidos[-1] == "002"
