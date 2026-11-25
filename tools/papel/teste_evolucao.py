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
            if esp["id"] == "indicadores" and g["regra"] == "mmalvo":
                assert g["lenta"] >= g["rapida"] + 4 and g["stop"], g
            if g.get("mercado", "spot") == "spot":
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


def teste_migrar_moeda():
    est = {"esp": {"robos.grade": {"lab": {"pop": [{"genes": {"mercado": "spot", "faixa": 0.1}, "origem": {"faixa": "pai"}}]},
                                   "liga": {"controle": {"genes": {"mercado": "perp"}}, "pop": []}}},
           "hb": {"spot": {"1": [1, 1, 1]}, "perp": {}}}
    E.migrar_moeda(est)
    ind = est["esp"]["robos.grade"]["lab"]["pop"][0]
    assert ind["genes"]["moeda"] == "BTC" and ind["origem"]["moeda"] == "base"
    assert est["esp"]["robos.grade"]["liga"]["controle"]["genes"]["moeda"] == "BTC"
    assert set(est["hb"]) == {"spot|BTC", "perp|BTC"} and est["hb"]["spot|BTC"] == {"1": [1, 1, 1]}
    assert E.onde({"mercado": "perp", "moeda": "SOL"}) == "perp|SOL" and E.onde({}) == "spot|BTC"
    assert E.coin_de("perp|SOL", {}) == "SOL" and E.coin_de("spot|ETH", {"ETH": "@151"}) == "@151"


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
    # indicadores: cada semente volta igual (a regra e os números dela) e se descreve
    for vid in [ESP["indicadores"]["controle"]] + ESP["indicadores"]["sementes"]:
        g = E.genes_da_versao(ESP["indicadores"], cfgs[vid])
        cfg, orig = E.cfg_de(ESP["indicadores"], g, "c", "c"), cfgs[vid]
        for k, v in orig.items():
            if k not in ("id", "nome", "frase", "grupo", "risco"):
                assert cfg.get(k) == v, (vid, k, cfg.get(k), v)
        assert E.descrever(ESP["indicadores"], g)
    # a moeda e o DCA (25/11/2026): cada semente volta igual nos números que importam
    for esp in ESP.values():
        for vid in [esp["controle"]] + esp["sementes"]:
            orig = cfgs[vid]
            cfg = E.cfg_de(esp, E.genes_da_versao(esp, orig), "c", "c")
            for k in ("moeda", "tipo", "mercado", "alav", "partes", "cada", "queda", "caixa", "passo", "seguranca",
                      "mult", "alvo", "faixa", "degraus", "regra"):
                if k in orig:
                    assert cfg.get(k) == orig[k], (esp["id"], vid, k, cfg.get(k), orig[k])
    g = E.genes_da_versao(ESP["dca"], cfgs["dcaqueda"])
    assert g["tipo"] == "queda" and g["cada"] == 7 and g["queda"] == 0.05 and g["passo"] == 0.02  # o passo fica neutro
    assert E.descrever(ESP["dca"], g) == "20 compras, só com 5% de queda, no máximo 1 a cada 7 dias", E.descrever(ESP["dca"], g)
    g = E.genes_da_versao(ESP["dca"], cfgs["dcam3"])
    assert g["mercado"] == "perp" and g["alav"] == 3 and g["partes"] == 20 and not g["caixa"]
    assert E.descrever(ESP["grade"], E.genes_da_versao(ESP["grade"], cfgs["geth10"])).startswith("ETH · ")
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
    assert [E.romano(k) for k in (2, 3, 4, 9, 14, 40)] == ["II", "III", "IV", "IX", "XIV", "XL"]
    assert len(set(E.NOMES)) == len(E.NOMES) >= 300 and len(set(E.SOBRENOMES)) == len(E.SOBRENOMES) >= 200
    assert not set(E.NOMES) & set(E.SOBRENOMES)


