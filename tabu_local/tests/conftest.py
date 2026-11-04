"""Utilidades compartidas por las pruebas. Ninguna prueba necesita Ollama."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cards.deck import Tarjeta  # noqa: E402
from config import Config, ExperimentConfig, GameConfig, TeamConfig  # noqa: E402

DESC, ADIV, VIG = "desc-model", "adiv-model", "vig-model"
VEREDICTO_OK = ('{"infraccion": false, "palabra_detectada": null, "tipo_infraccion": "ninguna", '
                '"justificacion": "ok", "nivel_confianza": 0.95}')


@pytest.fixture
def tarjeta_perro():
    return Tarjeta(id="t1", secreta="perro", prohibidas=("ladrar", "mascota", "hueso", "gato", "collar"),
                   categoria="animales", dificultad="facil", prohibidas_extra=("cachorro", "correa"),
                   variantes=("dog", "chien"))


@pytest.fixture
def cfg():
    return Config(
        juego=GameConfig(rondas=2, intentos_por_tarjeta=3, num_prohibidas=5,
                         usar_vigilante_semantico=True, umbral_confianza_vigilante=0.8),
        equipos=[TeamConfig("A", DESC, ADIV), TeamConfig("B", DESC, ADIV)],
        vigilante=VIG,
        experimento=ExperimentConfig(condiciones=[3, 5, 7], repeticiones=1, num_tarjetas=4, semilla=7),
    )
