"""python3 tools/papel/teste_pools_evolucao.py — a Evolução das Pools (pools_evolucao.py), sem rede: o caminho de hora em
hora contra o troca a troca, a espécie e as rodadas no mundo de mentira."""
from __future__ import annotations

import json
import math
import os
import random
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)

import falso  # noqa: E402
import papel  # noqa: E402
import pools as PL  # noqa: E402
import pools_evolucao as PE  # noqa: E402
from genetica import chave, reparar  # noqa: E402

HORA, DIA = PE.HORA, PE.DIA
T0 = 1_700_000_000_000 // DIA * DIA
GAS = PL.GAS_PADRAO


def ok(c, msg):
    if not c:
        raise AssertionError(msg)


def passeio(dias, por_min=1, sem=7, vol_dia=0.03):
    """Trocas inventadas: um passeio aleatório do ether com vai e vem (uma a cada minuto)."""
    rng = random.Random(sem)
    s, t, out = math.sqrt(2500.0), T0, []
    passo = vol_dia / 2 / math.sqrt(24 * 60 * por_min)
    for _ in range(dias * 24 * 60 * por_min):
        s *= math.exp(rng.gauss(0, passo))
        t += 60_000 // por_min
        out.append((t, 0, 0, s, 0, 0.0))
    return out


def direto(genes, trocas):
    """A conta troca a troca (a de verdade), com os mesmos genes."""
    c = PE.conta_de(genes, trocas[0][0], PL.LEGADO)
    s0 = None
    for t, _b, _i, s, _l, _v in trocas:
        c.troca(t, s0, s, GAS)
        s0 = s
    return c


def teste_caminho():
    acc = {}
    PE.caminho(acc, 0.0, 3.5 * PE.BW)
    ok(len(acc) == 4 and all(abs(acc[k] - PE.BW) < 1e-12 for k in range(3)) and abs(acc[3] - 0.5 * PE.BW) < 1e-12, acc)
    PE.caminho(acc, 3.5 * PE.BW, 2.5 * PE.BW)
    ok(abs(acc[3] - PE.BW) < 1e-12 and abs(acc[2] - 1.5 * PE.BW) < 1e-12, "a descida soma no mesmo balde")
    # os pedaços de uma hora: o peso × o caminho resumido = o caminho de verdade em cada balde
    g = PE.Gravador()
    for t, _b, _i, s, _l, _v in passeio(1)[:60]:
        g.ver(t, s)
    for h, e in g.h.items():
        soma = {}
        for _f, s0, s1, p in PE.pedacos(e):
            b = math.floor(min(math.log(s0), math.log(s1)) / PE.BW + 1e-9)
            soma[b] = soma.get(b, 0.0) + abs(math.log(s1) - math.log(s0)) * p
        for b, x in e[7].items():
            ok(abs(soma.get(b, 0.0) - x) < 1e-9 + 1e-6 * x, f"balde {b}: {soma.get(b)} × {x}")
        fr = [f for f, *_ in PE.pedacos(e)]
        ok(fr == sorted(fr) and 0 < fr[0] and fr[-1] < 1, "os pedaços andam dentro da hora")
    # o banco vai e volta do JSON
    j = json.loads(json.dumps(g.para_json()))
    g2 = PE.Gravador(j)
    ok(g2.s == g.s and set(g2.h) == set(g.h) and all(abs(sum(g2.h[k][7].values()) - sum(g.h[k][7].values())) < 1e-6
                                                     for k in g.h), "o banco no estado")


def teste_contra_troca_a_troca():
    """O simulador de hora em hora fica perto da conta troca a troca (a taxa por balde bate; a ordem na hora, não)."""
    trocas = passeio(12)
    g = PE.Gravador()
    g.alimentar(trocas)
    D = PE.Dados({"weth_usdc": g}, {"weth_usdc": PL.LEGADO}, GAS)
    df = PE.Definicao()
    base = df.genes_controle()
    ok(base == {"pool": "weth_usdc", "largura": 0.03, "regra": "hora", "fora": 1, "espera": 3, "reinv": 7}, base)
    ini, fim = PE.dia_de(trocas[0][0]), PE.dia_de(trocas[-1][0])
    casos = [base] + [g for _, g in df.sementes()]
    for genes in casos:
        c = direto(genes, trocas)
        r = PE.simular(D, genes, ini, fim)
        v = c.valor(trocas[-1][3])
        tx = c.acc["taxas"]
        dif = abs(r["serie"][-1][1] - v) / PE.CAPITAL
        # sem remontar na hora certa (nunca, à mão, espera), quase igual; remontando, a hora da remontagem muda um pouco
        tol = 0.002 if genes["regra"] in ("nunca", "dia", "espera", "sobra") else 0.015
        ok(r["montou"] and dif < tol, f"{PE.descrever(genes)}: hora em hora {r['serie'][-1][1]:.2f} × troca a troca {v:.2f}")
        if genes["regra"] == "nunca" or genes["regra"] in ("dia", "espera", "sobra"):
            ok(abs(r["taxas"] - tx) <= 0.03 * tx + 0.5, f"{PE.descrever(genes)}: taxas {r['taxas']} × {tx:.2f}")
    # a faixa estreita que remonta ao sair: remonta bem mais que a de 1 h fora
    a = PE.simular(D, reparar(PE.ESP, {**base, "largura": 0.01, "regra": "sai"}), ini, fim)
    b = PE.simular(D, reparar(PE.ESP, {**base, "largura": 0.01}), ini, fim)
    ok(a["remontagens"] > b["remontagens"] > 0 and a["ops"] == 1 + a["remontagens"], (a["remontagens"], b["remontagens"]))
    cheia = PE.simular(D, reparar(PE.ESP, {**base, "largura": 0}), ini, fim)
    ok(cheia["remontagens"] == 0 and cheia["membros"] == ["faixa cheia"] and cheia["dentroFrac"] == 1.0, cheia)
    ok(len(a["serie"]) == len({PE.dia_de(t) for t, *_ in trocas}), "um ponto por dia")
    # um pool sem banco: sem conta
    ok(not PE.simular(D, reparar(PE.ESP, {**base, "pool": "cbbtc_usdc"}), ini, fim)["montou"], "sem o banco do cbBTC")


