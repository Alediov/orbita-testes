"""Apostas de valor no futebol, NO PAPEL (formato: tools/papel/FORMATO.md). Nenhuma aposta de verdade, nenhuma conta em
casa de apostas: só dados públicos e gratuitos. O Alediov apostava na Betano com robôs simples de "aposta de valor" e
com a aposta grátis semanal (R$ 5, sem devolução do valor); as apostas estão suspensas no Brasil e ele NÃO vai apostar
agora: o papel é só para ver como o método se sairia.

O método:

- chance justa = as odds da Pinnacle (a casa de margem mais baixa, que aceita profissionais) sem a margem, pelo
  MÉTODO DA POTÊNCIA: p_i = (1/o_i)^k, com k tal que as chances somem 1 (tira mais margem dos azarões, onde as casas
  cobram mais; `sem_margem`). No 1X2 (vitória, empate, derrota) e, quando há, no "mais/menos de 2,5 gols";
- valor = odd da casa comum (Betano; no teste no passado, a Bet365) × chance justa − 1; aposta quando o valor passa do
  limiar da versão, com a odd dentro da faixa (1,50 a 4,00 por padrão), no máximo uma seleção por mercado e por jogo
  (a de maior valor);
- quando: ao vivo, 6 h antes do jogo (sem preço nessa hora, o último até 1 h antes); no passado, as odds "de antes do
  jogo" das planilhas (coletadas na sexta à tarde para o fim de semana e na terça para o meio de semana);
- banca: 1.000 de saldo fictício (em R$, como a Betano; o app mostra igual às outras formas); aposta fixa de 1% da banca
  inicial (R$ 10) ou ¼ do critério de Kelly, no máximo 2% da banca de agora;
- liquidação pelo placar final (90 minutos); jogo sem placar por 10 dias: aposta anulada (o valor volta);
- CLV (valor contra o fechamento) = odd que pegamos × chance justa da Pinnacle no fechamento − 1 (`clv`).

Fontes (`odds.py`): o teste no passado usa as planilhas do football-data.co.uk (sem chave); o ao vivo usa a OddsPapi
(gratuita, com chave na variável de ambiente ODDSPAPI_KEY, ~250 pedidos por mês: `Orcamento`), um `/historical-odds`
por jogo terminado (o histórico de preços da Pinnacle e da Betano do começo ao fechamento, de onde se reconstrói a
aposta de 6 h antes, sem olhar o futuro) e alguns `/fixtures`; os placares vêm da OddsPapi, se trouxer, ou da ESPN.
Sem a chave, o ao vivo não roda (`aoVivo` null) e só o teste no passado aparece.
"""
from __future__ import annotations

import copy
import csv
import datetime as dt
import io
import math
import os
import re
import unicodedata

import odds
from conta import CAPITAL, DIA, FUSO_MS, HORA, Curva, Eventos, dia_de, num_br, pct_br

try:  # o falso da Hyperliquid levanta hl.Erro quando um pedido "falha" nos testes
    import hl
    ERROS_API = (odds.Erro, hl.Erro)
except ImportError:  # pragma: no cover
    ERROS_API = (odds.Erro,)

NOME = "Apostas de valor"
VERSAO = 1

# ---------------------------------------------------------------------------------------------------- regras
FAIXA_PADRAO = (1.5, 4.0)
APOSTA_FIXA = 0.01          # da banca inicial
KELLY_FRACAO, KELLY_MAX = 0.25, 0.02
GRATIS_VALOR = 5.0          # R$ da aposta grátis semanal
GRATIS_FAIXA = (2.0, 6.0)
ANTES_H = 6                 # a aposta ao vivo é feita 6 h antes do jogo…
ULTIMO_H = 1                # …ou no último preço até 1 h antes
FIM_JOGO = 3 * HORA         # depois disso o jogo acabou (o fechamento e o placar existem)
ANULAR_DIAS = 10            # sem placar por 10 dias: anula
EV_POR_DIA = 3              # eventos de apostas da versão padrão por dia (o resto entra no resumo da semana)

# ---------------------------------------------------------------------------------------------------- ligas
# chave, nome, planilha do football-data (None = não tem), código do placar da ESPN
LIGAS = [
    ("bra", "Brasileirão", "BRA", "bra.1"),
    ("eng", "Premier League", "E0", "eng.1"),
    ("esp", "La Liga", "SP1", "esp.1"),
    ("ita", "Série A (Itália)", "I1", "ita.1"),
    ("ger", "Bundesliga", "D1", "ger.1"),
    ("fra", "Ligue 1", "F1", "fra.1"),
    ("lib", "Libertadores", None, "conmebol.libertadores"),
]
NOME_LIGA = {k: n for k, n, _, _ in LIGAS}
PRIORIDADE = {k: i for i, (k, _, _, _) in enumerate(LIGAS)}

# ---------------------------------------------------------------------------------------------------- football-data
URL_FD = "https://www.football-data.co.uk/mmz4281/{temp}/{div}.csv"
URL_FD_NOVA = "https://www.football-data.co.uk/new/{pais}.csv"
PLANILHAS_NOVAS = {"BRA"}    # um arquivo por país, com todas as temporadas e só odds de fechamento
HIST_TEMPORADAS = 3          # a atual e as 2 anteriores (europeias: ago.–mai.; o Brasileirão pelo ano)
HIST_REFAZER = 7 * DIA
HIST_TEMPO_MIN = 240         # segundos que precisam sobrar na rodada para refazer o teste no passado
BET365, MEDIA, PINNACLE = "Bet365", "média das casas", "Pinnacle"
# (rótulo, colunas) em ordem de preferência; 1X2 = casa, empate, fora; gols = mais, menos de 2,5
SOFT_1X2 = [(BET365, ("B365H", "B365D", "B365A")), (MEDIA, ("AvgH", "AvgD", "AvgA")), (MEDIA, ("BbAvH", "BbAvD", "BbAvA"))]
JUSTA_1X2 = [(PINNACLE, ("PSH", "PSD", "PSA")), (PINNACLE, ("PH", "PD", "PA")), (MEDIA, ("AvgH", "AvgD", "AvgA")),
             (MEDIA, ("BbAvH", "BbAvD", "BbAvA"))]
FECH_1X2 = [(PINNACLE, ("PSCH", "PSCD", "PSCA")), (MEDIA, ("AvgCH", "AvgCD", "AvgCA"))]
SOFT_OU = [(BET365, ("B365>2.5", "B365<2.5")), (MEDIA, ("Avg>2.5", "Avg<2.5")), (MEDIA, ("BbAv>2.5", "BbAv<2.5"))]
JUSTA_OU = [(PINNACLE, ("P>2.5", "P<2.5")), (MEDIA, ("Avg>2.5", "Avg<2.5")), (MEDIA, ("BbAv>2.5", "BbAv<2.5"))]
FECH_OU = [(PINNACLE, ("PC>2.5", "PC<2.5")), (MEDIA, ("AvgC>2.5", "AvgC<2.5"))]
# as planilhas "novas" (Brasil e outras ligas fora da Europa) só têm odds de FECHAMENTO: a aposta é feita no
# fechamento e o CLV não é medido nelas
SOFT_NOVA = [(BET365, ("B365CH", "B365CD", "B365CA")), (BET365, ("B365H", "B365D", "B365A")),
             (MEDIA, ("AvgCH", "AvgCD", "AvgCA")), (MEDIA, ("AvgH", "AvgD", "AvgA"))]
JUSTA_NOVA = [(PINNACLE, ("PSCH", "PSCD", "PSCA")), (PINNACLE, ("PH", "PD", "PA")),
              (MEDIA, ("AvgCH", "AvgCD", "AvgCA")), (MEDIA, ("AvgH", "AvgD", "AvgA"))]

# ---------------------------------------------------------------------------------------------------- OddsPapi
ORCAMENTO_MES = 250          # pedidos por mês no plano gratuito
PARAR_EM = 0.9               # para em 90% (225)
MAX_POR_DIA = 8              # jogos acompanhados por dia, no máximo
FX_CADA = 84 * HORA          # lista de jogos de cada campeonato: a cada 3,5 dias…
FX_VAZIO_CADA = 7 * DIA      # …ou 1× por semana se veio vazia (fora de temporada)
FX_DEPOIS = 4 * DIA          # a lista cobre até 4 dias à frente
TORNEIOS_CADA = 30 * DIA
ESPORTE_PADRAO = 10          # futebol na OddsPapi (conferido por /sports se a lista vier vazia)
SOFTS = ["betano.bet.br", "betano", "bet365"]  # a casa comum, em ordem de preferência
NOME_SOFT = {"betano.bet.br": "Betano", "betano": "Betano (internacional)", "bet365": "Bet365"}
VAZIOS_PARA_DESCARTAR = 5
RETESTAR = 14 * DIA
SEM_PINNACLE_PAUSA = 6       # jogos seguidos sem a Pinnacle: pausa o ao vivo 3 dias (formato inesperado?)
ESPN_MAX = 30                # pedidos ao placar da ESPN por rodada
URL_ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates={dia}"

