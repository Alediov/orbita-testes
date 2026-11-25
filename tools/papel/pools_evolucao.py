"""Evolução das Pools, NO PAPEL (pedido do Alediov, 25/11/2026: o 5º do plano docs/plano-evolucao.md do repositório do
app, "faremos uma por uma").

A espécie é a **Faixa** (controle `r3h`, a versão padrão do WETH/USDC): toda versão põe US$ 1.000 fictícios num pool
concentrado e cuida da faixa por uma regra. Os genes (o que evolui):

- `pool`: o WETH/USDC ou o cbBTC/USDC do Uniswap v3 na Base (os dois medidos em dólar; os outros pools da forma ficam
  de fora: o WETH/cbBTC é medido em bitcoin, o do Aerodrome ganha AERO pelo gauge e o dos dólares estáveis pede faixas
  cem vezes mais estreitas);
- `largura`: a faixa para cada lado do preço (0,5% a 15%, ou a cheia);
- `regra`: remonta ao sair, depois de um tempo fora, olha 1×/dia (à mão), espera dias fora (Marinho), remonta com o que
  sobrou, o automático da Krystal ou nunca remonta;
- `fora` (na "tempo fora" e na Krystal): quantas horas fora antes de remontar;
- `espera` (na espera e na sobra): quantos dias fora antes de mexer;
- `reinv` (à mão, espera, sobra e Krystal): de quantos em quantos dias põe as taxas de volta (0 = não põe).

**Os dados: o caminho do preço de hora em hora.** A taxa que uma faixa ganha só depende do caminho do preço por dentro
dela (`pools.taxa_no_trecho`: cada troca que move √P de s0 a s1 paga L × |Δ√P| × taxa), não do volume nem da liquidez
dos outros. Então o banco (`est["pools"][pool]["bancoEv"]`, gravado pelo `Gravador` junto com o ao vivo e semeado com
os 28 dias que o RPC grátis guarda) não guarda as trocas: guarda, de cada hora, a abertura, a mínima, a máxima, o
fechamento, qual extremo veio antes e, em baldes de 0,1% de √P, quanto o preço andou dentro de cada balde (o vai e vem
todo). O simulador refaz cada hora pelo caminho resumido (abertura → 1º extremo → 2º extremo → fechamento), cortado nos
baldes, e cada pedaço vale o tanto que o preço andou de verdade naquele balde dividido pelo tanto que o caminho resumido
anda nele (`peso`): a taxa total por balde bate com a de troca a troca; o que se perde é a ORDEM dentro da hora (uma
faixa que sai e é remontada no meio da hora ganha um pouco diferente). Por isso tudo é "aproximado". A conta é a própria
`pools.Conta` (as mesmas regras, gás, deslize, Krystal e reinvestimento), com as constantes de cada regra em `opc`.

O laboratório e a liga são os do motor comum (`evolucao_series.py`; estado em `est["evolucoes"]["faixa"]`); o
laboratório começa com MIN_DIAS_LAB dias de banco. Saída: `pools.json` → `evolucao` (FORMATO.md, "Evolução"). Teste:
`teste_pools_evolucao.py`.
"""
from __future__ import annotations

import bisect
import math

import evolucao_series as ES
import pools as PL
from conta import CAPITAL, DIA, cdi_ano_da_serie, dia_de, metricas
from genetica import reparar

VERSAO = 1
HORA = 3_600_000
BW = math.log(1.001)       # o balde: 0,1% em √P (~0,2% no preço)
ESC = 1e7                 # o caminho de cada balde vai ao estado em décimos de milionésimo (inteiros)
MAX_DIAS_BANCO = 60
MIN_HORAS = 24             # menos que isso de banco: sem a espécie ainda
MIN_DIAS_LAB = 25          # o RPC grátis guarda 28 dias: o laboratório começa quando o banco os tiver
CDI_PADRAO = 0.149
POOLS_EV = ["weth_usdc", "cbbtc_usdc"]
NOMES_POOL = {"weth_usdc": "WETH/USDC", "cbbtc_usdc": "cbBTC/USDC"}

