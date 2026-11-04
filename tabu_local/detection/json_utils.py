"""Extracción robusta de JSON de la salida de un modelo.

Los modelos pequeños a veces envuelven el JSON en ```json ... ```, añaden texto
antes o después, o usan comillas simples. Probamos varias estrategias antes de
rendirnos.
"""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _primer_objeto(texto: str) -> str | None:
    """Devuelve el primer bloque {...} equilibrado del texto."""
    inicio = texto.find("{")
    while inicio != -1:
        nivel, en_cadena, escape = 0, False, False
        for i in range(inicio, len(texto)):
            c = texto[i]
            if en_cadena:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    en_cadena = False
            elif c == '"':
                en_cadena = True
            elif c == "{":
                nivel += 1
            elif c == "}":
                nivel -= 1
                if nivel == 0:
                    return texto[inicio:i + 1]
        inicio = texto.find("{", inicio + 1)
    return None


def extraer_json(texto: str | None) -> dict[str, Any] | None:
    if not texto:
        return None
    candidatos = [texto.strip()]
    m = _FENCE.search(texto)
    if m:
        candidatos.append(m.group(1).strip())
    obj = _primer_objeto(texto)
    if obj:
        candidatos.append(obj)
    for c in candidatos:
        for intento in (c, c.replace("'", '"')):
            try:
                datos = json.loads(intento)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(datos, dict):
                return datos
    return None
