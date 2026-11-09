"""Pools de liquidez concentrada (Uniswap v3, WETH/USDC 0,05% na Base), NO PAPEL (plano: docs/plano-testes-mercado-2.md,
seção 3; formato: tools/papel/FORMATO.md). Nenhuma carteira, nenhuma ordem, nenhuma chave: só o RPC público da Base.

A ideia: emprestar as duas moedas (ether e dólar) para quem troca uma pela outra no pool e ganhar a taxa de 0,05% de
cada troca. Numa faixa de preço estreita a mesma quantia rende mais taxa, mas quando o preço sai da faixa a posição para
de ganhar e fica toda na moeda que caiu (a perda impermanente). Reposicionar (tirar, trocar e pôr de novo em volta do
preço novo) custa a troca e o gás e "realiza" a perda.

Fonte: CADA TROCA do pool, pelos eventos `Swap` no RPC público `base-rpc.publicnode.com` (o `mainnet.base.org` dá 429 no
getLogs). Cada evento traz o preço depois da troca (`sqrtPriceX96`), a liquidez ativa e o tick. Como só as trocas mexem
no preço, o caminho do preço entre uma troca e a seguinte é conhecido, e a taxa da nossa posição sai EXATA pela
matemática do v3: numa subida de √P de a até b dentro da faixa, entra L·(b − a) de USDC; numa descida, L·(1/a − 1/b) de
WETH; a taxa é esse valor × 0,05% ÷ (1 − 0,05%), na moeda que entrou. Não depende da liquidez dos outros (a nossa é
pequena demais para mexer no preço). O valor da posição a cada preço é o do v3 (perda impermanente exata). As faixas são
arredondadas aos ticks do pool (espaço 10). Gás medido a cada rodada (`eth_gasPrice`) × `GAS_UNIDADES` + uma estimativa
fixa da taxa de dados da L1 (`L1_US`).

Limites do publicnode (Teste de alcance, 03/11/2026): no máximo 20.000 eventos por pedido (~1.100 trocas por hora: o
pedaço começa em 10 mil blocos, ~5,5 h, e se ajusta: erro → metade; poucos eventos → dobra até 40 mil) e nada além de
~30 dias para trás ("Archive requests require a personal token"). Por isso o "teste no passado" são os 28 dias antes
do começo e depois anda junto com o ao vivo (as mesmas trocas); na 1ª vez leva vários minutos e, se o prazo da rodada
acabar, continua na rodada seguinte. Um pedido a cada `rede.INTERVALO["base"]` s.

Tempo: a Base faz um bloco a cada 2 s, exatos; a hora de um bloco = a do bloco de referência da rodada (`latest`) ±
2 s por bloco.

Amostras conferidas (Teste de alcance): `eth_getLogs` do pool com o tópico do Swap (258 eventos em 500 blocos; 4.766 em
10.000; há 30 dias: sim; há 365: recusado). NÃO conferidos (a 1ª rodada de verdade registra no log): o formato de cada
evento (o código segue o ABI do UniswapV3Pool: `Swap(address indexed sender, address indexed recipient, int256 amount0,
int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)`), o token0 (conferido por `token0()` a cada
semana), a mensagem do erro de "resultados demais" e o GeckoTerminal da conferência do volume.
"""
from __future__ import annotations

import copy
import math

import rede
from conta import CAPITAL, DIA, FUSO_MS, HORA, Curva, Eventos, dia_de, moeda_br, num_br

try:
    import hl
    ERROS = (rede.Erro, hl.Erro)
except ImportError:  # pragma: no cover
    ERROS = (rede.Erro,)

NOME = "Pools"
VERSAO = 1

POOL = "0xd0b53D9277642d899DF5C87A3966A349A798F224"  # Uniswap v3 WETH/USDC 0,05% na Base (Teste de alcance)
WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TOPICO_SWAP = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
SEL_TOKEN0, SEL_FEE = "0x0dfe1681", "0xddca3f43"
DEC0, DEC1 = 18, 6                     # WETH e USDC
ESCALA = 10 ** ((DEC0 - DEC1) / 2)     # √P em USDC por WETH = √P cru × 10^6
Q96 = 2 ** 96
TAXA_POOL = 0.0005
ESPACO_TICK = 10
TICK_MIN, TICK_MAX = -887270, 887270
BASE_TICK = math.log(1.0001)
DESLIZE = 0.0001                       # a nossa troca de reposicionamento, num pool de dezenas de milhões
GAS_UNIDADES = 700_000                 # tirar a liquidez + coletar, trocar e pôr de novo (3 transações)
GAS_PADRAO = 10_000_000                # wei por unidade de gás (0,01 gwei), se a rodada não conseguir medir
L1_US = 0.01                           # a taxa de dados da L1 nas 3 transações (estimativa fixa)
BLOCO_MS = 2000
BLOCOS_DIA = DIA // BLOCO_MS
CONFIRMACOES = 10                      # não lê os últimos 10 blocos (20 s)
HIST_DIAS = 28                         # o publicnode recusa mais de ~30 dias para trás
PEDACO_INI, PEDACO_MIN, PEDACO_MAX = 10_000, 250, 40_000
MAX_EVENTOS_PEDIDO = 20_000
RESERVA_S = 90                         # segundos que precisam sobrar na rodada para buscar mais um pedaço
MARCA_MS = 10 * 60_000                 # a curva é marcada no máximo a cada 10 min (e no fim de cada pedaço)
FORA_ESPERA = HORA
GAS_GUARDAR = 60
INICIO_BLOCOS = 300                    # o ao vivo começa ~10 min antes da 1ª rodada (para pôr no preço de agora)
VOL_HORAS = 48
HORA_CONFERIR = 12                     # "dia": a hora (Brasília) em que a pessoa olha a pool
REINVESTIR_DIAS = 7                    # "dia": a cada quantos dias põe as taxas de volta
GAS_REINVESTIR = 0.6                   # coletar + aumentar a liquidez: ~60% do gás de um reposicionamento
PARAMS_REFAZER = 7 * DIA

