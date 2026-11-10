"""Pools de liquidez concentrada na Base, NO PAPEL (plano: docs/plano-testes-mercado-2.md, seção 3; formato:
tools/papel/FORMATO.md). Nenhuma carteira, nenhuma ordem, nenhuma chave: só o RPC público da Base.

A ideia: emprestar as duas moedas de um par para quem troca uma pela outra no pool e ganhar a taxa de cada troca. Numa
faixa de preço estreita a mesma quantia rende mais taxa, mas quando o preço sai da faixa a posição para de ganhar e fica
toda na moeda que caiu (a perda impermanente). Reposicionar (tirar, trocar e pôr de novo em volta do preço novo) custa
a troca e o gás e "realiza" a perda.

Desde 09/11/2026 (pedido do Alediov: de um pool para cinco), `POOLS`:

- `weth_usdc`: Uniswap v3 WETH/USDC 0,05% (o de sempre; as 10 versões e o histórico ficam como estavam);
- `cbbtc_usdc`: Uniswap v3 cbBTC/USDC (a faixa de taxa com mais trocas, escolhida na 1ª rodada pela fábrica);
- `weth_cbbtc`: Uniswap v3 WETH/cbBTC (par correlacionado; a conta é MEDIDA EM BITCOIN, convertida em dólar pelo
  preço do bitcoin no dia em que começou, como as versões wstETH do looping: mostra só o pool contra segurar bitcoin);
- `aero_weth_usdc`: Aerodrome Slipstream WETH/USDC (liquidez concentrada; cada versão em dois jeitos: "sem gauge",
  que ganha as taxas das trocas menos a parte que vai ao gauge (`unstakedFee`), e "no gauge", que NÃO ganha taxa e
  sim AERO, vendido uma vez por dia);
- `estavel`: o par de dólares estáveis com mais trocas entre USDC/USDT e EURC/USDC, no Uniswap v3 ou no Slipstream;
- `brz`: o real digital (BRZ) contra USDC só como OBSERVADOR (volume e liquidez; em 09/11/2026, todos os 28 pools do
  BRZ na Base somavam ~US$ 10 mil de volume por dia e ~US$ 100 mil de liquidez: pequeno demais para o papel; o BRLA
  não tem pool com volume na Base). Vira teste quando passar de `OBSERVADOR_VIRA` de volume por dia.

Fonte: CADA TROCA do pool, pelos eventos `Swap` no RPC público `base-rpc.publicnode.com` (o `mainnet.base.org` dá 429 no
getLogs). O Slipstream (fork do Uniswap v3) emite o MESMO evento (mesmo tópico); o PancakeSwap v3, não (tem dois campos
a mais: não é usado). Cada evento traz o preço depois da troca (`sqrtPriceX96`), a liquidez ativa e o tick. Como só as
trocas mexem no preço, o caminho do preço entre uma troca e a seguinte é conhecido, e a taxa da nossa posição sai EXATA
pela matemática do v3: numa subida de √P de a até b dentro da faixa, entra L·(b − a) do token1; numa descida,
L·(1/a − 1/b) do token0; a taxa é esse valor × taxa ÷ (1 − taxa), na moeda que entrou. Não depende da liquidez dos outros
(a nossa é pequena demais para mexer no preço). As faixas são arredondadas aos ticks do pool. Gás medido a cada rodada
(`eth_gasPrice`) × as unidades de cada operação + uma estimativa fixa da taxa de dados da L1 (`L1_US`).

Faixas pela volatilidade (pools novos): "estreita", "média" e "larga" = 1, 3 e 8 vezes a volatilidade DIÁRIA medida no
próprio pool (média exponencial dos retornos de hora em hora, meia-vida de 7 dias, `Volatilidade`), calculada na hora de
pôr ou reposicionar (a largura usada vai no `extra.largura`). O WETH/USDC continua com as faixas fixas de ±1/±3/±10%.

Emissões do Aerodrome (aproximado): o gauge paga `rewardRate` AERO por segundo, dividido entre a liquidez EM STAKE que
está ativa no preço de agora. A nossa parte numa troca = rewardRate × tempo × L ÷ (liquidez em stake ativa + L). A
liquidez em stake só é lida a cada rodada (`stakedLiquidity()` ÷ `liquidity()` = a fração em stake); entre as rodadas,
supõe-se a mesma fração da liquidez ativa de cada evento. A taxa de emissão e o preço do AERO (GeckoTerminal) também só
são lidos a cada rodada; no passado (antes da 1ª leitura) vale a primeira. Por isso as versões "no gauge" saem
`aproximado: true`.

Limites do publicnode (Teste de alcance, 03/11/2026): no máximo 20.000 eventos por pedido (o pedaço começa em 10 mil
blocos e se ajusta: erro → metade; poucos eventos → dobra até 40 mil) e nada além de ~30 dias para trás ("Archive
requests require a personal token"). Por isso o "teste no passado" são os 28 dias antes do começo e depois anda junto
com o ao vivo (as mesmas trocas); na 1ª vez leva vários minutos e, se o prazo da rodada acabar, continua na rodada
seguinte. Com vários pools, o ao vivo de todos vem primeiro e os passados se revezam (`vez`): cada rodada começa por um
pool diferente. Um pedido a cada `rede.INTERVALO["base"]` s.

Tempo: a Base faz um bloco a cada 2 s, exatos; a hora de um bloco = a do bloco de referência da rodada (`latest`) ±
2 s por bloco.

CONFERIDO (Teste de alcance): `eth_getLogs` do WETH/USDC com o tópico do Swap. CONFERIDO daqui só pelo cálculo: o
tópico do Swap e os seletores (keccak de `keccak.py`, que bate com os valores conhecidos). NÃO conferidos (a 1ª rodada de
verdade registra no log a escolha de cada pool, com os candidatos, token0/token1, taxa, espaço dos ticks, decimais e o
volume da última hora, e a 1ª leitura do gauge): os endereços dos pools candidatos (de páginas públicas: DexPaprika,
TradingStrategy, Portals, 09/11/2026), as fábricas (Uniswap v3 `UNI_FABRICA`; Slipstream `AERO_FABRICAS`), as funções
do Slipstream (`gauge()`, `stakedLiquidity()`, `unstakedFee()`, `rewardRate()`/`periodFinish()` do gauge) e o caminho
do preço do AERO no GeckoTerminal. Um candidato que não responde ou não é o par certo é ignorado; um pool sem candidato
bom fica de fora da rodada (com o erro), e os outros seguem.
"""
from __future__ import annotations

import bisect
import copy
import math

import rede
from conta import CAPITAL, DIA, FUSO_MS, HORA, Curva, Eventos, dia_de, moeda_br, num_br
from keccak import seletor, topico

try:
    import hl
    ERROS = (rede.Erro, hl.Erro)
except ImportError:  # pragma: no cover
    ERROS = (rede.Erro,)

NOME = "Pools"
VERSAO = 1  # o estado de 1 pool (antes de 09/11/2026) é levado para `pools.weth_usdc` sem recomeçar (`migrar`)

POOL = "0xd0b53D9277642d899DF5C87A3966A349A798F224"  # Uniswap v3 WETH/USDC 0,05% na Base (Teste de alcance)
WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
TOKENS = {  # símbolo → (endereço, decimais esperados; conferidos por decimals() na 1ª rodada)
    "WETH": (WETH, 18),
    "USDC": (USDC, 6),
    "cbBTC": ("0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf", 8),
    "USDT": ("0xfde4C96c8593536E31F229EA8f37b2ADa2699bb2", 6),
    "EURC": ("0x60a3E35Cc302bFA44Cb288Bc5a4F316Fdb1adb42", 6),
    "BRZ": ("0xE9185Ee218cae427aF7B9764A011bb89FeA761B4", 18),
    "AERO": ("0x940181a94A35A4569E4529A3CDfB74e38FD98631", 18),
}
UNI_FABRICA = "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"   # Uniswap v3 na Base
AERO_FABRICAS = ["0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A"]  # Slipstream (CLFactory); não conferida daqui
UNI_TAXAS = [500, 3000, 100]                                  # as faixas de taxa procuradas na fábrica do Uniswap
AERO_ESPACOS = [100, 50, 1, 200]                              # os espaços de tick procurados nas fábricas do Slipstream

TOPICO_SWAP = topico("Swap(address,address,int256,int256,uint160,uint128,int24)")
SEL_TOKEN0, SEL_TOKEN1, SEL_FEE = seletor("token0()"), seletor("token1()"), seletor("fee()")
SEL_ESPACO, SEL_DECIMAIS, SEL_SALDO = seletor("tickSpacing()"), seletor("decimals()"), seletor("balanceOf(address)")
SEL_GETPOOL_UNI, SEL_GETPOOL_AERO = seletor("getPool(address,address,uint24)"), seletor("getPool(address,address,int24)")
SEL_GAUGE, SEL_STAKED, SEL_LIQ = seletor("gauge()"), seletor("stakedLiquidity()"), seletor("liquidity()")
SEL_UNSTAKED, SEL_RATE, SEL_FIM = seletor("unstakedFee()"), seletor("rewardRate()"), seletor("periodFinish()")
ZERO = "0x" + "0" * 40

DEC0, DEC1 = 18, 6                     # WETH e USDC (o pool de sempre)
ESCALA = 10 ** ((DEC0 - DEC1) / 2)     # √P em USDC por WETH = √P cru × 10^6
Q96 = 2 ** 96
TAXA_POOL = 0.0005
ESPACO_TICK = 10
TICK_MIN, TICK_MAX = -887270, 887270
BASE_TICK = math.log(1.0001)
DESLIZE = 0.0001                       # a nossa troca de reposicionamento, num pool de dezenas de milhões
GAS_UNIDADES = 700_000                 # tirar a liquidez + coletar, trocar e pôr de novo (3 transações)
GAS_STAKE = 250_000                    # no gauge: tirar do stake e pôr de novo (a mais, em cada reposicionamento)
GAS_VENDER = 350_000                   # no gauge: coletar o AERO e vender (uma vez por dia)
CUSTO_VENDA_AERO = 0.004               # taxa + deslize da venda do AERO
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
# As regras do Canal do Marinho (vídeo "Aposentadoria sem Governo #26", pedido do Alediov, 10/11/2026; os números são os
# da transcrição: 3 a 7 dias): olham 1×/dia como a "dia" e põem as taxas de volta toda semana, mas
#   "espera3"/"espera7": só reposicionam com o preço fora há 3/7 dias E longe da faixa (perto, a meia largura da faixa
#     da borda mais próxima, deixa: o preço costuma voltar);
#   "sobra": fora há 3 dias, não troca nada: remonta a faixa, do mesmo tamanho, logo do outro lado do preço, só com a
#     moeda que sobrou (tudo ether depois de uma queda → a faixa fica logo ACIMA do preço; tudo dólar depois de uma
#     alta → logo abaixo). Paga só o gás; se o preço volta, a posição vende aos poucos e ganha a taxa no caminho.
REGRAS_MAO = ("dia", "espera3", "espera7", "sobra")
ESPERA_DIAS = {"espera3": 3, "espera7": 7, "sobra": 3}
PERTO = 0.5                            # "espera": fora, mas a menos de meia largura da borda → não mexe
FOLGA_SOBRA = 0.002                    # "sobra": a borda nova a 0,2% do preço (fora da faixa de propósito)
GAS_REINVESTIR = 0.6                   # coletar + aumentar a liquidez: ~60% do gás de um reposicionamento
PARAMS_REFAZER = 7 * DIA
AMOSTRA_BLOCOS = 1800                  # a escolha do pool compara as trocas da última hora de cada candidato
VOL_MEIA_VIDA_H = 7 * 24               # meia-vida da volatilidade medida (horas)
LARGURA_MAX = 0.5
OBSERVADOR_VIRA = 50_000               # US$ por dia: com mais que isso, o observador avisa que dá para virar teste
AMOSTRAS_GAUGE = 200
UNSTAKED_PADRAO = 100_000              # 10%: a parte da taxa de quem NÃO está no gauge que vai para o gauge (se não ler)

