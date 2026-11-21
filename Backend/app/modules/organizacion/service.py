"""Reglas de mantenimiento y estado de las agencias."""

import logging
import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic.alias_generators import to_camel
from sqlalchemy import Connection
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.core.api.errors import problema, traducir_error_bd
from app.core.config.settings import Settings, get_settings
from app.core.database.db import get_engine
from app.core.security import audit
from app.core.security.auth import Usuario
from app.modules.aprobaciones.auditoria import ContextoAuditoria, encolar
from app.modules.aprobaciones.contratos import SolicitudAceptada
from app.modules.aprobaciones.identidad import Actor
from app.modules.organizacion import repository as repo
from app.modules.organizacion.schemas import (
    Agencia,
    AgenciaCreate,
    AgenciaEstado,
    AgenciaUpdate,
    Entidad,
    EntidadCreate,
    EntidadUpdate,
    EstadoAgencia,
    PresentacionInstitucion,
)

logger = logging.getLogger(__name__)


def sitio_web_seguro(valor: str | None) -> str | None:
    if not valor or any(ord(c) < 33 for c in valor.strip()):
        return None
    valor = valor.strip()
    try:
        url = urlsplit(valor)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            return None
        _ = url.port
    except ValueError:
        return None
    return valor


def resolver_presentacion(
    entidad: Mapping[str, Any] | None, settings: Settings
) -> PresentacionInstitucion:
    if entidad is not None:
        nombre = (entidad.get("nombre_comercial") or "").strip()
        nombre = nombre or (entidad.get("razon_social") or "").strip()
        return PresentacionInstitucion(
            nombre=nombre or None,
            sitio_web=sitio_web_seguro(entidad.get("sitio_web")),
            origen="ENTIDAD",
        )
    nombre = settings.cooperativa_nombre.strip()
    return PresentacionInstitucion(
        nombre=nombre or None,
        sitio_web=sitio_web_seguro(settings.cooperativa_sitio_web) if nombre else None,
        origen="ENTORNO" if nombre else "SIN_CONFIGURAR",
    )


def obtener_presentacion() -> PresentacionInstitucion:
    """Lectura pública; una caída SQL no se confunde con falta de configuración."""
    settings = get_settings()
    entidad = None
    if settings.cooperativa_db_server and settings.cooperativa_db_name:
        try:
            with get_engine("cooperativa").connect() as conn:
                entidad = repo.obtener_presentacion_entidad(conn)
        except SQLAlchemyError:
            raise problema(
                503,
                "INSTITUCION_NO_DISPONIBLE",
                "No se pudo consultar la presentación institucional.",
            ) from None
    return resolver_presentacion(entidad, settings)


TABLA = "Organizacion.Agencia"
SolicitarBaja = Callable[[str | None], SolicitudAceptada]

_TRANSICIONES: dict[str, frozenset[str]] = {
    "A": frozenset({"I"}),
    "I": frozenset({"A"}),
    "C": frozenset(),
}

# Restricción violada -> respuesta. Solo se lee el NOMBRE de la restricción en el
# mensaje del driver; el valor duplicado que trae SQL Server nunca se devuelve ni se
# registra.
_RESTRICCIONES: dict[str, tuple[int, str, str]] = {
    "PK_Agencia": (
        409,
        "AGENCIA_YA_EXISTE",
        "Ya existe una agencia con ese idAgencia.",
    ),
    "UQ_Agencia_Codigo": (
        409,
        "CODIGO_DUPLICADO",
        "Ya existe una agencia con ese código.",
    ),
    "UX_Agencia_KeyAgencia": (
        409,
        "KEY_AGENCIA_DUPLICADA",
        "Esa organización de WorkOS ya está vinculada a otra agencia.",
    ),
    "UX_Agencia_UnaMatriz": (409, "MATRIZ_YA_EXISTE", "Ya existe una agencia Matriz."),
    "FK_Agencia_Ciudad": (422, "CIUDAD_NO_ENCONTRADA", "La ciudad no existe."),
    "CK_Agencia_Tipo": (
        422,
        "TIPO_AGENCIA_INVALIDO",
        "El tipo de agencia no es válido.",
    ),
    "CK_Agencia_Estado": (422, "ESTADO_INVALIDO", "El estado no es válido."),
}
_NOMBRE_RESTRICCION = re.compile(
    r"'(PK_Agencia|UQ_Agencia_\w+|UX_Agencia_\w+|FK_Agencia_\w+|CK_Agencia_\w+)'"
)

