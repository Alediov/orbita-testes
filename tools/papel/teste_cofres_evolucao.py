"""python3 tools/papel/teste_cofres_evolucao.py — a Evolução dos Cofres (cofres_evolucao.py), sem rede: um banco de
cofres inventado para as contas à mão e, depois, o mercado de mentira rodando dia a dia (o banco semeado pelo teste
fora da amostra, a lista andando a cota, o laboratório e a liga)."""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)

import cofres_evolucao as CE  # noqa: E402
import evolucao_series as ES  # noqa: E402
import falso  # noqa: E402
import papel  # noqa: E402
from conta import dia_de  # noqa: E402

HORA, DIA = falso.HORA, falso.DIA
D0 = dt.date(2026, 6, 1)
dia = lambda n: (D0 + dt.timedelta(days=n)).isoformat()  # noqa: E731
ms = lambda n: int(dt.datetime(D0.year, D0.month, D0.day, 15, tzinfo=dt.timezone.utc).timestamp() * 1000) + n * DIA  # noqa: E731
N = 160


def ok(c, msg=""):
    if not c:
        raise AssertionError(msg)


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol


def banco_a_mao():
    """A: +0,2% ao dia, grande. B: +0,1% ao dia, pequeno. C: +0,3% ao dia e despenca 30% no dia 130. D: +0,15% ao dia,
    fecha no dia 120. E: sobe tudo num dia só (sem constância). HLP: +0,05% ao dia, sem comissão."""
    def serie(f):
        v, out = 1.0, []
        for n in range(N + 1):
            v *= f(n)
            out.append(round(v, 6))
        return out
    cofres = {
        "a": {"n": "Alfa", "com": 0.1, "c": ms(-200), "f": None, "d0": dia(0), "s": serie(lambda n: 1.002),
              "a0": dia(0), "av": [5000] * (N + 1), "antes": [0.9, 1.0, 0.02]},
        "b": {"n": "Beta", "com": 0.1, "c": ms(-200), "f": None, "d0": dia(0), "s": serie(lambda n: 1.001),
              "a0": dia(0), "av": [150] * (N + 1), "antes": [0.9, 1.0, 0.02]},
        "c": {"n": "Charlie", "com": 0.1, "c": ms(-200), "f": None, "d0": dia(0),
              "s": serie(lambda n: 0.7 if n == 130 else 1.003), "a0": dia(0), "av": [2000] * (N + 1), "antes": [0.9, 1.0, 0.02]},
        "d": {"n": "Delta", "com": 0.1, "c": ms(-200), "f": dia(120), "d0": dia(0), "s": serie(lambda n: 1.0015)[:121],
              "a0": dia(0), "av": [800] * 121, "antes": [0.9, 1.0, 0.02]},
        "e": {"n": "Eco", "com": 0.1, "c": ms(-200), "f": None, "d0": dia(0), "s": serie(lambda n: 1.5 if n == 80 else 1.0),
              "a0": dia(0), "av": [900] * (N + 1), "antes": [0.9, 1.0, 0.02]},
        CE.HLP: {"n": "HLP", "com": 0.0, "c": ms(-900), "f": None, "d0": dia(0), "s": serie(lambda n: 1.0005),
                 "a0": dia(0), "av": [300000] * (N + 1), "antes": [0.8, 1.0, 0.05]},
    }
    return {"bancoEv": {"v": CE.BANCO_V, "cofres": cofres, "ate": dia(N), "primeiro": dia(100)}}