FRASE = ("Faixas de pool que evoluem: toda semana as piores regras saem, as melhores se cruzam e, às vezes, um gene "
         "muda. Só no papel.")
AVISOS = ["Só no papel: nenhuma carteira, nenhum depósito.",
          "Aproximado: as contas são refeitas pelo caminho do preço de cada hora (abertura, mínima, máxima, fechamento e "
          "o vai e vem em pedaços de 0,1%), não troca a troca.",
          "O laboratório só tem os dias que o RPC grátis guarda (28) mais os que vão passando.",
          "O controle é a versão ±3% · 1 h fora do WETH/USDC refeita por este simulador (não bate centavo a centavo "
          "com a da forma)."]

ESP = {
    "id": "faixa", "nome": "Faixa", "icone": "📏", "prefixo": "f", "controle": "r3h",
    "frase": "Põe as duas moedas num pool, numa faixa em volta do preço: a largura, quando remontar e quando pôr as "
             "taxas de volta evoluem.",
    "genes": [
        {"k": "pool", "nome": "Pool", "tipo": "op", "opcoes": list(POOLS_EV), "rotulos": dict(NOMES_POOL),
         "neutro": "weth_usdc"},
        {"k": "largura", "nome": "Largura para cada lado", "tipo": "op",
         "opcoes": [0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0], "un": "%", "rotulos": {"0": "Cheia"},
         "neutro": 0.03},
        {"k": "regra", "nome": "Quando remonta", "tipo": "op",
         "opcoes": ["sai", "hora", "dia", "espera", "sobra", "krystal", "nunca"],
         "rotulos": {"sai": "Ao sair", "hora": "Depois de um tempo fora", "dia": "Olha 1×/dia",
                     "espera": "Espera dias fora", "sobra": "Com o que sobrou", "krystal": "Krystal",
                     "nunca": "Nunca"}, "neutro": "hora"},
        {"k": "fora", "nome": "Horas fora", "tipo": "op", "opcoes": [1, 2, 4, 8, 24], "un": "h", "neutro": 1,
         "so": {"regra": ["hora", "krystal"]}},
        {"k": "espera", "nome": "Dias fora antes de mexer", "tipo": "op", "opcoes": [1, 2, 3, 5, 7], "un": "d",
         "neutro": 3, "so": {"regra": ["espera", "sobra"]}},
        {"k": "reinv", "nome": "Põe as taxas de volta a cada", "tipo": "op", "opcoes": [0, 1, 3, 7, 14], "un": "d",
         "rotulos": {"0": "Não põe"}, "neutro": 7, "so": {"regra": ["dia", "espera", "sobra", "krystal"]}},
    ],
}
# as versões da forma que viram sementes: id → genes (fora do controle r3h e da referência "segurar")
SEMENTES = {
    "r1": {"largura": 0.01, "regra": "sai"}, "r1h": {"largura": 0.01}, "r3": {"regra": "sai"},
    "r10h": {"largura": 0.1}, "dia10": {"largura": 0.1, "regra": "dia"}, "dia5": {"largura": 0.05, "regra": "dia"},
    "esp3": {"largura": 0.05, "regra": "espera"}, "esp7": {"largura": 0.05, "regra": "espera", "espera": 7},
    "sobra": {"largura": 0.05, "regra": "sobra"}, "krystal10": {"largura": 0.1, "regra": "krystal", "reinv": 1},
    "krystal5": {"largura": 0.05, "regra": "krystal", "reinv": 1}, "cheia": {"largura": 0},
    "r3fixa": {"regra": "nunca"},
}


def _pc(x):
    return f"{x * 100:g}".replace(".", ",") + "%"