_CONFLICTOS = {
    "Codigo": "UQ_Agencia_Codigo",
    "KeyAgencia": "UX_Agencia_KeyAgencia",
    "Matriz": "UX_Agencia_UnaMatriz",
}


def _error(restriccion: str) -> HTTPException:
    return problema(*_RESTRICCIONES[restriccion])


def traducir_error_agencia(exc: DBAPIError) -> HTTPException:
    """Nombre de la restricción de Agencia -> código propio; el resto, al traductor común."""
    nombres = _NOMBRE_RESTRICCION.findall(str(exc.orig))
    for nombre in nombres:
        if nombre in _RESTRICCIONES:
            logger.warning("organizacion: restriccion violada nombre=%s", nombre)
            return _error(nombre)
    return traducir_error_bd(exc)


def a_respuesta(fila: dict[str, Any]) -> Agencia:
    return Agencia.model_validate(
        {
            "id_agencia": str(fila["IdAgencia"]).rstrip(),
            "codigo": fila["Codigo"],
            "tipo_agencia": fila["TipoAgencia"],
            "estado": str(fila["Estado"]).rstrip(),
            "id_ciudad": fila["IdCiudad"],
            "telefono": fila["Telefono"],
            "direccion": fila["Direccion"],
            "fecha_creacion": fila["FechaCreacion"],
            "vinculada_workos": bool(fila["VinculadaWorkos"]),
        }
    )


def listar_agencias(conn: Connection, estado: EstadoAgencia | None) -> list[Agencia]:
    return [a_respuesta(fila) for fila in repo.listar_agencias(conn, estado)]


def obtener_agencia(conn: Connection, id_agencia: str) -> Agencia:
    fila = repo.obtener_agencia(conn, id_agencia, bloquear=False)
    if fila is None:
        raise problema(404, "AGENCIA_NO_ENCONTRADA", "La agencia no existe.")
    return a_respuesta(
        {
            **fila,
            "Telefono": fila["Telefono"] if (fila["Telefono"] or "").strip() else None,
            "Direccion": fila["Direccion"]
            if (fila["Direccion"] or "").strip()
            else None,
        }
    )


def _verificar_ciudad(conn: Connection, id_ciudad: int) -> None:
    if not repo.existe_ciudad(conn, id_ciudad):
        raise _error("FK_Agencia_Ciudad")


def _verificar_unicidad(
    conn: Connection,
    id_agencia: str | None,
    *,
    codigo: str | None,
    key_agencia: str | None,
    matriz: bool,
) -> None:
    conflictos = repo.conflictos_de_unicidad(
        conn,
        id_agencia=id_agencia,
        codigo=codigo,
        key_agencia=key_agencia,
        matriz=matriz,
    )
    for nombre in ("Codigo", "KeyAgencia", "Matriz"):
        if nombre in conflictos:
            raise _error(_CONFLICTOS[nombre])


