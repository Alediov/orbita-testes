"""Evolução do Funding, NO PAPEL (pedido do Alediov, 17/11/2026, item 4 do plano de melhorias: depois dos Robôs e do
copy trading, "os Cofres e o Funding").

A espécie é o **carry** (comprar a moeda no à vista e vender a mesma quantidade no perpétuo, como "BTC 1×", que é o
controle): toda versão começa com US$ 1.000 fictícios. Os genes (o que evolui):

- `moedas`: uma das 4 (BTC, ETH, HYPE, SOL) ou o rodízio entre elas;
- `alav`: 1×, 2× ou 3× (nunca mais: a regra do Alediov para o funding);
- `regra`: sempre dentro, ou só com a taxa alta (a seletiva);
- `media`: de quantos dias é a média do financiamento que a regra olha (1, 3, 7 ou 14);
- `entra` e `folga` (só na seletiva): entra quando a média passa de `entra` ao ano e sai quando cai `folga` abaixo disso;
- `troca` e `dif` (só no rodízio): troca de moeda no máximo a cada `troca` dias, e só se a outra pagar `dif` a mais;
- `caixa` (só na seletiva): o dinheiro parado vai para o empréstimo de dólar da Aave.

Não precisa de rede a mais: as contas saem do **banco de dias** (`est["bancoEv"]`): de cada moeda, por dia de
Brasília, a soma do financiamento das 24 horas, o fechamento e a máxima do perpétuo e o fechamento do à vista. O banco
é escrito a cada rodada com as velas e as taxas que o Funding já baixou (na 1ª vez, os 180 dias do teste no passado);
o juro da Aave é o `est["aave"]["serie"]` que a forma já guarda.

O simulador repete a conta do `funding.py` (a mesma `Posicao`: as duas pernas, as taxas e o deslize, a liquidação pela
máxima, o reequilíbrio da margem, os custos de ir e voltar da Aave), mas com UM PASSO POR DIA em vez de um por hora:
o financiamento do dia entra de uma vez pelo preço do fechamento, e a regra decide no fim do dia (no dia de hoje,
ainda incompleto, ela não decide). Por isso o controle é o "BTC 1×" REFEITO aqui: não bate centavo a centavo com a
conta do teste, que anda de hora em hora.

O laboratório e a liga são os do motor comum (`evolucao_series.py`). Estado em `est["evolucao"]` (o do Funding);
saída em `funding.json` → `evolucao` (FORMATO.md, "Evolução"). Teste: `teste_funding_evolucao.py`.
"""
from __future__ import annotations

import datetime as dt
import functools

import evolucao_series as ES
from conta import CAPITAL, DIA, HORA, cdi_ano_da_serie, dia_de, metricas
from genetica import reparar

VERSAO = 1
BANCO_V = 1
MOEDAS = ["BTC", "ETH", "HYPE", "SOL"]
MAX_DIAS = 260           # dias guardados por moeda
MEDIA_MAX = 14           # a média mais longa que um gene pode pedir: o laboratório começa depois desses dias
CDI_PADRAO = 0.149

FRASE = ("Versões do carry que evoluem: toda semana as piores regras saem, as melhores se cruzam e, às vezes, um gene "
         "muda. Só no papel.")
AVISOS = ["Só simulação, com saldo fictício: nenhuma ordem, nenhuma conta.",
          "Aqui as contas andam um passo por dia (o financiamento somado do dia, o preço do fechamento, a liquidação "
          "pela máxima do dia); as versões do teste andam de hora em hora.",
          "O controle é o BTC 1× refeito por este simulador: não bate centavo a centavo com a conta BTC 1× do teste.",
          "A alavancagem nunca passa de 3×."]

