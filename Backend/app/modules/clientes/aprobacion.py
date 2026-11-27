"""E5-04: cambios sensibles del cliente aprobados por otra persona (cola E0-08)."""

import hashlib
import json
from datetime import date
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection

from app.core.api.errors import problema
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.clientes import (
    documentos_identidad,
    gestion_documentos,
    repository,
    service,
)
from app.modules.clientes.schemas import (
    CAMPOS_SENSIBLES,
    ConsultaDocumentoBody,
    ContenidoEdicion,
    DocumentoPrincipal,
)
from app.modules.parametros.service import hoy

CODIGO_EDICION = "CLI-EDITAR"
TIPO_OBJETIVO = "Cliente"


def objetivo(id_cliente: int) -> Objetivo:
    # Sin agencia: la regla de una solicitud pendiente es por cliente en toda la institución.
    return Objetivo(TIPO_OBJETIVO, str(id_cliente), None)


def _contenido(contenido: dict[str, Any]) -> ContenidoEdicion:
    try:
        return ContenidoEdicion.model_validate(contenido)
    except ValidationError:
        raise problema(
            422, "CONTENIDO_INVALIDO", "El cambio propuesto no cumple el contrato."
        ) from None


def _leer(conn: Connection, objetivo: Objetivo) -> dict[str, Any]:
    if not objetivo.id.isdigit() or objetivo.agencia is not None:
        raise problema(422, "OBJETIVO_INVALIDO", "Seleccione el cliente objetivo.")
    fila = repository.bloquear_datos_sensibles(conn, int(objetivo.id))
    if fila is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "No se encontró el cliente.")
    return fila


def _cambios(fila: dict[str, Any], datos: ContenidoEdicion) -> dict[str, Any]:
    return service.cambios_sensibles_efectivos(
        fila, datos.cambios.model_dump(exclude_unset=True)
    )


def _vista(fila: dict[str, Any], campos: set[str]) -> dict[str, Any]:
    return {_camel(c): service.texto_historial(fila[c]) for c in sorted(campos)}


def _camel(campo: str) -> str:
    primero, *resto = campo.split("_")
    return primero + "".join(p.capitalize() for p in resto)


