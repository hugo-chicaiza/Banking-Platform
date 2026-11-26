from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
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
from app.modules.catalogos import (
    administracion,
    confirmacion,
    repository,
    service,
    tipos_direccion,
)
from app.modules.catalogos.schemas import (
    ActividadEconomica,
    Agencia,
    Canal,
    Ciudad,
    Comision,
    Denominacion,
    Pais,
    Producto,
    Red,
    Seguro,
    SistemaAmortizacion,
    TasaInteres,
    TasaInteresCreate,
    TipoAntecedente,
    TipoCredito,
    TipoMovimientoCaja,
    TipoProducto,
    TipoTasa,
)
from app.modules.catalogos.subproductos import TipoTarjeta
from app.modules.clientes.relaciones import relacion_vigente

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
    dependencies=[Depends(solo_parametros("idTipoCredito", "tipoTasa"))],
)
def listar_tasas_interes(
    conn: Db,
    id_tipo_credito: Annotated[
        int | None, Query(alias="idTipoCredito", ge=1, le=2_147_483_647)
    ] = None,
    tipo_tasa: Annotated[TipoTasa | None, Query(alias="tipoTasa")] = None,
) -> Any:
    """Tasas activas (vigentes, futuras y vencidas); `vigente` dice cuáles aplican hoy."""
    return service.listar_tasas_interes(conn, id_tipo_credito, tipo_tasa)


@router.get("/comisiones", response_model=list[Comision])
def listar_comisiones(conn: Db) -> Any:
    """Comisiones y recargos activos, para vincularlos a productos y subproductos."""
    return repository.listar_comisiones(conn)


@router.get("/tipos-direccion", response_model=list[tipos_direccion.TipoDireccion])
def listar_tipos_direccion(conn: Db) -> list[tipos_direccion.TipoDireccion]:
    """Tipos actuales e históricos; solo los activos pueden asignarse de nuevo."""
    return tipos_direccion.listar(conn)


@router.get("/seguros", response_model=list[Seguro])
def listar_seguros(conn: Db) -> Any:
    return repository.listar_seguros(conn)


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


_ADMIN_LECTURA = ("ADMIN", "SUPERVISOR", "ASESOR")
Clave = Annotated[str, Path(pattern=r"^[a-z-]{3,40}$")]
IdRegistro = Annotated[str, Path(pattern=r"^[A-Za-z0-9]{1,15}$")]


@router.get(
    "/administracion",
    openapi_extra={"x-roles": list(_ADMIN_LECTURA)},
)
def listar_catalogos_administrables(
    _: Annotated[Usuario, Depends(require_roles(*_ADMIN_LECTURA))],
    conn: Db,
) -> list[dict[str, Any]]:
    """Catálogos que se administran y la descripción de sus campos."""
    return administracion.descriptores(conn)


@router.post(
    "/administracion/{clave}/confirmacion",
    openapi_extra={"x-roles": ["ADMIN"]},
)
def pedir_confirmacion(
    clave: Clave,
    usuario: Annotated[Usuario, Depends(require_roles("ADMIN"))],
) -> dict[str, Any]:
    """Código de 4 caracteres y su token para crear o eliminar en un catálogo que puede
    alterar la lógica de negocio. Se envían en X-Confirmacion-Codigo y
    X-Confirmacion-Token; vencen a los 5 minutos."""
    if clave not in confirmacion.CATALOGOS_CON_CONFIRMACION:
        raise problema(
            422, "CONFIRMACION_NO_APLICA", "Este catálogo no pide confirmación."
        )
    return confirmacion.emitir(usuario.id_usuario, clave)


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


@router.post(
    "/administracion/{clave}",
    status_code=201,
    openapi_extra={"x-roles": ["ADMIN"]},
)
def crear_registro(
    clave: Clave,
    payload: dict[str, Any],
    request: Request,
    usuario: Annotated[Usuario, Depends(require_roles("ADMIN"))],
    conn: Db,
) -> dict[str, Any]:
    """Alta con los campos de `camposAlta`; código repetido: 409 CODIGO_DUPLICADO."""
    confirmacion.exigir(
        usuario.id_usuario,
        clave,
        request.headers.get("x-confirmacion-token"),
        request.headers.get("x-confirmacion-codigo"),
    )
    return administracion.crear(
        conn, clave, payload, usuario, ip_cliente(request.scope)
    )


@router.delete(
    "/administracion/{clave}/{id_registro}",
    status_code=204,
    openapi_extra={"x-roles": ["ADMIN"]},
)
def eliminar_registro(
    clave: Clave,
    id_registro: IdRegistro,
    request: Request,
    usuario: Annotated[Usuario, Depends(require_roles("ADMIN"))],
    conn: Db,
) -> Response:
    """Solo lo que nadie usa; si se usa, 409 ITEM_EN_USO y se desactiva en su lugar."""
    confirmacion.exigir(
        usuario.id_usuario,
        clave,
        request.headers.get("x-confirmacion-token"),
        request.headers.get("x-confirmacion-codigo"),
    )
    administracion.eliminar(
        conn, clave, id_registro, usuario, ip_cliente(request.scope)
    )
    return Response(status_code=204)


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
    dependencies=[Depends(solo_parametros("tipo", "tipoTarjeta", "idCliente"))],
)
def listar_productos(
    conn: Db,
    tipo: TipoProducto | None = None,
    tipo_tarjeta: Annotated[TipoTarjeta | None, Query(alias="tipoTarjeta")] = None,
    id_cliente: Annotated[
        int | None, Query(alias="idCliente", ge=1, le=2_147_483_647)
    ] = None,
) -> Any:
    """Productos activos con sus subproductos. tipoTarjeta filtra por Debito/Credito.
    idCliente aplica la elegibilidad del cliente. Con tipo=Cuenta se comprueban
    también la relación obligatoria para la apertura y las condiciones vigentes.
    """
    if tipo_tarjeta is not None and tipo not in (None, "Tarjeta"):
        raise problema(
            400,
            "PARAMETRO_INVALIDO",
            "tipoTarjeta solo aplica a productos de tipo Tarjeta.",
        )
    if id_cliente is None:
        return repository.listar_productos(conn, tipo, tipo_tarjeta)

    perfil = repository.perfil_cliente(conn, id_cliente)
    if perfil is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "El cliente no existe.")
    tipo_cliente, nacimiento = perfil
    fecha = service.hoy()
    if tipo == "Cuenta" and tipo_cliente == "Juridico":
        edad = None
    else:
        edad = service.edad_en(nacimiento, fecha) if nacimiento is not None else -1
    productos = repository.listar_productos(conn, tipo, tipo_tarjeta, edad)
    if tipo == "Cuenta" and productos:
        from app.modules.cuentas.service import rol_para_apertura

        rol = rol_para_apertura(conn, tipo_cliente, nacimiento, fecha)
        if rol is not None and relacion_vigente(conn, id_cliente, rol, fecha) is None:
            return []

    from app.modules.productos.service import cliente_elegible, condiciones_vigentes

    for producto in productos:
        producto["subproductos"] = [
            s
            for s in producto["subproductos"]
            if cliente_elegible(conn, id_cliente, s["id_sub_producto"], fecha)[0]
            and (
                tipo != "Cuenta"
                or condiciones_vigentes(conn, s["id_sub_producto"], fecha, "FICHA")
                is not None
            )
        ]
    return [p for p in productos if p["subproductos"]]


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
