"""E1-12 opt-in: SQL Server local, base temporal propia; nunca lee .env.

E112_LOCAL_SQL_ENABLED=1. Lee fn_CalcularComision del laboratorio ATM02 local
para contrastar la carga con el cobrador existente, sin modificar ese laboratorio.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pyodbc
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("E112_LOCAL_SQL_ENABLED") != "1", reason="SQL Server local opt-in"
)
SCRIPTS = Path(__file__).resolve().parents[2] / "scripts/sql/e112"

TABLAS = """
CREATE TABLE Canal.Canal (IdCanal int PRIMARY KEY, CodigoCanal varchar(10), Estado char(1));
CREATE TABLE ProductosFinancieros.Producto (IdProducto int PRIMARY KEY);
CREATE TABLE ProductosFinancieros.SubProducto (IdSubProducto int PRIMARY KEY);
CREATE TABLE Organizacion.Usuarios (UsuarioID int PRIMARY KEY, Estado varchar(10));
INSERT Organizacion.Usuarios VALUES (900104,'Activo');
CREATE TABLE Transacciones.TipoTransaccion (
    CodigoTipo varchar(30) PRIMARY KEY, Nombre varchar(80) NOT NULL,
    Naturaleza char(1) NULL, AfectaSaldo bit NOT NULL, Descripcion varchar(250), Estado char(1) NOT NULL);
CREATE TABLE Transacciones.Comisiones (
    IdComision int IDENTITY PRIMARY KEY, CodigoComision varchar(10) NOT NULL,
    TipoCalculo varchar(10) NOT NULL, Valor decimal(12,4) NOT NULL,
    MontoMinimo decimal(18,2), MontoMaximo decimal(18,2), IdCanal int NOT NULL,
    VigenciaDesde date NOT NULL, VigenciaHasta date NULL, Estado char(1) NOT NULL,
    UNIQUE(IdComision,IdCanal));
CREATE TABLE Transacciones.ComisionTipoTransaccion (
    IdComisionTipoTransaccion int IDENTITY PRIMARY KEY,
    CodigoTipoTransaccion varchar(30) NOT NULL REFERENCES Transacciones.TipoTransaccion(CodigoTipo),
    IdCanal int NOT NULL REFERENCES Canal.Canal(IdCanal), IdComision int NOT NULL,
    VigenciaDesde date NOT NULL, VigenciaHasta date NULL, Estado char(1) NOT NULL DEFAULT 'A',
    RegistradoPor int NOT NULL,
    FOREIGN KEY(IdComision,IdCanal) REFERENCES Transacciones.Comisiones(IdComision,IdCanal),
    CHECK(VigenciaHasta IS NULL OR VigenciaHasta>VigenciaDesde), CHECK(Estado IN ('A','I')));
INSERT Canal.Canal VALUES (1,'VENT','A'),(2,'ATM','A'),(3,'WEB','A');
INSERT ProductosFinancieros.Producto VALUES (1);
INSERT ProductosFinancieros.SubProducto VALUES (1);
INSERT Transacciones.TipoTransaccion VALUES
 ('Retiro','Retiro','D',1,NULL,'A'),('Transferencia_Enviada','Transferencia','D',1,NULL,'A'),
 ('Cobro_Comision','Cobro generico','D',1,NULL,'A'),('Deposito','Deposito','C',1,NULL,'A');
INSERT Transacciones.Comisiones (CodigoComision,TipoCalculo,Valor,IdCanal,VigenciaDesde,Estado)
 VALUES ('RET','Fijo',0.45,2,'20200101','A'),('TRF','Fijo',0.20,3,'20200101','A'),('REP','Fijo',5,1,'20200101','A');
