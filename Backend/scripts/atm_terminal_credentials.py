"""Aprovisionamiento local fuera del repositorio; nunca imprime la credencial.

La entrega se escribe una sola vez en un archivo privado indicado por el operador.
No conecta con Azure, terminales o SQL. El registro contiene únicamente hashes.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Permite ejecutar desde la raíz, sin instalar el proyecto.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.atm.terminal_auth import (
    MAX_SOLAPE,
    RegistroCredencial,
    validar_registro,
)

_REPO = Path(__file__).resolve().parents[2]


def _externo(path: Path) -> Path:
    destino = path.resolve()
    if destino.is_relative_to(_REPO):
        raise ValueError("El material debe permanecer fuera del repositorio")
    return destino


def actualizar_registro(
    ruta: Path,
    accion: str,
    *,
    codigo: str | None = None,
    usuario: int | None = None,
    vence: datetime | None = None,
    entrega: Path | None = None,
    credential_id: str | None = None,
) -> None:
    ruta = _externo(ruta)
    entrega = _externo(entrega) if entrega is not None else None
    if entrega == ruta:
        raise ValueError("Destinos inválidos")
    bloqueo = ruta.with_name(ruta.name + ".lock")
    fd = os.open(bloqueo, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    temporal = ruta.with_name(ruta.name + ".tmp-" + uuid.uuid4().hex)
    creada = False
    material: str | None = None
    try:
        registros = validar_registro(ruta.read_bytes()) if ruta.exists() else {}
        ahora = datetime.now(UTC)
        if accion == "revoke":
            if credential_id not in registros:
                raise ValueError("Credencial desconocida")
            registros[credential_id].enabled = False
        else:
            if (
                accion not in {"issue", "rotate"}
                or codigo is None
                or re.fullmatch(r"[A-Za-z0-9_-]{8}", codigo) is None
                or usuario is None
                or usuario <= 0
                or vence is None
                or vence.tzinfo is None
                or vence <= ahora
                or entrega is None
            ):
                raise ValueError("Parámetros inválidos")
            activas = [
                r
                for r in registros.values()
                if r.codigo_atm == codigo and r.enabled and r.expires_at > ahora
            ]
            if (accion == "issue" and activas) or (
                accion == "rotate" and len(activas) != 1
            ):
                raise ValueError("Use la operación de rotación correcta")
            if accion == "rotate":
                activas[0].expires_at = min(activas[0].expires_at, ahora + MAX_SOLAPE)
            nuevo_id = secrets.token_urlsafe(12)
            secreto = (
                base64.urlsafe_b64encode(secrets.token_bytes(32))
                .rstrip(b"=")
                .decode("ascii")
            )
            registros[nuevo_id] = RegistroCredencial(
                codigoATM=codigo,
                sha256=hashlib.sha256(secreto.encode()).hexdigest(),
                enabled=True,
                notBefore=ahora,
                expiresAt=vence,
                auditUserId=usuario,
            )
            material = nuevo_id + "." + secreto + "\n"
        contenido = json.dumps(
            {k: v.model_dump(mode="json", by_alias=True) for k, v in registros.items()}
        ).encode()
        validar_registro(contenido)
        if material is not None and entrega is not None:
            fd = os.open(entrega, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            creada = True
            with os.fdopen(fd, "w", encoding="utf-8") as archivo:
                archivo.write(material)
        fd = os.open(temporal, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as archivo:
            archivo.write(contenido)
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, ruta)
    except Exception:
        if creada and entrega is not None:
            entrega.unlink(missing_ok=True)
        raise
    finally:
        temporal.unlink(missing_ok=True)
        bloqueo.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["issue", "rotate", "revoke"])
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--codigo-atm")
    parser.add_argument("--audit-user-id", type=int)
    parser.add_argument("--expires-at", help="ISO 8601 con zona horaria")
    parser.add_argument("--credential-out", type=Path)
    parser.add_argument("--credential-id")
    args = parser.parse_args()
    try:
        actualizar_registro(
            args.registry,
            args.action,
            codigo=args.codigo_atm,
            usuario=args.audit_user_id,
            vence=datetime.fromisoformat(args.expires_at) if args.expires_at else None,
            entrega=args.credential_out,
            credential_id=args.credential_id,
        )
    except (OSError, ValueError):
        parser.exit(
            2, "No se pudo actualizar el registro. Revise parámetros y permisos.\n"
        )
    print("Registro actualizado. No se muestran credenciales.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
