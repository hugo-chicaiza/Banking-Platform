"""Puerta de habilitación de clientes para los módulos de productos."""

from datetime import date

from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.core.api.schemas import CamelModel
from app.modules.parametros import general


class HabilitacionCliente(CamelModel):
    habilitado: bool
    motivos: list[str]


def requisitos_cliente(
    conn: Connection,
    id_cliente: int,
    fecha: date,
    solicitud_en_aplicacion: int | None = None,
) -> list[str]:
    """Comprueba la evidencia de la fecha de consulta en la transacción del consumidor.

    `solicitud_en_aplicacion`: la cola E0-08 escribe AprobacionAplicada después de
    aplicar, así que la solicitud que se está aplicando cuenta como aprobada.
    """
    fila = (
        conn.execute(
            text("""
            SELECT c.Estado,c.ConsentimientoDatos,c.FechaConsentimiento,c.TipoCliente,
                   r.IdEvaluacion,r.ResultadoEvaluacion,r.EsPEP,r.NivelRiesgoLAFT,r.IdSolicitud,
                   r.AntecedenteImpeditivo
            FROM Clientes.Cliente AS c WITH (HOLDLOCK)
            OUTER APPLY (
                SELECT TOP (1) r.IdEvaluacion,r.ResultadoEvaluacion,r.EsPEP,
                       r.NivelRiesgoLAFT,r.IdSolicitud,
                       CASE WHEN r.TieneAntecedentes=1 AND a.PuedeImpedirVinculacion=1
                            THEN 1 ELSE 0 END AS AntecedenteImpeditivo
                FROM Clientes.RiesgoCliente AS r WITH (HOLDLOCK)
                LEFT JOIN Catalogo.TipoAntecedente AS a WITH (HOLDLOCK)
                    ON a.IdTipoAntecedente=r.IdTipoAntecedente
                WHERE r.IdCliente=c.IdCliente AND r.EsVigente=1
                  AND CONVERT(date,r.FechaEvaluacion AT TIME ZONE 'UTC'
                      AT TIME ZONE 'SA Pacific Standard Time')<=:fecha AND r.VigenteHasta>=:fecha
                ORDER BY r.FechaEvaluacion DESC,r.IdEvaluacion DESC
            ) AS r
            WHERE c.IdCliente=:id
        """),
            {"id": id_cliente, "fecha": fecha},
        )
        .mappings()
        .first()
    )
    if fila is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "El cliente no existe.")
    motivos: list[str] = []
    if fila["Estado"] != "Activo":
        motivos.append("CLIENTE_NO_ACTIVO")
    consentimiento = fila["FechaConsentimiento"]
    if (
        not fila["ConsentimientoDatos"]
        or consentimiento is None
        or consentimiento.date() > fecha
    ):
        motivos.append("CONSENTIMIENTO_NO_VIGENTE")
    aprobada = fila["ResultadoEvaluacion"] == "Aprobado"
    if aprobada and (fila["EsPEP"] or fila["NivelRiesgoLAFT"] == "Alto"):
        solicitud = fila["IdSolicitud"]
        aprobada = solicitud is not None and (
            solicitud == solicitud_en_aplicacion
            or conn.execute(
                text("""
                SELECT 1 FROM Seguridad.AprobacionAplicada WITH (HOLDLOCK)
                WHERE IdSolicitud=:solicitud AND CodigoTransaccion='CLI-RIESGO'
            """),
                {"solicitud": solicitud},
            ).first()
            is not None
        )
    if not aprobada:
        motivos.append("RIESGO_NO_APROBADO_VIGENTE")
    if fila["AntecedenteImpeditivo"]:
        motivos.append("ANTECEDENTE_IMPIDE_VINCULACION")
    exige_archivos = general.valor(conn, "CLI_EXIGE_ARCHIVOS", fecha)
    if type(exige_archivos) is not bool:
        raise problema(
            503, "PARAMETRO_INVALIDO", "No se pudo verificar la regla de archivos."
        )
    if exige_archivos:
        catalogo_evidencia = conn.execute(
            text("""
                SELECT CASE WHEN OBJECT_ID('Catalogo.ClaseDocumentoCliente','U') IS NOT NULL
                             AND OBJECT_ID('Clientes.ClienteArchivo','U') IS NOT NULL
                            THEN 1 ELSE 0 END
            """)
        ).scalar_one()
        if not catalogo_evidencia:
            raise problema(
                503,
                "EVIDENCIA_NO_DISPONIBLE",
                "El catálogo de archivos no está disponible.",
            )
        faltantes = conn.execute(
            text("""
                SELECT clase.Codigo
                FROM Catalogo.ClaseDocumentoCliente AS clase WITH (HOLDLOCK)
                WHERE clase.Estado='A'
                  AND ((:tipo='Natural' AND clase.ObligatorioNatural=1)
                    OR (:tipo='Juridico' AND clase.ObligatorioJuridico=1))
                  AND NOT EXISTS (
                    SELECT 1 FROM Clientes.ClienteArchivo AS archivo WITH (HOLDLOCK)
                    WHERE archivo.IdCliente=:id AND archivo.ClaseDocumento=clase.Codigo
                      AND archivo.Reemplazado=0 AND archivo.EstadoAnalisis='Limpio')
                ORDER BY clase.Codigo
            """),
            {"tipo": fila["TipoCliente"], "id": id_cliente},
        ).scalars()
        motivos.extend(f"ARCHIVO_OBLIGATORIO_FALTANTE:{codigo}" for codigo in faltantes)
    else:
        motivos.append("ARCHIVOS_NO_EXIGIDOS")
    return motivos


