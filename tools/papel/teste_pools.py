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
def teste_a_mao():
    """"dia": só reposiciona na olhada do meio-dia (Brasília) e põe as taxas de volta a cada 7 dias."""
    g = sem_custos()
    try:
        c = PL.Conta(cfg("dia5"), T0)  # T0 = 0h UTC = 21h em Brasília
        c.troca(T0, None, sq(2500), 0)
        s0 = sq(2500)
        # sobe 8% às 22h (Brasília): fora da faixa de 5%, mas ninguém olha até o meio-dia seguinte
        c.troca(T0 + HORA, s0, sq(2700), 0)
        c.troca(T0 + 10 * HORA, sq(2700), sq(2700), 0)
        assert c.acc["repos"] == 0 and not c.dentro(sq(2700))
        c.troca(T0 + 16 * HORA, sq(2700), sq(2700), 0)  # 13h em Brasília: olhou e reposicionou
        assert c.acc["repos"] == 1 and c.dentro(sq(2700)) and c.olhou == (T0 + 16 * HORA + PL.FUSO_MS) // DIA
        # uma semana de vai e vem dentro da faixa: as taxas acumulam e voltam para a posição
        t, s_ant = T0 + 17 * HORA, sq(2700)
        L0 = c.L
        while t < T0 + 9 * DIA:
            for p_ in (2720, 2680):
                c.troca(t, s_ant, sq(p_), 0)
                s_ant, t = sq(p_), t + 30 * MIN
        assert c.acc["reinv"] >= 1 and c.L > L0 and c.fx + c.fy * 0 < 1e-3
        c.marcar(t)
        assert c.curva.extra["reinvestimentos"] == c.acc["reinv"]
    finally:
        com_custos(g)


def rodar(cli, pasta, quando, prazo=20):
    cli.agora = quando
    return papel.rodada(cli, pasta, quando, formas=["pools"], prazo_min=prazo, exemplo=True, buscar_cdi=False,
                        log=papel.Log(quieto=True))


def ler(pasta):
    with open(os.path.join(pasta, "pools.json")) as f:
        return json.load(f)


VERSOES_WETH = {v[0] for v in PL.VERSOES}
NOVOS = {"cbbtc_usdc", "weth_cbbtc", "aero_weth_usdc", "estavel"}


def conferir(d, com_hist=True):
    conferir_forma(d, "pools")
    assert d["padrao"] == "r3h"
    weth = [v for v in d["versoes"] if v["pool"] == "weth_usdc"]
    assert {v["id"] for v in weth} == VERSOES_WETH
    ids_pools = {p["id"] for p in d["pools"]}
    assert {"weth_usdc"} | NOVOS <= ids_pools and "brz" in ids_pools, ids_pools
    por_pool = {}
    for v in d["versoes"]:
        por_pool.setdefault(v["pool"], []).append(v)
        assert v["aoVivo"] is not None, v["id"]
        assert {"taxasGanhas", "gasPago", "reposicoes", "preco", "naBase", "naCotacao"} <= set(v["aoVivo"]["extra"]), v["id"]
        if v["pool"] == "weth_usdc":
            assert "precoEth" in v["aoVivo"]["extra"]
        if not v["id"].endswith("segurar"):
            assert {"perdaImp", "dentro", "dentroFrac"} <= set(v["aoVivo"]["extra"]), v["id"]
        if com_hist:
            h = v["historico"]
            assert h and h["nota"], v["id"]
            assert h["aproximado"] is (v["grupo"] == "No gauge (AERO)"), v["id"]
    for p in d["pools"]:
        if p["observador"]:
            assert p["id"] not in por_pool and p["nota"]
            continue
        assert p["padrao"] in {v["id"] for v in por_pool[p["id"]]}, p
        assert set(p["versoes"]) == {v["id"] for v in por_pool[p["id"]]}
        assert p["volume24h"] > 0 and p["tvl"] > 0 and p["giro"] > 0 and p["aprTaxas"] > 0, p
    assert d["config"]["gasWei"] > 0 and d["config"]["precoEth"] > 0


def teste_seletores():
    """O keccak de keccak.py bate com os valores conhecidos do Ethereum."""
    import keccak
    assert keccak.keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    assert PL.TOPICO_SWAP == "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"
    assert PL.SEL_TOKEN0 == "0x0dfe1681" and PL.SEL_FEE == "0xddca3f43" and PL.SEL_SALDO == "0x70a08231"
    assert PL.SEL_GETPOOL_UNI == "0x1698ee82" and PL.SEL_DECIMAIS == "0x313ce567"


