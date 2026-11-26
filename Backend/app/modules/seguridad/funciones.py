"""Autorización por funciones SQL, independiente de las asignaciones de WorkOS."""

import hashlib
import json

from fastapi import Request
from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.core.database.db import get_engine
from app.core.security import audit
from app.core.security.auth import ROLES, Usuario
from app.modules.seguridad import funciones_repository as repo
from app.modules.seguridad.funciones_catalogo import (
    FUNCIONES,
    FUNCIONES_TARJETA_OPERATIVAS,
    POR_ID,
    SECCIONES_LEGADAS,
    funcion_api,
)
from app.modules.seguridad.funciones_schemas import (
    AjusteFuncion,
    AutorizacionFunciones,
    CambiosFunciones,
    ConfiguracionFunciones,
    FuncionesGuardadas,
    FuncionVista,
)


def activa() -> bool:
    return get_settings().editor_funciones_activo


def version(ajustes: repo.Ajustes) -> str:
    catalogo = [
        (f.id, f.roles_iniciales, f.operaciones, f.rutas, f.dependencias, f.delegable)
        for f in FUNCIONES
    ]
    cuerpo = json.dumps(
        [activa(), catalogo, sorted((f, r, v) for (f, r), v in ajustes.items())],
        separators=(",", ":"),
    )
    return hashlib.sha256(cuerpo.encode()).hexdigest()


def _leer(conn: Connection) -> repo.Ajustes:
    try:
        if (
            activa()
            and conn.execute(
                text("SELECT COUNT(*) FROM Seguridad.PestanaRol")
            ).scalar_one()
        ):
            raise problema(
                503,
                "MIGRACION_PESTANAS_PENDIENTE",
                "Revisa las personalizaciones del editor anterior antes de activar funciones.",
            )
        ajustes = repo.leer(conn)
    except SQLAlchemyError:
        raise problema(
            503,
            "FUNCIONES_NO_DISPONIBLES",
            "No pudimos consultar los accesos por función.",
        ) from None
    for (funcion, rol), valor in ajustes.items():
        entrada = POR_ID.get(funcion)
        if entrada is None or rol not in ROLES or not entrada.delegable:
            raise problema(
                503,
                "CONFIGURACION_FUNCIONES_INVALIDA",
                "La configuración guardada requiere revisión.",
            )
        if not isinstance(valor, bool):
            raise problema(
                503,
                "CONFIGURACION_FUNCIONES_INVALIDA",
                "La configuración guardada requiere revisión.",
            )
    return ajustes


def permitido(ajustes: repo.Ajustes, funcion: str, rol: str) -> bool:
    if rol == "AUDITOR" and funcion in FUNCIONES_TARJETA_OPERATIVAS:
        return False
    return ajustes.get((funcion, rol), rol in POR_ID[funcion].roles_iniciales)


def _configuracion(ajustes: repo.Ajustes) -> ConfiguracionFunciones:
    return ConfiguracionFunciones(
        version=version(ajustes),
        activa=activa(),
        roles=list(ROLES),
        funciones=[
            FuncionVista(
                id=f.id,
                nombre=f.nombre,
                modulo=f.modulo,
                rutas=list(f.rutas),
                roles_iniciales=list(f.roles_iniciales),
                delegable=f.delegable,
                motivo_proteccion=None
                if f.delegable
                else "La asignación inicial de esta función está protegida.",
                dependencias=list(f.dependencias),
            )
            for f in FUNCIONES
        ],
        ajustes=[
            AjusteFuncion(funcion=f, rol=r, permitido=v)
            for (f, r), v in sorted(ajustes.items())
        ],
    )


def configuracion(conn: Connection) -> ConfiguracionFunciones:
    return _configuracion(_leer(conn))


def resolver(ajustes: repo.Ajustes, usuario: Usuario) -> AutorizacionFunciones:
    habilitadas = {
        f.id
        for f in FUNCIONES
        if any(permitido(ajustes, f.id, r) for r in usuario.roles if r in ROLES)
    }
    # Una configuración corrupta nunca concede una escritura sin sus prerequisitos.
    while True:
        completas = {
            id_ for id_ in habilitadas if set(POR_ID[id_].dependencias) <= habilitadas
        }
        if completas == habilitadas:
            break
        habilitadas = completas
    rutas = {ruta for id_ in habilitadas for ruta in POR_ID[id_].rutas}
    rutas.add("/")
    if "ADMIN" in usuario.roles:
        rutas.update({"/seguridad/roles", "/seguridad/pestanas"})
    return AutorizacionFunciones(
        version=version(ajustes), funciones=sorted(habilitadas), rutas=sorted(rutas)
    )


def efectivos(usuario: Usuario) -> AutorizacionFunciones:
    try:
        with get_engine("seguridad").connect() as conn:
            return resolver(_leer(conn), usuario)
    except SQLAlchemyError:
        raise problema(
            503,
            "FUNCIONES_NO_DISPONIBLES",
            "No pudimos comprobar los accesos por función.",
        ) from None


def autorizar_operacion(request: Request, usuario: Usuario) -> bool:
    """True solo si esta operación concreta fue autorizada por el modelo activo."""
    if not activa():
        return False
    id_ = funcion_api(request.method, request.url.path)
    if id_ is None:
        return False
    # No confiar en cabeceras ni en una función aportada por el cuerpo del cliente.
    comprobada = getattr(request.state, "funcion_autorizada", None)
    if comprobada == (id_, usuario.id_usuario):
        return True
    autorizacion = efectivos(usuario)
    if id_ not in autorizacion.funciones:
        raise problema(403, "FUNCION_NO_AUTORIZADA", "No tiene acceso a esta función.")
    request.state.funcion_autorizada = (id_, usuario.id_usuario)
    return True


