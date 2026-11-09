# orbita-testes

Repositório PÚBLICO (criado pelo Alediov em 03/11/2026) só com os testes de mercado no papel do app Órbita, que mora
no repositório privado `Alediov/odonto-quest` (lá estão o app, a aba Finanças → Testes que lê estes resultados e o
CLAUDE.md com o histórico dos pedidos). Veio para cá porque os minutos gratuitos do Actions do repositório privado
acabavam; aqui os executores padrão não têm limite.

## Regras (pedidos do Alediov)

- **Tudo é público.** Nunca pôr aqui token, chave, PIN, e-mail, nada das Finanças pessoais dele (Ping-Pong, saldos,
  macros, issue #1), nada do OdontoScan nem de outra área do app. Só código de simulação e dados públicos de mercado
  (endereços públicos de carteiras e cofres são públicos).
- **Só no papel**: nenhuma ordem, nenhuma conta, nenhuma chave de negociação, nenhum segredo nos workflows (o push
  nos ramos de saída usa o `GITHUB_TOKEN` automático).
- **Tudo gratuito**: só APIs públicas sem chave e sem cartão (as testadas estão no plano 2, "Teste de alcance").
- Valor inicial de toda conta fictícia: US$ 1.000. Alavancagem máxima nas formas novas: 3× no funding e nos robôs,
  6× só no looping. Moedas: BTC, ETH, HYPE e SOL na Hyperliquid; pools e looping na Base; opções BTC e ETH.
  Memecoins só como observatório. Teste no passado mostrado como "aproximado", separado do ao vivo. Cofres pela regra,
  com a opção de fixar alguns à mão.

## Estrutura

- `tools/mercado/`: copy trading (detalhes no `LEIA-ME.md` de lá). Workflow `mercado.yml`, ramo `mercado`.
- `tools/papel/`: as outras formas, no formato comum de `tools/papel/FORMATO.md`. Workflow `papel.yml`, ramo `papel`.
- `tools/papel/apostas.py` (+ `odds.py`, `falso_apostas.py`, `teste_apostas.py`): **Apostas de valor** (pedido do Alediov,
  03/11/2026; só futebol, só no papel, como ele fazia na Betano antes da suspensão das bets): odd justa = Pinnacle sem a
  margem (método da potência), aposta quando a casa comum paga ≥ 3/5/8% a mais, Kelly ¼, favoritos, azarões, a aposta
  grátis de R$ 5 por semana e "sem filtro" como referência; contas em R$ fictícios (1.000). Teste no passado pelas
  planilhas gratuitas do football-data (Bet365 no lugar da Betano; Brasileirão só no fechamento); ao vivo pela OddsPapi
  (gratuita, 250 pedidos/mês, chave SÓ no segredo `ODDSPAPI_KEY` deste repositório, passado como variável de ambiente
  no `papel.yml`; nunca em arquivo nem no log) e os placares pela ESPN. Os nomes dos campos das fontes foram escritos sem
  acesso a elas daqui: a 1ª rodada real registra a estrutura no log para conferir.
- **Fases 2 a 4** (07/11/2026): `looping.py` (Aave v3 na Base: wstETH × ETH 3×/6× medidos em ether, ETH × USDC 1,5×/2×,
  2× com defesa, só USDC), `opcoes.py` (venda de puts e calls na Deribit pública; o ao vivo começa na 1ª sexta; o
  passado pelo DVOL, "aproximado"), `pools.py` (Uniswap v3 WETH/USDC 0,05% na Base troca a troca pelo RPC público
  `base-rpc.publicnode.com`: faixas ±1/±3/±10%, cheia, sem reposicionar e segurar 50/50; o passado são os 28 dias antes
  do começo, o máximo que o RPC grátis guarda) e `memes.py` (observatório do pump.fun: amostra sorteada de 24
  lançamentos pelo websocket do PumpPortal, analisada 24 h depois pela DexScreener, GeckoTerminal e RugCheck; job
  próprio `memes.yml`, 2 vezes por dia, no mesmo ramo `papel`; nomes dos tokens nunca guardados). As fontes fora da
  Hyperliquid passam por `rede.py` (freio por fonte; `ws.py` é o websocket mínimo, só biblioteca padrão), e cada uma
  registra no log a estrutura da 1ª resposta de verdade (os nomes dos campos foram escritos sem acesso daqui: conferir
  no log da 1ª rodada). Mercado de mentira em `falso_looping.py`, `falso_opcoes.py`, `falso_pools.py` (também o RPC da
  Base e o `getReserveData` do Aave) e `falso_memes.py`; testes `teste_looping.py`, `teste_opcoes.py`, `teste_pools.py`,
  `teste_memes.py` (todos por `python3 tools/papel/teste_papel.py`). `papel.FORMAS` (o papel.yml) não inclui os memes
  (`FORMAS_A_PARTE`).
- `tools/ideias/` + `config/ideias-canais.json` + `ideias.yml`: **Antena de ideias** (pedido do Alediov, 09/11/2026:
  achar cedo nos canais que ele acompanha ideias de macros novas e de testes no papel). Só COLETA: feed RSS de cada canal
  (channel_id na config; se falhar, procurado de novo na página do @handle), na 1ª rodada de um canal os últimos 30
  envios pelo yt-dlp, e a transcrição (legendas pt/en pelo yt-dlp, senão youtube-transcript-api; bloqueio do IP do
  Actions vai para o `motivoSemTranscricao` e o vídeo é tentado de novo até 6 vezes). Ramo órfão `ideias` (2×/dia):
  `videos/<id>.json`, `indice.json` (sem os textos) e `log.txt`. Quem lê e classifica é a tarefa do repositório privado
  (`gerador/IDEIAS.md` de lá). Teste: `python3 tools/ideias/teste_ideias.py`.
- **Revisão de 09/11/2026** (pedido do Alediov: "aprimorar cada um dos Testes"; olhando as rodadas reais de 03 a
  09/11): (1) **métricas comuns** em toda conta com série (`conta.metricas`, posto pelo `papel.py` em todas as formas e
  pelo `mercado.py` em cada conta do copy trading, que agora lê `tools/papel` no checkout): CDI no MESMO período,
  excesso sobre ele, ao mês (só com 7 dias) e ao ano (só com 30), volatilidade, Sharpe contra o CDI (só com 14 dias),
  retorno por queda, pior dia e dias positivos; o CDI tenta 3 vezes (o BC respondeu 304 em 08/11) e, sem ele, usa a taxa
  dos últimos 20 dias guardados (`cdiAno`). (2) **Apostas**: o mais/menos de 2,5 gols nunca era lido ao vivo (o
  `/historical-odds` não traz o nome do mercado; agora pelo id 1010) e o 404 da lista de jogos (Libertadores sem jogos)
  vira lista vazia. Achado: "Valor 3%" quase não aposta (29 em 4.922 jogos no passado, 0 em 6 dias ao vivo); é a
  realidade da Betano (internacional) contra a Pinnacle nas ligas grandes, não um defeito. (3) **Funding**: a versão
  `entre` (entre corretoras, que tinha ficado de fora), só ao vivo e aproximada, pelas taxas previstas da Binance e da
  Bybit que a própria HL publica (o Actions não alcança a Binance nem a Bybit). (4) **Looping**: as réguas `wst1` (só o
  staking) e `eth1` (só o ether). (5) **Pools**: `dia10`/`dia5`, o jeito de cuidar da pool à mão (olha 1×/dia, reinveste
  as taxas a cada 7 dias), inspirado no que o Canal do Marinho (Victor Marinho, "Mestre das Pools") ensina; os vídeos
  não abriram daqui, então os números são uma suposição a confirmar com ele; versão nova recomeça o passado das pools.
  (6) **Memecoins** (`VERSAO` 2, recomeçou): o PumpPortal manda lançamentos de outras plataformas (filtro `pool` "pump")
  e a DexScreener não lista os tokens pequenos (GeckoTerminal confere; nenhum dos dois = "sem dados", fora das apostas).
  Detalhes no `tools/papel/FORMATO.md`.
- **Seguir o BDM** (pedido do Alediov, 09/11/2026; só esta conta, nenhum mercado novo): versão `bdm` das apostas, que
  segue os palpites do programa diário "Bom Dia Mercado" do Theo Borges. O repositório PRIVADO extrai os palpites da
  transcrição (que o celular baixa; `tools/ideias/bdm.py` + `ideias-bdm.yml` de lá, com a IA gratuita do filtro) e
  publica aqui SÓ os campos do palpite em `config/bdm/<data>.json` (jogo, campeonato, início, mercado, seleção, odd
  citada, id e data do vídeo; nunca o texto). R$ 20 fixos por palpite de 1X2 ou mais/menos de 2,5 gols, na odd da hora
  em que a rodada viu o palpite (antes do jogo), liquidado pela ESPN, CLV contra o fechamento; o resto conta como "fora
  do teste" com o motivo. Só ao vivo. Um push em `config/bdm/**` roda o papel.yml só com as apostas. Formato e regras no
  `tools/papel/FORMATO.md`; teste em `teste_apostas.py` (`teste_bdm_*`).
- **Cinco pools** (pedido do Alediov, 09/11/2026; `pools.py`): além do WETH/USDC do Uniswap (as 10 versões e o histórico
  continuam; o estado antigo vai para `pools.weth_usdc` sem recomeçar, `migrar`), cbBTC/USDC e WETH/cbBTC no Uniswap v3
  (o par correlacionado é medido em bitcoin), WETH/USDC no Aerodrome Slipstream (cada versão "sem gauge", com as taxas
  menos a parte do gauge, e "no gauge", com o AERO vendido todo dia: aproximado, porque a parte em stake, a emissão e o
  preço do AERO só são lidos a cada rodada) e o par de dólares estáveis com mais trocas (USDC/USDT ou EURC/USDC). O
  BRZ/USDC é só observado (em 09/11/2026 os 28 pools do BRZ na Base somavam ~US$ 10 mil por dia; o BRLA não tem pool com
  volume na Base). Cada pool novo é ESCOLHIDO na 1ª rodada pelo maior volume da última hora entre os candidatos (fábricas
  do Uniswap e do Slipstream + endereços conhecidos de páginas públicas), conferindo token0/token1/fee/tickSpacing/
  decimals na rede, e a escolha fica (`pools.<id>.escolha`; o log da 1ª rodada registra tudo). As faixas dos pools novos
  seguem a oscilação diária medida em cada um (estreita/média/larga = 1/3/8 vezes). O ao vivo de todos vem primeiro e os
  passados se revezam entre as rodadas. Seletores e o tópico do Swap pelo keccak de `keccak.py` (Python puro). Saída
  `pools[]` com volume, liquidez, giro, taxas ao ano e o gauge (FORMATO.md, "Pools").
- **Copy trading revisto** (pedido do Alediov, 09/11/2026, pelos dados reais de 02 a 09/11; detalhes no
  `tools/mercado/LEIA-ME.md`): 18 contas por carteira (sem 10×; 5 min só no controle `3x5`); versões `p20`/`p25`/`p30`
  que largam a carteira quando a cópia cai 20/25/30% do topo; `agregadas.py` (As 5 melhores, Só robôs, Só pessoas,
  refeitas pelo `banco` de séries, e o Consenso, 2+ carteiras do mesmo lado) em `agregadas` no resumo; `passado.py`, o
  teste FORA DA AMOSTRA (a regra aplicada aos dados de 60 a 30 dias atrás, a cópia nos 30 seguintes; ranking de T0
  refeito pelo `portfolio`; aos poucos, refeito a cada 7 dias; "aproximado") em `passado`; e o risco reavaliado nas
  carteiras que estavam sem ele. O teste de antes de cada carteira continua (`historico`): é o "período da escolha",
  otimista.
- **Cofres revistos** (pedido do Alediov, 09/11/2026, pelos 6 dias ao vivo: 5 melhores −0,06% ao vivo × +7,7% no teste
  no passado; detalhes no `tools/papel/FORMATO.md`, "Cofres"): versões novas `sinais` (o stop + o líder com < 5%, o TVL
  −30% em 7 dias e o cofre fechado para depósitos; motivo no evento, `motivo`), `constancia` (lucro de 90 dias ÷
  oscilação, sem quem fez > 50% do lucro num dia), `grandes` (TVL ≥ US$ 1 mi) e as misturas `mix50`/`mix25` com o HLP
  (rebalanceio toda segunda), todas com `grupo`; o teste antigo virou "no período da escolha (otimista)" e o motor das
  versões é um só (`simular_regras`); `cofres_passado.py`, o teste FORA DA AMOSTRA (12 semanas, escolha toda segunda só
  com o que se sabia, universo = a lista inteira com os fechados; aos poucos, 240 s por rodada, refeito a cada 7 dias) em
  `passado`; `cofres_lider.py`, o cofre × copiar as operações do cofre no papel com o `sim.py` do copy trading (1×,
  1 min) para os 5 melhores, em `lider`. As execuções de mentira dos cofres estão no `falso_cofres.py`.
- Os exemplos que o app usa sem rede ficam no repositório do app (`tools/mercado/exemplos/`); refazer aqui
  (`python3 tools/papel/falso.py`) e copiar para lá (`tools/mercado/exemplos/papel/`) quando o formato mudar.
- Os workflows (`mercado.yml`, `papel.yml`, `memes.yml`, `ideias.yml`) religam os agendamentos pela API a cada rodada (num
  repositório público o GitHub os desliga depois de 60 dias sem atividade).

## Commits

Mensagens em português; terminar com as linhas de atribuição pedidas pela sessão.
