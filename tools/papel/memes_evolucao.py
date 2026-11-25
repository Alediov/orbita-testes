"""Evolução das Memecoins, NO PAPEL (pedido do Alediov, 25/11/2026: o 6º e último do plano docs/plano-evolucao.md do
repositório do app, "faremos uma por uma").

A espécie é a **Caçada** (controle `min1rc`, o "1º minuto + RugCheck"): toda versão aposta US$ 10 em cada lançamento
da amostra do observatório que passa nos filtros dela, entrando e saindo pela regra dela. Os genes (o que evolui):

- `entra`: no fim do 1º minuto, no 5º ou no "momento" (quando o valor de mercado chega a 60 SOL, só na 1ª hora);
- os filtros da hora do lançamento (os sinais que o observatório já anota): `rc` (sem risco alto no RugCheck),
  `criador` (o criador comprou no máximo X da oferta), `donos` (os 10 maiores donos com no máximo X), `bundle` (sem
  compras no mesmo bloco da criação), `redes` (com site ou redes) e `velha` (a carteira do criador não é nova). Com o
  filtro ligado, o token sem o sinal anotado (a fonte falhou) fica de fora;
- a saída: `alvo` (vende quando multiplica por isso; 0 = sem alvo), `stop` (vende quando cai a essa fração da
  entrada; 0 = sem stop) e `tempo` (vende depois de tantos minutos; 1440 = segura até as 24 h).

**Os dados**: o banco (`est["bancoEv"]`, até MAX_BANCO tokens) guarda, de cada token analisado com velas, os sinais, o
preço do lançamento e de 24 h, a liquidez de 24 h, o preço do SOL e o custo de rede da amostra e as velas de minuto da
2 primeiras horas (`VELAS_MIN`) em múltiplos do preço do lançamento. Gravado pelo `memes.analisar` daqui para frente (as velas de
antes não foram guardadas). As apostas usam as mesmas contas da forma (`memes.entrar`/`sair`: a curva, as taxas, a
rede e o deslize). A entrada só vale na 1ª hora; com o `tempo` de 24 h, o alvo e o stop só são vistos na 1ª hora
depois da entrada e, depois, a saída é pelo preço de 24 h (com o teto da liquidez). Cada aposta conta no dia do lançamento.

O laboratório e a liga são os do motor comum (`evolucao_series.py`; estado em `est["evolucoes"]["cacada"]`); o
laboratório começa com MIN_DIAS_LAB dias de banco e, nele, versão com menos de MIN_APOSTAS apostas fica sem nota.
Saída: `memes.json` → `evolucao` (FORMATO.md, "Evolução"). Teste: `teste_memes_evolucao.py`.
"""
from __future__ import annotations

import bisect

import evolucao_series as ES
import memes as MM
from conta import CAPITAL, cdi_ano_da_serie, dia_de, metricas
from genetica import reparar

VERSAO = 1
MIN = 60_000
JANELA_MIN = 60           # a entrada só na 1ª hora; a saída (fora o "segura 24 h") até 60 min depois dela
VELAS_MIN = 120           # as velas guardadas: as 2 primeiras horas
MAX_BANCO = 6000          # tokens no banco (~30 dias de amostras)
MIN_APOSTAS = 20          # no laboratório, menos que isso = sem nota
MIN_DIAS_LAB = 14
CDI_PADRAO = 0.149

FRASE = ("Caçadas de memecoins que evoluem: toda semana as piores regras saem, as melhores se cruzam e, às vezes, um gene "
         "muda. Só no papel.")
AVISOS = ["Só no papel: nenhuma carteira, nenhuma compra.",
          "As apostas são refeitas pelas velas de minuto da 1ª hora de cada token da amostra; com o \"segura 24 h\", o "
          "alvo e o stop só valem na 1ª hora.",
          "O papel entra depois dos robôs do bloco do lançamento e sem a disputa pela fila: o real tende a ser pior.",
          "Cada aposta conta no dia do lançamento (o resultado só se sabe 24 h depois)."]