# (id, nome, largura da faixa (fração, None = cheia), regra, risco, frase)
#   regra: "sai" = reposiciona assim que o preço sai; "hora" = depois de 1 h fora; "nunca"; "segurar" = sem pool;
#   "dia" = o jeito de quem cuida da pool à mão (ensinado em canais brasileiros de pools, como o do Marinho, com o
#   Revert ou o Krystal): confere uma vez por dia (`HORA_CONFERIR`, Brasília), só reposiciona se estiver fora nessa hora e
#   toda semana põe as taxas ganhas de volta na posição, na mesma faixa (`REINVESTIR_DIAS`)
VERSOES = [
    ("r1", "±1% · ao sair", 0.01, "sai", "alto",
     "Faixa de 1% para cada lado do preço; quando o preço sai, tira, troca e põe de novo em volta do preço novo."),
    ("r1h", "±1% · 1 h fora", 0.01, "hora", "alto",
     "A mesma faixa de 1%, mas só reposiciona depois de 1 hora fora (para não pagar à toa no vai e vem)."),
    ("r3", "±3% · ao sair", 0.03, "sai", "médio",
     "Faixa de 3% para cada lado; reposiciona assim que o preço sai."),
    ("r3h", "±3% · 1 h fora", 0.03, "hora", "médio",
     "Faixa de 3% para cada lado; reposiciona depois de 1 hora fora."),
    ("r10h", "±10% · 1 h fora", 0.10, "hora", "médio",
     "Faixa larga, de 10% para cada lado: ganha menos por dólar e sai pouco; reposiciona depois de 1 hora fora."),
    ("dia10", "±10% · 1×/dia · reinveste", 0.10, "dia", "médio",
     "Como quem cuida da pool à mão: faixa de 10% para cada lado, olha uma vez por dia (meio-dia) e só reposiciona se "
     "estiver fora; toda semana põe as taxas ganhas de volta na posição."),
    ("dia5", "±5% · 1×/dia · reinveste", 0.05, "dia", "médio",
     "O mesmo cuidado à mão (uma olhada por dia, taxas de volta toda semana) com uma faixa de 5% para cada lado."),
    ("cheia", "Faixa cheia", None, "nunca", "médio",
     "A faixa inteira, como nos pools antigos (v2): nunca sai, ganha bem menos por dólar e não precisa reposicionar."),
    ("r3fixa", "±3% sem reposicionar", 0.03, "nunca", "médio",
     "Faixa de 3% posta uma vez e deixada: quando o preço sai, para de ganhar e espera ele voltar."),
    ("segurar", "Segurar 50/50", None, "segurar", "médio",
     "Referência sem pool: metade em ether e metade em dólar, parados. Mostra quanto do resultado é só o ether."),
]
FRASE = ("Empresta ether e dólar para quem troca um pelo outro e ganha 0,05% de cada troca; numa faixa estreita ganha "
         "mais, mas quando o preço sai dela para de ganhar e fica na moeda que caiu.")
COMO_FUNCIONA = [
    "No Uniswap da rede Base, quem troca ether por dólar paga 0,05% da troca para quem pôs as duas moedas no pool. A "
    "posição escolhe uma faixa de preço: só ganha enquanto o preço está dentro dela, e quanto mais estreita, mais taxa "
    "por dólar.",
    "Quando o preço sobe, a posição vai vendendo ether; quando cai, vai comprando. Saindo da faixa, fica toda na moeda "
    "que perdeu valor: a diferença para quem só segurou as duas moedas é a perda impermanente.",
    "Reposicionar é tirar a posição, trocar para a proporção certa e pôr de novo em volta do preço novo: custa a taxa da "
    "troca e o gás das transações, e torna a perda definitiva. Algumas versões reposicionam na hora, outras esperam 1 "
    "hora fora, uma nunca reposiciona.",
    "O papel usa cada troca de verdade do pool WETH/USDC 0,05% (lidas na rede Base): a taxa e o valor da posição saem "
    "exatos pela matemática do Uniswap, e o gás é medido a cada rodada.",
]
AVISOS = [
    "Robôs de liquidez relâmpago entram só no bloco de uma troca grande e levam boa parte da taxa dela; o papel conta a "
    "taxa como se só existissem as posições paradas.",
    "Boa parte das trocas vem de arbitradores, que trocam quando o preço do pool está atrasado em relação às corretoras: "
    "a posição ganha a taxa, mas troca no preço velho (o papel mostra isso no resultado, não em separado).",
    "O papel reposiciona exatamente na troca em que a regra manda; um robô de verdade chega alguns blocos depois.",
    "Erro no contrato, um problema na ponte da Base ou o dólar (USDC) descolar podem levar o dinheiro; nada disso aparece "
    "no papel.",
    "O teste no passado só vai até uns 28 dias antes do começo: o RPC gratuito não guarda mais que isso.",
    "Pôr dinheiro na Base exige carteira própria, ponte e um pouco de ether para o gás; o papel começa com o dinheiro já "
    "lá.",
]


