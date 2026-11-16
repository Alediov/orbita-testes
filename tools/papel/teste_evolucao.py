"""Testes da Evolução (evolucao.py): genes, cruzamento, mutação, notas, a virada da semana da liga (saem, entram,
campeã) e 25 dias de rodadas no mercado de mentira. Uso: python3 tools/papel/teste_evolucao.py"""
from __future__ import annotations

import json
import os
import random
import shutil
import sys
import tempfile
from types import SimpleNamespace

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)

import evolucao as E  # noqa: E402
import falso  # noqa: E402
import papel  # noqa: E402
import robos as R  # noqa: E402
from conta import CAPITAL, DIA, Curva, Eventos  # noqa: E402

ESP = {e["id"]: e for e in E.ESPECIES["robos"]}


def teste_genes():
    rng = random.Random(1)
    for esp in ESP.values():
        for _ in range(300):
            g = E.sortear(rng, esp)
            assert g == E.reparar(esp, g), (esp["id"], g)
            for d in esp["genes"]:
                v = g[d["k"]]
                if d["tipo"] in ("num", "int"):
                    assert d["min"] - 1e-9 <= v <= d["max"] + 1e-9, (d["k"], v)
                elif d["tipo"] == "op":
                    assert v in d["opcoes"], (d["k"], v)
                if not E.ativo(d, g):
                    assert v == d["neutro"], f"{esp['id']}: {d['k']} inativo fora do neutro ({g})"
            if esp["id"] == "tendencia":
                assert g["lenta"] >= 2 * g["rapida"], g
            if g["mercado"] == "spot":
                assert not g.get("ls") and g.get("alav", 1) == 1, g
            # a versão desses genes roda no robô
            R.Robo(E.cfg_de(esp, g, "x", "x"))
    # a regra da tendência: lenta sobe até o dobro da rápida
    t = E.reparar(ESP["tendencia"], {"mercado": "spot", "rapida": 72, "lenta": 48, "stop": 0, "ls": False})
    assert t["lenta"] == 144 and t["rapida"] == 72, t
    # alavancagem e dois lados só no perpétuo
    g = E.reparar(ESP["grade"], {"mercado": "spot", "faixa": 0.1, "degraus": 20, "alav": 3, "recentrar": False,
                                 "saida": False, "saidaQueda": 0.2})
    assert g["alav"] == 1 and g["saidaQueda"] == 0.15, g
    assert E.chave(g) == E.chave(dict(reversed(list(g.items()))))


def teste_controles_e_sementes():
    cfgs = {c["id"]: c for c in R.VERSOES}
    for esp in ESP.values():
        for vid in [esp["controle"]] + esp["sementes"]:
            assert vid in cfgs, vid
        g = E.genes_da_versao(esp, cfgs[esp["controle"]])
        cfg = E.cfg_de(esp, g, "c", "c")
        orig = cfgs[esp["controle"]]
        for k in ("mercado", "faixa", "degraus", "media", "z", "stop", "rapida", "lenta"):
            if k in orig:
                assert cfg[k] == orig[k], (esp["id"], k, cfg[k], orig[k])
    g = E.genes_da_versao(ESP["bandas"], cfgs["rbandastend"])
    assert g["filtro"] == 168
    g = E.genes_da_versao(ESP["grade"], cfgs["gsaida3"])
    assert g["mercado"] == "perp" and g["alav"] == 3 and g["saida"] and g["saidaQueda"] == 0.15
    assert E.descrever(ESP["grade"], g) == "±10%, 20 degraus, perpétuo 3×, sai com −15%", E.descrever(ESP["grade"], g)


def teste_cruzar_e_mutar():
    rng = random.Random(2)
    iguais = 0
    for _ in range(600):
        esp = ESP[rng.choice(list(ESP))]
        pai = {"id": "a", "genes": E.sortear(rng, esp)}
        mae = {"id": "b", "genes": E.sortear(rng, esp)}
        genes, origem = E.cruzar(rng, esp, pai, mae)
        assert genes == E.reparar(esp, genes)
        assert set(origem) == set(genes)
        for k, de in origem.items():
            if not E.ativo(next(d for d in esp["genes"] if d["k"] == k), genes):
                continue  # inativo: fica no neutro
            if de == "pai":
                assert genes[k] == pai["genes"][k], (k, genes, pai)
            elif de == "mae":
                assert genes[k] == mae["genes"][k], (k, genes, mae)
            else:
                assert de == "mut"
        iguais += E.chave(genes) in (E.chave(pai["genes"]), E.chave(mae["genes"]))
        novos, orig2, mudados = E.mutar(rng, esp, pai["genes"], {k: "pai" for k in pai["genes"]}, 2)
        assert 1 <= len(mudados) <= 2
        for k in mudados:
            assert orig2[k] == "mut"
        assert E.chave(novos) != E.chave(pai["genes"]) or all(pai["genes"][k] == novos[k] for k in novos)
    # a filha quase nunca sai igual ao pai ou à mãe (a mutação forçada pode cair no outro); a geração descarta essas
    assert iguais < 30, iguais
    assert E.nome_de(1) == "Ana" and E.nome_de(len(E.NOMES) + 1) == "Ana 2"


