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
`ref.cdiAno` = a taxa ao ano dos últimos 20 dias úteis da série (desde 09/11/2026; antes era fixa em 14,9%), usada
depois do último dia publicado; `ref.cdiFonte` = "bcb" quando a série veio nesta rodada (o BC às vezes responde 304 ou
cai: a rodada tenta 3 vezes e, se não der, fica com os dias já guardados).

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
  médios em US$); `aproximado: true` também no `aoVivo` quando o próprio ao vivo é uma estimativa (funding entre
  corretoras).
- `metricas` (desde 09/11/2026, em TODA conta com série: versões, itens dos cofres e, no `resumo.json` do copy trading,
  cada conta do `aoVivo`): os mesmos números para decidir em todas as formas, calculados em `conta.metricas` pela série
  diária e pelo CDI do Banco Central no MESMO período (dias sem ponto repetem o valor anterior):

  ```json
  { "dias": 21, "retorno": 0.0123, "cdi": 0.0109, "excesso": 0.0014, "venceCdi": true,
    "aoMes": 0.0176, "aoAno": null, "volAno": 0.083, "sharpe": 0.41, "retornoPorQueda": null,
    "piorDia": -0.0071, "diasPositivos": 0.57 }
  ```

  `cdi` = o CDI acumulado do início ao último ponto; `excesso` = (1 + retorno) ÷ (1 + cdi) − 1; `aoMes` só com 7 dias
  ou mais e `aoAno` só com 30 (antes disso, null: extrapolar engana); `volAno` = desvio dos retornos diários × √365;
  `sharpe` = (retorno diário médio − CDI do dia) ÷ desvio × √365, só com 14 dias ou mais e limitado a ±10 (abaixo de 0: o CDI rendeu
  mais com menos risco); `retornoPorQueda` = `aoAno` ÷ `piorQueda` (a "Calmar"), só com 30 dias e queda ≥ 0,5%. Nas
  apostas os valores estão em R$, e nas versões wstETH do looping, em ether: os números são frações, então valem igual.

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
`texto` (a frase em português que o app mostra como está; valores com vírgula decimal e "US$"). Opcional `motivo`
(nos cofres, desde 09/11/2026, nas saídas e trocas): o código do porquê ("stop", "tvl", "lider", "deposito",
"fechou", "sumiu", "lista", "semana", "fixos").

### itens

Lista própria da forma (opcional). Nos **cofres**: os cofres seguidos e os fixados:

```json
{ "endereco": "0xdfc2…", "nome": "Hyperliquidity Provider (HLP)", "tvl": 380000000, "apr": 0.12, "idadeDias": 900,
  "comissao": 0.1, "seguidoresMax": null, "fixo": false, "motivo": "TVL de US$ 380 mi; lucro no mês e no total",
  "desde": 1762000000000, "aoVivo": {conta}, "historico": {conta}, "saiu": null, "listas": ["seguidos"] }
```

`listas` (desde 09/11/2026): em quais listas ele está agora: "seguidos" (os 10 da regra), "grandes", "constancia".

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
  seletiva). A versão **`entre`** (entre corretoras, desde 09/11/2026; `grupo` "Entre corretoras", `aproximado: true`
  na versão e no `aoVivo`, `historico` sempre null) traz também `longo` e `curto` (o nome da corretora de cada perna:
  "Hyperliquid", "Binance" ou "Bybit"; null fora), `diferencaAno` (a diferença das taxas previstas agora, fração ao
  ano; igual a `fundingAno`), `montagens` e `leituras`; `base` é null. `config.entre` = { `entra`, `sai`, `troca`,
  `taxas`, `ponte` };
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

## Cofres (`cofres.json`): o que entrou em 09/11/2026

Pedidos do Alediov depois de 6 dias ao vivo (5 melhores −0,06% ao vivo × +7,7% no teste no passado). `VERSAO` da
forma continua 1: as versões novas nascem com US$ 1.000 na 1ª rodada depois da mudança e as listas novas são escolhidas
numa escolha fora da segunda, uma vez.

