"""Lógica de #206: alta (POST) y cambio de estado (PATCH .../estado) de cuentas.

Sin BD: se monkeypatchea el repositorio y la conexión es un Mock con begin().
La auditoría queda en `eventos_auditados` (conftest).
"""

from decimal import Decimal
from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.database.db import cooperativa
from app.main import app
from app.modules.contabilidad import repository, service
from tests.sesion import simular_sesion, usuario_con_roles

_BASE = "/api/v1/contabilidad/cuentas-contables"

_ALTA = {
    "codigoCuenta": "14020599",
    "nombreCuenta": "Consumo prioritario prueba",
    "idCuentaSuperior": 9,
    "esImputable": True,
}


def _cuenta(**cambios):
    fila = {
        "id_cuenta_contable": 9,
        "codigo_cuenta": "1402",
        "nombre_cuenta": "Cartera de crédito de consumo por vencer",
        "naturaleza": "DEUDORA",
        "tipo_cuenta": "ACTIVO",
        "id_cuenta_superior": 5,
        "es_imputable": False,
        "saldo": Decimal("0.00"),
        "estado": True,
        "es_cuenta_valuacion": False,
    }
    return {**fila, **cambios}


_NUEVA = _cuenta(
    id_cuenta_contable=2000,
    codigo_cuenta="14020599",
    nombre_cuenta="Consumo prioritario prueba",
    id_cuenta_superior=9,
    es_imputable=True,
)


@pytest.fixture
def conn():
    conexion = MagicMock()
    conexion.begin.return_value.__enter__.return_value = None
    conexion.begin.return_value.__exit__.return_value = False
    return conexion


@pytest.fixture
def client(conn):
    app.dependency_overrides[cooperativa] = lambda: conn
    simular_sesion(app, usuario_con_roles("CONTADOR"))
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def repo(monkeypatch):
    """Repositorio falso: una cuenta padre (9) y registro de las escrituras."""
    estado = {
        "cuentas": {9: _cuenta()},
        "codigos": {"1402"},
        "insertados": [],
        "actualizados": [],
        "con_movimientos": set(),
        "desmarcados": [],
        "orden": [],
    }

    def _bloquear(conn, id_cuenta):
        return estado["cuentas"].get(id_cuenta)

    def _obtener(conn, id_cuenta):
        return estado["cuentas"].get(id_cuenta)

    def _existe(conn, codigo):
        return codigo in estado["codigos"]

    def _tiene_movimientos(conn, id_cuenta):
        return id_cuenta in estado["con_movimientos"]

    def _desmarcar(conn, id_cuenta):
        estado["orden"].append("desmarcar")
        estado["desmarcados"].append(id_cuenta)
        estado["cuentas"][id_cuenta] = {
            **estado["cuentas"][id_cuenta],
            "es_imputable": False,
        }
        return 1

    def _insertar(conn, datos):
        estado["orden"].append("insertar")
        estado["insertados"].append(datos)
        estado["cuentas"][2000] = _NUEVA
        return 2000

    def _actualizar(conn, id_cuenta, activa):
        estado["actualizados"].append((id_cuenta, activa))
        estado["cuentas"][id_cuenta] = {
            **estado["cuentas"][id_cuenta],
            "estado": activa,
        }
        return 1

    monkeypatch.setattr(repository, "bloquear_cuenta", _bloquear)
    monkeypatch.setattr(repository, "obtener_cuenta", _obtener)
    monkeypatch.setattr(repository, "existe_codigo", _existe)
    monkeypatch.setattr(repository, "tiene_movimientos", _tiene_movimientos)
    monkeypatch.setattr(repository, "desmarcar_imputable", _desmarcar)
    monkeypatch.setattr(repository, "insertar_cuenta", _insertar)
    monkeypatch.setattr(repository, "actualizar_estado_cuenta", _actualizar)
    return estado


def _error_bd(mensaje: str) -> DBAPIError:
    return IntegrityError("INSERT ...", {"codigo": "x"}, Exception(mensaje))


# ---------------------------------------------------------------------------
# POST /cuentas-contables
# ---------------------------------------------------------------------------


