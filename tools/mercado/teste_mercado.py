"""Testes da cópia no papel (sem rede): python3 tools/mercado/teste_mercado.py"""
import json
import math
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import agregadas as AG  # noqa: E402
import carteiras as K  # noqa: E402
import falso  # noqa: E402
import passado as PS  # noqa: E402
import hl  # noqa: E402
import mercado  # noqa: E402
from sim import (MARGEM_FIXA, STOP_CONTA, TAXA_LIVRO, TAXA_TOMADOR, TEMPO_MAX_MS, Conta, Mercado, Patrimonio, Velas, deslize,  # noqa: E402
                 operacoes_da_carteira, simular)

MIN, HORA, DIA = 60_000, 3_600_000, 86_400_000
T = 1_800_000_000_000  # um instante qualquer, múltiplo de minuto
falhas = 0


def ok(cond, msg):
    global falhas
    if not cond:
        falhas += 1
        print("FALHOU:", msg)


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1, abs(a), abs(b))


def ex(nome):
    with open(os.path.join(AQUI, "exemplos", nome)) as f:
        return json.load(f)


def velas_de(f, ini, fim, passo=MIN):
    """Velas de 1 min com o preço f(t) (abertura em t, fechamento em t + passo)."""
    out, t = [], ini
    while t < fim:
        a, b = f(t), f(t + passo)
        out.append((t, t + passo - 1, a, max(a, b), min(a, b), b))
        t += passo
    return Velas(out)


def op(t, moeda, pos, px, antes=None, passiva=False):
    return {"t": t, "moeda": moeda, "pos": pos, "px": px, "n": 1, "antes": 0.0 if antes is None else antes, "passiva": passiva}


# ------------------------------------------------------------------ formatos (exemplos escritos à mão)
fills = ex("userFills.json")
ops = operacoes_da_carteira(fills)
ok(len(ops) == 2, f"spot (@107) e HIP-3 (xyz:) ficam fora e as 2 execuções de AVAX em 16 s viram uma: {len(ops)}")
ok(perto(ops[0]["pos"], 130.39), f"posição depois do grupo: {ops[0]['pos']}")
ok(perto(ops[0]["px"], (93.53 * 18.435 + 10 * 18.44) / 103.53), "preço médio do grupo")
ok(ops[1]["pos"] == 0, "a venda fecha a posição")
v = Velas.da_api(ex("candleSnapshot.json"))
ok(len(v) == 2 and perto(v.preco(1681923600000), 29295.0), "velas: abertura no começo da vela")
ok(perto(v.preco(1681923600000 + 450_000), 29295 + (29258 - 29295) * 450_000 / 899_999), "velas: interpolação no meio")
ok(v.preco(1681923600000 - 1) is None, "antes da 1ª vela não há preço")
ok(perto(v.preco(1682000000000), 29230.0), "depois da última vela vale o último fechamento")
ok(mercado.valor_conta(ex("clearinghouseState.json")) == 13109.482328, "valor da conta pelo marginSummary")
eq = mercado.eq_do_portfolio(ex("portfolio.json"))
ok(eq[0] == (1739300000000, 8800.0) and eq[-1][1] == 10100.0 and len(eq) == 3, f"portfolio: perpétuos, mês + semana: {eq}")
ml = mercado.max_lev_da_meta(ex("meta.json"))
ok(ml == {"BTC": 40, "ETH": 25, "HPOS": 3}, f"meta: alavancagem máxima sem as retiradas: {ml}")
lb = [K.linha_ranking(r) for r in ex("leaderboard.json")["leaderboardRows"]]
ok(lb[0]["mes"]["pnl"] == 15200.0 and lb[0]["conta"] == 152340.12, "ranking: janelas")
pf = K.pre_filtro(lb)
ok(pf[0][1] is None, f"a 1ª passa no pré-filtro: {pf[0][1]}")
ok(pf[1][1] == "cofre (pelo nome)", f"o HLP sai como cofre: {pf[1][1]}")
ok(ex("userRole.json")["role"] == "user", "userRole")

# ------------------------------------------------------------------ a conta da cópia
plano = Mercado({"BTC": velas_de(lambda t: 50_000.0, T - HORA, T + DIA)}, {}, {"BTC": 40})
c = Conta(3, MIN, 1000.0, T - 1)
c.copiar(plano, op(T, "BTC", 1.0, 50_000.0), 100_000.0)  # a carteira: 1 BTC com US$ 100 mil → 50% do patrimônio
p = c.pos["BTC"]
exe = 50_000 * (1 + deslize("BTC"))
alvo_sz = 0.5 * 1000 / 50_000
ok(perto(p["szi"], alvo_sz), f"mesma fração do patrimônio: {p['szi']} × {alvo_sz}")
ok(perto(p["margem"], alvo_sz * exe / 3), "margem isolada = valor ÷ alavancagem")
ok(perto(c.caixa, 1000 - alvo_sz * exe / 3 - alvo_sz * exe * TAXA_TOMADOR), "caixa depois da margem e da taxa")
ok(perto(c.taxas, alvo_sz * exe * TAXA_TOMADOR), "taxa de quem tira liquidez")
ok(p["desde"] == T + MIN, "a cópia entra com o atraso")
# fecha: resultado = só as taxas e o deslize (preço parado)
c.copiar(plano, op(T + HORA, "BTC", 0.0, 50_000.0), 100_000.0)
ok(not c.pos, "a carteira zerou: a cópia fecha")
custo = alvo_sz * exe * TAXA_TOMADOR + alvo_sz * 50_000 * (1 - deslize("BTC")) * TAXA_TOMADOR + alvo_sz * 50_000 * 2 * deslize("BTC")
ok(perto(c.caixa, 1000 - custo, 1e-9), f"ida e volta com o preço parado custa taxas + deslize: {c.caixa} × {1000 - custo}")
ok(c.fechamentos == 1 and c.acertos == 0 and c.ops == 2, "conta de operações e acertos")

