"""Política del correo principal de Clientes (E5-02)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from fastapi import HTTPException
from sqlalchemy import Connection
from sqlalchemy.exc import IntegrityError

from app.core.api.errors import problema, traducir_error_bd
from app.modules.parametros import general

PARAMETRO_DOMINIOS = "CLI_DOMINIOS_BLOQUEADOS"


@contextmanager
def traducir_conflicto() -> Iterator[None]:
    """Entrega el conflicto de negocio también al ejecutor de aprobaciones."""
    try:
        yield
    except IntegrityError as error:
        if "'UX_Cliente_EmailPrincipal'" in str(error.orig):
            raise traducir_error_bd(error) from None
        raise


def validar_dominio(conn: Connection, email: str, fecha: date) -> None:
    """Compara el dominio exacto contra la lista global vigente."""
    try:
        bloqueados = general.valor(conn, PARAMETRO_DOMINIOS, fecha)
    except HTTPException as error:
        if error.status_code not in (404, 422):
            raise
        bloqueados = None
    if not isinstance(bloqueados, list) or not all(
        isinstance(dominio, str) for dominio in bloqueados
    ):
        raise problema(
            503, "PARAMETRO_INVALIDO", "No se pudo verificar la política del correo."
        )
    if email.rsplit("@", 1)[-1].lower() in {
        dominio.strip().lower() for dominio in bloqueados
    }:
        raise problema(
            422, "DOMINIO_BLOQUEADO", "Usa un correo de un dominio permitido."
        )
