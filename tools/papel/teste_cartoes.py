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
    # 22/11/2026: o árbitro principal (pelo cargo; sem cargo, o 1º da lista; assistente nunca)
    assert C.arbitro({"gameInfo": {"officials": [{"displayName": "X", "position": {"name": "Assistant Referee"}},
                                                  {"displayName": "Y", "position": {"name": "Referee"}}]}}) == "Y"
    assert C.arbitro({"gameInfo": {"officials": [{"fullName": "Z", "order": 1}]}}) == "Z"
    assert C.arbitro({"gameInfo": {"officials": [{"displayName": "W", "position": {"name": "VAR"}}]}}) is None
    assert C.arbitro({"gameInfo": {}}) is None and C.arbitro(None) is None
    # o filtro do prompt: só médias de antes; árbitro abaixo de 4,0 descarta; sem as médias dos dois times, não passa
    js = []
    for k in range(4):   # A e B em jogos de 6 cartões com o árbitro R; C em jogos de 2 com o árbitro S
        js.append((f"a{k}", [k, "eng", "A", f"x{k}", 3, 3, 3, 3, "R"]))
        js.append((f"b{k}", [k, "eng", f"y{k}", "B", 3, 3, 3, 3, "R"]))
        js.append((f"c{k}", [k, "eng", "C", f"z{k}", 1, 1, 1, 1, "S"]))
    js.append(("ab", [10, "eng", "A", "B", 0, 2, 1, 1, "R"]))
    js.append(("ac", [10, "eng", "A", "C", 0, 2, 1, 1, "R"]))
    js.append(("as", [10, "eng", "A", "B", 0, 2, 1, 1, "S"]))
    fp = C.filtro_do_prompt(js)
    assert fp["ab"] == (True, 6.0, 6.0) and fp["ab"][0]
    # depois do A × B (2 cartões): A 26/5, C 2 e o árbitro R 50/9 → (5,2 + 2 + 5,56) ÷ 3 = 4,25, passa
    assert fp["ac"][0] is True and abs(fp["ac"][2] - (26 / 5 + 2 + 50 / 9) / 3) < 1e-9
    assert fp["as"][0] is False and fp["as"][1] == 2.0          # árbitro de média 2: fora
    assert fp["a0"] == (False, None, None)                      # o 1º jogo não tem média nenhuma
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
        assert tuple(j[4:8]) == c and j[6] + j[7] == j[4] + j[5], (eid, j, c)
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
    # o árbitro e o filtro do prompt
    assert sum(1 for j in js.values() if len(j) > 8 and j[8]) > 0.8 * len(js)
    assert r["filtro"]["jogosComArbitro"] > 0 and r["arbitros"] and all(a["jogos"] >= C.MIN_MEDIA for a in r["arbitros"])
    assert 0 < o15["comFiltro"]["n"] <= o15["comZero"]["n"] and r["filtro"]["zeroComFiltro"] == o15["comFiltro"]["n"]
    assert any("formato do gameInfo" in x for x in logs)
    assert set(r["ligasForaDaEspn"]) == {"Brasileirão B", "Copa do Brasil", "Sul-Americana", "Champions League", "Europa League"}
    # jogos velhos saem do estado
    C.coletar(fonte, est, cli.agora + (C.GUARDA_DIAS + 5) * DIA, lambda: 0, logs.append, erros)
    assert not est["jogos"]
    assert C.resumo({}, cli.agora)["jogos"] == 0