def teste_notas():
    P = E.parametros(SimpleNamespace(exemplo=False))

    def curva_de(vals, ops=20):
        c = Curva(inicio=0)
        for i, v in enumerate(vals):
            c.marcar(i * DIA + 1, v)
        c.ops = ops
        return c

    n = 180
    calma = [CAPITAL * (1.0005 ** (i + 1)) for i in range(n)]
    sorte = [CAPITAL * (1.0 if i < 100 else 1.004 ** (i - 99)) for i in range(n)]
    a, b = E.nota_de(curva_de(calma), {}, P), E.nota_de(curva_de(sorte), {}, P)
    assert len(a["jan"]) == 3 and a["nota"] > 0 and a["val"] > 0
    # a mesma subida, mas toda numa janela só, ganha nota menor (a constância conta)
    assert a["nota"] > b["nota"] - 1e-9 or b["jan"][0] == b["jan"][1], (a, b)
    assert E.nota_de(curva_de(calma, ops=2), {}, P)["nota"] is None
    assert E.nota_de(curva_de(calma), {"morta": True}, P)["nota"] == -1
    # pior queda pesa
    queda = [CAPITAL * (0.8 if 20 <= i < 30 else 1.0005 ** (i + 1)) for i in range(n)]
    assert E.nota_de(curva_de(queda), {}, P)["jan"][0] < a["jan"][0]


def _liga_falsa(n=12, k=2):
    """Uma liga de mentira: `n` versões e o controle, com as notas das semanas escritas à mão."""
    ctx = SimpleNamespace(exemplo=True)
    P = E.parametros(ctx)
    P.update(POP_LIGA=n, SAEM_LIGA=3, DO_LAB=1, SEMANAS_COROA=k, SEMANAS_NOTA=4, FILHAS_LIGA=1, MUTANTES_LIGA=1)
    e = {}
    logs = []
    sp = E.Especie("robos", ESP["bandas"], e, random.Random(5), P, Eventos(), logs.append)
    rng = random.Random(6)
    pop = []
    for i in range(n):
        ind = sp.nascer(E.sortear(rng, sp.esp), "novata")
        pop.append(ind)
    agora = 1_790_000_000_000
    aquecer = {"spot": [], "perp": []}
    liga = {"inicio": agora, "semana": R.semana_de(agora), "pop": [sp.comecar_vivo(i, agora, aquecer) for i in pop],
            "semanas": [], "coroadas": [], "campea": None}
    liga["controle"] = sp.comecar_vivo({"id": "controle", "nome": "Controle", "genes": sp.controle_genes(),
                                        "tipo": "controle", "pais": [], "origem": {}}, agora, aquecer)
    e["liga"] = liga
    return sp, liga, agora, aquecer


def _semana(sp, liga, agora, aquecer, retornos, ctrl):
    """Passa uma semana: cada conta termina com o retorno dado (por id) e o controle com `ctrl`."""
    agora += 7 * DIA
    for ind in liga["pop"] + [liga["controle"]]:
        r = ctrl if ind["id"] == "controle" else retornos.get(ind["id"], -0.01)
        c = Curva.de_json(ind["c"])
        c.marcar(agora - 1, ind["marco"]["eq"] * (1 + r))
        ind["c"] = c.para_json()
    sp.fechar_semana(SimpleNamespace(agora=agora), liga, None, aquecer)
    return agora


def teste_liga_semana():
    sp, liga, agora, aquecer = _liga_falsa()
    ids = [i["id"] for i in liga["pop"]]
    boa, fraca = ids[0], ids[1]
    ret = {i: -0.01 - 0.001 * k for k, i in enumerate(ids)}
    ret[boa] = 0.05
    ret[fraca] = -0.2
    agora = _semana(sp, liga, agora, aquecer, ret, 0.0)
    assert len(liga["pop"]) == 12, len(liga["pop"])
    vivos = {i["id"] for i in liga["pop"]}
    assert fraca not in vivos and boa in vivos
    s = liga["semanas"][-1]
    assert len(s["saiu"]) == 3 and len(s["entrou"]) == 3 and s["melhor"] == boa and s["venceram"] == 1
    assert liga["campea"] is None
    # filhas e mutantes da liga têm pais da liga e nascem com a conta zerada
    for i in liga["pop"]:
        if i["id"] not in ids:
            assert i["tipo"] in ("filha", "mutante", "novata") and i["c"]["ultimo"] == CAPITAL
            for p in i["pais"]:
                assert p in sp.e["arvore"]
    # 2ª semana seguida vencendo o controle: campeã
    agora = _semana(sp, liga, agora, aquecer, {boa: 0.03}, 0.0)
    assert liga["campea"] and liga["campea"]["id"] == boa, liga["campea"]
    assert any(e["tipo"] == "coroa" for e in sp.ev.lista)
    # a campeã não sai mesmo indo mal; perde a coroa depois de perder do controle k semanas seguidas
    agora = _semana(sp, liga, agora, aquecer, {boa: -0.3}, 0.0)
    assert boa in {i["id"] for i in liga["pop"]} and liga["campea"]["id"] == boa
    agora = _semana(sp, liga, agora, aquecer, {boa: -0.3}, 0.0)
    assert liga["campea"] is None or liga["campea"]["id"] != boa
    assert liga["coroadas"] and liga["coroadas"][-1]["id"] == boa
    assert len(liga["pop"]) == 12
    sp.podar_arvore()
    for i in liga["pop"]:
        assert i["id"] in sp.e["arvore"]


