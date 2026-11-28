import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config.settings import Settings
from app.core.security.hsm import REFERENCIA_HMAC_PAN, VERSION_HMAC_PAN, VERSION_PAN
from scripts import e612_backfill_pan
from scripts.e612_backfill_pan import (
    recalcular_por_tarjeta,
    validar_destino_local,
    verificar_backfill,
)

PAN = "5000001234567896"


def test_backfill_solo_acepta_servidores_locales_en_development():
    settings = Settings.model_construct(
        app_env="development",
        cooperativa_db_server=r"localhost\SQLEXPRESS",
        seguridad_db_server="127.0.0.1",
    )

    validar_destino_local(settings)


@pytest.mark.parametrize(
    "app_env,cooperativa,seguridad",
    [
        ("production", "localhost", "localhost"),
        ("development", "sql.example.com", "localhost"),
        ("development", "localhost", "sql.example.com"),
    ],
)
def test_backfill_rechaza_entornos_no_locales(app_env, cooperativa, seguridad):
    settings = Settings.model_construct(
        app_env=app_env,
        cooperativa_db_server=cooperativa,
        seguridad_db_server=seguridad,
    )

    with pytest.raises(RuntimeError, match="solo se permite contra SQL Server local"):
        validar_destino_local(settings)


def test_verificacion_exige_custodia_y_huella_coherentes():
    conn_coop, conn_seg, hsm = MagicMock(), MagicMock(), MagicMock()
    conn_coop.execute.return_value.mappings.return_value.all.return_value = [
        {
            "IdTarjeta": 1,
            "TokenTarjeta": "token-1",
            "HashNumeroTarjeta": b"h" * 32,
            "VersionClaveHuella": VERSION_HMAC_PAN,
            "ReferenciaClaveHuella": REFERENCIA_HMAC_PAN,
        }
    ]
    conn_seg.execute.return_value.mappings.return_value.all.return_value = [
        {
            "IdTarjeta": 1,
            "TokenTarjeta": "token-1",
            "NumeroCifrado": b"cipher",
            "ReferenciaClave": "SIM-PAN-01",
            "VersionClave": VERSION_PAN,
        }
    ]
    hsm.descifrar_pan.return_value = PAN
    hsm.huella_pan.return_value = b"h" * 32

    verificar_backfill(conn_coop, conn_seg, hsm)

    hsm.descifrar_pan.assert_called_once_with(
        b"cipher", "SIM-PAN-01", 1, version=VERSION_PAN
    )
    hsm.huella_pan.assert_called_once_with(PAN)


def test_verificacion_rechaza_tarjetas_sin_custodia_nueva():
    conn_coop, conn_seg, hsm = MagicMock(), MagicMock(), MagicMock()
    conn_coop.execute.return_value.mappings.return_value.all.return_value = [
        {
            "IdTarjeta": 1,
            "TokenTarjeta": "token-1",
            "HashNumeroTarjeta": b"h" * 32,
            "VersionClaveHuella": VERSION_HMAC_PAN,
            "ReferenciaClaveHuella": REFERENCIA_HMAC_PAN,
        }
    ]
    conn_seg.execute.return_value.mappings.return_value.all.return_value = []

    with pytest.raises(RuntimeError, match="cobertura de PAN"):
        verificar_backfill(conn_coop, conn_seg, hsm)

    hsm.descifrar_pan.assert_not_called()


def test_backfill_repetido_usa_upsert_y_conserva_origen_legacy():
    conn_coop, conn_seg, hsm = MagicMock(), MagicMock(), MagicMock()
    fila = {
        "IdTarjeta": 1,
        "NumeroCifrado": b"cipher",
        "ReferenciaClave": "SIM-PAN-01",
    }

    def ejecutar_seguridad(sql, params=None):
        sentencia = str(sql)
        if "INFORMATION_SCHEMA.TABLES" in sentencia:
            return SimpleNamespace(first=lambda: (1,))
        if "FROM Tarjetas.TarjetaNumeroCifrado" in sentencia:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=list))
        if "FROM Pruebas.PanFicticio" in sentencia:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [fila]))
        return MagicMock()

    def ejecutar_cooperativa(sql, params=None):
        if "SELECT TokenTarjeta" in str(sql):
            return SimpleNamespace(scalar_one_or_none=lambda: "tok-lab")
        return MagicMock()

    conn_seg.execute.side_effect = ejecutar_seguridad
    conn_coop.execute.side_effect = ejecutar_cooperativa
    hsm.descifrar_pan.return_value = PAN
    hsm.huella_pan.return_value = b"h" * 32

    assert recalcular_por_tarjeta(conn_coop, conn_seg, hsm, aplicar=True) == 1
    assert recalcular_por_tarjeta(conn_coop, conn_seg, hsm, aplicar=True) == 1

    merges = [
        str(call.args[0])
        for call in conn_seg.execute.call_args_list
        if "MERGE Tarjetas.TarjetaNumeroCifrado" in str(call.args[0])
    ]
    assert len(merges) == 2
    assert all("WHEN MATCHED" in sql and "WHEN NOT MATCHED" in sql for sql in merges)
    assert all(
        "DELETE" not in str(call.args[0]) for call in conn_seg.execute.call_args_list
    )


