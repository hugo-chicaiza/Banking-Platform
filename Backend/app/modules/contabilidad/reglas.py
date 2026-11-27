"""Consulta de reglas. La contabilización sigue a cargo de cada productor."""

from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import Connection, text

from . import repository
from .boveda_versionada import ambito_boveda
from .service import ahora_ecuador


class Regla(BaseModel):
    idRegla: str
    Origen: str
    CodigoTipoAsiento: str | None
    configurada: Literal[True]
    desde: str | None
    hacia: str | None
    consumidor: str | None
    integracion: Literal["CONECTADA", "PENDIENTE", "SIN_VERIFICAR"]


class ReglaVersionada(Regla):
    fuente: Literal["PLANTILLA_ASIENTO"]
    versionada: Literal[True]
    IdPlantillaAsiento: int
    CodigoPlantilla: str
    Version: int
    Nombre: str
    VigenciaDesde: date
    VigenciaHasta: date | None
    Estado: bool
    CodigoConcepto: str | None
    Prioridad: int | None
    vigente: bool | None
    Usada: bool
    IdAgencia: str | None


class ReglaBoveda(Regla):
    fuente: Literal["PLANTILLA_BOVEDA"]
    versionada: Literal[False]
    IdAgencia: str
    TipoMovimiento: str
    Naturaleza: Literal["I", "E"]
    EstadoTipo: str | None
    EsManual: bool | None
    Debe: str | None
    Haber: str | None
    Habilitada: bool
    Version: None
    vigente: None


class CatalogoReglas(BaseModel):
    fechaContable: date | None
    matrizBovedaDisponible: bool
    reglas: list[
        Annotated[ReglaVersionada | ReglaBoveda, Field(discriminator="fuente")]
    ]


_FLUJOS_VERSIONADOS = {
    "DOT_CAJA": ("BOVEDA", "CAJA", "CAJ-07"),
    "DEV_CAJA": ("CAJA", "BOVEDA", "CAJ-15"),
    "DOT_ATM": ("BOVEDA", "ATM", None),
    "CAJA_DEPOSITO": ("CLIENTE", "CUENTA", None),
    "RET_EFECTIVO_CAJA": ("CUENTA", "CLIENTE", None),
    "RET_EFECTIVO_ATM": ("CUENTA", "CLIENTE", None),
    "DEV_ATM": ("ATM", "BOVEDA", None),
    "CAJA_FALTANTE": ("CAJA", "DIFERENCIA_ARQUEO", None),
    "CAJA_SOBRANTE": ("DIFERENCIA_ARQUEO", "CAJA", None),
    "ATM_FALTANTE": ("ATM", "DIFERENCIA_ARQUEO", None),
    "ATM_SOBRANTE": ("DIFERENCIA_ARQUEO", "ATM", None),
    "CUENTAS_TRANSFERENCIA_INTERNA": ("CUENTA", "CUENTA", None),
    "CUENTAS_COMISION": ("CUENTA", "INGRESO_COMISION", None),
    "CREDITO_DESEMBOLSO_CUENTA": ("CARTERA", "CUENTA", None),
    "CREDITO_PAGO_CUENTA": ("CUENTA", "CARTERA", None),
    "CUENTAS_INTERES_DEVENGO": ("GASTO_INTERES", "INTERES_POR_PAGAR", None),
    "CUENTAS_INTERES_CAPITALIZACION": ("INTERES_POR_PAGAR", "CUENTA", None),
    "CREDITO_INTERES_DEVENGO": ("CARTERA", "INGRESO_INTERES", None),
    "CUENTAS_RETENCION": ("CUENTA", "DEPOSITO_RESTRINGIDO", "E6-05"),
    "CUENTAS_LIBERACION": ("DEPOSITO_RESTRINGIDO", "CUENTA", "E6-05"),
    "CUENTAS_RECLASIFICACION": ("CUENTA", "CUENTA", "E6-06"),
    "CREDITO_SEGURO_COBRO_CUENTA": ("CUENTA", "SEGURO_POR_PAGAR", None),
}
_FLUJOS_BOVEDA = {
    ("Traslado", "E"): ("BOVEDA", "EFECTIVO_EN_TRANSITO", "BOV-04"),
    ("Traslado", "I"): ("EFECTIVO_EN_TRANSITO", "BOVEDA", "BOV-04"),
    ("ProvisionExterna", "I"): ("EXTERNO", "BOVEDA", "BOV-04"),
    ("EnvioExcedente", "E"): ("BOVEDA", "EXTERNO", "BOV-04"),
    ("AjusteFaltante", "E"): ("BOVEDA", "CUENTAS_POR_COBRAR_CAJERO", "BOV-05"),
    ("AjusteSobrante", "I"): ("SOBRANTES_POR_REGULARIZAR", "BOVEDA", "BOV-05"),
    ("ReposicionFaltante", "I"): ("CUENTAS_POR_COBRAR_CAJERO", "BOVEDA", "BOV-05"),
    ("JustificaFaltante", "E"): (
        "CUENTAS_POR_COBRAR_CAJERO",
        "REGULARIZACION_FALTANTE",
        "BOV-05",
    ),
    ("DescuentoFaltante", "E"): (
        "CUENTAS_POR_COBRAR_CAJERO",
        "NOMINA_POR_PAGAR",
        "BOV-05",
    ),
}


