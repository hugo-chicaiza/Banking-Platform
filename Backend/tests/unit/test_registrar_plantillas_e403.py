from scripts.registrar_plantillas_e403 import registrar


def test_registrar_envia_y_recupera_solicitud_sin_duplicar():
    linea = {"lado": "DEBITO", "base": "DIFERENCIA", "origen": "FIJA", "cuenta": 7}
    filas = [
        {
            "idTipoAsiento": 2,
            "borrador": {
                "codigoPlantilla": "CAJA_FALTANTE",
                "idConceptoContable": 3,
                "vigenciaDesde": "2027-01-01",
                "lineas": [linea],
            },
        }
    ]
    posts = []

    def peticion(metodo, ruta, datos=None):
        if metodo == "POST":
            posts.append((ruta, datos))
            return {"idPlantillaAsiento": 4, "idSolicitud": 5}
        if "/plantillas?" in ruta:
            if not posts:
                return []
            return [
                {
                    "IdPlantillaAsiento": 4,
                    "IdTipoAsiento": 2,
                    "IdConceptoContable": 3,
                    "VigenciaDesde": "2027-01-01",
                    "Estado": False,
                }
            ]
        if ruta.endswith("/solicitudes"):
            return {"idSolicitud": 5}
        return {
            "lineas": [
                {
                    "Orden": 1,
                    "TipoMovimiento": "DEBITO",
                    "ComponenteImporte": "DIFERENCIA",
                    "OrigenCuenta": "FIJA",
                    "IdCuentaContable": 7,
                    "CodigoRol": None,
                }
            ]
        }

    registrar(peticion, filas)
    registrar(peticion, filas)
    assert len(posts) == 1
    assert posts[0][0] == "/contabilidad/tipos-asiento/2/plantillas"
