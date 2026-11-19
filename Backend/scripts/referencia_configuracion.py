"""Genera la referencia desde Settings, nunca desde valores del entorno/.env."""

import ast
import inspect
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.config.settings import Settings


def generar() -> str:
    codigo = inspect.getsource(Settings)
    lineas = codigo.splitlines()
    clase = ast.parse(codigo).body[0]
    assert isinstance(clase, ast.ClassDef)
    descripciones = {}
    for nodo in clase.body:
        if isinstance(nodo, ast.AnnAssign) and isinstance(nodo.target, ast.Name):
            comentarios = []
            i = nodo.lineno - 2
            while i >= 0 and lineas[i].strip().startswith("#"):
                comentarios.insert(0, lineas[i].strip().lstrip("# "))
                i -= 1
            descripciones[nodo.target.id] = " ".join(comentarios)
    salida = [
        "# Referencia de configuración",
        "",
        "Generada con `python Backend/scripts/referencia_configuracion.py`. No lee .env ni muestra valores desplegados.",
        "Los nombres siguen Settings; las variables se usan en MAYÚSCULAS. Vacío no habilita por sí solo la integración correspondiente.",
        "COOPERATIVA_NOMBRE y COOPERATIVA_SITIO_WEB son respaldos opcionales antes del alta de Entidad, sin marca de ejemplo. La ausencia de marca no bloquea la configuración inicial.",
        "",
        "| Variable | Tipo | Valor inicial de código | Descripción / contexto |",
        "|---|---|---|---|",
    ]
    for nombre, campo in Settings.model_fields.items():
        tipo = str(campo.annotation).replace("typing.", "").replace("|", "\\|")
        secreto = "SecretStr" in tipo
        inicial = (
            "Secreto; nunca se documenta su valor" if secreto else repr(campo.default)
        )
        if campo.is_required():
            inicial = "Obligatoria; sin valor inicial"
        elif campo.default_factory is not None and not secreto:
            inicial = "Factoría " + getattr(
                campo.default_factory, "__name__", "configurada"
            )
        descripcion = (
            campo.description
            or descripciones.get(nombre)
            or "Parámetro " + nombre.replace("_", " ")
        )
        salida.append(
            f"| `{nombre.upper()}` | `{tipo}` | `{inicial}` | {descripcion.replace('|', '/')} |"
        )
    return "\n".join(salida) + "\n"


if __name__ == "__main__":
    destino = BACKEND / "docs" / "configuracion-generada.md"
    destino.write_text(generar(), encoding="utf-8")
    print(
        f"Referencia generada: {len(Settings.model_fields)} variables en {destino.name}"
    )
