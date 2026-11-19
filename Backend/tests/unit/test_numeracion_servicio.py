"""Unidades de reglas y permisos; la persistencia se comprueba aparte en SQL real."""

from datetime import datetime
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.aprobaciones.registro import Objetivo
from app.modules.parametros.service import hoy
from app.modules.productos import numeracion as n
from app.modules.productos import numeracion_api as api
from app.modules.productos import numeracion_aprobacion as apr
from app.modules.productos.numeracion_schemas import EjemploEntrada, ReglaEntrada


def codigo_error(error: HTTPException):
    assert isinstance(error.detail, dict)
    return cast(dict[str, object], error.detail)["code"]


def fila(**otros):
    return {
        "IdReglaNumeracion": 5,
        "IdSubProducto": 3,
        "Prefijo": "2200",
        "LongitudSecuencia": 8,
        "IncluyeAgencia": False,
        "AlgoritmoVerificador": "NINGUNO",
        "Usada": False,
        "IdReglaSecuencia": None,
        "VigenciaDesde": hoy(),
        "VigenciaHasta": None,
        "FechaCreacion": datetime(2026, 11, 19),
        "IdSolicitud": 7,
        "Estado": "A",
        "UltimoNumero": 14,
        **otros,
    }


def resultado(valor=None, filas=None):
    r = MagicMock()
    r.scalar.return_value = valor
    r.scalar_one.return_value = valor
    r.mappings.return_value = filas or []
    return r


@pytest.mark.parametrize("codigo", [-1, -2, -3, 0, 1])
def test_bloqueo_respeta_resultado_del_motor(codigo):
    c = MagicMock()
    c.execute.return_value = resultado(codigo)
    if codigo < 0:
        with pytest.raises(HTTPException) as e:
            n.bloqueo(c)
        assert codigo_error(e.value) == "NUMERACION_OCUPADA"
    else:
        n.bloqueo(c, exclusivo=True)


@pytest.mark.parametrize(
    "usada,cuentas", [(True, False), (False, True), (False, False)]
)
def test_uso_se_determina_por_marca_o_cuentas(monkeypatch, usada, cuentas):
    monkeypatch.setattr(n, "cuentas_existentes", lambda *_: cuentas)
    if usada or cuentas:
        with pytest.raises(HTTPException) as e:
            n.impedir_edicion_usada(MagicMock(), 3, [fila(Usada=usada)])
        assert e.value.status_code == 409
    else:
        n.impedir_edicion_usada(MagicMock(), 3, [fila()])


def test_version_cambia_si_cambian_las_reglas_o_aparecen_cuentas(monkeypatch):
    c = MagicMock()
    c.execute.return_value = resultado(filas=[fila()])
    assert n.reglas(c, 3)[0]["Prefijo"] == "2200"
    monkeypatch.setattr(n, "reglas", lambda *_: [fila()])
    monkeypatch.setattr(n, "cuentas_existentes", lambda *_: False)
    primera = n.version(c, 3)
    assert n.version(c, 3) == primera
    monkeypatch.setattr(n, "cuentas_existentes", lambda *_: True)
    assert n.version(c, 3) != primera
    vigente = n.vigente(c, 3)
    assert vigente is not None
    assert vigente["IdReglaNumeracion"] == 5


@pytest.mark.parametrize(
    "ultimo,existe,codigo",
    [
        (None, 1, "SECUENCIA_AGOTADA"),
        (None, None, "SECUENCIA_NO_DISPONIBLE"),
        (15, 1, None),
    ],
)
def test_generador_propaga_agotamiento_sin_hacer_commit(
    monkeypatch, ultimo, existe, codigo
):
    monkeypatch.setattr(n, "bloqueo", lambda *_: None)
    monkeypatch.setattr(n, "vigente", lambda *_: fila())
    c = MagicMock()
    c.execute.side_effect = [resultado(ultimo), resultado(existe)]
    if codigo:
        with pytest.raises(HTTPException) as e:
            n.siguiente_numero_cuenta(c, 3, "001")
        assert codigo_error(e.value) == codigo
    else:
        assert n.siguiente_numero_cuenta(c, 3, "001") == "220000000015"
    c.commit.assert_not_called()


