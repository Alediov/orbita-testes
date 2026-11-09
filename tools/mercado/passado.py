"""Teste no passado FORA DA AMOSTRA (pedido do Alediov, 09/11/2026; só simulação, saldo fictício).

O teste de antes (`historico` de cada carteira) copia a carteira nos MESMOS 30 dias em que ela foi escolhida por ter ido
bem: é otimista (nos dados de 02 a 09/11/2026 dava +37% em média contra ~+1% ao vivo). Este teste pergunta outra coisa:
quanto a REGRA de escolha teria rendido se tivesse sido usada no passado, sem saber o que veio depois.

- T0 = 30 dias antes do começo do teste. A regra olha só os dados de T0 − 30 dias a T0 (o "passado do passado") e
  escolhe até 30 carteiras; a cópia delas é simulada de T0 até o fim (os 30 dias seguintes, que a regra não viu).
- O ranking público só tem o "agora" (lucro dos últimos 30 dias, conta de hoje): usar o de hoje seria olhar o futuro.
  Então, para cada candidata, o "ranking de T0" é refeito pelo `portfolio` dela (o histórico desde o começo da conta:
  valor da conta e lucro acumulado): conta em T0, lucro de T0 − 30 a T0, da semana e o total até T0, e o volume pelas
  execuções de T0 − 30 a T0. Depois, os mesmos filtros, o risco, o teste no período da escolha (em T0, velas de 1 h) e a
  mesma nota da escolha ao vivo. Entre as aprovadas, na ordem da nota do ranking, as 60 primeiras; dessas, as 30 de
  maior nota (como a escolha ao vivo).
- O universo: as linhas do ranking de hoje com volume total de pelo menos US$ 10 mil (o volume só cresce, então isso
  não depende de ter ganhado depois de T0; quem tinha conta de US$ 10 mil e girou 1× no mês já passa) e que não são
  cofre pelo nome. Uma amostra sorteada (semente = o dia de T0) de até `AMOSTRA` delas, não o ranking inteiro: o
  `portfolio` de cada uma custa 20 de peso e o balde é de 1.100 por minuto.
- O trabalho anda aos poucos, nas sobras de tempo das rodadas (fases pre → fino → copia → pronto, no estado
  `passado`); refaz a cada 7 dias com um T0 novo e guarda os resultados anteriores (`rodadas`).

Limitações (aparecem no LEIA-ME e no Como funciona do app): quem saiu do ranking antes de hoje (conta zerada e
esquecida) não entra no universo (viés de sobrevivência, otimista); o histórico "desde o começo" do `portfolio` é
espaçado (o valor mais perto de T0, até 5 dias); a API só guarda as 10.000 execuções mais recentes de cada carteira
(as muito ativas podem chegar sem as operações antigas); a escolha usa velas de 1 h e a cópia, de 15 min; o selo e o
papel (cofre) são os de hoje.
"""
from __future__ import annotations

import random
import time

import carteiras as K
import hl
from sim import Patrimonio, dia_de, operacoes_da_carteira, simular

MIN = 60_000
DIA = 86_400_000
JANELA = 30          # dias da escolha (antes de T0) e da cópia (depois de T0)
AMOSTRA = 3000
VOLUME_MIN = 10_000
REFAZER_DIAS = 7
ALVO = 30
TOL_DIAS = 5
MAX_FILLS = 3000
MAX_RODADAS = 12
VERSAO = 1


def curto(e):
    return f"{e[:6]}…{e[-4:]}"


def _hist(pf, nome):
    """Os pontos [(t, v)] de `accountValueHistory` ou `pnlHistory` desde o começo (perpétuos se houver)."""
    d = {k: v for k, v in (pf or [])}
    jan = d.get("perpAllTime") or d.get("allTime") or {}
    return sorted((int(t), float(v)) for t, v in (jan.get(nome) or []))