# ---------------------------------------------------------------------------------------------------- versões
# id, nome, grupo, risco, regra, frase
VERSOES = [
    ("valor3", "Valor 3%", "Valor", "médio", {"tipo": "valor", "limiar": 0.03, "faixa": FAIXA_PADRAO, "stake": "fixo"},
     "Aposta 1% da banca (R$ 10) quando a odd da casa paga pelo menos 3% a mais do que a chance justa vale."),
    ("valor5", "Valor 5%", "Valor", "médio", {"tipo": "valor", "limiar": 0.05, "faixa": FAIXA_PADRAO, "stake": "fixo"},
     "O mesmo, só com vantagem de 5% ou mais: menos apostas, cada uma melhor."),
    ("valor8", "Valor 8%", "Valor", "médio", {"tipo": "valor", "limiar": 0.08, "faixa": FAIXA_PADRAO, "stake": "fixo"},
     "Só as diferenças grandes, de 8% ou mais: são raras e às vezes a casa sabe de algo (um titular fora)."),
    ("kelly", "Kelly ¼", "Valor", "alto", {"tipo": "valor", "limiar": 0.03, "faixa": FAIXA_PADRAO, "stake": "kelly"},
     "Vantagem de 3% ou mais, mas o valor apostado cresce com a vantagem: ¼ do critério de Kelly, no máximo 2% da banca."),
    ("favoritos", "Favoritos", "Valor", "médio", {"tipo": "valor", "limiar": 0.03, "faixa": (1.5, 2.2), "stake": "fixo"},
     "Valor de 3% ou mais, só nas odds de 1,50 a 2,20: acerta mais vezes e a banca balança menos."),
    ("azaroes", "Azarões", "Valor", "alto", {"tipo": "valor", "limiar": 0.03, "faixa": (3.0, 6.0), "stake": "fixo"},
     "Valor de 3% ou mais, só nas odds de 3,00 a 6,00: acerta pouco e passa por sequências longas de derrotas."),
    ("gratis", "Aposta grátis", "Aposta grátis", "baixo", {"tipo": "gratis", "faixa": GRATIS_FAIXA},
     "Uma aposta grátis de R$ 5 por semana, como a da Betano, na odd de 2,00 a 6,00 que mais vale a pena; "
     "o valor não volta, só o lucro (a conta mostra 1.000 + o que ganhou)."),
    ("semfiltro", "Sem filtro", "Referência", "médio", {"tipo": "casa", "faixa": (1.01, 1000.0), "stake": "fixo"},
     "Referência: aposta R$ 10 no time da casa em todo jogo, sem olhar valor; mostra a margem da casa comendo a banca."),
]
PADRAO = "valor3"

FRASE = ("Aposta (no papel) quando a odd da casa paga mais do que a chance real do jogo vale; a chance real vem das "
         "odds da Pinnacle sem a margem.")
COMO_FUNCIONA = [
    "Uma casa paga, por exemplo, 2,10 pela vitória do Flamengo: a chance que ela dá é 1 ÷ 2,10 ≈ 47,6%. Somando as "
    "chances das três saídas do jogo (vitória, empate, derrota) passa de 100%: o que passa é a margem da casa.",
    "A Pinnacle tem a margem mais baixa e aceita apostadores profissionais, então as odds dela são a melhor estimativa "
    "pública da chance real. Tirando a margem dela (pelo método da potência, que tira mais margem dos azarões, onde as "
    "casas cobram mais), sobra a odd justa.",
    "Valor = odd da casa × chance justa − 1. Se a Betano paga 2,10 e a justa é 1,95 (chance de 51,3%), o valor é "
    "2,10 × 0,513 − 1 = 7,7%: em média, R$ 7,70 a cada R$ 100 apostados assim, no longo prazo. No papel, a aposta é "
    "feita 6 h antes do jogo (ou no último preço até 1 h antes), com odds de 1,50 a 4,00.",
    "Mesmo com valor, perde-se muito: a 2,10 perde-se quase metade das vezes, e o lucro só se separa da sorte depois "
    "de centenas de apostas. Por isso o papel mede o CLV (valor contra o fechamento): a odd que pegamos × a chance "
    "justa da Pinnacle na hora do jogo − 1. Pegar odds melhores que o fechamento quase sempre é o sinal mais confiável "
    "de vantagem de verdade, e aparece em semanas, muito antes do lucro.",
    "Banca: toda conta começa com 1.000 de saldo fictício (em R$). A aposta fixa é 1% da banca inicial (R$ 10); a "
    "versão Kelly aposta mais quando a vantagem é maior (¼ do critério de Kelly, no máximo 2% da banca).",
    "Aposta grátis sem devolução do valor: ganhando a 2,00, recebe-se só o lucro de R$ 5. Ela vale, em média, "
    "R$ 5 × chance × (odd − 1): numa odd justa de 2,00 (50%), R$ 2,50; numa de 5,00 (20%), R$ 4,00. Como o valor "
    "apostado não volta, as odds mais altas aproveitam melhor a aposta grátis (perto de 100% − a chance).",
    "Teste no passado: planilhas do football-data.co.uk (Brasileirão e as 5 maiores ligas da Europa, nas últimas "
    "temporadas), com a Bet365 no lugar da Betano, que não está nesses dados. O ao vivo usa a OddsPapi, gratuita com "
    "limite de ~250 pedidos por mês: segue até 8 jogos por dia, começando pelo Brasileirão.",
]
AVISOS = [
    "As casas limitam ou fecham as contas de quem ganha com aposta de valor: depois de algumas semanas a Betano "
    "costuma cortar o valor máximo para centavos. O papel não tem limite.",
    "No teste no passado a casa é a Bet365, no lugar da Betano (a Betano não está nas planilhas); no Brasileirão, onde "
    "só há odds de fechamento, a aposta é feita no fechamento e o CLV não é medido.",
    "O papel pega a odd de 6 h antes sem atraso; de verdade a odd pode mudar ou a seleção ficar suspensa enquanto você "
    "aposta, e a casa pode recusar ou reduzir a aposta.",
    "Sorte pesa muito: com algumas dezenas de apostas, ganhar ou perder não diz quase nada. Olhe o CLV e o número de "
    "apostas antes do resultado.",
    "A aposta grátis tem regras (odd mínima, prazo, mercados aceitos) que mudam; o papel supõe uma por semana, sempre.",
    "As apostas estão suspensas no Brasil agora, e os ganhos podem pagar imposto de renda. Apostar pode viciar: aqui é "
    "só para ver como o método se sairia.",
    "O ao vivo segue poucos jogos por dia por causa do limite gratuito da OddsPapi; as médias do ao vivo demoram mais "
    "para firmar que as do teste no passado.",
]


# ---------------------------------------------------------------------------------------------------- contas
def sem_margem(odds_):
    """Chances justas pelo método da potência: p_i = (1/o_i)^k, k tal que a soma dê 1 (bissecção). None se faltar
    alguma odd ou alguma for ≤ 1."""
    try:
        q = [1.0 / float(o) for o in odds_]
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    if len(q) < 2 or any(not (0 < x < 1) for x in q):
        return None
    lo, hi = 1e-3, 50.0
    for _ in range(100):
        k = (lo + hi) / 2
        if sum(x ** k for x in q) > 1:
            lo = k
        else:
            hi = k
    k = (lo + hi) / 2
    p = [x ** k for x in q]
    s = sum(p)
    return [x / s for x in p]


def valor(odd, p):
    return odd * p - 1


def kelly(odd, p):
    """Fração da banca do critério de Kelly para odd decimal `odd` e chance `p` (0 se não há vantagem)."""
    if odd <= 1:
        return 0.0
    return max(0.0, (odd * p - 1) / (odd - 1))


def ev_gratis(stake, odd, p):
    """Valor esperado de uma aposta grátis sem devolução do valor: stake × (odd × p − p) = stake × p × (odd − 1)."""
    return stake * p * (odd - 1)


def clv(odd, p_fech):
    """Valor contra o fechamento: a odd pega × a chance justa no fechamento − 1."""
    return odd * p_fech - 1


def ganhou(mk, sel, placar):
    h, a = placar
    if mk == "1x2":
        return sel == (0 if h > a else 1 if h == a else 2)
    return sel == (0 if h + a > 2.5 else 1)


# ---------------------------------------------------------------------------------------------------- textos
def reais(v, sinal=False):
    s = f"R$ {num_br(abs(v))}"
    if sinal:
        return ("+" if v >= 0 else "−") + s
    return ("−" if v < 0 else "") + s


def odd_txt(o):
    return num_br(o, 2)


def _ddmm(ms):
    return dt.datetime.fromtimestamp((ms + FUSO_MS) / 1000, dt.timezone.utc).strftime("%d/%m")


def nome_sel(casa, fora, mk, i):
    if mk == "1x2":
        return [f"{casa} vence", "empate", f"{fora} vence"][i]
    return ["mais de 2,5 gols", "menos de 2,5 gols"][i]


def semana_de(ms):
    """Início (ms) da semana de Brasília (segunda-feira, 0h) que contém `ms`."""
    dias = (int(ms) + FUSO_MS) // DIA
    seg = dias - (dias + 3) % 7  # 01/01/1970 foi quinta-feira
    return seg * DIA - FUSO_MS


def _f(x):
    try:
        v = float(str(x).strip().replace(",", "."))
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ---------------------------------------------------------------------------------------------------- a conta
ACC = ("n", "ganhas", "apostado", "resultado", "oddS", "clvS", "clvN", "clvPos", "seq", "pior", "anuladas")


