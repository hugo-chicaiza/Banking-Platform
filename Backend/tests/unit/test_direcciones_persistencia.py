"""Vínculos, auditoría y escrituras parciales del repositorio SQL de direcciones.

El cursor controlado prueba el contrato con el driver, no pretende ejecutar T-SQL.
El ensayo SQL LocalDB comprueba por separado la persistencia y las restricciones.
"""

import json
from typing import cast
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Connection

from app.modules.clientes import repository, service
from app.modules.clientes.schemas import ClienteCreate


def cursor(*filas):
    conexion = MagicMock(spec=Connection)
    resultados = []
    for fila in filas:
        resultado = MagicMock()
        resultado.mappings.return_value = [] if fila is None else [fila]
        resultados.append(resultado)
    conexion.execute.side_effect = resultados
    return conexion


def payload():
    return ClienteCreate.model_validate(
        {
            "identificacion": "0100000025",
            "tipoDocumento": "C",
            "tipoCliente": "Natural",
            "nombres": "María",
            "apellidos": "Prueba",
            "genero": "F",
            "estadoCivil": "Soltero",
            "fechaNacimiento": "1990-01-01",
            "codigoPaisNacionalidad": "ECU",
            "telefonoCelular": "0991234567",
            "email": "qa@example.invalid",
            "consentimientoDatos": True,
            "direccion": {
                "tipoDireccion": "Temporal",
                "codigoPais": "ECU",
                "idCiudad": 1,
                "calleDireccion": "Calle QA",
                "referenciaUbicacion": "Parque",
                "esPrincipal": True,
            },
        }
    )


def test_alta_vincula_cliente_direccion_principal_e_historial_sin_confirmar_por_separado():
    conexion = cursor({"id_cliente": 91}, {"id_direccion": 42}, None)
    resultado = repository.crear_cliente(
        cast(Connection, conexion), payload(), creado_por=7, direccion_ip="127.0.0.1"
    )
    assert resultado["id_cliente"] == 91
    assert resultado["estado"] == "Pendiente"
    assert resultado["direcciones"][0]["id_direccion"] == 42
    assert resultado["direcciones"][0]["tipo_direccion"] == "Temporal"
    llamadas = conexion.execute.call_args_list
    assert llamadas[1].args[1]["id_cliente"] == 91
    assert llamadas[1].args[1]["es_principal"] is True
    assert llamadas[2].args[1]["id_cliente"] == 91
    assert llamadas[2].args[1]["modificado_por"] == 7
    assert llamadas[2].args[1]["campo"] == "CREACION"
    conexion.commit.assert_not_called()  # El servicio confirma la unidad completa.


@pytest.mark.parametrize("fila", [None, {"otro_id": 1}])
def test_sin_id_cliente_no_escribe_direccion_ni_historial(fila):
    conexion = cursor(fila)
    with pytest.raises(RuntimeError, match="IdCliente"):
        repository.crear_cliente(
            cast(Connection, conexion),
            payload(),
            creado_por=7,
            direccion_ip="127.0.0.1",
        )
    assert conexion.execute.call_count == 1
    conexion.commit.assert_not_called()


@pytest.mark.parametrize("principal", [False, True])
def test_insertar_direccion_utiliza_id_devuelto_y_actor_del_servidor(principal):
    row = {"id_direccion": 42, "estado": "Activo"}
    conexion = cursor(*([None] if principal else []), row, None)
    datos = payload().direccion.model_dump()
    datos["es_principal"] = principal
    resultado = repository.insertar_direccion(
        cast(Connection, conexion),
        91,
        datos,
        modificado_por=7,
        direccion_ip="127.0.0.1",
    )
    assert resultado == row
    llamadas = conexion.execute.call_args_list
    if principal:
        assert llamadas[0].args[1] == {"id_cliente": 91}
    insercion = llamadas[-2].args[1]
    assert insercion["tipo_direccion"] == "Temporal"
    assert insercion["creado_por"] == 7
    assert insercion["id_cliente"] == 91
    assert llamadas[-1].args[1]["observaciones"] == "Dirección 42 creada"


