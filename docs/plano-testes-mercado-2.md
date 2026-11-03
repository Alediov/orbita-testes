# Testes de mercado 2: as outras formas de "investimento" arriscado, no papel

Pedido do Alediov (03/11/2026): pôr na aba **Testes** das Finanças, ao lado do copy trading, outras formas
arriscadas de ganhar com cripto. **Primeiro, só no papel**: saldo fictício, sem conta real, sem dinheiro, sem chave de
negociação e sem segredo. Ideia central: tudo tem de poder ser automatizado depois. **Única exigência dele: tudo
GRATUITO** (nenhuma API paga, nenhum plano pago; chave gratuita só se for gratuita de verdade e sem cartão, e aí ele
mesmo cria a conta).

As 7 formas: **1** cofres da Hyperliquid · **2** taxa de financiamento (funding) · **3** pools de liquidez ·
**5** robôs de grade e DCA · **6** memecoins · **7** venda de opções · **8** empréstimo em cascata (looping). A 4
(apostas esportivas) ficou de fora.

Este documento é só o plano: nada foi implementado. As fontes foram testadas **de dentro do GitHub Actions** (seção
"Teste de alcance"), porque os executores ficam nos EUA e algumas APIs bloqueiam esses endereços.

---

## Resumo em uma tela

| # | Forma | Fonte gratuita testada | Teste no passado | Fidelidade do papel (0–5) | Automação real (0–5) | Fase |
|---|---|---|---|---|---|---|
| 1 | Cofres (HLP e de traders) | Hyperliquid (`stats-data …/vaults` + `vaultDetails`) ✅ | sim, grosso (30 dias com ~46 pontos; desde 2023 com ~100) | **4** | **4** | 1 |
| 2 | Funding (à vista + perpétuo) | Hyperliquid (funding de hora em hora, à vista e perpétuo) ✅; OKX, dYdX, Kraken ✅; Binance e Bybit ❌ (bloqueiam EUA) | sim (funding ~2,5 anos; velas de 1 h ~7 meses, diárias ~3 anos) | **4** sem alavancagem, **3** com | **4** | 1 |
| 5 | Robôs de grade e DCA | Hyperliquid ✅, Coinbase ✅, arquivos da Binance (`data.binance.vision`) ✅ | sim, anos | **4** | **5** | 1 |
| 8 | Looping (Aave) | API GraphQL do Aave ✅ (taxas diárias de 1 ano), RPC público da Base ✅ | sim, 1 ano (diário) | **3** | **3** | 2 |
| 7 | Venda de opções | Deribit pública ✅ (cadeia ao vivo, DVOL, liquidações, negócios antigos); OKX ✅ | aproximado (pelo índice de volatilidade); exato só daqui para frente | **3** (4 daqui para frente) | **3** | 2 |
| 3 | Pools (Uniswap na Base) | RPC público (publicnode) ✅ com cada troca do pool; GeckoTerminal ✅ (com freio) | ~30 dias (o RPC grátis não guarda mais que isso) | **4** | **3** | 3 |
| 6 | Memecoins (pump.fun) | PumpPortal (lançamentos, grátis) ✅; GeckoTerminal ✅ (com freio); DexScreener ✅; RugCheck ✅; site do pump.fun ❌ | não de verdade: só "amostra de 24 h atrás" | **1–2** | **2** | 4 |

**O que dá:** 1, 2 e 5 com o que o app já usa (a Hyperliquid), com boa fidelidade; 8 e 7 com fontes públicas boas;
3 com fidelidade alta mas só ~30 dias para trás. **O que não dá direito:** memecoins "no lançamento" (o papel não
consegue disputar o mesmo bloco com os robôs de quem lança, e os golpes acontecem em segundos); vai como
"observatório" com números honestos, não como promessa.

**O maior problema não é técnico, é o limite de minutos do Actions** (seção própria): o repositório já gasta mais do
que os 2.000 min/mês gratuitos de um repositório privado. Recomendação: um repositório **público** só para os testes de
mercado (minutos ilimitados nos executores padrão; nada sensível: só dados públicos de mercado).

---

## Teste de alcance (feito em 03/11/2026, ramo temporário `sonda-mercado`)

Um workflow num ramo órfão chamou cada fonte (só leitura, sem chave) em 3 rodadas e gravou o relatório no próprio
ramo. Executor: **EUA (Arizona, rede da Microsoft)**. O ramo (só `sonda*.py`, o workflow e os relatórios; nenhum
segredo; o workflow só roda com push nele) ainda precisa ser apagado à mão no site do GitHub (Branches → lixeira):
a sessão do Claude não tem permissão para apagar ramos.

