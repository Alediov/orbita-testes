"""Taxa de financiamento (cash-and-carry) NO PAPEL (plano: docs/plano-testes-mercado-2.md, seção 2; formato:
tools/papel/FORMATO.md). Nenhuma ordem, nenhuma conta, nenhuma chave: só as APIs públicas de leitura da Hyperliquid.

A ideia: comprar a moeda no à vista e vender a MESMA quantidade no perpétuo. O que uma perna ganha com o preço a outra
perde, e quem está vendido no perpétuo recebe o financiamento a cada hora quando a taxa é positiva (os comprados pagam
o "aluguel" de apostar na alta). Taxa negativa: o vendido paga.

Simulação (de hora em hora, passo `t` = hora cheia):

- duas pernas: à vista (taxa de quem tira liquidez 0,07%, `TAXA_SPOT`) e perpétuo vendido (0,045%, `TAXA_PERP`),
  mais um deslize fixo por moeda (`DESLIZE`) nas duas; supomos ordem a mercado sempre (o papel fica do lado
  conservador: a ordem limite pagaria menos, mas pode não ser executada);
- preços: fechamento da vela de 1 h que termina em `t` (perpétuo pelo nome da moeda; à vista pelo par "@N", achado no
  `spotMetaAndAssetCtxs`); sem vela naquela hora, o último preço conhecido;
- financiamento: a taxa da hora `t` (`fundingHistory`) × quantidade vendida × preço do perpétuo, somada à margem;
- alavancagem L (1× ou 3×, nunca mais que `ALAV_MAX`): à vista = L ÷ (L + 1) do dinheiro, margem do vendido = 1 ÷ (L + 1)
  (1×: metade e metade; 3×: 75% e 25%); o vendido sempre do mesmo tamanho do à vista;
- liquidação do vendido (convenção do tools/mercado/sim.py): margem de manutenção = 1 ÷ (2 × alavancagem máxima da
  moeda); conferida pela MÁXIMA da vela; liquidado, perde a margem inteira e o à vista fica; na mesma hora a posição é
  remontada com o que sobrou (as versões que querem estar dentro);
- reequilíbrio: quando a margem do vendido (com o resultado dele) cai abaixo de 60% do que deveria ter pelo tamanho de
  agora, ou passa de 200%, vende (ou compra) um pouco do à vista e ajusta o vendido para voltar à divisão certa,
  pagando as taxas das duas pernas;
- base = (perpétuo − à vista) ÷ à vista, pelas velas; entra no valor marcado (as duas pernas a preços diferentes).

Entre corretoras (`entre`, só ao vivo e aproximada): comprado no perpétuo de uma corretora e vendido no da outra, na
mesma moeda, onde o financiamento previsto (`predictedFundings` da HL, que traz a Hyperliquid, a Binance e a Bybit) é
mais alto. O preço some (as duas pernas são perpétuos da mesma moeda) e sobra a DIFERENÇA das taxas. A taxa de cada
corretora só é lida a cada rodada (~3 a 4 vezes por dia) e vale até a rodada seguinte: por isso é aproximada e não há
teste no passado (a API não guarda o previsto antigo). Metade do dinheiro de margem em cada corretora (1×); entra com
diferença ≥ `ENTRE_ENTRA` ao ano (média das 2 últimas leituras), sai abaixo de `ENTRE_SAI`, troca para outra
combinação só se ela pagar `ENTRE_TROCA` a mais e a posição tiver 3 dias; taxas de quem tira liquidez das duas
corretoras + deslize nas duas pernas, e `ENTRE_PONTE` US$ para mandar dólar de uma corretora à outra a cada montagem.

Versões em `VERSOES`. O ao vivo começa quando a versão é criada e "alcança" as horas que o GitHub pulou; o teste no
passado (~180 dias de velas de 1 h) é refeito no máximo 1× por semana.
"""
from __future__ import annotations

import bisect
import copy
import datetime as dt
import math

import hl
from conta import DIA, FUSO_MS, HORA, Curva, Eventos, dia_de, moeda_br, num_br, pct_br

NOME = "Funding"
VERSAO = 1

TAXA_SPOT = 0.0007       # à vista, quem tira liquidez, nível base
TAXA_SPOT_LIVRO = 0.0004  # à vista, ordem limite (não usada: supomos ordem a mercado)
TAXA_PERP = 0.00045      # perpétuo, quem tira liquidez, nível base
TAXA_PERP_LIVRO = 0.00015
DESLIZE = {"BTC": 0.0003, "ETH": 0.0004, "SOL": 0.0008, "HYPE": 0.0008}  # por perna, pelo tamanho pequeno
MOEDAS = ["BTC", "ETH", "HYPE", "SOL"]
TOKENS = {"BTC": "UBTC", "ETH": "UETH", "SOL": "USOL", "HYPE": "HYPE"}
PARES_PADRAO = {"BTC": "@142", "ETH": "@151", "SOL": "@156", "HYPE": "@107"}
ALAV_MAX_PADRAO = {"BTC": 40, "ETH": 25, "SOL": 20, "HYPE": 10}  # se o metaAndAssetCtxs falhar
ALAV_MAX = 3             # regra do Alediov: no funding, no máximo 3×
ANO_H = 24 * 365
JANELA_MEDIA = 72        # horas: a média de 3 dias do financiamento
REEQ_BAIXO, REEQ_ALTO = 0.6, 2.0
SELETIVA_ENTRA, SELETIVA_SAI = 0.10, 0.03   # ao ano
RODIZIO_SEMANA = 7 * DIA
RODIZIO_DIFERENCA = 0.05  # ao ano: só troca se a melhor estiver 5 pontos acima (a troca custa ~0,3% do valor)
HIST_DIAS = 180
HIST_REFAZER = 7 * DIA
HIST_TEMPO_MIN = 300     # segundos que precisam sobrar na rodada para refazer o teste no passado
ALCANCE_MAX = 195 * DIA  # as velas de 1 h só vão até ~200 dias atrás
ENTRE_ENTRA, ENTRE_SAI, ENTRE_TROCA = 0.08, 0.02, 0.06   # ao ano
ENTRE_MIN_TROCA = 3 * DIA
ENTRE_TAXA = {"hl": 0.00045, "binance": 0.0005, "bybit": 0.00055}   # quem tira liquidez, nível base
ENTRE_PONTE = 1.0          # US$ por montagem (saque e depósito de USDC entre as corretoras)
ENTRE_LEITURAS = 120       # as últimas leituras do previsto guardadas no estado
CORRETORA = {"hl": "Hyperliquid", "binance": "Binance", "bybit": "Bybit"}
FOLGA_MS = 5 * 60_000    # o financiamento da hora sai alguns segundos depois: não processa a hora que acabou de virar

