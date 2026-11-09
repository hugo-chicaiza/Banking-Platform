"""SQL Server real, exclusivamente local y opt-in. No borra bases ni historial.

Las bases se preparan mediante atm_saldo_lab_schema; se conservan los datos
ficticios y evidencia. Nunca importar Settings para resolver conexiones SQL.
"""

import hashlib
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from threading import Event
from types import SimpleNamespace
from typing import Any

import pyodbc
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from app.core.config.settings import Settings
from app.core.database.session_scope import sesion_sql_acotada
from app.core.security.hsm import HsmSimulado
from app.core.security.pin_version import version_desde_fecha
from app.modules.atm import (
    repository,
    router,
    service,
    session,
    terminal_auth,
)
from app.modules.atm import saldo_repository as saldo_repo
from app.modules.tarjetas import repository as tarjetas_repo
from app.modules.transacciones import numeracion
from tests.integration.atm_saldo_sql_lab import COOP, SEG, motor


@pytest.fixture(scope="module")
def engines():
    import os

    if os.getenv("ATM02_LOCAL_SQL_ENABLED") != "1":
        pytest.skip(
            "Laboratorio SQL local deshabilitado; autorización explícita requerida"
        )
    original_connect = pyodbc.connect
    patcher = pytest.MonkeyPatch()

    def solo_local(dsn, *args, **kwargs):
        if "SERVER=lpc:.;" not in dsn or not any(
            "DATABASE=" + db + ";" in dsn for db in (COOP, SEG)
        ):
            raise RuntimeError("Conexión fuera del laboratorio prohibida")
        return original_connect(dsn, *args, **kwargs)

    patcher.setattr(pyodbc, "connect", solo_local)
    coop, seg = (
        motor(COOP, pool_size=4, max_overflow=0),
        motor(SEG, pool_size=4, max_overflow=0),
    )
    try:
        for engine, database in ((coop, COOP), (seg, SEG)):
            with engine.connect() as c:
                assert c.scalar(text("SELECT DB_NAME()")) == database
        yield {"cooperativa": coop, "seguridad": seg}
    finally:
        coop.dispose()
        seg.dispose()
        patcher.undo()


def insert(c, table, values, key=None) -> Any:
    # Solo nombres fijos del arnés; nunca aceptar identificadores de una petición.
    cols = ",".join("[" + k + "]" for k in values)
    params = ",".join(":" + k for k in values)
    if key:
        sql = f"SET NOCOUNT ON; DECLARE @ids TABLE(Id int); INSERT INTO {table} ({cols}) OUTPUT INSERTED.[{key}] INTO @ids VALUES ({params}); SELECT Id FROM @ids;"
        with sesion_sql_acotada(c):
            return c.scalar(text(sql), values)
    c.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({params})"), values)
    return None


