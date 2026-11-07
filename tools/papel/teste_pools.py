"""Testes dos pools no papel (sem rede). Uso: python3 tools/papel/teste_pools.py"""
from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)  # antes do mercado: os dois têm um falso.py

import falso  # noqa: E402
import falso_pools as FP  # noqa: E402
import papel  # noqa: E402
import pools as PL  # noqa: E402
from teste_papel import conferir_forma  # noqa: E402

HORA, DIA = falso.HORA, falso.DIA
T0 = 1_700_000_000_000 // DIA * DIA
MIN = 60_000


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def cfg(vid):
    return next(c for c in PL.VERSOES if c[0] == vid)


def sem_custos():
    g = (PL.TAXA_POOL, PL.DESLIZE, PL.L1_US)
    PL.TAXA_POOL = PL.DESLIZE = PL.L1_US = 0.0  # a taxa ganha (taxa_no_trecho) continua 0,05%
    return g


def com_custos(g):
    PL.TAXA_POOL, PL.DESLIZE, PL.L1_US = g


def sq(p):
    return math.sqrt(p)


# ------------------------------------------------------------------------------------------- matemática do v3
def teste_matematica():
    sa, sb = sq(2400), sq(2600)
    x, y = PL.quantias(1.0, sq(2500), sa, sb)
    assert perto(x, 1 / 50 - 1 / sb) and perto(y, 50 - sa)
    assert PL.quantias(1.0, sq(2300), sa, sb)[1] == 0 and PL.quantias(1.0, sq(2700), sa, sb)[0] == 0
    # contínuo nas pontas
    assert perto(PL.quantias(1.0, sa, sa, sb)[0], PL.quantias(1.0, sa * 0.999999, sa, sb)[0], 1e-5)
    # a faixa cai nos ticks do pool (espaço 10) e contém P × (1 ± largura)
    a, b = PL.faixa(sq(2500), 0.03)
    for s in (a, b):
        t = PL.tick_do_s(s)
        assert abs(t - round(t)) < 1e-6 and round(t) % 10 == 0
    assert PL.preco_de(a) <= 2500 * 0.97 and PL.preco_de(b) >= 2500 * 1.03 and PL.preco_de(b) < 2500 * 1.032
    cheia = PL.faixa(sq(2500), None)
    assert PL.preco_de(cheia[0]) < 1e-20 and PL.preco_de(cheia[1]) > 1e20
    # a taxa num trecho: subida → USDC; descida → WETH; só a parte dentro da faixa
    k = 0.0005 / 0.9995
    assert perto(PL.taxa_no_trecho(2.0, 49, 50, 40, 60)[1], 2.0 * 1 * k)
    assert perto(PL.taxa_no_trecho(2.0, 50, 49, 40, 60)[0], 2.0 * (1 / 49 - 1 / 50) * k)
    assert perto(PL.taxa_no_trecho(2.0, 58, 62, 40, 60)[1], 2.0 * 2 * k)  # só até o fim da faixa
    assert PL.taxa_no_trecho(2.0, 61, 62, 40, 60) == (0.0, 0.0)


def teste_evento():
    cli = falso.ClientePapelFalso()
    b = FP.B0 + 9 * 1000
    log = cli._evento(b)
    t, bloco, _i, s, liq, vol = PL.ler_evento(log, FP.B0, 1_000_000)
    assert bloco == b and t == 1_000_000 + 9 * 1000 * 2000 and liq == FP.LIQ and vol > 0
    assert perto(PL.preco_de(s), cli._px(b), 1e-6)
    assert PL.ler_evento({"data": "0x12", "blockNumber": "0x1"}, 0, 0) is None
    # amount1 negativo (o ether foi comprado): o volume é o valor absoluto
    d = "0x" + "".join(FP._palavra(v) for v in (10 ** 18, -2_500_000_000, int(50e-6 * 2 ** 96), 1, -200_000))
    assert perto(PL.ler_evento({"data": d, "blockNumber": "0x5"}, 0, 0)[5], 2500)


# ------------------------------------------------------------------------------------------- contas
def caminho(c, precos, t0=T0, passo=MIN, s0=None):
    s_ant = s0
    t = t0
    for p in precos:
        s = sq(p)
        c.troca(t, s_ant, s, 0)
        s_ant = s
        t += passo
    return t


