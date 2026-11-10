"""Aave de MENTIRA (sem rede; semente fixa): o GraphQL do Aave (mercados da Base e o histórico de juros), o staking do
Lido na DefiLlama, o GraphQL da Morpho (cofres de USDC na Base e o histórico) e os pools de USDC da Moonwell e da
Morpho na DefiLlama (`/pools` e `/chart`) e o `getReserveData` do Pool (pelo `rpc` de falso_pools.py, que chama `_eth_call_aave`), nos formatos
das amostras do Teste de alcance (ver looping.py). Nada aqui é dado real.

Os juros andam em regimes de alguns dias; em alguns trechos o juro do ether passa o staking (o wstETH em laço perde),
como acontece de verdade quando muita gente pega ether emprestado.
"""
from __future__ import annotations

import datetime as dt
import random
import re

import looping as LP

DIA = 86_400_000
# chave → (nível, peso dos regimes, desvio)
NIVEIS = {"sup:WETH": (0.016, 0.006), "bor:WETH": (0.024, 0.008), "sup:wstETH": (0.0003, 0.0001),
          "sup:USDC": (0.042, 0.010), "bor:USDC": (0.058, 0.012), "stake": (0.028, 0.002),
          "sup:morpho": (0.052, 0.008), "sup:moonwell": (0.047, 0.009)}
MORPHO_COFRE = "0xbeeF010f9cb27031ad51e3333f9aF9C6B1228183"  # um endereço com cara de cofre (de mentira)
LLAMA_POOLS = {"morpho": "4ad1b6a3-0000-4000-8000-00000000beef", "moonwell": "9b3f1c2e-0000-4000-8000-00000000d00d"}
SIMBOLO = {v.lower(): k for k, v in LP.ENDERECOS.items()}


