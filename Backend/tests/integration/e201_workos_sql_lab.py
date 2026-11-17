"""Ensayo del recibo WorkOS en una copia local que ya tiene 004."""

import json
import sys
from uuid import uuid4

import pyodbc
from e201_sql_lab import ROOT, batches, connect


def probar(database):
    if not database.startswith("CooperativaDB_E201_Lab_"):
        raise ValueError("Se requiere una base local de ensayo.")
    with connect(database) as db:
        for _ in range(2):
            batches(db, ROOT / "Backend/scripts/sql/e201/006_aprobacion_workos.sql")
        db.execute("""
            IF DATABASE_PRINCIPAL_ID('E201_LabServicio') IS NULL
            BEGIN
                CREATE USER E201_LabServicio WITHOUT LOGIN;
                ALTER ROLE E201_ServicioWorkOS ADD MEMBER E201_LabServicio;
            END;
            INSERT E201.PermisoWorkOS(UsuarioID,Preparar,Aprobar)
            SELECT n.Id,n.Preparar,1 FROM (VALUES (901,1),(902,0)) n(Id,Preparar)
            WHERE NOT EXISTS(SELECT 1 FROM E201.PermisoWorkOS WHERE UsuarioID=n.Id);
            UPDATE E201.PermisoWorkOS
            SET Aprobar=1,Organizacion='org-lab',
                Sujeto=CASE WHEN UsuarioID=901 THEN 'local-prep' ELSE 'local-approver' END
            WHERE UsuarioID IN (901,902);
        """)
        plan = str(uuid4())
        call = "EXEC E201.usp_PlanWorkOS ?,?,?,?,?,?,?,?"

        def run(sql, *args):
            cur = db.execute(sql, *args)
            result = None
            while True:
                if cur.description is not None:
                    result = cur.fetchall()
                if not cur.nextset():
                    return result

        def deny(code, sql, *args):
            try:
                run(sql, *args)
            except pyodbc.Error as error:
                assert f"({code})" in str(error), str(error)
            else:
                raise AssertionError(f"Faltó el rechazo {code}")

        args = (
            "PREPARAR",
            901,
            "local-prep",
            "org-lab",
            plan,
            json.dumps({"Alcance": "EFECTIVO_AHORRO", "PreparadoPor": 999}),
            None,
            None,
        )
        deny(56420, call, *args)
        db.execute("EXECUTE AS USER='E201_LabServicio'")
        try:
            deny(229, "UPDATE E201.PermisoWorkOS SET Aprobar=1 WHERE UsuarioID=901")
            deny(56411, call, *args[:1], 902, *args[2:])
            preparado = run(call, *args)
            assert preparado
            result = preparado[0]
            assert json.loads(result.Contenido)["PreparadoPor"] == 901
            digest = bytes.fromhex(result.HashPlan)
            deny(
                56412,
                call,
                "APROBAR",
                901,
                "local-prep",
                "org-lab",
                plan,
                None,
                digest,
                "same",
            )
            deny(
                56411,
                call,
                "VER",
                902,
                "local-approver",
                "otro-org",
                plan,
                None,
                None,
                None,
            )
            aprobacion = ("APROBAR", 902, "local-approver", "org-lab", plan, None)
            deny(56413, call, *aprobacion, bytes(32), "wrong")
            aprobado = run(call, *aprobacion, digest, "review")
            assert aprobado
            receipt = aprobado[0].IdSolicitud
            deny(56413, call, *aprobacion, digest, "repeat")
        finally:
            db.execute("REVERT")
        assert receipt < 0
        identidades = db.execute(
            "SELECT PreparadoPor,AprobadoPor FROM E201.ReciboReal WHERE IdSolicitud=?",
            receipt,
        ).fetchone()
        assert identidades is not None and tuple(identidades) == (901, 902)
        db.execute("UPDATE E201.PermisoWorkOS SET Aprobar=0 WHERE UsuarioID=902")
        deny(
            56414,
            "DECLARE @p int,@a int,@f datetime2; EXEC E201.usp_ValidarAprobacionCorte ?,?,?,@p OUTPUT,@a OUTPUT,@f OUTPUT",
            receipt,
            plan,
            digest,
        )
        print(
            "Recibo WorkOS y rechazo de autoaprobación, hash inválido, doble aprobación del mismo plan y permiso revocado: OK"
        )


if __name__ == "__main__":
    probar(sys.argv[1])
