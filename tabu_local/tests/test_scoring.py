from config import GameConfig
from game.records import ACIERTO, FALLO, INFRACCION, INVALIDA, TurnRecord
from game.scoring import Marcador, puntuar_turno


def registro(equipo="A", acertada=False, infracciones=0, resultado=FALLO):
    r = TurnRecord(partida_id="p", ronda=1, equipo=equipo, modelo_descriptor="d",
                   modelo_adivinador="a", modelo_vigilante=None, tarjeta_id="t",
                   palabra_secreta="perro", palabras_prohibidas=[], categoria="animales",
                   dificultad="facil", num_prohibidas=3, max_intentos=3)
    r.acertada = acertada
    r.resultado = resultado
    r.infracciones = [{"origen": "automatica"}] * infracciones
    return r


def test_puntuacion_basica():
    cfg = GameConfig()
    assert puntuar_turno(registro(acertada=True, resultado=ACIERTO), cfg) == 1
    assert puntuar_turno(registro(), cfg) == 0
    assert puntuar_turno(registro(infracciones=1, resultado=INFRACCION), cfg) == -1
    # sin fin de turno por infracción se puede acertar con penalización
    assert puntuar_turno(registro(acertada=True, infracciones=2, resultado=ACIERTO), cfg) == -1


def test_puntuacion_configurable():
    cfg = GameConfig(puntos_acierto=3, penalizacion_infraccion=2, penalizacion_invalida=1)
    assert puntuar_turno(registro(acertada=True, resultado=ACIERTO), cfg) == 3
    assert puntuar_turno(registro(infracciones=1, resultado=INFRACCION), cfg) == -2
    assert puntuar_turno(registro(resultado=INVALIDA), cfg) == -1


def test_marcador_ganador_y_desempate():
    m = Marcador(["A", "B"])
    for r in (registro("A", True, resultado=ACIERTO), registro("B", True, resultado=ACIERTO)):
        r.puntuacion = 1
        m.registrar(r)
    assert m.ganadores() == ["A", "B"]                     # empate total
    r = registro("B", infracciones=1, resultado=INFRACCION)
    r.puntuacion = -1
    m.registrar(r)
    assert m.ganadores() == ["A"]
    assert m.clasificacion()[0] == ("A", 1)
    assert m.to_dict()["infracciones"]["B"] == 1