def teste_nota_semana_curta():
    sp, liga, agora, aquecer = _liga_falsa()
    ind = liga["pop"][0]
    assert sp.nota_semana(ind, agora + 2 * DIA) is None
    c = Curva.de_json(ind["c"])
    c.marcar(agora + 3 * DIA, 900)
    c.marcar(agora + 6 * DIA, 1100)
    ind["c"] = c.para_json()
    nt = sp.nota_semana(ind, agora + 6 * DIA + 1)
    assert abs(nt[1] - 0.1) < 1e-9 and abs(nt[2] - 0.1) < 1e-9 and abs(nt[0] - 0.05) < 1e-9, nt


def conferir_evolucao(d):
    """O formato do evolucao.json (também usado pelo teste_papel.py)."""
    for k in ("v", "forma", "nome", "agora", "frase", "comoFunciona", "avisos", "versoes", "eventos", "formas",
              "regras", "rodada"):
        assert k in d, f"evolucao: falta {k}"
    assert d["versoes"] == [], "evolucao: as versões ficam na aba própria"
    assert len(json.dumps(d)) < 400_000, "evolucao: grande demais"
    for f in d["formas"]:
        for e in f["especies"]:
            assert {"id", "nome", "icone", "genes", "controle", "arvore"} <= set(e), e.keys()
            ks = {g["k"] for g in e["genes"]}
            lab = e.get("lab")
            if lab:
                ids = [i["id"] for i in lab["pop"]]
                assert len(ids) == len(set(ids))
                for i in lab["pop"]:
                    assert set(i["genes"]) == ks and set(i["origem"]) <= ks | set()
                    assert i["id"] in e["arvore"], i["id"]
                notas = [i.get("nota") for i in lab["pop"] if i.get("nota") is not None]
                assert notas == sorted(notas, reverse=True), "evolucao: laboratório fora de ordem"
                assert [h["g"] for h in lab["hist"]] == sorted(h["g"] for h in lab["hist"])
            liga = e.get("liga")
            if liga:
                ids = [i["id"] for i in liga["pop"]]
                assert len(ids) == len(set(ids))
                for i in liga["pop"] + [liga["controle"]]:
                    a = i["aoVivo"]
                    assert {"retorno", "piorQueda", "ops"} <= set(a)
                    if "serie" in a:
                        dias = [x[0] for x in a["serie"]]
                        assert dias == sorted(dias)
                assert "serie" in liga["controle"]["aoVivo"]
                if liga.get("campea"):
                    assert liga["campea"]["id"] in ids


def teste_rodadas():
    pasta = tempfile.mkdtemp(prefix="evolucao-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora
        for k in range(51):
            cli.agora = t0 + k * 12 * falso.HORA
            ind = papel.rodada(cli, pasta, cli.agora, formas=["evolucao"], exemplo=True, buscar_cdi=False,
                               log=papel.Log(quieto=True))
            assert ind["formas"]["evolucao"]["ok"], ind["formas"]["evolucao"]
        with open(os.path.join(pasta, "evolucao.json")) as f:
            d = json.load(f)
        conferir_evolucao(d)
        esp = d["formas"][0]["especies"]
        assert [e["id"] for e in esp] == ["grade", "bandas", "tendencia"]
        for e in esp:
            assert e["lab"]["g"] >= 40, e["lab"]["g"]
            assert len(e["liga"]["pop"]) == 8
            assert len(e["liga"]["semanas"]) >= 2, e["liga"]["semanas"]
            tipos = {i["tipo"] for i in e["lab"]["pop"]}
            assert tipos & {"filha", "mutante", "novata"}, tipos
        assert any(e["liga"].get("campea") for e in esp), "nenhuma campeã em 25 dias"
        # o estado não cresce sem limite
        assert os.path.getsize(os.path.join(pasta, "estado.json")) < 600_000
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def main():
    for nome, f in list(globals().items()):
        if nome.startswith("teste_") and callable(f):
            f()
            print(f"{nome}: ok")
    print("ok")


if __name__ == "__main__":
    main()
