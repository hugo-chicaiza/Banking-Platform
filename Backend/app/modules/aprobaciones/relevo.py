"""Relevo idempotente a la unica bitacora institucional y su detalle inmutable."""

import json

from sqlalchemy import Engine

from app.modules.aprobaciones.congelacion import congelar
from app.modules.aprobaciones.repositorio import consulta


def entregar(origen: Engine, seguridad: Engine, limite: int = 100, *, ids_evento: list[str] | None = None) -> int:
    enviados = 0
    with origen.begin() as fuente:
        filas = (
            fuente.execute(
                consulta("""SELECT TOP(:limite) IdEvento,CodigoEvento,Contenido,FechaCreacionUTC
            FROM Auditoria.EventoPendiente WITH(UPDLOCK,READPAST,ROWLOCK)
            WHERE Enviado=0 AND (CAST(:eventos AS nvarchar(max)) IS NULL OR IdEvento IN (SELECT CONVERT(uniqueidentifier,[value]) FROM OPENJSON(CAST(:eventos AS nvarchar(max))))) ORDER BY FechaCreacionUTC,IdEvento"""),
                {"limite": limite, "eventos": json.dumps(ids_evento) if ids_evento is not None else None},
            )
            .mappings()
            .all()
        )
        for fila in filas:
            contenido = json.loads(fila["Contenido"])
            # Rechazar campos secretos o contenido corrupto antes de copiar.
            congelar(contenido)
            with seguridad.begin() as destino:
                existe = destino.execute(
                    consulta(
                        "SELECT AuditoriaID FROM Auditoria.EventoDetalle WITH(UPDLOCK,HOLDLOCK) WHERE IdEvento=:id"
                    ),
                    {"id": fila["IdEvento"]},
                ).scalar()
                if existe is None:
                    id_auditoria = destino.execute(
                        consulta("""INSERT Auditoria.Auditoria
                        (UsuarioID,NombreAccion,TablaAfectada,IDRegistro,FechaHora,DireccionIP,Descripcion,Resultado,RolesWorkOS)
                        OUTPUT inserted.AuditoriaID VALUES(:interno,:codigo,:tabla,:objetivo,
                        DATEADD(hour,-5,:fecha),:ip,:descripcion,:resultado,:roles)"""),
                        {
                            "interno": contenido["idInterno"],
                            "codigo": fila["CodigoEvento"],
                            "objetivo": contenido["idObjetivo"],
                            "tabla": contenido.get(
                                "tablaAfectada", "Seguridad.SolicitudAprobacion"
                            ),
                            "fecha": fila["FechaCreacionUTC"],
                            "ip": contenido["origen"] or None,
                            "descripcion": (
                                "solicitud="
                                if contenido["tipoObjetivo"] == "SolicitudAprobacion"
                                else "objetivo="
                            )
                            + contenido["idObjetivo"]
                            + " trace="
                            + contenido["correlacion"],
                            "resultado": contenido["resultado"],
                            "roles": ",".join(contenido["roles"]),
                        },
                    ).scalar_one()
                    destino.execute(
                        consulta(
                            "INSERT Auditoria.EventoDetalle(IdEvento,AuditoriaID,CodigoEvento,Contenido,FechaHoraUTC) VALUES(:id,:auditoria,:codigo,:contenido,:fecha)"
                        ),
                        {
                            "id": fila["IdEvento"],
                            "auditoria": id_auditoria,
                            "codigo": fila["CodigoEvento"],
                            "contenido": fila["Contenido"],
                            "fecha": fila["FechaCreacionUTC"],
                        },
                    )
            fuente.execute(
                consulta(
                    "UPDATE Auditoria.EventoPendiente SET Enviado=1,Intentos=Intentos+1 WHERE IdEvento=:id"
                ),
                {"id": fila["IdEvento"]},
            )
            enviados += 1
    return enviados
