"""Reglas de entrada y aislamiento E3-03; complementan las pruebas SQL reales."""

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Connection

from app.modules.aprobaciones.congelacion import congelar
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


@pytest.fixture
def programador(monkeypatch):
    sub = {
        "EstadoSubProducto": "Activo",
        "TipoProducto": "Cuenta",
        "NombreSubProducto": "Ahorro Flexible",
        "NombreProducto": "Ahorro Familiar",
    }
    monkeypatch.setattr(p, "subproducto", lambda *args, **kwargs: dict(sub))
    monkeypatch.setattr(p, "filas", lambda *args: [])
    monkeypatch.setattr(p, "hoy", lambda: HOY)
    seguridad = MagicMock()
    seg = seguridad.connect.return_value.__enter__.return_value
    seg.execute.return_value.mappings.return_value.all.return_value = []
    seg.execute.return_value.scalar_one.return_value = 12
    return p.Programador(seguridad, "organizacion-qa"), seg


def datos_programables(clase, desde=HOY) -> dict[str, Any]:
    comunes = {"vigenciaDesde": desde.isoformat()}
    if clase == "condiciones":
        return {**comunes, "montoAperturaMinimo": "50", "saldoMinimo": "10"}
    if clase == "cupos":
        return {
            **comunes,
            "cupos": [
                {
                    "idCanal": 1,
                    "cupoDiarioMaximo": "100",
                    "cupoMensualMaximo": "1000",
                    "montoMaxTransaccion": "50",
                    "maxTransaccionesDia": 10,
                }
            ],
        }
    return {
        **comunes,
        "tipoRestriccion": "SALDO_MINIMO",
        "monto": "10",
        "descripcion": "Conservar reserva minima",
    }


def conexion_catalogos():
    conn = MagicMock(spec=Connection)
    conn.execute.return_value.scalars.return_value = [1]
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "UsaDias": False,
        "UsaMonto": True,
        "UsaCantidad": False,
    }
    return conn


@pytest.mark.parametrize("clase", ["condiciones", "cupos", "restricciones"])
def test_preparacion_congela_nombres_version_y_propuesta_sin_escribir(
    programador, clase
):
    manejador, _ = programador
    conn = conexion_catalogos()
    objetivo = Objetivo("SubProducto", "1", None)
    cambio = {"clase": clase, "accion": "programar", "datos": datos_programables(clase)}
    plan = manejador.preparar(conn, objetivo, cambio, HOY)
    assert plan.antes["registros"] == []
    assert plan.despues["subproducto"]["nombre"] == "Ahorro Flexible"
    assert plan.contenido["_previos"] == [] and len(plan.version) == 64
    assert plan.version == manejador.version(conn, objetivo)
    assert all(
        str(llamada.args[0]).startswith("SELECT")
        for llamada in conn.execute.call_args_list
    )


def test_programar_rechaza_canal_inactivo_y_cupos_incoherentes(programador):
    manejador, _ = programador
    conn = conexion_catalogos()
    datos = datos_programables("cupos")
    cambio = Cambio(clase="cupos", accion="programar", datos=datos)
    conn.execute.return_value.scalars.return_value = []
    with pytest.raises(HTTPException) as error:
        manejador._programar(conn, cambio, [], HOY)
    assert codigo(error.value) == "CANAL_NO_EXISTE"
    datos["cupos"][0]["montoMaxTransaccion"] = "101"
    with pytest.raises(HTTPException) as error:
        manejador._programar(
            conn, Cambio(clase="cupos", accion="programar", datos=datos), [], HOY
        )
    assert codigo(error.value) == "CUPOS_INCOHERENTES"


@pytest.mark.parametrize(
    "tipo", [None, {"UsaDias": True, "UsaMonto": False, "UsaCantidad": False}]
)
def test_restriccion_debe_respetar_catalogo_tipado(programador, tipo):
    manejador, _ = programador
    conn = conexion_catalogos()
    conn.execute.return_value.mappings.return_value.first.return_value = tipo
    with pytest.raises(HTTPException) as error:
        manejador._programar(
            conn,
            Cambio(
                clase="restricciones",
                accion="programar",
                datos=datos_programables("restricciones"),
            ),
            [],
            HOY,
        )
    assert codigo(error.value) == "RESTRICCION_INVALIDA"


def test_sucesor_congela_solo_antecesores_que_intersectan(programador):
    manejador, _ = programador
    inicio = HOY + timedelta(days=5)
    anterior = {
        "IdCondicion": 1,
        "Estado": "Vigente",
        "VigenciaDesde": HOY - timedelta(days=4),
        "VigenciaHasta": None,
    }
    otros = [
        {**anterior, "IdCondicion": 2, "Estado": "Cancelada"},
        {**anterior, "IdCondicion": 3, "VigenciaHasta": HOY - timedelta(days=1)},
        {**anterior, "IdCondicion": 4, "VigenciaDesde": inicio + timedelta(days=20)},
    ]
    datos = {
        **datos_programables("condiciones", inicio),
        "vigenciaHasta": (inicio + timedelta(days=10)).isoformat(),
    }
    cambio = Cambio(clase="condiciones", accion="programar", datos=datos)
    plan = manejador._programar(conexion_catalogos(), cambio, [anterior, *otros], HOY)
    assert [f["IdCondicion"] for f in plan["_previos"]] == [1]
    with pytest.raises(HTTPException) as error:
        manejador._programar(
            conexion_catalogos(), cambio, [{**anterior, "VigenciaDesde": inicio}], HOY
        )
    assert codigo(error.value) == "VIGENCIA_SOLAPADA"


