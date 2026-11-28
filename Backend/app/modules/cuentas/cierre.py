"""Lista de cierre, aprobación y certificado de cuenta (E6-07)."""

from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, StringConstraints, ValidationError
from sqlalchemy import Connection, Engine, text

from app.core.api.errors import problema
from app.core.api.schemas import CamelModel
from app.core.database.db import get_engine
from app.core.pdf import DocumentoPdf, institucion_actual
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.clientes import service as clientes_service
from app.modules.cuentas import repository

CODIGO = "CTA-CERRAR"
TIPO = "Cuenta"
PERMISO_APROBACION = "cuentas:aprobar"
ROLES = frozenset({"ASESOR", "ADMIN"})
_TERMINALES_TARJETA = ("Anulada", "Cancelada", "Cerrada", "Vencida")


class SolicitarCierre(CamelModel):
    model_config = ConfigDict(extra="forbid")
    motivo: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)
    ]


class VerificacionCierre(CamelModel):
    codigo: str
    resultado: Literal["Cumple", "Impide", "NoVerificable"]
    detalle: str


class ListaCierre(CamelModel):
    id_cuenta: int
    puede_cerrar: bool
    verificaciones: list[VerificacionCierre]


def _verificacion(
    codigo: str, cumple: bool | None, detalle: str
) -> VerificacionCierre:
    resultado = (
        "NoVerificable"
        if cumple is None
        else "Cumple"
        if cumple
        else "Impide"
    )
    return VerificacionCierre(codigo=codigo, resultado=resultado, detalle=detalle)


def _cuenta(
    conn: Connection,
    id_cuenta: int,
    agencia: str,
    *,
    bloquear: bool = False,
) -> dict[str, Any]:
    consulta = text("""
        SELECT IdCuenta, NumeroCuenta, IdCliente, RTRIM(IdAgencia) AS IdAgencia,
               Estado, Saldo, SaldoRetenido, FechaCierre
        FROM Cuentas.Cuenta WITH (XLOCK,HOLDLOCK)
        WHERE IdCuenta=:id AND IdAgencia=:agencia
    """) if bloquear else text("""
        SELECT IdCuenta, NumeroCuenta, IdCliente, RTRIM(IdAgencia) AS IdAgencia,
               Estado, Saldo, SaldoRetenido, FechaCierre
        FROM Cuentas.Cuenta
        WHERE IdCuenta=:id AND IdAgencia=:agencia
    """)
    fila = (
        conn.execute(
            consulta,
            {"id": id_cuenta, "agencia": agencia},
        )
        .mappings()
        .one_or_none()
    )
    if fila is None:
        raise problema(
            404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia."
        )
    return dict(fila)


def _retenciones_activas(conn: Connection, id_cuenta: int) -> bool:
    return bool(
        conn.execute(
            text("""
                SELECT TOP (1) 1
                FROM Cuentas.Retencion WITH (UPDLOCK,HOLDLOCK)
                WHERE IdCuenta=:id AND Estado='Activa'
            """),
            {"id": id_cuenta},
        ).scalar()
    )


def _tarjetas_vivas(conn: Connection, id_cuenta: int) -> bool:
    return bool(
        conn.execute(
            text("""
                SELECT TOP (1) 1
                FROM Tarjeta.Tarjeta WITH (UPDLOCK,HOLDLOCK)
                WHERE IdCuenta=:id AND Estado NOT IN (:anulada,:cancelada,:cerrada,:vencida)
            """),
            {
                "id": id_cuenta,
                "anulada": _TERMINALES_TARJETA[0],
                "cancelada": _TERMINALES_TARJETA[1],
                "cerrada": _TERMINALES_TARJETA[2],
                "vencida": _TERMINALES_TARJETA[3],
            },
        ).scalar()
    )


def _credito_vigente(conn: Connection, id_cuenta: int) -> bool:
    desembolsos = repository.desembolsos_de_cuenta(conn, id_cuenta)
    if any(d["estado"] == "PENDIENTE" for d in desembolsos):
        return True
    solicitudes = {
        d["id_solicitud"] for d in desembolsos if d["estado"] == "DESEMBOLSADO"
    }
    return any(
        clientes_service.credito_tiene_deuda(conn, id_solicitud)
        for id_solicitud in solicitudes
    )