def teste_contas():
    est = banco_a_mao()
    D = CE.Dados(est)
    df = CE.Definicao()
    ctrl = df.genes_controle()
    g = lambda **k: CE.reparar(CE.ESP, {**ctrl, **k})  # noqa: E731
    o = CE.ordinal
    ok(D.tem_dados and D.primeiro == dia(100))
    ok(ctrl == {"ordem": "nota", "n": 5, "tvl": 100_000, "idade": 30, "queda": 0.3, "fica": 28, "stop": 0, "hlp": 0}, ctrl)
    ok(df.descrever(ctrl) == "5 cofres · nota de hoje" and df.descrever(g(n=1, stop=0.15, hlp=0.25, tvl=1_000_000))
       == "1 cofre · nota de hoje · de US$ 1 mi ou mais · stop a −15% · 25% no HLP", df.descrever(g(n=1, stop=0.15, hlp=0.25)))
    ok([de for de, _ in df.sementes()] == ["top10", "top5s", "grandes", "constancia", "mix50", "mix25"])
    # as medidas: o lucro do mês e a queda de antes do banco
    m = D.medidas(o(dia(100)))
    ok(perto(m["a"]["lm"], 1.002 ** 30 - 1, 1e-4) and perto(m["a"]["l90"], 1.002 ** 90 - 1, 1e-4) and m["a"]["queda"] == 0.02, m["a"])
    ok(perto(m["a"]["tvl"], 5_000_000) and m["a"]["idade"] == 300 and m["a"]["const"] is not None, m["a"])
    ok(m["e"]["const"] is None and m["e"]["l90"] > 0.4, "um dia só fez o lucro: sem constância")
    # quem passa: o HLP nunca; o pequeno sai com o tamanho; o do dia só sai na constância; a ordem muda com o gene
    ok(CE.escolher(D, ctrl, o(dia(100))) == ["e", "c", "a", "d", "b"], CE.escolher(D, ctrl, o(dia(100))))
    ok(CE.escolher(D, g(tvl=300_000), o(dia(100))) == ["e", "c", "a", "d"], "o Beta tem US$ 150 mil")
    ok(set(CE.escolher(D, g(ordem="const"), o(dia(100)))) == {"a", "b", "c", "d"}, "um dia só fez o lucro do Eco")
    ok(CE.escolher(D, g(ordem="tri"), o(dia(100)))[:2] == ["e", "c"] and CE.escolher(D, g(ordem="mes"), o(dia(100)))[0] == "e")
    ok(CE.escolher(D, ctrl, o(dia(111)))[0] == "c", "30 dias depois do salto, o mês do Eco é zero: não passa")
    ok("d" not in CE.escolher(D, ctrl, o(dia(121))), "o cofre fechado não entra")
    ok("c" not in CE.escolher(D, ctrl, o(dia(131))), "depois da queda de 30% o mês ficou negativo")

    # 1 cofre, sem troca: o Charlie de 100 a 129, com a comissão descontada do lucro
    c = CE.simular(D, g(n=1, ordem="mes"), dia(111), dia(129))
    bruto = 1000 * 1.003 ** 18
    ok(perto(c["serie"][-1][1], bruto - 0.1 * (bruto - 1000), 0.02) and c["ops"] == 1 and c["membros"] == ["Charlie"], c["serie"][-1])
    ok(c["serie"][0] == [dia(111), 1000.0] and c["montou"] and c["custos"] == 0)
    # a queda de 30% num dia: sem stop, fica as 4 semanas; com stop de 15%, sai no dia (já no prejuízo) e vai para o seguinte
    sem = CE.simular(D, g(n=1, ordem="mes"), dia(111), dia(140))
    com = CE.simular(D, g(n=1, ordem="mes", stop=0.15), dia(111), dia(140))
    ok(sem["largadas"] == 0 and com["largadas"] == 1 and com["membros"] == ["Alfa"], (sem["membros"], com["membros"]))
    vs, vc = dict(map(tuple, sem["serie"])), dict(map(tuple, com["serie"]))
    ok(perto(vc[dia(135)] / vc[dia(131)], 1.0018 ** 4, 1e-4), "depois do stop, o dinheiro está no Alfa (0,2% ao dia menos a comissão)")
    ok(perto(vs[dia(135)] / vs[dia(131)], 1.003 ** 4, 1e-4), "sem stop, fica no Charlie as 4 semanas")
    ok(vc[dia(130)] < 800 and sem["membros"] == ["Alfa"], "o stop não salva de uma queda num dia só; na 4ª semana a regra troca")
    # o cofre que fecha: sai pelo último valor e a vaga vai para outro
    c = CE.simular(D, g(n=1, ordem="mes", queda=0.5), dia(100), dia(125))
    ok(c["membros"] and c["membros"] != ["Delta"])
    d = CE.simular(D, g(n=2, tvl=300_000, fica=7), dia(112), dia(125))
    ok("Delta" not in d["membros"] and len(d["membros"]) == 2, d["membros"])
    # a parte no HLP: metade lá, metade nos cofres; sem cofre nenhum na regra, tudo no HLP
    h = CE.simular(D, g(n=2, hlp=0.5), dia(100), dia(101))
    ok(h["membros"][-1] == "HLP" and len(h["membros"]) == 3, h["membros"])
    so = CE.simular(D, g(n=2, hlp=0.5, tvl=3_000_000, idade=180, queda=0.15), dia(135), dia(140))
    ok(set(so["membros"]) <= {"Alfa", "HLP"} and "HLP" in so["membros"], so["membros"])
    nada = CE.simular(D, g(tvl=3_000_000, idade=180, ordem="const", queda=0.15, n=1), dia(131), dia(131))
    ok(nada["membros"] in (["Alfa"], []) and nada["serie"][-1][1] <= 1000.0)
    # 5 cofres: partes iguais, o reequilíbrio semanal não cria nem some com dinheiro
    c = CE.simular(D, ctrl, dia(100), dia(119))
    ok(len(c["membros"]) == 5 and 1000 < c["serie"][-1][1] < 1000 * 1.003 ** 19 + 1 + 150, c["serie"][-1])
    ok(ES.nota_lab(CE.simular(D, ctrl, dia(100), dia(N))) is not None)


