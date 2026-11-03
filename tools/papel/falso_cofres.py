"""Cofres de MENTIRA (sem rede; semente fixa) para os testes e o exemplo de `cofres.py`: ~25 cofres de tipos diferentes,
no formato da API da Hyperliquid (`stats-data …/vaults` e `vaultDetails`). Nada aqui é dado real (só o endereço do HLP
é o de verdade, para a regra "versão própria do HLP" valer).

Cada cofre tem uma cota (passeio aleatório com tendência, quedas marcadas) e um número de cotas dos depositantes que
muda com depósitos e saques de outros: o patrimônio (accountValueHistory) não anda junto com a cota, o lucro
(pnlHistory) sim. Tipos: o HLP (sem comissão; dois filhos), bons, fechado, novo demais, queda grande no passado, líder
com pouco, prejuízo no mês, prejuízo total, TVL pequeno, sem depósitos, e os que mudam durante o teste (fecha, some,
para de aceitar depósitos, despenca 25%).
"""
from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import math
import random
import zlib

MIN = 60_000
HORA = 3_600_000
DIA = 86_400_000
T0 = int(dt.datetime(2026, 9, 20, tzinfo=dt.timezone.utc).timestamp() * 1000)  # o mesmo do tools/mercado/falso.py
A0 = T0 + 32 * DIA      # o `agora` inicial do cliente falso
FIM = T0 + 60 * DIA
HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"


def endereco(nome):
    return "0x" + hashlib.sha1(nome.encode()).hexdigest()[:40]


# (nome, dias de vida em A0, TVL inicial, tendência ao ano, vol. diária, comissão, parte do líder, outros ajustes)
TIPOS = [
    ("Hyperliquidity Provider (HLP)", None, 150e6, 0.14, 0.004, 0.0, 0.0, {"hlp": True}),
    ("HLP Strategy A", 700, 90e6, 0.15, 0.005, 0.0, 0.0, {"filho": True}),
    ("HLP Liquidator", 700, 30e6, 0.10, 0.004, 0.0, 0.0, {"filho": True}),
    ("Growi Calmo", 400, 12e6, 0.35, 0.006, 0.1, 0.06, {}),
    ("Systemic Grids", 300, 8e6, 0.55, 0.009, 0.1, 0.08, {}),
    ("Tendência BTC", 250, 3e6, 0.45, 0.011, 0.1, 0.12, {}),
    ("Sol Nascente", 200, 1.2e6, 0.60, 0.012, 0.1, 0.20, {}),
    ("Delta Neutro", 500, 6e6, 0.22, 0.003, 0.1, 0.07, {}),
    ("Funding Farm", 180, 2.2e6, 0.30, 0.004, 0.1, 0.10, {}),
    ("Base Larga", 365, 900e3, 0.40, 0.010, 0.1, 0.15, {}),
    ("Mesa do Leo", 120, 450e3, 0.70, 0.014, 0.1, 0.30, {}),
    ("Foguete Quebrado", 220, 4e6, 0.90, 0.008, 0.1, 0.10, {"despenca": A0 + 5 * DIA}),
    ("Aposentado", 400, 5e6, 0.50, 0.007, 0.1, 0.10, {"fecha": A0 - 20 * DIA}),
    ("Vai Fechar", 260, 2.5e6, 0.80, 0.008, 0.1, 0.10, {"fecha": A0 + 3 * DIA}),
    ("Recém-chegado", 10, 1.5e6, 1.50, 0.010, 0.1, 0.20, {}),
    ("Montanha-russa", 420, 3.5e6, 1.40, 0.012, 0.1, 0.10, {"queda": (A0 - 150 * DIA, 0.45)}),
    ("Porta Fechada", 300, 2e6, 0.50, 0.006, 0.1, 0.10, {"sem_deposito": True}),
    ("Lotado", 280, 1.8e6, 0.75, 0.007, 0.1, 0.10, {"para_deposito": A0 + 4 * DIA}),
    ("Fantasma", 200, 1.1e6, 0.85, 0.008, 0.1, 0.10, {"some": A0 + 2 * DIA}),
    ("Pequenino", 300, 25e3, 0.80, 0.008, 0.1, 0.30, {}),
    ("Líder Tímido", 300, 2e6, 0.60, 0.007, 0.1, 0.03, {}),
    ("Mês Ruim", 300, 2e6, 0.40, 0.006, 0.1, 0.10, {"mes_ruim": True}),
    ("Sempre Perde", 300, 2e6, -0.30, 0.006, 0.1, 0.10, {}),
    ("Degen 50x", 150, 700e3, 1.20, 0.022, 0.1, 0.25, {}),
    ("Entra e Sai", 330, 4e6, 0.45, 0.007, 0.1, 0.10, {"fluxo": 0.25}),
]


