"""Testes da venda de opções no papel (sem rede). Uso: python3 tools/papel/teste_opcoes.py"""
from __future__ import annotations

import datetime as dt
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
import opcoes as O  # noqa: E402
import papel  # noqa: E402
from teste_papel import conferir_forma  # noqa: E402

HORA, DIA = falso.HORA, falso.DIA


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def ms(s):
    return int(dt.datetime.fromisoformat(s).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


def cfg(vid):
    return next(c for c in O.VERSOES if c[0] == vid)


def mercado(precos_por_hora, ini, fim, vol=0.5, moedas=("BTC",)):
    """Um MercadoHist de mentira: `precos_por_hora(t)` dá o preço; o DVOL é fixo."""
    p, d = {}, {}
    for m in moedas:
        p[m], d[m] = {}, {}
        t = (ini // HORA) * HORA
        while t <= fim:
            p[m][t] = precos_por_hora(t)
            d[m][t] = vol
            t += HORA
    return O.MercadoHist(p, d)


def andar(c, mk, ini, fim):
    for t in O.horas(ini, fim):
        c.passo(mk, t)


# ------------------------------------------------------------------------------------------- utilidades
def teste_instrumentos_e_datas():
    m, venc, k, tipo = O.ler_instrumento("BTC-13NOV26-83000-P")
    assert (m, k, tipo) == ("BTC", 83000.0, "put") and venc == ms("2026-11-13T08:00:00")
    assert O.nome_instrumento("BTC", venc, 83000, "put") == "BTC-13NOV26-83000-P"
    assert O.ler_instrumento("ETH-6DEC26-3100-C")[3] == "call"
    assert O.ler_instrumento("BTC-PERPETUAL") is None and O.ler_instrumento("BTC-31FOO26-1-P") is None
    # sexta 08h UTC: 13/11/2026 é sexta
    assert O.sexta_08(ms("2026-11-18T10:00:00")) == ms("2026-11-13T08:00:00")
    assert O.sexta_08(ms("2026-11-13T08:00:00")) == ms("2026-11-13T08:00:00")
    assert O.sexta_08(ms("2026-11-13T07:59:00")) == ms("2026-11-06T08:00:00")
    assert O.eh_sexta(ms("2026-11-13T08:00:00")) and not O.eh_sexta(ms("2026-11-14T08:00:00"))
    assert O.ultima_sexta_do_mes(ms("2026-11-27T08:00:00")) and not O.ultima_sexta_do_mes(ms("2026-11-20T08:00:00"))


def teste_formula():
    S, K, T, iv = 100_000.0, 90_000.0, 7 / 365, 0.5
    put, call = O.bs(S, K, T, iv, "put"), O.bs(S, K, T, iv, "call")
    assert perto(call - put, S - K, 1e-9)  # paridade sem juros
    d = O.delta(S, K, T, iv, "put")
    assert -0.5 < d < 0 and 0 < O.delta(S, 110_000, T, iv, "call") < 0.5
    assert O.bs(S, K, 0, iv, "put") == 0 and O.bs(80_000, K, 0, iv, "put") == 10_000
    # o sorriso padrão: a put longe do preço bem mais cara, a call longe um pouco mais cara, a do dinheiro igual
    ivp, ivc = O.iv_do_sorriso(0.5, S, K, T, "put"), O.iv_do_sorriso(0.5, S, 110_000, T, "call")
    assert ivp > ivc > 0.5 and ivp < 0.5 * 1.2 and ivc < 0.5 * 1.05
    assert perto(O.iv_do_sorriso(0.5, S, S * 1.003, T, "put"), 0.5, 2e-2)
    # com a curva medida: a razão interpolada pelo delta
    curva = {"put": {"0.10": 1.3, "0.30": 1.1}}
    d = abs(O.delta(S, K, T, 0.5, "put"))
    r = 1.3 + (1.1 - 1.3) * (d - 0.10) / 0.20 if 0.10 < d < 0.30 else (1.3 if d <= 0.10 else 1.1)
    assert perto(O.iv_do_sorriso(0.5, S, K, T, "put", curva), 0.5 * r)
    assert perto(O.iv_do_sorriso(0.5, S, 110_000, T, "call", curva), ivc)  # sem o lado: a padrão
    # a taxa: 0,03% da moeda, no máximo 12,5% do prêmio
    assert perto(O.taxa_opcao(100_000, 0.01, 1000), 0.3) and perto(O.taxa_opcao(100_000, 0.01, 100), 0.125)


# ------------------------------------------------------------------------------------------- contas
def teste_put_sem_valor():
    ini, fim = ms("2026-10-01T00:00:00"), ms("2026-10-31T00:00:00")
    mk = mercado(lambda t: 100_000.0, ini - 30 * DIA, fim)
    c = O.Conta(cfg("put15"))
    c.criado = ini
    andar(c, mk, ini, fim)
    a = c.acc
    # sextas 02, 09, 16, 23 e 30/10: 4 puts vencidas sem valor, a 5ª em aberto
    assert a["vendas"] == 5 and a["fora"] == 4 and a["dentro"] == 0 and a["pagos"] == 0, a
    assert c.curva.inicio == ms("2026-10-02T08:00:00")
    assert c.curva.ultimo > 1000 and c.curva.ops >= 5
    op = c.pos[0]
    assert 0.08 < op["delta"] < 0.25 and op["K"] < 100_000 and op["K"] % 1000 == 0
    # o valor = caixa − a marca da put aberta; a garantia em dólar continua inteira
    assert perto(c.valor(mk, fim), c.caixa - mk.marca(op, fim)[0] * op["q"])
    assert c.curva.extra["semValor"] == 4 and c.curva.extra["emAberto"].startswith("Put ")


def teste_put_paga_na_queda():
    ini = ms("2026-10-01T00:00:00")
    queda = ms("2026-10-05T00:00:00")
    mk = mercado(lambda t: 100_000.0 if t < queda else 70_000.0, ini - 30 * DIA, ms("2026-10-10T00:00:00"))
    c = O.Conta(cfg("put15"))
    c.criado = ini
    andar(c, mk, ini, ms("2026-10-09T09:00:00"))
    assert c.acc["dentro"] == 1
    # pagou (K − 70.000) × q da put vendida em 02/10 (vencida em 09/10, pelo preço das 07h–08h)
    op_q = 1000 / 90_000  # a garantia inteira ÷ um strike perto de 90 mil (delta 0,15)
    assert c.acc["pagos"] > 10_000 * op_q and c.curva.ultimo < 1000 * 0.85
    assert c.curva.ganhos[-1] < 0


def teste_recompra():
    ini = ms("2026-10-01T00:00:00")
    queda = ms("2026-10-03T00:00:00")
    mk = mercado(lambda t: 100_000.0 if t < queda else 88_000.0, ini - 30 * DIA, ms("2026-10-20T00:00:00"))
    c = O.Conta(cfg("putstop"))
    c.criado = ini
    andar(c, mk, ini, ms("2026-10-08T00:00:00"))
    assert c.acc["recompras"] == 1 and not c.pos  # recomprou e espera a sexta seguinte
    andar(c, mk, ms("2026-10-08T00:00:00"), ms("2026-10-09T12:00:00"))
    assert c.pos and c.acc["vendas"] == 2


def teste_call_coberta():
    ini = ms("2026-10-01T00:00:00")
    alta = ms("2026-10-05T00:00:00")
    mk = mercado(lambda t: 100_000.0 if t < alta else 130_000.0, ini - 30 * DIA, ms("2026-10-10T00:00:00"))
    c = O.Conta(cfg("call15"))
    c.criado = ini
    andar(c, mk, ini, ms("2026-10-02T12:00:00"))
    custo = O.TAXA_SPOT + O.DESLIZE_SPOT
    assert perto(c.q, 1000 / 100_000 / (1 + custo), 1e-3) and c.caixa < 1000 * 0.05
    andar(c, mk, ms("2026-10-02T12:00:00"), ms("2026-10-09T09:00:00"))
    # a alta passou do strike: a call pagou a diferença; o ganho ficou limitado (bem menos que 30%)
    assert c.acc["dentro"] == 1 and 1000 < c.curva.ultimo < 1250, c.curva.ultimo
    assert c.curva.extra["naMoeda"] > 0


def teste_strangle_e_mensal():
    ini, fim = ms("2026-10-01T00:00:00"), ms("2026-11-10T00:00:00")
    mk = mercado(lambda t: 100_000.0, ini - 30 * DIA, fim)
    s = O.Conta(cfg("strangle"))
    s.criado = ini
    andar(s, mk, ini, ms("2026-10-02T12:00:00"))
    assert {p["tipo"] for p in s.pos} == {"put", "call"} and s.acc["vendas"] == 2
    m = O.Conta(cfg("putmes"))
    m.criado = ini
    andar(m, mk, ini, fim)
    # a mensal vende a da última sexta do mês, de 21 a 50 dias à frente (de 02/10: a de 30/10, a 28 dias)
    vencs = {p["venc"] for p in m.pos}
    assert m.acc["vendas"] <= 2 and all(O.ultima_sexta_do_mes(v) for v in vencs)


def teste_mercado_vivo():
    S = 77_550.0
    venc = ms("2026-11-13T08:00:00")
    cadeia = [{"instrument_name": "BTC-13NOV26-70000-P", "bid_price": 0.0021, "ask_price": 0.0025, "mark_price": 0.0023,
               "mark_iv": 45.0, "underlying_price": 77_600.0, "estimated_delivery_price": S},
              {"instrument_name": "BTC-13NOV26-74000-P", "bid_price": 0.0065, "ask_price": 0.0072, "mark_price": 0.0068,
               "mark_iv": 42.0, "underlying_price": 77_600.0, "estimated_delivery_price": S},
              {"instrument_name": "BTC-13NOV26-60000-P", "bid_price": None, "ask_price": 0.0001, "mark_price": 0.00003,
               "mark_iv": 60.0, "underlying_price": 77_600.0, "estimated_delivery_price": S},
              {"instrument_name": "BTC-PERPETUAL", "bid_price": 1, "mark_price": 1}]
    mk = O.MercadoVivo({"BTC": cadeia}, {"BTC": S}, {"BTC": {"2026-11-06": 76_000.0}})
    t = ms("2026-11-06T12:00:00")
    assert mk.vencimentos("BTC", t) == [venc]
    assert O.escolher_vencimento(mk, "BTC", t, "semana") == venc
    ops = mk.opcoes("BTC", t, "put", venc)
    assert len(ops) == 3 and perto(next(o for o in ops if o["K"] == 70000)["bid"], 0.0021 * S)
    escolhida = O.escolher_strike(ops, t, 0.15)
    assert escolhida["K"] in (70000.0, 74000.0) and escolhida["bid"] > 0  # a de 60.000 não tem oferta de compra
    assert mk.entrega("BTC", ms("2026-11-06T08:00:00")) == 76_000.0


# ------------------------------------------------------------------------------------------- rodadas
def rodar(cli, pasta, quando, prazo=20):
    cli.agora = quando
    return papel.rodada(cli, pasta, quando, formas=["opcoes"], prazo_min=prazo, exemplo=True, buscar_cdi=False,
                        log=papel.Log(quieto=True))


def ler(pasta):
    with open(os.path.join(pasta, "opcoes.json")) as f:
        return json.load(f)


def teste_rodadas():
    a = tempfile.mkdtemp(prefix="opcoes-a-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora  # quinta, 22/10/2026 00h UTC
        assert dt.datetime.fromtimestamp(t0 / 1000, dt.timezone.utc).weekday() == 3
        rodar(cli, a, t0)
        d = ler(a)
        conferir_forma(d, "opcoes")
        # antes da 1ª sexta: sem ao vivo, com o teste no passado e a data em que o ao vivo começa
        assert all(v["aoVivo"] is None and v["historico"] for v in d["versoes"])
        assert d["config"]["aoVivoComeca"] == ms("2026-10-23T08:00:00") and d["config"]["ivHistorico"] == "dvol"
        assert all(v["historico"]["aproximado"] for v in d["versoes"])
        for k in range(1, 12):
            ind = rodar(cli, a, t0 + k * 6 * HORA)
            assert ind["formas"]["opcoes"]["ok"]
        d = ler(a)
        conferir_forma(d, "opcoes")
        assert all(v["aoVivo"] for v in d["versoes"]), [v["id"] for v in d["versoes"] if not v["aoVivo"]]
        assert "aoVivoComeca" not in d["config"]
        vendeu = [e for e in d["eventos"] if e["tipo"] == "vendeu"]
        assert len(vendeu) >= 8 and all("delta" in e["texto"] for e in vendeu)
        assert d["itens"] and all(i["vence"] > d["agora"] for i in d["itens"])
        for v in d["versoes"]:
            x = v["aoVivo"]["extra"]
            assert "porDentro" in x and "metricas" in v["aoVivo"], v["id"]
            if v["grupo"] == "Referência":
                continue
            assert {"premios", "pagos", "vendas", "dentro", "semValor", "recompras", "emAberto", "naMoeda", "moeda"} <= set(x)
            assert v["alav"] == 1 and v["grupo"] in ("BTC", "ETH", "Garantia rendendo", "Prêmio caro", "A roda", "Referência")
        # a semana seguinte: vencem e vendem de novo
        for k in range(12, 42):
            rodar(cli, a, t0 + k * 6 * HORA)
        d = ler(a)
        tipos = {e["tipo"] for e in d["eventos"]}
        assert tipos & {"recebeu", "pagou"}, tipos
        # falha da cadeia: ok false e o arquivo da rodada boa fica
        antes = ler(a)
        cli.falhar.add("deribit:get_book_summary_by_currency")
        ind = rodar(cli, a, t0 + 42 * 6 * HORA)
        assert ind["formas"]["opcoes"]["ok"] is False and ler(a) == antes
        cli.falhar.clear()
    finally:
        shutil.rmtree(a, ignore_errors=True)


def teste_sem_dvol_e_sem_tempo():
    a = tempfile.mkdtemp(prefix="opcoes-b-")
    try:
        cli = falso.ClientePapelFalso()
        cli.falhar.add("deribit:get_volatility_index_data")
        rodar(cli, a, cli.agora)
        d = ler(a)
        assert d["config"]["ivHistorico"] == "realizada" and any("DVOL" in x for x in d["rodada"]["erros"])
        assert any(v["historico"] for v in d["versoes"])
        # sem tempo na rodada: o teste no passado fica para a próxima
        b = tempfile.mkdtemp(prefix="opcoes-c-")
        try:
            cli2 = falso.ClientePapelFalso()
            rodar(cli2, b, cli2.agora, prazo=3)
            assert all(v["historico"] is None for v in ler(b)["versoes"])
        finally:
            shutil.rmtree(b, ignore_errors=True)
    finally:
        shutil.rmtree(a, ignore_errors=True)


# ------------------------------------------------------------------------------------------- revisão de 09/11/2026
def oscila(base=100_000.0, amp=0.002, ini=None, queda=None, nivel=1.0):
    """Um preço que sobe e desce `amp` a cada hora (volatilidade realizada ≈ 2·amp·√8760) em volta de `base`."""
    def p(t):
        x = base * (nivel if queda and t >= queda else 1.0)
        return x * math.exp(amp if (t // HORA) % 2 else -amp)
    return p


def aave_fixa(taxa):
    import looping as LP
    return LP.Taxas({}, {"sup:USDC": taxa})


def teste_versoes_e_grupos():
    ids = [c[0] for c in O.VERSOES]
    assert len(ids) == len(set(ids))
    for vid in ("put30C", "putstopC", "eth_put15C", "put30vrp", "eth_put15vrp", "roda", "eth_roda", "segbtc", "segeth", "usdc"):
        assert vid in ids, vid
    # as réguas por último
    grupos = [O.GRUPO.get(c[0], c[2]) for c in O.VERSOES]
    assert grupos[-3:] == ["Referência"] * 3 and "Referência" not in grupos[:-3]
    assert O.contra_de(O.cfg_de("put30C")) == "usdc" and O.contra_de(O.cfg_de("eth_call15")) == "segeth"
    assert O.contra_de(O.cfg_de("call15")) == "segbtc" and O.contra_de(O.cfg_de("roda")) == "cdi"
    assert O.contra_de(O.cfg_de("strangle")) == "cdi" and O.contra_de(O.cfg_de("usdc")) == "cdi"


def teste_spread_e_tique():
    ini, fim = ms("2026-10-01T00:00:00"), ms("2026-10-03T00:00:00")
    mk = mercado(lambda t: 100_000.0, ini, fim)
    t = ms("2026-10-02T08:00:00")
    venc = ms("2026-10-09T08:00:00")
    ops = mk.opcoes("BTC", t, "put", venc)
    tq = O.TIQUE * 100_000
    for o in ops:
        if o["bid"]:
            assert abs(o["bid"] / tq - round(o["bid"] / tq)) < 1e-6 and o["bid"] <= o["mark"] * (1 - O.MEIO_SPREAD_HIST) + 1e-9
    # com o spread medido na cadeia (10%), a oferta fica mais baixa
    mk2 = mercado(lambda t: 100_000.0, ini, fim)
    mk2.sorriso = {"BTC": {"put": {}, "call": {}, "spread": {"put": {"0.15": 0.10}, "call": {}}}}
    o1 = O.escolher_strike(ops, t, 0.15)
    o2 = next(o for o in mk2.opcoes("BTC", t, "put", venc) if o["K"] == o1["K"])
    assert o2["bid"] < o1["bid"] and perto(o2["mark"], o1["mark"])
    assert o2["bid"] <= o2["mark"] * 0.9 + 1e-9


def teste_sorriso_medido():
    """A medida do sorriso numa cadeia feita com a curva padrão devolve a curva padrão."""
    cli = falso.ClientePapelFalso()
    t = cli.agora
    cadeia = cli._cadeia("BTC")
    S = cli.mundo.px("BTC", t)
    mk = O.MercadoVivo({"BTC": cadeia}, {"BTC": S}, {})
    base = cli._iv("BTC", t)
    m = O.medir_sorriso(mk, "BTC", t, base)
    assert m and m["base"] == "dvol" and m["put"] and m["call"]
    for k, r in m["put"].items():
        # o falso usa o preço do futuro (um pouco acima do índice): a razão fica a ~1% da curva padrão
        assert abs(r - O.razao_padrao("put", float(k))) < 0.03, (k, r)
    assert all(0 < v < 0.5 for v in m["spread"]["put"].values())
    r = O.resumo_sorriso([m, m, None])
    assert r["n"] == 2 and r["fonte"] == "cadeia" and r["put"] == m["put"]
    assert O.resumo_sorriso([]) is None and O.sorriso_padrao()["fonte"] == "padrao"
    # sem o DVOL: a razão contra a volatilidade no dinheiro
    m2 = O.medir_sorriso(mk, "BTC", t, None)
    assert m2["base"] == "atm" and abs(m2["put"][max(m2["put"])] - 1.0) < 0.06


def teste_garantia_rendendo():
    ini, fim = ms("2026-10-01T00:00:00"), ms("2026-10-31T00:00:00")
    mk = mercado(lambda t: 100_000.0, ini - 30 * DIA, fim)
    mk.aave = aave_fixa(0.05)
    a, c = O.Conta(cfg("put30")), O.Conta(cfg("put30C"))
    a.criado = c.criado = ini
    andar(a, mk, ini, fim)
    andar(c, mk, ini, fim)
    assert c.na_aave and not a.na_aave and c.acc["juros"] > 0 and a.acc["juros"] == 0
    dias = (fim - ms("2026-10-02T08:00:00")) / DIA
    esperado = 1000 * (1.05 ** (dias / 365) - 1)
    assert abs(c.acc["juros"] - esperado) < 0.15 * esperado, (c.acc["juros"], esperado)
    assert perto(c.acc["aave"], O.CAIXA_IDA)
    assert perto(c.curva.ultimo - a.curva.ultimo, c.acc["juros"] - O.CAIXA_IDA, 1e-2)
    x = c.curva.extra
    assert x["naAave"] > 1000 and x["juroAgora"] == 0.05 and x["juros"] > 0
    # a conta por dentro fecha: resultado = prêmios − pagos − recompras − custos + juros + preço
    pd = x["porDentro"]
    assert perto(pd["resultado"], pd["premios"] - pd["pagos"] - pd["recompras"] - pd["custos"] + pd["juros"] + pd["emAberto"] + pd["preco"], 1e-6)
    assert abs(pd["preco"]) < 1e-6 and pd["emAberto"] < 0  # a put não segura moeda


def teste_pagar_tira_da_aave():
    ini = ms("2026-10-01T00:00:00")
    queda = ms("2026-10-05T00:00:00")
    mk = mercado(lambda t: 100_000.0 if t < queda else 70_000.0, ini - 30 * DIA, ms("2026-10-10T00:00:00"))
    mk.aave = aave_fixa(0.05)
    c = O.Conta(cfg("put30C"))
    c.criado = ini
    andar(c, mk, ini, ms("2026-10-09T09:00:00"))
    assert c.acc["dentro"] == 1 and perto(c.acc["aave"], O.CAIXA_IDA + O.CAIXA_VOLTA)


def teste_premio_caro():
    ini, fim = ms("2026-10-01T00:00:00"), ms("2026-10-24T00:00:00")
    # realizada ≈ 2 × 0,002 × √8760 ≈ 37%: com o DVOL a 60%, caro; a 30%, barato
    for vol, vende in ((0.60, True), (0.30, False)):
        mk = mercado(oscila(), ini - 35 * DIA, fim, vol=vol)
        mk.aave = aave_fixa(0.04)
        rv = mk.realizada("BTC", ms("2026-10-02T08:00:00"))
        assert 0.3 < rv < 0.45, rv
        ev = O.Eventos([])
        c = O.Conta(cfg("put30vrp"))
        c.criado = ini
        for t in O.horas(ini, fim):
            c.passo(mk, t, ev)
        f = c.curva.extra["filtro"]
        if vende:
            assert f["vendeu"] >= 3 and f["fora"] == 0 and c.acc["vendas"] >= 3
            vs = [e for e in ev.lista if e["tipo"] == "vendeu"]
            assert vs and all(e.get("motivo") == "caro" and "implícita" in e["texto"] for e in vs)
            assert f["ultima"]["razao"] >= O.VRP_MIN
        else:
            assert f["fora"] >= 3 and f["vendeu"] == 0 and c.acc["vendas"] == 0 and not c.pos
            fora = [e for e in ev.lista if e.get("motivo") == "barato"]
            assert len(fora) == f["fora"] and "realizada" in fora[0]["texto"]
            # fora das vendas, o dólar rende na Aave
            assert c.na_aave and c.acc["juros"] > 0 and c.curva.ultimo > 1000 - O.CAIXA_IDA
            # uma decisão por sexta (não tenta de novo na rodada seguinte)
            assert len(fora) == 4  # as sextas 02, 09, 16 e 23/10


def teste_roda():
    ini = ms("2026-10-01T00:00:00")
    queda, alta = ms("2026-10-05T00:00:00"), ms("2026-10-12T00:00:00")
    preco = lambda t: 100_000.0 if t < queda else (80_000.0 if t < alta else 120_000.0)  # noqa: E731
    mk = mercado(preco, ini - 30 * DIA, ms("2026-10-20T00:00:00"))
    ev = O.Eventos([])
    c = O.Conta(cfg("roda"))
    c.criado = ini
    for t in O.horas(ini, ms("2026-10-09T12:00:00")):
        c.passo(mk, t, ev)
    # a put de 02/10 venceu dentro em 09/10: a conta ficou com o bitcoin comprado no strike e vendeu uma call
    assert c.acc["exercidas"] == 1 and c.q > 0 and c.fase == "call"
    assert c.pos and c.pos[0]["tipo"] == "call" and perto(c.pos[0]["q"], c.q)
    ex = [e for e in ev.lista if e.get("motivo") == "exercida"]
    assert len(ex) == 1 and ex[0]["tipo"] == "trocou"
    for t in O.horas(ms("2026-10-09T12:00:00"), ms("2026-10-16T12:00:00")):
        c.passo(mk, t, ev)
    assert c.acc["chamadas"] == 1 and c.q == 0 and c.fase in ("put",)
    assert c.pos and c.pos[0]["tipo"] == "put"
    assert [e.get("motivo") for e in ev.lista if e["tipo"] == "trocou"] == ["exercida", "chamada"]
    x = c.curva.extra
    assert x["fase"] == "put" and x["exercidas"] == 1 and x["chamadas"] == 1
    pd = x["porDentro"]
    assert perto(pd["resultado"], pd["premios"] - pd["pagos"] - pd["recompras"] - pd["custos"] + pd["juros"] + pd["emAberto"] + pd["preco"], 1e-6)


def teste_reguas():
    ini, fim = ms("2026-10-01T00:00:00"), ms("2026-10-20T00:00:00")
    mk = mercado(lambda t: 100_000.0 if t < ms("2026-10-10T00:00:00") else 110_000.0, ini - 30 * DIA, fim)
    mk.aave = aave_fixa(0.05)
    b, u = O.Conta(cfg("segbtc")), O.Conta(cfg("usdc"))
    b.criado = u.criado = ini
    andar(b, mk, ini, fim)
    andar(u, mk, ini, fim)
    # começam na mesma 1ª sexta que as outras
    assert b.curva.inicio == u.curva.inicio == ms("2026-10-02T08:00:00")
    custo = O.TAXA_SPOT + O.DESLIZE_SPOT
    assert perto(b.curva.ultimo, 1000 / (1 + custo) * 1.1, 1e-3) and not b.pos and b.acc["vendas"] == 0
    assert u.na_aave and u.curva.ultimo > 1000 - O.CAIXA_IDA and u.acc["juros"] > 0 and u.q == 0
    assert "empate" not in b.curva.extra and "piorSemana" not in b.curva.extra
    assert O.estresse(cfg("segbtc"), b, mk, fim) is None


def teste_pior_semana_e_empate():
    ini = ms("2026-10-01T00:00:00")
    queda = ms("2026-10-12T00:00:00")
    mk = mercado(lambda t: 100_000.0 if t < queda else 75_000.0, ini - 30 * DIA, ms("2026-10-20T00:00:00"))
    c = O.Conta(cfg("put15"))
    c.criado = ini
    andar(c, mk, ini, ms("2026-10-17T00:00:00"))
    ps = c.curva.extra["piorSemana"]
    # 02/10 → 09/10 sem valor; 09/10 → 16/10 dentro
    assert ps["vence"] == "2026-10-16" and ps["perda"] > 0 and ps["semanas"] == 2
    assert perto(ps["semanasDePremio"], round(ps["perda"] / ps["premioMedio"], 1), 1e-2)
    em = c.curva.extra["empate"]
    assert em["custos"] > 0 and em["premioSemana"] > 0 and em["jaPagou"] is False and em["semanasParaRecuperar"] > 1
    assert perto(em["semanas"], round(em["custos"] / em["premioSemana"], 1), 1e-2)


def teste_estresse():
    ini = ms("2026-10-01T00:00:00")
    mk = mercado(lambda t: 100_000.0, ini - 30 * DIA, ms("2026-10-10T00:00:00"))
    t = ms("2026-10-03T00:00:00")
    p = O.Conta(cfg("put15"))
    p.criado = ini
    andar(p, mk, ini, t)
    e = O.estresse(cfg("put15"), p, mk, t, premio_semana=10.0, premio_fonte="passado")
    assert e["base"] == "agora" and [x["variacao"] for x in e["choques"]] == [-0.15, -0.30]
    q15, q30 = e["choques"]
    assert 0 < q15["perda"] < q30["perda"] and perto(q30["perdaPct"], q30["perda"] / e["valor"], 1e-3)
    assert perto(q30["semanasDePremio"], round(q30["perda"] / 10.0, 1), 1e-2) and e["premioFonte"] == "passado"
    # a put de delta 0,15 está ~10% abaixo: a queda de 30% custa perto de (K − 70.000) × q
    op = p.pos[0]
    assert q30["perda"] > (op["K"] - 70_000) * op["q"] * 0.9
    # call coberta: as altas também (e nelas a conta ganha pouco: o ganho fica limitado)
    c = O.Conta(cfg("call15"))
    c.criado = ini
    andar(c, mk, ini, t)
    e = O.estresse(cfg("call15"), c, mk, t)
    vs = {x["variacao"]: x for x in e["choques"]}
    assert set(vs) == {-0.15, -0.30, 0.15, 0.30} and vs[-0.30]["perda"] > 250 and vs[0.30]["perda"] > -200
    assert vs[0.30]["semanasDePremio"] is None
    # sem posição: a teórica (o que a versão venderia agora)
    e = O.estresse(cfg("put30vrp"), None, mk, t)
    assert e["base"] == "teorica" and e["posicoes"] and e["choques"][1]["perda"] > 0


def teste_janelas():
    h = {"serie": [[(dt.date(2026, 6, 1) + dt.timedelta(days=i)).isoformat(), 1000 + i] for i in range(70)]}
    reg = {(dt.date(2026, 6, 1) + dt.timedelta(days=i)).isoformat(): 1000 + 2 * i for i in range(70)}
    j = O.janelas(h, "usdc", {}, 0.149, reg)
    assert j["contra"] == {"id": "usdc", "nome": "USDC na Aave"} and j["n"] >= 5 and j["vence"] == 0
    j2 = O.janelas(h, "usdc", {}, 0.149, {})
    assert j2["contra"]["id"] == "cdi" and "venceCdi" in j2


def teste_estado_antigo_refaz():
    a = tempfile.mkdtemp(prefix="opcoes-d-")
    try:
        cli = falso.ClientePapelFalso()
        rodar(cli, a, cli.agora)
        p = os.path.join(a, "estado.json")
        with open(p) as f:
            est = json.load(f)
        h = est["formas"]["opcoes"]["hist"]
        assert h["hv"] == O.HIST_V and h["sorriso"] == "cadeia"
        h.pop("hv")  # como o estado de antes de 09/11/2026
        h["em"] = cli.agora + 6 * HORA
        with open(p, "w") as f:
            json.dump(est, f)
        rodar(cli, a, cli.agora + 6 * HORA)
        with open(p) as f:
            assert json.load(f)["formas"]["opcoes"]["hist"]["hv"] == O.HIST_V
    finally:
        shutil.rmtree(a, ignore_errors=True)


def teste_rodadas_novas():
    a = tempfile.mkdtemp(prefix="opcoes-e-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora
        for k in range(0, 30):
            rodar(cli, a, t0 + k * 6 * HORA)
        d = ler(a)
        conferir_forma(d, "opcoes")
        vs = {v["id"]: v for v in d["versoes"]}
        assert [v["grupo"] for v in d["versoes"]][-3:] == ["Referência"] * 3
        assert vs["usdc"]["historico"] and vs["segbtc"]["historico"]
        for vid, v in vs.items():
            assert v["contra"] in ("usdc", "segbtc", "segeth", "cdi") and v["moeda"] in ("BTC", "ETH")
            for conta in (v["aoVivo"], v["historico"]):
                if conta:
                    assert "porDentro" in conta["extra"] and "metricas" in conta
            if v["grupo"] != "Referência":
                assert v["estresse"]["choques"], vid
                assert "piorSemana" in v["historico"]["extra"] or vid == "putmes", vid
            else:
                assert "estresse" not in v
        assert vs["put30C"]["historico"]["extra"]["juros"] > 0
        assert vs["roda"]["historico"]["extra"]["fase"] in ("put", "call")
        assert "filtro" in vs["put30vrp"]["historico"]["extra"]
        assert vs["put15"]["historico"]["janelas"] is None or vs["put15"]["historico"]["janelas"]["contra"]["id"] in ("usdc", "cdi")
        cfgd = d["config"]
        assert cfgd["sorriso"]["BTC"]["fonte"] == "cadeia" and cfgd["sorriso"]["BTC"]["n"] >= 20
        assert cfgd["vrp"]["minimo"] == O.VRP_MIN and cfgd["vrp"]["agora"]["BTC"]["rv"]
        assert cfgd["caixa"]["juroAgora"] is not None and cfgd["caixa"]["ponte"] == 0
        # o passado começa do sorriso medido: o historico guarda de onde veio
        # sem a Aave: o USDC na Aave fica sem dados, as outras seguem
        cli.falhar.add("aave")
        b = tempfile.mkdtemp(prefix="opcoes-f-")
        try:
            rodar(cli, b, cli.agora)
            d2 = ler(b)
            u = next(v for v in d2["versoes"] if v["id"] == "usdc")
            assert u["semDados"] and u["aoVivo"] is None and u["historico"] is None
            assert next(v for v in d2["versoes"] if v["id"] == "put30C")["historico"]
        finally:
            shutil.rmtree(b, ignore_errors=True)
        cli.falhar.clear()
    finally:
        shutil.rmtree(a, ignore_errors=True)


if __name__ == "__main__":
    teste_instrumentos_e_datas()
    teste_formula()
    teste_put_sem_valor()
    teste_put_paga_na_queda()
    teste_recompra()
    teste_call_coberta()
    teste_strangle_e_mensal()
    teste_mercado_vivo()
    teste_rodadas()
    teste_sem_dvol_e_sem_tempo()
    teste_versoes_e_grupos()
    teste_spread_e_tique()
    teste_sorriso_medido()
    teste_garantia_rendendo()
    teste_pagar_tira_da_aave()
    teste_premio_caro()
    teste_roda()
    teste_reguas()
    teste_pior_semana_e_empate()
    teste_estresse()
    teste_janelas()
    teste_estado_antigo_refaz()
    teste_rodadas_novas()
    print("ok")
