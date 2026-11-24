"""Conciliación de correo contra el valor confirmado en SeguridadDB."""

from sqlalchemy import Connection, Engine, text

from app.core.api.errors import problema
from app.integrations.workos_client import get_workos
from app.modules.auth import repository, service


def registrar(
    engine: Engine,
    usuario: int,
    llave: str,
    operacion: str = "Email",
    *,
    correo_alterno: str | None = None,
) -> int:
    # Se confirma antes de llamar al proveedor. El llamador mantiene bloqueado al usuario.
    with engine.begin() as conn:
        if conn.scalar(
            text("""
                SELECT TOP (1) 1 FROM Seguridad.SincronizacionProveedor
                WHERE UsuarioID=:id AND Estado='Pendiente'
            """),
            {"id": usuario},
        ):
            raise problema(
                409,
                "USUARIO_EN_CONCILIACION",
                "El usuario tiene una conciliación pendiente.",
            )
        return conn.execute(
            text("""
                INSERT Seguridad.SincronizacionProveedor(UsuarioID, Operacion, LlaveProveedor, CorreoAlterno)
                OUTPUT inserted.IdSincronizacion VALUES(:id, :operacion, :llave, :correo)
            """),
            {
                "id": usuario,
                "llave": llave,
                "operacion": operacion,
                "correo": correo_alterno,
            },
        ).scalar_one()


def confirmar(llave: str, correo: str) -> None:
    with service._workos("get_user"):
        remoto = get_workos().user_management.get_user(llave)
    if remoto.email.casefold() != correo.casefold():
        raise problema(
            503, "CORREO_EN_CONCILIACION", "WorkOS aún no confirma el correo."
        )


def confirmar_roles(llave: str, roles: tuple[str, ...]) -> None:
    miembro = service._membresia(llave)
    if miembro is None or service._slugs(miembro) != {
        service.slug_rol(rol) for rol in roles
    }:
        raise problema(
            503, "ROLES_PENDIENTES_CONFIRMACION", "WorkOS aún no confirma los roles."
        )


def completar(conn: Connection, id_: int) -> None:
    conn.execute(
        text("""
            UPDATE Seguridad.SincronizacionProveedor SET Estado='Completada',
                   FechaCompletado=SYSUTCDATETIME(), UltimoCodigoError=NULL,
                   CorreoAlterno=NULL
            WHERE IdSincronizacion=:id AND Estado='Pendiente'
        """),
        {"id": id_},
    )


def pendientes(engine: Engine) -> list[tuple[int, int]]:
    with engine.connect() as conn:
        return [
            (r.IdSincronizacion, r.UsuarioID)
            for r in conn.execute(
                text("""
                SELECT TOP (100) IdSincronizacion,UsuarioID
                FROM Seguridad.SincronizacionProveedor
                WHERE Estado='Pendiente' AND Operacion IN ('Email','Roles','Invitar')
                ORDER BY ISNULL(FechaUltimoIntento, FechaCreacion), IdSincronizacion
            """)
            )
        ]


def reconciliar(engine: Engine, id_: int, usuario: int) -> None:
    from app.modules.auth.aprobacion_roles import corte_protegido

    with corte_protegido(), engine.begin() as conn:
        service._serializar_cambios_administrativos(conn)
        fila = repository.obtener_usuario(conn, usuario, bloquear=True)
        trabajo = conn.execute(
            text("""
                SELECT LlaveProveedor,Operacion,CorreoAlterno FROM Seguridad.SincronizacionProveedor
                WHERE IdSincronizacion=:id AND UsuarioID=:usuario
                  AND Operacion IN ('Email','Roles','Invitar') AND Estado='Pendiente'
            """),
            {"id": id_, "usuario": usuario},
        ).first()
        if trabajo is None:
            return
        llave, operacion, alterno = trabajo
        if operacion == "Invitar":
            if fila is None or fila["KeyUsuario"]:
                raise problema(409, "VINCULO_CAMBIADO", "El vínculo requiere revisión.")
            anteriores = service._invitaciones_pendientes(fila["Email"])
            otra = (
                service._invitaciones_pendientes(alterno)
                if alterno and alterno != fila["Email"]
                else None
            )
            if len(anteriores) == 1 and anteriores[0].id == llave and not otra:
                completar(conn, id_)
                return
            # El SDK no publica el rol de una invitación ni acepta una clave idempotente.
            raise problema(
                409,
                "INVITACION_REQUIERE_REVISION",
                "La invitación requiere verificación institucional.",
            )
        if fila is None or fila["KeyUsuario"] != llave:
            raise problema(409, "VINCULO_CAMBIADO", "El vínculo requiere revisión.")
        gestion = get_workos().user_management
        if operacion == "Roles":
            roles = service._roles(fila)
            miembro = service._membresia(llave)
            if miembro is None or not roles:
                raise problema(
                    409, "ROLES_DESINCRONIZADOS", "La membresía requiere revisión."
                )
            slugs = sorted(service.slug_rol(rol) for rol in roles)
            if service._slugs(miembro) != set(slugs):
                if "ADMIN" not in roles:
                    service._validar_ultimo_admin(conn, fila)
                with service._workos("reconciliar_roles"):
                    gestion.update_organization_membership(
                        organization_membership_id=miembro.id,
                        **service._parametros_roles_workos(slugs),
                    )
            confirmar_roles(llave, roles)
            service._revocar_sesiones(llave)
            completar(conn, id_)
            return
        with service._workos("reconciliar_email"):
            if gestion.get_user(llave).email.casefold() != fila["Email"].casefold():
                gestion.update_user(user_id=llave, email=fila["Email"])
        confirmar(llave, fila["Email"])
        completar(conn, id_)


def registrar_error(engine: Engine, id_: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("""
                UPDATE Seguridad.SincronizacionProveedor
                SET Intentos=Intentos+1, FechaUltimoIntento=SYSUTCDATETIME(),
                    UltimoCodigoError='CONCILIACION_PENDIENTE'
                WHERE IdSincronizacion=:id AND Estado='Pendiente'
            """),
            {"id": id_},
        )
