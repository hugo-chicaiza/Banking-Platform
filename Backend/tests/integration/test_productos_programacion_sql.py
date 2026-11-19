"""E3-03 SQL local real; actores controlados, no acredita login WorkOS."""

import json
import os
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import pyodbc
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from app.modules.aprobaciones.auditoria import ContextoAuditoria
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.registro import Objetivo, Registro
from app.modules.aprobaciones.servicio import Servicio
from app.modules.parametros.service import hoy
from app.modules.productos import programacion as p
from app.modules.productos import repository

pytestmark = pytest.mark.skipif(
    not os.getenv("E303_LOCAL_MANIFEST"),
    reason="Requiere dos bases locales E3-03 propias",
)
ORG = "org_fixture_e303"
MAKER = Actor(
    "user_fixture_e303_maker",
    ORG,
    "Solicitante QA",
    900303,
    ("ADMIN",),
    frozenset({"prd-condicion"}),
    ("001",),
)
CHECKER = Actor(
    "user_fixture_e303_checker",
    ORG,
    "Supervisor QA",
    900304,
    ("SUPERVISOR",),
    frozenset({"productos:aprobar"}),
    ("001",),
)
CTX = ContextoAuditoria("fixture_e303", "127.0.0.1", "e303-local", "SQL_LOCAL")


def codigo_error(error: HTTPException) -> str:
    detalle = error.detail
    assert isinstance(detalle, dict)
    return str(cast(dict[str, object], detalle)["code"])


@pytest.fixture(scope="module")
def motores():
    m = json.loads(Path(os.environ["E303_LOCAL_MANIFEST"]).read_text(encoding="utf-8"))
    assert m["servidor"] == "lpc:." and m["propias"] is True and m["listo"] is True
    motores = {}
    for base, nombre in m["bases"].items():
        assert nombre.startswith("BankingE303_" + base + "_")

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
            if not c.execute(
                text("SELECT 1 FROM Organizacion.Usuarios WHERE UsuarioID=:id"),
                {"id": actor.id_interno},
            ).scalar():
                c.exec_driver_sql("SET IDENTITY_INSERT Organizacion.Usuarios ON")
                c.execute(
                    text(
                        "INSERT Organizacion.Usuarios(UsuarioID,NombreUsuario,Nombres,Apellidos,Email,Cedula,KeyUsuario,Estado,RolesWorkOS) VALUES(:id,:usuario,'Persona','QA',:email,:cedula,:usuario,'Activo',:roles)"
                    ),
                    {
                        "id": actor.id_interno,
                        "usuario": actor.sujeto,
                        "email": actor.sujeto + "@example.invalid",
                        "cedula": str(actor.id_interno).zfill(10),
                        "roles": actor.roles[0],
                    },
                )
                c.exec_driver_sql("SET IDENTITY_INSERT Organizacion.Usuarios OFF")
    yield motores
    for engine in motores.values():
        engine.dispose()


@pytest.fixture
def caso(motores):
    with motores["cooperativa"].begin() as c:
        sufijo = uuid4().hex[:6].upper()
        producto = c.execute(
            text(
                "INSERT ProductosFinancieros.Producto(CodigoProducto,NombreProducto,TipoProducto,TipoCuenta,Estado,EstadoProducto,IdTipoProducto) OUTPUT inserted.IdProducto VALUES(:codigo,'Ahorro QA local','Cuenta','Ahorro','A','Activo',1)"
            ),
            {"codigo": "L303" + sufijo},
        ).scalar_one()
        sub = c.execute(
            text(
                "INSERT ProductosFinancieros.SubProducto(IdProducto,CodigoSubProducto,NombreSubProducto,Estado,EstadoSubProducto) OUTPUT inserted.IdSubProducto VALUES(:producto,:codigo,'Modelo QA local','A','Activo')"
            ),
            {"producto": producto, "codigo": "S303" + sufijo},
        ).scalar_one()
        c.execute(
            text(
                "INSERT ProductosFinancieros.SubProductoCondicion(IdSubProducto,MontoAperturaMinimo,SaldoMinimo,TasaInteresAnual,CostoMantenimiento,VigenciaDesde,Estado) VALUES(:sub,25,5,0,0,:desde,'Vigente')"
            ),
            {"sub": sub, "desde": hoy() - timedelta(days=2)},
        )
        inicial = c.execute(
            text(
                "SELECT IdCondicion FROM ProductosFinancieros.SubProductoCondicion WHERE IdSubProducto=:sub"
            ),
            {"sub": sub},
        ).scalar_one()
    registro = Registro()
    registro.agregar(p.operacion(p.Programador(motores["seguridad"], ORG)))
    actores = {a.sujeto: a for a in [MAKER, CHECKER]}
    cola = Servicio(
        motores["seguridad"],
        motores["cooperativa"],
        registro,
        lambda sujeto, org: actores[sujeto],
    )
    return cola, Objetivo("SubProducto", str(sub), None), inicial, actores


