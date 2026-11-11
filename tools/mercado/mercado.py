"""Testes de mercado do Órbita: cópia de carteiras da Hyperliquid NO PAPEL (saldo fictício; nenhuma ordem, nenhuma
conta, nenhuma chave). Roda no GitHub Actions (`.github/workflows/mercado.yml`) a cada 2 h e grava no ramo órfão
`mercado`: `estado.json` (o que a próxima rodada precisa), `resumo.json` (o que o app lê, aba Finanças → Testes) e
`log.txt` (as últimas rodadas). Só dados públicos.

Uma rodada:
1. ao vivo: para cada carteira seguida, as execuções novas desde o cursor (até agora − 8 min, para as velas de 1 min do
   atraso de 5 min já existirem); as velas e o financiamento das moedas envolvidas; cada uma das 18 contas fictícias
   (`combos()`: 1×, 3× e 5× com 1 min, o controle 3× com 5 min e as versões, todas com 1 min) copia e anda até o fim da
   janela (sim.py); e a conta do Consenso (agregadas.py), que só entra quando 2+ carteiras estão do mesmo lado;
2. uma vez por semana (ou com menos de 20 carteiras): a escolha (carteiras.py), com o teste no período da escolha das
   candidatas (as execuções dos últimos 30 dias, velas de 15 min); as que já estão sendo seguidas ficam pelo menos 4
   semanas;
3. os perfis e a reavaliação do risco (aos poucos), as carteiras de carteiras (As 5 melhores, Só robôs, Só pessoas) e,
   com o tempo que sobrar, o teste no passado fora da amostra (passado.py, em várias rodadas);
4. as referências: comprar e segurar bitcoin (velas diárias) e o CDI (série 12 do Banco Central; sem ela, a taxa fixa).

Uso: python3 tools/mercado/mercado.py --dados <pasta do ramo> [--escolher] [--exemplos] [--agora <ms>]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import traceback
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agregadas as AG  # noqa: E402
import contrario as CT  # noqa: E402
import carteiras as K  # noqa: E402
import hl  # noqa: E402
import imitador as IM  # noqa: E402
import passado as PS  # noqa: E402
import perfil as PF  # noqa: E402
from sim import (Conta, Mercado, Patrimonio, Velas, dia_de, operacoes_da_carteira, simular)  # noqa: E402

# as métricas comuns de todas as formas (tools/papel/conta.py); no fim do caminho, para não esconder o falso.py daqui
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "papel"))
try:
    from conta import cdi_ano_da_serie, metricas  # noqa: E402
except ImportError:  # pragma: no cover (checkout sem tools/papel)
    metricas = None

    def cdi_ano_da_serie(cdi, padrao):
        return padrao

MIN = 60_000
HORA = 3_600_000
DIA = 86_400_000
ALAVANCAGENS = (1, 3, 5)   # 09/11/2026: o 10× saiu (quebrava: −16% a −20% em média, 2 a 4 liquidadas por carteira)
ATRASOS_MIN = (1, 5)       # o de 5 min ficou só no controle 3× (CONTROLE_ATRASO): dava quase igual ao de 1 min
PADRAO = "3x1"
CAPITAL = 1000.0
ALVO = 30          # carteiras seguidas
MINIMO = 20        # abaixo disso, tenta escolher de novo (no máximo a cada 6 h)
ANALISAR = 80      # candidatas novas analisadas por escolha (as melhores do pré-filtro)
FICA_SEMANAS = 4
JANELA_HIST = 30   # dias do teste no histórico
CDI_ANO = 0.149
VERSAO = 1
HIST_VERSAO = 3  # o teste no período da escolha com as versões de 09/11/2026 (parar ao cair 20/25/30%)
CONTROLE_ATRASO = "3x5"  # o único com 5 min de atraso, para ver se o atraso pesa
PERFIS_POR_RODADA = 3  # perfis (com o imitador) refeitos por rodada; cada carteira no máximo 1× por dia


# variantes, nos dois atrasos, cada uma com as suas alavancagens (chaves "3x1s", "5x5a2", "10x1f"…), ao lado das 8 de
# sempre ("3x1"…). 02/11/2026, 19h08: "s" saídas de segurança, "l" ordem limite (melhor caso), "m" só as moedas boas,
# com 3× e 5×. 19h43: "a2"/"a3" amplificada (a fração dela × 2 e × 3) com 5× e 10× (com 3× de conta, × 3 bateria no
# teto quase sempre e ficaria igual a × 2) e "f" entrada fixa (US$ 50 de margem por operação nova) com 2×, 5× e 10×.
# 09/11/2026 (enxugar, pedido do Alediov): sem 10× e todas as versões só com 1 min; "p20"/"p25"/"p30" param de copiar
# quem afunda (largam a carteira quando a cópia cai 20/25/30% do topo).
VARIANTES = {"s": (3, 5), "l": (3, 5), "m": (3, 5), "a2": (5,), "a3": (5,), "f": (2, 5), "p20": (3,), "p25": (3, 5),
             "p30": (3,)}
ALAV_VARIANTES = (3, 5)
NOME_VARIANTE = {"": "todas as operações", "s": "saídas de segurança", "l": "ordem limite", "m": "só as moedas boas",
                 "a2": "amplificada × 2", "a3": "amplificada × 3", "f": "entrada fixa de US$ 50",
                 "p20": "para ao cair 20%", "p25": "para ao cair 25%", "p30": "para ao cair 30%"}


def combos(variantes=True):
    out = [f"{a}x1" for a in ALAVANCAGENS] + [CONTROLE_ATRASO]
    if variantes:
        out += [f"{a}x1{v}" for v, alavs in VARIANTES.items() for a in alavs]
    return out


def enxugar(est):
    """As contas que saíram em 09/11/2026 (10×, 5 min fora do controle) somem do estado; as que ficam seguem iguais."""
    ks = set(combos())
    n = 0
    for c in est["carteiras"].values():
        for campo in ("contas", "resumo", "historico"):
            d = c.get(campo)
            if isinstance(d, dict):
                fora = [k for k in d if k not in ks]
                for k in fora:
                    del d[k]
                n += len(fora)
    return n


def partes_chave(chave):
    m = re.fullmatch(r"(\d+)x(\d+)([a-z]\d*)?", chave)
    return int(m.group(1)), int(m.group(2)), m.group(3) or ""


def nova_conta(chave, inicio, moedas=None):
    a, d, v = partes_chave(chave)
    return Conta(a, d * MIN, CAPITAL, inicio, v, moedas if v == "m" else None)


def garantir_contas(cli, c, log, cache=None, max_lev=None, prazo=None):
    """Carteiras seguidas antes das variantes: as contas que faltam começam agora (no cursor); as moedas boas e o teste
    no histórico das variantes novas saem das execuções dos 30 dias antes do início da cópia (uma vez)."""
    falta_hist = [k for k in combos() if not k.endswith("m") and k not in (c.get("historico") or {})]
    fills = None
    if c.get("moedasBoas") is None or (falta_hist and cache is not None):
        try:
            fills = cli.execucoes_entre(c["endereco"], c["desde"] - JANELA_HIST * DIA, c["desde"] - 1, maximo=2000)
        except hl.Erro as er:
            log(f"  {curto(c['endereco'])}: execuções de antes da cópia: {er}")
            return
    if c.get("moedasBoas") is None:
        c["moedasBoas"] = K.moedas_boas(fills, c["desde"])
    if falta_hist and fills is not None and cache is not None and (prazo is None or time.monotonic() < prazo):
        h = teste_historico(cli, log, c.get("ranking") or {"conta": 0}, fills, c.get("eq"), c["desde"], c["desde"],
                            cache, max_lev or {}, prazo or time.monotonic() + 60)
        c["historico"] = {**(h or {}), **(c.get("historico") or {})}
        c["histVersao"] = HIST_VERSAO  # tentou: não busca de novo, mesmo sem operações no período
    for k in combos():
        if k not in c["contas"]:
            c["contas"][k] = nova_conta(k, c["cursor"], [m for m, *_ in c["moedasBoas"]]).para_json()


def curto(e):
    return f"{e[:6]}…{e[-4:]}"


def iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Log:
    def __init__(self, quieto=False):
        self.linhas, self.quieto = [], quieto

    def __call__(self, *a):
        s = " ".join(str(x) for x in a)
        if not self.quieto:
            print(s, flush=True)
        self.linhas.append(s)


# ---------------------------------------------------------------------------------------------- dados de mercado
class Precos:
    """Velas e financiamento por moeda, buscados uma vez por rodada."""

    def __init__(self, cli, log, agora):
        self.cli, self.log, self.agora = cli, log, agora
        self.velas, self.funding, self.erros = {}, {}, []

    def garantir(self, moeda, ini, fim, intervalo=None, financiamento=True):
        iv = intervalo or hl.intervalo_para(ini, fim, self.agora)
        passo = hl.INTERVALO_MS[iv]
        ini = max(ini - 2 * passo, self.agora - passo * (hl.MAX_VELAS - 10))
        try:
            v = Velas.da_api(self.cli.velas(moeda, iv, ini, fim))
            self.velas[moeda] = self.velas[moeda].juntar(v) if moeda in self.velas else v
            f = self.cli.financiamento(moeda, ini, fim) if financiamento else []
            self.funding[moeda] = sorted(set(self.funding.get(moeda, [])) | {(int(x["time"]), float(x["fundingRate"])) for x in f})
        except hl.Erro as e:
            self.erros.append(f"{moeda}: {e}")
            self.log(f"  sem preços de {moeda}: {e}")

    def mercado(self, max_lev):
        return Mercado(self.velas, self.funding, max_lev)


def max_lev_da_meta(meta):
    out = {}
    for u in (meta or {}).get("universe", []):
        if u.get("name") and not u.get("isDelisted"):
            out[u["name"]] = int(u.get("maxLeverage") or 20)
    return out


def eq_do_portfolio(p):
    """Valor da conta ao longo do tempo pelo `portfolio` (perpétuos se houver; semana + mês, para ter densidade)."""
    d = {k: v for k, v in (p or [])}
    pts = {}
    for nome in ("perpMonth", "perpWeek") if "perpMonth" in d else ("month", "week"):
        for t, v in (d.get(nome) or {}).get("accountValueHistory", []):
            pts[int(t)] = float(v)
    return sorted(pts.items())


def pnl_do_portfolio(p):
    """Lucro acumulado ao longo do mês (perpétuos se houver) pelo `portfolio`."""
    d = {k: v for k, v in (p or [])}
    return [(int(t), float(v)) for t, v in (d.get("perpMonth") or d.get("month") or {}).get("pnlHistory", [])]


def valor_conta(estado):
    try:
        return float(estado["marginSummary"]["accountValue"])
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------------------------- estado
def estado_novo():
    return {"v": VERSAO, "inicio": None, "ultimaEscolha": None, "tentouEscolha": None, "maxLev": {}, "carteiras": {},
            "encerradas": [], "rodadas": [], "btc": {}, "cdi": {}, "funil": None, "recusadas": {},
            "recusaMotivo": {}, "analisadasSemana": {}, "banco": {}, "consenso": None, "passado": None}


def carregar(pasta):
    try:
        with open(os.path.join(pasta, "estado.json")) as f:
            e = json.load(f)
        return {**estado_novo(), **e} if e.get("v") == VERSAO else estado_novo()
    except (OSError, ValueError):
        return estado_novo()


# ---------------------------------------------------------------------------------------------- ao vivo
def ao_vivo(cli, est, fim_ops, ate, agora, log, prazo):
    """Execuções novas de cada carteira (até `fim_ops`) e as contas levadas até `ate`."""
    novas, precisa, cache_hist = {}, {}, None
    for e, c in est["carteiras"].items():
        if time.monotonic() > prazo:
            log("  tempo da rodada esgotado nas execuções")
            break
        if c["cursor"] >= fim_ops:
            continue
        falta_hist = c.get("histVersao") != HIST_VERSAO and any(k not in (c.get("historico") or {}) for k in combos() if not k.endswith("m"))
        if len(c["contas"]) < len(combos()) or (falta_hist and time.monotonic() < prazo - 4 * 60):
            if cache_hist is None:
                cache_hist = Precos(cli, log, agora)
            garantir_contas(cli, c, log, cache_hist, est["maxLev"], prazo - 4 * 60)
        try:
            fills = cli.execucoes_entre(e, c["cursor"] + 1, fim_ops)
        except hl.Erro as er:
            log(f"  {curto(e)}: {er}")
            continue
        ops = operacoes_da_carteira(fills)
        if ops:
            try:
                v = valor_conta(cli.estado(e))
                if v:
                    c["eq"] = (c.get("eq") or [])[-80:] + [[agora, v]]
            except hl.Erro as er:
                log(f"  {curto(e)}: patrimônio: {er}")
        novas[e] = ops
        contas = [Conta.de_json(x) for x in c["contas"].values()]
        for op in ops:
            precisa.setdefault(op["moeda"], set()).add(op["t"])
        for ct in contas:
            for m in ct.pos:
                precisa.setdefault(m, set()).add(ct.t)
    cons = AG.consenso_conta(est, fim_ops)
    for m in cons.pos:
        precisa.setdefault(m, set()).add(cons.t)
    # o Ao contrário (contrario.py, 11/11/2026): as carteiras que perdem, copiadas também do outro lado
    try:
        novas_ct, precisa_ct = CT.coletar(cli, est, fim_ops, agora, log, prazo, valor_conta)
    except Exception as er:  # noqa: BLE001
        novas_ct, precisa_ct = {}, {}
        log(f"  ao contrário: {er}")
    for m, ts in precisa_ct.items():
        precisa.setdefault(m, set()).update(ts)
    pr = Precos(cli, log, agora)
    for m, ts in sorted(precisa.items()):
        if time.monotonic() > prazo:
            break
        pr.garantir(m, min(ts) - 2 * MIN, ate)
    merc = pr.mercado(est["maxLev"])
    n = 0
    for e, ops in novas.items():
        c = est["carteiras"][e]
        pat = Patrimonio(c.get("eq") or [])
        contas = {k: Conta.de_json(x) for k, x in c["contas"].items()}
        simular(ops, pat, merc, list(contas.values()), ate)
        c["contas"] = {k: x.para_json() for k, x in contas.items()}
        c["cursor"] = fim_ops
        c["resumo"] = {k: x.resumo(merc, ate) for k, x in contas.items()}
        n += len(ops)
    # carteiras sem nada novo (ou que não deu para ler): o resumo continua com o último cálculo
    try:
        AG.consenso_rodada(est, cons, novas, merc, ate)
    except Exception as er:  # noqa: BLE001
        log(f"  consenso: {er}")
        log(traceback.format_exc())
    try:
        nct = CT.simular_rodada(est, novas_ct, merc, ate, agora, fim_ops)
        if nct:
            log(f"  ao contrário: {nct} operações")
    except Exception as er:  # noqa: BLE001
        log(f"  ao contrário: {er}")
        log(traceback.format_exc())
    return n, pr.erros


# ---------------------------------------------------------------------------------------------- escolha
def teste_historico(cli, log, l, fills, eq, agora, ate, cache, max_lev, prazo, intervalo="15m"):
    """A cópia nos 30 dias antes (velas de 15 min; o teste fora da amostra usa 1 h). Sem a variante "m": as moedas boas
    saem deste mesmo período. É o "período da escolha": otimista, porque a carteira foi escolhida por ter ido bem nele."""
    ini = agora - JANELA_HIST * DIA
    ops = [o for o in operacoes_da_carteira(fills) if ini <= o["t"] <= ate - 5 * MIN]
    if not ops:
        return None
    for m in sorted({o["moeda"] for o in ops}):
        if m not in cache.velas and time.monotonic() < prazo:
            cache.garantir(m, ini - DIA, ate, intervalo)
    merc = cache.mercado(max_lev)
    contas = {k: nova_conta(k, ops[0]["t"] - 1) for k in combos() if not k.endswith("m")}
    simular(ops, Patrimonio(eq or [(agora, l["conta"])]), merc, list(contas.values()), ate)
    out = {}
    for k, c in contas.items():
        r = c.resumo(merc, ate)
        out[k] = {"retorno": r["retorno"], "piorQueda": r["piorQueda"], "ops": r["ops"], "acerto": r["acerto"],
                  "gm": r.get("gm"), "pm": r.get("pm"),
                  "nLiq": r["nLiq"], "taxas": r["taxas"], "funding": r["funding"], "serie": r["serie"],
                  "de": ops[0]["t"], "ate": ate, "resolucao": intervalo, **({"saidas": r["saidas"]} if "saidas" in r else {}),
                  **({"parou": r["parou"]} if r.get("parou") else {})}
    return out


def calcular_perfil(fills, eq, merc, ini, fim, serie_copia=None):
    """O perfil (perfil.py) e, para os robôs, o imitador (imitador.py) pelas execuções [ini, fim] e as velas de 15 min."""
    pat = Patrimonio(eq or [])
    p, trades = PF.perfil([f for f in fills if ini <= int(f["time"]) <= fim], eq=pat.em if pat.t else None,
                          preco=merc.preco)
    trades = [n for n in trades if n["t1"] <= fim]
    im = IM.imitar(trades, p["parametros"], merc, ini, fim, p["robo"]["nota"])
    if im.get("regras"):
        im["regrasTexto"] = IM.texto_regras(im["regras"])
        if serie_copia:
            im["copiaTeste"] = IM.retorno_entre(serie_copia, dia_de(im["teste"]["de"]), dia_de(im["teste"]["ate"]))
    p["imitador"] = im
    return p


def atualizar_perfis(cli, est, agora, log, prazo, maximo=PERFIS_POR_RODADA):
    """Refaz o perfil das carteiras seguidas sem perfil ou com ele há mais de 1 dia (as mais antigas primeiro), pelas
    execuções dos últimos 30 dias, enquanto houver tempo. O imitador anda junto: no máximo 1× por dia por carteira."""
    # sem risco (as escolhidas antes de 02/11/2026, 19h08) vêm primeiro: a reavaliação do risco anda junto (09/11/2026)
    velhas = sorted((c.get("risco") is not None, c.get("perfilEm") or 0, e) for e, c in est["carteiras"].items()
                    if not c.get("perfil") or (c.get("perfil") or {}).get("v") != PF.VERSAO
                    or agora - (c.get("perfilEm") or 0) >= DIA or c.get("risco") is None)
    feitas = 0
    cache = Precos(cli, log, agora)
    for _, _, e in velhas[:maximo]:
        if time.monotonic() > prazo:
            break
        c = est["carteiras"][e]
        ini = agora - JANELA_HIST * DIA
        try:
            fills = cli.execucoes_entre(e, ini, agora, maximo=2000)
            for m in sorted({f["coin"] for f in fills if K.copiavel(f.get("coin", ""))}):
                if m not in cache.velas and time.monotonic() < prazo:
                    cache.garantir(m, ini - DIA, agora, "15m", financiamento=False)
        except hl.Erro as er:
            log(f"  {curto(e)}: perfil: {er}")
            continue
        serie = ((c.get("resumo") or {}).get(PADRAO) or {}).get("serie") or ((c.get("historico") or {}).get(PADRAO) or {}).get("serie")
        if c.get("risco") is None:
            try:
                reavaliar_risco(cli, c, fills, cache, agora, log)
            except (hl.Erro, Exception) as er:  # noqa: BLE001
                log(f"  {curto(e)}: risco: {er}")
        try:
            c["perfil"] = calcular_perfil(fills, c.get("eq"), cache.mercado(est["maxLev"]), ini, agora, serie)
            c["perfilEm"] = agora
            feitas += 1
        except Exception as er:  # noqa: BLE001
            log(f"  {curto(e)}: perfil falhou: {er}")
    if feitas:
        log(f"  perfis refeitos: {feitas}")
    return feitas


def reavaliar_risco(cli, c, fills, cache, agora, log):
    """As carteiras escolhidas antes da medida de risco: o risco pelas execuções dos últimos 30 dias (as do perfil) e a
    nota com o teste no período da escolha. Só ganha o alerta, nunca sai por isso (como as já seguidas na escolha)."""
    pf = cli.portfolio(c["endereco"])
    conta = (c.get("ranking") or {}).get("conta") or (c.get("eq") or [[0, 0]])[-1][1] or 0
    rk = K.risco(fills, conta, pnl_do_portfolio(pf), cache.velas, agora)
    if rk["recusa"]:
        rk["alertas"].insert(0, rk["recusa"])
    rk["recusa"] = None
    rk["reavaliado"] = agora
    c["risco"] = rk
    hist3 = ((c.get("historico") or {}).get(PADRAO) or {}).get("retorno")
    c["nota"] = K.nota_escolha(hist3, (c.get("medidas") or {}).get("passivoPct"), rk["alertas"])
    log(f"  {curto(c['endereco'])}: risco reavaliado ({len(rk['alertas'])} alertas), nota {c['nota']}")


def escolher(cli, est, agora, inicio_vivo, log, prazo):
    est["tentouEscolha"] = agora
    linhas = [K.linha_ranking(r) for r in cli.ranking()]
    por_end = {l["endereco"]: l for l in linhas}
    pre = K.pre_filtro(linhas)
    funil = {"ranking": len(linhas), "recusas": {}, "analisadas": 0, "aprovadas": 0}
    for _, m in pre:
        if m:
            funil["recusas"][m] = funil["recusas"].get(m, 0) + 1
    passam = sorted((l for l, m in pre if not m), key=K.nota_ranking, reverse=True)
    recusa_pre = {l["endereco"]: m for l, m in pre}
    funil["preFiltro"] = len(passam)
    # as seguidas há 4 semanas ou mais são reavaliadas; as mais novas ficam
    ficam, reavaliar = {}, []
    for e, c in est["carteiras"].items():
        if agora - c["desde"] < FICA_SEMANAS * 7 * DIA:
            ficam[e] = c
        else:
            reavaliar.append(e)
    cache = Precos(cli, log, agora)
    aprovadas = []

    def analisar(e, l, nova=True):
        # as execuções dos 30 dias (mais baratas que as 2.000 últimas); o papel (60 de peso) só de quem passou
        fills = cli.execucoes_entre(e, agora - JANELA_HIST * DIA, agora, maximo=2000)
        md = K.medidas(fills, agora)
        motivo = K.filtro_fino(md, "user")
        papel = None
        if not motivo:
            papel = cli.papel(e)
            motivo = K.filtro_fino(md, papel)
        funil["analisadas"] += 1
        est["analisadasSemana"][e] = agora
        if motivo:
            funil["recusas"][motivo] = funil["recusas"].get(motivo, 0) + 1
            est["recusadas"][e], est["recusaMotivo"][e] = agora, motivo
            return None
        pf = cli.portfolio(e)
        eq = eq_do_portfolio(pf)
        hist = teste_historico(cli, log, l, fills, eq, agora, inicio_vivo, cache, est["maxLev"], prazo)
        # contra o "quase nunca perde": recusa só nas novas; nas já seguidas, só o alerta
        rk = K.risco(fills, l["conta"], pnl_do_portfolio(pf), cache.velas, inicio_vivo)
        if rk["recusa"] and nova:
            funil["recusas"]["quase nunca perde"] = funil["recusas"].get("quase nunca perde", 0) + 1
            funil.setdefault("exemplos", {})[curto(e)] = rk["recusa"]
            est["recusadas"][e], est["recusaMotivo"][e] = agora, "quase nunca perde: " + rk["recusa"]
            return None
        if rk["recusa"]:
            rk["alertas"].insert(0, rk["recusa"])
        funil["aprovadas"] += 1
        boas = K.moedas_boas(fills, inicio_vivo)
        try:
            pf = calcular_perfil(fills, eq, cache.mercado(est["maxLev"]), agora - JANELA_HIST * DIA, inicio_vivo,
                                 ((hist or {}).get(PADRAO) or {}).get("serie"))
        except Exception as er:  # noqa: BLE001
            log(f"  {curto(e)}: perfil falhou: {er}")
            pf = None
        return {"l": l, "md": md, "papel": papel, "eq": eq[-80:], "hist": hist, "risco": rk, "boas": boas, "perfil": pf}

    for e in reavaliar:
        c = est["carteiras"][e]
        l = por_end.get(e)
        motivo = recusa_pre.get(e) if l else "saiu do ranking"
        r = None
        if not motivo and time.monotonic() < prazo:
            try:
                r = analisar(e, l, nova=False)
            except hl.Erro as er:
                log(f"  {curto(e)}: {er}")
                ficam[e] = c  # sem dados agora: fica
                continue
            motivo = None if r else "não passa mais nos filtros"
        if motivo:
            res = (c.get("resumo") or {}).get(PADRAO) or {}
            est["encerradas"] = (est["encerradas"] + [{"endereco": e, "desde": c["desde"], "ate": agora, "motivo": motivo,
                                                       "retorno": res.get("retorno")}])[-50:]
            log(f"  sai {curto(e)}: {motivo}")
        else:
            if r:
                c["ranking"], c["medidas"], c["risco"] = r["l"], r["md"], r["risco"]
                if r["perfil"]:
                    c["perfil"], c["perfilEm"] = r["perfil"], agora
            ficam[e] = c
    vagas = ALVO - len(ficam)
    est["recusadas"] = {e: t for e, t in est["recusadas"].items() if agora - t < 7 * DIA}
    est["recusaMotivo"] = {e: m for e, m in est["recusaMotivo"].items() if e in est["recusadas"]}
    est["analisadasSemana"] = {e: t for e, t in est["analisadasSemana"].items() if agora - t < 7 * DIA}
    esgotou = True
    for l in passam:
        if vagas <= 0 or len(aprovadas) >= max(vagas * 2, 10) or funil["analisadas"] >= ANALISAR + len(reavaliar):
            esgotou = vagas <= 0
            break
        if time.monotonic() > prazo:
            log("  tempo da rodada esgotado na escolha")
            esgotou = False
            break
        if l["endereco"] in ficam or l["endereco"] in est["recusadas"]:
            continue
        try:
            r = analisar(l["endereco"], l)
        except hl.Erro as er:
            log(f"  {curto(l['endereco'])}: {er}")
            continue
        if r:
            aprovadas.append(r)
    hist3 = lambda r: ((r["hist"] or {}).get(PADRAO) or {}).get("retorno")  # noqa: E731
    for r in aprovadas:
        r["nota"] = K.nota_escolha(hist3(r), r["md"].get("passivoPct"), r["risco"]["alertas"])
    aprovadas.sort(key=lambda r: r["nota"], reverse=True)
    for r in aprovadas[:max(0, vagas)]:
        e = r["l"]["endereco"]
        boas = [m for m, *_ in r["boas"]]
        ficam[e] = {"endereco": e, "desde": inicio_vivo, "cursor": inicio_vivo, "ranking": r["l"], "medidas": r["md"],
                    "papel": r["papel"], "eq": r["eq"], "historico": r["hist"], "histVersao": HIST_VERSAO,
                    "risco": r["risco"], "nota": r["nota"], "perfil": r["perfil"], "perfilEm": agora if r["perfil"] else None,
                    "moedasBoas": r["boas"], "motivos": K.motivos(r["l"], r["md"], hist3(r)),
                    "contas": {k: nova_conta(k, inicio_vivo, boas).para_json() for k in combos()}, "resumo": None}
        log(f"  entra {curto(e)}: {'; '.join(ficam[e]['motivos'][:2])}")
    est["carteiras"] = ficam
    funil["seguidas"] = len(ficam)
    funil["semana"] = len(est["analisadasSemana"])
    funil["em"] = agora
    est["funil"] = funil
    if len(ficam) >= MINIMO or esgotou:
        est["ultimaEscolha"] = agora
    if est["inicio"] is None and ficam:
        est["inicio"] = inicio_vivo
    log(f"  escolha: {funil['ranking']} no ranking, {funil['preFiltro']} no pré-filtro, {funil['analisadas']} analisadas "
        f"({funil['semana']} em 7 dias), {funil['aprovadas']} aprovadas; {len(ficam)} seguidas")


# ---------------------------------------------------------------------------------------------- referências
def referencias(cli, est, agora, log, cdi_ano, buscar_cdi=True):
    ini = (est["inicio"] or agora) - (JANELA_HIST + 5) * DIA
    try:
        for c in cli.velas("BTC", "1d", ini, agora):
            est["btc"][dia_de(int(c["T"]))] = float(c["c"])
    except hl.Erro as e:
        log(f"  bitcoin: {e}")
    fonte = "fixa"
    if buscar_cdi:
        a = dt.datetime.fromtimestamp(ini / 1000).strftime("%d/%m/%Y")
        b = dt.datetime.fromtimestamp(agora / 1000).strftime("%d/%m/%Y")
        url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial={a}&dataFinal={b}"
        erro = None
        for tentativa in range(3):  # o BC às vezes responde 304 sem corpo ou cai por segundos
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "orbita-testes/1", "Cache-Control": "no-cache",
                                                           "Pragma": "no-cache"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    for x in json.loads(r.read().decode()):
                        d, m, y = x["data"].split("/")
                        est["cdi"][f"{y}-{m}-{d}"] = float(x["valor"]) / 100
                fonte, erro = "bcb", None
                break
            except Exception as e:  # noqa: BLE001
                erro = e
                time.sleep(2 * (tentativa + 1))
        if erro is not None:
            log(f"  CDI do Banco Central: {erro}; ficam os dias já guardados e, depois deles, "
                f"{cdi_ano_da_serie(est['cdi'], cdi_ano) * 100:.2f}% ao ano")
    return fonte


def indice_cdi(est, de, ate, cdi_ano):
    """Índice diário do CDI (1 no 1º dia): a série do BC quando há; nos dias úteis sem ela, a taxa fixa."""
    out, v = [], 1.0
    d = dt.date.fromisoformat(de)
    fim = dt.date.fromisoformat(ate)
    diaria = (1 + cdi_ano) ** (1 / 252) - 1
    ultimo_bc = max(est["cdi"]) if est["cdi"] else ""
    while d <= fim:
        k = d.isoformat()
        out.append([k, round(v, 6)])
        if k in est["cdi"]:
            v *= 1 + est["cdi"][k]
        elif d.weekday() < 5 and k > ultimo_bc:
            v *= 1 + diaria
        d += dt.timedelta(days=1)
    return out


# ---------------------------------------------------------------------------------------------- resumo
def quarentena(est, maximo=30):
    """As recusadas dos últimos 7 dias (as mais recentes primeiro), com o motivo e até quando ficam de fora."""
    lista = sorted(est["recusadas"].items(), key=lambda x: -x[1])
    mot = est.get("recusaMotivo") or {}
    return {"n": len(lista), "lista": [{"curto": curto(e), "ate": t + 7 * DIA, "motivo": mot.get(e) or "recusada"}
                                       for e, t in lista[:maximo]]}


def selo_de(c):
    return PF.selo(c["perfil"]["robo"]["nota"]) if c.get("perfil") else K.selo(c.get("medidas"))


def montar_resumo(est, agora, fonte_cdi, cdi_ano, exemplo=False, rodada=None):
    taxa_cdi = cdi_ano_da_serie(est["cdi"], cdi_ano)

    def metricas_de(conta):
        if not metricas or not conta or not conta.get("serie"):
            return None
        try:
            return metricas(conta, est["cdi"], taxa_cdi)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            return None
    cart = []
    for e, c in est["carteiras"].items():
        l, md = c.get("ranking") or {}, c.get("medidas") or {}
        res = c.get("resumo") or {k: Conta.de_json(x).resumo(None, c["desde"]) for k, x in c["contas"].items()}
        if metricas:
            taxa = cdi_ano_da_serie(est["cdi"], cdi_ano)
            res = {k: ({**x, "metricas": metricas({**x, "inicio": c["desde"]}, est["cdi"], taxa)}
                       if isinstance(x, dict) and x.get("serie") else x) for k, x in res.items()}
        cart.append({
            "endereco": e, "curto": curto(e), "desde": c["desde"], "situacao": "seguindo", "motivos": c.get("motivos") or [],
            "conta": round(l.get("conta", 0)), "pnlMes": round((l.get("mes") or {}).get("pnl", 0)),
            "roiMes": round((l.get("mes") or {}).get("roi", 0), 4), "pnlTotal": round((l.get("total") or {}).get("pnl", 0)),
            "medidas": md, "aoVivo": res, "historico": c.get("historico") or {},
            "moedasBoas": c.get("moedasBoas"), "alertas": (c.get("risco") or {}).get("alertas") or [],
            "risco": {k: v for k, v in (c.get("risco") or {}).items() if k not in ("alertas", "recusa")} or None,
            "nota": c.get("nota"), "perfil": c.get("perfil"),
            "selo": selo_de(c),
        })
    chave = lambda x: (x["aoVivo"].get(PADRAO) or {}).get("retorno", 0)  # noqa: E731
    cart.sort(key=chave, reverse=True)
    de = dia_de((est["inicio"] or agora) - (JANELA_HIST + 2) * DIA)
    return {
        "v": VERSAO, "exemplo": exemplo, "geradoEm": iso(agora), "agora": agora, "inicio": est["inicio"],
        "proximaEscolha": (est["ultimaEscolha"] or agora) + 7 * DIA,
        "config": {"capital": CAPITAL, "alavancagens": list(ALAVANCAGENS), "atrasos": list(ATRASOS_MIN),
                   "combos": combos(), "controleAtraso": CONTROLE_ATRASO,
                   "variantes": {v: {"nome": NOME_VARIANTE[v], "alavancagens": list(a)} for v, a in VARIANTES.items()},
                   "margemFixa": 50,
                   "saidas": {"dias": 3, "stop": 0.05}, "taxaLivro": 0.00015, "minOpsMoeda": K.MIN_OPS_MOEDA, "analisar": ANALISAR,
                   "risco": K.RISCO,
                   "padrao": PADRAO, "taxa": 0.00045, "deslize": {"BTC": 0.0005, "ETH": 0.0005, "outras": 0.001},
                   "criterios": K.CRITERIOS, "frequencia": "a cada 2 h", "janelaHistorico": JANELA_HIST},
        "referencias": {"btc": sorted([d, round(v, 2)] for d, v in est["btc"].items() if d >= de),
                        "cdi": indice_cdi(est, de, dia_de(agora), cdi_ano), "cdiAno": cdi_ano, "cdiFonte": fonte_cdi},
        "ranking": [c["endereco"] for c in cart],
        "carteiras": cart, "encerradas": [{**x, "curto": curto(x["endereco"])} for x in est["encerradas"][-20:]],
        "quarentena": quarentena(est), "funil": est.get("funil"), "rodada": rodada,
        "agregadas": AG.resumo_agregadas(est, agora, metricas_de),
        "passado": PS.resumo(est, metricas_de),
        "contrario": CT.resumo(est, agora, metricas_de),
    }


# ---------------------------------------------------------------------------------------------- rodada
def rodada(cli, pasta, agora=None, forcar_escolha=False, exemplo=False, prazo_min=13.0, cdi_ano=CDI_ANO,
           buscar_cdi=True, log=None, passado_min=7.0):
    log = log or Log()
    t0 = time.monotonic()
    prazo = t0 + prazo_min * 60
    agora = int(agora or time.time() * 1000)
    ate = agora - 3 * MIN                 # velas de 1 min já fechadas
    fim_ops = ate - max(ATRASOS_MIN) * MIN  # operação + o maior atraso cabe na janela
    est = carregar(pasta)
    log(f"rodada {iso(agora)} · {len(est['carteiras'])} carteiras seguidas")
    tirou = enxugar(est)
    if tirou:
        log(f"  contas que saíram (10×, 5 min fora do controle): {tirou}")
    erros = []
    if not est["maxLev"] or forcar_escolha or not est["ultimaEscolha"] or agora - est["ultimaEscolha"] >= 7 * DIA:
        try:
            est["maxLev"] = max_lev_da_meta(cli.meta()) or est["maxLev"]
        except hl.Erro as e:
            erros.append(f"meta: {e}")
    n, er = ao_vivo(cli, est, fim_ops, ate, agora, log, prazo)
    erros += er
    log(f"  ao vivo: {n} operações novas copiadas")
    precisa = (forcar_escolha or not est["ultimaEscolha"] or agora - est["ultimaEscolha"] >= 7 * DIA
               or (len(est["carteiras"]) < MINIMO and agora - (est["tentouEscolha"] or 0) >= DIA))
    if precisa:
        try:
            escolher(cli, est, agora, fim_ops, log, prazo)
        except Exception as e:  # noqa: BLE001
            erros.append(f"escolha: {e}")
            log(traceback.format_exc())
    if CT.precisa_escolher(est, agora) and time.monotonic() < prazo - 4 * 60:
        try:
            CT.escolher(cli, est, agora, fim_ops, log, prazo - 3 * 60, eq_do_portfolio)
        except Exception as e:  # noqa: BLE001
            erros.append(f"ao contrário: {e}")
            log(traceback.format_exc())
    if time.monotonic() < prazo - 3 * 60:
        try:
            atualizar_perfis(cli, est, agora, log, prazo - 3 * 60)
        except Exception as e:  # noqa: BLE001
            erros.append(f"perfis: {e}")
            log(traceback.format_exc())
    try:
        AG.atualizar(est, agora, selo_de)
    except Exception as e:  # noqa: BLE001
        erros.append(f"agregadas: {e}")
        log(traceback.format_exc())
    if time.monotonic() < prazo - 3 * 60:
        try:
            PS.avancar(cli, est, agora, log, min(prazo - 3 * 60, time.monotonic() + passado_min * 60), sys.modules[__name__])
        except Exception as e:  # noqa: BLE001
            erros.append(f"passado: {e}")
            log(traceback.format_exc())
    fonte = referencias(cli, est, agora, log, cdi_ano, buscar_cdi)
    info = {"em": agora, "pedidos": cli.pedidos, "peso": cli.peso, "segundos": round(time.monotonic() - t0, 1),
            "operacoes": n, "escolha": bool(precisa), "erros": erros[:10]}
    est["rodadas"] = (est["rodadas"] + [info])[-60:]
    resumo = montar_resumo(est, agora, fonte, cdi_ano, exemplo, info)
    os.makedirs(pasta, exist_ok=True)
    with open(os.path.join(pasta, "estado.json"), "w") as f:
        json.dump(est, f, separators=(",", ":"))
    with open(os.path.join(pasta, "resumo.json"), "w") as f:
        json.dump(resumo, f, ensure_ascii=False, separators=(",", ":"))
    antigo = []
    try:
        with open(os.path.join(pasta, "log.txt")) as f:
            antigo = f.read().splitlines()[-1500:]
    except OSError:
        pass
    with open(os.path.join(pasta, "log.txt"), "w") as f:
        f.write("\n".join(antigo + log.linhas) + "\n")
    log(f"  fim: {cli.pedidos} pedidos, peso {cli.peso}, {info['segundos']} s, {len(erros)} erros")
    return resumo, est


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", required=True, help="pasta do ramo mercado (lê e grava estado.json, resumo.json, log.txt)")
    ap.add_argument("--escolher", action="store_true", help="refaz a escolha das carteiras agora")
    ap.add_argument("--exemplos", action="store_true", help="usa o mercado de mentira (falso.py), sem rede")
    ap.add_argument("--agora", type=int, help="instante da rodada em ms (testes)")
    ap.add_argument("--prazo", type=float, default=13.0, help="minutos no máximo")
    ap.add_argument("--cdi", type=float, default=CDI_ANO * 100, help="CDI ao ano (%%) quando a série do BC falhar")
    a = ap.parse_args()
    if a.exemplos:
        import falso
        cli = falso.ClienteFalso(agora=a.agora)
        a.agora = cli.agora
    else:
        cli = hl.Cliente()
    resumo, _ = rodada(cli, a.dados, a.agora, a.escolher, a.exemplos, a.prazo, a.cdi / 100, buscar_cdi=not a.exemplos)
    n = len(resumo["carteiras"])
    ac = sum(1 for c in resumo["carteiras"] if (c["aoVivo"].get(PADRAO) or {}).get("retorno", 0) > 0)
    print(f"::notice title=Testes de mercado::{n} carteiras seguidas; {ac} positivas ao vivo (3× e 1 min); "
          f"{resumo['rodada']['pedidos']} pedidos, {resumo['rodada']['segundos']} s")
    for e in resumo["rodada"]["erros"]:
        print(f"::warning title=Testes de mercado::{e}")


if __name__ == "__main__":
    main()
