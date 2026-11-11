"""ATM-02 local: HTTP, JWT y dependencias reales, persistencia transaccional doble.

No ejecuta T-SQL ni demuestra concurrencia SQL Server. La fixture compartida
prohíbe conexiones SQL y red externa y usa una clave RSA efímera.
"""

import copy
import hashlib
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Lock, RLock
from types import SimpleNamespace

import pyodbc
import pytest
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.modules.atm import router, saldo_service, session, terminal_auth
from app.modules.atm.saldo_service import numeracion, repo, repository
from tests.integration import test_atm_pin_version_local as pin_helpers
from tests.pin_version import FECHA_PIN, DriverLimitesSQL

RUTA = "/api/v1/atm/consulta-saldo"
BODY = {"idCuenta": 501, "registroUnico": "SALDOLAB0001"}
pin_lab = pin_helpers.lab
headers = pin_helpers.headers


class Almacen:
    def __init__(self):
        self.lock = RLock()
        self.rows = {}
        self.pool = []
        self.pool_lock = Lock()
        self.historial_credito = []
        self.credito_activo = False
        self.commits = 0
        self.rollbacks = 0
        self.fallo = None
        self.cuenta = {
            "IdCuenta": 501,
            "IdAgencia": "002",
            "Estado": "Activa",
            "Saldo": Decimal("100.25"),
            "SaldoRetenido": Decimal("20.15"),
            "TipoCuenta": "Ahorro",
            "Ahora": datetime(2026, 11, 8, 12),
        }

    @contextmanager
    def connect(self):
        with self.pool_lock:
            conn = self.pool.pop() if self.pool else ConexionAlmacen(self)
        try:
            yield conn
        finally:
            if not conn.invalidated:
                with self.pool_lock:
                    self.pool.append(conn)

    @contextmanager
    def begin(self):
        with self.lock:
            antes = copy.deepcopy(self.rows)
            credito_antes = self.credito_activo
            historial_antes = copy.deepcopy(self.historial_credito)
            confirmado = False
            try:
                yield self
                if self.fallo == "commit":
                    raise SQLAlchemyError("COMMIT SECRETO")
                self.commits += 1
                confirmado = True
                if self.fallo == "ack":
                    raise SQLAlchemyError("ACK SECRETO")
            except BaseException:
                if not confirmado:
                    self.rows = antes
                    self.credito_activo = credito_antes
                    self.historial_credito = historial_antes
                self.rollbacks += 1
                raise

    def insertar(self, conn, datos):
        # Efecto de sesión del batch real, sin ejecutar T-SQL.
        conn.connection.driver_connection.nocount = True
        if self.fallo == "insert":
            raise SQLAlchemyError("INSERT SECRETO")
        if self.fallo in ("timeout", "lock_timeout"):
            state = "HYT00" if self.fallo == "timeout" else "HY000"
            raise DBAPIError("lab", None, pyodbc.Error(state, "TIMEOUT SECRETO"))
        assert datos["registro"] not in self.rows
        assert datos["procesamiento"] in ("311000", "312000")
        row = {
            "IdTransaccion": len(self.rows) + 1,
            "NumeroComprobante": datos["comprobante"],
            "TipoTransaccion": "Consulta",
            "TipoOperacion": "Normal",
            "MTI": "0200",
            "IdCuenta": datos["cuenta"],
            "IdTarjeta": datos["tarjeta"],
            "IdATM": datos["atm"],
            "IdCanal": datos["canal"],
            "Monto": Decimal(0),
            "CodigoProcesamiento": datos["procesamiento"],
            "CodigoRespuesta": datos["respuesta"],
            "Estado": datos["estado"],
            "FechaHoraSistema": datos["ahora"],
            "STAN": datos["stan"],
            "RRN": datos["rrn"],
            "Secuencial": datos["secuencial"],
            "CreadoPor": datos["usuario"],
            "FechaSistema": datos["ahora"].date(),
        }
        self.rows[datos["registro"]] = row
        return row["IdTransaccion"]


