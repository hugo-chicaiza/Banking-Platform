"""E3-04 SQL real en dos bases locales propias; actores de prueba controlados."""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pyodbc
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.modules.aprobaciones.auditoria import ContextoAuditoria
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.registro import Objetivo, Registro
from app.modules.aprobaciones.servicio import Servicio
from app.modules.cuentas import repository as cuentas
from app.modules.parametros.service import hoy
from app.modules.productos import numeracion as n
from app.modules.productos.numeracion_aprobacion import (
    CODIGO,
    ProgramadorNumeracion,
    operacion,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("E304_LOCAL_MANIFEST"), reason="Requiere laboratorio SQL E3-04 propio"
)
ORG = "org_fixture_e304"
MAKER = Actor(
    "user_fixture_e304_maker",
    ORG,
    "Solicitante QA",
    900377,
    ("ADMIN",),
    frozenset({"prd-numeracion", "productos:aprobar"}),
    ("001",),
)
CHECKER = Actor(
    "user_fixture_e304_checker",
    ORG,
    "Supervisor QA",
    900378,
    ("SUPERVISOR",),
    frozenset({"productos:aprobar"}),
    ("001",),
)
CTX = ContextoAuditoria("fixture_e304", "127.0.0.1", "e304-local", "SQL_LOCAL")


@pytest.fixture(scope="module")
def motores():
    manifiesto = json.loads(
        Path(os.environ["E304_LOCAL_MANIFEST"]).read_text(encoding="utf-8")
    )
    assert (
        manifiesto["propias"]
        and manifiesto["listo"]
        and manifiesto["servidor"] == "lpc:."
    )
    motores = {}
    for base, nombre in manifiesto["bases"].items():
        assert re.fullmatch("BankingE304_" + base + "_[a-f0-9]{12}", nombre)

        def conectar(nombre=nombre):
            c = pyodbc.connect(
                "DRIVER={ODBC Driver 18 for SQL Server};SERVER=lpc:.;Trusted_Connection=yes;Encrypt=no;DATABASE="
                + nombre
            )
            assert c.execute("SELECT DB_NAME()").fetchval() == nombre
            assert (
                c.execute(
                    "SELECT CONVERT(int,SERVERPROPERTY('EngineEdition'))"
                ).fetchval()
                != 5
            )
            return c

        motores[base] = create_engine(
            "mssql+pyodbc://", creator=conectar, hide_parameters=True
        )
    with motores["seguridad"].begin() as c:
        for actor in [MAKER, CHECKER]:
            if c.execute(
                text("SELECT 1 FROM Organizacion.Usuarios WHERE UsuarioID=:id"),
                {"id": actor.id_interno},
            ).scalar():
                continue
            c.exec_driver_sql("SET IDENTITY_INSERT Organizacion.Usuarios ON")
            c.execute(
                text(
                    "INSERT Organizacion.Usuarios(UsuarioID,NombreUsuario,Nombres,Apellidos,Email,Cedula,KeyUsuario,Estado,RolesWorkOS) VALUES(:id,:usuario,'Persona','QA',:email,:cedula,:usuario,'Activo',:rol)"
                ),
                {
                    "id": actor.id_interno,
                    "usuario": actor.sujeto,
                    "email": actor.sujeto + "@example.invalid",
                    "cedula": str(actor.id_interno).zfill(10),
                    "rol": actor.roles[0],
                },
            )
            c.exec_driver_sql("SET IDENTITY_INSERT Organizacion.Usuarios OFF")
    yield motores
    for motor in motores.values():
        motor.dispose()