**Responderam (200):**
- **Hyperliquid**: lista de cofres `GET stats-data.hyperliquid.xyz/Mainnet/vaults` (9.478 cofres, 3.063 abertos, 22
  com mais de US$ 1 mi; 14 MB; por cofre: nome, endereço, líder, TVL, fechado ou não, pai/filho, `apr`, `pnls` dia/
  semana/mês/tudo); `vaultDetails` (HLP: 102 pontos desde mai./2023; cofre de usuário "Growi HF": 70 pontos no total,
  58 na semana, 28 no dia; `leaderCommission` 0,1 = 10%, `leaderFraction`, `allowDeposits`, até 100 seguidores);
  `clearinghouseState` do cofre (as posições dele); `predictedFundings` (235 moedas, com o funding previsto da própria
  HL, da Binance e da Bybit: um jeito de ver as duas sem acessá-las); `fundingHistory` (ETH há 900 dias: tem);
  `spotMetaAndAssetCtxs` e velas do à vista (`@107` HYPE, `@142` UBTC, `@151` UETH, `@156` USOL…). Profundidade
  das velas: 1 dia ≥ 1.000 dias; 4 h ≥ 700 dias; 1 h ~200 dias; 15 min ~52 dias; 1 min ~3,5 dias (as 5.000 mais
  recentes). `vaultSummaries` (oficial) vem vazio: só lista cofres com menos de 2 h.
- **Funding e velas fora da HL**: OKX (`/api/v5/public/funding-rate-history`), dYdX v4 (`indexer.dydx.trade`,
  limite 100), Kraken (OHLC e funding dos futuros, um ano), Coinbase Exchange (velas), **`data-api.binance.vision`** e
  **`data.binance.vision`** (arquivos mensais, inclusive funding: o caminho para a Binance a partir dos EUA), CoinGecko
  simples sem chave.
- **Pools e Base**: RPC `base-rpc.publicnode.com` e `arbitrum-one-rpc.publicnode.com` (o da Base deu as trocas do pool
  WETH/USDC 0,05%: 258 em 500 blocos, 4.766 em 10.000 blocos; há 30 dias: sim; há 365 dias: **recusado**, "archive
  requests require a personal token"; no máximo 20.000 resultados por pedido); `PoolManager` do Uniswap v4 (3.648
  trocas de todos os pools v4 em 500 blocos, filtráveis pelo id do pool); preço do gás. DefiLlama: `yields.llama.fi/
  pools` (15.949 pools), `/chart/<pool>` (931 dias do pool WETH-USDC v3 na Base) e `/lendBorrow` grátis.
  GeckoTerminal: pool, OHLCV de hora e de minuto (minuto há 60 dias: sim).
- **Memecoins**: PumpPortal websocket `wss://pumpportal.fun/api/data` (21 lançamentos em 2 min ≈ 15 mil por dia, com
  as reservas virtuais da curva e o tamanho da compra do criador; 1 graduação em 2 min); GeckoTerminal `new_pools`
  da Solana (13 de 20 eram `pump-fun`), OHLCV de minuto e as últimas negociações (54) de um pool pump.fun de 1 min de
  idade; DexScreener (perfis e pares do token, `dexId: pumpfun`); RugCheck (`/report/summary`); RPC da Solana
  (público e publicnode); preço da Jupiter (`price/v3`).
- **Opções**: Deribit `get_book_summary_by_currency` (toda a cadeia do BTC com compra, venda, marca e IV),
  índice, **DVOL** (há 1 ano, de hora em hora), `history.deribit.com` (negócios de opções de 6 meses atrás, com IV),
  preços de liquidação (2.658 dias), e o **testnet** público; OKX `opt-summary` (1.192 opções com gregas).
- **Aave**: GraphQL `api.v3.aave.com/graphql` (mercados da Base, e **`supplyAPYHistory`/`borrowAPYHistory` com 365
  dias**, sem chave); `getReserveData` e os eventos `ReserveDataUpdated` pelo RPC (recentes).
- **Referência**: Banco Central (CDI, série 12).

**Não responderam ou exigem algo:**
- **Binance** `api.binance.com`/`fapi`: **451** ("restricted location"). **Bybit**: **403** (CloudFront bloqueia o
  país). Os dois chegam pelos arquivos da Binance e pelo `predictedFundings` da HL.
- **Site do pump.fun** (`frontend-api-v3`): 403 do Cloudflare ("Just a moment…").
- **PumpPortal, negociações por token**: o `subscribeTokenTrade` foi recusado sem chave (0 negociações em 2 min,
  só a mensagem de recusa; ao que tudo indica pede conta e é pago por mensagem). Os lançamentos continuam grátis.
- **GeckoTerminal**: limite público de 30/min, mas **o IP do Actions é dividido com outros**: de 25 pedidos a cada
  2,2 s, só 6 passaram; precisa de freio (esperar 30–60 s no 429) e de poucas chamadas por rodada. OHLCV com mais de
  **180 dias**: 401 (só no plano pago).
