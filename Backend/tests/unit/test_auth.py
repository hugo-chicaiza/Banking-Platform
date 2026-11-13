"""AUT-01..04 y core/security.py (patrón BFF) sin red: WorkOS simulado."""

import base64
import hashlib
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError
from workos.exceptions import AuthenticationException
from workos.types.user_management import User
from workos.types.user_management.session import (
    AuthenticateWithSessionCookieErrorResponse,
    AuthenticateWithSessionCookieFailureReason,
    AuthenticateWithSessionCookieSuccessResponse,
    RefreshWithSessionCookieErrorResponse,
    RefreshWithSessionCookieSuccessResponse,
)

from app.core.api.errors import ProblemDetailsRoute
from app.core.config.settings import get_settings
from app.core.security import auth as security
from app.core.security.auth import COOKIE_SESION, require_roles
from app.integrations import workos_client
from app.main import app
from app.modules.auth import service
from app.modules.auth.router import COOKIE_STATE

BASE = "/api/v1/auth"
FRONT = "http://localhost:5173"
CALLBACK = f"{FRONT}/api/v1/auth/callback"
AUTHORIZE = "https://api.workos.com/user_management/authorize"


def _usuario(**cambios: Any) -> User:
    datos: dict[str, Any] = {
        "object": "user",
        "id": "user_1",
        "email": "maria.lopez@correo.ec",
        "first_name": "María",
        "last_name": "López",
        "email_verified": True,
        "created_at": "2026-11-01T00:00:00Z",
        "updated_at": "2026-11-01T00:00:00Z",
        "metadata": {"idAgencia": "001"},
    }
    return User(**{**datos, **cambios})


class _Sesion:
    """Imita workos.session.Session sobre el registro de sesiones del falso."""

    def __init__(self, workos: "_UserManagement", sellada: str) -> None:
        self._workos = workos
        self._sellada = sellada

    def _claims(self) -> dict[str, Any]:
        return {
            "session_id": "session_1",
            "organization_id": "org_1",
            "role": self._workos.roles[0] if self._workos.roles else None,
            "roles": self._workos.roles,
            "permissions": ["cuentas:crear"],
            # Como en WorkOS real: la copia del usuario en la cookie no trae metadatos
            "user": self._workos.usuario.model_copy(update={"metadata": {}}),
        }

    def authenticate(self) -> Any:
        if self._workos.error_jwks:
            raise self._workos.error_jwks
        estado = self._workos.sesiones.get(self._sellada)
        if estado == "vigente":
            return AuthenticateWithSessionCookieSuccessResponse(
                authenticated=True, **self._claims()
            )
        motivo = (
            AuthenticateWithSessionCookieFailureReason.INVALID_JWT
            # "usada": la cookie se descifra igual y su access token sigue vencido;
            # lo que ya no sirve es su refresh token
            if estado in ("vencida", "usada")
            else AuthenticateWithSessionCookieFailureReason.INVALID_SESSION_COOKIE
        )
        return AuthenticateWithSessionCookieErrorResponse(
            authenticated=False, reason=motivo
        )

    def refresh(self) -> Any:
        self._workos.renovaciones += 1
        if self._workos.sesiones.get(self._sellada) not in ("vigente", "vencida"):
            return RefreshWithSessionCookieErrorResponse(
                authenticated=False, reason="invalid_grant"
            )
        # El refresh token es de un solo uso
        self._workos.sesiones[self._sellada] = "usada"
        nueva = f"sellada-renovada-{self._workos.renovaciones}"
        self._workos.sesiones[nueva] = "vigente"
        return RefreshWithSessionCookieSuccessResponse(
            authenticated=True, sealed_session=nueva, **self._claims()
        )