@pytest.fixture(scope="module")
def catalogos(engines):
    coop = engines["cooperativa"]
    with coop.begin() as c:
        if c.scalar(text("SELECT COUNT(*) FROM Catalogo.Paises")):
            # Solo catálogos marcados y creados por este arnés, sin sobrescribirlos.
            assert (
                c.scalar(
                    text(
                        "SELECT COUNT(*) FROM Catalogo.Paises WHERE NombrePais='LAB ATM02 FICTICIO'"
                    )
                )
                == 1
            )
            row = c.execute(
                text("SELECT TOP(1) IdCanal,IdATM FROM ATM.ATM ORDER BY IdATM")
            ).first()
            productos = c.execute(
                text(
                    "SELECT IdProducto,TipoCuenta FROM ProductosFinancieros.Producto WHERE TipoProducto='Cuenta'"
                )
            ).all()
            cliente = c.scalar(text("SELECT MIN(IdCliente) FROM Clientes.Cliente"))
            return SimpleNamespace(
                canal=row.IdCanal,
                atm=row.IdATM,
                cliente=cliente,
                productos={r.TipoCuenta: r.IdProducto for r in productos},
            )
        insert(
            c,
            "Catalogo.Paises",
            {
                "CodigoPais": "ECU",
                "CodigoNumerico": "218",
                "NombrePais": "LAB ATM02 FICTICIO",
            },
        )
        ciudad = insert(
            c,
            "Catalogo.Ciudad",
            {"CodigoPais": "ECU", "Nombre": "CIUDAD FICTICIA", "Provincia": "LAB"},
            "IdCiudad",
        )
        insert(
            c,
            "Organizacion.Agencia",
            {
                "IdAgencia": "L01",
                "Codigo": "LAB01",
                "TipoAgencia": "Sucursal",
                "IdCiudad": ciudad,
            },
        )
        cliente = insert(
            c,
            "Clientes.Cliente",
            {
                "Identificacion": "LAB0000001",
                "TipoDocumento": "P",
                "TipoCliente": "Natural",
                "Nombres": "CLIENTE LAB",
                "Apellidos": "FICTICIO",
                "Genero": "M",
                "EstadoCivil": "Soltero",
                "FechaNacimiento": date(1990, 1, 1),
                "TelefonoCelular": "0000000000",
                "Email": "atm02@example.invalid",
                "ConsentimientoDatos": True,
                "FechaConsentimiento": datetime.now(UTC).replace(tzinfo=None),
                "CreadoPor": 900,
                "Estado": "Activo",
            },
            "IdCliente",
        )
        canal = insert(
            c,
            "Canal.Canal",
            {
                "CodigoCanal": "ATM",
                "NombreCanal": "ATM LAB",
                "Descripcion": "Terminal ficticio",
                "RequiereTarjeta": True,
                "RequierePin": True,
                "RequiereTerminal": True,
                "RequiereJornadaCaja": False,
            },
            "IdCanal",
        )
        atm = insert(
            c,
            "ATM.ATM",
            {
                "CodigoATM": "LABATM01",
                "CodigoAdquirente": "LAB",
                "TipoTerminal": "ATM",
                "IdCanal": canal,
                "IdAgencia": "L01",
                "FechaInstalacion": date(2026, 1, 1),
            },
            "IdATM",
        )
        for codigo, categoria in [("00", "Aprobada"), ("05", "RechazoSeguridad")]:
            insert(
                c,
                "Catalogo.CodigosRespuesta",
                {
                    "CodigoRespuesta": codigo,
                    "Descripcion": "RESPUESTA LAB",
                    "Categoria": categoria,
                },
            )
        insert(
            c,
            "Transacciones.TipoTransaccion",
            {
                "CodigoTipo": "Consulta",
                "Nombre": "Consulta LAB",
                "AfectaSaldo": False,
                "Naturaleza": None,
            },
        )
        productos = {}
        for tipo, codigo in [("Ahorro", "LABAHO"), ("Corriente", "LABCOR")]:
            productos[tipo] = insert(
                c,
                "ProductosFinancieros.Producto",
                {
                    "CodigoProducto": codigo,
                    "NombreProducto": "CUENTA FICTICIA",
                    "TipoProducto": "Cuenta",
                    "TipoCuenta": tipo,
                },
                "IdProducto",
            )
            insert(
                c,
                "ProductosFinancieros.SubProducto",
                {
                    "IdProducto": productos[tipo],
                    "CodigoSubProducto": codigo,
                    "NombreSubProducto": "SUBPRODUCTO LAB",
                },
                "IdSubProducto",
            )
        red = insert(
            c,
            "ProductosFinancieros.Red",
            {"CodigoRed": "LAB", "Nombre": "RED FICTICIA"},
            "IdRed",
        )
        prod = insert(
            c,
            "ProductosFinancieros.Producto",
            {
                "CodigoProducto": "LABTAR",
                "NombreProducto": "TARJETA FICTICIA",
                "TipoProducto": "Tarjeta",
                "IdRed": red,
            },
            "IdProducto",
        )
        insert(
            c,
            "ProductosFinancieros.SubProducto",
            {
                "IdProducto": prod,
                "CodigoSubProducto": "LABTAR",
                "NombreSubProducto": "TARJETA LAB",
            },
            "IdSubProducto",
        )
        insert(
            c,
            "Tarjeta.TransicionEstado",
            {"EstadoOrigen": "Generada", "EstadoDestino": "Activa"},
        )
        hoy = c.scalar(
            text(
                "SELECT CONVERT(date,SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time')"
            )
        )
        dias = {hoy + timedelta(days=i) for i in range(-40, 41)} | {
            date(2050, 1, 3),
            date(2050, 1, 4),
        }
        nombres = [
            "Lunes",
            "Martes",
            "Miércoles",
            "Jueves",
            "Viernes",
            "Sábado",
            "Domingo",
        ]
        for dia in sorted(dias):
            insert(
                c,
                "Contabilidad.FechaContable",
                {
                    "Fecha": dia,
                    "NumeroDiaSemana": dia.weekday() + 1,
                    "NombreDiaSemana": nombres[dia.weekday()],
                },
            )
    return SimpleNamespace(canal=canal, atm=atm, cliente=cliente, productos=productos)