- **The Graph** (subgraph do Uniswap): "missing authorization header" (pede chave; o plano grátis de 100 mil
  consultas existe, mas a conta é pela carteira/cartão: dispensável, o RPC dá o mesmo).
- **DefiLlama `chartLendBorrow`** (histórico de empréstimo): **402**, pago. Substituído pelo GraphQL do Aave.
- **RPC `mainnet.base.org`**: `getLogs` com 429 ("request limit reached"); o publicnode serve.
- **Jupiter `swap/v1/quote`**: 429 e depois erro de token; não é necessário (o deslize da curva do pump.fun é conta).
- **Derive (Lyra)**: 503 na hora do teste.

Nenhuma fonte usada no plano pede cartão, conta ou chave.

---

## Como medir (a mesma régua da aba)

Cada forma produz **contas fictícias de US$ 1.000** (o mesmo das carteiras copiadas, para comparar) com a curva diária
de patrimônio, e o app usa as contas que já existem em `testes/calculo.js`: % ao mês = (1 + r)^(30/dias) − 1, ao ano
com 365, a **faixa** (média ± 1,28 × erro dos retornos diários), "medindo há N dias" (menos de 7: só o período; menos
de 30: "extrapolação"), CDI e poupança no mesmo formato, **queda do topo** e o **semáforo** (ganhando do CDI /
perdendo do CDI / ainda é cedo). Em todas: taxas, deslize e o custo de rede descontados; o resultado do "teste no
passado" fica separado do "ao vivo".

Formato comum (proposta) para o workflow gravar, um arquivo por forma no ramo `mercado` (`cofres.json`,
`funding.json`, `pools.json`, `robos.json`, `memes.json`, `opcoes.json`, `looping.json` e `indice.json` com a data e a
versão de cada um), para o app baixar só o que vai mostrar:

```
{ v, forma, agora, frase, config: {...},
  versoes: [{ id, nome, frase, risco: "baixo|médio|alto",
              aoVivo: { curva: [[dia, valor]], eventos: [...], ops, taxas, rede },
              historico: { curva, eventos, desde, ate } }],
  avisos: ["o que o papel não mostra", ...] }
```

---

## 1. Cofres da Hyperliquid (HLP e cofres de traders)

**O que é.** Você deposita dólares (USDC) num cofre e ele negocia por você. O HLP é o cofre da própria corretora (faz
mercado e liquidações); os outros são de traders, que levam 10% do lucro.

**Fonte (testada ✅).** `GET stats-data.hyperliquid.xyz/Mainnet/vaults` (todos os cofres, uma chamada, 14 MB; peso 20
na conta do balde) e `POST /info {type: "vaultDetails", vaultAddress}` (curvas de patrimônio e de lucro por dia,
semana, mês e tudo; comissão; parte do líder; se aceita depósito). `clearinghouseState` mostra as posições. Já está em
`hl.py` o cliente com o balde de peso.

**Simulação.** O depósito fictício segue o **retorno por cota** do cofre, não o patrimônio (que sobe e desce com
depósitos e saques de outros): r = Δlucro ÷ patrimônio anterior, nos pontos de `pnlHistory`/`accountValueHistory`
(a rodada a cada 2 h guarda os seus próprios pontos; "semana" tem ~58 pontos, então dá para recuperar uma rodada
perdida). Desconta a **comissão de 10% do lucro** no saque (sobre o lucro da nossa entrada), respeita a **trava**
(HLP 4 dias, cofres de traders 1 dia: não dá para sair antes) e o tamanho máximo de saque (`maxWithdrawable`). Teste
no passado: 30 dias com ~46 pontos (grosso) e "tudo" com ~70–100 pontos; avisado como aproximado.

**Escolha dos cofres** (como as carteiras): abertos, aceitando depósito, TVL ≥ US$ 100 mil, ≥ 30 dias de vida, líder
com ≥ 5% (regra da casa), lucro no mês e no total, pior queda do pico ≤ 30%, sem "filhos" do HLP (que entram pelo
HLP). Toda semana; fica pelo menos 4 semanas.

**Versões (6):** HLP sozinho · os 5 melhores pela regra, partes iguais · os 10 melhores · os 5 melhores com saída se
cair 15% do nosso topo (respeitando a trava) · cada cofre seguido como conta própria (para o ranking) · "o melhor da
semana passada" (troca toda segunda; mostra o custo de correr atrás).

**O que o papel não mostra.** O cofre pode perder tudo num dia (eventos de manipulação em que o HLP herdou posições
ruins, como o caso JELLY em março de 2025); o líder pode fechar o cofre; o saque grande sai com deslize; risco da
própria corretora e da ponte de USDC.

