"""Contas de carteira de carteiras e o Consenso (pedidos do Alediov, 09/11/2026; só simulação, saldo fictício).

Carteiras de carteiras (`atualizar`, refeitas do zero a cada rodada, então nada se acumula errado):
- o `banco` do estado guarda, de toda carteira que já foi seguida (também as que saíram), a série diária da cópia no
  jeito padrão (3× e 1 min), o dia em que começou, o dia em que saiu e o selo robô/pessoa de agora;
- uma conta começa com US$ 1.000 e, toda semana (a cada 7 dias desde a 1ª troca), divide o dinheiro em partes iguais
  entre as carteiras da regra; entre as trocas, cada parte anda como a cópia daquela carteira. Carteira que entra no
  meio da semana espera a troca seguinte; a que sai do teste no meio da semana vira dinheiro parado até a troca;
- cada troca paga `CUSTO_LADO` (0,15%) de cada dólar que sai de uma carteira e de cada dólar que entra noutra (taxa de
  0,045% e a diferença de preço ao fechar e abrir as cópias; uma aproximação, porque a cópia de 3× pode ter mais de 1×
  de exposição).
  As regras: **As 5 melhores** (as 5 com o maior % ao mês ao vivo no jeito padrão até o dia da troca, só as com 7 dias
  ou mais), **Só robôs** e **Só pessoas** (todas com o selo robo, ou humano, de agora; o selo é o palpite do perfil e
  quase não muda, mas é o de hoje, não o de cada semana).
- Refeitas pela série das carteiras: na 1ª rodada (09/11/2026) as contas nascem com a história desde o começo do teste
  (02/11/2026), menos as carteiras que saíram antes de existir o banco (elas não têm mais série): um pouco otimista.

Consenso (`consenso_rodada`): uma conta de US$ 1.000, 3× e 1 min, que só fica posicionada numa moeda quando 2 ou mais
carteiras seguidas estão do mesmo lado nela (e mais do que do lado contrário); sai quando isso deixa de valer. Cada
posição do consenso usa `FRACAO_CONSENSO` (30%) do patrimônio da conta (margem de 10% a 3×). As posições das carteiras
são as que as operações delas mostram desde que o consenso começou (a cópia também só entra na próxima operação);
restos abaixo de US$ 10 contam como zero. Usa a mesma conta da cópia (sim.Conta): taxa, deslize, financiamento e
liquidação iguais.
"""
from __future__ import annotations

import bisect
import datetime as dt

from sim import Conta, Patrimonio, dia_de, simular

CAPITAL = 1000.0
CUSTO_LADO = 0.0015
SEMANA = 7
TOP = 5
MIN_DIAS_TOP = 7
FRACAO_CONSENSO = 0.3
MIN_CONSENSO = 2
POS_MIN_US = 10.0
PADRAO = "3x1"
MAX_TROCAS = 12

REGRAS = {
    "top5": {"nome": "As 5 melhores",
             "regra": "Toda semana, as 5 carteiras com o maior % ao mês ao vivo (3× e 1 min, com 7 dias ou mais), em partes iguais."},
    "robos": {"nome": "Só robôs",
              "regra": "Toda semana, todas as carteiras com o selo de robô, em partes iguais (3× e 1 min)."},
    "humanos": {"nome": "Só pessoas",
                "regra": "Toda semana, todas as carteiras com o selo de pessoa, em partes iguais (3× e 1 min)."},
}


def _mais_dias(dia, n):
    return (dt.date.fromisoformat(dia) + dt.timedelta(days=n)).isoformat()


