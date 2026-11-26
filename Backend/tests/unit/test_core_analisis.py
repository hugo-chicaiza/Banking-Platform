"""Análisis antimalware local + reputación por hash (app.core.documentos.analisis).

OWASP ASVS 5.0 5.2.2 / 5.4.3 y LOPDP (solo el hash sale a VirusTotal). Sin red real:
httpx se reemplaza por un falso.
"""

import hashlib
import io
import logging
import zlib
from typing import Any

import httpx
import pytest
from PIL import Image

from app.core.documentos import analisis
from app.core.documentos.analisis import EICAR, VIRUSTOTAL_URL, analizar
from app.core.pdf import DocumentoPdf

PDF = "application/pdf"
PNG_T = "image/png"
JPG_T = "image/jpeg"
CSV = "text/csv"


def _imagen(formato: str, **opciones: Any) -> bytes:
    salida = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 120, 200)).save(salida, formato, **opciones)
    return salida.getvalue()


PNG = _imagen("PNG")
JPG = _imagen("JPEG")
EXE = b"MZ" + b"\x00" * 0x3A + (0x40).to_bytes(4, "little") + b"PE\x00\x00"


def _pdf(catalogo: bytes, extra: bytes = b"", trailer: bytes = b"") -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog "
        + catalogo
        + b" >>\nendobj\n"
        + extra
        + b"trailer\n<< /Root 1 0 R "
        + trailer
        + b">>\n%%EOF\n"
    )


def _con_bloque_png(datos: bytes) -> bytes:
    """Un bloque privado antes de IEND (estructura PNG válida)."""
    bloque = b"zzZz" + datos
    crc = zlib.crc32(bloque).to_bytes(4, "big")
    return PNG[:-12] + len(datos).to_bytes(4, "big") + bloque + crc + PNG[-12:]


def _veredicto(contenido: bytes, tipo: str) -> tuple[str, str | None]:
    r = analizar(contenido, tipo)
    return r.veredicto, r.motivo


# --- PDF -----------------------------------------------------------------------------


def test_pdf_generado_por_core_pdf_es_limpio():
    doc = DocumentoPdf("Ficha (/JS) /Launch", institucion="Coop", generado_por="Ana")
    doc.titulo("/OpenAction << /S /JavaScript >>")
    doc.tabla(["/URI"], [["javascript:alert(1)"]])
    assert _veredicto(doc.contenido(), PDF) == ("Limpio", None)


@pytest.mark.parametrize(
    "catalogo",
    [
        b"/OpenAction << /S /JavaScript /JS (app.alert(1)) >>",
        b"/OpenAction 5 0 R",
        b"/AA << /O 4 0 R >>",
        b"/Names << /EmbeddedFiles 2 0 R >>",
        b"/A << /S /Launch /F (cmd.exe) >>",
        b"/FS << /Type /EmbeddedFile >>",
        b"/RichMedia 3 0 R",
        b"/AcroForm << /XFA 3 0 R >>",
        b"/A << /S /SubmitForm >>",
        b"/A << /S /ImportData >>",
        b"/A << /S /GoToR /F (otro.pdf) >>",
        b"/A << /S /J#61va#53cript >>",  # nombre ofuscado con #xx
        b"/A << /#4A#53 (x) >>",  # /JS ofuscado
    ],
)
def test_pdf_con_contenido_activo(catalogo):
    assert _veredicto(_pdf(catalogo), PDF) == ("Rechazado", "PDF_CONTENIDO_ACTIVO")


@pytest.mark.parametrize(
    "uri",
    [
        b"(javascript:alert(1))",
        b"( JaVa\tScript:alert(1))",
        b"(file:///C:/Windows/system32)",
        b"<6A6176617363726970743A78>",  # javascript:x en hexadecimal
        b"(java\\163cript:x)",  # escape octal
    ],
)
def test_pdf_uri_peligrosa(uri):
    contenido = _pdf(b"/A << /S /URI /URI " + uri + b" >>")
    assert _veredicto(contenido, PDF) == ("Rechazado", "PDF_URI_PELIGROSA")


@pytest.mark.parametrize(
    "catalogo",
    [
        b"/A << /S /URI /URI (https://www.ejemplo.ec) >>",
        b"/OpenAction [3 0 R /FitH null]",  # destino de página, como fpdf2
        b"/Title (/JavaScript /Launch)",  # dentro de una cadena no es un nombre
        b"/JSX 1 /AAA 2",  # nombres parecidos no cuentan
    ],
)
def test_pdf_sin_riesgo(catalogo):
    assert _veredicto(_pdf(catalogo), PDF) == ("Limpio", None)


def test_pdf_flujo_comprimido_con_texto_no_dispara():
    flujo = zlib.compress(b"BT (/JS /Launch) Tj ET")
    extra = (
        b"2 0 obj\n<< /Filter /FlateDecode /Length "
        + str(len(flujo)).encode()
        + b" >>\nstream\n"
        + flujo
        + b"\nendstream\nendobj\n"
    )
    assert _veredicto(_pdf(b"", extra), PDF) == ("Limpio", None)