def teste_par_invertido():
    """cbBTC/USDC tem o USDC como token0: o preço da base é 1/P e o valor sai em US$ do mesmo jeito."""
    par = PL.Par({"endereco": "0x1", "dex": "uni", "token0": PL.USDC, "token1": PL.TOKENS["cbBTC"][0], "sim0": "USDC",
                  "sim1": "cbBTC", "base": "cbBTC", "cotacao": "USDC", "dec0": 6, "dec1": 8, "fee": 500, "espaco": 10})
    p_btc = 70_000.0
    s = math.sqrt(1 / p_btc)  # cbBTC por USDC
    assert perto(par.preco_base(s), p_btc) and perto(par.usd_t1(s, 0), p_btc)
    c = PL.Conta({"id": "x", "nome": "x", "largura": None, "mult": 3.0, "regra": "hora", "risco": "médio", "frase": "",
                  "gauge": False}, T0, None, par)
    c.troca(T0, None, s, 0, sigma=0.02)
    assert 990 < c.curva.ultimo < 1000 and perto(c.w, 0.06)
    lo, hi = c.faixa_precos()
    assert lo < p_btc * 0.95 and hi > p_btc * 1.05 and lo > p_btc * 0.93 and hi < p_btc * 1.07
    c.marcar(T0 + MIN)
    x = c.curva.extra
    assert perto(x["naBase"] + x["naCotacao"], c.curva.ultimo, 1e-3) and 400 < x["naBase"] < 600


def teste_volatilidade():
    v = PL.Volatilidade(0.03)
    assert perto(v.dia(), 0.03)
    s = 50.0
    for h in range(24 * 60):  # 60 dias de ±0,5% por hora: diária ≈ 0,5% × √24 ≈ 2,45%
        s *= math.sqrt(1.005 if h % 2 else 1 / 1.005)
        v.ver(T0 + h * HORA, s)
    assert 0.022 < v.dia() < 0.027, v.dia()