class EdicionCliente:
    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan:
        datos = _contenido(contenido)
        fila = _leer(conn, objetivo)
        cambios = _cambios(fila, datos)
        if not cambios:
            raise problema(
                409, "SOLICITUD_DESACTUALIZADA", "Los datos ya tienen esos valores."
            )
        service.validar_cambios_sensibles(conn, fila, cambios, hoy)
        if {"identificacion", "tipo_documento"} & cambios.keys():
            raise problema(
                409,
                "USAR_GESTION_DOCUMENTOS",
                "Corrige la identificación desde Documentos.",
            )
        service.verificar_respaldo(
            conn, fila["id_cliente"], cambios, datos.id_archivo_respaldo, hoy
        )
        return Plan(
            service.congelar_contenido(datos),
            _vista(fila, set(cambios)),
            _vista(fila | cambios, set(cambios)),
            self.version(conn, objetivo),
        )

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        # Solo los sensibles y el estado: un cambio ordinario posterior no invalida la solicitud.
        fila = _leer(conn, objetivo)
        huella = {c: service.texto_historial(fila[c]) for c in CAMPOS_SENSIBLES}
        huella["estado"] = fila["estado"]
        return hashlib.sha256(json.dumps(huella, sort_keys=True).encode()).hexdigest()

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict[str, Any],
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        datos = _contenido(contenido)
        fila = _leer(conn, objetivo)
        cambios = _cambios(fila, datos)
        if not cambios:
            raise problema(
                409, "SOLICITUD_DESACTUALIZADA", "Los datos ya tienen esos valores."
            )
        service.validar_cambios_sensibles(conn, fila, cambios, hoy())
        motivo = f"Cambio aprobado (solicitud {id_solicitud})"
        if {"identificacion", "tipo_documento"} & cambios.keys():
            finales = fila | cambios
            tipo_documento = finales["tipo_documento"]
            if not isinstance(tipo_documento, str):
                raise problema(
                    409,
                    "SOLICITUD_DESACTUALIZADA",
                    "Revisa el tipo de documento desde la ficha.",
                )
            consulta = ConsultaDocumentoBody(
                tipo_documento=documentos_identidad.CODIGOS.get(
                    tipo_documento, tipo_documento
                ),
                numero=finales["identificacion"].upper(),
            )
            if consulta.tipo_documento == "PAS":
                raise problema(
                    409,
                    "SOLICITUD_DESACTUALIZADA",
                    "Registra el pasaporte con emisor y vencimiento desde Documentos.",
                )
            regla = documentos_identidad.validar(conn, consulta)
            if (
                not regla["Activo"]
                or not regla["PermitePrincipal"]
                or regla["RequiereVencimiento"]
            ):
                raise problema(
                    409,
                    "SOLICITUD_DESACTUALIZADA",
                    "Revisa las reglas actuales del documento.",
                )
            documentos_identidad.bloquear_identidad(conn, consulta)
            candidato = documentos_identidad.buscar(
                conn,
                consulta,
                hoy(),
                requiere_vencimiento=regla["RequiereVencimiento"],
            )
            if candidato.existe and candidato.id_cliente != fila["id_cliente"]:
                raise problema(
                    409, "DOCUMENTO_DUPLICADO", "El documento requiere revisión."
                )
            disponible = next(
                (
                    item
                    for item in gestion_documentos._documentos(conn, fila["id_cliente"])
                    if item["tipo_documento"] == consulta.tipo_documento
                    and item["numero"] == consulta.numero
                ),
                None,
            )
            id_documento = (
                disponible["id_documento"]
                if disponible
                else documentos_identidad.insertar(
                    conn,
                    fila["id_cliente"],
                    consulta,
                    None,
                    None,
                    principal=False,
                )
            )
            destino = gestion_documentos._leer(conn, fila["id_cliente"], id_documento)
            gestion_documentos.aplicar_principal(
                conn,
                fila["id_cliente"],
                id_documento,
                DocumentoPrincipal(
                    version=destino["version"], motivo=motivo, anular_anterior=True
                ),
                hoy(),
                datos.modificado_por,
                datos.direccion_ip,
                id_solicitud,
            )
            cambios = {
                k: v
                for k, v in cambios.items()
                if k not in {"identificacion", "tipo_documento"}
            }
            if not cambios:
                return

        historial = [
            (
                repository.CAMPOS_SENSIBLES_CLIENTE[campo],
                repository.observaciones_cambio(
                    service.texto_historial(fila[campo]),
                    service.texto_historial(valor),
                    motivo,
                ),
                service.texto_historial(fila[campo]),
                service.texto_historial(valor),
            )
            for campo, valor in cambios.items()
        ]
        repository.actualizar_cliente_sensible(conn, fila["id_cliente"], cambios)
        for campo, observaciones, anterior, nuevo in historial:
            repository.insertar_historial_cliente(
                conn,
                id_cliente=fila["id_cliente"],
                tipo_operacion="U",
                campo=campo,
                modificado_por=datos.modificado_por,
                direccion_ip=datos.direccion_ip,
                observaciones=observaciones,
                valor_anterior=anterior,
                valor_nuevo=nuevo,
                id_solicitud=id_solicitud,
            )


OPERACION_EDICION = Operacion(
    CODIGO_EDICION,
    TIPO_OBJETIVO,
    "cooperativa",
    frozenset({"ADMIN", "ASESOR"}),
    "clientes:aprobar",
    EdicionCliente(),
    tabla_auditada="Clientes.Cliente",
    evento_ejecucion="CLI_CAMBIO_SENSIBLE",
    solicitud_directa=False,
)