def teste_arbitros_de_fora():
    """22/11/2026: o resumo da ESPN de verdade não traz o árbitro; as outras fontes preenchem."""
    # a chave do nome
    assert C.chave_arbitro("Anthony Taylor") == C.chave_arbitro("A Taylor") == C.chave_arbitro("A. Taylor, England") == "a taylor"
    assert C.chave_arbitro("Wilton Pereira Sampaio") == "w sampaio" and C.chave_arbitro("Raphael Claus Junior") == "r claus"
    assert C.chave_arbitro("") is None and C.chave_arbitro(None) is None
    # a planilha do football-data.co.uk
    csv_ = ("Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,Referee,HY,AY,HR,AR\n"
            "E0,16/08/2025,12:30,Liverpool,Bournemouth,4,2,A Taylor,2,3,0,0\n"
            "E0,17/08/2025,14:00,Arsenal,Man United,1,0,M Oliver,1,1,0,1\n"
            "E0,18/08/2025,20:00,Leeds,Everton,1,0,,2,2,0,0\n")
    ls = C.ler_planilha_arbitros(csv_)
    assert [(x[1], x[3], x[4]) for x in ls] == [("Liverpool", "A Taylor", 5), ("Arsenal", "M Oliver", 3)]
    # football-data.org e API-Football
    fd = {"matches": [{"utcDate": "2026-11-20T19:00:00Z", "homeTeam": {"name": "CR Flamengo"}, "awayTeam": {"name": "SE Palmeiras"},
                       "referees": [{"name": "Fulano Assistente", "type": "ASSISTANT_REFEREE_N1"}, {"name": "Wilton Pereira Sampaio", "type": "REFEREE"}]},
                      {"utcDate": "2026-11-20T21:00:00Z", "homeTeam": {"name": "X"}, "awayTeam": {"name": "Y"}, "referees": []}]}
    assert [(x[1], x[3]) for x in C.ler_fdorg(fd)] == [("CR Flamengo", "Wilton Pereira Sampaio")]
    af = {"errors": [], "response": [{"fixture": {"date": "2026-11-20T19:00:00+00:00", "referee": "Anthony Taylor, England"},
                                      "teams": {"home": {"name": "Liverpool"}, "away": {"name": "Everton"}}},
                                     {"fixture": {"timestamp": 1795300000, "referee": None}, "teams": {"home": {"name": "A"}, "away": {"name": "B"}}}]}
    assert [(x[1], x[3]) for x in C.ler_apif(af)] == [("Liverpool", "Anthony Taylor")]
    # casar: os mesmos times em ±36 h, sem sobrescrever quem já tem
    ms = C._ms("2026-11-20T19:00:00Z")
    est = {"jogos": {"1": [ms, "bra", "Flamengo", "Palmeiras", 0, 2, 1, 1, None],
                     "2": [ms, "eng", "Liverpool", "Everton", 1, 2, 2, 1, "Outro Nome"],
                     "3": [ms + 3 * DIA, "bra", "Flamengo", "Palmeiras", 0, 1, 0, 1, None],
                     "4": [ms, "eng", "Liverpool", "Everton", 1, 2, 2, 1]}}
    assert C.casar(est, C.ler_fdorg(fd)) == 1 and est["jogos"]["1"][8] == "Wilton Pereira Sampaio" and est["jogos"]["3"][8] is None
    assert C.casar(est, C.ler_apif(af)) == 1 and est["jogos"]["2"][8] == "Outro Nome" and est["jogos"]["4"][8] == "Anthony Taylor"
    # o filtro pelo histórico das planilhas: só os jogos de antes, a média dele no lugar da daqui
    hist = {"a taylor": [[ms - 30 * DIA, 6], [ms - 20 * DIA, 5], [ms - 10 * DIA, 4], [ms + DIA, 0]]}
    js = [(f"t{k}", [ms - (10 - k) * DIA, "eng", "Liverpool", "Everton", 1, 3, 2, 2, None]) for k in range(4)]
    js.append(("alvo", [ms, "eng", "Liverpool", "Everton", 0, 2, 1, 1, "Anthony Taylor"]))
    fp = C.filtro_do_prompt(js, hist)
    assert fp["alvo"][1] == 5.0 and fp["alvo"][0] is True
    assert C.filtro_do_prompt(js)["alvo"][1] is None   # sem histórico: o árbitro ainda não tem 3 jogos aqui


class _SemOficiais:
    """O placar de mentira com o resumo SEM a arbitragem (como a ESPN de verdade) e a API core respondendo."""

    def __init__(self, base, core="ref", apif="plano"):
        self.base, self.core, self.apif, self.urls, self.chaves = base, core, apif, [], []

    def __getattr__(self, k):
        return getattr(self.base, k)

    def json_url(self, url, tipo="espn"):
        self.urls.append(url)
        if "sports.core.api.espn.com" in url:
            if self.core == "nada":
                return {"count": 0, "items": []}
            if "/officials/1" in url:
                return {"displayName": "Raphael Claus", "position": {"name": "Referee"}, "order": 1}
            return {"count": 2, "items": [{"$ref": url.replace("https://", "http://") + "/1"}, {"$ref": url + "/2"}]}
        r = self.base.json_url(url, tipo)
        if "summary" in url:
            r = dict(r)
            r.pop("gameInfo", None)
        return r

    def json_chave(self, url, tipo, cab, chave):
        self.chaves.append((tipo, cab, chave, url))
        if tipo == "fdorg":
            return {"matches": []}
        if self.apif == "plano":
            return {"errors": {"plan": "Free plans do not have access to this date, try from 2026-11-21 to 2026-11-23."}, "response": []}
        if self.apif == "chave":
            return {"errors": {"token": "Error/Missing application key."}, "response": []}
        return {"errors": [], "response": []}


