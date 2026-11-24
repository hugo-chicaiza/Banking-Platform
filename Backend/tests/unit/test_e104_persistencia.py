import sqlite3
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Connection, create_engine

from app.modules.auth import agencias_repository as agencias
from app.modules.auth import repository as usuarios


def test_traslado_sql_preserva_vencimiento_y_limita_actualizacion():
    motor = create_engine("sqlite://")
    with motor.begin() as conn:
        driver = conn.connection.driver_connection
        assert isinstance(driver, sqlite3.Connection)
        driver.create_function("SYSUTCDATETIME", 0, lambda: "2026-11-23T13:00:00")
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS Seguridad")
        conn.exec_driver_sql("""
            CREATE TABLE Seguridad.ContextoAgenciaSesion (
                IdSesionHash blob, UsuarioID int, IdAgencia text,
                FechaCambioUTC text, ExpiraUTC text
            );
        """)
        conn.exec_driver_sql("""
            INSERT INTO Seguridad.ContextoAgenciaSesion VALUES
                (X'01', 2, '001', NULL, '2026-11-23T14:00:00'),
                (X'02', 2, '001', NULL, '2026-11-23T12:00:00'),
                (X'03', 3, '001', NULL, '2026-11-23T14:00:00');
        """)
        agencias.trasladar_contextos_vigentes(conn, 2, "001", "002")
        assert agencias.contexto(conn, b"\x01", 2) == {"agencia": "002", "vigente": 1}
        assert agencias.contexto(conn, b"\x02", 2) == {"agencia": "001", "vigente": 0}
        assert agencias.contexto(conn, b"\x03", 3) == {"agencia": "001", "vigente": 1}
        assert (
            conn.exec_driver_sql("""
            SELECT ExpiraUTC FROM Seguridad.ContextoAgenciaSesion WHERE IdSesionHash = X'01'
        """).scalar_one()
            == "2026-11-23T14:00:00"
        )
    motor.dispose()


@pytest.mark.parametrize(
    ("resultado", "obtenido"), [(0, True), (1, True), (-1, False), (None, False)]
)
def test_bloqueo_de_administradores_solo_admite_resultados_validos(resultado, obtenido):
    conn = MagicMock(spec=Connection)
    conn.scalar.return_value = resultado
    assert usuarios.bloquear_cambios_administrativos(conn) is obtenido
    consulta = str(conn.scalar.call_args.args[0])
    assert "E104_ADMIN_ACTIVO" in consulta
    assert "@LockOwner = 'Transaction'" in consulta


def test_listado_de_usuarios_parametriza_filtros_y_pagina():
    conn = MagicMock(spec=Connection)
    resultado = conn.execute.return_value
    resultado.scalar_one.return_value = 21
    fila = {"UsuarioID": 2, "RolesWorkOS": "ASESOR,AUDITOR"}
    resultado.mappings.return_value.all.return_value = [fila]
    assert usuarios.listar_usuarios(
        conn,
        q="20%_[",
        estado="Activo",
        agencia_id=2,
        rol="AUDITOR",
        vinculado=True,
        orden="username,asc",
        page=2,
        page_size=10,
        id_usuario=2,
        nombre="Ana_%",
    ) == ([fila], 21)
    contar, listar = conn.execute.call_args_list
    filtros = {
        "q": r"%20\%\_\[%",
        "estado": "Activo",
        "agencia": 2,
        "rol": "AUDITOR",
        "vinculado": 1,
        "id_usuario": 2,
        "nombre": r"%Ana\_\%%",
    }
    assert contar.args[1] == filtros
    assert listar.args[1] == {
        **filtros,
        "orden": "username,asc",
        "offset": 10,
        "page_size": 10,
    }


def test_persistencia_de_historial_conserva_fechas_y_autor():
    conn = MagicMock(spec=Connection)
    fila = {
        "id_historial": 7,
        "id_agencia": "002",
        "fecha_utc": datetime(2026, 11, 23),
        "realizado_por": 4,
    }
    conn.execute.return_value.mappings.return_value.all.return_value = [fila]
    conn.scalar.return_value = 3
    assert agencias.historial(conn, 2, 2, 2) == ([fila], 3)
    assert conn.execute.call_args.args[1] == {"id": 2, "offset": 2, "size": 2}
    assert conn.scalar.call_args.args[1] == {"id": 2}


