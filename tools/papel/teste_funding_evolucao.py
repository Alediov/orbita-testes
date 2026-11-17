"""python3 tools/papel/teste_funding_evolucao.py — a Evolução do Funding (funding_evolucao.py), sem rede: um banco de
dias inventado para as contas à mão, o banco escrito pelas velas e taxas de hora em hora e, depois, o mercado de
mentira rodando dia a dia (o laboratório e a liga)."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)

import evolucao_series as ES  # noqa: E402
import falso  # noqa: E402
import funding as F  # noqa: E402
import funding_evolucao as FE  # noqa: E402
import papel  # noqa: E402
from conta import dia_de  # noqa: E402

HORA, DIA = falso.HORA, falso.DIA
D0 = dt.date(2026, 6, 1)
dia = lambda n: (D0 + dt.timedelta(days=n)).isoformat()  # noqa: E731
MEIA_NOITE = int(dt.datetime(D0.year, D0.month, D0.day, 3, tzinfo=dt.timezone.utc).timestamp() * 1000)  # 0h de Brasília
N = 120


def ok(c, msg=""):
    if not c:
        raise AssertionError(msg)


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol


def banco_a_mao():
    """Preços parados (BTC 100, ETH 10, SOL 5, HYPE 2). Financiamento por dia: BTC 0,03% (≈ 11% ao ano); ETH 0,06% nos
    dias 40 a 79 e 0,005% fora; SOL sempre negativo; HYPE 0,02% e a máxima de +40% no dia 50 (liquida o 3×)."""
    def moeda(p, f, h=lambda n: 1.0):
        return {"d0": dia(0), "f": [f(n) for n in range(N + 1)], "p": [p] * (N + 1), "h": [p * h(n) for n in range(N + 1)],
                "s": [p] * (N + 1)}
    return {"bancoEv": {"v": FE.BANCO_V, "ate": dia(N), "parcial": None, "lev": {"BTC": 40, "ETH": 25, "SOL": 20, "HYPE": 10},
                        "moedas": {"BTC": moeda(100.0, lambda n: 0.0003),
                                   "ETH": moeda(10.0, lambda n: 0.0006 if 40 <= n < 80 else 0.00005),
                                   "SOL": moeda(5.0, lambda n: -0.0002),
                                   "HYPE": moeda(2.0, lambda n: 0.0002, lambda n: 1.4 if n == 50 else 1.0)}},
            "aave": {"serie": {}, "atual": 0.0365}}


def teste_contas():
    est = banco_a_mao()
    D = FE.Dados(est, F)
    df = FE.Definicao()
    ctrl = df.genes_controle()
    g = lambda **k: FE.reparar(FE.ESP, {**ctrl, **k})  # noqa: E731
    ok(D.tem_dados and D.primeiro == dia(FE.MEDIA_MAX))
    ok(ctrl == {"moedas": "BTC", "alav": 1, "regra": "fixa", "media": 3, "entra": 0.1, "folga": 0.07, "troca": 7, "dif": 0.05,
                "caixa": False}, ctrl)
    ok(df.descrever(ctrl) == "BTC 1× · sempre dentro", df.descrever(ctrl))
    ok(df.descrever(g(moedas="todas", alav=3, regra="seletiva", caixa=True))
       == "Rodízio 3× · entra a 10%, sai a 3% · caixa na Aave · média de 3 dias", df.descrever(g(moedas="todas", alav=3, regra="seletiva", caixa=True)))
    ok([de for de, _ in df.sementes()] == ["eth1", "hype1", "sol1", "btc3", "seletiva", "seletiva3", "rodizio", "seletivaC"])
    ok(g(alav=9)["alav"] == 3 and g(entra=0.2)["entra"] == 0.1, "a alavancagem não passa de 3× e o gene que não vale fica no neutro")
    ok(perto(D.media("BTC", FE.ordinal(dia(10)), 3), 0.0003 / 24) and D.media("BTC", FE.ordinal(dia(-5)), 3) is None)

    # BTC 1×: monta no fim do 1º dia e recebe 0,03% por dia sobre a metade vendida nos 30 seguintes; a entrada custa as taxas
    c = FE.simular(D, ctrl, dia(20), dia(50))
    cs, cp = F.custos("BTC")
    entrada = 500 * (cs + cp)
    ok(c["ops"] == 1 and c["montou"] and c["membros"] == ["BTC 1×"] and c["nLiq"] == 0)
    ok(perto(c["custos"], entrada, 0.02) and perto(c["serie"][-1][1], 1000 - entrada + 30 * 0.0003 * 500, 0.1), (c["custos"], c["serie"][-1]))
    # 3×: três quartos vendidos
    c3 = FE.simular(D, g(alav=3), dia(20), dia(50))
    ok(perto(c3["serie"][-1][1], 1000 - 750 * (cs + cp) + 30 * 0.0003 * 750, 0.15), c3["serie"][-1])
    # o financiamento negativo: o vendido paga
    ok(FE.simular(D, g(moedas="SOL"), dia(20), dia(50))["retorno"] < -0.004)
    # a seletiva no ETH: entra quando a média de 3 dias passa de 10% ao ano (0,06% ao dia = 22%), sai abaixo de 3%
    s = FE.simular(D, g(moedas="ETH", regra="seletiva"), dia(20), dia(N))
    v = dict(map(tuple, s["serie"]))
    ok(s["ops"] == 2 and s["membros"] == [] and v[dia(39)] == 1000.0 and v[dia(41)] < 1000 < v[dia(79)], (s["ops"], v[dia(41)], v[dia(79)]))
    ok(v[dia(N)] == v[dia(85)], "fora, o dinheiro fica parado")
    # com o caixa na Aave: paga a ida e rende 3,65% ao ano enquanto espera
    sc = FE.simular(D, g(moedas="ETH", regra="seletiva", caixa=True), dia(85), dia(N))
    ok(sc["membros"] == ["Aave (dólar)"] and perto(sc["serie"][-1][1], (1000 - F.custo_caixa(1000, True)) * 1.0365 ** (35 / 365), 0.05), sc["serie"][-1])
    # a média de 1 dia entra antes da de 14
    v1 = dict(map(tuple, FE.simular(D, g(moedas="ETH", regra="seletiva", media=1), dia(20), dia(60))["serie"]))
    v14 = dict(map(tuple, FE.simular(D, g(moedas="ETH", regra="seletiva", media=14), dia(20), dia(60))["serie"]))
    ok(v1[dia(40)] < 1000 and v14[dia(44)] == 1000.0 and v14[dia(60)] < v1[dia(60)])
    # o rodízio: começa no BTC (0,03% > 0,02% > 0,01%), vai para o ETH quando ele paga mais e volta depois
    r = FE.simular(D, g(moedas="todas"), dia(20), dia(N))
    ok(r["ops"] == 3 and r["membros"] == ["BTC 1×"], (r["ops"], r["membros"]))
    r2 = FE.simular(D, g(moedas="todas", dif=0.2), dia(20), dia(N))
    ok(r2["ops"] == 1, "0,03 ponto por dia a mais é 11% ao ano: com a diferença de 20%, não troca")
    # a liquidação: o HYPE sobe 40% num dia; o 3× perde a margem e remonta; o 1× só reequilibra
    h3, h1 = FE.simular(D, g(moedas="HYPE", alav=3), dia(20), dia(60)), FE.simular(D, g(moedas="HYPE"), dia(20), dia(60))
    ok(h3["nLiq"] == 1 and h1["nLiq"] == 0 and h3["retorno"] < -0.2 and h3["membros"] == ["HYPE 3×"], (h3["nLiq"], h3["retorno"]))
    # o dia de hoje (incompleto) não decide
    est2 = banco_a_mao()
    est2["bancoEv"]["parcial"] = dia(40)
    p = FE.simular(FE.Dados(est2, F), g(moedas="ETH", regra="seletiva", media=1), dia(20), dia(40))
    ok(p["ops"] == 0 and v1[dia(40)] < 1000, "no dia parcial a regra espera")
    ok(ES.nota_lab(FE.simular(D, ctrl, D.primeiro, dia(N))) is not None)


def teste_banco():
    # 3 dias inteiros + 5 horas de hoje, de hora em hora: a taxa paga à meia-noite é do dia que acabou
    t0 = MEIA_NOITE
    horas = range(1, 3 * 24 + 6)
    fund = [{"time": t0 + k * HORA, "fundingRate": "0.00001"} for k in horas]
    perp = [{"t": t0 + (k - 1) * HORA, "h": str(100 + k + 0.5), "c": str(100 + k)} for k in horas]
    spot = [{"t": t0 + (k - 1) * HORA, "h": "0", "c": str(99 + k)} for k in horas]
    d = F.Dados({"BTC": perp}, {"BTC": spot}, {"BTC": fund}, {"BTC": 40})
    est = {}
    agora = t0 + (3 * 24 + 5) * HORA + 60_000
    ok(FE.atualizar_banco(est, d, agora) == 4)
    b = est["bancoEv"]
    x = b["moedas"]["BTC"]
    ok(x["d0"] == dia(0) and len(x["f"]) == 4 and perto(x["f"][0], 0.00024) and perto(x["f"][3], 0.00005), x["f"])
    ok(x["p"][0] == 124.0 and x["h"][0] == 124.5 and x["s"][0] == 123.0 and x["p"][3] == 177.0, (x["p"], x["h"], x["s"]))
    ok(b["parcial"] == dia(3) == b["ate"] and b["lev"]["BTC"] == 40 and FE.precisa_semear(est))
    # a rodada seguinte só tem os últimos dias: o dia inteiro troca o parcial; o começo incompleto da janela não estraga
    fund2 = [{"time": t0 + k * HORA, "fundingRate": "0.00002"} for k in range(2 * 24 + 12, 4 * 24 + 3)]
    perp2 = [{"t": t0 + (k - 1) * HORA, "h": "200", "c": "150"} for k in range(2 * 24 + 12, 4 * 24 + 3)]
    d2 = F.Dados({"BTC": perp2}, {}, {"BTC": fund2}, {})
    FE.atualizar_banco(est, d2, t0 + (4 * 24 + 2) * HORA + 60_000)
    ok(len(x["f"]) == 5 and perto(x["f"][2], 0.00024) and perto(x["f"][3], 0.00048) and perto(x["f"][4], 0.00004), x["f"])
    ok(x["s"][3] == 150.0 and b["parcial"] == dia(4), "sem o à vista, vale o perpétuo")
    # MAX_DIAS
    est3 = {"bancoEv": {"v": FE.BANCO_V, "moedas": {"BTC": {"d0": dia(-400), "f": [0.0] * 401, "p": [1.0] * 401, "h": [1.0] * 401,
                                                           "s": [1.0] * 401}}, "ate": None, "parcial": None}}
    ok(not FE.precisa_semear(est3))
    FE.atualizar_banco(est3, d, agora)
    y = est3["bancoEv"]["moedas"]["BTC"]
    ok(len(y["f"]) == FE.MAX_DIAS == len(y["p"]) and y["d0"] == dia(3 - FE.MAX_DIAS + 1) and y["p"][-1] == 177.0, (len(y["f"]), y["d0"]))


def teste_mercado_de_mentira():
    pasta = tempfile.mkdtemp()
    try:
        cli = falso.ClientePapelFalso()
        t0, log = cli.agora, papel.Log(quieto=True)
        d = None
        for k in range(100):
            cli.agora = t0 + k * 6 * HORA
            papel.rodada(cli, pasta, cli.agora, formas=["funding"], exemplo=True, buscar_cdi=False, log=log)
            with open(os.path.join(pasta, "funding.json")) as f:
                d = json.load(f)
            ok(not any("evolu" in e for e in d.get("erros") or []), d.get("erros"))
        with open(os.path.join(pasta, "estado.json")) as f:
            est = json.load(f)["formas"]["funding"]
        b = est["bancoEv"]
        ok(set(b["moedas"]) == set(FE.MOEDAS) and b["ate"] == dia_de(cli.agora) == b["parcial"])
        n = len(b["moedas"]["BTC"]["f"])
        ok(n >= 50 and all(len(x[c]) == n for x in b["moedas"].values() for c in "fphs") and len(json.dumps(b)) < 30 * n * 16, n)
        ev = d["evolucao"]
        ok(ev["forma"] == "evolucao" and ev["formas"][0]["id"] == "funding" and ev["regras"]["alavMax"] == 3)
        sp = ev["formas"][0]["especies"][0]
        P = ES.parametros(True)
        ok(sp["id"] == "carry" and sp["controle"]["nome"] == "BTC 1×" and len(sp["genes"]) == 9)
        liga, lab = sp["liga"], sp["lab"]
        ok(len(liga["pop"]) == P["POP_LIGA"] and liga["controle"]["aoVivo"]["serie"] and len(liga["semanas"]) >= 3, len(liga["semanas"]))
        ok(lab["g"] >= 20 and len(lab["pop"]) == P["POP"] and lab["controle"]["nota"] is not None, lab["g"])
        for x in liga["pop"] + [liga["controle"]]:
            a = x["aoVivo"]
            ok({"retorno", "piorQueda", "ops", "membros", "custos", "nLiq"} <= set(a) and x["descricao"], x["nome"])
            ok(x["genes"] == FE.reparar(FE.ESP, x["genes"]) and 1 <= x["genes"]["alav"] <= 3, x["nome"])
        ok(liga["controle"]["aoVivo"]["membros"] == ["BTC 1×"] and liga["controle"]["aoVivo"].get("metricas") is not None)
        # o controle refeito por dia anda perto do BTC 1× de hora em hora (o mesmo período: a liga começou na 1ª rodada)
        vivo = next(v for v in d["versoes"] if v["id"] == "btc1")["aoVivo"]
        ok(abs(vivo["retorno"] - liga["controle"]["aoVivo"]["retorno"]) < 0.004, (vivo["retorno"], liga["controle"]["aoVivo"]["retorno"]))
        ok(len(json.dumps(ev)) < 120_000, len(json.dumps(ev)))
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    teste_contas()
    teste_banco()
    teste_mercado_de_mentira()
    print("teste_funding_evolucao: ok")
