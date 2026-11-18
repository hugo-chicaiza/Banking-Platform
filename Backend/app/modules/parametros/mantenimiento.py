"""Mantenimiento E1-10 sobre los servicios reales de E0-09 y E0-08."""

import json
from datetime import UTC, date, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import ConfigDict, Field, field_validator
from sqlalchemy import Connection, bindparam, text

from app.core.api.errors import (
    RESPUESTAS_ERROR,
    ProblemDetailsRoute,
    problema,
    solo_parametros,
)
from app.core.api.schemas import CamelModel
from app.core.database.db import cooperativa
from app.core.security.auth import UsuarioActual, require_auth
from app.core.security.operador import agencia_de_consulta
from app.modules.aprobaciones import router as aprobaciones
from app.modules.aprobaciones.auditoria import encolar
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.motores import motor
from app.modules.aprobaciones.registro import Objetivo
from app.modules.parametros import general
from app.modules.parametros.service import hoy

router = APIRouter(
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    dependencies=[Depends(require_auth)],
)
Coop = Annotated[Connection, Depends(cooperativa)]
Actual = aprobaciones.Actual
Cola = aprobaciones.Cola
LECTURA = []
Clave = Annotated[str, Path(pattern=r"^[A-Z0-9_]{1,60}$")]
IdValor = Annotated[int, Path(alias="id_valor", gt=0, le=2147483647)]


class ValorNuevo(CamelModel):
    model_config = ConfigDict(extra="forbid")
    valor: str = Field(strict=True, max_length=500)
    vigencia_desde: date
    id_agencia: str | None = Field(default=None, pattern=r"^[0-9]{3}$")

    @field_validator("id_agencia")
    @classmethod
    def agencia_valida(cls, valor: str | None) -> str | None:
        if valor == "000":
            raise ValueError("La agencia 000 no es valida.")
        return valor


def lectura(actor: Actor) -> None:
    if not set(actor.roles).intersection({"ADMIN", "SUPERVISOR", "ASESOR"}):
        raise problema(
            403, "SIN_PERMISO", "No tiene acceso al mantenimiento de parametros."
        )


def escritura(actor: Actor) -> None:
    if "ADMIN" not in actor.roles:
        raise problema(
            403,
            "SIN_PERMISO",
            "La programacion de parametros requiere el rol ADMIN vigente.",
        )


def alcance(actor: Actor, usuario, pedida: str | None) -> str | None:
    agencia = agencia_de_consulta(usuario, pedida)
    aprobaciones.alcance_operativo(actor, usuario, agencia)
    return agencia


def auditar(
    conn: Connection,
    codigo: str,
    actor: Actor,
    clave: str,
    agencia: str | None,
    request: Request,
    usuario,
    antes: list[dict],
    despues: list[dict],
) -> None:
    anteriores = {v["IdParametroValor"]: v for v in antes}
    nuevos = {v["IdParametroValor"]: v for v in despues}
    modificados = {
        id_
        for id_ in anteriores.keys() | nuevos.keys()
        if anteriores.get(id_) != nuevos.get(id_)
    }
    cambios = {
        "antes": [v for id_, v in anteriores.items() if id_ in modificados],
        "despues": [v for id_, v in nuevos.items() if id_ in modificados],
    }
    encolar(
        conn,
        codigo,
        actor,
        None,
        agencia,
        aprobaciones.contexto(request, usuario),
        json.loads(json.dumps(cambios, default=str)),
        tabla="Parametros.Parametro",
        objetivo=clave,
    )


def nombres(valores: list[dict[str, Any]], actor: Actor) -> dict[str | None, str]:
    resultado: dict[str | None, str] = {
        None: "Sistema",
        actor.sujeto: f"{actor.nombre or 'Usuario'}({actor.id_interno})",
    }
    faltantes = {v["CreadoPor"] for v in valores} - resultado.keys()
    if faltantes:
        with motor("seguridad").connect() as conn:
            filas = (
                conn.execute(
                    text(
                        "SELECT KeyUsuario,UsuarioID,Nombres,Apellidos FROM Organizacion.Usuarios WHERE KeyUsuario IN :sujetos"
                    ).bindparams(bindparam("sujetos", expanding=True)),
                    {"sujetos": list(faltantes)},
                )
                .mappings()
                .all()
            )
        for fila in filas:
            nombre = " ".join(
                str(fila[c] or "").strip() for c in ("Nombres", "Apellidos")
            ).strip()
            resultado[fila["KeyUsuario"]] = (
                f"{nombre or 'Usuario'}({fila['UsuarioID']})"
            )
    return resultado


