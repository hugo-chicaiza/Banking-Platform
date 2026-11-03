from fastapi import FastAPI

from app.core.api.middleware import TraceIdMiddleware
from app.core.api.rate_limit import LimitePeticionesMiddleware
from app.core.config.settings import get_settings
from app.modules.catalogos.router import router as catalogos_router
from app.modules.clientes.router import router as clientes_router
from app.modules.contabilidad.router import router as contabilidad_router
from app.modules.cuentas.router import router as cuentas_router
from app.modules.tarjetas.router import router as tarjetas_router
from app.smoke_test import router as smoke_test_router  # SMOKE-TEST: borrar

settings = get_settings()
is_prod = settings.app_env == "production"

app = FastAPI(
    title=settings.app_name,
    # ASVS V14: no exponer documentación de la API en producción
    docs_url=None if is_prod else "/docs",
    redoc_url=None,
    openapi_url=None if is_prod else "/openapi.json",
)
if settings.limite_peticiones_activo:
    app.add_middleware(
        LimitePeticionesMiddleware,
        lectura=settings.limite_lectura_por_minuto,
        escritura=settings.limite_escritura_por_minuto,
        sensible=settings.limite_sensible_por_minuto,
    )
# Debe ir de último: se ejecuta primero el último agregado y así el 429 lleva traceId
app.add_middleware(TraceIdMiddleware)

API_V1 = "/api/v1"
app.include_router(catalogos_router, prefix=API_V1)
app.include_router(clientes_router, prefix=API_V1)
app.include_router(contabilidad_router, prefix=API_V1)
app.include_router(cuentas_router, prefix=API_V1)
app.include_router(tarjetas_router, prefix=API_V1)

app.include_router(smoke_test_router)  # SMOKE-TEST: borrar