class _UserManagement:
    """Imita los métodos de workos.user_management que usa el backend."""

    def __init__(self) -> None:
        self.usuario = _usuario()
        self.roles: list[str] = ["cajero"]
        self.sesiones: dict[str, str] = {
            "sellada-vigente": "vigente",
            "sellada-vencida": "vencida",
        }
        self.error: Exception | None = None
        self.error_jwks: Exception | None = None
        self.renovaciones = 0
        # Vínculos guardados en la base (KeyUsuario): AgenciaID y UsuarioID
        self.agencias: dict[str, str] = {"user_1": "001"}
        # user_1 es un usuario interno Activo; sin entrada aquí, no registrado
        self.internos: dict[str, int] = {"user_1": 1}
        self.consultas_base = 0
        self.roles_registrados: dict[str, str | None] = {}
        self.llamadas: list[tuple[str, dict[str, Any]]] = []

    def get_authorization_url(self, **kwargs: Any) -> str:
        self.llamadas.append(("authorize", kwargs))
        return f"{AUTHORIZE}?state={kwargs['state']}"

    def authenticate_with_code(self, **kwargs: Any) -> SimpleNamespace:
        self.llamadas.append(("code", kwargs))
        if self.error:
            raise self.error
        self.sesiones["sellada-nueva"] = "vigente"
        return SimpleNamespace(sealed_session="sellada-nueva", user=self.usuario)

    def load_sealed_session(self, *, sealed_session: str, cookie_password: str):
        clave = get_settings().workos_cookie_password.get_secret_value()
        assert cookie_password == clave
        return _Sesion(self, sealed_session)

    def revoke_session(self, *, session_id: str) -> None:
        self.llamadas.append(("revoke_session", {"session_id": session_id}))

    def get_logout_url(self, session_id: str, return_to: str) -> str:
        self.llamadas.append(("logout", {"session_id": session_id}))
        return (
            "https://api.workos.com/logout"
            f"?session_id={session_id}&return_to={return_to}"
        )


@pytest.fixture(autouse=True)
def _configuracion(monkeypatch):
    monkeypatch.setenv("WORKOS_COOKIE_PASSWORD", Fernet.generate_key().decode())
    monkeypatch.setenv("WORKOS_REDIRECT_URI", CALLBACK)
    monkeypatch.setenv("FRONTEND_URL", FRONT + "/")
    monkeypatch.setenv("WORKOS_ORGANIZATION_ID", "org_1")
    get_settings.cache_clear()
    workos_client.get_cookie_password.cache_clear()
    security._renovaciones.clear()
    yield
    get_settings.cache_clear()
    workos_client.get_cookie_password.cache_clear()


@pytest.fixture()
def workos(monkeypatch) -> _UserManagement:
    falso = _UserManagement()
    cliente = SimpleNamespace(user_management=falso)
    monkeypatch.setattr(security, "get_workos", lambda: cliente)
    monkeypatch.setattr(service, "get_workos", lambda: cliente)

    def agencia(id_workos: str) -> str | None:
        falso.consultas_base += 1
        return falso.agencias.get(id_workos)

    def interno(id_workos: str, roles: str | None) -> int | None:
        falso.consultas_base += 1
        falso.roles_registrados[id_workos] = roles
        return falso.internos.get(id_workos)

    monkeypatch.setattr(security, "_agencia_db", agencia)
    monkeypatch.setattr(security, "_id_interno_db", interno)
    return falso


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False, follow_redirects=False)


def _ruta(destino: str) -> str:
    """Decodifica la ruta guardada en la cookie de state (base64 sin relleno)."""
    return base64.urlsafe_b64decode(destino + "=" * (-len(destino) % 4)).decode()


def _cookies(response: httpx.Response) -> dict[str, str]:
    """Set-Cookie de la respuesta, por nombre."""
    return {
        valor.split("=", 1)[0]: valor
        for valor in response.headers.get_list("set-cookie")
    }


def _con_sesion(sellada: str = "sellada-vigente", **extra: str) -> dict[str, str]:
    return {"Cookie": f"{COOKIE_SESION}={sellada}", **extra}


