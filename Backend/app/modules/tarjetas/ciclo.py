"""Reglas del ciclo de débito. El consumidor confirma la transacción."""

from datetime import date, timedelta
from typing import Any, Literal

from fastapi import HTTPException
from sqlalchemy import Connection

from app.core.api.errors import problema
from app.modules.parametros import general
from app.modules.parametros.service import hoy
from app.modules.tarjetas import repository
from app.modules.tarjetas.schemas import TarjetaCreate

VENTANA_RENOVACION = "TAR_DIAS_AVISO_RENOVACION"
PLAZO_RETIRO = "TAR_DIAS_NO_RETIRADA"
_PERDIDA = {"PERDIDA", "ROBO"}
TipoReemision = Literal["Reposicion", "Renovacion"]


def dias(conn: Connection, clave: str, fecha: date) -> int:
    try:
        valor = general.valor(conn, clave, fecha)
    except HTTPException as error:
        if (
            not isinstance(error.detail, dict)
            or error.detail.get("code") != "PARAMETRO_NO_ENCONTRADO"
        ):
            raise
        # Instalaciones anteriores al alta de E6-11 conservan los 30 días del plan.
        return 30
    if type(valor) is not int or not 1 <= valor <= 365:
        raise problema(503, "PARAMETRO_INVALIDO", "El plazo de tarjeta no es válido.")
    return valor


def hasta_renovacion(conn: Connection, fecha: date) -> date:
    return fecha + timedelta(days=dias(conn, VENTANA_RENOVACION, fecha))


def en_ventana(conn: Connection, tarjeta: dict[str, Any]) -> bool:
    if tarjeta["tipo_tarjeta"] != "Debito" or tarjeta["estado_actual"] not in {
        "Activa",
        "Inactiva",
    }:
        return False
    fecha = hoy()
    vencimiento = tarjeta["fecha_expiracion"]
    if not fecha <= vencimiento <= fecha + timedelta(days=365):
        return False
    return fecha <= vencimiento <= hasta_renovacion(conn, fecha)


def perdida_o_robo(tarjeta: dict[str, Any]) -> bool:
    return (
        tarjeta["tipo_tarjeta"] == "Debito"
        and tarjeta["estado_actual"] in {"Bloqueada", "Cancelada", "Vencida"}
        and tarjeta.get("motivo_estado") in _PERDIDA
    )


def validar_reemision(
    conn: Connection, datos: TarjetaCreate, id_cliente: int
) -> tuple[TipoReemision, dict[str, Any]] | None:
    id_anterior = datos.id_tarjeta_reemplazada
    if id_anterior is None:
        return None
    anterior = repository.obtener_tarjeta(conn, id_anterior, bloquear=True)
    if (
        anterior is None
        or anterior["id_cuenta"] != datos.id_cuenta
        or anterior["id_cliente"] != id_cliente
    ):
        raise problema(
            404,
            "TARJETA_NO_ENCONTRADA",
            "La tarjeta anterior no pertenece a la cuenta.",
        )
    if (
        anterior["tipo_tarjeta"] != "Debito"
        or bool(anterior["es_extension"]) != datos.es_extension
        or anterior["id_tarjeta_titular"] != datos.id_tarjeta_titular
    ):
        raise problema(
            422,
            "TARJETA_REEMISION_INCOMPATIBLE",
            "Mantenga el tipo y el vínculo de la tarjeta anterior.",
        )
    if repository.reemision_vigente(conn, id_anterior):
        raise problema(
            409,
            "TARJETA_REEMISION_VIGENTE",
            "Ya existe una reemisión vigente para esta tarjeta.",
        )
    if perdida_o_robo(anterior):
        return "Reposicion", anterior
    if en_ventana(conn, anterior):
        return "Renovacion", anterior
    raise problema(
        409,
        "TARJETA_NO_REEMITIBLE",
        "La tarjeta no admite una reposición ni está en el plazo de renovación.",
    )


def cancelar_anterior(
    conn: Connection,
    anterior: dict[str, Any],
    tipo: TipoReemision,
    usuario: int,
    ip: str | None,
) -> None:
    estado = anterior["estado_actual"]
    if estado in {"Cancelada", "Anulada", "Vencida", "Cerrada"}:
        return
    id_anterior = anterior["id_tarjeta"]
    if not repository.existe_transicion(conn, estado, "Cancelada"):
        raise problema(
            409, "TRANSICION_INVALIDA", "No se puede cancelar la tarjeta anterior."
        )
    repository.actualizar_estado(
        conn, id_anterior, "Cancelada", motivo=anterior.get("motivo_estado")
    )
    detalle = (
        "Cancelación por reposición"
        if tipo == "Reposicion"
        else "Cancelación al entregar la tarjeta renovada"
    )
    repository.insertar_historial(
        conn, id_anterior, tipo, estado, "Cancelada", detalle, usuario, ip
    )
