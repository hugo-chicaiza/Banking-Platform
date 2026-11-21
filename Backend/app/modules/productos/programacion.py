"""E3-03: planes inmutables y aplicacion transaccional por la cola E0-08."""

import hashlib
import json
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Connection, Engine, text

from app.core.api.errors import problema
from app.integrations.workos_client import get_organizacion_id
from app.modules.aprobaciones.congelacion import verificar
from app.modules.aprobaciones.motores import motor
from app.modules.aprobaciones.registro import Objetivo, Operacion, Plan
from app.modules.parametros.service import hoy
from app.modules.productos.programacion_schemas import (
    Cambio,
    CondicionNueva,
    CuposNuevos,
    FinRestriccion,
    RestriccionNueva,
)

CODIGO = "PRD-CONDICION"
# Identificadores SQL internos cerrados; ningun nombre proviene del payload.
TABLAS = {
    "condiciones": (
        "ProductosFinancieros.SubProductoCondicion",
        "IdCondicion",
        "Estado",
        ("Vigente", "Programada"),
    ),
    "cupos": (
        "ProductosFinancieros.ProductoCanalCupo",
        "IdProductoCanalCupo",
        "EstadoCupo",
        ("A",),
    ),
    "restricciones": (
        "ProductosFinancieros.ProductoRestriccion",
        "IdRestriccion",
        "Estado",
        ("A",),
    ),
}
MODELOS = {
    "condiciones": CondicionNueva,
    "cupos": CuposNuevos,
    "restricciones": RestriccionNueva,
}


def sentencia(clase: str, plantilla: str):
    if clase not in TABLAS:
        raise problema(422, "CLASE_INVALIDA", "La clase de conjunto no existe.")
    tabla, llave, estado, _ = TABLAS[clase]
    return text(plantilla.format(tabla=tabla, llave=llave, estado=estado))


def normalizar(valor: Any) -> Any:
    return json.loads(json.dumps(valor, default=str, sort_keys=True))


def fecha(valor: Any) -> date:
    return valor if isinstance(valor, date) else date.fromisoformat(valor)


def vigente(fila: dict, clase: str) -> bool:
    return fila[TABLAS[clase][2]] in TABLAS[clase][3]


def particion(fila: dict, clase: str) -> Any:
    if clase == "cupos":
        return fila["IdCanal"]
    if clase == "restricciones":
        if fila["TipoRestriccion"] == "SIN_RETIROS" and fila.get("Dias") is not None:
            return "SIN_RETIROS_DIAS"
        return fila["TipoRestriccion"]
    return None


def subproducto(conn: Connection, id_sub: int, permitir_retirado: bool = False) -> dict:
    fila = (
        conn.execute(
            text(
                "SELECT s.*,p.TipoProducto,p.NombreProducto FROM ProductosFinancieros.SubProducto s WITH(UPDLOCK,HOLDLOCK) JOIN ProductosFinancieros.Producto p ON p.IdProducto=s.IdProducto WHERE s.IdSubProducto=:id"
            ),
            {"id": id_sub},
        )
        .mappings()
        .first()
    )
    if fila is None:
        raise problema(404, "SUBPRODUCTO_NO_ENCONTRADO", "El subproducto no existe.")
    if fila["EstadoSubProducto"] == "Retirado" and not permitir_retirado:
        raise problema(
            409,
            "PRODUCTO_RETIRADO",
            "No se programan cambios de un subproducto retirado.",
        )
    return dict(fila)


def filas(conn: Connection, clase: str, id_sub: int) -> list[dict]:
    return [
        dict(v)
        for v in conn.execute(
            sentencia(
                clase,
                "SELECT * FROM {tabla} WITH(UPDLOCK,HOLDLOCK) WHERE IdSubProducto=:id ORDER BY {llave}",
            ),
            {"id": id_sub},
        ).mappings()
    ]


def historia(conn: Connection, id_sub: int, permitir_retirado: bool = False) -> dict:
    subproducto(conn, id_sub, permitir_retirado)
    return {clase: filas(conn, clase, id_sub) for clase in TABLAS}


def id_subproducto(objetivo: Objetivo) -> int:
    if (
        objetivo.tipo != "SubProducto"
        or objetivo.agencia is not None
        or not objetivo.id.isascii()
        or not objetivo.id.isdecimal()
    ):
        raise problema(
            422,
            "OBJETIVO_INVALIDO",
            "Seleccione el subproducto del catalogo institucional.",
        )
    id_ = int(objetivo.id)
    if not 1 <= id_ <= 2147483647:
        raise problema(422, "OBJETIVO_INVALIDO", "El identificador no es valido.")
    return id_


