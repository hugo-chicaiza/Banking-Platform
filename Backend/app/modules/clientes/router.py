from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Connection

from app.core.db import cooperativa
from app.core.security import require_auth
from app.modules.clientes import service
from app.modules.clientes.schemas import (
    Cliente,
    ClienteCreate,
    TipoDocumento,
    ValidacionIdentificacion,
)

router = APIRouter(
    prefix="/clientes",
    tags=["clientes"],
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]

# ---------------------------------------------------------------------------
# CLI-01 · GET /api/v1/clientes/validar-identificacion
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN
# TODO(F-03): restringir por rol cuando require_auth valide el JWT.


@router.get("/validar-identificacion", response_model=ValidacionIdentificacion)
def validar_identificacion(
    tipo_documento: Annotated[
        TipoDocumento,
        Query(
            description="Tipo de documento: C (Cédula), R (RUC), P (Pasaporte)",
            alias="tipoDocumento",
        ),
    ],
    identificacion: Annotated[
        str,
        Query(
            description="Número de documento de identificación",
            min_length=1,
            max_length=20,
        ),
    ],
    conn: Db,
) -> Any:
    """Valida formato del documento (Módulo 10 para Cédula/RUC) y si ya existe (CLI-01 / C-02)."""
    return service.validar_identificacion(conn, tipo_documento, identificacion)


# ---------------------------------------------------------------------------
# CLI-02 · POST /api/v1/clientes
# ---------------------------------------------------------------------------
# Roles: ASESOR, ADMIN
# TODO(F-03): restringir por rol y extraer creado_por del token JWT.


@router.post("", response_model=Cliente, status_code=201)
def registrar_cliente(
    payload: ClienteCreate,
    request: Request,
    conn: Db,
) -> Any:
    """Registra un cliente (Natural o Jurídico) con su dirección principal (CLI-02 / C-01).

    **Nota de autenticación (F-03):** `require_auth()` todavía no valida el
    JWT de WorkOS. El `creado_por` se fija temporalmente a 1; cuando F-03
    esté implementado se leerá del sub/id del token.
    """
    creado_por = 1

    # Obtener IP del cliente para auditoría en ClientesHis
    direccion_ip = request.headers.get("x-forwarded-for")
    if direccion_ip:
        direccion_ip = direccion_ip.split(",")[0].strip()
    elif request.client:
        direccion_ip = request.client.host
    else:
        direccion_ip = "127.0.0.1"

    return service.registrar_cliente(conn, payload, creado_por, direccion_ip)