# limite da alavancagem: a carteira com 5× o patrimônio; a conta de 1× só põe o que o caixa paga
c1, c10 = Conta(1, MIN, 1000.0, T - 1), Conta(10, MIN, 1000.0, T - 1)
for cc in (c1, c10):
    cc.copiar(plano, op(T, "BTC", 10.0, 50_000.0), 100_000.0)
n1 = abs(c1.pos["BTC"]["szi"]) * exe
ok(990 < n1 < 1000, f"1×: posição limitada ao caixa: {n1:.2f}")
n10 = abs(c10.pos["BTC"]["szi"]) * exe
ok(perto(n10, 5000 * (1 + deslize("BTC")), 1e-3), f"10×: a exposição da carteira (5×) cabe: {n10:.2f}")
# alavancagem acima da máxima do ativo: vale a do ativo
merc_baixa = Mercado({"HPOS": velas_de(lambda t: 2.0, T - HORA, T + DIA)}, {}, {"HPOS": 3})
c10b = Conta(10, MIN, 1000.0, T - 1)
c10b.copiar(merc_baixa, op(T, "HPOS", 1000.0, 2.0), 10_000.0)  # 20% do patrimônio
ok(c10b.pos["HPOS"]["lev"] == 3, "alavancagem limitada à máxima do ativo")
# virar de lado: fecha e abre do outro lado
cv = Conta(3, MIN, 1000.0, T - 1)
cv.copiar(plano, op(T, "BTC", 1.0, 50_000.0), 100_000.0)
cv.copiar(plano, op(T + HORA, "BTC", -1.0, 50_000.0), 100_000.0)
ok(cv.pos["BTC"]["szi"] < 0 and cv.ops == 3, "virar de lado: fecha e abre vendido")
# ordem mínima de US$ 10
cm = Conta(3, MIN, 1000.0, T - 1)
cm.copiar(plano, op(T, "BTC", 0.01, 50_000.0), 100_000.0)  # 0,5% → US$ 5
ok(not cm.pos, "mudança menor que US$ 10 é ignorada")

# ------------------------------------------------------------------ liquidação
queda = lambda t: 50_000.0 if t < T + 2 * HORA else 50_000.0 * (1 - 0.09 * min(1, (t - T - 2 * HORA) / HORA))  # noqa: E731
mq = Mercado({"BTC": velas_de(queda, T - HORA, T + DIA)}, {}, {"BTC": 20})
cl = Conta(10, MIN, 1000.0, T - 1)
cl.copiar(mq, op(T, "BTC", 2.0, 50_000.0), 100_000.0)  # 100% do patrimônio a 10×: margem ~ US$ 100
pl = dict(cl.pos["BTC"])
liq = Conta.preco_liq(pl)
mmr = 1 / 40
esperado = pl["entrada"] * (1 - 1 / 10) / (1 - mmr)
ok(perto(liq, esperado, 1e-3), f"preço de liquidação (comprado): {liq:.2f} × {esperado:.2f}")
cl.avancar(mq, T + 5 * HORA)
ok(not cl.pos and len(cl.liquidacoes) == 1, "queda de 9% liquida a 10× (manutenção = metade da margem na máxima)")
ok(perto(cl.liquidacoes[0]["perda"], pl["margem"]), "liquidada, perde a margem daquela posição")
ok(perto(cl.caixa, 1000 - pl["margem"] - pl["margem"] * 10 * TAXA_TOMADOR, 1e-3), "e segue com o que sobrou")
ok(T + 2 * HORA <= cl.liquidacoes[0]["em"] <= T + 3 * HORA, "a liquidação acontece durante a queda")
c3 = Conta(3, MIN, 1000.0, T - 1)
c3.copiar(mq, op(T, "BTC", 2.0, 50_000.0), 100_000.0)
c3.avancar(mq, T + 5 * HORA)
ok(c3.pos and not c3.liquidacoes, "a 3× a mesma queda não liquida")
# vendido: preço sobe
alta = lambda t: 50_000.0 if t < T + HORA else 50_000.0 * 1.2  # noqa: E731
ma = Mercado({"BTC": velas_de(alta, T - HORA, T + DIA)}, {}, {"BTC": 20})
cs = Conta(5, MIN, 1000.0, T - 1)
cs.copiar(ma, op(T, "BTC", -2.0, 50_000.0), 100_000.0)
ps = dict(cs.pos["BTC"])
ok(perto(Conta.preco_liq(ps), ps["entrada"] * (1 + 1 / 5) / (1 + 1 / 40), 1e-3), "preço de liquidação (vendido)")
cs.avancar(ma, T + 3 * HORA)
ok(not cs.pos and cs.liquidacoes[0]["lado"] == "venda", "vendido a 5×: alta de 20% liquida")
# a vela da entrada: a mínima de antes da entrada não liquida
pico = lambda t: 40_000.0 if T + 30_000 > t >= T else 50_000.0  # noqa: E731
mp = Mercado({"BTC": Velas([(T, T + MIN - 1, 50_000, 50_000, 40_000, 50_000)] + [(T + k * MIN, T + (k + 1) * MIN - 1, 50_000, 50_000, 50_000, 50_000) for k in range(1, 200)])}, {}, {"BTC": 20})
ce = Conta(10, 0, 1000.0, T - 1)
ce.copiar(mp, op(T + 40_000, "BTC", 2.0, 50_000.0), 100_000.0)
ce.avancar(mp, T + HORA)
ok(ce.pos and not ce.liquidacoes, "na vela da entrada só o fechamento conta")

