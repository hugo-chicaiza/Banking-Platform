"""E3-06: lista de activación de un subproducto y reglas de retiro.

La lista consulta las plantillas que tienen un contrato contable confirmado.
"""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from sqlalchemy import Connection, text

from app.core.api.errors import ProblemDetailsRoute, problema
from app.core.api.schemas import CamelModel
from app.core.database.db import cooperativa
from app.core.security.auth import Usuario, require_auth, require_permiso
from app.modules.parametros.service import hoy

# Tipos cuyo dinero entra por canales: necesitan cupos en al menos uno.
TIPOS_CON_CUPOS = ("CUENTA_AHORRO", "CUENTA_CORRIENTE")

# E4-01 documenta CAJA_DEPOSITO para depósitos en ventanilla en cuentas de ahorro.
# La matriz exhaustiva de operaciones por producto todavía está pendiente.
_PLANTILLAS_CONFIRMADAS = {"CUENTA_AHORRO": ("CAJA_DEPOSITO",)}

DESCRIPCION = {
    "PRODUCTO_ACTIVO": "El producto está activo",
    "CONDICIONES": "Condiciones vigentes o programadas",
    "CUPOS": "Cupos en al menos un canal activo",
    "CUENTAS_CONTABLES": "Cuentas contables de los roles obligatorios",
    "NUMERACION": "Regla de numeración de cuentas",
    "ELEGIBILIDAD": "Elegibilidad verificable",
    "PLANTILLAS": "Plantillas de asiento de sus operaciones",
}


def _sub(conn: Connection, id_sub: int) -> dict[str, Any]:
    fila = (
        conn.execute(
            text("""
            SELECT s.IdSubProducto, s.CodigoSubProducto, s.EdadMinima, s.EdadMaxima,
                   s.RequiereTutor, s.TipoClientePermitido, p.EstadoProducto,
                   t.Codigo AS CodigoTipo, t.GeneraNumeroCuenta
            FROM ProductosFinancieros.SubProducto s
            JOIN ProductosFinancieros.Producto p ON p.IdProducto = s.IdProducto
            JOIN ProductosFinancieros.TipoProducto t ON t.IdTipoProducto = p.IdTipoProducto
            WHERE s.IdSubProducto = :id
        """),
            {"id": id_sub},
        )
        .mappings()
        .first()
    )
    if fila is None:
        raise problema(404, "SUBPRODUCTO_NO_ENCONTRADO", "El subproducto no existe.")
    return dict(fila)


def _existe(conn: Connection, sql: str, **p: Any) -> bool:
    return conn.execute(text(sql), p).first() is not None


def _plantillas(
    conn: Connection, codigo_tipo: str, fecha: date
) -> tuple[str, bool | None, str]:
    from app.modules.contabilidad.repository import obtener_plantilla

    faltantes = [
        codigo
        for codigo in _PLANTILLAS_CONFIRMADAS.get(codigo_tipo, ())
        if obtener_plantilla(conn, codigo, fecha) is None
    ]
    if faltantes:
        return "PLANTILLAS", False, "Sin vigencia: " + ", ".join(faltantes) + "."
    return (
        "PLANTILLAS",
        None,
        "Pendiente de confirmar todas las operaciones contables de este tipo de producto.",
    )


def lista(conn: Connection, id_sub: int, fecha: date) -> list[dict[str, Any]]:
    """Cada punto con `cumple`: True, False o None (no verificable todavía)."""
    from app.modules.contabilidad.cuentas_producto import roles_faltantes

    s = _sub(conn, id_sub)
    vigente = {"id": id_sub, "fecha": fecha}
    puntos: list[tuple[str, bool | None, str | None]] = [
        (
            "PRODUCTO_ACTIVO",
            s["EstadoProducto"] == "Activo",
            None
            if s["EstadoProducto"] == "Activo"
            else f"El producto está en {s['EstadoProducto']}.",
        ),
        (
            "CONDICIONES",
            _existe(
                conn,
                """SELECT 1 FROM ProductosFinancieros.SubProductoCondicion WHERE IdSubProducto=:id
                   AND Estado IN ('Vigente','Programada') AND (VigenciaHasta IS NULL OR VigenciaHasta >= :fecha)""",
                **vigente,
            ),
            None,
        ),
    ]
    if s["CodigoTipo"] in TIPOS_CON_CUPOS:
        puntos.append(
            (
                "CUPOS",
                _existe(
                    conn,
                    """SELECT 1 FROM ProductosFinancieros.ProductoCanalCupo c JOIN Canal.Canal a ON a.IdCanal=c.IdCanal
                       WHERE c.IdSubProducto=:id AND c.EstadoCupo='A' AND a.Estado='A'
                         AND (c.VigenciaHasta IS NULL OR c.VigenciaHasta >= :fecha)""",
                    **vigente,
                ),
                None,
            )
        )
    faltan = roles_faltantes(conn, id_sub, fecha)
    puntos.append(
        (
            "CUENTAS_CONTABLES",
            not faltan,
            ("Faltan: " + ", ".join(faltan) + ".") if faltan else None,
        )
    )
    if s["GeneraNumeroCuenta"]:
        puntos.append(
            (
                "NUMERACION",
                _existe(
                    conn,
                    "SELECT 1 FROM ProductosFinancieros.ReglaNumeracion WHERE IdSubProducto=:id AND Estado='A'",
                    id=id_sub,
                ),
                None,
            )
        )
    motivo = None
    if (
        s["EdadMinima"] is not None
        and s["EdadMaxima"] is not None
        and s["EdadMinima"] > s["EdadMaxima"]
    ):
        motivo = "La edad mínima supera la máxima."
    elif s["RequiereTutor"] and not _existe(
        conn,
        """SELECT 1 FROM Catalogo.TipoRelacionCliente
           WHERE Codigo='Tutor' AND Estado='A'
             AND OBJECT_ID(N'Clientes.ClienteRelacion', N'U') IS NOT NULL""",
    ):
        motivo = "La relación Tutor debe estar disponible en el catálogo de clientes."
    puntos.append(("ELEGIBILIDAD", motivo is None, motivo))
    puntos.append(_plantillas(conn, s["CodigoTipo"], fecha))
    return [
        {"codigo": c, "descripcion": DESCRIPCION[c], "cumple": ok, "detalle": d}
        for c, ok, d in puntos
    ]