class _Auditoria:
    """Un evento por operación, Exitoso o Fallido, con los mismos datos que CTA-05."""

    def __init__(
        self, accion: str, id_agencia: str, usuario: int, ip: str | None, trace_id: str
    ) -> None:
        self.accion = accion
        self.id_agencia = id_agencia
        self.usuario = usuario
        self.ip = ip
        self.trace_id = trace_id
        self.detalle = ""
        self.antes: Agencia | None = None
        self.despues: Agencia | None = None
        self.agencia_actor: str | None = None

    def registrar_cambio(
        self, conn: Connection, actor: Usuario, motivo: str | None = None
    ) -> None:
        identidad = Actor(
            actor.id_usuario,
            actor.id_organizacion or "",
            actor.nombre,
            self.usuario,
            actor.roles,
            frozenset(),
            (),
        )
        encolar(
            conn,
            self.accion,
            identidad,
            None,
            self.id_agencia,
            ContextoAuditoria(
                actor.id_sesion,
                self.ip or "",
                self.trace_id,
                agencia_actor=self.agencia_actor,
            ),
            cambios={
                "antes": self.antes.model_dump(mode="json", by_alias=True)
                if self.antes
                else None,
                "despues": self.despues.model_dump(mode="json", by_alias=True)
                if self.despues
                else None,
                "motivo": motivo,
            },
            tabla=TABLA,
            objetivo=self.id_agencia,
        )

    def registrar(self, resultado: audit.Resultado, motivo: str | None = None) -> None:
        partes = [self.detalle, f"traceId={self.trace_id[:64]}"]
        if motivo is not None:
            partes.append(f"motivo={motivo}")
        audit.registrar(
            audit.EventoAuditoria(
                accion=self.accion,
                tabla=TABLA,
                id_registro=self.id_agencia,
                resultado=resultado,
                usuario=self.usuario,
                ip=self.ip,
                descripcion="; ".join(p for p in partes if p),
            )
        )


def crear_agencia(
    conn: Connection,
    datos: AgenciaCreate,
    creado_por: int,
    ip: str | None,
    trace_id: str,
    actor: Usuario,
) -> Agencia:
    auditoria = _Auditoria(
        "ORG_AGENCIA_CREADA", "NO_ASIGNADO", creado_por, ip, trace_id
    )
    auditoria.detalle = (
        f"ORG01 codigo={datos.codigo} tipo={datos.tipo_agencia} "
        f"ciudad={datos.id_ciudad} workos={datos.key_agencia is not None}"
    )

    try:
        auditoria.agencia_actor = actor.agencia()
        _verificar_ciudad(conn, datos.id_ciudad)

        _verificar_unicidad(
            conn,
            None,
            codigo=datos.codigo,
            key_agencia=datos.key_agencia,
            matriz=datos.tipo_agencia == "Matriz",
        )

        id_agencia = repo.insertar_agencia(conn, datos.model_dump())
        auditoria.id_agencia = id_agencia

        fila = repo.obtener_agencia(conn, id_agencia)

        if fila is None:
            raise problema(
                500,
                "ERROR_INTERNO",
                "Error interno del servidor.",
            )

        auditoria.despues = a_respuesta(fila)
        auditoria.registrar_cambio(conn, actor)
        conn.commit()

    except DBAPIError as exc:
        conn.rollback()
        auditoria.registrar("Fallido")
        raise traducir_error_agencia(exc) from None

    except Exception:
        conn.rollback()
        auditoria.registrar("Fallido")
        raise

    return a_respuesta(fila)


def _cambios_efectivos(actual: dict[str, Any], datos: AgenciaUpdate) -> dict[str, Any]:
    """Solo los campos presentes cuyo valor difiere del guardado."""
    valores_actuales = {
        "codigo": actual["Codigo"],
        "tipo_agencia": actual["TipoAgencia"],
        "estado": str(actual["Estado"]).rstrip(),
        "id_ciudad": actual["IdCiudad"],
        "telefono": actual["Telefono"],
        "direccion": actual["Direccion"],
    }
    cambios: dict[str, Any] = {}
    for campo in sorted(datos.model_fields_set & set(repo.COLUMNAS_EDITABLES)):
        nuevo = getattr(datos, campo)
        # KeyAgencia no se lee de vuelta (no se publica): se escribe si viene
        if campo == "key_agencia" or valores_actuales[campo] != nuevo:
            cambios[campo] = nuevo
    return cambios


