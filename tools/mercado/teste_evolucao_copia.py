"""python3 tools/mercado/teste_evolucao_copia.py — a Evolução do copy trading (evolucao_copia.py), sem rede: um banco de
séries inventado (4 carteiras, 2 jeitos, 60 dias) e a evolução rodando dia a dia."""
import copy
import datetime as dt
import json
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
sys.path.append(os.path.join(AQUI, "..", "papel"))
import evolucao_copia as EV  # noqa: E402

DIA = 86_400_000
T0 = int(dt.datetime(2026, 11, 2, 12, tzinfo=dt.timezone.utc).timestamp() * 1000)  # uma segunda
dia = lambda n: (dt.date(2026, 11, 2) + dt.timedelta(days=n)).isoformat()  # noqa: E731
N = 60
JEITOS = ["3x1", "5x1", "3x1p20"]


def ok(c, msg):
    if not c:
        raise AssertionError(msg)


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol


def mundo():
    """A sobe 1% ao dia; B cai 2% ao dia; C sobe 3% e cai 2,5% alternando; D sai do teste no dia 20 (subia 0,5%)."""
    passo = {"A": lambda n: 1.01, "B": lambda n: 0.98, "C": lambda n: 1.03 if n % 2 else 0.975, "D": lambda n: 1.005}
    banco, bv = {}, {}
    for e, f in passo.items():
        v, s3, s5 = 1000.0, {}, {}
        v5 = 1000.0
        for n in range(1, N + 1):
            if e == "D" and n > 20:
                break
            v *= f(n)
            v5 *= 1 + (f(n) - 1) * 5 / 3
            s3[dia(n)], s5[dia(n)] = round(v, 2), round(v5, 2)
        banco[e] = {"desde": T0, "ate": T0 + 20 * DIA if e == "D" else None, "selo": "robo" if e in "AC" else "humano", "serie": s3}
        bv[e] = {"3x1": s3, "5x1": s5, "3x1p20": dict(s3)}
    return {"banco": banco, "bancoEv": bv, "carteiras": {}}


est = mundo()
esp = EV.especie(JEITOS, "3x1")
D = EV.Dados(est, "3x1")
ctrl = EV.genes_controle(esp)
ok(ctrl == {"jeito": "3x1", "quem": "top", "n": 5, "minDias": 7, "olhar": 0, "troca": 7, "largar": 0}, f"o controle: {ctrl}")
ok(EV.descrever(esp, ctrl) == "3x1 · as 5 melhores · troca a cada 7 d", EV.descrever(esp, ctrl))

# ---- dias e semanas
w = EV.semana_de(T0)
ok(EV.segunda_de(w) == "2026-11-02" and EV.semana_do_dia("2026-11-02") == w and EV.semana_do_dia("2026-11-08") == w
   and EV.semana_do_dia("2026-11-09") == w + 1, "a semana vai de segunda a domingo")
ok(EV.semana_de(T0 + 7 * DIA - 10 * 3_600_000) == w and EV.semana_de(T0 + 7 * DIA) == w + 1, "a virada é na segunda (Brasília)")

# ---- quem a regra escolhe
g = lambda **k: EV.reparar(esp, {**ctrl, **k})  # noqa: E731
ok(EV.escolher(D, ctrl, dia(5)) == [], "com menos de 7 dias ninguém entra nas melhores")
ok(EV.escolher(D, g(n=2), dia(10)) == ["A", "D"], f"as 2 melhores no dia 10: {EV.escolher(D, g(n=2), dia(10))}")
ok(EV.escolher(D, g(n=3), dia(30)) == ["A", "C", "B"], "a D saiu do teste no dia 20")
ok(EV.escolher(D, g(quem="robos"), dia(3)) == ["A", "C"] and EV.escolher(D, g(quem="humanos"), dia(30)) == ["B"], "os selos")
ok(EV.escolher(D, g(quem="todas"), dia(3)) == ["A", "B", "C", "D"], "todas")
ok(g(quem="robos")["n"] == 5 and g(quem="robos", n=2)["n"] == 5, "fora das melhores, o gene das quantas fica no neutro")