ESP = {
    "id": "cacada", "nome": "Caçada", "icone": "🐸", "prefixo": "k", "controle": "min1rc",
    "frase": "Aposta US$ 10 nos lançamentos que passam nos filtros: quando entrar, os filtros da hora do lançamento e a "
             "saída evoluem.",
    "genes": [
        {"k": "entra", "nome": "Entra", "tipo": "op", "opcoes": ["min1", "min5", "momento"],
         "rotulos": {"min1": "No 1º minuto", "min5": "No 5º minuto", "momento": "Aos 60 SOL"}, "neutro": "min1"},
        {"k": "rc", "nome": "Sem risco no RugCheck", "tipo": "bool", "neutro": True},
        {"k": "criador", "nome": "O criador comprou no máximo", "tipo": "op", "opcoes": [1, 0.1, 0.05, 0.02],
         "un": "%", "rotulos": {"1": "Sem filtro"}, "neutro": 1},
        {"k": "donos", "nome": "Os 10 maiores com no máximo", "tipo": "op", "opcoes": [1, 0.5, 0.35, 0.25], "un": "%",
         "rotulos": {"1": "Sem filtro"}, "neutro": 1},
        {"k": "bundle", "nome": "Sem bundle", "tipo": "bool", "neutro": False},
        {"k": "redes", "nome": "Com site ou redes", "tipo": "bool", "neutro": False},
        {"k": "velha", "nome": "Criador sem carteira nova", "tipo": "bool", "neutro": False},
        {"k": "alvo", "nome": "Vende ao multiplicar por", "tipo": "op", "opcoes": [1.5, 2, 3, 5, 0], "un": "×",
         "rotulos": {"0": "Sem alvo"}, "neutro": 2},
        {"k": "stop", "nome": "Vende ao cair a", "tipo": "op", "opcoes": [0.8, 0.7, 0.5, 0.3, 0], "un": "%",
         "rotulos": {"0": "Sem stop"}, "neutro": 0.5},
        {"k": "tempo", "nome": "Vende depois de", "tipo": "op", "opcoes": [5, 15, 30, 60, 1440], "un": "min",
         "rotulos": {"1440": "24 h"}, "neutro": 30},
    ],
}
SEMENTES = {
    "min1": {"rc": False}, "min5": {"rc": False, "entra": "min5"}, "momento": {"rc": False, "entra": "momento"},
    "segura": {"rc": False, "alvo": 0, "stop": 0, "tempo": 1440},
}


def _pc(x):
    return f"{x * 100:g}".replace(".", ",") + "%"


def descrever(g):
    ent = {"min1": "1º minuto", "min5": "5º minuto", "momento": "aos 60 SOL"}[g["entra"]]
    filtros = [nome for k, nome in (("rc", "RugCheck"), ("bundle", "sem bundle"), ("redes", "com redes"),
                                    ("velha", "criador antigo")) if g[k]]
    if g["criador"] < 1:
        filtros.append(f"criador ≤ {_pc(g['criador'])}")
    if g["donos"] < 1:
        filtros.append(f"10 maiores ≤ {_pc(g['donos'])}")
    saida = []
    if g["alvo"]:
        saida.append(f"{g['alvo']:g}×".replace(".", ","))
    if g["stop"]:
        saida.append(f"−{_pc(1 - g['stop'])}")
    saida.append("24 h" if g["tempo"] == 1440 else f"{g['tempo']} min")
    t = ent + (" + " + ", ".join(filtros) if filtros else "")
    return f"{t} · sai em {' / '.join(saida)}"


class Definicao:
    versao, nome_controle, da_liga, rotulo = VERSAO, "1º minuto + RugCheck", "das caçadas", "memecoins"

    def __init__(self, esp=ESP):
        self.esp = esp

    def genes_controle(self):
        return reparar(self.esp, {g["k"]: g["neutro"] for g in self.esp["genes"]})

    def sementes(self):
        b = self.genes_controle()
        return [(vid, reparar(self.esp, {**b, **m})) for vid, m in SEMENTES.items()]

    def descrever(self, genes):
        return descrever(genes)


# ====================================================================== o banco
def _r(x, n=4):
    return float(f"{x:.{n}g}")


def _tri(v):
    return -1 if v is None else int(bool(v))