def teste_banco():
    # semear: o formato do cofres_passado (semanal antes do corte, diário depois) vira um ponto por dia
    ini, fim = ms(100), ms(140)
    corte = ini - 100 * DIA
    s = [[corte - 14 * DIA, 0.8], [corte - 7 * DIA, 1.0], [corte - 1, 0.9]] + [[corte + k * DIA, 1 + k / 1000] for k in range(141)]
    av = [[ini - 45 * DIA + k * DIA, 2_000_000 + k * 1000] for k in range(86)]
    dados = {"x": {"n": "Xis", "com": 0.1, "lf": 0.2, "c": ms(-300), "f": None, "s": s, "av": av},
             "y": {"n": "Ípsilon", "com": 0.2, "lf": None, "c": ms(-300), "f": ms(120), "s": s[:124], "av": av[:60]},
             "curto": {"n": "Curto", "com": 0.1, "c": ms(90), "f": None, "s": [[fim, 1.0]], "av": []}}
    est = {}
    ok(CE.semear(est, dados, ini, fim) == 2)
    b = est["bancoEv"]
    x = b["cofres"]["x"]
    ok(b["primeiro"] == dia_de(ini) and x["d0"] == dia_de(corte) and len(x["s"]) == 141 and x["s"][-1] == 1.14, (x["d0"], len(x["s"])))
    ok(x["antes"] == [0.8, 1.0, 0.1] and x["av"][0] == 2000 and x["av"][-1] == 2085 and x["a0"] == dia_de(ini - 45 * DIA), x["antes"])
    ok(b["cofres"]["y"]["f"] == dia_de(ms(120)) and "curto" not in b["cofres"])
    # a lista anda a cota: r = Δ lucro ÷ TVL de ontem; o 1º dia só marca o ponto de partida
    linha = lambda pnl, tvl, fechado=False: {"lucroTotalUS": pnl, "tvl": tvl, "fechado": fechado}  # noqa: E731
    ok(CE.atualizar(est, {"x": linha(500_000, 2_000_000)}, {}, fim + DIA) == 1)
    ok(len(x["s"]) == 142 and x["s"][-1] == 1.14 and x["p"] == [500_000, 2_000_000] and b["ate"] == dia_de(fim + DIA))
    ok(CE.atualizar(est, {"x": linha(520_000, 2_100_000)}, {}, fim + DIA + HORA) == 0, "uma vez por dia")
    CE.atualizar(est, {"x": linha(520_000, 2_100_000)}, {}, fim + 3 * DIA)   # pulou um dia: repete o valor
    ok(len(x["s"]) == 144 and x["s"][-2] == 1.14 and perto(x["s"][-1], 1.14 * 1.01, 1e-5) and x["av"][-1] == 2100, x["s"][-3:])
    # o acompanhado do teste tem a cota fina: vale ela, não a da lista
    cof = {"x": {"i": 2.0, "tvl": 2_200_000, "fechado": False}}
    CE.atualizar(est, {"x": linha(541_000, 2_200_000)}, cof, fim + 4 * DIA)
    ok(perto(x["s"][-1], x["s"][-2] * 1.01, 1e-5) and x["ci"] == 2.0, "no 1º dia com a cota fina ainda vale a lista")
    cof["x"]["i"] = 2.1
    CE.atualizar(est, {"x": linha(999_000, 2_200_000)}, cof, fim + 5 * DIA)
    ok(perto(x["s"][-1], x["s"][-2] * 1.05, 1e-5))
    # fechou na lista; sumiu da lista
    CE.atualizar(est, {"x": linha(999_000, 0, True)}, {}, fim + 6 * DIA)
    ok(x["f"] == dia_de(fim + 6 * DIA))
    est2 = {}
    CE.semear(est2, {"x": dados["x"]}, ini, fim)
    CE.atualizar(est2, {"outro": linha(1, 1)}, {}, fim + DIA)
    ok(est2["bancoEv"]["cofres"]["x"]["f"] == dia_de(fim + DIA), "sumiu da lista: acaba hoje")
    ok(CE.atualizar(est2, {}, {}, fim + 2 * DIA) == 0 and est2["bancoEv"]["ate"] == dia_de(fim + DIA), "sem lista, não anda")
    # semear de novo troca a história e mantém os dias que vieram depois, na escala nova
    est3 = {}
    CE.semear(est3, {"x": dados["x"]}, ini, fim)
    CE.atualizar(est3, {"x": linha(0, 1_000_000)}, {}, fim + DIA)
    CE.atualizar(est3, {"x": linha(100_000, 1_000_000)}, {}, fim + 2 * DIA)   # +10%
    dobro = dict(dados["x"], s=[[t, v * 2] for t, v in s])
    CE.semear(est3, {"x": dobro}, ini, fim)
    x3 = est3["bancoEv"]["cofres"]["x"]
    ok(len(x3["s"]) == 143 and x3["s"][140] == 2.28 and perto(x3["s"][-1], 2.28 * 1.1, 1e-4) and x3["p"] == [100_000, 1_000_000], x3["s"][-3:])
    # podar: só MAX_DIAS dias; o que sai vira o topo e a queda de antes; o fechado antigo some
    velho = {"bancoEv": {"v": CE.BANCO_V, "ate": None, "primeiro": dia(0), "cofres": {
        "z": {"n": "Zê", "com": 0.1, "c": None, "f": None, "d0": dia(0), "s": [1.0, 2.0, 1.0] + [1.5] * 400, "a0": dia(0),
              "av": [100] * 403, "antes": [1.0, 0.0, 0.0]},
        "w": {"n": "Dabliú", "com": 0.1, "c": None, "f": dia(5), "d0": dia(0), "s": [1.0] * 6, "a0": None, "av": [], "antes": [1, 1, 0]}}}}
    CE.podar(velho["bancoEv"], CE.ordinal(dia(402)))
    z = velho["bancoEv"]["cofres"]["z"]
    ok(len(z["s"]) == CE.MAX_DIAS + 1 and z["antes"] == [1.0, 2.0, 0.5] and "w" not in velho["bancoEv"]["cofres"], (len(z["s"]), z["antes"]))
    ok(velho["bancoEv"]["primeiro"] == dia(402 - CE.MAX_DIAS + CE.PRE) and len(z["av"]) == len(z["s"]))


