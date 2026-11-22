"""Testes das apostas de valor no papel (sem rede). Uso: python3 tools/papel/teste_apostas.py"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)  # antes do mercado: os dois têm um falso.py

import apostas as A  # noqa: E402
import falso  # noqa: E402
import falso_apostas as FA  # noqa: E402
import odds  # noqa: E402
import papel  # noqa: E402
from teste_papel import conferir_forma  # noqa: E402

HORA, DIA = falso.HORA, falso.DIA


# O cliente falso das formas já traz as fontes das apostas (falso_apostas entre os mixins do falso.py)
Cli = falso.ClientePapelFalso
assert issubclass(Cli, FA.Falso)


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


# ------------------------------------------------------------------------------------------- contas à mão
def teste_contas():
    # margem pelo método da potência: (1/o)^k com o MESMO k nas três, somando 1
    p = A.sem_margem([2.0, 3.5, 4.0])
    q = [1 / 2.0, 1 / 3.5, 1 / 4.0]
    assert perto(sum(p), 1, 1e-9)
    ks = [math.log(a) / math.log(b) for a, b in zip(p, q)]
    assert all(perto(k, 1.0346367835791652, 1e-6) for k in ks), ks
    assert perto(p[0], 0.48813876, 1e-6) and perto(p[1], 0.27358179, 1e-6) and perto(p[2], 0.23827945, 1e-6)
    # tira mais margem do azarão que a divisão proporcional (0,4828 / 0,2759 / 0,2414)
    prop = [x / sum(q) for x in q]
    assert p[0] > prop[0] and p[2] < prop[2]
    assert A.sem_margem([1.9, 1.9]) == [0.5, 0.5] or all(perto(x, 0.5) for x in A.sem_margem([1.9, 1.9]))
    assert A.sem_margem([2.0, None, 3.0]) is None and A.sem_margem([1.0, 2.0]) is None
    # valor: 2,10 com justa 1,95 → 7,69%
    assert perto(A.valor(2.10, 1 / 1.95), 0.0769230769)
    # Kelly: (2,5 × 0,45 − 1) ÷ 1,5 = 8,33%; ¼ = 2,08% → teto de 2%
    assert perto(A.kelly(2.5, 0.45), 1 / 12) and A.kelly(2.0, 0.4) == 0
    # aposta grátis sem devolução: 5 × 0,25 × (4 − 1) = 3,75; numa odd justa, 5 × (1 − p)
    assert perto(A.ev_gratis(5, 4.0, 0.25), 3.75)
    assert perto(A.ev_gratis(5, 5.0, 0.2), 4.0) and perto(A.ev_gratis(5, 2.0, 0.5), 2.5)
    # CLV: 2,10 contra fechamento justo de 50% → +5%
    assert perto(A.clv(2.10, 0.5), 0.05) and A.clv(1.80, 0.5) < 0
    # liquidação
    assert A.ganhou("1x2", 0, [2, 1]) and A.ganhou("1x2", 1, [1, 1]) and A.ganhou("1x2", 2, [0, 3])
    assert A.ganhou("ou", 0, [2, 1]) and A.ganhou("ou", 1, [1, 1]) and not A.ganhou("ou", 0, [2, 0])
    # recortes (21/11/2026): por seleção, faixa de odd e campeonato, e o acerto que empata (média de 1 ÷ odd)
    c = A.Conta(next(x for x in A.VERSOES if x[0] == "valor3"), 0)
    for o, s_, l, pl in ((2.0, 0, "eng", [2, 0]), (4.0, 2, "eng", [2, 0]), (1.8, 1, "esp", [1, 1])):
        ap = {"j": "x", "jogo": "A × B", "l": l, "i": 0, "mk": "ou" if s_ == 1 else "1x2", "s": s_, "sel": "", "o": o,
              "p": 0.5, "v": 0, "st": 10.0, "c": "Bet365", "g": False, "clv": 0.02}
        c.abrir(ap)
        c.liquidar(ap, pl, HORA)
    x = c.extra()
    assert perto(x["acertoEmpate"], (1 / 2.0 + 1 / 4.0 + 1 / 1.8) / 3, 1e-4) and x["apostas"] == 3
    r = x["recortes"]
    assert [y["k"] for y in r["faixa"]] == ["1,50 a 1,99", "2,00 a 2,99", "3,00 ou mais"]
    assert {y["nome"] for y in r["selecao"]} == {"Vitória do mandante", "Vitória do visitante", "Menos de 2,5 gols"}
    eng = next(y for y in r["liga"] if y["k"] == "eng")
    assert eng["n"] == 2 and eng["acerto"] == 0.5 and eng["resultado"] == 0.0 and eng["clv"] == 0.02
    assert A.Conta(next(v for v in A.VERSOES if v[0] == "valor3"), 0, c.para_json()).recortes() == c.recortes()
    # textos
    assert A.reais(10.5, True) == "+R$ 10,50" and A.reais(-1234.5, True) == "−R$ 1.234,50"


def _jogo(o, p, pf=None, ou=None):
    j = {"id": "t1", "liga": "bra", "casa": "Flamengo", "fora": "Vasco", "inicio": falso.T0, "mk": {
        "1x2": {"o": o, "p": p, "pf": pf}}, "soft": "Betano"}
    if ou:
        j["mk"]["ou"] = ou
    return j


def teste_versoes():
    cfg = {c[0]: c for c in A.VERSOES}
    # valor da casa: 2,2 × 0,5 − 1 = 10%; empate 3,4 × 0,27 − 1 = −8,2%; fora 3,6 × 0,23 − 1 = −17,2%
    j = _jogo([2.2, 3.4, 3.6], [0.5, 0.27, 0.23], pf=[0.52, 0.26, 0.22])
    t = falso.T0 + 3 * HORA
    for vid, n in (("valor3", 1), ("valor5", 1), ("valor8", 1), ("favoritos", 1), ("azaroes", 0), ("semfiltro", 1), ("kelly", 1)):
        c = A.Conta(cfg[vid], falso.T0)
        aps = c.decidir(j)
        assert len(aps) == n, (vid, aps)
        for ap in aps:
            assert ap["s"] == 0 and ap["sel"] == "Flamengo vence" and perto(ap["v"], 0.10)
            assert perto(ap["clv"], 2.2 * 0.52 - 1, 1e-4)  # 14,4% acima do fechamento
            c.abrir(ap)
            assert perto(c.patrimonio(), 1000)
            res = c.liquidar(ap, [2, 1], t)
            st = 20.0 if vid == "kelly" else 10.0  # ¼ Kelly = 2,08% → teto de 2%
            assert perto(ap["st"], st) and perto(res, st * 1.2) and perto(c.caixa, 1000 + st * 1.2)
    # perdendo: a banca cai o valor apostado e a sequência de derrotas conta
    c = A.Conta(cfg["valor3"], falso.T0)
    for _ in range(3):
        ap = c.decidir(j)[0]
        c.abrir(ap)
        c.liquidar(ap, [0, 1], t)
    x = c.extra()
    assert perto(c.caixa, 970) and x["piorSequencia"] == 3 and x["acerto"] == 0 and perto(x["roi"], -1)
    assert perto(x["oddMedia"], 2.2) and perto(x["clvMedio"], 0.144, 1e-3) and x["clvPositivo"] == 1
    assert x["fonteSoft"] == "Betano"
    # Kelly menor que o teto: 2,0 × 0,52 → 4% × ¼ = 1% de 1.000
    c = A.Conta(cfg["kelly"], falso.T0)
    assert perto(c.decidir(_jogo([2.0, 3.6, 4.2], [0.52, 0.25, 0.23]))[0]["st"], 10.0)
    # uma aposta por mercado, a de maior valor; gols também
    ou = {"o": [2.1, 1.8], "p": [0.52, 0.48], "pf": None}  # mais: 9,2%; menos: −13,6%
    c = A.Conta(cfg["valor3"], falso.T0)
    aps = c.decidir(_jogo([2.2, 3.4, 3.6], [0.5, 0.27, 0.23], ou=ou))
    assert [a["mk"] for a in aps] == ["1x2", "ou"] and aps[1]["sel"] == "mais de 2,5 gols" and aps[1]["clv"] is None
    # fora da faixa de odds: nada
    assert not A.Conta(cfg["valor3"], falso.T0).decidir(_jogo([4.5, 3.4, 1.8], [0.25, 0.27, 0.48]))
    # aposta grátis: a de maior 5 × p × (odd − 1) entre 2,00 e 6,00: empate (3,24) > casa (3,00) > fora (2,99)
    e, jj, mk, i = A.melhor_gratis([j])
    assert (mk, i) == ("1x2", 1) and perto(e, 5 * 0.27 * 2.4)
    g = A.Conta(cfg["gratis"], falso.T0)
    ap = A.nova_aposta(jj, mk, i, A.GRATIS_VALOR, gratis=True)
    g.abrir(ap)
    assert perto(g.patrimonio(), 1000)  # o valor da aposta grátis não sai da banca
    assert perto(g.liquidar(ap, [1, 1], t), 12.0) and perto(g.caixa, 1012)
    ap = A.nova_aposta(jj, mk, i, A.GRATIS_VALOR, gratis=True)
    g.abrir(ap)
    assert g.liquidar(ap, [2, 0], t) == 0 and perto(g.caixa, 1012)
    x = g.extra()
    assert x["ganhoGratis"] == 12.0 and x["apostas"] == 2 and x["acerto"] == 0.5
    # anulada: o valor volta
    c = A.Conta(cfg["valor3"], falso.T0)
    ap = c.decidir(j)[0]
    c.abrir(ap)
    c.liquidar(ap, None, t, anular=True)
    assert perto(c.caixa, 1000) and c.extra()["anuladas"] == 1 and c.extra()["apostas"] == 0


# ------------------------------------------------------------------------------------------- planilhas
def teste_planilhas():
    # latin-1 e o BOM do UTF-8
    assert odds.decodificar("Grêmio".encode("latin-1")) == "Grêmio"
    assert odds.decodificar("﻿Div,Grêmio".encode("utf-8")) == "Div,Grêmio"
    # horário do Reino Unido: julho (verão) 15:00 → 14:00 UTC; janeiro 15:00 → 15:00 UTC
    import datetime as dt
    assert A._hora_uk(dt.date(2026, 7, 1), "15:00") == int(dt.datetime(2026, 7, 1, 14, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert A._hora_uk(dt.date(2026, 1, 10), "15:00") == int(dt.datetime(2026, 1, 10, 15, tzinfo=dt.timezone.utc).timestamp() * 1000)
    # sem as colunas da Pinnacle: a justa vem da média das casas (e o fechamento também)
    csv1 = ("﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,B365H,B365D,B365A,AvgH,AvgD,AvgA,AvgCH,AvgCD,AvgCA\n"
            "F1,10/01/26,20:00,Lyon,Nice,2,0,2.30,3.40,3.10,2.10,3.30,3.40,2.05,3.40,3.60\n"
            "F1,11/01/26,,Lens,Brest,,,2.0,3.0,4.0,2,3,4,2,3,4\n")
    js = A.ler_planilha(csv1, "fra")
    assert len(js) == 1, js  # a linha sem placar fica de fora
    j = js[0]
    assert j["justa"] == A.MEDIA and j["soft"] == A.BET365 and j["fechJusta"] == A.MEDIA and j["placar"] == [2, 0]
    assert j["mk"]["1x2"]["o"] == [2.3, 3.4, 3.1] and perto(sum(j["mk"]["1x2"]["p"]), 1, 1e-9) and "ou" not in j["mk"]
    # planilha "nova" (Brasil): só fechamento → a casa é a média e o CLV não é medido
    csv2 = ("Country,League,Season,Date,Time,Home,Away,HG,AG,Res,PSCH,PSCD,PSCA,MaxCH,MaxCD,MaxCA,AvgCH,AvgCD,AvgCA\n"
            "Brazil,Serie A,2026,05/04/2026,20:00,Grêmio,São Paulo,1,1,D,2.40,3.20,3.10,2.6,3.4,3.3,2.35,3.15,3.05\n")
    j = A.ler_planilha(csv2, "bra")[0]
    assert j["casa"] == "Grêmio" and j["soft"] == A.MEDIA and j["justa"] == A.PINNACLE and j["mk"]["1x2"]["pf"] is None
    assert not j["fech"]
    # o motor no passado com essa planilha não quebra e começa em 1.000
    jf = A.ler_planilha(csv1, "fra")
    res = A.simular_passado(jf, jf[0]["inicio"] - DIA, jf[0]["inicio"] + 3 * DIA)
    assert all(r["serie"][0][1] == 1000 and len(r["serie"]) == 5 for r in res.values())
    # Bet365 2,30 contra a justa da média (2,10 sem margem = 45,2%): valor de 3,9% → só o valor 3% aposta (e ganha)
    assert res["valor3"]["serie"][-1][1] == 1013.0 and res["valor5"]["serie"][-1][1] == 1000.0
    assert res["valor8"]["serie"][-1][1] == 1000.0 and res["valor3"]["extra"]["clvMedio"] is not None


# ------------------------------------------------------------------------------------------- OddsPapi
def teste_leitura_oddspapi():
    fut = FA.Futebol()
    import datetime as dt
    jw = fut.do_dia("eng", dt.date(2026, 10, 24))[0]
    agora = jw["inicio"] + 4 * HORA
    r = {"fixtureId": jw["id"], "bookmakers": {"pinnacle": FA.historico_livro(jw, "pinnacle", agora),
                                                "betano.bet.br": {}, "betano": FA.historico_livro(jw, "betano", agora)}}
    pin = A.mercados(A._no_da_casa(r, "pinnacle"))
    so = A.mercados(A._no_da_casa(r, "betano"))
    # o mais/menos de 2,5 gols vem pelo id 1010, sem o nome do mercado (como na resposta de verdade)
    assert set(pin) == {"1x2", "ou"} and not A.mercados(A._no_da_casa(r, "betano.bet.br"))
    assert len(pin["1x2"][0]) == len(FA.MOMENTOS)
    fx = {"id": jw["id"], "l": "eng", "c": jw["casa"], "f": jw["fora"], "i": jw["inicio"]}
    j = A.jogo_vivo(fx, pin, so, "Betano (internacional)")
    # 6 h antes vale o preço publicado 8 h antes; o fechamento é o de 15 min antes
    o8, of = FA.odds_de(jw, "pinnacle", 8), FA.odds_de(jw, "pinnacle", 0.25)
    assert j["mk"]["1x2"]["t"] == jw["inicio"] - 6 * HORA
    assert all(perto(a, b, 1e-9) for a, b in zip(j["mk"]["1x2"]["p"], A.sem_margem(o8["1x2"])))
    assert all(perto(a, b, 1e-9) for a, b in zip(j["mk"]["1x2"]["pf"], A.sem_margem(of["1x2"])))
    assert j["mk"]["1x2"]["o"] == FA.odds_de(jw, "betano", 8)["1x2"]
    # sem preço 6 h antes (abriu tarde): o último até 1 h antes
    pin2 = {"1x2": [[(t, p) for t, p in h if t >= jw["inicio"] - 5 * HORA] for h in pin["1x2"]]}
    so2 = {"1x2": [[(t, p) for t, p in h if t >= jw["inicio"] - 5 * HORA] for h in so["1x2"]]}
    assert A.jogo_vivo(fx, pin2, so2, "x")["mk"]["1x2"]["t"] == jw["inicio"] - HORA
    # placares em vários formatos
    assert A._placar({"scores": {"fullTime": {"participant1": 2, "participant2": 1}}}) == [2, 1]
    assert A._placar({"score": "3-0"}) == [3, 0] and A._placar({"homeScore": "1", "awayScore": 1}) == [1, 1]
    assert A._placar({"statusId": 0}) is None
    # instantes
    assert A._ms("2026-11-02T19:00:00.000Z") == A._ms(1793646000) == 1793646000000
    # campeonatos
    assert A.bate_torneio("bra", "Brasileiro Serie A", "Brazil") and not A.bate_torneio("bra", "Brasileiro Serie B", "Brazil")
    assert not A.bate_torneio("ita", "Serie A", "Ecuador") and A.bate_torneio("ita", "Serie A", "Italy")
    assert not A.bate_torneio("eng", "Premier League 2", "England") and not A.bate_torneio("ger", "2. Bundesliga", "Germany")
    assert A.bate_torneio("lib", "CONMEBOL Libertadores", "") and not A.bate_torneio("lib", "CONMEBOL Libertadores Femenina", "")
    # nomes dos times entre a OddsPapi e a ESPN
    assert A.mesmo_time("Man United", "Manchester United") and A.mesmo_time("Athletico-PR", "Athletico Paranaense")
    assert A.mesmo_time("Atlético-MG", "Atlético Mineiro") and A.mesmo_time("Vasco", "Vasco da Gama")
    assert not A.mesmo_time("Flamengo", "Fluminense") and not A.mesmo_time("Man City", "Manchester United")
    # a chave nunca aparece numa mensagem
    c = odds.Cliente(chave="ABC123")
    assert c._limpar("erro em https://x/?apiKey=ABC123") == "erro em https://x/?apiKey=***"
    try:
        odds.Cliente().oddspapi("/sports")
        raise AssertionError("sem chave devia falhar")
    except odds.Erro as e:
        assert "chave" in str(e)


def teste_orcamento():
    V = {"mes": "2026-11", "usados": 0}
    agora = A._ms("2026-11-03T12:00:00Z")
    o = A.Orcamento(None, V, agora)
    assert o.dias_restantes() == 28 and o.livre() == 225
    # 225 − 6 ligas × 8 listas de jogos = 177 ÷ 28 dias = 6 por dia
    assert o.cota_do_dia(6) == 6
    V["usados"] = 220
    assert o.cota_do_dia(6) == 0
    V2 = {"mes": "2026-10", "usados": 200}
    A.Orcamento(None, V2, agora)
    assert V2 == {"mes": "2026-11", "usados": 0}  # mês novo: zera


# ------------------------------------------------------------------------------------------- rodadas
def _forma(pasta):
    with open(os.path.join(pasta, "apostas.json")) as f:
        return json.load(f)


def _estado(pasta):
    with open(os.path.join(pasta, "estado.json")) as f:
        return json.load(f)["formas"]["apostas"]


def rodar(cli, pasta):
    return papel.rodada(cli, pasta, cli.agora, formas=["apostas"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))


def teste_rodadas():
    pasta = tempfile.mkdtemp(prefix="apostas-")
    try:
        cli = Cli()
        cli.chave = "SEGREDO-NAO-PODE-SAIR-123"
        t0 = cli.agora
        for k in range(29):  # a cada 6 h por 7 dias
            cli.agora = t0 + k * 6 * HORA
            ind = rodar(cli, pasta)
            assert ind["formas"]["apostas"]["ok"], ind["formas"]["apostas"]
            if k == 0:
                assert cli.contagem["csv"] == 16, cli.contagem  # 5 ligas × 3 temporadas + o Brasil
            d = _forma(pasta)
            conferir_forma(d, "apostas")
        assert cli.contagem["csv"] == 32, cli.contagem  # refeito uma vez, 7 dias depois
        assert d["cartoes"]["jogos"] > 0 and not [e for e in d.get("erros", []) if "cartões" in str(e)], d.get("erros")
        # um buraco de 30 h: a rodada alcança
        cli.agora += 30 * HORA
        ind = rodar(cli, pasta)
        assert ind["formas"]["apostas"]["ok"]
        d = _forma(pasta)
        conferir_forma(d, "apostas")
        est = _estado(pasta)
        V = est["vivo"]
        presos = [f for f in V["fx"].values() if f["st"] == "novo" and f["i"] + A.FIM_JOGO <= cli.agora]
        assert not presos, presos[:2]
        # formato
        assert d["padrao"] == "valor3" and d["nome"] == "Apostas de valor"
        ids = [v["id"] for v in d["versoes"]]
        assert ids == ["valor3", "valor5", "valor8", "kelly", "favoritos", "azaroes", "gratis", "semfiltro", "bdm", "bdmG15", "bdmG5",
                       "bdmFav", "bdmH15", "bdmConv", "bdmConf"]
        riscos = {v["id"]: v["risco"] for v in d["versoes"]}
        assert riscos["azaroes"] == riscos["kelly"] == "alto" and riscos["gratis"] == "baixo" and riscos["valor3"] == "médio"
        assert {v["grupo"] for v in d["versoes"]} == {"Valor", "Referência", "Aposta grátis", "Seguir palpites"}
        vs = {v["id"]: v for v in d["versoes"]}
        bdm = vs["bdm"]
        assert bdm["historico"] is None and bdm["soAoVivo"] and bdm["aoVivo"]["extra"]["palpitesVistos"] > 0
        for k in ("bdmG15", "bdmG5", "bdmFav", "bdmH15", "bdmConv", "bdmConf"):   # 21 e 22/11/2026: o gatilho da odd mínima (só ao vivo, como a bdm)
            assert vs[k]["historico"] is None and vs[k]["soAoVivo"] and vs[k]["aoVivo"]["serie"][0][1] == 1000.0, k
        for v in [v for v in d["versoes"] if v["id"] not in A.BDM_CONTAS]:
            for nome in ("aoVivo", "historico"):
                c = v[nome]
                assert c and c["serie"][0][1] == 1000.0, (v["id"], nome)
                for k in ("apostas", "acerto", "roi", "oddMedia", "clvMedio", "clvPositivo", "piorSequencia", "fonteSoft"):
                    assert k in c["extra"], (v["id"], nome, k)
            h = v["historico"]
            assert h["aproximado"] is False and "Bet365" in h["nota"] and h["de"] < h["ate"]
            # 21/11/2026: o acerto que empata e os recortes (cada recorte soma as apostas da conta)
            hx = h["extra"]
            if v["id"] != "gratis" and hx["apostas"]:
                assert 0 < hx["acertoEmpate"] < 1 and set(hx["recortes"]) == {"selecao", "faixa", "liga"}, v["id"]
                for tipo, linhas in hx["recortes"].items():
                    assert sum(x["n"] for x in linhas) == hx["apostas"], (v["id"], tipo)
                fx = [x["k"] for x in hx["recortes"]["faixa"]]
                assert fx == [n for _l, n in A.FAIXAS_ODD if n in fx], fx
            dias = [x for x, _ in h["serie"]]
            assert len(dias) == len(set(dias)) and dias == sorted(dias)
            assert len(dias) > 400  # um ponto por dia desde 2024
        hv = {v["id"]: v["historico"]["extra"] for v in d["versoes"] if v["historico"]}
        assert hv["valor3"]["apostas"] >= hv["valor5"]["apostas"] >= hv["valor8"]["apostas"] > 0
        assert hv["semfiltro"]["clvMedio"] < 0 < hv["valor3"]["clvMedio"]
        assert hv["valor3"]["fonteSoft"] == "Bet365 (no lugar da Betano)" and "ganhoGratis" in hv["gratis"]
        assert hv["gratis"]["apostas"] > 50 and hv["gratis"]["oddMedia"] >= 2
        # ao vivo: houve apostas liquidadas, a Betano do Brasil vazia foi trocada pela internacional
        vv = {v["id"]: v["aoVivo"] for v in d["versoes"]}
        assert vv["semfiltro"]["extra"]["apostas"] > 10 and vv["valor3"]["ops"] == vv["valor3"]["extra"]["apostas"]
        assert vv["valor3"]["extra"]["fonteSoft"] == "Betano (internacional)"
        assert vv["gratis"]["extra"]["apostas"] >= 1 and vv["gratis"]["piorQueda"] == 0
        assert "betano.bet.br" in d["config"]["softDescartadas"] and d["config"]["fonteSoft"].startswith("Betano (internacional)")
        assert any("betano.bet.br" in e["texto"] for e in d["eventos"])
        assert any(e["tipo"] == "resumo" and "CLV médio" in e["texto"] for e in d["eventos"])
        assert any(e["versao"] == "gratis" for e in d["eventos"])
        # no máximo 3 eventos de apostas da versão padrão por dia de jogo
        from collections import Counter
        por_dia = Counter(papel.dia_de(e["em"]) for e in d["eventos"] if e["versao"] == "valor3" and e["tipo"] in ("ganhou", "perdeu"))
        assert por_dia and max(por_dia.values()) <= 4  # um dia de jogo pode ser liquidado no dia seguinte
        # orçamento: o contado bate com o feito e não passa de 90%
        orc = d["config"]["orcamento"]
        assert orc["usados"] == cli.contagem["oddspapi"] <= 225 and orc["limite"] == 250
        assert d["config"]["pedidosRodada"].get("oddspapi", 0) >= 0
        # itens (apostas esperando o placar), se houver
        for it in d["itens"]:
            assert {"jogo", "liga", "inicio", "selecao", "odd", "justa", "valor", "casa", "versoes"} <= set(it)
        assert len(json.dumps(d)) < 400_000
        # a chave nunca foi gravada
        for nome in os.listdir(pasta):
            with open(os.path.join(pasta, nome), encoding="utf-8", errors="replace") as f:
                assert "SEGREDO-NAO-PODE-SAIR" not in f.read(), nome
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def teste_sem_chave_e_falhas():
    pasta = tempfile.mkdtemp(prefix="apostas-")
    try:
        # sem a chave: só o teste no passado
        cli = Cli()
        cli.chave = None
        ind = rodar(cli, pasta)
        assert ind["formas"]["apostas"]["ok"]
        d = _forma(pasta)
        conferir_forma(d, "apostas")
        assert all(v["aoVivo"] is None and (v["historico"] or v.get("soAoVivo")) for v in d["versoes"])
        assert d["config"]["aoVivo"] == "falta a chave gratuita da OddsPapi" and "OddsPapi" in d["avisos"][0]
        assert cli.contagem["oddspapi"] == 0 and d["itens"] == []
        # a chave chega depois: o ao vivo começa
        cli.chave = "x"
        cli.agora += 6 * HORA
        rodar(cli, pasta)
        d = _forma(pasta)
        assert all(v["aoVivo"] for v in d["versoes"]) and d["config"]["aoVivo"] == "ligado"
        # o limite do mês quase no fim: nenhum pedido à OddsPapi
        est = json.load(open(os.path.join(pasta, "estado.json")))
        est["formas"]["apostas"]["vivo"]["usados"] = 225
        papel.gravar_json(os.path.join(pasta, "estado.json"), est)
        antes = cli.contagem["oddspapi"]
        cli.agora += 6 * HORA
        assert rodar(cli, pasta)["formas"]["apostas"]["ok"]
        assert cli.contagem["oddspapi"] == antes
        # a OddsPapi falhando: a forma segue, com o erro anotado
        est = json.load(open(os.path.join(pasta, "estado.json")))
        est["formas"]["apostas"]["vivo"]["usados"] = 0
        papel.gravar_json(os.path.join(pasta, "estado.json"), est)
        cli.falhar.add("oddspapi")
        cli.agora += 4 * DIA
        ind = rodar(cli, pasta)
        assert ind["formas"]["apostas"]["ok"]
        d = _forma(pasta)
        assert any("OddsPapi" in e or "lista de jogos" in e for e in d["rodada"]["erros"]), d["rodada"]["erros"]
        cli.falhar.discard("oddspapi")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    # as planilhas falhando sem teste anterior: a forma fica ok: false, sem quebrar a rodada
    pasta = tempfile.mkdtemp(prefix="apostas-")
    try:
        cli = Cli()
        cli.falhar.add("csv")
        ind = rodar(cli, pasta)
        assert ind["formas"].get("apostas", {"ok": False})["ok"] is False
        assert not os.path.exists(os.path.join(pasta, "apostas.json"))
        cli.falhar.discard("csv")
        ind = rodar(cli, pasta)
        assert ind["formas"]["apostas"]["ok"]
        # com teste anterior, a falha das planilhas na semana seguinte não derruba a forma (fica o anterior)
        cli.falhar.add("csv")
        cli.agora += 8 * DIA
        ind = rodar(cli, pasta)
        assert ind["formas"]["apostas"]["ok"]
        d = _forma(pasta)
        assert any("teste no passado" in e for e in d["rodada"]["erros"]) and d["versoes"][0]["historico"]
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


class CliSemPinnacle(Cli):
    """A OddsPapi respondendo sem a Pinnacle (como se o formato fosse outro)."""

    def oddspapi(self, caminho, **p):
        r = FA.Falso.oddspapi(self, caminho, **p)
        if caminho == "/historical-odds":
            r["bookmakers"].pop("pinnacle", None)
        return r


class CliLib404(Cli):
    """A OddsPapi respondendo 404 na lista de jogos da Libertadores (sem jogos no período, como em 09/11/2026)."""

    def oddspapi(self, caminho, **p):
        if caminho == "/fixtures" and str(p.get("tournamentId")) == "384":
            self.contagem["oddspapi"] += 1
            raise odds.Erro("HTTP 404 em OddsPapi /fixtures", 404)
        return FA.Falso.oddspapi(self, caminho, **p)


def teste_lista_vazia_404():
    pasta = tempfile.mkdtemp(prefix="apostas-")
    try:
        cli = CliLib404()
        assert rodar(cli, pasta)["formas"]["apostas"]["ok"]
        d = _forma(pasta)
        assert not any("Libertadores" in e for e in d["rodada"]["erros"]), d["rodada"]["erros"]
        V = _estado(pasta)["vivo"]
        assert V["fxVazio"].get("lib") is True
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def teste_formato_estranho():
    pasta = tempfile.mkdtemp(prefix="apostas-")
    try:
        cli = CliSemPinnacle()
        t0 = cli.agora
        for k in range(16):
            cli.agora = t0 + k * 6 * HORA
            assert rodar(cli, pasta)["formas"]["apostas"]["ok"]
        V = _estado(pasta)["vivo"]
        d = _forma(pasta)
        assert V["pausaAte"] > cli.agora and any("pausou" in e["texto"] for e in d["eventos"])
        gasto = cli.contagem["oddspapi"]
        cli.agora += 6 * HORA
        rodar(cli, pasta)
        assert cli.contagem["oddspapi"] == gasto  # pausado: não gasta o limite
        assert all(v["aoVivo"]["extra"]["apostas"] == 0 for v in _forma(pasta)["versoes"])
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


# ------------------------------------------------------------------------------------------- Seguir o BDM
def _pk(**k):
    base = {"id": "v1-1", "mandante": "Flamengo", "visitante": "Vasco", "competicao": "Brasileirão",
            "inicio": "2026-11-09T21:30:00-03:00", "mercado": "1x2", "linha": None, "selecao": "mandante",
            "oddCitada": 1.85, "fora": False, "motivo": None}
    base.update(k)
    return A.palpite_bdm(base, "2026-11-09", "v1")


def teste_bdm_palpites():
    pk = _pk()
    assert pk["i"] == A._ms("2026-11-10T00:30:00Z") and pk["dia"] == "2026-11-09" and pk["oc"] == 1.85
    assert A.precificavel(pk) == (True, None)
    assert A.texto_selecao(pk) == "Flamengo vence" and A.nome_mercado(pk) == "Resultado (1X2)"
    # só 1X2 e mais/menos de 2,5 gols são precificados; o resto fica fora com o mercado no motivo
    assert A.precificavel(_pk(mercado="ou", linha=2.5, selecao="mais"))[0]
    ok, m = A.precificavel(_pk(mercado="ou", linha=1.5, selecao="mais"))
    assert not ok and m == "mercado fora do teste: Mais/menos de 1,5 gols", m
    ok, m = A.precificavel(_pk(mercado="ah", linha=-1.5, selecao="visitante"))
    assert not ok and "Handicap asiático" in m
    assert A.texto_selecao(_pk(mercado="ah", linha=-1.5, selecao="visitante")) == "Vasco −1,5 (handicap)"
    assert A.precificavel(_pk(mercado="cartoes", linha=4.5, selecao="mais", fora=True, motivo="cartoes")) == (False, "cartões")
    assert A.precificavel(_pk(fora=True, motivo="ao_vivo")) == (False, "plano para o ao vivo")
    # campos estranhos: mercado desconhecido some, seleção inválida vira None, odd fora de 1,01–50 vira None
    assert _pk(mercado="gols do Pedro") is None
    assert _pk(selecao="talvez")["sel"] is None and _pk(oddCitada=80)["oc"] is None and _pk(oddCitada="1,9")["oc"] == 1.9
    assert _pk(inicio="2026-11-10")["i"] is None and _pk(inicio="2026-11-10")["dia"] == "2026-11-10"
    # o jogo: times em qualquer ordem, início ±3 h; sem hora, o dia (ou o seguinte, depois da meia-noite)
    fx = [{"id": "a", "c": "Vasco da Gama", "f": "CR Flamengo", "i": A._ms("2026-11-10T00:00:00Z")},
          {"id": "b", "c": "Flamengo", "f": "Vasco", "i": A._ms("2026-11-20T00:00:00Z")}]
    f, inv = A.achar_jogo(pk, fx)
    assert f["id"] == "a" and inv
    assert A.indice_bdm(pk, inv) == 2 and A.indice_bdm(_pk(selecao="empate"), True) == 1
    assert A.indice_bdm(_pk(mercado="ou", linha=2.5, selecao="menos"), True) == 1
    assert A.achar_jogo(_pk(inicio="2026-11-09"), fx)[0]["id"] == "a"  # 21h de 09/11 em Brasília
    assert A.achar_jogo(_pk(inicio="2026-11-12"), fx)[0] is None
    # a odd: o 1º momento a partir de quando o palpite foi visto, antes do início
    hs = [(100, 2.0), (200, 2.1), (300, 2.2)]
    ph = [[(50, 1.9)], [(50, 3.5)], [(250, 4.0)]]
    assert A.preco_bdm(hs, ph, 150, 400) == (250, 2.1, [1.9, 3.5, 4.0])
    assert A.preco_bdm(hs, ph, 150, 240) is None


def teste_bdm_arquivos():
    pasta = tempfile.mkdtemp(prefix="bdm-")
    try:
        for d, conteudo in (("2026-11-09", {"versao": 1, "data": "2026-11-09", "video": {"id": "x"}, "palpites": []}),
                            ("2026-10-01", {"versao": 1, "data": "2026-10-01", "palpites": []}),
                            ("2026-11-08", "não é json")):
            with open(os.path.join(pasta, d + ".json"), "w") as f:
                f.write(conteudo if isinstance(conteudo, str) else json.dumps(conteudo))
        with open(os.path.join(pasta, "LEIA-ME.md"), "w") as f:
            f.write("x")
        lidos = A.ler_bdm(pasta, A._ms("2026-11-09T15:00:00Z"))
        assert [x["data"] for x in lidos] == ["2026-11-09"], lidos  # o velho e o quebrado ficam de fora
        assert A.ler_bdm(os.path.join(pasta, "nao-existe")) == []
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def teste_bdm_rodadas():
    """A conta Seguir o BDM nas rodadas: cada palpite vira aposta, fica fora (com o motivo) ou espera; a odd é a da
    hora em que a rodada viu o palpite, sem pedido a mais à OddsPapi."""
    pasta = tempfile.mkdtemp(prefix="apostas-")
    try:
        cli = Cli()
        t0 = cli.agora
        for k in range(40):
            cli.agora = t0 + k * 6 * HORA
            rodar(cli, pasta)
        d = _forma(pasta)
        V = _estado(pasta)["vivo"]
        v = next(x for x in d["versoes"] if x["id"] == "bdm")
        e = v["aoVivo"]["extra"]
        assert v["nome"] == "Seguir o Theo" and v["historico"] is None and v["soAoVivo"]
        assert e["palpitesVistos"] > 20 and 0 < e["noTeste"] < e["palpitesVistos"]
        assert e["cobertura"] == round(e["noTeste"] / e["palpitesVistos"], 4)
        assert e["noTeste"] + e["esperando"] + sum(f["n"] for f in e["fora"]) >= e["palpitesVistos"]
        motivos = {f["motivo"] for f in e["fora"]}
        assert {"plano para o ao vivo", "mercado fora do teste: Ambas marcam",
                "jogo fora dos campeonatos acompanhados"} <= motivos, motivos
        assert e["apostas"] > 5 and e["acerto"] is not None and e["clvMedio"] is not None and e["piorSequencia"] >= 1
        assert e["oddCitadaMedia"] and e["oddPegaMedia"] and 0 < len(e["ultimos"]) <= A.BDM_ULTIMOS
        # cada aposta: R$ 20, a odd da casa no 1º preço a partir da hora em que foi visto, antes do início
        B = V["bdm"]
        feitas = [p for p in B["p"].values() if p.get("o")]
        assert feitas
        for p in feitas:
            assert p["visto"] < p["i"]
        assert all(x["st"] == 20.0 for x in V["contas"]["bdm"]["abertas"])
        assert not any(p["st"] == "esperando" and (p["i"] or 0) + 2 * DIA < cli.agora for p in B["p"].values())
        # palpite com os times trocados pela IA virou a aposta certa (o lado do time, não a posição)
        trocados = [p for p in feitas if p.get("inv")]
        assert trocados
        for p in trocados:
            lado = p["v"] if p["sel"] == "visitante" else p["m"]
            f = V["fx"].get(p["fx"])
            if f:
                i = A.indice_bdm(p, True)
                assert A.mesmo_time(lado, f["c"] if i == 0 else f["f"]), (p, f)
        assert any(ev["versao"] == "bdm" and "odd citada" in ev["texto"] for ev in d["eventos"])
        # 21/11/2026: o gatilho da odd mínima. Cada aposta das contas com gatilho tem a odd >= a justa × (1 + g), é
        # da mesma lista de palpites, e a de 15% aposta no máximo o que a de 5% aposta
        for k, g in (("bdmG15", 0.15), ("bdmG5", 0.05)):
            for ap in V["contas"][k]["abertas"] + [a for a in V["contas"][k].get("fechadas", [])]:
                assert ap["o"] >= (1 / ap["p"]) * (1 + g) - 1e-6 and ap["pk"] in B["p"], (k, ap)
        n15 = sum(1 for p in B["p"].values() if (p.get("gat") or {}).get("bdmG15") == "apostado")
        n5 = sum(1 for p in B["p"].values() if (p.get("gat") or {}).get("bdmG5") == "apostado")
        assert n15 <= n5 and any((p.get("gat") or {}).get("bdmG15") for p in feitas), (n15, n5)
        assert A.preco_gatilho([(1, 2.0), (5, 2.4)], [[(1, 1.9)], [(1, 3.6)], [(1, 4.4)]], 1, 9, 0, 0.15)[0] == 5
        assert A.preco_gatilho([(1, 2.0)], [[(1, 1.9)], [(1, 3.6)], [(1, 4.4)]], 1, 9, 0, 0.15) is None
        # 21/11/2026: o controle (uma aposta por jogo com palpite, no favorito), o histórico (odd >= a justa do
        # histórico × 1,15) e a convergência (só com o histórico a favor, na mesma odd da bdm)
        fav = V["contas"]["bdmFav"]
        assert B["fav"] and fav["acc"]["n"] + len(fav["abertas"]) == sum(1 for v in B["fav"].values() if v == "apostado")
        assert {pk.get("fx") for pk in feitas} <= set(B["fav"]) | {None}
        for k in ("bdmH15", "bdmConv"):
            for pk in B["p"].values():
                m = (pk.get("gat") or {}).get(k)
                assert m is None or m in ("apostado", "sem histórico", "não chegou à odd mínima", "histórico não concorda",
                                          "histórico diz que a odd não paga", "sem saldo na conta"), (k, m)
                if m == "apostado":
                    assert pk.get("hist"), pk
                    if k == "bdmConv":
                        assert pk["hist"]["forte"] and pk["hist"]["p"] * pk["o"] >= 1 - 1e-9, pk
        for ap in V["contas"]["bdmH15"]["abertas"]:
            assert ap["o"] >= (1 / ap["ph"]) * 1.15 - 1e-6, ap
        vs = {x["id"]: x for x in d["versoes"]}
        assert vs["bdmFav"]["aoVivo"]["extra"]["jogos"] == len(B["fav"])
        assert vs["bdmH15"]["aoVivo"]["extra"]["comHistorico"] > 0
        assert any(s["motivo"] == "sem histórico" for s in vs["bdmConv"]["aoVivo"]["extra"]["situacoes"])
        # 22/11/2026: a dupla chance e o empate anula pelo 1X2 (aproximado), o empate devolve no empate anula, e a conta
        # pela confiança aposta R$ 30, 20 ou 10
        todas = V["contas"]["bdm"]["abertas"] + V["contas"]["bdmConf"]["abertas"]
        sint = [pk for pk in B["p"].values() if pk["mk"] in ("dupla", "dnb") and pk.get("o")]
        assert any(pk["mk"] == "dupla" for pk in sint) and any(pk["mk"] == "dnb" for pk in sint), len(sint)
        assert all(ap.get("aprox") for ap in todas if ap["mk"] in ("dupla", "dnb"))
        assert {ap["st"] for ap in V["contas"]["bdmConf"]["abertas"]} <= {30.0, 20.0, 10.0}
        assert any(ap.get("conf") == "alta" and ap["st"] == 30.0 for ap in V["contas"]["bdmConf"]["abertas"]) or \
            V["contas"]["bdmConf"]["acc"]["n"] > 0
        assert V["contas"]["bdm"]["acc"]["devolvidas"] > 0 and any(ev["tipo"] == "devolveu" for ev in d["eventos"])
        conf = vs["bdmConf"]["aoVivo"]["extra"]["recortes"]["confianca"]
        assert [x["k"] for x in conf] == [k for k in A.CONFIANCA if k in {x["k"] for x in conf}] and len(conf) >= 2
        assert {"Mandante ou empate", "Empate ou visitante", "Mandante (empate anula)", "Visitante (empate anula)"} & \
            {x["nome"] for x in vs["bdm"]["aoVivo"]["extra"]["recortes"]["selecao"]}
        # 22/11/2026: o theo.json do Placar (ao lado do apostas.json): cada palpite com tudo o que o teste sabe
        th = json.load(open(os.path.join(pasta, "theo.json"), encoding="utf-8"))
        assert th["v"] == 1 and th["palpites"] and len(th["contas"]) == len(A.BDM_CONTAS)
        ps = th["palpites"]
        assert [x["inicio"] or 0 for x in ps] == sorted([x["inicio"] or 0 for x in ps], reverse=True)
        feito = [x for x in ps if x["odd"]]
        assert feito and all(x["justa"] and x["casa"] and x["contas"]["bdm"]["st"] == "apostado" for x in feito)
        assert all(abs(x["valor"] - (x["odd"] / x["justa"] - 1)) < 1e-3 for x in feito)
        assert any(x["fechamento"] and x["clv"] is not None for x in feito) and any(x["resultado"] for x in feito)
        assert any(x["situacao"] == "fora" and x["motivo"] for x in ps)
        assert any(x["historico"] and x["historico"]["n"] for x in ps) and any(x["conviccao"] == "alta" for x in ps)
        assert any(c.get("o") for x in feito for k, c in x["contas"].items() if k != "bdm")
        assert all(set(x) >= {"mandante", "visitante", "competicao", "mercado", "selecao", "oddCitada", "video"} for x in ps)
        # nenhum pedido a mais: um /historical-odds por jogo, com ou sem palpite
        hist = sum(1 for f in V["fx"].values() if f["st"] in ("feito", "semOdds"))
        assert cli.contagem["oddspapi"] <= hist + 60, (cli.contagem, hist)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def teste_sinteticos():
    """22/11/2026: a dupla chance e o empate anula pelo preço do 1X2."""
    hs = [[(1, 2.0), (5, 2.1)], [(1, 3.5)], [(1, 4.0)]]
    d = A.serie_sintetica("dupla", hs)
    assert perto(d[0][0][1], 1 / (1 / 2.0 + 1 / 3.5), 1e-3) and perto(d[2][0][1], 1 / (1 / 3.5 + 1 / 4.0), 1e-3)
    assert [t for t, _ in d[0]] == [1, 5]
    n = A.serie_sintetica("dnb", hs)
    assert perto(n[0][0][1], 2.0 * (1 - 1 / 3.5), 1e-3) and perto(n[1][0][1], 4.0 * (1 - 1 / 3.5), 1e-3)
    assert A.serie_sintetica("dnb", [[(1, 2.0)], [], [(1, 4.0)]]) is None
    p = A.sem_margem([2.0, 3.5, 4.0])
    assert all(perto(a, b, 1e-9) for a, b in zip(A.justas("dupla", [2.0, 3.5, 4.0]), [p[0] + p[1], p[0] + p[2], p[1] + p[2]]))
    j = A.justas("dnb", [2.0, 3.5, 4.0])
    assert perto(j[0] + j[1], 1, 1e-9) and perto(j[0], p[0] / (p[0] + p[2]), 1e-9)
    assert A.ganhou("dupla", 0, (1, 1)) and A.ganhou("dupla", 0, (2, 1)) and not A.ganhou("dupla", 0, (0, 1))
    assert A.ganhou("dupla", 1, (0, 1)) and not A.ganhou("dupla", 1, (1, 1))
    assert A.devolve("dnb", (1, 1)) and not A.devolve("dnb", (2, 1)) and not A.devolve("dupla", (1, 1))
    assert A.ganhou("dnb", 1, (0, 2)) and not A.ganhou("dnb", 0, (0, 2))
    assert A.indice_bdm({"mk": "dupla", "sel": "1x"}, True) == 2 and A.indice_bdm({"mk": "dnb", "sel": "mandante"}, True) == 1
    assert A.precificavel({"fora": False, "m": "A", "v": "B", "mk": "dupla", "sel": "x2"}) == (True, None)
    # o empate devolve: a conta não perde nem conta a aposta
    c = A.Conta(next(x for x in A.VERSOES if x[0] == "bdm"), 0)
    ap = {"j": "x", "jogo": "A × B", "l": "eng", "i": 0, "mk": "dnb", "s": 0, "sel": "A (empate anula)", "o": 1.5,
          "p": 0.6, "v": 0, "st": 20.0, "c": "Bet365", "g": False, "clv": None}
    c.abrir(ap)
    antes = c.caixa
    assert c.liquidar(ap, (1, 1), HORA) == 0.0 and c.caixa == antes + 20.0 and c.acc["n"] == 0 and c.acc["devolvidas"] == 1
    # a confiança: R$ 30, 20 e 10
    cc = A.Conta(next(x for x in A.VERSOES if x[0] == "bdmConf"), 0)
    assert [cc._stake(2.0, 0.5, A.CONFIANCA[k]) for k in ("alta", "normal", "baixa")] == [30.0, 20.0, 10.0]
    assert A.palpite_bdm({"id": "x", "mandante": "A", "visitante": "B", "mercado": "dnb", "selecao": "mandante",
                          "conviccao": "Alta"}, "2026-11-22", "v")["conf"] == "alta"
    assert A.palpite_bdm({"id": "x", "mandante": "A", "visitante": "B", "mercado": "1x2", "selecao": "mandante",
                          "conviccao": "talvez"}, "2026-11-22", "v")["conf"] is None
    # o histórico no empate anula: os empates não contam
    js = [(k, "A", f"X{k}", 1, 1) for k in range(4)] + [(10 + k, "A", f"Y{k}", 2, 0) for k in range(6)] + \
        [(20 + k, f"Z{k}", "B", 3, 0) for k in range(6)]
    h = A.chance_historico(js, "A", "B", 100, "dnb", 0)
    assert h and h["taxas"][0] == 1.0, h


def teste_bdm_historico():
    """21/11/2026: a chance pelo histórico (o mandante em casa, o visitante fora, os confrontos diretos e o desconto
    pela média da liga), a convergência, o preço mínimo e o favorito."""
    H = 3600 * 1000
    js = []
    t = 0
    for k in range(24):   # o resto da liga: vitórias de fora (a média de vitória em casa fica baixa)
        t += H
        js.append((t, f"P{k}", f"Q{k}", 0, 1))
    # 8 jogos do Alfa em casa: 6 vitórias; 8 do Beta fora: 5 derrotas; 3 confrontos (2 vitórias do Alfa)
    for k in range(8):
        t += H
        js.append((t, "Alfa", f"X{k}", 2, 0) if k < 6 else (t, "Alfa", f"X{k}", 0, 1))
    for k in range(8):
        t += H
        js.append((t, f"Y{k}", "Beta", 3, 1) if k < 5 else (t, f"Y{k}", "Beta", 1, 1))
    t += H
    js.append((t, "Alfa", "Beta", 1, 0))
    t += H
    js.append((t, "Beta", "Alfa", 0, 2))   # o Alfa venceu fora: conta como vitória dele
    t += H
    js.append((t, "Beta", "Alfa", 1, 0))
    n_base = len(js)
    vit_casa = sum(1 for j in js if j[3] > j[4])
    base = vit_casa / n_base
    r = A.chance_historico(js, "Alfa FC", "Beta", t + 1, "1x2", 0)
    assert r and r["n"] == [8, 8, 3], r
    # em casa, os 8 últimos: 5 vitórias e 2 derrotas contra os X + o 1 × 0 no Beta = 6 de 8; fora, os 8 últimos do
    # Beta: 4 derrotas contra os Y + o 1 × 0 do Alfa = 5 de 8 (os jogos do Beta em casa não entram); confrontos: o
    # Alfa venceu 2 de 3 (o 0 × 2 fora conta como vitória dele)
    assert r["taxas"] == [0.75, 0.625, round(2 / 3, 3)], r
    esperado = (6 + 5 + 2 + base * A.HIST_PESO) / (8 + 8 + 3 + A.HIST_PESO)
    assert abs(r["p"] - round(esperado, 4)) < 1e-9 and r["forte"] and r["base"] == round(base, 4)
    # o empate: as taxas ficam abaixo da média, sem convergência
    e = A.chance_historico(js, "Alfa", "Beta", t + 1, "1x2", 1)
    assert e and not e["forte"]
    # só o que veio antes do palpite conta; poucos jogos = sem histórico; time desconhecido também
    assert A.chance_historico(js, "Alfa", "Beta", js[30][0], "1x2", 0) is None
    assert A.chance_historico(js, "Gama", "Beta", t + 1, "1x2", 0) is None
    assert A.time_na_liga("Man City", [(1, "Man City", "Man United", 0, 0)]) == "Man City"
    assert A.time_na_liga("Manchester", [(1, "Man City", "Man United", 0, 0)]) is None  # os dois batem: ambíguo
    # gols: mais de 2,5 nos jogos do Beta fora (3 × 1) e nunca nos do Alfa em casa
    g = A.chance_historico(js, "Alfa", "Beta", t + 1, "ou", 0)
    assert g["taxas"][0] == 0 and g["taxas"][1] == round(4 / 8, 3)
    # o preço mínimo e o favorito
    assert A.preco_minimo([(1, 1.8), (5, 2.05), (9, 2.3)], 1, 8, 2.0) == (5, 2.05)
    assert A.preco_minimo([(1, 1.8), (9, 2.3)], 1, 8, 2.0) is None
    sh = [[(1, 2.1)], [(1, 3.3)], [(1, 3.6)]]
    ph = [[(2, 2.0)], [(2, 3.5)], [(2, 4.0)]]
    x = A.favorito_em(sh, ph, 1, 9)
    assert x[0] == 2 and x[1] == 0 and x[2] == 2.1 and abs(sum(x[3]) - 1) < 1e-9
    assert A.favorito_em(sh, ph, 1, 2) is None


def teste_avulsa():
    """Sem o mixin (o falso.py de hoje), os exemplos usam a fonte avulsa."""
    pasta = tempfile.mkdtemp(prefix="apostas-")
    try:
        cli = falso.ClientePapelFalso()
        ind = rodar(cli, pasta)
        assert ind["formas"]["apostas"]["ok"]
        d = _forma(pasta)
        assert d["exemplo"] and all(v["aoVivo"] for v in d["versoes"])
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    teste_contas()
    teste_versoes()
    teste_planilhas()
    teste_leitura_oddspapi()
    teste_orcamento()
    teste_rodadas()
    teste_sem_chave_e_falhas()
    teste_lista_vazia_404()
    teste_formato_estranho()
    teste_bdm_palpites()
    teste_bdm_arquivos()
    teste_bdm_rodadas()
    teste_bdm_historico()
    teste_sinteticos()
    teste_avulsa()
    print("ok")
