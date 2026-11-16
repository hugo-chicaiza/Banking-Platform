"""Pruebas específicas E3-01. Ejecutar con pytest."""

from datetime import date
from unittest.mock import MagicMock

from app.modules.productos import repository as repo


def test_cupo_sin_canal_rechazado():
    import pytest

    with pytest.raises(ValueError):
        repo.cupo_vigente(MagicMock(), 1, date(2026, 11, 16), "")


def test_condiciones_sin_canal_rechazado():
    import pytest

    with pytest.raises(ValueError):
        repo.condiciones_vigentes(MagicMock(), 1, date(2026, 11, 16), "")


def test_guardar_cupos_no_elimina_historia(monkeypatch):
    consultas = []

    class Resultado:
        def scalar_one(self):
            return date(2026, 11, 16)

    class Conn:
        def execute(self, stmt, params=None):
            consultas.append(str(stmt))
            return Resultado()

    monkeypatch.setattr(repo, "_rows", lambda *args, **kwargs: [])
    repo.guardar_cupos(
        Conn(),
        1,
        [
            {
                "id_canal": 1,
                "cupo_diario_maximo": 100,
                "cupo_mensual_maximo": 1000,
                "monto_max_transaccion": 50,
                "max_transacciones_dia": 10,
            }
        ],
    )
    assert any("INSERT INTO" in q for q in consultas)
    assert not any("DELETE FROM" in q for q in consultas)