def _iniciar(client: TestClient, return_to: str = "/clientes") -> tuple[str, str]:
    """GET /login: devuelve el state de la URL y el valor de la cookie de state."""
    r = client.get(f"{BASE}/login", params={"return_to": return_to})
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    cookie = _cookies(r)[COOKIE_STATE].split(";")[0].split("=", 1)[1]
    return state, cookie


def _callback(client: TestClient, cookie_state: str | None, **params: str):
    cabeceras = {"Cookie": f"{COOKIE_STATE}={cookie_state}"} if cookie_state else {}
    return client.get(f"{BASE}/callback", params=params, headers=cabeceras)


# --- AUT-01 GET /auth/login --------------------------------------------------------


def test_login_redirige_al_hosted_ui_con_state_y_pkce(client, workos):
    r = client.get(f"{BASE}/login", params={"return_to": "/clientes?page=2"})

    assert r.status_code == 302
    assert r.headers["location"].startswith(AUTHORIZE)
    assert r.headers["cache-control"] == "no-store"
    argumentos = workos.llamadas[0][1]
    assert argumentos["provider"] == "authkit"
    assert argumentos["redirect_uri"] == CALLBACK
    cookie = _cookies(r)[COOKIE_STATE]
    for atributo in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=600"):
        assert atributo in cookie
    state, verificador, destino = cookie.split(";")[0].split("=", 1)[1].split(".")
    assert state == argumentos["state"] and len(state) >= 43
    assert len(verificador) == 43
    assert verificador != state
    resumen = hashlib.sha256(verificador.encode("ascii")).digest()
    assert argumentos["code_challenge"] == base64.urlsafe_b64encode(
        resumen
    ).decode().rstrip("=")
    assert verificador not in r.headers["location"]
    assert _ruta(destino) == "/clientes?page=2"


@pytest.mark.parametrize(
    "return_to",
    ["//evil.com", "/\\evil.com", "https://evil.com", "clientes", "/a b", ""],
)
def test_login_return_to_externo_vuelve_al_inicio(client, workos, return_to):
    _, cookie = _iniciar(client, return_to)

    assert _ruta(cookie.split(".", 2)[2]) == "/"


# --- AUT-01 GET /auth/callback -----------------------------------------------------


def test_callback_crea_la_sesion_y_vuelve_a_return_to(
    client, workos, eventos_auditados
):
    state, cookie = _iniciar(client)

    r = _callback(client, cookie, code="code-1", state=state)

    assert r.status_code == 302
    assert r.headers["location"] == f"{FRONT}/clientes"
    cookies = _cookies(r)
    sesion = cookies[COOKIE_SESION]
    assert sesion.startswith(f"{COOKIE_SESION}=sellada-nueva;")
    for atributo in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
        assert atributo in sesion
    assert "Domain" not in sesion
    assert "Max-Age=0" in cookies[COOKIE_STATE]
    argumentos = workos.llamadas[-1][1]
    assert argumentos["code"] == "code-1"
    assert argumentos["code_verifier"] == cookie.split(".", 2)[1]
    assert argumentos["session"]["seal_session"] is True
    assert eventos_auditados[-1].resultado == "Exitoso"


def test_callback_usuario_no_habilitado_no_crea_sesion_y_la_revoca(
    client, workos, eventos_auditados
):
    # Bloqueado, Inactivo o sin vínculo: no hay fila Activa con su KeyUsuario
    workos.internos.clear()
    state, cookie = _iniciar(client)

    r = _callback(client, cookie, code="code-1", state=state)

    assert r.headers["location"] == f"{FRONT}/login?error=USUARIO_NO_HABILITADO"
    assert COOKIE_SESION not in _cookies(r)
    assert ("revoke_session", {"session_id": "session_1"}) in workos.llamadas
    assert eventos_auditados[-1].resultado == "Fallido"


