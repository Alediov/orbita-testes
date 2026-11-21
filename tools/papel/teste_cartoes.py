"""Testes do observatório dos cartões no intervalo (cartoes.py), sem rede: o placar da ESPN de mentira do
falso_apostas.py (listas de jogos e resumos com os lances)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cartoes as C  # noqa: E402
import falso_apostas  # noqa: E402
import teste_apostas as T  # noqa: E402
from conta import DIA, HORA  # noqa: E402


def teste_lances():
    am = {"type": {"text": "Yellow Card"}, "clock": {"displayValue": "45'+2'", "value": 2820}, "team": {"id": "7"}}
    assert C.eh_cartao(am) and C.tempo(am) == 1          # acréscimo do 1º tempo pelo minuto escrito
    assert C.tempo({"clock": {"value": 2820}}) == 2        # sem o minuto escrito, só pelos segundos
    assert C.tempo({"period": {"number": 3}, "clock": {"displayValue": "95'"}}) is None  # prorrogação não conta
    assert C.tempo({"period": 2}) == 2
    assert not C.eh_cartao({"type": {"text": "Penalty - Scored"}}) and not C.eh_cartao({"type": {"text": "Goal"}})
    assert C.eh_cartao({"type": {"type": "red-card"}}) and C.eh_cartao({"yellowCard": True})
    assert not C.eh_cartao({"type": {"text": "Substitution"}})
    evs = [am, {"type": {"text": "Red Card"}, "period": {"number": 2}, "team": {"id": "9"}},
           {"type": {"text": "Yellow Card"}, "period": {"number": 2}},  # sem time: só no total
           {"type": {"text": "Goal"}, "period": {"number": 1}, "team": {"id": "7"}}]
    assert C.contar(evs, "7", "9") == (1, 2, 1, 1)
    assert C.contar(None, "7", "9") is None and C.contar([], "7", "9") == (0, 0, 0, 0)
    assert C.lances({"keyEvents": []}) == [] and C.lances({"header": {}}) is None
    assert C.lances({"header": {"competitions": [{"details": [am]}]}}) == [am]
    lo, hi = C.wilson(7, 7)
    assert 0.6 < lo < 0.7 and hi == 1.0 and C.wilson(0, 0) == (None, None)
    js = [[0, "eng", "A", "B", 0, 3, 2, 1], [0, "eng", "A", "C", 0, 1, 1, 0], [0, "eng", "B", "C", 2, 2, 2, 2]]
    t = C.taxa(js[:2], 1.5)
    assert t["n"] == 2 and t["k"] == 1 and t["taxa"] == 0.5 and t["justa"] == 2.0
    assert C.taxa([], 1.5)["taxa"] is None


def teste_coleta():
    cli = T.Cli()
    fonte = cli if hasattr(cli, "oddspapi") else falso_apostas.Avulsa(cli)
    est, erros, logs = {}, [], []
    t0 = cli.agora
    for k in range(16):
        cli.agora = t0 + k * 6 * HORA
        C.coletar(fonte, est, cli.agora, lambda: 3000, logs.append, erros)
    assert not erros, erros[:3]
    js = est["jogos"]
    assert len(js) > 150 and not est["pend"]
    # os campeonatos que o mundo de mentira não tem (404) ficam 7 dias parados, com o aviso no log
    assert set(est["pausa"]) == {"bra2", "cdb", "sud", "ucl", "uel"}
    assert any("não reconhece bra.2" in x for x in logs) and any("formato de um lance" in x for x in logs)
    # cada jogo bate com os lances do resumo de mentira (os gols e o "Penalty - Scored" não contam)
    for eid, j in list(js.items())[:40]:
        jogo = fonte.futebol.por_id(eid)
        r = falso_apostas.resumo_espn(jogo)
        c = C.contar(r["keyEvents"], falso_apostas.id_time(jogo["casa"]), falso_apostas.id_time(jogo["fora"]))
        assert tuple(j[4:]) == c and j[6] + j[7] == j[4] + j[5], (eid, j, c)
    assert est["semLances"] > 0                     # 1 de cada 20 resumos vem sem lances
    # os dias lidos não são pedidos de novo: uma rodada a mais quase não pede nada
    antes = fonte.contagem["espn"]
    C.coletar(fonte, est, cli.agora + HORA, lambda: 3000, logs.append, erros)
    assert fonte.contagem["espn"] - antes <= 12, fonte.contagem["espn"] - antes
    # o limite de tempo: sem tempo, nada é pedido
    antes = fonte.contagem["espn"]
    C.coletar(fonte, est, cli.agora + 2 * DIA, lambda: C.DEIXAR + 10, logs.append, erros)
    assert fonte.contagem["espn"] == antes
    # o resumo
    r = C.resumo(est, cli.agora)
    zero = [j for j in js.values() if j[4] == 0]
    assert r["jogos"] == len(js) and r["zero1t"] == len(zero) and r["oddRef"] == 1.9
    o15 = next(x for x in r["regras"] if x["id"] == "o15")
    assert o15["comZero"]["n"] == len(zero) and o15["comZero"]["k"] == sum(1 for j in zero if j[5] > 1.5)
    assert o15["todos"]["n"] == len(js) and o15["comZero"]["lo"] <= o15["comZero"]["taxa"] <= o15["comZero"]["hi"]
    assert [x["linha"] for x in r["regras"]] == [1.5, 2.5, 3.5]
    assert sum(x["jogos"] for x in r["ligas"]) == len(js) and r["times"] and len(r["ultimos"]) <= C.ULTIMOS
    assert all(t["jogos"] >= C.MIN_TIME for t in r["times"])
    assert set(r["ligasForaDaEspn"]) == {"Brasileirão B", "Copa do Brasil", "Sul-Americana", "Champions League", "Europa League"}
    # jogos velhos saem do estado
    C.coletar(fonte, est, cli.agora + (C.GUARDA_DIAS + 5) * DIA, lambda: 0, logs.append, erros)
    assert not est["jogos"]
    assert C.resumo({}, cli.agora)["jogos"] == 0


if __name__ == "__main__":
    teste_lances()
    teste_coleta()
    print("ok")
