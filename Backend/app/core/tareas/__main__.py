"""Comando de tareas programadas (E0-06).

    python -m app.core.tareas ejecutar <codigo>
    python -m app.core.tareas ejecutar <codigo> --por <usuario> --motivo "<por qué>"   # manual

Sale 0 si la tarea corrió (o si otra instancia ya la estaba corriendo: no es un error),
1 si falló o se rechazó. No imprime SQL, parámetros ni datos personales.
"""

import argparse
import json
import sys

import pyodbc


def main(argv: list[str] | None = None) -> int:
    from app.core.tareas.registro import APROBACIONES, TAREAS, codigos

    ap = argparse.ArgumentParser(prog="python -m app.core.tareas")
    ap.add_argument("accion", choices=["ejecutar"])
    ap.add_argument("codigo", choices=codigos())
    ap.add_argument(
        "--por", default=None, help="quién la lanza a mano (sujeto de WorkOS o usuario)"
    )
    ap.add_argument("--motivo", default=None)
    a = ap.parse_args(argv)
    # Antes de la primera conexión: sin el pool de ODBC, cerrar termina de verdad la sesión
    # (y libera sus bloqueos de aplicación). ATM-06 lo exige.
    pyodbc.pooling = False
    from app.core.config.logs import configurar_logging
    from app.core.config.settings import get_settings
    from app.core.tareas.ejecutor import TareaEnCurso, TareaRechazada, ejecutar

    s = get_settings()
    configurar_logging(s.log_level, s.log_formato)
    try:
        if a.codigo in APROBACIONES:
            from app.integrations.workos_client import get_organizacion_id
            from app.modules.aprobaciones.manejadores import registro_inicial
            from app.modules.aprobaciones.motores import motor
            from app.modules.aprobaciones.servicio import Servicio
            from app.modules.aprobaciones.tareas import (
                ejecutar as ejecutar_aprobaciones,
            )

            servicio = Servicio(
                motor("seguridad"), motor("cooperativa"), registro_inicial()
            )
            conteo = ejecutar_aprobaciones(
                servicio, get_organizacion_id(), a.codigo, a.por, a.motivo
            )
        else:
            conteo = ejecutar(TAREAS[a.codigo], por=a.por, motivo=a.motivo)
    except TareaEnCurso:
        print(json.dumps({"codigo": a.codigo, "resultado": "EN_CURSO"}))
        return 0
    except TareaRechazada as exc:
        print(
            json.dumps(
                {"codigo": a.codigo, "resultado": "RECHAZADA", "motivo": str(exc)}
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - sin filtrar detalles del error
        print(
            json.dumps(
                {"codigo": a.codigo, "resultado": "FALLIDA", "tipo": type(exc).__name__}
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "codigo": a.codigo,
                "procesados": conteo.procesados,
                "modificados": conteo.modificados,
                "errores": conteo.errores,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
