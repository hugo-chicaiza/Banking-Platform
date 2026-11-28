from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import Connection

from app.main import app
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.aprobaciones.registro import Objetivo
from app.modules.cuentas import cierre


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


def test_lista_cierre_nombra_todos_los_impedimentos_simultaneos(monkeypatch):
    cuenta = _cuenta(Saldo=Decimal("10.00"), SaldoRetenido=Decimal("1.00"))
    monkeypatch.setattr(cierre, "_cuenta", Mock(return_value=cuenta))
    monkeypatch.setattr(cierre, "_retenciones_activas", Mock(return_value=True))
    monkeypatch.setattr(cierre, "_tarjetas_vivas", Mock(return_value=True))
    monkeypatch.setattr(cierre, "_credito_vigente", Mock(return_value=True))
    monkeypatch.setattr(cierre, "_solicitudes_pendientes", Mock(return_value=True))

    resultado = cierre.lista_cierre(
        Mock(spec=Connection), 501, "001", seguridad=Mock()
    )

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
    assert set(parametros.values()) == {501, "Anulada", "Cancelada", "Cerrada", "Vencida"}


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
    assert error.value.detail["code"] == "CIERRE_INCOMPLETO"
    assert error.value.detail["bloqueos"] == [
        "saldoCero: Impide — Saldo pendiente.",
        "sinInteresDevengadoImpago: NoVerificable — Origen no disponible.",
    ]


def test_aplicacion_cierra_bajo_bloqueo_y_audita_al_aprobador(monkeypatch):
    conn = Mock(spec=Connection)
    monkeypatch.setattr(cierre, "_cuenta", Mock(return_value=_cuenta()))
    monkeypatch.setattr(cierre, "get_engine", Mock(return_value=Mock()))
    monkeypatch.setattr(
        cierre,
        "lista_cierre",
        Mock(
            return_value=cierre.ListaCierre(
                id_cuenta=501,
                puede_cerrar=True,
                verificaciones=[
                    cierre.VerificacionCierre(
                        codigo="saldoCero", resultado="Cumple", detalle="Cero."
                    )
                ],
            )
        ),
    )
    actualizar = Mock()
    monkeypatch.setattr(cierre.repository, "actualizar_estado_cuenta", actualizar)

    cierre.cerrar(conn, 501, "001", 88, 15)

    assert cierre._cuenta.call_args_list[0].kwargs == {"bloquear": True}
    assert cierre.lista_cierre.call_args.kwargs["bloquear"] is True
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
    assert error.value.detail["code"] == "APROBACION_NO_VALIDA"
    sql, parametros = seguridad.execute.call_args.args
    assert "AND IdAgencia=:agencia" in str(sql)
    assert "AND IdInternoResolutor IS NOT NULL" in str(sql)
    assert parametros == {
        "id": 15,
        "codigo": "CTA-CERRAR",
        "tipo": "Cuenta",
        "agencia": "001",
    }


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
    assert error.value.detail["code"] == "CIERRE_PENDIENTE"


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
    assert paths[
        "/api/v1/cuentas/{idCuenta}/certificado-cierre"
    ]["get"]["operationId"] == "CTACertificadoCierre"
