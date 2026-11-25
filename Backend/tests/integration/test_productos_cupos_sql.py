"""Cupos, concurrencia y consumidor real; solo bases locales E3-03 propias."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from typing import cast
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.modules.parametros.service import hoy
from app.modules.productos import programacion as p
from app.modules.transacciones import repository as transacciones
from tests.integration import test_productos_programacion_sql as base_sql
from tests.integration.test_productos_programacion_sql import (
    CHECKER,
    CTX,
    MAKER,
    ORG,
    aprobar,
    condicion,
    solicitar,
)

motores = base_sql.motores
caso = base_sql.caso

pytestmark = pytest.mark.skipif(
    not os.getenv("E303_LOCAL_MANIFEST"),
    reason="Requiere laboratorio local E3-03 propio",
)


def codigo_error(error: HTTPException) -> str:
    detalle = error.detail
    assert isinstance(detalle, dict)
    return str(cast(dict[str, object], detalle)["code"])


def cuenta_y_techo(motores, caso):
    sub = int(caso[1].id)
    with motores["cooperativa"].begin() as c:
        cliente = c.execute(
            text(
                "INSERT Clientes.Cliente(Identificacion,TipoDocumento,TipoCliente,Nombres,Apellidos,Genero,EstadoCivil,FechaNacimiento,TelefonoCelular,Email,ConsentimientoDatos,FechaConsentimiento,CreadoPor,Estado) OUTPUT inserted.IdCliente VALUES(:identificacion,'P','Natural','Cliente','QA local','M','Soltero','19900101','0990000000','qa-e303@example.invalid',1,SYSUTCDATETIME(),:actor,'Activo')"
            ),
            {
                "identificacion": "QA" + uuid4().hex[:10].upper(),
                "actor": MAKER.id_interno,
            },
        ).scalar_one()
        producto = c.execute(
            text(
                "SELECT IdProducto FROM ProductosFinancieros.SubProducto WHERE IdSubProducto=:sub"
            ),
            {"sub": sub},
        ).scalar_one()
        cuenta = c.execute(
            text(
                "INSERT Cuentas.Cuenta(NumeroCuenta,IdCliente,IdAgencia,IdProducto,IdSubProducto,CreadoPor,Saldo,SaldoRetenido,Estado) OUTPUT inserted.IdCuenta VALUES(:numero,:cliente,'001',:producto,:sub,:actor,2000,0,'Activa')"
            ),
            {
                "numero": "990" + str(sub).zfill(9),
                "cliente": cliente,
                "producto": producto,
                "sub": sub,
                "actor": MAKER.id_interno,
            },
        ).scalar_one()
        c.execute(
            text(
                "INSERT ProductosFinancieros.ProductoCanalCupo(IdSubProducto,IdCanal,CupoDiarioMaximo,CupoMensualMaximo,MontoMaxTransaccion,MaxTransaccionesDia,VigenciaDesde,EstadoCupo) VALUES(:sub,1,1000,5000,500,20,:desde,'A')"
            ),
            {"sub": sub, "desde": hoy() - timedelta(days=5)},
        )
    return cuenta


def test_e602_activacion_registra_un_evento_y_revierte_con_el_deposito(motores, caso):
    from app.modules.cuentas.service import activar_si_corresponde

    cuenta = cuenta_y_techo(motores, caso)
    with motores["cooperativa"].connect() as c, c.begin() as transaccion:
        parametros = {"cuenta": cuenta}
        c.execute(
            text("SELECT IdCuenta FROM Cuentas.Cuenta WHERE IdCuenta=:cuenta"),
            parametros,
        ).close()
        migracion = (
            Path(__file__).resolve().parents[2]
            / "migrations/cooperativa/202611232320_cuentas_apertura_eventos.up.sql"
        )
        c.exec_driver_sql("""
            DECLARE @bd sysname = DB_NAME();
            EXEC sys.sp_set_session_context @key=N'migration_database', @value=@bd;
            SET QUOTED_IDENTIFIER ON;
        """)
        c.exec_driver_sql(migracion.read_text(encoding="utf-8"))
        c.execute(
            text("""UPDATE Cuentas.Cuenta
                SET Estado='PendienteDeposito', Saldo=0, MontoAperturaAplicado=20
                WHERE IdCuenta=:cuenta"""),
            parametros,
        )
        evento = text("""SELECT COUNT(*) FROM Cuentas.CuentaEvento
            WHERE IdCuenta=:cuenta AND TipoEvento='Activacion'""")
        with pytest.raises(HTTPException) as error:
            activar_si_corresponde(c, cuenta, Decimal("19.99"), MAKER.id_interno)
        assert codigo_error(error.value) == "MONTO_BAJO_APERTURA"
        assert c.execute(evento, parametros).scalar_one() == 0
        deposito = c.begin_nested()
        assert activar_si_corresponde(c, cuenta, Decimal(20), MAKER.id_interno)
        assert not activar_si_corresponde(c, cuenta, Decimal(20), MAKER.id_interno)
        assert c.execute(evento, parametros).scalar_one() == 1
        deposito.rollback()
        assert c.execute(evento, parametros).scalar_one() == 0
        assert (
            c.execute(
                text("SELECT Estado FROM Cuentas.Cuenta WHERE IdCuenta=:cuenta"),
                parametros,
            ).scalar_one()
            == "PendienteDeposito"
        )
        transaccion.rollback()


def test_e602_cupo_efectivo_combina_capas_y_ambito(motores, caso):
    from app.modules.cuentas.service import cupo_efectivo

    cuenta = cuenta_y_techo(motores, caso)
    migracion = (
        Path(__file__).resolve().parents[2] / "tests/sql/e602_limites_operacion.sql"
    )
    with (
        motores["cooperativa"]
        .connect()
        .execution_options(isolation_level="AUTOCOMMIT") as c
    ):
        c.exec_driver_sql("SET QUOTED_IDENTIFIER ON; BEGIN TRANSACTION;")
        try:
            c.exec_driver_sql("""
                DECLARE @bd sysname = DB_NAME();
                EXEC sys.sp_set_session_context @key=N'migration_database', @value=@bd;
            """)
            c.exec_driver_sql(migracion.read_text(encoding="utf-8"))
            c.execute(
                text("""
                    INSERT Canal.CanalCupoClienteCustom
                      (IdCuenta,IdCanal,CupoDiario,CupoMensual,MontoMaxTransaccion,
                       MaxTransaccionesDia,Estado,ModificadoPor)
                    VALUES (:cuenta,1,800,4000,400,15,'A',:actor);
                    INSERT Parametros.LimiteOperacion
                      (CodigoTipoTransaccion,IdCanal,GrupoID,IdAgencia,
                       MontoMaximoOperacion,MontoMaximoDiario,VigenciaDesde)
                    VALUES ('Retiro',1,900303,NULL,450,750,:desde),
                           ('Retiro',1,900303,'001',300,700,:desde);
                """),
                {"cuenta": cuenta, "actor": MAKER.id_interno, "desde": hoy()},
            )
            local = cupo_efectivo(
                c, cuenta, 1, hoy(), tipo="Retiro", grupo=900303, agencia="001"
            )
            general = cupo_efectivo(
                c, cuenta, 1, hoy(), tipo="Retiro", grupo=900303, agencia="002"
            )
            anterior = cupo_efectivo(
                c,
                cuenta,
                1,
                hoy() - timedelta(days=1),
                tipo="Retiro",
                grupo=900303,
                agencia="001",
            )
            assert local is not None and general is not None and anterior is not None
            assert (local["MontoMaxTransaccion"], local["CupoDiario"]) == (300, 700)
            assert (general["MontoMaxTransaccion"], general["CupoDiario"]) == (400, 750)
            assert (anterior["MontoMaxTransaccion"], anterior["CupoDiario"]) == (
                400,
                800,
            )
        finally:
            c.exec_driver_sql("IF XACT_STATE()<>0 ROLLBACK TRANSACTION;")


def test_e603_ajuste_inmediato_persiste_pedido_y_documento(motores, caso):
    from app.modules.cuentas import service as cuentas
    from app.modules.cuentas.schemas import CupoSolicitado

    cuenta = cuenta_y_techo(motores, caso)
    payload = CupoSolicitado.model_validate(
        {
            "cupoDiario": "600",
            "cupoMensual": "4000",
            "montoMaxTransaccion": "400",
            "maxTransaccionesDia": 10,
            "solicitadoPorCliente": True,
            "documentoVerificado": "P",
        }
    )
    with motores["cooperativa"].connect() as conn:
        vigente = cuentas.actualizar_cupo(conn, cuenta, 1, payload, MAKER.id_interno)
        assert vigente.cupo_diario == 600
        historial = cuentas.obtener_historial_cupo(conn, cuenta, 1).items
        assert len(historial) == 1
        assert historial[0].solicitado_por_cliente is True
        assert historial[0].documento_verificado == "P"


def test_ac5_cuenta_superior_al_techo_rechazada_en_servicio_y_trigger(motores, caso):
    from app.modules.cuentas import service as cuentas
    from app.modules.cuentas.schemas import CupoSolicitado

    cuenta = cuenta_y_techo(motores, caso)
    payload = CupoSolicitado.model_validate(
        {
            "cupoDiario": "1001",
            "cupoMensual": "5000",
            "montoMaxTransaccion": "500",
            "maxTransaccionesDia": 20,
            "solicitadoPorCliente": True,
            "documentoVerificado": "C",
        }
    )
    with motores["cooperativa"].connect() as c, pytest.raises(HTTPException) as e:
        cuentas.actualizar_cupo(c, cuenta, 1, payload, MAKER.id_interno)
    assert e.value.status_code == 422 and codigo_error(e.value) == "CUPO_SOBRE_TOPE"
    with pytest.raises(DBAPIError, match="52003"), motores["cooperativa"].begin() as c:
        c.execute(
            text(
                "INSERT Canal.CanalCupoClienteCustom(IdCuenta,IdCanal,CupoDiario,CupoMensual,MontoMaxTransaccion,MaxTransaccionesDia,Estado,ModificadoPor) VALUES(:cuenta,1,1001,5000,500,20,'A',:actor)"
            ),
            {"cuenta": cuenta, "actor": MAKER.id_interno},
        )


def test_p7_techo_futuro_aplica_menor_sin_alterar_personalizado(motores, caso):
    cuenta = cuenta_y_techo(motores, caso)
    with motores["cooperativa"].begin() as c:
        c.execute(
            text(
                "INSERT Canal.CanalCupoClienteCustom(IdCuenta,IdCanal,CupoDiario,CupoMensual,MontoMaxTransaccion,MaxTransaccionesDia,Estado,ModificadoPor) VALUES(:cuenta,1,800,4000,400,15,'A',:actor)"
            ),
            {"cuenta": cuenta, "actor": MAKER.id_interno},
        )
    datos = {
        "clase": "cupos",
        "accion": "programar",
        "datos": {
            "vigenciaDesde": (hoy() + timedelta(days=2)).isoformat(),
            "cupos": [
                {
                    "idCanal": 1,
                    "cupoDiarioMaximo": "100",
                    "cupoMensualMaximo": "1000",
                    "montoMaxTransaccion": "50",
                    "maxTransaccionesDia": 5,
                }
            ],
        },
    }
    assert aprobar(caso, solicitar(caso, datos))["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        actual = (
            c.execute(
                text("SELECT * FROM Canal.fn_CupoVigenteFecha(:cuenta,1,:fecha)"),
                {"cuenta": cuenta, "fecha": hoy()},
            )
            .mappings()
            .one()
        )
        futuro = (
            c.execute(
                text("SELECT * FROM Canal.fn_CupoVigenteFecha(:cuenta,1,:fecha)"),
                {"cuenta": cuenta, "fecha": hoy() + timedelta(days=2)},
            )
            .mappings()
            .one()
        )
        assert (
            actual["CupoDiario"] == 800
            and futuro["CupoDiario"] == 100
            and futuro["MontoMaxTransaccion"] == 50
        )
        autorizacion_actual = transacciones.autorizar_operacion(
            c, cuenta, 1, "Retiro", 100, fecha_hora=datetime.combine(hoy(), time(12))
        )
        autorizacion_futura = transacciones.autorizar_operacion(
            c,
            cuenta,
            1,
            "Retiro",
            100,
            fecha_hora=datetime.combine(hoy() + timedelta(days=2), time(12)),
        )
        assert autorizacion_actual["CodigoRespuesta"].strip() == "00"
        assert autorizacion_futura["CodigoRespuesta"].strip() == "61"
        assert (
            c.execute(
                text(
                    "SELECT CupoDiario FROM Canal.CanalCupoClienteCustom WHERE IdCuenta=:id"
                ),
                {"id": cuenta},
            ).scalar_one()
            == 800
        )


def test_dos_aprobadores_compiten_sin_doble_aplicacion(motores, caso):
    cola, objetivo, _, actores = caso
    otro = replace(CHECKER, sujeto="user_fixture_e303_checker_dos", id_interno=900305)
    actores[otro.sujeto] = otro
    id_ = solicitar(caso, condicion())
    barrera = Barrier(2, timeout=15)

    def competir(actor):
        barrera.wait()
        try:
            return cola.aprobar(actor, id_, None, CTX)["estado"]
        except HTTPException as e:
            return e.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultados = list(pool.map(competir, [CHECKER, otro]))
    assert resultados.count("Ejecutada") == 1 and 409 in resultados
    with motores["cooperativa"].connect() as c:
        assert len(p.filas(c, "condiciones", int(objetivo.id))) == 2
        assert (
            c.execute(
                text(
                    "SELECT COUNT(*) FROM Seguridad.AprobacionAplicada WHERE IdOrganizacion=:org AND IdSolicitud=:id"
                ),
                {"org": ORG, "id": id_},
            ).scalar_one()
            == 1
        )


def test_cancelar_cadena_y_preservar_fin_anterior_limitado(motores, caso):
    sub = int(caso[1].id)
    fin = hoy() + timedelta(days=20)
    with motores["cooperativa"].begin() as c:
        c.execute(
            text(
                "UPDATE ProductosFinancieros.SubProductoCondicion SET VigenciaHasta=:fin WHERE IdCondicion=:id"
            ),
            {"fin": fin, "id": caso[2]},
        )
    assert aprobar(caso, solicitar(caso, condicion(2)))["estado"] == "Ejecutada"
    assert aprobar(caso, solicitar(caso, condicion(4)))["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        filas = p.filas(c, "condiciones", sub)
    assert (
        aprobar(
            caso,
            solicitar(
                caso,
                {
                    "clase": "condiciones",
                    "accion": "cancelar",
                    "idRegistro": filas[1]["IdCondicion"],
                },
            ),
        )["estado"]
        == "Ejecutada"
    )
    assert (
        aprobar(
            caso,
            solicitar(
                caso,
                {
                    "clase": "condiciones",
                    "accion": "cancelar",
                    "idRegistro": filas[2]["IdCondicion"],
                },
            ),
        )["estado"]
        == "Ejecutada"
    )
    with motores["cooperativa"].connect() as c:
        assert p.filas(c, "condiciones", sub)[0]["VigenciaHasta"] == fin


def test_consumidor_transacciones_respeta_restricciones_y_no_postea(motores, caso):
    cuenta = cuenta_y_techo(motores, caso)
    assert (
        aprobar(
            caso,
            solicitar(
                caso,
                {
                    "clase": "restricciones",
                    "accion": "programar",
                    "datos": {
                        "tipoRestriccion": "SIN_TRANSFERENCIAS_SALIDA",
                        "descripcion": "Sin transferencias de salida QA",
                        "vigenciaDesde": hoy().isoformat(),
                    },
                },
            ),
        )["estado"]
        == "Ejecutada"
    )

    def autorizar(tipo, canal=1):
        with motores["cooperativa"].connect() as c:
            r = (
                c.execute(
                    text(
                        "SET NOCOUNT ON; DECLARE @codigo char(2),@mensaje nvarchar(300),@comision decimal(18,2); EXEC Transacciones.usp_AutorizarOperacion @IdCuenta=:cuenta,@IdCanal=:canal,@TipoTransaccion=:tipo,@Monto=10,@CodigoRespuesta=@codigo OUTPUT,@Mensaje=@mensaje OUTPUT,@Comision=@comision OUTPUT; SELECT @codigo AS codigo,@mensaje AS mensaje;"
                    ),
                    {"cuenta": cuenta, "canal": canal, "tipo": tipo},
                )
                .mappings()
                .one()
            )
            return r["codigo"]

    assert autorizar("Transferencia_Enviada") == "05"
    assert autorizar("Retiro") == "00"
    assert autorizar("Retiro", 999) == "05"
    assert autorizar("Deposito") == "00"
    assert autorizar("Deposito", 999) == "05"
    with motores["cooperativa"].connect() as c:
        assert (
            c.execute(
                text("SELECT Saldo FROM Cuentas.Cuenta WHERE IdCuenta=:id"),
                {"id": cuenta},
            ).scalar_one()
            == 2000
        )
        assert (
            c.execute(
                text(
                    "SELECT COUNT(*) FROM Transacciones.Transaccion WHERE IdCuenta=:id"
                ),
                {"id": cuenta},
            ).scalar_one()
            == 0
        )


def test_consumidor_conserva_comision_real_y_validacion_de_fondos(motores, caso):
    """Contrato E1-12: el techo no altera el calculo ni contabiliza movimientos."""
    cuenta = cuenta_y_techo(motores, caso)
    with motores["cooperativa"].connect() as c:
        transaccion = c.begin()
        try:
            codigo = "Q" + uuid4().hex[:8].upper()
            c.execute(
                text(
                    "INSERT Transacciones.Comisiones(CodigoComision,TipoComision,TipoCalculo,Valor,IdCanal,Descripcion,VigenciaDesde,Estado) VALUES(:codigo,'Retiro','Fijo',0.45,1,'Comision QA local',:desde,'A')"
                ),
                {"codigo": codigo, "desde": hoy() - timedelta(days=1)},
            )
            id_comision = c.execute(
                text(
                    "SELECT IdComision FROM Transacciones.Comisiones WHERE CodigoComision=:codigo"
                ),
                {"codigo": codigo},
            ).scalar_one()
            c.execute(
                text(
                    "INSERT Transacciones.ComisionTipoTransaccion(CodigoTipoTransaccion,IdCanal,IdComision,VigenciaDesde,Estado,RegistradoPor) VALUES('Retiro',1,:comision,:desde,'A',:actor)"
                ),
                {
                    "comision": id_comision,
                    "desde": hoy() - timedelta(days=1),
                    "actor": MAKER.id_interno,
                },
            )

            def autorizar():
                return (
                    c.execute(
                        text(
                            "SET NOCOUNT ON; DECLARE @codigo char(2),@mensaje nvarchar(300),@comision decimal(18,2); EXEC Transacciones.usp_AutorizarOperacion @IdCuenta=:cuenta,@IdCanal=1,@TipoTransaccion='Retiro',@Monto=10,@CodigoRespuesta=@codigo OUTPUT,@Mensaje=@mensaje OUTPUT,@Comision=@comision OUTPUT; SELECT @codigo AS codigo,@comision AS comision;"
                        ),
                        {"cuenta": cuenta},
                    )
                    .mappings()
                    .one()
                )

            autorizado = autorizar()
            assert (
                autorizado["codigo"] == "00" and str(autorizado["comision"]) == "0.45"
            )
            c.execute(
                text("UPDATE Cuentas.Cuenta SET Saldo=10 WHERE IdCuenta=:cuenta"),
                {"cuenta": cuenta},
            )
            insuficiente = autorizar()
            assert (
                insuficiente["codigo"] == "51"
                and str(insuficiente["comision"]) == "0.45"
            )
            assert (
                c.execute(
                    text(
                        "SELECT COUNT(*) FROM Transacciones.Transaccion WHERE IdCuenta=:cuenta"
                    ),
                    {"cuenta": cuenta},
                ).scalar_one()
                == 0
            )
        finally:
            transaccion.rollback()
    with motores["cooperativa"].connect() as c:
        assert (
            c.execute(
                text("SELECT Saldo FROM Cuentas.Cuenta WHERE IdCuenta=:cuenta"),
                {"cuenta": cuenta},
            ).scalar_one()
            == 2000
        )


def test_lote_sin_canales_cancelable_una_sola_vez(motores, caso):
    cuenta_y_techo(motores, caso)
    id_ = solicitar(
        caso,
        {
            "clase": "cupos",
            "accion": "programar",
            "datos": {
                "vigenciaDesde": (hoy() + timedelta(days=3)).isoformat(),
                "cupos": [],
            },
        },
    )
    assert aprobar(caso, id_)["estado"] == "Ejecutada"
    cancelacion = {"clase": "cupos", "accion": "cancelar", "idProgramacion": id_}
    assert aprobar(caso, solicitar(caso, cancelacion))["estado"] == "Ejecutada"
    with pytest.raises(HTTPException) as e:
        solicitar(caso, cancelacion)
    assert codigo_error(e.value) == "CONJUNTO_CANCELADO"
    with motores["cooperativa"].connect() as c:
        assert p.filas(c, "cupos", int(caso[1].id))[0]["VigenciaHasta"] is None


def test_cancelar_cadena_con_lote_intermedio_sin_canales(motores, caso):
    cuenta_y_techo(motores, caso)
    vacio = solicitar(
        caso,
        {
            "clase": "cupos",
            "accion": "programar",
            "datos": {
                "vigenciaDesde": (hoy() + timedelta(days=2)).isoformat(),
                "cupos": [],
            },
        },
    )
    assert aprobar(caso, vacio)["estado"] == "Ejecutada"
    futuro = solicitar(
        caso,
        {
            "clase": "cupos",
            "accion": "programar",
            "datos": {
                "vigenciaDesde": (hoy() + timedelta(days=4)).isoformat(),
                "cupos": [
                    {
                        "idCanal": 1,
                        "cupoDiarioMaximo": "100",
                        "cupoMensualMaximo": "1000",
                        "montoMaxTransaccion": "50",
                        "maxTransaccionesDia": 10,
                    }
                ],
            },
        },
    )
    assert aprobar(caso, futuro)["estado"] == "Ejecutada"
    for id_ in [vacio, futuro]:
        assert (
            aprobar(
                caso,
                solicitar(
                    caso,
                    {"clase": "cupos", "accion": "cancelar", "idProgramacion": id_},
                ),
            )["estado"]
            == "Ejecutada"
        )
    with motores["cooperativa"].connect() as c:
        assert p.filas(c, "cupos", int(caso[1].id))[0]["VigenciaHasta"] is None


@pytest.mark.parametrize(
    "tipo,extra",
    [
        ("SIN_RETIROS", {}),
        ("SIN_RETIROS_DIAS", {"dias": 30}),
        ("SALDO_MINIMO", {"monto": "10"}),
        ("SALDO_MAXIMO", {"monto": "5000"}),
        ("MAXIMO_CUENTAS_CLIENTE", {"cantidad": 1}),
        ("SIN_TRANSFERENCIAS_SALIDA", {}),
    ],
)
def test_seis_tipos_vigencia_inclusiva_y_fin_aprobado(motores, caso, tipo, extra):
    from app.modules.productos.repository import (
        obtener_restricciones,
        restricciones_vigentes,
    )

    id_ = solicitar(
        caso,
        {
            "clase": "restricciones",
            "accion": "programar",
            "datos": {
                "tipoRestriccion": tipo,
                "descripcion": "Restriccion QA SQL local",
                "vigenciaDesde": hoy().isoformat(),
                **extra,
            },
        },
    )
    assert aprobar(caso, id_)["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        registros = restricciones_vigentes(c, int(caso[1].id), hoy(), "VENT")
        assert len(registros) == 1 and registros[0]["tipo_restriccion"] == tipo
        if tipo == "SIN_RETIROS_DIAS":
            assert obtener_restricciones(c, int(caso[1].id))["dias_sin_retiros"] == 30
        restriccion = registros[0]["id_restriccion"]
    fin = solicitar(
        caso,
        {
            "clase": "restricciones",
            "accion": "fin",
            "idRegistro": restriccion,
            "datos": {"vigenciaHasta": hoy().isoformat()},
        },
    )
    with motores["cooperativa"].connect() as c:
        assert p.filas(c, "restricciones", int(caso[1].id))[0]["VigenciaHasta"] is None
    assert aprobar(caso, fin)["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        assert len(restricciones_vigentes(c, int(caso[1].id), hoy(), "VENT")) == 1
        assert (
            restricciones_vigentes(
                c, int(caso[1].id), hoy() + timedelta(days=1), "VENT"
            )
            == []
        )


def test_maximo_cuentas_se_aplica_solo_desde_su_vigencia(motores, caso):
    from app.modules.productos.service import cliente_elegible

    cuenta = cuenta_y_techo(motores, caso)
    id_ = solicitar(
        caso,
        {
            "clase": "restricciones",
            "accion": "programar",
            "datos": {
                "tipoRestriccion": "MAXIMO_CUENTAS_CLIENTE",
                "descripcion": "Una cuenta por cliente QA",
                "cantidad": 1,
                "vigenciaDesde": (hoy() + timedelta(days=2)).isoformat(),
            },
        },
    )
    assert aprobar(caso, id_)["estado"] == "Ejecutada"
    with motores["cooperativa"].connect() as c:
        cliente = c.execute(
            text("SELECT IdCliente FROM Cuentas.Cuenta WHERE IdCuenta=:id"),
            {"id": cuenta},
        ).scalar_one()
        assert (
            "MAXIMO_POR_CLIENTE_ALCANZADO"
            not in cliente_elegible(c, cliente, int(caso[1].id), hoy())[1]
        )
        assert (
            "MAXIMO_POR_CLIENTE_ALCANZADO"
            in cliente_elegible(c, cliente, int(caso[1].id), hoy() + timedelta(days=2))[
                1
            ]
        )
