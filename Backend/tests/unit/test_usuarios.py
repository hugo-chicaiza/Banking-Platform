"""AUT-05..09 (C-05) y vínculo del primer login, sin red ni base.

WorkOS y el repositorio son falsos en memoria. La conexión falsa imita la transacción:
si algo falla dentro de `begin()`, la base vuelve a como estaba.
"""

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError
from workos.exceptions import BadRequestException, ServerException

from app.core.config.settings import get_settings
from app.core.database.db import cooperativa, seguridad
from app.core.security import auth
from app.main import app
from app.modules.auth import agencias as multiagencia
from app.modules.auth import agencias_repository as agencias_repo
from app.modules.auth import repository, service
from app.modules.caja import repository as caja_repo
from tests.sesion import ID_AUDITORIA, simular_sesion, usuario_con_roles

ORG = "org_enquocoop"
BASE = "/api/v1/usuarios"
ADMIN = replace(usuario_con_roles("ADMIN"), id_organizacion=ORG)
FECHA = datetime(2026, 11, 8, 10, 0)


def _fila(id_usuario: int, **cambios: Any) -> dict[str, Any]:
    fila = {
        "UsuarioID": id_usuario,
        "NombreUsuario": f"usuario{id_usuario}",
        "Nombres": "María",
        "Apellidos": "López",
        "Email": f"u{id_usuario}@correo.ec",
        "Estado": "Activo",
        "FechaCreacion": FECHA,
        "UltimoAcceso": None,
        "Cedula": f"{id_usuario:010d}",
        "AgenciaID": 1,
        "KeyUsuario": f"user_{id_usuario}",
        "RolesWorkOS": "CAJERO",
    }
    fila.update(cambios)
    return fila


def _http_error(cls: type[Exception]) -> Exception:
    respuesta = SimpleNamespace(
        headers={"X-Request-ID": "req_1"},
        status_code=500 if cls is ServerException else 400,
        json=lambda: {"code": "error_de_prueba", "message": "x"},
    )
    return cls(respuesta, {"code": "error_de_prueba"})  # type: ignore[arg-type]


class _Base:
    """Organizacion.Usuarios, Seguridad.Bloqueos y Caja.CajerosAsignadosAgencia."""

    def __init__(self) -> None:
        self.usuarios: dict[int, dict[str, Any]] = {
            1: _fila(1, RolesWorkOS="ADMIN"),  # el admin de la sesión (ID_AUDITORIA)
            2: _fila(2, Cedula="0926687856"),  # cajero vinculado
            3: _fila(3, KeyUsuario=None, RolesWorkOS="ASESOR"),  # invitación pendiente
        }
        self.bloqueos: list[dict[str, Any]] = []
        self.asignaciones: list[dict[str, Any]] = [
            {"IdUsuario": 2, "IdAgencia": "001", "Estado": 1, "AsignadoPor": 1}
        ]
        self.agencias = {"001", "002"}
        self.listados: list[dict[str, Any]] = []
        self.multi = {id_: ["001"] for id_ in self.usuarios}
        self.historial_multi: list[dict[str, Any]] = []
        self.contextos: dict[tuple[bytes, int], dict[str, Any]] = {}
        self.jornadas: dict[int, dict[str, Any]] = {}

    def estado(self) -> tuple[Any, ...]:
        return (
            self.usuarios,
            self.bloqueos,
            self.asignaciones,
            self.multi,
            self.historial_multi,
            self.contextos,
        )

    def restaurar(self, estado: tuple[Any, ...]) -> None:
        (
            self.usuarios,
            self.bloqueos,
            self.asignaciones,
            self.multi,
            self.historial_multi,
            self.contextos,
        ) = estado


class _Conn:
    def __init__(self, base: _Base) -> None:
        self.base = base
        self._respaldo_multi = copy.deepcopy(base.estado())
        self.fallar_commit = False
        self.rollbacks = 0

    @contextmanager
    def begin(self) -> Iterator[None]:
        respaldo = copy.deepcopy(self.base.estado())
        try:
            yield
            if self.fallar_commit:
                raise OperationalError("COMMIT", {}, Exception("sin red"))
        except BaseException:
            self.rollbacks += 1
            self.base.restaurar(respaldo)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def commit(self):
        if self.fallar_commit:
            raise OperationalError("COMMIT", {}, Exception("sin red"))
        self._respaldo_multi = copy.deepcopy(self.base.estado())

    def rollback(self):
        self.rollbacks += 1
        if hasattr(self, "_respaldo_multi"):
            self.base.restaurar(copy.deepcopy(self._respaldo_multi))


class _WorkOS:
    """Lo que usa el backend de workos.user_management."""

    def __init__(self) -> None:
        self.llamadas: list[tuple[str, Any]] = []
        self.errores: dict[str, Exception] = {}
        self.membresias = {
            "user_1": SimpleNamespace(
                id="om_1", user_id="user_1", status="active", role={"slug": "org-admin"}
            ),
            "user_2": SimpleNamespace(
                id="om_2",
                user_id="user_2",
                status="active",
                role={"slug": "org-cajero"},
            ),
        }
        for membresia in self.membresias.values():
            membresia.roles = None
        self.invitaciones = [
            SimpleNamespace(id="inv_3", email="u3@correo.ec", state="pending")
        ]
        # Usuarios de WorkOS por email (los vinculados no se buscan por email)
        self.usuarios: dict[str, SimpleNamespace] = {}
        self._n = 0

    def _registrar(self, nombre: str, datos: Any) -> None:
        if nombre in self.errores:
            raise self.errores[nombre]
        self.llamadas.append((nombre, datos))

    def nombres(self) -> list[str]:
        return [nombre for nombre, _ in self.llamadas]

    def send_invitation(self, **kwargs: Any) -> SimpleNamespace:
        self._registrar("send_invitation", kwargs)
        self._n += 1
        invitacion = SimpleNamespace(
            id=f"inv_n{self._n}", email=kwargs["email"], state="pending"
        )
        self.invitaciones.insert(0, invitacion)
        return invitacion

    def revoke_invitation(self, invitation_id: str) -> None:
        self._registrar("revoke_invitation", invitation_id)
        for invitacion in self.invitaciones:
            if invitacion.id == invitation_id:
                invitacion.state = "revoked"

    def list_invitations(self, *, email: str, organization_id: str) -> list[Any]:
        assert organization_id == ORG
        self._registrar("list_invitations", email)
        return [i for i in self.invitaciones if i.email == email]

    def list_users(self, *, email: str, limit: int) -> list[Any]:
        self._registrar("list_users", email)
        encontrado = self.usuarios.get(email)
        return [encontrado] if encontrado else []

    def list_organization_memberships(self, **kwargs: Any) -> list[Any]:
        assert kwargs["organization_id"] == ORG
        self._registrar("list_organization_memberships", kwargs)
        membresias = list(self.membresias.values())
        if kwargs.get("user_id"):
            membresias = [m for m in membresias if m.user_id == kwargs["user_id"]]
        return [m for m in membresias if m.status in kwargs["statuses"]]

    def deactivate_organization_membership(self, id_membresia: str) -> None:
        self._registrar("deactivate", id_membresia)
        self._membresia(id_membresia).status = "inactive"

    def reactivate_organization_membership(self, id_membresia: str) -> None:
        self._registrar("reactivate", id_membresia)
        self._membresia(id_membresia).status = "active"

    def update_organization_membership(
        self,
        *,
        organization_membership_id: str,
        role_slug: str | None = None,
        role_slugs: list[str] | None = None,
    ) -> None:
        self._registrar(
            "update_membership", (organization_membership_id, role_slugs or role_slug)
        )
        membresia = self._membresia(organization_membership_id)
        membresia.role = {"slug": role_slug} if role_slug else None
        membresia.roles = (
            [{"slug": slug} for slug in role_slugs] if role_slugs else None
        )

    def create_organization_membership(self, **kwargs: Any) -> Any:
        self._registrar("create_membership", kwargs)
        return SimpleNamespace(id="om_nueva")

    def delete_organization_membership(self, id_membresia: str) -> None:
        self._registrar("delete_membership", id_membresia)

    def update_user(self, **kwargs: Any) -> None:
        self._registrar("update_user", kwargs)

    def list_sessions(self, *, user_id: str) -> list[Any]:
        self._registrar("list_sessions", user_id)
        return [
            SimpleNamespace(id="session_a", status="active"),
            SimpleNamespace(id="session_b", status="revoked"),
        ]

    def revoke_session(self, *, session_id: str) -> None:
        self._registrar("revoke_session", session_id)

    def _membresia(self, id_membresia: str) -> Any:
        return next(m for m in self.membresias.values() if m.id == id_membresia)


