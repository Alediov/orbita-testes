"""Evolução dos Cofres, NO PAPEL (pedido do Alediov, 17/11/2026, item 4 do plano de melhorias: depois dos Robôs e do
copy trading, "os Cofres e o Funding").

A espécie é a **carteira de cofres** (como "5 melhores", que é o controle): toda versão começa com US$ 1.000 fictícios
e, toda semana, escolhe os cofres pela regra dela. Os genes (o que evolui):

- `ordem`: como os cofres que passam na regra são ordenados: a nota de hoje (mês e ano ÷ pior queda, com o bônus do
  tamanho), o lucro do mês, o lucro de 90 dias ou a constância (lucro de 90 dias ÷ oscilação, sem quem fez mais da
  metade do lucro num dia só);
- `n`: quantos cofres (1 a 10);
- `tvl`, `idade` e `queda`: o tamanho mínimo, a idade mínima e a pior queda que a regra aceita;
- `fica`: quantos dias um escolhido fica antes de poder sair por não passar mais na regra;
- `stop`: sai do cofre que cai tanto assim do topo da nossa posição e não volta por 4 semanas (0 = sem);
- `hlp`: a parte que fica no HLP (0 = nada).

Não precisa de rede a mais: as contas saem do **banco de cofres** (`est["bancoEv"]`), um ponto por dia da cota e do TVL
(este em milhares de dólares) de cada cofre. O banco é semeado pelo teste fora da amostra (`cofres_passado.py`: o universo largo, com os cofres que
fecharam; a `semear` é chamada antes de ele jogar os detalhes fora) e anda uma vez por dia: pela cota dos cofres
acompanhados (a do `vaultDetails`) ou, nos outros, pela lista da corretora (r = Δ lucro desde o início ÷ TVL de ontem,
a mesma conta da `encadear`). A cada semeadura a história de um cofre é trocada pela do `vaultDetails`, mais fina.

O simulador é próprio e simples (um ponto por dia): partes iguais, reequilíbrio na escolha da semana, a comissão do
líder paga no saque (o valor mostrado já desconta a que seria paga hoje), sem a trava do depósito e sem a parte do
líder (o banco não tem a de cada semana). Por isso o controle é a regra dos 5 melhores REFEITA aqui: não bate centavo
a centavo com a conta "5 melhores" do teste.

O laboratório e a liga são os do motor comum (`evolucao_series.py`). Estado em `est["evolucao"]` (o dos Cofres);
saída em `cofres.json` → `evolucao` (FORMATO.md, "Evolução"). Teste: `teste_cofres_evolucao.py`.
"""
from __future__ import annotations

import datetime as dt
import functools
import math

import evolucao_series as ES
from conta import CAPITAL, DIA, cdi_ano_da_serie, dia_de, metricas
from genetica import reparar

VERSAO = 1
BANCO_V = 1
HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"
MAX_DIAS = 260          # dias de cota guardados por cofre (o que passa disso vira só o topo e a pior queda de antes)
PRE = 100               # dias de história antes do 1º dia do laboratório (a constância olha 90)
BAN = 28                # dias sem voltar ao cofre de que saiu pelo stop
R_MAX = 5.0
TVL_BASE = 100_000.0
CONST_DIAS, CONST_MAIOR_DIA = 90, 0.5
CDI_PADRAO = 0.149

FRASE = ("Carteiras de cofres que evoluem: toda semana as piores regras saem, as melhores se cruzam e, às vezes, um "
         "gene muda. Só no papel.")
AVISOS = ["Só simulação, com saldo fictício: nenhum depósito, nenhuma conta.",
          "As contas são refeitas pela cota de cada cofre, um ponto por dia; a comissão do líder sai no saque. A trava "
          "do depósito e a parte do líder não entram.",
          "O controle é a regra dos 5 melhores refeita por este simulador: não bate centavo a centavo com a conta "
          "5 melhores do teste.",
          "Os cofres são os do teste fora da amostra (os abertos pelo TVL de hoje e os fechados que ainda estão na "
          "lista); quando ele é refeito, a história de cada cofre fica mais fina e as contas podem mudar um pouco."]

