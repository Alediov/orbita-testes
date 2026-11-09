"""Escolha das carteiras a copiar: o ranking público, os filtros e as medidas de cada candidata (puro, sem rede).

Filtros (CRITERIOS): conta de pelo menos US$ 10 mil; lucro positivo em 30 dias e no total; lucro do mês de no máximo
150% da conta (acima disso é aposta ou conta que acabou de receber depósito; na 1ª rodada de verdade, 02/11/2026, as
melhores pelo retorno do ranking tinham +200% a +350%); volume do mês entre 1× e 300× o valor da conta (abaixo, quase parada; acima, giro de formador de mercado ou de alta frequência); não é cofre
(userRole "vault"; e nomes com "vault"/"HLP"); nas execuções dos últimos 30 dias: pelo menos 10 operações e no máximo
48 por dia, tempo médio de posição de pelo menos 1 h (com 3 posições fechadas ou mais), e 80% do volume ou mais em
perpétuos da Hyperliquid (o que dá para copiar). Robôs de velocidade (posições de segundos ou minutos) não são copiáveis
com atraso de 1 a 5 min.

Contra o "quase nunca perde" (pedido do Alediov, 02/11/2026, 19h08; `risco`): carteiras que ganham pouco quase sempre e
seguram as perdas até virarem um tombo. Três medidas, com limites folgados (RISCO): a maior perda numa ordem ÷ o ganho
médio das ordens que ganharam (> 25× recusa, > 10× nota menor); a maior queda do lucro acumulado do pico ao fundo em 30
dias ÷ a conta (`portfolio`, pnlHistory; > 50% recusa, > 30% nota menor); e o tempo que a pior posição ficou no
vermelho (preço contra a entrada média, pelas velas de 15 min do teste no histórico; também a posição ainda aberta;
> 10 dias recusa, > 4 dias nota menor). Vale para as novas escolhas; as já seguidas não saem por isso.

Moedas boas (`moedas_boas`): pelas execuções da carteira ANTES do início da cópia (sem olhar o futuro), as moedas com
pelo menos `MIN_OPS_MOEDA` ordens que realizaram resultado e resultado somado (menos taxas) positivo.
"""
from __future__ import annotations

from sim import copiavel, operacoes_da_carteira

DIA = 86_400_000
CRITERIOS = {
    "conta_min": 10_000,
    "giro_mes_min": 1.0,
    "giro_mes_max": 300.0,
    "giro_regular_min": 3.0,
    "giro_regular_max": 100.0,
    "ganho_mes_max": 1.5,
    "ops_min": 10,
    "ops_dia_max": 48,
    "posicao_min_h": 1.0,
    "fechadas_min": 3,
    "copiavel_min": 0.8,
}
RISCO = {"razao_recusa": 25.0, "razao_alerta": 10.0, "queda_recusa": 0.5, "queda_alerta": 0.3,
         "vermelho_recusa_h": 240.0, "vermelho_alerta_h": 96.0}
MIN_OPS_MOEDA = 3