def teste_gauge():
    """No gauge: não ganha taxa, ganha AERO pela parte da liquidez em stake e vende uma vez por dia."""
    par = PL.Par({"endereco": "0x1", "dex": "aero", "fee": 500, "espaco": 100, "unstakedFee": 100_000, "gauge": "0x2"})
    base = {"nome": "x", "largura": None, "mult": 3.0, "regra": "hora", "risco": "médio", "frase": ""}
    g = PL.Conta({**base, "id": "g", "gauge": True}, T0, None, par)
    f = PL.Conta({**base, "id": "f", "gauge": False}, T0, None, par)
    aero = (0.06, 0.5, 1.0)
    liq = 10 ** 18
    for c in (g, f):
        c.troca(T0, None, sq(2500), 0, sigma=0.03, liq=liq, aero=aero)
    s_ant, t = sq(2500), T0
    for k in range(2 * 24 * 60):
        t += MIN
        p = sq(2500 * (1.001 if k % 2 else 0.999))
        for c in (g, f):
            c.troca(t, s_ant, p, 10_000_000, sigma=0.03, liq=liq, aero=aero)
        s_ant = p
    assert g.acc["taxas"] == 0 and g.acc["aero"] > 0 and g.acc["aeroUS"] > 0 and f.acc["taxas"] > 0
    Lr = g.L * par.escala_l
    esperado = 0.06 * (2 * 24 * 3600 - 60) * Lr / (0.5 * liq + Lr)
    assert perto(g.acc["aero"], esperado, 0.02), (g.acc["aero"], esperado)
    # sem gauge: a taxa é 90% da que ganharia (10% vai para o gauge)
    par.unstaked = 0
    h = PL.Conta({**base, "id": "h", "gauge": False}, T0, None, par)
    h.troca(T0, None, sq(2500), 0, sigma=0.03)
    s_ant, t = sq(2500), T0
    for k in range(2 * 24 * 60):
        t += MIN
        p = sq(2500 * (1.001 if k % 2 else 0.999))
        h.troca(t, s_ant, p, 10_000_000, sigma=0.03)
        s_ant = p
    assert perto(f.acc["taxas"], 0.9 * h.acc["taxas"], 0.01)
    g.marcar(t)
    assert g.curva.extra["aeroGanho"] > 0 and "aeroVendido" in g.curva.extra


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
        assert [v["id"] for v in da["versoes"]] == [v["id"] for v in db["versoes"]]
        for va, vb in zip(da["versoes"], db["versoes"]):
            if va["grupo"] == "No gauge (AERO)":
                continue  # o AERO depende das amostras do gauge, uma por rodada
            # alcançar dá o mesmo (as que reposicionam só diferem pelo gás, medido a cada rodada: B mediu menos vezes)
            sa, sb = va["aoVivo"]["serie"], vb["aoVivo"]["serie"]
            tol = 1e-4 if va["pool"] == "weth_usdc" else 2e-3
            assert [d for d, _ in sa] == [d for d, _ in sb] and all(perto(x, y, tol) for (_, x), (_, y) in zip(sa, sb)), va["id"]
            assert va["aoVivo"]["ops"] == vb["aoVivo"]["ops"], va["id"]
            if va["id"] in ("cheia", "r3fixa", "segurar"):
                assert sa == sb and va["aoVivo"]["piorQueda"] == vb["aoVivo"]["piorQueda"]
        assert da["config"]["passado"]["alcancou"] and da["config"]["trocasLidas"]["hist"] > 100_000
        assert da["config"]["conferencia"]["fonte"] == "GeckoTerminal" and da["config"]["pools"] == 5
        assert not da["rodada"]["erros"], da["rodada"]["erros"]
        vs = {v["id"]: v for v in da["versoes"]}
        r1, cheia = vs["r1"]["historico"], vs["cheia"]["historico"]
        # a faixa estreita ganha muito mais taxa por dólar e reposiciona muito mais
        assert r1["extra"]["taxasGanhas"] > 20 * cheia["extra"]["taxasGanhas"] and r1["extra"]["reposicoes"] > 50
        assert "abriu" in {e["tipo"] for e in da["eventos"]}
        assert da["rodada"]["pedidos"] < 60  # uma rodada normal: poucos pedidos
        ps = {p["id"]: p for p in da["pools"]}
        # a escolha: o de mais trocas entre os candidatos (no Aerodrome, com gauge)
        assert ps["cbbtc_usdc"]["endereco"].lower() == "0xfbb6eed8e7aa03b138556eedaf5d271a5e1e43ef"
        assert ps["aero_weth_usdc"]["endereco"].lower() == "0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59"
        assert ps["estavel"]["par"] == "USDT/USDC" and ps["estavel"]["dex"] == "Aerodrome"
        assert ps["brz"]["observador"] and "Pouco volume" in ps["brz"]["nota"]
        assert len(ps["aero_weth_usdc"]["escolha"]["candidatos"]) == 2
        g = ps["aero_weth_usdc"]["gauge"]
        assert g["aeroDia"] > 0 and g["precoAero"] and 0 < g["fracStake"] <= 1 and g["aprEmissoes"] > 0
        # as faixas seguem a volatilidade de cada par: a "média" dos dólares é muito mais estreita que a do ether
        assert ps["estavel"]["larguras"]["med"] < ps["aero_weth_usdc"]["larguras"]["med"] / 10
        assert vs["aer-medg"]["historico"]["extra"]["aeroGanho"] > 0 and vs["aer-medg"]["historico"]["extra"]["taxasGanhas"] == 0
        assert vs["aer-med"]["historico"]["extra"]["taxasGanhas"] > 0
        # medida em bitcoin: o preço do bitcoin do início e o valor em dólar de verdade
        e = vs["ecb-segurar"]["aoVivo"]["extra"]
        assert e["precoRef"] > 0 and e["emDolar"] > 0
        for v in da["versoes"]:
            m = v["aoVivo"].get("metricas")
            assert m and "cdi" in m and "excesso" in m, v["id"]
        # falha do RPC: ok false e o arquivo da rodada boa fica
        antes = ler(a)
        cli_a.rpc_falhar.add("eth_getLogs")
        ind = rodar(cli_a, a, t0 + 12 * 6 * HORA)
        assert ind["formas"]["pools"]["ok"] is False and ler(a) == antes
        cli_a.rpc_falhar.clear()
        ind = rodar(cli_a, a, t0 + 13 * 6 * HORA)
        assert ind["formas"]["pools"]["ok"]
        conferir(ler(a))
        # um pool novo que para de responder: a forma segue, ele fica parado na saída (com o erro)
        FP_end = "0xfBB6Eed8e7aa03B138556eeDaF5D271A5E1e43ef"
        est = json.load(open(os.path.join(a, "estado.json")))
        est["formas"]["pools"]["pools"]["cbbtc_usdc"]["conferido"] = 1
        papel.gravar_json(os.path.join(a, "estado.json"), est)
        cli_a.pools_fora.add(FP_end)
        ind = rodar(cli_a, a, t0 + 14 * 6 * HORA)
        d = ler(a)
        assert ind["formas"]["pools"]["ok"] and any("cbbtc_usdc" in x for x in d["rodada"]["erros"])
        assert any(v["pool"] == "cbbtc_usdc" for v in d["versoes"])
        cli_a.pools_fora.clear()
        # uma versão nova (sem passado no estado): o teste no passado recomeça para todas daquele pool
        est = json.load(open(os.path.join(a, "estado.json")))
        del est["formas"]["pools"]["pools"]["weth_usdc"]["hist"]["contas"]["dia5"]
        papel.gravar_json(os.path.join(a, "estado.json"), est)
        cli_a.agora = t0 + 15 * 6 * HORA
        log = papel.Log(quieto=True)
        papel.rodada(cli_a, a, cli_a.agora, formas=["pools"], exemplo=True, buscar_cdi=False, log=log)
        assert any("pools: weth_usdc: versões novas (dia5)" in x for x in log.linhas), log.linhas
        assert not any("cbbtc_usdc: versões novas" in x for x in log.linhas)
        conferir(ler(a))
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


