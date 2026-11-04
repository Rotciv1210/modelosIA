"""Pruebas de la interfaz gráfica (API del servidor local) en modo simulado."""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from gui.server import AppGUI, crear_servidor


@pytest.fixture
def servidor(tmp_path):
    app = AppGUI(simulado=True, directorio_partidas=tmp_path)
    app.retardo_simulado = 0
    srv = crear_servidor(app, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield app, f"http://127.0.0.1:{srv.server_address[1]}"
    app.sesion.detener = True
    app.sesion.continuar.set()
    srv.shutdown()
    srv.server_close()


def pedir(url, cuerpo=None):
    datos = None if cuerpo is None else json.dumps(cuerpo).encode()
    req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def esperar_eventos(base, condicion, limite=10.0):
    fin = time.time() + limite
    while time.time() < fin:
        _, d = pedir(base + "/api/eventos?desde=0")
        if condicion(d["eventos"]):
            return d["eventos"]
        time.sleep(0.05)
    raise AssertionError("tiempo agotado esperando eventos")


PETICION = {"equipos": [{"nombre": "A", "descriptor": "m1", "adivinador": "m2"},
                        {"nombre": "B", "descriptor": "m2", "adivinador": "m1"}],
            "vigilante": "m3", "rondas": 2, "num_prohibidas": 4, "intentos": 2, "pausar": False}


def test_pagina_y_estado(servidor):
    _, base = servidor
    with urllib.request.urlopen(base + "/", timeout=5) as r:
        assert b"Tab\xc3\xba entre modelos locales" in r.read()
    estado, d = pedir(base + "/api/estado")
    assert estado == 200 and d["simulado"] and d["ollama"] and d["config"]["equipos"]


def test_partida_completa_por_la_api(servidor):
    _, base = servidor
    assert pedir(base + "/api/partida", PETICION)[0] == 200
    eventos = esperar_eventos(base, lambda ev: any(e["tipo"] == "partida_fin" for e in ev))
    tipos = [e["tipo"] for e in eventos]
    assert tipos[0] == "carga_inicio" and tipos.count("carga_modelo_fin") == 3   # precarga de m1, m2, m3
    assert tipos.index("carga_fin") < tipos.index("partida_inicio")
    assert tipos.count("turno_fin") == 4
    inicio = next(e for e in eventos if e["tipo"] == "partida_inicio")
    assert inicio["vigilante"] == "m3" and inicio["rondas"] == 2
    turno = next(e for e in eventos if e["tipo"] == "turno_inicio")
    assert len(turno["prohibidas"]) == 4
    _, hist = pedir(base + "/api/historial")
    assert hist["partidas"][0]["turnos"] == 4
    _, det = pedir(base + "/api/partida?id=" + hist["partidas"][0]["partida_id"])
    assert len(det["turnos"]) == 4


def test_pausa_continuar_y_detener(servidor):
    app, base = servidor
    pedir(base + "/api/partida", PETICION | {"pausar": True})
    esperar_eventos(base, lambda ev: any(e["tipo"] == "esperando" for e in ev))
    # mientras está en pausa no avanza
    n = len(app.sesion.eventos)
    time.sleep(0.3)
    assert len(app.sesion.eventos) == n
    assert pedir(base + "/api/partida", PETICION)[0] == 400       # solo una partida a la vez
    pedir(base + "/api/continuar", {})
    esperar_eventos(base, lambda ev: sum(e["tipo"] == "esperando" for e in ev) >= 2)
    pedir(base + "/api/detener", {})
    eventos = esperar_eventos(base, lambda ev: any(e["tipo"] == "partida_fin" for e in ev))
    assert eventos[-1]["estado"] == "interrumpida"


def test_configuracion_invalida(servidor):
    _, base = servidor
    estado, d = pedir(base + "/api/partida", PETICION | {"num_prohibidas": 12})
    assert estado == 400 and "num_prohibidas" in d["error"]
