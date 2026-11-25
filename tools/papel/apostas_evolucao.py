"""Evolução das Apostas, NO PAPEL (pedido do Alediov, 25/11/2026: "Anote todas em um plano e faremos uma por uma …
já começamos com as Apostas"; plano em docs/plano-evolucao.md do repositório do app).

A espécie é o **Valor** (apostar quando a odd da casa paga mais do que a chance justa, a das odds da Pinnacle sem a
margem, como as versões `valor3`…): toda versão começa com R$ 1.000 fictícios. Os genes (o que evolui):

- `limiar`: o valor mínimo (1% a 12%);
- `de` e `ate`: a faixa de odd (de 1,20 a 3,00; até 2,20 a 10,00; sempre `ate` > `de`);
- `mercados`: o 1X2, o mais/menos de 2,5 gols ou os dois (no máximo uma seleção por mercado e por jogo, a de mais valor);
- `stake`: aposta fixa (`aposta`: 0,5%, 1% ou 2% da banca inicial) ou Kelly (`kf`: a fração do critério, de 0,1 a
  0,5, no máximo 2% da banca de agora);
- `casa`: a Bet365 (a das versões de sempre no passado) ou a melhor odd entre as casas comuns da planilha (Bet365,
  bwin, William Hill, 1xBet, Interwetten e VC Bet: como quem tem conta em todas e aposta onde paga mais; no
  Brasileirão a planilha só tem a Bet365);
- `liga`: todas, só a Europa ou um campeonato.

Não gasta pedido nenhum da OddsPapi: as contas saem de um **banco** dos jogos das planilhas gratuitas do
football-data (as mesmas do teste no passado da forma: 3 temporadas das 5 ligas grandes da Europa e o Brasileirão,
que só tem as odds de fechamento), guardado compacto no estado (`est["bancoEv"]`: de cada jogo o início, o campeonato,
o placar, as odds da Bet365, a melhor comum, as chances justas e o mais/menos de 2,5). Semeado quando a forma baixa as
3 temporadas (o teste no passado, 1×/semana) e posto em dia uma vez por dia pela temporada de agora (sem chave). As
planilhas chegam com uns 2 dias de atraso: a liga anda conforme os jogos novos entram nelas.

No laboratório, uma versão com menos de MIN_APOSTAS apostas no período fica sem nota (as que quase não apostam não
dizem nada). Cada aposta é decidida e liquidada no dia do jogo, pelo placar final (o mesmo `ganhou` da forma). O controle é o
`valor3` REFEITO aqui (não bate centavo a centavo com a conta valor3 do teste no passado, que marca a curva jogo a jogo).

O laboratório e a liga são os do motor comum (`evolucao_series.py`). Estado em `est["evolucao"]` (o da forma); saída
em `apostas.json` → `evolucao` (FORMATO.md, "Evolução"). Teste: `teste_apostas_evolucao.py`.
"""
from __future__ import annotations

import datetime as dt
import zlib

import apostas as A
import evolucao_series as ES
from conta import CAPITAL, DIA, HORA, cdi_ano_da_serie, dia_de, metricas
from genetica import reparar

VERSAO = 2               # 2 (25/11/2026, no mesmo dia): o mínimo de apostas para ter nota; recomeçou
CDI_PADRAO = 0.149
MIN_JOGOS = 300            # menos que isso no banco: sem a espécie ainda
# no laboratório, uma versão com menos apostas que isso fica sem nota: na 1ª rodada real (25/11/2026) as melhores eram
# as que quase não apostavam (1 a 3 apostas em 3 temporadas, nota ~0), o que não diz nada; o Valor 3% fez 29
MIN_APOSTAS = 20
BANCO_DIAS = 1100          # os jogos guardados (as 3 temporadas)
ATUALIZAR = DIA            # o banco é posto em dia pela temporada de agora uma vez por dia
LIGAS = [k for k, *_ in A.LIGAS if k != "lib"]

FRASE = ("Versões da aposta de valor que evoluem: toda semana as piores regras saem, as melhores se cruzam e, às vezes, "
         "um gene muda. Só no papel, em R$ fictícios.")
AVISOS = ["Só no papel, com saldo fictício: nenhuma conta em casa de apostas, nenhuma aposta.",
          "As contas saem das planilhas gratuitas do football-data (a Bet365 no lugar da Betano; no Brasileirão, só as "
          "odds de fechamento), que chegam com uns 2 dias de atraso: a liga anda conforme os jogos entram nelas.",
          "A casa \"melhor\" pega a maior odd entre as casas comuns da planilha, como quem tem conta em todas; de "
          "verdade, as casas limitam quem ganha com aposta de valor.",
          "O controle é o Valor 3% refeito por este simulador; apostas decididas e liquidadas no dia do jogo."]

