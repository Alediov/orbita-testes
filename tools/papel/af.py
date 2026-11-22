"""A API-Football (api-sports.io, plano grátis com chave no segredo APIFOOTBALL_KEY; pedido do Alediov, 22/11/2026):
as odds de antes do jogo das casas internacionais (Pinnacle, Betano, Bet365…) para os palpites do Theo e as odds ao vivo
do intervalo para o Observatório. Só leitura e as contas de mentira; a chave vai no cabeçalho, nunca na URL nem no log.

O que a sonda de 22/11/2026 mostrou (`sonda_odds.py`): o plano grátis só abre de ontem a amanhã (data do jogo); antes
do jogo vêm 338 mercados, com "Match Winner", "Goals Over/Under" ("Over 2.5"), "Cards Over/Under", "Corners Over
Under"…; ao vivo, `/odds/live` traz todos os jogos rolando num pedido só ("Over/Under Line", "Total Corners", "Total
Cards"…, os valores com `handicap`), mas sem o nome dos times (vem da lista de jogos do dia).
"""
from __future__ import annotations

import datetime as dt
import re

BASE = "https://v3.football.api-sports.io"
CAB = "x-apisports-key"
# as ligas da API-Football que o papel acompanha (a chave das apostas e dos cartões)
LIGA_AF = {71: "bra", 72: "bra2", 73: "cdb", 13: "lib", 11: "sud", 39: "eng", 140: "esp", 135: "ita", 78: "ger",
           61: "fra", 2: "ucl", 3: "uel"}
# a casa comum, na ordem de preferência (a Betano era a dele)
SOFTS_AF = ["Betano", "Bet365", "1xBet", "William Hill", "Marathonbet", "Betfair", "BetVictor"]
TERMINADO = {"FT", "AET", "PEN"}


def url_dia(d):
    return f"{BASE}/fixtures?date={d}&timezone=UTC"


def url_odds(fid):
    return f"{BASE}/odds?fixture={fid}"


def url_ao_vivo():
    return f"{BASE}/odds/live"


def _ms(s):
    try:
        d = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp() * 1000)
    except (TypeError, ValueError):
        return None


def num(x):
    try:
        v = float(str(x).replace(",", "."))
        return v if v > 1.0 else None
    except (TypeError, ValueError):
        return None


def jogos_do_dia(r):
    """[{id, ms, casa, fora, liga (a id da API-Football), st (status curto), placar [c, f] ou None}] de /fixtures."""
    out = []
    for x in (r or {}).get("response") or []:
        try:
            fx, tm, lg = x.get("fixture") or {}, x.get("teams") or {}, x.get("league") or {}
            ms = _ms(fx.get("date")) or (int(fx["timestamp"]) * 1000 if fx.get("timestamp") else None)
            casa, fora = (tm.get("home") or {}).get("name"), (tm.get("away") or {}).get("name")
            if not fx.get("id") or not ms or not casa or not fora:
                continue
            st = str((fx.get("status") or {}).get("short") or "")
            pl = None
            if st in TERMINADO:
                ft = (x.get("score") or {}).get("fulltime") or {}
                g = x.get("goals") or {}
                a, b = ft.get("home"), ft.get("away")
                if a is None or b is None:
                    a, b = g.get("home"), g.get("away")
                if a is not None and b is not None:
                    pl = [int(a), int(b)]
            out.append({"id": int(fx["id"]), "ms": ms, "casa": str(casa), "fora": str(fora),
                        "liga": lg.get("id"), "st": st, "placar": pl})
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def achar(lista, casa, fora, ms=None, janela=3 * 3600 * 1000):
    """(jogo, invertido) da lista que bate com os dois times (em qualquer ordem) e, se dado, o início (±3 h)."""
    from apostas import mesmo_time
    for j in lista:
        if ms is not None and abs(j["ms"] - ms) > janela:
            continue
        if mesmo_time(casa, j["casa"]) and mesmo_time(fora, j["fora"]):
            return j, False
        if mesmo_time(casa, j["fora"]) and mesmo_time(fora, j["casa"]):
            return j, True
    return None, None


def _valores(bet):
    """[(texto, linha ou None, odd)] dos valores de um mercado ("Over 2.5" ou "Over" com handicap "2.5")."""
    out = []
    for v in (bet or {}).get("values") or []:
        if not isinstance(v, dict) or v.get("suspended"):
            continue
        o = num(v.get("odd"))
        if not o:
            continue
        txt = str(v.get("value") or "").strip()
        ln = None
        m = re.match(r"^(over|under|mais|menos)\s*([0-9]+(?:[.,][0-9]+)?)$", txt, re.I)
        if m:
            txt, ln = m.group(1), float(m.group(2).replace(",", "."))
        elif v.get("handicap") not in (None, ""):
            try:
                ln = float(str(v["handicap"]).replace(",", "."))
            except ValueError:
                ln = None
        out.append((txt.lower(), ln, o))
    return out