# ---- a conta
c = EV.simular(D, g(n=1), dia(0), dia(40))
ok(len(c["serie"]) == 41 and c["serie"][0] == [dia(0), 1000.0] and c["serie"][6][1] == 1000.0, "antes de a regra achar alguém, o dinheiro fica parado")
ok(c["montou"] and c["ops"] == 1 and c["membros"] == ["A"], f"a melhor é sempre a A: {c['ops']} {c['membros']}")
esperado = 1000 * (1 - EV.CUSTO_LADO) * 1.01 ** (40 - 7)
ok(abs(c["serie"][-1][1] - esperado) < 0.6, f"a A desde o dia 7, menos o custo de entrar: {c['serie'][-1][1]} × {esperado:.2f}")
ok(abs(c["custos"] - 1.5) < 0.01, f"o custo de entrar: {c['custos']}")
# largar: a B cai 2% ao dia; com 10% de limite, a fatia vira dinheiro parado e volta na troca seguinte
so_b = g(quem="humanos", largar=0.1, troca=14)
c = EV.simular(D, so_b, dia(21), dia(34))
vals = [v for _, v in c["serie"]]
ok(c["largadas"] == 1 and vals[-1] == vals[-2] == vals[-3] and vals[-1] > 1000 * 0.98 ** 13, f"largou a B e ficou parado: {c['largadas']} {vals[-4:]}")
ok(vals[-1] < 900 * 1.001, f"largou depois de cair 10% do topo: {vals[-1]}")
sem = EV.simular(D, g(quem="humanos", troca=14), dia(21), dia(34))
ok(sem["largadas"] == 0 and sem["serie"][-1][1] < vals[-1], "sem largar, a conta segue a B até o fim")
# a carteira que sai do teste vira dinheiro parado até a troca
c = EV.simular(D, g(quem="todas", troca=14), dia(14), dia(27))
v19, v20, v27 = c["serie"][5][1], c["serie"][6][1], c["serie"][13][1]
ok(c["ops"] == 1 and len(c["membros"]) == 3, f"a D saiu no dia 20: {c['membros']}")
# jeitos: o 5× anda mais que o 3×
a3, a5 = EV.simular(D, g(n=1), dia(8), dia(40)), EV.simular(D, g(n=1, jeito="5x1"), dia(8), dia(40))
ok(a5["retorno"] > a3["retorno"] > 0, "o jeito de copiar muda a conta")
# uma carteira sem série naquele jeito não é escolhida
est2 = mundo(); del est2["bancoEv"]["A"]["5x1"]  # noqa: E702
ok("A" not in EV.escolher(EV.Dados(est2, "3x1"), g(quem="todas", jeito="5x1"), dia(10)), "sem série no jeito, fica de fora")
est3 = mundo(); est3["bancoEv"] = {}  # noqa: E702
ok(EV.escolher(EV.Dados(est3, "3x1"), g(quem="todas"), dia(10)) == ["A", "B", "C", "D"], "o jeito padrão vem do banco das agregadas")

# ---- notas
ok(EV.nota_semana([[dia(n), 1000 + n] for n in range(0, 14)], w, 5) is not None and EV.nota_semana([[dia(n), 1000] for n in range(4, 7)], w, 5) is None, "a nota da semana pede 5 dias")
ns = EV.nota_semana([[dia(n), 1000 * 1.01 ** n] for n in range(-2, 9)], w, 5)
ok(perto(ns[1], 1.01 ** 7 - 1, 1e-4) and ns[2] == 0 and ns[0] == ns[1], f"a semana de segunda a domingo, a partir do valor de domingo: {ns}")
nl = EV.nota_lab(EV.simular(D, g(n=1), dia(0), dia(N)))
ok(nl and len(nl["jan"]) == 3 and nl["val"] > 0 and nl["nota"] > 0, f"a nota do laboratório: {nl}")
ok(EV.nota_lab(EV.simular(D, g(minDias=21, n=1), dia(0), dia(10))) is None, "quem nunca montou a carteira fica sem nota")

# ---- a evolução dia a dia (números pequenos, como no mercado de mentira)
def rodar_dias(est, de, ate, vezes=1):
    ev = None
    for n in range(de, ate + 1):
        for k in range(vezes):
            ev, DD = EV.rodar(est, T0 + n * DIA + k * 7_200_000, JEITOS, "3x1", exemplo=True, log=lambda *a: None)
    return ev, DD


