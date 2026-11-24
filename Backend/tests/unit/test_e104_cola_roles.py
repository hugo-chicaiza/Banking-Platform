from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.modules.aprobaciones.auditoria import ContextoAuditoria
from app.modules.aprobaciones.congelacion import congelar
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.registro import Operacion, Registro
from app.modules.aprobaciones.servicio import Servicio
from app.modules.auth.aprobacion_roles import CODIGO, TIPO, validar_aprobador

CONTEXTO = ContextoAuditoria()


@pytest.fixture
def cola():
    org = "org_qa"
    solicitante = Actor("maker", org, None, 10, ("ADMIN",), frozenset(), ())
    aprobador = Actor(
        "checker", org, None, 11, ("AUDITOR",), frozenset({"qa:roles"}), ()
    )
    actores = {a.sujeto: a for a in (solicitante, aprobador)}
    motor = MagicMock()
    conn = MagicMock()
    motor.connect.return_value.__enter__.return_value = conn
    motor.begin.return_value.__enter__.return_value = conn
    manejador = MagicMock()
    manejador.version.return_value = "v1"
    propuesta = congelar(
        {"cambio": {"roles": ["AUDITOR"]}, "antes": {}, "despues": {}, "version": "v1"}
    )
    fila = {
        "IdSolicitud": 3,
        "IdOrganizacion": org,
        "CodigoTransaccion": CODIGO,
        "TipoObjetivo": TIPO,
        "IdObjetivo": "7",
        "IdAgencia": None,
        "Estado": "Pendiente",
        "SolicitadoPor": solicitante.sujeto,
        "IdInternoSolicitante": solicitante.id_interno,
        "ResueltoPor": aprobador.sujeto,
        "VersionObjetivo": "v1",
        "Contenido": propuesta.texto,
        "HashContenido": propuesta.huella,
        "BaseObjetivo": "seguridad",
        "PermisoAprobacion": "qa:roles",
        "RolesEjecucion": '["ADMIN"]',
    }
    registro = Registro()
    registro.agregar(
        Operacion(
            CODIGO,
            TIPO,
            "seguridad",
            frozenset({"ADMIN"}),
            "qa:roles",
            manejador,
            aplicar_diferido=True,
            validar_aprobador=validar_aprobador,
        )
    )
    cambios = []
    auditoria = []
    datos = SimpleNamespace(comprobante=None)

    def ejecutar(sentencia, parametros):
        sql = str(sentencia)
        resultado = MagicMock()
        if "sp_getapplock" in sql:
            resultado.scalar_one.return_value = 0
        elif "SELECT HashContenido" in sql:
            resultado.scalar.return_value = datos.comprobante
        elif "INSERT Seguridad.AprobacionAplicada" in sql:
            datos.comprobante = parametros["hash"]
        elif "UPDATE Seguridad.SolicitudAprobacion" in sql:
            cambios.append((sql, parametros))
            if "SET Estado='Aprobada'" in sql:
                fila["Estado"] = "Aprobada"
            elif "SET Estado='Ejecutada'" in sql:
                fila["Estado"] = "Ejecutada"
            elif "estado" in parametros:
                fila["Estado"] = parametros["estado"]
        elif "INSERT Auditoria.EventoPendiente" in sql:
            auditoria.append(parametros["codigo"])
        else:
            resultado.mappings.return_value.first.return_value = dict(fila)
        return resultado

    conn.execute.side_effect = ejecutar
    servicio = Servicio(motor, motor, registro, lambda sujeto, _: actores[sujeto])
    return SimpleNamespace(
        servicio=servicio,
        motor=motor,
        fila=fila,
        actores=actores,
        solicitante=solicitante,
        aprobador=aprobador,
        manejador=manejador,
        cambios=cambios,
        auditoria=auditoria,
        datos=datos,
        org=org,
    )


def test_aprobacion_confirma_decision_antes_de_aplicar(cola):
    def aplicar(*_):
        assert cola.fila["Estado"] == "Aprobada"
        cola.motor.begin.return_value.__exit__.assert_called_once_with(None, None, None)

    cola.manejador.aplicar.side_effect = aplicar
    assert (
        cola.servicio.aprobar(cola.aprobador, 3, None, CONTEXTO)["estado"]
        == "Ejecutada"
    )
    assert cola.servicio.ejecutar(3, cola.org, None, CONTEXTO)["estado"] == "Ejecutada"
    cola.manejador.aplicar.assert_called_once()
    assert cola.datos.comprobante == cola.fila["HashContenido"]


