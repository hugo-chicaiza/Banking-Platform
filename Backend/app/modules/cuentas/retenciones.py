from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StringConstraints
from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.core.api.schemas import CamelModel
from app.modules.contabilidad.asientos import (
    ErrorContable,
    OperacionContable,
    generar_asiento,
)
from app.modules.contabilidad.cuentas_producto import cuenta_contable
from app.modules.contabilidad.service import ahora_ecuador, resolver_id_fecha_contable

Tipo = Literal["OrdenJudicial", "GarantiaCredito", "Administrativa"]
Motivo = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=250)
]


class Alta(CamelModel):
    model_config = ConfigDict(extra="forbid")
    tipo_retencion: Tipo
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    motivo: Motivo
    documento_referencia: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
    ]
    fecha_fin: date | None = None


class Liberacion(CamelModel):
    model_config = ConfigDict(extra="forbid")
    motivo: Motivo


class Retencion(CamelModel):
    id_retencion: int
    tipo_retencion: Tipo
    monto: Decimal
    motivo: str
    documento_referencia: str
    origen: Literal["Manual", "Modulo"]
    fecha_inicio: date
    fecha_fin: date | None
    estado: str
    id_solicitud: int | None
    id_asiento: int | None
    id_asiento_liberacion: int | None
    motivo_liberacion: str | None


