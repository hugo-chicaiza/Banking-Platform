from datetime import date
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException

from app.core.security.auth import ROLES
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.registro import Objetivo
from app.modules.auth import aprobacion_roles as roles
from app.modules.auth.politica_roles import PoliticaRoles

OBJETIVO = Objetivo(roles.TIPO, "7", None)
CAMBIO = {"anteriores": ["CAJERO"], "roles": ["CAJERO", "AUDITOR"]}


@pytest.fixture
def escenario(monkeypatch):
    conn = MagicMock()
    coop = MagicMock()
    motor = MagicMock()
    motor.connect.return_value.__enter__.return_value = coop
    opciones = SimpleNamespace(
        e104_politica_roles_activa=True,
        e104_corte_asignacion_caja=False,
        e104_recuperar_correo=True,
        e104_permiso_aprobar_roles=" qa:roles ",
    )
    fila = {
        "Estado": "Activo",
        "KeyUsuario": "user_qa",
        "AgenciaID": 1,
        "RolesWorkOS": "CAJERO",
    }
    miembro = SimpleNamespace(
        id="om_qa", status="active", roles=[{"slug": "org-cajero"}]
    )
    actor = Actor("solicitante", "org_qa", None, 12, ("ADMIN",), frozenset(), ())
    gestion = MagicMock()
    politica = PoliticaRoles(
        niveles={rol: 1 for rol in ROLES}, privilegiados={"AUDITOR"}, incompatibles=[]
    )
    for destino, atributo, reemplazo in (
        (roles, "get_settings", lambda: opciones),
        (roles, "get_engine", lambda _: motor),
        (roles, "get_organizacion_id", lambda: "org_qa"),
        (roles, "get_workos", lambda: SimpleNamespace(user_management=gestion)),
        (roles.identidad, "vigente", MagicMock(return_value=actor)),
        (roles.politica_roles, "vigente", lambda: politica),
        (roles.service, "_serializar_cambios_administrativos", MagicMock()),
        (roles.service, "_cargar", MagicMock(return_value=fila)),
        (roles.service, "_membresia", MagicMock(return_value=miembro)),
        (roles.service, "_validar_ultimo_admin", MagicMock()),
        (roles.service, "_revocar_sesiones", MagicMock()),
        (roles.service, "bloquear_corte_caja", MagicMock()),
        (roles.repository, "sincronizacion_pendiente", MagicMock(return_value=False)),
        (roles.repository, "actualizar_rol", MagicMock()),
        (roles.agencias_repository, "asignaciones", MagicMock(return_value=["001"])),
        (roles, "jornada_abierta_de_usuario", MagicMock(return_value=None)),
    ):
        monkeypatch.setattr(destino, atributo, reemplazo)
    return SimpleNamespace(
        conn=conn,
        coop=coop,
        motor=motor,
        opciones=opciones,
        fila=fila,
        miembro=miembro,
        actor=actor,
        gestion=gestion,
        politica=politica,
    )


def test_registro_y_bloqueo_solo_con_configuracion(escenario):
    operacion = roles.operacion()
    assert operacion is not None
    assert operacion.permiso_aprobacion == "qa:roles"
    assert operacion.aplicar_diferido and not operacion.solicitud_directa
    with roles.corte_protegido():
        escenario.motor.connect.assert_not_called()
    escenario.opciones.e104_corte_asignacion_caja = True
    with roles.corte_protegido():
        cast(MagicMock, roles.service.bloquear_corte_caja).assert_called_once_with(
            escenario.coop
        )
    escenario.motor.connect.return_value.__exit__.assert_called_once()
    escenario.opciones.e104_permiso_aprobar_roles = ""
    assert roles.operacion() is None


def test_aprobador_no_puede_ser_usuario_objetivo():
    roles.validar_aprobador(OBJETIVO, 12)
    with pytest.raises(HTTPException) as error:
        roles.validar_aprobador(OBJETIVO, 7)
    assert error.value.status_code == 403


def test_aprobacion_suspendida_no_registra_ni_aplica_cambios(escenario):
    escenario.opciones.e104_politica_roles_activa = False
    assert roles.operacion() is None
    with pytest.raises(HTTPException) as error:
        roles.CambioRoles().aplicar(escenario.conn, OBJETIVO, CAMBIO, "solicitante", 1)
    assert error.value.status_code == 503
    escenario.gestion.assert_not_called()
    assert escenario.gestion.mock_calls == []


