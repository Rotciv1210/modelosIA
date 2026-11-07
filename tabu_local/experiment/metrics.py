"""Métricas y estadística descriptiva del experimento (solo biblioteca estándar).

Unidad de análisis: el TURNO (un equipo, una tarjeta, una condición, una
repetición). La "puntuación media por ronda" es la media de la puntuación por
turno, porque en el experimento cada turno es una ronda de un equipo.

Dispersión: desviación típica, rango intercuartílico e intervalos de confianza
del 95 % (Wilson para proporciones; bootstrap percentil para medias).
Comparaciones: diferencias PAREADAS entre condiciones (misma tarjeta, mismo
equipo, misma repetición) con IC bootstrap.
"""
from __future__ import annotations

import csv
import math
import random
import statistics
from itertools import combinations
from pathlib import Path

CAMPOS_TURNO = [
    "experimento_id", "simulado", "condicion", "num_prohibidas", "repeticion", "semilla",
    "tarjeta_id", "palabra_secreta", "categoria", "dificultad", "equipo",
    "modelo_descriptor", "modelo_adivinador", "modelo_vigilante", "resultado", "acertada",
    "intentos_usados", "infracciones_total", "infracciones_automaticas", "infracciones_semanticas",
    "descripciones_invalidas", "respuestas_invalidas", "respuestas_repetidas", "num_errores",
    "puntuacion", "tiempo_medio_descriptor_s", "tiempo_medio_adivinador_s",
    "tiempo_medio_vigilante_s", "tiempo_total_s",
]
_ENTEROS = {"num_prohibidas", "repeticion", "intentos_usados", "infracciones_total",
            "infracciones_automaticas", "infracciones_semanticas", "descripciones_invalidas",
            "respuestas_invalidas", "respuestas_repetidas", "num_errores", "puntuacion"}
_REALES = {"tiempo_medio_descriptor_s", "tiempo_medio_adivinador_s", "tiempo_medio_vigilante_s",
           "tiempo_total_s"}


# ------------------------------------------------------------------ lectura
def leer_turnos(ruta: Path) -> list[dict]:
    filas = []
    with Path(ruta).open(encoding="utf-8", newline="") as f:
        for fila in csv.DictReader(f):
            for k in _ENTEROS:
                fila[k] = int(fila[k]) if fila.get(k) not in (None, "") else 0
            for k in _REALES:
                fila[k] = float(fila[k]) if fila.get(k) not in (None, "") else None
            fila["acertada"] = str(fila["acertada"]).lower() in ("true", "1")
            fila["simulado"] = str(fila.get("simulado")).lower() in ("true", "1")
            filas.append(fila)
    return filas


def guardar_csv(filas: list[dict], ruta: Path, campos: list[str] | None = None) -> None:
    campos = campos or (list(filas[0].keys()) if filas else [])
    with Path(ruta).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)


# --------------------------------------------------------------- estadística
def media_sd(valores: list[float]) -> tuple[float | None, float | None]:
    v = [x for x in valores if x is not None]
    if not v:
        return None, None
    return statistics.fmean(v), (statistics.stdev(v) if len(v) > 1 else 0.0)


def iqr(valores: list[float]) -> float | None:
    v = sorted(x for x in valores if x is not None)
    if len(v) < 2:
        return None
    q = statistics.quantiles(v, n=4, method="inclusive")
    return q[2] - q[0]


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """IC del 95 % de Wilson para una proporción (robusto con n pequeño)."""
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centro - margen), min(1.0, centro + margen)


def bootstrap_ic(valores: list[float], n_boot: int = 2000, semilla: int = 0,
                 alfa: float = 0.05) -> tuple[float | None, float | None]:
    """IC bootstrap percentil para la media."""
    v = [x for x in valores if x is not None]
    if len(v) < 2:
        return None, None
    rng = random.Random(semilla)
    medias = sorted(statistics.fmean(rng.choices(v, k=len(v))) for _ in range(n_boot))
    return medias[int(alfa / 2 * n_boot)], medias[int((1 - alfa / 2) * n_boot) - 1]


def _r(x, nd=4):
    return None if x is None else round(x, nd)


