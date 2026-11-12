from sqlalchemy import Connection

from app.core.api.errors import problema
from app.modules.organizacion import repository
from app.modules.organizacion.schemas import AgenciaEstado, EstadoAgencia


def _agencia_bloqueada(conn: Connection, id_agencia: str) -> AgenciaEstado:
    fila = repository.bloquear_agencia(conn, id_agencia)
    if fila is None:
        raise problema(404, "AGENCIA_NO_ENCONTRADA", "No se encontró la agencia.")
    return AgenciaEstado(**fila)


def cambiar_estado(
    conn: Connection, id_agencia: str, estado: EstadoAgencia
) -> tuple[AgenciaEstado, str]:
    """Solo A ⇄ I; C es terminal. El lock dura hasta commit/rollback."""
    with conn.begin():
        agencia = _agencia_bloqueada(conn, id_agencia)
        anterior = agencia.estado
        if anterior == estado:
            return agencia, anterior
        if anterior == "C":
            raise problema(
                409, "AGENCIA_CERRADA", "Una agencia cerrada no se puede reabrir."
            )
        if estado == "C":
            raise problema(
                409,
                "CIERRE_AGENCIA_NO_HABILITADO",
                "El cierre de agencias aún no está definido.",
            )
        if not repository.actualizar_estado(conn, id_agencia, anterior, estado):
            raise problema(
                409,
                "ESTADO_AGENCIA_MODIFICADO",
                "El estado de la agencia cambió; vuelva a consultar.",
            )
        return AgenciaEstado(id_agencia=id_agencia, estado=estado), anterior


def exigir_agencia_destino_activa(conn: Connection, id_agencia: str) -> AgenciaEstado:
    """Punto de integración de AUT-06/AUT-11 antes de WorkOS y de asignar.

    El llamador debe abrir la transacción que escribirá la asignación y mantenerla
    abierta hasta terminar. Este guard no crea usuarios ni invita en WorkOS.
    """
    if not conn.in_transaction():
        raise RuntimeError(
            "La validación de agencia requiere la transacción de la asignación."
        )
    agencia = _agencia_bloqueada(conn, id_agencia)
    if agencia.estado != "A":
        raise problema(
            409, "AGENCIA_NO_ACTIVA", "La agencia destino debe estar activa."
        )
    return agencia
