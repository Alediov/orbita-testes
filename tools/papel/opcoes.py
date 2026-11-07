"""Venda de opções de bitcoin e ether NO PAPEL (plano: docs/plano-testes-mercado-2.md, seção 7; formato:
tools/papel/FORMATO.md). Nenhuma ordem, nenhuma conta, nenhuma chave: só a API pública da Deribit (e as velas da
Hyperliquid no teste no passado).

A ideia: vender a alguém o direito de vender (put) ou de comprar (call) a moeda a um preço combinado (o strike) numa
data, e receber o prêmio já. Na maior parte das semanas a opção vence sem valor e o prêmio fica; numa queda (put) ou
numa alta (call) forte, a conta paga a diferença.

Ao vivo (fiel, "daqui para frente"): a cada rodada (6 h) a cadeia inteira da Deribit (`get_book_summary_by_currency`,
uma chamada por moeda). Toda sexta, depois do vencimento das 08h UTC, a versão vende a opção da semana seguinte (ou a do
fim do mês seguinte, na mensal) pela MELHOR OFERTA DE COMPRA da cadeia (`bid_price`), escolhendo o strike de delta mais
perto do alvo (o delta vem da fórmula de Black-Scholes com a volatilidade da marca, `mark_iv`, e o preço do futuro do
vencimento, `underlying_price`). Marca a mercado pela `mark_price`; no vencimento paga a diferença pelo preço de entrega
oficial (`get_delivery_prices`; sem ele, o índice da rodada). Taxa de 0,03% do valor da moeda por opção (no máximo
12,5% do prêmio) e a de entrega de 0,015% (no máximo 12,5% do que a opção valeu). **O ao vivo só começa na 1ª sexta
de vencimento depois de a versão nascer**: até lá a versão não tem `aoVivo`.

Garantia em dólar (simplificação): a put fica "coberta por dólar" (o dinheiro inteiro guardado para comprar no strike);
a call fica coberta pela própria moeda (comprada na hora da venda, com taxa e deslize). Na Deribit de verdade as opções
clássicas usam a moeda como garantia e o mínimo é 0,1 BTC / 1 ETH (≈ US$ 7 mil); com US$ 1.000 o papel vende frações.

Teste no passado (aproximado): velas de 1 h da Hyperliquid (~180 dias) e o DVOL da Deribit (a volatilidade implícita de
30 dias, de hora em hora) no lugar da cadeia: preço pela fórmula de Black-Scholes com o DVOL mais uma inclinação para as
puts fora do dinheiro (`iv_com_inclinacao`), meio spread de 3% (mínimo 1 tique de 0,0001 da moeda), strikes de 1.000
(BTC) e 50 (ETH), vencimentos toda sexta às 08h UTC e entrega pelo fechamento da vela das 07h–08h. Sem o DVOL, a
volatilidade realizada de 30 dias × 1,1.

Amostras conferidas (Teste de alcance, 03/11/2026): book summary
`{"instrument_name": "BTC-13NOV26-83000-P", "bid_price": 0.071, "ask_price": 0.0755, "mark_price": 0.07326236,
"mark_iv": 38.31, "underlying_price": 77679.18, "estimated_delivery_price": 77548.61, …}` (preços na moeda);
índice `{"index_price": 77550.59, "estimated_delivery_price": …}`; entrega `{"data": [{"date": "2026-11-03",
"delivery_price": 76731.9}], "records_total": 2658}`; DVOL (resolução 3600) `{"data": [[ms, abre, máx., mín., fecha]]}`.
"""
from __future__ import annotations

import copy
import datetime as dt
import math
import re

import rede
from conta import CAPITAL, DIA, HORA, Curva, Eventos, dia_de, moeda_br, num_br, pct_br

try:
    import hl
    ERROS = (rede.Erro, hl.Erro)
except ImportError:  # pragma: no cover
    ERROS = (rede.Erro,)

NOME = "Opções"
VERSAO = 1

MOEDAS = ["BTC", "ETH"]
ANO_MS = 365 * DIA
TAXA_OPCAO = 0.0003       # da moeda, por opção vendida ou recomprada
TAXA_ENTREGA = 0.00015    # da moeda, no vencimento dentro do dinheiro
TETO_TAXA = 0.125         # as duas no máximo 12,5% do valor da opção
TAXA_SPOT = 0.0005        # comprar/vender a moeda da call coberta (à vista, quem tira liquidez)
DESLIZE_SPOT = 0.0002
TIQUE = 0.0001            # preço mínimo de uma opção, na moeda
MEIO_SPREAD_HIST = 0.03   # no teste no passado: oferta = preço teórico × (1 − 3%)
PASSO_STRIKE = {"BTC": 1000, "ETH": 50}
HORA_VENC = 8             # vencimento às 08h UTC
JANELA_VENDA = 3 * DIA    # vende do vencimento de sexta até domingo; depois espera a próxima sexta
SEMANA_MIN, SEMANA_MAX = 4 * DIA, 10 * DIA
MES_MIN, MES_MAX = 21 * DIA, 50 * DIA
HIST_DIAS = 180
HIST_REFAZER = 7 * DIA
HIST_TEMPO_MIN = 240      # segundos que precisam sobrar na rodada para refazer o teste no passado
DVOL_PEDACO = 30 * DIA    # o DVOL vem em pedaços de 30 dias de hora em hora (720 pontos por pedido)
INCLINACAO_PUT, INCLINACAO_CALL = 0.25, 0.05
MAX_EVENTOS_VIVO = 300
MESES = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}