class Conta:
    """Uma versão: banca, apostas abertas (esperando o placar) e os números do `extra`."""

    def __init__(self, cfg, inicio, estado=None):
        self.id, self.nome, self.grupo, self.risco, self.regra, self.frase = cfg
        e = estado or {}
        self.curva = Curva.de_json(e.get("curva")) or Curva(inicio=inicio)
        self.caixa = float(e.get("caixa", self.curva.capital))
        self.abertas = list(e.get("abertas") or [])
        a = e.get("acc") or {}
        self.acc = {k: float(a.get(k, 0)) for k in ACC}
        self.semana = e.get("semana")
        self.casas = dict(e.get("casas") or {})

    def para_json(self):
        return {"curva": self.curva.para_json(), "caixa": self.caixa, "abertas": self.abertas, "acc": self.acc,
                "semana": self.semana, "casas": self.casas}

    @property
    def gratis(self):
        return self.regra["tipo"] == "gratis"

    def patrimonio(self):
        return self.caixa + sum(a["st"] for a in self.abertas if not a.get("g"))

    def marcar(self, t):
        self.curva.marcar(max(int(t), self.curva.t), self.patrimonio())

    # ------------------------------------------------------------------ decidir
    def _stake(self, odd, p):
        if self.regra.get("stake") == "kelly":
            f = min(KELLY_FRACAO * kelly(odd, p), KELLY_MAX)
            st = round(f * self.caixa, 2)
        else:
            st = round(APOSTA_FIXA * self.curva.capital, 2)
        return st if 0.01 <= st <= self.caixa else 0.0

    def decidir(self, j):
        """As apostas desta versão no jogo `j` (no máximo uma por mercado). Não abre nada."""
        r = self.regra
        lo, hi = r.get("faixa", FAIXA_PADRAO)
        out = []
        if r["tipo"] == "casa":
            m = j["mk"].get("1x2")
            if m and m["o"][0] and m["p"]:
                st = self._stake(m["o"][0], m["p"][0])
                if st:
                    out.append(nova_aposta(j, "1x2", 0, st))
            return out
        if r["tipo"] != "valor":
            return out
        for mk in ("1x2", "ou"):
            m = j["mk"].get(mk)
            if not m or not m.get("p"):
                continue
            melhor = None
            for i, (o, p) in enumerate(zip(m["o"], m["p"])):
                if not o or p is None or not (lo <= o <= hi):
                    continue
                v = valor(o, p)
                if v >= r["limiar"] - 1e-12 and (melhor is None or v > melhor[1]):
                    melhor = (i, v)
            if melhor:
                st = self._stake(m["o"][melhor[0]], m["p"][melhor[0]])
                if st:
                    out.append(nova_aposta(j, mk, melhor[0], st))
        return out

    def abrir(self, ap):
        if not ap.get("g"):
            self.caixa -= ap["st"]
        self.abertas.append(ap)

    # ------------------------------------------------------------------ liquidar
    def liquidar(self, ap, placar, t, ev=None, anular=False):
        """Fecha a aposta `ap` (tirada das abertas) pelo placar. Devolve o resultado em R$."""
        self.abertas = [a for a in self.abertas if a is not ap]
        g = bool(ap.get("g"))
        if anular:
            if not g:
                self.caixa += ap["st"]
            self.acc["anuladas"] += 1
            self._ev(ev, t, "anulou", f"{ap['jogo']}: sem placar em {ANULAR_DIAS} dias; aposta anulada"
                                      + ("." if g else f" e os {reais(ap['st'])} voltaram."))
            self.marcar(t)
            return 0.0
        venceu = ganhou(ap["mk"], ap["s"], placar)
        res = ap["st"] * (ap["o"] - 1) if venceu else (0.0 if g else -ap["st"])
        self.caixa += res if g else ap["st"] + res
        a = self.acc
        a["n"] += 1
        a["apostado"] += ap["st"]
        a["resultado"] += res
        a["oddS"] += ap["o"]
        if venceu:
            a["ganhas"] += 1
            a["seq"] = 0
        else:
            a["seq"] += 1
            a["pior"] = max(a["pior"], a["seq"])
        c = ap.get("clv")
        if c is not None:
            a["clvS"] += c
            a["clvN"] += 1
            a["clvPos"] += 1 if c > 0 else 0
        self.casas[ap["c"]] = self.casas.get(ap["c"], 0) + 1
        self.curva.operou(0.0)
        self.curva.fechou(res)
        self._semana(t, ev, ap, res)
        self.marcar(t)
        return res

    # ------------------------------------------------------------------ resumo da semana (só ao vivo)
    def _ev(self, ev, t, tipo, texto):
        if ev is not None:
            ev.add(t, tipo, texto, self.id)

    def _semana(self, t, ev, ap=None, res=0.0):
        ini = semana_de(t)
        s = self.semana
        if s and s["ini"] != ini:
            self.virar(t, ev)
            s = None
        if ev is None:
            return
        if not s:
            s = self.semana = {"ini": ini, "n": 0, "res": 0.0, "clvS": 0.0, "clvN": 0, "clvPos": 0}
        if ap is not None:
            s["n"] += 1
            s["res"] += res
            if ap.get("clv") is not None:
                s["clvS"] += ap["clv"]
                s["clvN"] += 1
                s["clvPos"] += 1 if ap["clv"] > 0 else 0

    def virar(self, agora, ev):
        """Se a semana guardada já acabou, solta o resumo dela."""
        s = self.semana
        if not s or semana_de(agora) == s["ini"]:
            return
        self.semana = None
        if ev is None or not s["n"] or self.gratis:  # a grátis já tem um evento por semana
            return
        fim = s["ini"] + 7 * DIA
        n = int(s["n"])
        txt = (f"Semana de {_ddmm(s['ini'])} a {_ddmm(fim - DIA)}: {n} aposta{'s' if n != 1 else ''}, "
               f"resultado {reais(s['res'], True)}")
        if s["clvN"]:
            txt += (f"; CLV médio de {pct_sinal(s['clvS'] / s['clvN'])} "
                    f"({int(s['clvPos'])} de {int(s['clvN'])} acima do fechamento)")
        ev.add(fim, "resumo", txt + ".", self.id)

    # ------------------------------------------------------------------ extra
    def extra(self, casa_padrao=None):
        a = self.acc
        n = int(a["n"])
        top = max(self.casas, key=lambda k: self.casas[k]) if self.casas else casa_padrao
        x = {"apostas": n, "acerto": round(a["ganhas"] / n, 4) if n else None,
             "roi": round(a["resultado"] / a["apostado"], 4) if a["apostado"] else None,
             "oddMedia": round(a["oddS"] / n, 3) if n else None,
             "clvMedio": round(a["clvS"] / a["clvN"], 4) if a["clvN"] else None,
             "clvPositivo": round(a["clvPos"] / a["clvN"], 4) if a["clvN"] else None,
             "piorSequencia": int(a["pior"]), "fonteSoft": rotulo_soft(top),
             "anuladas": int(a["anuladas"])}
        if self.gratis:
            x["ganhoGratis"] = round(a["resultado"], 2)
        self.curva.extra = x
        return x


def rotulo_soft(casa):
    if not casa:
        return None
    if casa.startswith("Betano"):
        return casa
    return f"{casa} (no lugar da Betano)"


def nova_aposta(j, mk, i, st, gratis=False):
    m = j["mk"][mk]
    o, p = m["o"][i], m["p"][i]
    pf = m.get("pf")
    return {"j": j["id"], "jogo": f"{j['casa']} × {j['fora']}", "l": j["liga"], "i": j["inicio"], "mk": mk, "s": i,
            "sel": nome_sel(j["casa"], j["fora"], mk, i), "o": round(o, 3), "p": round(p, 5),
            "v": round(valor(o, p), 5), "st": st, "c": j.get("soft") or BET365, "g": gratis,
            "clv": round(clv(o, pf[i]), 5) if pf else None}


def melhor_gratis(jogos):
    """A seleção de odd 2,00 a 6,00 com o maior valor esperado como aposta grátis (p × (odd − 1)), entre os jogos."""
    lo, hi = GRATIS_FAIXA
    melhor = None
    for j in jogos:
        for mk, m in j["mk"].items():
            if not m.get("p"):
                continue
            for i, (o, p) in enumerate(zip(m["o"], m["p"])):
                if not o or p is None or not (lo <= o <= hi):
                    continue
                e = ev_gratis(GRATIS_VALOR, o, p)
                if melhor is None or e > melhor[0]:
                    melhor = (e, j, mk, i)
    return melhor


def pct_sinal(v, casas=1):
    return ("+" if v >= 0 else "−") + pct_br(abs(v), casas)


def texto_aposta(ap, res, placar, gratis=False):
    liga = NOME_LIGA.get(ap["l"], "")
    jogo = f"{ap['jogo']}{f' ({liga})' if liga else ''}: {ap['sel']} a {odd_txt(ap['o'])} na {ap['c']}; justa {odd_txt(1 / ap['p'])}"
    if gratis:
        e = ev_gratis(ap["st"], ap["o"], ap["p"])
        base = (f"Aposta grátis da semana — {jogo}; vale em média {reais(e)} "
                f"({pct_br(e / ap['st'], 0)} dos {reais(ap['st'])}).")
    else:
        base = f"{jogo}; valor de {pct_sinal(ap['v'])}."
    if res > 0:
        fim = f" Ganhou: {reais(res, True)}"
    elif gratis:
        fim = " Não deu (a aposta grátis não custa nada)"
    else:
        fim = f" Perdeu: {reais(res, True)}"
    return base + fim + f" ({placar[0]} × {placar[1]})."


