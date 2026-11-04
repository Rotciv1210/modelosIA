"""Los dos roles jugadores. El vigilante está en detection/semantic_judge.py.

La separación de información se garantiza por la FIRMA de los métodos: el
Adivinador no tiene ningún parámetro por el que pueda recibir la palabra
secreta ni las prohibidas.
"""
from __future__ import annotations

from game.prompts import mensajes_adivinador, mensajes_descriptor
from models.ollama_client import ChatResult, LLMClient


class Descriptor:
    def __init__(self, client: LLMClient, modelo: str, max_tokens: int = 200):
        self.client, self.modelo, self.max_tokens = client, modelo, max_tokens

    def describir(self, secreta: str, prohibidas: list[str], pistas_previas: list[str],
                  respuestas_fallidas: list[str], max_palabras: int, estricto: bool = False,
                  seed: int | None = None) -> ChatResult:
        msgs = mensajes_descriptor(secreta, prohibidas, pistas_previas, respuestas_fallidas,
                                   max_palabras, estricto)
        return self.client.chat(self.modelo, msgs, max_tokens=self.max_tokens, seed=seed)


class Adivinador:
    def __init__(self, client: LLMClient, modelo: str, max_tokens: int = 60):
        self.client, self.modelo, self.max_tokens = client, modelo, max_tokens

    def adivinar(self, pistas: list[str], respuestas_fallidas: list[str], intento: int,
                 max_intentos: int, insistir_distinta: bool = False,
                 seed: int | None = None) -> ChatResult:
        msgs = mensajes_adivinador(pistas, respuestas_fallidas, intento, max_intentos, insistir_distinta)
        return self.client.chat(self.modelo, msgs, json_mode=True, max_tokens=self.max_tokens, seed=seed)
