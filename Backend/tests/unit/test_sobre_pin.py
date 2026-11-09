"""Sobre de PIN (TAR-07): PDF, cifrado, almacenes (disco y MongoDB) y configuración."""

import re
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr
from pymongo.errors import ServerSelectionTimeoutError

from app.core.config.settings import Settings
from app.modules.tarjetas import sobre_pin
from app.modules.tarjetas.sobre_pin import (
    AlmacenDisco,
    AlmacenMongo,
    AlmacenNoDisponible,
    Cifrador,
    ServicioSobres,
    SobreNoDisponible,
    SobreYaEntregado,
    construir_pdf,
)

# Referencia a la función real: conftest la reemplaza en cada prueba
_OBTENER_SERVICIO = sobre_pin.obtener_servicio

CLAVE = bytes(range(32))
AHORA = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
VENCE = AHORA + timedelta(days=30)


def texto_pdf(pdf: bytes) -> str:
    """Texto de los flujos del PDF (fpdf2 los comprime con zlib)."""
    partes = []
    for flujo in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL):
        try:
            partes.append(zlib.decompress(flujo).decode("latin-1"))
        except zlib.error:
            partes.append(flujo.decode("latin-1"))
    return "\n".join(partes)


# --- PDF -------------------------------------------------------------------------


def test_pdf_lleva_bienvenida_sitio_y_el_pin_al_final():
    pdf = construir_pdf(SecretStr("4821"), "EnquoCoop", "www.coop.com.ec")

    assert pdf.startswith(b"%PDF")
    texto = texto_pdf(pdf)
    assert "Bienvenido a la Cooperativa EnquoCoop" in texto
    assert "www.coop.com.ec" in texto
    assert "(4 8 2 1)" in texto
    # El PIN va después de la bienvenida (al final de la hoja)
    assert texto.index("(4 8 2 1)") > texto.index("www.coop.com.ec")


def test_pdf_no_lleva_numero_de_tarjeta():
    texto = texto_pdf(construir_pdf(SecretStr("4821"), "EnquoCoop", "x"))
    assert not re.search(r"\d{12,19}", texto)


# --- Cifrado ---------------------------------------------------------------------


def test_cifrado_ida_y_vuelta_y_ligado_a_tarjeta_y_sobre():
    cifrador = Cifrador(CLAVE)
    cifrado = cifrador.cifrar(301, "s1", b"%PDF contenido")

    assert b"%PDF" not in cifrado
    assert cifrador.descifrar(301, "s1", cifrado) == b"%PDF contenido"
    with pytest.raises(AlmacenNoDisponible):
        cifrador.descifrar(302, "s1", cifrado)
    with pytest.raises(AlmacenNoDisponible):
        cifrador.descifrar(301, "s2", cifrado)
    with pytest.raises(AlmacenNoDisponible):
        Cifrador(bytes(32)).descifrar(301, "s1", cifrado)


# --- Almacenes -------------------------------------------------------------------


class ColeccionFalsa:
    """Lo mínimo de una colección de pymongo que usa AlmacenMongo."""

    def __init__(self) -> None:
        self.docs: dict[int, dict[str, Any]] = {}
        self.indices: list[tuple[str, dict[str, Any]]] = []
        self.falla: Exception | None = None

    def _revisar(self) -> None:
        if self.falla is not None:
            raise self.falla

    def create_index(self, campo: str, **opciones: Any) -> None:
        self._revisar()
        self.indices.append((campo, opciones))

    def replace_one(self, filtro: dict, documento: dict, upsert: bool) -> None:
        self._revisar()
        assert upsert
        self.docs[filtro["_id"]] = dict(documento)

    def _coincide(self, doc: dict[str, Any], filtro: dict[str, Any]) -> bool:
        for campo, valor in filtro.items():
            if isinstance(valor, dict):
                if campo not in doc or not doc[campo] > valor["$gt"]:
                    return False
            elif doc.get(campo) != valor:
                return False
        return True

    def find_one_and_update(self, filtro, cambios, return_document) -> dict | None:
        self._revisar()
        doc = self.docs.get(filtro["_id"])
        if doc is None or not self._coincide(doc, filtro):
            return None
        previo = dict(doc)
        doc.update(cambios["$set"])
        for campo in cambios["$unset"]:
            doc.pop(campo, None)
        return previo

    def find_one(self, filtro, proyeccion=None) -> dict | None:
        self._revisar()
        doc = self.docs.get(filtro["_id"])
        return dict(doc) if doc is not None else None

    def delete_one(self, filtro) -> None:
        self._revisar()
        doc = self.docs.get(filtro["_id"])
        if doc is not None and self._coincide(doc, filtro):
            del self.docs[filtro["_id"]]