- **Versões** (todas com `grupo`): "Pela regra" = `top5` (padrão), `top10`, `top5s` e **`sinais`** (5 melhores com
  sinais de saída: o stop de 15% do topo e, a cada rodada, o líder com menos de 5% do cofre, o TVL caindo 30% em 7 dias
  pelo `accountValueHistory` da semana, o cofre fechado para depósitos; sai depois da trava, 4 semanas de castigo, o
  dinheiro vai para o próximo da fila); "Outras escolhas" = **`constancia`** (os 5 de maior lucro de 90 dias ÷
  (desvio dos retornos diários × √90), pela cota interpolada dia a dia; recusa quem tem menos de 90 dias, prejuízo em 90
  dias ou um dia com mais de 50% do lucro), **`grandes`** (os 5 melhores pela nota entre os de TVL ≥ US$ 1 milhão; a
  escolha detalha também os 15 maiores do pré-filtro) e `semana`; "Com o HLP" = `hlp`, **`mix50`** (50% HLP + 50% nos
  5 melhores) e **`mix25`** (25% + 75%), que voltam às partes certas toda segunda (vendendo de quem passou da parte, se
  a trava deixa); "Seus" = `fixos`. As listas de `constancia` e `grandes` ficam no estado (`listas`) com a regra dos
  seguidos (4 semanas no mínimo; sai antes só se fechar, sumir ou parar de aceitar depósitos).
- **`historico`** das versões continua (refeito a cada 7 dias, e uma vez quando faltam as versões novas), agora chamado
  no app de "no período da escolha (otimista)": usa os cofres que a escolha de HOJE detalhou.
- **`passado`**: o teste FORA DA AMOSTRA (`cofres_passado.py`). As últimas 12 semanas, de uma segunda até a rodada que
  montou; toda segunda (a cada 7 dias desde o começo) cada versão escolhe só com os números até aquele dia e anda pelos
  dias seguintes (`simular_regras`, o mesmo motor do `historico`). O universo é a lista inteira (sem o HLP e os filhos,
  37+ dias de vida): os abertos com US$ 30 mil ou mais pela ordem do TVL de hoje (até 300) e os fechados pela ordem do
  lucro total em valor absoluto (até 100), mais o HLP. Um `vaultDetails` por cofre, aos poucos (até 240 s por rodada,
  só com 10 min ou mais de folga na rodada); refeito a cada 7 dias.

  ```json
  { "aproximado": true, "semanas": 12, "proximo": 1763600000000,
    "andamento": null | { "fase": "detalhar", "de": ms, "universo": 401, "detalhados": 120, "comDados": 64, "criado": ms },
    "resultado": { "de": ms, "ate": ms, "feitoEm": ms, "semanas": 13, "aproximado": true,
      "funil": { "lista": 9478, "candidatos": { "abertos": 380, "fechados": 2100 }, "universo": 401, "detalhados": 401,
                 "comDados": 150, "recusas": { "nunca teve US$ 100 mil no período": 200 }, "fechados": 12, "usados": 19 },
      "contas": { "top5": {conta com metricas}, "…": {} },
      "escolhas": [ { "semana": "2026-08-17", "top5": [{ "endereco", "nome" }], "passaram": 30, "comDados": 140 } ],
      "previsto": { "top5": 0.077 } },
    "rodadas": [ { "de": ms, "ate": ms, "retorno": 0.01, "previsto": 0.07, "comDados": 150 } ] }
  ```

  `previsto` = o que o `historico` (otimista) dava no mesmo período. Limitações: só cofres que ainda estão na lista (os
  apagados não), os abertos pelo TVL de hoje, a parte do líder de hoje (o sinal do líder não entra; nos fechados a regra
  não confere a parte), não se sabe quando um cofre fechou para depósitos, o histórico antigo tem poucos pontos.
- **`lider`**: o cofre × copiar o líder (`cofres_lider.py`) para os 5 melhores de agora: US$ 1.000 copiando no papel as
  operações do PRÓPRIO cofre (o endereço do cofre nas execuções; o `leader` vai só como informação) com o motor do copy
  trading (`tools/mercado/sim.py`: proporcional 1×, 1 min de atraso, taxa, deslize, financiamento), desde o dia em que o
  cofre passou a ser acompanhado, contra a conta própria do cofre (já sem a comissão de 10%).

  ```json
  { "atraso": 1, "alav": 1,
    "cofres": [ { "endereco", "nome", "lider", "desde": ms, "em": ms, "fonte": "operações do próprio cofre",
                  "muitas": false, "cofre": {conta com metricas}, "copia": {conta com metricas; extra.financiamento},
                  "diferenca": 0.012 } ],
    "total": { "cofre": {conta}, "copia": {conta}, "diferenca": 0.004, "n": 5, "copiaGanhou": 3 },
    "saidos": [ { "endereco", "nome", "desde", "saiu", "cofre", "copia", "diferenca" } ] }
  ```

  `diferenca` = retorno da cópia − retorno do cofre (positivo: copiar teria rendido mais). Só perpétuos entram na cópia;
  posições que o cofre já tinha e não mexeu depois não são copiadas; `muitas`: chegou ao teto de 4.000 execuções numa
  rodada (as mais antigas podem faltar).
