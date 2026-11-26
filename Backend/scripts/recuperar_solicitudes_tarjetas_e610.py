"""Inscribe las tarjetas 321 y 322 en la cola conservando su autor y agencia."""

import argparse

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.integrations.workos_client import get_organizacion_id
from app.modules.aprobaciones.auditoria import ContextoAuditoria
from app.modules.aprobaciones.router import servicio
from app.modules.aprobaciones.servicio import Servicio
from app.modules.tarjetas import aprobacion, repository


def recuperar(cola: Servicio, id_tarjeta: int, org: str) -> int:
    with cola.cooperativa.begin() as conn:
        tarjeta = repository.obtener_tarjeta(conn, id_tarjeta, bloquear=True)
        if tarjeta is None or tarjeta["tipo_tarjeta"] != "Debito":
            raise problema(404, "TARJETA_NO_ENCONTRADA", "Falta la tarjeta de débito.")
        if not aprobacion.gestionada(conn, id_tarjeta):
            if tarjeta["estado_actual"] != "Solicitada" or not tarjeta["id_agencia"]:
                raise problema(
                    409,
                    "TARJETA_NO_SOLICITADA",
                    "Revise el estado y la agencia de la tarjeta.",
                )
            with cola.seguridad.connect() as seguridad:
                sujeto = seguridad.execute(
                    text(
                        "SELECT KeyUsuario FROM Organizacion.Usuarios WHERE UsuarioID=:id AND Estado='Activo'"
                    ),
                    {"id": tarjeta["creado_por"]},
                ).scalar_one_or_none()
            if not sujeto:
                raise problema(
                    409,
                    "SOLICITANTE_SIN_VINCULO",
                    "El solicitante original requiere revisión.",
                )
            actor = cola.identidad_vigente(sujeto, org)
            if actor.id_interno != tarjeta["creado_por"]:
                raise problema(
                    409, "SOLICITANTE_INCOMPATIBLE", "Revise el solicitante original."
                )
            aprobacion.programar(conn, id_tarjeta, actor, tarjeta["id_agencia"])

    return aprobacion.publicar(cola, id_tarjeta, ContextoAuditoria(canal="SISTEMA"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--servidor", required=True)
    parser.add_argument("--cooperativa", required=True)
    parser.add_argument("--seguridad", required=True)
    parser.add_argument("--organizacion", required=True)
    parser.add_argument(
        "--tarjeta", type=int, choices=(321, 322), action="append", required=True
    )
    args = parser.parse_args()

    configuracion = get_settings()
    if (
        args.servidor != configuracion.cooperativa_db_server
        or args.servidor != configuracion.seguridad_db_server
        or args.cooperativa != configuracion.cooperativa_db_name
        or args.seguridad != configuracion.seguridad_db_name
        or args.organizacion != get_organizacion_id()
    ):
        parser.error(
            "El servidor, las bases o la organización difieren del destino confirmado."
        )

    cola = servicio()
    try:
        for motor, nombre in (
            (cola.cooperativa, args.cooperativa),
            (cola.seguridad, args.seguridad),
        ):
            with motor.connect() as conn:
                if conn.execute(text("SELECT DB_NAME()")).scalar_one() != nombre:
                    parser.error(
                        "Una conexión apunta a una base distinta del destino confirmado."
                    )
        for id_tarjeta in dict.fromkeys(args.tarjeta):
            print(
                f"Tarjeta {id_tarjeta}, solicitud {recuperar(cola, id_tarjeta, args.organizacion)}"
            )
    except HTTPException as error:
        detalle = error.detail if isinstance(error.detail, dict) else {}
        parser.exit(
            1,
            f"La recuperación se detuvo con {detalle.get('code', error.status_code)}.\n",
        )
    except SQLAlchemyError:
        parser.exit(1, "La recuperación se detuvo por un error de base de datos.\n")


if __name__ == "__main__":
    main()
