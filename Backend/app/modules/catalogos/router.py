from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from app.core.db import cooperativa
from app.core.security import require_auth
from app.modules.catalogos import repository
from app.modules.catalogos.schemas import (
    TIPOS_PRODUCTO,
    Agencia,
    Denominacion,
    Pais,
    ProblemDetails,
    Producto,
    TipoMovimientoCaja,
)

# Catálogos de solo lectura: sin service.py porque no hay reglas de negocio
router = APIRouter(
    prefix="/catalogos", tags=["catalogos"], dependencies=[Depends(require_auth)]
)
Db = Annotated[Connection, Depends(cooperativa)]

PROBLEM_DETAILS_SCHEMA = {
    "type": "object",
    "required": [
        "type",
        "title",
        "status",
        "code",
        "detail",
        "traceId",
        "errors",
    ],
    "properties": {
        "type": {"type": "string"},
        "title": {"type": "string"},
        "status": {"type": "integer"},
        "code": {"type": "string"},
        "detail": {"type": "string"},
        "traceId": {"type": "string"},
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["field", "message"],
                "properties": {
                    "field": {"type": "string"},
                    "message": {"type": "string"},
                },
            },
        },
    },
}


@router.get("/paises", response_model=list[Pais])
def listar_paises(conn: Db) -> Any:
    return repository.listar_paises(conn)


@router.get("/denominaciones", response_model=list[Denominacion])
def listar_denominaciones(conn: Db) -> Any:
    return repository.listar_denominaciones(conn)


@router.get("/tipos-movimiento-caja", response_model=list[TipoMovimientoCaja])
def listar_tipos_movimiento_caja(conn: Db) -> Any:
    return repository.listar_tipos_movimiento_caja(conn)


@router.get("/agencias", response_model=list[Agencia])
def listar_agencias(conn: Db) -> Any:
    return repository.listar_agencias(conn)


@router.get(
    "/productos",
    response_model=list[Producto],
    responses={
        400: {
            "description": "El parámetro tipo no pertenece al enum permitido.",
            "content": {"application/problem+json": {"schema": PROBLEM_DETAILS_SCHEMA}},
        },
        401: {
            "description": "Falta autenticación válida.",
            "content": {"application/problem+json": {"schema": PROBLEM_DETAILS_SCHEMA}},
        },
        403: {
            "description": "El usuario no tiene permisos.",
            "content": {"application/problem+json": {"schema": PROBLEM_DETAILS_SCHEMA}},
        },
    },
)
def listar_productos(
    conn: Db,
    request: Request,
    tipo: Annotated[
        str | None,
        Query(json_schema_extra={"enum": list(TIPOS_PRODUCTO)}),
    ] = None,
) -> Any:
    if tipo is not None and tipo not in TIPOS_PRODUCTO:
        trace_id = request.headers.get("X-Request-Id") or str(uuid4())
        problem = ProblemDetails(
            type="about:blank",
            title="Bad Request",
            status=400,
            code="VALIDATION_ERROR",
            detail="El parámetro tipo no es válido.",
            trace_id=trace_id,
            errors=[
                {
                    "field": "tipo",
                    "message": f"Debe ser uno de: {', '.join(TIPOS_PRODUCTO)}.",
                }
            ],
        )
        return JSONResponse(
            status_code=400,
            media_type="application/problem+json",
            content=problem.model_dump(by_alias=True),
            headers={"X-Request-Id": trace_id},
        )
    return repository.listar_productos(conn, tipo)