# (id, nome, largura da faixa (fração, None = cheia), regra, risco, frase): as versões do WETH/USDC de sempre
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
    ("esp3", "±5% · espera 3 dias fora", 0.05, "espera3", "médio",
     "Como o Marinho ensina: faixa de 5%, olha uma vez por dia e, com o preço fora, espera 3 dias antes de mexer; se o "
     "preço está perto da faixa, nem mexe. Toda semana põe as taxas de volta."),
    ("esp7", "±5% · espera 7 dias fora", 0.05, "espera7", "médio",
     "O mesmo, esperando 7 dias com o preço fora antes de reposicionar."),
    ("sobra", "±5% · remonta com o que sobrou", 0.05, "sobra", "médio",
     "Com o preço fora há 3 dias, não vende na baixa: monta a faixa de novo logo do outro lado do preço, só com a moeda "
     "que sobrou (de propósito fora da faixa). Se o preço volta, vai trocando aos poucos e ganhando a taxa."),
    ("cheia", "Faixa cheia", None, "nunca", "médio",
     "A faixa inteira, como nos pools antigos (v2): nunca sai, ganha bem menos por dólar e não precisa reposicionar."),
    ("r3fixa", "±3% sem reposicionar", 0.03, "nunca", "médio",
     "Faixa de 3% posta uma vez e deixada: quando o preço sai, para de ganhar e espera ele voltar."),
    ("segurar", "Segurar 50/50", None, "segurar", "médio",
     "Referência sem pool: metade em ether e metade em dólar, parados. Mostra quanto do resultado é só o ether."),
]

# as versões dos pools novos: (vid, nome, múltiplo da volatilidade diária (None = cheia), regra, risco, frase-base)
VERSOES_VOL = [
    ("est", "Estreita · 1 h fora", 1.0, "hora", "alto",
     "Faixa do tamanho de um dia normal de oscilação do par (hoje ±{w}); reposiciona depois de 1 hora fora."),
    ("med", "Média · 1 h fora", 3.0, "hora", "médio",
     "Faixa de 3 dias normais de oscilação (hoje ±{w}); reposiciona depois de 1 hora fora."),
    ("larga", "Larga · 1 h fora", 8.0, "hora", "médio",
     "Faixa larga, de 8 dias de oscilação (hoje ±{w}): ganha menos por dólar e sai pouco."),
    ("maoM", "Média · 1×/dia · reinveste", 3.0, "dia", "médio",
     "Como quem cuida da pool à mão: faixa média (hoje ±{w}), olha uma vez por dia e só reposiciona se estiver fora; "
     "toda semana põe as taxas de volta."),
    ("maoL", "Larga · 1×/dia · reinveste", 8.0, "dia", "médio",
     "O mesmo cuidado à mão com a faixa larga (hoje ±{w})."),
    ("esp3", "Média · espera 3 dias fora", 3.0, "espera3", "médio",
     "Como o Marinho ensina: faixa média (hoje ±{w}), olha uma vez por dia e, com o preço fora, espera 3 dias antes de "
     "mexer; perto da faixa, nem mexe. Toda semana põe as taxas de volta."),
    ("esp7", "Média · espera 7 dias fora", 3.0, "espera7", "médio",
     "O mesmo, esperando 7 dias com o preço fora (faixa de hoje ±{w})."),
    ("sobra", "Média · remonta com o que sobrou", 3.0, "sobra", "médio",
     "Fora há 3 dias, não vende na baixa: monta a faixa (hoje ±{w}) logo do outro lado do preço, só com a moeda que "
     "sobrou."),
    ("cheia", "Faixa cheia", None, "nunca", "médio",
     "A faixa inteira: nunca sai, ganha bem menos por dólar e não precisa reposicionar."),
    ("segurar", "Segurar 50/50", None, "segurar", "médio",
     "Referência sem pool: metade em cada moeda do par, paradas."),
]
NO_GAUGE = {"est", "med", "larga", "maoM", "cheia"}  # no Aerodrome, estas ganham também a versão "no gauge" (id + "g")

# os pools: id, prefixo dos ids das versões, nome, dex ("uni" | "aero"), pares [(base, cotação)] procurados, onde
# procurar, como medir a conta ("usd" | "btc"), a volatilidade diária de partida, o padrão e as notas
POOLS = [
    {"id": "weth_usdc", "prefixo": "", "nome": "WETH/USDC", "dexes": ["uni"], "pares": [("WETH", "USDC")],
     "fixo": POOL, "medida": "usd", "vol_dia": 0.03, "padrao": "r3h", "legado": True},
    {"id": "cbbtc_usdc", "prefixo": "cbu-", "nome": "cbBTC/USDC", "dexes": ["uni"], "pares": [("cbBTC", "USDC")],
     "conhecidos": [("uni", "0xfBB6Eed8e7aa03B138556eeDaF5D271A5E1e43ef"),
                    ("uni", "0xeC558e484cC9f2210714E345298fdc53B253c27D")],
     "medida": "usd", "vol_dia": 0.025, "padrao": "cbu-med"},
    {"id": "weth_cbbtc", "prefixo": "ecb-", "nome": "WETH/cbBTC", "dexes": ["uni"], "pares": [("WETH", "cbBTC")],
     "conhecidos": [("uni", "0x7AeA2E8A3843516afa07293a10Ac8E49906dabD1")],
     "medida": "btc", "vol_dia": 0.015, "padrao": "ecb-med"},
    {"id": "aero_weth_usdc", "prefixo": "aer-", "nome": "WETH/USDC", "dexes": ["aero"], "pares": [("WETH", "USDC")],
     "conhecidos": [("aero", "0xb2cc224c1c9feE385f8ad6a55b4d94E92359DC59"),
                    ("aero", "0xdbc6998296caA1652A810dc8D3BaF4A8294330f1"),
                    ("aero", "0xaAD23a67f2aC693Abbe543489aeb3F24f561d517")],
     "medida": "usd", "vol_dia": 0.03, "padrao": "aer-med", "gauge": True},
    {"id": "estavel", "prefixo": "stb-", "nome": "Dólares estáveis", "dexes": ["uni", "aero"],
     "pares": [("USDT", "USDC"), ("EURC", "USDC")],
     "conhecidos": [("aero", "0xa41Bc0AFfbA7Fd420d186b84899d7ab2aC57fcD1"),
                    ("aero", "0xD448990883E3BF9cDD8EBCa368a3EcF9d629AaF7"),
                    ("uni", "0xd56da2b74bA826f19015E6B7Dd9Dae1903E85DA1"),
                    ("aero", "0xC5e51044eB7318950B1aFb044FccFb25782C48c1"),
                    ("aero", "0xE846373C1a92B167b4E9cd5d8E4d6B1Db9E90EC7"),
                    ("uni", "0x7279c08a36333e12c3fc81747963264c100D66Fb")],
     "medida": "usd", "vol_dia": 0.0005, "padrao": "stb-med"},
    {"id": "brz", "prefixo": "brz-", "nome": "BRZ/USDC", "dexes": ["uni", "aero"], "pares": [("BRZ", "USDC")],
     "conhecidos": [("aero", "0xd43DecD5Df4BdFfd5A4cF35ca1F9557E33B7246c"),
                    ("aero", "0x8593512a08D80ce7F6ECb3Ab6c36C0bB040Ff143")],
     "medida": "usd", "vol_dia": 0.005, "observador": True},
]
NOMES_TOKEN = {"WETH": "ether", "cbBTC": "bitcoin", "USDC": "dólar", "USDT": "tether", "EURC": "euro digital",
               "BRZ": "real digital"}

FRASE = ("Empresta as duas moedas de um par para quem troca uma pela outra e ganha uma taxa de cada troca; numa faixa "
         "estreita ganha mais, mas quando o preço sai dela para de ganhar e fica na moeda que caiu.")
COMO_FUNCIONA = [
    "Num pool da rede Base, quem troca uma moeda pela outra paga uma pequena taxa (0,01% a 0,3%) para quem pôs as duas "
    "moedas lá. A posição escolhe uma faixa de preço: só ganha enquanto o preço está dentro dela, e quanto mais "
    "estreita, mais taxa por dólar.",
    "Quando o preço sobe, a posição vai vendendo a moeda que sobe; quando cai, vai comprando. Saindo da faixa, fica "
    "toda na moeda que perdeu valor: a diferença para quem só segurou as duas moedas é a perda impermanente.",
    "Reposicionar é tirar a posição, trocar para a proporção certa e pôr de novo em volta do preço novo: custa a taxa da "
    "troca e o gás das transações, e torna a perda definitiva.",
    "São cinco pools: ether × dólar (Uniswap e Aerodrome), bitcoin × dólar, ether × bitcoin (que andam juntos) e um par "
    "de dólares estáveis. Nos pools novos, a largura da faixa segue a oscilação de cada par: o que é estreito para o "
    "ether seria largo demais para dois dólares.",
    "No Aerodrome dá para escolher: deixar a posição solta e ganhar as taxas das trocas, ou pô-la no gauge e ganhar AERO "
    "(a moeda do Aerodrome) no lugar das taxas. O papel faz os dois e vende o AERO uma vez por dia.",
    "O papel usa cada troca de verdade dos pools (lidas na rede Base): a taxa e o valor da posição saem exatos pela "
    "matemática do pool, e o gás é medido a cada rodada.",
]
AVISOS = [
    "Robôs de liquidez relâmpago entram só no bloco de uma troca grande e levam boa parte da taxa dela; o papel conta a "
    "taxa como se só existissem as posições paradas.",
    "Boa parte das trocas vem de arbitradores, que trocam quando o preço do pool está atrasado em relação às corretoras: "
    "a posição ganha a taxa, mas troca no preço velho (o papel mostra isso no resultado, não em separado).",
    "O papel reposiciona exatamente na troca em que a regra manda; um robô de verdade chega alguns blocos depois.",
    "No gauge do Aerodrome, o AERO é dividido com quem mais estiver em stake; o papel só vê quanto há em stake a cada "
    "rodada e supõe o mesmo entre elas. O preço do AERO pode cair muito: o papel vende todo dia pelo preço lido na "
    "rodada.",
    "Erro no contrato, um problema na ponte da Base ou um dólar digital (USDC, USDT) descolar podem levar o dinheiro; "
    "nada disso aparece no papel.",
    "O teste no passado só vai até uns 28 dias antes do começo de cada pool: o RPC gratuito não guarda mais que isso.",
    "Pôr dinheiro na Base exige carteira própria, ponte e um pouco de ether para o gás; o papel começa com o dinheiro já "
    "lá.",
]