def faltantes(conn: Connection, id_sub: int, fecha: date) -> list[dict[str, Any]]:
    return [p for p in lista(conn, id_sub, fecha) if p["cumple"] is not True]


def exigir_activacion(conn: Connection, id_sub: int, fecha: date | None = None) -> None:
    pendientes = faltantes(conn, id_sub, fecha or hoy())
    if pendientes:
        raise problema(
            409,
            "ACTIVACION_INCOMPLETA",
            "No se puede activar: "
            + "; ".join(
                p["descripcion"] + (f" ({p['detalle']})" if p["detalle"] else "")
                for p in pendientes
            )
            + ".",
        )


# Consultas fijas (sin SQL armado): ¿queda algo abierto del subproducto o de cualquiera de
# los subproductos del producto?
_ABIERTOS = {
    "cuentas": """
        SELECT TOP (1) 1 FROM Cuentas.Cuenta
        WHERE (IdSubProducto = :sub OR IdSubProducto IN (
                SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE IdProducto = :prod))
          AND Estado NOT IN ('Cerrada', 'Cancelada')
    """,
    "tarjetas": """
        SELECT TOP (1) 1 FROM Tarjeta.Tarjeta
        WHERE (IdSubProducto = :sub OR IdSubProducto IN (
                SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE IdProducto = :prod))
          AND Estado NOT IN ('Cancelada', 'Rechazada', 'Anulada')
    """,
    "créditos": """
        SELECT TOP (1) 1 FROM Credito.CreditoSolicitud
        WHERE (IdSubProducto = :sub OR IdSubProducto IN (
                SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE IdProducto = :prod))
          AND Estado NOT IN ('DESISTIDA', 'RECHAZADA', 'CANCELADA', 'ANULADA')
    """,
}


def exigir_retiro(
    conn: Connection, id_sub: int | None = None, id_producto: int | None = None
) -> None:
    """Retirar es final: sin cuentas, tarjetas ni créditos abiertos del subproducto o producto."""
    p = {"sub": id_sub, "prod": id_producto}
    abiertos = [nombre for nombre, sql in _ABIERTOS.items() if _existe(conn, sql, **p)]
    if abiertos:
        raise problema(
            409,
            "PRODUCTO_CON_CUENTAS",
            "No se puede retirar: tiene "
            + ", ".join(abiertos)
            + " abiertos. Suspéndalo para dejar de venderlo.",
        )


# ---------- Consulta de la lista ----------

router = APIRouter(
    route_class=ProblemDetailsRoute, dependencies=[Depends(require_auth)]
)
Lector = Annotated[Usuario, Depends(require_permiso("prd-consultar"))]


class PuntoActivacion(CamelModel):
    codigo: str
    descripcion: str
    cumple: bool | None
    detalle: str | None


class ListaActivacion(CamelModel):
    completa: bool
    puntos: list[PuntoActivacion]


@router.get("/subproductos/{id_sub}/activacion", response_model=ListaActivacion)
def consultar_activacion(
    id_sub: Annotated[int, Path(gt=0, le=2147483647)],
    _: Lector,
    conn: Annotated[Connection, Depends(cooperativa)],
) -> dict[str, Any]:
    """Lo que falta para activar el subproducto."""
    puntos = lista(conn, id_sub, hoy())
    return {"completa": all(p["cumple"] is True for p in puntos), "puntos": puntos}
