"""Catálogo revisable por operación; los valores iniciales no limitan la delegación."""

import re
from dataclasses import dataclass

from app.core.security.auth import ROLES
from app.core.security.permisos import PERMISOS

ATENCION = ("ADMIN", "ASESOR", "CAJERO", "SUPERVISOR")
GESTORES = ("ADMIN", "ASESOR", "SUPERVISOR")
REGISTRO = ("ADMIN", "ASESOR")
AUDITORIA = ("ADMIN", "SUPERVISOR", "AUDITOR")
CONTABLES = ("ADMIN", "CONTADOR", "AUDITOR")


@dataclass(frozen=True)
class Funcion:
    id: str
    nombre: str
    modulo: str
    roles_iniciales: tuple[str, ...]
    operaciones: tuple[tuple[str, str], ...]
    rutas: tuple[str, ...] = ()
    dependencias: tuple[str, ...] = ()
    delegable: bool = True


def _f(
    id_: str,
    nombre: str,
    modulo: str,
    roles: tuple[str, ...],
    operaciones: tuple[tuple[str, str], ...],
    ruta: str,
    dependencias: tuple[str, ...] = (),
    *,
    delegable: bool = True,
) -> Funcion:
    return Funcion(
        id_, nombre, modulo, roles, operaciones, (ruta,), dependencias, delegable
    )


C = "/api/v1/clientes"
Q = "/api/v1/cuentas"
T = "/api/v1/tarjetas"
P = "/api/v1/productos"
G = "/api/v1/catalogos"
B = "/api/v1/contabilidad"
U = "/api/v1/usuarios"

# E1-10 conserva su autorización operativa y su cola de aprobación propias.
# Incluir una sección aquí no concede funciones ni sustituye sus verificaciones.
SECCIONES_LEGADAS = frozenset({"parametros.consultar"})