@pytest.fixture
def lab(engines, catalogos, monkeypatch, request):
    uid = uuid.uuid4().hex
    coop, seg = engines["cooperativa"], engines["seguridad"]
    tipo = "Corriente" if getattr(request, "param", None) == "Corriente" else "Ahorro"
    credito = getattr(request, "param", None) == "Credito"
    with coop.begin() as c:
        sub = c.scalar(
            text(
                "SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE IdProducto=:id"
            ),
            {"id": catalogos.productos[tipo]},
        )
        cuenta = insert(
            c,
            "Cuentas.Cuenta",
            {
                "NumeroCuenta": f"{int(uid[:10], 16):013d}",
                "IdCliente": catalogos.cliente,
                "IdAgencia": "L01",
                "IdProducto": catalogos.productos[tipo],
                "IdSubProducto": sub,
                "CreadoPor": 900,
                "Saldo": Decimal("100.25"),
                "SaldoRetenido": Decimal("20.15"),
            },
            "IdCuenta",
        )
        prod, subtar = c.execute(
            text(
                "SELECT IdProducto,IdSubProducto FROM ProductosFinancieros.SubProducto WHERE CodigoSubProducto='LABTAR'"
            )
        ).one()
        pan = "500000" + str(int(uid[10:20], 16) % 1000000000).zfill(9)
        digits = [int(d) for d in pan]
        total = sum(
            (n * 2 - 9 if n * 2 > 9 else n * 2) if i % 2 == 0 else n
            for i, n in enumerate(digits)
        )
        pan += str((-total) % 10)
        hoy = c.scalar(
            text(
                "SELECT CONVERT(date,SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time')"
            )
        )
        tarjeta = insert(
            c,
            "Tarjeta.Tarjeta",
            {
                "TokenTarjeta": "LAB-" + uid,
                "NumeroEnmascarado": "500000******0000",
                "HashNumeroTarjeta": hashlib.sha256(pan.encode()).digest(),
                "NombreTarjeta": "LABORATORIO FICTICIO",
                "TipoTarjeta": "Credito" if credito else "Debito",
                "NombresTitular": "CLIENTE LAB",
                "ApellidosTitular": "FICTICIO",
                "IdCliente": catalogos.cliente,
                "IdCuenta": cuenta,
                "IdProducto": prod,
                "IdSubProducto": subtar,
                "IdAgencia": "L01",
                "FechaEmision": hoy - timedelta(days=10),
                "FechaExpiracion": hoy + timedelta(days=365),
                "PinAsignado": True,
                "Estado": "Generada" if credito else "Activa",
                "CreadoPor": 900,
            },
            "IdTarjeta",
        )
    hsm = HsmSimulado(
        clave_pan=secrets.token_bytes(32),
        clave_pvk=secrets.token_bytes(16),
        claves_pin_block={"LABKEY": secrets.token_bytes(32)},
        referencia_pin_block="LABKEY",
    )
    bloque, referencia = hsm.construir_pin_block("7392", pan)
    offset, pvk = hsm.generar_offset(bloque, referencia, pan)
    with seg.begin() as c:
        cifrado, ref = hsm.cifrar_pan(pan, tarjeta)
        tarjetas_repo.guardar_pan_ficticio(c, tarjeta, cifrado, ref)
        tarjetas_repo.guardar_pin_generado(c, tarjeta, offset, pvk, False)
        version = version_desde_fecha(
            c.scalar(
                text(
                    "SELECT FechaAsignacion FROM Tarjetas.TarjetaPIN WHERE ID_Tarjeta=:id"
                ),
                {"id": tarjeta},
            )
        )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    cfg = Settings.model_construct(
        atm_jwt_private_key_pem=SecretStr(pem),
        atm_jwt_issuer="urn:atm02:local",
        atm_jwt_audience="urn:atm02:lab",
    )
    monkeypatch.setattr(session, "get_settings", lambda: cfg)
    for modulo in (router, session, service):
        monkeypatch.setattr(modulo, "get_engine", lambda db: engines[db])
    monkeypatch.setattr(service, "obtener_hsm", lambda: hsm)
    secret = secrets.token_urlsafe(32)
    record = terminal_auth.RegistroCredencial(
        codigoATM="LABATM01",
        sha256=hashlib.sha256(secret.encode()).hexdigest(),
        enabled=True,
        notBefore=datetime.now(UTC) - timedelta(minutes=1),
        expiresAt=datetime.now(UTC) + timedelta(minutes=15),
        auditUserId=900,
    )
    monkeypatch.setattr(
        terminal_auth, "leer_registro", lambda: {"ATM02-LOCAL-KEY01": record}
    )
    app = FastAPI()
    app.include_router(router.router, prefix="/api/v1")
    with TestClient(app, base_url="https://testserver") as http:
        credential = {"X-ATM-Credential": "ATM02-LOCAL-KEY01." + secret}
        response = http.post(
            "/api/v1/atm/auth",
            headers=credential,
            json={
                "codigoATM": "LABATM01",
                "numeroTarjeta": pan,
                "encryptedPinBlock": bloque,
                "keyReference": referencia,
            },
        )
        assert response.status_code == 200, "Autenticación ficticia local falló"
        token = response.json()["sessionToken"]
        headers = {**credential, "Authorization": "Bearer " + token}
        yield SimpleNamespace(
            coop=coop,
            seg=seg,
            http=http,
            headers=headers,
            cuenta=cuenta,
            tarjeta=tarjeta,
            canal=catalogos.canal,
            atm=catalogos.atm,
            version=version,
            body={"idCuenta": cuenta, "registroUnico": uid[:12].upper()},
            hsm=hsm,
            bloque=bloque,
            referencia=referencia,
            offset=offset,
            pvk=pvk,
        )


