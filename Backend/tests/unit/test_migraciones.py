"""E0-01: ejecutor de migraciones con bitácora (apagado por defecto)."""

import hashlib
import importlib.util
from pathlib import Path

import pytest

from app.core.config.settings import Settings
from app.core.migraciones.archivos import ArchivoInvalido, Migracion, descubrir, lotes
from app.core.migraciones.ejecutor import Ejecutor, MigracionRechazada

MIGRACIONES = Path(__file__).resolve().parents[2] / "migrations"


class _Sql:
    """Base simulada: bitácora en memoria; un lote con 'FALLA' lanza error."""

    def __init__(
        self, *, base="CooperativaDB", login="admin_migraciones", bitacora=None
    ):
        self.base, self.login = base, login
        self.bitacora: dict[str, bytes] | None = bitacora
        self.pendiente: list[tuple] = []
        self.lotes: list[str] = []
        self.contexto: str | None = None

    def valor(self, sql, **p):
        if "DB_NAME" in sql:
            return self.base
        if "ORIGINAL_LOGIN" in sql:
            return self.login
        if "OBJECT_ID('Migracion.Bitacora'" in sql:
            return 1 if self.bitacora is not None else None
        raise AssertionError(sql)

    def filas(self, sql, **p):
        return list((self.bitacora or {}).items())

    def ejecutar(self, sql, **p):
        if "CREATE TABLE Migracion.Bitacora" in sql:
            self.bitacora = {}
        elif "sp_set_session_context" in sql:
            self.contexto = p["base"]
        elif sql.startswith("INSERT INTO Migracion.Bitacora"):
            self.pendiente.append((p["archivo"], p["suma"], p["base"]))
        elif "DENY" in sql:
            pass
        else:
            if "FALLA" in sql:
                raise RuntimeError("error de SQL")
            self.lotes.append(sql)

    def confirmar(self):
        for archivo, suma, _ in self.pendiente:
            assert self.bitacora is not None
            self.bitacora[archivo] = suma
        self.pendiente.clear()

    def revertir(self):
        self.pendiente.clear()


def _m(archivo: str, contenido: str) -> Migracion:
    return Migracion(archivo, hashlib.sha256(contenido.encode()).digest(), contenido)


def _ejecutor(
    sql: _Sql, migraciones: list[Migracion], habilitado=True, login_app="app_user"
) -> Ejecutor:
    return Ejecutor(
        sql,
        base="cooperativa",
        nombre_base="CooperativaDB",
        login_aplicacion=login_app,
        migraciones=migraciones,
        habilitado=habilitado,
    )


UNO = _m(
    "202611190000_prueba_uno.up.sql",
    "CREATE TABLE A (x int);\nGO\nCREATE TABLE B (y int);",
)
DOS = _m("202611190001_prueba_dos.up.sql", "ALTER TABLE A ADD z int;")


def test_aplica_en_orden_con_bitacora_y_contexto():
    sql = _Sql()
    assert _ejecutor(sql, [UNO, DOS]).aplicar() == [UNO.archivo, DOS.archivo]
    assert sql.lotes == [
        "CREATE TABLE A (x int);",
        "CREATE TABLE B (y int);",
        "ALTER TABLE A ADD z int;",
    ]
    assert sql.bitacora == {UNO.archivo: UNO.sha256, DOS.archivo: DOS.sha256}
    assert (
        sql.contexto == "CooperativaDB"
    )  # las migraciones lo exigen antes de tocar nada


def test_segunda_ejecucion_sin_archivos_nuevos_no_cambia_nada():  # criterio 3
    sql = _Sql()
    _ejecutor(sql, [UNO]).aplicar()
    sql.lotes.clear()
    assert _ejecutor(sql, [UNO]).aplicar() == []
    assert sql.lotes == []


def test_archivo_alterado_detiene_todo_antes_de_aplicar():  # criterio 2
    sql = _Sql(bitacora={UNO.archivo: b"\x00" * 32})
    with pytest.raises(MigracionRechazada, match=UNO.archivo):
        _ejecutor(sql, [UNO, DOS]).aplicar()
    assert sql.lotes == []  # ni siquiera la pendiente DOS
    assert _ejecutor(sql, [UNO, DOS]).estado().alteradas == [UNO.archivo]