FUNCIONES = (
    _f(
        "clientes.registrar",
        "Registrar cliente",
        "Clientes",
        REGISTRO,
        (("GET", C + "/validar-identificacion"), ("POST", C)),
        "/registrar-cliente",
    ),
    _f(
        "clientes.consultar",
        "Consultar clientes",
        "Clientes",
        ATENCION,
        (("GET", C), ("GET", C + "/{idCliente}")),
        "/clientes-busqueda",
    ),
    _f(
        "clientes.editar",
        "Editar cliente",
        "Clientes",
        REGISTRO,
        (("PATCH", C + "/{idCliente}"),),
        "/clientes-busqueda",
        ("clientes.consultar",),
    ),
    _f(
        "clientes.cambiarEstado",
        "Cambiar estado del cliente",
        "Clientes",
        GESTORES,
        (("PATCH", C + "/{idCliente}/estado"),),
        "/clientes-busqueda",
        ("clientes.consultar",),
    ),
    _f(
        "clientes.verHistorial",
        "Ver historial del cliente",
        "Clientes",
        AUDITORIA,
        (("GET", C + "/{idCliente}/historial"),),
        "/clientes-busqueda",
    ),
    _f(
        "clientes.verPerfil",
        "Ver perfil del cliente",
        "Clientes",
        GESTORES,
        (("GET", C + "/{idCliente}/perfil"),),
        "/clientes-busqueda",
        ("clientes.consultar",),
    ),
    _f(
        "clientes.direcciones.consultar",
        "Consultar direcciones",
        "Clientes",
        REGISTRO,
        (("GET", C + "/{idCliente}/direcciones"),),
        "/clientes-busqueda",
    ),
    _f(
        "clientes.direcciones.gestionar",
        "Gestionar direcciones",
        "Clientes",
        REGISTRO,
        (
            ("POST", C + "/{idCliente}/direcciones"),
            ("PATCH", C + "/{idCliente}/direcciones/{idDireccion}"),
            ("DELETE", C + "/{idCliente}/direcciones/{idDireccion}"),
        ),
        "/clientes-busqueda",
        (
            "clientes.direcciones.consultar",
            "clientes.consultar",
        ),
    ),
    _f(
        "clientes.riesgo.consultar",
        "Consultar evaluaciones de riesgo",
        "Clientes",
        AUDITORIA + ("ASESOR",),
        (
            ("GET", C + "/{idCliente}/evaluaciones-riesgo"),
            ("GET", C + "/{idCliente}/habilitacion"),
        ),
        "/clientes-busqueda",
    ),
    _f(
        "clientes.riesgo.evaluar",
        "Evaluar riesgo del cliente",
        "Clientes",
        GESTORES,
        (("POST", C + "/{idCliente}/evaluaciones-riesgo"),),
        "/clientes-busqueda",
        (
            "clientes.riesgo.consultar",
            "clientes.consultar",
        ),
    ),
    _f(
        "cuentas.abrir",
        "Abrir cuenta",
        "Cuentas",
        REGISTRO,
        (
            ("POST", Q),
            ("GET", Q + "/{idCuenta}/formulario-apertura"),
            ("POST", Q + "/{idCuenta}/anulacion"),
            ("POST", Q + "/{idCuenta}/autorizados"),
            ("POST", Q + "/{idCuenta}/autorizados/{idAut}/fin"),
        ),
        "/cuentas/abrir",
    ),
    _f(
        "cuentas.consultar",
        "Consultar cuentas",
        "Cuentas",
        ATENCION,
        (
            ("GET", Q),
            ("GET", Q + "/{idCuenta}"),
            ("GET", Q + "/{idCuenta}/autorizados"),
            ("GET", Q + "/{idCuenta}/eventos"),
        ),
        "/cuentas",
    ),
    _f(
        "cuentas.verSaldo",
        "Consultar saldo",
        "Cuentas",
        ATENCION,
        (("GET", Q + "/{idCuenta}/saldo"),),
        "/cuentas",
        ("cuentas.consultar",),
    ),
    _f(
        "cuentas.verMovimientos",
        "Consultar movimientos",
        "Cuentas",
        ATENCION,
        (("GET", Q + "/{idCuenta}/movimientos"),),
        "/cuentas",
        ("cuentas.consultar",),
    ),
    _f(
        "cuentas.cambiarEstado",
        "Cambiar estado de cuenta",
        "Cuentas",
        ("ASESOR", "SUPERVISOR"),
        (
            ("PATCH", Q + "/{idCuenta}/estado"),
            ("GET", Q + "/catalogos/motivos-bloqueo"),
        ),
        "/cuentas",
        ("cuentas.consultar",),
    ),
    _f(
        "cuentas.cupos.consultar",
        "Consultar cupos",
        "Cuentas",
        GESTORES,
        (("GET", Q + "/{idCuenta}/cupos"),),
        "/cuentas",
        ("cuentas.consultar",),
    ),
    _f(
        "cuentas.cupos.modificar",
        "Modificar cupos",
        "Cuentas",
        ("ASESOR", "ADMIN", "SUPERVISOR"),
        (("PUT", Q + "/{idCuenta}/cupos/{idCanal}"),),
        "/cuentas",
        ("cuentas.cupos.consultar",),
    ),
    _f(
        "cuentas.cupos.verHistorial",
        "Ver historial de cupos",
        "Cuentas",
        AUDITORIA,
        (("GET", Q + "/{idCuenta}/cupos/{idCanal}/historial"),),
        "/cuentas",
    ),
    _f(
        "tarjetas.emitir",
        "Emitir tarjeta",
        "Tarjetas",
        REGISTRO,
        (("POST", T),),
        "/solicitar-tarjeta",
    ),
    _f(
        "tarjetas.consultar",
        "Consultar tarjetas",
        "Tarjetas",
        GESTORES,
        (("GET", T), ("GET", T + "/{idTarjeta}")),
        "/tarjetas",
    ),
    _f(
        "tarjetas.cambiarEstado",
        "Cambiar estado de tarjeta",
        "Tarjetas",
        GESTORES,
        (("POST", T + "/{idTarjeta}/estado"),),
        "/tarjetas",
        ("tarjetas.consultar",),
    ),
    _f(
        "tarjetas.asignarPin",
        "Asignar PIN",
        "Tarjetas",
        REGISTRO,
        (("POST", T + "/{idTarjeta}/pin"),),
        "/tarjetas",
        ("tarjetas.consultar",),
    ),
    _f(
        "tarjetas.verSobrePin",
        "Consultar sobre PIN",
        "Tarjetas",
        GESTORES,
        (("GET", T + "/{idTarjeta}/sobre-pin"),),
        "/tarjetas",
        ("tarjetas.consultar",),
    ),
    _f(
        "tarjetas.verHistorial",
        "Ver historial de tarjeta",
        "Tarjetas",
        AUDITORIA,
        (("GET", T + "/{idTarjeta}/historial"),),
        "/tarjetas",
    ),
    _f(
        "entidad.consultar",
        "Consultar cooperativa",
        "Organización",
        REGISTRO,
        (("GET", "/api/v1/organizacion/entidad"),),
        "/organizacion/entidad",
    ),
    _f(
        "entidad.crear",
        "Crear cooperativa",
        "Organización",
        ("ADMIN",),
        (("POST", "/api/v1/organizacion/entidad"),),
        "/organizacion/entidad",
        ("entidad.consultar",),
    ),
    _f(
        "entidad.editar",
        "Editar cooperativa",
        "Organización",
        ("ADMIN",),
        (("PATCH", "/api/v1/organizacion/entidad"),),
        "/organizacion/entidad",
        ("entidad.consultar",),
    ),
    _f(
        "agencias.consultar",
        "Consultar agencias",
        "Organización",
        ("ADMIN",),
        (
            ("GET", "/api/v1/agencias/{id_agencia}"),
            ("GET", "/api/v1/organizacion/agencias"),
            ("GET", "/api/v1/organizacion/agencias/{id_agencia}"),
        ),
        "/organizacion/agencias",
    ),
    _f(
        "agencias.crear",
        "Crear agencia",
        "Organización",
        ("ADMIN",),
        (
            ("POST", "/api/v1/agencias"),
            ("POST", "/api/v1/organizacion/agencias"),
        ),
        "/organizacion/agencias",
        ("agencias.consultar",),
    ),
    _f(
        "agencias.editar",
        "Editar agencia",
        "Organización",
        ("ADMIN",),
        (
            ("PATCH", "/api/v1/agencias/{id_agencia}"),
            ("PATCH", "/api/v1/organizacion/agencias/{id_agencia}"),
        ),
        "/organizacion/agencias",
        ("agencias.consultar",),
    ),
    _f(
        "agencias.cambiarEstado",
        "Cambiar estado de agencia",
        "Organización",
        ("ADMIN",),
        (
            ("PATCH", "/api/v1/agencias/{id_agencia}/estado"),
            ("PATCH", "/api/v1/organizacion/agencias/{id_agencia}/estado"),
        ),
        "/organizacion/agencias",
        ("agencias.consultar",),
    ),
    _f(
        "productos.consultar",
        "Consultar productos",
        "Productos",
        PERMISOS["prd-consultar"],
        tuple(
            ("GET", P + s)
            for s in (
                "",
                "/tipos",
                "/{id_producto}",
                "/{id_producto}/historial",
                "/{id_producto}/vinculos",
                "/subproductos/{id_sub_producto}/ficha",
                "/subproductos/{id_sub_producto}/historial",
                "/subproductos/{id_sub_producto}/vinculos",
                "/subproductos/{id_sub_producto}/cupos",
                "/subproductos/{id_sub_producto}/restricciones",
                "/subproductos/{id_sub}/vigencias",
                "/subproductos/{id_sub}/numeracion",
                "/subproductos/{id_sub}/activacion",
                "/subproductos/{id_sub}/condiciones",
            )
        ),
        "/productos",
    ),
    _f(
        "productos.editar",
        "Crear y editar productos y subproductos",
        "Productos",
        PERMISOS["prd-editar"],
        (
            ("POST", P),
            ("PATCH", P + "/{id_producto}"),
            ("POST", P + "/{id_producto}/subproductos"),
            ("PATCH", P + "/subproductos/{id_sub_producto}"),
        ),
        "/productos",
        ("productos.consultar",),
    ),
    _f(
        "productos.estado",
        "Solicitar cambios de estado de productos",
        "Productos",
        PERMISOS["prd-estado"],
        (
            ("POST", P + "/{id_producto}/estado"),
            ("POST", P + "/subproductos/{id_sub_producto}/estado"),
        ),
        "/productos",
        ("productos.consultar",),
    ),
    _f(
        "productos.eliminar",
        "Eliminar producto",
        "Productos",
        PERMISOS["prd-editar"],
        (("DELETE", P + "/{id_producto}"),),
        "/productos",
        ("productos.consultar",),
    ),
    _f(
        "productos.configurar",
        "Configurar vinculos de productos",
        "Productos",
        PERMISOS["prd-editar"],
        tuple(
            ("PUT", P + s)
            for s in (
                "/{id_producto}/vinculos",
                "/subproductos/{id_sub_producto}/vinculos",
            )
        ),
        "/productos",
        ("productos.consultar",),
    ),
    _f(
        "productos.programar",
        "Programar condiciones, cupos y restricciones",
        "Productos",
        PERMISOS["prd-condicion"],
        (
            ("PUT", P + "/subproductos/{id_sub_producto}/cupos"),
            ("PUT", P + "/subproductos/{id_sub_producto}/restricciones"),
            ("POST", P + "/subproductos/{id_sub}/condiciones"),
            ("DELETE", P + "/subproductos/{id_sub}/condiciones/{id_registro}"),
            ("PATCH", P + "/subproductos/{id_sub}/condiciones/{id_registro}"),
            ("PATCH", P + "/subproductos/{id_sub}/cupos/{id_registro}"),
            ("POST", P + "/subproductos/{id_sub}/restricciones"),
            ("DELETE", P + "/subproductos/{id_sub}/restricciones/{id_registro}"),
            ("PATCH", P + "/subproductos/{id_sub}/restricciones/{id_registro}"),
            ("POST", P + "/subproductos/{id_sub}/restricciones/{id_registro}/fin"),
            (
                "DELETE",
                P + "/subproductos/{id_sub}/cupos/programaciones/{id_programacion}",
            ),
        ),
        "/productos",
        ("productos.consultar",),
        delegable=False,
    ),
    _f(
        "productos.numeracion",
        "Solicitar reglas de numeracion de cuentas",
        "Productos",
        PERMISOS["prd-numeracion"],
        (
            ("PUT", P + "/subproductos/{id_sub}/numeracion"),
            ("POST", P + "/subproductos/{id_sub}/numeracion/ejemplo"),
        ),
        "/productos",
        ("productos.consultar",),
        delegable=False,
    ),
    _f(
        "productos.exportar",
        "Exportar ficha de producto",
        "Productos",
        PERMISOS["prd-consultar"],
        (("GET", P + "/subproductos/{id_sub_producto}/ficha/imprimible"),),
        "/productos",
        ("productos.consultar",),
    ),
    _f(
        "catalogos.consultar",
        "Consultar administración de catálogos",
        "Catálogos",
        GESTORES,
        (("GET", G + "/administracion"), ("GET", G + "/administracion/{clave}")),
        "/catalogos",
    ),
    _f(
        "catalogos.crear",
        "Crear registro de catálogo o tasa",
        "Catálogos",
        ("ADMIN",),
        (("POST", G + "/administracion/{clave}"), ("POST", G + "/tasas-interes")),
        "/catalogos",
        ("catalogos.consultar",),
    ),
    _f(
        "catalogos.editar",
        "Editar registro de catálogo",
        "Catálogos",
        ("ADMIN",),
        (("PATCH", G + "/administracion/{clave}/{id_registro}"),),
        "/catalogos",
        ("catalogos.consultar",),
    ),
    _f(
        "catalogos.eliminar",
        "Eliminar registro de catálogo",
        "Catálogos",
        ("ADMIN",),
        (("DELETE", G + "/administracion/{clave}/{id_registro}"),),
        "/catalogos",
        (
            "catalogos.consultar",
            "catalogos.confirmar",
        ),
    ),
    _f(
        "catalogos.confirmar",
        "Confirmar cambio de catálogo",
        "Catálogos",
        ("ADMIN",),
        (("POST", G + "/administracion/{clave}/confirmacion"),),
        "/catalogos",
        ("catalogos.consultar",),
    ),
    _f(
        "contabilidad.cuentas.consultar",
        "Consultar plan de cuentas",
        "Contabilidad",
        CONTABLES,
        (("GET", B + "/cuentas-contables"),),
        "/contabilidad",
    ),
    _f(
        "contabilidad.cuentas.editar",
        "Crear y editar cuentas contables",
        "Contabilidad",
        ("CONTADOR",),
        (
            ("POST", B + "/cuentas-contables"),
            ("PATCH", B + "/cuentas-contables/{idCuentaContable}"),
            ("PATCH", B + "/cuentas-contables/{idCuentaContable}/estado"),
        ),
        "/contabilidad",
        ("contabilidad.cuentas.consultar",),
    ),
    _f(
        "contabilidad.cuentas.eliminar",
        "Eliminar cuenta contable",
        "Contabilidad",
        ("CONTADOR",),
        (("DELETE", B + "/cuentas-contables/{idCuentaContable}"),),
        "/contabilidad",
        ("contabilidad.cuentas.consultar",),
    ),
    _f(
        "contabilidad.importaciones.preparar",
        "Preparar importación contable",
        "Contabilidad",
        PERMISOS["con-cuenta-editar"],
        (("POST", B + "/cuentas/importaciones"),),
        "/contabilidad",
        (
            "contabilidad.cuentas.consultar",
            "contabilidad.importaciones.consultar",
        ),
    ),
    _f(
        "contabilidad.importaciones.consultar",
        "Consultar importación contable",
        "Contabilidad",
        PERMISOS["con-cuenta-editar"],
        (("GET", B + "/cuentas/importaciones/{id_importacion}"),),
        "/contabilidad",
    ),
    _f(
        "contabilidad.importaciones.aplicar",
        "Aplicar importación contable",
        "Contabilidad",
        PERMISOS["con-cuenta-editar"],
        (("POST", B + "/cuentas/importaciones/{id_importacion}/aplicar"),),
        "/contabilidad",
        ("contabilidad.importaciones.consultar",),
    ),
    _f(
        "contabilidad.plantillas.consultar",
        "Consultar plantillas contables",
        "Contabilidad",
        ("ADMIN", "SUPERVISOR", "AUDITOR", "CONTADOR"),
        (
            ("GET", B + "/plantillas"),
            ("GET", B + "/plantillas/catalogos"),
            ("GET", B + "/plantillas/{id_plantilla}/solicitudes"),
            ("GET", B + "/tipos-asiento/{id_tipo}/plantillas"),
            ("GET", B + "/plantillas/{id_plantilla}"),
        ),
        "/contabilidad/plantillas",
    ),
    _f(
        "contabilidad.plantillas.editar",
        "Simular y crear versiones de plantillas",
        "Contabilidad",
        PERMISOS["con-plantilla-editar"],
        (
            ("POST", B + "/tipos-asiento/{id_tipo}/plantillas"),
            ("POST", B + "/plantillas/simulaciones"),
            ("POST", B + "/plantillas/{id_plantilla}/solicitudes"),
        ),
        "/contabilidad/plantillas",
        ("contabilidad.plantillas.consultar",),
    ),
    _f(
        "contabilidad.cuentas_producto.consultar",
        "Consultar cuentas contables de los productos",
        "Contabilidad",
        PERMISOS["prd-consultar"],
        (
            ("GET", B + "/cuentas-producto/clases"),
            ("GET", B + "/cuentas-producto/tipos/{id_tipo}"),
            ("GET", B + "/cuentas-producto/subproductos/{id_sub}"),
        ),
        "/contabilidad/cuentas-producto",
    ),
    _f(
        "contabilidad.cuentas_producto.editar",
        "Solicitar asignaciones de cuentas a productos",
        "Contabilidad",
        PERMISOS["con-cuenta-editar"],
        (("PUT", B + "/cuentas-producto/tipos/{id_tipo}"),),
        "/contabilidad/cuentas-producto",
        ("contabilidad.cuentas_producto.consultar",),
        delegable=False,
    ),
    _f(
        "contabilidad.asientos.consultar",
        "Consultar asientos",
        "Contabilidad",
        CONTABLES,
        (("GET", B + "/asientos"), ("GET", B + "/asientos/{idAsiento}")),
        "/contabilidad/asientos",
    ),
    _f(
        "contabilidad.fecha.consultar",
        "Consultar fecha contable",
        "Contabilidad",
        ROLES,
        (
            ("GET", B + "/fechas-contables/actual"),
            ("GET", B + "/fechas-contables/{fecha}"),
        ),
        "/contabilidad/fecha-contable",
    ),
    _f(
        "usuarios.consultar",
        "Consultar usuarios",
        "Seguridad",
        ("ADMIN",),
        (
            ("GET", U),
            ("GET", U + "/{idUsuario}"),
            ("GET", U + "/{idUsuario}/agencias"),
            ("GET", U + "/{idUsuario}/agencias/historial"),
            ("GET", U + "/{idUsuario}/historial"),
        ),
        "/usuarios",
    ),
    _f(
        "usuarios.administrar",
        "Administrar usuarios, roles y agencias",
        "Seguridad",
        ("ADMIN",),
        (
            ("POST", U),
            ("PATCH", U + "/{idUsuario}"),
            ("PUT", U + "/{idUsuario}/roles"),
            ("PUT", U + "/{idUsuario}/agencias"),
            ("PUT", U + "/{idUsuario}/agencia"),
        ),
        "/usuarios",
        delegable=False,
    ),
)