- `config` ganhou `sinais`, `constancia`, `tvlGrande` e `misturas`.

## Apostas de valor (`apostas.json`)

Futebol, só no papel (`apostas.py`). Diferenças das outras formas:

- **Mercados**: o 1X2 (mercado 101 da OddsPapi) e o mais/menos de 2,5 gols (mercado 1010; até 09/11/2026 o ao vivo não
  lia este, porque a resposta não traz o nome do mercado). Um 404 na lista de jogos de um campeonato = sem jogos no
  período (não é erro).
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
- **Seguir o BDM** (versão `bdm`, `grupo` "Seguir palpites", desde 09/11/2026): os palpites do programa diário "Bom Dia
  Mercado" do Theo Borges, lidos de `config/bdm/<data>.json` deste repositório (publicados pelo repositório do app,
  `tools/ideias/bdm.py` de lá; a transcrição NUNCA vem para cá). Arquivo:
  `{ "versao": 1, "data": "AAAA-MM-DD", "video": { "id", "publicado" }, "palpites": [{ "id": "<vídeo>-N", "mandante",
  "visitante", "competicao", "inicio" ("AAAA-MM-DDTHH:MM:00-03:00" ou só a data), "mercado" ("1x2" | "dupla" | "dnb" |
  "ou" | "ah" | "btts" | "cartoes" | "escanteios" | "outro"), "linha" (número ou null), "selecao" ("mandante" |
  "empate" | "visitante" | "1x" | "12" | "x2" | "mais" | "menos" | "sim" | "nao" | null), "oddCitada" (1,01 a 50 ou
  null), "fora" (plano condicional/ao vivo), "motivo" ("ao_vivo" | "condicional" | "cartoes" | "sem_jogo" | "outro" |
  null) }] }`. A conta aposta R$ 20 fixos (2% da banca inicial) em cada palpite de **1X2** ou de **mais/menos de 2,5
  gols** (os mercados que o teste já precifica; os outros ficam "fora do teste" com o nome do mercado no motivo) cujo
  jogo está nos campeonatos acompanhados (times em qualquer ordem; início ±3 h, ou o dia), na odd da casa comum do 1º
  preço a partir da hora em que a rodada VIU o palpite e antes do início (reconstruída depois do jogo pelo mesmo
  /historical-odds; os jogos com palpite vão primeiro na fila do limite do dia). Só ao vivo: `historico` null e
  `soAoVivo: true`. Um push em `config/bdm/**` roda o papel.yml só com as apostas. O `extra` dela tem também
  `palpitesVistos`, `noTeste` (viraram aposta), `cobertura` (noTeste ÷ vistos), `esperando`, `fora` [{ `motivo`, `n` }]
  (plano para o ao vivo, mercado fora do teste: …, jogo fora dos campeonatos acompanhados, visto depois do início do
  jogo, sem odds antes do jogo, limite gratuito da OddsPapi, sem saldo na conta), `oddCitadaMedia` e `oddPegaMedia` (nas
  apostas com odd citada), `ultimos` (até 12: { `jogo`, `competicao`, `inicio`, `dia`, `mercado`, `selecao`,
  `oddCitada`, `odd`, `situacao` esperando | apostado | liquidado | anulado | fora, `motivo`, `resultado` (R$),
  `placar`, `clv` }) e `desde`. Os eventos dela (`versao` "bdm") trazem cada aposta liquidada com a odd citada.
  `config.bdm` { `aposta`, `mercados`, `fonte`, `desde` }.

## Looping (`looping.json`)

Aave v3 na Base (`looping.py`): juros diários do GraphQL do Aave (`supplyAPYHistory`/`borrowAPYHistory`, 365 dias), o
staking do Lido pela DefiLlama, limites de liquidação pelo `getReserveData` (RPC) e o e-mode pelo GraphQL; o ether pelas
velas da HL (1 h ao vivo, 1 dia no teste no passado, que é `aproximado: true`).

- **Versões** (`grupo` "wstETH × ETH", "ETH × USDC" ou "Referência"; `alav` até 6): `wst3` (padrão), `wst6`, `eth15`, `eth2`,
  `eth2def` (desalavanca quando o fator de saúde cai a 1,3), e as réguas (desde 09/11/2026, `grupo` "Referência"):
  `wst1` (só wstETH, sem empréstimo: o staking sozinho, medido em ether), `eth1` (só ether, sem empréstimo: o preço
  sozinho) e `usdc` (só depositar). Cada laço se compara com a régua do mesmo tipo.
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