@pytest.mark.parametrize("comprimido", [True, False])
def test_pdf_javascript_escondido_en_flujo_de_objetos(comprimido):
    objetos = b"3 0 << /S /JavaScript /JS (x) >>"
    flujo = zlib.compress(objetos) if comprimido else objetos
    filtro = b"/Filter /FlateDecode " if comprimido else b""
    extra = (
        b"2 0 obj\n<< /Type /ObjStm /N 1 /First 4 "
        + filtro
        + b">>\nstream\n"
        + flujo
        + b"\nendstream\nendobj\n"
    )
    assert _veredicto(_pdf(b"", extra), PDF) == ("Rechazado", "PDF_CONTENIDO_ACTIVO")


def test_pdf_flujo_de_objetos_corrupto():
    extra = b"2 0 obj\n<< /Type /ObjStm /Filter /FlateDecode >>\nstream\nbasura\nendstream\nendobj\n"
    assert _veredicto(_pdf(b"", extra), PDF) == ("Rechazado", "PDF_MAL_FORMADO")


def test_pdf_con_ejecutable_embebido_sin_comprimir():
    extra = b"2 0 obj\n<< /Length 70 >>\nstream\n" + EXE + b"\nendstream\nendobj\n"
    assert _veredicto(_pdf(b"", extra), PDF) == ("Rechazado", "FIRMA_EMBEBIDA")
    # `<script` en un PDF es texto: no lo ejecuta ningún lector
    assert _veredicto(_pdf(b"/Title (<script>)"), PDF) == ("Limpio", None)


def test_pdf_cifrado_y_sin_fin():
    cifrado = _pdf(b"", trailer=b"/Encrypt 9 0 R ")
    assert _veredicto(cifrado, PDF) == ("Rechazado", "PDF_CIFRADO")
    truncado = _pdf(b"").replace(b"%%EOF", b"")
    assert _veredicto(truncado, PDF) == ("Rechazado", "PDF_SIN_FIN")


# --- Imágenes ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("contenido", "tipo"),
    [
        (PNG, PNG_T),
        (JPG, JPG_T),
        (_imagen("JPEG", progressive=True), JPG_T),
        (JPG + b"\x00\x00", JPG_T),  # relleno tras EOI que dejan algunas cámaras
    ],
)
def test_imagenes_validas_son_limpias(contenido, tipo):
    assert _veredicto(contenido, tipo) == ("Limpio", None)


@pytest.mark.parametrize(
    ("contenido", "tipo"),
    [
        (PNG + b"PK\x03\x04\x14\x00" + b"x" * 40 + b"PK\x05\x06", PNG_T),  # políglota
        (JPG + b"<?php system($_GET[1]); ?>", JPG_T),
        (PNG + EXE, PNG_T),
    ],
)
def test_datos_despues_del_final(contenido, tipo):
    assert _veredicto(contenido, tipo) == ("Rechazado", "DATOS_TRAS_FIN")


@pytest.mark.parametrize("contenido", [PNG[:-20], b"\x89PNG\r\n\x1a\n" + b"\x00" * 3])
def test_png_mal_formado(contenido):
    assert _veredicto(contenido, PNG_T) == ("Rechazado", "IMAGEN_MAL_FORMADA")


def test_jpeg_mal_formado():
    assert _veredicto(JPG[:-40], JPG_T) == ("Rechazado", "IMAGEN_MAL_FORMADA")
    assert _veredicto(b"\xff\xd8\xff" + b"\x00" * 10, JPG_T)[0] == "Rechazado"


@pytest.mark.parametrize(
    "embebido",
    [
        EXE,
        b"\x7fELF\x02\x01\x01\x00",
        b"PK\x03\x04\x14\x00\x00\x00",
        b"#!/bin/sh\nrm -rf /",
        b"<SCRIPT>alert(1)</script>",
    ],
)
def test_firmas_embebidas_en_imagen(embebido):
    assert _veredicto(_con_bloque_png(embebido), PNG_T) == (
        "Rechazado",
        "FIRMA_EMBEBIDA",
    )


def test_tipo_declarado_debe_coincidir_y_tipo_desconocido_se_rechaza():
    assert _veredicto(PNG, JPG_T) == ("Rechazado", "TIPO_NO_COINCIDE")
    assert _veredicto(b"hola", "application/zip") == ("Rechazado", "TIPO_NO_ANALIZABLE")


# --- Texto / CSV ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "contenido",
    [
        b"a,b\r\n1,\tdos\n",
        b"\xef\xbb\xbfNombre,Valor\nNi\xc3\xb1ez,1\n",  # UTF-8 con BOM
        b"",
    ],
)
def test_csv_limpio(contenido):
    assert _veredicto(contenido, CSV) == ("Limpio", None)