def test_generador_exige_regla_y_contador_no_es_del_cliente(monkeypatch):
    monkeypatch.setattr(n, "bloqueo", lambda *_: None)
    monkeypatch.setattr(n, "vigente", lambda *_: None)
    with pytest.raises(HTTPException) as e:
        n.siguiente_numero_cuenta(MagicMock(), 3, "001")
    assert codigo_error(e.value) == "REGLA_NUMERACION_NO_DISPONIBLE"


def test_series_compatibles_comparten_raiz_y_rechazan_intersecciones():
    c = MagicMock()
    c.execute.return_value = resultado(filas=[fila(IdReglaSecuencia=2)])
    assert n.serie_compatible(c, ReglaEntrada(prefijo="2200")) == 2
    with pytest.raises(HTTPException) as e:
        n.serie_compatible(c, ReglaEntrada(prefijo="22", longitud_secuencia=10))
    assert codigo_error(e.value) == "FORMATO_NUMERACION_SOLAPADO"
    c.execute.return_value = resultado(filas=[fila(UltimoNumero=0)])
    assert n.serie_compatible(c, ReglaEntrada(prefijo="3300"), 3) is None
    c.execute.return_value = resultado(14)
    assert n.inicial(c, ReglaEntrada(prefijo="2200")) == 14
    assert n.cuentas_existentes(c, 3)


@pytest.mark.parametrize(
    "roles,permisos,permitido",
    [
        (("ADMIN",), {"prd-numeracion"}, True),
        (("ADMIN",), set(), False),
        (("SUPERVISOR",), {"prd-numeracion"}, False),
    ],
)
def test_permiso_efectivo_no_se_sustituye_por_rol(roles, permisos, permitido):
    usuario = MagicMock()
    actor = MagicMock(roles=roles, permisos=permisos)
    if permitido:
        assert api.proponente(usuario, actor) is usuario
    else:
        with pytest.raises(HTTPException) as e:
            api.proponente(usuario, actor)
        assert e.value.status_code == 403


@pytest.mark.parametrize("ultimo,estado", [(14, "DISPONIBLE"), (99999999, "AGOTADA")])
def test_ejemplo_no_reserva_ni_hace_commit(monkeypatch, ultimo, estado):
    monkeypatch.setattr(n, "serie_compatible", lambda *_: 5)
    c = MagicMock()
    c.execute.return_value = resultado(ultimo)
    vista = api.ejemplo(c, 3, ReglaEntrada(prefijo="2200"), "001")
    assert vista.estado_secuencia == estado
    assert vista.ejemplo == ("220000000015" if estado == "DISPONIBLE" else None)
    c.commit.assert_not_called()


def test_ejemplo_sin_agencia_inactiva_y_sin_contador(monkeypatch):
    c = MagicMock()
    c.execute.return_value = resultado(None)
    regla = ReglaEntrada(prefijo="2200", incluye_agencia=True)
    assert api.ejemplo(c, 3, regla).estado_secuencia == "SIN_AGENCIA"
    with pytest.raises(HTTPException) as e:
        api.ejemplo(c, 3, regla, "001")
    assert codigo_error(e.value) == "AGENCIA_INACTIVA"
    monkeypatch.setattr(n, "serie_compatible", lambda *_: 5)
    with pytest.raises(HTTPException) as e:
        api.ejemplo(c, 3, ReglaEntrada(prefijo="2200"), "001")
    assert codigo_error(e.value) == "SECUENCIA_NO_DISPONIBLE"
    monkeypatch.setattr(n, "serie_compatible", lambda *_: None)
    monkeypatch.setattr(n, "inicial", lambda *_: 14)
    assert (
        api.ejemplo(c, 3, ReglaEntrada(prefijo="2200"), "001").ejemplo == "220000000015"
    )


def test_vista_conserva_autoria_y_no_inventa_un_aprobador():
    assert api.vista(fila(), {7: "Persona QA(12)"}).responsable == "Persona QA(12)"
    assert api.vista(fila(IdSolicitud=None), {}).responsable == "Configuracion inicial"
    assert api.vista(fila(), {}).responsable == "Registro previo"


