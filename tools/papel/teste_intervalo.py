"""Testes do robô do intervalo (intervalo.py), da leitura da API-Football (af.py) e das contas do intervalo nos cartões,
sem rede: uma API-Football de mentira com um jogo no intervalo, um perto dos 75' e um palpite do Theo para começar."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import af  # noqa: E402
import cartoes as C  # noqa: E402
import intervalo as I  # noqa: E402

MIN = 60 * 1000
HORA = 60 * MIN
AGORA = 1795370400000  # 2026-11-22 18:00 UTC


def iso(ms):
    import datetime as dt
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


JOGOS = [  # id, início, casa, fora, liga
    (101, AGORA - 50 * MIN, "Arsenal", "Chelsea", 39),
    (102, AGORA - 95 * MIN, "Liverpool", "Everton", 39),
    (103, AGORA + 30 * MIN, "Flamengo", "Palmeiras", 71),
    (104, AGORA - 50 * MIN, "Ajax", "PSV", 88),
]


class Falsa:
    def __init__(self, resto=80):
        self.urls, self.resto = [], resto

    def pedir(self, url):
        assert "chave" not in url
        self.urls.append(url)
        self.resto -= 1
        if "/fixtures?date=" in url:
            return {"errors": [], "response": [
                {"fixture": {"id": i, "date": iso(ms), "status": {"short": "NS"}}, "league": {"id": lg},
                 "teams": {"home": {"name": c}, "away": {"name": f}}} for i, ms, c, f, lg in JOGOS]}, self.resto
        if url.endswith("/odds/live"):
            return {"errors": [], "response": [
                {"fixture": {"id": 101, "status": {"short": "HT", "elapsed": 45}}, "teams": {"home": {"goals": 0}, "away": {"goals": 0}},
                 "odds": [{"name": "Total Cards", "values": [{"value": "Over", "odd": "1.80", "handicap": "1.5"},
                                                             {"value": "Under", "odd": "2.00", "handicap": "1.5"},
                                                             {"value": "Over", "odd": "2.60", "handicap": "2.5", "suspended": True}]},
                          {"name": "Home Team Total Cards", "values": [{"value": "Over", "odd": "9.0", "handicap": "1.5"}]},
                          {"name": "Over/Under Line", "values": [{"value": "Over", "odd": "1.40", "handicap": "0.5"}]},
                          {"name": "Total Corners", "values": [{"value": "Over", "odd": "1.90", "handicap": "7.5"}]},
                          {"name": "Race to the 5th corner?", "values": [{"value": "1", "odd": "1.8"}]},
                          {"name": "Fulltime Result", "values": [{"value": "Home", "odd": "2.0"}]}]},
                {"fixture": {"id": 102, "status": {"short": "2H", "elapsed": 76}}, "teams": {"home": {"goals": 1}, "away": {"goals": 1}},
                 "odds": [{"name": "Over/Under Line", "values": [{"value": "Over", "odd": "2.10", "handicap": "2.5"}]},
                          {"name": "Total Cards", "values": [{"value": "Over", "odd": "1.5", "handicap": "4.5"}]}]},
                {"fixture": {"id": 104, "status": {"short": "HT", "elapsed": 45}}, "teams": {"home": {"goals": 0}, "away": {"goals": 0}},
                 "odds": [{"name": "Total Cards", "values": [{"value": "Over", "odd": "1.80", "handicap": "1.5"}]}]}]}, self.resto
        if "/odds?fixture=103" in url:
            return {"errors": [], "response": [{"bookmakers": [
                {"name": "Pinnacle", "bets": [{"name": "Match Winner", "values": [{"value": "Home", "odd": "1.90"}, {"value": "Draw", "odd": "3.50"}, {"value": "Away", "odd": "4.40"}]}]},
                {"name": "Betano", "bets": [{"name": "Match Winner", "values": [{"value": "Home", "odd": "1.95"}, {"value": "Draw", "odd": "3.40"}, {"value": "Away", "odd": "4.20"}]},
                                            {"name": "Goals Over/Under", "values": [{"value": "Over 2.5", "odd": "2.05"}, {"value": "Under 2.5", "odd": "1.80"}]}]}]}]}, self.resto
        return {"errors": {"x": "?"}, "response": []}, self.resto


def teste_robo():
    E, logs = {}, []
    cli = Falsa()
    R = I.Robo(E, cli, AGORA, logs.append)
    R.theo([("Flamengo", "Palmeiras", AGORA + 30 * MIN, "2026-11-22"), ("Botafogo", "Bahia", None, "2026-11-22")])
    n = R.ao_vivo()
    assert n == 2, (n, logs)
    a, b = E["cap"]["101"], E["cap"]["102"]
    assert a["liga"] == "eng" and a["c"] == "Arsenal" and a["ht"]["gols"] == [0, 0] and "m75" not in a
    # só os mais/menos com linha de cartões, escanteios e gols (a odd suspensa e os mercados sem linha ficam de fora)
    assert a["ht"]["m"]["Total Cards"] == [["over", 1.5, 1.8], ["under", 1.5, 2.0]], a["ht"]["m"]
    assert "Race to the 5th corner?" not in a["ht"]["m"] and "Fulltime Result" not in a["ht"]["m"]
    assert b["m75"]["min"] == 76 and b["m75"]["gols"] == [1, 1] and list(b["m75"]["m"]) == ["Over/Under Line"]
    assert "104" not in E["cap"]  # a liga não é acompanhada
    # o fechamento do palpite do Theo (até 40 min antes): Pinnacle e Betano
    f = E["theo"]["103"][0]
    assert f["casa"] == "Betano" and f["pin"]["1x2"] == [1.9, 3.5, 4.4] and f["soft"]["ou"] == [2.05, 1.8] and f["fech"]
    usados = len(cli.urls)
    assert usados == 3 and E["uso"][R.hoje] == 3, cli.urls  # a lista do dia, o fechamento e o ao vivo
    # a 2ª rodada no mesmo minuto não pede nada (a lista vale 6 h, o fechamento e as capturas já foram)
    R2 = I.Robo(E, cli, AGORA + MIN, logs.append)
    R2.theo([("Flamengo", "Palmeiras", AGORA + 30 * MIN, "2026-11-22")])
    assert R2.ao_vivo() == 0 and len(cli.urls) == usados
    # o freio: com poucos pedidos restantes na API-Football, nada é pedido
    E2 = {}
    cli2 = Falsa(resto=I.FOLGA - 1)
    R3 = I.Robo(E2, cli2, AGORA, logs.append)
    R3.ao_vivo()
    R3b = I.Robo(E2, cli2, AGORA + 20 * MIN, logs.append)
    E2["dias"] = {}
    R3b.ao_vivo()
    assert len(cli2.urls) == 1, cli2.urls
    # o limite do dia
    E3 = {"uso": {R.hoje: I.LIMITE_DIA}}
    cli3 = Falsa()
    I.Robo(E3, cli3, AGORA, logs.append).ao_vivo()
    assert not cli3.urls
    # a saída e a limpeza
    out = R.saida()
    assert set(out) == {"v", "agora", "cap", "theo"} and out["cap"]["101"]["ht"]
    R4 = I.Robo(E, cli, AGORA + 40 * 24 * HORA, logs.append)
    R4.limpar()
    assert not E["cap"] and not E["theo"]


def teste_leitura_af():
    assert af._valores({"values": [{"value": "Over 2.5", "odd": "1.85"}, {"value": "Under", "odd": "2", "handicap": "2.5"},
                                   {"value": "Home", "odd": "1.0"}, {"value": "Away", "odd": "x"}]}) == [("over", 2.5, 1.85), ("under", 2.5, 2.0)]
    assert af.jogos_do_dia({"response": [{"fixture": {"id": 5, "date": "2026-11-22T19:00:00+00:00", "status": {"short": "FT"}},
                                          "league": {"id": 71}, "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
                                          "goals": {"home": 2, "away": 1}, "score": {"fulltime": {"home": 1, "away": 1}}}]})[0]["placar"] == [1, 1]
    assert af.odds_prejogo({"response": [{"bookmakers": [{"name": "Betano", "bets": []}]}]}) is None
    assert af.no_intervalo({"st": "HT"}) and af.no_intervalo({"st": "Halftime"}) and not af.no_intervalo({"st": "2H"})


def _jogo(ms, casa, fora, c1, c2, nar=None, gols=None, liga="eng"):
    return [ms, liga, casa, fora, c1, c2, c1, c2, None, nar, gols]


def teste_contas():
    E = {}
    R = I.Robo(E, Falsa(), AGORA, [].append)
    R.ao_vivo()
    robo = R.saida()
    est = {"jogos": {}}
    # 10 jogos de antes com 5 chutes no 1º tempo (a mediana) e os dois capturados
    for k in range(10):
        est["jogos"][f"x{k}"] = _jogo(AGORA - (20 + k) * HORA, f"T{k}", f"U{k}", 1, 1, gols=[1, 1, 0, 0, 3, 5])
    est["jogos"]["a"] = _jogo(AGORA - 50 * MIN, "Arsenal", "Chelsea", 0, 3, nar=[4, 5, 5, 4, 9, 10, 11, 9, 8],
                              gols=[0, 1, 1, 1, 4, 9])
    est["jogos"]["b"] = _jogo(AGORA - 95 * MIN, "Liverpool", "Everton", 1, 2, gols=[1, 1, 0, 1, 2, 6])
    C.contas_intervalo(est, robo)
    aps = est["int"]["ap"]
    assert {a["c"] for a in aps.values()} == {"cartL", "cart15", "escL", "esc35", "gol2t", "gol2tP", "fim75"}, aps
    a = {a["c"]: a for a in aps.values()}
    assert a["cart15"]["o"] == 1.8 and a["cart15"]["g"]             # 3 no 2º tempo
    assert a["cartL"]["o"] == 1.8 and a["escL"]["o"] == 1.9 and a["escL"]["g"]  # a linha principal: 7,5 e 9 no jogo
    assert C._linha_principal({"Total Cards": [["over", 3.5, 1.73], ["over", 2.5, 1.3], ["over", 4.0, 2.0]]}, C.RX_INT_CART) == (3.5, 1.73)
    assert a["esc35"]["o"] == 1.9 and a["esc35"]["g"]               # 4 no 1º: a linha 7,5; 5 no 2º
    assert a["gol2t"]["o"] == 1.4 and a["gol2t"]["g"] and a["gol2tP"]["g"]
    assert a["fim75"]["o"] == 2.1 and not a["fim75"]["g"]           # 1×1 aos 76', acabou 1×1
    # sem repetir na rodada seguinte
    C.contas_intervalo(est, robo)
    assert len(est["int"]["ap"]) == 7
    r = C.resumo_intervalo(est, robo)
    cs = {c["id"]: c for c in r["contas"]}
    assert r["capturas"] == 1 and r["m75"] == 1 and r["valor"] == 20
    assert cs["cart15"]["apostas"] == 1 and cs["cart15"]["lucro"] == 16.0 and cs["fim75"]["lucro"] == -20.0
    assert cs["cart25"]["apostas"] == 0 and cs["cart25"]["acerto"] is None
    assert cs["gol2t"]["ultimas"][0]["jogo"] == "Arsenal × Chelsea" and cs["gol2t"]["ultimas"][0]["ganhou"]
    assert ["Total Cards", 1] in r["mercados"]
    # o resumo dos cartões leva o bloco
    assert C.resumo(est, AGORA, robo)["intervalo"]["contas"]




# ------------------------------------------------------------------------------------ pela The Odds API (26/11/2026)
def _espn(jogos):
    """Um placar da ESPN: jogos = [(id, início, casa, fora, gols, estado, intervalo, período, relógio)]."""
    ev = []
    for i, ms, c, f, g, st, ht, per, rel in jogos:
        ev.append({"id": i, "date": iso(ms), "competitions": [{
            "status": {"displayClock": rel, "period": per,
                       "type": {"state": st, "name": "STATUS_HALFTIME" if ht else "STATUS_SECOND_HALF", "shortDetail": "HT" if ht else rel}},
            "competitors": [{"homeAway": "home", "score": str(g[0]), "team": {"displayName": c}},
                            {"homeAway": "away", "score": str(g[1]), "team": {"displayName": f}}]}]})
    return {"events": ev}


class FalsaTOA:
    def __init__(self, resto=400):
        self.pedidos, self.resto, self.ultimo = [], resto, None

    def pedir(self, caminho, **q):
        assert "apiKey" not in q
        self.pedidos.append((caminho, q))
        if caminho.endswith("/events"):
            self.ultimo = 0
            return [{"id": "ev1", "commence_time": iso(AGORA - 55 * MIN), "home_team": "Arsenal", "away_team": "Chelsea"},
                    {"id": "ev2", "commence_time": iso(AGORA - 95 * MIN), "home_team": "Liverpool", "away_team": "Everton"}], self.resto
        mks = q["markets"].split(",")
        self.ultimo = len(mks)
        self.resto -= len(mks)
        casas = [{"key": "betway", "markets": [{"key": "alternate_totals", "outcomes": [{"name": "Over", "point": 0.5, "price": 1.3}]}]},
                 {"key": "pinnacle", "markets": [
                     {"key": "alternate_totals_cards", "outcomes": [{"name": "Over", "point": 1.5, "price": 1.8}, {"name": "Under", "point": 1.5, "price": 2.0}]},
                     {"key": "alternate_totals", "outcomes": [{"name": "Over", "point": 0.5, "price": 1.4}, {"name": "Over", "point": 2.5, "price": 2.1}]}]},
                 {"key": "leovegas", "markets": [{"key": "alternate_totals_corners", "outcomes": [{"name": "Over", "point": 7.5, "price": 1.9}]}]}]
        return {"id": caminho.split("/")[4], "bookmakers": casas}, self.resto


def teste_robo_theodds():
    import theodds as T
    E, logs = {}, []
    placar = _espn([("901", AGORA - 55 * MIN, "Arsenal", "Chelsea", [0, 0], "in", True, 1, "45'"),
                    ("902", AGORA - 95 * MIN, "Liverpool", "Everton", [1, 1], "in", False, 2, "76'"),
                    ("903", AGORA - 95 * MIN, "Spurs", "Fulham", [2, 0], "in", False, 2, "76'")])
    urls = []

    def buscar(url):
        urls.append(url)
        return placar if "eng.1" in url else {"events": []}
    cli = FalsaTOA()
    R = I.RoboTOA(E, cli, AGORA, logs.append, buscar=buscar)
    n = R.ao_vivo()
    assert n == 2, (n, logs)
    a, b = E["cap"]["e901"], E["cap"]["e902"]
    assert a["liga"] == "eng" and a["ht"]["gols"] == [0, 0] and a["fonte"] == "theodds"
    m = a["ht"]["m"]
    assert m["Cards Over/Under · pinnacle"] == [["over", 1.5, 1.8], ["under", 1.5, 2.0]], m
    assert list(m)[0].endswith("pinnacle")  # a Pinnacle antes das outras casas
    assert b["m75"]["min"] == 76 and b["m75"]["gols"] == [1, 1] and all("Goals" in k for k in b["m75"]["m"])
    assert "e903" not in E["cap"]  # 2 × 0 aos 76': não está empatado, não gasta
    odds = [q for c, q in cli.pedidos if c.endswith("/odds")]
    assert sorted(q["markets"] for q in odds) == ["alternate_totals", "alternate_totals_cards,alternate_totals_corners,alternate_totals"]
    assert R.X["uso"][R.hoje] == 4 and R.X["resto"] == 396
    # o Observatório lê como antes: cartões e escanteios pela 1ª casa que bate, a betway fica fora (o "away" no nome)
    assert C._odd_int(m, C.RX_INT_CART, 1.5) == 1.8 and C._odd_int(m, C.RX_INT_ESC, 7.5) == 1.9
    assert C._odd_int(m, C.RX_INT_GOL, 0.5) == 1.4
    # a 2ª volta não pede odds de novo
    pedidos = len(cli.pedidos)
    R2 = I.RoboTOA(E, cli, AGORA + 5 * MIN, logs.append, buscar=buscar)
    assert R2.ao_vivo() == 0 and len(cli.pedidos) == pedidos
    # o freio do mês e o do dia
    E2 = {"toa": {"resto": I.FOLGA_TOA + 1}}
    cli2 = FalsaTOA(resto=I.FOLGA_TOA + 1)
    I.RoboTOA(E2, cli2, AGORA, logs.append, buscar=buscar).ao_vivo()
    assert [c for c, _ in cli2.pedidos if c.endswith("/odds")] == ["/sports/soccer_epl/events/ev2/odds"], cli2.pedidos  # só o de 1 crédito
    E3 = {"toa": {"uso": {I.dia(AGORA): I.LIMITE_TOA_DIA}}}
    cli3 = FalsaTOA()
    I.RoboTOA(E3, cli3, AGORA, logs.append, buscar=buscar).ao_vivo()
    assert not cli3.pedidos
    # a leitura da ESPN
    j = T.espn(placar)
    assert j[0]["ht"] and j[1]["min"] == 76 and j[1]["periodo"] == 2 and j[2]["gols"] == [2, 0]


if __name__ == "__main__":
    teste_leitura_af()
    teste_robo()
    teste_contas()
    teste_robo_theodds()
    print("ok")
