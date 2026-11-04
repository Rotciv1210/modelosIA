"""Pruebas del cliente de Ollama con una sesión HTTP falsa (sin red)."""
import pytest
import requests

from models.model_manager import ModelManager
from models.ollama_client import (ModelNotFoundError, OllamaClient, OllamaResponseError,
                                  OllamaTimeoutError, OllamaUnavailableError, quitar_razonamiento)


class Resp:
    def __init__(self, status=200, datos=None, texto=""):
        self.status_code, self._datos, self.text = status, datos, texto

    def json(self):
        if self._datos is None:
            raise ValueError("no json")
        return self._datos


class SesionFalsa:
    def __init__(self, post=None, get=None):
        self._post, self._get, self.payloads = post, get, []

    def post(self, url, json=None, timeout=None):
        self.payloads.append(json)
        if isinstance(self._post, Exception):
            raise self._post
        return self._post

    def get(self, url, timeout=None):
        if isinstance(self._get, Exception):
            raise self._get
        return self._get


def cliente(post=None, get=None):
    return OllamaClient(session=SesionFalsa(post, get))


def test_chat_ok_y_payload():
    c = cliente(Resp(datos={"message": {"content": "<think>pensando</think> Hola"}}))
    r = c.chat("m", [{"role": "user", "content": "x"}], json_mode=True, seed=5, max_tokens=10)
    assert r.text == "Hola"
    p = c.session.payloads[0]
    assert p["format"] == "json" and p["stream"] is False
    assert p["options"]["seed"] == 5 and p["options"]["num_predict"] == 10


@pytest.mark.parametrize("respuesta,error", [
    (requests.Timeout(), OllamaTimeoutError),
    (requests.ConnectionError(), OllamaUnavailableError),
    (Resp(404, texto="model not found"), ModelNotFoundError),
    (Resp(500, texto="boom"), OllamaResponseError),
    (Resp(200, datos=None), OllamaResponseError),
])
def test_errores_traducidos(respuesta, error):
    with pytest.raises(error):
        cliente(respuesta).chat("m", [])


def test_solo_inferencia_local():
    with pytest.raises(ValueError):
        OllamaClient(host="https://api.ejemplo.com")
    with pytest.raises(ModelNotFoundError):
        cliente(Resp(datos={"message": {"content": "x"}})).chat("gpt-oss:120b-cloud", [])


def test_quitar_razonamiento_cortado():
    assert quitar_razonamiento("Respuesta <think> sin cerrar") == "Respuesta"


def test_model_manager():
    c = cliente(get=Resp(datos={"models": [{"name": "llama3.2:latest"}, {"name": "qwen2.5:3b"}]}))
    estado = ModelManager(c).comprobar(["llama3.2", "qwen2.5:3b", "gemma2:2b"])
    assert estado.ollama_disponible and estado.faltan == ["gemma2:2b"]
    assert "ollama pull gemma2:2b" in ModelManager.instrucciones(estado)
    caido = ModelManager(cliente(get=requests.ConnectionError())).comprobar(["x"])
    assert not caido.ollama_disponible and not caido.todo_correcto


def test_num_gpu_cero_fuerza_cpu():
    c = OllamaClient(session=SesionFalsa(Resp(datos={"message": {"content": "x"}})), num_gpu=0)
    c.chat("m", [])
    assert c.session.payloads[0]["options"]["num_gpu"] == 0
    c2 = cliente(Resp(datos={"message": {"content": "x"}}))
    c2.chat("m", [])
    assert "num_gpu" not in c2.session.payloads[0]["options"]


def test_precargar_modelos():
    from models.fake_client import ScriptedClient
    from models.model_manager import precargar
    from models.ollama_client import OllamaTimeoutError
    eventos = []
    cli = ScriptedClient({"a": ["ok"], "b": [OllamaTimeoutError("lento")]})
    res = precargar(cli, ["a", "b"], lambda ev, d: eventos.append(ev))
    assert [r["ok"] for r in res] == [True, False]
    assert eventos == ["carga_modelo_inicio", "carga_modelo_fin"] * 2