# ------------------------------------------------------------------ financiamento
taxa = 0.0001
mf = Mercado({"BTC": velas_de(lambda t: 50_000.0, T - HORA, T + DIA)}, {"BTC": [(T + h * HORA + 76, taxa) for h in range(24)]}, {"BTC": 40})
cf = Conta(3, MIN, 1000.0, T - 1)
cf.copiar(mf, op(T, "BTC", 1.0, 50_000.0), 100_000.0)
m0, sz = cf.pos["BTC"]["margem"], cf.pos["BTC"]["szi"]
cf.avancar(mf, T + 10 * HORA + 1000)
pago = 10 * sz * 50_000 * taxa
ok(perto(cf.funding, pago), f"comprado paga a taxa positiva de hora em hora: {cf.funding} × {pago}")
ok(perto(cf.pos["BTC"]["margem"], m0 - pago), "o financiamento sai da margem isolada")
cfv = Conta(3, MIN, 1000.0, T - 1)
cfv.copiar(mf, op(T, "BTC", -1.0, 50_000.0), 100_000.0)
cfv.avancar(mf, T + 10 * HORA + 1000)
ok(cfv.funding < 0, "vendido recebe a taxa positiva")

# ------------------------------------------------------------------ atraso
rampa = lambda t: 50_000.0 * (1 + (t - T) / HORA * 0.01)  # noqa: E731 (+1% por hora)
mr = Mercado({"BTC": velas_de(rampa, T - HORA, T + DIA)}, {}, {"BTC": 40})
ca1, ca5 = Conta(3, MIN, 1000.0, T - 1), Conta(3, 5 * MIN, 1000.0, T - 1)
for cc in (ca1, ca5):
    cc.copiar(mr, op(T, "BTC", 1.0, 50_000.0), 100_000.0)
e1, e5 = ca1.pos["BTC"]["entrada"], ca5.pos["BTC"]["entrada"]
ok(perto(e1, rampa(T + MIN) * (1 + deslize("BTC")), 1e-6), f"atraso de 1 min: preço de t + 1 min: {e1}")
ok(perto(e5, rampa(T + 5 * MIN) * (1 + deslize("BTC")), 1e-6), f"atraso de 5 min: preço de t + 5 min: {e5}")
ok(e5 > e1, "com o preço subindo, o atraso maior compra mais caro")

# ------------------------------------------------------------------ série diária e em pedaços = de uma vez
mfx = Mercado({"BTC": velas_de(lambda t: 50_000.0 * (1 + 0.02 * math.sin((t - T) / (5 * HORA))), T - HORA, T + 4 * DIA)},
              {"BTC": [(T + h * HORA, 0.00002) for h in range(96)]}, {"BTC": 40})
seq = [op(T + k * 3 * HORA, "BTC", (1.5 if k % 2 == 0 else -0.5), 50_000.0) for k in range(25)]
pat = Patrimonio([(T, 100_000.0)])
uma = simular(seq, pat, mfx, [Conta(5, MIN, 1000.0, T - 1)], T + 3 * DIA + 7 * HORA)[0]
partes = Conta(5, MIN, 1000.0, T - 1)
for a, b in ((0, 7), (7, 16), (16, 25)):
    fim = seq[b - 1]["t"] + 5 * MIN if b < 25 else T + 3 * DIA + 7 * HORA
    simular(seq[a:b], pat, mfx, [partes], fim)
    partes = Conta.de_json(json.loads(json.dumps(partes.para_json())))
ok(perto(uma.patrimonio(mfx, T + 3 * DIA + 7 * HORA), partes.patrimonio(mfx, T + 3 * DIA + 7 * HORA), 1e-9), "em várias rodadas (com o estado em JSON) dá o mesmo que de uma vez")
ok(len(uma.serie) == 3 and uma.serie == partes.serie, f"um ponto por dia na série: {uma.serie}")
r = uma.resumo(mfx, T + 3 * DIA + 7 * HORA)
ok(r["serie"][-1][1] == r["patrimonio"] and 0 <= r["piorQueda"] < 1 and r["ops"] == uma.ops, "resumo da conta")

# ------------------------------------------------------------------ variantes: saídas de segurança
cs3 = Conta(3, MIN, 1000.0, T - 1, "s")
cs3.copiar(plano, op(T, "BTC", 1.0, 50_000.0), 100_000.0)
cs3.avancar(plano, T + TEMPO_MAX_MS + HORA)
ok(not cs3.pos and cs3.saidas["tempo"] == 1 and cs3.ultimas[-1]["tipo"] == "tempo", "saída pelo tempo: fecha a posição aberta há mais de 3 dias")
ok(cs3.ultimas[-1]["em"] == T + MIN + TEMPO_MAX_MS, "a saída pelo tempo é no instante dos 3 dias")
cs3.copiar(plano, op(T + TEMPO_MAX_MS + 2 * HORA, "BTC", 1.5, 50_000.0, antes=1.0), 100_000.0)
ok(not cs3.pos, "depois de sair, aumentar a mesma posição não volta a copiar")
cs3.copiar(plano, op(T + TEMPO_MAX_MS + 3 * HORA, "BTC", 0.0, 50_000.0, antes=1.5), 100_000.0)
cs3.copiar(plano, op(T + TEMPO_MAX_MS + 4 * HORA, "BTC", 1.0, 50_000.0, antes=0.0), 100_000.0)
ok("BTC" in cs3.pos and not cs3.bloqueadas, "uma operação nova da carteira libera a moeda")
cn3 = Conta(3, MIN, 1000.0, T - 1)
cn3.copiar(plano, op(T, "BTC", 1.0, 50_000.0), 100_000.0)
cn3.avancar(plano, T + TEMPO_MAX_MS + HORA)
ok(cn3.pos, "a conta normal não sai pelo tempo")
# stop de 5% da conta: 100% da conta comprado a 5× → stop com ~5% de queda, antes da liquidação (~−18%)
queda10 = lambda t: 50_000.0 if t < T + HORA else 50_000.0 * (1 - 0.10 * min(1, (t - T - HORA) / HORA))  # noqa: E731
m10 = Mercado({"BTC": velas_de(queda10, T - HORA, T + DIA)}, {}, {"BTC": 40})
cst = Conta(5, MIN, 1000.0, T - 1, "s")
cst.copiar(m10, op(T, "BTC", 2.0, 50_000.0), 100_000.0)
ps5 = dict(cst.pos["BTC"])
stop = cst.preco_stop(ps5)
ok(perto(abs(ps5["szi"]) * (ps5["entrada"] - stop), STOP_CONTA * ps5["eq0"]), "o stop é a perda de 5% da conta da entrada")
cst.avancar(m10, T + 4 * HORA)
ok(not cst.pos and cst.saidas["stop"] == 1 and not cst.liquidacoes, "a queda de 10% sai pelo stop, sem liquidar")
ok(-0.09 < (cst.caixa / 1000 - 1) < -0.04, f"perde ~5% da conta (com taxa e deslize): {cst.caixa:.2f}")
cnl = Conta(5, MIN, 1000.0, T - 1)
cnl.copiar(m10, op(T, "BTC", 2.0, 50_000.0), 100_000.0)
cnl.avancar(m10, T + 4 * HORA)
ok(cnl.pos and cnl.patrimonio(m10, T + 4 * HORA) < cst.caixa, "a normal fica com a queda inteira")