Pools de liquidez concentrada na Base (`pools.py`): cada troca do pool pelo RPC público (eventos `Swap`, o mesmo tópico no
Uniswap v3 e no Aerodrome Slipstream); a taxa e o valor da posição saem exatos pela matemática do v3. O "teste no
passado" (`aproximado: false`, menos nas versões "no gauge") começa 28 dias antes do ao vivo (o RPC gratuito não guarda
mais) e depois anda junto com ele; na 1ª vez pode levar algumas rodadas para alcançar (`pools[].passado`). Desde
09/11/2026 são vários pools (ver **pools**); cada versão diz de qual (`pool`). O WETH/USDC do Uniswap continua com as
mesmas versões, ids e histórico de antes (o estado antigo é levado para `pools.weth_usdc` sem recomeçar).

- **pools** (lista, desde 09/11/2026): um item por pool, na ordem `weth_usdc`, `cbbtc_usdc`, `weth_cbbtc`,
  `aero_weth_usdc`, `estavel`, `brz`:

  ```json
  { "id": "aero_weth_usdc", "nome": "WETH/USDC", "par": "WETH/USDC", "dex": "Aerodrome", "protocolo": "Aerodrome Slipstream",
    "endereco": "0xb2cc…", "taxa": 0.0005, "espacoTick": 100, "medida": "usd", "padrao": "aer-med",
    "versoes": ["aer-est", "aer-estg", …], "observador": false, "preco": 3120.5, "volume24h": 8690000, "trocas24h": 1900,
    "tvl": 3020000, "giro": 2.88, "rendTaxaDia": 0.0013, "aprTaxas": 0.47, "volDia": 0.031,
    "larguras": { "est": 0.031, "med": 0.093, … }, "passado": { "alcancou": true, "faltamDias": 0 },
    "trocasLidas": { "vivo": 4711, "hist": 88287 }, "parteGauge": 0.1,
    "gauge": { "endereco": "0x…", "aeroDia": 5184, "precoAero": 0.95, "fracStake": 0.6, "amostras": 12, "aproximado": true,
               "aprEmissoes": 0.61 },
    "escolha": { "em": 1762…, "origem": "fábrica do Slipstream, espaço 100", "candidatos": [{ "endereco", "dex", "fee",
                 "espaco", "par", "trocasHora", "volumeHora", "gauge" }] }, "nota": null }
  ```

  `par` = base/cotação (o preço é o da base na cotação: US$ por ether, US$ por bitcoin, bitcoin por ether, US$ por
  tether); `taxa` = a taxa da troca (fração); `medida` "usd" ou "btc" (o `weth_cbbtc`: a conta é medida em bitcoin,
  convertida pelo preço do bitcoin do dia em que começou, `extra.precoRef`, e o dólar de verdade em `extra.emDolar`);
  `volume24h` e `tvl` em US$ (o nosso volume, pelas trocas lidas; a liquidez pelo `balanceOf` dos dois tokens no pool);
  `giro` = volume ÷ liquidez; `rendTaxaDia`/`aprTaxas` = giro × taxa (× (1 − `parteGauge`) no Aerodrome), por dia e
  ×365: quanto o pool inteiro rende só de taxas; `volDia` = a oscilação diária medida no pool; `larguras` = a largura
  (fração para cada lado) que cada versão teria se pusesse agora. `observador: true` (o `brz`): sem versões, só volume,
  liquidez e a `nota`. `gauge` só no Aerodrome com gauge: `aeroDia` = AERO pago por dia ao pool inteiro, `fracStake` = a
  parte da liquidez ativa em stake, `aprEmissoes` ≈ aeroDia × preço × 365 ÷ (liquidez × fracStake). A escolha (a 1ª
  rodada de cada pool) é o candidato de maior volume na última hora entre os que são o par certo (`escolha.candidatos`);
  fica para sempre.
- **Versões do WETH/USDC** (`pool` "weth_usdc"; `grupo` "Reposiciona", "À mão", "Parada" ou "Referência"; `alav` 1): `r1`, `r1h`, `r3`, `r3h` (padrão),
  `r10h`, `dia10`, `dia5`, `cheia`, `r3fixa`, `segurar` (50/50 parado, sem pool). "ao sair" reposiciona na troca em que
  o preço sai da faixa; "1 h fora" depois de 1 h fora. **"À mão"** (desde 09/11/2026: o jeito de quem cuida da pool
  pelo celular, como ensinam os canais brasileiros de pools): olha uma vez por dia ao meio-dia (Brasília), só
  reposiciona se estiver fora nessa hora e a cada 7 dias põe as taxas ganhas de volta na posição, na mesma faixa
  (`extra.reinvestimentos`). Uma versão nova faz o teste no passado recomeçar para todas do mesmo pool (28 dias antes
  da rodada em que ela nasceu).
