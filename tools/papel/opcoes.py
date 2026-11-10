"""Venda de opções de bitcoin e ether NO PAPEL (plano: docs/plano-testes-mercado-2.md, seção 7; formato:
tools/papel/FORMATO.md). Nenhuma ordem, nenhuma conta, nenhuma chave: só a API pública da Deribit (e as velas da
Hyperliquid no teste no passado e na volatilidade realizada; o juro do dólar pelo GraphQL público do Aave).

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
30 dias, de hora em hora) no lugar da cadeia: preço pela fórmula de Black-Scholes com o DVOL ajustado pelo "sorriso"
(`iv_do_sorriso`), vendido pela oferta de compra estimada (o meio spread medido na cadeia, ou 3%, arredondada para baixo
no tique de 0,0001 da moeda), strikes de 1.000 (BTC) e 50 (ETH), vencimentos toda sexta às 08h UTC e entrega pelo
fechamento da vela das 07h–08h. Sem o DVOL, a volatilidade realizada de 30 dias × 1,1.

**Revisão de 09/11/2026** (pedido do Alediov, pelo teste no passado: put30 +3,3%, putstop +3,6%, eth_put15 +4,3%, mas
calls cobertas, strangle e a mensal negativas, Sharpe negativo em todas e o CDI ~6,7% no período):

- **Réguas** (`grupo` "Referência", por último): `segbtc` (só segurar BTC), `segeth` (só segurar ETH; as calls
  cobertas se comparam com elas) e `usdc` (USDC na Aave; as puts se comparam com ela). Começam na mesma 1ª sexta que as
  outras. Sem o juro da Aave, o `usdc` fica com `semDados`.
- **Garantia rendendo** (`put30C`, `putstopC`, `eth_put15C`, `grupo` "Garantia rendendo"): a garantia em dólar fica no
  empréstimo de USDC da Aave v3 na Base, rendendo o juro de cada dia (o mesmo GraphQL do looping/funding). Pôr lá custa
  `CAIXA_IDA` (o saque da corretora + o gás) uma vez; cada pagamento (vencimento dentro ou recompra) tira o valor da Aave
  pagando `CAIXA_VOLTA` (o gás). SUPOSIÇÃO: o dólar vai e volta pela própria Base (a Deribit recebe e manda USDC em
  mais de uma rede), então sem ponte; se precisasse de ponte, somaria ~0,04% por ida. Na Deribit de verdade a garantia
  precisa estar na corretora: guardá-la na Aave e só mandar o que for pago é a simplificação desta versão (como numa
  corretora que aceitasse um depósito que rende como garantia).
- **Prêmio caro** (`put30vrp`, `eth_put15vrp`, `grupo` "Prêmio caro"): só vende na sexta em que a volatilidade
  implícita (o DVOL; sem ele, a da opção no dinheiro da cadeia) ÷ a realizada de `VRP_DIAS` dias (de hora em hora,
  √(24 × 365)) ≥ `VRP_MIN` (1,2: a implícita costuma ficar ~10–15% acima da realizada; 20% a mais é um prêmio
  claramente caro). Nas semanas de fora, a garantia fica no USDC da Aave. Os eventos levam `motivo` "caro" (vendeu) ou
  "barato" (ficou de fora), com os dois números.
- **A roda** (`roda`, `eth_roda`, `grupo` "A roda"): vende a put de delta 0,30; se ela vence dentro, fica com a moeda
  (comprada no strike) e passa a vender a call de delta 0,30 sobre ela até ser chamada (vende a moeda no strike) e volta
  para a put. Eventos `trocou` com `motivo` "exercida" (put → moeda) e "chamada" (moeda → put); `extra.fase`.
- **Teste no passado mais realista** (`HIST_V` 2): o sorriso (a razão volatilidade do strike ÷ DVOL por delta, medida em
  cada rodada na cadeia da semana e guardada nas últimas `SORRISO_RODADAS`; sem medida, `SORRISO_PADRAO`), o meio spread
  medido na cadeia (mediana por delta; sem medida, 3%) e a oferta arredondada para baixo no tique; `historico.janelas`
  (30 dias a cada 7) contra a régua certa (`contra`: "usdc" nas puts, "segbtc"/"segeth" nas calls cobertas, "cdi" no
  strangle, na roda e nas réguas).
- **A conta por dentro** (`extra.porDentro`), o empate (`extra.empate`: quantas semanas de prêmio pagam os custos e
  quanto os prêmios já deixaram) e a pior semana (`extra.piorSemana`: o pior vencimento e quantas semanas de prêmio
  médio ele apagou).
- **Teste de estresse** (`estresse` na versão): queda de 15% e 30% num fim de semana (2 dias, volatilidade × 1,3) e,
  nas que seguram a moeda ou vendem call, alta de 15% e 30% (volatilidade × 1,1), sobre as posições abertas agora (ou,
  sem elas, as que a versão venderia agora pela cadeia), em US$, em % da conta e em semanas de prêmio médio do passado.

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
import conta as CT
from conta import CAPITAL, DIA, HORA, Curva, Eventos, dia_de, moeda_br, num_br, pct_br

try:
    import hl
    ERROS = (rede.Erro, hl.Erro)
except ImportError:  # pragma: no cover
    ERROS = (rede.Erro,)

try:  # o juro do dólar na Aave (o mesmo do funding) e as janelas (as do looping)
    import funding as FD
    import looping as LP
except ImportError:  # pragma: no cover
    FD = LP = None

NOME = "Opções"
VERSAO = 1
HIST_V = 2                # subir refaz o teste no passado (2: sorriso, spread, versões novas; 09/11/2026)

MOEDAS = ["BTC", "ETH"]
ANO_MS = 365 * DIA
TAXA_OPCAO = 0.0003       # da moeda, por opção vendida ou recomprada
TAXA_ENTREGA = 0.00015    # da moeda, no vencimento dentro do dinheiro
TETO_TAXA = 0.125         # as duas no máximo 12,5% do valor da opção
TAXA_SPOT = 0.0005        # comprar/vender a moeda da call coberta (à vista, quem tira liquidez)
DESLIZE_SPOT = 0.0002
TIQUE = 0.0001            # preço mínimo de uma opção, na moeda
MEIO_SPREAD_HIST = 0.03   # no teste no passado, sem medida da cadeia: oferta = preço teórico × (1 − 3%)
PASSO_STRIKE = {"BTC": 1000, "ETH": 50}
HORA_VENC = 8             # vencimento às 08h UTC
JANELA_VENDA = 3 * DIA    # vende do vencimento de sexta até domingo; depois espera a próxima sexta
SEMANA_MIN, SEMANA_MAX = 4 * DIA, 10 * DIA
MES_MIN, MES_MAX = 21 * DIA, 50 * DIA
HIST_DIAS = 180
HIST_REFAZER = 7 * DIA
HIST_TEMPO_MIN = 240      # segundos que precisam sobrar na rodada para refazer o teste no passado
DVOL_PEDACO = 30 * DIA    # o DVOL vem em pedaços de 30 dias de hora em hora (720 pontos por pedido)
MAX_EVENTOS_VIVO = 300
MESES = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}

# o sorriso: volatilidade do strike = base (DVOL) × razão(delta). Curva padrão (sem medida da cadeia), linear em
# (0,5 − |delta|): put de delta 0,15 ≈ 1,14 × DVOL, call de delta 0,15 ≈ 1,035 × DVOL (a put longe do preço é o seguro
# contra a queda e custa mais; a call longe, um pouco mais que a do dinheiro).
SORRISO_PADRAO = {"put": 0.40, "call": 0.10}
SORRISO_RAZAO = (0.6, 2.5)          # razões fora disso são descartadas (cadeia estranha)
SORRISO_DELTAS = [round(0.05 * i, 2) for i in range(1, 11)]  # 0,05 … 0,50
SORRISO_RODADAS = 40                # a média das últimas 40 medidas (10 dias de rodadas)
SPREAD_MAX = 0.5                    # meio spread acima de 50% do preço não entra na medida

# prêmio caro
VRP_MIN = 1.2
VRP_DIAS = 30
VRP_DIAS_CURTO = 7
VRP_MIN_HORAS = 7 * 24              # menos que isso de velas: sem a realizada (vende como a versão sem filtro)

# caixa na Aave (custos do funding, sem a ponte: ver o começo do arquivo)
CAIXA_IDA = FD.CAIXA_IDA if FD else 1.05
CAIXA_VOLTA = FD.CAIXA_VOLTA if FD else 0.10

# estresse
ESTRESSE_CHOQUES = (-0.15, -0.30, 0.15, 0.30)
ESTRESSE_VOL = {"queda": 1.3, "alta": 1.1}
ESTRESSE_DIAS = 2                   # um fim de semana

JANELA_DIAS, JANELA_PASSO = 30, 7

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
    # revisão de 09/11/2026
    ("put30C", "Put 0,30 + Aave", "BTC", "put", 0.30, "semana", None, "alto",
     "A put 0,30 da semana, com a garantia em dólar rendendo o juro do empréstimo de USDC da Aave enquanto espera."),
    ("putstopC", "Put com recompra + Aave", "BTC", "put", 0.15, "semana", 3.0, "médio",
     "A put 0,15 com recompra, com a garantia rendendo na Aave."),
    ("eth_put15C", "ETH put 0,15 + Aave", "ETH", "put", 0.15, "semana", None, "médio",
     "A put 0,15 de ether, com a garantia rendendo na Aave."),
    ("put30vrp", "Put 0,30 só caro", "BTC", "put", 0.30, "semana", None, "alto",
     "A put 0,30, mas só vende na sexta em que o prêmio está caro (a volatilidade implícita pelo menos 20% acima da que o "
     "bitcoin teve nos últimos 30 dias); nas outras semanas, o dólar fica rendendo na Aave."),
    ("eth_put15vrp", "ETH put 0,15 só caro", "ETH", "put", 0.15, "semana", None, "médio",
     "A put 0,15 de ether, só nas semanas de prêmio caro; nas outras, o dólar rende na Aave."),
    ("roda", "A roda", "BTC", "roda", 0.30, "semana", None, "alto",
     "Vende puts de delta 0,30; se uma vence dentro, fica com o bitcoin (comprado no strike) e passa a vender calls de "
     "delta 0,30 sobre ele até ser chamado, e volta para as puts."),
    ("eth_roda", "ETH: a roda", "ETH", "roda", 0.30, "semana", None, "alto",
     "A roda com o ether: puts até ser exercida, calls cobertas até ser chamada."),
    ("segbtc", "Só segurar BTC", "BTC", "regua", None, "semana", None, "alto",
     "Compra bitcoin com os US$ 1.000 na 1ª sexta e não faz mais nada: a régua das calls cobertas de bitcoin."),
    ("segeth", "Só segurar ETH", "ETH", "regua", None, "semana", None, "alto",
     "Compra ether com os US$ 1.000 na 1ª sexta e não faz mais nada: a régua das calls cobertas de ether."),
    ("usdc", "USDC na Aave", "BTC", "regua", None, "semana", None, "baixo",
     "Deixa os US$ 1.000 no empréstimo de dólar da Aave (rede Base) desde a 1ª sexta: a régua das puts, que guardam o "
     "mesmo dólar como garantia."),
]
OPCOES = {"put30C": {"caixa": True}, "putstopC": {"caixa": True}, "eth_put15C": {"caixa": True},
          "put30vrp": {"caixa": True, "vrp": True}, "eth_put15vrp": {"caixa": True, "vrp": True},
          "segbtc": {"regua": "moeda"}, "segeth": {"regua": "moeda"}, "usdc": {"regua": "usdc", "caixa": True}}
GRUPO = {"put30C": "Garantia rendendo", "putstopC": "Garantia rendendo", "eth_put15C": "Garantia rendendo",
         "put30vrp": "Prêmio caro", "eth_put15vrp": "Prêmio caro", "roda": "A roda", "eth_roda": "A roda",
         "segbtc": "Referência", "segeth": "Referência", "usdc": "Referência"}
NOMES_REGUA = {"usdc": "USDC na Aave", "segbtc": "Só segurar BTC", "segeth": "Só segurar ETH", "cdi": "CDI"}
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
    "Garantia rendendo: nas versões \"+ Aave\" o dólar da garantia fica no empréstimo de USDC da Aave (rede Base) e rende "
    "o juro de cada dia; só sai o que for pago. Prêmio caro: só vende quando a volatilidade que o mercado cobra passa em "
    "20% a que a moeda teve nos últimos 30 dias. A roda: put até ser exercida, depois call sobre a moeda até ser chamada.",
    "Réguas: Só segurar BTC e Só segurar ETH (para as calls cobertas, que seguram a moeda) e USDC na Aave (para as "
    "puts, que guardam dólar). Uma versão só vale a pena se passar a régua certa, não só o zero.",
    "O teste no passado é aproximado: sem a cadeia antiga, os preços saem da fórmula de Black-Scholes com o índice de "
    "volatilidade da Deribit (DVOL), ajustado pelo sorriso (as opções longe do preço custam mais) medido na cadeia de "
    "agora, e vendidos pela oferta de compra estimada (o spread medido na cadeia).",
]
AVISOS = [
    "Na Deribit, a menor opção de bitcoin é de 0,1 BTC (e de ether, 1 ETH): uns US$ 7 mil de garantia. Com US$ 1.000, a "
    "conta de verdade não conseguiria vender nem uma; o papel vende frações.",
    "As opções clássicas da Deribit usam a própria moeda como garantia, não dólar: numa queda forte, a garantia também "
    "cai. A conta em dólar do papel é uma simplificação.",
    "Garantia rendendo: na corretora de verdade a garantia precisa estar lá; deixá-la na Aave e só mandar o que for pago "
    "é uma simplificação. A Aave é mais um lugar que pode falhar.",
    "O papel olha a cadeia só a cada 6 h: a recompra (versão com recompra) e a venda de sexta acontecem na primeira "
    "rodada depois do momento certo, não no minuto exato. Um salto no fim de semana pode passar por cima.",
    "A melhor oferta de compra da cadeia vale para poucas opções; uma venda grande pegaria preços piores.",
    "A Deribit exige cadastro com documentos, e o uso por quem mora no Brasil precisa ser conferido antes.",
    "O teste no passado não tem os preços de verdade da época: usa a fórmula com o DVOL (a volatilidade de 30 dias, não "
    "a de cada semana), o sorriso e o spread medidos nas cadeias de agora.",
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


def _r(x, c=4):
    return round(float(x), c) + 0.0  # + 0.0: sem "-0.0" no JSON


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


def cfg_de(vid):
    return next(c for c in VERSOES if c[0] == vid)


def contra_de(cfg):
    """A régua certa de cada versão (para as janelas): as puts contra o USDC na Aave (guardam o mesmo dólar), as calls
    cobertas contra segurar a moeda, o strangle e a roda (metade ou parte do tempo em cada) e as réguas contra o CDI."""
    vid, moeda, tipo = cfg[0], cfg[2], cfg[3]
    if tipo == "put":
        return "usdc"
    if tipo == "call":
        return "segbtc" if moeda == "BTC" else "segeth"
    return "cdi"


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


def razao_padrao(tipo, d):
    """A razão volatilidade do strike ÷ DVOL da curva padrão, pelo |delta| (calculado com o DVOL)."""
    return 1 + SORRISO_PADRAO[tipo] * (0.5 - min(0.5, max(0.0, d)))


def _interpolar(tab, d):
    """`tab` = {"0.05": razão, …}; linear entre os deltas medidos, constante fora deles. None se vazia."""
    pts = sorted((float(k), float(v)) for k, v in (tab or {}).items() if _f(v))
    if not pts:
        return None
    if d <= pts[0][0]:
        return pts[0][1]
    if d >= pts[-1][0]:
        return pts[-1][1]
    for (a, ra), (b, rb) in zip(pts, pts[1:]):
        if a <= d <= b:
            return ra + (rb - ra) * (d - a) / (b - a) if b > a else ra
    return pts[-1][1]


def iv_do_sorriso(base, S, K, T, tipo, curva=None):
    """A volatilidade do strike: o DVOL (`base`, "no dinheiro") × a razão do sorriso pelo |delta| (calculado com a base).
    `curva` = {"put": {delta: razão}, "call": {…}} medida na cadeia; sem ela (ou sem o lado), a curva padrão."""
    d = abs(delta(S, K, T, base, tipo))
    r = _interpolar((curva or {}).get(tipo), d)
    return base * (r if r is not None else razao_padrao(tipo, d))


def iv_com_inclinacao(base, S, K, T, tipo):  # nome antigo (o falso e quem mais usar)
    return iv_do_sorriso(base, S, K, T, tipo)


def taxa_opcao(S, q, preco_un):
    return min(TAXA_OPCAO * S * q, TETO_TAXA * preco_un * q)


def vol_realizada(precos_m, t, dias):
    """A volatilidade realizada ao ano dos últimos `dias` dias até `t`, pelos fechamentos de hora em hora
    ({hora ms: preço}); None com menos de VRP_MIN_HORAS horas."""
    h = (int(t) // HORA) * HORA
    ps = [precos_m.get(h - i * HORA) for i in range(dias * 24, -1, -1)]
    rs = [math.log(b / a) for a, b in zip(ps, ps[1:]) if a and b]
    if len(rs) < min(VRP_MIN_HORAS, dias * 24 * 0.8):
        return None
    med = sum(rs) / len(rs)
    v = math.sqrt(sum((x - med) ** 2 for x in rs) / (len(rs) - 1) * 24 * 365)
    return v if v > 0 else None


# ---------------------------------------------------------------------------------------------------- mercados
class _Base:
    """O que os dois mercados têm em comum: o juro do dólar na Aave (`aave`: looping.Taxas com "sup:USDC", ou None) e
    a volatilidade realizada pelos preços de hora em hora (`precos`)."""
    aave = None
    precos = None

    def juro(self, t):
        if self.aave is None:
            return 0.0
        try:
            return max(0.0, float(self.aave.taxa("sup:USDC", t) or 0.0))
        except (TypeError, ValueError):
            return 0.0

    def realizada(self, m, t, dias=VRP_DIAS):
        return vol_realizada((self.precos or {}).get(m) or {}, t, dias)


class MercadoVivo(_Base):
    """A cadeia de uma rodada: `cadeias[moeda]` = lista do get_book_summary_by_currency; `indices[moeda]` = preço;
    `entregas[moeda]` = {AAAA-MM-DD: preço de entrega}; `dvol[moeda]` = o DVOL de agora (fração) ou None; `precos` =
    {moeda: {hora ms: preço}} dos últimos ~31 dias (a volatilidade realizada)."""

    def __init__(self, cadeias, indices, entregas, dvol=None, precos=None, aave=None):
        self.ops, self.indices, self.entregas = {}, dict(indices), {m: dict(v) for m, v in (entregas or {}).items()}
        self.dvol = dict(dvol or {})
        self.precos = precos or {}
        self.aave = aave
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

    def iv_no_dinheiro(self, m, t):
        """A volatilidade da opção da semana com o strike mais perto do preço (média da put e da call)."""
        venc = escolher_vencimento(self, m, t, "semana")
        S = self.preco(m, t)
        if not venc or not S:
            return None
        ivs = [o for o in self.ops.get(m, {}).values() if o["venc"] == venc and o.get("iv")]
        if not ivs:
            return None
        k = min(ivs, key=lambda o: abs(o["K"] - S))["K"]
        xs = [o["iv"] for o in ivs if o["K"] == k]
        return sum(xs) / len(xs)

    def implicita(self, m, t):
        return self.dvol.get(m) or self.iv_no_dinheiro(m, t)

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


class MercadoHist(_Base):
    """O passado sem a cadeia: velas de 1 h (`precos[moeda]` = {hora ms (fim da vela): fechamento}) e o DVOL
    (`dvol[moeda]` = {hora ms: fração}); as opções saem da fórmula com o sorriso e o spread (`sorriso[moeda]` = o
    resumo de `resumo_sorriso`, ou None para a curva padrão e 3%)."""

    def __init__(self, precos, dvol, sorriso=None, aave=None):
        self.precos = precos
        self.dvol = dvol
        self.sorriso = sorriso or {}
        self.aave = aave
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
            r = vol_realizada(self.precos.get(m, {}), h, 30)
            self._iv[(m, dia)] = 1.1 * r if r else 0.55
        return self._iv[(m, dia)]

    def implicita(self, m, t):
        return self.vol(m, t)

    def vencimentos(self, m, t):
        a = sexta_08(t)
        return [a + k * 7 * DIA for k in range(1, 9)]

    def meio_spread(self, m, tipo, d):
        tab = ((self.sorriso.get(m) or {}).get("spread") or {}).get(tipo)
        r = _interpolar(tab, d)
        return r if r is not None else MEIO_SPREAD_HIST

    def _cotar(self, m, t, K, venc, tipo):
        S, base = self.preco(m, t), self.vol(m, t)
        T = (venc - t) / ANO_MS
        curva = self.sorriso.get(m) or {}
        iv = iv_do_sorriso(base, S, K, T, tipo, curva)
        teo = bs(S, K, T, iv, tipo)
        d0 = abs(delta(S, K, T, base, tipo))
        meio = max(self.meio_spread(m, tipo, d0) * teo, TIQUE * S / 2)
        tq = TIQUE * S
        bid = math.floor((teo - meio) / tq + 1e-9) * tq  # a oferta de compra fica no tique, para baixo
        return {"bid": bid if bid >= tq else None, "ask": teo + meio, "mark": teo, "iv": iv, "S": S}

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


# ---------------------------------------------------------------------------------------------------- o sorriso
def medir_sorriso(mk, m, t, base=None):
    """Uma medida do sorriso e do spread na cadeia de agora (só o vencimento da semana): por tipo e por |delta|
    arredondado para 0,05, a média da razão `mark_iv` ÷ `base` (o DVOL; sem ele, a volatilidade no dinheiro) e a
    mediana do meio spread relativo ((oferta de venda − de compra) ÷ 2 ÷ marca). None sem cadeia."""
    venc = escolher_vencimento(mk, m, t, "semana")
    if not venc:
        return None
    fonte = "dvol" if base else "atm"
    base = base or mk.iv_no_dinheiro(m, t)
    if not base:
        return None
    raz, spr = {"put": {}, "call": {}}, {"put": {}, "call": {}}
    for o in mk.ops.get(m, {}).values():
        if o["venc"] != venc or not o.get("iv") or not o.get("S"):
            continue
        d0 = abs(delta(o["S"], o["K"], (o["venc"] - t) / ANO_MS, base, o["tipo"]))
        if d0 < 0.025 or d0 > 0.525:
            continue
        b = f"{min(SORRISO_DELTAS, key=lambda x: abs(x - d0)):.2f}"
        r = o["iv"] / base
        if SORRISO_RAZAO[0] <= r <= SORRISO_RAZAO[1]:
            raz[o["tipo"]].setdefault(b, []).append(r)
        if o.get("bid") and o.get("ask") and o.get("mark") and o["mark"] > 0:
            s = (o["ask"] - o["bid"]) / 2 / o["mark"]
            if 0 <= s <= SPREAD_MAX:
                spr[o["tipo"]].setdefault(b, []).append(s)
    med = lambda xs: sorted(xs)[len(xs) // 2]  # noqa: E731
    out = {"em": int(t), "base": fonte,
           "put": {k: round(sum(v) / len(v), 4) for k, v in raz["put"].items()},
           "call": {k: round(sum(v) / len(v), 4) for k, v in raz["call"].items()},
           "spread": {tp: {k: round(med(v), 4) for k, v in spr[tp].items()} for tp in ("put", "call")}}
    return out if out["put"] or out["call"] else None


def resumo_sorriso(medidas):
    """A média das últimas medidas de uma moeda: {"put": {delta: razão}, "call": {…}, "spread": {"put": {…}, "call":
    {…}}, "n", "fonte": "cadeia"}; None sem medidas."""
    xs = [x for x in (medidas or []) if x][-SORRISO_RODADAS:]
    if not xs:
        return None
    out = {"n": len(xs), "fonte": "cadeia", "de": min(x["em"] for x in xs), "ate": max(x["em"] for x in xs)}
    for tp in ("put", "call"):
        acc = {}
        for x in xs:
            for k, v in (x.get(tp) or {}).items():
                acc.setdefault(k, []).append(v)
        out[tp] = {k: round(sum(v) / len(v), 4) for k, v in sorted(acc.items())}
    out["spread"] = {}
    for tp in ("put", "call"):
        acc = {}
        for x in xs:
            for k, v in ((x.get("spread") or {}).get(tp) or {}).items():
                acc.setdefault(k, []).append(v)
        out["spread"][tp] = {k: round(sorted(v)[len(v) // 2], 4) for k, v in sorted(acc.items())}
    return out


def sorriso_padrao():
    """A curva padrão, no mesmo formato do resumo (para o app mostrar)."""
    return {"n": 0, "fonte": "padrao",
            "put": {f"{d:.2f}": round(razao_padrao("put", d), 4) for d in SORRISO_DELTAS},
            "call": {f"{d:.2f}": round(razao_padrao("call", d), 4) for d in SORRISO_DELTAS},
            "spread": {"put": {}, "call": {}}, "meioSpreadPadrao": MEIO_SPREAD_HIST}


# ---------------------------------------------------------------------------------------------------- conta
ACC = ("premios", "pagos", "vendas", "dentro", "fora", "recompras",
       "pagosVenc", "recCusto", "txOp", "txEnt", "txSpot", "juros", "aave", "semanasFora", "semanasCaro",
       "exercidas", "chamadas")


class Conta:
    """Uma versão: dólar (`caixa`), a moeda comprada (`q`, nas calls cobertas e na roda) e as opções vendidas em aberto."""

    def __init__(self, cfg, estado=None):
        (self.id, self.nome, self.moeda, self.tipo, self.alvo, self.prazo, self.stop, self.risco, self.frase) = cfg
        self.opc = OPCOES.get(self.id, {})
        self.caixa_aave = bool(self.opc.get("caixa"))
        self.vrp = bool(self.opc.get("vrp"))
        self.regua = self.opc.get("regua")
        e = estado or {}
        self.curva = Curva.de_json(e.get("curva"))  # None até a 1ª venda (o ao vivo começa na 1ª sexta)
        self.caixa = float(e.get("caixa", CAPITAL))
        self.q = float(e.get("q", 0.0))
        self.pos = list(e.get("pos") or [])
        self.ultima = int(e.get("ultima") or 0)  # a sexta (08h UTC) da última venda
        self.criado = int(e.get("criado") or 0)
        a = e.get("acc") or {}
        self.acc = {k: float(a.get(k, 0)) for k in ACC}
        self.ultimo_s = e.get("s")
        self.na_aave = bool(e.get("naAave"))
        self.t = int(e.get("t") or 0)
        self.fase = e.get("fase") or "put"
        self.fech = list(e.get("fech") or [])  # [vencimento, resultado da opção (US$), prêmio líquido (US$)]
        self.filtro = e.get("filtro")  # a última decisão do prêmio caro

    def para_json(self):
        return {"curva": self.curva.para_json() if self.curva else None, "caixa": self.caixa, "q": self.q, "pos": self.pos,
                "ultima": self.ultima, "criado": self.criado, "acc": self.acc, "s": self.ultimo_s,
                "naAave": self.na_aave, "t": self.t, "fase": self.fase, "fech": self.fech[-300:], "filtro": self.filtro}

    def _ev(self, ev, t, tipo, texto, motivo=None):
        if ev is not None:
            ev.add(t, tipo, texto, self.id)
            if motivo:
                ev.lista[-1]["motivo"] = motivo

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

    @property
    def nome_moeda(self):
        return "o bitcoin" if self.moeda == "BTC" else "o ether"

    # ------------------------------------------------------------------ a Aave
    def _juros(self, mk, t):
        if self.na_aave and self.caixa > 0 and self.t and t > self.t:
            j = self.caixa * ((1 + mk.juro(t)) ** ((t - self.t) / ANO_MS) - 1)
            self.caixa += j
            self.acc["juros"] += j
        self.t = int(t)

    def _para_aave(self, mk, t, ev):
        if self.na_aave or self.caixa <= 1:
            return
        self.caixa -= CAIXA_IDA
        self.acc["aave"] += CAIXA_IDA
        self._operou(CAIXA_IDA)
        self.na_aave = True
        self._ev(ev, t, "caixa", f"Pôs {moeda_br(self.caixa)} no empréstimo de dólar da Aave a {pct_br(mk.juro(t))} ao ano "
                                 f"(saque e gás: {moeda_br(CAIXA_IDA)}).")

    def _pagar(self, valor):
        """Paga `valor` (US$) da caixa; com o dólar na Aave, tirar de lá custa o gás de uma volta."""
        self.caixa -= valor
        if self.na_aave and valor > 0:
            self.caixa -= CAIXA_VOLTA
            self.acc["aave"] += CAIXA_VOLTA
            self._operou(CAIXA_VOLTA, 0)

    def _fechou(self, op, res):
        if self.curva:
            self.curva.fechou(res)
        self.fech.append([int(op["venc"]), round(res, 4), round(op["premio"] * op["q"] - op.get("taxa", 0.0), 4)])
        del self.fech[:-300]

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
            self._operou(taxa, 1 if taxa else 0)
            self.acc["txEnt"] += taxa
            self.acc["pagos"] += pago
            self.acc["pagosVenc"] += pago
            res = op["premio"] * op["q"] - op.get("taxa", 0.0) - pago - taxa
            self._fechou(op, res)
            nome = self.nome_moeda
            if self.tipo == "roda" and pago > 0:
                # entrega física: a put exercida compra a moeda no strike; a call chamada vende no strike. Conta-se
                # como pagar a diferença e comprar (ou vender) a moeda pelo preço de entrega, sem custo de à vista.
                self._pagar(pago + taxa)
                self.acc["dentro"] += 1
                if op["tipo"] == "put":
                    self.caixa -= P * op["q"]
                    self.q += op["q"]
                    self.fase = "call"
                    self.acc["exercidas"] += 1
                    self._ev(ev, op["venc"], "trocou", f"A {self._rotulo(op)} foi exercida ({nome} a {_strike_txt(P)}): a "
                                                       f"conta comprou {num_br(op['q'], 4)} {self.moeda} a "
                                                       f"{_strike_txt(op['K'])} e passa a vender calls sobre eles.", "exercida")
                else:
                    q = min(op["q"], self.q)
                    self.caixa += P * q
                    self.q -= q
                    if self.q < 1e-12:
                        self.q = 0.0
                        self.fase = "put"
                    self.acc["chamadas"] += 1
                    self._ev(ev, op["venc"], "trocou", f"A {self._rotulo(op)} foi chamada ({nome} a {_strike_txt(P)}): a "
                                                       f"conta vendeu {num_br(q, 4)} {self.moeda} a {_strike_txt(op['K'])} "
                                                       "e volta a vender puts.", "chamada")
            elif pago > 0:
                self._pagar(pago + taxa)
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
            self._pagar(custo + taxa)
            self._operou(taxa)
            self.acc["txOp"] += taxa
            self.acc["pagos"] += custo
            self.acc["recCusto"] += custo
            self.acc["recompras"] += 1
            self._fechou(op, op["premio"] * op["q"] - op.get("taxa", 0.0) - custo - taxa)
            self._ev(ev, t, "fechou", f"Recomprou a {self._rotulo(op)} por {moeda_br(custo)}: ela passou de "
                                      f"{num_br(self.stop, 0)} vezes o prêmio ({moeda_br(op['premio'] * op['q'])}). Espera a próxima sexta.")
            self.pos.remove(op)

    def _ajustar_moeda(self, mk, t, frac, ev, para="cobrir a call"):
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
            self._ev(ev, t, "comprou", f"Comprou {num_br(dq, 4)} {self.moeda} a {_strike_txt(S)} para {para}.")
        else:
            custo = -dq * S * c
            self.caixa += -dq * S - custo
        self.q += dq
        self.acc["txSpot"] += custo
        self._operou(custo)
        return True

    def _vender_uma(self, mk, t, tipo, garantia, ev, extra_txt="", motivo=None):
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
        self.acc["txOp"] += taxa
        self.acc["premios"] += premio
        self.acc["vendas"] += 1
        p = {"inst": op["inst"], "moeda": self.moeda, "tipo": tipo, "K": op["K"], "venc": venc, "q": q,
             "premio": op["bid"], "taxa": taxa, "iv": op.get("iv"), "delta": round(op["delta"], 3), "em": t}
        self.pos.append(p)
        self._ev(ev, t, "vendeu", f"{extra_txt}Vendeu a {self._rotulo(p)} (vence {_ddmm(venc)}, delta "
                                  f"{num_br(op['delta'], 2)}) por {moeda_br(premio)}, "
                                  f"{pct_br(premio / max(1.0, garantia if tipo == 'put' else garantia * S), 2)} da garantia.",
                 motivo)
        return p

    def _pode_vender(self, t):
        sexta = sexta_08(t)
        return (not self.pos and sexta > max(self.ultima, self.criado) and t - sexta < JANELA_VENDA)

    def _comecar(self, mk, t, S):
        if self.curva is None:
            self.curva = Curva(inicio=t)
            self.curva.marcar(t, self.caixa + self.q * S)

    def _filtro_caro(self, mk, t, ev):
        """Prêmio caro: True se pode vender. Grava a decisão (`self.filtro`) e o evento."""
        iv, rv = mk.implicita(self.moeda, t), mk.realizada(self.moeda, t, VRP_DIAS)
        rv7 = mk.realizada(self.moeda, t, VRP_DIAS_CURTO)
        if not iv or not rv:
            self.filtro = {"em": int(t), "iv": iv, "rv": rv, "rv7": rv7, "razao": None, "vendeu": True}
            self.acc["semanasCaro"] += 1
            return True, "Sem a volatilidade realizada (poucas velas): vende como a versão sem filtro. "
        razao = iv / rv
        caro = razao >= VRP_MIN
        self.filtro = {"em": int(t), "iv": round(iv, 4), "rv": round(rv, 4), "rv7": round(rv7, 4) if rv7 else None,
                       "razao": round(razao, 3), "vendeu": caro}
        txt = (f"implícita {pct_br(iv, 0)} × realizada de {VRP_DIAS} dias {pct_br(rv, 0)} "
               f"(razão {num_br(razao, 2)}, mínimo {num_br(VRP_MIN, 1)})")
        if caro:
            self.acc["semanasCaro"] += 1
            return True, f"Prêmio caro, {txt}. "
        self.acc["semanasFora"] += 1
        self.ultima = sexta_08(t)
        self._ev(ev, t, "aviso", f"Ficou de fora esta semana: {txt}. O dólar continua rendendo na Aave.", "barato")
        return False, ""

    def _vender(self, mk, t, ev):
        S = mk.preco(self.moeda, t)
        if not S:
            return
        self._comecar(mk, t, S)
        if self.caixa_aave:
            self._para_aave(mk, t, ev)
        extra_txt, motivo = "", None
        if self.vrp:
            pode, extra_txt = self._filtro_caro(mk, t, ev)
            if not pode:
                return
            motivo = "caro" if (self.filtro or {}).get("razao") is not None else "semDados"
        vendeu = []
        if self.tipo == "roda":
            if self.fase == "call" and self.q > 1e-12:
                vendeu.append(self._vender_uma(mk, t, "call", self.q, ev))
            else:
                self.fase = "put"
                vendeu.append(self._vender_uma(mk, t, "put", max(0.0, self.caixa), ev))
        else:
            frac = {"put": 0.0, "call": 1.0, "strangle": 0.5}[self.tipo]
            self._ajustar_moeda(mk, t, frac, ev)
            v = self.caixa + self.q * S
            if self.tipo in ("put", "strangle"):
                vendeu.append(self._vender_uma(mk, t, "put", v * (1 - frac), ev, extra_txt, motivo))
            if self.tipo in ("call", "strangle"):
                vendeu.append(self._vender_uma(mk, t, "call", self.q, ev))
        if any(vendeu):
            self.ultima = sexta_08(t)

    def _passo_regua(self, mk, t, ev):
        """As réguas começam na mesma 1ª sexta que as outras e depois só seguram (a moeda ou o dólar na Aave)."""
        if self.curva is not None:
            return
        sexta = sexta_08(t)
        if not (sexta > self.criado and t - sexta < JANELA_VENDA):
            return
        S = mk.preco(self.moeda, t)
        if not S:
            return
        self._comecar(mk, t, S)
        if self.regua == "moeda":
            self._ajustar_moeda(mk, t, 1.0, ev, para="segurar (a régua)")
        else:
            self._para_aave(mk, t, ev)
        self.ultima = sexta

    def passo(self, mk, t, ev=None):
        """Um instante `t`: juros da Aave, vencimentos, recompra, venda de sexta e a marcação."""
        S = mk.preco(self.moeda, t)
        self._juros(mk, t)
        if self.regua:
            self._passo_regua(mk, t, ev)
        else:
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

    # ------------------------------------------------------------------ números para o app
    def semanas(self):
        """[(vencimento, resultado das opções do vencimento, prêmio líquido)] por vencimento (o strangle junta as duas)."""
        por = {}
        for venc, res, prem in self.fech:
            a = por.setdefault(int(venc), [0.0, 0.0])
            a[0] += res
            a[1] += prem
        return [(v, r, p) for v, (r, p) in sorted(por.items())]

    def premio_semana(self):
        """O prêmio líquido (menos a taxa) médio por vencimento fechado (US$); None sem nenhum."""
        s = self.semanas()
        return sum(p for _, _, p in s) / len(s) if s else None

    def pior_semana(self):
        s = self.semanas()
        if not s:
            return None
        venc, res, _ = min(s, key=lambda x: x[1])
        med = self.premio_semana()
        perda = max(0.0, -res)
        return {"de": dia_de(venc - 7 * DIA if self.prazo == "semana" else venc - 30 * DIA), "vence": dia_de(venc),
                "perda": _r(perda, 2), "resultado": _r(res, 2),
                "semanasDePremio": round(perda / med, 1) if med and med > 0 else None,
                "premioMedio": _r(med, 2) if med is not None else None, "semanas": len(s)}

    def por_dentro(self, mk, t):
        """De onde veio o resultado (US$): resultado = prêmios − pagos − recompras − custos (taxas + entrega + aave) +
        juros + emAberto (o que custaria recomprar as opções abertas, negativo) + preço (o que sobra: a moeda que a
        conta segura)."""
        a = self.acc
        resultado = self.valor(mk, t) - CAPITAL
        taxas = a["txOp"] + a["txSpot"]
        custos = taxas + a["txEnt"] + a["aave"]
        aberto = 0.0
        for op in self.pos:
            mc = mk.marca(op, t)
            aberto -= (mc[0] if mc else op.get("ult", op["premio"])) * op["q"]
        conhecido = a["premios"] - a["pagosVenc"] - a["recCusto"] - custos + a["juros"] + aberto
        return {"premios": _r(a["premios"]), "pagos": _r(a["pagosVenc"]), "recompras": _r(a["recCusto"]),
                "taxas": _r(taxas), "entrega": _r(a["txEnt"]), "aave": _r(a["aave"]), "juros": _r(a["juros"]),
                "custos": _r(custos), "emAberto": _r(aberto), "preco": _r(resultado - conhecido),
                "resultado": _r(resultado)}

    def empate(self, mk, t):
        """Custos (taxas, entrega, à vista, Aave) × o prêmio médio por semana: `semanas` de prêmio que pagam os custos;
        `sobra` = o que os prêmios (e os juros) deixaram, pagos o que venceu dentro, as recompras e os custos (fora o
        preço da moeda); `semanasParaRecuperar` quando a sobra é negativa."""
        if self.regua:
            return None
        a = self.acc
        custos = a["txOp"] + a["txSpot"] + a["txEnt"] + a["aave"]
        med = self.premio_semana()
        sobra = a["premios"] + a["juros"] - a["pagosVenc"] - a["recCusto"] - custos
        bom = med is not None and med > 0
        return {"custos": _r(custos, 2), "premioSemana": _r(med, 2) if med is not None else None,
                "semanas": round(custos / med, 1) if bom else None, "sobra": _r(sobra, 2), "jaPagou": sobra >= 0,
                "semanasParaRecuperar": round(-sobra / med, 1) if bom and sobra < 0 else (0.0 if sobra >= 0 else None)}

    def _extra(self, mk, t):
        a = self.acc
        aberta = None
        if self.pos:
            op = self.pos[0]
            aberta = f"{'Put' if op['tipo'] == 'put' else 'Call'} {num_br(op['K'], 0)} · vence {_ddmm(op['venc'])}"
            if len(self.pos) > 1:
                aberta += f" (+{len(self.pos) - 1})"
        S = mk.preco(self.moeda, t) or self.ultimo_s or 0
        x = {"premios": round(a["premios"], 4), "pagos": round(a["pagos"], 4), "vendas": int(a["vendas"]),
             "dentro": int(a["dentro"]), "semValor": int(a["fora"]), "recompras": int(a["recompras"]),
             "emAberto": aberta, "naMoeda": round(self.q * S, 2), "moeda": self.moeda,
             "porDentro": self.por_dentro(mk, t)}
        if self.regua:
            x = {"naMoeda": round(self.q * S, 2), "moeda": self.moeda, "porDentro": x["porDentro"]}
            if self.regua == "usdc":
                x["naMoeda"], x["moeda"] = 0.0, "USDC"
        else:
            emp = self.empate(mk, t)
            if emp:
                x["empate"] = emp
            ps = self.pior_semana()
            if ps:
                x["piorSemana"] = ps
        if self.caixa_aave:
            x["naAave"] = round(self.caixa, 2) if self.na_aave else 0.0
            x["juros"] = round(a["juros"], 4)
            x["juroAgora"] = round(mk.juro(t), 5)
        if self.tipo == "roda":
            x["fase"] = self.fase
            x["exercidas"] = int(a["exercidas"])
            x["chamadas"] = int(a["chamadas"])
        if self.vrp:
            x["filtro"] = {"vendeu": int(a["semanasCaro"]), "fora": int(a["semanasFora"]), "minimo": VRP_MIN,
                           "dias": VRP_DIAS, "ultima": self.filtro}
        self.curva.extra = x


# ---------------------------------------------------------------------------------------------------- estresse
def estresse(cfg, conta, mk, t, premio_semana=None, premio_fonte=None):
    """O teste de estresse de uma versão (ver o começo do arquivo e o FORMATO.md): a conta reavaliada depois de um
    fim de semana com o preço `ESTRESSE_CHOQUES` e a volatilidade × `ESTRESSE_VOL`. Sobre as posições abertas agora
    (`base` "agora"); sem elas, as que a versão venderia agora pela cadeia (`base` "teorica", com US$ 1.000). As quedas
    sempre; as altas só nas versões que seguram a moeda ou vendem call. Réguas: None."""
    vid, moeda, tipo = cfg[0], cfg[2], cfg[3]
    if tipo == "regua":
        return None
    S = mk.preco(moeda, t)
    if not S:
        return None
    base = "agora"
    c = conta
    if c is None or (not c.pos and c.q <= 1e-12):
        c = Conta(cfg)
        c.vrp = False
        c.caixa_aave = False
        c.criado = 0
        c._vender(mk, t, None)
        c.curva = None
        base = "teorica"
        if not c.pos:
            return None
    antes = c.valor(mk, t)
    if antes <= 0:
        return None
    tem_call = c.q > 1e-12 or any(o["tipo"] == "call" for o in c.pos)
    vol0 = mk.implicita(moeda, t) or 0.5
    choques = []
    for x in ESTRESSE_CHOQUES:
        if x > 0 and not tem_call:
            continue
        S2 = S * (1 + x)
        k = ESTRESSE_VOL["queda" if x < 0 else "alta"]
        t2 = t + ESTRESSE_DIAS * DIA
        v = c.caixa + c.q * S2
        for op in c.pos:
            T = max(0.0, (op["venc"] - t2) / ANO_MS)
            iv = (op.get("iv") or vol0) * k
            v -= bs(S2, op["K"], T, iv, op["tipo"]) * op["q"]
        perda = antes - v
        choques.append({"variacao": x, "perda": _r(perda, 2), "perdaPct": round(perda / antes, 4),
                        "semanasDePremio": round(perda / premio_semana, 1) if premio_semana and premio_semana > 0 and perda > 0 else None})
    return {"base": base, "preco": round(S, 2), "valor": round(antes, 2), "dias": ESTRESSE_DIAS,
            "vol": dict(ESTRESSE_VOL), "posicoes": [{"tipo": o["tipo"], "strike": o["K"], "vence": o["venc"],
                                                     "q": round(o["q"], 6)} for o in c.pos],
            "naMoeda": round(c.q * S, 2), "premioSemana": _r(premio_semana, 2) if premio_semana else None,
            "premioFonte": premio_fonte, "choques": choques}


# ---------------------------------------------------------------------------------------------------- janelas
def janelas(h, contra, cdi, cdi_ano, regua):
    """As janelas de 30 dias a cada 7 do teste no passado (as do looping.py), contra a régua certa. Sem a série da régua,
    contra o CDI."""
    if LP is None or not h:
        return None
    if contra != "cdi" and not regua:
        contra = "cdi"
    j = LP.janelas(h, contra, cdi, cdi_ano, regua=regua, dias=JANELA_DIAS, passo=JANELA_PASSO)
    if j:
        j["contra"] = {"id": contra, "nome": NOMES_REGUA.get(contra, contra)}
    return j


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


NOTA_HIST = ("Aproximado: preços pela fórmula de Black-Scholes com o índice de volatilidade da Deribit (DVOL) ajustado "
             "pelo sorriso e vendidos pela oferta de compra estimada, não os da cadeia da época; vende às sextas 08h UTC.")


def teste_no_passado(mh, ini, fim, versoes=None):
    out, contas = {}, {}
    for cfg in versoes or VERSOES:
        c = Conta(cfg)
        c.criado = ini
        for t in horas(ini, fim):
            if mh.preco(cfg[2], t):
                c.passo(mh, t)
        nota = NOTA_HIST
        if c.caixa_aave and mh.aave is None:
            nota += " Sem o juro da Aave nesta rodada: a garantia rendeu 0."
        out[cfg[0]] = c.curva.resumo(de=dia_de(c.curva.inicio), ate=dia_de(fim), aproximado=True, nota=nota) if c.curva else None
        contas[cfg[0]] = c
    return out, contas


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
        # o juro do dólar (Aave), o DVOL de agora e os preços de 31 dias (a volatilidade realizada)
        aave_g = FD.ler_aave(ctx, est, log, erros) if FD else {}
        aave = FD.taxas_aave(aave_g) if FD else None
        dvol_agora = {}
        for m in cadeias:
            d = ler_dvol(fonte, m, agora - 6 * HORA, agora, log, erros)
            if d:
                dvol_agora[m] = d[max(d)]
        precos_vivo = {m: velas_1h(ctx.cli, m, agora - (VRP_DIAS + 1) * DIA, agora, erros) for m in cadeias}
        mk = MercadoVivo(cadeias, indices, entregas, dvol=dvol_agora, precos=precos_vivo, aave=aave)

        # ---------------------------------------------------------------- o sorriso e o spread da cadeia de agora
        med = est.setdefault("sorriso", {})
        for m in cadeias:
            s = medir_sorriso(mk, m, agora, dvol_agora.get(m))
            if s:
                med.setdefault(m, []).append(s)
                med[m] = med[m][-SORRISO_RODADAS:]
        sorriso = {m: resumo_sorriso(med.get(m)) for m in MOEDAS}

        # ---------------------------------------------------------------- ao vivo
        vivo = est.setdefault("vivo", {})
        ev = Eventos(est.get("eventos"))
        sem_dados = {}
        for cfg in VERSOES:
            vid = cfg[0]
            if OPCOES.get(vid, {}).get("regua") == "usdc" and aave is None:
                sem_dados[vid] = "Sem o juro do dólar na Aave: a fonte (GraphQL do Aave) não respondeu."
                continue
            if cfg[2] not in cadeias:
                continue
            c = Conta(cfg, vivo.get(vid))
            if not c.criado:
                c.criado = agora
                prox = sexta_08(agora) + 7 * DIA
                ev.add(agora, "aviso", f"Começou a esperar a 1ª sexta ({_ddmm(prox)}) para "
                                       f"{'começar' if c.regua else 'vender a primeira opção'}.", vid)
            try:
                c.passo(mk, agora, ev)
                vivo[vid] = c.para_json()
            except Exception as e:  # noqa: BLE001 (uma versão com problema não derruba as outras)
                erros.append(f"{vid} ao vivo: {e}")
                log(f"  opções: {vid} ao vivo: {e}")

        # ---------------------------------------------------------------- teste no passado
        hist = est.get("hist") or {}
        refazer = not hist or agora - int(hist.get("em") or 0) >= HIST_REFAZER or hist.get("hv") != HIST_V
        if refazer and ctx.restante() < HIST_TEMPO_MIN:
            log(f"  opções: pouco tempo na rodada ({ctx.restante():.0f} s); o teste no passado fica para a próxima")
            refazer = False
        if refazer:
            fim = (agora // HORA) * HORA
            ini = fim - HIST_DIAS * DIA
            precos = {m: velas_1h(ctx.cli, m, ini - (VRP_DIAS + 2) * DIA, agora, erros) for m in MOEDAS}
            dvol = {m: ler_dvol(fonte, m, ini, agora, log, erros) for m in MOEDAS}
            fonte_iv = "dvol" if all(dvol.values()) else "realizada"
            if any(precos.values()):
                primeira = max(min(p) for p in precos.values() if p)
                t0 = max(ini, primeira + 25 * DIA if fonte_iv == "realizada" else primeira)
                versoes_h = [c for c in VERSOES if c[0] not in sem_dados]
                res, _ = teste_no_passado(MercadoHist(precos, dvol, sorriso={m: s for m, s in sorriso.items() if s},
                                                      aave=aave), t0, fim, versoes_h)
                hist = {"v": VERSAO, "hv": HIST_V, "em": agora, "de": t0, "ate": fim, "versoes": res, "iv": fonte_iv,
                        "sorriso": "cadeia" if any(sorriso.values()) else "padrao"}
                est["hist"] = hist
                log(f"  opções: teste no passado refeito ({dia_de(t0)} a {dia_de(fim)}, volatilidade: {fonte_iv}, "
                    f"sorriso: {hist['sorriso']})")

        # ---------------------------------------------------------------- saída
        cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}
        cdi_ano = CT.cdi_ano_da_serie(cdi, 0.149)
        hv = hist.get("versoes") or {}
        versoes, itens, comeca = [], [], None
        for cfg in VERSOES:
            vid, nome, moeda, tipo, alvo, prazo, stop, risco, frase = cfg
            e = vivo.get(vid) or {}
            curva = Curva.de_json(e.get("curva")) if e.get("curva") else None
            if curva is None and e.get("criado"):
                p = sexta_08(int(e["criado"])) + 7 * DIA
                comeca = min(comeca or p, p)
            h = hv.get(vid)
            contra = contra_de(cfg)
            if h is not None:
                h = dict(h)
                try:
                    h["janelas"] = janelas(h, contra, cdi, cdi_ano, dict((hv.get(contra) or {}).get("serie") or []))
                except (TypeError, ValueError, ZeroDivisionError, OverflowError, KeyError):
                    h["janelas"] = None
            v = {"id": vid, "nome": nome, "frase": frase, "risco": risco, "alav": 1, "grupo": GRUPO.get(vid, moeda),
                 "moeda": moeda, "contra": contra if tipo != "regua" else "cdi",
                 "aoVivo": curva.resumo() if curva else None, "historico": h}
            if sem_dados.get(vid):
                v["semDados"] = sem_dados[vid]
            # o estresse: as posições de agora ou as que a versão venderia agora; o prêmio médio do passado
            try:
                c = Conta(cfg, e) if e.get("curva") else None
                ph = ((h or {}).get("extra") or {}).get("piorSemana") or {}
                pv = (((curva.resumo() if curva else {}) or {}).get("extra") or {}).get("piorSemana") or {}
                prem, fonte_p = (ph.get("premioMedio"), "passado") if ph.get("premioMedio") else (pv.get("premioMedio"), "aoVivo")
                if moeda in cadeias:
                    es = estresse(cfg, c, mk, agora, prem, fonte_p if prem else None)
                    if es:
                        v["estresse"] = es
            except (TypeError, ValueError, ZeroDivisionError, KeyError) as x:
                erros.append(f"{vid} estresse: {x}")
            versoes.append(v)
            for op in e.get("pos") or []:
                itens.append({"versao": vid, "instrumento": op["inst"], "moeda": op["moeda"], "tipo": op["tipo"],
                              "strike": op["K"], "vence": op["venc"], "delta": op.get("delta"),
                              "premio": round(op["premio"] * op["q"], 4), "marca": round(op.get("ult", op["premio"]) * op["q"], 4),
                              "vendidaEm": op.get("em")})
        est["eventos"] = ev.para_json()
        ctx.est.clear()
        ctx.est.update(est)
        vrp_agora = {}
        for m in cadeias:
            iv, rv, rv7 = mk.implicita(m, agora), mk.realizada(m, agora, VRP_DIAS), mk.realizada(m, agora, VRP_DIAS_CURTO)
            vrp_agora[m] = {"iv": round(iv, 4) if iv else None, "rv": round(rv, 4) if rv else None,
                            "rv7": round(rv7, 4) if rv7 else None,
                            "razao": round(iv / rv, 3) if iv and rv else None,
                            "caro": (iv / rv >= VRP_MIN) if iv and rv else None,
                            "fonteIv": "dvol" if dvol_agora.get(m) else "atm"}
        cfg_saida = {"frequencia": "a cada 6 h (vende às sextas, depois das 08h UTC)", "moedas": MOEDAS,
                     "fonte": "Deribit (pública)", "precos": {m: round(p, 2) for m, p in mk.indices.items()},
                     "taxas": {"opcao": TAXA_OPCAO, "entrega": TAXA_ENTREGA, "teto": TETO_TAXA, "spot": TAXA_SPOT,
                               "deslizeSpot": DESLIZE_SPOT},
                     "ivHistorico": hist.get("iv"), "deltaAlvo": {c[0]: c[4] for c in VERSOES if c[4] is not None},
                     "sorriso": {m: (sorriso.get(m) or sorriso_padrao()) for m in MOEDAS},
                     "sorrisoHistorico": hist.get("sorriso"),
                     "vrp": {"minimo": VRP_MIN, "dias": VRP_DIAS, "diasCurto": VRP_DIAS_CURTO, "agora": vrp_agora},
                     "caixa": {"ida": CAIXA_IDA, "volta": CAIXA_VOLTA, "ponte": 0.0,
                               "juroAgora": round(mk.juro(agora), 5) if aave is not None else None},
                     "estresse": {"choques": list(ESTRESSE_CHOQUES), "vol": dict(ESTRESSE_VOL), "dias": ESTRESSE_DIAS},
                     "janelas": {"dias": JANELA_DIAS, "passo": JANELA_PASSO}}
        if comeca:
            cfg_saida["aoVivoComeca"] = comeca
        return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": "put15", "versoes": versoes,
                "eventos": est["eventos"], "itens": sorted(itens, key=lambda x: x["vence"]), "avisos": AVISOS,
                "config": cfg_saida, "erros": erros}
    finally:
        rede.somar_pedidos(ctx, fonte, p0)