def test_backfill_incluye_tarjetas_nuevas_y_legacy_en_la_misma_ejecucion():
    conn_coop, conn_seg, hsm = MagicMock(), MagicMock(), MagicMock()
    nuevas = [
        {
            "IdTarjeta": 1,
            "NumeroCifrado": b"cipher-new",
            "ReferenciaClave": "SIM-PAN-01",
            "VersionClave": VERSION_PAN,
        }
    ]
    legacy = [
        {
            "IdTarjeta": 2,
            "NumeroCifrado": b"cipher-old",
            "ReferenciaClave": "SIM-PAN-01",
        }
    ]

    def ejecutar_seguridad(sql, params=None):
        sentencia = str(sql)
        if "INFORMATION_SCHEMA.TABLES" in sentencia:
            return SimpleNamespace(first=lambda: (1,))
        if "FROM Tarjetas.TarjetaNumeroCifrado" in sentencia:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: nuevas))
        if "FROM Pruebas.PanFicticio" in sentencia:
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: legacy))
        return MagicMock()

    conn_seg.execute.side_effect = ejecutar_seguridad
    conn_coop.execute.return_value.scalar_one_or_none.side_effect = [
        "tok-1",
        "tok-2",
    ]
    hsm.descifrar_pan.side_effect = [PAN, PAN]
    hsm.huella_pan.return_value = b"h" * 32

    assert recalcular_por_tarjeta(conn_coop, conn_seg, hsm, aplicar=False) == 2
    assert [call.kwargs["version"] for call in hsm.descifrar_pan.call_args_list] == [
        VERSION_PAN,
        VERSION_PAN,
    ]


def test_backfill_falla_si_legacy_y_nueva_custodia_no_coinciden():
    conn_coop, conn_seg, hsm = MagicMock(), MagicMock(), MagicMock()
    nueva = {
        "IdTarjeta": 1,
        "NumeroCifrado": b"cipher-new",
        "ReferenciaClave": "SIM-PAN-01",
        "VersionClave": VERSION_PAN,
    }
    legacy = {
        "IdTarjeta": 1,
        "NumeroCifrado": b"cipher-old",
        "ReferenciaClave": "SIM-PAN-01",
    }

    def ejecutar_seguridad(sql, params=None):
        sentencia = str(sql)
        if "INFORMATION_SCHEMA.TABLES" in sentencia:
            return SimpleNamespace(first=lambda: (1,))
        if "FROM Tarjetas.TarjetaNumeroCifrado" in sentencia:
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(all=lambda: [nueva])
            )
        if "FROM Pruebas.PanFicticio" in sentencia:
            return SimpleNamespace(
                mappings=lambda: SimpleNamespace(all=lambda: [legacy])
            )
        return MagicMock()

    conn_seg.execute.side_effect = ejecutar_seguridad

    with pytest.raises(RuntimeError, match="custodias legacy y nueva"):
        recalcular_por_tarjeta(conn_coop, conn_seg, hsm, aplicar=True)

    conn_coop.execute.assert_not_called()
    hsm.descifrar_pan.assert_not_called()


def test_main_no_retira_legacy_si_verificacion_falla(monkeypatch):
    settings = Settings.model_construct(
        app_env="development",
        cooperativa_db_server="localhost",
        seguridad_db_server="127.0.0.1",
    )
    conn_coop, conn_seg = MagicMock(), MagicMock()
    monkeypatch.setattr(
        sys,
        "argv",
        ["e612_backfill_pan.py", "--apply", "--confirmar-local", "--retirar-pruebas"],
    )
    monkeypatch.setattr(e612_backfill_pan, "get_settings", lambda: settings)
    monkeypatch.setattr(e612_backfill_pan, "obtener_hsm", MagicMock())
    monkeypatch.setattr(
        e612_backfill_pan,
        "get_engine",
        lambda nombre: SimpleNamespace(
            connect=lambda: nullcontext(
                conn_coop if nombre == "cooperativa" else conn_seg
            )
        ),
    )
    monkeypatch.setattr(e612_backfill_pan, "recalcular_por_tarjeta", lambda *a: 1)
    monkeypatch.setattr(
        e612_backfill_pan,
        "verificar_backfill",
        MagicMock(side_effect=RuntimeError("verificación fallida")),
    )
    retirar = MagicMock()
    monkeypatch.setattr(e612_backfill_pan, "retirar_pruebas", retirar)

    with pytest.raises(RuntimeError, match="verificación fallida"):
        e612_backfill_pan.main()

    conn_coop.commit.assert_called_once()
    conn_seg.commit.assert_called_once()
    retirar.assert_not_called()