def _solicitudes_pendientes(
    seguridad: Engine, id_cuenta: int, excluir: int | None = None
) -> bool:
    with seguridad.connect() as conn:
        return bool(
            conn.execute(
                text("""
                    SELECT TOP (1) 1
                    FROM Seguridad.SolicitudAprobacion
                    WHERE TipoObjetivo IN ('Cuenta','CuentaRetencion','Retencion')
                      AND (
                            (TipoObjetivo IN ('Cuenta','CuentaRetencion') AND IdObjetivo=:id)
                            OR (TipoObjetivo='Retencion' AND IdObjetivo LIKE :id_prefijo)
                      )
                      AND Estado='Pendiente'
                      AND (:excluir IS NULL OR IdSolicitud<>:excluir)
                """),
                {
                    "id": str(id_cuenta),
                    "id_prefijo": f"{id_cuenta}:%",
                    "excluir": excluir,
                },
            ).scalar()
        )


def _version(cuenta: dict[str, Any]) -> str:
    fecha = cuenta["FechaCierre"]
    return f"{cuenta['Estado']}:{fecha.isoformat() if fecha else ''}"


def _impedimentos(lista: ListaCierre) -> list[str]:
    return [
        f"{v.codigo}: {v.resultado} — {v.detalle}" for v in lista.verificaciones
    ]


def lista_cierre(
    conn: Connection,
    id_cuenta: int,
    agencia: str,
    *,
    seguridad: Engine | None = None,
    bloquear: bool = False,
    excluir_solicitud: int | None = None,
) -> ListaCierre:
    cuenta = _cuenta(conn, id_cuenta, agencia, bloquear=bloquear)
    retenciones = _retenciones_activas(conn, id_cuenta)
    tarjetas = _tarjetas_vivas(conn, id_cuenta)
    credito = _credito_vigente(conn, id_cuenta)
    solicitudes = _solicitudes_pendientes(
        seguridad or get_engine("seguridad"),
        id_cuenta,
        excluir_solicitud,
    )
    saldo_cero = (
        cuenta["Saldo"] == Decimal(0)
        and cuenta["SaldoRetenido"] == Decimal(0)
    )
    verificaciones = [
        _verificacion(
            "saldoCero",
            saldo_cero,
            "El saldo contable y el monto retenido son cero."
            if saldo_cero
            else "El saldo contable y el monto retenido deben ser cero.",
        ),
        _verificacion(
            "sinRetencionesActivas",
            not retenciones,
            "Hay retenciones activas."
            if retenciones
            else "No hay retenciones activas.",
        ),
        _verificacion(
            "sinTarjetasVivas",
            not tarjetas,
            "Hay tarjetas activas o pendientes; anúlelas primero."
            if tarjetas
            else "No hay tarjetas activas ni pendientes.",
        ),
        _verificacion(
            "sinCreditoRespaldado",
            not credito,
            "Hay un desembolso pendiente o un crédito vigente vinculado a la cuenta."
            if credito
            else "No hay desembolsos pendientes ni créditos vigentes vinculados.",
        ),
        _verificacion(
            "sinSolicitudesPendientes",
            not solicitudes,
            "Hay solicitudes pendientes para esta cuenta."
            if solicitudes
            else "No hay solicitudes pendientes para esta cuenta.",
        ),
        _verificacion(
            "sinInteresDevengadoImpago",
            None,
            "No existe un origen de datos de intereses devengados pendientes en el backend.",
        ),
        _verificacion(
            "estadoCuenta",
            cuenta["Estado"] in {"Activa", "Inactiva"},
            "La cuenta debe estar Activa o Inactiva y no cerrada."
            if cuenta["Estado"] not in {"Activa", "Inactiva"}
            else "El estado de cuenta permite solicitar el cierre.",
        ),
    ]
    return ListaCierre(
        id_cuenta=id_cuenta,
        puede_cerrar=all(v.resultado == "Cumple" for v in verificaciones),
        verificaciones=verificaciones,
    )


class Cierre:
    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        return _version(_cuenta(conn, int(objetivo.id), _agencia(objetivo)))

    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict, hoy: date
    ) -> Plan:
        try:
            datos = SolicitarCierre.model_validate(contenido)
        except ValidationError:
            raise problema(
                422, "CONTENIDO_INVALIDO", "Indique el motivo del cierre."
            ) from None
        lista = lista_cierre(
            conn, int(objetivo.id), _agencia(objetivo), seguridad=get_engine("seguridad")
        )
        if not lista.puede_cerrar:
            raise problema(
                409,
                "CIERRE_INCOMPLETO",
                "La cuenta no cumple todos los requisitos de cierre.",
                bloqueos=_impedimentos(lista),
            )
        cuenta = _cuenta(conn, int(objetivo.id), _agencia(objetivo))
        return Plan(
            datos.model_dump(mode="json", by_alias=True),
            {"estado": cuenta["Estado"]},
            {"estado": "Cerrada"},
            _version(cuenta),
        )

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict,
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        try:
            SolicitarCierre.model_validate(contenido)
        except ValidationError:
            raise problema(
                422, "CONTENIDO_INVALIDO", "Indique el motivo del cierre."
            ) from None
        with get_engine("seguridad").connect() as seguridad:
            aprobacion = seguridad.execute(
                text("""
                    SELECT IdInternoResolutor
                    FROM Seguridad.SolicitudAprobacion
                    WHERE IdSolicitud=:id AND CodigoTransaccion=:codigo
                      AND TipoObjetivo=:tipo AND Estado='Aprobada'
                      AND IdAgencia=:agencia AND IdInternoResolutor IS NOT NULL
                """),
                {
                    "id": id_solicitud,
                    "codigo": CODIGO,
                    "tipo": TIPO,
                    "agencia": _agencia(objetivo),
                },
            ).scalar_one_or_none()
        if aprobacion is None:
            raise problema(
                409, "APROBACION_NO_VALIDA", "No se pudo acreditar al aprobador."
            )
        cerrar(
            conn,
            int(objetivo.id),
            _agencia(objetivo),
            int(aprobacion),
            id_solicitud,
        )


