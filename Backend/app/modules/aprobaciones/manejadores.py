"""Adaptador real del servicio E0-09 para la cola E0-08; sin pantallas E1-10."""

from datetime import date

from pydantic import ConfigDict, Field, ValidationError
from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.api.schemas import CamelModel
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan, Registro
from app.modules.contabilidad.cuentas_producto import operacion as operacion_mapeo
from app.modules.organizacion.aprobacion import OPERACION_BAJA
from app.modules.parametros import general
from app.modules.parametros.aprobacion_comision import OPERACION_TARIFA
from app.modules.productos.estado_aprobacion import operaciones as operaciones_estado
from app.modules.productos.numeracion_aprobacion import (
    operacion as operacion_numeracion,
)
from app.modules.productos.programacion import operacion as operacion_productos


class PropuestaParametro(CamelModel):
    model_config = ConfigDict(extra="forbid")
    valor: str = Field(max_length=500)
    vigencia_desde: date


class Parametro:
    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict, hoy: date
    ) -> Plan:
        try:
            datos = PropuestaParametro.model_validate(contenido)
        except ValidationError:
            raise problema(
                422,
                "CONTENIDO_INVALIDO",
                "El cambio propuesto no cumple el contrato del parametro.",
            ) from None
        if datos.vigencia_desde < hoy:
            raise problema(
                422, "VIGENCIA_PASADA", "La vigencia no puede iniciar en el pasado."
            )
        definicion = general.validar(
            conn, objetivo.id, datos.valor, datos.vigencia_desde, None, objetivo.agencia
        )
        if not definicion["EsSensible"]:
            raise problema(
                409,
                "APROBACION_NO_REQUERIDA",
                "El parametro no requiere este flujo de aprobacion.",
            )
        valores = [
            v
            for v in general.historial(conn, objetivo.id, objetivo.agencia)
            if v["IdAgencia"] == objetivo.agencia and v["Estado"] == "A"
        ]
        if any(v["VigenciaDesde"] >= datos.vigencia_desde for v in valores):
            raise problema(
                422,
                "VIGENCIA_SOLAPADA",
                "Existe un valor con inicio igual o posterior.",
            )
        antes = {
            "clave": objetivo.id,
            "valores": [
                {
                    "valor": v["Valor"],
                    "vigenciaDesde": v["VigenciaDesde"].isoformat(),
                    "vigenciaHasta": v["VigenciaHasta"].isoformat()
                    if v["VigenciaHasta"]
                    else None,
                }
                for v in valores
            ],
        }
        return Plan(
            datos.model_dump(mode="json", by_alias=True),
            antes,
            {"clave": objetivo.id, **datos.model_dump(mode="json", by_alias=True)},
            self.version(conn, objetivo),
        )

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        return general.version(conn, objetivo.id, objetivo.agencia)

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict,
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        try:
            datos = PropuestaParametro.model_validate(contenido)
        except ValidationError:
            raise problema(
                422,
                "CONTENIDO_INVALIDO",
                "El cambio propuesto no cumple el contrato del parametro.",
            ) from None
        general.programar(
            conn,
            objetivo.id,
            datos.valor,
            datos.vigencia_desde,
            agencia=objetivo.agencia,
            actor=solicitante,
            solicitud=id_solicitud,
        )


def registro_inicial() -> Registro:
    from app.modules.auth.aprobacion_roles import operacion as operacion_roles
    from app.modules.contabilidad.plantillas import OPERACION_PLANTILLA
    from app.modules.cuentas.cambio_subproducto import OPERACION as cambio_subproducto

    registro = Registro()
    registro.agregar(
        Operacion(
            "PAR-EDITAR",
            "Parametro",
            "cooperativa",
            frozenset({"ADMIN"}),
            "parametros:aprobar",
            Parametro(),
        )
    )
    registro.agregar(OPERACION_BAJA)
    registro.agregar(OPERACION_TARIFA)
    registro.agregar(operacion_productos())
    registro.agregar(operacion_numeracion())
    registro.agregar(OPERACION_PLANTILLA)
    registro.agregar(cambio_subproducto)
    registro.agregar(operacion_mapeo())
    for operacion in operaciones_estado():
        registro.agregar(operacion)
    if roles := operacion_roles():
        registro.agregar(roles)
    return registro
