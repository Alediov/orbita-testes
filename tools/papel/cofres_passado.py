"""Cofres: o teste FORA DA AMOSTRA (pedido do Alediov, 09/11/2026; formato em FORMATO.md, "Cofres"). Só simulação.

O teste de antes (`historico` de cada versão, agora "no período da escolha (otimista)") refaz os últimos 180 dias com os
cofres que a escolha de HOJE detalhou: os ~40 que mais lucraram no último mês. Escolher pelo que foi bem e medir nos
mesmos dias é otimista (com 6 dias ao vivo: 5 melhores −0,06% ao vivo × +7,7% nesse teste). Este teste pergunta: quanto
as regras teriam rendido se fossem usadas no passado sem saber o que veio depois.

- O período: as últimas `SEMANAS` (12) semanas, de uma segunda-feira até agora. Toda segunda, cada versão escolhe com os
  números de cada cofre só até aquele dia (a cota e o patrimônio do `vaultDetails` até T0: lucro do mês, desde o
  início, pior queda, idade, TVL de T0, a constância de 90 dias) e o dinheiro anda pelos dias seguintes.
- O universo NÃO sai dos que foram bem: é a lista inteira da corretora (`stats-data …/vaults`), sem o HLP e os filhos
  dele, com pelo menos 37 dias de vida no fim. Os abertos, pela ordem do TVL de HOJE (com US$ 30 mil ou mais; até
  `ABERTOS`), e os FECHADOS (quebraram ou o líder fechou), pela ordem do lucro desde o início em valor absoluto (até
  `FECHADOS`): assim os que deram errado no meio do caminho também entram. O HLP vai primeiro.
- Cada cofre do universo custa um `vaultDetails` (peso 20; o balde é de 1.100 por minuto): o trabalho anda aos poucos,
  `TEMPO_MAX` por rodada, nas sobras de tempo (fases detalhar → simular → pronto, no estado `passado`). Fica só um
  resumo de cada cofre (a cota e o patrimônio, um ponto por dia desde 100 dias antes do começo, e os pontos antigos,
  semanais), e nada se o cofre acabou antes do começo ou nunca teve US$ 100 mil no período. Refeito a cada 7 dias.
- Cofre que fechou no meio: os dados param no último ponto (`fimDados`) e a versão sai dele no dia seguinte, pelo
  último valor.

Limitações (aparecem no Como funciona do app): só entram os cofres que ainda estão na lista (os apagados, não); os
abertos são escolhidos pelo TVL de hoje (um cofre que era grande e encolheu mais de 70% fica de fora); a parte do líder
é a de hoje (os fechados: não se sabe, a regra não confere) e por isso o sinal do líder não entra neste teste; não se
sabe quando um cofre fechou para depósitos; o histórico antigo de cada cofre tem poucos pontos (a constância de 90 dias
fica mais lisa que a de verdade); as comissões são as de hoje.
"""
from __future__ import annotations

import datetime as dt
import time

import hl
from conta import CAPITAL, DIA, cdi_ano_da_serie, dia_de, metricas

SEMANAS = 12
ABERTOS = 300
FECHADOS = 100
UNI_TVL_MIN = 30_000.0
FECHADO_PNL_MIN = 3_000.0
PRE_DIAS = 100             # dias com um ponto por dia antes do começo (90 da constância + folga)
REFAZER_DIAS = 7
TEMPO_MAX = 240            # s por rodada
RESTANTE_MIN = 600         # s: com menos que isso na rodada, fica para a próxima
MAX_RODADAS = 12
VERSAO = 1
CDI_PADRAO = 0.149


def _ms_do_dia(d: dt.date) -> int:
    """Meia-noite de Brasília do dia `d`, em ms."""
    return int(dt.datetime(d.year, d.month, d.day, 3, tzinfo=dt.timezone.utc).timestamp() * 1000)


def inicio_do_teste(agora):
    """A segunda-feira (meia-noite de Brasília) de `SEMANAS` semanas atrás."""
    d = dt.date.fromisoformat(dia_de(agora - SEMANAS * 7 * DIA))
    return _ms_do_dia(d - dt.timedelta(days=d.weekday()))


def universo(C, linhas, agora):
    """[endereço] na ordem do trabalho e {endereço: {n, c, f, pai}} (o que a lista diz de cada um)."""
    abertos, fechados, meta = [], [], {}
    corte = agora - (C.IDADE_MIN_DIAS + 7) * DIA
    for l in linhas.values():
        a = l["endereco"]
        if a == C.HLP or (l["tipo"] == "child" and l["pai"] in (None, C.HLP)):
            continue
        if l["criado"] and l["criado"] > corte:
            continue
        if l["fechado"]:
            if abs(l["lucroTotalUS"]) >= FECHADO_PNL_MIN:
                fechados.append(l)
        elif l["tvl"] >= UNI_TVL_MIN:
            abertos.append(l)
    abertos.sort(key=lambda l: (-l["tvl"], l["endereco"]))
    fechados.sort(key=lambda l: (-abs(l["lucroTotalUS"]), l["endereco"]))
    escolhidos = [C.HLP] + [l["endereco"] for l in abertos[:ABERTOS]] + [l["endereco"] for l in fechados[:FECHADOS]]
    for l in abertos[:ABERTOS] + fechados[:FECHADOS]:
        meta[l["endereco"]] = {"n": l["nome"], "c": l["criado"], "f": l["fechado"]}
    return escolhidos, meta, {"abertos": len(abertos), "fechados": len(fechados)}