# ------------------------------------------------------------------ variantes: ordem limite e moedas boas
cl_ = Conta(3, MIN, 1000.0, T - 1, "l")
cl_.copiar(plano, op(T, "BTC", 1.0, 50_000.0, passiva=True), 100_000.0)
pl_ = dict(cl_.pos["BTC"])
ok(perto(pl_["entrada"], 50_000.0) and perto(cl_.taxas, abs(pl_["szi"]) * 50_000 * TAXA_LIVRO), "ordem limite: sem deslize e taxa de 0,015%")
cl_.copiar(plano, op(T + HORA, "BTC", 0.0, 50_000.0, antes=1.0, passiva=False), 100_000.0)
ok(perto(cl_.taxas, abs(pl_["szi"]) * 50_000 * TAXA_LIVRO + abs(pl_["szi"]) * 50_000 * (1 - deslize("BTC")) * TAXA_TOMADOR), "operação a mercado da carteira: taxa cheia")
cnorm = Conta(3, MIN, 1000.0, T - 1)
cnorm.copiar(plano, op(T, "BTC", 1.0, 50_000.0, passiva=True), 100_000.0)
ok(cnorm.pos["BTC"]["entrada"] > 50_000.0, "a conta normal paga deslize mesmo quando a carteira usou ordem limite")
cmb = Conta(3, MIN, 1000.0, T - 1, "m", ["ETH"])
cmb.copiar(plano, op(T, "BTC", 1.0, 50_000.0), 100_000.0)
ok(not cmb.pos, "só as moedas boas: BTC fora da lista não é copiado")
fx = [{"coin": "BTC", "time": T + i, "closedPnl": "10", "fee": "1", "oid": i, "sz": "1", "px": "1", "side": "A", "startPosition": "1"} for i in range(3)]
fx += [{"coin": "ETH", "time": T + 9, "closedPnl": "50", "fee": "1", "oid": 9}]
fx += [{"coin": "SOL", "time": T + i, "closedPnl": "-5", "fee": "1", "oid": 20 + i} for i in range(4)]
fx += [{"coin": "BTC", "time": T + DIA, "closedPnl": "-999", "fee": "1", "oid": 99}]
mb = K.moedas_boas(fx, T + HORA)
ok([m for m, *_ in mb] == ["BTC"], f"moedas boas: mínimo de ordens, resultado positivo e só antes do início: {mb}")
oz = operacoes_da_carteira([{**f, "crossed": False} for f in fills[:2]])
ok(oz[0]["passiva"] and oz[0]["antes"] == 26.86, "operação: passiva pelo volume com ordem limite e a posição de antes")
ok(K.nota_escolha(0.5, 1.0, []) > K.nota_escolha(0.5, 0.0, []) > K.nota_escolha(0.5, 0.0, ["x"]), "nota: ordem limite ajuda, alerta atrapalha")

# ------------------------------------------------------------------ ganho médio ÷ perda média
sobe_desce = lambda t: 50_000.0 if t < T + HORA else 55_000.0 if t < T + 3 * HORA else 50_000.0  # noqa: E731
msd = Mercado({"BTC": velas_de(sobe_desce, T - HORA, T + DIA)}, {}, {"BTC": 40})
gp = Conta(1, MIN, 1000.0, T - 1)
gp.copiar(msd, op(T, "BTC", 1.0, 50_000.0), 100_000.0)
gp.copiar(msd, op(T + HORA, "BTC", 0.0, 55_000.0, antes=1.0), 100_000.0)  # fecha no lucro
gp.copiar(msd, op(T + 2 * HORA, "BTC", 1.0, 55_000.0), 100_000.0)
gp.copiar(msd, op(T + 3 * HORA, "BTC", 0.0, 50_000.0, antes=1.0), 100_000.0)  # fecha no prejuízo
rg = gp.resumo(None, T + 3 * HORA)
ok(rg["acerto"] == 0.5 and rg["gm"] > 40 and rg["pm"] > 40 and rg["gm"] < 60 and rg["pm"] < 60, f"ganho médio e perda média: {rg['gm']}, {rg['pm']}")

# ------------------------------------------------------------------ três jeitos de dimensionar: proporcional, amplificada, fixa
def nocional(c, m="BTC"):
    return abs(c.pos[m]["szi"]) * c.pos[m]["entrada"] if m in c.pos else 0.0


j = {v: Conta(5, MIN, 1000.0, T - 1, v) for v in ("", "a2", "a3", "f")}
for c in j.values():
    c.copiar(plano, op(T, "BTC", 1.0, 50_000.0), 100_000.0)  # a carteira: 50% do patrimônio
ok(perto(nocional(j[""]), 500 * (1 + deslize("BTC")), 1e-6), f"proporcional: 50% da conta ({nocional(j['']):.2f})")
ok(perto(nocional(j["a2"]), 1000 * (1 + deslize("BTC")), 1e-6) and perto(nocional(j["a3"]), 1500 * (1 + deslize("BTC")), 1e-6),
   f"amplificada: × 2 e × 3 a fração dela ({nocional(j['a2']):.0f}, {nocional(j['a3']):.0f})")
