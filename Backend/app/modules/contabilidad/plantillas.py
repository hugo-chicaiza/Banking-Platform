"""Administración y simulación de versiones del motor E4-01."""

import hashlib
import json
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, problema
from app.core.database.db import cooperativa
from app.core.security.auth import UsuarioActual, require_permiso
from app.core.security.operador import IdInterno, exigir_id_interno
from app.modules.aprobaciones.contratos import SolicitudResumen
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.contabilidad import repository
from app.modules.contabilidad.asientos import ErrorContable, resolver_lineas
from app.modules.contabilidad.schemas import INT32_MAX

router = APIRouter(
    route_class=ProblemDetailsRoute,
    # Con el editor activo require_permiso autoriza la función de cada método/ruta:
    # consultar en GET y editar en POST. Apagado, conserva el permiso WorkOS previo.
    dependencies=[Depends(require_permiso("con-plantilla-editar"))],
)
Db = Annotated[Connection, Depends(cooperativa)]
IdContable = Annotated[int, Path(ge=1, le=INT32_MAX)]
IdCuenta = Annotated[int, Field(gt=0, le=INT32_MAX)]


class Linea(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lado: Literal["DEBITO", "CREDITO"]
    origen: Literal["FIJA", "PRODUCTO", "CONTRAPRODUCTO", "COMISION"]
    base: Literal[
        "PRINCIPAL",
        "COMISION",
        "IMPUESTO",
        "INTERES",
        "MORA",
        "SEGURO",
        "DIFERENCIA",
        "TOTAL",
    ]
    cuenta: IdCuenta | None = None
    rol: str | None = Field(default=None, min_length=1, max_length=30)


class Version(BaseModel):
    model_config = ConfigDict(extra="forbid")

    codigoPlantilla: str | None = Field(default=None, min_length=1, max_length=50)
    vigenciaDesde: date
    nombre: str = Field(min_length=1, max_length=100)
    lineas: list[Linea] = Field(min_length=2, max_length=100)


class VersionSolicitada(BaseModel):
    idPlantillaAsiento: int
    idSolicitud: int


class Simulacion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lineas: list[Linea] = Field(min_length=2, max_length=100)
    montos: dict[str, Decimal]
    producto: dict[str, IdCuenta] = Field(default_factory=dict)
    contraproducto: dict[str, IdCuenta] = Field(default_factory=dict)
    comision: IdCuenta | None = None


def validar_lineas(conn: Connection, lineas: list[Linea]) -> list[dict[str, Any]]:
    balance: Counter[str] = Counter()
    resultado = []
    for linea in lineas:
        balance[linea.base] += 1 if linea.lado == "DEBITO" else -1
    if any(balance.values()):
        raise problema(
            422,
            "PLANTILLA_NO_CUADRA",
            "Cada base debe tener el mismo número de débitos y créditos.",
        )
    for orden, linea in enumerate(lineas, 1):
        cuenta = {}
        if linea.origen == "FIJA" and linea.cuenta is not None and linea.rol is None:
            cuenta = repository.cuenta_para_plantilla(conn, linea.cuenta) or {}
            # E3-05 (D-17): se registra en el último nivel de la rama, no solo a 8 dígitos.
            if (
                not cuenta.get("Estado")
                or not cuenta.get("EsImputable")
                or cuenta.get("TieneHijas")
            ):
                raise problema(
                    422,
                    "CUENTA_CONTABLE_NO_HABILITADA",
                    "La cuenta fija debe ser activa, imputable y del último nivel.",
                )
        elif (
            linea.origen in ("PRODUCTO", "CONTRAPRODUCTO")
            and linea.cuenta is None
            and linea.rol
        ):
            existe = conn.execute(
                text("""
                SELECT 1 FROM Contabilidad.RolCuentaProducto WITH (HOLDLOCK) WHERE CodigoRol=:rol
            """),
                {"rol": linea.rol},
            ).first()
            if existe is None:
                raise problema(422, "ROL_NO_DEFINIDO", "El rol contable no existe.")
        elif (linea.origen, linea.cuenta, linea.rol) != ("COMISION", None, None):
            raise problema(
                422, "ORIGEN_INVALIDO", "Revise la cuenta o el rol de la línea."
            )
        resultado.append(
            {
                **cuenta,
                "Orden": orden,
                "IdCuentaContable": linea.cuenta,
                "CodigoRol": linea.rol,
                "OrigenCuenta": linea.origen,
                "TipoMovimiento": linea.lado,
                "ComponenteImporte": linea.base,
            }
        )
    return resultado


def _listar(
    conn: Connection,
    id_tipo: int | None = None,
    q: str | None = None,
    codigo: str | None = None,
    estado: int | None = None,
    origen: str | None = None,
) -> list[dict[str, Any]]:
    filas = conn.execute(
        text("""
        SELECT p.IdPlantillaAsiento, p.CodigoPlantilla, p.Version, p.Nombre,
               p.VigenciaDesde, p.VigenciaHasta, p.Estado, p.CreadoPor, p.AprobadoPor,
               p.FechaAprobacion, p.Origen, p.IdTipoAsiento, p.IdConceptoContable,
               t.Codigo AS CodigoTipoAsiento, t.Nombre AS NombreTipoAsiento,
               c.CodigoConcepto, c.ConceptoDetalle
        FROM Contabilidad.PlantillaAsiento p
        LEFT JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento=p.IdTipoAsiento
        LEFT JOIN Contabilidad.ConceptoContable c ON c.IdConceptoContable=p.IdConceptoContable
        WHERE (:id IS NULL OR p.IdTipoAsiento=:id)
          AND (:codigo IS NULL OR p.CodigoPlantilla=:codigo)
          AND (:q IS NULL OR CHARINDEX(:q,p.Nombre)>0 OR CHARINDEX(:q,p.CodigoPlantilla)>0)
          AND (:estado IS NULL OR p.Estado=:estado)
          AND (:origen IS NULL OR p.Origen=:origen)
        ORDER BY p.CodigoPlantilla, p.Version DESC, p.IdPlantillaAsiento DESC
    """),
        {"id": id_tipo, "q": q, "codigo": codigo, "estado": estado, "origen": origen},
    ).mappings()
    return [dict(f) for f in filas]


@router.get(
    "/plantillas", responses={400: RESPUESTAS_ERROR[400], 403: RESPUESTAS_ERROR[403]}
)
def listar_global(
    conn: Db,
    q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
    codigo: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    estado: Annotated[int | None, Query(ge=0, le=1)] = None,
    origen: Annotated[str | None, Query(min_length=1, max_length=30)] = None,
    id_tipo: Annotated[
        int | None, Query(alias="idTipoAsiento", ge=1, le=INT32_MAX)
    ] = None,
) -> list[dict[str, Any]]:
    return _listar(conn, id_tipo, q, codigo, estado, origen)


@router.get("/tipos-asiento/{id_tipo}/plantillas")
def listar(conn: Db, id_tipo: IdContable) -> list[dict[str, Any]]:
    return _listar(conn, id_tipo)


@router.get("/plantillas/catalogos")
def catalogos(conn: Db) -> dict[str, list[dict[str, Any]]]:
    tipos = (
        conn.execute(
            text("""
        SELECT IdTipoAsiento, Codigo, Nombre, Descripcion, EsManual, Estado
        FROM Contabilidad.TiposAsiento ORDER BY Nombre, IdTipoAsiento
    """)
        )
        .mappings()
        .all()
    )
    conceptos = (
        conn.execute(
            text("""
        SELECT IdConceptoContable, CodigoConcepto, ConceptoDetalle, Estado
        FROM Contabilidad.ConceptoContable ORDER BY CodigoConcepto, IdConceptoContable
    """)
        )
        .mappings()
        .all()
    )
    return {
        "tiposAsiento": [dict(fila) for fila in tipos],
        "conceptosContables": [dict(fila) for fila in conceptos],
    }


@router.get("/plantillas/{id_plantilla}")
def detalle(conn: Db, id_plantilla: IdContable) -> dict[str, Any]:
    fila = (
        conn.execute(
            text("""
        SELECT p.*, t.Codigo AS CodigoTipoAsiento, t.Nombre AS NombreTipoAsiento,
               c.CodigoConcepto, c.ConceptoDetalle
        FROM Contabilidad.PlantillaAsiento p
        LEFT JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento=p.IdTipoAsiento
        LEFT JOIN Contabilidad.ConceptoContable c ON c.IdConceptoContable=p.IdConceptoContable
        WHERE p.IdPlantillaAsiento=:id
    """),
            {"id": id_plantilla},
        )
        .mappings()
        .one_or_none()
    )
    if fila is None:
        raise problema(404, "PLANTILLA_NO_DEFINIDA", "La plantilla no existe.")
    return {
        **fila,
        "lineas": repository.obtener_lineas_plantilla(
            conn, id_plantilla, para_detalle=True
        ),
    }


@router.get(
    "/plantillas/{id_plantilla}/solicitudes", response_model=SolicitudResumen | None
)
def solicitud_version(
    id_plantilla: IdContable, usuario: UsuarioActual
) -> SolicitudResumen | None:
    from app.modules.aprobaciones import lecturas
    from app.modules.aprobaciones import router as aprobaciones

    return lecturas.solicitud_global_por_objetivo(
        aprobaciones.servicio(),
        aprobaciones.actual(usuario),
        OPERACION_PLANTILLA,
        str(id_plantilla),
    )


def crear(
    conn: Db, id_tipo: int, datos: Version, id_interno: IdInterno
) -> dict[str, int]:
    actor = exigir_id_interno(id_interno)
    with conn.begin():
        lineas = validar_lineas(conn, datos.lineas)
        tipo = (
            conn.execute(
                text("""
            SELECT TOP (1) CodigoPlantilla, Version, Origen, IdConceptoContable
            FROM Contabilidad.PlantillaAsiento WITH (UPDLOCK,HOLDLOCK)
            WHERE IdTipoAsiento=:tipo AND (:codigo IS NULL OR CodigoPlantilla=:codigo)
            ORDER BY Version DESC, IdPlantillaAsiento DESC
        """),
                {"tipo": id_tipo, "codigo": datos.codigoPlantilla},
            )
            .mappings()
            .one_or_none()
        )
        if tipo is None:
            raise problema(
                404, "PLANTILLA_NO_DEFINIDA", "Falta la plantilla base del tipo."
            )
        familias = conn.execute(
            text("""
            SELECT COUNT(DISTINCT CodigoPlantilla) FROM Contabilidad.PlantillaAsiento
            WHERE IdTipoAsiento=:tipo AND (:codigo IS NULL OR CodigoPlantilla=:codigo)
        """),
            {"tipo": id_tipo, "codigo": datos.codigoPlantilla},
        ).scalar_one()
        if familias != 1:
            raise problema(
                409,
                "TIPO_AMBIGUO",
                "Indique codigoPlantilla para seleccionar una familia.",
            )
        id_plantilla = conn.execute(
            text("""
            INSERT Contabilidad.PlantillaAsiento
                (CodigoPlantilla, Version, Origen, IdTipoAsiento, IdConceptoContable,
                 Nombre, VigenciaDesde, Estado, CreadoPor)
            OUTPUT inserted.IdPlantillaAsiento
            VALUES (:CodigoPlantilla, :version, :Origen, :tipo, :IdConceptoContable,
                    :nombre, :desde, 0, :actor)
        """),
            {
                **tipo,
                "version": tipo["Version"] + 1,
                "tipo": id_tipo,
                "nombre": datos.nombre,
                "desde": datos.vigenciaDesde,
                "actor": actor,
            },
        ).scalar_one()
        conn.execute(
            text("""
            INSERT Contabilidad.PlantillaAsientoDetalle
                (IdPlantillaAsiento, Orden, IdCuentaContable, TipoMovimiento, ComponenteImporte,
                 OrigenCuenta, CodigoRol)
            VALUES (:id, :Orden, :IdCuentaContable, :TipoMovimiento, :ComponenteImporte,
                    :OrigenCuenta, :CodigoRol)
        """),
            [{**linea, "id": id_plantilla} for linea in lineas],
        )
        return {"idPlantillaAsiento": id_plantilla}


@router.post("/plantillas/simulaciones")
def simular(conn: Db, datos: Simulacion) -> dict[str, Any]:
    lineas = validar_lineas(conn, datos.lineas)
    cuentas: dict[tuple[str, str | None], int] = {
        (origen, rol): cuenta
        for origen, roles in (
            ("PRODUCTO", datos.producto),
            ("CONTRAPRODUCTO", datos.contraproducto),
        )
        for rol, cuenta in roles.items()
    }
    if datos.comision is not None:
        cuentas["COMISION", None] = datos.comision
    try:
        resultado = resolver_lineas(
            lineas, datos.montos, conn=conn, cuentas_por_rol=cuentas
        )
    except ErrorContable as error:
        raise problema(422, "SIMULACION_INVALIDA", str(error)) from error
    return {
        "lineas": resultado,
        "total": sum(f["monto"] for f in resultado if f["lado"] == "DEBITO"),
    }


def confirmar_aprobacion(
    conn: Connection, id_plantilla: int, aprobador: int, fecha_contable: date
) -> None:
    """Manejador interno. La cola valida permiso y proporciona el actor autenticado."""
    if not conn.in_transaction():
        raise RuntimeError("La aprobación requiere la transacción de la cola.")
    fila = (
        conn.execute(
            text("""
        SELECT CodigoPlantilla, CreadoPor, Estado, VigenciaDesde
        FROM Contabilidad.PlantillaAsiento WITH (UPDLOCK,HOLDLOCK)
        WHERE IdPlantillaAsiento=:id
    """),
            {"id": id_plantilla},
        )
        .mappings()
        .one_or_none()
    )
    if fila is None or fila["CreadoPor"] is None or fila["Estado"]:
        raise problema(409, "PLANTILLA_NO_PENDIENTE", "La versión no está pendiente.")
    if fila["CreadoPor"] == aprobador:
        raise problema(403, "AUTOAPROBACION_PROHIBIDA", "Debe aprobar otra persona.")
    if fila["VigenciaDesde"] <= fecha_contable:
        raise problema(
            409,
            "VIGENCIA_INVALIDA",
            "La vigencia debe iniciar después del día contable actual.",
        )
    superpuesta = conn.execute(
        text("""
        SELECT 1 FROM Contabilidad.PlantillaAsiento WITH (UPDLOCK,HOLDLOCK)
        WHERE CodigoPlantilla=:codigo AND Estado=1 AND VigenciaDesde>=:desde
    """),
        {"codigo": fila["CodigoPlantilla"], "desde": fila["VigenciaDesde"]},
    ).first()
    if superpuesta is not None:
        raise problema(
            409,
            "VIGENCIA_SUPERPUESTA",
            "Ya existe una versión programada para esa fecha o después.",
        )
    lineas = repository.obtener_lineas_plantilla(conn, id_plantilla)
    validar_lineas(
        conn,
        [
            Linea(
                lado=f["TipoMovimiento"],
                origen=f["OrigenCuenta"],
                base=f["ComponenteImporte"],
                cuenta=f["IdCuentaContable"],
                rol=f["CodigoRol"],
            )
            for f in lineas
        ],
    )
    conn.execute(
        text("""
        UPDATE Contabilidad.PlantillaAsiento SET VigenciaHasta=DATEADD(day,-1,:desde)
        WHERE CodigoPlantilla=:codigo AND Estado=1 AND VigenciaDesde<:desde
          AND (VigenciaHasta IS NULL OR VigenciaHasta>=:desde);
        UPDATE Contabilidad.PlantillaAsiento SET Estado=1,AprobadoPor=:aprobador,
            FechaAprobacion=SYSUTCDATETIME() WHERE IdPlantillaAsiento=:id;
    """),
        {
            "id": id_plantilla,
            "aprobador": aprobador,
            "codigo": fila["CodigoPlantilla"],
            "desde": fila["VigenciaDesde"],
        },
    )


def _id_objetivo(objetivo: Objetivo) -> int:
    if objetivo.agencia is None and objetivo.id.isascii() and objetivo.id.isdecimal():
        id_ = int(objetivo.id)
        if 0 < id_ <= 2147483647:
            return id_
    raise problema(422, "OBJETIVO_INVALIDO", "La version de plantilla no es valida.")


def _pendiente(conn: Connection, objetivo: Objetivo) -> dict[str, Any]:
    id_ = _id_objetivo(objetivo)
    repository.bloquear_contabilizacion(conn)
    fila = (
        conn.execute(
            text(
                "SELECT * FROM Contabilidad.PlantillaAsiento WITH (UPDLOCK,HOLDLOCK) WHERE IdPlantillaAsiento=:id"
            ),
            {"id": id_},
        )
        .mappings()
        .one_or_none()
    )
    if fila is None:
        raise problema(404, "PLANTILLA_NO_DEFINIDA", "La plantilla no existe.")
    if fila["Estado"] or fila["CreadoPor"] is None:
        raise problema(409, "PLANTILLA_NO_PENDIENTE", "La version no esta pendiente.")
    return {**fila, "lineas": repository.obtener_lineas_plantilla(conn, id_)}


def _huella(fila: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(fila, default=str, sort_keys=True).encode()
    ).hexdigest()


class AprobacionPlantilla:
    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict, hoy: date
    ) -> Plan:
        from app.modules.contabilidad.service import obtener_fecha_contable_actual

        fila = _pendiente(conn, objetivo)
        if fila["CreadoPor"] != contenido.get("creador"):
            raise problema(
                403, "SIN_PERMISO", "Solo el creador puede enviar esta version."
            )
        if fila["VigenciaDesde"] <= obtener_fecha_contable_actual(conn)["fecha"]:
            raise problema(
                409,
                "VIGENCIA_INVALIDA",
                "La vigencia debe iniciar despues del dia contable actual.",
            )
        propuesta = {
            "idPlantillaAsiento": _id_objetivo(objetivo),
            "vigenciaDesde": fila["VigenciaDesde"].isoformat(),
        }
        return Plan(
            propuesta,
            {"estado": "Pendiente"},
            {**propuesta, "estado": "Programada"},
            _huella(fila),
        )

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        return _huella(_pendiente(conn, objetivo))

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict,
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        raise RuntimeError("La plantilla requiere un aprobador autenticado.")