**Real (só descrevendo).** Conta na Hyperliquid (carteira própria, USDC pela Arbitrum), depósito e saque por API
assinados pela carteira; um robô que decide quando trocar. Nota **automação 4**, **fidelidade 4**.

## 2. Taxa de financiamento (cash-and-carry)

**O que é.** Compra a moeda no à vista e vende a mesma quantidade no perpétuo: o preço deixa de importar, e quando o
funding é positivo quem está vendido recebe a cada hora. É "aluguel" pago por quem aposta na alta.

**Fonte (testada ✅).** Hyperliquid: `fundingHistory` (de hora em hora, ~2,5 anos), velas do perpétuo e do à vista
(UBTC `@142`, UETH `@151`, USOL `@156`, HYPE `@107`), `predictedFundings` (a de agora na HL, Binance e Bybit). Para
comparar corretoras: OKX (`funding-rate-history`), dYdX (`historicalFunding`), Kraken futuros, e a Binance pelos
arquivos mensais de `data.binance.vision` (a API da Binance e a da Bybit bloqueiam os EUA).

**Simulação.** Duas pernas na HL: à vista (taxa 0,07% tomador / 0,04% ordem limite, no nível base) e perpétuo vendido
(0,045% / 0,015%), deslize pelo tamanho; **funding de hora em hora** (pode ficar negativo e custar); a diferença de
preço entre as duas pernas (base) nas velas; ao montar e desmontar, as taxas das duas. Com alavancagem: menos dinheiro
na margem do vendido → **liquidação** se a moeda subir ~1 ÷ alavancagem (o à vista ganha, mas está em outro bolso) e a
regra de reequilíbrio (vende um pouco do à vista para repor a margem quando ela cai a 60%, pagando as taxas).
Teste no passado: ~7 meses com velas de 1 h; funding mais longo.

**Versões (8):** BTC 1× (metade à vista, metade margem) · ETH 1× · HYPE 1× · BTC 3× (75% à vista, 25% margem) ·
"seletiva" (entra quando o funding médio de 3 dias passa de 10% ao ano, sai abaixo de 3%) · "rodízio" (a moeda de
funding mais alto entre as 4, troca no máximo 1× por semana, pagando a troca) · entre corretoras só com perpétuos
(comprado na HL e vendido onde o funding é maior, OKX/dYdX; só no papel, porque os dados de lá têm menos histórico) ·
seletiva 3×.

**O que o papel não mostra.** UBTC/UETH são versões "embrulhadas" (ponte): podem descolar; desalavancagem
automática (ADL) fecha o vendido nos dias loucos; fila de liquidez no à vista; risco de corretora.

**Real.** Conta na HL com uma "carteira de API" (permissão só de negociar, sem saque) num robô. **Automação 4**,
**fidelidade 4** (1×) / **3** (com alavancagem).

## 3. Pools de liquidez (Uniswap na Base, liquidez concentrada)

**O que é.** Você empresta as duas moedas (ETH e USDC) para quem troca uma pela outra e ganha uma taxa em cada troca;
numa faixa de preço estreita ganha mais, mas quando o preço sai da faixa você para de ganhar e fica "preso" na moeda
que caiu (a perda impermanente).

**Fonte (testada ✅).** O mais fiel possível e grátis: **cada troca do pool**, pelos eventos `Swap` no RPC público
`base-rpc.publicnode.com` (cada evento traz o preço, o tick e a liquidez ativa naquele instante). Pool alvo: WETH/USDC
0,05% v3 na Base (`0xd0b5…F224`, ~1.100 trocas por hora). O v4 também sai pelo `PoolManager` filtrando o id do pool.
Gás: `eth_gasPrice` + a taxa de dados da L1. GeckoTerminal (volume e preço por hora, até 180 dias) e DefiLlama
(`/chart`, APY diário desde 2023) como conferência.

**Simulação.** Posição fictícia de US$ 1.000 numa faixa: em cada troca dentro da faixa, a parte da taxa = L_nossa ÷
(L_ativa + L_nossa) × valor de entrada × 0,05%; o valor da posição pela matemática do v3 a cada preço (perda
impermanente exata); **reposicionar** custa trocar metade (0,05% + deslize) + gás de tirar, trocar e pôr (~US$ 0,01–
0,05 na Base, medido). Volume de 30 dias para trás de uma vez (~35 pedidos de 40 mil blocos; acima disso o publicnode
pede chave) e depois 1–2 pedidos por rodada.

**Versões (8):** faixa ±1%, ±3%, ±10% e cheia (como o v2) · cada uma com reposicionar "quando sai da faixa" e "só
depois de 1 h fora" (para não pagar à toa no vai e vem) · uma "sem reposicionar" de referência · comparação com "só
segurar 50/50".