def _verificar_estado(
    conn: Connection, id_agencia: str, actual: dict[str, Any], nuevo: str
) -> None:
    anterior = str(actual["Estado"]).rstrip()
    if nuevo not in _TRANSICIONES.get(anterior, frozenset()):
        raise problema(
            409, "TRANSICION_INVALIDA", "El cambio de estado no está permitido."
        )
    if nuevo != "I":
        return
    if actual["TipoAgencia"] == "Matriz":
        raise problema(
            409, "MATRIZ_NO_DESACTIVABLE", "La agencia Matriz no se puede desactivar."
        )
    activas = repo.dependencias_activas(conn, id_agencia)
    if activas:
        raise problema(
            409,
            "AGENCIA_CON_OPERACION",
            "La agencia tiene recursos u operaciones activas: "
            + ", ".join(activas)
            + ".",
            bloqueos=activas,
        )


def validar_desactivacion(
    conn: Connection, id_agencia: str, actual: dict[str, Any]
) -> None:
    """Validacion compartida con el futuro manejador E0-08, bajo el lock del objetivo."""
    _verificar_estado(conn, id_agencia, actual, "I")


def _aprobacion_requerida() -> HTTPException:
    return problema(
        409,
        "APROBACION_REQUERIDA",
        "La desactivación requiere el servicio de aprobación de dos personas.",
    )


def _verificar_tipo(actual: dict[str, Any], nuevo: str) -> None:
    if actual["TipoAgencia"] == "Matriz" and nuevo != "Matriz":
        raise problema(
            409,
            "CAMBIO_MATRIZ_NO_PERMITIDO",
            "La Matriz no puede pasar a Sucursal sin una decisión funcional aprobada.",
        )


def actualizar_agencia(
    conn: Connection,
    id_agencia: str,
    datos: AgenciaUpdate,
    modificado_por: int,
    ip: str | None,
    trace_id: str,
    actor: Usuario,
    solicitar_baja: SolicitarBaja | None = None,
) -> Agencia | SolicitudAceptada:
    auditoria = _Auditoria(
        "ORG_AGENCIA_EDITADA", id_agencia, modificado_por, ip, trace_id
    )
    try:
        auditoria.agencia_actor = actor.agencia()
        actual = repo.obtener_agencia(conn, id_agencia, bloquear=True)
        if actual is None:
            raise problema(404, "AGENCIA_NO_ENCONTRADA", "La agencia no existe.")
        estado_actual = str(actual["Estado"]).rstrip()
        if estado_actual not in ("A", "I"):
            raise problema(
                409,
                "ESTADO_NO_HABILITADO",
                "La agencia está en un estado que la API todavía no gestiona.",
            )

        cambios = _cambios_efectivos(actual, datos)
        auditoria.detalle = "ORG02 " + " ".join(
            f"{to_camel(campo)}={_valor_auditable(campo, actual, valor)}"
            for campo, valor in cambios.items()
        )
        if not cambios:
            # Mismo estado y mismos datos: nada que escribir (idempotente)
            conn.rollback()
            return a_respuesta(actual)

        if (
            cambios.get("tipo_agencia") == "Matriz"
            and cambios.get("estado", estado_actual) != "A"
        ):
            raise problema(
                409,
                "MATRIZ_NO_DESACTIVABLE",
                "Active la agencia antes de promoverla a Matriz.",
            )
        if cambios.get("estado") == "I":
            validar_desactivacion(conn, id_agencia, actual)
            if cambios.keys() != {"estado"}:
                raise problema(
                    409,
                    "BAJA_CON_EDICION",
                    "Envíe los cambios de datos por separado de la solicitud de baja.",
                )
            if solicitar_baja is None:
                raise _aprobacion_requerida()
            conn.rollback()
            return solicitar_baja(datos.motivo)
        if "estado" in cambios:
            auditoria.accion = "ORG_AGENCIA_ESTADO"
            _verificar_estado(conn, id_agencia, actual, cambios["estado"])
        if "tipo_agencia" in cambios:
            _verificar_tipo(actual, cambios["tipo_agencia"])
        if "id_ciudad" in cambios:
            _verificar_ciudad(conn, cambios["id_ciudad"])
        _verificar_unicidad(
            conn,
            id_agencia,
            codigo=cambios.get("codigo"),
            key_agencia=cambios.get("key_agencia"),
            matriz=cambios.get("tipo_agencia") == "Matriz",
        )

        if repo.actualizar_agencia(conn, id_agencia, cambios) != 1:
            raise problema(404, "AGENCIA_NO_ENCONTRADA", "La agencia no existe.")
        fila = repo.obtener_agencia(conn, id_agencia)
        if (
            fila is None
        ):  # pragma: no cover - la fila está bloqueada por esta transacción
            raise problema(404, "AGENCIA_NO_ENCONTRADA", "La agencia no existe.")
        auditoria.antes = a_respuesta(actual)
        auditoria.despues = a_respuesta(fila)
        auditoria.registrar_cambio(conn, actor, datos.motivo)
        conn.commit()
    except DBAPIError as exc:
        conn.rollback()
        auditoria.registrar("Fallido", datos.motivo)
        raise traducir_error_agencia(exc) from None
    except Exception:
        conn.rollback()
        auditoria.registrar("Fallido", datos.motivo)
        raise
    return a_respuesta(fila)


