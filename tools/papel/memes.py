"""Memecoins do pump.fun (Solana) como OBSERVATÓRIO, NO PAPEL (plano: docs/plano-testes-mercado-2.md, seção 6; formato:
tools/papel/FORMATO.md). Nenhuma carteira, nenhuma ordem, nenhuma chave: só fontes públicas e gratuitas.

O papel não consegue imitar quem compra no mesmo bloco do lançamento (os robôs de quem lança), e os golpes acontecem em
segundos. Por isso esta forma é um observatório honesto, sem viés de sobrevivência: "de N lançamentos, quantos
dobraram, quantos morreram, quantos foram golpe, e quanto cada regra simples teria dado". A conta de cada regra existe
(para o Placar), mas o aviso é que o real tende a ser pior.

Como funciona ("amostra de 24 h atrás"; job próprio, `memes.yml`, 3 vezes por dia desde 09/11/2026):
1. **Ouvir**: o websocket do PumpPortal (`subscribeNewToken`, grátis) por até `OUVIR_S` s (10 min; ~6,8 lançamentos do
   pump.fun por minuto em 11/2026 → ~68 por rodada, ~200 por dia). A amostra é TODO lançamento do pump.fun ouvido na
   janela; se passar de `AMOSTRA`, um sorteio simples sem reposição (`random.Random(agora).sample`): todos com a mesma
   chance, inclusive os que vão morrer (o destino não é conhecido na hora). O viés que sobra é o do horário: 3 janelas
   fixas por dia (00h41, 08h41 e 16h41 de Brasília), anotado no `config.amostragem`.
2. **Logo depois de ouvir** (os sinais da hora do lançamento; tokens com 0 a ~12 min de vida): RugCheck (riscos
   "danger"); os metadados do token no IPFS (só SIM/NÃO para site ou redes: o link e o nome nunca são guardados); pelo RPC
   público da Solana, as assinaturas da curva do token (`getSignaturesForAddress`: quantas compras no MESMO slot da
   criação, o "bundle", e as do 1º minuto), as primeiras `TX_POR_TOKEN` compras (`getTransaction`: quem comprou cedo e
   quanto SOL o bundle pôs), os maiores donos (`getTokenLargestAccounts`, tirando a própria curva: a concentração dos 10
   maiores), quantas transações a carteira do criador já tinha (`getSignaturesForAddress`, carteira nova = menos de
   `NOVA_TX`) e se o criador já vendeu tudo (`getTokenAccountsByOwner`). O histórico do criador são contagens por
   endereço do que o próprio observatório viu (lançamentos ouvidos, analisados, mortos, que dobraram), com limite.
3. **24 h depois**: a DexScreener (até 30 tokens por pedido) diz quais tiveram negociações, os pares (a curva do pump.fun
   e, se graduou, a PumpSwap) e o preço de agora; quem falta nela é procurado no GeckoTerminal; para os que negociaram,
   as velas de minuto do GeckoTerminal (`currency=token`: o preço em SOL; as primeiras `VELAS` minutos da curva e, se
   graduou, `VELAS` minutos do pool a partir da graduação). Com elas, a curva de cada token (5 min, 1 h, 6 h e 24 h), as
   regras, os sinais de golpe e as carteiras que chegaram cedo (contadas pela semana). E o criador de novo (vendeu tudo
   em 24 h?).
4. **7 dias depois**: os que ainda negociavam em 24 h (ou graduaram) são vistos de novo com velas de 1 h do GeckoTerminal
   (o ponto de 7 dias, a máxima da semana e, nos graduados, as 24 h depois da graduação); os mortos em 24 h contam como
   mortos em 7 dias.
5. **As regras** (US$ 10 por token): na curva, a compra e a venda saem da conta da própria curva (reservas virtuais de 30
   SOL e 1,073 bi de tokens: k = vSol × vTokens; dado o preço, vSol = √(preço × k)), então o deslize da nossa compra é
   exato; no pool depois da graduação, o mesmo com o pool inicial de `AMM_SOL` SOL × `AMM_TOKENS` tokens. Custos (ver
   `CUSTOS`): a taxa do pump.fun (`TAXA_CURVA` por lado na curva, `TAXA_AMM` no pool), a taxa base da rede, a de
   prioridade (a mediana medida × `CU_OPERACAO`) e a gorjeta da Jito (a mediana dos últimos blocos; sem ela,
   `GORJETA_PADRAO`). "1º minuto" compra pelo fechamento do 1º minuto, DEPOIS dos robôs do bloco do lançamento (sem vela
   no minuto, pelo preço depois do bundle). Saída: dobrou → vende; −50% → vende; 30 min → vende (dentro de uma vela, a
   pior hipótese: o −50% antes do dobro).

Nomes, símbolos e links dos tokens NÃO são guardados nem mostrados (qualquer um escolhe o nome, inclusive ofensivos): só
o endereço encurtado. Os endereços das carteiras (públicos) ficam no estado com contagens; na saída, encurtados.

Amostras conferidas (log da 1ª rodada real, 07/11/2026): PumpPortal `signature, mint, traderPublicKey, txType,
initialBuy, solAmount, bondingCurveKey, vTokensInBondingCurve, vSolInBondingCurve, marketCapSol` (e `pool`); DexScreener
`chainId, dexId, url, pairAddress, baseToken, quoteToken, priceNative, priceUsd, txns, volume`; velas do GeckoTerminal
`data.attributes.ohlcv_list`. NÃO conferidos (a 1ª rodada de verdade registra a estrutura no log): `uri` do PumpPortal,
`liquidity`/`pairCreatedAt` da DexScreener, `risks[].level` do RugCheck, as respostas do RPC (`slot`, `blockTime`,
`transaction.message.accountKeys`, `meta.pre/postTokenBalances`, `value[].uiAmount`), as gorjetas da Jito
(`landed_tips_50th_percentile`), os metadados (`twitter`, `telegram`, `website`) e as velas de hora; e a tabela de taxas
do pump.fun (muda com o valor de mercado).
"""
from __future__ import annotations

import copy
import datetime as dt
import math
import random
import re
import time

import rede
from conta import CAPITAL, DIA, HORA, Curva, Eventos, dia_de, moeda_br

try:
    import hl
    ERROS = (rede.Erro, hl.Erro)
except ImportError:  # pragma: no cover
    ERROS = (rede.Erro,)

NOME = "Memecoins"
# 2 (09/11/2026): a 1ª rodada real mostrou que o PumpPortal manda também lançamentos de outras plataformas (a curva
# delas é outra: um deles saiu "28.904 vezes" por erro de unidade) e que a DexScreener não lista boa parte dos tokens
# pequenos (25 de 32 viraram "sem negócios"); a amostra agora é só do pump.fun, quem falta na DexScreener é procurado no
# GeckoTerminal e o que nenhum dos dois conhece fica "sem dados" (fora das apostas). Recomeça do zero.
# A revisão de 09/11/2026 (a curva de cada token, os sinais, a amostra maior, os custos, a graduação, as carteiras que
# chegam cedo e o medidor de golpe) NÃO recomeça: os campos novos só existem nas amostras ouvidas depois dela.
VERSAO = 2

MIN = 60_000
OUVIR_S = 600                     # 10 min ouvindo (~68 lançamentos do pump.fun)
OUVIR_MIN_S = 120
OUVIR_MAX = 3000                  # mensagens (lançamentos de todas as plataformas e migrações)
RESERVA_SINAIS_S = 420            # o tempo guardado depois de ouvir para os sinais da hora do lançamento
AMOSTRA = 80                      # no máximo por rodada (acima disso, sorteio simples)
CADA_AMOSTRA = 7 * HORA           # uma amostra nova se a última tem 7 h ou mais (o job roda 3 vezes por dia)
ESPERA = 24 * HORA                # a análise de uma amostra, 24 h depois
ESPERA7 = 7 * DIA                 # a 2ª olhada, 7 dias depois
DESISTIR7 = 10 * DIA              # sem o GeckoTerminal por 3 dias depois dos 7, o ponto de 7 dias fica sem dados
ANALISES_POR_RODADA = 3
DESISTIR = 72 * HORA              # sem a DexScreener por 3 dias, a amostra é descartada (com aviso)
VELAS = 1000                      # minutos de velas por par (~16,7 h; o máximo de um pedido do GeckoTerminal)
VELAS_H = 200                     # velas de 1 h na olhada de 7 dias
APOSTA = 10.0                     # US$ por token
K_CURVA = 30.0 * 1_073_000_000    # reservas virtuais iniciais do pump.fun: 30 SOL × 1,073 bi de tokens
CURVA_EXTRA = 279_900_000         # tokens virtuais da curva (vTokens − este = os tokens que a curva tem de verdade)
OFERTA = 1_000_000_000            # tokens de cada memecoin do pump.fun
P_GRAD = 115.0 ** 2 / K_CURVA     # SOL por token quando a curva junta ~85 SOL de verdade (vSol ≈ 115): a graduação
P_60 = 60.0 / OFERTA              # valor de mercado de 60 SOL (a regra "momento")
# o pool da PumpSwap na graduação (~79 SOL e ~206,9 mi de tokens; o número da migração para a Raydium, que a PumpSwap
# manteve: conferir). O preço do pool segue x·y = k a partir daí (sem contar quem põe ou tira liquidez).
AMM_SOL, AMM_TOKENS = 79.0, 206_900_000
K_AMM = AMM_SOL * AMM_TOKENS

# ------------------------------------------------------------------ custos (a fonte de cada número em CUSTOS)
TAXA_CURVA = 0.01                 # por lado na curva do pump.fun
TAXA_AMM = 0.003                  # por lado na PumpSwap (0,25% do pool + 0,05% do criador)
REDE_BASE_SOL = 0.000005          # a taxa base da Solana (5.000 lamports por assinatura)
CU_OPERACAO = 100_000             # unidades de computação de uma compra ou venda (estimativa)
GORJETA_PADRAO = 0.001            # SOL de gorjeta da Jito quando a medida falha (o padrão dos robôs de compra)
REDE_SOL = REDE_BASE_SOL + GORJETA_PADRAO  # o custo de rede por operação sem medida nenhuma
DESLIZE_AMM = 0.0                 # (antigo: o deslize do pool agora vem da conta x·y = k)
CUSTOS = {
    "taxaCurva": [TAXA_CURVA, "pump.fun: 1% por compra ou venda na curva (a tabela muda com o valor de mercado: conferir)"],
    "taxaAmm": [TAXA_AMM, "PumpSwap: 0,25% para o pool + 0,05% para o criador, por lado"],
    "redeBase": [REDE_BASE_SOL, "Solana: 5.000 lamports por assinatura"],
    "prioridade": [CU_OPERACAO, "a mediana de getRecentPrioritizationFees (RPC público) × 100 mil unidades de computação"],
    "gorjeta": [GORJETA_PADRAO, "Jito: a mediana das gorjetas que entraram nos últimos blocos (tip_floor); sem a medida, 0,001 SOL"],
    "deslize": [None, "a conta da própria curva (k = vSol × vTokens) com a aposta de US$ 10; no pool, x·y = k com o pool da graduação"],
}

