"""Restricción adicional por sección: nunca reemplaza roles, permisos o agencia.

La clasificación usa método y ruta completa. Los selectores compartidos conservan
sus reglas anteriores; una API sensible no acepta un origen/pantalla del cliente
como excusa para eludir el acceso retirado.
"""

import re

from fastapi import Request

from app.core.api.errors import problema
from app.core.config.settings import get_settings
from app.core.security.auth import Usuario
from app.modules.seguridad.accesos import efectivos

RUTAS_SECCION = {
    "parametros.consultar": "/parametros",
    "clientes.registrar": "/registrar-cliente",
    "clientes.consultar": "/clientes-busqueda",
    "cuentas.abrir": "/cuentas/abrir",
    "cuentas.consultar": "/cuentas",
    "tarjetas.emitir": "/solicitar-tarjeta",
    "tarjetas.consultar": "/tarjetas",
    "organizacion.entidad": "/organizacion/entidad",
    "organizacion.agencias": "/organizacion/agencias",
    "productos.consultar": "/productos",
    "catalogos.consultar": "/catalogos",
    "contabilidad.plan": "/contabilidad",
    "contabilidad.asientos": "/contabilidad/asientos",
    "contabilidad.fecha": "/contabilidad/fecha-contable",
    "seguridad.usuarios": "/usuarios",
    "seguridad.roles": "/seguridad/roles",
}

