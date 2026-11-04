import json

import pytest

from cards.deck import cargar_tarjetas
from config import CARDS_DIR
from game.game_engine import MotorJuego, crear_arbitro
from game.game_logger import cargar_partida, listar_partidas
from game.records import ACIERTO, ERROR, FALLO, INFRACCION, INVALIDA
from game.referee import Arbitro
from game.turn_manager import GestorTurno, TurnoAbortado
from models.fake_client import ScriptedClient
from models.ollama_client import ModelNotFoundError, OllamaTimeoutError, OllamaUnavailableError
from tests.conftest import ADIV, DESC, VEREDICTO_OK, VIG

PISTA = "Animal doméstico muy fiel que mueve la cola."
PISTA2 = "Es el mejor amigo del ser humano."


def jugar(cfg, tarjeta, guiones, vigilante=True, eventos=None):
    cliente = ScriptedClient(guiones)
    if not vigilante:
        cfg.juego.usar_vigilante_semantico = False
    arbitro = crear_arbitro(cfg, cliente)
    gestor = GestorTurno(cfg.juego, cliente, arbitro,
                         observador=(lambda e, d: eventos.append(e)) if eventos is not None else None)
    rec = gestor.jugar(tarjeta, cfg.equipos[0], 1, "p", cfg.juego.num_prohibidas,
                       VIG if vigilante else None, semilla=1)
    return rec, cliente


# ------------------------------------------------------------- flujo básico
def test_acierto_primer_intento(cfg, tarjeta_perro):
    rec, cli = jugar(cfg, tarjeta_perro, {DESC: [PISTA], ADIV: ['{"respuesta": "Perro"}'], VIG: [VEREDICTO_OK]})
    assert rec.resultado == ACIERTO and rec.acertada and rec.puntuacion == 1
    assert rec.intentos_usados == 1 and rec.descripciones == [PISTA]
    assert rec.veredictos_vigilante[0]["infraccion"] is False


def test_acierto_en_segundo_intento_con_pista_adicional(cfg, tarjeta_perro):
    rec, cli = jugar(cfg, tarjeta_perro, {
        DESC: [PISTA, PISTA2], ADIV: ['{"respuesta": "lobo"}', '{"respuesta": "perro"}'], VIG: [VEREDICTO_OK]})
    assert rec.resultado == ACIERTO and rec.intentos_usados == 2
    assert rec.respuestas_adivinador == ["lobo", "perro"]
    # el descriptor recibe los fallos del adivinador para afinar la pista
    assert "lobo" in cli.llamadas_de(DESC)[1]["messages"][1]["content"]


def test_fallo_tras_agotar_intentos(cfg, tarjeta_perro):
    rec, _ = jugar(cfg, tarjeta_perro, {
        DESC: [PISTA, PISTA2, "Tiene cuatro patas y protege la casa."],
        ADIV: ['{"respuesta": "lobo"}', '{"respuesta": "zorro"}', '{"respuesta": "oveja"}'],
        VIG: [VEREDICTO_OK]})
    assert rec.resultado == FALLO and rec.puntuacion == 0 and rec.intentos_usados == 3


# ---------------------------------------------------------------- trampas
def test_infraccion_automatica_corta_turno_y_no_llega_al_adivinador(cfg, tarjeta_perro):
    rec, cli = jugar(cfg, tarjeta_perro, {
        DESC: ["Es un animal que sabe ladrar muy fuerte."], ADIV: ['{"respuesta": "perro"}'], VIG: [VEREDICTO_OK]})
    assert rec.resultado == INFRACCION and rec.puntuacion == -1
    assert rec.infracciones[0]["origen"] == "automatica" and rec.infracciones[0]["objetivo"] == "ladrar"
    assert cli.llamadas_de(ADIV) == []          # la pista tramposa nunca se entrega
    assert cli.llamadas_de(VIG) == []           # ni hace falta consultar al vigilante


def test_infraccion_semantica(cfg, tarjeta_perro):
    veredicto = ('{"infraccion": true, "palabra_detectada": "can", "tipo_infraccion": "sinonimo_evidente", '
                 '"justificacion": "can es sinónimo de perro", "nivel_confianza": 0.92}')
    rec, cli = jugar(cfg, tarjeta_perro, {DESC: ["Un can muy simpático."], ADIV: ['{"respuesta": "perro"}'],
                                          VIG: [veredicto]})
    assert rec.resultado == INFRACCION and rec.infracciones[0]["origen"] == "semantica"
    assert cli.llamadas_de(ADIV) == []


