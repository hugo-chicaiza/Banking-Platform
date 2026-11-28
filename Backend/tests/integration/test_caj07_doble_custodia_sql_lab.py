"""SQL Server local descartable. CAJ07_SQL_PROC apunta a la definición oficial del SP."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, nullcontext
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import uuid4

import pyodbc
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.modules.caja import dotaciones, service
from app.modules.caja import repository as caja_repo
from app.modules.caja.schemas import JornadaOpen, SolicitarDotacion
from app.modules.contabilidad import repository as contabilidad_repo
from tests.caja_contexto import usuario

pytestmark = pytest.mark.skipif(
    not os.getenv("CAJ07_SQL_PROC"),
    reason="Requiere definición oficial del SP para un SQL Server local",
)
ESQUEMA = """
CREATE SCHEMA Caja;
GO
CREATE SCHEMA Boveda;
GO
CREATE SCHEMA Organizacion;
GO
CREATE SCHEMA Contabilidad;
GO
CREATE SCHEMA Catalogo;
GO
CREATE SCHEMA Transacciones;
GO
CREATE TABLE Organizacion.Agencia(IdAgencia char(3) PRIMARY KEY);
CREATE TABLE Organizacion.Usuarios(UsuarioID int PRIMARY KEY, Nombres varchar(40),
 Apellidos varchar(40), Estado varchar(20), KeyUsuario varchar(50), RolesWorkOS varchar(80), AgenciaID int);
CREATE TABLE Organizacion.UsuarioAgencia(UsuarioID int, IdAgencia char(3), Activo bit,
 PRIMARY KEY(UsuarioID,IdAgencia));
INSERT Organizacion.Usuarios VALUES
 (7,'Titular','Caja','Activo','cajero','CAJERO,SUPERVISOR',1),
 (9,'Ana','Perez','Activo','supervisor','SUPERVISOR',2),
 (10,'Luis','Otro','Activo','otra','SUPERVISOR',2),
 (11,'Jose','Inactivo','Inactivo','inactivo','SUPERVISOR',1),
 (12,'Carlos','Caja','Activo','otro-cajero','CAJERO',1),
 (13,'Baja','Agencia','Activo','baja','SUPERVISOR',1),
 (14,'Sin','Vinculo','Activo',NULL,'SUPERVISOR',1);
INSERT Organizacion.UsuarioAgencia VALUES (9,'001',1),(13,'001',0);

CREATE TABLE Contabilidad.FechaContable(IdFechaContable int PRIMARY KEY, Fecha date,
 EsDiaContable bit, EsFeriado bit, EsFinDeSemana bit, HoraCorte time);
CREATE TABLE Contabilidad.PeriodoContable(Anio int, Mes int, Estado varchar(20));
CREATE TABLE Contabilidad.TiposAsiento(IdTipoAsiento int PRIMARY KEY, Codigo varchar(30), Estado char(1), EsManual bit);
CREATE TABLE Contabilidad.PlantillaAsiento(IdPlantillaAsiento int PRIMARY KEY,
 IdConceptoContable int, Origen varchar(20), IdTipoAsiento int, Nombre varchar(100),
 Estado bit, CodigoPlantilla varchar(30), VigenciaDesde date, VigenciaHasta date, Version int);
CREATE TABLE Contabilidad.CuentasContables(IdCuentaContable int PRIMARY KEY, Estado bit,
 EsImputable bit, CodigoCuenta varchar(20), NombreCuenta varchar(100));
CREATE TABLE Contabilidad.PlantillaAsientoDetalle(IdPlantillaAsiento int, Orden int,
 IdCuentaContable int, TipoMovimiento varchar(10), ComponenteImporte varchar(30),
 OrigenCuenta varchar(20), CodigoRol varchar(30));