ESP = {
    "id": "cofres", "nome": "Carteira de cofres", "icone": "🔐", "prefixo": "v", "controle": "top5",
    "frase": "Toda semana, o dinheiro vai em partes iguais para os cofres da regra: como ordenar, quantos, o tamanho, "
             "a idade, a queda aceita, o stop e a parte no HLP evoluem.",
    "genes": [
        {"k": "ordem", "nome": "Ordena por", "tipo": "op", "opcoes": ["nota", "mes", "tri", "const"],
         "rotulos": {"nota": "Nota de hoje", "mes": "Lucro do mês", "tri": "Lucro de 90 dias", "const": "Constância"},
         "neutro": "nota"},
        {"k": "n", "nome": "Quantos", "tipo": "int", "min": 1, "max": 10, "passo": 1, "neutro": 5},
        {"k": "tvl", "nome": "Tamanho mínimo", "tipo": "op", "opcoes": [100_000, 300_000, 1_000_000, 3_000_000],
         "rotulos": {"100000": "US$ 100 mil", "300000": "US$ 300 mil", "1000000": "US$ 1 mi", "3000000": "US$ 3 mi"},
         "neutro": 100_000},
        {"k": "idade", "nome": "Idade mínima", "tipo": "op", "opcoes": [30, 60, 90, 180], "un": "d", "neutro": 30},
        {"k": "queda", "nome": "Queda aceita", "tipo": "op", "opcoes": [0.15, 0.2, 0.3, 0.5], "un": "%", "neutro": 0.3},
        {"k": "fica", "nome": "Fica pelo menos", "tipo": "op", "opcoes": [7, 14, 28], "un": "d", "neutro": 28},
        {"k": "stop", "nome": "Stop", "tipo": "op", "opcoes": [0, 0.1, 0.15, 0.2], "un": "%", "rotulos": {"0": "Sem"},
         "neutro": 0},
        {"k": "hlp", "nome": "Parte no HLP", "tipo": "op", "opcoes": [0, 0.25, 0.5], "un": "%", "rotulos": {"0": "Nada"},
         "neutro": 0},
    ],
}


class Definicao:
    """A espécie como o motor comum espera."""
    versao, nome_controle, da_liga, rotulo, esp = VERSAO, "5 melhores", "das carteiras de cofres", "cofres", ESP

    def genes_controle(self):
        """"5 melhores": a nota de hoje, 5 cofres, US$ 100 mil, 30 dias, queda até 30%, fica 4 semanas, sem stop."""
        return reparar(ESP, {g["k"]: g["neutro"] for g in ESP["genes"]})

    def sementes(self):
        """As outras versões que o teste dos Cofres já roda."""
        b = self.genes_controle()
        return [(de, reparar(ESP, {**b, **m})) for de, m in (
            ("top10", {"n": 10}), ("top5s", {"stop": 0.15}), ("grandes", {"tvl": 1_000_000}),
            ("constancia", {"ordem": "const"}), ("mix50", {"hlp": 0.5}), ("mix25", {"hlp": 0.25}))]

    def descrever(self, genes):
        por = {g["k"]: g for g in ESP["genes"]}
        rot = lambda k: (por[k].get("rotulos") or {}).get(str(genes[k]), str(genes[k]))  # noqa: E731
        out = ["1 cofre" if genes["n"] == 1 else f"{genes['n']} cofres", rot("ordem").lower()]
        if genes["tvl"] != por["tvl"]["neutro"]:
            out.append(f"de {rot('tvl')} ou mais")
        if genes["stop"]:
            out.append(f"stop a −{round(genes['stop'] * 100)}%")
        if genes["hlp"]:
            out.append(f"{round(genes['hlp'] * 100)}% no HLP")
        return " · ".join(out)


