from datetime import date, datetime
from decimal import Decimal
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import Connection

from app.core.security.auth import normalizar_roles, require_permiso
from app.main import app
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.manejadores import registro_inicial
from app.modules.aprobaciones.registro import Objetivo
from app.modules.aprobaciones.servicio import Servicio
from app.modules.cuentas import cambio_subproducto as cambio
from app.modules.cuentas import retenciones as r
from tests.sesion import usuario_con_roles


@pytest.mark.parametrize("fase", ["preparar", "aplicar"])
@pytest.mark.parametrize("saldo_retenido", [0, 60])
def test_cambio_subproducto_bloquea_una_retencion_activa(
    monkeypatch, fase, saldo_retenido
):
    objetivo = Objetivo("Cuenta", "8", "001")
    datos = {"idSubProducto": 5, "realizadoPor": 1}
    conn = Mock(spec=Connection)
    conn.exec_driver_sql.return_value.scalar.return_value = 4
    conn.execute.return_value.scalar.return_value = 1
    actual = Mock(
        return_value={"IdCuenta": 8, "SaldoRetenido": Decimal(saldo_retenido)}
    )
    validar_destino = Mock()
    monkeypatch.setattr(cambio, "_actual", actual)
    monkeypatch.setattr(cambio, "_validar", validar_destino)
    manejador = cambio.CambioSubproducto()

    with pytest.raises(HTTPException) as error:
        if fase == "preparar":
            manejador.preparar(conn, objetivo, datos, date(2026, 11, 25))
        else:
            manejador.aplicar(conn, objetivo, datos, "solicitante", 3)

    assert error.value.status_code == 409
    assert isinstance(error.value.detail, dict)
    assert cast(dict[str, object], error.value.detail)["code"] == (
        "CUENTA_CON_RETENCIONES_ACTIVAS"
    )
    actual.assert_called_once_with(conn, objetivo, bloquear=True)
    validar_destino.assert_not_called()
    if saldo_retenido == 0:
        assert "Estado='Activa'" in str(conn.execute.call_args.args[0])
    else:
        conn.execute.assert_not_called()


def test_liberar_la_retencion_habilita_una_solicitud_nueva(monkeypatch):
    conn = Mock(spec=Connection)
    conn.exec_driver_sql.return_value.scalar.return_value = 4
    conn.execute.return_value.scalar.return_value = None
    monkeypatch.setattr(
        cambio,
        "_actual",
        Mock(
            return_value={
                "IdCuenta": 8,
                "SaldoRetenido": Decimal(0),
                "IdSubProducto": 4,
            }
        ),
    )
    monkeypatch.setattr(cambio, "_validar", Mock(return_value=1))
    plan = cambio.CambioSubproducto().preparar(
        conn,
        Objetivo("Cuenta", "8", "001"),
        {"idSubProducto": 5, "realizadoPor": 1},
        date(2026, 11, 25),
    )
    assert plan.version == "4"