@pytest.fixture()
def base(monkeypatch) -> _Base:
    datos = _Base()

    def listar_usuarios(_conn, **filtros):
        datos.listados.append(filtros)
        filas = [
            u
            for u in datos.usuarios.values()
            if filtros["estado"] in (None, u["Estado"])
        ]
        return filas, len(filas)

    def obtener_usuario(_conn, id_usuario, bloquear=False):
        if bloquear and isinstance(_conn, _Conn):
            _conn._respaldo_multi = copy.deepcopy(datos.estado())

        # Como una fila real: una copia, no cambia si luego se actualiza la tabla
        fila = datos.usuarios.get(id_usuario)
        return dict(fila) if fila else None

    def existe_duplicado(_conn, *, username, email, cedula, excluir_id=None):
        return any(
            u["UsuarioID"] != excluir_id
            and (
                u["NombreUsuario"] == username
                or u["Email"] == email
                or u["Cedula"] == cedula
            )
            for u in datos.usuarios.values()
        )

    def insertar_usuario(_conn, **campos):
        nuevo = max(datos.usuarios) + 1
        datos.usuarios[nuevo] = _fila(
            nuevo,
            NombreUsuario=campos["username"],
            Nombres=campos["nombres"],
            Apellidos=campos["apellidos"],
            Email=campos["email"],
            Cedula=campos["cedula"],
            AgenciaID=campos["agencia_id"],
            RolesWorkOS=campos["rol"],
            KeyUsuario=None,
        )
        return nuevo

    def actualizar_usuario(_conn, id_usuario, **campos):
        fila = datos.usuarios[id_usuario]
        for campo, columna in (
            ("nombres", "Nombres"),
            ("apellidos", "Apellidos"),
            ("email", "Email"),
            ("estado", "Estado"),
            ("agencia_id", "AgenciaID"),
        ):
            if campos[campo] is not None:
                fila[columna] = campos[campo]

    def vinculado_a_otro(_conn, id_workos, id_usuario):
        return any(
            u["KeyUsuario"] == id_workos and u["UsuarioID"] != id_usuario
            for u in datos.usuarios.values()
        )

    def vincular_por_id(_conn, id_usuario, id_workos):
        fila = datos.usuarios[id_usuario]
        if fila["KeyUsuario"] is not None:
            return False
        fila["KeyUsuario"] = id_workos
        return True

    def actualizar_rol(_conn, id_usuario, rol):
        datos.usuarios[id_usuario]["RolesWorkOS"] = rol

    def contar_activos_vinculados(_conn, ids, excluir_id):
        return sum(
            1
            for u in datos.usuarios.values()
            if u["Estado"] == "Activo"
            and u["KeyUsuario"] in ids
            and u["UsuarioID"] != excluir_id
        )

    def bloqueo_vigente(_conn, id_usuario):
        abiertos = [
            b
            for b in datos.bloqueos
            if b["UsuarioID"] == id_usuario and b["FechaDesbloqueo"] is None
        ]
        return abiertos[-1] if abiertos else None

    def abrir_bloqueo(_conn, id_usuario, *, motivo, observaciones, bloqueado_por):
        datos.bloqueos.append(
            {
                "UsuarioID": id_usuario,
                "MotivoBloqueo": motivo,
                "Observaciones": observaciones,
                "BloqueadoPor": bloqueado_por,
                "FechaBloqueo": FECHA,
                "FechaDesbloqueo": None,
                "DesbloqueadoPor": None,
            }
        )

    def cerrar_bloqueos(_conn, id_usuario, desbloqueado_por):
        for bloqueo in datos.bloqueos:
            if (
                bloqueo["UsuarioID"] == id_usuario
                and bloqueo["FechaDesbloqueo"] is None
            ):
                bloqueo["FechaDesbloqueo"] = FECHA
                bloqueo["DesbloqueadoPor"] = desbloqueado_por

    def cerrar_asignacion(_conn, id_usuario):
        for asignacion in datos.asignaciones:
            if asignacion["IdUsuario"] == id_usuario and asignacion["Estado"] == 1:
                asignacion["Estado"] = 0

    def abrir_asignacion(_conn, id_usuario, id_agencia, *, asignado_por, motivo):
        datos.asignaciones.append(
            {
                "IdUsuario": id_usuario,
                "IdAgencia": id_agencia,
                "Estado": 1,
                "AsignadoPor": asignado_por,
            }
        )

    for nombre, funcion in {
        "listar_usuarios": listar_usuarios,
        "obtener_usuario": obtener_usuario,
        "existe_duplicado": existe_duplicado,
        "insertar_usuario": insertar_usuario,
        "actualizar_usuario": actualizar_usuario,
        "actualizar_rol": actualizar_rol,
        "vinculado_a_otro": vinculado_a_otro,
        "vincular_por_id": vincular_por_id,
        "contar_activos_vinculados": contar_activos_vinculados,
        "bloquear_cambios_administrativos": lambda _conn: True,
        "bloqueo_vigente": bloqueo_vigente,
        "abrir_bloqueo": abrir_bloqueo,
        "cerrar_bloqueos": cerrar_bloqueos,
        "agencia_activa": lambda _conn, id_agencia: id_agencia in datos.agencias,
        "cerrar_asignacion": cerrar_asignacion,
        "abrir_asignacion": abrir_asignacion,
    }.items():
        monkeypatch.setattr(repository, nombre, funcion)

    def asignar(_conn, id_, agencia, activa, actor):
        ids = datos.multi.setdefault(id_, [])
        if activa and agencia not in ids:
            ids.append(agencia)
        if not activa and agencia in ids:
            ids.remove(agencia)

    def historial(_conn, id_, accion, agencia, anterior, nueva, actor, agencia_actor):
        datos.historial_multi.append(
            {
                "id_historial": len(datos.historial_multi) + 1,
                "usuario": id_,
                "id_agencia": agencia,
                "accion": accion,
                "principal_anterior": anterior,
                "principal_nueva": nueva,
                "realizado_por": actor,
                "agencia_actor": agencia_actor,
                "fecha_utc": FECHA,
            }
        )

    def leer_historial(_conn, id_, page, size):
        rows = [dict(r) for r in reversed(datos.historial_multi) if r["usuario"] == id_]
        return rows[(page - 1) * size : page * size], len(rows)

    monkeypatch.setattr(
        agencias_repo,
        "asignaciones",
        lambda _c, id_: (
            sorted(datos.multi[id_])
            if id_ in datos.multi
            else (
                [str(datos.usuarios[id_]["AgenciaID"]).zfill(3)]
                if id_ in datos.usuarios
                and datos.usuarios[id_]["AgenciaID"] is not None
                else []
            )
        ),
    )
    monkeypatch.setattr(
        agencias_repo,
        "agencias",
        lambda _c: [
            {"id_agencia": i, "codigo": i, "estado": "A"}
            for i in sorted(datos.agencias)
        ],
    )
    monkeypatch.setattr(
        agencias_repo,
        "version",
        lambda _c, id_: max(
            (r["id_historial"] for r in datos.historial_multi if r["usuario"] == id_),
            default=0,
        ),
    )
    monkeypatch.setattr(
        agencias_repo,
        "eliminar_contexto",
        lambda _c, sid, id_: datos.contextos.pop((sid, id_), None),
    )
    monkeypatch.setattr(agencias_repo, "guardar_asignacion", asignar)
    monkeypatch.setattr(agencias_repo, "historico", historial)
    monkeypatch.setattr(agencias_repo, "historial", leer_historial)
    monkeypatch.setattr(
        agencias_repo,
        "principal",
        lambda _c, id_, agencia: datos.usuarios[id_].update(
            AgenciaID=int(agencia) if agencia else None
        ),
    )
    monkeypatch.setattr(
        agencias_repo,
        "usuario_por_llave",
        lambda _c, llave: next(
            (dict(u) for u in datos.usuarios.values() if u["KeyUsuario"] == llave), None
        ),
    )
    monkeypatch.setattr(
        agencias_repo, "contexto", lambda _c, sid, id_: datos.contextos.get((sid, id_))
    )

    def trasladar_contextos(_conn, id_, anterior, nueva):
        for (_sid, usuario), contexto in datos.contextos.items():
            if (
                usuario == id_
                and contexto["agencia"] == anterior
                and contexto["vigente"]
            ):
                contexto["agencia"] = nueva

    monkeypatch.setattr(
        agencias_repo, "trasladar_contextos_vigentes", trasladar_contextos
    )
    monkeypatch.setattr(
        agencias_repo,
        "guardar_contexto",
        lambda _c, sid, id_, agencia: datos.contextos.update(
            {(sid, id_): {"agencia": agencia, "vigente": 1}}
        ),
    )
    monkeypatch.setattr(
        caja_repo,
        "jornada_abierta_de_usuario",
        lambda _c, id_, bloquear=False: datos.jornadas.get(id_),
    )
    monkeypatch.setattr(
        multiagencia,
        "get_engine",
        lambda _base: SimpleNamespace(connect=lambda: _Conn(datos)),
    )
    monkeypatch.setattr(
        agencias_repo,
        "inicializar_contexto",
        lambda _c, sid, id_, agencia: datos.contextos.setdefault(
            (sid, id_), {"agencia": agencia, "vigente": 1}
        ),
    )
    return datos