# (id, nome, moeda, tipo, delta alvo, prazo, recompra (× prêmio) ou None, risco, frase)
VERSOES = [
    ("put15", "Put 0,15", "BTC", "put", 0.15, "semana", None, "médio",
     "Toda sexta vende uma put de bitcoin de delta perto de 0,15 (≈ 15% de chance de terminar no prejuízo) para a sexta "
     "seguinte, com o dinheiro inteiro guardado em dólar para comprar no strike."),
    ("put30", "Put 0,30", "BTC", "put", 0.30, "semana", None, "alto",
     "A mesma put, mais perto do preço (delta 0,30): o prêmio é maior e o prejuízo vem mais vezes."),
    ("call15", "Call coberta", "BTC", "call", 0.15, "semana", None, "alto",
     "Compra bitcoin com o dinheiro todo e vende toda sexta uma call de delta 0,15 sobre ele: ganha o prêmio e abre mão "
     "das altas fortes; nas quedas, cai junto com o bitcoin."),
    ("strangle", "Strangle coberto", "BTC", "strangle", 0.15, "semana", None, "alto",
     "Metade em dólar para uma put e metade em bitcoin para uma call, as duas de delta 0,15: dois prêmios por semana e "
     "prejuízo se o preço andar muito para qualquer lado."),
    ("putmes", "Put mensal 0,20", "BTC", "put", 0.20, "mes", None, "médio",
     "Uma put de delta 0,20 de cerca de um mês (a da última sexta do mês), vendida de novo quando a anterior vence."),
    ("putstop", "Put 0,15 com recompra", "BTC", "put", 0.15, "semana", 3.0, "médio",
     "A put 0,15 da semana, mas recompra (fecha com prejuízo) se ela passar a valer 3 vezes o prêmio recebido, e espera "
     "a sexta seguinte."),
    ("eth_put15", "ETH put 0,15", "ETH", "put", 0.15, "semana", None, "médio",
     "A put semanal de delta 0,15, com o ether."),
    ("eth_call15", "ETH call coberta", "ETH", "call", 0.15, "semana", None, "alto",
     "A call coberta semanal de delta 0,15, com o ether comprado."),
]
FRASE = ("Vende o direito de comprar ou de vender bitcoin (ou ether) a um preço combinado: recebe o prêmio já e, na "
         "maior parte das semanas, fica com ele; numa queda ou alta forte, paga a diferença.")
COMO_FUNCIONA = [
    "Uma put é o direito de VENDER a moeda a um preço combinado (o strike) numa data. Quem vende a put recebe um prêmio "
    "na hora e, se no vencimento a moeda estiver abaixo do strike, paga a diferença. Uma call é o mesmo para cima.",
    "O delta diz mais ou menos a chance de a opção terminar valendo alguma coisa: delta 0,15 ≈ 15%. Quanto menor, menor "
    "o prêmio e mais raro o prejuízo, mas quando ele vem pode levar muitas semanas de prêmio.",
    "Ao vivo, toda sexta depois do vencimento das 5h (08h UTC) a conta vende a opção da semana seguinte pela melhor "
    "oferta de compra da Deribit, a maior corretora de opções de cripto, e no vencimento paga pelo preço de entrega "
    "oficial. O ao vivo começa na primeira sexta depois que a versão nasceu.",
    "A put fica coberta por dólar (o dinheiro inteiro guardado para comprar no strike); a call fica coberta pela moeda "
    "comprada. As taxas da Deribit (0,03% da moeda por opção e 0,015% na entrega, no máximo 12,5% do prêmio) estão "
    "descontadas.",
    "O teste no passado é aproximado: sem a cadeia antiga, os preços saem da fórmula de Black-Scholes com o índice de "
    "volatilidade da Deribit (DVOL), um pouco mais caros nas puts longe do preço.",
]
AVISOS = [
    "Na Deribit, a menor opção de bitcoin é de 0,1 BTC (e de ether, 1 ETH): uns US$ 7 mil de garantia. Com US$ 1.000, a "
    "conta de verdade não conseguiria vender nem uma; o papel vende frações.",
    "As opções clássicas da Deribit usam a própria moeda como garantia, não dólar: numa queda forte, a garantia também "
    "cai. A conta em dólar do papel é uma simplificação.",
    "O papel olha a cadeia só a cada 6 h: a recompra (versão com recompra) e a venda de sexta acontecem na primeira "
    "rodada depois do momento certo, não no minuto exato. Um salto no fim de semana pode passar por cima.",
    "A melhor oferta de compra da cadeia vale para poucas opções; uma venda grande pegaria preços piores.",
    "A Deribit exige cadastro com documentos, e o uso por quem mora no Brasil precisa ser conferido antes.",
    "O teste no passado não tem os preços de verdade da época: usa a fórmula com o DVOL, que é a volatilidade de 30 dias "
    "e não a de cada semana.",
]