def cliente_habilitado(
    conn: Connection, id_cliente: int, fecha: date
) -> HabilitacionCliente:
    motivos = requisitos_cliente(conn, id_cliente, fecha)
    return HabilitacionCliente(
        habilitado=all(m == "ARCHIVOS_NO_EXIGIDOS" for m in motivos),
        motivos=motivos,
    )


def activar_si_cumple(
    conn: Connection,
    id_cliente: int,
    fecha: date,
    actor: int,
    ip: str,
    solicitud_en_aplicacion: int | None = None,
) -> bool:
    """Activa al cliente si está en estado Pendiente y cumple todos los requisitos.

    E5-08 debe llamarla cuando un archivo obligatorio quede Limpio.
    """
    fila = (
        conn.execute(
            text("""
            SELECT Estado FROM Clientes.Cliente WITH (UPDLOCK, HOLDLOCK)
            WHERE IdCliente = :id
        """),
            {"id": id_cliente},
        )
        .mappings()
        .first()
    )
    if fila is None or fila["Estado"] != "Pendiente":
        return False

    motivos = requisitos_cliente(conn, id_cliente, fecha, solicitud_en_aplicacion)
    pendientes = [
        m for m in motivos if m not in ("CLIENTE_NO_ACTIVO", "ARCHIVOS_NO_EXIGIDOS")
    ]
    if pendientes:
        return False

    resultado = conn.execute(
        text("""
        UPDATE Clientes.Cliente
        SET Estado = 'Activo'
        WHERE IdCliente = :id AND Estado = 'Pendiente'
    """),
        {"id": id_cliente},
    )
    if resultado.rowcount != 1:
        return False

    from app.modules.clientes import repository

    observaciones = repository.observaciones_cambio(
        "Pendiente", "Activo", "Habilitado: requisitos cumplidos"
    )
    repository.insertar_historial_cliente(
        conn,
        id_cliente=id_cliente,
        tipo_operacion="U",
        campo="Estado",
        modificado_por=actor,
        direccion_ip=ip,
        observaciones=observaciones,
        valor_anterior="Pendiente",
        valor_nuevo="Activo",
    )
    return True
