"""Futebol de MENTIRA das apostas no papel (sem rede; semente fixa). Nada aqui é dado real.

Um mundo de jogos (Brasileirão, as 5 ligas grandes da Europa e a Libertadores) com chances "verdadeiras" pela força
dos times (gols de Poisson), placares sorteados por essas chances e odds de três casas ao longo do tempo: a Pinnacle
(margem de 2,5%, erra pouco e cada vez menos até o jogo), a Betano e a Bet365 (margem de 6%, erram mais). Assim a aposta
de valor tem uma vantagem pequena de verdade, como se espera na vida real, e o CLV aparece.

Os mesmos formatos das fontes de verdade (os que `apostas.py` lê):

- `texto(url)`: as planilhas CSV do football-data.co.uk (mmz4281/<temporada>/<div>.csv e new/BRA.csv), com as
  variações que a vida real tem: BOM no começo (La Liga), data com ano de 2 dígitos (Premier League 2024/25), uma
  temporada sem as colunas da Pinnacle (Ligue 1 2026/27) e só odds de fechamento no Brasil;
- `oddspapi(caminho, **params)`: /sports, /tournaments, /fixtures e /historical-odds da OddsPapi v4 (o formato que
  supomos: mercado 101 = 1X2 com resultados 101/102/103, histórico em players → "0" → [{createdAt, price}]); a Betano
  do Brasil (betano.bet.br) vem VAZIA por padrão (`betano_br_vazia`), como enquanto as apostas estão suspensas;
- `json_url(url)`: o placar da ESPN (events → competitions → competitors com homeAway e score);
- `bdm()`: os arquivos de config/bdm/ (os palpites do "Bom Dia Mercado" que o repositório do app publica), um por dia,
  publicados às 11h UTC, com palpites de jogos do mundo de mentira: 1X2 (um deles com os times trocados, como a IA pode
  escrever), mais/menos de 2,5 gols, mercados fora do teste (ambas marcam, handicap), um plano para o ao vivo
  (`fora`) e um jogo de um campeonato que o teste não acompanha.

`Falso` é o mixin (o cliente falso das formas o herda); `Avulsa(cli)` é a mesma coisa sozinha, usada quando o cliente
não tem o mixin (o horário vem de `cli.agora`).
"""
from __future__ import annotations

import datetime as dt
import math
import random
import re
import zlib
from collections import Counter

import odds

HORA = 3_600_000
DIA = 86_400_000

LIGAS = {
    "bra": ("BRA", "brasil", ["Flamengo", "Palmeiras", "São Paulo", "Grêmio", "Internacional", "Atlético-MG",
                              "Fluminense", "Botafogo", "Corinthians", "Santos", "Vasco", "Cruzeiro", "Bahia",
                              "Fortaleza", "Athletico-PR", "Bragantino", "Vitória", "Juventude", "Sport", "Ceará"]),
    "eng": ("E0", "europa", ["Arsenal", "Man City", "Liverpool", "Chelsea", "Tottenham", "Man United", "Newcastle",
                             "Aston Villa", "Brighton", "West Ham", "Fulham", "Brentford", "Crystal Palace", "Everton",
                             "Wolves", "Bournemouth", "Nott'm Forest", "Leeds", "Burnley", "Sunderland"]),
    "esp": ("SP1", "europa", ["Real Madrid", "Barcelona", "Ath Madrid", "Sevilla", "Betis", "Villarreal", "Sociedad",
                              "Ath Bilbao", "Valencia", "Girona", "Celta", "Osasuna", "Getafe", "Mallorca", "Alaves",
                              "Espanol", "Vallecano", "Levante", "Elche", "Oviedo"]),
    "ita": ("I1", "europa", ["Inter", "Milan", "Juventus", "Napoli", "Roma", "Lazio", "Atalanta", "Fiorentina", "Bologna",
                             "Torino", "Udinese", "Genoa", "Como", "Lecce", "Cagliari", "Verona", "Parma", "Sassuolo",
                             "Cremonese", "Pisa"]),
    "ger": ("D1", "europa", ["Bayern Munich", "Dortmund", "Leverkusen", "RB Leipzig", "Stuttgart", "Ein Frankfurt",
                             "Freiburg", "Wolfsburg", "M'gladbach", "Hoffenheim", "Werder Bremen", "Union Berlin",
                             "Mainz", "Augsburg", "Heidenheim", "St Pauli", "FC Koln", "Hamburg"]),
    "fra": ("F1", "europa", ["Paris SG", "Marseille", "Monaco", "Lyon", "Lille", "Nice", "Lens", "Rennes", "Strasbourg",
                             "Nantes", "Toulouse", "Brest", "Auxerre", "Angers", "Le Havre", "Lorient", "Metz", "Paris FC"]),
    "lib": (None, "lib", ["Flamengo", "Palmeiras", "River Plate", "Boca Juniors", "Racing Club", "Estudiantes",
                          "Peñarol", "Nacional", "LDU Quito", "Independiente del Valle", "Atlético Nacional",
                          "Colo-Colo", "Olimpia", "Cerro Porteño", "Botafogo", "São Paulo"]),
}
DIV_LIGA = {v[0]: k for k, v in LIGAS.items() if v[0]}
# como a ESPN escreve alguns nomes (o resto igual)
ESPN = {"Man City": "Manchester City", "Man United": "Manchester United", "Wolves": "Wolverhampton Wanderers",
        "Nott'm Forest": "Nottingham Forest", "Atlético-MG": "Atlético Mineiro", "Athletico-PR": "Athletico Paranaense",
        "Bragantino": "Red Bull Bragantino", "Paris SG": "Paris Saint-Germain", "Inter": "Internazionale",
        "Bayern Munich": "Bayern Munich FC", "Vasco": "Vasco da Gama"}
