"""Memecoins de MENTIRA (sem rede; semente fixa): os lançamentos do PumpPortal, os pares da DexScreener, as velas de minuto
e de hora do GeckoTerminal, o RugCheck, o RPC da Solana (assinaturas, transações, maiores donos, saldo do criador, taxa
de prioridade), as gorjetas da Jito e os metadados no IPFS, nos formatos que memes.py lê. Nada aqui é dado real.

Cada token sorteia um destino pelo próprio endereço: morre sem negociar (48%), murcha nos primeiros minutos (30%),
golpe (sobe e cai mais de 90% em 2 min, 12%), dobra ou mais e depois cai (8%) ou se forma e vai para a PumpSwap (2%).
O destino puxa os sinais: os golpes têm mais bundle, criadores repetidos e o criador vendendo tudo em minutos; os que
dobram têm mais site e redes e as carteiras "espertas" comprando no 1º minuto (assim a regra de copiar tem o que achar).
"""
from __future__ import annotations

import math
import random
import re
from collections import Counter

import memes as M
import rede

MIN = 60_000
HORA = 60 * MIN
LETRAS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
DESTINOS = [("morto", 48), ("murcha", 30), ("golpe", 12), ("dobra", 8), ("gradua", 2)]
_r0 = random.Random(7)
_end = lambda r: "".join(r.choice(LETRAS) for _ in range(44))  # noqa: E731
SERIAIS = [_end(_r0) for _ in range(8)]       # criadores que lançam muitos (e muitos golpes)
ESPERTAS = [_end(_r0) for _ in range(6)]      # carteiras que chegam cedo nos que dão certo
ROBOS = [_end(_r0) for _ in range(25)]        # carteiras que compram quase tudo no 1º minuto