def test_vigilante_sin_pruebas_se_descarta(cfg, tarjeta_perro):
    # El vigilante afirma que aparece la secreta, pero no está en el texto (caso real con gemma2:2b)
    falso = ('{"infraccion": true, "palabra_detectada": "perro", "tipo_infraccion": "revelacion_directa", '
             '"justificacion": "menciona la palabra secreta", "nivel_confianza": 0.9}')
    rec, _ = jugar(cfg, tarjeta_perro, {DESC: [PISTA], ADIV: ['{"respuesta": "perro"}'], VIG: [falso]})
    assert rec.resultado == ACIERTO and rec.infracciones == []
    assert "no aparece" in rec.veredictos_vigilante[0]["descartado_por_arbitro"]


def test_descripcion_larga_se_corta_en_frase_completa(cfg, tarjeta_perro):
    from game.referee import recortar_por_frases
    texto = "Primera frase corta. Segunda frase también corta. " + "palabra " * 50
    assert recortar_por_frases(texto, 10) == "Primera frase corta. Segunda frase también corta."
    assert recortar_por_frases("una dos tres cuatro cinco seis", 3) == "una dos tres…"


def test_vigilante_poco_seguro_o_consultivo_no_penaliza(cfg, tarjeta_perro):
    dudoso = ('{"infraccion": true, "palabra_detectada": "fiel", "tipo_infraccion": "otra", '
              '"justificacion": "quizá", "nivel_confianza": 0.5}')
    rec, _ = jugar(cfg, tarjeta_perro, {DESC: [PISTA], ADIV: ['{"respuesta": "perro"}'], VIG: [dudoso]})
    assert rec.resultado == ACIERTO and rec.infracciones == []
    seguro = dudoso.replace("0.5", "0.99")
    cfg.juego.vigilante_modo = "consultivo"
    rec, _ = jugar(cfg, tarjeta_perro, {DESC: [PISTA], ADIV: ['{"respuesta": "perro"}'], VIG: [seguro]})
    assert rec.resultado == ACIERTO and rec.veredictos_vigilante[0]["infraccion"] is True


def test_infraccion_sin_fin_de_turno(cfg, tarjeta_perro):
    cfg.juego.fin_turno_por_infraccion = False
    rec, _ = jugar(cfg, tarjeta_perro, {DESC: ["Le encantan los huesos.", PISTA], ADIV: ['{"respuesta": "perro"}']},
                   vigilante=False)
    assert rec.resultado == ACIERTO and rec.puntuacion == 0      # +1 acierto -1 infracción
    assert rec.intentos_usados == 2


# ------------------------------------------------- aislamiento de información
def test_adivinador_nunca_ve_secreta_ni_prohibidas(cfg, tarjeta_perro):
    rec, cli = jugar(cfg, tarjeta_perro, {
        DESC: [PISTA, PISTA2, "Tiene cuatro patas."],
        ADIV: ['{"respuesta": "lobo"}', '{"respuesta": "zorro"}', '{"respuesta": "oveja"}'], VIG: [VEREDICTO_OK]})
    for llamada in cli.llamadas_de(ADIV):
        texto = " ".join(m["content"] for m in llamada["messages"]).lower()
        assert "perro" not in texto
        for p in tarjeta_perro.prohibidas_para(cfg.juego.num_prohibidas):
            assert p not in texto


# ------------------------------------------------ robustez ante respuestas
def test_recuperacion_de_descripcion_vacia(cfg, tarjeta_perro):
    rec, cli = jugar(cfg, tarjeta_perro, {DESC: ["", "   ", PISTA], ADIV: ['{"respuesta": "perro"}'],
                                          VIG: [VEREDICTO_OK]})
    assert rec.resultado == ACIERTO and rec.descripciones_invalidas == 2
    assert "no era válida" in cli.llamadas_de(DESC)[1]["messages"][1]["content"]


def test_descripcion_invalida_definitiva(cfg, tarjeta_perro):
    rec, _ = jugar(cfg, tarjeta_perro, {DESC: ["", "Lo siento, no puedo decir la palabra secreta.", "ok"],
                                        ADIV: ['{"respuesta": "x"}']}, vigilante=False)
    assert rec.resultado == INVALIDA and rec.descripciones_invalidas == 3


def test_timeout_se_registra_y_se_recupera(cfg, tarjeta_perro):
    rec, _ = jugar(cfg, tarjeta_perro, {DESC: [OllamaTimeoutError("lento"), PISTA],
                                        ADIV: ['{"respuesta": "perro"}']}, vigilante=False)
    assert rec.resultado == ACIERTO
    assert any("OllamaTimeoutError" in e for e in rec.errores)


def test_timeouts_continuos_terminan_en_error(cfg, tarjeta_perro):
    rec, _ = jugar(cfg, tarjeta_perro, {DESC: [OllamaTimeoutError("lento")], ADIV: ["x"]}, vigilante=False)
    assert rec.resultado == ERROR and len(rec.errores) == 3


