"""Evolução: versões de cada forma que evoluem sozinhas, NO PAPEL (pedido do Alediov, 16/11/2026).

A ideia dele: "construímos algumas versões com parâmetros variáveis; depois de um ciclo (semanal) os piores são
eliminados, os melhores se cruzam, recebendo parte do pai e parte da mãe e, a depender da sorte, uma mutação", para
chegar ao melhor de cada estratégia (hoje há bons parâmetros, mas não se sabe se são os melhores). Começa pelos Robôs
(três espécies no bitcoin: grade, bandas e tendência); o copy trading vem depois.

Duas velocidades (decisão de 16/11/2026):

- **Laboratório** (no passado, "aproximado"): todo dia, com as velas de 1 h dos últimos HIST_DIAS dias, roda até
  GERACOES_DIA gerações de uma população de POP versões por espécie. Cada versão roda uma vez o período inteiro; os
  primeiros 3/4 são o TREINO, em 3 janelas (45 dias cada com 180 dias): a nota de cada janela é o retorno ao mês menos
  metade da pior queda dentro dela, e a nota da versão é a média das janelas menos metade do desvio entre elas
  (premia a constância, não um mês de sorte). O último 1/4 é a PROVA (validação): fica de fora da escolha, e só passa
  para a liga quem também for melhor que o controle nela. Menos de MIN_OPS operações = sem nota; conta liquidada = −1.
  Em cada geração ficam as SOBREVIVEM melhores; FILHAS nascem de duas sobreviventes (cada uma escolhida num torneio de
  3; cada gene vem do pai ou da mãe, sorteado, com MUT_FILHA de chance de um gene mudar); MUTANTES são cópias de uma
  sobrevivente com 1 ou 2 genes sorteados de novo; NOVATAS são sorteadas do zero (para a população não ficar toda
  igual). A primeira população tem a versão padrão de hoje e as outras versões da mesma família nos Robôs.
- **Liga** (ao vivo): POP_LIGA versões de cada espécie nas velas de 1 min, como as versões dos Robôs, e o controle (um
  clone da versão padrão de hoje, começado junto com a liga). Todo começo de semana (segunda, Brasília) cada uma ganha
  a nota da semana (retorno − ½ pior queda, pelos pontos diários); saem as SAEM_LIGA piores pela média das últimas
  SEMANAS_NOTA semanas e entram até DO_LAB aprovadas do laboratório, filhas das melhores da liga e uma mutante da
  melhor. **Campeã**: a que vence o controle SEMANAS_COROA semanas seguidas (entre as que conseguem, a de melhor
  média). Ela NÃO substitui a versão padrão dos Robôs (decisão dele: "manteremos as duas, como duas frentes"), não
  pode ser eliminada e perde a coroa se perder do controle SEMANAS_COROA semanas seguidas.

Cada versão tem um nome de gente, com a família (pedido do Alediov, 16/11/2026): a novata e a semente fundam uma
família ("Ana Ferraz"); a filha leva o sobrenome da mãe e o do pai, como no Brasil ("Clara Ferraz Lima", filha de Ana
Ferraz e Bento Lima; o pai é sempre o de nota melhor dos dois, então o último sobrenome segue a linha que vence); a
mutante fica com os sobrenomes de quem veio. Nome repetido entre as vivas e as da árvore ganha II, III… `pais` (pai e
mãe; a mutante tem um só) e `origem` (de onde veio cada gene: "pai", "mae", "mut" ou "novo") contam o resto. A árvore
guarda os antepassados das versões vivas até ARVORE_NIVEIS gerações.

Roda num job próprio (`.github/workflows/evolucao.yml`, 1 vez por dia, no ramo `papel` com o mesmo grupo de
concorrência das outras formas) e grava `evolucao.json` (formato em FORMATO.md, "Evolução"). Sem `versoes` (a lista
fica vazia): o app mostra numa aba própria (Testes → Evolução), não entre as formas.
"""
from __future__ import annotations

import datetime as dt
import math
import random
import statistics

import hl
import robos as R
from genetica import (NOMES, SOBRENOMES, ativo, _snap, reparar, chave, sortear, _novo_valor, mutar, cruzar,  # noqa: F401
                      romano)
from conta import CAPITAL, DIA, HORA, Curva, Eventos, cdi_ano_da_serie, dia_de, metricas

NOME = "Evolução"
VERSAO = 3              # 2: sem clones; 3: nomes com a família (as duas em 16/11/2026, o 1º dia: recomeçou)

MIN = 60_000
# ---------------------------------------------------------------- laboratório (no passado)
POP = 24
SOBREVIVEM = 12
FILHAS = 8
MUTANTES = 2
NOVATAS = 2
GERACOES_DIA = 10
MUT_FILHA = 0.15
HIST_DIAS = 180
JANELAS = 3            # o treino: as 3 primeiras quartas partes; a prova: a última
MIN_OPS = 5
SEG_MIN = 360          # segundos que ficam para a liga quando o laboratório para
MAX_HIST = 300         # gerações guardadas no estado (no evolucao.json vão as últimas HIST_SAIDA)
HIST_SAIDA = 150
# ---------------------------------------------------------------- liga (ao vivo)
POP_LIGA = 24
SAEM_LIGA = 6
DO_LAB = 3
FILHAS_LIGA = 2
MUTANTES_LIGA = 1
SEMANAS_NOTA = 4
SEMANAS_COROA = 4
MIN_DIAS_SEMANA = 5    # menos que isso na semana: ainda sem nota
NOVATAS_SEMENTE = 6    # a 1ª liga: as melhores do laboratório e algumas sorteadas
SERIE_SAIDA = 120      # pontos da série no evolucao.json (só das que o app desenha)
COM_SERIE = 6          # as melhores da liga que levam a série
MAX_SEMANAS = 52
ARVORE_NIVEIS = 4
GANHOS = 50            # operações fechadas guardadas por conta (o acerto)


def parametros(ctx):
    """Os números de cima; no mercado de mentira (60 dias de preços), tudo menor."""
    P = {k: globals()[k] for k in ("POP", "SOBREVIVEM", "FILHAS", "MUTANTES", "NOVATAS", "GERACOES_DIA", "HIST_DIAS",
                                   "POP_LIGA", "SAEM_LIGA", "DO_LAB", "FILHAS_LIGA", "MUTANTES_LIGA", "SEMANAS_NOTA",
                                   "SEMANAS_COROA", "NOVATAS_SEMENTE", "MIN_OPS")}
    if ctx.exemplo:
        P.update(POP=8, SOBREVIVEM=4, FILHAS=2, MUTANTES=1, NOVATAS=1, GERACOES_DIA=2, HIST_DIAS=20, POP_LIGA=8,
                 SAEM_LIGA=2, DO_LAB=1, FILHAS_LIGA=1, MUTANTES_LIGA=1, SEMANAS_COROA=2, NOVATAS_SEMENTE=2, MIN_OPS=2)
    return P


