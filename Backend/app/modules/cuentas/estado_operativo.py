from datetime import date

from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.clientes import service as clientes
from app.modules.cuentas import repository

CODIGO = "CTA-ESTADO"
PERMISO_APROBAR = "cuentas:aprobar"


def bloquear_en_agencia(conn: Connection, id_cuenta: int, agencia: str) -> dict:
    cuenta = repository.bloquear_cuenta(conn, id_cuenta)
    if cuenta is None or cuenta["id_agencia"] != agencia:
        raise problema(
            404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia."
        )
    return cuenta


def exigir_estado(cuenta: dict, estado: str) -> None:
    if cuenta["estado"] != estado:
        raise problema(
            409, "TRANSICION_INVALIDA", "El cambio de estado no está permitido."
        )


def evento(
    conn: Connection,
    id_cuenta: int,
    agencia: str,
    tipo: str,
    anterior: str,
    actual: str,
    detalle: str,
    actor: int,
) -> None:
    conn.execute(
        text("""
            INSERT Cuentas.CuentaEvento
                (IdCuenta,TipoEvento,EstadoAnterior,EstadoActual,Detalle,RealizadoPor,IdAgencia)
            VALUES (:cuenta,:tipo,:anterior,:actual,:detalle,:actor,:agencia)
        """),
        {
            "cuenta": id_cuenta,
            "tipo": tipo,
            "anterior": anterior,
            "actual": actual,
            "detalle": detalle,
            "actor": actor,
            "agencia": agencia,
        },
    )


def motivos_bloqueo(conn: Connection) -> list[dict]:
    return [
        dict(fila)
        for fila in conn.exec_driver_sql("""
        SELECT Codigo AS codigo, Nombre AS nombre FROM Catalogo.MotivoBloqueoCuenta
        WHERE Estado='A' ORDER BY Nombre
    """).mappings()
    ]


def bloquear(
    conn: Connection, id_cuenta: int, agencia: str, motivo: str, actor: int
) -> None:
    actual = bloquear_en_agencia(conn, id_cuenta, agencia)
    exigir_estado(actual, "ACTIVA")
    nombre = conn.execute(
        text("""
        SELECT Nombre FROM Catalogo.MotivoBloqueoCuenta WITH (HOLDLOCK)
        WHERE Codigo=:motivo AND Estado='A'
    """),
        {"motivo": motivo},
    ).scalar_one_or_none()
    if nombre is None:
        raise problema(
            422, "MOTIVO_BLOQUEO_INVALIDO", "Seleccione un motivo de bloqueo vigente."
        )
    repository.actualizar_estado_cuenta(conn, id_cuenta, "BLOQUEADA")
    evento(conn, id_cuenta, agencia, "Bloqueo", "Activa", "Bloqueada", nombre, actor)


def reactivar(
    conn: Connection,
    id_cuenta: int,
    agencia: str,
    documento: str,
    actor: int,
    motivo: str,
) -> None:
    cliente = repository.obtener_titular_cuenta(conn, id_cuenta)
    if cliente is None:
        raise problema(
            404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia."
        )
    clientes.validar_activacion_cuenta(conn, cliente)
    actual = bloquear_en_agencia(conn, id_cuenta, agencia)
    exigir_estado(actual, "INACTIVA")
    repository.actualizar_estado_cuenta(conn, id_cuenta, "ACTIVA")
    evento(
        conn,
        id_cuenta,
        agencia,
        "Reactivacion",
        "Inactiva",
        "Activa",
        f"{motivo}. Documento verificado: {documento}",
        actor,
    )


def _desbloquear(conn: Connection, objetivo: Objetivo, actor: int) -> None:
    id_cuenta = int(objetivo.id)
    agencia = _agencia(objetivo)
    cliente = repository.obtener_titular_cuenta(conn, id_cuenta)
    if cliente is None:
        raise problema(
            404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia."
        )
    clientes.validar_activacion_cuenta(conn, cliente)
    exigir_estado(bloquear_en_agencia(conn, id_cuenta, agencia), "BLOQUEADA")
    repository.actualizar_estado_cuenta(conn, id_cuenta, "ACTIVA")
    evento(
        conn,
        id_cuenta,
        agencia,
        "Desbloqueo",
        "Bloqueada",
        "Activa",
        "Desbloqueo aprobado en la cola",
        actor,
    )


def _agencia(objetivo: Objetivo) -> str:
    if objetivo.agencia is None:
        raise problema(403, "AGENCIA_REQUERIDA", "Seleccione una agencia activa.")
    return objetivo.agencia


class Desbloqueo:
    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict, hoy: date
    ) -> Plan:
        motivo = contenido.get("motivo")
        if not isinstance(motivo, str) or not motivo.strip() or len(motivo) > 300:
            raise problema(
                422, "MOTIVO_DESBLOQUEO_INVALIDO", "Indique el motivo del desbloqueo."
            )
        version = self.version(conn, objetivo)
        return Plan(
            {"motivo": motivo}, {"estado": "BLOQUEADA"}, {"estado": "ACTIVA"}, version
        )

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        id_cuenta = int(objetivo.id)
        cliente = repository.obtener_titular_cuenta(conn, id_cuenta)
        if cliente is None:
            raise problema(
                404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia."
            )
        clientes.validar_activacion_cuenta(conn, cliente)
        exigir_estado(
            bloquear_en_agencia(conn, id_cuenta, _agencia(objetivo)), "BLOQUEADA"
        )
        ultimo = conn.execute(
            text("""
            SELECT MAX(IdCuentaEvento) FROM Cuentas.CuentaEvento
            WHERE IdCuenta=:id AND TipoEvento='Bloqueo'
        """),
            {"id": id_cuenta},
        ).scalar_one()
        return f"BLOQUEADA:{ultimo or 0}"

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict,
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        raise RuntimeError("El desbloqueo requiere identificar al aprobador.")


OPERACION_DESBLOQUEO = Operacion(
    CODIGO,
    "Cuenta",
    "cooperativa",
    frozenset({"SUPERVISOR"}),
    PERMISO_APROBAR,
    Desbloqueo(),
    tabla_auditada="Cuentas.Cuenta",
    evento_ejecucion="CTA_DESBLOQUEO",
    solicitud_directa=False,
    aplicar_con_aprobador=_desbloquear,
)