def perto(pts, t, tol=TOL_DIAS * DIA):
    """O ponto mais perto de t (até `tol`), ou None."""
    melhor = None
    for x, v in pts:
        if abs(x - t) <= tol and (melhor is None or abs(x - t) < abs(melhor[0] - t)):
            melhor = (x, v)
    return None if melhor is None else melhor[1]


def lucro_em(pnl, t):
    """O lucro acumulado em t: antes do 1º ponto (a conta não existia), 0; senão o ponto mais perto."""
    if not pnl or t < pnl[0][0]:
        return 0.0
    v = perto(pnl, t)
    if v is None:  # longe de qualquer ponto: o último antes de t
        antes = [v for x, v in pnl if x <= t]
        v = antes[-1] if antes else 0.0
    return v


def linha_em(e, nome, conta, pnl, t0):
    """A linha do ranking como seria em T0 (o volume do mês entra depois, pelas execuções)."""
    l0 = lucro_em(pnl, t0)
    vazio = {"pnl": 0.0, "roi": 0.0, "vlm": 0.0}
    return {"endereco": e, "conta": conta, "nome": nome, "dia": vazio,
            "semana": {"pnl": l0 - lucro_em(pnl, t0 - 7 * DIA), "roi": 0.0, "vlm": 0.0},
            "mes": {"pnl": l0 - lucro_em(pnl, t0 - JANELA * DIA), "roi": 0.0, "vlm": conta * 10},
            "total": {"pnl": l0, "roi": 0.0, "vlm": 0.0}}


# ---------------------------------------------------------------------------------------------- fases
def novo(cli, est, agora, log):
    antes = est.get("passado") or {}
    linhas = [K.linha_ranking(r) for r in cli.ranking()]
    uni, nomes = [], {}
    for l in linhas:
        nome = (l.get("nome") or "").lower()
        if not l["endereco"].startswith("0x") or len(l["endereco"]) != 42 or "vault" in nome or "hlp" in nome:
            continue
        if l["total"]["vlm"] < VOLUME_MIN:
            continue
        uni.append(l["endereco"])
        if l.get("nome"):
            nomes[l["endereco"]] = l["nome"]
    fim = agora - 8 * MIN
    t0 = fim - JANELA * DIA
    uni.sort()
    random.Random(dia_de(t0)).shuffle(uni)
    fila = uni[:AMOSTRA]
    est["passado"] = {"v": VERSAO, "fase": "pre", "t0": t0, "fim": fim, "criado": agora, "universo": len(uni),
                      "amostra": len(fila), "fila": fila, "i": 0, "nomes": {e: nomes[e] for e in fila if e in nomes},
                      "pre": {}, "preRecusas": {}, "fino": {}, "finoRecusas": {}, "escolhidas": None, "copia": {},
                      "resultado": antes.get("resultado"), "rodadas": antes.get("rodadas") or [], "estrutura": False}
    log(f"  passado: novo teste fora da amostra, T0 {dia_de(t0)}; universo {len(uni)}, amostra {len(fila)}")


def _pre(cli, p, e, log):
    pf = cli.portfolio(e)
    eqh, pnl = _hist(pf, "accountValueHistory"), _hist(pf, "pnlHistory")
    if not p.get("estrutura"):  # a 1ª resposta de verdade vai ao log (sem endereço): quantos pontos e o espaço perto de T0
        p["estrutura"] = True
        perto_t0 = min((abs(t - p["t0"]) for t, _ in eqh), default=None)
        log(f"  passado: portfolio desde o começo: {len(eqh)} pontos de valor, {len(pnl)} de lucro; ponto mais perto de "
            f"T0 a {round(perto_t0 / 3_600_000, 1) if perto_t0 is not None else '—'} h; janelas {[k for k, _ in (pf or [])]}")
    conta = perto(eqh, p["t0"])
    if conta is None:
        return "sem histórico perto do começo"
    l = linha_em(e, p["nomes"].get(e), conta, pnl, p["t0"])
    motivo = K.pre_filtro([l])[0][1]
    if motivo:
        return motivo
    ini = p["t0"] - (JANELA + 1) * DIA
    p["pre"][e] = {"conta": round(conta, 2), "mes": round(l["mes"]["pnl"], 2), "sem": round(l["semana"]["pnl"], 2),
                   "total": round(l["total"]["pnl"], 2),
                   "eq": [[t, round(v, 2)] for t, v in eqh if ini <= t <= p["t0"]][-60:],
                   "pnl": [[t, round(v, 2)] for t, v in pnl if ini <= t <= p["t0"]][-60:]}
    return None


