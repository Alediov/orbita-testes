"""python3 tools/papel/teste_opcoes_evolucao.py — a Evolução das Opções (opcoes_evolucao.py), sem rede: o banco de
horas (crescer, trocar a hora em curso, o buraco, o corte), o simulador de 4 em 4 h contra o teste no passado de hora em
hora (a mesma `Conta`), os genes chegando à conta (a recompra, o prêmio caro, a moeda) e o motor comum por cima."""
from __future__ import annotations

import math
import os
import random
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import opcoes as O  # noqa: E402
import opcoes_evolucao as OE  # noqa: E402
from conta import DIA, HORA, dia_de  # noqa: E402

AGORA = 1795000000000 // HORA * HORA


def ok(c, msg=""):
    if not c:
        raise AssertionError(msg)


def mercado(seed=2, dias=200, vol=0.55, dvol=0.6):
    h0 = AGORA - dias * DIA
    pr, dv = {}, {}
    for m, s0 in (("BTC", 90000.0), ("ETH", 3000.0)):
        rng, s, pm, dm = random.Random(seed), s0, {}, {}
        for i in range(dias * 24):
            s *= math.exp(rng.gauss(0, vol / math.sqrt(24 * 365)))
            pm[h0 + i * HORA], dm[h0 + i * HORA] = s, dvol
        pr[m], dv[m] = pm, dm
    return pr, dv


def teste_banco():
    est = {}
    pr, dv = mercado(dias=60)
    ok(OE.atualizar_banco(est, pr, dv, AGORA) == 2 * 60 * 24)
    ok(not OE.precisa_semear(est), "60 dias passam do mínimo (45)")
    u = OE.ultima_hora(est, "BTC")
    # a hora em curso muda e uma hora nova entra
    n = OE.atualizar_banco(est, {"BTC": {u: 1.0, u + HORA: 2.0}}, {"BTC": {u + HORA: 0.7}}, AGORA + 2 * HORA)
    bm = est["bancoEv"]["moedas"]["BTC"]
    ok(n == 1 and bm["p"][-2] == 1.0 and bm["p"][-1] == 2.0 and bm["v"][-1] == 0.7, (n, bm["p"][-2:], bm["v"][-2:]))
    # um buraco de 3 horas fica com o preço de antes
    OE.atualizar_banco(est, {"BTC": {u + 5 * HORA: 3.0}}, {}, AGORA + 6 * HORA)
    ok(bm["p"][-4:] == [2.0, 2.0, 2.0, 3.0], bm["p"][-4:])
    # o corte em MAX_HORAS
    est2 = {}
    pr, dv = mercado(dias=210)
    OE.atualizar_banco(est2, pr, dv, AGORA)
    ok(len(est2["bancoEv"]["moedas"]["BTC"]["p"]) == OE.MAX_HORAS)
    ok(not OE.precisa_semear(est2))
    print("teste_banco: ok")


def teste_simulador():
    pr, dv = mercado(seed=3)
    est = {}
    OE.atualizar_banco(est, pr, dv, AGORA)
    D = OE.Dados(est, O)
    ok(D.tem_dados and D.primeiro == dia_de(AGORA - 200 * DIA + OE.FOLGA_INICIO * DIA), D.primeiro)
    hoje = dia_de(AGORA)
    g = OE.Definicao().genes_controle()
    r = OE.simular(D, g, D.primeiro, hoje)
    ok(r["montou"] and r["ops"] >= 20 and r["serie"][0][0] == D.primeiro and r["serie"][-1][0] == hoje, (r["ops"], r["serie"][:1]))
    # de 4 em 4 h ≈ o teste no passado de hora em hora (a mesma Conta, o mesmo mercado)
    res, _ = O.teste_no_passado(O.MercadoHist(pr, dv), OE._ms_do_dia(D.primeiro), OE.ultima_hora(est, "BTC"), [O.cfg_de("put15")])
    ok(abs(r["retorno"] - res["put15"]["retorno"]) < 0.01, (r["retorno"], res["put15"]["retorno"]))
    # os genes chegam à conta
    eth = OE.simular(D, dict(g, moeda="ETH"), D.primeiro, hoje)
    ok(eth["retorno"] != r["retorno"])
    caro = OE.simular(D, dict(g, caro=1.35), D.primeiro, hoje)   # DVOL 0,6 ÷ realizada ~0,55 = 1,09: nunca caro
    ok(caro["ops"] == 0 and not caro["montou"], caro["ops"])
    barato = OE.simular(D, dict(g, caro=1.0 + 1e-9), D.primeiro, hoje)
    ok(barato["ops"] > 0)
    stop = OE.simular(D, dict(g, delta=0.4, stop=2), D.primeiro, hoje)
    ok(stop["recompras"] > 0, stop)
    mes = OE.simular(D, dict(g, prazo="mes"), D.primeiro, hoje)
    ok(0 < mes["ops"] < r["ops"], (mes["ops"], r["ops"]))
    print("teste_simulador: ok")


def teste_motor():
    pr, dv = mercado(seed=5)

    class Ctx:
        exemplo, ref = True, {}

        @staticmethod
        def log(*a):
            pass

    est = {}
    corte = AGORA - 40 * DIA
    um = lambda d, a, b: {m: {h: v for h, v in x.items() if a <= h <= b} for m, x in d.items()}  # noqa: E731
    out = OE.avancar(Ctx, est, O, um(pr, 0, corte), um(dv, 0, corte), corte)
    for k in range(1, 41):
        t = corte + k * DIA
        out = OE.avancar(Ctx, est, O, um(pr, t - 31 * DIA, t), um(dv, t - 2 * DIA, t), t)
    ok(out and out["formas"][0]["id"] == "opcoes", out and out.get("formas"))
    e = out["formas"][0]["especies"][0]
    ok(e["id"] == "premio" and e["lab"] and e["liga"], list(e))
    ok(out["regras"]["passoHoras"] == 4)
    ok(OE.avancar(Ctx, {}, O, um(pr, AGORA - 10 * DIA, AGORA), um(dv, AGORA - 10 * DIA, AGORA), AGORA) is None,
       "sem banco suficiente, nada")
    print("teste_motor: ok")


if __name__ == "__main__":
    teste_banco()
    teste_simulador()
    teste_motor()