def test_callback_sesion_sin_organizacion_no_crea_sesion(client, workos, monkeypatch):
    # Membresía inactiva: WorkOS entrega la sesión sin organización
    monkeypatch.setenv("WORKOS_ORGANIZATION_ID", "org_enquocoop")
    get_settings.cache_clear()
    state, cookie = _iniciar(client)

    r = _callback(client, cookie, code="code-1", state=state)

    assert r.headers["location"] == f"{FRONT}/login?error=USUARIO_NO_HABILITADO"
    assert COOKIE_SESION not in _cookies(r)
    assert ("revoke_session", {"session_id": "session_1"}) in workos.llamadas


def test_callback_sin_llaves_de_workos_no_crea_sesion(client, workos):
    state, cookie = _iniciar(client)
    workos.error_jwks = PyJWKClientConnectionError("sin red")

    r = _callback(client, cookie, code="code-1", state=state)

    assert r.headers["location"] == f"{FRONT}/login?error=AUTENTICACION_NO_DISPONIBLE"
    assert COOKIE_SESION not in _cookies(r)


def test_me_usuario_bloqueado_con_sesion_viva_403(client, workos):
    workos.internos.clear()

    r = client.get(f"{BASE}/me", headers=_con_sesion())

    assert r.status_code == 403
    assert r.json()["code"] == "USUARIO_NO_REGISTRADO"


@pytest.mark.parametrize("cookie_state", [None, "otro-state.Lw", "sin-punto", "x.%%"])
def test_callback_state_invalido_no_crea_sesion(
    client, workos, eventos_auditados, cookie_state
):
    state, _ = _iniciar(client)

    r = _callback(client, cookie_state, code="code-1", state=state)

    assert r.headers["location"] == f"{FRONT}/login?error=SOLICITUD_INVALIDA"
    assert COOKIE_SESION not in _cookies(r)
    assert [metodo for metodo, _ in workos.llamadas] == ["authorize"]
    assert eventos_auditados[-1].resultado == "Fallido"


@pytest.mark.parametrize("verificador", [None, "", "invalido"])
def test_callback_sin_verificador_valido_no_canjea_el_codigo(
    client, workos, verificador
):
    state, cookie = _iniciar(client)
    destino = cookie.split(".", 2)[2]
    cookie = (
        f"{state}.{destino}"
        if verificador is None
        else f"{state}.{verificador}.{destino}"
    )

    r = _callback(client, cookie, code="code-1", state=state)

    assert r.headers["location"] == f"{FRONT}/login?error=SOLICITUD_INVALIDA"
    assert COOKIE_SESION not in _cookies(r)
    assert [metodo for metodo, _ in workos.llamadas] == ["authorize"]


def test_callback_usuario_cancelo(client, workos):
    state, cookie = _iniciar(client)

    r = _callback(client, cookie, state=state, error="access_denied")

    assert r.headers["location"] == f"{FRONT}/login?error=LOGIN_CANCELADO"


def test_callback_code_rechazado(client, workos):
    cuerpo = {"code": "invalid_grant", "message": "rechazado"}
    workos.error = AuthenticationException(httpx.Response(400, json=cuerpo), cuerpo)
    state, cookie = _iniciar(client)

    r = _callback(client, cookie, code="code-1", state=state)

    assert r.headers["location"] == f"{FRONT}/login?error=CREDENCIALES_INVALIDAS"
    assert COOKIE_SESION not in _cookies(r)


def test_callback_workos_caido(client, workos):
    workos.error = httpx.ConnectError("sin red")
    state, cookie = _iniciar(client)

    r = _callback(client, cookie, code="code-1", state=state)

    assert r.headers["location"] == (f"{FRONT}/login?error=AUTENTICACION_NO_DISPONIBLE")


# --- AUT-04 GET /auth/me -----------------------------------------------------------


def test_me_usuario_con_un_rol(client, workos):
    r = client.get(f"{BASE}/me", headers=_con_sesion())

    assert r.status_code == 200
    assert r.json() == {
        "idUsuario": "user_1",
        "nombre": "María López",
        "email": "maria.lopez@correo.ec",
        "idOrganizacion": "org_1",
        "roles": ["CAJERO"],
        "permisos": ["cuentas:crear"],
        "idAgencia": "001",
    }
    assert "set-cookie" not in r.headers