def test_migracion_que_falla_no_queda_registrada():  # criterio 4
    sql = _Sql()
    mala = _m("202611190002_prueba_mala.up.sql", "SELECT 1;\nGO\nFALLA")
    with pytest.raises(RuntimeError):
        _ejecutor(sql, [UNO, mala, DOS]).aplicar()
    assert sql.bitacora == {
        UNO.archivo: UNO.sha256
    }  # DOS no se intentó; la mala no quedó


def test_se_niega_con_el_login_de_la_aplicacion():  # criterio 5
    sql = _Sql(login="App_User")
    with pytest.raises(MigracionRechazada, match="login de la aplicación"):
        _ejecutor(sql, [UNO]).aplicar()
    with pytest.raises(MigracionRechazada):
        _ejecutor(sql, [UNO]).estado()


def test_apagado_no_aplica_pero_permite_ver_el_estado():
    sql = _Sql()
    with pytest.raises(MigracionRechazada, match="apagado"):
        _ejecutor(sql, [UNO], habilitado=False).aplicar()
    estado = _ejecutor(sql, [UNO], habilitado=False).estado()
    assert estado.pendientes == [UNO.archivo] and not estado.bitacora_instalada
    assert sql.lotes == []


def test_base_equivocada_se_rechaza():
    with pytest.raises(MigracionRechazada, match="SeguridadDB"):
        _ejecutor(_Sql(base="SeguridadDB"), [UNO]).aplicar()


def test_linea_base_se_marca_sin_ejecutar_en_la_base_compartida():
    base = _m("000000000000_linea_base.up.sql", "CREATE TABLE Todo (x int);")
    sql = _Sql()
    _ejecutor(sql, [base, UNO]).aplicar(marcar_linea_base=True)
    assert "CREATE TABLE Todo (x int);" not in sql.lotes
    assert base.archivo in (sql.bitacora or {})


def test_el_flag_viene_apagado_por_defecto():
    assert Settings.model_fields["migraciones_habilitadas"].default is False


def test_descubrir_valida_nombres_orden_y_sellos(tmp_path):
    (tmp_path / "202611190001_b_dos.up.sql").write_text("SELECT 2;")
    (tmp_path / "202611190000_a_uno.up.sql").write_text("SELECT 1;")
    (tmp_path / "202611190000_a_uno.down.sql").write_text("-- reversión")
    assert [m.archivo for m in descubrir(tmp_path)] == [
        "202611190000_a_uno.up.sql",
        "202611190001_b_dos.up.sql",
    ]
    (tmp_path / "202611190001_c_repetido.up.sql").write_text("SELECT 3;")
    with pytest.raises(ArchivoInvalido, match="repetidos"):
        descubrir(tmp_path)
    (tmp_path / "202611190001_c_repetido.up.sql").unlink()
    (tmp_path / "cambio_suelto.sql").write_text("SELECT 4;")
    with pytest.raises(ArchivoInvalido, match="cambio_suelto.sql"):
        descubrir(tmp_path)


@pytest.mark.parametrize("base", ["cooperativa", "seguridad"])
def test_las_carpetas_del_repositorio_cumplen_la_convencion(base):
    assert descubrir(MIGRACIONES / base)


def test_lotes_parte_por_go():
    assert lotes("A;\nGO\n  go ;\nB;\nGO") == ["A;", "B;"]
    assert lotes("SELECT 'GO';") == ["SELECT 'GO';"]  # GO dentro de un texto no separa


def test_generador_de_linea_base_tipos_y_literales():
    ruta = Path(__file__).resolve().parents[2] / "scripts" / "generar_linea_base.py"
    spec = importlib.util.spec_from_file_location("generar_linea_base", ruta)
    assert spec and spec.loader
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    assert modulo._tipo("nvarchar", 100, 0, 0) == "nvarchar(50)"
    assert modulo._tipo("varchar", -1, 0, 0) == "varchar(max)"
    assert modulo._tipo("decimal", 9, 18, 2) == "decimal(18,2)"
    assert modulo._literal("O'Brien") == "N'O''Brien'"
    assert modulo._literal(None) == "NULL" and modulo._literal(b"\x01\xff") == "0x01ff"
