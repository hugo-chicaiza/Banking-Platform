"""Comando de migraciones (E0-01). **Apagado por defecto** (`MIGRACIONES_HABILITADAS=false`).

    python -m app.core.migraciones estado  --base cooperativa
    python -m app.core.migraciones aplicar --base seguridad [--marcar-linea-base]

La conexión es la cadena ODBC administrativa `MIGRACIONES_ODBC_COOPERATIVA` /
`MIGRACIONES_ODBC_SEGURIDAD` (secreto aparte; nunca la de la aplicación). El ensayo en una
copia restaurada es E0-02.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import URL, create_engine, text

from app.core.config.settings import get_settings
from app.core.migraciones.archivos import descubrir
from app.core.migraciones.ejecutor import Ejecutor, MigracionRechazada

CARPETAS = Path(__file__).resolve().parents[3] / "migrations"


class ConexionSql:
    """Adaptador de SQLAlchemy al protocolo `Sql` del ejecutor."""

    def __init__(self, odbc: str) -> None:
        url = URL.create("mssql+pyodbc", query={"odbc_connect": odbc})
        self._conn = create_engine(url).connect()

    def valor(self, sql: str, **params: object) -> object:
        return self._conn.execute(text(sql), params).scalar()

    def filas(self, sql: str, **params: object) -> list[tuple]:
        return [tuple(f) for f in self._conn.execute(text(sql), params)]

    def ejecutar(self, sql: str, **params: object) -> None:
        if params:
            self._conn.execute(text(sql), params)
        else:  # un lote de un archivo: tal cual, sin interpretar «:nombre» como parámetro
            self._conn.exec_driver_sql(sql)

    def confirmar(self) -> None:
        self._conn.commit()

    def revertir(self) -> None:
        self._conn.rollback()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.core.migraciones")
    ap.add_argument("accion", choices=["estado", "aplicar"])
    ap.add_argument("--base", choices=["cooperativa", "seguridad"], required=True)
    ap.add_argument("--marcar-linea-base", action="store_true")
    a = ap.parse_args(argv)
    s = get_settings()
    odbc = getattr(s, f"migraciones_odbc_{a.base}").get_secret_value()
    if not odbc:
        print(
            f"falta MIGRACIONES_ODBC_{a.base.upper()} (cadena del login administrativo)",
            file=sys.stderr,
        )
        return 2
    ejecutor = Ejecutor(
        ConexionSql(odbc),
        base=a.base,
        nombre_base=getattr(s, f"{a.base}_db_name"),
        login_aplicacion=getattr(s, f"{a.base}_db_user"),
        migraciones=descubrir(CARPETAS / a.base),
        habilitado=s.migraciones_habilitadas,
    )
    try:
        if a.accion == "estado":
            e = ejecutor.estado()
            print(
                f"{a.base}: bitácora {'instalada' if e.bitacora_instalada else 'sin instalar'} · "
                f"aplicadas {len(e.aplicadas)} · pendientes {len(e.pendientes)} · alteradas {len(e.alteradas)}"
            )
            for nombre in e.pendientes:
                print(f"  pendiente  {nombre}")
            for nombre in e.alteradas:
                print(f"  ALTERADA   {nombre}")
            for nombre in e.desconocidas:
                print(f"  sin archivo {nombre}")
            return 1 if e.alteradas else 0
        for nombre in ejecutor.aplicar(marcar_linea_base=a.marcar_linea_base):
            print(f"aplicada {nombre}")
        return 0
    except MigracionRechazada as exc:
        print(f"RECHAZADO: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