ESP = {
    "id": "carry", "nome": "Carry", "icone": "🧲", "prefixo": "f", "controle": "btc1",
    "frase": "Compra a moeda e vende a mesma quantidade no perpétuo para receber o financiamento: a moeda, a "
             "alavancagem, a hora de entrar e de sair, o rodízio e o caixa evoluem.",
    "genes": [
        {"k": "moedas", "nome": "Moeda", "tipo": "op", "opcoes": MOEDAS + ["todas"], "rotulos": {"todas": "Rodízio das 4"},
         "neutro": "BTC"},
        {"k": "alav", "nome": "Alavancagem", "tipo": "int", "min": 1, "max": 3, "passo": 1, "un": "×", "neutro": 1},
        {"k": "regra", "nome": "Regra", "tipo": "op", "opcoes": ["fixa", "seletiva"],
         "rotulos": {"fixa": "Sempre dentro", "seletiva": "Só com taxa alta"}, "neutro": "fixa"},
        {"k": "media", "nome": "Média de", "tipo": "op", "opcoes": [1, 3, 7, 14], "un": "d", "neutro": 3},
        {"k": "entra", "nome": "Entra acima de", "tipo": "op", "opcoes": [0.05, 0.1, 0.15, 0.2], "un": "%",
         "neutro": 0.1, "so": {"regra": "seletiva"}},
        {"k": "folga", "nome": "Sai com a queda de", "tipo": "op", "opcoes": [0.03, 0.05, 0.07, 0.1], "un": "%",
         "neutro": 0.07, "so": {"regra": "seletiva"}},
        {"k": "troca", "nome": "Troca a cada", "tipo": "op", "opcoes": [3, 7, 14], "un": "d", "neutro": 7,
         "so": {"moedas": "todas"}},
        {"k": "dif", "nome": "Troca se pagar a mais", "tipo": "op", "opcoes": [0.02, 0.05, 0.1, 0.2], "un": "%",
         "neutro": 0.05, "so": {"moedas": "todas"}},
        {"k": "caixa", "nome": "Caixa na Aave", "tipo": "bool", "neutro": False, "so": {"regra": "seletiva"}},
    ],
}


class Definicao:
    """A espécie como o motor comum espera."""
    versao, nome_controle, da_liga, rotulo, esp = VERSAO, "BTC 1×", "do carry", "funding", ESP

    def genes_controle(self):
        """"BTC 1×": metade no à vista, metade de margem do vendido, sempre dentro."""
        return reparar(ESP, {g["k"]: g["neutro"] for g in ESP["genes"]})

    def sementes(self):
        """As outras versões que o teste do Funding já roda."""
        b = self.genes_controle()
        return [(de, reparar(ESP, {**b, **m})) for de, m in (
            ("eth1", {"moedas": "ETH"}), ("hype1", {"moedas": "HYPE"}), ("sol1", {"moedas": "SOL"}),
            ("btc3", {"alav": 3}), ("seletiva", {"regra": "seletiva"}), ("seletiva3", {"regra": "seletiva", "alav": 3}),
            ("rodizio", {"moedas": "todas"}), ("seletivaC", {"regra": "seletiva", "caixa": True}))]

    def descrever(self, genes):
        out = [("Rodízio" if genes["moedas"] == "todas" else genes["moedas"]) + f" {genes['alav']}×"]
        if genes["regra"] == "seletiva":
            sai = genes["entra"] - genes["folga"]
            out.append(f"entra a {round(genes['entra'] * 100)}%, sai a {round(sai * 100)}%")
            if genes["caixa"]:
                out.append("caixa na Aave")
        else:
            out.append("sempre dentro")
        if genes["moedas"] == "todas" or genes["regra"] == "seletiva":
            out.append("média de 1 dia" if genes["media"] == 1 else f"média de {genes['media']} dias")
        return " · ".join(out)


# ====================================================================== dias
@functools.lru_cache(maxsize=4096)
def ordinal(dia):
    return dt.date.fromisoformat(dia).toordinal()


def dia_do(o):
    return dt.date.fromordinal(o).isoformat()


def _sig(v, n=7):
    return float(f"{v:.{n}g}")


