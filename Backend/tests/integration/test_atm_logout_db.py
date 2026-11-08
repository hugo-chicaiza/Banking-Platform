"""Dos logout solapados, SQL real. Opt-in separado; máximo una fila por ejecución."""

import pytest

from tests.integration.atm_logout_lab import require_opt_in, run


@pytest.mark.integration
def test_atm09_logout_concurrente_sql_real():
    require_opt_in("ATM09_CONCURRENCY_ENABLED")
    run("concurrent")
