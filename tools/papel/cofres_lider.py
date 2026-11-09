"""Cofres: o cofre × copiar o líder no papel (pedido do Alediov, 09/11/2026; formato em FORMATO.md, "Cofres").

Pergunta: vale pagar 10% do lucro ao líder ou seria melhor copiar as operações dele? Para os 5 melhores cofres de agora
(a ordem da regra), cada um ganha uma conta de US$ 1.000 que copia NO PAPEL as operações do cofre desde o dia em que
começamos a acompanhá-lo (o mesmo dia em que começa a conta própria do cofre, o `item`), como no copy trading
(`tools/mercado/sim.py`): proporcional 1×, 1 minuto de atraso, taxa de 0,045%, deslize, financiamento de hora em hora,
margem isolada. O tamanho é proporcional ao patrimônio do cofre (`accountValueHistory` do vaultDetails).

As operações são as do PRÓPRIO cofre (o endereço do cofre nas execuções: é onde o líder opera o dinheiro dos
depositantes). A carteira pessoal do líder (`leader`) costuma ser outra coisa (às vezes nem opera); ela vai junto na
saída só como informação. Só perpétuos da Hyperliquid entram (`copiavel`): à vista e outros dex ficam de fora, e isso é
uma diferença que a comparação mostra.

Anda a cada rodada a partir de um cursor (as execuções novas desde a última vez), com velas de 15 min só das moedas que
aparecem; um cofre que fica para a próxima rodada (tempo curto) alcança depois. Cofre que deixa os 5 melhores sai da
comparação (o último resultado fica em `saidos`, os 10 mais recentes).
"""
from __future__ import annotations

import datetime as dt
import time

import hl
from conta import CAPITAL, cdi_ano_da_serie, dia_de, metricas
from sim import Conta, Mercado, Patrimonio, Velas, operacoes_da_carteira, simular

ATRASO = 60_000
ALAV = 1
INTERVALO = "15m"
PASSO = 900_000
MAX_FILLS = 4000
TEMPO_MAX = 120          # s por rodada
RESTANTE_MIN = 300       # s: com menos que isso na rodada, fica para a próxima
MAX_SAIDOS = 10
CDI_PADRAO = 0.149


def _curto(e):
    return f"{e[:6]}…{e[-4:]}" if isinstance(e, str) and len(e) > 12 else str(e)


def _av_do_cofre(det):
    """Patrimônio do cofre ao longo do tempo (as janelas mais finas por cima das grossas)."""
    pts = {}
    for nome in ("allTime", "month", "week", "day"):
        for par in (det or {}).get("portfolio") or []:
            if isinstance(par, (list, tuple)) and len(par) == 2 and par[0] == nome and isinstance(par[1], dict):
                for p in par[1].get("accountValueHistory") or []:
                    try:
                        pts[int(p[0])] = float(p[1])
                    except (TypeError, ValueError, IndexError):
                        pass
    return sorted(pts.items())


def _conta_papel(r, inicio):
    """O resumo do sim.py no formato das contas do papel."""
    return {"inicio": inicio, "serie": r["serie"], "retorno": r["retorno"], "piorQueda": r["piorQueda"], "ops": r["ops"],
            "taxas": r["taxas"], "liquidacoes": r["liquidacoes"][-10:], "nLiq": r["nLiq"],
            "extra": {"financiamento": r.get("funding"), "posicoes": len(r.get("posicoes") or [])},
            **({"acerto": r["acerto"]} if r.get("acerto") is not None else {})}


def avancar(ctx, est, alvos, dets, erros):
    """Anda as cópias dos `alvos` (os 5 melhores de agora) até agora, no tempo que sobrar."""
    cli, agora, log, cof = ctx.cli, ctx.agora, ctx.log, est.get("cofres") or {}
    L = est.setdefault("lider", {})
    for a in list(L):
        if a not in alvos:
            x = L.pop(a)
            if x.get("resumo"):
                saidos = [s for s in est.get("liderSaidos") or [] if s["endereco"] != a]
                est["liderSaidos"] = (saidos + [{"endereco": a, "nome": x.get("nome"), "desde": x["desde"], "saiu": agora,
                                                 "copia": x["resumo"], "cofre": conta_do_cofre(cof.get(a), x["desde"])}])[-MAX_SAIDOS:]
    for a in alvos:
        c = cof.get(a)
        if a not in L and c and a in dets:
            L[a] = {"desde": c["desde"], "cursor": c["desde"], "nome": c.get("nome"),
                    "lider": str(dets[a].get("leader") or "").lower() or None,
                    "conta": Conta(ALAV, ATRASO, CAPITAL, c["desde"]).para_json()}
    if ctx.restante() < RESTANTE_MIN:
        log("  cofre × líder: pouco tempo, fica para a próxima")
        return
    prazo = time.monotonic() + min(TEMPO_MAX, ctx.restante() - RESTANTE_MIN)
    velas, fund, desde_v = {}, {}, {}
    for a in sorted(L, key=lambda a: L[a]["cursor"]):
        if time.monotonic() > prazo:
            log("  cofre × líder: o tempo acabou; os outros alcançam na próxima")
            break
        x = L[a]
        if a in cof:
            x["nome"] = cof[a].get("nome") or x.get("nome")
        conta = Conta.de_json(x["conta"])
        try:
            fills = cli.execucoes_entre(a, x["cursor"] + 1, agora, maximo=MAX_FILLS)
        except hl.Erro as e:
            erros.append(f"execuções do cofre {_curto(a)}: {e}")
            continue
        ops = [o for o in operacoes_da_carteira(fills) if o["t"] > x["cursor"] and o["t"] + ATRASO <= agora]
        x["muitas"] = len(fills) >= MAX_FILLS
        moedas = {o["moeda"] for o in ops} | set(conta.pos)
        ini = min(x["cursor"], conta.t) - 2 * PASSO
        falhou = False
        for m in moedas:
            if m in velas and desde_v[m] <= ini:
                continue
            try:
                v = Velas.da_api(cli.velas(m, INTERVALO, ini, agora))
                f = cli.financiamento(m, ini, agora)
            except hl.Erro as e:
                erros.append(f"preços de {m}: {e}")
                falhou = True
                break
            velas[m] = v
            fund[m] = [(int(y["time"]), float(y["fundingRate"])) for y in f]
            desde_v[m] = ini
        if falhou:
            continue
        merc = Mercado({m: velas[m] for m in moedas if m in velas}, {m: fund[m] for m in moedas if m in fund}, {})
        d = dets.get(a)
        eq = _av_do_cofre(d) if d else []
        simular(ops, Patrimonio(eq or [(agora, 1.0)]), merc, [conta], agora)
        x["cursor"] = max(x["cursor"], agora - ATRASO)
        x["conta"] = conta.para_json()
        x["resumo"] = _conta_papel(conta.resumo(merc, agora), x["desde"])
        x["ops"] = conta.ops
        x["em"] = agora
        if d and d.get("leader"):
            x["lider"] = str(d["leader"]).lower()
    log(f"  cofre × líder: {sum(1 for a in L if L[a].get('em') == agora)} de {len(L)} cofres em dia")


