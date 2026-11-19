"""Relevo idempotente a la unica bitacora institucional y su detalle inmutable."""

import json
import logging

from sqlalchemy import Engine

from app.core.config.settings import get_settings
from app.core.security.audit import cambios_json
from app.modules.aprobaciones.congelacion import congelar
from app.modules.aprobaciones.repositorio import consulta

logger = logging.getLogger(__name__)


def edad_pendiente_minutos(origen: Engine) -> int | None:
    """Minutos del evento pendiente más antiguo de la bandeja (None si no hay)."""
    with origen.connect() as conn:
        valor = conn.execute(
            consulta(
                "SELECT DATEDIFF(minute, MIN(FechaCreacionUTC), SYSUTCDATETIME()) FROM Auditoria.EventoPendiente WHERE Enviado=0"
            )
        ).scalar()
    return None if valor is None else int(valor)


def alertar_pendientes(*origenes: Engine) -> list[int]:
    """Alerta (registro de nivel ERROR con código fijo, para el monitor de App Service) si
    un evento lleva más de AUD_EDAD_MAX_PENDIENTE_MIN minutos sin pasar a la bitácora."""
    limite = get_settings().aud_edad_max_pendiente_min
    edades = [e for o in origenes if (e := edad_pendiente_minutos(o)) is not None]
    for edad in edades:
        if edad > limite:
            logger.error(
                "AUD_RELEVO_ALERTA evento pendiente de %d minutos (máximo %d)",
                edad,
                limite,
            )
    return edades


def _corto(valor: object, largo: int, *, exacto: bool = False) -> str | None:
    texto = str(valor) if valor not in (None, "") else None
    if texto is None or (exacto and len(texto) > largo):
        return None
    return texto[:largo]


def entregar(
    origen: Engine,
    seguridad: Engine,
    limite: int = 100,
    *,
    ids_evento: list[str] | None = None,
) -> int:
    enviados = 0
    with origen.begin() as fuente:
        filas = (
            fuente.execute(
                consulta("""SELECT TOP(:limite) IdEvento,CodigoEvento,Contenido,FechaCreacionUTC
            FROM Auditoria.EventoPendiente WITH(UPDLOCK,READPAST,ROWLOCK)
            WHERE Enviado=0 AND (CAST(:eventos AS nvarchar(max)) IS NULL OR IdEvento IN (SELECT CONVERT(uniqueidentifier,[value]) FROM OPENJSON(CAST(:eventos AS nvarchar(max))))) ORDER BY FechaCreacionUTC,IdEvento"""),
                {
                    "limite": limite,
                    "eventos": json.dumps(ids_evento)
                    if ids_evento is not None
                    else None,
                },
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
                        (UsuarioID,NombreAccion,TablaAfectada,IDRegistro,FechaHora,DireccionIP,Descripcion,Resultado,RolesWorkOS,
                         IdEvento,CodigoEvento,FechaHoraUTC,IdAgencia,IdSesion,Canal,IdCorrelacion,TipoObjetivo,IdObjetivo,Cambios)
                        OUTPUT inserted.AuditoriaID VALUES(:interno,:codigo,:tabla,:objetivo,
                        DATEADD(hour,-5,:fecha),:ip,:descripcion,:resultado,:roles,
                        :id_evento,:codigo,:fecha,:agencia,:sesion,:canal,:correlacion,:tipo_objetivo,:objetivo,:cambios)"""),
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
                            # E0-05: columnas del formato nuevo desde el evento ya filtrado
                            "id_evento": fila["IdEvento"],
                            "agencia": _corto(contenido.get("agencia"), 3, exacto=True),
                            "sesion": _corto(contenido.get("sesion"), 64),
                            "canal": _corto(contenido.get("canal"), 10),
                            "correlacion": _corto(contenido.get("correlacion"), 64),
                            "tipo_objetivo": _corto(contenido.get("tipoObjetivo"), 100),
                            "cambios": cambios_json(contenido.get("cambios")),
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