ok(perto(j["f"].pos["BTC"]["margem"], MARGEM_FIXA, 1e-6) and perto(nocional(j["f"]), MARGEM_FIXA * 5, 1e-6),
   f"entrada fixa: US$ 50 de margem × 5 ({nocional(j['f']):.2f}), sem olhar a fração dela")
for c in j.values():  # a carteira dobra a posição (1 → 2 BTC, 100% do patrimônio)
    c.copiar(plano, op(T + HORA, "BTC", 2.0, 50_000.0, antes=1.0), 100_000.0)
ok(perto(nocional(j[""]), 1000 * (1 + deslize("BTC")), 1e-3), "proporcional: acompanha a fração nova")
ok(perto(j["f"].pos["BTC"]["margem"], 2 * MARGEM_FIXA, 1e-6), "entrada fixa: o aumento leva mais US$ 50 de margem")
for c in j.values():  # a carteira reduz pela metade
    c.copiar(plano, op(T + 2 * HORA, "BTC", 1.0, 50_000.0, antes=2.0), 100_000.0)
ok(perto(j["f"].pos["BTC"]["margem"], MARGEM_FIXA, 1e-6), "entrada fixa: reduz na mesma proporção que ela")
for c in j.values():  # vira de lado
    c.copiar(plano, op(T + 3 * HORA, "BTC", -1.0, 50_000.0, antes=1.0), 100_000.0)
ok(j["f"].pos["BTC"]["szi"] < 0 and perto(j["f"].pos["BTC"]["margem"], MARGEM_FIXA, 1e-6), "entrada fixa: virada fecha e abre com a margem fixa")
ok(j[""].pos["BTC"]["szi"] < 0 and j["a3"].pos["BTC"]["szi"] < 0, "as outras viram de lado também")
for c in j.values():
    c.copiar(plano, op(T + 4 * HORA, "BTC", 0.0, 50_000.0, antes=-1.0), 100_000.0)
ok(all(not c.pos for c in j.values()), "a carteira fecha: todas fecham")
# teto: a carteira com 6× o patrimônio; a 10×, × 2 e × 3 batem na alavancagem da conta (≈ 10× a conta)
t2, t3 = Conta(10, MIN, 1000.0, T - 1, "a2"), Conta(10, MIN, 1000.0, T - 1, "a3")
for c in (t2, t3):
    c.copiar(plano, op(T, "BTC", 12.0, 50_000.0), 100_000.0)
ok(nocional(t2) < 10_000 and perto(nocional(t2), nocional(t3), 1e-9), f"teto da alavancagem: × 2 e × 3 iguais quando a conta não comporta ({nocional(t2):.0f})")
mlev = Mercado({"HYPE": velas_de(lambda t: 30.0, T - HORA, T + DIA)}, {}, {"HYPE": 3})
fh = Conta(10, MIN, 1000.0, T - 1, "f")
fh.copiar(mlev, op(T, "HYPE", 100.0, 30.0), None)
ok(perto(nocional(fh, "HYPE"), MARGEM_FIXA * 3, 1e-6), "entrada fixa: a alavancagem vai até a máxima do ativo (e não precisa do patrimônio dela)")
pobre = Conta(5, MIN, 40.0, T - 1, "f")
pobre.copiar(plano, op(T, "BTC", 1.0, 50_000.0), 100_000.0)
ok(not pobre.pos and pobre.sem_caixa == 1, "entrada fixa: sem caixa para os US$ 50, não abre")
ok(mercado.partes_chave("10x5a3") == (10, 5, "a3") and mercado.partes_chave("2x1f") == (2, 1, "f") and mercado.partes_chave("3x1") == (3, 1, ""), "chaves das versões")
reg = {"endereco": "0x" + "1" * 40, "conta": 100_000.0, "nome": None, "dia": {"pnl": 0, "roi": 0, "vlm": 0},
       "semana": {"pnl": 1000.0, "roi": 0, "vlm": 0}, "mes": {"pnl": 10_000.0, "roi": 0, "vlm": 5e6}, "total": {"pnl": 1.0, "roi": 0, "vlm": 0}}
aposta = {**reg, "mes": {**reg["mes"], "vlm": 2e5}}
ok(K.nota_ranking(reg) > K.nota_ranking(aposta) and K.pre_filtro([aposta])[0][1] is None, "quem negocia com regularidade (3× a 100×) vem antes, sem recusar as outras")

