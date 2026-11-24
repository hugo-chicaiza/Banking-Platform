"""Formulario de apertura E6-01 generado en memoria con E0-18."""

from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.core.pdf import DocumentoPdf, institucion_actual
from app.modules.parametros.service import hoy
from app.modules.productos.repository import condiciones_vigentes


def formulario_apertura(
    conn: Connection, id_cuenta: int, agencia: str, generado_por: str
) -> bytes:
    datos = (
        conn.execute(
            text("""
            SELECT c.NumeroCuenta, c.IdAgencia, s.IdSubProducto, s.NombreSubProducto,
                   cl.Identificacion, cl.Nombres, cl.Apellidos, cl.RazonSocial
            FROM Cuentas.Cuenta AS c
            JOIN Clientes.Cliente AS cl ON cl.IdCliente = c.IdCliente
            JOIN ProductosFinancieros.SubProducto AS s ON s.IdSubProducto = c.IdSubProducto
            WHERE c.IdCuenta = :cuenta AND c.IdAgencia = :agencia
        """),
            {"cuenta": id_cuenta, "agencia": agencia},
        )
        .mappings()
        .first()
    )
    if datos is None:
        raise problema(
            404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia activa."
        )

    fecha = hoy()
    condiciones = condiciones_vigentes(conn, datos["IdSubProducto"], fecha, "FICHA")
    if condiciones is None:
        raise problema(
            409,
            "CONDICIONES_NO_VIGENTES",
            "No existen condiciones vigentes para emitir el formulario.",
        )
    titular = datos["RazonSocial"] or " ".join(
        valor for valor in (datos["Nombres"], datos["Apellidos"]) if valor
    )
    titulo = "Formulario de apertura de cuenta"
    doc = DocumentoPdf(
        titulo, institucion=institucion_actual(conn), generado_por=generado_por
    )
    doc.titulo(titulo)
    doc.campos(
        [
            ("Titular", titular),
            ("Identificación", datos["Identificacion"]),
            ("Cuenta", datos["NumeroCuenta"]),
            ("Agencia", datos["IdAgencia"]),
            ("Subproducto", datos["NombreSubProducto"]),
        ]
    )
    doc.subtitulo("Condiciones vigentes")
    doc.campos(
        [
            ("Fecha de consulta", fecha.isoformat()),
            ("Depósito mínimo (USD)", condiciones["monto_apertura_minimo"]),
            ("Saldo mínimo (USD)", condiciones["saldo_minimo"]),
            ("Interés anual (%)", condiciones["tasa_interes_anual"]),
            ("Mantenimiento (USD)", condiciones["costo_mantenimiento"]),
            ("Periodicidad del interés", condiciones["periodicidad_interes"]),
            ("Periodicidad del costo", condiciones["periodicidad_costo"]),
        ]
    )
    doc.subtitulo("Firmas")
    doc.espacio(12)
    doc.parrafo("_______________________________    _______________________________")
    doc.parrafo("Titular o representante                         Asesor de apertura")
    return doc.contenido()
