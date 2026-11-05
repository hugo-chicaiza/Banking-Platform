"""AUT-01..04 · Sesión con WorkOS AuthKit, patrón BFF.

1. El FE navega (no fetch) a GET /auth/login?return_to=/ruta.
2. El backend redirige al Hosted UI de AuthKit; el usuario inicia sesión allí.
3. AuthKit vuelve a GET /auth/callback; el backend crea la cookie de sesión y
   redirige al FE en return_to.
4. El FE llama a la API con la cookie (fetch con credentials) y usa GET /auth/me.
5. Logout: POST /auth/logout y el FE navega a la logoutUrl que recibe.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute
from app.core.security.auth import (
    COOKIE_SESION,
    UsuarioActual,
    borrar_cookie_sesion,
    guardar_cookie_sesion,
    no_autenticado,
    verificar_origen,
)
from app.integrations.workos_client import get_frontend_url
from app.modules.auth import service
from app.modules.auth.schemas import LogoutResponse, UsuarioSesion

COOKIE_STATE = "__Host-oauth_state"
_DURACION_STATE = 10 * 60  # tiempo para completar el login en el Hosted UI
_MAX_USER_AGENT = 512
_MAX_PARAMETRO = 2048

CookieSesion = Annotated[str | None, Cookie(alias=COOKIE_SESION, max_length=8192)]
ParametroCallback = Annotated[str | None, Query(max_length=_MAX_PARAMETRO)]


def _sin_cache(response: Response) -> None:
    """Datos de sesión no deben quedar en caché de navegadores ni proxies."""
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"


# Sin require_auth a nivel de router: login y callback son públicos. Las demás
# rutas validan la sesión con UsuarioActual o leen la cookie directamente.
router = APIRouter(
    prefix="/auth",
    route_class=ProblemDetailsRoute,
    responses=RESPUESTAS_ERROR,
    tags=["auth"],
    dependencies=[Depends(_sin_cache)],
)


def _ip(request: Request) -> str | None:
    # X-Forwarded-For no se lee porque el cliente puede falsificarlo
    return request.client.host if request.client else None


def _origen(request: Request) -> str:
    # Uno de los FRONTEND_URL: el de este host (5173 con el FE, 8471 con /docs)
    return get_frontend_url(request.headers.get("host"))


def _user_agent(request: Request) -> str | None:
    agente = request.headers.get("user-agent")
    return agente[:_MAX_USER_AGENT] if agente else None


def _redireccion(url: str) -> RedirectResponse:
    respuesta = RedirectResponse(url, status_code=302)
    _sin_cache(respuesta)
    return respuesta


# AUT-01. Público. El FE navega aquí con window.location, no con fetch
@router.get("/login", response_class=RedirectResponse, status_code=302)
def login(
    request: Request,
    return_to: Annotated[str | None, Query(max_length=512)] = None,
) -> RedirectResponse:
    """Redirige al Hosted UI de AuthKit. `return_to` es la ruta del FE a la que se
    vuelve después; si no es una ruta interna se usa "/".
    """
    url, valor_state = service.iniciar_login(return_to, _origen(request))
    respuesta = _redireccion(url)
    # Lax: tiene que viajar en la navegación de vuelta desde WorkOS
    respuesta.set_cookie(
        COOKIE_STATE,
        valor_state,
        max_age=_DURACION_STATE,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )
    return respuesta


# AUT-01. Público. Es la WORKOS_REDIRECT_URI: aquí vuelve AuthKit
@router.get("/callback", response_class=RedirectResponse, status_code=302)
def callback(
    request: Request,
    code: ParametroCallback = None,
    state: ParametroCallback = None,
    error: ParametroCallback = None,
    cookie_state: Annotated[
        str | None, Cookie(alias=COOKIE_STATE, max_length=1024)
    ] = None,
) -> RedirectResponse:
    """Crea la cookie de sesión y vuelve al FE, o a /login?error=CODIGO si falla."""
    destino, sellada = service.completar_login(
        code,
        state,
        error,
        cookie_state,
        _ip(request),
        _user_agent(request),
        _origen(request),
    )
    respuesta = _redireccion(destino)
    respuesta.delete_cookie(
        COOKIE_STATE, path="/", secure=True, httponly=True, samesite="lax"
    )
    if sellada:
        guardar_cookie_sesion(respuesta, sellada)
    return respuesta


# AUT-02. Requiere cookie de sesión. Opcional: /me y las demás rutas ya renuevan solas
@router.post("/refresh", status_code=204, dependencies=[Depends(verificar_origen)])
def refresh(response: Response, sellada: CookieSesion = None) -> None:
    """Renueva el access token de la sesión y reescribe la cookie."""
    sesion = service.refrescar(sellada)
    if sesion is None or not sesion.sellada_nueva:
        raise no_autenticado(borrar_cookie=True)
    guardar_cookie_sesion(response, sesion.sellada_nueva)


# AUT-03. Idempotente: sin sesión también responde 200
@router.post(
    "/logout", response_model=LogoutResponse, dependencies=[Depends(verificar_origen)]
)
def logout(request: Request, response: Response, sellada: CookieSesion = None) -> Any:
    """Borra la cookie y devuelve la URL que cierra la sesión en AuthKit."""
    url = service.cerrar_sesion(sellada, _ip(request), _origen(request))
    borrar_cookie_sesion(response)
    return LogoutResponse(logout_url=url)


# AUT-04. Roles: AUTH
@router.get("/me", response_model=UsuarioSesion)
def me(usuario: UsuarioActual) -> Any:
    """Usuario de la sesión, sus roles, permisos y agencia vigente."""
    return service.perfil(usuario)
