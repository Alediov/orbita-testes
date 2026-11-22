"""Sonda das odds da API-Football (22/11/2026, pedido do Alediov: "puxar odds de outras casas"). Uma vez só, à mão
(`sonda.yml`): pergunta quais mercados o plano grátis traz antes do jogo e ao vivo (cartões, escanteios, gols do 2º
tempo) e escreve no log SÓ a estrutura e os nomes dos mercados e das casas (nunca a chave). Gasta ~6 pedidos dos 100
do dia."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request

BASE = "https://v3.football.api-sports.io"
RX = re.compile(r"corner|card|booking|2nd half|second half|half", re.I)


def pedir(caminho, chave):
    req = urllib.request.Request(BASE + caminho, headers={"x-apisports-key": chave, "User-Agent": "orbita-testes"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            resto = r.headers.get("x-ratelimit-requests-remaining")
            return json.loads(r.read().decode("utf-8", "replace")), resto
    except Exception as e:  # noqa: BLE001
        return {"erroSonda": str(e).replace(chave, "***")}, None


def main():
    chave = (os.environ.get("APIFOOTBALL_KEY") or "").strip()
    if not chave:
        print("sem a chave APIFOOTBALL_KEY")
        return 1
    hoje = dt.datetime.now(dt.timezone.utc).date().isoformat()
    # 1. os nomes dos mercados (antes do jogo e ao vivo)
    for cam, rot in (("/odds/bets", "antes do jogo"), ("/odds/live/bets", "ao vivo")):
        r, resto = pedir(cam, chave)
        nomes = [b.get("name") for b in r.get("response") or [] if isinstance(b, dict)]
        print(f"\n== mercados {rot}: {len(nomes)} (erros: {r.get('errors') or r.get('erroSonda')}; restam {resto} hoje)")
        print("   de cartões, escanteios e tempos:", [n for n in nomes if n and RX.search(n)])
    # 2. as odds de antes do jogo de hoje (página 1)
    r, resto = pedir(f"/odds?date={hoje}", chave)
    resp = r.get("response") or []
    print(f"\n== odds de antes do jogo em {hoje}: {len(resp)} jogos na página 1 de {(r.get('paging') or {}).get('total')} "
          f"(erros: {r.get('errors') or r.get('erroSonda')}; restam {resto})")
    casas, merc = {}, {}
    for x in resp:
        for bk in x.get("bookmakers") or []:
            casas[bk.get("name")] = casas.get(bk.get("name"), 0) + 1
            for b in bk.get("bets") or []:
                if b.get("name") and RX.search(b["name"]):
                    merc.setdefault(b["name"], set()).add(bk.get("name"))
    print("   casas:", sorted(casas.items(), key=lambda kv: -kv[1])[:20])
    print("   mercados de cartões/escanteios/tempos e quem oferece:", {k: sorted(v)[:6] for k, v in sorted(merc.items())})
    ex = next((b for x in resp for bk in x.get("bookmakers") or [] for b in bk.get("bets") or [] if b.get("name") and re.search(r"corner|card", b["name"], re.I)), None)
    if ex:
        print("   exemplo:", json.dumps(ex)[:600])
    # 3. ao vivo agora
    r, resto = pedir("/odds/live", chave)
    resp = r.get("response") or []
    print(f"\n== odds ao vivo agora: {len(resp)} jogos (erros: {r.get('errors') or r.get('erroSonda')}; restam {resto})")
    if resp:
        x = resp[0]
        print("   estrutura de um jogo:", json.dumps({k: (v if not isinstance(v, list) else f"[{len(v)}]") for k, v in x.items()})[:700])
    merc = {}
    for x in resp:
        for b in x.get("odds") or []:
            merc[b.get("name")] = merc.get(b.get("name"), 0) + 1
    print("   mercados ao vivo (em quantos jogos):", sorted(merc.items(), key=lambda kv: -kv[1])[:60])
    for x in resp:
        b = next((b for b in x.get("odds") or [] if b.get("name") and re.search(r"card|corner", b["name"], re.I)), None)
        if b:
            st = (x.get("fixture") or {}).get("status") or {}
            print("   exemplo ao vivo:", st, json.dumps(b)[:600])
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
