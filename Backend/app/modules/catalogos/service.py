"""Reglas del único catálogo que se escribe desde la API: tasas de interés.

Los demás catálogos siguen siendo de solo lectura. Una tasa no se edita ni se elimina:
la usan simulaciones, solicitudes y créditos; una tasa nueva reemplaza a otra con su vigencia.
"""

from datetime import date

from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.core.security.auth import Usuario
from app.core.security.operador import auditar
from app.modules.catalogos import repository
from app.modules.catalogos.schemas import TasaInteres, TasaInteresCreate
from app.modules.contabilidad.service import ahora_ecuador


def hoy() -> date:
    """Fecha de hoy en Ecuador: decide qué tasas están vigentes."""
    return ahora_ecuador().date()


def edad_en(nacimiento: date, dia: date | None = None) -> int:
    """Años cumplidos a la fecha (hoy en Ecuador por defecto)."""
    dia = dia or hoy()
    return (
        dia.year
        - nacimiento.year
        - ((dia.month, dia.day) < (nacimiento.month, nacimiento.day))
    )


def listar_tasas_interes(
    conn: Connection, id_tipo_credito: int | None, tipo_tasa: str | None = None
) -> list[TasaInteres]:
    return [
        TasaInteres.model_validate(f)
        for f in repository.listar_tasas_interes(
            conn, hoy(), id_tipo_credito, tipo_tasa
        )
    ]


def crear_tasa_interes(
    conn: Connection, datos: TasaInteresCreate, usuario: Usuario, ip: str
) -> TasaInteres:
    with auditar(
        "CREAR",
        "Credito.TasaInteres",
        usuario,
        ip,
        f"CAT-TASA tipo={datos.tipo_tasa} tipoCredito={datos.id_tipo_credito}"
        f" desde={datos.vigencia_desde.isoformat()}",
    ) as registro:
        try:
            if datos.vigencia_desde < hoy():
                raise problema(
                    422, "VIGENCIA_PASADA", "La vigencia no puede empezar antes de hoy."
                )
            es_credito = datos.id_tipo_credito is not None
            if es_credito and not repository.existe_tipo_credito_activo(
                conn, datos.id_tipo_credito or 0
            ):
                raise problema(
                    422,
                    "TIPO_CREDITO_NO_EXISTE",
                    "El tipo de crédito no existe o está inactivo.",
                )
            valores = datos.model_dump()
            id_tasa = repository.insertar_tasa_interes(conn, valores)
            registro.id_registro = str(id_tasa)
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise traducir_error_bd(exc) from None
        except Exception:
            conn.rollback()
            raise
    fila = repository.obtener_tasa_interes(conn, id_tasa, hoy())
    if fila is None:
        raise problema(500, "ERROR_INTERNO", "Error interno del servidor.")
    return TasaInteres.model_validate(fila)
