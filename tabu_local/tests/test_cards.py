import json

import pytest

from cards.card_generator import CardGenerator
from cards.card_validator import validar_mazo, validar_tarjeta
from cards.deck import (Mazo, MazoAgotadoError, Tarjeta, TarjetasInvalidasError, cargar_tarjetas,
                        leer_json_tarjetas)
from config import CARDS_DIR
from models.fake_client import ScriptedClient

MAZO = CARDS_DIR / "cards.json"


def tarjeta(**cambios):
    base = {"id": "x1", "secreta": "perro", "prohibidas": ["ladrar", "mascota", "hueso"],
            "prohibidas_extra": [], "categoria": "animales", "dificultad": "facil", "variantes": []}
    base.update(cambios)
    return base


# ------------------------------------------------------------- mazo incluido
def test_mazo_base_valido_y_suficiente():
    resultados, globales = validar_mazo(leer_json_tarjetas(MAZO))
    assert globales == []
    assert all(r.valida for r in resultados), [r.errores for r in resultados if not r.valida]
    tarjetas = cargar_tarjetas(MAZO)
    assert len(tarjetas) >= 40
    # todas sirven para la condición de 7 prohibidas del experimento
    assert all(t.max_prohibidas >= 7 for t in tarjetas)
    assert all(3 <= len(t.prohibidas) <= 5 for t in tarjetas)


# --------------------------------------------------------------- validador
@pytest.mark.parametrize("cambios,fragmento", [
    ({"prohibidas": ["ladrar", "hueso"]}, "entre 3 y 5"),
    ({"prohibidas": ["ladrar", "hueso", "Ladrar"]}, "repetida"),
    ({"prohibidas": ["ladrar", "hueso", "perros"]}, "propia palabra secreta"),
    ({"prohibidas": ["ladrar", "hueso", "que"]}, "palabra vacía"),
    ({"categoria": "inventada"}, "Categoría"),
    ({"dificultad": "extrema"}, "Dificultad"),
    ({"secreta": ""}, "vacía"),
    ({"prohibidas_extra": ["a1", "b2", "c3", "d4", "e5"]}, "extra"),
])
def test_validador_detecta_errores(cambios, fragmento):
    r = validar_tarjeta(tarjeta(**cambios))
    assert not r.valida
    assert any(fragmento.lower() in e.lower() for e in r.errores), r.errores


def test_validador_avisa_derivado_redundante():
    r = validar_tarjeta(tarjeta(prohibidas=["ladrar", "hueso", "perrera"]))
    assert r.valida and any("derivado" in a for a in r.avisos)


def test_secretas_repetidas_en_mazo():
    _, globales = validar_mazo([tarjeta(id="a"), tarjeta(id="b", secreta="Perros")])
    assert any("repetida" in g for g in globales)


def test_cargar_estricto_rechaza(tmp_path):
    ruta = tmp_path / "malas.json"
    ruta.write_text(json.dumps({"tarjetas": [tarjeta(prohibidas=["x"])]}), encoding="utf-8")
    with pytest.raises(TarjetasInvalidasError):
        cargar_tarjetas(ruta, estricto=True)
    assert cargar_tarjetas(ruta, estricto=False) == []


# -------------------------------------------------------------------- mazo
def test_prohibidas_para_condiciones_anidadas(tarjeta_perro):
    tres, cinco, siete = (tarjeta_perro.prohibidas_para(n) for n in (3, 5, 7))
    assert tres == cinco[:3] and cinco == siete[:5] and len(siete) == 7
    with pytest.raises(ValueError):
        tarjeta_perro.prohibidas_para(8)


def test_mazo_sin_repeticiones():
    tarjetas = cargar_tarjetas(MAZO)
    mazo = Mazo(tarjetas, semilla=1)
    vistas = [mazo.robar().id for _ in range(len(tarjetas))]
    assert len(set(vistas)) == len(tarjetas)
    with pytest.raises(MazoAgotadoError):
        mazo.robar()


def test_mazo_filtros_y_semilla():
    tarjetas = cargar_tarjetas(MAZO)
    a = Mazo(tarjetas, semilla=5, dificultades=["dificil"])
    assert all(t.dificultad == "dificil" for t in [a.robar() for _ in range(len(a))])
    assert Mazo(tarjetas, semilla=5).robar() == Mazo(tarjetas, semilla=5).robar()


# --------------------------------------------------------------- generador
def test_generador_acepta_y_rechaza():
    buena = ('{"secreta": "camello", "prohibidas": ["joroba", "desierto", "animal", "arena", '
             '"agua", "dromedario", "caravana"], "variantes": ["camel"]}')
    repetida = ('{"secreta": "perro", "prohibidas": ["a1", "b2", "c3", "d4", "e5", "f6", "g7"]}')
    cliente = ScriptedClient({"gen": [repetida, "basura", buena]})
    informe = CardGenerator(cliente, "gen").generar(1, ["perro"], categorias=["animales"])
    assert [t["secreta"] for t in informe.aceptadas] == ["camello"]
    assert len(informe.rechazadas) == 2
    t = informe.aceptadas[0]
    assert len(t["prohibidas"]) == 5 and len(t["prohibidas_extra"]) == 2
    assert Tarjeta.desde_dict(t).max_prohibidas == 7


def test_generador_con_revisor_descarta_irrelevantes():
    buena = ('{"secreta": "camello", "prohibidas": ["joroba", "desierto", "animal", "arena", '
             '"agua", "dromedario", "bicicleta"]}')
    revision = '{"conocida": true, "relevancia": {"bicicleta": 0.05}}'
    cliente = ScriptedClient({"gen": [buena], "rev": [revision]})
    informe = CardGenerator(cliente, "gen", "rev").generar(1, [], max_intentos=1)
    assert informe.aceptadas == []
    assert "bicicleta" in informe.rechazadas[0][1][0]