@pytest.fixture
def caso(motores):
    with motores["cooperativa"].begin() as c:
        sufijo = uuid4().hex[:6].upper()
        producto = c.execute(
            text(
                "INSERT ProductosFinancieros.Producto(CodigoProducto,NombreProducto,TipoProducto,TipoCuenta,Estado,EstadoProducto,IdTipoProducto,MontoAperturaMinimo) OUTPUT inserted.IdProducto VALUES(:codigo,'Ahorro QA local','Cuenta','Ahorro','A','Activo',1,25)"
            ),
            {"codigo": "N377" + sufijo},
        ).scalar_one()
        sub = c.execute(
            text(
                "INSERT ProductosFinancieros.SubProducto(IdProducto,CodigoSubProducto,NombreSubProducto,Estado,EstadoSubProducto) OUTPUT inserted.IdSubProducto VALUES(:producto,:codigo,'Modelo QA local','A','Activo')"
            ),
            {"producto": producto, "codigo": "S377" + sufijo},
        ).scalar_one()
        prefijo = str(
            c.execute(
                text(
                    "SELECT COALESCE(MAX(TRY_CONVERT(int,Prefijo)),2200)+1 FROM ProductosFinancieros.ReglaNumeracion WHERE LEN(Prefijo)=4"
                )
            ).scalar_one()
        )
    registro = Registro()
    registro.agregar(
        replace(operacion(), manejador=ProgramadorNumeracion(motores["seguridad"]))
    )
    actores = {a.sujeto: a for a in [MAKER, CHECKER]}
    cola = Servicio(
        motores["seguridad"],
        motores["cooperativa"],
        registro,
        lambda sujeto, org: actores[sujeto],
    )
    return (
        cola,
        Objetivo("SubProducto", str(sub), None),
        {
            "prefijo": prefijo,
            "incluyeAgencia": False,
            "longitudSecuencia": 8,
            "algoritmoVerificador": "NINGUNO",
        },
    )


def abrir_real(conn, id_sub):
    cliente = conn.execute(
        text(
            "SELECT TOP(1) IdCliente FROM Clientes.Cliente WHERE Estado='Activo' ORDER BY IdCliente"
        )
    ).scalar_one()
    agencia = conn.execute(
        text(
            "SELECT TOP(1) IdAgencia FROM Organizacion.Agencia WHERE Estado='A' ORDER BY IdAgencia"
        )
    ).scalar_one()
    numero = n.siguiente_numero_cuenta(conn, id_sub, agencia)
    fila = cuentas.abrir_cuenta(
        conn, numero, cliente, id_sub, agencia, Decimal(100), 12
    )
    assert fila["numero_cuenta"] == numero
    return numero


def test_ac3_ahorro_sembrado_sigue_mayor_sin_consumir_al_revertir(motores):
    with motores["cooperativa"].connect() as c:
        sub = c.execute(
            text(
                "SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE CodigoSubProducto='AHO001-PN'"
            )
        ).scalar_one()
        ultimo = c.execute(
            text(
                "SELECT s.UltimoNumero FROM ProductosFinancieros.ReglaNumeracion r JOIN ProductosFinancieros.SecuenciaCuenta s ON s.IdReglaNumeracion=COALESCE(r.IdReglaSecuencia,r.IdReglaNumeracion) WHERE r.IdSubProducto=:sub"
            ),
            {"sub": sub},
        ).scalar_one()
        assert ultimo >= 14
        assert n.siguiente_numero_cuenta(c, sub, "001") == "2200" + str(
            ultimo + 1
        ).zfill(8)
        c.rollback()


def test_ac1_dos_aperturas_reales_concurrentes_confirman_numeros_distintos(motores):
    with motores["cooperativa"].connect() as c:
        sub = c.execute(
            text(
                "SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE CodigoSubProducto='AHO001-PN'"
            )
        ).scalar_one()
    barrera = Barrier(2)

    def abrir():
        with motores["cooperativa"].begin() as c:
            barrera.wait(timeout=15)
            return abrir_real(c, sub)

    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        futuros = [ejecutor.submit(abrir) for _ in range(2)]
        numeros = [f.result(timeout=45) for f in futuros]
    assert len(set(numeros)) == 2
    assert all(re.fullmatch(r"2200[0-9]{8}", v) for v in numeros)


def test_ahorro_natural_y_juridico_comparten_contador(motores):
    with motores["cooperativa"].connect() as c:
        subs = (
            c.execute(
                text(
                    "SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE CodigoSubProducto IN('AHO001-PN','AHO001-PJ') ORDER BY CodigoSubProducto"
                )
            )
            .scalars()
            .all()
        )
        numeros = [n.siguiente_numero_cuenta(c, sub, "001") for sub in subs]
        assert len(subs) == 2 and len(set(numeros)) == 2
        c.rollback()