RUTAS_POR_SECCION: dict[str, tuple[tuple[str, str], ...]] = {
    "parametros.consultar": (
        ("GET", "/api/v1/parametros"),
        ("GET", "/api/v1/parametros/{clave}"),
        ("POST", "/api/v1/parametros/{clave}/valores"),
        ("DELETE", "/api/v1/parametros/{clave}/valores/{id_valor}"),
        ("PATCH", "/api/v1/parametros/{clave}/valores/{id_valor}"),
    ),
    "clientes.registrar": (
        ("POST", "/api/v1/clientes/validaciones/documento"),
        ("POST", "/api/v1/clientes"),
        ("POST", "/api/v1/clientes/reincorporaciones"),
    ),
    "clientes.consultar": (
        ("POST", "/api/v1/clientes/busqueda"),
        ("GET", "/api/v1/clientes/{idCliente}/relaciones/firmantes"),
        ("POST", "/api/v1/clientes/{idCliente}/relaciones/firmantes"),
        ("POST", "/api/v1/clientes/{idCliente}/relaciones/firmantes/{idRelacion}/fin"),
        ("POST", "/api/v1/clientes/busqueda/exportacion"),
        ("GET", "/api/v1/clientes/{idCliente}"),
        ("POST", "/api/v1/clientes/{idCliente}/revelacion/desafio"),
        ("POST", "/api/v1/clientes/{idCliente}/revelacion"),
        ("PATCH", "/api/v1/clientes/{idCliente}"),
        ("PATCH", "/api/v1/clientes/{idCliente}/estado"),
        ("GET", "/api/v1/clientes/{idCliente}/historial"),
        ("GET", "/api/v1/clientes/{idCliente}/perfil"),
        ("GET", "/api/v1/clientes/{idCliente}/documentos"),
        ("POST", "/api/v1/clientes/{idCliente}/documentos"),
        ("PATCH", "/api/v1/clientes/{idCliente}/documentos/{idDocumento}"),
        ("PUT", "/api/v1/clientes/{idCliente}/documentos/{idDocumento}/principal"),
        ("GET", "/api/v1/clientes/{idCliente}/direcciones"),
        ("POST", "/api/v1/clientes/{idCliente}/direcciones"),
        ("PATCH", "/api/v1/clientes/{idCliente}/direcciones/{idDireccion}"),
        ("DELETE", "/api/v1/clientes/{idCliente}/direcciones/{idDireccion}"),
        ("GET", "/api/v1/clientes/{idCliente}/emails"),
        ("POST", "/api/v1/clientes/{idCliente}/emails"),
        ("DELETE", "/api/v1/clientes/{idCliente}/emails/{idEmail}"),
        ("POST", "/api/v1/clientes/{idCliente}/email/verificacion"),
        ("POST", "/api/v1/clientes/{idCliente}/emails/{idEmail}/verificacion"),
        ("GET", "/api/v1/clientes/{idCliente}/evaluaciones-riesgo"),
        ("GET", "/api/v1/clientes/{idCliente}/habilitacion"),
        ("POST", "/api/v1/clientes/{idCliente}/evaluaciones-riesgo"),
    ),
    "cuentas.abrir": (
        ("POST", "/api/v1/cuentas"),
        ("GET", "/api/v1/cuentas/{idCuenta}/formulario-apertura"),
        ("POST", "/api/v1/cuentas/{idCuenta}/anulacion"),
        ("POST", "/api/v1/cuentas/{idCuenta}/autorizados"),
        ("POST", "/api/v1/cuentas/{idCuenta}/autorizados/{idAut}/fin"),
    ),
    "cuentas.consultar": (
        ("GET", "/api/v1/cuentas"),
        ("GET", "/api/v1/cuentas/{idCuenta}"),
        ("GET", "/api/v1/cuentas/{idCuenta}/saldo"),
        ("GET", "/api/v1/cuentas/{idCuenta}/autorizados"),
        ("GET", "/api/v1/cuentas/{idCuenta}/eventos"),
        ("GET", "/api/v1/cuentas/{idCuenta}/movimientos"),
        ("PATCH", "/api/v1/cuentas/{idCuenta}/estado"),
        ("GET", "/api/v1/cuentas/catalogos/motivos-bloqueo"),
        ("GET", "/api/v1/cuentas/{idCuenta}/cupos"),
        ("PUT", "/api/v1/cuentas/{idCuenta}/cupos/{idCanal}"),
        ("GET", "/api/v1/cuentas/{idCuenta}/cupos/{idCanal}/historial"),
        ("GET", "/api/v1/cuentas/{idCuenta}/retenciones"),
        ("POST", "/api/v1/cuentas/{idCuenta}/retenciones"),
        ("POST", "/api/v1/cuentas/{idCuenta}/retenciones/{idRet}/liberacion"),
        ("GET", "/api/v1/cuentas/{idCuenta}/subproductos-destino"),
        ("POST", "/api/v1/cuentas/{idCuenta}/subproducto"),
    ),
    "tarjetas.emitir": (("POST", "/api/v1/tarjetas"),),
    "tarjetas.consultar": (
        ("GET", "/api/v1/tarjetas"),
        ("GET", "/api/v1/tarjetas/por-renovar"),
        ("GET", "/api/v1/tarjetas/{idTarjeta}"),
        ("POST", "/api/v1/tarjetas/{idTarjeta}/estado"),
        ("PATCH", "/api/v1/tarjetas/{idTarjeta}/envio"),
        ("POST", "/api/v1/tarjetas/{idTarjeta}/pin"),
        ("GET", "/api/v1/tarjetas/{idTarjeta}/sobre-pin"),
        ("GET", "/api/v1/tarjetas/{idTarjeta}/historial"),
    ),
    "organizacion.entidad": tuple(
        (metodo, "/api/v1/organizacion/entidad") for metodo in ("GET", "POST", "PATCH")
    ),
    "organizacion.agencias": (
        ("POST", "/api/v1/agencias"),
        ("GET", "/api/v1/agencias/{id_agencia}"),
        ("PATCH", "/api/v1/agencias/{id_agencia}"),
        ("PATCH", "/api/v1/agencias/{id_agencia}/estado"),
        ("GET", "/api/v1/organizacion/agencias"),
        ("POST", "/api/v1/organizacion/agencias"),
        ("GET", "/api/v1/organizacion/agencias/{id_agencia}"),
        ("PATCH", "/api/v1/organizacion/agencias/{id_agencia}"),
        ("PATCH", "/api/v1/organizacion/agencias/{id_agencia}/estado"),
    ),
    "productos.consultar": (
        ("GET", "/api/v1/contabilidad/cuentas-producto/subproductos/{id_sub}"),
        ("GET", "/api/v1/productos/subproductos/{id_sub}/vigencias"),
        ("GET", "/api/v1/productos/subproductos/{id_sub}/activacion"),
        ("GET", "/api/v1/productos/subproductos/{id_sub}/numeracion"),
        ("PUT", "/api/v1/productos/subproductos/{id_sub}/numeracion"),
        ("POST", "/api/v1/productos/subproductos/{id_sub}/numeracion/ejemplo"),
        ("GET", "/api/v1/productos/subproductos/{id_sub}/condiciones"),
        ("POST", "/api/v1/productos/subproductos/{id_sub}/condiciones"),
        ("DELETE", "/api/v1/productos/subproductos/{id_sub}/condiciones/{id_registro}"),
        ("PATCH", "/api/v1/productos/subproductos/{id_sub}/condiciones/{id_registro}"),
        ("PATCH", "/api/v1/productos/subproductos/{id_sub}/cupos/{id_registro}"),
        ("POST", "/api/v1/productos/subproductos/{id_sub}/restricciones"),
        (
            "DELETE",
            "/api/v1/productos/subproductos/{id_sub}/restricciones/{id_registro}",
        ),
        (
            "PATCH",
            "/api/v1/productos/subproductos/{id_sub}/restricciones/{id_registro}",
        ),
        (
            "POST",
            "/api/v1/productos/subproductos/{id_sub}/restricciones/{id_registro}/fin",
        ),
        (
            "DELETE",
            "/api/v1/productos/subproductos/{id_sub}/cupos/programaciones/{id_programacion}",
        ),
        ("GET", "/api/v1/productos"),
        ("POST", "/api/v1/productos"),
        ("GET", "/api/v1/productos/tipos"),
        ("GET", "/api/v1/productos/{id_producto}"),
        ("GET", "/api/v1/productos/{id_producto}/historial"),
        ("POST", "/api/v1/productos/{id_producto}/estado"),
        ("PATCH", "/api/v1/productos/{id_producto}"),
        ("DELETE", "/api/v1/productos/{id_producto}"),
        ("POST", "/api/v1/productos/{id_producto}/subproductos"),
        ("GET", "/api/v1/productos/{id_producto}/vinculos"),
        ("PUT", "/api/v1/productos/{id_producto}/vinculos"),
        ("GET", "/api/v1/productos/subproductos/{id_sub_producto}/ficha"),
        ("GET", "/api/v1/productos/subproductos/{id_sub_producto}/historial"),
        ("POST", "/api/v1/productos/subproductos/{id_sub_producto}/estado"),
        ("GET", "/api/v1/productos/subproductos/{id_sub_producto}/ficha/imprimible"),
        ("PATCH", "/api/v1/productos/subproductos/{id_sub_producto}"),
        ("GET", "/api/v1/productos/subproductos/{id_sub_producto}/vinculos"),
        ("PUT", "/api/v1/productos/subproductos/{id_sub_producto}/vinculos"),
        ("GET", "/api/v1/productos/subproductos/{id_sub_producto}/cupos"),
        ("PUT", "/api/v1/productos/subproductos/{id_sub_producto}/cupos"),
        ("GET", "/api/v1/productos/subproductos/{id_sub_producto}/restricciones"),
        ("PUT", "/api/v1/productos/subproductos/{id_sub_producto}/restricciones"),
    ),
    "catalogos.consultar": (
        ("POST", "/api/v1/catalogos/tipos-documento"),
        ("PATCH", "/api/v1/catalogos/tipos-documento/{codigo}"),
        ("GET", "/api/v1/catalogos/administracion"),
        ("GET", "/api/v1/catalogos/administracion/{clave}"),
        ("POST", "/api/v1/catalogos/administracion/{clave}"),
        ("POST", "/api/v1/catalogos/administracion/{clave}/confirmacion"),
        ("PATCH", "/api/v1/catalogos/administracion/{clave}/{id_registro}"),
        ("DELETE", "/api/v1/catalogos/administracion/{clave}/{id_registro}"),
        ("POST", "/api/v1/catalogos/tasas-interes"),
    ),
    "contabilidad.plan": (
        ("GET", "/api/v1/contabilidad/cuentas-contables"),
        ("POST", "/api/v1/contabilidad/cuentas-contables"),
        ("PATCH", "/api/v1/contabilidad/cuentas-contables/{idCuentaContable}"),
        ("DELETE", "/api/v1/contabilidad/cuentas-contables/{idCuentaContable}"),
        ("PATCH", "/api/v1/contabilidad/cuentas-contables/{idCuentaContable}/estado"),
        ("POST", "/api/v1/contabilidad/cuentas/importaciones"),
        ("GET", "/api/v1/contabilidad/cuentas/importaciones/{id_importacion}"),
        ("POST", "/api/v1/contabilidad/cuentas/importaciones/{id_importacion}/aplicar"),
        ("GET", "/api/v1/contabilidad/cuentas-producto/clases"),
        ("GET", "/api/v1/contabilidad/cuentas-producto/tipos/{id_tipo}"),
        ("PUT", "/api/v1/contabilidad/cuentas-producto/tipos/{id_tipo}"),
    ),
    "contabilidad.asientos": (
        ("GET", "/api/v1/contabilidad/asientos"),
        ("GET", "/api/v1/contabilidad/asientos/{idAsiento}"),
    ),
    "contabilidad.fecha": (
        ("GET", "/api/v1/contabilidad/fechas-contables/actual"),
        ("GET", "/api/v1/contabilidad/fechas-contables/{fecha}"),
    ),
    "seguridad.usuarios": (
        ("GET", "/api/v1/usuarios"),
        ("POST", "/api/v1/usuarios"),
        ("GET", "/api/v1/usuarios/{idUsuario}"),
        ("PATCH", "/api/v1/usuarios/{idUsuario}"),
        ("PUT", "/api/v1/usuarios/{idUsuario}/roles"),
        ("GET", "/api/v1/usuarios/{idUsuario}/agencias"),
        ("PUT", "/api/v1/usuarios/{idUsuario}/agencias"),
        ("GET", "/api/v1/usuarios/{idUsuario}/agencias/historial"),
        ("GET", "/api/v1/usuarios/{idUsuario}/historial"),
        ("PUT", "/api/v1/usuarios/{idUsuario}/agencia"),
    ),
}