def test_alta_crea_la_cuenta_y_responde_201(client, conn, repo, eventos_auditados):
    r = client.post(_BASE, json=_ALTA)

    assert r.status_code == 201
    assert r.json() == {
        "idCuentaContable": 2000,
        "codigoCuenta": "14020599",
        "nombreCuenta": "Consumo prioritario prueba",
        "naturaleza": "DEUDORA",
        "tipoCuenta": "ACTIVO",
        "idCuentaSuperior": 9,
        "esImputable": True,
        "saldo": 0.0,
        "estado": "Activo",
    }
    assert repo["insertados"] == [
        {
            "codigo": "14020599",
            "nombre": "Consumo prioritario prueba",
            "naturaleza": "DEUDORA",
            "id_superior": 9,
            "imputable": 1,
            "valuacion": 0,
        }
    ]
    conn.begin.assert_called_once()
    (evento,) = eventos_auditados
    assert (evento.accion, evento.resultado) == ("CON_CUENTA_CREADA", "Exitoso")
    assert evento.tabla == "Contabilidad.CuentasContables"
    assert evento.id_registro == "2000"


def test_alta_hereda_naturaleza_y_valuacion_del_padre(client, repo):
    # Hija de una cuenta de valuación (p. ej. 1399, ACREEDORA dentro del activo)
    repo["cuentas"][9] = _cuenta(
        codigo_cuenta="1399", naturaleza="ACREEDORA", es_cuenta_valuacion=True
    )

    r = client.post(_BASE, json={**_ALTA, "codigoCuenta": "13990501"})

    assert r.status_code == 201
    (insertado,) = repo["insertados"]
    assert insertado["naturaleza"] == "ACREEDORA"
    assert insertado["valuacion"] == 1


def test_alta_no_imputable(client, repo):
    r = client.post(_BASE, json={**_ALTA, "esImputable": False})

    assert r.status_code == 201
    assert repo["insertados"][0]["imputable"] == 0


def test_alta_padre_inexistente_es_404(client, repo, eventos_auditados):
    r = client.post(_BASE, json={**_ALTA, "idCuentaSuperior": 404})

    assert r.status_code == 404
    assert r.json()["code"] == "CUENTA_SUPERIOR_NO_ENCONTRADA"
    assert repo["insertados"] == []
    (evento,) = eventos_auditados
    assert evento.resultado == "Fallido"
    assert "motivo=CUENTA_SUPERIOR_NO_ENCONTRADA" in evento.descripcion


@pytest.mark.parametrize(
    "codigo",
    [
        "15020599",  # no empieza con 1402
        "14030599",
        "1402",  # igual al padre
        "140205",  # empieza con el padre pero no es auxiliar (6 dígitos)
        "1402059",  # 7 dígitos
        "140205991",  # 9 dígitos
    ],
)
def test_alta_codigo_que_no_corresponde_es_422(client, repo, codigo):
    r = client.post(_BASE, json={**_ALTA, "codigoCuenta": codigo})

    assert r.status_code == 422
    assert r.json()["code"] == "CODIGO_NO_CORRESPONDE_AL_PADRE"
    assert codigo not in r.json()["detail"]
    assert repo["insertados"] == []


def test_alta_valida_el_prefijo_antes_que_el_largo(client, repo, monkeypatch):
    # Orden: padre -> prefijo -> largo -> duplicado. Un código ajeno y corto no
    # llega a consultar duplicados.
    existe = Mock(side_effect=AssertionError("no debe consultar duplicados"))
    monkeypatch.setattr(repository, "existe_codigo", existe)

    r = client.post(_BASE, json={**_ALTA, "codigoCuenta": "25"})

    assert r.status_code == 422
    existe.assert_not_called()


def test_nivel_auxiliar_es_ocho():
    assert service.NIVEL_AUXILIAR == 8


def test_alta_codigo_duplicado_es_409(client, repo):
    repo["codigos"].add("14020599")

    r = client.post(_BASE, json=_ALTA)

    assert r.status_code == 409
    assert r.json()["code"] == "CODIGO_DUPLICADO"
    assert repo["insertados"] == []


