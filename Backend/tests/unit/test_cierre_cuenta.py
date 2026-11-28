from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from typing import cast
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import HTTPException, Request
from sqlalchemy import Connection, Engine

from app.main import app
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.aprobaciones.registro import Objetivo
from app.modules.cuentas import cierre, cierre_api
from tests.sesion import usuario_con_roles


def _cuenta(**cambios):
    return {
        "IdCuenta": 501,
        "NumeroCuenta": "00000501",
        "IdCliente": 125,
        "IdAgencia": "001",
        "Estado": "Activa",
        "Saldo": Decimal("0.00"),
        "SaldoRetenido": Decimal("0.00"),
        "FechaCierre": None,
        **cambios,
    }


def _cola(seguridad: object) -> cierre_api.aprobaciones.Servicio:
    return cierre_api.aprobaciones.Servicio(
        cast(Engine, seguridad), cast(Engine, Mock()), registro_inicial()
    )


@pytest.mark.parametrize("bloquear", [False, True])
def test_lectura_cuenta_parametriza_agencia_y_bloqueo(bloquear):
    conn = Mock(spec=Connection)
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = _cuenta()

    resultado = cierre._cuenta(conn, 501, "001", bloquear=bloquear)

    consulta, parametros = conn.execute.call_args.args
    assert resultado["IdCuenta"] == 501
    assert ("WITH (XLOCK,HOLDLOCK)" in str(consulta)) is bloquear
    assert parametros == {"id": 501, "agencia": "001"}


def test_lectura_cuenta_no_cruza_agencias():
    conn = Mock(spec=Connection)
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = None

    with pytest.raises(HTTPException) as error:
        cierre._cuenta(conn, 501, "002")

    assert error.value.status_code == 404
    detalle = getattr(error.value, "detail", None)
    assert isinstance(detalle, dict)
    assert detalle["code"] == "CUENTA_NO_ENCONTRADA"


@pytest.mark.parametrize(
    ("encontrada", "excluir", "esperado"),
    [(1, None, True), (None, 15, False)],
)
def test_consultas_pendientes_se_parametrizan_y_pueden_excluir_cierre(
    encontrada, excluir, esperado
):
    seguridad = MagicMock()
    conn = seguridad.connect.return_value.__enter__.return_value
    conn.execute.return_value.scalar.return_value = encontrada

    assert cierre._solicitudes_pendientes(seguridad, 501, excluir) is esperado

    consulta, parametros = conn.execute.call_args.args
    assert "AND (:excluir IS NULL OR IdSolicitud<>:excluir)" in str(consulta)
    assert parametros == {
        "id": "501",
        "id_prefijo": "501:%",
        "excluir": excluir,
    }


def test_version_del_cierre_incluye_la_fecha_de_cierre(monkeypatch):
    monkeypatch.setattr(
        cierre,
        "_cuenta",
        Mock(return_value=_cuenta(FechaCierre=date(2026, 11, 27))),
    )

    version = cierre.Cierre().version(
        Mock(spec=Connection), Objetivo("Cuenta", "501", "001")
    )

    assert version == "Activa:2026-11-27"


def test_version_del_cierre_exige_agencia():
    with pytest.raises(HTTPException) as error:
        cierre.Cierre().version(Mock(spec=Connection), Objetivo("Cuenta", "501", None))

    assert error.value.status_code == 403


def test_lista_cierre_nombra_todos_los_impedimentos_simultaneos(monkeypatch):
    cuenta = _cuenta(Saldo=Decimal("10.00"), SaldoRetenido=Decimal("1.00"))
    monkeypatch.setattr(cierre, "_cuenta", Mock(return_value=cuenta))
    monkeypatch.setattr(cierre, "_retenciones_activas", Mock(return_value=True))
    monkeypatch.setattr(cierre, "_tarjetas_vivas", Mock(return_value=True))
    monkeypatch.setattr(cierre, "_credito_vigente", Mock(return_value=True))
    monkeypatch.setattr(cierre, "_solicitudes_pendientes", Mock(return_value=True))

    resultado = cierre.lista_cierre(Mock(spec=Connection), 501, "001", seguridad=Mock())

    por_codigo = {v.codigo: v.resultado for v in resultado.verificaciones}
    assert por_codigo == {
        "saldoCero": "Impide",
        "sinRetencionesActivas": "Impide",
        "sinTarjetasVivas": "Impide",
        "sinCreditoRespaldado": "Impide",
        "sinSolicitudesPendientes": "Impide",
        "sinInteresDevengadoImpago": "NoVerificable",
        "estadoCuenta": "Cumple",
    }
    assert resultado.puede_cerrar is False
    assert all(v.detalle for v in resultado.verificaciones)