SAIDA_ALTA, SAIDA_BAIXA, SAIDA_MIN = 2.0, 0.5, 30
CRIADOR_GRANDE = 0.10
CONCENTRADO = 0.25                # os 10 maiores donos (fora a curva) com 25% ou mais
BUNDLE_MIN = 2                    # 2 ou mais compras no slot da criação = bundle
NOVA_TX = 10                      # carteira do criador com menos de 10 transações = nova
TX_POR_TOKEN = 4                  # compras do 1º minuto abertas por token (quem comprou cedo)
PAGINAS_SIG = 3                   # páginas de 1.000 assinaturas da curva até achar a criação
CEDO_S = 60                       # "cedo" = no 1º minuto
CRIADOR_SAIU = 0.01               # o criador com menos de 1% do que comprou = vendeu tudo
LIQ_RETIRADA = 0.05               # graduado com menos de 5% da liquidez da graduação = liquidez retirada
FALHAS_RPC = 8                    # falhas seguidas do RPC da Solana: os sinais por ele param nesta rodada
MIN_SINAL = 20                    # a comparação com/sem um sinal só aparece com 20 tokens de cada lado
N_COPIAR = 10                     # as carteiras mais certeiras da semana anterior
MIN_COMPRAS_CEDO = 3              # compras cedo na semana para entrar no ranking
COPIA_ATRASO = 2                  # minutos depois do lançamento: quem copia vê a compra e entra depois
MAX_TOKENS = 3000                 # o resumo de cada token analisado (para as contagens), os mais novos
MAX_ITENS = 40
MAX_CARTEIRAS = 3000
MAX_CRIADORES = 4000
MAX_SEMANA7 = 1500
SOL_PADRAO = 150.0
X_ABSURDO = 1e5                   # máxima ÷ lançamento acima disso = erro de unidade (outra moeda de cotação): fora
DEX_GECKO = {"pump-fun": "pumpfun", "pumpfun": "pumpfun"}
PONTOS = [("5m", "5 min", 5 * MIN), ("1h", "1 h", HORA), ("6h", "6 h", 6 * HORA), ("24h", "24 h", ESPERA), ("7d", "7 dias", ESPERA7)]
PONTOS_GRAD = [("0", "Na graduação", 0), ("5m", "5 min", 5 * MIN), ("1h", "1 h", HORA), ("6h", "6 h", 6 * HORA), ("24h", "24 h", ESPERA)]

# (id, nome, entrada, filtro RugCheck, saída, risco, frase)
VERSOES = [
    ("min1", "1º minuto", "min1", False, "regras", "alto",
     "Compra US$ 10 de cada lançamento da amostra no fim do 1º minuto (depois dos robôs do bloco do lançamento); vende "
     "quando dobra, quando cai 50% ou depois de 30 min."),
    ("min5", "5º minuto", "min5", False, "regras", "alto",
     "A mesma coisa, mas compra no 5º minuto (os que já morreram no começo ficam de fora)."),
    ("momento", "Momento (60 SOL)", "momento", False, "regras", "alto",
     "Só compra quando o valor de mercado chega a 60 SOL (mais ou menos o dobro do lançamento): aposta em quem já subiu."),
    ("graduacao", "Na graduação", "graduacao", False, "regras", "alto",
     "Só compra os que se formam (a curva enche e o token vai para a PumpSwap), no momento da graduação."),
    ("grad1h", "1 h depois da graduação", "grad1h", False, "regras", "alto",
     "Só compra os que se formam, 1 hora depois da graduação (quando a euforia da formatura já passou)."),
    ("min1rc", "1º minuto + RugCheck", "min1", True, "regras", "alto",
     "O 1º minuto, mas só nos tokens sem risco alto no RugCheck logo depois do lançamento."),
    ("copia", "Copiar quem chega cedo", "copia", False, "regras", "alto",
     "Compra 2 minutos depois do lançamento quando uma das 10 carteiras que mais acertaram na semana anterior comprou no "
     "1º minuto (escolhidas com a semana passada, medidas nesta: fora da amostra)."),
    ("segura", "1º minuto e segura", "min1", False, "segura", "alto",
     "Referência: compra no 1º minuto e só vende cerca de 24 h depois. Mostra o que acontece com a maioria."),
]
FRASE = ("Observatório das moedas novas do pump.fun: de cada lote de lançamentos, quantas dobram, quantas morrem, quantas "
         "são golpe, e quanto cada regra simples teria dado.")
COMO_FUNCIONA = [
    "Qualquer pessoa cria uma memecoin no pump.fun em segundos; são uns 10 mil lançamentos por dia na Solana. O preço "
    "segue uma curva: cada compra deixa o próximo mais caro. Se a curva enche, o token se forma e passa a ser negociado "
    "numa corretora (a graduação).",
    "Três vezes por dia o papel ouve os lançamentos por 10 minutos e fica com todos (uns 70; se passar de 80, sorteia), "
    "inclusive os que vão morrer. Logo depois, anota os sinais da hora: quanto o criador comprou, se houve compras no "
    "mesmo bloco (bundle), quanto os 10 maiores donos têm, se tem site ou redes e o que o criador já fez.",
    "24 horas depois olha o que aconteceu com cada um (o preço com 5 min, 1 h, 6 h e 24 h) e simula as regras com US$ 10 "
    "por token; 7 dias depois, olha de novo os que ainda estavam vivos.",
    "As regras compram no 1º ou no 5º minuto, quando o token já dobrou, na graduação ou 1 h depois dela, ou copiando as "
    "carteiras que mais acertaram na semana anterior; vendem quando dobra, quando cai 50% ou depois de 30 minutos. A taxa "
    "do pump.fun, a da rede, a gorjeta e o deslize da própria compra estão descontados.",
    "É um observatório, não uma estratégia: o papel não compra no mesmo segundo do lançamento como os robôs, então o "
    "real tende a ser pior do que estes números.",
]
AVISOS = [
    "Robôs compram no mesmo bloco do lançamento e vendem em cima de quem chega depois: o papel entra pelo preço do fim do "
    "1º minuto, depois deles, mas sem a disputa pela fila.",
    "Em minutos de euforia a fila de transações da Solana atrasa compras e vendas; o papel executa sempre no preço da "
    "vela e paga só a gorjeta mediana.",
    "Alguns tokens fora do pump.fun não deixam vender; aqui todos são da curva do pump.fun, mas golpes de outros tipos "
    "existem.",
    "Num token de US$ 2 mil de valor, uma compra de US$ 10 já mexe no preço: a conta da curva desconta isso, mas a dos "
    "outros compradores ao mesmo tempo não.",
    "O resultado é de 24 h atrás (a amostra de agora só é analisada amanhã), e o de 7 dias, de uma semana atrás.",
    "As amostras saem sempre nos mesmos 3 horários do dia: o que acontece de madrugada nos EUA pesa mais ou menos que a "
    "média.",
    "Os nomes dos tokens não aparecem: qualquer um escolhe o nome, inclusive ofensivo ou enganoso.",
]


def _f(x, padrao=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else padrao
    except (TypeError, ValueError):
        return padrao


def curto(mint):
    m = str(mint or "")
    return f"{m[:4]}…{m[-4:]}" if len(m) > 10 else m


def semana_de(ms):
    """A semana ISO (segunda a domingo, UTC), "2026-W46"."""
    d = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isocalendar()
    return f"{d[0]}-W{d[1]:02d}"


def semana_antes(sem):
    a, w = sem.split("-W")
    d = dt.date.fromisocalendar(int(a), int(w), 1) - dt.timedelta(days=7)
    i = d.isocalendar()
    return f"{i[0]}-W{i[1]:02d}"


def wilson(k, n, z=1.96):
    """O intervalo de 95% de Wilson para k sucessos em n (proporção, de 0 a 1)."""
    if not n:
        return None
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    meia = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0.0, centro - meia), 4), round(min(1.0, centro + meia), 4)]


def quartis(xs):
    xs = sorted(xs)
    if not xs:
        return None

    def q(f):
        i = f * (len(xs) - 1)
        a, b = int(math.floor(i)), int(math.ceil(i))
        return xs[a] + (xs[b] - xs[a]) * (i - a)
    return [round(q(0.25), 4), round(q(0.5), 4), round(q(0.75), 4)]


