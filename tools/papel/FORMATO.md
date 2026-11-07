# Formato dos resultados das outras formas (ramo `papel`)

O workflow `papel.yml` roda `tools/papel/papel.py` a cada 6 h e grava, num commit único do ramo órfão `papel`:

- `indice.json`: o que existe e quando cada forma rodou (o app lê primeiro e só baixa a forma que mudou);
- `<forma>.json`: um por forma (`cofres.json`, `funding.json`, `robos.json`, `apostas.json`, `looping.json`,
  `opcoes.json`, `pools.json`; e `memes.json`, gravado pelo job próprio `memes.yml`, 2 vezes por dia, no mesmo ramo);
- `estado.json`: o que a próxima rodada precisa (o app não lê);
- `log.txt`: as últimas rodadas.

Tudo em US$ fictícios. **Toda conta começa com US$ 1.000** (`CAPITAL` em `conta.py`), como no copy trading, para
comparar. Datas: `ms` = milissegundos UTC; `dia` = "AAAA-MM-DD" no horário de Brasília (`conta.dia_de`, o mesmo do
`sim.py` e do app).

## indice.json

```json
{
  "v": 1,
  "agora": 1762180000000,
  "formas": {
    "cofres":  { "arquivo": "cofres.json",  "agora": 1762180000000, "nome": "Cofres", "ok": true },
    "funding": { "arquivo": "funding.json", "agora": 1762180000000, "nome": "Funding", "ok": false, "erro": "HTTP 500 em fundingHistory" }
  },
  "ref": { "btc": [["2026-10-01", 64000.5], …], "cdi": [["2026-10-01", 1.0], …] },
  "exemplo": false
}
```

`ok: false` = a forma falhou nesta rodada; o `<forma>.json` continua sendo o da última rodada boa (o `agora` dela).
`ref.btc` = fechamento diário do bitcoin (velas de 1 dia da Hyperliquid); `ref.cdi` = índice acumulado do CDI
(série 12 do Banco Central), 1,0 no primeiro dia; os dois desde 400 dias atrás, para o app comparar qualquer período.

## <forma>.json

```json
{
  "v": 1,
  "forma": "funding",
  "nome": "Funding",
  "agora": 1762180000000,
  "frase": "Compra a moeda e vende a mesma quantidade no perpétuo: o preço deixa de importar e você recebe a taxa de financiamento.",
  "comoFunciona": ["parágrafo curto 1", "parágrafo curto 2"],
  "padrao": "btc1",
  "versoes": [
    {
      "id": "btc1",
      "nome": "BTC 1×",
      "frase": "Metade comprada no à vista, metade de margem do vendido no perpétuo.",
      "risco": "baixo",
      "alav": 1,
      "aoVivo": {
        "inicio": 1762000000000,
        "serie": [["2026-11-03", 1000.0], ["2026-11-04", 1000.8]],
        "retorno": 0.0008,
        "piorQueda": 0.001,
        "ops": 2,
        "taxas": 1.12,
        "extra": { "recebido": 1.9, "pago": 0.1 },
        "liquidacoes": [],
        "nLiq": 0
      },
      "historico": {
        "inicio": 1746000000000,
        "serie": [["2026-05-03", 1000.0], …],
        "retorno": 0.031, "piorQueda": 0.004, "ops": 14, "taxas": 6.3,
        "de": "2026-05-03", "ate": "2026-11-02",
        "aproximado": false,
        "liquidacoes": [], "nLiq": 0
      }
    }
  ],
  "eventos": [
    { "em": 1762100000000, "versao": "btc1", "tipo": "abriu", "texto": "Montou a posição: comprou 0,0071 BTC e vendeu 0,0071 no perpétuo a US$ 70.120." }
  ],
  "itens": [],
  "avisos": ["O que o papel não mostra 1", "…"],
  "config": { "frequencia": "a cada 6 h", "moedas": ["BTC", "ETH", "HYPE", "SOL"] },
  "rodada": { "pedidos": 41, "segundos": 52.3, "erros": [] }
}
```

### Conta (`aoVivo` e `historico`)

O mesmo formato que as contas do copy trading (o app usa as mesmas contas de `testes/calculo.js`: `curva`, `trecho`,
`razao`, `nota`):