# ---------------------------------------------------------------------------------------------------- planilhas
def _hora_uk(d: dt.date, hm: str):
    """Data e hora do Reino Unido → ms UTC (horário de verão do último domingo de março ao de outubro)."""
    try:
        h, m = (int(x) for x in (hm or "15:00").strip().split(":")[:2])
    except ValueError:
        h, m = 15, 0
    t = dt.datetime(d.year, d.month, d.day, h, m, tzinfo=dt.timezone.utc)

    def ultimo_domingo(mes):
        x = dt.date(d.year, mes, 31)
        return x - dt.timedelta(days=(x.weekday() + 1) % 7)
    verao = ultimo_domingo(3) <= d < ultimo_domingo(10)
    return int(t.timestamp() * 1000) - (HORA if verao else 0)


def _data(s):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _pegar(linha, grupos):
    """(rótulo, odds) do primeiro grupo de colunas presente com todas as odds > 1."""
    for rot, cols in grupos:
        vs = [_f(linha.get(c)) for c in cols]
        if all(v is not None and v > 1 for v in vs):
            return rot, vs
    return None, None


def _campo(linha, *nomes):
    for n in nomes:
        v = linha.get(n)
        if v not in (None, ""):
            return str(v).strip()
    return None


def ler_planilha(texto, liga, desde=0, ate=None):
    """Os jogos de uma planilha do football-data: lista de jogos no formato do motor (ver `nova_aposta`)."""
    texto = texto.lstrip("﻿")
    leitor = csv.DictReader(io.StringIO(texto))
    if not leitor.fieldnames:
        return []
    leitor.fieldnames = [(c or "").strip().lstrip("﻿") for c in leitor.fieldnames]
    nova = "HomeTeam" not in leitor.fieldnames and "Home" in leitor.fieldnames
    out = []
    for ln in leitor:
        casa, fora = _campo(ln, "HomeTeam", "Home", "HT"), _campo(ln, "AwayTeam", "Away", "AT")
        gc, gf = _f(_campo(ln, "FTHG", "HG")), _f(_campo(ln, "FTAG", "AG"))
        d = _data(_campo(ln, "Date"))
        if not casa or not fora or gc is None or gf is None or d is None:
            continue
        ini = _hora_uk(d, _campo(ln, "Time"))
        if ini < desde or (ate is not None and ini > ate):
            continue
        j = {"id": f"{liga}-{d.isoformat()}-{_norm(casa)}-{_norm(fora)}", "liga": liga, "casa": casa, "fora": fora,
             "inicio": ini, "placar": [int(gc), int(gf)], "mk": {}, "fech": not nova}
        if nova:
            grupos = [("1x2", SOFT_NOVA, JUSTA_NOVA, None)]
        else:
            grupos = [("1x2", SOFT_1X2, JUSTA_1X2, FECH_1X2), ("ou", SOFT_OU, JUSTA_OU, FECH_OU)]
        for mk, gs, gj, gfch in grupos:
            rs, so = _pegar(ln, gs)
            rj, jo = _pegar(ln, gj)
            if not so or not jo:
                continue
            p = sem_margem(jo)
            if not p:
                continue
            pf = None
            rf = None
            if gfch:
                rf, fo = _pegar(ln, gfch)
                pf = sem_margem(fo) if fo else None
            j["mk"][mk] = {"o": so, "p": p, "pf": pf}
            if mk == "1x2":
                j["soft"], j["justa"], j["fechJusta"] = rs, rj, rf
        if j["mk"].get("1x2"):
            out.append(j)
    return out


