from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request

from app.modules.clientes import firmantes, relaciones, tutores

HOY = date(2026, 11, 27)
INICIO = HOY - timedelta(days=1)
NACIMIENTO_ADULTO = date(1989, 4, 10)
NACIMIENTO_MENOR = date(2015, 2, 15)
RESPALDO = {
    "tipo_respaldo": "Resolución",
    "referencia_respaldo": "QA-002",
}


@pytest.fixture(autouse=True)
def fecha_y_mayoria(monkeypatch):
    monkeypatch.setattr(tutores, "hoy", lambda: HOY)
    monkeypatch.setattr(relaciones.general, "valor", lambda *_: 18)


def titular(nacimiento=NACIMIENTO_MENOR):
    return SimpleNamespace(
        Estado="Activo", TipoCliente="Natural", FechaNacimiento=nacimiento
    )


def anterior(persona=2, inicio=INICIO):
    return SimpleNamespace(
        IdRelacion=7, IdClienteRelacionado=persona, FechaInicio=inicio, FechaFin=None
    )


def conexion(*, cliente=None, adulto=NACIMIENTO_ADULTO, cruces=()):
    conn = MagicMock()
    conn.execute.return_value.first.return_value = (
        titular() if cliente is None else cliente
    )
    conn.execute.return_value.scalar_one_or_none.return_value = adulto
    conn.execute.return_value.all.return_value = cruces
    conn.execute.return_value.scalar_one.return_value = 8
    return conn


def solicitud(persona=3, fecha=HOY):
    return tutores.AltaTutor(
        id_cliente_relacionado=persona, fecha_efectiva=fecha, **RESPALDO
    )


def request():
    return Request({"type": "http", "headers": []})


@pytest.mark.parametrize("relevo", [False, True])
def test_tutor_guarda_vigencia_y_respaldo_en_la_transaccion(monkeypatch, relevo):
    auditoria = []
    monkeypatch.setattr(tutores.audit, "registrar", auditoria.append)
    conn = conexion(cruces=[anterior()] if relevo else [])
    datos = solicitud()
    if relevo:
        cambio = tutores.RelevoTutor(**datos.model_dump(), id_relacion_anterior=7)
        assert tutores.relevo(1, cambio, conn, 4, request()) == 8
        update = next(
            c.args
            for c in conn.execute.call_args_list
            if "UPDATE Clientes" in str(c.args[0])
        )
        assert update[1]["fin"] == INICIO and update[1]["anterior"] == 7
        assert update[1]["referencia"] == "QA-002"
    else:
        assert tutores.alta(1, datos, conn, 4, request()) == 8
    insert = conn.execute.call_args.args[1]
    assert (
        insert["inicio"] == HOY
        and insert["actor"] == 4
        and insert["tipo"] == "Resolución"
    )
    conn.begin.assert_called_once()
    esperados = [("CLI_RELACION_INICIADA", "8")]
    if relevo:
        esperados.insert(0, ("CLI_RELACION_TERMINADA", "7"))
    assert [(e.accion, e.id_registro) for e in auditoria] == esperados


@pytest.mark.parametrize(
    "datos,cliente,adulto,cruces,id_anterior,estado",
    [
        (
            solicitud(fecha=HOY + timedelta(days=1)),
            None,
            NACIMIENTO_ADULTO,
            [],
            None,
            422,
        ),
        (solicitud(fecha=date(2014, 1, 1)), None, NACIMIENTO_ADULTO, [], None, 422),
        (solicitud(persona=1), None, NACIMIENTO_ADULTO, [], None, 422),
        (solicitud(), None, NACIMIENTO_MENOR, [], None, 422),
        (solicitud(), titular(NACIMIENTO_ADULTO), NACIMIENTO_ADULTO, [], None, 422),
        (solicitud(), None, NACIMIENTO_ADULTO, [anterior()], None, 409),
        (solicitud(), None, NACIMIENTO_ADULTO, [anterior()], 9, 409),
        (solicitud(persona=2), None, NACIMIENTO_ADULTO, [anterior()], 7, 422),
        (solicitud(), None, NACIMIENTO_ADULTO, [anterior(inicio=HOY)], 7, 422),
    ],
)
def test_tutor_rechaza_perfiles_fechas_y_conflictos_sin_escribir(
    datos, cliente, adulto, cruces, id_anterior, estado
):
    conn = conexion(cliente=cliente, adulto=adulto, cruces=cruces)
    with pytest.raises(HTTPException) as error:
        tutores._guardar(conn, 1, datos, 4, id_anterior)
    assert error.value.status_code == estado
    assert all(
        str(c.args[0]).strip().startswith("SELECT") for c in conn.execute.call_args_list
    )