def num(x, padrao=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return padrao


def linha_ranking(r):
    """Uma linha do ranking → {endereco, conta, nome, dia/semana/mes/total: {pnl, roi, vlm}}."""
    jan = {}
    for par in r.get("windowPerformances") or []:
        if isinstance(par, (list, tuple)) and len(par) == 2:
            jan[par[0]] = {k: num(par[1].get(k)) for k in ("pnl", "roi", "vlm")}
    vazio = {"pnl": 0.0, "roi": 0.0, "vlm": 0.0}
    return {"endereco": (r.get("ethAddress") or "").lower(), "conta": num(r.get("accountValue")),
            "nome": r.get("displayName"), "dia": jan.get("day", vazio), "semana": jan.get("week", vazio),
            "mes": jan.get("month", vazio), "total": jan.get("allTime", vazio)}


def pre_filtro(linhas, c=CRITERIOS):
    """Só pelo ranking (sem pedidos): devolve [(linha, motivo da recusa ou None)]."""
    out = []
    for l in linhas:
        nome = (l.get("nome") or "").lower()
        giro = l["mes"]["vlm"] / l["conta"] if l["conta"] > 0 else 0
        if not l["endereco"].startswith("0x") or len(l["endereco"]) != 42:
            m = "endereço estranho"
        elif "vault" in nome or "hlp" in nome:
            m = "cofre (pelo nome)"
        elif l["conta"] < c["conta_min"]:
            m = "conta pequena"
        elif l["mes"]["pnl"] <= 0:
            m = "prejuízo em 30 dias"
        elif l["total"]["pnl"] <= 0:
            m = "prejuízo no total"
        elif ganho(l) > c["ganho_mes_max"]:
            m = "lucro alto demais para a conta (aposta)"
        elif giro < c["giro_mes_min"]:
            m = "quase parada no mês"
        elif giro > c["giro_mes_max"]:
            m = "giro de formador de mercado"
        else:
            m = None
        out.append((l, m))
    return out


def ganho(l, janela="mes"):
    """Lucro da janela ÷ valor da conta (o `roi` do ranking usa outra base e dá números estranhos: US$ 210 de lucro
    numa conta de US$ 85 mil aparecia como +210%)."""
    return l[janela]["pnl"] / l["conta"] if l["conta"] > 0 else 0.0


def giro(l):
    return l["mes"]["vlm"] / l["conta"] if l["conta"] > 0 else 0.0


def nota_ranking(l, c=CRITERIOS):
    """Para ordenar as que passaram no pré-filtro: o ganho do mês (até 100%) pesado pelo tamanho da conta (contas
    maiores e lucrativas costumam ser menos sorte), mais um pouco da semana; e a preferência por quem negocia com
    regularidade (pedido de 02/11/2026, 19h43: o lucro alto do mês costuma ser de poucas apostas grandes, que não
    passam nos filtros finos): giro do mês entre 3× e 100× a conta vale o dobro. Não recusa ninguém (as recusas
    continuam em 1× e 300×)."""
    import math
    base = min(1.0, ganho(l)) * (math.log10(max(l["conta"], 10)) - 3) + 0.3 * max(-0.3, min(0.3, ganho(l, "semana")))
    regular = c["giro_regular_min"] <= giro(l) <= c["giro_regular_max"]
    return base * (1.0 if regular else 0.5) + (0.1 if regular else 0.0)


def medidas(fills, agora, dias=30):
    """Medidas das execuções dos últimos `dias`: operações por dia, tempo médio de posição, % de execuções passivas…"""
    ini = agora - dias * DIA
    fs = [f for f in fills if int(f["time"]) >= ini]
    tot = sum(num(f["sz"]) * num(f["px"]) for f in fs)
    perp = [f for f in fs if copiavel(f.get("coin", ""))]
    vol_perp = sum(num(f["sz"]) * num(f["px"]) for f in perp)
    passivo = sum(num(f["sz"]) * num(f["px"]) for f in perp if f.get("crossed") is False)
    ops = operacoes_da_carteira(perp)
    if perp:
        span = max(1.0, (agora - min(int(f["time"]) for f in perp)) / DIA)
    else:
        span = float(dias)
    # posições: de zero a zero (ou até virar de lado), por moeda
    dur, abertas, por_moeda = [], {}, {}
    for f in sorted(perp, key=lambda f: int(f["time"])):
        m, t = f["coin"], int(f["time"])
        antes = num(f["startPosition"])
        depois = antes + (1 if f["side"] == "B" else -1) * num(f["sz"])
        por_moeda[m] = por_moeda.get(m, 0) + num(f["sz"]) * num(f["px"])
        if antes == 0 and depois != 0:
            abertas[m] = t
        elif antes != 0 and (depois == 0 or (depois > 0) != (antes > 0)):
            if m in abertas:
                dur.append(t - abertas.pop(m))
            if depois != 0:
                abertas[m] = t
    resultado = sum(num(f.get("closedPnl")) - num(f.get("fee")) for f in perp)
    return {
        "ops": len(ops),
        "opsDia": round(len(ops) / span, 2),
        "fechadas": len(dur),
        "posicaoMediaH": round(sum(dur) / len(dur) / 3_600_000, 2) if dur else None,
        "posicaoMedianaH": round(sorted(dur)[len(dur) // 2] / 3_600_000, 2) if dur else None,
        "passivoPct": round(passivo / vol_perp, 3) if vol_perp else None,
        "copiavelPct": round(vol_perp / tot, 3) if tot else None,
        "moedas": [m for m, _ in sorted(por_moeda.items(), key=lambda x: -x[1])[:6]],
        "resultado30d": round(resultado, 2),
        "volume30d": round(vol_perp, 2),
        "dias": round(span, 1),
    }


def filtro_fino(md, papel, c=CRITERIOS):
    """Depois de buscar as execuções: o motivo da recusa ou None."""
    if papel == "vault":
        return "é um cofre"
    if md["ops"] < c["ops_min"]:
        return "poucas operações em 30 dias"
    if md["opsDia"] > c["ops_dia_max"]:
        return "operações demais por dia (robô de velocidade)"
    if md["copiavelPct"] is not None and md["copiavelPct"] < c["copiavel_min"]:
        return "opera muito fora dos perpétuos"
    if md["fechadas"] < c["fechadas_min"] or md["posicaoMediaH"] is None:
        return "poucas posições fechadas para medir"
    if md["posicaoMediaH"] < c["posicao_min_h"]:
        return "posições curtas demais"
    return None


def us(v):
    v = abs(v)
    if v >= 1e6:
        return f"US$ {v / 1e6:.1f} mi".replace(".", ",")
    if v >= 1e3:
        return f"US$ {v / 1e3:.0f} mil"
    return f"US$ {v:.0f}"


def pct(v):
    return f"{v * 100:+.0f}%".replace("+-", "−").replace("-", "−")


def horas(h):
    if h is None:
        return "?"
    if h < 48:
        return f"{h:.0f} h" if h >= 2 else f"{h * 60:.0f} min"
    return f"{h / 24:.0f} dias"


def nota_escolha(hist3, passivo, alertas):
    """Nota para escolher entre as aprovadas: o teste no histórico (3× e 1 min, entre −100% e +300%), mais um pouco
    pela fração com ordem limite (o que dá para copiar mais barato) e menos 0,3 por alerta de "quase nunca perde"."""
    h = -1.0 if hist3 is None else max(-1.0, min(3.0, hist3))
    return round(h + 0.2 * (passivo or 0) - 0.3 * len(alertas or []), 4)


def selo(md):
    """"robo" (robô provável: muitas operações por dia, posições curtas ou quase tudo em ordem limite, de formador de
    mercado) ou "humano" (humano provável). Só um palpite pelo jeito de operar, para o filtro do app."""
    if not md:
        return None
    if (md.get("opsDia") or 0) >= 10 or (md.get("posicaoMediaH") or 99) < 3 or (md.get("passivoPct") or 0) >= 0.7:
        return "robo"
    return "humano"


def motivos(l, md, hist=None):
    """Por que a carteira entrou, em frases curtas."""
    m = [f"Conta de {us(l['conta'])}",
         f"Lucro de {us(l['mes']['pnl'])} em 30 dias ({pct(ganho(l))} da conta)",
         f"Lucro total de {us(l['total']['pnl'])}",
         f"~{md['opsDia']:.1f} operações por dia; posição média de {horas(md['posicaoMediaH'])}".replace(".", ",")]
    if md.get("moedas"):
        m.append("Opera " + ", ".join(md["moedas"][:4]))
    if md.get("passivoPct"):
        m.append(f"Ordens limite em {md['passivoPct'] * 100:.0f}% do volume")
    if hist is not None:
        m.append(f"Teste no período da escolha (3× e 1 min): {pct(hist)}")
    return m


def moedas_boas(fills, ate, minimo=MIN_OPS_MOEDA):
    """Moedas em que a carteira ganhou ANTES de `ate`: [(moeda, ordens, resultado)] das boas, do melhor ao pior."""
    por = {}
    for f in fills:
        if int(f["time"]) >= ate or not copiavel(f.get("coin", "")):
            continue
        d = por.setdefault(f["coin"], {"res": 0.0, "ordens": set()})
        d["res"] += num(f.get("closedPnl")) - num(f.get("fee"))
        if num(f.get("closedPnl")) != 0:
            d["ordens"].add(f.get("oid") or f.get("tid"))
    boas = [(m, len(d["ordens"]), round(d["res"], 2)) for m, d in por.items() if len(d["ordens"]) >= minimo and d["res"] > 0]
    return sorted(boas, key=lambda x: -x[2])


def _resultado_por_ordem(fills):
    por = {}
    for f in fills:
        if not copiavel(f.get("coin", "")):
            continue
        k = f.get("oid") or (f["coin"], int(f["time"]) // 60_000)
        por[k] = por.get(k, 0.0) + num(f.get("closedPnl"))
    return [v for v in por.values() if v != 0]


def _queda_do_lucro(pnl_hist, conta):
    """Maior queda do lucro acumulado (pico → fundo) ÷ conta."""
    pico, pior = None, 0.0
    for _t, v in pnl_hist or []:
        v = num(v)
        pico = v if pico is None else max(pico, v)
        pior = max(pior, pico - v)
    return pior / conta if conta > 0 else 0.0


def _tempo_no_vermelho(fills, velas, ate):
    """Por posição (de zero a zero, por moeda): horas com o fechamento da vela contra a entrada média. A pior."""
    pior = (0.0, None)
    abertas = {}
    for f in sorted((f for f in fills if copiavel(f.get("coin", ""))), key=lambda f: int(f["time"])):
        m, t = f["coin"], int(f["time"])
        sz, px = num(f["sz"]), num(f["px"])
        antes = num(f["startPosition"])
        depois = antes + (1 if f["side"] == "B" else -1) * sz
        e = abertas.get(m)
        if antes == 0 or e is None:
            if depois != 0:
                abertas[m] = {"t": t, "lado": 1 if depois > 0 else -1, "sz": abs(depois), "ent": px}
            continue
        if (depois > 0) == (e["lado"] > 0) and abs(depois) > e["sz"]:  # aumentou
            e["ent"] = (e["sz"] * e["ent"] + (abs(depois) - e["sz"]) * px) / abs(depois)
            e["sz"] = abs(depois)
            continue
        if depois == 0 or (depois > 0) != (e["lado"] > 0):  # fechou (ou virou)
            h = _horas_contra(velas.get(m), e, t)
            if h > pior[0]:
                pior = (h, m)
            abertas.pop(m)
            if depois != 0:
                abertas[m] = {"t": t, "lado": 1 if depois > 0 else -1, "sz": abs(depois), "ent": px}
        else:
            e["sz"] = abs(depois)
    for m, e in abertas.items():  # a posição ainda aberta também conta
        h = _horas_contra(velas.get(m), e, ate)
        if h > pior[0]:
            pior = (h, m)
    return pior


def _horas_contra(v, e, fim):
    if not v:
        return 0.0
    tot = 0
    for t0, t1, _h, _l, c in v.entre(e["t"], fim):
        if (c - e["ent"]) * e["lado"] < 0:
            tot += min(t1 + 1, fim) - max(t0, e["t"])
    return max(0, tot) / 3_600_000


def risco(fills, conta, pnl_hist, velas, ate, r=RISCO):
    """As três medidas contra o "quase nunca perde", os alertas legíveis e a recusa (ou None)."""
    res = _resultado_por_ordem([f for f in fills if int(f["time"]) <= ate])
    ganhos = [x for x in res if x > 0]
    perdas = [-x for x in res if x < 0]
    razao = (max(perdas) / (sum(ganhos) / len(ganhos))) if ganhos and perdas else 0.0
    queda = _queda_do_lucro(pnl_hist, conta)
    vermelho, moeda = _tempo_no_vermelho(fills, velas or {}, ate)
    alertas, recusa = [], None

    def checar(valor, recusa_em, alerta_em, frase):
        nonlocal recusa
        if valor > recusa_em and recusa is None:
            recusa = frase
        elif valor > alerta_em:
            alertas.append(frase)
    checar(razao, r["razao_recusa"], r["razao_alerta"], f"a pior perda é {razao:.0f}× o ganho médio")
    checar(queda, r["queda_recusa"], r["queda_alerta"], f"o lucro caiu {queda * 100:.0f}% da conta do pico ao fundo")
    checar(vermelho, r["vermelho_recusa_h"], r["vermelho_alerta_h"],
           f"a pior posição ({moeda}) passou {horas(vermelho)} no vermelho")
    return {"piorPerdaRazao": round(razao, 1), "quedaLucro": round(queda, 3), "vermelhoH": round(vermelho, 1),
            "vermelhoMoeda": moeda, "alertas": alertas, "recusa": recusa}