CREATE TABLE Contabilidad.AsientoContable(IdAsientoContable int IDENTITY PRIMARY KEY,
 NumeroAsiento varchar(20), FechaAsiento date, FechaSistema datetime2, IdTipoAsiento int,
 Origen varchar(20), Concepto varchar(100), TotalDebito decimal(18,2), TotalCredito decimal(18,2),
 Estado varchar(20), IdUsuarioCreacion int, IdAgencia char(3), IdConceptoContable int,
 IdFechaContable int, IdPlantillaAsiento int, ClaveEventoContable varchar(100) UNIQUE,
 HuellaEventoContable char(64), IdTransaccion bigint, IdAsientoReversion int);
CREATE TABLE Contabilidad.MovimientosContables(IdCuentaContable int, IdTransaccion bigint,
 IdAgencia char(3), TipoMovimiento varchar(10), Monto decimal(18,2), FechaHora datetime2,
 IdAsientoContable int);
CREATE TABLE Catalogo.Denominacion(IdDenominacion int PRIMARY KEY,Valor decimal(10,2),Estado char(1));
CREATE TABLE Boveda.Boveda(IdBoveda int PRIMARY KEY,IdAgencia char(3),Estado char(1),
 SaldoActual decimal(18,2),LimiteMinimo decimal(18,2),LimiteMaximo decimal(18,2));
CREATE TABLE Boveda.BovedaDenominacion(IdBoveda int,IdDenominacion int,CantidadActual int,
 FechaActualizacion datetime2,PRIMARY KEY(IdBoveda,IdDenominacion));
CREATE TABLE Boveda.MovimientoBoveda(IdMovimiento bigint IDENTITY PRIMARY KEY,IdBoveda int,
 IdBovedaContraparte int,TipoMovimiento varchar(30),Naturaleza char(1),Monto decimal(18,2),
 SaldoAnterior decimal(18,2),SaldoPosterior decimal(18,2),AutorizadoPor int,
 IdUsuarioMovimiento int,Observaciones varchar(300),FechaMovimiento datetime2,
 IdFechaContable int,IdAsientoContable int NULL);
CREATE TABLE Boveda.MovimientoBovedaDenominacion(IdMovimiento bigint,IdDenominacion int,Cantidad int);
CREATE TABLE Caja.CajaFisica(IdCajaFisica int PRIMARY KEY, IdAgencia char(3),
 CodigoCaja varchar(10), Estado bit, LimiteEfectivoCaja decimal(18,2));
INSERT Caja.CajaFisica VALUES(1,'001','CJ01',1,200),(2,'001','CJ02',1,200);
CREATE TABLE Caja.JornadasCaja(IdJornadaCaja int IDENTITY(55,1) PRIMARY KEY,IdUsuario int,IdAgencia char(3),
 Estado varchar(20),DineroInicial decimal(18,2),IdCajaFisica int,FechaHoraApertura datetime2,
 FechaHoraCierre datetime2,Observacion varchar(500));
CREATE UNIQUE INDEX UX_JornadasCaja_Caja_Abierta ON Caja.JornadasCaja(IdCajaFisica) WHERE Estado='ABIERTA';
CREATE UNIQUE INDEX UX_JornadasCaja_Usuario_Abierta ON Caja.JornadasCaja(IdUsuario) WHERE Estado='ABIERTA';
ALTER TABLE Caja.JornadasCaja ADD UNIQUE(IdJornadaCaja,IdUsuario,DineroInicial);
CREATE TABLE Caja.CuadreCaja(
 IdJornadaCaja int PRIMARY KEY, IdUsuario int, SaldoInicial decimal(18,2),
 FOREIGN KEY(IdJornadaCaja,IdUsuario,SaldoInicial)
 REFERENCES Caja.JornadasCaja(IdJornadaCaja,IdUsuario,DineroInicial)
);
CREATE TABLE Caja.TipoMovimientoCaja(IdTipoMovimientoCaja int PRIMARY KEY,Naturaleza char(1));
CREATE TABLE Transacciones.Transaccion(IdTransaccion bigint PRIMARY KEY,TipoTransaccion varchar(20));
CREATE TABLE Caja.MovimientosCaja(IdJornadaCaja int,IdTipoMovimiento int,IdTransaccion bigint,Monto decimal(18,2));
CREATE TABLE Caja.DevolucionesCaja(IdJornadaCaja int,Monto decimal(18,2));
CREATE TABLE Caja.DotacionesCaja(IdDotacionCaja int IDENTITY PRIMARY KEY,IdJornadaCaja int,
 IdBoveda int,AutorizadoPor int,Monto decimal(18,2),TipoDotacion varchar(20),
 Observacion varchar(500),IdFechaContable int,IdMovimientoBoveda bigint,Estado varchar(20) DEFAULT 'REGISTRADA');