class ConexionAlmacen:
    """Conexión ODBC doble independiente; el pool conserva su estado de sesión."""

    def __init__(self, store):
        self.store = store
        self.connection = SimpleNamespace(driver_connection=DriverLimitesSQL())
        self.invalidated = False

    def begin(self):
        return self.store.begin()

    def rollback(self):
        pass  # begin() ya restaura el snapshot transaccional al salir con error.

    def invalidate(self):
        self.invalidated = True

    def execute(self, sentencia, parametros):
        sql = str(sentencia)
        if "UPDATE Tarjeta.Tarjeta SET Estado = 'Activa'" in sql:
            afectadas = 0 if self.store.credito_activo else 1
            self.store.credito_activo = True
            if "OUTPUT INSERTED.IdTarjeta INTO @activadas" in sql:
                assert "INSERT INTO Tarjeta.TarjetaHis" in sql
                assert "FROM @activadas" in sql
                if afectadas:
                    if self.store.fallo == "historial":
                        raise SQLAlchemyError("Historial no disponible")
                    self.store.historial_credito.append(parametros)
            return SimpleNamespace(
                rowcount=-1 if self.connection.driver_connection.nocount else afectadas
            )
        assert "INSERT INTO Tarjeta.TarjetaHis" in sql
        self.store.historial_credito.append(parametros)


@pytest.fixture
def saldo_lab(pin_lab, monkeypatch):
    store = Almacen()

    def ejecutar_lote_credito(conn, sql, parametros):
        # Adaptador del doble: el helper DBAPI real se comprueba en test_atm.py.
        id_tarjeta, canal, usuario, ip = parametros
        conn.execute(
            sql, {"id": id_tarjeta, "canal": canal, "usuario": usuario, "ip": ip}
        )
        return {"Activadas": 1}

    monkeypatch.setattr(repository, "ejecutar_con_salidas", ejecutar_lote_credito)
    monkeypatch.setattr(router, "get_engine", lambda nombre: store)
    monkeypatch.setattr(repo, "buscar_registro", lambda c, clave: store.rows.get(clave))
    monkeypatch.setattr(repo, "bloquear_contexto", lambda *_: None)
    monkeypatch.setattr(repo, "leer_cuenta", lambda *_: copy.deepcopy(store.cuenta))
    monkeypatch.setattr(repo, "insertar_consulta", store.insertar)
    monkeypatch.setattr(repo, "fecha_contable", lambda *_: 20261108)
    monkeypatch.setattr(numeracion, "bloquear_numeracion", lambda *_: True)
    monkeypatch.setattr(
        numeracion,
        "siguiente_secuencial",
        lambda conn, fecha: (
            max(
                (
                    int(r["Secuencial"])
                    for r in store.rows.values()
                    if r["FechaSistema"] == fecha
                ),
                default=0,
            )
            + 1
        ),
    )
    monkeypatch.setattr(
        numeracion,
        "identificadores_ocupados",
        lambda conn, d: any(
            r["NumeroComprobante"] == d["comprobante"]
            or r["RRN"] == d["rrn"]
            or (
                r["FechaSistema"] == d["fecha"]
                and (r["STAN"] == d["stan"] or r["Secuencial"] == d["secuencial"])
            )
            for r in store.rows.values()
        ),
    )
    atm = {
        "id_atm": 7,
        "id_canal": 2,
        "tipo_terminal": "ATM",
        "estado_atm": "A",
        "estado_canal": "A",
        "requiere_tarjeta": True,
        "requiere_pin": True,
        "requiere_terminal": True,
    }
    card = {
        "id_cuenta": 501,
        "estado_tarjeta": "Activa",
        "pin_asignado": True,
        "fecha_expiracion": datetime(2030, 1, 1).date(),
    }
    monkeypatch.setattr(repository, "obtener_atm", lambda *_: atm)
    monkeypatch.setattr(repository, "obtener_tarjeta", lambda *_: card)
    autorizaciones = []

    def autorizar(*args, **kwargs):
        args[0].connection.driver_connection.nocount = True
        autorizaciones.append(args)
        assert kwargs["fecha_hora"] == store.cuenta["Ahora"]
        return {"CodigoRespuesta": "00", "Comision": Decimal(0)}

    monkeypatch.setattr(saldo_service, "autorizar_operacion", autorizar)
    monkeypatch.setattr(saldo_service, "comision_de", lambda *_: Decimal(0))
    secreto = secrets.token_urlsafe(32)
    credencial = terminal_auth.RegistroCredencial(
        codigoATM="ATM00001",
        sha256=hashlib.sha256(secreto.encode()).hexdigest(),
        enabled=True,
        notBefore=datetime.now(UTC) - timedelta(minutes=1),
        expiresAt=datetime.now(UTC) + timedelta(minutes=10),
        auditUserId=900,
    )
    monkeypatch.setattr(
        terminal_auth, "leer_registro", lambda: {"SALDO-LAB-KEY-001": credencial}
    )
    auth = {**headers(pin_lab), "X-ATM-Credential": "SALDO-LAB-KEY-001." + secreto}
    return SimpleNamespace(
        pin=pin_lab,
        store=store,
        card=card,
        atm=atm,
        auth=auth,
        autorizaciones=autorizaciones,
        credential=credencial,
    )


