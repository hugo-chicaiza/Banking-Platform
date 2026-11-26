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
from app.core.security.permisos import permisos_de
from app.modules.boveda import repository as repo
from app.modules.boveda import service
from app.modules.boveda.router import router
from app.modules.boveda.solicitudes import repository as solicitudes_repo
from tests.sesion import USUARIO

BASE = "/api/v1/boveda"


class BovedaContexto:
    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api/v1")
        self.app.add_middleware(TraceIdMiddleware)
        self.client = TestClient(self.app)
        self.usuario = replace(
            USUARIO,
            roles=("SUPERVISOR",),
            permisos=permisos_de(("SUPERVISOR",)),
            id_interno=7,
        )
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
            "solicitudes": {},
            "detalle_solicitudes": {},
        }
        self.bloqueos: list[int] = []
        self.fallo_asiento: int | None = None
        self.intentos_asiento = 0
        monkeypatch.setattr(service, "validar_participante_boveda", lambda *args: None)
        monkeypatch.setattr(
            service.contabilidad, "resolver_id_fecha_contable", lambda *args: 1
        )
        monkeypatch.setattr(
            service.repo_contable, "bloquear_contabilizacion", lambda *args: None
        )
        monkeypatch.setattr(service.repo_contable, "obtener_por_id", lambda *args: None)
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
            "listar_arqueos",
            "ajustes_arqueos",
            "obtener_arqueo",
            "detalle_arqueo",
            "ajustes_arqueo",
            "aprobar_arqueo",
        ):
            monkeypatch.setattr(repo, nombre, getattr(self, nombre))
        for nombre in (
            "obtener",
            "repeticion",
            "listar",
            "detalles",
            "movimientos",
            "crear",
            "resolver",
            "vincular",
        ):
            monkeypatch.setattr(
                solicitudes_repo, nombre, getattr(self, "solicitud_" + nombre)
            )

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
            self.usuario,
            roles=roles,
            permisos=permisos_de(roles),
            id_interno=actor,
            id_agencia=agencia,
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

    def listar_arqueos(
        self, conn, id_boveda, desde, hasta, estado, tipo, page, page_size
    ):
        filas = [
            deepcopy(a)
            for a in self.state["arqueos"].values()
            if a["id_boveda"] == id_boveda
            and (desde is None or a["fecha_hora_arqueo"].date() >= desde)
            and (hasta is None or a["fecha_hora_arqueo"].date() <= hasta)
            and (estado is None or a["estado"] == estado)
            and (tipo is None or a["tipo_arqueo"] == tipo)
        ]
        filas.sort(
            key=lambda a: (a["fecha_hora_arqueo"], a["id_arqueo_boveda"]), reverse=True
        )
        return filas[(page - 1) * page_size : page * page_size], len(filas)

    def ajustes_arqueos(self, conn, ids):
        return {i: self.ajustes_arqueo(conn, i) for i in ids}

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

    def ejecutar(self, ruta, json, headers=None):
        """Ejercita creación y aprobación por dos sesiones diferentes."""
        creada = self.client.post(
            ruta.replace("/movimientos", "/solicitudes-movimiento"),
            json=json,
            headers=headers,
        )
        if creada.status_code != 201:
            return creada
        anterior = self.usuario
        try:
            self.usuario = replace(anterior, id_interno=9)
            return self.client.post(
                f"{BASE}/solicitudes-movimiento/{creada.json()['idSolicitudMovimiento']}/aprobacion"
            )
        finally:
            self.usuario = anterior

    def solicitud_obtener(self, conn, i, bloquear=False):
        return deepcopy(self.state["solicitudes"].get(i))

    def solicitud_repeticion(self, conn, actor, clave):
        return next(
            (
                deepcopy(s)
                for s in self.state["solicitudes"].values()
                if s["id_usuario_solicitante"] == actor and s["clave"] == clave
            ),
            None,
        )

    def solicitud_listar(self, conn, agencia, estado, page, page_size):
        filas = [
            deepcopy(s)
            for s in self.state["solicitudes"].values()
            if (agencia is None or s["id_agencia"] == agencia)
            and (estado is None or s["estado"] == estado)
        ]
        return filas[(page - 1) * page_size : page * page_size], len(filas)

    def solicitud_detalles(self, conn, ids):
        return {i: deepcopy(self.state["detalle_solicitudes"][i]) for i in ids}

    def solicitud_movimientos(self, conn, ids):
        return {
            i: [
                m["id_movimiento"]
                for m in self.state["movimientos"].values()
                if m.get("solicitud") == i
            ]
            for i in ids
        }

    def solicitud_crear(self, conn, datos, detalle):
        i = len(self.state["solicitudes"]) + 1
        self.state["solicitudes"][i] = {
            "id_solicitud_movimiento": i,
            "id_boveda": datos["boveda"],
            "id_boveda_contraparte": datos["contraparte"],
            "id_agencia": datos["agencia"],
            "tipo_movimiento": datos["tipo"],
            "monto": datos["monto"],
            "id_usuario_solicitante": datos["actor"],
            "fecha_solicitud": datos["ahora"],
            "estado": "PENDIENTE",
            "observaciones": datos["observaciones"],
            "clave": datos["clave"],
            "huella_peticion": datos["huella"],
            "id_usuario_resolucion": None,
            "fecha_resolucion": None,
            "motivo_resolucion": None,
        }
        self.state["detalle_solicitudes"][i] = deepcopy(detalle)
        return i

    def solicitud_resolver(self, conn, i, estado, actor, ahora, motivo):
        self.state["solicitudes"][i].update(
            estado=estado,
            id_usuario_resolucion=actor,
            fecha_resolucion=ahora,
            motivo_resolucion=motivo,
        )

    def solicitud_vincular(self, conn, i, ids):
        for m in ids:
            self.state["movimientos"][m]["solicitud"] = i
            self.state["movimientos"][m]["id_solicitud_movimiento"] = i