# (id, nome, moedas, alavancagem, regra, risco, frase)
VERSOES = [
    ("btc1", "BTC 1×", ["BTC"], 1, "fixa", "baixo",
     "Metade do dinheiro compra bitcoin no à vista; a outra metade é a margem do vendido no perpétuo."),
    ("eth1", "ETH 1×", ["ETH"], 1, "fixa", "baixo",
     "O mesmo com o ether: metade no à vista, metade de margem do vendido."),
    ("hype1", "HYPE 1×", ["HYPE"], 1, "fixa", "médio",
     "Com o HYPE, a moeda da própria Hyperliquid: o financiamento costuma ser mais alto e o preço balança mais."),
    ("sol1", "SOL 1×", ["SOL"], 1, "fixa", "médio",
     "Com o solana, metade e metade; o à vista é o USOL, uma versão embrulhada vinda por uma ponte."),
    ("btc3", "BTC 3×", ["BTC"], 3, "fixa", "médio",
     "75% no à vista e só 25% de margem: rende mais por dólar, mas uma alta forte obriga a reequilibrar e pode liquidar."),
    ("seletiva", "Seletiva", ["BTC"], 1, "seletiva", "baixo",
     "Só monta quando o financiamento médio de 3 dias passa de 10% ao ano e sai abaixo de 3%; fora, o dinheiro fica parado."),
    ("seletiva3", "Seletiva 3×", ["BTC"], 3, "seletiva", "médio",
     "A seletiva com 75% no à vista e 25% de margem."),
    ("rodizio", "Rodízio", ["BTC", "ETH", "HYPE", "SOL"], 1, "rodizio", "médio",
     "Fica na moeda de financiamento médio de 3 dias mais alto entre as 4 e troca no máximo uma vez por semana, pagando a troca."),
]

FRASE = ("Compra a moeda e vende a mesma quantidade no perpétuo: o preço deixa de importar e você recebe a taxa de "
         "financiamento a cada hora.")
COMO_FUNCIONA = [
    "Na Hyperliquid, quem aposta na alta com o perpétuo paga, a cada hora, uma taxa a quem aposta na queda "
    "(o financiamento). Quando muita gente está comprada, a taxa fica positiva e quem está vendido recebe.",
    "Aqui a conta compra a moeda no à vista e vende a mesma quantidade no perpétuo. Se o preço sobe, o à vista ganha "
    "o que o vendido perde (e vice-versa): o que sobra é o financiamento, menos as taxas.",
    "Com 1×, metade do dinheiro fica no à vista e metade de margem do vendido. Com 3×, 75% e 25%: rende mais, mas "
    "uma alta forte come a margem; quando ela cai a 60% do necessário, a conta vende um pouco do à vista para repor.",
    "A taxa pode ficar negativa por dias: aí o vendido paga. A seletiva só monta quando a média de 3 dias passa de "
    "10% ao ano, e o rodízio fica na moeda que paga mais.",
    "Taxas das duas pernas na entrada, na saída e em cada reequilíbrio (à vista 0,07%, perpétuo 0,045%, mais um "
    "deslize de 0,03% a 0,08%) já estão descontadas.",
    "Entre corretoras: em vez do à vista, a outra perna é o perpétuo de OUTRA corretora (comprado onde a taxa é baixa, "
    "vendido onde é alta). Sobra só a diferença das taxas. Só existe ao vivo, e é aproximada: as taxas previstas da "
    "Binance e da Bybit são lidas a cada rodada.",
]
AVISOS = [
    "UBTC, UETH e USOL são versões “embrulhadas” que chegam por uma ponte de outra rede: em dias ruins o preço delas "
    "pode descolar do bitcoin, do ether e do solana de verdade, e a proteção deixa de ser perfeita.",
    "Nos dias de pânico a corretora pode fechar o vendido sozinha (desalavancagem automática, a ADL) para cobrir "
    "outras contas; a moeda fica sem proteção até montar de novo, e o papel não mostra isso.",
    "O papel compra e vende pelo preço da vela com um deslize fixo; no à vista a fila de ordens é curta, e uma conta "
    "grande pagaria bem mais para entrar e sair.",
    "Risco de corretora: as duas pernas ficam dentro da Hyperliquid; se ela parar, for atacada ou travar os saques, o "
    "dinheiro inteiro fica preso, e isso nenhum teste no papel mede.",
    "O financiamento entra pelo preço de fechamento de cada hora; na corretora ele usa o preço do oráculo, que difere "
    "um pouco.",
    "Entre corretoras: as taxas da Binance e da Bybit são as previstas que a Hyperliquid publica, lidas só a cada rodada; "
    "os preços dos dois perpétuos podem descolar por minutos e o dinheiro fica em duas corretoras (dois riscos de "
    "corretora, e a Binance e a Bybit pedem cadastro com documento).",
]
ENTRE_FRASE = ("Comprado no perpétuo de uma corretora e vendido no de outra onde o financiamento é maior (Hyperliquid, "
               "Binance ou Bybit): ganha a diferença das taxas. Aproximada: as taxas são lidas a cada rodada.")


