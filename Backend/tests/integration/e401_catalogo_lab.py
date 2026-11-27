"""Pruebas del catálogo E4-01 sobre la proyección local del corte E2-01."""

import json
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.modules.contabilidad import repository
from app.modules.contabilidad.asientos import (
    ErrorContable,
    OperacionContable,
    generar_asiento,
)


@dataclass(frozen=True)
class Linea:
    lado: str
    base: str
    origen: str
    rol: str | None
    cuenta: str


@dataclass(frozen=True)
class Familia:
    codigo: str
    tipo: str
    concepto: str
    lineas: tuple[Linea, ...]


def _familias() -> list[Familia]:
    datos = json.loads(
        Path(__file__).with_name("e401_familias.json").read_text(encoding="utf-8")
    )
    familias = [
        Familia(
            f["familia"],
            f["tipo"],
            f["concepto"],
            tuple(Linea(*l) for l in f["lineas"]),
        )
        for f in datos
    ]
    assert len(familias) == len({f.codigo for f in familias}) == 32
    return familias


def _fecha(conn: Connection, fecha: date) -> int:
    conn.execute(
        text("""
        IF NOT EXISTS (SELECT 1 FROM Contabilidad.PeriodoContable WHERE Anio=:anio AND Mes=:mes)
            INSERT Contabilidad.PeriodoContable (Anio,Mes,Estado) VALUES (:anio,:mes,'ABIERTO');
        IF NOT EXISTS (SELECT 1 FROM Contabilidad.FechaContable WHERE Fecha=:fecha)
            INSERT Contabilidad.FechaContable (IdFechaContable,Fecha,EsDiaContable)
            SELECT MAX(IdFechaContable)+1,:fecha,1 FROM Contabilidad.FechaContable;
        """),
        {"fecha": fecha, "anio": fecha.year, "mes": fecha.month},
    )
    return conn.execute(
        text(
            "SELECT IdFechaContable FROM Contabilidad.FechaContable WHERE Fecha=:fecha"
        ),
        {"fecha": fecha},
    ).scalar_one()


def _version(conn: Connection, familia: Familia, version: int, desde: date) -> int:
    datos = {
        "familia": familia.codigo,
        "tipo": familia.tipo,
        "concepto": familia.concepto,
        "version": version,
        "desde": desde,
    }
    conn.execute(
        text("""
        IF NOT EXISTS (SELECT 1 FROM Contabilidad.TiposAsiento WHERE Codigo=:tipo)
            INSERT Contabilidad.TiposAsiento (IdTipoAsiento,Codigo,Nombre,Descripcion,EsManual,Estado)
            SELECT MAX(IdTipoAsiento)+1,:tipo,:tipo,:tipo,0,'A' FROM Contabilidad.TiposAsiento;
        IF NOT EXISTS (SELECT 1 FROM Contabilidad.ConceptoContable WHERE CodigoConcepto=:concepto)
            INSERT Contabilidad.ConceptoContable (IdConceptoContable,CodigoConcepto,ConceptoDetalle,Estado)
            SELECT MAX(IdConceptoContable)+1,:concepto,:concepto,'Activo' FROM Contabilidad.ConceptoContable;
        """),
        datos,
    )
    existente = conn.execute(
        text("""
        SELECT IdPlantillaAsiento FROM Contabilidad.PlantillaAsiento
        WHERE CodigoPlantilla=:familia AND Version=:version
        """),
        datos,
    ).scalar_one_or_none()
    if existente is not None:
        return existente
    plantilla = conn.execute(
        text("""
        INSERT Contabilidad.PlantillaAsiento
            (CodigoPlantilla,IdConceptoContable,Origen,IdTipoAsiento,Nombre,Estado,Version,VigenciaDesde)
        OUTPUT inserted.IdPlantillaAsiento
        SELECT :familia,c.IdConceptoContable,'TRANSACCIONES',t.IdTipoAsiento,:familia,1,:version,:desde
        FROM Contabilidad.ConceptoContable c CROSS JOIN Contabilidad.TiposAsiento t
        WHERE c.CodigoConcepto=:concepto AND t.Codigo=:tipo
        """),
        datos,
    ).scalar_one()
    for orden, linea in enumerate(familia.lineas, 1):
        cuenta = _cuenta(conn, linea.cuenta) if linea.origen == "FIJA" else None
        conn.execute(
            text("""
            INSERT Contabilidad.PlantillaAsientoDetalle (IdPlantillaAsiento,Orden,
                TipoMovimiento,ComponenteImporte,OrigenCuenta,CodigoRol,IdCuentaContable)
            VALUES (:plantilla,:orden,:lado,:base,:origen,:rol,:cuenta)
            """),
            {
                "plantilla": plantilla,
                "orden": orden,
                "lado": linea.lado,
                "base": linea.base,
                "origen": linea.origen,
                "rol": linea.rol,
                "cuenta": cuenta,
            },
        )
    return plantilla


