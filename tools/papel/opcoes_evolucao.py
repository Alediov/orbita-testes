"""Evolução das Opções, NO PAPEL (pedido do Alediov, 15/11/2026; item 4 do plano de melhorias, "Previsões e Opções por
último"; feito em 19/11/2026, junto do resto das Finanças e dos Testes antes do APK).

A espécie é a **venda de prêmio** (vender o seguro contra a queda ou a alta e ficar com o prêmio, como "Put 0,15", que
é o controle e a versão padrão da forma): toda versão começa com US$ 1.000 fictícios. Os genes (o que evolui):

- `moeda`: BTC ou ETH;
- `tipo`: put (garantia em dólar), call coberta (a moeda comprada), strangle coberto (metade de cada) ou a roda (puts
  até ser exercida, calls até ser chamada);
- `delta`: a distância do preço (0,10 a 0,40: quanto menor, mais longe, menor o prêmio e mais raro o prejuízo);
- `prazo`: a opção da semana ou a do fim do mês seguinte;
- `stop` (só nas que vendem toda semana): recompra quando a opção passa a valer 2, 3 ou 4 vezes o prêmio (0 = nunca);
- `caro`: só vende na semana em que a implícita ÷ a realizada de 30 dias passa de 1,1, 1,2 ou 1,35 (0 = sempre);
- `caixa`: a garantia em dólar rendendo no empréstimo de USDC da Aave enquanto espera.

Não precisa de rede a mais além de um pedaço por rodada: as contas saem do **banco de horas** (`est["bancoEv"]`): de
cada moeda, o fechamento de cada hora (as velas de 1 h da Hyperliquid que a rodada já baixa) e o DVOL da Deribit de
cada hora (a volatilidade implícita de 30 dias), até 200 dias. Semeado uma vez pelos 180 dias do teste no passado e
andado a cada rodada (as velas dos últimos 31 dias que a forma já baixa e o DVOL desde a última hora guardada).

O simulador é a própria `Conta` do `opcoes.py` com o `MercadoHist` (o mesmo do teste no passado: Black-Scholes com o
DVOL e o sorriso medido na cadeia, a oferta de compra estimada, as taxas da Deribit, a entrega pelo fechamento das
07h–08h UTC, a Aave), mas com UM PASSO A CADA 4 HORAS (o vencimento das 08h UTC cai num passo). Por isso o controle é o
"Put 0,15" REFEITO aqui: aproximado e sem bater centavo a centavo com a conta do teste no passado, que anda de hora em
hora.

O laboratório e a liga são os do motor comum (`evolucao_series.py`). Estado em `est["evolucao"]` (o da forma);
saída em `opcoes.json` → `evolucao` (FORMATO.md, "Evolução"). Teste: `teste_opcoes_evolucao.py`.
"""
from __future__ import annotations

import datetime as dt
import functools

import evolucao_series as ES
from conta import CAPITAL, DIA, HORA, cdi_ano_da_serie, dia_de, metricas
from genetica import reparar

VERSAO = 1
BANCO_V = 1
MOEDAS = ["BTC", "ETH"]
MAX_HORAS = 200 * 24     # horas guardadas por moeda
PASSO = 4 * HORA         # um passo a cada 4 h (alinhado ao UTC: 00, 04, 08…)
FOLGA_INICIO = 31        # dias do banco antes do 1º dia do laboratório (a realizada de 30 dias)
MIN_HORAS = 45 * 24      # menos que isso de banco: sem a espécie ainda
CDI_PADRAO = 0.149

FRASE = ("Versões da venda de opções que evoluem: toda semana as piores regras saem, as melhores se cruzam e, às vezes, "
         "um gene muda. Só no papel.")
AVISOS = ["Só simulação, com saldo fictício: nenhuma ordem, nenhuma conta.",
          "Os preços das opções saem da fórmula de Black-Scholes com o índice de volatilidade da Deribit (DVOL) e o "
          "sorriso medido na cadeia, não da cadeia da época: aproximado.",
          "Aqui as contas andam um passo a cada 4 horas; o controle é a Put 0,15 refeita por este simulador.",
          "A put guarda o dólar inteiro para comprar no strike; a call fica coberta pela moeda comprada."]

