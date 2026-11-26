"""Verifica los bloqueos E1-04 en una base desechable de SQL Server local."""

import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from app.core.security import auth as seguridad_auth
from app.core.security.auth import ROLES
from app.modules.aprobaciones import tareas
from app.modules.aprobaciones.auditoria import ContextoAuditoria
from app.modules.aprobaciones.identidad import Actor
from app.modules.aprobaciones.registro import Objetivo, Registro
from app.modules.aprobaciones.servicio import Servicio
from app.modules.auth import (
    aprobacion_roles,
    politica_roles,
    recuperacion_correo,
    repository,
    service,
)
from app.modules.organizacion.repository import bloquear_corte_asignaciones
from tests.sesion import usuario_con_roles

pytestmark = pytest.mark.skipif(
    os.getenv("E104_SQL_LOCAL") != "1", reason="Requiere SQL Server local explícito"
)


def motor(base: str, **opciones):
    url = URL.create(
        "mssql+pyodbc",
        query={
            "odbc_connect": (
                "DRIVER={ODBC Driver 18 for SQL Server};SERVER=lpc:localhost;"
                f"DATABASE={base};Trusted_Connection=yes;TrustServerCertificate=yes;"
            )
        },
    )
    return create_engine(url, **opciones)


@pytest.fixture(scope="module")
def laboratorio():
    nombre = f"E104_Lab_{uuid4().hex}"
    servidor = motor("master", isolation_level="AUTOCOMMIT")
    with servidor.connect() as admin:
        assert admin.scalar(text("SELECT CONNECTIONPROPERTY('net_transport')")) == (
            "Shared memory"
        )
        admin.exec_driver_sql(f"CREATE DATABASE [{nombre}]")
        lab = motor(nombre)
        try:
            with lab.begin() as conn:
                conn.exec_driver_sql("CREATE SCHEMA Organizacion")
                conn.exec_driver_sql(
                    """
                    CREATE TABLE Organizacion.Usuarios (
                        UsuarioID int PRIMARY KEY, NombreUsuario varchar(60),
                        Nombres varchar(60), Apellidos varchar(60), Email varchar(60),
                        Estado varchar(10), FechaCreacion datetime2, UltimoAcceso datetime2,
                        Cedula varchar(20), AgenciaID int, KeyUsuario varchar(60),
                        RolesWorkOS varchar(60)
                    )
                    """
                )
                conn.execute(
                    text(
                        "INSERT Organizacion.Usuarios (UsuarioID, Estado, KeyUsuario) "
                        "VALUES (1, 'Activo', :llave)"
                    ),
                    {"llave": usuario_con_roles("CAJERO").id_usuario},
                )
            yield lab
        finally:
            lab.dispose()
            # ODBC puede conservar conexiones inactivas tras dispose().
            admin.exec_driver_sql(
                f"ALTER DATABASE [{nombre}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                f"DROP DATABASE [{nombre}]"
            )
    servidor.dispose()


@pytest.mark.parametrize("apertura_primero", [True, False])
def test_apertura_y_edicion_bloquean_la_misma_fila(
    laboratorio, monkeypatch, apertura_primero
):
    actor = usuario_con_roles("CAJERO")
    monkeypatch.setattr(
        service,
        "_membresia",
        lambda _: SimpleNamespace(status="active", roles=[{"slug": "org-cajero"}]),
    )
    with laboratorio.connect() as apertura, laboratorio.connect() as edicion:
        if apertura_primero:
            with service.proteger_apertura_caja(apertura, 1, actor):
                edicion.exec_driver_sql("SET LOCK_TIMEOUT 100")
                with pytest.raises(DBAPIError, match="1222"):
                    repository.obtener_usuario(edicion, 1, bloquear=True)
        else:
            with edicion.begin():
                assert repository.obtener_usuario(edicion, 1, bloquear=True)
                with apertura.begin():
                    apertura.exec_driver_sql("SET LOCK_TIMEOUT 100")
                with (
                    pytest.raises(DBAPIError, match="1222"),
                    service.proteger_apertura_caja(apertura, 1, actor),
                ):
                    pytest.fail("La apertura debe esperar a la edición")
            with service.proteger_apertura_caja(apertura, 1, actor):
                pass


