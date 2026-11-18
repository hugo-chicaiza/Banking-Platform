"""No sustituyen las pruebas SQL, de concurrencia ni la sesion real WorkOS."""

import hashlib

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.aprobaciones.congelacion import congelar, verificar
from app.modules.aprobaciones.contratos import Rechazo, SolicitudAceptada


def test_huella_estable_para_orden_distinto_y_utf8():
    a = congelar({"valor": "19:00", "meta": {"b": 2, "a": "ñ"}})
    b = congelar({"meta": {"a": "ñ", "b": 2}, "valor": "19:00"})
    assert a == b
    assert verificar(a.texto, a.huella)["valor"] == "19:00"


def test_detecta_cambio_sin_mostrar_contenido():
    a = congelar({"valor": "10"})
    with pytest.raises(HTTPException, match="CONTENIDO_ALTERADO") as error:
        verificar(a.texto.replace("10", "20"), a.huella)
    assert error.value.status_code == 409
    assert "20" not in str(error.value.detail)


@pytest.mark.parametrize(
    "clave", ["PIN", "pan", "access_token", "Cookie", "secret", "numeroTarjeta"]
)
def test_no_persistir_campos_secretos_anidados(clave):
    with pytest.raises(HTTPException, match="CONTENIDO_INVALIDO"):
        congelar({"cambio": [{clave: "fixture_no_secreto"}]})


@pytest.mark.parametrize("valor", [float("nan"), float("inf"), object()])
def test_no_canonizar_valores_no_json(valor):
    with pytest.raises(HTTPException, match="CONTENIDO_INVALIDO"):
        congelar({"valor": valor})


@pytest.mark.parametrize("texto", ['{"a":1,"a":2}', '{"a":NaN}', "[1,2]", '{ "a":1 }'])
def test_rechazar_representacion_no_canonica(texto):
    with pytest.raises(HTTPException) as error:
        verificar(texto, hashlib.sha256(texto.encode()).digest())
    assert error.value.status_code == 409


def test_limite_es_por_bytes_utf8_y_no_caracteres():
    with pytest.raises(HTTPException, match="CONTENIDO_INVALIDO"):
        congelar({"valor": "ñ" * 33000})


@pytest.mark.parametrize("comentario", ["", " ", "\n\t", "x" * 301])
def test_rechazo_exige_comentario(comentario):
    with pytest.raises(ValidationError):
        Rechazo(comentario=comentario)


def test_el_cliente_no_puede_elegir_el_actor_del_rechazo():
    with pytest.raises(ValidationError):
        Rechazo.model_validate({"comentario": "No corresponde", "actor": "otro"})


def test_202_no_se_representa_como_ejecucion_exitosa():
    resultado = SolicitudAceptada(id_solicitud=12).model_dump(by_alias=True)
    assert resultado == {
        "idSolicitud": 12,
        "estado": "Pendiente",
        "requiereAprobacion": True,
    }
