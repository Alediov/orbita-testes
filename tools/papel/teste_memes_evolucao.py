"""python3 tools/papel/teste_memes_evolucao.py — a Evolução das Memecoins (memes_evolucao.py), sem rede: o banco, as
apostas contra as regras da forma, a espécie e as rodadas no mundo de mentira."""
from __future__ import annotations

import json
import os
import random
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)

import falso  # noqa: E402
import memes as M  # noqa: E402
import memes_evolucao as ME  # noqa: E402
import papel  # noqa: E402
from genetica import chave, reparar  # noqa: E402

HORA, DIA, MIN = falso.HORA, falso.DIA, 60_000
T0 = 1_700_000_000_000 // DIA * DIA
P0 = 30.0 / (M.K_CURVA / 30.0)
SOL, CUSTO = 100.0, 0.0011


def ok(c, msg):
    if not c:
        raise AssertionError(msg)


def ver(vid):
    return next(v for v in M.VERSOES if v[0] == vid)


def inventar(n, sem=3):
    """n tokens inventados (um a cada 7 min): (tok, velas) com sinais e caminhos variados."""
    rng = random.Random(sem)
    out = []
    for i in range(n):
        t0 = T0 + i * 7 * MIN
        tok = {"mint": f"M{i:05d}" + "x" * 30, "t": t0, "p0": P0, "rc": rng.choice(["ok", "ok", "alto", None]),
               "cr": rng.choice([0.0, 0.03, 0.08, 0.2]),
               "sg": {"con": rng.choice([0.1, 0.3, 0.45, 0.7, None]), "bd": rng.choice([0, 0, 1, 3, None]),
                      "rd": rng.choice([True, False, None]), "nv": rng.choice([True, False, None])}}
        p, vs = P0, []
        for m in range(1, 150):
            if rng.random() < 0.3:
                continue
            o = p
            p = max(P0 * 0.01, p * (1 + rng.gauss(0.01, 0.15)))
            vs.append((t0 + m * MIN, o, max(o, p) * (1 + rng.random() * 0.1), min(o, p) * (1 - rng.random() * 0.1), p, 1.0))
        tok["p24"] = p * rng.choice([0.0, 0.2, 1.0, 3.0])
        tok["liq24"] = rng.choice([0, 500, 20000])
        out.append((tok, vs))
    return out


def banco(itens):
    est = {}
    for tok, vs in itens:
        ME.guardar(est, tok, vs, SOL, CUSTO)
    return json.loads(json.dumps(est["bancoEv"]))  # como volta do estado


def teste_bate_com_as_regras():
    """O controle (1º minuto + RugCheck, 2×/−50%/30 min) e o "segura" refeitos pelo banco = as regras da forma."""
    itens = inventar(300)
    D = ME.Dados(banco(itens), 1)
    df = ME.Definicao()
    ctrl = df.genes_controle()
    ok(ctrl == {"entra": "min1", "rc": True, "criador": 1, "donos": 1, "bundle": False, "redes": False, "velha": False,
                "alvo": 2, "stop": 0.5, "tempo": 30}, ctrl)
    ok(ME.descrever(ctrl) == "1º minuto + RugCheck · sai em 2× / −50% / 30 min", ME.descrever(ctrl))
    sem = dict(df.sementes())
    for genes, vid in ((ctrl, "min1rc"), (sem["min1"], "min1"), (sem["min5"], "min5"), (sem["momento"], "momento")):
        a = [M.simular(tok, vs, ver(vid), SOL, CUSTO) for tok, vs in itens]
        b = [ME.aposta(tk, genes) if tk.passa(genes) else None for tk in D.toks]
        for x, y, (tok, vs) in zip(a, b, itens):
            if vid == "momento" and x and x[3] > tok["t"] + ME.JANELA_MIN * MIN:
                ok(y is None, "o momento depois da 1ª hora fica de fora")
                continue
            ok((x is None) == (y is None), f"{vid}: entrou num e não no outro")
            if x:
                ok(abs(x[0] - y[0]) < 0.02, f"{vid}: {x[0]:.4f} × {y[0]:.4f}")
    # o segura: o mesmo da forma, menos o alvo e o stop da 1ª hora (sem alvo nem stop, igual)
    a = [M.simular(tok, vs, ver("segura"), SOL, CUSTO) for tok, vs in itens]
    b = [ME.aposta(tk, sem["segura"]) for tk in D.toks]
    ok(all(abs(x[0] - y[0]) < 0.02 + 1e-3 * abs(x[0]) for x, y in zip(a, b)), "o segura")
    # a conta inteira: a soma das apostas
    dias = sorted({tk.dia for tk in D.toks})
    r = ME.simular(D, ctrl, dias[0], dias[-1])
    soma = sum(x[0] for x in (M.simular(tok, vs, ver("min1rc"), SOL, CUSTO) for tok, vs in itens) if x)
    ok(abs(r["retorno"] * ME.CAPITAL - soma) < 0.5 and r["apostas"] == sum(1 for tok, _ in itens if tok["rc"] == "ok"),
       f"a conta: {r['retorno'] * ME.CAPITAL:.2f} × {soma:.2f}")
    ok(r["montou"] and r["serie"][0][0] == dias[0] and r["ops"] == r["apostas"], r)