ROT_LIGA = {"todas": "Todas", "europa": "Só a Europa", **{k: A.NOME_LIGA[k] for k in LIGAS}}
ESP = {
    "id": "valor", "nome": "Valor", "icone": "⚽", "prefixo": "a", "controle": "valor3",
    "frase": "Aposta quando a odd paga mais do que a chance justa vale: o valor mínimo, a faixa de odd, os mercados, o "
             "jeito de apostar, a casa e o campeonato evoluem.",
    "genes": [
        {"k": "limiar", "nome": "Valor mínimo", "tipo": "op", "opcoes": [0.01, 0.02, 0.03, 0.05, 0.08, 0.12], "un": "%",
         "neutro": 0.03},
        {"k": "de", "nome": "Odd de", "tipo": "op", "opcoes": [1.2, 1.5, 2.0, 3.0], "neutro": 1.5},
        {"k": "ate", "nome": "Odd até", "tipo": "op", "opcoes": [2.2, 3.0, 4.0, 6.0, 10.0], "neutro": 4.0},
        {"k": "mercados", "nome": "Mercados", "tipo": "op", "opcoes": ["ambos", "1x2", "ou"],
         "rotulos": {"ambos": "1X2 e gols", "1x2": "Só o 1X2", "ou": "Só mais/menos de 2,5"}, "neutro": "ambos"},
        {"k": "stake", "nome": "Aposta", "tipo": "op", "opcoes": ["fixo", "kelly"],
         "rotulos": {"fixo": "Fixa", "kelly": "Kelly"}, "neutro": "fixo"},
        {"k": "aposta", "nome": "Valor fixo", "tipo": "op", "opcoes": [0.005, 0.01, 0.02], "un": "%", "neutro": 0.01,
         "so": {"stake": "fixo"}},
        {"k": "kf", "nome": "Fração de Kelly", "tipo": "op", "opcoes": [0.1, 0.25, 0.5], "neutro": 0.25,
         "so": {"stake": "kelly"}},
        {"k": "casa", "nome": "Casa", "tipo": "op", "opcoes": ["bet365", "melhor"],
         "rotulos": {"bet365": "Bet365", "melhor": "A melhor"}, "neutro": "bet365"},
        {"k": "liga", "nome": "Campeonato", "tipo": "op", "opcoes": ["todas", "europa"] + LIGAS, "rotulos": ROT_LIGA,
         "neutro": "todas"},
    ],
}


def _reparar(genes):
    """A faixa de odd sempre aberta: `ate` sobe até passar de `de`."""
    g = reparar(ESP, genes)
    if g["ate"] <= g["de"]:
        g["ate"] = next(x for x in ESP["genes"][2]["opcoes"] if x > g["de"])
    return g


class Definicao:
    """A espécie como o motor comum espera."""
    versao, nome_controle, da_liga, rotulo, esp = VERSAO, "Valor 3%", "do valor", "apostas", ESP

    def genes_controle(self):
        """"Valor 3%": 3% de valor, odd de 1,50 a 4,00, os dois mercados, R$ 10 por aposta, na Bet365."""
        return _reparar({g["k"]: g["neutro"] for g in ESP["genes"]})

    def sementes(self):
        """As outras versões de valor que a forma já roda."""
        b = self.genes_controle()
        return [(de, _reparar({**b, **m})) for de, m in (
            ("valor5", {"limiar": 0.05}), ("valor8", {"limiar": 0.08}), ("kelly", {"stake": "kelly"}),
            ("favoritos", {"ate": 2.2}), ("azaroes", {"de": 3.0, "ate": 6.0}), ("valor3m", {"casa": "melhor"}),
            ("valor5m", {"limiar": 0.05, "casa": "melhor"}))]

    def descrever(self, genes):
        num = lambda x: f"{x:.2f}".replace(".", ",")  # noqa: E731
        out = [f"Valor ≥ {round(genes['limiar'] * 100)}%", f"odd {num(genes['de'])} a {num(genes['ate'])}"]
        if genes["mercados"] != "ambos":
            out.append("só 1X2" if genes["mercados"] == "1x2" else "só gols")
        out.append(f"R$ {genes['aposta'] * CAPITAL:.0f}".replace(".", ",") if genes["stake"] == "fixo"
                   else f"Kelly {str(genes['kf']).replace('.', ',')}")
        if genes["casa"] == "melhor":
            out.append("melhor casa")
        if genes["liga"] != "todas":
            out.append(ROT_LIGA[genes["liga"]])
        return " · ".join(out)


