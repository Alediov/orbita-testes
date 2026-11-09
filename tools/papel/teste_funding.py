"""Testes do funding no papel (sem rede). Uso: python3 tools/papel/teste_funding.py"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)  # antes do mercado: os dois têm um falso.py

import falso  # noqa: E402
import funding as F  # noqa: E402
import papel  # noqa: E402
from teste_papel import conferir_forma  # noqa: E402

HORA, DIA = falso.HORA, falso.DIA


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


# ------------------------------------------------------------------------------------------- contas à mão
def teste_posicao():
    p = F.Posicao(1000.0)
    custo, pernas, dq = p.montar(100.0, 100.0, 1, 0.0, 0.0)
    assert custo == 0 and pernas == 2 and perto(dq, 5)
    assert perto(p.qs, 5) and perto(p.qp, 5) and perto(p.margem, 500) and perto(p.valor(100, 100), 1000)
    # o preço deixa de importar: subiu 50%, o à vista ganha o que o vendido perde
    assert perto(p.valor(150, 150), 1000) and perto(p.valor(60, 60), 1000)
    # base: o perpétuo 1% acima do à vista pesa no valor marcado
    assert perto(p.valor(100, 101), 995)
    # financiamento: positivo o vendido recebe, negativo paga
    assert perto(p.financiar(0.0001, 100), 0.05) and perto(p.margem, 500.05)
    assert perto(p.financiar(-0.0002, 100), -0.1) and perto(p.margem, 499.95)
    # com taxas: q = V ÷ (ps + pp/L + ps·cs + pp·cp)
    p = F.Posicao(1000.0)
    custo, _, _ = p.montar(100.0, 100.0, 1, 0.001, 0.001)
    assert perto(p.qs, 1000 / 200.2, 1e-9) and perto(custo, p.qs * 0.2, 1e-9) and p.caixa < 1e-6
    assert perto(p.valor(100, 100) + custo, 1000, 1e-9)
    custo2, pernas = p.desmontar(100.0, 100.0, 0.001, 0.001)
    assert pernas == 2 and perto(p.caixa, 1000 - custo - custo2, 1e-9)


def teste_liquidacao_e_reequilibrio():
    p = F.Posicao(1000.0)
    p.montar(100.0, 100.0, 3, 0.0, 0.0)  # 75% à vista, 25% de margem
    assert perto(p.qs, 7.5) and perto(p.margem, 250) and perto(p.qs * 100, 750)
    mmr = 1 / 80  # BTC: alavancagem máxima 40
    assert perto(p.preco_liquidacao(mmr), 1000 / (7.5 * 1.0125))  # ≈ 131,69
    assert not p.fora_do_ponto(100, 3)
    assert not p.fora_do_ponto(111, 3)  # margem 167,5 de 277,5 (60,4%)
    assert p.fora_do_ponto(112, 3)      # margem 160 de 280 (57,1%)
    assert p.fora_do_ponto(79, 3)       # sobrou: margem 407,5 de 197,5 (> 200%)
    assert p.liquidar_se(131.0, mmr) is None
    perda = p.liquidar_se(132.0, mmr)
    assert perto(perda, 250) and p.qp == 0 and perto(p.qs, 7.5)
    assert perto(p.valor(132, 132), 7.5 * 132)  # o à vista ficou
    # remonta a partir do à vista que sobrou (pernas diferentes = fora do ponto)
    assert p.fora_do_ponto(132, 3)
    p.montar(132.0, 132.0, 3, 0.0, 0.0)
    assert perto(p.qs, p.qp) and perto(p.valor(132, 132), 7.5 * 132)
    assert perto(p.margem, p.qp * 132 / 3)


def dados_sinteticos(horas, taxas, precos=None, moedas=("BTC",)):
    """Velas e financiamento de mentira: `taxas[m]` e `precos[m]` são funções da hora (0, 1, 2…)."""
    t0 = 1_700_000_000_000 // HORA * HORA
    perp, spot, fund = {}, {}, {}
    for m in moedas:
        pr = (precos or {}).get(m, lambda i: 100.0)
        perp[m] = [{"t": t0 + i * HORA, "h": str(pr(i) * 1.001), "c": str(pr(i))} for i in range(-80, horas)]
        spot[m] = [{"t": t0 + i * HORA, "h": str(pr(i)), "c": str(pr(i))} for i in range(-80, horas)]
        fund[m] = [{"time": t0 + i * HORA + 40, "fundingRate": f"{taxas[m](i):.10f}"} for i in range(-80, horas + 1)]
    return F.Dados(perp, spot, fund, {m: 40 for m in moedas}), t0


def sem_taxas():
    guardado = (F.TAXA_SPOT, F.TAXA_PERP, dict(F.DESLIZE))
    F.TAXA_SPOT = F.TAXA_PERP = 0.0
    F.DESLIZE = {m: 0.0 for m in F.MOEDAS}
    return guardado


def com_taxas(g):
    F.TAXA_SPOT, F.TAXA_PERP, F.DESLIZE = g


def cfg(vid):
    return next(c for c in F.VERSOES if c[0] == vid)


def teste_conta_fixa():
    g = sem_taxas()
    try:
        d, t0 = dados_sinteticos(30, {"BTC": lambda i: 0.0001})
        c = F.Conta(cfg("btc1"), t0)
        c.passo(t0, d)
        for i in range(1, 25):
            c.passo(t0 + i * HORA, d)
        # 5 BTC × US$ 100 × 0,01% × 24 h = US$ 1,20
        assert perto(c.curva.ultimo, 1001.2, 1e-9), c.curva.ultimo
        assert perto(c.curva.extra["recebido"], 1.2, 1e-6) and c.curva.extra["pago"] == 0
        assert perto(c.curva.extra["fundingAno"], 0.0001 * 8760) and c.curva.extra["dentro"] is True
        assert c.curva.ops == 2 and c.curva.taxas == 0
    finally:
        com_taxas(g)
    # com taxas: a entrada custa as duas pernas (0,07% + 0,045% + 2 × 0,03% sobre metade cada)
    d, t0 = dados_sinteticos(3, {"BTC": lambda i: 0.0})
    c = F.Conta(cfg("btc1"), t0)
    c.passo(t0, d)
    k = 100 + 100 + 100 * (F.TAXA_SPOT + F.DESLIZE["BTC"]) + 100 * (F.TAXA_PERP + F.DESLIZE["BTC"])
    assert perto(c.pos.qs, 1000 / k, 1e-9) and perto(c.curva.taxas, 1000 - c.curva.ultimo, 1e-6)


def teste_liquidacao_na_conta():
    g = sem_taxas()
    try:
        # BTC 3× e a moeda pula 40% numa hora: liquida (máxima ≥ 131,7), o à vista fica e a posição é remontada
        d, t0 = dados_sinteticos(5, {"BTC": lambda i: 0.0}, {"BTC": lambda i: 100.0 if i < 2 else 140.0})
        c = F.Conta(cfg("btc3"), t0)
        c.passo(t0, d)
        for i in range(1, 4):
            c.passo(t0 + i * HORA, d)
        assert c.curva.n_liq == 1 and perto(c.curva.liq[0]["perda"], 250)
        assert perto(c.curva.ultimo, 7.5 * 140, 1e-9)  # US$ 1.050: só o à vista sobrou, e remontado
        assert perto(c.pos.qs, c.pos.qp) and c.pos.qp > 0
    finally:
        com_taxas(g)


def teste_seletiva():
    g = sem_taxas()
    try:
        # 0 por 3 dias; depois 0,002%/h (17,5% ao ano): entra quando a média de 72 h passa de 10% (a 42ª hora);
        # depois −0,002%/h: sai quando a média cai abaixo de 3%
        def taxa(i):
            return 0.0 if i < 0 else 0.00002 if i < 100 else -0.00002
        d, t0 = dados_sinteticos(200, {"BTC": taxa})
        c = F.Conta(cfg("seletiva"), t0)
        entrou = saiu = None
        c.passo(t0, d)
        for i in range(1, 200):
            c.passo(t0 + i * HORA, d)
            if c.dentro and entrou is None:
                entrou = i
            if entrou and not c.dentro and saiu is None:
                saiu = i
        assert entrou == 41, entrou  # horas 0..41 = 42 taxas de 0,002% em 72: 0,00117%/h = 10,2% ao ano
        # sai quando (72 − 2k)/72 × 17,5% < 3% (k horas negativas na janela): k = 30 dá 2,9% → hora 129
        assert saiu == 129, saiu
        assert c.curva.ops == 4 and perto(c.pos.caixa, c.curva.ultimo)
        assert c.curva.extra["dentro"] is False
    finally:
        com_taxas(g)


def teste_rodizio():
    g = sem_taxas()
    try:
        # BTC paga mais no começo; depois o ETH passa (troca só depois de 1 semana e com 5 pontos de diferença)
        taxas = {"BTC": lambda i: 0.00002, "ETH": lambda i: 0.00001 if i < 24 else 0.00004,
                 "HYPE": lambda i: 0.0, "SOL": lambda i: 0.0}
        d, t0 = dados_sinteticos(24 * 9, taxas, moedas=F.MOEDAS)
        c = F.Conta(cfg("rodizio"), t0)
        c.passo(t0, d)
        assert c.moeda == "BTC"
        trocou = None
        for i in range(1, 24 * 9):
            c.passo(t0 + i * HORA, d)
            if c.moeda == "ETH" and trocou is None:
                trocou = i
        assert trocou == 24 * 7, trocou  # o ETH passou na hora ~60, mas só depois de uma semana pode trocar
        assert c.curva.ops == 6  # montar (2) + desmontar (2) + montar (2)
    finally:
        com_taxas(g)


def teste_teste_no_passado():
    d, t0 = dados_sinteticos(24 * 5, {m: (lambda i: 0.00001) for m in F.MOEDAS}, moedas=F.MOEDAS)
    res = F.teste_no_passado(d, t0, t0 + 24 * 5 * HORA - HORA)
    assert set(res) == {v[0] for v in F.VERSOES}
    for r in res.values():
        assert r["serie"] and r["aproximado"] is False and r["de"] <= r["ate"]


def teste_pares():
    cli = falso.ClientePapelFalso()
    erros = []
    assert F.pares_spot(cli, lambda *_: None, erros) == {"BTC": "@142", "ETH": "@151", "SOL": "@156", "HYPE": "@107"}
    assert not erros
    # nomes reais diferentes: acha pelo token
    cli.spot_meta_e_contextos = lambda: [{"tokens": [{"name": "USDC", "index": 0}, {"name": "UBTC", "index": 197},
                                                     {"name": "HYPE", "index": 150}],
                                          "universe": [{"name": "@9", "tokens": [197, 0], "index": 9},
                                                       {"name": "@7", "tokens": [150, 0], "index": 7}]}, []]
    p = F.pares_spot(cli, lambda *_: None, erros)
    assert p["BTC"] == "@9" and p["HYPE"] == "@7" and p["ETH"] == "@151"
    cli.falhar.add("spotMetaAndAssetCtxs")
    del cli.spot_meta_e_contextos
    assert F.pares_spot(cli, lambda *_: None, erros) == F.PARES_PADRAO and erros


# ------------------------------------------------------------------------------------------- rodadas
def rodar(cli, pasta, quando):
    cli.agora = quando
    return papel.rodada(cli, pasta, quando, formas=["funding"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))


def ler(pasta):
    with open(os.path.join(pasta, "funding.json")) as f:
        return json.load(f)


def conferir(d):
    conferir_forma(d, "funding")
    assert d["forma"] == "funding" and d["nome"] == "Funding" and d["padrao"] == "btc1"
    assert {v["id"] for v in d["versoes"]} == {"btc1", "eth1", "hype1", "sol1", "btc3", "seletiva", "seletiva3", "rodizio", "entre"}
    for v in d["versoes"]:
        assert v["alav"] <= 3
        if v["id"] == "entre":
            assert v["historico"] is None and {"recebido", "pago", "longo", "curto", "diferencaAno"} <= set(v["aoVivo"]["extra"])
            continue
        for k in ("aoVivo", "historico"):
            c = v[k]
            assert c is not None, (v["id"], k)
            assert c["serie"][0][1] <= 1000.0 + 1e-9 and c["serie"][0][1] > 990, (v["id"], k, c["serie"][0])
            assert {"recebido", "pago", "base", "fundingAno", "moeda", "dentro"} <= set(c["extra"])
        assert v["historico"]["aproximado"] is False and "de" in v["historico"] and "ate" in v["historico"]
    assert d["avisos"] and d["comoFunciona"] and len(json.dumps(d)) < 400_000
    tipos = {e["tipo"] for e in d["eventos"]}
    assert "abriu" in tipos


def teste_rodadas():
    a = tempfile.mkdtemp(prefix="funding-a-")
    b = tempfile.mkdtemp(prefix="funding-b-")
    try:
        cli_a, cli_b = falso.ClientePapelFalso(), falso.ClientePapelFalso()
        t0 = cli_a.agora
        # A: a cada 6 h por 7 dias; B: as mesmas, mas pula 30 h no meio (o GitHub não rodou)
        pulos = {t0 + k * 6 * HORA for k in range(10, 15)}
        for k in range(29):
            q = t0 + k * 6 * HORA
            ind = rodar(cli_a, a, q)
            assert ind["formas"]["funding"]["ok"], ind["formas"]["funding"]
            if q not in pulos:
                rodar(cli_b, b, q)
            conferir(ler(a))
        da, db = ler(a), ler(b)
        assert ler(b)["agora"] == da["agora"]
        for va, vb in zip(da["versoes"], db["versoes"]):
            if va["id"] == "entre":
                continue  # a entre corretoras depende de quando a rodada lê o previsto (por isso é aproximada)
            assert va["aoVivo"] == vb["aoVivo"], va["id"]  # alcançar o tempo perdido dá o mesmo resultado
        assert [e["texto"] for e in da["eventos"] if e["versao"] != "entre"] == \
            [e["texto"] for e in db["eventos"] if e["versao"] != "entre"]
        btc = da["versoes"][0]["aoVivo"]
        assert len(btc["serie"]) >= 7 and btc["inicio"] == F.hora_de(t0 - F.FOLGA_MS)
        dias = [x for x, _ in btc["serie"]]
        assert dias == sorted(dias)
        # o histórico não é refeito a cada rodada (só depois de 7 dias)
        with open(os.path.join(a, "estado.json")) as f:
            est = json.load(f)["formas"]["funding"]
        assert est["hist"]["em"] == t0 + 28 * 6 * HORA  # refeito na rodada de 7 dias depois
        assert set(est["vivo"]) == {v[0] for v in F.VERSOES}
        # no mundo de mentira a seletiva sai (o BTC fica negativo) e recebe/paga por semana
        tipos = {(e["versao"], e["tipo"]) for e in da["eventos"]}
        assert ("seletiva", "saiu") in tipos and any(t == "recebeu" for _, t in tipos)
        # sem eventos de hora em hora: no máximo um de financiamento por versão por semana
        fin = [e for e in da["eventos"] if e["tipo"] in ("recebeu", "pagou")]
        assert len(fin) <= 8 * 2
        # a entre corretoras: só ao vivo, montou e desmontou no mundo de mentira, e anda com o dinheiro
        en = next(v for v in da["versoes"] if v["id"] == "entre")
        assert en["historico"] is None and en["aoVivo"]["aproximado"] and en["grupo"] == "Entre corretoras"
        assert ("entre", "entrou") in tipos and ("entre", "saiu") in tipos, sorted(t for t in tipos if t[0] == "entre")
        assert en["aoVivo"]["extra"]["recebido"] > 0

        # uma falha da API: ok false no índice, o funding.json da rodada boa fica
        antes = ler(a)
        cli_a.falhar.add("fundingHistory")
        ind = rodar(cli_a, a, t0 + 29 * 6 * HORA)
        assert ind["formas"]["funding"]["ok"] is False and "fundingHistory" in ind["formas"]["funding"]["erro"]
        assert ler(a) == antes
        # e o estado não andou: a próxima rodada alcança as horas
        cli_a.falhar.clear()
        ind = rodar(cli_a, a, t0 + 30 * 6 * HORA)
        assert ind["formas"]["funding"]["ok"]
        conferir(ler(a))
        # falha só no financiamento previsto: segue, com o erro anotado
        cli_a.falhar.add("predictedFundings")
        ind = rodar(cli_a, a, t0 + 31 * 6 * HORA)
        assert ind["formas"]["funding"]["ok"] and any("previsto" in x for x in ler(a)["rodada"]["erros"])
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


def teste_entre():
    """A entre corretoras à mão: diferença acima de 8% entra, ganha metade do dinheiro × diferença, sai abaixo de 2%."""
    ev = F.Eventos()
    en = F.Entre(0)
    leit = {"BTC": {"hl": 0.10, "binance": 0.0, "bybit": 0.05}, "ETH": {"hl": 0.02, "binance": 0.01}}
    en.passo(0, leit, ev)
    assert en.pos == {"moeda": "BTC", "longo": "binance", "curto": "hl", "desde": 0}
    custo = 500 * (F.ENTRE_TAXA["binance"] + F.ENTRE_TAXA["hl"] + 2 * F.DESLIZE["BTC"]) + F.ENTRE_PONTE
    assert perto(en.curva.ultimo, 1000 - custo)
    v0 = en.curva.ultimo
    en.passo(365 * DIA, leit, ev)  # um ano com 10% de diferença em metade do dinheiro
    assert perto(en.curva.ultimo, v0 + v0 / 2 * 0.10)
    v1 = en.curva.ultimo
    baixa = {"BTC": {"hl": 0.01, "binance": 0.0}}
    en.passo(366 * DIA, baixa, ev)  # a diferença caiu a 1% numa leitura só: a média (5,5%) ainda segura
    assert en.pos is not None
    en.passo(367 * DIA, baixa, ev)  # duas leituras baixas: sai
    assert en.pos is None and en.curva.ultimo < v1 + v1 / 2 * 0.10 * 2 / 365 + 1e-9
    assert [e["tipo"] for e in ev.para_json()][::-1] == ["entrou", "saiu"]


def teste_pouco_tempo():
    """Sem tempo na rodada, o teste no passado fica para depois (historico null) e o ao vivo anda."""
    pasta = tempfile.mkdtemp(prefix="funding-c-")
    try:
        cli = falso.ClientePapelFalso()
        cli.agora = falso.T0 + 32 * DIA
        papel.rodada(cli, pasta, cli.agora, formas=["funding"], prazo_min=4, exemplo=True, buscar_cdi=False,
                     log=papel.Log(quieto=True))
        d = ler(pasta)
        assert all(v["historico"] is None and v["aoVivo"] for v in d["versoes"])
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    teste_posicao()
    teste_liquidacao_e_reequilibrio()
    teste_conta_fixa()
    teste_liquidacao_na_conta()
    teste_seletiva()
    teste_rodizio()
    teste_teste_no_passado()
    teste_pares()
    teste_entre()
    teste_rodadas()
    teste_pouco_tempo()
    print("ok")
