"""O ranking de palpites do clube do Theo (27/11/2026, pedido do Alediov: "automatizarmos os palpites… simular por
variações, como seguindo a odd, seguindo algum outro fator"). Só no papel: nenhum palpite é enviado a lugar nenhum.

A regra do clube (desde novembro de 2026): só o 1X2 dos 90 minutos; palpite até 1 h antes do jogo, sem mudar depois;
acerto +2, erro −1, jogo anulado 0; no mês, mais pontos primeiro, depois o aproveitamento, depois os acertos; os 5
primeiros dividem R$ 1.000 (R$ 500, 250, 125…).

A conta que importa: um palpite com chance p vale, em média, 2p − (1 − p) = 3p − 1 pontos. O favorito de qualquer
jogo tem p ≥ 1/3, então palpitar no favorito nunca tira ponto em média, e quanto mais jogos, mais pontos. As
estratégias abaixo testam isso contra as variações (só os favoritos claros, o empate nos equilibrados, o mandante, os
palpites do próprio Theo) e duas réguas (o sorteio, que fica perto de zero, e o azarão).

- Teste no passado (aproximado): os jogos do banco da Evolução das Apostas (`apostas_evolucao.Dados`: as planilhas
  do football-data, a chance justa pela Pinnacle sem a margem, o placar), mês a mês.
- Ao vivo: cada jogo que o ao vivo das apostas processa (`Vivo.processar`, a OddsPapi) entra com a chance justa da
  Pinnacle 65 min antes do início (o último preço que um robô ainda poderia usar), ou 6 h antes; o placar vem da ESPN
  como nas apostas. Os palpites do Theo (1X2) entram na estratégia `theo`.
"""
from __future__ import annotations

import hashlib

ACERTO, ERRO = 2, -1
MIN_PASSADO = 300           # jogos no banco para mostrar o passado
ANTES_MIN = 65              # o palpite usa o preço de 65 min antes (o limite do clube é 1 h)
GUARDA_DIAS = 120           # o ao vivo guarda os jogos dos últimos 4 meses
PREMIOS = [500, 250, 125, 62.5, 31.25]
DIA = 24 * 3600 * 1000
HORA = 3600 * 1000


def _fav(p):
    return max(range(3), key=lambda i: p[i])


def _sorteio(chave):
    return int(hashlib.md5(str(chave).encode()).hexdigest(), 16) % 3


# (id, nome, frase, grupo, regra(p, chave, theo) → 0 | 1 | 2 | None)
ESTRATEGIAS = [
    ("fav", "Favorito em todos", "Palpita em todos os jogos, sempre no mais provável pela Pinnacle.", "Seguir a odd",
     lambda p, k, t: _fav(p)),
    ("fav40", "Favorito com 40%+", "Só nos jogos em que o favorito tem 40% ou mais.", "Seguir a odd",
     lambda p, k, t: _fav(p) if max(p) >= 0.40 else None),
    ("fav50", "Favorito com 50%+", "Só nos jogos em que o favorito tem 50% ou mais.", "Seguir a odd",
     lambda p, k, t: _fav(p) if max(p) >= 0.50 else None),
    ("fav60", "Favorito com 60%+", "Só nos favoritos claros (60% ou mais): acerta muito, palpita pouco.",
     "Seguir a odd", lambda p, k, t: _fav(p) if max(p) >= 0.60 else None),
    ("empate", "Empate nos equilibrados", "O favorito, menos quando mandante e visitante estão a menos de 10 pontos: aí o empate.",
     "Outros fatores", lambda p, k, t: 1 if abs(p[0] - p[2]) < 0.10 else _fav(p)),
    ("casa", "Sempre o mandante", "Palpita no time da casa em todos os jogos.", "Outros fatores",
     lambda p, k, t: 0),
    ("theo", "Os palpites do Theo", "Só os jogos em que o Theo deu palpite de 1X2, no lado dele (só ao vivo).",
     "Seguir o Theo", lambda p, k, t: t),
    ("theoFav", "Theo e o favorito", "O palpite do Theo quando ele deu um; nos outros jogos, o favorito.",
     "Seguir o Theo", lambda p, k, t: t if t is not None else _fav(p)),
    ("sorteio", "Sorteio", "Um dos três ao acaso: a régua do palpite sem saber nada (fica perto de zero).", "Referência",
     lambda p, k, t: _sorteio(k)),
    ("azarao", "Sempre o azarão", "O menos provável: a régua do lado errado.", "Referência",
     lambda p, k, t: min(range(3), key=lambda i: p[i])),
]
PADRAO = "fav"
SO_AO_VIVO = {"theo", "theoFav"}


