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
    os.makedirs(a.dados, exist_ok=True)
    linhas = []
    agora = int(time.time() * 1000)

    def log(x):
        s = f"{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} {x}"
        print(s)
        linhas.append(s)
    if not chave:
        log("sem a chave APIFOOTBALL_KEY")
        return 0
    E = ler(os.path.join(a.dados, "estado.json"), {})
    R = Robo(E, Cliente(chave), agora, log)
    try:
        R.theo(palpites_do_theo(agora))
    except Exception as e:  # noqa: BLE001
        log(f"fechamento do Theo: {type(e).__name__}: {e}")
    n = R.ao_vivo()
    R.limpar()
    log(f"rodada: {n} capturas, {E['uso'].get(R.hoje, 0)} pedidos hoje"
        + (f", restam {E['resto']} na API-Football" if E.get("resto") is not None else ""))
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