def teste_filtros():
    itens = inventar(200, sem=5)
    D = ME.Dados(banco(itens), 1)
    base = reparar(ME.ESP, {**ME.Definicao().genes_controle(), "rc": False})
    n = lambda **k: sum(1 for tk in D.toks if tk.passa(reparar(ME.ESP, {**base, **k})))  # noqa: E731
    tudo = n()
    ok(tudo == 200, "sem filtro, todos")
    ok(n(rc=True) == sum(1 for t, _ in itens if t["rc"] == "ok"), "RugCheck")
    ok(n(criador=0.05) == sum(1 for t, _ in itens if t["cr"] <= 0.05), "criador")
    ok(n(donos=0.35) == sum(1 for t, _ in itens if t["sg"]["con"] is not None and t["sg"]["con"] <= 0.35), "donos")
    ok(n(bundle=True) == sum(1 for t, _ in itens if t["sg"]["bd"] is not None and t["sg"]["bd"] < M.BUNDLE_MIN), "bundle")
    ok(n(redes=True) == sum(1 for t, _ in itens if t["sg"]["rd"] is True), "redes")
    ok(n(velha=True) == sum(1 for t, _ in itens if t["sg"]["nv"] is False), "carteira velha")
    ok(n(rc=True, redes=True) < n(rc=True), "os filtros somam")
    # a saída: sem stop, perde-se mais no pior caso; segurar 24 h com o p24 0 perde tudo
    tk = next(t for t in D.toks if t.tok["p24"] == 0)
    r = ME.aposta(tk, reparar(ME.ESP, {**base, "alvo": 0, "stop": 0, "tempo": 1440}))
    ok(r[1] == "24 h" and r[0] < -9.9, r)
    r5 = [ME.aposta(t, reparar(ME.ESP, {**base, "tempo": 5})) for t in D.toks]
    ok(all(x[1] in ("stop", "alvo", "tempo") for x in r5), "5 min")
    # o banco é limitado
    est = {"bancoEv": [[0] * 15] * (ME.MAX_BANCO + 5)}
    ME.guardar(est, *itens[0], SOL, CUSTO)
    ok(len(est["bancoEv"]) == ME.MAX_BANCO and est["bancoEv"][-1][0] == itens[0][0]["t"], "o teto do banco")
    # as velas guardadas: só a 1ª hora
    r = ME.registro(*itens[0], SOL, CUSTO)
    ok(max(r[-1][0::5]) <= ME.VELAS_MIN, "as 2 primeiras horas")


def teste_genes():
    df = ME.Definicao()
    se = df.sementes()
    ok([v for v, _ in se] == ["min1", "min5", "momento", "segura"], "as sementes")
    ok(len({chave(g) for _, g in se} | {chave(df.genes_controle())}) == 5, "diferentes do controle")
    ok(ME.descrever(dict(se)["segura"]) == "1º minuto · sai em 24 h", ME.descrever(dict(se)["segura"]))
    g = reparar(ME.ESP, {**df.genes_controle(), "entra": "momento", "criador": 0.05, "donos": 0.35, "redes": True,
                         "alvo": 3, "stop": 0.7, "tempo": 60})
    ok(ME.descrever(g) == "aos 60 SOL + RugCheck, com redes, criador ≤ 5%, 10 maiores ≤ 35% · sai em 3× / −30% / 60 min",
       ME.descrever(g))


def rodar(cli, pasta, quando):
    cli.agora = quando
    return papel.rodada(cli, pasta, quando, formas=["memes"], prazo_min=20, exemplo=True, buscar_cdi=False,
                        log=papel.Log(quieto=True))


def teste_rodadas():
    pasta = tempfile.mkdtemp(prefix="memes-ev-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora
        rodar(cli, pasta, t0)
        d = json.load(open(os.path.join(pasta, "memes.json")))
        ok(d.get("evolucao") is None, "sem banco ainda: sem espécie")
        for k in range(1, 22):
            ind = rodar(cli, pasta, t0 + k * 12 * HORA)
            ok(ind["formas"]["memes"]["ok"], ind["formas"]["memes"])
        d = json.load(open(os.path.join(pasta, "memes.json")))
        est = json.load(open(os.path.join(pasta, "estado.json")))["formas"]["memes"]
        ok(not d["rodada"]["erros"], d["rodada"]["erros"])
        ok(len(est["bancoEv"]) > 20 * 40, f"o banco: {len(est['bancoEv'])}")
        ok("Mentira" not in json.dumps(est["bancoEv"]) and "pump" not in json.dumps(est["bancoEv"]),
           "nem nome nem endereço no banco")
        ev = d["evolucao"]
        sp = ev["formas"][0]["especies"][0]
        ok(ev["formas"][0]["id"] == "memes" and sp["id"] == "cacada" and len(sp["genes"]) == 10, "a espécie")
        ok(sp["liga"] and sp["liga"]["controle"]["aoVivo"]["serie"], "a liga")
        ok(sp["lab"] and sp["lab"]["pop"][0].get("nota") is not None, "o laboratório")
        ok(all({"resolvidas", "acertos"} <= set(x["aoVivo"]) for x in sp["liga"]["pop"]), "as apostas de cada versão")
        ok(ev["regras"]["tokens"] == len(est["bancoEv"]), "quantos tokens")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    teste_genes()
    teste_bate_com_as_regras()
    teste_filtros()
    teste_rodadas()
    print("teste_memes_evolucao: ok")
