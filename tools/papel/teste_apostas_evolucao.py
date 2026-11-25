"""python3 tools/papel/teste_apostas_evolucao.py — a Evolução das Apostas (apostas_evolucao.py): o banco compacto, as
contas à mão (o valor, a faixa, a casa melhor, o campeonato, Kelly), o controle contra a conta valor3 do teste no
passado, e a rodada inteira no mundo de mentira (o banco semeado pelas planilhas, o laboratório e a liga)."""
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

import apostas as A  # noqa: E402
import apostas_evolucao as AE  # noqa: E402
from conta import CAPITAL, DIA, HORA  # noqa: E402

T0 = int(dt.datetime(2026, 3, 2, 18, tzinfo=dt.timezone.utc).timestamp() * 1000)


def ok(c, msg=""):
    if not c:
        raise AssertionError(msg)


def justas(p):
    """Odds "da Pinnacle" sem margem nenhuma, das chances `p` (a leitura refaz as mesmas chances, a menos do
    arredondamento das odds em centavos)."""
    return [round(1 / x, 2) for x in p]


def jogo(n, liga, o, p, placar, om=None, ou=None):
    """Um jogo no formato de apostas.ler_planilha, no dia `n` depois de T0."""
    mk = {"1x2": {"o": o, "p": p, "pf": None, "jo": justas(p)}}
    if om:
        mk["1x2"]["om"] = om
    if ou:
        mk["ou"] = {"o": ou[0], "p": ou[1], "pf": None, "jo": justas(ou[1])}
    return {"id": f"{liga}-{n}-{o}", "liga": liga, "casa": "A", "fora": "B", "inicio": T0 + n * DIA, "placar": placar,
            "mk": mk}


def banco(jogos):
    est = {}
    AE.guardar_jogos(est, jogos, T0 + 40 * DIA)
    return est, AE.Dados(est)


def teste_banco():
    j = jogo(1, "eng", [2.1, 3.4, 3.5], [0.5, 0.27, 0.23], [2, 1], om=[2.15, 3.4, 3.6], ou=([1.9, 1.95], [0.52, 0.48]))
    ln = AE.linha_do_jogo(j)
    ok(ln[1] == "eng" and ln[4] == [210, 340, 350] and ln[5] == [2000, 3700, 4350], ln)
    ok(dt.date.fromordinal(ln[0] + AE.EPOCA).isoformat() == A.dia_de(j["inicio"] + 2 * HORA))
    ok(ln[6] == [215, 340, 360] and ln[7] == [190, 195], ln)
    est, D = banco([j, jogo(2, "lib", [2, 3, 4], [0.5, 0.3, 0.2], [0, 0])])  # a Libertadores não entra
    ok(len(D.jogos) == 1 and D.jogos[0][1] == "eng" and D.jogos[0][3]["1x2"][2] == [2.15, 3.4, 3.6])
    ok(D.primeiro == A.dia_de(T0), D.primeiro)
    # o mesmo jogo de novo não repete; o velho sai
    AE.guardar_jogos(est, [j], T0 + 40 * DIA)
    ok(len(est["bancoEv"]["jogos"]) == 1)
    AE.guardar_jogos(est, [], T0 + (AE.BANCO_DIAS + 5) * DIA)
    ok(not est["bancoEv"]["jogos"])
    ok(len(json.dumps(ln, separators=(",", ":"))) < 90, len(json.dumps(ln, separators=(",", ":"))))