# ------------------------------------------------------------------ parar de copiar quem afunda (09/11/2026)
queda40 = lambda t: 50_000.0 if t < T + HORA else 50_000.0 * (1 - 0.40 * min(1, (t - T - HORA) / (10 * HORA)))  # noqa: E731
m40 = Mercado({"BTC": velas_de(queda40, T - HORA, T + 2 * DIA)}, {}, {"BTC": 40})
cp = Conta(3, MIN, 1000.0, T - 1, "p25")
cp.copiar(m40, op(T, "BTC", 1.0, 50_000.0), 100_000.0)  # 50% da conta comprada a 3×: −40% no preço ≈ −20% na conta
cp.avancar(m40, T + DIA)
ok(not cp.parada and cp.liquidacoes, "a 25% a perda de ~17% da conta (a garantia liquidada) não para")
cp2 = Conta(3, MIN, 1000.0, T - 1, "p20")
cp2.copiar(m40, op(T, "BTC", 2.0, 50_000.0), 100_000.0)  # 100%: −40% no preço ≈ −40% na conta
cp2.avancar(m40, T + DIA)
ok(cp2.parada and not cp2.pos and 0.2 <= cp2.parada["queda"] < 0.27, f"para ao cair 20% do topo, conferido de hora em hora: {cp2.parada}")
ok(cp2.parada["em"] % HORA == 0 and cp2.ultimas[-1]["tipo"] == "parou", "a saída é numa hora cheia e vira 'parou'")
cp2.copiar(m40, op(T + DIA + HORA, "BTC", 1.0, 30_000.0), 100_000.0)
ok(not cp2.pos, "depois de parar, não copia mais")
rp = cp2.resumo(m40, T + DIA + 2 * HORA)
ok(rp["parou"] and rp["limite"] == 0.2, "o resumo diz que parou e o limite")
ok(Conta.de_json(json.loads(json.dumps(cp2.para_json()))).parada == cp2.parada, "a parada vai e volta pelo JSON")
# enxugar: as contas de 10× e de 5 min (menos o controle) somem; as outras ficam como estão
ee = {"carteiras": {"x": {"contas": {"10x1": 1, "3x1": 2, "5x5": 3, "3x5": 4, "10x5a3": 5}, "resumo": {"10x1": 1, "3x1": 2}, "historico": None}}}
ok(mercado.enxugar(ee) == 4 and ee["carteiras"]["x"]["contas"] == {"3x1": 2, "3x5": 4}, f"enxugar: {ee}")
# carteiras de carteiras: duas carteiras, uma dobra e outra cai pela metade; as 5 melhores (aqui 1) trocam com custo
d0 = int(__import__("datetime").datetime(2026, 11, 1, 15).timestamp() * 1000)
dias = [mercado.dia_de(d0 + i * DIA) for i in range(20)]
banco = {"a": {"desde": d0, "serie": {d: 1000 * (1 + 0.05 * i) for i, d in enumerate(dias)}, "selo": "robo", "ate": None},
         "b": {"desde": d0, "serie": {d: 1000 * (1 - 0.02 * i) for i, d in enumerate(dias)}, "selo": "humano", "ate": None}}
rob = AG.agregada(banco, dias[-1], "robos")
ok(rob["n"] == 1 and rob["trocas"][0]["dia"] == dias[0] and abs(rob["serie"][-1][1] - (1000 - 1.5) * banco["a"]["serie"][dias[-1]] / 1000) < 0.05,
   f"Só robôs segue a carteira robô, com o custo da entrada: {rob['serie'][-1]}")
top = AG.agregada(banco, dias[-1], "top5")
ok(top["trocas"][0]["dia"] == dias[7] and top["n"] == 2, f"As 5 melhores começa com 7 dias de dados: {top['trocas'][0]}")
banco["b"]["ate"] = d0 + 10 * DIA
hum = AG.agregada(banco, dias[-1], "humanos")
ok(hum["serie"][-1][1] == hum["serie"][10][1] or hum["n"] == 0, "a carteira que saiu vira dinheiro parado até a troca")
# o "ranking de T0" pelo histórico desde o começo
pnl = [(d0, 0.0), (d0 + 10 * DIA, 500.0), (d0 + 30 * DIA, 2000.0)]
ok(PS.lucro_em(pnl, d0 - DIA) == 0 and PS.lucro_em(pnl, d0 + 30 * DIA) == 2000 and PS.perto(pnl, d0 + 20 * DIA) is None,
   "lucro em T0: antes de existir é 0; longe de qualquer ponto, nada")
l0 = PS.linha_em("0x" + "a" * 40, None, 20_000.0, pnl, d0 + 30 * DIA)
ok(l0["mes"]["pnl"] == 2000 - 0 and l0["total"]["pnl"] == 2000, f"linha de T0: {l0['mes']}")
ok(PS.media([[["2026-11-02", 1100.0]], [["2026-11-03", 800.0]]], "2026-11-01", "2026-11-03")
   == [["2026-11-01", 1000.0], ["2026-11-02", 1050.0], ["2026-11-03", 950.0]], "média das cópias, US$ 1.000 antes do 1º ponto")

