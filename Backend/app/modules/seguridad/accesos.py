"""PolÃ­tica de secciones sobre PestanaRol; nunca concede operaciones de negocio."""

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.core.security import audit
from app.core.security.auth import ROLES, Usuario
from app.modules.seguridad import repository
from app.modules.seguridad.schemas import (
    AccesosEfectivos,
    ConfiguracionAccesos,
    PestanaRoles,
    PestanasConfig,
    SeccionAcceso,
)


@dataclass(frozen=True)
class Seccion:
    ruta: str
    nombre: str
    roles: tuple[str, ...]
    permiso: str | None = None


ATENCION = ("ADMIN", "ASESOR", "CAJERO", "SUPERVISOR")
CONTABLES = ("ADMIN", "CONTADOR", "AUDITOR")
SECCIONES = (
    Seccion("/parametros", "Parametros", ("ADMIN", "SUPERVISOR", "ASESOR")),
    Seccion("/organizacion/entidad", "Datos de la cooperativa", ("ADMIN", "ASESOR")),
    Seccion("/organizacion/agencias", "Agencias", ("ADMIN",)),
    Seccion("/productos", "Productos", ROLES, "prd-consultar"),
    Seccion("/catalogos", "CatÃ¡logos", ("ADMIN", "ASESOR", "SUPERVISOR")),
    Seccion("/registrar-cliente", "Registrar cliente", ("ADMIN", "ASESOR")),
    Seccion("/clientes-busqueda", "Consultar clientes", ATENCION),
    Seccion("/cuentas", "Consultar cuentas", ATENCION),
    Seccion("/cuentas/abrir", "Abrir cuenta", ("ADMIN", "ASESOR")),
    Seccion("/tarjetas", "Consultar tarjetas", ("ADMIN", "ASESOR", "SUPERVISOR")),
    Seccion("/solicitar-tarjeta", "Solicitar tarjeta", ("ADMIN", "ASESOR")),
    Seccion("/contabilidad", "Plan de cuentas", CONTABLES),
    Seccion("/contabilidad/asientos", "Asientos contables", CONTABLES),
    Seccion("/contabilidad/fecha-contable", "Fecha contable", CONTABLES),
    Seccion("/usuarios", "Usuarios del sistema", ("ADMIN",)),
    Seccion("/creditos", "Solicitudes de crÃ©dito", ("ADMIN", "ASESOR")),
)
POR_RUTA = {s.ruta: s for s in SECCIONES}
FIJAS = frozenset({"/", "/seguridad/roles", "/seguridad/pestanas"})
# CrÃ©ditos es una pantalla en preparaciÃ³n, sin APIs administradas por esta polÃ­tica.
SOLO_MENU = frozenset({"/creditos"})


def activa() -> bool:
    return get_settings().editor_accesos_activo


def version(filas: list[tuple[str, str]]) -> str:
    normalizadas = sorted((p, sorted(set(r.split(",")) - {""})) for p, r in filas)
    catalogo = [(s.ruta, s.roles, s.permiso) for s in SECCIONES]
    cuerpo = json.dumps(
        ["1", catalogo, normalizadas], ensure_ascii=True, separators=(",", ":")
    )
    return hashlib.sha256(cuerpo.encode()).hexdigest()


def _leer(conn: Connection) -> list[tuple[str, str]]:
    try:
        return repository.pestanas(conn)
    except SQLAlchemyError:
        raise problema(
            503, "ACCESOS_NO_DISPONIBLES", "No pudimos consultar los accesos."
        ) from None


def configuracion(conn: Connection) -> ConfiguracionAccesos:
    filas = _leer(conn)
    return ConfiguracionAccesos(
        version=version(filas),
        activa=activa(),
        pestanas=[
            PestanaRoles(pestana=p, roles=[r for r in ROLES if r in rs.split(",")])
            for p, rs in filas
            if p not in FIJAS
        ],
        secciones=[
            SeccionAcceso(ruta=s.ruta, nombre=s.nombre, roles=list(s.roles))
            for s in SECCIONES
        ],
    )


def resolver(conn: Connection, usuario: Usuario) -> AccesosEfectivos:
    filas = _leer(conn)
    personalizadas = {p: set(rs.split(",")) for p, rs in filas}
    roles = set(usuario.roles)
    habilitadas = ["/"]
    for seccion in SECCIONES:
        permitidos = set(seccion.roles) & personalizadas.get(
            seccion.ruta, set(seccion.roles)
        )
        if roles & permitidos and (
            seccion.permiso is None or seccion.permiso in usuario.permisos
        ):
            habilitadas.append(seccion.ruta)
    if "ADMIN" in roles:
        habilitadas.extend(["/seguridad/roles", "/seguridad/pestanas"])
    return AccesosEfectivos(version=version(filas), habilitadas=sorted(habilitadas))