def test_lista_cierre_falla_cerrado_si_interes_no_tiene_fuente(monkeypatch):
    conn = Mock(spec=Connection)
    monkeypatch.setattr(cierre, "_cuenta", Mock(return_value=_cuenta()))
    monkeypatch.setattr(cierre, "_retenciones_activas", Mock(return_value=False))
    monkeypatch.setattr(cierre, "_tarjetas_vivas", Mock(return_value=False))
    monkeypatch.setattr(cierre, "_credito_vigente", Mock(return_value=False))
    monkeypatch.setattr(cierre, "_solicitudes_pendientes", Mock(return_value=False))
    resultado = cierre.lista_cierre(conn, 501, "001", seguridad=Mock())

    interes = next(
        v for v in resultado.verificaciones if v.codigo == "sinInteresDevengadoImpago"
    )
    assert interes.resultado == "NoVerificable"
    assert resultado.puede_cerrar is False


@pytest.mark.parametrize(
    ("desembolsos", "deudas", "esperado"),
    [
        ([{"id_solicitud": 7, "estado": "PENDIENTE"}], [], True),
        ([{"id_solicitud": 7, "estado": "DESEMBOLSADO"}], [True], True),
        ([{"id_solicitud": 7, "estado": "DESEMBOLSADO"}], [False], False),
        ([{"id_solicitud": 7, "estado": "REVERSADO"}], [], False),
    ],
)
def test_credito_respaldado_reutiliza_vinculo_y_estado_deuda(
    monkeypatch, desembolsos, deudas, esperado
):
    conn = Mock(spec=Connection)
    monkeypatch.setattr(
        cierre.repository, "desembolsos_de_cuenta", Mock(return_value=desembolsos)
    )
    tiene_deuda = Mock(side_effect=deudas)
    monkeypatch.setattr(cierre.clientes_service, "credito_tiene_deuda", tiene_deuda)

    assert cierre._credito_vigente(conn, 501) is esperado
    if desembolsos and desembolsos[0]["estado"] == "DESEMBOLSADO":
        tiene_deuda.assert_called_once_with(conn, 7)
    else:
        tiene_deuda.assert_not_called()


def test_tarjetas_generadas_y_solicitadas_cuentan_como_vivas():
    conn = Mock(spec=Connection)
    conn.execute.return_value.scalar.return_value = 1

    assert cierre._tarjetas_vivas(conn, 501)

    sql, parametros = conn.execute.call_args.args
    assert "Estado NOT IN" in str(sql)
    assert set(parametros.values()) == {
        501,
        "Anulada",
        "Cancelada",
        "Cerrada",
        "Vencida",
    }


def test_retencion_activa_de_monto_cero_no_se_ignora():
    conn = Mock(spec=Connection)
    conn.execute.return_value.scalar.return_value = 1

    assert cierre._retenciones_activas(conn, 501)

    sql, parametros = conn.execute.call_args.args
    assert "Estado='Activa'" in str(sql)
    assert "Monto" not in str(sql)
    assert parametros == {"id": 501}