def _fino(cli, p, e, cache, max_lev, prazo, M, log):
    x = p["pre"][e]
    t0 = p["t0"]
    fills = cli.execucoes_entre(e, t0 - JANELA * DIA, t0, maximo=MAX_FILLS)
    md = K.medidas(fills, t0)
    l = linha_em(e, p["nomes"].get(e), x["conta"], x["pnl"], t0)
    l["mes"]["pnl"], l["semana"]["pnl"], l["total"]["pnl"] = x["mes"], x["sem"], x["total"]
    l["mes"]["vlm"] = md["volume30d"]
    nr = K.nota_ranking(l)
    giro = K.giro(l)
    c = K.CRITERIOS
    motivo = ("quase parada no mês" if giro < c["giro_mes_min"] else "giro de formador de mercado" if giro > c["giro_mes_max"]
              else K.filtro_fino(md, "user"))
    if not motivo:
        motivo = K.filtro_fino(md, cli.papel(e))
    if motivo:
        p["fino"][e] = {"nr": round(nr, 4), "motivo": motivo}
        return motivo
    hist = M.teste_historico(cli, log, l, fills, x["eq"] or [(t0, x["conta"])], t0, t0, cache, max_lev, prazo,
                             intervalo="1h")
    rk = K.risco(fills, x["conta"], x["pnl"], cache.velas, t0)
    if rk["recusa"]:
        p["fino"][e] = {"nr": round(nr, 4), "motivo": "quase nunca perde"}
        return "quase nunca perde"
    h3 = ((hist or {}).get(M.PADRAO) or {}).get("retorno")
    p["fino"][e] = {"nr": round(nr, 4), "nota": K.nota_escolha(h3, md.get("passivoPct"), rk["alertas"]), "hist3": h3,
                    "boas": [m for m, *_ in K.moedas_boas(fills, t0)]}
    return None


def escolher(p):
    """Como a escolha ao vivo: na ordem da nota do ranking, as 2 × ALVO primeiras aprovadas; dessas, as ALVO de maior
    nota."""
    ok = [(f["nr"], e) for e, f in p["fino"].items() if "nota" in f]
    aprovadas = [e for _, e in sorted(ok, reverse=True)[:2 * ALVO]]
    return sorted(aprovadas, key=lambda e: -p["fino"][e]["nota"])[:ALVO]


def _copiar(cli, p, e, cache, max_lev, M):
    t0, fim = p["t0"], p["fim"]
    fills = cli.execucoes_entre(e, t0, fim, maximo=10_000)
    ops = operacoes_da_carteira(fills)
    pf = cli.portfolio(e)
    eq = [(t, v) for t, v in M.eq_do_portfolio(pf) + _hist(pf, "accountValueHistory") if t0 - 2 * DIA <= t <= fim]
    if not eq:
        eq = [tuple(x) for x in (p["pre"].get(e) or {}).get("eq") or []]
    for m in sorted({o["moeda"] for o in ops}):
        if m not in cache.velas:
            cache.garantir(m, t0 - DIA, fim, "15m")
    merc = cache.mercado(max_lev)
    boas = p["fino"][e].get("boas") or []
    contas = {k: M.nova_conta(k, t0, boas) for k in M.combos()}
    simular(ops, Patrimonio(eq or [(t0, p["pre"][e]["conta"])]), merc, list(contas.values()), fim)
    out = {}
    for k, c in contas.items():
        r = c.resumo(merc, fim)
        out[k] = {"serie": r["serie"], "retorno": r["retorno"], "piorQueda": r["piorQueda"], "ops": r["ops"],
                  "nLiq": r["nLiq"], **({"parou": 1} if r.get("parou") else {})}
    p["copia"][e] = out


