"""A The Odds API (the-odds-api.com, plano grátis: 500 créditos por mês, a chave no segredo ODDSAPI_KEY, na URL e
nunca no log; 26/11/2026, no lugar da API-Football, que suspendeu a conta grátis por causa dos endereços compartilhados
do GitHub Actions).

O que a sonda de 26/11/2026 mostrou (`sonda_theodds.py`): 46 campeonatos de futebol (o Brasileirão, a Libertadores e
os europeus), 29 casas nas regiões eu+uk (a Pinnacle e a Betano do Reino Unido entre elas) e o /odds traz os jogos
AO VIVO. Nos mercados extras de um jogo da Europa League rolando: `alternate_totals_cards` (só a Pinnacle),
`alternate_totals_corners` (só a LeoVegas), `alternate_totals` (5 casas) e `btts` (7).

Custos: a lista de eventos (`/events`) não gasta; as odds de um jogo (`/events/{id}/odds`) gastam 1 crédito por mercado
que VOLTA × região. Os créditos restantes vêm no cabeçalho `x-requests-remaining`.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.the-odds-api.com/v4"
# as nossas chaves de campeonato → a da The Odds API e a da ESPN (o placar, o intervalo e o minuto vêm da ESPN, grátis)
LIGAS = {
    "bra": ("soccer_brazil_campeonato", "bra.1"),
    "lib": ("soccer_conmebol_copa_libertadores", "conmebol.libertadores"),
    "eng": ("soccer_epl", "eng.1"),
    "esp": ("soccer_spain_la_liga", "esp.1"),
    "ita": ("soccer_italy_serie_a", "ita.1"),
    "ger": ("soccer_germany_bundesliga", "ger.1"),
    "fra": ("soccer_france_ligue_one", "fra.1"),
    "ucl": ("soccer_uefa_champs_league", "uefa.champions"),
    "uel": ("soccer_uefa_europa_league", "uefa.europa"),
    "uecl": ("soccer_uefa_europa_conference_league", "uefa.europa.conf"),
}
# os mercados de linha que o Observatório lê, com o nome que as regras dele reconhecem (cartoes.RX_INT_*)
MERCADOS = {
    "alternate_totals_cards": "Cards Over/Under",
    "alternate_totals_corners": "Corners Over/Under",
    "alternate_totals": "Goals Over/Under",
    "totals": "Goals Over/Under",
}
PREFERIDAS = ["pinnacle", "leovegas", "betano_uk", "marathonbet", "coolbet", "ladbrokes_uk", "coral", "williamhill"]


def ms_de(iso):
    try:
        return int(dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError):
        return None


class Cliente:
    """A The Odds API de verdade: pedir(caminho, **q) → (json, créditos restantes ou None)."""

    def __init__(self, chave):
        self.chave, self.ultimo = chave, None

    def pedir(self, caminho, **q):
        q["apiKey"] = self.chave
        url = BASE + caminho + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"User-Agent": "orbita-testes"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                resto = r.headers.get("x-requests-remaining")
                try:
                    self.ultimo = int(float(r.headers.get("x-requests-last") or 0))
                except ValueError:
                    self.ultimo = None
                return (json.loads(r.read().decode("utf-8", "replace")),
                        int(float(resto)) if resto not in (None, "") else None)
        except urllib.error.HTTPError as e:
            corpo = e.read().decode("utf-8", "replace")[:200]
            raise RuntimeError(f"HTTP {e.code}: {corpo}".replace(self.chave, "***")) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise RuntimeError(str(e).replace(self.chave, "***")) from None


def eventos(r):
    """[{id, ms, casa, fora}] de /sports/{esporte}/events."""
    out = []
    for e in r if isinstance(r, list) else []:
        try:
            ms = ms_de(e.get("commence_time"))
            if ms and e.get("id"):
                out.append({"id": str(e["id"]), "ms": ms, "casa": str(e.get("home_team") or ""),
                            "fora": str(e.get("away_team") or "")})
        except AttributeError:
            continue
    return out


def linhas(r):
    """{nome do mercado: [(over|under, linha, odd)]} das odds de um jogo (/events/{id}/odds), uma entrada por casa
    ("Cards Over/Under · pinnacle"), a Pinnacle e as casas mais confiáveis primeiro (o Observatório usa a 1ª que bate)."""
    casas = (r or {}).get("bookmakers") if isinstance(r, dict) else None
    ordem = {k: i for i, k in enumerate(PREFERIDAS)}
    out = {}
    for b in sorted(casas or [], key=lambda b: ordem.get(b.get("key"), 99)):
        for m in b.get("markets") or []:
            nome = MERCADOS.get(m.get("key"))
            if not nome:
                continue
            xs = []
            for o in m.get("outcomes") or []:
                t = str(o.get("name") or "").strip().lower()
                try:
                    ln, odd = float(o.get("point")), float(o.get("price"))
                except (TypeError, ValueError):
                    continue
                if t in ("over", "under") and odd > 1:
                    xs.append([t, ln, odd])
            if xs:
                k = f"{nome} · {b.get('key')}"
                vistos = {(x[0], x[1]) for x in out.get(k, [])}
                out.setdefault(k, []).extend(x for x in xs if (x[0], x[1]) not in vistos)
    return out


# ------------------------------------------------------------------------------------------------ o placar da ESPN
URL_ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates={dia}"
RX_MIN = re.compile(r"(\d+)")


def espn(r):
    """[{id, ms, casa, fora, gols [c, f], st (pre|in|post), ht (no intervalo), min (o minuto ou None), periodo}]."""
    out = []
    for e in (r or {}).get("events") or []:
        try:
            comp = (e.get("competitions") or [{}])[0]
            st = comp.get("status") or e.get("status") or {}
            tipo = st.get("type") or {}
            lados = {c.get("homeAway"): c for c in comp.get("competitors") or []}
            h, a = lados.get("home"), lados.get("away")
            if not h or not a:
                continue

            def nome(c):
                tm = c.get("team") or {}
                return tm.get("displayName") or tm.get("name") or tm.get("shortDisplayName") or ""

            def gol(c):
                try:
                    return int(float(c.get("score")))
                except (TypeError, ValueError):
                    return None
            nm = str(tipo.get("name") or "").upper()
            det = str(tipo.get("shortDetail") or tipo.get("detail") or "")
            ht = nm == "STATUS_HALFTIME" or det.strip().upper() in ("HT", "HALFTIME", "HALF TIME")
            mn = RX_MIN.match(str(st.get("displayClock") or ""))
            out.append({"id": str(e.get("id")), "ms": ms_de(e.get("date") or comp.get("date")),
                        "casa": nome(h), "fora": nome(a), "gols": [gol(h), gol(a)],
                        "st": str(tipo.get("state") or ""), "ht": ht, "periodo": st.get("period"),
                        "min": int(mn.group(1)) if mn and tipo.get("state") == "in" else None})
        except (AttributeError, TypeError, IndexError):
            continue
    return out
