# Testes de mercado com saldo fictício

Pedido do Alediov (30/10/2026): antes de qualquer operação real, só testes com dinheiro de mentira; importa saber se a
estratégia dá lucro e quanto, comparado com comprar e segurar e com o CDI, já descontando taxas. Verba real, se um dia
houver: os 5% do rendimento (`TESTES_PADRAO` em contas.js), risco alto aceito. **Agora: nada de dinheiro, nada de conta,
nada de chave de API de negociação.**

## O plano novo (02/11/2026): cópia de carteiras da Hyperliquid no papel

Palavras dele: "o que penso é em trading… copy trading de criptomoedas, se conseguirmos ver/acompanhar o histórico de
determinadas carteiras, poderíamos simplesmente copiar as operações com um atraso, ou melhor, sabendo que são bots,
descobrir os parâmetros por trás das operações." Escolhas: **Hyperliquid** (as operações de toda carteira são públicas
e a API de leitura é aberta) e "ver simulações com diferentes alavancagens. Tudo inicialmente serão só simulações."

Feito em `tools/mercado/` (LEIA-ME lá) + `.github/workflows/mercado.yml` + Finanças → aba **Testes**
(`app/js/financas/testes.js`).

### Escolha das carteiras (toda semana)

1. O ranking público (`stats-data.hyperliquid.xyz/Mainnet/leaderboard`, o mesmo da página Leaderboard do site).
2. Pré-filtro só pelo ranking: conta ≥ US$ 10 mil; lucro positivo em 30 dias e no total; lucro do mês ≤ 150% da conta
   (acima: aposta ou depósito recente); volume do mês entre 1× e 300× a conta (abaixo, parada; acima, formador de
   mercado ou alta frequência); nome sem "vault"/"HLP". O `roi` do ranking usa outra base (US$ 210 de lucro numa conta
   de US$ 85 mil saía +210%): o app usa lucro ÷ conta.
3. As 80 melhores NOVAS (ganho do mês até 100% × log do tamanho da conta, mais um pouco da semana; desde 19h43, peso
   cheio para giro de 3× a 100× a conta por mês e metade fora disso) são analisadas pelas
   execuções dos últimos 30 dias (`userFillsByTime`, até 2.000): ≥ 10 operações, ≤ 48 por dia, tempo médio de posição
   ≥ 1 h (com ≥ 3 posições fechadas; robôs de velocidade não dá para copiar com 1 a 5 min de atraso), ≥ 80% do volume
   em perpétuos; só quem passa gasta o `userRole` (sai cofre) e o `portfolio`.
4. As aprovadas passam pelo **teste no histórico** (a mesma cópia nos 30 dias antes, velas de 15 min) e entram pela
   ordem do resultado com 3× e 1 min, até 30 seguidas. Cada uma guarda por que entrou (`motivos`).
5. Quem já é seguida fica pelo menos **4 semanas**; depois é reavaliada (sai se não passar mais ou sumir do ranking).
   Recusadas não são analisadas de novo por 7 dias (quarentena, com o motivo): a escolha seguinte anda pela fila da
   nota. Com menos de 20 seguidas, tenta de novo uma vez por dia. O funil guarda quantas foram analisadas nos últimos
   7 dias (`funil.semana`), mostrado no app.

### A cópia no papel (sim.py)

Por carteira, **8 contas fictícias de US$ 1.000**: alavancagem 1×, 3×, 5× e 10× × atraso de 1 e 5 min.

- A cada operação da carteira (execuções da mesma moeda em até 60 s), a conta põe a sua posição naquela moeda na
  **mesma fração do patrimônio** que a carteira tem (posição depois × preço ÷ valor da conta dela). O valor da conta:
  ao vivo, o `clearinghouseState` da rodada; no histórico, o `portfolio` (perpétuos, semana + mês).
