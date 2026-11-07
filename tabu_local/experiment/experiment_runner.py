"""Experimento: ¿cómo afecta el número de palabras prohibidas al rendimiento?

Diseño (intra-sujetos, condiciones anidadas):
  * Factor: número de prohibidas = condiciones de config (por defecto 3, 5, 7).
    Las 3 de A están incluidas en las 5 de B y estas en las 7 de C.
  * Mismas tarjetas, mismos equipos (pares descriptor-adivinador), mismo
    vigilante, misma configuración y MISMA SEMILLA en las tres condiciones: lo
    único que cambia es la lista de prohibidas.
  * Para cada (repetición, tarjeta, equipo) se juegan las tres condiciones
    seguidas en orden aleatorio (con semilla), para que posibles derivas
    temporales (calentamiento, temperatura del equipo) no se confundan con la
    condición.
  * Cada repetición usa otra semilla de muestreo -> estimación de la variabilidad.

Salida (data/results/<experimento_id>/):
  turnos.csv               una fila por turno (se escribe incrementalmente)
  registros.jsonl          registro completo de cada turno (JSON por línea)
  resumen_condiciones.csv  métricas por condición
  resumen_equipos.csv      métricas por condición y equipo
  resumen_dificultad.csv   métricas por condición y dificultad
  comparaciones.csv        diferencias pareadas con IC 95 %
  graficos/*.png
  config.json              configuración exacta usada (reproducibilidad)

Se puede reanudar con --reanudar <id>: los turnos ya guardados no se repiten.
"""
from __future__ import annotations

import csv
import json
import random
import zlib
from datetime import datetime
from pathlib import Path
from typing import Callable

from cards.deck import Tarjeta
from config import RESULTS_DIR, Config, guardar_config
from experiment.metrics import (CAMPOS_TURNO, acierto_sin_infraccion, auditoria_vigilante,
                                comparaciones_pareadas, guardar_csv, leer_turnos, mcnemar_aciertos,
                                resumen_por)
from experiment.plots import generar_graficos
from game.game_engine import crear_arbitro
from game.records import TurnRecord
from game.turn_manager import GestorTurno, TurnoAbortado
from models.ollama_client import LLMClient

Progreso = Callable[[int, int, TurnRecord], None]


def semilla_turno(base: int, repeticion: int, tarjeta_id: str, equipo: str) -> int:
    """Semilla estable (no depende del orden ni de la condición)."""
    return (base * 1000 + repeticion * 7919 + zlib.crc32(f"{tarjeta_id}|{equipo}".encode())) % 2_000_000_000


def fila_csv(rec: TurnRecord, experimento_id: str, condicion: str, repeticion: int,
             simulado: bool) -> dict:
    d = rec.to_dict()
    return {
        "experimento_id": experimento_id, "simulado": simulado, "condicion": condicion,
        "num_prohibidas": rec.num_prohibidas, "repeticion": repeticion, "semilla": rec.semilla,
        "tarjeta_id": rec.tarjeta_id, "palabra_secreta": rec.palabra_secreta,
        "categoria": rec.categoria, "dificultad": rec.dificultad, "equipo": rec.equipo,
        "modelo_descriptor": rec.modelo_descriptor, "modelo_adivinador": rec.modelo_adivinador,
        "modelo_vigilante": rec.modelo_vigilante or "", "resultado": rec.resultado,
        "acertada": rec.acertada, "intentos_usados": rec.intentos_usados,
        "infracciones_total": rec.num_infracciones,
        "infracciones_automaticas": rec.infracciones_por_origen("automatica"),
        "infracciones_semanticas": rec.infracciones_por_origen("semantica"),
        "descripciones_invalidas": rec.descripciones_invalidas,
        "respuestas_invalidas": rec.respuestas_invalidas,
        "respuestas_repetidas": rec.respuestas_repetidas,
        "num_errores": sum(1 for e in rec.errores if not e.startswith("aviso")),
        "puntuacion": rec.puntuacion,
        "tiempo_medio_descriptor_s": d["tiempo_medio_descriptor_s"],
        "tiempo_medio_adivinador_s": d["tiempo_medio_adivinador_s"],
        "tiempo_medio_vigilante_s": d["tiempo_medio_vigilante_s"],
        "tiempo_total_s": rec.tiempo_total_s,
    }