def media(series_por_carteira, de, ate):
    """A carteira de carteiras: US$ 1.000 em partes iguais, cada uma andando como a cópia (US$ 1.000 antes do 1º ponto)."""
    import datetime as dt
    if not series_por_carteira:
        return []
    mapas = [dict(s) for s in series_por_carteira]
    out, d = [], dt.date.fromisoformat(de)
    fim = dt.date.fromisoformat(ate)
    ult = [1000.0] * len(mapas)
    while d <= fim:
        k = d.isoformat()
        for i, m in enumerate(mapas):
            if k in m:
                ult[i] = m[k]
        out.append([k, round(sum(ult) / len(ult), 2)])
        d += dt.timedelta(days=1)
    return out


def fechar(p, agora):
    de, ate = dia_de(p["t0"]), dia_de(p["fim"])
    esc = [e for e in p["escolhidas"] if e in p["copia"]]
    contas = {}
    for k in sorted({k for e in esc for k in p["copia"][e]}):
        cs = [p["copia"][e][k] for e in esc if k in p["copia"][e]]
        serie = media([c["serie"] for c in cs], de, ate)
        if not serie:
            continue
        pico, queda = 1000.0, 0.0
        for _, v in serie:
            pico = max(pico, v)
            queda = max(queda, 1 - v / pico)
        contas[k] = {"serie": serie, "retorno": round(serie[-1][1] / 1000 - 1, 4), "piorQueda": round(queda, 4),
                     "ops": sum(c["ops"] for c in cs), "nLiq": sum(c["nLiq"] for c in cs), "inicio": p["t0"],
                     "piores": round(min(c["retorno"] for c in cs), 4), "positivas": sum(1 for c in cs if c["retorno"] > 0),
                     **({"pararam": sum(1 for c in cs if c.get("parou"))} if any(c.get("parou") for c in cs) else {})}
    prev = [p["fino"][e]["hist3"] for e in esc if p["fino"][e].get("hist3") is not None]
    previsto = round(sum(prev) / len(prev), 4) if prev else None
    rec_pre = dict(sorted(p["preRecusas"].items(), key=lambda x: -x[1]))
    rec_fino = dict(sorted(p["finoRecusas"].items(), key=lambda x: -x[1]))
    res = {"de": p["t0"], "ate": p["fim"], "feitoEm": agora, "n": len(esc), "universo": p["universo"],
           "amostra": p["amostra"], "aproximado": True, "resolucao": {"escolha": "1h", "copia": "15m"},
           "funil": {"amostra": p["amostra"], "olhadas": p["i"], "passaram": len(p["pre"]), "recusasPre": rec_pre,
                     "analisadas": len(p["fino"]), "aprovadas": sum(1 for f in p["fino"].values() if "nota" in f),
                     "recusasFino": rec_fino, "escolhidas": len(esc)},
           "previsto": previsto, "contas": contas,
           "carteiras": sorted(({"curto": curto(e), "nota": p["fino"][e]["nota"], "previsto": p["fino"][e].get("hist3"),
                                 "retorno": (p["copia"][e].get("3x1") or {}).get("retorno")} for e in esc),
                               key=lambda x: -(x["retorno"] or -9))}
    p["resultado"] = res
    r3 = (contas.get("3x1") or {}).get("retorno")
    p["rodadas"] = (p["rodadas"] + [{"de": p["t0"], "ate": p["fim"], "n": len(esc), "retorno": r3, "previsto": previsto}])[-MAX_RODADAS:]
    p["fase"] = "pronto"
    for k in ("fila", "pre", "fino", "copia", "nomes"):
        p[k] = {} if k != "fila" else []