def temporadas(agora, n=HIST_TEMPORADAS):
    """Os códigos das últimas `n` temporadas europeias ("2425"…) e o início (ms) da mais antiga."""
    d = dt.datetime.fromtimestamp(agora / 1000, dt.timezone.utc)
    atual = d.year if d.month >= 7 else d.year - 1
    anos = list(range(atual - n + 1, atual + 1))
    ini = int(dt.datetime(anos[0], 7, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    return [f"{a % 100:02d}{(a + 1) % 100:02d}" for a in anos], ini


def baixar_passado(fonte, agora, log, erros):
    """Baixa as planilhas e devolve (jogos, informações). Levanta odds.Erro se nenhuma planilha veio."""
    temps, ini = temporadas(agora)
    jogos, ok, falhas = [], 0, []
    for chave, _nome, div, _espn in LIGAS:
        if not div:
            continue
        if div in PLANILHAS_NOVAS:
            urls = [URL_FD_NOVA.format(pais=div)]
        else:
            urls = [URL_FD.format(temp=t, div=div) for t in temps]
        for url in urls:
            try:
                txt = fonte.texto(url, "csv")
                lista = ler_planilha(txt, chave, ini, agora)
                jogos.extend(lista)
                ok += 1
            except ERROS_API as e:
                # a temporada que ainda não começou dá 404: não é erro
                if getattr(e, "status", None) == 404 and url.endswith(f"{temps[-1]}/{div}.csv"):
                    continue
                falhas.append(f"{url.split('/')[-2]}/{url.split('/')[-1]}: {e}")
    if not ok:
        raise odds.Erro("nenhuma planilha do football-data veio: " + "; ".join(falhas[:3]))
    for f in falhas:
        erros.append(f"planilha {f}")
        log(f"  apostas: planilha {f}")
    # o mesmo jogo duas vezes (planilhas repetidas): fica um
    vistos, unicos = set(), []
    for j in sorted(jogos, key=lambda x: x["inicio"]):
        if j["id"] not in vistos:
            vistos.add(j["id"])
            unicos.append(j)
    n = len(unicos) or 1
    info = {"jogos": len(unicos), "planilhas": ok, "temporadas": temps,
            "porLiga": {k: sum(1 for j in unicos if j["liga"] == k) for k, *_ in LIGAS if any(j["liga"] == k for j in unicos)},
            "justaPinnacle": round(sum(1 for j in unicos if j.get("justa") == PINNACLE) / n, 3),
            "fechamentoPinnacle": round(sum(1 for j in unicos if j.get("fechJusta") == PINNACLE) / n, 3),
            "casaBet365": round(sum(1 for j in unicos if j.get("soft") == BET365) / n, 3),
            "comGols": round(sum(1 for j in unicos if "ou" in j["mk"]) / n, 3),
            "fonte": "football-data.co.uk"}
    return unicos, info


def preencher(curva, ate):
    """Um ponto por dia na série (os dias sem aposta repetem o anterior), do início até `ate`."""
    d = dt.date.fromisoformat(dia_de(curva.inicio))
    fim = dt.date.fromisoformat(dia_de(ate))
    ultimo = curva.capital
    while d <= fim:
        k = d.isoformat()
        if k in curva.serie:
            ultimo = curva.serie[k]
        else:
            curva.serie[k] = round(ultimo, 4)
        d += dt.timedelta(days=1)


def simular_passado(jogos, ini, fim):
    """Todas as versões nos jogos do passado (contas novas). Devolve id → conta (resumo)."""
    jogos = sorted(jogos, key=lambda j: j["inicio"])
    contas = {cfg[0]: Conta(cfg, ini) for cfg in VERSOES}
    for c in contas.values():
        c.curva.marcar(ini, c.curva.capital)
    for j in jogos:
        t = j["inicio"] + 2 * HORA
        for c in contas.values():
            if c.gratis:
                continue
            for ap in c.decidir(j):
                c.abrir(ap)
                c.liquidar(ap, j["placar"], t)
            c.marcar(t)
    g = next(c for c in contas.values() if c.gratis)
    semanas = {}
    for j in jogos:
        semanas.setdefault(semana_de(j["inicio"]), []).append(j)
    for s in sorted(semanas):
        m = melhor_gratis(semanas[s])
        if not m:
            continue
        _e, j, mk, i = m
        ap = nova_aposta(j, mk, i, GRATIS_VALOR, gratis=True)
        g.abrir(ap)
        g.liquidar(ap, j["placar"], j["inicio"] + 2 * HORA)
    out = {}
    for vid, c in contas.items():
        preencher(c.curva, fim)
        c.extra()
        out[vid] = c.curva.resumo(de=dia_de(ini), ate=dia_de(fim), aproximado=False,
                                  nota="A casa é a Bet365, no lugar da Betano (que não está nas planilhas do "
                                       "football-data); no Brasileirão a aposta é feita no fechamento.")
    return out


# ---------------------------------------------------------------------------------------------------- OddsPapi: leitura
def _ms(x):
    """Instante em ms de um número (s ou ms) ou de um texto ISO; None se não der."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        v = float(x)
        if v > 1e14:
            return int(v / 1000)  # microssegundos
        return int(v) if v > 1e11 else int(v * 1000)
    s = str(x).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return _ms(float(s))
    try:
        s2 = s.replace("Z", "+00:00").replace(" ", "T")
        s2 = re.sub(r"\.(\d{1,6})\d*", r".\1", s2)
        d = dt.datetime.fromisoformat(s2)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp() * 1000)
    except ValueError:
        return None


def _lista(r, *chaves):
    """A lista de itens de uma resposta (lista pura ou {"data": […]} etc.)."""
    if isinstance(r, list):
        return r
    if isinstance(r, dict):
        for k in chaves + ("data", "items", "results", "response", "fixtures", "tournaments", "sports"):
            if isinstance(r.get(k), list):
                return r[k]
        # {"<id>": {...}, …}
        vs = list(r.values())
        if vs and all(isinstance(v, dict) for v in vs):
            return vs
    return []


def _pega(d, *nomes):
    """O primeiro campo presente (aceita dict com "name")."""
    if not isinstance(d, dict):
        return None
    for n in nomes:
        v = d.get(n)
        if isinstance(v, dict):
            v = v.get("name") or v.get("slug") or v.get("id")
        if v not in (None, ""):
            return v
    return None


def estrutura(x, prof=3):
    """As chaves de uma resposta (sem valores), para conferir o formato na primeira rodada de verdade."""
    if prof <= 0:
        return "…"
    if isinstance(x, dict):
        ks = list(x)[:8]
        return {str(k): estrutura(x[k], prof - 1) for k in ks}
    if isinstance(x, list):
        return [estrutura(x[0], prof - 1)] if x else []
    return type(x).__name__


TORNEIOS = {
    # países (categoria), frases do nome, palavras que excluem, frase que basta sem país
    "bra": (["brazil", "brasil"], ["serie a", "brasileirao", "brasileiro"], ["b", "c", "d", "women", "feminino", "u20",
            "copa", "paulista", "carioca", "gaucho", "mineiro", "u23", "sub"], "brasileir"),
    "eng": (["england"], ["premier league"], ["2", "women", "u21", "u18", "cup", "summer", "international"], None),
    "esp": (["spain"], ["laliga", "la liga", "primera division"], ["2", "women", "femenina", "f", "segunda", "rfef"], None),
    "ita": (["italy"], ["serie a"], ["women", "femminile", "b", "c", "primavera"], "ital"),
    "ger": (["germany"], ["bundesliga"], ["2", "3", "women", "frauen", "austria", "osterreich"], None),
    "fra": (["france"], ["ligue 1"], ["women", "feminine", "d1"], None),
    "lib": ([], ["libertadores"], ["women", "femenina", "femenino", "u20", "sub"], "libertadores"),
}


def bate_torneio(chave, nome, categoria):
    paises, frases, fora, sozinha = TORNEIOS[chave]
    n, c = _norm(nome), _norm(categoria)
    palavras = set(n.split())
    if not any(f in n for f in frases) or palavras & set(fora):
        return False
    if not paises:
        return True
    if c:
        return any(p in c for p in paises) or any(p in n for p in paises)
    return bool(sozinha and sozinha in n)


def _no_da_casa(r, slug):
    """O pedaço da resposta de uma casa (`slug`), em qualquer profundidade."""
    pilha, n = [r], 0
    while pilha and n < 20000:
        x = pilha.pop()
        n += 1
        if isinstance(x, dict):
            for k, v in x.items():
                if str(k).lower() == slug and isinstance(v, (dict, list)):
                    return v
            nome = x.get("bookmaker") or x.get("bookmakerSlug") or x.get("slug")
            if isinstance(nome, str) and nome.lower() == slug:
                return x
            pilha.extend(v for v in x.values() if isinstance(v, (dict, list)))
        elif isinstance(x, list):
            pilha.extend(v for v in x if isinstance(v, (dict, list)))
    return None


CAMPOS_PRECO = ("price", "odds", "decimalOdds", "odd")
CAMPOS_HORA = ("createdAt", "changedAt", "updatedAt", "timestamp", "time", "ts", "t", "lastUpdate", "date")


def _precos(x):
    """[(ms, preço)] de qualquer lugar dentro de `x` (lista de mudanças ou um preço só), em ordem."""
    out, pilha = [], [x]
    while pilha:
        y = pilha.pop()
        if isinstance(y, dict):
            pr = next((_f(y[k]) for k in CAMPOS_PRECO if k in y and not isinstance(y[k], (dict, list))), None)
            if pr is not None and pr > 1:
                t = next((_ms(y[k]) for k in CAMPOS_HORA if k in y), None)
                if t is not None:
                    out.append((t, pr))
                    continue
            pilha.extend(v for v in y.values() if isinstance(v, (dict, list)))
        elif isinstance(y, list):
            pilha.extend(v for v in y if isinstance(v, (dict, list)))
    return sorted(set(out))


NOMES_1X2 = {"1x2", "full time result", "fulltime result", "match result", "match winner", "1x2 full time",
             "resultado final", "three way", "3 way", "moneyline 3 way"}
NOMES_TOTAL = ("over under", "over/under", "total goals", "totals", "total", "goals over under", "gols")


def _itens(d):
    """(chave, valor) de um dict ou de uma lista de dicts com id."""
    if isinstance(d, dict):
        return [(str(k), v) for k, v in d.items() if isinstance(v, (dict, list))]
    if isinstance(d, list):
        return [(str(_pega(v, "marketId", "outcomeId", "id") or i), v) for i, v in enumerate(d) if isinstance(v, dict)]
    return []


def _linha(d):
    for k in ("handicap", "line", "points", "total", "hdp"):
        v = _f(d.get(k)) if isinstance(d, dict) else None
        if v is not None:
            return v
    return None


def mercados(no):
    """{"1x2": [hist casa, hist empate, hist fora], "ou": [hist mais, hist menos]} de uma casa; hist = [(ms, preço)]."""
    if not isinstance(no, (dict, list)):
        return {}
    mk = no.get("markets") if isinstance(no, dict) and isinstance(no.get("markets"), (dict, list)) else no
    out = {}
    for mid, m in _itens(mk):
        if not isinstance(m, dict):
            continue
        nome = _norm(_pega(m, "marketName", "name", "market") or "")
        outs = m.get("outcomes") if isinstance(m.get("outcomes"), (dict, list)) else None
        if outs is None:
            continue
        if "1x2" not in out and (mid == "101" or nome in NOMES_1X2):
            h = [None, None, None]
            for oid, o in _itens(outs):
                on = _norm(_pega(o, "outcomeName", "name", "label") or "") if isinstance(o, dict) else ""
                i = {"101": 0, "102": 1, "103": 2}.get(oid)
                if i is None:
                    i = 0 if on in ("1", "home", "casa") else 1 if on in ("x", "draw", "empate") else 2 if on in ("2", "away", "fora") else None
                if i is not None:
                    h[i] = _precos(o)
            if all(h):
                out["1x2"] = h
        elif "ou" not in out and any(t in nome for t in NOMES_TOTAL) and "corner" not in nome and "card" not in nome \
                and "half" not in nome and "1st" not in nome:
            linha = _linha(m)
            if linha is None and "2 5" in nome:
                linha = 2.5
            h = [None, None]
            for _oid, o in _itens(outs):
                if not isinstance(o, dict):
                    continue
                lo = _linha(o)
                if (lo if lo is not None else linha) != 2.5:
                    continue
                on = _norm(_pega(o, "outcomeName", "name", "label") or "")
                i = 0 if on.startswith(("over", "mais", "acima")) else 1 if on.startswith(("under", "menos", "abaixo")) else None
                if i is not None:
                    h[i] = _precos(o)
            if all(h):
                out["ou"] = h
    return out


def preco_em(hist, t):
    """O último preço publicado até `t` (ms), ou None."""
    melhor = None
    for ts, p in hist or []:
        if ts <= t:
            melhor = p
        else:
            break
    return melhor


def jogo_vivo(fx, pin, soft, rotulo):
    """O jogo no formato do motor a partir dos históricos da Pinnacle e da casa comum, olhando só o que existia 6 h
    antes (ou até 1 h antes). None se não houver preço que sirva."""
    ini = fx["i"]
    j = {"id": fx["id"], "liga": fx["l"], "casa": fx["c"], "fora": fx["f"], "inicio": ini, "mk": {}, "soft": rotulo}
    for mk in ("1x2", "ou"):
        ph, sh = pin.get(mk), soft.get(mk)
        if not ph or not sh:
            continue
        for t in (ini - ANTES_H * HORA, ini - ULTIMO_H * HORA):
            po = [preco_em(h, t) for h in ph]
            so = [preco_em(h, t) for h in sh]
            if all(po) and any(so):
                break
        else:
            continue
        p = sem_margem(po)
        if not p:
            continue
        fo = [preco_em(h, ini) for h in ph]
        j["mk"][mk] = {"o": so, "p": p, "pf": sem_margem(fo) if all(fo) else None, "t": t}
    return j if j["mk"].get("1x2") else None


def _placar(x, prof=4):
    """(gols da casa, gols de fora) de um jogo, se a resposta trouxer; aceita vários formatos."""
    if prof <= 0 or not isinstance(x, (dict, list)):
        return None
    if isinstance(x, dict):
        pares = [("participant1Score", "participant2Score"), ("homeScore", "awayScore"), ("home_score", "away_score"),
                 ("participant1", "participant2"), ("home", "away"), ("p1", "p2")]
        for a, b in pares:
            va, vb = x.get(a), x.get(b)
            if not isinstance(va, (dict, list)) and not isinstance(vb, (dict, list)):
                fa, fb = _f(va), _f(vb)
                if fa is not None and fb is not None and fa >= 0 and fb >= 0 and fa == int(fa) and fb == int(fb):
                    return [int(fa), int(fb)]
        for k in ("score", "result", "ft", "fullTime", "fulltime", "final"):
            v = x.get(k)
            if isinstance(v, str):
                m = re.fullmatch(r"\s*(\d+)\s*[-:x×]\s*(\d+)\s*", v)
                if m:
                    return [int(m.group(1)), int(m.group(2))]
        for k in ("scores", "fullTime", "fulltime", "ft", "final", "score", "result", "period0", "regular"):
            v = x.get(k)
            if isinstance(v, (dict, list)):
                r = _placar(v, prof - 1)
                if r:
                    return r
    return None


# ---------------------------------------------------------------------------------------------------- nomes dos times
APELIDOS = {"man utd": "manchester united", "man united": "manchester united", "man city": "manchester city",
            "nott m forest": "nottingham forest", "nottm forest": "nottingham forest", "spurs": "tottenham",
            "wolves": "wolverhampton", "inter": "internazionale", "psg": "paris saint germain",
            "paris sg": "paris saint germain", "ath madrid": "atletico madrid", "ath bilbao": "athletic bilbao",
            "sp lisbon": "sporting", "atletico mg": "atletico mineiro", "athletico pr": "athletico paranaense"}
SOBRA = {"fc", "cf", "ec", "sc", "ac", "afc", "cr", "se", "club", "clube", "de", "da", "do", "the", "ca", "cd", "ss",
         "as", "us", "rc", "sv", "vfb", "vfl", "tsg", "fk", "sk", "esporte", "futebol", "football", "calcio", "1"}


def _tokens(n):
    s = _norm(n)
    s = APELIDOS.get(s, s)
    return [t for t in s.split() if t not in SOBRA] or s.split()


def mesmo_time(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False

    def casa(x, y):
        return x == y or (min(len(x), len(y)) >= 2 and (x.startswith(y) or y.startswith(x)))
    batem = sum(1 for x in ta if any(casa(x, y) for y in tb))
    menor = min(len(ta), len(tb))
    return batem >= min(2, menor) and batem / menor >= 0.5  # "Man City" × "Manchester United" não bate


def jogos_espn(r):
    """[(ms, casa, fora, gols casa, gols fora, terminou)] do placar da ESPN."""
    out = []
    for e in (r or {}).get("events") or []:
        try:
            comp = (e.get("competitions") or [{}])[0]
            st = ((comp.get("status") or e.get("status") or {}).get("type") or {})
            terminou = bool(st.get("completed")) or st.get("state") == "post"
            lados = {c.get("homeAway"): c for c in comp.get("competitors") or []}
            h, a = lados.get("home"), lados.get("away")
            if not h or not a:
                continue

            def nome(c):
                tm = c.get("team") or {}
                return tm.get("displayName") or tm.get("name") or tm.get("shortDisplayName") or ""
            out.append((_ms(e.get("date") or comp.get("date")), nome(h), nome(a), _f(h.get("score")), _f(a.get("score")), terminou))
        except (AttributeError, TypeError, IndexError):
            continue
    return out


# ---------------------------------------------------------------------------------------------------- OddsPapi: orçamento
class Esgotado(Exception):
    pass


PARAR = (401, 402, 403, 429)  # chave recusada, plano ou limite: para o ao vivo nesta rodada


class Orcamento:
    """Os pedidos à OddsPapi no mês (calendário UTC), guardados no estado. Para em 90% do limite gratuito."""

    def __init__(self, fonte, V, agora):
        self.fonte, self.V, self.agora = fonte, V, agora
        mes = dia_de(agora)[:7]
        if V.get("mes") != mes:
            V["mes"], V["usados"] = mes, 0
        self.feitos = 0

    def limite(self):
        return int(ORCAMENTO_MES * PARAR_EM)

    def livre(self):
        return self.limite() - int(self.V.get("usados", 0))

    def pedir(self, caminho, **params):
        if self.livre() <= 0:
            raise Esgotado()
        cont = getattr(self.fonte, "contagem", None)
        antes = cont["oddspapi"] if cont is not None else None
        try:
            return self.fonte.oddspapi(caminho, **params)
        finally:
            gasto = (cont["oddspapi"] - antes) if cont is not None else 1
            gasto = max(1, gasto)
            self.V["usados"] = int(self.V.get("usados", 0)) + gasto
            self.feitos += gasto

    def dias_restantes(self):
        d = dt.date.fromisoformat(dia_de(self.agora))
        prox = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return (prox - d).days

    def cota_do_dia(self, ligas_ativas):
        """Jogos que ainda cabem por dia: o que sobra do mês (menos as listas de jogos que ainda virão) ÷ dias."""
        dias = self.dias_restantes()
        reserva = ligas_ativas * math.ceil(dias / (FX_CADA / DIA))
        sobra = self.livre() - reserva
        return max(0, min(MAX_POR_DIA, sobra // max(1, dias)))


# ---------------------------------------------------------------------------------------------------- ao vivo
def _iso(ms, so_dia=False):
    d = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    return d.strftime("%Y-%m-%d") if so_dia else d.strftime("%Y-%m-%dT%H:%M:%SZ")


class Vivo:
    """O acompanhamento ao vivo pela OddsPapi (só com a chave)."""

    def __init__(self, fonte, V, agora, contas, ev, evdia, log, erros):
        self.fonte, self.V, self.agora, self.contas, self.ev, self.evdia = fonte, V, agora, contas, ev, evdia
        self.log, self.erros = log, erros
        self.orc = Orcamento(fonte, V, agora)
        for k, pad in (("fx", {}), ("fxEm", {}), ("fxAte", {}), ("fxVazio", {}), ("porDia", {}), ("gratis", {}),
                       ("soft", {"vazios": {}, "descartadas": {}, "usada": None}), ("pulados", 0), ("semOdds", 0)):
            V.setdefault(k, copy.deepcopy(pad))
        self.espn_cache, self.espn_pedidos = {}, 0

    # ------------------------------------------------------------------ campeonatos
    def torneios(self):
        V = self.V
        cada = TORNEIOS_CADA if V.get("torneios") else DIA  # nada achado: tenta de novo só amanhã (o limite é curto)
        if self.agora - int(V.get("torneiosEm") or 0) < cada:
            return
        esporte = V.get("esporte") or ESPORTE_PADRAO
        r = self.orc.pedir("/tournaments", sportId=esporte)
        lista = _lista(r)
        if not lista and not V.get("esporte"):
            rs = self.orc.pedir("/sports")
            for s in _lista(rs):
                nome = _norm(_pega(s, "sportName", "name", "slug") or "")
                if nome in ("soccer", "football", "futebol") or nome.startswith("soccer"):
                    esporte = _pega(s, "sportId", "id")
                    break
            if esporte != ESPORTE_PADRAO:
                lista = _lista(self.orc.pedir("/tournaments", sportId=esporte))
        if lista:
            self.log(f"  apostas: formato de /tournaments: {estrutura(lista[0], 2)}")
        achados = {}
        for t in lista:
            if not isinstance(t, dict):
                continue
            nome = _pega(t, "tournamentName", "name", "slug") or ""
            cat = _pega(t, "categoryName", "category", "countryName", "country", "categorySlug") or ""
            tid = _pega(t, "tournamentId", "id")
            if tid is None:
                continue
            for chave in TORNEIOS:
                if chave not in achados and bate_torneio(chave, nome, cat):
                    achados[chave] = {"id": tid, "nome": str(nome)}
        V["esporte"] = esporte
        V["torneios"] = achados
        V["torneiosEm"] = self.agora
        faltam = [NOME_LIGA[k] for k in TORNEIOS if k not in achados]
        if faltam:
            self.log(f"  apostas: campeonatos não achados na OddsPapi: {', '.join(faltam)}")

    # ------------------------------------------------------------------ jogos
    def jogos(self):
        V = self.V
        for chave, *_ in LIGAS:
            tor = (V.get("torneios") or {}).get(chave)
            if not tor:
                continue
            ultimo = int(V["fxEm"].get(chave) or 0)
            cada = FX_VAZIO_CADA if V["fxVazio"].get(chave) else FX_CADA
            if self.agora - ultimo < cada:
                continue
            de = max(self.agora - 7 * DIA, min(self.agora - DIA, int(V["fxAte"].get(chave) or self.agora - DIA)))
            ate = self.agora + FX_DEPOIS
            so_dia = V.get("fmtData") == "dia"
            try:
                try:
                    r = self.orc.pedir("/fixtures", tournamentId=tor["id"], **{"from": _iso(de, so_dia), "to": _iso(ate, so_dia)})
                except ERROS_API as e:
                    if getattr(e, "status", None) not in (400, 422) or so_dia:
                        raise
                    V["fmtData"] = "dia"  # a data com hora foi recusada: tenta só o dia (e fica assim)
                    r = self.orc.pedir("/fixtures", tournamentId=tor["id"], **{"from": _iso(de, True), "to": _iso(ate, True)})
            except ERROS_API as e:
                if getattr(e, "status", None) in PARAR:
                    raise
                V["fxEm"][chave] = self.agora - cada + 6 * HORA  # tenta de novo daqui a ~6 h
                self.erros.append(f"lista de jogos ({NOME_LIGA[chave]}): {e}")
                continue
            lista = [x for x in _lista(r) if isinstance(x, dict)]
            if lista and not V.get("viuFixture"):
                self.log(f"  apostas: formato de /fixtures: {estrutura(lista[0], 2)}")
                V["viuFixture"] = True
            novos = 0
            for x in lista:
                fid = _pega(x, "fixtureId", "id")
                ini = _ms(_pega(x, "startTime", "start_time", "startDate", "commence_time", "date", "kickoff"))
                casa = _pega(x, "participant1Name", "homeTeam", "home", "homeName", "participant1")
                fora = _pega(x, "participant2Name", "awayTeam", "away", "awayName", "participant2")
                if fid is None or ini is None or not casa or not fora:
                    continue
                fid = str(fid)
                reg = V["fx"].get(fid)
                if not reg:
                    reg = V["fx"][fid] = {"id": fid, "l": chave, "c": str(casa), "f": str(fora), "i": ini, "st": "novo", "p": None}
                    novos += 1
                reg["i"] = ini
                if ini + 2 * HORA <= self.agora and not reg.get("p"):
                    pl = _placar(x)
                    if pl:
                        reg["p"] = pl
            V["fxEm"][chave] = self.agora
            V["fxAte"][chave] = ate
            V["fxVazio"][chave] = not lista
            self.log(f"  apostas: {NOME_LIGA[chave]}: {len(lista)} jogos na lista ({novos} novos)")

    # ------------------------------------------------------------------ casas
    def softs(self):
        S = self.V["soft"]
        out = []
        for s in SOFTS:
            desc = S["descartadas"].get(s)
            if desc and self.agora - int(desc) < RETESTAR:
                continue
            if desc:  # volta a testar
                S["descartadas"].pop(s, None)
                S["vazios"][s] = VAZIOS_PARA_DESCARTAR - 2
            out.append(s)
            if len(out) == 2:
                break
        return out or ["betano"]

    def _anotar_soft(self, pedidas, dados):
        S = self.V["soft"]
        for s in pedidas:
            if dados.get(s):
                S["vazios"][s] = 0
            else:
                S["vazios"][s] = int(S["vazios"].get(s, 0)) + 1
                if S["vazios"][s] >= VAZIOS_PARA_DESCARTAR and s not in S["descartadas"]:
                    S["descartadas"][s] = self.agora
                    prox = next((x for x in SOFTS if x != s and x not in S["descartadas"]), None)
                    txt = (f"A {NOME_SOFT[s]} ({s}) veio sem odds em {VAZIOS_PARA_DESCARTAR} jogos seguidos"
                           + (" (as apostas estão suspensas no Brasil)" if s.endswith(".br") else "")
                           + (f"; o papel passa a usar a {NOME_SOFT[prox]} ({prox})." if prox else "."))
                    self.ev.add(self.agora, "aviso", txt, None)
                    self.log(f"  apostas: {txt}")

    # ------------------------------------------------------------------ jogos terminados
    def processar(self):
        V = self.V
        fx = V["fx"]
        prontos = [f for f in fx.values() if f.get("st") == "novo" and f["i"] + FIM_JOGO <= self.agora]
        # jogos velhos demais, ou cuja aposta (6 h antes) seria antes de a conta existir, ficam de fora
        comeco = int(V.get("inicio") or 0)
        for f in prontos:
            if f["i"] < self.agora - 20 * DIA:
                f["st"] = "velho"
            elif f["i"] - ANTES_H * HORA < comeco:
                f["st"] = "antes"
        prontos = [f for f in prontos if f["st"] == "novo"]
        if self.agora < int(V.get("pausaAte") or 0):
            return
        ativas = max(1, sum(1 for k in (V.get("torneios") or {}) if not V["fxVazio"].get(k)))
        dias = {}
        for f in prontos:
            dias.setdefault(dia_de(f["i"]), []).append(f)
        for d in sorted(dias):
            lista = sorted(dias[d], key=lambda f: (PRIORIDADE.get(f["l"], 99), f["i"]))
            for f in lista:
                feitos = int(V["porDia"].get(d, 0))
                if feitos >= self.orc.cota_do_dia(ativas):
                    f["st"] = "pulado"
                    V["pulados"] = int(V.get("pulados", 0)) + 1
                    continue
                pedidas = self.softs()
                try:
                    r = self.orc.pedir("/historical-odds", fixtureId=f["id"], bookmakers=",".join(["pinnacle"] + pedidas))
                except ERROS_API as e:
                    if getattr(e, "status", None) in PARAR:
                        raise
                    f["tent"] = int(f.get("tent", 0)) + 1
                    if f["tent"] >= 2:
                        f["st"] = "erro"
                    self.erros.append(f"odds de {f['c']} × {f['f']}: {e}")
                    continue
                V["porDia"][d] = feitos + 1
                if not V.get("viuHistorico"):
                    self.log(f"  apostas: formato de /historical-odds: {estrutura(r, 8)}")
                    V["viuHistorico"] = True
                pin = mercados(_no_da_casa(r, "pinnacle"))
                dados = {s: mercados(_no_da_casa(r, s)) for s in pedidas}
                self._anotar_soft(pedidas, dados)
                usada = next((s for s in pedidas if dados[s].get("1x2")), None)
                f["st"] = "feito"
                V["seguidos"] = 0 if pin.get("1x2") else int(V.get("seguidos", 0)) + 1
                if V["seguidos"] >= SEM_PINNACLE_PAUSA:
                    # provavelmente o formato da resposta não é o que o papel entende: para de gastar o limite
                    V["pausaAte"], V["seguidos"] = self.agora + 3 * DIA, 0
                    msg = (f"{SEM_PINNACLE_PAUSA} jogos seguidos sem odds da Pinnacle que o papel entenda; o ao vivo "
                           f"pausa 3 dias (formato recebido: {estrutura(r, 8)})")
                    self.erros.append(msg[:900])
                    self.log(f"  apostas: {msg}")
                    self.ev.add(self.agora, "aviso", "O ao vivo pausou 3 dias: as odds chegaram num formato que o papel "
                                                     "não entendeu.", None)
                    return
                if not pin.get("1x2") or not usada:
                    V["semOdds"] = int(V.get("semOdds", 0)) + 1
                    f["st"] = "semOdds"
                    continue
                V["soft"]["usada"] = usada
                j = jogo_vivo(f, pin, dados[usada], NOME_SOFT[usada])
                if not j:
                    V["semOdds"] = int(V.get("semOdds", 0)) + 1
                    f["st"] = "semOdds"
                    continue
                for c in self.contas.values():
                    if c.gratis:
                        continue
                    for ap in c.decidir(j):
                        c.abrir(ap)
                m = melhor_gratis([j])
                if m:
                    _e, jj, mk, i = m
                    sem = str(semana_de(j["inicio"]))
                    V["gratis"].setdefault(sem, []).append({"e": round(_e, 5), "ap": nova_aposta(jj, mk, i, GRATIS_VALOR, True)})

    # ------------------------------------------------------------------ aposta grátis
    def gratis_da_semana(self):
        G = self.V["gratis"]
        c = next((c for c in self.contas.values() if c.gratis), None)
        for sem in sorted(G, key=int):
            ini = int(sem)
            if self.agora < ini + 7 * DIA + 12 * HORA:
                continue
            cands = G.pop(sem)
            if c is None or ini + 7 * DIA <= c.curva.inicio:
                continue
            if cands:
                melhor = max(cands, key=lambda x: x["e"])
                c.abrir(melhor["ap"])

    # ------------------------------------------------------------------ placares
    def _espn(self, liga, ini):
        cod = next((e for k, _n, _d, e in LIGAS if k == liga), None)
        if not cod:
            return []
        dias = {_iso(ini, True).replace("-", ""), dia_de(ini).replace("-", "")}
        out = []
        for d in sorted(dias):
            k = (cod, d)
            if k not in self.espn_cache:
                if self.espn_pedidos >= ESPN_MAX:
                    continue
                self.espn_pedidos += 1
                try:
                    self.espn_cache[k] = jogos_espn(self.fonte.json_url(URL_ESPN.format(liga=cod, dia=d), "espn"))
                except ERROS_API as e:
                    self.espn_cache[k] = []
                    self.erros.append(f"placar da ESPN ({cod} {d}): {e}")
            out.extend(self.espn_cache[k])
        return out

    def placar(self, ap):
        f = self.V["fx"].get(ap["j"])
        if f and f.get("p"):
            return f["p"]
        if ap["i"] + FIM_JOGO > self.agora:
            return None
        for t, casa, fora, gc, gf, terminou in self._espn(ap["l"], ap["i"]):
            if not terminou or gc is None or gf is None or t is None or abs(t - ap["i"]) > 6 * HORA:
                continue
            nomes = ap["jogo"].split(" × ")
            if len(nomes) == 2 and mesmo_time(nomes[0], casa) and mesmo_time(nomes[1], fora):
                pl = [int(gc), int(gf)]
                if f:
                    f["p"] = pl
                return pl
        return None

    def liquidar(self):
        pend = sorted(((c, ap) for c in self.contas.values() for ap in c.abertas), key=lambda x: x[1]["i"])
        for c, ap in pend:
            pl = self.placar(ap)
            t = max(ap["i"] + 2 * HORA, c.curva.t)
            if pl:
                res = c.liquidar(ap, pl, t, self.ev)
                if c.id == PADRAO or c.gratis:
                    d = dia_de(ap["i"])
                    if c.gratis or self.evdia.get(d, 0) < EV_POR_DIA:
                        if not c.gratis:
                            self.evdia[d] = self.evdia.get(d, 0) + 1
                        self.ev.add(t, "ganhou" if res > 0 else "perdeu", texto_aposta(ap, res, pl, c.gratis), c.id)
            elif ap["i"] < self.agora - ANULAR_DIAS * DIA:
                c.liquidar(ap, None, t, self.ev, anular=True)

    def limpar(self):
        V = self.V
        corte = self.agora - 25 * DIA
        abertas = {ap["j"] for c in self.contas.values() for ap in c.abertas}
        for fid in [k for k, f in V["fx"].items() if f["i"] < corte and k not in abertas]:
            del V["fx"][fid]
        d0 = dia_de(self.agora - 40 * DIA)
        for d in [d for d in V["porDia"] if d < d0]:
            del V["porDia"][d]

    def rodar(self):
        try:
            self.torneios()
            self.jogos()
            self.processar()
        except Esgotado:
            self.log(f"  apostas: limite do mês da OddsPapi alcançado ({self.V.get('usados')} de {ORCAMENTO_MES}); "
                     "o ao vivo espera o mês que vem")
        except ERROS_API as e:
            st = getattr(e, "status", None)
            if st in (401, 402, 403):
                msg = f"OddsPapi recusou a chave ({e}); confira o segredo ODDSPAPI_KEY"
            elif st == 429:
                msg = f"OddsPapi pediu para esperar ({e}); o ao vivo continua na próxima rodada"
            else:
                msg = f"OddsPapi: {e}"
            self.erros.append(msg)
            self.log(f"  apostas: {msg}")
        except Exception as e:  # noqa: BLE001  (um formato inesperado não pode perder o que já foi gasto do mês)
            self.erros.append(f"ao vivo: {type(e).__name__}: {e}")
            self.log(f"  apostas: ao vivo: {type(e).__name__}: {e}")
        self.gratis_da_semana()
        self.liquidar()
        self.limpar()


# ---------------------------------------------------------------------------------------------------- a rodada
def fonte_de(ctx):
    """De onde vêm os dados: o próprio cliente (falso com o mixin de falso_apostas), o falso avulso nos exemplos ou o
    cliente de verdade (odds.py, a chave só da variável de ambiente)."""
    cli = ctx.cli
    if hasattr(cli, "oddspapi") and hasattr(cli, "texto"):
        return cli
    if getattr(ctx, "exemplo", False):
        import falso_apostas
        return falso_apostas.Avulsa(cli)
    return odds.Cliente(chave=os.environ.get("ODDSPAPI_KEY") or None, log=ctx.log)


def itens_pendentes(contas):
    """As apostas no papel esperando o placar (uma linha por seleção, com as versões que apostaram)."""
    linhas = {}
    for c in contas.values():
        for ap in c.abertas:
            k = (ap["j"], ap["mk"], ap["s"])
            if k not in linhas:
                linhas[k] = {"jogo": ap["jogo"], "liga": NOME_LIGA.get(ap["l"], ap["l"]), "inicio": ap["i"],
                             "selecao": ap["sel"], "odd": ap["o"], "justa": round(1 / ap["p"], 3), "valor": ap["v"],
                             "casa": ap["c"], "versoes": []}
            linhas[k]["versoes"].append(c.id)
    return sorted(linhas.values(), key=lambda x: x["inicio"])[:40]


def rodar(ctx):
    erros = []
    est = copy.deepcopy(ctx.est)  # só volta para ctx.est se a rodada der certo
    agora, log = int(ctx.agora), ctx.log
    fonte = fonte_de(ctx)
    tem_chave = bool(getattr(fonte, "chave", None))
    cont0 = dict(getattr(fonte, "contagem", None) or {})
    ped0 = getattr(fonte, "pedidos", 0)

    # ---------------------------------------------------------------- teste no passado
    hist = est.get("hist") or {}
    refazer = not hist or agora - int(hist.get("em") or 0) >= HIST_REFAZER or hist.get("v") != VERSAO
    if refazer and ctx.restante() < HIST_TEMPO_MIN:
        log(f"  apostas: pouco tempo na rodada ({ctx.restante():.0f} s); o teste no passado fica para a próxima")
        refazer = False
    if refazer:
        try:
            jogos, info = baixar_passado(fonte, agora, log, erros)
        except ERROS_API as e:
            if not hist:  # nada para mostrar: a forma falha (fica o arquivo anterior, se houver)
                raise
            jogos, info = [], None
            erros.append(f"teste no passado: {e}")
            log(f"  apostas: teste no passado não refeito ({e}); fica o anterior")
        if jogos:
            ini = jogos[0]["inicio"] - DIA  # a curva parte de 1.000 na véspera do primeiro jogo
            res = simular_passado(jogos, ini, agora)
            hist = {"v": VERSAO, "em": agora, "de": ini, "ate": agora, "versoes": res, "info": info}
            est["hist"] = hist
            log(f"  apostas: teste no passado refeito ({info['jogos']} jogos, {dia_de(ini)} a {dia_de(agora)})")
        elif info is not None:
            erros.append("as planilhas vieram sem jogos")

    # ---------------------------------------------------------------- ao vivo
    ev = Eventos(est.get("eventos"))
    evdia = est.setdefault("evDia", {})
    V = est.setdefault("vivo", {})
    contas = None
    if tem_chave:
        V.setdefault("inicio", agora)
        guard = V.setdefault("contas", {})
        contas = {cfg[0]: Conta(cfg, int(V["inicio"]), guard.get(cfg[0])) for cfg in VERSOES}
        if not guard:
            ev.add(agora, "aviso", "Começou o acompanhamento ao vivo pela OddsPapi: até 8 jogos por dia, "
                                   "começando pelo Brasileirão.", None)
        vivo = Vivo(fonte, V, agora, contas, ev, evdia, log, erros)
        vivo.rodar()
        for c in contas.values():
            c.virar(agora, ev)
            c.marcar(agora)
            c.extra(NOME_SOFT.get(V["soft"].get("usada") or "", None))
            guard[c.id] = c.para_json()
        V.pop("semChave", None)
    else:
        V["semChave"] = True
        log("  apostas: falta a chave gratuita da OddsPapi (ODDSPAPI_KEY); só o teste no passado")
        if V.get("contas"):  # a chave sumiu depois de começar: as contas ficam paradas onde estavam
            contas = {cfg[0]: Conta(cfg, int(V.get("inicio") or agora), V["contas"].get(cfg[0])) for cfg in VERSOES}
            for c in contas.values():
                c.extra()
    d0 = dia_de(agora - 10 * DIA)
    for d in [d for d in evdia if d < d0]:
        del evdia[d]

    # ---------------------------------------------------------------- saída
    versoes = []
    hv = (hist or {}).get("versoes") or {}
    for cfg in VERSOES:
        vid, nome, grupo, risco, _regra, frase = cfg
        conta = contas[vid].curva.resumo() if contas and vid in contas else None
        versoes.append({"id": vid, "nome": nome, "frase": frase, "risco": risco, "alav": 1, "grupo": grupo,
                        "aoVivo": conta, "historico": hv.get(vid)})
    est["eventos"] = ev.para_json()
    usada = (V.get("soft") or {}).get("usada")
    S = V.get("soft") or {}
    if tem_chave:
        situacao = "ligado"
    elif V.get("contas"):
        situacao = "parado: falta a chave gratuita da OddsPapi (as contas ficam onde estavam)"
    else:
        situacao = "falta a chave gratuita da OddsPapi"
    orc = Orcamento(fonte, V, agora) if tem_chave else None
    config = {
        "frequencia": "a cada 6 h", "moeda": "R$", "unidade": "R$ fictícios", "saldoInicial": "1.000 = saldo fictício",
        "esporte": "futebol", "ligas": [n for _k, n, *_ in LIGAS],
        "metodo": "potência (odds da Pinnacle sem a margem)", "faixaOdds": list(FAIXA_PADRAO),
        "apostaFixa": round(APOSTA_FIXA * CAPITAL, 2), "kelly": {"fracao": KELLY_FRACAO, "maximo": KELLY_MAX},
        "gratis": {"valor": GRATIS_VALOR, "faixa": list(GRATIS_FAIXA), "porSemana": 1},
        "horaAposta": f"{ANTES_H} h antes do jogo (ou o último preço até {ULTIMO_H} h antes)",
        "aoVivo": situacao,
        "fonteSoft": (f"{NOME_SOFT.get(usada, usada)} ({usada})" if usada else None),
        "softDescartadas": sorted((S.get("descartadas") or {}).keys()),
        "orcamento": {"mes": V.get("mes"), "usados": int(V.get("usados") or 0), "limite": ORCAMENTO_MES,
                      "paraEm": int(ORCAMENTO_MES * PARAR_EM), "maxPorDia": MAX_POR_DIA,
                      "cotaHoje": orc.cota_do_dia(max(1, sum(1 for k in (V.get("torneios") or {}) if not (V.get("fxVazio") or {}).get(k)))) if orc else None,
                      "puladosPeloLimite": int(V.get("pulados") or 0), "semOdds": int(V.get("semOdds") or 0)},
        "campeonatosAoVivo": {k: t.get("nome") for k, t in (V.get("torneios") or {}).items()},
        "historico": (hist or {}).get("info"),
        "pedidosRodada": {k: v - cont0.get(k, 0) for k, v in (getattr(fonte, "contagem", None) or {}).items()
                          if v - cont0.get(k, 0)},
    }
    avisos = list(AVISOS)
    if not tem_chave:
        avisos.insert(0, "O acompanhamento ao vivo está parado: falta a chave gratuita da OddsPapi (o Alediov cria a "
                         "conta, sem cartão, e põe a chave no segredo ODDSPAPI_KEY deste repositório). Por enquanto, só o "
                         "teste no passado.")
    info = (hist or {}).get("info") or {}
    if info.get("jogos") and info.get("justaPinnacle", 1) < 0.9:
        avisos.append(f"Em {pct_br(1 - info['justaPinnacle'], 0)} dos jogos do teste no passado as planilhas não tinham "
                      "as odds da Pinnacle; neles a chance justa veio da média das casas, que é menos precisa.")
    if fonte is not ctx.cli and isinstance(getattr(ctx.cli, "pedidos", None), int):
        ctx.cli.pedidos += getattr(fonte, "pedidos", 0) - ped0  # para o rodada.pedidos e o log contarem estes também
    ctx.est.clear()
    ctx.est.update(est)
    return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": PADRAO, "versoes": versoes,
            "eventos": est["eventos"], "itens": itens_pendentes(contas) if contas else [], "avisos": avisos,
            "config": config, "erros": erros}