def test_me_usuario_con_varios_roles(client, workos):
    workos.roles = ["asesor", "SUPERVISOR", "aprobador-credito", "member"]

    r = client.get(f"{BASE}/me", headers=_con_sesion())

    assert r.json()["roles"] == ["ASESOR", "SUPERVISOR", "APROBADOR_CREDITO"]


def test_roles_de_organizacion_con_prefijo_org(client, workos):
    # Slugs que se crean en WorkOS (C-05): org-<rol>
    workos.roles = ["org-aprobador-credito"]

    r = client.get(f"{BASE}/me", headers=_con_sesion())

    assert r.json()["roles"] == ["APROBADOR_CREDITO"]


def test_slug_rol_es_el_inverso_de_normalizar():
    for rol in security.ROLES:
        assert security.normalizar_roles([security.slug_rol(rol)], None) == (rol,)
    with pytest.raises(ValueError):
        security.slug_rol("MEMBER")


def test_sesion_de_otra_organizacion_no_tiene_roles(client, workos, monkeypatch):
    monkeypatch.setenv("WORKOS_ORGANIZATION_ID", "org_enquocoop")
    get_settings.cache_clear()

    r = client.get(f"{BASE}/me", headers=_con_sesion())

    assert r.status_code == 200
    assert r.json()["roles"] == []


def test_me_sin_agencia_vigente(client, workos):
    workos.usuario = _usuario(first_name=None, last_name=None)
    workos.agencias.clear()

    cuerpo = client.get(f"{BASE}/me", headers=_con_sesion()).json()

    assert cuerpo["idAgencia"] is None
    assert cuerpo["nombre"] == "maria.lopez@correo.ec"


def test_agencia_sale_de_agencia_id_del_usuario(client, workos):
    cuerpo = client.get(f"{BASE}/me", headers=_con_sesion()).json()

    # Organizacion.Usuarios.AgenciaID del usuario vinculado (KeyUsuario = user_1)
    assert cuerpo["idAgencia"] == "001"
    # Una para require_auth (vínculo Activo) y otra para la agencia
    assert workos.consultas_base == 2


def test_cambio_de_vinculo_aplica_sin_volver_a_iniciar_sesion(client, workos):
    client.get(f"{BASE}/me", headers=_con_sesion())
    workos.agencias["user_1"] = "002"

    cuerpo = client.get(f"{BASE}/me", headers=_con_sesion()).json()

    # Sin caché entre peticiones
    assert cuerpo["idAgencia"] == "002"


def test_usuario_sin_agencia_no_tiene_agencia(client, workos):
    workos.agencias.clear()

    assert client.get(f"{BASE}/me", headers=_con_sesion()).json()["idAgencia"] is None


def test_vinculos_solo_se_consultan_si_se_usan(workos):
    sesion = security.validar_sesion("sellada-vigente")
    assert sesion is not None
    assert workos.consultas_base == 0

    assert sesion.usuario.interno(solo_si_leido=True) is None
    assert workos.consultas_base == 0

    assert sesion.usuario.agencia() == "001"
    assert sesion.usuario.agencia() == "001"
    assert sesion.usuario.interno() == 1
    assert sesion.usuario.interno() == 1
    # Una consulta por dato y por petición
    assert workos.consultas_base == 2


def test_id_interno_sale_de_key_usuario(workos):
    workos.internos["user_1"] = 8
    sesion = security.validar_sesion("sellada-vigente")
    assert sesion is not None

    assert security.id_usuario_auditoria(sesion.usuario) == 8
    # Los roles que dio WorkOS se envían para guardarlos en RolesWorkOS
    assert workos.roles_registrados["user_1"] == "CAJERO"


