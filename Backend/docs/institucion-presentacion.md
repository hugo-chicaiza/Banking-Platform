# E0-12 #353 · Presentación institucional

`GET /api/v1/institucion` es una consulta pública mínima, sin sesión ni llamadas a WorkOS. El Worker sigue siendo el proxy del entorno desplegado. No modifica la autorización de `/api/v1/organizacion/entidad`.

Respuesta 200: `nombre: string|null`, `sitioWeb: string|null`, `logoUrl: null`, `origen: ENTIDAD|ENTORNO|SIN_CONFIGURAR`. Cache-Control: no-store. Logo reservado y sin implementación en este cambio.

1. Si existe Entidad (IdEntidad=1), nombre comercial sin espacios exteriores; si está vacío, razón social. La web corresponde solo a esa Entidad. No mezclar con la web de otra configuración.
2. Si no hay Entidad o aún no se configuró servidor SQL, usar COOPERATIVA_NOMBRE y COOPERATIVA_SITIO_WEB explícitos. Ambos dejan de tener datos institucionales de ejemplo por defecto.
3. Sin nombre, devolver null y SIN_CONFIGURAR; frontend muestra Sistema de gestión. La configuración inicial permanece accesible para ADMIN. La web es opcional y solo se presenta como enlace si es HTTPS sin credenciales.
4. Un error de conexión/consulta SQL devuelve 503 INSTITUCION_NO_DISPONIBLE, sin detalles privados. No se responde como instalación vacía. El frontend conserva el último resultado válido o usa presentación genérica; esto no bloquea el login.

El SELECT público solo solicita NombreComercial, RazonSocial y SitioWeb: no RUC, representante, contactos ni auditoría. No agrega columnas, migraciones, permisos de Entidad ni un nuevo servicio de logos.

La referencia completa de Settings se genera en configuracion-generada.md con `python Backend/scripts/referencia_configuracion.py`. Describe los defaults del código, no secretos ni la configuración efectiva de Azure. El arranque/validaciones de las demás integraciones no se reestructura con este endpoint.

El contrato se exporta por módulo mediante el mecanismo existente `Backend/scripts/contrato.py`; la nueva respuesta tiene su módulo `institucion`.