def validar_cupos(cupos) -> None:
    if any(
        c.monto_max_transaccion > c.cupo_diario_maximo
        or c.cupo_diario_maximo > c.cupo_mensual_maximo
        for c in cupos
    ):
        raise problema(
            422,
            "CUPOS_INCOHERENTES",
            "El maximo por transaccion no puede superar el diario ni este el mensual.",
        )


class Programador:
    def __init__(
        self, seguridad: Engine | None = None, organizacion: str | None = None
    ):
        self.seguridad = seguridad
        self.organizacion = organizacion

    def version(self, conn: Connection, objetivo: Objetivo) -> str:
        id_sub = id_subproducto(objetivo)
        datos = {"subproducto": subproducto(conn, id_sub), **historia(conn, id_sub)}
        return hashlib.sha256(
            json.dumps(
                normalizar(datos), sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()

    def origen(self, id_solicitud: int | None, id_sub: int) -> dict:
        if id_solicitud is None:
            raise problema(
                409,
                "PROGRAMACION_SIN_TRAZABILIDAD",
                "La programacion anterior no tiene una solicitud verificable.",
            )
        with (self.seguridad or motor("seguridad")).connect() as seg:
            fila = (
                seg.execute(
                    text(
                        "SELECT Contenido,HashContenido FROM Seguridad.SolicitudAprobacion WHERE IdSolicitud=:id AND IdOrganizacion=:org AND CodigoTransaccion=:codigo AND TipoObjetivo='SubProducto' AND IdObjetivo=:sub AND Estado IN ('Ejecutada','Aprobada')"
                    ),
                    {
                        "id": id_solicitud,
                        "org": self.organizacion or get_organizacion_id(),
                        "codigo": CODIGO,
                        "sub": str(id_sub),
                    },
                )
                .mappings()
                .first()
            )
        if fila is None:
            raise problema(
                409,
                "PROGRAMACION_SIN_TRAZABILIDAD",
                "La solicitud original no esta disponible en este alcance.",
            )
        return verificar(fila["Contenido"], bytes(fila["HashContenido"]))["cambio"]

    def preparar(
        self, conn: Connection, objetivo: Objetivo, contenido: dict, hoy: date
    ) -> Plan:
        id_sub = id_subproducto(objetivo)
        sub = subproducto(conn, id_sub)
        try:
            cambio = Cambio.model_validate(contenido)
        except ValidationError:
            raise problema(
                422,
                "CONTENIDO_INVALIDO",
                "El cambio no cumple el contrato de programacion.",
            ) from None
        clase = cambio.clase
        if clase == "cupos" and sub["TipoProducto"] not in ("Cuenta", "Tarjeta"):
            raise problema(
                422,
                "TIPO_PRODUCTO_INVALIDO",
                "Este tipo de producto no tiene cupos por canal.",
            )
        if clase == "restricciones" and sub["TipoProducto"] != "Cuenta":
            raise problema(
                422,
                "TIPO_PRODUCTO_INVALIDO",
                "Las restricciones corresponden a productos de cuenta.",
            )
        actuales = filas(conn, clase, id_sub)
        if cambio.accion == "programar":
            plan = self._programar(conn, cambio, actuales, hoy)
        elif cambio.accion == "cancelar":
            plan = self._cancelar(cambio, actuales, id_sub, hoy)
        else:
            plan = self._fin(cambio, actuales, hoy)
        return Plan(
            normalizar(plan),
            {
                "clase": clase,
                "subproducto": {
                    "nombre": sub["NombreSubProducto"],
                    "producto": sub["NombreProducto"],
                },
                "registros": normalizar(actuales),
            },
            {
                "clase": clase,
                "subproducto": {
                    "nombre": sub["NombreSubProducto"],
                    "producto": sub["NombreProducto"],
                },
                "propuesta": normalizar(plan),
            },
            self.version(conn, objetivo),
        )

    def _programar(self, conn, cambio, actuales, hoy):
        try:
            datos = MODELOS[cambio.clase].model_validate(cambio.datos)
        except ValidationError:
            raise problema(
                422,
                "CONTENIDO_INVALIDO",
                "Revise los tipos, rangos y fechas del conjunto.",
            ) from None
        if datos.vigencia_desde < hoy:
            raise problema(
                422, "VIGENCIA_PASADA", "La programacion no puede iniciar en el pasado."
            )
        if cambio.clase == "cupos":
            validar_cupos(datos.cupos)
            canales = set(
                conn.execute(
                    text("SELECT IdCanal FROM Canal.Canal WHERE Estado='A'")
                ).scalars()
            )
            if {c.id_canal for c in datos.cupos} - canales:
                raise problema(
                    422, "CANAL_NO_EXISTE", "Hay canales inexistentes o inactivos."
                )
            particiones = {c.id_canal for c in datos.cupos} | {
                particion(v, "cupos") for v in actuales if vigente(v, "cupos")
            }
        elif cambio.clase == "restricciones":
            tipo = (
                conn.execute(
                    text(
                        "SELECT UsaDias,UsaMonto,UsaCantidad FROM ProductosFinancieros.TipoRestriccion WHERE Codigo=:tipo"
                    ),
                    {"tipo": datos.tipo_restriccion},
                )
                .mappings()
                .first()
            )
            if (
                tipo is None
                or any(
                    bool(tipo[usa]) != (getattr(datos, campo) is not None)
                    for usa, campo in [
                        ("UsaDias", "dias"),
                        ("UsaMonto", "monto"),
                        ("UsaCantidad", "cantidad"),
                    ]
                )
                or (datos.monto is not None and datos.monto <= 0)
            ):
                raise problema(
                    422,
                    "RESTRICCION_INVALIDA",
                    "Los valores no corresponden al tipo de restriccion.",
                )
            particiones = {datos.tipo_restriccion}
        else:
            particiones = {None}
        anteriores = []
        for v in actuales:
            if (
                not vigente(v, cambio.clase)
                or particion(v, cambio.clase) not in particiones
            ):
                continue
            desde, hasta = fecha(v["VigenciaDesde"]), v["VigenciaHasta"]
            if hasta is not None and fecha(hasta) < datos.vigencia_desde:
                continue
            if datos.vigencia_hasta is not None and desde > datos.vigencia_hasta:
                continue
            # Un vigente puede ser sucedido; un futuro ya aprobado no se pisa.
            if desde > hoy and desde >= datos.vigencia_desde:
                raise problema(
                    422,
                    "VIGENCIA_SOLAPADA",
                    "El intervalo coincide con un conjunto futuro ya programado.",
                )
            if desde >= datos.vigencia_desde and desde != hoy:
                raise problema(
                    422, "VIGENCIA_SOLAPADA", "Existe un conjunto con el mismo inicio."
                )
            if desde <= datos.vigencia_desde:
                anteriores.append(v)
        return {
            "clase": cambio.clase,
            "accion": "programar",
            "datos": datos.model_dump(mode="json", by_alias=True),
            "_previos": normalizar(anteriores),
        }

    def _cancelar(self, cambio, actuales, id_sub, hoy):
        clase = cambio.clase
        llave = TABLAS[clase][1]
        if cambio.id_programacion:
            id_origen = cambio.id_programacion
            original = self.origen(cambio.id_programacion, id_sub)
            objetivos = [
                v for v in actuales if v["IdSolicitud"] == cambio.id_programacion
            ]
        else:
            objetivo = next(
                (v for v in actuales if v[llave] == cambio.id_registro), None
            )
            if objetivo is None:
                raise problema(
                    404,
                    "CONJUNTO_NO_ENCONTRADO",
                    "El conjunto no existe en este subproducto.",
                )
            original = self.origen(objetivo["IdSolicitud"], id_sub)
            id_origen = objetivo["IdSolicitud"]
            objetivos = [
                v for v in actuales if v["IdSolicitud"] == objetivo["IdSolicitud"]
            ]
        if original.get("clase") != clase or original.get("accion") != "programar":
            raise problema(
                409,
                "PROGRAMACION_NO_CANCELABLE",
                "La solicitud no es una programacion de este tipo.",
            )
        if fecha(original["datos"]["vigenciaDesde"]) <= hoy:
            raise problema(
                409,
                "CONJUNTO_YA_VIGENTE",
                "Solo se cancelan programaciones antes de su inicio.",
            )
        if objetivos and not any(vigente(v, clase) for v in objetivos):
            raise problema(409, "CONJUNTO_CANCELADO", "El conjunto ya esta cancelado.")
        # Un lote sin canales tambien es una programacion: su cancelacion no
        # deja filas nuevas. Se verifica el historial inmutable de la cola.
        with (self.seguridad or motor("seguridad")).connect() as seg:
            cancelaciones = (
                seg.execute(
                    text(
                        "SELECT Contenido,HashContenido FROM Seguridad.SolicitudAprobacion WHERE IdOrganizacion=:org AND CodigoTransaccion=:codigo AND TipoObjetivo='SubProducto' AND IdObjetivo=:sub AND Estado='Ejecutada'"
                    ),
                    {
                        "org": self.organizacion or get_organizacion_id(),
                        "codigo": CODIGO,
                        "sub": str(id_sub),
                    },
                )
                .mappings()
                .all()
            )
        for cancelacion in cancelaciones:
            plan = verificar(
                cancelacion["Contenido"], bytes(cancelacion["HashContenido"])
            )["cambio"]
            if plan.get("accion") == "cancelar" and plan.get("idOrigen") == id_origen:
                raise problema(
                    409, "CONJUNTO_CANCELADO", "El conjunto ya esta cancelado."
                )
        restaurar = []
        por_id = {v[llave]: v for v in actuales}
        pendientes = list(original["_previos"])
        incluidos = {v[llave] for v in pendientes}
        if clase == "cupos":
            # Una programacion que deshabilita todos los canales no inserta
            # filas. Si se cancelo antes un lote intermedio, la cola conserva
            # la preimagen necesaria para restaurar el antecesor sin inventar
            # una fila artificial ni perder su fecha final original.
            limite = fecha(original["datos"]["vigenciaDesde"]) - timedelta(days=1)
            for registro in cancelaciones:
                cancelado = verificar(
                    registro["Contenido"], bytes(registro["HashContenido"])
                )["cambio"]
                if cancelado.get("accion") != "cancelar" or not cancelado.get(
                    "idOrigen"
                ):
                    continue
                antecedente = self.origen(cancelado["idOrigen"], id_sub)
                if antecedente.get("clase") != clase:
                    continue
                for previo in antecedente["_previos"]:
                    actual = por_id.get(previo[llave])
                    if (
                        previo[llave] not in incluidos
                        and actual
                        and vigente(actual, clase)
                        and actual["VigenciaHasta"]
                        and fecha(actual["VigenciaHasta"]) == limite
                    ):
                        pendientes.append(previo)
                        incluidos.add(previo[llave])
        vistos = set()
        while pendientes:
            previo = pendientes.pop()
            id_ = previo[llave]
            if id_ in vistos:
                continue
            vistos.add(id_)
            if len(vistos) > 1000 or id_ not in por_id:
                raise problema(
                    409,
                    "TRAZABILIDAD_INVALIDA",
                    "La cadena de vigencias requiere revision.",
                )
            actual = por_id[id_]
            if vigente(actual, clase):
                posteriores = [
                    fecha(v["VigenciaDesde"])
                    for v in actuales
                    if vigente(v, clase)
                    and v not in objetivos
                    and v[llave] != id_
                    and particion(v, clase) == particion(actual, clase)
                    and fecha(v["VigenciaDesde"]) > fecha(actual["VigenciaDesde"])
                ]
                fin_original = (
                    fecha(previo["VigenciaHasta"]) if previo["VigenciaHasta"] else None
                )
                fin_siguiente = (
                    min(posteriores) - timedelta(days=1) if posteriores else None
                )
                fin = (
                    min(fin_original, fin_siguiente)
                    if fin_original and fin_siguiente
                    else fin_original or fin_siguiente
                )
                restaurar.append(
                    {"id": id_, "estado": previo[TABLAS[clase][2]], "hasta": fin}
                )
            else:
                origen = self.origen(actual["IdSolicitud"], id_sub)
                pendientes.extend(
                    p
                    for p in origen["_previos"]
                    if particion(p, clase) == particion(actual, clase)
                )
        return {
            "clase": clase,
            "accion": "cancelar",
            "idOrigen": id_origen,
            "ids": [v[llave] for v in objetivos],
            "_restaurar": normalizar(restaurar),
            "inicio": original["datos"]["vigenciaDesde"],
        }

    @staticmethod
    def _fin(cambio, actuales, hoy):
        if cambio.clase != "restricciones":
            raise problema(
                422, "ACCION_INVALIDA", "La finalizacion corresponde a una restriccion."
            )
        try:
            datos = FinRestriccion.model_validate(cambio.datos)
        except ValidationError:
            raise problema(
                422, "VIGENCIA_INVALIDA", "Indique una fecha final valida."
            ) from None
        objetivo = next(
            (
                v
                for v in actuales
                if v["IdRestriccion"] == cambio.id_registro
                and vigente(v, "restricciones")
            ),
            None,
        )
        if objetivo is None:
            raise problema(
                404, "CONJUNTO_NO_ENCONTRADO", "La restriccion no esta activa."
            )
        if datos.vigencia_hasta < hoy or datos.vigencia_hasta < fecha(
            objetivo["VigenciaDesde"]
        ):
            raise problema(
                422, "VIGENCIA_PASADA", "No se cambia una vigencia historica."
            )
        if objetivo["VigenciaHasta"] and datos.vigencia_hasta > fecha(
            objetivo["VigenciaHasta"]
        ):
            raise problema(
                422,
                "VIGENCIA_INVALIDA",
                "La finalizacion no puede ampliar el periodo registrado.",
            )
        return {
            "clase": "restricciones",
            "accion": "fin",
            "id": cambio.id_registro,
            "hasta": datos.vigencia_hasta.isoformat(),
        }

    def aplicar(
        self,
        conn: Connection,
        objetivo: Objetivo,
        contenido: dict,
        solicitante: str,
        id_solicitud: int,
    ) -> None:
        id_sub = id_subproducto(objetivo)
        subproducto(conn, id_sub)
        clase, accion = contenido["clase"], contenido["accion"]
        if accion == "fin":
            if fecha(contenido["hasta"]) < hoy():
                raise problema(
                    409,
                    "VIGENCIA_PASADA",
                    "La fecha de finalizacion ya paso; registre otra solicitud.",
                )
            conn.execute(
                sentencia(
                    clase,
                    "UPDATE {tabla} SET VigenciaHasta=:hasta WHERE {llave}=:id AND IdSubProducto=:sub",
                ),
                {
                    "hasta": fecha(contenido["hasta"]),
                    "id": contenido["id"],
                    "sub": id_sub,
                },
            )
            return
        if accion == "cancelar":
            if fecha(contenido["inicio"]) <= hoy():
                raise problema(
                    409,
                    "CONJUNTO_YA_VIGENTE",
                    "La programacion ya comenzo y no se cancela.",
                )
            for id_ in contenido["ids"]:
                conn.execute(
                    sentencia(
                        clase,
                        "UPDATE {tabla} SET {estado}=:estado WHERE {llave}=:id AND IdSubProducto=:sub",
                    ),
                    {
                        "estado": "Cancelada" if clase == "condiciones" else "I",
                        "id": id_,
                        "sub": id_sub,
                    },
                )
            for v in contenido["_restaurar"]:
                conn.execute(
                    sentencia(
                        clase,
                        "UPDATE {tabla} SET {estado}=:estado,VigenciaHasta=CAST(:hasta AS date) WHERE {llave}=:id AND IdSubProducto=:sub",
                    ),
                    {
                        "estado": v["estado"],
                        "hasta": v["hasta"],
                        "id": v["id"],
                        "sub": id_sub,
                    },
                )
            return
        datos = MODELOS[clase].model_validate(contenido["datos"])
        if datos.vigencia_desde < hoy():
            raise problema(
                409,
                "VIGENCIA_PASADA",
                "La fecha de inicio ya paso; registre otra propuesta.",
            )
        # Revalida reglas de negocio y canales en la misma transaccion de aplicacion.
        self._programar(
            conn,
            Cambio(clase=clase, accion="programar", datos=contenido["datos"]),
            filas(conn, clase, id_sub),
            hoy(),
        )
        for previo in contenido["_previos"]:
            if fecha(previo["VigenciaDesde"]) == datos.vigencia_desde:
                conn.execute(
                    sentencia(
                        clase, "UPDATE {tabla} SET {estado}=:estado WHERE {llave}=:id"
                    ),
                    {
                        "estado": "Reemplazada" if clase == "condiciones" else "I",
                        "id": previo[TABLAS[clase][1]],
                    },
                )
            else:
                conn.execute(
                    sentencia(
                        clase,
                        "UPDATE {tabla} SET VigenciaHasta=:hasta WHERE {llave}=:id",
                    ),
                    {
                        "hasta": datos.vigencia_desde - timedelta(days=1),
                        "id": previo[TABLAS[clase][1]],
                    },
                )
        if clase == "condiciones":
            with (self.seguridad or motor("seguridad")).connect() as seg:
                actor = seg.execute(
                    text(
                        "SELECT UsuarioID FROM Organizacion.Usuarios WHERE KeyUsuario=:actor AND Estado='Activo'"
                    ),
                    {"actor": solicitante},
                ).scalar_one()
            valores = datos.model_dump()
            conn.execute(
                text(
                    "INSERT ProductosFinancieros.SubProductoCondicion(IdSubProducto,MontoAperturaMinimo,SaldoMinimo,TasaInteresAnual,PeriodicidadInteres,CostoMantenimiento,PeriodicidadCosto,MesesInactividad,AplicaACuentasExistentes,VigenciaDesde,VigenciaHasta,Estado,IdSolicitud,CreadoPor) VALUES(:sub,:monto_apertura_minimo,:saldo_minimo,:tasa_interes_anual,:periodicidad_interes,:costo_mantenimiento,:periodicidad_costo,:meses_inactividad,:aplica_a_cuentas_existentes,:vigencia_desde,CAST(:vigencia_hasta AS date),:estado,:solicitud,:actor)"
                ),
                {
                    **valores,
                    "sub": id_sub,
                    "estado": "Programada"
                    if datos.vigencia_desde > hoy()
                    else "Vigente",
                    "solicitud": id_solicitud,
                    "actor": actor,
                },
            )
        elif clase == "cupos":
            for cupo in datos.cupos:
                conn.execute(
                    text(
                        "INSERT ProductosFinancieros.ProductoCanalCupo(IdSubProducto,IdCanal,CupoDiarioMaximo,CupoMensualMaximo,MontoMaxTransaccion,MaxTransaccionesDia,VigenciaDesde,VigenciaHasta,EstadoCupo,IdSolicitud) VALUES(:sub,:id_canal,:cupo_diario_maximo,:cupo_mensual_maximo,:monto_max_transaccion,:max_transacciones_dia,:desde,CAST(:hasta AS date),'A',:solicitud)"
                    ),
                    {
                        **cupo.model_dump(),
                        "sub": id_sub,
                        "desde": datos.vigencia_desde,
                        "hasta": datos.vigencia_hasta,
                        "solicitud": id_solicitud,
                    },
                )
        else:
            with (self.seguridad or motor("seguridad")).connect() as seg:
                actor = seg.execute(
                    text(
                        "SELECT UsuarioID FROM Organizacion.Usuarios WHERE KeyUsuario=:actor AND Estado='Activo'"
                    ),
                    {"actor": solicitante},
                ).scalar_one()
            conn.execute(
                text(
                    "INSERT ProductosFinancieros.ProductoRestriccion(IdSubProducto,TipoRestriccion,Dias,Monto,Cantidad,Descripcion,VigenciaDesde,VigenciaHasta,Estado,RegistradoPor,IdSolicitud) VALUES(:sub,:tipo_restriccion,:dias,:monto,:cantidad,:descripcion,:vigencia_desde,CAST(:vigencia_hasta AS date),'A',:actor,:solicitud)"
                ),
                {
                    **datos.model_dump(),
                    "sub": id_sub,
                    "actor": actor,
                    "solicitud": id_solicitud,
                },
            )


def evento(cambio: dict[str, Any]) -> str:
    if cambio["accion"] == "cancelar":
        return "PRD_PROGRAMACION_CANCELADA"
    return {
        "condiciones": "PRD_CONDICION_PROGRAMADA",
        "cupos": "PRD_CUPO_PROGRAMADO",
        "restricciones": "PRD_RESTRICCION_PROGRAMADA",
    }[cambio["clase"]]


def operacion(manejador: Programador | None = None) -> Operacion:
    return Operacion(
        CODIGO,
        "SubProducto",
        "cooperativa",
        frozenset({"ADMIN"}),
        "productos:aprobar",
        manejador or Programador(),
        tabla_auditada="ProductosFinancieros.SubProducto",
        evento_ejecucion=evento,
        solicitud_directa=False,
        permiso_ejecucion="prd-condicion",
    )
