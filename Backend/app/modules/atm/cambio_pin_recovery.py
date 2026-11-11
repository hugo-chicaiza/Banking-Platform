"""Reconciliacion interna ATM-06, sin ruta HTTP ni excepciones de autenticacion.

Uso por un operador autorizado con acceso a la configuracion del backend:
python -m app.modules.atm.cambio_pin_recovery --operacion UUID

No imprime excepciones SQL, sesiones ni material criptografico. No vuelve a
verificar/generar PIN: solo recupera una operacion persistida. No ejecutar sobre
un destino distinto del expresamente autorizado por el operador.
"""

import argparse
from uuid import UUID

import pyodbc
from fastapi import HTTPException

from app.core.config.logs import configurar_logging
from app.core.config.settings import get_settings
from app.modules.atm.cambio_pin_service import recuperar_cambio_pin


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconciliar una operacion ATM-06 persistida"
    )
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--operacion", type=UUID)
    modo.add_argument("--pendientes", action="store_true")
    args = parser.parse_args()
    # Solo este proceso independiente. Debe hacerse ANTES de la primera conexion:
    # SQLAlchemy invalida conexiones, pero el pool inferior de ODBC puede conservar
    # una sesion con applocks. Sin ese pool, close termina realmente la sesion.
    pyodbc.pooling = False
    try:
        configurar_logging(get_settings().log_level)
    except ValueError:
        print("ATM06_RECOVERY_ALERT reason=INVALID_CONFIGURATION")
        return 1
    if args.pendientes:
        from app.modules.atm.cambio_pin_worker import ejecutar_configurado

        try:
            return ejecutar_configurado()
        except ValueError:
            print("ATM06_RECOVERY_ALERT reason=INVALID_CONFIGURATION")
            return 1
    from app.modules.atm.cambio_pin_worker import observar

    auditado = observar(
        str(args.operacion), "ATM06_REC_MANUAL_INICIO", "INICIO", ejecutor="MANUAL"
    )
    try:
        recuperar_cambio_pin(str(args.operacion))
    except HTTPException:
        observar(
            str(args.operacion),
            "ATM06_REC_MANUAL_FALLO",
            "NO_CONFIRMADO",
            ejecutor="MANUAL",
        )
        print(
            "No se pudo confirmar la operacion; conservar las restricciones y revisar la evidencia."
        )
        return 1
    except Exception:  # noqa: BLE001 -- no filtrar datos de errores inesperados del CLI.
        print("ATM06_RECOVERY_ALERT reason=MANUAL_UNEXPECTED_FAILURE")
        return 1
    auditado &= observar(
        str(args.operacion), "ATM06_REC_MANUAL_OK", "OK", ejecutor="MANUAL"
    )
    print("Operacion confirmada mediante evidencia persistida.")
    return 0 if auditado else 1


if __name__ == "__main__":
    raise SystemExit(main())
