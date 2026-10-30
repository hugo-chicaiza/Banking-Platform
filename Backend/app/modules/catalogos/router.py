from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy import Connection

from app.core.db import cooperativa
from app.core.security import require_auth
from app.modules.catalogos import repository
from app.modules.catalogos.schemas import (
    Agencia,
    Canal,
    Ciudad,
    Denominacion,
    Pais,
    TipoCredito,
    TipoMovimientoCaja,
)

# Catálogos de solo lectura: sin service.py porque no hay reglas de negocio
router = APIRouter(
    prefix="/catalogos", tags=["catalogos"], dependencies=[Depends(require_auth)]
)
Db = Annotated[Connection, Depends(cooperativa)]


@router.get("/paises", response_model=list[Pais])
def listar_paises(conn: Db) -> Any:
    return repository.listar_paises(conn)


@router.get("/denominaciones", response_model=list[Denominacion])
def listar_denominaciones(conn: Db) -> Any:
    return repository.listar_denominaciones(conn)


@router.get("/tipos-movimiento-caja", response_model=list[TipoMovimientoCaja])
def listar_tipos_movimiento_caja(conn: Db) -> Any:
    return repository.listar_tipos_movimiento_caja(conn)


@router.get("/canales", response_model=list[Canal])
def listar_canales(conn: Db) -> Any:
    return repository.listar_canales(conn)


@router.get("/agencias", response_model=list[Agencia])
def listar_agencias(conn: Db) -> Any:
    return repository.listar_agencias(conn)


@router.get("/tipos-credito", response_model=list[TipoCredito])
def listar_tipos_credito(conn: Db) -> Any:
    return repository.listar_tipos_credito(conn)


@router.get("/paises/{codigo_pais}/ciudades", response_model=list[Ciudad])
def listar_ciudades(
    conn: Db,
    codigo_pais: Annotated[str, Path(min_length=3, max_length=3)],
    q: Annotated[str | None, Query()] = None,
) -> Any:
    codigo_pais = codigo_pais.upper()
    if not repository.existe_pais(conn, codigo_pais):
        # Temporal hasta F-04 (ProblemDetails): el code del contrato va en detail.
        raise HTTPException(
            status_code=404,
            detail={"code": "PAIS_NO_ENCONTRADO", "message": "El país no existe"},
        )
    return repository.listar_ciudades(conn, codigo_pais, q.strip() if q else None)
