"""Atomic cut projection. Approval source below is explicitly a LOCAL fixture."""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from e201_sql_lab import (
    ROOT,
    batches,
    connect,
    expect_error,
    fixture,
    new_entry,
    quote,
    rows,
)


def run():
    db = "CooperativaDB_E201_Lab_" + uuid.uuid4().hex[:10]
    with connect("master") as c:
        c.execute(
            "CREATE DATABASE " + quote(db) + " COLLATE SQL_Latin1_General_CP1_CI_AS"
        )
    checks = {}
    folder = ROOT / "Backend/scripts/sql/e201"
    with connect(db) as c:
        fixture(c)
        original = rows(
            c,
            "SELECT CodigoCuenta,EsImputable,Saldo FROM Contabilidad.CuentasContables ORDER BY CodigoCuenta",
        )
        history = rows(
            c,
            "SELECT * FROM Contabilidad.MovimientosContables ORDER BY IdMovimientoContable",
        )
        for _ in range(2):
            batches(c, folder / "001_solo_estructura.sql")
        assert original == rows(
            c,
            "SELECT CodigoCuenta,EsImputable,Saldo FROM Contabilidad.CuentasContables ORDER BY CodigoCuenta",
        )
        checks["structure_does_not_change_accounts_flags_or_balances"] = True
        reserva = rows(
            c, "SELECT * FROM Contabilidad.CuentasContables WHERE CodigoCuenta='3301'"
        )
        for _ in range(2):
            batches(c, folder / "002_cuc_seps_2025_100_segmento_1.sql")
        assert reserva == rows(
            c, "SELECT * FROM Contabilidad.CuentasContables WHERE CodigoCuenta='3301'"
        )
        assert (
            c.execute(
                "SELECT COUNT(*) FROM Contabilidad.CuentasContables WHERE CodigoCuenta LIKE '3304%'"
            ).fetchval()
            == 0
        )
        assert (
            c.execute("""
            SELECT COUNT(*) FROM Contabilidad.CuentasContables h
            JOIN Contabilidad.CuentasContables p ON p.IdCuentaContable=h.IdCuentaSuperior
            WHERE h.CodigoCuenta='740640' AND p.CodigoCuenta='7406'
              AND h.EsImputable=0 AND h.EsCatalogoRegulador=1 AND h.Saldo=0
        """).fetchval()
            == 1
        )
        assert history == rows(
            c,
            "SELECT * FROM Contabilidad.MovimientosContables ORDER BY IdMovimientoContable",
        )
        con_delta = rows(
            c,
            "SELECT CodigoCuenta,EsImputable,Saldo FROM Contabilidad.CuentasContables ORDER BY CodigoCuenta",
        )
        assert [f for f in con_delta if f["CodigoCuenta"] != "740640"] == original
        original = con_delta
        checks["seps_2025_100_delta_idempotent_without_reserve_or_history_changes"] = (
            True
        )
        for _ in range(2):
            batches(c, folder / "004_corte_completo_ssms.sql")
        assert original == rows(
            c,
            "SELECT CodigoCuenta,EsImputable,Saldo FROM Contabilidad.CuentasContables ORDER BY CodigoCuenta",
        )
        checks["motor_install_does_not_create_children_or_change_flags"] = True
        plan = str(uuid.uuid4())
        cut = str(uuid.uuid4())
        values = [
            ("11010505", "BOVEDAS", "262955.63"),
            ("11010510", "JORNADAS", "560.00"),
            ("11010515", "ATM", "9860.00"),
            ("21013505", "AHO001-PN", "86646.76"),
            ("21013510", "AHO001-PJ", "76000.00"),
        ]
        payload = {
            "IdPlan": plan,
            "IdCorte": cut,
            "FechaCorte": "2026-10-14T18:00:00",
            "NumeroAsiento": "E201-ATOMICO",
            "IdFechaContable": 287,
            "IdAgencia": "001",
            "PreparadoPor": 101,
            "Alcance": "EFECTIVO_AHORRO",
            "Controles": [
                {
                    "CodigoAuxiliar": code,
                    "IdCustodio": who,
                    "Monto": float(amount),
                    "Fuente": "FIXTURE LOCAL",
                    "Evidencia": "Ensayo, no captura Azure",
                }
                for code, who, amount in values
            ],
            "ConciliacionAhorro": {
                "Libro210135": 162646.76,
                "LibroPN": 86646.76,
                "LibroPJ": 76000,
                "OperativoPN": 86646.76,
                "OperativoPJ": 76000,
                "LineasSinMapeo": 0,
                "EsEnsayo": True,
                "Evidencia": "FIXTURE LOCAL",
            },
        }
        checks["unmapped_preparer_rejected"] = expect_error(
            c, f"EXEC E201.usp_PrepararCorte '{plan}',N'{json.dumps(payload)}'", 56410
        )
        c.execute("CREATE USER E201_PrepRealTest WITHOUT LOGIN")
        c.execute("CREATE USER E201_AproRealTest WITHOUT LOGIN")
        c.execute("ALTER ROLE E201_PreparadorCorte ADD MEMBER E201_PrepRealTest")
        c.execute(
            "INSERT E201.IdentidadCorte VALUES(USER_SID(USER_ID('E201_PrepRealTest')),ORIGINAL_LOGIN(),101,1,1,'FIXTURE preparador'),(USER_SID(USER_ID('E201_AproRealTest')),ORIGINAL_LOGIN(),202,1,1,'FIXTURE aprobador')"
        )
        c.execute("EXECUTE AS USER='E201_PrepRealTest'")
        try:
            c.execute("EXEC E201.usp_PrepararCorte ?,?", plan, json.dumps(payload))
        finally:
            c.execute("REVERT")
        actual_hash = c.execute(
            "SELECT HashPlan FROM E201.PlanCorte WHERE IdPlan=?", plan
        ).fetchval()
        c.execute("EXECUTE AS USER='E201_AproRealTest'")
        try:
            checks["sql_real_approver_without_role_rejected"] = expect_error(
                c,
                f"EXEC E201.usp_AprobarCorteSSMS '{plan}',0x{actual_hash.hex()},'Prueba'",
                229,
            )
        finally:
            c.execute("REVERT")
        c.execute("ALTER ROLE E201_AprobadorCorte ADD MEMBER E201_AproRealTest")
        c.execute("EXECUTE AS USER='E201_AproRealTest'")
        try:
            checks["impersonation_same_original_login_rejected"] = expect_error(
                c,
                f"EXEC E201.usp_AprobarCorteSSMS '{plan}',0x{actual_hash.hex()},'Prueba'",
                56412,
            )
        finally:
            c.execute("REVERT")
        checks["authorized_flag_without_real_authorization_rejected"] = expect_error(
            c, f"EXEC E201.usp_RegistrarAprobacionReal 2001,'{plan}'", 56414
        )
        # Only the successful authorisation ROW is a DBA-seeded local fixture.
        # The native validator/procedures remain EXACTLY those in the SSMS bundle.
        c.execute(
            "UPDATE E201.IdentidadCorte SET NombreLogin='LOGIN_APROBADOR_SIMULADO' WHERE UsuarioID=202"
        )
        c.execute("SET IDENTITY_INSERT E201.AutorizacionSSMS ON")
        c.execute("""INSERT E201.AutorizacionSSMS(IdSolicitud,IdPlan,HashPlan,PreparadoPor,AprobadoPor,FechaAprobacion,PrincipalAprobador,LoginAprobador,Comentario)
        SELECT 2001,IdPlan,HashPlan,101,202,'20261116',USER_SID(USER_ID('E201_AproRealTest')),'LOGIN_APROBADOR_SIMULADO','FIXTURE LOCAL: no es aprobacion emitida por dos logins reales' FROM E201.PlanCorte""")
        c.execute("SET IDENTITY_INSERT E201.AutorizacionSSMS OFF")
        c.execute("ALTER ROLE E201_AprobadorCorte DROP MEMBER E201_AproRealTest")
        checks["approver_without_permission_rejected"] = expect_error(
            c, f"EXEC E201.usp_RegistrarAprobacionReal 2001,'{plan}'", 56414
        )
        c.execute("ALTER ROLE E201_AprobadorCorte ADD MEMBER E201_AproRealTest")
        checks["authorization_is_immutable"] = expect_error(
            c, "UPDATE E201.AutorizacionSSMS SET Comentario='Cambio'", 56415
        )
        c.execute("EXEC E201.usp_RegistrarAprobacionReal 2001,?", plan)
        assert original == rows(
            c,
            "SELECT CodigoCuenta,EsImputable,Saldo FROM Contabilidad.CuentasContables ORDER BY CodigoCuenta",
        )
        checks["register_receipt_does_not_apply_cut"] = True
        c.execute("UPDATE E201.IdentidadCorte SET Activo=0 WHERE UsuarioID=202")
        checks["revoked_permission_rechecked_at_execution"] = expect_error(
            c, "EXEC E201.usp_EjecutarCorte 2001", 56414
        )
        c.execute("UPDATE E201.IdentidadCorte SET Activo=1 WHERE UsuarioID=202")
        c.execute(
            "CREATE TRIGGER Contabilidad.trg_Lab_FalloFinal ON Contabilidad.AsientoContable AFTER UPDATE AS BEGIN IF EXISTS(SELECT 1 FROM inserted WHERE Estado='CONTABILIZADO') THROW 56999,N'Fallo simulado al contabilizar',1; END"
        )
        checks["failure_at_posting"] = expect_error(
            c, "EXEC E201.usp_EjecutarCorte 2001", 56999
        )
        assert original == rows(
            c,
            "SELECT CodigoCuenta,EsImputable,Saldo FROM Contabilidad.CuentasContables ORDER BY CodigoCuenta",
        )
        assert history == rows(
            c,
            "SELECT * FROM Contabilidad.MovimientosContables ORDER BY IdMovimientoContable",
        )
        assert (
            c.execute("SELECT COUNT(*) FROM Contabilidad.AsientoContable").fetchval()
            == 877
        )
        assert c.execute("SELECT COUNT(*) FROM E201.Reclasificacion").fetchval() == 0
        assert c.execute("SELECT COUNT(*) FROM E201.ControlCorte").fetchval() == 0
        assert (
            c.execute("SELECT Estado FROM E201.ReciboReal").fetchval() == "AUTORIZADA"
        )
        checks["rollback_children_flags_draft_lines_and_consumption_together"] = True
        c.execute("DROP TRIGGER Contabilidad.trg_Lab_FalloFinal")
        before = rows(
            c,
            "SELECT CodigoElemento,SUM(SaldoPropio) AS Total FROM E201.vw_SaldoPropio GROUP BY CodigoElemento ORDER BY CodigoElemento",
        )

        def execute(_):
            with connect(db) as other:
                cur = other.execute("EXEC E201.usp_EjecutarCorte 2001")
                result = []
                while True:
                    if cur.description:
                        result += [
                            dict(zip([v[0] for v in cur.description], r))
                            for r in cur.fetchall()
                        ]
                    if not cur.nextset():
                        return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = list(pool.map(execute, range(2)))
        assert (
            c.execute(
                "SELECT COUNT(*) FROM Contabilidad.MovimientosContables"
            ).fetchval()
            == 1775
        )
        assert (
            c.execute("SELECT COUNT(*) FROM Contabilidad.AsientoContable").fetchval()
            == 878
        )
        assert c.execute("SELECT Estado FROM E201.ReciboReal").fetchval() == "EJECUTADA"
        after = rows(
            c,
            "SELECT CodigoElemento,SUM(SaldoPropio) AS Total FROM E201.vw_SaldoPropio GROUP BY CodigoElemento ORDER BY CodigoElemento",
        )
        assert before == after
        balances = rows(
            c,
            "SELECT CodigoCuenta,SaldoPropio FROM E201.vw_SaldoPropio WHERE CodigoCuenta IN ('110105','210135','11010505','11010510','11010515','21013505','21013510') ORDER BY CodigoCuenta",
        )
        for code, _, amount in values:
            assert next(
                r["SaldoPropio"] for r in balances if r["CodigoCuenta"] == code
            ) == Decimal(amount)
        assert all(
            r["SaldoPropio"] == 0 for r in balances if len(r["CodigoCuenta"]) == 6
        )
        checks["concurrent_single_cut"] = attempts
        checks["historical_1768_lines_unchanged"] = history == rows(
            c,
            "SELECT * FROM Contabilidad.MovimientosContables WHERE IdMovimientoContable<=1768 ORDER BY IdMovimientoContable",
        )
        borrador = new_entry(c, "E201-REGLAS-LAB")
        insertar_linea = """
            INSERT Contabilidad.MovimientosContables
                (IdCuentaContable, IdAgencia, TipoMovimiento, Monto, FechaHora, IdAsientoContable)
            SELECT IdCuentaContable, '001', 'DEBITO', 1, '20261014 18:00:00', {asiento}
            FROM Contabilidad.CuentasContables WHERE CodigoCuenta='{codigo}'
        """
        checks["legacy_account_rejects_new_movements"] = expect_error(
            c, insertar_linea.format(asiento=borrador, codigo="110105"), 56311
        )
        checks["automatic_account_rejects_manual_movements"] = expect_error(
            c, insertar_linea.format(asiento=borrador, codigo="11010505"), 56312
        )
        total_lineas = c.execute(
            "SELECT COUNT(*) FROM Contabilidad.MovimientosContables"
        ).fetchval()
        for _ in range(2):
            batches(c, folder / "005_auxiliar_faltantes.sql")
        assert (
            c.execute("""
            SELECT COUNT(*) FROM Contabilidad.CuentasContables
            WHERE CodigoCuenta='19902505' AND EsImputable=1 AND EsCatalogoRegulador=0
        """).fetchval()
            == 1
        )
        assert (
            c.execute(
                "SELECT COUNT(*) FROM Contabilidad.MovimientosContables"
            ).fetchval()
            == total_lineas
        )
        checks["shortage_auxiliary_idempotent_without_history_changes"] = True
        report = {
            "database": db,
            "azure_accessed": False,
            "approval_source": "Native SSMS rejection paths tested; successful cut uses a LOCAL FIXTURE. Two independent authenticated logins not available in this runner. E0-08 is not installed.",
            "checks": checks,
            "balances": balances,
            "elements_before": before,
            "elements_after": after,
            "production_prerequisite": "DBA binds two verified accountant SQL identities, grants specific roles; positive approval requires separate original logins.",
        }
        output = ROOT / "Backend/docs/e201/resultados_corte_atomico.json"
        output.write_text(
            json.dumps(report, default=str, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {"database": db, "checks": list(checks), "report": str(output)},
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    run()
