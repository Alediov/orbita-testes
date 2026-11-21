"""Observatório dos cartões no intervalo (pedido do Alediov, 21/11/2026, pela planilha de apostas dele de agosto: os
"Over cartões no intervalo" deram 7 de 7). SÓ OBSERVAÇÃO: não há odds gratuitas de cartões, então nenhuma conta aposta.

O método dele (o prompt "Cartões" do AI Studio): apostar em mais cartões no 2º tempo, no intervalo, só nos jogos em que
o 1º tempo terminou SEM cartão. Aqui se mede, nos jogos de verdade, com que frequência isso acontece:

- dos jogos terminados nos campeonatos que o prompt aceita, os que tiveram 0 cartão no 1º tempo;
- desses, em quantos o 2º tempo teve mais de 1,5, 2,5 e 3,5 cartões (a taxa, o intervalo de Wilson de 95% e a odd
  justa = 1 ÷ taxa: se a casa paga mais que ela no intervalo, o método tem valor);
- o mesmo em todos os jogos (sem a condição), para ver se o "0 no 1º tempo" muda alguma coisa;
- por campeonato e os times com mais cartões por jogo.

Fonte: o placar público da ESPN (sem chave), o mesmo das apostas: a lista de jogos do dia de cada campeonato e, de cada
jogo terminado, os lances (`keyEvents` do resumo do jogo: tipo, minuto, período e time). Cada cartão conta 1 (o 2º
amarelo e o vermelho que vem com ele contam 2, como a ESPN registra). Prorrogação não conta. Os nomes dos campos foram
escritos sem acesso à ESPN daqui: a 1ª rodada registra no log a estrutura de um lance para conferir.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import time

from conta import DIA, HORA, dia_de

URL_DIA = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates={dia}"
URL_JOGO = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/summary?event={id}"

# chave, nome, código da ESPN (os campeonatos que o prompt dele aceita)
LIGAS = [
    ("bra", "Brasileirão A", "bra.1"),
    ("bra2", "Brasileirão B", "bra.2"),
    ("cdb", "Copa do Brasil", "bra.copa_do_brazil"),
    ("lib", "Libertadores", "conmebol.libertadores"),
    ("sud", "Sul-Americana", "conmebol.sudamericana"),
    ("eng", "Premier League", "eng.1"),
    ("esp", "La Liga", "esp.1"),
    ("ita", "Série A (Itália)", "ita.1"),
    ("ger", "Bundesliga", "ger.1"),
    ("fra", "Ligue 1", "fra.1"),
    ("ucl", "Champions League", "uefa.champions"),
    ("uel", "Europa League", "uefa.europa"),
]
NOME = {k: n for k, n, _ in LIGAS}
COD = {k: c for k, _, c in LIGAS}

VOLTA_DIAS = 30              # quanto do passado se busca na 1ª vez (aos poucos)
GUARDA_DIAS = 120            # jogos guardados no estado
MAX_DIAS_RODADA = 24         # listas de jogos por rodada (um campeonato × um dia cada)
MAX_JOGOS_RODADA = 40        # resumos de jogo por rodada
SEGUNDOS = 150               # tempo máximo do observatório numa rodada (as formas depois das apostas precisam dele)
DEIXAR = 400                 # segundos da rodada que ficam para as formas seguintes
TEMPO_MIN = 40               # segundos que precisam sobrar para continuar pedindo
FALHA_PAUSA = 7 * DIA        # campeonato que a ESPN não reconhece (404): tenta de novo em 7 dias
TENTATIVAS = 3               # resumo de jogo que falha: tenta até 3 vezes
LINHAS = [(1.5, "o15"), (2.5, "o25"), (3.5, "o35")]
ODD_REF = 1.9                # a odd típica que ele pegava (a média da planilha de agosto: 1,6 a 2,55)
MIN_TIME = 4                 # jogos mínimos de um time para entrar na lista
ULTIMOS = 10


def _dia_espn(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y%m%d")


def _ms(x):
    if not x:
        return None
    try:
        s = str(x).replace("Z", "+00:00")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\+00:00", s):
            s = s.replace("+00:00", ":00+00:00")
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp() * 1000)
    except ValueError:
        return None


def wilson(k, n, z=1.96):
    """O intervalo de Wilson (95%) de k acertos em n."""
    if not n:
        return None, None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - m), min(1.0, c + m)


def estrutura(x, prof=3):
    if prof <= 0:
        return "…"
    if isinstance(x, dict):
        return {str(k): estrutura(v, prof - 1) for k, v in list(x.items())[:10]}
    if isinstance(x, list):
        return [estrutura(x[0], prof - 1)] if x else []
    return type(x).__name__


# ---------------------------------------------------------------------------------------------------- leitura da ESPN
def jogos_do_dia(r):
    """[(id, ms, casa, fora, id da casa, id de fora, terminou)] da lista de jogos de um dia."""
    out = []
    for e in (r or {}).get("events") or []:
        try:
            comp = (e.get("competitions") or [{}])[0]
            st = ((comp.get("status") or e.get("status") or {}).get("type") or {})
            terminou = bool(st.get("completed")) or st.get("state") == "post"
            lados = {c.get("homeAway"): c for c in comp.get("competitors") or []}
            h, a = lados.get("home"), lados.get("away")
            if not h or not a or not e.get("id"):
                continue

            def nome(c):
                tm = c.get("team") or {}
                return tm.get("displayName") or tm.get("name") or tm.get("shortDisplayName") or ""
            out.append((str(e["id"]), _ms(e.get("date") or comp.get("date")), nome(h), nome(a),
                        str((h.get("team") or {}).get("id") or h.get("id") or ""),
                        str((a.get("team") or {}).get("id") or a.get("id") or ""), terminou))
        except (AttributeError, TypeError, IndexError):
            continue
    return out


def _tipo(ev):
    t = ev.get("type")
    if isinstance(t, dict):
        t = " ".join(str(t.get(k) or "") for k in ("text", "type", "name"))
    return str(t or "").lower()


RE_CARTAO = re.compile(r"card|cart[aã]o|amarel|vermelh|\byellow\b|\bred\b")


def eh_cartao(ev):
    if not isinstance(ev, dict):
        return False
    if ev.get("yellowCard") or ev.get("redCard"):
        return True
    t = _tipo(ev)
    # "red" só como palavra: "Penalty - Scored" também tem "red"
    return bool(RE_CARTAO.search(t)) and "substitution" not in t


def tempo(ev):
    """1 ou 2 (o tempo do lance), ou None (prorrogação, pênaltis ou sem minuto)."""
    per = ev.get("period")
    n = per.get("number") if isinstance(per, dict) else per
    if isinstance(n, (int, float)) and not isinstance(n, bool):
        return int(n) if int(n) in (1, 2) else None
    clk = ev.get("clock") or {}
    dv = str(clk.get("displayValue") or "")
    m = re.match(r"\s*(\d+)\s*'?", dv)
    if m:
        base = int(m.group(1))
        return 1 if base <= 45 else 2 if base <= 90 else None
    v = clk.get("value")
    if isinstance(v, (int, float)):
        mn = v / 60
        return 1 if mn <= 45 else 2 if mn <= 95 else None
    return None


def lances(r):
    """Os lances de um resumo de jogo (keyEvents; se não houver, os `details` da competição)."""
    if not isinstance(r, dict):
        return None
    if isinstance(r.get("keyEvents"), list):
        return r["keyEvents"]
    comp = ((r.get("header") or {}).get("competitions") or [{}])[0]
    if isinstance(comp.get("details"), list):
        return comp["details"]
    return None


def contar(evs, id_casa, id_fora):
    """(cartões no 1º tempo, no 2º, da casa, de fora) dos lances; None se não houver lista de lances."""
    if evs is None:
        return None
    c1 = c2 = cc = cf = 0
    for ev in evs:
        if not eh_cartao(ev):
            continue
        t = tempo(ev)
        if t is None:
            continue
        if t == 1:
            c1 += 1
        else:
            c2 += 1
        tid = str(((ev.get("team") or {}).get("id")) or "")
        if tid and tid == id_casa:
            cc += 1
        elif tid and tid == id_fora:
            cf += 1
    return c1, c2, cc, cf


# ---------------------------------------------------------------------------------------------------- a coleta
def coletar(fonte, C, agora, restante, log, erros):
    """Anda o observatório: pede as listas de jogos dos dias que faltam (do mais novo para trás) e os resumos dos jogos
    terminados. `C` é o estado (est["cartoes"]). Devolve quantos pedidos fez."""
    C.setdefault("jogos", {})
    C.setdefault("pend", {})
    C.setdefault("dias", {})      # liga → [dias da ESPN já lidos (AAAAMMDD)]
    C.setdefault("pausa", {})
    C.setdefault("desde", agora)
    ontem = dia_de(agora - DIA)
    pedidos = feitos_dias = feitos_jogos = 0
    # os dias que faltam, de ontem para trás, revezando os campeonatos (hoje fica para amanhã, quando os jogos acabaram;
    # um dia com jogo ainda sem fim volta na próxima rodada)
    t0 = time.monotonic()
    do_ctx = restante
    restante = lambda: min(do_ctx() - DEIXAR, SEGUNDOS - (time.monotonic() - t0))  # noqa: E731
    faltam = []
    for k in range(1, VOLTA_DIAS + 1):
        d = _dia_espn(agora - k * DIA)
        for liga, _n, _c in LIGAS:
            if agora < int(C["pausa"].get(liga) or 0):
                continue
            if d not in C["dias"].setdefault(liga, []):
                faltam.append((liga, d))
    for liga, d in faltam:
        if feitos_dias >= MAX_DIAS_RODADA or restante() < TEMPO_MIN:
            break
        try:
            r = fonte.json_url(URL_DIA.format(liga=COD[liga], dia=d), "espn")
        except Exception as e:  # noqa: BLE001  (odds.Erro e o hl.Erro dos testes; 404 = campeonato desconhecido)
            pedidos += 1
            feitos_dias += 1
            if getattr(e, "status", None) == 404:
                C["pausa"][liga] = agora + FALHA_PAUSA
                log(f"  cartões: a ESPN não reconhece {COD[liga]} ({NOME[liga]}); tenta de novo em 7 dias")
            else:
                erros.append(f"cartões: lista de jogos ({NOME[liga]} {d}): {e}")
            continue
        pedidos += 1
        feitos_dias += 1
        lista = jogos_do_dia(r)
        if lista and not C.get("viuDia"):
            log(f"  cartões: formato da lista de jogos: {estrutura((r.get('events') or [{}])[0], 4)}")
            C["viuDia"] = True
        todos_fim = True
        for eid, ms, casa, fora, ic, iff, fim in lista:
            if not fim:
                todos_fim = False
                continue
            if eid in C["jogos"] or eid in C["pend"] or ms is None or ms < agora - GUARDA_DIAS * DIA:
                continue
            C["pend"][eid] = [ms, liga, casa, fora, ic, iff, 0]
        lidos = C["dias"][liga]
        # um dia só fica "lido" quando acabou (ontem ou antes, com todos os jogos terminados)
        if d not in lidos and todos_fim and d <= ontem.replace("-", ""):
            lidos.append(d)
    # os resumos: os jogos mais antigos primeiro (a ordem não muda as contas)
    for eid in sorted(C["pend"], key=lambda k: C["pend"][k][0]):
        if feitos_jogos >= MAX_JOGOS_RODADA or restante() < TEMPO_MIN:
            break
        ms, liga, casa, fora, ic, iff, tent = C["pend"][eid]
        try:
            r = fonte.json_url(URL_JOGO.format(liga=COD[liga], id=eid), "espn")
        except Exception as e:  # noqa: BLE001
            pedidos += 1
            feitos_jogos += 1
            C["pend"][eid][6] = tent + 1
            if tent + 1 >= TENTATIVAS:
                C["pend"].pop(eid)
                C["semLances"] = int(C.get("semLances", 0)) + 1
            if getattr(e, "status", None) not in (404,):
                erros.append(f"cartões: resumo do jogo {eid}: {e}")
            continue
        pedidos += 1
        feitos_jogos += 1
        evs = lances(r)
        if evs and not C.get("viuLance"):
            card = next((x for x in evs if eh_cartao(x)), evs[0])
            log(f"  cartões: formato de um lance: {estrutura(card, 3)}")
            C["viuLance"] = True
        n = contar(evs, ic, iff)
        C["pend"].pop(eid)
        if n is None:
            C["semLances"] = int(C.get("semLances", 0)) + 1
            continue
        C["jogos"][eid] = [ms, liga, casa, fora, *n]
    # limpeza
    corte = agora - GUARDA_DIAS * DIA
    for eid in [k for k, j in C["jogos"].items() if j[0] < corte]:
        del C["jogos"][eid]
    dcorte = _dia_espn(agora - (VOLTA_DIAS + 2) * DIA)
    for liga in C["dias"]:
        C["dias"][liga] = sorted(d for d in C["dias"][liga] if d >= dcorte)
    if feitos_dias or feitos_jogos:
        log(f"  cartões: {feitos_dias} listas de jogos e {feitos_jogos} resumos; {len(C['jogos'])} jogos guardados, "
            f"{len(C['pend'])} esperando o resumo")
    return pedidos


# ---------------------------------------------------------------------------------------------------- as contas
def taxa(js, linha):
    """{n, k, taxa, lo, hi, justa} dos jogos `js` com 2º tempo acima de `linha`."""
    n = len(js)
    k = sum(1 for j in js if j[5] > linha)
    lo, hi = wilson(k, n)
    t = k / n if n else None
    return {"n": n, "k": k, "taxa": round(t, 4) if t is not None else None,
            "lo": round(lo, 4) if lo is not None else None, "hi": round(hi, 4) if hi is not None else None,
            "justa": round(1 / t, 2) if t else None}


def resumo(C, agora):
    """O bloco `cartoes` da saída das apostas (FORMATO.md, "Cartões no intervalo")."""
    js = sorted(C.get("jogos", {}).values(), key=lambda j: j[0])
    zero = [j for j in js if j[4] == 0]
    out = {"desde": C.get("desde"), "jogos": len(js), "zero1t": len(zero),
           "esperando": len(C.get("pend") or {}), "semLances": int(C.get("semLances", 0)),
           "oddRef": ODD_REF, "empateRef": round(1 / ODD_REF, 4), "fonte": "ESPN (lances de cada jogo)",
           "ligasForaDaEspn": [NOME[k] for k, t in (C.get("pausa") or {}).items() if agora < int(t or 0)]}
    if not js:
        return out
    n = len(js)
    out["media"] = {"jogo": round(sum(j[4] + j[5] for j in js) / n, 2), "t1": round(sum(j[4] for j in js) / n, 2),
                    "t2": round(sum(j[5] for j in js) / n, 2),
                    "t2SemCartao1t": round(sum(j[5] for j in zero) / len(zero), 2) if zero else None}
    out["regras"] = [{"id": rid, "linha": ln, "nome": f"Mais de {str(ln).replace('.', ',')} cartões no 2º tempo",
                      "comZero": taxa(zero, ln), "todos": taxa(js, ln)} for ln, rid in LINHAS]
    ligas = []
    for liga, nome, _c in LIGAS:
        lj = [j for j in js if j[1] == liga]
        if not lj:
            continue
        lz = [j for j in lj if j[4] == 0]
        ligas.append({"liga": liga, "nome": nome, "jogos": len(lj), "zero1t": len(lz),
                      "media": round(sum(j[4] + j[5] for j in lj) / len(lj), 2), "o15": taxa(lz, 1.5)})
    out["ligas"] = sorted(ligas, key=lambda x: -x["jogos"])
    tm = {}
    for j in js:
        for nome, c, contra in ((j[2], j[6], j[7]), (j[3], j[7], j[6])):
            t = tm.setdefault((j[1], nome), [0, 0, 0])
            t[0] += 1
            t[1] += c
            t[2] += contra
    times = [{"time": nome, "liga": NOME.get(liga, liga), "jogos": v[0], "media": round(v[1] / v[0], 2),
              "contra": round(v[2] / v[0], 2)} for (liga, nome), v in tm.items() if v[0] >= MIN_TIME]
    out["times"] = sorted(times, key=lambda x: (-x["media"], -x["jogos"]))[:8]
    out["ultimos"] = [{"jogo": f"{j[2]} × {j[3]}", "liga": NOME.get(j[1], j[1]), "inicio": j[0], "t2": j[5]}
                      for j in reversed(zero[-ULTIMOS:])]
    return out
