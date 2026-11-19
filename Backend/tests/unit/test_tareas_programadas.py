"""E0-06: ejecutor de tareas (bloqueo, registro, manual con motivo), vigilante y web jobs."""

import json
from pathlib import Path

import pytest

from app.core.tareas import __main__ as cli
from app.core.tareas import ejecutor, registro, vigilante
from app.core.tareas.ejecutor import Conteo, Tarea, TareaEnCurso, TareaRechazada

BACKEND = Path(__file__).resolve().parents[2]


class _Resultado:
    def __init__(self, valor=None, filas=None):
        self.valor, self.filas = valor, filas or []

    def scalar_one(self):
        return self.valor

    def mappings(self):
        return self

    def first(self):
        return self.filas[0] if self.filas else None

    def all(self):
        return self.filas


class _Conexion:
    def __init__(self, bloqueo=0, tarea=None):
        self.bloqueo, self.tarea, self.sql = bloqueo, tarea, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        s = str(sql)
        self.sql.append((s, params or {}))
        if "sp_getapplock" in s:
            return _Resultado(self.bloqueo)
        if s.startswith("SELECT Estado"):
            return _Resultado(filas=[self.tarea] if self.tarea else [])
        if s.startswith("INSERT Sistema.TareaEjecucion"):
            return _Resultado(41)
        return _Resultado()

    def commit(self):
        pass

    def rollback(self):
        pass

    def in_transaction(self):
        return False

    def connect(self):
        return self

    def terminada(self):
        return next(
            p for s, p in self.sql if s.startswith("UPDATE Sistema.TareaEjecucion")
        )

    def solto(self):
        return any("sp_releaseapplock" in s for s, _ in self.sql)


@pytest.fixture
def conexion(monkeypatch):
    conn = _Conexion(tarea={"Estado": "A", "PermiteManual": True})
    monkeypatch.setattr(ejecutor, "get_engine", lambda base: conn)
    return conn


def test_registra_resultado_y_suelta_el_bloqueo(conexion):
    assert ejecutor.ejecutar(Tarea("X", lambda: Conteo(5, 2))) == Conteo(5, 2)
    fin = conexion.terminada()
    assert (fin["resultado"], fin["procesados"], fin["modificados"], fin["error"]) == (
        "Exitoso",
        5,
        2,
        None,
    )
    assert conexion.solto()


def test_errores_parciales_y_fallos_quedan_registrados(conexion):
    ejecutor.ejecutar(Tarea("X", lambda: Conteo(3, 1, errores=1)))
    assert conexion.terminada()["resultado"] == "Parcial"

    def falla() -> Conteo:
        raise ValueError("x")

    conexion.sql.clear()
    with pytest.raises(ValueError):
        ejecutor.ejecutar(Tarea("X", falla))
    assert (
        conexion.terminada()["resultado"] == "Fallido"
        and conexion.terminada()["error"] == "TAREA_ERROR"
    )
    assert conexion.solto()


def test_otra_instancia_en_curso_no_ejecuta(conexion):  # M8 AC 15
    conexion.bloqueo = -1
    llamadas = []
    with pytest.raises(TareaEnCurso):
        ejecutor.ejecutar(Tarea("X", lambda: llamadas.append(1) or Conteo()))
    assert not llamadas and not any("INSERT" in s for s, _ in conexion.sql)


def test_manual_exige_motivo_y_permiso(conexion):  # M8 AC 4
    with pytest.raises(TareaRechazada):
        ejecutor.ejecutar(Tarea("X", Conteo), por="user_1", motivo="  ")
    conexion.tarea = {"Estado": "A", "PermiteManual": False}
    with pytest.raises(TareaRechazada):
        ejecutor.ejecutar(Tarea("X", Conteo), por="user_1", motivo="reproceso")
    assert conexion.solto()
    conexion.tarea = {"Estado": "A", "PermiteManual": True}
    ejecutor.ejecutar(Tarea("X", Conteo), por="user_1", motivo="reproceso")
    inicio = next(
        p for s, p in conexion.sql if s.startswith("INSERT Sistema.TareaEjecucion")
    )
    assert inicio == {"codigo": "X", "por": "user_1", "motivo": "reproceso"}


def test_tarea_deshabilitada_no_corre(conexion):
    conexion.tarea = {"Estado": "I", "PermiteManual": True}
    with pytest.raises(TareaRechazada):
        ejecutor.ejecutar(Tarea("X", Conteo))


def test_vigilante_alerta_tareas_atrasadas(monkeypatch, eventos_auditados, caplog):
    monkeypatch.setattr(
        vigilante,
        "tareas_atrasadas",
        lambda: [("ATM06_RECUPERACION", 10, 42), ("SIS_X", 5, None)],
    )
    assert vigilante.vigilar().procesados == 2
    assert [e.accion for e in eventos_auditados] == ["SIS_TAREA_SIN_EJECUTAR"] * 2
    assert "TAREA_SIN_EJECUTAR codigo=ATM06_RECUPERACION" in caplog.text


def test_vigilante_filtra_por_ventana(monkeypatch):
    conn = _Conexion()
    conn.execute = lambda sql, params=None: _Resultado(
        filas=[("A", 10, 3), ("B", 10, 11), ("C", 10, None)]
    )  # type: ignore[method-assign]
    monkeypatch.setattr(vigilante, "get_engine", lambda base: conn)
    assert vigilante.tareas_atrasadas() == [("B", 10, 11), ("C", 10, None)]


def test_cada_tarea_tiene_fila_en_la_migracion():
    sql = (
        BACKEND / "migrations/seguridad/202611191200_tareas_programadas.up.sql"
    ).read_text(encoding="utf-8")
    faltan = [c for c in registro.codigos() if f"('{c}'," not in sql]
    assert not faltan


def test_cli_en_curso_sale_0_y_rechazo_sale_1(monkeypatch, capsys):
    monkeypatch.setattr(
        ejecutor, "ejecutar", lambda *a, **k: (_ for _ in ()).throw(TareaEnCurso("x"))
    )
    monkeypatch.setattr(cli, "pyodbc", type("P", (), {"pooling": True}))
    assert cli.main(["ejecutar", "SIS_VIGILANTE"]) == 0
    assert json.loads(capsys.readouterr().out)["resultado"] == "EN_CURSO"
    monkeypatch.setattr(
        ejecutor,
        "ejecutar",
        lambda *a, **k: (_ for _ in ()).throw(TareaRechazada("no")),
    )
    assert cli.main(["ejecutar", "SIS_VIGILANTE", "--por", "u", "--motivo", "m"]) == 1


@pytest.mark.parametrize(
    ("job", "codigo", "programa"),
    [
        ("atm06-recovery", "ATM06_RECUPERACION", "0 * * * * *"),
        ("sis-vigilante", "SIS_VIGILANTE", "0 */5 * * * *"),
    ],
)
def test_web_jobs_usan_el_ejecutor(job, codigo, programa):
    base = BACKEND / "App_Data/jobs/triggered" / job
    assert json.loads((base / "settings.job").read_text())["schedule"] == programa
    script = (base / "run.sh").read_bytes()
    assert script.startswith(b"#!/bin/bash\n") and b"\r\n" not in script
    assert f"-m app.core.tareas ejecutar {codigo}".encode() in script
