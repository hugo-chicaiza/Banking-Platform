from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.atm.service import autenticar_pin_ficticio_atm


@pytest.fixture
def entorno_atm():
    conn = MagicMock()
    conn_seguridad = MagicMock()
    hsm = MagicMock()
    repositorio_pan = MagicMock()

    repositorio_pan.obtener.return_value = "4111111111111111"

    tarjeta = {
        "id_tarjeta": 1,
        "estado_tarjeta": "Activa",
        "pin_asignado": True,
        "hash_numero_tarjeta": "hash_ficticio",
    }

    estado_pin = {
        "id_tarjeta": 1,
        "tiene_pin_asignado": True,
        "intentos_fallidos": 0,
        "estado_pin": "Activo",
        "pin_offset": "1234",
    }

    return {
        "conn": conn,
        "conn_seguridad": conn_seguridad,
        "hsm": hsm,
        "repositorio_pan": repositorio_pan,
        "tarjeta": tarjeta,
        "estado_pin": estado_pin,
    }


async def ejecutar_autenticacion(entorno):
    return await autenticar_pin_ficticio_atm(
        conn=entorno["conn"],
        conn_seguridad=entorno["conn_seguridad"],
        hsm=entorno["hsm"],
        repositorio_pan=entorno["repositorio_pan"],
        id_tarjeta=1,
        encrypted_pin_block=b"\x00" * 16,
        key_reference="TEST-KEY-01",
    )


@pytest.mark.asyncio
async def test_pin_correcto(entorno_atm):
    e = entorno_atm

    with (
        patch(
            "app.modules.atm.service.validar_tarjeta",
            return_value=e["tarjeta"],
        ),
        patch(
            "app.modules.atm.service.validar_hash_pan",
            return_value=True,
        ),
        patch(
            "app.modules.atm.service.get_engine",
        ) as engine,
        patch(
            "app.modules.atm.service.repository.obtener_pin_para_verificacion",
            return_value=e["estado_pin"],
        ),
        patch(
            "app.modules.atm.service.repository.guardar_resultado_pin",
            return_value={
                "intentos_fallidos": 0,
                "estado_pin": "Activo",
            },
        ) as guardar,
    ):
        engine.return_value.begin.return_value.__enter__.return_value = MagicMock()
        e["hsm"].verify_pin = AsyncMock(return_value=True)

        resultado = await ejecutar_autenticacion(e)

        assert resultado is True
        guardar.assert_called_once()
        assert guardar.call_args.kwargs["pin_correcto"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intentos,estado,codigo",
    [
        (1, "Activo", 401),
        (2, "Activo", 401),
        (3, "Bloqueado", 423),
    ],
)
async def test_intentos_fallidos(entorno_atm, intentos, estado, codigo):
    e = entorno_atm

    with (
        patch(
            "app.modules.atm.service.validar_tarjeta",
            return_value=e["tarjeta"],
        ),
        patch(
            "app.modules.atm.service.validar_hash_pan",
            return_value=True,
        ),
        patch(
            "app.modules.atm.service.get_engine",
        ) as engine,
        patch(
            "app.modules.atm.service.repository.obtener_pin_para_verificacion",
            return_value=e["estado_pin"],
        ),
        patch(
            "app.modules.atm.service.repository.guardar_resultado_pin",
            return_value={
                "intentos_fallidos": intentos,
                "estado_pin": estado,
            },
        ),
    ):
        engine.return_value.begin.return_value.__enter__.return_value = MagicMock()
        e["hsm"].verify_pin = AsyncMock(return_value=False)

        with pytest.raises(HTTPException) as error:
            await ejecutar_autenticacion(e)

        assert error.value.status_code == codigo


@pytest.mark.asyncio
async def test_pin_bloqueado_no_consulta_hsm(entorno_atm):
    e = entorno_atm
    estado_bloqueado = {
        **e["estado_pin"],
        "intentos_fallidos": 3,
        "estado_pin": "Bloqueado",
    }

    with (
        patch(
            "app.modules.atm.service.validar_tarjeta",
            return_value=e["tarjeta"],
        ),
        patch(
            "app.modules.atm.service.validar_hash_pan",
            return_value=True,
        ),
        patch(
            "app.modules.atm.service.get_engine",
        ) as engine,
        patch(
            "app.modules.atm.service.repository.obtener_pin_para_verificacion",
            return_value=estado_bloqueado,
        ),
    ):
        engine.return_value.begin.return_value.__enter__.return_value = MagicMock()
        e["hsm"].verify_pin = AsyncMock()

        with pytest.raises(HTTPException) as error:
            await ejecutar_autenticacion(e)

        assert error.value.status_code == 423
        e["hsm"].verify_pin.assert_not_awaited()
