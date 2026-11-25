"""python3 tools/papel/teste_looping_evolucao.py — a Evolução do Looping (looping_evolucao.py): os controles iguais ao
teste no passado da forma, as regras de cada gene (laço quando compensa, só na alta, defesa) e a rodada inteira no
mundo de mentira (as duas espécies, o laboratório e a liga)."""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)

import looping as LP  # noqa: E402
import looping_evolucao as LE  # noqa: E402
from conta import DIA, dia_de  # noqa: E402
from genetica import reparar  # noqa: E402

T0 = 1_767_225_600_000  # 01/01/2026 0h UTC


def ok(c, msg=""):
    if not c:
        raise AssertionError(msg)


def params():
    p = {k: dict(v) for k, v in LP.PARAMS_PADRAO.items()}
    p["emode"] = dict(LP.EMODE_PADRAO)
    return p


def diarias(n=300, f=lambda i: 3000 * (1 + 0.2 * math.sin(i / 25))):
    """Velas de 1 dia [(fim, fechamento, mínima)] do ether."""
    return [(T0 + (i + 1) * DIA, f(i), f(i) * 0.98) for i in range(n)]


def taxas(dif_dias):
    """Taxas por dia: o staking 2,8% e o juro do ether que dá a diferença `dif_dias(i)`."""
    serie = {"stake": {}, "bor:WETH": {}, "sup:wstETH": {}, "sup:WETH": {}, "bor:USDC": {}, "sup:USDC": {}}
    for i in range(320):
        d = dia_de(T0 + i * DIA)[:10]
        serie["stake"][d] = 0.028
        serie["bor:WETH"][d] = 0.028 - dif_dias(i)
        serie["sup:wstETH"][d] = 0.0
        serie["sup:WETH"][d] = 0.01
        serie["bor:USDC"][d] = 0.06
        serie["sup:USDC"][d] = 0.045
    return LP.Taxas(serie, {})


def teste_controle_igual_ao_passado():
    dd, tx, pr = diarias(), taxas(lambda i: 0.004), params()
    for esp, vid in ((LE.ESP_LACO, "wst3"), (LE.ESP_ETH, "eth2"), (LE.ESP_ETH, "eth2tend"), (LE.ESP_LACO, "wstAuto6")):
        D = LE.Dados(esp, dd, tx, pr)
        df = LE.Definicao(esp)
        genes = df.genes_controle() if vid in ("wst3", "eth2") else dict(df.sementes())[vid]
        res = LP.teste_no_passado(dd, tx, pr, inicio=dd[0][0], versoes=[next(c for c in LP.VERSOES if c[0] == vid)])[vid]
        c = LE.simular(D, genes, dia_de(dd[0][0] - 1), dia_de(dd[-1][0]))
        ok(abs(c["retorno"] - res["retorno"]) < 1e-4, (vid, c["retorno"], res["retorno"]))
        ok(c["serie"][0][0] <= c["serie"][-1][0] and c["montou"])


def teste_regras():
    dd, pr = diarias(), params()
    # o juro do ether passa o staking na 2ª metade: o laço sempre montado perde; o "quando compensa" desmonta
    tx = taxas(lambda i: 0.006 if i < 150 else -0.01)
    D = LE.Dados(LE.ESP_LACO, dd, tx, pr)
    ini, fim = dia_de(dd[0][0] - 1), dia_de(dd[-1][0])
    sempre = LE.simular(D, reparar(LE.ESP_LACO, {"alav": 6, "regra": "sempre"}), ini, fim)
    auto = LE.simular(D, reparar(LE.ESP_LACO, {"alav": 6, "regra": "compensa", "fica": 7, "diasSai": 3,
                                               "dispara": 0.01, "entra": 0.0025, "diasEntra": 7, "pagaDias": 365}),
                      ini, fim)
    ok(auto["desmontagens"] >= 1 and auto["retorno"] > sempre["retorno"], (auto, sempre["retorno"]))
    ok(auto["membros"] == ["só wstETH (1×)"], auto["membros"])
    # o ether cai 60%: o 3× sempre é liquidado; o só na alta (média de 20) sai antes; a defesa vende antes
    cai = diarias(f=lambda i: 3000 if i < 60 else max(1200, 3000 - 15 * (i - 60)))
    D = LE.Dados(LE.ESP_ETH, cai, taxas(lambda i: 0.0), pr)
    ini, fim = dia_de(cai[0][0] - 1), dia_de(cai[-1][0])
    g3 = reparar(LE.ESP_ETH, {"alav": 3, "regra": "sempre", "defesa": 0})
    a = LE.simular(D, g3, ini, fim)
    b = LE.simular(D, dict(g3, regra="alta", media=20), ini, fim)
    d = LE.simular(D, dict(g3, defesa=1.5), ini, fim)
    ok(a["liq"] >= 1 and b["retorno"] > a["retorno"] and b["membros"] == ["em dólar no Aave (fora)"], (a, b["membros"]))
    ok(d["desmontagens"] >= 1, d)
    # descrições
    df = LE.Definicao(LE.ESP_ETH)
    ok(df.descrever(dict(g3, regra="alta", media=50)) == "Ether 3×, só acima da média de 50 dias", df.descrever(g3))
    ok(LE.Definicao(LE.ESP_LACO).descrever(LE.Definicao(LE.ESP_LACO).genes_controle()) == "Laço de 3×, sempre montado")


def teste_rodada():
    import falso
    import papel
    pasta = tempfile.mkdtemp(prefix="looping-ev-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora
        for k in range(10):
            cli.agora = t0 + k * 12 * 3_600_000
            ind = papel.rodada(cli, pasta, cli.agora, formas=["looping"], exemplo=True, buscar_cdi=False,
                               log=papel.Log(quieto=True))
            ok(ind["formas"]["looping"]["ok"], ind["formas"]["looping"])
        d = json.load(open(os.path.join(pasta, "looping.json")))
        e = d.get("evolucao")
        ok(e and e["formas"][0]["id"] == "looping", d.get("erros"))
        esps = e["formas"][0]["especies"]
        ok([x["id"] for x in esps] == ["laco", "alavancado"], [x["id"] for x in esps])
        for x in esps:
            ok(x.get("lab") and x["lab"]["g"] >= 2 and x.get("liga"), (x["id"], list(x)))
        ok(not [x for x in d.get("erros") or [] if "evolu" in x], d.get("erros"))
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    for f in (teste_controle_igual_ao_passado, teste_regras, teste_rodada):
        f()
        print(f"{f.__name__}: ok")
    print("ok")
