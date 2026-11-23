"""F-03 en todos los módulos: sesión obligatoria, roles de cada tarea y auditoría de
los accesos denegados.

Las rutas salen del OpenAPI de la app, así que una ruta nueva sin require_auth hace
fallar test_toda_ruta_de_la_api_exige_sesion.
"""

import re
from dataclasses import replace

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.core.database.db import cooperativa
from app.core.security.auth import ROLES, Usuario, require_auth
from app.core.security.permisos import PERMISOS
from app.main import app
from app.modules.tarjetas import router as tarjetas_router
from tests.sesion import USUARIO, simular_sesion, usuario_con_roles

CONSULTA_PRODUCTOS = PERMISOS["prd-consultar"]

AUTH = ()  # Cualquier usuario autenticado, sin rol específico
_PUBLICAS = {
    ("GET", "/api/v1/institucion"),  # #353: solo nombre/web, sin ficha legal ni sesión.
    ("GET", "/api/v1/auth/login"),
    ("GET", "/api/v1/auth/callback"),
    ("POST", "/api/v1/auth/logout"),  # AUT-03: idempotente, sin sesión responde 200
}
# ATM usa credencial de terminal y/o JWT propios, sin sesión WorkOS.
_TERMINALES = {
    ("POST", "/api/v1/atm/auth"),
    ("POST", "/api/v1/atm/logout"),
    ("POST", "/api/v1/atm/consulta-saldo"),
    ("POST", "/api/v1/atm/cambio-pin"),
    ("POST", "/api/v1/atm/transferencias"),
    ("POST", "/api/v1/atm/reversos"),
    ("POST", "/api/v1/atm/retiros"),
}
_VALORES_PATH = {
    "codigo_pais": "ECU",
    "clave": "PARAMETRO_QA",
    "fecha": "2026-11-04",
    "id_agencia": "002",
}

