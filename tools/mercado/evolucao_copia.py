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

Duas frentes, como nos Robôs (as mesmas regras e números; a genética é a mesma, `tools/papel/genetica.py`, e o
motor do laboratório e da liga é o comum das formas refeitas por séries, `tools/papel/evolucao_series.py`):

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

import evolucao_series as ES
from evolucao_series import (COM_SERIE, JANELAS, Evolucao, dias_entre, mais_dias, nota_janela, nota_lab,  # noqa: F401
                             nota_semana, segunda_de, semana_de, semana_do_dia)
from genetica import ativo, chave, reparar  # noqa: F401
from sim import dia_de  # noqa: F401

VERSAO = 1
CAPITAL = 1000.0
CUSTO_LADO = 0.0015
DIA = 86_400_000
FRASE = ("Carteiras de carteiras que evoluem: toda semana as piores regras saem, as melhores se cruzam e, às vezes, "
         "um gene muda. Só no papel.")
AVISOS = ["Só simulação, com saldo fictício: nenhuma ordem, nenhuma conta.",
          "As contas são refeitas pelas séries diárias das cópias; cada troca de carteira paga 0,15% de cada lado "
          "(aproximação).",
          "O selo de robô ou pessoa é o de hoje, não o de cada semana.",
          "O laboratório só começa com 4 semanas de cópias guardadas: com poucos dias, a nota seria sorte."]


def parametros(exemplo=False):
    return ES.parametros(exemplo)


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

    # o que o motor comum pede
    @property
    def tem_dados(self):
        return bool(self.carteiras)

    def simular(self, genes, inicio, hoje):
        return simular(self, genes, inicio, hoje)

    @staticmethod
    def extras(c):
        return {"membros": c["membros"], "custos": c["custos"], "largadas": c["largadas"]}


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


# ====================================================================== a espécie no motor comum
class Definicao:
    """A espécie como o motor (`evolucao_series.py`) espera."""
    versao, nome_controle, da_liga, rotulo = VERSAO, "As 5 melhores", "das carteiras de carteiras", "copy"

    def __init__(self, esp):
        self.esp = esp

    def genes_controle(self):
        return genes_controle(self.esp)

    def sementes(self):
        return sementes(self.esp)

    def descrever(self, genes):
        return descrever(self.esp, genes)


def rodar(est, agora, jeitos, padrao, nome_jeito=None, exemplo=False, log=print):
    """Uma rodada: o banco, o laboratório (uma vez por dia) e a liga (a virada na segunda). Devolve a `Evolucao`."""
    atualizar_banco(est)
    D = Dados(est, padrao)
    ev = ES.rodar(est, Definicao(especie(jeitos, padrao, nome_jeito)), D, agora, parametros(exemplo), log)
    return ev, D


def resumo(ev, D, agora, metricas_de=None):
    """O bloco `evolucao` do resumo.json (o formato do evolucao.json dos Robôs: uma forma, "copy", com a espécie)."""
    return ES.resumo(ev, D, agora, "copy", "Copy trading", FRASE, AVISOS, metricas_de, VERSAO, custoLado=CUSTO_LADO)


__all__ = ["rodar", "resumo", "especie", "simular", "escolher", "Dados", "Evolucao", "ativo"]
