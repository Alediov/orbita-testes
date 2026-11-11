"""Copiar AO CONTRÁRIO (pedido do Alediov, 11/11/2026; só no papel, saldo fictício).

A pergunta dele: "se um teste é muito ruim, mas consistente, não daria para apostar contra ele?". A conta mostra o
limite: o resultado de qualquer estratégia = o que ela ganha ANTES dos custos − os custos; o contrário ganha
−(antes dos custos) − os MESMOS custos (taxa, diferença de preço e financiamento são pagos dos dois lados). Então o
contrário só dá lucro quando a carteira perde mais do que os custos já antes de pagá-los. Este teste mede isso de
verdade, daqui para frente (fora da amostra: escolhe pelo passado e mede no que vem depois).

Escolha (uma vez por semana, ou de novo no dia seguinte se houver menos de `MINIMO`): o ranking público da Hyperliquid,
as carteiras que PERDEM de forma consistente (conta ≥ US$ 10 mil; prejuízo na semana, nos 30 dias e no total; perdeu
10% ou mais da conta nos 30 dias; giro entre 1× e 300× a conta) e que dá para copiar (os mesmos filtros finos da cópia:
operações por dia, tempo de posição, perpétuos, não ser cofre). Até `ALVO` carteiras, as que mais perderam primeiro
(pesadas pelo tamanho da conta). Uma carteira sai quando volta a ganhar nos 30 dias ou some do ranking.

Contas por carteira (US$ 1.000 cada, 1 min de atraso, a mesma conta da cópia: sim.Conta, com taxa, deslize,
financiamento e liquidação):
- `n1`: a cópia normal 1× (para saber o quanto ela perde, e quanto disso é custo);
- `i1` e `i3`: a cópia AO CONTRÁRIO com 1× e 3× (cada compra dela vira venda e vice-versa, na mesma fração do patrimônio).

Para cada conta: o resultado, os custos (taxas, deslize e financiamento) e o "antes dos custos". E as carteiras de
carteiras de cada tipo (partes iguais entre as que estão no teste, refeitas toda semana, como em agregadas.py).
"""
from __future__ import annotations

import math
import time

import agregadas as AG
import carteiras as K
import hl
from sim import Conta, Patrimonio, dia_de, operacoes_da_carteira, simular

MIN = 60_000
DIA = 86_400_000
CAPITAL = 1000.0
ALVO = 10
MINIMO = 5
ANALISAR = 25          # análises finas por escolha
JANELA = 30            # dias de execuções para os filtros finos
PERDA_MES_MIN = 0.10   # perdeu 10% ou mais da conta nos 30 dias
CONTAS = {"n1": (1, False), "i1": (1, True), "i3": (3, True)}
NOMES = {"n1": "Copiando normal 1×", "i1": "Ao contrário 1×", "i3": "Ao contrário 3×"}
PADRAO = "i1"
REGRA = ("Toda semana, as carteiras do ranking da Hyperliquid que perdem de forma consistente (prejuízo na semana, "
         "nos 30 dias e no total; 10% ou mais da conta nos 30 dias; conta de US$ 10 mil ou mais) e que dá para copiar. "
         "Cada compra delas vira venda na cópia (e vice-versa), na mesma fração do patrimônio, 1 min depois.")


def curto(e):
    return f"{e[:6]}…{e[-4:]}"


def estado(est):
    return est.setdefault("contrario", {"carteiras": {}, "ultimaEscolha": None, "tentou": None, "encerradas": [],
                                        "banco": {k: {} for k in CONTAS}, "funil": None, "inicio": None})


# ---------------------------------------------------------------------------------------------- escolha
def pre_filtro(l, c=K.CRITERIOS):
    """O motivo da recusa (ou None) só pelo ranking."""
    nome = (l.get("nome") or "").lower()
    giro = K.giro(l)
    if not l["endereco"].startswith("0x") or len(l["endereco"]) != 42:
        return "endereço estranho"
    if "vault" in nome or "hlp" in nome:
        return "cofre (pelo nome)"
    if l["conta"] < c["conta_min"]:
        return "conta pequena"
    if l["mes"]["pnl"] >= 0:
        return "não perdeu em 30 dias"
    if l["semana"]["pnl"] >= 0:
        return "não perdeu na semana"
    if l["total"]["pnl"] >= 0:
        return "não perdeu no total"
    if -K.ganho(l) < PERDA_MES_MIN:
        return "perdeu pouco no mês"
    if giro < c["giro_mes_min"]:
        return "quase parada no mês"
    if giro > c["giro_mes_max"]:
        return "giro de formador de mercado"
    return None


def nota(l):
    """Quem mais perdeu (até 100% da conta), pesado pelo tamanho da conta, mais um pouco da semana."""
    return min(1.0, -K.ganho(l)) * (math.log10(max(l["conta"], 10)) - 3) + 0.3 * min(0.3, max(0.0, -K.ganho(l, "semana")))