def test_bloqueo_administrativo_exclusivo_y_liberado_al_confirmar(laboratorio):
    with laboratorio.connect() as primero, laboratorio.connect() as segundo:
        with primero.begin():
            assert repository.bloquear_cambios_administrativos(primero)
            with segundo.begin():
                assert not repository.bloquear_cambios_administrativos(segundo)
        with segundo.begin():
            assert repository.bloquear_cambios_administrativos(segundo)


def test_ensayo_exige_identidad_y_revierte_la_carga(laboratorio):
    with laboratorio.begin() as conn:
        conn.exec_driver_sql("CREATE SCHEMA Caja")
        conn.exec_driver_sql("""
            CREATE TABLE Caja.CajerosAsignadosAgencia (
                IdUsuario int, IdAgencia char(3), Estado bit,
                FechaInicio datetime2, FechaFin datetime2
            )
            INSERT Caja.CajerosAsignadosAgencia VALUES (1, '001', 1, '2025-01-01', NULL)
            INSERT Caja.CajerosAsignadosAgencia VALUES (1, '002', 0, '2024-01-01', '2024-12-31')
            UPDATE Organizacion.Usuarios SET RolesWorkOS = 'CAJERO' WHERE UsuarioID = 1
            CREATE TABLE Organizacion.UsuarioAgencia (
                UsuarioID int, IdAgencia char(3), Activo bit,
                FechaAsignacion datetime2, Origen varchar(16),
                PRIMARY KEY (UsuarioID, IdAgencia)
            )
            CREATE TABLE Organizacion.UsuarioAgenciaHistorial (
                UsuarioID int, IdAgencia char(3), Accion varchar(20),
                PrincipalNueva char(3), FechaUTC datetime2
            )
        """)
    ruta = (
        Path(__file__).resolve().parents[2]
        / "scripts/sql/e104/ensayo_asignaciones_caja.sql"
    )
    nombre = laboratorio.url.query["odbc_connect"]
    base = nombre.split("DATABASE=", 1)[1].split(";", 1)[0]
    sql = (
        ruta.read_text(encoding="utf-8")
        .replace("BankingE305_Seguridad_Local", base)
        .replace("BankingE305_Cooperativa_Local", base)
    )
    with laboratorio.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        import pyodbc

        cursor = conn.connection.cursor()
        try:
            with pytest.raises(pyodbc.Error, match="51404"):
                cursor.execute(sql)
                while cursor.nextset():
                    pass
        finally:
            cursor.close()
        conn.exec_driver_sql(
            "IF OBJECT_ID('tempdb..#IdentidadesConfirmadas') IS NULL "
            "CREATE TABLE #IdentidadesConfirmadas (IdUsuario int PRIMARY KEY, UsuarioID int)"
        )
        conn.exec_driver_sql("INSERT #IdentidadesConfirmadas VALUES (1, 1)")
        for _ in range(2):
            assert tuple(conn.exec_driver_sql(sql).one()) == (1, 1, 2, 1)
            assert (
                conn.scalar(
                    text("SELECT OBJECT_ID('Organizacion.UsuarioAgenciaLegado')")
                )
                is None
            )
            assert (
                conn.scalar(text("SELECT COUNT(*) FROM Organizacion.UsuarioAgencia"))
                == 0
            )
            assert (
                conn.scalar(
                    text("SELECT COUNT(*) FROM Organizacion.UsuarioAgenciaHistorial")
                )
                == 0
            )

        conn.exec_driver_sql(
            "EXEC sp_set_session_context N'e104_aplicar_asignaciones', 1"
        )
        try:
            assert tuple(conn.exec_driver_sql(sql).one()) == (1, 1, 2, 1)
            assert tuple(conn.exec_driver_sql(sql).one()) == (1, 0, 2, 1)
            assert (
                conn.scalar(
                    text("SELECT SUM(Cantidad) FROM Organizacion.UsuarioAgenciaLegado")
                )
                == 2
            )
        finally:
            conn.exec_driver_sql(
                "EXEC sp_set_session_context N'e104_aplicar_asignaciones', NULL"
            )


