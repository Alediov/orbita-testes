"""Cópia no papel de uma carteira da Hyperliquid (só simulação: nenhuma ordem, nenhuma conta, nenhuma chave).

Uma `Conta` fictícia (US$ 1.000 por padrão) copia as operações de UMA carteira com uma alavancagem máxima e um atraso:

- a cada operação da carteira (grupo de execuções da mesma moeda em até 60 s), o robô põe a SUA posição naquela moeda
  na mesma fração do patrimônio que a carteira tem (posição depois da operação × preço ÷ valor da conta dela);
- garantia ISOLADA por posição: margem = valor da posição ÷ alavancagem (a menor entre a da conta fictícia e a máxima do
  ativo); sem caixa livre para a margem, a posição fica menor (é o limite da alavancagem);
- preço de execução = preço do mercado no instante da operação + atraso (vela que contém o instante, interpolada entre a
  abertura e o fechamento) piorado por uma diferença de preço conservadora (`deslize`);
- taxa de quem tira liquidez (nível base da Hyperliquid: 0,045%) sobre o valor negociado; mudanças menores que US$ 10
  (a ordem mínima da Hyperliquid) são ignoradas, menos o fechamento;
- financiamento de hora em hora (`fundingHistory`): posição comprada paga a taxa positiva, vendida recebe; sai da margem
  isolada, como na Hyperliquid;
- liquidação quando margem + resultado não realizado < margem de manutenção, que é metade da margem inicial na
  alavancagem máxima do ativo (documentação de margem da Hyperliquid): mmr = 1 / (2 × alavancagem máxima). Conferida
  pelas máximas e mínimas das velas; liquidada, a conta perde a margem daquela posição e segue com o resto. Na vela em
  que a posição abriu, só o fechamento conta (a máxima ou a mínima podem ter vindo antes da entrada).

Variantes (pedidos do Alediov, 02/11/2026, 19h08; `variante` da conta, chave "3x1s" etc.):
- "s" SAÍDAS DE SEGURANÇA: além de seguir a carteira, fecha a posição aberta há mais de 3 dias (`TEMPO_MAX_MS`) e a que
  perder mais de 5% da conta (`STOP_CONTA`, sobre o patrimônio na entrada; conferido pelas velas, como a liquidação).
  Depois de sair (e de uma liquidação), fica fora daquela moeda até a carteira ABRIR uma operação nova nela (sair do zero
  ou virar de lado).
- "l" ORDEM LIMITE (melhor caso): nas operações em que a carteira usou ordem limite (maior parte do volume com
  `crossed` false), a cópia paga a taxa de quem deixa ordem no livro (0,015%) e não tem deslize; nas outras, igual.
- "m" SÓ AS MOEDAS BOAS: só copia as moedas da lista `moedas` (escolhidas antes do início da cópia).
- "a2"/"a3" AMPLIFICADA (02/11/2026, 19h43): a fração do patrimônio da carteira × 2 ou × 3 (até `FRACAO_MAX`); a
  margem continua isolada e o teto é a alavancagem da conta e a máxima do ativo.
- "f" ENTRADA FIXA ("como no vídeo"): cada operação nova da carteira (abertura ou aumento) usa US$ 50 de margem
  (`MARGEM_FIXA`) × a alavancagem da conta (até a máxima do ativo); quando a carteira reduz ou fecha, a cópia reduz ou
  fecha na mesma proporção; virada de lado: fecha e abre com a margem fixa; sem caixa para os US$ 50, não abre. Não
  depende do patrimônio da carteira.
- "p20"/"p25"/"p30" PARAR DE COPIAR (09/11/2026, pedido do Alediov: "parar de copiar quem afunda"): copia como a
  proporcional, mas confere o patrimônio da cópia DE HORA EM HORA (e a cada operação); quando ele fica 20, 25 ou 30%
  abaixo do melhor momento da cópia, fecha tudo (a mercado: taxa cheia e deslize) e larga a carteira para sempre (o
  dinheiro fica parado). Conferir de hora em hora quer dizer que a saída pode vir um pouco depois do limite exato.

Tudo em milissegundos UTC. Puro: os preços e o financiamento chegam prontos (`Mercado`).
"""
from __future__ import annotations

