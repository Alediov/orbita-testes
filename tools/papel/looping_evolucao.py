"""Evolução do Looping, NO PAPEL (pedido do Alediov, 25/11/2026: o 3º do plano docs/plano-evolucao.md do repositório do
app, "faremos uma por uma").

Duas espécies, porque as contas são medidas em coisas diferentes e não dá para comparar uma com a outra:

- **Laço** (wstETH × ether, medido em ether como as versões `wst*`; controle `wst3`). Genes: `alav` (1,5 a 6×, a regra
  dele: 6× só no looping), `regra` (sempre montado | só quando compensa) e, no "quando compensa", `entra` (a diferença
  staking − juro do ether, por × a mais, para montar), `diasEntra` (a média de quantos dias), `pagaDias` (o ganho extra
  desses dias precisa pagar montar e desmontar), `sai` (abaixo disso desmonta), `diasSai`, `dispara` (o juro do dia
  acima do staking por isso desmonta já) e `fica` (fica montado pelo menos).
- **Ether alavancado** (ETH × USDC, em dólar; controle `eth2`). Genes: `alav` (1,25 a 3×), `regra` (sempre | só na
  alta, acima da média de `media` dias, com o dólar no Aave fora dela) e `defesa` (desalavanca quando o fator de saúde
  cai a 1,2/1,3/1,5; 0 = sem).

As contas são refeitas pela própria `looping.Conta`, um passo por dia, pelas velas de 1 dia do ether e pelas taxas
diárias do Aave e do staking que a forma já guarda (`est["taxas"]`): nenhum pedido a mais. O controle é a versão `wst3`
ou `eth2` REFEITA aqui (é o mesmo jeito do teste no passado da forma, de 1 dia em 1 dia; o ao vivo da forma anda de
hora em hora e não bate centavo a centavo).

O laboratório e a liga são os do motor comum (`evolucao_series.py`), uma vez para cada espécie (estado em
`est["evolucoes"][id]["evolucao"]`); a saída `looping.json` → `evolucao` traz as duas espécies (FORMATO.md,
"Evolução"). Teste: `teste_looping_evolucao.py`.
"""
from __future__ import annotations

import bisect

import evolucao_series as ES
import looping as LP
from conta import CAPITAL, DIA, cdi_ano_da_serie, dia_de, metricas
from genetica import reparar

VERSAO = 1
CDI_PADRAO = 0.149
MIN_DIAS = 60             # menos que isso de velas e taxas: sem as espécies ainda

FRASE = ("Versões do looping que evoluem: toda semana as piores regras saem, as melhores se cruzam e, às vezes, um gene "
         "muda. Só no papel.")
AVISOS = ["Só no papel: nenhuma carteira, nenhum depósito, nenhum empréstimo.",
          "As contas andam um passo por dia, pelas velas de 1 dia do ether e pelas taxas médias de cada dia do Aave e do "
          "staking: a liquidação confere a mínima do dia, mas os picos de juro de poucas horas não aparecem.",
          "O Laço (wstETH × ether) é medido em ether, como as versões da forma: compare com o \"Só wstETH\", não com o "
          "CDI. O Ether alavancado é em dólar e sobe e cai com o ether.",
          "Os controles são o wstETH 3× e o ETH 2× refeitos por este simulador."]

