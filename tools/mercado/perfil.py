"""O perfil de cada carteira (pedido do Alediov, 02/11/2026, 22h27): robô × humano por sinais com peso, e os
"parâmetros" dela em linguagem simples, tudo pelas execuções dos 30 dias que a escolha já baixa (nenhum pedido a
mais, a não ser as velas de 15 min para "o que o preço fazia antes de ela entrar", as mesmas do teste no histórico).

Sinais de robô (cada um dá s de −1, cara de pessoa, a +1, cara de robô, e um peso; peso 0 quando não há amostra):
  a) "não dorme": a maior pausa do dia (horas UTC quase sem operação, somadas nos 30 dias, em círculo);
  b) tamanhos repetidos: o mesmo tamanho exato ou o mesmo valor em US$ com até 0,5%;
  c) intervalos regulares entre as entradas ou entradas concentradas em minutos fixos (:00, :15, :30, :45);
  d) grade: várias ordens limite na mesma hora com o mesmo espaço entre os preços;
  e) preço redondo nas ordens limite (gente digita 62.300; robô calcula 62.347,5);
  f) velocidade: ordens a menos de 3 s da anterior.
Nota de 0 a 100 = 50 + 50 × média ponderada de s. ≥ 80 robô (quase certo), ≥ 62 robô provável, ≥ 38 não dá para
dizer, abaixo humano provável.
"""
from __future__ import annotations

import bisect
import datetime as dt
import math
import statistics as st
from collections import Counter

from sim import operacoes_da_carteira

MIN = 60_000
HORA = 3_600_000
DIA = 86_400_000
BRT = -3 * HORA  # Brasília, para os horários na tela
VERSAO = 1


# ---------------------------------------------------------------------------------------------- negócios fechados
def negocios(ops):
    """As operações → os negócios: da posição saindo do zero até voltar a zero (ou virar de lado).
    Cada um: {moeda, lado (1 comprado, −1 vendido), t0, t1, entrada, saida, mov (variação a favor, fração), durH, pico
    (maior tamanho em US$), contra (aumentos com o preço contra a entrada média)}. Os que começaram antes da janela
    (sem a abertura) e os ainda abertos ficam de fora."""
    abertos, out = {}, []

    def abrir(o, q):
        abertos[o["moeda"]] = {"moeda": o["moeda"], "lado": 1 if o["pos"] > 0 else -1, "t0": o["t"], "entrada": o["px"],
                               "sz": q, "pico": q * o["px"], "contra": 0, "aumentos": 0, "saidas": []}

    def fechar(n, t, px, q):
        n["saidas"].append((q, px))
        tot = sum(a for a, _ in n["saidas"])
        saida = sum(a * p for a, p in n["saidas"]) / tot if tot else px
        out.append({"moeda": n["moeda"], "lado": n["lado"], "t0": n["t0"], "t1": t, "entrada": n["entrada"], "saida": saida,
                    "mov": (saida / n["entrada"] - 1) * n["lado"], "durH": (t - n["t0"]) / HORA, "pico": n["pico"],
                    "contra": n["contra"], "aumentos": n["aumentos"]})

    for o in ops:
        m, a, p, px = o["moeda"], o.get("antes", 0.0), o["pos"], o["px"]
        n = abertos.get(m)
        if a and (p == 0 or (a > 0) != (p > 0)):  # fecha (e talvez vira de lado)
            if n:
                fechar(n, o["t"], px, abs(a))
                del abertos[m]
            if p:
                abrir(o, abs(p))
        elif abs(p) > abs(a):  # abre ou aumenta
            if not a or not n:
                if not a:
                    abrir(o, abs(p))
                continue
            q = abs(p) - abs(a)
            if (px - n["entrada"]) * n["lado"] < -0.003 * n["entrada"]:
                n["contra"] += 1
            n["aumentos"] += 1
            n["entrada"] = (n["sz"] * n["entrada"] + q * px) / (n["sz"] + q)
            n["sz"] = abs(p)
            n["pico"] = max(n["pico"], abs(p) * px)
        elif n and abs(p) < abs(a):  # reduz
            n["saidas"].append((abs(a) - abs(p), px))
            n["sz"] = abs(p)
    return out


# ---------------------------------------------------------------------------------------------- sinais de robô
def _pausa(horas, total):
    """A maior sequência (em círculo) de horas quase sem operação (menos de 10% da média por hora)."""
    lim = 0.1 * total / 24
    quieta = [horas.get(h, 0) <= lim for h in range(24)]
    if all(quieta):
        return 24
    melhor = atual = 0
    for h in range(48):
        atual = atual + 1 if quieta[h % 24] else 0
        melhor = max(melhor, atual)
    return min(melhor, 24)