"""


def conectar(base):
    return pyodbc.connect(
        "DRIVER={ODBC Driver 18 for SQL Server};SERVER=lpc:.;"
        f"DATABASE={base};Trusted_Connection=yes;Encrypt=no;APP=E112_Local_Test;",
        autocommit=True,
        timeout=5,
    )


@pytest.fixture
def sql():
    base = "E112_Test_" + uuid4().hex
    with closing(conectar("master")) as master:
        assert (
            master.execute(
                "SELECT CONVERT(int,SERVERPROPERTY('EngineEdition'))"
            ).fetchval()
            != 5
        )
        # Identificador generado, exclusivamente en shared memory local.
        master.execute(f"CREATE DATABASE [{base}]")
        try:
            with closing(conectar(base)) as conn:
                assert conn.execute("SELECT DB_NAME()").fetchval() == base
                for schema in (
                    "Transacciones",
                    "Canal",
                    "ProductosFinancieros",
                    "Organizacion",
                ):
                    conn.execute(f"CREATE SCHEMA {schema}")
                conn.execute(TABLAS)
                with closing(conectar("CooperativaDB_ATM02_Lab")) as fuente:
                    identidad = fuente.execute("""
                        SELECT COLUMNPROPERTY(OBJECT_ID('Transacciones.ComisionTipoTransaccion'),
                          'IdComisionTipoTransaccion','IsIdentity')
                    """).fetchval()
                    assert identidad == 1
                    funcion = fuente.execute(
                        "SELECT OBJECT_DEFINITION(OBJECT_ID('Transacciones.fn_CalcularComision'))"
                    ).fetchval()
                    assert funcion and "ComisionTipoTransaccion" in funcion
                conn.execute(funcion)
                assert (
                    conn.execute(
                        "SELECT UsuarioID FROM Organizacion.Usuarios WHERE Estado='Activo'"
                    ).fetchval()
                    == 900104
                )
                contexto(conn, "registrado_por", 900104)
                yield conn, base
        finally:
            # Solo esta base temporal, con prefijo fijo y UUID generado arriba.
            master.execute(
                f"ALTER DATABASE [{base}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE"
            )
            master.execute(f"DROP DATABASE [{base}]")


def contexto(conn, clave, valor):
    conn.execute(
        "EXEC sys.sp_set_session_context @key=?, @value=?", "e112." + clave, valor
    )


def ejecutar(conn, archivo):
    cursor = conn.execute((SCRIPTS / archivo).read_text(encoding="utf-8"))
    while cursor.nextset():
        pass


def monto(conn, tipo, canal, fecha):
    return conn.execute(
        """
        SELECT COALESCE(SUM(MontoComision),0) FROM Transacciones.fn_CalcularComision(?,?,100,?)
    """,
        tipo,
        canal,
        fecha,
    ).fetchval()


def test_migracion_repetible_y_limites(sql):
    conn, _ = sql
    ejecutar(conn, "001_exoneraciones.up.sql")
    ejecutar(conn, "001_exoneraciones.up.sql")
    assert (
        conn.execute(
            "SELECT is_nullable FROM sys.columns WHERE object_id=OBJECT_ID('Transacciones.Comisiones') AND name='IdCuentaContableIngreso'"
        ).fetchval()
        == 1
    )
    for porcentaje, cupo in [(0, 0), (100, 3), (50, None)]:
        conn.execute(
            """
            INSERT Transacciones.ExoneracionComision
              (IdComision,PorcentajeExonerado,OperacionesGratisMes,VigenciaDesde)
            VALUES (1,?,?, '20261116')
        """,
            porcentaje,
            cupo,
        )
    for porcentaje, cupo in [(-0.01, 0), (100.01, 0), (50, -1)]:
        with pytest.raises(pyodbc.IntegrityError):
            conn.execute(
                """
                INSERT Transacciones.ExoneracionComision
                  (IdComision,PorcentajeExonerado,OperacionesGratisMes,VigenciaDesde)
                VALUES (1,?,?,'20261116')
            """,
                porcentaje,
                cupo,
            )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ExoneracionComision"
        ).fetchval()
        == 3
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM sys.check_constraints WHERE parent_object_id=OBJECT_ID('Transacciones.ExoneracionComision') AND (is_disabled=1 OR is_not_trusted=1)"
        ).fetchval()
        == 0
    )


def test_carga_repetible_fecha_real_y_aislamiento(sql):
    conn, _ = sql
    ejecutar(conn, "002_cargar_tarifas.sql")
    fecha = conn.execute(
        "SELECT CONVERT(date,SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time')"
    ).fetchval()
    ejecutar(conn, "002_cargar_tarifas.sql")
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion WHERE VigenciaDesde=? AND RegistradoPor=900104",
            fecha,
        ).fetchval()
        == 2
    )
    assert str(monto(conn, "Retiro", 2, fecha)) == "0.45"
    assert str(monto(conn, "Transferencia_Enviada", 3, fecha)) == "0.20"
    assert monto(conn, "Cobro_Comision", 1, fecha) == 0
    assert monto(conn, "Deposito", 1, fecha) == 0
    contexto(conn, "fecha_efectiva", "2099-01-01")
    ejecutar(conn, "002_cargar_tarifas.sql")
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion"
        ).fetchval()
        == 2
    )


@pytest.mark.parametrize(
    "inicio,fin", [("20200101", None), ("20990101", None), ("20200101", "20990101")]
)
def test_conflicto_revierte_toda_carga(sql, inicio, fin):
    conn, _ = sql
    contexto(conn, "fecha_efectiva", "2026-11-16")
    # Otra comisión para el mismo evento/canal, sin alterar la tarifa esperada.
    conn.execute(
        "INSERT Transacciones.Comisiones (CodigoComision,TipoCalculo,Valor,IdCanal,VigenciaDesde,Estado) VALUES ('OTRA','Fijo',1,2,'20200101','A')"
    )
    conn.execute(
        "INSERT Transacciones.ComisionTipoTransaccion (CodigoTipoTransaccion,IdCanal,IdComision,VigenciaDesde,VigenciaHasta,RegistradoPor) VALUES ('Retiro',2,4,?,?,900104)",
        inicio,
        fin,
    )
    with pytest.raises(pyodbc.Error, match="vigencia incompatible"):
        ejecutar(conn, "002_cargar_tarifas.sql")
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion"
        ).fetchval()
        == 1
    )


def test_historia_fin_exclusivo_no_solapa(sql):
    conn, _ = sql
    contexto(conn, "fecha_efectiva", "2026-11-16")
    conn.execute(
        "INSERT Transacciones.ComisionTipoTransaccion (CodigoTipoTransaccion,IdCanal,IdComision,VigenciaDesde,VigenciaHasta,RegistradoPor) VALUES ('Retiro',2,1,'20200101','20261116',900104)"
    )
    ejecutar(conn, "002_cargar_tarifas.sql")
    assert str(monto(conn, "Retiro", 2, "20261116")) == "0.45"
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion"
        ).fetchval()
        == 3
    )


@pytest.mark.parametrize(
    "clave,valor", [("registrado_por", None), ("fecha_efectiva", "invalida")]
)
def test_parametros_obligatorios(sql, clave, valor):
    conn, _ = sql
    contexto(conn, clave, valor)
    with pytest.raises(pyodbc.Error):
        ejecutar(conn, "002_cargar_tarifas.sql")
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion"
        ).fetchval()
        == 0
    )


def test_reposicion_propuesta_unica_tarifa_no_es_flujo_completo(sql):
    conn, _ = sql
    with pytest.raises(pyodbc.Error, match="Propuesta pendiente"):
        ejecutar(conn, "003_propuesta_reposicion.sql")
    contexto(conn, "incluir_reposicion", 1)
    with pytest.raises(pyodbc.Error, match="Catalogos"):
        ejecutar(conn, "002_cargar_tarifas.sql")
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion"
        ).fetchval()
        == 0
    )
    contexto(conn, "aprobar_evento_reposicion", 1)
    ejecutar(conn, "003_propuesta_reposicion.sql")
    ejecutar(conn, "003_propuesta_reposicion.sql")
    ejecutar(conn, "002_cargar_tarifas.sql")
    ejecutar(conn, "002_cargar_tarifas.sql")
    fecha = conn.execute(
        "SELECT CONVERT(date,SYSDATETIMEOFFSET() AT TIME ZONE 'SA Pacific Standard Time')"
    ).fetchval()
    assert str(monto(conn, "Reposicion_Tarjeta", 1, fecha)) == "5.00"
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.fn_CalcularComision('Reposicion_Tarjeta',1,100,?)",
            fecha,
        ).fetchval()
        == 1
    )
    assert monto(conn, "Cobro_Comision", 1, fecha) == 0
    assert monto(conn, "Deposito", 1, fecha) == 0
    assert monto(conn, "Retiro", 1, fecha) == 0


def test_cargas_concurrentes(sql):
    conn, base = sql

    def cargar(_):
        with closing(conectar(base)) as otra:
            contexto(otra, "registrado_por", 900104)
            ejecutar(otra, "002_cargar_tarifas.sql")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(cargar, range(2)))
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion"
        ).fetchval()
        == 2
    )


def test_corrige_check_antiguo_y_no_pierde_datos(sql):
    conn, _ = sql
    ejecutar(conn, "001_exoneraciones.up.sql")
    conn.execute("""
        ALTER TABLE Transacciones.ExoneracionComision DROP CONSTRAINT CK_Exoneracion_Porcentaje;
        ALTER TABLE Transacciones.ExoneracionComision ADD CONSTRAINT CK_Exoneracion_Porcentaje
            CHECK(PorcentajeExonerado>0 AND PorcentajeExonerado<=100);
        INSERT Transacciones.ExoneracionComision (IdComision,VigenciaDesde) VALUES(1,'20261116');
    """)
    ejecutar(conn, "001_exoneraciones.up.sql")
    conn.execute(
        "INSERT Transacciones.ExoneracionComision (IdComision,VigenciaDesde,PorcentajeExonerado) VALUES(1,'20261116',0)"
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ExoneracionComision"
        ).fetchval()
        == 2
    )
    # Datos inválidos preexistentes no se arreglan silenciosamente.
    conn.execute(
        "ALTER TABLE Transacciones.ExoneracionComision NOCHECK CONSTRAINT CK_Exoneracion_CupoMes"
    )
    conn.execute("UPDATE Transacciones.ExoneracionComision SET OperacionesGratisMes=-1")
    with pytest.raises(pyodbc.Error):
        ejecutar(conn, "001_exoneraciones.up.sql")
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ExoneracionComision WHERE OperacionesGratisMes=-1"
        ).fetchval()
        == 2
    )


@pytest.mark.parametrize("secuencia", [False, True])
def test_generador_id(sql, secuencia):
    conn, _ = sql
    conn.execute("DROP TABLE Transacciones.ComisionTipoTransaccion")
    if secuencia:
        conn.execute("CREATE SEQUENCE Transacciones.SeqComision AS int START WITH 1")
    defecto = "DEFAULT (NEXT VALUE FOR Transacciones.SeqComision)" if secuencia else ""
    conn.execute(f"""
        CREATE TABLE Transacciones.ComisionTipoTransaccion (
            IdComisionTipoTransaccion int NOT NULL {defecto} PRIMARY KEY,
            CodigoTipoTransaccion varchar(30), IdCanal int, IdComision int,
            VigenciaDesde date, VigenciaHasta date NULL, Estado char(1), RegistradoPor int NOT NULL)
    """)
    if secuencia:
        ejecutar(conn, "002_cargar_tarifas.sql")
        ejecutar(conn, "002_cargar_tarifas.sql")
        assert (
            conn.execute(
                "SELECT COUNT(DISTINCT IdComisionTipoTransaccion) FROM Transacciones.ComisionTipoTransaccion"
            ).fetchval()
            == 2
        )
    else:
        with pytest.raises(pyodbc.Error, match="ID sin IDENTITY"):
            ejecutar(conn, "002_cargar_tarifas.sql")
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion"
            ).fetchval()
            == 0
        )


def test_duplicados_existentes_y_tarifa_distinta_aborta(sql):
    conn, _ = sql
    conn.execute("UPDATE Transacciones.Comisiones SET Valor=0.46 WHERE IdComision=1")
    with pytest.raises(pyodbc.Error, match="Catalogos"):
        ejecutar(conn, "002_cargar_tarifas.sql")
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion"
        ).fetchval()
        == 0
    )
    conn.execute("UPDATE Transacciones.Comisiones SET Valor=0.45 WHERE IdComision=1")
    conn.execute("""
        INSERT Transacciones.ComisionTipoTransaccion
            (CodigoTipoTransaccion,IdCanal,IdComision,VigenciaDesde,Estado,RegistradoPor)
        VALUES ('Retiro',2,1,'20200101','A',900104),('Retiro',2,1,'20200101','A',900104)
    """)
    with pytest.raises(pyodbc.Error, match="duplicadas"):
        ejecutar(conn, "002_cargar_tarifas.sql")
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM Transacciones.ComisionTipoTransaccion"
        ).fetchval()
        == 2
    )
