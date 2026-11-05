import uvicorn

from app.core.config.settings import get_settings

settings = get_settings()
uvicorn.run(
    "app.main:app",
    host=settings.app_host,
    port=settings.app_port,
    reload=settings.app_env == "development",
    server_header=False,
)
