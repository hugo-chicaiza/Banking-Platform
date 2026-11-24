from calendar import monthrange
from datetime import date

from sqlalchemy import Connection

from app.core.api.errors import problema
from app.modules.clientes import repository
from app.modules.parametros.general import valor


def motivos_no_habilitado(conn: Connection, id_cliente: int, hoy: date) -> list[str]:
    """Comprueba la habilitación y serializa con cambios de estado y de riesgo."""
    cliente = repository.bloquear_cliente(conn, id_cliente)
    if cliente is None or cliente["estado"] != "Activo":
        return ["CLIENTE_NO_ACTIVO"]

    motivos = []
    consentimiento = cliente["fecha_consentimiento"]
    if (
        not cliente["consentimiento_datos"]
        or consentimiento is None
        or consentimiento.date() > hoy
    ):
        motivos.append("CONSENTIMIENTO_NO_VIGENTE")

    riesgo = repository.riesgo_para_habilitacion(conn, id_cliente)
    if riesgo is None or riesgo["resultado"] != "Aprobado":
        motivos.append("RIESGO_NO_APROBADO")
    else:
        fecha = riesgo["fecha"]
        meses = valor(
            conn, f"CLI_RIESGO_VIGENCIA_{riesgo['nivel'].upper()}_MESES", fecha
        )
        if type(meses) is not int or meses < 1:
            raise problema(
                503,
                "VIGENCIA_RIESGO_NO_CONFIGURADA",
                "No se pudo verificar la vigencia del riesgo.",
            )
        anio, mes = divmod(fecha.year * 12 + fecha.month - 1 + meses, 12)
        vence = date(anio, mes + 1, min(fecha.day, monthrange(anio, mes + 1)[1]))
        if not fecha <= hoy <= vence:
            motivos.append("RIESGO_NO_VIGENTE")
        if riesgo["tiene_antecedentes"] and riesgo["impide_vinculacion"] != 0:
            motivos.append("ANTECEDENTE_IMPIDE_VINCULACION")
        # CLI-13 todavía no registra una segunda aprobación verificable.
        if riesgo["es_pep"] or riesgo["nivel"] == "Alto":
            motivos.append("APROBACION_CUMPLIMIENTO_NO_VERIFICABLE")

    if valor(conn, "CLI_EXIGE_ARCHIVOS", hoy) is True:
        motivos.append("ARCHIVOS_OBLIGATORIOS_NO_VERIFICABLES")
    return motivos


def exigir_cliente_habilitado(conn: Connection, id_cliente: int, hoy: date) -> None:
    motivos = motivos_no_habilitado(conn, id_cliente, hoy)
    if motivos:
        raise problema(
            409,
            "CLIENTE_NO_HABILITADO",
            "El cliente no está habilitado para recibir el producto.",
            bloqueos=motivos,
        )
