"""O robô imitador (pedido do Alediov, 02/11/2026, 22h27: "descobrir os parâmetros dos robôs"). Só para as carteiras
com perfil de robô (perfil.py, nota ≥ 62) e negócios suficientes. Regras simples, ajustadas nos primeiros 20 dias
dos 30 (treino) e conferidas nos 10 últimos (teste), para não se enganar:
  - moedas: as que ela negociou pelo menos 3 vezes no treino;
  - gatilho: o preço andou pelo menos `limiar` na `janela` antes (15, 30, 60 ou 120 min), CONTRA o lado ("compra
    depois de queda") ou A FAVOR ("segue o movimento");
  - lado: os que ela usa (cada um com pelo menos 25% dos negócios);
  - saída: alvo e stop pelas medianas de ganho e perda dela; tempo máximo pelo 3º quartil do tempo dela (até 3 dias).
Escolha da regra: a melhor nota F1 (acertos ÷ entradas reais e ÷ entradas inventadas) no treino, numa grade de
janelas, limiares e dos dois modos. Acerto = mesma moeda e mesmo lado com até 30 min de diferença. No teste: quantas
entradas reais ele acertou, quantas inventou, e uma conta de US$ 1.000 (3×, sem atraso: ele não espera a carteira).
Tudo no papel, sobre as velas de 15 min que o teste no histórico já baixou.
"""
from __future__ import annotations

from sim import Conta, Patrimonio, simular

MIN = 60_000
DIA = 86_400_000
PASSO = 15 * MIN
JANELAS = (1, 2, 4, 8)  # em passos de 15 min: 15, 30, 60, 120 min
LIMIARES = (0.003, 0.005, 0.0075, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04)
TOLERANCIA = 30 * MIN
TREINO_DIAS = 20
MIN_NEGOCIOS = 10


