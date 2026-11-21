"""Documento PDF común para cualquier módulo (comprobantes, fichas, reportes, sobres).

Envuelve fpdf2 con lo que se repite: A4, metadatos, encabezado con la institución,
pie con fecha de generación y número de página, títulos, párrafos, pares
etiqueta–valor, tablas y un texto destacado (p. ej. el PIN del sobre).

Uso:

    doc = DocumentoPdf(
        "Ficha del subproducto",
        institucion=institucion_actual(conn),  # perfil de la entidad (core/pdf/institucion.py)
        generado_por=usuario.nombre,
    )
    doc.titulo("Ahorro a la vista")
    doc.campos([("Código", "AHO001-PN"), ("Estado", "Activo")])
    doc.tabla(["Canal", "Cupo diario"], [["Ventanilla", "$ 10.000,00"]])
    contenido = doc.contenido()

Fuentes: las base de PDF (Helvetica, Courier), que no se incrustan ni se descargan,
así el generador funciona sin internet. Solo cubren Latin-1: los caracteres de
fuera (rayas, comillas tipográficas, emojis) se cambian por un equivalente o por «?»
en vez de romper el documento. El texto nunca se registra en logs.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Literal

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from fpdf.fonts import FontFace

from app.core.pdf.institucion import Institucion

Alineacion = Literal["L", "C", "R", "J"]

# Ecuador no tiene horario de verano: UTC-5 todo el año
_ECUADOR = timezone(timedelta(hours=-5))
_EQUIVALENTES = str.maketrans(
    {
        "—": "-",  # raya
        "–": "-",  # semirraya
        "−": "-",  # menos
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "…": "...",
        "•": "-",  # viñeta
        " ": " ",  # espacio duro
        "→": "->",
    }
)
_GRIS = (110, 110, 110)
_AZUL = (31, 56, 100)


def texto_pdf(valor: Any) -> str:
    """El valor como texto que las fuentes base pueden dibujar (Latin-1)."""
    texto = "" if valor is None else str(valor)
    return texto.translate(_EQUIVALENTES).encode("latin-1", "replace").decode("latin-1")


class _Pdf(FPDF):
    """FPDF con encabezado y pie opcionales."""

    def __init__(
        self,
        titulo: str,
        institucion: Institucion | None,
        encabezado: bool,
        pie: bool,
        generado_por: str | None,
        zona: tzinfo,
        nombre_zona: str,
    ) -> None:
        super().__init__(format="A4")
        self._titulo_doc = titulo
        self._institucion = institucion
        self._con_encabezado = encabezado
        self._con_pie = pie
        fecha = datetime.now(zona).strftime("%d/%m/%Y %H:%M")
        quien = f" por {texto_pdf(generado_por)}" if generado_por else ""
        self._generado = f"Generado{quien} el {fecha} ({nombre_zona})"

    def header(self) -> None:
        if not self._con_encabezado:
            return
        nombre = self._institucion.nombre if self._institucion else ""
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_AZUL)
        self.cell(self.epw / 2, 6, texto_pdf(nombre), align="L")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*_GRIS)
        self.cell(
            0,
            6,
            texto_pdf(self._titulo_doc),
            align="R",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        if self._institucion and self._institucion.ruc:
            self.set_font("Helvetica", "", 8)
            self.cell(
                0,
                4,
                texto_pdf(f"RUC {self._institucion.ruc}"),
                align="L",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
        self.set_draw_color(*_AZUL)
        self.line(
            self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1
        )
        self.ln(6)
        self.set_text_color(0, 0, 0)

    def footer(self) -> None:
        if not self._con_pie:
            return
        self.set_y(-15)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_GRIS)
        self.cell(self.epw * 0.75, 6, self._generado, align="L")
        self.cell(0, 6, f"Página {self.page_no()} de {{nb}}", align="R")
        self.set_text_color(0, 0, 0)


class DocumentoPdf:
    """Documento A4 armado por bloques; `contenido()` devuelve los bytes del PDF."""

    def __init__(
        self,
        titulo: str,
        *,
        institucion: str | Institucion | None = None,
        generado_por: str | None = None,
        zona: tzinfo = _ECUADOR,
        nombre_zona: str = "hora de Ecuador",
        encabezado: bool = True,
        pie: bool = True,
        margenes: tuple[float, float, float] = (20, 20, 20),
        salto_automatico: bool = True,
    ) -> None:
        """`institucion`: el perfil de la entidad (`institucion_actual(conn)`) o solo su
        nombre. `generado_por`: nombre de quien lo pide, va en el pie con la fecha y hora
        en `zona` (la de la institución). `margenes` = (izquierda, arriba, derecha) en
        mm. Sin salto automático el contenido no pasa a otra página (hojas de una sola
        página, como el sobre)."""
        datos = (
            Institucion(nombre=institucion)
            if isinstance(institucion, str)
            else institucion
        )
        self._pdf = _Pdf(
            texto_pdf(titulo), datos, encabezado, pie, generado_por, zona, nombre_zona
        )
        self._pdf.set_title(texto_pdf(titulo))
        if datos:
            self._pdf.set_creator(texto_pdf(datos.nombre))
            self._pdf.set_author(texto_pdf(datos.nombre))
        izquierda, arriba, derecha = margenes
        self._pdf.set_margins(izquierda, arriba, derecha)
        self._pdf.set_auto_page_break(auto=salto_automatico, margin=20 if pie else 15)
        self._pdf.add_page()

    @property
    def pdf(self) -> FPDF:
        """El FPDF de fpdf2, para lo que esta clase no cubre (imágenes, códigos)."""
        return self._pdf

    def titulo(
        self, texto: str, *, tamano: float = 18, alineacion: Alineacion = "L"
    ) -> None:
        self._pdf.set_font("Helvetica", "B", tamano)
        self._pdf.multi_cell(
            0,
            tamano * 0.55,
            texto_pdf(texto),
            align=alineacion,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self._pdf.ln(3)

    def subtitulo(self, texto: str, *, alineacion: Alineacion = "L") -> None:
        self._pdf.ln(2)
        self._pdf.set_font("Helvetica", "B", 13)
        self._pdf.set_text_color(*_AZUL)
        self._pdf.multi_cell(
            0,
            7,
            texto_pdf(texto),
            align=alineacion,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self._pdf.set_text_color(0, 0, 0)
        self._pdf.ln(1)

    def parrafo(
        self,
        texto: str,
        *,
        tamano: float = 11,
        alineacion: Alineacion = "L",
        negrita: bool = False,
    ) -> None:
        self._pdf.set_font("Helvetica", "B" if negrita else "", tamano)
        self._pdf.multi_cell(
            0,
            tamano * 0.55,
            texto_pdf(texto),
            align=alineacion,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self._pdf.ln(2)

    def espacio(self, mm: float = 6) -> None:
        self._pdf.ln(mm)

    def campos(
        self, pares: Sequence[tuple[str, Any]], *, ancho_etiqueta: float = 55
    ) -> None:
        """Pares etiqueta–valor, uno por línea (datos de una ficha o comprobante)."""
        for etiqueta, valor in pares:
            self._pdf.set_font("Helvetica", "B", 10)
            self._pdf.cell(ancho_etiqueta, 6, texto_pdf(etiqueta))
            self._pdf.set_font("Helvetica", "", 10)
            self._pdf.multi_cell(
                0, 6, texto_pdf(valor), new_x=XPos.LMARGIN, new_y=YPos.NEXT
            )
        self._pdf.ln(2)

    def tabla(
        self,
        columnas: Sequence[str],
        filas: Sequence[Sequence[Any]],
        *,
        anchos: Sequence[float] | None = None,
        alineaciones: Sequence[Alineacion] | None = None,
    ) -> None:
        """Tabla con cabecera; se repite la cabecera si pasa a otra página. `anchos`
        son proporciones (p. ej. (3, 1, 1)); `alineaciones`, una por columna."""
        self._pdf.set_font("Helvetica", "", 9)
        cabecera = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=_AZUL)
        with self._pdf.table(
            col_widths=tuple(anchos) if anchos else None,
            text_align=tuple(alineaciones) if alineaciones else "LEFT",
            headings_style=cabecera,
            line_height=5.5,
            padding=1.5,
            repeat_headings=1,
        ) as tabla:
            fila_cabecera = tabla.row()
            for columna in columnas:
                fila_cabecera.cell(texto_pdf(columna))
            for fila in filas:
                nueva = tabla.row()
                for valor in fila:
                    nueva.cell(texto_pdf(valor))
        self._pdf.ln(3)

    def destacado(
        self,
        texto: str,
        *,
        etiqueta: str | None = None,
        tamano: float = 40,
        fuente: str = "Courier",
        desde_abajo_mm: float | None = None,
    ) -> None:
        """Texto grande y centrado (un PIN, un número de comprobante). Con
        `desde_abajo_mm` se ubica a esa distancia del borde inferior."""
        if desde_abajo_mm is not None:
            self._pdf.set_y(-desde_abajo_mm)
        if etiqueta:
            self._pdf.set_font("Helvetica", "", 12)
            self._pdf.cell(
                0,
                8,
                texto_pdf(etiqueta),
                align="C",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )
        self._pdf.set_font(fuente, "B", tamano)
        self._pdf.cell(
            0,
            tamano / 2,
            texto_pdf(texto),
            align="C",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    def contenido(self) -> bytes:
        return bytes(self._pdf.output())