def teste_conta_taxas():
    g = sem_custos()
    try:
        c = PL.Conta(cfg("r3h"), T0)
        c.troca(T0, None, sq(2500), 0)
        assert perto(c.curva.ultimo, 1000) and c.montada and c.dentro(sq(2500))
        L = c.L
        # vai a 2.550 e volta: ganha a taxa nos dois sentidos, o valor volta (sem perda impermanente líquida)
        caminho(c, [2550, 2500], T0 + MIN, s0=sq(2500))
        k = 0.0005 / 0.9995
        fy = L * (sq(2550) - sq(2500)) * k
        fx = L * (1 / sq(2500) - 1 / sq(2550)) * k
        assert perto(c.fy, fy) and perto(c.fx, fx)
        assert perto(c.valor(sq(2500)), 1000 + fy + fx * 2500)
        assert perto(c.acc["taxas"], fy + fx * 2500)
        c.marcar(T0 + 3 * MIN)
        x = c.curva.extra
        assert perto(x["taxasGanhas"], fy + fx * 2500, 1e-3) and x["dentro"] and x["reposicoes"] == 0
        assert abs(x["perdaImp"]) < 1e-6
    finally:
        com_custos(g)


def teste_reposicionar():
    g = sem_custos()
    try:
        sai = PL.Conta(cfg("r1"), T0)
        hora = PL.Conta(cfg("r1h"), T0)
        fixa = PL.Conta(cfg("r3fixa"), T0)
        seg = PL.Conta(cfg("segurar"), T0)
        cheia = PL.Conta(cfg("cheia"), T0)
        for c in (sai, hora, fixa, seg, cheia):
            c.troca(T0, None, sq(2500), 0)
        # sobe 5% e fica: "ao sair" reposiciona na hora; "1 h fora" só depois de 1 h; a fixa nunca
        precos = [2525, 2550, 2600, 2625] + [2625] * 70
        for c in (sai, hora, fixa, seg, cheia):
            caminho(c, precos, T0 + MIN, s0=sq(2500))
        assert sai.acc["repos"] >= 1 and hora.acc["repos"] == 1 and fixa.acc["repos"] == 0
        assert sai.dentro(sq(2625)) and hora.dentro(sq(2625)) and not fixa.dentro(sq(2625))
        # a fixa ficou toda em dólar (a faixa de 3% ficou para trás) e com perda impermanente contra segurar
        x, y = fixa.tokens(sq(2625))
        assert x == 0 and y > 0 and fixa.perda_imp(sq(2625)) < 0
        # segurar 50/50: metade em ether, metade em dólar
        assert perto(seg.valor(sq(2625)), 500 * 2625 / 2500 + 500)
        assert cheia.dentro(sq(2625)) and cheia.acc["repos"] == 0
        # sem custos, reposicionar não muda o valor na hora; com custos, cobra a troca + o gás
        v = hora.valor(sq(2625))
        hora.reposicionar(T0 + 2 * HORA, sq(2625), 0)
        assert perto(hora.valor(sq(2625)), v)
    finally:
        com_custos(g)
    c = PL.Conta(cfg("r3"), T0)
    c.troca(T0, None, sq(2500), 10_000_000)
    gas = 10_000_000 * PL.GAS_UNIDADES / 1e18 * 2500 + PL.L1_US
    # pôr: troca de ~metade do dinheiro (0,05% + deslize) e o gás
    assert 1000 - gas - 500 * 0.0006 * 1.1 < c.curva.ultimo < 1000 - gas - 500 * 0.0006 * 0.9
    assert perto(c.curva.taxas, 1000 - c.valor(sq(2500)), 1e-9)


def teste_resumo_do_dia():
    ev = PL.Eventos()
    c = PL.Conta(cfg("r1"), T0)
    c.troca(T0, None, sq(2500), 0, ev)
    t = T0 + MIN
    s0 = sq(2500)
    for k in range(3):
        for p in (2560, 2440):
            c.troca(t, s0, sq(p), 0, ev)
            s0, t = sq(p), t + MIN
    c.troca(T0 + 2 * DIA, s0, sq(2450), 0, ev)
    rs = [e for e in ev.lista if e["tipo"] == "reequilibrou"]
    assert len(rs) == 1 and "Reposicionou 6 vezes" in rs[0]["texto"], rs


