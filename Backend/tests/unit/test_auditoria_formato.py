"""E0-05 (parte A): formato nuevo de la bitácora, catálogo de eventos, saneo y alerta del relevo."""

import ast
import logging
import re
from pathlib import Path

import pytest

from app.core.config.logs import trace_id_actual
from app.core.security import audit
from app.core.security.audit import EventoAuditoria, cambios_json, texto_seguro

BACKEND = Path(__file__).resolve().parents[2]
MIGRACION = (
    BACKEND / "migrations" / "seguridad" / "202611191000_auditoria_formato.up.sql"
)
_FUNCIONES = {"auditar", "_auditar", "EventoAuditoria", "encolar"}


def _codigos_del_codigo() -> set[str]:
    """Códigos de evento escritos como texto en las llamadas de auditoría."""
    codigos: set[str] = set()
    for archivo in (BACKEND / "app").rglob("*.py"):
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            if not isinstance(nodo, ast.Call):
                continue
            nombre = getattr(nodo.func, "id", None) or getattr(nodo.func, "attr", None)
            if nombre not in _FUNCIONES:
                continue
            candidatos = (
                [nodo.args[1]]
                if nombre == "encolar" and len(nodo.args) > 1
                else nodo.args[:1]
            )
            candidatos += [
                k.value for k in nodo.keywords if k.arg in ("accion", "codigo")
            ]
            codigos |= {
                c.value
                for c in candidatos
                if isinstance(c, ast.Constant)
                and isinstance(c.value, str)
                and c.value.isupper()
            }
        # Ventanilla: REGISTRAR_<CODIGO> por cada tipo de TipoVentanilla (Literal)
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            if (
                isinstance(nodo, ast.Assign)
                and getattr(nodo.targets[0], "id", "") == "TipoVentanilla"
                and isinstance(nodo.value, ast.Subscript)
            ):
                valores = nodo.value.slice
                elementos = (
                    valores.elts if isinstance(valores, ast.Tuple) else [valores]
                )
                codigos |= {
                    f"REGISTRAR_{e.value.upper()}"
                    for e in elementos
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)
                }
        # Tablas de códigos explícitas (`_EVENTO_* = {...: "CODIGO"}`)
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            if isinstance(nodo, (ast.Assign, ast.AnnAssign)) and isinstance(
                nodo.value, ast.Dict
            ):
                destinos = (
                    nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
                )
                if any(getattr(d, "id", "").startswith("_EVENTO_") for d in destinos):
                    codigos |= {
                        v.value
                        for v in nodo.value.values
                        if isinstance(v, ast.Constant) and isinstance(v.value, str)
                    }
    return codigos


def _codigos_del_catalogo() -> set[str]:
    """Códigos sembrados en Auditoria.TipoEvento por todas las migraciones de SeguridadDB."""
    patron = r"\('([A-Z0-9_]+)', '[a-z]+', '(?:Informativo|Sensible|Seguridad)'"
    return {
        codigo
        for archivo in MIGRACION.parent.glob("*.up.sql")
        for codigo in re.findall(patron, archivo.read_text(encoding="utf-8"))
    }


def test_cada_evento_del_codigo_esta_en_el_catalogo():
    # Un evento nuevo se agrega al catálogo (migración) en el mismo pull request
    faltan = sorted(_codigos_del_codigo() - _codigos_del_catalogo())
    assert not faltan, f"eventos sin catálogo Auditoria.TipoEvento: {faltan}"


def test_la_migracion_no_actualiza_la_bitacora_y_la_protege():
    sql = MIGRACION.read_text(encoding="utf-8")
    assert not re.search(
        r"(?i)UPDATE\s+Auditoria\.Auditoria", sql
    )  # el disparador de E0-08 lo impediría
    assert "AFTER UPDATE, DELETE" in sql and "THROW 57201" in sql
    assert "DEFAULT (1) WITH VALUES" in sql  # filas viejas marcadas sin UPDATE


def test_texto_libre_no_puede_falsificar_registros():  # ASVS 16.4.1
    limpio = texto_seguro(
        "ok\nAuditoriaID=1 LOGIN Exitoso\r\x00 tarjeta 4111111111111111"
    )
    assert "\n" not in limpio and "\r" not in limpio and "\x00" not in limpio
    assert "\\x0a" in limpio and "[PAN ****1111]" in limpio


def test_cambios_sin_datos_sensibles():
    cambios = {
        "antes": {"estado": "A", "pinOffset": "1234"},
        "despues": {"Token": "abc", "compania": "Andina"},
    }
    texto = cambios_json(cambios)
    assert texto is not None
    assert "1234" not in texto and "abc" not in texto and "[filtrado]" in texto
    assert "Andina" in texto  # «compania» no es «pan»
    assert cambios_json(None) is None


class _Conexion:
    def __init__(self) -> None:
        self.sql = ""
        self.params: dict = {}

    def execute(self, sql, params):
        self.sql, self.params = str(sql), params


def test_el_escritor_llena_el_formato_nuevo():
    conn = _Conexion()
    token = trace_id_actual.set("traza-123")
    try:
        audit._insertar(
            conn,  # type: ignore[arg-type]
            EventoAuditoria(
                accion="CAMBIAR_ROL",
                tabla="Organizacion.Usuarios",
                id_registro="7",
                resultado="Exitoso",
                usuario=None,
                ip="10.0.0.1",
                descripcion="rol=ADMIN\nfalso",
                agencia="001",
                sesion="session_abc",
                cambios={"antes": {"rol": "CAJERO"}, "despues": {"rol": "ADMIN"}},
            ),
        )
    finally:
        trace_id_actual.reset(token)
    assert (
        "IdEvento" in conn.sql
        and "SYSUTCDATETIME()" in conn.sql
        and "NEWID()" in conn.sql
    )
    p = conn.params
    assert (
        p["correlacion"] == "traza-123"
        and p["agencia"] == "001"
        and p["sesion"] == "session_abc"
    )
    assert p["canal"] == "API" and "\n" not in p["descripcion"]
    assert '"ADMIN"' in p["cambios"]


def test_agencia_invalida_no_se_guarda():
    conn = _Conexion()
    audit._insertar(
        conn,  # type: ignore[arg-type]
        EventoAuditoria(
            "LOGIN", None, None, "Exitoso", None, None, "x", agencia="agencia-larga"
        ),
    )
    assert conn.params["agencia"] is None


@pytest.mark.parametrize(("edad", "alerta"), [(25, True), (3, False)])
def test_alerta_del_relevo_por_edad(monkeypatch, caplog, edad, alerta):
    from app.modules.aprobaciones import relevo

    monkeypatch.setattr(relevo, "edad_pendiente_minutos", lambda origen: edad)
    with caplog.at_level(logging.ERROR, logger=relevo.__name__):
        assert relevo.alertar_pendientes(object()) == [edad]  # type: ignore[arg-type]
    assert ("AUD_RELEVO_ALERTA" in caplog.text) is alerta


def test_la_alerta_del_relevo_queda_en_la_bitacora(monkeypatch, eventos_auditados):
    from app.modules.aprobaciones import relevo

    monkeypatch.setattr(relevo, "edad_pendiente_minutos", lambda origen: 30)
    relevo.alertar_pendientes(object())  # type: ignore[arg-type]
    assert [e.accion for e in eventos_auditados] == ["AUD_RELEVO_ALERTA"]
    assert eventos_auditados[0].canal == "SISTEMA"


def test_la_ventanilla_declara_sus_eventos():
    assert {"REGISTRAR_DEPOSITO", "REGISTRAR_RETIRO"} <= _codigos_del_codigo()
