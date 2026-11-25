from datetime import date

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.cuentas import retenciones as r

ALTA = "CTA-RETENCION"
LIBERACION = "CTA-LIBERACION"
PERMISO = "cta-retencion"
ROLES = frozenset({"ADMIN", "SUPERVISOR", "CUMPLIMIENTO"})


class AltaRetencion:
    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        fila = r.cuenta(conn, int(objetivo.id), objetivo.agencia)
        return f"{fila['Estado']}:{fila['Saldo']}:{fila['SaldoRetenido']}"

    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict, hoy: date
    ) -> Plan:
        datos = r.Alta.model_validate(contenido["datos"])
        fila = r.cuenta(conn, int(objetivo.id), objetivo.agencia)
        monto = r.monto_aplicable(fila, datos)
        if datos.fecha_fin is not None and datos.fecha_fin < hoy:
            raise problema(
                422, "FECHA_RETENCION_INVALIDA", "La fecha de término ya pasó."
            )
        return Plan(
            contenido,
            {"retenido": str(fila["SaldoRetenido"])},
            {"montoRetenido": str(monto)},
            self.version(conn, objetivo),
        )

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict,
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        fila = r.cuenta(conn, int(objetivo.id), objetivo.agencia)
        r.crear_retencion(
            conn,
            fila,
            r.Alta.model_validate(contenido["datos"]),
            contenido["actor"],
            clave=f"CTA-RETENCION:{id_solicitud}",
            solicitud=id_solicitud,
        )


class LiberarRetencion:
    def _obtener(self, conn: Connection, objetivo: Objetivo) -> tuple[dict, dict]:
        id_cuenta, id_retencion = map(int, objetivo.id.split(":"))
        fila = r.cuenta(conn, id_cuenta, objetivo.agencia)
        ret = r.retencion(conn, id_retencion, id_cuenta)
        return fila, ret

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        _, ret = self._obtener(conn, objetivo)
        return str(ret["Estado"])

    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict, hoy: date
    ) -> Plan:
        _, ret = self._obtener(conn, objetivo)
        if ret["Origen"] == "Modulo":
            raise problema(
                409,
                "RETENCION_DE_MODULO",
                "Solo el módulo de origen puede liberar esta retención.",
            )
        if ret["Estado"] != "Activa":
            raise problema(
                409, "SOLICITUD_DESACTUALIZADA", "La retención ya no está vigente."
            )
        return Plan(contenido, {"estado": "Activa"}, {"estado": "Liberada"}, "Activa")

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict,
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        fila, ret = self._obtener(conn, objetivo)
        r.liberar_retencion(
            conn,
            fila,
            ret,
            contenido["actor"],
            contenido["motivo"],
            clave=f"CTA-LIBERACION:{id_solicitud}",
            solicitud=id_solicitud,
        )


def operaciones() -> tuple[Operacion, Operacion]:
    return (
        Operacion(
            ALTA,
            "CuentaRetencion",
            "cooperativa",
            ROLES,
            PERMISO,
            AltaRetencion(),
            tabla_auditada="Cuentas.Retencion",
            evento_ejecucion="CTA_RETENCION",
            solicitud_directa=False,
            permiso_ejecucion=PERMISO,
        ),
        Operacion(
            LIBERACION,
            "Retencion",
            "cooperativa",
            ROLES,
            PERMISO,
            LiberarRetencion(),
            tabla_auditada="Cuentas.Retencion",
            evento_ejecucion="CTA_LIBERACION",
            solicitud_directa=False,
            permiso_ejecucion=PERMISO,
        ),
    )