def _valor_auditable(campo: str, actual: dict[str, Any], nuevo: Any) -> str:
    """anterior->nuevo. De KeyAgencia solo si queda vinculada (nunca el valor)."""
    if campo == "key_agencia":
        return f"vinculadaWorkos:{bool(actual['VinculadaWorkos'])}->{nuevo is not None}"
    if campo == "direccion":
        # Hasta 250 caracteres: no cabe con el resto en Auditoria.Descripcion (500)
        return "modificada" if nuevo is not None else "borrada"
    columna = repo.COLUMNAS_EDITABLES[campo]
    anterior = actual[columna]
    if isinstance(anterior, str):
        anterior = anterior.rstrip()
    return f"{anterior}->{nuevo}"


# Compatibilidad: endpoint de estado existente.


def _tipo_agencia_bloqueada(conn: Connection, id_agencia: str) -> str:
    fila = repo.obtener_agencia(conn, id_agencia, bloquear=True)
    if fila is None:
        raise problema(404, "AGENCIA_NO_ENCONTRADA", "No se encontró la agencia.")
    return str(fila["TipoAgencia"])


def _agencia_bloqueada(conn: Connection, id_agencia: str) -> AgenciaEstado:
    fila = repo.bloquear_agencia(conn, id_agencia)
    if fila is None:
        raise problema(404, "AGENCIA_NO_ENCONTRADA", "No se encontró la agencia.")
    return AgenciaEstado(**fila)


def solicitar_estado_inactivo(
    conn: Connection, id_agencia: str, motivo: str | None, solicitar: SolicitarBaja
) -> AgenciaEstado | SolicitudAceptada:
    with conn.begin():
        agencia = _agencia_bloqueada(conn, id_agencia)
        if agencia.estado == "I":
            return agencia
        if agencia.estado == "C":
            raise problema(
                409, "AGENCIA_CERRADA", "Una agencia cerrada no se puede reabrir."
            )
        validar_desactivacion(
            conn,
            id_agencia,
            {
                "Estado": agencia.estado,
                "TipoAgencia": _tipo_agencia_bloqueada(conn, id_agencia),
            },
        )
    return solicitar(motivo)


