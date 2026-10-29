def require_auth() -> None:
    """Punto único de autenticación para todas las rutas protegidas.

    TODO(F-03): validar el JWT de WorkOS (header Authorization: Bearer) y
    responder 401 si falta o es inválido. Los routers ya declaran esta
    dependencia, así que implementarla aquí protege todos los endpoints
    sin tocar ningún módulo. Hoy no valida nada: las rutas están abiertas.
    """