# ====================================================================== espécies e genes
# tipo: "num" (min…max no passo), "int", "bool" ou "op" (uma das opções). "so": o gene só vale quando os outros têm
# esses valores (senão fica no `neutro`, para duas versões iguais terem a mesma chave). "un": "%" (fração), "×" ou "h".
MERCADO = {"k": "mercado", "nome": "Mercado", "tipo": "op", "opcoes": ["spot", "perp"],
           "rotulos": {"spot": "À vista", "perp": "Perpétuo"}, "neutro": "spot"}
ESPECIES = {
    "robos": [
        {"id": "grade", "nome": "Grade", "icone": "🪜", "prefixo": "g", "controle": "gbtc10",
         "sementes": ["gbtc20r", "gneutra1", "gneutra3", "gsaida1", "gsaida3"],
         "base": {"tipo": "grade", "moeda": "BTC"},
         "frase": "Grades de compra e venda no bitcoin: a largura, os degraus, o mercado, a alavancagem e a saída "
                  "evoluem.",
         "genes": [
             MERCADO,
             {"k": "faixa", "nome": "Largura", "tipo": "num", "min": 0.03, "max": 0.25, "passo": 0.01, "un": "%",
              "neutro": 0.10},
             {"k": "degraus", "nome": "Degraus", "tipo": "int", "min": 6, "max": 40, "passo": 1, "neutro": 20},
             {"k": "alav", "nome": "Alavancagem", "tipo": "num", "min": 1, "max": 3, "passo": 0.5, "un": "×",
              "neutro": 1, "so": {"mercado": "perp"}},
             {"k": "recentrar", "nome": "Recentra", "tipo": "bool", "neutro": False},
             {"k": "saida", "nome": "Saída", "tipo": "bool", "neutro": False},
             {"k": "saidaQueda", "nome": "Sai com queda de", "tipo": "num", "min": 0.05, "max": 0.30, "passo": 0.01,
              "un": "%", "neutro": 0.15, "so": {"saida": True}},
         ]},
        {"id": "bandas", "nome": "Bandas", "icone": "〰️", "prefixo": "b", "controle": "rbandas",
         "sementes": ["rbandastend", "rbandasls"],
         "base": {"tipo": "sinal", "regra": "bandas", "moeda": "BTC"},
         "frase": "Compra quando o preço estica para baixo da média e vende na volta: a média, os desvios, o stop e "
                  "o filtro de tendência evoluem.",
         "genes": [
             MERCADO,
             {"k": "ls", "nome": "Dois lados", "tipo": "bool", "neutro": False, "so": {"mercado": "perp"}},
             {"k": "media", "nome": "Média", "tipo": "int", "min": 12, "max": 168, "passo": 6, "un": "h",
              "neutro": 48},
             {"k": "z", "nome": "Desvios", "tipo": "num", "min": 1.0, "max": 3.0, "passo": 0.1, "neutro": 2.0},
             {"k": "stop", "nome": "Stop", "tipo": "num", "min": 0.02, "max": 0.15, "passo": 0.005, "un": "%",
              "neutro": 0.06},
             {"k": "filtro", "nome": "Só a favor da média de", "tipo": "op", "opcoes": [0, 72, 120, 168], "un": "h",
              "rotulos": {"0": "Não"}, "neutro": 0},
         ]},
        {"id": "tendencia", "nome": "Tendência", "icone": "📈", "prefixo": "t", "controle": "tcruz",
         "sementes": ["tcruzls"],
         "base": {"tipo": "sinal", "regra": "cruz", "moeda": "BTC"},
         "frase": "Fica comprado enquanto a média rápida está acima da lenta: as duas médias, os dois lados e o stop "
                  "evoluem.",
         "genes": [
             MERCADO,
             {"k": "ls", "nome": "Dois lados", "tipo": "bool", "neutro": False, "so": {"mercado": "perp"}},
             {"k": "rapida", "nome": "Média rápida", "tipo": "int", "min": 6, "max": 72, "passo": 2, "un": "h",
              "neutro": 24},
             {"k": "lenta", "nome": "Média lenta", "tipo": "int", "min": 48, "max": 200, "passo": 4, "un": "h",
              "neutro": 120},
             {"k": "stop", "nome": "Stop", "tipo": "op", "opcoes": [0, 0.03, 0.05, 0.08, 0.12], "un": "%",
              "rotulos": {"0": "Sem"}, "neutro": 0},
         ]},
    ],
}
FORMA_NOME = {"robos": "Robôs"}

FRASE = ("Cada estratégia vira uma população de versões que evoluem: as piores saem, as melhores se cruzam (cada gene vem "
         "do pai ou da mãe) e às vezes nasce uma mutação. No laboratório isso acontece todo dia no passado; na liga, "
         "toda semana ao vivo.")
COMO_FUNCIONA = [
    "Laboratório: todo dia, até 10 gerações nos últimos 180 dias (velas de 1 h, aproximado). A nota vem dos primeiros "
    "135 dias, em 3 janelas (retorno ao mês − ½ pior queda), premiando a constância; os últimos 45 dias são a prova.",
    "Em cada geração ficam as 12 melhores de 24; nascem 8 filhas (genes do pai ou da mãe), 2 mutantes e 2 novatas.",
    "Liga: 24 versões ao vivo e o controle (a versão padrão de hoje). Toda segunda saem as 6 piores (média de 4 "
    "semanas) e entram até 3 aprovadas do laboratório (melhores que o controle no treino e na prova), filhas e uma "
    "mutante.",
    "Campeã: a que vence o controle 4 semanas seguidas. Ela roda ao lado da versão padrão, não no lugar dela.",
]
AVISOS = [
    "Tudo no papel: contas fictícias de US$ 1.000, nenhuma ordem.",
    "Quanto mais gerações no mesmo passado, mais a população se ajusta a ele: por isso a prova fica de fora e só a "
    "liga, ao vivo, decide a campeã.",
]


# ====================================================================== genes
def genes_da_versao(esp, cfg):
    """Os genes de uma versão dos Robôs (a padrão e as sementes)."""
    genes = {}
    for g in esp["genes"]:
        k = g["k"]
        if k == "recentrar":
            genes[k] = cfg.get("recentrar") is True
        elif k in ("ls", "saida"):
            genes[k] = bool(cfg.get(k))
        elif k in ("filtro", "stop") and g["tipo"] == "op":
            genes[k] = cfg.get(k) or 0
        else:
            genes[k] = cfg.get(k, g["neutro"])
    return reparar(esp, genes)