def cambiar_estado(
    conn: Connection,
    id_agencia: str,
    estado: EstadoAgencia,
    *,
    actor: Usuario | None = None,
    ip: str | None = None,
    trace_id: str = "",
    motivo: str | None = None,
) -> tuple[AgenciaEstado, str]:
    """Solo A ⇄ I; C es terminal. El lock dura hasta commit/rollback."""
    with conn.begin():
        agencia = _agencia_bloqueada(conn, id_agencia)
        anterior = agencia.estado
        if anterior == estado:
            return agencia, anterior
        if anterior == "C":
            raise problema(
                409, "AGENCIA_CERRADA", "Una agencia cerrada no se puede reabrir."
            )
        if estado == "C":
            raise problema(
                409,
                "CIERRE_AGENCIA_NO_HABILITADO",
                "El cierre de agencias aún no está definido.",
            )
        if estado == "I":
            validar_desactivacion(
                conn,
                id_agencia,
                {
                    "Estado": anterior,
                    "TipoAgencia": _tipo_agencia_bloqueada(conn, id_agencia),
                },
            )
            raise _aprobacion_requerida()
        usuario = actor.interno() if actor is not None else None
        if actor is None or usuario is None:
            raise problema(
                403, "USUARIO_NO_VINCULADO", "El usuario no tiene un vinculo interno."
            )
        auditoria = _Auditoria("ORG_AGENCIA_ESTADO", id_agencia, usuario, ip, trace_id)
        auditoria.agencia_actor = actor.agencia()
        auditoria.antes = obtener_agencia(conn, id_agencia)
        if not repo.actualizar_estado(conn, id_agencia, anterior, estado):
            raise problema(
                409,
                "ESTADO_AGENCIA_MODIFICADO",
                "El estado de la agencia cambió; vuelva a consultar.",
            )
        auditoria.despues = obtener_agencia(conn, id_agencia)
        auditoria.registrar_cambio(conn, actor, motivo)
    return AgenciaEstado(id_agencia=id_agencia, estado=estado), anterior


def exigir_agencia_destino_activa(conn: Connection, id_agencia: str) -> AgenciaEstado:
    """Punto de integración de AUT-06/AUT-11 antes de WorkOS y de asignar.

    El llamador debe abrir la transacción que escribirá la asignación y mantenerla
    abierta hasta terminar. Este guard no crea usuarios ni invita en WorkOS.
    """
    if not conn.in_transaction():
        raise RuntimeError(
            "La validación de agencia requiere la transacción de la asignación."
        )
    agencia = _agencia_bloqueada(conn, id_agencia)
    if agencia.estado != "A":
        raise problema(
            409, "AGENCIA_NO_ACTIVA", "La agencia destino debe estar activa."
        )
    return agencia


def obtener_entidad(conn: Connection, *, bloquear: bool = False) -> Entidad:
    fila = repo.obtener_entidad(conn, bloquear=bloquear)
    if fila is None:
        raise problema(404, "ENTIDAD_NO_ENCONTRADA", "No se encontró la entidad.")
    return Entidad(**fila)


def crear_entidad(
    conn: Connection, datos: EntidadCreate, modificado_por: int
) -> Entidad:
    """El bloqueo de rango serializa las altas simultáneas de la única entidad."""
    with conn.begin():
        if repo.obtener_entidad(conn, bloquear=True) is not None:
            raise problema(409, "ENTIDAD_YA_EXISTE", "La entidad ya está registrada.")
        repo.insertar_entidad(conn, datos.model_dump(), modificado_por)
        return obtener_entidad(conn)


def editar_entidad(
    conn: Connection, datos: EntidadUpdate, modificado_por: int
) -> tuple[Entidad, list[str]]:
    """Serializa ediciones y obtiene la respuesta persistida antes del commit."""
    with conn.begin():
        actual = obtener_entidad(conn, bloquear=True)
        cambios = {
            campo: valor
            for campo, valor in datos.model_dump(exclude_unset=True).items()
            if valor != getattr(actual, campo)
        }
        if not cambios:
            return actual, []
        repo.actualizar_entidad(conn, cambios, modificado_por)
        resultado = obtener_entidad(conn)
        return resultado, list(cambios)
