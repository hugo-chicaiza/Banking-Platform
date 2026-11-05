"""Reglas puras, conversión de fechas e integración con main.py."""


def _operaciones() -> dict[tuple[str, str], str]:
    """(método, ruta) → operationId según el OpenAPI que genera main.py."""
    from app.main import app

    return {
        (metodo.upper(), ruta): operacion.get("operationId", "")
        for ruta, metodos in app.openapi()["paths"].items()
        for metodo, operacion in metodos.items()
    }


def test_main_registra_caja_bajo_api_v1() -> None:
    operaciones = _operaciones()
    assert operaciones[("GET", "/api/v1/caja/cajas-fisicas")] == "CAJ01"
    # Las rutas que ya existían siguen registradas
    assert any(ruta.startswith("/api/v1/auth") for _, ruta in operaciones)