@pytest.fixture(params=["disco", "mongo"])
def almacen(request, tmp_path: Path):
    if request.param == "disco":
        return AlmacenDisco(tmp_path / "sobres")
    return AlmacenMongo(ColeccionFalsa())


def test_almacen_entrega_una_sola_vez(almacen):
    almacen.guardar(301, "s1", b"cifrado", "Aprobacion", AHORA, VENCE)

    entregado = almacen.entregar(301, 7, AHORA)

    assert (entregado.id_sobre, entregado.contenido) == ("s1", b"cifrado")
    with pytest.raises(SobreYaEntregado):
        almacen.entregar(301, 7, AHORA)


def test_almacen_sin_sobre(almacen):
    with pytest.raises(SobreNoDisponible):
        almacen.entregar(999, 7, AHORA)


def test_almacen_sobre_vencido_no_se_entrega_y_se_borra(almacen):
    almacen.guardar(301, "s1", b"cifrado", "Aprobacion", AHORA, VENCE)

    with pytest.raises(SobreNoDisponible):
        almacen.entregar(301, 7, VENCE + timedelta(seconds=1))
    # Ya no existe: tampoco aparece como entregado
    with pytest.raises(SobreNoDisponible):
        almacen.entregar(301, 7, AHORA)


def test_almacen_nuevo_sobre_reemplaza_al_anterior(almacen):
    almacen.guardar(301, "s1", b"viejo", "Aprobacion", AHORA, VENCE)
    almacen.entregar(301, 7, AHORA)
    almacen.guardar(301, "s2", b"nuevo", "Regeneracion", AHORA, VENCE)

    assert almacen.entregar(301, 7, AHORA).contenido == b"nuevo"


def test_almacen_descarta_solo_el_mismo_sobre(almacen):
    almacen.guardar(301, "s2", b"nuevo", "Regeneracion", AHORA, VENCE)

    almacen.descartar(301, "s1")
    assert almacen.entregar(301, 7, AHORA).id_sobre == "s2"

    almacen.guardar(301, "s3", b"otro", "Regeneracion", AHORA, VENCE)
    almacen.descartar(301, "s3")
    with pytest.raises(SobreNoDisponible):
        almacen.entregar(301, 7, AHORA)


def test_mongo_entregado_queda_sin_contenido_y_con_quien_lo_entrego():
    coleccion = ColeccionFalsa()
    almacen = AlmacenMongo(coleccion)
    almacen.guardar(301, "s1", b"cifrado", "Aprobacion", AHORA, VENCE)

    almacen.entregar(301, 7, AHORA)

    doc = coleccion.docs[301]
    assert doc["estado"] == "Entregado" and doc["entregadoPor"] == 7
    assert "contenido" not in doc and "expiraEn" not in doc
    assert coleccion.indices == [("expiraEn", {"expireAfterSeconds": 0})]


def test_mongo_caido_es_almacen_no_disponible():
    coleccion = ColeccionFalsa()
    coleccion.falla = ServerSelectionTimeoutError("sin servidor")
    almacen = AlmacenMongo(coleccion)

    with pytest.raises(AlmacenNoDisponible):
        almacen.guardar(301, "s1", b"x", "Aprobacion", AHORA, VENCE)
    with pytest.raises(AlmacenNoDisponible):
        almacen.entregar(301, 7, AHORA)
    with pytest.raises(AlmacenNoDisponible):
        almacen.descartar(301, "s1")


