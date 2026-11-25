"""E5-04 · Correos secundarios del cliente y marca "verificado por el personal".

Sin base de datos: se reemplazan el repositorio de clientes, el parámetro y el SQL
de correos.py; la sesión es la simulada de tests/sesion.py.
"""

import asyncio
import json
from datetime import datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.database.db import cooperativa
from app.modules.clientes import correos, repository
from app.modules.parametros import general
from tests.sesion import ID_AUDITORIA, simular_sesion, usuario_con_roles

BASE = "/api/v1/clientes"
CORREO = "secundario@example.com"
FECHA = datetime(2026, 11, 24, 15, 0, 0)


class _Conn:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _fila(id_email: int = 7, email: str = CORREO, verificado: bool = False) -> dict:
    return {
        "id_cliente_email": id_email,
        "email": email,
        "etiqueta": "Trabajo",
        "verificado": verificado,
        "fecha_verificacion": FECHA if verificado else None,
        "fecha_creacion": FECHA,
    }


class _Entorno:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.conn = _Conn()
        self.estado: str | None = "Activo"
        self.maximo: Any = 2
        self.activos: list[dict] = []
        self.principal: dict | None = {
            "email": "Principal@Example.com",
            "verificado_por": None,
        }
        self.historial: list[dict] = []
        self.insertados: list[tuple] = []
        self.bajas: list[tuple] = []
        mp = monkeypatch
        mp.setattr(repository, "bloquear_cliente", self._cliente)
        mp.setattr(repository, "obtener_cliente_por_id", self._cliente)
        mp.setattr(
            repository,
            "insertar_historial_cliente",
            lambda conn, **kw: self.historial.append(kw),
        )
        mp.setattr(general, "valor", lambda conn, clave, fecha: self.maximo)
        mp.setattr(correos, "listar_activos", lambda conn, cid: self.activos)
        mp.setattr(correos, "leer_principal", lambda conn, cid: self.principal)
        mp.setattr(correos, "obtener_activo", self._activo)
        mp.setattr(correos, "insertar", self._insertar)
        mp.setattr(
            correos, "dar_de_baja", lambda conn, cid, eid: self.bajas.append((cid, eid))
        )
        mp.setattr(
            correos,
            "marcar_secundario",
            lambda conn, cid, eid, usuario: _fila(eid, verificado=True),
        )
        mp.setattr(correos, "marcar_principal", lambda conn, cid, usuario: FECHA)

    def _cliente(self, conn, id_cliente):
        return (
            None
            if self.estado is None
            else {"id_cliente": id_cliente, "estado": self.estado}
        )

    def _activo(self, conn, id_cliente, id_email):
        return next(
            (f for f in self.activos if f["id_cliente_email"] == id_email), None
        )

    def _insertar(self, conn, id_cliente, email, etiqueta, creado_por):
        self.insertados.append((id_cliente, email, etiqueta, creado_por))
        return {**_fila(9, email), "etiqueta": etiqueta}


@pytest.fixture
def entorno(monkeypatch) -> _Entorno:
    return _Entorno(monkeypatch)


def _llamar(
    entorno: _Entorno, metodo: str, ruta: str, body: Any = None, roles=None
) -> httpx.Response:
    local = FastAPI()
    local.include_router(correos.router, prefix=BASE)
    if roles is None:
        simular_sesion(local)
    else:
        simular_sesion(local, usuario_con_roles(*roles))
    local.dependency_overrides[cooperativa] = lambda: entorno.conn

    async def llamar():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=local), base_url="http://test"
        ) as client:
            return await client.request(metodo, BASE + ruta, json=body)

    return asyncio.run(llamar())


def _code(respuesta: httpx.Response) -> str:
    assert respuesta.headers["content-type"] == "application/problem+json"
    return respuesta.json()["code"]


NUEVO = {"email": "Nuevo.Correo@Example.COM", "etiqueta": "Personal"}


def test_listar_solo_activos(entorno):
    entorno.activos = [_fila(3), _fila(5, "otro@example.com", verificado=True)]
    respuesta = _llamar(entorno, "GET", "/10/emails")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert [d["idClienteEmail"] for d in datos] == [3, 5]
    assert datos[1]["verificado"] is True
    assert "creadoPor" not in datos[0] and "verificadoPor" not in datos[0]