**O que o papel não mostra.** Liquidez relâmpago (robôs que entram só no bloco da troca grande e pegam a taxa), o
fluxo "tóxico" (arbitradores sempre do lado certo), erro no contrato, descolamento do USDC; o nosso tamanho é pequeno
demais para mexer no pool (ok no papel).

**Real.** Carteira própria na Base com a chave num robô ligado o tempo todo (o Actions não serve para executar:
atrasa e não guarda segredo direito) ou um cofre automático de terceiros (Gamma, Arrakis, Revert), que cobra taxa.
**Automação 3**, **fidelidade 4** (30 dias de passado; daí em diante, completo).

## 5. Robôs de grade e DCA

**O que é.** Grade: ordens de compra abaixo e de venda acima do preço, em degraus; ganha no vai e vem. DCA: compra um
pouco de tempos em tempos (ou na queda), para não acertar o pior momento.

**Fonte (testada ✅).** Velas da HL (à vista e perpétuo; 1 min só 3,5 dias, 1 h ~7 meses, 1 dia ~3 anos), Coinbase
(velas de 1 min desde anos atrás, 300 por pedido) e `data.binance.vision` (arquivos de 1 min por mês: o melhor para
o passado longo, um download por mês e moeda).

**Simulação.** Velas de 1 min; dentro da vela, a ordem dos extremos pela pior hipótese para nós (abre → mínima →
máxima → fecha ou o contrário, a que nos prejudica); ordem limite só executa se o preço passar 1 tique além (fila);
taxas de ordem limite (perpétuo 0,015%, à vista 0,04%); funding no perpétuo; margem e liquidação nas versões
alavancadas (as mesmas regras do `sim.py`).

**Versões (10):** grade à vista BTC ±10% com 20 degraus · ETH ±10% · grade ±20% com recentralizar quando sai ·
grade neutra no perpétuo 1× e 3× · DCA semanal fixo (BTC) · DCA "só na queda" (≥ 5% abaixo da máxima de 7 dias) ·
DCA com ordens de segurança (a "martingale" dos robôs prontos: compra mais a cada −2%, até 5 vezes, vende com +1,5%)
1× e 3×.

**O que o papel não mostra.** Tendência forte que leva o preço para fora da grade e deixa tudo comprado no alto; na
martingale, a sequência de quedas que esgota o caixa (o papel mostra, mas pode não ter acontecido no período);
corretora fora do ar.

**Real.** A mais simples: API da HL com carteira de API; robôs prontos em corretoras também existem. **Automação 5**,
**fidelidade 4**.

## 6. Memecoins (pump.fun, Solana)

**O que é.** Comprar moedas recém-criadas por qualquer pessoa, apostando que alguma dispare. A maioria vai a zero em
minutos; muitas são feitas para o criador vender em cima de quem compra.

**Fonte (testada).** PumpPortal websocket ✅ (todos os lançamentos, grátis: ~15 mil por dia, com as reservas da curva
e a compra do criador); GeckoTerminal ✅ (velas de minuto e as últimas negociações de cada pool, mas com freio duro no
IP do Actions: ~6 pedidos seguidos e depois espera); DexScreener ✅ (preço, liquidez, pares de até 30 tokens por
pedido); RugCheck ✅ (riscos do token); RPC da Solana ✅ (taxa de prioridade). O site do pump.fun ❌ (Cloudflare) e as
negociações por token do PumpPortal ❌ (pagas).

**Simulação ("amostra de 24 h atrás", honesta, sem viés de sobrevivência).** A cada rodada: ouvir os lançamentos por
~3 min e guardar uma amostra sorteada (≈ 20–30 tokens, todos, inclusive os que morrem); 24 h depois, buscar as velas
de minuto de cada um (uma chamada por token, com o freio) e simular as regras. Entrada: preço da curva no minuto
escolhido (a curva do pump.fun é uma conta: reservas virtuais de 30 SOL e 1,073 bi de tokens, então o deslize da nossa
compra é exato); taxa de ~1,25% por lado na curva (conferir a tabela da casa na implementação; varia com o valor de
mercado) e ~0,001 SOL de rede + prioridade por operação (medida). Golpe: queda > 90% em menos de 5 min depois da
entrada, ou criador com compra inicial grande que vende (marcado e contado à parte); "morreu": sem negociações.
Token sem velas = entrou e não conseguiu sair melhor que a curva vazia (perde taxas). Tamanho: US$ 10 por token
(conta de US$ 1.000 dividida em 100 apostas).

**Versões (6):** entra no 1º minuto · no 5º minuto · "momento" (quando o valor chega a 60 SOL na curva) · "na
graduação" (quando vai para a PumpSwap) · cada uma com saída: dobrou → vende, −50% → vende, 30 min → vende · e o
filtro RugCheck (só tokens sem risco "alto").

