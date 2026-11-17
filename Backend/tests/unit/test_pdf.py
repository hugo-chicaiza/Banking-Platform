"""Utilidad común de PDF (app.core.pdf)."""

import re
import zlib

from app.core.pdf import (
    DocumentoPdf,
    nombre_archivo,
    respuesta_pdf,
    respuestas_pdf,
    texto_pdf,
)


def _texto(pdf: bytes) -> str:
    """Texto de los flujos del PDF (fpdf2 los comprime con zlib)."""
    partes = []
    for flujo in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL):
        try:
            partes.append(zlib.decompress(flujo).decode("latin-1"))
        except zlib.error:
            continue
    return "".join(partes)


def test_documento_con_bloques_encabezado_y_pie():
    doc = DocumentoPdf("Ficha del subproducto", institucion="EnquoCoop")
    doc.titulo("Ahorro a la vista")
    doc.subtitulo("Datos")
    doc.campos([("Código", "AHO001-PN"), ("Estado", "Activo")])
    doc.parrafo("Cuenta de ahorro con retiros libres.")
    doc.tabla(
        ["Canal", "Cupo diario"],
        [["Ventanilla", "10.000,00"], ["Cajero", "500,00"]],
        anchos=(3, 1),
    )
    pdf = doc.contenido()
    assert pdf.startswith(b"%PDF")
    texto = _texto(pdf)
    for esperado in (
        "EnquoCoop",
        "Ficha del subproducto",
        "AHO001-PN",
        "Ventanilla",
        "Generado el",
        "gina 1 de",  # el total va en otro fragmento de texto
    ):
        assert esperado in texto, esperado
    assert b"/Title" in pdf


def test_tabla_larga_pasa_de_pagina_y_numera():
    doc = DocumentoPdf("Listado", institucion="EnquoCoop")
    doc.tabla(["N", "Nombre"], [[str(i), f"Fila {i}"] for i in range(120)])
    texto = _texto(doc.contenido())
    assert "gina 1 de " in texto and "gina 2 de " in texto
    assert texto.count("Nombre") >= 2  # la cabecera se repite en la página nueva


def test_sin_encabezado_ni_pie():
    texto = _texto(
        DocumentoPdf(
            "Sobre", institucion="EnquoCoop", encabezado=False, pie=False
        ).contenido()
    )
    assert "Generado el" not in texto and "EnquoCoop" not in texto


def test_caracteres_fuera_de_latin1_no_rompen_el_documento():
    assert texto_pdf("Saldo — mínimo “neto” … 💳") == 'Saldo - mínimo "neto" ... ?'
    assert texto_pdf(None) == "" and texto_pdf(12.5) == "12.5"
    doc = DocumentoPdf("Prueba — rayas")
    doc.parrafo("Emoji 🏦 y comillas ‘simples’")
    assert doc.contenido().startswith(b"%PDF")


def test_destacado_al_final_de_la_hoja():
    doc = DocumentoPdf("Sobre", encabezado=False, pie=False, salto_automatico=False)
    doc.destacado("4 8 2 1", etiqueta="Tu PIN", desde_abajo_mm=90)
    texto = _texto(doc.contenido())
    assert "Tu PIN" in texto and "4 8 2 1" in texto


def test_nombre_de_archivo_seguro():
    assert nombre_archivo("sobre-pin-301.pdf") == "sobre-pin-301.pdf"
    assert nombre_archivo("../../etc/passwd") == "passwd.pdf"
    assert nombre_archivo('ficha "AHO001".PDF') == "ficha-AHO001.pdf"
    assert nombre_archivo("..") == "documento.pdf"


def test_respuesta_descarga_sin_cache():
    r = respuesta_pdf(b"%PDF-1.4", "comprobante 12.pdf")
    assert r.media_type == "application/pdf"
    assert (
        r.headers["content-disposition"] == 'attachment; filename="comprobante-12.pdf"'
    )
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert (
        respuesta_pdf(b"%PDF", "x", adjunto=False)
        .headers["content-disposition"]
        .startswith("inline;")
    )
    assert respuestas_pdf("Ficha")[200]["content"] == {"application/pdf": {}}