def test_usuario_no_registrado_se_rechaza_antes_de_la_ruta(client, workos):
    router = APIRouter(
        route_class=ProblemDetailsRoute, dependencies=[Depends(security.require_auth)]
    )
    ejecutada: list[bool] = []

    @router.get("/protegida")
    def protegida() -> dict[str, bool]:
        ejecutada.append(True)
        return {"ok": True}

    prueba = FastAPI()
    prueba.include_router(router)
    cliente = TestClient(prueba, raise_server_exceptions=False)
    workos.internos.clear()

    r = cliente.get("/protegida", headers=_con_sesion())
    assert r.status_code == 403
    assert r.json()["code"] == "USUARIO_NO_REGISTRADO"
    assert ejecutada == []

    workos.internos["user_1"] = 8
    assert cliente.get("/protegida", headers=_con_sesion()).status_code == 200
    assert ejecutada == [True]


def test_vinculo_falla_cerrado_si_la_base_falla(monkeypatch):
    from sqlalchemy.exc import OperationalError

    def caida(_base):
        raise OperationalError("SELECT", {}, Exception("sin red"))

    monkeypatch.setattr(security, "get_engine", caida)

    assert security._id_interno_db("user_1", "ADMIN") is None
    assert security._agencia_db("user_1") is None


def test_me_con_token_vencido_renueva_la_cookie(client, workos):
    r = client.get(f"{BASE}/me", headers=_con_sesion("sellada-vencida"))

    assert r.status_code == 200
    assert _cookies(r)[COOKIE_SESION].startswith(f"{COOKIE_SESION}=sellada-renovada-1;")


def test_peticiones_paralelas_comparten_una_renovacion(workos):
    primera = security.validar_sesion("sellada-vencida")
    segunda = security.validar_sesion("sellada-vencida")

    assert workos.renovaciones == 1
    assert primera is not None and segunda is not None
    assert primera.sellada_nueva == segunda.sellada_nueva


def test_cookie_vieja_ya_renovada_no_sirve_despues_del_margen(workos):
    assert security.validar_sesion("sellada-vencida") is not None
    security._renovaciones.clear()  # como si hubieran pasado los 30 s

    assert security.validar_sesion("sellada-vencida") is None


def test_me_sin_cookie_401(client, workos):
    r = client.get(f"{BASE}/me")

    assert r.status_code == 401
    assert r.json()["code"] == "NO_AUTENTICADO"


def test_me_cookie_invalida_401_y_la_borra(client, workos):
    r = client.get(f"{BASE}/me", headers=_con_sesion("basura"))

    assert r.status_code == 401
    assert "Max-Age=0" in _cookies(r)[COOKIE_SESION]


def test_me_llaves_de_workos_inaccesibles_503(client, workos):
    workos.error_jwks = PyJWKClientConnectionError("sin red")

    r = client.get(f"{BASE}/me", headers=_con_sesion())

    assert r.status_code == 503
    assert r.json()["code"] == "AUTENTICACION_NO_DISPONIBLE"


# --- AUT-02 POST /auth/refresh -----------------------------------------------------


def test_refresh_reescribe_la_cookie(client, workos):
    r = client.post(f"{BASE}/refresh", headers=_con_sesion(origin=FRONT))

    assert r.status_code == 204
    assert _cookies(r)[COOKIE_SESION].startswith(f"{COOKIE_SESION}=sellada-renovada-1;")


def test_refresh_sin_sesion_401(client, workos):
    r = client.post(f"{BASE}/refresh")

    assert r.status_code == 401
    assert r.json()["code"] == "NO_AUTENTICADO"


def test_refresh_desde_otro_origen_403(client, workos):
    r = client.post(
        f"{BASE}/refresh", headers=_con_sesion(origin="https://evil.example")
    )

    assert r.status_code == 403
    assert r.json()["code"] == "ORIGEN_NO_PERMITIDO"
    assert workos.renovaciones == 0


# --- AUT-03 POST /auth/logout ------------------------------------------------------