# ------------------------------------------------------------------ escolha e rodadas (mercado de mentira)
mundo = falso.Mundo()
cli = falso.ClienteFalso(mundo)
agora = cli.agora
md_esc = K.medidas(cli.execucoes(falso.endereco(6)), agora)
ok(K.filtro_fino(md_esc, "user") is not None, f"o robô de velocidade sai: {md_esc['opsDia']} por dia, {md_esc['posicaoMediaH']} h")
md_ten = K.medidas(cli.execucoes(falso.endereco(1)), agora)
ok(K.filtro_fino(md_ten, "user") is None, f"o de tendência passa: {md_ten}")
ok(K.filtro_fino(md_ten, "vault") == "é um cofre", "cofre pelo userRole")
pasta = tempfile.mkdtemp()
PS.JANELA = 14  # o mundo de mentira tem 32 dias antes de "agora": 14 + 14 cabem
try:
    r1, e1 = mercado.rodada(cli, pasta, agora, exemplo=True, buscar_cdi=False, log=mercado.Log(quieto=True))
    seg = set(e1["carteiras"])
    ok(seg == {falso.endereco(n) for n in (1, 2, 3, 4, 5)}, f"as 5 boas entram: {sorted(seg)}")
    ok(e1["funil"]["recusas"].get("quase nunca perde") == 1 and "×" in e1["funil"]["exemplos"].get(mercado.curto(falso.endereco(11)), ""),
       f"a que segura as perdas sai, com o motivo legível: {e1['funil'].get('exemplos')}")
    ok(all("3x1m" not in c["historico"] and "3x1s" in c["historico"] for c in e1["carteiras"].values()), "no histórico, sem a variante das moedas boas (seria olhar o futuro)")
    ok(all(c["moedasBoas"] is not None for c in e1["carteiras"].values()), "moedas boas de cada carteira")
    ok(all(c["historico"] and c["historico"]["3x1"]["resolucao"] == "15m" for c in e1["carteiras"].values()), "teste no histórico de todas")
    ok(e1["funil"]["recusas"].get("giro de formador de mercado") == 1 and e1["funil"]["recusas"].get("conta pequena") == 1, f"funil: {e1['funil']}")
    escolhas = []
    for k in range(1, 12):
        cli.agora = agora + k * 2 * HORA
        r2, e2 = mercado.rodada(cli, pasta, cli.agora, exemplo=True, buscar_cdi=False, log=mercado.Log(quieto=True))
        escolhas.append(r2["rodada"]["escolha"])
    ok(all(c["cursor"] == cli.agora - 8 * MIN for c in e2["carteiras"].values()), "o cursor anda até agora − 8 min")
    nops = sum(c["aoVivo"]["3x1"]["ops"] for c in r2["carteiras"])
    ok(nops > 0, f"operações copiadas ao vivo em 22 h: {nops}")
    ok(len(r2["carteiras"][0]["aoVivo"]) == 18 and set(r2["carteiras"][0]["aoVivo"]) == set(mercado.combos()),
       f"18 contas por carteira: {sorted(r2['carteiras'][0]['aoVivo'])}")
    ok(not any(k.startswith("10x") or (k.endswith("x5") is False and "x5" in k and k != "3x5") for k in mercado.combos()),
       f"sem 10× e só o 3× com 5 min: {mercado.combos()}")
    ok(all(k in r2["carteiras"][0]["historico"] for k in ("5x1a2", "5x1a3", "2x1f", "3x1p25", "5x1p25")), "as versões no teste do período da escolha")
    ok(r2["config"]["combos"] == mercado.combos() and r2["config"]["controleAtraso"] == "3x5", "o resumo diz as contas que existem")
    ok(e1["funil"]["semana"] == e1["funil"]["analisadas"], "o funil conta as analisadas na semana")
    q = r1["quarentena"]
    ok(q["n"] == len(e1["recusadas"]) and q["lista"] and all(x["ate"] > agora and x["motivo"] for x in q["lista"])
       and any(x["motivo"].startswith("quase nunca perde: ") for x in q["lista"]), f"quarentena com motivo e prazo no resumo: {q}")
    ok(all(c["selo"] in ("robo", "humano", "incerto") for c in r1["carteiras"]), "selo robô/humano/incerto em cada carteira")
    pf = {c["endereco"]: c["perfil"] for c in r1["carteiras"]}
    ok(pf[falso.endereco(2)]["robo"]["nota"] >= 80 and pf[falso.endereco(2)]["robo"]["rotulo"] == "robô (quase certo)",
       f"robô de regra clara: {pf[falso.endereco(2)]['robo']}")
    ok(all(pf[falso.endereco(n)]["robo"]["nota"] < 38 for n in (1, 4)), f"gente que dorme e digita preço redondo: {[pf[falso.endereco(n)]['robo']['nota'] for n in (1, 4)]}")
    ok(all(38 <= pf[falso.endereco(n)]["robo"]["nota"] < 62 for n in (3, 5)), f"ambíguas: {[pf[falso.endereco(n)]['robo']['nota'] for n in (3, 5)]}")
    im2 = pf[falso.endereco(2)]["imitador"]
    ok(im2["ok"] and im2["teste"]["acerto"] >= 0.7 and im2["regras"]["modo"] == "contra" and im2["regras"]["janelaMin"] == 60
       and "copiaTeste" in im2 and im2["teste"]["de"] - im2["treino"]["de"] == 20 * DIA,
       f"o imitador descobre a regra do robô no treino e acerta no teste: {im2.get('regras')}, {im2.get('teste')}")
    ok(not pf[falso.endereco(1)]["imitador"]["ok"] and "robô" in pf[falso.endereco(1)]["imitador"]["texto"], "gente: sem imitador, com o motivo")
    ok("Robô (quase certo): opera" in pf[falso.endereco(2)]["frase"] and "contra o movimento" in pf[falso.endereco(2)]["frase"], pf[falso.endereco(2)]["frase"])
    ok(sum(sum(l) for l in pf[falso.endereco(2)]["horario"]) > 0 and len(pf[falso.endereco(2)]["horario"]) == 7, "mapa de horário 7 × 24")
    ok(all("gm" in x and "pm" in x for c in r2["carteiras"] for x in c["aoVivo"].values()), "ganho médio e perda média em cada conta")
    mt = r2["carteiras"][0]["aoVivo"]["3x1"].get("metricas") or {}
    ok({"dias", "cdi", "excesso", "venceCdi", "aoMes", "volAno", "sharpe"} <= set(mt) and mt["cdi"] > 0,
       f"métricas comuns (CDI no mesmo período, Sharpe) em cada conta: {mt}")
    # carteira seguida antes das variantes: as contas que faltam começam no cursor, com as moedas boas de antes
    with open(os.path.join(pasta, "estado.json")) as f:
        ev = json.load(f)
    c0 = next(iter(ev["carteiras"].values()))
    c0["contas"] = {k: v for k, v in c0["contas"].items() if k[-1].isdigit()}
    c0.pop("moedasBoas", None)
    with open(os.path.join(pasta, "estado.json"), "w") as f:
        json.dump(ev, f)
    cli.agora += 2 * HORA
    rv, ev2 = mercado.rodada(cli, pasta, cli.agora, exemplo=True, buscar_cdi=False, log=mercado.Log(quieto=True))
    cv = ev2["carteiras"][c0["endereco"]]
    ok(len(cv["contas"]) == 18 and cv["moedasBoas"] is not None and cv["contas"]["3x1s"]["inicio"] == c0["cursor"], "contas novas para as carteiras já seguidas")
    ok(r2["ranking"] == [c["endereco"] for c in r2["carteiras"]], "ranking pelo resultado ao vivo com 3× e 1 min")
    # risco vazio (carteiras de antes da medida): reavaliado aos poucos, só com alerta
    with open(os.path.join(pasta, "estado.json")) as f:
        ev = json.load(f)
    alvo_r = next(iter(ev["carteiras"]))
    ev["carteiras"][alvo_r]["risco"] = None
    ev["carteiras"][alvo_r]["nota"] = None
    with open(os.path.join(pasta, "estado.json"), "w") as f:
        json.dump(ev, f)
    cli.agora += 2 * HORA
    rr, er_ = mercado.rodada(cli, pasta, cli.agora, exemplo=True, buscar_cdi=False, log=mercado.Log(quieto=True))
    cr = er_["carteiras"][alvo_r]
    ok(cr["risco"] and cr["risco"].get("reavaliado") and cr["risco"]["recusa"] is None and cr["nota"] is not None,
       f"risco e nota reavaliados: {cr['risco']}, {cr['nota']}")
    ok(len(r2["referencias"]["btc"]) > 30 and r2["referencias"]["cdi"][-1][1] > 1, "referências: bitcoin e CDI")
    ok(not any(escolhas), "a escolha não se repete no mesmo dia (com menos de 20 seguidas, tenta de novo 1× por dia)")
    # o teste fora da amostra (no mundo de mentira com janela de 14 dias)
    ps = rv["passado"]
    ok(ps and ps["aproximado"] and ps["resultado"] and ps["resultado"]["funil"]["olhadas"] == ps["resultado"]["amostra"],
       f"o teste fora da amostra fica pronto no mundo de mentira: {ps and ps.get('andamento')}")
    rs = ps["resultado"]
    ok(rs["de"] == rs["ate"] - PS.JANELA * DIA and "3x1" in rs["contas"] and rs["contas"]["3x1"]["metricas"] is not None
       and rs["n"] == len(rs["carteiras"]) and rs["n"] >= 1, f"resultado: {rs['n']} escolhidas, {list(rs['contas'])[:4]}")
    ok(rs["contas"]["3x1"]["serie"][0][0] >= mercado.dia_de(rs["de"]), "a cópia só anda depois de T0")
    ok(ps["rodadas"] and ps["rodadas"][-1]["retorno"] == rs["contas"]["3x1"]["retorno"], "rodadas do teste fora da amostra")
    # falha de rede nas velas: a rodada termina e conta o erro
    cli.falhar = {"candleSnapshot"}
    cli.agora += 2 * HORA
    r3, _ = mercado.rodada(cli, pasta, cli.agora, exemplo=True, buscar_cdi=False, log=mercado.Log(quieto=True))
    ok(r3["rodada"]["erros"], "sem velas: a rodada registra o erro e segue")
    cli.falhar = set()
    # uma semana depois: escolhe de novo, e as seguidas há menos de 4 semanas ficam
    cli.agora = agora + 7 * DIA + HORA
    r4, e4 = mercado.rodada(cli, pasta, cli.agora, exemplo=True, buscar_cdi=False, log=mercado.Log(quieto=True))
    ok(r4["rodada"]["escolha"] and set(e4["carteiras"]) == seg, "a escolha da semana mantém as seguidas há menos de 4 semanas")
    cli.agora = agora + 9 * DIA
    r5, e5 = mercado.rodada(cli, pasta, cli.agora, exemplo=True, buscar_cdi=False, log=mercado.Log(quieto=True))
    # carteiras de carteiras e o consenso (09/11/2026)
    ag = r5["agregadas"]
    ok(set(ag) >= {"top5", "robos", "consenso"}, f"as contas novas no resumo: {sorted(ag)}")
    t5 = ag["top5"]
    ok(t5["n"] <= AG.TOP and t5["serie"][0][1] <= 1000 and t5["metricas"] and t5["nTrocas"] >= 1 and t5["trocas"][0]["n"] >= 1,
       f"As 5 melhores: {t5['n']} carteiras, {t5['nTrocas']} trocas")
    ok(ag["robos"]["n"] >= 1 and all(x in t5 for x in ("nome", "regra", "retorno", "piorQueda", "inicio")), "Só robôs")
    co = ag["consenso"]
    ok(co["metricas"] is not None and "consensoAgora" in co and co["inicio"] and isinstance(co["ops"], int), f"Consenso: {co['ops']} operações")
    ok(set(e5["banco"]) >= set(e5["carteiras"]) and all(b["serie"] for b in e5["banco"].values()), "o banco guarda a série de todas")
    tam = os.path.getsize(os.path.join(pasta, "resumo.json")) + os.path.getsize(os.path.join(pasta, "estado.json"))
    ok(tam < 2_000_000, f"arquivos pequenos: {tam // 1024} KB")
    with open(os.path.join(pasta, "resumo.json")) as f:
        txt = f.read()
    ok("token" not in txt.lower() and "secret" not in txt.lower(), "nada de segredo no resumo")
