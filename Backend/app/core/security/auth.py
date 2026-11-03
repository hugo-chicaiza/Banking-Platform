def require_auth() -> None:
    """Autenticación de las rutas protegidas. Por ahora no valida nada.

    TODO(F-03): validar el JWT de WorkOS (Authorization: Bearer) y responder 401 si falta
    o no es válido. Los routers ya declaran esta dependencia, así que basta con
    implementarla aquí.
    """