def test_preparar_congela_cambio_y_version_de_agencia(escenario):
    manejador = roles.CambioRoles()
    plan = manejador.preparar(
        escenario.conn, OBJETIVO, {"roles": CAMBIO["roles"]}, date.today()
    )
    assert plan.contenido == CAMBIO
    assert plan.antes == {"roles": ["CAJERO"]}
    assert plan.despues == {"roles": CAMBIO["roles"]}
    assert plan.version == manejador.version(escenario.conn, OBJETIVO)
    escenario.fila["AgenciaID"] = 2
    assert plan.version != manejador.version(escenario.conn, OBJETIVO)
    assert escenario.gestion.mock_calls == []


@pytest.mark.parametrize(
    "caso", ["diario", "inactivo", "sin_vinculo", "membresia", "desfase", "corte"]
)
def test_preparar_rechaza_objetivo_inconsistente(escenario, caso):
    propuesta = CAMBIO["roles"]
    if caso == "diario":
        cast(MagicMock, roles.repository.sincronizacion_pendiente).return_value = True
    elif caso == "inactivo":
        escenario.fila["Estado"] = "Inactivo"
    elif caso == "sin_vinculo":
        escenario.fila["KeyUsuario"] = None
    elif caso == "membresia":
        escenario.miembro.status = "inactive"
    elif caso == "desfase":
        escenario.miembro.roles = [{"slug": "org-admin"}]
    else:
        propuesta = ["AUDITOR"]
    with pytest.raises(HTTPException) as error:
        roles.CambioRoles().preparar(
            escenario.conn, OBJETIVO, {"roles": propuesta}, date.today()
        )
    assert error.value.status_code == 409
    escenario.gestion.update_organization_membership.assert_not_called()


@pytest.mark.parametrize(
    ("caso", "estado"),
    [
        ("sin_permiso", 403),
        ("propio", 403),
        ("corte", 409),
        ("politica", 409),
        ("jornada", 409),
        ("sql", 409),
        ("sin_membresia", 409),
        ("remoto", 409),
        ("sin_confirmacion", 503),
    ],
)
def test_aplicar_revalida_antes_de_confirmar_sql(escenario, caso, estado):
    cambio = CAMBIO
    if caso in {"sin_permiso", "propio"}:
        cast(MagicMock, roles.identidad.vigente).return_value = SimpleNamespace(
            global_admin=caso == "propio", id_interno=7, roles=("ADMIN",)
        )
    elif caso == "corte":
        cambio = {**CAMBIO, "roles": ["AUDITOR"]}
    elif caso == "politica":
        escenario.politica.privilegiados.clear()
    elif caso == "jornada":
        cast(MagicMock, roles.jornada_abierta_de_usuario).return_value = {
            "IdJornada": 1
        }
    elif caso == "sql":
        escenario.fila["RolesWorkOS"] = "SUPERVISOR"
    elif caso == "sin_membresia":
        cast(MagicMock, roles.service._membresia).return_value = None
    elif caso == "remoto":
        escenario.miembro.roles = [{"slug": "org-supervisor"}]
    with pytest.raises(HTTPException) as error:
        roles.CambioRoles().aplicar(escenario.conn, OBJETIVO, cambio, "solicitante", 11)
    assert error.value.status_code == estado
    cast(MagicMock, roles.repository.actualizar_rol).assert_not_called()
    cast(MagicMock, roles.service._revocar_sesiones).assert_not_called()
    if caso != "sin_confirmacion":
        escenario.gestion.update_organization_membership.assert_not_called()


def test_respuesta_ambigua_se_recupera_sin_repetir_escritura(escenario):
    def actualizar(**kwargs):
        escenario.miembro.roles = [{"slug": slug} for slug in kwargs["role_slugs"]]
        raise httpx.ReadTimeout("respuesta perdida")

    escritura = escenario.gestion.update_organization_membership
    escritura.side_effect = actualizar
    manejador = roles.CambioRoles()
    with pytest.raises(HTTPException) as error:
        manejador.aplicar(escenario.conn, OBJETIVO, CAMBIO, "solicitante", 11)
    assert error.value.status_code == 503
    cast(MagicMock, roles.repository.actualizar_rol).assert_not_called()
    manejador.aplicar(escenario.conn, OBJETIVO, CAMBIO, "solicitante", 11)
    escritura.assert_called_once()
    cast(MagicMock, roles.service._revocar_sesiones).assert_called_once_with("user_qa")
    cast(MagicMock, roles.repository.actualizar_rol).assert_called_once_with(
        escenario.conn, 7, "CAJERO,AUDITOR"
    )