def _agencia(objetivo: Objetivo) -> str:
    if objetivo.agencia is None:
        raise problema(403, "AGENCIA_REQUERIDA", "Seleccione una agencia activa.")
    return objetivo.agencia


def cerrar(
    conn: Connection,
    id_cuenta: int,
    agencia: str,
    aprobador: int,
    id_solicitud: int,
) -> None:
    cuenta = _cuenta(conn, id_cuenta, agencia, bloquear=True)
    lista = lista_cierre(
        conn,
        id_cuenta,
        agencia,
        seguridad=get_engine("seguridad"),
        bloquear=True,
        excluir_solicitud=id_solicitud,
    )
    if not lista.puede_cerrar:
        raise problema(
            409,
            "CIERRE_INCOMPLETO",
            "La cuenta ya no cumple todos los requisitos de cierre.",
            bloqueos=_impedimentos(lista),
        )
    repository.actualizar_estado_cuenta(conn, id_cuenta, "CERRADA")
    conn.execute(
        text("""
            INSERT Cuentas.CuentaEvento
                (IdCuenta,TipoEvento,EstadoAnterior,EstadoActual,Detalle,RealizadoPor,IdAgencia)
            VALUES (:cuenta,'Cierre',:anterior,'Cerrada',:detalle,:aprobador,:agencia)
        """),
        {
            "cuenta": id_cuenta,
            "anterior": cuenta["Estado"],
            "detalle": f"Cierre aprobado (solicitud {id_solicitud})",
            "aprobador": aprobador,
            "agencia": agencia,
        },
    )


def certificado_cierre(
    conn: Connection, id_cuenta: int, agencia: str, generado_por: str
) -> bytes:
    datos = (
        conn.execute(
            text("""
                SELECT c.NumeroCuenta, c.FechaCierre, c.Estado,
                       cl.Identificacion, cl.Nombres, cl.Apellidos, cl.RazonSocial
                FROM Cuentas.Cuenta AS c
                JOIN Clientes.Cliente AS cl ON cl.IdCliente=c.IdCliente
                WHERE c.IdCuenta=:id AND c.IdAgencia=:agencia
            """),
            {"id": id_cuenta, "agencia": agencia},
        )
        .mappings()
        .one_or_none()
    )
    if datos is None:
        raise problema(
            404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia."
        )
    if datos["Estado"] != "Cerrada" or datos["FechaCierre"] is None:
        raise problema(
            409, "CIERRE_PENDIENTE", "El certificado estará disponible al aprobarse."
        )
    titular = datos["RazonSocial"] or " ".join(
        valor for valor in (datos["Nombres"], datos["Apellidos"]) if valor
    )
    fecha = datos["FechaCierre"]
    if hasattr(fecha, "date"):
        fecha = fecha.date()
    doc = DocumentoPdf(
        "Certificado de cierre de cuenta",
        institucion=institucion_actual(conn),
        generado_por=generado_por,
    )
    doc.titulo("Certificado de cierre de cuenta")
    doc.parrafo(
        "Se certifica que la cuenta indicada quedó cerrada después de aprobarse su lista de verificación."
    )
    doc.campos(
        [
            ("Titular", titular),
            ("Identificación", datos["Identificacion"]),
            ("Número de cuenta", datos["NumeroCuenta"]),
            ("Fecha de cierre", fecha.isoformat()),
        ]
    )
    return doc.contenido()


OPERACION = Operacion(
    CODIGO,
    TIPO,
    "cooperativa",
    ROLES,
    PERMISO_APROBACION,
    Cierre(),
    tabla_auditada="Cuentas.Cuenta",
    evento_ejecucion="CTA_CIERRE",
    solicitud_directa=False,
    permiso_ejecucion=None,
    cancelable_por_solicitante=False,
    cancelar_por_revocacion=False,
)
