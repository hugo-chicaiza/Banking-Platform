"""Administración de catálogos: ADMIN edita y activa o desactiva; ADMIN y ASESOR consultan.

Cada catálogo declara sus campos aquí (una sola fuente: el frontend dibuja la tabla y el
formulario con esta descripción). Los campos que cambian reglas de negocio quedan de solo
lectura: valor y tipo de una denominación, naturaleza de un movimiento de caja, requisitos
de seguridad de un canal y la categoría de un antecedente (la regla C-08 depende de ella).
Nada se borra: la baja es por Estado. Fuera de aquí: agencias, productos y plan de cuentas,
que tienen su propia pantalla.

El SQL de cada catálogo es fijo (sin armar nombres de tabla o columna con texto).
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.core.api.errors import problema, traducir_error_bd
from app.core.security.auth import Usuario
from app.core.security.operador import auditar
from app.modules.catalogos.confirmacion import CATALOGOS_CON_CONFIRMACION

# numero: >= 0 con hasta 6 decimales (valor de comisión o seguro; en % si es Porcentaje)
# opcion: uno de `opciones` (p. ej. Billete o Moneda)
TipoCampo = Literal[
    "texto", "entero", "dinero", "porcentaje", "numero", "booleano", "fecha", "opcion"
]
_SIN_CONTROL = re.compile(r"^[^\x00-\x1f\x7f]+$")
_MAX_DINERO = Decimal("9999999999999999.99")


@dataclass(frozen=True)
class Campo:
    nombre: str  # camelCase, igual en la respuesta y en el PATCH
    etiqueta: str
    tipo: TipoCampo = "texto"
    editable: bool = False
    nulo: bool = False
    maximo: int | None = None  # largo del texto o valor máximo del número
    minimo: int | None = None
    opciones: tuple[str, ...] = ()
    patron: str | None = None  # formato del texto (códigos); se guarda en mayúsculas
    # Opciones que salen de la base al armar el descriptor (p. ej. "canales")
    opciones_de: str | None = None


@dataclass(frozen=True)
class Catalogo:
    clave: str
    nombre: str
    descripcion: str
    tabla: str
    campos: tuple[Campo, ...]
    listar: str
    actualizar: str
    # Tasas de interés: además se crean desde POST /catalogos/tasas-interes
    permite_crear: bool = False
    id_texto: bool = False  # Países usan su código ISO como id
    editables: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "editables", frozenset(c.nombre for c in self.campos if c.editable)
        )


CATALOGOS: dict[str, Catalogo] = {
    c.clave: c
    for c in (
        Catalogo(
            clave="tasas-interes",
            nombre="Tasas de interés",
            descripcion=(
                "Tasas de crédito, ahorro y tarjeta, con rango de monto y vigencia. "
                "Se vinculan a productos y subproductos desde Productos."
            ),
            tabla="Credito.TasaInteres",
            permite_crear=True,
            campos=(
                Campo("tipoTasa", "Tipo de tasa"),
                Campo("nombreTipoCredito", "Tipo de crédito"),
                Campo("tasaNominalAnual", "Tasa anual", "porcentaje", True),
                Campo("recargoMoraSobreTasa", "Recargo por mora", "porcentaje", True),
                Campo("montoMinimo", "Monto mínimo", "dinero", True, nulo=True),
                Campo("montoMaximo", "Monto máximo", "dinero", True, nulo=True),
                Campo(
                    "plazoMaximoMeses",
                    "Plazo máximo (meses)",
                    "entero",
                    True,
                    nulo=True,
                    maximo=600,
                    minimo=1,
                ),
                Campo("vigenciaDesde", "Vigente desde", "fecha"),
                Campo("vigenciaHasta", "Vigente hasta", "fecha", True, nulo=True),
            ),
            listar="""
                SELECT CAST(t.IdTasaInteres AS varchar(10)) AS id, t.Estado AS estado,
                       t.TipoTasa AS tipoTasa,
                       t.IdTipoCredito AS idTipoCredito, tc.Nombre AS nombreTipoCredito,
                       t.TasaNominalAnual AS tasaNominalAnual,
                       t.RecargoMoraSobreTasa AS recargoMoraSobreTasa,
                       t.MontoMinimo AS montoMinimo, t.MontoMaximo AS montoMaximo,
                       t.PlazoMaximoMeses AS plazoMaximoMeses,
                       t.VigenciaDesde AS vigenciaDesde, t.VigenciaHasta AS vigenciaHasta
                FROM Credito.TasaInteres AS t
                LEFT JOIN Credito.TipoCredito AS tc ON tc.IdTipoCredito = t.IdTipoCredito
                ORDER BY t.TipoTasa, tc.Nombre, t.VigenciaDesde DESC, t.MontoMinimo
            """,
            actualizar="""
                UPDATE Credito.TasaInteres SET
                    TasaNominalAnual = CASE WHEN :c_tasaNominalAnual = 1
                        THEN :tasaNominalAnual ELSE TasaNominalAnual END,
                    RecargoMoraSobreTasa = CASE WHEN :c_recargoMoraSobreTasa = 1
                        THEN :recargoMoraSobreTasa ELSE RecargoMoraSobreTasa END,
                    MontoMinimo = CASE WHEN :c_montoMinimo = 1
                        THEN :montoMinimo ELSE MontoMinimo END,
                    MontoMaximo = CASE WHEN :c_montoMaximo = 1
                        THEN :montoMaximo ELSE MontoMaximo END,
                    PlazoMaximoMeses = CASE WHEN :c_plazoMaximoMeses = 1
                        THEN :plazoMaximoMeses ELSE PlazoMaximoMeses END,
                    VigenciaHasta = CASE WHEN :c_vigenciaHasta = 1
                        THEN :vigenciaHasta ELSE VigenciaHasta END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE IdTasaInteres = TRY_CAST(:id AS int)
            """,
        ),
        Catalogo(
            clave="comisiones",
            nombre="Comisiones y recargos",
            descripcion=(
                "Cobros por canal (fijos o en %). Se vinculan a productos y subproductos; "
                "un subproducto puede quedar exonerado."
            ),
            tabla="Transacciones.Comisiones",
            campos=(
                Campo("codigo", "Código"),
                Campo("tipoComision", "Tipo"),
                Campo("tipoCalculo", "Cálculo"),
                Campo("valor", "Valor", "numero", True, minimo=0),
                Campo("nombreCanal", "Canal"),
                Campo("descripcion", "Descripción", editable=True, maximo=250),
                Campo("vigenciaDesde", "Vigente desde", "fecha"),
                Campo("vigenciaHasta", "Vigente hasta", "fecha", True, nulo=True),
            ),
            listar="""
                SELECT CAST(c.IdComision AS varchar(10)) AS id, c.Estado AS estado,
                       c.CodigoComision AS codigo, c.TipoComision AS tipoComision,
                       c.TipoCalculo AS tipoCalculo, c.Valor AS valor,
                       ca.NombreCanal AS nombreCanal, c.Descripcion AS descripcion,
                       c.VigenciaDesde AS vigenciaDesde, c.VigenciaHasta AS vigenciaHasta
                FROM Transacciones.Comisiones AS c
                JOIN Canal.Canal AS ca ON ca.IdCanal = c.IdCanal
                ORDER BY c.TipoComision, c.CodigoComision
            """,
            actualizar="""
                UPDATE Transacciones.Comisiones SET
                    Valor = CASE WHEN :c_valor = 1 THEN :valor ELSE Valor END,
                    Descripcion = CASE WHEN :c_descripcion = 1 THEN :descripcion ELSE Descripcion END,
                    VigenciaHasta = CASE WHEN :c_vigenciaHasta = 1
                        THEN :vigenciaHasta ELSE VigenciaHasta END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE IdComision = TRY_CAST(:id AS int)
            """,
        ),
        Catalogo(
            clave="seguros",
            nombre="Seguros",
            descripcion="Seguros (fijos o en %) que se vinculan a productos y subproductos.",
            tabla="Credito.Seguro",
            campos=(
                Campo("codigo", "Código"),
                Campo("nombre", "Nombre", editable=True, maximo=60),
                Campo(
                    "aseguradora", "Aseguradora", editable=True, nulo=True, maximo=100
                ),
                Campo("tipoCalculo", "Cálculo"),
                Campo("valor", "Valor", "numero", True, minimo=0),
                Campo("vigenciaDesde", "Vigente desde", "fecha"),
                Campo("vigenciaHasta", "Vigente hasta", "fecha", True, nulo=True),
            ),
            listar="""
                SELECT CAST(IdSeguro AS varchar(10)) AS id, Estado AS estado,
                       CodigoSeguro AS codigo, Nombre AS nombre, Aseguradora AS aseguradora,
                       TipoCalculo AS tipoCalculo, Valor AS valor,
                       VigenciaDesde AS vigenciaDesde, VigenciaHasta AS vigenciaHasta
                FROM Credito.Seguro
                ORDER BY Nombre
            """,
            actualizar="""
                UPDATE Credito.Seguro SET
                    Nombre = CASE WHEN :c_nombre = 1 THEN :nombre ELSE Nombre END,
                    Aseguradora = CASE WHEN :c_aseguradora = 1 THEN :aseguradora ELSE Aseguradora END,
                    Valor = CASE WHEN :c_valor = 1 THEN :valor ELSE Valor END,
                    VigenciaHasta = CASE WHEN :c_vigenciaHasta = 1
                        THEN :vigenciaHasta ELSE VigenciaHasta END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE IdSeguro = TRY_CAST(:id AS int)
            """,
        ),
        Catalogo(
            clave="tipos-credito",
            nombre="Tipos de crédito",
            descripcion="Consumo, microcrédito… Cada producto de crédito pertenece a uno.",
            tabla="Credito.TipoCredito",
            campos=(
                Campo("codigo", "Código"),
                Campo("nombre", "Nombre", editable=True, maximo=60),
                Campo(
                    "descripcion", "Descripción", editable=True, nulo=True, maximo=250
                ),
            ),
            listar="""
                SELECT CAST(IdTipoCredito AS varchar(10)) AS id, Estado AS estado,
                       CodigoTipoCredito AS codigo, Nombre AS nombre, Descripcion AS descripcion
                FROM Credito.TipoCredito
                ORDER BY Nombre
            """,
            actualizar="""
                UPDATE Credito.TipoCredito SET
                    Nombre = CASE WHEN :c_nombre = 1 THEN :nombre ELSE Nombre END,
                    Descripcion = CASE WHEN :c_descripcion = 1 THEN :descripcion ELSE Descripcion END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE IdTipoCredito = TRY_CAST(:id AS int)
            """,
        ),
        Catalogo(
            clave="sistemas-amortizacion",
            nombre="Sistemas de amortización",
            descripcion="Tablas de amortización que puede ofrecer un subproducto de crédito.",
            tabla="Catalogo.SistemaAmortizacion",
            id_texto=True,
            campos=(
                Campo("codigo", "Código"),
                Campo("nombre", "Nombre", editable=True, maximo=60),
                Campo("descripcion", "Descripción", editable=True, maximo=250),
            ),
            listar="""
                SELECT Codigo AS id, Estado AS estado, Codigo AS codigo, Nombre AS nombre,
                       Descripcion AS descripcion
                FROM Catalogo.SistemaAmortizacion
                ORDER BY Nombre
            """,
            actualizar="""
                UPDATE Catalogo.SistemaAmortizacion SET
                    Nombre = CASE WHEN :c_nombre = 1 THEN :nombre ELSE Nombre END,
                    Descripcion = CASE WHEN :c_descripcion = 1 THEN :descripcion ELSE Descripcion END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE Codigo = :id
            """,
        ),
        Catalogo(
            clave="redes",
            nombre="Redes de tarjeta",
            descripcion="Visa, Mastercard… y los requisitos para emitir una tarjeta de la red.",
            tabla="ProductosFinancieros.Red",
            campos=(
                Campo("codigo", "Código"),
                Campo("nombre", "Nombre", editable=True, maximo=60),
                Campo(
                    "descripcion", "Descripción", editable=True, nulo=True, maximo=250
                ),
                Campo(
                    "ingresoMinimo",
                    "Ingreso mínimo",
                    "dinero",
                    True,
                    nulo=True,
                    minimo=0,
                ),
                Campo(
                    "edadMinima",
                    "Edad mínima",
                    "entero",
                    True,
                    nulo=True,
                    minimo=16,
                    maximo=99,
                ),
                Campo(
                    "requiereCuentaActiva", "Requiere cuenta activa", "booleano", True
                ),
            ),
            listar="""
                SELECT CAST(IdRed AS varchar(10)) AS id, Estado AS estado, CodigoRed AS codigo,
                       Nombre AS nombre, Descripcion AS descripcion,
                       IngresoMinimo AS ingresoMinimo, EdadMinima AS edadMinima,
                       RequiereCuentaActiva AS requiereCuentaActiva
                FROM ProductosFinancieros.Red
                ORDER BY Nombre
            """,
            actualizar="""
                UPDATE ProductosFinancieros.Red SET
                    Nombre = CASE WHEN :c_nombre = 1 THEN :nombre ELSE Nombre END,
                    Descripcion = CASE WHEN :c_descripcion = 1 THEN :descripcion ELSE Descripcion END,
                    IngresoMinimo = CASE WHEN :c_ingresoMinimo = 1
                        THEN :ingresoMinimo ELSE IngresoMinimo END,
                    EdadMinima = CASE WHEN :c_edadMinima = 1 THEN :edadMinima ELSE EdadMinima END,
                    RequiereCuentaActiva = CASE WHEN :c_requiereCuentaActiva = 1
                        THEN :requiereCuentaActiva ELSE RequiereCuentaActiva END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE IdRed = TRY_CAST(:id AS int)
            """,
        ),
        Catalogo(
            clave="canales",
            nombre="Canales",
            descripcion="Ventanilla, cajero, banca web… Sus requisitos de seguridad no se editan aquí.",
            tabla="Canal.Canal",
            campos=(
                Campo("codigo", "Código"),
                Campo("nombre", "Nombre", editable=True, maximo=50),
                Campo("descripcion", "Descripción", editable=True, maximo=200),
                Campo("modo", "Modo"),
                Campo("requiereTarjeta", "Requiere tarjeta", "booleano"),
                Campo("requierePin", "Requiere PIN", "booleano"),
            ),
            listar="""
                SELECT CAST(IdCanal AS varchar(10)) AS id, Estado AS estado, CodigoCanal AS codigo,
                       NombreCanal AS nombre, Descripcion AS descripcion,
                       ModoDigitalPresencial AS modo, RequiereTarjeta AS requiereTarjeta,
                       RequierePin AS requierePin
                FROM Canal.Canal
                ORDER BY NombreCanal
            """,
            actualizar="""
                UPDATE Canal.Canal SET
                    NombreCanal = CASE WHEN :c_nombre = 1 THEN :nombre ELSE NombreCanal END,
                    Descripcion = CASE WHEN :c_descripcion = 1 THEN :descripcion ELSE Descripcion END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE IdCanal = TRY_CAST(:id AS int)
            """,
        ),
        Catalogo(
            clave="denominaciones",
            nombre="Denominaciones",
            descripcion="Billetes y monedas que se cuentan en caja y bóveda.",
            tabla="Catalogo.Denominacion",
            campos=(
                Campo("tipoPieza", "Tipo"),
                Campo("valor", "Valor", "dinero"),
                Campo("descripcion", "Descripción", editable=True, maximo=50),
            ),
            listar="""
                SELECT CAST(IdDenominacion AS varchar(10)) AS id, Estado AS estado,
                       TipoPieza AS tipoPieza, Valor AS valor, Descripcion AS descripcion
                FROM Catalogo.Denominacion
                ORDER BY CASE TipoPieza WHEN 'Billete' THEN 0 ELSE 1 END, Valor DESC
            """,
            actualizar="""
                UPDATE Catalogo.Denominacion SET
                    Descripcion = CASE WHEN :c_descripcion = 1 THEN :descripcion ELSE Descripcion END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE IdDenominacion = TRY_CAST(:id AS int)
            """,
        ),
        Catalogo(
            clave="tipos-movimiento-caja",
            nombre="Tipos de movimiento de caja",
            descripcion="Motivos de ingreso y egreso de efectivo. La naturaleza no se edita.",
            tabla="Caja.TipoMovimientoCaja",
            campos=(
                Campo("codigo", "Código"),
                Campo("descripcion", "Descripción", editable=True, maximo=150),
                Campo("naturaleza", "Naturaleza"),
            ),
            listar="""
                SELECT CAST(IdTipoMovimientoCaja AS varchar(10)) AS id, Estado AS estado,
                       Codigo AS codigo, Descripcion AS descripcion,
                       CASE Naturaleza WHEN 'I' THEN 'Ingreso' ELSE 'Egreso' END AS naturaleza
                FROM Caja.TipoMovimientoCaja
                ORDER BY Naturaleza, Codigo
            """,
            actualizar="""
                UPDATE Caja.TipoMovimientoCaja SET
                    Descripcion = CASE WHEN :c_descripcion = 1 THEN :descripcion ELSE Descripcion END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE IdTipoMovimientoCaja = TRY_CAST(:id AS int)
            """,
        ),
        Catalogo(
            clave="actividades-economicas",
            nombre="Actividades económicas",
            descripcion="Actividad del cliente al registrarlo, agrupada por área.",
            tabla="Catalogo.ActividadEconomica",
            campos=(
                Campo("descripcion", "Descripción", editable=True, maximo=200),
                Campo("areaActividad", "Área", editable=True, maximo=100),
            ),
            listar="""
                SELECT CAST(IdActividadEconomica AS varchar(10)) AS id, Estado AS estado,
                       Descripcion AS descripcion, AreaActividad AS areaActividad
                FROM Catalogo.ActividadEconomica
                ORDER BY AreaActividad, Descripcion
            """,
            actualizar="""
                UPDATE Catalogo.ActividadEconomica SET
                    Descripcion = CASE WHEN :c_descripcion = 1 THEN :descripcion ELSE Descripcion END,
                    AreaActividad = CASE WHEN :c_areaActividad = 1
                        THEN :areaActividad ELSE AreaActividad END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE IdActividadEconomica = TRY_CAST(:id AS int)
            """,
        ),
        Catalogo(
            clave="tipos-antecedente",
            nombre="Tipos de antecedente",
            descripcion="Antecedentes que se revisan al vincular un cliente. La categoría no se edita.",
            tabla="Catalogo.TipoAntecedente",
            campos=(
                Campo("nombre", "Nombre", editable=True, maximo=150),
                Campo("categoria", "Categoría"),
                Campo(
                    "puedeImpedirVinculacion",
                    "Puede impedir la vinculación",
                    "booleano",
                ),
            ),
            # Esta tabla guarda Activo/Inactivo: se normaliza a A/I
            listar="""
                SELECT CAST(IdTipoAntecedente AS varchar(10)) AS id,
                       CASE Estado WHEN 'Activo' THEN 'A' ELSE 'I' END AS estado,
                       Nombre AS nombre, Categoria AS categoria,
                       PuedeImpedirVinculacion AS puedeImpedirVinculacion
                FROM Catalogo.TipoAntecedente
                ORDER BY Categoria, Nombre
            """,
            actualizar="""
                UPDATE Catalogo.TipoAntecedente SET
                    Nombre = CASE WHEN :c_nombre = 1 THEN :nombre ELSE Nombre END,
                    Estado = CASE WHEN :c_estado = 1
                        THEN CASE :estado WHEN 'A' THEN 'Activo' ELSE 'Inactivo' END
                        ELSE Estado END
                WHERE IdTipoAntecedente = TRY_CAST(:id AS int)
            """,
        ),
        Catalogo(
            clave="paises",
            nombre="Países",
            descripcion="Nacionalidad y país de residencia de los clientes (ISO 3166-1).",
            tabla="Catalogo.Paises",
            id_texto=True,
            campos=(
                Campo("codigoPais", "Código"),
                Campo("codigoNumerico", "Código numérico"),
                Campo("nombrePais", "Nombre", editable=True, maximo=100),
            ),
            listar="""
                SELECT CodigoPais AS id, Estado AS estado, CodigoPais AS codigoPais,
                       CodigoNumerico AS codigoNumerico, NombrePais AS nombrePais
                FROM Catalogo.Paises
                ORDER BY NombrePais
            """,
            actualizar="""
                UPDATE Catalogo.Paises SET
                    NombrePais = CASE WHEN :c_nombrePais = 1 THEN :nombrePais ELSE NombrePais END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE CodigoPais = :id
            """,
        ),
        Catalogo(
            clave="ciudades",
            nombre="Ciudades",
            descripcion="Ciudades y provincias de direcciones y agencias.",
            tabla="Catalogo.Ciudad",
            campos=(
                Campo("codigoPais", "País"),
                Campo("provincia", "Provincia", editable=True, maximo=80),
                Campo("nombre", "Nombre", editable=True, maximo=80),
            ),
            listar="""
                SELECT CAST(IdCiudad AS varchar(10)) AS id, Estado AS estado,
                       CodigoPais AS codigoPais, Provincia AS provincia, Nombre AS nombre
                FROM Catalogo.Ciudad
                ORDER BY CodigoPais, Provincia, Nombre
            """,
            actualizar="""
                UPDATE Catalogo.Ciudad SET
                    Provincia = CASE WHEN :c_provincia = 1 THEN :provincia ELSE Provincia END,
                    Nombre = CASE WHEN :c_nombre = 1 THEN :nombre ELSE Nombre END,
                    Estado = CASE WHEN :c_estado = 1 THEN :estado ELSE Estado END
                WHERE IdCiudad = TRY_CAST(:id AS int)
            """,
        ),
    )
}


def _campo_json(f: Campo, *, editable: bool | None = None) -> dict[str, Any]:
    return {
        "nombre": f.nombre,
        "etiqueta": f.etiqueta,
        "tipo": f.tipo,
        "editable": f.editable if editable is None else editable,
        "nulo": f.nulo,
        "maximo": f.maximo,
        "minimo": f.minimo,
        "opciones": list(f.opciones),
    }


def _opciones_dinamicas(conn: Connection | None, origen: str) -> list[str]:
    if conn is None or origen != "canales":
        return []
    return [
        str(c)
        for c in conn.execute(
            text(
                "SELECT CodigoCanal FROM Canal.Canal WHERE Estado = 'A' ORDER BY CodigoCanal"
            )
        ).scalars()
    ]


def descriptores(conn: Connection | None = None) -> list[dict[str, Any]]:
    """Catálogos y sus campos: el frontend dibuja la tabla, la edición y el alta con esto."""
    salida = []
    for c in CATALOGOS.values():
        alta_baja = _ALTA_BAJA.get(c.clave, AltaBaja())
        campos_alta = []
        for f in alta_baja.campos:
            campo = _campo_json(f, editable=True)
            if f.opciones_de:
                campo["opciones"] = _opciones_dinamicas(conn, f.opciones_de)
            campos_alta.append(campo)
        salida.append(
            {
                "clave": c.clave,
                "nombre": c.nombre,
                "descripcion": c.descripcion,
                "permiteCrear": c.permite_crear,
                "campos": [_campo_json(f) for f in c.campos],
                # Alta genérica (vacío = sin alta desde esta pantalla)
                "camposAlta": campos_alta,
                "permiteEliminar": bool(alta_baja.eliminar),
                # Crear o eliminar pide el código de confirmación (confirmacion.py)
                "requiereConfirmacion": c.clave in CATALOGOS_CON_CONFIRMACION,
            }
        )
    return salida


def _catalogo(clave: str) -> Catalogo:
    catalogo = CATALOGOS.get(clave)
    if catalogo is None:
        raise problema(404, "CATALOGO_NO_EXISTE", "Ese catálogo no existe.")
    return catalogo


def _invalido(etiqueta: str, motivo: str) -> Exception:
    return problema(422, "DATOS_INVALIDOS", f"{etiqueta}: {motivo}")


def _valor(campo: Campo, valor: Any) -> Any:
    """Valida un valor recibido según el tipo del campo y lo deja listo para la BD."""
    if valor is None or (
        campo.tipo == "texto" and isinstance(valor, str) and not valor.strip()
    ):
        if campo.nulo:
            return None
        raise _invalido(campo.etiqueta, "es obligatorio.")
    if campo.tipo == "texto":
        if not isinstance(valor, str):
            raise _invalido(campo.etiqueta, "debe ser texto.")
        valor = valor.strip()
        if not _SIN_CONTROL.match(valor):
            raise _invalido(campo.etiqueta, "escríbelo en una sola línea.")
        if campo.patron and not re.match(campo.patron, valor):
            raise _invalido(campo.etiqueta, "tiene un formato no válido.")
        if campo.maximo and len(valor) > campo.maximo:
            raise _invalido(
                campo.etiqueta, f"usa {campo.maximo} caracteres como máximo."
            )
        return valor
    if campo.tipo == "opcion" and campo.opciones_de:
        if not isinstance(valor, str) or not valor.strip():
            raise _invalido(campo.etiqueta, "es obligatorio.")
        return valor.strip().upper()
    if campo.tipo == "opcion":
        if valor not in campo.opciones:
            raise _invalido(campo.etiqueta, f"elige {' o '.join(campo.opciones)}.")
        return valor
    if campo.tipo == "booleano":
        if not isinstance(valor, bool):
            raise _invalido(campo.etiqueta, "debe ser sí o no.")
        return valor
    if campo.tipo == "fecha":
        if not isinstance(valor, str):
            raise _invalido(campo.etiqueta, "usa una fecha AAAA-MM-DD.")
        try:
            return date.fromisoformat(valor)
        except ValueError:
            raise _invalido(campo.etiqueta, "usa una fecha AAAA-MM-DD.") from None
    if campo.tipo == "entero":
        if isinstance(valor, bool) or not isinstance(valor, int):
            raise _invalido(campo.etiqueta, "debe ser un número entero.")
        if (campo.minimo is not None and valor < campo.minimo) or (
            campo.maximo is not None and valor > campo.maximo
        ):
            raise _invalido(
                campo.etiqueta, f"debe estar entre {campo.minimo} y {campo.maximo}."
            )
        return valor
    # dinero y porcentaje: números con 2 y 4 decimales
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str)):
        raise _invalido(campo.etiqueta, "debe ser un número.")
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        raise _invalido(campo.etiqueta, "debe ser un número.") from None
    if not numero.is_finite():
        raise _invalido(campo.etiqueta, "debe ser un número.")
    decimales = {"dinero": 2, "porcentaje": 4}.get(campo.tipo, 6)
    if numero != numero.quantize(Decimal(1).scaleb(-decimales)):
        raise _invalido(campo.etiqueta, f"usa {decimales} decimales como máximo.")
    if campo.tipo == "porcentaje":
        # Fracción anual: 0.16 = 16 %. La tasa nominal no puede ser 0 (CK de la tabla)
        minimo_ok = numero > 0 if campo.nombre == "tasaNominalAnual" else numero >= 0
        if not minimo_ok or numero > 1:
            raise _invalido(campo.etiqueta, "debe estar entre 0 y 100 %.")
        return numero
    if campo.tipo == "numero":
        if numero < 0 or numero > Decimal("99999999.999999"):
            raise _invalido(campo.etiqueta, "está fuera de rango.")
        return numero
    minimo = Decimal(campo.minimo) if campo.minimo is not None else Decimal("0.01")
    if numero < minimo or numero > _MAX_DINERO:
        raise _invalido(campo.etiqueta, "está fuera de rango.")
    return numero


def _cambios(catalogo: Catalogo, cuerpo: dict[str, Any]) -> dict[str, Any]:
    if not cuerpo:
        raise problema(
            400, "DATOS_INVALIDOS", "Envíe al menos un campo para actualizar."
        )
    desconocidos = set(cuerpo) - catalogo.editables - {"estado"}
    if desconocidos:
        raise problema(
            400,
            "DATOS_INVALIDOS",
            f"Campos que no se editan en este catálogo: {', '.join(sorted(desconocidos))}.",
        )
    cambios: dict[str, Any] = {}
    for campo in catalogo.campos:
        if campo.nombre in cuerpo:
            cambios[campo.nombre] = _valor(campo, cuerpo[campo.nombre])
    if "estado" in cuerpo:
        if cuerpo["estado"] not in ("A", "I"):
            raise _invalido("Estado", "debe ser A (activo) o I (inactivo).")
        cambios["estado"] = cuerpo["estado"]
    return cambios


def _rows(conn: Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(text(sql)).mappings()]


def _normalizar(fila: dict[str, Any]) -> dict[str, Any]:
    # char(1) puede traer espacios; los bit llegan como bool
    return {**fila, "estado": str(fila["estado"]).strip()}


def _salida(fila: dict[str, Any]) -> dict[str, Any]:
    """Montos y tasas como número en el JSON (como Money), no como texto."""
    return {k: float(v) if isinstance(v, Decimal) else v for k, v in fila.items()}


def listar(conn: Connection, clave: str) -> list[dict[str, Any]]:
    return [_salida(_normalizar(f)) for f in _rows(conn, _catalogo(clave).listar)]


def _fila(conn: Connection, catalogo: Catalogo, id_: str) -> dict[str, Any] | None:
    return next(
        (_normalizar(f) for f in _rows(conn, catalogo.listar) if f["id"] == id_), None
    )


def _validar_fila(final: dict[str, Any]) -> None:
    """Reglas que cruzan campos, antes de que la BD las rechace con un 500 (CK)."""
    hasta = final.get("vigenciaHasta")
    if hasta is not None and hasta <= final["vigenciaDesde"]:
        raise _invalido("Vigente hasta", "debe ser posterior a la fecha de inicio.")
    if final.get("tipoCalculo") == "Porcentaje" and final["valor"] > 100:
        raise _invalido("Valor", "en porcentaje no puede pasar de 100.")


def _validar_tasa(
    _conn: Connection, actual: dict[str, Any], cambios: dict[str, Any]
) -> None:
    """Una tasa de crédito necesita plazo. Pueden coexistir varias tasas del mismo tipo:
    el solapamiento se valida al vincularlas a un producto o subproducto."""
    final = {**actual, **cambios}
    minimo, maximo = final["montoMinimo"], final["montoMaximo"]
    if minimo is not None and maximo is not None and maximo < minimo:
        raise _invalido("Monto máximo", "debe ser mayor o igual que el mínimo.")
    if final["tipoTasa"] != "CREDITO":
        return
    if final["plazoMaximoMeses"] is None:
        raise _invalido("Plazo máximo (meses)", "es obligatorio en tasas de crédito.")


def actualizar(
    conn: Connection,
    clave: str,
    id_: str,
    cuerpo: dict[str, Any],
    usuario: Usuario,
    ip: str,
) -> dict[str, Any]:
    catalogo = _catalogo(clave)
    cambios = _cambios(catalogo, cuerpo)
    actual = _fila(conn, catalogo, id_)
    if actual is None:
        raise problema(404, "REGISTRO_NO_ENCONTRADO", "El registro no existe.")
    # E1-09 AC 5: antes y después de cada campo que cambia (lo demás no cambia)
    antes = {k: actual.get(k) for k in sorted(cambios)}
    despues = {k: cambios[k] for k in sorted(cambios)}
    with auditar(
        "ACTUALIZAR",
        catalogo.tabla,
        usuario,
        ip,
        f"CAT-EDITAR {clave} antes={_json(antes)} despues={_json(despues)}",
        id_,
    ):
        try:
            _validar_fila({**actual, **cambios})
            if clave == "tasas-interes":
                _validar_tasa(conn, actual, cambios)
            parametros: dict[str, Any] = {"id": id_}
            for nombre in (*catalogo.editables, "estado"):
                parametros[f"c_{nombre}"] = nombre in cambios
                parametros[nombre] = cambios.get(nombre)
            conn.execute(text(catalogo.actualizar), parametros)
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise _error_bd(exc) from None
        except Exception:
            conn.rollback()
            raise
    fila = _fila(conn, catalogo, id_)
    if fila is None:
        raise problema(500, "ERROR_INTERNO", "Error interno del servidor.")
    return _salida(fila)


# ---------- Alta y baja (E1-09 #109) ----------
# Sin alta ni baja: sistemas de amortización y canales (su comportamiento es código),
# comisiones (el tipo de cálculo cambia qué datos exige; alta con pantalla propia) y
# tasas (alta en POST /catalogos/tasas-interes). Una baja solo procede sin uso: lo que
# se usa se desactiva (409 ITEM_EN_USO). El SQL de cada catálogo es fijo.

_CODIGO = r"^[A-Za-z0-9_-]{2,15}$"


@dataclass(frozen=True)
class AltaBaja:
    campos: tuple[Campo, ...] = ()  # vacío = sin alta
    insertar: str | None = None
    en_uso: str = ""
    eliminar: str = ""


_ALTA_BAJA: dict[str, AltaBaja] = {
    "tasas-interes": AltaBaja(
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM ProductosFinancieros.ProductoTasaInteres
                WHERE IdTasaInteres = TRY_CAST(:id AS int)) THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM Credito.TasaInteres WHERE IdTasaInteres = TRY_CAST(:id AS int)",
    ),
    "comisiones": AltaBaja(
        campos=(
            Campo("codigo", "Código", maximo=10, patron=_CODIGO),
            Campo(
                "tipoComision",
                "Tipo",
                "opcion",
                opciones=(
                    "Retiro",
                    "Transferencia",
                    "Consulta",
                    "Mantenimiento",
                    "Emision Tarjeta",
                    "Reposicion Tarjeta",
                    "Otro",
                ),
            ),
            Campo("tipoCalculo", "Cálculo", "opcion", opciones=("Fijo", "Porcentaje")),
            Campo("valor", "Valor (USD o %)", "numero", minimo=0),
            Campo(
                "montoMinimo", "Cobro mínimo (solo %)", "dinero", nulo=True, minimo=0
            ),
            Campo(
                "montoMaximo", "Cobro máximo (solo %)", "dinero", nulo=True, minimo=0
            ),
            Campo("codigoCanal", "Canal", "opcion", opciones_de="canales"),
            Campo("descripcion", "Descripción", maximo=250),
            Campo("vigenciaDesde", "Vigente desde", "fecha"),
        ),
        # El canal se busca por su código: si no existe o está inactivo, no inserta
        insertar="""
            INSERT INTO Transacciones.Comisiones (CodigoComision, TipoComision, TipoCalculo,
                Valor, MontoMinimo, MontoMaximo, IdCanal, Descripcion, VigenciaDesde)
            OUTPUT CAST(inserted.IdComision AS varchar(10))
            SELECT :codigo, :tipoComision, :tipoCalculo, :valor, :montoMinimo, :montoMaximo,
                   c.IdCanal, :descripcion, :vigenciaDesde
            FROM Canal.Canal AS c
            WHERE c.CodigoCanal = :codigoCanal AND c.Estado = 'A'
        """,
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM ProductosFinancieros.ProductoComision
                    WHERE IdComision = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Transacciones.TransaccionComision
                    WHERE IdComision = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Transacciones.ComisionTipoTransaccion
                    WHERE IdComision = TRY_CAST(:id AS int))
            THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM Transacciones.Comisiones WHERE IdComision = TRY_CAST(:id AS int)",
    ),
    "sistemas-amortizacion": AltaBaja(
        campos=(
            Campo("codigo", "Código", maximo=10, patron=r"^[A-Za-z]{3,10}$"),
            Campo("nombre", "Nombre", maximo=60),
            Campo("descripcion", "Descripción", maximo=250),
        ),
        insertar="""
            INSERT INTO Catalogo.SistemaAmortizacion (Codigo, Nombre, Descripcion)
            OUTPUT inserted.Codigo
            VALUES (:codigo, :nombre, :descripcion)
        """,
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM ProductosFinancieros.ProductoSistemaAmortizacion
                    WHERE CodigoSistema = :id)
                OR EXISTS (SELECT 1 FROM Credito.CreditoSolicitud WHERE SistemaAmortizacion = :id)
            THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM Catalogo.SistemaAmortizacion WHERE Codigo = :id",
    ),
    "canales": AltaBaja(
        campos=(
            Campo("codigo", "Código", maximo=10, patron=_CODIGO),
            Campo("nombre", "Nombre", maximo=50),
            Campo("descripcion", "Descripción", maximo=200),
            Campo(
                "modo", "Modo", "opcion", opciones=("Digital", "Presencial", "Ambos")
            ),
            Campo("requiereTarjeta", "Requiere tarjeta", "booleano"),
            Campo("requierePin", "Requiere PIN", "booleano"),
            Campo("requiereTerminal", "Requiere terminal", "booleano"),
            Campo("requiereJornadaCaja", "Requiere jornada de caja", "booleano"),
        ),
        insertar="""
            INSERT INTO Canal.Canal (CodigoCanal, NombreCanal, Descripcion, ModoDigitalPresencial,
                RequiereTarjeta, RequierePin, RequiereTerminal, RequiereJornadaCaja)
            OUTPUT CAST(inserted.IdCanal AS varchar(10))
            VALUES (:codigo, :nombre, :descripcion, :modo, :requiereTarjeta, :requierePin,
                    :requiereTerminal, :requiereJornadaCaja)
        """,
    ),
    "seguros": AltaBaja(
        campos=(
            Campo("codigo", "Código", maximo=15, patron=_CODIGO),
            Campo("nombre", "Nombre", maximo=60),
            Campo("aseguradora", "Aseguradora", nulo=True, maximo=100),
            Campo("tipoCalculo", "Cálculo", "opcion", opciones=("Fijo", "Porcentaje")),
            Campo("valor", "Valor", "numero", minimo=0),
            Campo("vigenciaDesde", "Vigente desde", "fecha"),
        ),
        insertar="""
            INSERT INTO Credito.Seguro (CodigoSeguro, Nombre, Aseguradora, TipoCalculo, Valor,
                VigenciaDesde)
            OUTPUT CAST(inserted.IdSeguro AS varchar(10))
            VALUES (:codigo, :nombre, :aseguradora, :tipoCalculo, :valor, :vigenciaDesde)
        """,
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM ProductosFinancieros.ProductoSeguro
                    WHERE IdSeguro = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Credito.CreditoPlanDetalleRubro
                    WHERE IdSeguro = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Credito.TipoCreditoSeguro
                    WHERE IdSeguro = TRY_CAST(:id AS int))
            THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM Credito.Seguro WHERE IdSeguro = TRY_CAST(:id AS int)",
    ),
    "tipos-credito": AltaBaja(
        campos=(
            Campo("codigo", "Código", maximo=15, patron=_CODIGO),
            Campo("nombre", "Nombre", maximo=60),
            Campo("descripcion", "Descripción", nulo=True, maximo=250),
        ),
        insertar="""
            INSERT INTO Credito.TipoCredito (CodigoTipoCredito, Nombre, Descripcion)
            OUTPUT CAST(inserted.IdTipoCredito AS varchar(10))
            VALUES (:codigo, :nombre, :descripcion)
        """,
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM ProductosFinancieros.Producto
                    WHERE IdTipoCredito = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Credito.TasaInteres WHERE IdTipoCredito = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Credito.CreditoSolicitud
                    WHERE IdTipoCredito = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Credito.TipoCreditoSeguro
                    WHERE IdTipoCredito = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Credito.TipoCreditoImpuesto
                    WHERE IdTipoCredito = TRY_CAST(:id AS int))
            THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM Credito.TipoCredito WHERE IdTipoCredito = TRY_CAST(:id AS int)",
    ),
    "redes": AltaBaja(
        campos=(
            Campo("codigo", "Código", maximo=20, patron=_CODIGO),
            Campo("nombre", "Nombre", maximo=60),
            Campo("descripcion", "Descripción", nulo=True, maximo=250),
            Campo("ingresoMinimo", "Ingreso mínimo", "dinero", nulo=True, minimo=0),
            Campo(
                "edadMinima", "Edad mínima", "entero", nulo=True, minimo=16, maximo=99
            ),
            Campo("requiereCuentaActiva", "Requiere cuenta activa", "booleano"),
        ),
        insertar="""
            INSERT INTO ProductosFinancieros.Red (CodigoRed, Nombre, Descripcion, IngresoMinimo,
                EdadMinima, RequiereCuentaActiva)
            OUTPUT CAST(inserted.IdRed AS varchar(10))
            VALUES (:codigo, :nombre, :descripcion, :ingresoMinimo, :edadMinima,
                    :requiereCuentaActiva)
        """,
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM ProductosFinancieros.Producto
                    WHERE IdRed = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Tarjeta.BIN WHERE IdRed = TRY_CAST(:id AS int))
            THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM ProductosFinancieros.Red WHERE IdRed = TRY_CAST(:id AS int)",
    ),
    "denominaciones": AltaBaja(
        campos=(
            Campo("tipoPieza", "Tipo", "opcion", opciones=("Billete", "Moneda")),
            Campo("valor", "Valor", "dinero"),
            Campo("descripcion", "Descripción", maximo=50),
        ),
        insertar="""
            INSERT INTO Catalogo.Denominacion (TipoPieza, Valor, Descripcion)
            OUTPUT CAST(inserted.IdDenominacion AS varchar(10))
            VALUES (:tipoPieza, :valor, :descripcion)
        """,
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM Boveda.BilleteSerie WHERE IdDenominacion = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Boveda.ArqueoBovedaDenominacion WHERE IdDenominacion = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM ATM.Gaveta WHERE IdDenominacion = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Boveda.BovedaDenominacion WHERE IdDenominacion = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Boveda.MovimientoBovedaDenominacion WHERE IdDenominacion = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Caja.DevolucionCajaDenominacion WHERE IdDenominacion = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Caja.DotacionCajaDenominacion WHERE IdDenominacion = TRY_CAST(:id AS int))
            THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM Catalogo.Denominacion WHERE IdDenominacion = TRY_CAST(:id AS int)",
    ),
    "tipos-movimiento-caja": AltaBaja(
        campos=(
            Campo("codigo", "Código", maximo=20, patron=_CODIGO),
            Campo("descripcion", "Descripción", maximo=150),
            Campo("naturaleza", "Naturaleza", "opcion", opciones=("Ingreso", "Egreso")),
        ),
        insertar="""
            INSERT INTO Caja.TipoMovimientoCaja (Codigo, Descripcion, Naturaleza)
            OUTPUT CAST(inserted.IdTipoMovimientoCaja AS varchar(10))
            VALUES (:codigo, :descripcion, CASE :naturaleza WHEN 'Ingreso' THEN 'I' ELSE 'E' END)
        """,
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM Caja.MovimientosCaja
                WHERE IdTipoMovimiento = TRY_CAST(:id AS int)) THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM Caja.TipoMovimientoCaja WHERE IdTipoMovimientoCaja = TRY_CAST(:id AS int)",
    ),
    "actividades-economicas": AltaBaja(
        campos=(
            Campo("descripcion", "Descripción", maximo=200),
            Campo("areaActividad", "Área", maximo=100),
        ),
        insertar="""
            INSERT INTO Catalogo.ActividadEconomica (Descripcion, AreaActividad)
            OUTPUT CAST(inserted.IdActividadEconomica AS varchar(10))
            VALUES (:descripcion, :areaActividad)
        """,
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM Clientes.Cliente
                WHERE IdActividadEconomica = TRY_CAST(:id AS int)) THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM Catalogo.ActividadEconomica WHERE IdActividadEconomica = TRY_CAST(:id AS int)",
    ),
    "tipos-antecedente": AltaBaja(
        campos=(
            Campo("nombre", "Nombre", maximo=150),
            Campo(
                "categoria", "Categoría", "opcion", opciones=("EnRevision", "Critico")
            ),
            Campo(
                "puedeImpedirVinculacion", "Puede impedir la vinculación", "booleano"
            ),
        ),
        insertar="""
            INSERT INTO Catalogo.TipoAntecedente (Nombre, Categoria, PuedeImpedirVinculacion)
            OUTPUT CAST(inserted.IdTipoAntecedente AS varchar(10))
            VALUES (:nombre, :categoria, :puedeImpedirVinculacion)
        """,
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM Clientes.RiesgoCliente
                WHERE IdTipoAntecedente = TRY_CAST(:id AS int)) THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM Catalogo.TipoAntecedente WHERE IdTipoAntecedente = TRY_CAST(:id AS int)",
    ),
    "paises": AltaBaja(
        campos=(
            Campo(
                "codigoPais", "Código (ISO alfa-3)", maximo=3, patron=r"^[A-Za-z]{3}$"
            ),
            Campo("codigoNumerico", "Código numérico", maximo=3, patron=r"^[0-9]{3}$"),
            Campo("nombrePais", "Nombre", maximo=100),
        ),
        insertar="""
            INSERT INTO Catalogo.Paises (CodigoPais, CodigoNumerico, NombrePais)
            OUTPUT inserted.CodigoPais
            VALUES (:codigoPais, :codigoNumerico, :nombrePais)
        """,
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM Catalogo.Ciudad WHERE CodigoPais = :id)
                OR EXISTS (SELECT 1 FROM Clientes.Cliente WHERE CodigoPaisNacionalidad = :id)
                OR EXISTS (SELECT 1 FROM Transacciones.Transaccion WHERE CodigoPaisOrigen = :id)
            THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM Catalogo.Paises WHERE CodigoPais = :id",
    ),
    "ciudades": AltaBaja(
        campos=(
            Campo("codigoPais", "País (ISO alfa-3)", maximo=3, patron=r"^[A-Za-z]{3}$"),
            Campo("provincia", "Provincia", maximo=80),
            Campo("nombre", "Nombre", maximo=80),
        ),
        insertar="""
            INSERT INTO Catalogo.Ciudad (CodigoPais, Provincia, Nombre)
            OUTPUT CAST(inserted.IdCiudad AS varchar(10))
            VALUES (:codigoPais, :provincia, :nombre)
        """,
        en_uso="""
            SELECT CASE WHEN EXISTS (SELECT 1 FROM Organizacion.Agencia WHERE IdCiudad = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Clientes.Direcciones WHERE IdCiudad = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Tarjeta.EnviosTarjeta WHERE IdCiudad = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Transacciones.Transaccion WHERE IdCiudad = TRY_CAST(:id AS int))
                OR EXISTS (SELECT 1 FROM Contabilidad.Feriado WHERE IdCiudad = TRY_CAST(:id AS int))
            THEN 1 ELSE 0 END
        """,
        eliminar="DELETE FROM Catalogo.Ciudad WHERE IdCiudad = TRY_CAST(:id AS int)",
    ),
}

_DUPLICADO = re.compile(r"\((2627|2601)\)")
_REFERENCIA = re.compile(r"\(547\)")


def _error_bd(exc: DBAPIError, *, borrando: bool = False) -> Exception:
    """Duplicados y referencias con su código del criterio; lo demás, al traductor común."""
    texto = str(exc.orig)
    if _DUPLICADO.search(texto):
        return problema(
            409, "CODIGO_DUPLICADO", "Ya existe un registro con ese código o nombre."
        )
    if _REFERENCIA.search(texto):
        if borrando:
            return problema(
                409, "ITEM_EN_USO", "El registro se usa en otros datos: desactívelo."
            )
        return problema(
            422,
            "REFERENCIA_INVALIDA",
            "Hay un dato que apunta a un registro que no existe.",
        )
    return traducir_error_bd(exc)


def _json(datos: dict[str, Any]) -> str:
    """Valores del catálogo para la auditoría (no hay datos personales en los catálogos)."""
    return json.dumps(
        _salida(datos), ensure_ascii=False, separators=(",", ":"), default=str
    )


def _validar_alta(clave: str, valores: dict[str, Any]) -> None:
    """Reglas que cruzan campos, antes de que la base las rechace con un CK (500)."""
    if valores.get("tipoCalculo") == "Porcentaje":
        if valores["valor"] > 100:
            raise _invalido("Valor", "en porcentaje no puede pasar de 100.")
        if clave == "comisiones":
            minimo, maximo = valores["montoMinimo"], valores["montoMaximo"]
            if minimo is None or maximo is None:
                raise _invalido(
                    "Cobro mínimo y máximo", "son obligatorios en una comisión en %."
                )
            if maximo < minimo:
                raise _invalido("Cobro máximo", "debe ser mayor o igual que el mínimo.")
    if (
        clave == "comisiones"
        and valores.get("tipoCalculo") == "Fijo"
        and (valores["montoMinimo"] is not None or valores["montoMaximo"] is not None)
    ):
        raise _invalido("Cobro mínimo y máximo", "solo aplican a comisiones en %.")
    if clave == "canales" and valores["requierePin"] and not valores["requiereTarjeta"]:
        raise _invalido("Requiere PIN", "un canal que pide PIN también pide tarjeta.")


def crear(
    conn: Connection, clave: str, cuerpo: dict[str, Any], usuario: Usuario, ip: str
) -> dict[str, Any]:
    catalogo = _catalogo(clave)
    alta = _ALTA_BAJA.get(clave)
    if alta is None or not alta.campos or alta.insertar is None:
        raise problema(
            422, "ALTA_NO_PERMITIDA", "Este catálogo no admite altas desde aquí."
        )
    nombres = {c.nombre for c in alta.campos}
    desconocidos = set(cuerpo) - nombres
    if desconocidos:
        raise problema(
            400,
            "DATOS_INVALIDOS",
            f"Campos que no se usan al crear: {', '.join(sorted(desconocidos))}.",
        )
    valores = {c.nombre: _valor(c, cuerpo.get(c.nombre)) for c in alta.campos}
    for c in alta.campos:
        if c.patron and isinstance(valores[c.nombre], str):
            valores[c.nombre] = valores[c.nombre].upper()
    _validar_alta(clave, valores)
    with auditar(
        "CREAR",
        catalogo.tabla,
        usuario,
        ip,
        f"CAT-CREAR {clave} despues={_json(valores)}",
    ) as registro:
        try:
            nuevo = conn.execute(text(alta.insertar), valores).scalar()
            if nuevo is None:  # INSERT ... SELECT sin la fila de referencia (el canal)
                raise problema(
                    422,
                    "REFERENCIA_INVALIDA",
                    "Hay un dato que apunta a un registro que no existe o está inactivo.",
                )
            id_ = str(nuevo)
            registro.id_registro = id_
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise _error_bd(exc) from None
        except Exception:
            conn.rollback()
            raise
    fila = _fila(conn, catalogo, id_)
    if fila is None:
        raise problema(500, "ERROR_INTERNO", "Error interno del servidor.")
    return _salida(fila)


def eliminar(conn: Connection, clave: str, id_: str, usuario: Usuario, ip: str) -> None:
    catalogo = _catalogo(clave)
    baja = _ALTA_BAJA.get(clave)
    if baja is None or not baja.eliminar:
        raise problema(
            422,
            "BAJA_NO_PERMITIDA",
            "Este catálogo no admite eliminar: desactive el registro.",
        )
    actual = _fila(conn, catalogo, id_)
    if actual is None:
        raise problema(404, "REGISTRO_NO_ENCONTRADO", "El registro no existe.")
    with auditar(
        "ELIMINAR",
        catalogo.tabla,
        usuario,
        ip,
        f"CAT-ELIMINAR {clave} antes={_json(actual)}",
        id_,
    ):
        try:
            if conn.execute(text(baja.en_uso), {"id": id_}).scalar_one():
                raise problema(
                    409,
                    "ITEM_EN_USO",
                    "El registro se usa en otros datos: desactívelo.",
                )
            conn.execute(text(baja.eliminar), {"id": id_})
            conn.commit()
        except DBAPIError as exc:
            conn.rollback()
            raise _error_bd(exc, borrando=True) from None
        except Exception:
            conn.rollback()
            raise