est = mundo()
ev, DD = rodar_dias(est, 3, 3)
e = est["evolucao"]
P = ev.P
ok(e["liga"] and len(e["liga"]["pop"]) == P["POP_LIGA"] and e["liga"]["controle"]["genes"] == ctrl, "a liga começa na 1ª rodada, com o controle")
ok(len({EV.chave(i["genes"]) for i in e["liga"]["pop"]} | {EV.chave(ctrl)}) == P["POP_LIGA"] + 1, "sem versões repetidas na liga")
ok([i.get("de") for i in e["liga"]["pop"][:3]] == ["robos", "humanos", "todas"], "as sementes: as outras carteiras de carteiras")
ok(e.get("labEspera") == {"faltam": P["MIN_DIAS_LAB"] - 3, "dias": 3, "precisa": P["MIN_DIAS_LAB"]} and not e["lab"], f"o laboratório espera: {e.get('labEspera')}")
ok(len({i["nome"] for i in e["liga"]["pop"]}) == P["POP_LIGA"], "nomes diferentes")
antes = copy.deepcopy(e["liga"]["pop"])
ev, DD = rodar_dias(est, 4, 6, vezes=3)
ok([i["id"] for i in est["evolucao"]["liga"]["pop"]] == [i["id"] for i in antes] and not est["evolucao"]["liga"]["semanas"], "no meio da semana nada muda")
# a virada da 1ª semana (a liga começou na quinta: 4 dias, ainda sem nota para sair alguém)
ev, DD = rodar_dias(est, 7, 8)
liga = est["evolucao"]["liga"]
ok(len(liga["semanas"]) == 1 and liga["semanas"][0]["de"] == "2026-11-02" and liga["semana"] == w + 1, f"a 1ª virada: {liga['semanas']}")
# o laboratório começou com MIN_DIAS_LAB dias (o dia 8) e roda uma vez por dia, mesmo com várias rodadas no dia
ok(est["evolucao"]["lab"]["g"] == P["GERACOES_DIA"], "o laboratório começa no dia em que o banco tem os dias que precisa")
ev, DD = rodar_dias(est, 9, 9, vezes=2)
lab = est["evolucao"]["lab"]
ok(lab and lab["g"] == 2 * P["GERACOES_DIA"] and len(lab["pop"]) == P["POP"] and "labEspera" not in est["evolucao"], f"o laboratório: {lab and lab['g']}")
ok(lab["pop"][0]["nota"] is not None and lab["controle"]["nota"] is not None and len(lab["hist"]) == 2 * P["GERACOES_DIA"], "as notas do laboratório")
ok(len({EV.chave(i["genes"]) for i in lab["pop"]}) == P["POP"], "sem versões repetidas no laboratório")
# semanas seguintes: saem as piores, entram outras, a população não muda de tamanho
ev, DD = rodar_dias(est, 10, 45)
e = est["evolucao"]
liga, lab = e["liga"], e["lab"]
ok(len(liga["pop"]) == P["POP_LIGA"] and len(liga["semanas"]) == 6, f"6 viradas: {len(liga['semanas'])}")
cheias = [s for s in liga["semanas"] if s["saiu"]]
ok(cheias and all(len(s["saiu"]) == len(s["entrou"]) <= P["SAEM_LIGA"] for s in cheias), f"sai e entra o mesmo tanto: {[(len(s['saiu']), len(s['entrou'])) for s in liga['semanas']]}")
ok(lab["g"] == P["GERACOES_DIA"] * 38 and lab["dia"] == dia(45), f"o laboratório roda todo dia: {lab['g']}")
ok(any(x["fonte"] == "laboratório" for s in cheias for x in s["entrou"]) or not ev.aprovadas(), "as aprovadas do laboratório entram na liga")
ok(lab["pop"][0]["nota"] >= lab["controle"]["nota"], "a melhor do laboratório é pelo menos o controle")
ok(all(str(i["semana"]).isdigit() and isinstance(i["notas"], dict) for i in liga["pop"]), "o estado da liga")
ok(len({i["nome"] for i in liga["pop"]}) == len(liga["pop"]), "nomes diferentes na liga")
for i in liga["pop"] + lab["pop"]:
    ok(i["id"] in e["arvore"] and all(p in e["arvore"] for p in i["pais"]), f"a árvore tem {i['id']} e os pais")
    ok(i["genes"] == EV.reparar(ev.esp, i["genes"]), "genes no domínio")