def consultar(lab, body=None, auth=None):
    return lab.pin.http.post(RUTA, headers=auth or lab.auth, json=body or BODY)


@pytest.mark.parametrize("tipo,codigo", [("Ahorro", "311000"), ("Corriente", "312000")])
def test_consulta_gratuita_sin_movimientos(saldo_lab, tipo, codigo, caplog):
    lab = saldo_lab
    lab.store.cuenta["TipoCuenta"] = tipo
    antes = copy.deepcopy(lab.store.cuenta)
    r = consultar(lab)
    assert r.status_code == 200
    assert r.json()["saldoContable"] == 100.25
    assert r.json()["saldoRetenido"] == 20.15
    assert r.json()["saldoDisponible"] == 80.10
    assert r.json()["comision"] == 0 and r.json()["codigoRespuesta"] == "00"
    assert r.json()["estado"] == "Completada" and r.json()["esReintento"] is False
    assert lab.store.cuenta == antes
    row = lab.store.rows[BODY["registroUnico"]]
    assert row["CodigoProcesamiento"] == codigo and row["CreadoPor"] == 900
    assert lab.autorizaciones[0][1:] == (501, 2, "Consulta", Decimal(0))
    assert lab.auth["Authorization"][7:] not in caplog.text
    assert lab.auth["X-ATM-Credential"] not in caplog.text


def test_reintento_conserva_comprobante_y_actualiza_saldos(saldo_lab):
    lab = saldo_lab
    primero = consultar(lab).json()
    lab.store.cuenta.update(
        Saldo=Decimal(250), SaldoRetenido=Decimal(50), Ahora=datetime(2026, 11, 9, 8)
    )
    segundo = consultar(lab).json()
    for campo in ("idTransaccion", "numeroComprobante", "fechaHoraSistema"):
        assert primero[campo] == segundo[campo]
    assert segundo["saldoDisponible"] == 200 and segundo["esReintento"] is True
    assert primero["fechaConsultaSaldo"] != segundo["fechaConsultaSaldo"]
    assert len(lab.store.rows) == len(lab.autorizaciones) == 1


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("IdATM", 8),
        ("IdTarjeta", 99),
        ("IdCuenta", 8),
        ("TipoTransaccion", "Retiro"),
        ("TipoOperacion", "Reverso"),
        ("Monto", Decimal(1)),
        ("CodigoProcesamiento", "312000"),
        ("IdCanal", 8),
    ],
)
def test_reutilizacion_conflictiva_409(saldo_lab, campo, valor):
    consultar(saldo_lab)
    saldo_lab.store.rows[BODY["registroUnico"]][campo] = valor
    assert consultar(saldo_lab).status_code == 409
    assert len(saldo_lab.store.rows) == 1


