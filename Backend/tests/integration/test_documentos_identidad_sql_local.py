"""Integración #42 con una base SQL Server local y desechable."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pyodbc
import pytest
from fastapi import HTTPException
from sqlalchemy import Connection, create_engine, text

from app.core.migraciones.archivos import lotes
from app.modules.clientes import documentos_identidad
from app.modules.clientes.schemas import ClienteCreate, ConsultaDocumentoBody

pytestmark = pytest.mark.skipif(
    os.getenv("E542_SQL_LOCAL") != "1",
    reason="requiere SQL Server local y permiso para crear una base desechable",
)
HOY = date(2026, 11, 27)
MIGRACION = (
    Path(__file__).resolve().parents[2]
    / "migrations/cooperativa/202611271500_clientes_documentos.up.sql"
)


@pytest.fixture
def bd():
    instancia = os.getenv("E542_LOCALDB_INSTANCE", "EnquoAccesosQA")
    if not instancia or not all(
        c.isascii() and (c.isalnum() or c in "_-") for c in instancia
    ):
        pytest.fail("Indica únicamente el nombre de una instancia LocalDB.")

    def conectar(base: str, *, autocommit: bool = False):
        return pyodbc.connect(
            rf"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER=(localdb)\{instancia};"
            f"DATABASE={base};Trusted_Connection=yes;TrustServerCertificate=yes;",
            timeout=5,
            autocommit=autocommit,
        )

    nombre = "E542_Test_" + uuid4().hex
    admin = create_engine(
        "mssql+pyodbc://",
        creator=lambda: conectar("master", autocommit=True),
        isolation_level="AUTOCOMMIT",
    )
    motor = None
    creada = False
    try:
        with admin.connect() as conn:
            conn.exec_driver_sql(f"CREATE DATABASE [{nombre}]")
            creada = True
        motor = create_engine(
            "mssql+pyodbc://", creator=lambda: conectar(nombre), hide_parameters=True
        )
        with motor.begin() as conn:
            conn.exec_driver_sql("CREATE SCHEMA Catalogo")
            conn.exec_driver_sql("CREATE SCHEMA Clientes")
            conn.exec_driver_sql("""
                CREATE TABLE Catalogo.Paises (CodigoPais char(3) PRIMARY KEY);
                INSERT Catalogo.Paises VALUES ('ECU'), ('COL');
                CREATE TABLE Clientes.Cliente (
                    IdCliente int IDENTITY PRIMARY KEY,
                    TipoDocumento varchar(10) NOT NULL,
                    Identificacion varchar(13) NOT NULL,
                    TipoCliente varchar(10) NOT NULL DEFAULT 'Natural',
                    Estado varchar(20) NOT NULL DEFAULT 'Activo',
                    CONSTRAINT UQ_Cliente_Identificacion UNIQUE (Identificacion),
                    CONSTRAINT CK_Cliente_TipoDocumento CHECK (TipoDocumento IN ('C','R','P')),
                    CONSTRAINT CK_Cliente_Identificacion CHECK (LEN(Identificacion) > 0)
                );
                INSERT Clientes.Cliente (TipoDocumento, Identificacion) VALUES ('P', 'SINTETICO01');
            """)
            for lote in lotes(MIGRACION.read_text(encoding="utf-8")):
                conn.exec_driver_sql(lote)
        yield motor
    finally:
        if motor is not None:
            motor.dispose()
        try:
            if creada:
                with admin.connect() as conn:
                    conn.exec_driver_sql(
                        f"ALTER DATABASE [{nombre}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                        f"DROP DATABASE [{nombre}];"
                    )
        finally:
            admin.dispose()


def _registrar(conn: Connection, tipo: str, numero: str, pais: str | None = None):
    vencimiento = date(2027, 11, 27) if pais else None
    payload = ClienteCreate.model_construct(
        tipo_documento=tipo,
        identificacion=numero,
        tipo_cliente="Natural",
        codigo_pais_emision=pais,
        fecha_emision=None,
        fecha_vencimiento=vencimiento,
    )
    consulta = documentos_identidad.preparar_alta(conn, payload, HOY)
    id_cliente = conn.execute(
        text("""
            INSERT Clientes.Cliente(TipoDocumento, Identificacion)
            OUTPUT inserted.IdCliente VALUES (:tipo, :numero)
        """),
        {"tipo": tipo, "numero": numero},
    ).scalar_one()
    documentos_identidad.insertar(
        conn, id_cliente, consulta, None, vencimiento, principal=True
    )
    return id_cliente


def test_migracion_preserva_pasaporte_heredado_e_identifica_por_emisor(bd):
    def pasaporte(numero, pais):
        return ConsultaDocumentoBody(
            tipo_documento="PAS", numero=numero, codigo_pais_emision=pais
        )

    with bd.begin() as conn:
        legado = documentos_identidad.consultar(
            conn, pasaporte("SINTETICO01", "ECU"), HOY
        )
        assert legado.existe and legado.estado_documento == "POR_COMPLETAR"
        assert legado.id_cliente is None
        ecu = _registrar(conn, "P", "SINTETICO02", "ECU")
        col = _registrar(conn, "P", "SINTETICO02", "COL")
        assert ecu != col
        assert (
            documentos_identidad.consultar(
                conn, pasaporte("SINTETICO02", "ECU"), HOY
            ).id_cliente
            == ecu
        )
        resultado = documentos_identidad.consultar(
            conn,
            pasaporte("SINTETICO02", "COL"),
            date(2027, 11, 28),
        )
        assert resultado.id_cliente == col and resultado.estado_documento == "VENCIDO"


@pytest.mark.parametrize(
    "documentos",
    [
        [("P", "SINTETICO03", "ECU"), ("P", "SINTETICO03", "ECU")],
        [("C", "1712345675", None), ("R", "1712345675001", None)],
    ],
)
def test_altas_concurrentes_admiten_una_sola_ficha(bd, documentos):
    salida = Barrier(2, timeout=10)

    def registrar(documento):
        try:
            with bd.begin() as conn:
                salida.wait()
                _registrar(conn, *documento)
            return "REGISTRADO"
        except HTTPException as exc:
            return exc.detail["code"]

    with ThreadPoolExecutor(max_workers=2) as hilos:
        assert sorted(hilos.map(registrar, documentos)) == [
            "DOCUMENTO_DUPLICADO",
            "REGISTRADO",
        ]
