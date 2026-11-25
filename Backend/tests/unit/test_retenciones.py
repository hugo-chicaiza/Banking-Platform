from decimal import Decimal
from typing import cast

import pytest
from fastapi import HTTPException

from app.core.security.auth import normalizar_roles, require_permiso
from app.main import app
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.aprobaciones.registro import Objetivo
from app.modules.aprobaciones.servicio import Servicio
from app.modules.cuentas import retenciones as r
from tests.sesion import usuario_con_roles


@pytest.mark.parametrize(
    ("tipo", "saldo", "monto"),
    [("OrdenJudicial", 40, 40), ("OrdenJudicial", 0, 0), ("Administrativa", 100, 60)],
)
def test_importe_retenido_respeta_el_disponible(tipo, saldo, monto):
    alta = r.Alta.model_validate(
        {
            "tipoRetencion": tipo,
            "monto": 60,
            "motivo": "Orden de prueba",
            "documentoReferencia": "QA-123",
        }
    )
    fila = {"Estado": "Activa", "Saldo": Decimal(saldo), "SaldoRetenido": Decimal(0)}
    assert r.monto_aplicable(fila, alta) == monto


def test_retencion_administrativa_rechaza_monto_mayor_al_disponible():
    alta = r.Alta.model_validate(
        {
            "tipoRetencion": "Administrativa",
            "monto": 60,
            "motivo": "Prueba",
            "documentoReferencia": "QA-123",
        }
    )
    with pytest.raises(HTTPException) as error:
        r.monto_aplicable(
            {"Estado": "Activa", "Saldo": Decimal(100), "SaldoRetenido": Decimal(50)},
            alta,
        )
    assert error.value.status_code == 409
    assert isinstance(error.value.detail, dict)
    assert cast(dict[str, object], error.value.detail)["code"] == "SALDO_INSUFICIENTE"


def test_alta_y_liberacion_requieren_permiso_y_cola():
    paths = app.openapi()["paths"]
    for ruta in (
        "/api/v1/cuentas/{idCuenta}/retenciones",
        "/api/v1/cuentas/{idCuenta}/retenciones/{idRet}/liberacion",
    ):
        assert "202" in paths[ruta]["post"]["responses"]
        assert paths[ruta]["post"]["security"]

    registro = registro_inicial()
    for codigo, tipo in [
        ("CTA-RETENCION", "CuentaRetencion"),
        ("CTA-LIBERACION", "Retencion"),
    ]:
        op = registro.obtener(codigo, tipo)
        assert op.permiso_aprobacion == op.permiso_ejecucion == "cta-retencion"
        assert not op.solicitud_directa
        assert op.base == "cooperativa"


def test_sesion_de_cumplimiento_puede_solicitar_con_permiso_y_agencia():
    roles = normalizar_roles(["org-cumplimiento"], None)
    assert roles == ("CUMPLIMIENTO",)
    sesion = usuario_con_roles(*roles)
    assert require_permiso("cta-retencion")(sesion) == sesion
    operacion = registro_inicial().obtener("CTA-RETENCION", "CuentaRetencion")
    actor = Actor(
        "cumplimiento", "org-qa", None, 1, roles, frozenset(sesion.permisos), ("001",)
    )
    Servicio.puede_solicitar(actor, operacion, Objetivo("CuentaRetencion", "8", "001"))

    with pytest.raises(HTTPException) as ausencia:
        require_permiso("cta-retencion")(usuario_con_roles("ASESOR"))
    assert ausencia.value.status_code == 403
    with pytest.raises(HTTPException) as agencia:
        Servicio.puede_solicitar(
            actor, operacion, Objetivo("CuentaRetencion", "8", "002")
        )
    assert agencia.value.status_code == 404