def efectivos(usuario: Usuario) -> AccesosEfectivos:
    try:
        with get_engine("seguridad").connect() as conn:
            return resolver(conn, usuario)
    except SQLAlchemyError:
        raise problema(
            503, "ACCESOS_NO_DISPONIBLES", "No pudimos comprobar los accesos."
        ) from None


def validar(config: PestanasConfig) -> None:
    for pestana in config.pestanas:
        if pestana.pestana not in POR_RUTA and pestana.pestana not in SOLO_MENU:
            raise problema(
                422, "SECCION_DESCONOCIDA", "La secciÃ³n no pertenece al catÃ¡logo."
            )
        if len(pestana.roles) != len(set(pestana.roles)):
            raise problema(422, "ROL_DUPLICADO", "No repitas un rol en la secciÃ³n.")
        # No permite ampliar las restricciones vigentes. Las APIs conservan su control propio.
        seccion = POR_RUTA.get(pestana.pestana)
        if seccion and set(pestana.roles) - set(seccion.roles):
            raise problema(
                422,
                "ROL_INCOMPATIBLE",
                "Una secciÃ³n no concede operaciones a roles incompatibles.",
            )


def guardar(
    conn: Connection,
    config: PestanasConfig,
    usuario: Usuario,
    id_usuario: int,
    ip: str | None,
) -> list[PestanaRoles]:
    """Misma tabla y transacciÃ³n para configuraciÃ³n y auditorÃ­a; control optimista."""
    validar(config)
    if config.version is None or config.motivo is None:
        raise problema(
            409,
            "VERSION_Y_MOTIVO_REQUERIDOS",
            "Consulta la configuraciÃ³n e indica el motivo antes de guardar.",
        )
    try:
        with conn.begin():
            lock = conn.execute(
                text("""
                DECLARE @resultado int;
                EXEC @resultado = sys.sp_getapplock @Resource='enquo-pestanas',
                    @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=0;
                SELECT @resultado;
            """)
            ).scalar_one()
            if lock in (-1, -2, -3):
                raise problema(
                    409,
                    "EDICION_EN_CURSO",
                    "Otra persona estÃ¡ guardando. Consulta de nuevo.",
                )
            if lock not in (0, 1):
                raise problema(
                    503,
                    "COORDINACION_NO_DISPONIBLE",
                    "No se pudo coordinar el guardado.",
                )
            anteriores = _leer(conn)
            if version(anteriores) != config.version:
                raise problema(
                    409,
                    "CONFIGURACION_DESACTUALIZADA",
                    "La configuraciÃ³n cambiÃ³. Consulta de nuevo.",
                )
            nuevas = [
                (p.pestana, ",".join(r for r in ROLES if r in p.roles))
                for p in config.pestanas
            ]
            # No eliminar silenciosamente personalizaciones ajenas al catÃ¡logo.
            if any(p not in POR_RUTA and p not in SOLO_MENU for p, _ in anteriores):
                raise problema(
                    409,
                    "CATALOGO_DESACTUALIZADO",
                    "Existen secciones no reconocidas. Revisa el catÃ¡logo antes de guardar.",
                )
            repository.reemplazar_pestanas(conn, nuevas, id_usuario)
            antes, despues = dict(anteriores), dict(nuevas)
            for ruta in sorted(set(antes) | set(despues)):
                if antes.get(ruta) == despues.get(ruta):
                    continue
                audit.registrar_en_transaccion(
                    conn,
                    audit.EventoAuditoria(
                        accion="CONFIGURAR_ACCESOS",
                        tabla="Seguridad.PestanaRol",
                        id_registro=ruta,
                        resultado="Exitoso",
                        usuario=id_usuario,
                        ip=ip,
                        descripcion=f"antes={antes.get(ruta, 'POR_DEFECTO')} despues={despues.get(ruta, 'POR_DEFECTO')} motivo={config.motivo}",
                        roles=usuario.roles_texto(),
                    ),
                )
            return [
                PestanaRoles(pestana=p, roles=[r for r in ROLES if r in rs.split(",")])
                for p, rs in nuevas
            ]
    except SQLAlchemyError:
        raise problema(
            503,
            "GUARDADO_NO_CONFIRMADO",
            "No se pudo confirmar el guardado. Consulta el estado actual antes de reintentar.",
        ) from None