def resultado(placar):
    h, a = placar
    return 0 if h > a else 1 if h == a else 2


def _vazio():
    return {"palpites": 0, "acertos": 0, "pontos": 0, "esperado": 0.0}


def _somar(x, sel, r, p):
    x["palpites"] += 1
    x["acertos"] += int(sel == r)
    x["pontos"] += ACERTO if sel == r else ERRO
    x["esperado"] += 3 * p[sel] - 1


def _fechar(x):
    n = x["palpites"]
    return {**x, "esperado": round(x["esperado"], 1), "aproveitamento": round(x["acertos"] / n, 4) if n else None,
            "porPalpite": round(x["pontos"] / n, 3) if n else None}


def contar(jogos):
    """jogos = [(mês "AAAA-MM", liga, p [3], resultado 0|1|2, chave, theo 0|1|2|None)] →
    {estratégia: {"total": …, "meses": {mês: …}, "ligas": {liga: …}}}."""
    out = {}
    for eid, _n, _f, _g, regra in ESTRATEGIAS:
        tot, meses, ligas = _vazio(), {}, {}
        for mes, liga, p, r, chave, theo in jogos:
            sel = regra(p, chave, theo)
            if sel is None:
                continue
            for x in (tot, meses.setdefault(mes, _vazio()), ligas.setdefault(liga, _vazio())):
                _somar(x, sel, r, p)
        out[eid] = {"total": _fechar(tot), "meses": {m: _fechar(v) for m, v in sorted(meses.items())},
                    "ligas": {l: _fechar(v) for l, v in sorted(ligas.items())}}
    return out


def resumo_meses(c):
    """A média, o pior e o melhor mês de pontos (só os meses com pelo menos 20 jogos no banco)."""
    ms = [v for v in c["meses"].values() if v["palpites"] >= 1]
    if not ms:
        return None
    pts = [v["pontos"] for v in ms]
    return {"meses": len(ms), "media": round(sum(pts) / len(pts), 1), "pior": min(pts), "melhor": max(pts),
            "palpitesPorMes": round(sum(v["palpites"] for v in ms) / len(ms))}


# ------------------------------------------------------------------------------------------------ o passado
def passado(D):
    """O teste no passado pelo banco da Evolução das Apostas (`apostas_evolucao.Dados`), aproximado: a chance justa
    das planilhas, não a de 65 min antes. Só os meses com 20+ jogos contam na média."""
    jogos = []
    meses = {}
    for d, liga, placar, mk in D.jogos:
        meses[d[:7]] = meses.get(d[:7], 0) + 1
    ok = {m for m, n in meses.items() if n >= 20}
    for d, liga, placar, mk in D.jogos:
        if d[:7] in ok:
            jogos.append((d[:7], liga, mk["1x2"][1], resultado(placar), f"{d}|{liga}|{placar}", None))
    if len(jogos) < MIN_PASSADO:
        return None
    return {"jogos": len(jogos), "de": D.jogos[0][0], "ate": D.jogos[-1][0], "contas": contar(jogos)}


# ------------------------------------------------------------------------------------------------ ao vivo
def chance_antes(pin, ini, sem_margem, preco_em):
    """A chance justa do 1X2 da Pinnacle 65 min antes do início (ou 6 h antes), ou None."""
    ph = (pin or {}).get("1x2")
    if not ph:
        return None
    for t in (ini - ANTES_MIN * 60 * 1000, ini - 6 * HORA):
        po = [preco_em(h, t) for h in ph]
        if all(po):
            return sem_margem(po)
    return None


