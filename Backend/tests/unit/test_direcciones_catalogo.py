"""E5-10: catálogo consultado en SQL local y protección de campos embebidos."""

from dataclasses import replace
from typing import cast

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from app.modules.catalogos import tipos_direccion
from app.modules.clientes import repository, service
from app.modules.clientes.schemas import (
    Cliente,
    ClientePerfil,
    DireccionUpdate,
    PageCliente,
)
from app.modules.clientes.visibilidad import aplicar_visibilidad
from app.modules.seguridad import funciones
from app.modules.seguridad.funciones_schemas import AutorizacionFunciones
from tests.sesion import usuario_con_roles


@pytest.fixture
def catalogo():
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        conn.execute(text("ATTACH DATABASE ':memory:' AS Catalogo"))
        conn.execute(
            text("CREATE TABLE Catalogo.TipoDireccion (Codigo, Nombre, Estado)")
        )
        conn.execute(
            text("INSERT INTO Catalogo.TipoDireccion VALUES (:codigo,:nombre,:estado)"),
            [
                {"codigo": "Domicilio", "nombre": "Domicilio", "estado": "A"},
                {"codigo": "Temporal", "nombre": "Alojamiento temporal", "estado": "A"},
                {"codigo": "Otra", "nombre": "Otra anterior", "estado": "I"},
            ],
        )
        yield conn
    engine.dispose()


def test_catalogo_incluye_tipo_nuevo_y_nombre_historico(catalogo):
    resultado = {t.codigo: t for t in tipos_direccion.listar(catalogo)}
    assert resultado["Temporal"].nombre == "Alojamiento temporal"
    assert resultado["Otra"].estado == "I"
    tipos_direccion.validar_activo(catalogo, "Temporal")


@pytest.mark.parametrize("codigo", ["Otra", "NoExiste", "Temporal' OR 1=1 --"])
def test_catalogo_rechaza_inactivos_desconocidos_e_inyeccion(catalogo, codigo):
    with pytest.raises(HTTPException) as error:
        tipos_direccion.validar_activo(catalogo, codigo)
    assert error.value.status_code == 422
    detalle = cast(dict[str, object], error.value.detail)
    assert detalle["code"] == "TIPO_DIRECCION_INVALIDO"


@pytest.mark.parametrize("tipo", ["detalle", "listado", "perfil"])
@pytest.mark.parametrize("permite", [False, True])
def test_no_eludir_permiso_en_respuestas_compartidas(monkeypatch, tipo, permite):
    cliente = Cliente.model_construct(
        id_cliente=1, direcciones=[{"calleDireccion": "Privada"}]
    )
    if tipo == "listado":
        resultado = PageCliente(items=[cliente], page=1, page_size=20, total=1)
    elif tipo == "perfil":
        resultado = ClientePerfil(cliente=cliente)
    else:
        resultado = cliente
    monkeypatch.setattr(funciones, "activa", lambda: True)
    monkeypatch.setattr(
        funciones,
        "efectivos",
        lambda _: AutorizacionFunciones(
            version="a" * 64,
            funciones=["clientes.direcciones.consultar"] if permite else [],
            rutas=["/"],
        ),
    )
    usuario = replace(usuario_con_roles("ASESOR"), id_usuario="qa")
    filtrado = aplicar_visibilidad(resultado, usuario)
    visto = (
        filtrado.items[0]
        if isinstance(filtrado, PageCliente)
        else filtrado.cliente
        if isinstance(filtrado, ClientePerfil)
        else filtrado
    )
    assert bool(visto.direcciones) == permite
    assert cliente.direcciones  # No muta un objeto de caché compartido.


def test_control_apagado_conserva_contrato_anterior(monkeypatch):
    monkeypatch.setattr(funciones, "activa", lambda: False)
    cliente = Cliente.model_construct(direcciones=[{"calleDireccion": "Conservada"}])
    assert aplicar_visibilidad(cliente, usuario_con_roles("ASESOR")) is cliente