class Falso:
    def preparar(self):
        self._memes = {}
        self._sigs = {}
        self._txs = {}
        if not hasattr(self, "contagem"):
            self.contagem = Counter()

    def _c(self, tipo):
        self._contar(tipo, 1)
        self.contagem[tipo] += 1

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

    # ------------------------------------------------------------------ PumpPortal
    def pumpportal_ouvir(self, segundos, maximo, assinar=None):
        self._c("pumpportal")
        r = random.Random(self.agora)
        n = min(maximo, int(segundos / 60 * 8) + r.randint(0, 10))
        msgs = [{"message": "Successfully subscribed to token creation events."}]
        passo = segundos * 1000 // max(1, n)
        for k in range(n):
            outra = k % 7 == 3  # o PumpPortal manda também lançamentos de outras plataformas (o letsbonk.fun, "bonk")
            mint = "".join(r.choice(LETRAS) for _ in range(40)) + ("bonk" if outra else "pump")
            sol_criador = r.choice([0.0, 0.0, 0.1, 0.5, 1.0, 3.0, 5.0])
            vS = 30.0 + sol_criador
            vT = M.K_CURVA / vS
            t = self.agora - segundos * 1000 + k * passo  # as chegadas, antes do fim da escuta
            rd = random.Random(mint)
            destino = rd.choices([d for d, _ in DESTINOS], [p for _, p in DESTINOS])[0]
            serial = rd.random() < (0.6 if destino == "golpe" else 0.15)
            criador = rd.choice(SERIAIS) if serial else _end(rd)
            info = {"t": t, "p0": vS / vT, "destino": destino, "fase": rd.random() * 6, "criador": criador,
                    "serial": serial, "inicial": 1_073_000_000 - vT, "sol0": sol_criador,
                    "a": {"golpe": rd.uniform(2, 4), "dobra": rd.uniform(2, 8)}.get(destino, 1.0),
                    "m1": {"golpe": rd.uniform(5, 40), "dobra": rd.uniform(10, 120), "gradua": rd.uniform(30, 300)}.get(destino, 0.0),
                    "redes": rd.random() < (0.6 if destino in ("dobra", "gradua") else 0.2),
                    "liqBaixa": destino == "gradua" and rd.random() < 0.3}
            # o criador vende tudo: nos golpes em minutos; às vezes nos outros, mais tarde
            if sol_criador > 0:
                if destino == "golpe":
                    info["vende"] = t + int(rd.uniform(1, 25) * MIN)
                elif rd.random() < 0.3:
                    info["vende"] = t + int(rd.uniform(60, 900) * MIN)
            self._memes[mint] = info
            info["cid"] = "Qm" + "".join(rd.choice(LETRAS) for _ in range(44))
            uri = "https://ipfs.io/ipfs/" + info["cid"] if rd.random() < 0.9 else "https://exemplo.invalid/meta.json"
            msgs.append({"signature": "x" * 20, "mint": mint, "traderPublicKey": criador, "txType": "create",
                         "initialBuy": 1_073_000_000 - vT, "solAmount": sol_criador, "bondingCurveKey": "c" + mint[1:36],
                         "vTokensInBondingCurve": vT, "vSolInBondingCurve": vS, "marketCapSol": vS / vT * M.OFERTA,
                         "name": "Nome de Mentira", "symbol": "MENT", "uri": uri, "pool": "bonk" if outra else "pump",
                         "_t": t})
        return msgs

    # ------------------------------------------------------------------ DexScreener e GeckoTerminal
    def dexscreener(self, caminho):
        self._c("dexscreener")
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
                liq = (50.0 if i["liqBaixa"] else 5000.0) if dex == "pumpswap" else 800.0
                out.append({"chainId": "solana", "dexId": dex, "pairAddress": end, "pairCreatedAt": criado,
                            "baseToken": {"address": mint, "name": "Nome de Mentira", "symbol": "MENT"},
                            "quoteToken": {"symbol": "SOL"}, "priceNative": f"{preco:.12g}", "priceUsd": f"{preco * 150:.12g}",
                            "liquidity": {"usd": liq}})
        return out

    def _gecko_memes(self, caminho):
        self.contagem["gecko"] += 1
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
        m = re.match(r"^/networks/solana/pools/([^/]+)/ohlcv/(minute|hour)\?(.*)$", caminho)
        if not m:
            raise rede.Erro("HTTP 404 em GeckoTerminal", 404)
        par, escala, q = m.group(1), m.group(2), dict(x.split("=", 1) for x in m.group(3).split("&"))
        mint = q.get("token")
        i = self._info(mint)
        if not i or par[1:] != mint[1:36]:
            raise rede.Erro("HTTP 404 em GeckoTerminal", 404)
        antes = min(int(q["before_timestamp"]) * 1000, self.agora)
        tg = self._t_grad(i)
        a, b = (i["t"], tg or antes) if par.startswith("c") else (tg, antes)
        b = min(b, antes)
        passo = MIN if escala == "minute" else HORA
        lst = []
        t = (a // passo) * passo
        lim = int(q.get("limit", 1000))
        while t < b:
            if escala == "minute":
                p1, p2 = self._preco(i, t), self._preco(i, t + MIN)
                if p1 is not None:
                    p2 = p2 if p2 is not None else p1
                    lst.append([t // 1000, p1, max(p1, p2) * 1.01, min(p1, p2) * 0.99, p2, 1.5])
            else:
                ps = [self._preco(i, t + k * 10 * MIN) for k in range(7)]
                ps = [p for p in ps if p is not None]
                if ps:
                    lst.append([t // 1000, ps[0], max(ps) * 1.01, min(ps) * 0.99, ps[-1], 9.0])
            t += passo
        lst = lst[-lim:]  # o GeckoTerminal devolve as `limit` mais perto do before_timestamp
        return {"data": {"id": "solana_" + par, "type": "ohlcv_request_response",
                         "attributes": {"ohlcv_list": list(reversed(lst))}},
                "meta": {"base": {"address": mint}, "quote": {"symbol": "SOL"}}}

    # ------------------------------------------------------------------ RugCheck, Jito, metadados
    def rugcheck(self, mint):
        self._c("rugcheck")
        i = self._info(mint)
        if not i:
            raise rede.Erro("HTTP 404 em RugCheck", 404)
        rd = random.Random(mint + "rc")
        perigo = rd.random() < (0.7 if i["destino"] == "golpe" else 0.2)
        riscos = [{"name": "Mutable metadata", "level": "warn", "score": 100}]
        if perigo:
            riscos.append({"name": "Top 10 holders high ownership", "level": "danger", "score": 5000})
        return {"tokenProgram": "x", "tokenType": "", "risks": riscos, "score": 5100 if perigo else 100, "score_normalised": 50}

    def jito(self):
        self._c("jito")
        return [{"time": "2026-11-09T12:00:00Z", "landed_tips_25th_percentile": 0.00001,
                 "landed_tips_50th_percentile": 0.0006, "landed_tips_75th_percentile": 0.0021,
                 "landed_tips_95th_percentile": 0.012, "landed_tips_99th_percentile": 0.05,
                 "ema_landed_tips_50th_percentile": 0.00055}]

    def metadados(self, url):
        self._c("ipfs")
        m = re.search(r"/ipfs/(Qm[A-Za-z0-9]+)$", url)
        if not m:
            raise rede.Erro("HTTP 404 em metadados (IPFS)", 404)
        # o metadado de mentira não sabe de qual token é: o sorteio pelo CID (os de verdade dizem pelo conteúdo)
        mint = next((k for k, v in self._memes.items() if v.get("cid") == m.group(1)), None)
        i = self._info(mint) if mint else None
        redes = i["redes"] if i else False
        out = {"name": "Nome de Mentira", "symbol": "MENT", "description": "texto de mentira",
               "image": "https://ipfs.io/ipfs/QmImagem", "showName": True, "createdOn": "https://pump.fun"}
        if redes:
            out.update({"twitter": "https://x.com/mentira", "website": "https://exemplo.invalid"})
        return out

    # ------------------------------------------------------------------ RPC da Solana
    def _lista_sigs(self, mint):
        """Todas as assinaturas da curva de um token (a mais velha primeiro), com o slot, a hora e a transação."""
        if mint in self._sigs:
            return self._sigs[mint]
        i = self._info(mint)
        rd = random.Random(mint + "sigs")
        bt0 = i["t"] // 1000
        slot0 = 300_000_000 + (i["t"] // 400) % 50_000_000
        lst = [("cria" + mint[:20], slot0, bt0, i["criador"], i["sol0"])]
        d = i["destino"]
        nb = rd.randint(2, 5) if d == "golpe" else (1 if rd.random() < 0.2 else 0)
        for k in range(nb):
            lst.append((f"bd{k}" + mint[:20], slot0, bt0, _end(rd), rd.uniform(0.3, 2.0)))
        cedo = []
        if d != "morto":
            for w in ESPERTAS:
                if rd.random() < (0.55 if d in ("dobra", "gradua") else 0.04):
                    cedo.append(w)
            for w in ROBOS:
                if rd.random() < 0.06:
                    cedo.append(w)
        rd.shuffle(cedo)
        for k, w in enumerate(cedo):
            lst.append((f"ce{k}" + mint[:20], slot0 + 5 + k * 3, bt0 + 2 + k * 5, w, rd.uniform(0.05, 0.5)))
        mais = {"morto": 0, "murcha": 30, "golpe": 60, "dobra": 300, "gradua": 1300}[d]
        for k in range(mais):
            bt = bt0 + 61 + k * 20
            lst.append((f"tr{k}" + mint[:20], slot0 + 200 + k * 50, bt, _end(rd), rd.uniform(0.01, 0.3)))
        self._sigs[mint] = lst
        for sig, slot, bt, quem, sol in lst:
            self._txs[sig] = (mint, slot, bt, quem, sol)
        return lst

    def _mint_da_curva(self, end):
        return next((k for k in self._memes if "c" + k[1:36] == end), None)

    def solana(self, metodo, params):
        self._contar("solana:" + metodo, 1)
        self.contagem["solana"] += 1
        if "solana" in self.falhar:
            raise rede.Erro("RPC de mentira fora do ar")
        if metodo == "getRecentPrioritizationFees":
            r = random.Random(self.agora)
            return [{"slot": 300_000_000 + k, "prioritizationFee": r.choice([0, 1000, 5000, 20000, 100000])} for k in range(150)]
        if metodo == "getSignaturesForAddress":
            end, op = params[0], params[1] if len(params) > 1 else {}
            lim = int(op.get("limit", 1000))
            mint = self._mint_da_curva(end)
            if mint:
                lst = [x for x in self._lista_sigs(mint) if x[2] * 1000 <= self.agora]
                novas = list(reversed(lst))
                if op.get("before"):
                    k = next((j for j, x in enumerate(novas) if x[0] == op["before"]), len(novas))
                    novas = novas[k + 1:]
                return [{"signature": s, "slot": sl, "err": None, "memo": None, "blockTime": bt, "confirmationStatus": "finalized"}
                        for s, sl, bt, _q, _s in novas[:lim]]
            # a carteira de um criador: os seriais têm muitas transações; os outros, poucas ou muitas
            rd = random.Random(end + "cr")
            n = 1000 if end in SERIAIS else rd.choice([1, 2, 3, 5, 8, 12, 40, 400])
            return [{"signature": f"w{k}", "slot": 1, "err": None, "blockTime": 1} for k in range(min(lim, n))]
        if metodo == "getTransaction":
            x = self._txs.get(params[0])
            if not x:
                return None
            mint, slot, bt, quem, sol = x
            ganhou = sol * 30_000_000
            return {"slot": slot, "blockTime": bt,
                    "meta": {"err": None, "fee": 5000, "preBalances": [int((sol + 1) * 1e9), 0], "postBalances": [int(1e9 - 5000), 0],
                             "preTokenBalances": [], "postTokenBalances": [
                                 {"accountIndex": 1, "mint": mint, "owner": quem, "uiTokenAmount": {"uiAmount": ganhou, "decimals": 6}}]},
                    "transaction": {"message": {"accountKeys": [quem, "conta" + mint[:10], "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"]},
                                    "signatures": [params[0]]}}
        if metodo == "getTokenLargestAccounts":
            i = self._info(params[0])
            if not i:
                raise rede.Erro("RPC getTokenLargestAccounts: conta desconhecida")
            lst = self._lista_sigs(params[0])
            donos = {}
            for _s, _sl, bt, quem, sol in lst:
                if bt * 1000 <= self.agora:
                    donos[quem] = donos.get(quem, 0.0) + (i["inicial"] if quem == i["criador"] else sol * 30_000_000)
            if i.get("vende") and i["vende"] <= self.agora:
                donos.pop(i["criador"], None)
            curva = 793_100_000 - sum(donos.values())
            vals = sorted([curva] + list(donos.values()), reverse=True)[:20]
            return {"context": {"slot": 1}, "value": [{"address": f"a{k}", "amount": str(int(v * 1e6)), "decimals": 6,
                                                       "uiAmount": v, "uiAmountString": str(v)} for k, v in enumerate(vals) if v > 0]}
        if metodo == "getTokenAccountsByOwner":
            dono, filtro = params[0], params[1]
            i = self._info(filtro.get("mint"))
            if not i or i["criador"] != dono:
                return {"context": {"slot": 1}, "value": []}
            if i.get("vende") and i["vende"] <= self.agora:
                return {"context": {"slot": 1}, "value": []}  # vendeu tudo e fechou a conta
            return {"context": {"slot": 1}, "value": [{"pubkey": "conta", "account": {"data": {"parsed": {"info": {
                "mint": filtro["mint"], "owner": dono, "tokenAmount": {"uiAmount": i["inicial"], "decimals": 6}}}}}}]}
        raise rede.Erro(f"RPC {metodo}: método de mentira desconhecido")
