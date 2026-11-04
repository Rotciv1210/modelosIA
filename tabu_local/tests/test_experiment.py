import csv

import pytest

from cards.deck import cargar_tarjetas
from config import CARDS_DIR
from experiment.experiment_runner import EjecutorExperimento, semilla_turno
from experiment.metrics import bootstrap_ic, comparaciones_pareadas, media_sd, wilson
from models.fake_client import ScriptedClient, SimulatedClient
from models.ollama_client import OllamaUnavailableError
from tests.conftest import ADIV, DESC, VEREDICTO_OK, VIG


def test_wilson_y_media():
    lo, hi = wilson(8, 10)
    assert 0.44 < lo < 0.5 and 0.94 < hi < 0.97
    assert wilson(0, 0) == (None, None)
    m, sd = media_sd([1, 2, 3])
    assert m == 2 and sd == 1
    lo, hi = bootstrap_ic([1, 2, 3, 4, 5] * 10)
    assert lo < 3 < hi


def test_comparacion_pareada():
    filas = []
    for k in range(10):
        for n, ac in ((3, True), (7, k < 3)):
            filas.append({"repeticion": 1, "tarjeta_id": f"t{k}", "equipo": "A", "num_prohibidas": n,
                          "acertada": ac, "infracciones_total": 0, "puntuacion": int(ac)})
    comp = {(c["metrica"], c["condicion_a"], c["condicion_b"]): c for c in comparaciones_pareadas(filas)}
    c = comp[("acierto", 3, 7)]
    assert c["n_pares"] == 10 and c["diferencia_media_b_menos_a"] == pytest.approx(-0.7)
    assert c["ic_excluye_cero"]


def test_semilla_independiente_de_condicion():
    assert semilla_turno(1, 1, "c001", "A") == semilla_turno(1, 1, "c001", "A")
    assert semilla_turno(1, 1, "c001", "A") != semilla_turno(1, 2, "c001", "A")


def test_experimento_simulado_completo(cfg, tmp_path):
    tarjetas = cargar_tarjetas(CARDS_DIR / "cards.json")
    ej = EjecutorExperimento(cfg, SimulatedClient(semilla=3), tarjetas, directorio=tmp_path, simulado=True)
    carpeta = ej.ejecutar()
    with (carpeta / "turnos.csv").open(encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    assert len(filas) == ej.total_turnos() == 4 * 2 * 3
    assert {f["num_prohibidas"] for f in filas} == {"3", "5", "7"}
    assert all(f["simulado"] == "True" for f in filas)
    # mismas tarjetas y equipos en las tres condiciones
    por_cond = {n: {(f["tarjeta_id"], f["equipo"]) for f in filas if f["num_prohibidas"] == n} for n in "357"}
    assert por_cond["3"] == por_cond["5"] == por_cond["7"]
    # misma semilla para una tarjeta/equipo en todas las condiciones
    semillas = {}
    for f in filas:
        semillas.setdefault((f["tarjeta_id"], f["equipo"]), set()).add(f["semilla"])
    assert all(len(s) == 1 for s in semillas.values())
    for nombre in ("resumen_condiciones.csv", "resumen_equipos.csv", "comparaciones.csv", "config.json",
                   "registros.jsonl", "graficos/tasa_acierto.png", "graficos/infracciones.png"):
        assert (carpeta / nombre).exists(), nombre


def test_prohibidas_que_recibe_el_descriptor_dependen_de_la_condicion(cfg, tmp_path):
    cliente = ScriptedClient({DESC: ["Pista neutra sobre algo."], ADIV: ['{"respuesta": "x"}'], VIG: [VEREDICTO_OK]})
    cfg.experimento.num_tarjetas = 1
    cfg.equipos = cfg.equipos[:1]
    cfg.juego.intentos_por_tarjeta = 1
    ej = EjecutorExperimento(cfg, cliente, cargar_tarjetas(CARDS_DIR / "cards.json"), directorio=tmp_path)
    ej.ejecutar()
    cuentas = sorted(len(c["messages"][1]["content"].split("PALABRAS PROHIBIDAS: ")[1].split("\n")[0].split(", "))
                     for c in cliente.llamadas_de(DESC))
    assert cuentas == [3, 5, 7]


def test_reanudar_no_repite_turnos(cfg, tmp_path):
    tarjetas = cargar_tarjetas(CARDS_DIR / "cards.json")
    llamadas = {"n": 0}

    def desc(_):
        llamadas["n"] += 1
        if llamadas["n"] == 5:
            raise OllamaUnavailableError("caído")
        return f"Pista neutra número {llamadas['n']}."

    cliente = ScriptedClient({DESC: [desc], ADIV: ['{"respuesta": "x"}'], VIG: [VEREDICTO_OK]})
    cfg.juego.intentos_por_tarjeta = 1
    ej = EjecutorExperimento(cfg, cliente, tarjetas, directorio=tmp_path)
    with pytest.raises(RuntimeError, match="--reanudar"):
        ej.ejecutar()
    exp_id = next(tmp_path.iterdir()).name
    carpeta = EjecutorExperimento(cfg, cliente, tarjetas, directorio=tmp_path).ejecutar(reanudar=exp_id)
    with (carpeta / "turnos.csv").open(encoding="utf-8") as f:
        filas = list(csv.DictReader(f))
    claves = [(f["tarjeta_id"], f["equipo"], f["num_prohibidas"]) for f in filas]
    assert len(claves) == len(set(claves)) == ej.total_turnos()
