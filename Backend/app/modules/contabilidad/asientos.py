"""Contabilización automática dentro de la transacción del módulo de origen."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.modules.contabilidad import repository


@dataclass(frozen=True)
class OperacionContable:
    codigo_plantilla: str
    clave_evento: str
    id_agencia: str
    id_fecha_contable: int
    id_usuario: int
    fecha_hora: datetime
    importes: Mapping[str, Decimal]
    id_transaccion: int | None = None
    cuentas_por_rol: Mapping[tuple[str, str | None], int] = field(default_factory=dict)


class ErrorContable(ValueError):
    """La operación no puede generar un asiento válido."""


def resolver_lineas(
    plantilla: list[dict[str, Any]],
    importes: Mapping[str, Decimal],
    *,
    conn: Connection | None = None,
    cuentas_por_rol: Mapping[tuple[str, str | None], int] | None = None,
) -> list[dict[str, Any]]:
    lineas = []
    debe = haber = Decimal(0)
    for detalle in plantilla:
        componente = detalle["ComponenteImporte"]
        monto = importes.get(componente)
        if (
            monto is None
            or not monto.is_finite()
            or monto < 0
            or monto >= Decimal(10000000000000000)
            or monto * 100 != (monto * 100).to_integral_value()
        ):
            raise ErrorContable(f"Importe ausente o inválido para {componente}.")
        if monto == 0:
            continue
        origen = detalle.get("OrigenCuenta", "FIJA")
        id_cuenta = detalle["IdCuentaContable"]
        cuenta = detalle
        if origen != "FIJA":
            id_cuenta = (cuentas_por_rol or {}).get((origen, detalle.get("CodigoRol")))
            cuenta = (
                repository.cuenta_para_plantilla(conn, id_cuenta)
                if conn is not None and id_cuenta is not None
                else None
            )
        if (
            cuenta is None
            or not cuenta["Estado"]
            or not cuenta["EsImputable"]
            or len(cuenta.get("CodigoCuenta", "00000000")) != 8
        ):
            raise ErrorContable("La cuenta debe ser un auxiliar activo e imputable.")
        lado = detalle["TipoMovimiento"]
        if lado == "DEBITO":
            debe += monto
        elif lado == "CREDITO":
            haber += monto
        else:
            raise ErrorContable("El tipo de movimiento contable no es válido.")
        lineas.append({"cuenta": id_cuenta, "lado": lado, "monto": monto})
    if debe != haber or debe <= 0 or len(lineas) < 2:
        raise ErrorContable("El asiento requiere líneas positivas y debe cuadrar.")
    return lineas


def generar_asiento(conn: Connection, operacion: OperacionContable) -> int:
    """Registra el asiento usando la conexión del llamador. Los errores se propagan."""
    if not conn.in_transaction():
        raise ErrorContable("La operación debe abrir una transacción de base de datos.")
    if (
        not operacion.clave_evento
        or operacion.clave_evento != operacion.clave_evento.strip()
        or len(operacion.clave_evento) > 100
        or len(operacion.id_agencia) != 3
    ):
        raise ErrorContable("La clave del evento o la agencia no es válida.")

    datos_huella: list[Any] = [
        operacion.codigo_plantilla,
        operacion.id_agencia,
        operacion.id_fecha_contable,
        operacion.id_transaccion,
        sorted(
            (clave, str(valor.normalize()) if valor else "0")
            for clave, valor in operacion.importes.items()
        ),
    ]
    if operacion.cuentas_por_rol:
        datos_huella.append(
            sorted(
                (origen, rol or "", cuenta)
                for (origen, rol), cuenta in operacion.cuentas_por_rol.items()
            )
        )
    huella = hashlib.sha256(
        json.dumps(datos_huella, separators=(",", ":")).encode()
    ).hexdigest()
    existente = repository.buscar_asiento_evento(conn, operacion.clave_evento)
    if existente is not None:
        if existente["HuellaEventoContable"] != huella or existente["Estado"] not in (
            "CONTABILIZADO",
            "REVERSADO",
        ):
            raise ErrorContable("La clave del evento ya corresponde a otro asiento.")
        return int(existente["IdAsientoContable"])

    calendario = repository.obtener_por_id(conn, operacion.id_fecha_contable)
    if (
        calendario is None
        or not calendario["es_dia_contable"]
        or not repository.periodo_abierto(conn, calendario["fecha"])
    ):
        raise ErrorContable("La fecha contable debe pertenecer a un período abierto.")

    plantilla = repository.obtener_plantilla(
        conn, operacion.codigo_plantilla, calendario["fecha"]
    )
    if plantilla is None or not plantilla["Estado"]:
        raise problema(
            409,
            "PLANTILLA_NO_DEFINIDA",
            "No existe plantilla vigente para la operación.",
        )
    id_plantilla = plantilla["IdPlantillaAsiento"]

    lineas = resolver_lineas(
        repository.obtener_lineas_plantilla(conn, id_plantilla),
        operacion.importes,
        conn=conn,
        cuentas_por_rol=operacion.cuentas_por_rol,
    )
    id_asiento = repository.insertar_asiento_automatico(
        conn,
        {
            "fecha": calendario["fecha"],
            "fecha_hora": operacion.fecha_hora,
            "agencia": operacion.id_agencia,
            "tipo": plantilla["IdTipoAsiento"],
            "origen": plantilla["Origen"],
            "nombre": plantilla["Nombre"],
            "usuario": operacion.id_usuario,
            "concepto": plantilla["IdConceptoContable"],
            "id_fecha": operacion.id_fecha_contable,
            "plantilla": id_plantilla,
            "evento": operacion.clave_evento,
            "huella": huella,
            "transaccion": operacion.id_transaccion,
            "original": None,
        },
    )
    repository.insertar_lineas_asiento(
        conn,
        [
            {
                **linea,
                "transaccion": operacion.id_transaccion,
                "agencia": operacion.id_agencia,
                "fecha_hora": operacion.fecha_hora,
                "asiento": id_asiento,
            }
            for linea in lineas
        ],
    )
    repository.contabilizar_asiento(conn, id_asiento)
    return id_asiento


def reversar(
    conn: Connection,
    id_asiento: int,
    motivo: str,
    *,
    actor: int,
    id_transaccion_reverso: int | None = None,
    id_transaccion_original: int | None = None,
) -> int:
    from app.modules.contabilidad.service import (
        ahora_ecuador,
        resolver_id_fecha_contable,
    )

    if not conn.in_transaction():
        raise ErrorContable("El reverso requiere la transacción del módulo de origen.")
    motivo = motivo.strip()
    if not motivo or len(motivo) > 300:
        raise problema(
            422, "MOTIVO_INVALIDO", "Indique un motivo de hasta 300 caracteres."
        )
    original = (
        conn.execute(
            text("""
        SELECT IdTipoAsiento, IdAgencia, IdConceptoContable, Origen, Estado,
               IdAsientoReversion, IdTransaccion
        FROM Contabilidad.AsientoContable WITH (UPDLOCK,HOLDLOCK)
        WHERE IdAsientoContable=:id
    """),
            {"id": id_asiento},
        )
        .mappings()
        .one_or_none()
    )
    if original is None:
        raise problema(404, "ASIENTO_NO_ENCONTRADO", "El asiento no existe.")
    if original["Estado"] == "REVERSADO":
        raise problema(409, "ASIENTO_YA_REVERSADO", "El asiento ya está reversado.")
    if (
        original["Estado"] != "CONTABILIZADO"
        or original["IdAsientoReversion"] is not None
    ):
        raise problema(
            409,
            "ASIENTO_NO_REVERSABLE",
            "El asiento debe ser un original contabilizado.",
        )
    detalle = repository.movimientos_asiento(conn, id_asiento)
    transacciones = {
        m["id_transaccion"] for m in detalle if m["id_transaccion"] is not None
    }
    if original["IdTransaccion"] is not None:
        transacciones.add(original["IdTransaccion"])
    if transacciones and (
        id_transaccion_reverso is None or transacciones != {id_transaccion_original}
    ):
        raise problema(
            409, "REVERSO_DE_OPERACION_REQUERIDO", "Reverse la operación de origen."
        )

    ahora = ahora_ecuador()
    id_fecha = resolver_id_fecha_contable(conn, ahora)
    dia = repository.obtener_por_id(conn, id_fecha)
    if (
        dia is None
        or not dia["es_dia_contable"]
        or not repository.periodo_abierto(conn, dia["fecha"])
    ):
        raise problema(
            409, "PERIODO_CONTABLE_NO_ABIERTO", "El período contable no está abierto."
        )
    espejo = repository.insertar_asiento_automatico(
        conn,
        {
            "fecha": dia["fecha"],
            "fecha_hora": ahora,
            "agencia": original["IdAgencia"],
            "tipo": original["IdTipoAsiento"],
            "origen": original["Origen"],
            "nombre": motivo,
            "usuario": actor,
            "concepto": original["IdConceptoContable"],
            "id_fecha": id_fecha,
            "plantilla": None,
            "evento": None,
            "huella": None,
            "transaccion": id_transaccion_reverso,
            "original": id_asiento,
        },
    )
    repository.insertar_lineas_asiento(
        conn,
        [
            {
                "cuenta": m["id_cuenta_contable"],
                "transaccion": id_transaccion_reverso,
                "agencia": m["id_agencia"],
                "lado": "CREDITO" if m["tipo_movimiento"] == "DEBITO" else "DEBITO",
                "monto": m["monto"],
                "fecha_hora": ahora,
                "asiento": espejo,
            }
            for m in detalle
        ],
    )
    repository.contabilizar_asiento(conn, espejo)
    conn.execute(
        text("""
        UPDATE Contabilidad.AsientoContable SET Estado='REVERSADO' WHERE IdAsientoContable=:id
    """),
        {"id": id_asiento},
    )
    return espejo