def test_persistencia_de_roles_y_vinculo_conserva_identidad_de_workos():
    conn = MagicMock(spec=Connection)
    resultado = conn.execute.return_value
    resultado.rowcount = 1
    resultado.first.return_value = None
    assert not usuarios.vinculado_a_otro(conn, "user_qa", 2)
    assert usuarios.vincular_por_id(conn, 2, "user_qa")
    assert conn.execute.call_args.args[1] == {"id_usuario": 2, "id_workos": "user_qa"}
    assert usuarios.vincular(conn, "user_qa", "qa@example.invalid")
    usuarios.registrar_acceso(conn, "user_qa")
    usuarios.actualizar_rol(conn, 2, "ASESOR,AUDITOR")
    assert conn.execute.call_args.args[1] == {"id": 2, "rol": "ASESOR,AUDITOR"}
    resultado.scalar_one.return_value = 1
    assert usuarios.contar_activos_vinculados(conn, ["user_otro"], 2) == 1
    assert conn.execute.call_args.args[1] == {"ids": ["user_otro"], "excluir": 2}


def test_traslado_de_cajero_cierra_asignacion_y_conserva_autor():
    conn = MagicMock(spec=Connection)
    resultado = conn.execute.return_value
    vigente = {"IdAgencia": "001"}
    resultado.mappings.return_value.first.return_value = vigente
    assert usuarios.asignacion_vigente(conn, 2) == vigente
    usuarios.cerrar_asignacion(conn, 2)
    assert conn.execute.call_args.args[1] == {"id": 2}
    usuarios.abrir_asignacion(conn, 2, "002", asignado_por=4, motivo="traslado")
    assert conn.execute.call_args.args[1] == {
        "id": 2,
        "agencia": "002",
        "por": 4,
        "motivo": "traslado",
    }


def test_asignaciones_sesion_y_principal_usen_el_mismo_usuario():
    conn = MagicMock(spec=Connection)
    resultado = conn.execute.return_value
    fila = {"UsuarioID": 2, "AgenciaID": 1, "Estado": "Activo"}
    resultado.mappings.return_value.first.return_value = fila
    resultado.mappings.return_value.__iter__.return_value = iter(
        [{"id_agencia": "002"}]
    )
    conn.scalars.return_value = ["001"]
    conn.scalar.return_value = None
    assert agencias.usuario_por_llave(conn, "user_qa") == fila
    assert agencias.asignaciones(conn, 2) == ["001"]
    assert agencias.agencias(conn) == [{"id_agencia": "002"}]
    assert agencias.version(conn, 2) == 0
    agencias.guardar_asignacion(conn, 2, "002", True, 4)
    assert conn.execute.call_args.args[1] == {
        "id": 2,
        "agencia": "002",
        "activa": True,
        "actor": 4,
    }
    agencias.principal(conn, 2, "002")
    assert conn.execute.call_args.args[1] == {"id": 2, "agencia": 2}
    agencias.historico(conn, 2, "PRINCIPAL", None, "001", "002", 4, "001")
    assert conn.execute.call_args.args[1]["anterior"] == "001"
    assert conn.execute.call_args.args[1]["nueva"] == "002"
    agencias.inicializar_contexto(conn, b"sid", 2, "002")
    assert conn.execute.call_args.args[1] == {"sid": b"sid", "id": 2, "agencia": "002"}
    agencias.guardar_contexto(conn, b"sid", 2, "002")
    assert conn.execute.call_args.args[1]["id"] == 2
    agencias.eliminar_contexto(conn, b"sid", 2)
    assert conn.execute.call_args.args[1] == {"sid": b"sid", "id": 2}


def test_repositorio_de_edicion_mantiene_bloqueo_y_excluye_al_usuario_actual():
    conn = MagicMock(spec=Connection)
    resultado = conn.execute.return_value
    fila = {"UsuarioID": 2}
    resultado.mappings.return_value.first.return_value = fila
    resultado.first.return_value = None
    assert usuarios.obtener_usuario(conn, 2, bloquear=True) == fila
    assert "UPDLOCK" in str(conn.execute.call_args.args[0])
    assert not usuarios.existe_duplicado(
        conn, username=None, email="qa@example.invalid", cedula=None, excluir_id=2
    )
    assert conn.execute.call_args.args[1]["excluir"] == 2
    usuarios.actualizar_usuario(
        conn, 2, nombres=None, apellidos=None, email=None, estado="Activo", agencia_id=2
    )
    consulta, parametros = conn.execute.call_args.args
    assert "Estado = 'Bloqueado' THEN 0" in str(consulta)
    assert parametros == {
        "id": 2,
        "nombres": None,
        "apellidos": None,
        "email": None,
        "estado": "Activo",
        "agencia": 2,
    }
    assert not usuarios.agencia_activa(conn, "002")
    assert conn.execute.call_args.args[1] == {"id": "002"}