CREATE TABLE Caja.DotacionCajaDenominacion(IdDotacionCaja int,IdDenominacion int,Cantidad int);
INSERT Organizacion.Agencia VALUES ('001'),('002');
INSERT Contabilidad.FechaContable VALUES(1,'20261126',1,0,0,'19:00');
INSERT Contabilidad.PeriodoContable VALUES(2026,11,'ABIERTO');
INSERT Contabilidad.TiposAsiento VALUES(1,'CAJA_DOTACION','A',0);
INSERT Contabilidad.PlantillaAsiento VALUES(1,1,'CAJA',1,'Dotación',1,'DOT_CAJA','20261126',NULL,1);
INSERT Contabilidad.CuentasContables VALUES(1,1,1,'11010510','Caja'),(2,1,1,'11010505','Bóveda');
INSERT Contabilidad.PlantillaAsientoDetalle VALUES
    (1,1,1,'DEBITO','PRINCIPAL','FIJA',NULL),(1,2,2,'CREDITO','PRINCIPAL','FIJA',NULL);
INSERT Catalogo.Denominacion VALUES(1,10,'A');
INSERT Caja.JornadasCaja VALUES(7,'001','ABIERTA',0,1,SYSUTCDATETIME(),NULL,NULL);
INSERT Boveda.Boveda VALUES(2,'001','A',250,50,1000);
INSERT Boveda.BovedaDenominacion VALUES(2,1,25,NULL);
GO
CREATE FUNCTION Contabilidad.fn_IdFechaContable(@Instante datetime2) RETURNS int AS BEGIN RETURN 1; END;
GO
CREATE PROCEDURE Contabilidad.usp_GenerarNumeroAsiento
 @FechaAsiento date,@IdAgencia char(3),@NumeroAsiento varchar(20) OUTPUT
AS BEGIN SET @NumeroAsiento='CAJ07-LAB'; END;
GO
CREATE PROCEDURE Contabilidad.usp_ContabilizarAsiento @IdAsientoContable int
AS BEGIN
    SET NOCOUNT ON;
    UPDATE a SET Estado='CONTABILIZADO', TotalDebito=d.Debe, TotalCredito=d.Haber
    FROM Contabilidad.AsientoContable a
    CROSS APPLY (SELECT SUM(CASE WHEN TipoMovimiento='DEBITO' THEN Monto ELSE 0 END) Debe,
        SUM(CASE WHEN TipoMovimiento='CREDITO' THEN Monto ELSE 0 END) Haber
        FROM Contabilidad.MovimientosContables m WHERE m.IdAsientoContable=a.IdAsientoContable) d
    WHERE a.IdAsientoContable=@IdAsientoContable AND d.Debe=d.Haber AND d.Debe>0;
    IF @@ROWCOUNT<>1 THROW 57920,N'El asiento de laboratorio no cuadra.',1;