@pytest.mark.parametrize("estado", ["Bloqueada", "Generada", "Inactiva", "Vencida"])
def test_tarjeta_no_operativa_no_registra(saldo_lab, estado):
    saldo_lab.card["estado_tarjeta"] = estado
    assert consultar(saldo_lab).status_code == 403
    assert not saldo_lab.store.rows


def test_cuenta_ajena_o_desvinculada_404_sin_registro(saldo_lab):
    assert consultar(saldo_lab, {**BODY, "idCuenta": 999}).status_code == 404
    saldo_lab.card["id_cuenta"] = 999
    assert consultar(saldo_lab).status_code == 404
    assert not saldo_lab.store.rows


def test_terminal_no_corresponde_a_sesion(saldo_lab):
    saldo_lab.atm["id_atm"] = 88
    assert consultar(saldo_lab).status_code == 403
    assert not saldo_lab.store.rows


@pytest.mark.parametrize(
    "modo,codigo",
    [("revocada", 401), ("anterior", 401), ("restringida", 403), ("bloqueado", 403)],
)
def test_dependencias_reales_rechazan_sesion(saldo_lab, modo, codigo):
    lab = saldo_lab
    if modo == "revocada":
        sesion = session.validar_jwt_atm(lab.auth["Authorization"][7:])
        lab.pin.driver.revoked.add(sesion.jti)
    elif modo == "anterior":
        lab.pin.driver.row["fecha_asignacion"] = FECHA_PIN + timedelta(seconds=1)
    elif modo == "bloqueado":
        lab.pin.driver.row["estado_pin"] = "Bloqueado"
    else:
        lab.auth.update(
            headers(
                lab.pin, replace(lab.pin.acceso, cambio_pin_requerido=True, cuentas=[])
            )
        )
    r = consultar(lab)
    assert r.status_code == codigo
    if modo == "restringida":
        assert r.json()["code"] == "PIN_CAMBIO_REQUERIDO"
    assert not lab.store.rows


def test_rechazo_negocio_persistente_e_idempotente(saldo_lab):
    lab = saldo_lab
    lab.store.cuenta["Estado"] = "Bloqueada"
    for _ in range(2):
        assert consultar(lab).status_code == 409
    assert len(lab.store.rows) == 1
    assert lab.store.rows[BODY["registroUnico"]]["Estado"] == "Rechazada"
    assert lab.store.rows[BODY["registroUnico"]]["CodigoRespuesta"] == "05"
    assert len(lab.autorizaciones) == 1


@pytest.mark.parametrize("fallo", ["insert", "commit", "timeout", "lock_timeout"])
def test_infraestructura_503_y_rollback(saldo_lab, fallo, caplog):
    saldo_lab.store.fallo = fallo
    r = consultar(saldo_lab)
    assert r.status_code == 503 and not saldo_lab.store.rows
    assert saldo_lab.store.rollbacks == 1
    assert "SECRETO" not in r.text + caplog.text
    driver = saldo_lab.store.pool[-1].connection.driver_connection
    assert (driver.nocount, driver.timeout, driver.lock_timeout) == (False, 0, -1)


def test_commit_sin_confirmacion_se_recupera_con_misma_clave(saldo_lab):
    saldo_lab.store.fallo = "ack"
    assert consultar(saldo_lab).status_code == 503
    saldo_lab.store.fallo = None
    r = consultar(saldo_lab)
    assert r.status_code == 200 and r.json()["esReintento"] is True
    assert len(saldo_lab.store.rows) == len(saldo_lab.autorizaciones) == 1