# ------------------------------------------------------------------ resúmenes
def resumen_grupo(filas: list[dict], semilla: int = 0) -> dict:
    n = len(filas)
    aciertos = sum(f["acertada"] for f in filas)
    ic_ac = wilson(aciertos, n)
    infr = [f["infracciones_total"] for f in filas]
    inval = [f["descripciones_invalidas"] for f in filas]
    punt = [f["puntuacion"] for f in filas]
    intentos = [f["intentos_usados"] for f in filas if f["acertada"]]
    t_desc = [f["tiempo_medio_descriptor_s"] for f in filas]
    t_adiv = [f["tiempo_medio_adivinador_s"] for f in filas]
    t_tot = [f["tiempo_total_s"] for f in filas]
    m_inf, sd_inf = media_sd(infr)
    m_inv, sd_inv = media_sd(inval)
    m_p, sd_p = media_sd(punt)
    m_int, sd_int = media_sd(intentos)
    m_td, sd_td = media_sd(t_desc)
    m_ta, sd_ta = media_sd(t_adiv)
    m_tt, sd_tt = media_sd(t_tot)
    ic_p = bootstrap_ic(punt, semilla=semilla)
    ic_inf = bootstrap_ic(infr, semilla=semilla)
    return {
        "n_turnos": n,
        "aciertos": aciertos,
        "tasa_acierto": _r(aciertos / n if n else None),
        "tasa_acierto_ic95_inf": _r(ic_ac[0]), "tasa_acierto_ic95_sup": _r(ic_ac[1]),
        "infracciones_total": sum(infr),
        "infracciones_automaticas": sum(f["infracciones_automaticas"] for f in filas),
        "infracciones_semanticas": sum(f["infracciones_semanticas"] for f in filas),
        "turnos_con_infraccion": sum(1 for x in infr if x > 0),
        "infracciones_media": _r(m_inf), "infracciones_sd": _r(sd_inf),
        "infracciones_ic95_inf": _r(ic_inf[0]), "infracciones_ic95_sup": _r(ic_inf[1]),
        "descripciones_invalidas_total": sum(inval),
        "descripciones_invalidas_media": _r(m_inv), "descripciones_invalidas_sd": _r(sd_inv),
        "turnos_con_error": sum(1 for f in filas if f["resultado"] == "error"),
        "intentos_media_aciertos": _r(m_int), "intentos_sd_aciertos": _r(sd_int),
        "puntuacion_media": _r(m_p), "puntuacion_sd": _r(sd_p), "puntuacion_iqr": _r(iqr(punt)),
        "puntuacion_ic95_inf": _r(ic_p[0]), "puntuacion_ic95_sup": _r(ic_p[1]),
        "tiempo_descriptor_media_s": _r(m_td), "tiempo_descriptor_sd_s": _r(sd_td),
        "tiempo_adivinador_media_s": _r(m_ta), "tiempo_adivinador_sd_s": _r(sd_ta),
        "tiempo_turno_media_s": _r(m_tt), "tiempo_turno_sd_s": _r(sd_tt),
    }


def resumen_por(filas: list[dict], claves: list[str], semilla: int = 0) -> list[dict]:
    grupos: dict[tuple, list[dict]] = {}
    for f in filas:
        grupos.setdefault(tuple(f[c] for c in claves), []).append(f)
    salida = []
    for clave in sorted(grupos, key=lambda k: tuple(str(x).zfill(3) for x in k)):
        fila = dict(zip(claves, clave))
        fila.update(resumen_grupo(grupos[clave], semilla))
        salida.append(fila)
    return salida


METRICAS_PAREADAS = {
    "acierto": lambda f: 1.0 if f["acertada"] else 0.0,
    "infracciones": lambda f: float(f["infracciones_total"]),
    "puntuacion": lambda f: float(f["puntuacion"]),
}


def comparaciones_pareadas(filas: list[dict], semilla: int = 0) -> list[dict]:
    """Diferencia media (B - A) entre cada par de condiciones, emparejando turnos
    con la misma tarjeta, equipo y repetición. IC bootstrap del 95 %."""
    por_cond: dict[int, dict[tuple, dict]] = {}
    for f in filas:
        clave = (f["repeticion"], f["tarjeta_id"], f["equipo"])
        por_cond.setdefault(f["num_prohibidas"], {})[clave] = f
    salida = []
    for a, b in combinations(sorted(por_cond), 2):
        comunes = sorted(set(por_cond[a]) & set(por_cond[b]))
        for nombre, fn in METRICAS_PAREADAS.items():
            difs = [fn(por_cond[b][k]) - fn(por_cond[a][k]) for k in comunes]
            m, sd = media_sd(difs)
            ic = bootstrap_ic(difs, semilla=semilla)
            salida.append({
                "metrica": nombre, "condicion_a": a, "condicion_b": b, "n_pares": len(comunes),
                "diferencia_media_b_menos_a": _r(m), "sd": _r(sd),
                "ic95_inf": _r(ic[0]), "ic95_sup": _r(ic[1]),
                "ic_excluye_cero": (ic[0] is not None and (ic[0] > 0 or ic[1] < 0)),
            })
    return salida