ESP_LACO = {
    "id": "laco", "nome": "Laço", "icone": "🔁", "prefixo": "w", "controle": "wst3",
    "frase": "Deposita wstETH, toma ether e deposita de novo: a alavancagem e quando montar e desmontar o laço evoluem "
             "(medido em ether).",
    "genes": [
        {"k": "alav", "nome": "Alavancagem", "tipo": "num", "min": 1.5, "max": 6, "passo": 0.5, "un": "×", "neutro": 3},
        {"k": "regra", "nome": "Montado", "tipo": "op", "opcoes": ["sempre", "compensa"],
         "rotulos": {"sempre": "Sempre", "compensa": "Só quando compensa"}, "neutro": "sempre"},
        {"k": "entra", "nome": "Monta com diferença de", "tipo": "op", "opcoes": [0.0, 0.0025, 0.005, 0.01, 0.02],
         "un": "%", "neutro": LP.AUTO_ENTRA, "so": {"regra": "compensa"}},
        {"k": "diasEntra", "nome": "Média de", "tipo": "op", "opcoes": [3, 7, 14, 30], "un": "d",
         "neutro": LP.AUTO_DIAS_ENTRA, "so": {"regra": "compensa"}},
        {"k": "pagaDias", "nome": "Paga a ida e a volta em", "tipo": "op", "opcoes": [30, 60, 120, 365], "un": "d",
         "neutro": LP.AUTO_PAGA_DIAS, "so": {"regra": "compensa"}},
        {"k": "sai", "nome": "Desmonta abaixo de", "tipo": "op", "opcoes": [-0.005, 0.0, 0.0025, 0.005], "un": "%",
         "neutro": LP.AUTO_SAI, "so": {"regra": "compensa"}},
        {"k": "diasSai", "nome": "Média para desmontar", "tipo": "op", "opcoes": [3, 7, 14], "un": "d",
         "neutro": LP.AUTO_DIAS_SAI, "so": {"regra": "compensa"}},
        {"k": "dispara", "nome": "Desmonta já com o juro acima por", "tipo": "op", "opcoes": [0.01, 0.02, 0.04],
         "un": "%", "neutro": LP.AUTO_DISPARA, "so": {"regra": "compensa"}},
        {"k": "fica", "nome": "Fica montado pelo menos", "tipo": "op", "opcoes": [7, 14, 30, 60], "un": "d",
         "neutro": LP.AUTO_FICA_DIAS, "so": {"regra": "compensa"}},
    ],
}
ESP_ETH = {
    "id": "alavancado", "nome": "Ether alavancado", "icone": "📈", "prefixo": "x", "controle": "eth2",
    "frase": "Deposita ether, toma dólar e compra mais ether: a alavancagem, ficar só na alta (e a média) e a defesa "
             "evoluem (em dólar).",
    "genes": [
        {"k": "alav", "nome": "Alavancagem", "tipo": "num", "min": 1.25, "max": 3, "passo": 0.25, "un": "×",
         "neutro": 2},
        {"k": "regra", "nome": "Fica alavancado", "tipo": "op", "opcoes": ["sempre", "alta"],
         "rotulos": {"sempre": "Sempre", "alta": "Só na alta"}, "neutro": "sempre"},
        {"k": "media", "nome": "Acima da média de", "tipo": "op", "opcoes": [20, 50, 100, 200], "un": "d",
         "neutro": LP.MEDIA_DIAS, "so": {"regra": "alta"}},
        {"k": "defesa", "nome": "Defesa no fator de saúde", "tipo": "op", "opcoes": [0, 1.2, 1.3, 1.5],
         "rotulos": {"0": "Sem"}, "neutro": 0},
    ],
}
AUTO = ("entra", "diasEntra", "pagaDias", "sai", "diasSai", "dispara", "fica")


def _cfg(vid):
    return next(c for c in LP.VERSOES if c[0] == vid)


class Definicao:
    """Uma das duas espécies como o motor comum espera."""
    versao = VERSAO

    def __init__(self, esp):
        self.esp = esp
        laco = esp["id"] == "laco"
        self.nome_controle = "wstETH 3×" if laco else "ETH 2×"
        self.da_liga = "do laço" if laco else "do ether alavancado"
        self.rotulo = "looping, " + esp["nome"].lower()

    def genes_controle(self):
        return reparar(self.esp, {g["k"]: g["neutro"] for g in self.esp["genes"]})

    def sementes(self):
        b = self.genes_controle()
        if self.esp["id"] == "laco":
            ms = (("wst6", {"alav": 6}), ("wstAuto3", {"regra": "compensa"}),
                  ("wstAuto6", {"alav": 6, "regra": "compensa"}), ("wst15", {"alav": 1.5}))
        else:
            ms = (("eth15", {"alav": 1.5}), ("eth2def", {"defesa": 1.3}), ("eth2tend", {"regra": "alta"}),
                  ("eth3tend", {"alav": 3, "regra": "alta"}))
        return [(de, reparar(self.esp, {**b, **m})) for de, m in ms]

    def descrever(self, genes):
        x = f"{genes['alav']:g}".replace(".", ",") + "×"
        pc = lambda v: f"{v * 100:g}".replace(".", ",") + "%"  # noqa: E731
        if self.esp["id"] == "laco":
            if genes["regra"] == "sempre":
                return f"Laço de {x}, sempre montado"
            return (f"Laço de {x} quando a diferença passa de {pc(genes['entra'])} ({genes['diasEntra']} dias) e paga "
                    f"em {genes['pagaDias']} dias; sai abaixo de {pc(genes['sai'])} ({genes['diasSai']} dias) ou com o "
                    f"juro {pc(genes['dispara'])} acima; fica {genes['fica']} dias")
        t = f"Ether {x}" + (", sempre" if genes["regra"] == "sempre" else f", só acima da média de {genes['media']} dias")
        return t + (f", defesa em {str(genes['defesa']).replace('.', ',')}" if genes["defesa"] else "")


