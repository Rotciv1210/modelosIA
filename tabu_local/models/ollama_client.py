"""Cliente mínimo para la API local de Ollama.

Solo usa dos endpoints:
  * GET  /api/tags  -> modelos instalados
  * POST /api/chat  -> generar una respuesta (stream=False)

Todos los fallos se traducen a excepciones propias (``OllamaError`` y
subclases) para que el árbitro pueda registrarlos sin que el programa se
bloquee.

Seguridad: por defecto solo se aceptan hosts locales y se rechazan los modelos
"cloud" de Ollama (p. ej. ``gpt-oss:120b-cloud``), que se ejecutan en
servidores remotos. Así garantizamos que toda la inferencia sea local.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

import requests

HOSTS_LOCALES = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


# ---------------------------------------------------------------- excepciones
class OllamaError(Exception):
    """Error genérico al hablar con un modelo."""


class OllamaUnavailableError(OllamaError):
    """Ollama no está arrancado o no se puede conectar."""


class ModelNotFoundError(OllamaError):
    """El modelo pedido no está instalado (falta ``ollama pull``)."""


class OllamaTimeoutError(OllamaError):
    """El modelo ha superado el tiempo máximo de respuesta."""


class OllamaResponseError(OllamaError):
    """Respuesta HTTP inesperada o cuerpo no interpretable."""


# ---------------------------------------------------------------- resultado
@dataclass
class ChatResult:
    text: str
    model: str
    elapsed_s: float
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class LLMClient(Protocol):
    """Interfaz común para el cliente real y los clientes simulados de prueba."""

    def chat(self, model: str, messages: list[dict[str, str]], *, json_mode: bool = False,
             max_tokens: int | None = None, temperature: float | None = None,
             seed: int | None = None) -> ChatResult: ...

    def list_models(self) -> list[str]: ...

    def is_available(self) -> bool: ...


def quitar_razonamiento(texto: str) -> str:
    """Elimina bloques <think>...</think> que emiten algunos modelos (qwen3, deepseek-r1)."""
    texto = _THINK.sub("", texto or "")
    # Si el modelo se cortó a mitad de razonamiento, descartamos lo que haya tras <think>
    if "<think>" in texto.lower():
        texto = texto[: texto.lower().index("<think>")]
    return texto.strip()


def es_modelo_remoto(nombre: str) -> bool:
    """Los modelos con sufijo -cloud / :cloud de Ollama se ejecutan fuera del ordenador."""
    n = nombre.lower()
    return n.endswith("-cloud") or n.endswith(":cloud") or ":cloud" in n


class OllamaClient:
    def __init__(self, host: str = "http://localhost:11434", timeout_s: float = 90.0,
                 connect_timeout_s: float = 5.0, temperature: float = 0.7,
                 seed: int | None = 42, max_tokens: int = 200, keep_alive: str = "15m", num_gpu: int | None = None,
                 permitir_host_no_local: bool = False, session: requests.Session | None = None):
        hostname = urlparse(host).hostname or ""
        if not permitir_host_no_local and hostname not in HOSTS_LOCALES:
            raise ValueError(
                f"El host '{host}' no es local. Esta práctica exige inferencia local; "
                "activa 'permitir_host_no_local' solo si es otro equipo de tu red.")
        self.host = host.rstrip("/")
        self.timeout_s = timeout_s
        self.connect_timeout_s = connect_timeout_s
        self.temperature = temperature
        self.seed = seed
        self.max_tokens = max_tokens
        self.keep_alive = keep_alive
        self.num_gpu = num_gpu
        self.session = session or requests.Session()

    @classmethod
    def desde_config(cls, cfg) -> "OllamaClient":
        o = cfg.ollama
        return cls(host=o.host, timeout_s=o.timeout_s, connect_timeout_s=o.connect_timeout_s,
                   temperature=o.temperature, seed=o.seed, max_tokens=o.max_tokens,
                   keep_alive=o.keep_alive, num_gpu=o.num_gpu,
                   permitir_host_no_local=o.permitir_host_no_local)

    # ------------------------------------------------------------ información
    def is_available(self) -> bool:
        try:
            r = self.session.get(f"{self.host}/api/version", timeout=self.connect_timeout_s)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def list_models(self) -> list[str]:
        try:
            r = self.session.get(f"{self.host}/api/tags",
                                 timeout=(self.connect_timeout_s, self.timeout_s))
        except requests.ConnectionError as e:
            raise OllamaUnavailableError(
                f"No se puede conectar con Ollama en {self.host}. ¿Está arrancado? "
                "(ejecuta 'ollama serve' o abre la aplicación Ollama)") from e
        except requests.Timeout as e:
            raise OllamaTimeoutError("Ollama no respondió al listar modelos") from e
        if r.status_code != 200:
            raise OllamaResponseError(f"Error {r.status_code} al listar modelos: {r.text[:200]}")
        try:
            return sorted(m["name"] for m in r.json().get("models", []))
        except (ValueError, KeyError, TypeError) as e:
            raise OllamaResponseError("Respuesta de /api/tags no interpretable") from e

    # ------------------------------------------------------------ generación
    def chat(self, model: str, messages: list[dict[str, str]], *, json_mode: bool = False,
             max_tokens: int | None = None, temperature: float | None = None,
             seed: int | None = None) -> ChatResult:
        if es_modelo_remoto(model):
            raise ModelNotFoundError(
                f"'{model}' es un modelo cloud de Ollama (inferencia remota); no está permitido.")
        options: dict[str, Any] = {
            "temperature": self.temperature if temperature is None else temperature,
            "num_predict": max_tokens or self.max_tokens,
        }
        if self.num_gpu is not None:
            # 0 = todo en CPU. Con una GPU pequeña, repartir el modelo entre CPU y GPU
            # obliga a Ollama a descargar un modelo para cargar otro en cada turno.
            options["num_gpu"] = int(self.num_gpu)
        semilla = self.seed if seed is None else seed
        if semilla is not None:
            options["seed"] = int(semilla)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options,
            "keep_alive": self.keep_alive,
        }
        if json_mode:
            payload["format"] = "json"  # Ollama fuerza salida JSON válida

        inicio = time.perf_counter()
        try:
            r = self.session.post(f"{self.host}/api/chat", json=payload,
                                  timeout=(self.connect_timeout_s, self.timeout_s))
        except requests.Timeout as e:
            raise OllamaTimeoutError(
                f"El modelo '{model}' superó el tiempo máximo ({self.timeout_s}s)") from e
        except requests.ConnectionError as e:
            raise OllamaUnavailableError(
                f"Se perdió la conexión con Ollama en {self.host}") from e
        except requests.RequestException as e:
            raise OllamaError(f"Error de red con '{model}': {e}") from e
        elapsed = time.perf_counter() - inicio

        if r.status_code == 404:
            raise ModelNotFoundError(
                f"El modelo '{model}' no está instalado. Ejecuta: ollama pull {model}")
        if r.status_code != 200:
            raise OllamaResponseError(f"Ollama devolvió {r.status_code} para '{model}': {r.text[:200]}")
        try:
            data = r.json()
            texto = data.get("message", {}).get("content", "")
        except (ValueError, AttributeError) as e:
            raise OllamaResponseError(f"Respuesta no interpretable de '{model}'") from e
        return ChatResult(text=quitar_razonamiento(texto), model=model, elapsed_s=elapsed, raw=data)