@pytest.fixture()
def workos(monkeypatch) -> _WorkOS:
    falso = _WorkOS()
    cliente = SimpleNamespace(user_management=falso)
    monkeypatch.setattr(service, "get_workos", lambda: cliente)
    return falso


@pytest.fixture()
def conn(base) -> _Conn:
    return _Conn(base)


@pytest.fixture()
def client(monkeypatch, conn, workos) -> Iterator[TestClient]:
    monkeypatch.setenv("WORKOS_ORGANIZATION_ID", ORG)
    monkeypatch.setenv(
        "E104_POLITICA_ROLES",
        '{"niveles":{"ADMIN":1,"ASESOR":1,"CAJERO":1,"SUPERVISOR":1,'
        '"APROBADOR_CREDITO":1,"CONTADOR":1,"AUDITOR":1},'
        '"privilegiados":[],"incompatibles":[]}',
    )
    get_settings.cache_clear()
    simular_sesion(app, ADMIN)
    app.dependency_overrides[seguridad] = lambda: conn
    app.dependency_overrides[cooperativa] = lambda: conn
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


@pytest.mark.parametrize("configuracion", [None, "json inválido", '{"niveles":{}}'])
def test_cambio_de_roles_sin_politica_se_deniega(
    client, monkeypatch, workos, configuracion
):
    if configuracion is None:
        monkeypatch.delenv("E104_POLITICA_ROLES")
    else:
        monkeypatch.setenv("E104_POLITICA_ROLES", configuracion)
    get_settings.cache_clear()
    r = client.put(f"{BASE}/2/roles", json={"roles": ["ASESOR"]})
    assert r.status_code == 503
    assert r.json()["code"] == "POLITICA_ROLES_NO_CONFIGURADA"
    assert not any(operacion.startswith("update_") for operacion, _ in workos.llamadas)


def test_sin_politica_sigue_disponible_la_edicion_de_perfil(
    client, monkeypatch, workos
):
    monkeypatch.delenv("E104_POLITICA_ROLES")
    get_settings.cache_clear()
    assert client.get(f"{BASE}/2").status_code == 200
    assert client.patch(f"{BASE}/2", json={"nombres": "Ana"}).status_code == 200
    r = client.post(BASE, json=NUEVO)
    assert r.status_code == 503
    assert r.json()["code"] == "POLITICA_ROLES_NO_CONFIGURADA"
    assert "send_invitation" not in workos.nombres()


def test_rol_privilegiado_ausente_en_workos_no_se_restaura_directamente(
    client, base, workos, monkeypatch
):
    base.usuarios[2]["RolesWorkOS"] = "CAJERO,AUDITOR"
    politica = service.politica_roles.vigente().model_copy(
        update={"privilegiados": {"AUDITOR"}}
    )
    monkeypatch.setattr(service.politica_roles, "vigente", lambda: politica)
    r = client.put(f"{BASE}/2/roles", json={"roles": ["ASESOR", "AUDITOR"]})

    assert r.status_code == 409
    assert r.json()["code"] == "APROBACION_REQUERIDA"
    assert base.usuarios[2]["RolesWorkOS"] == "CAJERO,AUDITOR"
    assert service._slugs(workos.membresias["user_2"]) == {"org-cajero"}


def test_cambio_privilegiado_configurado_devuelve_solicitud_202(
    client, base, workos, monkeypatch
):
    from app.modules.aprobaciones import router as aprobaciones

    monkeypatch.setenv("E104_PERMISO_APROBAR_ROLES", "qa:aprobar")
    get_settings.cache_clear()
    politica = service.politica_roles.vigente().model_copy(
        update={"privilegiados": {"AUDITOR"}}
    )
    monkeypatch.setattr(service.politica_roles, "vigente", lambda: politica)
    monkeypatch.setattr(
        service.repository, "cambio_roles_en_recuperacion", lambda *_: False
    )
    monkeypatch.setattr(
        aprobaciones,
        "actual",
        lambda _: SimpleNamespace(global_admin=True, id_interno=1),
    )
    llamadas = []

    def solicitar(*args):
        llamadas.append(args)
        return 123

    monkeypatch.setattr(
        aprobaciones, "servicio", lambda: SimpleNamespace(solicitar=solicitar)
    )
    r = client.put(f"{BASE}/2/roles", json={"roles": ["CAJERO", "AUDITOR"]})

    assert r.status_code == 202, r.text
    assert r.json() == {
        "idSolicitud": 123,
        "estado": "Pendiente",
        "requiereAprobacion": True,
    }
    assert llamadas[0][1] == "SEG-USUARIO-ROLES"
    assert base.usuarios[2]["RolesWorkOS"] == "CAJERO"
    assert service._slugs(workos.membresias["user_2"]) == {"org-cajero"}


