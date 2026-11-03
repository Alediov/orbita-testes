"""Mercado de MENTIRA para os testes e o resumo de exemplo (sem rede): preços minuto a minuto por passeio aleatório
com semente fixa, carteiras com estilos diferentes (as que devem passar nos filtros e as que não) e um cliente com a
mesma interface do `hl.Cliente`, que devolve tudo no formato da API da Hyperliquid (exemplos/ tem uma amostra de cada
resposta, escrita à mão a partir da documentação). Nada aqui é dado real.
"""
from __future__ import annotations

import datetime as dt
import math
import random

import hl

MIN = 60_000
HORA = 3_600_000
DIA = 86_400_000
T0 = int(dt.datetime(2026, 9, 20, tzinfo=dt.timezone.utc).timestamp() * 1000)
DIAS = 60
INICIAL = {"BTC": 62000.0, "ETH": 2450.0, "SOL": 148.0, "HYPE": 31.0}
VOL = {"BTC": 0.0007, "ETH": 0.0009, "SOL": 0.0013, "HYPE": 0.0016}
MAX_LEV = {"BTC": 40, "ETH": 25, "SOL": 20, "HYPE": 10}


def endereco(n):
    return "0x" + f"{n:02x}" * 20


class Mundo:
    def __init__(self, semente=7):
        r = random.Random(semente)
        self.n = DIAS * 1440
        self.p = {}
        for m, p0 in INICIAL.items():
            xs, x, deriva = [], p0, 0.0
            for i in range(self.n + 1):
                if i % 4320 == 0:  # um "regime" a cada 3 dias
                    deriva = r.gauss(0, VOL[m] * 0.06)
                x *= math.exp(deriva + r.gauss(0, VOL[m]))
                xs.append(x)
            self.p[m] = xs
        self.funding = {m: [(T0 + h * HORA, round(r.gauss(0.00001, 0.00002), 8)) for h in range(DIAS * 24)] for m in INICIAL}
        self.carteiras = {}
        self._criar(r)

    def px(self, m, t):
        i = max(0, min(self.n, (t - T0) // MIN))
        return self.p[m][i]

    # ------------------------------------------------------------------ carteiras
    def _criar(self, r):
        perfis = [
            # (n, estilo, moedas, conta, papel, ranking: mês pnl, roi, total pnl, vlm mês)
            (1, "tendencia", ["BTC", "ETH"], 250_000, "user", 31_000, 0.14, 410_000, 9e6),
            (2, "robo", ["SOL", "HYPE"], 80_000, "user", 12_500, 0.18, 95_000, 4e6),      # robô de regra clara
            (3, "contra", ["ETH"], 1_200_000, "user", 64_000, 0.05, 2_300_000, 3e7),
            (4, "tendencia", ["BTC", "SOL", "HYPE"], 140_000, "user", 9_000, 0.07, 160_000, 6e6),
            (5, "contra", ["BTC", "HYPE"], 60_000, "user", 7_200, 0.13, 52_000, 2e6),
            (6, "escalpo", ["BTC"], 300_000, "user", 40_000, 0.15, 900_000, 5e7),         # robô de velocidade
            (7, "tendencia", ["ETH"], 5_000_000, "vault", 90_000, 0.02, 8_000_000, 2e8),  # cofre
            (8, "tendencia", ["SOL"], 40_000, "user", -3_000, -0.07, 20_000, 1e6),        # prejuízo no mês
            (9, "tendencia", ["BTC"], 900_000, "user", 50_000, 0.06, 3_000_000, 9e8),      # formador de mercado
            (10, "tendencia", ["ETH"], 3_000, "user", 900, 0.4, 2_000, 1e5),              # conta pequena
            (11, "segura", ["SOL", "HYPE"], 120_000, "user", 9_500, 0.08, 70_000, 5e6),   # "quase nunca perde"
        ]
        for n, estilo, moedas, conta, papel, pm, roi, pt, vlm in perfis:
            e = endereco(n)
            if estilo == "robo":
                fills, eq = self._robo(moedas, conta)
            else:  # 1 e 4: gente (dorme, preço redondo nas ordens limite); 3 e 5: ambíguas
                fills, eq = self._operar(random.Random(n * 101), estilo, moedas, conta, passivo=0.7 if n in (1, 4) else 0.15,
                                         horas=(9, 23) if n in (1, 4) else None, redondo=n in (1, 4))
            self.carteiras[e] = {"fills": fills, "eq": eq, "conta": conta, "papel": papel,
                                 "ranking": {"ethAddress": e, "accountValue": str(conta), "displayName": "HLP Vault" if papel == "vault" else None, "prize": 0,
                                             "windowPerformances": [["day", {"pnl": str(pm / 30), "roi": str(roi / 30), "vlm": str(vlm / 30)}],
                                                                    ["week", {"pnl": str(pm / 4), "roi": str(roi / 4), "vlm": str(vlm / 4)}],
                                                                    ["month", {"pnl": str(pm), "roi": str(roi), "vlm": str(vlm)}],
                                                                    ["allTime", {"pnl": str(pt), "roi": str(pt / conta), "vlm": str(vlm * 12)}]]}}

    def _robo(self, moedas, conta, limiar=0.025, alvo=0.02, stop=0.015, max_h=12):
        """Robô de regra clara: a cada 15 min (minutos :00, :15, :30, :45), se o preço andou ≥ 2,5% em 60 min, entra
        CONTRA o movimento com o mesmo valor em US$ (25% da conta); sai com +2%, −1,5% ou depois de 12 h."""
        fills, eq, tid, eqv = [], [], 0, float(conta)
        fim = T0 + (DIAS - 1) * DIA
        livre = {m: T0 + HORA for m in moedas}
        valor = 0.25 * conta
        t = T0 + HORA
        while t < fim:
            for m in moedas:
                if t < livre[m]:
                    continue
                p, p60 = self.px(m, t), self.px(m, t - HORA)
                mov = p / p60 - 1
                lado = 1 if mov <= -limiar else -1 if mov >= limiar else 0
                if not lado:
                    continue
                sz = round(valor / p, 4)
                u = t + MIN
                while u < min(fim, t + max_h * HORA):
                    rr = (self.px(m, u) / p - 1) * lado
                    if rr >= alvo or rr <= -stop:
                        break
                    u += MIN
                p2 = self.px(m, u)
                for k, (quando, px, start, delta) in enumerate(((t + 400, p, 0.0, lado * sz), (u + 700, p2, lado * sz, -lado * sz))):
                    tid += 1
                    fechado = 0.0 if k == 0 else sz * (p2 - p) * lado
                    fee = sz * px * 0.00045
                    fills.append({"coin": m, "px": f"{px:.6g}", "sz": f"{sz:.6g}", "side": "B" if delta > 0 else "A", "time": quando,
                                  "startPosition": f"{start:.6g}", "dir": ("Open " if k == 0 else "Close ") + ("Long" if lado > 0 else "Short"),
                                  "closedPnl": f"{fechado:.4f}", "hash": "0x" + f"{tid:064x}", "oid": tid * 7, "crossed": True,
                                  "fee": f"{fee:.6f}", "feeToken": "USDC", "tid": tid})
                    eqv += fechado - fee
                livre[m] = u + 15 * MIN
            t += 15 * MIN
        fills.sort(key=lambda f: (f["time"], f["tid"]))
        eq = [(T0 + h * HORA, float(conta)) for h in range(DIAS * 24 + 24)]
        # o patrimônio pelo resultado acumulado até cada hora
        acum, i = float(conta), 0
        for j, (th, _) in enumerate(eq):
            while i < len(fills) and fills[i]["time"] <= th:
                acum += float(fills[i]["closedPnl"]) - float(fills[i]["fee"])
                i += 1
            eq[j] = (th, acum)
        return fills, eq

    def _operar(self, r, estilo, moedas, conta, passivo=0.15, horas=None, redondo=False):
        """`horas`: (de, até) no horário de Brasília em que a pessoa opera (fora disso, dorme); `redondo`: as ordens
        limite em preço com 3 algarismos (62.300), como uma pessoa digita."""
        fills, eq, pos, entrada = [], [], {m: 0.0 for m in moedas}, {m: 0.0 for m in moedas}
        t, eqv, tid = T0 + r.randint(1, 600) * MIN, float(conta), 0
        acao = 0

        def acordado(x):
            if not horas:
                return x
            h = ((x - 3 * HORA) // HORA) % 24
            if horas[0] <= h < horas[1]:
                return x
            dia = (x - 3 * HORA) // DIA * DIA + 3 * HORA
            prox = dia + horas[0] * HORA + (DIA if h >= horas[1] else 0)
            return prox + r.randint(0, 50) * MIN
        fim = T0 + (DIAS - 1) * DIA
        prox_eq = T0
        while t < fim:
            t = acordado(t)
            m = r.choice(moedas)
            p = self.px(m, t)
            if estilo == "escalpo":
                espera, dura = r.randint(3, 15) * MIN, r.randint(2, 8) * MIN
            elif estilo == "segura":
                espera, dura = r.randint(4, 30) * HORA + r.randint(0, 59) * MIN, 0
            else:
                # gente não tem relógio: esperas e durações bem irregulares (exponenciais)
                espera = int(min(4 * DIA, r.expovariate(1 / 14) * HORA)) + r.randint(10, 59) * MIN
                dura = int(min(4 * DIA, 2 * HORA + r.expovariate(1 / 13) * HORA)) + r.randint(0, 59) * MIN
            ant = self.px(m, t - 6 * HORA)
            lado = 1 if p >= ant else -1
            if estilo == "contra":
                lado = -lado
            if estilo == "segura":  # fecha com +0,5% a favor; se for contra, segura até voltar (até 20 dias)
                lado, dura = 1, 20 * DIA
                for h in range(1, 20 * 24):
                    if self.px(m, t + h * HORA) >= p * 1.005:
                        dura = h * HORA
                        break
            frac = r.uniform(0.4, 1.2)
            sz = round(frac * eqv / p, 4)
            dura = acordado(t + dura) - t
            for alvo, quando in ((lado * sz, t), (0.0, t + dura)):
                if quando >= fim:
                    break
                livro = estilo != "escalpo" and r.random() < passivo
                px = self.px(m, quando)
                if redondo and livro:
                    px = float(f"{px:.3g}")
                acao += 1
                partes = r.randint(1, 3)
                antes = pos[m]
                delta = alvo - antes
                for k in range(partes):
                    q = round(abs(delta) / partes, 6)
                    if q <= 0:
                        continue
                    lado_f = "B" if delta > 0 else "A"
                    fechado = 0.0
                    if pos[m] and (delta > 0) != (pos[m] > 0):
                        fechado = q * (px - entrada[m]) * (1 if pos[m] > 0 else -1)
                    elif not pos[m] or (delta > 0) == (pos[m] > 0):
                        entrada[m] = (abs(pos[m]) * entrada[m] + q * px) / (abs(pos[m]) + q)
                    tid += 1
                    fee = q * px * (0.00045 if estilo != "escalpo" else 0.00015)
                    fills.append({"coin": m, "px": f"{px:.6g}", "sz": f"{q:.6g}", "side": lado_f, "time": quando + k,
                                  "startPosition": f"{pos[m]:.6g}", "dir": ("Open " if fechado == 0 else "Close ") + ("Long" if (delta > 0) == (fechado == 0) else "Short"),
                                  "closedPnl": f"{fechado:.4f}", "hash": "0x" + f"{tid:064x}", "oid": acao * 7 + 3, "crossed": not livro if estilo != "escalpo" else False,
                                  "fee": f"{fee:.6f}", "feeToken": "USDC", "tid": tid})
                    pos[m] = float(f"{pos[m] + (q if lado_f == 'B' else -q):.6g}")
                    eqv += fechado - fee
                if abs(pos[m]) < 1e-9:
                    pos[m] = 0.0
            while prox_eq <= t:
                eq.append((prox_eq, eqv))
                prox_eq += HORA
            t += dura + espera
        while prox_eq <= fim + DIA:
            eq.append((prox_eq, eqv))
            prox_eq += HORA
        return fills, eq


class ClienteFalso:
    """Mesma interface do hl.Cliente, sobre o Mundo; nada depois de `agora` (ponha `cli.agora` antes da rodada)."""

    def __init__(self, mundo=None, agora=None):
        self.mundo = mundo or Mundo()
        self.agora = agora or T0 + 32 * DIA
        self.pedidos = 0
        self.peso = 0
        self.falhar = set()  # tipos de pedido que dão erro (testes)
        self.sumidas = set()  # carteiras que saíram do ranking (o exemplo mostra uma carteira que saiu)

    def _contar(self, tipo, peso=20):
        if tipo in self.falhar:
            raise hl.Erro(f"falha de teste em {tipo}")
        self.pedidos += 1
        self.peso += peso

    def ranking(self):
        self._contar("ranking")
        return [c["ranking"] for e, c in self.mundo.carteiras.items() if e not in self.sumidas]

    def meta(self):
        self._contar("meta")
        return {"universe": [{"name": m, "szDecimals": 4, "maxLeverage": v} for m, v in MAX_LEV.items()]}

    def papel(self, user):
        self._contar("userRole", 60)
        c = self.mundo.carteiras.get(user)
        return c["papel"] if c else "missing"

    def _eq(self, user, t):
        eq = self.mundo.carteiras[user]["eq"]
        i = max(0, min(len(eq) - 1, (t - eq[0][0]) // HORA))
        return eq[i][1]

    def estado(self, user):
        self._contar("clearinghouseState", 2)
        v = self._eq(user, self.agora)
        return {"marginSummary": {"accountValue": f"{v:.2f}", "totalNtlPos": "0", "totalRawUsd": f"{v:.2f}", "totalMarginUsed": "0"},
                "crossMarginSummary": {"accountValue": f"{v:.2f}"}, "assetPositions": [], "time": self.agora, "withdrawable": f"{v:.2f}"}

    def portfolio(self, user):
        self._contar("portfolio")
        eq = [(t, v) for t, v in self.mundo.carteiras[user]["eq"] if self.agora - 30 * DIA <= t <= self.agora]
        c0 = eq[0][1] if eq else 0
        mes = {"accountValueHistory": [[t, f"{v:.2f}"] for t, v in eq[::6]], "pnlHistory": [[t, f"{v - c0:.2f}"] for t, v in eq[::6]], "vlm": "0"}
        sem = {"accountValueHistory": [[t, f"{v:.2f}"] for t, v in eq if t >= self.agora - 7 * DIA], "pnlHistory": [], "vlm": "0"}
        return [["day", sem], ["week", sem], ["month", mes], ["allTime", mes], ["perpDay", sem], ["perpWeek", sem], ["perpMonth", mes], ["perpAllTime", mes]]

    def execucoes(self, user):
        self._contar("userFills")
        fs = [f for f in self.mundo.carteiras[user]["fills"] if f["time"] <= self.agora]
        self.peso += math.ceil(min(2000, len(fs)) / 20)
        return list(reversed(fs))[:2000]

    def execucoes_entre(self, user, ini, fim=None, maximo=10_000):
        self._contar("userFillsByTime")
        fim = min(fim if fim is not None else self.agora, self.agora)
        return [f for f in self.mundo.carteiras[user]["fills"] if ini <= f["time"] <= fim]

    def velas(self, moeda, intervalo, ini, fim):
        self._contar("candleSnapshot")
        passo = hl.INTERVALO_MS[intervalo]
        k = passo // MIN
        fim = min(fim, self.agora)
        a = max(T0, (ini // passo) * passo)
        out = []
        p = self.mundo.p[moeda]
        while a <= fim and len(out) < hl.MAX_VELAS:
            i = (a - T0) // MIN
            if i + k > self.mundo.n:
                break
            trecho = p[i:i + k + 1]
            out.append({"t": a, "T": a + passo - 1, "s": moeda, "i": intervalo, "o": f"{trecho[0]:.6g}", "c": f"{trecho[-1]:.6g}",
                        "h": f"{max(trecho) * 1.0002:.6g}", "l": f"{min(trecho) * 0.9998:.6g}", "v": "10.0", "n": 50})
            a += passo
        return out

    def financiamento(self, moeda, ini, fim):
        self._contar("fundingHistory")
        fim = min(fim, self.agora)
        return [{"coin": moeda, "fundingRate": f"{r:.8f}", "premium": "0.0", "time": t} for t, r in self.mundo.funding[moeda] if ini <= t <= fim]


def gerar_exemplo(destino, pasta, rodadas=48, cada_h=6):
    """Roda a 1ª escolha e `rodadas` rodadas seguidas no mercado de mentira e guarda o resumo (exemplos/resumo.json)."""
    import json
    import os
    import shutil

    import mercado
    shutil.rmtree(pasta, ignore_errors=True)
    cli = ClienteFalso()
    t = cli.agora
    fica = mercado.FICA_SEMANAS
    mercado.FICA_SEMANAS = 1  # no exemplo, a reavaliação vem em 1 semana, para a tela Escolha mostrar uma carteira que saiu
    for k in range(rodadas + 1):
        cli.agora = t + k * cada_h * HORA
        if cli.agora - t >= 6 * DIA and not cli.sumidas:
            cli.sumidas.add(sorted(cli.mundo.carteiras)[0])
        resumo, _ = mercado.rodada(cli, pasta, cli.agora, exemplo=True, buscar_cdi=False, log=mercado.Log(quieto=k > 0))
    mercado.FICA_SEMANAS = fica
    with open(destino, "w") as f:
        json.dump(resumo, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{destino}: {len(resumo['carteiras'])} carteiras, {os.path.getsize(destino) // 1024} KB")


if __name__ == "__main__":
    import os
    import sys
    aqui = os.path.dirname(os.path.abspath(__file__))
    gerar_exemplo(os.path.join(aqui, "exemplos", "resumo.json"), sys.argv[1] if len(sys.argv) > 1 else "/tmp/orbita-mercado-exemplo")