def test_consulta_sql_incluye_retiradas_sin_mezclar_clientes(catalogo):
    catalogo.execute(text("ATTACH DATABASE ':memory:' AS Clientes"))
    catalogo.execute(text("CREATE TABLE Catalogo.Ciudad (IdCiudad, CodigoPais)"))
    catalogo.execute(text("INSERT INTO Catalogo.Ciudad VALUES (1, 'ECU')"))
    catalogo.execute(
        text("""CREATE TABLE Clientes.Direcciones (
        IdCliente, IdDireccion, TipoDireccion, IdCiudad, Sector, CalleDireccion,
        ReferenciaUbicacion, CodigoPostal, EsPrincipal, Estado)""")
    )
    catalogo.execute(
        text("""INSERT INTO Clientes.Direcciones VALUES
        (1,1,'Domicilio',1,NULL,'Casa','Parque',NULL,1,'Activo'),
        (1,2,'Trabajo',1,NULL,'Anterior','Parque',NULL,0,'Inactivo'),
        (1,3,'Otra',1,NULL,'Retirada','Parque',NULL,0,'Eliminado'),
        (2,4,'Domicilio',1,NULL,'Otro cliente','Parque',NULL,1,'Activo')""")
    )
    filas = repository.listar_direcciones(catalogo, 1)
    assert {f["estado"] for f in filas} == {"Activo", "Inactivo", "Eliminado"}
    assert {f["id_direccion"] for f in filas} == {1, 2, 3}
    retirada = repository.obtener_direccion(catalogo, 1, 3)
    assert retirada is not None
    assert retirada["estado"] == "Eliminado"
    assert repository.obtener_direccion(catalogo, 2, 3) is None
    catalogo.execute(text("CREATE TABLE Catalogo.Paises (CodigoPais)"))
    catalogo.execute(text("INSERT INTO Catalogo.Paises VALUES ('ECU')"))
    catalogo.execute(
        text("CREATE TABLE Clientes.Cliente (IdCliente, Identificacion, Estado)")
    )
    catalogo.execute(
        text("INSERT INTO Clientes.Cliente VALUES (1, '0100000025', 'Activo')")
    )
    assert repository.existe_pais(catalogo, "ECU")
    assert not repository.existe_pais(catalogo, "COL")
    assert repository.existe_ciudad(catalogo, 1, "ECU")
    assert not repository.existe_ciudad(catalogo, 1, "COL")
    cliente = repository.obtener_cliente_por_identificacion(catalogo, "0100000025")
    assert cliente is not None
    assert cliente["id_cliente"] == 1


@pytest.mark.parametrize("cambia_tipo", [False, True])
def test_editar_conserva_tipo_retirado_pero_no_lo_asigna_de_nuevo(
    catalogo, monkeypatch, cambia_tipo
):
    actual = {
        "id_direccion": 1,
        "tipo_direccion": "Domicilio" if cambia_tipo else "Otra",
        "codigo_pais": "ECU",
        "id_ciudad": 1,
        "sector": None,
        "calle_direccion": "Casa",
        "referencia_ubicacion": "Parque",
        "codigo_postal": None,
        "es_principal": True,
        "estado": "Activo",
    }
    monkeypatch.setattr(
        repository, "bloquear_cliente", lambda *args: {"estado": "Activo"}
    )
    monkeypatch.setattr(repository, "obtener_direccion", lambda *args: actual)
    monkeypatch.setattr(
        repository,
        "actualizar_direccion",
        lambda conn, cliente, id_, cambios, **kwargs: {**actual, **cambios},
    )
    payload = DireccionUpdate(tipo_direccion="Otra", calle_direccion="Casa editada")
    if cambia_tipo:
        with pytest.raises(HTTPException) as error:
            service.editar_direccion(catalogo, 1, 1, payload, 1, "127.0.0.1")
        assert error.value.status_code == 422
    else:
        resultado = service.editar_direccion(catalogo, 1, 1, payload, 1, "127.0.0.1")
        assert resultado.tipo_direccion == "Otra"
        assert resultado.calle_direccion == "Casa editada"
