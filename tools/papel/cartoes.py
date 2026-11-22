"""Observatório dos cartões no intervalo (pedido do Alediov, 21/11/2026, pela planilha de apostas dele de agosto: os
"Over cartões no intervalo" deram 7 de 7). SÓ OBSERVAÇÃO: não há odds gratuitas de cartões, então nenhuma conta aposta.

O método dele (o prompt "Cartões" do AI Studio): apostar em mais cartões no 2º tempo, no intervalo, só nos jogos em que
o 1º tempo terminou SEM cartão. Aqui se mede, nos jogos de verdade, com que frequência isso acontece:

- dos jogos terminados nos campeonatos que o prompt aceita, os que tiveram 0 cartão no 1º tempo;
- desses, em quantos o 2º tempo teve mais de 1,5, 2,5 e 3,5 cartões (a taxa, o intervalo de Wilson de 95% e a odd
  justa = 1 ÷ taxa: se a casa paga mais que ela no intervalo, o método tem valor);
- o mesmo em todos os jogos (sem a condição), para ver se o "0 no 1º tempo" muda alguma coisa;
- por campeonato e os times com mais cartões por jogo.

Fonte: o placar público da ESPN (sem chave), o mesmo das apostas: a lista de jogos do dia de cada campeonato e, de cada
jogo terminado, os lances (`keyEvents` do resumo do jogo: tipo, minuto, período e time). Cada cartão conta 1 (o 2º
amarelo e o vermelho que vem com ele contam 2, como a ESPN registra). Prorrogação não conta. Os nomes dos campos foram
escritos sem acesso à ESPN daqui: a 1ª rodada registra no log a estrutura de um lance para conferir.

O árbitro (22/11/2026): o resumo da ESPN de verdade NÃO traz a arbitragem (o `gameInfo` só tem o estádio e o público).
Outras fontes, todas gratuitas, preenchem o nome (`completar_arbitros`, a ordem abaixo):
1. a API "core" da ESPN (`/events/<id>/competitions/<id>/officials`), sem chave: tentada nos jogos novos; se 12 jogos
   seguidos não trazem ninguém, para por 14 dias (o log diz);
2. as planilhas do football-data.co.uk (sem chave): `Referee` e os cartões (HY, AY, HR, AR) da Premier League, 1×/dia,
   a temporada atual e a anterior; servem também de HISTÓRICO do árbitro (`arb.hist`: a média dele vem só dos jogos de
   antes, sem contar duas vezes o mesmo jogo);
3. a football-data.org (chave grátis no segredo `FOOTBALLDATA_KEY`, cabeçalho `X-Auth-Token`; 10 pedidos por minuto):
   `referees` dos jogos do Brasileirão A e das ligas grandes da Europa, até 10 dias por pedido;
4. a API-Football (chave grátis no segredo `APIFOOTBALL_KEY`, cabeçalho `x-apisports-key`; 100 pedidos por dia):
   `fixture.referee` de todos os jogos de um dia num pedido só. O plano grátis só abre de ontem a amanhã: pede ontem e
   hoje a cada rodada enquanto faltar árbitro (os dias mais velhos ficam com a football-data.org).
As chaves só por variável de ambiente (papel.yml), nunca em arquivo, URL ou log. O casamento com os jogos da ESPN é pela
data (±36 h) e pelos dois times (`apostas.mesmo_time`); o nome vira uma chave "inicial + sobrenome" (`chave_arbitro`),
porque a planilha escreve "A Taylor" e as APIs "Anthony Taylor".

Escanteios, faltas e chutes (22/11/2026, pedido do Alediov; também SÓ OBSERVAÇÃO, sem odds grátis de escanteio): do
MESMO resumo do jogo (nenhum pedido a mais), a narração lance a lance (`commentary`: "Corner, …", "Foul by …",
"Attempt …", com o minuto) separa cada tempo, e as estatísticas (`boxscore.teams[].statistics`, `wonCorners`) dão o
total de escanteios de cada time. Guardado na 10ª posição do jogo: [esc. 1º tempo, esc. 2º, esc. casa, esc. fora,
esc. total, faltas 1º, faltas 2º, chutes 1º, chutes 2º] (None no que a ESPN não trouxe). As planilhas do football-data
das 5 ligas grandes (HC e AC, o jogo inteiro, 2 temporadas, 1×/dia) dão o histórico de cada liga. As faltas do 1º tempo
entram nos cartões (o recorte "0 cartão e muitas faltas no 1º tempo"). Os nomes dos campos foram escritos sem acesso à
ESPN daqui: a 1ª rodada registra a estrutura de um item da narração e das estatísticas.

Gols no intervalo e no fim (22/11/2026, pedido do Alediov): pelos gols dos lances (`keyEvents`, `scoringPlay`) e pelos
chutes da narração, a 11ª posição do jogo: [gols 1º, gols 2º, gols depois dos 75', empatado aos 75' (1/0), chutes
entre 60' e 75', chutes 1º] (None se os gols dos lances não batem com o placar final do resumo). Mede: depois de 0×0 no
intervalo, o gol no 2º tempo (com mais ou menos chutes no 1º que a mediana dos jogos) e, empatado aos 75', o gol depois
(com mais ou menos chutes entre 60' e 75').

As contas do intervalo (22/11/2026, pedido do Alediov): o robô do intervalo (`intervalo.py`) guarda as odds AO VIVO da
API-Football no intervalo e perto dos 75'; aqui cada método vira uma conta no papel de R$ 20 por aposta, na odd que a
casa pagava naquela hora, liquidada pelo que a ESPN conta do jogo: mais cartões que a linha principal da casa e mais de 1,5 e
2,5 cartões no 2º tempo depois de 0 no 1º, mais escanteios que a linha principal, mais de 3,5 escanteios no 2º tempo (a linha do jogo = os do 1º + 3,5), gol no 2º tempo depois do 0×0 (e só com
mais chutes no 1º que a mediana dos jogos de antes) e gol depois dos 75' com o jogo empatado.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
import os
import re
import time
import unicodedata

from conta import DIA, HORA, dia_de

URL_DIA = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates={dia}"
URL_JOGO = "https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/summary?event={id}"

# chave, nome, código da ESPN (os campeonatos que o prompt dele aceita)
LIGAS = [
    ("bra", "Brasileirão A", "bra.1"),
    ("bra2", "Brasileirão B", "bra.2"),
    ("cdb", "Copa do Brasil", "bra.copa_do_brazil"),
    ("lib", "Libertadores", "conmebol.libertadores"),
    ("sud", "Sul-Americana", "conmebol.sudamericana"),
    ("eng", "Premier League", "eng.1"),
    ("esp", "La Liga", "esp.1"),
    ("ita", "Série A (Itália)", "ita.1"),
    ("ger", "Bundesliga", "ger.1"),
    ("fra", "Ligue 1", "fra.1"),
    ("ucl", "Champions League", "uefa.champions"),
    ("uel", "Europa League", "uefa.europa"),
]
NOME = {k: n for k, n, _ in LIGAS}
COD = {k: c for k, _, c in LIGAS}

VOLTA_DIAS = 30              # quanto do passado se busca na 1ª vez (aos poucos)
GUARDA_DIAS = 120            # jogos guardados no estado
MAX_DIAS_RODADA = 24         # listas de jogos por rodada (um campeonato × um dia cada)
MAX_JOGOS_RODADA = 40        # resumos de jogo por rodada
SEGUNDOS = 150               # tempo máximo do observatório numa rodada (as formas depois das apostas precisam dele)
DEIXAR = 400                 # segundos da rodada que ficam para as formas seguintes
TEMPO_MIN = 40               # segundos que precisam sobrar para continuar pedindo
FALHA_PAUSA = 7 * DIA        # campeonato que a ESPN não reconhece (404): tenta de novo em 7 dias
TENTATIVAS = 3               # resumo de jogo que falha: tenta até 3 vezes
LINHAS = [(1.5, "o15"), (2.5, "o25"), (3.5, "o35")]
ODD_REF = 1.9                # a odd típica que ele pegava (a média da planilha de agosto: 1,6 a 2,55)
MIN_TIME = 4                 # jogos mínimos de um time para entrar na lista
ULTIMOS = 10
# 22/11/2026: o filtro do prompt "Cartões" dele: descartar o jogo com árbitro de média abaixo de 4,0 cartões por jogo
# e com a expectativa (as médias dos dois times e a do árbitro) abaixo de 4,0. As médias saem SÓ dos jogos de antes,
# vistos aqui (nada do futuro), e pedem MIN_MEDIA jogos de cada um.
FILTRO_ARBITRO = 4.0
FILTRO_EXPECTATIVA = 4.0
MIN_MEDIA = 3
RE_ARBITRO = re.compile(r"referee|[áa]rbitro|arbitre|schiedsrichter", re.I)
RE_NAO_ARBITRO = re.compile(r"assist|var\b|video|fourth|quarto|reserve|linesman", re.I)

# as fontes do árbitro (22/11/2026; ver o começo do arquivo)
URL_OFICIAIS = "https://sports.core.api.espn.com/v2/sports/soccer/leagues/{liga}/events/{id}/competitions/{id}/officials"
CORE_DESISTE = 12            # jogos seguidos sem árbitro na API core: para
CORE_PAUSA = 14 * DIA
URL_FDORG = "https://api.football-data.org/v4/matches?competitions={comps}&dateFrom={de}&dateTo={ate}&status=FINISHED"
FDORG_COMP = {"bra": "BSA", "eng": "PL", "esp": "PD", "ita": "SA", "ger": "BL1", "fra": "FL1", "ucl": "CL"}
FDORG_DIAS = 10              # o máximo de dias por pedido
FDORG_RODADA = 3
URL_APIF = "https://v3.football.api-sports.io/fixtures?date={dia}&timezone=UTC"
APIF_RODADA = 2              # dias por rodada (ontem e hoje)
APIF_VOLTA = 2               # o plano grátis só abre de ontem a amanhã
APIF_DIA = 90                # pedidos por dia (o limite grátis é 100)
CHAVE_PAUSA = 7 * DIA        # fonte com chave que recusou (plano, chave errada): tenta de novo em 7 dias
CASAR_JANELA = 36 * HORA
# escanteios (22/11/2026)
LINHAS_ESC = [(8.5, "e85"), (9.5, "e95"), (10.5, "e105")]     # no jogo
LINHAS_ESC2 = [(3.5, "s35"), (4.5, "s45")]                    # no 2º tempo
POUCOS_ESC1 = 3              # "1º tempo com poucos escanteios": até 3 (os dois times)
MUITAS_FALTAS = 12           # "muitas faltas no 1º tempo" (os dois times)
TARDE = 75                   # "gol no fim": depois dos 75'
JANELA_PRESSAO = (60, 75)    # os chutes que contam como pressão antes do fim
# as contas do intervalo (22/11/2026)
CONTAS_INT = [("cartL", "Mais cartões que a linha da casa", "0 cartão no 1º tempo"),
              ("cart15", "Mais de 1,5 cartão no 2º tempo", "0 cartão no 1º tempo"),
              ("cart25", "Mais de 2,5 cartões no 2º tempo", "0 cartão no 1º tempo"),
              ("escL", "Mais escanteios que a linha da casa", "todos os jogos"),
              ("esc35", "Mais de 3,5 escanteios no 2º tempo", "todos os jogos"),
              ("gol2t", "Gol no 2º tempo", "0×0 no intervalo"),
              ("gol2tP", "Gol no 2º tempo", "0×0 e mais chutes no 1º que a mediana"),
              ("fim75", "Gol depois dos 75'", "empatado perto dos 75'")]
VALOR_INT = 20.0
MIN_MEDIANA = 10             # jogos de antes para a mediana dos chutes valer
RX_INT_CART = re.compile(r"card", re.I)
RX_INT_ESC = re.compile(r"corner", re.I)
RX_INT_GOL = re.compile(r"over/under line|match goals|^over/under$|goals over/under", re.I)
RX_INT_FORA = re.compile(r"home|away|team|1st half|first half|2nd half|second half|asian|handicap|european|race|"
                         r"which|extra|3 ?way", re.I)
PLANILHAS = {"eng": "E0", "esp": "SP1", "ita": "I1", "ger": "D1", "fra": "F1"}
RE_N_ESC = re.compile(r"^\s*corner\b|escanteio|corner kick", re.I)
RE_N_FALTA = re.compile(r"^\s*foul by\b|^\s*falta\b|^foul$", re.I)
RE_N_CHUTE = re.compile(r"^\s*(attempt (missed|saved|blocked)|goal!)|^shot (on|off) target|^(blocked )?shot$", re.I)


def _dia_espn(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y%m%d")


def _ms(x):
    if not x:
        return None
    try:
        s = str(x).replace("Z", "+00:00")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\+00:00", s):
            s = s.replace("+00:00", ":00+00:00")
        d = dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return int(d.timestamp() * 1000)
    except ValueError:
        return None


def wilson(k, n, z=1.96):
    """O intervalo de Wilson (95%) de k acertos em n."""
    if not n:
        return None, None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, c - m), min(1.0, c + m)


def estrutura(x, prof=3):
    if prof <= 0:
        return "…"
    if isinstance(x, dict):
        return {str(k): estrutura(v, prof - 1) for k, v in list(x.items())[:10]}
    if isinstance(x, list):
        return [estrutura(x[0], prof - 1)] if x else []
    return type(x).__name__


# ---------------------------------------------------------------------------------------------------- leitura da ESPN
def jogos_do_dia(r):
    """[(id, ms, casa, fora, id da casa, id de fora, terminou)] da lista de jogos de um dia."""
    out = []
    for e in (r or {}).get("events") or []:
        try:
            comp = (e.get("competitions") or [{}])[0]
            st = ((comp.get("status") or e.get("status") or {}).get("type") or {})
            terminou = bool(st.get("completed")) or st.get("state") == "post"
            lados = {c.get("homeAway"): c for c in comp.get("competitors") or []}
            h, a = lados.get("home"), lados.get("away")
            if not h or not a or not e.get("id"):
                continue

            def nome(c):
                tm = c.get("team") or {}
                return tm.get("displayName") or tm.get("name") or tm.get("shortDisplayName") or ""
            out.append((str(e["id"]), _ms(e.get("date") or comp.get("date")), nome(h), nome(a),
                        str((h.get("team") or {}).get("id") or h.get("id") or ""),
                        str((a.get("team") or {}).get("id") or a.get("id") or ""), terminou))
        except (AttributeError, TypeError, IndexError):
            continue
    return out


def _tipo(ev):
    t = ev.get("type")
    if isinstance(t, dict):
        t = " ".join(str(t.get(k) or "") for k in ("text", "type", "name"))
    return str(t or "").lower()


RE_CARTAO = re.compile(r"card|cart[aã]o|amarel|vermelh|\byellow\b|\bred\b")


def eh_cartao(ev):
    if not isinstance(ev, dict):
        return False
    if ev.get("yellowCard") or ev.get("redCard"):
        return True
    t = _tipo(ev)
    # "red" só como palavra: "Penalty - Scored" também tem "red"
    return bool(RE_CARTAO.search(t)) and "substitution" not in t


def tempo(ev):
    """1 ou 2 (o tempo do lance), ou None (prorrogação, pênaltis ou sem minuto)."""
    per = ev.get("period")
    n = per.get("number") if isinstance(per, dict) else per
    if isinstance(n, (int, float)) and not isinstance(n, bool):
        return int(n) if int(n) in (1, 2) else None
    clk = ev.get("clock") or {}
    dv = str(clk.get("displayValue") or "")
    m = re.match(r"\s*(\d+)\s*'?", dv)
    if m:
        base = int(m.group(1))
        return 1 if base <= 45 else 2 if base <= 90 else None
    v = clk.get("value")
    if isinstance(v, (int, float)):
        mn = v / 60
        return 1 if mn <= 45 else 2 if mn <= 95 else None
    return None


def lances(r):
    """Os lances de um resumo de jogo (keyEvents; se não houver, os `details` da competição)."""
    if not isinstance(r, dict):
        return None
    if isinstance(r.get("keyEvents"), list):
        return r["keyEvents"]
    comp = ((r.get("header") or {}).get("competitions") or [{}])[0]
    if isinstance(comp.get("details"), list):
        return comp["details"]
    return None


def _texto(x):
    if isinstance(x, dict):
        return " ".join(str(x.get(k) or "") for k in ("name", "displayName", "abbreviation", "text", "type"))
    return str(x or "")


def arbitro(r):
    """O nome do árbitro principal do resumo do jogo (gameInfo.officials); None se não vier."""
    if not isinstance(r, dict):
        return None
    gi = r.get("gameInfo") if isinstance(r.get("gameInfo"), dict) else {}
    offs = gi.get("officials") or r.get("officials") or []
    if not isinstance(offs, list):
        return None
    nomes = []
    for o in offs:
        if not isinstance(o, dict):
            continue
        nome = o.get("displayName") or o.get("fullName") or o.get("name")
        if not nome:
            continue
        pos = _texto(o.get("position")) + " " + _texto(o.get("type"))
        if RE_ARBITRO.search(pos) and not RE_NAO_ARBITRO.search(pos):
            return str(nome)
        nomes.append((o.get("order"), str(nome), pos))
    # sem o cargo escrito: o 1º da lista (a ESPN põe o principal primeiro), se nada diz que é assistente
    um = [x for x in nomes if x[0] in (1, "1")] or nomes[:1]
    return um[0][1] if um and not RE_NAO_ARBITRO.search(um[0][2]) else None


def chave_arbitro(nome):
    """"Anthony Taylor", "A Taylor", "A. Taylor, England" → "a taylor" (a inicial e o último sobrenome)."""
    if not nome:
        return None
    n = unicodedata.normalize("NFKD", str(nome).split(",")[0]).encode("ascii", "ignore").decode().lower()
    ts = [t for t in re.sub(r"[^a-z ]+", " ", n).split() if t not in ("jr", "junior", "filho", "neto", "de", "da", "do", "dos")]
    if not ts:
        return None
    return ts[0] if len(ts) == 1 else f"{ts[0][0]} {ts[-1]}"


def oficiais_core(r):
    """(nome do árbitro, [$ref]) da lista de oficiais da API core da ESPN: o nome se os itens vêm inteiros; senão os
    endereços dos itens (só `$ref`)."""
    itens = (r or {}).get("items") if isinstance(r, dict) else None
    if not isinstance(itens, list) or not itens:
        return None, []
    inteiros = [x for x in itens if isinstance(x, dict) and (x.get("displayName") or x.get("fullName"))]
    if inteiros:
        return arbitro({"officials": inteiros}), []
    return None, [x["$ref"] for x in itens if isinstance(x, dict) and x.get("$ref")]


def arbitro_core(fonte, C, liga, eid, agora, log):
    """O árbitro pela API core da ESPN (sem chave); None se ela não tem ou está parada."""
    F = C.setdefault("arb", {}).setdefault("fontes", {}).setdefault("espnCore", {"tentou": 0, "achou": 0, "seguidos": 0})
    if agora < int(F.get("pausa") or 0):
        return None
    F["tentou"] += 1
    try:
        r = fonte.json_url(URL_OFICIAIS.format(liga=COD[liga], id=eid), "espn")
        if not F.get("viu"):
            log(f"  cartões: formato dos oficiais (ESPN core): {estrutura(r, 4)}")
            F["viu"] = True
        nome, refs = oficiais_core(r)
        if not nome and refs:
            um = fonte.json_url(refs[0].replace("http://", "https://"), "espn")
            nome = arbitro({"officials": [um]}) if isinstance(um, dict) else None
    except Exception:  # noqa: BLE001  (404: a ESPN não tem a lista desse jogo)
        nome = None
    if nome:
        F["achou"] += 1
        F["seguidos"] = 0
        return nome
    F["seguidos"] = int(F.get("seguidos", 0)) + 1
    if F["seguidos"] >= CORE_DESISTE and not F["achou"]:
        F["pausa"] = agora + CORE_PAUSA
        F["seguidos"] = 0
        log(f"  cartões: a API core da ESPN não trouxe o árbitro em {CORE_DESISTE} jogos seguidos; para por 14 dias")
    return None


def contar(evs, id_casa, id_fora):
    """(cartões no 1º tempo, no 2º, da casa, de fora) dos lances; None se não houver lista de lances."""
    if evs is None:
        return None
    c1 = c2 = cc = cf = 0
    for ev in evs:
        if not eh_cartao(ev):
            continue
        t = tempo(ev)
        if t is None:
            continue
        if t == 1:
            c1 += 1
        else:
            c2 += 1
        tid = str(((ev.get("team") or {}).get("id")) or "")
        if tid and tid == id_casa:
            cc += 1
        elif tid and tid == id_fora:
            cf += 1
    return c1, c2, cc, cf


def _tipo_narracao(it):
    """"esc", "falta", "chute" ou None de um item da narração (pelo tipo do lance; sem ele, pelo começo do texto)."""
    t = _tipo(it.get("play") or {}) if isinstance(it.get("play"), dict) else ""
    t = t.strip()
    txt = str(it.get("text") or "")
    for nome, rx in (("esc", RE_N_ESC), ("falta", RE_N_FALTA), ("chute", RE_N_CHUTE)):
        if (t and rx.search(t)) or rx.search(txt):
            return nome
    return None


def escanteios_box(r, id_casa, id_fora):
    """(escanteios da casa, de fora) das estatísticas do resumo (`wonCorners`); None se não vierem."""
    times = ((r or {}).get("boxscore") or {}).get("teams") if isinstance(r, dict) else None
    if not isinstance(times, list):
        return None
    out = {}
    for t in times:
        if not isinstance(t, dict):
            continue
        tid = str(((t.get("team") or {}).get("id")) or "")
        for st in t.get("statistics") or []:
            if isinstance(st, dict) and (st.get("name") == "wonCorners" or str(st.get("label") or "").lower() == "corner kicks"):
                try:
                    out[tid] = int(float(str(st.get("displayValue") or st.get("value")).replace(",", ".")))
                except (TypeError, ValueError):
                    pass
    if id_casa in out and id_fora in out:
        return out[id_casa], out[id_fora]
    return None


def narracao(r, id_casa, id_fora, casa, fora):
    """[esc. 1º, esc. 2º, esc. casa, esc. fora, esc. total, faltas 1º, faltas 2º, chutes 1º, chutes 2º] do resumo (a
    narração lance a lance e as estatísticas); None se não houver nenhum dos dois."""
    itens = (r or {}).get("commentary") if isinstance(r, dict) else None
    box = escanteios_box(r, id_casa, id_fora)
    if not isinstance(itens, list) or not itens:
        itens = None
    if itens is None and box is None:
        return None
    e = [None] * 9
    if itens is not None:
        cont = {("esc", 1): 0, ("esc", 2): 0, ("falta", 1): 0, ("falta", 2): 0, ("chute", 1): 0, ("chute", 2): 0}
        lado = [0, 0]
        nc, nf = _tokens_nome(casa), _tokens_nome(fora)
        for it in itens:
            if not isinstance(it, dict):
                continue
            tp = _tipo_narracao(it)
            if not tp:
                continue
            pl = it.get("play") if isinstance(it.get("play"), dict) else {}
            per = it.get("period") or pl.get("period")
            t = tempo({"period": per, "clock": it.get("time") or it.get("clock") or pl.get("clock") or {}})
            if t is None:
                continue
            cont[(tp, t)] += 1
            if tp == "esc":
                tm = pl.get("team") or it.get("team") or {}
                tid = str(tm.get("id") or "")
                quem = tm.get("displayName") or str(it.get("text") or "")
                if tid and tid == id_casa:
                    lado[0] += 1
                elif tid and tid == id_fora:
                    lado[1] += 1
                elif _cita(quem, nc) and not _cita(quem, nf):
                    lado[0] += 1
                elif _cita(quem, nf) and not _cita(quem, nc):
                    lado[1] += 1
        e[0], e[1] = cont[("esc", 1)], cont[("esc", 2)]
        e[5], e[6], e[7], e[8] = cont[("falta", 1)], cont[("falta", 2)], cont[("chute", 1)], cont[("chute", 2)]
        if sum(lado) == e[0] + e[1]:
            e[2], e[3] = lado
        e[4] = e[0] + e[1]
        if e[0] + e[1] + e[5] + e[6] == 0:  # narração sem nada disso (a liga não tem narração de verdade)
            e = [None] * 9
    if box is not None:
        e[2], e[3] = box
        e[4] = box[0] + box[1]
        if e[0] is not None and e[0] + e[1] != e[4]:
            # a narração perdeu algum: os tempos não batem com o total, então ficam de fora (o total vale)
            e[0] = e[1] = None
    return e


def _tokens_nome(n):
    s = unicodedata.normalize("NFKD", str(n or "")).encode("ascii", "ignore").decode().lower()
    return [t for t in re.sub(r"[^a-z0-9]+", " ", s).split() if len(t) >= 3 and t not in ("fc", "club", "clube", "esporte")]


def _cita(texto, tokens):
    s = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().lower()
    return bool(tokens) and all(t in s for t in tokens[:2])


def minuto(ev):
    """O minuto do lance (45'+2' = 47, 90'+3' = 93); None sem minuto."""
    clk = ev.get("clock") or ev.get("time") or {}
    dv = str(clk.get("displayValue") or "")
    m = re.match(r"\s*(\d+)\s*'?\s*(?:\+\s*(\d+))?", dv)
    if m:
        return int(m.group(1)) + int(m.group(2) or 0)
    v = clk.get("value")
    return int(v // 60) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def eh_gol(ev):
    if not isinstance(ev, dict):
        return False
    if isinstance(ev.get("scoringPlay"), bool):
        return ev["scoringPlay"]
    t = _tipo(ev)
    return bool(re.search(r"goal|penalty - scored", t)) and not re.search(r"missed|saved|disallowed|no goal", t)


def placar_final(r, id_casa, id_fora):
    """(gols da casa, de fora) do cabeçalho do resumo; None se não vier."""
    comp = (((r or {}).get("header") or {}).get("competitions") or [{}])[0] if isinstance(r, dict) else {}
    out = {}
    for c in comp.get("competitors") or []:
        try:
            out[str((c.get("team") or {}).get("id") or c.get("id") or "")] = int(float(str(c.get("score"))))
        except (TypeError, ValueError, AttributeError):
            pass
    return (out[id_casa], out[id_fora]) if id_casa in out and id_fora in out else None


def gols_e_fim(r, id_casa, id_fora):
    """[gols 1º, gols 2º, gols depois dos 75', empatado aos 75' (1/0), chutes entre 60' e 75', chutes 1º] (os chutes None
    sem narração); None se os gols dos lances não batem com o placar final."""
    evs = lances(r)
    fim = placar_final(r, id_casa, id_fora)
    if evs is None or fim is None:
        return None
    g = [0, 0]
    lado = {id_casa: 0, id_fora: 0}
    ate75 = {id_casa: 0, id_fora: 0}
    tarde = 0
    for ev in evs:
        if not eh_gol(ev):
            continue
        t, mn = tempo(ev), minuto(ev)
        if t is None or mn is None:
            continue  # prorrogação
        g[t - 1] += 1
        tid = str(((ev.get("team") or {}).get("id")) or "")
        if tid in lado:
            lado[tid] += 1
            if mn <= TARDE:
                ate75[tid] += 1
        if t == 2 and mn > TARDE:
            tarde += 1
    if (lado[id_casa], lado[id_fora]) != tuple(fim) or sum(g) != sum(fim):
        return None
    ch_janela = ch1 = None
    itens = (r or {}).get("commentary")
    if isinstance(itens, list) and itens:
        ch_janela = ch1 = 0
        for it in itens:
            if not isinstance(it, dict) or _tipo_narracao(it) != "chute":
                continue
            pl = it.get("play") if isinstance(it.get("play"), dict) else {}
            x = {"period": it.get("period") or pl.get("period"), "clock": it.get("time") or pl.get("clock") or {}}
            t, mn = tempo(x), minuto(x)
            if t == 1:
                ch1 += 1
            if t == 2 and mn is not None and JANELA_PRESSAO[0] < mn <= JANELA_PRESSAO[1]:
                ch_janela += 1
    return [g[0], g[1], tarde, int(ate75[id_casa] == ate75[id_fora]), ch_janela, ch1]


# ---------------------------------------------------------------------------------------------------- a coleta
def coletar(fonte, C, agora, restante, log, erros):
    """Anda o observatório: pede as listas de jogos dos dias que faltam (do mais novo para trás) e os resumos dos jogos
    terminados. `C` é o estado (est["cartoes"]). Devolve quantos pedidos fez."""
    C.setdefault("jogos", {})
    C.setdefault("pend", {})
    C.setdefault("dias", {})      # liga → [dias da ESPN já lidos (AAAAMMDD)]
    C.setdefault("pausa", {})
    C.setdefault("desde", agora)
    ontem = dia_de(agora - DIA)
    pedidos = feitos_dias = feitos_jogos = 0
    # os dias que faltam, de ontem para trás, revezando os campeonatos (hoje fica para amanhã, quando os jogos acabaram;
    # um dia com jogo ainda sem fim volta na próxima rodada)
    t0 = time.monotonic()
    do_ctx = restante
    restante = lambda: min(do_ctx() - DEIXAR, SEGUNDOS - (time.monotonic() - t0))  # noqa: E731
    faltam = []
    for k in range(1, VOLTA_DIAS + 1):
        d = _dia_espn(agora - k * DIA)
        for liga, _n, _c in LIGAS:
            if agora < int(C["pausa"].get(liga) or 0):
                continue
            if d not in C["dias"].setdefault(liga, []):
                faltam.append((liga, d))
    for liga, d in faltam:
        if feitos_dias >= MAX_DIAS_RODADA or restante() < TEMPO_MIN:
            break
        try:
            r = fonte.json_url(URL_DIA.format(liga=COD[liga], dia=d), "espn")
        except Exception as e:  # noqa: BLE001  (odds.Erro e o hl.Erro dos testes; 404 = campeonato desconhecido)
            pedidos += 1
            feitos_dias += 1
            if getattr(e, "status", None) == 404:
                C["pausa"][liga] = agora + FALHA_PAUSA
                log(f"  cartões: a ESPN não reconhece {COD[liga]} ({NOME[liga]}); tenta de novo em 7 dias")
            else:
                erros.append(f"cartões: lista de jogos ({NOME[liga]} {d}): {e}")
            continue
        pedidos += 1
        feitos_dias += 1
        lista = jogos_do_dia(r)
        if lista and not C.get("viuDia"):
            log(f"  cartões: formato da lista de jogos: {estrutura((r.get('events') or [{}])[0], 4)}")
            C["viuDia"] = True
        todos_fim = True
        for eid, ms, casa, fora, ic, iff, fim in lista:
            if not fim:
                todos_fim = False
                continue
            if eid in C["jogos"] or eid in C["pend"] or ms is None or ms < agora - GUARDA_DIAS * DIA:
                continue
            C["pend"][eid] = [ms, liga, casa, fora, ic, iff, 0]
        lidos = C["dias"][liga]
        # um dia só fica "lido" quando acabou (ontem ou antes, com todos os jogos terminados)
        if d not in lidos and todos_fim and d <= ontem.replace("-", ""):
            lidos.append(d)
    # os resumos: os jogos mais antigos primeiro (a ordem não muda as contas)
    for eid in sorted(C["pend"], key=lambda k: C["pend"][k][0]):
        if feitos_jogos >= MAX_JOGOS_RODADA or restante() < TEMPO_MIN:
            break
        ms, liga, casa, fora, ic, iff, tent = C["pend"][eid]
        try:
            r = fonte.json_url(URL_JOGO.format(liga=COD[liga], id=eid), "espn")
        except Exception as e:  # noqa: BLE001
            pedidos += 1
            feitos_jogos += 1
            C["pend"][eid][6] = tent + 1
            if tent + 1 >= TENTATIVAS:
                C["pend"].pop(eid)
                C["semLances"] = int(C.get("semLances", 0)) + 1
            if getattr(e, "status", None) not in (404,):
                erros.append(f"cartões: resumo do jogo {eid}: {e}")
            continue
        pedidos += 1
        feitos_jogos += 1
        evs = lances(r)
        if evs and not C.get("viuLance"):
            card = next((x for x in evs if eh_cartao(x)), evs[0])
            log(f"  cartões: formato de um lance: {estrutura(card, 3)}")
            C["viuLance"] = True
        if not C.get("viuArbitro") and isinstance(r, dict) and (r.get("gameInfo") or r.get("officials")):
            log(f"  cartões: formato do gameInfo: {estrutura(r.get('gameInfo') or {'officials': r.get('officials')}, 4)}")
            C["viuArbitro"] = True
        n = contar(evs, ic, iff)
        C["pend"].pop(eid)
        if n is None:
            C["semLances"] = int(C.get("semLances", 0)) + 1
            continue
        if not C.get("viuNarracao") and isinstance(r, dict) and (r.get("commentary") or r.get("boxscore")):
            it = next((x for x in r.get("commentary") or [] if isinstance(x, dict) and _tipo_narracao(x) == "esc"),
                      (r.get("commentary") or [None])[0])
            log(f"  cartões: formato da narração: {estrutura(it, 4) if it else 'sem'}; das estatísticas: "
                f"{estrutura(((r.get('boxscore') or {}).get('teams') or [{}])[0], 3)}")
            C["viuNarracao"] = True
        C["jogos"][eid] = [ms, liga, casa, fora, *n, arbitro(r) or arbitro_core(fonte, C, liga, eid, agora, log),
                           narracao(r, ic, iff, casa, fora), gols_e_fim(r, ic, iff)]
    try:
        completar_arbitros(fonte, C, agora, restante, log, erros)
    except Exception as e:  # noqa: BLE001  (os árbitros nunca derrubam a coleta)
        erros.append(f"cartões: árbitros: {type(e).__name__}: {e}")
    # limpeza
    corte = agora - GUARDA_DIAS * DIA
    for eid in [k for k, j in C["jogos"].items() if j[0] < corte]:
        del C["jogos"][eid]
    dcorte = _dia_espn(agora - (VOLTA_DIAS + 2) * DIA)
    for liga in C["dias"]:
        C["dias"][liga] = sorted(d for d in C["dias"][liga] if d >= dcorte)
    if feitos_dias or feitos_jogos:
        log(f"  cartões: {feitos_dias} listas de jogos e {feitos_jogos} resumos; {len(C['jogos'])} jogos guardados, "
            f"{len(C['pend'])} esperando o resumo")
    return pedidos


# ---------------------------------------------------------------------------------------------------- os árbitros de fora
def ler_planilha_jogos(texto):
    """[(ms, casa, fora, árbitro ou None, cartões ou None, escanteios ou None)] de uma planilha do football-data.co.uk
    (cartões = HY + AY + HR + AR e escanteios = HC + AC, o jogo inteiro)."""
    from apostas import _campo, _data, _hora_uk, _f
    texto = (texto or "").lstrip("\ufeff")
    leitor = csv.DictReader(io.StringIO(texto))
    if not leitor.fieldnames:
        return []
    leitor.fieldnames = [(c or "").strip().lstrip("\ufeff") for c in leitor.fieldnames]
    out = []
    for ln in leitor:
        ref = (_campo(ln, "Referee") or "").strip() or None
        casa, fora, d = _campo(ln, "HomeTeam", "Home"), _campo(ln, "AwayTeam", "Away"), _data(_campo(ln, "Date"))
        if not casa or not fora or d is None:
            continue
        cs = [_f(_campo(ln, k)) for k in ("HY", "AY", "HR", "AR")]
        es = [_f(_campo(ln, k)) for k in ("HC", "AC")]
        out.append((_hora_uk(d, _campo(ln, "Time")), casa, fora, ref,
                    int(sum(cs)) if all(c is not None for c in cs) else None,
                    int(sum(es)) if all(x is not None for x in es) else None))
    return out


def ler_planilha_arbitros(texto):
    """[(ms, casa, fora, árbitro, cartões)] das linhas com Referee."""
    return [x[:5] for x in ler_planilha_jogos(texto) if x[3]]


def historico_escanteios(totais):
    """{jogos, media, e85, e95, e105} de uma lista de totais de escanteios por jogo."""
    n = len(totais)
    out = {"jogos": n, "media": round(sum(totais) / n, 2) if n else None}
    for ln, rid in LINHAS_ESC:
        k = sum(1 for t in totais if t > ln)
        out[rid] = round(k / n, 4) if n else None
    return out


def ler_fdorg(r):
    """[(ms, casa, fora, árbitro, None)] da lista de jogos da football-data.org (o árbitro principal de `referees`)."""
    out = []
    for m in (r or {}).get("matches") or []:
        try:
            refs = [x for x in m.get("referees") or [] if isinstance(x, dict) and x.get("name")]
            ref = next((x["name"] for x in refs if str(x.get("type") or "").upper() == "REFEREE"), None)
            ms = _ms(m.get("utcDate"))
            casa = (m.get("homeTeam") or {}).get("name") or (m.get("homeTeam") or {}).get("shortName")
            fora = (m.get("awayTeam") or {}).get("name") or (m.get("awayTeam") or {}).get("shortName")
            if ref and ms and casa and fora:
                out.append((ms, casa, fora, ref, None))
        except (AttributeError, TypeError):
            continue
    return out


def ler_apif(r):
    """[(ms, casa, fora, árbitro, None)] de /fixtures da API-Football ("Anthony Taylor, England" vira o nome)."""
    out = []
    for x in (r or {}).get("response") or []:
        try:
            fx, tm = x.get("fixture") or {}, x.get("teams") or {}
            ref = str(fx.get("referee") or "").split(",")[0].strip()
            ms = _ms(fx.get("date")) or (int(fx["timestamp"]) * 1000 if fx.get("timestamp") else None)
            casa, fora = (tm.get("home") or {}).get("name"), (tm.get("away") or {}).get("name")
            if ref and ms and casa and fora:
                out.append((ms, casa, fora, ref, None))
        except (AttributeError, TypeError, ValueError):
            continue
    return out


def casar(C, achados, ligas=None):
    """Põe o árbitro de `achados` [(ms, casa, fora, árbitro, _)] nos jogos guardados sem ele (mesmos times, ±36 h).
    Devolve quantos preencheu."""
    from apostas import mesmo_time
    n = 0
    for j in C.get("jogos", {}).values():
        if (len(j) > 8 and j[8]) or (ligas and j[1] not in ligas):
            continue
        for ms, casa, fora, ref, _c in achados:
            if abs(ms - j[0]) <= CASAR_JANELA and mesmo_time(j[2], casa) and mesmo_time(j[3], fora):
                if len(j) > 8:
                    j[8] = ref
                else:
                    j.append(ref)
                n += 1
                break
    return n


def _faltam(C, ligas=None):
    """Os jogos guardados sem árbitro (dos campeonatos `ligas`, se dado)."""
    return [j for j in C.get("jogos", {}).values() if not (len(j) > 8 and j[8]) and (not ligas or j[1] in ligas)]


def _contar_fonte(A, nome, n):
    F = A.setdefault("fontes", {}).setdefault(nome, {})
    F["preencheu"] = int(F.get("preencheu", 0)) + n
    return F


def completar_arbitros(fonte, C, agora, restante, log, erros, env=None):
    """As fontes 2 a 4 do começo do arquivo. Nada aqui derruba a coleta."""
    env = os.environ if env is None else env
    A = C.setdefault("arb", {})
    A.setdefault("fontes", {})
    # 2. as planilhas (1×/dia): o árbitro e o histórico dele (só as inglesas têm Referee) e o histórico dos escanteios
    F = A["fontes"].setdefault("planilha", {})
    if (agora - int(F.get("em") or 0) >= DIA or "escHist" not in C) and restante() >= TEMPO_MIN:
        from apostas import URL_FD, temporadas
        temps, _ini = temporadas(agora, 2)
        linhas, hist, esc = [], {}, {}
        for liga, div in PLANILHAS.items():
            for t in temps:
                try:
                    linhas += [(liga, x) for x in ler_planilha_jogos(fonte.texto(URL_FD.format(temp=t, div=div), "arbitros"))]
                except Exception as e:  # noqa: BLE001  (a temporada que não começou dá 404)
                    if getattr(e, "status", None) != 404:
                        erros.append(f"cartões: planilha ({div} {t}): {e}")
        for liga, (ms, casa, fora, ref, cart, es) in linhas:
            k = chave_arbitro(ref)
            if k and cart is not None:
                hist.setdefault(k, []).append([ms, cart])
            if es is not None:
                esc.setdefault(liga, []).append(es)
        F["em"] = agora
        com_ref = [x for _l, x in linhas if x[3]]
        if linhas:
            A["hist"] = {k: sorted(v) for k, v in hist.items()}
            C["escHist"] = {liga: historico_escanteios(v) for liga, v in esc.items()}
            n = casar(C, [x[:5] for x in com_ref])
            _contar_fonte(A, "planilha", n)
            log(f"  cartões: planilha dos árbitros: {len(com_ref)} jogos, {len(hist)} árbitros, {n} jogos daqui preenchidos; "
                f"escanteios de {sum(len(v) for v in esc.values())} jogos em {len(esc)} ligas")
    # 3. football-data.org (chave grátis)
    chave = (env.get("FOOTBALLDATA_KEY") or "").strip()
    F = A["fontes"].setdefault("fdorg", {})
    if chave and agora >= int(F.get("pausa") or 0):
        tentados = set(F.get("tentados") or [])
        recente = (dt.datetime.fromtimestamp(agora / 1000, dt.timezone.utc) - dt.timedelta(days=2)).date()
        falta = sorted(j[0] for j in _faltam(C, set(FDORG_COMP)))
        falta = [ms for ms in falta if dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date().isoformat() not in tentados]
        feitos = 0
        while falta and feitos < FDORG_RODADA and restante() >= TEMPO_MIN:
            de = dt.datetime.fromtimestamp(falta[0] / 1000, dt.timezone.utc).date()
            ate = de + dt.timedelta(days=FDORG_DIAS - 1)
            # um dia de 2 dias atrás ou mais velho só é pedido uma vez (o grátis chega com atraso: os recentes voltam)
            tentados |= {(de + dt.timedelta(days=k)).isoformat() for k in range(FDORG_DIAS) if de + dt.timedelta(days=k) <= recente}
            url = URL_FDORG.format(comps=",".join(sorted(set(FDORG_COMP.values()))), de=de.isoformat(), ate=ate.isoformat())
            feitos += 1
            try:
                r = fonte.json_chave(url, "fdorg", "X-Auth-Token", chave)
            except Exception as e:  # noqa: BLE001
                if getattr(e, "status", None) in (400, 401, 403):
                    F["pausa"] = agora + CHAVE_PAUSA
                    log(f"  cartões: a football-data.org recusou ({e}); tenta de novo em 7 dias")
                else:
                    erros.append(f"cartões: football-data.org: {e}")
                break
            if not F.get("viu"):
                log(f"  cartões: formato da football-data.org: {estrutura(((r or {}).get('matches') or [{}])[0], 3)}")
                F["viu"] = True
            n = casar(C, ler_fdorg(r), set(FDORG_COMP))
            _contar_fonte(A, "fdorg", n)
            log(f"  cartões: football-data.org {de}–{ate}: {n} árbitros")
            fim = int(dt.datetime.combine(ate + dt.timedelta(days=1), dt.time(), dt.timezone.utc).timestamp() * 1000)
            falta = [ms for ms in falta if ms >= fim]
        corte = (dt.datetime.fromtimestamp(agora / 1000, dt.timezone.utc) - dt.timedelta(days=GUARDA_DIAS + 2)).date().isoformat()
        F["tentados"] = sorted(x for x in tentados if x >= corte)
    # 4. API-Football (chave grátis): um dia por pedido, todos os campeonatos. O plano grátis só abre de ontem a amanhã
    # (a 1ª resposta de verdade, 22/11/2026: "Free plans do not have access to this date, try from 2026-11-21 to
    # 2026-11-23"): pede só ontem e hoje, a cada rodada enquanto faltar árbitro (ele aparece algumas horas depois)
    chave = (env.get("APIFOOTBALL_KEY") or "").strip()
    F = A["fontes"].setdefault("apif", {})
    F.pop("tentados", None)
    if re.search(r"access to this date", str(F.get("motivo") or ""), re.I):  # a parada de 7 dias da 1ª versão
        F.pop("pausa", None)
        F.pop("motivo", None)
    # 22/11/2026: as apostas rodam a cada hora; a API-Football dos árbitros só a cada 3 h (o robô e o Theo usam o resto)
    if chave and agora >= int(F.get("pausa") or 0) and agora - int(F.get("em") or 0) >= 3 * HORA:
        F["em"] = agora
        hoje = dia_de(agora)
        if F.get("dia") != hoje:
            F["dia"], F["hoje"] = hoje, 0
        janela = {_dia_espn(agora - k * DIA) for k in range(APIF_VOLTA)}
        dias = sorted({_dia_espn(j[0]) for j in _faltam(C)} & janela, reverse=True)
        feitos = 0
        for d in dias:
            if feitos >= APIF_RODADA or F["hoje"] >= APIF_DIA or restante() < TEMPO_MIN:
                break
            iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
            feitos += 1
            F["hoje"] += 1
            try:
                r = fonte.json_chave(URL_APIF.format(dia=iso), "apif", "x-apisports-key", chave)
            except Exception as e:  # noqa: BLE001
                erros.append(f"cartões: API-Football: {e}")
                break
            errs = (r or {}).get("errors")
            if errs:  # 200 com o motivo em `errors`: a data fora do plano passa; chave ou limite param 1 dia
                F["motivo"] = str(errs)[:200]
                if re.search(r"access to this date|try from", F["motivo"], re.I):
                    log(f"  cartões: a API-Football não abre {iso} no plano grátis")
                    continue
                F["pausa"] = agora + DIA
                log(f"  cartões: a API-Football recusou: {F['motivo']}; tenta de novo amanhã")
                break
            if not F.get("viu"):
                log(f"  cartões: formato da API-Football: {estrutura(((r or {}).get('response') or [{}])[0], 3)}")
                F["viu"] = True
            n = casar(C, ler_apif(r))
            _contar_fonte(A, "apif", n)
            log(f"  cartões: API-Football {iso}: {n} árbitros")


# ---------------------------------------------------------------------------------------------------- as contas
def taxa(js, linha):
    """{n, k, taxa, lo, hi, justa} dos jogos `js` com 2º tempo acima de `linha`."""
    n = len(js)
    k = sum(1 for j in js if j[5] > linha)
    lo, hi = wilson(k, n)
    t = k / n if n else None
    return {"n": n, "k": k, "taxa": round(t, 4) if t is not None else None,
            "lo": round(lo, 4) if lo is not None else None, "hi": round(hi, 4) if hi is not None else None,
            "justa": round(1 / t, 2) if t else None}


def taxa_valores(vs, linha):
    """{n, k, taxa, lo, hi, justa} de uma lista de números acima de `linha`."""
    n = len(vs)
    k = sum(1 for v in vs if v > linha)
    lo, hi = wilson(k, n)
    t = k / n if n else None
    return {"n": n, "k": k, "taxa": round(t, 4) if t is not None else None,
            "lo": round(lo, 4) if lo is not None else None, "hi": round(hi, 4) if hi is not None else None,
            "justa": round(1 / t, 2) if t else None}


def _nar(j):
    return j[9] if len(j) > 9 and isinstance(j[9], list) and len(j[9]) == 9 else None


def resumo_escanteios(C):
    """O bloco `escanteios` (FORMATO.md, "Escanteios")."""
    js = sorted(C.get("jogos", {}).values(), key=lambda j: j[0])
    com = [(j, _nar(j)) for j in js if _nar(j) and _nar(j)[4] is not None]
    tempos = [(j, e) for j, e in com if e[0] is not None]
    out = {"jogos": len(com), "comTempos": len(tempos), "poucos1t": POUCOS_ESC1,
           "hist": [{"liga": k, "nome": NOME.get(k, k), **v} for k, v in (C.get("escHist") or {}).items()]}
    if not com:
        return out
    tot = [e[4] for _j, e in com]
    out["media"] = {"jogo": round(sum(tot) / len(tot), 2),
                    "t1": round(sum(e[0] for _j, e in tempos) / len(tempos), 2) if tempos else None,
                    "t2": round(sum(e[1] for _j, e in tempos) / len(tempos), 2) if tempos else None}
    regras = [{"id": rid, "linha": ln, "nome": f"Mais de {str(ln).replace('.', ',')} escanteios no jogo",
               "todos": taxa_valores(tot, ln)} for ln, rid in LINHAS_ESC]
    poucos = [e for _j, e in tempos if e[0] <= POUCOS_ESC1]
    regras += [{"id": rid, "linha": ln, "nome": f"Mais de {str(ln).replace('.', ',')} escanteios no 2º tempo",
                "todos": taxa_valores([e[1] for _j, e in tempos], ln),
                "poucos1t": taxa_valores([e[1] for e in poucos], ln)} for ln, rid in LINHAS_ESC2]
    out["regras"] = regras
    ligas = []
    for liga, nome, _c in LIGAS:
        lv = [e[4] for j, e in com if j[1] == liga]
        if lv:
            ligas.append({"liga": liga, "nome": nome, "jogos": len(lv), "media": round(sum(lv) / len(lv), 2),
                          "e95": taxa_valores(lv, 9.5)})
    out["ligas"] = sorted(ligas, key=lambda x: -x["jogos"])
    tm = {}
    for j, e in com:
        if e[2] is None or e[3] is None:
            continue
        for nome, a, c in ((j[2], e[2], e[3]), (j[3], e[3], e[2])):
            t = tm.setdefault((j[1], nome), [0, 0, 0])
            t[0] += 1
            t[1] += a
            t[2] += c
    times = [{"time": nome, "liga": NOME.get(liga, liga), "jogos": v[0], "aFavor": round(v[1] / v[0], 2),
              "contra": round(v[2] / v[0], 2), "media": round((v[1] + v[2]) / v[0], 2)}
             for (liga, nome), v in tm.items() if v[0] >= MIN_TIME]
    out["times"] = sorted(times, key=lambda x: (-x["media"], -x["jogos"]))[:8]
    return out


def _gols(j):
    return j[10] if len(j) > 10 and isinstance(j[10], list) and len(j[10]) == 6 else None


def _mediana(vs):
    vs = sorted(vs)
    n = len(vs)
    return None if not n else (vs[n // 2] if n % 2 else (vs[n // 2 - 1] + vs[n // 2]) / 2)


def resumo_gols(C):
    """O bloco `gols` (FORMATO.md, "Gols no intervalo e no fim")."""
    js = [_gols(j) for j in C.get("jogos", {}).values() if _gols(j)]
    out = {"jogos": len(js), "tarde": TARDE, "janela": list(JANELA_PRESSAO)}
    if not js:
        return out
    out["media"] = {"t1": round(sum(g[0] for g in js) / len(js), 2), "t2": round(sum(g[1] for g in js) / len(js), 2),
                    "depois75": round(sum(g[2] for g in js) / len(js), 2)}
    zero = [g for g in js if g[0] == 0]
    m1 = _mediana([g[5] for g in js if g[5] is not None])
    out["zero1t"], out["chutes1tMediana"] = len(zero), m1
    regras = []
    for ln, rid, nome in ((0.5, "g2", "Gol no 2º tempo"), (1.5, "g2m15", "Mais de 1,5 gol no 2º tempo")):
        x = {"id": rid, "linha": ln, "nome": nome, "todos": taxa_valores([g[1] for g in js], ln),
             "zero": taxa_valores([g[1] for g in zero], ln)}
        if m1 is not None:
            x["zeroPressao"] = taxa_valores([g[1] for g in zero if g[5] is not None and g[5] > m1], ln)
            x["zeroCalmo"] = taxa_valores([g[1] for g in zero if g[5] is not None and g[5] <= m1], ln)
        regras.append(x)
    out["regras"] = regras
    emp = [g for g in js if g[3] == 1]
    mj = _mediana([g[4] for g in js if g[4] is not None])
    fim = {"todos": taxa_valores([g[2] for g in js], 0.5), "empate": taxa_valores([g[2] for g in emp], 0.5),
           "empates": len(emp), "chutesMediana": mj}
    if mj is not None:
        fim["empatePressao"] = taxa_valores([g[2] for g in emp if g[4] is not None and g[4] > mj], 0.5)
        fim["empateCalmo"] = taxa_valores([g[2] for g in emp if g[4] is not None and g[4] <= mj], 0.5)
    out["fim"] = fim
    return out


def _odd_int(m, rx, linha):
    """A odd de "mais de `linha`" no mercado do jogo inteiro (sem time, tempo, handicap) cujo nome bate com `rx`."""
    for nome, vs in (m or {}).items():
        if not rx.search(nome) or RX_INT_FORA.search(nome):
            continue
        for t, ln, o in vs:
            if t == "over" and ln is not None and abs(float(ln) - linha) < 1e-6 and o:
                return float(o)
    return None


def _linha_principal(m, rx):
    """(linha, odd do "mais") da linha principal ao vivo (a de odd mais perto de 2,0; só linhas x,5, sem devolução)."""
    melhor = None
    for nome, vs in (m or {}).items():
        if not rx.search(nome) or RX_INT_FORA.search(nome):
            continue
        for t, ln, o in vs:
            if t != "over" or ln is None or not o or abs(float(ln) % 1 - 0.5) > 1e-6:
                continue
            if melhor is None or abs(float(o) - 2.0) < abs(melhor[1] - 2.0):
                melhor = (float(ln), float(o))
    return melhor


def contas_intervalo(C, robo):
    """Abre e liquida as apostas do intervalo (C["int"]["ap"], uma por jogo e conta) com as capturas do robô e os
    jogos terminados que a ESPN contou."""
    from apostas import mesmo_time
    I = C.setdefault("int", {})
    I.setdefault("ap", {})
    caps = (robo or {}).get("cap") or {}
    jogos = list(C.get("jogos", {}).values())
    chutes = sorted((j[0], _gols(j)[5]) for j in jogos if _gols(j) and _gols(j)[5] is not None)
    for k, cp in caps.items():
        try:
            ms = int(cp["ms"])
        except (KeyError, TypeError, ValueError):
            continue
        j = next((j for j in jogos if abs(j[0] - ms) <= 3 * HORA and mesmo_time(j[2], cp.get("c")) and mesmo_time(j[3], cp.get("f"))), None)
        if not j:
            continue

        def apostar(cid, odd, ganhou, t):
            chave = f"{k}:{cid}"
            if chave in I["ap"] or not odd or odd <= 1:
                return
            I["ap"][chave] = {"c": cid, "o": round(odd, 3), "g": bool(ganhou), "ms": j[0], "jogo": f"{j[2]} × {j[3]}",
                              "liga": j[1], "t": t}
        ht, m75 = cp.get("ht") or {}, cp.get("m75") or {}
        if ht:
            m = ht.get("m") or {}
            if j[4] == 0:
                lp = _linha_principal(m, RX_INT_CART)
                if lp:
                    apostar("cartL", lp[1], j[5] > lp[0], ht.get("t"))
                apostar("cart15", _odd_int(m, RX_INT_CART, 1.5), j[5] > 1.5, ht.get("t"))
                apostar("cart25", _odd_int(m, RX_INT_CART, 2.5), j[5] > 2.5, ht.get("t"))
            e = _nar(j)
            lp = _linha_principal(m, RX_INT_ESC)
            if e and e[4] is not None and lp:
                apostar("escL", lp[1], e[4] > lp[0], ht.get("t"))
            if e and e[0] is not None:
                apostar("esc35", _odd_int(m, RX_INT_ESC, e[0] + 3.5), e[1] > 3.5, ht.get("t"))
            g = _gols(j)
            if g and list(ht.get("gols") or []) == [0, 0] and g[0] == 0:
                o = _odd_int(m, RX_INT_GOL, 0.5)
                apostar("gol2t", o, g[1] > 0, ht.get("t"))
                antes = [c for t, c in chutes if t < j[0]]
                med = _mediana(antes) if len(antes) >= MIN_MEDIANA else None
                if med is not None and g[5] is not None and g[5] > med:
                    apostar("gol2tP", o, g[1] > 0, ht.get("t"))
        if m75:
            g, gl = _gols(j), list(m75.get("gols") or [])
            if g and len(gl) == 2 and None not in gl and gl[0] == gl[1]:
                tot = int(gl[0]) + int(gl[1])
                apostar("fim75", _odd_int(m75.get("m"), RX_INT_GOL, tot + 0.5), g[0] + g[1] > tot, m75.get("t"))
    corte = max([a["ms"] for a in I["ap"].values()] or [0]) - GUARDA_DIAS * DIA
    I["ap"] = {k: a for k, a in I["ap"].items() if a["ms"] >= corte}


def resumo_intervalo(C, robo):
    """O bloco `intervalo` (FORMATO.md, "As contas do intervalo")."""
    aps = list(((C.get("int") or {}).get("ap") or {}).values())
    caps = (robo or {}).get("cap") or {}
    contas = []
    for cid, nome, quando in CONTAS_INT:
        xs = sorted((a for a in aps if a["c"] == cid), key=lambda a: a["ms"])
        n = len(xs)
        k = sum(1 for a in xs if a["g"])
        lucro = sum(VALOR_INT * (a["o"] - 1) if a["g"] else -VALOR_INT for a in xs)
        lo, hi = wilson(k, n)
        contas.append({"id": cid, "nome": nome, "quando": quando, "apostas": n, "ganhas": k,
                       "acerto": round(k / n, 4) if n else None, "lo": round(lo, 4) if lo is not None else None,
                       "hi": round(hi, 4) if hi is not None else None,
                       "empate": round(sum(1 / a["o"] for a in xs) / n, 4) if n else None,
                       "oddMedia": round(sum(a["o"] for a in xs) / n, 3) if n else None,
                       "lucro": round(lucro, 2), "apostado": round(VALOR_INT * n, 2),
                       "roi": round(lucro / (VALOR_INT * n), 4) if n else None,
                       "ultimas": [{"jogo": a["jogo"], "liga": NOME.get(a["liga"], a["liga"]), "inicio": a["ms"], "odd": a["o"],
                                    "ganhou": a["g"]} for a in reversed(xs[-6:])]})
    merc = {}
    for c in caps.values():
        for nome in ((c.get("ht") or {}).get("m") or {}):
            merc[nome] = merc.get(nome, 0) + 1
    return {"valor": VALOR_INT, "robo": (robo or {}).get("agora"), "capturas": sum(1 for c in caps.values() if c.get("ht")),
            "m75": sum(1 for c in caps.values() if c.get("m75")),
            "mercados": sorted(([n, k] for n, k in merc.items()), key=lambda x: -x[1])[:12], "contas": contas}


def _media_hist(hist, k, antes):
    """(jogos, média) do árbitro `k` no histórico das planilhas, só com os jogos de antes de `antes`."""
    xs = [c for ms, c in (hist or {}).get(k) or [] if ms < antes - 6 * HORA]
    return (len(xs), sum(xs) / len(xs)) if xs else (0, None)


def filtro_do_prompt(js, hist=None):
    """{id do jogo: (passa, média do árbitro, expectativa)} pelo filtro do prompt, com as médias só dos jogos de antes
    (os jogos em ordem de início; o árbitro só conta com MIN_MEDIA jogos dele; a expectativa pede as médias dos dois
    times, também com MIN_MEDIA jogos). O árbitro com histórico nas planilhas (`hist`, por `chave_arbitro`) usa só ele
    (o mesmo jogo não conta duas vezes); os outros, os jogos vistos aqui. Os jogos são (id, linha do estado)."""
    arb, tim, out = {}, {}, {}
    for eid, j in sorted(js, key=lambda x: x[1][0]):
        total = j[4] + j[5]
        ref = chave_arbitro(j[8] if len(j) > 8 else None)
        if ref and hist and ref in hist:
            nh, mh = _media_hist(hist, ref, j[0])
            ma = mh if nh >= MIN_MEDIA else None
        else:
            ma = (arb[ref][1] / arb[ref][0]) if ref and ref in arb and arb[ref][0] >= MIN_MEDIA else None
        mc = (tim[j[2]][1] / tim[j[2]][0]) if j[2] in tim and tim[j[2]][0] >= MIN_MEDIA else None
        mf = (tim[j[3]][1] / tim[j[3]][0]) if j[3] in tim and tim[j[3]][0] >= MIN_MEDIA else None
        exp = None
        if mc is not None and mf is not None:
            vals = [mc, mf] + ([ma] if ma is not None else [])
            exp = sum(vals) / len(vals)
        passa = exp is not None and exp >= FILTRO_EXPECTATIVA and (ma is None or ma >= FILTRO_ARBITRO)
        out[eid] = (passa, ma, exp)
        if ref:
            a = arb.setdefault(ref, [0, 0])
            a[0] += 1
            a[1] += total
        for t in (j[2], j[3]):
            x = tim.setdefault(t, [0, 0])
            x[0] += 1
            x[1] += total
    return out


def resumo(C, agora, robo=None):
    """O bloco `cartoes` da saída das apostas (FORMATO.md, "Cartões no intervalo"), com o `escanteios` dentro."""
    js = sorted(C.get("jogos", {}).values(), key=lambda j: j[0])
    zero = [j for j in js if j[4] == 0]
    out = {"desde": C.get("desde"), "jogos": len(js), "zero1t": len(zero),
           "esperando": len(C.get("pend") or {}), "semLances": int(C.get("semLances", 0)),
           "oddRef": ODD_REF, "empateRef": round(1 / ODD_REF, 4), "fonte": "ESPN (lances de cada jogo)",
           "ligasForaDaEspn": [NOME[k] for k, t in (C.get("pausa") or {}).items() if agora < int(t or 0)],
           "escanteios": resumo_escanteios(C), "gols": resumo_gols(C), "intervalo": resumo_intervalo(C, robo)}
    if not js:
        return out
    n = len(js)
    out["media"] = {"jogo": round(sum(j[4] + j[5] for j in js) / n, 2), "t1": round(sum(j[4] for j in js) / n, 2),
                    "t2": round(sum(j[5] for j in js) / n, 2),
                    "t2SemCartao1t": round(sum(j[5] for j in zero) / len(zero), 2) if zero else None}
    hist = (C.get("arb") or {}).get("hist") or {}
    fp = filtro_do_prompt(list(C.get("jogos", {}).items()), hist)
    passa = {eid for eid, (ok, _a, _e) in fp.items() if ok}
    zero_f = [j for eid, j in C.get("jogos", {}).items() if j[4] == 0 and eid in passa]
    # 22/11/2026: com a narração, o recorte "0 cartão e muitas faltas no 1º tempo"
    zero_faltas = [j for j in zero if _nar(j) and _nar(j)[5] is not None and _nar(j)[5] >= MUITAS_FALTAS]
    out["regras"] = [{"id": rid, "linha": ln, "nome": f"Mais de {str(ln).replace('.', ',')} cartões no 2º tempo",
                      "comZero": taxa(zero, ln), "todos": taxa(js, ln), "comFiltro": taxa(zero_f, ln),
                      "comFaltas": taxa(zero_faltas, ln)}
                     for ln, rid in LINHAS]
    nar = [_nar(j) for j in js if _nar(j) and _nar(j)[5] is not None]
    out["faltas"] = {"jogos": len(nar), "muitas": MUITAS_FALTAS,
                     "t1": round(sum(e[5] for e in nar) / len(nar), 2) if nar else None,
                     "t2": round(sum(e[6] for e in nar) / len(nar), 2) if nar else None,
                     "zeroComMuitas": len(zero_faltas)}
    com_arb = [j for j in js if len(j) > 8 and j[8]]
    out["filtro"] = {"arbitro": FILTRO_ARBITRO, "expectativa": FILTRO_EXPECTATIVA, "minimo": MIN_MEDIA,
                     "jogosComArbitro": len(com_arb), "zeroComFiltro": len(zero_f),
                     "zeroComMedias": sum(1 for eid, j in C.get("jogos", {}).items() if j[4] == 0 and fp[eid][2] is not None)}
    out["filtro"]["fontes"] = {k: int(v.get("preencheu") or 0) for k, v in ((C.get("arb") or {}).get("fontes") or {}).items()
                               if k != "espnCore"}
    core = ((C.get("arb") or {}).get("fontes") or {}).get("espnCore") or {}
    out["filtro"]["fontes"]["espnCore"] = int(core.get("achou") or 0)
    ar, nomes = {}, {}
    for j in com_arb:
        k = chave_arbitro(j[8])
        if not k:
            continue
        if len(str(j[8])) > len(nomes.get(k, "")):
            nomes[k] = str(j[8])
        a = ar.setdefault(k, [0, 0])
        a[0] += 1
        a[1] += j[4] + j[5]
    lista = []
    for k, v in ar.items():
        nh, mh = _media_hist(hist, k, agora + DIA)  # com as planilhas: a média da temporada (todos os jogos)
        n, m, fonte_m = (nh, mh, "planilha") if nh >= MIN_MEDIA else (v[0], v[1] / v[0], "aqui")
        if n >= MIN_MEDIA:
            lista.append({"nome": nomes[k], "jogos": n, "media": round(m, 2), "fonte": fonte_m})
    out["arbitros"] = sorted(lista, key=lambda x: (-x["media"], -x["jogos"]))[:8]
    ligas = []
    for liga, nome, _c in LIGAS:
        lj = [j for j in js if j[1] == liga]
        if not lj:
            continue
        lz = [j for j in lj if j[4] == 0]
        ligas.append({"liga": liga, "nome": nome, "jogos": len(lj), "zero1t": len(lz),
                      "media": round(sum(j[4] + j[5] for j in lj) / len(lj), 2), "o15": taxa(lz, 1.5)})
    out["ligas"] = sorted(ligas, key=lambda x: -x["jogos"])
    tm = {}
    for j in js:
        for nome, c, contra in ((j[2], j[6], j[7]), (j[3], j[7], j[6])):
            t = tm.setdefault((j[1], nome), [0, 0, 0])
            t[0] += 1
            t[1] += c
            t[2] += contra
    times = [{"time": nome, "liga": NOME.get(liga, liga), "jogos": v[0], "media": round(v[1] / v[0], 2),
              "contra": round(v[2] / v[0], 2)} for (liga, nome), v in tm.items() if v[0] >= MIN_TIME]
    out["times"] = sorted(times, key=lambda x: (-x["media"], -x["jogos"]))[:8]
    out["ultimos"] = [{"jogo": f"{j[2]} × {j[3]}", "liga": NOME.get(j[1], j[1]), "inicio": j[0], "t2": j[5]}
                      for j in reversed(zero[-ULTIMOS:])]
    return out
