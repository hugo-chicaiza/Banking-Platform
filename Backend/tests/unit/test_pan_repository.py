import pytest

from app.modules.atm.hsm.test_pan_repository import PanFicticioRepository


def test_registrar_y_recuperar_pan(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")

    repositorio = PanFicticioRepository()
    repositorio.registrar(1, "432198765432109870")

    assert repositorio.obtener(1) == "432198765432109870"
    assert repositorio.obtener(999) is None


def test_rechazar_pan_invalido(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")

    repositorio = PanFicticioRepository()

    with pytest.raises(ValueError):
        repositorio.registrar(1, "ABC123")


def test_rechazar_uso_en_produccion(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(RuntimeError):
        PanFicticioRepository()
