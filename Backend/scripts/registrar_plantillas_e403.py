"""Presenta JSON de E4-03 en la cola como el operador autenticado."""

import argparse
import getpass
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


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
        datos["nombre"] = cuerpo.get("nombre", codigo)
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
    parser.add_argument("manifiesto", type=Path)
    parser.add_argument("--url", required=True, help="Base API con /api/v1")
    parser.add_argument("--registrar", action="store_true", help="Enviar a E0-08")
    args = parser.parse_args()
    filas = json.loads(args.manifiesto.read_text(encoding="utf-8-sig"))
    if not isinstance(filas, list) or not filas:
        parser.error("El manifiesto debe ser un arreglo no vacío.")
    if not args.registrar:
        print(json.dumps(filas, ensure_ascii=False, indent=2))
        return
    url = urlsplit(args.url)
    if url.username or url.password or url.query or url.fragment or not url.hostname:
        parser.error("URL inválida.")
    if url.scheme != "https" and not (
        url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        parser.error("HTTPS obligatorio salvo laboratorio local.")
    token = getpass.getpass("Token del solicitante E0-08: ").strip()
    if not token:
        parser.error("Token requerido.")
    opener = build_opener(SinRedireccion())

    def peticion(metodo, ruta, datos=None):
        request = Request(
            args.url.rstrip("/") + ruta,
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