def teste_migracao():
    """O estado de antes (um pool só, no alto do estado da forma) continua: o WETH/USDC não recomeça e os pools novos
    começam o passado deles."""
    a = tempfile.mkdtemp(prefix="pools-m-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora
        rodar(cli, a, t0)
        est = json.load(open(os.path.join(a, "estado.json")))
        f = est["formas"]["pools"]
        w = f.pop("pools")["weth_usdc"]
        f.update(w)  # o formato antigo: vivo, hist, pedaco, volume, pool, gecko no alto
        f.pop("vez", None)
        f.pop("decimais", None)
        papel.gravar_json(os.path.join(a, "estado.json"), est)
        ini_hist = w["hist"]["inicio"]
        ret = {k: c["curva"]["ultimo"] for k, c in w["vivo"]["contas"].items()}
        log = papel.Log(quieto=True)
        cli.agora = t0 + 6 * HORA
        papel.rodada(cli, a, cli.agora, formas=["pools"], exemplo=True, buscar_cdi=False, log=log)
        assert not any("pools: weth_usdc: versões novas" in x or "pools: weth_usdc: começando" in x for x in log.linhas), log.linhas
        assert any("cbbtc_usdc: escolhido" in x for x in log.linhas)
        est = json.load(open(os.path.join(a, "estado.json")))
        f = est["formas"]["pools"]
        assert "vivo" not in f and f["pools"]["weth_usdc"]["hist"]["inicio"] == ini_hist
        d = ler(a)
        conferir(d)
        for v in d["versoes"]:
            if v["pool"] == "weth_usdc":
                assert v["aoVivo"]["inicio"] == t0 and ret[v["id"]] > 0
    finally:
        shutil.rmtree(a, ignore_errors=True)


def teste_passado_aos_poucos():
    """Sem tempo para os 28 dias de uma vez: o ao vivo anda e os passados continuam nas rodadas seguintes, revezando
    qual pool começa."""
    a = tempfile.mkdtemp(prefix="pools-c-")
    try:
        cli = falso.ClientePapelFalso()
        cli.max_eventos = 2000
        relogio = {"n": 0}
        orig = PL.ler_trocas

        def devagar(rpc, de, ate, ref, ped, tempo, log, par=None):
            # cada pedaço "gasta" tempo: só 30 pedaços por rodada (o ao vivo dos pools vem primeiro)
            def t():
                relogio["n"] += 1
                return relogio["n"] <= 30 and tempo()
            yield from orig(rpc, de, ate, ref, ped, t, log, par)
        PL.ler_trocas = devagar
        try:
            t0 = cli.agora
            rodar(cli, a, t0)
            d = ler(a)
            assert d["config"]["passado"]["alcancou"] is False and d["config"]["passado"]["faltamDias"] > 20
            assert all(v["aoVivo"] for v in d["versoes"])
            for k in range(1, 600):
                relogio["n"] = 0
                rodar(cli, a, t0 + k * 6 * HORA)
                if all(p.get("passado", {"alcancou": True})["alcancou"] for p in ler(a)["pools"]):
                    break
            d = ler(a)
            assert all(p.get("passado", {"alcancou": True})["alcancou"] for p in d["pools"]), [p.get("passado") for p in d["pools"]]
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
            if m == "eth_call" and p[0]["to"] == PL.POOL and p[0]["data"].startswith(PL.SEL_FEE):
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
    teste_seletores()
    teste_matematica()
    teste_evento()
    teste_conta_taxas()
    teste_reposicionar()
    teste_resumo_do_dia()
    teste_a_mao()
    teste_par_invertido()
    teste_volatilidade()
    teste_gauge()
    teste_ler_trocas()
    teste_rodadas()
    teste_migracao()
    teste_passado_aos_poucos()
    teste_pool_errado()
    print("ok")
