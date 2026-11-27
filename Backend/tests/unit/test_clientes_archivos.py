import asyncio
from contextlib import contextmanager
from dataclasses import replace
from typing import cast
from unittest.mock import Mock

import pytest
from fastapi import Depends, FastAPI, HTTPException, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.core.documentos import ArchivoRechazado, Documento, Referencia, clamav
from app.core.security.audit import AccesoDenegadoMiddleware
from app.core.security.auth import Usuario, require_auth, usuario_actual
from app.modules.clientes import archivos, archivos_huerfanos
from app.modules.seguridad import funciones


def _peticion(*fragmentos: bytes) -> Request:
    partes = iter(fragmentos)

    async def recibir():
        datos = next(partes, None)
        return {
            "type": "http.request",
            "body": datos or b"",
            "more_body": datos is not None,
        }

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/clientes/1/archivos",
            "headers": [(b"content-type", b"multipart/form-data; boundary=demo")],
            "client": ("127.0.0.1", 10001),
        },
        recibir,
    )


def _cuerpo(datos: bytes) -> bytes:
    return (
        b'--demo\r\nContent-Disposition: form-data; name="claseDocumento"\r\n\r\nOTRO\r\n'
        b'--demo\r\nContent-Disposition: form-data; name="archivo"; filename="evidencia.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n" + datos + b"\r\n--demo--\r\n"
    )


def test_multipart_acepta_el_limite_exacto_y_mantiene_el_nombre():
    cuerpo = _cuerpo(b"x" * archivos.MAX_BYTES)
    carga = asyncio.run(
        archivos.recibir_archivo(_peticion(cuerpo[:80], cuerpo[80:]), Mock())
    )
    assert carga.clase == "OTRO"
    assert carga.nombre == "evidencia.pdf"
    assert len(carga.contenido) == archivos.MAX_BYTES


@pytest.mark.parametrize("tamano", [archivos.MAX_BYTES + 1, 6 * 1024 * 1024])
def test_multipart_rechaza_archivo_grande_sin_content_length(tamano):
    cuerpo = _cuerpo(b"x" * tamano)
    with pytest.raises(HTTPException) as error:
        asyncio.run(
            archivos.recibir_archivo(_peticion(cuerpo[:256], cuerpo[256:]), Mock())
        )
    assert error.value.status_code == 413


def test_multipart_truncado_no_acepta_un_formulario_parcial():
    cuerpo = _cuerpo(b"archivo de prueba")[:-10]
    with pytest.raises(HTTPException) as error:
        asyncio.run(archivos.recibir_archivo(_peticion(cuerpo), Mock()))
    assert error.value.status_code == 422


@pytest.mark.parametrize(
    ("fragmentos", "espera"),
    [
        ([b"stream: ", b"OK\0"], None),
        ([b"stream: Test.Signature FOUND\0"], ArchivoRechazado),
        ([b"stream: OK"], clamav.AnalisisNoDisponible),
        ([b"stream: error ERROR\0"], clamav.AnalisisNoDisponible),
    ],
)
def test_clamav_exige_veredicto_completo(monkeypatch, fragmentos, espera):
    canal = Mock()
    canal.recv.side_effect = [*fragmentos, b""]
    canal.__enter__ = Mock(return_value=canal)
    canal.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(clamav.socket, "create_connection", Mock(return_value=canal))
    monkeypatch.setattr(
        clamav,
        "get_settings",
        lambda: Mock(documentos_clamav_host="localhost", documentos_clamav_port=3310),
    )
    datos = b"test"
    if espera is None:
        clamav.analizar_clamav(datos)
    else:
        with pytest.raises(espera):
            clamav.analizar_clamav(datos)
    assert [item.args[0] for item in canal.sendall.call_args_list] == [
        b"zINSTREAM\0\0\0\0\x04",
        datos,
        b"\0\0\0\0",
    ]


def test_contenido_no_se_entrega_si_falla_auditoria(monkeypatch):
    usuario = cast(Usuario, Mock())
    conn = cast(Connection, Mock())
    monkeypatch.setattr(archivos, "_cliente", Mock())
    monkeypatch.setattr(
        archivos,
        "_archivo",
        Mock(
            return_value={
                "estadoAnalisis": "Limpio",
                "clave": "objeto",
                "tipoContenido": "image/png",
                "nombreOriginal": "evidencia.png",
            }
        ),
    )
    almacen = Mock()
    almacen.leer.return_value.tipo_contenido = "image/png"
    monkeypatch.setattr(archivos, "obtener_servicio", lambda: almacen)

    @contextmanager
    def no_persiste():
        raise SQLAlchemyError("fallo simulado")
        yield

    monkeypatch.setattr(archivos, "get_engine", lambda _: Mock(begin=no_persiste))
    responder = Mock()
    monkeypatch.setattr(archivos, "respuesta_documento", responder)
    with pytest.raises(HTTPException) as error:
        archivos.contenido(42, 1, conn, usuario, _peticion())
    assert error.value.status_code == 503
    responder.assert_not_called()


