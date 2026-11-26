from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import HTTPException

from app.modules.aprobaciones import lecturas
from app.modules.aprobaciones.identidad import Actor
from app.modules.contabilidad import repository
from app.modules.contabilidad.plantillas import (
    OPERACION_PLANTILLA,
    Linea,
    Simulacion,
    simular,
    validar_lineas,
)


def test_solicitud_version_reutiliza_estado_y_acciones_de_e008():
    cola = MagicMock()
    cola.registro.obtener.return_value = OPERACION_PLANTILLA
    consulta = cola.seguridad.connect.return_value.__enter__.return_value.execute
    fila = consulta.return_value.mappings.return_value
    fila.first.return_value = {
        "IdSolicitud": 23,
        "IdObjetivo": "17",
        "TipoObjetivo": "PlantillaAsiento",
        "CodigoTransaccion": "CON-PLANTILLA",
        "IdAgencia": None,
        "Estado": "Pendiente",
        "FechaSolicitud": datetime(2026, 11, 20),
        "SolicitadoPor": "user_creador",
        "NombreSolicitante": "Contador",
        "IdInternoSolicitante": 101,
        "ResueltoPor": None,
        "FechaResolucion": None,
        "Comentario": None,
        "CodigoError": None,
    }
    creador = Actor("user_creador", "org_1", None, 101, ("CONTADOR",), frozenset(), ())
    propia = lecturas.solicitud_global_por_objetivo(
        cola, creador, OPERACION_PLANTILLA, "17"
    )
    assert propia and propia.puede_cancelar and not propia.puede_aprobar
    revisor = replace(
        creador, sujeto="user_revisor", permisos=frozenset({"con-plantilla-aprobar"})
    )
    ajena = lecturas.solicitud_global_por_objetivo(
        cola, revisor, OPERACION_PLANTILLA, "17"
    )
    assert (
        ajena
        and ajena.puede_aprobar
        and ajena.puede_rechazar
        and not ajena.puede_cancelar
    )
    assert consulta.call_args.args[1] == {
        "org": "org_1",
        "codigo": "CON-PLANTILLA",
        "tipo": "PlantillaAsiento",
        "objetivo": "17",
        "agencia": None,
        "actor": "user_revisor",
        "puede_revisar": 1,
    }
    for estado in ("Aprobada", "Ejecutada", "Rechazada"):
        fila.first.return_value["Estado"] = estado
        resuelta = lecturas.solicitud_global_por_objetivo(
            cola, revisor, OPERACION_PLANTILLA, "17"
        )
        assert resuelta and resuelta.estado == estado
        assert not (
            resuelta.puede_aprobar or resuelta.puede_rechazar or resuelta.puede_cancelar
        )
    fila.first.return_value = None
    sin_acceso = replace(revisor, permisos=frozenset())
    assert (
        lecturas.solicitud_global_por_objetivo(
            cola, sin_acceso, OPERACION_PLANTILLA, "17"
        )
        is None
    )
    assert consulta.call_args.args[1]["puede_revisar"] == 0


def test_rechaza_descuadre_por_base():
    lineas = [
        Linea(lado="DEBITO", origen="FIJA", cuenta=1, base="PRINCIPAL"),
        Linea(lado="CREDITO", origen="FIJA", cuenta=2, base="COMISION"),
    ]
    with pytest.raises(HTTPException) as error:
        validar_lineas(Mock(), lineas)
    assert isinstance(error.value.detail, dict)
    assert error.value.detail.get("code") == "PLANTILLA_NO_CUADRA"


def test_simulacion_comparte_resolvedor_sin_escrituras(monkeypatch):
    conn = Mock()
    monkeypatch.setattr(
        repository,
        "cuenta_para_plantilla",
        Mock(
            return_value={
                "Estado": True,
                "EsImputable": True,
                "CodigoCuenta": "11010510",
            }
        ),
    )
    datos = Simulacion(
        lineas=[
            Linea(lado="DEBITO", origen="FIJA", cuenta=1, base="PRINCIPAL"),
            Linea(lado="CREDITO", origen="FIJA", cuenta=2, base="PRINCIPAL"),
        ],
        montos={"PRINCIPAL": Decimal("100.00")},
    )
    resultado = simular(conn, datos)
    assert resultado["total"] == Decimal(100)
    assert len(resultado["lineas"]) == 2
    conn.execute.assert_not_called()


def test_simulacion_resuelve_comision_sin_rol_y_sin_escrituras(monkeypatch):
    conn = Mock()
    monkeypatch.setattr(
        repository,
        "cuenta_para_plantilla",
        Mock(
            return_value={
                "Estado": True,
                "EsImputable": True,
                "CodigoCuenta": "11010510",
            }
        ),
    )
    datos = Simulacion(
        lineas=[
            Linea(lado="DEBITO", origen="PRODUCTO", rol="CAPITAL", base="COMISION"),
            Linea(lado="CREDITO", origen="COMISION", base="COMISION"),
        ],
        producto={"CAPITAL": 1},
        comision=2,
        montos={"COMISION": Decimal("2.50")},
    )
    resultado = simular(conn, datos)
    assert resultado["total"] == Decimal("2.50")
    assert [linea["cuenta"] for linea in resultado["lineas"]] == [1, 2]
    assert conn.execute.call_count == 1
    assert str(conn.execute.call_args.args[0]).lstrip().upper().startswith("SELECT")