# ====================================================================== o banco de dias
def atualizar_banco(est, d, agora):
    """Escreve no banco os dias que os dados desta rodada (`funding.Dados`: velas de 1 h e o financiamento de hora em
    hora) cobrem: o dia inteiro (24 taxas) sempre; o incompleto, só se é o de hoje ou se o banco não tinha o dia.
    Devolve quantos dias foram escritos."""
    b = est.get("bancoEv")
    if not b or b.get("v") != BANCO_V:
        b = est["bancoEv"] = {"v": BANCO_V, "moedas": {}, "ate": None, "parcial": None}
    hoje = dia_de(agora)
    escritos = 0
    for m in MOEDAS:
        fund = d.fund.get(m) or {}
        ts, vs = d.perp.get(m, ([], []))
        if not fund or not ts:
            continue
        por = {}   # dia → [soma, n, fechamento do perpétuo, máxima, fechamento do à vista]
        for t, r in fund.items():
            x = por.setdefault(dia_de(t - 1), [0.0, 0, None, None, None])   # a taxa paga à meia-noite é do dia que acabou
            x[0] += r
            x[1] += 1
        for t, (h, c) in zip(ts, vs):
            x = por.get(dia_de(t))
            if x:
                x[2], x[3] = c, max(x[3] or 0.0, h)
        sts, svs = d.spot.get(m, ([], []))
        for t, (_h, c) in zip(sts, svs):
            x = por.get(dia_de(t))
            if x:
                x[4] = c
        bm = b["moedas"].setdefault(m, {"d0": None, "f": [], "p": [], "h": [], "s": []})
        for dia in sorted(por):
            soma, n, p, h, s = por[dia]
            if p is None or dia > hoje:
                continue
            if bm["d0"] is None:
                bm["d0"] = dia
            k = ordinal(dia) - ordinal(bm["d0"])
            if k < 0:
                continue   # antes do 1º dia guardado: o banco só cresce para a frente
            tem = k < len(bm["f"])
            if n < 24 and dia != hoje and tem:
                continue
            while len(bm["f"]) < k:   # um buraco nos dados: o dia sem taxa, com o preço de antes
                bm["f"].append(0.0)
                for c in ("p", "h", "s"):
                    bm[c].append(bm[c][-1] if bm[c] else p)
            linha = {"f": round(soma, 8), "p": _sig(p), "h": _sig(max(h or p, p)), "s": _sig(s if s else p)}
            for c, v in linha.items():
                if tem:
                    bm[c][k] = v
                else:
                    bm[c].append(v)
            escritos += 1
        corte = len(bm["f"]) - MAX_DIAS
        if corte > 0:
            for c in ("f", "p", "h", "s"):
                bm[c] = bm[c][corte:]
            bm["d0"] = dia_do(ordinal(bm["d0"]) + corte)
    b["ate"] = hoje
    b["parcial"] = hoje   # o dia de hoje nunca está completo na hora da rodada
    b["lev"] = {m: int(d.alav_max.get(m) or 0) or None for m in MOEDAS}
    return escritos


def precisa_semear(est):
    """True enquanto o banco não tem história: a rodada baixa os 180 dias do teste no passado uma vez."""
    b = est.get("bancoEv") or {}
    return b.get("v") != BANCO_V or not any(len(x.get("f") or []) > MEDIA_MAX + 7 for x in (b.get("moedas") or {}).values())


