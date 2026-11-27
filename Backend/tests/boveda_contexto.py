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
            "novedades": {},
            "detalles": {},
            "asientos": [],
            "solicitudes": {},
            "detalle_solicitudes": {},
            "conteos_solicitudes": {},
            "cupos_solicitudes": {},
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
            service.repo_contable, "plantilla_boveda", self.plantilla_movimiento
        )
        monkeypatch.setattr(
            service.repo_contable,
            "cuenta_boveda",
            lambda *args: {
                "estado": True,
                "imputable": True,
            },
        )
        monkeypatch.setattr(
            service.repo_contable, "movimientos_asiento", self.movimientos_asiento
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
            "listar_arqueos",
            "ajustes_arqueos",
            "obtener_arqueo",
            "detalle_arqueo",
            "ajustes_arqueo",
            "aprobar_arqueo",
            "vincular_ajuste_arqueo",
            "novedades_arqueos",
            "crear_novedad",
            "resolver_novedad",
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
            "anular",
            "destinos",
            "conteos",
            "guardar_conteo",
            "cupo_ocupado",
            "reservar_cupo",
            "liberar_cupo",
            "despachar",
            "confirmar",
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

    def plantilla_movimiento(self, conn, agencia, tipo, naturaleza):
        debe, haber = {
            ("Traslado", "E"): (6, 1),
            ("Traslado", "I"): (1, 6),
            ("RetornoRemesa", "I"): (1, 6),
            ("FaltanteTransito", "E"): (2, 6),
            ("SobranteTransito", "I"): (6, 3),
            ("DespachoExcedente", "E"): (6, 1),
            ("CierreExcedente", "I"): (7, 6),
            ("ProvisionExterna", "I"): (1, 7),
        }[(tipo, naturaleza)]
        return {"debito": debe, "credito": haber, "estado_tipo": "A"}

    def movimientos_asiento(self, conn, asiento):
        datos = self.state["asientos"][asiento - 1]
        arqueos = {
            "AjusteFaltante": (2, 1),
            "AjusteSobrante": (1, 3),
            "ReposicionFaltante": (1, 2),
            "JustificaFaltante": (5, 2),
            "DescuentoFaltante": (4, 2),
        }
        if datos["tipo"] in arqueos:
            debe, haber = arqueos[datos["tipo"]]
        else:
            plantilla = self.plantilla_movimiento(
                conn, datos["agencia"], datos["tipo"], datos["naturaleza"]
            )
            debe, haber = plantilla["debito"], plantilla["credito"]
        codigos = {
            1: "110101",
            2: "160101",
            3: "290101",
            4: "250101",
            5: "450101",
            6: "190801",
            7: "110301",
        }
        return [
            {
                "tipo_movimiento": lado,
                "monto": datos["monto"],
                "id_cuenta_contable": cuenta,
                "codigo_cuenta": codigos[cuenta],
            }
            for lado, cuenta in (("DEBITO", debe), ("CREDITO", haber))
        ]

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
            "id_usuario_testigo": datos.get("testigo"),
            "estado": datos["estado"],
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

    def vincular_ajuste_arqueo(self, conn, i, ajuste):
        self.state["arqueos"][i]["id_movimiento_ajuste"] = ajuste

    def novedades_arqueos(self, conn, ids, ahora):
        return {
            i: {
                **n,
                "estado": "RESUELTA"
                if n["fecha_resolucion"] is not None
                else "VENCIDA"
                if n["fecha_vencimiento"] <= ahora
                else "PENDIENTE",
            }
            for i, n in self.state["novedades"].items()
            if i in ids
        }

    def crear_novedad(self, conn, datos):
        self.state["novedades"][datos["arqueo"]] = {
            "id_novedad": len(self.state["novedades"]) + 1,
            "id_usuario_responsable": datos["responsable"],
            "monto": datos["monto"],
            "fecha_vencimiento": datos["vence"],
            "id_asiento_contable": datos["asiento"],
            "tipo_resolucion": None,
            "fecha_resolucion": None,
            "id_usuario_resolucion": None,
            "referencia_resolucion": None,
            "observaciones_resolucion": None,
            "id_asiento_resolucion": None,
            "id_movimiento_reposicion": None,
        }

    def resolver_novedad(self, conn, datos):
        novedad = next(
            n
            for n in self.state["novedades"].values()
            if n["id_novedad"] == datos["id"]
        )
        novedad.update(
            tipo_resolucion=datos["tipo"],
            fecha_resolucion=datos["ahora"],
            id_usuario_resolucion=datos["actor"],
            referencia_resolucion=datos["referencia"],
            observaciones_resolucion=datos["observaciones"],
            id_asiento_resolucion=datos["asiento"],
            id_movimiento_reposicion=datos["movimiento"],
        )

    def arqueo_historico(self, cantidad=9):
        return self.crear_arqueo(
            self.conn,
            {
                "id_boveda": 1,
                "ahora": service.contabilidad.ahora_ecuador(),
                "tipo": "Sorpresivo",
                "actor": 7,
                "testigo": 12,
                "estado": "REGISTRADO",
                "observaciones": None,
                "teorico": Decimal(200),
                "fisico": Decimal(20) * cantidad,
                "corte": self.ultimo_movimiento(self.conn, 1),
            },
            [
                {
                    "id_denominacion": 1,
                    "cantidad": cantidad,
                    "cantidad_esperada": 10,
                    "valor": Decimal(20),
                }
            ],
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
            "desglose": [{"idDenominacion": 1, "cantidad": cantidad}],
            **extra,
        }

    def registrar_conteo(self, cantidad=10, **extra):
        return self.client.post(
            f"{BASE}/bovedas/1/arqueos", json=self.arqueo(cantidad, **extra)
        )

    def ejecutar(self, ruta, json, headers=None):
        """Ejercita las etapas físicas con usuarios distintos."""
        creada = self.client.post(
            ruta.replace("/movimientos", "/solicitudes-movimiento"),
            json=json,
            headers=headers,
        )
        if creada.status_code != 201:
            return creada
        datos = creada.json()
        if datos["estado"] == "RECIBIDO":
            return creada
        anterior = self.usuario
        try:
            self.usuario = replace(anterior, id_interno=9)
            ruta = f"{BASE}/solicitudes-movimiento/{datos['idSolicitudMovimiento']}"
            aprobada = self.client.post(f"{ruta}/aprobacion")
            if aprobada.status_code != 200:
                return aprobada
            documentos = {"numeroGuia": "GUIA1", "precinto": "PRECINTO1"}
            if datos["tipoMovimiento"] != "ProvisionExterna":
                despacho = self.client.post(f"{ruta}/despacho", json=documentos)
                if despacho.status_code != 200:
                    return despacho
            if datos["tipoMovimiento"] == "EnvioExcedente":
                return self.client.post(
                    f"{ruta}/cierre", json={"comprobanteBanco": "DEP1"}
                )
            self.usuario = replace(
                anterior,
                id_interno=10,
                id_agencia=datos["idAgenciaDestino"] or datos["idAgencia"],
            )
            return self.client.post(
                f"{ruta}/recepcion",
                json={"desglose": json["desglose"], **documentos},
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
            if (
                agencia is None or agencia in {s["id_agencia"], s["id_agencia_destino"]}
            )
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
            "id_agencia_destino": datos["agencia_destino"],
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

    def solicitud_resolver(
        self,
        conn,
        i,
        estado,
        actor,
        ahora,
        motivo,
        cuenta_transito=None,
        usa_version=None,
    ):
        self.state["solicitudes"][i].update(
            estado=estado,
            id_usuario_resolucion=actor,
            fecha_resolucion=ahora,
            motivo_resolucion=motivo,
            id_cuenta_transito=cuenta_transito,
            usa_plantilla_versionada=usa_version,
        )

    def solicitud_destinos(self, conn, origen):
        return [
            f
            for i, f in self.state["bovedas"].items()
            if i != origen and f["estado"] == "A"
        ]

    def solicitud_conteos(self, conn, ids):
        return {i: deepcopy(self.state["conteos_solicitudes"].get(i, [])) for i in ids}

    def solicitud_guardar_conteo(self, conn, i, detalle):
        self.state["conteos_solicitudes"][i] = deepcopy(detalle)

    def solicitud_cupo_ocupado(self, conn, agencia):
        return agencia in self.state["cupos_solicitudes"]

    def solicitud_reservar_cupo(self, conn, i, agencias):
        for agencia in agencias:
            assert agencia not in self.state["cupos_solicitudes"]
            self.state["cupos_solicitudes"][agencia] = i

    def solicitud_liberar_cupo(self, conn, i):
        self.state["cupos_solicitudes"] = {
            agencia: solicitud
            for agencia, solicitud in self.state["cupos_solicitudes"].items()
            if solicitud != i
        }

    def solicitud_anular(self, conn, i, actor, ahora, motivo):
        self.state["solicitudes"][i].update(
            estado="ANULADA",
            id_usuario_anulacion=actor,
            fecha_anulacion=ahora,
            motivo_anulacion=motivo,
        )

    def solicitud_despachar(self, conn, datos):
        self.state["solicitudes"][datos["solicitud"]].update(
            estado="DESPACHADO",
            id_usuario_despacho=datos["actor"],
            fecha_despacho=datos["ahora"],
            numero_guia=datos["guia"],
            precinto=datos["precinto"],
            id_asiento_despacho=datos["asiento"],
        )

    def solicitud_confirmar(self, conn, datos):
        fila = self.state["solicitudes"][datos["solicitud"]]
        fila.update(
            estado=datos["estado"],
            id_usuario_confirmacion=datos["actor"],
            fecha_confirmacion=datos["ahora"],
            monto_confirmado=datos["monto"],
            diferencia=datos["monto"] - fila["monto"],
            acta_novedad=datos["acta"],
            comprobante_banco=datos["comprobante"],
            id_asiento_confirmacion=datos["asiento"],
            id_asiento_novedad=datos["novedad"],
            numero_guia=fila.get("numero_guia") or datos["guia"],
            precinto=fila.get("precinto") or datos["precinto"],
        )

    def solicitud_vincular(self, conn, i, ids):
        for m in ids:
            self.state["movimientos"][m]["solicitud"] = i
            self.state["movimientos"][m]["id_solicitud_movimiento"] = i