# Consultas mínimas reutilizadas por varios formularios. No son APIs públicas:
# conservan autenticación y sus restricciones actuales.
COMPARTIDAS = tuple(
    ("GET", "/api/v1/catalogos/" + nombre)
    for nombre in (
        "paises",
        "paises/{codigo_pais}/ciudades",
        "denominaciones",
        "tipos-movimiento-caja",
        "canales",
        "redes",
        "sistemas-amortizacion",
        "tasas-interes",
        "comisiones",
        "seguros",
        "agencias",
        "tipos-credito",
        "actividades-economicas",
        "tipos-antecedente",
        "tipos-direccion",
        "tipos-documento",
        "productos",
    )
)

# Sin sección equivalente en el editor actual. No se inventa una asignación;
# mantienen su autorización anterior hasta acordar su catálogo de navegación.
FUERA_DEL_EDITOR = (
    ("POST", "/api/v1/contabilidad/cortes-e201"),
    ("GET", "/api/v1/contabilidad/cortes-e201/{id_plan}"),
    ("POST", "/api/v1/contabilidad/cortes-e201/{id_plan}/aprobaciones"),
    # Plantillas ya tiene funciones en el editor nuevo. El modo anterior conserva
    # sus permisos WorkOS y no necesita una sección legada adicional.
    ("GET", "/api/v1/contabilidad/plantillas"),
    ("GET", "/api/v1/contabilidad/reglas-contables"),
    ("GET", "/api/v1/contabilidad/plantillas/catalogos"),
    ("GET", "/api/v1/contabilidad/plantillas/{id_plantilla}/solicitudes"),
    ("GET", "/api/v1/contabilidad/tipos-asiento/{id_tipo}/plantillas"),
    ("POST", "/api/v1/contabilidad/tipos-asiento/{id_tipo}/plantillas"),
    ("GET", "/api/v1/contabilidad/plantillas/{id_plantilla}"),
    ("POST", "/api/v1/contabilidad/plantillas/simulaciones"),
    ("POST", "/api/v1/contabilidad/plantillas/{id_plantilla}/solicitudes"),
    ("GET", "/api/v1/parametros/comisiones"),
    ("GET", "/api/v1/parametros/comisiones/{idComision}/tarifa"),
    ("POST", "/api/v1/parametros/comisiones"),
    ("PATCH", "/api/v1/parametros/comisiones/{idComision}"),
    ("GET", "/api/v1/parametros/exoneraciones"),
    ("POST", "/api/v1/parametros/exoneraciones"),
    ("PATCH", "/api/v1/parametros/exoneraciones/{idExoneracion}"),
)