def fila_historial(id_relacion, nombre, inicio, fin=None):
    return {
        "id_relacion": id_relacion,
        "nombre": nombre,
        "fecha_inicio": inicio,
        "fecha_fin": fin,
        "tipo_respaldo_alta": "Acta",
        "respaldo_alta": "QA-001",
        "tipo_respaldo_fin": None,
        "respaldo_fin": None,
        "creado_por": 4,
        "fecha_creacion": datetime(2026, 11, 27, 15),
        "finalizado_por": None,
        "finalizado_en": None,
    }


def test_historial_reconstruye_fecha_efectiva_y_detecta_dos_vigentes():
    conn = conexion()
    nuevo = fila_historial(8, "Luis", HOY)
    previo = fila_historial(7, "Ana", INICIO, INICIO)
    conn.execute.return_value.mappings.return_value = [nuevo, previo]
    datos = tutores.listar(1, conn)
    assert datos.admite_tutor and datos.id_vigente == 8
    assert [r.nombre for r in datos.historial] == ["Luis", "Ana"]
    conn.execute.return_value.mappings.return_value = [
        nuevo,
        {**previo, "fecha_fin": None},
    ]
    with pytest.raises(HTTPException) as error:
        tutores.listar(1, conn)
    assert error.value.status_code == 409


def test_historial_devuelve_404_si_falta_ficha():
    conn = conexion()
    conn.execute.return_value.first.return_value = None
    with pytest.raises(HTTPException) as error:
        tutores.listar(1, conn)
    assert error.value.status_code == 404


@pytest.mark.parametrize(
    "filas,persona",
    [
        ([], None),
        ([{"FechaNacimiento": None, "IdClienteRelacionado": 2}], None),
        ([{"FechaNacimiento": NACIMIENTO_MENOR, "IdClienteRelacionado": 2}], None),
        ([{"FechaNacimiento": NACIMIENTO_ADULTO, "IdClienteRelacionado": 2}], 2),
    ],
)
def test_tutor_vigente_para_cuentas_requiere_adulto(filas, persona):
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.all.return_value = filas
    actual = relaciones.relacion_vigente(conn, 1, "Tutor", HOY)
    assert (actual["IdClienteRelacionado"] if actual is not None else None) == persona


def test_tutor_vigente_no_elige_entre_dos_relaciones():
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.all.return_value = [{}, {}]
    with pytest.raises(HTTPException) as error:
        relaciones.relacion_vigente(conn, 1, "Tutor", HOY)
    assert error.value.status_code == 409


def test_mayoria_de_edad_rechaza_un_parametro_invalido(monkeypatch):
    monkeypatch.setattr(relaciones.general, "valor", lambda *_: 0)
    with pytest.raises(HTTPException) as error:
        relaciones.edad_mayoria(MagicMock(), HOY)
    assert error.value.status_code == 503


def test_relacionados_conserva_historial_de_firmantes():
    conn = MagicMock()
    conn.execute.return_value.scalar_one_or_none.return_value = "Activo"
    datos = fila_historial(7, "Rosa", INICIO, HOY)
    conn.execute.return_value.mappings.return_value = [
        {**datos, "id_cliente_relacionado": 2, "alcance": "Constancia"}
    ]
    [registro] = firmantes.listar(1, conn)
    assert registro.nombre == "Rosa" and registro.fecha_fin == HOY
    assert "TipoRelacion='Firmante'" in str(conn.execute.call_args.args[0])
