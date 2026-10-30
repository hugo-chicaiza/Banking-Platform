from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Connection

from app.core.db import cooperativa
from app.core.security import require_auth
from app.modules.clientes import repository
from app.modules.clientes.schemas import PageCliente

router = APIRouter(
    prefix="/clientes",
    tags=["clientes"],
    dependencies=[Depends(require_auth)],
)

Db = Annotated[Connection, Depends(cooperativa)]


@router.get("", response_model=PageCliente)
def listar_clientes(
    conn: Db,
    q: Annotated[str | None, Query()] = None,
    identificacion: Annotated[str | None, Query()] = None,
    tipo_cliente: Annotated[str | None, Query(alias="tipoCliente")] = None,
    estado: Annotated[str | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
    sort: Annotated[str, Query()] = "idCliente,asc",
) -> PageCliente:
    try:
        resultado = repository.listar_clientes(
            conn,
            q=q,
            identificacion=identificacion,
            tipo_cliente=tipo_cliente,
            estado=estado,
            page=page,
            page_size=page_size,
            sort=sort,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return PageCliente.model_validate(resultado)