END;
GO
CREATE PROCEDURE Contabilidad.usp_E401_AplicarSaldos @IdAsiento int AS BEGIN SET NOCOUNT ON; END;
"""


@pytest.fixture
def db_local(monkeypatch):
    proc = Path(os.environ["CAJ07_SQL_PROC"])
    nombre = f"CooperativaDB_CAJ07_Lab_{uuid4().hex[:10]}"
    cadena = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=localhost;Trusted_Connection=yes;Encrypt=yes;TrustServerCertificate=yes;"
    pyodbc.pooling = False
    with closing(
        pyodbc.connect(cadena + "DATABASE=master;", autocommit=True)
    ) as master:
        equipo = master.execute("SELECT SERVERPROPERTY('MachineName')").fetchval()
        assert equipo.casefold() == os.environ["COMPUTERNAME"].casefold()
        master.execute(f"CREATE DATABASE [{nombre}]")
        destino = cadena + f"DATABASE={nombre};"
        engine = create_engine(
            "mssql+pyodbc://", creator=lambda: pyodbc.connect(destino)
        )
        try:
            with closing(pyodbc.connect(destino, autocommit=True)) as db:
                for lote in ESQUEMA.strip().split("\nGO\n"):
                    db.execute(lote)
                definicion = proc.read_text(encoding="utf-8")
                assert definicion.lstrip().upper().startswith("CREATE")
                db.execute(definicion)
                archivo = (
                    Path(__file__).resolve().parents[2]
                    / "migrations/cooperativa/202611261800_caja_solicitudes_dotacion.up.sql"
                )
                db.execute(
                    "EXEC sys.sp_set_session_context N'migration_database', ?", nombre
                )
                migracion = archivo.read_text(encoding="utf-8")
                db.execute(migracion)
                db.execute(migracion)
            # El entorno mínimo carece del catálogo de auditoría y del mayor E4-01 completo.
            from unittest.mock import MagicMock

            monkeypatch.setattr(dotaciones, "auditar", MagicMock())

            monkeypatch.setattr(caja_repo, "get_engine", lambda _: engine)
            yield engine
        finally:
            engine.dispose()
            master.execute(f"DROP DATABASE [{nombre}]")


def _solicitar(
    engine,
    *,
    clave="pieza",
    cantidad=10,
    tipo="INICIAL",
    autorizado=9,
    actor=7,
    jornada=55,
):
    with engine.connect() as conn:
        return dotaciones.solicitar(
            conn,
            usuario("CAJERO"),
            actor,
            jornada,
            SolicitarDotacion.model_validate(
                {
                    "idBoveda": 2,
                    "tipoDotacion": tipo,
                    "autorizadoPor": autorizado,
                    "desglose": [{"idDenominacion": 1, "cantidad": cantidad}],
                }
            ),
            clave,
        )


def _confirmar(engine, id_solicitud):
    with engine.connect() as conn:
        return dotaciones.confirmar(
            conn, usuario("SUPERVISOR"), 9, id_solicitud, "127.0.0.1"
        )


def _efectos(engine):
    with engine.connect() as conn:
        return tuple(
            conn.execute(
                text("""
            SELECT (SELECT SaldoActual FROM Boveda.Boveda WHERE IdBoveda=2),
                   (SELECT CantidadActual FROM Boveda.BovedaDenominacion WHERE IdBoveda=2),
                   (SELECT COUNT(*) FROM Boveda.MovimientoBoveda),
                   (SELECT COUNT(*) FROM Caja.DotacionesCaja),
                   (SELECT COUNT(*) FROM Contabilidad.AsientoContable),
                   (SELECT DineroInicial FROM Caja.JornadasCaja WHERE IdJornadaCaja=55)
        """)
            ).one()
        )


def test_pendiente_reintento_y_confirmaciones_concurrentes(db_local):
    solicitud = _solicitar(db_local)
    assert _solicitar(db_local).id_solicitud == solicitud.id_solicitud
    with pytest.raises(HTTPException, match="IDEMPOTENCIA_CONFLICTO"):
        _solicitar(db_local, cantidad=9)
    assert _efectos(db_local) == (250, 25, 0, 0, 0, 0)
    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(
            pool.map(lambda _: _confirmar(db_local, solicitud.id_solicitud), range(2))
        )
    assert sorted(repetida for _, repetida in resultados) == [False, True]
    assert len({dto.id_dotacion_caja for dto, _ in resultados}) == 1
    assert len({dto.id_asiento_contable for dto, _ in resultados}) == 1
    assert _efectos(db_local) == (150, 15, 1, 1, 1, 100)
    with db_local.connect() as conn:
        lineas = conn.execute(
            text("""
            SELECT t.Codigo, c.CodigoCuenta, l.TipoMovimiento, l.Monto
            FROM Contabilidad.AsientoContable a
            JOIN Caja.DotacionesCaja d ON d.IdAsientoContable=a.IdAsientoContable
            JOIN Boveda.MovimientoBoveda m ON m.IdAsientoContable=a.IdAsientoContable
                AND m.IdMovimiento=d.IdMovimientoBoveda
            JOIN Contabilidad.TiposAsiento t ON t.IdTipoAsiento=a.IdTipoAsiento
            JOIN Contabilidad.MovimientosContables l ON l.IdAsientoContable=a.IdAsientoContable
            JOIN Contabilidad.CuentasContables c ON c.IdCuentaContable=l.IdCuentaContable
            WHERE a.Estado='CONTABILIZADO' AND a.IdUsuarioCreacion=9
            ORDER BY c.CodigoCuenta
        """)
        ).all()
    assert lineas == [
        ("CAJA_DOTACION", "11010505", "CREDITO", 100),
        ("CAJA_DOTACION", "11010510", "DEBITO", 100),
    ]


@pytest.mark.parametrize(
    ("cambio", "codigo"),
    [
        ("UPDATE Caja.JornadasCaja SET Estado='CERRADA'", "JORNADA_NO_ABIERTA"),
        ("UPDATE Boveda.Boveda SET Estado='I'", "BOVEDA_NO_ACTIVA"),
        ("UPDATE Boveda.Boveda SET IdAgencia='002'", "BOVEDA_OTRA_AGENCIA"),
        ("UPDATE Boveda.Boveda SET SaldoActual=90", "51014"),
        ("UPDATE Boveda.BovedaDenominacion SET CantidadActual=9", "51015"),
        (
            "UPDATE Catalogo.Denominacion SET Valor=9",
            "SOLICITUD_DOTACION_DESACTUALIZADA",
        ),
    ],
)
def test_confirmacion_revalida_cambios(db_local, cambio, codigo):
    solicitud = _solicitar(db_local)
    with db_local.begin() as conn:
        conn.exec_driver_sql(cambio)
    antes = _efectos(db_local)
    with pytest.raises((HTTPException, DBAPIError), match=codigo):
        _confirmar(db_local, solicitud.id_solicitud)
    assert _efectos(db_local) == antes


def test_fallo_contable_revierte_y_permite_reintento(db_local, monkeypatch):
    solicitud = _solicitar(db_local)
    contabilizar = contabilidad_repo.contabilizar_asiento

    def error(conn, id_asiento):
        contabilizar(conn, id_asiento)
        raise RuntimeError("Fallo contable simulado")

    with monkeypatch.context() as mp:
        mp.setattr(contabilidad_repo, "contabilizar_asiento", error)
        with pytest.raises(RuntimeError, match="Fallo contable"):
            _confirmar(db_local, solicitud.id_solicitud)
    assert _efectos(db_local) == (250, 25, 0, 0, 0, 0)
    with db_local.connect() as conn:
        detalles = conn.execute(
            text("""
            SELECT (SELECT COUNT(*) FROM Boveda.MovimientoBovedaDenominacion),
                   (SELECT COUNT(*) FROM Caja.DotacionCajaDenominacion),
                   (SELECT COUNT(*) FROM Contabilidad.MovimientosContables)
        """)
        ).one()
        assert tuple(detalles) == (0, 0, 0)
    assert _solicitar(db_local).estado == "PENDIENTE"
    assert _confirmar(db_local, solicitud.id_solicitud)[1] is False


def test_rechazo_no_aplica_efectivo(db_local):
    solicitud = _solicitar(db_local)
    with db_local.connect() as conn:
        estado = dotaciones.rechazar(
            conn, usuario("SUPERVISOR"), 9, solicitud.id_solicitud, "Sin entrega"
        )
    assert estado.estado == "RECHAZADA"
    with pytest.raises(HTTPException, match="SOLICITUD_DOTACION_RESUELTA"):
        _confirmar(db_local, solicitud.id_solicitud)
    assert _efectos(db_local) == (250, 25, 0, 0, 0, 0)


@pytest.mark.parametrize("actores", [(11, 11), (11, 12)])
def test_caj03_concurrencia_de_cajero_y_caja(db_local, monkeypatch, actores):
    monkeypatch.setattr(service, "proteger_apertura_caja", lambda *_: nullcontext())
    monkeypatch.setattr(
        service,
        "auditar",
        lambda *_: nullcontext(type("Registro", (), {"confirmar": lambda *_: None})()),
    )
    monkeypatch.setattr(
        caja_repo,
        "obtener_caja_fisica",
        lambda *_: {"IdAgencia": "001", "Estado": True},
    )
    monkeypatch.setattr(caja_repo, "cajero_asignado", lambda *_: True)
    datos = JornadaOpen.model_validate({"idCajaFisica": 2, "dineroInicial": 0})

    def abrir(actor):
        with db_local.connect() as conn:
            try:
                service.abrir_jornada(
                    conn, conn, usuario("CAJERO"), actor, datos, "127.0.0.1"
                )
            except HTTPException as error:
                assert error.status_code == 409
                assert isinstance(error.detail, dict)
                return cast(dict[str, str], error.detail)["code"]
            return "ABIERTA"

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = sorted(pool.map(abrir, actores))
    esperado = (
        "CAJERO_YA_TIENE_JORNADA_ABIERTA" if actores[0] == actores[1] else "CAJA_EN_USO"
    )
    assert resultados == ["ABIERTA", esperado]


def test_dos_iniciales_distintas_y_dotacion_adicional(db_local):
    solicitudes = [_solicitar(db_local, clave=clave) for clave in ("uno", "dos")]

    def confirmar(solicitud):
        try:
            dotacion, _ = _confirmar(db_local, solicitud.id_solicitud)
            assert dotacion.id_asiento_contable is not None
            return "CONFIRMADA"
        except HTTPException as error:
            assert error.status_code == 409
            assert isinstance(error.detail, dict)
            return cast(dict[str, str], error.detail)["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirmar, solicitudes)) == [
            "CONFIRMADA",
            "DOTACION_INICIAL_YA_CONFIRMADA",
        ]
    adicional = _solicitar(db_local, clave="adicional", cantidad=3, tipo="ADICIONAL")
    assert _confirmar(db_local, adicional.id_solicitud)[0].monto == 30
    assert _efectos(db_local) == (120, 12, 2, 2, 2, 100)


def test_selector_y_revocacion_en_seguridad(db_local):
    with db_local.connect() as conn:
        opciones = dotaciones.consultar_autorizadores(conn, usuario("CAJERO"), 7, 55)
    assert [(opcion.id_usuario, opcion.nombre_completo) for opcion in opciones] == [
        (9, "Ana Perez")
    ]

    solicitud = _solicitar(db_local)
    with db_local.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE Organizacion.UsuarioAgencia SET Activo=0 WHERE UsuarioID=9"
        )
    with pytest.raises(HTTPException, match="AUTORIZADOR_NO_VALIDO"):
        _confirmar(db_local, solicitud.id_solicitud)
    assert _efectos(db_local) == (250, 25, 0, 0, 0, 0)


@pytest.mark.parametrize(
    ("autorizado", "codigo"),
    [
        (7, "DOBLE_CUSTODIA"),
        (10, "AUTORIZADOR_NO_VALIDO"),
        (11, "AUTORIZADOR_NO_VALIDO"),
    ],
)
def test_solicitud_rechaza_autorizador_no_elegible(db_local, autorizado, codigo):
    with pytest.raises(HTTPException, match=codigo):
        _solicitar(db_local, autorizado=autorizado)
    with db_local.connect() as conn:
        assert conn.scalar(text("SELECT COUNT(*) FROM Caja.SolicitudDotacion")) == 0
    assert _efectos(db_local) == (250, 25, 0, 0, 0, 0)


def test_apertura_en_cero_y_primera_inicial(db_local, monkeypatch):
    monkeypatch.setattr(service, "proteger_apertura_caja", lambda *_: nullcontext())
    monkeypatch.setattr(
        service,
        "auditar",
        lambda *_: nullcontext(type("Registro", (), {"confirmar": lambda *_: None})()),
    )
    monkeypatch.setattr(caja_repo, "cajero_asignado", lambda *_: True)
    with db_local.connect() as conn:
        jornada = service.abrir_jornada(
            conn,
            conn,
            usuario("CAJERO"),
            12,
            JornadaOpen.model_validate({"idCajaFisica": 2, "dineroInicial": 0}),
            "127.0.0.1",
        )
    assert jornada.dinero_inicial == 0
    solicitud = _solicitar(db_local, actor=12, jornada=jornada.id_jornada_caja)
    dotacion, repetida = _confirmar(db_local, solicitud.id_solicitud)
    assert not repetida and dotacion.monto == 100
    with db_local.connect() as conn:
        fila = caja_repo.obtener_jornada(conn, jornada.id_jornada_caja)
        assert fila is not None and fila["DineroInicial"] == 100


def test_inicial_con_cuadre_previo_rechaza_sin_efectos(db_local):
    solicitud = _solicitar(db_local)
    with db_local.begin() as conn:
        conn.exec_driver_sql("INSERT Caja.CuadreCaja VALUES(55,7,0)")
    with pytest.raises(HTTPException, match="DOTACION_INICIAL_CUADRE_EXISTENTE"):
        _confirmar(db_local, solicitud.id_solicitud)
    assert _efectos(db_local) == (250, 25, 0, 0, 0, 0)


def test_inicial_limite_incluye_movimientos_previos(db_local):
    with db_local.begin() as conn:
        conn.exec_driver_sql("INSERT Caja.TipoMovimientoCaja VALUES(1,'I')")
        conn.exec_driver_sql("INSERT Transacciones.Transaccion VALUES(1,'Deposito')")
        conn.exec_driver_sql("INSERT Caja.MovimientosCaja VALUES(55,1,1,50)")
    solicitud = _solicitar(db_local, cantidad=16)
    with pytest.raises(HTTPException, match="LIMITE_EFECTIVO_CAJA_EXCEDIDO"):
        _confirmar(db_local, solicitud.id_solicitud)
    assert _efectos(db_local) == (250, 25, 0, 0, 0, 0)
    solicitud_al_limite = _solicitar(db_local, clave="limite", cantidad=15)
    assert _confirmar(db_local, solicitud_al_limite.id_solicitud)[0].monto == 150


@pytest.mark.parametrize("misma_jornada", [True, False])
def test_confirmaciones_concurrentes_compiten_por_capacidad(db_local, misma_jornada):
    if misma_jornada:
        _confirmar(db_local, _solicitar(db_local).id_solicitud)
        jornadas = [(7, 55), (7, 55)]
        tipo, cantidad = "ADICIONAL", 6
        esperado = (90, 9, 2, 2, 2, 100)
        error = "LIMITE_EFECTIVO_CAJA_EXCEDIDO"
    else:
        with db_local.begin() as conn:
            conn.exec_driver_sql(
                "INSERT Caja.JornadasCaja VALUES(12,'001','ABIERTA',0,2,SYSUTCDATETIME(),NULL,NULL)"
            )
        jornadas = [(7, 55), (12, 56)]
        tipo, cantidad = "INICIAL", 15
        esperado = (100, 10, 1, 1, 1)
        error = "51014"

    barrera = Barrier(2, timeout=10)

    def confirmar(datos):
        n, (actor, jornada) = datos
        solicitud = _solicitar(
            db_local,
            clave=f"concurrente-{n}",
            cantidad=cantidad,
            tipo=tipo,
            actor=actor,
            jornada=jornada,
        )
        barrera.wait()
        try:
            _confirmar(db_local, solicitud.id_solicitud)
            return "CONFIRMADA"
        except (HTTPException, DBAPIError) as exc:
            assert error in str(exc)
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(confirmar, enumerate(jornadas))) == sorted(
            ["CONFIRMADA", error]
        )
    assert _efectos(db_local)[: len(esperado)] == esperado
    with db_local.connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT COUNT(*) FROM Caja.SolicitudDotacion WHERE Estado='PENDIENTE'"
                )
            )
            == 1
        )


def test_respeta_reservas_bov04_y_revierte_el_movimiento(db_local):
    archivo = (
        Path(__file__).resolve().parents[2]
        / "migrations/20261127_boveda_reservas_operativas.tsql"
    )
    with db_local.begin() as conn:
        conn.exec_driver_sql("""
            CREATE TABLE Boveda.CupoSolicitudMovimiento(IdSolicitudMovimiento bigint,IdAgencia char(3));
            CREATE TABLE Boveda.SolicitudMovimientoBoveda(
                IdSolicitudMovimiento bigint, IdBoveda int, IdBovedaContraparte int,
                Estado varchar(20), TipoMovimiento varchar(20), Monto decimal(18,2));
            CREATE TABLE Boveda.SolicitudMovimientoBovedaDenominacion(
                IdSolicitudMovimiento bigint, IdDenominacion int, Cantidad int);
            INSERT Boveda.CupoSolicitudMovimiento VALUES(1,'001');
            INSERT Boveda.SolicitudMovimientoBoveda VALUES(1,2,NULL,'APROBADO','EnvioExcedente',170);
            INSERT Boveda.SolicitudMovimientoBovedaDenominacion VALUES(1,1,17);
        """)
        for lote in archivo.read_text(encoding="utf8").split("\nGO"):
            if lote.strip():
                conn.exec_driver_sql(lote)
    solicitud = _solicitar(db_local)
    with pytest.raises(DBAPIError, match="59021"):
        _confirmar(db_local, solicitud.id_solicitud)
    assert _efectos(db_local) == (250, 25, 0, 0, 0, 0)
    assert _solicitar(db_local).estado == "PENDIENTE"


def test_migracion_caj07_revierte_vacia_y_protege_el_historial(db_local):
    migraciones = Path(__file__).resolve().parents[2] / "migrations/cooperativa"
    prefijo = "202611261800_caja_solicitudes_dotacion"
    up = (migraciones / f"{prefijo}.up.sql").read_text(encoding="utf8")
    down = (migraciones / f"{prefijo}.down.sql").read_text(encoding="utf8")
    with db_local.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        destino = conn.scalar(text("SELECT DB_NAME()"))
        conn.exec_driver_sql(
            "EXEC sys.sp_set_session_context N'migration_database', ?", (destino,)
        )
        conn.exec_driver_sql(down)
        assert conn.scalar(text("SELECT OBJECT_ID('Caja.SolicitudDotacion')")) is None
        assert (
            conn.scalar(
                text("SELECT COL_LENGTH('Caja.DotacionesCaja','IdAsientoContable')")
            )
            is None
        )
        conn.exec_driver_sql(up)
        conn.exec_driver_sql(up)
    _solicitar(db_local)
    with db_local.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        destino = conn.scalar(text("SELECT DB_NAME()"))
        conn.exec_driver_sql(
            "EXEC sys.sp_set_session_context N'migration_database', ?", (destino,)
        )
        with pytest.raises(DBAPIError, match="57911"):
            conn.exec_driver_sql(down)
    assert _solicitar(db_local).estado == "PENDIENTE"