# ---------------------------------------------------------------------------------------------------- matemática do v3
def preco_de(s):
    """√P (token1 por token0) → P."""
    return s * s


def s_do_tick(tick):
    return math.exp(tick * BASE_TICK / 2) * ESCALA


def tick_do_s(s):
    return math.log((s / ESCALA) ** 2) / BASE_TICK


def faixa(s, largura):
    """(√Pa, √Pb) arredondados aos ticks do pool WETH/USDC: P × (1 − largura) para baixo e P × (1 + largura) para
    cima."""
    return LEGADO.faixa(s, largura)


def quantias(L, s, sa, sb):
    """(token0, token1) de uma posição de liquidez L na faixa [√Pa, √Pb] com o preço em √P = s."""
    if s <= sa:
        return L * (1 / sa - 1 / sb), 0.0
    if s >= sb:
        return 0.0, L * (sb - sa)
    return L * (1 / s - 1 / sb), L * (s - sa)


def taxa_no_trecho(L, s0, s1, sa, sb, taxa=TAXA_POOL):
    """A taxa (token0, token1) que a liquidez L na faixa ganha quando o preço anda de √P = s0 a s1 (uma troca)."""
    lo, hi = (s0, s1) if s0 < s1 else (s1, s0)
    a, b = max(lo, sa), min(hi, sb)
    if a >= b or L <= 0:
        return 0.0, 0.0
    k = taxa / (1 - taxa)
    if s1 < s0:  # preço caiu: entrou token0
        return L * (1 / a - 1 / b) * k, 0.0
    return 0.0, L * (b - a) * k


def custo_gas(gas_wei, P):
    """O gás de um reposicionamento no WETH/USDC, em US$ (P = preço do ether)."""
    return gas_wei * GAS_UNIDADES / 1e18 * P + L1_US


def _palavra(h):
    return int(h, 16) if h and h != "0x" else 0


def _assinado(v, bits=256):
    return v - (1 << bits) if v >= 1 << (bits - 1) else v


# ---------------------------------------------------------------------------------------------------- o par de um pool
class Par:
    """Os números de um pool escolhido: endereço, decimais, taxa, espaço dos ticks, a orientação (qual token é a cotação)
    e como converter para a unidade da conta. Por dentro tudo é em token1 (como a matemática do v3); `u1` leva para a
    unidade da conta (US$, ou US$ do início pelo bitcoin)."""

    def __init__(self, esc, legado=False):
        self.legado = legado
        self.endereco = esc["endereco"]
        self.dex = esc.get("dex", "uni")
        self.token0, self.token1 = esc.get("token0", WETH), esc.get("token1", USDC)
        self.sim0, self.sim1 = esc.get("sim0", "WETH"), esc.get("sim1", "USDC")
        self.base, self.cot = esc.get("base", "WETH"), esc.get("cotacao", "USDC")
        self.dec0, self.dec1 = int(esc.get("dec0", DEC0)), int(esc.get("dec1", DEC1))
        self.escala = 10 ** ((self.dec0 - self.dec1) / 2)
        self.escala_l = 10 ** ((self.dec0 + self.dec1) / 2)  # liquidez crua = L × isto
        self.fee = int(esc.get("fee", 500))
        self.espaco = int(esc.get("espaco", ESPACO_TICK))
        self.unstaked = int(esc.get("unstakedFee") or 0) if self.dex == "aero" else 0
        self.gauge = esc.get("gauge")
        self.medida = esc.get("medida", "usd")
        self.cot0 = self.cot == self.sim0      # a cotação é o token0: o preço da base = 1 / P
        self.btc_usd = lambda t: 1.0           # posto pela rodada (`ref.btc`)
        self.eth_usd = None                    # posto pela rodada (o preço do ether do WETH/USDC)
        self.deslize = DESLIZE

    # a taxa que a posição GANHA; o custo da NOSSA troca, no WETH/USDC de sempre, lê os globais (os testes os zeram)
    @property
    def taxa(self):
        return self.fee / 1e6

    @property
    def custo(self):
        """Taxa + deslize da NOSSA troca ao pôr e reposicionar."""
        return (TAXA_POOL + DESLIZE) if self.legado else self.fee / 1e6 + self.deslize

    @property
    def l1(self):
        return L1_US

    @property
    def parte_gauge(self):
        """A fração da taxa de quem NÃO está no gauge que vai para o gauge (Slipstream)."""
        return self.unstaked / 1e6

    def s_do_tick(self, tick):
        return math.exp(tick * BASE_TICK / 2) * self.escala

    def tick_do_s(self, s):
        return math.log((s / self.escala) ** 2) / BASE_TICK

    def faixa(self, s, largura):
        if largura is None:
            return self.s_do_tick(TICK_MIN), self.s_do_tick(TICK_MAX)
        P = preco_de(s)
        e = self.espaco
        ta = math.floor(self.tick_do_s(math.sqrt(P * (1 - largura))) / e) * e
        tb = math.ceil(self.tick_do_s(math.sqrt(P * (1 + largura))) / e) * e
        if tb <= ta:
            tb = ta + e
        return self.s_do_tick(max(TICK_MIN, ta)), self.s_do_tick(min(TICK_MAX, tb))

    def largura_min(self):
        return 1.0001 ** self.espaco - 1

    # ------------------------------------------------------------------ preços e unidades
    def preco_base(self, s):
        """O preço da base na cotação (ex.: US$ por ether; bitcoin por ether)."""
        P = preco_de(s)
        return 1 / P if self.cot0 else P

    def usd_cot(self, t):
        return self.btc_usd(t) if self.cot == "cbBTC" else 1.0

    def usd_t1(self, s, t):
        """US$ de 1 token1."""
        P = preco_de(s)
        return (1 / P if self.cot0 else 1.0) * self.usd_cot(t)

    def u1(self, s, pref):
        """Unidades da conta por token1: US$ (ou, medida em bitcoin, bitcoin × o preço do bitcoin do início)."""
        P = preco_de(s)
        f = 1 / P if self.cot0 else 1.0
        return f * (pref or 1.0) if self.medida == "btc" else f

    def eth(self, s, t):
        if self.legado:
            return preco_de(s)
        if self.base == "WETH":
            return self.preco_base(s) * self.usd_cot(t)
        return self.eth_usd or 3000.0

    def gas_t1(self, gas_wei, s, t, unidades=GAS_UNIDADES, fracao=1.0):
        """O gás de uma operação, em token1."""
        if self.legado and unidades == GAS_UNIDADES:
            return custo_gas(gas_wei, preco_de(s)) * fracao
        usd = (gas_wei * unidades / 1e18 * self.eth(s, t) + self.l1) * fracao
        return usd / max(1e-18, self.usd_t1(s, t))

    def texto_preco(self, s):
        p = self.preco_base(s)
        if self.cot == "cbBTC":
            return f"{num_br(p, 5)} BTC"
        return moeda_br(p, 0 if p >= 100 else 2 if p >= 0.5 else 4)

    def nome_base(self):
        return NOMES_TOKEN.get(self.base, self.base)

    def nome_cot(self):
        return NOMES_TOKEN.get(self.cot, self.cot)

    def ler_evento(self, log, ref_bloco, ref_ms):
        """Um evento Swap → (t ms, bloco, índice, √P (token1 por token0), liquidez ativa crua, volume na cotação) ou
        None."""
        try:
            d = log["data"][2:]
            if len(d) < 320:
                return None
            w = [int(d[i:i + 64], 16) for i in range(0, 320, 64)]
            b = int(log["blockNumber"], 16)
            i = int(log.get("logIndex") or "0x0", 16)
            s = w[2] / Q96 * self.escala
            if s <= 0:
                return None
            if self.cot0:
                vol = abs(_assinado(w[0])) / 10 ** self.dec0
            else:
                vol = abs(_assinado(w[1])) / 10 ** self.dec1
            return ref_ms + (b - ref_bloco) * BLOCO_MS, b, i, s, w[3], vol
        except (KeyError, TypeError, ValueError):
            return None


LEGADO = Par({"endereco": POOL, "dex": "uni", "token0": WETH, "token1": USDC, "sim0": "WETH", "sim1": "USDC",
              "base": "WETH", "cotacao": "USDC", "dec0": DEC0, "dec1": DEC1, "fee": 500, "espaco": ESPACO_TICK},
             legado=True)


def ler_evento(log, ref_bloco, ref_ms, par=None):
    """Um evento Swap do pool → (t ms, bloco, índice, √P, liquidez ativa crua, volume na cotação) ou None."""
    return (par or LEGADO).ler_evento(log, ref_bloco, ref_ms)


# ---------------------------------------------------------------------------------------------------- versões
def cfg_de(cfg):
    """A configuração de uma versão como dict (as do WETH/USDC são tuplas)."""
    if isinstance(cfg, dict):
        return cfg
    vid, nome, largura, regra, risco, frase = cfg
    return {"id": vid, "vid": vid, "nome": nome, "largura": largura, "mult": None, "regra": regra, "risco": risco,
            "frase": frase, "gauge": False}


def versoes_do_pool(spec, gauge=False):
    """As versões de um pool: as de sempre no WETH/USDC; nos novos, as faixas pela volatilidade (e, no Aerodrome com
    gauge, cada uma também "no gauge")."""
    if spec.get("legado"):
        return [cfg_de(c) for c in VERSOES]
    out = []
    for vid, nome, mult, regra, risco, frase in VERSOES_VOL:
        base = {"vid": vid, "mult": mult, "largura": None, "regra": regra, "risco": risco, "frase": frase}
        out.append({**base, "id": spec["prefixo"] + vid, "nome": nome + (" · taxas" if gauge and vid in NO_GAUGE else ""),
                    "gauge": False})
        if gauge and vid in NO_GAUGE:
            out.append({**base, "id": spec["prefixo"] + vid + "g", "vid": vid + "g", "nome": nome + " · no gauge",
                        "gauge": True,
                        "frase": frase + " No gauge do Aerodrome: não ganha a taxa das trocas e sim AERO, vendido todo dia."})
    return out


def grupo_da_versao(cfg):
    if cfg["regra"] == "segurar":
        return "Referência"
    if cfg.get("gauge"):
        return "No gauge (AERO)"
    if cfg["regra"] in ESPERA_DIAS:
        return "Espera fora (Marinho)"
    return "Reposiciona" if cfg["regra"] in ("sai", "hora") else "À mão" if cfg["regra"] == "dia" else "Parada"


