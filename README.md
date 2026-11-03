# Órbita · testes de mercado no papel

Simulações de formas arriscadas de "investir" em cripto, **só no papel**: saldos fictícios de US$ 1.000, nenhuma
conta, nenhuma ordem, nenhuma chave de negociação, nenhum segredo. Só APIs públicas de leitura. Os resultados são lidos
pelo app pessoal Órbita (Finanças → Testes).

Nada aqui é recomendação de investimento. O papel não mostra boa parte dos riscos reais (cada forma lista os seus).

## O que roda

| Workflow | Quando | Ramo de saída | O que é |
|---|---|---|---|
| `mercado.yml` | a cada 2 h | `mercado` | cópia de carteiras da Hyperliquid (copy trading), `tools/mercado/` |
| `papel.yml` | a cada 6 h | `papel` | as outras formas (cofres, funding, robôs de grade e DCA…), `tools/papel/` |

Os ramos de saída são órfãos e levam um commit só (forçado a cada rodada): `resumo.json`/`<forma>.json` para o app,
`estado.json` para a rodada seguinte e `log.txt`.

Planos: `docs/plano-testes-mercado.md` (copy trading) e `docs/plano-testes-mercado-2.md` (as outras formas).

## Testar

```
python3 tools/mercado/teste_mercado.py     # copy trading, com o mercado de mentira
python3 tools/papel/teste_papel.py         # as outras formas
```
