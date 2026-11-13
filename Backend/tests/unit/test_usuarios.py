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
from app.main import app
from app.modules.auth import repository, service
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

    def estado(self) -> tuple[Any, ...]:
        return (self.usuarios, self.bloqueos, self.asignaciones)

    def restaurar(self, estado: tuple[Any, ...]) -> None:
        self.usuarios, self.bloqueos, self.asignaciones = estado


class _Conn:
    def __init__(self, base: _Base) -> None:
        self.base = base
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
        self, *, organization_membership_id: str, role_slug: str
    ) -> None:
        self._registrar("update_membership", (organization_membership_id, role_slug))
        self._membresia(organization_membership_id).role = {"slug": role_slug}

    def create_organization_membership(self, **kwargs: Any) -> None:
        self._registrar("create_membership", kwargs)

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
        "bloqueo_vigente": bloqueo_vigente,
        "abrir_bloqueo": abrir_bloqueo,
        "cerrar_bloqueos": cerrar_bloqueos,
        "agencia_activa": lambda _conn, id_agencia: id_agencia in datos.agencias,
        "cerrar_asignacion": cerrar_asignacion,
        "abrir_asignacion": abrir_asignacion,
    }.items():
        monkeypatch.setattr(repository, nombre, funcion)
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
    get_settings.cache_clear()
    simular_sesion(app, ADMIN)
    app.dependency_overrides[seguridad] = lambda: conn
    app.dependency_overrides[cooperativa] = lambda: conn
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()
    get_settings.cache_clear()


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

    assert r.status_code == 409
    assert r.json()["code"] == "OPERACION_SOBRE_SI_MISMO"


def test_desactivar_pendiente_revoca_la_invitacion(client, workos):
    r = client.patch(f"{BASE}/3", json={"estado": "Inactivo"})

    assert r.status_code == 200
    assert ("revoke_invitation", "inv_3") in workos.llamadas
    assert "send_invitation" not in workos.nombres()


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


def test_email_duplicado_al_editar(client, workos):
    r = client.patch(f"{BASE}/2", json={"email": "u3@correo.ec"})

    assert r.status_code == 409
    assert r.json()["code"] == "USUARIO_DUPLICADO"


def test_cambiar_agencia_de_cajero_mueve_su_asignacion(client, base):
    r = client.patch(f"{BASE}/2", json={"idAgencia": "002"})

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
    r = client.put(f"{BASE}/2/roles", json={"rol": "SUPERVISOR"})

    assert r.status_code == 200
    assert r.json()["rol"] == "SUPERVISOR"
    assert base.usuarios[2]["RolesWorkOS"] == "SUPERVISOR"
    assert ("update_membership", ("om_2", "org-supervisor")) in workos.llamadas
    # Dejó de ser cajero: su asignación vigente se cierra
    assert base.asignaciones[0]["Estado"] == 0


def test_cambiar_rol_de_pendiente_reemplaza_la_invitacion(client, workos):
    r = client.put(f"{BASE}/3/roles", json={"rol": "CONTADOR"})

    assert r.status_code == 200
    assert ("revoke_invitation", "inv_3") in workos.llamadas
    assert dict(workos.llamadas)["send_invitation"]["role_slug"] == "org-contador"


def test_mismo_rol_no_llama_a_workos(client, workos):
    r = client.put(f"{BASE}/2/roles", json={"rol": "CAJERO"})

    assert r.status_code == 200
    assert workos.llamadas == []


def test_rol_invalido_o_varios_roles(client):
    assert client.put(f"{BASE}/2/roles", json={"rol": "GERENTE"}).status_code == 400
    assert client.put(f"{BASE}/2/roles", json={"roles": ["ADMIN"]}).status_code == 400


def test_ultimo_admin_no_pierde_el_rol(client, base, workos):
    r = client.put(f"{BASE}/1/roles", json={"rol": "AUDITOR"})

    assert r.status_code == 409
    assert r.json()["code"] == "ULTIMO_ADMIN"
    assert base.usuarios[1]["RolesWorkOS"] == "ADMIN"


def test_admin_con_otro_admin_real_si_puede_cambiar(client, base, workos):
    base.usuarios[5] = _fila(5, RolesWorkOS="ADMIN")
    workos.membresias["user_5"] = SimpleNamespace(
        id="om_5", user_id="user_5", status="active", role={"slug": "org-admin"}
    )
    workos.membresias["user_5"].roles = None

    r = client.put(f"{BASE}/1/roles", json={"rol": "AUDITOR"})

    assert r.status_code == 200


def test_admin_sin_membresia_activa_no_cuenta(client, base, workos):
    # Fila con rol ADMIN pero sin membresía activa en WorkOS: no es un ADMIN real
    base.usuarios[5] = _fila(5, RolesWorkOS="ADMIN")

    r = client.put(f"{BASE}/1/roles", json={"rol": "AUDITOR"})

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