def avancar(cli, est, agora, log, prazo, M):
    """Anda o que der até `prazo` (time.monotonic)."""
    p = est.get("passado")
    if not p or p.get("v") != VERSAO or (p["fase"] == "pronto" and agora - p["criado"] >= REFAZER_DIAS * DIA):
        if time.monotonic() > prazo - 30:
            return
        novo(cli, est, agora, log)
        p = est["passado"]
    if p["fase"] == "pronto":
        return
    n0 = (p["i"], len(p["fino"]), len(p["copia"]))
    cache = M.Precos(cli, log, agora)
    try:
        if p["fase"] == "pre":
            while p["i"] < len(p["fila"]) and time.monotonic() < prazo:
                e = p["fila"][p["i"]]
                try:
                    m = _pre(cli, p, e, log)
                except hl.Erro as er:
                    m = "sem dados"
                    log(f"  passado: {curto(e)}: {er}")
                p["i"] += 1
                if m:
                    p["preRecusas"][m] = p["preRecusas"].get(m, 0) + 1
            if p["i"] >= len(p["fila"]):
                p["fase"] = "fino"
        if p["fase"] == "fino":
            fila = sorted((e for e in p["pre"] if e not in p["fino"]), key=lambda e: -p["pre"][e]["mes"] / max(1, p["pre"][e]["conta"]))
            for e in fila:
                if time.monotonic() > prazo:
                    break
                try:
                    m = _fino(cli, p, e, cache, est["maxLev"], prazo, M, log)
                except hl.Erro as er:
                    p["fino"][e] = {"nr": 0, "motivo": "sem dados"}
                    m = "sem dados"
                    log(f"  passado: {curto(e)}: {er}")
                if m:
                    p["finoRecusas"][m] = p["finoRecusas"].get(m, 0) + 1
            if all(e in p["fino"] for e in p["pre"]):
                p["escolhidas"] = escolher(p)
                p["fase"] = "copia"
                log(f"  passado: {len(p['escolhidas'])} escolhidas pela regra em T0")
        if p["fase"] == "copia":
            cache = M.Precos(cli, log, agora)  # velas de 15 min até o fim (as da escolha são de 1 h e param em T0)
            for e in p["escolhidas"]:
                if e in p["copia"]:
                    continue
                if time.monotonic() > prazo:
                    break
                try:
                    _copiar(cli, p, e, cache, est["maxLev"], M)
                except hl.Erro as er:
                    log(f"  passado: cópia de {curto(e)}: {er}")
                    p["copia"][e] = {}
            if all(e in p["copia"] for e in p["escolhidas"]):
                fechar(p, agora)
                r = (p["resultado"]["contas"].get("3x1") or {}).get("retorno")
                log(f"  passado: pronto: {p['resultado']['n']} carteiras, 3× · 1 min {r if r is None else round(r * 100, 1)}% "
                    f"(o teste no período da escolha dizia {p['resultado']['previsto']})")
    finally:
        log(f"  passado ({p['fase']}): {p['i'] - n0[0]} olhadas, {len(p['fino']) - n0[1]} analisadas, "
            f"{len(p['copia']) - n0[2]} copiadas nesta rodada")


def resumo(est, metricas_de):
    p = est.get("passado")
    if not p:
        return None
    andamento = {"fase": p["fase"], "de": p["t0"], "amostra": p["amostra"], "olhadas": p["i"], "passaram": len(p["pre"]),
                 "analisadas": len(p["fino"]), "aprovadas": sum(1 for f in p["fino"].values() if "nota" in f),
                 "escolhidas": len(p["escolhidas"] or []), "copiadas": len(p["copia"]), "criado": p["criado"]}
    res = p.get("resultado")
    if res:
        res = {**res, "contas": {k: {**c, "metricas": metricas_de(c)} for k, c in res["contas"].items()}}
    return {"aproximado": True, "andamento": andamento if p["fase"] != "pronto" else None, "resultado": res,
            "rodadas": p.get("rodadas") or [], "proximo": p["criado"] + REFAZER_DIAS * DIA if p["fase"] == "pronto" else None}
