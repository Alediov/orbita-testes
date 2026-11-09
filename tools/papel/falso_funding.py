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

    # ---------------------------------------------------------------- só observando (moedas fora da lista)
    # moedas de mentira com volume e financiamento próprios: algumas pagam muito há dias, outras pulam, uma tem pouco
    # volume (fica de fora pelo mínimo de US$ 5 mi)
    OUTRAS = {"AAA": (0.00006, 40e6), "BBB": (0.00004, 12e6), "CCC": (0.00009, 3e6), "DDD": (0.00002, 80e6),
              "EEE": (0.00005, 9e6), "FFF": (-0.00003, 20e6), "GGG": (0.000035, 6e6), "HHH": (0.00008, 15e6)}

    def _taxa_outra(self, m, t):
        nivel, _ = self.OUTRAS[m]
        r = random.Random(f"{m}:{t // (2 * 86_400_000)}")  # semente em texto: a mesma em todo processo
        return round(nivel * (r.random() * 2.2 - 0.4) + random.Random(f"{m}:{t}").gauss(0, 0.000005), 8)

    def meta_e_contextos(self):
        meta, ctxs = super().meta_e_contextos()
        meta = {"universe": list(meta["universe"]) + [{"name": m, "szDecimals": 1, "maxLeverage": 5} for m in self.OUTRAS]}
        agora = (self.agora // HORA) * HORA
        ctxs = list(ctxs) + [{"funding": f"{self._taxa_outra(m, agora):.8f}", "markPx": "1.0", "oraclePx": "1.0",
                              "openInterest": "2000000", "premium": "0.0", "dayNtlVlm": f"{v:.0f}"}
                             for m, (_, v) in self.OUTRAS.items()]
        return [meta, ctxs]

    def financiamento(self, moeda, ini, fim):
        if moeda not in self.OUTRAS:
            return super().financiamento(moeda, ini, fim)
        self._contar("fundingHistory")
        fim = min(fim, self.agora)
        t = (int(ini) // HORA + 1) * HORA
        out = []
        while t <= fim:
            out.append({"coin": moeda, "fundingRate": f"{self._taxa_outra(moeda, t):.8f}", "premium": "0.0", "time": t + 40})
            t += HORA
        return out
