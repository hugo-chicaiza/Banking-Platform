"""E3-05: cuentas contables de los productos (clases por tipo, asignaciones y resolución).

Modelo de cuenta de control: cada rol de un tipo de producto se asigna una vez (a nivel de
tipo, o de producto para el capital de depósitos) y los productos y subproductos lo heredan;
el subproducto solo lleva una asignación propia como excepción. La resolución elige la
asignación vigente más específica: subproducto → producto → tipo.
"""

from datetime import date, timedelta
from typing import Any

from pydantic import ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import Connection, Engine, text

from app.core.api.errors import problema
from app.core.api.schemas import CamelModel
from app.modules.aprobaciones.motores import motor
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.catalogos.subproductos import tipo_tarjeta_de

CODIGO = "CON-MAPEO"
# Una tarjeta de crédito es cartera de consumo (CUC grupo 14): usa las clases de ese tipo.
TIPO_CREDITO_TARJETA = "CONSUMO"
AVISO_TARJETA_CREDITO = (
    "La emisión de tarjetas de crédito está habilitada para cooperativas del segmento 1; "
    "este subproducto se mantiene para la demostración."
)

Id = Field(gt=0, le=2147483647)


class Cambio(CamelModel):
    """Una asignación nueva (o el fin de una excepción si idCuentaContable es null)."""

    model_config = ConfigDict(extra="forbid")
    id_clase: int = Id
    id_producto: int | None = Field(default=None, gt=0, le=2147483647)
    id_sub_producto: int | None = Field(default=None, gt=0, le=2147483647)
    id_cuenta_contable: int | None = Field(default=None, gt=0, le=2147483647)
    vigencia_desde: date

    @model_validator(mode="after")
    def alcance(self) -> "Cambio":
        if self.id_producto is not None and self.id_sub_producto is not None:
            raise ValueError("Indique el producto o el subproducto, no ambos.")
        return self


class Solicitud(CamelModel):
    model_config = ConfigDict(extra="forbid")
    cambios: list[Cambio] = Field(min_length=1, max_length=200)


# ---------- Lecturas ----------

_CLASES = """
    SELECT k.IdClase, k.IdTipoProducto, t.Codigo AS CodigoTipoProducto, k.IdTipoCredito,
           tc.CodigoTipoCredito, k.CodigoRol, r.Nombre AS NombreRol, k.Situacion, k.Condicion,
           k.Tramo, k.CuentaBase, c.NombreCuenta AS NombreCuentaBase, k.Nivel, k.Obligatorio,
           k.SoloConTasa, k.Orden
    FROM Contabilidad.ClaseCuentaProducto k
    JOIN ProductosFinancieros.TipoProducto t ON t.IdTipoProducto = k.IdTipoProducto
    JOIN Contabilidad.RolCuentaProducto r ON r.CodigoRol = k.CodigoRol
    LEFT JOIN Credito.TipoCredito tc ON tc.IdTipoCredito = k.IdTipoCredito
    LEFT JOIN Contabilidad.CuentasContables c ON c.CodigoCuenta = k.CuentaBase
    WHERE k.Estado = 'A'
"""


def clases(
    conn: Connection, id_tipo: int | None = None, id_tipo_credito: int | None = None
) -> list[dict[str, Any]]:
    sql = _CLASES
    if id_tipo is not None:
        sql += " AND k.IdTipoProducto = :tipo"
    if id_tipo_credito is not None:
        sql += " AND k.IdTipoCredito = :credito"
    sql += " ORDER BY k.IdTipoProducto, k.IdTipoCredito, k.Orden, k.IdClase"
    return [
        dict(f)
        for f in conn.execute(
            text(sql), {"tipo": id_tipo, "credito": id_tipo_credito}
        ).mappings()
    ]


