from sqlalchemy import Connection, text

from app.core.api.errors import problema
from app.modules.clientes.relaciones import edad_en, edad_mayoria, relacion_vigente
from app.modules.cuentas.schemas import AutorizadoCuenta, AutorizadoCuentaCreate
from app.modules.parametros.service import hoy


def _titular(conn: Connection, cuenta: int, agencia: str) -> int:
    fila = (
        conn.execute(
            text("""
            SELECT IdCliente, Estado FROM Cuentas.Cuenta WITH (UPDLOCK,HOLDLOCK)
            WHERE IdCuenta=:cuenta AND IdAgencia=:agencia
        """),
            {"cuenta": cuenta, "agencia": agencia},
        )
        .mappings()
        .one_or_none()
    )
    if fila is None:
        raise problema(
            404, "CUENTA_NO_ENCONTRADA", "La cuenta no existe en la agencia activa."
        )
    if fila["Estado"] in ("Anulada", "Cerrada"):
        raise problema(
            409, "CUENTA_NO_OPERABLE", "La cuenta no admite cambios de autorizados."
        )
    return int(fila["IdCliente"])


def agregar(
    conn: Connection, cuenta: int, agencia: str, datos: AutorizadoCuentaCreate
) -> AutorizadoCuenta:
    fecha = hoy()
    with conn.begin():
        titular = _titular(conn, cuenta, agencia)
        cliente = datos.id_cliente_autorizado
        nacimiento = conn.execute(
            text("""
                SELECT FechaNacimiento FROM Clientes.Cliente WITH (HOLDLOCK)
                WHERE IdCliente=:cliente AND Estado='Activo' AND TipoCliente='Natural'
            """),
            {"cliente": cliente},
        ).scalar_one_or_none()
        if (
            cliente == titular
            or nacimiento is None
            or edad_en(nacimiento, fecha) < edad_mayoria(conn, fecha)
        ):
            raise problema(
                422,
                "AUTORIZADO_INVALIDO",
                "Se requiere otro cliente activo y mayor de edad.",
            )
        relacion = None
        if datos.rol != "Firmante":
            relacion = relacion_vigente(conn, titular, datos.rol, fecha)
            if relacion is None or relacion["IdClienteRelacionado"] != cliente:
                raise problema(
                    422,
                    "RELACION_NO_VIGENTE",
                    "El autorizado debe tener una relación vigente de ese tipo.",
                )
        parametros = {
            "cuenta": cuenta,
            "cliente": cliente,
            "rol": datos.rol,
            "fecha": fecha,
        }
        if conn.execute(
            text("""
                SELECT 1 FROM Cuentas.CuentaAutorizado
                WHERE IdCuenta=:cuenta AND Rol=:rol AND (IdClienteAutorizado=:cliente OR Rol<>'Firmante')
                    AND RevocadoEn IS NULL AND FechaInicio<=:fecha
                    AND (FechaFin IS NULL OR FechaFin>=:fecha)
            """),
            parametros,
        ).first():
            raise problema(
                409, "AUTORIZADO_YA_VIGENTE", "Ya existe una autorización vigente."
            )
        fin = relacion["FechaFin"] if relacion else None
        id_aut = conn.execute(
            text("""
                SET NOCOUNT ON;
                DECLARE @nueva TABLE (Id int);
                INSERT Cuentas.CuentaAutorizado
                    (IdCuenta,IdClienteAutorizado,Rol,IdClienteRelacion,FechaInicio,FechaFin)
                OUTPUT inserted.IdCuentaAutorizado INTO @nueva
                VALUES (:cuenta,:cliente,:rol,:relacion,:fecha,:fin);
                SELECT Id FROM @nueva;
            """),
            {
                **parametros,
                "relacion": relacion["IdRelacion"] if relacion else None,
                "fin": fin,
            },
        ).scalar_one()
        return AutorizadoCuenta(
            id_cuenta_autorizado=id_aut,
            id_cliente_autorizado=cliente,
            rol=datos.rol,
            fecha_inicio=fecha,
            fecha_fin=fin,
            vigente=True,
        )


def finalizar(conn: Connection, cuenta: int, id_aut: int, agencia: str) -> None:
    with conn.begin():
        _titular(conn, cuenta, agencia)
        parametros = {"cuenta": cuenta, "id": id_aut, "fecha": hoy()}
        fila = (
            conn.execute(
                text("""
                SELECT FechaInicio, FechaFin, RevocadoEn FROM Cuentas.CuentaAutorizado
                WHERE IdCuenta=:cuenta AND IdCuentaAutorizado=:id
            """),
                parametros,
            )
            .mappings()
            .one_or_none()
        )
        if fila is None:
            raise problema(
                404,
                "AUTORIZADO_NO_ENCONTRADO",
                "El autorizado no existe para esta cuenta.",
            )
        if fila["RevocadoEn"] is not None:
            return
        fecha = parametros["fecha"]
        if fila["FechaInicio"] > fecha or (
            fila["FechaFin"] is not None and fila["FechaFin"] < fecha
        ):
            raise problema(
                409, "AUTORIZADO_NO_VIGENTE", "El autorizado no está vigente."
            )
        conn.execute(
            text("""
                UPDATE Cuentas.CuentaAutorizado SET FechaFin=:fecha, RevocadoEn=SYSUTCDATETIME()
                WHERE IdCuenta=:cuenta AND IdCuentaAutorizado=:id
            """),
            parametros,
        )