NUEVO = {
    "username": "jperez",
    "nombres": "Juan",
    "apellidos": "Pérez",
    "email": "Juan.Perez@correo.ec",
    "cedula": "1710034065",
    "idAgencia": "002",
    "rol": "CAJERO",
}


# --- AUT-05 ------------------------------------------------------------------------


def test_listar_usuarios_paginado(client, base):
    r = client.get(BASE, params={"estado": "Activo", "page": 1, "pageSize": 2})

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["total"] == 3 and cuerpo["pageSize"] == 2
    item = next(i for i in cuerpo["items"] if i["idUsuario"] == 3)
    assert item == {
        "idUsuario": 3,
        "username": "usuario3",
        "nombres": "María",
        "apellidos": "López",
        "email": "u3@correo.ec",
        "rol": "ASESOR",
        "roles": ["ASESOR"],
        "estado": "Activo",
        "idAgencia": "001",
        "vinculado": False,
        "fechaCreacion": "2026-11-08T10:00:00",
    }
    assert "intentosFallidos" not in item and "cedula" not in item
    assert base.listados[-1]["orden"] == "fechaCreacion,desc"


def test_listar_pasa_filtros_al_repositorio(client, base):
    r = client.get(
        BASE,
        params={
            "q": " lopez ",
            "idAgencia": "002",
            "rol": "CAJERO",
            "vinculado": "false",
            "sort": "username,asc",
        },
    )

    assert r.status_code == 200
    filtros = base.listados[-1]
    assert (filtros["q"], filtros["agencia_id"], filtros["rol"]) == (
        "lopez",
        2,
        "CAJERO",
    )
    assert (filtros["vinculado"], filtros["orden"]) == (False, "username,asc")


@pytest.mark.parametrize(
    ("parametros", "code"),
    [
        ({"sort": "Cedula,asc"}, "SORT_INVALIDO"),
        ({"pageSize": 101}, "DATOS_INVALIDOS"),
        ({"idAgencia": "1"}, "DATOS_INVALIDOS"),
        ({"otro": "x"}, "PARAMETRO_INVALIDO"),
    ],
)
def test_listar_rechaza_parametros_invalidos(client, parametros, code):
    r = client.get(BASE, params=parametros)

    assert r.status_code == 400
    assert r.json()["code"] == code


# --- AUT-06 ------------------------------------------------------------------------


def test_crear_usuario_invita_a_la_organizacion(
    client, base, workos, eventos_auditados
):
    r = client.post(BASE, json=NUEVO)

    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["idUsuario"] == 4
    assert (cuerpo["email"], cuerpo["rol"], cuerpo["idAgencia"]) == (
        "juan.perez@correo.ec",
        "CAJERO",
        "002",
    )
    assert cuerpo["vinculado"] is False
    assert cuerpo["estadoInvitacion"] == "pending"
    assert base.usuarios[4]["KeyUsuario"] is None
    assert base.usuarios[4]["AgenciaID"] == 2
    assert workos.llamadas == [
        (
            "send_invitation",
            {
                "email": "juan.perez@correo.ec",
                "organization_id": ORG,
                "role_slug": "org-cajero",
                "inviter_user_id": ADMIN.id_usuario,
            },
        )
    ]
    evento = eventos_auditados[-1]
    assert (evento.accion, evento.resultado, evento.id_registro) == (
        "CREAR",
        "Exitoso",
        "4",
    )
    assert "juan" not in evento.descripcion.lower()


@pytest.mark.parametrize("campo", ["username", "email", "cedula"])
def test_crear_usuario_duplicado(client, base, workos, campo):
    existente = {
        "username": "usuario2",
        "email": "u2@correo.ec",
        "cedula": "0926687856",
    }

    r = client.post(BASE, json={**NUEVO, campo: existente[campo]})

    assert r.status_code == 409
    assert r.json()["code"] == "USUARIO_DUPLICADO"
    assert workos.llamadas == []
    assert 4 not in base.usuarios


def test_crear_usuario_agencia_inactiva(client, workos):
    r = client.post(BASE, json={**NUEVO, "idAgencia": "009"})

    assert r.status_code == 422
    assert r.json()["code"] == "AGENCIA_INVALIDA"
    assert workos.llamadas == []


@pytest.mark.parametrize(
    "cambio",
    [
        {"rol": "GERENTE"},
        {"cedula": "17100340"},
        {"cedula": "1710034064"},  # dígito verificador
        {"cedula": "2510034065"},  # provincia
        {"cedula": "1760034065"},  # tercer dígito
        {"email": "sin-arroba"},
        {"password": "Temporal2026*"},
        {"rol": None},
    ],
)
def test_crear_usuario_datos_invalidos(client, workos, cambio):
    r = client.post(BASE, json={**NUEVO, **cambio})

    assert r.status_code == 400
    assert r.json()["code"] == "DATOS_INVALIDOS"
    assert workos.llamadas == []


def test_crear_usuario_workos_caido_revierte(client, base, workos, conn):
    workos.errores["send_invitation"] = _http_error(ServerException)

    r = client.post(BASE, json=NUEVO)

    assert r.status_code == 503
    assert r.json()["code"] == "WORKOS_NO_DISPONIBLE"
    assert 4 not in base.usuarios
    assert conn.rollbacks == 1


def test_crear_usuario_workos_rechaza(client, base, workos):
    workos.errores["send_invitation"] = _http_error(BadRequestException)

    r = client.post(BASE, json=NUEVO)

    assert r.status_code == 422
    assert r.json()["code"] == "WORKOS_RECHAZO"
    # El código de WorkOS va en la respuesta para que el rechazo sea explícito
    assert "(error_de_prueba)" in r.json()["detail"]
    assert 4 not in base.usuarios


def test_crear_usuario_si_falla_el_commit_revoca_la_invitacion(
    client, base, workos, conn
):
    conn.fallar_commit = True

    r = client.post(BASE, json=NUEVO)

    assert r.status_code == 500
    assert 4 not in base.usuarios
    assert workos.nombres() == ["send_invitation", "revoke_invitation"]


def test_crear_usuario_carrera_por_unicidad_es_409(client, base, workos, monkeypatch):
    def insertar(_conn, **_campos):
        raise IntegrityError("INSERT", {}, Exception("2627"))

    monkeypatch.setattr(repository, "insertar_usuario", insertar)

    r = client.post(BASE, json=NUEVO)

    assert r.status_code == 409
    assert r.json()["code"] == "USUARIO_DUPLICADO"


# --- AUT-07 ------------------------------------------------------------------------


def test_detalle_de_usuario_vinculado_no_consulta_invitaciones(client, workos):
    r = client.get(f"{BASE}/2")

    assert r.status_code == 200
    cuerpo = r.json()
    assert (cuerpo["cedula"], cuerpo["vinculado"]) == ("0926687856", True)
    assert cuerpo["estadoInvitacion"] is None and cuerpo["ultimoAcceso"] is None
    assert workos.llamadas == []