_ASIGNACIONES = """
    SELECT v.IdCuentaProducto, v.IdClase, v.IdProducto, p.CodigoProducto, v.IdSubProducto,
           s.CodigoSubProducto, v.IdCuentaContable, c.CodigoCuenta, c.NombreCuenta,
           v.VigenciaDesde, v.VigenciaHasta, v.IdSolicitud
    FROM Contabilidad.CuentaProducto v
    JOIN Contabilidad.ClaseCuentaProducto k ON k.IdClase = v.IdClase
    JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable = v.IdCuentaContable
    LEFT JOIN ProductosFinancieros.Producto p ON p.IdProducto = v.IdProducto
    LEFT JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto = v.IdSubProducto
    WHERE v.Estado = 'A' AND (v.VigenciaHasta IS NULL OR v.VigenciaHasta >= :fecha)
"""


def asignaciones(conn: Connection, id_tipo: int, fecha: date) -> list[dict[str, Any]]:
    """Vigentes en la fecha y programadas después, de las clases del tipo."""
    return [
        dict(f)
        for f in conn.execute(
            text(
                _ASIGNACIONES
                + " AND k.IdTipoProducto = :tipo ORDER BY k.Orden, v.IdClase, v.VigenciaDesde"
            ),
            {"tipo": id_tipo, "fecha": fecha},
        ).mappings()
    ]


