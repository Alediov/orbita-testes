# Testes de mercado: cópia de carteiras da Hyperliquid no papel

Só simulação: nenhuma ordem, nenhuma conta, nenhuma chave. Só a API pública de leitura. Plano completo em
`docs/plano-testes-mercado.md` (as outras formas: `docs/plano-testes-mercado-2.md`).

## Arquivos

- `hl.py`: cliente de leitura (`POST api.hyperliquid.xyz/info` e o ranking `stats-data.hyperliquid.xyz/Mainnet/leaderboard`),
  com o balde de peso (1.200/min na API; usamos 1.100) e as páginas.
- `sim.py`: a conta fictícia (fração do patrimônio da carteira, margem isolada, atraso, deslize, taxa de 0,045%,
  financiamento de hora em hora, liquidação pela manutenção = metade da margem inicial na alavancagem máxima).
  Variantes, só com 3× e 5× nos dois atrasos (chaves `3x1s`, `5x5l`…): `s` saídas de segurança (fecha a posição aberta
  há mais de 3 dias ou que perder 5% da conta; fica fora da moeda até a carteira abrir uma operação nova), `l` ordem
  limite no melhor caso (taxa de 0,015% e sem deslize nas operações em que a carteira usou ordem limite) e `m` só as
  moedas boas. Desde 19h43 (02/11/2026), mais dois jeitos de dimensionar: `a2`/`a3` **amplificada** (o dobro ou o
  triplo da fração da carteira, sempre até a alavancagem da conta e a máxima da moeda), só com 5× e 10× (com 3×, o
  triplo de uma carteira que já põe 100% bateria no teto quase sempre e as duas versões dariam o mesmo que a de 3×), e
  `f` **entrada fixa** (cada abertura ou aumento dela usa US$ 50 de margem × a alavancagem; redução e fechamento na
  mesma proporção que ela; virar de lado fecha e abre com a margem fixa; sem caixa, não entra e conta `semCaixa`), com
  2×, 5× e 10×. Eram **34 contas por carteira** (8 + 12 + 8 + 6) até 09/11/2026; agora 18 (ver a revisão abaixo). Cada conta conta também os ganhos e as perdas dos
  fechamentos (`gm`, `pm` no resumo: ganho médio e perda média; as contas de antes de 19h50 contam só daí em diante).
  Desde 09/11/2026 cada conta do `aoVivo` no `resumo.json` traz também `metricas` (CDI no mesmo período, excesso, ao
  mês, Sharpe contra o CDI…), as mesmas das outras formas (`tools/papel/conta.py`, formato em `tools/papel/FORMATO.md`).
- **Revisão de 09/11/2026** (pedido do Alediov, com os dados de 02 a 09/11: o teste de antes dava +37% em média contra
  ~+1% ao vivo, o 10× quebrava, o atraso de 5 min dava quase igual ao de 1 min, robôs +4% × pessoas −5% ao vivo):
  - **Enxugar** (`combos()`, 34 → **18 contas por carteira**): saiu o 10× (também nas versões ×2, ×3 e fixa) e o atraso de
    5 min, menos o controle `3x5`; todas as versões só com 1 min. `enxugar(est)` tira do estado as contas que saíram; as
    que ficam seguem com o histórico. `config.combos` no resumo diz quais existem (o app aguenta o resumo antigo).
  - **Parar de copiar quem afunda** (`p20`, `p25`, `p30` em sim.py, `limite_parada`): como a proporcional, mas confere o
    patrimônio da cópia de hora em hora e, 20/25/30% abaixo do melhor momento da cópia, fecha tudo a mercado e larga a
    carteira para sempre (`parou` {em, queda, patrimonio} no resumo, operação "parou" nas últimas). 25% é o padrão
    (3× e 5×); 20% e 30% só com 3×.
  - **Carteiras de carteiras** (`agregadas.py`, refeitas do zero a cada rodada pelo `banco` do estado: a série 3× · 1 min
    de toda carteira que já foi seguida, com o começo, o fim e o selo): **As 5 melhores** (toda semana as 5 de maior % ao
    mês ao vivo, com 7+ dias), **Só robôs** e **Só pessoas** (selo de agora), partes iguais, troca semanal com 0,15% de
    custo por dólar que sai ou entra. Nasceram com a história desde 02/11/2026 (menos as carteiras que saíram antes de o
    banco existir). E o **Consenso**: uma conta de 3× e 1 min que só fica numa moeda com 2+ carteiras do mesmo lado (e mais
    que do outro), 30% da conta por moeda (sim.Conta). Tudo em `agregadas` no resumo, com `metricas`.
  - **Teste fora da amostra** (`passado.py`, `passado` no resumo, "aproximado"): a regra de escolha aplicada aos dados de
    60 a 30 dias atrás e a cópia simulada nos 30 dias seguintes, que ela não viu. O ranking público só tem o "agora",
    então o ranking de T0 é refeito pelo `portfolio` desde o começo de cada candidata (conta e lucro em T0) e pelas
    execuções (volume); universo = as linhas do ranking de hoje com volume total ≥ US$ 10 mil (o volume só cresce),
    amostra sorteada de até 3.000; mesmos filtros, risco e nota; 30 escolhidas (as 60 primeiras aprovadas pela nota do
    ranking, as 30 de maior nota). Anda aos poucos nas sobras das rodadas (até 7 min por rodada; fases pre → fino →
    copia → pronto) e refaz a cada 7 dias (`rodadas`). Limitações: viés de sobrevivência (quem sumiu do ranking não
    entra), histórico espaçado do `portfolio` (o ponto mais perto de T0, até 5 dias), só as 10.000 execuções mais
    recentes de cada carteira na API, velas de 1 h na escolha e de 15 min na cópia, selo e cofre de hoje. O teste de
    antes de cada carteira (`historico`) ficou, renomeado no app "no período da escolha (otimista)", e o resultado traz
    o `previsto` (a média desse teste nas escolhidas) para comparar.
  - **Risco reavaliado**: as carteiras sem `risco`/`nota` (escolhidas antes da medida) vêm primeiro em `atualizar_perfis`
    (`reavaliar_risco`: execuções dos últimos 30 dias e o `portfolio`; só alerta, nunca sai por isso).
