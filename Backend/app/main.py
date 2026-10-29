from fastapi import FastAPI

from app.core.config import get_settings
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

app.include_router(smoke_test_router)  # SMOKE-TEST: borrar