# ====================================================================== o banco
def _cod(xs, k):
    return [int(round(x * k)) for x in xs] if xs else 0


def _dia_num(ms):
    """O dia (Brasília) em que o jogo é liquidado (início + 2 h), como número (dias desde 1970)."""
    return dt.date.fromisoformat(dia_de(ms + 2 * HORA)).toordinal() - EPOCA


EPOCA = dt.date(1970, 1, 1).toordinal()


def linha_do_jogo(j):
    """O jogo do football-data (o formato de `apostas.ler_planilha`) numa linha compacta: [dia, liga, gols da casa,
    gols de fora, odds 1X2 da casa ×100, odds de onde sai a justa (a Pinnacle, que dá 3 casas) ×1000, melhor comum
    ×100 ou 0, odds do mais/menos ×100 ou 0, as da justa ×1000 ou 0]. As chances justas são refeitas na leitura (`apostas.sem_margem`), iguais às
    do teste no passado."""
    m, ou = j["mk"]["1x2"], j["mk"].get("ou")
    return [_dia_num(j["inicio"]), j["liga"], j["placar"][0], j["placar"][1], _cod(m["o"], 100),
            _cod(m.get("jo"), 1000), _cod(m.get("om"), 100), _cod(ou and ou["o"], 100), _cod(ou and ou.get("jo"), 1000)]


def guardar_jogos(est, jogos, agora):
    """Põe os jogos no banco (pelo id, sem repetir) e tira os de mais de BANCO_DIAS."""
    b = est.setdefault("bancoEv", {"jogos": {}})
    js = b.setdefault("jogos", {})
    for j in jogos:
        if j.get("mk", {}).get("1x2") and j["liga"] in LIGAS:
            js[format(zlib.crc32(j["id"].encode()), "08x")] = linha_do_jogo(j)
    corte = _dia_num(agora - BANCO_DIAS * DIA)
    for k in [k for k, x in js.items() if x[0] < corte]:
        del js[k]
    return len(js)


def atualizar(est, fonte, agora, log, erros, jogos=None):
    """O banco em dia: com os `jogos` das 3 temporadas (o teste no passado acabou de baixar) ou, uma vez por dia, com a
    temporada de agora (as planilhas gratuitas, sem chave)."""
    b = est.setdefault("bancoEv", {"jogos": {}})
    if jogos:
        n = guardar_jogos(est, jogos, agora)
        b["em"] = agora
        log(f"  apostas: evolução: banco com {n} jogos (as 3 temporadas)")
        return
    if agora - int(b.get("em") or 0) < ATUALIZAR:
        return
    try:
        novos, _info = A.baixar_passado(fonte, agora, log, erros, n=1 if b.get("jogos") else A.HIST_TEMPORADAS)
    except A.ERROS_API as e:
        erros.append(f"evolução: planilhas ({e})")
        return
    n = guardar_jogos(est, novos, agora)
    b["em"] = agora
    log(f"  apostas: evolução: banco posto em dia ({len(novos)} jogos da temporada de agora; {n} no total)")


class Dados:
    """O banco para o simulador: os jogos em ordem, cada um com o dia (Brasília) em que é liquidado."""

    def __init__(self, est, min_apostas=MIN_APOSTAS):
        self.min_apostas = min_apostas
        js = list(((est.get("bancoEv") or {}).get("jogos") or {}).values())
        js.sort(key=lambda x: x[0])
        self.jogos = []
        for d, liga, gc, gf, o, jo, om, uo, ujo in js:
            p = A.sem_margem([x / 1000 for x in jo]) if jo else None
            if not p:
                continue
            mk = {"1x2": ([x / 100 for x in o], p, [x / 100 for x in om] if om else None)}
            up = A.sem_margem([x / 1000 for x in ujo]) if uo and ujo else None
            if up:
                mk["ou"] = ([x / 100 for x in uo], up, None)
            self.jogos.append((dt.date.fromordinal(d + EPOCA).isoformat(), liga, (gc, gf), mk))
        self.primeiro = (dt.date.fromisoformat(self.jogos[0][0]) - dt.timedelta(days=1)).isoformat() \
            if self.jogos else None  # a véspera do 1º jogo

    @property
    def tem_dados(self):
        return len(self.jogos) >= MIN_JOGOS

    def simular(self, genes, inicio, hoje):
        c = simular(self, genes, inicio, hoje)
        c["montou"] = c["ops"] >= self.min_apostas
        return c

    @staticmethod
    def extras(c):
        return {"membros": [], "custos": 0.0, "largadas": 0, "acertos": c["acertos"], "resolvidas": c["ops"]}