- **Garantia isolada** por posição: margem = valor ÷ alavancagem (a menor entre a da conta e a máxima do ativo, `meta`);
  sem caixa livre, a posição fica menor. Ou seja: a alavancagem é o teto da exposição e o tamanho da margem; com a
  carteira usando pouca exposição, 3×, 5× e 10× têm o mesmo resultado até a liquidação (só o risco muda).
- **Preço** = o do mercado no instante da operação + atraso (vela de 1 min que contém o instante, interpolada) piorado
  em 0,05% (BTC, ETH) ou 0,10% (o resto). **Taxa** de quem tira liquidez no nível base: 0,045%. Mínimo de US$ 10 por
  ajuste (fechar sempre vale).
- **Financiamento** de hora em hora (`fundingHistory`): comprado paga a taxa positiva, vendido recebe; sai da margem.
- **Liquidação**: manutenção = metade da margem inicial na alavancagem máxima do ativo (documentação de margem);
  conferida pelas máximas e mínimas das velas (na vela da entrada, só o fechamento). Liquidada, perde a margem
  daquela posição, registra e segue com o resto; volta à moeda na próxima operação da carteira.
- A cópia ao vivo começa **sem posição** e entra na próxima operação da carteira em cada moeda.

### Versões para comparar (aprovadas pelo Alediov em 02/11/2026, 19h08)

Só com 3× e 5×, nos dois atrasos, ao lado das 8 contas de sempre (20 por carteira; nenhuma rede a mais, só conta):

1. **Saídas de segurança** (`3x1s`…): tempo máximo (fecha a posição aberta há mais de 3 dias) e stop financeiro
   (fecha se a posição perder mais de 5% do patrimônio da conta na entrada; conferido pelas velas, antes da liquidação
   se o preço chegar primeiro nele). Depois de sair (ou de uma liquidação), fica fora daquela moeda até a carteira
   ABRIR uma operação nova nela (sair do zero ou virar de lado); aumentar a posição antiga não conta.
2. **Ordem limite** (`3x1l`…, melhor caso): nas operações em que a carteira usou ordem limite (a maior parte do volume
   com `crossed` false), taxa de quem deixa ordem no livro (0,015%) e sem diferença de preço; nas outras, igual à
   principal. O resultado principal continua com a taxa cheia. A fração passiva também entra na nota de escolha.
3. **Só as moedas boas** (`3x1m`…): as moedas em que a carteira ganhou, com pelo menos 3 ordens com resultado, pelas
   execuções dos 30 dias ANTES do início da cópia (sem olhar o futuro). Sem teste no histórico (seria o mesmo período).
   Para as carteiras seguidas antes desta versão, as moedas saem das execuções de antes do `desde` e as contas novas
   começam na rodada em que apareceram.

### Amplificada e entrada fixa (aprovadas pelo Alediov em 02/11/2026, 19h43)

4. **Amplificada × 2 e × 3** (`5x1a2`, `10x5a3`…): o dobro ou o triplo da fração da carteira, margem isolada, sempre
   até a alavancagem da conta e a máxima do ativo. Só com **5× e 10×**: com 3×, o triplo de uma carteira que já põe
   100% do patrimônio bateria no teto da conta quase sempre, e as versões ficariam iguais à de 3×.
5. **Entrada fixa "como no vídeo"** (`2x1f`, `5x5f`, `10x1f`…): cada operação nova da carteira (abrir ou aumentar)
   entra com US$ 50 de margem × a alavancagem (2×, 5× e 10×), sem olhar a fração dela; reduzir e fechar na mesma
   proporção que ela; virar de lado fecha e abre de novo com os US$ 50; sem caixa para a margem e a taxa, não entra
   (conta como `semCaixa`).

34 contas por carteira. As carteiras já seguidas ganham as contas novas no cursor e o teste no histórico delas uma vez.

### Contra o "quase nunca perde" (nas próximas escolhas)