def test_concurrencia_local_un_solo_comprobante(saldo_lab):
    with ThreadPoolExecutor(max_workers=2) as pool:
        respuestas = list(pool.map(lambda _: consultar(saldo_lab), range(2)))
    assert [r.status_code for r in respuestas] == [200, 200]
    assert len({r.json()["idTransaccion"] for r in respuestas}) == 1
    assert sorted(r.json()["esReintento"] for r in respuestas) == [False, True]
    assert len(saldo_lab.store.rows) == 1


def test_openapi_documenta_503_y_seguridad(saldo_lab):
    operacion = saldo_lab.pin.http.app.openapi()["paths"][RUTA]["post"]
    assert operacion["operationId"] == "ATM02"
    assert "application/problem+json" in operacion["responses"]["503"]["content"]
    assert operacion["security"] == [{"SesionATM": [], "APIKeyHeader": []}]


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("estado_atm", "I"),
        ("estado_canal", "I"),
        ("requiere_tarjeta", False),
        ("requiere_pin", False),
        ("requiere_terminal", False),
    ],
)
def test_terminal_no_habilitado_no_registra(saldo_lab, campo, valor):
    saldo_lab.atm[campo] = valor
    assert consultar(saldo_lab).status_code == 409
    assert not saldo_lab.store.rows


@pytest.mark.parametrize(
    "modo", ["saldo", "retenido", "fecha_contable", "autorizar", "comision", "applock"]
)
def test_dependencias_invalidas_no_registran(saldo_lab, monkeypatch, modo):
    if modo == "saldo":
        saldo_lab.store.cuenta["Saldo"] = None
    elif modo == "retenido":
        saldo_lab.store.cuenta["SaldoRetenido"] = Decimal(-1)
    elif modo == "fecha_contable":
        monkeypatch.setattr(repo, "fecha_contable", lambda *_: None)
    elif modo == "applock":
        monkeypatch.setattr(numeracion, "bloquear_numeracion", lambda *_: False)
    else:
        monkeypatch.setattr(
            saldo_service,
            "autorizar_operacion",
            lambda *_, **kw: {
                "CodigoRespuesta": "99" if modo == "autorizar" else "00",
                "Comision": Decimal(1) if modo == "comision" else Decimal(0),
            },
        )
    assert consultar(saldo_lab).status_code == 503
    assert not saldo_lab.store.rows


def test_codigo_05_del_autorizador_queda_registrado(saldo_lab, monkeypatch):
    monkeypatch.setattr(
        saldo_service,
        "autorizar_operacion",
        lambda *_, **kw: {
            "CodigoRespuesta": "05",
            "Comision": Decimal(0),
        },
    )
    assert consultar(saldo_lab).status_code == 409
    assert saldo_lab.store.rows[BODY["registroUnico"]]["CodigoRespuesta"] == "05"
    assert saldo_lab.store.commits == 1


@pytest.mark.parametrize(
    "cambio,status", [("cuenta", 409), ("tarjeta", 403), ("version", 401)]
)
def test_reintento_revalida_permisos_actuales(saldo_lab, cambio, status):
    assert consultar(saldo_lab).status_code == 200
    antes = copy.deepcopy(saldo_lab.store.rows)
    if cambio == "cuenta":
        saldo_lab.store.cuenta["Estado"] = "Cerrada"
    elif cambio == "tarjeta":
        saldo_lab.card["estado_tarjeta"] = "Bloqueada"
    else:
        saldo_lab.pin.driver.row["fecha_asignacion"] = FECHA_PIN + timedelta(seconds=1)
    assert consultar(saldo_lab).status_code == status
    assert saldo_lab.store.rows == antes
    assert len(saldo_lab.autorizaciones) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"idCuenta": True, "registroUnico": "SALDOLAB0001"},
        {"idCuenta": 501, "registroUnico": "corta"},
        {"idCuenta": 501, "registroUnico": "SALDOLAB0001", "monto": 100},
    ],
)
def test_body_estricto_400(saldo_lab, body):
    assert consultar(saldo_lab, body).status_code == 400
    assert not saldo_lab.store.rows


