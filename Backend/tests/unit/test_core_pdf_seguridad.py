"""Endurecimiento de app.core.pdf: solo texto plano, sin controles, longitudes acotadas,
sin enlaces ni acciones (OWASP ASVS 5.0 1.2.x, 5.4.x) y salida que pasa el análisis."""

import inspect

import pytest

from app.core.documentos import analisis
from app.core.documentos.analisis import analizar
from app.core.pdf import DocumentoPdf, texto_pdf
from app.core.pdf import documento as modulo
from tests.unit.test_pdf import _texto

HOSTIL = "Ana\x00\x07\x1b[31m\x85" + chr(0x202E) + "\r\n<script>/JS</script>\t(/Launch)"


def test_texto_quita_controles_y_normaliza_saltos():
    assert texto_pdf("a\x00b\x07c\x1b[0m\x85\x9fd") == "abc[0md"
    assert texto_pdf("uno\r\ndos\rtres\tcuatro") == "uno\ndos\ntres cuatro"
    assert texto_pdf("uno\ndos", multilinea=False) == "uno dos"
    assert (
        texto_pdf(chr(0x202E) + "anverso") == "?anverso"
    )  # sin control bidi en Latin-1


def test_texto_limita_longitud():
    assert len(texto_pdf("x" * 10_000)) == modulo.MAX_TEXTO
    assert texto_pdf("abcdef", max_largo=5) == "ab..."
    assert texto_pdf("abc", max_largo=5) == "abc"


def test_metadatos_y_pie_limpios_y_acotados():
    doc = DocumentoPdf(
        "Título\x00\n" + "T" * 1000,
        institucion="Coop\x1b\nNorte",
        generado_por="Ana\r\nPérez\x00" + "z" * 500,
    )
    pdf = doc.pdf
    for valor in (pdf.title, pdf.author, pdf.creator):
        assert isinstance(valor, str)
        assert len(valor) <= modulo.MAX_METADATO
        assert not any(ord(c) < 32 or 127 <= ord(c) < 160 for c in valor)
    assert pdf.author == "Coop Norte"
    generado = pdf._generado  # type: ignore[attr-defined]
    assert "\n" not in generado and "\x00" not in generado
    assert "Ana Pérez" in generado and len(generado) < modulo.MAX_METADATO + 60


def test_bloques_no_dejan_pasar_controles():
    doc = DocumentoPdf("Ficha")
    doc.titulo(HOSTIL)
    doc.subtitulo(HOSTIL)
    doc.parrafo(HOSTIL)
    doc.campos([(HOSTIL, HOSTIL)])
    doc.tabla([HOSTIL], [[HOSTIL]])
    doc.destacado("1234\x00", etiqueta=HOSTIL)
    texto = _texto(doc.contenido())
    assert "\x1b" not in texto and "\x07" not in texto and "\x85" not in texto
    assert "[31m" in texto  # el resto del texto se conserva como texto


def test_pdf_sin_enlaces_ni_acciones_y_limpio_para_el_analisis():
    doc = DocumentoPdf(HOSTIL, institucion=HOSTIL, generado_por=HOSTIL)
    doc.titulo("javascript:alert(1)")
    doc.parrafo("https://ejemplo.ec /URI (file:///etc/passwd)")
    doc.campos([("Enlace", "javascript:alert(1)")])
    doc.tabla(["/OpenAction"], [["<< /S /JavaScript >>"]])
    contenido = doc.contenido()
    # Nombres PDF reales (fuera de cadenas y flujos): ningún enlace ni acción
    nombres = {v for clase, v in analisis._tokens(contenido) if clase == "n"}
    assert not nombres & {b"Annots", b"Link", b"URI", b"A", b"JavaScript", b"Launch"}
    resultado = analizar(contenido, "application/pdf")
    assert (resultado.veredicto, resultado.motivo) == ("Limpio", None)


@pytest.mark.parametrize(
    "prohibido", ["markdown=True", "write_html", "link=", ".link("]
)
def test_documento_no_interpreta_markup_ni_crea_enlaces(prohibido):
    for clase in (modulo.DocumentoPdf, modulo._Pdf):
        assert prohibido not in inspect.getsource(clase)