def test_modelo_y_previsualizacion_solo_para_cuentas(monkeypatch):
    monkeypatch.setattr(
        api, "subproducto", lambda *_, **kw: {"TipoProducto": "Credito"}
    )
    with pytest.raises(HTTPException) as e:
        api.comprobar_modelo(MagicMock(), 3)
    assert e.value.status_code == 422
    monkeypatch.setattr(api, "subproducto", lambda *_, **kw: {"TipoProducto": "Cuenta"})
    monkeypatch.setattr(api, "ejemplo", lambda *_: "ejemplo")
    assert (
        api.previsualizar(
            3,
            EjemploEntrada(regla=ReglaEntrada(prefijo="2200")),
            MagicMock(),
            MagicMock(),
        )
        == "ejemplo"
    )


def test_solicitud_delega_en_cola_con_el_objetivo_y_no_aplica(monkeypatch):
    cola = MagicMock()
    cola.solicitar.return_value = 7
    monkeypatch.setattr(api.apr, "contexto", lambda *_: "contexto")
    respuesta = api.solicitar(
        3,
        ReglaEntrada(prefijo="2200"),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        cola,
    )
    assert respuesta.id_solicitud == 7
    assert cola.solicitar.call_args.args[2] == Objetivo("SubProducto", "3", None)


def preparar_manejador(monkeypatch):
    monkeypatch.setattr(
        apr,
        "modelo",
        lambda *_: {"NombreSubProducto": "Ahorro", "NombreProducto": "Cuenta"},
    )
    monkeypatch.setattr(n, "bloqueo", lambda *_, **kw: None)
    monkeypatch.setattr(n, "reglas", lambda *_: [])
    monkeypatch.setattr(n, "impedir_edicion_usada", lambda *_: None)
    monkeypatch.setattr(n, "serie_compatible", lambda *_: None)
    monkeypatch.setattr(n, "vigente", lambda *_: None)
    monkeypatch.setattr(n, "version", lambda *_: "version")


def test_plan_congela_nombre_y_formato_y_rechaza_payload_inyectado(monkeypatch):
    preparar_manejador(monkeypatch)
    manejador = apr.ProgramadorNumeracion()
    objetivo = Objetivo("SubProducto", "3", None)
    plan = manejador.preparar(MagicMock(), objetivo, {"prefijo": "2200"}, hoy())
    assert plan.antes["formato"] == {}
    assert plan.despues["formato"]["prefijo"] == "2200"
    assert plan.version == "version"
    with pytest.raises(HTTPException) as e:
        manejador.preparar(
            MagicMock(), objetivo, {"prefijo": "2200", "usada": False}, hoy()
        )
    assert codigo_error(e.value) == "REGLA_INVALIDA"


@pytest.mark.parametrize("raiz,ultimo", [(None, 0), (2, 0), (None, 99999999)])
def test_aplicar_no_confirma_transaccion_y_no_reinicia_contador_compartido(
    monkeypatch, raiz, ultimo
):
    preparar_manejador(monkeypatch)
    monkeypatch.setattr(n, "serie_compatible", lambda *_: raiz)
    monkeypatch.setattr(n, "inicial", lambda *_: ultimo)
    seguridad = MagicMock()
    seguridad.connect.return_value.__enter__.return_value.execute.return_value.scalar_one.return_value = 12
    c = MagicMock()
    c.execute.return_value = resultado(9)
    manejador = apr.ProgramadorNumeracion(seguridad)
    args = (
        c,
        Objetivo("SubProducto", "3", None),
        {"regla": {"prefijo": "2200"}},
        "persona",
        7,
    )
    if ultimo == 99999999:
        with pytest.raises(HTTPException) as e:
            manejador.aplicar(*args)
        assert codigo_error(e.value) == "SECUENCIA_AGOTADA"
    else:
        manejador.aplicar(*args)
        assert c.execute.call_count == (3 if raiz else 4)
    c.commit.assert_not_called()


def test_operacion_reutiliza_cola_sin_aprobacion_implicita_admin():
    op = apr.operacion()
    assert op.permiso_aprobacion == "productos:aprobar"
    assert op.permiso_ejecucion == "prd-numeracion"
    assert not op.solicitud_directa
