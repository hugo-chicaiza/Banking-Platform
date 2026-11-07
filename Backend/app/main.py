from fastapi import FastAPI

# TODO: Estos imports comentados venían de develop al realizar el merge, pero no se usan en main.py. Revisar si se pueden borrar.
# from app.core.config import get_settings
# from app.core.middleware import TraceIdMiddleware
# from app.core.rate_limit import LimitePeticionesMiddleware
from app.core.api.middleware import HstsMiddleware, TraceIdMiddleware
from app.core.api.rate_limit import LimitePeticionesMiddleware
from app.core.config.logs import configurar_logging
from app.core.config.settings import get_settings
from app.core.security.audit import AccesoDenegadoMiddleware
from app.modules.atm.router import router as atm_router
from app.modules.auth.router import router as auth_router
from app.modules.caja.router import router as caja_router
from app.modules.catalogos.router import router as catalogos_router
from app.modules.clientes.router import router as clientes_router
from app.modules.contabilidad.router import router as contabilidad_router
from app.modules.creditos.router import router as creditos_router
from app.modules.cuentas.router import router as cuentas_router
from app.modules.tarjetas.router import router as tarjetas_router
from app.modules.tarjetas.router import router_pruebas as tarjetas_pruebas_router
from app.modules.transacciones.router import router as transacciones_router
from app.smoke_test import router as smoke_test_router  # SMOKE-TEST: borrar

settings = get_settings()
is_prod = settings.app_env == "production"
# Antes de crear la app, para que los mensajes del arranque ya salgan con el formato
configurar_logging(settings.log_level)

app = FastAPI(
    title=settings.app_name,
    # ASVS V14: no exponer documentación de la API en producción
    # Bajo /api para que el proxy del FE (Vite en local, Cloudflare en Azure) también la
    # sirva: así /api/docs usa la cookie de sesión del dominio del FE
    docs_url=None if is_prod else "/api/docs",
    redoc_url=None,
    openapi_url=None if is_prod else "/api/openapi.json",
)
# Primero en agregarse, último en ejecutarse: ya tiene el traceId y no audita los 429
app.add_middleware(AccesoDenegadoMiddleware)
if settings.limite_peticiones_activo:
    app.add_middleware(
        LimitePeticionesMiddleware,
        lectura=settings.limite_lectura_por_minuto,
        escritura=settings.limite_escritura_por_minuto,
        sensible=settings.limite_sensible_por_minuto,
    )
# Fuera de development: en localhost el navegador recordaría HSTS para otros proyectos
if settings.app_env != "development":
    app.add_middleware(HstsMiddleware)
# Debe ir de último: se ejecuta primero el último agregado y así el 429 lleva traceId
app.add_middleware(TraceIdMiddleware)

API_V1 = "/api/v1"
app.include_router(auth_router, prefix=API_V1)
app.include_router(catalogos_router, prefix=API_V1)
app.include_router(clientes_router, prefix=API_V1)
app.include_router(contabilidad_router, prefix=API_V1)
app.include_router(creditos_router, prefix=API_V1)
app.include_router(cuentas_router, prefix=API_V1)
app.include_router(tarjetas_router, prefix=API_V1)
app.include_router(caja_router, prefix=API_V1)
app.include_router(transacciones_router, prefix=API_V1)
app.include_router(atm_router, prefix=API_V1)
# PIN pad simulado para probar TAR-05 y ATM-01: responde 404 en producción
app.include_router(tarjetas_pruebas_router, prefix=API_V1)

# Público a propósito: verifica el despliegue sin sesión (fuera de /api, sin require_auth)
app.include_router(smoke_test_router)  # SMOKE-TEST: borrar
