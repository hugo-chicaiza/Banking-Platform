"""ORG-01 (POST) y ORG-02 (PATCH) de agencias, sin BD.

El repositorio se reemplaza por un almacén en memoria que imita las restricciones reales
de Organizacion.Agencia (PK, UQ_Agencia_Codigo, UX_Agencia_KeyAgencia,
UX_Agencia_UnaMatriz, FK a Catalogo.Ciudad).
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.core.database.db import cooperativa
from app.core.security import audit
from app.modules.organizacion import repository as repo
from app.modules.organizacion import service
from app.modules.organizacion.router import router
from tests.sesion import ID_AUDITORIA, USUARIO, simular_sesion, usuario_con_roles


def _codigo_json(respuesta: Any) -> str:
    return str(respuesta.json()["code"])


def _codigo(exc: Any) -> str:
    detalle: Any = exc.detail
    return str(detalle["code"])


BASE = "https://testserver/api/v1/agencias"
CREADA = datetime(2026, 11, 12, 9, 0)


def _fila(
    id_agencia: str, codigo: str, tipo: str = "Sucursal", **otros: Any
) -> dict[str, Any]:
    return {
        "IdAgencia": id_agencia,
        "Codigo": codigo,
        "TipoAgencia": tipo,
        "Estado": "A",
        "IdCiudad": 1,
        "Telefono": None,
        "Direccion": None,
        "FechaCreacion": CREADA,
        "KeyAgencia": None,
        **otros,
    }


@dataclass
class BdFalsa:
    agencias: dict[str, dict[str, Any]] = field(default_factory=dict)
    ciudades: set[int] = field(default_factory=lambda: {1, 2})
    activas: dict[str, list[str]] = field(default_factory=dict)
    actualizaciones: list[dict[str, Any]] = field(default_factory=list)
    error_en_escritura: Exception | None = None

    def leer(self, _conn: Any, id_agencia: str, *, bloquear: bool = False) -> Any:
        fila = self.agencias.get(id_agencia)
        if fila is None:
            return None
        return {**fila, "VinculadaWorkos": fila["KeyAgencia"] is not None}

    def ciudad(self, _conn: Any, id_ciudad: int) -> bool:
        return id_ciudad in self.ciudades

    def conflictos(
        self,
        _conn: Any,
        *,
        id_agencia: str,
        codigo: Any,
        key_agencia: Any,
        matriz: bool,
    ) -> set[str]:
        otras = [a for k, a in self.agencias.items() if k != id_agencia]
        resultado = set()
        if codigo is not None and any(a["Codigo"] == codigo for a in otras):
            resultado.add("Codigo")
        if key_agencia is not None and any(
            a["KeyAgencia"] == key_agencia for a in otras
        ):
            resultado.add("KeyAgencia")
        if matriz and any(a["TipoAgencia"] == "Matriz" for a in otras):
            resultado.add("Matriz")
        return resultado

    def insertar(self, _conn: Any, datos: dict[str, Any]) -> None:
        if self.error_en_escritura is not None:
            raise self.error_en_escritura
        self.agencias[datos["id_agencia"]] = _fila(
            datos["id_agencia"],
            datos["codigo"],
            datos["tipo_agencia"],
            IdCiudad=datos["id_ciudad"],
            Telefono=datos["telefono"],
            Direccion=datos["direccion"],
            KeyAgencia=datos["key_agencia"],
        )

    def actualizar(self, _conn: Any, id_agencia: str, cambios: dict[str, Any]) -> int:
        if self.error_en_escritura is not None:
            raise self.error_en_escritura
        self.actualizaciones.append(cambios)
        fila = self.agencias.get(id_agencia)
        if fila is None:
            return 0
        for campo, valor in cambios.items():
            fila[repo.COLUMNAS_EDITABLES[campo]] = valor
        return 1

    def dependencias(self, _conn: Any, id_agencia: str) -> list[str]:
        return self.activas.get(id_agencia, [])


@pytest.fixture
def bd(monkeypatch: pytest.MonkeyPatch) -> BdFalsa:
    falsa = BdFalsa(
        agencias={
            "001": _fila("001", "MTZ-UIO", "Matriz", KeyAgencia="org_MATRIZ"),
            "002": _fila("002", "SUC-SGQ", KeyAgencia="org_SGQ"),
            "003": _fila("003", "SUC-GYE", Estado="I"),
            "004": _fila("004", "SUC-CUE", Estado="C"),
        }
    )
    monkeypatch.setattr(repo, "obtener_agencia", falsa.leer)
    monkeypatch.setattr(repo, "existe_ciudad", falsa.ciudad)
    monkeypatch.setattr(repo, "conflictos_de_unicidad", falsa.conflictos)
    monkeypatch.setattr(repo, "insertar_agencia", falsa.insertar)
    monkeypatch.setattr(repo, "actualizar_agencia", falsa.actualizar)
    monkeypatch.setattr(repo, "dependencias_activas", falsa.dependencias)
    return falsa


@pytest.fixture
def conn() -> MagicMock:
    return MagicMock()


@pytest.fixture
def app(conn: MagicMock) -> Iterator[FastAPI]:
    aplicacion = FastAPI()
    aplicacion.include_router(router, prefix="/api/v1")
    aplicacion.dependency_overrides[cooperativa] = lambda: conn
    simular_sesion(aplicacion, usuario_con_roles("ADMIN"))
    yield aplicacion


@pytest.fixture
def cliente(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def eventos(monkeypatch: pytest.MonkeyPatch) -> list[audit.EventoAuditoria]:
    lista: list[audit.EventoAuditoria] = []
    monkeypatch.setattr(audit, "registrar", lista.append)
    return lista


NUEVA = {
    "idAgencia": "005",
    "codigo": "SUC-AMB",
    "tipoAgencia": "Sucursal",
    "idCiudad": 2,
    "telefono": "032 123 456",
    "direccion": "Av. Cevallos y Montalvo",
}


# --- ORG-01 · creación --------------------------------------------------------------


def test_crea_agencia_activa(cliente, bd, conn, eventos) -> None:
    r = cliente.post(BASE, json={**NUEVA, "keyAgencia": "org_01AMBATO"})

    assert r.status_code == 201, r.text
    assert r.json() == {
        "idAgencia": "005",
        "codigo": "SUC-AMB",
        "tipoAgencia": "Sucursal",
        "estado": "A",
        "idCiudad": 2,
        "telefono": "032 123 456",
        "direccion": "Av. Cevallos y Montalvo",
        "fechaCreacion": "2026-11-12T09:00:00-05:00",
        "vinculadaWorkos": True,
    }
    assert "keyAgencia" not in r.json()  # el valor no se publica
    conn.commit.assert_called_once()
    evento = eventos[-1]
    assert (evento.accion, evento.tabla, evento.id_registro, evento.resultado) == (
        "INSERT",
        "Organizacion.Agencia",
        "005",
        "Exitoso",
    )
    assert evento.usuario == ID_AUDITORIA
    assert "org_01AMBATO" not in evento.descripcion
    assert "workos=True" in evento.descripcion


def test_campos_opcionales_pueden_omitirse(cliente, bd) -> None:
    r = cliente.post(
        BASE,
        json={
            "idAgencia": "006",
            "codigo": "SUC-LOJ",
            "tipoAgencia": "Sucursal",
            "idCiudad": 1,
        },
    )

    assert r.status_code == 201, r.text
    assert r.json()["telefono"] is None
    assert r.json()["vinculadaWorkos"] is False


@pytest.mark.parametrize(
    ("cambios", "codigo"),
    [
        ({"idAgencia": "002"}, "AGENCIA_YA_EXISTE"),
        ({"codigo": "SUC-SGQ"}, "CODIGO_DUPLICADO"),
        ({"keyAgencia": "org_SGQ"}, "KEY_AGENCIA_DUPLICADA"),
        ({"tipoAgencia": "Matriz"}, "MATRIZ_YA_EXISTE"),
    ],
)
def test_crear_duplicados_409(cliente, bd, conn, eventos, cambios, codigo) -> None:
    r = cliente.post(BASE, json={**NUEVA, **cambios})

    assert r.status_code == 409
    assert r.json()["code"] == codigo
    assert "005" not in bd.agencias
    conn.commit.assert_not_called()
    conn.rollback.assert_called()
    assert eventos[-1].resultado == "Fallido"


def test_ciudad_inexistente_422(cliente, bd) -> None:
    r = cliente.post(BASE, json={**NUEVA, "idCiudad": 99})

    assert r.status_code == 422
    assert r.json()["code"] == "CIUDAD_NO_ENCONTRADA"


@pytest.mark.parametrize(
    "cambios",
    [
        {"idAgencia": "05"},
        {"idAgencia": "0055"},
        {"idAgencia": "a05"},
        {"codigo": ""},
        {"codigo": "SUC-AMBATO-1"},
        {"codigo": "suc amb"},
        {"tipoAgencia": "Oficina"},
        {"idCiudad": 0},
        {"idCiudad": 2_147_483_648},
        {"telefono": "12"},
        {"telefono": "abc-def-ghi"},
        {"direccion": "x" * 251},
        {"direccion": "linea\nnueva"},
        {"keyAgencia": "user_01X"},
        {"keyAgencia": "org_" + "A" * 61},
        {"estado": "A"},
        {"fechaCreacion": "2026-01-01T00:00:00"},
        {"id_agencia": "007"},
    ],
)
def test_crear_con_datos_invalidos_400(cliente, bd, cambios) -> None:
    r = cliente.post(BASE, json={**NUEVA, **cambios})

    assert r.status_code == 400, r.text
    assert r.json()["code"] == "DATOS_INVALIDOS"
    assert "005" not in bd.agencias and "007" not in bd.agencias


@pytest.mark.parametrize("campo", ["idAgencia", "codigo", "tipoAgencia", "idCiudad"])
def test_crear_sin_obligatorio_400(cliente, bd, campo) -> None:
    cuerpo = {k: v for k, v in NUEVA.items() if k != campo}

    assert cliente.post(BASE, json=cuerpo).status_code == 400


def test_carrera_perdida_en_el_indice_devuelve_409(cliente, bd) -> None:
    """Otra transacción creó la Matriz entre la verificación y el INSERT."""
    del bd.agencias["001"]
    bd.error_en_escritura = _error_sql(
        "Cannot insert duplicate key row in object 'Organizacion.Agencia' with unique"
        " index 'UX_Agencia_UnaMatriz'. The duplicate key value is (Matriz). (2601)"
        " (SQLExecDirectW)"
    )

    r = cliente.post(BASE, json={**NUEVA, "tipoAgencia": "Matriz"})

    assert r.status_code == 409
    assert r.json()["code"] == "MATRIZ_YA_EXISTE"
    assert "Matriz)" not in r.text


# --- ORG-02 · actualización parcial ---------------------------------------------------


def _patch(cliente: TestClient, id_agencia: str, cuerpo: dict[str, Any]) -> Any:
    return cliente.patch(f"{BASE}/{id_agencia}", json=cuerpo)


def test_patch_parcial_solo_cambia_lo_enviado(cliente, bd, conn, eventos) -> None:
    r = _patch(cliente, "002", {"telefono": "022 999 888", "direccion": None})

    assert r.status_code == 200, r.text
    assert bd.actualizaciones == [{"telefono": "022 999 888"}]  # direccion ya era NULL
    assert r.json()["codigo"] == "SUC-SGQ"
    conn.commit.assert_called_once()
    assert eventos[-1].descripcion.startswith("ORG02 telefono=None->022 999 888")


def test_patch_borra_opcional_con_null(cliente, bd) -> None:
    bd.agencias["002"]["Direccion"] = "Calle 1"

    r = _patch(cliente, "002", {"direccion": None})

    assert r.status_code == 200
    assert bd.agencias["002"]["Direccion"] is None


def test_patch_sin_cambios_reales_no_escribe(cliente, bd, conn, eventos) -> None:
    r = _patch(cliente, "002", {"codigo": "SUC-SGQ"})

    assert r.status_code == 200
    assert bd.actualizaciones == []
    conn.commit.assert_not_called()
    assert eventos == []


@pytest.mark.parametrize(
    "cuerpo",
    [
        {},
        {"motivo": "solo motivo"},
        {"idAgencia": "009"},
        {"fechaCreacion": "2026-01-01T00:00:00"},
        {"codigo": None},
        {"tipoAgencia": None},
        {"idCiudad": None},
        {"estado": None, "motivo": "x"},
        {"estado": "I"},
        {"estado": "C", "motivo": "cierre"},
        {"estado": "X", "motivo": "x"},
        {"motivo": "\u0007"},
    ],
)
def test_patch_invalido_400(cliente, bd, cuerpo) -> None:
    r = _patch(cliente, "002", cuerpo)

    assert r.status_code == 400, r.text
    assert bd.actualizaciones == []


def test_patch_ruta_con_id_mal_formado_400(cliente, bd) -> None:
    assert _patch(cliente, "1", {"telefono": "022 999 888"}).status_code == 400


def test_patch_agencia_inexistente_404(cliente, bd) -> None:
    r = _patch(cliente, "999", {"telefono": "022 999 888"})

    assert r.status_code == 404
    assert r.json()["code"] == "AGENCIA_NO_ENCONTRADA"


@pytest.mark.parametrize(
    ("cambios", "codigo"),
    [
        ({"codigo": "MTZ-UIO"}, "CODIGO_DUPLICADO"),
        ({"keyAgencia": "org_MATRIZ"}, "KEY_AGENCIA_DUPLICADA"),
        ({"tipoAgencia": "Matriz"}, "MATRIZ_YA_EXISTE"),
    ],
)
def test_patch_unicidad_409(cliente, bd, cambios, codigo) -> None:
    r = _patch(cliente, "002", cambios)

    assert r.status_code == 409
    assert r.json()["code"] == codigo
    assert bd.actualizaciones == []


def test_sucursal_pasa_a_matriz_si_no_hay_otra(cliente, bd) -> None:
    bd.agencias["001"]["TipoAgencia"] = "Sucursal"

    r = _patch(cliente, "002", {"tipoAgencia": "Matriz"})

    assert r.status_code == 200
    assert r.json()["tipoAgencia"] == "Matriz"


@pytest.mark.parametrize(
    ("id_agencia", "cuerpo"),
    [
        ("003", {"tipoAgencia": "Matriz"}),  # inactiva promovida a Matriz
        ("002", {"tipoAgencia": "Matriz", "estado": "I", "motivo": "x"}),
    ],
)
def test_una_matriz_inactiva_no_se_permite(cliente, bd, id_agencia, cuerpo) -> None:
    bd.agencias["001"]["TipoAgencia"] = "Sucursal"

    r = _patch(cliente, id_agencia, cuerpo)

    assert r.status_code == 409
    assert _codigo_json(r) == "MATRIZ_NO_DESACTIVABLE"
    assert bd.actualizaciones == []


def test_matriz_no_pasa_a_sucursal(cliente, bd) -> None:
    r = _patch(cliente, "001", {"tipoAgencia": "Sucursal"})

    assert r.status_code == 409
    assert r.json()["code"] == "CAMBIO_MATRIZ_NO_PERMITIDO"


def test_patch_ciudad_inexistente_422(cliente, bd) -> None:
    r = _patch(cliente, "002", {"idCiudad": 77})

    assert r.status_code == 422
    assert r.json()["code"] == "CIUDAD_NO_ENCONTRADA"


def test_patch_quita_vinculo_workos_sin_registrar_el_valor(
    cliente, bd, eventos
) -> None:
    r = _patch(cliente, "002", {"keyAgencia": None})

    assert r.status_code == 200
    assert r.json()["vinculadaWorkos"] is False
    assert "org_SGQ" not in eventos[-1].descripcion
    assert "keyAgencia=vinculadaWorkos:True->False" in eventos[-1].descripcion


# --- ORG-02 · desactivación y reactivación --------------------------------------------

DESACTIVAR = {"estado": "I", "motivo": "Cierre de la sucursal aprobado"}


def test_desactiva_sucursal_sin_actividad(cliente, bd, conn, eventos) -> None:
    r = _patch(cliente, "002", DESACTIVAR)

    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "I"
    assert bd.actualizaciones == [{"estado": "I"}]
    conn.commit.assert_called_once()
    descripcion = eventos[-1].descripcion
    assert descripcion.startswith("ORG02 estado=A->I")
    assert descripcion.endswith("motivo=Cierre de la sucursal aprobado")


def test_desactivar_bloqueado_por_actividad_real(cliente, bd, conn, eventos) -> None:
    bd.activas["002"] = ["jornadas abiertas", "cuentas activas"]

    r = _patch(cliente, "002", DESACTIVAR)

    assert r.status_code == 409
    assert r.json()["code"] == "AGENCIA_CON_ACTIVIDAD"
    assert "jornadas abiertas, cuentas activas" in r.json()["detail"]
    assert bd.actualizaciones == []
    conn.commit.assert_not_called()
    assert eventos[-1].resultado == "Fallido"
    assert "motivo=Cierre" in eventos[-1].descripcion


def test_no_desactiva_la_matriz(cliente, bd) -> None:
    r = _patch(cliente, "001", DESACTIVAR)

    assert r.status_code == 409
    assert r.json()["code"] == "MATRIZ_NO_DESACTIVABLE"


def test_desactivar_dos_veces_es_idempotente(cliente, bd, conn) -> None:
    r = _patch(cliente, "003", DESACTIVAR)

    assert r.status_code == 200
    assert r.json()["estado"] == "I"
    assert bd.actualizaciones == []
    conn.commit.assert_not_called()


def test_reactiva_agencia_inactiva(cliente, bd) -> None:
    r = _patch(cliente, "003", {"estado": "A", "motivo": "Reapertura"})

    assert r.status_code == 200
    assert r.json()["estado"] == "A"


def test_agencia_en_estado_c_no_se_modifica(cliente, bd) -> None:
    r = _patch(cliente, "004", {"telefono": "022 999 888"})

    assert r.status_code == 409
    assert r.json()["code"] == "ESTADO_NO_HABILITADO"


def test_desactivar_y_editar_en_la_misma_peticion(cliente, bd) -> None:
    r = _patch(cliente, "002", {**DESACTIVAR, "telefono": "022 111 222"})

    assert r.status_code == 200
    assert bd.actualizaciones == [{"estado": "I", "telefono": "022 111 222"}]


def test_update_sin_filas_afectadas_404(cliente, bd, conn, monkeypatch) -> None:
    """El UPDATE no afectó filas: no se confirma nada."""
    monkeypatch.setattr(repo, "actualizar_agencia", lambda *_a: 0)

    r = _patch(cliente, "002", {"telefono": "022 111 222"})

    assert r.status_code == 404
    conn.commit.assert_not_called()


# --- Autorización ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "roles", [("SUPERVISOR",), ("CAJERO",), ("ASESOR",), ("AUDITOR", "CONTADOR")]
)
def test_solo_admin(app, bd, roles) -> None:
    simular_sesion(app, usuario_con_roles(*roles))
    cliente = TestClient(app, raise_server_exceptions=False)

    assert cliente.post(BASE, json=NUEVA).status_code == 403
    assert _patch(cliente, "002", DESACTIVAR).status_code == 403
    assert bd.actualizaciones == [] and "005" not in bd.agencias


def test_admin_no_registrado_403(app, bd) -> None:
    from dataclasses import replace

    simular_sesion(app, replace(USUARIO, roles=("ADMIN",), id_interno=None))
    cliente = TestClient(app, raise_server_exceptions=False)

    r = cliente.post(BASE, json=NUEVA)

    assert r.status_code == 403
    assert r.json()["code"] == "USUARIO_NO_REGISTRADO"


def test_sin_sesion_401(bd, conn) -> None:
    aplicacion = FastAPI()
    aplicacion.include_router(router, prefix="/api/v1")
    aplicacion.dependency_overrides[cooperativa] = lambda: conn
    cliente = TestClient(aplicacion, raise_server_exceptions=False)

    assert cliente.post(BASE, json=NUEVA).status_code == 401


def test_parametros_de_consulta_desconocidos_400(cliente, bd) -> None:
    assert cliente.post(f"{BASE}?forzar=1", json=NUEVA).status_code == 400


# --- Traducción de errores de SQL ------------------------------------------------------


def _error_sql(mensaje: str) -> DBAPIError:
    return DBAPIError("INSERT ...", {"codigo": "SECRETO"}, Exception(mensaje))


@pytest.mark.parametrize(
    ("restriccion", "numero", "status", "codigo"),
    [
        ("PK_Agencia", 2627, 409, "AGENCIA_YA_EXISTE"),
        ("UQ_Agencia_Codigo", 2627, 409, "CODIGO_DUPLICADO"),
        ("UX_Agencia_KeyAgencia", 2601, 409, "KEY_AGENCIA_DUPLICADA"),
        ("UX_Agencia_UnaMatriz", 2601, 409, "MATRIZ_YA_EXISTE"),
        ("FK_Agencia_Ciudad", 547, 422, "CIUDAD_NO_ENCONTRADA"),
        ("CK_Agencia_Estado", 547, 422, "ESTADO_INVALIDO"),
        ("CK_Agencia_Tipo", 547, 422, "TIPO_AGENCIA_INVALIDO"),
    ],
)
def test_traduce_restricciones_sin_filtrar_valores(
    restriccion, numero, status, codigo
) -> None:
    exc = _error_sql(
        f"Violation of constraint '{restriccion}'. Value is (dato-sensible). "
        f"({numero}) (SQLExecDirectW)"
    )

    resultado = service.traducir_error_agencia(exc)

    assert resultado.status_code == status
    assert _codigo(resultado) == codigo
    assert "dato-sensible" not in str(resultado.detail)


def test_otro_error_de_bd_usa_el_traductor_comun() -> None:
    exc = _error_sql("Deadlock victim (1205) (SQLExecDirectW)")

    resultado = service.traducir_error_agencia(exc)

    assert resultado.status_code == 500
    assert _codigo(resultado) == "ERROR_INTERNO"


# --- Repositorio: SQL fijo y dependencias ---------------------------------------------


def test_update_rechaza_campos_no_editables() -> None:
    with pytest.raises(ValueError, match="no editables"):
        repo.actualizar_agencia(MagicMock(), "002", {"id_agencia": "003"})


def test_update_usa_sql_fijo_con_banderas() -> None:
    conexion = MagicMock()
    conexion.execute.return_value.rowcount = 1

    assert repo.actualizar_agencia(conexion, "002", {"estado": "I"}) == 1

    sentencia, parametros = conexion.execute.call_args.args
    sql = str(sentencia)
    assert "IdAgencia =" not in sql.split("WHERE")[0]  # IdAgencia nunca se asigna
    assert "FechaCreacion" not in sql
    assert parametros["con_estado"] == 1 and parametros["estado"] == "I"
    assert parametros["con_codigo"] == 0 and parametros["id_agencia_actual"] == "002"


def test_lectura_bloqueada_para_patch() -> None:
    conexion = MagicMock()
    conexion.execute.return_value.mappings.return_value.first.return_value = None

    repo.obtener_agencia(conexion, "002", bloquear=True)

    assert "UPDLOCK, HOLDLOCK" in str(conexion.execute.call_args.args[0])


def test_dependencias_solo_recursos_activos() -> None:
    sql = repo.DEPENDENCIAS_ACTIVAS
    assert "Estado = 'ABIERTA'" in sql["jornadas abiertas"]
    assert "Estado = 1" in sql["cajas físicas activas"]
    assert "FechaFin IS NULL" in sql["cajeros asignados vigentes"]
    assert "Estado = 'Activa'" in sql["cuentas activas"]
    assert "Estado = 'PENDIENTE'" in sql["desembolsos de crédito pendientes"]
    assert all("HOLDLOCK" in consulta for consulta in sql.values())
    # Historial (Transaccion, asientos, movimientos) no bloquea la desactivación
    assert not any(
        tabla in " ".join(sql.values())
        for tabla in ("Transacciones.Transaccion", "Contabilidad.", "MovimientosCaja")
    )


def test_dependencias_devuelve_las_que_tienen_filas() -> None:
    conexion = MagicMock()
    resultados = iter([(1,), None, None, None, (1,), None, None])
    conexion.execute.return_value.first.side_effect = lambda: next(resultados)

    assert repo.dependencias_activas(conexion, "002") == [
        "jornadas abiertas",
        "ATM activos",
    ]
