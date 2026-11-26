"""Almacenamiento de documentos (app.core.documentos), con el adaptador en memoria."""

import io
import os
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from app.core.database import mongo
from app.core.documentos import (
    AlmacenamientoNoDisponible,
    ArchivoMuyGrande,
    ArchivoRechazado,
    DocumentoNoDisponible,
    DocumentoNoEncontrado,
    ErrorDocumento,
    ServicioDocumentos,
    TipoNoPermitido,
    problema_documento,
    respuesta_documento,
)
from app.core.documentos import servicio as modulo_servicio
from app.core.documentos.almacen import AlmacenMemoria, ErrorAlmacen
from app.core.pdf import DocumentoPdf

PDF = DocumentoPdf("Prueba").contenido()


def _imagen(formato: str) -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(salida, formato)
    return salida.getvalue()


PNG = _imagen("PNG")
JPG = _imagen("JPEG")


@pytest.fixture
def almacen() -> AlmacenMemoria:
    return AlmacenMemoria()


@pytest.fixture
def servicio(almacen: AlmacenMemoria) -> ServicioDocumentos:
    return ServicioDocumentos(almacen, os.urandom(32), max_bytes=5 * 1024 * 1024)


def test_pdf_del_sistema_se_guarda_cifrado_y_se_lee(servicio, almacen):
    ref = servicio.guardar(PDF, origen="creditos", generado_por_sistema=True)
    assert ref.tipo_contenido == "application/pdf" and ref.analisis == "Limpio"
    assert ref.tamano == len(PDF) and len(ref.sha256) == 64
    guardado = almacen.documentos[ref.clave]
    assert b"%PDF" not in guardado["contenido"]  # cifrado en reposo
    assert guardado["origen"] == "creditos"
    assert servicio.leer(ref.clave).contenido == PDF


def test_lo_que_sube_un_usuario_se_analiza_antes_de_guardar(servicio, almacen):
    ref = servicio.guardar(PNG, origen="clientes")
    assert ref.analisis == "Limpio"  # análisis síncrono: pasó las reglas
    assert servicio.leer(ref.clave).contenido == PNG
    antes = len(almacen.documentos)
    with pytest.raises(ArchivoRechazado) as error:  # políglota PNG + ZIP
        servicio.guardar(PNG + b"PK\x03\x04\x14\x00" + os.urandom(32), origen="x")
    assert error.value.motivo == "DATOS_TRAS_FIN"
    assert len(almacen.documentos) == antes  # no se guarda nada
    # Un análisis posterior todavía puede bloquear la entrega
    servicio.marcar_analisis(ref.clave, "Rechazado")
    with pytest.raises(DocumentoNoDisponible):
        servicio.leer(ref.clave)
    servicio.marcar_analisis(ref.clave, "Limpio")
    assert servicio.leer(ref.clave).tipo_contenido == "image/png"


def test_tipo_por_contenido_y_tamano(servicio, almacen):
    assert servicio.guardar(JPG, origen="clientes").tipo_contenido == "image/jpeg"
    with pytest.raises(TipoNoPermitido):  # un ejecutable renombrado a .pdf
        servicio.guardar(b"MZ\x90\x00" + os.urandom(32), origen="clientes")
    with pytest.raises(TipoNoPermitido):  # el módulo solo acepta PDF
        servicio.guardar(PNG, origen="creditos", tipos=("application/pdf",))
    pequeno = ServicioDocumentos(almacen, os.urandom(32), max_bytes=10)
    antes = len(almacen.documentos)
    with pytest.raises(ArchivoMuyGrande):
        pequeno.guardar(PDF, origen="clientes")
    assert len(almacen.documentos) == antes  # no se guarda nada


def test_nunca_sobrescribe_y_cada_guardado_es_otra_clave(servicio):
    a = servicio.guardar(PDF, origen="x", generado_por_sistema=True)
    b = servicio.guardar(PDF, origen="x", generado_por_sistema=True)
    assert a.clave != b.clave and a.sha256 == b.sha256


def test_contenido_atado_a_su_clave(servicio, almacen):
    a = servicio.guardar(PDF, origen="x", generado_por_sistema=True)
    b = servicio.guardar(PDF, origen="x", generado_por_sistema=True)
    # El contenido cifrado de un documento puesto en otro no se puede descifrar
    almacen.documentos[b.clave]["contenido"] = almacen.documentos[a.clave]["contenido"]
    with pytest.raises(AlmacenamientoNoDisponible):
        servicio.leer(b.clave)


