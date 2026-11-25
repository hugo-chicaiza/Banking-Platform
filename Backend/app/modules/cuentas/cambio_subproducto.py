"""Cambio de subproducto sujeto a aprobación, con reclasificación de CAPITAL."""

from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import ConfigDict, Field
from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.core.api.schemas import CamelModel
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.clientes import repository as clientes
from app.modules.clientes.relaciones import edad_en, edad_mayoria
from app.modules.contabilidad.asientos import (
    ErrorContable,
    OperacionContable,
    generar_asiento,
)
from app.modules.contabilidad.cuentas_producto import cuenta_contable
from app.modules.contabilidad.service import ahora_ecuador, resolver_id_fecha_contable
from app.modules.cuentas.repository import bloquear_cuenta, obtener_titular_cuenta
from app.modules.productos.schemas import FichaSubProducto
from app.modules.productos.service import cliente_elegible, ficha_subproducto

CODIGO = "CTA-SUBPRODUCTO"
ROLES = ("ASESOR",)
Id = Annotated[int, Field(strict=True, gt=0, le=2_147_483_647)]


class Destino(CamelModel):
    model_config = ConfigDict(extra="forbid")
    id_sub_producto: Id


class Comparacion(CamelModel):
    actual: FichaSubProducto
    destinos: list[FichaSubProducto]


class CambioAprobable(Destino):
    realizado_por: Id


def _actual(conn: Connection, objetivo: Objetivo, *, bloquear: bool = False):
    id_cuenta = int(objetivo.id)
    if bloquear:
        titular = obtener_titular_cuenta(conn, id_cuenta)
        if titular is None or clientes.bloquear_cliente(conn, titular) is None:
            raise problema(
                404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia activa."
            )
        bloquear_cuenta(conn, id_cuenta)
    fila = (
        conn.execute(
            text("""
            SELECT c.IdCuenta,c.IdCliente,c.IdSubProducto,c.Estado,c.Saldo,c.SaldoRetenido,
                   c.IdAgencia,p.IdTipoProducto,cl.FechaNacimiento
            FROM Cuentas.Cuenta c
            JOIN ProductosFinancieros.Producto p ON p.IdProducto=c.IdProducto
            JOIN Clientes.Cliente cl ON cl.IdCliente=c.IdCliente
            WHERE c.IdCuenta=:cuenta AND c.IdAgencia=:agencia
        """),
            {"cuenta": id_cuenta, "agencia": objetivo.agencia},
        )
        .mappings()
        .one_or_none()
    )
    if fila is None:
        raise problema(
            404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia activa."
        )
    if fila["Estado"] in {"PendienteDeposito", "Cerrada", "Anulada"}:
        raise problema(
            409,
            "TRANSICION_INVALIDA",
            "El estado de la cuenta impide cambiar el subproducto.",
        )
    return fila


def _validar(conn: Connection, actual, destino: int, fecha: date) -> int:
    fila = (
        conn.execute(
            text("""
            SELECT p.IdProducto,p.IdTipoProducto
            FROM ProductosFinancieros.SubProducto s WITH (HOLDLOCK)
            JOIN ProductosFinancieros.Producto p WITH (HOLDLOCK) ON p.IdProducto=s.IdProducto
            WHERE s.IdSubProducto=:destino
        """),
            {"destino": destino},
        )
        .mappings()
        .one_or_none()
    )
    if fila is None or fila["IdTipoProducto"] != actual["IdTipoProducto"]:
        raise problema(
            422,
            "SUBPRODUCTO_NO_COMPATIBLE",
            "El destino debe ser del mismo tipo de producto.",
        )
    if destino == actual["IdSubProducto"]:
        raise problema(
            422, "SUBPRODUCTO_NO_COMPATIBLE", "Seleccione un subproducto distinto."
        )
    elegible, motivos = cliente_elegible(conn, actual["IdCliente"], destino, fecha)
    if not elegible:
        raise problema(
            422,
            "SUBPRODUCTO_NO_ELEGIBLE",
            "El cliente no reúne los requisitos del destino.",
            bloqueos=motivos,
        )
    return fila["IdProducto"]


def destinos(conn: Connection, objetivo: Objetivo, fecha: date) -> Comparacion:
    actual = _actual(conn, objetivo)
    ids = (
        conn.execute(
            text("""
            SELECT s.IdSubProducto
            FROM ProductosFinancieros.SubProducto s
            JOIN ProductosFinancieros.Producto p ON p.IdProducto=s.IdProducto
            WHERE p.IdTipoProducto=:tipo AND s.IdSubProducto<>:actual
              AND s.Estado='A' AND p.Estado='A'
            ORDER BY s.IdSubProducto
        """),
            {"tipo": actual["IdTipoProducto"], "actual": actual["IdSubProducto"]},
        )
        .scalars()
        .all()
    )
    return Comparacion(
        actual=ficha_subproducto(conn, actual["IdSubProducto"]),
        destinos=[
            ficha_subproducto(conn, id_sub)
            for id_sub in ids
            if cliente_elegible(conn, actual["IdCliente"], id_sub, fecha)[0]
        ],
    )


