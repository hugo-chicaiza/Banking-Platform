"""Repositorio en memoria transaccional para probar las reglas BOV por HTTP."""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.api.middleware import TraceIdMiddleware
from app.core.database.db import cooperativa
from app.core.security.auth import usuario_actual
from app.modules.boveda import repository as repo
from app.modules.boveda import service
from app.modules.boveda.router import router
from tests.sesion import USUARIO

BASE = "/api/v1/boveda"


class BovedaContexto:
    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api/v1")
        self.app.add_middleware(TraceIdMiddleware)
        self.client = TestClient(self.app)
        self.usuario = replace(USUARIO, roles=("SUPERVISOR",), id_interno=7)
        self.conn = MagicMock()
        self.conn.begin.side_effect = self.transaccion
        self.app.dependency_overrides[cooperativa] = lambda: self.conn
        self.app.dependency_overrides[usuario_actual] = lambda: self.usuario
        self.state: dict[str, Any] = {
            "bovedas": {
                i: {
                    "id_boveda": i,
                    "codigo_boveda": f"B{i}",
                    "tipo_boveda": "General",
                    "id_agencia": agencia,
                    "id_boveda_superior": None,
                    "limite_maximo": Decimal(1000),
                    "limite_minimo": Decimal(50),
                    "saldo_actual": Decimal(200),
                    "estado": "A",
                }
                for i, agencia in ((1, "001"), (2, "002"))
            },
            "catalogo": {
                1: {"valor": Decimal(20), "estado": "A"},
                2: {"valor": Decimal(10), "estado": "A"},
            },
            "inventarios": {1: {1: 10}, 2: {1: 10}},
            "movimientos": {},
            "desgloses": {},
            "arqueos": {},
            "detalles": {},
            "asientos": [],
        }
        self.bloqueos: list[int] = []
        self.fallo_asiento: int | None = None
        self.intentos_asiento = 0
        monkeypatch.setattr(service, "validar_participante_boveda", lambda *args: None)
        monkeypatch.setattr(
            service.contabilidad, "resolver_id_fecha_contable", lambda *args: 1
        )
        monkeypatch.setattr(
            service.contabilidad, "contabilizar_boveda", self.contabilizar
        )
        for nombre in (
            "listar_bovedas",
            "obtener_boveda",
            "inventarios",
            "denominaciones",
            "ultimo_movimiento",
            "crear_movimiento",
            "actualizar_inventario",
            "vincular_asiento",
            "relacionar_movimiento",
            "repeticion",
            "huella_movimiento",
            "obtener_movimiento",
            "desgloses_movimientos",
            "listar_movimientos",
            "crear_arqueo",
            "obtener_arqueo",
            "detalle_arqueo",
            "ajustes_arqueo",
            "aprobar_arqueo",
        ):
            monkeypatch.setattr(repo, nombre, getattr(self, nombre))

    @contextmanager
    def transaccion(self):
        anterior = deepcopy(self.state)
        try:
            yield
        except BaseException:
            self.state = anterior
            raise

    def como(self, *roles: str, actor: int | None = 7, agencia: str | None = "001"):
        self.usuario = replace(
            self.usuario, roles=roles, id_interno=actor, id_agencia=agencia
        )

    def contabilizar(self, conn, **datos):
        self.intentos_asiento += 1
        if self.intentos_asiento == self.fallo_asiento:
            from app.core.api.errors import problema

            raise problema(409, "PLANTILLA_BOVEDA_NO_CONFIGURADA", "Falta plantilla.")
        self.state["asientos"].append(datos)
        return len(self.state["asientos"])

    def listar_bovedas(self, conn, agencia, tipo):
        return [
            deepcopy(f)
            for f in self.state["bovedas"].values()
            if (agencia is None or agencia == f["id_agencia"])
            and (tipo is None or tipo == f["tipo_boveda"])
        ]

    def obtener_boveda(self, conn, id_boveda, bloquear=False):
        if bloquear:
            self.bloqueos.append(id_boveda)
        return deepcopy(self.state["bovedas"].get(id_boveda))

    def inventarios(self, conn, ids):
        return {
            i: [
                {
                    "id_denominacion": d,
                    "cantidad_actual": n,
                    "valor": self.state["catalogo"][d]["valor"],
                }
                for d, n in self.state["inventarios"][i].items()
            ]
            for i in ids
        }

    def denominaciones(self, conn, ids):
        return {
            i: self.state["catalogo"][i] for i in ids if i in self.state["catalogo"]
        }

    def ultimo_movimiento(self, conn, id_boveda):
        return max(
            (
                i
                for i, m in self.state["movimientos"].items()
                if m["id_boveda"] == id_boveda
            ),
            default=0,
        )

    def crear_movimiento(self, conn, datos):
        i = len(self.state["movimientos"]) + 1
        self.state["movimientos"][i] = {
            "id_movimiento": i,
            "id_boveda": datos["id_boveda"],
            "id_boveda_contraparte": datos["contraparte"],
            "tipo_movimiento": datos["tipo"],
            "naturaleza": datos["naturaleza"],
            "monto": datos["monto"],
            "saldo_anterior": datos["anterior"],
            "saldo_posterior": datos["posterior"],
            "autorizado_por": datos["autorizador"],
            "id_usuario_movimiento": datos["actor"],
            "id_movimiento_relacionado": datos["relacionado"],
            "fecha_movimiento": datos["ahora"],
            "observaciones": datos["observaciones"],
            "id_asiento_contable": None,
            "arqueo": datos["arqueo"],
            "clave": datos["clave"],
            "huella": datos["huella"],
        }
        return i

    def actualizar_inventario(
        self, conn, id_boveda, id_movimiento, piezas, ingreso, ahora, saldo
    ):
        inventario = self.state["inventarios"][id_boveda]
        for i, cantidad in piezas.items():
            inventario[i] = inventario.get(i, 0) + (cantidad if ingreso else -cantidad)
        self.state["desgloses"][id_movimiento] = [
            {"id_denominacion": i, "cantidad": n} for i, n in piezas.items()
        ]
        self.state["bovedas"][id_boveda]["saldo_actual"] = saldo

    def vincular_asiento(self, conn, id_movimiento, asiento):
        self.state["movimientos"][id_movimiento]["id_asiento_contable"] = asiento

    def relacionar_movimiento(self, conn, origen, destino):
        self.state["movimientos"][origen]["id_movimiento_relacionado"] = destino

    def repeticion(self, conn, actor, clave):
        return next(
            (
                m
                for m in self.state["movimientos"].values()
                if m["id_usuario_movimiento"] == actor and m["clave"] == clave
            ),
            None,
        )

    def huella_movimiento(self, conn, id_movimiento):
        return self.state["movimientos"][id_movimiento]["huella"]

    def obtener_movimiento(self, conn, i):
        return self.state["movimientos"][i]

    def desgloses_movimientos(self, conn, ids):
        return {i: self.state["desgloses"][i] for i in ids}

    def listar_movimientos(
        self, conn, id_boveda, tipo, desde, hasta, page, page_size, sort
    ):
        filas = [
            m
            for m in self.state["movimientos"].values()
            if m["id_boveda"] == id_boveda
            and (tipo is None or m["tipo_movimiento"] == tipo)
        ]
        return filas[(page - 1) * page_size : page * page_size], len(filas)

    def crear_arqueo(self, conn, datos, detalle):
        i = len(self.state["arqueos"]) + 1
        self.state["arqueos"][i] = {
            "id_arqueo_boveda": i,
            "id_boveda": datos["id_boveda"],
            "fecha_hora_arqueo": datos["ahora"],
            "tipo_arqueo": datos["tipo"],
            "id_usuario_arqueador": datos["actor"],
            "id_usuario_testigo": datos["testigo"],
            "estado": "REGISTRADO",
            "id_movimiento_ajuste": None,
            "observaciones": datos["observaciones"],
            "saldo_teorico": datos["teorico"],
            "saldo_fisico": datos["fisico"],
            "id_movimiento_corte": datos["corte"],
            "id_usuario_aprobador": None,
            "fecha_hora_aprobacion": None,
        }
        self.state["detalles"][i] = deepcopy(detalle)
        return i

    def obtener_arqueo(self, conn, i, bloquear=False):
        return deepcopy(self.state["arqueos"].get(i))

    def detalle_arqueo(self, conn, i):
        return self.state["detalles"][i]

    def ajustes_arqueo(self, conn, i):
        return [k for k, m in self.state["movimientos"].items() if m["arqueo"] == i]

    def aprobar_arqueo(self, conn, i, actor, ahora, ajuste):
        self.state["arqueos"][i].update(
            estado="APROBADO",
            id_usuario_aprobador=actor,
            fecha_hora_aprobacion=ahora,
            id_movimiento_ajuste=ajuste,
        )

    def movimiento(self, tipo="ProvisionExterna", **extra):
        return {
            "tipoMovimiento": tipo,
            "autorizadoPor": 9,
            "desglose": [{"idDenominacion": 1, "cantidad": 2}],
            **extra,
        }

    def arqueo(self, cantidad=10, **extra):
        return {
            "tipoArqueo": "Sorpresivo",
            "idUsuarioTestigo": 9,
            "desglose": [{"idDenominacion": 1, "cantidad": cantidad}],
            **extra,
        }

    def registrar_conteo(self, cantidad=10, **extra):
        return self.client.post(
            f"{BASE}/bovedas/1/arqueos", json=self.arqueo(cantidad, **extra)
        )