def mediana(xs):
    xs = sorted(x for x in xs if x is not None)
    return xs[len(xs) // 2] if xs else None


# ---------------------------------------------------------------------------------------------------- a curva
def comprar_curva(sol, p, k=K_CURVA):
    """Tokens recebidos com `sol` (já sem a taxa) na curva x·y = k com o preço `p` (SOL por token)."""
    vS = math.sqrt(p * k)
    vT = k / vS
    return vT - k / (vS + sol)


def vender_curva(q, p, k=K_CURVA):
    """SOL recebido (sem a taxa) vendendo `q` tokens na curva x·y = k com o preço `p`."""
    vS = math.sqrt(p * k)
    vT = k / vS
    return vS - k / (vT + q)


def custo_operacao(prio=None, gorjeta=None):
    """SOL de rede por operação: a taxa base + a prioridade (micro-lamports por unidade × `CU_OPERACAO`) + a gorjeta."""
    p = (prio or 0) * CU_OPERACAO / 1e6 / 1e9
    g = GORJETA_PADRAO if gorjeta is None else gorjeta
    return REDE_BASE_SOL + p + g


def _somar(partes, k, v):
    if partes is not None:
        partes[k] = partes.get(k, 0.0) + v


def entrar(sol, p, graduado, custo=REDE_SOL, partes=None):
    """(tokens, sol gasto) de uma compra de `sol` (com a taxa e a rede) pelo preço `p`. `partes` soma os custos em SOL
    (`taxa`, `rede`, `deslize`)."""
    liquido = max(0.0, sol - custo)
    taxa = liquido * (TAXA_AMM if graduado else TAXA_CURVA)
    base = liquido - taxa
    q = comprar_curva(base, p, K_AMM if graduado else K_CURVA)
    _somar(partes, "taxa", taxa)
    _somar(partes, "rede", min(sol, custo))
    _somar(partes, "deslize", max(0.0, base - q * p))
    return q, sol


def sair(q, p, graduado, custo=REDE_SOL, partes=None):
    """SOL líquido vendendo `q` tokens pelo preço `p` (com a taxa e a rede)."""
    _somar(partes, "rede", custo)
    if q <= 0 or p <= 0:
        return -custo
    bruto = vender_curva(q, p, K_AMM if graduado else K_CURVA)
    taxa = bruto * (TAXA_AMM if graduado else TAXA_CURVA)
    _somar(partes, "taxa", taxa)
    _somar(partes, "deslize", max(0.0, q * p - bruto))
    return bruto - taxa - custo


def preco_depois(p, sol):
    """O preço da curva depois de `sol` (já sem a taxa) entrar nela a partir do preço `p`."""
    vS = math.sqrt(p * K_CURVA) + sol
    return vS * vS / K_CURVA


# ---------------------------------------------------------------------------------------------------- velas e regras
def juntar_velas(listas):
    """[(t ms, abre, máx., mín., fecha, volume)] em ordem, sem repetir o minuto (a curva vale até a graduação)."""
    por_t = {}
    for lst in listas:
        for v in lst:
            por_t.setdefault(v[0], v)
    return [por_t[k] for k in sorted(por_t)]


def preco_em(velas, t, p0):
    """O fechamento da última vela até `t` (sem vela, `p0`). Como a vela é marcada pelo começo do minuto, a vela que contém
    `t` fecha DEPOIS de `t`: o fim do minuto."""
    p = p0
    for v in velas:
        if v[0] > t:
            break
        p = v[4]
    return p


def t_grad(tok, velas):
    """A hora da graduação: o par da PumpSwap ou a 1ª vela que passou do preço da graduação."""
    if tok.get("tGrad"):
        return tok["tGrad"]
    return next((v[0] for v in velas if v[2] >= P_GRAD and v[0] >= tok["t"]), None)


def entrada(versao_entrada, tok, velas):
    """(t, preço) da entrada da regra ou None."""
    t0, p0 = tok["t"], tok["p0"]
    if versao_entrada in ("min1", "min5", "copia"):
        if versao_entrada == "copia" and not tok.get("copiar"):
            return None
        m = {"min1": 1, "min5": 5, "copia": COPIA_ATRASO}[versao_entrada]
        t = t0 + m * MIN
        # sem vela até lá, o preço depois das compras do bloco do lançamento (o bundle), se conhecidas
        return t, preco_em(velas, t, tok.get("pB") or p0)
    if versao_entrada in ("graduacao", "grad1h"):
        tg = t_grad(tok, velas)
        if not tg:
            return None
        t = tg + (HORA if versao_entrada == "grad1h" else 0)
        if versao_entrada == "grad1h" and velas and t > velas[-1][0] + 6 * HORA:
            return None  # sem velas perto da hora: não se sabe o preço
        return t, preco_em(velas, t, max(p0, P_GRAD))
    for v in velas:
        if v[2] >= P_60 and v[0] >= t0:
            return v[0], max(P_60, v[1])
    return None


def simular(tok, velas, versao, sol_usd, custo=REDE_SOL, partes=None):
    """Uma aposta de US$ 10 num token: (resultado em US$, saída (t), motivo, entrada (t)) ou None se a regra não
    entrou. `partes` soma os custos em SOL."""
    _vid, _nome, ent, filtro, saida, _r, _fr = versao
    if filtro and tok.get("rc") != "ok":
        return None
    e = entrada(ent, tok, velas)
    if not e:
        return None
    te, pe = e
    tg = t_grad(tok, velas) if ent in ("graduacao", "grad1h") else tok.get("tGrad")
    grad = lambda t: bool(tg) and t >= tg  # noqa: E731
    sol = APOSTA / sol_usd
    q, gasto = entrar(sol, pe, grad(te), custo, partes)
    if saida == "segura":
        p24 = tok.get("p24")
        if p24 is None:
            p24 = preco_em(velas, te + ESPERA, pe) if velas else pe
        ts = te + ESPERA
        recebido = sair(q, p24, grad(ts), custo, partes) if p24 > 0 else -custo
        return (recebido - gasto) * sol_usd, ts, "24 h", te
    for v in velas:
        if v[0] <= te:
            continue
        if v[0] > te + SAIDA_MIN * MIN:
            break
        if v[3] <= pe * SAIDA_BAIXA:
            return (sair(q, pe * SAIDA_BAIXA, grad(v[0]), custo, partes) - gasto) * sol_usd, v[0], "−50%", te
        if v[2] >= pe * SAIDA_ALTA:
            return (sair(q, pe * SAIDA_ALTA, grad(v[0]), custo, partes) - gasto) * sol_usd, v[0], "dobrou", te
    ts = te + SAIDA_MIN * MIN
    return (sair(q, preco_em(velas, ts, pe), grad(ts), custo, partes) - gasto) * sol_usd, ts, "30 min", te


def pontos_da_curva(tok, velas, negociou, p24):
    """Os múltiplos do preço do lançamento em 5 min, 1 h, 6 h e 24 h (e o lugar dos 7 dias, None). Sem negócios = 0
    (ninguém comprou: não vale nada para vender); depois das velas, o último fechamento."""
    if not negociou:
        return [0.0] * 4 + [None]
    p0, t0 = tok["p0"], tok["t"]
    out = [round(preco_em(velas, t0 + d, p0) / p0, 4) for _id, _n, d in PONTOS[:3]]
    out.append(round(p24 / p0, 4) if p24 is not None else None)
    return out + [None]


def pontos_grad(tg, velas, ate):
    """Os múltiplos do preço da graduação em 5 min, 1 h e 6 h depois (e o lugar das 24 h, None); só o que as velas
    alcançam (`ate`)."""
    pg = preco_em(velas, tg, P_GRAD)
    if pg <= 0:
        return None
    out = [1.0]
    for _id, _n, d in PONTOS_GRAD[1:4]:
        out.append(round(preco_em(velas, tg + d, pg) / pg, 4) if tg + d <= ate else None)
    return {"p": pg, "c": out + [None]}


def classificar(tok, velas, faltou=False):
    """O resumo do que aconteceu com um token (as contagens do observatório). `faltou`: tinha par, mas as velas não
    vieram (conta como negociado e não morto, e fica fora das apostas)."""
    p0, t0 = tok["p0"], tok["t"]
    maxp = max([v[2] for v in velas] + [tok.get("p24") or 0, p0])
    p24 = tok.get("p24")
    if p24 is None:
        p24 = velas[-1][4] if velas else p0
    golpe, qm = False, None
    for i, v in enumerate(velas):
        if v[0] > t0 + HORA:
            break
        pico = max(x[2] for x in velas[max(0, i - 5):i + 1])
        if v[3] <= 0.1 * pico and pico > p0 * 1.05:
            golpe, qm = True, round(max(0, v[0] - t0) / MIN, 1)  # o minuto da vela da queda
            break
    negociou = faltou or any(v[0] >= t0 + MIN for v in velas)
    grad = bool(tok.get("tGrad")) or maxp >= P_GRAD
    morto = (not negociou) or (p24 < 0.1 * p0 and not grad)
    c = pontos_da_curva(tok, velas, negociou, p24) if not faltou else [None] * 5
    sumiu = None
    if not faltou:
        depois1h = any(v[0] >= t0 + HORA for v in velas)
        sumiu = (not negociou) or (not grad and (not depois1h or (c[1] is not None and c[1] < 0.1)))
    return {"t": t0, "m": curto(tok["mint"]), "x": round(maxp / p0, 3), "x24": round(p24 / p0, 4) if negociou else None, "g": grad,
            "gp": golpe, "mo": morto, "sv": not negociou, "rc": tok.get("rc"), "cr": round(tok.get("cr") or 0, 4),
            "vf": faltou, "c": c, "s1h": sumiu, "xs": round(maxp / p0, 3), "qm": qm}


def contagens(lista):
    n = len(lista)
    if not n:
        return {"tokens": 0}
    c = lambda f: sum(1 for x in lista if f(x))  # noqa: E731
    x24 = sorted(x["x24"] for x in lista if x["x24"] is not None)
    return {"tokens": n, "dobraram": c(lambda x: x["x"] >= 2), "dezVezes": c(lambda x: max(x["x"], x.get("xs") or 0) >= 10),
            "graduaram": c(lambda x: x["g"]), "golpes": c(lambda x: x["gp"]), "morreram": c(lambda x: x["mo"]),
            "semNegocios": c(lambda x: x["sv"]), "rugcheckAlto": c(lambda x: x["rc"] == "alto"),
            "rugcheckSem": c(lambda x: x["rc"] is None), "criadorGrande": c(lambda x: x["cr"] >= CRIADOR_GRANDE),
            "medianaX24": x24[len(x24) // 2] if x24 else None, "semVelas": c(lambda x: x.get("vf") and not x.get("sd")),
            "semDados": c(lambda x: x.get("sd")),
            "vivos24h": c(lambda x: x["x24"] is not None and x["x24"] >= 1 and not x["mo"])}


# ---------------------------------------------------------------------------------------------------- o observatório
def _taxa(id_, nome, k, n, dica):
    return {"id": id_, "nome": nome, "k": k, "n": n, "p": round(k / n, 4) if n else None, "ic": wilson(k, n), "dica": dica}


def taxas_basicas(lista):
    """"De cada 100 lançamentos": as taxas com o tamanho da amostra e o intervalo de 95% (Wilson). Os "sem dados" ficam
    fora; o de 7 dias só conta quem já passou dos 7 dias."""
    ok = [x for x in lista if not x.get("sd")]
    com_c = [x for x in ok if x.get("c") is not None and not x.get("vf")]
    n = len(ok)
    s1h = [x for x in com_c if x.get("s1h") is not None]
    v24 = [x for x in ok if not x.get("vf")]
    v7 = [x for x in com_c if x["c"][4] is not None]
    return [
        _taxa("somem1h", "Somem na 1ª hora", sum(1 for x in s1h if x["s1h"]), len(s1h),
              "sem negócios depois de 1 h ou valendo menos de 10% do lançamento"),
        _taxa("dobram", "Chegam a dobrar", sum(1 for x in ok if x["x"] >= 2), n, "o preço chegou a 2× o do lançamento em algum momento"),
        _taxa("vale24", "Valem 50% ou mais em 24 h", sum(1 for x in v24 if (x["x24"] or 0) >= 0.5), len(v24),
              "o preço de 24 h depois é pelo menos metade do lançamento (sem negócios conta como não)"),
        _taxa("vale7d", "Valem 50% ou mais em 7 dias", sum(1 for x in v7 if x["c"][4] >= 0.5), len(v7),
              "só os que já passaram dos 7 dias; mortos em 24 h contam como mortos"),
        _taxa("dez", "Chegam a 10×", sum(1 for x in ok if max(x["x"], x.get("xs") or 0) >= 10), n, "a máxima chegou a 10× o lançamento (até 7 dias)"),
        _taxa("graduam", "Se formam", sum(1 for x in ok if x["g"]), n, "a curva encheu e o token foi para a PumpSwap"),
    ]


def curva_tipica(lista):
    """A mediana e os quartis do preço ÷ o do lançamento em cada ponto (0 = sem negócios ou morto)."""
    out = []
    for i, (id_, nome, _d) in enumerate(PONTOS):
        xs = [x["c"][i] for x in lista if not x.get("sd") and x.get("c") and x["c"][i] is not None]
        q = quartis(xs)
        out.append({"id": id_, "nome": nome, "n": len(xs), "q1": q[0] if q else None, "mediana": q[1] if q else None,
                    "q3": q[2] if q else None, "acima": round(sum(1 for x in xs if x >= 1) / len(xs), 4) if xs else None})
    return out


SINAIS = [
    ("criadorGrande", "Criador comprou 10% ou mais", lambda s: s.get("cg")),
    ("concentrado", "Os 10 maiores donos com 25% ou mais", lambda s: None if s.get("con") is None else s["con"] >= CONCENTRADO),
    ("bundle", "Compras no mesmo bloco do lançamento (bundle)", lambda s: None if s.get("bd") is None else s["bd"] >= BUNDLE_MIN),
    ("redes", "Tem site ou redes", lambda s: s.get("rd")),
    ("criadorRepetido", "O criador já lançou outro (visto aqui)", lambda s: None if s.get("crN") is None else s["crN"] >= 1),
    ("carteiraNova", "Carteira do criador nova (menos de 10 transações)", lambda s: s.get("nv")),
    ("rugcheck", "RugCheck com risco alto", lambda s: None if s.get("rc") is None else s["rc"] == "alto"),
]


def _lado(xs):
    n = len(xs)
    sv = sum(1 for x in xs if (x["x24"] or 0) >= 0.5)
    db = sum(1 for x in xs if x["x"] >= 2)
    return {"n": n, "sobreviveram": round(sv / n, 4) if n else None, "icSobreviveram": wilson(sv, n),
            "dobraram": round(db / n, 4) if n else None, "icDobraram": wilson(db, n)}


def tabela_sinais(lista):
    """Com o sinal × sem ele: % que valiam 50% ou mais em 24 h ("sobreviveram") e % que dobraram. Só os tokens com os
    sinais anotados (os ouvidos depois de 09/11/2026); a comparação só vale (`ok`) com `MIN_SINAL` de cada lado."""
    base = [x for x in lista if isinstance(x.get("sg"), dict) and not x.get("sd") and not x.get("vf")]
    out = []
    for id_, nome, f in SINAIS:
        com, sem, sd = [], [], 0
        for x in base:
            v = f(x["sg"])
            if v is None:
                sd += 1
            elif v:
                com.append(x)
            else:
                sem.append(x)
        out.append({"id": id_, "nome": nome, "com": _lado(com), "sem": _lado(sem), "semDados": sd,
                    "ok": len(com) >= MIN_SINAL and len(sem) >= MIN_SINAL})
    return {"minimo": MIN_SINAL, "tokens": len(base), "linhas": out}


def resumo_graduacao(lista, regras):
    ok = [x for x in lista if not x.get("sd")]
    gs = [x for x in ok if x["g"]]
    curva = []
    for i, (id_, nome, _d) in enumerate(PONTOS_GRAD):
        xs = [x["gr"]["c"][i] for x in gs if isinstance(x.get("gr"), dict) and x["gr"]["c"][i] is not None]
        q = quartis(xs)
        curva.append({"id": id_, "nome": nome, "n": len(xs), "q1": q[0] if q else None, "mediana": q[1] if q else None,
                      "q3": q[2] if q else None})
    mins = [x["gr"]["min"] for x in gs if isinstance(x.get("gr"), dict) and x["gr"].get("min") is not None]
    return {"n": len(ok), "graduaram": len(gs), "taxa": round(len(gs) / len(ok), 4) if ok else None,
            "ic": wilson(len(gs), len(ok)), "minutosMediana": mediana(mins), "curva": curva,
            "regras": [r for r in regras if r["id"] in ("graduacao", "grad1h")]}


GOLPES = [
    ("criadorCedo", "O criador vendeu tudo logo no começo", lambda g: None if g.get("cs") is None else g["cs"] is not False),
    ("criador24h", "O criador vendeu tudo em 24 h", lambda g: g.get("cs24")),
    ("queda", "Caiu mais de 90% em minutos", lambda g: g.get("q")),
    ("rugcheck", "RugCheck com risco alto", lambda g: g.get("rc")),
    ("liquidez", "Liquidez retirada do pool", lambda g: g.get("lq")),
]


def eh_golpe(x):
    g = x.get("gl") or {"q": x.get("gp"), "rc": None if x.get("rc") is None else x.get("rc") == "alto"}
    return any(f(g) for _i, _n, f in GOLPES)


def medidor_golpe(lista, regras):
    ok = [x for x in lista if not x.get("sd") and not x.get("vf")]
    linhas = []
    for id_, nome, f in GOLPES:
        k = n = 0
        for x in ok:
            g = x.get("gl")
            if not isinstance(g, dict):
                g = {"q": x.get("gp"), "rc": None if x.get("rc") is None else x.get("rc") == "alto"}
            v = f(g)
            if v is None:
                continue
            n += 1
            k += 1 if v else 0
        linhas.append(_taxa(id_, nome, k, n, ""))
    qual = sum(1 for x in ok if eh_golpe(x))
    linhas.append(_taxa("qualquer", "Qualquer um destes", qual, len(ok), ""))
    cedo = [x["gl"]["cs"] for x in ok if isinstance(x.get("gl"), dict) and type(x["gl"].get("cs")) in (int, float)]
    checados = [x["gl"].get("chk") for x in ok if isinstance(x.get("gl"), dict) and x["gl"].get("chk") is not None]
    return {"linhas": linhas, "minutosQueda": mediana([x.get("qm") for x in ok if x.get("gp")]),
            "minutosCriador": mediana(cedo), "idadeChecagem": mediana(checados),
            "regras": [{"id": r["id"], "nome": r["nome"], "apostas": r["apostas"], "emGolpe": r.get("emGolpe", 0),
                        "fracao": round(r.get("emGolpe", 0) / r["apostas"], 4) if r["apostas"] else None,
                        "resultado": r.get("resultadoGolpe", 0.0)} for r in regras]}


# ---------------------------------------------------------------------------------------------------- fontes
def eh_pumpfun(m):
    """O PumpPortal manda também os lançamentos de outras plataformas (o campo `pool`: "pump", "bonk"…). Só os do
    pump.fun entram (a curva da simulação é a dele); sem o campo, vale o endereço terminado em "pump"."""
    pool = m.get("pool")
    if pool is not None:
        return str(pool).lower() == "pump"
    return str(m.get("mint") or "").endswith("pump")


def ler_lancamento(m, agora):
    """Uma mensagem de criação do PumpPortal → o token (só números e endereços) ou None. O `uri` (os metadados) fica só
    durante a rodada (para saber se tem site ou redes) e é apagado antes de guardar."""
    if not isinstance(m, dict) or m.get("txType") not in ("create", None) or not m.get("mint"):
        return None
    if not eh_pumpfun(m):
        return None
    vS, vT = _f(m.get("vSolInBondingCurve")), _f(m.get("vTokensInBondingCurve"))
    if not vS or not vT:
        return None
    t = _f(m.get("timestamp")) or _f(m.get("_t")) or agora
    if t < 1e11:  # em segundos
        t *= 1000
    tok = {"mint": str(m["mint"]), "curva": m.get("bondingCurveKey"), "t": int(t),
           "p0": vS / vT, "mc": _f(m.get("marketCapSol")), "cr": (_f(m.get("initialBuy"), 0.0) or 0.0) / OFERTA,
           "pool": m.get("pool")}
    if m.get("traderPublicKey"):
        tok["criador"] = str(m["traderPublicKey"])
    if isinstance(m.get("uri"), str):
        tok["uri"] = m["uri"]
    return tok


def ouvir(fonte, agora, est, log, erros, segundos=OUVIR_S):
    """(lançamentos, migrações, segundos ouvidos)."""
    try:
        msgs = fonte.pumpportal_ouvir(segundos, OUVIR_MAX)
    except ERROS as e:
        erros.append(f"PumpPortal: {e}")
        log(f"  memes: PumpPortal: {e}")
        return [], [], 0
    if msgs and not est.get("formatoPP2"):
        amostra = next((m for m in msgs if m.get("txType") == "create"), msgs[0])
        log(f"  memes: formato do PumpPortal: {sorted(rede.estrutura(amostra, 1)) if isinstance(amostra, dict) else '?'}")
        est["formatoVisto"] = est["formatoPP2"] = True
    lanc, migr = [], []
    outras = sum(1 for m in msgs if isinstance(m, dict) and m.get("txType") == "create" and m.get("mint")
                 and not eh_pumpfun(m))
    if outras:
        est["outrasPlataformas"] = int(est.get("outrasPlataformas") or 0) + outras
    ts = sorted(int(m["_t"]) for m in msgs if isinstance(m, dict) and m.get("_t"))
    seg = round((ts[-1] - ts[0]) / 1000) if len(ts) > 1 else segundos
    for m in msgs:
        if m.get("txType") == "migrate" or "migrat" in str(m.get("txType") or "").lower():
            if m.get("mint"):
                migr.append(str(m["mint"]))
            continue
        tok = ler_lancamento(m, agora)
        if tok:
            lanc.append(tok)
    return lanc, migr, max(1, seg)


def rugcheck(fonte, tok, erros):
    """"alto" (algum risco "danger"), "ok" ou None (sem resposta)."""
    try:
        r = fonte.rugcheck(tok["mint"]) or {}
    except ERROS as e:
        if len(erros) < 30:
            erros.append(f"RugCheck: {str(e)[:80]}")
        return None
    riscos = r.get("risks") if isinstance(r, dict) else None
    if not isinstance(riscos, list):
        return None
    return "alto" if any(str((x or {}).get("level", "")).lower() == "danger" for x in riscos) else "ok"


RE_CID = re.compile(r"/ipfs/([A-Za-z0-9]{40,100})(?:[/?#]|$)")


def url_metadados(uri):
    """O endereço seguro dos metadados: um CID do IPFS (sempre pelo ipfs.io: o conteúdo é o mesmo em qualquer gateway)
    ou o arweave.net; outro endereço = None (não é aberto)."""
    u = str(uri or "").strip()
    m = RE_CID.search(u)
    if m:
        return rede.URL["ipfs"] + m.group(1)
    if u.startswith("ipfs://"):
        cid = u[7:].split("/")[0]
        if re.fullmatch(r"[A-Za-z0-9]{40,100}", cid):
            return rede.URL["ipfs"] + cid
    m = re.match(r"^https://arweave\.net/([A-Za-z0-9_-]{30,64})$", u)
    if m:
        return u
    return None


def tem_redes(j):
    """SIM/NÃO: os metadados trazem site ou redes (twitter/x, telegram, website, também dentro de `extensions`). Só o
    booleano sai daqui; nenhum valor é guardado."""
    if not isinstance(j, dict):
        return None
    lugares = [j] + ([j["extensions"]] if isinstance(j.get("extensions"), dict) else [])
    for d in lugares:
        for k in ("twitter", "x", "telegram", "website", "discord"):
            v = d.get(k)
            if isinstance(v, str) and len(v.strip()) > 3:
                return True
    return False


class Freio:
    """Conta as falhas seguidas de uma fonte; depois de `limite`, a fonte fica de fora no resto da rodada (o motivo vai
    para `semDados`)."""

    def __init__(self, limite):
        self.limite, self.seguidas, self.motivo = limite, 0, None

    @property
    def parado(self):
        return self.seguidas >= self.limite

    def ok(self):
        self.seguidas = 0

    def falhou(self, e):
        self.seguidas += 1
        self.motivo = str(e)[:120]


def _rpc(fonte, freio, metodo, params, est, log, erros):
    """Uma chamada ao RPC da Solana com o freio; registra a estrutura da 1ª resposta de cada método."""
    if freio.parado:
        return None
    try:
        r = fonte.solana(metodo, params)
    except (ERROS + (TypeError, ValueError, AttributeError)) as e:
        freio.falhou(e)
        if len(erros) < 30:
            erros.append(f"RPC {metodo}: {str(e)[:80]}")
        return None
    freio.ok()
    vistos = est.setdefault("formatosRpc", [])
    if metodo not in vistos and r:
        log(f"  memes: formato do RPC {metodo}: {rede.estrutura(r, 4)}")
        vistos.append(metodo)
    return r


def ler_tx(r, mint):
    """(comprador, comprou?, SOL gasto) de uma transação (`getTransaction`, encoding json) ou None."""
    if not isinstance(r, dict):
        return None
    msg = ((r.get("transaction") or {}).get("message") or {})
    chaves = msg.get("accountKeys") or []
    if not chaves:
        return None
    quem = chaves[0] if isinstance(chaves[0], str) else (chaves[0] or {}).get("pubkey")
    meta = r.get("meta") or {}
    if meta.get("err"):
        return None

    def saldo(lst):
        s = 0.0
        for b in lst or []:
            if isinstance(b, dict) and b.get("owner") == quem and b.get("mint") == mint:
                s += _f((b.get("uiTokenAmount") or {}).get("uiAmount"), 0.0) or 0.0
        return s
    comprou = saldo(meta.get("postTokenBalances")) > saldo(meta.get("preTokenBalances"))
    pre, pos = meta.get("preBalances") or [0], meta.get("postBalances") or [0]
    gasto = max(0.0, ((_f(pre[0], 0) or 0) - (_f(pos[0], 0) or 0) - (_f(meta.get("fee"), 0) or 0)) / 1e9)
    return quem, comprou, gasto


def sinais_do_lancamento(tok, fonte, freio, est, log, erros, agora_chk):
    """Os sinais pelo RPC da Solana (bundle, quem comprou cedo, os 10 maiores, a carteira do criador, se ele já vendeu).
    Cada um fica None se a fonte falhar."""
    mint, curva_k = tok["mint"], tok.get("curva")
    tok.setdefault("sg", {})
    sg = tok["sg"]
    # as assinaturas da curva, da mais nova para a mais velha: a última é a criação
    if curva_k:
        sigs, antes, achou = [], None, False
        for _ in range(PAGINAS_SIG):
            op = {"limit": 1000}
            if antes:
                op["before"] = antes
            r = _rpc(fonte, freio, "getSignaturesForAddress", [curva_k, op], est, log, erros)
            if not isinstance(r, list):
                break
            sigs += [x for x in r if isinstance(x, dict)]
            if len(r) < 1000:
                achou = True
                break
            antes = r[-1].get("signature")
        if achou and sigs:
            cria = sigs[-1]
            slot0, bt0 = cria.get("slot"), _f(cria.get("blockTime"))
            depois = [x for x in reversed(sigs[:-1]) if not x.get("err")]
            sg["bd"] = sum(1 for x in depois if x.get("slot") == slot0)
            cedo_sigs = [x for x in depois if bt0 is not None and (_f(x.get("blockTime"), 1e18) or 1e18) <= bt0 + CEDO_S]
            sg["c1m"] = len(cedo_sigs)
            cedo, bundle, sol_bd = [], [], 0.0
            for x in cedo_sigs[:TX_POR_TOKEN]:
                tx = _rpc(fonte, freio, "getTransaction",
                          [x.get("signature"), {"encoding": "json", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}],
                          est, log, erros)
                lido = ler_tx(tx, mint)
                if not lido or not lido[1] or not lido[0] or lido[0] == tok.get("criador"):
                    continue
                if lido[0] not in cedo:
                    cedo.append(lido[0])
                if x.get("slot") == slot0:
                    if lido[0] not in bundle:
                        bundle.append(lido[0])
                    sol_bd += lido[2]
            tok["cedo"], tok["bdW"] = cedo, bundle
            if sol_bd > 0:
                tok["pB"] = preco_depois(tok["p0"], sol_bd * (1 - TAXA_CURVA))
    # os 10 maiores donos, fora a própria curva (a maior conta enquanto o token não se forma)
    r = _rpc(fonte, freio, "getTokenLargestAccounts", [mint], est, log, erros)
    lst = (r or {}).get("value") if isinstance(r, dict) else None
    if isinstance(lst, list) and lst:
        qs = sorted((_f(x.get("uiAmount"), 0.0) or 0.0 for x in lst if isinstance(x, dict)), reverse=True)
        if qs and qs[0] >= 0.25 * OFERTA:  # a própria curva
            qs = qs[1:]
        sg["con"] = round(sum(qs[:10]) / OFERTA, 4)
    criador = tok.get("criador")
    if criador:
        r = _rpc(fonte, freio, "getSignaturesForAddress", [criador, {"limit": NOVA_TX}], est, log, erros)
        if isinstance(r, list):
            sg["nv"] = len(r) < NOVA_TX
        if tok.get("cr", 0) > 0:
            saiu = criador_vendeu(fonte, freio, tok, est, log, erros)
            if saiu is not None:
                idade = round(max(0, agora_chk - tok["t"]) / MIN, 1)
                tok["cs"] = idade if saiu else False
                tok["chk"] = idade


def criador_vendeu(fonte, freio, tok, est, log, erros):
    """True se o criador tem menos de 1% do que comprou na criação (a conta pode até ter sido fechada), None sem
    resposta."""
    r = _rpc(fonte, freio, "getTokenAccountsByOwner", [tok["criador"], {"mint": tok["mint"]}, {"encoding": "jsonParsed"}],
             est, log, erros)
    if not isinstance(r, dict) or not isinstance(r.get("value"), list):
        return None
    saldo = 0.0
    for x in r["value"]:
        info = ((((x or {}).get("account") or {}).get("data") or {}).get("parsed") or {}).get("info") or {}
        saldo += _f((info.get("tokenAmount") or {}).get("uiAmount"), 0.0) or 0.0
    return saldo < CRIADOR_SAIU * (tok.get("cr") or 0) * OFERTA


def ler_metadados(fonte, tok, est, log, erros, freio):
    url = url_metadados(tok.get("uri"))
    if not url or freio.parado:
        return None
    try:
        j = fonte.metadados(url)
    except ERROS as e:
        freio.falhou(e)
        return None
    freio.ok()
    if j and not est.get("formatoMeta"):
        log(f"  memes: formato dos metadados: {sorted(j) if isinstance(j, dict) else type(j).__name__}")
        est["formatoMeta"] = True
    return tem_redes(j)


def gorjeta_jito(fonte, est, log, erros):
    """(mediana, p75) das gorjetas que entraram nos últimos blocos, em SOL, ou (None, None)."""
    try:
        r = fonte.jito()
    except ERROS as e:
        erros.append(f"Jito: {str(e)[:80]}")
        return None, None
    x = r[0] if isinstance(r, list) and r else r
    if not isinstance(x, dict):
        return None, None
    if not est.get("formatoJito"):
        log(f"  memes: formato da Jito: {sorted(x)}")
        est["formatoJito"] = True
    return _f(x.get("landed_tips_50th_percentile")), _f(x.get("landed_tips_75th_percentile"))


def ler_pares(fonte, mints, log, est, erros):
    """{mint: {"pares": [(dex, endereço, criado ms)], "preco": SOL por token ou None, "liq": US$}} pela DexScreener."""
    out = {}
    for i in range(0, len(mints), 30):
        grupo = mints[i:i + 30]
        r = fonte.dexscreener(f"/tokens/v1/solana/{','.join(grupo)}")  # um erro aqui deixa a amostra para a próxima
        lista = r if isinstance(r, list) else (r or {}).get("pairs") or []
        if lista and not est.get("formatoDex"):
            log(f"  memes: formato da DexScreener: {rede.estrutura(lista[0], 2)}")
            est["formatoDex"] = True
        for p in lista:
            if not isinstance(p, dict):
                continue
            mint = ((p.get("baseToken") or {}).get("address"))
            if mint not in grupo:
                continue
            o = out.setdefault(mint, {"pares": [], "preco": None, "liq": 0.0, "liqAmm": None})
            dex = str(p.get("dexId") or "")
            o["pares"].append((dex, p.get("pairAddress"), int(_f(p.get("pairCreatedAt"), 0) or 0)))
            preco = _f(p.get("priceNative"))
            liq = _f(((p.get("liquidity") or {}).get("usd")), 0.0) or 0.0
            if dex and dex != "pumpfun":
                o["liqAmm"] = max(o["liqAmm"] or 0.0, liq)
            if preco is not None and (o["preco"] is None or liq >= o["liq"]):
                o["preco"], o["liq"] = preco, liq
    return out


def pares_gecko(fonte, mint, log, est, erros):
    """Os pares de um token pelo GeckoTerminal (quando a DexScreener não o conhece): {"pares": [...], "preco": SOL por
    token ou None} ou {"pares": []} se o GeckoTerminal também não conhece (404 ou lista vazia: ninguém negociou), ou None
    se ele falhou (o token fica "sem dados": fora das apostas)."""
    try:
        r = fonte.gecko(f"/networks/solana/tokens/{mint}/pools?page=1")
    except ERROS as e:
        if getattr(e, "status", None) == 404:
            return {"pares": [], "preco": None}
        if len(erros) < 30:
            erros.append(f"GeckoTerminal (pares): {str(e)[:80]}")
        return None
    lst = (r or {}).get("data") or []
    if lst and not est.get("formatoGeckoPares"):
        log(f"  memes: formato dos pares do GeckoTerminal: {rede.estrutura(lst[0], 3)}")
        est["formatoGeckoPares"] = True
    out = {"pares": [], "preco": None, "liq": 0.0, "liqAmm": None}
    for x in lst:
        if not isinstance(x, dict):
            continue
        at = x.get("attributes") or {}
        dex = (((x.get("relationships") or {}).get("dex") or {}).get("data") or {}).get("id") or ""
        end = at.get("address")
        if not end:
            continue
        criado = at.get("pool_created_at")
        try:
            criado = int(dt.datetime.fromisoformat(str(criado).replace("Z", "+00:00")).timestamp() * 1000) if criado else 0
        except ValueError:
            criado = 0
        d = DEX_GECKO.get(dex, dex or "?")
        out["pares"].append((d, end, criado))
        preco = _f(at.get("base_token_price_native_currency"))
        liq = _f(at.get("reserve_in_usd"), 0.0) or 0.0
        if d != "pumpfun":
            out["liqAmm"] = max(out["liqAmm"] or 0.0, liq)
        if preco is not None and (out["preco"] is None or liq >= out["liq"]):
            out["preco"], out["liq"] = preco, liq
    return out


def ler_velas(fonte, par, mint, t0, log, est, erros, antes_ms=None, escala="minute", limite=VELAS):
    """[(t ms, abre, máx., mín., fecha, volume)] em SOL por token, as `limite` velas antes de `antes_ms` (padrão: as
    primeiras VELAS minutos depois de `t0`); [] se o GeckoTerminal não conhece o par (404) e None se ele falhou (o token
    fica sem apostas, mas não conta como morto)."""
    antes = (antes_ms or (t0 + VELAS * MIN)) // 1000
    try:
        r = fonte.gecko(f"/networks/solana/pools/{par}/ohlcv/{escala}?aggregate=1&limit={limite}&currency=token"
                        f"&token={mint}&before_timestamp={antes}")
    except ERROS as e:
        if getattr(e, "status", None) == 404:
            return []
        if len(erros) < 30:
            erros.append(f"GeckoTerminal: {str(e)[:80]}")
        return None
    lst = ((((r or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list")) or []
    chave = "formatoGecko" if escala == "minute" else "formatoGeckoHora"
    if lst and not est.get(chave):
        log(f"  memes: formato das velas ({escala}) do GeckoTerminal: {rede.estrutura(r, 4)}")
        est[chave] = True
    out = []
    for x in lst:
        if isinstance(x, list) and len(x) >= 5:
            v = [_f(y) for y in x[:6]] + [0.0] * (6 - len(x[:6]))
            if v[0] and all(y is not None and y > 0 for y in v[1:5]):
                out.append((int(v[0]) * 1000, v[1], v[2], v[3], v[4], v[5] or 0.0))
    return sorted(out)


def preco_sol(cli, t, erros):
    """O preço do SOL em US$ na hora `t` (velas de 1 h da Hyperliquid)."""
    try:
        vs = cli.velas("SOL", "1h", t - 2 * HORA, t + HORA)
        if vs:
            return float(min(vs, key=lambda c: abs(int(c["t"]) - t))["c"])
    except ERROS as e:
        erros.append(f"preço do SOL: {e}")
    return None


def taxa_prioridade(fonte, erros):
    """A mediana da taxa de prioridade recente (micro-lamports por unidade de computação) ou None."""
    try:
        r = fonte.solana("getRecentPrioritizationFees", []) or []
        xs = sorted(int(x.get("prioritizationFee") or 0) for x in r if isinstance(x, dict))
        return xs[len(xs) // 2] if xs else None
    except (ERROS + (TypeError, ValueError, AttributeError)) as e:
        erros.append(f"taxa de prioridade: {e}")
        return None


# ---------------------------------------------------------------------------------------------------- criadores e carteiras
def _podar(d, maximo, chave="u"):
    if len(d) > maximo:
        for k in sorted(d, key=lambda k: d[k].get(chave) or 0)[:len(d) - maximo]:
            del d[k]


def anotar_criadores(lanc, est):
    """O histórico do criador visto pelo observatório: antes de contar este lançamento, quantos ele já tinha lançado e
    quantos deles morreram (dos analisados). Conta todos os lançamentos ouvidos, não só os da amostra."""
    cri = est.setdefault("criadores", {})
    for tok in sorted(lanc, key=lambda x: x["t"]):
        a = tok.get("criador")
        if not a:
            continue
        c = cri.get(a) or {"l": 0, "a": 0, "m": 0, "d": 0}
        tok.setdefault("sg", {}).update({"crN": c["l"], "crM": c["m"]})
        c["l"] += 1
        c["u"] = tok["t"]
        cri[a] = c
    _podar(cri, MAX_CRIADORES)


def selecao_copia(est, sem, guardar=True):
    """As `N_COPIAR` carteiras mais certeiras da semana ANTERIOR a `sem` (escolhidas uma vez e guardadas: fora da
    amostra). Certeira = mais compras cedo em tokens que depois dobraram, com pelo menos `MIN_COMPRAS_CEDO` compras."""
    sel = est.setdefault("copiaSel", {}) if guardar else dict(est.get("copiaSel") or {})
    if sem in sel:
        return sel[sem]
    ant = semana_antes(sem)
    cands = []
    for w, c in (est.get("carteiras") or {}).items():
        n, bons = (c.get("s") or {}).get(ant, [0, 0])
        if n >= MIN_COMPRAS_CEDO and bons >= 1:
            cands.append((-bons, -bons / n, -n, w))
    sel[sem] = [w for *_x, w in sorted(cands)[:N_COPIAR]]
    for k in sorted(sel)[:-4]:
        del sel[k]
    return sel[sem]


def anotar_carteiras(tok, res, est):
    """Cada carteira que comprou cedo: +1 compra na semana do lançamento e +1 acerto se o token dobrou; e as marcas de
    criador (já lançou algum token visto aqui) e de bundle (comprou no bloco da criação)."""
    cart = est.setdefault("carteiras", {})
    cri = est.get("criadores") or {}
    sem = semana_de(tok["t"])
    bd = set(tok.get("bdW") or [])
    for w in tok.get("cedo") or []:
        c = cart.get(w) or {"s": {}, "cr": 0, "bd": 0}
        n, b = c["s"].get(sem, [0, 0])
        c["s"][sem] = [n + 1, b + (1 if res["x"] >= 2 else 0)]
        for k in sorted(c["s"])[:-3]:
            del c["s"][k]
        if w in bd:
            c["bd"] += 1
        if w in cri:
            c["cr"] = 1
        c["u"] = tok["t"]
        cart[w] = c
    _podar(cart, MAX_CARTEIRAS)


def resumo_carteiras(est, agora):
    sem = semana_de(agora)
    ult = {sem, semana_antes(sem)}
    sel_atual = set(selecao_copia(est, sem, guardar=False)) if est.get("carteiras") else set()
    linhas, total = [], 0
    for w, c in (est.get("carteiras") or {}).items():
        n = sum(v[0] for k, v in c["s"].items() if k in ult)
        b = sum(v[1] for k, v in c["s"].items() if k in ult)
        total += n
        if n >= 2:
            linhas.append({"carteira": curto(w), "compras": n, "acertos": b, "taxa": round(b / n, 4),
                           "criador": bool(c.get("cr")), "bundle": c.get("bd", 0) > 0, "copiando": w in sel_atual})
    linhas.sort(key=lambda x: (-x["acertos"], -x["taxa"], -x["compras"]))
    return {"semana": sem, "observadas": len(est.get("carteiras") or {}), "comprasCedo": total,
            "selecao": [curto(w) for w in sorted(sel_atual)], "carteiras": linhas[:15],
            "criadoras": sum(1 for c in (est.get("carteiras") or {}).values() if c.get("cr")),
            "bundle": sum(1 for c in (est.get("carteiras") or {}).values() if c.get("bd"))}


# ---------------------------------------------------------------------------------------------------- rodada
def analisar(amostra, fonte, cli, est, contas, ev, log, erros, restante, agora=None, sol_fonte=None):
    """Os tokens de uma amostra 24 h depois: pares, velas, classificação, a curva, os sinais de golpe, as carteiras e as
    apostas de cada versão."""
    toks = amostra["tokens"]
    agora = agora or (amostra["t"] + ESPERA)
    pares = ler_pares(fonte, [t["mint"] for t in toks], log, est, erros)
    sol_usd = amostra.get("sol") or preco_sol(cli, amostra["t"], erros) or SOL_PADRAO
    custo = custo_operacao(amostra.get("prio"), amostra.get("gorjeta"))
    migr = set(amostra.get("migr") or [])
    sol_fonte = sol_fonte or (fonte if hasattr(fonte, "solana") else None)
    freio = Freio(FALHAS_RPC)
    cri = est.setdefault("criadores", {})
    resumos, por_versao = [], {v[0]: [] for v in VERSOES}
    sete = est.setdefault("semana7", [])
    for tok in toks:
        info = pares.get(tok["mint"])
        sem_dados = False
        if info is None:
            # a DexScreener não lista boa parte dos tokens pequenos: o GeckoTerminal confirma se ninguém negociou
            info = pares_gecko(fonte, tok["mint"], log, est, erros) if restante() > 60 else None
            if info is None:
                info, sem_dados = {"pares": [], "preco": None}, True
        velas_lst = []
        amm = [p for p in info["pares"] if p[0] and p[0] != "pumpfun" and p[1]]
        curva = [p for p in info["pares"] if p[0] == "pumpfun" and p[1]]
        if amm:
            tok["tGrad"] = min((p[2] for p in amm if p[2]), default=None) or tok.get("tGrad")
        if tok["mint"] in migr and not tok.get("tGrad"):
            tok["tGrad"] = tok["t"] + HORA  # migrou enquanto ouvíamos (raro): a hora exata não vem
        faltou = False
        if curva or amm:
            for dex, end, criado in (curva[:1] + amm[:1]):
                antes = None
                if dex != "pumpfun" and tok.get("tGrad"):
                    antes = min(agora, max(tok["t"], tok["tGrad"]) + VELAS * MIN)
                vs = ler_velas(fonte, end, tok["mint"], tok["t"], log, est, erros, antes) if restante() > 60 else None
                if vs is None:
                    faltou = True
                else:
                    velas_lst.append(vs)
        velas = juntar_velas(velas_lst)
        if not tok.get("tGrad"):
            tok["tGrad"] = next((v[0] for v in velas if v[2] >= P_GRAD), None)
        tok["p24"] = info.get("preco")
        if tok["p24"] is None and not info["pares"]:
            tok["p24"] = 0.0 if velas else None
        if velas and max(v[2] for v in velas) / tok["p0"] > X_ABSURDO:
            faltou, velas = True, []  # erro de unidade (cotado em outra moeda): fica fora, sem contar como 10×
            if len(erros) < 30:
                erros.append(f"velas fora de escala em {curto(tok['mint'])}")
        res = classificar(tok, velas, faltou or sem_dados)
        res["sd"] = sem_dados
        if sem_dados:  # não se sabe o que aconteceu: nem morto, nem vivo, nem sem negócios
            res.update({"x24": None, "mo": False, "sv": False, "x": 1.0, "xs": 1.0, "c": None, "s1h": None})
        # os sinais da hora do lançamento (só nas amostras ouvidas depois de 09/11/2026)
        sg = tok.get("sg")
        if isinstance(sg, dict):
            res["sg"] = {**{k: sg.get(k) for k in ("con", "bd", "rd", "crN", "crM", "nv", "c1m")},
                         "cg": (tok.get("cr") or 0) >= CRIADOR_GRANDE, "rc": tok.get("rc")}
        # o medidor de golpe
        if isinstance(sg, dict) and not sem_dados and not faltou:
            comprou = (tok.get("cr") or 0) > 0
            # cs: os minutos de vida na checagem em que o criador já tinha vendido tudo, False (não tinha) ou None
            gl = {"q": res["gp"], "rc": None if tok.get("rc") is None else tok.get("rc") == "alto",
                  "cs": tok.get("cs") if comprou else False, "chk": tok.get("chk")}
            if not comprou:
                gl["cs24"] = False  # não comprou nada: não tem o que vender
            elif tok.get("cs") not in (None, False):
                gl["cs24"] = True
            elif tok.get("criador") and sol_fonte is not None and restante() > 60:
                gl["cs24"] = criador_vendeu(sol_fonte, freio, tok, est, log, erros)
            if res["g"]:
                liq = info.get("liqAmm")
                gl["lq"] = None if liq is None else liq < LIQ_RETIRADA * 2 * AMM_SOL * sol_usd
            else:
                gl["lq"] = False
            res["gl"] = gl
        # a graduação: quanto tempo levou e a curva depois dela
        tg = tok.get("tGrad")
        if res["g"] and tg and velas and not faltou:
            pg = pontos_grad(tg, velas, velas[-1][0])
            if pg:
                res["gr"] = {"min": round(max(0, tg - tok["t"]) / MIN, 1), "c": pg["c"]}
        # o criador: lançamento analisado, morto, dobrou
        a = tok.get("criador")
        if a and a in cri and not sem_dados:
            cri[a]["a"] = cri[a].get("a", 0) + 1
            cri[a]["m"] = cri[a].get("m", 0) + (1 if res["mo"] else 0)
            cri[a]["d"] = cri[a].get("d", 0) + (1 if res["x"] >= 2 else 0)
        # as carteiras que chegaram cedo: a regra de copiar usa a seleção da semana anterior (antes de contar esta)
        if tok.get("cedo") and not sem_dados and not faltou:
            sel = set(selecao_copia(est, semana_de(tok["t"])))
            tok["copiar"] = bool(sel & set(tok["cedo"]))
            anotar_carteiras(tok, res, est)
        # a 2ª olhada, 7 dias depois (só quem negociava em 24 h ou graduou; os mortos ficam mortos)
        if not sem_dados and not faltou and res["c"] is not None:
            par = (amm or curva or [None])[0]
            if (not res["mo"] or res["g"]) and par:
                sete.append({"mint": tok["mint"], "t": tok["t"], "p0": tok["p0"], "par": par[1],
                             "tg": tg if res.get("gr") else None, "pg": preco_em(velas, tg, P_GRAD) if res.get("gr") else None})
            else:
                res["c"][4] = 0.0  # morto em 24 h conta como morto em 7 dias
        resumos.append(res)
        if faltou or sem_dados:
            continue  # sem as velas não dá para simular as regras (nem dizer que morreu)
        golpe = eh_golpe(res)
        for v in VERSOES:
            partes = {}
            r = simular(tok, velas, v, sol_usd, custo, partes)
            if r:
                por_versao[v[0]].append((r[1], r[0], r[2], tok["mint"], r[3], golpe, partes))
    del sete[:-MAX_SEMANA7]
    # a conta de cada versão: as apostas fecham ao longo das 24 h; a curva é marcada no fim da análise da amostra
    fim = amostra["t"] + ESPERA
    for v in VERSOES:
        c = contas[v[0]]
        # as apostas de uma amostra ficam abertas ao mesmo tempo: só cabem tantas quantas o dinheiro da conta paga
        cabem = int(max(0.0, c.ultimo) // APOSTA)
        res = sorted(por_versao[v[0]], key=lambda r: r[4])[:cabem]
        if len(por_versao[v[0]]) > cabem:
            c.extra["semDinheiro"] = c.extra.get("semDinheiro", 0) + len(por_versao[v[0]]) - cabem
        for _ts, ganho, _motivo, _m, _te, _g, _p in res:
            c.operou(sum(_p.values()) * sol_usd, 2)
            c.fechou(ganho)
        total = sum(x[1] for x in res)
        c.marcar(fim, c.ultimo + total)
        x = c.extra
        x["apostas"] = x.get("apostas", 0) + len(res)
        x["ganhas"] = x.get("ganhas", 0) + sum(1 for r in res if r[1] > 0)
        x["dobrou"] = x.get("dobrou", 0) + sum(1 for r in res if r[2] == "dobrou")
        x["stop"] = x.get("stop", 0) + sum(1 for r in res if r[2] == "−50%")
        x["apostado"] = round(x.get("apostado", 0.0) + APOSTA * len(res), 2)
        x["resultado"] = round(x.get("resultado", 0.0) + total, 4)
        x["emGolpe"] = x.get("emGolpe", 0) + sum(1 for r in res if r[5])
        x["resultadoGolpe"] = round(x.get("resultadoGolpe", 0.0) + sum(r[1] for r in res if r[5]), 4)
        cu = x.setdefault("custos", {"taxa": 0.0, "rede": 0.0, "deslize": 0.0})
        for r in res:
            for k2, val in r[6].items():
                cu[k2] = round(cu.get(k2, 0.0) + val * sol_usd, 4)
        if res:
            x["melhor"] = round(max(x.get("melhor", -1e9), max(r[1] for r in res)), 2)
            x["pior"] = round(min(x.get("pior", 1e9), min(r[1] for r in res)), 2)
        x["acerto"] = round(x["ganhas"] / x["apostas"], 4) if x["apostas"] else None
        x["roi"] = round(x["resultado"] / x["apostado"], 4) if x["apostado"] else None
        x["custoPct"] = round(sum(cu.values()) / x["apostado"], 4) if x["apostado"] else None
        if v[0] == "min1" and res:
            ev.add(fim, "resumo", f"Amostra de {dia_de(amostra['t'])[8:10]}/{dia_de(amostra['t'])[5:7]} "
                                   f"({len(toks)} lançamentos): {len(res)} apostas, {sum(1 for r in res if r[1] > 0)} com lucro, "
                                   f"resultado {moeda_br(total)}.", v[0])
    c = contagens(resumos)
    ev.add(fim, "resumo", f"Dos {c['tokens']} lançamentos sorteados há 24 h: {c.get('dobraram', 0)} dobraram, "
                          f"{c.get('graduaram', 0)} se formaram, {c.get('golpes', 0)} caíram mais de 90% em minutos e "
                          f"{c.get('morreram', 0)} morreram.", None)
    if freio.motivo:
        est.setdefault("semDadosRodada", {})["rpc24h"] = freio.motivo
    return resumos, sol_usd


def olhar_7_dias(est, tokens, fonte, agora, log, erros, restante):
    """A 2ª olhada: velas de 1 h do GeckoTerminal até 7 dias depois do lançamento. Atualiza o ponto de 7 dias, a máxima
    da semana e, nos graduados, as 24 h depois da graduação."""
    sete = est.setdefault("semana7", [])
    por_chave = {(x["t"], x["m"]): x for x in tokens}
    feitos = 0
    for item in sorted(list(sete), key=lambda i: i["t"]):
        if item["t"] + ESPERA7 > agora:
            continue
        if restante() < 90:
            break
        r = por_chave.get((item["t"], curto(item["mint"])))
        if r is None:
            sete.remove(item)
            continue
        vs = ler_velas(fonte, item["par"], item["mint"], item["t"], log, est, erros,
                       antes_ms=item["t"] + ESPERA7 + HORA, escala="hour", limite=VELAS_H)
        if vs is None:
            if agora - item["t"] > DESISTIR7:
                sete.remove(item)
            continue
        sete.remove(item)
        feitos += 1
        p0 = item["p0"]
        if vs:
            fim = [v for v in vs if v[0] <= item["t"] + ESPERA7] or vs
            x7 = round(fim[-1][4] / p0, 4)
            r["xs"] = round(max(r.get("xs") or r["x"], max(v[2] for v in vs) / p0), 3)
            if item.get("tg") and isinstance(r.get("gr"), dict) and item.get("pg"):
                r["gr"]["c"][4] = round(preco_em(vs, item["tg"] + ESPERA, item["pg"]) / item["pg"], 4)
        else:
            x7 = 0.0  # o par sumiu ou ninguém negociou na semana
        if isinstance(r.get("c"), list):
            r["c"][4] = x7
    return feitos


def sinais_da_amostra(escolha, ctx, est, log, erros, agora_chk_fn):
    """Logo depois de ouvir: RugCheck, os metadados (site ou redes) e os sinais pelo RPC. O que falhar fica None e o
    motivo vai para `semDados` da saída."""
    rc_fonte = rede.fonte_de(ctx, "rugcheck")
    meta_fonte = rede.fonte_de(ctx, "metadados")
    sol_fonte = rede.fonte_de(ctx, "solana")
    fr_rpc, fr_meta = Freio(FALHAS_RPC), Freio(FALHAS_RPC)
    sem = {}
    for tok in sorted(escolha, key=lambda x: x["t"]):
        tok.setdefault("sg", {})
        if ctx.restante() < 60:
            sem["tempo"] = "o tempo da rodada acabou antes dos sinais de todos"
            break
        tok["rc"] = rugcheck(rc_fonte, tok, erros)
        tok["sg"]["rd"] = ler_metadados(meta_fonte, tok, est, log, erros, fr_meta)
        sinais_do_lancamento(tok, sol_fonte, fr_rpc, est, log, erros, agora_chk_fn())
    for tok in escolha:
        tok.pop("uri", None)  # o link dos metadados nunca é guardado
    if fr_rpc.motivo:
        sem["rpc"] = fr_rpc.motivo
    if fr_meta.motivo:
        sem["metadados"] = fr_meta.motivo
    if any(t.get("rc") is None for t in escolha):
        sem["rugcheck"] = next((e for e in erros if e.startswith("RugCheck")), "sem resposta")
    return sem


def regras_saida(contas):
    regras = []
    for v in VERSOES:
        x = contas[v[0]].extra
        regras.append({"id": v[0], "nome": v[1], "apostas": x.get("apostas", 0), "acerto": x.get("acerto"),
                       "roi": x.get("roi"), "resultado": x.get("resultado", 0.0), "melhor": x.get("melhor"),
                       "pior": x.get("pior"), "dobrou": x.get("dobrou", 0), "stop": x.get("stop", 0),
                       "emGolpe": x.get("emGolpe", 0), "resultadoGolpe": x.get("resultadoGolpe", 0.0),
                       "custoPct": x.get("custoPct"), "custos": x.get("custos")})
    return regras


def custos_saida(est):
    prios = [p for _, p in est.get("prio") or []]
    gorj = [g for _, g, _p75 in est.get("gorjetas") or []]
    g75 = [x for _, _g, x in est.get("gorjetas") or [] if x is not None]
    sol = mediana([s for _, s in est.get("solUsd") or []]) or SOL_PADRAO
    prio = mediana(prios)
    g = mediana(gorj)
    op = custo_operacao(prio, g)
    # o deslize de US$ 10 no preço do lançamento (a curva quase vazia: o pior caso da curva)
    p0 = 30.0 / (K_CURVA / 30.0)
    sol_a = APOSTA / sol
    q = comprar_curva(sol_a, p0)
    desl = 1 - q * p0 / sol_a
    return {"taxaCurva": TAXA_CURVA, "taxaAmm": TAXA_AMM, "redeBaseSol": REDE_BASE_SOL,
            "prioridade": prio, "prioridadeSol": round((prio or 0) * CU_OPERACAO / 1e15, 9),
            "gorjetaSol": g, "gorjetaP75Sol": mediana(g75), "gorjetaMedida": g is not None,
            "porOperacaoSol": round(op, 6), "porOperacaoUsd": round(op * sol, 4), "solUsd": round(sol, 2),
            "porApostaPct": round((2 * op * sol) / APOSTA + 2 * TAXA_CURVA, 4), "deslizeLancamento": round(desl, 5),
            "fontes": {k: v[1] for k, v in CUSTOS.items()}}


def rodar(ctx):
    erros = []
    est = copy.deepcopy(ctx.est)
    agora, log, cli = int(ctx.agora), ctx.log, ctx.cli
    t_inicio = time.monotonic()
    agora_real = lambda: agora + int((time.monotonic() - t_inicio) * 1000)  # noqa: E731
    fonte = rede.fonte_de(ctx, "pumpportal_ouvir")
    fontes = {id(f): (f, getattr(f, "pedidos", 0)) for f in
              (fonte, rede.fonte_de(ctx, "dexscreener"), rede.fonte_de(ctx, "gecko"), rede.fonte_de(ctx, "rugcheck"),
               rede.fonte_de(ctx, "solana"), rede.fonte_de(ctx, "jito"), rede.fonte_de(ctx, "metadados"))}
    contagem0 = {k: v for f, _p in fontes.values() for k, v in dict(getattr(f, "contagem", {}) or {}).items()}
    try:
        ev = Eventos(est.get("eventos"))
        vivo = est.setdefault("vivo", {})
        inicio = int(est.get("inicio") or agora)
        est["inicio"] = inicio
        contas = {}
        for v in VERSOES:
            c = Curva.de_json(vivo.get(v[0]))
            if c is None:
                ini = inicio if not vivo else agora  # versão nova numa conta que já existia: começa agora
                c = Curva(inicio=ini)
                c.marcar(ini, CAPITAL)
            contas[v[0]] = c
        tokens = est.setdefault("tokens", [])
        pend = est.setdefault("pendentes", [])
        est["semDadosRodada"] = {}

        # ---------------------------------------------------------------- 1. as amostras de 24 h atrás
        feitas = 0
        for am in sorted(pend, key=lambda a: a["t"]):
            if am["t"] + ESPERA > agora or feitas >= ANALISES_POR_RODADA or ctx.restante() < 120:
                continue
            try:
                resumos, sol = analisar(am, rede.fonte_de(ctx, "dexscreener"), cli, est, contas, ev, log, erros,
                                        ctx.restante, agora, rede.fonte_de(ctx, "solana"))
            except ERROS as e:
                erros.append(f"análise da amostra de {dia_de(am['t'])}: {e}")
                log(f"  memes: a amostra de {dia_de(am['t'])} fica para a próxima rodada ({e})")
                if agora - am["t"] > DESISTIR:
                    pend.remove(am)
                    ev.add(agora, "aviso", f"A amostra de {dia_de(am['t'])[8:10]}/{dia_de(am['t'])[5:7]} foi descartada: "
                                           "a DexScreener não respondeu por 3 dias.", None)
                break
            tokens.extend(resumos)
            est["nAmostras"] = int(est.get("nAmostras") or 0) + 1
            pend.remove(am)
            feitas += 1
            log(f"  memes: amostra de {dia_de(am['t'])} analisada ({len(resumos)} tokens)")
        del tokens[:-MAX_TOKENS]

        # ---------------------------------------------------------------- 1b. a olhada de 7 dias
        if est.get("semana7"):
            n7 = olhar_7_dias(est, tokens, rede.fonte_de(ctx, "gecko"), agora, log, erros, ctx.restante)
            if n7:
                log(f"  memes: {n7} tokens vistos de novo depois de 7 dias")

        # ---------------------------------------------------------------- 2. uma amostra nova
        ultima = max([a["t"] for a in pend] + [int(est.get("ultimaAmostra") or 0)])
        seg_ouvir = min(OUVIR_S, int(ctx.restante() - RESERVA_SINAIS_S))
        if agora - ultima >= CADA_AMOSTRA and seg_ouvir >= OUVIR_MIN_S:
            lanc, migr, seg = ouvir(fonte, agora, est, log, erros, seg_ouvir)
            if lanc:
                anotar_criadores(lanc, est)
                rnd = random.Random(agora)
                escolha = rnd.sample(lanc, min(AMOSTRA, len(lanc)))
                sem = sinais_da_amostra(escolha, ctx, est, log, erros, agora_real)
                if sem:
                    est["semDadosRodada"].update(sem)
                prio = taxa_prioridade(rede.fonte_de(ctx, "solana"), erros)
                g50, g75 = gorjeta_jito(rede.fonte_de(ctx, "jito"), est, log, erros)
                if g50 is None:
                    est["semDadosRodada"]["jito"] = next((e for e in erros if e.startswith("Jito")), "sem resposta")
                sol = preco_sol(cli, agora, erros)
                for tok in escolha:
                    tok.pop("uri", None)
                am = {"t": agora, "tokens": escolha, "migr": migr, "lancamentos": len(lanc), "seg": seg,
                      "sol": sol, "prio": prio, "gorjeta": g50}
                pend.append(am)
                est["ultimaAmostra"] = agora
                taxa = len(lanc) / max(1.0, seg / 60)
                est["ritmo"] = (est.get("ritmo") or [])[-29:] + [[agora, round(taxa, 2)]]
                est["porRodada"] = (est.get("porRodada") or [])[-29:] + [[agora, len(escolha), len(lanc)]]
                if prio is not None:
                    est["prio"] = (est.get("prio") or [])[-29:] + [[agora, prio]]
                if g50 is not None:
                    est["gorjetas"] = (est.get("gorjetas") or [])[-29:] + [[agora, g50, g75]]
                if sol:
                    est["solUsd"] = (est.get("solUsd") or [])[-29:] + [[agora, sol]]
                log(f"  memes: amostra nova: {len(escolha)} de {len(lanc)} lançamentos em {seg} s")
            else:
                erros.append("nenhum lançamento ouvido")

        # ---------------------------------------------------------------- saída
        for k, c in contas.items():
            vivo[k] = c.para_json()
        est["eventos"] = ev.para_json()
        semana = [x for x in tokens if x["t"] >= agora - 8 * DIA]
        regras = regras_saida(contas)
        ritmo = [r for _, r in est.get("ritmo") or []]
        prios = [p for _, p in est.get("prio") or []]
        por_rod = [n for t_r, n, _l in (est.get("porRodada") or []) if t_r >= agora - 7 * DIA]
        contagem = {}
        for f, _p in fontes.values():
            for k, v in dict(getattr(f, "contagem", {}) or {}).items():
                contagem[k] = contagem.get(k, 0) + v
        pedidos = {k: v - contagem0.get(k, 0) for k, v in contagem.items() if v - contagem0.get(k, 0) > 0}
        obs = {"tudo": contagens(tokens), "semana": contagens(semana), "desde": tokens[0]["t"] if tokens else None,
               "amostras": int(est.get("nAmostras") or 0), "esperando": sum(len(a["tokens"]) for a in pend),
               "proxima": min((a["t"] + ESPERA for a in pend), default=None), "regras": regras,
               "lancamentosPorMin": round(sorted(ritmo)[len(ritmo) // 2], 1) if ritmo else None,
               "lancamentosPorDia": round(sorted(ritmo)[len(ritmo) // 2] * 1440) if ritmo else None,
               "outrasPlataformas": int(est.get("outrasPlataformas") or 0),
               # a revisão de 09/11/2026
               "taxas": taxas_basicas(tokens), "curva": curva_tipica(tokens), "sinais": tabela_sinais(tokens),
               "graduacao": resumo_graduacao(tokens, regras), "golpe": medidor_golpe(tokens, regras),
               "cedo": resumo_carteiras(est, agora), "custos": custos_saida(est),
               "esperando7d": len(est.get("semana7") or []),
               "amostra": {"porRodada": AMOSTRA, "ouvirSegundos": OUVIR_S, "rodadasPorDia": 3,
                           "porDia": round(sum(por_rod) / 7) if por_rod else None,
                           "metodo": ("todos os lançamentos do pump.fun ouvidos em 10 min, 3 vezes por dia; acima de "
                                      f"{AMOSTRA}, sorteio simples sem reposição"),
                           "pedidos": pedidos},
               "semDados": [{"fonte": k, "motivo": v} for k, v in (est.get("semDadosRodada") or {}).items()]}
        itens = [{"mint": x["m"], "lancado": x["t"], "maxX": x["x"], "x24": x["x24"], "graduou": x["g"], "golpe": x["gp"],
                  "morreu": x["mo"], "rugcheck": x["rc"], "criadorGrande": x["cr"] >= CRIADOR_GRANDE,
                  "semDados": bool(x.get("sd")), "curva": x.get("c"), "golpeAlgum": eh_golpe(x) if not x.get("sd") else None}
                 for x in sorted(tokens, key=lambda y: -y["t"])[:MAX_ITENS]]
        versoes = [{"id": v[0], "nome": v[1], "frase": v[6], "risco": v[5], "alav": 1,
                    "grupo": "Referência" if v[4] == "segura" else "Regras",
                    "aoVivo": contas[v[0]].resumo() if contas[v[0]].serie else None, "historico": None} for v in VERSOES]
        cfg = {"frequencia": "3 vezes por dia (cada amostra é analisada 24 h depois e os vivos de novo em 7 dias)",
               "rede": "Solana", "plataforma": "pump.fun",
               "aposta": APOSTA, "amostra": AMOSTRA, "ouvirSegundos": OUVIR_S,
               "taxas": {"curva": TAXA_CURVA, "amm": TAXA_AMM, "deslizeAmm": DESLIZE_AMM, "redeSol": REDE_SOL},
               "prioridade": sorted(prios)[len(prios) // 2] if prios else None,
               "saida": {"alta": SAIDA_ALTA, "baixa": SAIDA_BAIXA, "minutos": SAIDA_MIN}, "observatorio": True,
               "amostragem": "todos os lançamentos do pump.fun numa janela de 10 min às 00h41, 08h41 e 16h41 de Brasília",
               "sinais": {"criadorGrande": CRIADOR_GRANDE, "concentrado": CONCENTRADO, "bundle": BUNDLE_MIN,
                          "carteiraNova": NOVA_TX, "minimo": MIN_SINAL},
               "copia": {"carteiras": N_COPIAR, "minCompras": MIN_COMPRAS_CEDO, "atrasoMin": COPIA_ATRASO}}
        ctx.est.clear()
        ctx.est.update(est)
        return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": "min1", "versoes": versoes,
                "eventos": est["eventos"], "itens": itens, "observatorio": obs, "avisos": AVISOS, "config": cfg,
                "erros": erros}
    finally:
        for f, p0 in fontes.values():
            rede.somar_pedidos(ctx, f, p0)
