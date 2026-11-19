"""python3 tools/papel/teste_previsao_evolucao.py — a Evolução das Previsões (previsao_evolucao.py), sem rede: um
observatório inventado para as contas à mão (a entrada, a resolução, o teto de abertas, a categoria) e o motor comum
rodando por cima dele (o laboratório e a liga)."""
from __future__ import annotations

import datetime as dt
import os
import random
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import previsao_evolucao as PE  # noqa: E402
from conta import CAPITAL, DIA  # noqa: E402

D0 = dt.date(2026, 6, 1)
dia = lambda n: (D0 + dt.timedelta(days=n)).isoformat()  # noqa: E731
MEIO_DIA = int(dt.datetime(D0.year, D0.month, D0.day, 15, tzinfo=dt.timezone.utc).timestamp() * 1000)  # 12h de Brasília


def ok(c, msg=""):
    if not c:
        raise AssertionError(msg)


def mercado(n_fim, p_sim, o, cat="Esportes", vol=10_000, ev=None):
    """Um mercado que acaba no dia `n_fim` (meio-dia), com o "Sim" a `p_sim` nos 30 dias antes e o resultado `o`."""
    fim = MEIO_DIA + n_fim * DIA
    return {"fim": fim, "o": o, "cat": cat, "vol": vol, "pts": [int(p_sim * 1000)] * 31, "ev": ev or f"e{n_fim}{cat}{p_sim}",
            "q": "teste", "ult": int(p_sim * 1000)}


def teste_contas_a_mao():
    est = {"cal": {"mercados": {
        "a": mercado(20, 0.92, 1),                  # favorito no Sim, ganha
        "b": mercado(25, 0.06, 0),                  # favorito no Não (94%), ganha
        "c": mercado(30, 0.91, 0),                  # favorito no Sim, perde
        "d": mercado(35, 0.50, 1),                  # nenhum lado na faixa
        "e": mercado(40, 0.93, 1, cat="Política"),  # outra categoria
    }}}
    D = PE.Dados(est)
    ok(len(D.merc) == 5 and D.primeiro == dia(20 - 30), D.primeiro)
    g = PE.Definicao().genes_controle()
    r = PE.simular(D, g, dia(0), dia(45))
    ok(r["ops"] == 4, r)                                   # a, b, c, e
    ok(r["resolvidas"] == 4 and r["acertos"] == 3, r)
    # a conta: 4 × US$ 20 a (p + 1 centavo); as ganhas pagam US$ 1 por cota
    ganho = 20 / 0.93 + 20 / 0.95 + 20 / 0.94 - 4 * 20
    ok(abs(r["serie"][-1][1] - (CAPITAL + ganho)) < 0.02, (r["serie"][-1], CAPITAL + ganho))
    # entra faltando 7 dias: no dia 13 a de 20 está aberta e marcada pelo preço do dia
    linha = dict(r["serie"])
    ok(linha[dia(12)] == CAPITAL and linha[dia(13)] < CAPITAL, (linha[dia(12)], linha[dia(13)]))
    # só Política
    r2 = PE.simular(D, dict(g, cat="Política"), dia(0), dia(45))
    ok(r2["ops"] == 1 and r2["acertos"] == 1, r2)
    # o teto de abertas: 12 favoritos que acabam no mesmo dia, no máximo 10 ao mesmo tempo
    muitos = {"cal": {"mercados": {f"x{i}": mercado(20, 0.95, 1, ev=f"x{i}") for i in range(12)}}}
    r3 = PE.simular(PE.Dados(muitos), dict(g, max=10), dia(0), dia(25))
    ok(r3["ops"] == 10, r3)
    # o azarão compra o lado barato (2% a 10%): o Não de a (8%), o Sim de b (6%), o Não de c (9%) e o Não de e (7%)
    r4 = PE.simular(D, dict(g, lado="az", faixa="2-10", dias=30), dia(0), dia(45))
    ok(r4["ops"] == 4 and r4["acertos"] == 1, r4)          # ganha só em c (o Não de 9% venceu)
    # volume mínimo
    ok(PE.simular(D, dict(g, vol=20000), dia(0), dia(45))["ops"] == 0)
    # o mesmo evento conta uma vez (um_por_evento)
    est["cal"]["mercados"]["a2"] = dict(mercado(20, 0.92, 1), ev=est["cal"]["mercados"]["a"]["ev"], vol=5000)
    ok(PE.simular(PE.Dados(est), g, dia(0), dia(45))["ops"] == 4)
    print("teste_contas_a_mao: ok")


def teste_motor():
    rng = random.Random(7)
    merc = {}
    for i in range(160):
        p = rng.choice([0.03, 0.07, 0.5, 0.88, 0.92, 0.96])
        o = 1 if rng.random() < p else 0
        merc[f"m{i}"] = mercado(10 + i // 2, p, o, cat=rng.choice(PE.CATS), vol=rng.choice([6000, 30000, 200000]),
                                ev=f"ev{i}")
    est = {"cal": {"mercados": merc}}

    class Ctx:
        exemplo, ref = True, {}

        @staticmethod
        def log(*a):
            pass

    agora = MEIO_DIA + 95 * DIA
    for k in range(0, 40, 1):
        out = PE.avancar(Ctx, est, agora + k * DIA)
    ok(out and out["formas"][0]["id"] == "previsao", out and out.get("formas"))
    e = out["formas"][0]["especies"][0]
    ok(e["id"] == "colheita" and e["lab"] and e["liga"], list(e))
    ok(e["controle"]["nome"] == "Favorito ≥ 90%" if isinstance(e["controle"], dict) and "nome" in e["controle"] else True)
    ok(out["regras"].get("mercados") == 160, out["regras"])
    ok(PE.avancar(Ctx, {"cal": {"mercados": dict(list(merc.items())[:10])}}, agora) is None, "com poucos mercados, nada")
    print("teste_motor: ok")


if __name__ == "__main__":
    teste_contas_a_mao()
    teste_motor()
