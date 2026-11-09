from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import Connection

from app.core.api.errors import (
    RESPUESTAS_ERROR,
    ProblemDetailsRoute,
    problema,
    solo_parametros,
)
from app.core.database.db import cooperativa
from app.core.security.auth import require_auth
from app.modules.catalogos import repository
from app.modules.catalogos.schemas import (
    ActividadEconomica,
    Agencia,
    Canal,
    Ciudad,
    Denominacion,
    Pais,
    Producto,
    TipoAntecedente,
    TipoCredito,
    TipoMovimientoCaja,
    TipoProducto,
)
from app.modules.catalogos.subproductos import TipoTarjeta

# Catálogos de solo lectura: sin service.py porque no hay reglas de negocio
router = APIRouter(
    prefix="/catalogos",
    tags=["catalogos"],
    dependencies=[Depends(require_auth)],
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
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


@router.get("/actividades-economicas", response_model=list[ActividadEconomica])
def listar_actividades_economicas(conn: Db) -> Any:
    return repository.listar_actividades_economicas(conn)


@router.get("/tipos-antecedente", response_model=list[TipoAntecedente])
def listar_tipos_antecedente(conn: Db) -> Any:
    return repository.listar_tipos_antecedente(conn)


@router.get(
    "/productos",
    response_model=list[Producto],
    dependencies=[Depends(solo_parametros("tipo", "tipoTarjeta"))],
)
def listar_productos(
    conn: Db,
    tipo: TipoProducto | None = None,
    tipo_tarjeta: Annotated[TipoTarjeta | None, Query(alias="tipoTarjeta")] = None,
) -> Any:
    """Productos activos con sus subproductos. tipoTarjeta (Debito/Credito) deja solo
    los subproductos de tarjeta de ese tipo, para que la emisión sea congruente.
    """
    if tipo_tarjeta is not None and tipo not in (None, "Tarjeta"):
        raise problema(
            400,
            "PARAMETRO_INVALIDO",
            "tipoTarjeta solo aplica a productos de tipo Tarjeta.",
        )
    return repository.listar_productos(conn, tipo, tipo_tarjeta)


@router.get("/paises/{codigo_pais}/ciudades", response_model=list[Ciudad])
def listar_ciudades(
    conn: Db,
    codigo_pais: Annotated[str, Path(min_length=3, max_length=3)],
    q: Annotated[str | None, Query()] = None,
) -> Any:
    codigo_pais = codigo_pais.upper()
    if not repository.existe_pais(conn, codigo_pais):
        raise problema(404, "PAIS_NO_ENCONTRADO", "El país no existe")
    return repository.listar_ciudades(conn, codigo_pais, q.strip() if q else None)
