from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import HTTPException

from app.modules.auth import recuperacion_correo as rec


@pytest.fixture
def escenario(monkeypatch):
    motor = MagicMock()
    conn = motor.begin.return_value.__enter__.return_value
    fila = {
        "KeyUsuario": "user_qa",
        "Email": "qa@example.test",
        "RolesWorkOS": "CAJERO",
    }
    resultado = conn.execute.return_value
    resultado.first.return_value = ("user_qa", "Email", None)
    remoto = SimpleNamespace(email="otro@example.test")
    miembro = SimpleNamespace(id="om_qa", roles=[{"slug": "org-auditor"}])
    gestion = MagicMock()
    gestion.get_user.return_value = remoto

    def actualizar(**kwargs):
        remoto.email = kwargs["email"]

    def actualizar_roles(**kwargs):
        miembro.roles = [{"slug": kwargs["role_slug"]}]

    gestion.update_user.side_effect = actualizar
    gestion.update_organization_membership.side_effect = actualizar_roles
    mocks = SimpleNamespace(
        bloqueo=MagicMock(),
        cargar=MagicMock(return_value=fila),
        membresia=MagicMock(return_value=miembro),
        ultimo_admin=MagicMock(),
        sesiones=MagicMock(),
        invitaciones=MagicMock(),
    )
    monkeypatch.setattr(
        rec, "get_workos", lambda: SimpleNamespace(user_management=gestion)
    )
    monkeypatch.setattr(rec.repository, "obtener_usuario", mocks.cargar)
    monkeypatch.setattr(
        rec.service, "_serializar_cambios_administrativos", mocks.bloqueo
    )
    monkeypatch.setattr(rec.service, "_membresia", mocks.membresia)
    monkeypatch.setattr(rec.service, "_validar_ultimo_admin", mocks.ultimo_admin)
    monkeypatch.setattr(rec.service, "_revocar_sesiones", mocks.sesiones)
    monkeypatch.setattr(rec.service, "_invitaciones_pendientes", mocks.invitaciones)
    return SimpleNamespace(
        motor=motor,
        conn=conn,
        resultado=resultado,
        fila=fila,
        remoto=remoto,
        miembro=miembro,
        gestion=gestion,
        mocks=mocks,
    )


def escrituras(escenario, fragmento):
    return [
        llamada.args[1]
        for llamada in escenario.conn.execute.call_args_list
        if fragmento in str(llamada.args[0])
    ]


def test_registrar_persiste_intencion_y_rechaza_solapamiento(escenario):
    escenario.conn.scalar.return_value = None
    escenario.resultado.scalar_one.return_value = 13
    assert (
        rec.registrar(
            escenario.motor, 7, "inv_qa", "Invitar", correo_alterno="qa@example.test"
        )
        == 13
    )
    assert escrituras(escenario, "INSERT") == [
        {
            "id": 7,
            "llave": "inv_qa",
            "operacion": "Invitar",
            "correo": "qa@example.test",
        }
    ]
    escenario.motor.begin.return_value.__exit__.assert_called_once_with(
        None, None, None
    )
    escenario.conn.scalar.return_value = 1
    with pytest.raises(HTTPException) as error:
        rec.registrar(escenario.motor, 7, "user_qa")
    assert error.value.status_code == 409
    assert len(escrituras(escenario, "INSERT")) == 1


def test_pendientes_y_error_no_cambian_estado_del_trabajo(escenario):
    lectura = escenario.motor.connect.return_value.__enter__.return_value
    lectura.execute.return_value = [
        SimpleNamespace(IdSincronizacion=13, UsuarioID=7),
        SimpleNamespace(IdSincronizacion=14, UsuarioID=8),
    ]
    assert rec.pendientes(escenario.motor) == [(13, 7), (14, 8)]
    rec.registrar_error(escenario.motor, 13)
    assert escrituras(escenario, "Intentos=Intentos+1") == [{"id": 13}]
    assert escrituras(escenario, "Estado='Completada'") == []