ESPN_COD = {"bra.1": "bra", "eng.1": "eng", "esp.1": "esp", "ita.1": "ita", "ger.1": "ger", "fra.1": "fra",
            "conmebol.libertadores": "lib"}
# a OddsPapi de mentira: (id, nome, categoria, liga do mundo ou None = enfeite)
TORNEIOS = [(325, "Brasileiro Serie A", "Brazil", "bra"), (390, "Brasileiro Serie B", "Brazil", None),
            (17, "Premier League", "England", "eng"), (18, "Premier League 2", "England", None),
            (8, "LaLiga", "Spain", "esp"), (23, "Serie A", "Italy", "ita"), (240, "Serie A", "Ecuador", None),
            (35, "Bundesliga", "Germany", "ger"), (44, "2. Bundesliga", "Germany", None),
            (34, "Ligue 1", "France", "fra"), (384, "CONMEBOL Libertadores", "South America", "lib"),
            (480, "CONMEBOL Libertadores Femenina", "South America", None)]
TORNEIO_LIGA = {t: l for t, _n, _c, l in TORNEIOS if l}
LIGA_TORNEIO = {l: t for t, l in TORNEIO_LIGA.items()}
PLACAR_NA_LISTA = {"eng", "esp"}  # só nesses a lista de jogos traz o placar (o resto vai pela ESPN)

# horas antes do jogo em que as casas publicam um preço novo (o último é o fechamento)
MOMENTOS = [72, 48, 30, 24, 12, 8, 5, 2, 0.25]
PRE = 30  # a planilha guarda o preço de 30 h antes (sexta à tarde para o sábado) e o fechamento
LIVROS = {"pinnacle": (0.025, 0.020, 3), "betano": (0.05, 0.05, 2), "betano.bet.br": (0.055, 0.055, 2),
          "bet365": (0.05, 0.05, 2)}


def semente(*partes):
    return zlib.crc32("|".join(str(p) for p in partes).encode())


def _ms_dia(d: dt.date, h: float):
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() * 1000 + h * HORA)


def _poisson(lam, k):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _sorteio_poisson(r, lam):
    x, p, s, u = 0, math.exp(-lam), math.exp(-lam), r.random()
    while u > s and x < 12:
        x += 1
        p *= lam / x
        s += p
    return x


def forca(nome):
    return 0.7 + 0.8 * random.Random(semente("forca", nome)).random()


