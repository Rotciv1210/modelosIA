import pytest

from detection.forbidden_checker import ForbiddenChecker
from detection.json_utils import extraer_json
from detection.semantic_judge import SemanticJudge, parsear_veredicto
from detection.text_normalizer import (es_misma_palabra, formas_flexivas, normalizar,
                                       quitar_tildes)
from models.fake_client import ScriptedClient
from models.ollama_client import OllamaTimeoutError

PROH = ["ladrar", "mascota", "hueso", "gato", "collar"]


@pytest.fixture
def checker():
    return ForbiddenChecker()


def tipos(dets):
    return {(d.tipo, d.objetivo) for d in dets}


# ----------------------------------------------------------- normalización
def test_normalizar_tildes_mayusculas_puntuacion():
    assert quitar_tildes("Canción pingüino") == "Cancion pinguino"
    assert normalizar("¡¿Hola, PERRO-guardián?!") == "hola perro guardian"


def test_formas_flexivas():
    f = formas_flexivas("perro")
    assert {"perros", "perra", "perras", "perrito", "perritos", "perrazo"} <= f
    assert "lapices" in formas_flexivas("lápiz")
    assert "canciones" in formas_flexivas("canción")


def test_es_misma_palabra():
    assert es_misma_palabra("Perros", "perro")
    assert es_misma_palabra("el perro", "perro")
    assert es_misma_palabra("arco iris", "arcoíris")
    assert es_misma_palabra("LÁPICES", "lápiz")
    assert not es_misma_palabra("perra", "perro")   # el género no vale como acierto
    assert not es_misma_palabra("gato", "perro")


# ------------------------------------------------------ detector automático
def test_descripcion_limpia(checker):
    texto = "Animal doméstico muy fiel que mueve la cola cuando está contento."
    assert checker.comprobar(texto, "perro", PROH) == []


@pytest.mark.parametrize("texto,tipo,objetivo", [
    ("Es un PERRO grande", "exacta", "perro"),
    ("Animal que suele LADRAR.", "exacta", "ladrar"),
    ("Los perros son fieles", "morfologica", "perro"),
    ("Una perrita pequeña", "morfologica", "perro"),
    ("Le gustan los huesos", "morfologica", "hueso"),
    ("Enemigo de los gatitos", "morfologica", "gato"),
    ("Vive en la perrera", "derivada", "perro"),
    ("Animal ladrador", "derivada", "ladrar"),
    ("Se escribe p-e-r-r-o", "deletreo", "perro"),
    ("En inglés se dice dog", "traduccion", "perro"),
])
def test_detecciones(checker, texto, tipo, objetivo):
    dets = checker.comprobar(texto, "perro", PROH, variantes_secreta=("dog",))
    assert (tipo, objetivo) in tipos(dets)


def test_palabra_compuesta(checker):
    dets = checker.comprobar("Se usa como paraguas", "agua", ["lluvia"])
    assert ("compuesta", "agua") in tipos(dets)


def test_no_confunde_inicio_de_palabra_corta(checker):
    # 'casado' empieza por 'casa' pero no es compuesta ni derivada detectable
    assert checker.comprobar("Un señor casado", "casa", ["hogar"]) == []


def test_prohibida_de_varias_palabras(checker):
    dets = checker.comprobar("Es cuando echas de menos algo", "nostalgia", ["echar de menos", "pasado"])
    assert dets == []  # 'echas' no es 'echar' literal: queda para el vigilante
    dets = checker.comprobar("Es echar de menos el pasado", "nostalgia", ["echar de menos", "pasado"])
    assert {d.objetivo for d in dets} == {"echar de menos", "pasado"}


def test_una_deteccion_por_objetivo(checker):
    dets = checker.comprobar("perro perros perrito", "perro", PROH)
    assert len(dets) == 1 and dets[0].tipo == "exacta"


def test_mismo_fragmento_no_penaliza_dos_veces(checker):
    dets = checker.comprobar("Se parece a un helicóptero", "helicóptero", ["hélice", "volar"])
    assert len(dets) == 1 and dets[0].es_secreta


def test_variantes_globales_y_stopwords():
    ch = ForbiddenChecker(variantes_globales={"hueso": ["bone"], "perro": ["son"]})
    assert ("traduccion", "hueso") in tipos(ch.comprobar("Le encanta el bone", "perro", PROH))
    # 'son' es palabra común en español: no debe generar falsos positivos
    assert ch.comprobar("Son animales leales", "perro", PROH) == []


# --------------------------------------------------------------- JSON / juez
def test_extraer_json_variantes():
    assert extraer_json('{"a": 1}') == {"a": 1}
    assert extraer_json('Aquí tienes:\n```json\n{"a": 2}\n```') == {"a": 2}
    assert extraer_json("texto {'a': 3} más texto") == {"a": 3}
    assert extraer_json("sin json") is None


def test_parsear_veredicto_valida_y_normaliza():
    v = parsear_veredicto('{"infraccion": "true", "palabra_detectada": "can", '
                          '"tipo_infraccion": "SINONIMO_EVIDENTE", "justificacion": "x", "nivel_confianza": 90}')
    assert v.infraccion is True and v.nivel_confianza == 0.9 and v.tipo_infraccion == "sinonimo_evidente"
    v = parsear_veredicto('{"infraccion": false, "tipo_infraccion": "inventado"}')
    assert v.tipo_infraccion == "ninguna"
    assert parsear_veredicto('{"otra": 1}') is None


def test_juez_umbral_y_reintento():
    respuesta = ('{"infraccion": true, "palabra_detectada": "can", "tipo_infraccion": "sinonimo_evidente", '
                 '"justificacion": "can es sinónimo", "nivel_confianza": 0.85}')
    cliente = ScriptedClient({"vig": ["no es json", respuesta]})
    juez = SemanticJudge(cliente, "vig", umbral=0.8)
    v = juez.evaluar("Es un can", "perro", PROH)
    assert v.valido and juez.es_infraccion(v)
    assert len(cliente.llamadas) == 2                       # reintentó tras el JSON roto
    assert SemanticJudge(cliente, "vig", umbral=0.9).es_infraccion(v) is False


def test_juez_sin_respuesta_no_penaliza():
    cliente = ScriptedClient({"vig": [OllamaTimeoutError("lento")]})
    juez = SemanticJudge(cliente, "vig")
    v = juez.evaluar("Es un animal", "perro", PROH)
    assert not v.valido and not juez.es_infraccion(v) and "OllamaTimeoutError" in v.error


def test_juez_no_recibe_informacion_innecesaria():
    cliente = ScriptedClient({"vig": ['{"infraccion": false, "nivel_confianza": 1}']})
    SemanticJudge(cliente, "vig").evaluar("Animal fiel", "perro", PROH)
    contenido = " ".join(m["content"] for m in cliente.llamadas[0]["messages"])
    for prohibido in ("Equipo", "puntuación", "marcador", "adivinador ha respondido"):
        assert prohibido not in contenido