import bisect
import math

TAXA_TOMADOR = 0.00045  # nível base, perpétuos, quem tira liquidez (hyperliquid.gitbook.io → Trading → Fees)
TAXA_LIVRO = 0.00015    # nível base, perpétuos, quem deixa ordem no livro
TEMPO_MAX_MS = 3 * 86_400_000  # saídas de segurança: posição aberta há mais de 3 dias
STOP_CONTA = 0.05               # saídas de segurança: perda da posição acima de 5% da conta
MARGEM_FIXA = 50.0              # entrada fixa: margem por operação nova da carteira
ORDEM_MINIMA = 10.0     # US$
FRACAO_MAX = 50.0       # teto da fração posição/patrimônio da carteira (patrimônio quase zero dá números absurdos)
AGRUPAR_MS = 60_000     # execuções da mesma moeda em até 60 s viram uma operação só
DIA_MS = 86_400_000
HORA_MS = 3_600_000
FUSO_MS = -3 * 3_600_000  # o dia da série é o dia de Brasília


def deslize(moeda: str) -> float:
    """Diferença de preço conservadora contra a cópia: 0,05% em BTC e ETH, 0,10% no resto."""
    return 0.0005 if moeda in ("BTC", "ETH") else 0.001


def dia_de(ms: int) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp((ms + FUSO_MS) / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def fim_do_dia(ms: int) -> int:
    """O primeiro instante do dia seguinte (em Brasília) depois de `ms`."""
    return ((ms + FUSO_MS) // DIA_MS + 1) * DIA_MS - FUSO_MS


class Velas:
    """Velas de uma moeda: [(t abertura, t fechamento, o, h, l, c)] em ordem."""

    def __init__(self, lista):
        lista = sorted({int(v[0]): v for v in lista}.values(), key=lambda v: v[0])
        self.v = [(int(a), int(b), float(o), float(h), float(l), float(c)) for a, b, o, h, l, c in lista]
        self.t = [x[0] for x in self.v]

    @classmethod
    def da_api(cls, lista):
        """Do formato do `candleSnapshot`: {t, T, o, h, l, c, …} com os preços em texto."""
        return cls([(c["t"], c["T"], c["o"], c["h"], c["l"], c["c"]) for c in lista])

    def __len__(self):
        return len(self.v)

    def juntar(self, outra: "Velas") -> "Velas":
        return Velas(self.v + outra.v)

    def preco(self, T: int):
        """Preço no instante T: a vela que contém T, interpolada; depois da última vela, o último fechamento."""
        i = bisect.bisect_right(self.t, T) - 1
        if i < 0:
            return None
        a, b, o, _h, _l, c = self.v[i]
        if T > b:
            return c
        f = (T - a) / max(1, b - a)
        return o + (c - o) * f

    def entre(self, a: int, b: int):
        """As velas que terminam depois de `a` e começam até `b`: [(t, T, h, l, c)]."""
        i = max(0, bisect.bisect_right(self.t, a) - 1)
        out = []
        while i < len(self.v) and self.v[i][0] <= b:
            x = self.v[i]
            if x[1] > a:
                out.append((x[0], x[1], x[3], x[4], x[5]))
            i += 1
        return out


class Mercado:
    """Velas, financiamento e alavancagem máxima por moeda."""

    def __init__(self, velas=None, funding=None, max_lev=None):
        self.velas: dict[str, Velas] = velas or {}
        # financiamento: moeda → [(t, taxa)] em ordem
        self.funding: dict[str, list] = {m: sorted((int(t), float(r)) for t, r in l) for m, l in (funding or {}).items()}
        self.max_lev: dict[str, int] = max_lev or {}

    def preco(self, moeda, T):
        v = self.velas.get(moeda)
        return v.preco(T) if v else None

    def fundings(self, moeda, a, b):
        l = self.funding.get(moeda) or []
        i = bisect.bisect_right(l, (a, math.inf))
        j = bisect.bisect_right(l, (b, math.inf))
        return l[i:j]

    def lev_max(self, moeda):
        return int(self.max_lev.get(moeda) or 20)


def operacoes_da_carteira(fills):
    """Execuções (formato `userFills`) → operações: [{t, moeda, pos (depois), px, n}] em ordem.

    Só perpétuos da Hyperliquid: as de spot (`@107`, `PURR/USDC`) e as de outros dex (HIP-3, `xyz:XYZ100`) ficam de fora.
    Execuções da mesma moeda em até 60 s viram uma operação (a posição final do grupo e o preço médio).
    """
    fs = sorted((f for f in fills if copiavel(f.get("coin", ""))), key=lambda f: (int(f["time"]), int(f.get("tid") or 0)))
    ops, abertos = [], {}
    for f in fs:
        m, t, sz, px = f["coin"], int(f["time"]), float(f["sz"]), float(f["px"])
        sinal = 1 if f["side"] == "B" else -1
        pos = float(f["startPosition"]) + sinal * sz
        g = abertos.get(m)
        passivo = sz * px if f.get("crossed") is False else 0.0
        if g and t - g["t0"] <= AGRUPAR_MS:
            g["t"], g["pos"] = t, pos
            g["_ntl"] += sz * px
            g["_pas"] += passivo
            g["_sz"] += sz
            g["px"] = g["_ntl"] / g["_sz"]
            g["n"] += 1
            continue
        g = {"t": t, "t0": t, "moeda": m, "pos": pos, "antes": float(f["startPosition"]), "px": px, "n": 1,
             "_ntl": sz * px, "_sz": sz, "_pas": passivo}
        abertos[m] = g
        ops.append(g)
    for g in ops:
        g["passiva"] = g["_pas"] >= 0.5 * g["_ntl"]  # a maior parte do volume com ordem limite
        g.pop("_ntl"), g.pop("_sz"), g.pop("_pas"), g.pop("t0")
    ops.sort(key=lambda g: g["t"])
    return ops


def copiavel(moeda: str) -> bool:
    """Perpétuo da Hyperliquid: fora spot (`@107`, `PURR/USDC`), outros dex (HIP-3, `xyz:XYZ100`) e `#…` (sem velas)."""
    return bool(moeda) and moeda[0] not in "@#" and "/" not in moeda and ":" not in moeda


class Patrimonio:
    """Valor da conta da carteira ao longo do tempo: [(t, valor)]."""

    def __init__(self, pontos):
        p = sorted((int(t), float(v)) for t, v in pontos if v is not None)
        self.t = [x[0] for x in p]
        self.v = [x[1] for x in p]

    def em(self, T):
        """O ponto mais perto de T (antes ou depois)."""
        if not self.t:
            return None
        i = bisect.bisect_left(self.t, T)
        if i <= 0:
            return self.v[0]
        if i >= len(self.t):
            return self.v[-1]
        return self.v[i] if self.t[i] - T < T - self.t[i - 1] else self.v[i - 1]


def limite_parada(variante: str):
    """"p25" → 0,25 (a queda do topo que faz largar a carteira); outras versões → None."""
    if variante[:1] == "p" and variante[1:].isdigit():
        return int(variante[1:]) / 100
    return None


class Conta:
    def __init__(self, alav: int, atraso_ms: int, capital: float = 1000.0, inicio: int = 0, variante: str = "",
                 moedas=None):
        self.alav, self.atraso, self.capital = alav, atraso_ms, capital
        self.variante = variante or ""   # "", "s", "l", "m", "a2"/"a3" (amplificada), "f" (entrada fixa), "p25"…
        self.moedas = list(moedas) if moedas is not None else None
        self.bloqueadas: list[str] = []  # "s": moedas de onde saiu, até a carteira abrir de novo
        self.saidas = {"tempo": 0, "stop": 0}
        self.sem_caixa = 0   # entrada fixa: operações que não abriram por falta de caixa
        self.inicio = inicio
        self.caixa = capital          # o que não está preso como margem isolada
        self.pos: dict[str, dict] = {}  # moeda → {szi, entrada, margem, lev, mmr, desde, checado}
        self.t = inicio
        self.taxas = self.funding = 0.0
        self.ops = self.fechamentos = self.acertos = 0
        self.ganhos = self.perdas = 0.0  # soma dos fechamentos com lucro e com prejuízo (para ganho médio ÷ perda média)
        self.liquidacoes: list[dict] = []
        self.ultimas: list[dict] = []
        self.serie: dict[str, float] = {}
        self.pico = capital
        self.pior_queda = 0.0
        self.quebrada = False
        self.sem_preco = 0
        self.parada = None  # "pNN": {em, queda, patrimonio} quando largou a carteira

    # ------------------------------------------------------------------ estado (JSON)
    def para_json(self):
        return {k: getattr(self, k) for k in ("alav", "atraso", "capital", "caixa", "pos", "t", "taxas", "funding", "ops",
                                              "fechamentos", "acertos", "liquidacoes", "ultimas", "serie", "pico",
                                              "pior_queda", "quebrada", "sem_preco", "variante", "moedas", "bloqueadas",
                                              "saidas", "inicio", "sem_caixa", "ganhos", "perdas", "parada")}

    @classmethod
    def de_json(cls, d):
        c = cls(d["alav"], d["atraso"], d["capital"], d["t"], d.get("variante", ""), d.get("moedas"))
        for k, v in d.items():
            setattr(c, k, v)
        return c

    # ------------------------------------------------------------------ contas
    def patrimonio(self, merc: Mercado, T: int) -> float:
        tot = self.caixa
        for m, p in self.pos.items():
            px = merc.preco(m, T)
            if px is None:
                px = p["entrada"]
            tot += p["margem"] + max(-p["margem"], p["szi"] * (px - p["entrada"]))
        return tot

    @staticmethod
    def preco_liq(p):
        """Preço em que margem + resultado = manutenção (posição isolada)."""
        sz, e, m, mmr = abs(p["szi"]), p["entrada"], p["margem"], p["mmr"]
        if sz <= 0:
            return None
        if p["szi"] > 0:
            return (sz * e - m) / (sz * (1 - mmr))
        return (m + sz * e) / (sz * (1 + mmr))

    def _anotar(self, merc, T):
        v = self.patrimonio(merc, T)
        self.pico = max(self.pico, v)
        if self.pico > 0:
            self.pior_queda = max(self.pior_queda, 1 - v / self.pico)
        if v < 1 and not self.pos:
            self.quebrada = True
        return v

    def _guardar_ultima(self, d):
        self.ultimas.append(d)
        del self.ultimas[:-15]

    # ------------------------------------------------------------------ o tempo passa
    def avancar(self, merc: Mercado, T: int):
        """Leva a conta até T: financiamento, liquidações e o patrimônio do fim de cada dia (série)."""
        lim = limite_parada(self.variante)
        while self.t < T:
            b = min(T, fim_do_dia(self.t))
            if lim and not self.parada:  # "pNN": de hora em hora
                b = min(b, (self.t // HORA_MS + 1) * HORA_MS)
            self._ate(merc, b)
            self.t = b
            if lim and not self.parada:
                self._conferir_parada(merc, b, lim)
            if b == fim_do_dia(b - 1) and b <= T:  # virou o dia
                self.serie[dia_de(b - 1)] = round(self._anotar(merc, b - 1), 2)

    def _conferir_parada(self, merc, T, lim):
        """"pNN": o patrimônio ficou `lim` abaixo do melhor momento → fecha tudo e larga a carteira."""
        v = self.patrimonio(merc, T)
        self.pico = max(self.pico, v)
        if self.pico <= 0 or v >= self.pico * (1 - lim):
            return False
        for m in list(self.pos):
            px = merc.preco(m, T) or self.pos[m]["entrada"]
            self._negociar(merc, m, -self.pos[m]["szi"], px, T, forcar_fechar=True)
            if self.ultimas:
                self.ultimas[-1]["tipo"] = "parou"
        depois = self.patrimonio(merc, T)
        self.pior_queda = max(self.pior_queda, 1 - min(v, depois) / self.pico)
        self.parada = {"em": T, "queda": round(1 - depois / self.pico, 4), "patrimonio": round(depois, 2)}
        if not self.ultimas or self.ultimas[-1].get("tipo") != "parou":
            self._guardar_ultima({"em": T, "moeda": "", "tipo": "parou", "lado": "", "tam": 0, "px": 0,
                                  "res": 0})
        return True

    def _ate(self, merc: Mercado, T: int):
        for m in list(self.pos):
            p = self.pos[m]
            a = p["checado"]
            for tf, taxa in merc.fundings(m, a, T):
                if self._checar(merc, m, p, a, tf):
                    break
                px = merc.preco(m, tf) or p["entrada"]
                pag = p["szi"] * px * taxa  # positivo: comprado paga
                p["margem"] -= pag
                self.funding += pag
                a = p["checado"] = tf
                if p["margem"] <= 0:
                    self._liquidar(m, p, tf, px)
                    break
            else:
                if not self._checar(merc, m, p, a, T):
                    p["checado"] = T

    def preco_stop(self, p):
        """Saídas de segurança: o preço em que a posição perde STOP_CONTA do patrimônio da entrada."""
        if self.variante != "s" or not p.get("eq0"):
            return None
        d = STOP_CONTA * p["eq0"] / abs(p["szi"])
        return p["entrada"] - d if p["szi"] > 0 else p["entrada"] + d

    def _checar(self, merc, m, p, a, b) -> bool:
        """Liquida (ou, nas saídas de segurança, fecha pelo stop ou pelo tempo) a posição entre a e b. True se saiu."""
        if b <= a:
            return False
        prazo = p["desde"] + TEMPO_MAX_MS if self.variante == "s" else None
        fim = min(b, prazo) if prazo is not None and a < prazo else b
        v = merc.velas.get(m)
        liq = self.preco_liq(p)
        stop = self.preco_stop(p)
        if v and liq is not None:
            for t0, t1, h, l, c in v.entre(a, fim):
                if t0 <= p["desde"] < t1:  # a vela da entrada: só o fechamento
                    h = l = c
                longo = p["szi"] > 0
                # o que vem primeiro com o preço andando contra: o stop (mais perto da entrada) ou a liquidação
                if stop is not None and ((longo and stop >= liq and l <= stop) or (not longo and stop <= liq and h >= stop)):
                    self._sair(merc, m, max(t0, a), stop, "stop")
                    return True
                if (longo and l <= liq) or (not longo and h >= liq):
                    self._liquidar(m, p, max(t0, a), liq)
                    return True
        if prazo is not None and a < prazo <= b:
            px = merc.preco(m, prazo) or p["entrada"]
            self._sair(merc, m, prazo, px, "tempo")
            return True
        return False

    def _sair(self, merc, m, T, px, motivo):
        """Saída de segurança: fecha a mercado (taxa cheia e deslize) e bloqueia a moeda."""
        self._negociar(merc, m, -self.pos[m]["szi"], px, T, forcar_fechar=True)
        if self.ultimas:
            self.ultimas[-1]["tipo"] = motivo
        self.saidas[motivo] = self.saidas.get(motivo, 0) + 1
        if m not in self.bloqueadas:
            self.bloqueadas.append(m)

    def _liquidar(self, m, p, t, px):
        perda = p["margem"]
        self.liquidacoes.append({"em": t, "moeda": m, "lado": "compra" if p["szi"] > 0 else "venda", "px": round(px, 6),
                                 "perda": round(perda, 2)})
        self._guardar_ultima({"em": t, "moeda": m, "tipo": "liquidada", "lado": "compra" if p["szi"] > 0 else "venda",
                              "tam": round(abs(p["szi"]) * px, 2), "px": round(px, 6), "res": round(-perda, 2)})
        self.fechamentos += 1
        self.perdas += perda
        del self.pos[m]
        if self.variante == "s" and m not in self.bloqueadas:
            self.bloqueadas.append(m)

    # ------------------------------------------------------------------ copiar uma operação
    def copiar(self, merc: Mercado, op: dict, eq_carteira: float | None):
        """Ajusta a posição na moeda da operação para a mesma fração do patrimônio da carteira."""
        if self.quebrada or self.parada:
            return
        T = op["t"] + self.atraso
        self.avancar(merc, T)
        if self.parada:  # largou a carteira no caminho
            return
        m = op["moeda"]
        if self.variante == "m" and self.moedas is not None and m not in self.moedas:
            return
        if m in self.bloqueadas:
            antes = op.get("antes", 0.0)
            abriu = op["pos"] != 0 and (antes == 0 or (antes > 0) != (op["pos"] > 0))
            if not abriu:
                return
            self.bloqueadas.remove(m)
        px = merc.preco(m, T)
        if px is None or px <= 0:
            self.sem_preco += 1
            return
        if self.variante == "f":
            return self._copiar_fixo(merc, op, m, px, T)
        if not eq_carteira or eq_carteira <= 0:
            self.sem_preco += 1
            return
        fator = int(self.variante[1:]) if self.variante[:1] == "a" else 1
        frac = max(-FRACAO_MAX, min(FRACAO_MAX, fator * op["pos"] * op["px"] / eq_carteira))
        E = self.patrimonio(merc, T)
        if E <= 0:
            self.quebrada = True
            return
        alvo = frac * E / px  # tamanho com sinal
        atual = self.pos.get(m, {}).get("szi", 0.0)
        livro = self.variante == "l" and op.get("passiva")
        if atual and (alvo == 0 or (alvo > 0) != (atual > 0)):
            self._negociar(merc, m, -atual, px, T, livro=livro)
            atual = 0.0
        delta = alvo - atual
        if abs(delta) * px < ORDEM_MINIMA:
            return
        self._negociar(merc, m, delta, px, T, livro=livro, eq=E)
        self._anotar(merc, T)

    def _copiar_fixo(self, merc, op, m, px, T):
        """Entrada fixa: US$ 50 de margem por operação nova; reduz e fecha na proporção da carteira."""
        antes, pos = op.get("antes", 0.0), op["pos"]
        atual = self.pos.get(m, {}).get("szi", 0.0)
        abre = pos != 0 and (antes == 0 or (antes > 0) != (pos > 0))
        if pos == 0 or abre:  # fechou, ou abriu (do zero ou virando de lado): a cópia fecha o que tinha
            if atual:
                self._negociar(merc, m, -atual, px, T)
                atual = 0.0
            if pos == 0:
                self._anotar(merc, T)
                return
        elif abs(pos) < abs(antes):  # reduziu: na mesma proporção
            if atual:
                q = atual * (1 - abs(pos) / abs(antes))
                if abs(q) * px >= ORDEM_MINIMA:
                    self._negociar(merc, m, -q, px, T)
                else:
                    return
            self._anotar(merc, T)
            return
        # abriu ou aumentou: mais US$ 50 de margem × a alavancagem, na direção da carteira
        lev = max(1, min(self.alav, merc.lev_max(m)))
        exe = px * (1 + deslize(m)) if pos > 0 else px * (1 - deslize(m))
        if self.caixa < MARGEM_FIXA * (1 + lev * TAXA_TOMADOR):
            self.sem_caixa += 1
            return
        q = MARGEM_FIXA * lev / exe
        if atual and (atual > 0) != (pos > 0):
            return
        self._negociar(merc, m, q if pos > 0 else -q, px, T, eq=self.patrimonio(merc, T))
        self._anotar(merc, T)

    def _negociar(self, merc, m, delta, px, T, livro=False, eq=None, forcar_fechar=False):
        s = 0.0 if livro else deslize(m)
        tx = TAXA_LIVRO if livro else TAXA_TOMADOR
        exe = px * (1 + s) if delta > 0 else px * (1 - s)
        p = self.pos.get(m)
        atual = p["szi"] if p else 0.0
        if atual and (delta > 0) != (atual > 0):  # reduz (ou fecha)
            q = min(abs(delta), abs(atual))
            sinal = 1 if atual > 0 else -1
            liber = p["margem"] * q / abs(atual)
            res = max(-liber, q * (exe - p["entrada"]) * sinal)
            taxa = q * exe * tx
            self.caixa += liber + res - taxa
            self.taxas += taxa
            p["margem"] -= liber
            p["szi"] = atual - sinal * q
            self.fechamentos += 1
            if res - taxa > 0:
                self.acertos += 1
                self.ganhos += res - taxa
            else:
                self.perdas += taxa - res
            self.ops += 1
            fechou = forcar_fechar or abs(p["szi"]) * exe < 0.01
            self._guardar_ultima({"em": T, "moeda": m, "tipo": "fechou" if fechou else "reduziu",
                                  "lado": "venda" if sinal > 0 else "compra", "tam": round(q * exe, 2),
                                  "px": round(exe, 6), "res": round(res - taxa, 2)})
            if fechou:
                del self.pos[m]
            return
        # aumenta (ou abre)
        lev = max(1, min(self.alav, merc.lev_max(m)))
        q = abs(delta)
        custo = q * exe / lev + q * exe * tx
        if custo > self.caixa:  # o limite da alavancagem: o que dá com o caixa livre
            q = max(0.0, self.caixa / (exe / lev + exe * tx)) * 0.999
            if q * exe < ORDEM_MINIMA:
                return
        margem = q * exe / lev
        taxa = q * exe * tx
        self.caixa -= margem + taxa
        self.taxas += taxa
        sinal = 1 if delta > 0 else -1
        if p:
            novo = abs(atual) + q
            p["entrada"] = (abs(atual) * p["entrada"] + q * exe) / novo
            p["szi"] = sinal * novo
            p["margem"] += margem
            if eq:
                p["eq0"] = eq
        else:
            self.pos[m] = {"szi": sinal * q, "entrada": exe, "margem": margem, "lev": lev,
                           "mmr": 1 / (2 * merc.lev_max(m)), "desde": T, "checado": T, "eq0": eq or self.capital}
        self.ops += 1
        self._guardar_ultima({"em": T, "moeda": m, "tipo": "aumentou" if p else "abriu",
                              "lado": "compra" if sinal > 0 else "venda", "tam": round(q * exe, 2),
                              "px": round(exe, 6), "res": round(-taxa, 2)})

    # ------------------------------------------------------------------ resumo
    def resumo(self, merc: Mercado, T: int, serie_extra=True):
        v = self.patrimonio(merc, T) if merc else self.caixa
        serie = sorted(self.serie.items())
        if serie_extra:
            serie = [x for x in serie if x[0] != dia_de(T)] + [(dia_de(T), round(v, 2))]
        pico = max(self.pico, v)
        queda = max(self.pior_queda, 1 - v / pico if pico > 0 else 0)
        return {
            "patrimonio": round(v, 2),
            "retorno": round(v / self.capital - 1, 4),
            "piorQueda": round(queda, 4),
            "ops": self.ops,
            "acerto": round(self.acertos / self.fechamentos, 3) if self.fechamentos else None,
            "gm": round(self.ganhos / self.acertos, 2) if self.acertos and self.ganhos else None,
            "pm": round(self.perdas / (self.fechamentos - self.acertos), 2) if self.fechamentos > self.acertos and self.perdas else None,
            "taxas": round(self.taxas, 2),
            "funding": round(self.funding, 2),
            "liquidacoes": self.liquidacoes[-(5 if self.variante else 20):],
            "nLiq": len(self.liquidacoes),
            "quebrada": self.quebrada,
            "posicoes": [{"moeda": m, "lado": "compra" if p["szi"] > 0 else "venda",
                          "tam": round(abs(p["szi"]) * (merc.preco(m, T) or p["entrada"]), 2) if merc else None,
                          "entrada": round(p["entrada"], 6), "margem": round(p["margem"], 2), "lev": p["lev"],
                          "liq": round(self.preco_liq(p) or 0, 6)} for m, p in self.pos.items()],
            "serie": [[d, x] for d, x in serie],
            "ultimas": list(reversed(self.ultimas[-(6 if self.variante else 12):])),  # variantes: menos, para o resumo caber
            "inicio": self.inicio,
            **({"variante": self.variante} if self.variante else {}),
            **({"saidas": self.saidas, "fora": self.bloqueadas} if self.variante == "s" else {}),
            **({"moedas": self.moedas} if self.variante == "m" else {}),
            **({"semCaixa": self.sem_caixa} if self.variante == "f" else {}),
            **({"parou": self.parada, "limite": limite_parada(self.variante)} if limite_parada(self.variante) else {}),
        }


def simular(ops, patrimonio: Patrimonio, merc: Mercado, contas: list[Conta], ate: int):
    """Passa as operações (já em ordem) por todas as contas e leva cada uma até `ate`."""
    for c in contas:
        for op in ops:
            if op["t"] + c.atraso > ate:
                break
            c.copiar(merc, op, patrimonio.em(op["t"]))
        c.avancar(merc, ate)
    return contas
