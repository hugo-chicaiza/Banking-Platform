"""Cambios de estado del catálogo sujetos a la cola de aprobación E0-08."""

from datetime import date
from typing import Literal

from pydantic import ConfigDict, ValidationError
from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.api.schemas import CamelModel
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.productos import activacion, repository, service

CODIGO = "PRD-ESTADO"
TIPOS = ("Producto", "SubProducto")


class CambioEstado(CamelModel):
    model_config = ConfigDict(extra="forbid")
    estado: Literal["Activo", "Suspendido", "Retirado"]


class EstadoProducto:
    def _actual(self, conn: Connection, objetivo: Objetivo) -> dict:
        es_producto = objetivo.tipo == "Producto"
        consultar = (
            repository.obtener_producto
            if es_producto
            else repository.obtener_subproducto
        )
        actual = consultar(conn, int(objetivo.id), bloquear=True)
        if actual is None:
            codigo = (
                "PRODUCTO_NO_ENCONTRADO" if es_producto else "SUBPRODUCTO_NO_ENCONTRADO"
            )
            raise problema(404, codigo, "El objetivo no existe.")
        return actual

    def _validar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict, fecha: date
    ) -> tuple[dict, dict]:
        try:
            datos = CambioEstado.model_validate(contenido)
        except ValidationError:
            raise problema(
                422, "CONTENIDO_INVALIDO", "El estado propuesto no es válido."
            ) from None
        actual = self._actual(conn, objetivo)
        cambios = {"estado_catalogo": datos.estado}
        service._sincronizar_estado(actual, cambios)
        if datos.estado == actual["estado_catalogo"]:
            raise problema(409, "ESTADO_INVALIDO", "El objetivo ya tiene ese estado.")
        id_ = int(objetivo.id)
        es_producto = objetivo.tipo == "Producto"
        if datos.estado == "Activo":
            if not es_producto:
                activacion.exigir_activacion(conn, id_, fecha)
            elif not repository.listar_subproductos(conn, id_):
                raise problema(
                    409, "PRODUCTO_SIN_SUBPRODUCTOS", "Agregue al menos un subproducto."
                )
        if datos.estado == "Retirado":
            activacion.exigir_retiro(
                conn,
                id_sub=None if es_producto else id_,
                id_producto=id_ if es_producto else None,
            )
        return actual, cambios

    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict, hoy: date
    ) -> Plan:
        actual, cambios = self._validar(conn, objetivo, contenido, hoy)
        antes = actual["estado_catalogo"]
        despues = cambios["estado_catalogo"]
        return Plan({"estado": despues}, {"estado": antes}, {"estado": despues}, antes)

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        return self._actual(conn, objetivo)["estado_catalogo"]

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict,
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        from app.modules.parametros.service import hoy

        _, cambios = self._validar(conn, objetivo, contenido, hoy())
        actualizar = (
            repository.actualizar_producto
            if objetivo.tipo == "Producto"
            else repository.actualizar_subproducto
        )
        actualizar(conn, int(objetivo.id), cambios)


def operaciones() -> tuple[Operacion, ...]:
    return tuple(
        Operacion(
            CODIGO,
            tipo,
            "cooperativa",
            frozenset({"ADMIN"}),
            "productos:aprobar",
            EstadoProducto(),
            tabla_auditada=f"ProductosFinancieros.{tipo}",
            evento_ejecucion="PRD_ESTADO_CAMBIADO",
            solicitud_directa=False,
            permiso_ejecucion="prd-estado",
        )
        for tipo in TIPOS
    )
