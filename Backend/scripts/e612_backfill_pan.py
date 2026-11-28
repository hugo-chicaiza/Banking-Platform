"""Backfill seguro E6-12: recalcula HMAC y copia el PAN cifrado.

No elimina datos legacy ni ejecuta SQL automáticamente. Requiere --apply para
escribir y --retirar-pruebas solamente después de una verificación aprobada.
Nunca imprime PAN, PIN, claves ni huellas.
"""

import argparse
import hmac
import socket
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.core.config.settings import Settings, get_settings
from app.core.database.db import get_engine
from app.core.security.hsm import (
    REFERENCIA_HMAC_PAN,
    VERSION_HMAC_PAN,
    VERSION_PAN,
    ErrorHsm,
    Hsm,
    obtener_hsm,
)


def _host_local(servidor: str) -> bool:
    host = servidor.strip().casefold().removeprefix("tcp:")
    host = host.split(",", 1)[0].split("\\", 1)[0].strip("[]")
    equipos = {
        "localhost",
        "127.0.0.1",
        "::1",
        ".",
        "(local)",
        "(localdb)",
        socket.gethostname().casefold(),
        socket.getfqdn().casefold(),
    }
    return bool(host) and host in equipos


def validar_destino_local(settings: Settings) -> None:
    if settings.app_env != "development" or not all(
        _host_local(servidor)
        for servidor in (
            settings.cooperativa_db_server,
            settings.seguridad_db_server,
        )
    ):
        raise RuntimeError(
            "El backfill E6-12 solo se permite contra SQL Server local en development"
        )


def recalcular_por_tarjeta(
    conn_coop: Connection, conn_seg: Connection, hsm: Hsm, aplicar: bool
) -> int:
    legado = conn_seg.execute(
        text(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA='Pruebas' AND TABLE_NAME='PanFicticio'"
        )
    ).first()
    filas_nuevas = (
        conn_seg.execute(
            text(
                """
        SELECT IdTarjeta, NumeroCifrado, ReferenciaClave, VersionClave
        FROM Tarjetas.TarjetaNumeroCifrado
        """
            )
        )
        .mappings()
        .all()
    )
    por_id: dict[int, dict[str, Any]] = {}
    for fila in filas_nuevas:
        por_id[int(fila["IdTarjeta"])] = {
            "IdTarjeta": int(fila["IdTarjeta"]),
            "NumeroCifrado": bytes(fila["NumeroCifrado"]),
            "ReferenciaClave": fila["ReferenciaClave"],
            "VersionClave": int(fila["VersionClave"]),
        }

    if legado is not None:
        filas_legacy = (
            conn_seg.execute(
                text(
                    """
            SELECT IdTarjeta, PanCifrado AS NumeroCifrado, ReferenciaClave
            FROM Pruebas.PanFicticio
            """
                )
            )
            .mappings()
            .all()
        )
        for fila in filas_legacy:
            id_tarjeta = int(fila["IdTarjeta"])
            legado_normalizado = {
                "IdTarjeta": id_tarjeta,
                "NumeroCifrado": bytes(fila["NumeroCifrado"]),
                "ReferenciaClave": fila["ReferenciaClave"],
                "VersionClave": VERSION_PAN,
            }
            existente = por_id.get(id_tarjeta)
            if existente is not None and existente != legado_normalizado:
                raise RuntimeError("Las custodias legacy y nueva no coinciden")
            por_id[id_tarjeta] = legado_normalizado

    procesadas = 0

    for fila in por_id.values():
        id_tarjeta = int(fila["IdTarjeta"])
        token = conn_coop.execute(
            text("SELECT TokenTarjeta FROM Tarjeta.Tarjeta WHERE IdTarjeta=:id"),
            {"id": id_tarjeta},
        ).scalar_one_or_none()
        if token is None:
            raise RuntimeError("La tarjeta destino no existe")

        pan = hsm.descifrar_pan(
            bytes(fila["NumeroCifrado"]),
            fila["ReferenciaClave"],
            id_tarjeta,
            version=int(fila["VersionClave"]),
        )
        huella = hsm.huella_pan(pan)
        del pan

        if aplicar:
            conn_seg.execute(
                text(
                    """
                    MERGE Tarjetas.TarjetaNumeroCifrado WITH (HOLDLOCK) AS destino
                    USING (SELECT :id AS IdTarjeta) AS origen
                    ON destino.IdTarjeta=origen.IdTarjeta
                    WHEN MATCHED THEN UPDATE SET
                        TokenTarjeta=:token, NumeroCifrado=:cifrado,
                        ReferenciaClave=:referencia, VersionClave=:version
                    WHEN NOT MATCHED THEN INSERT
                        (IdTarjeta, TokenTarjeta, NumeroCifrado, ReferenciaClave, VersionClave)
                    VALUES (:id, :token, :cifrado, :referencia, :version);
                    """
                ),
                {
                    "id": id_tarjeta,
                    "token": str(token),
                    "cifrado": bytes(fila["NumeroCifrado"]),
                    "referencia": fila["ReferenciaClave"],
                    "version": int(fila["VersionClave"]),
                },
            )
            conn_coop.execute(
                text(
                    """
                    UPDATE Tarjeta.Tarjeta
                    SET HashNumeroTarjeta=:huella, VersionClaveHuella=:version,
                        ReferenciaClaveHuella=:referencia
                    WHERE IdTarjeta=:id
                    """
                ),
                {
                    "huella": huella,
                    "id": id_tarjeta,
                    "version": VERSION_HMAC_PAN,
                    "referencia": REFERENCIA_HMAC_PAN,
                },
            )
        procesadas += 1
    return procesadas