def test_alta_padre_imputable_sin_movimientos_se_desmarca_y_crea(
    client, conn, repo, eventos_auditados
):
    repo["cuentas"][9] = _cuenta(es_imputable=True)

    r = client.post(_BASE, json=_ALTA)

    assert r.status_code == 201
    assert r.json()["idCuentaContable"] == 2000
    assert repo["desmarcados"] == [9]
    assert repo["cuentas"][9]["es_imputable"] is False
    # Primero el padre deja de ser imputable; si no, el trigger rechaza la hija (51100)
    assert repo["orden"] == ["desmarcar", "insertar"]
    conn.begin.assert_called_once()  # padre e hija en la misma transacción
    (evento,) = eventos_auditados
    assert (evento.accion, evento.resultado) == ("CON_CUENTA_CREADA", "Exitoso")
    assert evento.id_registro == "2000"
    assert "padre_desmarcado=9" in evento.descripcion
    assert "padre_es_imputable=1->0" in evento.descripcion


@pytest.mark.parametrize(
    ("saldo", "con_movimientos"),
    [
        (Decimal("0.00"), True),
        (Decimal("150.25"), False),
        (Decimal("-3.10"), False),
        (Decimal("10.00"), True),
    ],
)
def test_alta_padre_imputable_con_movimientos_o_saldo_es_409(
    client, repo, eventos_auditados, saldo, con_movimientos
):
    repo["cuentas"][9] = _cuenta(es_imputable=True, saldo=saldo)
    if con_movimientos:
        repo["con_movimientos"].add(9)

    r = client.post(_BASE, json=_ALTA)

    assert r.status_code == 409
    assert r.json()["code"] == "CUENTA_SUPERIOR_CON_MOVIMIENTOS"
    assert r.json()["detail"] == "La cuenta superior tiene movimientos o saldo."
    assert str(saldo) not in r.json()["detail"]
    assert repo["desmarcados"] == [] and repo["insertados"] == []
    assert repo["cuentas"][9]["es_imputable"] is True
    (evento,) = eventos_auditados
    assert evento.resultado == "Fallido"
    assert "motivo=CUENTA_SUPERIOR_CON_MOVIMIENTOS" in evento.descripcion
    assert "padre_desmarcado" not in evento.descripcion


def test_alta_padre_ya_no_imputable_no_lo_toca(
    client, repo, monkeypatch, eventos_auditados
):
    movimientos = Mock(side_effect=AssertionError("no debe consultar movimientos"))
    desmarcar = Mock(side_effect=AssertionError("no debe tocar al padre"))
    monkeypatch.setattr(repository, "tiene_movimientos", movimientos)
    monkeypatch.setattr(repository, "desmarcar_imputable", desmarcar)

    r = client.post(_BASE, json=_ALTA)

    assert r.status_code == 201
    assert repo["cuentas"][9] == _cuenta()
    (evento,) = eventos_auditados
    assert "padre_desmarcado" not in evento.descripcion


def test_alta_valida_duplicado_antes_de_desmarcar(client, repo):
    repo["cuentas"][9] = _cuenta(es_imputable=True)
    repo["codigos"].add("14020599")

    r = client.post(_BASE, json=_ALTA)

    assert r.json()["code"] == "CODIGO_DUPLICADO"
    assert repo["desmarcados"] == []


@pytest.mark.parametrize(
    "mensaje",
    [
        "[23000] Violation of UNIQUE KEY constraint 'UQ_CuentasContables_Codigo'. (2627) (SQLExecDirectW)",
        "[23000] Cannot insert duplicate key row in object (2601) (SQLExecDirectW)",
    ],
)
def test_alta_carrera_con_indice_unico_es_409(client, repo, monkeypatch, mensaje):
    def _choca(conn, datos):
        raise _error_bd(mensaje)

    monkeypatch.setattr(repository, "insertar_cuenta", _choca)

    r = client.post(_BASE, json=_ALTA)

    assert r.status_code == 409
    assert r.json()["code"] == "CODIGO_DUPLICADO"
    assert "UQ_" not in r.json()["detail"]