def anotar(C, f, p, theo):
    """Guarda o jogo `f` (o do ao vivo das apostas) com a chance `p` e o lado do Theo (0/1/2 ou None)."""
    if not p:
        return
    C.setdefault("jogos", {})[str(f["id"])] = {"i": f["i"], "l": f["l"], "c": f["c"], "f": f["f"],
                                              "p": [round(x, 4) for x in p], "t": theo, "r": None}


def liquidar(C, placar, agora):
    """Põe o resultado nos jogos que acabaram (`placar(jogo)` → [gols, gols] ou None) e esquece os velhos."""
    js = C.setdefault("jogos", {})
    for k, j in list(js.items()):
        if j.get("r") is None and j["i"] + 3 * HORA <= agora:
            pl = placar(k, j)
            if pl:
                j["r"] = resultado(pl)
                j["pl"] = list(pl)
            elif j["i"] < agora - 10 * DIA:
                j["r"] = "anulado"
        if j["i"] < agora - GUARDA_DIAS * DIA:
            del js[k]


def ao_vivo(C, dia_de):
    jogos = [(dia_de(j["i"])[:7], j["l"], j["p"], j["r"], k, j.get("t"))
             for k, j in (C.get("jogos") or {}).items() if isinstance(j.get("r"), int)]
    pend = sum(1 for j in (C.get("jogos") or {}).values() if j.get("r") is None)
    return {"jogos": len(jogos), "esperando": pend, "contas": contar(jogos)}


# ------------------------------------------------------------------------------------------------ saída
def resumo(C, D, dia_de, nome_liga):
    """O bloco `concurso` do apostas.json."""
    try:
        pas = passado(D) if D is not None and getattr(D, "jogos", None) else None
    except Exception:  # noqa: BLE001
        pas = None
    viv = ao_vivo(C, dia_de)
    ests = []
    for eid, nome, frase, grupo, _r in ESTRATEGIAS:
        e = {"id": eid, "nome": nome, "frase": frase, "grupo": grupo, "soAoVivo": eid in SO_AO_VIVO,
             "aoVivo": viv["contas"][eid]}
        if pas and eid not in SO_AO_VIVO:
            e["passado"] = {**pas["contas"][eid], "porMes": resumo_meses(pas["contas"][eid])}
        ests.append(e)
    return {
        "frase": "Palpites de 1X2 no papel, contados como no ranking do clube do Theo: acerto +2, erro −1.",
        "regra": {"acerto": ACERTO, "erro": ERRO, "ate": "1 h antes do jogo", "mercado": "1X2 dos 90 minutos",
                  "desempate": ["aproveitamento", "acertos"], "premios": PREMIOS},
        "conta": "Em média, um palpite com chance p vale 3p − 1 pontos: o favorito (p ≥ 1/3) nunca perde em média, "
                 "então quanto mais jogos, mais pontos.",
        "padrao": PADRAO, "estrategias": ests,
        "passado": ({k: pas[k] for k in ("jogos", "de", "ate")} if pas else None),
        "aoVivo": {"jogos": viv["jogos"], "esperando": viv["esperando"]},
        "ligas": {l: nome_liga.get(l, l) for l in sorted({l for e in ests for l in
                                                        ((e.get("passado") or {}).get("ligas") or {}) | e["aoVivo"]["ligas"]})},
        "avisos": ["Só no papel: nenhum palpite é enviado ao clube.",
                   "O passado é aproximado (a chance das planilhas, não a de 1 h antes) e conta todos os jogos dos "
                   "campeonatos do banco; o clube pode liberar outros. Os pontos por palpite servem para qualquer lista."],
    }


__all__ = ["ESTRATEGIAS", "contar", "passado", "anotar", "liquidar", "ao_vivo", "resumo", "chance_antes", "resultado"]