class Futebol:
    """Os jogos do mundo de mentira, um dia de cada vez (com cache)."""

    def __init__(self):
        self._dias = {}

    @staticmethod
    def _temporada(estilo, d):
        if estilo == "europa":
            return not (dt.date(d.year, 5, 26) <= d <= dt.date(d.year, 8, 8))
        if estilo == "brasil":
            return dt.date(d.year, 4, 1) <= d <= dt.date(d.year, 12, 7)
        return dt.date(d.year, 2, 15) <= d <= dt.date(d.year, 11, 28)

    def do_dia(self, liga, d: dt.date):
        k = (liga, d)
        if k in self._dias:
            return self._dias[k]
        div, estilo, times = LIGAS[liga]
        out = []
        if self._temporada(estilo, d):
            wd = d.weekday()
            if estilo == "europa":
                horas = {5: [11.5, 14, 14, 14, 16.5, 19], 6: [13, 15.5, 18, 19.75]}.get(wd, [])
            elif estilo == "brasil":
                horas = {2: [22, 22, 23.5, 0.5], 6: [19, 19, 21.5, 21.5, 23, 23]}.get(wd, [])
            else:
                horas = {1: [22, 0.5], 2: [22, 0.5, 23], 3: [22, 0.5]}.get(wd, [])
            sem = d.isocalendar()
            ordem = list(times)
            random.Random(semente("rodada", liga, sem[0], sem[1], wd)).shuffle(ordem)
            for i, h in enumerate(horas):
                if 2 * i + 1 >= len(ordem):
                    break
                dia_jogo = d + dt.timedelta(days=1) if h < 6 else d  # depois da meia-noite UTC
                out.append(self._jogo(liga, d, i, ordem[2 * i], ordem[2 * i + 1], _ms_dia(dia_jogo, h)))
        self._dias[k] = out
        return out

    def _jogo(self, liga, d, i, casa, fora, ini):
        fid = f"fx-{liga}-{d:%Y%m%d}-{i}"
        sc, sf = forca(casa), forca(fora)
        lc, lf = 1.45 * (sc / sf) ** 1.2, 1.1 * (sf / sc) ** 1.2
        pc = [_poisson(lc, k) for k in range(11)]
        pf = [_poisson(lf, k) for k in range(11)]
        p1 = sum(pc[a] * pf[b] for a in range(11) for b in range(11) if a > b)
        px = sum(pc[a] * pf[a] for a in range(11))
        p2 = max(1e-6, 1 - p1 - px)
        lt = lc + lf
        pmenos = sum(_poisson(lt, k) for k in range(3))
        r = random.Random(semente("placar", fid))
        return {"id": fid, "liga": liga, "casa": casa, "fora": fora, "inicio": ini, "p1x2": [p1, px, p2],
                "pou": [1 - pmenos, pmenos], "placar": [_sorteio_poisson(r, lc), _sorteio_poisson(r, lf)]}

    def entre(self, liga, ini, fim):
        """Os jogos de `liga` que começam entre ini e fim (ms)."""
        d = dt.datetime.fromtimestamp(ini / 1000, dt.timezone.utc).date() - dt.timedelta(days=1)
        ult = dt.datetime.fromtimestamp(fim / 1000, dt.timezone.utc).date()
        out = []
        while d <= ult:
            out.extend(j for j in self.do_dia(liga, d) if ini <= j["inicio"] <= fim)
            d += dt.timedelta(days=1)
        return out

    def por_id(self, fid):
        m = re.fullmatch(r"fx-([a-z]+)-(\d{8})-(\d+)", str(fid))
        if not m or m.group(1) not in LIGAS:
            return None
        d = dt.datetime.strptime(m.group(2), "%Y%m%d").date()
        return next((j for j in self.do_dia(m.group(1), d) if j["id"] == fid), None)