finally:
    shutil.rmtree(pasta, ignore_errors=True)

# ------------------------------------------------------------------ cliente: balde e páginas
dormiu = []
relogio = [0.0]
b = hl.Balde(100, relogio=lambda: relogio[0], dormir=lambda s: (dormiu.append(s), relogio.__setitem__(0, relogio[0] + s)))
for _ in range(5):
    b.gastar(20)
ok(not dormiu, "o balde cheio não espera")
b.gastar(60)
ok(dormiu and perto(dormiu[0], 60 * 60 / 100), f"sem peso, espera o necessário: {dormiu}")
ok(hl.intervalo_para(0, 1, 2 * DIA) == "1m" and hl.intervalo_para(0, 1, 10 * DIA) == "5m" and hl.intervalo_para(0, 1, 40 * DIA) == "15m", "intervalo das velas pelo que ainda existe")


class Paginas(hl.Cliente):
    def __init__(self):
        super().__init__(balde=hl.Balde(10**9))
        self.corpos = []

    def _pedir(self, url, corpo=None, peso=20):
        self.corpos.append(corpo)
        a = corpo["startTime"]
        n = 500 if a == 1000 else 3
        return [{"time": a + i, "tid": a + i, "hash": "h", "coin": "BTC"} for i in range(n)]


pg = Paginas()
fs = pg.execucoes_entre("0x" + "1" * 40, 1000, 5000)
ok(len(fs) == 502 and len(pg.corpos) == 2 and pg.corpos[1]["startTime"] == 1499, f"páginas pelo último horário, sem repetir: {len(fs)}, {len(pg.corpos)}")

print("ok" if not falhas else f"{falhas} falha(s)")
sys.exit(1 if falhas else 0)