def verificar_backfill(conn_coop: Connection, conn_seg: Connection, hsm: Hsm) -> None:
    tarjetas = (
        conn_coop.execute(
            text(
                """
            SELECT IdTarjeta, TokenTarjeta, HashNumeroTarjeta, VersionClaveHuella,
                   ReferenciaClaveHuella
            FROM Tarjeta.Tarjeta
            """
            )
        )
        .mappings()
        .all()
    )
    custodias = (
        conn_seg.execute(
            text(
                """
            SELECT IdTarjeta, TokenTarjeta, NumeroCifrado, ReferenciaClave, VersionClave
            FROM Tarjetas.TarjetaNumeroCifrado
            """
            )
        )
        .mappings()
        .all()
    )
    por_id = {int(fila["IdTarjeta"]): fila for fila in custodias}

    if len(por_id) != len(custodias) or set(por_id) != {
        int(fila["IdTarjeta"]) for fila in tarjetas
    }:
        raise RuntimeError("La verificación de cobertura de PAN no pasó")

    for tarjeta in tarjetas:
        id_tarjeta = int(tarjeta["IdTarjeta"])
        custodia = por_id[id_tarjeta]
        if (
            tarjeta["TokenTarjeta"] != custodia["TokenTarjeta"]
            or tarjeta["HashNumeroTarjeta"] is None
            or int(tarjeta["VersionClaveHuella"]) != VERSION_HMAC_PAN
            or tarjeta["ReferenciaClaveHuella"] != REFERENCIA_HMAC_PAN
            or int(custodia["VersionClave"]) != VERSION_PAN
        ):
            raise RuntimeError("La verificación de metadatos de PAN no pasó")

        pan = hsm.descifrar_pan(
            bytes(custodia["NumeroCifrado"]),
            custodia["ReferenciaClave"],
            id_tarjeta,
            version=int(custodia["VersionClave"]),
        )
        try:
            huella = hsm.huella_pan(pan)
        finally:
            del pan
        if not hmac.compare_digest(huella, bytes(tarjeta["HashNumeroTarjeta"])):
            raise RuntimeError("La verificación de huella PAN no pasó")


def retirar_pruebas(conn_seg) -> None:
    conn_seg.execute(
        text(
            """
        IF OBJECT_ID(N'Pruebas.PanFicticio', N'U') IS NOT NULL
            DROP TABLE Pruebas.PanFicticio;
        IF EXISTS (
            SELECT 1 FROM sys.schemas AS s
            JOIN sys.objects AS o ON o.schema_id = s.schema_id
            WHERE s.name = N'Pruebas'
        )
            THROW 57721, N'El esquema legacy conserva objetos; retiro cancelado.', 1;
        IF EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'Pruebas')
            DROP SCHEMA Pruebas;
        """
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirmar-local",
        action="store_true",
        help="confirma explícitamente que la escritura es solo en SQL Server local",
    )
    parser.add_argument("--retirar-pruebas", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    validar_destino_local(settings)
    if args.apply and not args.confirmar_local:
        raise RuntimeError("--apply requiere --confirmar-local")

    try:
        hsm = obtener_hsm()
    except ErrorHsm as exc:
        raise RuntimeError("Clave HSM/HMAC de PAN no disponible") from exc

    try:
        with (
            get_engine("cooperativa").connect() as coop,
            get_engine("seguridad").connect() as seg,
        ):
            filas = recalcular_por_tarjeta(coop, seg, hsm, args.apply)
            if args.apply:
                coop.commit()
                seg.commit()
            print(f"Tarjetas procesadas: {filas}")
            if args.retirar_pruebas:
                if not args.apply:
                    raise RuntimeError("--retirar-pruebas exige --apply")
                verificar_backfill(coop, seg, hsm)
                retirar_pruebas(seg)
                seg.commit()
                print("Esquema legacy Pruebas retirado")
    except SQLAlchemyError:
        raise RuntimeError(
            "Falló el backfill E6-12; no se muestran datos sensibles"
        ) from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
