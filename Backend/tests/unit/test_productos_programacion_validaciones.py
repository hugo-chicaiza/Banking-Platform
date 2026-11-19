"""Reglas de entrada y aislamiento E3-03; complementan las pruebas SQL reales."""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Connection

from app.modules.aprobaciones.registro import Objetivo
from app.modules.productos import programacion as p
from app.modules.productos.programacion_schemas import (
    Cambio,
    CondicionNueva,
    CuposNuevos,
)

HOY = date(2026, 11, 19)


def codigo(error: HTTPException) -> str:
    detalle = error.detail
    assert isinstance(detalle, dict)
    return str(dict(detalle)["code"])


def conexion(fila):
    conn = MagicMock(spec=Connection)
    conn.execute.return_value.mappings.return_value.first.return_value = fila
    return conn


@pytest.mark.parametrize(
    "objetivo",
    [
        Objetivo("Producto", "1", None),
        Objetivo("SubProducto", "1", "001"),
        Objetivo("SubProducto", "-1", None),
        Objetivo("SubProducto", "0", None),
        Objetivo("SubProducto", "2147483648", None),
        Objetivo("SubProducto", "١", None),
        Objetivo("SubProducto", "1;DELETE", None),
    ],
)
def test_objetivo_debe_ser_modelo_institucional_con_identificador_valido(objetivo):
    with pytest.raises(HTTPException) as error:
        p.id_subproducto(objetivo)
    assert error.value.status_code == 422
    assert codigo(error.value) == "OBJETIVO_INVALIDO"


def test_identificador_valido_y_nombres_sql_no_controlados_por_el_cliente():
    assert p.id_subproducto(Objetivo("SubProducto", "2147483647", None)) == 2147483647
    with pytest.raises(HTTPException) as error:
        p.sentencia("condiciones; DROP TABLE", "SELECT * FROM {tabla}")
    assert codigo(error.value) == "CLASE_INVALIDA"


def test_retirado_permite_consulta_pero_impide_solicitar_cambios():
    conn = conexion({"EstadoSubProducto": "Retirado"})
    with pytest.raises(HTTPException) as error:
        p.subproducto(conn, 1)
    assert error.value.status_code == 409 and codigo(error.value) == "PRODUCTO_RETIRADO"
    assert (
        p.subproducto(conn, 1, permitir_retirado=True)["EstadoSubProducto"]
        == "Retirado"
    )
    assert all(
        str(llamada.args[0]).startswith("SELECT")
        for llamada in conn.execute.call_args_list
    )


def test_modelo_inexistente_no_crea_datos():
    conn = conexion(None)
    with pytest.raises(HTTPException) as error:
        p.subproducto(conn, 1)
    assert error.value.status_code == 404
    assert conn.execute.call_count == 1


@pytest.mark.parametrize(
    "tipo,clase",
    [("Credito", "cupos"), ("Credito", "restricciones"), ("Tarjeta", "restricciones")],
)
def test_configuracion_debe_corresponder_al_tipo_de_producto(tipo, clase):
    conn = conexion({"EstadoSubProducto": "Activo", "TipoProducto": tipo})
    with pytest.raises(HTTPException) as error:
        p.Programador().preparar(
            conn,
            Objetivo("SubProducto", "1", None),
            {"clase": clase, "accion": "programar", "datos": {}},
            HOY,
        )
    assert codigo(error.value) == "TIPO_PRODUCTO_INVALIDO"
    assert conn.execute.call_count == 1


def test_preimagen_o_aprobacion_no_se_aceptan_desde_el_cliente():
    conn = conexion({"EstadoSubProducto": "Borrador"})
    with pytest.raises(HTTPException) as error:
        p.Programador().preparar(
            conn,
            Objetivo("SubProducto", "1", None),
            {
                "clase": "condiciones",
                "accion": "programar",
                "_previos": [],
                "aprobado": True,
            },
            HOY,
        )
    assert codigo(error.value) == "CONTENIDO_INVALIDO"


@pytest.mark.parametrize(
    "cambios",
    [
        {"saldoMinimo": "51"},
        {"tasaInteresAnual": "100.0001"},
        {"montoAperturaMinimo": "1.001"},
        {"mesesInactividad": True},
    ],
)
def test_condiciones_invalidas_se_rechazan_antes_de_consultar_o_modificar(cambios):
    conn = MagicMock(spec=Connection)
    cambio = Cambio(
        clase="condiciones",
        accion="programar",
        datos={
            "montoAperturaMinimo": "50",
            "saldoMinimo": "10",
            "vigenciaDesde": HOY.isoformat(),
            **cambios,
        },
    )
    with pytest.raises(HTTPException) as error:
        p.Programador()._programar(conn, cambio, [], HOY)
    assert codigo(error.value) == "CONTENIDO_INVALIDO"
    conn.execute.assert_not_called()


def test_fecha_pasada_no_crea_programacion():
    conn = MagicMock(spec=Connection)
    cambio = Cambio(
        clase="condiciones",
        accion="programar",
        datos={
            "montoAperturaMinimo": "50",
            "saldoMinimo": "10",
            "vigenciaDesde": (HOY - timedelta(days=1)).isoformat(),
        },
    )
    with pytest.raises(HTTPException) as error:
        p.Programador()._programar(conn, cambio, [], HOY)
    assert codigo(error.value) == "VIGENCIA_PASADA"
    conn.execute.assert_not_called()


def test_fechas_invertidas_y_canales_duplicados_no_son_validos():
    with pytest.raises(ValidationError):
        CondicionNueva.model_validate(
            {
                "montoAperturaMinimo": "50",
                "saldoMinimo": "10",
                "vigenciaDesde": "2026-12-02",
                "vigenciaHasta": "2026-12-01",
            }
        )
    canal = {
        "idCanal": 1,
        "cupoDiarioMaximo": "100",
        "cupoMensualMaximo": "1000",
        "montoMaxTransaccion": "50",
        "maxTransaccionesDia": 10,
    }
    with pytest.raises(ValidationError):
        CuposNuevos.model_validate({"vigenciaDesde": HOY, "cupos": [canal, canal]})


def test_cancelacion_sin_trazabilidad_no_asume_una_vigencia_anterior():
    with pytest.raises(HTTPException) as error:
        p.Programador().origen(None, 1)
    assert codigo(error.value) == "PROGRAMACION_SIN_TRAZABILIDAD"


@pytest.mark.parametrize(
    "clase,codigo_evento",
    [
        ("condiciones", "PRD_CONDICION_PROGRAMADA"),
        ("cupos", "PRD_CUPO_PROGRAMADO"),
        ("restricciones", "PRD_RESTRICCION_PROGRAMADA"),
    ],
)
def test_eventos_del_contrato_y_permiso_de_solicitud_no_delegable(clase, codigo_evento):
    assert p.evento({"clase": clase, "accion": "programar"}) == codigo_evento
    assert (
        p.evento({"clase": clase, "accion": "cancelar"}) == "PRD_PROGRAMACION_CANCELADA"
    )
    operacion = p.operacion()
    assert operacion.permiso_ejecucion == "prd-condicion"
    assert operacion.permiso_aprobacion == "productos:aprobar"
    assert operacion.solicitud_directa is False