def _dias_entre(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def curto(e):
    return f"{e[:6]}…{e[-4:]}"


# ---------------------------------------------------------------------------------------------- o banco
def atualizar_banco(est, agora, selo_de):
    """A série 3× · 1 min de cada carteira seguida entra no banco; as que saíram ganham `ate`."""
    banco = est.setdefault("banco", {})
    for e, c in est["carteiras"].items():
        b = banco.setdefault(e, {"desde": c["desde"], "serie": {}, "selo": None, "ate": None})
        b["desde"] = min(b.get("desde") or c["desde"], c["desde"])
        serie = ((c.get("resumo") or {}).get(PADRAO) or {}).get("serie") or []
        for d, v in serie:
            b["serie"][d] = v
        b["selo"] = selo_de(c)
        b["ate"] = None
    for e, b in banco.items():
        if e not in est["carteiras"] and b.get("ate") is None:
            b["ate"] = agora
    return banco


class _Serie:
    """O valor da cópia de uma carteira num dia (o último fechamento até ele; US$ 1.000 antes do 1º ponto)."""

    def __init__(self, b):
        self.ini = dia_de(b["desde"])
        self.fim = dia_de(b["ate"]) if b.get("ate") else None
        self.d = sorted(b["serie"])
        self.v = [b["serie"][x] for x in self.d]

    def valor(self, dia):
        if dia < self.ini:
            return None
        i = bisect.bisect_right(self.d, dia) - 1
        return self.v[i] if i >= 0 else CAPITAL

    def ativa(self, dia):
        return dia >= self.ini and (self.fim is None or dia < self.fim)


def _sel_top(series, dia):
    nota = []
    for e, s in series.items():
        if not s.ativa(dia):
            continue
        n = _dias_entre(s.ini, dia)
        v = s.valor(dia)
        if n < MIN_DIAS_TOP or not v or v <= 0:
            continue
        nota.append(((v / CAPITAL) ** (30 / n) - 1, e))
    return [e for _, e in sorted(nota, reverse=True)[:TOP]]


def _sel_selo(alvo):
    def f(series, dia, selos):
        return sorted(e for e, s in series.items() if s.ativa(dia) and selos.get(e) == alvo)
    return f


def agregada(banco, hoje, regra):
    """A conta de uma regra refeita do começo: {serie, retorno, piorQueda, inicio, membros, trocas, custos} ou None."""
    series = {e: _Serie(b) for e, b in banco.items() if b.get("desde")}
    if not series:
        return None
    selos = {e: b.get("selo") for e, b in banco.items()}
    if regra == "top5":
        escolher = lambda dia: _sel_top(series, dia)  # noqa: E731
    else:
        f = _sel_selo("robo" if regra == "robos" else "humano")
        escolher = lambda dia: f(series, dia, selos)  # noqa: E731
    dia = min(s.ini for s in series.values())
    fatias, caixa, inicio, proxima = {}, CAPITAL, None, None
    serie, trocas, custos, pico, queda = [], [], 0.0, CAPITAL, 0.0
    while dia <= hoje:
        total = caixa + sum(f["v0"] * (series[e].valor(dia) or f["base"]) / f["base"] for e, f in fatias.items())
        if (inicio is None and escolher(dia)) or (proxima is not None and dia >= proxima):
            alvo = escolher(dia)
            novos = {e: total / len(alvo) for e in alvo} if alvo else {}
            atuais = {e: f["v0"] * (series[e].valor(dia) or f["base"]) / f["base"] for e, f in fatias.items()}
            mexe = sum(abs(novos.get(e, 0.0) - atuais.get(e, 0.0)) for e in set(novos) | set(atuais))
            custo = max(0.0, mexe) * CUSTO_LADO
            custos += custo
            total -= custo
            if alvo:
                fatias = {e: {"v0": total / len(alvo), "base": series[e].valor(dia) or CAPITAL} for e in alvo}
                caixa = 0.0
            else:
                fatias, caixa = {}, total
            entraram = sorted(set(novos) - set(atuais))
            sairam = sorted(set(atuais) - set(novos))
            if inicio is None or entraram or sairam:
                trocas.append({"dia": dia, "entraram": [curto(e) for e in entraram], "sairam": [curto(e) for e in sairam],
                               "custo": round(custo, 2), "n": len(alvo)})
            if inicio is None:
                inicio = dia
            proxima = _mais_dias(dia, SEMANA)
        if inicio is not None:
            serie.append([dia, round(total, 2)])
            pico = max(pico, total)
            queda = max(queda, 1 - total / pico if pico > 0 else 0)
        dia = _mais_dias(dia, 1)
    if inicio is None or not serie:
        return None
    t0 = int(dt.datetime.fromisoformat(inicio + "T12:00:00+00:00").timestamp() * 1000)
    return {"serie": serie, "retorno": round(serie[-1][1] / CAPITAL - 1, 4), "piorQueda": round(queda, 4),
            "inicio": t0, "membros": sorted(curto(e) for e in fatias), "n": len(fatias), "trocas": trocas[-MAX_TROCAS:],
            "nTrocas": len(trocas), "custos": round(custos, 2), "proximaTroca": proxima, "ops": len(trocas)}


def atualizar(est, agora, selo_de):
    """O banco e as 3 carteiras de carteiras (guardadas em `est["agregadas"]` para o resumo)."""
    banco = atualizar_banco(est, agora, selo_de)
    hoje = dia_de(agora)
    est["agregadas"] = {k: agregada(banco, hoje, k) for k in REGRAS}
    return est["agregadas"]


# ---------------------------------------------------------------------------------------------- consenso
def consenso_conta(est, inicio):
    """A conta do consenso (criada na 1ª rodada, começando em `inicio`)."""
    c = est.get("consenso")
    if not c:
        c = est["consenso"] = {"conta": Conta(3, 60_000, CAPITAL, inicio).para_json(), "lados": {}, "alvo": {},
                               "desde": inicio, "resumo": None}
    return Conta.de_json(c["conta"])


def _alvo(lados, moeda):
    n = {1: 0, -1: 0}
    for por in lados.values():
        s = por.get(moeda, 0)
        if s:
            n[s] += 1
    for s in (1, -1):
        if n[s] >= MIN_CONSENSO and n[s] > n[-s]:
            return s, n[s]
    return 0, max(n.values())


def consenso_rodada(est, conta, novas, merc, ate):
    """As operações novas de todas as carteiras, em ordem, mudam os lados; cada mudança do consenso numa moeda vira uma
    operação da conta (30% do patrimônio do lado do consenso, ou zero)."""
    c = est["consenso"]
    lados, alvo = c["lados"], c["alvo"]
    sinteticas = []

    def mudou(t, m):
        s, _ = _alvo(lados, m)
        antes = alvo.get(m, 0)
        if s != antes:
            sinteticas.append({"t": t, "moeda": m, "pos": FRACAO_CONSENSO * s, "px": 1.0, "antes": FRACAO_CONSENSO * antes,
                               "n": 1, "passiva": False})
            if s:
                alvo[m] = s
            else:
                alvo.pop(m, None)
    # carteiras que saíram: os lados delas somem
    for e in [e for e in lados if e not in est["carteiras"]]:
        moedas = list(lados.pop(e))
        for m in moedas:
            mudou(max(conta.t - 60_000, c["desde"]), m)
    eventos = sorted(((op["t"], e, op) for e, ops in novas.items() for op in ops), key=lambda x: (x[0], x[1]))
    for t, e, op in eventos:
        m = op["moeda"]
        px = merc.preco(m, t) or op.get("px") or 0
        s = 0 if abs(op["pos"]) * px < POS_MIN_US else (1 if op["pos"] > 0 else -1)
        por = lados.setdefault(e, {})
        if s:
            por[m] = s
        else:
            por.pop(m, None)
        mudou(t, m)
    sinteticas.sort(key=lambda o: o["t"])
    simular(sinteticas, Patrimonio([(0, 1.0)]), merc, [conta], ate)
    c["conta"] = conta.para_json()
    r = conta.resumo(merc, ate)
    agora_ = {m: {"lado": "compra" if s > 0 else "venda", "n": _alvo(lados, m)[1]} for m, s in sorted(alvo.items())}
    c["resumo"] = {**r, "consensoAgora": agora_, "carteirasComPosicao": sum(1 for x in lados.values() if x)}
    return c["resumo"]


# ---------------------------------------------------------------------------------------------- resumo
def resumo_agregadas(est, agora, metricas_de):
    out = {}
    for k, info in REGRAS.items():
        a = (est.get("agregadas") or {}).get(k)
        if a:
            out[k] = {"id": k, **info, **a, "metricas": metricas_de(a)}
    c = (est.get("consenso") or {}).get("resumo")
    if c:
        out["consenso"] = {"id": "consenso", "nome": "Consenso",
                           "regra": f"Só entra numa moeda quando {MIN_CONSENSO} ou mais carteiras seguidas estão do mesmo lado "
                                    f"(e mais do que do outro); sai quando isso acaba. {int(FRACAO_CONSENSO * 100)}% da conta "
                                    "por moeda, 3× e 1 min.",
                           **c, "metricas": metricas_de(c)}
    return out