class EjecutorExperimento:
    def __init__(self, cfg: Config, client: LLMClient, tarjetas: list[Tarjeta],
                 directorio: Path = RESULTS_DIR, simulado: bool = False,
                 progreso: Progreso | None = None):
        self.cfg = cfg
        self.client = client
        self.simulado = simulado
        self.progreso = progreso
        exp = cfg.experimento
        maximo = max(exp.condiciones)
        aptas = [t for t in tarjetas if t.max_prohibidas >= maximo
                 and (not exp.dificultades or t.dificultad in exp.dificultades)]
        aptas.sort(key=lambda t: t.id)
        # Selección de tarjetas fija para la semilla del experimento
        random.Random(exp.semilla).shuffle(aptas)
        self.tarjetas = aptas[: exp.num_tarjetas]
        if not self.tarjetas:
            raise ValueError(f"No hay tarjetas con al menos {maximo} prohibidas")
        self.directorio = Path(directorio)

    def total_turnos(self) -> int:
        e = self.cfg.experimento
        return e.repeticiones * len(self.tarjetas) * len(self.cfg.equipos) * len(e.condiciones)

    def ejecutar(self, reanudar: str | None = None) -> Path:
        exp = self.cfg.experimento
        prefijo = "simulado" if self.simulado else "exp"
        exp_id = reanudar or f"{prefijo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        carpeta = self.directorio / exp_id
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta_csv, ruta_jsonl = carpeta / "turnos.csv", carpeta / "registros.jsonl"
        if not reanudar:
            guardar_config(self.cfg, carpeta / "config.json")
            (carpeta / "tarjetas.json").write_text(
                json.dumps([t.to_dict() for t in self.tarjetas], ensure_ascii=False, indent=2), encoding="utf-8")

        hechos = set()
        if ruta_csv.exists():
            for f in leer_turnos(ruta_csv):
                hechos.add((f["repeticion"], f["tarjeta_id"], f["equipo"], f["num_prohibidas"]))
        nuevo_csv = not ruta_csv.exists()

        arbitro = crear_arbitro(self.cfg, self.client)
        gestor = GestorTurno(self.cfg.juego, self.client, arbitro, None, self.cfg.ollama.max_tokens)
        vigilante = self.cfg.vigilante if arbitro.juez else None
        orden_rng = random.Random(exp.semilla + 1)
        letras = {n: chr(ord("A") + i) for i, n in enumerate(sorted(exp.condiciones))}
        total, hecho = self.total_turnos(), len(hechos)

        with ruta_csv.open("a", encoding="utf-8", newline="") as fcsv, \
                ruta_jsonl.open("a", encoding="utf-8") as fjson:
            w = csv.DictWriter(fcsv, fieldnames=CAMPOS_TURNO)
            if nuevo_csv:
                w.writeheader()
            for rep in range(1, exp.repeticiones + 1):
                for tarjeta in self.tarjetas:
                    for equipo in self.cfg.equipos:
                        condiciones = list(exp.condiciones)
                        orden_rng.shuffle(condiciones)  # se baraja siempre, para que reanudar sea idéntico
                        semilla = semilla_turno(exp.semilla, rep, tarjeta.id, equipo.nombre)
                        for n in condiciones:
                            if (rep, tarjeta.id, equipo.nombre, n) in hechos:
                                continue
                            try:
                                rec = gestor.jugar(tarjeta, equipo, rep, f"{exp_id}_r{rep}_n{n}", n,
                                                   vigilante, semilla=semilla)
                            except TurnoAbortado as e:
                                # Ollama caído / modelo ausente: guardamos lo hecho y paramos
                                fjson.write(json.dumps(e.registro.to_dict(), ensure_ascii=False) + "\n")
                                raise RuntimeError(
                                    f"Experimento detenido: {e}. Reanuda con --reanudar {exp_id}") from e
                            w.writerow(fila_csv(rec, exp_id, letras[n], rep, self.simulado))
                            fcsv.flush()
                            fjson.write(json.dumps(rec.to_dict() | {"condicion": letras[n]},
                                                   ensure_ascii=False) + "\n")
                            fjson.flush()
                            hecho += 1
                            if self.progreso:
                                self.progreso(hecho, total, rec)
        analizar(carpeta, simulado=self.simulado, semilla=exp.semilla)
        return carpeta


