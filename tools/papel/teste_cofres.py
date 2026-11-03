"""Testes dos cofres no papel (cofres.py) no mercado de mentira (falso_cofres.py). Uso: python3 tools/papel/teste_cofres.py"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)

import cofres as C  # noqa: E402
import falso  # noqa: E402
import falso_cofres as FC  # noqa: E402
import papel  # noqa: E402

HORA, DIA = falso.HORA, falso.DIA
RISCOS = {"baixo", "médio", "alto"}


def conferir_conta(c, onde, capital=True):
    if c is None:
        return
    for k in ("inicio", "serie", "retorno", "piorQueda", "ops", "taxas", "liquidacoes", "nLiq"):
        assert k in c, f"{onde}: falta {k}"
    dias = [d for d, _ in c["serie"]]
    assert dias == sorted(dias) and len(set(dias)) == len(dias), f"{onde}: série fora de ordem"
    assert 0 <= c["piorQueda"] <= 1, f"{onde}: pior queda {c['piorQueda']}"
    if c["serie"]:
        assert abs(c["serie"][-1][1] / 1000 - 1 - c["retorno"]) < 0.02, f"{onde}: retorno não bate com a série"
        if capital:
            assert abs(c["serie"][0][1] - 1000) < 60, f"{onde}: não começa perto de US$ 1.000 ({c['serie'][0]})"


def conferir_forma(d):
    for k in ("v", "forma", "nome", "agora", "frase", "comoFunciona", "padrao", "versoes", "eventos", "itens",
              "candidatos", "avisos", "config", "rodada"):
        assert k in d, f"falta {k}"
    ids = [v["id"] for v in d["versoes"]]
    assert len(ids) == len(set(ids)) and d["padrao"] in ids, ids
    for v in d["versoes"]:
        assert v["risco"] in RISCOS and v["nome"] and v["frase"] and v["alav"] == 1, v["id"]
        conferir_conta(v["aoVivo"], f"{v['id']}/aoVivo")
        conferir_conta(v.get("historico"), f"{v['id']}/historico")
        x = v["aoVivo"]["extra"]
        assert {"cofres", "travadoAte", "comissaoPaga"} <= set(x), x
        if v.get("historico"):
            assert v["historico"]["aproximado"] is True and v["historico"]["de"] <= v["historico"]["ate"]
    for it in d["itens"]:
        for k in ("endereco", "nome", "tvl", "apr", "idadeDias", "comissao", "seguidoresMax", "fixo", "motivo", "desde",
                  "aoVivo", "historico", "saiu"):
            assert k in it, f"item sem {k}"
        conferir_conta(it["aoVivo"], f"item {it['nome']}")
        conferir_conta(it["historico"], f"item {it['nome']}/historico")
    assert len(d["candidatos"]) <= 40
    for c in d["candidatos"]:
        assert {"endereco", "nome", "tvl", "apr", "idadeDias", "lucroMes", "lucroTotal", "piorQueda", "comissao", "passou", "motivo"} <= set(c)
    for e in d["eventos"]:
        assert {"em", "versao", "tipo", "texto"} <= set(e)
    assert [e["em"] for e in d["eventos"]] == sorted((e["em"] for e in d["eventos"]), reverse=True)
    assert len(json.dumps(d, ensure_ascii=False)) < 400_000, "cofres.json grande demais"


def rodar(pasta, tempos, cli=None, quieto=True):
    cli = cli or falso.ClientePapelFalso()
    ind, log = None, papel.Log(quieto=quieto)
    for t in tempos:
        cli.agora = t
        ind = papel.rodada(cli, pasta, t, formas=["cofres"], exemplo=True, buscar_cdi=False, log=log)
    with open(os.path.join(pasta, "cofres.json")) as f:
        return ind, json.load(f), cli, log


def teste_contas_pequenas():
    # cota: r = Δlucro ÷ patrimônio anterior; o patrimônio cai pela metade (saque dos outros) e a cota não
    pts = [(0, 100.0, 0.0), (10, 110.0, 10.0), (20, 50.0, 15.0)]
    novos, lacuna = C.encadear(pts, 0, 1.0)
    assert not lacuna and abs(novos[-1][1] - 1.1 * (1 + 5 / 110)) < 1e-12, novos
    novos, _ = C.encadear(pts, 5, 1.0)  # começa no meio do 1º trecho: só metade dele conta
    assert abs(novos[0][1] - 1.05) < 1e-12 and abs(novos[1][1] - 1.05 * (1 + 5 / 110)) < 1e-12, novos
    novos, lacuna = C.encadear(pts, -50, 1.0)  # a janela começa depois do último processado
    assert lacuna and abs(novos[-1][1] - 1.15) < 1e-12
    assert C.encadear(pts, 20, 1.0)[0] == []

    # comissão: US$ 1.000 a cota 1, cota 1,2 → valor 1.200, comissão 10% do lucro = 20 → mostra 1.180
    cart = C.Carteira({}, 0)
    assert cart.entrar("a", 1000, 0, 1.0, 0.1, C.TRAVA)
    assert abs(cart.valor(lambda a: 1.2) - 1180) < 1e-9
    volta, com = cart.sair("a", DIA, 1.2)
    assert abs(volta - 1180) < 1e-9 and abs(com - 20) < 1e-9 and abs(cart.d["pago"] - 20) < 1e-9 and cart.curva.taxas == 20
    assert cart.curva.ops == 2 and abs(cart.d["caixa"] - 1180) < 1e-9
    # prejuízo: sem comissão
    cart = C.Carteira({}, 0)
    cart.entrar("a", 1000, 0, 1.0, 0.1, C.TRAVA)
    assert abs(cart.valor(lambda a: 0.9) - 900) < 1e-9

    # trava: pedir para sair antes do fim da trava espera; depois, sai
    info = lambda a: {"nome": a, "com": 0.1, "aceita": True, "fechado": False, "tvl": 1e6, "lucroMes": 0.01}  # noqa: E731
    ev = C.Eventos()
    cart = C.Carteira({}, 0)
    C.ajustar(cart, "v", 0, ["a", "b"], 2, info, lambda a: 1.0, ev)
    assert set(cart.h) == {"a", "b"} and abs(cart.h["a"]["custo"] - 500) < 1e-9
    assert "Montou a carteira com 2 cofres" in ev.lista[-1]["texto"]
    s, e = C.ajustar(cart, "v", HORA, ["b", "c"], 2, info, lambda a: 1.0, ev)
    assert not s and not e and "travado" in ev.lista[-1]["texto"] and cart.h["a"]["sair"]
    s, e = C.ajustar(cart, "v", DIA + 1, ["b", "c"], 2, info, lambda a: 1.1, ev)
    assert [x[0] for x in s] == ["a"] and [x[0] for x in e] == ["c"] and ev.lista[-1]["tipo"] == "trocou"
    assert abs(cart.h["c"]["custo"] - (550 - 5)) < 1e-9  # 500 × 1,1 menos 10% do lucro de 50
    # reequilíbrio na escolha: o novo entra com a parte igual, tirada dos outros
    cart = C.Carteira({}, 0)
    C.ajustar(cart, "v", 0, ["a", "b"], 3, info, lambda a: 1.0)
    assert abs(cart.h["a"]["custo"] - 500) < 1e-9 and cart.d["caixa"] < 1e-9
    _, e = C.ajustar(cart, "v", 2 * DIA, ["a", "b", "c"], 3, info, lambda a: 1.0, ev, reequilibrar=True)
    assert [x[0] for x in e] == ["c"] and abs(cart.h["c"]["custo"] - 1000 / 3) < 1e-6, cart.h
    assert abs(cart.h["a"]["q"] - 1000 / 3) < 1e-6 and ev.lista[-1]["tipo"] == "reequilibrou"
    # dinheiro parado vai para os que já tem
    cart.d["caixa"] += 90
    C.ajustar(cart, "v", 3 * DIA, ["a", "b", "c"], 3, info, lambda a: 1.0, ev, reequilibrar=True)
    assert cart.d["caixa"] < 1e-9 and abs(cart.h["a"]["custo"] - (1000 / 3 + 30)) < 1e-6 and "parados" in ev.lista[-1]["texto"]
    # o HLP trava 4 dias
    cart = C.Carteira({}, 0)
    C.ajustar(cart, "hlp", 0, [C.HLP], 1, lambda a: {**info(a), "com": 0.0}, lambda a: 1.0)
    assert cart.h[C.HLP]["ate"] == 4 * DIA
    # cofre fechado sai na hora, mesmo travado
    s, _ = C.ajustar(cart, "hlp", HORA, [C.HLP], 1, info, lambda a: 1.0, forcar={C.HLP})
    assert s and not cart.h

    # saída na queda (top5s): cai 20% do topo; travada espera, depois sai
    cart = C.Carteira({}, 0)
    cart.entrar("a", 1000, 0, 1.0, 0.0, C.TRAVA)
    C.conferir_stop(cart, "top5s", HORA, lambda a: 1.1, info)
    assert not cart.h["a"].get("sair") and abs(cart.h["a"]["pico"] - 1100) < 1e-9
    assert C.conferir_stop(cart, "top5s", 2 * HORA, lambda a: 0.88, info) == []  # −20% do topo, mas travado
    assert cart.h["a"]["sair"].startswith("caiu") and "a" in cart.d["ban"]
    assert C.conferir_stop(cart, "top5s", DIA + 1, lambda a: 0.9, info) == ["a"]
    assert abs(cart.d["caixa"] - 900) < 1e-9

    # regra
    base = {"endereco": "0x1", "aceita": True, "fechado": False, "tvl": 2e5, "idadeDias": 60, "lf": 0.1,
            "lucroMes": 0.01, "lucroTotal": 0.2, "piorQueda": 0.1}
    assert C.motivo_regra(base) is None
    for k, v, trecho in (("tvl", 5e4, "TVL"), ("idadeDias", 10, "30 dias"), ("lf", 0.03, "líder"),
                         ("lucroMes", -0.01, "mês"), ("lucroTotal", -0.1, "início"), ("piorQueda", 0.35, "topo"),
                         ("aceita", False, "depósitos"), ("fechado", True, "fechado"), ("filhoHLP", True, "filho")):
        assert trecho in C.motivo_regra({**base, k: v}), k
    assert "HLP" in C.motivo_regra({**base, "endereco": C.HLP})

    # fixados: arquivo ausente ou inválido = nenhum
    pasta = tempfile.mkdtemp()
    try:
        arq = os.path.join(pasta, "f.json")
        assert C.ler_fixos(arq) == []
        with open(arq, "w") as f:
            f.write("{nada")
        assert C.ler_fixos(arq) == []
        with open(arq, "w") as f:
            json.dump({"fixos": [{"endereco": "0x" + "AB" * 20, "em": "2026-11-01"}, {"endereco": "lixo"}, "0x" + "ab" * 20]}, f)
        assert C.ler_fixos(arq) == ["0x" + "ab" * 20]
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def teste_rodadas():
    pasta = tempfile.mkdtemp(prefix="cofres-")
    arq_fixos = os.path.join(pasta, "fixos.json")
    timido = FC.endereco("Líder Tímido")
    with open(arq_fixos, "w") as f:
        json.dump({"fixos": [{"endereco": timido, "em": "2026-10-25"}]}, f)
    antigo = C.ARQ_FIXOS
    try:
        t0 = FC.A0 + 6 * HORA
        tempos = [t0 + k * 6 * HORA for k in range(29)]          # 7 dias, a cada 6 h
        C.ARQ_FIXOS = os.path.join(pasta, "nenhum.json")
        ind, d, cli, log = rodar(os.path.join(pasta, "a"), tempos[:12])
        C.ARQ_FIXOS = arq_fixos                                   # ele fixa um cofre no meio
        ind, d, cli, log = rodar(os.path.join(pasta, "a"), tempos[12:] + [tempos[-1] + 30 * HORA], cli)  # e uma lacuna de 30 h
        assert ind["formas"]["cofres"]["ok"], ind
        conferir_forma(d)
        ids = [v["id"] for v in d["versoes"]]
        assert ids == ["top5", "top10", "top5s", "hlp", "semana", "fixos"], ids
        v = {x["id"]: x for x in d["versoes"]}
        assert v["fixos"]["fixa"] is True and v["fixos"]["aoVivo"]["extra"]["cofres"] == 1
        assert v["hlp"]["aoVivo"]["extra"]["comissaoPaga"] == 0
        assert all(x["historico"] for x in d["versoes"] if x["id"] != "fixos") and v["fixos"]["historico"] is None
        nomes = {it["nome"]: it for it in d["itens"]}
        assert nomes["Hyperliquidity Provider (HLP)"]["comissao"] == 0
        assert nomes["Líder Tímido"]["fixo"] is True
        # os que mudaram no meio: fechou, sumiu, parou de aceitar depósitos (sai na segunda)
        assert "fechou" in nomes["Vai Fechar"]["saiu"]["motivo"], nomes["Vai Fechar"]["saiu"]
        assert "sumiu" in nomes["Fantasma"]["saiu"]["motivo"]
        assert "depósitos" in nomes["Lotado"]["saiu"]["motivo"]
        assert all(nomes[n]["saiu"] is None for n in ("Sol Nascente", "Systemic Grids"))
        textos = [e["texto"] for e in d["eventos"]]
        assert any(e["versao"] == "top5s" and "caiu" in e["texto"] for e in d["eventos"]), "top5s não saiu na queda"
        assert any("Foguete Quebrado" in t and "caiu" in t for t in textos)
        assert any(e["versao"] == "semana" and e["tipo"] in ("trocou", "entrou") for e in d["eventos"])
        assert any("Montou a carteira com 5 cofres" in t for t in textos)
        # os que não passam na regra não são seguidos
        seguidos = {it["nome"] for it in d["itens"] if not it["fixo"] and it["saiu"] is None}
        for n in ("Aposentado", "Recém-chegado", "Montanha-russa", "Porta Fechada", "Pequenino", "Mês Ruim",
                  "Sempre Perde", "HLP Strategy A", "HLP Liquidator"):
            assert n not in seguidos, n
        cand = {c["nome"]: c for c in d["candidatos"]}
        assert cand["Sol Nascente"]["passou"] and not cand["Recém-chegado"]["passou"]
        assert "30 dias" in cand["Recém-chegado"]["motivo"] and "topo" in cand["Montanha-russa"]["motivo"]
        # a cota (não o patrimônio): o item de "Entra e Sai" segue a cota do cofre de mentira
        es = next(c for c in FC.universo() if c.nome == "Entra e Sai")
        it = nomes["Entra e Sai"]
        ini, fim = es.k(it["desde"]), es.k(tempos[-1] + 30 * HORA)
        cota = es.i[fim] / es.i[ini] - 1
        pat = es.av(fim) / es.av(ini) - 1
        bruto = (1 + it["aoVivo"]["retorno"])  # o item mostra já sem a comissão: desfaz para comparar
        bruto = (bruto - 0.1) / 0.9 if bruto > 1 else bruto
        assert abs(bruto - 1 - cota) < 0.004, (bruto - 1, cota, pat)
        assert abs(pat - cota) > 0.02, "o cofre de mentira devia ter depósitos e saques dos outros"
        # a lacuna de 30 h: igual (quase) a quem rodou sem pular
        _, d2, _, _ = rodar(os.path.join(pasta, "b"), tempos[:12] + tempos[12:] + [tempos[-1] + k * 6 * HORA for k in range(1, 6)])
        v2 = {x["id"]: x for x in d2["versoes"]}
        for k in ("hlp", "top10"):
            a, b = v[k]["aoVivo"]["retorno"], v2[k]["aoVivo"]["retorno"]
            assert abs(a - b) < 0.003, (k, a, b)
        # lacuna maior que a semana: usa a janela do mês (e avisa no log)
        ind, d3, _, log3 = rodar(os.path.join(pasta, "a"), [tempos[-1] + 30 * HORA + 10 * DIA], cli)
        assert ind["formas"]["cofres"]["ok"] and any("janela month" in x for x in log3.linhas), log3.linhas[-20:]
        conferir_forma(d3)
    finally:
        C.ARQ_FIXOS = antigo
        shutil.rmtree(pasta, ignore_errors=True)


def teste_falhas():
    pasta = tempfile.mkdtemp(prefix="cofres-f-")
    antigo = C.ARQ_FIXOS
    C.ARQ_FIXOS = os.path.join(pasta, "nenhum.json")
    try:
        # a lista falha na 1ª rodada: a forma fica ok: false (sem arquivo), sem quebrar a rodada
        cli = falso.ClientePapelFalso()
        cli.falhar.add("vaults")
        cli.agora = FC.A0
        ind = papel.rodada(cli, pasta, cli.agora, formas=["cofres"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))
        assert "cofres" not in ind["formas"] or not ind["formas"]["cofres"]["ok"]
        cli.falhar.clear()
        ind, d, cli, _ = rodar(pasta, [FC.A0 + 6 * HORA, FC.A0 + 12 * HORA], cli)
        assert ind["formas"]["cofres"]["ok"]
        # vaultDetails falha: ok: false, o arquivo da rodada anterior fica
        cli.falhar.add("vaultDetails")
        cli.agora = FC.A0 + 18 * HORA
        ind = papel.rodada(cli, pasta, cli.agora, formas=["cofres"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))
        f = ind["formas"]["cofres"]
        assert f["ok"] is False and "vaultDetails" in f["erro"], f
        with open(os.path.join(pasta, "cofres.json")) as fh:
            assert json.load(fh)["agora"] == FC.A0 + 12 * HORA
        # e volta na rodada seguinte, alcançando o tempo perdido
        cli.falhar.clear()
        ind, d, _, _ = rodar(pasta, [FC.A0 + 24 * HORA], cli)
        assert ind["formas"]["cofres"]["ok"]
        conferir_forma(d)
        assert max(s[0] for s in d["versoes"][0]["aoVivo"]["serie"]) == C.dia_de(FC.A0 + 24 * HORA)
        # a lista falha numa segunda-feira com o estado pronto: a escolha fica para a próxima, a forma segue
        cli.falhar.add("vaults")
        ind, d, _, _ = rodar(pasta, [FC.A0 + 5 * DIA], cli)
        assert ind["formas"]["cofres"]["ok"] and any("escolha" in e for e in d["rodada"]["erros"]), d["rodada"]
    finally:
        C.ARQ_FIXOS = antigo
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    teste_contas_pequenas()
    teste_rodadas()
    teste_falhas()
    print("ok")
