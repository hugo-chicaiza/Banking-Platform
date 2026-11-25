import json
import os
import subprocess
import sys
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from scripts import registrar_plantillas_e403 as cli
from scripts.registrar_plantillas_e403 import registrar


@pytest.fixture
def filas_validas():
    return [
        {
            "idTipoAsiento": 2,
            "borrador": {
                "codigoPlantilla": "CAJA_FALTANTE",
                "idConceptoContable": 3,
                "vigenciaDesde": "2027-01-01",
                "lineas": [
                    {
                        "lado": "DEBITO",
                        "base": "DIFERENCIA",
                        "origen": "FIJA",
                        "cuenta": 7,
                    },
                    {
                        "lado": "CREDITO",
                        "base": "DIFERENCIA",
                        "origen": "FIJA",
                        "cuenta": 8,
                    },
                ],
            },
        },
    ]


def test_manifiesto_valida_formatos_anidado_y_por_agencia(tmp_path, filas_validas):
    plano = deepcopy(filas_validas[0]["borrador"])
    plano.update(
        idTipoAsiento=4,
        codigoPlantilla="BOV_001_TRASLADO_I",
        agencia="001",
        operacion="Traslado",
        naturaleza="I",
    )
    filas_validas.append(plano)
    (tmp_path / "revisado.json").write_text(
        json.dumps(filas_validas), encoding="utf-8-sig"
    )
    assert cli.cargar_manifiesto("revisado.json", tmp_path) == filas_validas


@pytest.mark.parametrize(
    "nombre",
    [
        "../secreto.json",
        r"..\secreto.json",
        "/tmp/secreto.json",
        r"C:\tmp\secreto.json",
        r"\\servidor\docs\secreto.json",
        "sub/revisado.json",
        "sub\\revisado.json",
        "revisado.txt",
        "revisado.json:otro",
        "CON.json",
        "revisado.json\x00",
    ],
)
def test_manifiesto_rechaza_rutas_y_extensiones_ajenas(tmp_path, nombre):
    with pytest.raises(ValueError, match="solo el nombre"):
        cli.cargar_manifiesto(nombre, tmp_path)


def test_manifiesto_rechaza_ruta_absoluta_incluso_si_existe(tmp_path, filas_validas):
    ruta = tmp_path / "revisado.json"
    ruta.write_text(json.dumps(filas_validas), encoding="utf-8")
    with pytest.raises(ValueError, match="solo el nombre"):
        cli.cargar_manifiesto(str(ruta), tmp_path)


def test_manifiesto_rechaza_enlaces_externos_e_internos(tmp_path, filas_validas):
    raiz = tmp_path / "autorizado"
    raiz.mkdir()
    for destino in (tmp_path / "fuera.json", raiz / "dentro.json"):
        destino.write_text(json.dumps(filas_validas), encoding="utf-8")
        enlace = raiz / f"enlace-{destino.name}"
        try:
            enlace.symlink_to(destino)
        except OSError as error:
            pytest.skip(
                f"El entorno no permite crear enlaces simbólicos: {error.winerror if sys.platform == 'win32' else error.errno}"
            )
        with pytest.raises(ValueError, match="sin enlaces"):
            cli.cargar_manifiesto(enlace.name, raiz)