def analizar(carpeta: Path, simulado: bool | None = None, semilla: int = 0) -> dict[str, Path]:
    """Calcula los resúmenes y gráficos a partir de turnos.csv."""
    carpeta = Path(carpeta)
    filas = leer_turnos(carpeta / "turnos.csv")
    if not filas:
        raise ValueError("turnos.csv está vacío: no hay nada que analizar")
    if simulado is None:
        simulado = any(f["simulado"] for f in filas)
    res_cond = resumen_por(filas, ["num_prohibidas"], semilla)
    res_eq = resumen_por(filas, ["num_prohibidas", "equipo"], semilla)
    res_dif = resumen_por(filas, ["num_prohibidas", "dificultad"], semilla)
    comp = comparaciones_pareadas(filas, semilla)
    # Análisis de sensibilidad: sin los turnos penalizados por el vigilante
    contaminados = {(f["repeticion"], f["tarjeta_id"], f["equipo"]) for f in filas if f["infracciones_semanticas"]}
    mcn = [d | {"analisis": "todos"} for d in mcnemar_aciertos(filas)]
    if contaminados:
        mcn += [d | {"analisis": "sin_turnos_penalizados_por_vigilante"}
                for d in mcnemar_aciertos(filas, excluir=contaminados)]
    limpio = acierto_sin_infraccion(filas)
    registros = []
    if (carpeta / "registros.jsonl").exists():
        with (carpeta / "registros.jsonl").open(encoding="utf-8") as f:
            registros = [json.loads(l) for l in f if l.strip()]
    rutas = {
        "resumen_condiciones": carpeta / "resumen_condiciones.csv",
        "resumen_equipos": carpeta / "resumen_equipos.csv",
        "resumen_dificultad": carpeta / "resumen_dificultad.csv",
        "comparaciones": carpeta / "comparaciones.csv",
        "mcnemar": carpeta / "mcnemar.csv",
        "acierto_sin_infraccion": carpeta / "acierto_sin_infraccion.csv",
        "auditoria_vigilante": carpeta / "auditoria_vigilante.json",
    }
    guardar_csv(res_cond, rutas["resumen_condiciones"])
    guardar_csv(res_eq, rutas["resumen_equipos"])
    guardar_csv(res_dif, rutas["resumen_dificultad"])
    guardar_csv(comp, rutas["comparaciones"])
    guardar_csv(mcn, rutas["mcnemar"])
    guardar_csv(limpio, rutas["acierto_sin_infraccion"])
    rutas["auditoria_vigilante"].write_text(
        json.dumps(auditoria_vigilante(registros), ensure_ascii=False, indent=2), encoding="utf-8")
    generar_graficos(res_cond, res_eq, carpeta / "graficos", simulado=simulado)
    rutas["graficos"] = carpeta / "graficos"
    return rutas


def estimar_duracion(total_turnos: int, segundos_por_llamada: float = 3.0,
                     llamadas_por_turno: float = 5.0) -> float:
    """Estimación grosera en horas (para avisar antes de lanzar)."""
    return total_turnos * segundos_por_llamada * llamadas_por_turno / 3600

