"""Gestión de modelos: comprobar Ollama, listar modelos instalados y verificar
que están todos los que pide la configuración."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from models.ollama_client import LLMClient, OllamaError, OllamaUnavailableError, es_modelo_remoto


@dataclass
class EstadoModelos:
    ollama_disponible: bool
    instalados: list[str]
    faltan: list[str]
    remotos: list[str]
    error: str | None = None

    @property
    def todo_correcto(self) -> bool:
        return self.ollama_disponible and not self.faltan and not self.remotos


def _canonico(nombre: str) -> str:
    """'llama3.2' y 'llama3.2:latest' son el mismo modelo en Ollama."""
    return nombre if ":" in nombre else f"{nombre}:latest"


class ModelManager:
    def __init__(self, client: LLMClient):
        self.client = client

    def modelos_instalados(self) -> list[str]:
        return self.client.list_models()

    def esta_instalado(self, modelo: str, instalados: list[str] | None = None) -> bool:
        instalados = self.modelos_instalados() if instalados is None else instalados
        canon = {_canonico(m) for m in instalados}
        return _canonico(modelo) in canon

    def comprobar(self, necesarios: list[str]) -> EstadoModelos:
        remotos = [m for m in necesarios if es_modelo_remoto(m)]
        if not self.client.is_available():
            return EstadoModelos(False, [], list(necesarios), remotos,
                                 "Ollama no responde. Arráncalo con 'ollama serve' o abre la app.")
        try:
            instalados = self.modelos_instalados()
        except OllamaError as e:
            return EstadoModelos(True, [], list(necesarios), remotos, str(e))
        faltan = [m for m in necesarios if not self.esta_instalado(m, instalados)]
        return EstadoModelos(True, instalados, faltan, remotos)

    @staticmethod
    def instrucciones(estado: EstadoModelos) -> str:
        lineas = []
        if not estado.ollama_disponible:
            lineas.append("1) Instala Ollama desde https://ollama.com/download")
            lineas.append("2) Arráncalo: 'ollama serve' (o abre la aplicación)")
        if estado.faltan:
            lineas.append("Descarga los modelos que faltan:")
            lineas += [f"    ollama pull {m}" for m in estado.faltan]
        if estado.remotos:
            lineas.append("Estos modelos son 'cloud' (remotos) y no están permitidos: "
                          + ", ".join(estado.remotos))
        return "\n".join(lineas)


def precargar(client: LLMClient, modelos: list[str],
              aviso: Callable[[str, dict], None] | None = None) -> list[dict]:
    """Carga cada modelo en memoria con una petición mínima antes de jugar.

    Así la espera de carga ocurre una vez, al principio y a la vista, y no a mitad
    de un turno. Los fallos se registran pero no detienen la partida (salvo que
    Ollama no esté disponible).
    """
    resultados = []
    for m in modelos:
        if aviso:
            aviso("carga_modelo_inicio", {"modelo": m})
        inicio = time.perf_counter()
        try:
            client.chat(m, [{"role": "user", "content": "Hola"}], max_tokens=1, temperature=0.0)
            r = {"modelo": m, "ok": True, "tiempo": round(time.perf_counter() - inicio, 1), "error": None}
        except OllamaUnavailableError:
            raise
        except OllamaError as e:
            r = {"modelo": m, "ok": False, "tiempo": round(time.perf_counter() - inicio, 1), "error": str(e)}
        resultados.append(r)
        if aviso:
            aviso("carga_modelo_fin", r)
    return resultados