ESP = {
    "id": "premio", "nome": "Venda de prêmio", "icone": "🛡️", "prefixo": "o", "controle": "put15",
    "frase": "Vende o seguro contra a queda (put) ou contra a alta (call) e fica com o prêmio: a moeda, o tipo, a "
             "distância do preço, o prazo, a recompra, o filtro do prêmio caro e a Aave evoluem.",
    "genes": [
        {"k": "moeda", "nome": "Moeda", "tipo": "op", "opcoes": MOEDAS, "neutro": "BTC"},
        {"k": "tipo", "nome": "Vende", "tipo": "op", "opcoes": ["put", "call", "strangle", "roda"],
         "rotulos": {"put": "Put", "call": "Call coberta", "strangle": "Strangle coberto", "roda": "A roda"}, "neutro": "put"},
        {"k": "delta", "nome": "Delta", "tipo": "op", "opcoes": [0.1, 0.15, 0.2, 0.25, 0.3, 0.4], "neutro": 0.15},
        {"k": "prazo", "nome": "Prazo", "tipo": "op", "opcoes": ["semana", "mes"],
         "rotulos": {"semana": "Da semana", "mes": "Do mês"}, "neutro": "semana"},
        {"k": "stop", "nome": "Recompra com", "tipo": "op", "opcoes": [0, 2, 3, 4], "un": "×", "neutro": 0,
         "rotulos": {"0": "Nunca"}, "so": {"prazo": "semana"}},
        {"k": "caro", "nome": "Só vende caro acima de", "tipo": "op", "opcoes": [0, 1.1, 1.2, 1.35], "un": "×", "neutro": 0,
         "rotulos": {"0": "Sempre vende"}},
        {"k": "caixa", "nome": "Garantia na Aave", "tipo": "bool", "neutro": False},
    ],
}


class Definicao:
    """A espécie como o motor comum espera."""
    versao, nome_controle, da_liga, rotulo, esp = VERSAO, "Put 0,15", "da venda de prêmio", "opções", ESP

    def genes_controle(self):
        """"Put 0,15": toda sexta a put de bitcoin de delta 0,15 da semana seguinte, com o dólar guardado."""
        return reparar(ESP, {g["k"]: g["neutro"] for g in ESP["genes"]})

    def sementes(self):
        """As outras versões que o teste das Opções já roda."""
        b = self.genes_controle()
        return [(de, reparar(ESP, {**b, **m})) for de, m in (
            ("put30", {"delta": 0.3}), ("call15", {"tipo": "call"}), ("strangle", {"tipo": "strangle"}),
            ("putmes", {"delta": 0.2, "prazo": "mes"}), ("putstop", {"stop": 3}), ("eth_put15", {"moeda": "ETH"}),
            ("put30C", {"delta": 0.3, "caixa": True}), ("put30vrp", {"delta": 0.3, "caro": 1.2, "caixa": True}),
            ("roda", {"tipo": "roda", "delta": 0.3}))]

    def descrever(self, genes):
        nome = {"put": "Put", "call": "Call coberta", "strangle": "Strangle", "roda": "A roda"}[genes["tipo"]]
        out = [f"{genes['moeda']} · {nome} {str(genes['delta']).replace('.', ',')}",
               "do mês" if genes["prazo"] == "mes" else "da semana"]
        if genes["prazo"] == "semana" and genes["stop"]:
            out.append(f"recompra a {genes['stop']}×")
        if genes["caro"]:
            out.append(f"só caro (≥ {str(genes['caro']).replace('.', ',')}×)")
        if genes["caixa"]:
            out.append("Aave")
        return " · ".join(out)