# ---------------------------------------------------------------------------------------------------- matemática do v3
def preco_de(s):
    """√P (USDC por WETH) → P."""
    return s * s


def s_do_tick(tick):
    return math.exp(tick * BASE_TICK / 2) * ESCALA


def tick_do_s(s):
    return math.log((s / ESCALA) ** 2) / BASE_TICK


def faixa(s, largura):
    """(√Pa, √Pb) arredondados aos ticks do pool: P × (1 − largura) para baixo e P × (1 + largura) para cima."""
    if largura is None:
        return s_do_tick(TICK_MIN), s_do_tick(TICK_MAX)
    P = preco_de(s)
    ta = math.floor(tick_do_s(math.sqrt(P * (1 - largura))) / ESPACO_TICK) * ESPACO_TICK
    tb = math.ceil(tick_do_s(math.sqrt(P * (1 + largura))) / ESPACO_TICK) * ESPACO_TICK
    return s_do_tick(max(TICK_MIN, ta)), s_do_tick(min(TICK_MAX, tb))


def quantias(L, s, sa, sb):
    """(WETH, USDC) de uma posição de liquidez L na faixa [√Pa, √Pb] com o preço em √P = s."""
    if s <= sa:
        return L * (1 / sa - 1 / sb), 0.0
    if s >= sb:
        return 0.0, L * (sb - sa)
    return L * (1 / s - 1 / sb), L * (s - sa)


def taxa_no_trecho(L, s0, s1, sa, sb, taxa=TAXA_POOL):
    """A taxa (WETH, USDC) que a liquidez L na faixa ganha quando o preço anda de √P = s0 a s1 (uma troca)."""
    lo, hi = (s0, s1) if s0 < s1 else (s1, s0)
    a, b = max(lo, sa), min(hi, sb)
    if a >= b or L <= 0:
        return 0.0, 0.0
    k = taxa / (1 - taxa)
    if s1 < s0:  # preço caiu: entrou WETH
        return L * (1 / a - 1 / b) * k, 0.0
    return 0.0, L * (b - a) * k


def ler_evento(log, ref_bloco, ref_ms):
    """Um evento Swap → (t ms, bloco, índice, √P em USDC por WETH, liquidez ativa crua, volume em US$) ou None."""
    try:
        d = log["data"][2:]
        if len(d) < 320:
            return None
        w = [int(d[i:i + 64], 16) for i in range(0, 320, 64)]
        a1 = w[1] - (1 << 256) if w[1] >= 1 << 255 else w[1]
        b = int(log["blockNumber"], 16)
        i = int(log.get("logIndex") or "0x0", 16)
        s = w[2] / Q96 * ESCALA
        if s <= 0:
            return None
        return ref_ms + (b - ref_bloco) * BLOCO_MS, b, i, s, w[3], abs(a1) / 10 ** DEC1
    except (KeyError, TypeError, ValueError):
        return None


def custo_gas(gas_wei, P):
    return gas_wei * GAS_UNIDADES / 1e18 * P + L1_US