def test_alta_ok_en_minusculas_con_historial_y_auditoria(entorno, eventos_auditados):
    respuesta = _llamar(entorno, "POST", "/10/emails", NUEVO)
    assert respuesta.status_code == 201
    assert respuesta.json()["email"] == "nuevo.correo@example.com"
    assert entorno.insertados == [
        (10, "nuevo.correo@example.com", "Personal", ID_AUDITORIA)
    ]
    assert entorno.conn.commits == 1 and entorno.conn.rollbacks == 0
    (his,) = entorno.historial
    assert his["tipo_operacion"] == "I" and his["campo"] == "EMAIL_SECUNDARIO"
    assert his["valor_anterior"] is None
    assert his["valor_nuevo"] == "nuevo.correo@example.com"
    assert json.loads(his["observaciones"])["v"] == 1
    (evento,) = eventos_auditados
    assert evento.accion == "CLI_EDITADO" and evento.tabla == "Clientes.ClienteEmail"
    assert evento.id_registro == "10" and evento.resultado == "Exitoso"
    assert "@" not in evento.descripcion
    assert "nuevo.correo" not in evento.descripcion.lower()


@pytest.mark.parametrize(
    "estado,status,code",
    [
        (None, 404, "CLIENTE_NO_ENCONTRADO"),
        ("Bloqueado", 423, "CLIENTE_BLOQUEADO"),
        ("Eliminado", 409, "CLIENTE_NO_EDITABLE"),
    ],
)
@pytest.mark.parametrize(
    "metodo,ruta,body",
    [
        ("POST", "/10/emails", NUEVO),
        ("DELETE", "/10/emails/7", None),
        ("POST", "/10/email/verificacion", None),
        ("POST", "/10/emails/7/verificacion", None),
    ],
)
def test_escrituras_validan_cliente(
    entorno, eventos_auditados, estado, status, code, metodo, ruta, body
):
    entorno.estado = estado
    entorno.activos = [_fila(7)]
    respuesta = _llamar(entorno, metodo, ruta, body)
    assert respuesta.status_code == status and _code(respuesta) == code
    assert entorno.conn.commits == 0 and entorno.conn.rollbacks == 1
    assert not entorno.historial and not eventos_auditados


def test_listar_cliente_inexistente(entorno):
    entorno.estado = None
    respuesta = _llamar(entorno, "GET", "/10/emails")
    assert respuesta.status_code == 404 and _code(respuesta) == "CLIENTE_NO_ENCONTRADO"


def test_limite_de_correos_secundarios(entorno):
    entorno.activos = [_fila(1, "a@example.com"), _fila(2, "b@example.com")]
    respuesta = _llamar(entorno, "POST", "/10/emails", NUEVO)
    assert respuesta.status_code == 422
    assert _code(respuesta) == "LIMITE_EMAILS_SECUNDARIOS"
    assert not entorno.insertados and entorno.conn.rollbacks == 1


@pytest.mark.parametrize("email", ["PRINCIPAL@example.com", "a@example.com"])
def test_duplicado_con_principal_o_secundario(entorno, email):
    entorno.activos = [_fila(1, "a@example.com")]
    respuesta = _llamar(
        entorno, "POST", "/10/emails", {"email": email, "etiqueta": "x"}
    )
    assert respuesta.status_code == 409 and _code(respuesta) == "EMAIL_DUPLICADO"
    assert not entorno.insertados


@pytest.mark.parametrize("valor", ["2", None, True, 1.5, -1])
def test_parametro_invalido(entorno, valor):
    entorno.maximo = valor
    respuesta = _llamar(entorno, "POST", "/10/emails", NUEVO)
    assert respuesta.status_code == 503 and _code(respuesta) == "PARAMETRO_INVALIDO"
    assert not entorno.insertados


def test_baja_ok_y_repetida_404_sin_segunda_auditoria(entorno, eventos_auditados):
    entorno.activos = [_fila(7)]
    respuesta = _llamar(entorno, "DELETE", "/10/emails/7")
    assert respuesta.status_code == 204 and entorno.bajas == [(10, 7)]
    (his,) = entorno.historial
    assert his["tipo_operacion"] == "D" and his["campo"] == "EMAIL_SECUNDARIO.estado"
    assert (his["valor_anterior"], his["valor_nuevo"]) == ("Activo", "Eliminado")
    assert "7" in json.loads(his["observaciones"])["motivo"]
    assert len(eventos_auditados) == 1

    entorno.activos = []  # ya dado de baja (o de otro cliente)
    respuesta = _llamar(entorno, "DELETE", "/10/emails/7")
    assert respuesta.status_code == 404 and _code(respuesta) == "EMAIL_NO_ENCONTRADO"
    assert len(eventos_auditados) == 1 and len(entorno.historial) == 1