- **Versões dos pools novos** (ids com o prefixo do pool: `cbu-`, `ecb-`, `aer-`, `stb-`): a faixa segue a oscilação
  diária medida no próprio pool (`volDia`): `est` (estreita, 1×), `med` (média, 3×; o padrão), `larga` (8×), as três
  reposicionando depois de 1 h fora; `maoM` e `maoL` (média e larga "à mão": 1×/dia + reinveste); `cheia`; `segurar`.
  No Aerodrome com gauge, `est`, `med`, `larga`, `maoM` e `cheia` ganham também a versão "no gauge" (id + `g`, `grupo`
  "No gauge (AERO)", `aproximado: true` no `aoVivo` e no `historico`): não ganha taxa e sim AERO (rewardRate × tempo
  dentro da faixa × L ÷ (liquidez em stake ativa + L)), vendido uma vez por dia; as outras ganham as taxas menos a parte
  que vai ao gauge (`parteGauge`). A largura é calculada na hora de pôr e de reposicionar (limitada a 50% e a um espaço
  de tick).
- **extra**: `taxasGanhas` (US$ de taxa do pool ganhos), `gasPago`, `reposicoes`, `reinvestimentos`, `preco` (a base
  na cotação), `naBase`/`naCotacao` (US$ em cada moeda agora, com as taxas não coletadas; no WETH/USDC também os antigos
  `precoEth`, `noEther`/`noDolar`), `perdaImp` (US$, ≤ 0: a realizada nos reposicionamentos + a de agora, contra segurar
  o que foi posto), `dentro`, `dentroFrac` (fração do tempo dentro da faixa), `faixa` [mín., máx.] (o preço da base na
  cotação), `largura` (nos pools novos), `aeroGanho` (AERO), `aeroVendido` (US$ líquidos da venda) e `aeroParado` (US$
  ainda por vender) no gauge, `precoRef`/`emDolar` no `weth_cbbtc`.
- **config**: `rede`, `protocolo`, `pool`, `par`, `taxaPool`, `precoEth`, `gasWei` (mediana medida), `custoReposicionar`
  (US$ de gás de um reposicionamento), `trocasLidas` { `vivo`, `hist` }, `passado` { `alcancou`, `faltamDias` },
  `volume24h` (o nosso) e `conferencia` { `fonte`: "GeckoTerminal", `volume24h`, `tvl` } (ou null): todos do WETH/USDC,
  como antes; e `pools` (quantos pools com contas).
- **eventos**: `abriu`; um `reequilibrou` por dia com reposicionamentos (o resumo do dia); na `r3fixa`, `saiu` depois de
  1 h fora da faixa e `entrou` quando volta.

## Memecoins (`memes.json`)

O observatório do pump.fun (`memes.py`, job `memes.yml`, 2 vezes por dia): uma amostra sorteada de 24 lançamentos a cada
rodada, analisada 24 h depois. **Os nomes dos tokens não aparecem** (só o endereço encurtado). `historico` é sempre null.
**Recomeçou do zero em 09/11/2026** (`VERSAO` 2): a 1ª rodada real mostrou lançamentos de outras plataformas no
PumpPortal (curva diferente; um deles saiu "28.904×" por erro de unidade) e que a DexScreener não lista a maioria dos
tokens pequenos (viravam "sem negócios"). Agora a amostra é só do pump.fun (`pool` "pump"), quem falta na DexScreener é
procurado no GeckoTerminal, e o que nenhum dos dois responde fica "sem dados" (fora das apostas e das contagens de morto
e vivo).

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
  `vivos24h`, `semDados` (nem a DexScreener nem o GeckoTerminal responderam: não se sabe; desde 09/11/2026). No
  `observatorio`, também `outrasPlataformas` (lançamentos de outras plataformas que o PumpPortal mandou e ficaram fora).
- **itens**: os últimos 40 tokens analisados: `{ "mint" ("AbCd…pump"), "lancado" (ms), "maxX", "x24" (null sem
  negócios ou sem dados), "graduou", "golpe", "morreu", "rugcheck" ("alto" | "ok" | null), "criadorGrande",
  "semDados" }`.
- **config**: `rede`, `plataforma`, `aposta`, `amostra`, `ouvirSegundos`, `taxas` { `curva`, `amm`, `deslizeAmm`,
  `redeSol` }, `prioridade` (mediana medida, micro-lamports por unidade), `saida` { `alta`, `baixa`, `minutos` },
  `observatorio: true`.
- **eventos** (`resumo`, `aviso`): o resumo de cada amostra (o da forma, `versao` null) e o da versão padrão.
