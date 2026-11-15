"""Administración de catálogos: ADMIN edita y activa o desactiva; ADMIN y ASESOR consultan.

Cada catálogo declara sus campos aquí (una sola fuente: el frontend dibuja la tabla y el
formulario con esta descripción). Los campos que cambian reglas de negocio quedan de solo
lectura: valor y tipo de una denominación, naturaleza de un movimiento de caja, requisitos
de seguridad de un canal y la categoría de un antecedente (la regla C-08 depende de ella).
Nada se borra: la baja es por Estado. Fuera de aquí: agencias, productos y plan de cuentas,
que tienen su propia pantalla.

El SQL de cada catálogo es fijo (sin armar nombres de tabla o columna con texto).
"""

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

# numero: >= 0 con hasta 6 decimales (valor de comisión o seguro; en % si es Porcentaje)
TipoCampo = Literal[
    "texto", "entero", "dinero", "porcentaje", "numero", "booleano", "fecha"
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


def descriptores() -> list[dict[str, Any]]:
    return [
        {
            "clave": c.clave,
            "nombre": c.nombre,
            "descripcion": c.descripcion,
            "permiteCrear": c.permite_crear,
            "campos": [
                {
                    "nombre": f.nombre,
                    "etiqueta": f.etiqueta,
                    "tipo": f.tipo,
                    "editable": f.editable,
                    "nulo": f.nulo,
                    "maximo": f.maximo,
                    "minimo": f.minimo,
                }
                for f in c.campos
            ],
        }
        for c in CATALOGOS.values()
    ]


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
        if campo.maximo and len(valor) > campo.maximo:
            raise _invalido(
                campo.etiqueta, f"usa {campo.maximo} caracteres como máximo."
            )
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
    conn: Connection, actual: dict[str, Any], cambios: dict[str, Any]
) -> None:
    """Una tasa de crédito necesita plazo y no puede solaparse con otra del mismo tipo de
    crédito. Cuenta también las inactivas: Credito.usp_EvaluarSolicitudCredito no filtra
    por Estado y con dos tasas lanza 55103. Ahorro y tarjeta pueden coexistir."""
    final = {**actual, **cambios}
    minimo, maximo = final["montoMinimo"], final["montoMaximo"]
    if minimo is not None and maximo is not None and maximo < minimo:
        raise _invalido("Monto máximo", "debe ser mayor o igual que el mínimo.")
    if final["tipoTasa"] != "CREDITO":
        return
    if final["plazoMaximoMeses"] is None:
        raise _invalido("Plazo máximo (meses)", "es obligatorio en tasas de crédito.")
    hasta = final["vigenciaHasta"]
    solapadas = conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM Credito.TasaInteres WITH (UPDLOCK, HOLDLOCK)
            WHERE IdTipoCredito = :tipo AND TipoTasa = 'CREDITO'
              AND IdTasaInteres <> TRY_CAST(:id AS int)
              AND VigenciaDesde <= ISNULL(:hasta, '9999-12-31')
              AND :desde <= ISNULL(VigenciaHasta, '9999-12-31')
              AND ISNULL(MontoMinimo, 0) <= ISNULL(:maximo, 9999999999999999)
              AND ISNULL(:minimo, 0) <= ISNULL(MontoMaximo, 9999999999999999)
            """
        ),
        {
            "tipo": actual["idTipoCredito"],
            "id": actual["id"],
            "desde": final["vigenciaDesde"],
            "hasta": hasta,
            "minimo": minimo,
            "maximo": maximo,
        },
    ).scalar_one()
    if solapadas:
        raise problema(
            409,
            "TASA_SOLAPADA",
            "Ya hay una tasa de ese tipo de crédito para ese rango de monto en esas fechas.",
        )


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
    with auditar(
        "ACTUALIZAR",
        catalogo.tabla,
        usuario,
        ip,
        f"CAT-EDITAR {clave} campos={','.join(sorted(cambios))}",
        id_,
    ):
        try:
            actual = _fila(conn, catalogo, id_)
            if actual is None:
                raise problema(404, "REGISTRO_NO_ENCONTRADO", "El registro no existe.")
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
            raise traducir_error_bd(exc) from None
        except Exception:
            conn.rollback()
            raise
    fila = _fila(conn, catalogo, id_)
    if fila is None:
        raise problema(500, "ERROR_INTERNO", "Error interno del servidor.")
    return _salida(fila)
