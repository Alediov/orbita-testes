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
    assert s["morta"] and s["buf"]["liq"][0]["perda"] == 40.0 and r.patrimonio(s, 65) == 0
    # vendida: liquida na alta
    s3 = r.novo(0)
    s3.update(ini=True, fase="esperando", C=40.0, p=-1.0, e=100.0)
    s3["fase"] = "x"  # sem ordens nem ciclo novo
    lq = (40 + 100) / (1 + 1 / 80)
    assert perto(r.liq(s3), lq)
    r.vela(s3, vela(0, 120, 140, 120, 130))
    assert s3["morta"]


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
        assert {"comprado", "caixa", "degrausExecutados", "precoMedio", "foraDaGrade"} <= set(c["extra"]), onde
    if c.get("acerto") is not None:
        assert 0 <= c["acerto"] <= 1


def conferir_forma(d):
    for k in ("v", "forma", "nome", "agora", "frase", "comoFunciona", "padrao", "versoes", "eventos", "itens",
              "avisos", "config", "rodada"):
        assert k in d, f"falta {k}"
    assert d["forma"] == "robos" and d["nome"] == "Robôs"
    ids = [v["id"] for v in d["versoes"]]
    assert ids == ["gbtc10", "geth10", "gbtc20r", "gneutra1", "gneutra3", "dca", "dcaqueda", "dcam1", "dcam3"]
    assert d["padrao"] in ids
    for v in d["versoes"]:
        assert v["risco"] in RISCOS and v["nome"] and v["frase"] and 1 <= v["alav"] <= 3
        conferir_conta(v["aoVivo"], v["id"] + "/aoVivo")
        conferir_conta(v["historico"], v["id"] + "/historico")
        if v["historico"]:
            assert v["historico"]["aproximado"] is False and v["historico"]["de"] <= v["historico"]["ate"]
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


if __name__ == "__main__":
    teste_grade_a_mao()
    teste_caminho_pessimista()
    teste_liquidacao()
    teste_dca()
    teste_martingale()
    teste_pares()
    teste_rodadas()
    teste_tempo_do_historico()
    print("ok")