def _cuenta(conn: Connection, codigo: str) -> int:
    cuenta = conn.execute(
        text("""
        SELECT IdCuentaContable FROM Contabilidad.CuentasContables
        WHERE CodigoCuenta=:codigo AND Estado=1 AND EsImputable=1
        """),
        {"codigo": codigo},
    ).scalar_one_or_none()
    assert cuenta is not None, f"Falta la cuenta hoja {codigo} en la proyección local"
    return cuenta


def _saldos(
    conn: Connection, cuentas: set[str]
) -> dict[str, tuple[Decimal, str, str | None]]:
    filas = conn.execute(
        text("""
        SELECT c.CodigoCuenta,c.Saldo,c.Naturaleza,p.CodigoCuenta
        FROM Contabilidad.CuentasContables c LEFT JOIN Contabilidad.CuentasContables p
            ON p.IdCuentaContable=c.IdCuentaSuperior
        """)
    )
    catalogo = {c: (saldo, naturaleza, padre) for c, saldo, naturaleza, padre in filas}
    resultado = {}
    for cuenta in sorted(cuentas):
        codigo: str | None = cuenta
        while codigo is not None and codigo not in resultado:
            resultado[codigo] = catalogo[codigo]
            codigo = catalogo[codigo][2]
    return resultado


def _numero_nativo(conn: Connection, fecha: date, agencia: str) -> str:
    return conn.execute(
        text("""
        SET NOCOUNT ON;
        DECLARE @numero varchar(20);
        EXEC Contabilidad.usp_GenerarNumeroAsiento
            @FechaAsiento=:fecha,@IdAgencia=:agencia,@NumeroAsiento=@numero OUTPUT;
        SELECT @numero;
        """),
        {"fecha": fecha, "agencia": agencia},
    ).scalar_one()


def _probar_asiento(
    engine: Engine,
    familia: Familia,
    plantilla: int,
    fecha: date,
    dia: int,
    modelo: OperacionContable,
) -> None:
    bases = dict.fromkeys(l.base for l in familia.lineas)
    importes = {base: Decimal(100 + 7 * i) for i, base in enumerate(bases)}
    codigos = {l.cuenta for l in familia.lineas}
    esperadas = [(l.cuenta, l.lado, importes[l.base]) for l in familia.lineas]
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(
                text(
                    "CREATE TABLE #E401_CatalogoNegocio (Evento varchar(100) NOT NULL)"
                )
            )
        with conn.begin() as tx:
            roles = {
                (l.origen, l.rol): _cuenta(conn, l.cuenta)
                for l in familia.lineas
                if l.origen != "FIJA"
            }
            clave = f"E401_CATALOGO:{familia.codigo}:{uuid4().hex}"
            operacion = replace(
                modelo,
                codigo_plantilla=familia.codigo,
                clave_evento=clave,
                id_fecha_contable=dia,
                fecha_hora=datetime.combine(fecha, modelo.fecha_hora.time()),
                importes=importes,
                cuentas_por_rol=roles,
            )
            antes = _saldos(conn, codigos)
            numero = _numero_nativo(conn, fecha, modelo.id_agencia)
            conn.execute(
                text("INSERT #E401_CatalogoNegocio VALUES (:clave)"), {"clave": clave}
            )
            id_asiento = generar_asiento(conn, operacion)
            cabecera = conn.execute(
                text("""
                SELECT IdPlantillaAsiento,NumeroAsiento,Estado,FechaAsiento,TotalDebito,TotalCredito
                FROM Contabilidad.AsientoContable WHERE IdAsientoContable=:id
                """),
                {"id": id_asiento},
            ).one()
            total = sum(monto for _, lado, monto in esperadas if lado == "DEBITO")
            assert tuple(cabecera) == (
                plantilla,
                numero,
                "CONTABILIZADO",
                fecha,
                total,
                total,
            )
            detalle = repository.movimientos_asiento(conn, id_asiento)
            assert [
                (m["codigo_cuenta"], m["tipo_movimiento"], m["monto"]) for m in detalle
            ] == esperadas
            deltas: dict[str, Decimal] = defaultdict(Decimal)
            for cuenta, lado, monto in esperadas:
                # El delta se calcula en la hoja y se propaga a sus ascendientes.
                naturaleza = antes[cuenta][1]
                signo = 1 if (naturaleza == "DEUDORA") == (lado == "DEBITO") else -1
                codigo: str | None = cuenta
                while codigo is not None:
                    deltas[codigo] += signo * monto
                    codigo = antes[codigo][2]
            despues = _saldos(conn, codigos)
            assert {c: s[0] - antes[c][0] for c, s in despues.items()} == deltas
            assert generar_asiento(conn, operacion) == id_asiento
            primera_base = next(iter(importes))
            otros_importes = {**importes, primera_base: importes[primera_base] + 1}
            with pytest.raises(ErrorContable, match="ya corresponde a otro asiento"):
                generar_asiento(conn, replace(operacion, importes=otros_importes))
            assert _saldos(conn, codigos) == despues
            assert repository.movimientos_asiento(conn, id_asiento) == detalle
            tx.rollback()
        assert repository.buscar_asiento_evento(conn, clave) is None
        assert not repository.movimientos_asiento(conn, id_asiento)
        assert _saldos(conn, codigos) == antes
        assert conn.scalar(text("SELECT COUNT(*) FROM #E401_CatalogoNegocio")) == 0
        conn.rollback()
        with conn.begin():
            conn.execute(text("DROP TABLE #E401_CatalogoNegocio"))


