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
- Os exemplos que o app usa sem rede ficam no repositório do app (`tools/mercado/exemplos/`); refazer aqui e copiar
  para lá quando o formato mudar.
- Os dois workflows religam os agendamentos pela API a cada rodada (num repositório público o GitHub os desliga
  depois de 60 dias sem atividade).

## Commits

Mensagens em português; terminar com as linhas de atribuição pedidas pela sessão.