- `carteiras.py`: o ranking, os filtros (`CRITERIOS`), as medidas (operações por dia, tempo médio de posição, fração
  passiva…), os motivos de cada escolha, a `nota_escolha` (teste no histórico + fração com ordem limite − alertas), as
  `moedas_boas` (pelas execuções de ANTES da cópia, `MIN_OPS_MOEDA` ordens com resultado e lucro) e o `risco` contra o
  "quase nunca perde" (`RISCO`: pior perda ÷ ganho médio, queda do lucro do pico ao fundo, tempo da pior posição no
  vermelho; recusa as novas acima do limite folgado, alerta acima do menor; as já seguidas só ganham o alerta). A
  `nota_ranking` dá peso cheio ao giro de 3× a 100× a conta por mês (`giro_regular_min/max`) e metade fora dele (sem
  recusar: as recusas continuam só abaixo de 1× e acima de 300×). `selo` dá o palpite robô/humano provável (≥ 10
  operações por dia, posição média < 3 h ou ≥ 70% em ordem limite → robô) para o filtro do app.
- `mercado.py`: a rodada (ao vivo → escolha semanal com teste no histórico → bitcoin e CDI → `resumo.json`). A escolha
  analisa até `ANALISAR` (80) candidatas NOVAS por vez, na ordem da nota do ranking; as recusadas ficam 7 dias de fora
  (`recusadas` + `recusaMotivo`, no resumo como `quarentena`), então a próxima escolha olha as seguintes da fila; com
  menos de 20 seguidas, tenta de novo uma vez por dia. `analisadasSemana` conta as analisadas nos últimos 7 dias
  (`funil.semana`). O resumo traz também `encerradas` (as que saíram, com o motivo e o resultado em 3× e 1 min). As
  carteiras seguidas antes de uma versão nova ganham as contas que faltam no cursor e, uma vez (`histVersao`), o teste
  no histórico delas, se sobrar tempo na rodada (até 4 min antes do prazo).
- `perfil.py` (02/11/2026, 22h27): o perfil de cada carteira pelas execuções dos 30 dias, sem pedido a mais (só as
  velas de 15 min, sem financiamento). Robô × pessoa por 6 sinais com peso (s de −1 a +1): a) "não dorme" (a maior
  pausa do dia, em horas UTC quase sem operação: ≤ 2 h robô, ≥ 6 h pessoa; peso 2), b) tamanhos repetidos (o mesmo
  tamanho ou o mesmo valor em US$ com até 0,5% em ≥ 50% das entradas), c) relógio (intervalos com coeficiente de
  variação < 0,25 ou ≥ 60% das entradas em :00/:15/:30/:45; quem opera 1× por dia também é "regular", por isso o
  limite baixo), d) grade (≥ 4 ordens limite na mesma hora com o mesmo espaço), e) preço redondo nas ordens limite
  (3 algarismos: gente digita 62.300) e f) ordens a menos de 3 s uma da outra. Nota = 50 + 50 × média ponderada;
  ≥ 80 "robô (quase certo)", ≥ 62 "robô provável", ≥ 38 "não dá para dizer", senão "humano provável". `selo` (o campo
  antigo) vira "robo", "humano" ou "incerto". Os "parâmetros": moedas, a menor janela de horas com 85% das operações,
  a variação mediana de preço da entrada à saída nos ganhos e nas perdas, se aumenta a posição com o preço contra
  (≥ 30% dos negócios: martingale, risco), o tamanho típico em % do patrimônio e a alavancagem efetiva (percentil 90),
  o lado, o que o preço fez nos 15 e 60 min antes das entradas (contra, segue ou rompimento) e o tempo típico; a
  frase-resumo; e o mapa hora × dia (Brasília). Restos de posição abaixo de US$ 1 contam como zero.
