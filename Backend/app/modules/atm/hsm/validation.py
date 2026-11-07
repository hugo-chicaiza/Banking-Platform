def derivar_validation_data(pan: str) -> str:
    """Deriva datos de validación para nuestro simulador académico.

    Regla provisional: utilizar los primeros 16 dígitos del PAN ficticio.
    Debe ser idéntica durante la asignación y verificación del PIN.
    """
    if not isinstance(pan, str):
        raise TypeError("PAN ficticio no válido")

    if not pan.isascii() or not pan.isdigit():
        raise ValueError("PAN ficticio no válido")

    if not 16 <= len(pan) <= 19:
        raise ValueError("Longitud de PAN no válida")

    return pan[:16]