@pytest.mark.parametrize(
    ("caso", "estado"),
    [
        ("propia", 403),
        ("objetivo", 403),
        ("sin_permiso", 403),
        ("sin_solicitante", 409),
    ],
)
def test_rechaza_aprobacion_sin_autorizacion(cola, caso, estado):
    actor = cola.aprobador
    if caso == "propia":
        actor = cola.solicitante
    elif caso == "objetivo":
        actor = replace(actor, id_interno=7)
    elif caso == "sin_permiso":
        actor = replace(actor, permisos=frozenset())
    else:
        cola.actores["maker"] = replace(cola.solicitante, roles=("CAJERO",))
    with pytest.raises(HTTPException) as error:
        cola.servicio.aprobar(actor, 3, None, CONTEXTO)
    assert error.value.status_code == estado
    cola.manejador.aplicar.assert_not_called()
    if caso == "propia":
        assert "APR_AUTOAPROBACION_INTENTO" in cola.auditoria
    if caso == "sin_solicitante":
        assert "APR_SOLICITUD_CANCELADA" in cola.auditoria


@pytest.mark.parametrize(
    ("accion", "por_aprobador", "comentario", "error"),
    [
        ("Rechazada", True, "Incompatible con sus funciones", None),
        ("Rechazada", False, "Motivo", 403),
        ("Rechazada", True, " ", 422),
        ("Cancelada", False, "", None),
        ("Cancelada", True, "", 403),
    ],
)
def test_rechazo_y_cancelacion_preservan_el_objetivo(
    cola, accion, por_aprobador, comentario, error
):
    actor = cola.aprobador if por_aprobador else cola.solicitante
    if error:
        with pytest.raises(HTTPException) as exc:
            cola.servicio.resolver(actor, 3, accion, comentario, CONTEXTO)
        assert exc.value.status_code == error
        assert cola.fila["Estado"] == "Pendiente"
    else:
        assert (
            cola.servicio.resolver(actor, 3, accion, comentario, CONTEXTO)["estado"]
            == accion
        )
    cola.manejador.aplicar.assert_not_called()
    assert cola.datos.comprobante is None


@pytest.mark.parametrize("fallo", ["permiso_revocado", "version", "commit"])
def test_recuperacion_conserva_aprobada_hasta_confirmar(cola, fallo):
    cola.fila["Estado"] = "Aprobada"
    if fallo == "permiso_revocado":
        cola.actores["checker"] = replace(cola.aprobador, permisos=frozenset())
    elif fallo == "version":
        cola.manejador.version.return_value = "v2"
    else:
        cola.manejador.aplicar.side_effect = SQLAlchemyError("fallo transaccional")
    with pytest.raises(HTTPException) as error:
        cola.servicio.ejecutar(3, cola.org, None, CONTEXTO)
    assert error.value.status_code == 503
    assert cola.fila["Estado"] == "Aprobada"
    assert cola.datos.comprobante is None
    if fallo != "commit":
        assert any("Intentos=Intentos+1" in sql for sql, _ in cola.cambios)
        cola.manejador.aplicar.assert_not_called()


@pytest.mark.parametrize("comprobante_integro", [True, False])
def test_recuperacion_verifica_comprobante_antes_de_repetir_efecto(
    cola, comprobante_integro
):
    cola.fila["Estado"] = "Aprobada"
    cola.datos.comprobante = (
        cola.fila["HashContenido"] if comprobante_integro else bytes(32)
    )
    if comprobante_integro:
        assert (
            cola.servicio.ejecutar(3, cola.org, None, CONTEXTO)["estado"] == "Ejecutada"
        )
    else:
        with pytest.raises(HTTPException) as error:
            cola.servicio.ejecutar(3, cola.org, None, CONTEXTO)
        assert error.value.status_code == 503
        assert cola.fila["Estado"] == "Aprobada"
    cola.manejador.aplicar.assert_not_called()