def odds_de(j, livro, horas_antes):
    """As odds de uma casa `horas_antes` do jogo: {"1x2": [3], "ou": [2]} (margem proporcional, com erro)."""
    m1, m2, casas = LIVROS.get(livro, LIVROS["bet365"])
    sig_pin = 0.004 + 0.025 * math.sqrt(horas_antes / 72)
    rp = random.Random(semente("odds", j["id"], "pinnacle", horas_antes))
    r = random.Random(semente("odds", j["id"], livro, horas_antes))
    out = {}
    for mk, ps, mg in (("1x2", j["p1x2"], m1), ("ou", j["pou"], m2)):
        erro_pin = [rp.gauss(0, sig_pin) for _ in ps]
        if livro == "pinnacle":
            q = [p * math.exp(e) for p, e in zip(ps, erro_pin)]
        else:  # a casa comum segue em parte o mercado (o erro da Pinnacle) e erra um pouco por conta própria
            q = [p * math.exp(0.7 * e + r.gauss(0, 0.05)) for p, e in zip(ps, erro_pin)]
        s = sum(q)
        out[mk] = [max(1.01, round(1 / (x / s * (1 + mg)), casas)) for x in q]
    return out


# ---------------------------------------------------------------------------------------------------- planilhas
CAB_EUROPA = ["Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "B365H", "B365D", "B365A", "PSH",
              "PSD", "PSA", "MaxH", "MaxD", "MaxA", "AvgH", "AvgD", "AvgA", "B365>2.5", "B365<2.5", "P>2.5", "P<2.5",
              "Max>2.5", "Max<2.5", "Avg>2.5", "Avg<2.5", "B365CH", "B365CD", "B365CA", "PSCH", "PSCD", "PSCA",
              "MaxCH", "MaxCD", "MaxCA", "AvgCH", "AvgCD", "AvgCA", "B365C>2.5", "B365C<2.5", "PC>2.5", "PC<2.5",
              "AvgC>2.5", "AvgC<2.5"]
CAB_NOVA = ["Country", "League", "Season", "Date", "Time", "Home", "Away", "HG", "AG", "Res", "PSCH", "PSCD", "PSCA",
            "MaxCH", "MaxCD", "MaxCA", "AvgCH", "AvgCD", "AvgCA", "BFECH", "BFECD", "BFECA"]


def _hora_uk(ms):
    """O inverso aproximado do que apostas.py faz: hora do Reino Unido (verão de abril a outubro)."""
    d = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)
    verao = 4 <= d.month <= 10
    return d + dt.timedelta(hours=1 if verao else 0)


def _media(a, b):
    return [round((x + y) / 2, 2) for x, y in zip(a, b)]


