"""Testes do looping no papel (sem rede). Uso: python3 tools/papel/teste_looping.py"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)  # antes do mercado: os dois têm um falso.py

import falso  # noqa: E402
import looping as LP  # noqa: E402
import papel  # noqa: E402
from teste_papel import conferir_forma  # noqa: E402

HORA, DIA = falso.HORA, falso.DIA
T0 = 1_700_000_000_000 // DIA * DIA


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def cfg(vid):
    return next(c for c in LP.VERSOES if c[0] == vid)


def params():
    p = {k: dict(v) for k, v in LP.PARAMS_PADRAO.items()}
    p["emode"] = dict(LP.EMODE_PADRAO)
    return p


def sem_custos():
    g = (LP.TAXA_TROCA, LP.DESLIZE, LP.TAXA_RELAMPAGO, LP.GAS_US)
    LP.TAXA_TROCA = LP.DESLIZE = LP.TAXA_RELAMPAGO = LP.GAS_US = 0.0
    return g


def com_custos(g):
    LP.TAXA_TROCA, LP.DESLIZE, LP.TAXA_RELAMPAGO, LP.GAS_US = g


def taxas_fixas(**kw):
    """Taxas constantes ao ano (as chaves de Taxas: "sup:WETH", "bor:WETH", "sup:wstETH", "sup:USDC", "bor:USDC", "stake")."""
    base = {"sup:WETH": 0.0, "bor:WETH": 0.0, "sup:wstETH": 0.0, "sup:USDC": 0.0, "bor:USDC": 0.0, "stake": 0.0}
    base.update({k.replace("_", ":"): v for k, v in kw.items()})
    return LP.Taxas({}, base)


# ------------------------------------------------------------------------------------------- contas à mão
def teste_config_reserva():
    cfg_ = 8100 | (8400 << 16) | (10500 << 32) | (18 << 48)
    c = LP.config_reserva("0x" + f"{cfg_:064x}" + "0" * 64)
    assert perto(c["ltv"], 0.81) and perto(c["lt"], 0.84) and perto(c["bonus"], 0.05)
    assert LP.config_reserva("0x00") is None and LP.config_reserva(None) is None
    assert LP.config_reserva("0x" + "0" * 64) is None
    assert perto(LP._apy("0.0148"), 0.0148) and perto(LP._apy("5.4"), 0.054) and LP._apy("x") is None


def teste_wst_em_ether():
    g = sem_custos()
    try:
        c = LP.Conta(cfg("wst3"), T0, params())
        c.passo(T0, 0, 2000.0, 2000.0, taxas_fixas())
        # 3× com US$ 1.000 a US$ 2.000: 1,5 wstETH de garantia, 1 ETH de dívida; fator = 1,5 × 0,93 ÷ 1
        assert perto(c.a, 1.5) and perto(c.b, 1.0) and perto(c.saude(2000), 1.395) and c.pref == 2000
        assert perto(c.curva.ultimo, 1000)
        # o ether cai 40%: a conta (medida em ether) não muda e não liquida; em dólar, cairia
        tx = taxas_fixas()
        c.passo(T0 + DIA, DIA, 1200.0, 1100.0, tx)
        assert perto(c.curva.ultimo, 1000) and c.curva.n_liq == 0
        assert perto(c.curva.extra["emDolar"], 600) and c.curva.extra["precoRef"] == 2000
        # um ano de staking 3% contra juro de 2%: 3 × 1,03 − 2 × 1,02 = 1,05 do dinheiro
        tx = taxas_fixas(stake=0.03, bor_WETH=0.02)
        c2 = LP.Conta(cfg("wst3"), T0, params())
        c2.passo(T0, 0, 2000.0, 2000.0, tx)
        for k in range(1, 366):
            c2.passo(T0 + k * DIA, DIA, 2000.0, 2000.0, tx)
        assert perto(c2.curva.ultimo, 1050, 1e-6), c2.curva.ultimo
        assert perto(c2.curva.extra["ganhoJuros"], 90, 1e-6) and perto(c2.curva.extra["custoJuros"], 40, 1e-6)
        # o que rende agora ao ano: (garantia × staking − dívida × juro) ÷ patrimônio
        assert perto(c2.curva.extra["rendeAno"], (3090 * 0.03 - 2040 * 0.02) / 1050, 1e-3)
    finally:
        com_custos(g)


def teste_wst_liquida_pelo_juro():
    g = sem_custos()
    try:
        # 6× com o juro do ether muito acima do staking: o fator de saúde cai até 1 e o Aave liquida (metade da dívida)
        tx = taxas_fixas(bor_WETH=0.60)
        c = LP.Conta(cfg("wst6"), T0, params())
        c.passo(T0, 0, 2000.0, 2000.0, tx)
        assert perto(c.saude(2000), 3 * 0.93 / 2.5)  # 3 wstETH de garantia, 2,5 ETH de dívida
        dias = 0
        while c.curva.n_liq == 0 and dias < 400:
            dias += 1
            c.passo(T0 + dias * DIA, DIA, 2000.0, 2000.0, tx)
        assert c.curva.n_liq == 1 and 60 < dias < 120, dias
        assert c.saude(2000) > 1  # depois da liquidação, a dívida caiu pela metade
        assert c.curva.liq[0]["moeda"] == "wstETH" and c.curva.liq[0]["perda"] > 0
    finally:
        com_custos(g)


def teste_eth_liquidacao():
    g = sem_custos()
    try:
        c = LP.Conta(cfg("eth2"), T0, params())
        c.passo(T0, 0, 2000.0, 2000.0, taxas_fixas())
        # 2×: 1 ETH de garantia, US$ 1.000 de dívida; liquida quando 1 × P × 0,84 < 1.000 → P < 1.190,48
        assert perto(c.a, 1.0) and perto(c.b, 1000) and perto(c.preco_liquidacao(), 1000 / 0.84)
        c.passo(T0 + HORA, HORA, 1300.0, 1200.0, taxas_fixas())
        assert c.curva.n_liq == 0
        c.passo(T0 + 2 * HORA, 2 * HORA, 1250.0, 1150.0, taxas_fixas())
        assert c.curva.n_liq == 1
        pl = 1000 / 0.84
        # metade da dívida (500) paga com a garantia + 5% de bônus, no preço em que o fator chegou a 1
        assert perto(c.b, 500) and perto(c.a, 1 - 525 / pl)
        assert perto(c.curva.liq[0]["perda"], 25)
        assert c.curva.queda > 0.8  # a mínima foi marcada (US$ 1.000 → ~US$ 150)
    finally:
        com_custos(g)


def teste_defesa():
    g = sem_custos()
    try:
        c = LP.Conta(cfg("eth2def"), T0, params())
        c.passo(T0, 0, 2000.0, 2000.0, taxas_fixas())
        hf = c.saude(2000)
        assert perto(hf, 1.68)
        # cai a 1.500: fator 1,26 < 1,3 → vende ether e paga a dívida, voltando a 2× (garantia = 2 × patrimônio)
        c.passo(T0 + HORA, HORA, 1500.0, 1500.0, taxas_fixas())
        E = c.valor(1500)
        assert perto(E, 500) and perto(c.garantia_us(1500), 2 * E) and c.curva.extra["defesas"] == 1
        assert c.curva.n_liq == 0 and c.saude(1500) > 1.3
        # sem defesa, a mesma queda deixa o fator em 1,26
        d = LP.Conta(cfg("eth2"), T0, params())
        d.passo(T0, 0, 2000.0, 2000.0, taxas_fixas())
        d.passo(T0 + HORA, HORA, 1500.0, 1500.0, taxas_fixas())
        assert perto(d.saude(1500), 1.26)
    finally:
        com_custos(g)


def teste_usdc_e_custos():
    c = LP.Conta(cfg("usdc"), T0, params())
    tx = taxas_fixas(sup_USDC=0.05)
    c.passo(T0, 0, 2000.0, 2000.0, tx)
    assert perto(c.curva.ultimo, 1000 - LP.GAS_US)
    for k in range(1, 366):
        c.passo(T0 + k * DIA, DIA, 3000.0, 3000.0, tx)
    assert perto(c.curva.ultimo, (1000 - LP.GAS_US) * 1.05, 1e-6)
    # montar o laço custa a troca + deslize sobre tudo, o empréstimo relâmpago sobre a dívida e o gás
    w = LP.Conta(cfg("wst3"), T0, params())
    w.passo(T0, 0, 2000.0, 2000.0, taxas_fixas())
    custo = 3000 * (LP.TAXA_TROCA + LP.DESLIZE) + LP.TAXA_RELAMPAGO * 2000 + LP.GAS_US
    assert perto(w.curva.taxas, custo) and perto(w.curva.ultimo, 1000 - custo)


def teste_taxas_por_dia():
    tx = LP.Taxas({"bor:WETH": {"2026-01-01": 0.02, "2026-01-03": 0.04}}, {"bor:WETH": 0.05})
    d = lambda s: int(__import__("datetime").datetime.fromisoformat(s + "T12:00:00+00:00").timestamp() * 1000)  # noqa: E731
    assert tx.taxa("bor:WETH", d("2026-01-01")) == 0.02
    assert tx.taxa("bor:WETH", d("2026-01-02")) == 0.02  # sem o dia: o anterior
    assert tx.taxa("bor:WETH", d("2026-01-05")) == 0.05  # depois do último: a de agora
    assert tx.taxa("bor:WETH", d("2025-12-01")) == 0.02
    assert tx.taxa("stake", d("2026-01-01")) == LP.STAKING_PADRAO


# ------------------------------------------------------------------------------------------- revisão de 09/11/2026
def teste_auto_monta_e_desmonta():
    g = sem_custos()
    try:
        # staking 3% e juro 2%: (3 − 1) × 1 ponto = 2 pontos a mais no laço ≥ 0,5 → monta já no começo
        tx = taxas_fixas(stake=0.03, bor_WETH=0.02)
        ev = LP.Eventos()
        c = LP.Conta(cfg("wstAuto3"), T0, params())
        c.passo(T0, 0, 2000.0, 2000.0, tx, ev)
        assert c.L == 3 and perto(c.saude(2000), 1.395) and c.acc["montagens"] == 1
        assert ev.lista[-1]["motivo"] == "compensa"
        # o juro do ether dispara (3% + 2 pontos): no dia seguinte, desmonta para 1× com o motivo "juro"
        tx2 = taxas_fixas(stake=0.03, bor_WETH=0.06)
        c.passo(T0 + DIA, DIA, 2000.0, 2000.0, tx2, ev)
        assert c.L == 1 and c.b < 1e-12 and c.acc["desmontagens"] == 1
        assert ev.lista[-1]["motivo"] == "juro" and ev.lista[-1]["tipo"] == "reequilibrou"
        # só uma decisão por dia
        n = len(ev.lista)
        c.passo(T0 + DIA + HORA, HORA, 2000.0, 2000.0, tx, ev)
        assert len(ev.lista) == n and c.L == 1
        # diferença pequena: 2 × 0,2 ponto = 0,4 < 0,5 → não monta; a régua do 1× segue
        c2 = LP.Conta(cfg("wstAuto3"), T0, params())
        c2.passo(T0, 0, 2000.0, 2000.0, taxas_fixas(stake=0.03, bor_WETH=0.028))
        assert c2.L == 1 and c2.b == 0
        # regra de 09/11/2026: o que conta é a diferença por × a mais (0,2 ponto < 0,5): o 6× também não monta
        c3 = LP.Conta(cfg("wstAuto6"), T0, params())
        c3.passo(T0, 0, 2000.0, 2000.0, taxas_fixas(stake=0.03, bor_WETH=0.028))
        assert c3.L == 1
        c3.passo(T0 + DIA, DIA, 2000.0, 2000.0, taxas_fixas(stake=0.03, bor_WETH=0.02))
        assert c3.L == 6
        # a diferença fica negativa sem disparar: fica montado os 30 dias mínimos e só depois desmonta ("diferenca")
        ev3 = LP.Eventos()
        for k in range(2, 10):
            c3.passo(T0 + k * DIA, DIA, 2000.0, 2000.0, taxas_fixas(stake=0.03, bor_WETH=0.0305), ev3)
        assert c3.L == 6
        for k in range(10, 40):
            c3.passo(T0 + k * DIA, DIA, 2000.0, 2000.0, taxas_fixas(stake=0.03, bor_WETH=0.0305), ev3)
        assert c3.L == 1 and ev3.lista[-1]["motivo"] == "diferenca"
    finally:
        com_custos(g)
    # com custos: montar e desmontar cobram troca, deslize, relâmpago e gás sobre o que muda
    c = LP.Conta(cfg("wstAuto3"), T0, params())
    c.passo(T0, 0, 2000.0, 2000.0, taxas_fixas(stake=0.03, bor_WETH=0.0299))  # 0,02 ponto: fica no 1×
    E0 = c.valor(2000)
    # 1 ponto já não paga a ida e a volta em 60 dias com custos; 3 pontos pagam
    c.passo(T0 + DIA, 0, 2000.0, 2000.0, taxas_fixas(stake=0.03, bor_WETH=0.02))
    assert c.L == 1
    c.passo(T0 + 2 * DIA, 0, 2000.0, 2000.0, taxas_fixas(stake=0.05, bor_WETH=0.02))
    assert c.L == 3
    custo = 2 * E0 * (LP.TAXA_TROCA + LP.DESLIZE) + 2 * E0 * LP.TAXA_RELAMPAGO + LP.GAS_US
    assert perto(c.valor(2000), E0 - custo, 1e-4), (c.valor(2000), E0 - custo)
    pd = c.curva.extra["porDentro"]
    assert perto(pd["relampago"], 2 * E0 * LP.TAXA_RELAMPAGO, 1e-4) and pd["montagens"] == 1


def teste_tendencia():
    g = sem_custos()
    try:
        tx = taxas_fixas(sup_USDC=0.05)
        ev = LP.Eventos()
        # abaixo da média: fica em USDC no Aave
        c = LP.Conta(cfg("eth2tend"), T0, params())
        c.passo(T0, 0, 2000.0, 2000.0, tx, ev, tend=(1900.0, 2000.0))
        assert c.L == 0 and perto(c.u, 1000) and c.a == 0 and c.b == 0 and c.saude(2000) is None
        assert ev.lista[-1]["motivo"] == "queda"
        c.passo(T0 + DIA, DIA, 1500.0, 1400.0, tx, ev, tend=(1500.0, 1900.0))
        assert perto(c.valor(1500), 1000 * 1.05 ** (1 / 365), 1e-6)  # o ether caiu e a conta só rendeu o juro
        # o ether passa a média: monta o 2× (2 vezes o patrimônio em ether)
        c.passo(T0 + 2 * DIA, DIA, 2100.0, 2050.0, tx, ev, tend=(2100.0, 1950.0))
        E = c.valor(2100)
        assert c.L == 2 and perto(c.garantia_us(2100), 2 * E) and perto(c.b, E) and c.u == 0
        assert ev.lista[-1]["motivo"] == "alta"
        # sem média (poucos dias): não muda
        c.passo(T0 + 3 * DIA, DIA, 2100.0, 2100.0, tx, ev, tend=(None, None))
        assert c.L == 2
        # cai abaixo: vende tudo, paga a dívida
        c.passo(T0 + 4 * DIA, DIA, 1800.0, 1800.0, tx, ev, tend=(1800.0, 1950.0))
        assert c.L == 0 and c.b == 0 and c.a == 0 and perto(c.u, c.valor(1800))
        assert c.curva.extra["laco"] == "fora" and c.curva.extra["emUsdc"] > 0
    finally:
        com_custos(g)
    # a média móvel pelas velas de 1 dia (só os dias fechados até t)
    d = [(T0 + k * DIA, 100.0 + k, 99.0) for k in range(1, 61)]
    f, m = LP.media_movel(d, T0 + 60 * DIA)
    assert f == 160.0 and perto(m, sum(100.0 + k for k in range(11, 61)) / 50)
    f, m = LP.media_movel(d, T0 + 10 * DIA)
    assert f == 110.0 and m is None  # menos de 20 dias
    f, m = LP.media_movel(d, T0 + 25 * DIA)
    assert perto(m, sum(100.0 + k for k in range(1, 26)) / 25)


def teste_estresse():
    g = sem_custos()
    try:
        tx = taxas_fixas(stake=0.03, bor_WETH=0.02)
        c = LP.Conta(cfg("wst6"), T0, params())
        c.passo(T0, 0, 2000.0, 2000.0, tx)
        es = LP.estresse(cfg("wst6"), c, tx, T0, params(), 2000.0)
        assert es["tipo"] == "wst" and es["base"] == "agora"
        # rende 6 × 3% − 5 × 2% = 8%; o laço perde com juro acima de 6 × 3% ÷ 5 = 3,6%
        assert perto(es["rendeAno"], 0.08) and perto(es["juroPerde"], 0.036) and perto(es["juroRegua"], 0.03)
        j2, j5 = es["juroAlto"]
        assert perto(j2["juro"], 0.04) and perto(j2["rendeAno"], 0.18 - 0.20)
        assert perto(j2["diasApagam"], round(365 * 0.08 / 0.02, 1))  # 1.460 dias de juro dobrado apagam um ano
        assert perto(j5["rendeAno"], 0.18 - 0.50) and perto(j5["diasApagam"], round(365 * 0.08 / 0.32, 1))
        hf = 6 * 0.93 / 5
        d6 = es["desvio"][-1]
        assert d6["desvio"] == 0.06 and perto(d6["hfAave"], hf, 1e-3) and perto(d6["hfSeMercado"], hf * 0.94, 1e-3)
        assert perto(d6["perdaSaindo"], 0.36) and d6["liquidariaSeMercado"] is False
        assert perto(es["desvioLiquida"], 1 - 1 / hf, 1e-3)
        # o laço quando compensa no 1×: a conta teórica do 6×
        a = LP.Conta(cfg("wstAuto6"), T0, params())
        a.passo(T0, 0, 2000.0, 2000.0, taxas_fixas(stake=0.03, bor_WETH=0.031))
        assert a.L == 1 and LP.estresse(cfg("wstAuto6"), a, tx, T0, params(), 2000.0)["base"] == "teorica"
        # ETH × USDC: queda até liquidar e o fator nas quedas
        txe = taxas_fixas(sup_WETH=0.02, bor_USDC=0.06)
        e = LP.Conta(cfg("eth2"), T0, params())
        e.passo(T0, 0, 2000.0, 2000.0, txe)
        ee = LP.estresse(cfg("eth2"), e, txe, T0, params(), 2000.0)
        assert ee["tipo"] == "eth" and perto(ee["quedaLiquida"], 1 - (1000 / 0.84) / 2000, 1e-4)
        assert perto(ee["rendeAno"], 2 * 0.02 - 0.06) and ee["juroAlto"][0]["diasApagam"] is None  # já rende negativo
        assert perto(ee["quedas"][1]["hf"], 1.68 * 0.6, 1e-3) and ee["quedas"][1]["liquida"] is False
        assert LP.estresse(cfg("wst1"), None, tx, T0, params(), 2000.0) is None
    finally:
        com_custos(g)


def teste_por_dentro_e_empate():
    tx = taxas_fixas(stake=0.03, bor_WETH=0.02, sup_wstETH=0.001)
    c = LP.Conta(cfg("wst3"), T0, params())
    c.passo(T0, 0, 2000.0, 2000.0, tx)
    for k in range(1, 91):
        c.passo(T0 + k * DIA, DIA, 2000.0 + k, 1990.0, tx)
    pd = c.curva.extra["porDentro"]
    soma = pd["staking"] + pd["juroRecebido"] - pd["juroPago"] - pd["custos"] - pd["liquidacoes"] + pd["preco"]
    assert perto(soma, pd["resultado"], 1e-4) and abs(pd["preco"]) < 1e-3  # medido em ether: o preço não entra
    assert perto(pd["custos"], 3000 * (LP.TAXA_TROCA + LP.DESLIZE) + 2000 * LP.TAXA_RELAMPAGO + LP.GAS_US)
    assert "estimado" not in pd
    em = c.curva.extra["empate"]
    custo_regua = 1000 * (LP.TAXA_TROCA + LP.DESLIZE) + LP.GAS_US
    assert perto(em["custo"], pd["custos"] - custo_regua, 1e-6) and em["pelo"] == "juro"
    E = c.valor(2000)
    rende = c.curva.extra["rendeAno"]
    assert perto(em["ganhoAno"], (rende - 0.031) * E, 1e-3) and perto(em["meses"], em["custo"] / (em["ganhoAno"] / 12), 1e-2)
    # em dólar de verdade: o ether subiu 4,5%; a conta em dólar subiu junto
    dol = c.curva.extra["dolar"]
    assert perto(dol["ether"], 2090 / 2000 - 1, 1e-6) and perto(dol["retorno"], c.curva.extra["emDolar"] / 1000 - 1, 1e-4)
    # ETH × USDC: o preço aparece no "preco"
    e = LP.Conta(cfg("eth2"), T0, params())
    txe = taxas_fixas(sup_WETH=0.02, bor_USDC=0.06)
    e.passo(T0, 0, 2000.0, 2000.0, txe)
    e.passo(T0 + DIA, DIA, 2200.0, 2100.0, txe)
    pe = e.curva.extra["porDentro"]
    assert pe["preco"] > 190 and perto(pe["staking"] + pe["juroRecebido"] - pe["juroPago"] - pe["custos"] - pe["liquidacoes"] + pe["preco"], pe["resultado"], 1e-4)
    assert e.curva.extra["empate"]["pelo"] == "preco" and e.curva.extra["empate"]["meses"] is None
    # a régua não tem empate
    w = LP.Conta(cfg("wst1"), T0, params())
    w.passo(T0, 0, 2000.0, 2000.0, tx)
    assert "empate" not in w.curva.extra


def teste_janelas():
    import datetime as dt
    d0 = dt.date(2026, 1, 1)
    # a conta sobe 1% a cada 30 dias; a régua 0,5%
    serie = [[(d0 + dt.timedelta(days=k)).isoformat(), 1000 * 1.01 ** (k / 30)] for k in range(91)]
    regua = {(d0 + dt.timedelta(days=k)).isoformat(): 1000 * 1.005 ** (k / 30) for k in range(91)}
    j = LP.janelas({"serie": serie}, "wst1", regua=regua)
    assert j["n"] == 9 and j["vence"] == 9 and j["contra"]["id"] == "wst1" and perto(j["mediana"], 0.01, 1e-6)
    assert perto(j["lista"][0][2], 0.005, 1e-6) and "venceCdi" not in j
    # contra o ether parado (0%)
    j = LP.janelas({"serie": serie}, "ether")
    assert j["vence"] == 9 and j["lista"][0][2] == 0.0
    # contra o CDI: 2% num mês ganha da conta
    cdi = {(d0 + dt.timedelta(days=k)).isoformat(): 0.001 for k in range(91)}
    j = LP.janelas({"serie": serie}, "cdi", cdi=cdi, cdi_ano=0.15)
    assert j["vence"] == 0 and j["venceCdi"] == 0 and j["pior"]["cdi"] > 0.02
    assert LP.janelas({"serie": serie[:20]}, "cdi", cdi=cdi) is None
    assert LP.janelas({"serie": serie}, "wst1", regua={}) is None
    assert LP.contra_de(cfg("wst6")) == "wst1" and LP.contra_de(cfg("wst1")) == "ether" and LP.contra_de(cfg("eth2")) == "cdi"
    assert LP.contra_de(cfg("morpho")) == "cdi"


# ------------------------------------------------------------------------------------------- rodadas
def rodar(cli, pasta, quando):
    cli.agora = quando
    return papel.rodada(cli, pasta, quando, formas=["looping"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))


def ler(pasta):
    with open(os.path.join(pasta, "looping.json")) as f:
        return json.load(f)


def conferir(d):
    conferir_forma(d, "looping")
    assert d["padrao"] == "wst3" and d["nome"] == "Looping"
    assert {v["id"] for v in d["versoes"]} == {v[0] for v in LP.VERSOES}
    for v in d["versoes"]:
        assert v["alav"] <= LP.ALAV_MAX
        for k in ("aoVivo", "historico"):
            c = v[k]
            assert c is not None, (v["id"], k)
            assert {"hf", "alavAgora", "rendeAno", "ganhoJuros", "custoJuros", "defesas"} <= set(c["extra"]), (v["id"], k)
        assert v["historico"]["aproximado"] is True and v["historico"]["nota"]
    assert d["config"]["fontesParametros"]["reservas"] == "getReserveData"
    assert len(d["itens"]) == 3 and all(i["lt"] for i in d["itens"])
    assert "abriu" in {e["tipo"] for e in d["eventos"]}
    # revisão de 09/11/2026
    ids = {v["id"]: v for v in d["versoes"]}
    assert ids["wstAuto3"]["grupo"] == "Laço quando compensa" and ids["morpho"]["grupo"] == "Referência"
    assert ids["wst3"]["medida"] == "ether" and ids["eth2"]["medida"] == "dolar" and ids["wst3"]["contra"] == "wst1"
    for v in d["versoes"]:
        for k in ("aoVivo", "historico"):
            pd = v[k]["extra"]["porDentro"]
            assert {"staking", "juroRecebido", "juroPago", "troca", "deslize", "relampago", "gas", "liquidacoes", "preco", "resultado"} <= set(pd)
            assert v[k]["metricas"] is not None
            assert ("empate" in v[k]["extra"]) == (v["alav"] > 1), (v["id"], k)
        assert ("estresse" in v) == (v["alav"] > 1), v["id"]
        if v["medida"] == "ether":
            assert set(v["aoVivo"]["extra"]["dolar"]) == {"retorno", "piorQueda", "ether"}
    assert {x["id"] for x in d["dolar"]} == {"usdc", "morpho", "moonwell"} and all(x["agora"] for x in d["dolar"])
    assert d["config"]["auto"]["entra"] == LP.AUTO_ENTRA and d["config"]["tendencia"]["dias"] == 50


def teste_rodadas():
    a = tempfile.mkdtemp(prefix="looping-a-")
    b = tempfile.mkdtemp(prefix="looping-b-")
    try:
        cli_a, cli_b = falso.ClientePapelFalso(), falso.ClientePapelFalso()
        t0 = cli_a.agora
        pulos = {t0 + k * 6 * HORA for k in range(5, 9)}
        for k in range(16):
            q = t0 + k * 6 * HORA
            ind = rodar(cli_a, a, q)
            assert ind["formas"]["looping"]["ok"], ind["formas"]["looping"]
            if q not in pulos:
                rodar(cli_b, b, q)
            conferir(ler(a))
        da, db = ler(a), ler(b)
        # as janelas aparecem com 30 dias de teste no passado (o mundo de mentira tem ~40)
        js = {v["id"]: v["historico"].get("janelas") for v in da["versoes"]}
        assert js["wst3"] and js["wst3"]["contra"]["id"] == "wst1" and js["wst1"]["contra"]["id"] == "ether"
        assert js["eth2"]["contra"]["id"] == "cdi" and "venceCdi" in js["eth2"]
        for va, vb in zip(da["versoes"], db["versoes"]):
            assert va["aoVivo"]["serie"] == vb["aoVivo"]["serie"], va["id"]  # alcançar dá o mesmo resultado
        assert not da["rodada"]["erros"], da["rodada"]["erros"]
        # o e-mode veio do GraphQL e o getReserveData deu os limites (o da reserva do WETH: 84%)
        with open(os.path.join(a, "estado.json")) as f:
            est = json.load(f)["formas"]["looping"]
        assert est["params"]["fontes"] == {"reservas": "getReserveData", "emode": "GraphQL"}
        assert perto(est["params"]["WETH"]["lt"], 0.84) and perto(est["params"]["emode"]["lt"], 0.93)
        assert set(est["taxas"]["serie"]) == {"sup:WETH", "bor:WETH", "sup:wstETH", "sup:USDC", "bor:USDC", "stake"}
        # o wstETH é medido em ether: o ether do mundo de mentira andou muito, a conta pouco
        w = next(v for v in da["versoes"] if v["id"] == "wst3")["aoVivo"]
        assert abs(w["retorno"]) < 0.02 and w["extra"]["emDolar"] > 0
        # falha do GraphQL: ok false e o arquivo da rodada boa fica
        antes = ler(a)
        cli_a.falhar.add("aave")
        ind = rodar(cli_a, a, t0 + 16 * 6 * HORA)
        assert ind["formas"]["looping"]["ok"] is False and ler(a) == antes
        cli_a.falhar.clear()
        # falha só no staking (DefiLlama): segue com o da rodada anterior e anota o erro
        cli_a.falhar.add("llama")
        ind = rodar(cli_a, a, t0 + 20 * 6 * HORA)
        assert ind["formas"]["looping"]["ok"]
        assert any("DefiLlama" in x for x in ler(a)["rodada"]["erros"])
        assert ler(a)["config"]["stakingFonte"] == "DefiLlama (Lido)"
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


def teste_estado_antigo():
    """O estado de antes de 09/11/2026 (sem as chaves novas na conta e o teste no passado da versão 1) continua: a
    conta segue de onde estava, com a conta por dentro marcada como estimada, e o passado é refeito."""
    a = tempfile.mkdtemp(prefix="looping-v-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora
        rodar(cli, a, t0)
        caminho = os.path.join(a, "estado.json")
        with open(caminho) as f:
            est = json.load(f)
        lp = est["formas"]["looping"]
        for vid in list(lp["vivo"]):
            x = lp["vivo"][vid]
            if vid in {c[0] for c in LP.VERSOES if c[0] not in LP.OPCOES}:
                x["acc"] = {k: x["acc"][k] for k in ("ganho", "custo", "defesas")}
                for k in ("u", "L", "dec", "estimado", "dol"):
                    x.pop(k, None)
            else:
                del lp["vivo"][vid]  # as versões novas não existiam
        lp["hist"]["v"] = 1
        antes = lp["vivo"]["wst3"]["curva"]["ultimo"]
        with open(caminho, "w") as f:
            json.dump(est, f)
        ind = rodar(cli, a, t0 + 6 * HORA)
        assert ind["formas"]["looping"]["ok"]
        d = ler(a)
        conferir(d)
        w = next(v for v in d["versoes"] if v["id"] == "wst3")
        assert w["aoVivo"]["extra"]["porDentro"]["estimado"] is True and abs(w["aoVivo"]["retorno"] - (antes / 1000 - 1)) < 0.01
        with open(caminho) as f:
            assert json.load(f)["formas"]["looping"]["hist"]["v"] == LP.HIST_V
    finally:
        shutil.rmtree(a, ignore_errors=True)


def teste_dolar_sem_dados():
    """A Morpho fora do ar cai para a DefiLlama; a Moonwell sem pool na DefiLlama vira `semDados` (sem derrubar nada)."""
    a = tempfile.mkdtemp(prefix="looping-d-")
    try:
        cli = falso.ClientePapelFalso()
        cli.falhar.add("morpho")
        cli.sem_moonwell = True
        ind = rodar(cli, a, cli.agora)
        assert ind["formas"]["looping"]["ok"]
        d = ler(a)
        v = {x["id"]: x for x in d["versoes"]}
        assert v["morpho"]["aoVivo"] is not None and v["morpho"].get("semDados") is None
        assert next(x for x in d["dolar"] if x["id"] == "morpho")["fonte"] == "DefiLlama (Morpho)"
        mw = v["moonwell"]
        assert mw["aoVivo"] is None and mw["historico"] is None and "Moonwell" in mw["semDados"], mw.get("semDados")
        assert next(x for x in d["dolar"] if x["id"] == "moonwell")["semDados"]
        assert any("Morpho (blue-api)" in e for e in d["rodada"]["erros"])
        conferir_forma(d, "looping")
    finally:
        shutil.rmtree(a, ignore_errors=True)


if __name__ == "__main__":
    teste_config_reserva()
    teste_wst_em_ether()
    teste_wst_liquida_pelo_juro()
    teste_eth_liquidacao()
    teste_defesa()
    teste_usdc_e_custos()
    teste_taxas_por_dia()
    teste_auto_monta_e_desmonta()
    teste_tendencia()
    teste_estresse()
    teste_por_dentro_e_empate()
    teste_janelas()
    teste_rodadas()
    teste_estado_antigo()
    teste_dolar_sem_dados()
    print("ok")