def novo(ctx, est, linhas):
    import cofres as C
    agora = ctx.agora
    antes = est.get("passado") or {}
    fila, meta, tam = universo(C, linhas, agora)
    est["passado"] = {"v": VERSAO, "fase": "detalhar", "criado": agora, "ini": inicio_do_teste(agora), "fim": agora,
                      "fila": fila, "meta": meta, "i": 0, "dados": {}, "recusas": {}, "lista": len(linhas),
                      "candidatos": tam, "resultado": antes.get("resultado"), "rodadas": antes.get("rodadas") or []}
    ctx.log(f"  fora da amostra: novo teste desde {dia_de(est['passado']['ini'])}; universo {len(fila)} cofres "
            f"({tam['abertos']} abertos e {tam['fechados']} fechados candidatos)")


def compactar(C, s, av, ini, fim):
    """A cota e o patrimônio: os pontos antes de `ini − PRE_DIAS` (um por semana, mais o 1º) e um por dia depois."""
    corte = ini - PRE_DIAS * DIA
    velhos, ult = [], None
    for t, v in s:
        if t >= corte:
            break
        if ult is None or t - ult >= 7 * DIA:
            velhos.append([t, round(v, 6)])
            ult = t
    fim_s = min(fim, s[-1][0])
    novos = []
    t = max(corte, s[0][0])
    while t <= fim_s:
        v = C.interp(s, t)
        if v is not None:
            novos.append([t, round(v, 6)])
        t += DIA
    if s[-1][0] <= fim and (not novos or novos[-1][0] < s[-1][0]):
        novos.append([s[-1][0], round(s[-1][1], 6)])
    av_out = []
    t = max(ini - 45 * DIA, av[0][0]) if av else fim + 1
    while av and t <= min(fim, av[-1][0]):
        v = C.valor_em(av, t)
        if v is not None:
            av_out.append([t, round(v, 0)])
        t += DIA
    if av and av[-1][0] <= fim:
        av_out.append([av[-1][0], round(av[-1][1], 0)])
    return velhos + novos, av_out


def _detalhar(ctx, C, p, a):
    d = ctx.cli.cofre(a)
    if not isinstance(d, dict) or not d.get("portfolio"):
        return "sem dados na corretora"
    m = p["meta"].get(a) or {}
    linha = {"nome": m.get("n"), "criado": m.get("c"), "fechado": m.get("f")}
    inf = C.info_detalhe(d, linha)
    s, av = C.serie_cota(d)
    if len(s) < 2 or not av:
        return "sem histórico"
    if s[-1][0] < p["ini"]:
        return "acabou antes do teste"
    janela = [v for t, v in av if p["ini"] - 30 * DIA <= t <= p["fim"]]
    if a != C.HLP and (not janela or max(janela) < C.TVL_MIN):
        return "nunca teve US$ 100 mil no período"
    sc, avc = compactar(C, s, av, p["ini"], p["fim"])
    fechado = bool(inf["fechado"])
    p["dados"][a] = {"n": inf["nome"], "com": inf["com"], "lf": None if fechado else inf["lf"], "c": inf["criado"],
                     "f": s[-1][0] if fechado else None, "s": sc, "av": avc}
    return None


def simular(ctx, C, p, est):
    metas = {}
    for a, x in p["dados"].items():
        metas[a] = {"endereco": a, "nome": x["n"], "com": x["com"], "lf": x["lf"], "criado": x["c"], "filhoHLP": False,
                    "fechado": False, "aceita": True, "fimDados": x["f"], "s": [tuple(y) for y in x["s"]],
                    "av": [tuple(y) for y in x["av"]]}
    if not metas:
        return {"contas": {}, "escolhas": []}
    return C.simular_regras(metas, p["ini"], p["fim"], passado=True)


def previsto_do_hist(est, ini, fim):
    """O que o teste no período da escolha (otimista) dizia para o MESMO período: {versão: retorno}."""
    out = {}
    for vid, h in ((est.get("hist") or {}).get("versoes") or {}).items():
        sr = dict((d, v) for d, v in (h or {}).get("serie") or [])
        a = [v for d, v in sorted(sr.items()) if d <= dia_de(ini)]
        b = [v for d, v in sorted(sr.items()) if d <= dia_de(fim)]
        if a and b and a[-1] > 0:
            out[vid] = round(b[-1] / a[-1] - 1, 6)
    return out


