"""Ejecutor de migraciones con bitácora (E0-01). **Apagado por defecto.**

Reglas:
- Solo con el login administrativo (cadena `MIGRACIONES_ODBC_<BASE>`); con el login de
  la aplicación se niega (ASVS 13.3.1, 15.2.3).
- `aplicar` requiere `MIGRACIONES_HABILITADAS=true`; `estado` solo lee.
- Antes de aplicar nada compara la suma SHA-256 de cada migración ya aplicada: si un
  archivo cambió, se detiene y nombra el archivo (PCI E-207 a E-211).
- Cada archivo va en una transacción con su registro en la bitácora: si falla, se
  revierte completo y no queda registrado. Repetir sin archivos nuevos no cambia nada.
- Fija `SESSION_CONTEXT('migration_database')` = la base verificada, que las migraciones
  exigen antes de tocar nada.
"""

import time
from dataclasses import dataclass, field
from typing import Protocol

from app.core.migraciones.archivos import LINEA_BASE, Migracion, lotes

BITACORA_SQL = """
IF SCHEMA_ID('Migracion') IS NULL EXEC ('CREATE SCHEMA Migracion');
IF OBJECT_ID('Migracion.Bitacora', 'U') IS NULL
CREATE TABLE Migracion.Bitacora (
    IdMigracion     int IDENTITY(1,1) NOT NULL CONSTRAINT PK_MigracionBitacora PRIMARY KEY,
    Archivo         varchar(200)  NOT NULL CONSTRAINT UQ_MigracionBitacora_Archivo UNIQUE,
    SumaSha256      binary(32)    NOT NULL,
    AplicadaUTC     datetime2     NOT NULL CONSTRAINT DF_MigracionBitacora_Fecha DEFAULT (SYSUTCDATETIME()),
    AplicadaPor     sysname       NOT NULL CONSTRAINT DF_MigracionBitacora_Por DEFAULT (ORIGINAL_LOGIN()),
    DuracionMs      int           NOT NULL,
    EsLineaBase     bit           NOT NULL CONSTRAINT DF_MigracionBitacora_Base DEFAULT (0),
    VersionProducto varchar(20)   NULL
);
"""


class Sql(Protocol):
    """Lo mínimo que el ejecutor necesita de una conexión (real o de prueba)."""

    def valor(self, sql: str, **params: object) -> object: ...
    def filas(self, sql: str, **params: object) -> list[tuple]: ...
    def ejecutar(self, sql: str, **params: object) -> None: ...
    def confirmar(self) -> None: ...
    def revertir(self) -> None: ...


class MigracionRechazada(RuntimeError):
    """El ejecutor se niega a correr (login, flag, base equivocada, archivo alterado)."""


@dataclass
class Estado:
    base: str
    bitacora_instalada: bool
    aplicadas: list[str] = field(default_factory=list)
    pendientes: list[str] = field(default_factory=list)
    alteradas: list[str] = field(default_factory=list)
    desconocidas: list[str] = field(
        default_factory=list
    )  # en la bitácora pero sin archivo


class Ejecutor:
    def __init__(
        self,
        sql: Sql,
        *,
        base: str,
        nombre_base: str,
        login_aplicacion: str,
        migraciones: list[Migracion],
        habilitado: bool,
        version: str | None = None,
    ) -> None:
        self._sql = sql
        self._base = base
        self._nombre_base = nombre_base
        self._login_app = login_aplicacion.strip().lower()
        self._migraciones = migraciones
        self._habilitado = habilitado
        self._version = version

    # --- verificaciones ---------------------------------------------------------
    def _verificar_conexion(self) -> None:
        base = str(self._sql.valor("SELECT DB_NAME()"))
        if base != self._nombre_base:
            raise MigracionRechazada(
                f"la conexión apunta a {base}, se esperaba {self._nombre_base}"
            )
        login = str(self._sql.valor("SELECT ORIGINAL_LOGIN()")).strip().lower()
        if self._login_app and login == self._login_app:
            raise MigracionRechazada(
                "las migraciones no corren con el login de la aplicación; use el login administrativo"
            )

    def _bitacora(self) -> dict[str, bytes] | None:
        if not self._sql.valor("SELECT OBJECT_ID('Migracion.Bitacora', 'U')"):
            return None
        return {
            str(archivo): bytes(suma)
            for archivo, suma in self._sql.filas(
                "SELECT Archivo, SumaSha256 FROM Migracion.Bitacora"
            )
        }

    def estado(self) -> Estado:
        self._verificar_conexion()
        registradas = self._bitacora()
        estado = Estado(self._base, registradas is not None)
        registradas = registradas or {}
        archivos = {m.archivo for m in self._migraciones}
        for m in self._migraciones:
            if m.archivo not in registradas:
                estado.pendientes.append(m.archivo)
            elif registradas[m.archivo] != m.sha256:
                estado.alteradas.append(m.archivo)
            else:
                estado.aplicadas.append(m.archivo)
        estado.desconocidas = sorted(set(registradas) - archivos)
        return estado

    # --- aplicar ----------------------------------------------------------------
    def _registrar(self, m: Migracion, duracion_ms: int, linea_base: bool) -> None:
        self._sql.ejecutar(
            "INSERT INTO Migracion.Bitacora (Archivo, SumaSha256, DuracionMs, EsLineaBase, VersionProducto) "
            "VALUES (:archivo, :suma, :ms, :base, :version)",
            archivo=m.archivo,
            suma=m.sha256,
            ms=duracion_ms,
            base=1 if linea_base else 0,
            version=self._version,
        )

    def aplicar(self, *, marcar_linea_base: bool = False) -> list[str]:
        """Aplica las pendientes en orden y devuelve sus nombres. Con
        `marcar_linea_base` la migración cero se registra sin ejecutarla (la base
        compartida ya tiene esa estructura)."""
        if not self._habilitado:
            raise MigracionRechazada(
                "el ejecutor está apagado (MIGRACIONES_HABILITADAS=false)"
            )
        estado = self.estado()
        if estado.alteradas:
            raise MigracionRechazada(
                "migraciones aplicadas cuyo archivo cambió (suma SHA-256 distinta): "
                + ", ".join(estado.alteradas)
                + ". Una migración aplicada no se edita: la corrección es una migración nueva."
            )
        if not estado.bitacora_instalada:
            self._sql.ejecutar(BITACORA_SQL)
            if self._login_app:
                # Solo el login administrativo escribe la bitácora
                self._sql.ejecutar(
                    "DECLARE @u sysname = (SELECT name FROM sys.database_principals WHERE sid = SUSER_SID(:login)); "
                    "IF @u IS NOT NULL EXEC ('DENY INSERT, UPDATE, DELETE ON Migracion.Bitacora TO ' + QUOTENAME(@u));",
                    login=self._login_app,
                )
            self._sql.confirmar()
        aplicadas: list[str] = []
        for m in self._migraciones:
            if m.archivo not in estado.pendientes:
                continue
            inicio = time.perf_counter()
            try:
                if m.es_linea_base and marcar_linea_base:
                    self._registrar(m, 0, True)
                else:
                    self._sql.ejecutar(
                        "EXEC sys.sp_set_session_context @key = N'migration_database', @value = :base",
                        base=self._nombre_base,
                    )
                    for lote in lotes(m.contenido):
                        self._sql.ejecutar(lote)
                    self._registrar(
                        m,
                        int((time.perf_counter() - inicio) * 1000),
                        m.archivo == LINEA_BASE,
                    )
                self._sql.confirmar()
            except Exception:
                self._sql.revertir()
                raise
            aplicadas.append(m.archivo)
        return aplicadas