def test_sin_respuesta_del_insert_no_inventa_una_direccion():
    conexion = cursor(None)
    datos = {**payload().direccion.model_dump(), "es_principal": False}
    with pytest.raises(RuntimeError, match="dirección insertada"):
        repository.insertar_direccion(
            cast(Connection, conexion),
            91,
            datos,
            modificado_por=7,
            direccion_ip="127.0.0.1",
        )
    assert conexion.execute.call_count == 1


def test_edicion_distingue_null_de_omitido_y_audita_cada_campo():
    conexion = cursor(None, {"id_direccion": 42, "sector": None}, None, None)
    repository.actualizar_direccion(
        cast(Connection, conexion),
        91,
        42,
        {"sector": None, "es_principal": True},
        modificado_por=7,
        direccion_ip="127.0.0.1",
        valores_anteriores={"sector": "Centro", "es_principal": False},
    )
    llamadas = conexion.execute.call_args_list
    params = llamadas[1].args[1]
    assert params["id_cliente"] == 91 and params["id_direccion"] == 42
    assert params["enviado_sector"] is True and params["sector"] is None
    assert params["enviado_calle_direccion"] is False
    auditorias = [llamada.args[1] for llamada in llamadas[2:]]
    assert {a["campo"] for a in auditorias} == {
        "DIRECCION.sector",
        "DIRECCION.es_principal",
    }
    assert json.loads(auditorias[0]["observaciones"])["valorAnterior"] == "Centro"
    assert all(a["modificado_por"] == 7 for a in auditorias)


def test_sin_fila_actualizada_no_audita_un_exito():
    conexion = cursor(None)
    with pytest.raises(RuntimeError, match="Dirección no encontrada"):
        repository.actualizar_direccion(
            cast(Connection, conexion),
            91,
            42,
            {"sector": None},
            modificado_por=7,
            direccion_ip="127.0.0.1",
            valores_anteriores={"sector": "Centro"},
        )
    assert conexion.execute.call_count == 1


def test_baja_logica_conserva_identidad_y_registra_antes_despues():
    conexion = cursor(None, None)
    repository.eliminar_direccion_logica(
        cast(Connection, conexion),
        91,
        42,
        modificado_por=7,
        direccion_ip="127.0.0.1",
        estado_anterior="Activo",
    )
    llamadas = conexion.execute.call_args_list
    assert llamadas[0].args[1] == {"id_direccion": 42, "id_cliente": 91}
    assert not str(llamadas[0].args[0]).lstrip().upper().startswith("DELETE")
    evento = llamadas[1].args[1]
    assert evento["campo"] == "DIRECCION.estado"
    cambios = json.loads(evento["observaciones"])
    assert cambios["valorAnterior"] == "Activo"
    assert cambios["valorNuevo"] == "Eliminado"


def test_fallo_al_confirmar_registro_revierte_la_unidad_cliente_direccion(monkeypatch):
    entrada = payload()
    monkeypatch.setattr(service, "edad_mayoria", lambda *_: 18)
    datos = repository.crear_cliente(
        cast(Connection, cursor({"id_cliente": 91}, {"id_direccion": 42}, None)),
        entrada,
        creado_por=7,
        direccion_ip="127.0.0.1",
    )
    monkeypatch.setattr(
        repository, "obtener_cliente_por_identificacion", lambda *args: None
    )
    monkeypatch.setattr(repository, "existe_pais", lambda *args: True)
    monkeypatch.setattr(repository, "existe_ciudad", lambda *args: True)
    monkeypatch.setattr(service, "validar_tipo_direccion", lambda *args: None)
    monkeypatch.setattr(repository, "crear_cliente", lambda *args, **kwargs: datos)
    conexion = MagicMock(spec=Connection)
    from app.modules.clientes import documentos_identidad
    from app.modules.clientes.schemas import ConsultaDocumentoBody

    monkeypatch.setattr(
        documentos_identidad,
        "preparar_alta",
        lambda *_: ConsultaDocumentoBody(
            tipo_documento="CED",
            numero=entrada.identificacion,
        ),
    )
    monkeypatch.setattr(documentos_identidad, "insertar", lambda *_, **__: 1)
    conexion.commit.side_effect = RuntimeError("Fallo de confirmación")
    with pytest.raises(RuntimeError, match="Fallo de confirmación"):
        service.registrar_cliente(cast(Connection, conexion), entrada, 7, "127.0.0.1")
    conexion.rollback.assert_called_once()