# ---------------------------------------------------------------------------------------------------- conta
class Conta:
    """Uma versão: liquidez `L` na faixa [`sa`, `sb`] (√P), as taxas ainda não coletadas (`fx` WETH, `fy` USDC) e, na
    referência, `x`/`y` parados."""

    def __init__(self, cfg, inicio, estado=None):
        self.id, self.nome, self.largura, self.regra, self.risco, self.frase = cfg
        e = estado or {}
        self.curva = Curva.de_json(e.get("curva")) or Curva(inicio=inicio)
        self.L, self.sa, self.sb = float(e.get("L", 0.0)), float(e.get("sa", 0.0)), float(e.get("sb", 0.0))
        self.fx, self.fy = float(e.get("fx", 0.0)), float(e.get("fy", 0.0))
        self.x, self.y = float(e.get("x", 0.0)), float(e.get("y", 0.0))
        self.dep = e.get("dep")          # [WETH, USDC] logo depois de pôr (para a perda impermanente)
        self.montada = bool(e.get("montada"))
        self.fora = e.get("fora")        # desde quando o preço está fora (ms) ou None
        self.t = int(e.get("t") or inicio)
        self.marca = int(e.get("marca") or 0)
        self.s = e.get("s")              # último √P visto
        a = e.get("acc") or {}
        self.acc = {k: float(a.get(k, 0.0)) for k in ("taxas", "gas", "repos", "pi", "dentro", "total", "diaRepos")}
        self.dia = e.get("dia")          # o dia (índice, Brasília) da última troca, para o resumo dos reposicionamentos
        self.aviso_fora = bool(e.get("avisoFora"))
        self.olhou = e.get("olhou")      # "dia": o último dia (índice, Brasília) em que conferiu
        self.reinvestiu = e.get("reinvestiu")  # "dia": o dia da última vez que pôs as taxas de volta
        self.acc.setdefault("reinv", float(a.get("reinv", 0.0)))

    def para_json(self):
        return {"curva": self.curva.para_json(), "L": self.L, "sa": self.sa, "sb": self.sb, "fx": self.fx, "fy": self.fy,
                "x": self.x, "y": self.y, "dep": self.dep, "montada": self.montada, "fora": self.fora, "t": self.t,
                "marca": self.marca, "s": self.s, "acc": self.acc, "dia": self.dia, "avisoFora": self.aviso_fora,
                "olhou": self.olhou, "reinvestiu": self.reinvestiu}

    def _ev(self, ev, t, tipo, texto):
        if ev is not None:
            ev.add(t, tipo, texto, self.id)

    def dentro(self, s):
        return self.sa <= s <= self.sb

    def tokens(self, s):
        """(WETH, USDC) da posição sem as taxas."""
        if self.regra == "segurar":
            return self.x, self.y
        return quantias(self.L, s, self.sa, self.sb)

    def valor(self, s):
        x, y = self.tokens(s)
        P = preco_de(s)
        return (x + self.fx) * P + y + self.fy

    def perda_imp(self, s):
        """A perda impermanente da posição de agora (US$, ≤ 0): o valor sem as taxas × segurar o que foi posto."""
        if not self.dep or self.regra == "segurar":
            return 0.0
        x, y = self.tokens(s)
        P = preco_de(s)
        return (x * P + y) - (self.dep[0] * P + self.dep[1])

    # ------------------------------------------------------------------ pôr e reposicionar
    def _por(self, s, X, Y, gas_wei):
        """Põe a posição em volta de √P = s com X WETH e Y USDC (as taxas já somadas), trocando o que precisa.
        Devolve o custo (troca + deslize + gás, em US$)."""
        P = preco_de(s)
        V = X * P + Y
        gas = custo_gas(gas_wei, P)
        c = TAXA_POOL + DESLIZE
        if self.regra == "segurar":
            alvo = (V - gas) / 2
            troca = abs(alvo - X * P)
            custo = gas + troca * c
            sobra = V - custo
            self.x, self.y = sobra / 2 / P, sobra / 2
            return custo
        self.sa, self.sb = faixa(s, self.largura)
        x1, y1 = quantias(1.0, s, self.sa, self.sb)
        u = x1 * P + y1
        # comprando WETH (X < L·x1) ou vendendo (X > L·x1): o custo da troca sai do que vai para a posição
        L = (V - gas + c * X * P) / (u + c * x1 * P)
        if X > L * x1:
            L = (V - gas - c * X * P) / (u - c * x1 * P)
        L = max(0.0, L)
        self.L = L
        self.fx = self.fy = 0.0
        x, y = quantias(L, s, self.sa, self.sb)
        self.dep = [x, y]
        return V - (x * P + y)

    def montar(self, t, s, gas_wei, ev):
        V = self.curva.ultimo if self.curva.ultimo > 0 else CAPITAL
        custo = self._por(s, 0.0, V, gas_wei)
        self.curva.operou(custo, 1)
        self.acc["gas"] += custo_gas(gas_wei, preco_de(s))
        self.montada = True
        P = preco_de(s)
        if self.regra == "segurar":
            self._ev(ev, t, "abriu", f"Comprou {num_br(self.x, 4)} ETH a {moeda_br(P, 0)} e guardou {moeda_br(self.y)} em dólar "
                                     f"(custou {moeda_br(custo)}).")
        elif self.largura is None:
            self._ev(ev, t, "abriu", f"Pôs {moeda_br(V - custo)} no pool na faixa cheia, com o ether a {moeda_br(P, 0)} "
                                     f"(custou {moeda_br(custo)}).")
        else:
            self._ev(ev, t, "abriu", f"Pôs {moeda_br(V - custo)} no pool na faixa de {moeda_br(preco_de(self.sa), 0)} a "
                                     f"{moeda_br(preco_de(self.sb), 0)} (custou {moeda_br(custo)}).")

    def reposicionar(self, t, s, gas_wei):
        P = preco_de(s)
        x, y = self.tokens(s)
        self.acc["pi"] += self.perda_imp(s)
        custo = self._por(s, x + self.fx, y + self.fy, gas_wei)
        self.curva.operou(custo, 1)
        self.acc["gas"] += custo_gas(gas_wei, P)
        self.acc["repos"] += 1
        self.acc["diaRepos"] += 1
        self.fora = None

    def reinvestir(self, t, s, gas_wei):
        """Põe as taxas não coletadas de volta na posição, na MESMA faixa (coleta, troca o que precisa e aumenta a
        liquidez). Não faz nada se as taxas não pagam pelo menos 5 vezes o gás."""
        P = preco_de(s)
        Vf = self.fx * P + self.fy
        gas = custo_gas(gas_wei, P) * GAS_REINVESTIR
        if Vf < 5 * gas:
            return False
        x1, y1 = quantias(1.0, s, self.sa, self.sb)
        u = x1 * P + y1
        if u <= 0:
            return False
        c = TAXA_POOL + DESLIZE
        L = (Vf - gas) / u
        L = max(0.0, (Vf - gas - c * abs(self.fx * P - L * x1 * P)) / u)
        x, y = quantias(L, s, self.sa, self.sb)
        self.L += L
        self.fx = self.fy = 0.0
        if self.dep:
            self.dep = [self.dep[0] + x, self.dep[1] + y]
        self.curva.operou(Vf - (x * P + y), 1)
        self.acc["gas"] += gas
        self.acc["reinv"] += 1
        return True

    def olhar(self, t, s, gas_wei, ev):
        """"dia": a olhada do dia (na 1ª troca depois de HORA_CONFERIR, Brasília)."""
        d = (t + FUSO_MS) // DIA
        if self.olhou == d or (t + FUSO_MS) % DIA < HORA_CONFERIR * HORA:
            return
        self.olhou = d
        if not self.dentro(s):
            self.reposicionar(t, s, gas_wei)
        if self.reinvestiu is None:
            self.reinvestiu = d
        elif d - self.reinvestiu >= REINVESTIR_DIAS:
            if self.reinvestir(t, s, gas_wei):
                self._ev(ev, t, "reequilibrou", f"Pôs de volta na posição as taxas da semana (até agora "
                                                f"{moeda_br(self.acc['taxas'])} ganhos no total).")
            self.reinvestiu = d

    # ------------------------------------------------------------------ cada troca
    def troca(self, t, s0, s1, gas_wei, ev=None):
        """O preço andou de √P = s0 (a troca anterior, ou None) para s1 no instante t."""
        if not self.montada:
            self.montar(t, s1, gas_wei, ev)
            if self.regra == "dia":
                self.olhou = (t + FUSO_MS) // DIA  # pôr a posição conta como a olhada do dia
            self.t, self.s, self.marca = t, s1, t
            self.curva.marcar(t, self.valor(s1))
            return
        dia = (t + FUSO_MS) // DIA
        if self.dia is not None and dia != self.dia:
            self._fechar_dia(t, ev)
        self.dia = dia
        if self.regra != "segurar":
            dt_ms = max(0, t - self.t)
            self.acc["total"] += dt_ms
            if self.s is not None and self.dentro(self.s):
                self.acc["dentro"] += dt_ms
            if s0 is not None:
                fx, fy = taxa_no_trecho(self.L, s0, s1, self.sa, self.sb)
                if fx or fy:
                    self.fx += fx
                    self.fy += fy
                    self.acc["taxas"] += fx * preco_de(s1) + fy
            if self.dentro(s1):
                self.fora = None
                if self.aviso_fora:
                    self.aviso_fora = False
                    if self.regra == "nunca":
                        self._ev(ev, t, "entrou", f"O ether voltou à faixa ({moeda_br(preco_de(s1), 0)}): voltou a ganhar a taxa.")
            else:
                if self.fora is None:
                    self.fora = t
                if self.regra == "sai" or (self.regra == "hora" and t - self.fora >= FORA_ESPERA):
                    self.reposicionar(t, s1, gas_wei)
                elif self.regra == "nunca" and self.largura is not None and not self.aviso_fora and t - self.fora >= FORA_ESPERA:
                    self.aviso_fora = True
                    lado = "acima" if s1 > self.sb else "abaixo"
                    moeda = "dólar" if s1 > self.sb else "ether"
                    self._ev(ev, t, "saiu", f"O ether ficou {lado} da faixa por 1 hora ({moeda_br(preco_de(s1), 0)}): a "
                                            f"posição parou de ganhar e está toda em {moeda}.")
            if self.regra == "dia":
                self.olhar(t, s1, gas_wei, ev)
        self.t, self.s = t, s1
        if t // MARCA_MS != self.marca // MARCA_MS:
            self.marcar(t)

    def marcar(self, t, agenda=True):
        """Marca a curva em `t`. As marcas de cada troca seguem a grade fixa de 10 min (`agenda`), para o resultado
        não depender de onde caem os pedaços de blocos de cada rodada."""
        if self.s is None:
            return
        if agenda:
            self.marca = t
        self.curva.marcar(t, self.valor(self.s))
        self._extra()

    def _fechar_dia(self, t, ev):
        n = int(self.acc["diaRepos"])
        if n and ev is not None:
            d = dia_de(t - 1)
            self._ev(ev, t - 1, "reequilibrou", f"Reposicionou {n} {'vez' if n == 1 else 'vezes'} em {d[8:10]}/{d[5:7]}: "
                                                f"já ganhou {moeda_br(self.acc['taxas'])} de taxa e a perda impermanente "
                                                f"realizada soma {moeda_br(self.acc['pi'])}.")
        self.acc["diaRepos"] = 0

    def _extra(self):
        s = self.s
        if s is None:
            return
        x, y = self.tokens(s)
        P = preco_de(s)
        tot = self.acc["total"]
        e = {"taxasGanhas": round(self.acc["taxas"], 4), "gasPago": round(self.acc["gas"], 4),
             "reposicoes": int(self.acc["repos"]), "precoEth": round(P, 2), "reinvestimentos": int(self.acc.get("reinv", 0)),
             "noEther": round((x + self.fx) * P, 2), "noDolar": round(y + self.fy, 2)}
        if self.regra != "segurar":
            e["perdaImp"] = round(self.acc["pi"] + self.perda_imp(s), 4)
            e["dentro"] = self.dentro(s)
            e["dentroFrac"] = round(self.acc["dentro"] / tot, 4) if tot > 0 else None
            if self.largura is not None:
                e["faixa"] = [round(preco_de(self.sa), 2), round(preco_de(self.sb), 2)]
        self.curva.extra = e


