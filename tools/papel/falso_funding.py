"""Mercado de MENTIRA do funding (sem rede; semente fixa): troca o financiamento do mundo (tools/mercado/falso.py, que
é ruído em volta de 8,8% ao ano, igual para as 4 moedas) por regimes de alguns dias por moeda, como na vida real:
semanas no piso de ~11% ao ano (0,00125% por hora), trechos animados de 25–45% ao ano, e trechos NEGATIVOS, em que o
vendido paga. Assim a seletiva entra e sai e o rodízio troca de moeda. Mesmas horas e mesmo tamanho; recalculado
sempre do zero pela semente (chamar de novo dá o mesmo). Nada aqui é dado real."""
from __future__ import annotations

import random

HORA = 3_600_000

# por moeda: (taxa por hora do regime, peso no sorteio)
REGIMES = {
    "BTC": [(0.0000125, 5), (0.000028, 2), (0.000004, 2), (-0.000010, 1), (0.000045, 1)],
    "ETH": [(0.0000125, 5), (0.000022, 2), (0.000002, 2), (-0.000012, 1), (0.000040, 1)],
    "SOL": [(0.0000125, 4), (0.000030, 2), (-0.000015, 2), (0.000050, 1), (0.000005, 1)],
    "HYPE": [(0.0000125, 3), (0.000040, 3), (-0.000020, 1), (0.000070, 1), (0.000008, 1)],
}

# escolhidas para o exemplo mostrar de tudo: o BTC fica negativo no passado e de novo no ao vivo (a seletiva sai e
# volta), e o HYPE e o SOL se revezam no topo (o rodízio troca)
SEMENTES = {"BTC": 1104, "ETH": 1101, "HYPE": 1102, "SOL": 1103}


def serie_falsa(horas, moeda, semente):
    """[(t, taxa)] por regimes de 2 a 6 dias, com um pouco de ruído (a taxa da HL anda em degraus pequenos)."""
    r = random.Random(semente)
    regs = REGIMES.get(moeda) or REGIMES["BTC"]
    out, falta, nivel = [], 0, 0.0000125
    for t in horas:
        if falta <= 0:
            nivel = r.choices([x for x, _ in regs], [p for _, p in regs])[0]
            falta = r.randint(48, 144)
        falta -= 1
        out.append((t, round(nivel + r.gauss(0, 0.000004), 8)))
    return out


class Falso:
    def preparar(self):
        novo = {}
        for m, lista in self.mundo.funding.items():
            novo[m] = serie_falsa([t for t, _ in lista], m, SEMENTES.get(m, 1100))
        self.mundo.funding = novo