# Roles de cada tarea (GitHubProject_Files)
ROLES_POR_RUTA: dict[tuple[str, str], tuple[str, ...]] = {
    ("GET", "/api/v1/parametros"): AUTH,
    ("GET", "/api/v1/parametros/{clave}"): AUTH,
    ("POST", "/api/v1/parametros/{clave}/valores"): AUTH,
    ("DELETE", "/api/v1/parametros/{clave}/valores/{id_valor}"): AUTH,
    ("PATCH", "/api/v1/parametros/{clave}/valores/{id_valor}"): AUTH,
    # E0-08 usa permisos efectivos por operacion y propiedad; no un rol fijo.
    ("GET", "/api/v1/aprobaciones"): AUTH,
    ("POST", "/api/v1/aprobaciones"): AUTH,
    ("GET", "/api/v1/aprobaciones/accesos"): AUTH,
    ("GET", "/api/v1/aprobaciones/notificaciones"): AUTH,
    ("GET", "/api/v1/aprobaciones/{idSolicitud}"): AUTH,
    ("POST", "/api/v1/aprobaciones/{idSolicitud}/aprobar"): AUTH,
    ("POST", "/api/v1/aprobaciones/{idSolicitud}/rechazar"): AUTH,
    ("POST", "/api/v1/aprobaciones/{idSolicitud}/cancelar"): AUTH,
    ("POST", "/api/v1/boveda/bovedas/{idBoveda}/solicitudes-movimiento"): (
        "SUPERVISOR",
        "ADMIN",
    ),
    ("GET", "/api/v1/boveda/solicitudes-movimiento"): (
        "SUPERVISOR",
        "CONTADOR",
        "AUDITOR",
        "ADMIN",
    ),
    ("GET", "/api/v1/boveda/solicitudes-movimiento/{idSolicitudMovimiento}"): (
        "SUPERVISOR",
        "CONTADOR",
        "AUDITOR",
        "ADMIN",
    ),
    (
        "POST",
        "/api/v1/boveda/solicitudes-movimiento/{idSolicitudMovimiento}/aprobacion",
    ): ("SUPERVISOR", "ADMIN"),
    ("POST", "/api/v1/boveda/solicitudes-movimiento/{idSolicitudMovimiento}/rechazo"): (
        "SUPERVISOR",
        "ADMIN",
    ),
    (
        "POST",
        "/api/v1/boveda/solicitudes-movimiento/{idSolicitudMovimiento}/cancelacion",
    ): ("SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/parametros/comisiones"): ("ADMIN", "SUPERVISOR", "ASESOR"),
    ("GET", "/api/v1/parametros/comisiones/{idComision}/tarifa"): (
        "ADMIN",
        "SUPERVISOR",
        "ASESOR",
    ),
    ("POST", "/api/v1/parametros/comisiones"): ("ADMIN",),
    ("PATCH", "/api/v1/parametros/comisiones/{idComision}"): ("ADMIN",),
    ("GET", "/api/v1/parametros/exoneraciones"): ("ADMIN", "SUPERVISOR", "ASESOR"),
    ("POST", "/api/v1/parametros/exoneraciones"): ("ADMIN",),
    ("PATCH", "/api/v1/parametros/exoneraciones/{idExoneracion}"): ("ADMIN",),
    ("GET", "/api/v1/boveda/bovedas"): ("SUPERVISOR", "CONTADOR", "ADMIN"),
    ("GET", "/api/v1/boveda/bovedas/{idBoveda}"): ("SUPERVISOR", "CONTADOR", "ADMIN"),
    ("GET", "/api/v1/boveda/bovedas/{idBoveda}/movimientos"): (
        "SUPERVISOR",
        "CONTADOR",
        "AUDITOR",
        "ADMIN",
    ),
    ("POST", "/api/v1/boveda/bovedas/{idBoveda}/movimientos"): ("SUPERVISOR", "ADMIN"),
    ("POST", "/api/v1/boveda/bovedas/{idBoveda}/arqueos"): (
        "SUPERVISOR",
        "AUDITOR",
        "ADMIN",
    ),
    ("GET", "/api/v1/boveda/bovedas/{idBoveda}/arqueos"): (
        "SUPERVISOR",
        "CONTADOR",
        "AUDITOR",
        "ADMIN",
    ),
    ("POST", "/api/v1/boveda/arqueos/{idArqueoBoveda}/aprobacion"): (
        "SUPERVISOR",
        "ADMIN",
    ),
    ("GET", "/api/v1/auth/me"): AUTH,
    # AUT-05..09 (C-05): usuarios internos
    ("GET", "/api/v1/usuarios"): ("ADMIN",),
    ("POST", "/api/v1/usuarios"): ("ADMIN",),
    ("GET", "/api/v1/usuarios/{idUsuario}"): ("ADMIN",),
    ("PATCH", "/api/v1/usuarios/{idUsuario}"): ("ADMIN",),
    ("PUT", "/api/v1/usuarios/{idUsuario}/roles"): ("ADMIN",),
    **{
        ("GET", f"/api/v1/catalogos/{ruta}"): AUTH
        for ruta in (
            "paises",
            "paises/{codigo_pais}/ciudades",
            "redes",
            "sistemas-amortizacion",
            "tasas-interes",
            "comisiones",
            "seguros",
            "actividades-economicas",
            "tipos-antecedente",
            "denominaciones",
            "agencias",
            "productos",
            "canales",
            "tipos-credito",
            "tipos-movimiento-caja",
        )
    },
    ("POST", "/api/v1/contabilidad/cortes-e201"): ("CONTADOR",),
    ("GET", "/api/v1/contabilidad/cortes-e201/{id_plan}"): ("CONTADOR",),
    ("POST", "/api/v1/contabilidad/cortes-e201/{id_plan}/aprobaciones"): ("CONTADOR",),
    ("GET", "/api/v1/contabilidad/fechas-contables/actual"): AUTH,
    ("GET", "/api/v1/contabilidad/fechas-contables/{fecha}"): AUTH,
    ("GET", "/api/v1/contabilidad/cuentas-contables"): (
        "CONTADOR",
        "AUDITOR",
        "ADMIN",
    ),
    # #206: escritura del plan de cuentas, solo CONTADOR (el AUDITOR solo lee)
    ("POST", "/api/v1/contabilidad/cuentas-contables"): ("CONTADOR",),
    ("PATCH", "/api/v1/contabilidad/cuentas-contables/{idCuentaContable}"): (
        "CONTADOR",
    ),
    ("PATCH", "/api/v1/contabilidad/cuentas-contables/{idCuentaContable}/estado"): (
        "CONTADOR",
    ),
    ("DELETE", "/api/v1/contabilidad/cuentas-contables/{idCuentaContable}"): (
        "CONTADOR",
    ),
    ("GET", "/api/v1/contabilidad/asientos"): ("CONTADOR", "AUDITOR", "ADMIN"),
    ("GET", "/api/v1/contabilidad/asientos/{idAsiento}"): (
        "CONTADOR",
        "AUDITOR",
        "ADMIN",
    ),
    ("PATCH", "/api/v1/agencias/{id_agencia}/estado"): ("ADMIN",),
    ("GET", "/api/v1/organizacion/entidad"): ("ASESOR", "ADMIN"),
    ("POST", "/api/v1/organizacion/entidad"): ("ADMIN",),
    ("PATCH", "/api/v1/organizacion/entidad"): ("ADMIN",),
    ("GET", "/api/v1/clientes/validar-identificacion"): ("ASESOR", "ADMIN"),
    ("POST", "/api/v1/clientes"): ("ASESOR", "ADMIN"),
    ("GET", "/api/v1/clientes"): ("ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/clientes/{idCliente}"): (
        "ASESOR",
        "CAJERO",
        "SUPERVISOR",
        "ADMIN",
    ),
    ("PATCH", "/api/v1/clientes/{idCliente}"): ("ASESOR", "ADMIN"),
    ("PATCH", "/api/v1/clientes/{idCliente}/estado"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/clientes/{idCliente}/historial"): (
        "SUPERVISOR",
        "AUDITOR",
        "ADMIN",
    ),
    ("GET", "/api/v1/clientes/{idCliente}/perfil"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/clientes/{idCliente}/direcciones"): ("ASESOR", "ADMIN"),
    ("POST", "/api/v1/clientes/{idCliente}/direcciones"): ("ASESOR", "ADMIN"),
    ("PATCH", "/api/v1/clientes/{idCliente}/direcciones/{idDireccion}"): (
        "ASESOR",
        "ADMIN",
    ),
    ("DELETE", "/api/v1/clientes/{idCliente}/direcciones/{idDireccion}"): (
        "ASESOR",
        "ADMIN",
    ),
    ("POST", "/api/v1/clientes/{idCliente}/evaluaciones-riesgo"): (
        "ASESOR",
        "SUPERVISOR",
        "ADMIN",
    ),
    ("GET", "/api/v1/clientes/{idCliente}/evaluaciones-riesgo"): (
        "ASESOR",
        "SUPERVISOR",
        "AUDITOR",
        "ADMIN",
    ),
    ("GET", "/api/v1/creditos/tipos/{idTipoCredito}/condiciones"): ("ASESOR", "ADMIN"),
    ("POST", "/api/v1/creditos/simulaciones"): ("ASESOR", "ADMIN"),
    ("POST", "/api/v1/cuentas"): ("ASESOR", "ADMIN"),
    ("GET", "/api/v1/cuentas"): ("ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/cuentas/{idCuenta}"): ("ASESOR", "CAJERO", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/cuentas/{idCuenta}/saldo"): (
        "ASESOR",
        "CAJERO",
        "SUPERVISOR",
        "ADMIN",
    ),
    ("GET", "/api/v1/cuentas/{idCuenta}/movimientos"): (
        "ASESOR",
        "CAJERO",
        "SUPERVISOR",
        "ADMIN",
    ),
    ("PATCH", "/api/v1/cuentas/{idCuenta}/estado"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/cuentas/{idCuenta}/cupos"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("PUT", "/api/v1/cuentas/{idCuenta}/cupos/{idCanal}"): ("SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/cuentas/{idCuenta}/cupos/{idCanal}/historial"): (
        "SUPERVISOR",
        "AUDITOR",
        "ADMIN",
    ),
    ("POST", "/api/v1/tarjetas"): ("ASESOR", "ADMIN"),
    ("GET", "/api/v1/tarjetas"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("GET", "/api/v1/tarjetas/{idTarjeta}"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("POST", "/api/v1/tarjetas/{idTarjeta}/estado"): ("ASESOR", "SUPERVISOR", "ADMIN"),
    ("POST", "/api/v1/tarjetas/{idTarjeta}/pin"): ("ASESOR", "ADMIN"),
    ("GET", "/api/v1/tarjetas/{idTarjeta}/sobre-pin"): (
        "ASESOR",
        "SUPERVISOR",
        "ADMIN",
    ),
    ("POST", "/api/v1/pruebas/pin-block"): ("ADMIN",),
    ("GET", "/api/v1/tarjetas/{idTarjeta}/historial"): (
        "SUPERVISOR",
        "AUDITOR",
        "ADMIN",
    ),
    # CAJ-01: listado de cajas físicas
    ("GET", "/api/v1/caja/cajas-fisicas"): (
        "CAJERO",
        "SUPERVISOR",
        "ADMIN",
    ),
    # CAJ-02: consulta de jornadas
    ("GET", "/api/v1/caja/jornadas"): (
        "SUPERVISOR",
        "CONTADOR",
        "AUDITOR",
    ),
    # CAJ-05:
    ("GET", "/api/v1/caja/jornadas/{idJornada}"): (
        "CAJERO",
        "SUPERVISOR",
        "CONTADOR",
    ),
    # CAJ-08
    ("GET", "/api/v1/caja/jornadas/{idJornada}/dotaciones"): (
        "CAJERO",
        "SUPERVISOR",
        "CONTADOR",
    ),
    # CAJ-12
    ("GET", "/api/v1/caja/jornadas/{idJornada}/movimientos"): (
        "CAJERO",
        "SUPERVISOR",
        "CONTADOR",
    ),
    # CAJ-14
    ("GET", "/api/v1/caja/jornadas/{idJornada}/cuadre"): (
        "CAJERO",
        "SUPERVISOR",
        "CONTADOR",
    ),
    # TRX - 01
    ("GET", "/api/v1/transacciones"): (
        "SUPERVISOR",
        "AUDITOR",
        "CONTADOR",
        "ADMIN",
    ),
    # TRX - 02
    ("GET", "/api/v1/transacciones/{idTransaccion}"): (
        "SUPERVISOR",
        "AUDITOR",
        "CONTADOR",
        "ADMIN",
    ),
    # CAJ-06
    ("POST", "/api/v1/caja/jornadas/{idJornada}/cancelacion"): ("SUPERVISOR",),
    # CAJ-03
    ("POST", "/api/v1/caja/jornadas"): ("CAJERO",),
    # CAJ - 04
    ("GET", "/api/v1/caja/jornadas/actual"): ("CAJERO",),
    # CAJ - 07
    ("POST", "/api/v1/caja/jornadas/{idJornada}/dotaciones"): (
        "CAJERO",
        "SUPERVISOR",
    ),
    # CAJ - 13
    ("POST", "/api/v1/caja/jornadas/{idJornada}/cuadre"): ("CAJERO",),
    # CAJ - 16
    ("PUT", "/api/v1/caja/jornadas/{idJornada}/cuadre/conteo"): ("CAJERO",),
    # CAJ - 15
    ("POST", "/api/v1/caja/jornadas/{idJornada}/devoluciones"): (
        "CAJERO",
        "SUPERVISOR",
    ),
    # CAJ-17
    ("POST", "/api/v1/caja/jornadas/{idJornada}/cuadre/autorizacion"): ("SUPERVISOR",),
    # CAJ-18
    ("POST", "/api/v1/caja/jornadas/{idJornada}/cierre"): ("CAJERO",),
    # CAJ-09
    ("POST", "/api/v1/caja/jornadas/{idJornada}/depositos"): ("CAJERO",),
    # CAJ-10
    ("POST", "/api/v1/caja/depositos/{idTransaccion}/series"): ("CAJERO",),
    # CAJ - 11
    ("POST", "/api/v1/caja/jornadas/{idJornada}/retiros"): ("CAJERO",),
    # TRX - 03
    ("POST", "/api/v1/transacciones/{idTransaccion}/reverso"): ("SUPERVISOR",),
    # Agencias
    ("POST", "/api/v1/agencias"): ("ADMIN",),
    ("GET", "/api/v1/organizacion/agencias"): ("ADMIN",),
    ("GET", "/api/v1/seguridad/directorio-agencias"): ("ADMIN", "AUDITOR"),
    ("GET", "/api/v1/seguridad/directorio-usuarios"): ("ADMIN", "AUDITOR"),
    ("GET", "/api/v1/seguridad/matriz-roles"): ("ADMIN", "AUDITOR"),
    ("POST", "/api/v1/organizacion/agencias"): ("ADMIN",),
    ("GET", "/api/v1/organizacion/agencias/{id_agencia}"): ("ADMIN",),
    ("PATCH", "/api/v1/organizacion/agencias/{id_agencia}"): ("ADMIN",),
    ("PATCH", "/api/v1/organizacion/agencias/{id_agencia}/estado"): ("ADMIN",),
    ("GET", "/api/v1/agencias/{id_agencia}"): ("ADMIN",),
    ("PATCH", "/api/v1/agencias/{id_agencia}"): ("ADMIN",),
    # Productos: consultar exige prd-consultar (todos menos CAJERO en WorkOS); escribir prd-editar
    ("GET", "/api/v1/productos"): CONSULTA_PRODUCTOS,
    ("GET", "/api/v1/productos/subproductos/{id_sub}/numeracion"): CONSULTA_PRODUCTOS,
    # E3-05: cuentas contables de los productos
    ("GET", "/api/v1/contabilidad/cuentas-producto/clases"): CONSULTA_PRODUCTOS,
    (
        "GET",
        "/api/v1/contabilidad/cuentas-producto/tipos/{id_tipo}",
    ): CONSULTA_PRODUCTOS,
    (
        "GET",
        "/api/v1/contabilidad/cuentas-producto/subproductos/{id_sub}",
    ): CONSULTA_PRODUCTOS,
    ("PUT", "/api/v1/contabilidad/cuentas-producto/tipos/{id_tipo}"): ("CONTADOR",),
    ("PUT", "/api/v1/productos/subproductos/{id_sub}/numeracion"): ("ADMIN",),
    ("POST", "/api/v1/productos/subproductos/{id_sub}/numeracion/ejemplo"): ("ADMIN",),
    ("GET", "/api/v1/productos/subproductos/{id_sub}/vigencias"): CONSULTA_PRODUCTOS,
    ("GET", "/api/v1/productos/subproductos/{id_sub}/activacion"): CONSULTA_PRODUCTOS,
    ("GET", "/api/v1/productos/subproductos/{id_sub}/condiciones"): CONSULTA_PRODUCTOS,
    ("POST", "/api/v1/productos/subproductos/{id_sub}/condiciones"): ("ADMIN",),
    ("DELETE", "/api/v1/productos/subproductos/{id_sub}/condiciones/{id_registro}"): (
        "ADMIN",
    ),
    ("PATCH", "/api/v1/productos/subproductos/{id_sub}/condiciones/{id_registro}"): (
        "ADMIN",
    ),
    ("PATCH", "/api/v1/productos/subproductos/{id_sub}/cupos/{id_registro}"): (
        "ADMIN",
    ),
    ("POST", "/api/v1/productos/subproductos/{id_sub}/restricciones"): ("ADMIN",),
    ("DELETE", "/api/v1/productos/subproductos/{id_sub}/restricciones/{id_registro}"): (
        "ADMIN",
    ),
    ("PATCH", "/api/v1/productos/subproductos/{id_sub}/restricciones/{id_registro}"): (
        "ADMIN",
    ),
    (
        "POST",
        "/api/v1/productos/subproductos/{id_sub}/restricciones/{id_registro}/fin",
    ): ("ADMIN",),
    (
        "DELETE",
        "/api/v1/productos/subproductos/{id_sub}/cupos/programaciones/{id_programacion}",
    ): ("ADMIN",),
    ("GET", "/api/v1/productos/{id_producto}"): CONSULTA_PRODUCTOS,
    (
        "GET",
        "/api/v1/productos/subproductos/{id_sub_producto}/ficha/imprimible",
    ): CONSULTA_PRODUCTOS,
    ("GET", "/api/v1/productos/tipos"): CONSULTA_PRODUCTOS,
    ("DELETE", "/api/v1/productos/{id_producto}"): ("ADMIN",),
    (
        "GET",
        "/api/v1/productos/subproductos/{id_sub_producto}/ficha",
    ): CONSULTA_PRODUCTOS,
    ("POST", "/api/v1/productos"): ("ADMIN",),
    ("PATCH", "/api/v1/productos/{id_producto}"): ("ADMIN",),
    ("POST", "/api/v1/productos/{id_producto}/subproductos"): ("ADMIN",),
    ("PATCH", "/api/v1/productos/subproductos/{id_sub_producto}"): ("ADMIN",),
    (
        "GET",
        "/api/v1/productos/subproductos/{id_sub_producto}/cupos",
    ): CONSULTA_PRODUCTOS,
    ("PUT", "/api/v1/productos/subproductos/{id_sub_producto}/cupos"): ("ADMIN",),
    (
        "GET",
        "/api/v1/productos/subproductos/{id_sub_producto}/vinculos",
    ): CONSULTA_PRODUCTOS,
    ("PUT", "/api/v1/productos/subproductos/{id_sub_producto}/vinculos"): ("ADMIN",),
    ("GET", "/api/v1/productos/{id_producto}/vinculos"): CONSULTA_PRODUCTOS,
    ("PUT", "/api/v1/productos/{id_producto}/vinculos"): ("ADMIN",),
    (
        "GET",
        "/api/v1/productos/subproductos/{id_sub_producto}/restricciones",
    ): CONSULTA_PRODUCTOS,
    ("PUT", "/api/v1/productos/subproductos/{id_sub_producto}/restricciones"): (
        "ADMIN",
    ),
    ("POST", "/api/v1/catalogos/tasas-interes"): ("ADMIN",),
    ("GET", "/api/v1/catalogos/administracion"): ("ADMIN", "SUPERVISOR", "ASESOR"),
    ("GET", "/api/v1/catalogos/administracion/{clave}"): (
        "ADMIN",
        "SUPERVISOR",
        "ASESOR",
    ),
    ("PATCH", "/api/v1/catalogos/administracion/{clave}/{id_registro}"): ("ADMIN",),
    ("POST", "/api/v1/catalogos/administracion/{clave}"): ("ADMIN",),
    ("DELETE", "/api/v1/catalogos/administracion/{clave}/{id_registro}"): ("ADMIN",),
    ("POST", "/api/v1/catalogos/administracion/{clave}/confirmacion"): ("ADMIN",),
}


# Cobertura de las rutas aditivas y de los contratos incorporados desde develop.
ROLES_POR_RUTA.update(
    {
        # Seguridad: permisos de roles (WorkOS) y pestañas por rol
        ("GET", "/api/v1/seguridad/permisos"): ("ADMIN",),
        ("PATCH", "/api/v1/seguridad/permisos/{slug}"): ("ADMIN",),
        ("POST", "/api/v1/seguridad/permisos"): ("ADMIN",),
        ("DELETE", "/api/v1/seguridad/permisos/{slug}"): ("ADMIN",),
        ("GET", "/api/v1/seguridad/roles"): ("ADMIN",),
        ("POST", "/api/v1/seguridad/roles/{rol}/permisos"): ("ADMIN",),
        ("DELETE", "/api/v1/seguridad/roles/{rol}/permisos/{permiso}"): ("ADMIN",),
        ("PUT", "/api/v1/seguridad/roles/{rol}/permisos"): ("ADMIN",),
        ("GET", "/api/v1/seguridad/pestanas"): AUTH,
        ("PUT", "/api/v1/seguridad/pestanas"): ("ADMIN",),
        ("GET", "/api/v1/seguridad/pestanas/configuracion"): ("ADMIN",),
        ("PUT", "/api/v1/seguridad/pestanas/configuracion"): ("ADMIN",),
        ("GET", "/api/v1/seguridad/accesos/configuracion"): ("ADMIN",),
        ("PATCH", "/api/v1/seguridad/accesos/configuracion"): ("ADMIN",),
        ("GET", "/api/v1/auth/agencias"): (),
        ("POST", "/api/v1/auth/agencia-activa"): (),
        ("GET", "/api/v1/usuarios/{idUsuario}/agencias"): ("ADMIN",),
        ("PUT", "/api/v1/usuarios/{idUsuario}/agencias"): ("ADMIN",),
        ("GET", "/api/v1/usuarios/{idUsuario}/agencias/historial"): ("ADMIN",),
        ("PUT", "/api/v1/usuarios/{idUsuario}/agencia"): ("ADMIN",),
        ("GET", "/api/v1/usuarios/{idUsuario}/historial"): ("ADMIN",),
        ("GET", "/api/v1/contabilidad/cuentas/importaciones/{id_importacion}"): (
            "CONTADOR",
        ),
        ("POST", "/api/v1/contabilidad/cuentas/importaciones"): ("CONTADOR",),
        (
            "POST",
            "/api/v1/contabilidad/cuentas/importaciones/{id_importacion}/aplicar",
        ): ("CONTADOR",),
        ("GET", "/api/v1/contabilidad/plantillas/{id_plantilla}"): ("CONTADOR",),
        ("GET", "/api/v1/contabilidad/plantillas"): ("CONTADOR",),
        ("GET", "/api/v1/contabilidad/plantillas/catalogos"): ("CONTADOR",),
        ("GET", "/api/v1/contabilidad/plantillas/{id_plantilla}/solicitudes"): (
            "CONTADOR",
        ),
        ("GET", "/api/v1/contabilidad/tipos-asiento/{id_tipo}/plantillas"): (
            "CONTADOR",
        ),
        ("POST", "/api/v1/contabilidad/tipos-asiento/{id_tipo}/plantillas"): (
            "CONTADOR",
        ),
        ("POST", "/api/v1/contabilidad/plantillas/{id_plantilla}/solicitudes"): (
            "CONTADOR",
        ),
        ("POST", "/api/v1/contabilidad/plantillas/simulaciones"): ("CONTADOR",),
    }
)


def _rutas_api() -> list[tuple[str, str]]:
    return [
        (metodo.upper(), ruta)
        for ruta, operaciones in app.openapi()["paths"].items()
        if ruta.startswith("/api/")
        for metodo in operaciones
        if metodo in {"get", "post", "put", "patch", "delete"}
    ]


def _concreta(ruta: str) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: _VALORES_PATH.get(m.group(1), "1"), ruta)


@pytest.fixture(autouse=True)
def _pin_pad_simulado_habilitado(monkeypatch):
    """El CI usa production: simular development para probar permisos del PIN pad,
    sin habilitarlo en produccion real.
    """
    from types import SimpleNamespace

    monkeypatch.setattr(
        tarjetas_router, "get_settings", lambda: SimpleNamespace(app_env="development")
    )


@pytest.fixture
def client():
    # Sin BD real: lo que llegue al repositorio falla, pero el control de acceso ya pasó
    app.dependency_overrides[cooperativa] = lambda: None
    app.dependency_overrides[tarjetas_router.seguridad] = lambda: None
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _llamar(client: TestClient, metodo: str, ruta: str):
    return client.request(metodo, _concreta(ruta))


def _code(respuesta) -> str:
    # Clientes (gestión) y contabilidad aún no usan ProblemDetailsRoute (F-04): ahí
    # FastAPI responde {"detail": {"code": ...}}. Cuando migren, basta con ["code"].
    cuerpo = respuesta.json()
    return cuerpo.get("code") or cuerpo["detail"]["code"]


def test_tabla_de_roles_cubre_todas_las_rutas_protegidas():
    protegidas = (
        set(_rutas_api()) - _PUBLICAS - _TERMINALES - {("POST", "/api/v1/auth/refresh")}
    )
    assert protegidas == set(ROLES_POR_RUTA)


@pytest.mark.parametrize("ruta", sorted(set(_rutas_api()) - _PUBLICAS - _TERMINALES))
def test_toda_ruta_de_la_api_exige_sesion(client, eventos_auditados, ruta):
    metodo, path = ruta

    r = _llamar(client, metodo, path)

    assert r.status_code == 401
    assert _code(r) == "NO_AUTENTICADO"
    evento = eventos_auditados[-1]
    assert (evento.accion, evento.resultado, evento.usuario) == (
        "ACCESO_DENEGADO",
        "Fallido",
        None,
    )
    assert evento.descripcion.startswith(f"401 {metodo} {_concreta(path)} trace=")


def test_atm_registrado_exige_credencial_aun_con_sesion_workos(
    client, eventos_auditados
):
    simular_sesion(app, USUARIO)
    respuesta = client.post("https://testserver/api/v1/atm/auth")
    assert respuesta.status_code == 401
    assert _code(respuesta) == "TERMINAL_NO_AUTORIZADO"
    assert eventos_auditados[-1].accion == "ACCESO_DENEGADO"
    assert "/api/v1/atm/auth" in app.openapi()["paths"]


def test_logout_exige_jwt_atm_aun_con_sesion_workos(client):
    simular_sesion(app, USUARIO)
    respuesta = client.post("https://testserver/api/v1/atm/logout")
    assert respuesta.status_code == 401
    assert _code(respuesta) == "SESION_ATM_INVALIDA"
    assert (
        app.openapi()["paths"]["/api/v1/atm/logout"]["post"]["operationId"] == "ATM09"
    )


@pytest.mark.parametrize("sesion_workos", [False, True])
@pytest.mark.parametrize("authorization", [None, "Bearer no-es-un-jwt"])
@pytest.mark.parametrize(
    "ruta_atm",
    ["consulta-saldo", "cambio-pin", "transferencias", "reversos", "retiros"],
)
def test_consulta_saldo_exige_sesion_atm_valida(
    client, monkeypatch, sesion_workos, authorization, ruta_atm
):
    from unittest.mock import Mock

    from cryptography.hazmat.primitives.asymmetric import rsa

    from app.modules.atm import router as atm_router
    from app.modules.atm import session as atm_session

    if sesion_workos:
        simular_sesion(app, USUARIO)
    emisor = atm_session.EmisorSesionATM(
        rsa.generate_private_key(public_exponent=65537, key_size=2048),
        "atm-laboratorio",
        "atm-laboratorio",
    )
    monkeypatch.setattr(atm_session, "preparar_emisor_atm", lambda: emisor)
    base_de_datos = Mock(side_effect=AssertionError("No debe acceder a SQL"))
    monkeypatch.setattr(atm_router, "get_engine", base_de_datos)
    monkeypatch.setattr(atm_session, "get_engine", base_de_datos)
    respuesta = client.post(
        "https://testserver/api/v1/atm/" + ruta_atm,
        headers={} if authorization is None else {"Authorization": authorization},
        json={"idCuenta": 1, "registroUnico": "SALDOLAB0001"},
    )
    assert respuesta.status_code == 401
    assert _code(respuesta) == "SESION_ATM_INVALIDA"
    assert respuesta.headers["WWW-Authenticate"] == "Bearer"
    base_de_datos.assert_not_called()


@pytest.mark.parametrize(
    ("ruta", "roles"),
    [(r, roles) for r, roles in ROLES_POR_RUTA.items() if roles],
    ids=lambda v: " ".join(v) if isinstance(v, tuple) else v,
)
def test_rol_fuera_de_la_tarea_recibe_403(client, ruta, roles):
    simular_sesion(app, usuario_con_roles(*(r for r in ROLES if r not in roles)))

    r = _llamar(client, *ruta)

    assert r.status_code == 403
    assert _code(r) == "SIN_PERMISO"


@pytest.mark.parametrize("ruta", list(ROLES_POR_RUTA), ids=" ".join)
def test_roles_de_la_tarea_pasan_el_control(client, ruta, monkeypatch):
    roles = ROLES_POR_RUTA[ruta]
    usuario = usuario_con_roles(*roles)
    if ruta[1].startswith(
        (
            "/api/v1/aprobaciones",
            "/api/v1/productos",
            "/api/v1/contabilidad/cuentas-producto",
        )
    ) or ruta[1] in {
        "/api/v1/parametros",
        "/api/v1/parametros/{clave}",
        "/api/v1/parametros/{clave}/valores",
        "/api/v1/parametros/{clave}/valores/{id_valor}",
    }:
        from app.modules.aprobaciones import identidad

        # Esta matriz comprueba el guarda comun. La revalidacion WorkOS y el
        # permiso por operacion se prueban en las suites especificas de E0-08.
        usuario = replace(usuario, id_organizacion="org_fixture_autorizacion")
        monkeypatch.setattr(
            identidad, "get_organizacion_id", lambda: usuario.id_organizacion
        )
    if ruta[1] == "/api/v1/contabilidad/plantillas/{id_plantilla}/solicitudes":
        from app.core.api.errors import problema
        from app.modules.aprobaciones import identidad

        usuario = replace(usuario, id_organizacion="org_fixture_autorizacion")

        def sin_proveedor(*args):
            raise problema(503, "IDENTIDAD_NO_DISPONIBLE", "Fixture de autorizacion.")

        monkeypatch.setattr(identidad, "vigente", sin_proveedor)
    simular_sesion(app, usuario)

    r = _llamar(client, *ruta)

    # D-01: estos endpoints requieren vinculación
    # WorkOS -> IdUsuario interno.
    rutas_con_vinculacion = {
        ("GET", "/api/v1/caja/jornadas/actual"),
        ("POST", "/api/v1/caja/jornadas/{idJornada}/cierre"),
        ("POST", "/api/v1/caja/jornadas/{idJornada}/depositos"),
        ("POST", "/api/v1/caja/depositos/{idTransaccion}/series"),
        ("POST", "/api/v1/caja/jornadas/{idJornada}/retiros"),
        ("POST", "/api/v1/transacciones/{idTransaccion}/reverso"),
    }

    if ruta in rutas_con_vinculacion and r.status_code == 403:
        assert r.json().get("code") == "USUARIO_INTERNO_NO_VINCULADO"
        return

    assert r.status_code not in {401, 403}


@pytest.mark.parametrize(
    "ruta",
    [r for r in ROLES_POR_RUTA if r[1].startswith("/api/v1/boveda/")],
    ids=" ".join,
)
def test_admin_pasa_control_de_todas_las_rutas_de_boveda(client, ruta):
    simular_sesion(app, usuario_con_roles("ADMIN"))

    respuesta = _llamar(client, *ruta)

    assert respuesta.status_code not in {401, 403}


def test_require_auth_entrega_el_usuario_de_la_sesion():
    from starlette.requests import Request

    assert (
        require_auth(
            Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api/v1/auth/me",
                    "headers": [],
                }
            ),
            USUARIO,
        )
        is USUARIO
    )