# ------------------------------------------------------------ McNemar
def mcnemar_exacto(b10: int, b01: int) -> float:
    """p-valor bilateral exacto de McNemar (binomial con p = 0,5 sobre los pares discordantes)."""
    n = b10 + b01
    if n == 0:
        return 1.0
    cola = sum(math.comb(n, i) for i in range(min(b10, b01) + 1)) / 2 ** n
    return min(1.0, 2 * cola)


def mcnemar_aciertos(filas: list[dict], excluir: set | None = None) -> list[dict]:
    """Compara el acierto entre cada par de condiciones con turnos PAREADOS.

    b10 = acertó en A y falló en B; b01 = al revés. Solo cuentan los pares
    discordantes. ``excluir`` = claves (repetición, tarjeta, equipo) a omitir.
    """
    excluir = excluir or set()
    por_cond: dict[int, dict[tuple, dict]] = {}
    for f in filas:
        clave = (f["repeticion"], f["tarjeta_id"], f["equipo"])
        if clave not in excluir:
            por_cond.setdefault(f["num_prohibidas"], {})[clave] = f
    salida = []
    for a, b in combinations(sorted(por_cond), 2):
        comunes = set(por_cond[a]) & set(por_cond[b])
        b10 = sum(1 for k in comunes if por_cond[a][k]["acertada"] and not por_cond[b][k]["acertada"])
        b01 = sum(1 for k in comunes if not por_cond[a][k]["acertada"] and por_cond[b][k]["acertada"])
        salida.append({"condicion_a": a, "condicion_b": b, "n_pares": len(comunes),
                       "acierta_solo_a": b10, "acierta_solo_b": b01,
                       "p_valor_mcnemar": round(mcnemar_exacto(b10, b01), 4)})
    return salida


# ------------------------------------------------- auditoría del vigilante
def auditoria_vigilante(registros: list[dict]) -> dict:
    """Resume cómo se comportó el vigilante a partir de registros.jsonl."""
    veredictos = [v for r in registros for v in r.get("veredictos_vigilante", [])]
    acusa = [v for v in veredictos if v.get("valido") and v.get("infraccion")]
    sin_pruebas = [v for v in acusa if v.get("descartado_por_arbitro")]
    con_pruebas = [v for v in acusa if not v.get("descartado_por_arbitro")]
    n = len(veredictos)
    return {
        "veredictos": n,
        "invalidos": sum(1 for v in veredictos if not v.get("valido")),
        "acusaciones": len(acusa),
        "porcentaje_acusa": round(len(acusa) / n, 4) if n else None,
        "descartadas_sin_pruebas": len(sin_pruebas),
        "porcentaje_sin_pruebas": round(len(sin_pruebas) / len(acusa), 4) if acusa else None,
        "con_pruebas": len(con_pruebas),
        "infracciones_semanticas_aplicadas": sum(
            1 for r in registros for i in r.get("infracciones", []) if i.get("origen") == "semantica"),
    }


def acierto_sin_infraccion(filas: list[dict]) -> list[dict]:
    """Tasa de acierto solo en turnos SIN infracciones, por condición y equipo.

    Separa los dos mecanismos: hacer trampa frente a describir peor.
    """
    grupos: dict[tuple, list[dict]] = {}
    for f in filas:
        if f["infracciones_total"] == 0:
            grupos.setdefault((f["num_prohibidas"], f["equipo"]), []).append(f)
    salida = []
    for (n, eq) in sorted(grupos):
        g = grupos[(n, eq)]
        k = sum(f["acertada"] for f in g)
        lo, hi = wilson(k, len(g))
        salida.append({"num_prohibidas": n, "equipo": eq, "turnos_sin_infraccion": len(g), "aciertos": k,
                       "tasa_acierto": _r(k / len(g)), "ic95_inf": _r(lo), "ic95_sup": _r(hi)})
    return salida
