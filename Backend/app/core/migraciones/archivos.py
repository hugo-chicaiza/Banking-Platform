"""Archivos de migración (E0-01): nombre, orden, suma SHA-256 y lotes.

Carpetas `Backend/migrations/cooperativa/` y `Backend/migrations/seguridad/`. Nombre
`AAAAMMDDHHMM_<modulo>_<descripcion>.up.sql` (y su `.down.sql`, que el ejecutor nunca
aplica solo). `000000000000_linea_base.up.sql` es la migración cero de cada base.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

NOMBRE = re.compile(r"^(\d{12})_[a-z0-9]+(?:_[a-z0-9]+)*\.up\.sql$")
LINEA_BASE = "000000000000_linea_base.up.sql"
_GO = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE | re.MULTILINE)


class ArchivoInvalido(ValueError):
    """Un archivo de la carpeta no sigue la convención de nombres."""


@dataclass(frozen=True)
class Migracion:
    archivo: str
    sha256: bytes
    contenido: str

    @property
    def es_linea_base(self) -> bool:
        return self.archivo == LINEA_BASE


def descubrir(carpeta: Path) -> list[Migracion]:
    """Las migraciones `.up.sql` en orden. Un `.sql` con otro nombre detiene todo: un
    archivo mal nombrado podría quedar sin aplicar sin que nadie lo note."""
    migraciones: list[Migracion] = []
    for ruta in sorted(carpeta.glob("*.sql")):
        if ruta.name.endswith(".down.sql"):
            continue
        if not NOMBRE.fullmatch(ruta.name):
            raise ArchivoInvalido(
                f"{ruta.name}: se espera AAAAMMDDHHMM_<modulo>_<descripcion>.up.sql"
            )
        datos = ruta.read_bytes()
        migraciones.append(
            Migracion(
                archivo=ruta.name,
                sha256=hashlib.sha256(datos).digest(),
                contenido=datos.decode("utf-8-sig"),
            )
        )
    sellos = [m.archivo[:12] for m in migraciones]
    repetidos = sorted({s for s in sellos if sellos.count(s) > 1})
    if repetidos:
        raise ArchivoInvalido(f"sellos de fecha repetidos: {', '.join(repetidos)}")
    return migraciones


def lotes(sql: str) -> list[str]:
    """El guion partido en lotes por las líneas `GO` (separador de sqlcmd/SSMS)."""
    return [lote.strip() for lote in _GO.split(sql) if lote.strip()]