- `imitador.py`: só nos robôs (nota ≥ 62) com ≥ 10 negócios. Regras: moedas (≥ 3 negócios no treino), gatilho (o preço
  andou ≥ limiar em 15/30/60/120 min, contra ou a favor), lados (≥ 25%), alvo e stop pelas medianas, tempo máximo pelo
  3º quartil (até 3 dias). Ajuste pela melhor F1 nos primeiros 20 dias (grade de 2 modos × 4 janelas × 9 limiares,
  velas de 15 min); conferência nos 10 últimos: acerto (entradas reais com uma dele na mesma moeda e lado a até
  30 min), inventadas e uma conta de US$ 1.000 a 3× sem atraso; `copiaTeste` = a cópia proporcional 3× · 1 min nos
  mesmos dias. `ok` só com acerto ≥ 40% e precisão ≥ 25%; senão a tela diz "não deu para descobrir as regras".
  Quando roda: na análise da escolha (as velas do teste no histórico já estão baixadas) e em `atualizar_perfis`
  (mercado.py), que refaz até `PERFIS_POR_RODADA` (3) perfis por rodada, os mais velhos, cada carteira no máximo 1×
  por dia e só com 3 min de folga no prazo: com 30 carteiras e 12 rodadas, todas por dia. Peso extra ≈ 200 por
  carteira (execuções + velas de 15 min de 1 a 3 moedas).
- `falso.py`: mercado de mentira (semente fixa) com a mesma interface do cliente; `python3 tools/mercado/falso.py`
  refaz `exemplos/resumo.json`, que o app usa no navegador sem token (teste de fumaça, passos `financas-testes*`); no
  exemplo, a reavaliação vem em 1 semana e uma carteira some do ranking, para a subaba Escolha mostrar uma que saiu. As
  carteiras de mentira cobrem os três perfis: 2 é um robô de regra clara (a cada 15 min, se o preço andou ≥ 2,5% em
  60 min, entra contra com o mesmo valor; sai com +2%, −1,5% ou 12 h), 1 e 4 são gente (dormem das 23h às 9h e digitam
  preço redondo nas ordens limite) e 3 e 5 são ambíguas (a qualquer hora, tamanhos variados).
- `exemplos/`: uma resposta de cada pedido, escrita à mão no formato da documentação, e o `resumo.json` de exemplo.

## Rodar

- Testes (sem rede): `python3 tools/mercado/teste_mercado.py` (no mundo de mentira, o teste fora da amostra usa 14 + 14
  dias: `passado.JANELA = 14`) e, das contas do app, `node tools/mercado/teste_app.mjs` (o % ao mês e ao ano, a faixa, o semáforo, os gráficos, o ranking dos jeitos e a linha do tempo)
- Uma rodada no mercado de mentira: `python3 tools/mercado/mercado.py --dados /tmp/m --exemplos`
- De verdade: o workflow "Testes de mercado (Hyperliquid, no papel)" (`.github/workflows/mercado.yml`), a cada 2 h e à
  mão (com "Refazer a escolha"). Grava `estado.json`, `resumo.json` e `log.txt` no ramo órfão `mercado` (commit único,
  forçado). O resumo de cada rodada também sai como anotação (`::notice::`). Daqui do Claude a Hyperliquid não abre
  (proxy); só pelo Actions. Tempo: a rodada comum (só o ao vivo) leva cerca de 1 min; a da escolha, até ~13 min (o
  prazo é 14); a primeira depois de uma versão nova refaz o histórico das seguidas uma vez, dentro do mesmo prazo.

## O que é aproximação

Preço das velas (de negociação, não o de marcação) interpolado dentro da vela; o patrimônio da carteira ao vivo é o
`clearinghouseState` da hora da rodada (no histórico, o `portfolio`); o teste no histórico usa velas de 15 min; a cópia
começa sem posição e entra na próxima operação da carteira em cada moeda; liquidada, volta na próxima operação dela.
Ordem limite é o melhor caso (a ordem sempre executa, ao preço da carteira). As versões das carteiras seguidas antes
delas começam na rodada em que apareceram (o app mostra a data). O resumo cresce ~3 a 4 MB por ano com 30 carteiras;
o app guarda no aparelho enquanto couber (senão, só na memória).
