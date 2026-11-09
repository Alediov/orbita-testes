"""Memecoins de MENTIRA (sem rede; semente fixa): os lançamentos do PumpPortal, os pares da DexScreener, as velas de minuto
do GeckoTerminal, o RugCheck e a taxa de prioridade da Solana, nos formatos que memes.py lê. Nada aqui é dado real.

Cada token sorteia um destino pelo próprio endereço: morre sem negociar (48%), murcha nos primeiros minutos (30%),
golpe (sobe e cai mais de 90% em 2 min, 12%), dobra ou mais e depois cai (8%) ou se forma e vai para a PumpSwap (2%).
"""
from __future__ import annotations

import math
import random
import re

import memes as M
import rede

MIN = 60_000
LETRAS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
DESTINOS = [("morto", 48), ("murcha", 30), ("golpe", 12), ("dobra", 8), ("gradua", 2)]


class Falso:
    def preparar(self):
        self._memes = {}

    # ------------------------------------------------------------------ o destino de cada token
    def _info(self, mint):
        return self._memes.get(mint)

    def _preco(self, i, t):
        """SOL por token no instante t, ou None se ninguém negociou até lá (ou depois que o token morreu)."""
        x = (t - i["t"]) / MIN
        if x < 0:
            return None
        p0, d, a, m1 = i["p0"], i["destino"], i["a"], i["m1"]
        ru = 1 + 0.04 * math.sin(x * 1.7 + i["fase"])
        if d == "morto":
            return None
        if d == "murcha":
            if x > 90:
                return None
            return p0 * (1 + 0.15 * math.exp(-((x - 2) ** 2) / 4)) * math.exp(-x / 12) * ru
        if d == "golpe":
            if x <= m1:
                return p0 * (1 + (a - 1) * x / m1) * ru
            if x <= m1 + 2:
                return p0 * a * (1 - 0.485 * (x - m1))
            return None if x > m1 + 20 else p0 * a * 0.03
        if d == "dobra":
            if x <= m1:
                return p0 * (1 + (a - 1) * (x / m1) ** 1.5) * ru
            return p0 * a * max(0.03, math.exp(-(x - m1) / 120)) * ru
        # gradua
        if x <= m1:
            return p0 + (M.P_GRAD * 1.05 - p0) * (x / m1) ** 2
        return M.P_GRAD * 1.05 * max(0.05, math.exp(-(x - m1) / 500)) * (1 + 0.3 * math.sin((x - m1) / 90 + i["fase"])) * ru

    def _t_grad(self, i):
        return i["t"] + int(i["m1"] * MIN) if i["destino"] == "gradua" else None

    # ------------------------------------------------------------------ fontes
    def pumpportal_ouvir(self, segundos, maximo, assinar=None):
        self._contar("pumpportal", 1)
        r = random.Random(self.agora)
        n = min(maximo, 32 + r.randint(0, 20))
        msgs = [{"message": "Successfully subscribed to token creation events."}]
        for k in range(n):
            outra = k % 7 == 3  # o PumpPortal manda também lançamentos de outras plataformas (o letsbonk.fun, "bonk")
            mint = "".join(r.choice(LETRAS) for _ in range(40)) + ("bonk" if outra else "pump")
            sol_criador = r.choice([0.0, 0.0, 0.1, 0.5, 1.0, 3.0, 5.0])
            vS = 30.0 + sol_criador
            vT = M.K_CURVA / vS
            t = self.agora + k * (segundos * 1000 // max(1, n))
            rd = random.Random(mint)
            destino = rd.choices([d for d, _ in DESTINOS], [p for _, p in DESTINOS])[0]
            info = {"t": t, "p0": vS / vT, "destino": destino, "fase": rd.random() * 6,
                    "a": {"golpe": rd.uniform(2, 4), "dobra": rd.uniform(2, 8)}.get(destino, 1.0),
                    "m1": {"golpe": rd.uniform(5, 40), "dobra": rd.uniform(10, 120), "gradua": rd.uniform(30, 300)}.get(destino, 0.0)}
            self._memes[mint] = info
            msgs.append({"signature": "x" * 20, "mint": mint, "traderPublicKey": "y" * 40, "txType": "create",
                         "initialBuy": 1_073_000_000 - vT, "solAmount": sol_criador, "bondingCurveKey": "c" + mint[1:36],
                         "vTokensInBondingCurve": vT, "vSolInBondingCurve": vS, "marketCapSol": vS / vT * M.OFERTA,
                         "name": "Nome de Mentira", "symbol": "MENT", "uri": "https://exemplo.invalid/x.json", "pool": "bonk" if outra else "pump",
                         "_t": t})
        return msgs

    def dexscreener(self, caminho):
        self._contar("dexscreener", 1)
        m = re.match(r"^/tokens/v1/solana/(.+)$", caminho)
        if not m:
            raise rede.Erro("HTTP 404 em DexScreener", 404)
        out = []
        for mint in m.group(1).split(","):
            i = self._info(mint)
            if not i or i["destino"] == "morto":
                continue
            p = self._preco(i, self.agora)
            pares = [("pumpfun", "c" + mint[1:36], i["t"] + MIN)]
            tg = self._t_grad(i)
            if tg and tg <= self.agora:
                pares.append(("pumpswap", "s" + mint[1:36], tg))
            for dex, end, criado in pares:
                fim = tg if (dex == "pumpfun" and tg and tg <= self.agora) else None
                preco = (self._preco(i, fim - MIN) if fim else p) or i["p0"] * 0.01
                out.append({"chainId": "solana", "dexId": dex, "pairAddress": end, "pairCreatedAt": criado,
                            "baseToken": {"address": mint, "name": "Nome de Mentira", "symbol": "MENT"},
                            "quoteToken": {"symbol": "SOL"}, "priceNative": f"{preco:.12g}", "priceUsd": f"{preco * 150:.12g}",
                            "liquidity": {"usd": 5000.0 if dex == "pumpswap" else 800.0}})
        return out

    def _gecko_memes(self, caminho):
        m = re.match(r"^/networks/solana/tokens/([^/?]+)/pools", caminho)
        if m:
            # os tokens "mortos" não aparecem na DexScreener: o GeckoTerminal confirma (404 = ninguém negociou); de
            # alguns, o GeckoTerminal conhece o par da curva (a DexScreener não listou)
            mint = m.group(1)
            i = self._info(mint)
            if not i or i["destino"] == "morto":
                raise rede.Erro("HTTP 404 em GeckoTerminal", 404)
            return {"data": [{"id": "solana_c" + mint[1:36], "type": "pool",
                              "attributes": {"address": "c" + mint[1:36], "name": "MENT / SOL",
                                             "base_token_price_native_currency": f"{i['p0']:.12g}", "reserve_in_usd": "800",
                                             "pool_created_at": "2026-11-01T00:00:00Z"},
                              "relationships": {"dex": {"data": {"id": "pump-fun", "type": "dex"}}}}]}
        m = re.match(r"^/networks/solana/pools/([^/]+)/ohlcv/minute\?(.*)$", caminho)
        if not m:
            raise rede.Erro("HTTP 404 em GeckoTerminal", 404)
        par, q = m.group(1), dict(x.split("=", 1) for x in m.group(2).split("&"))
        mint = q.get("token")
        i = self._info(mint)
        if not i or par[1:] != mint[1:36]:
            raise rede.Erro("HTTP 404 em GeckoTerminal", 404)
        antes = min(int(q["before_timestamp"]) * 1000, self.agora)
        tg = self._t_grad(i)
        a, b = (i["t"], tg or antes) if par.startswith("c") else (tg, antes)
        b = min(b, antes)
        lst = []
        t = (a // MIN) * MIN
        while t < b and len(lst) < int(q.get("limit", 1000)):
            p1, p2 = self._preco(i, t), self._preco(i, t + MIN)
            if p1 is not None:
                p2 = p2 if p2 is not None else p1
                lst.append([t // 1000, p1, max(p1, p2) * 1.01, min(p1, p2) * 0.99, p2, 1.5])
            t += MIN
        return {"data": {"id": "solana_" + par, "type": "ohlcv_request_response",
                         "attributes": {"ohlcv_list": list(reversed(lst))}},
                "meta": {"base": {"address": mint}, "quote": {"symbol": "SOL"}}}

    def rugcheck(self, mint):
        self._contar("rugcheck", 1)
        i = self._info(mint)
        if not i:
            raise rede.Erro("HTTP 404 em RugCheck", 404)
        rd = random.Random(mint + "rc")
        perigo = rd.random() < (0.7 if i["destino"] == "golpe" else 0.2)
        riscos = [{"name": "Mutable metadata", "level": "warn", "score": 100}]
        if perigo:
            riscos.append({"name": "Top 10 holders high ownership", "level": "danger", "score": 5000})
        return {"tokenProgram": "x", "tokenType": "", "risks": riscos, "score": 5100 if perigo else 100, "score_normalised": 50}

    def solana(self, metodo, params):
        self._contar("solana:" + metodo, 1)
        if metodo == "getRecentPrioritizationFees":
            r = random.Random(self.agora)
            return [{"slot": 300_000_000 + k, "prioritizationFee": r.choice([0, 1000, 5000, 20000, 100000])} for k in range(150)]
        raise rede.Erro(f"RPC {metodo}: método de mentira desconhecido")