def test_preparar_cierre_rechaza_y_devuelve_todos_los_puntos(monkeypatch):
    resultado = cierre.ListaCierre(
        id_cuenta=501,
        puede_cerrar=False,
        verificaciones=[
            cierre.VerificacionCierre(
                codigo="saldoCero", resultado="Impide", detalle="Saldo pendiente."
            ),
            cierre.VerificacionCierre(
                codigo="sinInteresDevengadoImpago",
                resultado="NoVerificable",
                detalle="Origen no disponible.",
            ),
        ],
    )
    monkeypatch.setattr(cierre, "get_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(cierre, "lista_cierre", Mock(return_value=resultado))

    with pytest.raises(HTTPException) as error:
        cierre.Cierre().preparar(
            Mock(spec=Connection),
            Objetivo("Cuenta", "501", "001"),
            {"motivo": "Solicitud del titular"},
            date(2026, 11, 27),
        )

    assert error.value.status_code == 409
    detalle = getattr(error.value, "detail", None)
    assert isinstance(detalle, dict)
    assert detalle["code"] == "CIERRE_INCOMPLETO"
    assert detalle["bloqueos"] == [
        "saldoCero: Impide — Saldo pendiente.",
        "sinInteresDevengadoImpago: NoVerificable — Origen no disponible.",
    ]


def test_preparar_cierre_rechaza_contenido_invalido():
    with pytest.raises(HTTPException) as error:
        cierre.Cierre().preparar(
            Mock(spec=Connection),
            Objetivo("Cuenta", "501", "001"),
            {"motivo": "   "},
            date(2026, 11, 27),
        )

    assert error.value.status_code == 422


def test_preparar_cierre_conserva_la_version_y_el_motivo(monkeypatch):
    cuenta = _cuenta()
    lista = cierre.ListaCierre(id_cuenta=501, puede_cerrar=True, verificaciones=[])
    monkeypatch.setattr(cierre, "get_engine", Mock(return_value=object()))
    monkeypatch.setattr(cierre, "_cuenta", Mock(return_value=cuenta))
    monkeypatch.setattr(cierre, "lista_cierre", Mock(return_value=lista))

    plan = cierre.Cierre().preparar(
        Mock(spec=Connection),
        Objetivo("Cuenta", "501", "001"),
        {"motivo": "Solicitud del titular"},
        date(2026, 11, 27),
    )

    assert plan.contenido == {"motivo": "Solicitud del titular"}
    assert plan.antes == {"estado": "Activa"}
    assert plan.despues == {"estado": "Cerrada"}
    assert plan.version == "Activa:"


def test_aplicacion_cierra_bajo_bloqueo_y_audita_al_aprobador(monkeypatch):
    conn = Mock(spec=Connection)
    cuenta_mock = Mock(return_value=_cuenta())
    lista_mock = Mock(
        return_value=cierre.ListaCierre(
            id_cuenta=501,
            puede_cerrar=True,
            verificaciones=[
                cierre.VerificacionCierre(
                    codigo="saldoCero", resultado="Cumple", detalle="Cero."
                )
            ],
        )
    )
    monkeypatch.setattr(cierre, "_cuenta", cuenta_mock)
    monkeypatch.setattr(cierre, "get_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(cierre, "lista_cierre", lista_mock)
    actualizar = Mock()
    monkeypatch.setattr(cierre.repository, "actualizar_estado_cuenta", actualizar)

    cierre.cerrar(conn, 501, "001", 88, 15)

    assert cuenta_mock.call_args_list[0].kwargs == {"bloquear": True}
    assert lista_mock.call_args.kwargs["bloquear"] is True
    actualizar.assert_called_once_with(conn, 501, "CERRADA")
    sql, parametros = conn.execute.call_args.args
    assert "INSERT Cuentas.CuentaEvento" in str(sql)
    assert parametros == {
        "cuenta": 501,
        "anterior": "Activa",
        "detalle": "Cierre aprobado (solicitud 15)",
        "aprobador": 88,
        "agencia": "001",
    }


def test_aplicacion_acredita_aprobacion_de_la_misma_agencia(monkeypatch):
    conn = Mock(spec=Connection)
    seguridad = Mock()
    seguridad.execute.return_value.scalar_one_or_none.return_value = None
    motor = MagicMock()
    motor.connect.return_value.__enter__.return_value = seguridad
    monkeypatch.setattr(cierre, "get_engine", Mock(return_value=motor))

    with pytest.raises(HTTPException) as error:
        cierre.Cierre().aplicar(
            conn,
            Objetivo("Cuenta", "501", "001"),
            {"motivo": "Solicitud del titular"},
            "asesor",
            15,
        )

    assert error.value.status_code == 409
    detalle = getattr(error.value, "detail", None)
    assert isinstance(detalle, dict)
    assert detalle["code"] == "APROBACION_NO_VALIDA"
    sql, parametros = seguridad.execute.call_args.args
    assert "AND IdAgencia=:agencia" in str(sql)
    assert "AND IdInternoResolutor IS NOT NULL" in str(sql)
    assert parametros == {
        "id": 15,
        "codigo": "CTA-CERRAR",
        "tipo": "Cuenta",
        "agencia": "001",
    }


def test_aplicacion_rechaza_contenido_invalido():
    with pytest.raises(HTTPException) as error:
        cierre.Cierre().aplicar(
            Mock(spec=Connection),
            Objetivo("Cuenta", "501", "001"),
            {"motivo": ""},
            "asesor",
            15,
        )

    assert error.value.status_code == 422


def test_aplicacion_ejecuta_cierre_solo_con_aprobador_acreditado(monkeypatch):
    conn = Mock(spec=Connection)
    seguridad = Mock()
    seguridad.execute.return_value.scalar_one_or_none.return_value = 88
    motor = MagicMock()
    motor.connect.return_value.__enter__.return_value = seguridad
    cerrar = Mock()
    monkeypatch.setattr(cierre, "get_engine", Mock(return_value=motor))
    monkeypatch.setattr(cierre, "cerrar", cerrar)

    cierre.Cierre().aplicar(
        conn,
        Objetivo("Cuenta", "501", "001"),
        {"motivo": "Solicitud del titular"},
        "asesor",
        15,
    )

    cerrar.assert_called_once_with(conn, 501, "001", 88, 15)


def test_cierre_revalidado_bloquea_si_aparece_un_impedimento(monkeypatch):
    conn = Mock(spec=Connection)
    lista = cierre.ListaCierre(
        id_cuenta=501,
        puede_cerrar=False,
        verificaciones=[
            cierre.VerificacionCierre(
                codigo="sinInteresDevengadoImpago",
                resultado="NoVerificable",
                detalle="Origen no disponible.",
            )
        ],
    )
    actualizar = Mock()
    monkeypatch.setattr(cierre, "_cuenta", Mock(return_value=_cuenta()))
    monkeypatch.setattr(cierre, "lista_cierre", Mock(return_value=lista))
    monkeypatch.setattr(cierre, "get_engine", Mock(return_value=object()))
    monkeypatch.setattr(cierre.repository, "actualizar_estado_cuenta", actualizar)

    with pytest.raises(HTTPException) as error:
        cierre.cerrar(conn, 501, "001", 88, 15)

    assert error.value.status_code == 409
    assert actualizar.call_count == 0
    assert conn.execute.call_count == 0


def test_certificado_repetible_usa_fecha_e_identificacion_del_cierre(monkeypatch):
    conn = Mock(spec=Connection)
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "NumeroCuenta": "00000501",
        "FechaCierre": date(2026, 11, 27),
        "Estado": "Cerrada",
        "Identificacion": "0912345678",
        "Nombres": "Ana",
        "Apellidos": "Pérez",
        "RazonSocial": None,
    }
    monkeypatch.setattr(cierre, "institucion_actual", Mock(return_value="Cooperativa"))

    documento = cierre.certificado_cierre(conn, 501, "001", "Asesor")

    assert documento.startswith(b"%PDF")
    sql, parametros = conn.execute.call_args.args
    assert "c.FechaCierre" in str(sql)
    assert parametros == {"id": 501, "agencia": "001"}


def test_certificado_no_disponible_antes_de_cierre():
    conn = Mock(spec=Connection)
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "NumeroCuenta": "00000501",
        "FechaCierre": None,
        "Estado": "Activa",
        "Identificacion": "0912345678",
        "Nombres": "Ana",
        "Apellidos": "Pérez",
        "RazonSocial": None,
    }

    with pytest.raises(HTTPException) as error:
        cierre.certificado_cierre(conn, 501, "001", "Asesor")

    assert error.value.status_code == 409
    detalle = getattr(error.value, "detail", None)
    assert isinstance(detalle, dict)
    assert detalle["code"] == "CIERRE_PENDIENTE"