def precisa_escolher(est, agora):
    ct = estado(est)
    if not ct["ultimaEscolha"] or agora - ct["ultimaEscolha"] >= 7 * DIA:
        return not ct["tentou"] or agora - ct["tentou"] >= 6 * 3_600_000
    return len(ct["carteiras"]) < MINIMO and agora - (ct["tentou"] or 0) >= DIA


def escolher(cli, est, agora, inicio_vivo, log, prazo, eq_do_portfolio, linhas=None):
    ct = estado(est)
    ct["tentou"] = agora
    linhas = linhas if linhas is not None else [K.linha_ranking(r) for r in cli.ranking()]
    por_end = {l["endereco"]: l for l in linhas}
    funil = {"ranking": len(linhas), "recusas": {}, "analisadas": 0, "aprovadas": 0}
    candidatas = []
    for l in linhas:
        m = pre_filtro(l)
        if m:
            funil["recusas"][m] = funil["recusas"].get(m, 0) + 1
        else:
            candidatas.append(l)
    funil["preFiltro"] = len(candidatas)
    # as que já estão: saem se voltaram a ganhar nos 30 dias ou sumiram do ranking
    ficam = {}
    for e, c in ct["carteiras"].items():
        l = por_end.get(e)
        motivo = "saiu do ranking" if not l else ("voltou a ganhar nos 30 dias" if l["mes"]["pnl"] >= 0 else None)
        if motivo:
            r = ((c.get("resumo") or {}).get(PADRAO) or {})
            ct["encerradas"] = (ct["encerradas"] + [{"endereco": e, "desde": c["desde"], "ate": agora, "motivo": motivo,
                                                     "retorno": r.get("retorno")}])[-30:]
            log(f"  ao contrário: sai {curto(e)}: {motivo}")
            continue
        c["ranking"] = l
        ficam[e] = c
    vagas = ALVO - len(ficam)
    for l in sorted(candidatas, key=nota, reverse=True):
        if vagas <= 0 or funil["analisadas"] >= ANALISAR:
            break
        if time.monotonic() > prazo:
            log("  ao contrário: tempo esgotado na escolha")
            break
        e = l["endereco"]
        if e in ficam or e in est.get("carteiras", {}):
            continue  # já é copiada normalmente: não entra dos dois lados
        try:
            fills = cli.execucoes_entre(e, agora - JANELA * DIA, agora, maximo=2000)
            md = K.medidas(fills, agora)
            motivo = K.filtro_fino(md, "user")
            papel = None
            if not motivo:
                papel = cli.papel(e)
                motivo = K.filtro_fino(md, papel)
            funil["analisadas"] += 1
            if motivo:
                funil["recusas"][motivo] = funil["recusas"].get(motivo, 0) + 1
                continue
            eq = eq_do_portfolio(cli.portfolio(e))
        except hl.Erro as er:
            log(f"  ao contrário: {curto(e)}: {er}")
            continue
        funil["aprovadas"] += 1
        ficam[e] = {"endereco": e, "desde": inicio_vivo, "cursor": inicio_vivo, "ranking": l, "medidas": md,
                    "eq": eq[-80:], "contas": {k: Conta(a, MIN, CAPITAL, inicio_vivo).para_json() for k, (a, _) in CONTAS.items()},
                    "resumo": None}
        vagas -= 1
        log(f"  ao contrário: entra {curto(e)} (perdeu {K.pct(-K.ganho(l))} da conta em 30 dias)")
    ct["carteiras"] = ficam
    funil["seguidas"] = len(ficam)
    funil["em"] = agora
    ct["funil"] = funil
    if len(ficam) >= MINIMO or not candidatas:
        ct["ultimaEscolha"] = agora
    if ct["inicio"] is None and ficam:
        ct["inicio"] = inicio_vivo


# ---------------------------------------------------------------------------------------------- ao vivo
def inverter(ops):
    """Cada operação com o lado trocado (a mesma fração do patrimônio, do outro lado)."""
    return [{**o, "pos": -o["pos"], "antes": -o.get("antes", 0.0)} for o in ops]


def coletar(cli, est, fim_ops, agora, log, prazo, valor_conta):
    """As operações novas de cada carteira do teste e as moedas que precisam de preço: (novas, precisa)."""
    ct = estado(est)
    novas, precisa = {}, {}
    for e, c in ct["carteiras"].items():
        if time.monotonic() > prazo:
            log("  ao contrário: tempo esgotado nas execuções")
            break
        if c["cursor"] >= fim_ops:
            continue
        try:
            fills = cli.execucoes_entre(e, c["cursor"] + 1, fim_ops)
        except hl.Erro as er:
            log(f"  ao contrário: {curto(e)}: {er}")
            continue
        ops = operacoes_da_carteira(fills)
        if ops:
            try:
                v = valor_conta(cli.estado(e))
                if v:
                    c["eq"] = (c.get("eq") or [])[-80:] + [[agora, v]]
            except hl.Erro as er:
                log(f"  ao contrário: {curto(e)}: patrimônio: {er}")
        novas[e] = ops
        for op in ops:
            precisa.setdefault(op["moeda"], set()).add(op["t"])
        for x in c["contas"].values():
            for m in x.get("pos") or {}:
                precisa.setdefault(m, set()).add(x["t"])
    return novas, precisa