def verificar_peticion(request: Request, usuario: Usuario) -> None:
    if autorizar_operacion(request, usuario):
        return
    # APIs compartidas o fuera de este catálogo conservan sus controles anteriores.
    from app.core.security.secciones import AMBITOS, seccion_api

    if any(
        request.url.path == p or request.url.path.startswith(p + "/") for p in AMBITOS
    ):
        clasificacion = seccion_api(request.method, request.url.path)
        if clasificacion in SECCIONES_LEGADAS:
            from app.core.security.secciones import verificar_seccion

            verificar_seccion(request, usuario)
            return
        if clasificacion is None or clasificacion:
            raise problema(
                503,
                "FUNCION_SIN_CLASIFICAR",
                "Esta operación necesita clasificación de funciones.",
            )


def _validar_cambios(datos: CambiosFunciones) -> None:
    vistas: set[tuple[str, str]] = set()
    for cambio in datos.cambios:
        clave = (cambio.funcion, cambio.rol)
        if clave in vistas:
            raise problema(
                422, "CAMBIO_DUPLICADO", "No repitas una función y rol en el envío."
            )
        vistas.add(clave)
        funcion = POR_ID.get(cambio.funcion)
        if funcion is None:
            raise problema(
                422, "FUNCION_DESCONOCIDA", "La función no pertenece al catálogo."
            )
        if not funcion.delegable:
            raise problema(
                422,
                "FUNCION_PROTEGIDA",
                "Esta función administrativa no se puede delegar ni retirar.",
            )
        if (
            cambio.rol == "AUDITOR"
            and cambio.permitido is True
            and cambio.funcion in FUNCIONES_TARJETA_OPERATIVAS
        ):
            raise problema(
                422,
                "FUNCION_PROTEGIDA",
                "El rol Auditor es de solo lectura en Tarjetas.",
            )


def _validar_dependencias(ajustes: repo.Ajustes, roles: set[str]) -> None:
    for funcion in FUNCIONES:
        for rol in roles:
            if permitido(ajustes, funcion.id, rol) and any(
                not permitido(ajustes, d, rol) for d in funcion.dependencias
            ):
                raise problema(
                    422,
                    "DEPENDENCIA_FUNCION_REQUERIDA",
                    f"{rol}: {funcion.nombre} requiere habilitar sus funciones de consulta.",
                )


def guardar(
    conn: Connection,
    datos: CambiosFunciones,
    actor: Usuario,
    id_actor: int,
    ip: str | None,
) -> FuncionesGuardadas:
    if "ADMIN" not in actor.roles or actor.interno() != id_actor:
        raise problema(
            403,
            "ADMINISTRACION_NO_AUTORIZADA",
            "Solo ADMIN con un vínculo interno válido puede configurar funciones.",
        )
    _validar_cambios(datos)
    aplicados = 0
    try:
        with conn.begin():
            lock = conn.execute(
                text("""
                DECLARE @r int;
                EXEC @r=sys.sp_getapplock @Resource='enquo-funciones',
                    @LockMode='Exclusive', @LockOwner='Transaction', @LockTimeout=0;
                SELECT @r;
            """)
            ).scalar_one()
            if lock in (-1, -2, -3):
                raise problema(
                    409,
                    "EDICION_EN_CURSO",
                    "Otra persona está guardando. Consulta la configuración actual.",
                )
            if lock not in (0, 1):
                raise problema(
                    503,
                    "COORDINACION_NO_DISPONIBLE",
                    "No pudimos coordinar el guardado.",
                )
            anteriores = _leer(conn)
            if datos.version != version(anteriores):
                raise problema(
                    409,
                    "CONFIGURACION_DESACTUALIZADA",
                    "La configuración cambió. Consulta el estado actual conservando tu borrador.",
                )
            nuevas = dict(anteriores)
            for cambio in datos.cambios:
                clave = (cambio.funcion, cambio.rol)
                if cambio.permitido is None:
                    nuevas.pop(clave, None)
                else:
                    nuevas[clave] = cambio.permitido
            _validar_dependencias(nuevas, {c.rol for c in datos.cambios})
            for cambio in datos.cambios:
                clave = (cambio.funcion, cambio.rol)
                antes, despues = anteriores.get(clave), nuevas.get(clave)
                if antes == despues:
                    continue
                repo.escribir(conn, *clave, despues, id_actor)
                descripcion = f"funcion={clave[0]} rol={clave[1]} antes={antes} despues={despues} motivo={datos.motivo}"
                audit.registrar_en_transaccion(
                    conn,
                    audit.EventoAuditoria(
                        accion="CONFIGURAR_FUNCION",
                        tabla="Seguridad.AccesoFuncionRol",
                        id_registro=hashlib.sha256(
                            f"{clave[0]}|{clave[1]}".encode()
                        ).hexdigest(),
                        resultado="Exitoso",
                        usuario=id_actor,
                        ip=ip,
                        descripcion=descripcion,
                        roles=actor.roles_texto(),
                    ),
                )
                aplicados += 1
            resultado = _configuracion(nuevas)
        # Construir la respuesta del estado guardado, no releer una versión de otro escritor.
        return FuncionesGuardadas(**resultado.model_dump(), cambios_aplicados=aplicados)
    except SQLAlchemyError:
        raise problema(
            503,
            "GUARDADO_NO_CONFIRMADO",
            "No pudimos confirmar el guardado. Consulta el estado antes de reintentar.",
        ) from None
