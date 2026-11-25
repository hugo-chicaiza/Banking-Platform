"""Presenta JSON de E4-03 en la cola como el operador autenticado."""

import argparse
import getpass
import json
import os
import re
import stat
from datetime import date
from pathlib import Path
from typing import Annotated, Literal
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

MAX_BYTES = 1_048_576
_NOMBRE_JSON = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.json", re.ASCII)
_DISPOSITIVO = re.compile(
    r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.IGNORECASE
)
_AUTORIDAD = re.compile(r"(?:[a-z0-9][a-z0-9.-]*|\[::1\])(?::[0-9]{1,5})?", re.ASCII)
Id = Annotated[int, Field(strict=True, gt=0, le=2_147_483_647)]


class Linea(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lado: Literal["DEBITO", "CREDITO"]
    base: Literal[
        "PRINCIPAL",
        "COMISION",
        "IMPUESTO",
        "INTERES",
        "MORA",
        "SEGURO",
        "DIFERENCIA",
        "TOTAL",
    ]
    origen: Literal["FIJA", "PRODUCTO", "CONTRAPRODUCTO", "COMISION"]
    cuenta: Id | None = None
    rol: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,29}$")] | None = None

    @model_validator(mode="after")
    def validar_referencia(self):
        if (self.cuenta is not None) != (self.origen == "FIJA") or (
            self.rol is not None
        ) != (self.origen in {"PRODUCTO", "CONTRAPRODUCTO"}):
            raise ValueError("La referencia no corresponde al origen de cuenta.")
        return self


class Borrador(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codigoPlantilla: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,49}$")]
    idConceptoContable: Id
    vigenciaDesde: Annotated[str, Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
    nombre: Annotated[str, Field(min_length=1, max_length=100)] | None = None
    lineas: Annotated[list[Linea], Field(min_length=2, max_length=100)]

    @model_validator(mode="after")
    def validar_vigencia_y_nombre(self):
        date.fromisoformat(self.vigenciaDesde)
        if self.nombre is not None and (
            not self.nombre.strip()
            or any(not caracter.isprintable() for caracter in self.nombre)
        ):
            raise ValueError("Nombre de plantilla inválido.")
        return self


class EntradaPlana(Borrador):
    idTipoAsiento: Id
    agencia: Annotated[str, Field(pattern=r"^[0-9]{3}$")] | None = None
    operacion: (
        Literal[
            "Traslado",
            "AjusteFaltante",
            "AjusteSobrante",
            "ProvisionExterna",
            "EnvioExcedente",
        ]
        | None
    ) = None
    naturaleza: Literal["I", "E"] | None = None

    @model_validator(mode="after")
    def validar_ambito(self):
        if any(
            x is not None for x in (self.agencia, self.operacion, self.naturaleza)
        ) and (
            self.operacion is None
            or self.agencia is None
            or self.naturaleza is None
            or self.codigoPlantilla
            != f"BOV_{self.agencia}_{self.operacion.upper()}_{self.naturaleza}"
        ):
            raise ValueError("El código no corresponde al ámbito declarado.")
        return self


class EntradaAnidada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idTipoAsiento: Id
    borrador: Borrador


_MANIFIESTO = TypeAdapter(
    Annotated[list[EntradaAnidada | EntradaPlana], Field(min_length=1, max_length=500)]
)


def directorio_manifiestos() -> Path:
    return Path.home() / ".banking-platform" / "e403" / "manifiestos"


def _sin_claves_repetidas(pares):
    resultado = dict(pares)
    if len(resultado) != len(pares):
        raise ValueError("El JSON contiene claves repetidas.")
    return resultado


def cargar_manifiesto(nombre: str, directorio: Path):
    if not _NOMBRE_JSON.fullmatch(nombre) or _DISPOSITIVO.match(nombre):
        raise ValueError("Indique solo el nombre de un archivo .json autorizado.")
    try:
        raiz = directorio.absolute()
        if raiz.resolve(strict=True) != raiz or not raiz.is_dir():
            raise ValueError(
                "El directorio autorizado debe ser un directorio local sin enlaces."
            )
        ruta = next(
            (entrada for entrada in raiz.iterdir() if entrada.name == nombre), None
        )
        if ruta is None:
            raise ValueError(
                "No se encontró el manifiesto en el directorio autorizado."
            )
        canonica = ruta.resolve(strict=True)
        if canonica != ruta or not canonica.is_relative_to(raiz) or ruta.is_symlink():
            raise ValueError(
                "El manifiesto debe permanecer en el directorio autorizado y sin enlaces."
            )
        anterior = ruta.lstat()
        if not stat.S_ISREG(anterior.st_mode) or anterior.st_size > MAX_BYTES:
            raise ValueError(
                "El manifiesto debe ser un archivo regular de hasta 1 MiB."
            )
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        with os.fdopen(os.open(canonica, flags), "rb") as archivo:
            actual = os.fstat(archivo.fileno())
            if (
                not stat.S_ISREG(actual.st_mode)
                or not os.path.samestat(anterior, actual)
                or actual.st_nlink != 1
                or actual.st_size > MAX_BYTES
                or ruta.resolve(strict=True) != canonica
                or not os.path.samestat(ruta.lstat(), actual)
            ):
                raise ValueError(
                    "El manifiesto cambió durante la apertura o supera 1 MiB."
                )
            datos = archivo.read(MAX_BYTES + 1)
        if len(datos) > MAX_BYTES:
            raise ValueError("El manifiesto supera 1 MiB.")
    except (OSError, RuntimeError):
        raise ValueError(
            "No se pudo abrir el manifiesto en el directorio autorizado."
        ) from None
    try:
        filas = json.loads(
            datos.decode("utf-8-sig"), object_pairs_hook=_sin_claves_repetidas
        )
        validadas = _MANIFIESTO.validate_python(filas)
    except (ValueError, RecursionError):
        raise ValueError(
            "El manifiesto debe ser JSON UTF-8 con la estructura de E4-03."
        ) from None
    codigos = [
        fila.borrador.codigoPlantilla
        if isinstance(fila, EntradaAnidada)
        else fila.codigoPlantilla
        for fila in validadas
    ]
    if len(codigos) != len(set(codigos)):
        raise ValueError("El manifiesto contiene familias repetidas.")
    return filas


def _origen(valor: str, ruta_api: bool) -> str:
    if any(
        not caracter.isascii() or caracter.isspace() or not caracter.isprintable()
        for caracter in valor
    ):
        raise ValueError("URL de API inválida.")
    url = urlsplit(valor)
    autoridad = url.netloc.lower()
    rutas = ("/api/v1", "/api/v1/") if ruta_api else ("", "/")
    if (
        not _AUTORIDAD.fullmatch(autoridad)
        or not url.hostname
        or url.path not in rutas
        or "?" in valor
        or "#" in valor
        or url.port == 0
        or url.hostname.endswith(".")
    ):
        raise ValueError("URL de API inválida.")
    if url.scheme != "https" and not (
        url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}
    ):
        raise ValueError("HTTPS obligatorio salvo laboratorio local autorizado.")
    return f"{url.scheme}://{autoridad}"


