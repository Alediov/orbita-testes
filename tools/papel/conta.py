"""A conta fictícia genérica das outras formas (formato em FORMATO.md): curva diária de patrimônio, pior queda medida
no passo da simulação, operações, taxas, liquidações e números próprios (`extra`). Só biblioteca padrão.

Uso típico num módulo de forma:

    c = Curva.de_json(est.get("btc1")) or Curva(inicio=agora)
    for t, valor in passos:          # cada passo da simulação (hora, vela, ponto do cofre…)
        c.marcar(t, valor)
    c.operou(taxa=0.45)              # a cada ordem executada (taxa em US$)
    est["btc1"] = c.para_json()
    versao["aoVivo"] = c.resumo()
"""
from __future__ import annotations

import datetime as dt

CAPITAL = 1000.0
FUSO_MS = -3 * 3_600_000  # Brasília (sem horário de verão desde 2019)
HORA = 3_600_000
DIA = 86_400_000
MAX_LIQ = 50
MAX_EVENTOS = 300


def dia_de(ms: int) -> str:
    """O dia (AAAA-MM-DD) em Brasília: o mesmo do sim.py e do app (`diaDe`)."""
    return dt.datetime.fromtimestamp((ms + FUSO_MS) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def moeda_br(v: float, casas: int = 2) -> str:
    """US$ 1.234,56 (para os textos dos eventos)."""
    s = f"{abs(v):,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'−' if v < 0 else ''}US$ {s}"


def num_br(v: float, casas: int = 2) -> str:
    s = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def pct_br(v: float, casas: int = 1) -> str:
    return f"{num_br(v * 100, casas)}%"


class Curva:
    """Patrimônio de uma conta ao longo do tempo."""

    def __init__(self, inicio: int, capital: float = CAPITAL):
        self.inicio = int(inicio)
        self.capital = capital
        self.serie: dict[str, float] = {}
        self.pico = capital
        self.queda = 0.0
        self.ultimo = capital
        self.t = int(inicio)
        self.ops = 0
        self.taxas = 0.0
        self.liq: list[dict] = []
        self.n_liq = 0
        self.extra: dict = {}
        self.ganhos: list[float] = []  # resultado de cada operação fechada (para acerto, gm, pm), as últimas 500

    # ------------------------------------------------------------------ registro
    def marcar(self, t: int, valor: float):
        """O patrimônio em `t` (ms). Atualiza o ponto do dia, o pico e a pior queda."""
        valor = max(0.0, float(valor))
        self.t, self.ultimo = int(t), valor
        self.serie[dia_de(t)] = round(valor, 4)
        self.pico = max(self.pico, valor)
        if self.pico > 0:
            self.queda = max(self.queda, 1 - valor / self.pico)

    def operou(self, taxa: float = 0.0, n: int = 1):
        self.ops += n
        self.taxas += max(0.0, taxa)

    def fechou(self, resultado: float):
        """Uma operação fechada com `resultado` em US$ (para o acerto e o ganho/perda médios)."""
        self.ganhos.append(float(resultado))
        del self.ganhos[:-500]

    def liquidou(self, t: int, moeda: str, perda: float):
        self.n_liq += 1
        self.liq.append({"em": int(t), "moeda": moeda, "perda": round(float(perda), 2)})
        del self.liq[:-MAX_LIQ]

    # ------------------------------------------------------------------ saída
    def resumo(self, **mais) -> dict:
        serie = sorted(self.serie.items())
        out = {"inicio": self.inicio, "serie": [[d, v] for d, v in serie],
               "retorno": round(self.ultimo / self.capital - 1, 6), "piorQueda": round(self.queda, 6),
               "ops": self.ops, "taxas": round(self.taxas, 4), "liquidacoes": list(self.liq), "nLiq": self.n_liq}
        if self.extra:
            out["extra"] = self.extra
        g = [x for x in self.ganhos if x > 0]
        p = [-x for x in self.ganhos if x < 0]
        if self.ganhos:
            out["acerto"] = round(len(g) / len(self.ganhos), 4)
        if g and p:
            out["gm"] = round(sum(g) / len(g), 4)
            out["pm"] = round(sum(p) / len(p), 4)
        out.update(mais)
        return out

    def para_json(self) -> dict:
        return {"inicio": self.inicio, "capital": self.capital, "serie": self.serie, "pico": self.pico,
                "queda": self.queda, "ultimo": self.ultimo, "t": self.t, "ops": self.ops, "taxas": self.taxas,
                "liq": self.liq, "nLiq": self.n_liq, "extra": self.extra, "ganhos": self.ganhos}

    @classmethod
    def de_json(cls, d: dict | None) -> "Curva | None":
        if not d:
            return None
        c = cls(d["inicio"], d.get("capital", CAPITAL))
        c.serie = dict(d.get("serie") or {})
        c.pico, c.queda, c.ultimo, c.t = d.get("pico", c.capital), d.get("queda", 0.0), d.get("ultimo", c.capital), d.get("t", c.inicio)
        c.ops, c.taxas = d.get("ops", 0), d.get("taxas", 0.0)
        c.liq, c.n_liq = list(d.get("liq") or []), d.get("nLiq", 0)
        c.extra, c.ganhos = dict(d.get("extra") or {}), list(d.get("ganhos") or [])
        return c


class Eventos:
    """A linha do tempo da forma (mais nova primeiro no JSON; no máximo MAX_EVENTOS)."""

    def __init__(self, lista: list | None = None):
        self.lista = list(lista or [])

    def add(self, em: int, tipo: str, texto: str, versao: str | None = None):
        self.lista.append({"em": int(em), "versao": versao, "tipo": tipo, "texto": texto})

    def para_json(self) -> list:
        return sorted(self.lista, key=lambda e: -e["em"])[:MAX_EVENTOS]
