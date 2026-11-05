"""DTO de Caja (OpenAPI `CAJ01`..`CAJ18`). camelCase en el JSON, Decimal en Python."""

from app.core.api.schemas import CamelModel, Money


# CAJ-01
class CajaFisica(CamelModel):
    id_caja_fisica: int
    id_agencia: str | None = None
    codigo_caja: str | None = None
    estado: bool | None = None
    descripcion_estado: str | None = None
    limite_efectivo_caja: Money | None = None