class Dados:
    """O banco de dias para o simulador."""

    def __init__(self, est, F):
        b = est.get("bancoEv") or {}
        self.F = F
        self.m = {k: v for k, v in (b.get("moedas") or {}).items() if v.get("d0") and v.get("f")}
        self.o0 = {k: ordinal(v["d0"]) for k, v in self.m.items()}
        self.parcial = ordinal(b["parcial"]) if b.get("parcial") else None
        self.lev = {k: v for k, v in (b.get("lev") or {}).items() if v}
        self.juros = (est.get("aave") or {}).get("serie") or {}
        self._juro_ult = (est.get("aave") or {}).get("atual")
        primeiro = max(self.o0.values()) + MEDIA_MAX if self.m else None
        self.primeiro = dia_do(primeiro) if primeiro else None
        self._med = {}

    @property
    def tem_dados(self):
        return bool(self.m) and "BTC" in self.m

    def dia(self, m, o):
        """(financiamento do dia, perpétuo, máxima, à vista) da moeda no dia `o`, ou None."""
        x = self.m.get(m)
        if not x:
            return None
        k = o - self.o0[m]
        if k < 0 or k >= len(x["f"]):
            return None
        return x["f"][k], x["p"][k], x["h"][k], x["s"][k]

    def media(self, m, o, dias):
        """A média por HORA do financiamento nos `dias` até `o` (inclusive); None sem dados."""
        k = (m, o, dias)
        if k not in self._med:
            x = self.m.get(m)
            vs = []
            if x:
                i = o - self.o0[m]
                vs = x["f"][max(0, i - dias + 1):i + 1] if i >= 0 else []
            self._med[k] = sum(vs) / (24 * len(vs)) if vs else None
        return self._med[k]

    def juro(self, o):
        """O juro ao ano do depósito de USDC na Aave no dia (0 sem dados: o papel fica do lado conservador)."""
        v = self.juros.get(dia_do(o))
        if v is None:
            v = self._juro_ult
        try:
            return max(0.0, float(v or 0.0))
        except (TypeError, ValueError):
            return 0.0

    def mmr(self, m):
        return 1 / (2 * max(1, int(self.lev.get(m) or self.F.ALAV_MAX_PADRAO.get(m, 20))))

    # o que o motor comum pede
    def simular(self, genes, inicio, hoje):
        return simular(self, genes, inicio, hoje)

    @staticmethod
    def extras(c):
        return {"membros": c["membros"], "custos": c["custos"], "largadas": 0, "nLiq": c["nLiq"]}


