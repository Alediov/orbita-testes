"""Evolução do copy trading, NO PAPEL (pedido do Alediov, 16/11/2026, item 4 do plano de melhorias: depois dos Robôs,
"o Copy trading: jeito de copiar, multiplicador, atraso, quem copiar, a regra de largar a carteira").

A espécie é a **carteira de carteiras** (como "As 5 melhores" das agregadas, que é o controle): toda versão começa com
US$ 1.000 fictícios e, a cada troca, divide o dinheiro em partes iguais entre as carteiras que a regra dela escolhe.
Os genes (o que evolui):

- `jeito`: com qual das contas de cópia a carteira é seguida ("3x1", "5x1", "3x1s", "5x1a2", "3x1p20"…: a alavancagem,
  o atraso, as saídas de segurança, a amplificada, a entrada fixa e o parar de copiar já são contas que o teste roda
  para toda carteira; o gene escolhe uma);
- `quem`: as melhores (pelo % ao mês da cópia naquele jeito), só robôs, só pessoas ou todas;
- `n`, `minDias` e `olhar` (só nas melhores): quantas, com quantos dias de cópia no mínimo e olhando quantos dias para
  trás (0 = desde o começo);
- `troca`: de quantos em quantos dias refaz a escolha (3, 7 ou 14);
- `largar`: a fatia de uma carteira que cai tanto assim do topo dela vira dinheiro parado até a próxima troca
  (0 = não larga).

Não precisa de rede: as contas saem do **banco de séries** (`est["bancoEv"]`: a série diária de TODOS os jeitos de
copiar de cada carteira que já foi seguida; o `banco` das agregadas guarda só o jeito padrão, e dele vêm o começo, a
saída e o selo robô/pessoa de cada carteira). Cada troca paga `CUSTO_LADO` de cada dólar que sai e que entra (a mesma
aproximação das agregadas). Como tudo é refeito pelas séries, uma conta é só os genes e o dia em que começou.

Duas frentes, como nos Robôs (as mesmas regras e números; a genética é a mesma, `tools/papel/genetica.py`):

- **Laboratório** (no passado, "aproximado"): uma vez por dia, até GERACOES_DIA gerações de POP versões, cada uma
  rodando do 1º dia do banco até hoje. Só começa com MIN_DIAS_LAB dias de banco (antes disso `labEspera` diz quantos
  dias faltam): os primeiros 3/4 são o treino, em 3 janelas (nota = média das janelas − ½ desvio; cada janela = retorno
  ao mês − ½ pior queda), o último 1/4 é a prova. Versão que nunca chegou a montar a carteira fica sem nota.
- **Liga** (ao vivo): POP_LIGA versões + o controle, todas começando no dia em que entram. Toda segunda (Brasília) cada
  uma ganha a nota da semana (retorno − ½ pior queda pelos pontos diários); saem as SAEM_LIGA piores pela média das
  últimas SEMANAS_NOTA notas e entram aprovadas do laboratório, filhas das melhores, uma mutante da melhor e sorteadas.
  **Campeã**: venceu o controle SEMANAS_COROA semanas seguidas; não substitui "As 5 melhores" (as duas frentes
  continuam) e perde a coroa se perder do controle SEMANAS_COROA semanas seguidas.

Aviso que vai no resultado: o selo robô/pessoa é o de hoje (não o de cada semana) e as carteiras que saíram do teste
antes de 16/11/2026 só têm no banco a série do jeito padrão.

Estado em `est["evolucao"]`; saída em `resumo["evolucao"]` (o mesmo formato das espécies do `evolucao.json` dos Robôs,
tools/papel/FORMATO.md, "Evolução", para o app mostrar na mesma aba). Teste: `teste_evolucao_copia.py`.
"""
from __future__ import annotations

import bisect
import datetime as dt
import random
import statistics

from genetica import NOMES, SOBRENOMES, ativo, chave, cruzar, mutar, reparar, romano, sortear
from sim import dia_de

VERSAO = 1
CAPITAL = 1000.0
CUSTO_LADO = 0.0015
DIA = 86_400_000
# laboratório
POP, SOBREVIVEM, FILHAS, MUTANTES, NOVATAS = 24, 12, 8, 2, 2
GERACOES_DIA = 10
MIN_DIAS_LAB = 28
JANELAS = 3
MAX_HIST, HIST_SAIDA = 300, 150
# liga
POP_LIGA, SAEM_LIGA, DO_LAB, FILHAS_LIGA, MUTANTES_LIGA = 24, 6, 3, 2, 1
SEMANAS_NOTA, SEMANAS_COROA, MIN_DIAS_SEMANA = 4, 4, 5
SERIE_SAIDA, COM_SERIE, MAX_SEMANAS, ARVORE_NIVEIS, MAX_EVENTOS = 120, 6, 52, 4, 40

PARAMS = ("POP", "SOBREVIVEM", "FILHAS", "MUTANTES", "NOVATAS", "GERACOES_DIA", "MIN_DIAS_LAB", "POP_LIGA", "SAEM_LIGA",
          "DO_LAB", "FILHAS_LIGA", "MUTANTES_LIGA", "SEMANAS_NOTA", "SEMANAS_COROA", "MIN_DIAS_SEMANA")
FRASE = ("Carteiras de carteiras que evoluem: toda semana as piores regras saem, as melhores se cruzam e, às vezes, "
         "um gene muda. Só no papel.")