def test_ac2_regla_usada_no_admite_solicitar_otro_formato(motores):
    with motores["cooperativa"].begin() as c:
        sub = c.execute(
            text(
                "SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE CodigoSubProducto='AHO001-PN'"
            )
        ).scalar_one()
        with pytest.raises(HTTPException) as e:
            ProgramadorNumeracion(motores["seguridad"]).preparar(
                c, Objetivo("SubProducto", str(sub), None), {"prefijo": "3300"}, hoy()
            )
        assert e.value.status_code == 409 and e.value.detail["code"] == "REGLA_EN_USO"


def test_ac4_agotamiento_no_crea_cuenta_ni_desborda_longitud(motores):
    with motores["cooperativa"].connect() as c:
        sub = c.execute(
            text(
                "SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE CodigoSubProducto='AHO001-PN'"
            )
        ).scalar_one()
        c.execute(
            text(
                "UPDATE ProductosFinancieros.SecuenciaCuenta SET UltimoNumero=99999999 WHERE IdReglaNumeracion=(SELECT COALESCE(IdReglaSecuencia,IdReglaNumeracion) FROM ProductosFinancieros.ReglaNumeracion WHERE IdSubProducto=:sub)"
            ),
            {"sub": sub},
        )
        total = c.execute(text("SELECT COUNT(*) FROM Cuentas.Cuenta")).scalar_one()
        with pytest.raises(HTTPException) as e:
            abrir_real(c, sub)
        assert (
            e.value.status_code == 409 and e.value.detail["code"] == "SECUENCIA_AGOTADA"
        )
        assert (
            c.execute(text("SELECT COUNT(*) FROM Cuentas.Cuenta")).scalar_one() == total
        )
        c.rollback()


def test_solicitud_persistida_no_aplica_hasta_aprobar_otra_identidad(motores, caso):
    cola, objetivo, regla = caso
    id_ = cola.solicitar(MAKER, CODIGO, objetivo, regla, hoy(), CTX)
    with motores["cooperativa"].connect() as c:
        assert n.reglas(c, int(objetivo.id)) == []
    with pytest.raises(HTTPException) as e:
        cola.aprobar(MAKER, id_, None, CTX)
    assert e.value.status_code == 403
    assert cola.aprobar(CHECKER, id_, None, CTX)["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        filas = n.reglas(c, int(objetivo.id))
        assert (
            len(filas) == 1
            and filas[0]["IdSolicitud"] == id_
            and filas[0]["Prefijo"] == regla["prefijo"]
        )


def test_recuperacion_entre_bases_no_duplica_regla(motores, caso, monkeypatch):
    cola, objetivo, regla = caso
    id_ = cola.solicitar(MAKER, CODIGO, objetivo, regla, hoy(), CTX)
    original = cola._terminar

    def fallo(*args):
        raise SQLAlchemyError("Fallo QA tras commit cooperativo")

    monkeypatch.setattr(cola, "_terminar", fallo)
    with pytest.raises(HTTPException):
        cola.aprobar(CHECKER, id_, None, CTX)
    monkeypatch.setattr(cola, "_terminar", original)
    assert cola.ejecutar(id_, ORG, CHECKER, CTX)["estado"] == "Ejecutada"
    assert cola.ejecutar(id_, ORG, CHECKER, CTX)["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        assert len(n.reglas(c, int(objetivo.id))) == 1


def test_sql_protege_el_formato_de_una_regla_usada(motores):
    with pytest.raises(DBAPIError), motores["cooperativa"].begin() as c:
        c.execute(
            text(
                "UPDATE ProductosFinancieros.ReglaNumeracion SET Prefijo='9999' WHERE IdSubProducto=(SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE CodigoSubProducto='AHO001-PN')"
            )
        )
    with motores["cooperativa"].connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT Prefijo FROM ProductosFinancieros.ReglaNumeracion WHERE IdSubProducto=(SELECT IdSubProducto FROM ProductosFinancieros.SubProducto WHERE CodigoSubProducto='AHO001-PN')"
                )
            ).scalar_one()
            == "2200"
        )