def test_reconciliar_correo_tras_respuesta_ambigua(escenario):
    def actualizar(**kwargs):
        escenario.remoto.email = kwargs["email"]
        raise httpx.ReadTimeout("respuesta perdida")

    escenario.gestion.update_user.side_effect = actualizar
    with pytest.raises(HTTPException) as error:
        rec.reconciliar(escenario.motor, 13, 7)
    assert error.value.status_code == 503
    assert escrituras(escenario, "Estado='Completada'") == []
    rec.reconciliar(escenario.motor, 13, 7)
    escenario.gestion.update_user.assert_called_once_with(
        user_id="user_qa", email="qa@example.test"
    )
    assert escrituras(escenario, "Estado='Completada'") == [{"id": 13}]
    escenario.mocks.cargar.assert_called_with(escenario.conn, 7, bloquear=True)


def test_confirma_correo_sin_distinguir_mayusculas_y_rechaza_desfase(escenario):
    rec.confirmar("user_qa", "OTRO@example.test")
    with pytest.raises(HTTPException) as error:
        rec.confirmar("user_qa", "qa@example.test")
    assert error.value.status_code == 503


@pytest.mark.parametrize("caso", ["sin_trabajo", "sin_fila", "otro_vinculo"])
def test_reconciliar_no_escribe_si_el_trabajo_o_vinculo_no_coinciden(escenario, caso):
    if caso == "sin_trabajo":
        escenario.resultado.first.return_value = None
        rec.reconciliar(escenario.motor, 13, 7)
    else:
        if caso == "sin_fila":
            escenario.mocks.cargar.return_value = None
        else:
            escenario.fila["KeyUsuario"] = "user_otra"
        with pytest.raises(HTTPException) as error:
            rec.reconciliar(escenario.motor, 13, 7)
        assert error.value.status_code == 409
    assert escrituras(escenario, "Estado='Completada'") == []
    assert escenario.gestion.mock_calls == []


def test_roles_recupera_valor_sql_y_revalida_ultimo_admin(escenario):
    escenario.resultado.first.return_value = ("user_qa", "Roles", None)
    rec.reconciliar(escenario.motor, 13, 7)
    rec.reconciliar(escenario.motor, 13, 7)
    escenario.mocks.ultimo_admin.assert_called_once_with(escenario.conn, escenario.fila)
    escenario.gestion.update_organization_membership.assert_called_once_with(
        organization_membership_id="om_qa", role_slug="org-cajero"
    )
    assert escrituras(escenario, "Estado='Completada'") == [{"id": 13}, {"id": 13}]


def test_roles_no_confirma_si_workos_no_refleja_la_escritura(escenario):
    escenario.resultado.first.return_value = ("user_qa", "Roles", None)
    escenario.gestion.update_organization_membership.side_effect = None
    with pytest.raises(HTTPException) as error:
        rec.reconciliar(escenario.motor, 13, 7)
    assert error.value.status_code == 503
    assert escrituras(escenario, "Estado='Completada'") == []
    escenario.mocks.sesiones.assert_not_called()


def test_roles_sin_membresia_pide_revision(escenario):
    escenario.resultado.first.return_value = ("user_qa", "Roles", None)
    escenario.mocks.membresia.return_value = None
    with pytest.raises(HTTPException) as error:
        rec.reconciliar(escenario.motor, 13, 7)
    assert error.value.status_code == 409
    escenario.gestion.update_organization_membership.assert_not_called()


@pytest.mark.parametrize("caso", ["unica", "duplicada", "alterna", "vinculada"])
def test_invitacion_solo_cierra_con_evidencia_inequivoca(escenario, caso):
    escenario.resultado.first.return_value = ("inv_qa", "Invitar", "otro@example.test")
    escenario.fila["KeyUsuario"] = "user_qa" if caso == "vinculada" else None
    original = SimpleNamespace(id="inv_qa")
    otra = SimpleNamespace(id="inv_otra")
    escenario.mocks.invitaciones.side_effect = [
        [original, otra] if caso == "duplicada" else [original],
        [otra] if caso == "alterna" else [],
    ]
    if caso == "unica":
        rec.reconciliar(escenario.motor, 13, 7)
        assert escrituras(escenario, "Estado='Completada'") == [{"id": 13}]
    else:
        with pytest.raises(HTTPException) as error:
            rec.reconciliar(escenario.motor, 13, 7)
        assert error.value.status_code == 409
        assert escrituras(escenario, "Estado='Completada'") == []
    assert escenario.gestion.mock_calls == []