def cfg_de(esp, genes, id_, nome):
    """A versão dos Robôs (robos.Robo) com esses genes."""
    cfg = dict(esp["base"])
    cfg.update(id=id_, nome=nome, mercado=genes["mercado"], alav=1, risco="médio", grupo="Evolução")
    if esp["id"] == "grade":
        cfg.update(faixa=genes["faixa"], degraus=genes["degraus"], recentrar=bool(genes["recentrar"]),
                   alav=genes["alav"], saida=bool(genes["saida"]), saidaQueda=genes["saidaQueda"])
    elif esp["id"] == "bandas":
        cfg.update(media=genes["media"], z=genes["z"], stop=genes["stop"], ls=bool(genes["ls"]),
                   filtro=genes["filtro"] or None)
    else:
        cfg.update(rapida=genes["rapida"], lenta=genes["lenta"], ls=bool(genes["ls"]), stop=genes["stop"] or None)
    return cfg


def descrever(esp, genes):
    """A versão em poucas palavras (o app mostra embaixo do nome)."""
    perp = genes["mercado"] == "perp"
    if esp["id"] == "grade":
        t = f"±{genes['faixa'] * 100:.0f}%, {genes['degraus']} degraus"
        t += f", perpétuo {num(genes['alav'])}×" if perp else ", à vista"
        if genes["recentrar"]:
            t += ", recentra"
        if genes["saida"]:
            t += f", sai com −{genes['saidaQueda'] * 100:.0f}%"
        return t
    if esp["id"] == "bandas":
        t = f"{num(genes['z'])} desvios da média de {genes['media']} h, stop {num(genes['stop'] * 100)}%"
        if genes["filtro"]:
            t += f", só acima da média de {genes['filtro']} h"
        return t + (", dois lados" if genes["ls"] else (", perpétuo" if perp else ""))
    t = f"Médias de {genes['rapida']} h e {genes['lenta']} h"
    if genes["stop"]:
        t += f", stop {num(genes['stop'] * 100)}%"
    return t + (", dois lados" if genes["ls"] else (", perpétuo" if perp else ""))


def num(x):
    x = float(x)
    return f"{x:.0f}" if abs(x - round(x)) < 1e-9 else f"{x:.1f}".replace(".", ",")


def _queda(vals):
    pico, q = 0.0, 0.0
    for v in vals:
        pico = max(pico, v)
        if pico > 0:
            q = max(q, 1 - v / pico)
    return q


def nota_janela(vals, dias):
    """Retorno ao mês − ½ pior queda de um trecho de pontos diários (o 1º é o começo)."""
    if len(vals) < 2 or vals[0] <= 0:
        return None
    r = vals[-1] / vals[0] - 1
    mes = max(0.0, 1 + r) ** (30 / max(1, dias)) - 1
    return mes - 0.5 * _queda(vals)