# ---------------------------------------------------------------------------------------------------- conta
class Conta:
    """Uma versão: liquidez `L` na faixa [`sa`, `sb`] (√P), as taxas ainda não coletadas (`fx` token0, `fy` token1) e,
    na referência, `x`/`y` parados. Por dentro em token1; a curva na unidade da conta (`Par.u1`)."""

    def __init__(self, cfg, inicio, estado=None, par=None):
        cfg = cfg_de(cfg)
        self.cfg = cfg
        self.id, self.nome, self.largura, self.regra = cfg["id"], cfg["nome"], cfg["largura"], cfg["regra"]
        self.risco, self.frase, self.mult, self.gauge = cfg["risco"], cfg["frase"], cfg.get("mult"), bool(cfg.get("gauge"))
        self.par = par or LEGADO
        e = estado or {}
        self.curva = Curva.de_json(e.get("curva")) or Curva(inicio=inicio)
        self.L, self.sa, self.sb = float(e.get("L", 0.0)), float(e.get("sa", 0.0)), float(e.get("sb", 0.0))
        self.fx, self.fy = float(e.get("fx", 0.0)), float(e.get("fy", 0.0))
        self.x, self.y = float(e.get("x", 0.0)), float(e.get("y", 0.0))
        self.dep = e.get("dep")          # [token0, token1] logo depois de pôr (para a perda impermanente)
        self.montada = bool(e.get("montada"))
        self.fora = e.get("fora")        # desde quando o preço está fora (ms) ou None
        self.t = int(e.get("t") or inicio)
        self.marca = int(e.get("marca") or 0)
        self.s = e.get("s")              # último √P visto
        a = e.get("acc") or {}
        self.acc = {k: float(a.get(k, 0.0)) for k in ("taxas", "gas", "repos", "pi", "dentro", "total", "diaRepos",
                                                       "reinv", "aero", "aeroUS")}
        self.dia = e.get("dia")          # o dia (índice, Brasília) da última troca, para o resumo dos reposicionamentos
        self.aviso_fora = bool(e.get("avisoFora"))
        self.olhou = e.get("olhou")      # "dia": o último dia (índice, Brasília) em que conferiu
        self.reinvestiu = e.get("reinvestiu")  # "dia": o dia da última vez que pôs as taxas de volta
        self.w = e.get("w")              # a largura usada na faixa de agora (pools novos)
        self.aero = float(e.get("aero", 0.0))  # AERO ganho e ainda não vendido
        self.pref = e.get("pref")        # medida em bitcoin: o preço do bitcoin quando a conta começou
        self._aero_info = None
        self._gas = None

    def para_json(self):
        return {"curva": self.curva.para_json(), "L": self.L, "sa": self.sa, "sb": self.sb, "fx": self.fx, "fy": self.fy,
                "x": self.x, "y": self.y, "dep": self.dep, "montada": self.montada, "fora": self.fora, "t": self.t,
                "marca": self.marca, "s": self.s, "acc": self.acc, "dia": self.dia, "avisoFora": self.aviso_fora,
                "olhou": self.olhou, "reinvestiu": self.reinvestiu, "w": self.w, "aero": self.aero, "pref": self.pref}

    def _ev(self, ev, t, tipo, texto):
        if ev is not None:
            ev.add(t, tipo, texto, self.id)

    def dentro(self, s):
        return self.sa <= s <= self.sb

    def tokens(self, s):
        """(token0, token1) da posição sem as taxas."""
        if self.regra == "segurar":
            return self.x, self.y
        return quantias(self.L, s, self.sa, self.sb)

    def u1(self, s):
        return self.par.u1(s, self.pref)

    def valor(self, s):
        """O patrimônio na unidade da conta (sem o AERO não vendido)."""
        x, y = self.tokens(s)
        P = preco_de(s)
        return ((x + self.fx) * P + y + self.fy) * self.u1(s)

    def perda_imp(self, s):
        """A perda impermanente da posição de agora (unidade da conta, ≤ 0): o valor sem as taxas × segurar o que foi
        posto."""
        if not self.dep or self.regra == "segurar":
            return 0.0
        x, y = self.tokens(s)
        P = preco_de(s)
        return ((x * P + y) - (self.dep[0] * P + self.dep[1])) * self.u1(s)

    def _gas_t1(self, gas_wei, s, t, fracao=1.0):
        un = GAS_UNIDADES + (GAS_STAKE if self.gauge else 0)
        return self.par.gas_t1(gas_wei, s, t, un, fracao)

    def _largura(self, sigma):
        if self.mult is None:
            return self.largura
        sg = sigma if sigma and sigma > 0 else 0.0
        return max(self.par.largura_min(), min(LARGURA_MAX, self.mult * sg))

    # ------------------------------------------------------------------ pôr e reposicionar
    def _por(self, s, X, Y, gas_t1, sigma=None):
        """Põe a posição em volta de √P = s com X token0 e Y token1 (as taxas já somadas), trocando o que precisa.
        Devolve o custo (troca + deslize + gás, em token1)."""
        P = preco_de(s)
        V = X * P + Y
        gas = gas_t1
        c = self.par.custo
        if self.regra == "segurar":
            alvo = (V - gas) / 2
            troca = abs(alvo - X * P)
            custo = gas + troca * c
            sobra = V - custo
            self.x, self.y = sobra / 2 / P, sobra / 2
            return custo
        largura = self._largura(sigma)
        self.w = largura
        self.sa, self.sb = self.par.faixa(s, largura)
        x1, y1 = quantias(1.0, s, self.sa, self.sb)
        u = x1 * P + y1
        # comprando token0 (X < L·x1) ou vendendo (X > L·x1): o custo da troca sai do que vai para a posição
        L = (V - gas + c * X * P) / (u + c * x1 * P)
        if X > L * x1:
            L = (V - gas - c * X * P) / (u - c * x1 * P)
        L = max(0.0, L)
        self.L = L
        self.fx = self.fy = 0.0
        x, y = quantias(L, s, self.sa, self.sb)
        self.dep = [x, y]
        return V - (x * P + y)

    def montar(self, t, s, gas_wei, ev, sigma=None):
        if self.par.medida == "btc" and not self.pref:
            self.pref = self.par.btc_usd(t)
        V = self.curva.ultimo if self.curva.ultimo > 0 else CAPITAL
        gas = self._gas_t1(gas_wei, s, t)
        u1 = self.u1(s)
        custo = self._por(s, 0.0, V / u1, gas, sigma)
        self.curva.operou(custo * u1, 1)
        self.acc["gas"] += gas * u1
        self.montada = True
        txt = self.par.texto_preco(s)
        pa = self.par
        if self.regra == "segurar":
            self._ev(ev, t, "abriu", f"Guardou metade em {pa.nome_base()} (a {txt}) e metade em {pa.nome_cot()} "
                                     f"(custou {moeda_br(custo * u1)}).")
        elif self.largura is None and self.mult is None:
            self._ev(ev, t, "abriu", f"Pôs {moeda_br(V - custo * u1)} no pool na faixa cheia, com o {pa.nome_base()} a "
                                     f"{txt} (custou {moeda_br(custo * u1)}).")
        else:
            lo, hi = self.faixa_precos()
            self._ev(ev, t, "abriu", f"Pôs {moeda_br(V - custo * u1)} no pool na faixa de {self._txt(lo)} a "
                                     f"{self._txt(hi)}{' (no gauge)' if self.gauge else ''} (custou {moeda_br(custo * u1)}).")

    def _txt(self, p):
        if self.par.cot == "cbBTC":
            return f"{num_br(p, 5)} BTC"
        return moeda_br(p, 0 if p >= 100 else 2 if p >= 0.5 else 4)

    def faixa_precos(self):
        """[mín., máx.] do preço da base na cotação."""
        a, b = preco_de(self.sa), preco_de(self.sb)
        return (1 / b, 1 / a) if self.par.cot0 else (a, b)

    def reposicionar(self, t, s, gas_wei, sigma=None):
        x, y = self.tokens(s)
        u1 = self.u1(s)
        self.acc["pi"] += self.perda_imp(s)
        gas = self._gas_t1(gas_wei, s, t)
        custo = self._por(s, x + self.fx, y + self.fy, gas, sigma)
        self.curva.operou(custo * u1, 1)
        self.acc["gas"] += gas * u1
        self.acc["repos"] += 1
        self.acc["diaRepos"] += 1
        self.fora = None

    def perto(self, s):
        """Fora da faixa, mas a menos de meia largura (em preço) da borda mais próxima."""
        if self.sa <= 0 or self.sb <= 0:
            return False
        meia = (self.sb / self.sa) ** PERTO            # em √P: meia largura da faixa, multiplicativa
        return (s < self.sa and s * meia >= self.sa) or (s > self.sb and s <= self.sb * meia)

    def remontar_sobra(self, t, s, gas_wei, ev=None):
        """"sobra": a faixa do mesmo tamanho logo do outro lado do preço, só com a moeda que a posição tem (sem troca).
        As taxas da outra moeda ficam guardadas (não coletadas)."""
        x, y = self.tokens(s)
        u1 = self.u1(s)
        P = preco_de(s)
        razao = self.sb / self.sa if self.sa > 0 else (1.05 ** 0.5) / (0.95 ** 0.5)
        gas = self._gas_t1(gas_wei, s, t)
        self.acc["pi"] += self.perda_imp(s)
        k = (1 + FOLGA_SOBRA) ** 0.5
        if s < self.sa:      # tudo na moeda 0: a faixa logo acima do preço
            X = x + self.fx - gas / P
            if X <= 0:
                return
            self.sa = s * k
            self.sb = self.sa * razao
            self.L = X / (1 / self.sa - 1 / self.sb)
            self.fx = 0.0
        else:                # tudo na moeda 1: a faixa logo abaixo do preço
            Y = y + self.fy - gas
            if Y <= 0:
                return
            self.sb = s / k
            self.sa = self.sb / razao
            self.L = Y / (self.sb - self.sa)
            self.fy = 0.0
        self.dep = list(quantias(self.L, s, self.sa, self.sb))
        self.curva.operou(gas * u1, 1)
        self.acc["gas"] += gas * u1
        self.acc["repos"] += 1
        self.acc["diaRepos"] += 1
        self.fora = t
        lo, hi = self.faixa_precos()
        self._ev(ev, t, "reequilibrou", f"Fora havia {ESPERA_DIAS['sobra']} dias: remontou sem vender, na faixa de "
                                        f"{self._txt(lo)} a {self._txt(hi)}, só com o que sobrou.")

    def reinvestir(self, t, s, gas_wei):
        """Põe as taxas não coletadas de volta na posição, na MESMA faixa (coleta, troca o que precisa e aumenta a
        liquidez). Não faz nada se as taxas não pagam pelo menos 5 vezes o gás."""
        P = preco_de(s)
        Vf = self.fx * P + self.fy
        gas = self._gas_t1(gas_wei, s, t, GAS_REINVESTIR)
        if Vf < 5 * gas:
            return False
        x1, y1 = quantias(1.0, s, self.sa, self.sb)
        u = x1 * P + y1
        if u <= 0:
            return False
        c = self.par.custo
        L = (Vf - gas) / u
        L = max(0.0, (Vf - gas - c * abs(self.fx * P - L * x1 * P)) / u)
        x, y = quantias(L, s, self.sa, self.sb)
        self.L += L
        self.fx = self.fy = 0.0
        if self.dep:
            self.dep = [self.dep[0] + x, self.dep[1] + y]
        u1 = self.u1(s)
        self.curva.operou((Vf - (x * P + y)) * u1, 1)
        self.acc["gas"] += gas * u1
        self.acc["reinv"] += 1
        return True

    def olhar(self, t, s, gas_wei, ev, sigma=None):
        """"dia": a olhada do dia (na 1ª troca depois de HORA_CONFERIR, Brasília)."""
        d = (t + FUSO_MS) // DIA
        if self.olhou == d or (t + FUSO_MS) % DIA < HORA_CONFERIR * HORA:
            return
        self.olhou = d
        if not self.dentro(s):
            espera = ESPERA_DIAS.get(self.regra, 0) * DIA
            if self.fora is None:
                self.fora = t
            if self.regra == "dia":
                self.reposicionar(t, s, gas_wei, sigma)
            elif t - self.fora >= espera:
                if self.regra == "sobra":
                    self.remontar_sobra(t, s, gas_wei, ev)
                elif not self.perto(s):
                    self.reposicionar(t, s, gas_wei, sigma)
        if self.reinvestiu is None:
            self.reinvestiu = d
        elif d - self.reinvestiu >= REINVESTIR_DIAS:
            if self.reinvestir(t, s, gas_wei):
                self._ev(ev, t, "reequilibrou", f"Pôs de volta na posição as taxas da semana (até agora "
                                                f"{moeda_br(self.acc['taxas'])} ganhos no total).")
            self.reinvestiu = d

    def vender_aero(self, t, s, gas_wei):
        """No gauge: vende o AERO acumulado (uma vez por dia), se pagar pelo menos 5 vezes o gás."""
        info = self._aero_info
        if not self.gauge or self.aero <= 0 or not info or not info[2]:
            return
        usd = self.aero * info[2] * (1 - CUSTO_VENDA_AERO)
        gas_usd = gas_wei * GAS_VENDER / 1e18 * self.par.eth(s, t) + self.par.l1
        if usd < 5 * gas_usd:
            return
        t1 = (usd - gas_usd) / max(1e-18, self.par.usd_t1(s, t))
        self.fy += t1
        u1 = self.u1(s)
        self.acc["aeroUS"] += t1 * u1
        self.acc["gas"] += gas_usd / max(1e-18, self.par.usd_t1(s, t)) * u1
        self.curva.operou((self.aero * info[2] * CUSTO_VENDA_AERO + gas_usd) / max(1e-18, self.par.usd_t1(s, t)) * u1, 1)
        self.aero = 0.0

    # ------------------------------------------------------------------ cada troca
    def troca(self, t, s0, s1, gas_wei, ev=None, sigma=None, liq=None, aero=None):
        """O preço andou de √P = s0 (a troca anterior, ou None) para s1 no instante t. `sigma` = a volatilidade diária
        do pool; `liq` = a liquidez ativa crua no trecho; `aero` = (AERO por segundo, fração em stake, preço do AERO)."""
        self._aero_info = aero if aero else self._aero_info
        self._gas = gas_wei
        if not self.montada:
            self.montar(t, s1, gas_wei, ev, sigma)
            if self.regra in REGRAS_MAO:
                self.olhou = (t + FUSO_MS) // DIA  # pôr a posição conta como a olhada do dia
            self.t, self.s, self.marca = t, s1, t
            self.curva.marcar(t, self.valor(s1))
            return
        dia = (t + FUSO_MS) // DIA
        if self.dia is not None and dia != self.dia:
            self._fechar_dia(t, ev, s1, gas_wei)
        self.dia = dia
        if self.regra != "segurar":
            dt_ms = max(0, t - self.t)
            self.acc["total"] += dt_ms
            dentro_antes = self.s is not None and self.dentro(self.s)
            if dentro_antes:
                self.acc["dentro"] += dt_ms
                if self.gauge and aero and liq and aero[1] is not None and dt_ms:
                    rate, frac, _p = aero
                    Lr = self.L * self.par.escala_l
                    den = frac * liq + Lr
                    if den > 0 and rate > 0:
                        ganho = rate * dt_ms / 1000 * Lr / den
                        self.aero += ganho
                        self.acc["aero"] += ganho
            if s0 is not None and not self.gauge:
                fx, fy = taxa_no_trecho(self.L, s0, s1, self.sa, self.sb, self.par.taxa)
                if fx or fy:
                    k = 1 - self.par.parte_gauge
                    fx, fy = fx * k, fy * k
                    self.fx += fx
                    self.fy += fy
                    self.acc["taxas"] += (fx * preco_de(s1) + fy) * self.u1(s1)
            if self.dentro(s1):
                self.fora = None
                if self.aviso_fora:
                    self.aviso_fora = False
                    if self.regra == "nunca":
                        self._ev(ev, t, "entrou", f"O {self.par.nome_base()} voltou à faixa ({self.par.texto_preco(s1)}): "
                                                  f"voltou a ganhar a taxa.")
            else:
                if self.fora is None:
                    self.fora = t
                if self.regra == "sai" or (self.regra == "hora" and t - self.fora >= FORA_ESPERA):
                    self.reposicionar(t, s1, gas_wei, sigma)
                elif self.regra == "nunca" and (self.largura is not None or self.mult is not None) \
                        and not self.aviso_fora and t - self.fora >= FORA_ESPERA:
                    self.aviso_fora = True
                    sobe = self.par.preco_base(s1) > self.faixa_precos()[1]
                    lado = "acima" if sobe else "abaixo"
                    moeda = self.par.nome_cot() if sobe else self.par.nome_base()
                    self._ev(ev, t, "saiu", f"O {self.par.nome_base()} ficou {lado} da faixa por 1 hora "
                                            f"({self.par.texto_preco(s1)}): a posição parou de ganhar e está toda em {moeda}.")
            if self.regra in REGRAS_MAO:
                self.olhar(t, s1, gas_wei, ev, sigma)
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

    def _fechar_dia(self, t, ev, s=None, gas_wei=None):
        if self.gauge and s is not None:
            self.vender_aero(t, s, gas_wei if gas_wei is not None else (self._gas or GAS_PADRAO))
        n = int(self.acc["diaRepos"])
        if n and ev is not None:
            d = dia_de(t - 1)
            ganho = (f"já ganhou {moeda_br(self.acc['aeroUS'])} em AERO vendido" if self.gauge else
                     f"já ganhou {moeda_br(self.acc['taxas'])} de taxa")
            self._ev(ev, t - 1, "reequilibrou", f"Reposicionou {n} {'vez' if n == 1 else 'vezes'} em {d[8:10]}/{d[5:7]}: "
                                                f"{ganho} e a perda impermanente realizada soma {moeda_br(self.acc['pi'])}.")
        self.acc["diaRepos"] = 0

    def _extra(self):
        s = self.s
        if s is None:
            return
        x, y = self.tokens(s)
        P = preco_de(s)
        u1 = self.u1(s)
        no0, no1 = (x + self.fx) * P * u1, (y + self.fy) * u1
        nab, nac = (no1, no0) if self.par.cot0 else (no0, no1)
        tot = self.acc["total"]
        e = {"taxasGanhas": round(self.acc["taxas"], 4), "gasPago": round(self.acc["gas"], 4),
             "reposicoes": int(self.acc["repos"]), "reinvestimentos": int(self.acc.get("reinv", 0)),
             "preco": round(self.par.preco_base(s), 8 if self.par.cot == "cbBTC" else 6 if self.par.preco_base(s) < 10 else 2),
             "naBase": round(nab, 2), "naCotacao": round(nac, 2)}
        if self.par.legado:
            e.update({"precoEth": round(P, 2), "noEther": round(no0, 2), "noDolar": round(no1, 2)})
        if self.regra != "segurar":
            e["perdaImp"] = round(self.acc["pi"] + self.perda_imp(s), 4)
            e["dentro"] = self.dentro(s)
            e["dentroFrac"] = round(self.acc["dentro"] / tot, 4) if tot > 0 else None
            if self.largura is not None or self.mult is not None:
                lo, hi = self.faixa_precos()
                casas = 8 if self.par.cot == "cbBTC" else 6 if hi < 10 else 2
                e["faixa"] = [round(lo, casas), round(hi, casas)]
            if self.mult is not None and self.w is not None:
                e["largura"] = round(self.w, 6)
        if self.gauge:
            info = self._aero_info
            e["aeroGanho"] = round(self.acc["aero"], 4)
            e["aeroVendido"] = round(self.acc["aeroUS"], 4)
            e["aeroParado"] = round(self.aero * (info[2] if info and info[2] else 0.0), 4)
        if self.par.medida == "btc" and self.pref:
            btc = self.par.btc_usd(self.t)
            e["precoRef"] = round(self.pref, 2)
            e["emDolar"] = round(self.valor(s) / self.pref * btc, 2)
        self.curva.extra = e