AVISOS = ["Só simulação, com saldo fictício: nenhuma ordem, nenhuma conta.",
          "As contas são refeitas pelas séries diárias das cópias; cada troca de carteira paga 0,15% de cada lado "
          "(aproximação).",
          "O selo de robô ou pessoa é o de hoje, não o de cada semana.",
          "O laboratório só começa com 4 semanas de cópias guardadas: com poucos dias, a nota seria sorte."]


def parametros(exemplo=False):
    P = {k: globals()[k] for k in PARAMS}
    if exemplo:  # o mercado de mentira tem poucos dias e poucas carteiras
        P.update(POP=8, SOBREVIVEM=4, FILHAS=2, MUTANTES=1, NOVATAS=1, GERACOES_DIA=2, MIN_DIAS_LAB=8, POP_LIGA=8,
                 SAEM_LIGA=2, DO_LAB=1, FILHAS_LIGA=1, MUTANTES_LIGA=1, SEMANAS_COROA=2, MIN_DIAS_SEMANA=3)
    return P


def especie(jeitos, padrao, nome_jeito=None):
    """A espécie com os jeitos de copiar que o teste roda (as chaves das contas: "3x1", "5x1s"…)."""
    rot = {j: (nome_jeito(j) if nome_jeito else j) for j in jeitos}
    return {
        "id": "carteiras", "nome": "Carteira de carteiras", "icone": "🧺", "prefixo": "c", "controle": "top5",
        "frase": "Toda troca, o dinheiro é dividido entre as carteiras da regra: o jeito de copiar, quem copiar, "
                 "quantas, a troca e a hora de largar evoluem.",
        "genes": [
            {"k": "jeito", "nome": "Jeito de copiar", "tipo": "op", "opcoes": list(jeitos), "rotulos": rot,
             "neutro": padrao},
            {"k": "quem", "nome": "Quem copiar", "tipo": "op", "opcoes": ["top", "robos", "humanos", "todas"],
             "rotulos": {"top": "As melhores", "robos": "Só robôs", "humanos": "Só pessoas", "todas": "Todas"},
             "neutro": "top"},
            {"k": "n", "nome": "Quantas", "tipo": "int", "min": 1, "max": 8, "passo": 1, "neutro": 5,
             "so": {"quem": "top"}},
            {"k": "minDias", "nome": "Com pelo menos", "tipo": "int", "min": 3, "max": 21, "passo": 1, "un": "d",
             "neutro": 7, "so": {"quem": "top"}},
            {"k": "olhar", "nome": "Olhando para trás", "tipo": "op", "opcoes": [0, 7, 14, 30], "un": "d",
             "rotulos": {"0": "Desde o começo"}, "neutro": 0, "so": {"quem": "top"}},
            {"k": "troca", "nome": "Troca a cada", "tipo": "op", "opcoes": [3, 7, 14], "un": "d", "neutro": 7},
            {"k": "largar", "nome": "Larga quem cai", "tipo": "op", "opcoes": [0, 0.1, 0.15, 0.2, 0.3], "un": "%",
             "rotulos": {"0": "Não"}, "neutro": 0},
        ],
    }


def genes_controle(esp):
    """"As 5 melhores" das agregadas: o jeito padrão, as 5 com 7 dias ou mais, troca semanal, sem largar."""
    return reparar(esp, {g["k"]: g["neutro"] for g in esp["genes"]})


def sementes(esp):
    """As outras carteiras de carteiras que já existem (só robôs, só pessoas) e todas."""
    base = genes_controle(esp)
    return [("robos", reparar(esp, {**base, "quem": "robos"})), ("humanos", reparar(esp, {**base, "quem": "humanos"})),
            ("todas", reparar(esp, {**base, "quem": "todas"}))]


def descrever(esp, genes):
    por = {g["k"]: g for g in esp["genes"]}
    rot = lambda k: (por[k].get("rotulos") or {}).get(str(genes[k]), str(genes[k]))  # noqa: E731
    quem = f"as {genes['n']} melhores" if genes["quem"] == "top" else rot("quem").lower()
    if genes["quem"] == "top" and genes["n"] == 1:
        quem = "a melhor"
    out = [genes["jeito"], quem, f"troca a cada {genes['troca']} d"]
    if genes["largar"]:
        out.append(f"larga a −{round(genes['largar'] * 100)}%")
    return " · ".join(out)


# ====================================================================== dias e semanas
def _data(dia):
    return dt.date.fromisoformat(dia)


def mais_dias(dia, n):
    return (_data(dia) + dt.timedelta(days=n)).isoformat()


def dias_entre(a, b):
    return (_data(b) - _data(a)).days