def test_certificado_rechaza_cuenta_ajena_o_inexistente():
    conn = Mock(spec=Connection)
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = None

    with pytest.raises(HTTPException) as error:
        cierre.certificado_cierre(conn, 501, "002", "Asesor")

    assert error.value.status_code == 404


def test_certificado_usa_razon_social_y_fecha_hora_cerrada(monkeypatch):
    conn = Mock(spec=Connection)
    conn.execute.return_value.mappings.return_value.one_or_none.return_value = {
        "NumeroCuenta": "00000501",
        "FechaCierre": datetime(2026, 11, 27, 15, 30),
        "Estado": "Cerrada",
        "Identificacion": "SINTETICA-501",
        "Nombres": None,
        "Apellidos": None,
        "RazonSocial": "Titular de prueba",
    }
    monkeypatch.setattr(cierre, "institucion_actual", Mock(return_value="Cooperativa"))

    documento = cierre.certificado_cierre(conn, 501, "001", "Asesor")

    assert documento.startswith(b"%PDF")


def test_operacion_cta_cerrar_registrada_para_la_cola_y_openapi():
    operacion = registro_inicial().obtener("CTA-CERRAR", "Cuenta")
    assert operacion.base == "cooperativa"
    assert operacion.permiso_aprobacion == "cuentas:aprobar"
    assert operacion.evento_ejecucion == "CTA_CIERRE"
    assert operacion.solicitud_directa is False
    assert operacion.cancelable_por_solicitante is False

    paths = app.openapi()["paths"]
    assert paths["/api/v1/cuentas/{idCuenta}/cierre"]["get"]["operationId"] == (
        "CTACierreLista"
    )
    assert paths["/api/v1/cuentas/{idCuenta}/cierre"]["post"]["operationId"] == (
        "CTACierreSolicitar"
    )
    assert paths["/api/v1/cuentas/{idCuenta}/cierre"]["post"]["responses"]["202"]
    assert (
        paths["/api/v1/cuentas/{idCuenta}/certificado-cierre"]["get"]["operationId"]
        == "CTACertificadoCierre"
    )