def teste_mercado_de_mentira():
    pasta = tempfile.mkdtemp()
    try:
        cli = falso.ClientePapelFalso()
        t0, log = cli.agora, papel.Log(quieto=True)
        d = None
        for k in range(100):
            cli.agora = t0 + k * 6 * HORA
            papel.rodada(cli, pasta, cli.agora, formas=["cofres"], exemplo=True, buscar_cdi=False, log=log)
            with open(os.path.join(pasta, "cofres.json")) as f:
                d = json.load(f)
            ok(not any("evolu" in e for e in d.get("erros") or []), d.get("erros"))
        with open(os.path.join(pasta, "estado.json")) as f:
            est = json.load(f)["formas"]["cofres"]
        b = est["bancoEv"]
        ok(len(b["cofres"]) >= 10 and b["ate"] == dia_de(cli.agora) and CE.HLP in b["cofres"], len(b["cofres"]))
        ok(all(len(x["s"]) <= CE.MAX_DIAS + 1 and x["s"][0] > 0 for x in b["cofres"].values()))
        ok(len(json.dumps(b)) < 6_000 * len(b["cofres"]), "o banco tem de caber no estado")
        ev = d["evolucao"]
        ok(ev["forma"] == "evolucao" and ev["formas"][0]["id"] == "cofres" and ev["formas"][0]["nome"] == "Cofres" and ev["avisos"])
        sp = ev["formas"][0]["especies"][0]
        P = ES.parametros(True)
        ok(sp["id"] == "cofres" and sp["controle"]["nome"] == "5 melhores" and len(sp["genes"]) == 8)
        liga, lab = sp["liga"], sp["lab"]
        ok(len(liga["pop"]) == P["POP_LIGA"] and liga["controle"]["aoVivo"]["serie"] and len(liga["semanas"]) >= 3, len(liga["semanas"]))
        ok(lab["g"] >= 20 and len(lab["pop"]) == P["POP"] and lab["controle"]["nota"] is not None, lab["g"])
        ok(len({json.dumps(x["genes"], sort_keys=True) for x in liga["pop"]}) == P["POP_LIGA"], "sem versões repetidas na liga")
        for x in liga["pop"] + [liga["controle"]]:
            a = x["aoVivo"]
            ok({"retorno", "piorQueda", "ops", "membros", "custos", "largadas"} <= set(a) and x["descricao"], x["nome"])
            ok(x["genes"] == CE.reparar(CE.ESP, x["genes"]) and 0 <= a["piorQueda"] < 0.9, x["nome"])
        ok(any(x["aoVivo"]["membros"] for x in liga["pop"]), "alguém tem de estar em algum cofre")
        ok(liga["controle"]["aoVivo"].get("metricas") is not None, "as métricas comuns no controle")
        ok(any(e["tipo"] == "semana" for e in ev["eventos"]) and len(json.dumps(ev)) < 120_000, len(json.dumps(ev)))
        ok(any("banco semeado" in l for l in log.linhas) if hasattr(log, "linhas") else True)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    teste_contas()
    teste_banco()
    teste_mercado_de_mentira()
    print("teste_cofres_evolucao: ok")