Carteiras que ganham pouco quase sempre e seguram as perdas até virarem um tombo. Medidas nas execuções dos 30 dias e
nas velas do teste no histórico: a maior perda numa ordem ÷ o ganho médio (alerta > 10×, recusa > 25×), a maior queda
do lucro acumulado do pico ao fundo ÷ a conta (`portfolio`; alerta > 30%, recusa > 50%) e o tempo que a pior posição
ficou com o preço contra a entrada média, contando a ainda aberta (alerta > 4 dias, recusa > 10 dias). A recusa vale
para as candidatas novas (o motivo vai no funil, ex. "a pior perda é 44× o ganho médio"); cada alerta tira 0,3 da nota;
as já seguidas não saem por isso, só ganham o alerta no app.

Nota de escolha: teste no histórico (3× e 1 min, entre −100% e +300%) + 0,2 × fração com ordem limite − 0,3 por alerta.

### Referências

Comprar e segurar bitcoin com os mesmos US$ 1.000 (velas diárias) e o **CDI** (série 12 do Banco Central; sem ela,
14,9% ao ano nos dias úteis; `--cdi` muda). No app, as duas são reescaladas para US$ 1.000 no dia em que cada carteira
começou a ser seguida.

### Rodar e guardar

1ª rodada de verdade (02/11/2026): 48.138 carteiras no ranking → 2.380 no pré-filtro → 45 analisadas → 5 aprovadas
(pela ordem do `roi`: contas pequenas de +200% a +350%, o que levou ao filtro de 150% e à nota pelo tamanho). 2ª
(recomeçada do zero com a escolha nova): 48.139 → 2.354 → 80 analisadas → 6 aprovadas, 263 pedidos, 13 min. Recusas
mais comuns entre as analisadas: poucas operações em 30 dias, poucas posições fechadas, fora dos perpétuos e robôs de
velocidade.

Workflow a cada 2 h (`17 */2 * * *`) e à mão (com "Refazer a escolha" e "Recomeçar do zero"); ~420 min/mês do Actions (cálculo no topo do
.yml; limite combinado: 800). Grava `estado.json`, `resumo.json` e `log.txt` no ramo órfão **`mercado`** num commit
único forçado (sem histórico; nunca mesclado na main). A frequência não muda o resultado: a cópia usa as velas do
horário de cada operação; as velas de 1 min existem por ~3,5 dias (depois, 5 e 15 min).

### Perfil, robô × pessoa e o imitador (pedido do Alediov, 02/11/2026, 22h27)

`perfil.py`: seis sinais com peso pelas execuções dos 30 dias ("não dorme", tamanhos repetidos, relógio, grade,
preço redondo, velocidade) → nota de 0 a 100 e os rótulos robô (quase certo) / robô provável / não dá para dizer /
humano provável, com os motivos em frases; os "parâmetros" em linguagem simples (moedas, horários, alvo e stop
típicos no preço, martingale, tamanho e alavancagem efetiva, lado, o que o preço fazia antes de entrar, tempo
típico) e uma frase-resumo; o mapa hora × dia. `imitador.py`: nos robôs, a regra mais simples de preço que explica
as entradas (janela, limiar, contra ou a favor, alvo, stop, tempo máximo), ajustada nos 20 primeiros dias e
conferida nos 10 últimos, com o acerto, as inventadas e a conta do imitador (3×, sem atraso) ao lado da cópia. Roda
na escolha e 1× por dia por carteira (3 por rodada). Com regra que acerta pouco, a tela diz que não deu.

### No app (Finanças → Testes)

Em linguagem simples desde 02/11/2026, 22h27 (ele se disse leigo; antes, 19h50, eram 6 subabas). O aviso fixo
"Simulação com saldo fictício. Nada aqui é recomendação de investimento.", o botão **Como funciona** no alto e 4 abas
(escolha em `orbita.testes.sel`; as subabas antigas migram: resumo → indo, carteiras → quem, comparar → jeitos,
operações e escolha → aconteceu):