def media(contas, de, ate):
    """US$ 1.000 em cada conta, juntas (a soma ÷ o número de contas); antes do 1º ponto de cada uma, US$ 1.000."""
    if not contas:
        return None
    mapas = [dict((d, v) for d, v in c["serie"]) for c in contas]
    out, d = [], dt.date.fromisoformat(de)
    fim = dt.date.fromisoformat(ate)
    ult = [CAPITAL] * len(mapas)
    while d <= fim:
        k = d.isoformat()
        for i, m in enumerate(mapas):
            if k in m:
                ult[i] = m[k]
        out.append([k, round(sum(ult) / len(ult), 2)])
        d += dt.timedelta(days=1)
    pico, queda = CAPITAL, 0.0
    for _, v in out:
        pico = max(pico, v)
        queda = max(queda, 1 - v / pico)
    return {"inicio": min(c["inicio"] for c in contas), "serie": out, "retorno": round(out[-1][1] / CAPITAL - 1, 6),
            "piorQueda": round(queda, 6), "ops": sum(c.get("ops") or 0 for c in contas),
            "taxas": round(sum(c.get("taxas") or 0 for c in contas), 4), "liquidacoes": [],
            "nLiq": sum(c.get("nLiq") or 0 for c in contas)}


def _met(c, ctx):
    if not c or not c.get("serie"):
        return c
    cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}
    try:
        c["metricas"] = metricas(c, cdi, cdi_ano_da_serie(cdi, CDI_PADRAO))
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        c["metricas"] = None
    return c


def conta_do_cofre(c, desde):
    """A conta própria do cofre (o item: US$ 1.000 só nele, já sem a comissão) no formato das contas."""
    from conta import Curva
    cv = Curva.de_json((c or {}).get("curva"))
    if not cv:
        return None
    r = cv.resumo()
    return {k: r[k] for k in ("inicio", "serie", "retorno", "piorQueda", "ops", "taxas", "liquidacoes", "nLiq")}


def saida(est, cof, ctx):
    """O `lider` do cofres.json: por cofre o cofre × a cópia e, no total, as duas juntas (US$ 1.000 em cada)."""
    L = est.get("lider") or {}
    linhas = []
    for a, x in sorted(L.items(), key=lambda kv: kv[1]["desde"]):
        if not x.get("resumo"):
            continue
        cofre = conta_do_cofre(cof.get(a), x["desde"])
        copia = dict(x["resumo"])
        if not cofre:
            continue
        linhas.append({"endereco": a, "nome": x.get("nome") or _curto(a), "desde": x["desde"], "em": x.get("em"),
                       "lider": x.get("lider"), "fonte": "operações do próprio cofre", "muitas": bool(x.get("muitas")),
                       "cofre": _met(cofre, ctx), "copia": _met(copia, ctx),
                       "diferenca": round(copia["retorno"] - cofre["retorno"], 6)})
    tot = None
    if linhas:
        de = min(dia_de(l["desde"]) for l in linhas)
        ate = dia_de(ctx.agora)
        cofre_t = media([l["cofre"] for l in linhas], de, ate)
        copia_t = media([l["copia"] for l in linhas], de, ate)
        tot = {"cofre": _met(cofre_t, ctx), "copia": _met(copia_t, ctx),
               "diferenca": round(copia_t["retorno"] - cofre_t["retorno"], 6), "n": len(linhas),
               "copiaGanhou": sum(1 for l in linhas if l["diferenca"] > 0)}
    saidos = [{**s, "copia": _met(dict(s["copia"]), ctx), "cofre": _met(dict(s["cofre"]), ctx) if s.get("cofre") else None,
               "diferenca": round(s["copia"]["retorno"] - s["cofre"]["retorno"], 6) if s.get("cofre") else None}
              for s in (est.get("liderSaidos") or []) if s.get("copia")]
    return {"atraso": ATRASO // 60_000, "alav": ALAV, "cofres": linhas, "total": tot, "saidos": saidos[-MAX_SAIDOS:]}