def publicar_valor(
    v: dict[str, Any] | None, responsables: dict[str | None, str]
) -> dict[str, Any] | None:
    if v is None:
        return None
    campos = {
        "IdParametroValor": "idParametroValor",
        "IdAgencia": "idAgencia",
        "Valor": "valor",
        "VigenciaDesde": "vigenciaDesde",
        "VigenciaHasta": "vigenciaHasta",
        "Estado": "estado",
        "CreadoPor": "creadoPor",
        "FechaCreacion": "fechaCreacion",
    }
    return {
        "responsable": responsables.get(v["CreadoPor"], "Usuario institucional"),
        **{
            nombre: v[columna].replace(tzinfo=UTC)
            if columna == "FechaCreacion"
            else v[columna]
            for columna, nombre in campos.items()
        },
    }


def detalle(
    conn: Connection, clave: str, agencia: str | None, fecha: date, actor: Actor
) -> dict[str, Any]:
    p = general.definicion(conn, clave)
    historial = general.historial(conn, clave, agencia)
    return presentar(p, historial, agencia, fecha, actor, nombres(historial, actor))


def presentar(
    p: dict[str, Any],
    historial: list[dict[str, Any]],
    agencia: str | None,
    fecha: date,
    actor: Actor,
    responsables: dict[str | None, str],
) -> dict[str, Any]:
    vigentes = [
        v
        for v in historial
        if v["Estado"] == "A"
        and v["VigenciaDesde"] <= fecha
        and (v["VigenciaHasta"] is None or fecha <= v["VigenciaHasta"])
    ]
    vigentes.sort(
        key=lambda v: (v["IdAgencia"] is not None, v["VigenciaDesde"]), reverse=True
    )
    futuros = sorted(
        [v for v in historial if v["Estado"] == "A" and v["VigenciaDesde"] > fecha],
        key=lambda v: (v["VigenciaDesde"], v["IdAgencia"] is None),
    )
    return {
        "clave": p["Clave"],
        "modulo": p["Modulo"],
        "descripcion": p["Descripcion"],
        "tipoDato": p["TipoDato"],
        "unidad": p["Unidad"],
        "minimo": str(p["ValorMinimo"]) if p["ValorMinimo"] is not None else None,
        "maximo": str(p["ValorMaximo"]) if p["ValorMaximo"] is not None else None,
        "esSensible": p["EsSensible"],
        "admiteAgencia": p["AdmiteAgencia"],
        "estado": p["Estado"],
        "valorActual": publicar_valor(vigentes[0], responsables) if vigentes else None,
        "proximoValor": publicar_valor(futuros[0], responsables) if futuros else None,
        "valoresProgramados": [publicar_valor(v, responsables) for v in futuros],
        "historial": [publicar_valor(v, responsables) for v in historial],
        "agenciaConsultada": agencia,
        "fechaConsulta": fecha,
        "puedeEditar": "ADMIN" in actor.roles and p["Estado"] == "A",
        "valoresPermitidos": json.loads(p["ValoresPermitidos"])
        if p["ValoresPermitidos"]
        else None,
    }