def teste_nomes_de_familia():
    """A novata funda a família; a filha leva o sobrenome da mãe e o do pai; a mutante fica com os de quem veio; nome
    repetido ganha II, III."""
    P = E.parametros(SimpleNamespace(exemplo=True))
    sp = E.Especie("robos", ESP["grade"], {}, random.Random(9), P, Eventos(), lambda x: None)
    rng = random.Random(10)
    a = sp.nascer(E.sortear(rng, sp.esp), "novata")
    b = sp.nascer(E.sortear(rng, sp.esp), "semente")
    assert len(a["sob"]) == 1 and len(b["sob"]) == 1 and a["sob"] != b["sob"], (a["nome"], b["nome"])
    assert a["nome"].split()[0] in E.NOMES and a["nome"].endswith(" " + a["sob"][0])
    f = sp.nascer(E.sortear(rng, sp.esp), "filha", (a["id"], b["id"]))
    assert f["sob"] == [b["sob"][0], a["sob"][0]], f["nome"]            # mãe e depois o pai
    assert f["nome"].endswith(f" {b['sob'][0]} {a['sob'][0]}")
    n = sp.nascer(E.sortear(rng, sp.esp), "filha", (f["id"], b["id"]))
    assert n["sob"] == [b["sob"][0], a["sob"][0]], n["nome"]            # o último de cada um
    irmas = sp.nascer(E.sortear(rng, sp.esp), "filha", (a["id"], a["id"]))
    assert irmas["sob"] == a["sob"]                                     # os dois da mesma família: um sobrenome só
    m = sp.nascer(E.sortear(rng, sp.esp), "mutante", (f["id"],))
    assert m["sob"] == f["sob"] and m["nome"] != f["nome"]
    assert sp.e["arvore"][f["id"]]["s"] == f["sob"]
    # fundadoras não repetem sobrenome enquanto houver livre, e ninguém repete o nome
    nomes = {x["nome"] for x in (a, b, f, n, irmas, m)}
    sobs = {a["sob"][0], b["sob"][0]}
    for _ in range(150):
        x = sp.nascer(E.sortear(rng, sp.esp), "novata")
        assert x["nome"] not in nomes and x["sob"][0] not in sobs, x["nome"]
        nomes.add(x["nome"])
        sobs.add(x["sob"][0])
    # com um prenome só, o repetido vira II, III
    orig = E.NOMES
    E.NOMES = ["Ana"]
    try:
        x1 = sp.nascer(E.sortear(rng, sp.esp), "mutante", (a["id"],))
        x2 = sp.nascer(E.sortear(rng, sp.esp), "mutante", (a["id"],))
        x3 = sp.nascer(E.sortear(rng, sp.esp), "mutante", (a["id"],))
    finally:
        E.NOMES = orig
    base = f"Ana {a['sob'][0]}"
    esperado = [base, f"{base} II", f"{base} III"] if a["nome"] != base else [f"{base} II", f"{base} III", f"{base} IV"]
    assert [x1["nome"], x2["nome"], x3["nome"]] == esperado, (x1["nome"], x2["nome"], x3["nome"])


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


def teste_sem_clones():
    """Duas versões com o mesmo resultado (genes que não mudam nada): só a mais velha fica no laboratório."""
    P = E.parametros(SimpleNamespace(exemplo=True))
    sp = E.Especie("robos", ESP["grade"], {}, random.Random(3), P, Eventos(), lambda x: None)
    lab = {"g": 0, "pop": [], "hist": [], "dia": "2026-11-16", "hoje": 0}
    rng = random.Random(4)
    for k in range(P["POP"]):
        ind = sp.nascer(E.sortear(rng, sp.esp), "novata", g=0)
        ind.update(nota=0.01 * (k % 3), val=0.0, ops=10, ret=0.01 * (k % 3), queda=0.1, idade=k)
        lab["pop"].append(ind)
    falsos = {"spot": None, "perp": None}
    orig = E.avaliar
    E.avaliar = lambda esp, genes, dados, P: {"nota": -0.5, "val": -0.5, "ops": 10, "ret": -0.1, "queda": 0.3}
    try:
        sp.geracao(lab, falsos, {})
    finally:
        E.avaliar = orig
    ficaram = [i for i in lab["pop"] if i.get("nota") != -0.5]
    assert len(ficaram) == 3, [(i["nome"], i["nota"]) for i in ficaram]          # uma de cada resultado
    assert all(i["idade"] >= 5 for i in ficaram), [i["idade"] for i in ficaram]   # a mais velha de cada
    assert sum(1 for x in lab["saiu"] if x.get("clone")) == P["POP"] - 3
    assert len(lab["pop"]) == P["POP"]
    assert len(E.sem_clones(lab["pop"])) <= len(lab["pop"])


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
        assert [e["id"] for e in esp] == ["grade", "bandas", "tendencia", "indicadores", "dca"]
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