**O que o papel não mostra (e é quase tudo).** Os robôs que compram no mesmo bloco do lançamento e vendem em cima de
você; a fila de transações em minutos de euforia; tokens que não deixam vender (fora do pump.fun); a nossa compra num
token de US$ 2 mil de valor mexe no preço. Por isso a aba mostra isto como **observatório**: "de 1.000 lançamentos,
quantos dobraram, quantos foram golpe, quanto a regra X teria dado", com o aviso de que o real tende a ser pior.

**Real.** Robô com RPC próprio e "gorjeta" de prioridade (Jito), ligado o tempo todo; o Actions não serve. Concorrência
com profissionais. **Automação 2**, **fidelidade 1–2**.

## 7. Venda de opções (Deribit)

**O que é.** Você vende a alguém o direito de comprar (call) ou vender (put) bitcoin a um preço combinado numa data e
recebe um prêmio já. Na maior parte das semanas fica com o prêmio; numa queda ou alta forte, paga a diferença.

**Fonte (testada ✅).** Deribit pública: `get_book_summary_by_currency` (toda a cadeia de BTC e ETH: compra, venda,
marca, IV), índice, **DVOL** (volatilidade implícita de 30 dias, de hora em hora, anos), `get_delivery_prices`
(preço de liquidação de cada dia desde 2019), `history.deribit.com` (negócios antigos de opções com IV). OKX
(`opt-summary`, com gregas) de reserva. **Conta de teste da Deribit (testnet)**: existe, é grátis (e-mail, sem
dinheiro) e dá chave de API; **não é necessária agora** (os dados públicos bastam e a liquidez do testnet não é real);
só seria útil numa fase de "enviar ordens de mentira", e aí ele criaria a conta e a chave viraria um segredo (fora do
que ele quer agora).

**Simulação.** Daqui para frente (fiel): toda sexta, depois das 08h UTC (vencimento semanal), vender a opção pela
**melhor oferta de compra** da cadeia guardada na rodada; marcar a mercado pela `mark_price`; no vencimento, pagar
pelo preço de liquidação; taxa de 0,03% do valor do ativo (no máximo 12,5% do prêmio) e a de entrega (0,015%). No
passado (aproximado): o preço pela fórmula de Black-Scholes com a IV = DVOL mais um ajuste de inclinação para puts
fora do dinheiro, conferido com os negócios antigos de `history.deribit.com`; avisado como "aproximação".

**Versões (8):** put coberta por dólar (cash-secured) semanal delta ~0,15 e ~0,30 · call coberta semanal delta 0,15
(com BTC comprado) · strangle coberto 0,15 (as duas, com dólar + BTC) · put mensal 0,20 · put semanal 0,15 com
recompra se o prêmio triplicar · as mesmas duas principais em ETH.

**O que o papel não mostra.** O "salto" de fim de semana; na Deribit as opções clássicas de BTC usam BTC como
garantia (a conta em dólar é uma simplificação; existem as lineares em USDC para algumas moedas); exigência de
cadastro e conferência de documentos; disponibilidade para residentes no Brasil a conferir.

**Real.** Conta verificada na Deribit (ou OKX) e chave de API num robô. **Automação 3**, **fidelidade 3** (4 daqui para
frente).

## 8. Empréstimo em cascata (looping no Aave)

**O que é.** Deposita, toma emprestado contra o depósito, deposita de novo, várias vezes: multiplica o rendimento
(e o custo do empréstimo). Se o valor da garantia cair demais em relação à dívida, o protocolo vende a garantia com
multa (liquidação).

**Fonte (testada ✅).** GraphQL do Aave `api.v3.aave.com/graphql` (sem chave): mercados, taxas atuais e
`supplyAPYHistory`/`borrowAPYHistory` diários de 1 ano por moeda e rede; parâmetros de risco (LTV, limite de
liquidação, bônus, e-mode) pelo GraphQL ou pelo `getReserveData` no RPC; preços pela HL/Coinbase (hora a hora) e a
taxa de câmbio do wstETH no RPC. (O histórico da DefiLlama de empréstimo é pago: não usado.)

**Simulação.** Diária com as taxas do dia (juros compostos dos dois lados), preço de hora em hora para o fator de
saúde (HF = garantia × limite de liquidação ÷ dívida); **liquidação** quando HF < 1 (metade da dívida, ou toda abaixo
de 0,95, com o bônus do ativo); montar o laço com empréstimo relâmpago (0,05%) ou em N voltas com troca a 0,05% +
deslize + gás da Base; regra de defesa opcional (desalavancar quando HF < 1,3).