def test_detalle_de_usuario_pendiente_trae_estado_de_invitacion(client, workos):
    cuerpo = client.get(f"{BASE}/3").json()

    assert cuerpo["estadoInvitacion"] == "pending"


def test_detalle_sale_aunque_workos_no_responda(client, workos):
    workos.errores["list_invitations"] = _http_error(ServerException)

    r = client.get(f"{BASE}/3")

    assert r.status_code == 200
    assert r.json()["estadoInvitacion"] is None


def test_detalle_inexistente(client):
    r = client.get(f"{BASE}/99")

    assert r.status_code == 404
    assert r.json()["code"] == "USUARIO_NO_ENCONTRADO"


# --- AUT-08 ------------------------------------------------------------------------


def test_bloquear_usuario_vinculado(client, base, workos):
    r = client.patch(
        f"{BASE}/2",
        json={"estado": "Bloqueado", "motivo": "Fraude", "observaciones": "Caso 12"},
    )

    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] == "Bloqueado"
    assert cuerpo["bloqueo"]["motivo"] == "Fraude"
    assert base.bloqueos[0]["BloqueadoPor"] == ID_AUDITORIA
    assert workos.membresias["user_2"].status == "inactive"
    # Corta la sesión viva sin esperar las 8 h
    assert ("revoke_session", "session_a") in workos.llamadas
    assert ("revoke_session", "session_b") not in workos.llamadas


def test_desactivar_usuario_vinculado_cierra_sus_sesiones(client, workos):
    auth._revocadas.clear()

    r = client.patch(f"{BASE}/2", json={"estado": "Inactivo"})

    assert r.status_code == 200
    assert r.json()["estado"] == "Inactivo"
    assert workos.membresias["user_2"].status == "inactive"
    # Sus sesiones se cierran en WorkOS y se rechazan al instante (401 SESION_REVOCADA)
    assert ("revoke_session", "session_a") in workos.llamadas
    assert ("revoke_session", "session_b") not in workos.llamadas
    assert auth.motivo_revocacion("session_a") == "SESION_REVOCADA"


def test_bloquear_exige_motivo(client, workos):
    r = client.patch(f"{BASE}/2", json={"estado": "Bloqueado"})

    assert r.status_code == 400
    assert workos.llamadas == []


def test_desbloquear_cierra_el_bloqueo_y_reactiva(client, base, workos):
    client.patch(f"{BASE}/2", json={"estado": "Bloqueado", "motivo": "Fraude"})

    r = client.patch(f"{BASE}/2", json={"estado": "Activo"})

    assert r.status_code == 200
    assert r.json()["bloqueo"] is None
    assert base.bloqueos[0]["DesbloqueadoPor"] == ID_AUDITORIA
    assert workos.membresias["user_2"].status == "active"


def test_no_puede_bloquearse_a_si_mismo(client, workos):
    r = client.patch(f"{BASE}/{ID_AUDITORIA}", json={"estado": "Inactivo"})

    assert r.status_code == 403
    assert r.json()["code"] == "AUTOGESTION_NO_PERMITIDA"


def test_no_puede_cambiar_su_propia_agencia(client, workos):
    r = client.patch(f"{BASE}/{ID_AUDITORIA}", json={"idAgencia": "002"})

    assert r.status_code == 403
    assert r.json()["code"] == "AUTOGESTION_NO_PERMITIDA"
    assert workos.llamadas == []


def test_no_puede_cambiar_su_propio_rol(client, workos, eventos_auditados):
    r = client.put(f"{BASE}/{ID_AUDITORIA}/roles", json={"rol": "CAJERO"})

    assert r.status_code == 403
    assert r.json()["code"] == "AUTOGESTION_NO_PERMITIDA"
    assert workos.llamadas == []
    evento = next(e for e in eventos_auditados if e.accion == "SEG_AUTOGESTION_INTENTO")
    assert evento.resultado == "Fallido"
    assert "AUTOGESTION_NO_PERMITIDA" in evento.descripcion


@pytest.mark.parametrize(
    ("metodo", "sufijo", "cambios"),
    [
        ("PATCH", "", {"estado": "Activo"}),
        ("PATCH", "", {"idAgencia": "001"}),
        ("PUT", "/agencia", {"idAgencia": "001"}),
    ],
)
def test_autogestion_denegada_aun_si_repite_el_valor_actual(
    client, base, workos, eventos_auditados, metodo, sufijo, cambios
):
    antes = copy.deepcopy(base.estado())
    r = client.request(metodo, f"{BASE}/{ID_AUDITORIA}{sufijo}", json=cambios)

    assert r.status_code == 403
    assert r.json()["code"] == "AUTOGESTION_NO_PERMITIDA"
    assert base.estado() == antes
    assert workos.llamadas == []
    evento = next(e for e in eventos_auditados if e.accion == "SEG_AUTOGESTION_INTENTO")
    assert evento.resultado == "Fallido"
    assert "AUTOGESTION_NO_PERMITIDA" in evento.descripcion


def test_desactivar_pendiente_revoca_la_invitacion(client, workos):
    r = client.patch(f"{BASE}/3", json={"estado": "Inactivo"})

    assert r.status_code == 200
    assert ("revoke_invitation", "inv_3") in workos.llamadas
    assert "send_invitation" not in workos.nombres()