def _mediana(xs):
    s = sorted(xs)
    return (s[len(s) // 2] + s[(len(s) - 1) // 2]) / 2 if s else None


def _sinais(cl, ts, regra, i0, i1):
    """As entradas que a regra faria entre os passos i0 e i1: [(t, moeda, lado, px, t_saida, px_saida)]."""
    out = []
    w, lim, modo = regra["janela"], regra["limiar"], regra["modo"]
    for m in regra["moedas"]:
        c = cl.get(m)
        if not c:
            continue
        i = max(i0, w)
        while i < i1:
            if c[i] is None or c[i - w] is None:
                i += 1
                continue
            mov = c[i] / c[i - w] - 1
            lado = 0
            if modo == "contra":
                lado = 1 if mov <= -lim else -1 if mov >= lim else 0
            else:
                lado = 1 if mov >= lim else -1 if mov <= -lim else 0
            if not lado or lado not in regra["lados"]:
                i += 1
                continue
            entrada = c[i]
            j, fim = i + 1, min(len(c) - 1, i + regra["tempoMax"])
            while j < fim:
                if c[j] is not None:
                    r = (c[j] / entrada - 1) * lado
                    if r >= regra["alvo"] or r <= -regra["stop"]:
                        break
                j += 1
            out.append((ts[i], m, lado, entrada, ts[j], c[j] if c[j] is not None else entrada))
            i = j + 1
    out.sort()
    return out


def _casar(reais, sinais):
    """Quantas entradas reais têm uma do imitador (mesma moeda e lado, até 30 min); cada sinal casa uma vez."""
    usados, ok = set(), 0
    for t, m, lado in reais:
        for k, s in enumerate(sinais):
            if k not in usados and s[1] == m and s[2] == lado and abs(s[0] - t) <= TOLERANCIA:
                usados.add(k)
                ok += 1
                break
    return ok


def _f1(acertos, reais, sinais):
    if not acertos:
        return 0.0
    p, r = acertos / sinais, acertos / reais
    return 2 * p * r / (p + r)


def imitar(trades, parametros, merc, ini, fim, robo_nota):
    """`trades`: os negócios fechados (perfil.negocios); `merc`: o mercado das velas de 15 min; [ini, fim]: a janela."""
    if robo_nota < 62:
        return {"ok": False, "motivo": "humano", "texto": "Não parece robô: não há regra fixa para descobrir."}
    if len(trades) < MIN_NEGOCIOS:
        return {"ok": False, "motivo": "poucos", "texto": f"Só {len(trades)} negócios fechados: poucos para descobrir as regras."}
    corte = ini + TREINO_DIAS * DIA
    treino = [n for n in trades if n["t0"] < corte]
    teste = [n for n in trades if n["t0"] >= corte]
    if len(treino) < 6 or len(teste) < 3:
        return {"ok": False, "motivo": "poucos", "texto": "Poucos negócios no treino ou no teste para conferir as regras."}
    conta = {}
    for n in treino:
        conta[n["moeda"]] = conta.get(n["moeda"], 0) + 1
    moedas = sorted(m for m, k in conta.items() if k >= 3)
    if not moedas:
        return {"ok": False, "motivo": "espalhado", "texto": "Opera muitas moedas, poucas vezes cada: não deu para descobrir as regras."}
    compras = sum(1 for n in treino if n["lado"] > 0) / len(treino)
    lados = [x for x, f in ((1, compras), (-1, 1 - compras)) if f >= 0.25]
    ganhos = [n["mov"] for n in treino if n["mov"] > 0]
    perdas = [-n["mov"] for n in treino if n["mov"] <= 0]
    duracoes = sorted(n["durH"] for n in treino)
    t75 = duracoes[int(0.75 * (len(duracoes) - 1))]
    base = {"moedas": moedas, "lados": lados,
            "alvo": max(0.002, _mediana(ganhos) or 0.01), "stop": max(0.002, _mediana(perdas) or 0.01),
            "tempoMax": int(min(3 * 24 * 4, max(1, round(t75 * 4))))}
    ts = list(range(ini - (ini % PASSO), fim, PASSO))
    cl = {m: [merc.preco(m, t) for t in ts] for m in moedas}
    i_corte = next((i for i, t in enumerate(ts) if t >= corte), len(ts))
    reais_tr = [(n["t0"], n["moeda"], n["lado"]) for n in treino]
    melhor = None
    for modo in ("contra", "segue"):
        for w in JANELAS:
            for lim in LIMIARES:
                r = {**base, "modo": modo, "janela": w, "limiar": lim}
                s = _sinais(cl, ts, r, 0, i_corte)
                if not s:
                    continue
                f = _f1(_casar(reais_tr, s), len(reais_tr), len(s))
                if not melhor or f > melhor[0] + 1e-9 or (abs(f - melhor[0]) < 1e-9 and len(s) < melhor[2]):
                    melhor = (f, r, len(s))
    if not melhor or melhor[0] == 0:
        return {"ok": False, "motivo": "sem_regra", "texto": "Nenhuma regra simples de preço explica as entradas dela: não deu para descobrir as regras desta carteira."}
    f_tr, regra, n_tr = melhor
    sinais_te = _sinais(cl, ts, regra, i_corte, len(ts))
    reais_te = [(n["t0"], n["moeda"], n["lado"]) for n in teste]
    acertos = _casar(reais_te, sinais_te)
    acerto = acertos / len(reais_te)
    precisao = acertos / len(sinais_te) if sinais_te else 0.0
    # a conta do imitador no período de teste: 3×, sem atraso, o tamanho típico dela
    frac = min(1.0, max(0.1, parametros.get("apostaPct") or 0.5))
    ops = []
    for t, m, lado, px, t2, px2 in sinais_te:
        q = lado * frac * 1000 / px
        ops.append({"t": t, "moeda": m, "pos": q, "antes": 0.0, "px": px, "n": 1, "passiva": False})
        ops.append({"t": t2, "moeda": m, "pos": 0.0, "antes": q, "px": px2, "n": 1, "passiva": False})
    ops.sort(key=lambda o: o["t"])
    c = Conta(3, 0, 1000.0, corte - 1)
    simular(ops, Patrimonio([(corte, 1000.0)]), merc, [c], fim)
    r = c.resumo(merc, fim)
    ok = acerto >= 0.4 and precisao >= 0.25
    return {
        "ok": ok, "motivo": None if ok else "acerta_pouco",
        "texto": None if ok else "O imitador acertou pouco: não deu para descobrir as regras desta carteira.",
        "regras": {"moedas": moedas, "modo": regra["modo"], "janelaMin": regra["janela"] * 15, "limiar": regra["limiar"],
                   "lados": lados, "alvo": round(regra["alvo"], 4), "stop": round(regra["stop"], 4),
                   "tempoMaxH": round(regra["tempoMax"] / 4, 1)},
        "treino": {"de": ini, "ate": corte, "f1": round(f_tr, 3), "reais": len(reais_tr), "sinais": n_tr},
        "teste": {"de": corte, "ate": fim, "reais": len(reais_te), "acertadas": acertos, "sinais": len(sinais_te),
                  "inventadas": len(sinais_te) - min(acertos, len(sinais_te)), "acerto": round(acerto, 3),
                  "precisao": round(precisao, 3)},
        "conta": {"retorno": r["retorno"], "piorQueda": r["piorQueda"], "ops": r["ops"], "serie": r["serie"]},
    }


def retorno_entre(serie, de_dia, ate_dia):
    """O retorno de uma série diária [[dia, valor]] entre dois dias (o último valor até cada um); None sem dados."""
    a = [v for d, v in serie if d <= de_dia]
    b = [v for d, v in serie if d <= ate_dia]
    v0 = a[-1] if a else (serie[0][1] if serie and serie[0][0] <= ate_dia else None)
    return round(b[-1] / v0 - 1, 4) if v0 and b else None


def texto_regras(rg):
    """As regras em português: "compra depois de quedas de 2% em 60 min em BTC e ETH; sai com +1,5% ou −1%; até 12 h"."""
    num = lambda v: f"{v * 100:.1f}".replace(".", ",").replace(",0", "")  # noqa: E731
    ms = rg["moedas"]
    lista = ms[0] if len(ms) == 1 else ", ".join(ms[:-1]) + " e " + ms[-1]
    so_compra, so_venda = rg["lados"] == [1], rg["lados"] == [-1]
    if rg["modo"] == "contra":
        o_que = (f"compra depois de quedas de {num(rg['limiar'])}%" if so_compra else
                 f"vende depois de altas de {num(rg['limiar'])}%" if so_venda else
                 f"entra contra movimentos de {num(rg['limiar'])}%")
    else:
        o_que = (f"compra depois de altas de {num(rg['limiar'])}%" if so_compra else
                 f"vende depois de quedas de {num(rg['limiar'])}%" if so_venda else
                 f"segue movimentos de {num(rg['limiar'])}%")
    return (f"{o_que} em {rg['janelaMin']} min, em {lista}; sai com +{num(rg['alvo'])}% ou −{num(rg['stop'])}%, "
            f"ou depois de {str(rg['tempoMaxH']).replace('.', ',').replace(',0', '')} h")