# ------------------------------------------------------------------------------------------- leitura
def teste_ler_trocas():
    cli = falso.ClientePapelFalso()
    topo = FP.B0 + 10 * PL.BLOCOS_DIA
    cli.agora = cli._t_de(topo)
    ref = (topo, cli._t_de(topo))
    cli.max_eventos = 1000
    ped = {"n": 40_000}
    vistos, total = [], 0
    logs = []
    for b, trocas in PL.ler_trocas(cli.rpc, topo - PL.BLOCOS_DIA, topo, ref, ped, lambda: True, logs.append):
        vistos.append(b)
        total += len(trocas)
        assert all(trocas[i][1] <= trocas[i + 1][1] for i in range(len(trocas) - 1))
    assert vistos[-1] == topo and ped["n"] < 40_000 and any("recusado" in x for x in logs)
    # ~uma troca a cada 9 blocos × 0,9
    assert 0.8 * PL.BLOCOS_DIA / 9 < total < 1.0 * PL.BLOCOS_DIA / 9
    # blocos antigos demais: Arquivo
    try:
        list(PL.ler_trocas(cli.rpc, topo - 40 * PL.BLOCOS_DIA, topo, ref, {"n": 1000}, lambda: True, logs.append))
        assert False, "devia recusar"
    except PL.Arquivo:
        pass
    # sem tempo: não pede nada
    assert list(PL.ler_trocas(cli.rpc, topo - 100, topo, ref, {"n": 1000}, lambda: False, logs.append)) == []


# ------------------------------------------------------------------------------------------- rodadas
def rodar(cli, pasta, quando, prazo=20):
    cli.agora = quando
    return papel.rodada(cli, pasta, quando, formas=["pools"], prazo_min=prazo, exemplo=True, buscar_cdi=False,
                        log=papel.Log(quieto=True))


def ler(pasta):
    with open(os.path.join(pasta, "pools.json")) as f:
        return json.load(f)


def conferir(d, com_hist=True):
    conferir_forma(d, "pools")
    assert d["padrao"] == "r3h" and {v["id"] for v in d["versoes"]} == {v[0] for v in PL.VERSOES}
    for v in d["versoes"]:
        assert v["aoVivo"] is not None, v["id"]
        assert {"taxasGanhas", "gasPago", "reposicoes", "precoEth"} <= set(v["aoVivo"]["extra"])
        if v["id"] != "segurar":
            assert {"perdaImp", "dentro", "dentroFrac"} <= set(v["aoVivo"]["extra"])
        if com_hist:
            assert v["historico"] and v["historico"]["aproximado"] is False and v["historico"]["nota"]
    assert d["config"]["gasWei"] > 0 and d["config"]["precoEth"] > 0


