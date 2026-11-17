from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.modules.contabilidad import corte_workos
from tests.sesion import usuario_con_roles


def test_aprobacion_excluye_identidad_enviada():
    with pytest.raises(ValidationError):
        corte_workos.Aprobacion.model_validate(
            {
                "hashPlan": "a" * 64,
                "comentario": "Revisado",
                "AprobadoPor": 42,
            }
        )


def test_aprobacion_usa_la_sesion(monkeypatch):
    usuario = usuario_con_roles("CONTADOR")
    plan = uuid4()
    datos = corte_workos.Aprobacion(hashPlan="a" * 64, comentario="Revisado")
    llamada = {}

    def operar(modo, sesion, id_plan, **params):
        llamada.update(modo=modo, sesion=sesion, id_plan=id_plan, **params)
        return {"IdSolicitud": -1}

    monkeypatch.setattr(corte_workos, "operar", operar)
    assert corte_workos.aprobar(plan, datos, usuario) == {"IdSolicitud": -1}
    assert llamada["sesion"] is usuario
    assert llamada["hash_plan"] == bytes.fromhex("a" * 64)


def test_organizacion_distinta_rechazada_antes_de_sql(monkeypatch):
    usuario = replace(usuario_con_roles("CONTADOR"), id_organizacion="otra")
    monkeypatch.setattr(
        corte_workos,
        "get_settings",
        lambda: type(
            "Cfg",
            (),
            {
                "workos_organization_id": "institucion",
            },
        )(),
    )
    with pytest.raises(HTTPException) as fallo:
        corte_workos.operar("APROBAR", usuario, uuid4())
    assert fallo.value.status_code == 403


def test_aprobacion_revalida_ambos_vinculos(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace

    usuario = replace(usuario_con_roles("CONTADOR"), id_organizacion="org-dev")
    consultas = []

    def identidad(sujeto):
        consultas.append(sujeto)
        return 10 if sujeto == usuario.id_usuario else 20

    def sql(conn, lote, params):
        if params[0] == "VER":
            return {"SujetoPreparador": "user_preparador", "UsuarioPreparador": 20}
        assert params[:4] == ("APROBAR", 10, usuario.id_usuario, "org-dev")
        return {"IdSolicitud": -2}

    monkeypatch.setattr(
        corte_workos,
        "get_settings",
        lambda: SimpleNamespace(workos_organization_id="org-dev"),
    )
    monkeypatch.setattr(
        corte_workos,
        "motor_corte",
        lambda: SimpleNamespace(begin=lambda: nullcontext(None)),
    )
    monkeypatch.setattr(corte_workos, "identidad_vigente", identidad)
    monkeypatch.setattr(corte_workos, "ejecutar_con_salidas", sql)
    assert corte_workos.operar("APROBAR", usuario, uuid4()) == {"IdSolicitud": -2}
    assert consultas == [usuario.id_usuario, "user_preparador"]
