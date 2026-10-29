from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import Connection

from app.core.db import cooperativa
from app.core.security import require_auth
from app.modules.catalogos import repository
from app.modules.catalogos.schemas import (
    Canal,
    Denominacion,
    Pais,
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