class Definicao:
    versao, nome_controle, da_liga, rotulo = VERSAO, "±3% · 1 h fora", "das faixas", "pools"

    def __init__(self, esp=ESP):
        self.esp = esp

    def genes_controle(self):
        return reparar(self.esp, {g["k"]: g["neutro"] for g in self.esp["genes"]})

    def sementes(self):
        b = self.genes_controle()
        return [(vid, reparar(self.esp, {**b, **m})) for vid, m in SEMENTES.items()]

    def descrever(self, genes):
        return descrever(genes)


def descrever(genes):
    g = genes
    if not g["largura"]:
        t = "Faixa cheia"
    else:
        w = "±" + _pc(g["largura"])
        r = g["regra"]
        if r == "sai":
            t = f"{w} · remonta ao sair"
        elif r == "hora":
            t = f"{w} · remonta depois de {g['fora']} h fora"
        elif r == "dia":
            t = f"{w} · olha 1×/dia"
        elif r == "espera":
            t = f"{w} · espera {g['espera']} {'dia' if g['espera'] == 1 else 'dias'} fora"
        elif r == "sobra":
            t = f"{w} · remonta com o que sobrou depois de {g['espera']} {'dia' if g['espera'] == 1 else 'dias'}"
        elif r == "krystal":
            t = f"{w} · Krystal depois de {g['fora']} h fora"
        else:
            t = f"{w} · nunca remonta"
        if r in ("dia", "espera", "sobra", "krystal"):
            t += " · taxas de volta " + ("nunca" if not g["reinv"] else "todo dia" if g["reinv"] == 1 else
                                         f"a cada {g['reinv']} dias")
    return (t if g["pool"] == "weth_usdc" else f"{NOMES_POOL[g['pool']]} · {t}")


# ====================================================================== o banco: o caminho do preço de hora em hora
def caminho(acc, x0, x1):
    """Soma em `acc[balde]` o comprimento do trecho de x0 a x1 (ln √P), cortado nos baldes."""
    lo, hi = (x0, x1) if x0 < x1 else (x1, x0)
    b = math.floor(lo / BW)
    while lo < hi:
        fim = min(hi, (b + 1) * BW)
        acc[b] = acc.get(b, 0.0) + (fim - lo)
        lo, b = fim, b + 1


def _r(v):
    return float(f"{v:.10g}")


class Gravador:
    """O banco de um pool, que anda como um grupo de versões (`pools.avancar` o alimenta com as mesmas trocas): de
    cada hora, [abertura, mínima, máxima, fechamento (√P), ms da mínima e da máxima na hora, salto, {balde: caminho}].
    `salto` = 1 quando a abertura veio depois de blocos que não deu para ler (o caminho até ela se perdeu)."""

    nome = "banco"

    def __init__(self, estado=None):
        e = estado or {}
        self.bloco = int(e.get("bloco") or 0)
        self.s = e.get("s")
        # no estado: os ms da mínima e da máxima em segundos e o caminho em décimos de milionésimo (inteiros)
        self.h = {int(k): [*v[:4], v[4] * 1000, v[5] * 1000, v[6], {int(b): x / ESC for b, x in v[7].items()}]
                  for k, v in (e.get("h") or {}).items()}
        self._salto = bool(e.get("salto"))

    def para_json(self):
        if self.h:
            corte = max(self.h) - MAX_DIAS_BANCO * DIA
            self.h = {k: v for k, v in self.h.items() if k >= corte}
        return {"bloco": self.bloco, "s": self.s, "salto": self._salto,
                "h": {str(k): [*[_r(x) for x in v[:4]], v[4] // 1000, v[5] // 1000, v[6],
                               {str(b): round(x * ESC) for b, x in v[7].items() if round(x * ESC)}]
                      for k, v in sorted(self.h.items())}}

    def ver(self, t, s):
        h = t // HORA * HORA
        e = self.h.get(h)
        s0 = self.s
        if e is None:
            o = s0 if s0 else s
            e = self.h[h] = [o, o, o, o, 0, 0, 1 if (self._salto or not s0) else 0, {}]
            self._salto = False
        if s0 and s0 != s:
            caminho(e[7], math.log(s0), math.log(s))
        if s < e[1]:
            e[1], e[4] = s, t - h
        if s > e[2]:
            e[2], e[5] = s, t - h
        e[3] = s
        self.s = s

    # o que o `pools.avancar` chama num grupo
    def alimentar(self, trocas, gas_wei=None, ev=None):
        for t, _b, _i, s, _liq, _v in trocas:
            self.ver(t, s)

    def fechar(self, t):
        pass

    def pulo(self):
        self.s = None
        self._salto = True

    @property
    def horas(self):
        return len(self.h)