def consultar(lab, body=None):
    return lab.http.post(
        "/api/v1/atm/consulta-saldo", headers=lab.headers, json=body or lab.body
    )


def fila(lab):
    with lab.coop.connect() as c:
        return dict(
            c.execute(
                text("SELECT * FROM Transacciones.Transaccion WHERE RegistroUnico=:r"),
                {"r": lab.body["registroUnico"]},
            )
            .mappings()
            .one()
        )


def test_esquema_local_coincide_con_metadatos_de_origen(engines):
    import json

    from tests.integration.atm_saldo_lab_schema import SNAPSHOT

    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    for nombre, engine in engines.items():
        esperado = snapshot[nombre]
        with engine.connect() as c:
            assert (
                c.scalar(
                    text(
                        "SELECT compatibility_level FROM sys.databases WHERE database_id=DB_ID()"
                    )
                )
                == esperado["compatibility"]
            )
            assert (
                c.scalar(
                    text(
                        "SELECT is_read_committed_snapshot_on FROM sys.databases WHERE database_id=DB_ID()"
                    )
                )
                is True
            )
            for tabla in esperado["tables"]:
                objeto = tabla["esquema"] + "." + tabla["name"]
                columnas = (
                    c.execute(
                        text(
                            "SELECT c.name,t.name AS tipo,c.max_length,c.precision,c.scale,c.is_nullable,c.is_identity FROM sys.columns c JOIN sys.types t ON t.user_type_id=c.user_type_id WHERE c.object_id=OBJECT_ID(:objeto) ORDER BY c.column_id"
                        ),
                        {"objeto": objeto},
                    )
                    .mappings()
                    .all()
                )
                originales = [
                    v for v in esperado["columns"] if v["tabla"] == tabla["id"]
                ]
                assert len(columnas) == len(originales)
                for actual, original in zip(columnas, originales, strict=True):
                    assert all(
                        actual[k] == original[k]
                        for k in (
                            "name",
                            "tipo",
                            "max_length",
                            "precision",
                            "scale",
                            "is_nullable",
                            "is_identity",
                        )
                    )
                indices = (
                    c.execute(
                        text(
                            "SELECT name,is_unique,is_primary_key,is_unique_constraint,filter_definition FROM sys.indexes WHERE object_id=OBJECT_ID(:objeto) AND index_id>0"
                        ),
                        {"objeto": objeto},
                    )
                    .mappings()
                    .all()
                )
                originales_idx = {
                    v["name"]: v
                    for v in esperado["indices"]
                    if v["tabla"] == tabla["id"]
                }
                assert {v["name"] for v in indices} == set(originales_idx)
                for actual in indices:
                    original = originales_idx[actual["name"]]
                    assert all(
                        actual[k] == original[k]
                        for k in (
                            "is_unique",
                            "is_primary_key",
                            "is_unique_constraint",
                            "filter_definition",
                        )
                    )
                assert c.scalar(
                    text(
                        "SELECT COUNT(*) FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID(:objeto)"
                    ),
                    {"objeto": objeto},
                ) == len([v for v in esperado["checks"] if v["tabla"] == tabla["id"]])
                assert c.scalar(
                    text(
                        "SELECT COUNT(*) FROM sys.foreign_keys WHERE parent_object_id=OBJECT_ID(:objeto)"
                    ),
                    {"objeto": objeto},
                ) == len(
                    {v["id"] for v in esperado["fks"] if v["padre"] == tabla["id"]}
                )
            for modulo in esperado["modules"]:
                definicion = c.scalar(
                    text(
                        "SELECT definition FROM sys.sql_modules WHERE object_id=OBJECT_ID(:objeto)"
                    ),
                    {"objeto": modulo["esquema"] + "." + modulo["name"]},
                )
                assert definicion == modulo["definition"]


