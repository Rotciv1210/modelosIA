"""Gráficos comparativos del experimento (PNG con matplotlib, sin pantalla).

Un gráfico por métrica con la condición experimental en el eje X, barras de
un solo color (una sola serie) con barras de error = IC 95 % y el valor
escrito sobre cada barra. Además, un gráfico de tasa de acierto por equipo.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # sin ventana: funciona en cualquier equipo
import matplotlib.pyplot as plt  # noqa: E402

AZUL, NARANJA = "#2a78d6", "#eb6834"
TINTA, TINTA_2, REJILLA, FONDO = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
COLORES_SERIES = [AZUL, NARANJA, "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]


def _estilo(ax, titulo: str, ylabel: str) -> None:
    ax.set_facecolor(FONDO)
    ax.set_title(titulo, loc="left", fontsize=12, color=TINTA, pad=12)
    ax.set_ylabel(ylabel, color=TINTA_2, fontsize=10)
    ax.set_xlabel("Número de palabras prohibidas", color=TINTA_2, fontsize=10)
    ax.grid(axis="y", color=REJILLA, linewidth=0.8)
    ax.set_axisbelow(True)
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(TINTA_2)
    ax.tick_params(colors=TINTA_2, length=0)


def _barras(ax, etiquetas, valores, inf, sup, formato, minimo=None):
    x = range(len(etiquetas))
    if minimo is not None:  # p. ej. un recuento no puede ser negativo
        inf = [None if i is None else max(i, minimo) for i in inf]
    err = [[max(0, v - i) if None not in (v, i) else 0 for v, i in zip(valores, inf)],
           [max(0, s - v) if None not in (v, s) else 0 for v, s in zip(valores, sup)]]
    vals = [v if v is not None else 0 for v in valores]
    ax.bar(x, vals, width=0.55, color=AZUL, edgecolor=FONDO, linewidth=2, zorder=2)
    ax.errorbar(x, vals, yerr=err, fmt="none", ecolor=TINTA_2, elinewidth=1.2, capsize=5, zorder=3)
    ax.set_xticks(list(x), etiquetas)
    for xi, v, s, i in zip(x, vals, sup, inf):
        if v < 0:   # barras negativas: etiqueta por debajo del extremo inferior
            ax.annotate(formato(v), (xi, i if i is not None else v), xytext=(0, -6),
                        textcoords="offset points", ha="center", va="top", color=TINTA, fontsize=10)
        else:
            ax.annotate(formato(v), (xi, s if s is not None else v), xytext=(0, 6),
                        textcoords="offset points", ha="center", va="bottom", color=TINTA, fontsize=10)
    if min(vals) < 0:
        ax.axhline(0, color=TINTA_2, linewidth=0.8)
        fondo = min([i for i in inf if i is not None] + vals)
        ax.set_ylim(bottom=fondo * 1.2)   # espacio para la etiqueta bajo la barra


GRAFICOS = [
    # (fichero, título, eje y, valor, ic_inf, ic_sup, formato)
    ("tasa_acierto.png", "Porcentaje de palabras adivinadas", "% de turnos acertados",
     "tasa_acierto", "tasa_acierto_ic95_inf", "tasa_acierto_ic95_sup", lambda v: f"{v:.0%}"),
    ("infracciones.png", "Infracciones por turno", "Infracciones (media)",
     "infracciones_media", "infracciones_ic95_inf", "infracciones_ic95_sup", lambda v: f"{v:.2f}"),
    ("puntuacion.png", "Puntuación media por ronda", "Puntos por turno (media)",
     "puntuacion_media", "puntuacion_ic95_inf", "puntuacion_ic95_sup", lambda v: f"{v:.2f}"),
]


def generar_graficos(resumen_cond: list[dict], resumen_equipo: list[dict], carpeta: Path,
                     simulado: bool = False) -> list[Path]:
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    sufijo = "  [DATOS SIMULADOS]" if simulado else ""
    etiquetas = [str(r["num_prohibidas"]) for r in resumen_cond]
    rutas = []

    for fichero, titulo, ylabel, k, ki, ks, fmt in GRAFICOS:
        fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150, facecolor=FONDO)
        _barras(ax, etiquetas, [r[k] for r in resumen_cond], [r[ki] for r in resumen_cond],
                [r[ks] for r in resumen_cond], fmt)
        if k == "tasa_acierto":
            ax.set_ylim(0, 1.08)
            ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        _estilo(ax, titulo + sufijo, ylabel)
        ax.text(0, -0.2, "Barras de error: IC 95 %", transform=ax.transAxes, fontsize=8, color=TINTA_2)
        fig.tight_layout()
        fig.savefig(carpeta / fichero, facecolor=FONDO)
        plt.close(fig)
        rutas.append(carpeta / fichero)

    # Métricas sin IC (desviación típica como barra de error)
    for fichero, titulo, ylabel, k, ksd, fmt in [
        ("descripciones_invalidas.png", "Descripciones inválidas por turno", "Inválidas (media ± DT)",
         "descripciones_invalidas_media", "descripciones_invalidas_sd", lambda v: f"{v:.2f}"),
        ("intentos.png", "Intentos necesarios (turnos acertados)", "Intentos (media ± DT)",
         "intentos_media_aciertos", "intentos_sd_aciertos", lambda v: f"{v:.2f}"),
        ("tiempo_descriptor.png", "Tiempo de respuesta del descriptor", "Segundos (media ± DT)",
         "tiempo_descriptor_media_s", "tiempo_descriptor_sd_s", lambda v: f"{v:.1f} s"),
    ]:
        vals = [r[k] for r in resumen_cond]
        sds = [r[ksd] or 0 for r in resumen_cond]
        fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150, facecolor=FONDO)
        _barras(ax, etiquetas, vals,
                [None if v is None else v - s for v, s in zip(vals, sds)],
                [None if v is None else v + s for v, s in zip(vals, sds)], fmt, minimo=0)
        _estilo(ax, titulo + sufijo, ylabel)
        ax.text(0, -0.2, "Barras de error: desviación típica", transform=ax.transAxes, fontsize=8, color=TINTA_2)
        fig.tight_layout()
        fig.savefig(carpeta / fichero, facecolor=FONDO)
        plt.close(fig)
        rutas.append(carpeta / fichero)

    # Tasa de acierto por equipo (líneas, una serie por equipo, con leyenda + etiqueta directa)
    equipos = sorted({r["equipo"] for r in resumen_equipo})
    if equipos:
        fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=150, facecolor=FONDO)
        for i, eq in enumerate(equipos[:8]):
            filas = sorted((r for r in resumen_equipo if r["equipo"] == eq), key=lambda r: r["num_prohibidas"])
            xs = [r["num_prohibidas"] for r in filas]
            ys = [r["tasa_acierto"] for r in filas]
            color = COLORES_SERIES[i]
            ax.plot(xs, ys, color=color, linewidth=2, marker="o", markersize=8,
                    markeredgecolor=FONDO, markeredgewidth=2, label=eq, zorder=3)
            if len(equipos) <= 4 and ys:
                ax.annotate(eq, (xs[-1], ys[-1]), xytext=(8, 0), textcoords="offset points",
                            va="center", fontsize=9, color=TINTA)
        ax.set_xticks(sorted({r["num_prohibidas"] for r in resumen_equipo}))
        ax.set_ylim(0, 1.05)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
        _estilo(ax, "Porcentaje de acierto por equipo" + sufijo, "% de turnos acertados")
        ax.legend(frameon=False, loc="lower left", fontsize=9)
        fig.tight_layout()
        fig.savefig(carpeta / "acierto_por_equipo.png", facecolor=FONDO)
        plt.close(fig)
        rutas.append(carpeta / "acierto_por_equipo.png")
    return rutas
