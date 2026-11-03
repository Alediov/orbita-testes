"""Cliente de LEITURA da API pública da Hyperliquid (só biblioteca padrão). Nada de ordens, contas ou chaves.

- `POST https://api.hyperliquid.xyz/info` (documentação oficial, hyperliquid.gitbook.io → For developers → API → Info
  endpoint): userFills, userFillsByTime, clearinghouseState, candleSnapshot, fundingHistory, meta, portfolio, userRole.
- O ranking: `GET https://stats-data.hyperliquid.xyz/Mainnet/leaderboard`. NÃO está na documentação oficial: é o arquivo
  que o próprio site usa para a página Leaderboard, e bibliotecas abertas o leem (hyperliquid no Hex, eth_defi):
  {"leaderboardRows": [{"ethAddress", "accountValue", "windowPerformances": [["day"|"week"|"month"|"allTime",
  {"pnl", "roi", "vlm"}]], "prize", "displayName"}]}.

Limite (documentação "Rate limits and user limits"): 1.200 de peso por minuto por IP; clearinghouseState pesa 2,
userRole 60, o resto 20; userFills/userFillsByTime/fundingHistory somam 1 a cada 20 itens devolvidos e candleSnapshot
1 a cada 60. O cliente leva a conta num balde (com folga) e espera quando precisa; 429 ou erro de rede: espera e tenta
de novo. Respostas por intervalo de tempo vêm em páginas (no máximo 500 itens; userFillsByTime até 2.000): a próxima
começa no último horário devolvido.
"""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request

URL_INFO = "https://api.hyperliquid.xyz/info"
URL_RANKING = "https://stats-data.hyperliquid.xyz/Mainnet/leaderboard"
PESO = {"clearinghouseState": 2, "userRole": 60}
EXTRA_POR = {"userFills": 20, "userFillsByTime": 20, "fundingHistory": 20, "candleSnapshot": 60}
INTERVALO_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "1d": 86_400_000}
MAX_VELAS = 5000  # só as 5.000 velas mais recentes de cada intervalo existem


class Erro(Exception):
    pass


class Balde:
    """Peso por minuto (1.200 na API; usamos 1.100 de folga)."""

    def __init__(self, por_minuto=1100, relogio=time.monotonic, dormir=time.sleep):
        self.cap, self.tem, self.relogio, self.dormir = por_minuto, por_minuto, relogio, dormir
        self.t = relogio()
        self.esperou = 0.0

    def gastar(self, peso):
        agora = self.relogio()
        self.tem = min(self.cap, self.tem + (agora - self.t) * self.cap / 60)
        self.t = agora
        if self.tem < peso:
            s = (peso - self.tem) * 60 / self.cap
            self.esperou += s
            self.dormir(s)
            self.tem = peso
            self.t = self.relogio()
        self.tem -= peso


class Cliente:
    def __init__(self, balde=None, tentativas=5, prazo=40, dormir=time.sleep, log=print):
        self.balde = balde or Balde()
        self.tentativas, self.prazo, self.dormir, self.log = tentativas, prazo, dormir, log
        self.pedidos = 0
        self.peso = 0

    # ------------------------------------------------------------------ transporte
    def _http(self, url, corpo=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(url, data=dados, method="POST" if dados else "GET",
                                     headers={"Content-Type": "application/json", "User-Agent": "orbita-testes/1"})
        with urllib.request.urlopen(req, timeout=self.prazo) as r:
            return json.loads(r.read().decode())

    def _pedir(self, url, corpo=None, peso=20):
        self.balde.gastar(peso)
        for k in range(self.tentativas):
            try:
                self.pedidos += 1
                self.peso += peso
                return self._http(url, corpo)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and k < self.tentativas - 1:
                    s = min(60, 5 * 2 ** k)
                    self.log(f"  HTTP {e.code} em {corpo and corpo.get('type') or url}; espera {s}s")
                    self.dormir(s)
                    continue
                raise Erro(f"HTTP {e.code} em {corpo and corpo.get('type') or url}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if k < self.tentativas - 1:
                    self.dormir(min(30, 3 * 2 ** k))
                    continue
                raise Erro(f"rede: {e}") from e
        raise Erro("sem resposta")

    def info(self, corpo):
        tipo = corpo["type"]
        r = self._pedir(URL_INFO, corpo, PESO.get(tipo, 20))
        por = EXTRA_POR.get(tipo)
        if por and isinstance(r, list):
            extra = math.ceil(len(r) / por)
            self.balde.gastar(extra)
            self.peso += extra
        return r

    # ------------------------------------------------------------------ pedidos
    def ranking(self):
        r = self._pedir(URL_RANKING, None, 20)
        return r.get("leaderboardRows") or []

    def meta(self):
        return self.info({"type": "meta"})

    def papel(self, user):
        return (self.info({"type": "userRole", "user": user}) or {}).get("role")

    def estado(self, user):
        return self.info({"type": "clearinghouseState", "user": user})

    def portfolio(self, user):
        return self.info({"type": "portfolio", "user": user})

    def execucoes(self, user):
        """As 2.000 execuções mais recentes (agrupadas por horário)."""
        return self.info({"type": "userFills", "user": user, "aggregateByTime": True})

    def execucoes_entre(self, user, ini, fim=None, maximo=10_000):
        """Execuções entre ini e fim (inclusive), em páginas; sem repetir (pelo tid)."""
        vistos, out, a = set(), [], int(ini)
        while True:
            corpo = {"type": "userFillsByTime", "user": user, "startTime": a, "aggregateByTime": True}
            if fim is not None:
                corpo["endTime"] = int(fim)
            pag = self.info(corpo) or []
            novos = [f for f in pag if (f.get("tid"), f.get("hash"), f.get("time")) not in vistos]
            for f in novos:
                vistos.add((f.get("tid"), f.get("hash"), f.get("time")))
            out += novos
            if len(pag) < 500 or not novos or len(out) >= maximo:
                break
            a = max(int(f["time"]) for f in pag)
        return sorted(out, key=lambda f: int(f["time"]))

    def velas(self, moeda, intervalo, ini, fim):
        """Velas [ini, fim] em páginas; respeita o limite das 5.000 mais recentes."""
        passo = INTERVALO_MS[intervalo]
        out, a = {}, int(ini)
        while a <= fim:
            pag = self.info({"type": "candleSnapshot", "req": {"coin": moeda, "interval": intervalo,
                                                                "startTime": a, "endTime": int(fim)}}) or []
            if not pag:
                break
            for c in pag:
                out[int(c["t"])] = c
            ult = max(int(c["t"]) for c in pag)
            if ult + passo > fim or len(pag) < 400:
                break
            a = ult + passo
        return [out[k] for k in sorted(out)]

    def financiamento(self, moeda, ini, fim):
        out, a = {}, int(ini)
        while a <= fim:
            pag = self.info({"type": "fundingHistory", "coin": moeda, "startTime": a, "endTime": int(fim)}) or []
            if not pag:
                break
            for x in pag:
                out[int(x["time"])] = x
            ult = max(int(x["time"]) for x in pag)
            if len(pag) < 500 or ult <= a:
                break
            a = ult + 1
        return [out[k] for k in sorted(out)]


def intervalo_para(ini, fim, agora):
    """O intervalo mais fino que ainda tem velas desde `ini` (a API só guarda as 5.000 mais recentes)."""
    for nome in ("1m", "5m", "15m", "1h"):
        if agora - ini <= INTERVALO_MS[nome] * (MAX_VELAS - 50):
            return nome
    return "1h"