def apostas_do_jogo(genes, liga, mk):
    """[(mercado, índice, odd, chance)] que a regra aposta neste jogo (no máximo uma por mercado)."""
    if genes["liga"] == "europa" and liga == "bra":
        return []
    if genes["liga"] not in ("todas", "europa") and liga != genes["liga"]:
        return []
    out = []
    for nome in (("1x2", "ou") if genes["mercados"] == "ambos" else (genes["mercados"],)):
        m = mk.get(nome)
        if not m:
            continue
        os_, ps, om = m
        if genes["casa"] == "melhor" and om:
            os_ = om
        melhor = None
        for i, (o, p) in enumerate(zip(os_, ps)):
            if not (genes["de"] <= o <= genes["ate"]):
                continue
            v = o * p - 1
            if v >= genes["limiar"] - 1e-12 and (melhor is None or v > melhor[3]):
                melhor = (i, o, p, v)
        if melhor:
            out.append((nome, melhor[0], melhor[1], melhor[2]))
    return out


def simular(D, genes, inicio, hoje):
    """A conta de uma versão de `inicio` a `hoje` (dias de Brasília), um ponto por dia: { serie: [[dia, R$]], retorno,
    piorQueda, ops (apostas), acertos, montou }."""
    caixa = float(CAPITAL)
    serie, ops, acertos = [], 0, 0
    pico, queda = caixa, 0.0
    jogos = [j for j in D.jogos if inicio <= j[0] <= hoje]
    i = 0
    d, fim = dt.date.fromisoformat(inicio), dt.date.fromisoformat(hoje)
    while d <= fim:
        dia = d.isoformat()
        while i < len(jogos) and jogos[i][0] <= dia:
            _dia, liga, placar, mk = jogos[i]
            i += 1
            for nome, sel, o, p in apostas_do_jogo(genes, liga, mk):
                if genes["stake"] == "kelly":
                    st = min(genes["kf"] * A.kelly(o, p), A.KELLY_MAX) * caixa
                else:
                    st = genes["aposta"] * CAPITAL
                st = round(st, 2)
                if st < 0.01 or st > caixa:
                    continue
                ops += 1
                if A.ganhou(nome, sel, placar):
                    caixa += st * (o - 1)
                    acertos += 1
                else:
                    caixa -= st
        serie.append([dia, round(caixa, 2)])
        pico = max(pico, caixa)
        queda = max(queda, 1 - caixa / pico if pico > 0 else 0.0)
        d += dt.timedelta(days=1)
    fim_v = serie[-1][1] if serie else CAPITAL
    return {"serie": serie, "retorno": round(fim_v / CAPITAL - 1, 5), "piorQueda": round(queda, 4), "ops": ops,
            "montou": ops > 0, "acertos": acertos}


# ====================================================================== a rodada
def _met(ctx):
    cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}

    def f(c):
        return metricas(c, cdi, cdi_ano_da_serie(cdi, CDI_PADRAO))
    return f


def avancar(ctx, est, agora, fonte, log, erros, jogos=None):
    """O banco em dia, o laboratório e a liga do valor. Devolve o bloco `evolucao` do apostas.json (None enquanto o
    banco não tem MIN_JOGOS jogos)."""
    atualizar(est, fonte, agora, log, erros, jogos)
    D = Dados(est, 3 if getattr(ctx, "exemplo", False) else MIN_APOSTAS)
    if not D.tem_dados:
        return None
    ev = ES.rodar(est, Definicao(), D, agora, ES.parametros(bool(getattr(ctx, "exemplo", False))), log)
    return ES.resumo(ev, D, agora, "apostas", "Apostas", FRASE, AVISOS, _met(ctx), VERSAO, jogos=len(D.jogos),
                     moeda="R$")


__all__ = ["avancar", "simular", "apostas_do_jogo", "Dados", "Definicao", "ESP", "linha_do_jogo", "guardar_jogos"]