def test_logout_devuelve_logout_url_y_borra_la_cookie(
    client, workos, eventos_auditados
):
    r = client.post(f"{BASE}/logout", headers=_con_sesion(origin=FRONT))

    assert r.status_code == 200
    url = r.json()["logoutUrl"]
    assert "session_id=session_1" in url and f"return_to={FRONT}/login" in url
    assert "Max-Age=0" in _cookies(r)[COOKIE_SESION]
    assert eventos_auditados[-1].accion == "LOGOUT"
    assert eventos_auditados[-1].resultado == "Exitoso"


def test_logout_con_token_vencido_igual_cierra_en_workos(client, workos):
    r = client.post(f"{BASE}/logout", headers=_con_sesion("sellada-vencida"))

    assert "session_id=session_1" in r.json()["logoutUrl"]


def test_logout_sin_sesion_es_idempotente(client, workos):
    r = client.post(f"{BASE}/logout")

    assert r.status_code == 200
    assert r.json() == {"logoutUrl": f"{FRONT}/login"}


def test_logout_desde_otro_sitio_403(client, workos):
    cabeceras = _con_sesion(**{"sec-fetch-site": "cross-site"})

    r = client.post(f"{BASE}/logout", headers=cabeceras)

    assert r.status_code == 403


# --- Previews de PR de Cloudflare (FRONTEND_ORIGIN_REGEX, solo backend-dev) --------

FRONT_DEV = "https://banking-platform-front.diegosebastia94.workers.dev"
CALLBACK_DEV = f"{FRONT_DEV}/api/v1/auth/callback"
PREVIEW_HOST = "pr-12-banking-platform-front.diegosebastia94.workers.dev"
PREVIEW = f"https://{PREVIEW_HOST}"
DESDE_PREVIEW = {"x-forwarded-host": PREVIEW_HOST}


@pytest.fixture()
def preview(monkeypatch):
    """Configuración de backend-dev: WorkOS Staging y regex de previews."""
    monkeypatch.setenv("FRONTEND_URL", FRONT_DEV)
    monkeypatch.setenv("WORKOS_REDIRECT_URI", CALLBACK_DEV)
    monkeypatch.setenv("WORKOS_API_KEY", "sk_test_prueba")
    monkeypatch.setenv(
        "FRONTEND_ORIGIN_REGEX",
        r"^https://[a-z0-9-]+-banking-platform-front\.diegosebastia94\.workers\.dev$",
    )
    get_settings.cache_clear()


def _iniciar_desde(client: TestClient, cabeceras: dict[str, str]) -> tuple[str, str]:
    r = client.get(
        f"{BASE}/login", params={"return_to": "/clientes"}, headers=cabeceras
    )
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    cookie = _cookies(r)[COOKIE_STATE].split(";")[0].split("=", 1)[1]
    return state, cookie


def test_login_desde_preview_vuelve_al_callback_de_la_preview(client, workos, preview):
    r = client.get(f"{BASE}/login", headers=DESDE_PREVIEW)

    assert workos.llamadas[0][1]["redirect_uri"] == f"{PREVIEW}/api/v1/auth/callback"
    cookie = _cookies(r)[COOKIE_STATE]
    for atributo in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=600"):
        assert atributo in cookie
    assert "Domain" not in cookie


@pytest.mark.parametrize(
    "cabeceras",
    [
        {},
        {"x-forwarded-host": FRONT_DEV.removeprefix("https://")},
        {"x-forwarded-host": "evil.com"},
        {"x-forwarded-host": f"{PREVIEW_HOST}.evil.com"},
    ],
)
def test_login_fuera_de_preview_usa_workos_redirect_uri(
    client, workos, preview, cabeceras
):
    client.get(f"{BASE}/login", headers=cabeceras)

    assert workos.llamadas[0][1]["redirect_uri"] == CALLBACK_DEV


def test_sin_regex_se_ignora_x_forwarded_host(client, workos):
    client.get(f"{BASE}/login", headers=DESDE_PREVIEW)
    r = _callback(client, None, code="code-1", state="x")

    assert workos.llamadas[0][1]["redirect_uri"] == CALLBACK
    assert r.headers["location"] == f"{FRONT}/login?error=SOLICITUD_INVALIDA"


