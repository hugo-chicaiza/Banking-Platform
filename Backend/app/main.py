from fastapi import FastAPI

from app.core.config import get_settings
from app.modules.catalogos.router import router as catalogos_router
from app.modules.clientes.router import router as clientes_router
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

API_V1 = "/api/v1"
app.include_router(catalogos_router, prefix=API_V1)
app.include_router(clientes_router, prefix=API_V1)

app.include_router(smoke_test_router)  # SMOKE-TEST: borrar