# ====================================================================== dias
@functools.lru_cache(maxsize=4096)
def ordinal(dia):
    return dt.date.fromisoformat(dia).toordinal()


def dia_do(o):
    return dt.date.fromordinal(o).isoformat()


# ====================================================================== o banco de cofres
def _banco(est):
    b = est.get("bancoEv")
    if not b or b.get("v") != BANCO_V:
        b = est["bancoEv"] = {"v": BANCO_V, "cofres": {}, "ate": None, "primeiro": None}
    return b


def _mil(v):
    """O TVL fica guardado em milhares de dólares (inteiro): o banco vai no estado, que é gravado a cada rodada."""
    return int(round(v / 1000))


def _por_dia(pts, casas):
    """[[ms, v]] → (1º dia, [v de cada dia seguido]); o último ponto de cada dia vale; dia sem ponto repete o de antes.
    `casas` 0: é o TVL, guardado em milhares."""
    por = {}
    for t, v in pts:
        por[dia_de(int(t))] = v
    if not por:
        return None, []
    dias = sorted(por)
    o0, out, ult = ordinal(dias[0]), [], None
    for o in range(o0, ordinal(dias[-1]) + 1):
        ult = por.get(dia_do(o), ult)
        out.append(round(ult, casas) if casas else _mil(ult))
    return dias[0], out


def _valor(x, o, campo="s", zero="d0"):
    """O valor de um cofre do banco no dia `o` (ordinal): None antes do 1º; o último depois do fim."""
    v = x.get(campo) or []
    if not v or not x.get(zero):
        return None
    k = o - ordinal(x[zero])
    return None if k < 0 else v[min(k, len(v) - 1)]


def semear(est, dados, ini, fim, pre_dias=PRE):
    """Os cofres detalhados pelo teste fora da amostra (`p["dados"]` do cofres_passado: {endereço: {n, com, c, f, s, av}},
    com a cota por semana antes de `ini − pre_dias` e por dia depois) entram no banco, ou trocam a história que o banco
    tinha (os dias depois de `fim`, que vieram da lista, ficam, na escala nova)."""
    b = _banco(est)
    corte = ini - pre_dias * DIA
    n = 0
    for a, x in dados.items():
        velhos = [v for t, v in x["s"] if t < corte]
        d0, s = _por_dia([p for p in x["s"] if p[0] >= corte], 6)
        if len(s) < 2:
            continue
        i0, pico, queda = (velhos[0] if velhos else s[0]), 0.0, 0.0
        for v in velhos:
            pico = max(pico, v)
            queda = max(queda, 1 - v / pico if pico > 0 else 0.0)
        a0, av = _por_dia(x.get("av") or [], 0)
        novo = {"n": x["n"], "com": x.get("com"), "c": x.get("c"), "f": dia_de(x["f"]) if x.get("f") else None,
                "d0": d0, "s": [round(v, 5) for v in s], "a0": a0, "av": av, "antes": [round(i0, 6), round(pico, 6), round(queda, 5)]}
        velho = b["cofres"].get(a)
        if velho and not novo["f"]:
            o_fim = ordinal(d0) + len(s) - 1
            o_ult = ordinal(velho["d0"]) + len(velho["s"]) - 1
            base = _valor(velho, o_fim)
            if o_ult > o_fim and base and base > 0:
                k = s[-1] / base
                novo["s"] += [round(_valor(velho, o) * k, 5) for o in range(o_fim + 1, o_ult + 1)]
                if a0:
                    oa = ordinal(a0) + len(av) - 1
                    novo["av"] += [_valor(velho, o, "av", "a0") or (av[-1] if av else 0) for o in range(oa + 1, o_ult + 1)]
            for k_ in ("p", "ci"):
                if velho.get(k_) is not None:
                    novo[k_] = velho[k_]
        b["cofres"][a] = novo
        n += 1
    if n:
        d = dia_de(ini)
        b["primeiro"] = min(b["primeiro"], d) if b.get("primeiro") else d
        b["semeado"] = fim
    return n


