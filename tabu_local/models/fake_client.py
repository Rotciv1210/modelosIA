"""Clientes falsos para pruebas automáticas y para el modo ``--simulado``.

IMPORTANTE: estos clientes NO son modelos de lenguaje. Sirven para comprobar que
el árbitro, el registro y el experimento funcionan de principio a fin sin tener
Ollama instalado. Cualquier resultado producido con ellos es sintético y se
marca como ``simulado`` en los CSV y en los registros.
"""
from __future__ import annotations

import random
import re
from typing import Any, Callable

from models.ollama_client import ChatResult

Respuesta = str | Exception | Callable[[list[dict[str, str]]], str]


class ScriptedClient:
    """Devuelve respuestas predefinidas por modelo, en orden. Registra cada llamada.

    ``guiones = {"modelo": ["respuesta 1", OllamaTimeoutError("..."), ...]}``
    Si se agota el guion de un modelo se repite la última respuesta.
    """

    def __init__(self, guiones: dict[str, list[Respuesta]], instalados: list[str] | None = None,
                 disponible: bool = True):
        self.guiones = {m: list(r) for m, r in guiones.items()}
        self._indices = {m: 0 for m in guiones}
        self.llamadas: list[dict[str, Any]] = []
        self.instalados = instalados if instalados is not None else list(guiones)
        self.disponible = disponible

    def chat(self, model, messages, *, json_mode=False, max_tokens=None, temperature=None, seed=None):
        self.llamadas.append({"model": model, "messages": messages, "json_mode": json_mode, "seed": seed})
        guion = self.guiones.get(model)
        if not guion:
            raise KeyError(f"Sin guion para el modelo {model}")
        i = min(self._indices[model], len(guion) - 1)
        self._indices[model] += 1
        r = guion[i]
        if isinstance(r, Exception):
            raise r
        texto = r(messages) if callable(r) else r
        return ChatResult(text=texto, model=model, elapsed_s=0.01)

    def list_models(self):
        return list(self.instalados)

    def is_available(self):
        return self.disponible

    def llamadas_de(self, model: str) -> list[dict[str, Any]]:
        return [c for c in self.llamadas if c["model"] == model]


class SimulatedClient:
    """Simulador aleatorio (con semilla) de los tres roles, para probar el pipeline.

    Detecta el rol por la etiqueta ``ROL:`` del prompt de sistema. El adivinador
    "acierta" con probabilidad ``p_acierto`` porque el simulador recuerda la
    última palabra secreta: es una trampa deliberada que solo tiene sentido para
    pruebas de software. NO usar para sacar conclusiones.
    """

    RELLENO = ["casa", "árbol", "coche", "mesa", "sol", "libro", "agua", "silla"]

    def __init__(self, semilla: int = 0, p_acierto: float = 0.5, p_trampa: float = 0.1,
                 p_vacia: float = 0.05, retardo_s: float = 0.0):
        self.rng = random.Random(semilla)
        self.retardo_s = retardo_s  # pausa artificial para que la interfaz gráfica se vea en directo
        self.p_acierto = p_acierto
        self.p_trampa = p_trampa
        self.p_vacia = p_vacia
        self._ultima_secreta = ""

    def chat(self, model, messages, *, json_mode=False, max_tokens=None, temperature=None, seed=None):
        sistema = messages[0]["content"] if messages else ""
        usuario = messages[-1]["content"] if messages else ""
        elapsed = round(self.rng.uniform(0.2, 2.0), 3)
        if self.retardo_s:
            import time
            time.sleep(self.retardo_s)
        if "ROL: DESCRIPTOR" in sistema:
            m = re.search(r"PALABRA SECRETA:\s*(.+)", usuario)
            self._ultima_secreta = m.group(1).strip() if m else ""
            x = self.rng.random()
            if x < self.p_vacia:
                texto = ""
            elif x < self.p_vacia + self.p_trampa:
                texto = f"Se parece mucho a {self._ultima_secreta} pero no lo digo."
            else:
                texto = (f"Es algo bastante conocido que casi todo el mundo ha visto alguna vez "
                         f"(pista simulada {self.rng.randint(1, 9999)}).")
        elif "ROL: ADIVINADOR" in sistema:
            if self.rng.random() < self.p_acierto and self._ultima_secreta:
                resp = self._ultima_secreta
            else:
                resp = self.rng.choice(self.RELLENO)
            texto = '{"respuesta": "%s"}' % resp
        elif "ROL: VIGILANTE" in sistema:
            texto = ('{"infraccion": false, "palabra_detectada": null, "tipo_infraccion": "ninguna", '
                     '"justificacion": "simulado", "nivel_confianza": 0.9}')
        else:
            texto = '{"secreta": "simulada"}'
        return ChatResult(text=texto, model=model, elapsed_s=elapsed)

    def list_models(self):
        return []

    def is_available(self):
        return True
