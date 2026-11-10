"""Mercados de previsão de MENTIRA (sem rede; semente fixa): a Gamma, o CLOB e a Data API da Polymarket, a lista da
Kalshi e a busca da Manifold, nos formatos que `previsao.py` lê. Nada aqui é dado real: perguntas, times, candidatos,
moedas e carteiras são inventados.

- ~700 mercados de sim ou não entre 200 dias antes e 120 dias depois do começo do mundo de mentira (20/09/2026), cada
  um com o preço inicial, o resultado (com um viés do azarão: os de 10% ou menos acontecem menos do que o preço diz) e
  um caminho em logit que anda para o resultado perto do fim (com ruído de 12 em 12 h);
- livro de cada lado em volta do preço (3 níveis, o 1º pequeno para haver deslize); taxa só nos de Cripto;
- 40 carteiras no ranking da semana e as negociações de cada uma (compras a cada ~9 h, as melhores acertam mais);
- a Kalshi tem 1 de cada 4 mercados (fora os esportes) com a pergunta reescrita e alguns com 7 pontos de diferença, e
  mercados "parecidos" com outro número (que o casamento conservador NÃO deve casar); a Manifold, 1 de cada 3.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import random
import urllib.parse

import rede

HORA = 3_600_000
DIA = 86_400_000
PASSO = 12 * HORA
CATS = [("Esportes", 3), ("Política", 2), ("Cripto", 2), ("Economia", 1), ("Cultura", 1), ("Ciência e tecnologia", 1), ("Outros", 1)]
EN = {"Esportes": "Sports", "Política": "Politics", "Cripto": "Crypto", "Economia": "Economics", "Cultura": "Culture",
      "Ciência e tecnologia": "Science", "Outros": None}
MESES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def _sig(x):
    return 1 / (1 + math.exp(-x))


def _logit(p):
    return math.log(p / (1 - p))


def _iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pergunta(cat, i, r, fim):
    mes = MESES[dt.datetime.fromtimestamp(fim / 1000, dt.timezone.utc).month - 1]
    if cat == "Esportes":
        return f"Will Clube Alfa{i} beat Clube Beta{i} in the Liga Zeta match?"
    if cat == "Política":
        return f"Will candidate Gamma{i} win the presidential election in Republica{i % 17}?"
    if cat == "Cripto":
        return f"Will the TESTCOIN{i} token price reach ${(i % 9 + 1) * 10}k by {mes}?"
    if cat == "Economia":
        return f"Will the central bank of Pais{i} cut interest rates in {mes}?"
    if cat == "Cultura":
        return f"Will the movie Filme{i} win the award for best picture?"
    if cat == "Ciência e tecnologia":
        return f"Will the rocket Foguete{i} launch successfully before {mes}?"
    return f"Will the river Rio{i} flood the city of Cidade{i} before {mes}?"


class Falso:
    def preparar(self):
        import falso_mercado
        t0 = falso_mercado.T0
        r = random.Random(9091)
        ini_mundo, fim_mundo = t0 - 200 * DIA, t0 + 120 * DIA
        pesos = [c for c, w in CATS for _ in range(w)]
        self._pm = []
        for i in range(700):
            dur = int(r.choice([3, 5, 7, 10, 14, 21, 30, 45, 60]) * DIA * (0.8 + 0.4 * r.random()))
            ini = int(ini_mundo + r.random() * (fim_mundo - ini_mundo - dur))
            fim = ini + dur
            cat = r.choice(pesos)
            p0 = min(0.97, max(0.03, r.betavariate(0.55, 0.55)))
            pt = p0 if 0.12 < p0 < 0.88 else (p0 * 0.8 if p0 <= 0.12 else 1 - (1 - p0) * 0.8)
            o = 1 if r.random() < pt else 0
            surpresa = r.random() < 0.07  # o favorito até a véspera perde no fim (a cauda)
            ruido, x = [], 0.0
            for _ in range(dur // PASSO + 2):
                x += r.gauss(0, 0.22)
                ruido.append(x)
            self._pm.append({"i": i, "id": str(530000 + i), "ini": ini, "fim": fim, "cat": cat, "p0": p0, "o": o,
                             "ruido": ruido, "surpresa": surpresa, "vol": 10 ** r.uniform(3.5, 6.5), "q": _pergunta(cat, i, r, fim),
                             "cond": "0x" + hashlib.sha256(f"cond{i}".encode()).hexdigest(),
                             "toks": [str(7_000_000_000 + i * 2), str(7_000_000_001 + i * 2)]})
        self._por_id = {m["id"]: m for m in self._pm}
        self._por_tok = {t: (m, k) for m in self._pm for k, t in enumerate(m["toks"])}
        self._por_cond = {m["cond"]: m for m in self._pm}
        # as carteiras: endereços de mentira, habilidade de 0,35 a 0,8
        self._carteiras = []
        for k in range(40):
            end = "0x" + hashlib.sha256(f"carteira{k}".encode()).hexdigest()[:40]
            self._carteiras.append({"end": end, "hab": 0.35 + 0.45 * random.Random(k).random(), "k": k})

    # ------------------------------------------------------------------ o preço
    def _p(self, m, t):
        t = max(m["ini"], min(t, m["fim"]))
        fr = (t - m["ini"]) / max(1, m["fim"] - m["ini"])
        x0 = _logit(m["p0"])
        alvo = 4.6 if m["o"] else -4.6
        if m["surpresa"] and t < m["fim"] - 12 * HORA:
            alvo = -alvo * 0.7
        j = (t - m["ini"]) / PASSO
        a = int(j)
        ru = m["ruido"][a] + (m["ruido"][min(a + 1, len(m["ruido"]) - 1)] - m["ruido"][a]) * (j - a)
        x = x0 + fr ** 3 * (alvo - x0) + ru * (1 - fr) * 0.8
        return min(0.995, max(0.005, _sig(x)))

    def _gamma_json(self, m):
        ag = self.agora
        fechado = m["fim"] <= ag
        p = self._p(m, ag)
        precos = (["1", "0"] if m["o"] else ["0", "1"]) if fechado else [f"{p:.4f}", f"{1 - p:.4f}"]
        d = {"id": m["id"], "question": m["q"], "conditionId": m["cond"], "slug": f"mercado-{m['i']}",
             "startDate": _iso(m["ini"]), "endDate": _iso(m["fim"]), "outcomes": '["Yes", "No"]',
             "outcomePrices": str(precos).replace("'", '"'), "clobTokenIds": str(m["toks"]).replace("'", '"'),
             "volumeNum": round(m["vol"], 2), "volume24hr": 0 if fechado else round(m["vol"] / 20, 2),
             "liquidityNum": round(m["vol"] / 4, 2), "closed": fechado, "active": not fechado, "enableOrderBook": True,
             "acceptingOrders": not fechado, "bestBid": None if fechado else round(max(0.001, p - 0.005), 3),
             "bestAsk": None if fechado else round(min(0.999, p + 0.005), 3),
             "events": [{"title": m["q"], "slug": f"evento-{m['i']}"}],
             "takerBaseFee": 100 if m["cat"] == "Cripto" else 0}
        if EN[m["cat"]] and m["i"] % 2 == 0:
            d["category"] = EN[m["cat"]]
        if fechado:
            d["closedTime"] = _iso(m["fim"]).replace("T", " ").replace("Z", "+00")
            d["umaResolutionStatus"] = "resolved"
        return d

    # ------------------------------------------------------------------ Gamma
    def gamma(self, caminho):
        self._contar("gamma")
        u = urllib.parse.urlparse(caminho)
        q = urllib.parse.parse_qs(u.query)
        um = lambda k, d=None: (q.get(k) or [d])[0]  # noqa: E731
        ag = self.agora
        xs = [m for m in self._pm if m["ini"] <= ag]
        if "id" in q:
            ids = set(q["id"])
            xs = [m for m in xs if m["id"] in ids]
            if um("closed") != "true":
                xs = [m for m in xs if m["fim"] > ag]
        elif "condition_ids" in q:
            xs = [m for m in xs if m["cond"] in set(q["condition_ids"])]
        else:
            if um("closed") == "true":
                xs = [m for m in xs if m["fim"] <= ag]
            elif um("closed") == "false" or um("active") == "true":
                xs = [m for m in xs if m["fim"] > ag]
        from previsao import ms_de
        if um("end_date_min"):
            xs = [m for m in xs if m["fim"] >= ms_de(um("end_date_min"))]
        if um("end_date_max"):
            xs = [m for m in xs if m["fim"] <= ms_de(um("end_date_max"))]
        if um("volume_num_min"):
            xs = [m for m in xs if m["vol"] >= float(um("volume_num_min"))]
        if um("liquidity_num_min"):
            xs = [m for m in xs if m["vol"] / 4 >= float(um("liquidity_num_min"))]
        chave = {"volume24hr": lambda m: m["vol"], "volumeNum": lambda m: m["vol"], "endDate": lambda m: m["fim"]}.get(um("order"), lambda m: m["i"])
        xs.sort(key=chave, reverse=um("ascending") == "false")
        off, lim = int(um("offset", 0)), int(um("limit", 100))
        return [self._gamma_json(m) for m in xs[off:off + lim]]

    # ------------------------------------------------------------------ CLOB
    def clob(self, caminho):
        self._contar("clob")
        u = urllib.parse.urlparse(caminho)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/book":
            m, k = self._por_tok[q["token_id"][0]]
            p = self._p(m, self.agora)
            p = p if k == 0 else 1 - p
            a = round(min(0.999, p + 0.005), 3)
            b = round(max(0.001, p - 0.005), 3)
            asks = [{"price": f"{min(0.999, a + d):.3f}", "size": f"{s}"} for d, s in ((0.02, 2000), (0.01, 400), (0, 120))]
            bids = [{"price": f"{max(0.001, b - d):.3f}", "size": f"{s}"} for d, s in ((0.02, 2000), (0.01, 300), (0, 12))]
            return {"market": m["cond"], "asset_id": m["toks"][k], "bids": bids, "asks": asks, "timestamp": str(self.agora)}
        if u.path == "/prices-history":
            if "market" not in q or q["market"][0] not in self._por_tok:
                raise rede.Erro("HTTP 400 em CLOB de mentira: market", 400)
            if ("interval" in q) == ("startTs" in q):  # um OU outro, como a API
                raise rede.Erro("HTTP 400 em CLOB de mentira: interval ou startTs/endTs", 400)
            if "startTs" in q and getattr(self, "pv_so_intervalo", False):  # a reserva: só o interval funciona
                raise rede.Erro("HTTP 400 em CLOB de mentira: startTs", 400)
            m, k = self._por_tok[q["market"][0]]
            fim_ = min(self.agora, m["fim"])
            if "interval" in q:
                dur = {"max": 10 ** 13, "1m": 30 * DIA, "1w": 7 * DIA, "1d": DIA}[q["interval"][0]]
                a, b = max(m["ini"], fim_ - dur), fim_
            else:
                a = max(int(q["startTs"][0]) * 1000, m["ini"])
                b = min(int(q["endTs"][0]) * 1000, fim_)
            f = max(1, int(q.get("fidelity", ["60"])[0])) * 60_000
            out, t = [], (a // f) * f + f
            while t <= b and len(out) < 1500:
                p = self._p(m, t)
                out.append({"t": t // 1000, "p": round(p if k == 0 else 1 - p, 4)})
                t += f
            return {"history": out}
        raise rede.Erro(f"CLOB de mentira: {u.path}")

    # ------------------------------------------------------------------ Data API
    def _trades(self, c):
        """As compras (e algumas vendas) da carteira nos 10 dias antes de agora, a mais nova primeiro."""
        ag, out = self.agora, []
        base = (ag // (9 * HORA)) * (9 * HORA)
        for j in range(27):
            t = base - j * 9 * HORA + (hash((c["k"], j)) % 3) * HORA
            t = base - j * 9 * HORA + (c["k"] * 7919 + int(t // HORA)) % 5 * HORA
            if t > ag:
                continue
            r = random.Random(c["k"] * 100_003 + int(t // HORA))
            abertos = [m for m in self._pm if m["ini"] < t < m["fim"] - DIA and m["cat"] != "Esportes"]
            if not abertos:
                continue
            m = r.choice(abertos)
            certo = r.random() < c["hab"]
            lado = (0 if m["o"] else 1) if certo else (1 if m["o"] else 0)
            p = self._p(m, t)
            p = p if lado == 0 else 1 - p
            out.append({"proxyWallet": c["end"], "side": "BUY", "asset": m["toks"][lado], "conditionId": m["cond"],
                        "size": round(r.uniform(80, 3000), 2), "price": round(p, 4), "timestamp": t // 1000,
                        "title": m["q"], "outcome": "Yes" if lado == 0 else "No", "outcomeIndex": lado,
                        "pseudonym": f"Apelido-{c['k']}", "transactionHash": "0x" + "ab" * 32})
            if r.random() < 0.25 and t + 2 * HORA <= ag:
                p2 = self._p(m, t + 2 * HORA)
                out.append({**out[-1], "side": "SELL", "price": round(p2 if lado == 0 else 1 - p2, 4),
                            "timestamp": (t + 2 * HORA) // 1000})
        out.sort(key=lambda x: -x["timestamp"])
        return out[:100]

    def pmdata(self, caminho):
        self._contar("pmdata")
        u = urllib.parse.urlparse(caminho)
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/v1/leaderboard":
            sem = self.agora // (7 * DIA)
            lst = []
            for c in self._carteiras:
                r = random.Random(c["k"] * 31 + sem)
                lst.append({"proxyWallet": c["end"], "userName": f"Apelido-{c['k']}", "vol": round(r.uniform(5e3, 5e5), 2),
                            "pnl": round((c["hab"] - 0.5) * 40_000 + r.gauss(0, 8000), 2)})
            lst.sort(key=lambda x: -x["pnl"])
            for n, x in enumerate(lst):
                x["rank"] = str(n + 1)
            return lst[: int(q.get("limit", ["50"])[0])]
        if u.path == "/trades" and "market" in q:
            m = self._por_cond.get(q["market"][0])
            if not m or m["fim"] > self.agora:
                return []
            out = []
            for c in self._carteiras:
                r = random.Random(c["k"] * 7_777 + m["i"])
                if r.random() > 0.35:
                    continue
                t = m["ini"] + int(r.random() * (m["fim"] - m["ini"]) * 0.9)
                lado = (0 if m["o"] else 1) if r.random() < c["hab"] else (1 if m["o"] else 0)
                p = self._p(m, t)
                for _ in range(3):
                    out.append({"proxyWallet": c["end"], "side": "BUY", "asset": m["toks"][lado], "conditionId": m["cond"],
                                "size": round(r.uniform(100, 2000), 2), "price": round(p if lado == 0 else 1 - p, 4),
                                "timestamp": t // 1000, "outcomeIndex": lado, "pseudonym": f"Apelido-{c['k']}"})
            return out[:500]
        if u.path == "/trades":
            end = q["user"][0].lower()
            c = next((c for c in self._carteiras if c["end"] == end), None)
            return self._trades(c) if c else []
        raise rede.Erro(f"Data API de mentira: {u.path}")

    def pmlb(self, caminho):
        self._contar("pmlb")
        return []

    # ------------------------------------------------------------------ Kalshi e Manifold
    def kalshi(self, caminho):
        self._contar("kalshi")
        ag, out = self.agora, []
        for m in self._pm:
            if not (m["ini"] <= ag < m["fim"]) or m["cat"] == "Esportes" or m["i"] % 4:
                continue
            p = self._p(m, ag) + (0.08 if m["i"] % 8 == 0 else 0.005)
            p = min(0.97, max(0.03, p))
            titulo = m["q"].replace("Will ", "").replace("?", "")
            out.append({"ticker": f"KXTESTE-{m['i']}", "event_ticker": f"KXEV-{m['i']}", "title": titulo + "?",
                        "yes_bid": int(p * 100) - 1, "yes_ask": int(p * 100) + 1, "status": "active",
                        "close_time": _iso(m["fim"] + DIA)})
            # parecido, com outro número: não pode casar
            if m["cat"] == "Cripto":
                out.append({**out[-1], "ticker": f"KXTESTE-{m['i']}-B", "title": titulo.replace("0k", "5k") + "?",
                            "yes_bid": 10, "yes_ask": 12})
        return {"markets": out, "cursor": ""}

    def manifold(self, caminho):
        self._contar("manifold")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(caminho).query)
        termo = set((q.get("term") or [""])[0].lower().split())
        ag, out = self.agora, []
        for m in self._pm:
            if not (m["ini"] <= ag < m["fim"]) or m["i"] % 3:
                continue
            if not termo or not termo <= set(m["q"].lower().replace("?", "").split()):
                continue
            p = min(0.97, max(0.03, self._p(m, ag) - (0.09 if m["i"] % 6 == 0 else 0.005)))
            out.append({"id": f"mf{m['i']}", "question": m["q"], "probability": round(p, 4), "closeTime": m["fim"],
                        "isResolved": False, "outcomeType": "BINARY", "uniqueBettorCount": 35, "volume": 1200})
        return out[:5]