- `inicio` (ms): quando a conta começou (a curva do app parte de US$ 1.000 nesse dia);
- `serie`: [dia, patrimônio em US$] um ponto por dia (o último ponto do dia; o dia de hoje é refeito a cada rodada);
- `retorno`: patrimônio de agora ÷ 1.000 − 1; `piorQueda`: a maior queda do topo (0,12 = 12%), medida no passo da
  simulação (não só no fechamento diário);
- `ops`: quantas operações (ordens executadas, depósitos, saques, trocas de posição); `taxas`: US$ pagos em taxas,
  deslize e rede;
- `liquidacoes`: [{ "em": ms, "moeda": "BTC", "perda": 312.5 }] e `nLiq` (o total; a lista guarda as últimas 50);
- `extra`: números próprios da forma (o app mostra os que conhece; ver abaixo).
- Opcionais, como no copy trading: `acerto` (fração de operações fechadas com lucro), `gm`/`pm` (ganho e perda
  médios em US$).

`aoVivo` começa quando a versão foi criada e anda a cada rodada (a rodada "alcança" o tempo perdido pelos
históricos: um horário pulado pelo GitHub não muda o resultado). `historico` é o teste no passado, refeito de tempos
em tempos (`aproximado: true` quando os dados são grossos, como os poucos pontos dos cofres): o app mostra separado e
com a etiqueta "aproximado". Qualquer um dos dois pode ser `null`.

### Versões

- `id`: curto e estável (vira chave no app e no estado); `nome`: curto (cabe num chip); `frase`: uma frase simples;
- `risco`: "baixo", "médio" ou "alto" (pela regra da forma; o app mostra a etiqueta);
- `alav`: a alavancagem (1 quando não há); `padrao` (na forma) é a versão do número grande e do Placar.
- Opcional: `fixa: true` (cofres fixados por ele), `grupo` (para separar versões no ranking, como "BTC" e "ETH").

### eventos

A linha do tempo da forma, mais nova primeiro, no máximo 300: `em` (ms), `versao` (id ou null para a forma inteira),
`tipo` (curto: abriu, fechou, comprou, vendeu, entrou, saiu, liquidou, trocou, reequilibrou, recebeu, pagou, aviso) e
`texto` (a frase em português que o app mostra como está; valores com vírgula decimal e "US$").

### itens

Lista própria da forma (opcional). Nos **cofres**: os cofres seguidos e os fixados:

```json
{ "endereco": "0xdfc2…", "nome": "Hyperliquidity Provider (HLP)", "tvl": 380000000, "apr": 0.12, "idadeDias": 900,
  "comissao": 0.1, "seguidoresMax": null, "fixo": false, "motivo": "TVL de US$ 380 mi; lucro no mês e no total",
  "desde": 1762000000000, "aoVivo": {conta}, "historico": {conta}, "saiu": null }
```

No **funding**, `itens` traz uma linha por moeda: `{ "moeda", "par" (o par à vista, "@142"), "alavMax", "fundingAgora",
"media3d", "hl", "binance", "bybit" }` (taxas ao ano, fração: 0,11 = 11% a.a.; `binance`/`bybit` podem ser null). As
versões do funding têm `grupo` ("1×" ou "3×").

E `candidatos` (só nos cofres): os que passaram na regra e os maiores abertos, para ele escolher quais fixar
(no máximo 40): `{ "endereco", "nome", "tvl", "apr", "idadeDias", "lucroMes", "lucroTotal", "piorQueda", "comissao",
"passou": true, "motivo": "…" }`.

**Cofres fixados à mão**: `config/cofres-fixos.json` na `main` deste repositório, `{ "fixos": [{ "endereco": "0x…",
"em": "AAAA-MM-DD" }] }`. O app grava esse arquivo pela API de conteúdo do GitHub (com o token do app, se ele tiver
acesso a este repositório); a rodada lê o arquivo do checkout. Cofre fixado vira um item com `"fixo": true` e entra
na versão "Os que você fixou" (partes iguais), e não sai pela regra.

### extra (o que o app conhece)

- funding: `recebido`, `pago` (US$ de financiamento), `base` (diferença média entre à vista e perpétuo, fração),
  `fundingAno` (taxa média anualizada no período), `moeda` (a da posição agora, no rodízio), `dentro` (true/false na
  seletiva);