# ---------------------------------------------------------------------------------------------------- volatilidade
class Volatilidade:
    """A volatilidade diária do preço, pela média exponencial dos quadrados dos retornos de hora em hora (meia-vida de
    `VOL_MEIA_VIDA_H` horas); começa na de partida do pool."""

    LAMBDA = 0.5 ** (1 / VOL_MEIA_VIDA_H)

    def __init__(self, padrao, estado=None):
        e = estado or {}
        self.var = float(e.get("var") or (padrao ** 2 / 24))
        self.h = e.get("h")
        self.sh = e.get("sh")

    def para_json(self):
        return {"var": self.var, "h": self.h, "sh": self.sh}

    def ver(self, t, s):
        h = t // HORA
        if self.h is None:
            self.h, self.sh = h, s
            return
        if h != self.h:
            if self.sh and s > 0:
                r = 2 * math.log(s / self.sh)
                self.var = self.LAMBDA * self.var + (1 - self.LAMBDA) * r * r
            self.h, self.sh = h, s

    def dia(self):
        return math.sqrt(max(0.0, self.var) * 24)


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


def ler_trocas(rpc, de, ate, ref, estado_pedaco, tempo, log, par=None):
    """Gera (bloco final lido, [trocas]) em pedaços de blocos, do bloco `de` ao `ate`, enquanto `tempo()` deixar. O
    tamanho do pedaço se ajusta (`estado_pedaco["n"]`). Levanta Arquivo se o RPC recusar blocos antigos."""
    par = par or LEGADO
    a = de
    while a <= ate:
        if not tempo():
            return
        n = int(estado_pedaco.get("n") or PEDACO_INI)
        b = min(ate, a + n - 1)
        try:
            logs = rpc("eth_getLogs", [{"address": par.endereco, "topics": [TOPICO_SWAP], "fromBlock": hex(a),
                                        "toBlock": hex(b)}])
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
        trocas = [x for x in (par.ler_evento(g, *ref) for g in logs) if x]
        trocas.sort(key=lambda x: (x[1], x[2]))
        if len(logs) < MAX_EVENTOS_PEDIDO * 0.3 and n < PEDACO_MAX:
            teto = estado_pedaco.get("teto")
            estado_pedaco["n"] = max(n, min(PEDACO_MAX, n * 2, teto * 3 // 4 if teto else PEDACO_MAX))
        elif len(logs) > MAX_EVENTOS_PEDIDO * 0.8:
            estado_pedaco["n"] = max(PEDACO_MIN, n // 2)
        yield b, trocas
        a = b + 1


class Grupo:
    """As versões de um pool que andam juntas pelas mesmas trocas: "vivo" ou "hist". `s` é o último √P do grupo,
    `bloco` o último bloco lido, `liq` a liquidez ativa crua da última troca e `vol` a volatilidade medida."""

    def __init__(self, nome, inicio, estado=None, versoes=None, par=None, vol_dia=0.03):
        e = estado or {}
        self.nome = nome
        self.par = par or LEGADO
        self.bloco = int(e.get("bloco") or 0)
        self.s = e.get("s")
        self.liq = e.get("liq")
        self.inicio = int(e.get("inicio") or inicio)
        cfgs = versoes if versoes is not None else [cfg_de(c) for c in VERSOES]
        self.contas = {c["id"]: Conta(c, self.inicio, (e.get("contas") or {}).get(c["id"]), self.par) for c in cfgs}
        self.trocas = int(e.get("trocas") or 0)
        self.vol = Volatilidade(vol_dia, e.get("vol"))
        self.aero = None  # função t → (AERO/s, fração em stake, preço) ou None

    def para_json(self):
        return {"bloco": self.bloco, "s": self.s, "liq": self.liq, "inicio": self.inicio, "trocas": self.trocas,
                "vol": self.vol.para_json(), "contas": {k: c.para_json() for k, c in self.contas.items()}}

    def alimentar(self, trocas, gas_wei, ev=None):
        cs = list(self.contas.values())
        aero_fn = self.aero
        for t, _b, _i, s, liq, _v in trocas:
            s0 = self.s
            self.vol.ver(t, s)
            sig = self.vol.dia()
            ae = aero_fn(t) if aero_fn else None
            for c in cs:
                c.troca(t, s0, s, gas_wei, ev, sig, self.liq, ae)
            self.s = s
            self.liq = liq
            self.trocas += 1

    def fechar(self, t):
        """No fim de um pedaço: marca as curvas até `t` (o preço continua o da última troca)."""
        for c in self.contas.values():
            if c.montada:
                c.marcar(max(c.t, t), agenda=False)

    def pulo(self):
        """Blocos que não deu para ler: o caminho do preço se perde (nenhuma taxa até a próxima troca)."""
        self.s = None
        self.liq = None


def gas_mediano(est):
    xs = sorted(v for _, v in est.get("gas") or [] if v)
    return xs[len(xs) // 2] if xs else GAS_PADRAO


# ---------------------------------------------------------------------------------------------------- contratos
def _end(a):
    return a[2:].lower().rjust(64, "0")


def _uint(v):
    return f"{v % (1 << 256):064x}"


def _chamar(rpc, para, dados):
    return rpc("eth_call", [{"to": para, "data": dados}, "latest"])


def _ler_int(rpc, para, sel, assinado=False):
    r = _chamar(rpc, para, sel)
    v = _palavra(str(r)[:66]) if r else 0
    return _assinado(v) if assinado else v


def _ler_end(rpc, para, sel):
    r = _chamar(rpc, para, sel)
    if not r or len(str(r)) < 42:
        return None
    return "0x" + str(r)[-40:]


def conferir_pool(rpc, est, agora, log, erros):
    """token0() e fee() do WETH/USDC (uma vez por semana): o código supõe token0 = WETH e taxa de 0,05%."""
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


def decimais_de(rpc, sim, est, log):
    """Os decimais de um token (lidos uma vez; avisa se não forem os esperados)."""
    dec = est.setdefault("decimais", {})
    if sim in dec:
        return dec[sim]
    end, esperado = TOKENS[sim]
    try:
        d = _ler_int(rpc, end, SEL_DECIMAIS)
        if not 0 < d <= 36:
            raise rede.Erro(f"decimals() = {d}")
    except ERROS as e:
        log(f"  pools: decimals() de {sim} falhou ({e}); usando {esperado}")
        return esperado
    if d != esperado:
        log(f"  pools: {sim} tem {d} decimais (o código esperava {esperado}); usando {d}")
    dec[sim] = d
    return d


def candidatos(rpc, spec, log):
    """Os endereços candidatos de um pool: pela fábrica (Uniswap: cada taxa; Slipstream: cada espaço) e os conhecidos.
    Devolve [(dex, endereço, de onde)] sem repetir."""
    vistos, out = set(), []

    def por(dex, end, origem):
        if end and end.lower() != ZERO and end.lower() not in vistos:
            vistos.add(end.lower())
            out.append((dex, end, origem))

    for base, cot in spec["pares"]:
        a, b = TOKENS[base][0], TOKENS[cot][0]
        if "uni" in spec["dexes"]:
            for f in UNI_TAXAS:
                try:
                    por("uni", _ler_end(rpc, UNI_FABRICA, SEL_GETPOOL_UNI + _end(a) + _end(b) + _uint(f)), f"fábrica {f}")
                except ERROS as e:
                    log(f"  pools: fábrica do Uniswap ({base}/{cot} {f}): {str(e)[:100]}")
        if "aero" in spec["dexes"]:
            for fab in AERO_FABRICAS:
                for esp in AERO_ESPACOS:
                    try:
                        por("aero", _ler_end(rpc, fab, SEL_GETPOOL_AERO + _end(a) + _end(b) + _uint(esp)),
                            f"fábrica do Slipstream, espaço {esp}")
                    except ERROS as e:
                        log(f"  pools: fábrica do Slipstream ({base}/{cot} {esp}): {str(e)[:100]}")
                        break
    for dex, end in spec.get("conhecidos") or []:
        por(dex, end, "conhecido")
    return out


def examinar(rpc, dex, end, spec, est, topo, ref, log):
    """Lê um candidato: tokens, taxa, espaço, gauge e as trocas da última hora. Devolve a escolha (dict) ou None."""
    t0, t1 = _ler_end(rpc, end, SEL_TOKEN0), _ler_end(rpc, end, SEL_TOKEN1)
    if not t0 or not t1:
        return None
    sims = {TOKENS[k][0].lower(): k for k in TOKENS}
    s0, s1 = sims.get(t0.lower()), sims.get(t1.lower())
    par_ok = next(((b, c) for b, c in spec["pares"] if {b, c} == {s0, s1}), None)
    if not par_ok:
        log(f"  pools: {end} não é {spec['nome']} (token0 {t0}, token1 {t1})")
        return None
    fee = _ler_int(rpc, end, SEL_FEE)
    try:
        esp = _ler_int(rpc, end, SEL_ESPACO, assinado=True)
    except ERROS:
        esp = {100: 1, 500: 10, 3000: 60, 10000: 200}.get(fee, 10)
    esc = {"endereco": end, "dex": dex, "token0": t0, "token1": t1, "sim0": s0, "sim1": s1, "base": par_ok[0],
           "cotacao": par_ok[1], "dec0": decimais_de(rpc, s0, est, log), "dec1": decimais_de(rpc, s1, est, log),
           "fee": fee, "espaco": esp, "medida": spec["medida"]}
    if dex == "aero":
        try:
            g = _ler_end(rpc, end, SEL_GAUGE)
            esc["gauge"] = g if g and g.lower() != ZERO else None
        except ERROS:
            esc["gauge"] = None
        try:
            esc["unstakedFee"] = _ler_int(rpc, end, SEL_UNSTAKED)
        except ERROS:
            esc["unstakedFee"] = None
    par = Par(esc)
    logs = rpc("eth_getLogs", [{"address": end, "topics": [TOPICO_SWAP], "fromBlock": hex(topo - AMOSTRA_BLOCOS),
                                "toBlock": hex(topo)}]) or []
    tr = [x for x in (par.ler_evento(g, *ref) for g in logs) if x]
    esc["trocasHora"] = len(tr)
    esc["volumeHora"] = round(sum(x[5] for x in tr), 6)
    return esc


def escolher(rpc, spec, est, st, topo, ref, agora, log):
    """Escolhe o pool de `spec` (uma vez): entre os candidatos que são o par certo, o de maior volume na última hora (no
    Aerodrome com gauge, só os que têm gauge, se houver algum). A escolha fica para sempre (`st["escolha"]`)."""
    vistos = []
    for dex, end, origem in candidatos(rpc, spec, log):
        try:
            esc = examinar(rpc, dex, end, spec, est, topo, ref, log)
        except ERROS as e:
            log(f"  pools: candidato {end} ({origem}) não respondeu: {str(e)[:100]}")
            continue
        if esc:
            esc["origem"] = origem
            vistos.append(esc)
    com_trocas = [e for e in vistos if e["volumeHora"] > 0]
    if spec.get("gauge") and any(e.get("gauge") for e in com_trocas):
        com_trocas = [e for e in com_trocas if e.get("gauge")]
    if not com_trocas:
        raise rede.Erro(f"{spec['nome']}: nenhum candidato com trocas na última hora ({len(vistos)} conferidos)")
    melhor = max(com_trocas, key=lambda e: e["volumeHora"])
    melhor["em"] = agora
    melhor["candidatos"] = [{"endereco": e["endereco"], "dex": e["dex"], "fee": e["fee"], "espaco": e["espaco"],
                             "par": f"{e['base']}/{e['cotacao']}", "trocasHora": e["trocasHora"],
                             "volumeHora": e["volumeHora"], "gauge": e.get("gauge")} for e in vistos]
    st["escolha"] = melhor
    log(f"  pools: {spec['id']}: escolhido {melhor['endereco']} ({melhor['dex']}, {melhor['base']}/{melhor['cotacao']}, "
        f"taxa {melhor['fee']}, espaço {melhor['espaco']}, token0 {melhor['sim0']}, decimais {melhor['dec0']}/{melhor['dec1']}, "
        f"{melhor['trocasHora']} trocas na última hora, gauge {melhor.get('gauge')}, unstakedFee {melhor.get('unstakedFee')}); "
        f"candidatos: {[(c['endereco'][:10], c['dex'], c['fee'], c['trocasHora']) for c in melhor['candidatos']]}")
    return melhor


def reconferir(rpc, st, agora, log):
    """Uma vez por semana: o pool escolhido ainda tem os mesmos tokens (e a taxa de agora, que no Slipstream pode
    mudar)."""
    esc = st["escolha"]
    if agora - int(st.get("conferido") or esc.get("em") or 0) < PARAMS_REFAZER:
        return
    t0 = _ler_end(rpc, esc["endereco"], SEL_TOKEN0)
    if not t0 or t0.lower() != esc["token0"].lower():
        raise rede.Erro(f"o pool {esc['endereco']} não é o esperado (token0 {t0})")
    fee = _ler_int(rpc, esc["endereco"], SEL_FEE)
    if fee and fee != esc["fee"]:
        log(f"  pools: a taxa do {esc['endereco']} mudou de {esc['fee']} para {fee}")
        esc["fee"] = fee
    st["conferido"] = agora


def ler_gauge(rpc, fonte_gecko, st, par, agora, log, erros):
    """Uma amostra do gauge do Aerodrome: AERO por segundo, a fração da liquidez ativa em stake, o preço do AERO e a
    parte da taxa de quem está fora do gauge. Guarda em `st["amostras"]`."""
    esc = st["escolha"]
    g = esc.get("gauge")
    if not g:
        return
    amostra = {"em": agora}
    try:
        rate = _ler_int(rpc, g, SEL_RATE) / 1e18
        fim = _ler_int(rpc, g, SEL_FIM)
        if fim and fim * 1000 < agora:
            rate = 0.0
        staked = _ler_int(rpc, esc["endereco"], SEL_STAKED)
        liq = _ler_int(rpc, esc["endereco"], SEL_LIQ)
        amostra.update({"rate": rate, "frac": (staked / liq) if liq else None, "fim": fim})
        try:
            uf = _ler_int(rpc, esc["endereco"], SEL_UNSTAKED)
            esc["unstakedFee"] = uf
            par.unstaked = uf
        except ERROS:
            pass
        try:
            fee = _ler_int(rpc, esc["endereco"], SEL_FEE)
            if fee:
                esc["fee"] = par.fee = fee
        except ERROS:
            pass
        if not st.get("gaugeVisto"):
            log(f"  pools: gauge {g}: rewardRate {rate} AERO/s, periodFinish {fim}, stakedLiquidity {staked}, "
                f"liquidity {liq}, unstakedFee {esc.get('unstakedFee')}, fee {esc.get('fee')}")
            st["gaugeVisto"] = True
    except ERROS as e:
        erros.append(f"gauge de {esc['endereco'][:10]}: {e}")
        log(f"  pools: gauge: {e}")
        return
    preco = None
    if hasattr(fonte_gecko, "gecko"):
        try:
            r = fonte_gecko.gecko(f"/networks/base/tokens/{TOKENS['AERO'][0].lower()}") or {}
            at = ((r.get("data") or {}).get("attributes")) or {}
            if not st.get("aeroVisto"):
                log(f"  pools: formato do preço do AERO no GeckoTerminal: {rede.estrutura(at, 2)}")
                st["aeroVisto"] = True
            preco = float(at["price_usd"]) if at.get("price_usd") is not None else None
        except (ERROS + (ValueError, TypeError, KeyError)) as e:
            erros.append(f"preço do AERO: {e}")
    if preco is None:
        ant = [a for a in st.get("amostras") or [] if a.get("preco")]
        preco = ant[-1]["preco"] if ant else None
    amostra["preco"] = preco
    st["amostras"] = ((st.get("amostras") or []) + [amostra])[-AMOSTRAS_GAUGE:]


def funcao_aero(st):
    """t → (AERO/s, fração em stake, preço do AERO) pela última amostra antes de t (ou a primeira)."""
    am = [a for a in st.get("amostras") or [] if a.get("frac") is not None]
    if not am:
        return None
    ts = [a["em"] for a in am]

    def f(t):
        i = bisect.bisect_right(ts, t) - 1
        a = am[max(0, i)]
        return (a["rate"], a["frac"], a.get("preco"))
    return f


def saldos(rpc, par, st, log, erros):
    """O que o pool guarda de cada token (balanceOf), para a liquidez em US$."""
    try:
        b0 = _ler_int(rpc, par.token0, SEL_SALDO + _end(par.endereco)) / 10 ** par.dec0
        b1 = _ler_int(rpc, par.token1, SEL_SALDO + _end(par.endereco)) / 10 ** par.dec1
        st["saldos"] = [b0, b1]
    except ERROS as e:
        erros.append(f"saldos de {par.endereco[:10]}: {e}")


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


def volume_24h(st, agora):
    v = st.get("volume") or {}
    return sum(x for h, x in v.items() if agora - 24 * HORA <= int(h) < agora)


def trocas_24h(st, agora):
    v = st.get("nTrocas") or {}
    return sum(x for h, x in v.items() if agora - 24 * HORA <= int(h) < agora)


def migrar(est):
    """O estado de antes de 09/11/2026 (um pool só, no alto do estado) vai para `pools.weth_usdc`, sem recomeçar."""
    if "pools" in est:
        return
    p = {}
    for k in ("vivo", "hist", "pedaco", "volume", "pool", "gecko"):
        if k in est:
            p[k] = est.pop(k)
    est["pools"] = {"weth_usdc": p} if p else {}


def btc_de(ref):
    """t → preço do bitcoin (US$) pelo fechamento do dia em `ref.btc` (o último antes, ou o primeiro)."""
    serie = sorted((ref or {}).get("btc", {}).items())
    if not serie:
        return None
    dias = [d for d, _ in serie]

    def f(t):
        i = bisect.bisect_right(dias, dia_de(t)) - 1
        return float(serie[max(0, i)][1])
    return f


# ---------------------------------------------------------------------------------------------------- rodada
def par_de(spec, st, btc, eth_usd):
    """O Par de um pool novo já escolhido, com o preço do bitcoin e do ether da rodada."""
    par = Par(st["escolha"])
    if spec["medida"] == "btc" or par.cot == "cbBTC":
        if btc is None:
            raise rede.Erro("sem o preço do bitcoin (ref.btc) para medir a conta")
        par.btc_usd = btc
    par.eth_usd = eth_usd
    return par


class Corrida:
    """Um pool numa rodada: o par, os grupos e as leituras."""

    def __init__(self, spec, st, par, agora, topo):
        self.spec, self.st, self.par = spec, st, par
        self.observador = bool(spec.get("observador"))
        gauge = bool(par.dex == "aero" and par.gauge) and not self.observador
        self.versoes = [] if self.observador else versoes_do_pool(spec, gauge)
        self.pedaco = st.setdefault("pedaco", {"n": PEDACO_INI})
        self.vol_st = st.setdefault("volume", {})
        self.n_st = st.setdefault("nTrocas", {})
        novo = "vivo" not in st
        vd = spec["vol_dia"]
        self.vivo = Grupo("vivo", agora, st.get("vivo"), self.versoes, par, vd)
        self.hist = Grupo("hist", agora - HIST_DIAS * DIA, st.get("hist"), self.versoes, par, vd)
        self.novas = [] if (novo or self.observador) else [
            c["id"] for c in self.versoes if c["id"] not in ((st.get("hist") or {}).get("contas") or {})]
        self.reiniciou = bool(self.novas)
        if self.novas:
            # uma versão nova não tem passado: o teste no passado recomeça para todas, 28 dias antes de agora
            self.hist = Grupo("hist", agora - HIST_DIAS * DIA, None, self.versoes, par, vd)
            self.hist.bloco = topo - HIST_DIAS * BLOCOS_DIA
        if novo:
            self.vivo.bloco = topo - INICIO_BLOCOS
            self.hist.bloco = topo - HIST_DIAS * BLOCOS_DIA
            if self.observador:
                self.vivo.bloco = topo - BLOCOS_DIA  # o observador começa com as últimas 24 h
        self.novo = novo
        af = funcao_aero(st) if gauge else None
        self.vivo.aero = self.hist.aero = af

    def guardar(self):
        self.st["vivo"] = self.vivo.para_json()
        if not self.observador:
            self.st["hist"] = self.hist.para_json()


def rodar(ctx):
    erros = []
    est = copy.deepcopy(ctx.est)
    migrar(est)
    agora, log = int(ctx.agora), ctx.log
    fonte = rede.fonte_de(ctx, "rpc")
    gecko = rede.fonte_de(ctx, "gecko")
    p0 = getattr(fonte, "pedidos", 0)
    rpc = fonte.rpc
    btc = btc_de(getattr(ctx, "ref", None))
    try:
        ref = referencia(rpc)
        topo = ref[0]
        pst = est.setdefault("pools", {})
        conferir_pool(rpc, pst.setdefault("weth_usdc", {}), agora, log, erros)
        try:
            g = int(rpc("eth_gasPrice", []), 16)
            est["gas"] = (est.get("gas") or [])[-(GAS_GUARDAR - 1):] + [[agora, g]]
        except (ERROS + (TypeError, ValueError)) as e:
            erros.append(f"preço do gás: {e}")
        gas_wei = gas_mediano(est)
        ev = Eventos(est.get("eventos"))

        def tempo():
            return ctx.restante() > RESERVA_S

        # ---------------------------------------------------------------- os pools (escolha e ao vivo)
        corridas = []
        eth_usd = None
        for spec in POOLS:
            st = pst.setdefault(spec["id"], {})
            cor = None
            try:
                if spec.get("legado"):
                    par = LEGADO
                else:
                    if not st.get("escolha"):
                        if not tempo():
                            continue
                        escolher(rpc, spec, est, st, topo, ref, agora, log)
                    else:
                        reconferir(rpc, st, agora, log)
                    par = par_de(spec, st, btc, eth_usd)
                    if par.dex == "aero" and par.gauge and not spec.get("observador"):
                        ler_gauge(rpc, gecko, st, par, agora, log, erros)
                cor = Corrida(spec, st, par, agora, topo)
                if cor.novas:
                    log(f"  pools: {spec['id']}: versões novas ({', '.join(cor.novas)}); o teste no passado recomeça "
                        f"28 dias antes de agora")
                if cor.novo:
                    log(f"  pools: {spec['id']}: começando; " + (
                        "só observado (o volume e a liquidez das últimas 24 h)" if cor.observador else
                        f"o teste no passado lê {HIST_DIAS} dias de trocas (blocos {cor.hist.bloco} a {topo})"))
                ao_vivo(cor, rpc, topo, ref, gas_wei, ev, tempo, log, erros)
                saldos(rpc, par, st, log, erros)
                if spec["id"] == "weth_usdc" and cor.vivo.s:
                    eth_usd = preco_de(cor.vivo.s)
                corridas.append(cor)
            except ERROS as e:
                if spec.get("legado"):
                    raise
                erros.append(f"{spec['id']}: {e}")
                log(f"  pools: {spec['id']} não andou nesta rodada: {e}")
                # o que já existe continua na saída (parado na rodada anterior)
                if cor is None and st.get("escolha") and st.get("vivo"):
                    try:
                        cor = Corrida(spec, st, par_de(spec, st, btc, eth_usd), agora, topo)
                    except ERROS:
                        cor = None
                if cor is not None and cor not in corridas:
                    corridas.append(cor)
        if eth_usd:
            for cor in corridas:
                cor.par.eth_usd = eth_usd

        # ---------------------------------------------------------------- os passados, revezando qual começa
        com_passado = [c for c in corridas if not c.observador]
        if com_passado:
            vez = int(est.get("vez") or 0) % len(com_passado)
            est["vez"] = vez + 1
            for cor in com_passado[vez:] + com_passado[:vez]:
                passado(cor, rpc, ref, gas_wei, tempo, log)

        gk = conferencia_gecko(gecko, pst["weth_usdc"], agora, log, erros)
        for cor in corridas:
            cor.guardar()
            corte = str(((agora - VOL_HORAS * HORA) // HORA) * HORA)
            for d in (cor.vol_st, cor.n_st):
                for h in [h for h in d if int(h) < int(corte)]:
                    del d[h]
        # ---------------------------------------------------------------- saída
        est["eventos"] = ev.para_json()
        saida = montar_saida(corridas, est, agora, gas_wei, gk, btc, erros)
        ctx.est.clear()
        ctx.est.update(est)
        return saida
    finally:
        rede.somar_pedidos(ctx, fonte, p0)


def avancar(cor, grupos, de, ate, rpc, ref, gas_wei, ev, tempo, log):
    """Lê [de, ate] do pool e alimenta os grupos; devolve o último bloco lido."""
    ult = de - 1
    for b, trocas in ler_trocas(rpc, de, ate, ref, cor.pedaco, tempo, log, cor.par):
        for gr in grupos:
            gr.alimentar(trocas, gas_wei, ev if gr.nome == "vivo" else None)
            gr.bloco = b
            gr.fechar(ref[1] + (b - ref[0]) * BLOCO_MS)
        if any(gr.nome == "vivo" for gr in grupos):  # o volume só pelos blocos novos (o passado já passou por eles)
            for t, _b, _i, _s, _l, v in trocas:
                h = str((t // HORA) * HORA)
                cor.vol_st[h] = cor.vol_st.get(h, 0.0) + v
                cor.n_st[h] = cor.n_st.get(h, 0) + 1
        ult = b
    return ult


def ao_vivo(cor, rpc, topo, ref, gas_wei, ev, tempo, log, erros):
    vivo, hist = cor.vivo, cor.hist
    juntos = [vivo] + ([hist] if hist.bloco == vivo.bloco and not cor.observador else [])
    if vivo.bloco >= topo:
        return
    try:
        if vivo.bloco < topo - (HIST_DIAS + 1) * BLOCOS_DIA:
            pulo = topo - HIST_DIAS * BLOCOS_DIA
            log(f"  pools: {cor.spec['id']}: o ao vivo ficou para trás demais; pulando para o bloco {pulo}")
            erros.append(f"{cor.spec['id']}: ao vivo ficou mais de 28 dias para trás: blocos pulados")
            for gr in juntos:
                gr.bloco = pulo
                gr.pulo()
        avancar(cor, juntos, vivo.bloco + 1, topo, rpc, ref, gas_wei, ev, tempo, log)
    except Arquivo as e:
        erros.append(f"{cor.spec['id']}: ao vivo: {e}")
        raise rede.Erro(f"o RPC recusou os blocos do ao vivo: {e}") from None


def passado(cor, rpc, ref, gas_wei, tempo, log):
    vivo, hist = cor.vivo, cor.hist
    if hist.bloco >= vivo.bloco:
        return
    while hist.bloco < vivo.bloco and tempo():
        try:
            avancar(cor, [hist], hist.bloco + 1, vivo.bloco, rpc, ref, gas_wei, None, tempo, log)
            break
        except Arquivo as e:
            pulo = hist.bloco + BLOCOS_DIA
            log(f"  pools: {cor.spec['id']}: o RPC recusou blocos antigos ({str(e)[:100]}); o teste no passado começa "
                f"1 dia depois")
            hist.bloco = pulo
            hist.pulo()
        except ERROS as e:
            log(f"  pools: {cor.spec['id']}: o passado parou nesta rodada ({str(e)[:100]})")
            break
    falta = vivo.bloco - hist.bloco
    if falta > 0:
        log(f"  pools: {cor.spec['id']}: o teste no passado continua na próxima rodada (faltam {falta} blocos, "
            f"~{falta / BLOCOS_DIA:.1f} dias)")
    else:
        log(f"  pools: {cor.spec['id']}: o teste no passado alcançou o ao vivo")


def _usd_base(cor, t):
    """US$ por unidade da base agora."""
    s = cor.vivo.s
    if not s:
        return None
    return cor.par.preco_base(s) * cor.par.usd_cot(t)


def resumo_pool(cor, agora, btc):
    """O resumo de um pool para a tabela de comparação do app (`pools[]`)."""
    spec, par, st = cor.spec, cor.par, cor.st
    usd_cot = par.usd_cot(agora)
    vol = volume_24h(st, agora) * usd_cot
    tvl = None
    sal = st.get("saldos")
    ub = _usd_base(cor, agora)
    if sal and ub is not None:
        b0, b1 = sal
        nb, nc = (b1, b0) if par.cot0 else (b0, b1)
        tvl = nb * ub + nc * usd_cot
    giro = (vol / tvl) if tvl else None
    esc = st.get("escolha") or {}
    out = {"id": spec["id"], "nome": spec["nome"], "par": f"{par.base}/{par.cot}",
           "dex": "Aerodrome" if par.dex == "aero" else "Uniswap",
           "protocolo": "Aerodrome Slipstream" if par.dex == "aero" else "Uniswap v3", "endereco": par.endereco,
           "taxa": par.taxa, "espacoTick": par.espaco, "medida": spec["medida"],
           "padrao": None if cor.observador else spec["padrao"], "versoes": [c["id"] for c in cor.versoes],
           "observador": cor.observador, "preco": round(par.preco_base(cor.vivo.s), 8) if cor.vivo.s else None,
           "volume24h": round(vol, 0), "trocas24h": int(trocas_24h(st, agora)), "tvl": round(tvl, 0) if tvl else None,
           "giro": round(giro, 4) if giro is not None else None,
           "rendTaxaDia": round(giro * par.taxa * (1 - par.parte_gauge), 6) if giro is not None else None,
           "aprTaxas": round(giro * par.taxa * (1 - par.parte_gauge) * 365, 4) if giro is not None else None,
           "volDia": round(cor.vivo.vol.dia(), 6),
           "escolha": {"em": esc.get("em"), "origem": esc.get("origem"), "candidatos": esc.get("candidatos")} if esc else None}
    if not cor.observador:
        alc = cor.hist.bloco >= cor.vivo.bloco
        out["passado"] = {"alcancou": alc, "faltamDias": round(max(0, cor.vivo.bloco - cor.hist.bloco) / BLOCOS_DIA, 1)}
        out["trocasLidas"] = {"vivo": cor.vivo.trocas, "hist": cor.hist.trocas}
        out["larguras"] = {c["vid"]: round(max(par.largura_min(), min(LARGURA_MAX, c["mult"] * cor.vivo.vol.dia())), 6)
                           for c in cor.versoes if c.get("mult")}
    if par.dex == "aero":
        out["parteGauge"] = par.parte_gauge
        am = [a for a in st.get("amostras") or [] if a.get("frac") is not None]
        if par.gauge and am and not cor.observador:
            a = am[-1]
            aero_dia = a["rate"] * 86400
            g = {"endereco": par.gauge, "aeroDia": round(aero_dia, 2), "precoAero": a.get("preco"),
                 "fracStake": round(a["frac"], 4), "amostras": len(am), "aproximado": True}
            if a.get("preco") and tvl:
                staked_usd = tvl * a["frac"]
                g["aprEmissoes"] = round(aero_dia * a["preco"] * 365 / staked_usd, 4) if staked_usd > 0 else None
            out["gauge"] = g
    if cor.observador:
        out["nota"] = ("Já tem volume para virar teste." if vol >= OBSERVADOR_VIRA else
                       "Pouco volume e pouca liquidez: só observado (o papel não simula uma posição num pool deste "
                       "tamanho).")
    if spec["medida"] == "btc":
        out["nota"] = ("Medido em bitcoin: a conta é convertida em dólar pelo preço do bitcoin no dia em que começou, para "
                       "mostrar só o pool contra segurar bitcoin.")
    return out


def montar_saida(corridas, est, agora, gas_wei, gk, btc, erros):
    versoes, pools_out = [], []
    vivo_weth = None
    for cor in corridas:
        pools_out.append(resumo_pool(cor, agora, btc))
        if cor.observador:
            continue
        if cor.spec["id"] == "weth_usdc":
            vivo_weth = cor
        alc = cor.hist.bloco >= cor.vivo.bloco
        larg = cor.vivo.vol.dia()
        for cfg in cor.versoes:
            cv, ch = cor.vivo.contas[cfg["id"]], cor.hist.contas[cfg["id"]]
            aprox = bool(cfg.get("gauge"))
            hres = None
            if ch.montada and ch.curva.serie:
                hres = ch.curva.resumo(de=dia_de(cor.hist.inicio), ate=dia_de(ch.t), aproximado=aprox,
                                       nota=(f"Desde {HIST_DIAS} dias antes do começo, troca a troca como o ao vivo"
                                             + ("; o AERO e a parte em stake do passado são estimados" if aprox else "")
                                             + ("" if alc else "; ainda lendo o passado (continua nas próximas rodadas)")
                                             + "."))
            frase = cfg["frase"]
            if "{w}" in frase:
                w = max(cor.par.largura_min(), min(LARGURA_MAX, (cfg["mult"] or 0) * larg))
                frase = frase.replace("{w}", num_br(w * 100, 2 if w < 0.01 else 1) + "%")
            av = None
            if cv.montada:
                av = cv.curva.resumo(**({"aproximado": True} if aprox else {}))
            versoes.append({"id": cfg["id"], "nome": cfg["nome"], "frase": frase, "risco": cfg["risco"], "alav": 1,
                            "pool": cor.spec["id"], "grupo": grupo_da_versao(cfg), "aoVivo": av, "historico": hres})
    nosso = pools_out[0] if pools_out and pools_out[0]["id"] == "weth_usdc" else None
    s = vivo_weth.vivo.s if vivo_weth else None
    cfg_saida = {"frequencia": "a cada 6 h (troca a troca)", "rede": "Base", "protocolo": "Uniswap v3", "pool": POOL,
                 "par": "WETH/USDC", "taxaPool": TAXA_POOL, "precoEth": round(preco_de(s), 2) if s else None,
                 "gasWei": gas_wei, "custoReposicionar": round(custo_gas(gas_wei, preco_de(s)) if s else 0.0, 4),
                 "trocasLidas": nosso["trocasLidas"] if nosso else None,
                 "passado": nosso["passado"] if nosso else None,
                 "volume24h": nosso["volume24h"] if nosso else None,
                 "conferencia": {"fonte": "GeckoTerminal", "volume24h": gk.get("volume24h"), "tvl": gk.get("tvl")}
                 if gk.get("em") else None,
                 "pools": len([p for p in pools_out if not p["observador"]])}
    return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": "r3h", "versoes": versoes, "pools": pools_out,
            "eventos": est["eventos"], "itens": [], "avisos": AVISOS, "config": cfg_saida, "erros": erros}