# ====================================================================== os dados
class Dados:
    """As velas de 1 dia do ether e as taxas diárias para o simulador de uma das espécies."""

    def __init__(self, esp, diarias, tx, params, min_dias=MIN_DIAS):
        self.esp, self.diarias, self.tx, self.params = esp, list(diarias or []), tx, params
        self.min_dias = min_dias
        self.ts = [x[0] for x in self.diarias]
        ini = (self.diarias[-1][0] - (LP.HIST_DIAS + 1) * DIA) if self.diarias else 0
        jan = [x for x in self.diarias if x[0] >= ini]
        self.primeiro = dia_de(jan[0][0] - 1) if jan else None

    @property
    def tem_dados(self):
        return bool(self.tx) and bool(self.params) and len(self.diarias) >= self.min_dias

    def simular(self, genes, inicio, hoje):
        return simular(self, genes, inicio, hoje)

    @staticmethod
    def extras(c):
        return {"membros": c["membros"], "custos": c["custos"], "largadas": c["desmontagens"], "nLiq": c["liq"]}


def conta_de(esp, genes, inicio, params):
    """A `looping.Conta` de uma versão com estes genes."""
    if esp["id"] == "laco":
        opc = {"auto": genes["regra"] == "compensa", **{k: genes[k] for k in AUTO}}
        cfg = ("ev", "ev", "wst", float(genes["alav"]), None, "médio", "")
    else:
        opc = {"tend": genes["regra"] == "alta", "media": genes["media"]}
        cfg = ("ev", "ev", "eth", float(genes["alav"]), genes["defesa"] or None, "alto", "")
    return LP.Conta(cfg, inicio, params, opc=opc)


def simular(D, genes, inicio, hoje):
    """A conta de uma versão de `inicio` a `hoje` (dias de Brasília; os passos são as velas de 1 dia UTC que terminam
    nesses dias), um ponto por dia: { serie, retorno, piorQueda, ops (montar e desmontar), montou, custos, liq,
    desmontagens, membros }."""
    jan = [x for x in D.diarias if inicio <= dia_de(x[0] - 1) <= hoje]
    if not jan:
        return {"serie": [], "retorno": 0.0, "piorQueda": 0.0, "ops": 0, "montou": False, "custos": 0.0, "liq": 0,
                "desmontagens": 0, "membros": []}
    c = conta_de(D.esp, genes, jan[0][0], D.params)
    media = genes.get("media", LP.MEDIA_DIAS)
    ant = None
    for t, p, mi in jan:
        tend = LP.media_movel(D.diarias, t - 1, dias=media) if c.tend else None
        c.passo(t, DIA if ant else 0, p, mi, D.tx, tend=tend)
        ant = t
    serie = [[d, round(v, 2)] for d, v in sorted(c.curva.serie.items())]
    vals = [v for _, v in serie]
    pico, queda = 0.0, 0.0
    for v in vals:
        pico = max(pico, v)
        queda = max(queda, 1 - v / pico if pico > 0 else 0.0)
    fim = vals[-1] if vals else CAPITAL
    acc = c.acc
    if c.tipo == "wst":
        membros = [f"laço de {c.L:g}×".replace(".", ",") if c.L > 1 else "só wstETH (1×)"]
    else:
        membros = ["em dólar no Aave (fora)" if c.L == 0 else f"ether {c.L:g}×".replace(".", ",")]
    custos = acc["troca"] + acc["desl"] + acc["rel"] + acc["gas"]
    return {"serie": serie, "retorno": round(fim / CAPITAL - 1, 5), "piorQueda": round(queda, 4),
            "ops": int(1 + acc["montagens"] + acc["desmontagens"]), "montou": True, "custos": round(custos, 2),
            "liq": len(c.curva.liq),
            "desmontagens": int(acc["desmontagens"] + acc["defesas"]), "membros": membros}


# ====================================================================== a rodada
def _met(ctx):
    cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}

    def f(c):
        return metricas(c, cdi, cdi_ano_da_serie(cdi, CDI_PADRAO))
    return f


def avancar(ctx, est, agora, diarias, tx, params):
    """O laboratório e a liga das duas espécies. Devolve o bloco `evolucao` do looping.json (None sem dados)."""
    blocos = []
    P = ES.parametros(bool(getattr(ctx, "exemplo", False)))
    lugar = est.setdefault("evolucoes", {})
    for esp in (ESP_LACO, ESP_ETH):
        D = Dados(esp, diarias, tx, params, 20 if getattr(ctx, "exemplo", False) else MIN_DIAS)
        if not D.tem_dados:
            continue
        sub = lugar.setdefault(esp["id"], {})
        ev = ES.rodar(sub, Definicao(esp), D, agora, P, ctx.log)
        blocos.append(ES.resumo(ev, D, agora, "looping", "Looping", FRASE, AVISOS, _met(ctx), VERSAO,
                                dias=len(D.diarias)))
    if not blocos:
        return None
    out = blocos[0]
    for b in blocos[1:]:
        out["formas"][0]["especies"] += b["formas"][0]["especies"]
        out["eventos"] = sorted(out["eventos"] + b["eventos"], key=lambda e: -(e.get("em") or 0))[:80]
    return out


__all__ = ["avancar", "simular", "conta_de", "Dados", "Definicao", "ESP_LACO", "ESP_ETH"]