# ====================================================================== horas
def _hora(t):
    return (int(t) // HORA) * HORA


@functools.lru_cache(maxsize=4096)
def _ms_do_dia(dia):
    """O começo (ms UTC) de um dia de Brasília (UTC−3)."""
    d = dt.datetime.fromisoformat(dia) + dt.timedelta(hours=3)
    return int(d.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


# ====================================================================== o banco de horas
def atualizar_banco(est, precos, dvol, agora):
    """Põe no banco as horas de `precos` ({moeda: {hora ms: fechamento}}) e `dvol` ({moeda: {hora ms: fração}}). As horas
    novas entram no fim; as que o banco já tem são trocadas (a vela da hora em curso muda). Devolve quantas entraram."""
    b = est.get("bancoEv")
    if not b or b.get("v") != BANCO_V:
        b = est["bancoEv"] = {"v": BANCO_V, "moedas": {}}
    novas = 0
    for m in MOEDAS:
        pm, dm = (precos or {}).get(m) or {}, (dvol or {}).get(m) or {}
        bm = b["moedas"].setdefault(m, {"h0": None, "p": [], "v": []})
        horas = sorted(h for h in set(pm) | set(dm) if h <= agora)
        if not horas:
            continue
        if bm["h0"] is None or (not bm["p"]):
            bm["h0"], bm["p"], bm["v"] = _hora(horas[0]), [], []
        for h in horas:
            k = (_hora(h) - bm["h0"]) // HORA
            if k < 0:
                continue   # antes da 1ª hora guardada: o banco só cresce para a frente (a semente vem inteira de uma vez)
            while len(bm["p"]) < k:   # um buraco: a hora com o preço e o DVOL de antes
                bm["p"].append(bm["p"][-1] if bm["p"] else None)
                bm["v"].append(bm["v"][-1] if bm["v"] else 0.0)
            p, v = pm.get(h), dm.get(h)
            if k < len(bm["p"]):
                if p:
                    bm["p"][k] = float(f"{p:.7g}")
                if v:
                    bm["v"][k] = round(v, 4)
            else:
                bm["p"].append(float(f"{p:.7g}") if p else (bm["p"][-1] if bm["p"] else None))
                bm["v"].append(round(v, 4) if v else (bm["v"][-1] if bm["v"] else 0.0))
                novas += 1
        corte = len(bm["p"]) - MAX_HORAS
        if corte > 0:
            bm["p"], bm["v"] = bm["p"][corte:], bm["v"][corte:]
            bm["h0"] += corte * HORA
    return novas


def ultima_hora(est, m):
    bm = ((est.get("bancoEv") or {}).get("moedas") or {}).get(m) or {}
    return bm["h0"] + (len(bm["p"]) - 1) * HORA if bm.get("h0") is not None and bm.get("p") else None


def precisa_semear(est):
    """True enquanto o banco do bitcoin tem menos de MIN_HORAS: a rodada baixa os 180 dias do teste no passado."""
    b = est.get("bancoEv") or {}
    bm = (b.get("moedas") or {}).get("BTC") or {}
    return b.get("v") != BANCO_V or len(bm.get("p") or []) < MIN_HORAS


class Dados:
    """O banco de horas como o `MercadoHist` das Opções, para a `Conta` andar por ele."""

    def __init__(self, est, O, sorriso=None, aave=None):
        self.O = O
        b = (est.get("bancoEv") or {}).get("moedas") or {}
        precos, dvol, self.h0 = {}, {}, {}
        for m, bm in b.items():
            if bm.get("h0") is None or not bm.get("p"):
                continue
            self.h0[m] = bm["h0"]
            precos[m] = {bm["h0"] + i * HORA: p for i, p in enumerate(bm["p"]) if p}
            dvol[m] = {bm["h0"] + i * HORA: v for i, v in enumerate(bm["v"]) if v}
        self.n = {m: len(b[m]["p"]) for m in self.h0}
        self.mk = O.MercadoHist(precos, dvol, sorriso=sorriso or {}, aave=aave)
        btc = self.h0.get("BTC")
        self.primeiro = dia_de(btc + FOLGA_INICIO * DIA) if btc is not None and self.n["BTC"] >= MIN_HORAS else None

    @property
    def tem_dados(self):
        return self.primeiro is not None

    def simular(self, genes, inicio, hoje):
        return simular(self, genes, inicio, hoje)

    @staticmethod
    def extras(c):
        return {"membros": c["membros"], "custos": c["custos"], "largadas": c["recompras"], "exercidas": c["exercidas"]}


def _conta(O, genes):
    """A `Conta` das Opções com os genes no lugar da linha de `VERSOES` e das `OPCOES`."""
    stop = genes["stop"] if genes["prazo"] == "semana" and genes["stop"] else None
    cfg = ("evolucao", "Evolução", genes["moeda"], genes["tipo"], float(genes["delta"]), genes["prazo"], stop, "médio", "")
    c = O.Conta(cfg)
    c.opc = {"caixa": bool(genes["caixa"]), "vrp": bool(genes["caro"])}
    c.caixa_aave, c.vrp = bool(genes["caixa"]), bool(genes["caro"])
    c.vrp_min = float(genes["caro"] or 0) or O.VRP_MIN
    return c


def simular(D, genes, inicio, hoje):
    """A conta de uma versão de `inicio` a `hoje` (dias de Brasília), um passo a cada 4 h e um ponto por dia: { serie:
    [[dia, US$]], retorno, piorQueda, ops (vendas e recompras), custos (taxas da Deribit e do à vista), recompras,
    exercidas, membros (as opções abertas no fim), montou }."""
    O, mk = D.O, D.mk
    c = _conta(O, genes)
    t0 = _ms_do_dia(inicio)
    t_fim = min(_ms_do_dia(hoje) + DIA - 1, D.h0[genes["moeda"]] + (D.n[genes["moeda"]] - 1) * HORA) \
        if genes["moeda"] in D.h0 else t0 - 1
    c.criado = t0
    t = ((t0 + PASSO - 1) // PASSO) * PASSO
    serie, dia_atual, v_ult = [], None, float(CAPITAL)
    pico, queda = float(CAPITAL), 0.0
    while t <= t_fim:
        if mk.preco(c.moeda, t):
            c._juros(mk, t)
            if c.regua:   # (não acontece na espécie: as réguas não evoluem)
                c._passo_regua(mk, t, None)
            else:
                c._vencer(mk, t, None)
                c._recomprar(mk, t, None)
                if c._pode_vender(t):
                    c._vender(mk, t, None)
            c.ultimo_s = mk.preco(c.moeda, t)
            for op in c.pos:
                mc = mk.marca(op, t)
                if mc:
                    op["ult"] = mc[0]
            v_ult = c.valor(mk, t)
        d = dia_de(t)
        if d != dia_atual:
            dia_atual = d
            serie.append([d, round(v_ult, 2)])
        else:
            serie[-1][1] = round(v_ult, 2)
        pico = max(pico, v_ult)
        queda = max(queda, 1 - v_ult / pico if pico > 0 else 0.0)
        t += PASSO
    a = c.acc
    fim_v = serie[-1][1] if serie else CAPITAL
    membros = [c._rotulo(op) for op in c.pos]
    if not membros and c.q > 1e-9:
        membros = [f"{c.moeda} comprado"]
    return {"serie": serie, "retorno": round(fim_v / CAPITAL - 1, 5), "piorQueda": round(queda, 4),
            "ops": int(a["vendas"] + a["recompras"]), "custos": round(a["txOp"] + a["txEnt"] + a["txSpot"], 2),
            "recompras": int(a["recompras"]), "exercidas": int(a["exercidas"]), "montou": a["vendas"] > 0,
            "membros": membros}


# ====================================================================== a rodada
def _met(ctx):
    cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}

    def f(c):
        return metricas(c, cdi, cdi_ano_da_serie(cdi, CDI_PADRAO))
    return f


def avancar(ctx, est, O, precos, dvol, agora, sorriso=None, aave=None):
    """O banco de horas anda com o que a rodada baixou (`precos`, `dvol`), o laboratório e a liga rodam. Devolve o bloco
    `evolucao` do opcoes.json (None sem banco suficiente)."""
    n = atualizar_banco(est, precos, dvol, agora)
    if n > 24 * 10:
        ctx.log(f"  evolução (opções): banco com {len(((est.get('bancoEv') or {}).get('moedas') or {}).get('BTC', {}).get('p') or [])} "
                f"horas de BTC ({n} horas novas nesta rodada)")
    D = Dados(est, O, sorriso=sorriso, aave=aave)
    if not D.tem_dados:
        return None
    ev = ES.rodar(est, Definicao(), D, agora, ES.parametros(bool(getattr(ctx, "exemplo", False))), ctx.log)
    return ES.resumo(ev, D, agora, "opcoes", "Opções", FRASE, AVISOS, _met(ctx), VERSAO,
                     passoHoras=PASSO // HORA)


__all__ = ["avancar", "atualizar_banco", "precisa_semear", "ultima_hora", "simular", "Dados", "Definicao", "ESP"]