def test_origen_verifica_hash_y_rechaza_solicitud_ajena_o_alterada(programador):
    manejador, seg = programador
    congelado = congelar({"cambio": {"clase": "condiciones", "accion": "programar"}})
    resultado = seg.execute.return_value.mappings.return_value
    resultado.first.return_value = {
        "Contenido": congelado.texto,
        "HashContenido": congelado.huella,
    }
    assert manejador.origen(5, 1)["clase"] == "condiciones"
    resultado.first.return_value = None
    with pytest.raises(HTTPException) as error:
        manejador.origen(5, 1)
    assert codigo(error.value) == "PROGRAMACION_SIN_TRAZABILIDAD"
    resultado.first.return_value = {
        "Contenido": congelado.texto + " ",
        "HashContenido": congelado.huella,
    }
    with pytest.raises(HTTPException) as error:
        manejador.origen(5, 1)
    assert codigo(error.value) == "CONTENIDO_ALTERADO"


def test_cancelar_preserva_fin_original_y_no_invade_sucesor(programador, monkeypatch):
    manejador, _ = programador
    anterior = {
        "IdCondicion": 1,
        "Estado": "Vigente",
        "VigenciaDesde": HOY - timedelta(days=5),
        "VigenciaHasta": HOY + timedelta(days=20),
        "IdSolicitud": 1,
    }
    futuro = {
        **anterior,
        "IdCondicion": 2,
        "VigenciaDesde": HOY + timedelta(days=5),
        "IdSolicitud": 2,
    }
    posterior = {
        **anterior,
        "IdCondicion": 3,
        "VigenciaDesde": HOY + timedelta(days=10),
        "IdSolicitud": 3,
    }
    original = {
        "clase": "condiciones",
        "accion": "programar",
        "datos": {"vigenciaDesde": futuro["VigenciaDesde"].isoformat()},
        "_previos": [anterior, anterior],
    }
    monkeypatch.setattr(manejador, "origen", lambda *args: original)
    cambio = Cambio(clase="condiciones", accion="cancelar", id_registro=2)
    plan = manejador._cancelar(cambio, [anterior, futuro, posterior], 1, HOY)
    assert plan["ids"] == [2] and plan["idOrigen"] == 2
    assert plan["_restaurar"] == [
        {"id": 1, "estado": "Vigente", "hasta": (HOY + timedelta(days=9)).isoformat()}
    ]


@pytest.mark.parametrize(
    "escenario,esperado",
    [
        ("inexistente", "CONJUNTO_NO_ENCONTRADO"),
        ("vigente", "CONJUNTO_YA_VIGENTE"),
        ("cancelado", "CONJUNTO_CANCELADO"),
        ("clase", "PROGRAMACION_NO_CANCELABLE"),
        ("traza", "TRAZABILIDAD_INVALIDA"),
    ],
)
def test_cancelacion_rechaza_estados_no_cancelables(
    programador, monkeypatch, escenario, esperado
):
    manejador, _ = programador
    fila = {
        "IdCondicion": 2,
        "Estado": "Cancelada" if escenario == "cancelado" else "Programada",
        "VigenciaDesde": HOY + timedelta(days=5),
        "VigenciaHasta": None,
        "IdSolicitud": 2,
    }
    original = {
        "clase": "cupos" if escenario == "clase" else "condiciones",
        "accion": "programar",
        "datos": {
            "vigenciaDesde": (
                HOY if escenario == "vigente" else HOY + timedelta(days=5)
            ).isoformat()
        },
        "_previos": [{"IdCondicion": 99}] if escenario == "traza" else [],
    }
    monkeypatch.setattr(manejador, "origen", lambda *args: original)
    with pytest.raises(HTTPException) as error:
        manejador._cancelar(
            Cambio(clase="condiciones", accion="cancelar", id_registro=2),
            [] if escenario == "inexistente" else [fila],
            1,
            HOY,
        )
    assert codigo(error.value) == esperado


