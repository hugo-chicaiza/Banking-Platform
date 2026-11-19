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


# --- E0-18: institución desde su perfil, quién lo generó y zona horaria -------------


def test_pie_con_quien_lo_genero_y_la_zona_de_la_institucion():
    from datetime import UTC

    from app.core.pdf import Institucion

    doc = DocumentoPdf(
        "Comprobante",
        institucion=Institucion(nombre="Cooperativa Andina", ruc="1790012345001"),
        generado_por="Ana Pérez",
        zona=UTC,
        nombre_zona="UTC",
    )
    doc.parrafo("Depósito")
    texto = _texto(doc.contenido())
    for esperado in (
        "Cooperativa Andina",
        "RUC 1790012345001",
        "Generado por Ana P",
        "UTC",
        "Comprobante",
    ):
        assert esperado in texto, esperado


def test_sin_quien_mantiene_el_pie_y_la_hora_de_ecuador():
    texto = _texto(DocumentoPdf("Ficha", institucion="EnquoCoop").contenido())
    assert "Generado el" in texto and "hora de Ecuador" in texto
    assert "RUC" not in texto


def test_institucion_actual_desde_el_perfil(monkeypatch):
    from types import SimpleNamespace

    from app.core.pdf import institucion_actual
    from app.modules.organizacion import service

    entidad = SimpleNamespace(
        nombre_comercial=None,
        razon_social="Cooperativa Andina Ltda.",
        ruc="1790012345001",
        sitio_web="https://andina.ec",
    )
    monkeypatch.setattr(service, "obtener_entidad", lambda conn: entidad)
    datos = institucion_actual(None)  # type: ignore[arg-type]
    assert (datos.nombre, datos.ruc, datos.sitio_web) == (
        "Cooperativa Andina Ltda.",
        "1790012345001",
        "https://andina.ec",
    )


def test_institucion_actual_sin_perfil_usa_la_configuracion(monkeypatch):
    from fastapi import HTTPException

    from app.core.config.settings import get_settings
    from app.core.pdf import institucion_actual
    from app.modules.organizacion import service

    def sin_perfil(conn):
        raise HTTPException(status_code=404)

    monkeypatch.setattr(service, "obtener_entidad", sin_perfil)
    datos = institucion_actual(None)  # type: ignore[arg-type]
    assert datos.nombre == get_settings().cooperativa_nombre and datos.ruc is None


def test_el_generador_no_escribe_en_disco(tmp_path, monkeypatch):
    # Todo se arma en memoria: con el directorio de trabajo vacío, sigue vacío
    monkeypatch.chdir(tmp_path)
    doc = DocumentoPdf("Reporte", institucion="EnquoCoop", generado_por="Ana")
    doc.tabla(["A", "B"], [["1", "2"]] * 200)  # varias páginas
    assert doc.contenido().startswith(b"%PDF")
    assert list(tmp_path.iterdir()) == []