POR_ID = {f.id: f for f in FUNCIONES}


def _patron(ruta: str) -> re.Pattern[str]:
    return re.compile(
        "".join(
            "[^/]+" if parte.startswith("{") else re.escape(parte)
            for parte in re.split(r"(\{[^}]+\})", ruta)
        )
    )


OPERACIONES = tuple(
    (metodo, _patron(ruta), funcion.id)
    for metodo, ruta, funcion in sorted(
        (
            (metodo, ruta, funcion)
            for funcion in FUNCIONES
            for metodo, ruta in funcion.operaciones
        ),
        key=lambda fila: fila[1].count("{"),
    )
)


def funcion_api(metodo: str, ruta: str) -> str | None:
    return next(
        (
            id_
            for verbo, patron, id_ in OPERACIONES
            if verbo == metodo and patron.fullmatch(ruta)
        ),
        None,
    )


def valor_inicial(funcion: str, rol: str) -> bool:
    return rol in POR_ID[funcion].roles_iniciales


def catalogo_valido() -> bool:
    parejas = [op for f in FUNCIONES for op in f.operaciones]
    return (
        len(POR_ID) == len(FUNCIONES)
        and len(parejas) == len(set(parejas))
        and all(set(f.roles_iniciales) <= set(ROLES) for f in FUNCIONES)
        and all(d in POR_ID for f in FUNCIONES for d in f.dependencias)
    )