def pedacos(e):
    """Os pedaços de uma hora do banco: [(fração da hora, √P de, √P para, peso)] pelo caminho resumido."""
    o, lo, hi, c, tlo, thi, _salto, act = e
    pts = [o, lo, hi, c] if tlo <= thi else [o, hi, lo, c]
    xs = [math.log(p) for p in pts]
    base = {}
    for a, b in zip(xs, xs[1:]):
        caminho(base, a, b)
    out = []
    for a, b in zip(xs, xs[1:]):
        if a == b:
            continue
        sobe = b > a
        x = a
        while x != b:
            k = math.floor(x / BW) if sobe else math.ceil(x / BW) - 1
            borda = (k + 1) * BW if sobe else k * BW
            y = min(b, borda) if sobe else max(b, borda)
            if y == x:  # em cima da borda: o próximo balde
                k = k + 1 if sobe else k - 1
                borda = (k + 1) * BW if sobe else k * BW
                y = min(b, borda) if sobe else max(b, borda)
            bs = base.get(k) or 0.0
            out.append((math.exp(x), math.exp(y), (act.get(k, 0.0) / bs) if bs > 0 else 1.0))
            x = y
    n = len(out)
    return [((i + 1) / (n + 1), s0, s1, p) for i, (s0, s1, p) in enumerate(out)]


# ====================================================================== os dados e o simulador
class Dados:
    """Os bancos dos pools (as horas já em pedaços) para o simulador."""

    def __init__(self, bancos, pars, gas_wei, min_horas=MIN_HORAS):
        self.pars, self.gas = pars, gas_wei
        self.horas = {}
        for pid, st in (bancos or {}).items():
            if not st or pid not in pars:
                continue
            g = st if isinstance(st, Gravador) else Gravador(st)
            hs = []
            for h in sorted(g.h):
                e = g.h[h]
                hs.append((h, dia_de(h + HORA - 1), e[6], e[0], [(h + int(f * HORA), s0, s1, p) for f, s0, s1, p in pedacos(e)],
                           e[3]))
            if len(hs) >= min_horas:
                self.horas[pid] = hs
        self.dias = {pid: [x[1] for x in hs] for pid, hs in self.horas.items()}
        hs = self.horas.get("weth_usdc") or next(iter(self.horas.values()), None)
        # o 1º dia inteiro do banco
        self.primeiro = ES.mais_dias(hs[0][1], 1) if hs else None

    @property
    def tem_dados(self):
        return bool(self.horas)

    def simular(self, genes, inicio, hoje):
        return simular(self, genes, inicio, hoje)

    @staticmethod
    def extras(c):
        return {"membros": c["membros"], "custos": c["custos"], "largadas": c["remontagens"], "taxas": c["taxas"],
                "dentroFrac": c["dentroFrac"]}


def conta_de(genes, inicio, par):
    """A `pools.Conta` de uma versão com estes genes."""
    regra = {"espera": "espera3"}.get(genes["regra"], genes["regra"])
    largura = genes["largura"] or None
    if largura is None:
        regra = "nunca"
    cfg = {"id": "ev", "vid": "ev", "nome": "ev", "largura": largura, "mult": None, "regra": regra, "risco": "médio",
           "frase": "", "gauge": False}
    opc = {"fora": genes["fora"] * HORA, "esperaDias": genes["espera"], "reinvDias": genes["reinv"]}
    c = PL.Conta(cfg, inicio, None, par, opc)
    c.marcar = lambda *a, **k: None  # a curva é marcada aqui, de hora em hora (mais rápido)
    return c