def test_diario_correo_sobrevive_rollback_y_reintento_es_idempotente(
    laboratorio, monkeypatch
):
    migracion = (
        Path(__file__).resolve().parents[2]
        / "migrations/seguridad/202611240901_e104_recuperacion_correo.up.sql"
    )
    llave = usuario_con_roles("CAJERO").id_usuario
    anterior = "anterior@example.test"
    remoto = SimpleNamespace(email="incierto@example.test")
    llamadas = []

    def actualizar(**datos):
        llamadas.append(datos)
        remoto.email = datos["email"]

    gestion = SimpleNamespace(get_user=lambda _: remoto, update_user=actualizar)
    monkeypatch.setattr(
        recuperacion_correo,
        "get_workos",
        lambda: SimpleNamespace(user_management=gestion),
    )
    with laboratorio.begin() as conn:
        conn.exec_driver_sql(
            "IF SCHEMA_ID('Seguridad') IS NULL EXEC('CREATE SCHEMA Seguridad')"
        )
        conn.exec_driver_sql(
            "DECLARE @base nvarchar(128)=DB_NAME(); "
            "EXEC sp_set_session_context N'migration_database', @base"
        )
        conn.exec_driver_sql(migracion.read_text(encoding="utf-8"))
        conn.exec_driver_sql(
            migracion.with_name(
                "202611240902_e104_conciliacion_roles_invitacion.up.sql"
            ).read_text(encoding="utf-8")
        )
        conn.execute(
            text("UPDATE Organizacion.Usuarios SET Email=:correo WHERE UsuarioID=1"),
            {"correo": anterior},
        )
    with laboratorio.connect() as conn:
        assert repository.obtener_usuario(conn, 1, bloquear=True)
        registro = recuperacion_correo.registrar(laboratorio, 1, llave)
        conn.execute(
            text(
                "UPDATE Organizacion.Usuarios SET Email='incierto@example.test' WHERE UsuarioID=1"
            )
        )
        conn.rollback()

    assert (registro, 1) in recuperacion_correo.pendientes(laboratorio)
    recuperacion_correo.registrar_error(laboratorio, registro)
    recuperacion_correo.reconciliar(laboratorio, registro, 1)
    recuperacion_correo.reconciliar(laboratorio, registro, 1)
    assert remoto.email == anterior
    assert llamadas == [{"user_id": llave, "email": anterior}]
    assert recuperacion_correo.pendientes(laboratorio) == []

    miembro = SimpleNamespace(id="om_qa", roles=[{"slug": "org-auditor"}])
    monkeypatch.setattr(service, "_membresia", lambda _: miembro)
    monkeypatch.setattr(service, "_validar_ultimo_admin", lambda *_: None)
    monkeypatch.setattr(service, "_revocar_sesiones", lambda *_: None)
    restaurados = []

    def devolver_roles(**datos):
        restaurados.append(datos)
        miembro.roles = [{"slug": datos["role_slug"]}]

    gestion.update_organization_membership = devolver_roles
    with laboratorio.begin() as conn:
        conn.exec_driver_sql(
            "UPDATE Organizacion.Usuarios SET RolesWorkOS='CAJERO' WHERE UsuarioID=1"
        )
    roles = recuperacion_correo.registrar(laboratorio, 1, llave, "Roles")
    recuperacion_correo.reconciliar(laboratorio, roles, 1)
    recuperacion_correo.reconciliar(laboratorio, roles, 1)
    assert restaurados == [
        {"organization_membership_id": "om_qa", "role_slug": "org-cajero"}
    ]

    with laboratorio.begin() as conn:
        conn.exec_driver_sql("""
            INSERT Organizacion.Usuarios (UsuarioID, Estado, Email, RolesWorkOS)
            VALUES (2, 'Activo', 'invitado@example.test', 'CAJERO')
        """)
    anterior_inv = SimpleNamespace(id="inv_anterior")
    invitaciones = [anterior_inv, SimpleNamespace(id="inv_ambiguo")]
    monkeypatch.setattr(service, "_invitaciones_pendientes", lambda _: invitaciones)
    invitacion = recuperacion_correo.registrar(
        laboratorio, 2, "inv_anterior", "Invitar"
    )
    with pytest.raises(HTTPException) as pendiente:
        recuperacion_correo.reconciliar(laboratorio, invitacion, 2)
    assert pendiente.value.status_code == 409
    with laboratorio.begin() as conn:
        assert repository.invitacion_en_conciliacion(conn, "invitado@example.test")
    invitaciones.pop()
    recuperacion_correo.reconciliar(laboratorio, invitacion, 2)
    assert recuperacion_correo.pendientes(laboratorio) == []