def test_verificar_secundario_inexistente(entorno):
    respuesta = _llamar(entorno, "POST", "/10/emails/99/verificacion")
    assert respuesta.status_code == 404 and _code(respuesta) == "EMAIL_NO_ENCONTRADO"


def test_verificar_principal_ok_y_ya_verificado(entorno, eventos_auditados):
    respuesta = _llamar(entorno, "POST", "/10/email/verificacion")
    assert respuesta.status_code == 200
    assert respuesta.json()["emailVerificado"] is True
    assert respuesta.json()["fechaEmailVerificado"].startswith("2026-11-24")
    (his,) = entorno.historial
    assert his["tipo_operacion"] == "U" and his["campo"] == "EMAIL.verificado"
    assert (his["valor_anterior"], his["valor_nuevo"]) == ("false", "true")
    assert eventos_auditados[0].tabla == "Clientes.Cliente"
    assert "principal@" not in eventos_auditados[0].descripcion.lower()

    entorno.principal = {"email": "p@example.com", "verificado_por": 3}
    respuesta = _llamar(entorno, "POST", "/10/email/verificacion")
    assert respuesta.status_code == 409 and _code(respuesta) == "EMAIL_YA_VERIFICADO"


def test_verificar_secundario_ok_y_ya_verificado(entorno):
    entorno.activos = [_fila(7)]
    respuesta = _llamar(entorno, "POST", "/10/emails/7/verificacion")
    assert respuesta.status_code == 200 and respuesta.json()["verificado"] is True
    assert entorno.historial[0]["campo"] == "EMAIL_SECUNDARIO.verificado"

    entorno.activos = [_fila(7, verificado=True)]
    respuesta = _llamar(entorno, "POST", "/10/emails/7/verificacion")
    assert respuesta.status_code == 409 and _code(respuesta) == "EMAIL_YA_VERIFICADO"


@pytest.mark.parametrize(
    "metodo,ruta,body",
    [
        ("POST", "/10/emails", NUEVO),
        ("DELETE", "/10/emails/7", None),
        ("POST", "/10/email/verificacion", None),
        ("POST", "/10/emails/7/verificacion", None),
    ],
)
def test_rol_sin_permiso_403(entorno, metodo, ruta, body):
    respuesta = _llamar(entorno, metodo, ruta, body, roles=("CAJERO",))
    assert respuesta.status_code == 403
    assert not entorno.insertados and not entorno.bajas and not entorno.historial


def test_lectura_sin_rol_de_consulta_403(entorno):
    respuesta = _llamar(entorno, "GET", "/10/emails", roles=("CONTADOR",))
    assert respuesta.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {**NUEVO, "creadoPor": 5},
        {**NUEVO, "etiqueta": "   "},
        {**NUEVO, "etiqueta": "a\tb"},
        {**NUEVO, "etiqueta": "x" * 31},
        {**NUEVO, "email": "sin-arroba"},
    ],
)
def test_body_invalido_400(entorno, body):
    respuesta = _llamar(entorno, "POST", "/10/emails", body)
    assert respuesta.status_code == 400 and _code(respuesta) == "DATOS_INVALIDOS"
    assert not entorno.insertados


@pytest.mark.parametrize("ruta", ["/0/emails", "/2147483648/emails"])
def test_id_fuera_de_rango_400(entorno, ruta):
    assert _llamar(entorno, "GET", ruta).status_code == 400


def test_error_bd_se_traduce_y_revierte(entorno, monkeypatch):
    from sqlalchemy.exc import DBAPIError

    def fallar(*args):
        raise DBAPIError(
            "INSERT DATO_PRIVADO",
            {},
            Exception("[23000] duplicado (2601) (SQLExecDirectW)"),
            False,
        )

    monkeypatch.setattr(correos, "insertar", fallar)
    respuesta = _llamar(entorno, "POST", "/10/emails", NUEVO)
    assert respuesta.status_code == 409 and _code(respuesta) == "REGISTRO_DUPLICADO"
    assert "DATO_PRIVADO" not in respuesta.text and entorno.conn.rollbacks == 1
