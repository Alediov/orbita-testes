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


class ClientePapelFalso(*_mixins, _base.ClienteFalso):
    """O cliente do copy trading com os métodos das formas. `agora` começa 32 dias depois do início do mundo."""

    def __init__(self, mundo=None, agora=None):
        _base.ClienteFalso.__init__(self, mundo, agora)
        for m in _mixins:
            if hasattr(m, "preparar"):
                m.preparar(self)


def gerar_exemplos(pasta_saida, pasta_trabalho, rodadas=28, cada_h=6, primeira=None):
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