def _redondo(px):
    """Preço com até 3 algarismos significativos (62.300, 3,45, 0,123)."""
    if px <= 0:
        return False
    passo = 10 ** (math.floor(math.log10(px)) - 2)
    return abs(px / passo - round(px / passo)) < 1e-6


def _cv(xs):
    if len(xs) < 3:
        return None
    m = st.mean(xs)
    return st.pstdev(xs) / m if m > 0 else None


def sinais(fills, ops, entradas):
    """Os seis sinais: [{id, s, peso, valor, frase}]. `entradas`: as aberturas e os aumentos (t, moeda, q, px)."""
    out = []
    # a) não dorme
    if len(ops) >= 20:
        horas = Counter(dt.datetime.fromtimestamp(o["t"] / 1000, dt.timezone.utc).hour for o in ops)
        p = _pausa(horas, len(ops))
        s = 1.0 if p <= 2 else 0.5 if p <= 3 else 0.0 if p <= 5 else -1.0
        out.append({"id": "dorme", "s": s, "peso": 2.0 if len(ops) >= 40 else 1.0, "valor": p,
                    "frase": f"Opera a qualquer hora: a maior pausa do dia é de {p} h" if p <= 3 else
                    f"Fica cerca de {p} h por dia sem operar, como quem dorme" if p >= 6 else f"Para cerca de {p} h por dia"})
    # b) tamanhos repetidos
    if len(entradas) >= 8:
        qs = [round(q, 6) for _, _, q, _ in entradas]
        exato = Counter(qs).most_common(1)[0][1] / len(qs)
        usd = sorted(q * px for _, _, q, px in entradas)
        perto = max(bisect.bisect_right(usd, u * 1.005) - bisect.bisect_left(usd, u * 0.995) for u in usd) / len(usd)
        r = max(exato, perto)
        s = 1.0 if r >= 0.5 else 0.5 if r >= 0.3 else -0.5 if r <= 0.12 else 0.0
        out.append({"id": "tamanho", "s": s, "peso": 1.5, "valor": round(r, 3),
                    "frase": f"{round(r * 100)}% das entradas têm o mesmo tamanho" if r >= 0.3 else "O tamanho das entradas muda de uma para outra"})
    # c) intervalos regulares ou minutos fixos
    ts = sorted(t for t, *_ in entradas)
    if len(ts) >= 8:
        cv = _cv([b - a for a, b in zip(ts, ts[1:]) if b > a])
        fixo = sum(1 for t in ts if (t // MIN) % 15 in (14, 0, 1)) / len(ts)  # ao acaso, ~20%
        # quem opera uma vez por dia também é "regular": só um relógio de verdade (cv < 0,25) conta forte
        s_cv = 1.0 if cv is not None and cv < 0.25 else 0.3 if cv is not None and cv < 0.4 else -0.3 if cv is not None and cv > 1.2 else 0.0
        s_min = 1.0 if fixo >= 0.6 else 0.5 if fixo >= 0.4 else 0.0
        s = max(s_cv, s_min) if max(s_cv, s_min) > 0 else s_cv
        frase = (f"{round(fixo * 100)}% das entradas caem em minutos fixos (:00, :15, :30, :45)" if s_min >= s_cv and s_min > 0 else
                 "Os intervalos entre as entradas são muito regulares" if s_cv >= 1 else
                 "Os intervalos entre as entradas são um pouco regulares" if s_cv > 0 else
                 "Os intervalos entre as entradas são irregulares, como os de uma pessoa" if s_cv < 0 else
                 "Os intervalos entre as entradas não mostram padrão")
        out.append({"id": "relogio", "s": s, "peso": 1.5, "valor": {"cv": round(cv, 2) if cv is not None else None, "minFixo": round(fixo, 3)}, "frase": frase})
    # d) grade e e) preço redondo (só as execuções com ordem limite)
    pas = [f for f in fills if f.get("crossed") is False]
    if pas:
        janelas = {}
        for f in pas:
            janelas.setdefault((f["coin"], int(f["time"]) // HORA), set()).add(float(f["px"]))
        boas = [sorted(v) for v in janelas.values() if len(v) >= 4]
        if len(boas) >= 3:
            grade = sum(1 for v in boas if (_cv([b - a for a, b in zip(v, v[1:])]) or 9) < 0.25) / len(boas)
            s = 1.0 if grade >= 0.5 else 0.5 if grade >= 0.25 else 0.0
            out.append({"id": "grade", "s": s, "peso": 1.0, "valor": round(grade, 3),
                        "frase": "Ordens limite em grade, com o mesmo espaço entre os preços" if s > 0 else "Sem ordens em grade"})
        if len(pas) >= 10:
            red = sum(1 for f in pas if _redondo(float(f["px"]))) / len(pas)
            s = -1.0 if red >= 0.3 else -0.5 if red >= 0.15 else 0.5 if red <= 0.03 else 0.0
            out.append({"id": "redondo", "s": s, "peso": 1.0, "valor": round(red, 3),
                        "frase": f"{round(red * 100)}% das ordens limite em preço redondo, como faz uma pessoa" if red >= 0.15 else
                        "Ordens limite em preços quebrados, calculados" if red <= 0.03 else "Ordens limite em preços nem redondos nem quebrados"})
    # f) velocidade: o começo de cada ordem (pelo oid) a menos de 3 s do começo da anterior
    inicio = {}
    for f in fills:
        k = f.get("oid") or f.get("hash")
        inicio[k] = min(inicio.get(k, math.inf), int(f["time"]))
    ini = sorted(inicio.values())
    if len(ini) >= 10:
        r = sum(1 for a, b in zip(ini, ini[1:]) if b - a < 3000) / (len(ini) - 1)
        s = 1.0 if r >= 0.2 else 0.5 if r >= 0.08 else -0.3 if r <= 0.01 else 0.0
        out.append({"id": "rapido", "s": s, "peso": 1.0, "valor": round(r, 3),
                    "frase": f"{round(r * 100)}% das ordens saem a menos de 3 s da anterior" if r >= 0.08 else "Ordens espaçadas, no ritmo de uma pessoa"})
    return out


def nota_robo(ss):
    peso = sum(x["peso"] for x in ss)
    if not peso:
        return 50
    return round(50 + 50 * sum(x["s"] * x["peso"] for x in ss) / peso)


def rotulo(nota):
    return ("robô (quase certo)" if nota >= 80 else "robô provável" if nota >= 62 else
            "não dá para dizer" if nota >= 38 else "humano provável")


def selo(nota):
    """O campo antigo (`selo` no resumo): "robo", "humano" ou "incerto"."""
    return "robo" if nota >= 62 else "humano" if nota < 38 else "incerto"


# ---------------------------------------------------------------------------------------------- os "parâmetros"
def _mediana(xs):
    return st.median(xs) if xs else None


def _pct(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]


def horario(ops):
    """Operações por dia da semana (0 = segunda) × hora, no horário de Brasília: 7 listas de 24."""
    g = [[0] * 24 for _ in range(7)]
    for o in ops:
        d = dt.datetime.fromtimestamp((o["t"] + BRT) / 1000, dt.timezone.utc)
        g[d.weekday()][d.hour] += 1
    return g


def _janela_horas(g, cobre=0.85):
    """A menor janela de horas seguidas (Brasília) com pelo menos 85% das operações: (início, tamanho em horas)."""
    por_hora = [sum(g[d][h] for d in range(7)) for h in range(24)]
    tot = sum(por_hora)
    if not tot:
        return None, 24
    for tam in range(1, 25):
        for h in range(24):
            if sum(por_hora[(h + k) % 24] for k in range(tam)) >= cobre * tot:
                return h, tam
    return 0, 24


def antes_da_entrada(trades, preco):
    """A variação do preço nos 15 e 60 min antes de cada entrada, a favor do lado (positivo = já vinha a favor)."""
    m15, m60 = [], []
    for n in trades:
        p0, p15, p60 = preco(n["moeda"], n["t0"]), preco(n["moeda"], n["t0"] - 15 * MIN), preco(n["moeda"], n["t0"] - 60 * MIN)
        if p0 and p15:
            m15.append((p0 / p15 - 1) * n["lado"])
        if p0 and p60:
            m60.append((p0 / p60 - 1) * n["lado"])
    if len(m60) < 5:
        return None
    a15, a60 = _mediana(m15), _mediana(m60)
    rapido = sum(1 for a, b in zip(m15, m60) if abs(b) > 0.002 and abs(a) >= 0.6 * abs(b) and a * b > 0) / len(m60)
    tipo = ("contra" if a60 <= -0.005 else "rompimento" if a15 >= 0.003 and rapido >= 0.5 else "segue" if a60 >= 0.005 else "nenhum")
    return {"m15": round(a15, 4), "m60": round(a60, 4), "tipo": tipo}


def parametros(ops, trades, entradas, eq, preco):
    moedas = Counter(o["moeda"] for o in ops).most_common()
    tot = sum(n for _, n in moedas) or 1
    g = horario(ops)
    h0, tam_h = _janela_horas(g)
    ganhos = [n["mov"] for n in trades if n["mov"] > 0]
    perdas = [-n["mov"] for n in trades if n["mov"] <= 0]
    com_aumento = [n for n in trades if n["aumentos"]]
    contra = sum(1 for n in trades if n["contra"]) / len(trades) if trades else 0
    apostas = []
    for n in trades:
        v = eq(n["t0"])
        if v and v > 0:
            apostas.append(n["pico"] / v)
    compras = sum(1 for n in trades if n["lado"] > 0) / len(trades) if trades else None
    p = {
        "moedas": [[m, round(n / tot, 3)] for m, n in moedas[:4]],
        "horas": {"de": h0, "ate": (h0 + tam_h) % 24 if h0 is not None else None, "tam": tam_h},
        "ganhoMediano": round(_mediana(ganhos), 4) if ganhos else None,
        "perdaMediana": round(_mediana(perdas), 4) if perdas else None,
        "negocios": len(trades),
        "aumentaContra": round(contra, 3), "martingale": bool(trades) and contra >= 0.3 and len(com_aumento) >= 3,
        "apostaPct": round(_mediana(apostas), 3) if apostas else None,
        "alavEfetiva": round(_pct(apostas, 0.9), 2) if apostas else None,
        "compras": round(compras, 3) if compras is not None else None,
        "tempoH": round(_mediana([n["durH"] for n in trades]), 2) if trades else None,
        "antes": antes_da_entrada(trades, preco) if preco else None,
    }
    return p, g


def _num(v, casas=1):
    return f"{v:.{casas}f}".replace(".", ",")


def frase(rot, p, ss):
    """A frase-resumo: "Robô (quase certo): opera BTC e ETH a qualquer hora, sai com cerca de +1,2% ou −0,8%…"."""
    ms = [m for m, f in p["moedas"] if f >= 0.15][:3] or [m for m, _ in p["moedas"][:1]]
    lista = ms[0] if len(ms) == 1 else ", ".join(ms[:-1]) + " e " + ms[-1] if ms else "várias moedas"
    h = p["horas"]
    quando = (f"entre {h['de']}h e {h['ate']}h" if h["de"] is not None and h["tam"] <= 17 else "a qualquer hora")
    partes = [f"opera {lista} {quando}"]
    if p["ganhoMediano"] is not None and p["perdaMediana"] is not None:
        partes.append(f"sai com cerca de +{_num(p['ganhoMediano'] * 100)}% ou −{_num(p['perdaMediana'] * 100)}%")
    tam = next((x for x in ss if x["id"] == "tamanho"), None)
    if tam and tam["s"] >= 1:
        partes.append("sempre do mesmo tamanho")
    a = p.get("antes") or {}
    c = p.get("compras")
    if a.get("tipo") == "contra":
        partes.append("e costuma comprar depois de quedas" if c is not None and c >= 0.7 else
                      "e costuma vender depois de altas" if c is not None and c <= 0.3 else
                      "e costuma entrar contra o movimento (compra depois de quedas, vende depois de altas)")
    elif a.get("tipo") == "segue":
        partes.append("e costuma seguir o movimento (entra depois que o preço já andou a favor)")
    elif a.get("tipo") == "rompimento":
        partes.append("e entra em rompimentos (logo depois de um salto rápido)")
    txt = f"{rot[0].upper()}{rot[1:]}: " + ", ".join(partes[:-1]) + (" " if partes[-1].startswith("e ") else ", ") + partes[-1] if len(partes) > 1 else f"{rot[0].upper()}{rot[1:]}: {partes[0]}"
    txt += "."
    if p.get("martingale"):
        txt += " Aumenta a posição quando o preço vai contra (risco)."
    return txt


def perfil(fills, eq=None, preco=None):
    """O perfil completo de uma carteira pelas execuções (formato `userFills`). `eq(t)`: patrimônio dela no instante;
    `preco(moeda, t)`: o preço (velas de 15 min), para "o que o preço fazia antes"."""
    ops = operacoes_da_carteira(fills)
    for o in ops:  # restos de arredondamento (menos de US$ 1) contam como posição zerada
        if abs(o["pos"]) * o["px"] < 1:
            o["pos"] = 0.0
        if abs(o.get("antes", 0.0)) * o["px"] < 1:
            o["antes"] = 0.0
    ops = [o for o in ops if o["pos"] != o.get("antes", 0.0)]
    trades = negocios(ops)
    entradas = []
    for o in ops:
        a, p = o.get("antes", 0.0), o["pos"]
        if p and (not a or (a > 0) != (p > 0)):
            entradas.append((o["t"], o["moeda"], abs(p), o["px"]))
        elif a and (a > 0) == (p > 0) and abs(p) > abs(a):
            entradas.append((o["t"], o["moeda"], abs(p) - abs(a), o["px"]))
    ss = sinais(fills, ops, entradas)
    nota = nota_robo(ss)
    rot = rotulo(nota)
    p, g = parametros(ops, trades, entradas, eq or (lambda t: None), preco)
    return {"v": VERSAO, "robo": {"nota": nota, "rotulo": rot, "sinais": [{k: x[k] for k in ("id", "s", "peso", "frase")} for x in ss]},
            "parametros": p, "horario": g, "frase": frase(rot, p, ss)}, trades