def test_credencial_de_terminal_invalida_no_registra(saldo_lab):
    auth = {**saldo_lab.auth, "X-ATM-Credential": "invalida"}
    assert consultar(saldo_lab, auth=auth).status_code == 401
    assert not saldo_lab.store.rows


def test_consulta_historica_con_comision_no_se_reinterpreta_como_gratuita(
    saldo_lab, monkeypatch
):
    assert consultar(saldo_lab).status_code == 200
    monkeypatch.setattr(saldo_service, "comision_de", lambda *_: Decimal(1))
    assert consultar(saldo_lab).status_code == 409
    assert len(saldo_lab.store.rows) == 1


def test_conexion_cooperativa_fallida_503(saldo_lab, monkeypatch):
    def caida(_nombre):
        raise SQLAlchemyError("SECRETO")

    monkeypatch.setattr(router, "get_engine", caida)
    respuesta = consultar(saldo_lab)
    assert respuesta.status_code == 503 and "SECRETO" not in respuesta.text
    assert not saldo_lab.store.rows


@pytest.mark.parametrize("fallo", [None, "insert", "rechazo"])
@pytest.mark.parametrize("nocount", [False, True])
def test_conexion_reutilizada_por_atm01_conserva_historial_credito(
    saldo_lab, fallo, nocount
):
    lab = saldo_lab
    with lab.store.connect() as conn:
        conn.connection.driver_connection.nocount = nocount
    if fallo == "rechazo":
        lab.store.cuenta["Estado"] = "Bloqueada"
    else:
        lab.store.fallo = fallo
    r = consultar(lab)
    assert r.status_code == ({None: 200, "insert": 503, "rechazo": 409}[fallo])
    prestada = lab.store.pool[-1]
    with lab.store.connect() as conn:
        assert conn is prestada
        assert conn.connection.driver_connection.nocount is nocount
        # Función real de ATM-01; otra tarjeta ficticia de crédito Generada.
        repository.activar_tarjeta_credito(conn, 302, 2, 900, "127.0.0.1")
        repository.activar_tarjeta_credito(conn, 302, 2, 900, "127.0.0.1")
    assert lab.store.credito_activo is True
    assert lab.store.historial_credito == [
        {"id": 302, "canal": 2, "usuario": 900, "ip": "127.0.0.1"}
    ]
    assert conn.connection.driver_connection.nocount is nocount


@pytest.mark.parametrize("nocount", [False, True])
def test_activacion_credito_revierte_si_falla_historial(saldo_lab, nocount):
    store = saldo_lab.store
    store.fallo = "historial"
    with store.connect() as conn:
        conn.connection.driver_connection.nocount = nocount
        with pytest.raises(SQLAlchemyError), conn.begin():
            repository.activar_tarjeta_credito(conn, 302, 2, 900, None)
        assert conn.connection.driver_connection.nocount is nocount
    assert store.credito_activo is False
    assert store.historial_credito == []


def test_dias_distintos_reutilizan_stan_sin_colision_y_reintento_no_renumera(saldo_lab):
    lab = saldo_lab
    primero = consultar(lab).json()
    dia1 = copy.deepcopy(lab.store.rows[BODY["registroUnico"]])
    lab.store.cuenta["Ahora"] = datetime(2026, 11, 9, 0, 0)
    assert consultar(lab, {**BODY, "registroUnico": "SALDOLAB0002"}).status_code == 200
    dia2 = lab.store.rows["SALDOLAB0002"]
    assert dia1["Secuencial"] == dia2["Secuencial"] == "000001"
    assert dia1["STAN"] == dia2["STAN"] == "000001"
    assert dia1["RRN"] != dia2["RRN"]
    assert dia1["NumeroComprobante"] != dia2["NumeroComprobante"]
    assert consultar(lab).json()["numeroComprobante"] == primero["numeroComprobante"]
    assert len(lab.store.rows) == 2