def teste_arbitros_na_coleta():
    cli = T.Cli()
    base = cli if hasattr(cli, "oddspapi") else falso_apostas.Avulsa(cli)
    # a API core traz (pelo $ref): o árbitro entra no jogo
    f = _SemOficiais(base)
    est, erros, logs = {}, [], []
    for k in range(3):
        C.coletar(f, est, cli.agora + k * 6 * HORA, lambda: 3000, logs.append, erros)
    assert not erros, erros[:3]
    com = [j for j in est["jogos"].values() if j[8]]
    assert com and all(j[8] == "Raphael Claus" for j in com) and len(com) == len(est["jogos"])
    assert any("formato dos oficiais" in x for x in logs) and est["arb"]["fontes"]["espnCore"]["achou"] == len(com)
    assert any("/officials/1" in u and u.startswith("https://") for u in f.urls)
    # a API core sem ninguém: para depois de 12 jogos seguidos, com o aviso
    f2 = _SemOficiais(base, core="nada")
    est2, logs2 = {}, []
    for k in range(4):
        C.coletar(f2, est2, cli.agora + k * 6 * HORA, lambda: 3000, logs2.append, [])
    F = est2["arb"]["fontes"]["espnCore"]
    assert F["achou"] == 0 and F["pausa"] > cli.agora and any("para por 14 dias" in x for x in logs2)
    assert sum(1 for u in f2.urls if "core.api" in u) == C.CORE_DESISTE
    # as chaves: pelo cabeçalho, nunca no log; a API-Football recusada pelo plano para 7 dias
    env = {"FOOTBALLDATA_KEY": "fd-segredo", "APIFOOTBALL_KEY": "af-segredo"}
    f3 = _SemOficiais(base, core="nada")
    est3, logs3, err3 = {}, [], []
    for k in range(4):
        C.coletar(f3, est3, cli.agora + k * 6 * HORA, lambda: 3000, logs3.append, err3)
    C.completar_arbitros(f3, est3, cli.agora, lambda: 3000, logs3.append, err3, env)
    tipos = {t for t, *_ in f3.chaves}
    assert tipos == {"fdorg", "apif"}, tipos
    assert all((t, c) in (("fdorg", "X-Auth-Token"), ("apif", "x-apisports-key")) for t, c, *_ in f3.chaves)
    assert all("segredo" not in u for *_x, u in f3.chaves) and not any("segredo" in x for x in logs3 + err3)
    # a API-Football: só ontem e hoje (o plano grátis); a data fora do plano não para a fonte
    dias_af = {u.split("date=")[1][:10] for t, _c, _k, u in f3.chaves if t == "apif"}
    import datetime as dt
    hoje_d = dt.datetime.fromtimestamp(cli.agora / 1000, dt.timezone.utc).date()
    assert dias_af and dias_af <= {hoje_d.isoformat(), (hoje_d - dt.timedelta(days=1)).isoformat()}, dias_af
    assert not est3["arb"]["fontes"]["apif"].get("pausa") and any("não abre" in x for x in logs3)
    n = len(f3.chaves)
    C.completar_arbitros(f3, est3, cli.agora + HORA, lambda: 3000, logs3.append, err3, env)
    assert any(t == "apif" for t, *_ in f3.chaves[n:])               # continua pedindo ontem e hoje
    # a chave recusada: para 1 dia
    f3.apif = "chave"
    C.completar_arbitros(f3, est3, cli.agora + 2 * HORA, lambda: 3000, logs3.append, err3, env)
    assert est3["arb"]["fontes"]["apif"]["pausa"] == cli.agora + 2 * HORA + DIA and any("tenta de novo amanhã" in x for x in logs3)
    m = len(f3.chaves)
    C.completar_arbitros(f3, est3, cli.agora + 3 * HORA, lambda: 3000, logs3.append, err3, env)
    assert not any(t == "apif" for t, *_ in f3.chaves[m:])
    # os dias velhos já pedidos não voltam (os 2 últimos, sim: o grátis chega com atraso)
    limite = (dt.datetime.fromtimestamp(cli.agora / 1000, dt.timezone.utc) - dt.timedelta(days=2)).date().isoformat()
    de = [u.split("dateFrom=")[1][:10] for t, _c, _k, u in f3.chaves[n:] if t == "fdorg"]
    assert all(d >= limite for d in de), (de, limite)
    r = C.resumo(est3, cli.agora)
    assert set(r["filtro"]["fontes"]) >= {"planilha", "fdorg", "apif", "espnCore"}
    # sem as chaves: nada de pedido com chave
    f4 = _SemOficiais(base, core="nada")
    C.completar_arbitros(f4, {"jogos": dict(est3["jogos"])}, cli.agora, lambda: 3000, [].append, [], {})
    assert not f4.chaves


if __name__ == "__main__":
    teste_lances()
    teste_coleta()
    teste_arbitros_de_fora()
    teste_arbitros_na_coleta()
    print("ok")