def test_api_consulta_cierre_usa_agencia_y_custodia(monkeypatch):
    conn = Mock(spec=Connection)
    seguridad = Mock(spec=Engine)
    resultado = cierre.ListaCierre(id_cuenta=501, puede_cerrar=False, verificaciones=[])
    listar = Mock(return_value=resultado)
    monkeypatch.setattr(cierre, "lista_cierre", listar)

    respuesta = cierre_api.consultar_lista_cierre(
        501,
        usuario_con_roles("ASESOR"),
        conn,
        _cola(seguridad),
    )

    assert respuesta is resultado
    listar.assert_called_once_with(conn, 501, "001", seguridad=seguridad)


def test_api_solicitud_cierre_registra_contexto_y_objetivo(monkeypatch):
    usuario = usuario_con_roles("ASESOR")
    actor = Actor(
        "sujeto-prueba",
        "organizacion-prueba",
        "Usuario de prueba",
        88,
        ("ASESOR",),
        frozenset(),
        ("001",),
    )
    contexto = object()
    cola = _cola(Mock(spec=Engine))
    solicitar = Mock(return_value=15)
    monkeypatch.setattr(cola, "solicitar", solicitar)
    hoy = date(2026, 11, 27)
    monkeypatch.setattr(cierre_api, "hoy", Mock(return_value=hoy))
    monkeypatch.setattr(
        cierre_api.aprobaciones, "contexto", Mock(return_value=contexto)
    )

    respuesta = cierre_api.solicitar_cierre(
        501,
        cierre.SolicitarCierre(motivo="Solicitud del titular"),
        usuario,
        Mock(spec=Request),
        actor,
        cola,
    )

    assert respuesta.id_solicitud == 15
    solicitar.assert_called_once_with(
        actor,
        cierre.CODIGO,
        Objetivo("Cuenta", "501", "001"),
        {"motivo": "Solicitud del titular"},
        hoy,
        contexto,
    )


def test_api_certificado_devuelve_pdf_de_la_misma_agencia(monkeypatch):
    conn = Mock(spec=Connection)
    pdf = b"%PDF-1.4 synthetic"
    generar = Mock(return_value=pdf)
    monkeypatch.setattr(cierre, "certificado_cierre", generar)

    respuesta = cierre_api.descargar_certificado_cierre(
        501, usuario_con_roles("ASESOR"), conn
    )

    assert respuesta.status_code == 200
    assert respuesta.media_type == "application/pdf"
    assert respuesta.body == pdf
    generar.assert_called_once_with(conn, 501, "001", "Usuario de prueba")


def test_api_cierre_exige_agencia_activa():
    usuario = replace(usuario_con_roles("ASESOR"), id_agencia=None)

    with pytest.raises(HTTPException) as error:
        cierre_api.consultar_lista_cierre(
            501, usuario, Mock(spec=Connection), _cola(Mock(spec=Engine))
        )

    assert error.value.status_code == 403
