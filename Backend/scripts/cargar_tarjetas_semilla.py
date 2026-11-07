"""Carga PAN ficticio y PIN de prueba en las tarjetas existentes (solo desarrollo y pruebas).

Las tarjetas semilla se crearon antes del HSM: no tienen un PAN recuperable ni un PIN
Offset. Este script, con las mismas funciones que TAR-01 y TAR-05:

1. Genera un PAN ficticio que conserva la máscara actual (BIN, últimos 4 dígitos y
   Luhn válido), actualiza HashNumeroTarjeta (SHA-256, como TAR-01) y custodia el PAN
   cifrado por el HSM en Pruebas.PanFicticio.
2. Asigna el PIN de prueba con la lógica de TAR-05 (PIN Block ISO-4 + IBM 3624 PIN
   Offset), en las tarjetas que se indiquen.

Es idempotente: no toca un PAN ya custodiado ni un PIN ya asignado con Offset. Nunca
imprime PAN, PIN, PIN Block ni Offset. No corre en producción.

Uso, desde Backend/ (PINs de 4 dígitos, no triviales, solo para pruebas):
    .venv/Scripts/python scripts/cargar_tarjetas_semilla.py --usuario 8 \
        --pines '{"1": "4826", "3": "7392"}'
"""

import argparse
import hashlib
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import SecretStr
from sqlalchemy import Connection, text

from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.core.security.hsm import Hsm, es_pin_debil, obtener_hsm
from app.modules.tarjetas import repository, service

_IP = "script-semilla"


def pan_con_mascara(mascara: str) -> str:
    """PAN de 16 dígitos con el mismo BIN y los mismos últimos 4 que la máscara."""
    digitos = mascara.replace(" ", "")
    prefijo, sufijo = digitos[:6], digitos[-4:]
    while True:
        medio = "".join(secrets.choice("0123456789") for _ in range(6))
        parcial = prefijo + medio + sufijo[:-1]
        if service._digito_luhn(parcial) == sufijo[-1]:
            return parcial + sufijo[-1]


def cargar_pan(coop: Connection, seg: Connection, hsm: Hsm, fila: dict) -> str:
    id_tarjeta = fila["id"]
    if repository.obtener_pan_ficticio(seg, id_tarjeta) is not None:
        return "PAN ya custodiado"
    pan = pan_con_mascara(fila["mascara"])
    if service._enmascarar(pan) != fila["mascara"]:
        raise RuntimeError("El PAN generado no conserva la máscara")
    cifrado, referencia = hsm.cifrar_pan(pan, id_tarjeta)
    coop.execute(
        text(
            "UPDATE Tarjeta.Tarjeta SET HashNumeroTarjeta = :hash WHERE IdTarjeta = :id"
        ),
        {"hash": hashlib.sha256(pan.encode()).digest(), "id": id_tarjeta},
    )
    del pan
    repository.guardar_pan_ficticio(seg, id_tarjeta, cifrado, referencia)
    # Mismo orden que TAR-01: primero el PAN, luego la tarjeta
    seg.commit()
    coop.commit()
    return "PAN ficticio custodiado"


def reiniciar_pin_sin_offset(
    coop: Connection, seg: Connection, id_tarjeta: int
) -> None:
    """Un PIN marcado como asignado sin Offset (Argon2 o semilla) no sirve: se limpia
    para asignarlo con TAR-05.
    """
    seg.execute(
        text(
            """
            UPDATE Tarjetas.TarjetaPIN
            SET TienePINAsignado = 0, FechaAsignacion = NULL, IntentosFallidos = 0
            WHERE ID_Tarjeta = :id AND PINOffset IS NULL
            """
        ),
        {"id": id_tarjeta},
    )
    if (
        seg.execute(
            text("SELECT COL_LENGTH('Tarjetas.TarjetaPIN', 'HashPIN')")
        ).scalar()
        is not None
    ):
        seg.execute(
            text(
                "UPDATE Tarjetas.TarjetaPIN SET HashPIN = NULL WHERE ID_Tarjeta = :id"
            ),
            {"id": id_tarjeta},
        )
    coop.execute(
        text("UPDATE Tarjeta.Tarjeta SET PinAsignado = 0 WHERE IdTarjeta = :id"),
        {"id": id_tarjeta},
    )
    seg.commit()
    coop.commit()


def cargar_pin(
    coop: Connection, seg: Connection, hsm: Hsm, id_tarjeta: int, pin: str, usuario: int
) -> str:
    estado = repository.obtener_estado_pin(seg, id_tarjeta)
    seg.rollback()
    if estado is not None and estado["confirmado"] and estado["tiene_offset"]:
        return "PIN ya asignado con Offset"
    if estado is None or not estado["tiene_offset"]:
        reiniciar_pin_sin_offset(coop, seg, id_tarjeta)
    pan = service.pan_de_prueba(seg, id_tarjeta, hsm)
    bloque, referencia = hsm.construir_pin_block(pin, pan)
    del pan
    service.asignar_pin(
        coop, seg, id_tarjeta, SecretStr(bloque), referencia, usuario, _IP
    )
    return "PIN asignado (ISO-4 + IBM 3624)"


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--usuario", type=int, required=True, help="UsuarioID auditor")
    parser.add_argument(
        "--pines", default="{}", help='JSON {"idTarjeta": "PIN"}; PIN de prueba'
    )
    args = parser.parse_args()
    if get_settings().app_env == "production":
        sys.exit("No se ejecuta en producción.")
    pines = {int(k): v for k, v in json.loads(args.pines).items()}
    if any(es_pin_debil(p) for p in pines.values()):
        sys.exit("Hay un PIN débil o que no tiene 4 dígitos.")

    hsm = obtener_hsm()
    with (
        get_engine("cooperativa").connect() as coop,
        get_engine("seguridad").connect() as seg,
    ):
        filas = [
            {"id": r[0], "mascara": r[1], "estado": r[2]}
            for r in coop.execute(
                text(
                    "SELECT IdTarjeta, RTRIM(NumeroEnmascarado), Estado "
                    "FROM Tarjeta.Tarjeta ORDER BY IdTarjeta"
                )
            )
        ]
        coop.rollback()
        for fila in filas:
            print(
                f"tarjeta {fila['id']} ({fila['estado']}): {cargar_pan(coop, seg, hsm, fila)}"
            )
        for id_tarjeta, pin in pines.items():
            resultado = cargar_pin(coop, seg, hsm, id_tarjeta, pin, args.usuario)
            print(f"tarjeta {id_tarjeta}: {resultado}")


if __name__ == "__main__":
    main()