def _vazio():
    return {"serie": [], "retorno": 0.0, "piorQueda": 0.0, "ops": 0, "montou": False, "custos": 0.0, "remontagens": 0,
            "taxas": 0.0, "dentroFrac": None, "membros": []}


def simular(D, genes, inicio, hoje):
    """A conta de uma versão de `inicio` a `hoje` (dias de Brasília), de hora em hora: { serie (um ponto por dia),
    retorno, piorQueda, ops (montar + remontagens), montou, custos (gás e Krystal), remontagens, taxas, dentroFrac,
    membros }."""
    pid = genes["pool"]
    hs, dias = D.horas.get(pid), D.dias.get(pid)
    if not hs:
        return _vazio()
    i0, i1 = bisect.bisect_left(dias, inicio), bisect.bisect_right(dias, hoje)
    jan = hs[i0:i1]
    if not jan:
        return _vazio()
    par, gas = D.pars[pid], D.gas
    c = conta_de(genes, jan[0][0], par)
    serie, pico, queda, s_ant = {}, CAPITAL, 0.0, None
    for h, dia, salto, o, pcs, fim in jan:
        if salto or s_ant is None:
            c.troca(h, None, o, gas)
            s_ant = o
        for t, s0, s1, p in pcs:
            c.troca(t, s_ant, s1, gas, peso=p)
            s_ant = s1
        v = c.valor(s_ant)
        serie[dia] = v
        pico = max(pico, v)
        queda = max(queda, 1 - v / pico if pico > 0 else 0.0)
    ultimo = serie[jan[-1][1]]
    acc = c.acc
    if c.regra == "segurar" or c.largura is None:
        membros = ["faixa cheia"]
    else:
        lo, hi = c.faixa_precos()
        membros = [f"{c._txt(lo)} a {c._txt(hi)}" + ("" if c.dentro(s_ant) else " (fora)")]
    return {"serie": [[d, round(v, 2)] for d, v in sorted(serie.items())], "retorno": round(ultimo / CAPITAL - 1, 5),
            "piorQueda": round(queda, 4), "ops": int(1 + acc["repos"]), "montou": True,
            "custos": round(acc["gas"] + acc["krystal"], 2), "remontagens": int(acc["repos"]),
            "taxas": round(acc["taxas"], 2),
            "dentroFrac": round(acc["dentro"] / acc["total"], 4) if acc["total"] else None, "membros": membros}


# ====================================================================== a rodada
def _met(ctx):
    cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}

    def f(c):
        return metricas(c, cdi, cdi_ano_da_serie(cdi, CDI_PADRAO))
    return f


def avancar(ctx, est, agora, pars, gas_wei):
    """O laboratório e a liga da Faixa. Devolve o bloco `evolucao` do pools.json (None sem dados)."""
    exemplo = bool(getattr(ctx, "exemplo", False))
    bancos = {pid: (est.get("pools") or {}).get(pid, {}).get("bancoEv") for pid in POOLS_EV}
    D = Dados(bancos, {k: v for k, v in pars.items() if k in POOLS_EV}, gas_wei, 12 if exemplo else MIN_HORAS)
    if not D.tem_dados:
        return None
    P = ES.parametros(exemplo, **({} if exemplo else {"MIN_DIAS_LAB": MIN_DIAS_LAB}))
    sub = est.setdefault("evolucoes", {}).setdefault("faixa", {})
    ev = ES.rodar(sub, Definicao(), D, agora, P, ctx.log)
    return ES.resumo(ev, D, agora, "pools", "Pools", FRASE, AVISOS, _met(ctx), VERSAO,
                     horas={k: len(v) for k, v in D.horas.items()})


__all__ = ["avancar", "simular", "conta_de", "Dados", "Definicao", "Gravador", "pedacos", "caminho", "ESP"]
