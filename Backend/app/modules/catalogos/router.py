from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy import Connection

from app.core.api.errors import (
    RESPUESTAS_ERROR,
    ProblemDetailsRoute,
    problema,
    solo_parametros,
)
from app.core.api.middleware import ip_cliente
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, require_auth, require_roles
from app.modules.catalogos import administracion, repository, service
from app.modules.catalogos.schemas import (
    ActividadEconomica,
    Agencia,
    Canal,
    Ciudad,
    Denominacion,
    Pais,
    Producto,
    Red,
    SistemaAmortizacion,
    TasaInteres,
    TasaInteresCreate,
    TipoAntecedente,
    TipoCredito,
    TipoMovimientoCaja,
    TipoProducto,
)
from app.modules.catalogos.subproductos import TipoTarjeta

# Catálogos de lectura para cualquier usuario autenticado. Solo las tasas de interés se
# crean aquí (ADMIN); sus reglas están en service.py
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


@router.get("/redes", response_model=list[Red])
def listar_redes(conn: Db) -> Any:
    return repository.listar_redes(conn)


@router.get("/sistemas-amortizacion", response_model=list[SistemaAmortizacion])
def listar_sistemas_amortizacion(conn: Db) -> Any:
    return repository.listar_sistemas_amortizacion(conn)


@router.get(
    "/tasas-interes",
    response_model=list[TasaInteres],
    dependencies=[Depends(solo_parametros("idTipoCredito"))],
)
def listar_tasas_interes(
    conn: Db,
    id_tipo_credito: Annotated[
        int | None, Query(alias="idTipoCredito", ge=1, le=2_147_483_647)
    ] = None,
) -> Any:
    """Todas las tasas (vigentes, futuras y vencidas); `vigente` dice cuáles aplican hoy."""
    return service.listar_tasas_interes(conn, id_tipo_credito)


@router.post(
    "/tasas-interes",
    response_model=TasaInteres,
    status_code=201,
    openapi_extra={"x-roles": ["ADMIN"]},
)
def crear_tasa_interes(
    payload: TasaInteresCreate,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_roles("ADMIN"))],
    conn: Db,
) -> Any:
    """Las tasas no se editan: una nueva con su vigencia reemplaza a la anterior."""
    return service.crear_tasa_interes(conn, payload, usuario, ip_cliente(request.scope))


_ADMIN_LECTURA = ("ADMIN", "ASESOR")
Clave = Annotated[str, Path(pattern=r"^[a-z-]{3,40}$")]
IdRegistro = Annotated[str, Path(pattern=r"^[A-Za-z0-9]{1,15}$")]


@router.get(
    "/administracion",
    openapi_extra={"x-roles": list(_ADMIN_LECTURA)},
)
def listar_catalogos_administrables(
    _: Annotated[Usuario, Depends(require_roles(*_ADMIN_LECTURA))],
) -> list[dict[str, Any]]:
    """Catálogos que se administran y la descripción de sus campos."""
    return administracion.descriptores()


@router.get(
    "/administracion/{clave}",
    openapi_extra={"x-roles": list(_ADMIN_LECTURA)},
)
def listar_registros(
    clave: Clave,
    _: Annotated[Usuario, Depends(require_roles(*_ADMIN_LECTURA))],
    conn: Db,
) -> list[dict[str, Any]]:
    """Todas las filas del catálogo, activas e inactivas."""
    return administracion.listar(conn, clave)


@router.patch(
    "/administracion/{clave}/{id_registro}",
    openapi_extra={"x-roles": ["ADMIN"]},
)
def actualizar_registro(
    clave: Clave,
    id_registro: IdRegistro,
    payload: dict[str, Any],
    request: Request,
    usuario: Annotated[Usuario, Depends(require_roles("ADMIN"))],
    conn: Db,
) -> dict[str, Any]:
    """Edita los campos editables o el estado (A/I). Nada se borra."""
    return administracion.actualizar(
        conn, clave, id_registro, payload, usuario, ip_cliente(request.scope)
    )


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