def _validar_sin_retenciones(conn: Connection, actual) -> None:
    # La cuenta ya está bloqueada. Una orden puede seguir activa con monto cero.
    activa = actual["SaldoRetenido"] != 0
    if (
        not activa
        and conn.exec_driver_sql(
            "SELECT OBJECT_ID(N'Cuentas.Retencion', N'U')"
        ).scalar()
    ):
        activa = (
            conn.execute(
                text("""
                SELECT TOP (1) 1 FROM Cuentas.Retencion WITH (HOLDLOCK)
                WHERE IdCuenta=:cuenta AND Estado='Activa'
            """),
                {"cuenta": actual["IdCuenta"]},
            ).scalar()
            is not None
        )
    if activa:
        raise problema(
            409,
            "CUENTA_CON_RETENCIONES_ACTIVAS",
            "Resuelva las retenciones de la cuenta antes de cambiar su subproducto.",
        )


class CambioSubproducto:
    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict, hoy: date
    ) -> Plan:
        cambio = CambioAprobable.model_validate(contenido)
        actual = _actual(conn, objetivo, bloquear=True)
        _validar_sin_retenciones(conn, actual)
        _validar(conn, actual, cambio.id_sub_producto, hoy)
        anterior = actual["IdSubProducto"]
        return Plan(
            cambio.model_dump(mode="json"),
            {"idSubProducto": anterior},
            {"idSubProducto": cambio.id_sub_producto},
            str(anterior),
        )

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        actual = _actual(conn, objetivo, bloquear=True)
        return str(actual["IdSubProducto"])

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict,
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        cambio = CambioAprobable.model_validate(contenido)
        actual = _actual(conn, objetivo, bloquear=True)
        _validar_sin_retenciones(conn, actual)
        ahora = ahora_ecuador()
        fecha = ahora.date()
        nuevo_producto = _validar(conn, actual, cambio.id_sub_producto, fecha)
        saldo_capital = actual["Saldo"]
        anterior = actual["IdSubProducto"]
        destino = cambio.id_sub_producto
        nacimiento = actual["FechaNacimiento"]
        if nacimiento is not None and edad_en(nacimiento, fecha) >= edad_mayoria(
            conn, fecha
        ):
            conn.execute(
                text("""
                    UPDATE Cuentas.CuentaAutorizado SET FechaFin=:fecha,RevocadoEn=SYSUTCDATETIME()
                    WHERE IdCuenta=:cuenta AND Rol='Tutor' AND RevocadoEn IS NULL
                      AND FechaInicio<=:fecha AND (FechaFin IS NULL OR FechaFin>=:fecha)
                """),
                {"cuenta": int(objetivo.id), "fecha": fecha},
            )
        asiento = None
        if saldo_capital:
            capital_origen = cuenta_contable(conn, anterior, "CAPITAL", fecha)
            capital_destino = cuenta_contable(conn, destino, "CAPITAL", fecha)
            if capital_origen != capital_destino:
                id_fecha = resolver_id_fecha_contable(conn, ahora)
                try:
                    asiento = generar_asiento(
                        conn,
                        OperacionContable(
                            "CUENTAS_RECLASIFICACION",
                            f"CTA-SUBPRODUCTO:{id_solicitud}",
                            actual["IdAgencia"],
                            id_fecha,
                            cambio.realizado_por,
                            ahora,
                            {"PRINCIPAL": saldo_capital, "RETENIDO": Decimal(0)},
                            cuentas_por_rol={
                                ("PRODUCTO", "CAPITAL"): capital_origen,
                                ("CONTRAPRODUCTO", "CAPITAL"): capital_destino,
                            },
                        ),
                    )
                except ErrorContable as exc:
                    raise problema(
                        503,
                        "RECLASIFICACION_CONTABLE_NO_DISPONIBLE",
                        "La reclasificación contable no se pudo registrar.",
                    ) from exc
        conn.execute(
            text("""
            UPDATE Cuentas.Cuenta SET IdProducto=:producto,IdSubProducto=:destino
            WHERE IdCuenta=:cuenta;
            INSERT Cuentas.CuentaEvento
              (IdCuenta,TipoEvento,EstadoAnterior,EstadoActual,Detalle,RealizadoPor,IdAgencia)
            VALUES (:cuenta,'CambioSubproducto',:estado,:estado,:detalle,:actor,:agencia);
        """),
            {
                "producto": nuevo_producto,
                "destino": destino,
                "cuenta": int(objetivo.id),
                "estado": actual["Estado"],
                "actor": cambio.realizado_por,
                "agencia": actual["IdAgencia"],
                "detalle": f"Subproducto {anterior} a {destino}. Solicitud {id_solicitud}."
                + (f" Asiento {asiento}." if asiento is not None else ""),
            },
        )


OPERACION = Operacion(
    CODIGO,
    "Cuenta",
    "cooperativa",
    frozenset(ROLES),
    "cuentas:aprobar",
    CambioSubproducto(),
    tabla_auditada="Cuentas.Cuenta",
    evento_ejecucion="CTA_CAMBIO_SUBPRODUCTO",
    solicitud_directa=False,
)
