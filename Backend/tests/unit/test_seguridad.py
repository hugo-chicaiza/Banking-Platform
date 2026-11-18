"""Seguridad: permisos de los roles en WorkOS y pestañas del menú por rol."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.database.db import seguridad
from app.main import app
from app.modules.seguridad import repository, service
from tests.sesion import simular_sesion, usuario_con_roles

BASE = "/api/v1/seguridad"


class _Autorizacion:
    """WorkOS falso: catálogo de permisos y roles org-* con sus permisos."""

    def __init__(self) -> None:
        self.permisos = {
            "prd-consultar": ("Consultar productos", False),
            "prd-editar": ("Editar productos", False),
            "con-cuenta-editar": ("Editar cuentas", False),
            "widgets:users-table:manage": ("Manage users", True),
        }
        self.roles = {
            "org-admin": ["prd-consultar", "prd-editar", "widgets:users-table:manage"],
            "org-contador": ["prd-consultar"],
            "org-cajero": [],
        }
        self.llamadas: list[tuple] = []

    def list_permissions(self, limit, after, order):
        datos = [
            SimpleNamespace(slug=s, name=n, description=None, system=sis)
            for s, (n, sis) in self.permisos.items()
        ]
        return SimpleNamespace(data=datos, list_metadata=SimpleNamespace(after=None))

    def update_permission(self, slug, name=None, description=None):
        self.llamadas.append(("update", slug, name, description))
        nombre = name or self.permisos[slug][0]
        self.permisos[slug] = (nombre, self.permisos[slug][1])
        return SimpleNamespace(
            slug=slug, name=nombre, description=description, system=False
        )

    def list_organization_roles(self, organizacion):
        datos = [
            SimpleNamespace(slug=s, name=s, description=None, permissions=list(p))
            for s, p in {**self.roles, "member": []}.items()
        ]
        return SimpleNamespace(data=datos)

    def add_organization_role_permission(self, organization_id, slug, permission_slug):
        self.llamadas.append(("add", slug, permission_slug))
        self.roles[slug].append(permission_slug)

    def remove_organization_role_permission(
        self, organization_id, slug, permission_slug
    ):
        self.llamadas.append(("remove", slug, permission_slug))
        self.roles[slug].remove(permission_slug)

    def set_organization_role_permissions(self, organization_id, slug, permissions):
        self.llamadas.append(("set", slug, tuple(permissions)))
        self.roles[slug] = list(permissions)


@pytest.fixture
def workos(monkeypatch) -> _Autorizacion:
    falso = _Autorizacion()
    monkeypatch.setattr(
        service, "get_workos", lambda: SimpleNamespace(authorization=falso)
    )
    monkeypatch.setattr(service, "get_organizacion_id", lambda: "org_prueba")
    return falso


@pytest.fixture
def pestanas(monkeypatch) -> dict[str, str]:
    """Seguridad.PestanaRol en memoria."""
    tabla: dict[str, str] = {}

    def reemplazar(conn, filas, usuario):
        tabla.clear()
        tabla.update(dict(filas))

    monkeypatch.setattr(repository, "pestanas", lambda conn: sorted(tabla.items()))
    monkeypatch.setattr(repository, "reemplazar_pestanas", reemplazar)
    return tabla


@pytest.fixture
def client():
    conn = SimpleNamespace(begin=nullcontext)
    app.dependency_overrides[seguridad] = lambda: conn
    simular_sesion(app, usuario_con_roles("ADMIN"))
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_lista_permisos_con_los_de_sistema_al_final(client, workos):
    r = client.get(f"{BASE}/permisos")
    assert r.status_code == 200
    assert [p["slug"] for p in r.json()][-1] == "widgets:users-table:manage"
    assert r.json()[-1]["sistema"] is True


def test_roles_solo_los_del_sistema(client, workos):
    r = client.get(f"{BASE}/roles")
    assert r.status_code == 200
    assert [v["rol"] for v in r.json()] == [
        "ADMIN",
        "CAJERO",
        "CONTADOR",
    ]  # orden de ROLES
    assert "member" not in {v["slug"] for v in r.json()}


def test_asignar_y_quitar_permiso(client, workos, eventos_auditados):
    r = client.post(f"{BASE}/roles/CAJERO/permisos", json={"permiso": "prd-consultar"})
    assert r.status_code == 200 and r.json()["permisos"] == ["prd-consultar"]
    # Asignar de nuevo no duplica ni llama a WorkOS
    client.post(f"{BASE}/roles/CAJERO/permisos", json={"permiso": "prd-consultar"})
    assert workos.llamadas.count(("add", "org-cajero", "prd-consultar")) == 1

    r = client.delete(f"{BASE}/roles/CAJERO/permisos/prd-consultar")
    assert r.status_code == 200 and r.json()["permisos"] == []
    assert {e.accion for e in eventos_auditados} >= {
        "ASIGNAR_PERMISO_ROL",
        "QUITAR_PERMISO_ROL",
    }


@pytest.mark.parametrize(
    ("permiso", "status", "code"),
    [
        ("inventado", 404, "PERMISO_NO_ENCONTRADO"),
        ("widgets:users-table:manage", 409, "PERMISO_DE_SISTEMA"),
    ],
)
def test_no_asigna_permisos_inexistentes_ni_de_sistema(
    client, workos, permiso, status, code
):
    r = client.post(f"{BASE}/roles/CAJERO/permisos", json={"permiso": permiso})
    assert r.status_code == status and r.json()["code"] == code
    assert not [x for x in workos.llamadas if x[0] == "add"]


def test_quitar_permiso_no_asignado_es_404(client, workos):
    r = client.delete(f"{BASE}/roles/CAJERO/permisos/prd-editar")
    assert r.status_code == 404 and r.json()["code"] == "PERMISO_NO_ASIGNADO"


def test_rol_desconocido_es_400(client, workos):
    assert (
        client.post(
            f"{BASE}/roles/ROOT/permisos", json={"permiso": "prd-editar"}
        ).status_code
        == 400
    )


def test_reemplazar_conserva_los_de_sistema(client, workos):
    r = client.put(
        f"{BASE}/roles/ADMIN/permisos", json={"permisos": ["con-cuenta-editar"]}
    )
    assert r.status_code == 200
    assert r.json()["permisos"] == ["con-cuenta-editar", "widgets:users-table:manage"]


def test_reemplazar_rechaza_permisos_de_sistema(client, workos):
    r = client.put(
        f"{BASE}/roles/CAJERO/permisos",
        json={"permisos": ["widgets:users-table:manage"]},
    )
    assert r.status_code == 409
    assert not [x for x in workos.llamadas if x[0] == "set"]


def test_editar_permiso_nombre(client, workos):
    r = client.patch(
        f"{BASE}/permisos/prd-editar", json={"nombre": "Editar catálogo de productos"}
    )
    assert r.status_code == 200 and r.json()["nombre"] == "Editar catálogo de productos"
    assert client.patch(f"{BASE}/permisos/prd-editar", json={}).status_code == 422
    assert (
        client.patch(
            f"{BASE}/permisos/widgets:users-table:manage", json={"nombre": "x"}
        ).status_code
        == 409
    )


def test_workos_caido_es_503(client):
    # Sin falso instalado, el conftest simula WorkOS caído
    r = client.get(f"{BASE}/roles")
    assert r.status_code == 503 and r.json()["code"] == "WORKOS_NO_DISPONIBLE"


@pytest.mark.parametrize(
    ("metodo", "ruta", "cuerpo"),
    [
        ("GET", "/permisos", None),
        ("GET", "/roles", None),
        ("POST", "/roles/CAJERO/permisos", {"permiso": "prd-editar"}),
        ("PUT", "/pestanas", {"pestanas": []}),
    ],
)
def test_solo_admin_administra(client, workos, pestanas, metodo, ruta, cuerpo):
    simular_sesion(
        app, usuario_con_roles("SUPERVISOR", "ASESOR", "CONTADOR", "AUDITOR")
    )
    r = client.request(metodo, BASE + ruta, json=cuerpo)
    assert r.status_code == 403
    assert not workos.llamadas


def test_pestanas_las_lee_cualquier_rol_y_las_guarda_admin(
    client, pestanas, eventos_auditados
):
    cuerpo = {"pestanas": [{"pestana": "/cuentas/abrir", "roles": ["ASESOR", "ADMIN"]}]}
    r = client.put(f"{BASE}/pestanas", json=cuerpo)
    assert r.status_code == 200
    assert pestanas == {"/cuentas/abrir": "ADMIN,ASESOR"}  # orden de ROLES
    assert eventos_auditados[-1].accion == "CONFIGURAR_PESTANAS"

    simular_sesion(app, usuario_con_roles("CAJERO"))
    r = client.get(f"{BASE}/pestanas")
    assert r.status_code == 200
    assert r.json() == [{"pestana": "/cuentas/abrir", "roles": ["ADMIN", "ASESOR"]}]


@pytest.mark.parametrize(
    ("cuerpo", "code"),
    [
        (
            {"pestanas": [{"pestana": "/seguridad/roles", "roles": []}]},
            "PESTANA_NO_CONFIGURABLE",
        ),
        (
            {
                "pestanas": [
                    {"pestana": "/cuentas", "roles": []},
                    {"pestana": "/cuentas", "roles": ["ADMIN"]},
                ]
            },
            "PESTANA_DUPLICADA",
        ),
    ],
)
def test_pestanas_rechaza_configuraciones_invalidas(client, pestanas, cuerpo, code):
    r = client.put(f"{BASE}/pestanas", json=cuerpo)
    assert r.status_code == 422 and r.json()["code"] == code
    assert pestanas == {}


@pytest.mark.parametrize(
    "pestana", ["cuentas", "/Cuentas", "/../x", "/a?b=1", "/" + "a" * 90]
)
def test_pestanas_rechaza_rutas_mal_formadas(client, pestanas, pestana):
    r = client.put(
        f"{BASE}/pestanas", json={"pestanas": [{"pestana": pestana, "roles": []}]}
    )
    assert r.status_code == 400


def test_pestanas_ignora_roles_desconocidos_guardados(client, pestanas):
    pestanas["/cuentas"] = "ADMIN,ROOT"
    assert client.get(f"{BASE}/pestanas").json() == [
        {"pestana": "/cuentas", "roles": ["ADMIN"]}
    ]
