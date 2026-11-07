"""Testes da venda de opções no papel (sem rede). Uso: python3 tools/papel/teste_opcoes.py"""
from __future__ import annotations

import datetime as dt
import json
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
    # a inclinação: a put longe do preço fica mais cara, a call longe um pouco mais barata
    assert O.iv_com_inclinacao(0.5, S, K, T, "put") > 0.5 > O.iv_com_inclinacao(0.5, S, 110_000, T, "call")
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
            assert {"premios", "pagos", "vendas", "dentro", "semValor", "recompras", "emAberto", "naMoeda", "moeda"} <= set(x)
            assert v["alav"] == 1 and v["grupo"] in ("BTC", "ETH")
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
    print("ok")
