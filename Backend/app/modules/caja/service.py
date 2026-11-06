"""Reglas de negocio de Caja.

Las consultas respetan los permisos de WorkOS y el aislamiento por agencia.
Las operaciones de escritura deben ejecutarse en transacciones de BD.
"""

from datetime import date

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.core.security.auth import Usuario
from app.core.security.operador import exigir_agencia
from app.modules.caja import repository as repo
from app.modules.caja.repository import Fila
from app.modules.caja.schemas import CajaFisica, Jornada, PageJornada

ROLES_GLOBALES = frozenset({"CONTADOR", "AUDITOR", "ADMIN"})


def agencia_consultable(
    usuario: Usuario,
    pedida: str | None,
    roles_globales: frozenset[str],
) -> str | None:
    """Determina qué agencia puede consultar un usuario.

    Los roles globales pueden consultar cualquier agencia.
    Los demás usuarios solamente pueden consultar su agencia asignada.
    """

    if set(usuario.roles) & roles_globales:
        return pedida

    propia = exigir_agencia(usuario)

    if pedida is not None and pedida != propia:
        raise problema(
            403,
            "SIN_ACCESO_AGENCIA",
            "No tiene acceso a los datos de esa agencia.",
        )

    return propia


def _caja(fila: Fila) -> CajaFisica:
    """Convierte una fila SQL al modelo CajaFisica."""

    return CajaFisica(
        id_caja_fisica=fila["IdCajaFisica"],
        id_agencia=fila["IdAgencia"],
        codigo_caja=fila["CodigoCaja"],
        estado=fila["Estado"],
        descripcion_estado=fila["DescripcionEstado"],
        limite_efectivo_caja=fila["LimiteEfectivoCaja"],
    )


# ---------------------------------------------------------------------
# CAJ-01: Listado de cajas físicas
# ---------------------------------------------------------------------


def listar_cajas_fisicas(
    conn: Connection,
    usuario: Usuario,
    id_agencia: str | None,
    activa: bool | None,
) -> list[CajaFisica]:
    """Lista cajas físicas según los permisos de agencia."""

    agencia = agencia_consultable(
        usuario,
        id_agencia,
        frozenset({"ADMIN"}),
    )

    filas = repo.listar_cajas_fisicas(
        conn,
        agencia,
        activa,
    )

    return [_caja(fila) for fila in filas]


# ---------------------------------------------------------------------
# CAJ-02: Consulta de jornadas
# ---------------------------------------------------------------------


SORT_JORNADAS = frozenset(
    {
        "idJornadaCaja",
        "idUsuario",
        "idCajaFisica",
        "idAgencia",
        "fechaHoraApertura",
        "fechaHoraCierre",
        "dineroInicial",
        "estado",
    }
)


def _jornada(fila: Fila) -> Jornada:
    """Convierte una fila SQL al modelo Jornada."""

    return Jornada(
        id_jornada_caja=fila["IdJornadaCaja"],
        id_usuario=fila["IdUsuario"],
        id_caja_fisica=fila["IdCajaFisica"],
        id_agencia=fila["IdAgencia"].strip(),
        fecha_hora_apertura=fila["FechaHoraApertura"],
        fecha_hora_cierre=fila["FechaHoraCierre"],
        dinero_inicial=fila["DineroInicial"],
        estado=fila["Estado"],
        observacion=fila["Observacion"],
    )


def listar_jornadas(
    conn: Connection,
    *,
    usuario: Usuario,
    id_agencia: str | None,
    id_usuario: int | None,
    estado: str | None,
    desde: date | None,
    hasta: date | None,
    page: int,
    page_size: int,
    sort: str,
) -> PageJornada:
    """Consulta paginada de jornadas con restricciones por agencia."""

    # Validar agencia autorizada.
    agencia = agencia_consultable(
        usuario,
        id_agencia,
        frozenset({"CONTADOR", "AUDITOR"}),
    )

    # Validar rango de fechas.
    if desde is not None and hasta is not None and desde > hasta:
        raise problema(
            400,
            "RANGO_FECHAS_INVALIDO",
            "La fecha desde no puede ser posterior a hasta.",
        )

    if hasta == date.max:
        raise problema(
            400,
            "FECHA_HASTA_INVALIDA",
            "La fecha hasta está fuera del rango permitido.",
        )

    # Validar ordenamiento permitido.
    partes = sort.split(",")

    if (
        len(partes) != 2
        or partes[0] not in SORT_JORNADAS
        or partes[1] not in {"asc", "desc"}
    ):
        raise problema(
            400,
            "ORDEN_INVALIDO",
            "El ordenamiento solicitado no es válido.",
        )

    # Consultar únicamente la agencia autorizada.
    filas, total = repo.listar_jornadas(
        conn,
        id_agencia=agencia,
        id_usuario=id_usuario,
        estado=estado,
        desde=desde,
        hasta=hasta,
        page=page,
        page_size=page_size,
        sort=sort,
    )

    return PageJornada(
        items=[_jornada(fila) for fila in filas],
        page=page,
        page_size=page_size,
        total=total,
    )
