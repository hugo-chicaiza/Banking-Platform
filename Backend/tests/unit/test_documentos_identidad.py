from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.modules.clientes import documentos_identidad
from app.modules.clientes.schemas import ConsultaDocumentoBody

HOY = date(2026, 11, 26)


def _conexion(algoritmo, patron, minimo, maximo, requiere_pais=False):
    conn = MagicMock()
    conn.execute.return_value.mappings.return_value.first.return_value = {
        "Algoritmo": algoritmo,
        "PatronCaracteres": patron,
        "LongitudMinima": minimo,
        "LongitudMaxima": maximo,
        "RequierePais": requiere_pais,
        "RequiereVencimiento": requiere_pais,
    }
    return conn


def _ficha(**cambios):
    return {
        "id_cliente": 42,
        "estado_cliente": "Activo",
        "tipo_cliente": "Natural",
        "estado_documento": "REGISTRADO",
        "emisor": None,
        "vencimiento": None,
        **cambios,
    }


def test_cedula_invalida_no_busca_clientes(monkeypatch):
    conn = _conexion("EC_CEDULA", "DIGITOS", 10, 10)
    buscar = MagicMock()
    monkeypatch.setattr(documentos_identidad, "_buscar", buscar)
    body = ConsultaDocumentoBody(tipo_documento="CED", numero="1712345678")

    with pytest.raises(HTTPException) as error:
        documentos_identidad.consultar(conn, body, HOY)

    assert error.value.detail["code"] == "DOCUMENTO_INVALIDO"
    buscar.assert_not_called()


def test_ruc_encuentra_cedula_sin_heredar_estado(monkeypatch):
    conn = _conexion("EC_RUC", "DIGITOS", 13, 13)
    cedula = "1712345675"
    buscar = MagicMock(side_effect=[None, _ficha()])
    monkeypatch.setattr(documentos_identidad, "_buscar", buscar)
    body = ConsultaDocumentoBody(tipo_documento="RUC", numero=cedula + "001")

    resultado = documentos_identidad.consultar(conn, body, HOY)

    assert resultado.id_cliente == 42
    assert resultado.tipo_coincidencia == "EQUIVALENCIA"
    assert resultado.estado_documento is None
    buscar.assert_called_with(conn, "CED", cedula, None)


@pytest.mark.parametrize(
    ("vencimiento", "estado"),
    [(date(2026, 11, 25), "VENCIDO"), (HOY, "VIGENTE"), (None, "POR_COMPLETAR")],
)
def test_pasaporte_consulta_emisor_y_vigencia(monkeypatch, vencimiento, estado):
    conn = _conexion("NINGUNO", "ALFANUMERICO", 5, 20, requiere_pais=True)
    monkeypatch.setattr(documentos_identidad.repository, "existe_pais", lambda *_: True)
    buscar = MagicMock(return_value=_ficha(emisor="COL", vencimiento=vencimiento))
    monkeypatch.setattr(documentos_identidad, "_buscar", buscar)
    body = ConsultaDocumentoBody(
        tipo_documento="PAS", numero="ab012345", codigo_pais_emision="COL"
    )

    resultado = documentos_identidad.consultar(conn, body, HOY)

    buscar.assert_called_once_with(conn, "PAS", "AB012345", "COL")
    assert resultado.id_cliente == 42
    assert resultado.tipo_coincidencia == "EXACTA"
    assert resultado.estado_documento == estado


def test_pasaporte_heredado_sin_emisor_no_confirma_titular(monkeypatch):
    conn = _conexion("NINGUNO", "ALFANUMERICO", 5, 20, requiere_pais=True)
    monkeypatch.setattr(documentos_identidad.repository, "existe_pais", lambda *_: True)
    monkeypatch.setattr(documentos_identidad, "_buscar", lambda *_: _ficha())
    body = ConsultaDocumentoBody(
        tipo_documento="PAS", numero="AB012345", codigo_pais_emision="COL"
    )

    resultado = documentos_identidad.consultar(conn, body, HOY)

    assert resultado.existe
    assert resultado.id_cliente is None
    assert resultado.estado_documento == "POR_COMPLETAR"


