"""Identidad de las familias versionadas de custodia por agencia y etapa."""

import re

_NATURALEZAS = {
    "TRASLADO": {"E", "I"},
    "AJUSTEFALTANTE": {"E"},
    "AJUSTESOBRANTE": {"I"},
    "PROVISIONEXTERNA": {"I"},
    "ENVIOEXCEDENTE": {"E"},
    "REPOSICIONFALTANTE": {"I"},
    "JUSTIFICAFALTANTE": {"E"},
    "DESCUENTOFALTANTE": {"E"},
}


def codigo_boveda(agencia: str, tipo: str, naturaleza: str) -> str:
    return f"BOV_{agencia.strip()}_{tipo.upper()}_{naturaleza}"


def ambito_boveda(codigo: str) -> tuple[str, str, str] | None:
    coincidencia = re.fullmatch(r"BOV_([0-9]{3})_([A-Z]+)_([IE])", codigo)
    if coincidencia is None:
        return None
    agencia, tipo, naturaleza = coincidencia.groups()
    if naturaleza not in _NATURALEZAS.get(tipo, set()):
        return None
    return agencia, tipo, naturaleza