def condicion(dias=2, **cambios):
    return {
        "clase": "condiciones",
        "accion": "programar",
        "datos": {
            "montoAperturaMinimo": "35",
            "saldoMinimo": "5",
            "vigenciaDesde": (hoy() + timedelta(days=dias)).isoformat(),
            **cambios,
        },
    }


def solicitar(caso, contenido):
    cola, objetivo, *_ = caso
    return cola.solicitar(MAKER, p.CODIGO, objetivo, contenido, hoy(), CTX)


def aprobar(caso, id_):
    return caso[0].aprobar(CHECKER, id_, None, CTX)


def test_recuperacion_entre_bases_no_duplica_conjunto(motores, caso, monkeypatch):
    cola = caso[0]
    id_ = solicitar(caso, condicion())
    terminar = cola._terminar

    def interrupcion(*args):
        raise SQLAlchemyError("Interrupcion QA despues del commit destino")

    monkeypatch.setattr(cola, "_terminar", interrupcion)
    with pytest.raises(HTTPException) as e:
        aprobar(caso, id_)
    assert e.value.status_code == 503
    with motores["cooperativa"].connect() as c:
        assert len(p.filas(c, "condiciones", int(caso[1].id))) == 2
    monkeypatch.setattr(cola, "_terminar", terminar)
    assert cola.ejecutar(id_, ORG, CHECKER, CTX)["estado"] == "Ejecutada"
    assert cola.ejecutar(id_, ORG, CHECKER, CTX)["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        assert len(p.filas(c, "condiciones", int(caso[1].id))) == 2
        assert (
            c.execute(
                text(
                    "SELECT COUNT(*) FROM Seguridad.AprobacionAplicada WHERE IdOrganizacion=:org AND IdSolicitud=:id"
                ),
                {"org": ORG, "id": id_},
            ).scalar_one()
            == 1
        )


def test_cambio_del_objetivo_invalida_la_solicitud(motores, caso):
    id_ = solicitar(caso, condicion())
    with motores["cooperativa"].begin() as c:
        c.execute(
            text(
                "UPDATE ProductosFinancieros.SubProducto SET NombreSubProducto='Nombre QA actualizado' WHERE IdSubProducto=:id"
            ),
            {"id": int(caso[1].id)},
        )
    with pytest.raises(HTTPException) as e:
        aprobar(caso, id_)
    assert e.value.status_code == 409
    with motores["cooperativa"].connect() as c:
        assert len(p.filas(c, "condiciones", int(caso[1].id))) == 1


def test_notificaciones_solo_aprobador_y_resolucion_para_solicitante(caso):
    from app.modules.aprobaciones.lecturas import notificaciones

    id_ = solicitar(caso, condicion())

    def ids(actor):
        return {s["idSolicitud"] for s in notificaciones(caso[0], actor, None)["items"]}

    assert id_ in ids(CHECKER)
    assert id_ not in ids(MAKER)
    assert id_ not in ids(replace(CHECKER, organizacion="org_ajena_qa"))
    assert id_ not in ids(replace(CHECKER, permisos=frozenset()))
    assert aprobar(caso, id_)["estado"] == "Ejecutada"
    assert id_ in ids(MAKER)
    assert id_ not in ids(CHECKER)


def test_una_pendiente_por_modelo_sin_bloquear_otros_modelos(motores, caso):
    primera = solicitar(caso, condicion())
    with pytest.raises(HTTPException) as error:
        solicitar(caso, condicion(4))
    assert error.value.status_code == 409
    with motores["cooperativa"].begin() as c:
        otro = c.execute(
            text(
                "INSERT ProductosFinancieros.SubProducto(IdProducto,CodigoSubProducto,NombreSubProducto,Estado,EstadoSubProducto) OUTPUT inserted.IdSubProducto SELECT IdProducto,:codigo,'Otro modelo QA local','A','Activo' FROM ProductosFinancieros.SubProducto WHERE IdSubProducto=:id"
            ),
            {"codigo": "Q303" + uuid4().hex[:8].upper(), "id": int(caso[1].id)},
        ).scalar_one()
    otro_caso = (caso[0], Objetivo("SubProducto", str(otro), None), None, caso[3])
    segunda = solicitar(otro_caso, condicion())
    assert primera != segunda
    with motores["seguridad"].connect() as c:
        estados = (
            c.execute(
                text(
                    "SELECT Estado FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud IN (:primera,:segunda)"
                ),
                {"primera": primera, "segunda": segunda},
            )
            .scalars()
            .all()
        )
    assert estados == ["Pendiente", "Pendiente"]


def test_migraciones_repetibles_y_rollback_ante_fallo(motores):
    from sqlalchemy.exc import DBAPIError

    raiz = Path(__file__).resolve().parents[2] / "migrations"
    scripts = [
        ("cooperativa", "202611183030_productos_vigencias.up.sql"),
        ("cooperativa", "202611183031_cupos_efectivos.up.sql"),
        ("cooperativa", "202611183032_productos_consumidor.up.sql"),
        ("seguridad", "202611183030_productos_aprobacion.up.sql"),
    ]
    for _ in range(2):
        for base, nombre in scripts:
            with motores[base].connect() as c:
                destino = c.execute(text("SELECT DB_NAME()")).scalar_one()
                assert destino.startswith("BankingE303_" + base + "_")
                c.execute(
                    text(
                        "EXEC sys.sp_set_session_context @key=N'migration_database',@value=:destino"
                    ),
                    {"destino": destino},
                )
                c.exec_driver_sql((raiz / base / nombre).read_text(encoding="utf-8"))
                c.commit()
    with motores["cooperativa"].connect() as c:
        antes = c.execute(
            text("SELECT OBJECT_DEFINITION(OBJECT_ID('Canal.fn_CupoVigente'))")
        ).scalar_one()
    script = (raiz / "cooperativa" / scripts[1][1]).read_text(encoding="utf-8")
    script = script.replace(
        "COMMIT TRANSACTION;",
        "THROW 57699,'Interrupcion QA de migracion',1; COMMIT TRANSACTION;",
    )
    with (
        pytest.raises(DBAPIError, match="57699"),
        motores["cooperativa"].connect() as c,
    ):
        destino = c.execute(text("SELECT DB_NAME()")).scalar_one()
        c.execute(
            text(
                "EXEC sys.sp_set_session_context @key=N'migration_database',@value=:destino"
            ),
            {"destino": destino},
        )
        c.exec_driver_sql(script)
    with motores["cooperativa"].connect() as c:
        assert (
            c.execute(
                text("SELECT OBJECT_DEFINITION(OBJECT_ID('Canal.fn_CupoVigente'))")
            ).scalar_one()
            == antes
        )


@pytest.mark.parametrize(
    "clase,sql,error",
    [
        (
            "condiciones",
            "INSERT ProductosFinancieros.SubProductoCondicion(IdSubProducto,MontoAperturaMinimo,SaldoMinimo,TasaInteresAnual,CostoMantenimiento,VigenciaDesde,Estado) VALUES(:sub,30,5,0,0,:fecha,'Vigente')",
            "56201",
        ),
        (
            "cupos",
            "INSERT ProductosFinancieros.ProductoCanalCupo(IdSubProducto,IdCanal,CupoDiarioMaximo,CupoMensualMaximo,MontoMaxTransaccion,MaxTransaccionesDia,VigenciaDesde,EstadoCupo) VALUES(:sub,1,100,500,50,10,:fecha,'A'),(:sub,1,100,500,50,10,DATEADD(day,1,:fecha),'A')",
            "56202",
        ),
        (
            "restricciones",
            "INSERT ProductosFinancieros.ProductoRestriccion(IdSubProducto,TipoRestriccion,Descripcion,VigenciaDesde,Estado,RegistradoPor) VALUES(:sub,'SIN_RETIROS','QA uno',:fecha,'A',900303),(:sub,'SIN_RETIROS','QA dos',DATEADD(day,1,:fecha),'A',900303)",
            "56203",
        ),
    ],
)
def test_sql_rechaza_solapes_y_revierte_el_lote(motores, caso, clase, sql, error):
    from sqlalchemy.exc import DBAPIError

    with motores["cooperativa"].connect() as c:
        inicial = len(p.filas(c, clase, int(caso[1].id)))
    with pytest.raises(DBAPIError, match=error), motores["cooperativa"].begin() as c:
        c.execute(text(sql), {"sub": int(caso[1].id), "fecha": hoy()})
    with motores["cooperativa"].connect() as c:
        assert len(p.filas(c, clase, int(caso[1].id))) == inicial


def test_ac6_persiste_sin_aplicar_y_otra_identidad_aprueba(motores, caso):
    id_ = solicitar(caso, condicion())
    with motores["cooperativa"].connect() as c:
        assert len(p.filas(c, "condiciones", int(caso[1].id))) == 1
    with pytest.raises(HTTPException) as e:
        caso[0].aprobar(MAKER, id_, None, CTX)
    assert (
        e.value.status_code == 403
        and codigo_error(e.value) == "APROBADOR_ES_SOLICITANTE"
    )
    assert aprobar(caso, id_)["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        valores = p.filas(c, "condiciones", int(caso[1].id))
        assert len(valores) == 2
        assert valores[0]["VigenciaHasta"] == hoy() + timedelta(days=1)
        actual = repository.condiciones_vigentes(c, int(caso[1].id), hoy(), "ATM")
        futuro = repository.condiciones_vigentes(
            c, int(caso[1].id), hoy() + timedelta(days=2), "ATM"
        )
        assert actual is not None and actual["monto_apertura_minimo"] == 25
        assert futuro is not None and futuro["monto_apertura_minimo"] == 35


def test_ac1_solape_futuro_422_sin_crear_otra_solicitud(caso):
    assert aprobar(caso, solicitar(caso, condicion()))["estado"] == "Ejecutada"
    with pytest.raises(HTTPException) as e:
        solicitar(caso, condicion())
    assert e.value.status_code == 422 and codigo_error(e.value) == "VIGENCIA_SOLAPADA"


def test_ac3_cancelar_futuro_restaura_fin_exacto(motores, caso):
    assert aprobar(caso, solicitar(caso, condicion()))["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        futuro = p.filas(c, "condiciones", int(caso[1].id))[-1]["IdCondicion"]
    cancelacion = solicitar(
        caso, {"clase": "condiciones", "accion": "cancelar", "idRegistro": futuro}
    )
    with motores["cooperativa"].connect() as c:
        assert p.filas(c, "condiciones", int(caso[1].id))[-1]["Estado"] == "Programada"
    assert aprobar(caso, cancelacion)["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        filas = p.filas(c, "condiciones", int(caso[1].id))
        assert filas[0]["VigenciaHasta"] is None and filas[-1]["Estado"] == "Cancelada"


def test_ac4_transaccion_mayor_diario_rechazada(caso):
    datos = {
        "clase": "cupos",
        "accion": "programar",
        "datos": {
            "vigenciaDesde": (hoy() + timedelta(days=1)).isoformat(),
            "cupos": [
                {
                    "idCanal": 1,
                    "cupoDiarioMaximo": "100",
                    "cupoMensualMaximo": "1000",
                    "montoMaxTransaccion": "101",
                    "maxTransaccionesDia": 10,
                }
            ],
        },
    }
    with pytest.raises(HTTPException) as e:
        solicitar(caso, datos)
    assert e.value.status_code == 422 and codigo_error(e.value) == "CUPOS_INCOHERENTES"


def test_permisos_insuficientes_y_revocacion_solicitante(caso):
    cola, _, _, actores = caso
    id_ = solicitar(caso, condicion())
    with pytest.raises(HTTPException) as e:
        cola.aprobar(replace(CHECKER, permisos=frozenset()), id_, None, CTX)
    assert e.value.status_code == 403
    actores[MAKER.sujeto] = replace(MAKER, permisos=frozenset())
    with pytest.raises(HTTPException) as e:
        aprobar(caso, id_)
    assert (
        e.value.status_code == 409
        and codigo_error(e.value) == "SOLICITANTE_SIN_PERMISO"
    )