def test_alta_documento_y_direccion_en_misma_transaccion(monkeypatch):
    from app.modules.clientes import service
    from app.modules.clientes.schemas import ClienteCreate

    conn = MagicMock()
    payload = ClienteCreate.model_construct(
        tipo_documento="C",
        tipo_cliente="Natural",
        identificacion="1712345675",
        fecha_emision=None,
        fecha_vencimiento=None,
    )
    body = ConsultaDocumentoBody(tipo_documento="CED", numero=payload.identificacion)
    monkeypatch.setattr(service, "_validar_datos_alta", lambda *_, **__: None)
    monkeypatch.setattr(service, "_validar_persona_y_catalogos", lambda *_: None)
    monkeypatch.setattr(documentos_identidad, "preparar_alta", lambda *_: body)
    monkeypatch.setattr(
        service.repository, "crear_cliente", lambda *_, **__: {"id_cliente": 42}
    )
    monkeypatch.setattr(service, "Cliente", lambda **datos: datos)
    escritura = MagicMock(
        side_effect=RuntimeError("fallo simulado al guardar el documento")
    )
    monkeypatch.setattr(documentos_identidad, "insertar", escritura)

    with pytest.raises(RuntimeError):
        service.registrar_cliente(conn, payload, 1, "127.0.0.1")

    escritura.assert_called_once_with(conn, 42, body, None, None, principal=True)
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()


@pytest.mark.parametrize(
    "tipo_activo,vencimiento", [(False, HOY), (True, date(2026, 11, 25))]
)
def test_revisar_principal_usa_reglas_y_fecha_vigentes(
    monkeypatch, tipo_activo, vencimiento
):
    from app.modules.clientes import gestion_documentos
    from app.modules.clientes.schemas import DocumentoPrincipal

    conn = MagicMock()
    monkeypatch.setattr(
        gestion_documentos, "_cliente_editable", lambda *_: {"tipo_cliente": "Natural"}
    )
    monkeypatch.setattr(
        gestion_documentos,
        "_leer",
        lambda *_: {
            "version": "0000000000000001",
            "principal": False,
            "tipo_activo": tipo_activo,
            "permite_principal": True,
            "aplica_natural": True,
            "estado": "REGISTRADO",
            "fecha_vencimiento": vencimiento,
            "requiere_vencimiento": True,
            "requiere_pais": False,
        },
    )

    datos = DocumentoPrincipal(
        version="0000000000000001", motivo="Documento comprobado"
    )
    with pytest.raises(HTTPException) as error:
        gestion_documentos.aplicar_principal(
            conn, 42, 79, datos, HOY, 1, "127.0.0.1", 2
        )

    assert error.value.detail["code"] == "DOCUMENTO_NO_HABILITADO"
    conn.execute.assert_not_called()


def test_selector_enruta_consulta_y_declara_documento_solo_en_cuerpo(monkeypatch):
    from fastapi import FastAPI

    from app.modules.clientes.router import router, validar_identificacion

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    ruta = app.openapi()["paths"]["/api/v1/clientes/validaciones/documento"]["post"]
    assert "requestBody" in ruta
    assert not ruta.get("parameters")
    monkeypatch.setattr(
        documentos_identidad,
        "validar",
        lambda *_: {
            "Advertencias": [],
            "RequiereVencimiento": True,
        },
    )
    monkeypatch.setattr(
        documentos_identidad,
        "_buscar",
        lambda _, tipo, numero, emisor: (
            None
            if numero == "NOENCONTRADO"
            else _ficha(
                emisor=emisor, vencimiento=date(2000, 1, 1) if tipo == "PAS" else None
            )
        ),
    )
    conn = MagicMock()
    pasaporte = ConsultaDocumentoBody(
        tipo_documento="PAS",
        numero="AB012345",
        codigo_pais_emision="COL",
    )
    cedula = ConsultaDocumentoBody(tipo_documento="CED", numero="1712345675")
    resultado = validar_identificacion(pasaporte, conn)
    assert resultado.estado_documento == "VENCIDO"
    assert resultado.id_cliente == validar_identificacion(cedula, conn).id_cliente == 42
    ausente = validar_identificacion(
        pasaporte.model_copy(update={"numero": "NOENCONTRADO"}), conn
    )
    assert not ausente.existe
    assert ausente.id_cliente is None