def teste_contas_a_mao():
    g = AE.Definicao().genes_controle()
    ok(g["limiar"] == 0.03 and g["de"] == 1.5 and g["ate"] == 4.0 and g["stake"] == "fixo" and g["aposta"] == 0.01)
    jogos = [
        jogo(1, "eng", [2.1, 3.4, 3.5], [0.5, 0.27, 0.23], [2, 1]),            # casa: valor 5%, ganha (+11)
        jogo(2, "esp", [2.0, 3.3, 4.2], [0.52, 0.27, 0.21], [0, 1]),           # casa: valor 4%, perde (−10)
        jogo(3, "bra", [1.9, 3.4, 4.5], [0.5, 0.28, 0.22], [1, 0]),            # sem valor na Bet365…
        jogo(4, "ita", [5.0, 3.6, 1.7], [0.21, 0.26, 0.53], [0, 2]),           # fora a 1,70: −9,9% de valor; nada
    ]
    jogos[2]["mk"]["1x2"]["om"] = [2.0, 3.4, 4.5]                             # …mas a melhor casa paga 2,00: 0%
    est, D = banco(jogos)
    ini, fim = A.dia_de(T0), A.dia_de(T0 + 6 * DIA)
    c = AE.simular(D, g, ini, fim)
    ok(c["ops"] == 2 and c["acertos"] == 1, c)
    ok(abs(c["serie"][-1][1] - (CAPITAL + 10 * 1.1 - 10)) < 1e-6, c["serie"][-1])
    ok(c["serie"][0][0] == ini and len(c["serie"]) == 7 and c["retorno"] > 0)
    # a melhor casa paga 2,06 no jogo 3 (2,06 × 0,5 = 3%): com 1% de valor mínimo ele entra; na Bet365, não
    g2 = dict(g, limiar=0.01, casa="melhor")
    jogos[2]["mk"]["1x2"]["om"] = [2.06, 3.4, 4.5]                            # 2,06 × 0,5 = 3%
    est, D = banco(jogos)
    ok(AE.simular(D, g2, ini, fim)["ops"] == 3)
    ok(AE.simular(D, dict(g, limiar=0.01), ini, fim)["ops"] == 2, "a Bet365 não tem o valor do jogo 3")
    # o campeonato e a Europa
    ok(AE.simular(D, dict(g2, liga="eng"), ini, fim)["ops"] == 1)
    ok(AE.simular(D, dict(g2, liga="europa"), ini, fim)["ops"] == 2)
    # a faixa de odd: até 2,05 corta o jogo 1 (2,10)
    ok(AE.simular(D, dict(g, ate=2.2, de=2.05), ini, fim)["ops"] == 1)
    # Kelly: aposta mais com mais valor e cresce com a banca
    k = AE.simular(D, dict(g, stake="kelly", kf=0.25), ini, fim)
    ok(k["ops"] == 2 and k["serie"][-1][1] != c["serie"][-1][1])
    # só gols
    jg = [jogo(1, "eng", [2.1, 3.4, 3.5], [0.45, 0.3, 0.25], [3, 1], ou=([2.0, 1.85], [0.55, 0.45]))]
    est, D = banco(jg)
    ok(AE.simular(D, dict(g, mercados="ou"), ini, fim)["ops"] == 1)
    ok(AE.simular(D, dict(g, mercados="1x2"), ini, fim)["ops"] == 0)
    # a faixa sempre aberta
    r = AE._reparar(dict(g, de=3.0, ate=2.2))
    ok(r["ate"] == 4.0, r)
    ok(AE.Definicao().descrever(g) == "Valor ≥ 3% · odd 1,50 a 4,00 · R$ 10", AE.Definicao().descrever(g))


def teste_controle_bate_com_o_passado():
    """O controle (Valor 3%) faz as mesmas apostas que a conta valor3 do teste no passado, nos mesmos jogos."""
    import falso
    cli = falso.ClientePapelFalso()
    jogos, _info = A.baixar_passado(cli, cli.agora, lambda *a: None, [])
    est = {}
    AE.guardar_jogos(est, jogos, cli.agora)
    D = AE.Dados(est)
    cfg = next(c for c in A.VERSOES if c[0] == "valor3")
    conta = A.Conta(cfg, jogos[0]["inicio"])
    n = sum(len(conta.decidir(j)) for j in jogos if j["liga"] in AE.LIGAS)
    c = AE.simular(D, AE.Definicao().genes_controle(), D.primeiro, A.dia_de(cli.agora))
    ok(c["ops"] == n and n > 0, (c["ops"], n))
    melhor = AE.simular(D, dict(AE.Definicao().genes_controle(), casa="melhor"), D.primeiro, A.dia_de(cli.agora))
    ok(melhor["ops"] >= c["ops"], "a casa melhor nunca aposta menos")


def teste_rodada():
    import falso
    import papel
    pasta = tempfile.mkdtemp(prefix="apostas-ev-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora
        for k in range(12):
            cli.agora = t0 + k * 12 * HORA
            ind = papel.rodada(cli, pasta, cli.agora, formas=["apostas"], exemplo=True, buscar_cdi=False,
                               log=papel.Log(quieto=True))
            ok(ind["formas"]["apostas"]["ok"], ind["formas"]["apostas"])
        d = json.load(open(os.path.join(pasta, "apostas.json")))
        ok(d["nome"] == "Apostas", d["nome"])
        e = d.get("evolucao")
        ok(e and e["formas"][0]["id"] == "apostas" and e["regras"]["moeda"] == "R$", e and e.get("regras"))
        esp = e["formas"][0]["especies"][0]
        ok(esp["id"] == "valor" and esp.get("lab") and esp["lab"]["g"] >= 2 and esp.get("liga"), list(esp))
        ok(not [x for x in d.get("erros") or [] if "evolu" in x], d.get("erros"))
        est = json.load(open(os.path.join(pasta, "estado.json")))["formas"]["apostas"]
        ok(len(est["bancoEv"]["jogos"]) >= AE.MIN_JOGOS, len(est["bancoEv"]["jogos"]))
        ids = [i["id"] for i in esp["liga"]["pop"]]
        ok(len(ids) == len(set(ids)) and "serie" in esp["liga"]["controle"]["aoVivo"], esp["liga"]["controle"])
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    for f in (teste_banco, teste_contas_a_mao, teste_controle_bate_com_o_passado, teste_rodada):
        f()
        print(f"{f.__name__}: ok")
    print("ok")