# ---------------------------------------------------------------------------------------------------- utilidades
def _f(x, padrao=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else padrao
    except (TypeError, ValueError):
        return padrao


def _ddmm(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%d/%m")


def _strike_txt(k):
    return moeda_br(k, 0 if k >= 100 else 2)


def sexta_08(t):
    """A sexta-feira 08h UTC mais recente até `t` (ms)."""
    a = int(t) - HORA_VENC * HORA
    d = a // DIA
    dia_semana = (d + 3) % 7  # 0 = segunda (01/01/1970 foi quinta)
    return (d - (dia_semana - 4) % 7) * DIA + HORA_VENC * HORA


def eh_sexta(ms):
    return ((int(ms) // DIA) + 3) % 7 == 4


def ultima_sexta_do_mes(ms):
    """True se o dia de `ms` (UTC) é a última sexta do mês (os vencimentos mensais)."""
    d = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    return eh_sexta(ms) and (d + dt.timedelta(days=7)).month != d.month


def ler_instrumento(nome):
    """"BTC-13NOV26-83000-P" → (moeda, vencimento ms às 08h UTC, strike, "put"|"call"); None se não for opção."""
    m = re.match(r"^([A-Z]+)-(\d{1,2})([A-Z]{3})(\d{2})-(\d+(?:d\d+)?)-([CP])$", str(nome or ""))
    if not m or m.group(3) not in MESES:
        return None
    try:
        venc = dt.datetime(2000 + int(m.group(4)), MESES[m.group(3)], int(m.group(2)), HORA_VENC, tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    return m.group(1), int(venc.timestamp() * 1000), float(m.group(5).replace("d", ".")), "put" if m.group(6) == "P" else "call"


def nome_instrumento(moeda, venc, strike, tipo):
    d = dt.datetime.fromtimestamp(venc / 1000, dt.timezone.utc)
    mes = [k for k, v in MESES.items() if v == d.month][0]
    return f"{moeda}-{d.day}{mes}{d.year % 100:02d}-{int(strike)}-{'P' if tipo == 'put' else 'C'}"


# ---------------------------------------------------------------------------------------------------- Black-Scholes
def _N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, T, iv, tipo):
    """Preço (por unidade da moeda, em US$) pela fórmula de Black-Scholes sem juros. T em anos; iv em fração."""
    if T <= 0 or iv <= 0 or S <= 0 or K <= 0:
        return max(K - S, 0.0) if tipo == "put" else max(S - K, 0.0)
    r = iv * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * iv * iv * T) / r
    call = S * _N(d1) - K * _N(d1 - r)
    return max(0.0, call - S + K) if tipo == "put" else max(0.0, call)


def delta(S, K, T, iv, tipo):
    if T <= 0 or iv <= 0 or S <= 0 or K <= 0:
        dentro = (S < K) if tipo == "put" else (S > K)
        return (-1.0 if tipo == "put" else 1.0) if dentro else 0.0
    d1 = (math.log(S / K) + 0.5 * iv * iv * T) / (iv * math.sqrt(T))
    return _N(d1) - 1 if tipo == "put" else _N(d1)


def iv_com_inclinacao(base, S, K, T, tipo):
    """O DVOL é a volatilidade "no dinheiro"; as puts longe do preço custam mais (o medo da queda) e as calls longe um
    pouco menos: iv = base × (1 ± inclinação × (0,5 − |delta|))."""
    d = abs(delta(S, K, T, base, tipo))
    if tipo == "put":
        return base * (1 + INCLINACAO_PUT * (0.5 - d))
    return base * (1 - INCLINACAO_CALL * (0.5 - d))


def taxa_opcao(S, q, preco_un):
    return min(TAXA_OPCAO * S * q, TETO_TAXA * preco_un * q)


# ---------------------------------------------------------------------------------------------------- mercados
class MercadoVivo:
    """A cadeia de uma rodada: `cadeias[moeda]` = lista do get_book_summary_by_currency; `indices[moeda]` = preço;
    `entregas[moeda]` = {AAAA-MM-DD: preço de entrega}."""

    def __init__(self, cadeias, indices, entregas):
        self.ops, self.indices, self.entregas = {}, dict(indices), {m: dict(v) for m, v in (entregas or {}).items()}
        for m, lista in (cadeias or {}).items():
            d = {}
            for x in lista or []:
                inst = ler_instrumento((x or {}).get("instrument_name"))
                if not inst or inst[0] != m:
                    continue
                idx = _f(x.get("estimated_delivery_price")) or self.indices.get(m) or _f(x.get("underlying_price"))
                if not idx:
                    continue
                bid, ask, mark = _f(x.get("bid_price")), _f(x.get("ask_price")), _f(x.get("mark_price"))
                iv = _f(x.get("mark_iv"))
                d[x["instrument_name"]] = {
                    "inst": x["instrument_name"], "moeda": m, "venc": inst[1], "K": inst[2], "tipo": inst[3],
                    "bid": bid * idx if bid else None, "ask": ask * idx if ask else None,
                    "mark": mark * idx if mark is not None else None, "iv": iv / 100 if iv else None,
                    "S": _f(x.get("underlying_price")) or idx}
                self.indices.setdefault(m, idx)
            self.ops[m] = d

    def preco(self, m, t):
        return self.indices.get(m)

    def vencimentos(self, m, t):
        return sorted({o["venc"] for o in self.ops.get(m, {}).values() if o["venc"] > t})

    def opcoes(self, m, t, tipo, venc):
        return [o for o in self.ops.get(m, {}).values() if o["venc"] == venc and o["tipo"] == tipo]

    def marca(self, op, t):
        """(marca, oferta de venda) em US$ por unidade; sem a opção na cadeia, a fórmula com a última volatilidade."""
        o = self.ops.get(op["moeda"], {}).get(op["inst"])
        if o and o["mark"] is not None:
            return o["mark"], o["ask"] if o["ask"] else o["mark"] * (1 + MEIO_SPREAD_HIST)
        S = self.preco(op["moeda"], t)
        if not S:
            return None
        v = bs(S, op["K"], (op["venc"] - t) / ANO_MS, op.get("iv") or 0.5, op["tipo"])
        return v, v * (1 + MEIO_SPREAD_HIST)

    def entrega(self, m, venc):
        return self.entregas.get(m, {}).get(dt.datetime.fromtimestamp(venc / 1000, dt.timezone.utc).strftime("%Y-%m-%d"))


class MercadoHist:
    """O passado sem a cadeia: velas de 1 h (`precos[moeda]` = {hora ms (fim da vela): fechamento}) e o DVOL
    (`dvol[moeda]` = {hora ms: fração}); as opções saem da fórmula."""

    def __init__(self, precos, dvol):
        self.precos = precos
        self.dvol = dvol
        self._iv = {}

    def preco(self, m, t):
        return self.precos.get(m, {}).get((int(t) // HORA) * HORA)

    def vol(self, m, t):
        h = (int(t) // HORA) * HORA
        d = self.dvol.get(m, {})
        for k in range(0, 48):
            v = d.get(h - k * HORA)
            if v:
                return v
        # sem o DVOL: a volatilidade realizada de 30 dias × 1,1 (guardada por dia)
        dia = h // DIA
        if (m, dia) not in self._iv:
            ps = [self.precos.get(m, {}).get(h - i * HORA) for i in range(30 * 24, -1, -1)]
            rs = [math.log(b / a) for a, b in zip(ps, ps[1:]) if a and b]
            if len(rs) > 48:
                med = sum(rs) / len(rs)
                self._iv[(m, dia)] = 1.1 * math.sqrt(sum((x - med) ** 2 for x in rs) / (len(rs) - 1) * 24 * 365)
            else:
                self._iv[(m, dia)] = 0.55
        return self._iv[(m, dia)]

    def vencimentos(self, m, t):
        a = sexta_08(t)
        return [a + k * 7 * DIA for k in range(1, 9)]

    def _cotar(self, m, t, K, venc, tipo):
        S, base = self.preco(m, t), self.vol(m, t)
        T = (venc - t) / ANO_MS
        iv = iv_com_inclinacao(base, S, K, T, tipo)
        teo = bs(S, K, T, iv, tipo)
        meio = max(MEIO_SPREAD_HIST * teo, TIQUE * S / 2)
        bid = teo - meio
        return {"bid": bid if bid >= TIQUE * S else None, "ask": teo + meio, "mark": teo, "iv": iv, "S": S}

    def opcoes(self, m, t, tipo, venc):
        S = self.preco(m, t)
        if not S:
            return []
        passo = PASSO_STRIKE.get(m, 1)
        centro = round(S / passo) * passo
        out = []
        for i in range(-int(0.4 * S / passo), int(0.4 * S / passo) + 1):
            K = centro + i * passo
            if K <= 0:
                continue
            o = {"inst": nome_instrumento(m, venc, K, tipo), "moeda": m, "venc": venc, "K": float(K), "tipo": tipo}
            o.update(self._cotar(m, t, K, venc, tipo))
            out.append(o)
        return out

    def marca(self, op, t):
        if not self.preco(op["moeda"], t):
            return None
        c = self._cotar(op["moeda"], t, op["K"], op["venc"], op["tipo"])
        return c["mark"], c["ask"]

    def entrega(self, m, venc):
        return self.preco(m, venc)


def escolher_vencimento(mk, m, t, prazo):
    vs = mk.vencimentos(m, t)
    if prazo == "mes":
        bons = [v for v in vs if MES_MIN <= v - t <= MES_MAX and ultima_sexta_do_mes(v)] or \
               [v for v in vs if MES_MIN <= v - t <= MES_MAX and eh_sexta(v)]
        alvo = 30 * DIA
    else:
        bons = [v for v in vs if SEMANA_MIN <= v - t <= SEMANA_MAX and eh_sexta(v)]
        alvo = 7 * DIA
    return min(bons, key=lambda v: abs(v - t - alvo)) if bons else None


def escolher_strike(ops, t, alvo):
    """A opção com oferta de compra e delta mais perto do alvo (delta pela fórmula com a iv e o preço da opção)."""
    melhor, dist = None, None
    for o in ops:
        if not o.get("bid") or not o.get("iv") or not o.get("S"):
            continue
        d = abs(delta(o["S"], o["K"], (o["venc"] - t) / ANO_MS, o["iv"], o["tipo"]))
        if d > 0.5:
            continue
        if dist is None or abs(d - alvo) < dist:
            melhor, dist = dict(o, delta=d), abs(d - alvo)
    return melhor


# ---------------------------------------------------------------------------------------------------- conta
class Conta:
    """Uma versão: dólar (`caixa`), a moeda comprada (`q`, nas calls cobertas) e as opções vendidas em aberto."""

    def __init__(self, cfg, estado=None):
        (self.id, self.nome, self.moeda, self.tipo, self.alvo, self.prazo, self.stop, self.risco, self.frase) = cfg
        e = estado or {}
        self.curva = Curva.de_json(e.get("curva"))  # None até a 1ª venda (o ao vivo começa na 1ª sexta)
        self.caixa = float(e.get("caixa", CAPITAL))
        self.q = float(e.get("q", 0.0))
        self.pos = list(e.get("pos") or [])
        self.ultima = int(e.get("ultima") or 0)  # a sexta (08h UTC) da última venda
        self.criado = int(e.get("criado") or 0)
        a = e.get("acc") or {}
        self.acc = {k: float(a.get(k, 0)) for k in ("premios", "pagos", "vendas", "dentro", "fora", "recompras")}
        self.ultimo_s = e.get("s")

    def para_json(self):
        return {"curva": self.curva.para_json() if self.curva else None, "caixa": self.caixa, "q": self.q, "pos": self.pos,
                "ultima": self.ultima, "criado": self.criado, "acc": self.acc, "s": self.ultimo_s}

    def _ev(self, ev, t, tipo, texto):
        if ev is not None:
            ev.add(t, tipo, texto, self.id)

    def _operou(self, taxa, n=1):
        if self.curva:
            self.curva.operou(taxa, n)

    def valor(self, mk, t):
        S = mk.preco(self.moeda, t) or self.ultimo_s or 0.0
        v = self.caixa + self.q * S
        for op in self.pos:
            mc = mk.marca(op, t)
            v -= (mc[0] if mc else op.get("ult", op["premio"])) * op["q"]
        return v

    def _rotulo(self, op):
        return f"{'put' if op['tipo'] == 'put' else 'call'} de {_strike_txt(op['K'])}"

    # ------------------------------------------------------------------ passos
    def _vencer(self, mk, t, ev):
        for op in [o for o in self.pos if o["venc"] <= t]:
            P = mk.entrega(self.moeda, op["venc"])
            fonte = "o preço de entrega"
            if not P:
                P = mk.preco(self.moeda, t) or self.ultimo_s
                fonte = "o índice da rodada (sem o preço de entrega)"
            if not P:
                continue
            fora = (op["K"] - P) if op["tipo"] == "put" else (P - op["K"])
            pago = max(0.0, fora) * op["q"]
            taxa = min(TAXA_ENTREGA * P * op["q"], TETO_TAXA * pago) if pago > 0 else 0.0
            self.caixa -= pago + taxa
            self._operou(taxa, 1 if taxa else 0)
            self.acc["pagos"] += pago
            res = op["premio"] * op["q"] - op.get("taxa", 0.0) - pago - taxa
            if self.curva:
                self.curva.fechou(res)
            nome = "o bitcoin" if self.moeda == "BTC" else "o ether"
            if pago > 0:
                self.acc["dentro"] += 1
                self._ev(ev, op["venc"], "pagou", f"A {self._rotulo(op)} venceu dentro: {nome} fechou a {_strike_txt(P)} "
                                                 f"(pelo {fonte}) e a conta pagou {moeda_br(pago)}; o prêmio tinha sido "
                                                 f"{moeda_br(op['premio'] * op['q'])}.")
            else:
                self.acc["fora"] += 1
                self._ev(ev, op["venc"], "recebeu", f"A {self._rotulo(op)} venceu sem valor ({nome} a {_strike_txt(P)}): "
                                                    f"ficou com o prêmio de {moeda_br(op['premio'] * op['q'])}.")
            self.pos.remove(op)

    def _recomprar(self, mk, t, ev):
        if not self.stop:
            return
        for op in list(self.pos):
            mc = mk.marca(op, t)
            if not mc or mc[0] < self.stop * op["premio"]:
                continue
            S = mk.preco(self.moeda, t) or self.ultimo_s
            custo = mc[1] * op["q"]
            taxa = taxa_opcao(S, op["q"], mc[1])
            self.caixa -= custo + taxa
            self._operou(taxa)
            self.acc["pagos"] += custo
            self.acc["recompras"] += 1
            if self.curva:
                self.curva.fechou(op["premio"] * op["q"] - op.get("taxa", 0.0) - custo - taxa)
            self._ev(ev, t, "fechou", f"Recomprou a {self._rotulo(op)} por {moeda_br(custo)}: ela passou de "
                                      f"{num_br(self.stop, 0)} vezes o prêmio ({moeda_br(op['premio'] * op['q'])}). Espera a próxima sexta.")
            self.pos.remove(op)

    def _ajustar_moeda(self, mk, t, frac, ev):
        """Leva a moeda comprada a `frac` do valor da conta (call coberta: 100%; strangle: 50%; put: 0), pagando a taxa
        do à vista e o deslize."""
        S = mk.preco(self.moeda, t)
        if not S:
            return False
        c = TAXA_SPOT + DESLIZE_SPOT
        v = self.caixa + self.q * S
        dq = v * frac / S - self.q
        if abs(dq) * S < 1.0:
            return True
        if dq > 0:
            dq /= 1 + c  # o que se gasta (compra + custo) é o que faltava
            custo = dq * S * c
            self.caixa -= dq * S + custo
            self._ev(ev, t, "comprou", f"Comprou {num_br(dq, 4)} {self.moeda} a {_strike_txt(S)} para cobrir a call.")
        else:
            custo = -dq * S * c
            self.caixa += -dq * S - custo
        self.q += dq
        self._operou(custo)
        return True

    def _vender_uma(self, mk, t, tipo, garantia, ev):
        venc = escolher_vencimento(mk, self.moeda, t, self.prazo)
        if not venc:
            return None
        op = escolher_strike(mk.opcoes(self.moeda, t, tipo, venc), t, self.alvo)
        if not op:
            return None
        S = mk.preco(self.moeda, t) or op["S"]
        q = garantia / op["K"] if tipo == "put" else garantia
        if q <= 0:
            return None
        premio = op["bid"] * q
        taxa = taxa_opcao(S, q, op["bid"])
        self.caixa += premio - taxa
        self._operou(taxa)
        self.acc["premios"] += premio
        self.acc["vendas"] += 1
        p = {"inst": op["inst"], "moeda": self.moeda, "tipo": tipo, "K": op["K"], "venc": venc, "q": q,
             "premio": op["bid"], "taxa": taxa, "iv": op.get("iv"), "delta": round(op["delta"], 3), "em": t}
        self.pos.append(p)
        self._ev(ev, t, "vendeu", f"Vendeu a {self._rotulo(p)} (vence {_ddmm(venc)}, delta {num_br(op['delta'], 2)}) "
                                  f"por {moeda_br(premio)}, {pct_br(premio / max(1.0, garantia if tipo == 'put' else garantia * S), 2)} "
                                  "da garantia.")
        return p

    def _pode_vender(self, t):
        sexta = sexta_08(t)
        return (not self.pos and sexta > max(self.ultima, self.criado) and t - sexta < JANELA_VENDA)

    def _vender(self, mk, t, ev):
        S = mk.preco(self.moeda, t)
        if not S:
            return
        frac = {"put": 0.0, "call": 1.0, "strangle": 0.5}[self.tipo]
        if self.curva is None:
            self.curva = Curva(inicio=t)
            self.curva.marcar(t, self.caixa + self.q * S)
        self._ajustar_moeda(mk, t, frac, ev)
        v = self.caixa + self.q * S
        vendeu = []
        if self.tipo in ("put", "strangle"):
            vendeu.append(self._vender_uma(mk, t, "put", v * (1 - frac), ev))
        if self.tipo in ("call", "strangle"):
            vendeu.append(self._vender_uma(mk, t, "call", self.q, ev))
        if any(vendeu):
            self.ultima = sexta_08(t)

    def passo(self, mk, t, ev=None):
        """Um instante `t`: vencimentos, recompra, venda de sexta e a marcação."""
        S = mk.preco(self.moeda, t)
        self._vencer(mk, t, ev)
        self._recomprar(mk, t, ev)
        if self._pode_vender(t):
            self._vender(mk, t, ev)
        if S:
            self.ultimo_s = S
        for op in self.pos:
            mc = mk.marca(op, t)
            if mc:
                op["ult"] = mc[0]
        if self.curva:
            self.curva.marcar(t, self.valor(mk, t))
            self._extra(mk, t)

    def _extra(self, mk, t):
        a = self.acc
        aberta = None
        if self.pos:
            op = self.pos[0]
            aberta = f"{'Put' if op['tipo'] == 'put' else 'Call'} {num_br(op['K'], 0)} · vence {_ddmm(op['venc'])}"
            if len(self.pos) > 1:
                aberta += f" (+{len(self.pos) - 1})"
        S = mk.preco(self.moeda, t) or self.ultimo_s or 0
        self.curva.extra = {"premios": round(a["premios"], 4), "pagos": round(a["pagos"], 4), "vendas": int(a["vendas"]),
                            "dentro": int(a["dentro"]), "semValor": int(a["fora"]), "recompras": int(a["recompras"]),
                            "emAberto": aberta, "naMoeda": round(self.q * S, 2), "moeda": self.moeda}


# ---------------------------------------------------------------------------------------------------- API
def ler_cadeias(fonte, log, erros, est):
    cadeias, indices, entregas = {}, {}, {}
    for m in MOEDAS:
        try:
            r = fonte.deribit("get_book_summary_by_currency", currency=m, kind="option")
            if not isinstance(r, list) or not r:
                raise rede.Erro(f"cadeia de {m} vazia")
            if not est.get("formatoVisto"):
                log(f"  opções: formato da cadeia de {m}: {rede.estrutura(r[0], 2)}")
            cadeias[m] = r
        except ERROS as e:
            erros.append(f"cadeia de {m}: {e}")
            log(f"  opções: cadeia de {m}: {e}")
            continue
        try:
            r = fonte.deribit("get_index_price", index_name=f"{m.lower()}_usd") or {}
            p = _f(r.get("index_price")) or _f(r.get("estimated_delivery_price"))
            if p:
                indices[m] = p
        except ERROS as e:
            erros.append(f"índice de {m}: {e}")
        try:
            r = fonte.deribit("get_delivery_prices", index_name=f"{m.lower()}_usd", count=14) or {}
            entregas[m] = {str(x.get("date")): _f(x.get("delivery_price")) for x in (r.get("data") or [])
                           if isinstance(x, dict) and _f(x.get("delivery_price"))}
            if not est.get("formatoVisto"):
                log(f"  opções: formato das entregas de {m}: {rede.estrutura(r, 3)}")
        except ERROS as e:
            erros.append(f"preços de entrega de {m}: {e}")
    if cadeias:
        est["formatoVisto"] = True
    return cadeias, indices, entregas


def ler_dvol(fonte, m, ini, fim, log, erros):
    """{hora ms: fração} do DVOL (fechamento de cada hora), em pedaços de 30 dias."""
    out, a = {}, int(ini)
    while a < fim:
        b = min(int(fim), a + DVOL_PEDACO)
        try:
            r = fonte.deribit("get_volatility_index_data", currency=m, start_timestamp=a, end_timestamp=b, resolution=3600) or {}
        except ERROS as e:
            erros.append(f"DVOL de {m}: {e}")
            log(f"  opções: DVOL de {m}: {e}; o teste no passado usa a volatilidade realizada")
            return out
        for x in r.get("data") or []:
            if isinstance(x, list) and len(x) >= 5 and _f(x[4]):
                out[(int(x[0]) // HORA) * HORA] = float(x[4]) / 100
        a = b
    return out


def velas_1h(cli, m, ini, fim, erros):
    """{hora do fim da vela: fechamento} pelas velas de 1 h da Hyperliquid (o perpétuo, muito perto do índice)."""
    try:
        return {int(c["t"]) + HORA: float(c["c"]) for c in cli.velas(m, "1h", ini, fim) if _f(c.get("c"))}
    except ERROS as e:
        erros.append(f"velas de {m}: {e}")
        return {}


def horas(a, b):
    t = (int(a) // HORA) * HORA + HORA
    while t <= b:
        yield t
        t += HORA


def teste_no_passado(mh, ini, fim):
    out = {}
    for cfg in VERSOES:
        c = Conta(cfg)
        c.criado = ini
        for t in horas(ini, fim):
            if mh.preco(cfg[2], t):
                c.passo(mh, t)
        out[cfg[0]] = c.curva.resumo(de=dia_de(c.curva.inicio), ate=dia_de(fim), aproximado=True,
                                     nota="Aproximado: preços pela fórmula de Black-Scholes com o índice de volatilidade "
                                          "da Deribit (DVOL), não os da cadeia da época; vende às sextas 08h UTC.") if c.curva else None
    return out


def rodar(ctx):
    erros = []
    est = copy.deepcopy(ctx.est)
    agora, log = int(ctx.agora), ctx.log
    fonte = rede.fonte_de(ctx, "deribit")
    p0 = getattr(fonte, "pedidos", 0)
    try:
        cadeias, indices, entregas = ler_cadeias(fonte, log, erros, est)
        if not cadeias:
            raise rede.Erro("nenhuma cadeia de opções respondeu: " + "; ".join(erros[:2]))
        mk = MercadoVivo(cadeias, indices, entregas)

        # ---------------------------------------------------------------- ao vivo
        vivo = est.setdefault("vivo", {})
        ev = Eventos(est.get("eventos"))
        for cfg in VERSOES:
            vid = cfg[0]
            if cfg[2] not in cadeias:
                continue
            c = Conta(cfg, vivo.get(vid))
            if not c.criado:
                c.criado = agora
                prox = sexta_08(agora) + 7 * DIA
                ev.add(agora, "aviso", f"Começou a esperar a 1ª sexta ({_ddmm(prox)}) para vender a primeira opção.", vid)
            try:
                c.passo(mk, agora, ev)
                vivo[vid] = c.para_json()
            except Exception as e:  # noqa: BLE001 (uma versão com problema não derruba as outras)
                erros.append(f"{vid} ao vivo: {e}")
                log(f"  opções: {vid} ao vivo: {e}")

        # ---------------------------------------------------------------- teste no passado
        hist = est.get("hist") or {}
        refazer = not hist or agora - int(hist.get("em") or 0) >= HIST_REFAZER or hist.get("v") != VERSAO
        if refazer and ctx.restante() < HIST_TEMPO_MIN:
            log(f"  opções: pouco tempo na rodada ({ctx.restante():.0f} s); o teste no passado fica para a próxima")
            refazer = False
        if refazer:
            fim = (agora // HORA) * HORA
            ini = fim - HIST_DIAS * DIA
            precos = {m: velas_1h(ctx.cli, m, ini - 25 * DIA, agora, erros) for m in MOEDAS}
            dvol = {m: ler_dvol(fonte, m, ini, agora, log, erros) for m in MOEDAS}
            fonte_iv = "dvol" if all(dvol.values()) else "realizada"
            if any(precos.values()):
                primeira = max(min(p) for p in precos.values() if p)
                t0 = max(ini, primeira + 25 * DIA if fonte_iv == "realizada" else primeira)
                res = teste_no_passado(MercadoHist(precos, dvol), t0, fim)
                hist = {"v": VERSAO, "em": agora, "de": t0, "ate": fim, "versoes": res, "iv": fonte_iv}
                est["hist"] = hist
                log(f"  opções: teste no passado refeito ({dia_de(t0)} a {dia_de(fim)}, volatilidade: {fonte_iv})")

        # ---------------------------------------------------------------- saída
        versoes, itens, comeca = [], [], None
        for cfg in VERSOES:
            vid, nome, moeda, tipo, alvo, prazo, stop, risco, frase = cfg
            e = vivo.get(vid) or {}
            curva = Curva.de_json(e.get("curva")) if e.get("curva") else None
            if curva is None and e.get("criado"):
                p = sexta_08(int(e["criado"])) + 7 * DIA
                comeca = min(comeca or p, p)
            versoes.append({"id": vid, "nome": nome, "frase": frase, "risco": risco, "alav": 1, "grupo": moeda,
                            "aoVivo": curva.resumo() if curva else None,
                            "historico": (hist.get("versoes") or {}).get(vid)})
            for op in e.get("pos") or []:
                itens.append({"versao": vid, "instrumento": op["inst"], "moeda": op["moeda"], "tipo": op["tipo"],
                              "strike": op["K"], "vence": op["venc"], "delta": op.get("delta"),
                              "premio": round(op["premio"] * op["q"], 4), "marca": round(op.get("ult", op["premio"]) * op["q"], 4),
                              "vendidaEm": op.get("em")})
        est["eventos"] = ev.para_json()
        ctx.est.clear()
        ctx.est.update(est)
        cfg_saida = {"frequencia": "a cada 6 h (vende às sextas, depois das 08h UTC)", "moedas": MOEDAS,
                     "fonte": "Deribit (pública)", "precos": {m: round(p, 2) for m, p in mk.indices.items()},
                     "taxas": {"opcao": TAXA_OPCAO, "entrega": TAXA_ENTREGA, "teto": TETO_TAXA},
                     "ivHistorico": hist.get("iv"), "deltaAlvo": {c[0]: c[4] for c in VERSOES}}
        if comeca:
            cfg_saida["aoVivoComeca"] = comeca
        return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": "put15", "versoes": versoes,
                "eventos": est["eventos"], "itens": sorted(itens, key=lambda x: x["vence"]), "avisos": AVISOS,
                "config": cfg_saida, "erros": erros}
    finally:
        rede.somar_pedidos(ctx, fonte, p0)
