"""Asignación ficticia estable para fixtures, sin conexiones ni secretos."""

from datetime import datetime

FECHA_PIN = datetime(2026, 11, 1, 10, 0, 0)
VERSION_PIN = "2026-11-01T10:00:00.000000"


class DriverLimitesSQL:
    """Superficie ODBC local para comprobar límites sin abrir conexiones."""

    def __init__(self):
        self.timeout = 0
        self.lock_timeout = -1
        self.nocount = False
        self.sentencias = []

    def cursor(self):
        return CursorLimitesSQL(self)


class CursorLimitesSQL:
    def __init__(self, driver):
        self.driver = driver

    def execute(self, sql):
        self.driver.sentencias.append(sql)
        if sql.startswith("SET LOCK_TIMEOUT "):
            self.driver.lock_timeout = int(sql.split()[-1])
        if sql.startswith("SET NOCOUNT "):
            self.driver.nocount = sql.endswith("ON")
        return self

    def fetchone(self):
        return (self.driver.lock_timeout, 512 if self.driver.nocount else 0)

    def fetchval(self):
        return self.driver.lock_timeout

    def close(self):
        pass