class Cofre:
    def __init__(self, k, nome, idade, tvl0, mu, vol, com, lf, aj, r):
        self.nome, self.com, self.lf, self.aj = nome, com, lf, aj
        self.endereco = HLP if aj.get("hlp") else endereco(nome)
        self.lider = endereco("lider " + nome)
        self.criado = int(dt.datetime(2023, 5, 1, tzinfo=dt.timezone.utc).timestamp() * 1000) if idade is None else A0 - idade * DIA
        # grade: diária até 15 dias antes de T0, depois de hora em hora até o fim do mundo
        corte = T0 - 15 * DIA
        ts = list(range(self.criado, min(corte, FIM), DIA)) + list(range(max(corte, self.criado), FIM + 1, HORA))
        self.t, self.i, self.s, self.pnl = [], [], [], []
        i, s, pnl, t_ant = 1.0, tvl0, 0.0, None
        fluxo = aj.get("fluxo", 0.03)
        for t in ts:
            if t_ant is not None:
                d = (t - t_ant) / DIA
                m = mu
                if aj.get("mes_ruim") and t > A0 - 40 * DIA:
                    m = -0.9
                r_ = m * d / 365 + vol * math.sqrt(d) * r.gauss(0, 1)
                q = aj.get("queda")
                if q and q[0] <= t < q[0] + 10 * DIA:
                    r_ -= (1 - (1 - q[1]) ** (1 / 10)) * d  # a queda grande dividida em 10 dias
                dp = aj.get("despenca")
                if dp and dp <= t < dp + 6 * HORA:
                    r_ -= (1 - 0.72 ** (1 / 6)) * d * 24
                fe = aj.get("fecha")
                novo_i = i if (fe and t >= fe) else i * math.exp(max(-0.5, min(0.5, r_)))
                pnl += s * (novo_i - i)
                i = novo_i
                # depósitos e saques dos outros (o número de cotas muda; a cota não)
                s *= math.exp(fluxo * math.sqrt(d) * r.gauss(0, 1) + 0.15 * d / 365)
                if aj.get("fluxo") and r.random() < 0.02 * d * 24:
                    s *= r.choice((0.7, 1 / 0.7))
                if fe and t >= fe:
                    s = 0.0
            self.t.append(t)
            self.i.append(i)
            self.s.append(s)
            self.pnl.append(pnl)
            t_ant = t

    def k(self, t):
        return bisect.bisect_right(self.t, t) - 1

    def av(self, k):
        return self.s[k] * self.i[k]

    def existe(self, agora):
        some = self.aj.get("some")
        return self.criado <= agora and not (some and agora >= some)

    def fechado(self, agora):
        fe = self.aj.get("fecha")
        return bool(fe and agora >= fe)

    def aceita(self, agora):
        if self.aj.get("sem_deposito"):
            return False
        pd = self.aj.get("para_deposito")
        return not (pd and agora >= pd) and not self.fechado(agora)

    def indices(self, nome, agora):
        """Os índices da grade na janela `nome` (day, week, month, allTime) em `agora`."""
        kk = self.k(agora)
        if kk < 0:
            return []
        if nome == "allTime":  # ~90 pontos igualmente espaçados no tempo, desde a criação
            passo = max(HORA, (self.t[kk] - self.t[0]) // 90)
            ks = sorted({self.k(self.t[0] + j * passo) for j in range(91) if self.t[0] + j * passo <= self.t[kk]})
        else:
            dur, passo = {"day": (DIA, HORA), "week": (7 * DIA, 3 * HORA), "month": (30 * DIA, 16 * HORA)}[nome]
            ini = max(self.k(agora - dur), 0)
            ks = [k for k in range(ini, kk + 1) if (self.t[kk] - self.t[k]) % passo == 0]
        if ks[-1] != kk:
            ks.append(kk)
        return ks

    def janela(self, nome, agora):
        ks = self.indices(nome, agora)
        if not ks:
            return {"accountValueHistory": [], "pnlHistory": [], "vlm": "0.0"}
        p0 = self.pnl[ks[0]]
        return {"accountValueHistory": [[self.t[k], f"{self.av(k):.6f}"] for k in ks],
                "pnlHistory": [[self.t[k], f"{self.pnl[k] - p0:.6f}"] for k in ks], "vlm": f"{self.av(ks[-1]) * 3:.2f}"}

    def apr(self, agora):
        kk, km = self.k(agora), self.k(agora - 30 * DIA)
        if kk < 0 or km < 0 or self.i[km] <= 0:
            return 0.0
        return (self.i[kk] / self.i[km]) ** 12 - 1

    def relacao(self, filhos):
        if self.aj.get("hlp"):
            return {"type": "parent", "data": {"childAddresses": filhos}}
        if self.aj.get("filho"):
            return {"type": "child", "data": {"parent": HLP}}
        return {"type": "normal"}


_UNIVERSO = None


def universo():
    global _UNIVERSO
    if _UNIVERSO is None:
        r = random.Random(42)
        _UNIVERSO = [Cofre(k, *x, r) for k, x in enumerate(TIPOS)]
    return _UNIVERSO


class Falso:
    """Mixin do cliente falso (tools/papel/falso.py): `cofres()` e `cofre(endereco)` no formato da API."""

    def preparar(self):
        self.cofres_falsos = {c.endereco: c for c in universo()}
        self.filhos_hlp = [c.endereco for c in universo() if c.aj.get("filho")]

    def cofres(self):
        self._contar("vaults")
        out = []
        for c in self.cofres_falsos.values():
            if not c.existe(self.agora):
                continue
            kk = c.k(self.agora)
            pnls = []
            for nome in ("day", "week", "month", "allTime"):
                ks = c.indices(nome, self.agora)
                ks = ks[:: max(1, len(ks) // 12)][-12:]
                p0 = c.pnl[c.indices(nome, self.agora)[0]]
                pnls.append([nome, [f"{c.pnl[k] - p0:.6f}" for k in ks]])
            out.append({"apr": c.apr(self.agora), "pnls": pnls,
                        "summary": {"name": c.nome, "vaultAddress": c.endereco, "leader": c.lider,
                                    "tvl": f"{c.av(kk):.6f}", "isClosed": c.fechado(self.agora),
                                    "relationship": c.relacao(self.filhos_hlp), "createTimeMillis": c.criado}})
        # o resto da lista de verdade: milhares de cofres pequenos e fechados
        for n in range(40):
            out.append({"apr": 0.0, "pnls": [[j, ["0.0"] * 12] for j in ("day", "week", "month", "allTime")],
                        "summary": {"name": f"Cofre parado {n}", "vaultAddress": endereco(f"parado {n}"),
                                    "leader": endereco(f"lider parado {n}"), "tvl": f"{n * 0.37:.6f}", "isClosed": n % 3 == 0,
                                    "relationship": {"type": "normal"}, "createTimeMillis": A0 - (50 + n) * DIA}})
        return out

    def cofre(self, endereco_, user=None):
        self._contar("vaultDetails")
        c = self.cofres_falsos.get(str(endereco_).lower())
        if c is None or not c.existe(self.agora):
            return None
        kk = c.k(self.agora)
        av = c.av(kk)
        r = random.Random(zlib.crc32(f"{c.nome}|{self.agora // DIA}".encode()))
        seguidores = [{"user": endereco(f"seguidor {c.nome} {j}"), "vaultEquity": f"{av * 0.01 * (j + 1):.2f}",
                       "pnl": f"{r.uniform(-50, 500):.2f}", "allTimePnl": f"{r.uniform(-50, 900):.2f}",
                       "daysFollowing": r.randint(1, 200), "vaultEntryTime": c.criado + j * DIA,
                       "lockupUntil": c.criado + j * DIA + DIA} for j in range(min(12, 3 + int(math.log10(max(av, 10)))))]
        return {"name": c.nome, "vaultAddress": c.endereco, "leader": c.lider,
                "description": f"Cofre de mentira ({c.nome}) para os testes.",
                "portfolio": [[j, c.janela(j, self.agora)] for j in ("day", "week", "month", "allTime")],
                "apr": c.apr(self.agora), "followerState": None, "leaderFraction": c.lf, "leaderCommission": c.com,
                "followers": seguidores, "maxDistributable": f"{av * 0.9:.6f}", "maxWithdrawable": f"{av * 0.5:.6f}",
                "isClosed": c.fechado(self.agora), "relationship": c.relacao(self.filhos_hlp),
                "allowDeposits": c.aceita(self.agora), "alwaysCloseOnWithdraw": False}
