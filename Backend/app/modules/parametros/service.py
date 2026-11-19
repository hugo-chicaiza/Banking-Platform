"""E1-12: parámetros, asociaciones autenticadas y selección automática de reglas."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.core.security import audit
from app.core.security.auth import Usuario
from app.modules.parametros import repository as repo
from app.modules.parametros.schemas import (
    AsociarComision,
    CobroComision,
    Comision,
    ComisionCreate,
    ComisionUpdate,
    Exoneracion,
    ExoneracionCreate,
    ExoneracionUpdate,
)
from app.modules.transacciones.comisiones import ReglaExoneracion, calcular_comision

_ECUADOR = ZoneInfo("America/Guayaquil")


def hoy() -> date:
    return datetime.now(_ECUADOR).date()


def _codigo(error: HTTPException) -> str:
    detalle: Any = error.detail
    return (
        str(detalle.get("code", "ERROR_INTERNO"))
        if isinstance(detalle, dict)
        else "ERROR_INTERNO"
    )


@contextmanager
def _escribir(
    conn: Connection, tabla: str, actor: int, ip: str | None, id_: int | None = None
) -> Iterator[dict[str, Any]]:
    evento: dict[str, Any] = {"id": id_, "cambios": {}}
    resultado: audit.Resultado = "Fallido"
    motivo = "ERROR_INTERNO"
    try:
        yield evento
        conn.commit()
        resultado = "Exitoso"
    except DBAPIError as exc:
        conn.rollback()
        error = traducir_error_bd(exc)
        motivo = _codigo(error)
        raise error from None
    except HTTPException as exc:
        conn.rollback()
        motivo = _codigo(exc)
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        audit.registrar(
            audit.EventoAuditoria(
                accion="PAR_COMISION_REGISTRADA"
                if tabla == "Comisiones"
                else "PAR_EXONERACION_EDITADA",
                tabla="Transacciones." + tabla,
                id_registro=str(evento["id"]) if evento["id"] is not None else None,
                resultado=resultado,
                usuario=actor,
                ip=ip,
                descripcion=json.dumps(
                    {
                        "cambios": evento["cambios"],
                        "motivo": motivo if resultado == "Fallido" else None,
                    },
                    default=str,
                    ensure_ascii=False,
                ),
            )
        )


def _no_pasada(inicio: date) -> None:
    if inicio < hoy():
        raise problema(
            422,
            "VIGENCIA_PASADA",
            "No se puede crear o modificar un valor con inicio pasado.",
        )


def _comision(
    conn: Connection, id_: int, *, referencia: bool = False
) -> dict[str, Any]:
    fila = repo.obtener_comision(conn, id_)
    if fila is None:
        raise problema(
            422 if referencia else 404,
            "COMISION_NO_ENCONTRADA",
            "La comisión no existe.",
        )
    return fila


def _respuesta(conn: Connection, fila: dict[str, Any]) -> Comision:
    return Comision.model_validate(
        {**fila, "asociaciones": repo.asociaciones(conn, fila["id_comision"])}
    )


def listar_comisiones(conn: Connection) -> list[Comision]:
    return [_respuesta(conn, f) for f in repo.listar_comisiones(conn)]


def listar_exoneraciones(
    conn: Connection, id_comision: int | None
) -> list[Exoneracion]:
    return [
        Exoneracion.model_validate(f)
        for f in repo.listar_exoneraciones(conn, id_comision)
    ]


def _referencias_asociacion(conn: Connection, datos: dict[str, Any]) -> None:
    if not repo.canal_activo(conn, datos["id_canal"]):
        raise problema(
            422, "CANAL_NO_DISPONIBLE", "El canal no existe o no está activo."
        )
    if not repo.tipo_activo(conn, datos["codigo_tipo_transaccion"]):
        raise problema(
            422,
            "TIPO_TRANSACCION_NO_DISPONIBLE",
            "El tipo de transacción no existe o no está activo.",
        )


def _asociar(
    conn: Connection, fila: dict[str, Any], datos: dict[str, Any], actor: int
) -> None:
    if fila["id_canal"] != datos["id_canal"]:
        raise problema(
            422, "CANAL_COMISION_INCOMPATIBLE", "La comisión pertenece a otro canal."
        )
    if fila["estado"] != "A":
        raise problema(409, "COMISION_INACTIVA", "La comisión está inactiva.")
    if fila["vigencia_desde"] > datos["vigencia_desde"] or (
        fila["vigencia_hasta"] is not None
        and (
            datos["vigencia_hasta"] is None
            or datos["vigencia_hasta"] > fila["vigencia_hasta"]
        )
    ):
        raise problema(
            422,
            "VIGENCIA_FUERA_DE_COMISION",
            "La asociación debe estar dentro de la vigencia de la comisión.",
        )
    existentes = repo.asociaciones_solapadas(conn, datos)
    equivalentes = [
        f
        for f in existentes
        if f["id_comision"] == fila["id_comision"]
        and f["vigencia_desde"] == datos["vigencia_desde"]
        and f["vigencia_hasta"] == datos["vigencia_hasta"]
    ]
    if existentes and not (len(existentes) == 1 and equivalentes):
        raise problema(
            409,
            "COMISION_VIGENCIA_SOLAPADA",
            "Ya existe una comisión activa para esa operación, canal y vigencia.",
        )
    if not existentes:
        repo.insertar_asociacion(
            conn, {**datos, "id_comision": fila["id_comision"]}, actor
        )


def crear_comision(
    conn: Connection,
    entrada: ComisionCreate | AsociarComision,
    actor: int,
    ip: str | None,
) -> Comision:
    datos = entrada.model_dump()
    with _escribir(conn, "Comisiones", actor, ip) as evento:
        _no_pasada(entrada.vigencia_desde)
        repo.bloquear_comisiones(conn)
        _referencias_asociacion(conn, datos)
        if isinstance(entrada, AsociarComision):
            fila = _comision(conn, entrada.id_comision, referencia=True)
        else:
            if repo.codigo_existe(conn, entrada.codigo_comision):
                raise problema(
                    409, "CODIGO_COMISION_DUPLICADO", "El código de comisión ya existe."
                )
            id_ = repo.insertar_comision(conn, datos)
            fila = _comision(conn, id_)
        _asociar(conn, fila, datos, actor)
        evento.update(id=fila["id_comision"], cambios=datos)
        respuesta = _respuesta(conn, fila)
    return respuesta


def cambio_sensible(conn: Connection, id_: int, entrada: ComisionUpdate) -> bool:
    if entrada.vigencia_desde is not None:
        return True
    return entrada.valor is not None and entrada.valor != _comision(conn, id_)["valor"]


def actualizar_comision(
    conn: Connection,
    id_: int,
    entrada: ComisionUpdate,
    actor: int,
    ip: str | None,
    *,
    usuario: Usuario | None = None,
) -> Comision:
    cambios = entrada.model_dump(exclude_unset=True)
    with _escribir(conn, "Comisiones", actor, ip, id_) as evento:
        repo.bloquear_comisiones(conn)
        fila = _comision(conn, id_)
        evento["cambios"] = {
            k: {"antes": fila.get(k), "despues": v} for k, v in cambios.items()
        }
        if (
            "valor" in cambios and cambios["valor"] != fila["valor"]
        ) or "vigencia_desde" in cambios:
            raise problema(
                409, "TARIFA_REQUIERE_APROBACION", "Solicite el cambio de tarifa."
            )
        repo.actualizar_comision(conn, id_, cambios)
        respuesta = _respuesta(conn, _comision(conn, id_))
    return respuesta


def _validar_regla(
    conn: Connection, regla: ExoneracionCreate, id_: int | None = None
) -> None:
    _comision(conn, regla.id_comision, referencia=True)
    if regla.id_producto is not None and not repo.producto_existe(
        conn, regla.id_producto
    ):
        raise problema(422, "PRODUCTO_NO_ENCONTRADO", "El producto no existe.")
    if regla.id_sub_producto is not None:
        producto = repo.producto_de_subproducto(conn, regla.id_sub_producto)
        if producto is None:
            raise problema(
                422, "SUBPRODUCTO_NO_ENCONTRADO", "El subproducto no existe."
            )
        if regla.id_producto is not None and producto != regla.id_producto:
            raise problema(
                422,
                "SUBPRODUCTO_INCOMPATIBLE",
                "El subproducto no pertenece al producto indicado.",
            )
    # Una sola regla activa por alcance exacto. Los alcances más específicos
    # prevalecen al calcular; jamás se acumulan porcentajes.
    for otra in repo.listar_exoneraciones(conn, regla.id_comision):
        if (
            otra["id_exoneracion"] == id_
            or otra["estado"] != "A"
            or regla.estado != "A"
        ):
            continue
        mismo_alcance = (
            otra["id_sub_producto"] == regla.id_sub_producto
            and otra["tipo_cliente"] == regla.tipo_cliente
            and (
                regla.id_sub_producto is not None
                or otra["id_producto"] == regla.id_producto
            )
        )
        solapan = (
            regla.vigencia_hasta is None
            or otra["vigencia_desde"] < regla.vigencia_hasta
        ) and (
            otra["vigencia_hasta"] is None
            or otra["vigencia_hasta"] > regla.vigencia_desde
        )
        if mismo_alcance and solapan:
            raise problema(
                409,
                "EXONERACION_VIGENCIA_SOLAPADA",
                "Ya existe una regla activa para ese alcance y vigencia.",
            )


def crear_exoneracion(
    conn: Connection, entrada: ExoneracionCreate, actor: int, ip: str | None
) -> Exoneracion:
    with _escribir(conn, "ExoneracionComision", actor, ip) as evento:
        _no_pasada(entrada.vigencia_desde)
        repo.bloquear_comisiones(conn)
        repo.bloquear_exoneraciones(conn)
        _validar_regla(conn, entrada)
        id_ = repo.insertar_exoneracion(conn, entrada.model_dump(), actor)
        evento.update(id=id_, cambios=entrada.model_dump())
        respuesta = Exoneracion.model_validate(repo.obtener_exoneracion(conn, id_))
    return respuesta


def actualizar_exoneracion(
    conn: Connection, id_: int, entrada: ExoneracionUpdate, actor: int, ip: str | None
) -> Exoneracion:
    cambios = entrada.model_dump(exclude_unset=True)
    with _escribir(conn, "ExoneracionComision", actor, ip, id_) as evento:
        repo.bloquear_comisiones(conn)
        repo.bloquear_exoneraciones(conn)
        fila = repo.obtener_exoneracion(conn, id_)
        if fila is None:
            raise problema(404, "EXONERACION_NO_ENCONTRADA", "La regla no existe.")
        if set(cambios) - {"estado"}:
            _no_pasada(fila["vigencia_desde"])
        try:
            final = ExoneracionCreate.model_validate(
                {**{k: fila[k] for k in ExoneracionCreate.model_fields}, **cambios}
            )
        except ValidationError:
            raise problema(
                422, "DATOS_INVALIDOS", "La regla resultante no es válida."
            ) from None
        if set(cambios) - {"estado"}:
            _no_pasada(final.vigencia_desde)
        _validar_regla(conn, final, id_)
        evento["cambios"] = {
            k: {"antes": fila[k], "despues": v} for k, v in cambios.items()
        }
        repo.actualizar_exoneracion(conn, id_, cambios)
        respuesta = Exoneracion.model_validate(repo.obtener_exoneracion(conn, id_))
    return respuesta


def comision(
    conn: Connection,
    tipo: str,
    canal: int,
    cuenta: int,
    fecha: datetime,
    *,
    monto_operacion: Decimal,
) -> list[CobroComision]:
    """Selecciona y exonera sin intervención del cliente. Sin commit ni débito.

    El llamador debe mantener esta transacción y el bloqueo de cuenta hasta
    registrar el cobro; persistir también cada id_exoneracion devuelto.
    """
    fecha = fecha.astimezone(_ECUADOR).replace(tzinfo=None) if fecha.tzinfo else fecha
    if not monto_operacion.is_finite() or monto_operacion < 0:
        raise problema(422, "MONTO_INVALIDO", "El monto debe ser finito y no negativo.")
    contexto = repo.contexto_cuenta(conn, cuenta)
    if contexto is None:
        raise problema(422, "CUENTA_NO_ENCONTRADA", "La cuenta no existe.")
    previas = repo.operaciones_previas(conn, cuenta, tipo, canal, fecha)
    cobros = []
    for tarifa in repo.tarifas_vigentes(conn, tipo, canal, fecha.date()):
        base = tarifa["valor"]
        if tarifa["tipo_calculo"] == "Porcentaje":
            base = monto_operacion * base / Decimal(100)
            if tarifa["monto_minimo"] is not None:
                base = max(base, tarifa["monto_minimo"])
            if tarifa["monto_maximo"] is not None:
                base = min(base, tarifa["monto_maximo"])
        reglas = [
            r
            for r in repo.listar_exoneraciones(conn, tarifa["id_comision"])
            if r["estado"] == "A"
            and r["vigencia_desde"] <= fecha.date()
            and (r["vigencia_hasta"] is None or r["vigencia_hasta"] > fecha.date())
            and all(
                r[k] is None or r[k] == contexto[k]
                for k in ("id_producto", "id_sub_producto", "tipo_cliente")
            )
        ]

        def prioridad(r: dict[str, Any]) -> tuple[int, int]:
            return (
                2
                if r["id_sub_producto"] is not None
                else 1
                if r["id_producto"] is not None
                else 0,
                int(r["tipo_cliente"] is not None),
            )

        reglas.sort(key=prioridad, reverse=True)
        if len(reglas) > 1 and prioridad(reglas[0]) == prioridad(reglas[1]):
            raise problema(
                409,
                "EXONERACION_AMBIGUA",
                "Hay reglas de igual prioridad; corrija la configuración.",
            )
        regla = reglas[0] if reglas else None
        monto, id_regla = calcular_comision(
            base,
            ReglaExoneracion(
                regla["id_exoneracion"],
                regla["porcentaje_exonerado"],
                regla["operaciones_gratis_mes"],
            )
            if regla
            else None,
            previas,
        )
        cobros.append(
            CobroComision(
                id_comision=tarifa["id_comision"],
                monto_base=base,
                monto_cobrar=monto,
                id_exoneracion=id_regla,
            )
        )
    return cobros