@pytest.mark.parametrize(
    ("numero", "code"),
    [
        (51100, "DB_51100"),
        (56010, "CODIGO_NO_CORRESPONDE_AL_PADRE"),
    ],
)
def test_alta_errores_del_trigger_se_traducen(client, repo, monkeypatch, numero, code):
    def _trigger(conn, datos):
        raise _error_bd(f"[42000] Mensaje del trigger. ({numero}) (SQLExecDirectW)")

    monkeypatch.setattr(repository, "insertar_cuenta", _trigger)

    r = client.post(_BASE, json=_ALTA)

    assert r.status_code == 422
    assert r.json()["code"] == code
    assert "trigger" not in r.json()["detail"]


def test_alta_no_modifica_el_estado_del_padre(client, repo, monkeypatch):
    actualizar = Mock(side_effect=AssertionError("no debe tocar al padre"))
    monkeypatch.setattr(repository, "actualizar_estado_cuenta", actualizar)

    r = client.post(_BASE, json=_ALTA)

    assert r.status_code == 201
    assert repo["cuentas"][9] == _cuenta()


# ---------------------------------------------------------------------------
# PATCH /cuentas-contables/{id}/estado
# ---------------------------------------------------------------------------


def test_desactivar_sin_saldo_responde_200(client, conn, repo, eventos_auditados):
    r = client.patch(f"{_BASE}/9/estado", json={"estado": "Inactivo"})

    assert r.status_code == 200
    assert r.json()["estado"] == "Inactivo"
    assert r.json()["idCuentaContable"] == 9
    assert repo["actualizados"] == [(9, False)]
    conn.begin.assert_called_once()
    (evento,) = eventos_auditados
    assert (evento.accion, evento.resultado) == ("CON_CUENTA_ESTADO", "Exitoso")
    assert evento.id_registro == "9"


def test_desactivar_con_saldo_es_409(client, repo, eventos_auditados):
    repo["cuentas"][9] = _cuenta(saldo=Decimal("8013.00"))

    r = client.patch(f"{_BASE}/9/estado", json={"estado": "Inactivo"})

    assert r.status_code == 409
    assert r.json()["code"] == "CUENTA_CON_SALDO"
    assert "8013" not in r.json()["detail"]
    assert repo["actualizados"] == []
    assert eventos_auditados[0].resultado == "Fallido"


def test_desactivar_con_saldo_negativo_es_409(client, repo):
    repo["cuentas"][9] = _cuenta(saldo=Decimal("-0.01"))

    r = client.patch(f"{_BASE}/9/estado", json={"estado": "Inactivo"})

    assert r.status_code == 409
    assert r.json()["code"] == "CUENTA_CON_SALDO"


def test_activar_con_saldo_no_tiene_bloqueo(client, repo):
    repo["cuentas"][9] = _cuenta(estado=False, saldo=Decimal("10.00"))

    r = client.patch(f"{_BASE}/9/estado", json={"estado": "Activo"})

    assert r.status_code == 200
    assert r.json()["estado"] == "Activo"
    assert repo["actualizados"] == [(9, True)]


@pytest.mark.parametrize(("bit", "estado"), [(True, "Activo"), (False, "Inactivo")])
def test_mismo_estado_responde_200_sin_escribir(
    client, repo, eventos_auditados, bit, estado
):
    # Con saldo: aun así "Inactivo" sobre una inactiva no es un 409, no cambia nada
    repo["cuentas"][9] = _cuenta(estado=bit, saldo=Decimal("5.00"))

    r = client.patch(f"{_BASE}/9/estado", json={"estado": estado})

    assert r.status_code == 200
    assert r.json()["estado"] == estado
    assert repo["actualizados"] == []
    assert "sin_cambio" in eventos_auditados[0].descripcion


def test_estado_cuenta_inexistente_es_404(client, repo):
    r = client.patch(f"{_BASE}/404/estado", json={"estado": "Inactivo"})

    assert r.status_code == 404
    assert r.json()["code"] == "CUENTA_NO_ENCONTRADA"
    assert "404" not in r.json()["detail"]