# ---------------------------------------------------------------------------------------------------- utilidades
def _f(x, padrao=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else padrao
    except (TypeError, ValueError):
        return padrao


def hora_de(ms):
    return (int(ms) // HORA) * HORA


def semana_de(ms):
    """Início (ms) da semana de Brasília (segunda-feira, 0h) que contém `ms`."""
    dias = (int(ms) + FUSO_MS) // DIA
    seg = dias - (dias + 3) % 7  # 01/01/1970 foi quinta-feira
    return seg * DIA - FUSO_MS


def _ddmm(ms):
    return dt.datetime.fromtimestamp((ms + FUSO_MS) / 1000, dt.timezone.utc).strftime("%d/%m")


def _qtd(q, preco):
    return num_br(q, 4 if preco >= 1000 else 3 if preco >= 50 else 2)


def _preco_txt(p):
    return moeda_br(p, 0 if p >= 1000 else 2)


def ao_ano(taxa_hora):
    return taxa_hora * ANO_H


# ---------------------------------------------------------------------------------------------------- dados
class Dados:
    """Velas de 1 h do perpétuo e do à vista e o financiamento de hora em hora, por moeda."""

    def __init__(self, perp=None, spot=None, funding=None, alav_max=None):
        # perp/spot: moeda → lista de velas no formato da API ({t, h, c…}); funding: moeda → lista ({time, fundingRate})
        self.perp, self.spot, self.fund = {}, {}, {}
        for m, lista in (perp or {}).items():
            self.perp[m] = self._velas(lista)
        for m, lista in (spot or {}).items():
            self.spot[m] = self._velas(lista)
        for m, lista in (funding or {}).items():
            d = {}
            for x in lista or []:
                t, r = _f(x.get("time")), _f(x.get("fundingRate"))
                if t is not None and r is not None:
                    d[hora_de(t)] = r
            self.fund[m] = d
        self.alav_max = dict(ALAV_MAX_PADRAO)
        self.alav_max.update({k: v for k, v in (alav_max or {}).items() if v})
        self._med = {}

    @staticmethod
    def _velas(lista):
        d = {}
        for c in lista or []:
            t, h, fe = _f(c.get("t")), _f(c.get("h")), _f(c.get("c"))
            if t is not None and fe is not None and fe > 0:
                d[int(t)] = (h if h and h > 0 else fe, fe)
        ts = sorted(d)
        return (ts, [d[t] for t in ts])

    def primeira(self, m):
        ts = self.perp.get(m, ([], []))[0]
        return ts[0] + HORA if ts else None

    @staticmethod
    def _em(serie, t):
        """(máxima, fechamento, exata) da vela que termina em t (aberta em t − 1 h); sem ela, o último fechamento."""
        ts, vs = serie
        i = bisect.bisect_right(ts, t - HORA) - 1
        if i < 0:
            return None
        h, c = vs[i]
        exata = ts[i] == t - HORA
        return (h if exata else c, c, exata)

    def precos(self, m, t):
        """(perpétuo, máxima do perpétuo na hora, à vista) em t; à vista ausente → o do perpétuo."""
        p = self._em(self.perp.get(m, ([], [])), t)
        if not p:
            return None
        s = self._em(self.spot.get(m, ([], [])), t)
        return p[1], p[0], (s[1] if s else p[1])

    def taxa(self, m, t):
        return self.fund.get(m, {}).get(hora_de(t))

    def media(self, m, t, horas=JANELA_MEDIA):
        """Média por hora do financiamento nas `horas` até t (inclusive); None sem dados."""
        k = (m, hora_de(t), horas)
        if k not in self._med:
            d = self.fund.get(m, {})
            vs = [d[h] for h in range(hora_de(t) - (horas - 1) * HORA, hora_de(t) + 1, HORA) if h in d]
            self._med[k] = sum(vs) / len(vs) if vs else None
        return self._med[k]

    def mmr(self, m):
        return 1 / (2 * max(1, int(self.alav_max.get(m) or ALAV_MAX_PADRAO.get(m, 20))))


# ---------------------------------------------------------------------------------------------------- posição
class Posicao:
    """As duas pernas: `qs` moedas no à vista, `qp` vendidas no perpétuo (entrada `entrada`, margem `margem`) e o caixa."""

    def __init__(self, caixa=0.0):
        self.qs = self.qp = self.margem = self.entrada = 0.0
        self.caixa = float(caixa)

    def valor(self, ps, pp):
        return self.caixa + self.qs * ps + self.margem + self.qp * (self.entrada - pp)

    def margem_viva(self, pp):
        return self.margem + self.qp * (self.entrada - pp)

    def montar(self, ps, pp, alav, cs, cp):
        """Leva as pernas à divisão certa (q no à vista = q vendido; margem = q × pp ÷ alav) a partir de qualquer estado
        (caixa, desequilibrado, depois de uma liquidação). cs/cp: custo por dólar negociado (taxa + deslize) do à vista e
        do perpétuo. Devolve (custo em US$, pernas negociadas, variação do à vista)."""
        v = self.valor(ps, pp)
        k = ps + pp / alav
        q = v / k
        custo = 0.0
        for _ in range(4):
            custo = abs(q - self.qs) * ps * cs + abs(q - self.qp) * pp * cp
            q = max(0.0, (v - custo) / k)
        pernas = int(abs(q - self.qs) * ps > 0.01) + int(abs(q - self.qp) * pp > 0.01)
        dq = q - self.qs
        self.qs = self.qp = q
        self.entrada = pp
        self.margem = q * pp / alav
        self.caixa = max(0.0, v - custo - q * k)
        return custo, pernas, dq

    def desmontar(self, ps, pp, cs, cp):
        """Vende o à vista e recompra o vendido. Devolve (custo, pernas)."""
        custo = self.qs * ps * cs + self.qp * pp * cp
        pernas = int(self.qs > 0) + int(self.qp > 0)
        self.caixa = max(0.0, self.valor(ps, pp) - custo)
        self.qs = self.qp = self.margem = self.entrada = 0.0
        return custo, pernas

    def financiar(self, taxa, pp):
        """O vendido recebe taxa × valor quando a taxa é positiva (paga quando negativa). Devolve o valor (US$)."""
        v = self.qp * pp * taxa
        self.margem += v
        return v

    def preco_liquidacao(self, mmr):
        if self.qp <= 0:
            return None
        return (self.margem + self.qp * self.entrada) / (self.qp * (1 + mmr))

    def liquidar_se(self, maxima, mmr):
        """Liquida o vendido se a máxima da hora alcançou o preço de liquidação. Devolve a margem perdida ou None."""
        pl = self.preco_liquidacao(mmr)
        if pl is None or maxima < pl:
            return None
        perda = max(0.0, self.margem)
        self.qp = self.margem = self.entrada = 0.0
        return perda

    def fora_do_ponto(self, pp, alav):
        """True se a margem viva saiu da faixa de reequilíbrio (60% a 200% do que deveria ter) ou as pernas diferem."""
        if self.qs <= 0 and self.qp <= 0:
            return False
        if abs(self.qs - self.qp) > 1e-9 * max(1.0, self.qs):
            return True
        alvo = self.qp * pp / alav
        r = self.margem_viva(pp) / alvo if alvo > 0 else 1
        return r < REEQ_BAIXO or r > REEQ_ALTO

    def para_json(self):
        return {"qs": self.qs, "qp": self.qp, "margem": self.margem, "entrada": self.entrada, "caixa": self.caixa}

    @classmethod
    def de_json(cls, d):
        p = cls()
        for k in ("qs", "qp", "margem", "entrada", "caixa"):
            setattr(p, k, float((d or {}).get(k, 0.0)))
        return p


def custos(m):
    d = DESLIZE.get(m, 0.001)
    return TAXA_SPOT + d, TAXA_PERP + d


# ---------------------------------------------------------------------------------------------------- versão
class Conta:
    """Uma versão andando no tempo: decide entrar, sair, trocar ou reequilibrar a cada hora."""

    def __init__(self, cfg, inicio, estado=None):
        self.id, self.nome, self.moedas, self.alav, self.regra, self.risco, self.frase = cfg
        assert self.alav <= ALAV_MAX
        e = estado or {}
        self.curva = Curva.de_json(e.get("curva")) or Curva(inicio=inicio)
        self.pos = Posicao.de_json(e["pos"]) if e.get("pos") else Posicao(self.curva.capital)
        self.moeda = e.get("moeda") or self.moedas[0]
        self.dentro = bool(e.get("dentro"))
        self.t = int(e.get("t") or inicio)
        self.novo = not estado
        self.troca = e.get("troca")
        self.entrada_valor = e.get("entradaValor")
        a = e.get("acc") or {}
        self.acc = {k: float(a.get(k, 0.0)) for k in ("rec", "pag", "bS", "bN", "fS", "fN", "dS", "dN")}
        self.semana = e.get("semana") or {"ini": semana_de(self.t), "liq": 0.0}
        self.precos = e.get("precos") or {}  # moeda → [pp, ps] do último passo

    def para_json(self):
        return {"curva": self.curva.para_json(), "pos": self.pos.para_json(), "moeda": self.moeda, "dentro": self.dentro,
                "t": self.t, "troca": self.troca, "entradaValor": self.entrada_valor, "acc": self.acc,
                "semana": self.semana, "precos": self.precos}

    # ------------------------------------------------------------------ eventos
    def _ev(self, ev, t, tipo, texto):
        if ev is not None:
            ev.add(t, tipo, texto, self.id)

    def _semana(self, t, ev):
        ini = semana_de(t)
        s = self.semana
        if ini != s["ini"]:
            liq = s["liq"]
            if abs(liq) >= 0.005:
                periodo = f"na semana de {_ddmm(s['ini'])} a {_ddmm(ini - DIA)}"
                if liq > 0:
                    self._ev(ev, ini, "recebeu", f"Recebeu {moeda_br(liq)} de financiamento {periodo}.")
                else:
                    self._ev(ev, ini, "pagou", f"Pagou {moeda_br(-liq)} de financiamento {periodo}: "
                                               "a taxa ficou negativa e quem está vendido paga.")
            self.semana = {"ini": ini, "liq": 0.0}

    # ------------------------------------------------------------------ operações
    def _montar(self, d, t, ev, tipo, texto_antes=""):
        m = self.moeda
        pr = d.precos(m, t)
        if not pr:
            return False
        pp, _h, ps = pr
        cs, cp = custos(m)
        antes_qp = self.pos.qp
        custo, pernas, dq = self.pos.montar(ps, pp, self.alav, cs, cp)
        self.curva.operou(custo, pernas)
        if tipo in ("abriu", "entrou", "trocou"):
            self.entrada_valor = self.pos.valor(ps, pp)
            self.dentro = True
            self._ev(ev, t, tipo, f"{texto_antes}Montou a posição em {m}: comprou {_qtd(self.pos.qs, ps)} no à vista e "
                                  f"vendeu {_qtd(self.pos.qp, pp)} no perpétuo a {_preco_txt(pp)}.")
        elif tipo == "reequilibrou" and pernas:
            if dq < 0:
                txt = (f"Reequilibrou a margem: vendeu {_qtd(-dq, ps)} {m} do à vista e recomprou o mesmo no perpétuo "
                       f"para repor a margem do vendido (custou {moeda_br(custo)}).")
            else:
                txt = (f"Reequilibrou: a margem do vendido tinha sobrado, então comprou mais {_qtd(dq, ps)} {m} no à vista "
                       f"e vendeu o mesmo no perpétuo (custou {moeda_br(custo)}).")
            if antes_qp <= 0 < self.pos.qp:
                txt = f"Remontou o vendido de {m} depois da liquidação (custou {moeda_br(custo)})."
            self._ev(ev, t, "reequilibrou", txt)
        return True

    def _desmontar(self, d, t, ev, texto=None):
        m = self.moeda
        pr = d.precos(m, t)
        if not pr:
            return False
        pp, _h, ps = pr
        cs, cp = custos(m)
        custo, pernas = self.pos.desmontar(ps, pp, cs, cp)
        self.curva.operou(custo, pernas)
        if self.entrada_valor is not None:
            self.curva.fechou(self.pos.caixa - self.entrada_valor)
        self.entrada_valor = None
        self.dentro = False
        if texto:
            self._ev(ev, t, "saiu", texto)
        return True

    # ------------------------------------------------------------------ passo
    def passo(self, t, d, ev=None):
        """A hora `t` (cheia): liquidação pela máxima, financiamento, regra da versão, reequilíbrio e marcação."""
        self.t = t
        self._semana(t, ev)
        m = self.moeda
        pr = d.precos(m, t)
        if pr and self.dentro and self.pos.qp > 0:
            pp, h, ps = pr
            perda = self.pos.liquidar_se(h, d.mmr(m))
            if perda is not None:
                self.curva.liquidou(t, m, perda)
                self._ev(ev, t, "liquidou", f"Liquidado o vendido de {m}: a moeda subiu até {_preco_txt(h)} e a conta perdeu "
                                            f"{moeda_br(perda)} de margem; o à vista ficou com a conta.")
            taxa = d.taxa(m, t)
            if taxa is not None and self.pos.qp > 0:
                v = self.pos.financiar(taxa, pp)
                self.acc["rec" if v >= 0 else "pag"] += abs(v)
                self.semana["liq"] += v
            if taxa is not None:
                self.acc["dS"] += taxa
                self.acc["dN"] += 1
            self.acc["bS"] += pp / ps - 1
            self.acc["bN"] += 1
        tx = d.taxa(m, t)
        if tx is not None:
            self.acc["fS"] += tx
            self.acc["fN"] += 1

        getattr(self, "_regra_" + self.regra)(t, d, ev)

        if self.dentro and self.pos.qs + self.pos.qp > 0:
            pr = d.precos(self.moeda, t)
            if pr and self.pos.fora_do_ponto(pr[0], self.alav):
                self._montar(d, t, ev, "reequilibrou")
        self._marcar(t, d)
        self._extra()

    def _marcar(self, t, d):
        m = self.moeda
        pr = d.precos(m, t)
        if pr:
            self.precos[m] = [pr[0], pr[2]]
        pp, ps = self.precos.get(m, [0.0, 0.0])
        self.curva.marcar(t, self.pos.valor(ps, pp) if pp else self.pos.caixa)

    def _extra(self):
        a = self.acc
        if a["dN"]:
            fano = ao_ano(a["dS"] / a["dN"])
        elif a["fN"]:
            fano = ao_ano(a["fS"] / a["fN"])
        else:
            fano = None
        self.curva.extra = {"recebido": round(a["rec"], 4), "pago": round(a["pag"], 4),
                            "base": round(a["bS"] / a["bN"], 6) if a["bN"] else None,
                            "fundingAno": round(fano, 4) if fano is not None else None,
                            "moeda": self.moeda, "dentro": self.dentro}

    # ------------------------------------------------------------------ regras
    def _regra_fixa(self, t, d, ev):
        if not self.dentro:
            self._montar(d, t, ev, "abriu")

    def _regra_seletiva(self, t, d, ev):
        med = d.media(self.moeda, t)
        if med is None:
            return
        a = ao_ano(med)
        if not self.dentro and a > SELETIVA_ENTRA:
            self._montar(d, t, ev, "entrou", f"Entrou: o financiamento médio de 3 dias subiu para {pct_br(a)} ao ano. ")
        elif self.dentro and a < SELETIVA_SAI:
            self._desmontar(d, t, ev, f"Saiu: o financiamento caiu para {pct_br(a)} ao ano; o dinheiro fica parado até "
                                      f"voltar a passar de {pct_br(SELETIVA_ENTRA, 0)}.")

    def _regra_rodizio(self, t, d, ev):
        medias = {m: d.media(m, t) for m in self.moedas}
        medias = {m: v for m, v in medias.items() if v is not None and d.precos(m, t)}
        if not medias:
            if not self.dentro:
                self._montar(d, t, ev, "abriu")
            return
        melhor = max(medias, key=lambda m: medias[m])
        if not self.dentro:
            self.moeda = melhor
            self.troca = t
            self._montar(d, t, ev, "abriu", f"Escolheu {melhor} (financiamento médio de 3 dias: "
                                            f"{pct_br(ao_ano(medias[melhor]))} ao ano). ")
            return
        atual = medias.get(self.moeda)
        if (melhor != self.moeda and t - (self.troca or 0) >= RODIZIO_SEMANA
                and (atual is None or ao_ano(medias[melhor] - atual) >= RODIZIO_DIFERENCA)):
            de = self.moeda
            texto = (f"Trocou de {de} para {melhor}: o financiamento médio de 3 dias de {melhor} estava em "
                     f"{pct_br(ao_ano(medias[melhor]))} ao ano ({de}: "
                     f"{pct_br(ao_ano(atual)) if atual is not None else 'sem dados'}). ")
            self._desmontar(d, t, None)
            self._marcar(t, d)  # o preço da moeda antiga fica guardado
            self.moeda = melhor
            self.troca = t
            self._montar(d, t, ev, "trocou", texto)


# ---------------------------------------------------------------------------------------------------- API
def pares_spot(cli, log, erros):
    """moeda → nome do par à vista ("@142"…), pelo spotMetaAndAssetCtxs; na falha, os nomes conhecidos."""
    pares = dict(PARES_PADRAO)
    try:
        r = cli.spot_meta_e_contextos()
        meta = r[0] if isinstance(r, list) and r else (r or {})
        ctxs = r[1] if isinstance(r, list) and len(r) > 1 else []
        nomes = {}
        for i, tk in enumerate(meta.get("tokens") or []):
            nomes[int(tk.get("index", i))] = str(tk.get("name") or "")
        usdc = next((i for i, n in nomes.items() if n == "USDC"), 0)
        vol = {}
        for i, c in enumerate(ctxs or []):
            if isinstance(c, dict):
                vol[c.get("coin") or i] = _f(c.get("dayNtlVlm"), 0.0)
        achados = {}
        for pos, u in enumerate(meta.get("universe") or []):
            tks = u.get("tokens") or []
            if len(tks) != 2 or int(tks[1]) != usdc:
                continue
            base = nomes.get(int(tks[0]))
            for m, tk in TOKENS.items():
                if base == tk and u.get("name"):
                    v = vol.get(u["name"], vol.get(pos, 0.0)) or 0.0
                    if m not in achados or v > achados[m][1]:
                        achados[m] = (u["name"], v)
        for m, (nome, _v) in achados.items():
            pares[m] = nome
        falta = [m for m in MOEDAS if m not in achados]
        if falta:
            log(f"  funding: par à vista não achado para {', '.join(falta)}; usando {', '.join(PARES_PADRAO[m] for m in falta)}")
    except (hl.Erro, KeyError, TypeError, ValueError, AttributeError) as e:
        erros.append(f"pares do à vista: {e}")
        log(f"  funding: pares do à vista ({e}); usando os conhecidos")
    return pares


def contextos(cli, erros):
    """(alavancagem máxima por moeda, financiamento de agora por moeda), pelo metaAndAssetCtxs."""
    lev, agora = {}, {}
    try:
        meta, ctxs = cli.meta_e_contextos()
        for u, c in zip(meta.get("universe") or [], ctxs or []):
            n = u.get("name")
            if n in MOEDAS:
                lev[n] = int(_f(u.get("maxLeverage"), 0) or 0) or None
                agora[n] = _f((c or {}).get("funding"))
    except (hl.Erro, KeyError, TypeError, ValueError) as e:
        erros.append(f"contextos do perpétuo: {e}")
    return lev, agora


def previstos(cli, erros):
    """moeda → {hl, binance, bybit} do financiamento previsto, ao ano."""
    out = {}
    nomes = {"HlPerp": "hl", "BinPerp": "binance", "BybitPerp": "bybit"}
    try:
        for item in cli.funding_previsto() or []:
            if not isinstance(item, list) or len(item) < 2 or item[0] not in MOEDAS:
                continue
            d = {}
            for par in item[1] or []:
                if not isinstance(par, list) or len(par) < 2 or not isinstance(par[1], dict):
                    continue
                r = _f(par[1].get("fundingRate"))
                h = _f(par[1].get("fundingIntervalHours"), 1) or 1
                if r is not None and par[0] in nomes:
                    d[nomes[par[0]]] = round(r / h * ANO_H, 4)
            out[item[0]] = d
    except (hl.Erro, KeyError, TypeError, ValueError) as e:
        erros.append(f"financiamento previsto: {e}")
    return out


class Entre:
    """A versão entre corretoras (ver o começo do arquivo). Estado: curva, posição, a leitura anterior e o acumulado."""

    def __init__(self, inicio, estado=None):
        e = estado or {}
        self.curva = Curva.de_json(e.get("curva")) or Curva(inicio=inicio)
        self.pos = e.get("pos")          # {moeda, longo, curto, desde} ou None
        self.t = int(e.get("t") or inicio)
        self.antes = e.get("antes")      # a leitura (moeda → corretora → taxa ao ano) usada de t até agora
        self.leituras = list(e.get("leituras") or [])
        a = e.get("acc") or {}
        self.acc = {k: float(a.get(k, 0.0)) for k in ("recebido", "pago", "trocas")}

    def para_json(self):
        return {"curva": self.curva.para_json(), "pos": self.pos, "t": self.t, "antes": self.antes,
                "leituras": self.leituras[-ENTRE_LEITURAS:], "acc": self.acc}

    @staticmethod
    def diferenca(leit, moeda, longo, curto):
        d = (leit or {}).get(moeda) or {}
        if d.get(longo) is None or d.get(curto) is None:
            return None
        return d[curto] - d[longo]

    def melhor(self, agora_l):
        """(diferença ao ano pela média das 2 últimas leituras, moeda, longo, curto) da melhor combinação, ou None."""
        anterior = self.leituras[-1][1] if self.leituras else None
        melhor = None
        for m, d in (agora_l or {}).items():
            cs = [c for c in ("hl", "binance", "bybit") if d.get(c) is not None]
            for lo in cs:
                for cu in cs:
                    if lo == cu:
                        continue
                    x = self.diferenca(agora_l, m, lo, cu)
                    y = self.diferenca(anterior, m, lo, cu)
                    v = x if y is None else (x + y) / 2
                    if melhor is None or v > melhor[0]:
                        melhor = (v, m, lo, cu)
        return melhor

    def custo(self, moeda, longo, curto, nocional):
        des = DESLIZE.get(moeda, 0.0008)
        return nocional * (ENTRE_TAXA[longo] + ENTRE_TAXA[curto] + 2 * des)

    def _texto(self, p):
        return f"comprado na {CORRETORA[p['longo']]} e vendido na {CORRETORA[p['curto']]} ({p['moeda']})"

    def passo(self, agora, leit, ev):
        """Anda de `t` até `agora` com a leitura anterior e decide com a de agora."""
        V = self.curva.ultimo if self.curva.ultimo > 0 else self.curva.capital
        if self.pos and self.antes and agora > self.t:
            dif = self.diferenca(self.antes, self.pos["moeda"], self.pos["longo"], self.pos["curto"])
            if dif is not None:
                ganho = V / 2 * dif * (agora - self.t) / (365 * DIA)
                V += ganho
                self.acc["recebido" if ganho >= 0 else "pago"] += abs(ganho)
        self.curva.marcar(agora, V)
        m = self.melhor(leit)
        sair = trocar = False
        if self.pos:
            # a mesma média das 2 últimas leituras da entrada: uma leitura ruim sozinha não desmonta
            atual = self.diferenca(leit, self.pos["moeda"], self.pos["longo"], self.pos["curto"])
            ant = self.diferenca(self.leituras[-1][1] if self.leituras else None, self.pos["moeda"], self.pos["longo"],
                                 self.pos["curto"])
            if atual is not None and ant is not None:
                atual = (atual + ant) / 2
            if atual is None or atual < ENTRE_SAI:
                sair = True
            elif m and (m[1], m[2], m[3]) != (self.pos["moeda"], self.pos["longo"], self.pos["curto"]) \
                    and m[0] - atual >= ENTRE_TROCA and agora - int(self.pos["desde"]) >= ENTRE_MIN_TROCA:
                trocar = True
        if self.pos and (sair or trocar):
            c = self.custo(self.pos["moeda"], self.pos["longo"], self.pos["curto"], V / 2)
            V -= c
            self.curva.operou(c, 2)
            ev.add(agora, "saiu", f"Desmontou ({self._texto(self.pos)}): a diferença das taxas caiu"
                                  f"{' e outra combinação paga mais' if trocar else ''} (custou {moeda_br(c)}).", "entre")
            self.pos = None
            self.curva.marcar(agora, V)
        if not self.pos and m and m[0] >= ENTRE_ENTRA:
            c = self.custo(m[1], m[2], m[3], V / 2) + ENTRE_PONTE
            V -= c
            self.curva.operou(c, 2)
            self.acc["trocas"] += 1
            self.pos = {"moeda": m[1], "longo": m[2], "curto": m[3], "desde": agora}
            ev.add(agora, "entrou", f"Montou {self._texto(self.pos)}: a diferença prevista é de {pct_br(m[0])} ao ano "
                                    f"(custou {moeda_br(c)}).", "entre")
            self.curva.marcar(agora, V)
        if leit:
            self.leituras.append([agora, leit])
            self.leituras = self.leituras[-ENTRE_LEITURAS:]
        self.antes, self.t = leit or self.antes, agora
        dif = self.diferenca(leit, self.pos["moeda"], self.pos["longo"], self.pos["curto"]) if self.pos else None
        self.curva.extra = {"recebido": round(self.acc["recebido"], 4), "pago": round(self.acc["pago"], 4),
                            "moeda": self.pos["moeda"] if self.pos else None, "dentro": bool(self.pos),
                            "longo": CORRETORA[self.pos["longo"]] if self.pos else None,
                            "curto": CORRETORA[self.pos["curto"]] if self.pos else None,
                            "diferencaAno": round(dif, 4) if dif is not None else None,
                            "fundingAno": round(dif, 4) if dif is not None else None, "base": None,
                            "montagens": int(self.acc["trocas"]), "leituras": len(self.leituras)}


def buscar(cli, pares, ini, fim, lev, log, erros):
    """As velas de 1 h (perpétuo e à vista) e o financiamento das 4 moedas entre ini e fim. Falha do perpétuo ou do
    financiamento: levanta (a forma fica ok: false); falha do à vista: segue com o preço do perpétuo e anota."""
    perp, spot, fund = {}, {}, {}
    for m in MOEDAS:
        perp[m] = cli.velas(m, "1h", ini, fim)
        fund[m] = cli.financiamento(m, ini, fim)
        try:
            spot[m] = cli.velas(pares[m], "1h", ini, fim)
            if not spot[m]:
                log(f"  funding: sem velas do à vista {pares[m]} ({m}); usando o perpétuo")
        except hl.Erro as e:
            spot[m] = []
            erros.append(f"velas do à vista de {m} ({pares[m]}): {e}")
    return Dados(perp, spot, fund, lev)


# ---------------------------------------------------------------------------------------------------- simulação
def horas(a, b):
    """As horas cheias de a (exclusive) até b (inclusive)."""
    t = hora_de(a) + HORA
    while t <= b:
        yield t
        t += HORA


def teste_no_passado(d, ini, fim):
    """Todas as versões no passado, de `ini` a `fim` (horas cheias), com contas novas. Devolve id → conta (resumo)."""
    out = {}
    for cfg in VERSOES:
        c = Conta(cfg, ini)
        c.passo(ini, d)
        for t in horas(ini, fim):
            c.passo(t, d)
        out[cfg[0]] = c.curva.resumo(de=dia_de(ini), ate=dia_de(fim), aproximado=False)
    return out


def rodar(ctx):
    erros = []
    est = copy.deepcopy(ctx.est)  # só volta para ctx.est se a rodada der certo
    cli, agora, log = ctx.cli, int(ctx.agora), ctx.log
    fim = hora_de(agora - FOLGA_MS)

    pares = pares_spot(cli, log, erros)
    lev, agora_f = contextos(cli, erros)
    prev = previstos(cli, erros)

    vivo = est.setdefault("vivo", {})
    hist = est.get("hist") or {}
    cursores = [int(v.get("t") or fim) for v in vivo.values()] + [fim]
    ini_vivo = min(cursores)
    if ini_vivo < fim - ALCANCE_MAX:
        log(f"  funding: {(fim - ini_vivo) // DIA} dias sem rodar; só há velas de 1 h dos últimos ~200: o ao vivo pula o resto")
        ini_vivo = fim - ALCANCE_MAX
    refazer = (not hist or agora - int(hist.get("em") or 0) >= HIST_REFAZER or hist.get("v") != VERSAO)
    if refazer and ctx.restante() < HIST_TEMPO_MIN:
        log(f"  funding: pouco tempo na rodada ({ctx.restante():.0f} s); o teste no passado fica para a próxima")
        refazer = False
    ini_hist = fim - HIST_DIAS * DIA
    ini = min(ini_vivo, ini_hist if refazer else ini_vivo) - (JANELA_MEDIA + 1) * HORA
    d = buscar(cli, pares, ini, agora, lev, log, erros)

    # ---------------------------------------------------------------- ao vivo
    ev = Eventos(est.get("eventos"))
    for cfg in VERSOES:
        vid = cfg[0]
        try:
            antes = vivo.get(vid)
            c = Conta(cfg, fim, antes)
            if antes and c.t < ini_vivo:
                c.t = ini_vivo
            if c.novo:
                c.passo(fim, d, ev)
            else:
                for t in horas(c.t, fim):
                    c.passo(t, d, ev)
            vivo[vid] = c.para_json()
        except Exception as e:  # noqa: BLE001  (uma versão com problema não derruba as outras)
            erros.append(f"{vid} ao vivo: {e}")
            log(f"  funding: {vid} ao vivo: {e}")

    # ---------------------------------------------------------------- entre corretoras (só ao vivo)
    try:
        en = Entre(fim, est.get("entre"))
        leit = {m: {k: v for k, v in (prev.get(m) or {}).items() if v is not None} for m in MOEDAS}
        leit = {m: d for m, d in leit.items() if len(d) >= 2}
        en.passo(int(agora), leit, ev)
        est["entre"] = en.para_json()
    except Exception as e:  # noqa: BLE001
        erros.append(f"entre corretoras: {e}")
        log(f"  funding: entre corretoras: {e}")

    # ---------------------------------------------------------------- teste no passado
    if refazer:
        try:
            primeira = max([x for x in (d.primeira(m) for m in MOEDAS) if x] or [ini_hist])
            t0 = hora_de(max(ini_hist, primeira) + HORA - 1)
            res = teste_no_passado(d, t0, fim)
            hist = {"v": VERSAO, "em": agora, "de": t0, "ate": fim, "versoes": res}
            est["hist"] = hist
            log(f"  funding: teste no passado refeito ({dia_de(t0)} a {dia_de(fim)})")
        except Exception as e:  # noqa: BLE001
            erros.append(f"teste no passado: {e}")
            log(f"  funding: teste no passado: {e}")

    # ---------------------------------------------------------------- saída
    versoes = []
    for cfg in VERSOES:
        vid, nome, moedas, alav, regra, risco, frase = cfg
        e = vivo.get(vid)
        conta = Curva.de_json(e["curva"]).resumo() if e else None
        versoes.append({"id": vid, "nome": nome, "frase": frase, "risco": risco, "alav": alav,
                        "grupo": "1×" if alav == 1 else f"{alav}×",
                        "aoVivo": conta, "historico": (hist.get("versoes") or {}).get(vid)})
    if est.get("entre"):
        versoes.append({"id": "entre", "nome": "Entre corretoras", "frase": ENTRE_FRASE, "risco": "médio", "alav": 1,
                        "grupo": "Entre corretoras", "aproximado": True,
                        "aoVivo": Curva.de_json(est["entre"]["curva"]).resumo(aproximado=True), "historico": None})
    itens = []
    for m in MOEDAS:
        med = d.media(m, fim)
        p = prev.get(m) or {}
        itens.append({"moeda": m, "par": pares.get(m), "alavMax": d.alav_max.get(m),
                      "fundingAgora": round(ao_ano(agora_f[m]), 4) if agora_f.get(m) is not None else None,
                      "media3d": round(ao_ano(med), 4) if med is not None else None,
                      "binance": p.get("binance"), "bybit": p.get("bybit"), "hl": p.get("hl")})
    est["eventos"] = ev.para_json()
    est["pares"] = pares
    ctx.est.clear()
    ctx.est.update(est)
    return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": "btc1", "versoes": versoes,
            "eventos": est["eventos"], "itens": itens, "avisos": AVISOS,
            "config": {"frequencia": "a cada 6 h", "moedas": MOEDAS, "pares": pares,
                       "taxas": {"avista": TAXA_SPOT, "perpetuo": TAXA_PERP, "deslize": DESLIZE},
                       "reequilibrio": [REEQ_BAIXO, REEQ_ALTO], "seletiva": [SELETIVA_ENTRA, SELETIVA_SAI],
                       "rodizio": {"semanas": 1, "diferencaAno": RODIZIO_DIFERENCA}, "alavMax": ALAV_MAX,
                       "entre": {"entra": ENTRE_ENTRA, "sai": ENTRE_SAI, "troca": ENTRE_TROCA, "taxas": ENTRE_TAXA,
                                 "ponte": ENTRE_PONTE}},
            "erros": erros}