def test_callback_desde_preview_vuelve_a_la_preview(client, workos, preview):
    state, cookie = _iniciar_desde(client, DESDE_PREVIEW)

    r = client.get(
        f"{BASE}/callback",
        params={"code": "code-1", "state": state},
        headers={"Cookie": f"{COOKIE_STATE}={cookie}", **DESDE_PREVIEW},
    )

    assert r.headers["location"] == f"{PREVIEW}/clientes"
    assert _cookies(r)[COOKIE_SESION].startswith(f"{COOKIE_SESION}=sellada-nueva;")


def test_callback_con_error_desde_preview_vuelve_al_login_de_la_preview(
    client, workos, preview
):
    r = client.get(
        f"{BASE}/callback",
        params={"code": "code-1", "state": "otro"},
        headers=DESDE_PREVIEW,
    )

    assert r.headers["location"] == f"{PREVIEW}/login?error=SOLICITUD_INVALIDA"
    assert COOKIE_SESION not in _cookies(r)


def test_logout_desde_preview_vuelve_al_login_de_la_preview(client, workos, preview):
    r = client.post(
        f"{BASE}/logout", headers=_con_sesion(origin=PREVIEW, **DESDE_PREVIEW)
    )

    assert r.status_code == 200
    assert f"return_to={PREVIEW}/login" in r.json()["logoutUrl"]


def test_logout_sin_sesion_desde_preview(client, workos, preview):
    r = client.post(f"{BASE}/logout", headers=DESDE_PREVIEW)

    assert r.json() == {"logoutUrl": f"{PREVIEW}/login"}


@pytest.mark.parametrize(
    ("origin", "cabeceras", "estado"),
    [
        (PREVIEW, DESDE_PREVIEW, 204),
        (FRONT_DEV, DESDE_PREVIEW, 204),
        (PREVIEW, {}, 403),
        (
            PREVIEW,
            {
                "x-forwarded-host": "pr-13-banking-platform-front.diegosebastia94.workers.dev"
            },
            403,
        ),
        ("https://evil.com", {"x-forwarded-host": "evil.com"}, 403),
    ],
)
def test_verificar_origen_con_preview(
    client, workos, preview, origin, cabeceras, estado
):
    r = client.post(f"{BASE}/refresh", headers=_con_sesion(origin=origin, **cabeceras))

    assert r.status_code == estado


# --- core/security.py --------------------------------------------------------------


def _app_con_roles() -> TestClient:
    rutas = APIRouter(route_class=ProblemDetailsRoute)

    @rutas.get("/solo-admin", dependencies=[Depends(require_roles("ADMIN"))])
    def solo_admin() -> dict[str, bool]:
        return {"ok": True}

    prueba = FastAPI()
    prueba.include_router(rutas)
    return TestClient(prueba)


def test_require_roles_403_sin_el_rol(workos):
    r = _app_con_roles().get("/solo-admin", headers=_con_sesion())

    assert r.status_code == 403
    assert r.json()["code"] == "SIN_PERMISO"


def test_require_roles_permite_con_el_rol(workos):
    workos.roles = ["admin"]

    r = _app_con_roles().get("/solo-admin", headers=_con_sesion())

    assert r.status_code == 200


def test_require_roles_rechaza_roles_desconocidos():
    with pytest.raises(ValueError, match="GERENTE"):
        require_roles("GERENTE")


def test_frontend_url_con_ruta_es_invalida(monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:5173/app")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="FRONTEND_URL"):
        get_settings()


def test_cookie_password_invalida(monkeypatch):
    monkeypatch.setenv("WORKOS_COOKIE_PASSWORD", "no-es-fernet")
    get_settings.cache_clear()
    workos_client.get_cookie_password.cache_clear()

    with pytest.raises(RuntimeError, match="Fernet"):
        workos_client.get_cookie_password()