def nota_de(curva, s, P):
    """A nota (treino), a prova e as janelas de uma conta do laboratório."""
    vals = [CAPITAL] + [v for _, v in sorted(curva.serie.items())]
    q = max(1, (len(vals) - 1) // (JANELAS + 1))
    out = {"ret": round(curva.ultimo / CAPITAL - 1, 5), "queda": round(curva.queda, 4), "ops": curva.ops,
           "liq": curva.n_liq}
    if s.get("morta"):
        out.update(nota=-1.0, val=-1.0, jan=[-1.0] * JANELAS, morta=True)
        return out
    jan = [nota_janela(vals[i * q:(i + 1) * q + 1], q) for i in range(JANELAS)]
    val = nota_janela(vals[JANELAS * q:], len(vals) - 1 - JANELAS * q)
    out["jan"] = [round(x, 5) if x is not None else None for x in jan]
    out["val"] = round(val, 5) if val is not None else None
    if curva.ops < P["MIN_OPS"] or any(x is None for x in jan):
        out["nota"] = None
        out["semNota"] = f"menos de {P['MIN_OPS']} operações" if curva.ops < P["MIN_OPS"] else "pouco tempo"
        return out
    out["nota"] = round(statistics.mean(jan) - 0.5 * statistics.pstdev(jan), 5)
    return out


def _n(x):
    return x if x is not None else -9.0


def assinatura(i):
    """O resultado de uma versão no laboratório. Duas com a mesma assinatura são clones: genes diferentes que não
    mudam nada (a queda da saída que nunca dispara, o stop que nunca é tocado); só a mais velha fica, para a população
    não se encher de cópias (descoberto na 1ª rodada real, 16/11/2026)."""
    return (i.get("nota"), i.get("val"), i.get("ops"), i.get("ret"), i.get("queda"))


def sem_clones(ordem):
    """`ordem` sem os clones (fica a primeira de cada assinatura)."""
    vistos, out = set(), []
    for i in ordem:
        a = assinatura(i)
        if a not in vistos:
            vistos.add(a)
            out.append(i)
    return out


# ====================================================================== laboratório
def dados_lab(ctx, pares, P, erros, log):
    """As velas de 1 h (com os dias de aquecer antes) do à vista e do perpétuo e o financiamento do perpétuo."""
    agora = ctx.agora
    ini = agora - P["HIST_DIAS"] * DIA
    out = {}
    for merc, coin in (("spot", pares.get("BTC", R.PARES_PADRAO["BTC"])), ("perp", "BTC")):
        try:
            velas = R.velas_da_api(ctx.cli.velas(coin, "1h", ini - R.AQUECER_SINAL_DIAS * DIA, agora), "1h", agora)
            fund = R.Funding.da_api(ctx.cli.financiamento("BTC", ini - HORA, agora)) if merc == "perp" else None
        except hl.Erro as e:
            erros.append(f"evolucao: velas de 1 h {coin} ({e})")
            continue
        antes = [v for v in velas if v[0] < ini]
        depois = [v for v in velas if v[0] >= ini]
        if len(depois) < 24 * 7:
            erros.append(f"evolucao: poucas velas de 1 h em {coin} ({len(depois)})")
            continue
        out[merc] = (antes, depois, fund)
        log(f"  evolucao: {len(depois)} velas de 1 h de {coin} ({dia_de(depois[0][0])} a {dia_de(depois[-1][1])})")
    return out


def avaliar(esp, genes, dados, P):
    d = dados.get(genes["mercado"])
    if not d:
        return None
    antes, depois, fund = d
    robo = R.Robo(cfg_de(esp, genes, "lab", "lab"), R.LEV_MAX_PADRAO["BTC"])
    s = robo.novo(depois[0][0])
    robo.aquecer(s, antes)
    curva = Curva(inicio=depois[0][0])
    R.processar(robo, s, curva, depois, fund, None)
    return nota_de(curva, s, P)


class Especie:
    """O estado de uma espécie (laboratório, liga, árvore) e as contas de nascer, cruzar e escolher."""

    def __init__(self, forma, esp, e, rng, P, ev, log):
        self.forma, self.esp, self.e, self.rng, self.P, self.ev, self.log = forma, esp, e, rng, P, ev, log
        e.setdefault("contador", 0)
        e.setdefault("arvore", {})
        self.cfg_padrao = {c["id"]: c for c in R.VERSOES}

    # -------------------------------------------------------------- nascer
    def nascer(self, genes, tipo, pais=(), origem=None, g=None):
        self.e["contador"] += 1
        n = self.e["contador"]
        nome, sob = self.batizar(tipo, pais)
        ind = {"id": f"{self.esp['prefixo']}{n}", "nome": nome, "sob": sob, "genes": genes, "tipo": tipo,
               "pais": list(pais), "origem": origem or {k: "novo" for k in genes}, "g": g}
        self.e["arvore"][ind["id"]] = {"n": nome, "s": sob, "t": tipo, "p": list(pais), "g": g}
        self._nomes.add(nome)
        return ind

    def batizar(self, tipo, pais):
        """O nome e os sobrenomes de quem nasce: a filha leva o último sobrenome da mãe e o do pai; a mutante, os de
        quem veio; a novata e a semente fundam uma família (um sobrenome que nenhuma viva usa, enquanto houver).
        O prenome é sorteado; nome igual ao de uma viva ou de alguém da árvore ganha II, III…"""
        arv, rng = self.e["arvore"], self.rng
        if not hasattr(self, "_nomes"):
            self._nomes = {a["n"] for a in arv.values()}
        sob_de = lambda i: (arv.get(i) or {}).get("s") or []  # noqa: E731
        sp = [sob_de(i) for i in pais]
        if tipo == "filha" and len(sp) == 2 and sp[0] and sp[1]:
            sob = [sp[1][-1], sp[0][-1]] if sp[1][-1] != sp[0][-1] else [sp[0][-1]]
        elif tipo == "mutante" and sp and sp[0]:
            sob = list(sp[0])
        else:
            usados = {x for a in arv.values() for x in a.get("s") or []}
            livres = [x for x in SOBRENOMES if x not in usados] or SOBRENOMES
            sob = [rng.choice(livres)]
        familia = " ".join(sob)
        for _ in range(12):
            nome = f"{rng.choice(NOMES)} {familia}"
            if nome not in self._nomes:
                return nome, sob
        k = 2
        while f"{nome} {romano(k)}" in self._nomes:
            k += 1
        return f"{nome} {romano(k)}", sob

    def controle_genes(self):
        return genes_da_versao(self.esp, self.cfg_padrao[self.esp["controle"]])

    def avaliar(self, ind, dados, cache):
        k = chave(ind["genes"])
        if k not in cache:
            cache[k] = avaliar(self.esp, ind["genes"], dados, self.P)
        r = cache[k]
        for x in ("nota", "val", "jan", "ret", "queda", "ops", "liq", "morta", "semNota"):
            ind.pop(x, None)
        if r:
            ind.update(r)
        return ind

    # -------------------------------------------------------------- laboratório
    def semear_lab(self, lab):
        P, vistos, pop = self.P, set(), []
        for vid in [self.esp["controle"]] + self.esp["sementes"]:
            cfg = self.cfg_padrao.get(vid)
            if not cfg:
                continue
            genes = genes_da_versao(self.esp, cfg)
            if chave(genes) in vistos:
                continue
            vistos.add(chave(genes))
            ind = self.nascer(genes, "semente", g=0)
            ind["de"] = vid
            pop.append(ind)
        while len(pop) < P["POP"]:
            genes = sortear(self.rng, self.esp)
            if chave(genes) in vistos:
                continue
            vistos.add(chave(genes))
            pop.append(self.nascer(genes, "novata", g=0))
        lab["pop"] = pop[:P["POP"]]

    def geracao(self, lab, dados, cache):
        """Uma geração: ficam as melhores, nascem filhas, mutantes e novatas (já avaliadas)."""
        P, rng = self.P, self.rng
        # a mais velha primeiro no empate: entre clones (o mesmo resultado), fica a que já estava
        ordem = sorted(lab["pop"], key=lambda i: (-_n(i.get("nota")), -i.get("idade", 0)))
        ficam, saem, vistos_r = [], [], set()
        for i in ordem:
            a = assinatura(i)
            if len(ficam) < P["SOBREVIVEM"] and a not in vistos_r:
                ficam.append(i)
                vistos_r.add(a)
            else:
                if a in vistos_r:
                    i["clone"] = True
                saem.append(i)
        g = lab["g"] + 1
        vistos = {chave(i["genes"]) for i in ficam}
        novos = []

        def entrar(ind):
            vistos.add(chave(ind["genes"]))
            novos.append(ind)

        def torneio(excluir=None):
            cands = [i for i in ficam if i is not excluir] or ficam
            return max(rng.sample(cands, min(3, len(cands))), key=lambda i: _n(i.get("nota")))

        tentativas = 0
        while len(novos) < P["FILHAS"] and tentativas < 60:
            tentativas += 1
            pai = torneio()
            mae = torneio(pai)
            if _n(mae.get("nota")) > _n(pai.get("nota")):  # o pai é o de nota melhor (o sobrenome dele fica por último)
                pai, mae = mae, pai
            genes, origem = cruzar(rng, self.esp, pai, mae)
            if chave(genes) in vistos:
                continue
            entrar(self.nascer(genes, "filha", (pai["id"], mae["id"]), origem, g))
        while len(novos) < P["FILHAS"] + P["MUTANTES"] and tentativas < 120:
            tentativas += 1
            base = torneio()
            genes, origem, _ = mutar(rng, self.esp, base["genes"], {k: "pai" for k in base["genes"]},
                                     1 if rng.random() < 0.6 else 2)
            if chave(genes) in vistos:
                continue
            entrar(self.nascer(genes, "mutante", (base["id"],), origem, g))
        while len(ficam) + len(novos) < P["POP"] and tentativas < 200:
            tentativas += 1
            genes = sortear(rng, self.esp)
            if chave(genes) in vistos:
                continue
            entrar(self.nascer(genes, "novata", (), None, g))
        for ind in novos:
            self.avaliar(ind, dados, cache)
        for ind in ficam:
            ind["idade"] = ind.get("idade", 0) + 1
        lab["pop"] = ficam + novos
        lab["g"] = g
        lab["saiu"] = [{"id": i["id"], "nome": i["nome"], "nota": i.get("nota"), **({"clone": True} if i.get("clone") else {})}
                       for i in saem]
        lab["nasceu"] = [i["id"] for i in novos]

    def resumo_geracao(self, lab):
        ordem = sorted(lab["pop"], key=lambda i: -_n(i.get("nota")))
        notas = [i["nota"] for i in ordem if i.get("nota") is not None]
        c = lab.get("controle") or {}
        top = ordem[0] if ordem else {}
        lab.setdefault("hist", []).append({
            "g": lab["g"], "dia": lab["dia"], "melhor": top.get("nota"), "id": top.get("id"),
            "mediana": round(statistics.median(notas), 5) if notas else None, "val": top.get("val"),
            "controle": c.get("nota"), "valControle": c.get("val")})
        del lab["hist"][:-MAX_HIST]

    def aprovadas(self, lab):
        """As melhores do laboratório que venceram o controle no treino E na prova (candidatas à liga)."""
        c = lab.get("controle") or {}
        cn, cv = _n(c.get("nota")), _n(c.get("val"))
        ordem = sem_clones(sorted(lab["pop"], key=lambda i: -_n(i.get("nota"))))[:max(6, self.P["DO_LAB"] * 2)]
        boas = [i for i in ordem if i.get("nota") is not None and i.get("val") is not None
                and i["nota"] > cn and i["val"] > cv]
        return sorted(boas, key=lambda i: -i["val"])

    def rodar_lab(self, ctx, dados, cache, cota):
        """O laboratório de hoje: reavalia quem tem nota de outro dia e roda até `cota` gerações. Devolve quantas."""
        lab = self.e.setdefault("lab", {"g": 0, "pop": [], "hist": [], "dia": None, "hoje": 0})
        hoje = dia_de(ctx.agora)
        if lab.get("dia") != hoje:
            lab["dia"], lab["hoje"] = hoje, 0
        if not lab["pop"]:
            self.semear_lab(lab)
        for ind in lab["pop"]:
            if ind.get("dia") != hoje:
                self.avaliar(ind, dados, cache)
                ind["dia"] = hoje
        c = lab.get("controle") or {}
        if c.get("dia") != hoje:
            r = avaliar(self.esp, self.controle_genes(), dados, self.P) or {}
            lab["controle"] = {**r, "dia": hoje}
        feitas = 0
        while feitas < cota and lab["hoje"] < self.P["GERACOES_DIA"] and ctx.restante() > SEG_MIN:
            self.geracao(lab, dados, cache)
            for ind in lab["pop"]:
                ind["dia"] = hoje
            lab["hoje"] += 1
            feitas += 1
            self.resumo_geracao(lab)
        return feitas

    # -------------------------------------------------------------- liga
    def robo(self, ind):
        return R.Robo(cfg_de(self.esp, ind["genes"], ind["id"], ind["nome"]), R.LEV_MAX_PADRAO["BTC"])

    def comecar_vivo(self, ind, agora, aquecer):
        """Começa a conta ao vivo de `ind` agora (com as velas de 1 h dos últimos dias para as que precisam)."""
        robo = self.robo(ind)
        s = robo.novo(agora // MIN * MIN)
        if robo.usa_buffer:
            velas = aquecer.get(ind["genes"]["mercado"]) or []
            robo.aquecer(s, [v for v in velas if v[1] < agora])
        curva = Curva(inicio=agora)
        curva.marcar(agora, CAPITAL)
        ind.update(desde=agora, s=s, c=curva.para_json(), notas={}, marco={"em": agora, "eq": CAPITAL})
        for x in ("dia", "idade"):
            ind.pop(x, None)
        return ind

    def de_lab(self, ind):
        """A cópia de uma versão do laboratório para a liga (o mesmo id: a mesma versão, a outra frente)."""
        out = {k: ind[k] for k in ("id", "nome", "sob", "genes", "tipo", "pais", "origem", "g") if k in ind}
        out["fonte"] = "laboratório"
        out["lab"] = {"nota": ind.get("nota"), "val": ind.get("val")}
        return out

    def semear_liga(self, ctx, lab, aquecer):
        P = self.P
        ordem = sem_clones(sorted([i for i in lab["pop"] if i.get("nota") is not None], key=lambda i: -i["nota"]))
        pop, vistos = [], set()
        for ind in ordem[:P["POP_LIGA"] - P["NOVATAS_SEMENTE"]]:
            pop.append(self.de_lab(ind))
            vistos.add(chave(ind["genes"]))
        while len(pop) < P["POP_LIGA"]:
            genes = sortear(self.rng, self.esp)
            if chave(genes) in vistos:
                continue
            vistos.add(chave(genes))
            ind = self.nascer(genes, "novata", (), None, None)
            ind["fonte"] = "sorteada"
            pop.append(ind)
        liga = {"inicio": ctx.agora, "semana": R.semana_de(ctx.agora), "pop": [], "semanas": [], "coroadas": [],
                "campea": None}
        for ind in pop:
            liga["pop"].append(self.comecar_vivo(ind, ctx.agora, aquecer))
        ctrl = {"id": "controle", "nome": "Controle", "genes": self.controle_genes(), "tipo": "controle",
                "pais": [], "origem": {}, "de": self.esp["controle"]}
        liga["controle"] = self.comecar_vivo(ctrl, ctx.agora, aquecer)
        self.e["liga"] = liga
        self.ev.add(ctx.agora, "liga", f"{self.esp['nome']}: a liga começou com {len(pop)} versões e o controle "
                                       f"({self.cfg_padrao[self.esp['controle']]['nome']}).", self.esp["id"])
        return liga

    def nota_semana(self, ind, agora):
        """A nota da semana que fechou (retorno − ½ pior queda pelos pontos diários) ou None (pouco tempo)."""
        m = ind.get("marco") or {}
        if agora - int(m.get("em") or agora) < MIN_DIAS_SEMANA * DIA or not m.get("eq"):
            return None
        c = ind["c"]
        ultimo = 0.0 if ind["s"].get("morta") else float(c.get("ultimo") or 0)
        d0 = dia_de(int(m["em"]))
        vals = [float(m["eq"])] + [float(v) for d, v in sorted((c.get("serie") or {}).items()) if d > d0] + [ultimo]
        r = ultimo / float(m["eq"]) - 1
        q = _queda(vals)
        return [round(r - 0.5 * q, 5), round(r, 5), round(q, 4)]

    def media_liga(self, ind, n=None):
        ns = [ind["notas"][w][0] for w in sorted(ind.get("notas") or {}, key=int)]
        ns = ns[-(n or self.P["SEMANAS_NOTA"]):]
        return round(statistics.mean(ns), 5) if ns else None

    def venceu_seguidas(self, ind, ctrl, semanas):
        """Venceu (ou perdeu, se negativo) do controle em todas as `semanas` (lista de semanas)?"""
        a, b = ind.get("notas") or {}, ctrl.get("notas") or {}
        if not semanas or any(str(w) not in a or str(w) not in b for w in semanas):
            return None
        if all(a[str(w)][0] > b[str(w)][0] for w in semanas):
            return 1
        if all(a[str(w)][0] < b[str(w)][0] for w in semanas):
            return -1
        return 0

    def fechar_semana(self, ctx, liga, lab, aquecer):
        """A virada da semana: notas, campeã, quem sai e quem entra."""
        P, rng, agora, nome = self.P, self.rng, ctx.agora, self.esp["nome"]
        w = liga["semana"]
        todos = liga["pop"] + [liga["controle"]]
        for ind in todos:
            nt = self.nota_semana(ind, agora)
            if nt is not None:
                ind["notas"][str(w)] = nt
            c = ind["c"]
            ind["marco"] = {"em": agora, "eq": 0.0 if ind["s"].get("morta") else float(c.get("ultimo") or 0)}
        ctrl = liga["controle"]
        ultimas = sorted({int(x) for x in ctrl["notas"]})[-P["SEMANAS_COROA"]:]
        cheias = len(ultimas) == P["SEMANAS_COROA"] and ultimas[-1] == w
        # ---- a campeã
        camp = liga.get("campea")
        if camp and cheias:
            atual = next((i for i in liga["pop"] if i["id"] == camp["id"]), None)
            if atual is None or self.venceu_seguidas(atual, ctrl, ultimas) == -1:
                camp["ate"] = agora
                liga["coroadas"].append(camp)
                del liga["coroadas"][:-20]
                liga["campea"] = camp = None
                self.ev.add(agora, "coroa", f"{nome}: {atual['nome'] if atual else 'a campeã'} perdeu a coroa "
                                            f"(perdeu do controle {P['SEMANAS_COROA']} semanas seguidas).",
                            self.esp["id"])
        if cheias:
            boas = [i for i in liga["pop"] if self.venceu_seguidas(i, ctrl, ultimas) == 1]
            if boas:
                k = P["SEMANAS_COROA"]
                melhor = max(boas, key=lambda i: self.media_liga(i, k))
                atual = next((i for i in liga["pop"] if camp and i["id"] == camp["id"]), None)
                troca = camp is None or (melhor["id"] != camp["id"] and
                                         (atual is None or self.media_liga(melhor, k) > _n(self.media_liga(atual, k))))
                if troca:
                    if camp:
                        camp["ate"] = agora
                        liga["coroadas"].append(camp)
                        del liga["coroadas"][:-20]
                    liga["campea"] = {"id": melhor["id"], "nome": melhor["nome"], "desde": agora,
                                      "genes": melhor["genes"], "semana": w}
                    self.ev.add(agora, "coroa", f"{nome}: {melhor['nome']} é a campeã: venceu o controle "
                                                f"{P['SEMANAS_COROA']} semanas seguidas ({descrever(self.esp, melhor['genes'])}).",
                                self.esp["id"])
        # ---- quem sai
        com_nota = [i for i in liga["pop"] if i["notas"]]
        protegida = (liga.get("campea") or {}).get("id")
        saem = []
        if len(com_nota) >= 2 * P["SAEM_LIGA"]:
            ordem = sorted([i for i in com_nota if i["id"] != protegida], key=lambda i: _n(self.media_liga(i)))
            saem = ordem[:P["SAEM_LIGA"]]
        ids_saem = {i["id"] for i in saem}
        liga["pop"] = [i for i in liga["pop"] if i["id"] not in ids_saem]
        # ---- quem entra
        vistos = {chave(i["genes"]) for i in liga["pop"]}
        entram = []
        vagas = P["POP_LIGA"] - len(liga["pop"])
        for cand in self.aprovadas(lab)[:P["DO_LAB"]] if lab else []:
            if len(entram) >= vagas:
                break
            if chave(cand["genes"]) in vistos or any(i["id"] == cand["id"] for i in liga["pop"]):
                continue
            ind = self.de_lab(cand)
            entram.append(ind)
            vistos.add(chave(ind["genes"]))
        boas = sorted([i for i in liga["pop"] if i["notas"]], key=lambda i: -_n(self.media_liga(i)))[:8]
        tentativas = 0
        while len(entram) < vagas and tentativas < 80:
            tentativas += 1
            mutante = len(entram) >= vagas - P["MUTANTES_LIGA"] and boas
            if mutante:
                base = boas[0]
                genes, origem, _ = mutar(rng, self.esp, base["genes"], {k: "pai" for k in base["genes"]})
                ind = self.nascer(genes, "mutante", (base["id"],), origem, None)
            elif len(boas) >= 2:
                pai = max(rng.sample(boas, min(3, len(boas))), key=lambda i: _n(self.media_liga(i)))
                outras = [i for i in boas if i is not pai]
                mae = max(rng.sample(outras, min(3, len(outras))), key=lambda i: _n(self.media_liga(i)))
                if _n(self.media_liga(mae)) > _n(self.media_liga(pai)):
                    pai, mae = mae, pai
                genes, origem = cruzar(rng, self.esp, pai, mae)
                ind = self.nascer(genes, "filha", (pai["id"], mae["id"]), origem, None)
            else:
                genes = sortear(rng, self.esp)
                ind = self.nascer(genes, "novata", (), None, None)
            if chave(ind["genes"]) in vistos:
                continue
            ind["fonte"] = "liga"
            entram.append(ind)
            vistos.add(chave(ind["genes"]))
        for ind in entram:
            ind["semana"] = w + 1
            liga["pop"].append(self.comecar_vivo(ind, agora, aquecer))
        # ---- o resumo da semana
        notas = [i["notas"][str(w)][0] for i in liga["pop"] + saem if str(w) in i.get("notas", {})]
        cn = (ctrl["notas"].get(str(w)) or [None])[0]
        melhor = max((i for i in liga["pop"] + saem if str(w) in i.get("notas", {})),
                     key=lambda i: i["notas"][str(w)][0], default=None)
        if notas or saem or entram:
            liga["semanas"].append({
                "semana": w, "de": segunda_de(w), "melhor": melhor["id"] if melhor else None,
                "nota": melhor["notas"][str(w)][0] if melhor else None, "controle": cn,
                "mediana": round(statistics.median(notas), 5) if notas else None,
                "venceram": sum(1 for x in notas if cn is not None and x > cn), "notas": len(notas),
                "saiu": [{"id": i["id"], "nome": i["nome"], "media": self.media_liga(i)} for i in saem],
                "entrou": [{"id": i["id"], "nome": i["nome"], "fonte": i.get("fonte"), "tipo": i.get("tipo")} for i in entram]})
        del liga["semanas"][:-MAX_SEMANAS]
        liga["semana"] = R.semana_de(agora)
        if saem or entram:
            self.ev.add(agora, "semana", f"{nome}, semana de {segunda_de(w)[8:10]}/{segunda_de(w)[5:7]}: "
                                         + (f"saíram {', '.join(i['nome'] for i in saem)}; " if saem else "")
                                         + (f"entraram {', '.join(i['nome'] for i in entram)}." if entram else ""),
                        self.esp["id"])
        self.log(f"  evolucao: {self.esp['id']} fechou a semana {w} ({len(saem)} saíram, {len(entram)} entraram)")

    # -------------------------------------------------------------- árvore
    def podar_arvore(self):
        arv = self.e["arvore"]
        vivos = [i["id"] for i in (self.e.get("lab") or {}).get("pop", [])]
        liga = self.e.get("liga") or {}
        vivos += [i["id"] for i in liga.get("pop", [])]
        vivos += [c["id"] for c in ([liga.get("campea")] if liga.get("campea") else []) + liga.get("coroadas", [])]
        manter, nivel = set(), set(vivos)
        for _ in range(ARVORE_NIVEIS + 1):
            manter |= nivel
            nivel = {p for i in nivel for p in (arv.get(i) or {}).get("p", [])} - manter
        for k in [k for k in arv if k not in manter]:
            del arv[k]


def segunda_de(w):
    """A segunda-feira (Brasília) da semana `w` de robos.semana_de, em AAAA-MM-DD."""
    return (dt.date(1970, 1, 1) + dt.timedelta(days=7 * w - 3)).isoformat()


# ====================================================================== a rodada
def _contas(especies):
    for sp in especies:
        liga = sp.e.get("liga")
        if liga:
            for ind in liga["pop"] + [liga["controle"]]:
                yield ind


def restaurar_buffers(especies, est):
    """As velas de 1 h que as versões de sinal e de saída guardam são as mesmas para todas do mesmo mercado: o estado
    guarda uma cópia por mercado (est["hb"]) e cada conta ganha a sua aqui, só com as horas antes de onde ela parou
    (nenhuma vê o futuro)."""
    hb = est.get("hb") or {}
    for ind in _contas(especies):
        s = ind["s"]
        if "hb" in s and s["hb"] is None:
            ate = int(s["ate"])
            s["hb"] = {k: list(v) for k, v in (hb.get(ind["genes"]["mercado"]) or {}).items() if int(k) < ate}


def guardar_buffers(especies, est):
    """O contrário de restaurar_buffers: fica a cópia mais nova de cada mercado e as contas guardam só `None`."""
    hb = {}
    for ind in _contas(especies):
        s = ind["s"]
        b = s.get("hb")
        if b:
            m = ind["genes"]["mercado"]
            if m not in hb or max(map(int, b)) > max(map(int, hb[m])) or (
                    max(map(int, b)) == max(map(int, hb[m])) and len(b) > len(hb[m])):
                hb[m] = b
        if "hb" in s:
            s["hb"] = None
    if hb:
        est["hb"] = hb
    elif "hb" in est and not any("hb" in ind["s"] for ind in _contas(especies)):
        del est["hb"]


def avancar_vivo(ctx, especies, pares, erros, log):
    """Leva todas as contas ao vivo (as da liga e os controles) de onde pararam até agora, nas velas de 1 min."""
    agora = ctx.agora
    grupos = {}
    for sp in especies:
        liga = sp.e.get("liga")
        if not liga:
            continue
        for ind in liga["pop"] + [liga["controle"]]:
            grupos.setdefault(ind["genes"]["mercado"], []).append((sp, ind))
    for merc, lista in grupos.items():
        vivos = [ind for _, ind in lista if not ind["s"].get("morta")]
        if not vivos:
            continue
        ini = min(int(ind["s"]["ate"]) for ind in vivos)
        if agora - ini < MIN:
            continue
        coin = pares.get("BTC", R.PARES_PADRAO["BTC"]) if merc == "spot" else "BTC"
        intervalo = hl.intervalo_para(ini, agora, agora)
        try:
            velas = R.velas_da_api(ctx.cli.velas(coin, intervalo, ini, agora), intervalo, agora)
            fund = R.Funding.da_api(ctx.cli.financiamento("BTC", ini - HORA, agora)) if merc == "perp" else None
        except hl.Erro as e:
            erros.append(f"evolucao: velas {coin} {intervalo} ({e})")
            continue
        if intervalo != "1m":
            log(f"  evolucao: {coin} alcançou o atraso com velas de {intervalo}")
        for sp, ind in lista:
            robo = sp.robo(ind)
            curva = Curva.de_json(ind["c"])
            try:
                R.processar(robo, ind["s"], curva, velas, fund, None)
            except Exception as e:  # noqa: BLE001  (uma versão com defeito não derruba as outras)
                erros.append(f"evolucao: {ind['id']} ao vivo ({e})")
                continue
            curva.ganhos = curva.ganhos[-GANHOS:]
            curva.extra = {}
            ind["c"] = curva.para_json()
        log(f"  evolucao: {len(lista)} contas ao vivo no {'à vista' if merc == 'spot' else 'perpétuo'} "
            f"({len(velas)} velas de {intervalo})")


def aquecer_de(ctx, dados, pares, erros):
    """As velas de 1 h dos últimos dias (para as versões novas da liga que precisam delas)."""
    out = {}
    corte = ctx.agora - (R.AQUECER_SINAL_DIAS + 1) * DIA
    for merc, coin in (("spot", pares.get("BTC", R.PARES_PADRAO["BTC"])), ("perp", "BTC")):
        if merc in dados:
            antes, depois, _ = dados[merc]
            out[merc] = [v for v in antes + depois if v[0] >= corte]
            continue
        try:
            out[merc] = R.velas_da_api(ctx.cli.velas(coin, "1h", corte, ctx.agora), "1h", ctx.agora)
        except hl.Erro as e:
            erros.append(f"evolucao: velas de 1 h para aquecer {coin} ({e})")
    return out


def rodar(ctx):
    est, agora, log = ctx.est, ctx.agora, ctx.log
    P = parametros(ctx)
    erros = []
    ev = Eventos(est.get("eventos"))
    pares = R.resolver_pares(ctx, est, erros)
    estados = est.setdefault("esp", {})
    especies = []
    for forma, lista in ESPECIES.items():
        for esp in lista:
            e = estados.setdefault(f"{forma}.{esp['id']}", {})
            rng = random.Random(f"{forma}.{esp['id']}.{agora}")
            especies.append(Especie(forma, esp, e, rng, P, ev, log))

    # ---------------------------------------------------------------- laboratório
    hoje = dia_de(agora)
    precisa = any((sp.e.get("lab") or {}).get("dia") != hoje or (sp.e.get("lab") or {}).get("hoje", 0) < P["GERACOES_DIA"]
                  for sp in especies)
    dados = dados_lab(ctx, pares, P, erros, log) if precisa else {}
    if dados:
        caches = {sp.esp["id"]: {} for sp in especies}
        rodando = list(especies)
        # uma geração de cada espécie por vez, para o prazo dividir entre elas
        while rodando and ctx.restante() > SEG_MIN:
            for sp in list(rodando):
                try:
                    feitas = sp.rodar_lab(ctx, dados, caches[sp.esp["id"]], 1)
                except Exception as e:  # noqa: BLE001
                    erros.append(f"evolucao: laboratório de {sp.esp['id']} ({e})")
                    feitas = 0
                if not feitas:
                    rodando.remove(sp)
        for sp in especies:
            lab = sp.e.get("lab") or {}
            log(f"  evolucao: {sp.esp['id']} geração {lab.get('g')} ({lab.get('hoje')} hoje)")
    elif precisa:
        log("  evolucao: sem velas de 1 h; o laboratório fica para a próxima rodada")

    # ---------------------------------------------------------------- liga
    restaurar_buffers(especies, est)
    avancar_vivo(ctx, especies, pares, erros, log)
    aquecer = None
    for sp in especies:
        lab = sp.e.get("lab")
        liga = sp.e.get("liga")
        try:
            if liga and R.semana_de(agora) != liga["semana"]:
                aquecer = aquecer if aquecer is not None else aquecer_de(ctx, dados, pares, erros)
                sp.fechar_semana(ctx, liga, lab, aquecer)
            elif not liga and lab and any(i.get("nota") is not None for i in lab.get("pop", [])):
                aquecer = aquecer if aquecer is not None else aquecer_de(ctx, dados, pares, erros)
                sp.semear_liga(ctx, lab, aquecer)
                log(f"  evolucao: {sp.esp['id']} começou a liga")
        except Exception as e:  # noqa: BLE001
            erros.append(f"evolucao: liga de {sp.esp['id']} ({e})")
        sp.podar_arvore()
    guardar_buffers(especies, est)

    if not dados and precisa and not any(sp.e.get("liga") for sp in especies):
        raise hl.Erro("sem dados da Hyperliquid: " + "; ".join(erros[:3]))

    # ---------------------------------------------------------------- saída
    cdi = (ctx.ref or {}).get("cdi") or {}
    cdi_ano = cdi_ano_da_serie(cdi, 0.149)
    formas = []
    for forma, lista in ESPECIES.items():
        saida_esp = [saida_especie(sp, agora, cdi, cdi_ano) for sp in especies if sp.forma == forma]
        formas.append({"id": forma, "nome": FORMA_NOME.get(forma, forma), "especies": saida_esp})
    est["eventos"] = ev.para_json()
    return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "avisos": AVISOS, "padrao": None, "versoes": [],
            "eventos": est["eventos"], "formas": formas,
            "regras": {"pop": P["POP"], "sobrevivem": P["SOBREVIVEM"], "filhas": P["FILHAS"],
                       "mutantes": P["MUTANTES"], "novatas": P["NOVATAS"], "geracoesDia": P["GERACOES_DIA"],
                       "histDias": P["HIST_DIAS"], "janelas": JANELAS, "minOps": P["MIN_OPS"],
                       "popLiga": P["POP_LIGA"], "saemLiga": P["SAEM_LIGA"], "doLab": P["DO_LAB"],
                       "semanasNota": P["SEMANAS_NOTA"], "semanasCoroa": P["SEMANAS_COROA"],
                       "minDiasSemana": MIN_DIAS_SEMANA, "mutFilha": MUT_FILHA},
            "erros": erros}


# ====================================================================== saída
def _r(x, n=5):
    return round(x, n) if isinstance(x, (int, float)) and not isinstance(x, bool) else x


def saida_lab_ind(i):
    out = {k: i[k] for k in ("id", "nome", "genes", "tipo", "pais", "origem", "g") if k in i}
    if i.get("sob"):
        out["familia"] = i["sob"][-1]
    for k in ("nota", "val", "jan", "ret", "queda", "ops", "morta", "semNota", "idade", "de"):
        if i.get(k) is not None:
            out[k] = i[k]
    return out


def conta_viva(ind, cdi, cdi_ano, serie=False):
    c = Curva.de_json(ind["c"])
    r = c.resumo()
    out = {"retorno": r["retorno"], "piorQueda": r["piorQueda"], "ops": r["ops"], "nLiq": r["nLiq"],
           "morta": bool(ind["s"].get("morta")), "inicio": r["inicio"]}
    if serie:
        out["serie"] = r["serie"][-SERIE_SAIDA:]
        try:
            out["metricas"] = metricas(r, cdi, cdi_ano)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            out["metricas"] = None
    return out


def saida_liga_ind(sp, ind, cdi, cdi_ano, serie):
    out = {k: ind[k] for k in ("id", "nome", "genes", "tipo", "pais", "origem", "fonte", "desde", "lab", "de", "semana")
           if ind.get(k) is not None}
    if ind.get("sob"):
        out["familia"] = ind["sob"][-1]
    out["notas"] = [[int(w)] + list(v) for w, v in sorted((ind.get("notas") or {}).items(), key=lambda x: int(x[0]))]
    out["media"] = sp.media_liga(ind)
    out["aoVivo"] = conta_viva(ind, cdi, cdi_ano, serie)
    return out


def saida_especie(sp, agora, cdi, cdi_ano):
    esp, e = sp.esp, sp.e
    lab = e.get("lab") or {}
    liga = e.get("liga")
    ctrl_cfg = sp.cfg_padrao[esp["controle"]]
    out = {"id": esp["id"], "nome": esp["nome"], "icone": esp["icone"], "frase": esp["frase"],
           "genes": [{k: v for k, v in g.items()} for g in esp["genes"]],
           "controle": {"id": esp["controle"], "nome": ctrl_cfg["nome"], "genes": sp.controle_genes(),
                        "descricao": descrever(esp, sp.controle_genes())}}
    if lab.get("pop"):
        ordem = sorted(lab["pop"], key=lambda i: -_n(i.get("nota")))
        pop = []
        for i in ordem:
            x = saida_lab_ind(i)
            x["descricao"] = descrever(esp, i["genes"])
            pop.append(x)
        out["lab"] = {"g": lab.get("g", 0), "dia": lab.get("dia"), "hoje": lab.get("hoje", 0), "pop": pop,
                      "controle": {k: v for k, v in (lab.get("controle") or {}).items() if k != "dia"},
                      "hist": lab.get("hist", [])[-HIST_SAIDA:], "saiu": lab.get("saiu", []),
                      "nasceu": lab.get("nasceu", []), "aprovadas": [i["id"] for i in sp.aprovadas(lab)]}
    if liga:
        camp = (liga.get("campea") or {}).get("id")
        ordem = sorted(liga["pop"], key=lambda i: (-_n(sp.media_liga(i)), -float(i["c"].get("ultimo") or 0)))
        com_serie = {i["id"] for i in ordem[:COM_SERIE]} | ({camp} if camp else set())
        pop = []
        for i in ordem:
            x = saida_liga_ind(sp, i, cdi, cdi_ano, i["id"] in com_serie)
            x["descricao"] = descrever(esp, i["genes"])
            pop.append(x)
        ctrl = saida_liga_ind(sp, liga["controle"], cdi, cdi_ano, True)
        ctrl["descricao"] = descrever(esp, liga["controle"]["genes"])
        c = liga.get("campea")
        if c:
            atual = next((i for i in liga["pop"] if i["id"] == c["id"]), None)
            c = dict(c, descricao=descrever(esp, c["genes"]))
            if atual:
                c["vsControle"] = [[int(w), v[0], (liga["controle"]["notas"].get(w) or [None])[0]]
                                   for w, v in sorted(atual["notas"].items(), key=lambda x: int(x[0]))]
        out["liga"] = {"inicio": liga["inicio"], "semana": liga["semana"], "semanaDe": segunda_de(liga["semana"]),
                       "pop": pop, "controle": ctrl, "campea": c, "coroadas": liga.get("coroadas", []),
                       "semanas": liga.get("semanas", [])}
    out["arvore"] = e.get("arvore", {})
    return out