def listar_reglas(
    conn: Connection, agencia: str | None, fecha: date | None
) -> dict[str, Any]:
    if fecha is None:
        id_fecha = repository.id_fecha_contable(conn, ahora_ecuador())
        calendario = repository.obtener_por_id(conn, id_fecha) if id_fecha else None
        fecha = calendario["fecha"] if calendario else None
    versiones = conn.execute(
        text("""
        WITH elegibles AS (
            SELECT p.IdPlantillaAsiento, ROW_NUMBER() OVER (
                PARTITION BY p.CodigoPlantilla ORDER BY p.VigenciaDesde DESC, p.Version DESC
            ) AS Prioridad
            FROM Contabilidad.PlantillaAsiento p
            JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento = p.IdTipoAsiento
            WHERE p.Estado = 1 AND t.Estado = 'A' AND t.EsManual = 0
              AND p.VigenciaDesde <= :fecha AND (p.VigenciaHasta >= :fecha OR p.VigenciaHasta IS NULL)
        )
        SELECT p.IdPlantillaAsiento, p.CodigoPlantilla, p.Version, p.Nombre, p.Origen,
               p.VigenciaDesde, p.VigenciaHasta, p.Estado, t.Codigo AS CodigoTipoAsiento,
               c.CodigoConcepto, e.Prioridad,
               CAST(CASE WHEN EXISTS (SELECT 1 FROM Contabilidad.AsientoContable a
                   WHERE a.IdPlantillaAsiento = p.IdPlantillaAsiento) THEN 1 ELSE 0 END AS bit) AS Usada
        FROM Contabilidad.PlantillaAsiento p
        LEFT JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento = p.IdTipoAsiento
        LEFT JOIN Contabilidad.ConceptoContable c ON c.IdConceptoContable = p.IdConceptoContable
        LEFT JOIN elegibles e ON e.IdPlantillaAsiento = p.IdPlantillaAsiento
        ORDER BY p.CodigoPlantilla, p.Version DESC, p.IdPlantillaAsiento DESC
        """),
        {"fecha": fecha},
    ).mappings()
    reglas = []
    for fila in versiones:
        codigo = fila["CodigoPlantilla"]
        desde, hacia, consumidor = _FLUJOS_VERSIONADOS.get(codigo, (None, None, None))
        ambito = ambito_boveda(codigo)
        if ambito:
            if agencia is not None and agencia != ambito[0]:
                continue
            desde, hacia, consumidor = next(
                flujo
                for (tipo, lado), flujo in _FLUJOS_BOVEDA.items()
                if tipo.upper() == ambito[1] and lado == ambito[2]
            )
        reglas.append(
            {
                **fila,
                "idRegla": f"plantilla:{fila['IdPlantillaAsiento']}",
                "fuente": "PLANTILLA_ASIENTO",
                "IdAgencia": ambito[0] if ambito else None,
                "versionada": True,
                "configurada": True,
                "vigente": fila["Prioridad"] == 1 if fecha is not None else None,
                "desde": desde,
                "hacia": hacia,
                "consumidor": consumidor,
                "integracion": "CONECTADA"
                if consumidor
                else (
                    "PENDIENTE" if codigo in _FLUJOS_VERSIONADOS else "SIN_VERIFICAR"
                ),
            }
        )

    matriz_disponible = bool(
        conn.execute(
            text("SELECT OBJECT_ID('Contabilidad.PlantillaBoveda', 'U')")
        ).scalar()
    )
    if matriz_disponible:
        filas = conn.execute(
            text("""
            SELECT RTRIM(p.IdAgencia) AS IdAgencia, p.TipoMovimiento, p.Naturaleza,
                   t.Codigo AS CodigoTipoAsiento, t.Estado AS EstadoTipo, t.EsManual,
                   d.CodigoCuenta AS Debe, h.CodigoCuenta AS Haber,
                   CAST(CASE WHEN t.Estado = 'A' AND t.EsManual = 0
                     AND d.Estado = 1 AND d.EsImputable = 1 AND h.Estado = 1 AND h.EsImputable = 1
                     AND NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables x
                          WHERE x.IdCuentaSuperior IN (p.IdCuentaDebito, p.IdCuentaCredito))
                     THEN 1 ELSE 0 END AS bit) AS Habilitada
            FROM Contabilidad.PlantillaBoveda p
            LEFT JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento = p.IdTipoAsiento
            LEFT JOIN Contabilidad.CuentasContables d ON d.IdCuentaContable = p.IdCuentaDebito
            LEFT JOIN Contabilidad.CuentasContables h ON h.IdCuentaContable = p.IdCuentaCredito
            WHERE :agencia IS NULL OR p.IdAgencia = :agencia
            ORDER BY p.IdAgencia, p.TipoMovimiento, p.Naturaleza
            """),
            {"agencia": agencia},
        ).mappings()
        for fila in filas:
            tipo, naturaleza = fila["TipoMovimiento"], fila["Naturaleza"]
            desde, hacia, consumidor = _FLUJOS_BOVEDA.get(
                (tipo, naturaleza), (None, None, None)
            )
            reglas.append(
                {
                    **fila,
                    "idRegla": f"boveda:{fila['IdAgencia']}:{tipo}:{naturaleza}",
                    "fuente": "PLANTILLA_BOVEDA",
                    "Origen": "BOVEDA",
                    "Version": None,
                    "versionada": False,
                    "configurada": True,
                    "vigente": None,
                    "desde": desde,
                    "hacia": hacia,
                    "consumidor": consumidor,
                    "integracion": "CONECTADA" if consumidor else "SIN_VERIFICAR",
                }
            )
    return {
        "fechaContable": fecha,
        "matrizBovedaDisponible": matriz_disponible,
        "reglas": reglas,
    }