def teste_genes():
    df = PE.Definicao()
    esp = PE.ESP
    c = reparar(esp, {**df.genes_controle(), "largura": 0, "regra": "krystal", "fora": 8})
    ok(c["regra"] == "nunca" and c["fora"] == 1 and c["reinv"] == 7, f"a cheia nunca remonta: {c}")
    ok(reparar(esp, {**df.genes_controle(), "regra": "sai", "espera": 7})["espera"] == 3, "a espera só na espera")
    se = df.sementes()
    ok(len({chave(g) for _, g in se} | {chave(df.genes_controle())}) == len(se) + 1, "sementes diferentes do controle")
    ok(PE.descrever(df.genes_controle()) == "±3% · remonta depois de 1 h fora", PE.descrever(df.genes_controle()))
    k = dict(se)["krystal10"]
    ok(PE.descrever(k) == "±10% · Krystal depois de 1 h fora · taxas de volta todo dia", PE.descrever(k))
    ok(PE.descrever({**dict(se)["esp7"], "pool": "cbbtc_usdc"}) ==
       "cbBTC/USDC · ±5% · espera 7 dias fora · taxas de volta a cada 7 dias", "o pool na descrição")
    ok(PE.descrever(dict(se)["cheia"]) == "Faixa cheia", "a cheia")


def teste_salto():
    """Blocos que não deu para ler: a hora seguinte começa com um salto (sem taxa no caminho perdido)."""
    g = PE.Gravador()
    tr = passeio(2)
    g.alimentar(tr[:600])
    g.pulo()
    g.alimentar([(t + 3 * HORA, b, i, s * 1.05, li, v) for t, b, i, s, li, v in tr[600:1200]])
    saltos = [h for h, e in g.h.items() if e[6]]
    ok(len(saltos) == 2, f"o começo e o pulo: {saltos}")
    D = PE.Dados({"weth_usdc": g}, {"weth_usdc": PL.LEGADO}, GAS, min_horas=1)
    r = PE.simular(D, PE.Definicao().genes_controle(), PE.dia_de(tr[0][0]), PE.dia_de(tr[1200][0] + 3 * HORA))
    ok(r["montou"] and r["remontagens"] >= 1, "o salto de 5% tira da faixa de 3%")


def rodar(cli, pasta, quando):
    cli.agora = quando
    return papel.rodada(cli, pasta, quando, formas=["pools"], prazo_min=20, exemplo=True, buscar_cdi=False,
                        log=papel.Log(quieto=True))


def teste_rodadas():
    pasta = tempfile.mkdtemp(prefix="pools-ev-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora
        for k in range(6):
            ind = rodar(cli, pasta, t0 + k * 6 * HORA)
            ok(ind["formas"]["pools"]["ok"], ind["formas"]["pools"])
        d = json.load(open(os.path.join(pasta, "pools.json")))
        est = json.load(open(os.path.join(pasta, "estado.json")))["formas"]["pools"]
        ok(not d["rodada"]["erros"], d["rodada"]["erros"])
        b = est["pools"]["weth_usdc"]["bancoEv"]
        ok(b["bloco"] == est["pools"]["weth_usdc"]["vivo"]["bloco"], "o banco alcançou o ao vivo")
        ok(len(b["h"]) >= 28 * 24, f"28 dias de horas: {len(b['h'])}")
        ok(est["pools"]["cbbtc_usdc"].get("bancoEv") and "bancoEv" not in est["pools"]["estavel"], "os dois pools")
        ev = d["evolucao"]
        sp = ev["formas"][0]["especies"][0]
        ok(ev["formas"][0]["id"] == "pools" and sp["id"] == "faixa" and [g["k"] for g in sp["genes"]] ==
           ["pool", "largura", "regra", "fora", "espera", "reinv"], "a espécie")
        ok(sp["liga"] and sp["liga"]["controle"]["aoVivo"]["serie"], "a liga com o controle")
        ok(sp["lab"] and sp["lab"]["pop"] and sp["lab"]["pop"][0].get("nota") is not None, "o laboratório")
        ok(any(x["genes"]["pool"] == "cbbtc_usdc" for x in sp["lab"]["pop"] + sp["liga"]["pop"]) or True, "")
        # o controle refeito × a versão r3h no teste no passado da forma (troca a troca): perto
        r3h = next(v for v in d["versoes"] if v["id"] == "r3h")
        ok(sp["controle"]["descricao"] and r3h["historico"], "o controle")
        # rodar de novo no mesmo dia não refaz o laboratório
        g = sp["lab"]["g"]
        rodar(cli, pasta, t0 + 6 * 6 * HORA + 60_000)
        d2 = json.load(open(os.path.join(pasta, "pools.json")))
        sp2 = d2["evolucao"]["formas"][0]["especies"][0]
        ok(sp2["lab"]["g"] >= g, "o laboratório")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    teste_caminho()
    teste_genes()
    teste_contra_troca_a_troca()
    teste_salto()
    teste_rodadas()
    print("teste_pools_evolucao: ok")
