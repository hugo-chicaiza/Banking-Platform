"""E5-08: respaldos de una ficha existente. El contenido vive en MongoDB."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from pydantic import BaseModel, field_validator
from python_multipart.exceptions import MultipartParseError
from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import ClientDisconnect

from app.core.api.errors import RESPUESTAS_ERROR, ProblemDetailsRoute, problema
from app.core.api.middleware import ip_cliente
from app.core.config.settings import get_settings
from app.core.database.db import cooperativa, get_engine
from app.core.documentos import (
    ArchivoMuyGrande,
    ArchivoRechazado,
    ErrorDocumento,
    obtener_servicio,
    problema_documento,
    respuesta_documento,
    respuestas_documento,
)
from app.core.documentos.clamav import AnalisisNoDisponible, analizar_clamav
from app.core.security import audit
from app.core.security.auth import Usuario, require_permiso
from app.modules.clientes import repository
from app.modules.parametros import general
from app.modules.parametros.service import hoy

MAX_BYTES = 5 * 1024 * 1024
MAX_MULTIPART = MAX_BYTES + 32 * 1024
ORIGEN = "clientes"
ESTADO_LIMPIO = "Limpio"
Db = Annotated[Connection, Depends(cooperativa)]
IdCliente = Annotated[int, Path(gt=0, le=2**31 - 1)]
IdArchivo = Annotated[int, Path(gt=0, le=2**53 - 1)]
VerArchivos = Annotated[Usuario, Depends(require_permiso("cli-archivo-ver"))]
GestionarArchivos = Annotated[Usuario, Depends(require_permiso("cli-archivo"))]


def sin_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    route_class=ProblemDetailsRoute,
    dependencies=[Depends(sin_cache)],
    responses={
        **RESPUESTAS_ERROR,
        413: {**RESPUESTAS_ERROR[400], "description": "Archivo demasiado grande"},
        415: {**RESPUESTAS_ERROR[400], "description": "Tipo no permitido"},
    },
)


class ClaseArchivo(BaseModel):
    codigo: str
    nombre: str
    obligatorioNatural: bool
    obligatorioJuridico: bool


class Archivo(BaseModel):
    idArchivo: int
    claseDocumento: str
    nombreOriginal: str
    tipoContenido: Literal["application/pdf", "image/jpeg", "image/png"]
    tamanoBytes: int
    estadoAnalisis: Literal["Pendiente", "Limpio", "Rechazado"]
    version: int
    reemplazado: bool
    idArchivoAnterior: int | None
    fechaSubida: datetime

    @field_validator("fechaSubida")
    @classmethod
    def fecha_utc(cls, valor: datetime) -> datetime:
        return valor.replace(tzinfo=UTC) if valor.tzinfo is None else valor


class CatalogoArchivos(BaseModel):
    clases: list[ClaseArchivo]
    maxBytes: int


class ListadoArchivos(CatalogoArchivos):
    archivos: list[Archivo]


_ARCHIVO = text("""
    SELECT IdArchivo AS idArchivo, ClaseDocumento AS claseDocumento,
    NombreOriginal AS nombreOriginal, TipoContenido AS tipoContenido,
    TamanoBytes AS tamanoBytes, EstadoAnalisis AS estadoAnalisis,
    Version AS version, Reemplazado AS reemplazado,
    IdArchivoAnterior AS idArchivoAnterior, FechaSubida AS fechaSubida,
    ClaveAlmacenamiento AS clave FROM Clientes.ClienteArchivo
    WHERE IdArchivo=:archivo AND IdCliente=:cliente
""")
_LISTADO = text("""
    SELECT IdArchivo AS idArchivo, ClaseDocumento AS claseDocumento,
    NombreOriginal AS nombreOriginal, TipoContenido AS tipoContenido,
    TamanoBytes AS tamanoBytes, EstadoAnalisis AS estadoAnalisis,
    Version AS version, Reemplazado AS reemplazado,
    IdArchivoAnterior AS idArchivoAnterior, FechaSubida AS fechaSubida
    FROM Clientes.ClienteArchivo WHERE IdCliente=:cliente
    ORDER BY ClaseDocumento, Reemplazado, IdArchivo DESC