**Versões (6):** wstETH/WETH em e-mode 3× e 6× (o rendimento do staking contra o juro do ETH; quase sem risco de
preço, o perigo é o juro passar o rendimento) · ETH de garantia → USDC → mais ETH 1,5× e 2× (aposta alavancada na
alta, com liquidação de verdade) · a de 2× com a defesa · só depositar USDC (referência sem laço).

**O que o papel não mostra.** Descolamento do wstETH, falha de oráculo, juro que dispara por horas (a média diária
esconde picos), erro de contrato, fila na liquidação.

**Real.** Carteira na Base/Arbitrum e um robô (ou serviços como DeFi Saver/Instadapp, que automatizam a defesa e
cobram). **Automação 3**, **fidelidade 3**.

---

## Minutos do Actions (o ponto mais importante)

**Limite gratuito** (docs.github.com, "How use of GitHub Actions is measured"): repositório **privado** numa conta
GitHub Free tem **US$ 12/mês de uso incluído = ~2.000 min** de Linux 2 núcleos (Pro: US$ 18 ≈ 3.000). Cada job é
cobrado arredondado para cima ao minuto. **Sem forma de pagamento cadastrada, o uso é bloqueado ao chegar no limite**
(os workflows param, inclusive o do APK). Repositório **público**: executores padrão grátis, sem limite de minutos.
O repositório `Alediov/odonto-quest` é **privado**.

**Gasto medido** (somando a duração de cada job arredondada, pela API do Actions):

| Workflow | Quando roda | Out. (17 a 31) | Nov. (1 a 3) | Estimativa por mês |
|---|---|---|---|---|
| Gerar APK (`apk.yml`) | cada push em `app/` (≈ 13 min: teste 7–8 + APK 5–6) | 1.352 | 233 | **2.300–2.700** |
| Testes de mercado (`mercado.yml`) | a cada 2 h + escolha | — | 87 | 420–780 (cálculo do .yml) |
| Eventos do Even3 (`even3.yml`) | diário | — | 41 (testes à mão) | ~90 |
| Dados do SIA (`sia.yml`) | dia 22 | 113 (1ª carga) | — | ~10 |
| Teste das etiquetas, Modelo de gêneros, Problemas de xadrez, Whisper, IBGE, OSM | push/à mão | 39 | 10 | ~20–40 |
| **Total** | | **1.504** (meio mês) | **371** (3 dias) | **≈ 2.850–3.600** |

Ou seja: **já passa dos 2.000** mesmo sem nada novo, por causa do APK. Observação: o cron do `mercado.yml` rodou só 2
vezes sozinho em ~14 h (03h28 e 11h56 UTC); o GitHub atrasa e às vezes pula horários agendados. Por isso todas as
formas abaixo "alcançam" o tempo perdido pelos históricos (como a cópia já faz) e não dependem de rodar na hora certa.

**Estimativa das formas novas:**

| Forma | O que cada rodada faz | Tempo |
|---|---|---|
| Cofres, funding, robôs, opções, looping | 1 job a cada 6 h (`papel.yml`), ~60–80 pedidos leves | ~2–3 min × 4 × 30 ≈ **300–360/mês** (+ ~5 min/semana na escolha dos cofres) |
| Pools | junto no mesmo job (1–2 `getLogs` por rodada; 1ª vez ~3 min para os 30 dias) | +0 a 1 min |
| Memecoins | job próprio (ouvir 3 min + ~25 velas com o freio do GeckoTerminal) | ~10–12 min × 2 por dia ≈ **600–720/mês** |
| **Total novo** | | **≈ 900–1.100/mês** |

**Recomendação:** criar um repositório **público** (ex.: `Alediov/orbita-mercado`) só com `tools/mercado/` e os
workflows de mercado, e mudar para lá também o `mercado.yml` de hoje. Não há nada sensível: só dados públicos de
mercado e endereços públicos de carteiras; nenhum segredo (o push no ramo usa o `GITHUB_TOKEN` automático). O app lê
o ramo `mercado` de lá **sem token** (o `contents` público, ou `raw.githubusercontent.com`). Cuidados: em
repositório público o GitHub desliga os agendamentos depois de 60 dias sem atividade (o workflow pode fazer um commit
mensal na main para manter vivo, ou ele reativa com um toque); qualquer pessoa vê o código e os resultados. Se ele não
quiser público: as formas novas precisam esperar ou o APK precisa gastar menos (ex.: não rodar o teste de fumaça
quando só muda texto), e o memecoins fica de fora.

---

## Ordem sugerida

- **Fase 0** (antes de tudo): decidir o repositório (público ou não); o formato comum de resultado (`<forma>.json` +
  `indice.json`); o seletor na aba; um `tools/mercado/papel.py` com uma "conta" genérica (curva diária, taxas, eventos)
  e o workflow `papel.yml` a cada 6 h.
