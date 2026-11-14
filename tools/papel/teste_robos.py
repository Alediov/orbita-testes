"""Testes dos robôs de grade e DCA no papel (robos.py). Uso: python3 tools/papel/teste_robos.py"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)

import falso  # noqa: E402
import papel  # noqa: E402
import robos  # noqa: E402
from conta import DIA, HORA, Curva  # noqa: E402

MIN = 60_000
RISCOS = {"baixo", "médio", "alto"}


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def vela(t, o, h, l, c, passo=MIN):
    return (t, t + passo - 1, o, h, l, c)


def cfg_de(id_):
    return dict(next(c for c in robos.VERSOES if c["id"] == id_))


# ---------------------------------------------------------------------- contas à mão
def teste_grade_a_mao():
    r = robos.Robo(cfg_de("gbtc10"))
    s = r.novo(0)
    r.vela(s, vela(0, 100, 100, 100, 100))
    assert [round(x, 9) for x in s["L"]] == [float(90 + i) for i in range(21)]
    soma = sum(90 + k for k in range(10)) * 1.0004
    pb = 100 * 1.0005 * 1.0007
    q = 1000 / (soma + 10 * pb) * 0.999
    assert perto(s["q"], q), (s["q"], q)
    assert perto(s["moeda"], 10 * q)
    assert perto(s["caixa"], 1000 - 10 * q * pb)
    taxa0 = 10 * q * 100.05 * 0.0007 + 10 * q * 100 * 0.0005
    assert perto(s["buf"]["taxas"], taxa0)
    s["buf"] = robos._buf()
    # encostar em 99 não executa (precisa passar um tique além)
    r.vela(s, vela(MIN, 100, 100, 99.0, 99.5))
    assert s["degraus"] == 0 and perto(s["moeda"], 10 * q)
    # passar de 98,9901 executa a compra em 99 (e só ela)
    caixa = s["caixa"]
    r.vela(s, vela(2 * MIN, 100, 100, 98.98, 99.5))
    assert s["degraus"] == 1 and perto(s["moeda"], 11 * q)
    assert perto(s["caixa"], caixa - q * 99 * 1.0004)
    # a venda em 100 fecha o par com lucro de q × (100 × 0,9996 − 99 × 1,0004)
    s["buf"] = robos._buf()
    r.vela(s, vela(3 * MIN, 99.5, 100.02, 99.4, 99.9))
    assert s["degraus"] == 2 and perto(s["moeda"], 10 * q)
    assert len(s["buf"]["fech"]) == 1 and perto(s["buf"]["fech"][0], q * (100 * 0.9996 - 99 * 1.0004))
    assert s["buf"]["ops"] == 1 and perto(s["buf"]["taxas"], q * 100 * 0.0004)


def teste_caminho_pessimista():
    r = robos.Robo(cfg_de("gbtc10"))
    s = r.novo(0)
    r.vela(s, vela(0, 100, 100, 100, 100))
    v = vela(MIN, 100, 101.2, 98.8, 99.5)
    a, b = copy.deepcopy(s), copy.deepcopy(s)
    r.caminho(a, MIN, [100, 98.8, 101.2, 99.5])
    r.caminho(b, MIN, [100, 101.2, 98.8, 99.5])
    ea, eb = r.patrimonio(a, 99.5), r.patrimonio(b, 99.5)
    assert abs(ea - eb) > 1e-6, "os dois caminhos deveriam dar resultados diferentes"
    r.vela(s, v)
    assert perto(r.patrimonio(s, 99.5), min(ea, eb))
    assert s["degraus"] == (a if ea <= eb else b)["degraus"]


def teste_liquidacao():
    cfg = cfg_de("dcam3")
    r = robos.Robo(cfg, lev_max=40)
    assert perto(r.mmr, 1 / 80)
    s = r.novo(0)
    s.update(ini=True, fase="ciclo", ref=100.0, k=5, B=1.0, eq0=1000.0, C=40.0, p=1.0, e=100.0)
    liq = (100 - 40) / (1 - 1 / 80)
    assert perto(r.liq(s), liq)
    s2 = copy.deepcopy(s)
    r.vela(s2, vela(0, 70, 70, liq * 1.001, 65))
    assert not s2["morta"]
    r.vela(s, vela(0, 70, 70, 60, 65))
    assert s["morta"] and r.patrimonio(s, 65) == 0
    # a perda da liquidação é o que restava no preço de liquidação (a manutenção), não o colateral inteiro
    assert perto(s["buf"]["liq"][0]["perda"], round(liq / 80, 2), 1e-3), s["buf"]["liq"]
    # vendida: liquida na alta
    s3 = r.novo(0)
    s3.update(ini=True, fase="esperando", C=40.0, p=-1.0, e=100.0)
    s3["fase"] = "x"  # sem ordens nem ciclo novo
    lq = (40 + 100) / (1 + 1 / 80)
    assert perto(r.liq(s3), lq)
    r.vela(s3, vela(0, 120, 140, 120, 130))
    assert s3["morta"]


def teste_neutra_1x_sem_liquidar():
    """A grade neutra 1× (HYPE, alavancagem máxima 10: a manutenção mais alta) não é liquidada com 20% para cima ou
    para baixo; com o preço quase dobrando acima da grade, a posição vendida (1×) é, e a conta por dentro põe o
    prejuízo no preço, não na liquidação."""
    for alvo in (120.0, 80.0):
        r = robos.Robo(cfg_de("ghype1"), lev_max=10)
        s = r.novo(0)
        t, px = 0, 100.0
        r.vela(s, vela(t, 100, 100, 100, 100, HORA))
        for k in range(1, 41):
            novo = 100 + (alvo - 100) * k / 40
            t += HORA
            r.vela(s, vela(t, px, max(px, novo), min(px, novo), novo, HORA))
            px = novo
        assert not s["morta"] and r.patrimonio(s, px) > 700, (alvo, r.patrimonio(s, px))
        assert abs(s["p"]) * px < 1300  # 1×: a posição nunca passa do patrimônio de partida (+ o movimento)
    r = robos.Robo(cfg_de("ghype1"), lev_max=10)
    s = r.novo(0)
    t, px = 0, 100.0
    r.vela(s, vela(t, 100, 100, 100, 100, HORA))
    for k in range(1, 81):
        novo = 100 * 2.0 ** (k / 80)
        t += HORA
        r.vela(s, vela(t, px, max(px, novo), min(px, novo), novo, HORA))
        px = novo
        if s["morta"]:
            break
    assert s["morta"] and px > 180, px
    pd = r.por_dentro(s, px)
    assert pd["liquidacoes"] < 120 and pd["preco"] < -800, pd


def teste_dca():
    r = robos.Robo(cfg_de("dca"))
    s = r.novo(0)
    r.vela(s, vela(0, 100, 100, 100, 100, HORA))
    q = 50 / (100 * 1.0005 * 1.0007)
    assert perto(s["moeda"], q) and perto(s["caixa"], 950)
    assert perto(s["buf"]["taxas"], q * 100.05 * 0.0007 + q * 100 * 0.0005)
    r.vela(s, vela(DIA, 90, 90, 90, 90, HORA))
    assert s["compras"] == 1
    r.vela(s, vela(7 * DIA, 80, 80, 80, 80, HORA))
    assert s["compras"] == 2 and perto(s["caixa"], 900)
    # DCA na queda: só com 5% abaixo da máxima de 7 dias
    rq = robos.Robo(cfg_de("dcaqueda"))
    sq = rq.novo(0)
    rq.aquecer(sq, [vela(-HORA, 100, 100, 100, 100, HORA)])
    rq.vela(sq, vela(0, 96, 96, 96, 96, HORA))
    assert sq["compras"] == 0
    rq.vela(sq, vela(HORA, 95, 95, 94.9, 94.9, HORA))
    assert sq["compras"] == 1 and perto(sq["caixa"], 950)
    rq.vela(sq, vela(2 * HORA, 90, 90, 90, 90, HORA))
    assert sq["compras"] == 1  # no máximo uma por semana


def teste_martingale():
    r = robos.Robo(cfg_de("dcam1"))
    s = r.novo(0)
    r.vela(s, vela(0, 100, 100, 100, 100))
    soma = sum(1.5 ** j for j in range(6))
    B = 1000 / soma / 1.003
    assert perto(s["B"], B) and perto(s["moeda"], B / (100 * 1.0005 * 1.0007))
    r.vela(s, vela(MIN, 100, 100, 97.9, 98))
    assert s["k"] == 1 and s["compras"] == 1
    assert perto(s["moeda"], B / (100 * 1.0005 * 1.0007) + 1.5 * B / (98 * 1.0004))
    tp = r.preco_medio(s) * 1.015
    s["buf"] = robos._buf()
    r.vela(s, vela(2 * MIN, 98, tp * 1.0002, 98, tp))
    assert s["ciclos"] == 1 and s["fase"] == "esperando" and s["moeda"] == 0
    assert len(s["buf"]["fech"]) == 1 and s["buf"]["fech"][0] > 0
    assert perto(s["buf"]["fech"][0], s["caixa"] - 1000)
    r.vela(s, vela(3 * MIN, 101, 101, 101, 101))
    assert s["fase"] == "ciclo" and s["ref"] == 101


def teste_pares():
    cli = falso.ClientePapelFalso()
    ctx = SimpleNamespace(cli=cli, agora=cli.agora)
    erros = []
    assert robos.resolver_pares(ctx, {}, erros) == {"BTC": "@142", "ETH": "@151", "SOL": "@156", "HYPE": "@107"}
    assert not erros
    cli.falhar.add("spotMetaAndAssetCtxs")
    est = {}
    assert robos.resolver_pares(ctx, est, erros)["BTC"] == "@142" and erros


# ---------------------------------------------------------------------- formato
def conferir_conta(c, onde, capital_inicio=False):
    if c is None:
        return
    for k in ("inicio", "serie", "retorno", "piorQueda", "ops", "taxas", "liquidacoes", "nLiq"):
        assert k in c, f"{onde}: falta {k}"
    dias = [d for d, _ in c["serie"]]
    assert dias == sorted(dias) and len(set(dias)) == len(dias), f"{onde}: série fora de ordem"
    assert 0 <= c["piorQueda"] <= 1
    if c["serie"]:
        assert abs(c["serie"][-1][1] / 1000 - 1 - c["retorno"]) < 0.01, onde
    if "extra" in c:
        assert {"comprado", "caixa", "degrausExecutados", "precoMedio", "foraDaGrade", "porDentro"} <= set(c["extra"]), onde
        pd = c["extra"]["porDentro"]
        soma = pd["pares"] + pd["financiamento"] + pd["juros"] - pd["custos"] - pd["liquidacoes"] + pd["preco"]
        assert abs(soma - pd["resultado"]) < 0.01, (onde, pd)
    if c.get("acerto") is not None:
        assert 0 <= c["acerto"] <= 1


def conferir_forma(d):
    for k in ("v", "forma", "nome", "agora", "frase", "comoFunciona", "padrao", "versoes", "eventos", "itens",
              "avisos", "config", "rodada"):
        assert k in d, f"falta {k}"
    assert d["forma"] == "robos" and d["nome"] == "Robôs"
    ids = [v["id"] for v in d["versoes"]]
    assert ids == ["gbtc10", "geth10", "gbtc20r", "gneutra1", "gneutra3", "dca", "dcaqueda", "dcam1", "dcam3",
                   "gsaida1", "gsaida3", "gvol2", "gvol4", "gsol1", "ghype1", "dcaC", "tcruz", "tcruzls", "tcruzeth",
                   "trompe", "tmovel", "rfaixa", "rfaixavol", "rbandas", "rbandastend", "rrsi", "rbandasls", "irbandas",
                   "irsi", "icruzls", "segbtc", "segeth"]
    assert d["padrao"] in ids
    for v in d["versoes"]:
        assert v["risco"] in RISCOS and v["nome"] and v["frase"] and 1 <= v["alav"] <= 3
        conferir_conta(v["aoVivo"], v["id"] + "/aoVivo")
        conferir_conta(v["historico"], v["id"] + "/historico")
        if v["historico"]:
            assert v["historico"]["aproximado"] is False and v["historico"]["de"] <= v["historico"]["ate"]
            j = v["historico"].get("janelas")
            if j:
                assert 0 <= j["venceCdi"] <= j["n"] and j["pior"]["retorno"] <= j["mediana"] <= j["melhor"]["retorno"]
    assert [v["id"] for v in d["versoes"] if v["grupo"] == "Referência"] == ["segbtc", "segeth"]
    ems = [e["em"] for e in d["eventos"]]
    assert ems == sorted(ems, reverse=True) and len(ems) <= 300
    for e in d["eventos"]:
        assert {"em", "versao", "tipo", "texto"} <= set(e)
    assert len(json.dumps(d)) < 400_000


def teste_rodadas():
    pasta = tempfile.mkdtemp(prefix="robos-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora
        ler = lambda n: json.load(open(os.path.join(pasta, n)))  # noqa: E731
        papel.rodada(cli, pasta, t0, ["robos"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))
        d = ler("robos.json")
        conferir_forma(d)
        for v in d["versoes"]:
            assert v["aoVivo"]["serie"] == [[robos.dia_de(t0), 1000.0]] and v["aoVivo"]["retorno"] == 0
            assert v["historico"] is not None
        hist_em = ler("estado.json")["formas"]["robos"]["hist"]["em"]
        # 7,5 dias a cada 6 h
        for k in range(1, 31):
            cli.agora = t0 + k * 6 * HORA
            papel.rodada(cli, pasta, cli.agora, ["robos"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))
            d = ler("robos.json")
            conferir_forma(d)
            assert ler("indice.json")["formas"]["robos"]["ok"]
        est = ler("estado.json")["formas"]["robos"]
        assert est["hist"]["em"] > hist_em, "o teste no passado deveria ter sido refeito depois de 7 dias"
        for vid, vv in est["vivo"].items():
            assert vv["bot"]["ate"] == (cli.agora // MIN) * MIN, vid  # alcançou até a última vela fechada
            c = Curva.de_json(vv["curva"])
            assert c.capital == 1000
        assert any(v["aoVivo"]["ops"] > 0 for v in d["versoes"])
        assert any("degrau" in e["texto"] for e in d["eventos"])
        # buraco de 30 h: alcança com velas de 1 min (ainda dentro dos ~3,5 dias)
        cli.agora += 30 * HORA
        papel.rodada(cli, pasta, cli.agora, ["robos"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))
        est = ler("estado.json")["formas"]["robos"]
        assert all(vv["bot"]["ate"] == cli.agora // MIN * MIN for vv in est["vivo"].values())
        conferir_forma(ler("robos.json"))
        # buraco de 5 dias: alcança com velas mais grossas (5 min)
        log = papel.Log(quieto=True)
        cli.agora += 5 * DIA
        papel.rodada(cli, pasta, cli.agora, ["robos"], exemplo=True, buscar_cdi=False, log=log)
        assert any("velas de 5m" in x for x in log.linhas), log.linhas
        est = ler("estado.json")["formas"]["robos"]
        assert all(vv["bot"]["ate"] == cli.agora // (5 * MIN) * (5 * MIN) for vv in est["vivo"].values())
        # pedido de velas falhando: a forma fica ok: false e o robos.json continua o da rodada anterior
        antes = ler("robos.json")["agora"]
        cli.falhar.add("candleSnapshot")
        cli.agora += 6 * HORA
        ind = papel.rodada(cli, pasta, cli.agora, ["robos"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))
        assert ind["formas"]["robos"]["ok"] is False and ler("robos.json")["agora"] == antes
        cli.falhar.clear()
        cli.agora += 6 * HORA
        ind = papel.rodada(cli, pasta, cli.agora, ["robos"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))
        assert ind["formas"]["robos"]["ok"] is True
        conferir_forma(ler("robos.json"))
        # financiamento falhando: só o perpétuo espera; o resto anda e o erro aparece na rodada
        cli.falhar.add("fundingHistory")
        cli.agora += 6 * HORA
        ind = papel.rodada(cli, pasta, cli.agora, ["robos"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))
        d = ler("robos.json")
        assert ind["formas"]["robos"]["ok"] and d["rodada"]["erros"]
        est = ler("estado.json")["formas"]["robos"]
        assert est["vivo"]["gbtc10"]["bot"]["ate"] > est["vivo"]["gneutra1"]["bot"]["ate"]
        cli.falhar.clear()
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def teste_tempo_do_historico():
    """O teste no passado com o maior trecho de velas de 1 h do mercado de mentira (~59 dias) precisa ser rápido."""
    cli = falso.ClientePapelFalso()
    cli.agora = falso.T0 + 59 * DIA
    ctx = SimpleNamespace(cli=cli, agora=cli.agora, est={}, antigo=None, log=lambda x: None, exemplo=True, ref={},
                          restante=lambda: 1000)
    t = time.monotonic()
    robos.rodar(ctx)
    s = time.monotonic() - t
    assert s < 20, f"teste no passado lento: {s:.1f} s para ~59 dias"
    print(f"  teste no passado de ~59 dias: {s:.1f} s (180 dias ≈ {s * 3:.0f} s)")


# ---------------------------------------------------------------------- revisão de 09/11/2026
def teste_regua_segurar():
    r = robos.Robo(cfg_de("segbtc"))
    s = r.novo(0)
    r.vela(s, vela(0, 100, 100, 100, 100, HORA))
    q = 1000 / (100 * 1.0005 * 1.0007)
    assert perto(s["moeda"], q) and s["caixa"] < 1e-6
    r.vela(s, vela(HORA, 100, 130, 90, 120, HORA))
    assert perto(r.patrimonio(s, 120), q * 120) and s["buf"]["ops"] == 1
    pd = r.por_dentro(s, 120)
    assert pd["pares"] == 0 and perto(pd["resultado"], q * 120 - 1000, 1e-4)
    assert perto(pd["preco"] - pd["custos"], pd["resultado"], 1e-4)
    assert next(c for c in robos.VERSOES if c["id"] == "segeth")["grupo"] == "Referência"


def teste_por_dentro_par():
    """Um par fechado da grade: pares = q × (100 − 99) bruto; o resto (taxas, deslize) separado."""
    r = robos.Robo(cfg_de("gneutra1"))
    s = r.novo(0)
    r.vela(s, vela(0, 100, 100, 100, 100))
    q = s["q"]
    r.vela(s, vela(MIN, 100, 100, 98.98, 99.5))
    r.vela(s, vela(2 * MIN, 99.5, 100.02, 99.4, 100))
    pd = r.por_dentro(s, 100)
    assert perto(pd["pares"], q * 1.0), (pd, q)
    assert abs(pd["taxas"] - (q * 99 * 0.00015 + q * 100 * 0.00015)) < 1e-4
    assert pd["deslize"] == 0
    soma = pd["pares"] + pd["financiamento"] + pd["juros"] - pd["custos"] - pd["liquidacoes"] + pd["preco"]
    assert perto(soma, pd["resultado"], 1e-6)
    assert abs(pd["preco"]) < 1e-6  # sem posição aberta


def _subir_horas(r, s, t0, precos):
    """Uma vela de 1 h por preço, abrindo no fechamento da anterior (o caminho passa pelos degraus)."""
    t = t0
    for p in precos:
        o = s.get("px") or p
        r.vela(s, vela(t, o, max(o, p), min(o, p), p, HORA))
        s["px"] = p
        t += HORA
    return t


def teste_grade_saida():
    r = robos.Robo(cfg_de("gsaida1"))
    s = r.novo(0)
    t = _subir_horas(r, s, 0, [100] * 3)
    assert s["L"][-1] == 110.00000000000001 or perto(s["L"][-1], 110)
    # passa um degrau (1) além da borda de cima: fecha tudo e para
    t = _subir_horas(r, s, t, [104, 108, 110.5, 111.2])
    assert s["parada"] and s["parada"]["motivo"] == "grade" and abs(s["p"]) < 1e-12
    ev = [x for x in s["buf"]["ev"] if x[1] == "saiu"]
    assert ev and ev[-1][3] == "grade"
    assert r.ordens(s) == []
    # ainda balançando (> 4% em 24 h): não volta
    t = _subir_horas(r, s, t, [111, 116, 110] * 8)
    assert s["parada"]
    # 24 h calmas: remonta em volta do preço
    t = _subir_horas(r, s, t, [112] * 26)
    assert not s["parada"] and perto(s["centro"], 112) and s["remontes"] == 1
    assert r.extra(s)["remontes"] == 1 and r.extra(s)["parada"] is False
    # o stop de 15% do topo (3×): uma queda forte dentro da grade, com a conta comprada
    r3 = robos.Robo(cfg_de("gsaida3"))
    s3 = r3.novo(0)
    t = _subir_horas(r3, s3, 0, [100] * 2)
    t = _subir_horas(r3, s3, t, [97, 94, 92, 91])
    assert not s3.get("parada")  # ~11% abaixo: ainda dentro
    eq = r3.patrimonio(s3, 91)
    assert 0.08 < 1 - eq / s3["picoG"] < 0.15, eq
    s3["picoG"] = eq / 0.84  # como se o melhor momento tivesse sido 16% acima de agora
    t = _subir_horas(r3, s3, t, [91])
    assert s3["parada"] and s3["parada"]["motivo"] == "stop", s3.get("parada")
    assert abs(s3["p"]) < 1e-12
    assert r3.patrimonio(s3, 91) > 0


def teste_grade_oscilacao():
    r = robos.Robo(cfg_de("gvol2"))
    s = r.novo(0)
    # 7 dias de retornos de hora em hora de ±0,5% alternados: oscilação diária ≈ 0,5% × √24 ≈ 2,45%
    velas, p = [], 100.0
    for i in range(7 * 24):
        p *= 1.005 if i % 2 == 0 else 1 / 1.005
        velas.append(vela(-7 * DIA + i * HORA, p, p, p, p, HORA))
    r.aquecer(s, velas)
    vd = r.vol_dia(s, 0)
    assert 0.023 < vd < 0.026, vd
    r.vela(s, vela(0, 100, 100, 100, 100, HORA))
    assert perto(s["faixa"], 2 * vd, 1e-3) and perto(s["L"][0], 100 * (1 - s["faixa"]))
    # segunda-feira (Brasília): mede de novo e recentra, pagando a troca
    t = 0
    seg = next(x for x in range(DIA, 8 * DIA, HORA) if robos.semana_de(x) != robos.semana_de(0))
    while t < seg:
        t += HORA
        r.vela(s, vela(t, 105, 105, 105, 105, HORA))
    assert perto(s["centro"], 105) and any(x[1] == "reequilibrou" for x in s["buf"]["ev"])
    # sem dados suficientes: a largura padrão
    r2 = robos.Robo(cfg_de("gvol4"))
    s2 = r2.novo(0)
    r2.vela(s2, vela(0, 100, 100, 100, 100, HORA))
    assert perto(s2["faixa"], 4 * robos.VOL_PADRAO)


def teste_dca_caixa():
    r = robos.Robo(cfg_de("dcaC"))
    r.juro = lambda t: 0.10
    s = r.novo(0)
    r.vela(s, vela(0, 100, 100, 100, 100, HORA))
    ida = robos.FD.custo_caixa(950, True)
    assert s["caixa"] < 1e-6 and perto(s["aave"], 950 - ida) and perto(s["acc"]["ponte"], ida)
    a0 = s["aave"]
    r.vela(s, vela(HORA, 100, 100, 100, 100, HORA))
    assert perto(s["aave"], a0 * 1.10 ** (HORA / (365 * DIA)), 1e-9) and s["acc"]["juros"] > 0
    t = HORA
    while t < 7 * DIA:
        t += HORA
        r.vela(s, vela(t, 100, 100, 100, 100, HORA))
    assert s["compras"] == 2 and s["caixa"] < 1 and s["acc"]["ponte"] > ida
    pd = r.por_dentro(s, 100)
    soma = pd["pares"] + pd["financiamento"] + pd["juros"] - pd["custos"] - pd["liquidacoes"] + pd["preco"]
    assert perto(soma, pd["resultado"], 1e-6) and pd["juros"] > 0
    # a última compra saca tudo
    s.update(compras=19)
    r._compra_dca(s, t + HORA, 100, "a última")
    assert s["aave"] == 0 and s["compras"] == 20 and s["caixa"] > 400


def teste_janelas():
    import datetime as dt
    d0 = dt.date(2026, 1, 1)
    # +0,1% por dia por 60 dias; CDI 0,05% por dia útil
    serie = [[(d0 + dt.timedelta(days=i)).isoformat(), 1000 * 1.001 ** i] for i in range(61)]
    cdi = {(d0 + dt.timedelta(days=i)).isoformat(): 0.0005 for i in range(61) if (d0 + dt.timedelta(days=i)).weekday() < 5}
    j = robos.janelas({"serie": serie}, cdi, 0.13)
    assert j["n"] == 5 and j["venceCdi"] == 5, j  # dias 0, 7, 14, 21, 28 (+30 ≤ 60)
    assert perto(j["mediana"], 1.001 ** 30 - 1, 1e-4)
    assert j["lista"][0][0] == "2026-01-01" and 0.009 < j["lista"][0][2] < 0.012
    # caindo: perde em todas
    serie2 = [[d, 2000 - v] for d, v in serie]
    j2 = robos.janelas({"serie": serie2}, cdi, 0.13)
    assert j2["venceCdi"] == 0 and j2["pior"]["retorno"] <= j2["mediana"] <= j2["melhor"]["retorno"]
    assert robos.janelas({"serie": serie[:20]}, cdi, 0.13) is None


def teste_sem_dados_e_antigo():
    """Uma moeda sem velas não quebra (a versão diz o motivo); um estado antigo (sem a conta por dentro) continua."""
    pasta = tempfile.mkdtemp(prefix="robos-")
    try:
        cli = falso.ClientePapelFalso()
        orig = cli.velas
        cli.velas = lambda m, i, a, b: [] if m == "HYPE" else orig(m, i, a, b)
        papel.rodada(cli, pasta, cli.agora, ["robos"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))
        d = json.load(open(os.path.join(pasta, "robos.json")))
        v = next(x for x in d["versoes"] if x["id"] == "ghype1")
        assert v["historico"] is None and "HYPE" in v["semDados"], v
        assert next(x for x in d["versoes"] if x["id"] == "gsol1")["historico"]
        # estado antigo: sem `acc` nas contas ao vivo nem `hv` no teste no passado
        cli.velas = orig
        caminho = os.path.join(pasta, "estado.json")
        est = json.load(open(caminho))
        fr = est["formas"]["robos"]
        for vv in fr["vivo"].values():
            vv["bot"].pop("acc", None)
            vv["bot"].pop("aave", None)
        fr["hist"].pop("hv", None)
        json.dump(est, open(caminho, "w"))
        cli.agora += 6 * HORA
        ind = papel.rodada(cli, pasta, cli.agora, ["robos"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))
        assert ind["formas"]["robos"]["ok"]
        d = json.load(open(os.path.join(pasta, "robos.json")))
        conferir_forma(d)
        v = next(x for x in d["versoes"] if x["id"] == "gbtc10")
        assert v["aoVivo"]["extra"]["porDentro"].get("estimado") is True
        assert v["historico"]["extra"]["porDentro"].get("estimado") is None
        assert json.load(open(caminho))["formas"]["robos"]["hist"]["hv"] == robos.HIST_V
        assert next(x for x in d["versoes"] if x["id"] == "ghype1")["historico"]  # agora com dados
        assert "semDados" not in next(x for x in d["versoes"] if x["id"] == "ghype1")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


# ---------------------------------------------------------------------- robôs de sinal (14/11/2026)
def _rodar_sinal(id_, precos, cfg_extra=None):
    cfg = cfg_de(id_)
    cfg.update(cfg_extra or {})
    r = robos.Robo(cfg)
    s = r.novo(0)
    _subir_horas(r, s, 0, precos)
    return r, s


def teste_sinais_indicadores():
    assert perto(robos.ema([1.0] * 30, 10), 1.0)
    xs = [float(i) for i in range(1, 40)]
    assert robos.ema(xs, 5) > robos.ema(xs, 20)  # subindo: a rápida fica acima
    assert robos.rsi(xs, 14) == 100.0
    assert robos.rsi(list(reversed(xs)), 14) < 1
    zig = [100 + (1 if i % 2 else -1) for i in range(60)]
    assert 40 < robos.rsi(zig, 14) < 60


def teste_tendencia():
    # 6 dias parados, 4 subindo, 4 caindo: entra na subida e sai na queda
    precos = [100.0] * 144 + [100 * 1.004 ** i for i in range(1, 97)] + [100 * 1.004 ** 96 * 0.996 ** i for i in range(1, 97)]
    r, s = _rodar_sinal("tcruz", precos)
    ev = [x for x in s["buf"]["ev"]]
    tipos = [x[1] for x in ev]
    assert "comprou" in tipos and "saiu" in tipos, tipos
    assert tipos.index("comprou") < len(tipos) - 1 - tipos[::-1].index("saiu")
    assert r._lado_real(s) == 0
    assert r.patrimonio(s, precos[-1]) > robos.CAPITAL * 1.05  # pegou boa parte da alta
    # nos dois lados, termina vendido na queda
    r2, s2 = _rodar_sinal("tcruzls", precos)
    assert r2._lado_real(s2) == -1
    # o contrário termina comprado e perde
    r3, s3 = _rodar_sinal("icruzls", precos)
    assert r3._lado_real(s3) == 1 and r3.patrimonio(s3, precos[-1]) < robos.CAPITAL
    e = r.extra(s)
    assert e["lado"] == 0 and e["entradas"] >= 1 and "rapida" in (e["indicadores"] or {})
    # rompimento: só depois de 7 dias de dados
    rr, sr = _rodar_sinal("trompe", [100.0] * 100 + [101.0])
    assert rr._lado_real(sr) == 0
    rr, sr = _rodar_sinal("trompe", [100.0 + (i % 3) * 0.1 for i in range(200)] + [104.0, 105.0])
    assert rr._lado_real(sr) == 1
    rm, sm = _rodar_sinal("tmovel", [100.0 + (i % 3) * 0.1 for i in range(200)] + [104, 110, 115, 120] + [80, 70, 60, 60])
    assert rm._lado_real(sm) == 0 and any("stop móvel" in x[2] for x in sm["buf"]["ev"])


def teste_baixa_alta():
    # vai e vem de ±5% em volta de 100 (período de 2 dias): compra na baixa, vende na alta e ganha
    import math as m
    precos = [100 * (1 + 0.05 * m.sin(2 * m.pi * i / 48)) for i in range(24 * 14)]
    r, s = _rodar_sinal("rfaixa", precos)
    compras = [x for x in s["buf"]["ev"] if x[1] == "comprou"]
    assert len(compras) >= 4, len(compras)
    for x in compras:
        px = float(x[2].split("comprou a US$ ")[1].split(".")[0].replace(",", ".")) if "comprou a" in x[2] else None
        assert px is None or px < 100
    assert r.patrimonio(s, precos[-1]) > robos.CAPITAL * 1.03, r.patrimonio(s, precos[-1])
    # o contrário nos dois lados perde no vai e vem
    picos = [(95.0 if i % 40 == 39 else 105.0 if i % 40 == 19 else 100 + (0.1 if i % 2 else -0.1)) for i in range(24 * 12)]
    ri, si = _rodar_sinal("irbandas", picos)
    rb, sb = _rodar_sinal("rbandasls", picos)
    assert [x for x in sb["buf"]["ev"] if x[1] == "comprou"] and [x for x in sb["buf"]["ev"] if x[1] == "vendeu"]
    precos = picos
    assert rb.patrimonio(sb, precos[-1]) > ri.patrimonio(si, precos[-1])
    # stop: cai 10% sem voltar → sai com o stop e espera um dia
    queda = [100.0] * 80 + [94.0] + [93 - i * 0.5 for i in range(20)]
    rq, sq = _rodar_sinal("rfaixa", queda)
    assert any(len(x) > 3 and x[3] == "stop" for x in sq["buf"]["ev"]), [x[2] for x in sq["buf"]["ev"]]
    assert rq._lado_real(sq) == 0
    # RSI: compra depois de uma queda forte
    rr, sr = _rodar_sinal("rrsi", [100.0] * 30 + [100 - i for i in range(1, 6)])
    assert rr._lado_real(sr) == 1
    # filtro de tendência: não compra a queda abaixo da média de 7 dias
    descendo = [200 - i * 0.3 for i in range(200)] + [130, 120]
    rt, st = _rodar_sinal("rbandastend", descendo)
    assert not [x for x in st["buf"]["ev"] if x[1] == "comprou"]
    assert [x for x in _rodar_sinal("rbandas", descendo)[1]["buf"]["ev"] if x[1] == "comprou"]


if __name__ == "__main__":
    teste_grade_a_mao()
    teste_caminho_pessimista()
    teste_liquidacao()
    teste_neutra_1x_sem_liquidar()
    teste_dca()
    teste_martingale()
    teste_pares()
    teste_rodadas()
    teste_tempo_do_historico()
    teste_regua_segurar()
    teste_por_dentro_par()
    teste_grade_saida()
    teste_grade_oscilacao()
    teste_dca_caixa()
    teste_janelas()
    teste_sem_dados_e_antigo()
    teste_sinais_indicadores()
    teste_tendencia()
    teste_baixa_alta()
    print("ok")