def planilha(fut, url, agora):
    """O CSV de uma planilha do football-data (str), ou levanta odds.Erro 404."""
    m = re.search(r"/mmz4281/(\d{4})/([A-Z0-9]+)\.csv$", url)
    n = re.search(r"/new/([A-Z]+)\.csv$", url)
    corte = agora - 2 * DIA  # as planilhas são atualizadas com atraso
    linhas = []
    if m:
        temp, div = m.group(1), m.group(2)
        liga = DIV_LIGA.get(div)
        if not liga or LIGAS[liga][1] != "europa":
            raise odds.Erro(f"HTTP 404 em {url}", 404)
        ano = 2000 + int(temp[:2])
        ini = int(dt.datetime(ano, 7, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
        fim = min(int(dt.datetime(ano + 1, 6, 30, tzinfo=dt.timezone.utc).timestamp() * 1000), corte)
        if ini > agora:
            raise odds.Erro(f"HTTP 404 em {url}", 404)
        sem_pinnacle = (div, temp) == ("F1", "2627")
        cab = [c for c in CAB_EUROPA if not (sem_pinnacle and (c.startswith("PS") or c.startswith("P>") or
                                                                 c.startswith("P<") or c.startswith("PC")))]
        fmt_data = "%d/%m/%y" if (div, temp) == ("E0", "2425") else "%d/%m/%Y"
        for j in fut.entre(liga, ini, fim):
            if j["inicio"] + 3 * HORA > corte:
                continue
            pin, b365 = odds_de(j, "pinnacle", PRE), odds_de(j, "bet365", PRE)
            pinc, b365c = odds_de(j, "pinnacle", 0.25), odds_de(j, "bet365", 0.25)
            avg, avgc = _media(pin["1x2"], b365["1x2"]), _media(pinc["1x2"], b365c["1x2"])
            hu = _hora_uk(j["inicio"])
            h, a = j["placar"]
            v = {"Div": div, "Date": hu.strftime(fmt_data), "Time": hu.strftime("%H:%M"), "HomeTeam": j["casa"],
                 "AwayTeam": j["fora"], "FTHG": h, "FTAG": a, "FTR": "H" if h > a else "D" if h == a else "A"}
            for pre, vals in (("B365", b365["1x2"]), ("PS", pin["1x2"]), ("Max", [max(x, y) for x, y in zip(pin["1x2"], b365["1x2"])]),
                              ("Avg", avg), ("B365C", b365c["1x2"]), ("PSC", pinc["1x2"]),
                              ("MaxC", [max(x, y) for x, y in zip(pinc["1x2"], b365c["1x2"])]), ("AvgC", avgc)):
                for suf, x in zip("HDA", vals):
                    v[f"{pre}{suf}"] = x
            for pre, vals in (("B365", b365["ou"]), ("P", pin["ou"]), ("Max", [max(x, y) for x, y in zip(pin["ou"], b365["ou"])]),
                              ("Avg", _media(pin["ou"], b365["ou"])), ("B365C", b365c["ou"]), ("PC", pinc["ou"]),
                              ("AvgC", _media(pinc["ou"], b365c["ou"]))):
                v[f"{pre}>2.5"], v[f"{pre}<2.5"] = vals
            linhas.append([v.get(c, "") for c in cab])
    elif n and n.group(1) == "BRA":
        cab = CAB_NOVA
        ini = int(dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
        for j in fut.entre("bra", ini, corte):
            if j["inicio"] + 3 * HORA > corte:
                continue
            pinc, b365c = odds_de(j, "pinnacle", 0.25), odds_de(j, "bet365", 0.25)
            hu = _hora_uk(j["inicio"])
            h, a = j["placar"]
            v = {"Country": "Brazil", "League": "Serie A", "Season": hu.year, "Date": hu.strftime("%d/%m/%Y"),
                 "Time": hu.strftime("%H:%M"), "Home": j["casa"], "Away": j["fora"], "HG": h, "AG": a,
                 "Res": "H" if h > a else "D" if h == a else "A"}
            for pre, vals in (("PSC", pinc["1x2"]), ("MaxC", [max(x, y) for x, y in zip(pinc["1x2"], b365c["1x2"])]),
                              ("AvgC", _media(pinc["1x2"], b365c["1x2"])), ("BFEC", [round(x * 1.02, 2) for x in pinc["1x2"]])):
                for suf, x in zip("HDA", vals):
                    v[f"{pre}{suf}"] = x
            linhas.append([v.get(c, "") for c in cab])
    else:
        raise odds.Erro(f"HTTP 404 em {url}", 404)
    texto = ",".join(cab) + "\n" + "\n".join(",".join(str(x) for x in ln) for ln in linhas) + "\n"
    if "/SP1.csv" in url:
        texto = "﻿" + texto
    return texto


# ---------------------------------------------------------------------------------------------------- OddsPapi
def _iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _data_param(x):
    s = str(x)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        s += "T00:00:00Z"
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1000)


def historico_livro(j, livro, agora):
    """{"markets": {...}} no formato que supomos do /historical-odds (só o que já tinha sido publicado em `agora`)."""
    precos = []
    for h in MOMENTOS:
        t = j["inicio"] - int(h * HORA)
        if t <= agora:
            precos.append((t, odds_de(j, livro, h)))
    if not precos:
        return {}

    def hist(mk, i):
        return {"players": {"0": [{"createdAt": _iso(t), "price": o[mk][i], "limit": 1000, "active": True}
                                  for t, o in precos]}}
    return {"bookmakerIsActive": True, "markets": {
        "101": {"outcomes": {"101": hist("1x2", 0), "102": hist("1x2", 1), "103": hist("1x2", 2)}},
        # como na resposta de verdade (log de 05/11/2026): sem o nome do mercado nem do resultado, só os ids
        "1010": {"outcomes": {"1010": hist("ou", 0), "1011": hist("ou", 1)}},
    }}


class Falso:
    """Mixin: as fontes das apostas (planilhas, OddsPapi e ESPN) no mundo de mentira."""

    def preparar(self):
        self.futebol = Futebol()
        self.contagem = Counter()
        if not hasattr(self, "chave"):
            self.chave = "chave-falsa"
        self.betano_br_vazia = True
        self._csv = {}

    def _contar_ap(self, tipo):
        if tipo in self.falhar:
            raise odds.Erro(f"falha de teste em {tipo}", 500)
        self.pedidos = getattr(self, "pedidos", 0) + 1
        self.contagem[tipo] += 1

    # ------------------------------------------------------------------ football-data
    def texto(self, url, tipo="csv"):
        self._contar_ap(tipo)
        k = (url, self.agora // DIA)
        if k not in self._csv:
            self._csv[k] = planilha(self.futebol, url, self.agora)
        return self._csv[k]

    # ------------------------------------------------------------------ ESPN
    def json_url(self, url, tipo="espn"):
        self._contar_ap(tipo)
        m = re.search(r"/soccer/([^/]+)/scoreboard\?dates=(\d{8})", url)
        if not m or m.group(1) not in ESPN_COD:
            raise odds.Erro("HTTP 404 em ESPN", 404)
        liga = ESPN_COD[m.group(1)]
        d = dt.datetime.strptime(m.group(2), "%Y%m%d").replace(tzinfo=dt.timezone.utc)
        ini = int(d.timestamp() * 1000)
        evs = []
        for j in self.futebol.entre(liga, ini, ini + DIA - 1):
            fim = j["inicio"] + 2 * HORA <= self.agora
            evs.append({"id": j["id"], "date": _iso(j["inicio"]).replace(":00.000Z", "Z"),
                        "status": {"type": {"completed": fim, "state": "post" if fim else "pre"}},
                        "competitions": [{"competitors": [
                            {"homeAway": "home", "score": str(j["placar"][0]) if fim else "0",
                             "team": {"displayName": ESPN.get(j["casa"], j["casa"])}},
                            {"homeAway": "away", "score": str(j["placar"][1]) if fim else "0",
                             "team": {"displayName": ESPN.get(j["fora"], j["fora"])}}]}]})
        return {"events": evs}

    # ------------------------------------------------------------------ BDM (config/bdm/)
    def bdm(self):
        hoje = dt.datetime.fromtimestamp(self.agora / 1000, dt.timezone.utc).date()
        out = []
        for k in range(10, -1, -1):
            d = hoje - dt.timedelta(days=k)
            if _ms_dia(d, BDM_PUBLICA_H) > self.agora:
                continue
            x = bdm_do_dia(self.futebol, d)
            if x:
                out.append(x)
        return out

    # ------------------------------------------------------------------ OddsPapi
    def oddspapi(self, caminho, **params):
        if not getattr(self, "chave", None):
            raise odds.Erro("falta a chave da OddsPapi")
        self._contar_ap("oddspapi")
        if caminho == "/sports":
            return [{"sportId": 10, "sportName": "Soccer", "slug": "soccer"}, {"sportId": 11, "sportName": "Basketball"}]
        if caminho == "/tournaments":
            if str(params.get("sportId")) != "10":
                return []
            return [{"tournamentId": t, "tournamentName": n, "tournamentSlug": n.lower().replace(" ", "-"),
                     "categoryName": c, "sportId": 10} for t, n, c, _l in TORNEIOS]
        if caminho == "/fixtures":
            liga = TORNEIO_LIGA.get(int(params.get("tournamentId") or 0))
            if not liga:
                return []
            ini, fim = _data_param(params["from"]), _data_param(params["to"])
            out = []
            for j in self.futebol.entre(liga, ini, fim):
                x = {"fixtureId": j["id"], "participant1Name": j["casa"], "participant2Name": j["fora"],
                     "sportId": 10, "tournamentId": LIGA_TORNEIO[liga], "startTime": _iso(j["inicio"]),
                     "statusId": 2 if j["inicio"] + 2 * HORA <= self.agora else 0, "hasOdds": True}
                if liga in PLACAR_NA_LISTA and j["inicio"] + 2 * HORA <= self.agora:
                    x["scores"] = {"fullTime": {"participant1": j["placar"][0], "participant2": j["placar"][1]}}
                out.append(x)
            return out
        if caminho == "/historical-odds":
            j = self.futebol.por_id(params.get("fixtureId"))
            if not j:
                raise odds.Erro("HTTP 404 em OddsPapi /historical-odds", 404)
            casas = [c for c in str(params.get("bookmakers") or "").split(",") if c][:3]
            livros = {}
            for c in casas:
                if c == "betano.bet.br" and self.betano_br_vazia:
                    livros[c] = {}
                elif c in LIVROS:
                    livros[c] = historico_livro(j, c, self.agora)
            return {"fixtureId": j["id"], "bookmakers": livros}
        raise odds.Erro(f"HTTP 404 em OddsPapi {caminho}", 404)


# ---------------------------------------------------------------------------------------------------- BDM
BDM_PUBLICA_H = 11  # UTC (8h em Brasília)
COMPETICAO = {"bra": "Brasileirão", "eng": "Premier League", "esp": "La Liga", "ita": "Série A", "ger": "Bundesliga",
              "fra": "Ligue 1", "lib": "Libertadores"}


def _iso_br(ms):
    return dt.datetime.fromtimestamp(ms / 1000 - 3 * 3600, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:00-03:00")


def bdm_do_dia(fut, d: dt.date):
    """O arquivo de config/bdm/<d>.json do mundo de mentira (None se não há jogos para palpitar)."""
    pub = _ms_dia(d, BDM_PUBLICA_H)
    jogos = []
    for liga in ("bra", "eng", "esp", "ita", "ger", "fra", "lib"):
        jogos += fut.entre(liga, pub + HORA, _ms_dia(d + dt.timedelta(days=1), 6))
    jogos.sort(key=lambda j: (j["inicio"], j["id"]))
    if not jogos:
        return None
    video = f"bdm{d:%y%m%d}FK"
    out, n = [], 0

    def add(**k):
        nonlocal n
        n += 1
        out.append({"id": f"{video}-{n}", **k})

    def citada(j, mk, i):
        return odds_de(j, "betano", 8)[mk][i]

    for k, j in enumerate(jogos[:2]):
        i = 0 if j["p1x2"][0] >= j["p1x2"][2] else 2
        trocar = k == 1 and d.day % 2 == 0  # a IA escreveu o visitante primeiro
        m, v = (j["fora"], j["casa"]) if trocar else (j["casa"], j["fora"])
        sel = "mandante" if (i == 0) != trocar else "visitante"
        add(mandante=m, visitante=v, competicao=COMPETICAO[j["liga"]], inicio=_iso_br(j["inicio"]), mercado="1x2",
            linha=None, selecao=sel, oddCitada=citada(j, "1x2", i), fora=False, motivo=None)
    if len(jogos) > 2:
        j = jogos[2]
        i = 0 if j["pou"][0] > 0.5 else 1
        add(mandante=j["casa"], visitante=j["fora"], competicao=COMPETICAO[j["liga"]], inicio=_iso_br(j["inicio"])[:10],
            mercado="ou", linha=2.5, selecao=["mais", "menos"][i], oddCitada=citada(j, "ou", i), fora=False, motivo=None)
    j = jogos[-1]
    add(mandante=j["casa"], visitante=j["fora"], competicao=COMPETICAO[j["liga"]], inicio=_iso_br(j["inicio"]),
        mercado="btts", linha=None, selecao="sim", oddCitada=1.8, fora=False, motivo=None)
    add(mandante=j["casa"], visitante=j["fora"], competicao=COMPETICAO[j["liga"]], inicio=_iso_br(j["inicio"]),
        mercado="ou", linha=1.5, selecao="mais", oddCitada=None, fora=True, motivo="ao_vivo")
    add(mandante="Ajax", visitante="PSV", competicao="Eredivisie", inicio=_iso_br(pub + 6 * HORA), mercado="1x2",
        linha=None, selecao="visitante", oddCitada=2.4, fora=False, motivo=None)
    return {"versao": 1, "data": d.isoformat(), "video": {"id": video, "publicado": _iso(pub)}, "palpites": out}


class Avulsa(Falso):
    """As mesmas fontes sem o cliente das formas (o horário vem de `cli.agora`)."""

    def __init__(self, cli):
        self._cli = cli
        self.pedidos = 0
        self.falhar = getattr(cli, "falhar", set())
        self.preparar()

    @property
    def agora(self):
        return self._cli.agora
