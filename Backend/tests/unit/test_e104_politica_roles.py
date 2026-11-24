from typing import cast

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.security.auth import ROLES
from app.modules.auth.politica_roles import PoliticaRoles


def politica():
    return PoliticaRoles(
        niveles={rol: 4 if rol == "AUDITOR" else 3 for rol in ROLES},
        privilegiados={"CONTADOR"},
        incompatibles=[("CAJERO", "CONTADOR")],
    )


@pytest.mark.parametrize(
    ("actuales", "nuevos", "codigo"),
    [
        (["CAJERO"], ["AUDITOR"], "NIVEL_INSUFICIENTE"),
        (["AUDITOR"], ["CAJERO"], "NIVEL_INSUFICIENTE"),
        (["CAJERO"], ["CAJERO", "CONTADOR"], "ROLES_INCOMPATIBLES"),
    ],
)
def test_rechaza_cambios_fuera_de_la_politica(actuales, nuevos, codigo):
    with pytest.raises(HTTPException) as exc:
        politica().requiere_aprobacion(["ADMIN"], actuales, nuevos)
    assert exc.value.status_code == 422
    assert cast(dict[str, str], exc.value.detail)["code"] == codigo


def test_solo_la_adicion_configurada_requiere_aprobacion():
    assert politica().requiere_aprobacion(["ADMIN"], ["ASESOR"], ["CONTADOR"])
    assert not politica().requiere_aprobacion(["ADMIN"], ["CONTADOR"], ["ASESOR"])


def test_rechaza_politica_parcial():
    with pytest.raises(ValidationError, match="cubrir todos"):
        PoliticaRoles(niveles={"ADMIN": 3}, privilegiados=set(), incompatibles=[])
