import pytest

from app.modules.atm.hsm.validation import derivar_validation_data


def test_derivar_validation_data():
    assert derivar_validation_data("432198765432109870") == "4321987654321098"


@pytest.mark.parametrize(
    "pan",
    [
        "1234",
        "ABC1234567890123",
        "12345678901234567890",
        "",
    ],
)
def test_rechazar_pan_invalido(pan):
    with pytest.raises(ValueError):
        derivar_validation_data(pan)