def test_disco_guarda_el_contenido_cifrado(tmp_path: Path):
    servicio = ServicioSobres(
        AlmacenDisco(tmp_path), Cifrador(CLAVE), "EnquoCoop", "www.coop.com.ec", 30
    )

    servicio.preparar(301, SecretStr("4821"), "Aprobacion")

    archivo = (tmp_path / "301.json").read_text(encoding="utf-8")
    assert "4821" not in archivo and "JVBERi" not in archivo  # "%PDF" en base64
    pdf = servicio.entregar(301, 7)
    assert "(4 8 2 1)" in texto_pdf(pdf)
    # Entregado: el sobre cifrado ya no existe; solo queda quién y cuándo
    assert not (tmp_path / "301.json").exists()
    entrega = (tmp_path / "301.entregado").read_text(encoding="utf-8")
    assert '"entregadoPor": 7' in entrega and "contenido" not in entrega


# --- Configuración ---------------------------------------------------------------


def _configurar(monkeypatch, **valores: Any) -> None:
    ajustes = Settings(_env_file=None, **valores)  # type: ignore[call-arg]
    monkeypatch.setattr(sobre_pin, "get_settings", lambda: ajustes)


def test_sin_clave_no_hay_sobres(monkeypatch):
    _configurar(monkeypatch, app_env="development")
    assert _OBTENER_SERVICIO() is None


def test_clave_invalida_no_hay_sobres(monkeypatch):
    _configurar(monkeypatch, app_env="development", sobre_pin_clave="abc")
    assert _OBTENER_SERVICIO() is None


def test_sin_mongo_fuera_de_produccion_usa_disco(monkeypatch, tmp_path):
    _configurar(
        monkeypatch,
        app_env="development",
        sobre_pin_clave=CLAVE.hex(),
        sobre_pin_dir=str(tmp_path),
        cooperativa_nombre="Coop Prueba",
    )
    servicio = _OBTENER_SERVICIO()

    assert servicio is not None and isinstance(servicio.almacen, AlmacenDisco)
    assert servicio.cooperativa == "Coop Prueba" and servicio.dias == 30


def test_sin_mongo_en_produccion_no_hay_sobres(monkeypatch):
    _configurar(monkeypatch, app_env="production", sobre_pin_clave=CLAVE.hex())
    assert _OBTENER_SERVICIO() is None


def test_con_mongo_uri_usa_mongo_sin_conectar_al_crear(monkeypatch):
    coleccion = ColeccionFalsa()
    llamadas: list[tuple[str, str]] = []

    def coleccion_mongo(uri: str, base: str) -> ColeccionFalsa:
        llamadas.append((uri, base))
        return coleccion

    monkeypatch.setattr(sobre_pin, "_coleccion_mongo", coleccion_mongo)
    _configurar(
        monkeypatch,
        app_env="production",
        sobre_pin_clave=CLAVE.hex(),
        mongo_uri="mongodb://servidor:27017",
        mongo_db="coop",
    )
    servicio = _OBTENER_SERVICIO()

    assert servicio is not None and isinstance(servicio.almacen, AlmacenMongo)
    assert llamadas == [("mongodb://servidor:27017", "coop")]


def test_servicio_descartar_no_falla_si_el_almacen_cae():
    almacen = SimpleNamespace(
        descartar=lambda *a: (_ for _ in ()).throw(AlmacenNoDisponible("x"))
    )
    servicio = ServicioSobres(almacen, Cifrador(CLAVE), "c", "s", 30)  # type: ignore[arg-type]

    servicio.descartar(301, "s1")


@pytest.mark.parametrize("id_tarjeta", [0, -1, True])
def test_disco_rechaza_ids_que_no_son_enteros_positivos(tmp_path: Path, id_tarjeta):
    almacen = AlmacenDisco(tmp_path)

    with pytest.raises(AlmacenNoDisponible):
        almacen.guardar(id_tarjeta, "s1", b"x", "Aprobacion", AHORA, VENCE)
    assert list(tmp_path.iterdir()) == []