def registro(tok, velas, sol_usd, custo):
    """O token no banco: [t, p0, pB/p0, min. da graduação (−1), SOL em US$, custo de rede (SOL), p24/p0 (−1), liquidez
    de 24 h (US$), RugCheck ("ok"/"alto"/None), criador, os 10 maiores (−1), bundle (−1), redes (−1), carteira nova
    (−1), velas das 2 primeiras horas [minuto, abre, máx., mín., fecha, …] em múltiplos de p0]."""
    t0, p0 = tok["t"], tok["p0"]
    sg = tok.get("sg") if isinstance(tok.get("sg"), dict) else {}
    vs = []
    for v in velas:
        dm = (v[0] - t0) // MIN
        if dm < 0:
            continue
        if dm > VELAS_MIN:
            break
        vs += [int(dm), *(_r(x / p0, 6) for x in v[1:5])]
    tg = tok.get("tGrad")
    p24 = tok.get("p24")
    return [t0, _r(p0, 6), _r((tok.get("pB") or p0) / p0), int((tg - t0) // MIN) if tg else -1, _r(sol_usd, 5),
            _r(custo, 4), _r(p24 / p0, 6) if p24 is not None else -1, round(tok.get("liq24") or 0), tok.get("rc"),
            _r(tok.get("cr") or 0, 3), _r(sg["con"], 3) if sg.get("con") is not None else -1,
            -1 if sg.get("bd") is None else int(sg["bd"]), _tri(sg.get("rd")), _tri(sg.get("nv")), vs]


def guardar(est, tok, velas, sol_usd, custo):
    b = est.setdefault("bancoEv", [])
    b.append(registro(tok, velas, sol_usd, custo))
    del b[:-MAX_BANCO]


class Token:
    """Um registro do banco aberto: o `tok` e as velas (absolutas) que as contas da forma usam."""
    __slots__ = ("t", "dia", "tok", "velas", "sol", "custo", "rc", "cr", "con", "bd", "rd", "nv")

    def __init__(self, r):
        t0, p0, pb, tg, sol, custo, p24, liq, rc, cr, con, bd, rd, nv, vs = r
        self.t, self.dia, self.sol, self.custo = t0, dia_de(t0), sol, custo
        self.rc, self.cr, self.con, self.bd, self.rd, self.nv = rc, cr, con, bd, rd, nv
        self.tok = {"t": t0, "p0": p0, "pB": pb * p0, "tGrad": t0 + tg * MIN if tg >= 0 else None,
                    "p24": p24 * p0 if p24 >= 0 else None, "liq24": liq or None}
        self.velas = [(t0 + vs[i] * MIN, vs[i + 1] * p0, vs[i + 2] * p0, vs[i + 3] * p0, vs[i + 4] * p0, 0.0)
                      for i in range(0, len(vs), 5)]

    def passa(self, g):
        if g["rc"] and self.rc != "ok":
            return False
        if g["criador"] < 1 and self.cr > g["criador"]:
            return False
        if g["donos"] < 1 and not (0 <= self.con <= g["donos"]):
            return False
        if g["bundle"] and not (0 <= self.bd < MM.BUNDLE_MIN):
            return False
        if g["redes"] and self.rd != 1:
            return False
        if g["velha"] and self.nv != 0:
            return False
        return True


def aposta(tk, g):
    """(resultado em US$, motivo) de uma aposta de US$ 10, ou None se a regra não entrou."""
    tok, velas = tk.tok, tk.velas
    e = MM.entrada(g["entra"], tok, velas)
    if not e:
        return None
    te, pe = e
    if te > tok["t"] + JANELA_MIN * MIN or pe <= 0:
        return None  # o "momento" depois da 1ª hora: sem velas para saber
    tg = tok.get("tGrad")
    grad = lambda t: bool(tg) and t >= tg  # noqa: E731
    sol = MM.APOSTA / tk.sol
    q, gasto = MM.entrar(sol, pe, grad(te), tk.custo)
    alvo, stop, tempo = g["alvo"], g["stop"], g["tempo"]
    fim = te + (JANELA_MIN if tempo == 1440 else tempo) * MIN
    for v in velas:
        if v[0] <= te:
            continue
        if v[0] > fim:
            break
        if stop and v[3] <= pe * stop:  # dentro de uma vela, a pior hipótese: o stop antes do alvo
            return (MM.sair(q, pe * stop, grad(v[0]), tk.custo) - gasto) * tk.sol, "stop"
        if alvo and v[2] >= pe * alvo:
            return (MM.sair(q, pe * alvo, grad(v[0]), tk.custo) - gasto) * tk.sol, "alvo"
    if tempo == 1440:
        ts = te + MM.ESPERA
        p24 = tok["p24"] if tok["p24"] is not None else MM.preco_em(velas, ts, pe)
        recebido = MM.sair(q, p24, grad(ts), tk.custo) if p24 > 0 else -tk.custo
        liq = tok.get("liq24")
        if liq and recebido > MM.LIQ_SAIDA * liq / tk.sol:
            recebido = MM.LIQ_SAIDA * liq / tk.sol
        return (recebido - gasto) * tk.sol, "24 h"
    return (MM.sair(q, MM.preco_em(velas, fim, pe), grad(fim), tk.custo) - gasto) * tk.sol, "tempo"


# ====================================================================== os dados e o simulador
class Dados:
    def __init__(self, banco, min_apostas=MIN_APOSTAS):
        self.toks = sorted((Token(r) for r in banco or []), key=lambda x: x.t)
        self.dias = [x.dia for x in self.toks]
        self.min_apostas = min_apostas
        self.primeiro = self.dias[0] if self.dias else None

    @property
    def tem_dados(self):
        return bool(self.toks)

    def simular(self, genes, inicio, hoje):
        return simular(self, genes, inicio, hoje)

    @staticmethod
    def extras(c):
        return {"membros": [], "resolvidas": c["apostas"], "acertos": c["acertos"], "custos": c["custos"]}


def simular(D, g, inicio, hoje):
    """A conta de uma versão de `inicio` a `hoje`: { serie (um ponto por dia com apostas, e o 1º dia), retorno,
    piorQueda, ops (apostas), montou (pelo menos `min_apostas` apostas), apostas, acertos, custos }."""
    i0, i1 = bisect.bisect_left(D.dias, inicio), bisect.bisect_right(D.dias, hoje)
    saldo, pico, queda = CAPITAL, CAPITAL, 0.0
    por_dia, n, ac, custos = {inicio: CAPITAL}, 0, 0, 0.0
    for tk in D.toks[i0:i1]:
        if not tk.passa(g):
            continue
        r = aposta(tk, g)
        if r is None:
            continue
        if saldo < MM.APOSTA:
            break  # sem dinheiro para apostar
        saldo += r[0]
        n += 1
        ac += r[0] > 0
        custos += 2 * tk.custo * tk.sol
        por_dia[tk.dia] = saldo
        pico = max(pico, saldo)
        queda = max(queda, 1 - saldo / pico if pico > 0 else 0.0)
    serie = [[d, round(v, 2)] for d, v in sorted(por_dia.items())]
    if serie[-1][0] < hoje and D.dias and D.dias[min(i1, len(D.dias)) - 1] >= inicio:
        serie.append([min(hoje, D.dias[i1 - 1]) if i1 else hoje, round(saldo, 2)])
    return {"serie": serie, "retorno": round(saldo / CAPITAL - 1, 5), "piorQueda": round(queda, 4), "ops": n,
            "montou": n >= D.min_apostas, "apostas": n, "acertos": int(ac), "custos": round(custos, 2)}


# ====================================================================== a rodada
def _met(ctx):
    cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}

    def f(c):
        return metricas(c, cdi, cdi_ano_da_serie(cdi, CDI_PADRAO))
    return f


def avancar(ctx, est, agora):
    """O laboratório e a liga da Caçada. Devolve o bloco `evolucao` do memes.json (None sem banco)."""
    exemplo = bool(getattr(ctx, "exemplo", False))
    D = Dados(est.get("bancoEv"), 3 if exemplo else MIN_APOSTAS)
    if not D.tem_dados:
        return None
    P = ES.parametros(exemplo, **({} if exemplo else {"MIN_DIAS_LAB": MIN_DIAS_LAB}))
    sub = est.setdefault("evolucoes", {}).setdefault("cacada", {})
    ev = ES.rodar(sub, Definicao(), D, agora, P, ctx.log)
    return ES.resumo(ev, D, agora, "memes", "Memecoins", FRASE, AVISOS, _met(ctx), VERSAO, tokens=len(D.toks),
                     aposta=MM.APOSTA)


__all__ = ["avancar", "simular", "aposta", "Dados", "Definicao", "Token", "registro", "guardar", "ESP"]