@router.get(
    "",
    dependencies=LECTURA
    + [
        Depends(
            solo_parametros(
                "buscar", "modulo", "estado", "idAgencia", "page", "pageSize"
            )
        )
    ],
)
def listar(
    conn: Coop,
    usuario: UsuarioActual,
    actor: Actual,
    buscar: str = Query("", max_length=100),
    modulo: str | None = Query(None, max_length=30),
    estado: str | None = Query(None, pattern="^[AI]$"),
    id_agencia: str | None = Query(None, alias="idAgencia", pattern=r"^\d{3}$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, alias="pageSize", ge=1, le=100),
) -> dict[str, Any]:
    lectura(actor)
    agencia = alcance(actor, usuario, id_agencia)
    # Parametros son pocos; no se interpolan filtros del usuario en SQL.
    filas = (
        conn.execute(text("SELECT * FROM Parametros.Parametro ORDER BY Modulo,Clave"))
        .mappings()
        .all()
    )
    filtradas = [
        f
        for f in filas
        if (modulo is None or f["Modulo"] == modulo)
        and (estado is None or f["Estado"] == estado)
        and (buscar.casefold() in (f["Clave"] + " " + f["Descripcion"]).casefold())
    ]
    seleccion = filtradas[(page - 1) * page_size : page * page_size]
    general._validar_agencia(agencia)
    valores = []
    if seleccion:
        valores = [
            dict(v)
            for v in conn.execute(
                text(
                    "SELECT * FROM Parametros.ParametroValor WHERE IdParametro IN :ids AND (IdAgencia=CAST(:agencia AS char(3)) OR IdAgencia IS NULL) ORDER BY VigenciaDesde DESC,IdParametroValor DESC"
                ).bindparams(bindparam("ids", expanding=True)),
                {"ids": [p["IdParametro"] for p in seleccion], "agencia": agencia},
            ).mappings()
        ]
    responsables = nombres(valores, actor)
    return {
        "items": [
            presentar(
                dict(p),
                [v for v in valores if v["IdParametro"] == p["IdParametro"]],
                agencia,
                hoy(),
                actor,
                responsables,
            )
            for p in seleccion
        ],
        "total": len(filtradas),
        "page": page,
        "pageSize": page_size,
        "modulos": sorted({f["Modulo"] for f in filas}),
    }


@router.get("/{clave}", dependencies=LECTURA + [Depends(solo_parametros("idAgencia"))])
def consultar(
    clave: str,
    conn: Coop,
    usuario: UsuarioActual,
    actor: Actual,
    id_agencia: str | None = Query(None, alias="idAgencia", pattern=r"^\d{3}$"),
) -> dict[str, Any]:
    lectura(actor)
    return detalle(conn, clave, alcance(actor, usuario, id_agencia), hoy(), actor)


def cancelar_futuro(
    conn: Connection, clave: str, id_valor: int, agencia: str | None, fecha: date
) -> None:
    general.definicion(conn, clave, bloquear=True)
    valores = [
        v for v in general.historial(conn, clave, agencia) if v["IdAgencia"] == agencia
    ]
    objetivo = next((v for v in valores if v["IdParametroValor"] == id_valor), None)
    if objetivo is None:
        raise problema(
            404, "VALOR_NO_ENCONTRADO", "El valor no existe en este alcance."
        )
    if objetivo["VigenciaDesde"] <= fecha:
        raise problema(
            409,
            "VALOR_YA_VIGENTE",
            "Un valor cuya vigencia ya inicio no se puede cancelar.",
        )
    if objetivo["Estado"] != "A":
        raise problema(409, "VALOR_CANCELADO", "El valor ya esta cancelado.")
    anterior = next(
        (
            v
            for v in valores
            if v["IdParametroValor"] == objetivo["IdValorAnterior"]
            and v["Estado"] == "A"
        ),
        None,
    )
    siguientes = [
        v for v in valores if v["Estado"] == "A" and v["IdValorAnterior"] == id_valor
    ]
    if len(siguientes) > 1:
        raise problema(
            409,
            "CADENA_VIGENCIAS_INVALIDA",
            "La cadena de programacion requiere revision.",
        )
    siguiente = siguientes[0] if siguientes else None
    conn.execute(
        text(
            "UPDATE Parametros.ParametroValor SET Estado='C' WHERE IdParametroValor=:id AND Estado='A'"
        ),
        {"id": id_valor},
    )
    if anterior:
        if anterior["VigenciaHasta"] != objetivo["VigenciaDesde"] - timedelta(days=1):
            raise problema(
                409,
                "VIGENCIA_DESACTUALIZADA",
                "El valor anterior cambio; vuelva a consultar.",
            )
        hasta = (
            siguiente["VigenciaDesde"] - timedelta(days=1)
            if siguiente
            else objetivo["VigenciaHastaAnterior"]
        )
        conn.execute(
            general._sql(
                "UPDATE Parametros.ParametroValor SET VigenciaHasta=:hasta WHERE IdParametroValor=:id"
            ),
            {"id": anterior["IdParametroValor"], "hasta": hasta},
        )
    if siguiente:
        conn.execute(
            general._sql(
                "UPDATE Parametros.ParametroValor SET IdValorAnterior=:anterior,VigenciaHastaAnterior=:hasta WHERE IdParametroValor=:id"
            ),
            {
                "id": siguiente["IdParametroValor"],
                "anterior": anterior["IdParametroValor"] if anterior else None,
                "hasta": objetivo["VigenciaHastaAnterior"],
            },
        )


@router.post(
    "/{clave}/valores",
    status_code=201,
    dependencies=[Depends(solo_parametros())],
    responses={202: {"model": SolicitudAceptada}},
)
def programar(
    clave: Clave,
    payload: ValorNuevo,
    response: Response,
    conn: Coop,
    actor: Actual,
    cola: Cola,
    usuario: UsuarioActual,
    request: Request,
) -> dict[str, Any]:
    escritura(actor)
    aprobaciones.alcance_operativo(actor, usuario, payload.id_agencia)
    if payload.vigencia_desde < hoy():
        raise problema(
            422, "VIGENCIA_PASADA", "La fecha de inicio no puede ser anterior a hoy."
        )
    p = general.definicion(conn, clave, bloquear=True)
    if p["EsSensible"]:
        conn.rollback()
        id_ = cola.solicitar(
            actor,
            "PAR-EDITAR",
            Objetivo("Parametro", clave, payload.id_agencia),
            {
                "valor": payload.valor,
                "vigenciaDesde": payload.vigencia_desde.isoformat(),
            },
            hoy(),
            aprobaciones.contexto(request, usuario),
        )
        response.status_code = 202
        return SolicitudAceptada(id_solicitud=id_).model_dump(by_alias=True)
    try:
        antes = general.historial(conn, clave, payload.id_agencia)
        id_ = general.programar(
            conn,
            clave,
            payload.valor,
            payload.vigencia_desde,
            agencia=payload.id_agencia,
            actor=actor.sujeto,
        )
        despues = general.historial(conn, clave, payload.id_agencia)
        auditar(
            conn,
            "PAR_VALOR_REGISTRADO",
            actor,
            clave,
            payload.id_agencia,
            request,
            usuario,
            antes,
            despues,
        )
        conn.commit()
        return {"idParametroValor": id_, "estado": "Registrado"}
    except Exception:
        conn.rollback()
        raise


@router.delete(
    "/{clave}/valores/{id_valor}",
    status_code=204,
    dependencies=[Depends(solo_parametros("idAgencia"))],
)
def cancelar(
    clave: Clave,
    id_valor: IdValor,
    conn: Coop,
    actor: Actual,
    usuario: UsuarioActual,
    request: Request,
    id_agencia: str | None = Query(None, alias="idAgencia", pattern=r"^[0-9]{3}$"),
) -> Response:
    escritura(actor)
    aprobaciones.alcance_operativo(actor, usuario, id_agencia)
    try:
        general.definicion(conn, clave, bloquear=True)
        antes = general.historial(conn, clave, id_agencia)
        cancelar_futuro(conn, clave, id_valor, id_agencia, hoy())
        despues = general.historial(conn, clave, id_agencia)
        auditar(
            conn,
            "PAR_VALOR_CANCELADO",
            actor,
            clave,
            id_agencia,
            request,
            usuario,
            antes,
            despues,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return Response(status_code=204)


@router.patch(
    "/{clave}/valores/{id_valor}", dependencies=[Depends(solo_parametros("idAgencia"))]
)
def intentar_editar(
    clave: Clave,
    id_valor: IdValor,
    conn: Coop,
    actor: Actual,
    usuario: UsuarioActual,
    id_agencia: str | None = Query(None, alias="idAgencia", pattern=r"^[0-9]{3}$"),
) -> None:
    """Los valores son inmutables: una correccion se registra como un valor nuevo."""
    escritura(actor)
    aprobaciones.alcance_operativo(actor, usuario, id_agencia)
    valores = general.historial(conn, clave, id_agencia)
    valor = next(
        (
            v
            for v in valores
            if v["IdParametroValor"] == id_valor and v["IdAgencia"] == id_agencia
        ),
        None,
    )
    if valor is None:
        raise problema(
            404, "VALOR_NO_ENCONTRADO", "El valor no existe en este alcance."
        )
    if valor["VigenciaDesde"] < hoy():
        raise problema(
            422,
            "VIGENCIA_PASADA",
            "Un valor historico no se edita; registre un nuevo valor desde hoy.",
        )
    raise problema(
        409,
        "VALOR_NO_EDITABLE",
        "Cancele el valor futuro y programe otro; los valores registrados no se editan.",
    )