AMBITOS = (
    "/api/v1/clientes",
    "/api/v1/cuentas",
    "/api/v1/tarjetas",
    "/api/v1/agencias",
    "/api/v1/organizacion",
    "/api/v1/productos",
    "/api/v1/catalogos",
    "/api/v1/contabilidad",
    "/api/v1/parametros",
    "/api/v1/usuarios",
)


def _patron(ruta: str) -> re.Pattern[str]:
    partes = re.split(r"(\{[^}]+\})", ruta)
    return re.compile(
        "".join(
            "[^/]+" if parte.startswith("{") else re.escape(parte) for parte in partes
        )
    )


CLASIFICACION = tuple(
    (metodo, _patron(ruta), seccion)
    for metodo, ruta, seccion in sorted(
        [
            (metodo, ruta, seccion)
            for seccion, rutas in RUTAS_POR_SECCION.items()
            for metodo, ruta in rutas
        ]
        + [(metodo, ruta, "") for metodo, ruta in COMPARTIDAS + FUERA_DEL_EDITOR],
        key=lambda fila: fila[1].count("{"),
    )
)


def seccion_api(metodo: str, ruta: str) -> str | None:
    """Vacío = excepción explícita; None = no clasificada."""
    return next(
        (
            seccion
            for verbo, patron, seccion in CLASIFICACION
            if verbo == metodo and patron.fullmatch(ruta)
        ),
        None,
    )


def verificar_seccion(request: Request, usuario: Usuario) -> None:
    if not get_settings().editor_accesos_activo:
        return
    seccion = seccion_api(request.method, request.url.path)
    if seccion is None:
        if any(
            request.url.path == prefijo or request.url.path.startswith(prefijo + "/")
            for prefijo in AMBITOS
        ):
            raise problema(
                503,
                "RUTA_SIN_CLASIFICAR",
                "Esta operación necesita revisión de su acceso de sección.",
            )
        return
    if not seccion:
        return
    accesos = getattr(request.state, "accesos_secciones", None)
    if accesos is None:
        accesos = efectivos(usuario)
        request.state.accesos_secciones = accesos
    if RUTAS_SECCION[seccion] not in accesos.habilitadas:
        raise problema(
            403,
            "ACCESO_SECCION_RETIRADO",
            "El acceso a esta sección no está habilitado para su usuario.",
        )