class Falso:
    def preparar(self):
        import falso_mercado
        self._juros = {}
        r = random.Random(4401)
        d0 = dt.date.fromtimestamp((falso_mercado.T0 - 400 * DIA) / 1000)
        for chave, (nivel, desvio) in NIVEIS.items():
            s, alvo, x = {}, nivel, nivel
            for i in range(470):
                if i % 9 == 0:
                    alvo = max(0.0, nivel + r.gauss(0, desvio))
                    if chave == "bor:WETH" and r.random() < 0.15:
                        alvo = nivel * 1.9  # o juro do ether passa o staking por uns dias
                x += 0.3 * (alvo - x) + r.gauss(0, desvio * 0.05)
                s[(d0 + dt.timedelta(days=i)).isoformat()] = max(0.0, x)
            self._juros[chave] = s

    def _hoje(self):
        return dt.datetime.fromtimestamp(self.agora / 1000, dt.timezone.utc).strftime("%Y-%m-%d")

    def aave(self, query):
        self._contar("aave")
        m = re.search(r"(supplyAPYHistory|borrowAPYHistory)\(request:\{.*underlyingToken:\"(0x[0-9a-fA-F]+)\"", query)
        if m:
            campo, tok = m.group(1), SIMBOLO.get(m.group(2).lower())
            chave = ("sup:" if campo.startswith("supply") else "bor:") + (tok or "?")
            s = self._juros.get(chave)
            if s is None:
                return {campo: []}
            hoje = self._hoje()
            dias = sorted(d for d in s if d <= hoje)[-365:]
            return {campo: [{"date": f"{d}T00:00:00+00:00", "avgRate": {"value": f"{s[d]:.24f}"}} for d in reversed(dias)]}
        if "eModeCategories" in query:
            return {"markets": [{"address": LP.POOL, "eModeCategories": [
                {"id": 1, "label": "ETH correlated", "maxLTV": {"value": "0.9"}, "liquidationThreshold": {"value": "0.93"},
                 "liquidationPenalty": {"value": "0.01"}}]}]}
        if "markets" in query:
            hoje = self._hoje()
            reservas = []
            for sim, end in [("AAVE", "0x63706e401c06ac8513145b7687a14804d17f814b")] + list(LP.ENDERECOS.items()):
                k = sim
                sup = self._juros.get("sup:" + k, {}).get(hoje)
                bor = self._juros.get("bor:" + k, {}).get(hoje)
                tok = {"symbol": sim}
                if "address" in query.split("underlyingToken")[1].split("}")[0]:
                    tok["address"] = end
                reservas.append({"underlyingToken": tok, "supplyInfo": {"apy": {"value": f"{(sup or 0):.24f}"}},
                                 "borrowInfo": {"apy": {"value": f"{bor:.24f}"}} if bor is not None else None})
            return {"markets": [{"name": "AaveV3Base", "address": LP.POOL, "reserves": reservas}]}
        raise LP.rede.Erro("Aave GraphQL: consulta de mentira desconhecida")

    def morpho(self, query):
        self._contar("morpho")
        hoje = self._hoje()
        s = self._juros["sup:morpho"]
        if "vaultByAddress" in query:
            campo = re.search(r"historicalState \{ (\w+)\(", query).group(1)
            if campo == "netApyWithoutRewards":
                raise LP.rede.Erro('Morpho GraphQL: Cannot query field "netApyWithoutRewards" on type "VaultHistory".')
            pts = [{"x": int(dt.datetime.fromisoformat(d + "T00:00:00+00:00").timestamp()), "y": s[d]}
                   for d in sorted(s) if d <= hoje][-366:]
            return {"vaultByAddress": {"address": MORPHO_COFRE, "historicalState": {campo: pts}}}
        if "vaults(" in query:
            st = {"totalAssetsUsd": 412_000_000.0, "apy": s[hoje] * 1.1, "fee": 0.1}
            if "netApy" in query:
                st["netApy"] = s[hoje] + 0.004  # com as recompensas em MORPHO
            if "netApyWithoutRewards" in query:
                st["netApyWithoutRewards"] = s[hoje]
            return {"vaults": {"items": [
                {"address": MORPHO_COFRE, "name": "Cofre de mentira USDC", "symbol": "mUSDC", "state": st},
                {"address": "0x" + "1" * 40, "name": "Cofre pequeno", "symbol": "pUSDC",
                 "state": dict(st, totalAssetsUsd=200_000.0)}]}}
        raise LP.rede.Erro("Morpho GraphQL: consulta de mentira desconhecida")

    def llama(self, caminho):
        self._contar("llama")
        hoje = self._hoje()
        if caminho == "/pools":
            pools = [
                {"chain": "Ethereum", "project": "moonwell-lending", "symbol": "USDC", "tvlUsd": 9e9, "pool": "x", "apyBase": 9.0},
                {"chain": "Base", "project": "moonwell-lending", "symbol": "USDC", "tvlUsd": 4.1e7, "pool": LLAMA_POOLS["moonwell"],
                 "apyBase": round(self._juros["sup:moonwell"][hoje] * 100, 5), "apyReward": 1.2, "apy": 6.0},
                {"chain": "Base", "project": "moonwell-lending", "symbol": "WETH", "tvlUsd": 9e7, "pool": "y", "apyBase": 1.0},
                {"chain": "Base", "project": "morpho-blue", "symbol": "USDC", "tvlUsd": 3.0e8, "pool": LLAMA_POOLS["morpho"],
                 "apyBase": round(self._juros["sup:morpho"][hoje] * 100, 5), "apyReward": 0.4}]
            if getattr(self, "sem_moonwell", False):  # teste: a Moonwell sumiu da DefiLlama
                pools = [x for x in pools if not x["project"].startswith("moonwell")]
            return {"status": "success", "data": pools}
        for nome, pid in LLAMA_POOLS.items():
            if pid in caminho:
                s = self._juros["sup:" + nome]
                return {"status": "success", "data": [{"timestamp": f"{d}T23:01:00.000Z", "tvlUsd": 4e7, "apy": round(s[d] * 100, 5),
                                                       "apyBase": round(s[d] * 100, 5), "apyReward": None} for d in sorted(s) if d <= hoje]}
        if LP.LIDO_LLAMA not in caminho:
            raise LP.rede.Erro("HTTP 404 em DefiLlama", 404)
        s = self._juros["stake"]
        return {"status": "success", "data": [{"timestamp": f"{d}T23:05:17.943Z", "tvlUsd": 2.2e10, "apy": round(s[d] * 100, 5),
                                               "apyBase": round(s[d] * 100, 5), "apyReward": None} for d in sorted(s) if d <= hoje]}

    def _eth_call_aave(self, para, dados):
        """getReserveData (seletor 0x35ea6a75) do Pool: a configuração no 1º campo, o resto zerado."""
        if para.lower() != LP.POOL.lower() or not dados.startswith("0x35ea6a75"):
            raise LP.rede.Erro("RPC eth_call: execution reverted", codigo=3)
        tok = "0x" + dados[-40:]
        sim = SIMBOLO.get(tok.lower())
        ltv, lt, bonus = {"WETH": (8100, 8400, 10500), "wstETH": (7500, 7900, 10600), "USDC": (7500, 7800, 10500)}.get(sim, (0, 0, 0))
        cfg = ltv | (lt << 16) | (bonus << 32) | (18 << 48)
        return "0x" + f"{cfg:064x}" + "0" * 64 * 14
