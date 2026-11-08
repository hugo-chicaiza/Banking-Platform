"""Revocación real visible entre dos procesos spawn con motores independientes."""

import pytest

from tests.integration.atm_logout_lab import require_opt_in, run


@pytest.mark.integration
def test_atm09_revocacion_compartida_entre_procesos():
    require_opt_in("ATM09_INSTANCES_ENABLED")
    run("sequential")