""")


def _cliente(conn: Connection, id_cliente: int, *, escribir: bool = False) -> None:
    cliente = (
        repository.bloquear_cliente(conn, id_cliente)
        if escribir
        else repository.obtener_cliente_por_id(conn, id_cliente)
    )
    if cliente is None:
        raise problema(404, "CLIENTE_NO_ENCONTRADO", "No se encontró el cliente.")
    if cliente["estado"] == "Eliminado":
        raise problema(409, "CLIENTE_ELIMINADO", "La ficha del cliente está eliminada.")


def _archivo(conn: Connection, cliente: int, archivo: int) -> dict[str, Any]:
    fila = (
        conn.execute(_ARCHIVO, {"cliente": cliente, "archivo": archivo})
        .mappings()
        .first()
    )
    if fila is None:
        raise problema(404, "DOCUMENTO_NO_ENCONTRADO", "El documento no existe.")
    return dict(fila)


def _limite(conn: Connection) -> int:
    limite = general.valor(conn, "CLI_ARCHIVO_MAX_BYTES", hoy())
    if type(limite) is not int or not 1 <= limite <= MAX_BYTES:
        raise problema(
            503, "PARAMETRO_INVALIDO", "No se pudo verificar el tamaño permitido."
        )
    return min(limite, get_settings().documentos_max_bytes)


def _catalogo(conn: Connection) -> CatalogoArchivos:
    filas = conn.execute(
        text("""
        SELECT Codigo AS codigo, Nombre AS nombre, ObligatorioNatural AS obligatorioNatural,
               ObligatorioJuridico AS obligatorioJuridico
        FROM Catalogo.ClaseDocumentoCliente WHERE Estado='A' ORDER BY Nombre
    """)
    ).mappings()
    return CatalogoArchivos(
        clases=[ClaseArchivo.model_validate(f) for f in filas], maxBytes=_limite(conn)
    )


class _CargaInvalida(MultiPartException):
    pass


class _CargaGrande(MultiPartException):
    pass


class _FormularioArchivo(MultiPartParser):
    # Los respaldos contienen datos personales. Mantener el tamaño acotado en memoria.
    spool_max_size = MAX_MULTIPART
    completo = False

    def on_end(self) -> None:
        self.completo = True
        super().on_end()


async def _flujo_limitado(request: Request) -> AsyncIterator[bytes]:
    total = 0
    try:
        async for fragmento in request.stream():
            total += len(fragmento)
            if total > MAX_MULTIPART:
                raise _CargaGrande("Tamaño máximo excedido")
            yield fragmento
    except ClientDisconnect as exc:
        raise _CargaInvalida("Carga desconectada") from exc


def _multipart_invalido() -> HTTPException:
    return problema(
        422, "CARGA_INVALIDA", "Selecciona un archivo y una clase de documento válidos."
    )


class CargaArchivo(BaseModel):
    clase: str
    nombre: str
    contenido: bytes
    reemplaza: int | None


async def recibir_archivo(
    request: Request, _usuario: GestionarArchivos
) -> CargaArchivo:
    if (
        request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        != "multipart/form-data"
    ):
        raise _multipart_invalido()
    parser = _FormularioArchivo(
        request.headers,
        _flujo_limitado(request),
        max_files=1,
        max_fields=2,
        max_part_size=256,
    )
    try:
        formulario = await parser.parse()
    except _CargaGrande:
        raise problema_documento(ArchivoMuyGrande()) from None
    except (MultiPartException, MultipartParseError):
        raise _multipart_invalido() from None
    try:
        campos = formulario.multi_items()
        if (
            not parser.completo
            or len(campos) != len(formulario)
            or not set(formulario).issubset(
                {"archivo", "claseDocumento", "reemplazarIdArchivo"}
            )
        ):
            raise _multipart_invalido()
        archivo = formulario.get("archivo")
        clase = formulario.get("claseDocumento")
        reemplaza = formulario.get("reemplazarIdArchivo")
        if (
            not isinstance(archivo, UploadFile)
            or not isinstance(clase, str)
            or not 0 < len(clase) <= 30
        ):
            raise _multipart_invalido()
        if reemplaza is not None and (
            not isinstance(reemplaza, str)
            or not reemplaza.isascii()
            or not reemplaza.isdecimal()
            or len(reemplaza) > 16
            or not 0 < int(reemplaza) <= 2**53 - 1
        ):
            raise _multipart_invalido()
        contenido = await archivo.read(MAX_BYTES + 1)
        if len(contenido) > MAX_BYTES:
            raise problema_documento(ArchivoMuyGrande())
        nombre = (archivo.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        nombre = "".join(c for c in nombre if c.isprintable()).strip()
        nombre = nombre.encode("utf-16-le")[:300].decode("utf-16-le", errors="ignore")
        if not contenido or not nombre:
            raise _multipart_invalido()
        return CargaArchivo(
            clase=clase,
            nombre=nombre,
            contenido=contenido,
            reemplaza=int(reemplaza) if reemplaza else None,
        )
    finally:
        await formulario.close()


def _auditar(
    evento: str,
    cliente: int,
    archivo: int | None,
    usuario: Usuario,
    request: Request,
    *,
    motivo: str | None = None,
    obligatorio: bool = False,
) -> None:
    datos = audit.EventoAuditoria(
        accion=evento,
        tabla="Clientes.ClienteArchivo",
        id_registro=str(archivo) if archivo is not None else None,
        resultado="Fallido" if motivo else "Exitoso",
        usuario=usuario.interno(),
        ip=ip_cliente(request.scope),
        descripcion=f"Cliente {cliente}" + (f"; motivo={motivo}" if motivo else ""),
        roles=usuario.roles_texto(),
        agencia=usuario.id_agencia,
        sesion=usuario.id_sesion,
        cambios={"idCliente": cliente, "idArchivo": archivo},
    )
    if obligatorio:
        try:
            with get_engine("seguridad").begin() as conn:
                audit.registrar_en_transaccion(conn, datos)
        except SQLAlchemyError:
            raise problema(
                503,
                "AUDITORIA_NO_DISPONIBLE",
                "No se pudo registrar la consulta del archivo.",
            ) from None
    else:
        audit.registrar(datos)


@router.get("/{idCliente}/archivos", operation_id="CLIArchivosListar")
def listar(idCliente: IdCliente, conn: Db, _usuario: VerArchivos) -> ListadoArchivos:
    _cliente(conn, idCliente)
    catalogo = _catalogo(conn)
    filas = conn.execute(_LISTADO, {"cliente": idCliente}).mappings()
    return ListadoArchivos(
        clases=catalogo.clases,
        maxBytes=catalogo.maxBytes,
        archivos=[Archivo.model_validate(f) for f in filas],
    )


@router.get("/{idCliente}/archivos/clases", operation_id="CLIArchivosClases")
def clases(
    idCliente: IdCliente, conn: Db, _usuario: GestionarArchivos
) -> CatalogoArchivos:
    _cliente(conn, idCliente)
    return _catalogo(conn)


@router.post(
    "/{idCliente}/archivos",
    operation_id="CLIArchivoSubir",
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["archivo", "claseDocumento"],
                        "properties": {
                            "archivo": {"type": "string", "format": "binary"},
                            "claseDocumento": {"type": "string"},
                            "reemplazarIdArchivo": {
                                "type": "integer",
                                "format": "int64",
                            },
                        },
                    }
                }
            },
        }
    },
)
def subir(
    idCliente: IdCliente,
    conn: Db,
    usuario: GestionarArchivos,
    request: Request,
    carga: Annotated[CargaArchivo, Depends(recibir_archivo)],
) -> Archivo:
    _cliente(conn, idCliente)
    try:
        if len(carga.contenido) > _limite(conn):
            raise ArchivoMuyGrande()
        almacenamiento = obtener_servicio()
        ref = almacenamiento.guardar(
            carga.contenido,
            origen=ORIGEN,
            analisis_adicional=analizar_clamav,
        )
    except AnalisisNoDisponible:
        raise problema(
            503,
            "ANALISIS_NO_DISPONIBLE",
            "No se pudo analizar el archivo. Inténtalo más tarde.",
        ) from None
    except ArchivoRechazado as exc:
        _auditar(
            "CLI_ARCHIVO_RECHAZADO",
            idCliente,
            None,
            usuario,
            request,
            motivo=exc.motivo or "RECHAZADO",
        )
        raise problema_documento(exc) from None
    except ErrorDocumento as exc:
        raise problema_documento(exc) from None

    # Serializa versiones y bajas por ficha. Si falla antes del commit, compensar
    # en MongoDB; un commit de resultado incierto lo resuelve la limpieza diferida.
    try:
        _cliente(conn, idCliente, escribir=True)
        clase = conn.execute(
            text("""
            SELECT Codigo FROM Catalogo.ClaseDocumentoCliente WITH (HOLDLOCK)
            WHERE Codigo=:clase AND Estado='A'
        """),
            {"clase": carga.clase},
        ).scalar_one_or_none()
        if clase is None:
            raise problema(
                422,
                "CLASE_ARCHIVO_INVALIDA",
                "La clase de documento no está disponible.",
            )
        version = 1
        if carga.reemplaza is not None:
            anterior = _archivo(conn, idCliente, carga.reemplaza)
            if anterior["reemplazado"] or anterior["claseDocumento"] != clase:
                raise problema(
                    409,
                    "ARCHIVO_NO_REEMPLAZABLE",
                    "El archivo cambió o pertenece a otra clase.",
                )
            version = anterior["version"] + 1
            conn.execute(
                text("""
                UPDATE Clientes.ClienteArchivo SET Reemplazado=1
                WHERE IdArchivo=:anterior AND IdCliente=:cliente
            """),
                {"anterior": carga.reemplaza, "cliente": idCliente},
            )
        id_archivo = conn.execute(
            text("""
            INSERT Clientes.ClienteArchivo
                (IdCliente,ClaseDocumento,ClaveAlmacenamiento,NombreOriginal,TipoContenido,
                 TamanoBytes,HashSha256,EstadoAnalisis,Version,IdArchivoAnterior,SubidoPor)
            OUTPUT inserted.IdArchivo
            VALUES (:cliente,:clase,:clave,:nombre,:tipo,:tamano,:hash,:estado,:version,:anterior,:usuario)
        """),
            {
                "cliente": idCliente,
                "clase": clase,
                "clave": ref.clave,
                "nombre": carga.nombre,
                "tipo": ref.tipo_contenido,
                "tamano": ref.tamano,
                "hash": bytes.fromhex(ref.sha256),
                "estado": ref.analisis,
                "version": version,
                "anterior": carga.reemplaza,
                "usuario": usuario.interno(),
            },
        ).scalar_one()
        archivo = Archivo.model_validate(_archivo(conn, idCliente, id_archivo))
    except Exception:
        try:
            conn.rollback()
        finally:
            almacenamiento.eliminar(ref.clave)
        raise
    conn.commit()
    _auditar("CLI_ARCHIVO_SUBIDO", idCliente, id_archivo, usuario, request)
    return archivo


@router.get(
    "/{idCliente}/archivos/{idArchivo}/contenido",
    operation_id="CLIArchivoContenido",
    responses=respuestas_documento("Archivo analizado, entregado como descarga."),
    response_class=Response,
)
def contenido(
    idCliente: IdCliente,
    idArchivo: IdArchivo,
    conn: Db,
    usuario: VerArchivos,
    request: Request,
) -> Response:
    _cliente(conn, idCliente)
    fila = _archivo(conn, idCliente, idArchivo)
    if fila["estadoAnalisis"] != ESTADO_LIMPIO:
        raise problema(
            409, "DOCUMENTO_NO_DISPONIBLE", "El archivo aún no está disponible."
        )
    try:
        documento = obtener_servicio().leer(fila["clave"])
    except ErrorDocumento as exc:
        raise problema_documento(exc) from None
    if documento.tipo_contenido != fila["tipoContenido"]:
        raise problema(
            503,
            "ALMACENAMIENTO_NO_DISPONIBLE",
            "No se pudo verificar el tipo del archivo.",
        )
    _auditar(
        "CLI_ARCHIVO_VISTO", idCliente, idArchivo, usuario, request, obligatorio=True
    )
    return respuesta_documento(documento, fila["nombreOriginal"])
