from datetime import date
from hashlib import sha256
from typing import Any

from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.clientes import gestion_documentos as documentos
from app.modules.clientes.schemas import DocumentoPrincipal, TipoDocumentoEscritura
from app.modules.parametros.service import hoy

CLI = "CLI-DOCUMENTO"
CAT = "CAT-EDITAR-DOCUMENTO"


class Principal:
    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        cliente = int(objetivo.id)
        documentos._cliente_editable(conn, cliente)
        filas = documentos._documentos(conn, cliente)
        return sha256(
            "|".join(
                f"{fila['id_documento']}:{fila['version']}" for fila in filas
            ).encode()
        ).hexdigest()

    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan:
        datos = DocumentoPrincipal.model_validate(contenido["cambio"])
        cliente, id_documento = int(objetivo.id), contenido["documento"]
        documentos.validar_principal(conn, cliente, id_documento, datos, hoy)
        return Plan(
            contenido,
            {},
            {
                "idDocumentoPrincipal": id_documento,
                "anularAnterior": datos.anular_anterior,
            },
            self.version(conn, objetivo),
        )

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict[str, Any],
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        documentos.aplicar_principal(
            conn,
            int(objetivo.id),
            contenido["documento"],
            DocumentoPrincipal.model_validate(contenido["cambio"]),
            hoy(),
            contenido["actor"],
            contenido["ip"],
            id_solicitud,
        )


class Catalogo:
    def leer(self, conn: Connection, objetivo: Objetivo):
        return (
            conn.execute(
                text("""SELECT Nombre AS nombre, Algoritmo AS algoritmo,
                    PatronCaracteres AS patron_caracteres, LongitudMinima AS longitud_minima,
                    LongitudMaxima AS longitud_maxima, AplicaNatural AS aplica_natural,
                    AplicaJuridico AS aplica_juridico, RequierePais AS requiere_pais,
                    RequiereVencimiento AS requiere_vencimiento,
                    DigitoVerificadorBloquea AS digito_verificador_bloquea,
                    PermitePrincipal AS permite_principal, AccionAlVencer AS accion_al_vencer,
                    Activo AS activo, CONVERT(varchar(16), Version, 2) AS version
                    FROM Catalogo.TipoDocumentoIdentidad WITH (UPDLOCK, HOLDLOCK)
                    WHERE Codigo = :codigo"""),
                {"codigo": objetivo.id},
            )
            .mappings()
            .first()
        )

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        fila = self.leer(conn, objetivo)
        return fila["version"] if fila else "nuevo"

    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict[str, Any], hoy: date
    ) -> Plan:
        if (
            not objetivo.id.isascii()
            or not objetivo.id.isalnum()
            or objetivo.id != objetivo.id.upper()
            or objetivo.id in {"C", "R", "P"}
        ):
            raise problema(422, "REGLAS_INVALIDAS", "Usa un código de tipo válido.")
        datos = TipoDocumentoEscritura.model_validate(contenido)
        fila = self.leer(conn, objetivo)
        actual = fila["version"] if fila else None
        if (datos.version.upper() if datos.version else None) != actual:
            raise problema(
                409, "SOLICITUD_DESACTUALIZADA", "Recarga el tipo de documento."
            )
        if datos.longitud_minima > datos.longitud_maxima or not (
            datos.aplica_natural or datos.aplica_juridico
        ):
            raise problema(
                422, "REGLAS_INVALIDAS", "Revisa los límites y titulares admitidos."
            )
        if objetivo.id == "PAS" and not (
            datos.requiere_pais and datos.requiere_vencimiento
        ):
            raise problema(
                422,
                "REGLAS_INVALIDAS",
                "El pasaporte requiere país emisor y vencimiento.",
            )
        campos = datos.model_dump(exclude={"motivo", "version"})
        if fila and any(
            fila[c] != campos[c]
            for c in (
                "algoritmo",
                "patron_caracteres",
                "longitud_minima",
                "longitud_maxima",
            )
        ):
            usado = conn.execute(
                text(
                    "SELECT TOP (1) 1 FROM Clientes.ClienteDocumento WHERE TipoDocumento = :codigo"
                ),
                {"codigo": objetivo.id},
            ).scalar()
            if usado:
                raise problema(
                    409,
                    "TIPO_EN_USO",
                    "Conserva el formato de los documentos ya registrados.",
                )
        return Plan(contenido, dict(fila) if fila else {}, campos, actual or "nuevo")

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict[str, Any],
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        plan = self.preparar(conn, objetivo, contenido, hoy())
        if plan.antes:
            sql = """UPDATE Catalogo.TipoDocumentoIdentidad
                SET Nombre=:nombre, Algoritmo=:algoritmo, PatronCaracteres=:patron_caracteres,
                    LongitudMinima=:longitud_minima, LongitudMaxima=:longitud_maxima,
                    AplicaNatural=:aplica_natural, AplicaJuridico=:aplica_juridico,
                    RequierePais=:requiere_pais, RequiereVencimiento=:requiere_vencimiento,
                    DigitoVerificadorBloquea=:digito_verificador_bloquea,
                    PermitePrincipal=:permite_principal, AccionAlVencer=:accion_al_vencer,
                    Activo=:activo
                WHERE Codigo=:codigo"""
        else:
            sql = """INSERT INTO Catalogo.TipoDocumentoIdentidad (
                    Codigo, Nombre, Algoritmo, PatronCaracteres, LongitudMinima, LongitudMaxima,
                    AplicaNatural, AplicaJuridico, RequierePais, RequiereVencimiento,
                    DigitoVerificadorBloquea, PermitePrincipal, AccionAlVencer, Activo
                ) VALUES (
                    :codigo, :nombre, :algoritmo, :patron_caracteres, :longitud_minima, :longitud_maxima,
                    :aplica_natural, :aplica_juridico, :requiere_pais, :requiere_vencimiento,
                    :digito_verificador_bloquea, :permite_principal, :accion_al_vencer, :activo
                )"""
        conn.execute(text(sql), {"codigo": objetivo.id, **plan.despues})


OPERACION_DOCUMENTOS = Operacion(
    CLI,
    "ClienteDocumento",
    "cooperativa",
    frozenset({"ADMIN", "ASESOR"}),
    "clientes:aprobar",
    Principal(),
    tabla_auditada="Clientes.ClienteDocumento",
    solicitud_directa=False,
)
OPERACION_CATALOGO_DOCUMENTOS = Operacion(
    CAT,
    "TipoDocumentoIdentidad",
    "cooperativa",
    frozenset({"ADMIN"}),
    "parametros:aprobar",
    Catalogo(),
    tabla_auditada="Catalogo.TipoDocumentoIdentidad",
    solicitud_directa=False,
)
