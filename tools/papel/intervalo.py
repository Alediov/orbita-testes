"""O robô do intervalo (pedido do Alediov, 22/11/2026): a cada 15 minutos, nos horários de jogo (`intervalo.yml`),
guarda as odds AO VIVO da API-Football de cartões, escanteios e gols quando um jogo dos campeonatos acompanhados chega ao
intervalo (e de novo perto dos 75', para o "gol no fim"), e tira a foto de fechamento das odds de antes do jogo dos
palpites do Theo (até 40 min antes do início). Só leitura: nenhuma aposta de verdade, nenhuma conta.

Gasta pouco do plano grátis (100 pedidos por dia, a chave no segredo APIFOOTBALL_KEY, no cabeçalho, nunca no log): a
lista de jogos do dia a cada 6 h e um `/odds/live` (todos os jogos rolando num pedido só) SÓ quando algum jogo
acompanhado pode estar no intervalo ou perto dos 75'; no máximo LIMITE_DIA por dia e nunca abaixo de FOLGA restantes.

Saída no ramo órfão `intervalo`: `intervalo.json` {v, agora, cap {id: {ms, liga, c, f, ht {t, gols, m}, m75 {t, min,
gols, m}}}, theo {id: [fotos de antes do jogo]}} (m = {mercado: [[texto, linha, odd]]}), `estado.json` e `log.txt`.
Quem lê: as apostas (o fechamento dos palpites do Theo) e o Observatório dos cartões (as contas do intervalo).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import af  # noqa: E402

MIN = 60 * 1000
HORA = 60 * MIN
DIA = 24 * HORA
LIMITE_DIA = 55              # pedidos do robô por dia (as apostas e os árbitros usam o resto dos 100)
FOLGA = 12                   # não pede se a API-Football disser que restam menos que isso hoje
LISTA_CADA = 6 * HORA
JANELA_HT = (44, 68)         # minutos depois do início em que o jogo pode estar no intervalo
JANELA_75 = (86, 106)        # …e perto dos 75' (com o intervalo e os acréscimos)
TENTATIVAS = 4               # pedidos ao vivo por jogo e momento sem achar o que guardar: desiste (não gasta à toa)
MIN_75 = (70, 86)            # o minuto do jogo que vale como "perto dos 75'"
FECH_ANTES = 40 * MIN        # a foto de fechamento dos palpites do Theo: até 40 min antes do início
GUARDA_CAP = 30 * DIA
GUARDA_THEO = 10 * DIA
LOG_LINHAS = 400
RX_CART = re.compile(r"card", re.I)
RX_ESC = re.compile(r"corner", re.I)
RX_GOL = re.compile(r"over/under line|match goals|over/under$|goals over/under", re.I)


def dia(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date().isoformat()


class Cliente:
    """A API-Football de verdade: (json, pedidos restantes hoje)."""

    def __init__(self, chave):
        self.chave = chave

    def pedir(self, url):
        req = urllib.request.Request(url, headers={af.CAB: self.chave, "User-Agent": "orbita-testes"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                resto = r.headers.get("x-ratelimit-requests-remaining")
                return json.loads(r.read().decode("utf-8", "replace")), (int(resto) if resto and resto.isdigit() else None)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise RuntimeError(str(e).replace(self.chave, "***")) from None


def _so_linhas(m):
    """Só os mais/menos com linha dos mercados de cartões, escanteios e gols (o resto não serve e pesa)."""
    out = {}
    for nome, vs in (m or {}).items():
        if not (RX_CART.search(nome) or RX_ESC.search(nome) or RX_GOL.search(nome)):
            continue
        xs = [[t, ln, o] for t, ln, o in vs if t in ("over", "under") and ln is not None]
        if xs:
            out[nome] = xs
    return out


class Robo:
    def __init__(self, E, cli, agora, log):
        self.E, self.cli, self.agora, self.log = E, cli, agora, log
        for k in ("dias", "cap", "theo", "uso"):
            E.setdefault(k, {})
        E.setdefault("fech", [])
        hoje = dia(agora)
        E["uso"] = {hoje: int(E["uso"].get(hoje, 0))}
        self.hoje = hoje

    def pedir(self, url):
        E = self.E
        if E["uso"][self.hoje] >= LIMITE_DIA or (E.get("resto") is not None and E.get("restoDia") == self.hoje
                                                 and E["resto"] < FOLGA):
            return None
        E["uso"][self.hoje] += 1
        try:
            r, resto = self.cli.pedir(url)
        except Exception as e:  # noqa: BLE001
            self.log(f"erro em {url.split('?')[0].replace(af.BASE, '')}: {e}")
            return None
        if resto is not None:
            E["resto"], E["restoDia"] = resto, self.hoje
        if (r or {}).get("errors"):
            self.log(f"a API-Football recusou {url.split('?')[0].replace(af.BASE, '')}: {str(r['errors'])[:200]}")
            return None
        return r

    def lista(self, d):
        x = self.E["dias"].get(d)
        if not x or self.agora - int(x.get("em") or 0) >= LISTA_CADA:
            r = self.pedir(af.url_dia(d))
            if r is not None:
                todos = af.jogos_do_dia(r)
                x = self.E["dias"][d] = {"em": self.agora, "j": todos}
                self.log(f"lista de {d}: {len(todos)} jogos, {sum(1 for j in todos if j['liga'] in af.LIGA_AF)} acompanhados")
        return (x or {}).get("j") or []

    def acompanhados(self):
        out = []
        for d in {dia(self.agora - 3 * HORA), self.hoje}:
            out += [j for j in self.lista(d) if j["liga"] in af.LIGA_AF]
        return {j["id"]: j for j in out}

    # ---------------------------------------------------------------- o fechamento dos palpites do Theo
    def theo(self, palpites):
        """`palpites`: [(mandante, visitante, início em ms ou None, dia AAAA-MM-DD)] dos palpites que o teste precifica."""
        E = self.E
        feitos = set(E["fech"])
        for m, v, ini, d in palpites:
            dias = [dia(ini)] if ini else [d, (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()]
            for dd in dias:
                if abs((dt.date.fromisoformat(dd) - dt.date.fromisoformat(self.hoje)).days) > 1:
                    continue
                if not ini and dd not in E["dias"]:
                    continue  # sem a hora do palpite: só pelos dias que a lista já tem (não gasta pedido à toa)
                j, _inv = af.achar(self.lista(dd), m, v, ini)
                if not j:
                    continue
                if j["id"] in feitos or not (self.agora < j["ms"] <= self.agora + FECH_ANTES):
                    break
                r = self.pedir(af.url_odds(j["id"]))
                foto = af.odds_prejogo(r) if r is not None else None
                feitos.add(j["id"])
                if foto:
                    E["theo"].setdefault(str(j["id"]), []).append({"t": self.agora, **foto, "fech": True})
                    self.log(f"fechamento do palpite {j['casa']} × {j['fora']}: {foto['casa']}")
                break
        E["fech"] = sorted(feitos)[-200:]

    # ---------------------------------------------------------------- o intervalo e o 75'
    def ao_vivo(self):
        E = self.E
        jogos = self.acompanhados()
        perto = []
        for j in jogos.values():
            mins = (self.agora - j["ms"]) / MIN
            c = E["cap"].get(str(j["id"])) or {}
            tent = E.setdefault("tent", {})
            if JANELA_HT[0] <= mins <= JANELA_HT[1] and "ht" not in c and tent.get(f"{j['id']}:ht", 0) < TENTATIVAS:
                perto.append((j, "ht"))
            elif JANELA_75[0] <= mins <= JANELA_75[1] and "m75" not in c and tent.get(f"{j['id']}:m75", 0) < TENTATIVAS:
                perto.append((j, "m75"))
        if not perto:
            return 0
        for j, fase in perto:
            E["tent"][f"{j['id']}:{fase}"] = E["tent"].get(f"{j['id']}:{fase}", 0) + 1
        E["tent"] = {k: v for k, v in E["tent"].items() if int(k.split(":")[0]) in jogos}
        r = self.pedir(af.url_ao_vivo())
        if r is None:
            return 0
        vivos = af.ao_vivo(r)
        if not E.get("viuAoVivo") and vivos:
            nomes = sorted({n for x in vivos for n in x["m"]})
            self.log(f"mercados ao vivo de cartões, escanteios e gols: {nomes[:40]}")
            E["viuAoVivo"] = True
        n = 0
        for x in vivos:
            j = jogos.get(x["id"])
            if not j:
                continue
            k = str(x["id"])
            c = E["cap"].setdefault(k, {"ms": j["ms"], "liga": af.LIGA_AF[j["liga"]], "c": j["casa"], "f": j["fora"]})
            if af.no_intervalo(x) and "ht" not in c:
                c["ht"] = {"t": self.agora, "gols": x["gols"], "m": _so_linhas(x["m"])}
                n += 1
                self.log(f"intervalo: {j['casa']} × {j['fora']} ({x['gols'][0]} × {x['gols'][1]}), "
                         f"{len(c['ht']['m'])} mercados")
            elif str(x["st"]).upper() == "2H" and x.get("min") and MIN_75[0] <= int(x["min"]) <= MIN_75[1] and "m75" not in c:
                c["m75"] = {"t": self.agora, "min": int(x["min"]), "gols": x["gols"],
                            "m": {k2: v for k2, v in _so_linhas(x["m"]).items() if RX_GOL.search(k2)}}
                n += 1
            if not c.get("ht") and not c.get("m75"):
                E["cap"].pop(k, None)
        return n

    def limpar(self):
        E = self.E
        E["cap"] = {k: c for k, c in E["cap"].items() if c["ms"] >= self.agora - GUARDA_CAP}
        E["theo"] = {k: v for k, v in E["theo"].items() if v and v[-1]["t"] >= self.agora - GUARDA_THEO}
        d0 = dia(self.agora - 2 * DIA)
        E["dias"] = {d: x for d, x in E["dias"].items() if d >= d0}

    def saida(self):
        return {"v": 1, "agora": self.agora, "cap": self.E["cap"], "theo": self.E["theo"]}


# ------------------------------------------------------------------------------------ pela The Odds API (26/11/2026)
LIMITE_TOA_DIA = 14          # créditos por dia (500 por mês; sobra para a sonda e os imprevistos)
FOLGA_TOA = 25               # não pede se restarem menos créditos que isso no mês
AGENDA_CADA = 60 * MIN       # a agenda de cada campeonato (ESPN, grátis) quando nenhum jogo está rolando
EVENTOS_CADA = 30 * MIN      # a lista de eventos da The Odds API (grátis)
JANELA_ESPN = (40, 125)      # minutos depois do início em que a ESPN é olhada a cada volta
TENT_TOA = 3


def json_url(url, prazo=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (orbita-testes)"})
    with urllib.request.urlopen(req, timeout=prazo) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


class RoboTOA:
    """O robô do intervalo pela The Odds API: o placar, o intervalo e o minuto pela ESPN (grátis, a cada volta só dos
    campeonatos com jogo rolando) e, no intervalo e perto dos 75' (só empatado), as odds ao vivo do jogo (cartões,
    escanteios e gols) pelas odds do evento. Mesma saída (`cap`) que o Observatório já lê."""

    def __init__(self, E, cli, agora, log, buscar=json_url):
        import theodds as T
        self.T, self.E, self.cli, self.agora, self.log, self.buscar = T, E, cli, agora, log, buscar
        for k in ("cap", "theo"):
            E.setdefault(k, {})
        X = E.setdefault("toa", {})
        for k in ("agenda", "ev", "tent"):
            X.setdefault(k, {})
        self.hoje = dia(agora)
        X["uso"] = {self.hoje: int((X.get("uso") or {}).get(self.hoje, 0))}
        self.X = X

    def creditos(self, n):
        X = self.X
        return X["uso"][self.hoje] + n <= LIMITE_TOA_DIA and (X.get("resto") is None or X["resto"] - n >= FOLGA_TOA)

    def pedir(self, caminho, **q):
        try:
            r, resto = self.cli.pedir(caminho, **q)
        except Exception as e:  # noqa: BLE001
            self.log(f"The Odds API, erro em {caminho.split('/odds')[0]}: {e}")
            return None
        ult = getattr(self.cli, "ultimo", None)
        if ult is None and resto is not None and self.X.get("resto") is not None:
            ult = max(0, self.X["resto"] - resto)
        if resto is not None:
            self.X["resto"] = resto
        self.X["uso"][self.hoje] += int(ult or 0)
        return r

    def agenda(self, liga):
        """Os jogos de hoje e de ontem (UTC) do campeonato pela ESPN; refeita a cada volta se algum está rolando."""
        T, X = self.T, self.X
        cod = T.LIGAS[liga][1]
        a = X["agenda"].get(liga) or {}
        rolando = any(JANELA_ESPN[0] <= (self.agora - j["ms"]) / MIN <= JANELA_ESPN[1] for j in a.get("j") or [] if j.get("ms"))
        if a and not rolando and self.agora - int(a.get("em") or 0) < AGENDA_CADA:
            return a.get("j") or []
        js = {}
        for d in sorted({dia(self.agora - 6 * HORA), self.hoje}):
            try:
                for j in T.espn(self.buscar(T.URL_ESPN.format(liga=cod, dia=d.replace("-", "")))):
                    if j.get("ms"):
                        js[j["id"]] = j
            except Exception as e:  # noqa: BLE001
                self.log(f"ESPN {cod} {d}: {type(e).__name__}: {str(e)[:120]}")
                return a.get("j") or []
        j = sorted(js.values(), key=lambda x: x["ms"])
        X["agenda"][liga] = {"em": self.agora, "j": j}
        return j

    def evento(self, liga, j):
        """O evento da The Odds API do jogo da ESPN (pela lista grátis de eventos), ou None."""
        from apostas import mesmo_time
        T, X = self.T, self.X
        esporte = T.LIGAS[liga][0]
        ev = X["ev"].get(esporte) or {}
        def achar(lista):
            return next((e for e in lista if abs(e["ms"] - j["ms"]) <= 3 * HORA and mesmo_time(e["casa"], j["casa"])
                         and mesmo_time(e["fora"], j["fora"])), None)
        e = achar(ev.get("l") or [])
        if e or self.agora - int(ev.get("em") or 0) < 5 * MIN:
            return e
        r = self.pedir(f"/sports/{esporte}/events")
        if r is None:
            return None
        lista = T.eventos(r)
        X["ev"][esporte] = {"em": self.agora, "l": lista}
        e = achar(lista)
        if not e:
            self.log(f"sem o evento da The Odds API de {j['casa']} × {j['fora']} ({len(lista)} eventos em {esporte})")
        return e

    def odds(self, liga, e, mercados):
        r = self.pedir(f"/sports/{self.T.LIGAS[liga][0]}/events/{e['id']}/odds", regions="eu",
                       markets=",".join(mercados), oddsFormat="decimal")
        if r is None:
            return None
        m = self.T.linhas(r)
        if not self.X.get("viu"):
            casas = sorted({b.get("key") for b in (r or {}).get("bookmakers") or []}) if isinstance(r, dict) else []
            self.log(f"The Odds API ao vivo, 1ª resposta: casas {casas[:12]}, mercados {sorted(m)[:12]}")
            self.X["viu"] = True
        return m

    def ao_vivo(self):
        E, X = self.E, self.X
        n = 0
        vivos = set()
        for liga in self.T.LIGAS:
            for j in self.agenda(liga):
                mins = (self.agora - j["ms"]) / MIN
                if not (JANELA_ESPN[0] <= mins <= JANELA_ESPN[1]) or (j.get("st") != "in" and not j.get("ht")):
                    continue
                k = "e" + j["id"]
                vivos.add(k)
                c = E["cap"].get(k) or {}
                fase = None
                if j.get("ht") and "ht" not in c:
                    fase = "ht"
                elif (j.get("periodo") == 2 and j.get("min") and MIN_75[0] <= j["min"] <= MIN_75[1] and "m75" not in c
                      and None not in j["gols"] and j["gols"][0] == j["gols"][1]):
                    fase = "m75"
                if not fase or X["tent"].get(f"{k}:{fase}", 0) >= TENT_TOA:
                    continue
                mercados = (["alternate_totals_cards", "alternate_totals_corners"]
                            + (["alternate_totals"] if j["gols"] == [0, 0] else [])) if fase == "ht" else ["alternate_totals"]
                if not self.creditos(len(mercados)):
                    if not X.get("avisou") == self.hoje:
                        self.log(f"sem créditos para {j['casa']} × {j['fora']} ({X['uso'][self.hoje]} hoje, restam {X.get('resto')})")
                        X["avisou"] = self.hoje
                    continue
                X["tent"][f"{k}:{fase}"] = X["tent"].get(f"{k}:{fase}", 0) + 1
                e = self.evento(liga, j)
                m = self.odds(liga, e, mercados) if e else None
                if not m:
                    continue
                c = E["cap"].setdefault(k, {"ms": j["ms"], "liga": liga, "c": j["casa"], "f": j["fora"], "fonte": "theodds"})
                if fase == "ht":
                    c["ht"] = {"t": self.agora, "gols": j["gols"], "m": _so_linhas(m)}
                    self.log(f"intervalo: {j['casa']} × {j['fora']} ({j['gols'][0]} × {j['gols'][1]}), {len(c['ht']['m'])} mercados")
                else:
                    c["m75"] = {"t": self.agora, "min": j["min"], "gols": j["gols"],
                                "m": {k2: v for k2, v in _so_linhas(m).items() if RX_GOL.search(k2)}}
                    self.log(f"75': {j['casa']} × {j['fora']} ({j['gols'][0]} × {j['gols'][1]}, {j['min']}')")
                n += 1
        X["tent"] = {k: v for k, v in X["tent"].items() if k.split(":")[0] in vivos}
        return n

    def limpar(self):
        E = self.E
        E["cap"] = {k: c for k, c in E["cap"].items() if c["ms"] >= self.agora - GUARDA_CAP}
        E["theo"] = {k: v for k, v in E["theo"].items() if v and v[-1]["t"] >= self.agora - GUARDA_THEO}

    def saida(self):
        return {"v": 1, "agora": self.agora, "cap": self.E["cap"], "theo": self.E["theo"]}


def palpites_do_theo(agora, pasta=None):
    """Os palpites que o teste precifica (o mesmo filtro das apostas), dos arquivos de config/bdm/."""
    from apostas import PASTA_BDM, ler_bdm, palpite_bdm, precificavel
    out = []
    for arq in ler_bdm(pasta or PASTA_BDM, agora):
        d = str(arq.get("data") or "")[:10]
        for bruto in arq.get("palpites") or []:
            pk = palpite_bdm(bruto, d, None)
            if pk and precificavel(pk)[0] and (pk["i"] is None or pk["i"] > agora):
                out.append((pk["m"], pk["v"], pk["i"], pk["dia"]))
    return out


def ler(caminho, padrao):
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", required=True)
    a = ap.parse_args()
    chave = (os.environ.get("APIFOOTBALL_KEY") or "").strip()
    chave_toa = (os.environ.get("ODDSAPI_KEY") or "").strip()
    os.makedirs(a.dados, exist_ok=True)
    linhas = []
    agora = int(time.time() * 1000)

    def log(x):
        s = f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} {x}"
        print(s)
        linhas.append(s)
    E = ler(os.path.join(a.dados, "estado.json"), {})
    if chave:
        R = Robo(E, Cliente(chave), agora, log)
        try:
            R.theo(palpites_do_theo(agora))
        except Exception as e:  # noqa: BLE001
            log(f"fechamento do Theo: {type(e).__name__}: {e}")
        n = R.ao_vivo()
        R.limpar()
        log(f"rodada: {n} capturas, {E['uso'].get(R.hoje, 0)} pedidos hoje"
            + (f", restam {E['resto']} na API-Football" if E.get("resto") is not None else ""))
    elif chave_toa:
        import theodds
        R = RoboTOA(E, theodds.Cliente(chave_toa), agora, log)
        n = R.ao_vivo()
        R.limpar()
        if n or R.X["uso"][R.hoje]:
            log(f"rodada: {n} capturas, {R.X['uso'][R.hoje]} créditos hoje, restam {R.X.get('resto')} na The Odds API")
    else:
        log("sem a chave ODDSAPI_KEY nem a APIFOOTBALL_KEY")
        return 0
    with open(os.path.join(a.dados, "estado.json"), "w", encoding="utf-8") as f:
        json.dump(E, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(a.dados, "intervalo.json"), "w", encoding="utf-8") as f:
        json.dump(R.saida(), f, ensure_ascii=False, separators=(",", ":"))
    velho = []
    try:
        with open(os.path.join(a.dados, "log.txt"), encoding="utf-8") as f:
            velho = f.read().splitlines()
    except OSError:
        pass
    with open(os.path.join(a.dados, "log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join((velho + linhas)[-LOG_LINHAS:]) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