def test_manifiesto_limita_el_tamano(tmp_path):
    (tmp_path / "grande.json").write_bytes(b" " * (cli.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="1 MiB"):
        cli.cargar_manifiesto("grande.json", tmp_path)


def test_manifiesto_rechaza_directorio_autorizado_redirigido(tmp_path, filas_validas):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (fuera / "revisado.json").write_text(json.dumps(filas_validas), encoding="utf-8")
    raiz = tmp_path / "autorizado"
    if sys.platform == "win32":
        subprocess.run(
            ["cmd.exe", "/d", "/c", "mklink", "/J", str(raiz), str(fuera)],
            check=True,
            capture_output=True,
        )
    else:
        raiz.symlink_to(fuera, target_is_directory=True)
    with pytest.raises(ValueError, match="directorio local sin enlaces"):
        cli.cargar_manifiesto("revisado.json", raiz)


def test_manifiesto_rechaza_archivo_con_enlace_duro(tmp_path, filas_validas):
    raiz = tmp_path / "autorizado"
    raiz.mkdir()
    destino = tmp_path / "fuera.json"
    destino.write_text(json.dumps(filas_validas), encoding="utf-8")
    os.link(destino, raiz / "enlace.json")
    with pytest.raises(ValueError, match="cambió durante la apertura"):
        cli.cargar_manifiesto("enlace.json", raiz)


def test_manifiesto_rechaza_archivo_sustituido_durante_la_apertura(
    tmp_path, filas_validas, monkeypatch
):
    destino = tmp_path / "revisado.json"
    destino.write_text(json.dumps(filas_validas), encoding="utf-8")
    reemplazo = tmp_path / "reemplazo.json"
    reemplazo.write_text(json.dumps(filas_validas), encoding="utf-8")
    abrir = os.open

    def sustituir(ruta, *args, **kwargs):
        if ruta == destino:
            reemplazo.replace(destino)
        return abrir(ruta, *args, **kwargs)

    monkeypatch.setattr(cli.os, "open", sustituir)
    with pytest.raises(ValueError, match="cambió durante la apertura"):
        cli.cargar_manifiesto(destino.name, tmp_path)


@pytest.mark.parametrize(
    "contenido",
    [b"[]", b"{}", b"{", b"\xff", b"[1]", b'[{"idTipoAsiento":1,"idTipoAsiento":2}]'],
)
def test_manifiesto_rechaza_json_o_estructura_invalidos(tmp_path, contenido):
    (tmp_path / "invalido.json").write_bytes(contenido)
    with pytest.raises(ValueError, match="estructura"):
        cli.cargar_manifiesto("invalido.json", tmp_path)


@pytest.mark.parametrize(
    ("campo", "valor"),
    [
        ("idConceptoContable", True),
        ("vigenciaDesde", "2027-02-30"),
        ("lineas", []),
        ("codigoPlantilla", "../../otro"),
        ("nombre", "\x1b[0m"),
        ("campoExtra", 1),
    ],
)
def test_manifiesto_valida_campos_de_las_reglas(tmp_path, filas_validas, campo, valor):
    filas_validas[0]["borrador"][campo] = valor
    (tmp_path / "invalido.json").write_text(json.dumps(filas_validas), encoding="utf-8")
    with pytest.raises(ValueError, match="estructura"):
        cli.cargar_manifiesto("invalido.json", tmp_path)


@pytest.mark.parametrize(
    "url",
    [
        "https://otra.test/api/v1",
        "https://api.test.otra.test/api/v1",
        "https://api.test@otra.test/api/v1",
        "https://otra.test@api.test/api/v1",
        "https://api.test:8443/api/v1",
        "https://api.test/api/v1/../otro",
        "https://api.test/api/v1?x=1",
        "https://api.test/api/v1#x",
        "https://api.test\\@otra.test/api/v1",
        "https://api.test\n/api/v1",
        "https://api.test./api/v1",
        "https://api.test:99999/api/v1",
    ],
)
def test_url_rechaza_origenes_no_autorizados_y_urls_ambiguas(url):
    with pytest.raises(ValueError):
        cli.base_api_autorizada(url, "https://api.test")


def test_url_acepta_https_y_loopback_solo_si_esta_autorizado():
    assert (
        cli.base_api_autorizada("https://API.test/api/v1/", "https://api.test")
        == "https://api.test/api/v1"
    )
    url = "http://127.0.0.1:8014/api/v1"
    assert cli.base_api_autorizada(url, "https://api.test,http://127.0.0.1:8014") == url
    for destino, origenes in ((url, ""), ("http://api.test/api/v1", "http://api.test")):
        with pytest.raises(ValueError):
            cli.base_api_autorizada(destino, origenes)


def test_revision_y_rechazo_de_destino_no_piden_token(
    tmp_path, filas_validas, monkeypatch, capsys
):
    (tmp_path / "revisado.json").write_text(json.dumps(filas_validas), encoding="utf-8")
    monkeypatch.setattr(cli, "directorio_manifiestos", lambda: tmp_path)
    pedir = MagicMock()
    red = MagicMock()
    monkeypatch.setattr(cli.getpass, "getpass", pedir)
    monkeypatch.setattr(cli, "build_opener", red)
    monkeypatch.setattr(sys, "argv", ["registrar", "revisado.json"])
    cli.main()
    assert json.loads(capsys.readouterr().out) == filas_validas
    monkeypatch.setenv("E403_API_ORIGENES_AUTORIZADOS", "https://api.test")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "registrar",
            "revisado.json",
            "--registrar",
            "--url",
            "https://otra.test/api/v1",
        ],
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    pedir.assert_not_called()
    red.assert_not_called()


