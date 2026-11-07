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


if __name__ == "__main__":
    teste_config_reserva()
    teste_wst_em_ether()
    teste_wst_liquida_pelo_juro()
    teste_eth_liquidacao()
    teste_defesa()
    teste_usdc_e_custos()
    teste_taxas_por_dia()
    teste_rodadas()
    print("ok")