- robôs: `comprado` (US$ na moeda agora), `caixa` (US$), `degrausExecutados`, `precoMedio`, `foraDaGrade` (true/false);
  Nas versões no perpétuo (grade neutra, DCA com proteção 3×), `comprado` tem sinal (negativo = vendido) e `caixa` é o
  patrimônio inteiro; `fundingPago` (US$) e, no DCA com proteção, `ciclos` (fechados). `degrausExecutados` conta as
  ordens da grade, as compras do DCA ou, no DCA com proteção, as compras de proteção. As versões têm `grupo` ("Grade"
  ou "DCA");
- cofres: `cofres` (quantos na versão), `travadoAte` (ms; não dá para sair antes), `comissaoPaga` (US$).

## estado.json

Livre por forma: `{ "v": 1, "formas": { "<forma>": { … } } }`. Cada módulo guarda o que precisa (contas abertas,
cursores de horário, escolha dos cofres). Mudar o formato de uma forma: subir a `VERSAO` dela; o módulo decide se
recomeça ou converte.

## Exemplos

`python3 tools/papel/falso.py <pasta>` roda as formas num mercado de mentira (semente fixa) e grava o mesmo conjunto
de arquivos com `"exemplo": true`; o app (repositório odonto-quest) usa a cópia em `tools/mercado/exemplos/papel/`.

## Apostas de valor (`apostas.json`)

Futebol, só no papel (`apostas.py`). Diferenças das outras formas:

- **Moeda**: as contas são em **R$ fictícios** (1.000 = saldo fictício, como a banca da Betano); `config.moeda` = "R$".
  As contas têm o mesmo formato (`inicio`, `serie`, `retorno`…); `taxas` = 0 (a margem já está na odd) e `ops` = apostas
  liquidadas. `historico` traz também `nota` (a casa do teste é a Bet365, no lugar da Betano).
- **Versões** (`grupo` "Valor", "Aposta grátis" ou "Referência"; `alav` sempre 1): `valor3` (padrão), `valor5`, `valor8`,
  `kelly`, `favoritos`, `azaroes`, `gratis`, `semfiltro`. A `gratis` só soma o que ganha com uma aposta grátis de R$ 5 por
  semana: o patrimônio é 1.000 + os ganhos (nunca cai).