def teste_rodadas():
    a = tempfile.mkdtemp(prefix="pools-a-")
    b = tempfile.mkdtemp(prefix="pools-b-")
    try:
        cli_a, cli_b = falso.ClientePapelFalso(), falso.ClientePapelFalso()
        t0 = cli_a.agora
        pulos = {t0 + k * 6 * HORA for k in range(3, 7)}
        for k in range(12):
            q = t0 + k * 6 * HORA
            ind = rodar(cli_a, a, q)
            assert ind["formas"]["pools"]["ok"], ind["formas"]["pools"]
            if q not in pulos:
                rodar(cli_b, b, q)
            conferir(ler(a))
        da, db = ler(a), ler(b)
        for va, vb in zip(da["versoes"], db["versoes"]):
            # alcançar dá o mesmo (as que reposicionam só diferem pelo gás, medido a cada rodada: B mediu menos vezes)
            sa, sb = va["aoVivo"]["serie"], vb["aoVivo"]["serie"]
            assert [d for d, _ in sa] == [d for d, _ in sb] and all(perto(x, y, 1e-4) for (_, x), (_, y) in zip(sa, sb)), va["id"]
            assert va["aoVivo"]["ops"] == vb["aoVivo"]["ops"], va["id"]
            if va["id"] in ("cheia", "r3fixa", "segurar"):
                assert sa == sb and va["aoVivo"]["piorQueda"] == vb["aoVivo"]["piorQueda"]
        assert da["config"]["passado"]["alcancou"] and da["config"]["trocasLidas"]["hist"] > 100_000
        assert da["config"]["conferencia"]["fonte"] == "GeckoTerminal"
        assert not da["rodada"]["erros"], da["rodada"]["erros"]
        r1 = next(v for v in da["versoes"] if v["id"] == "r1")["historico"]
        cheia = next(v for v in da["versoes"] if v["id"] == "cheia")["historico"]
        # a faixa estreita ganha muito mais taxa por dólar e reposiciona muito mais
        assert r1["extra"]["taxasGanhas"] > 20 * cheia["extra"]["taxasGanhas"] and r1["extra"]["reposicoes"] > 50
        assert "abriu" in {e["tipo"] for e in da["eventos"]}
        assert da["rodada"]["pedidos"] < 20  # uma rodada normal: poucos pedidos
        # falha do RPC: ok false e o arquivo da rodada boa fica
        antes = ler(a)
        cli_a.rpc_falhar.add("eth_getLogs")
        ind = rodar(cli_a, a, t0 + 12 * 6 * HORA)
        assert ind["formas"]["pools"]["ok"] is False and ler(a) == antes
        cli_a.rpc_falhar.clear()
        ind = rodar(cli_a, a, t0 + 13 * 6 * HORA)
        assert ind["formas"]["pools"]["ok"]
        conferir(ler(a))
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


def teste_passado_aos_poucos():
    """Sem tempo para os 28 dias de uma vez: o ao vivo anda e o passado continua nas rodadas seguintes."""
    a = tempfile.mkdtemp(prefix="pools-c-")
    try:
        cli = falso.ClientePapelFalso()
        cli.max_eventos = 2000
        relogio = {"n": 0}
        orig = PL.ler_trocas

        def devagar(rpc, de, ate, ref, ped, tempo, log):
            # cada pedaço "gasta" tempo: só 3 pedaços por rodada
            def t():
                relogio["n"] += 1
                return relogio["n"] % 4 != 0 and tempo()
            yield from orig(rpc, de, ate, ref, ped, t, log)
        PL.ler_trocas = devagar
        try:
            t0 = cli.agora
            rodar(cli, a, t0)
            d = ler(a)
            assert d["config"]["passado"]["alcancou"] is False and d["config"]["passado"]["faltamDias"] > 20
            assert all(v["aoVivo"] for v in d["versoes"])
            for k in range(1, 400):
                rodar(cli, a, t0 + k * 6 * HORA)
                if ler(a)["config"]["passado"]["alcancou"]:
                    break
            d = ler(a)
            assert d["config"]["passado"]["alcancou"], d["config"]["passado"]
            conferir(d)
        finally:
            PL.ler_trocas = orig
    finally:
        shutil.rmtree(a, ignore_errors=True)


def teste_pool_errado():
    """Se o pool não for o WETH/USDC 0,05% (token0 ou taxa diferentes), a forma falha em vez de simular errado."""
    a = tempfile.mkdtemp(prefix="pools-d-")
    try:
        cli = falso.ClientePapelFalso()
        orig = cli.rpc

        def rpc(m, p, rede_=None):
            if m == "eth_call" and p[0]["data"].startswith(PL.SEL_FEE):
                return "0x" + FP._palavra(3000)
            return orig(m, p, rede_)
        cli.rpc = rpc
        log = papel.Log(quieto=True)
        ind = papel.rodada(cli, a, cli.agora, formas=["pools"], exemplo=True, buscar_cdi=False, log=log)
        assert "pools" not in ind["formas"] and not os.path.exists(os.path.join(a, "pools.json"))
        assert any("não é o esperado" in x for x in log.linhas)
    finally:
        shutil.rmtree(a, ignore_errors=True)


if __name__ == "__main__":
    teste_matematica()
    teste_evento()
    teste_conta_taxas()
    teste_reposicionar()
    teste_resumo_do_dia()
    teste_ler_trocas()
    teste_rodadas()
    teste_passado_aos_poucos()
    teste_pool_errado()
    print("ok")