def test_acceso_directo_a_archivo_exige_permiso_y_audita_ambos_resultados(
    monkeypatch, eventos_auditados
):
    app = FastAPI()
    app.add_middleware(AccesoDenegadoMiddleware)
    app.include_router(
        archivos.router, prefix="/api/v1/clientes", dependencies=[Depends(require_auth)]
    )
    monkeypatch.setattr(funciones, "activa", lambda: False)
    monkeypatch.setattr(
        "app.core.security.secciones.verificar_seccion", lambda *_: None
    )
    usuario = Usuario(
        id_usuario="user_local",
        id_sesion="sesion_local",
        id_organizacion=None,
        nombre="Asesora",
        email="asesora@example.invalid",
        roles=("ASESOR",),
        permisos=(),
        id_interno=7,
    )

    async def identidad(request: Request):
        request.state.usuario = usuario
        return usuario

    async def sql_falso():
        return Mock()

    app.dependency_overrides[usuario_actual] = identidad
    app.dependency_overrides[archivos.cooperativa] = sql_falso
    verificar = Mock()
    monkeypatch.setattr(archivos, "_cliente", verificar)
    monkeypatch.setattr(
        archivos,
        "_archivo",
        lambda *_: {
            "estadoAnalisis": "Limpio",
            "clave": "opaca",
            "tipoContenido": "image/png",
            "nombreOriginal": "respaldo.png",
        },
    )
    almacen = Mock()
    almacen.leer.return_value = Documento(b"contenido", "image/png")
    monkeypatch.setattr(archivos, "obtener_servicio", lambda: almacen)

    @contextmanager
    def transaccion():
        yield Mock()

    monkeypatch.setattr(archivos, "get_engine", lambda _: Mock(begin=transaccion))
    monkeypatch.setattr(
        archivos.audit,
        "registrar_en_transaccion",
        lambda _, evento: eventos_auditados.append(evento),
    )

    async def probar():
        nonlocal usuario
        ruta = "/api/v1/clientes/42/archivos/9/contenido"
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as cliente:
            denegado = await cliente.get(ruta)
            assert denegado.status_code == 403
            verificar.assert_not_called()
            almacen.leer.assert_not_called()
            assert eventos_auditados[-1].accion == "ACCESO_DENEGADO"
            assert eventos_auditados[-1].usuario == 7
            usuario = replace(usuario, permisos=("cli-archivo-ver",))
            permitido = await cliente.get(ruta)

        assert permitido.status_code == 200
        assert permitido.content == b"contenido"
        assert (
            permitido.headers["content-disposition"]
            == 'attachment; filename="respaldo.png"'
        )
        evento = eventos_auditados[-1]
        assert (evento.accion, evento.usuario, evento.id_registro) == (
            "CLI_ARCHIVO_VISTO",
            7,
            "9",
        )
        assert evento.cambios == {"idCliente": 42, "idArchivo": 9}

    asyncio.run(probar())


def test_reemplazo_desactualizado_compensa_el_archivo_nuevo(monkeypatch):
    conn = Mock()
    usuario = Mock()
    almacen = Mock()
    almacen.guardar.return_value = Referencia(
        "nuevo", "aa" * 32, 7, "image/png", "Limpio"
    )
    conn.execute.return_value.scalar_one_or_none.return_value = "OTRO"
    monkeypatch.setattr(archivos, "_cliente", Mock())
    monkeypatch.setattr(archivos, "_limite", lambda _: archivos.MAX_BYTES)
    monkeypatch.setattr(
        archivos,
        "_archivo",
        lambda *_: {
            "idArchivo": 5,
            "claseDocumento": "OTRO",
            "version": 1,
            "reemplazado": True,
        },
    )
    monkeypatch.setattr(archivos, "obtener_servicio", lambda: almacen)
    carga = archivos.CargaArchivo(
        clase="OTRO", nombre="adjunto.png", contenido=b"adjunto", reemplaza=5
    )

    with pytest.raises(HTTPException) as error:
        archivos.subir(42, conn, usuario, _peticion(), carga)

    assert error.value.status_code == 409
    assert conn.execute.call_count == 1
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    almacen.eliminar.assert_called_once_with("nuevo")


def test_limpieza_conserva_objetos_con_metadatos_historicos(monkeypatch):
    mongo = Mock()
    cursor = Mock()
    cursor.__enter__ = Mock(return_value=cursor)
    cursor.__exit__ = Mock(return_value=False)
    cursor.to_list.side_effect = [[{"_id": "historico"}, {"_id": "huerfano"}], []]
    mongo.find.return_value.batch_size.return_value = cursor
    mongo.delete_many.return_value.deleted_count = 1
    conn = Mock()
    conn.execute.return_value.scalars.return_value = ["historico"]

    @contextmanager
    def conexion():
        yield conn

    monkeypatch.setattr(archivos_huerfanos, "coleccion", lambda _: mongo)
    monkeypatch.setattr(
        archivos_huerfanos, "get_engine", lambda _: Mock(connect=conexion)
    )
    conteo = archivos_huerfanos.ejecutar()

    assert (conteo.procesados, conteo.modificados) == (2, 1)
    filtro = mongo.delete_many.call_args.args[0]
    assert filtro["origen"] == archivos.ORIGEN
    assert filtro["_id"] == {"$in": ["huerfano"]}