def simular(D, genes, inicio, hoje):
    """A conta de uma versão de `inicio` a `hoje` (dias), um passo por dia: { serie: [[dia, US$]], retorno, piorQueda,
    ops (montagens, saídas e trocas), custos (taxas, deslize, ponte e gás), nLiq, membros (onde o dinheiro está),
    montou }."""
    F = D.F
    alav = min(int(genes["alav"]), F.ALAV_MAX)
    rodizio, seletiva = genes["moedas"] == "todas", genes["regra"] == "seletiva"
    moedas = [m for m in MOEDAS if m in D.m] if rodizio else [genes["moedas"]]
    media, entra, sai = genes["media"], genes["entra"], genes["entra"] - genes["folga"]
    usar_aave = bool(genes["caixa"]) and seletiva
    pos = F.Posicao(CAPITAL)
    moeda, dentro, na_aave, troca = (None if rodizio else moedas[0]), False, False, None
    serie, ops, custos, n_liq, montou = [], 0, 0.0, 0, False
    pico, queda, ultimo = CAPITAL, 0.0, {}

    def montar(m, x):
        nonlocal custos, na_aave
        _f, pp, _h, ps = x
        if na_aave:
            c = F.custo_caixa(pos.caixa, False)
            pos.caixa = max(0.0, pos.caixa - c)
            custos += c
            na_aave = False
        cs, cp = F.custos(m)
        custo, _pernas, _dq = pos.montar(ps, pp, alav, cs, cp)
        custos += custo

    def desmontar(m, x):
        nonlocal custos
        _f, pp, _h, ps = x
        cs, cp = F.custos(m)
        custo, _pernas = pos.desmontar(ps, pp, cs, cp)
        custos += custo

    for o in range(ordinal(inicio), ordinal(hoje) + 1):
        x = D.dia(moeda, o) if moeda else None
        if x:
            ultimo[moeda] = x
        if x and dentro and pos.qp > 0:
            if pos.liquidar_se(x[2], D.mmr(moeda)) is not None:
                n_liq += 1
            if pos.qp > 0:
                pos.financiar(x[0], x[1])
        if na_aave and pos.caixa > 0:
            pos.caixa *= (1 + D.juro(o)) ** (1 / 365)

        if o != D.parcial:   # o dia de hoje ainda não acabou: a regra não decide por ele
            medias = {m: D.media(m, o, media) for m in moedas}
            medias = {m: v for m, v in medias.items() if v is not None and D.dia(m, o)}
            melhor = max(medias, key=lambda m: (medias[m], m)) if medias else None
            if not dentro:
                alvo = melhor if rodizio else (moeda if moeda in medias else None)
                if alvo and (not seletiva or F.ao_ano(medias[alvo]) > entra):
                    moeda, x = alvo, D.dia(alvo, o)
                    ultimo[moeda] = x
                    montar(moeda, x)
                    dentro, troca, montou = True, o, True
                    ops += 1
            elif x:
                atual = medias.get(moeda)
                if seletiva and atual is not None and F.ao_ano(atual) < sai and (
                        not rodizio or melhor is None or F.ao_ano(medias[melhor]) < sai):
                    desmontar(moeda, x)
                    dentro = False
                    ops += 1
                elif (rodizio and melhor and melhor != moeda and o - (troca or o) >= genes["troca"]
                      and (atual is None or F.ao_ano(medias[melhor] - atual) >= genes["dif"])):
                    desmontar(moeda, x)
                    moeda, x = melhor, D.dia(melhor, o)
                    ultimo[moeda] = x
                    montar(moeda, x)
                    troca = o
                    ops += 1
        if dentro and x and pos.qs + pos.qp > 0 and pos.fora_do_ponto(x[1], alav):
            cs, cp = F.custos(moeda)
            custo, _pernas, _dq = pos.montar(x[3], x[1], alav, cs, cp)   # reequilibra (ou remonta depois da liquidação)
            custos += custo
        if usar_aave and not dentro and not na_aave and pos.caixa > 1:
            c = F.custo_caixa(pos.caixa, True)
            pos.caixa = max(0.0, pos.caixa - c)
            custos += c
            na_aave = True
        u = ultimo.get(moeda) if moeda else None
        total = pos.valor(u[3], u[1]) if (u and dentro) else pos.caixa
        serie.append([dia_do(o), round(total, 2)])
        pico = max(pico, total)
        queda = max(queda, 1 - total / pico if pico > 0 else 0.0)
    fim = serie[-1][1] if serie else CAPITAL
    onde = [f"{moeda} {alav}×"] if dentro else (["Aave (dólar)"] if na_aave else [])
    return {"serie": serie, "retorno": round(fim / CAPITAL - 1, 5), "piorQueda": round(queda, 4), "ops": ops,
            "custos": round(custos, 2), "nLiq": n_liq, "montou": montou, "membros": onde}


# ====================================================================== a rodada
def _met(ctx):
    cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}

    def f(c):
        return metricas(c, cdi, cdi_ano_da_serie(cdi, CDI_PADRAO))
    return f


def avancar(ctx, est, d, agora, F):
    """O banco de dias anda com os dados desta rodada, o laboratório e a liga rodam. Devolve o bloco `evolucao` do
    funding.json (None sem dados)."""
    n = atualizar_banco(est, d, agora)
    D = Dados(est, F)
    if not D.tem_dados:
        return None
    dias = len(D.m["BTC"]["f"])
    if n > 10 * len(MOEDAS):   # só quando semeia (ou depois de dias sem rodar)
        ctx.log(f"  evolução (funding): banco com {dias} dias de BTC ({n} dias escritos nesta rodada)")
    ev = ES.rodar(est, Definicao(), D, agora, ES.parametros(bool(getattr(ctx, "exemplo", False))), ctx.log)
    return ES.resumo(ev, D, agora, "funding", "Funding", FRASE, AVISOS, _met(ctx), VERSAO, alavMax=F.ALAV_MAX)


__all__ = ["avancar", "atualizar_banco", "precisa_semear", "simular", "Dados", "Definicao", "ESP", "HORA", "DIA"]