filhas = [i for i in lab["pop"] if i["tipo"] == "filha"]
ok(filhas and all(len(i["pais"]) == 2 and set(i["origem"].values()) <= {"pai", "mae", "mut"} for i in filhas), "as filhas têm pai, mãe e a origem de cada gene")
# a coroa: vencer o controle SEMANAS_COROA semanas seguidas
ok(EV.Evolucao.venceu({"notas": {"5": [.02], "6": [.03]}}, {"notas": {"5": [.01], "6": [.01]}}, [6, 5]) == 1
   and EV.Evolucao.venceu({"notas": {"5": [.0], "6": [.0]}}, {"notas": {"5": [.01], "6": [.01]}}, [6, 5]) == -1
   and EV.Evolucao.venceu({"notas": {"6": [.03]}}, {"notas": {"5": [.01], "6": [.01]}}, [6, 5]) is None, "venceu o controle")
if liga["campea"]:
    ok(any(i["id"] == liga["campea"]["id"] for i in liga["pop"]), "a campeã continua na liga")

# ---- a saída (o formato do evolucao.json dos Robôs)
r = EV.resumo(ev, DD, T0 + 45 * DIA)
json.dumps(r)
sp = r["formas"][0]["especies"][0]
ok(r["formas"][0]["id"] == "copy" and sp["id"] == "carteiras" and [x["k"] for x in sp["genes"]] == ["jeito", "quem", "n", "minDias", "olhar", "troca", "largar"], "a espécie")
ok(sp["controle"]["descricao"] and sp["liga"]["controle"]["aoVivo"]["serie"] and sp["liga"]["semanaDe"] == EV.segunda_de(liga["semana"]), "o controle da liga")
ok(len(sp["liga"]["pop"]) == P["POP_LIGA"] and sum(1 for x in sp["liga"]["pop"] if "serie" in x["aoVivo"]) >= min(EV.COM_SERIE, P["POP_LIGA"]), "as séries das melhores")
ok(all(set(x["aoVivo"]) >= {"retorno", "piorQueda", "ops", "inicio", "membros"} and x["descricao"] and isinstance(x["notas"], list) for x in sp["liga"]["pop"]), "cada versão da liga")
ms = [x["media"] for x in sp["liga"]["pop"] if x["media"] is not None]
ok(ms == sorted(ms, reverse=True), "a liga vem da melhor média para a pior")
ok(len(sp["lab"]["pop"]) == P["POP"] and sp["lab"]["hist"] and all("descricao" in x for x in sp["lab"]["pop"]), "o laboratório na saída")
ok(r["eventos"] and r["eventos"][0]["em"] >= r["eventos"][-1]["em"] and r["regras"]["popLiga"] == P["POP_LIGA"], "eventos e regras")
ok(all(not k.startswith("_") for k in sp) and "sob" not in json.dumps(sp["liga"]["pop"][0]), "nada do estado interno na saída")

# ---- o mesmo mundo dá o mesmo resultado (a sorte depende só da semente guardada, da semana e do dia)
e1 = mundo(); e2 = mundo()  # noqa: E702
for x in (e1, e2):
    x["evolucao"] = {"v": EV.VERSAO, "contador": 0, "arvore": {}, "lab": None, "liga": None, "eventos": [], "semente": 7}
    rodar_dias(x, 3, 25)
ok(json.dumps(e1["evolucao"], sort_keys=True) == json.dumps(e2["evolucao"], sort_keys=True), "repetir a rodada não muda o resultado")
# versão nova do estado recomeça; sem carteiras, nada acontece
e4 = {"banco": {}, "carteiras": {}, "evolucao": {"v": 0}}
ev4, D4 = EV.rodar(e4, T0, JEITOS, "3x1", exemplo=True, log=lambda *a: None)
ok(e4["evolucao"]["v"] == EV.VERSAO and e4["evolucao"]["liga"] is None and EV.resumo(ev4, D4, T0)["formas"][0]["especies"][0].get("liga") is None, "sem carteiras, sem liga")
# o banco: as séries de todos os jeitos das carteiras seguidas
e5 = {"carteiras": {"X": {"resumo": {"3x1": {"serie": [["2026-11-02", 1001.0]]}, "5x1": {"serie": [["2026-11-02", 1002.0]]}}}}, "bancoEv": {"X": {"3x1": {"2026-11-01": 1000.0}}}}
ok(EV.atualizar_banco(e5) == {"X": {"3x1": {"2026-11-01": 1000.0, "2026-11-02": 1001.0}, "5x1": {"2026-11-02": 1002.0}}}, "o banco junta os dias")
print("teste_evolucao_copia: ok")