def _estender(x, o, v, tvl):
    """A cota (e o TVL) do dia `o`: os dias que faltaram repetem o último valor."""
    s = x["s"]
    k = o - ordinal(x["d0"])
    while len(s) < k:
        s.append(s[-1])
    if len(s) == k:
        s.append(round(v, 5))
    else:
        s[k] = round(v, 5)
    if tvl is not None and x.get("a0"):
        av = x["av"]
        ka = o - ordinal(x["a0"])
        while len(av) < ka:
            av.append(av[-1] if av else _mil(tvl))
        if len(av) == ka:
            av.append(_mil(tvl))
        elif 0 <= ka < len(av):
            av[ka] = _mil(tvl)
    elif tvl is not None:
        x["a0"], x["av"] = dia_do(o), [_mil(tvl)]


def atualizar(est, linhas, cof, agora):
    """Uma vez por dia (Brasília): a cota de cada cofre do banco anda até hoje. `linhas`: a lista da corretora
    ({endereço: linha_lista}); `cof`: os acompanhados do teste (cota fina, do vaultDetails). Devolve quantos andaram."""
    b = est.get("bancoEv")
    hoje = dia_de(agora)
    if not b or not b.get("cofres") or b.get("ate") == hoje or not linhas:
        return 0
    o, n = ordinal(hoje), 0
    for a, x in b["cofres"].items():
        if x.get("f"):
            continue
        l, c = linhas.get(a), (cof or {}).get(a)
        if c and (c.get("sumiu") or not c.get("i")):
            c = None
        if not l and not c:  # sumiu da lista: sai pelo último valor
            x["f"] = hoje
            continue
        r, tvl, fechado = None, None, False
        if c:
            if x.get("ci"):
                r = c["i"] / x["ci"] - 1
            x["ci"], tvl, fechado = c["i"], c.get("tvl"), bool(c.get("fechado"))
        else:
            x.pop("ci", None)
        if l:
            p = x.get("p")
            if r is None and p and p[1] > 0:
                r = (l["lucroTotalUS"] - p[0]) / p[1]
            x["p"] = [round(l["lucroTotalUS"], 2), round(l["tvl"], 2)]
            tvl, fechado = l["tvl"], fechado or l["fechado"]
        _estender(x, o, x["s"][-1] * (1 + max(-1.0, min(R_MAX, r or 0.0))), tvl)
        if fechado:
            x["f"] = hoje
        n += 1
    b["ate"] = hoje
    podar(b, o)
    return n


def podar(b, o):
    """Só MAX_DIAS dias por cofre (o que sai vira o topo e a pior queda de antes); o cofre que acabou há mais que isso
    sai do banco."""
    corte = o - MAX_DIAS
    for a in [a for a, x in b["cofres"].items() if x.get("f") and ordinal(x["f"]) < corte]:
        del b["cofres"][a]
    for x in b["cofres"].values():
        k = corte - ordinal(x["d0"])
        if k <= 0:
            continue
        i0, pico, queda = x.get("antes") or [x["s"][0], 0.0, 0.0]
        for v in x["s"][:k]:
            pico = max(pico, v)
            queda = max(queda, 1 - v / pico if pico > 0 else 0.0)
        x["antes"], x["s"], x["d0"] = [i0, round(pico, 6), round(queda, 5)], x["s"][k:], dia_do(corte)
        if x.get("a0"):
            ka = corte - ordinal(x["a0"])
            if ka > 0:
                x["av"], x["a0"] = x["av"][ka:], dia_do(corte)
    if b.get("primeiro") and ordinal(b["primeiro"]) < corte + PRE:
        b["primeiro"] = dia_do(corte + PRE)