def test_consulta_real_y_reintento_saldos_actuales(lab):
    r = consultar(lab)
    assert r.status_code == 200
    assert r.json()["saldoDisponible"] == 80.1
    primera = fila(lab)
    with lab.coop.begin() as c:
        c.execute(
            text(
                "UPDATE Cuentas.Cuenta SET Saldo=200,SaldoRetenido=25 WHERE IdCuenta=:id"
            ),
            {"id": lab.cuenta},
        )
    repetida = consultar(lab)
    assert repetida.status_code == 200
    assert repetida.json()["esReintento"] is True
    assert repetida.json()["saldoDisponible"] == 175
    assert fila(lab) == primera
    with lab.coop.connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT COUNT(*) FROM Cuentas.MovimientoTransaccion WHERE IdCuenta=:id"
                ),
                {"id": lab.cuenta},
            )
            == 0
        )
        assert (
            c.scalar(
                text(
                    "SELECT COUNT(*) FROM Transacciones.TransaccionComision WHERE IdTransaccion=:id"
                ),
                {"id": primera["IdTransaccion"]},
            )
            == 0
        )


def test_concurrencia_real_misma_clave(lab):
    with ThreadPoolExecutor(max_workers=2) as pool:
        respuestas = list(pool.map(lambda _: consultar(lab), range(2)))
    assert [r.status_code for r in respuestas] == [200, 200]
    assert len({r.json()["idTransaccion"] for r in respuestas}) == 1
    assert sorted(r.json()["esReintento"] for r in respuestas) == [False, True]


def test_concurrencia_real_distintas_claves(lab):
    with ThreadPoolExecutor(max_workers=2) as pool:
        respuestas = list(
            pool.map(
                lambda _: consultar(
                    lab, {**lab.body, "registroUnico": uuid.uuid4().hex[:12].upper()}
                ),
                range(2),
            )
        )
    assert [r.status_code for r in respuestas] == [200, 200]
    with lab.coop.connect() as c:
        rows = c.execute(
            text("SELECT STAN,RRN FROM Transacciones.Transaccion WHERE IdCuenta=:id"),
            {"id": lab.cuenta},
        ).all()
    assert len(rows) == len({r.STAN for r in rows}) == len({r.RRN for r in rows}) == 2


def test_rechazo_persistente_y_rollback_infraestructura(lab, monkeypatch):
    with lab.coop.begin() as c:
        c.execute(
            text("UPDATE Cuentas.Cuenta SET Estado='Bloqueada' WHERE IdCuenta=:id"),
            {"id": lab.cuenta},
        )
    assert consultar(lab).status_code == 409
    assert fila(lab)["Estado"] == "Rechazada" and fila(lab)["CodigoRespuesta"] == "05"
    original = saldo_repo.insertar_consulta

    def fallo(c, datos):
        original(c, datos)
        raise DBAPIError("lab", None, RuntimeError("error local controlado"))

    monkeypatch.setattr(saldo_repo, "insertar_consulta", fallo)
    nueva = {**lab.body, "registroUnico": uuid.uuid4().hex[:12].upper()}
    assert consultar(lab, nueva).status_code == 503
    with lab.coop.connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT COUNT(*) FROM Transacciones.Transaccion WHERE RegistroUnico=:r"
                ),
                {"r": nueva["registroUnico"]},
            )
            == 0
        )


