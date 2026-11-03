"""As outras formas de "investimento" arriscado, NO PAPEL (plano: docs/plano-testes-mercado-2.md; formato dos
resultados: tools/papel/FORMATO.md). Roda no GitHub Actions (`.github/workflows/papel.yml`) a cada 6 h e grava no ramo
órfão `papel`: indice.json, <forma>.json, estado.json e log.txt. Nenhuma ordem, nenhuma conta, nenhuma chave: só APIs
públicas de leitura.

Cada forma é um módulo desta pasta (`cofres.py`, `funding.py`, `robos.py`…) com:

    NOME = "Funding"          # o nome curto (chip do app)
    VERSAO = 1                # mudar o formato do estado da forma: subir (o estado antigo vai para ctx.antigo)
    def rodar(ctx) -> dict    # devolve o <forma>.json SEM v, forma, nome, agora e rodada (o papel.py põe)

`ctx` tem: `cli` (hl.Cliente ou o falso), `agora` (ms), `est` (o estado da forma, dict, mudado no lugar), `antigo`
(o estado de uma VERSAO anterior, ou None), `log(texto)`, `restante()` (segundos até o prazo da rodada),
`exemplo` (True no mercado de mentira) e `ref` (as referências já buscadas: {"btc": {dia: preço}, "cdi": {dia: taxa}}).
Uma forma que levanta exceção fica `ok: false` no índice e mantém o <forma>.json da rodada anterior; as outras seguem.

Uso: python3 tools/papel/papel.py --dados <pasta do ramo> [--formas cofres,funding] [--prazo 20] [--exemplos]
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import json
import os
import sys
import time
import traceback
import urllib.request
from types import SimpleNamespace

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)  # antes do mercado: os dois têm um falso.py

import hl  # noqa: E402
from conta import DIA, dia_de  # noqa: E402

FORMAS = ["cofres", "funding", "robos"]
V = 1
CDI_ANO = 0.149
REF_DIAS = 400
MAX_LOG = 400  # linhas


class Log:
    def __init__(self, quieto=False):
        self.linhas, self.quieto = [], quieto

    def __call__(self, texto):
        self.linhas.append(texto)
        if not self.quieto:
            print(texto, flush=True)


def ler_json(caminho, padrao=None):
    try:
        with open(caminho) as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def gravar_json(caminho, dados):
    tmp = caminho + ".tmp"
    with open(tmp, "w") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, caminho)


def referencias(cli, ref, agora, log, buscar_cdi=True):
    """Bitcoin (velas diárias da HL) e CDI (série 12 do BC) desde REF_DIAS atrás; guarda em `ref` (o estado)."""
    ini = agora - REF_DIAS * DIA
    ultimo_btc = max(ref["btc"]) if ref["btc"] else None
    try:
        a = ini if not ultimo_btc else int(dt.datetime.fromisoformat(ultimo_btc).replace(tzinfo=dt.timezone.utc).timestamp() * 1000) - 2 * DIA
        for c in cli.velas("BTC", "1d", max(ini, a), agora):
            ref["btc"][dia_de(int(c["T"]))] = float(c["c"])
    except hl.Erro as e:
        log(f"  bitcoin: {e}")
    fonte = "fixa"
    if buscar_cdi:
        try:
            de = dt.datetime.fromtimestamp(ini / 1000).strftime("%d/%m/%Y")
            ate = dt.datetime.fromtimestamp(agora / 1000).strftime("%d/%m/%Y")
            url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados?formato=json&dataInicial={de}&dataFinal={ate}"
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "orbita-testes/1"}), timeout=20) as r:
                for x in json.loads(r.read().decode()):
                    d, m, y = x["data"].split("/")
                    ref["cdi"][f"{y}-{m}-{d}"] = float(x["valor"]) / 100
            fonte = "bcb"
        except Exception as e:  # noqa: BLE001
            log(f"  CDI do Banco Central: {e}; usando {CDI_ANO * 100:.1f}% ao ano")
    corte = dia_de(ini)
    for k in ("btc", "cdi"):
        for d in [d for d in ref[k] if d < corte]:
            del ref[k][d]
    return fonte


def indice_cdi(cdi, de, ate, cdi_ano=CDI_ANO):
    """Índice diário do CDI (1 no 1º dia): a série do BC quando há; nos dias úteis depois dela, a taxa fixa."""
    out, v = [], 1.0
    d, fim = dt.date.fromisoformat(de), dt.date.fromisoformat(ate)
    diaria = (1 + cdi_ano) ** (1 / 252) - 1
    ultimo = max(cdi) if cdi else ""
    while d <= fim:
        k = d.isoformat()
        out.append([k, round(v, 6)])
        if k in cdi:
            v *= 1 + cdi[k]
        elif d.weekday() < 5 and k > ultimo:
            v *= 1 + diaria
        d += dt.timedelta(days=1)
    return out


def rodada(cli, pasta, agora=None, formas=None, prazo_min=20.0, exemplo=False, buscar_cdi=True, log=None):
    """Uma rodada de todas as formas pedidas. Devolve o índice."""
    log = log or Log()
    t0 = time.monotonic()
    agora = int(agora or time.time() * 1000)
    os.makedirs(pasta, exist_ok=True)
    est = ler_json(os.path.join(pasta, "estado.json"), {}) or {}
    if est.get("v") != V:
        est = {"v": V, "formas": {}, "ref": {"btc": {}, "cdi": {}}}
    est.setdefault("formas", {})
    est.setdefault("ref", {"btc": {}, "cdi": {}})
    indice = ler_json(os.path.join(pasta, "indice.json"), {}) or {}
    ind_formas = dict(indice.get("formas") or {})
    log(f"rodada {dt.datetime.fromtimestamp(agora / 1000, dt.timezone.utc):%Y-%m-%d %H:%M}Z")
    fonte = referencias(cli, est["ref"], agora, log, buscar_cdi)

    for nome in formas or FORMAS:
        p0, peso0 = getattr(cli, "pedidos", 0), time.monotonic()
        try:
            mod = importlib.import_module(nome)
        except ImportError as e:
            log(f"  {nome}: módulo ausente ({e})")
            continue
        guardado = est["formas"].get(nome) or {}
        antigo = None
        if guardado.get("_v") != mod.VERSAO:
            antigo = guardado or None
            guardado = {"_v": mod.VERSAO}
        ctx = SimpleNamespace(cli=cli, agora=agora, est=guardado, antigo=antigo, log=log, exemplo=exemplo,
                              ref=est["ref"], restante=lambda: prazo_min * 60 - (time.monotonic() - t0))
        try:
            saida = mod.rodar(ctx)
            saida.update({"v": V, "forma": nome, "nome": mod.NOME, "agora": agora,
                          "rodada": {"pedidos": getattr(cli, "pedidos", 0) - p0,
                                     "segundos": round(time.monotonic() - peso0, 1), "erros": saida.get("erros", [])}})
            saida.pop("erros", None)
            if exemplo:
                saida["exemplo"] = True
            gravar_json(os.path.join(pasta, f"{nome}.json"), saida)
            est["formas"][nome] = ctx.est
            ind_formas[nome] = {"arquivo": f"{nome}.json", "agora": agora, "nome": mod.NOME, "ok": True}
            log(f"  {nome}: ok ({len(saida.get('versoes') or [])} versões, {saida['rodada']['pedidos']} pedidos, {saida['rodada']['segundos']} s)")
        except Exception as e:  # noqa: BLE001
            log(f"  {nome}: ERRO {e}")
            log("    " + traceback.format_exc().strip().replace("\n", "\n    ")[-1500:])
            velho = ind_formas.get(nome) or {}
            if os.path.exists(os.path.join(pasta, f"{nome}.json")):
                ind_formas[nome] = {**velho, "arquivo": f"{nome}.json", "nome": getattr(mod, "NOME", nome), "ok": False, "erro": str(e)[:200]}
            else:
                ind_formas.pop(nome, None)

    ref = est["ref"]
    de = dia_de(agora - REF_DIAS * DIA)
    indice = {"v": V, "agora": agora, "formas": ind_formas,
              "ref": {"btc": sorted([[d, v] for d, v in ref["btc"].items()]),
                      "cdi": indice_cdi(ref["cdi"], de, dia_de(agora)), "cdiAno": CDI_ANO, "cdiFonte": fonte},
              "exemplo": bool(exemplo)}
    gravar_json(os.path.join(pasta, "indice.json"), indice)
    gravar_json(os.path.join(pasta, "estado.json"), est)
    log(f"fim: {getattr(cli, 'pedidos', '?')} pedidos, {time.monotonic() - t0:.0f} s")
    antigo_log = []
    try:
        with open(os.path.join(pasta, "log.txt")) as f:
            antigo_log = f.read().splitlines()
    except OSError:
        pass
    with open(os.path.join(pasta, "log.txt"), "w") as f:
        f.write("\n".join((antigo_log + log.linhas)[-MAX_LOG:]) + "\n")
    return indice


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", required=True)
    ap.add_argument("--formas", default=",".join(FORMAS))
    ap.add_argument("--prazo", type=float, default=20.0, help="minutos")
    ap.add_argument("--exemplos", action="store_true", help="mercado de mentira (sem rede)")
    a = ap.parse_args()
    if a.exemplos:
        import falso
        cli = falso.ClientePapelFalso()
        rodada(cli, a.dados, cli.agora, a.formas.split(","), a.prazo, exemplo=True, buscar_cdi=False)
    else:
        rodada(hl.Cliente(), a.dados, None, a.formas.split(","), a.prazo)


if __name__ == "__main__":
    main()