# ---------------------------------------------------------------------------------------------------- leitura
class Arquivo(Exception):
    """O publicnode recusou blocos antigos demais."""


def eh_arquivo(e):
    m = str(e).lower()
    return "archive" in m or "personal token" in m or "pruned" in m


def referencia(rpc):
    """(bloco, ms) do último bloco confirmado (o `latest` − CONFIRMACOES)."""
    b = rpc("eth_getBlockByNumber", ["latest", False]) or {}
    num, ts = int(b["number"], 16), int(b["timestamp"], 16) * 1000
    return num - CONFIRMACOES, ts - CONFIRMACOES * BLOCO_MS


def ler_trocas(rpc, de, ate, ref, estado_pedaco, tempo, log):
    """Gera (bloco final lido, [trocas]) em pedaços de blocos, do bloco `de` ao `ate`, enquanto `tempo()` deixar. O
    tamanho do pedaço se ajusta (`estado_pedaco["n"]`). Levanta Arquivo se o RPC recusar blocos antigos."""
    a = de
    while a <= ate:
        if not tempo():
            return
        n = int(estado_pedaco.get("n") or PEDACO_INI)
        b = min(ate, a + n - 1)
        try:
            logs = rpc("eth_getLogs", [{"address": POOL, "topics": [TOPICO_SWAP], "fromBlock": hex(a), "toBlock": hex(b)}])
        except ERROS as e:
            if eh_arquivo(e):
                raise Arquivo(str(e)) from None
            if n <= PEDACO_MIN:
                raise
            estado_pedaco["n"] = max(PEDACO_MIN, n // 2)
            estado_pedaco["teto"] = n  # não volta a pedir tanto (só até 3/4 disso)
            log(f"  pools: pedaço de {n} blocos recusado ({str(e)[:120]}); tentando com {estado_pedaco['n']}")
            continue
        if not isinstance(logs, list):
            raise rede.Erro(f"eth_getLogs sem lista ({type(logs).__name__})")
        trocas = [x for x in (ler_evento(g, *ref) for g in logs) if x]
        trocas.sort(key=lambda x: (x[1], x[2]))
        if len(logs) < MAX_EVENTOS_PEDIDO * 0.3 and n < PEDACO_MAX:
            teto = estado_pedaco.get("teto")
            estado_pedaco["n"] = max(n, min(PEDACO_MAX, n * 2, teto * 3 // 4 if teto else PEDACO_MAX))
        elif len(logs) > MAX_EVENTOS_PEDIDO * 0.8:
            estado_pedaco["n"] = max(PEDACO_MIN, n // 2)
        yield b, trocas
        a = b + 1


class Grupo:
    """As versões que andam juntas pelas mesmas trocas: "vivo" ou "hist". `s` é o último √P do grupo, `bloco` o último
    bloco lido."""

    def __init__(self, nome, inicio, estado=None):
        e = estado or {}
        self.nome = nome
        self.bloco = int(e.get("bloco") or 0)
        self.s = e.get("s")
        self.inicio = int(e.get("inicio") or inicio)
        self.contas = {cfg[0]: Conta(cfg, self.inicio, (e.get("contas") or {}).get(cfg[0])) for cfg in VERSOES}
        self.trocas = int(e.get("trocas") or 0)

    def para_json(self):
        return {"bloco": self.bloco, "s": self.s, "inicio": self.inicio, "trocas": self.trocas,
                "contas": {k: c.para_json() for k, c in self.contas.items()}}

    def alimentar(self, trocas, gas_wei, ev=None):
        cs = list(self.contas.values())
        for t, _b, _i, s, _liq, _v in trocas:
            s0 = self.s
            for c in cs:
                c.troca(t, s0, s, gas_wei, ev)
            self.s = s
            self.trocas += 1

    def fechar(self, t):
        """No fim de um pedaço: marca as curvas até `t` (o preço continua o da última troca)."""
        for c in self.contas.values():
            if c.montada:
                c.marcar(max(c.t, t), agenda=False)

    def pulo(self):
        """Blocos que não deu para ler: o caminho do preço se perde (nenhuma taxa até a próxima troca)."""
        self.s = None


def gas_mediano(est):
    xs = sorted(v for _, v in est.get("gas") or [] if v)
    return xs[len(xs) // 2] if xs else GAS_PADRAO


def conferir_pool(rpc, est, agora, log, erros):
    """token0() e fee() do pool (uma vez por semana): o código supõe token0 = WETH e taxa de 0,05%."""
    c = est.get("pool") or {}
    if c and agora - int(c.get("em") or 0) < PARAMS_REFAZER:
        return
    try:
        t0 = rpc("eth_call", [{"to": POOL, "data": SEL_TOKEN0}, "latest"])
        fee = rpc("eth_call", [{"to": POOL, "data": SEL_FEE}, "latest"])
        tok = "0x" + str(t0)[-40:]
        f = int(fee, 16) if fee else None
        est["pool"] = {"em": agora, "token0": tok, "fee": f}
        if tok.lower() != WETH.lower() or f != int(TAXA_POOL * 1e6):
            raise rede.Erro(f"o pool não é o esperado (token0 {tok}, taxa {f}): conferir POOL")
    except ERROS as e:
        if "não é o esperado" in str(e):
            raise
        erros.append(f"conferência do pool: {e}")
        log(f"  pools: conferência do pool: {e}")


def conferencia_gecko(fonte, est, agora, log, erros):
    """O volume de 24 h do GeckoTerminal contra o nosso (soma das trocas lidas), uma vez a cada 12 h (não conferido)."""
    g = est.get("gecko") or {}
    if g and agora - int(g.get("em") or 0) < 12 * HORA:
        return g
    if not hasattr(fonte, "gecko"):
        return g
    try:
        r = fonte.gecko(f"/networks/base/pools/{POOL.lower()}") or {}
        at = ((r.get("data") or {}).get("attributes")) or {}
        if not g.get("formatoVisto"):
            log(f"  pools: formato do GeckoTerminal: {rede.estrutura(at, 2)}")
        vol = ((at.get("volume_usd") or {}).get("h24"))
        g = {"em": agora, "volume24h": float(vol) if vol is not None else None,
             "tvl": float(at["reserve_in_usd"]) if at.get("reserve_in_usd") is not None else None, "formatoVisto": True}
        est["gecko"] = g
    except (ERROS + (ValueError, TypeError)) as e:
        erros.append(f"GeckoTerminal: {e}")
    return g


def volume_24h(est, agora):
    v = est.get("volume") or {}
    return sum(x for h, x in v.items() if agora - 24 * HORA <= int(h) < agora)


# ---------------------------------------------------------------------------------------------------- rodada
def rodar(ctx):
    erros = []
    est = copy.deepcopy(ctx.est)
    agora, log = int(ctx.agora), ctx.log
    fonte = rede.fonte_de(ctx, "rpc")
    p0 = getattr(fonte, "pedidos", 0)
    rpc = fonte.rpc
    try:
        ref = referencia(rpc)
        topo = ref[0]
        conferir_pool(rpc, est, agora, log, erros)
        try:
            g = int(rpc("eth_gasPrice", []), 16)
            est["gas"] = (est.get("gas") or [])[-(GAS_GUARDAR - 1):] + [[agora, g]]
        except (ERROS + (TypeError, ValueError)) as e:
            erros.append(f"preço do gás: {e}")
        gas_wei = gas_mediano(est)
        ev = Eventos(est.get("eventos"))
        pedaco = est.setdefault("pedaco", {"n": PEDACO_INI})
        vol = est.setdefault("volume", {})

        novo = "vivo" not in est
        vivo = Grupo("vivo", agora, est.get("vivo"))
        hist = Grupo("hist", agora - HIST_DIAS * DIA, est.get("hist"))
        novas = [c[0] for c in VERSOES if not novo and c[0] not in ((est.get("hist") or {}).get("contas") or {})]
        if novas:
            # uma versão nova não tem passado: o teste no passado recomeça para todas, 28 dias antes de agora
            hist = Grupo("hist", agora - HIST_DIAS * DIA)
            hist.bloco = topo - HIST_DIAS * BLOCOS_DIA
            log(f"  pools: versões novas ({', '.join(novas)}); o teste no passado recomeça 28 dias antes de agora")
        if novo:
            vivo.bloco = topo - INICIO_BLOCOS  # uns minutos antes, para o ao vivo já começar com o preço de agora
            hist.bloco = topo - HIST_DIAS * BLOCOS_DIA
            log(f"  pools: começando; o teste no passado lê {HIST_DIAS} dias de trocas (blocos {hist.bloco} a {topo})")

        def tempo():
            return ctx.restante() > RESERVA_S

        def avancar(grupos, de, ate, eventos):
            """Lê [de, ate] e alimenta os grupos; devolve o último bloco lido."""
            ult = de - 1
            for b, trocas in ler_trocas(rpc, de, ate, ref, pedaco, tempo, log):
                for gr in grupos:
                    gr.alimentar(trocas, gas_wei, eventos if gr.nome == "vivo" else None)
                    gr.bloco = b
                    gr.fechar(ref[1] + (b - ref[0]) * BLOCO_MS)
                if any(gr.nome == "vivo" for gr in grupos):  # o volume só pelos blocos novos (o passado já passou por eles)
                    for t, _b, _i, _s, _l, v in trocas:
                        h = str((t // HORA) * HORA)
                        vol[h] = vol.get(h, 0.0) + v
                ult = b
            return ult

        # ---------------------------------------------------------------- ao vivo (e o passado junto, se alcançou)
        juntos = [vivo] + ([hist] if hist.bloco == vivo.bloco else [])
        try:
            if vivo.bloco < topo:
                if vivo.bloco < topo - (HIST_DIAS + 1) * BLOCOS_DIA:
                    pulo = topo - HIST_DIAS * BLOCOS_DIA
                    log(f"  pools: o ao vivo ficou para trás demais; pulando para o bloco {pulo}")
                    erros.append("ao vivo ficou mais de 28 dias para trás: blocos pulados")
                    for gr in juntos:
                        gr.bloco = pulo
                        gr.pulo()
                avancar(juntos, vivo.bloco + 1, topo, ev)
        except Arquivo as e:
            erros.append(f"ao vivo: {e}")
            raise rede.Erro(f"o RPC recusou os blocos do ao vivo: {e}") from None

        # ---------------------------------------------------------------- o passado (enquanto houver tempo)
        if hist.bloco < vivo.bloco:
            while hist.bloco < vivo.bloco and tempo():
                try:
                    avancar([hist], hist.bloco + 1, vivo.bloco, None)
                    break
                except Arquivo as e:
                    pulo = hist.bloco + BLOCOS_DIA
                    log(f"  pools: o RPC recusou blocos antigos ({str(e)[:100]}); o teste no passado começa 1 dia depois")
                    hist.bloco = pulo
                    hist.pulo()
            falta = vivo.bloco - hist.bloco
            if falta > 0:
                log(f"  pools: o teste no passado continua na próxima rodada (faltam {falta} blocos, ~{falta / BLOCOS_DIA:.1f} dias)")
            else:
                log("  pools: o teste no passado alcançou o ao vivo")
        corte = str(((agora - VOL_HORAS * HORA) // HORA) * HORA)
        for h in [h for h in vol if int(h) < int(corte)]:
            del vol[h]

        gk = conferencia_gecko(rede.fonte_de(ctx, "gecko"), est, agora, log, erros)
        # ---------------------------------------------------------------- saída
        est["vivo"], est["hist"] = vivo.para_json(), hist.para_json()
        est["eventos"] = ev.para_json()
        alcancou = hist.bloco >= vivo.bloco
        versoes = []
        for cfg in VERSOES:
            vid, nome, largura, regra, risco, frase = cfg
            cv, ch = vivo.contas[vid], hist.contas[vid]
            hres = None
            if ch.montada and ch.curva.serie:
                hres = ch.curva.resumo(de=dia_de(hist.inicio), ate=dia_de(ch.t), aproximado=False,
                                       nota=(f"Desde {HIST_DIAS} dias antes do começo, troca a troca como o ao vivo"
                                             + ("" if alcancou else "; ainda lendo o passado (continua nas próximas rodadas)") + "."))
            versoes.append({"id": vid, "nome": nome, "frase": frase, "risco": risco, "alav": 1,
                            "grupo": "Referência" if regra == "segurar" else ("Reposiciona" if regra in ("sai", "hora") else
                                                                    "À mão" if regra == "dia" else "Parada"),
                            "aoVivo": cv.curva.resumo() if cv.montada else None, "historico": hres})
        s = vivo.s
        nosso = volume_24h(est, agora)
        cfg_saida = {"frequencia": "a cada 6 h (troca a troca)", "rede": "Base", "protocolo": "Uniswap v3", "pool": POOL,
                     "par": "WETH/USDC", "taxaPool": TAXA_POOL, "precoEth": round(preco_de(s), 2) if s else None,
                     "gasWei": gas_wei, "custoReposicionar": round(custo_gas(gas_wei, preco_de(s)) if s else 0.0, 4),
                     "trocasLidas": {"vivo": vivo.trocas, "hist": hist.trocas},
                     "passado": {"alcancou": alcancou, "faltamDias": round(max(0, vivo.bloco - hist.bloco) / BLOCOS_DIA, 1)},
                     "volume24h": round(nosso, 0), "conferencia": {"fonte": "GeckoTerminal", "volume24h": gk.get("volume24h"),
                                                                  "tvl": gk.get("tvl")} if gk.get("em") else None}
        ctx.est.clear()
        ctx.est.update(est)
        return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": "r3h", "versoes": versoes,
                "eventos": est["eventos"], "itens": [], "avisos": AVISOS, "config": cfg_saida, "erros": erros}
    finally:
        rede.somar_pedidos(ctx, fonte, p0)
