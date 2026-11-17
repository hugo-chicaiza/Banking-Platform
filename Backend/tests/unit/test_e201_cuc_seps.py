import csv
from pathlib import Path

SQL = Path(__file__).resolve().parents[2] / "scripts/sql/e201"


def test_catalogo_segmento_1_seps_2025_100():
    with (SQL / "cuc_segmento_1.csv").open(encoding="utf-8", newline="") as archivo:
        filas = list(csv.DictReader(archivo))
    cuentas = {fila["CodigoCuenta"]: fila for fila in filas}
    assert len(filas) == len(cuentas) == 1183
    assert not any(codigo.startswith("3304") for codigo in cuentas)
    assert cuentas["3301"]["CodigoCuentaSuperior"] == "33"
    assert all(
        cuentas[codigo]["CodigoCuentaSuperior"] == "3301"
        for codigo in ("330105", "330110", "330115")
    )
    nueva = cuentas["740640"]
    assert nueva["CodigoCuentaSuperior"] == "7406"
    assert nueva["NombreCuenta"] == "Diferimiento extraordinario de provisiones"
    for codigo, fila in cuentas.items():
        padre = fila["CodigoCuentaSuperior"]
        assert padre == codigo[: {1: 0, 2: 1, 4: 2, 6: 4}[len(codigo)]]
        assert not padre or padre in cuentas
    delta = (SQL / "002_cuc_seps_2025_100_segmento_1.sql").read_text(encoding="utf-8")
    assert (
        f"VALUES ('{nueva['CodigoCuenta']}',N'{nueva['NombreCuenta']}',@Padre," in delta
    )