def test_check_de_saldo_de_la_bd_es_409(client, repo, monkeypatch):
    # Si el saldo cambió entre la lectura y el UPDATE, el CHECK de la BD responde
    def _check(conn, id_cuenta, activa):
        raise _error_bd(
            "[23000] The UPDATE statement conflicted with the CHECK constraint "
            '"CK_CuentasContables_InactivaSinSaldo". (547) (SQLExecDirectW)'
        )

    monkeypatch.setattr(repository, "actualizar_estado_cuenta", _check)

    r = client.patch(f"{_BASE}/9/estado", json={"estado": "Inactivo"})

    assert r.status_code == 409
    assert r.json()["code"] == "CUENTA_CON_SALDO"


def test_error_de_bd_no_previsto_es_500_generico(client, repo, monkeypatch):
    def _falla(conn, id_cuenta, activa):
        raise _error_bd("[08S01] Communication link failure (10054) (SQLExecDirectW)")

    monkeypatch.setattr(repository, "actualizar_estado_cuenta", _falla)

    r = client.patch(f"{_BASE}/9/estado", json={"estado": "Inactivo"})

    assert r.status_code == 500
    assert r.json()["code"] == "ERROR_INTERNO"


# ---------------------------------------------------------------------------
# Roles y repositorio
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rol", ["AUDITOR", "ADMIN"])
def test_solo_contador_escribe(client, repo, rol):
    simular_sesion(app, usuario_con_roles(rol))

    alta = client.post(_BASE, json=_ALTA)
    estado = client.patch(f"{_BASE}/9/estado", json={"estado": "Inactivo"})

    assert (alta.status_code, estado.status_code) == (403, 403)
    assert repo["insertados"] == [] and repo["actualizados"] == []


def test_repositorio_inserta_parametrizado_con_estado_y_saldo_fijos():
    conn = Mock()
    conn.execute.return_value.scalar_one.return_value = 2000

    datos = {
        "codigo": "14020599",
        "nombre": "x'); DROP TABLE y; --",
        "naturaleza": "DEUDORA",
        "id_superior": 9,
        "imputable": 1,
        "valuacion": 0,
    }
    assert repository.insertar_cuenta(conn, datos) == 2000

    sql, params = str(conn.execute.call_args.args[0]), conn.execute.call_args.args[1]
    assert "DROP TABLE" not in sql
    assert params == datos
    assert "0, 1, :imputable, :valuacion" in sql  # Saldo = 0, Estado = 1
    assert "CodigoElemento" not in sql and "TipoCuenta" not in sql  # calculadas


def test_repositorio_bloquea_padre_y_codigo():
    conn = Mock()
    conn.execute.return_value.mappings.return_value.first.return_value = None

    repository.bloquear_cuenta(conn, 9)
    bloqueo = str(conn.execute.call_args.args[0])
    repository.existe_codigo(conn, "14020599")
    codigo = str(conn.execute.call_args.args[0])

    assert "WITH (UPDLOCK, HOLDLOCK)" in bloqueo
    assert "WITH (UPDLOCK, HOLDLOCK)" in codigo
    assert conn.execute.call_args.args[1] == {"codigo": "14020599"}


def test_repositorio_movimientos_y_desmarcar_parametrizados():
    conn = Mock()
    conn.execute.return_value.mappings.return_value.first.return_value = None
    conn.execute.return_value.rowcount = 1

    assert repository.tiene_movimientos(conn, 9) is False
    movimientos, p_mov = (
        str(conn.execute.call_args.args[0]),
        conn.execute.call_args.args[1],
    )
    assert repository.desmarcar_imputable(conn, 9) == 1
    desmarcar, p_des = (
        str(conn.execute.call_args.args[0]),
        conn.execute.call_args.args[1],
    )

    assert "Contabilidad.MovimientosContables WITH (HOLDLOCK)" in movimientos
    assert p_mov == {"id": 9} and p_des == {"id": 9}
    assert "SET EsImputable = 0" in desmarcar
    assert "WHERE IdCuentaContable = :id AND EsImputable = 1" in desmarcar