1. **Como está indo**: "Se você tivesse copiado todas · Proporcional 3× · 1 min: +X% ao mês (estimado)", a faixa,
   "medindo há N dias", o ao ano, o CDI e a poupança no mesmo formato (poupança: 0,5% + TR ≈ 0,6% ao mês, ≈ 7,4% ao
   ano, estimativa fixa) e o semáforo ("ganhando do CDI" / "perdendo do CDI" / "ainda é cedo para saber": cedo com
   menos de 14 dias, menos de 10 operações ou a faixa cruzando o CDI); o teto (cada uma no jeito que funcionou melhor
   para ela); a carteira de carteiras × CDI × bitcoin; o % de cada mês; a queda do topo; a projeção de 1 ano (em US$
   e em reais com a verba de testes do Rendimento); as novidades em frases.
2. **Quem copiamos**: um cartão por carteira com a frase do perfil, robô/pessoa com a nota, o % ao mês, o risco
   (baixo/médio/alto pela pior queda, liquidações e alavancagem efetiva da cópia) e o jeito que funcionou melhor
   para ela; ordem e filtros. A tela da carteira: Resumo (o número grande, números com "o que quer dizer", gráficos,
   alavancagem × resultado, projeção), Jeitos (ranking + grade), O que fez (frases) e Perfil (frase, régua robô ×
   pessoa com os sinais, parâmetros, mapa de horário, imitador, por que entrou).
3. **Jeitos de copiar**: o ranking em frases ("1º Triplo 5× · 5 min: +44% ao mês · risco médio"), alavancagem ×
   resultado, o aviso de consistência em frase e a grade num "Ver detalhes".
4. **O que aconteceu**: o funil recolhível no alto e a linha do tempo em frases (comprou, vendeu, fechou com
   ganho/perda, foi liquidada, saiu por tempo ou stop, carteira entrou porque…, saiu porque…), com filtros.

% estimado: ao mês (1 + r)^(30/dias) − 1 e ao ano com 365, sobre o período escolhido; a faixa é a média ± 1,28 × o
erro dos retornos diários (percentis 10 e 90, calculada no app, sem custo no workflow; mais barata que um bootstrap e
honesta: poucos dias = faixa larga); abaixo de 7 dias, só o % do período e "cedo demais para estimar ao mês"; abaixo
de 30, "extrapolação". Em cada termo técnico, um "?" abre uma explicação de 1 ou 2 frases (`GLOSSARIO` em comum.js).
Avisos no celular (desligados por padrão) no Como funciona; nada no Meu dia. No Início, o cartão "Testes: N
carteiras à frente do CDI".

## Fase futura (só descrita): engenharia reversa dos robôs

A partir das execuções públicas de cada carteira: (1) classificar robô × discricionário (regularidade dos horários,
tamanho das ordens, proporção passiva, reação a variações de preço, atividade nas 24 h); (2) para os robôs, ajustar
modelos simples aos gatilhos (cruzamento de médias, rompimento de máximas/mínimas, volta à média por bandas, grade,
financiamento extremo) e aos parâmetros (períodos, limites, tamanho, saída por alvo/tempo/stop), escolhendo pelo
acerto de "quando entra e para que lado" fora da amostra; (3) rodar o robô reconstruído no papel ao lado da cópia,
sem atraso; (4) só então, se ele quiser, conta de teste e, muito depois, a verba de 5%.

## O plano anterior (30/10/2026), ainda válido como alternativa

Teste no histórico de estratégias clássicas (compra recorrente, grade, cruzamento de médias, momento, volta à média) e
um simulador próprio com preços reais; depois, contas de teste (Binance/Bybit testnet — a Binance bloqueia servidores
dos EUA, como o GitHub —, Alpaca paper). MetaTrader 5 demo precisa de Windows ligado o tempo todo (o PC do laboratório
NÃO serve: é da IC).