def simular_rodada(est, novas, merc, ate, agora, fim_ops):
    """As contas de cada carteira lida andam até `ate` (o cursor vai a `fim_ops`, como na cópia)."""
    ct = estado(est)
    n = 0
    for e, ops in novas.items():
        c = ct["carteiras"].get(e)
        if not c:
            continue
        pat = Patrimonio(c.get("eq") or [])
        contas = {k: Conta.de_json(x) for k, x in c["contas"].items()}
        for k, conta in contas.items():
            simular(inverter(ops) if CONTAS[k][1] else ops, pat, merc, [conta], ate)
        c["contas"] = {k: x.para_json() for k, x in contas.items()}
        c["cursor"] = fim_ops
        c["resumo"] = {k: x.resumo(merc, ate) for k, x in contas.items()}
        n += len(ops)
    atualizar_banco(ct, agora)
    return n


def atualizar_banco(ct, agora):
    """A série de cada tipo de conta de toda carteira que já passou pelo teste (para as carteiras de carteiras)."""
    for k in CONTAS:
        banco = ct["banco"].setdefault(k, {})
        for e, c in ct["carteiras"].items():
            b = banco.setdefault(e, {"desde": c["desde"], "serie": {}, "selo": None, "ate": None})
            for d, v in ((c.get("resumo") or {}).get(k) or {}).get("serie") or []:
                b["serie"][d] = v
            b["ate"] = None
        for e, b in banco.items():
            if e not in ct["carteiras"] and b.get("ate") is None:
                b["ate"] = agora


# ---------------------------------------------------------------------------------------------- resumo
def custos(r):
    """Taxas + deslize + financiamento pago (o financiamento recebido conta como custo negativo)."""
    if not r:
        return None
    return round((r.get("taxas") or 0) + (r.get("deslize") or 0) + (r.get("funding") or 0), 2)


def com_custos(r):
    if not r:
        return r
    cu = custos(r)
    antes = round(r["patrimonio"] - CAPITAL + cu, 2)
    return {**r, "custos": cu, "antesDosCustos": antes, "retornoAntes": round(antes / CAPITAL, 4)}


def resumo(est, agora, metricas_de):
    ct = est.get("contrario")
    if not ct or (not ct["carteiras"] and not ct["encerradas"]):
        return None
    hoje = dia_de(agora)
    todas = {}
    for k in CONTAS:
        a = AG.agregada(ct["banco"].get(k) or {}, hoje, "todas")
        if a:
            todas[k] = {**a, "nome": NOMES[k], "metricas": metricas_de(a)}
    cart = []
    for e, c in ct["carteiras"].items():
        l, res = c.get("ranking") or {}, c.get("resumo") or {}
        contas = {k: ({**com_custos(x), "metricas": metricas_de({**x, "inicio": c["desde"]})} if x and x.get("serie") else com_custos(x))
                  for k, x in res.items()}
        cart.append({"endereco": e, "curto": curto(e), "desde": c["desde"], "conta": round(l.get("conta", 0)),
                     "pnlMes": round((l.get("mes") or {}).get("pnl", 0)), "ganhoMes": round(K.ganho(l), 4) if l else None,
                     "pnlSemana": round((l.get("semana") or {}).get("pnl", 0)),
                     "pnlTotal": round((l.get("total") or {}).get("pnl", 0)), "medidas": c.get("medidas"), "contas": contas})
    cart.sort(key=lambda x: ((x["contas"].get(PADRAO) or {}).get("retorno") or 0), reverse=True)
    # o resumo da ideia: somando todas as carteiras, quanto a cópia normal perdeu antes e depois dos custos
    soma = {}
    for k in CONTAS:
        xs = [x["contas"].get(k) for x in cart if x["contas"].get(k)]
        if xs:
            soma[k] = {"resultado": round(sum(x["patrimonio"] - CAPITAL for x in xs), 2),
                       "custos": round(sum(x["custos"] or 0 for x in xs), 2),
                       "antesDosCustos": round(sum(x["antesDosCustos"] for x in xs), 2), "n": len(xs)}
    return {"regra": REGRA, "nomes": NOMES, "padrao": PADRAO, "inicio": ct["inicio"], "funil": ct["funil"],
            "proximaEscolha": (ct["ultimaEscolha"] or agora) + 7 * DIA if ct["ultimaEscolha"] else None,
            "carteiras": cart, "todas": todas, "soma": soma,
            "encerradas": [{**x, "curto": curto(x["endereco"])} for x in ct["encerradas"][-15:]],
            "config": {"alvo": ALVO, "minimo": MINIMO, "perdaMesMin": PERDA_MES_MIN, "atrasoMin": 1, "contas": list(CONTAS)}}