def test_registro_usa_origen_verificado_sin_proxy_ni_redireccion(
    tmp_path, filas_validas, monkeypatch
):
    (tmp_path / "revisado.json").write_text(json.dumps(filas_validas), encoding="utf-8")
    monkeypatch.setattr(cli, "directorio_manifiestos", lambda: tmp_path)
    monkeypatch.setenv("E403_API_ORIGENES_AUTORIZADOS", "https://api.test")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "registrar",
            "revisado.json",
            "--registrar",
            "--url",
            "https://API.test/api/v1/",
        ],
    )
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "sesion-ficticia")
    abrir = MagicMock()
    abrir.open.return_value.__enter__.return_value.read.return_value = b"[]"
    construir = MagicMock(return_value=abrir)
    monkeypatch.setattr(cli, "build_opener", construir)

    def solicitar(peticion, _filas):
        assert peticion("GET", "/contabilidad/plantillas") == []

    monkeypatch.setattr(cli, "registrar", solicitar)
    cli.main()
    peticion = abrir.open.call_args.args[0]
    assert peticion.full_url == "https://api.test/api/v1/contabilidad/plantillas"
    assert peticion.get_header("Authorization") == "Bearer sesion-ficticia"
    proxy, redireccion = construir.call_args.args
    assert proxy.proxies == {}
    assert (
        redireccion.redirect_request(peticion, None, 302, "", {}, "https://otra.test")
        is None
    )


def test_registrar_envia_y_recupera_solicitud_sin_duplicar():
    linea = {"lado": "DEBITO", "base": "DIFERENCIA", "origen": "FIJA", "cuenta": 7}
    filas = [
        {
            "idTipoAsiento": 2,
            "borrador": {
                "codigoPlantilla": "CAJA_FALTANTE",
                "idConceptoContable": 3,
                "vigenciaDesde": "2027-01-01",
                "lineas": [linea],
            },
        }
    ]
    posts = []

    def peticion(metodo, ruta, datos=None):
        if metodo == "POST":
            posts.append((ruta, datos))
            return {"idPlantillaAsiento": 4, "idSolicitud": 5}
        if "/plantillas?" in ruta:
            if not posts:
                return []
            return [
                {
                    "IdPlantillaAsiento": 4,
                    "IdTipoAsiento": 2,
                    "IdConceptoContable": 3,
                    "VigenciaDesde": "2027-01-01",
                    "Estado": False,
                }
            ]
        if ruta.endswith("/solicitudes"):
            return {"idSolicitud": 5}
        return {
            "lineas": [
                {
                    "Orden": 1,
                    "TipoMovimiento": "DEBITO",
                    "ComponenteImporte": "DIFERENCIA",
                    "OrigenCuenta": "FIJA",
                    "IdCuentaContable": 7,
                    "CodigoRol": None,
                }
            ]
        }

    registrar(peticion, filas)
    registrar(peticion, filas)
    assert len(posts) == 1
    assert posts[0][0] == "/contabilidad/tipos-asiento/2/plantillas"
