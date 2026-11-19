"""Cambios de reglas E3-04 por la cola real E0-08."""

from datetime import date
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text

from app.core.api.errors import problema
from app.modules.aprobaciones.motores import motor
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.parametros.service import hoy
from app.modules.productos import numeracion as n
from app.modules.productos.numeracion_schemas import ReglaEntrada
from app.modules.productos.programacion import id_subproducto, subproducto

CODIGO = "PRD-NUMERACION"


def modelo(conn: Connection, objetivo: Objetivo) -> dict:
    fila = subproducto(conn, id_subproducto(objetivo))
    if fila["TipoProducto"] != "Cuenta":
        raise problema(
            422,
            "TIPO_PRODUCTO_INVALIDO",
            "La numeracion corresponde a subproductos de cuenta.",
        )
    return fila


class ProgramadorNumeracion:
    def __init__(self, seguridad: Engine | None = None):
        self.seguridad = seguridad

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        modelo(conn, objetivo)
        return n.version(conn, id_subproducto(objetivo))

    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan:
        n.bloqueo(conn, exclusivo=True)
        sub = modelo(conn, objetivo)
        id_sub = id_subproducto(objetivo)
        actuales = n.reglas(conn, id_sub)
        n.impedir_edicion_usada(conn, id_sub, actuales)
        try:
            nueva = ReglaEntrada.model_validate(contenido)
        except ValidationError:
            raise problema(
                422,
                "REGLA_INVALIDA",
                "Revise el prefijo, la longitud y el verificador.",
            ) from None
        n.serie_compatible(conn, nueva, id_sub)
        anterior = n.vigente(conn, id_sub)
        contexto = {
            "nombre": sub["NombreSubProducto"],
            "producto": sub["NombreProducto"],
        }
        return Plan(
            {"regla": nueva.model_dump(mode="json", by_alias=True)},
            {
                "subproducto": contexto,
                "formato": n.configuracion(anterior).model_dump(
                    mode="json", by_alias=True
                )
                if anterior
                else {},
            },
            {
                "subproducto": contexto,
                "formato": nueva.model_dump(mode="json", by_alias=True),
            },
            self.version(conn, objetivo),
        )

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict[str, Any],
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        n.bloqueo(conn, exclusivo=True)
        modelo(conn, objetivo)
        id_sub = id_subproducto(objetivo)
        n.impedir_edicion_usada(conn, id_sub, n.reglas(conn, id_sub))
        regla = ReglaEntrada.model_validate(contenido["regla"])
        raiz = n.serie_compatible(conn, regla, id_sub)
        with (self.seguridad or motor("seguridad")).connect() as seg:
            actor = seg.execute(
                text(
                    "SELECT UsuarioID FROM Organizacion.Usuarios WHERE KeyUsuario=:sujeto AND Estado='Activo'"
                ),
                {"sujeto": solicitante},
            ).scalar_one()
        conn.execute(
            text(
                "UPDATE ProductosFinancieros.ReglaNumeracion SET Estado='I' WHERE IdSubProducto=:sub AND Estado='A'"
            ),
            {"sub": id_sub},
        )
        conn.execute(
            text(
                "INSERT ProductosFinancieros.ReglaNumeracion(IdSubProducto,Prefijo,LongitudSecuencia,VigenciaDesde,Estado,IncluyeAgencia,AlgoritmoVerificador,Usada,IdSolicitud,CreadoPor,IdReglaSecuencia) VALUES(:sub,:prefijo,:longitud_secuencia,:fecha,'A',:incluye_agencia,:algoritmo_verificador,0,:solicitud,:actor,:raiz)"
            ),
            {
                **regla.model_dump(),
                "sub": id_sub,
                "fecha": hoy(),
                "solicitud": id_solicitud,
                "actor": actor,
                "raiz": raiz,
            },
        )
        id_regla = conn.execute(
            text(
                "SELECT IdReglaNumeracion FROM ProductosFinancieros.ReglaNumeracion WHERE IdSolicitud=:id"
            ),
            {"id": id_solicitud},
        ).scalar_one()
        if raiz is None:
            ultimo = n.inicial(conn, regla)
            if ultimo >= 10**regla.longitud_secuencia - 1:
                raise problema(
                    409, "SECUENCIA_AGOTADA", "El formato no tiene numeros disponibles."
                )
            conn.execute(
                text(
                    "INSERT ProductosFinancieros.SecuenciaCuenta(IdReglaNumeracion,UltimoNumero) VALUES(:id,:ultimo)"
                ),
                {"id": id_regla, "ultimo": ultimo},
            )


def operacion() -> Operacion:
    return Operacion(
        CODIGO,
        "SubProducto",
        "cooperativa",
        frozenset({"ADMIN"}),
        "productos:aprobar",
        ProgramadorNumeracion(),
        tabla_auditada="ProductosFinancieros.ReglaNumeracion",
        evento_ejecucion="PRD_NUMERACION_DEFINIDA",
        solicitud_directa=False,
        permiso_ejecucion="prd-numeracion",
    )