@pytest.mark.parametrize("nocount", [False, True])
def test_nocount_timeout_reuso_y_historial_credito(lab, nocount):
    with lab.coop.connect() as c:
        raw = c.connection.driver_connection
        c.execute(text("SET NOCOUNT OFF; SET LOCK_TIMEOUT -1"))
        c.rollback()
        previo = raw.timeout
        raw.timeout = 0
        with sesion_sql_acotada(c), c.begin():
            assert raw.timeout == 15
            assert c.scalar(text("SELECT @@LOCK_TIMEOUT")) == 5000
            c.execute(text("SET NOCOUNT ON"))
        assert c.scalar(text("SELECT @@OPTIONS & 512")) == 0
        assert c.scalar(text("SELECT @@LOCK_TIMEOUT")) == -1
        assert raw.timeout == 0
        c.rollback()
        raw.timeout = previo
    assert consultar(lab).status_code == 200
    with lab.coop.begin() as c:
        valores = dict(
            c.execute(
                text("SELECT * FROM Tarjeta.Tarjeta WHERE IdTarjeta=:id"),
                {"id": lab.tarjeta},
            )
            .mappings()
            .one()
        )
        valores.pop("IdTarjeta")
        valores.update(
            TokenTarjeta="LAB-C-" + uuid.uuid4().hex,
            HashNumeroTarjeta=secrets.token_bytes(32),
            TipoTarjeta="Credito",
            Estado="Generada",
        )
        tarjeta_credito = insert(c, "Tarjeta.Tarjeta", valores, "IdTarjeta")
        with sesion_sql_acotada(c):
            c.execute(text("SET NOCOUNT ON" if nocount else "SET NOCOUNT OFF"))
            for _ in range(2):
                repository.activar_tarjeta_credito(
                    c, tarjeta_credito, lab.canal, 900, "127.0.0.1"
                )
            assert bool(c.scalar(text("SELECT @@OPTIONS & 512"))) is nocount
    with lab.coop.connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT COUNT(*) FROM Tarjeta.TarjetaHis WHERE IdTarjeta=:id AND TipoEvento='Activacion'"
                ),
                {"id": tarjeta_credito},
            )
            == 1
        )


@pytest.mark.parametrize("lab", ["Credito"], indirect=True)
def test_atm01_credito_generada_se_activa_con_historial(lab):
    assert consultar(lab).status_code == 200
    with lab.coop.connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT COUNT(*) FROM Tarjeta.TarjetaHis WHERE IdTarjeta=:id AND TipoEvento='Activacion'"
                ),
                {"id": lab.tarjeta},
            )
            == 1
        )


def test_pin_version_antigua_rechazada(lab):
    with lab.seg.begin() as c:
        tarjetas_repo.guardar_pin_generado(c, lab.tarjeta, lab.offset, lab.pvk, False)
    assert consultar(lab).status_code == 401


def test_numeracion_diaria_y_agotamiento_sql(lab):
    with lab.coop.connect() as c, sesion_sql_acotada(c), c.begin():
        assert numeracion.bloquear_numeracion(c)
        assert numeracion.siguiente_secuencial(c, date(2050, 1, 3)) == 1
        ahora = datetime(2050, 1, 3, 12)
        contable = saldo_repo.fecha_contable(c, ahora)
        datos = {
            "comprobante": "LAB-AGOTAMIENTO-" + uuid.uuid4().hex[:6],
            "secuencial": "999999",
            "registro": uuid.uuid4().hex[:12].upper(),
            "procesamiento": "311000",
            "stan": "999999",
            "rrn": "500103999999",
            "cuenta": lab.cuenta,
            "tarjeta": lab.tarjeta,
            "atm": lab.atm,
            "canal": lab.canal,
            "agencia": "L01",
            "ahora": ahora,
            "usuario": 900,
            "fecha_contable": contable,
            "ip": "127.0.0.1",
            "respuesta": "00",
            "estado": "Completada",
        }
        saldo_repo.insertar_consulta(c, datos)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as e:
            numeracion.numerar_consulta(c, ahora, "Ahorro")
        assert e.value.status_code == 503
        assert (
            numeracion.numerar_consulta(c, datetime(2050, 1, 4), "Ahorro").stan
            == "000001"
        )
        c.rollback()  # Fixture transaccional: no deja agotado el día de laboratorio.