def semana_de(ms):
    """O número da semana (de segunda a domingo, horário de Brasília)."""
    return ((int(ms) - 3 * 3_600_000) // DIA + 3) // 7


def segunda_de(w):
    return (dt.date(1970, 1, 1) + dt.timedelta(days=int(w) * 7 - 3)).isoformat()


def semana_do_dia(dia):
    return (dias_entre("1970-01-01", dia) + 3) // 7


# ====================================================================== o banco de séries
def atualizar_banco(est):
    """A série diária de TODOS os jeitos de copiar de cada carteira seguida (as que saem continuam no banco)."""
    bv = est.setdefault("bancoEv", {})
    for e, c in (est.get("carteiras") or {}).items():
        b = bv.setdefault(e, {})
        for k, r in (c.get("resumo") or {}).items():
            s = b.setdefault(k, {})
            for d, v in (r or {}).get("serie") or []:
                s[d] = v
    return bv


class Dados:
    """As séries das cópias: o valor (US$ 1.000 no começo) da cópia de uma carteira, num jeito, num dia."""

    def __init__(self, est, padrao):
        self.padrao = padrao
        self.bv = est.get("bancoEv") or {}
        info = {e: b for e, b in (est.get("banco") or {}).items() if b.get("desde")}
        self.ini = {e: dia_de(b["desde"]) for e, b in info.items()}
        self.fim = {e: (dia_de(b["ate"]) if b.get("ate") else None) for e, b in info.items()}
        self.selo = {e: b.get("selo") for e, b in info.items()}
        self.velho = {e: b.get("serie") or {} for e, b in info.items()}  # o jeito padrão, do banco das agregadas
        self.carteiras = sorted(info)
        self.primeiro = min(self.ini.values()) if info else None
        self._c = {}

    def _serie(self, e, jeito):
        k = (e, jeito)
        if k not in self._c:
            s = (self.bv.get(e) or {}).get(jeito)
            if not s and jeito == self.padrao:
                s = self.velho.get(e)
            s = s or {}
            d = sorted(s)
            self._c[k] = (d, [s[x] for x in d])
        return self._c[k]

    def tem(self, e, jeito):
        return bool(self._serie(e, jeito)[0])

    def valor(self, e, jeito, dia):
        if dia < self.ini[e]:
            return None
        d, v = self._serie(e, jeito)
        i = bisect.bisect_right(d, dia) - 1
        return v[i] if i >= 0 else CAPITAL

    def ativa(self, e, dia):
        return dia >= self.ini[e] and (self.fim[e] is None or dia < self.fim[e])


def escolher(D, genes, dia):
    """As carteiras da regra num dia (só as que estão no teste e têm série naquele jeito)."""
    j = genes["jeito"]
    ativas = [e for e in D.carteiras if D.ativa(e, dia) and D.tem(e, j)]
    q = genes["quem"]
    if q in ("robos", "humanos"):
        alvo = "robo" if q == "robos" else "humano"
        return [e for e in ativas if D.selo.get(e) == alvo]
    if q == "todas":
        return ativas
    nota = []
    for e in ativas:
        n = dias_entre(D.ini[e], dia)
        v = D.valor(e, j, dia)
        if n < genes["minDias"] or not v or v <= 0:
            continue
        v0 = CAPITAL
        if genes["olhar"] and n > genes["olhar"]:
            v0, n = D.valor(e, j, mais_dias(dia, -genes["olhar"])) or CAPITAL, genes["olhar"]
        if v0 <= 0:
            continue
        nota.append(((v / v0) ** (30 / max(1, n)) - 1, e))
    return [e for _, e in sorted(nota, reverse=True)[:genes["n"]]]


def simular(D, genes, inicio, hoje):
    """A conta de uma versão de `inicio` a `hoje` (dias): { serie: [[dia, US$]], retorno, piorQueda, ops (trocas),
    custos, membros, largadas, montou }. Antes de a regra achar alguma carteira, o dinheiro fica parado."""
    j, larga = genes["jeito"], genes["largar"]
    fatias, caixa, proxima, montou = {}, CAPITAL, None, False
    serie, ops, custos, largadas, pico, queda = [], 0, 0.0, 0, CAPITAL, 0.0
    dia = inicio

    def vale(e, f):
        return f["fora"] if f["fora"] is not None else f["v0"] * (D.valor(e, j, dia) or f["base"]) / f["base"]

    while dia <= hoje:
        for e, f in fatias.items():
            if f["fora"] is not None:
                continue
            v = vale(e, f)
            f["pico"] = max(f["pico"], v)
            if larga and v <= f["pico"] * (1 - larga):  # largou: fecha a cópia e espera a troca
                custos += v * CUSTO_LADO
                f["fora"] = v * (1 - CUSTO_LADO)
                largadas += 1
            elif not D.ativa(e, dia):  # a carteira saiu do teste: dinheiro parado até a troca
                f["fora"] = v
        total = caixa + sum(vale(e, f) for e, f in fatias.items())
        if not montou or dia >= proxima:
            alvo = escolher(D, genes, dia)
            if alvo or montou:
                novos = {e: total / len(alvo) for e in alvo}
                atuais = {e: vale(e, f) for e, f in fatias.items() if f["fora"] is None}
                custo = sum(abs(novos.get(e, 0.0) - atuais.get(e, 0.0)) for e in set(novos) | set(atuais)) * CUSTO_LADO
                custos += custo
                total -= custo
                if not montou or set(novos) != set(atuais):
                    ops += 1
                fatias = {e: {"v0": total / len(alvo), "base": D.valor(e, j, dia) or CAPITAL, "pico": total / len(alvo),
                              "fora": None} for e in alvo}
                caixa = 0.0 if alvo else total
                montou, proxima = True, mais_dias(dia, genes["troca"])
        serie.append([dia, round(total, 2)])
        pico = max(pico, total)
        queda = max(queda, 1 - total / pico if pico > 0 else 0.0)
        dia = mais_dias(dia, 1)
    ultimo = serie[-1][1] if serie else CAPITAL
    return {"serie": serie, "retorno": round(ultimo / CAPITAL - 1, 5), "piorQueda": round(queda, 4), "ops": ops,
            "custos": round(custos, 2), "largadas": largadas, "montou": montou,
            "membros": sorted(e[:6] + "…" + e[-4:] if len(e) > 12 else e for e, f in fatias.items() if f["fora"] is None)}


# ====================================================================== notas
def _queda(vals):
    pico, q = vals[0], 0.0
    for v in vals:
        pico = max(pico, v)
        q = max(q, 1 - v / pico if pico > 0 else 0.0)
    return q


def nota_janela(vals, dias):
    """Retorno ao mês − ½ pior queda de um trecho da série."""
    if len(vals) < 2 or vals[0] <= 0 or dias <= 0:
        return None
    r = vals[-1] / vals[0]
    return (r ** (30 / dias) - 1 if r > 0 else -1.0) - 0.5 * _queda(vals)


def nota_lab(conta):
    """{ nota, val, jan, ret, queda, ops } de uma conta rodada no banco inteiro, ou None (curta demais, nunca montou)."""
    vals = [v for _, v in conta["serie"]]
    n = len(vals)
    if n < 8 or not conta["montou"]:
        return None
    q = n // (JANELAS + 1)
    jan = [nota_janela(vals[i * q:(i + 1) * q + 1], q) for i in range(JANELAS)]
    val = nota_janela(vals[JANELAS * q:], n - 1 - JANELAS * q)
    if any(x is None for x in jan) or val is None:
        return None
    nota = statistics.mean(jan) - 0.5 * statistics.pstdev(jan)
    return {"nota": round(nota, 5), "val": round(val, 5), "jan": [round(x, 5) for x in jan], "ret": conta["retorno"],
            "queda": conta["piorQueda"], "ops": conta["ops"]}


def nota_semana(serie, w, min_dias):
    """[nota, retorno, queda] da semana `w` pelos pontos diários (o valor de antes da semana é o ponto de partida)."""
    antes = [v for d, v in serie if semana_do_dia(d) < w]
    dentro = [v for d, v in serie if semana_do_dia(d) == w]
    if len(dentro) < min_dias:
        return None
    vals = [antes[-1] if antes else CAPITAL] + dentro
    if vals[0] <= 0:
        return None
    r, q = vals[-1] / vals[0] - 1, _queda(vals)
    return [round(r - 0.5 * q, 5), round(r, 5), round(q, 4)]


def _n(x):
    return x if isinstance(x, (int, float)) else float("-inf")


# ====================================================================== a espécie: laboratório e liga
class Evolucao:
    def __init__(self, est, esp, agora, P=None, log=print):
        self.esp, self.agora, self.hoje, self.P, self.log = esp, agora, dia_de(agora), P or parametros(), log
        e = est.get("evolucao")
        if not e or e.get("v") != VERSAO:
            e = est["evolucao"] = {"v": VERSAO, "contador": 0, "arvore": {}, "lab": None, "liga": None, "eventos": [],
                                   "semente": random.Random(agora).randrange(1 << 30)}
        self.e = e
        self.rng = random.Random(e["semente"] * 1000 + semana_de(agora) * 31 + int(self.hoje.replace("-", "")))
        self._nomes = {a["n"] for a in e["arvore"].values()}
        # os jeitos mudaram (uma conta nova ou tirada): os genes de todos voltam ao domínio
        for ind in self._todos():
            ind["genes"] = reparar(esp, ind["genes"])

    def _todos(self):
        lab, liga = self.e.get("lab") or {}, self.e.get("liga") or {}
        return list(lab.get("pop") or []) + list(liga.get("pop") or []) + ([liga["controle"]] if liga.get("controle") else [])

    def evento(self, tipo, texto):
        self.e["eventos"] = (self.e["eventos"] + [{"em": self.agora, "versao": self.esp["id"], "tipo": tipo,
                                                   "texto": texto}])[-MAX_EVENTOS:]

    # -------------------------------------------------------------- nascer
    def batizar(self, tipo, pais):
        """A filha leva o último sobrenome da mãe e o do pai; a mutante, os de quem veio; a novata e a semente fundam
        uma família. Nome repetido ganha II, III… (as mesmas regras dos Robôs)."""
        arv, rng = self.e["arvore"], self.rng
        sp = [(arv.get(i) or {}).get("s") or [] for i in pais]
        if tipo == "filha" and len(sp) == 2 and sp[0] and sp[1]:
            sob = [sp[1][-1], sp[0][-1]] if sp[1][-1] != sp[0][-1] else [sp[0][-1]]
        elif tipo == "mutante" and sp and sp[0]:
            sob = list(sp[0])
        else:
            usados = {x for a in arv.values() for x in a.get("s") or []}
            sob = [rng.choice([x for x in SOBRENOMES if x not in usados] or SOBRENOMES)]
        familia = " ".join(sob)
        for _ in range(12):
            nome = f"{rng.choice(NOMES)} {familia}"
            if nome not in self._nomes:
                return nome, sob
        k = 2
        while f"{nome} {romano(k)}" in self._nomes:
            k += 1
        return f"{nome} {romano(k)}", sob

    def nascer(self, genes, tipo, pais=(), origem=None, g=None, de=None):
        self.e["contador"] += 1
        nome, sob = self.batizar(tipo, pais)
        ind = {"id": f"{self.esp['prefixo']}{self.e['contador']}", "nome": nome, "sob": sob, "genes": genes, "tipo": tipo,
               "pais": list(pais), "origem": origem or {k: "novo" for k in genes}, "g": g}
        if de:
            ind["de"] = de
        self.e["arvore"][ind["id"]] = {"n": nome, "s": sob, "t": tipo, "p": list(pais), "g": g}
        self._nomes.add(nome)
        return ind

    def nova(self, usadas, g=None, tentativas=30):
        """Uma versão sorteada que ainda não existe na população."""
        genes = sortear(self.rng, self.esp)
        for _ in range(tentativas):
            if chave(genes) not in usadas:
                break
            genes = sortear(self.rng, self.esp)
        usadas.add(chave(genes))
        return self.nascer(genes, "novata", g=g)

    def filha(self, pop, usadas, nota, g=None):
        """Dois torneios de 3; o pai é o de nota melhor."""
        tor = lambda: max(self.rng.sample(pop, min(3, len(pop))), key=nota)  # noqa: E731
        a, b = tor(), tor()
        for _ in range(6):
            if b["id"] != a["id"] or len(pop) < 2:
                break
            b = tor()
        pai, mae = (a, b) if nota(a) >= nota(b) else (b, a)
        genes, origem = cruzar(self.rng, self.esp, pai, mae)
        for _ in range(10):
            if chave(genes) not in usadas:
                break
            genes, origem, _m = mutar(self.rng, self.esp, genes, origem)
        usadas.add(chave(genes))
        return self.nascer(genes, "filha", (pai["id"], mae["id"]), origem, g)

    def mutante(self, de, usadas, g=None):
        genes, origem = dict(de["genes"]), {k: "pai" for k in de["genes"]}
        for _ in range(10):
            genes, origem, _m = mutar(self.rng, self.esp, genes, origem, self.rng.choice((1, 2)))
            if chave(genes) not in usadas:
                break
        usadas.add(chave(genes))
        return self.nascer(genes, "mutante", (de["id"],), origem, g)

    # -------------------------------------------------------------- laboratório
    def avaliar(self, D, ind, cache):
        k = chave(ind["genes"])
        if k not in cache:
            cache[k] = nota_lab(simular(D, ind["genes"], D.primeiro, self.hoje))
        r = cache[k]
        for c in ("nota", "val", "jan", "ret", "queda", "ops"):
            ind[c] = r[c] if r else None
        ind["semNota"] = r is None
        return r

    def aprovadas(self, lab=None):
        """As do laboratório melhores que o controle no treino E na prova (a melhor primeiro)."""
        lab = lab or self.e.get("lab") or {}
        c = lab.get("controle") or {}
        if c.get("nota") is None:
            return []
        ok = [i for i in lab.get("pop") or [] if i.get("nota") is not None and i["nota"] > c["nota"] and i["val"] > c["val"]]
        return sorted(ok, key=lambda i: -i["nota"])

    def rodar_lab(self, D):
        P, e = self.P, self.e
        dias = dias_entre(D.primeiro, self.hoje) if D.primeiro else 0
        if dias < P["MIN_DIAS_LAB"]:
            e["labEspera"] = {"faltam": P["MIN_DIAS_LAB"] - dias, "dias": dias, "precisa": P["MIN_DIAS_LAB"]}
            return
        e.pop("labEspera", None)
        lab = e.get("lab")
        if not lab:
            lab = e["lab"] = {"g": 0, "dia": None, "hoje": 0, "pop": [], "hist": [], "saiu": [], "nasceu": []}
            usadas = set()
            ctrl = genes_controle(self.esp)
            usadas.add(chave(ctrl))
            lab["pop"].append(self.nascer(ctrl, "semente", g=0, de="top5"))
            for de, genes in sementes(self.esp):
                if chave(genes) not in usadas:
                    usadas.add(chave(genes))
                    lab["pop"].append(self.nascer(genes, "semente", g=0, de=de))
            while len(lab["pop"]) < P["POP"]:
                lab["pop"].append(self.nova(usadas, g=0))
        if lab["dia"] == self.hoje:
            return
        lab["dia"], lab["hoje"] = self.hoje, 0
        cache = {}
        for _ in range(P["GERACOES_DIA"]):
            self.geracao(lab, D, cache)
        self.log(f"  evolução (copy): laboratório na geração {lab['g']}, melhor {lab['pop'][0].get('nota')}")

    def geracao(self, lab, D, cache):
        P, pop = self.P, lab["pop"]
        for i in pop:
            self.avaliar(D, i, cache)
            i["idade"] = i.get("idade", 0) + 1
        rc = cache.get(chave(genes_controle(self.esp))) or nota_lab(simular(D, genes_controle(self.esp), D.primeiro, self.hoje))
        lab["controle"] = dict(rc or {"nota": None, "val": None}, dia=self.hoje)
        ordem = sorted(pop, key=lambda i: (-_n(i["nota"]), -i.get("idade", 0)))
        # clones (o mesmo resultado): fica a mais velha
        vistos, fica, saiu = set(), [], []
        for i in ordem:
            ass = (i["nota"], i["val"], i["ops"], i["ret"], i["queda"]) if i["nota"] is not None else ("sem", i["id"])
            if ass in vistos:
                saiu.append({"id": i["id"], "nome": i["nome"], "nota": i["nota"], "clone": True})
                continue
            vistos.add(ass)
            fica.append(i)
        sobrev = fica[:P["SOBREVIVEM"]]
        saiu += [{"id": i["id"], "nome": i["nome"], "nota": i["nota"]} for i in fica[P["SOBREVIVEM"]:]]
        com_nota = [i for i in sobrev if i["nota"] is not None] or sobrev
        g = lab["g"] + 1
        usadas = {chave(i["genes"]) for i in sobrev}
        nota = lambda i: _n(i["nota"])  # noqa: E731
        novas = [self.filha(com_nota, usadas, nota, g) for _ in range(P["FILHAS"])]
        novas += [self.mutante(self.rng.choice(com_nota), usadas, g) for _ in range(P["MUTANTES"])]
        while len(sobrev) + len(novas) < P["POP"]:
            novas.append(self.nova(usadas, g))
        notas = [i["nota"] for i in fica if i["nota"] is not None]
        melhor = fica[0] if fica else None
        lab["hist"] = (lab["hist"] + [{"g": g, "dia": self.hoje, "melhor": melhor and melhor["nota"], "id": melhor and melhor["id"],
                                       "mediana": round(statistics.median(notas), 5) if notas else None,
                                       "val": melhor and melhor["val"], "controle": lab["controle"].get("nota"),
                                       "valControle": lab["controle"].get("val")}])[-MAX_HIST:]
        for i in novas:  # as que nascem já ganham a nota (para a lista de hoje não ter buracos)
            self.avaliar(D, i, cache)
            i["idade"] = 0
        lab["pop"] = sorted(sobrev + novas, key=lambda i: -_n(i["nota"]))
        lab["saiu"], lab["nasceu"] = saiu, [i["id"] for i in novas]
        lab["g"], lab["hoje"] = g, lab["hoje"] + 1

    # -------------------------------------------------------------- liga
    def entrar(self, ind, fonte, liga):
        """Uma versão entra na liga: começa hoje, com US$ 1.000."""
        v = {k: ind[k] for k in ("id", "nome", "sob", "genes", "tipo", "pais", "origem", "g", "de") if k in ind}
        v.update(fonte=fonte, desde=self.agora, dia0=self.hoje, semana=liga["semana"], notas={})
        if ind.get("nota") is not None:
            v["lab"] = {"nota": ind["nota"], "val": ind["val"]}
        return v

    def semear_liga(self):
        P = self.P
        liga = {"inicio": self.agora, "semana": semana_de(self.agora), "pop": [], "semanas": [], "coroadas": [],
                "campea": None, "controle": None}
        ctrl = genes_controle(self.esp)
        liga["controle"] = {"id": "controle", "nome": "As 5 melhores", "genes": ctrl, "tipo": "controle", "pais": [],
                            "origem": {}, "fonte": "controle", "desde": self.agora, "dia0": self.hoje,
                            "semana": liga["semana"], "notas": {}}
        usadas = {chave(ctrl)}
        for i in self.aprovadas()[:P["POP_LIGA"] // 2]:
            if chave(i["genes"]) not in usadas:
                usadas.add(chave(i["genes"]))
                liga["pop"].append(self.entrar(i, "laboratório", liga))
        for de, genes in sementes(self.esp):
            if chave(genes) not in usadas and len(liga["pop"]) < P["POP_LIGA"]:
                usadas.add(chave(genes))
                liga["pop"].append(self.entrar(self.nascer(genes, "semente", de=de), "sorteada", liga))
        while len(liga["pop"]) < P["POP_LIGA"]:
            liga["pop"].append(self.entrar(self.nova(usadas), "sorteada", liga))
        self.e["liga"] = liga
        self.evento("liga", f"A liga das carteiras de carteiras começou com {len(liga['pop'])} versões e o controle "
                            "(As 5 melhores).")
        return liga

    def conta(self, D, ind):
        return simular(D, ind["genes"], ind["dia0"], self.hoje)

    @staticmethod
    def media(ind, n):
        ns = [ind["notas"][w][0] for w in sorted(ind.get("notas") or {}, key=int)][-n:]
        return round(statistics.mean(ns), 5) if ns else None

    @staticmethod
    def venceu(ind, ctrl, semanas):
        a, b = ind.get("notas") or {}, ctrl.get("notas") or {}
        if not semanas or any(str(w) not in a or str(w) not in b for w in semanas):
            return None
        if all(a[str(w)][0] > b[str(w)][0] for w in semanas):
            return 1
        return -1 if all(a[str(w)][0] < b[str(w)][0] for w in semanas) else 0

    def fechar_semana(self, D, liga):
        """A semana `liga["semana"]` acabou: notas, quem sai, quem entra, a coroa."""
        P, w = self.P, liga["semana"]
        ctrl, pop = liga["controle"], liga["pop"]
        for i in pop + [ctrl]:
            n = nota_semana(self.conta(D, i)["serie"], w, P["MIN_DIAS_SEMANA"])
            if n:
                i["notas"][str(w)] = n
                i["notas"] = {k: i["notas"][k] for k in sorted(i["notas"], key=int)[-MAX_SEMANAS:]}
        nc = (ctrl["notas"].get(str(w)) or [None])[0]
        com = [i for i in pop if str(w) in i["notas"]]
        media = lambda i: self.media(i, P["SEMANAS_NOTA"])  # noqa: E731
        reg = {"semana": w, "de": segunda_de(w), "controle": nc, "notas": len(com), "saiu": [], "entrou": []}
        if com:
            melhor = max(com, key=lambda i: i["notas"][str(w)][0])
            reg.update(melhor=melhor["id"], nota=melhor["notas"][str(w)][0],
                       mediana=round(statistics.median(i["notas"][str(w)][0] for i in com), 5),
                       venceram=sum(1 for i in com if nc is not None and i["notas"][str(w)][0] > nc))
            # a coroa
            camp = liga.get("campea")
            ultimas = [w - k for k in range(P["SEMANAS_COROA"])]
            if camp:
                atual = next((i for i in pop if i["id"] == camp["id"]), None)
                if not atual or self.venceu(atual, ctrl, ultimas) == -1:
                    liga["coroadas"] = (liga["coroadas"] + [dict(camp, ate=self.agora)])[-12:]
                    liga["campea"] = camp = None
                    self.evento("coroa", f"{(atual or {}).get('nome', 'A campeã')} perdeu a coroa: {P['SEMANAS_COROA']} "
                                         "semanas seguidas atrás do controle.")
            if not camp:
                cands = [i for i in pop if self.venceu(i, ctrl, ultimas) == 1]
                if cands:
                    c = max(cands, key=lambda i: _n(media(i)))
                    liga["campea"] = {"id": c["id"], "nome": c["nome"], "desde": self.agora, "genes": c["genes"], "semana": w}
                    self.evento("coroa", f"{c['nome']} é a campeã: venceu o controle {P['SEMANAS_COROA']} semanas seguidas.")
            # quem sai (só quem já tem nota; a campeã fica) e quem entra
            camp_id = (liga.get("campea") or {}).get("id")
            ordem = sorted((i for i in com if i["id"] != camp_id), key=lambda i: _n(media(i)))
            saem = ordem[:min(P["SAEM_LIGA"], max(0, len(ordem) - 2))]
            ids = {i["id"] for i in saem}
            reg["saiu"] = [{"id": i["id"], "nome": i["nome"], "media": media(i)} for i in saem]
            fica = [i for i in pop if i["id"] not in ids]
            usadas = {chave(i["genes"]) for i in fica} | {chave(ctrl["genes"])}
            liga["semana"] = semana_de(self.agora)
            novas = []
            for i in self.aprovadas():
                if len(novas) >= min(P["DO_LAB"], len(saem)):
                    break
                if chave(i["genes"]) not in usadas:
                    usadas.add(chave(i["genes"]))
                    novas.append(self.entrar(i, "laboratório", liga))
            bons = sorted((i for i in fica if media(i) is not None), key=lambda i: -_n(media(i)))
            topo = bons[:max(2, len(bons) // 2)]
            nota = lambda i: _n(media(i))  # noqa: E731
            for _ in range(P["FILHAS_LIGA"]):
                if len(novas) < len(saem) and len(topo) >= 2:
                    novas.append(self.entrar(self.filha(topo, usadas, nota), "liga", liga))
            for _ in range(P["MUTANTES_LIGA"]):
                if len(novas) < len(saem) and topo:
                    novas.append(self.entrar(self.mutante(topo[0], usadas), "liga", liga))
            while len(novas) < len(saem):
                novas.append(self.entrar(self.nova(usadas), "sorteada", liga))
            reg["entrou"] = [{"id": i["id"], "nome": i["nome"], "fonte": i["fonte"], "tipo": i["tipo"]} for i in novas]
            liga["pop"] = fica + novas
            self.evento("semana", f"Semana de {segunda_de(w)}: {reg['venceram']} de {len(com)} venceram o controle; "
                                  f"saíram {len(saem)} e entraram {len(novas)}.")
        liga["semana"] = semana_de(self.agora)
        liga["semanas"] = (liga["semanas"] + [reg])[-MAX_SEMANAS:]

    def rodar_liga(self, D):
        liga = self.e.get("liga")
        if not liga:
            if not D.carteiras:
                return None
            return self.semear_liga()
        if semana_de(self.agora) != liga["semana"]:
            self.fechar_semana(D, liga)
        return liga

    def podar_arvore(self):
        """Só os antepassados (até ARVORE_NIVEIS gerações) das versões vivas, da campeã e das coroadas."""
        arv, liga = self.e["arvore"], self.e.get("liga") or {}
        vivos = {i["id"] for i in self._todos()} | {c["id"] for c in liga.get("coroadas") or []}
        if liga.get("campea"):
            vivos.add(liga["campea"]["id"])
        manter, borda = set(vivos), set(vivos)
        for _ in range(ARVORE_NIVEIS):
            borda = {p for i in borda for p in (arv.get(i) or {}).get("p") or []} - manter
            manter |= borda
        self.e["arvore"] = {k: v for k, v in arv.items() if k in manter}

    # -------------------------------------------------------------- saída
    def _ind(self, i):
        out = {k: i[k] for k in ("id", "nome", "genes", "tipo", "pais", "origem", "g", "fonte", "desde", "lab", "de",
                                 "semana") if i.get(k) is not None}
        if i.get("sob"):
            out["familia"] = i["sob"][-1]
        out["descricao"] = descrever(self.esp, i["genes"])
        return out

    def saida(self, D, metricas_de=None):
        esp, e, P = self.esp, self.e, self.P
        ctrl = genes_controle(esp)
        out = {"id": esp["id"], "nome": esp["nome"], "icone": esp["icone"], "frase": esp["frase"],
               "genes": [dict(g) for g in esp["genes"]],
               "controle": {"id": esp["controle"], "nome": "As 5 melhores", "genes": ctrl, "descricao": descrever(esp, ctrl)}}
        lab, liga = e.get("lab"), e.get("liga")
        if e.get("labEspera"):
            out["labEspera"] = e["labEspera"]
        if lab and lab.get("pop"):
            pop = []
            for i in sorted(lab["pop"], key=lambda i: -_n(i.get("nota"))):
                x = self._ind(i)
                for k in ("nota", "val", "jan", "ret", "queda", "ops", "semNota", "idade"):
                    if i.get(k) is not None:
                        x[k] = i[k]
                pop.append(x)
            out["lab"] = {"g": lab["g"], "dia": lab["dia"], "hoje": lab["hoje"], "pop": pop,
                          "controle": {k: v for k, v in (lab.get("controle") or {}).items() if k != "dia"},
                          "hist": lab["hist"][-HIST_SAIDA:], "saiu": lab["saiu"], "nasceu": lab["nasceu"],
                          "aprovadas": [i["id"] for i in self.aprovadas(lab)]}
        if liga:
            contas = {i["id"]: self.conta(D, i) for i in liga["pop"] + [liga["controle"]]}
            media = lambda i: self.media(i, P["SEMANAS_NOTA"])  # noqa: E731
            ordem = sorted(liga["pop"], key=lambda i: (-_n(media(i)), -contas[i["id"]]["retorno"]))
            camp = (liga.get("campea") or {}).get("id")
            com_serie = {i["id"] for i in ordem[:COM_SERIE]} | ({camp} if camp else set()) | {"controle"}

            def viva(i):
                c = contas[i["id"]]
                x = self._ind(i)
                x["notas"] = [[int(w)] + list(v) for w, v in sorted(i["notas"].items(), key=lambda t: int(t[0]))]
                x["media"] = media(i)
                x["aoVivo"] = {"retorno": c["retorno"], "piorQueda": c["piorQueda"], "ops": c["ops"], "nLiq": 0,
                               "morta": False, "inicio": i["desde"], "membros": c["membros"], "custos": c["custos"],
                               "largadas": c["largadas"]}
                if i["id"] in com_serie:
                    x["aoVivo"]["serie"] = c["serie"][-SERIE_SAIDA:]
                    if metricas_de:
                        try:
                            x["aoVivo"]["metricas"] = metricas_de({"serie": c["serie"], "inicio": i["desde"],
                                                                   "retorno": c["retorno"], "piorQueda": c["piorQueda"]})
                        except Exception:  # noqa: BLE001
                            x["aoVivo"]["metricas"] = None
                return x

            c = liga.get("campea")
            if c:
                atual = next((i for i in liga["pop"] if i["id"] == c["id"]), None)
                c = dict(c, descricao=descrever(esp, c["genes"]))
                if atual:
                    c["vsControle"] = [[int(w), v[0], (liga["controle"]["notas"].get(w) or [None])[0]]
                                       for w, v in sorted(atual["notas"].items(), key=lambda t: int(t[0]))]
            out["liga"] = {"inicio": liga["inicio"], "semana": liga["semana"], "semanaDe": segunda_de(liga["semana"]),
                           "pop": [viva(i) for i in ordem], "controle": viva(liga["controle"]), "campea": c,
                           "coroadas": liga["coroadas"], "semanas": liga["semanas"]}
        out["arvore"] = e["arvore"]
        return out


def rodar(est, agora, jeitos, padrao, nome_jeito=None, exemplo=False, log=print):
    """Uma rodada: o banco, o laboratório (uma vez por dia) e a liga (a virada na segunda). Devolve a `Evolucao`."""
    atualizar_banco(est)
    P = parametros(exemplo)
    ev = Evolucao(est, especie(jeitos, padrao, nome_jeito), agora, P, log)
    D = Dados(est, padrao)
    if D.carteiras:
        ev.rodar_lab(D)
        ev.rodar_liga(D)
        ev.podar_arvore()
    return ev, D


def resumo(ev, D, agora, metricas_de=None):
    """O bloco `evolucao` do resumo.json (o formato do evolucao.json dos Robôs: uma forma, "copy", com a espécie)."""
    P = ev.P
    return {"v": VERSAO, "forma": "evolucao", "nome": "Evolução", "agora": agora, "frase": FRASE,
            "avisos": AVISOS, "eventos": list(reversed(ev.e["eventos"])),
            "regras": {"pop": P["POP"], "sobrevivem": P["SOBREVIVEM"], "filhas": P["FILHAS"], "mutantes": P["MUTANTES"],
                       "novatas": P["NOVATAS"], "geracoesDia": P["GERACOES_DIA"], "minDiasLab": P["MIN_DIAS_LAB"],
                       "janelas": JANELAS, "popLiga": P["POP_LIGA"], "saemLiga": P["SAEM_LIGA"], "doLab": P["DO_LAB"],
                       "semanasNota": P["SEMANAS_NOTA"], "semanasCoroa": P["SEMANAS_COROA"],
                       "minDiasSemana": P["MIN_DIAS_SEMANA"], "custoLado": CUSTO_LADO},
            "formas": [{"id": "copy", "nome": "Copy trading", "especies": [ev.saida(D, metricas_de)]}]}


__all__ = ["rodar", "resumo", "especie", "simular", "escolher", "Dados", "Evolucao", "ativo"]