def test_eliminar_y_documento_inexistente(servicio):
    ref = servicio.guardar(PDF, origen="x", generado_por_sistema=True)
    servicio.eliminar(ref.clave)
    with pytest.raises(DocumentoNoEncontrado):
        servicio.leer(ref.clave)
    with pytest.raises(DocumentoNoEncontrado):
        servicio.marcar_analisis("no-existe", "Limpio")


def test_almacen_caido_es_503(servicio, monkeypatch):
    def cae(*_a: Any, **_k: Any) -> None:
        raise ErrorAlmacen("ServerSelectionTimeoutError")

    monkeypatch.setattr(servicio.almacen, "guardar", cae)
    monkeypatch.setattr(servicio.almacen, "leer", cae)
    monkeypatch.setattr(servicio.almacen, "eliminar", cae)
    with pytest.raises(AlmacenamientoNoDisponible):
        servicio.guardar(PDF, origen="x", generado_por_sistema=True)
    with pytest.raises(AlmacenamientoNoDisponible):
        servicio.leer("abc")
    servicio.eliminar("abc")  # la compensación no lanza


def test_sin_configuracion_no_hay_servicio(monkeypatch):
    configurar = modulo_servicio._servicio_configurado.__wrapped__
    monkeypatch.setattr(modulo_servicio, "coleccion", lambda _n: None)
    assert configurar(os.urandom(32).hex(), 100) is None  # sin MONGO_URI
    assert configurar("corta", 100) is None  # clave que no es AES-256


def test_coleccion_compartida_sin_uri_no_conecta(monkeypatch):
    class Uri:
        def get_secret_value(self) -> str:
            return ""

    class Config:
        mongo_uri = Uri()
        mongo_db = "coop"

    def no_conectar(_uri: str) -> Any:
        pytest.fail("no debía conectar")

    monkeypatch.setattr(mongo, "get_settings", lambda: Config())
    monkeypatch.setattr(mongo, "_cliente", no_conectar)
    assert mongo.coleccion("documentos") is None


def test_coleccion_compartida_usa_uri_y_base(monkeypatch):
    class Uri:
        def get_secret_value(self) -> str:
            return "mongodb://servidor:27017"

    class Config:
        mongo_uri = Uri()
        mongo_db = "coop"

    pedidos: list[str] = []
    monkeypatch.setattr(mongo, "get_settings", lambda: Config())
    monkeypatch.setattr(
        mongo,
        "_cliente",
        lambda uri: pedidos.append(uri) or {"coop": {"documentos": "coleccion"}},
    )
    assert mongo.coleccion("documentos") == "coleccion"
    assert pedidos == ["mongodb://servidor:27017"]


@pytest.mark.parametrize(
    ("error", "status", "codigo"),
    [
        (ArchivoMuyGrande(), 413, "ARCHIVO_MUY_GRANDE"),
        (TipoNoPermitido(), 415, "TIPO_NO_PERMITIDO"),
        (ArchivoRechazado("EICAR"), 422, "ARCHIVO_RECHAZADO"),
        (DocumentoNoEncontrado(), 404, "DOCUMENTO_NO_ENCONTRADO"),
        (DocumentoNoDisponible(), 409, "DOCUMENTO_NO_DISPONIBLE"),
        (AlmacenamientoNoDisponible(), 503, "ALMACENAMIENTO_NO_DISPONIBLE"),
    ],
)
def test_errores_http(error: ErrorDocumento, status: int, codigo: str):
    exc = problema_documento(error)
    assert exc.status_code == status
    assert exc.detail["code"] == codigo  # type: ignore[index]


def test_enlace_de_descarga(servicio):
    """Así lo usa la ruta de un módulo: su permiso y su auditoría, luego la respuesta."""
    ref = servicio.guardar(PNG, origen="clientes")
    app = FastAPI()

    @app.get("/archivos/{clave}/contenido")
    def contenido(clave: str) -> Any:
        try:
            return respuesta_documento(servicio.leer(clave), "cedula anverso.jpg")
        except ErrorDocumento as exc:
            raise problema_documento(exc) from None

    cliente = TestClient(app)
    r = cliente.get(f"/archivos/{ref.clave}/contenido")
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"] == "image/png"  # el tipo detectado, no el nombre
    assert (
        r.headers["content-disposition"] == 'attachment; filename="cedula-anverso.png"'
    )
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert cliente.get("/archivos/otra/contenido").status_code == 404