def probar_catalogo(
    engine: Engine, modelo: OperacionContable, migraciones: Path
) -> None:
    familias = _familias()
    anterior = date(2026, 11, 26)
    vigente = date(2026, 11, 27)
    siguiente = date(2026, 11, 30)
    with engine.begin() as conn:
        # La copia E2-01 trae el disparador histórico. Instalar el bloque D-17
        # exacto de develop para representar el esquema actual sin mutar el criterio.
        sql = (
            migraciones / "cooperativa/202611201000_cuentas_producto.up.sql"
        ).read_text(encoding="utf-8")
        trigger = sql.split("EXEC sys.sp_executesql N'CREATE OR ALTER TRIGGER ", 1)[
            1
        ].split("END;';", 1)[0]
        conn.exec_driver_sql(
            "CREATE OR ALTER TRIGGER " + trigger.replace("''", "'") + "END;"
        )
        # Auxiliares de E3-05 ausentes de la captura antigua del plan de cuentas.
        conn.execute(
            text("""
            UPDATE Contabilidad.CuentasContables SET EsImputable=0
            WHERE CodigoCuenta IN ('169090','250590','259090') AND EsImputable=1 AND Saldo=0;

            INSERT Contabilidad.CuentasContables
                (CodigoCuenta,NombreCuenta,Naturaleza,IdCuentaSuperior,Estado,
                 EsImputable,EsCuentaValuacion,SoloAutomatica,EsCatalogoRegulador)
            SELECT a.Codigo,a.Codigo,p.Naturaleza,p.IdCuentaContable,1,1,0,0,0
            FROM (VALUES ('16909005','169090'),('25059015','250590'),
                         ('25909005','259090'),('25909010','259090')) a(Codigo,Padre)
            JOIN Contabilidad.CuentasContables p ON p.CodigoCuenta=a.Padre
            WHERE NOT EXISTS (SELECT 1 FROM Contabilidad.CuentasContables c
                              WHERE c.CodigoCuenta=a.Codigo);
        """)
        )
        dia_anterior, dia, dia_siguiente = (
            _fecha(conn, f) for f in (anterior, vigente, siguiente)
        )
        versiones = {f.codigo: _version(conn, f, 1, vigente) for f in familias}
        deposito = next(f for f in familias if f.codigo == "CAJA_DEPOSITO")
        version_nueva = _version(conn, deposito, 2, siguiente)
        assert repository.obtener_plantilla(conn, "RET_EFECTIVO_CAJA", anterior) is None
    for familia in familias:
        try:
            _probar_asiento(
                engine, familia, versiones[familia.codigo], vigente, dia, modelo
            )
        except Exception as error:
            raise AssertionError(f"Falló la familia {familia.codigo}") from error
    _probar_asiento(
        engine, deposito, versiones[deposito.codigo], anterior, dia_anterior, modelo
    )
    _probar_asiento(engine, deposito, version_nueva, siguiente, dia_siguiente, modelo)
    print("32 familias, transición v1/v2, saldos, idempotencia y rollback: OK")