def esperar_bloqueo(engine, sid, bloqueador):
    limite = time.monotonic() + 3
    with engine.connect() as c:
        while time.monotonic() < limite:
            row = c.execute(
                text(
                    "SELECT wait_type,blocking_session_id FROM sys.dm_exec_requests WHERE session_id=:sid AND database_id=DB_ID()"
                ),
                {"sid": sid},
            ).first()
            if (
                row
                and row.blocking_session_id == bloqueador
                and str(row.wait_type).startswith("LCK_M_")
            ):
                return str(row.wait_type)
            time.sleep(0.05)
    raise AssertionError("No se comprobó espera SQL real dentro del plazo")


@pytest.mark.parametrize("recurso", ["applock", "registro", "cuenta"])
def test_bloqueos_reales_y_timeout(lab, recurso):
    worker = Event()
    observado = {}
    principal = threading.get_ident()
    objetivo = {
        "applock": "sp_getapplock",
        "registro": "WHERE RegistroUnico =",
        "cuenta": "FROM Cuentas.Cuenta c WITH",
    }[recurso]

    def antes(_conn, cursor, sql, _params, _context, _many):
        if (
            threading.get_ident() != principal
            and objetivo in sql
            and not worker.is_set()
        ):
            observado["sid"] = cursor.execute("SELECT @@SPID").fetchval()
            worker.set()

    with lab.coop.connect() as a, a.begin():
        sid_a = a.scalar(text("SELECT @@SPID"))
        if recurso == "applock":
            assert numeracion.bloquear_numeracion(a)
        elif recurso == "registro":
            assert saldo_repo.buscar_registro(a, lab.body["registroUnico"]) is None
        else:
            a.execute(
                text(
                    "SELECT IdCuenta FROM Cuentas.Cuenta WITH (UPDLOCK,HOLDLOCK) WHERE IdCuenta=:id"
                ),
                {"id": lab.cuenta},
            ).all()
        event.listen(lab.coop, "before_cursor_execute", antes)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                inicio = time.monotonic()
                futuro = pool.submit(consultar, lab)
                assert worker.wait(3)
                wait = esperar_bloqueo(lab.coop, observado["sid"], sid_a)
                assert wait.startswith("LCK_M_")
                if recurso == "registro":
                    a.rollback()  # Libera el rango ausente y permite una única inserción.
                respuesta = futuro.result(timeout=10)
                assert respuesta.status_code == (200 if recurso == "registro" else 503)
                if recurso != "registro":
                    assert 4 <= time.monotonic() - inicio < 10
        finally:
            event.remove(lab.coop, "before_cursor_execute", antes)


@pytest.mark.parametrize("nocount", [False, True])
@pytest.mark.parametrize("fallo", [False, True])
def test_restauracion_real_tras_reutilizar_conexion(engines, nocount, fallo):
    with engines["cooperativa"].connect() as c:
        raw = c.connection.driver_connection
        previo = raw.timeout
        inicial = c.execute(
            text("SELECT @@LOCK_TIMEOUT AS bloqueo,@@OPTIONS & 512 AS nocount")
        ).one()
        c.execute(text("SET NOCOUNT ON" if nocount else "SET NOCOUNT OFF"))
        c.execute(text("SET LOCK_TIMEOUT 750"))
        c.rollback()
        raw.timeout = 3
        try:

            def operar():
                with sesion_sql_acotada(c), c.begin():
                    assert c.scalar(text("SELECT @@LOCK_TIMEOUT")) == 750
                    assert raw.timeout == 3
                    c.execute(text("SET NOCOUNT OFF" if nocount else "SET NOCOUNT ON"))
                    if fallo:
                        raise RuntimeError("fallo ficticio antes de commit")

            if fallo:
                with pytest.raises(RuntimeError):
                    operar()
            else:
                operar()
            assert c.scalar(text("SELECT @@OPTIONS & 512")) == (512 if nocount else 0)
            assert c.scalar(text("SELECT @@LOCK_TIMEOUT")) == 750 and raw.timeout == 3
        finally:
            c.execute(text("SET NOCOUNT ON" if inicial.nocount else "SET NOCOUNT OFF"))
            c.execute(text(f"SET LOCK_TIMEOUT {int(inicial.bloqueo)}"))
            c.rollback()
            raw.timeout = previo