def mercados_casa(bets):
    """{"1x2": [casa, empate, fora], "ou": [mais 2,5, menos 2,5]} dos mercados de uma casa (antes do jogo)."""
    out = {}
    for b in bets or []:
        nome = str((b or {}).get("name") or "").strip().lower()
        vs = _valores(b)
        if nome in ("match winner", "1x2", "fulltime result") and "1x2" not in out:
            d = {t: o for t, _l, o in vs}
            h = [d.get("home"), d.get("draw"), d.get("away")]
            if all(h):
                out["1x2"] = h
        elif nome in ("goals over/under", "over/under", "goals over under") and "ou" not in out:
            d = {(t, ln): o for t, ln, o in vs}
            h = [d.get(("over", 2.5)), d.get(("under", 2.5))]
            if all(h):
                out["ou"] = h
    return out


def odds_prejogo(r):
    """Uma foto das odds de antes do jogo: {"pin": {...}, "soft": {...}, "casa": nome} (None sem a Pinnacle ou sem
    uma casa comum)."""
    resp = (r or {}).get("response") or []
    if not resp:
        return None
    casas = {}
    for bk in (resp[0] or {}).get("bookmakers") or []:
        nome = str((bk or {}).get("name") or "")
        casas[nome] = mercados_casa(bk.get("bets"))
    pin = casas.get("Pinnacle") or {}
    casa = next((c for c in SOFTS_AF if casas.get(c, {}).get("1x2")), None)
    if not pin.get("1x2") or not casa:
        return None
    return {"pin": pin, "soft": casas[casa], "casa": casa}


def series(fotos, ate):
    """As fotos (lista de {t, pin, soft, casa}) de antes de `ate` no formato do motor das apostas: (pin, soft, casa) com
    {mk: [hist por resultado]}, hist = [(ms, odd)]. A casa é a que mais aparece (a série não mistura casas)."""
    fs = sorted((f for f in fotos or [] if f and int(f.get("t") or 0) < ate), key=lambda f: f["t"])
    if not fs:
        return None, None, None
    cont = {}
    for f in fs:
        cont[f["casa"]] = cont.get(f["casa"], 0) + 1
    casa = max(cont, key=lambda c: (cont[c], -SOFTS_AF.index(c) if c in SOFTS_AF else -99))
    pin, soft = {}, {}
    for f in fs:
        for alvo, fonte in ((pin, f.get("pin") or {}), (soft, f.get("soft") or {} if f["casa"] == casa else {})):
            for mk, vals in fonte.items():
                h = alvo.setdefault(mk, [[] for _ in vals])
                if len(h) != len(vals):
                    continue
                for k, o in enumerate(vals):
                    if o:
                        h[k].append((int(f["t"]), float(o)))
    pin = {mk: h for mk, h in pin.items() if all(h)}
    soft = {mk: h for mk, h in soft.items() if all(h)}
    return pin, soft, casa


# ---------------------------------------------------------------------------------------------------- ao vivo
RX_AO_VIVO = re.compile(r"card|corner|over/under line|match goals|2nd half|second half", re.I)


def ao_vivo(r):
    """[{id, st (status curto), min (o minuto), gols [c, f], m {nome: [(texto, linha, odd)]}}] de /odds/live, só com os
    mercados de cartões, escanteios e gols."""
    out = []
    for x in (r or {}).get("response") or []:
        try:
            fx = x.get("fixture") or {}
            st = fx.get("status") or {}
            tm = x.get("teams") or {}
            m = {}
            for b in x.get("odds") or []:
                nome = str((b or {}).get("name") or "")
                if RX_AO_VIVO.search(nome) and not re.search(r"extra time|race to|which team|last corner|first corner",
                                                             nome, re.I):
                    vs = _valores(b)
                    if vs:
                        m[nome] = vs
            out.append({"id": int(fx["id"]), "st": str(st.get("short") or st.get("long") or ""),
                        "min": st.get("elapsed"), "gols": [(tm.get("home") or {}).get("goals"),
                                                           (tm.get("away") or {}).get("goals")],
                        "m": m, "parado": bool((x.get("status") or {}).get("stopped"))})
        except (AttributeError, TypeError, ValueError, KeyError):
            continue
    return out


def no_intervalo(j):
    """O jogo está no intervalo (o status curto "HT" ou o nome comprido)."""
    return j["st"].upper() in ("HT", "HALFTIME", "HALF TIME", "HALF-TIME")


def odd_mais(m, padrao, linha):
    """A odd de "mais de `linha`" no 1º mercado cujo nome bate com `padrao` (regex), ou None."""
    for nome, vs in (m or {}).items():
        if not re.search(padrao, nome, re.I):
            continue
        for t, ln, o in vs:
            if t in ("over", "mais") and ln is not None and abs(ln - linha) < 1e-6:
                return o
    return None
