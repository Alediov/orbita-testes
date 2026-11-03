"""Mercado de MENTIRA das outras formas (sem rede; semente fixa): o cliente do copy trading (tools/mercado/falso.py:
preços de BTC, ETH, SOL e HYPE minuto a minuto por 60 dias desde 20/09/2026, funding de hora em hora) mais o que cada
forma precisa, em mixins de arquivos próprios (`falso_cofres.py`, `falso_funding.py`, `falso_robos.py`…), cada um com
os métodos que faltam no formato da API da Hyperliquid. Nada aqui é dado real.

`python3 tools/papel/falso.py [pasta]` roda várias rodadas seguidas e grava o conjunto de exemplo (com "exemplo":
true) em `exemplos/` desta pasta; o app usa a cópia em odonto-quest/tools/mercado/exemplos/papel/.
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)  # antes do mercado: os dois têm um falso.py

import importlib.util as _iu  # noqa: E402

# o falso do copy trading (tools/mercado/falso.py), carregado com outro nome (este arquivo também se chama falso.py)
_esp = _iu.spec_from_file_location("falso_mercado", os.path.join(AQUI, "..", "mercado", "falso.py"))
_base = _iu.module_from_spec(_esp)
sys.modules["falso_mercado"] = _base
_esp.loader.exec_module(_base)

HORA, DIA, T0 = _base.HORA, _base.DIA, _base.T0

_mixins = []
for _n in ("falso_cofres", "falso_funding", "falso_robos", "falso_looping", "falso_opcoes", "falso_pools", "falso_memes"):
    try:
        _mixins.append(getattr(importlib.import_module(_n), "Falso"))
    except ImportError:
        pass


# O à vista de mentira (comum a todas as formas): os pares "@N" da Hyperliquid, com o preço do perpétuo do Mundo
# um pouco abaixo (a base), como UBTC, UETH e USOL (embrulhados pela ponte) e o HYPE nativo.
SPOT = {"@142": ("UBTC", "BTC"), "@151": ("UETH", "ETH"), "@156": ("USOL", "SOL"), "@107": ("HYPE", "HYPE")}
BASE_SPOT = 0.0004  # o à vista 0,04% abaixo do perpétuo


class _Comum:
    """À vista, contextos e funding previsto, no formato da API."""

    def velas(self, moeda, intervalo, ini, fim):
        if moeda in SPOT:
            out = _base.ClienteFalso.velas(self, SPOT[moeda][1], intervalo, ini, fim)
            k = 1 - BASE_SPOT
            for c in out:
                for x in "ohlc":
                    c[x] = f"{float(c[x]) * k:.6g}"
                c["s"] = moeda
            return out
        return _base.ClienteFalso.velas(self, moeda, intervalo, ini, fim)

    def spot_meta_e_contextos(self):
        self._contar("spotMetaAndAssetCtxs")
        tokens = [{"name": "USDC", "index": 0, "szDecimals": 8}] + [
            {"name": t, "index": i + 1, "szDecimals": 5} for i, (t, _) in enumerate(SPOT.values())]
        universo = [{"name": "PURR/USDC", "tokens": [99, 0], "index": 0, "isCanonical": True}] + [
            {"name": par, "tokens": [i + 1, 0], "index": int(par[1:]), "isCanonical": False} for i, par in enumerate(SPOT)]
        ctxs = [{"markPx": "1", "midPx": "1", "dayNtlVlm": "0"}] + [
            {"markPx": f"{self.mundo.px(m, self.agora) * (1 - BASE_SPOT):.6g}", "midPx": f"{self.mundo.px(m, self.agora) * (1 - BASE_SPOT):.6g}",
             "dayNtlVlm": "5000000", "coin": par} for par, (_, m) in SPOT.items()]
        return [{"tokens": tokens, "universe": universo}, ctxs]

    def _taxa(self, m):
        f = [r for t, r in self.mundo.funding[m] if t <= self.agora]
        return f[-1] if f else 0.0

    def meta_e_contextos(self):
        self._contar("metaAndAssetCtxs")
        meta = {"universe": [{"name": m, "szDecimals": 4, "maxLeverage": v} for m, v in _base.MAX_LEV.items()]}
        ctxs = [{"funding": f"{self._taxa(m):.8f}", "markPx": f"{self.mundo.px(m, self.agora):.6g}",
                 "oraclePx": f"{self.mundo.px(m, self.agora):.6g}", "openInterest": "1000", "premium": "0.0"} for m in _base.MAX_LEV]
        return [meta, ctxs]

    def funding_previsto(self):
        self._contar("predictedFundings")
        prox = (self.agora // HORA + 1) * HORA
        return [[m, [["HlPerp", {"fundingRate": f"{self._taxa(m):.8f}", "nextFundingTime": prox, "fundingIntervalHours": 1}],
                     ["BinPerp", {"fundingRate": f"{self._taxa(m) * 8:.8f}", "nextFundingTime": prox, "fundingIntervalHours": 8}]]]
                for m in _base.MAX_LEV]


class ClientePapelFalso(*_mixins, _Comum, _base.ClienteFalso):
    """O cliente do copy trading com o comum e os métodos das formas. `agora` começa 32 dias depois do início do
    mundo (20/09/2026 + 32 dias); o mundo tem 60 dias de preços."""

    def __init__(self, mundo=None, agora=None):
        _base.ClienteFalso.__init__(self, mundo, agora)
        for m in _mixins:
            if hasattr(m, "preparar"):
                m.preparar(self)


def gerar_exemplos(pasta_saida, pasta_trabalho, rodadas=100, cada_h=6, primeira=None):
    """Roda `rodadas` seguidas (a cada `cada_h` horas) e copia o resultado final para `pasta_saida`."""
    import papel
    shutil.rmtree(pasta_trabalho, ignore_errors=True)
    cli = ClientePapelFalso()
    t = primeira or cli.agora
    for k in range(rodadas + 1):
        cli.agora = t + k * cada_h * HORA
        papel.rodada(cli, pasta_trabalho, cli.agora, exemplo=True, buscar_cdi=False, log=papel.Log(quieto=k < rodadas))
    os.makedirs(pasta_saida, exist_ok=True)
    for f in os.listdir(pasta_saida):
        if f.endswith(".json"):
            os.remove(os.path.join(pasta_saida, f))
    for f in os.listdir(pasta_trabalho):
        if f.endswith(".json") and f != "estado.json":
            shutil.copy(os.path.join(pasta_trabalho, f), pasta_saida)
    tam = {f: os.path.getsize(os.path.join(pasta_saida, f)) // 1024 for f in sorted(os.listdir(pasta_saida))}
    print(f"{pasta_saida}: {tam} KB")


if __name__ == "__main__":
    gerar_exemplos(os.path.join(AQUI, "exemplos"), sys.argv[1] if len(sys.argv) > 1 else "/tmp/orbita-papel-exemplo")