@pytest.mark.parametrize("primero", ["asignacion", "baja"])
def test_corte_no_deja_entrar_asignacion_y_baja_simultaneas(
    laboratorio, primero, monkeypatch
):
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(e104_corte_asignacion_caja=True),
    )
    asignacion, baja = service.bloquear_corte_caja, bloquear_corte_asignaciones
    ganador, perdedor = (
        (asignacion, baja) if primero == "asignacion" else (baja, asignacion)
    )
    with laboratorio.connect() as uno, laboratorio.connect() as dos:
        with uno.begin():
            ganador(uno)
            with pytest.raises(HTTPException) as ocupada, dos.begin():
                perdedor(dos)
            assert ocupada.value.status_code == 409, primero
        with dos.begin():
            perdedor(dos)


def test_roles_e008_resoluciones_y_recuperacion(laboratorio, monkeypatch):
    carpeta = Path(__file__).resolve().parents[2] / "migrations/seguridad"
    with laboratorio.begin() as conn:
        conn.exec_driver_sql(
            "DECLARE @base nvarchar(128)=DB_NAME(); "
            "EXEC sp_set_session_context N'migration_database', @base; "
            "EXEC sp_set_session_context N'e104_permiso_aprobar_roles', N'qa:roles'"
        )
        for archivo in (
            "202611180800_aprobaciones_catalogo.up.sql",
            "202611180801_aprobaciones_solicitudes.up.sql",
            "202611180802_aprobaciones_entrega.up.sql",
            "202611240900_e104_roles_aprobacion.up.sql",
        ):
            conn.exec_driver_sql((carpeta / archivo).read_text(encoding="utf-8"))
        conn.exec_driver_sql(
            "UPDATE Organizacion.Usuarios SET RolesWorkOS='CAJERO', AgenciaID=1 WHERE UsuarioID=1"
        )
    org = "org_qa"
    creador = Actor("maker", org, None, 10, ("ADMIN",), frozenset(), ())
    aprobador = Actor(
        "checker", org, None, 11, ("AUDITOR",), frozenset({"qa:roles"}), ()
    )
    actores = {a.sujeto: a for a in (creador, aprobador)}
    miembro = SimpleNamespace(
        id="om_qa", status="active", roles=[{"slug": "org-cajero"}]
    )
    escrituras = []

    def actualizar(**datos):
        escrituras.append(datos)
        miembro.roles = [{"slug": slug} for slug in datos["role_slugs"]]
        raise httpx.ReadTimeout("respuesta sintética perdida")

    monkeypatch.setattr(aprobacion_roles, "get_organizacion_id", lambda: org)
    monkeypatch.setattr(
        aprobacion_roles.identidad, "vigente", lambda sujeto, _: actores[sujeto]
    )
    monkeypatch.setattr(aprobacion_roles, "get_engine", lambda _: laboratorio)
    monkeypatch.setattr(
        aprobacion_roles, "jornada_abierta_de_usuario", lambda *_, **__: None
    )
    monkeypatch.setattr(
        aprobacion_roles.agencias_repository, "asignaciones", lambda *_: ["001"]
    )
    monkeypatch.setattr(
        aprobacion_roles,
        "get_workos",
        lambda: SimpleNamespace(
            user_management=SimpleNamespace(update_organization_membership=actualizar)
        ),
    )
    monkeypatch.setattr(service, "_membresia", lambda _: miembro)
    monkeypatch.setattr(service, "_validar_ultimo_admin", lambda *_: None)
    monkeypatch.setattr(service, "_revocar_sesiones", lambda _: None)
    monkeypatch.setattr(
        politica_roles,
        "vigente",
        lambda: politica_roles.PoliticaRoles(
            niveles={rol: 1 for rol in ROLES},
            privilegiados={"AUDITOR"},
            incompatibles=[],
        ),
    )
    opciones = SimpleNamespace(
        e104_permiso_aprobar_roles="qa:roles",
        e104_politica_roles_activa=True,
        e104_corte_asignacion_caja=False,
        e104_recuperar_correo=False,
    )
    monkeypatch.setattr(aprobacion_roles, "get_settings", lambda: opciones)
    registro = Registro()
    operacion = aprobacion_roles.operacion()
    assert operacion is not None
    registro.agregar(operacion)
    cola = Servicio(
        laboratorio, laboratorio, registro, lambda sujeto, _: actores[sujeto]
    )
    contexto = ContextoAuditoria()

    def solicitar():
        return cola.solicitar(
            creador,
            operacion.codigo,
            Objetivo(operacion.tipo_objetivo, "1", None),
            {"roles": ["CAJERO", "AUDITOR"]},
            date(2026, 11, 24),
            contexto,
        )

    rechazada = solicitar()
    with pytest.raises(HTTPException) as propia:
        cola.aprobar(creador, rechazada, None, contexto)
    assert propia.value.status_code == 403
    assert (
        cola.resolver(aprobador, rechazada, "Rechazada", "Prueba", contexto)["estado"]
        == "Rechazada"
    )
    cancelada = solicitar()
    assert (
        cola.resolver(creador, cancelada, "Cancelada", "", contexto)["estado"]
        == "Cancelada"
    )
    pendiente = solicitar()
    opciones.e104_politica_roles_activa = False
    assert aprobacion_roles.operacion() is None
    monkeypatch.setattr(tareas, "get_settings", lambda: opciones)
    suspendida = Servicio(
        laboratorio, laboratorio, Registro(), lambda sujeto, _: actores[sujeto]
    )
    assert tareas.recuperar(suspendida, org) == tareas.Conteo()
    assert escrituras == []
    with laboratorio.connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT Estado FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"
                ),
                {"id": pendiente},
            )
            == "Pendiente"
        )
    opciones.e104_politica_roles_activa = True
    with pytest.raises(HTTPException) as ambigua:
        cola.aprobar(aprobador, pendiente, None, contexto)
    assert ambigua.value.status_code == 503
    opciones.e104_politica_roles_activa = False
    assert tareas.recuperar(suspendida, org) == tareas.Conteo()
    assert len(escrituras) == 1
    opciones.e104_politica_roles_activa = True
    monkeypatch.setattr(seguridad_auth, "get_engine", lambda _: laboratorio)
    monkeypatch.setattr(
        seguridad_auth,
        "get_settings",
        lambda: SimpleNamespace(
            e104_permiso_aprobar_roles="qa:roles",
            workos_organization_id=org,
            e104_recuperar_correo=False,
        ),
    )
    llave = usuario_con_roles("CAJERO").id_usuario
    assert seguridad_auth._id_interno_db(llave, "CAJERO,AUDITOR") is None
    assert seguridad_auth._id_interno_db(llave, "CAJERO") == 1
    with laboratorio.connect() as conn:
        assert (
            conn.scalar(
                text(
                    "SELECT Estado FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id"
                ),
                {"id": pendiente},
            )
            == "Aprobada"
        )
        assert (
            conn.scalar(
                text("SELECT RolesWorkOS FROM Organizacion.Usuarios WHERE UsuarioID=1")
            )
            == "CAJERO"
        )

    actores["checker"] = Actor("checker", org, None, 11, ("AUDITOR",), frozenset(), ())
    with pytest.raises(HTTPException) as revocado:
        cola.ejecutar(pendiente, org, None, contexto)
    assert revocado.value.status_code == 503
    actores["checker"] = aprobador
    assert cola.ejecutar(pendiente, org, None, contexto)["estado"] == "Ejecutada"
    assert cola.ejecutar(pendiente, org, None, contexto)["estado"] == "Ejecutada"
    assert len(escrituras) == 1
