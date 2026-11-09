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
import math

CAPITAL = 1000.0
FUSO_MS = -3 * 3_600_000  # Brasília (sem horário de verão desde 2019)
HORA = 3_600_000
DIA = 86_400_000
MAX_LIQ = 50
MAX_EVENTOS = 300
SHARPE_MAX = 10.0


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


def cdi_ano_da_serie(cdi: dict, padrao: float) -> float:
    """A taxa ao ano do CDI pelos últimos 20 dias úteis da série do BC (fração diária por dia); sem série, `padrao`."""
    ult = [cdi[d] for d in sorted(cdi)[-20:]]
    if len(ult) < 5:
        return padrao
    return round((1 + sum(ult) / len(ult)) ** 252 - 1, 4)


def _cdi_do_dia(cdi: dict, d: dt.date, primeiro: str, ultimo: str, diaria: float) -> float:
    """O CDI do dia `d` (fração): o da série; fora dela (antes do 1º ou depois do último dia guardado), a taxa de agora
    nos dias úteis; dentro dela, um dia útil sem valor é feriado (0)."""
    k = d.isoformat()
    if k in cdi:
        return cdi[k]
    if (k > ultimo or k < primeiro) and d.weekday() < 5:
        return diaria
    return 0.0


def metricas(conta: dict | None, cdi: dict, cdi_ano: float, capital: float = CAPITAL) -> dict | None:
    """Números para decidir, iguais em todas as formas (e no copy trading), a partir da série diária da conta:

    - `dias` (do começo ao último ponto), `aoMes` ((1 + retorno)^(30/dias) − 1; só com 7 dias ou mais) e `aoAno` (só
      com 30 dias ou mais: extrapolar uma semana para um ano engana);
    - `cdi`: o CDI no MESMO período (a série 12 do BC, dia a dia; depois do último dia publicado, a taxa de agora) e
      `excesso` = (1 + retorno) ÷ (1 + cdi) − 1: positivo = ganhou do CDI no mesmo tempo;
    - `volAno`: o quanto o patrimônio balança (desvio dos retornos diários × √365); `sharpe`: (retorno diário médio −
      CDI do dia) ÷ desvio × √365, só com 14 dias ou mais e limitado a ±10 (acima de 1 é bom; abaixo de 0, o CDI ganhou
      com menos risco);
    - `retornoPorQueda`: o ao ano ÷ a pior queda (a "Calmar"; só com 30 dias e queda de 0,5% ou mais);
    - `piorDia` (o pior retorno de um dia) e `diasPositivos` (fração dos dias que fecharam no azul).

    Dias sem ponto repetem o valor anterior (a conta ficou parada). Devolve None sem série."""
    if not conta or not conta.get("serie"):
        return None
    try:
        inicio = dt.date.fromisoformat(dia_de(int(conta.get("inicio") or 0)))
    except (TypeError, ValueError, OverflowError):
        return None
    pontos = {dt.date.fromisoformat(d): float(v) for d, v in conta["serie"]}
    fim = max(pontos)
    inicio = min(inicio, min(pontos))
    valores, v, d = [], capital, inicio
    while d <= fim:
        v = pontos.get(d, v)
        valores.append((d, v))
        d += dt.timedelta(days=1)
    dias = (fim - inicio).days
    ret = valores[-1][1] / capital - 1
    ultimo, primeiro = (max(cdi), min(cdi)) if cdi else ("", "")
    diaria = (1 + cdi_ano) ** (1 / 252) - 1
    rets, livres, ind_cdi = [], [], 1.0
    anterior = capital
    for i, (d, v) in enumerate(valores):
        rf = _cdi_do_dia(cdi, d - dt.timedelta(days=1), primeiro, ultimo, diaria) if i else 0.0
        if i:
            ind_cdi *= 1 + rf
            if anterior > 0:
                rets.append(v / anterior - 1)
                livres.append(rf)
        anterior = v
    out = {"dias": dias, "retorno": round(ret, 6), "cdi": round(ind_cdi - 1, 6),
           "excesso": round((1 + ret) / ind_cdi - 1, 6), "venceCdi": (1 + ret) > ind_cdi,
           "aoMes": None, "aoAno": None, "volAno": None, "sharpe": None, "retornoPorQueda": None,
           "piorDia": round(min(rets), 6) if rets else None,
           "diasPositivos": round(sum(1 for r in rets if r > 0) / len(rets), 4) if rets else None}
    if dias >= 7:
        out["aoMes"] = round(max(0.0, 1 + ret) ** (30 / dias) - 1, 6)
    if dias >= 30:
        out["aoAno"] = round(max(0.0, 1 + ret) ** (365 / dias) - 1, 6)
        q = float(conta.get("piorQueda") or 0)
        if q >= 0.005:
            out["retornoPorQueda"] = round(out["aoAno"] / q, 3)
    if len(rets) >= 2:
        m = sum(rets) / len(rets)
        dp = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
        out["volAno"] = round(dp * math.sqrt(365), 6)
        if dias >= 14 and dp > 1e-9:
            ex = [r - f for r, f in zip(rets, livres)]
            # limitado a ±10: uma conta quase parada que rende menos que o CDI daria −100 (certo, mas sem sentido)
            out["sharpe"] = round(max(-SHARPE_MAX, min(SHARPE_MAX, sum(ex) / len(ex) / dp * math.sqrt(365))), 3)
    return out


def com_metricas(saida: dict, cdi: dict, cdi_ano: float):
    """Põe `metricas` em cada conta (`aoVivo` e `historico`) das versões e dos itens de um <forma>.json."""
    for grupo in (saida.get("versoes") or [], saida.get("itens") or []):
        for v in grupo:
            if not isinstance(v, dict):
                continue
            for k in ("aoVivo", "historico"):
                c = v.get(k)
                if isinstance(c, dict) and c.get("serie"):
                    try:
                        c["metricas"] = metricas(c, cdi, cdi_ano)
                    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
                        c["metricas"] = None
    return saida


class Eventos:
    """A linha do tempo da forma (mais nova primeiro no JSON; no máximo MAX_EVENTOS)."""

    def __init__(self, lista: list | None = None):
        self.lista = list(lista or [])

    def add(self, em: int, tipo: str, texto: str, versao: str | None = None):
        self.lista.append({"em": int(em), "versao": versao, "tipo": tipo, "texto": texto})

    def para_json(self) -> list:
        return sorted(self.lista, key=lambda e: -e["em"])[:MAX_EVENTOS]
