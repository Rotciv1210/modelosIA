"""Generación de tarjetas nuevas con un modelo local + revisión automática.

Flujo:
  1. El modelo propone una tarjeta en JSON (secreta + 7 prohibidas + variantes).
  2. Se valida con reglas (card_validator) y se comprueba que la secreta no
     esté ya en el mazo.
  3. (Opcional) Un modelo revisor puntúa la relevancia de cada prohibida; las
     de relevancia < umbral provocan el rechazo de la tarjeta.
  4. Las aceptadas se guardan en cards/cards_generadas.json. Para usarlas en
     partidas, añade ese fichero a 'juego.ficheros_tarjetas' en config.json.

Las tarjetas generadas NO se mezclan automáticamente con el mazo base: así el
experimento sigue usando siempre las mismas tarjetas revisadas a mano.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from cards.card_validator import CATEGORIAS, DIFICULTADES, validar_tarjeta
from detection.json_utils import extraer_json
from detection.text_normalizer import es_misma_palabra
from game.prompts import mensajes_generador_tarjeta, mensajes_revision_tarjeta
from models.ollama_client import LLMClient, OllamaError


@dataclass
class InformeGeneracion:
    aceptadas: list[dict] = field(default_factory=list)
    rechazadas: list[tuple[dict | None, list[str]]] = field(default_factory=list)


class CardGenerator:
    def __init__(self, client: LLMClient, modelo: str, modelo_revisor: str | None = None,
                 umbral_relevancia: float = 0.4):
        self.client = client
        self.modelo = modelo
        self.modelo_revisor = modelo_revisor
        self.umbral_relevancia = umbral_relevancia

    def _proponer(self, categoria: str, dificultad: str, evitar: list[str]) -> dict | None:
        res = self.client.chat(self.modelo, mensajes_generador_tarjeta(categoria, dificultad, evitar),
                               json_mode=True, max_tokens=300, temperature=0.9, seed=None)
        datos = extraer_json(res.text)
        if not datos or not isinstance(datos.get("prohibidas"), list):
            return None
        todas = [str(p).strip() for p in datos["prohibidas"] if str(p).strip()]
        return {
            "secreta": str(datos.get("secreta", "")).strip().lower(),
            "prohibidas": todas[:5],
            "prohibidas_extra": todas[5:7],
            "categoria": categoria,
            "dificultad": dificultad,
            "variantes": [str(v) for v in datos.get("variantes", []) if isinstance(v, str)][:4],
        }

    def _revisar(self, tarjeta: dict) -> list[str]:
        """Devuelve problemas detectados por el modelo revisor (lista vacía = OK)."""
        if not self.modelo_revisor:
            return []
        todas = tarjeta["prohibidas"] + tarjeta["prohibidas_extra"]
        try:
            res = self.client.chat(self.modelo_revisor, mensajes_revision_tarjeta(tarjeta["secreta"], todas),
                                   json_mode=True, max_tokens=300, temperature=0.0)
        except OllamaError as e:
            return [f"Revisor no disponible: {e}"]
        datos = extraer_json(res.text) or {}
        problemas = []
        if datos.get("conocida") is False:
            problemas.append("El revisor considera que la palabra no es suficientemente conocida")
        relevancia = datos.get("relevancia") or {}
        for p in todas:
            try:
                r = float(relevancia.get(p, 1.0))
            except (TypeError, ValueError):
                continue
            if r < self.umbral_relevancia:
                problemas.append(f"Prohibida poco relevante: '{p}' ({r:.2f})")
        return problemas

    def generar(self, n: int, existentes: list[str], categorias: list[str] | None = None,
                dificultades: list[str] | None = None, max_intentos: int | None = None) -> InformeGeneracion:
        categorias = categorias or list(CATEGORIAS)
        dificultades = dificultades or list(DIFICULTADES)
        informe = InformeGeneracion()
        evitar = list(existentes)
        intentos = 0
        max_intentos = max_intentos or n * 4
        while len(informe.aceptadas) < n and intentos < max_intentos:
            cat = categorias[intentos % len(categorias)]
            dif = dificultades[intentos % len(dificultades)]
            intentos += 1
            try:
                t = self._proponer(cat, dif, evitar)
            except OllamaError as e:
                informe.rechazadas.append((None, [f"Error del modelo: {e}"]))
                continue
            if t is None:
                informe.rechazadas.append((None, ["Respuesta no válida (JSON incorrecto)"]))
                continue
            t["id"] = f"g{len(existentes) + len(informe.aceptadas) + 1:03d}"
            problemas = validar_tarjeta(t).errores
            if len(t["prohibidas"]) + len(t["prohibidas_extra"]) < 7:
                problemas.append("Se necesitan 7 prohibidas para poder usarla en el experimento")
            if any(es_misma_palabra(t["secreta"], e) for e in evitar):
                problemas.append(f"Palabra secreta repetida: '{t['secreta']}'")
            if not problemas:
                problemas = self._revisar(t)
            if problemas:
                informe.rechazadas.append((t, problemas))
            else:
                informe.aceptadas.append(t)
                evitar.append(t["secreta"])
        return informe


def guardar_generadas(tarjetas: list[dict], ruta: Path) -> None:
    existentes = []
    if ruta.exists():
        with ruta.open(encoding="utf-8") as f:
            existentes = json.load(f).get("tarjetas", [])
    with ruta.open("w", encoding="utf-8") as f:
        json.dump({"version": 1, "descripcion": "Tarjetas generadas automáticamente y validadas",
                   "tarjetas": existentes + tarjetas}, f, ensure_ascii=False, indent=2)