# ====================================================================== os números de cada cofre num dia
class Dados:
    """O banco de cofres para o simulador: a cota e as medidas de cada cofre num dia (ordinal)."""

    def __init__(self, est):
        b = est.get("bancoEv") or {}
        self.c = b.get("cofres") or {}
        self.primeiro = b.get("primeiro") if self.c else None
        self.o0 = {a: ordinal(x["d0"]) for a, x in self.c.items()}
        self.of = {a: ordinal(x["f"]) for a, x in self.c.items() if x.get("f")}
        self.oc = {a: ordinal(dia_de(x["c"])) for a, x in self.c.items() if x.get("c")}
        self._q, self._m = {}, {}

    @property
    def tem_dados(self):
        return bool(self.c) and bool(self.primeiro)

    def cota(self, a, o):
        k = o - self.o0[a]
        s = self.c[a]["s"]
        return None if k < 0 else s[min(k, len(s) - 1)]

    def acabou(self, a, o):
        return a in self.of and o > self.of[a]

    def nome(self, a):
        return "HLP" if a == HLP else self.c[a]["n"]

    def com(self, a):
        c = self.c[a].get("com")
        return 0.1 if c is None else c

    def _quedas(self, a):
        """A pior queda acumulada até cada dia (contando o topo e a queda de antes do banco)."""
        if a not in self._q:
            x = self.c[a]
            _i0, pico, queda = x.get("antes") or [x["s"][0], 0.0, 0.0]
            out = []
            for v in x["s"]:
                pico = max(pico, v)
                queda = max(queda, 1 - v / pico if pico > 0 else 0.0)
                out.append(queda)
            self._q[a] = out
        return self._q[a]

    def medidas(self, o):
        """{endereço: {lm, lt, l90, queda, idade, tvl, nota, const}} dos cofres vivos no dia `o` (os mesmos números da
        regra do teste: `cofres.medidas` e `cofres.constancia`, pela cota de um ponto por dia)."""
        if o in self._m:
            return self._m[o]
        out = {}
        for a, x in self.c.items():
            k = o - self.o0[a]
            if k < 1 or (a in self.of and o >= self.of[a]):
                continue
            s = x["s"]
            k = min(k, len(s) - 1)
            i_t, i0 = s[k], (x.get("antes") or [s[0]])[0]
            i_m = s[k - 30] if k >= 30 else s[0]
            if i_t <= 0 or i_m <= 0 or i0 <= 0:
                continue
            lm, lt = i_t / i_m - 1, i_t / i0 - 1
            queda = self._quedas(a)[k]
            idade = o - self.oc[a] if a in self.oc else k
            tvl = 1000.0 * (_valor(x, o, "av", "a0") or (x["av"][0] if x.get("av") else 0.0))
            ano = (1 + lt) ** (365 / max(idade, 30)) - 1 if lt > -1 else -1.0
            bonus = min(1.4, max(1.0, 1 + 0.1 * math.log10(max(tvl, 1) / TVL_BASE)))
            nota = (0.6 * max(-1.0, min(3.0, lm * 12)) + 0.4 * max(-1.0, min(3.0, ano))) / (queda + 0.05) * bonus
            m = {"lm": lm, "lt": lt, "queda": queda, "idade": idade, "tvl": tvl, "nota": nota, "l90": None, "const": None}
            if k >= CONST_DIAS:
                vals = s[k - CONST_DIAS:k + 1]
                if all(v > 0 for v in vals):
                    lucro = vals[-1] / vals[0] - 1
                    m["l90"] = lucro
                    rets = [q / p - 1 for p, q in zip(vals, vals[1:])]
                    med = sum(rets) / len(rets)
                    vol = math.sqrt(sum((r - med) ** 2 for r in rets) / max(1, len(rets) - 1))
                    ganho = vals[-1] - vals[0]
                    maior = max((q - p) / ganho for p, q in zip(vals, vals[1:])) if ganho > 0 else None
                    if lucro > 0 and not (maior is not None and maior > CONST_MAIOR_DIA):
                        m["const"] = min(99.0, lucro / (vol * math.sqrt(CONST_DIAS))) if vol > 1e-9 else 99.0
            out[a] = m
        self._m[o] = out
        return out

    # o que o motor comum pede
    def simular(self, genes, inicio, hoje):
        return simular(self, genes, inicio, hoje)

    @staticmethod
    def extras(c):
        return {"membros": c["membros"], "custos": c["custos"], "largadas": c["largadas"]}