def test_concurrencia_claves_distintas_numeros_unicos_dentro_del_dia(saldo_lab):
    def solicitar(indice):
        return consultar(saldo_lab, {**BODY, "registroUnico": f"SALDOLAB{indice:04d}"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        respuestas = list(pool.map(solicitar, [1, 2]))
    assert [r.status_code for r in respuestas] == [200, 200]
    assert {r["STAN"] for r in saldo_lab.store.rows.values()} == {"000001", "000002"}
    assert len({r["RRN"] for r in saldo_lab.store.rows.values()}) == 2
    for conn in saldo_lab.store.pool:
        d = conn.connection.driver_connection
        assert (d.nocount, d.timeout, d.lock_timeout) == (False, 0, -1)


def test_agotamiento_sin_reciclaje_y_dia_nuevo_disponible(saldo_lab):
    lab = saldo_lab
    assert consultar(lab).status_code == 200
    lab.store.rows[BODY["registroUnico"]]["Secuencial"] = "999999"
    antes = copy.deepcopy(lab.store.rows)
    assert consultar(lab, {**BODY, "registroUnico": "SALDOLAB0002"}).status_code == 503
    assert lab.store.rows == antes
    lab.store.cuenta["Ahora"] = datetime(2026, 11, 9)
    assert consultar(lab, {**BODY, "registroUnico": "SALDOLAB0002"}).status_code == 200
    assert lab.store.rows["SALDOLAB0002"]["Secuencial"] == "000001"


def test_rollback_libera_consecutivo_no_confirmado(saldo_lab):
    lab = saldo_lab
    lab.store.fallo = "commit"
    assert consultar(lab).status_code == 503
    assert not lab.store.rows
    lab.store.fallo = None
    assert consultar(lab).status_code == 200
    assert lab.store.rows[BODY["registroUnico"]]["Secuencial"] == "000001"


def test_stan_ocupado_en_el_dia_no_se_reutiliza(saldo_lab):
    lab = saldo_lab
    assert consultar(lab).status_code == 200
    lab.store.rows[BODY["registroUnico"]]["STAN"] = "000002"
    antes = copy.deepcopy(lab.store.rows)
    assert consultar(lab, {**BODY, "registroUnico": "SALDOLAB0002"}).status_code == 503
    assert lab.store.rows == antes


@pytest.mark.parametrize("campo", ["RRN", "NumeroComprobante"])
def test_colisiones_globales_no_se_ignoran_por_cambio_de_fecha(saldo_lab, campo):
    lab = saldo_lab
    assert consultar(lab).status_code == 200
    row = lab.store.rows[BODY["registroUnico"]]
    row["FechaSistema"] = datetime(2026, 11, 7).date()
    if campo == "RRN":
        row["NumeroComprobante"] = "LEGACY-LAB-000001"
    else:
        row["RRN"] = "000000000000"
    antes = copy.deepcopy(lab.store.rows)
    assert consultar(lab, {**BODY, "registroUnico": "SALDOLAB0002"}).status_code == 503
    assert lab.store.rows == antes


def test_restauracion_fallida_descarta_conexion_sin_repetir_consulta(
    saldo_lab, monkeypatch
):
    lab = saldo_lab
    with lab.store.connect() as anterior:
        driver = anterior.connection.driver_connection
    cursor = driver.cursor()
    ejecutar = cursor.execute

    def falla_restaurar(sql):
        if sql == "SET NOCOUNT OFF":
            raise pyodbc.Error("08S01", "fallo de restauración")
        return ejecutar(sql)

    monkeypatch.setattr(cursor, "execute", falla_restaurar)
    monkeypatch.setattr(driver, "cursor", lambda: cursor)
    assert consultar(lab).status_code == 200
    assert anterior.invalidated is True and not lab.store.pool
    assert lab.store.commits == len(lab.store.rows) == len(lab.autorizaciones) == 1
    with lab.store.connect() as nueva:
        assert nueva is not anterior
        assert nueva.connection.driver_connection.nocount is False