@pytest.fixture
def diario_e104(monkeypatch, client, conn):
    from unittest.mock import MagicMock

    from app.modules.auth import recuperacion_correo

    monkeypatch.setenv("E104_RECUPERAR_CORREO", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(conn, "engine", object(), raising=False)
    monkeypatch.setattr(
        service.repository, "sincronizacion_pendiente", lambda *_: False
    )
    diario = SimpleNamespace(
        registrar=MagicMock(return_value=17),
        completar=MagicMock(),
        confirmar=MagicMock(),
        confirmar_roles=MagicMock(),
    )
    for nombre, funcion in vars(diario).items():
        monkeypatch.setattr(recuperacion_correo, nombre, funcion)
    return diario


def test_diario_correo_exige_peticion_separada_y_confirma_antes_de_completar(
    client, diario_e104, conn, base
):
    rechazo = client.patch(
        f"{BASE}/2", json={"email": "nuevo@example.test", "nombres": "Ana"}
    )
    assert rechazo.status_code == 422
    assert rechazo.json()["code"] == "CORREO_REQUIERE_CAMBIO_SEPARADO"
    diario_e104.registrar.assert_not_called()

    respuesta = client.patch(f"{BASE}/2", json={"email": "nuevo@example.test"})
    assert respuesta.status_code == 200, respuesta.text
    diario_e104.registrar.assert_called_once_with(conn.engine, 2, "user_2")
    diario_e104.confirmar.assert_called_once_with("user_2", "nuevo@example.test")
    diario_e104.completar.assert_called_once_with(conn, 17)
    assert base.usuarios[2]["Email"] == "nuevo@example.test"


def test_diario_roles_confirma_membresia_antes_de_completar(
    client, diario_e104, conn, workos
):
    respuesta = client.put(f"{BASE}/2/roles", json={"roles": ["CAJERO", "AUDITOR"]})
    assert respuesta.status_code == 200, respuesta.text
    diario_e104.registrar.assert_called_once_with(conn.engine, 2, "user_2", "Roles")
    diario_e104.confirmar_roles.assert_called_once_with("user_2", ("CAJERO", "AUDITOR"))
    diario_e104.completar.assert_called_once_with(conn, 17)
    assert service._slugs(workos.membresias["user_2"]) == {"org-cajero", "org-auditor"}


@pytest.mark.parametrize("cambiar_correo", [True, False])
def test_diario_cubre_reemplazo_de_invitacion(
    client, diario_e104, conn, cambiar_correo
):
    if cambiar_correo:
        respuesta = client.patch(f"{BASE}/3", json={"email": "nuevo@example.test"})
        diario_e104.registrar.assert_called_once_with(
            conn.engine, 3, "inv_3", "Invitar", correo_alterno="nuevo@example.test"
        )
    else:
        respuesta = client.put(f"{BASE}/3/roles", json={"roles": ["AUDITOR"]})
        diario_e104.registrar.assert_called_once_with(
            conn.engine, 3, "inv_3", "Invitar"
        )
    assert respuesta.status_code == 200, respuesta.text
    diario_e104.completar.assert_called_once_with(conn, 17)


def test_cambiar_email_de_vinculado_actualiza_workos(client, base, workos):
    r = client.patch(f"{BASE}/2", json={"email": "Nuevo@correo.ec", "nombres": "Ana"})

    assert r.status_code == 200
    assert base.usuarios[2]["Email"] == "nuevo@correo.ec"
    assert workos.llamadas == [
        (
            "update_user",
            {
                "user_id": "user_2",
                "email": "nuevo@correo.ec",
                "first_name": "Ana",
                "last_name": None,
            },
        )
    ]


def test_cambiar_email_de_pendiente_reenvia_la_invitacion(client, workos):
    r = client.patch(f"{BASE}/3", json={"email": "nuevo@correo.ec"})

    assert r.status_code == 200
    assert ("revoke_invitation", "inv_3") in workos.llamadas
    envio = dict(workos.llamadas)["send_invitation"]
    assert (envio["email"], envio["role_slug"]) == ("nuevo@correo.ec", "org-asesor")


def test_error_de_commit_compensa_el_correo_del_usuario_vinculado(
    client, base, workos, conn
):
    anterior = base.usuarios[2]["Email"]
    conn.fallar_commit = True

    r = client.patch(f"{BASE}/2", json={"email": "nuevo@correo.ec"})

    assert r.status_code == 500
    assert base.usuarios[2]["Email"] == anterior
    cambios = [
        datos for operacion, datos in workos.llamadas if operacion == "update_user"
    ]
    assert [datos["email"] for datos in cambios] == ["nuevo@correo.ec", anterior]


def test_actualizacion_ambigua_de_correo_intenta_compensar(
    client, base, workos, monkeypatch
):
    anterior = base.usuarios[2]["Email"]
    remoto = anterior

    def actualizar(*, email, **_):
        nonlocal remoto
        remoto = email
        if email != anterior:
            raise _http_error(ServerException)

    monkeypatch.setattr(workos, "update_user", actualizar)
    r = client.patch(f"{BASE}/2", json={"email": "nuevo@correo.ec"})

    assert r.status_code == 503
    assert base.usuarios[2]["Email"] == remoto == anterior


def test_error_de_commit_restaura_invitacion_al_correo_anterior(
    client, base, workos, conn
):
    conn.fallar_commit = True

    r = client.patch(f"{BASE}/3", json={"email": "nuevo@correo.ec"})

    assert r.status_code == 500
    assert base.usuarios[3]["Email"] == "u3@correo.ec"
    assert [i.email for i in workos.invitaciones if i.state == "pending"] == [
        "u3@correo.ec"
    ]


def test_email_duplicado_al_editar(client, workos):
    r = client.patch(f"{BASE}/2", json={"email": "u3@correo.ec"})

    assert r.status_code == 409
    assert r.json()["code"] == "USUARIO_DUPLICADO"


@pytest.mark.parametrize(("metodo", "sufijo"), [("PATCH", ""), ("PUT", "/agencia")])
def test_cambiar_agencia_de_cajero_mueve_su_asignacion(client, base, metodo, sufijo):
    r = client.request(metodo, f"{BASE}/2{sufijo}", json={"idAgencia": "002"})

    assert r.status_code == 200
    assert r.json()["idAgencia"] == "002"
    assert [(a["IdAgencia"], a["Estado"]) for a in base.asignaciones] == [
        ("001", 0),
        ("002", 1),
    ]
    assert base.asignaciones[-1]["AsignadoPor"] == ID_AUDITORIA


def test_cambiar_agencia_inactiva(client, base):
    r = client.patch(f"{BASE}/2", json={"idAgencia": "009"})

    assert r.status_code == 422
    assert base.usuarios[2]["AgenciaID"] == 1


def test_si_workos_falla_al_editar_se_revierte_todo(client, base, workos):
    workos.errores["list_sessions"] = _http_error(ServerException)

    r = client.patch(f"{BASE}/2", json={"estado": "Bloqueado", "motivo": "Fraude"})

    assert r.status_code == 503
    assert base.usuarios[2]["Estado"] == "Activo"
    assert base.bloqueos == []
    # La membresía que ya se había desactivado se reactiva
    assert workos.nombres()[-1] == "reactivate"
    assert workos.membresias["user_2"].status == "active"


def test_editar_sin_cambios_es_400(client):
    r = client.patch(f"{BASE}/2", json={})

    assert r.status_code == 400


def test_no_se_edita_username_ni_cedula(client):
    r = client.patch(f"{BASE}/2", json={"username": "otro", "cedula": "1710034065"})

    assert r.status_code == 400


# --- AUT-09 y último ADMIN -----------------------------------------------------------


def test_cambiar_rol_de_vinculado(client, base, workos):
    auth._revocadas.clear()

    r = client.put(f"{BASE}/2/roles", json={"rol": "SUPERVISOR"})

    assert r.status_code == 200
    assert r.json()["rol"] == "SUPERVISOR"
    assert base.usuarios[2]["RolesWorkOS"] == "SUPERVISOR"
    assert ("update_membership", ("om_2", "org-supervisor")) in workos.llamadas
    # Dejó de ser cajero: su asignación vigente se cierra
    assert base.asignaciones[0]["Estado"] == 0
    # Sus sesiones se cierran y se rechazan al instante: entra de nuevo con el rol nuevo
    assert ("list_sessions", "user_2") in workos.llamadas
    assert ("revoke_session", "session_a") in workos.llamadas
    assert ("revoke_session", "session_b") not in workos.llamadas
    assert auth.motivo_revocacion("session_a") == "SESION_REVOCADA"


def test_cambiar_rol_sin_poder_cerrar_sesiones_se_revierte(client, base, workos):
    workos.errores["list_sessions"] = _http_error(ServerException)

    r = client.put(f"{BASE}/2/roles", json={"rol": "SUPERVISOR"})

    assert r.status_code == 503
    assert base.usuarios[2]["RolesWorkOS"] == "CAJERO"
    # El rol aplicado en WorkOS se deshace
    assert ("update_membership", ("om_2", "org-cajero")) in workos.llamadas


def test_fallo_de_sesion_restaura_todos_los_roles_del_proveedor(client, base, workos):
    workos.membresias["user_2"].roles = [
        {"slug": "org-cajero"},
        {"slug": "org-auditor"},
    ]
    workos.errores["list_sessions"] = _http_error(ServerException)

    r = client.put(f"{BASE}/2/roles", json={"rol": "SUPERVISOR"})

    assert r.status_code == 503
    assert base.usuarios[2]["RolesWorkOS"] == "CAJERO"
    assert service._slugs(workos.membresias["user_2"]) == {"org-cajero", "org-auditor"}


def test_fallo_de_sesion_revierte_membresia_nueva(client, workos):
    del workos.membresias["user_2"]
    workos.errores["list_sessions"] = _http_error(ServerException)

    r = client.put(f"{BASE}/2/roles", json={"rol": "SUPERVISOR"})

    assert r.status_code == 503
    assert ("delete_membership", "om_nueva") in workos.llamadas


def test_edicion_de_un_rol_preserva_asignaciones_multiples(client, base, workos):
    base.usuarios[2]["RolesWorkOS"] = "CAJERO,AUDITOR"

    r = client.put(f"{BASE}/2/roles", json={"rol": "SUPERVISOR"})

    assert r.status_code == 409
    assert r.json()["code"] == "USUARIO_CON_MULTIPLES_ROLES"
    assert base.usuarios[2]["RolesWorkOS"] == "CAJERO,AUDITOR"
    assert workos.llamadas == []


def test_cambiar_rol_de_pendiente_reemplaza_la_invitacion(client, workos):
    r = client.put(f"{BASE}/3/roles", json={"rol": "CONTADOR"})

    assert r.status_code == 200
    assert ("revoke_invitation", "inv_3") in workos.llamadas
    assert dict(workos.llamadas)["send_invitation"]["role_slug"] == "org-contador"


def test_mismo_rol_solo_consulta_workos(client, workos):
    r = client.put(f"{BASE}/2/roles", json={"rol": "CAJERO"})

    assert r.status_code == 200
    assert workos.nombres() == ["list_organization_memberships"]


def test_mismos_roles_locales_detectan_deriva_en_workos(client, base, workos):
    base.usuarios[2]["RolesWorkOS"] = "CAJERO,AUDITOR"

    r = client.put(f"{BASE}/2/roles", json={"roles": ["AUDITOR", "CAJERO"]})

    assert r.status_code == 409
    assert r.json()["code"] == "ROLES_DESINCRONIZADOS"
    assert workos.nombres() == ["list_organization_memberships"]
    assert base.usuarios[2]["RolesWorkOS"] == "CAJERO,AUDITOR"


def test_rol_invalido_o_varios_roles(client):
    assert client.put(f"{BASE}/2/roles", json={"rol": "GERENTE"}).status_code == 400
    assert client.put(f"{BASE}/2/roles", json={"roles": []}).status_code == 400
    assert (
        client.put(
            f"{BASE}/2/roles", json={"roles": ["CONTADOR", "CONTADOR"]}
        ).status_code
        == 400
    )
    assert (
        client.put(
            f"{BASE}/2/roles", json={"rol": "ADMIN", "roles": ["AUDITOR"]}
        ).status_code
        == 400
    )


def test_usuario_vinculado_puede_tener_varios_roles(client, base, workos):
    r = client.put(f"{BASE}/2/roles", json={"roles": ["CAJERO", "AUDITOR"]})

    assert r.status_code == 200
    assert set(r.json()["roles"]) == {"CAJERO", "AUDITOR"}
    assert set(base.usuarios[2]["RolesWorkOS"].split(",")) == {"CAJERO", "AUDITOR"}
    assert service._slugs(workos.membresias["user_2"]) == {"org-cajero", "org-auditor"}
    assert base.asignaciones[0]["Estado"] == 1


def test_multirrol_pendiente_exige_vinculo(client, base, workos):
    r = client.put(f"{BASE}/3/roles", json={"roles": ["ASESOR", "AUDITOR"]})

    assert r.status_code == 409
    assert r.json()["code"] == "USUARIO_PENDIENTE_DE_VINCULO"
    assert base.usuarios[3]["RolesWorkOS"] == "ASESOR"
    assert "revoke_invitation" not in workos.nombres()


@pytest.fixture
def otro_editor(client, monkeypatch):
    monkeypatch.setitem(
        app.dependency_overrides,
        auth.usuario_actual,
        lambda: replace(ADMIN, id_usuario="user_2", id_interno=2),
    )
    monkeypatch.setitem(app.dependency_overrides, auth.id_usuario_auditoria, lambda: 2)
    return client


def test_ultimo_admin_no_pierde_el_rol(otro_editor, base, workos):
    r = otro_editor.put(f"{BASE}/1/roles", json={"rol": "AUDITOR"})

    assert r.status_code == 409
    assert r.json()["code"] == "ULTIMO_ADMIN"
    assert base.usuarios[1]["RolesWorkOS"] == "ADMIN"


def test_ultimo_admin_protegido_si_sql_tiene_roles_desactualizados(
    otro_editor, base, workos
):
    base.usuarios[1]["RolesWorkOS"] = "CONTADOR"

    r = otro_editor.put(f"{BASE}/1/roles", json={"roles": ["CONTADOR", "AUDITOR"]})

    assert r.status_code == 409
    assert r.json()["code"] == "ULTIMO_ADMIN"
    assert service._slugs(workos.membresias["user_1"]) == {"org-admin"}
    assert "update_membership" not in workos.nombres()


def test_cambio_concurrente_de_acceso_se_rechaza_antes_de_workos(
    client, base, workos, monkeypatch
):
    monkeypatch.setattr(repository, "bloquear_cambios_administrativos", lambda _: False)

    r = client.patch(f"{BASE}/2", json={"estado": "Inactivo"})

    assert r.status_code == 409
    assert r.json()["code"] == "USUARIOS_OCUPADOS"
    assert base.usuarios[2]["Estado"] == "Activo"
    assert workos.llamadas == []


def test_admin_con_otro_admin_real_si_puede_cambiar(otro_editor, base, workos):
    base.usuarios[5] = _fila(5, RolesWorkOS="ADMIN")
    workos.membresias["user_5"] = SimpleNamespace(
        id="om_5", user_id="user_5", status="active", role={"slug": "org-admin"}
    )
    workos.membresias["user_5"].roles = None

    r = otro_editor.put(f"{BASE}/1/roles", json={"rol": "AUDITOR"})

    assert r.status_code == 200


def test_admin_sin_membresia_activa_no_cuenta(otro_editor, base, workos):
    # Fila con rol ADMIN pero sin membresía activa en WorkOS: no es un ADMIN real
    base.usuarios[5] = _fila(5, RolesWorkOS="ADMIN")

    r = otro_editor.put(f"{BASE}/1/roles", json={"rol": "AUDITOR"})

    assert r.status_code == 409


def test_ultimo_admin_no_se_desactiva(client, base, workos):
    # El único ADMIN real es el 5 (la membresía del 1 ya no tiene org-admin)
    workos.membresias["user_1"].role = {"slug": "org-auditor"}
    base.usuarios[5] = _fila(5, RolesWorkOS="ADMIN")
    workos.membresias["user_5"] = SimpleNamespace(
        id="om_5", user_id="user_5", status="active", role={"slug": "org-admin"}
    )
    workos.membresias["user_5"].roles = None

    r = client.patch(f"{BASE}/5", json={"estado": "Bloqueado", "motivo": "Prueba"})

    assert r.status_code == 409
    assert r.json()["code"] == "ULTIMO_ADMIN"
    assert workos.membresias["user_5"].status == "active"


# --- Sin KeyUsuario: aceptó la invitación pero el login no lo vinculó ---------------


def _miembro_sin_vinculo(
    base: _Base, workos: _WorkOS, *, verificado: bool = True, rol: str = "org-admin"
) -> None:
    """Fila 6 sin KeyUsuario; en WorkOS user_6 ya es miembro de EnquoCoop."""
    base.usuarios[6] = _fila(6, KeyUsuario=None, RolesWorkOS="ADMIN")
    workos.usuarios["u6@correo.ec"] = SimpleNamespace(
        id="user_6", email_verified=verificado
    )
    workos.membresias["user_6"] = SimpleNamespace(
        id="om_6", user_id="user_6", status="active", role={"slug": rol}, roles=None
    )


def test_cambiar_rol_de_miembro_sin_vinculo_actualiza_la_membresia(
    client, base, workos
):
    _miembro_sin_vinculo(base, workos)

    r = client.put(f"{BASE}/6/roles", json={"rol": "ASESOR"})

    assert r.status_code == 200
    assert ("update_membership", ("om_6", "org-asesor")) in workos.llamadas
    assert "send_invitation" not in workos.nombres()
    # Email verificado por WorkOS: queda vinculado sin esperar otro login
    assert base.usuarios[6]["KeyUsuario"] == "user_6"
    assert r.json()["vinculado"] is True


def test_miembro_con_email_sin_verificar_no_se_vincula(client, base, workos):
    _miembro_sin_vinculo(base, workos, verificado=False)

    r = client.put(f"{BASE}/6/roles", json={"rol": "ASESOR"})

    assert r.status_code == 200
    assert ("update_membership", ("om_6", "org-asesor")) in workos.llamadas
    assert base.usuarios[6]["KeyUsuario"] is None


def test_usuario_de_workos_sin_membresia_es_409_sin_reinvitar(client, base, workos):
    base.usuarios[6] = _fila(6, KeyUsuario=None, RolesWorkOS="ASESOR")
    workos.usuarios["u6@correo.ec"] = SimpleNamespace(id="user_6", email_verified=True)

    r = client.put(f"{BASE}/6/roles", json={"rol": "CONTADOR"})

    assert r.status_code == 409
    assert r.json()["code"] == "USUARIO_WORKOS_SIN_MEMBRESIA"
    assert "send_invitation" not in workos.nombres()
    assert "revoke_invitation" not in workos.nombres()
    assert base.usuarios[6]["RolesWorkOS"] == "ASESOR"


def test_usuario_de_workos_vinculado_a_otra_fila_es_409(client, base, workos):
    # user_2 ya es el KeyUsuario de la fila 2
    base.usuarios[6] = _fila(6, KeyUsuario=None, RolesWorkOS="ASESOR")
    workos.usuarios["u6@correo.ec"] = SimpleNamespace(id="user_2", email_verified=True)

    r = client.put(f"{BASE}/6/roles", json={"rol": "CONTADOR"})

    assert r.status_code == 409
    assert r.json()["code"] == "VINCULO_EN_CONFLICTO"
    assert "update_membership" not in workos.nombres()


def test_bloquear_miembro_sin_vinculo_desactiva_y_corta_sesiones(client, base, workos):
    _miembro_sin_vinculo(base, workos, rol="org-cajero")
    base.usuarios[6]["RolesWorkOS"] = "CAJERO"

    r = client.patch(f"{BASE}/6", json={"estado": "Bloqueado", "motivo": "Fraude"})

    assert r.status_code == 200
    assert workos.membresias["user_6"].status == "inactive"
    assert ("revoke_session", "session_a") in workos.llamadas
    assert "revoke_invitation" not in workos.nombres()
    assert "send_invitation" not in workos.nombres()


def test_cambiar_email_de_miembro_sin_vinculo_actualiza_workos(client, base, workos):
    _miembro_sin_vinculo(base, workos, rol="org-cajero")

    r = client.patch(f"{BASE}/6", json={"email": "nuevo6@correo.ec"})

    assert r.status_code == 200
    assert dict(workos.llamadas)["update_user"]["user_id"] == "user_6"
    assert "send_invitation" not in workos.nombres()


def test_editar_sin_vinculo_si_falla_workos_revierte_el_vinculo(client, base, workos):
    _miembro_sin_vinculo(base, workos, rol="org-cajero")
    workos.errores["update_user"] = _http_error(ServerException)

    r = client.patch(f"{BASE}/6", json={"nombres": "Ana"})

    assert r.status_code == 503
    assert base.usuarios[6]["KeyUsuario"] is None
    assert base.usuarios[6]["Nombres"] == "María"


# --- AUT-01: vínculo del primer login ----------------------------------------------


class _Motor:
    def __init__(self) -> None:
        self.conn = object()

    @contextmanager
    def begin(self) -> Iterator[object]:
        yield self.conn


@pytest.mark.parametrize(("verificado", "vincula"), [(True, True), (False, False)])
def test_vinculo_solo_con_email_verificado(
    monkeypatch, eventos_auditados, verificado, vincula
):
    llamadas: list[str] = []
    monkeypatch.setattr(service, "get_engine", lambda _base: _Motor())

    def vincular(_conn, id_workos, email):
        llamadas.append(f"vincular {id_workos} {email}")
        return True

    monkeypatch.setattr(repository, "vincular", vincular)
    monkeypatch.setattr(
        repository,
        "registrar_acceso",
        lambda _conn, id_workos: llamadas.append(f"acceso {id_workos}"),
    )

    service._vincular("user_7", "Ana@Correo.ec", verificado, "10.0.0.1")

    esperado = ["vincular user_7 ana@correo.ec"] if vincula else []
    assert llamadas == [*esperado, "acceso user_7"]
    assert [e.accion for e in eventos_auditados] == (["VINCULAR"] if vincula else [])


def test_vinculo_no_rompe_el_login_si_la_base_falla(monkeypatch, eventos_auditados):
    def caida(_base):
        raise OperationalError("UPDATE", {}, Exception("sin red"))

    monkeypatch.setattr(service, "get_engine", caida)

    service._vincular("user_7", "ana@correo.ec", True, None)

    assert eventos_auditados == []


# --- Repositorio -------------------------------------------------------------------


def test_busqueda_escapa_comodines_de_like():
    assert repository._patron("50%_[a\\") == r"%50\%\_\[a\\%"
    assert repository._patron("") is None and repository._patron(None) is None


def test_listar_usa_parametros_y_no_concatena(monkeypatch):
    ejecutadas: list[tuple[str, dict[str, Any]]] = []

    class _Resultado:
        def scalar_one(self) -> int:
            return 7

        def mappings(self) -> "_Resultado":
            return self

        def all(self) -> list[Any]:
            return []

    class _ConnSql:
        def execute(self, sql: Any, parametros: dict[str, Any]) -> _Resultado:
            ejecutadas.append((str(sql), parametros))
            return _Resultado()

    filas, total = repository.listar_usuarios(
        _ConnSql(),  # type: ignore[arg-type]
        q="o'brien",
        estado=None,
        agencia_id=2,
        rol="CAJERO",
        vinculado=True,
        orden="email,desc",
        page=3,
        page_size=10,
    )

    assert (filas, total) == ([], 7)
    (sql_total, _), (sql_items, parametros) = ejecutadas
    assert "o'brien" not in sql_total + sql_items
    assert parametros["q"] == "%o'brien%"
    assert (parametros["vinculado"], parametros["offset"]) == (1, 20)
    assert parametros["orden"] == "email,desc"