def base_api_autorizada(url: str, configuracion: str) -> str:
    autorizados = {
        _origen(valor.strip(), False)
        for valor in configuracion.split(",")
        if valor.strip()
    }
    destino = _origen(url, True)
    if destino not in autorizados:
        raise ValueError(
            "El origen de la API no figura en E403_API_ORIGENES_AUTORIZADOS."
        )
    return destino + "/api/v1"


class SinRedireccion(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def registrar(peticion, filas):
    for fila in filas:
        tipo = int(fila["idTipoAsiento"])
        cuerpo = fila.get("borrador", fila)
        datos = {
            k: cuerpo[k]
            for k in (
                "codigoPlantilla",
                "idConceptoContable",
                "vigenciaDesde",
                "lineas",
            )
        }
        codigo = datos["codigoPlantilla"]
        datos["nombre"] = cuerpo.get("nombre") or codigo
        datos["soloPrimeraVersion"] = True
        existentes = peticion(
            "GET", "/contabilidad/plantillas?" + urlencode({"codigo": codigo})
        )
        if not existentes:
            resultado = peticion(
                "POST", f"/contabilidad/tipos-asiento/{tipo}/plantillas", datos
            )
            print(json.dumps({"codigo": codigo, **resultado}))
            continue
        exacta = [
            v
            for v in existentes
            if (
                v["VigenciaDesde"] == datos["vigenciaDesde"]
                and v["IdTipoAsiento"] == tipo
                and v["IdConceptoContable"] == datos["idConceptoContable"]
            )
        ]
        if len(exacta) != 1:
            raise SystemExit(
                f"{codigo}: familia existente con otra fecha o metadatos. Revisar."
            )
        ident = exacta[0]["IdPlantillaAsiento"]
        detalle = peticion("GET", f"/contabilidad/plantillas/{ident}")
        esperado = [
            (l["lado"], l["base"], l["origen"], l.get("cuenta"), l.get("rol"))
            for l in datos["lineas"]
        ]
        actual = [
            (
                l["TipoMovimiento"],
                l["ComponenteImporte"],
                l["OrigenCuenta"],
                l["IdCuentaContable"],
                l["CodigoRol"],
            )
            for l in sorted(detalle["lineas"], key=lambda l: l["Orden"])
        ]
        if esperado != actual:
            raise SystemExit(
                f"{codigo}: el borrador existente tiene otras líneas. Revisar."
            )
        ruta = f"/contabilidad/plantillas/{ident}/solicitudes"
        solicitud = peticion("GET", ruta)
        if solicitud is None and not exacta[0]["Estado"]:
            solicitud = peticion("POST", ruta)
        print(
            json.dumps(
                {"codigo": codigo, "idPlantillaAsiento": ident, "solicitud": solicitud}
            )
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifiesto", help="Nombre .json en ~/.banking-platform/e403/manifiestos"
    )
    parser.add_argument(
        "--url", help="Base API autorizada con /api/v1, obligatoria para registrar"
    )
    parser.add_argument("--registrar", action="store_true", help="Enviar a E0-08")
    args = parser.parse_args()
    try:
        filas = cargar_manifiesto(args.manifiesto, directorio_manifiestos())
    except ValueError as error:
        parser.error(str(error))
    if not args.registrar:
        print(json.dumps(filas, ensure_ascii=False, indent=2))
        return
    if not args.url:
        parser.error("--url es obligatorio al registrar.")
    try:
        base_api = base_api_autorizada(
            args.url, os.environ.get("E403_API_ORIGENES_AUTORIZADOS", "")
        )
    except ValueError as error:
        parser.error(str(error))
    token = getpass.getpass("Token del solicitante E0-08: ").strip()
    if not token:
        parser.error("Token requerido.")
    opener = build_opener(ProxyHandler({}), SinRedireccion())

    def peticion(metodo, ruta, datos=None):
        request = Request(
            base_api + ruta,
            method=metodo,
            data=json.dumps(datos).encode("utf-8") if datos is not None else None,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with opener.open(request, timeout=30) as resp:
                return json.load(resp)
        except HTTPError as error:
            raise SystemExit(
                f"{metodo} {ruta}: HTTP {error.code}. {error.read().decode()}"
            ) from error

    registrar(peticion, filas)


if __name__ == "__main__":
    main()