def productos_del_tipo(
    conn: Connection, id_tipo: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Productos y subproductos no retirados del tipo, para asignar o exceptuar."""
    productos = [
        dict(f)
        for f in conn.execute(
            text("""
            SELECT IdProducto AS id_producto, CodigoProducto AS codigo_producto,
                   NombreProducto AS nombre_producto, IdTipoCredito AS id_tipo_credito
            FROM ProductosFinancieros.Producto
            WHERE IdTipoProducto = :tipo AND ISNULL(EstadoProducto, '') <> 'Retirado'
            ORDER BY CodigoProducto
        """),
            {"tipo": id_tipo},
        ).mappings()
    ]
    subproductos = [
        dict(f)
        for f in conn.execute(
            text("""
            SELECT s.IdSubProducto AS id_sub_producto, s.IdProducto AS id_producto,
                   s.CodigoSubProducto AS codigo_sub_producto,
                   s.NombreSubProducto AS nombre_sub_producto
            FROM ProductosFinancieros.SubProducto s
            JOIN ProductosFinancieros.Producto p ON p.IdProducto = s.IdProducto
            WHERE p.IdTipoProducto = :tipo AND ISNULL(s.EstadoSubProducto, '') <> 'Retirado'
            ORDER BY s.CodigoSubProducto
        """),
            {"tipo": id_tipo},
        ).mappings()
    ]
    return productos, subproductos


def _subproducto(conn: Connection, id_sub: int) -> dict[str, Any]:
    fila = (
        conn.execute(
            text("""
            SELECT s.IdSubProducto, s.CodigoSubProducto, s.NombreSubProducto, s.IdProducto,
                   p.CodigoProducto, p.IdTipoProducto, t.Codigo AS CodigoTipoProducto,
                   p.IdTipoCredito
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


def _tasa(conn: Connection, id_sub: int, fecha: date) -> float:
    valor = conn.execute(
        text("""
        SELECT TOP (1) TasaInteresAnual FROM ProductosFinancieros.SubProductoCondicion
        WHERE IdSubProducto = :id AND Estado IN ('Vigente', 'Programada')
          AND VigenciaDesde <= :fecha AND (VigenciaHasta IS NULL OR VigenciaHasta >= :fecha)
        ORDER BY VigenciaDesde DESC
    """),
        {"id": id_sub, "fecha": fecha},
    ).scalar()
    return float(valor or 0)


def clases_de(conn: Connection, sub: dict[str, Any]) -> list[dict[str, Any]]:
    """Clases que aplican a un subproducto (la tarjeta de crédito suma las de consumo)."""
    propias = clases(conn, sub["IdTipoProducto"])
    if sub["CodigoTipoProducto"] == "CREDITO":
        return [k for k in propias if k["IdTipoCredito"] == sub["IdTipoCredito"]]
    if (
        sub["CodigoTipoProducto"] == "TARJETA"
        and tipo_tarjeta_de(sub["CodigoSubProducto"]) == "Credito"
    ):
        return propias + [
            k
            for k in clases(conn)
            if k["CodigoTipoProducto"] == "CREDITO"
            and k["CodigoTipoCredito"] == TIPO_CREDITO_TARJETA
        ]
    return propias


def resolver(
    conn: Connection, id_sub: int, fecha: date
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Cada clase del subproducto con su cuenta vigente y el nivel del que viene."""
    sub = _subproducto(conn, id_sub)
    lista = clases_de(conn, sub)
    filas = [
        dict(f)
        for f in conn.execute(
            text(
                _ASIGNACIONES
                + """ AND v.VigenciaDesde <= :fecha
                AND (v.IdSubProducto = :sub OR v.IdProducto = :prod
                     OR (v.IdProducto IS NULL AND v.IdSubProducto IS NULL))"""
            ),
            {"fecha": fecha, "sub": id_sub, "prod": sub["IdProducto"]},
        ).mappings()
    ]
    tasa = _tasa(conn, id_sub, fecha)
    resultado = []
    for k in lista:
        candidatas = [f for f in filas if f["IdClase"] == k["IdClase"]]
        elegida, origen = None, None
        for nivel, cumple in (
            ("SUBPRODUCTO", lambda f: f["IdSubProducto"] == id_sub),
            ("PRODUCTO", lambda f: f["IdProducto"] == sub["IdProducto"]),
            ("TIPO", lambda f: f["IdProducto"] is None and f["IdSubProducto"] is None),
        ):
            elegida = next((f for f in candidatas if cumple(f)), None)
            if elegida:
                origen = nivel
                break
        resultado.append(
            {
                **k,
                "Requerido": bool(k["Obligatorio"])
                and (not k["SoloConTasa"] or tasa > 0),
                "Origen": origen,
                "Cuenta": elegida,
            }
        )
    return sub, resultado


def roles_faltantes(conn: Connection, id_sub: int, fecha: date) -> list[str]:
    _, filas = resolver(conn, id_sub, fecha)
    return sorted(
        {f["CodigoRol"] for f in filas if f["Requerido"] and f["Cuenta"] is None}
    )


def cuenta_contable(
    conn: Connection,
    id_sub: int,
    rol: str,
    fecha: date,
    situacion: str | None = None,
    condicion: str | None = None,
    tramo: int | None = None,
) -> int:
    """Cuenta del rol para una operación del subproducto, para el motor contable."""
    sub, filas = resolver(conn, id_sub, fecha)
    if (
        sub["CodigoTipoProducto"] == "TARJETA"
        and tipo_tarjeta_de(sub["CodigoSubProducto"]) == "Debito"
        and rol == "CAPITAL"
    ):
        raise problema(
            422,
            "ROL_NO_APLICA",
            "La tarjeta de débito usa el capital de su cuenta vinculada.",
        )
    if rol in ("INTERES_POR_COBRAR", "INTERES_GANADO", "PROVISION", "CARTERA"):
        condicion = condicion or "ORIGINAL"
    for f in filas:
        if (f["CodigoRol"], f["Situacion"], f["Condicion"], f["Tramo"]) == (
            rol,
            situacion,
            condicion,
            tramo,
        ):
            if f["Cuenta"] is None:
                break
            return int(f["Cuenta"]["IdCuentaContable"])
    raise problema(
        422, "ROL_SIN_CUENTA", "El rol no tiene una cuenta contable vigente."
    )


# ---------- Validación y aplicación de cambios ----------


def _tipo(conn: Connection, id_tipo: int) -> dict[str, Any]:
    fila = (
        conn.execute(
            text(
                "SELECT IdTipoProducto, Codigo, Nombre FROM ProductosFinancieros.TipoProducto WHERE IdTipoProducto = :id"
            ),
            {"id": id_tipo},
        )
        .mappings()
        .first()
    )
    if fila is None:
        raise problema(
            404, "TIPO_PRODUCTO_NO_ENCONTRADO", "El tipo de producto no existe."
        )
    return dict(fila)


def _clase(conn: Connection, id_clase: int) -> dict[str, Any]:
    fila = next((k for k in clases(conn) if k["IdClase"] == id_clase), None)
    if fila is None:
        raise problema(404, "CLASE_NO_ENCONTRADA", "El rol contable no existe.")
    return fila


def _producto_efectivo(conn: Connection, cambio: Cambio) -> dict[str, Any] | None:
    if cambio.id_sub_producto is not None:
        return _subproducto(conn, cambio.id_sub_producto)
    if cambio.id_producto is None:
        return None
    fila = (
        conn.execute(
            text("""
            SELECT p.IdProducto, p.CodigoProducto, p.IdTipoProducto, t.Codigo AS CodigoTipoProducto,
                   p.IdTipoCredito, NULL AS CodigoSubProducto
            FROM ProductosFinancieros.Producto p
            JOIN ProductosFinancieros.TipoProducto t ON t.IdTipoProducto = p.IdTipoProducto
            WHERE p.IdProducto = :id
        """),
            {"id": cambio.id_producto},
        )
        .mappings()
        .first()
    )
    if fila is None:
        raise problema(404, "PRODUCTO_NO_ENCONTRADO", "El producto no existe.")
    return dict(fila)


def _vigentes(conn: Connection, cambio: Cambio) -> list[dict[str, Any]]:
    return [
        dict(f)
        for f in conn.execute(
            text("""
            SELECT IdCuentaProducto, VigenciaDesde, VigenciaHasta, IdCuentaContable
            FROM Contabilidad.CuentaProducto WITH (UPDLOCK, HOLDLOCK)
            WHERE IdClase = :clase AND Estado = 'A'
              AND ISNULL(IdProducto, 0) = ISNULL(:prod, 0)
              AND ISNULL(IdSubProducto, 0) = ISNULL(:sub, 0)
        """),
            {
                "clase": cambio.id_clase,
                "prod": cambio.id_producto,
                "sub": cambio.id_sub_producto,
            },
        ).mappings()
    ]


def validar(conn: Connection, id_tipo: int, cambio: Cambio, hoy: date) -> None:
    clase = _clase(conn, cambio.id_clase)
    producto = _producto_efectivo(conn, cambio)
    tarjeta_credito = (
        producto is not None
        and producto["CodigoTipoProducto"] == "TARJETA"
        and cambio.id_sub_producto is not None
        and tipo_tarjeta_de(producto["CodigoSubProducto"] or "") == "Credito"
        and clase["CodigoTipoProducto"] == "CREDITO"
    )
    if clase["IdTipoProducto"] != id_tipo and not tarjeta_credito:
        raise problema(
            422, "ROL_NO_APLICA", "El rol no pertenece a este tipo de producto."
        )
    if (
        producto is not None
        and not tarjeta_credito
        and (
            producto["IdTipoProducto"] != clase["IdTipoProducto"]
            or (
                clase["IdTipoCredito"] is not None
                and producto["IdTipoCredito"] != clase["IdTipoCredito"]
            )
        )
    ):
        raise problema(
            422, "ROL_NO_APLICA", "El rol no corresponde al tipo del producto."
        )
    if clase["Nivel"] == "PRODUCTO" and producto is None:
        raise problema(422, "ROL_POR_PRODUCTO", "Este rol se asigna a cada producto.")
    if cambio.vigencia_desde < hoy:
        raise problema(
            422, "VIGENCIA_PASADA", "La asignación no puede iniciar en el pasado."
        )
    for v in _vigentes(conn, cambio):
        if v["VigenciaDesde"] >= cambio.vigencia_desde:
            raise problema(
                422,
                "VIGENCIA_SOLAPADA",
                "Ya hay una asignación que inicia en esa fecha o después.",
            )
    if cambio.id_cuenta_contable is None:
        if producto is None:
            raise problema(
                422,
                "CUENTA_OBLIGATORIA",
                "El rol del tipo necesita una cuenta; solo una excepción se puede quitar.",
            )
        return
    cuenta = (
        conn.execute(
            text("""
            SELECT c.CodigoCuenta, c.Estado, c.EsImputable,
                   CASE WHEN EXISTS (SELECT 1 FROM Contabilidad.CuentasContables h
                                     WHERE h.IdCuentaSuperior = c.IdCuentaContable)
                        THEN 1 ELSE 0 END AS TieneHijas
            FROM Contabilidad.CuentasContables c WHERE c.IdCuentaContable = :id
        """),
            {"id": cambio.id_cuenta_contable},
        )
        .mappings()
        .first()
    )
    if (
        cuenta is None
        or not cuenta["Estado"]
        or not cuenta["EsImputable"]
        or cuenta["TieneHijas"]
        or not cuenta["CodigoCuenta"].startswith(clase["CuentaBase"])
    ):
        raise problema(
            422,
            "CUENTA_NO_CORRESPONDE",
            f"La cuenta debe ser activa, imputable, del último nivel y estar bajo {clase['CuentaBase']}.",
        )
    if clase["CodigoRol"] == "CAPITAL":
        dueno = conn.execute(
            text("""
            SELECT TOP (1) COALESCE(v.IdProducto, s.IdProducto)
            FROM Contabilidad.CuentaProducto v
            JOIN Contabilidad.ClaseCuentaProducto k ON k.IdClase = v.IdClase AND k.CodigoRol = 'CAPITAL'
            LEFT JOIN ProductosFinancieros.SubProducto s ON s.IdSubProducto = v.IdSubProducto
            WHERE v.IdCuentaContable = :cuenta AND v.Estado = 'A'
              AND (v.VigenciaHasta IS NULL OR v.VigenciaHasta >= :desde)
              AND ISNULL(COALESCE(v.IdProducto, s.IdProducto), 0) <> ISNULL(:prod, 0)
        """),
            {
                "cuenta": cambio.id_cuenta_contable,
                "desde": cambio.vigencia_desde,
                "prod": producto["IdProducto"] if producto else None,
            },
        ).scalar()
        if dueno is not None:
            raise problema(
                409,
                "CUENTA_YA_ASIGNADA",
                "Esa cuenta ya es el capital de otro producto.",
            )


def aplicar_cambio(
    conn: Connection, cambio: Cambio, id_solicitud: int, creado_por: int | None
) -> None:
    for v in _vigentes(conn, cambio):
        if v["VigenciaHasta"] is None or v["VigenciaHasta"] >= cambio.vigencia_desde:
            conn.execute(
                text(
                    "UPDATE Contabilidad.CuentaProducto SET VigenciaHasta = :hasta WHERE IdCuentaProducto = :id"
                ),
                {
                    "hasta": cambio.vigencia_desde - timedelta(days=1),
                    "id": v["IdCuentaProducto"],
                },
            )
    if cambio.id_cuenta_contable is not None:
        conn.execute(
            text("""
            INSERT Contabilidad.CuentaProducto (IdClase, IdProducto, IdSubProducto, IdCuentaContable,
                   VigenciaDesde, IdSolicitud, CreadoPor)
            VALUES (:clase, :prod, :sub, :cuenta, :desde, :solicitud, :autor)
        """),
            {
                "clase": cambio.id_clase,
                "prod": cambio.id_producto,
                "sub": cambio.id_sub_producto,
                "cuenta": cambio.id_cuenta_contable,
                "desde": cambio.vigencia_desde,
                "solicitud": id_solicitud,
                "autor": creado_por,
            },
        )


def version(conn: Connection) -> str:
    """Huella de todas las asignaciones: cualquier cambio invalida una solicitud previa."""
    fila = conn.execute(
        text("""
        SELECT COUNT(*), ISNULL(MAX(IdCuentaProducto), 0),
               ISNULL(CHECKSUM_AGG(CHECKSUM(IdCuentaProducto, VigenciaHasta, Estado)), 0)
        FROM Contabilidad.CuentaProducto WITH (UPDLOCK, HOLDLOCK)
    """)
    ).one()
    return f"{fila[0]}:{fila[1]}:{fila[2]}"


def _id_tipo(objetivo: Objetivo) -> int:
    if (
        objetivo.tipo != "TipoProducto"
        or objetivo.agencia is not None
        or not objetivo.id.isascii()
        or not objetivo.id.isdecimal()
        or not 0 < int(objetivo.id) <= 2147483647
    ):
        raise problema(422, "OBJETIVO_INVALIDO", "El tipo de producto no es válido.")
    return int(objetivo.id)


def _solicitud(contenido: dict[str, Any]) -> Solicitud:
    try:
        return Solicitud.model_validate(contenido)
    except ValidationError:
        raise problema(
            422, "CONTENIDO_INVALIDO", "Revise las asignaciones propuestas."
        ) from None


class AprobacionAsignaciones:
    def __init__(self, seguridad: Engine | None = None):
        self.seguridad = seguridad

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        _id_tipo(objetivo)
        return version(conn)

    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan:
        id_tipo = _id_tipo(objetivo)
        tipo = _tipo(conn, id_tipo)
        datos = _solicitud(contenido)
        llaves = {(c.id_clase, c.id_producto, c.id_sub_producto) for c in datos.cambios}
        if len(llaves) != len(datos.cambios):
            raise problema(
                422, "CAMBIO_REPETIDO", "Cada rol y alcance va una sola vez."
            )
        for cambio in datos.cambios:
            validar(conn, id_tipo, cambio, hoy)
        propuesta = datos.model_dump(mode="json", by_alias=True)
        actuales = [
            {
                "idClase": a["IdClase"],
                "idProducto": a["IdProducto"],
                "idSubProducto": a["IdSubProducto"],
                "cuenta": a["CodigoCuenta"],
                "vigenciaDesde": a["VigenciaDesde"].isoformat(),
            }
            for a in asignaciones(conn, id_tipo, hoy)
            if (a["IdClase"], a["IdProducto"], a["IdSubProducto"]) in llaves
        ]
        return Plan(
            propuesta,
            {"tipoProducto": tipo["Nombre"], "asignaciones": actuales},
            {"tipoProducto": tipo["Nombre"], **propuesta},
            version(conn),
        )

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict[str, Any],
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        _id_tipo(objetivo)
        datos = _solicitud(contenido)
        with (self.seguridad or motor("seguridad")).connect() as seg:
            autor = seg.execute(
                text(
                    "SELECT UsuarioID FROM Organizacion.Usuarios WHERE KeyUsuario=:sujeto AND Estado='Activo'"
                ),
                {"sujeto": solicitante},
            ).scalar()
        for cambio in datos.cambios:
            aplicar_cambio(conn, cambio, id_solicitud, autor)


def operacion() -> Operacion:
    return Operacion(
        CODIGO,
        "TipoProducto",
        "cooperativa",
        frozenset({"CONTADOR"}),
        "con-plantilla-aprobar",
        AprobacionAsignaciones(),
        tabla_auditada="Contabilidad.CuentaProducto",
        evento_ejecucion="CON_MAPEO_PROGRAMADO",
        solicitud_directa=False,
        permiso_ejecucion="con-cuenta-editar",
    )