- **extra**: `apostas` (liquidadas), `acerto` (fração ganha), `roi` (resultado ÷ valor apostado), `oddMedia`,
  `clvMedio` (média de odd pega × chance justa da Pinnacle no fechamento − 1; null sem fechamento), `clvPositivo` (fração
  das apostas com CLV > 0), `piorSequencia` (derrotas seguidas), `fonteSoft` (a casa comum: "Betano", "Betano
  (internacional)" ou "Bet365 (no lugar da Betano)"), `anuladas` (sem placar em 10 dias; o valor voltou) e, na `gratis`,
  `ganhoGratis` (R$ ganhos com as apostas grátis).
- **itens**: as apostas no papel esperando o placar: `{ "jogo": "Flamengo × Vasco", "liga", "inicio" (ms),
  "selecao": "Flamengo vence" | "empate" | "mais de 2,5 gols"…, "odd", "justa" (odd justa = 1 ÷ chance), "valor"
  (fração), "casa", "versoes": ["valor3", …] }`. A aposta ao vivo é reconstruída depois do jogo pelo histórico de preços
  (o preço de 6 h antes), então não há "próximas apostas".
- **config**: `aoVivo` ("ligado" ou "falta a chave gratuita da OddsPapi"), `fonteSoft`, `softDescartadas`, `orcamento`
  { `mes`, `usados`, `limite` 250, `paraEm` 225, `maxPorDia`, `cotaHoje`, `puladosPeloLimite`, `semOdds` },
  `campeonatosAoVivo`, `historico` { `jogos`, `temporadas`, `porLiga`, `justaPinnacle`, `fechamentoPinnacle`,
  `casaBet365`, `comGols`, `fonte` } e `pedidosRodada` (por fonte: csv, oddspapi, espn).
- **eventos** (tipos `ganhou`, `perdeu`, `anulou`, `resumo`, `aviso`): até 3 apostas da versão padrão por dia de jogo, a
  aposta grátis de cada semana, um resumo semanal por versão (com o CLV) e os avisos da forma (`versao` null).

## Looping (`looping.json`)

Aave v3 na Base (`looping.py`): juros diários do GraphQL do Aave (`supplyAPYHistory`/`borrowAPYHistory`, 365 dias), o
staking do Lido pela DefiLlama, limites de liquidação pelo `getReserveData` (RPC) e o e-mode pelo GraphQL; o ether pelas
velas da HL (1 h ao vivo, 1 dia no teste no passado, que é `aproximado: true`).

- **Versões** (`grupo` "wstETH × ETH", "ETH × USDC" ou "Referência"; `alav` até 6): `wst3` (padrão), `wst6`, `eth15`, `eth2`,
  `eth2def` (desalavanca quando o fator de saúde cai a 1,3), `usdc` (só depositar).
- **As versões wstETH são medidas em ether**: a conta é convertida em dólar pelo preço do ether no dia em que começou
  (`extra.precoRef`), para mostrar só o laço (staking contra juro); o valor em dólar de verdade vai em `extra.emDolar`.
- **extra**: `hf` (fator de saúde; null sem dívida), `alavAgora`, `rendeAno` (o que a conta rende agora ao ano, fração),
  `ganhoJuros`/`custoJuros` (US$ acumulados), `defesas`, `garantia`/`divida` (símbolos), `precoLiquidacao` (ETH × USDC),
  `emDolar`/`precoRef` (wstETH).
- **itens**: uma linha por moeda: `{ "ativo", "deposito", "emprestimo", "staking", "lt", "bonus", "nota" }` (taxas ao ano).
- **config**: `rede`, `protocolo`, `pool`, `alavMax`, `emode` { `lt`, `bonus`, `ltv`, `nome` }, `fontesParametros`,
  `custos` { `troca`, `deslize`, `relampago`, `gas` }, `stakingFonte`.

## Opções (`opcoes.json`)

Venda de opções de BTC e ETH na Deribit pública (`opcoes.py`): ao vivo, toda sexta depois do vencimento das 08h UTC,
vende pela melhor oferta de compra da cadeia; marca pela `mark_price`; no vencimento paga pelo preço de entrega. **O ao
vivo de cada versão só começa na 1ª sexta depois de ela nascer** (antes, `aoVivo: null` e `config.aoVivoComeca` = ms da
sexta). Teste no passado (180 dias, `aproximado: true`): Black-Scholes com o DVOL (ou a volatilidade realizada,
`config.ivHistorico` "dvol" | "realizada").

- **Versões** (`grupo` "BTC" ou "ETH"; `alav` 1): `put15` (padrão), `put30`, `call15`, `strangle`, `putmes`, `putstop`
  (recompra se a put passar de 3 vezes o prêmio), `eth_put15`, `eth_call15`.
- **extra**: `premios`, `pagos` (US$), `vendas`, `dentro` (venceram com prejuízo), `semValor`, `recompras`, `emAberto`
  (texto curto: "Put 70.000 · vence 13/11"), `naMoeda` (US$ na moeda, nas cobertas), `moeda`.
- **itens**: as opções vendidas em aberto: `{ "versao", "instrumento", "moeda", "tipo", "strike", "vence" (ms), "delta",
  "premio" (US$ recebidos), "marca" (US$ que custaria recomprar), "vendidaEm" }`.
- **config**: `moedas`, `fonte`, `precos` (índice de agora), `taxas`, `ivHistorico`, `deltaAlvo`, `aoVivoComeca`.

## Pools (`pools.json`)

Uniswap v3 WETH/USDC 0,05% na Base (`pools.py`): cada troca do pool pelo RPC público (eventos `Swap`); a taxa e o valor
da posição saem exatos pela matemática do v3. O "teste no passado" (`aproximado: false`) começa 28 dias antes do ao vivo
(o RPC gratuito não guarda mais) e depois anda junto com ele; na 1ª vez pode levar algumas rodadas para alcançar
(`config.passado`).

- **Versões** (`grupo` "Reposiciona", "Parada" ou "Referência"; `alav` 1): `r1`, `r1h`, `r3`, `r3h` (padrão), `r10h`,
  `cheia`, `r3fixa`, `segurar` (50/50 parado, sem pool). "ao sair" reposiciona na troca em que o preço sai da faixa;
  "1 h fora" depois de 1 h fora.
- **extra**: `taxasGanhas` (US$ de taxa do pool ganhos), `gasPago`, `reposicoes`, `precoEth`, `noEther`/`noDolar` (US$ em
  cada moeda agora, com as taxas não coletadas), `perdaImp` (US$, ≤ 0: a realizada nos reposicionamentos + a de agora,
  contra segurar o que foi posto), `dentro`, `dentroFrac` (fração do tempo dentro da faixa), `faixa` [mín., máx.] (US$
  por ETH).
- **config**: `rede`, `protocolo`, `pool`, `par`, `taxaPool`, `precoEth`, `gasWei` (mediana medida), `custoReposicionar`
  (US$ de gás de um reposicionamento), `trocasLidas` { `vivo`, `hist` }, `passado` { `alcancou`, `faltamDias` },
  `volume24h` (o nosso) e `conferencia` { `fonte`: "GeckoTerminal", `volume24h`, `tvl` } (ou null).
- **eventos**: `abriu`; um `reequilibrou` por dia com reposicionamentos (o resumo do dia); na `r3fixa`, `saiu` depois de
  1 h fora da faixa e `entrou` quando volta.

## Memecoins (`memes.json`)

O observatório do pump.fun (`memes.py`, job `memes.yml`, 2 vezes por dia): uma amostra sorteada de 24 lançamentos a cada
rodada, analisada 24 h depois. **Os nomes dos tokens não aparecem** (só o endereço encurtado). `historico` é sempre null.

- **Versões** (`grupo` "Regras" ou "Referência"; `alav` 1; US$ 10 por token): `min1` (padrão), `min5`, `momento`,
  `graduacao`, `min1rc` (só tokens sem risco alto no RugCheck), `segura` (segura ~24 h). A conta é marcada uma vez por
  amostra analisada (no fim das 24 h dela); só aposta o que a conta tem (`extra.semDinheiro` = apostas que não couberam).
- **extra**: `apostas`, `ganhas`, `acerto`, `roi` (resultado ÷ apostado), `resultado` (US$), `apostado`, `dobrou` e `stop`
  (saídas pelo dobro e pelo −50%), `melhor`/`pior` (US$ de uma aposta).
- **observatorio**: `{ "tudo": {contagens}, "semana": {contagens dos últimos 8 dias}, "desde" (ms), "amostras",
  "esperando" (tokens aguardando as 24 h), "proxima" (ms da próxima análise), "regras": [{ "id", "nome", "apostas",
  "acerto", "roi", "resultado", "melhor", "pior", "dobrou", "stop" }], "lancamentosPorMin", "lancamentosPorDia" }`.
  Contagens: `tokens`, `dobraram` (máxima ≥ 2× o lançamento), `dezVezes`, `graduaram`, `golpes` (queda > 90% em até 5 min
  na 1ª hora), `morreram` (sem negociação depois do 1º minuto ou < 10% do lançamento em ~24 h, sem ter graduado),
  `semNegocios`, `semVelas` (tinham par, mas as velas não vieram), `rugcheckAlto`, `rugcheckSem`, `criadorGrande`
  (criador comprou ≥ 10% na criação), `medianaX24` (preço de ~24 h ÷ o do lançamento, dos que negociaram; pode ser null),
  `vivos24h`.
- **itens**: os últimos 40 tokens analisados: `{ "mint" ("AbCd…pump"), "lancado" (ms), "maxX", "x24" (null sem
  negócios), "graduou", "golpe", "morreu", "rugcheck" ("alto" | "ok" | null), "criadorGrande" }`.
- **config**: `rede`, `plataforma`, `aposta`, `amostra`, `ouvirSegundos`, `taxas` { `curva`, `amm`, `deslizeAmm`,
  `redeSol` }, `prioridade` (mediana medida, micro-lamports por unidade), `saida` { `alta`, `baixa`, `minutos` },
  `observatorio: true`.
- **eventos** (`resumo`, `aviso`): o resumo de cada amostra (o da forma, `versao` null) e o da versão padrão.