def cuenta(conn: Connection, id_cuenta: int, agencia: str | None = None) -> dict:
    row = (
        conn.execute(
            text("""
        SELECT IdCuenta, RTRIM(IdAgencia) AS IdAgencia, IdSubProducto, Estado, Saldo, SaldoRetenido
        FROM Cuentas.Cuenta WITH (UPDLOCK,HOLDLOCK) WHERE IdCuenta=:id
    """),
            {"id": id_cuenta},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or (agencia is not None and row["IdAgencia"] != agencia):
        raise problema(
            404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia activa."
        )
    return dict(row)


def retencion(conn: Connection, id_retencion: int, id_cuenta: int) -> dict:
    row = (
        conn.execute(
            text("""
        SELECT * FROM Cuentas.Retencion WITH (UPDLOCK,HOLDLOCK)
        WHERE IdRetencion=:retencion AND IdCuenta=:cuenta
    """),
            {"retencion": id_retencion, "cuenta": id_cuenta},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise problema(
            404, "RETENCION_NO_ENCONTRADA", "La retención no existe en esta cuenta."
        )
    return dict(row)


def listar(conn: Connection, id_cuenta: int, agencia: str) -> list[Retencion]:
    cuenta(conn, id_cuenta, agencia)
    filas = conn.execute(
        text("""
        SELECT IdRetencion id_retencion, TipoRetencion tipo_retencion, Monto monto, Motivo motivo,
          DocumentoReferencia documento_referencia, Origen origen, FechaInicio fecha_inicio,
          FechaFin fecha_fin, Estado estado, IdSolicitud id_solicitud, IdAsiento id_asiento,
          IdAsientoLiberacion id_asiento_liberacion, MotivoLiberacion motivo_liberacion
        FROM Cuentas.Retencion WHERE IdCuenta=:id ORDER BY IdRetencion DESC
    """),
        {"id": id_cuenta},
    ).mappings()
    return [Retencion.model_validate(dict(fila)) for fila in filas]


def monto_aplicable(fila: dict, alta: Alta) -> Decimal:
    if fila["Estado"] != "Activa":
        raise problema(409, "CUENTA_NO_ACTIVA", "La cuenta debe estar activa.")
    disponible = fila["Saldo"] - fila["SaldoRetenido"]
    if disponible <= 0 and alta.tipo_retencion == "OrdenJudicial":
        return Decimal(0)
    if disponible < alta.monto and alta.tipo_retencion != "OrdenJudicial":
        raise problema(409, "SALDO_INSUFICIENTE", "La retención supera el disponible.")
    return min(disponible, alta.monto)


def _contabilizar(
    conn: Connection,
    fila: dict,
    actor: int,
    clave: str,
    monto: Decimal,
    *,
    alta: bool,
    asiento_original: int | None = None,
    subproducto_origen: int | None = None,
) -> int:
    ahora = ahora_ecuador()
    id_fecha = resolver_id_fecha_contable(conn, ahora)
    from app.modules.contabilidad.repository import obtener_por_id

    calendario = obtener_por_id(conn, id_fecha)
    if calendario is None:
        raise problema(409, "FECHA_CONTABLE_NO_CONFIGURADA", "Falta la fecha contable.")
    original = (
        _roles_originales(conn, asiento_original)
        if asiento_original is not None
        else None
    )
    capital = (
        original[0]
        if original is not None and subproducto_origen == fila["IdSubProducto"]
        else cuenta_contable(
            conn, fila["IdSubProducto"], "CAPITAL", calendario["fecha"]
        )
    )
    restringido = (
        original[1]
        if original is not None
        else cuenta_contable(
            conn, fila["IdSubProducto"], "RESTRINGIDO", calendario["fecha"]
        )
    )
    roles: dict[tuple[str, str | None], int] = {
        ("PRODUCTO", "CAPITAL"): capital,
        ("PRODUCTO", "RESTRINGIDO"): restringido,
    }
    if len(set(roles.values())) != 2:
        raise problema(
            409,
            "MAPEO_RETENCION_INVALIDO",
            "CAPITAL y RESTRINGIDO deben ser auxiliares distintos.",
        )
    try:
        asiento = generar_asiento(
            conn,
            OperacionContable(
                "CUENTAS_RETENCION" if alta else "CUENTAS_LIBERACION",
                clave,
                fila["IdAgencia"],
                id_fecha,
                actor,
                ahora,
                {"PRINCIPAL": monto},
                cuentas_por_rol=roles,
            ),
        )
    except ErrorContable as error:
        raise problema(
            409, "CONTABILIZACION_RETENCION_RECHAZADA", str(error)
        ) from error
    esperadas = (capital, restringido) if alta else (restringido, capital)
    if _roles_originales(conn, asiento, monto) != esperadas:
        raise problema(
            409,
            "ASIENTO_RETENCION_INVALIDO",
            "La plantilla no reclasificó los auxiliares requeridos.",
        )
    return asiento


def _roles_originales(
    conn: Connection, id_asiento: int, monto: Decimal | None = None
) -> tuple[int, int]:
    filas = conn.execute(
        text("""
        SELECT TipoMovimiento,IdCuentaContable,Monto FROM Contabilidad.MovimientosContables
        WHERE IdAsientoContable=:asiento
    """),
        {"asiento": id_asiento},
    ).all()
    por_lado = {lado: cuenta for lado, cuenta, _ in filas}
    if (
        len(filas) != 2
        or set(por_lado) != {"DEBITO", "CREDITO"}
        or (monto is not None and any(fila.Monto != monto for fila in filas))
    ):
        raise problema(
            409,
            "ASIENTO_RETENCION_INVALIDO",
            "La retención no tiene un asiento original válido.",
        )
    return int(por_lado["DEBITO"]), int(por_lado["CREDITO"])


def crear_retencion(
    conn: Connection,
    fila: dict,
    datos: Alta,
    actor: int,
    *,
    clave: str,
    solicitud: int | None = None,
    modulo: str | None = None,
) -> int:
    """Alta con la transacción abierta por la cola o por el módulo propietario."""
    registrado = conn.execute(
        text("""SELECT IdRetencion,IdCuenta,TipoRetencion,MontoSolicitado,Motivo,DocumentoReferencia,
                    ModuloOrigen,FechaFin,IdSolicitud,CreadoPor FROM Cuentas.Retencion WITH (UPDLOCK,HOLDLOCK)
                WHERE ClaveEvento=:clave"""),
        {"clave": clave},
    ).one_or_none()
    if registrado is not None:
        esperado = (
            fila["IdCuenta"],
            datos.tipo_retencion,
            datos.monto,
            datos.motivo,
            datos.documento_referencia,
            modulo,
            datos.fecha_fin,
            solicitud,
            actor,
        )
        if tuple(registrado)[1:] != esperado:
            raise problema(
                409,
                "RETENCION_CLAVE_REUTILIZADA",
                "La clave ya identifica otra retención.",
            )
        return int(registrado[0])
    fecha = ahora_ecuador().date()
    if datos.fecha_fin is not None and datos.fecha_fin < fecha:
        raise problema(409, "SOLICITUD_DESACTUALIZADA", "La fecha de término ya pasó.")
    if not conn.execute(
        text(
            "SELECT 1 FROM Catalogo.TipoRetencion WITH (HOLDLOCK) WHERE Codigo=:tipo AND Estado='A'"
        ),
        {"tipo": datos.tipo_retencion},
    ).scalar():
        raise problema(
            422, "TIPO_RETENCION_INACTIVO", "El tipo de retención no está activo."
        )
    monto = monto_aplicable(fila, datos)
    bloquea = datos.tipo_retencion == "OrdenJudicial" and monto < datos.monto
    asiento = (
        _contabilizar(conn, fila, actor, clave, monto, alta=True) if monto else None
    )
    if bloquea:
        conn.execute(
            text("""
           UPDATE Cuentas.Cuenta SET Estado='Bloqueada' WHERE IdCuenta=:id;
           INSERT Cuentas.CuentaEvento
             (IdCuenta,TipoEvento,EstadoAnterior,EstadoActual,Detalle,RealizadoPor,IdAgencia)
           VALUES (:id,'Bloqueo','Activa','Bloqueada',N'Orden judicial superior al saldo disponible',:actor,:agencia);
        """),
            {"id": fila["IdCuenta"], "actor": actor, "agencia": fila["IdAgencia"]},
        )
    if monto:
        conn.execute(
            text(
                "UPDATE Cuentas.Cuenta SET SaldoRetenido=SaldoRetenido+:monto WHERE IdCuenta=:id"
            ),
            {"monto": monto, "id": fila["IdCuenta"]},
        )
    return int(
        conn.execute(
            text("""
        INSERT Cuentas.Retencion (IdCuenta,IdSubProductoOrigen,TipoRetencion,Monto,MontoSolicitado,ClaveEvento,Motivo,DocumentoReferencia,Origen,ModuloOrigen,
            FechaInicio,FechaFin,Estado,IdSolicitud,IdAsiento,CreadoPor)
        OUTPUT inserted.IdRetencion
        VALUES (:cuenta,:subproducto,:tipo,:monto,:monto_solicitado,:clave,:motivo,:documento,:origen,:modulo,:fecha,:fin,'Activa',:solicitud,:asiento,:actor)
    """),
            {
                "cuenta": fila["IdCuenta"],
                "subproducto": fila["IdSubProducto"],
                "tipo": datos.tipo_retencion,
                "monto": monto,
                "monto_solicitado": datos.monto,
                "clave": clave,
                "motivo": datos.motivo,
                "documento": datos.documento_referencia,
                "origen": "Modulo" if modulo else "Manual",
                "modulo": modulo,
                "fecha": fecha,
                "fin": datos.fecha_fin,
                "solicitud": solicitud,
                "asiento": asiento,
                "actor": actor,
            },
        ).scalar_one()
    )


def liberar_retencion(
    conn: Connection,
    fila: dict,
    r: dict,
    actor: int,
    motivo: str,
    *,
    clave: str,
    solicitud: int | None = None,
    modulo: str | None = None,
    ejecutada: bool = False,
) -> int | None:
    if r["Origen"] == "Modulo" and (modulo is None or r["ModuloOrigen"] != modulo):
        raise problema(
            409,
            "RETENCION_DE_MODULO",
            "Solo el módulo de origen puede liberar esta retención.",
        )
    estado = "Ejecutada" if ejecutada else "Liberada"
    if (
        r["ClaveLiberacion"] == clave
        and r["Estado"] == estado
        and r["IdSolicitudLiberacion"] == solicitud
        and r["MotivoLiberacion"] == motivo
    ):
        return r["IdAsientoLiberacion"]
    if r["Estado"] != "Activa" or fila["SaldoRetenido"] < r["Monto"]:
        raise problema(
            409,
            "SOLICITUD_DESACTUALIZADA",
            "La retención ya no está vigente o su saldo cambió.",
        )
    if r["Monto"] and r["IdAsiento"] is None:
        raise problema(
            409,
            "ASIENTO_RETENCION_INVALIDO",
            "Falta el asiento original de la retención.",
        )
    asiento = (
        _contabilizar(
            conn,
            fila,
            actor,
            clave,
            r["Monto"],
            alta=False,
            asiento_original=r["IdAsiento"],
            subproducto_origen=r["IdSubProductoOrigen"],
        )
        if r["Monto"]
        else None
    )
    conn.execute(
        text("""
        UPDATE Cuentas.Retencion SET Estado=:estado,IdSolicitudLiberacion=:solicitud,ClaveLiberacion=:clave,
            IdAsientoLiberacion=:asiento,MotivoLiberacion=:motivo WHERE IdRetencion=:id;
        UPDATE Cuentas.Cuenta SET SaldoRetenido=SaldoRetenido-:monto WHERE IdCuenta=:cuenta;
    """),
        {
            "estado": estado,
            "clave": clave,
            "solicitud": solicitud,
            "asiento": asiento,
            "motivo": motivo,
            "id": r["IdRetencion"],
            "monto": r["Monto"],
            "cuenta": fila["IdCuenta"],
        },
    )
    return asiento


def ejecutar_retencion(
    conn: Connection,
    fila: dict,
    r: dict,
    actor: int,
    motivo: str,
    *,
    clave: str,
    modulo: str | None = None,
) -> int | None:
    """El consumidor registra su débito y su asiento en la misma transacción."""
    return liberar_retencion(
        conn, fila, r, actor, motivo, clave=clave, modulo=modulo, ejecutada=True
    )