def test_403_auditado_con_el_usuario_vinculado(client, eventos_auditados, monkeypatch):

    usuario = replace(usuario_con_roles("CAJERO"), id_interno=12)
    # La sesión real deja el usuario en request.state; aquí se simula ese paso

    def sesion(request: Request) -> Usuario:
        request.state.usuario = usuario
        return usuario

    from app.core.security.auth import usuario_actual

    app.dependency_overrides[usuario_actual] = sesion

    r = client.get("/api/v1/tarjetas/1/historial?fechaDesde=2026-01-01")

    assert r.status_code == 403
    evento = eventos_auditados[-1]
    assert evento.usuario == 12
    # Sin query string: puede traer datos personales
    assert "fechaDesde" not in evento.descripcion
    assert "usuario=" not in evento.descripcion


def test_403_de_usuario_sin_vinculo_registra_su_id_de_workos(client, eventos_auditados):
    usuario = replace(usuario_con_roles("CAJERO"), id_interno=None)

    def sesion(request: Request) -> Usuario:
        request.state.usuario = usuario
        return usuario

    from app.core.security.auth import usuario_actual

    app.dependency_overrides[usuario_actual] = sesion

    client.get("/api/v1/tarjetas/1")

    evento = eventos_auditados[-1]
    assert evento.usuario is None
    assert evento.descripcion.endswith(f"usuario={usuario.id_usuario}")
    # Los roles de WorkOS con que se negó quedan en la auditoría
    assert evento.roles == "CAJERO"


def test_respuestas_que_no_son_401_ni_403_no_se_auditan(client, eventos_auditados):
    simular_sesion(app)

    client.get("/api/v1/clientes", params={"page": "0"})

    assert eventos_auditados == []


def test_smoke_test_sigue_siendo_publico(client, eventos_auditados, monkeypatch):
    from app import smoke_test

    monkeypatch.setattr(smoke_test, "_db_ok", lambda _db: True)

    r = client.get("/smoke-test")

    assert r.status_code == 200
    assert eventos_auditados == []