@pytest.mark.parametrize(
    ("contenido", "motivo"),
    [
        (b"a,b\n1,\x00\n", "TEXTO_CON_CONTROL"),  # NUL
        (b"a,b\n1,\x1b[31m\n", "TEXTO_CON_CONTROL"),
        (b"a,b\n1,\x7f\n", "TEXTO_CON_CONTROL"),
        (b"a,b\n\xff\xfe\n", "TEXTO_NO_UTF8"),
        (b"a,\xc3\n", "TEXTO_NO_UTF8"),  # UTF-8 truncado
        (b"%PDF-1.4\n", "FIRMA_EMBEBIDA"),
        (b"#!/usr/bin/env python\n", "FIRMA_EMBEBIDA"),
        (b"a,b\n1,<script>x</script>\n", "FIRMA_EMBEBIDA"),
    ],
)
def test_csv_rechazado(contenido, motivo):
    assert _veredicto(contenido, CSV) == ("Rechazado", motivo)


@pytest.mark.parametrize(
    ("contenido", "tipo"),
    [(EICAR, CSV), (EICAR, "text/plain"), (PNG + EICAR, PNG_T), (_pdf(EICAR), PDF)],
)
def test_eicar_siempre_se_rechaza(contenido, tipo):
    assert _veredicto(contenido, tipo) == ("Rechazado", "EICAR")


# --- Reputación (VirusTotal simulado) -----------------------------------------------


class _VirusTotalFalso:
    def __init__(self, respuesta: Any) -> None:
        self.respuesta = respuesta
        self.llamadas: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> httpx.Response:
        self.llamadas.append((args, kwargs))
        if isinstance(self.respuesta, Exception):
            raise self.respuesta
        return self.respuesta


def _respuesta(status: int, cuerpo: Any = None) -> httpx.Response:
    return httpx.Response(
        status, json=cuerpo, request=httpx.Request("GET", "https://x")
    )


def _maliciosos(n: int) -> httpx.Response:
    stats = {"malicious": n, "harmless": 60}
    return _respuesta(200, {"data": {"attributes": {"last_analysis_stats": stats}}})


@pytest.fixture
def virustotal(monkeypatch):
    def instalar(respuesta: Any) -> _VirusTotalFalso:
        falso = _VirusTotalFalso(respuesta)
        monkeypatch.setattr(analisis, "_clave_reputacion", lambda: "clave-prueba")
        monkeypatch.setattr(analisis.httpx, "get", falso)
        return falso

    return instalar


@pytest.mark.parametrize(
    ("respuesta", "esperado"),
    [
        (_maliciosos(3), ("Rechazado", "REPUTACION_MALICIOSA")),
        (_maliciosos(0), ("Limpio", None)),
        (_respuesta(404, {"error": {"code": "NotFoundError"}}), ("Limpio", None)),
        (_respuesta(429), ("Limpio", None)),
        (_respuesta(200, {"data": {}}), ("Limpio", None)),
        (httpx.ReadTimeout("lento"), ("Limpio", None)),
        (httpx.ConnectError("sin red"), ("Limpio", None)),
    ],
)
def test_reputacion(virustotal, respuesta, esperado):
    falso = virustotal(respuesta)
    assert _veredicto(PNG, PNG_T) == esperado
    assert len(falso.llamadas) == 1


def test_solo_viaja_el_hash_nunca_el_contenido(virustotal):
    falso = virustotal(_respuesta(404))
    contenido = b"cedula,nombre\n1710034065,Ana\n"
    analizar(contenido, CSV)
    ((args, kwargs),) = falso.llamadas
    sha256 = hashlib.sha256(contenido).hexdigest()
    assert args == (VIRUSTOTAL_URL.format(sha256),)
    assert args[0].startswith("https://www.virustotal.com/api/v3/files/")
    assert set(kwargs) == {"headers", "timeout"}  # sin content/data/files/json
    assert kwargs["timeout"] <= 5
    enviado = repr((args, kwargs)).encode()
    assert b"1710034065" not in enviado and b"Ana" not in enviado


def test_error_de_reputacion_no_bloquea_y_no_registra_datos(virustotal, caplog):
    virustotal(httpx.ReadTimeout("lento"))
    contenido = b"cedula\n1710034065\n"
    with caplog.at_level(logging.WARNING, logger=analisis.__name__):
        assert analizar(contenido, CSV).veredicto == "Limpio"
    assert "ReadTimeout" in caplog.text
    assert "1710034065" not in caplog.text
    assert hashlib.sha256(contenido).hexdigest() not in caplog.text


def test_sin_clave_o_con_rechazo_local_no_consulta(virustotal, monkeypatch):
    falso = virustotal(_maliciosos(1))
    assert analizar(PNG + b"basura", PNG_T).motivo == "DATOS_TRAS_FIN"
    monkeypatch.setattr(analisis, "_clave_reputacion", lambda: "")
    assert analizar(PNG, PNG_T).veredicto == "Limpio"
    assert falso.llamadas == []


def test_clave_viene_de_la_configuracion(monkeypatch):
    class Secreto:
        def get_secret_value(self) -> str:
            return "desde-settings"

    class Config:
        virustotal_api_key = Secreto()

    monkeypatch.undo()  # quita el _clave_reputacion falso de conftest
    monkeypatch.setattr(analisis, "get_settings", lambda: Config())
    assert analisis._clave_reputacion() == "desde-settings"