def test_respuesta_larga_se_trunca(cfg, tarjeta_perro):
    larga = "Animal fiel y simpático " * 30
    rec, _ = jugar(cfg, tarjeta_perro, {DESC: [larga], ADIV: ['{"respuesta": "perro"}']}, vigilante=False)
    assert len(rec.descripciones[0].split()) == cfg.juego.max_palabras_descripcion
    assert rec.descripciones[0].endswith("…")
    assert any("truncada" in e for e in rec.errores)


def test_adivinador_repetido_o_sin_formato(cfg, tarjeta_perro):
    rec, cli = jugar(cfg, tarjeta_perro, {
        DESC: [PISTA, PISTA2],
        ADIV: ['{"respuesta": "lobo"}', '{"respuesta": "lobo"}', "Creo que es: el perro."]}, vigilante=False)
    assert rec.resultado == ACIERTO and rec.respuestas_repetidas == 1
    assert rec.respuestas_adivinador == ["lobo", "perro"]


def test_descriptor_repetido_se_rechaza(cfg, tarjeta_perro):
    rec, _ = jugar(cfg, tarjeta_perro, {DESC: [PISTA, PISTA, PISTA2],
                                        ADIV: ['{"respuesta": "lobo"}', '{"respuesta": "perro"}']}, vigilante=False)
    assert rec.descripciones == [PISTA, PISTA2]
    assert rec.descripciones_rechazadas[0]["motivo"] == "repetida"


def test_extraer_respuesta():
    f = Arbitro.extraer_respuesta
    assert f('{"respuesta": "El Pingüino"}') == "pingüino"
    assert f('```json\n{"respuesta": "gato"}\n```') == "gato"
    assert f("Respuesta: perro.") == "perro"
    assert f("") is None
    assert f("esto es una respuesta demasiado larga para ser una palabra") is None


@pytest.mark.parametrize("error", [OllamaUnavailableError("caído"), ModelNotFoundError("no está")])
def test_errores_fatales_abortan_turno(cfg, tarjeta_perro, error):
    with pytest.raises(TurnoAbortado) as exc:
        jugar(cfg, tarjeta_perro, {DESC: [error], ADIV: ["x"]}, vigilante=False)
    assert exc.value.registro.resultado == ERROR


# ------------------------------------------------------- partida completa
def _cliente_partida():
    return ScriptedClient({DESC: [lambda m: f"Pista número {len(m[1]['content'])} sobre algo conocido."],
                           ADIV: ['{"respuesta": "nada"}'], VIG: [VEREDICTO_OK]})


def test_partida_completa_alterna_equipos_y_guarda_json(cfg, tmp_path):
    tarjetas = cargar_tarjetas(CARDS_DIR / "cards.json")
    eventos = []
    motor = MotorJuego(cfg, _cliente_partida(), tarjetas, observador=lambda e, d: eventos.append(e),
                       directorio_partidas=tmp_path)
    res = motor.jugar_partida()
    assert res.estado == "terminada"
    assert [r.equipo for r in res.registros] == ["A", "B", "A", "B"]
    assert len({r.tarjeta_id for r in res.registros}) == 4          # ninguna tarjeta repetida
    datos = json.loads(res.ruta_registro.read_text(encoding="utf-8"))
    campos = {"partida_id", "ronda", "modelo_descriptor", "modelo_adivinador", "modelo_vigilante",
              "palabra_secreta", "palabras_prohibidas", "descripciones", "respuestas_adivinador",
              "resultado", "infracciones", "puntuacion", "tiempo_total_s", "errores"}
    assert campos <= set(datos["turnos"][0])
    assert datos["marcador"]["ganadores"]
    assert listar_partidas(tmp_path)[0]["turnos"] == 4
    assert cargar_partida(res.partida_id[:20], tmp_path)["partida_id"] == res.partida_id
    assert eventos[0] == "partida_inicio" and eventos[-1] == "partida_fin"


def test_partida_con_mazo_insuficiente(cfg, tmp_path, tarjeta_perro):
    res = MotorJuego(cfg, _cliente_partida(), [tarjeta_perro], directorio_partidas=tmp_path).jugar_partida()
    assert res.estado == "mazo_agotado" and len(res.registros) == 1


def test_partida_abortada_si_ollama_cae(cfg, tmp_path):
    cliente = ScriptedClient({DESC: [OllamaUnavailableError("caído")], ADIV: ["x"], VIG: [VEREDICTO_OK]})
    res = MotorJuego(cfg, cliente, cargar_tarjetas(CARDS_DIR / "cards.json"),
                     directorio_partidas=tmp_path).jugar_partida()
    assert res.estado == "abortada"
    assert json.loads(res.ruta_registro.read_text(encoding="utf-8"))["estado"] == "abortada"
