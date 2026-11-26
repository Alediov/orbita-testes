"""Sonda da The Odds API (26/11/2026: a API-Football foi suspensa; a chave grátis no segredo ODDSAPI_KEY). Uma vez só,
à mão (`sonda.yml`, input `qual` = theodds): o que o plano grátis traz para o futebol (as ligas, as casas da região eu
e uk, se vêm jogos ao vivo, os mercados extras de um jogo: escanteios, cartões, ambas marcam). Escreve no log SÓ a
estrutura, os nomes e as cotas usadas (nunca a chave). Gasta ~6 créditos dos 500 do mês."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.the-odds-api.com/v4"


def pedir(caminho, chave, **q):
    q["apiKey"] = chave
    url = BASE + caminho + "?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "orbita-testes"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            cab = {k: r.headers.get(k) for k in ("x-requests-remaining", "x-requests-used", "x-requests-last")}
            return json.loads(r.read().decode("utf-8", "replace")), cab
    except urllib.error.HTTPError as e:
        corpo = e.read().decode("utf-8", "replace")[:300].replace(chave, "***")
        return {"erroSonda": f"HTTP {e.code}: {corpo}"}, {}
    except Exception as e:  # noqa: BLE001
        return {"erroSonda": str(e).replace(chave, "***")}, {}


def main():
    chave = (os.environ.get("ODDSAPI_KEY") or "").strip()
    if not chave:
        print("sem ODDSAPI_KEY")
        return 1
    agora = dt.datetime.now(dt.timezone.utc)
    esportes, cab = pedir("/sports", chave)
    print("sports:", cab, "erro" if isinstance(esportes, dict) else len(esportes))
    if isinstance(esportes, dict):
        print(esportes)
        return 1
    fut = [s for s in esportes if s.get("group") == "Soccer"]
    print("futebol:", len(fut))
    for s in fut:
        print("  ", s.get("key"), "|", s.get("title"), "|", s.get("has_outrights"))
    # um campeonato com jogo rolando ou perto: a Europa League (quinta), senão a Premier League
    escolhido = None
    for chave_liga in ("soccer_uefa_europa_league", "soccer_uefa_europa_conference_league", "soccer_epl",
                       "soccer_brazil_campeonato"):
        evs, _ = pedir(f"/sports/{chave_liga}/events", chave)
        if isinstance(evs, list) and evs:
            print(f"eventos {chave_liga}:", len(evs))
            rolando = [e for e in evs if dt.datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")) <= agora]
            print("  rolando ou começados:", len(rolando), "| exemplo de campos:", sorted(evs[0].keys()))
            escolhido = (chave_liga, (rolando or evs)[0])
            break
    if not escolhido:
        print("nenhum evento")
        return 0
    liga, ev = escolhido
    print("jogo:", ev.get("home_team"), "x", ev.get("away_team"), ev.get("commence_time"))
    # as odds em destaque da liga (2 mercados x 2 regiões = 4 créditos): as casas, se o jogo rolando vem
    odds, cab = pedir(f"/sports/{liga}/odds", chave, regions="eu,uk", markets="h2h,totals", oddsFormat="decimal",
                      eventIds=ev["id"])
    print("odds:", cab)
    if isinstance(odds, list):
        for j in odds:
            casas = [b.get("key") for b in j.get("bookmakers") or []]
            print("  casas", len(casas), casas)
            for b in (j.get("bookmakers") or [])[:2]:
                for m in b.get("markets") or []:
                    print("   ", b.get("key"), m.get("key"), m.get("last_update"), [(o.get("name"), o.get("point"), o.get("price")) for o in m.get("outcomes") or []][:6])
    else:
        print(odds)
    # os mercados que cada casa tem nesse jogo (1 crédito)
    mk, cab = pedir(f"/sports/{liga}/events/{ev['id']}/markets", chave, regions="eu,uk")
    print("markets:", cab)
    if isinstance(mk, dict) and mk.get("bookmakers"):
        todos = {}
        for b in mk["bookmakers"]:
            for m in b.get("markets") or []:
                todos.setdefault(m.get("key"), []).append(b.get("key"))
        for k in sorted(todos):
            print("  ", k, len(todos[k]), todos[k][:8])
    else:
        print(json.dumps(mk)[:500])
    print("fim; restam", cab.get("x-requests-remaining"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