CAMPO = {"nota": "nota", "mes": "lm", "tri": "l90", "const": "const"}


def escolher(D, genes, o):
    """Os cofres que passam na regra da versão no dia `o`, do melhor para o pior (sem o HLP)."""
    campo = CAMPO[genes["ordem"]]
    ok = []
    for a, m in D.medidas(o).items():
        if a == HLP or m[campo] is None:
            continue
        if m["tvl"] < genes["tvl"] or m["idade"] < genes["idade"] or m["queda"] > genes["queda"] or m["lm"] <= 0 or m["lt"] <= 0:
            continue
        ok.append((m[campo], a))
    return [a for _, a in sorted(ok, key=lambda t: (-t[0], t[1]))]


def simular(D, genes, inicio, hoje):
    """A conta de uma versão de `inicio` a `hoje` (dias): { serie: [[dia, US$]], retorno, piorQueda, ops (trocas de
    cofre), custos (a comissão paga), largadas (stops), membros, montou }. O valor de cada dia já desconta a comissão
    que seria paga no saque. Antes de a regra achar algum cofre, o dinheiro fica parado."""
    n, fica, stop, w = genes["n"], genes["fica"], genes["stop"], genes["hlp"]
    o1, o2 = ordinal(inicio), ordinal(hoje)
    pos, ban, caixa = {}, {}, CAPITAL       # pos: endereço → {q (cotas), base (o que entrou), pico, desde}
    serie, ops, custos, largadas, montou, repor = [], 0, 0.0, 0, False, False
    pico, queda = CAPITAL, 0.0

    def vale(a, o):
        return pos[a]["q"] * (D.cota(a, o) or 0.0)

    def liquido(a, o):
        v = vale(a, o)
        return v - D.com(a) * max(0.0, v - pos[a]["base"])

    def tirar(a, o, parte=1.0):
        nonlocal caixa, custos
        p, v = pos[a], vale(a, o)
        taxa = D.com(a) * max(0.0, v - p["base"]) * parte
        custos += taxa
        caixa += v * parte - taxa
        if parte >= 1.0:
            del pos[a]
        else:
            p["q"] *= 1 - parte
            p["base"] *= 1 - parte

    def por(a, o, v):
        nonlocal caixa
        c = D.cota(a, o)
        if v <= 0.01 or not c or c <= 0:
            return
        v = min(v, caixa)
        p = pos.setdefault(a, {"q": 0.0, "base": 0.0, "pico": 0.0, "desde": o})
        p["q"] += v / c
        p["base"] += v
        p["pico"] = max(p["pico"], p["q"] * c)
        caixa -= v

    for o in range(o1, o2 + 1):
        for a in list(pos):
            v = vale(a, o)
            pos[a]["pico"] = max(pos[a]["pico"], v)
            if D.acabou(a, o):          # o cofre fechou: sai pelo último valor
                tirar(a, o)
                repor = True
            elif stop and a != HLP and v <= pos[a]["pico"] * (1 - stop):
                tirar(a, o)
                ban[a] = o + BAN
                largadas += 1
                repor = True
        semana = (o - o1) % 7 == 0
        if semana or repor or not montou:
            passam = [a for a in escolher(D, genes, o) if ban.get(a, 0) <= o]
            antes = set(pos)
            if semana:
                ok = set(passam)
                for a in [a for a in pos if a != HLP and a not in ok and o - pos[a]["desde"] >= fica]:
                    tirar(a, o)
            membros = [a for a in pos if a != HLP]
            novos = [a for a in passam if a not in pos][:max(0, n - len(membros))]
            hlp_ok = bool(w) and HLP in D.c and D.cota(HLP, o) and not D.acabou(HLP, o)
            if semana or not montou:
                # as partes certas: o HLP com a parte dele (tudo, se a regra não achou cofre nenhum) e o resto igual
                alvo = membros + novos
                total = caixa + sum(liquido(a, o) for a in pos)
                parte_hlp = (w if alvo else 1.0) if hlp_ok else 0.0
                quer = {a: total * (1 - parte_hlp) / len(alvo) for a in alvo}
                if hlp_ok:
                    quer[HLP] = total * parte_hlp
                elif HLP in pos:
                    quer[HLP] = 0.0
                for a in list(pos):
                    v = liquido(a, o)
                    if v > quer.get(a, 0.0) + 0.01 and v > 0:
                        tirar(a, o, min(1.0, (v - quer.get(a, 0.0)) / v))
                for a in sorted(quer, key=lambda a: a not in novos):
                    falta = quer[a] - (liquido(a, o) if a in pos else 0.0)
                    por(a, o, falta)
            elif novos and caixa > 1:   # uma vaga abriu no meio da semana: o dinheiro parado vai para quem entra
                cada = caixa / len(novos)
                for a in novos:
                    por(a, o, cada)
            if pos:
                montou = True
            if set(pos) != antes:
                ops += 1
            repor = False
        total = caixa + sum(liquido(a, o) for a in pos)
        serie.append([dia_do(o), round(total, 2)])
        pico = max(pico, total)
        queda = max(queda, 1 - total / pico if pico > 0 else 0.0)
    ultimo = serie[-1][1] if serie else CAPITAL
    return {"serie": serie, "retorno": round(ultimo / CAPITAL - 1, 5), "piorQueda": round(queda, 4), "ops": ops,
            "custos": round(custos, 2), "largadas": largadas, "montou": montou,
            "membros": sorted((D.nome(a) for a in pos), key=lambda x: (x == "HLP", x.lower()))}