def fechar(ctx, C, p, est):
    r = simular(ctx, C, p, est)
    contas = {}
    for vid, c in r["contas"].items():
        c = {k: c[k] for k in ("inicio", "serie", "retorno", "piorQueda", "ops", "taxas", "liquidacoes", "nLiq", "extra") if k in c}
        contas[vid] = c
    escolhas = r["escolhas"]
    usados = {x["endereco"] for e in escolhas for x in e["top5"]}
    res = {"de": p["ini"], "ate": p["fim"], "feitoEm": ctx.agora, "semanas": len(escolhas), "aproximado": True,
           "funil": {"lista": p["lista"], "candidatos": p["candidatos"], "universo": len(p["fila"]),
                     "detalhados": p["i"], "comDados": len(p["dados"]), "recusas": dict(sorted(p["recusas"].items(), key=lambda x: -x[1])),
                     "fechados": sum(1 for x in p["dados"].values() if x["f"]), "usados": len(usados)},
           "contas": contas, "escolhas": escolhas, "previsto": previsto_do_hist(est, p["ini"], p["fim"])}
    p["resultado"] = res
    p["rodadas"] = (p["rodadas"] + [{"de": p["ini"], "ate": p["fim"], "retorno": (contas.get("top5") or {}).get("retorno"),
                                     "previsto": res["previsto"].get("top5"), "comDados": len(p["dados"])}])[-MAX_RODADAS:]
    p["fase"] = "pronto"
    p["fila"], p["meta"], p["dados"] = [], {}, {}
    t5 = (contas.get("top5") or {}).get("retorno")
    ctx.log(f"  fora da amostra: pronto: {res['funil']['comDados']} cofres com dados; 5 melhores "
            f"{'—' if t5 is None else f'{t5 * 100:.1f}%'} (no período da escolha: {res['previsto'].get('top5')})")


def avancar(ctx, est, cache, erros):
    """Anda o que der nesta rodada (nas sobras de tempo)."""
    import cofres as C
    p = est.get("passado")
    agora = ctx.agora
    precisa_novo = not p or p.get("v") != VERSAO or (p["fase"] == "pronto" and agora - p["criado"] >= REFAZER_DIAS * DIA)
    if ctx.restante() < RESTANTE_MIN:
        if precisa_novo or (p and p["fase"] != "pronto"):
            ctx.log("  fora da amostra: pouco tempo, fica para a próxima")
        return
    if precisa_novo:
        linhas = (cache or {}).get("linhas")
        if not linhas:
            linhas = {}
            for x in ctx.cli.cofres():
                l = C.linha_lista(x)
                if l:
                    linhas[l["endereco"]] = l
        if not linhas:
            raise hl.Erro("a lista de cofres veio vazia")
        novo(ctx, est, linhas)
        p = est["passado"]
    if p["fase"] == "pronto":
        return
    prazo = time.monotonic() + min(TEMPO_MAX, ctx.restante() - RESTANTE_MIN)
    n0 = p["i"]
    if p["fase"] == "detalhar":
        while p["i"] < len(p["fila"]) and time.monotonic() < prazo:
            a = p["fila"][p["i"]]
            try:
                m = _detalhar(ctx, C, p, a)
            except hl.Erro as e:
                m = "sem dados na corretora"
                erros.append(f"fora da amostra {C.curto(a)}: {e}")
            p["i"] += 1
            if m:
                p["recusas"][m] = p["recusas"].get(m, 0) + 1
        if p["i"] >= len(p["fila"]):
            p["fase"] = "simular"
    if p["fase"] == "simular":
        fechar(ctx, C, p, est)
    elif p["i"] > n0:
        ctx.log(f"  fora da amostra: {p['i']} de {len(p['fila'])} cofres detalhados ({len(p['dados'])} com dados)")


def _met(c, ctx):
    cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}
    try:
        return metricas(c, cdi, cdi_ano_da_serie(cdi, CDI_PADRAO))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return None


def resumo(est, ctx):
    """O `passado` do cofres.json: {aproximado, andamento, resultado, rodadas, proximo} (FORMATO.md)."""
    p = est.get("passado")
    if not p:
        return None
    andamento = None
    if p["fase"] != "pronto":
        andamento = {"fase": p["fase"], "de": p["ini"], "universo": len(p["fila"]), "detalhados": p["i"],
                     "comDados": len(p["dados"]), "criado": p["criado"]}
    res = p.get("resultado")
    if res:
        res = {**res, "contas": {k: {**c, "metricas": _met(c, ctx)} for k, c in res["contas"].items()}}
    return {"aproximado": True, "semanas": SEMANAS, "andamento": andamento, "resultado": res,
            "rodadas": p.get("rodadas") or [], "proximo": p["criado"] + REFAZER_DIAS * DIA if p["fase"] == "pronto" else None}