def _aplicar_con_aprobador(
    conn: Connection, objetivo: Objetivo, aprobador: int
) -> None:
    from app.modules.contabilidad.service import obtener_fecha_contable_actual

    confirmar_aprobacion(
        conn,
        _id_objetivo(objetivo),
        aprobador,
        obtener_fecha_contable_actual(conn)["fecha"],
    )


OPERACION_PLANTILLA = Operacion(
    "CON-PLANTILLA",
    "PlantillaAsiento",
    "cooperativa",
    frozenset({"CONTADOR"}),
    "con-plantilla-aprobar",
    AprobacionPlantilla(),
    tabla_auditada="Contabilidad.PlantillaAsiento",
    evento_ejecucion="CON_PLANTILLA_PROGRAMADA",
    solicitud_directa=False,
    permiso_ejecucion="con-plantilla-editar",
    aplicar_con_aprobador=_aplicar_con_aprobador,
    solicitud_unica=True,
)


@router.post(
    "/tipos-asiento/{id_tipo}/plantillas",
    status_code=202,
    response_model=VersionSolicitada,
    operation_id="crear_api_v1_contabilidad_tipos_asiento__id_tipo__plantillas_post",
)
def crear_y_solicitar(
    conn: Db,
    id_tipo: IdContable,
    datos: Version,
    id_interno: IdInterno,
    usuario: UsuarioActual,
    request: Request,
) -> dict[str, int]:
    from app.modules.aprobaciones import router as aprobaciones
    from app.modules.contabilidad.service import obtener_fecha_contable_actual

    actor = aprobaciones.actual(usuario)
    aprobaciones.servicio().puede_solicitar(
        actor, OPERACION_PLANTILLA, Objetivo("PlantillaAsiento", "", None)
    )
    if actor.id_interno != exigir_id_interno(id_interno):
        raise problema(403, "SIN_PERMISO", "La identidad del creador no coincide.")
    with conn.begin():
        if datos.vigenciaDesde <= obtener_fecha_contable_actual(conn)["fecha"]:
            raise problema(
                409,
                "VIGENCIA_INVALIDA",
                "La vigencia debe iniciar despues del dia contable actual.",
            )
    creada = crear(conn, id_tipo, datos, id_interno)
    return _enviar(creada["idPlantillaAsiento"], usuario, request, actor)


def _enviar(
    id_plantilla: int, usuario: UsuarioActual, request: Request, actor: Actor
) -> dict[str, int]:
    from app.modules.aprobaciones import router as aprobaciones
    from app.modules.contabilidad.service import ahora_ecuador

    id_solicitud = aprobaciones.servicio().solicitar(
        actor,
        OPERACION_PLANTILLA.codigo,
        Objetivo(OPERACION_PLANTILLA.tipo_objetivo, str(id_plantilla), None),
        {"creador": actor.id_interno},
        ahora_ecuador().date(),
        aprobaciones.contexto(request, usuario),
    )
    return {"idPlantillaAsiento": id_plantilla, "idSolicitud": id_solicitud}


@router.post(
    "/plantillas/{id_plantilla}/solicitudes",
    status_code=202,
    response_model=VersionSolicitada,
)
def enviar_pendiente(
    id_plantilla: IdContable, usuario: UsuarioActual, request: Request
) -> dict[str, int]:
    from app.modules.aprobaciones import router as aprobaciones

    return _enviar(id_plantilla, usuario, request, aprobaciones.actual(usuario))