# ====================================================================== a rodada
def _linhas(ctx, cache):
    """A lista da corretora: a que a escolha da semana ou o teste fora da amostra já baixaram nesta rodada, ou uma nova."""
    import cofres as C
    linhas = (cache or {}).get("linhas")
    if not linhas:
        linhas = {}
        for x in ctx.cli.cofres():
            l = C.linha_lista(x)
            if l:
                linhas[l["endereco"]] = l
        if cache is not None and linhas:
            cache["linhas"] = linhas
    return linhas


def _met(ctx):
    cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}

    def f(c):
        return metricas(c, cdi, cdi_ano_da_serie(cdi, CDI_PADRAO))
    return f


def avancar(ctx, est, cof, cache=None):
    """O banco anda (uma vez por dia), o laboratório e a liga rodam. Devolve o bloco `evolucao` do cofres.json, ou
    None enquanto o banco não foi semeado (o teste fora da amostra ainda não acabou)."""
    b = est.get("bancoEv") or {}
    if b.get("cofres") and b.get("ate") != dia_de(ctx.agora):
        n = atualizar(est, _linhas(ctx, cache), cof, ctx.agora)
        ctx.log(f"  evolução (cofres): banco com {len(b['cofres'])} cofres; {n} andaram até hoje")
    D = Dados(est)
    if not D.tem_dados:
        return None
    ev = ES.rodar(est, Definicao(), D, ctx.agora, ES.parametros(bool(getattr(ctx, "exemplo", False))), ctx.log)
    return ES.resumo(ev, D, ctx.agora, "cofres", "Cofres", FRASE, AVISOS, _met(ctx), VERSAO)
