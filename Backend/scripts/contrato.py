"""Contrato de la API por módulo (E0-03). **Sin activar**: no lo ejecuta el pipeline todavía.

    python scripts/contrato.py exportar      # escribe Backend/contract/<modulo>.json desde el código
    python scripts/contrato.py comparar      # código vs contrato confirmado; sale 1 y nombra cada diferencia
    python scripts/contrato.py convenciones  # informe de convenciones (Problem Details, Idempotency-Key, montos)

El contrato es el OpenAPI que genera FastAPI, partido por módulo (primer segmento después
de /api/v1/), con solo los esquemas que usa cada módulo. Se escribe o actualiza como
primera tarea de cada historia y lo revisan backend y frontend juntos. Determinista:
claves ordenadas, así un cambio en el diff es un cambio de contrato.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
CARPETA = BACKEND / "contract"
_EXCLUIDOS = {"pruebas"}  # PIN pad simulado: no es parte del contrato
_METODOS = {"get", "post", "put", "patch", "delete"}
_REF = "#/components/schemas/"


def openapi_del_codigo() -> dict[str, Any]:
    os.environ.setdefault("APP_ENV", "development")
    sys.path.insert(0, str(BACKEND))
    from app.main import app

    return app.openapi()


def modulo(ruta: str) -> str | None:
    partes = ruta.split("/")
    return partes[3] if ruta.startswith("/api/v1/") and len(partes) > 3 else None


def _refs(nodo: Any, encontrados: set[str]) -> None:
    if isinstance(nodo, dict):
        ref = nodo.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF):
            encontrados.add(ref[len(_REF) :])
        for valor in nodo.values():
            _refs(valor, encontrados)
    elif isinstance(nodo, list):
        for valor in nodo:
            _refs(valor, encontrados)


def _cierre(nombres: set[str], esquemas: dict[str, Any]) -> set[str]:
    """Los esquemas usados más los que ellos usan, transitivamente."""
    pendientes, vistos = list(nombres), set()
    while pendientes:
        nombre = pendientes.pop()
        if nombre in vistos or nombre not in esquemas:
            continue
        vistos.add(nombre)
        internos: set[str] = set()
        _refs(esquemas[nombre], internos)
        pendientes += sorted(internos - vistos)
    return vistos


def por_modulo(openapi: dict[str, Any]) -> dict[str, dict[str, Any]]:
    esquemas = openapi.get("components", {}).get("schemas", {})
    rutas: dict[str, dict[str, Any]] = {}
    for ruta, operaciones in openapi.get("paths", {}).items():
        mod = modulo(ruta)
        if mod and mod not in _EXCLUIDOS:
            rutas.setdefault(mod, {})[ruta] = operaciones
    contratos = {}
    for mod, paths in sorted(rutas.items()):
        usados: set[str] = set()
        _refs(paths, usados)
        contratos[mod] = {
            "openapi": openapi.get("openapi"),
            "info": {
                "title": f"Banking Platform · {mod}",
                "version": openapi.get("info", {}).get("version", ""),
            },
            "paths": paths,
            "components": {
                "schemas": {n: esquemas[n] for n in sorted(_cierre(usados, esquemas))}
            },
        }
    return contratos


def _texto(contrato: dict[str, Any]) -> str:
    return json.dumps(contrato, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def exportar(openapi: dict[str, Any], carpeta: Path = CARPETA) -> list[str]:
    carpeta.mkdir(parents=True, exist_ok=True)
    contratos = por_modulo(openapi)
    for mod, contrato in contratos.items():
        (carpeta / f"{mod}.json").write_text(_texto(contrato), encoding="utf-8")
    for viejo in carpeta.glob("*.json"):
        if viejo.stem not in contratos:
            viejo.unlink()
    return sorted(contratos)


def _operaciones(contrato: dict[str, Any]) -> dict[tuple[str, str], Any]:
    return {
        (metodo.upper(), ruta): op
        for ruta, ops in contrato.get("paths", {}).items()
        for metodo, op in ops.items()
        if metodo in _METODOS
    }


def _firma(op: dict[str, Any], esquemas: dict[str, Any]) -> str:
    """Lo que el frontend usa de una operación: parámetros, cuerpo, códigos y esquemas."""
    usados: set[str] = set()
    _refs(op, usados)
    datos = {
        "parametros": sorted(
            (
                p.get("in"),
                p.get("name"),
                p.get("required", False),
                json.dumps(p.get("schema"), sort_keys=True),
            )
            for p in op.get("parameters", [])
        ),
        "cuerpo": op.get("requestBody"),
        "respuestas": {
            codigo: r.get("content") for codigo, r in op.get("responses", {}).items()
        },
        "esquemas": {n: esquemas.get(n) for n in sorted(_cierre(usados, esquemas))},
    }
    return json.dumps(datos, sort_keys=True, default=str)


def comparar(openapi: dict[str, Any], carpeta: Path = CARPETA) -> list[str]:
    """Diferencias entre el código y el contrato confirmado, una por línea."""
    diferencias: list[str] = []
    actuales = por_modulo(openapi)
    confirmados = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(carpeta.glob("*.json"))
    }
    for mod in sorted(set(actuales) | set(confirmados)):
        codigo, contrato = actuales.get(mod, {}), confirmados.get(mod, {})
        ops_codigo, ops_contrato = _operaciones(codigo), _operaciones(contrato)
        for metodo, ruta in sorted(set(ops_codigo) - set(ops_contrato)):
            diferencias.append(
                f"{metodo} {ruta}: está en el código y no en el contrato ({mod}.json)"
            )
        for metodo, ruta in sorted(set(ops_contrato) - set(ops_codigo)):
            diferencias.append(
                f"{metodo} {ruta}: está en el contrato ({mod}.json) y no en el código"
            )
        esq_codigo = codigo.get("components", {}).get("schemas", {})
        esq_contrato = contrato.get("components", {}).get("schemas", {})
        for clave in sorted(set(ops_codigo) & set(ops_contrato)):
            if _firma(ops_codigo[clave], esq_codigo) != _firma(
                ops_contrato[clave], esq_contrato
            ):
                diferencias.append(
                    f"{clave[0]} {clave[1]}: parámetros, cuerpo, respuestas o esquemas distintos del contrato"
                )
    return diferencias


_DINERO = {"caja", "transacciones", "atm", "boveda"}


def convenciones(openapi: dict[str, Any]) -> list[str]:
    """Avisos (no fallan): convenciones del criterio 4 que aún no cumple una operación."""
    avisos: list[str] = []
    esquemas = openapi.get("components", {}).get("schemas", {})
    for (metodo, ruta), op in sorted(_operaciones(openapi).items()):
        mod = modulo(ruta)
        if not mod or mod in _EXCLUIDOS:
            continue
        errores = [c for c in op.get("responses", {}) if c.startswith(("4", "5"))]
        if errores and not any(
            "application/problem+json" in (op["responses"][c].get("content") or {})
            for c in errores
        ):
            avisos.append(f"{metodo} {ruta}: errores sin application/problem+json")
        if metodo == "POST" and mod in _DINERO:
            cabeceras = {
                p.get("name", "").lower()
                for p in op.get("parameters", [])
                if p.get("in") == "header"
            }
            if "idempotency-key" not in cabeceras:
                avisos.append(
                    f"{metodo} {ruta}: operación de dinero sin cabecera Idempotency-Key"
                )
    for nombre, esquema in sorted(esquemas.items()):
        for campo, prop in (esquema.get("properties") or {}).items():
            if any(
                campo.lower().startswith(p)
                for p in ("monto", "saldo", "valor", "importe")
            ) and prop.get("type") in ("number", "integer"):
                avisos.append(
                    f"{nombre}.{campo}: monto como número; la convención es cadena decimal con 2 posiciones"
                )
    return avisos


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["exportar", "comparar", "convenciones"])
    a = ap.parse_args()
    openapi = openapi_del_codigo()
    if a.accion == "exportar":
        modulos = exportar(openapi)
        print(
            f"contrato exportado: {len(modulos)} módulos en {CARPETA.relative_to(BACKEND)}/"
        )
        return 0
    if a.accion == "comparar":
        diferencias = comparar(openapi)
        for d in diferencias:
            print(f"DIFERENCIA {d}")
        print(
            "contrato y código coinciden"
            if not diferencias
            else f"{len(diferencias)} diferencias"
        )
        return 1 if diferencias else 0
    avisos = convenciones(openapi)
    for aviso in avisos:
        print(f"aviso {aviso}")
    print(f"{len(avisos)} avisos de convenciones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
