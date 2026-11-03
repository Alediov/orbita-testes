# Formato dos resultados das outras formas (ramo `papel`)

O workflow `papel.yml` roda `tools/papel/papel.py` a cada 6 h e grava, num commit único do ramo órfão `papel`:

- `indice.json`: o que existe e quando cada forma rodou (o app lê primeiro e só baixa a forma que mudou);
- `<forma>.json`: um por forma (`cofres.json`, `funding.json`, `robos.json`; depois `looping.json`, `opcoes.json`,
  `pools.json`, `memes.json`);
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

### extra (o que o app conhece)

- funding: `recebido`, `pago` (US$ de financiamento), `base` (diferença média entre à vista e perpétuo, fração),
  `fundingAno` (taxa média anualizada no período), `moeda` (a da posição agora, no rodízio), `dentro` (true/false na
  seletiva);
- robôs: `comprado` (US$ na moeda agora), `caixa` (US$), `degrausExecutados`, `precoMedio`, `foraDaGrade` (true/false);
- cofres: `cofres` (quantos na versão), `travadoAte` (ms; não dá para sair antes), `comissaoPaga` (US$).

## estado.json

Livre por forma: `{ "v": 1, "formas": { "<forma>": { … } } }`. Cada módulo guarda o que precisa (contas abertas,
cursores de horário, escolha dos cofres). Mudar o formato de uma forma: subir a `VERSAO` dela; o módulo decide se
recomeça ou converte.

## Exemplos

`python3 tools/papel/falso.py <pasta>` roda as formas num mercado de mentira (semente fixa) e grava o mesmo conjunto
de arquivos com `"exemplo": true`; o app (repositório odonto-quest) usa a cópia em `tools/mercado/exemplos/papel/`.