- **Fase 1 — o que já usa a Hyperliquid** (`hl.py` pronto, fidelidade alta): **Cofres**, **Funding** e **Robôs de
  grade/DCA**. Cada uma com o teste no passado e o ao vivo.
- **Fase 2 — fontes novas simples**: **Looping** (GraphQL do Aave, 2–3 chamadas) e **Opções** (Deribit pública; o ao
  vivo começa a contar desde a 1ª sexta).
- **Fase 3**: **Pools** (a parte de matemática do Uniswap v3 e a leitura dos eventos; teste com um pool de mentira
  como os de `falso.py`).
- **Fase 4**: **Memecoins** como observatório (job próprio, só depois do repositório público).

Cada fase ganha o seu passo no teste de fumaça (`financas-testes-<forma>`), o exemplo de mentira em
`tools/mercado/exemplos/` (para o app sem token) e testes em `tools/mercado/teste_mercado.py` e
`tools/mercado/teste_app.mjs`.

## Como aparece na aba Testes (sem lotar)

- No alto, abaixo do aviso fixo, uma **faixa de chips roláveis**: **Placar · Copy trading · Cofres · Funding · Pools ·
  Robôs · Memecoins · Opções · Looping** (escolha guardada em `orbita.testes.forma`; deslizar troca, como nas outras
  abas). Só aparecem as formas que já têm dados.
- **Placar** (o novo começo): uma linha por forma com o jeito padrão de cada uma ("Cofres · 5 melhores: +1,8% ao
  mês · faixa −0,5% a +4% · ganhando do CDI"), ordenada pelo % ao mês, com o semáforo, o risco e "medindo há N dias";
  embaixo, CDI e poupança. Tocar abre a forma.
- **Copy trading**: exatamente o que existe hoje (as 4 abas).
- **Cada forma nova**: um cabeçalho "o que é" em 2 frases + "Como funciona" (com o "?" do glossário) e 3 partes:
  **Como está indo** (o número grande da versão padrão, a faixa, CDI/poupança, a curva × CDI × bitcoin, a queda do
  topo), **Versões** (ranking em frases, como "Jeitos de copiar") e **O que aconteceu** (linha do tempo: "vendeu a put
  de 70 mil por US$ 12", "foi liquidada", "saiu do cofre X porque…"). Nos cofres, uma 4ª, **Quais cofres** (como
  "Quem copiamos"). Nos memecoins, o observatório (quantos dobraram, golpes, mortos) no lugar do "Como está indo".
- **Início das Finanças**: o cartão continua um só ("Testes: 3 formas à frente do CDI").
- Avisos no celular: os mesmos interruptores de hoje (desligados), com uma opção por forma.

---

## Perguntas para o Alediov (só as que mudam o desenho)

1. **Repositório público só para os testes?** Os minutos gratuitos do repositório privado já acabam pelo APK; num
   público os testes rodam de graça e sem limite. Tudo ali seria público (o código e os resultados no papel, nada
   seu). *Recomendo: sim, e levar o copy trading junto.*
2. **Valor fictício inicial** de cada conta. *Recomendo: US$ 1.000 em todas (igual ao copy trading), para comparar; o
   app já converte em reais pela verba de testes.*
3. **Alavancagem máxima** nas formas que têm (funding, grade, looping). *Recomendo: até 3× no funding e na grade, e
   até 6× só no looping wstETH/ETH (que quase não tem risco de preço); nada de 10× nas formas novas.*
4. **Moedas e redes.** *Recomendo: BTC, ETH, HYPE e SOL na HL; pools e looping só na Base (gás mais barato, os dados
   funcionaram); opções só BTC e ETH.*
5. **Memecoins: observatório ou estratégia?** O papel não consegue imitar quem compra no mesmo segundo do lançamento.
   *Recomendo: observatório (os números honestos do que acontece com as moedas novas e quanto cada regra teria dado),
   e só na fase 4.*
6. **Tudo na mesma tela (seletor de chips) ou uma aba para cada?** *Recomendo: o seletor de chips com o "Placar" no
   começo; a aba Testes continua uma só.*
7. **Frequência.** *Recomendo: a cada 6 h para as formas novas (os resultados não mudam por rodar mais vezes, porque
   usam os históricos) e 2 vezes por dia para os memecoins.*
8. **Teste no passado aproximado** (opções pelo índice de volatilidade; cofres com poucos pontos): mostrar ou só o ao
   vivo? *Recomendo: mostrar, com a etiqueta "aproximado", separado do ao vivo, como hoje.*
9. **Cofres: escolher sozinho** pela regra (como as carteiras) ou **ele escolhe** alguns à mão? *Recomendo: pela
   regra, com um campo para ele fixar cofres que quiser acompanhar.*