@pytest.mark.parametrize("falla_contable", [False, True])
def test_cambio_tras_liberacion_reclasifica_el_saldo_completo_o_falla_sin_cambiar_cuenta(
    monkeypatch, falla_contable
):
    conn = Mock(spec=Connection)
    conn.exec_driver_sql.return_value.scalar.return_value = 4
    cuenta = {
        "IdCuenta": 8,
        "IdCliente": 22,
        "IdSubProducto": 4,
        "IdTipoProducto": 1,
        "IdAgencia": "001",
        "Estado": "Activa",
        "Saldo": Decimal(125),
        "SaldoRetenido": Decimal(0),
        "FechaNacimiento": date(2008, 1, 1),
    }
    fila = Mock()
    fila.mappings.return_value.one_or_none.return_value = cuenta
    retencion = Mock()
    retencion.scalar.return_value = None
    destino = Mock()
    destino.mappings.return_value.one_or_none.return_value = {
        "IdProducto": 6,
        "IdTipoProducto": 1,
    }
    conn.execute.side_effect = [fila, retencion, destino, None, None]
    monkeypatch.setattr(cambio, "obtener_titular_cuenta", Mock(return_value=22))
    monkeypatch.setattr(
        cambio.clientes, "bloquear_cliente", Mock(return_value={"estado": "Activo"})
    )
    bloquear = Mock()
    monkeypatch.setattr(cambio, "bloquear_cuenta", bloquear)
    monkeypatch.setattr(
        cambio, "ahora_ecuador", Mock(return_value=datetime(2026, 11, 25, 10))
    )
    monkeypatch.setattr(cambio, "edad_mayoria", Mock(return_value=18))
    monkeypatch.setattr(cambio, "cliente_elegible", Mock(return_value=(True, [])))
    monkeypatch.setattr(cambio, "cuenta_contable", Mock(side_effect=[2001, 2002]))
    monkeypatch.setattr(
        cambio, "resolver_id_fecha_contable", Mock(return_value=20261125)
    )
    asiento = Mock(
        return_value=45,
        side_effect=cambio.ErrorContable("Período cerrado") if falla_contable else None,
    )
    monkeypatch.setattr(cambio, "generar_asiento", asiento)

    objetivo = Objetivo("Cuenta", "8", "001")
    datos = {"idSubProducto": 5, "realizadoPor": 1}
    manejador = cambio.CambioSubproducto()
    if falla_contable:
        with pytest.raises(HTTPException) as error:
            manejador.aplicar(conn, objetivo, datos, "solicitante", 3)
        assert error.value.status_code == 503
    else:
        manejador.aplicar(conn, objetivo, datos, "solicitante", 3)

    bloquear.assert_called_once_with(conn, 8)
    operacion = asiento.call_args.args[1]
    assert operacion.codigo_plantilla == "CUENTAS_RECLASIFICACION"
    assert operacion.clave_evento == "CTA-SUBPRODUCTO:3"
    assert operacion.importes == {"PRINCIPAL": Decimal(125), "RETENIDO": Decimal(0)}
    assert operacion.cuentas_por_rol == {
        ("PRODUCTO", "CAPITAL"): 2001,
        ("CONTRAPRODUCTO", "CAPITAL"): 2002,
    }
    consultas = [str(llamada.args[0]) for llamada in conn.execute.call_args_list]
    assert "UPDATE Cuentas.CuentaAutorizado" in consultas[3]
    if falla_contable:
        assert len(consultas) == 4
    else:
        assert "INSERT Cuentas.CuentaEvento" in consultas[4]
        parametros = conn.execute.call_args.args[1]
        assert (
            parametros["producto"],
            parametros["destino"],
            parametros["cuenta"],
        ) == (6, 5, 8)
        assert "Asiento 45." in parametros["detalle"]
    conn.commit.assert_not_called()


def test_liberacion_cta_reintenta_sin_duplicar_asiento_y_respeta_modulo(monkeypatch):
    conn = Mock(spec=Connection)
    cuenta = {"IdCuenta": 8, "SaldoRetenido": Decimal(60)}
    retencion = {
        "Origen": "Modulo",
        "ModuloOrigen": "Creditos",
        "Estado": "Activa",
        "ClaveLiberacion": None,
        "IdAsiento": 10,
        "IdRetencion": 9,
        "IdSubProductoOrigen": 4,
        "Monto": Decimal(60),
    }
    contabilizar = Mock(return_value=11)
    monkeypatch.setattr(r, "_contabilizar", contabilizar)
    with pytest.raises(HTTPException) as error:
        r.liberar_retencion(
            conn, cuenta, retencion, 1, "Garantía resuelta", clave="QA-9"
        )
    assert error.value.status_code == 409
    conn.execute.assert_not_called()

    assert (
        r.liberar_retencion(
            conn,
            cuenta,
            retencion,
            1,
            "Garantía resuelta",
            clave="QA-9",
            modulo="Creditos",
            solicitud=3,
        )
        == 11
    )
    contabilizar.assert_called_once_with(
        conn,
        cuenta,
        1,
        "QA-9",
        Decimal(60),
        alta=False,
        asiento_original=10,
        subproducto_origen=4,
    )
    sql, parametros = conn.execute.call_args.args
    assert "SaldoRetenido=SaldoRetenido-:monto" in str(sql)
    assert (parametros["estado"], parametros["asiento"], parametros["monto"]) == (
        "Liberada",
        11,
        Decimal(60),
    )

    liberada = {
        **retencion,
        "Estado": "Liberada",
        "ClaveLiberacion": "QA-9",
        "IdSolicitudLiberacion": 3,
        "MotivoLiberacion": "Garantía resuelta",
        "IdAsientoLiberacion": 11,
    }
    assert (
        r.liberar_retencion(
            conn,
            {**cuenta, "SaldoRetenido": Decimal(0)},
            liberada,
            1,
            "Garantía resuelta",
            clave="QA-9",
            modulo="Creditos",
            solicitud=3,
        )
        == 11
    )
    assert contabilizar.call_count == conn.execute.call_count == 1


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