def test_timeout_odbc_real_y_restauracion(engines):
    with engines["cooperativa"].connect() as c:
        raw = c.connection.driver_connection
        previo = raw.timeout
        raw.timeout = 1
        try:
            inicio = time.monotonic()
            with pytest.raises(DBAPIError) as error, sesion_sql_acotada(c), c.begin():
                c.execute(text("WAITFOR DELAY '00:00:03'"))
            assert time.monotonic() - inicio < 3
            origen = error.value.orig
            assert origen is not None and origen.args[0] == "HYT00"
            if error.value.connection_invalidated:
                assert c.invalidated
            else:
                assert raw.timeout == 1
                assert c.scalar(text("SELECT @@OPTIONS & 512")) == 0
        finally:
            c.rollback()
            if not c.invalidated:
                raw.timeout = previo
    with engines["cooperativa"].connect() as nueva:
        assert nueva.scalar(text("SELECT @@OPTIONS & 512")) == 0
        assert nueva.scalar(text("SELECT @@LOCK_TIMEOUT")) == -1


@pytest.mark.parametrize("lab", ["Corriente"], indirect=True)
def test_consulta_corriente_real(lab):
    assert consultar(lab).status_code == 200
    assert fila(lab)["CodigoProcesamiento"] == "312000"


def test_error_fk_sql_real_revierte_consulta(lab, monkeypatch):
    original = saldo_repo.insertar_consulta

    def invalida(conn, datos):
        return original(conn, {**datos, "fecha_contable": -1})

    monkeypatch.setattr(saldo_repo, "insertar_consulta", invalida)
    assert consultar(lab).status_code == 503
    with lab.coop.connect() as c:
        assert (
            c.scalar(
                text(
                    "SELECT COUNT(*) FROM Transacciones.Transaccion WHERE RegistroUnico=:r"
                ),
                {"r": lab.body["registroUnico"]},
            )
            == 0
        )
        assert c.scalar(
            text("SELECT Saldo FROM Cuentas.Cuenta WHERE IdCuenta=:id"),
            {"id": lab.cuenta},
        ) == Decimal("100.25")


def test_commit_real_confirmacion_perdida_recupera_comprobante(lab, monkeypatch):
    from tests.integration.atm_saldo_sql_lab import ConexionLocal

    original = ConexionLocal.commit
    perdido = []

    def confirmar(self):
        original(self)
        if self._database == COOP and not perdido:
            perdido.append(True)
            raise pyodbc.OperationalError(
                "08S01", "Confirmación ficticia perdida después de commit local"
            )

    monkeypatch.setattr(ConexionLocal, "commit", confirmar)
    assert consultar(lab).status_code == 503
    primera = fila(lab)
    repetida = consultar(lab)
    assert repetida.status_code == 200 and repetida.json()["esReintento"] is True
    assert fila(lab) == primera
    assert len(perdido) == 1


def test_reutilizacion_stan_entre_fechas_con_inserciones_reales(lab):
    numeros = []
    registros = []
    with lab.coop.connect() as c, sesion_sql_acotada(c), c.begin():
        assert numeracion.bloquear_numeracion(c)
        for dia in (3, 4):
            ahora = datetime(2050, 1, dia, 12)
            n = numeracion.numerar_consulta(c, ahora, "Ahorro")
            assert n.stan == n.secuencial == "000001"
            registro = uuid.uuid4().hex[:12].upper()
            saldo_repo.insertar_consulta(
                c,
                {
                    "comprobante": n.numero_comprobante,
                    "secuencial": n.secuencial,
                    "registro": registro,
                    "procesamiento": n.codigo_procesamiento,
                    "stan": n.stan,
                    "rrn": n.rrn,
                    "cuenta": lab.cuenta,
                    "tarjeta": lab.tarjeta,
                    "atm": lab.atm,
                    "canal": lab.canal,
                    "agencia": "L01",
                    "ahora": ahora,
                    "usuario": 900,
                    "fecha_contable": saldo_repo.fecha_contable(c, ahora),
                    "ip": "127.0.0.1",
                    "respuesta": "00",
                    "estado": "Completada",
                },
            )
            numeros.append(n)
            registros.append(registro)
        assert numeros[0].rrn != numeros[1].rrn
        assert numeros[0].numero_comprobante != numeros[1].numero_comprobante
        row = c.execute(
            text(
                "SELECT COUNT(*) AS cantidad,COUNT(DISTINCT STAN) AS stans FROM Transacciones.Transaccion WHERE RegistroUnico IN (:a,:b)"
            ),
            {"a": registros[0], "b": registros[1]},
        ).one()
        assert row.cantidad == 2 and row.stans == 1
        c.rollback()
