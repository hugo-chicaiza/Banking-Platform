from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base de las respuestas: snake_case en Python, camelCase en el JSON (contrato OpenAPI)."""

    model_config = ConfigDict(alias_generator=to_camel, validate_by_name=True)


# Decimal en el backend (nunca float para dinero); número en el JSON hacia el FE
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]