def test_cancelacion_vacia_se_detecta_por_historial_con_hash(programador, monkeypatch):
    manejador, seg = programador
    monkeypatch.setattr(
        manejador,
        "origen",
        lambda *args: {
            "clase": "cupos",
            "accion": "programar",
            "datos": {"vigenciaDesde": (HOY + timedelta(days=5)).isoformat()},
            "_previos": [],
        },
    )
    cambio = Cambio(clase="cupos", accion="cancelar", id_programacion=2)
    assert manejador._cancelar(cambio, [], 1, HOY)["ids"] == []
    congelado = congelar(
        {"cambio": {"clase": "cupos", "accion": "cancelar", "idOrigen": 2}}
    )
    seg.execute.return_value.mappings.return_value.all.return_value = [
        {"Contenido": congelado.texto, "HashContenido": congelado.huella}
    ]
    with pytest.raises(HTTPException) as error:
        manejador._cancelar(cambio, [], 1, HOY)
    assert codigo(error.value) == "CONJUNTO_CANCELADO"


@pytest.mark.parametrize(
    "dias,esperado", [(5, None), (-1, "VIGENCIA_PASADA"), (20, "VIGENCIA_INVALIDA")]
)
def test_finalizar_restriccion_no_reescribe_historia_ni_extiende_intervalo(
    programador, dias, esperado
):
    manejador, _ = programador
    fila = {
        "IdRestriccion": 1,
        "Estado": "A",
        "VigenciaDesde": HOY,
        "VigenciaHasta": HOY + timedelta(days=10),
    }
    cambio = Cambio(
        clase="restricciones",
        accion="fin",
        id_registro=1,
        datos={"vigenciaHasta": (HOY + timedelta(days=dias)).isoformat()},
    )
    if esperado:
        with pytest.raises(HTTPException) as error:
            manejador._fin(cambio, [fila], HOY)
        assert codigo(error.value) == esperado
    else:
        assert (
            manejador._fin(cambio, [fila], HOY)["hasta"]
            == (HOY + timedelta(days=dias)).isoformat()
        )


@pytest.mark.parametrize("accion", ["fin", "cancelar"])
def test_aprobacion_tardia_rechazada_sin_escritura(programador, accion):
    manejador, _ = programador
    conn = conexion_catalogos()
    contenido = {
        "clase": "restricciones",
        "accion": accion,
        "hasta": (HOY - timedelta(days=1)).isoformat(),
        "inicio": HOY.isoformat(),
    }
    with pytest.raises(HTTPException) as error:
        manejador.aplicar(
            conn, Objetivo("SubProducto", "1", None), contenido, "solicitante-qa", 2
        )
    assert error.value.status_code == 409
    conn.execute.assert_not_called()


@pytest.mark.parametrize("clase", ["condiciones", "cupos", "restricciones"])
def test_aplicar_usa_actor_resuelto_y_no_datos_del_cliente(programador, clase):
    manejador, _ = programador
    conn = conexion_catalogos()
    llave, estado = p.TABLAS[clase][1:3]
    previos = [
        {
            llave: 1,
            estado: "Vigente" if clase == "condiciones" else "A",
            "VigenciaDesde": HOY - timedelta(days=2),
        },
        {
            llave: 2,
            estado: "Vigente" if clase == "condiciones" else "A",
            "VigenciaDesde": HOY,
        },
    ]
    contenido = {
        "clase": clase,
        "accion": "programar",
        "datos": datos_programables(clase),
        "_previos": previos,
    }
    manejador.aplicar(
        conn, Objetivo("SubProducto", "1", None), contenido, "solicitante-qa", 27
    )
    escrituras = [
        c
        for c in conn.execute.call_args_list
        if str(c.args[0]).startswith(("INSERT", "UPDATE"))
    ]
    assert len(escrituras) == 3
    parametros = escrituras[-1].args[1]
    assert parametros["solicitud"] == 27 and parametros["sub"] == 1
    if clase != "cupos":
        assert parametros["actor"] == 12
    assert escrituras[0].args[1]["hasta"] == HOY - timedelta(days=1)
    assert escrituras[1].args[1]["estado"] == (
        "Reemplazada" if clase == "condiciones" else "I"
    )


def test_aplicar_cancelacion_y_finalizacion_solo_en_objetivo(programador):
    manejador, _ = programador
    conn = conexion_catalogos()
    objetivo = Objetivo("SubProducto", "1", None)
    manejador.aplicar(
        conn,
        objetivo,
        {"clase": "restricciones", "accion": "fin", "hasta": HOY.isoformat(), "id": 3},
        "qa",
        2,
    )
    assert conn.execute.call_args.args[1] == {"hasta": HOY, "id": 3, "sub": 1}
    conn.reset_mock()
    manejador.aplicar(
        conn,
        objetivo,
        {
            "clase": "condiciones",
            "accion": "cancelar",
            "inicio": (HOY + timedelta(days=1)).isoformat(),
            "ids": [3],
            "_restaurar": [{"id": 1, "estado": "Vigente", "hasta": None}],
        },
        "qa",
        2,
    )
    assert conn.execute.call_args_list[0].args[1] == {
        "estado": "Cancelada",
        "id": 3,
        "sub": 1,
    }
    assert conn.execute.call_args_list[1].args[1] == {
        "estado": "Vigente",
        "hasta": None,
        "id": 1,
        "sub": 1,
    }
