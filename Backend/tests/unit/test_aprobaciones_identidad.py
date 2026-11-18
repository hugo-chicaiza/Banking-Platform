"""Los permisos se vuelven a leer, sin confiar en los roles de un token anterior."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.aprobaciones import identidad


@pytest.fixture
def cliente(monkeypatch):
    cliente = MagicMock()
    miembro = SimpleNamespace(
        roles=[{"slug": "org-supervisor"}], role={"slug": "org-supervisor"}
    )
    cliente.user_management.list_organization_memberships.return_value = [miembro]
    cliente.authorization.get_organization_role.return_value = SimpleNamespace(
        permissions=["parametros:aprobar"]
    )
    monkeypatch.setattr(identidad, "get_organizacion_id", lambda: "org_fixture_e008")
    monkeypatch.setattr(identidad, "get_workos", lambda: cliente)
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.all.return_value = [
        {
            "UsuarioID": 900801,
            "Estado": "Activo",
            "Nombres": "Responsable",
            "Apellidos": "QA",
        }
    ]
    conn.scalars.return_value = ["001"]
    motor = MagicMock()
    motor.connect.return_value.__enter__.return_value = conn
    monkeypatch.setattr(identidad, "motor", lambda _: motor)
    return cliente


def test_revalidar_permiso_en_cada_llamada_sin_cache(cliente):
    primero = identidad.vigente("user_fixture_e008", "org_fixture_e008")
    cliente.authorization.get_organization_role.return_value = SimpleNamespace(
        permissions=[]
    )
    segundo = identidad.vigente("user_fixture_e008", "org_fixture_e008")
    assert "parametros:aprobar" in primero.permisos
    assert "parametros:aprobar" not in segundo.permisos
    assert cliente.authorization.get_organization_role.call_count == 2


def test_no_aprobacion_implicita_para_admin(cliente):
    cliente.user_management.list_organization_memberships.return_value = [
        SimpleNamespace(roles=None, role={"slug": "org-admin"})
    ]
    cliente.authorization.get_organization_role.return_value = SimpleNamespace(
        permissions=[]
    )
    actor = identidad.vigente("user_fixture_e008", "org_fixture_e008")
    assert actor.global_admin and not actor.permisos


def test_organizacion_ajena_se_rechaza_antes_del_sdk(cliente):
    with pytest.raises(HTTPException, match="ORGANIZACION_NO_AUTORIZADA"):
        identidad.vigente("user_fixture_e008", "org_otro_fixture")
    cliente.user_management.list_organization_memberships.assert_not_called()


def test_membresia_inactiva_no_se_acepta(cliente):
    cliente.user_management.list_organization_memberships.return_value = []
    with pytest.raises(HTTPException, match="ACTOR_NO_ACTIVO"):
        identidad.vigente("user_fixture_e008", "org_fixture_e008")


def test_scope_asignado_no_se_amplia_por_permiso(cliente):
    actor = identidad.vigente("user_fixture_e008", "org_fixture_e008")
    actor.alcance("001")
    with pytest.raises(HTTPException) as error:
        actor.alcance("002")
    assert error.value.status_code == 404
