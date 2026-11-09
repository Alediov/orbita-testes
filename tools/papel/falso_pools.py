"""Pools e RPC da Base de MENTIRA (sem rede; semente fixa): as trocas dos pools sobre os preços do mundo de mentira
(tools/mercado/falso.py), no formato dos eventos `Swap` do Uniswap v3 (ABI; o Slipstream usa o mesmo), mais
`eth_getBlockByNumber`, `eth_gasPrice`, as fábricas (`getPool`), `token0()`/`token1()`/`fee()`/`tickSpacing()`,
`decimals()`/`balanceOf()`, o gauge do Aerodrome (`gauge()`, `stakedLiquidity()`, `liquidity()`, `unstakedFee()`,
`rewardRate()`, `periodFinish()`), o preço do AERO no GeckoTerminal e o `getReserveData` do Aave (de falso_looping.py).
Nada aqui é dado real: os endereços são os candidatos de verdade (para a escolha ser exercitada), os números não.

Imita os limites do publicnode: mais de 20.000 eventos num pedido → erro; blocos de mais de 30 dias atrás → "Archive
requests require a personal token". Uma troca a cada `cada` blocos (por pool), sorteada pelo número do bloco (sempre a
mesma), com o preço do mundo e um ruído pequeno (o vai e vem que faz as faixas estreitas saírem e voltarem).
"""
from __future__ import annotations

import math

import pools as PL
import rede

B0 = 20_000_000          # o bloco no começo do mundo de mentira
CADA = 9                 # WETH/USDC: em média uma troca a cada 9 blocos (18 s), ~4.800 por dia
LIQ = 3 * 10 ** 18       # liquidez ativa crua do WETH/USDC (mais ou menos a do pool de verdade)
T = {k: v[0] for k, v in PL.TOKENS.items()}
GAUGE_A, GAUGE_B, GAUGE_C = "0x" + "a1" * 20, "0x" + "a2" * 20, "0x" + "a3" * 20
AERO_PRECO = 0.95

# endereço → (token0, token1, taxa, espaço, troca a cada N blocos, semente, ruído, gauge, liquidez crua, US$ guardados)
POOLS = {
    PL.POOL: ("WETH", "USDC", 500, 10, CADA, 0, 1.0, None, LIQ, 30_000_000),
    "0xfBB6Eed8e7aa03B138556eeDaF5D271A5E1e43ef": ("USDC", "cbBTC", 500, 10, 31, 101, 0.8, None, 2 * 10 ** 9, 8_000_000),
    "0xeC558e484cC9f2210714E345298fdc53B253c27D": ("USDC", "cbBTC", 3000, 60, 400, 102, 0.8, None, 10 ** 8, 900_000),
    "0x7AeA2E8A3843516afa07293a10Ac8E49906dabD1": ("WETH", "cbBTC", 500, 10, 37, 103, 0.5, None, 4 * 10 ** 14, 17_000_000),
    "0xb2cc224c1c9feE385f8ad6a55b4d94E92359DC59": ("WETH", "USDC", 500, 100, 13, 104, 1.0, GAUGE_A, 3 * 10 ** 18, 3_000_000),
    "0xdbc6998296caA1652A810dc8D3BaF4A8294330f1": ("WETH", "USDC", 100, 1, 60, 105, 1.0, GAUGE_B, 10 ** 17, 1_100_000),
    "0xa41Bc0AFfbA7Fd420d186b84899d7ab2aC57fcD1": ("USDC", "USDT", 100, 1, 23, 106, 0.05, GAUGE_C, 5 * 10 ** 15, 450_000),
    "0xC5e51044eB7318950B1aFb044FccFb25782C48c1": ("EURC", "USDC", 500, 50, 90, 107, 0.2, None, 10 ** 12, 150_000),
    "0xd56da2b74bA826f19015E6B7Dd9Dae1903E85DA1": ("USDC", "USDT", 100, 1, 200, 108, 0.05, None, 10 ** 12, 80_000),
    "0xd43DecD5Df4BdFfd5A4cF35ca1F9557E33B7246c": ("USDC", "BRZ", 500, 10, 1500, 109, 0.3, None, 10 ** 15, 500),
}
FABRICA_UNI = {("cbBTC", "USDC", 500): "0xfBB6Eed8e7aa03B138556eeDaF5D271A5E1e43ef",
               ("cbBTC", "USDC", 3000): "0xeC558e484cC9f2210714E345298fdc53B253c27D",
               ("WETH", "cbBTC", 500): "0x7AeA2E8A3843516afa07293a10Ac8E49906dabD1",
               ("USDT", "USDC", 100): "0xd56da2b74bA826f19015E6B7Dd9Dae1903E85DA1"}
FABRICA_AERO = {("WETH", "USDC", 100): "0xb2cc224c1c9feE385f8ad6a55b4d94E92359DC59",
                ("WETH", "USDC", 1): "0xdbc6998296caA1652A810dc8D3BaF4A8294330f1",
                ("USDT", "USDC", 1): "0xa41Bc0AFfbA7Fd420d186b84899d7ab2aC57fcD1"}
GAUGES = {GAUGE_A: 0.06, GAUGE_B: 0.01, GAUGE_C: 0.004}   # AERO por segundo
DECIMAIS = {"WETH": 18, "USDC": 6, "cbBTC": 8, "USDT": 6, "EURC": 6, "BRZ": 18, "AERO": 18}
POR_END = {k.lower(): k for k in POOLS}
SIM = {v.lower(): k for k, v in T.items()}


def _h(b):
    """Um número de 0 a 1 sorteado pelo bloco (sempre o mesmo)."""
    x = (b * 2654435761) & 0xFFFFFFFF
    x ^= x >> 13
    x = (x * 1274126177) & 0xFFFFFFFF
    return (x ^ (x >> 16)) / 0xFFFFFFFF


def _palavra(v):
    return f"{v % (1 << 256):064x}"


def _end_palavra(a):
    return "0x" + a[2:].lower().rjust(64, "0")


class Falso:
    def preparar(self):
        import falso_mercado
        self._t0_bloco = falso_mercado.T0
        self.rpc_falhar = set()   # métodos do RPC que dão erro (testes)
        self.max_eventos = PL.MAX_EVENTOS_PEDIDO
        self.pools_fora = set()   # endereços de pool que não respondem (testes)

    # ------------------------------------------------------------------ tempo dos blocos
    def _bloco_de(self, t):
        return B0 + (int(t) - self._t0_bloco) // PL.BLOCO_MS

    def _t_de(self, b):
        return self._t0_bloco + (b - B0) * PL.BLOCO_MS

    def _usd(self, sim, b):
        t = self._t_de(b)
        if sim == "WETH":
            return self.mundo.px("ETH", t)
        if sim == "cbBTC":
            return self.mundo.px("BTC", t)
        if sim == "USDT":
            return 1.0 + 0.0003 * math.sin(b / 500.0)
        if sim == "EURC":
            return 1.15 * (1 + 0.002 * math.sin(b / 4000.0))
        if sim == "BRZ":
            return 0.185 * (1 + 0.003 * math.sin(b / 3000.0))
        if sim == "AERO":
            return AERO_PRECO
        return 1.0

    def _px(self, b):
        """O preço do WETH/USDC (o pool de sempre)."""
        return self._px_pool(PL.POOL, b)

    def _px_pool(self, end, b):
        """token1 por token0 (em unidades inteiras) no bloco b, com o ruído do pool."""
        t0, t1, _f, _e, _c, sem, ruido, *_ = POOLS[end]
        p = self._usd(t0, b) / self._usd(t1, b)
        if end == PL.POOL:
            return p * (1 + 0.0012 * math.sin(b / 37.0) + 0.0008 * (_h(b + 7) - 0.5))
        return p * (1 + ruido * (0.0012 * math.sin((b + sem) / 37.0) + 0.0008 * (_h(b + 7 + sem) - 0.5)))

    def _evento(self, b):
        return self._evento_pool(PL.POOL, b)

    def _evento_pool(self, end, b):
        t0, t1, _f, _e, cada, sem, _r, _g, liq, _tvl = POOLS[end]
        d0, d1 = DECIMAIS[t0], DECIMAIS[t1]
        p = self._px_pool(end, b)
        s_cru = math.sqrt(p / 10 ** (d0 - d1))
        sx96 = int(s_cru * PL.Q96)
        sobe = p >= self._px_pool(end, b - cada)
        usd = (50 + 20_000 * _h(b + 3 + sem) ** 3) * (1.0 if end == PL.POOL else min(1.0, _tvl / 1e6))
        a1 = int(usd / self._usd(t1, b) * 10 ** d1) * (1 if sobe else -1)
        a0 = -int(usd / self._usd(t0, b) * 10 ** d0) * (1 if sobe else -1)
        tick = math.floor(math.log(s_cru ** 2) / PL.BASE_TICK)
        dados = "0x" + "".join(_palavra(v) for v in (a0, a1, sx96, liq, tick))
        return {"address": end.lower(), "topics": [PL.TOPICO_SWAP, "0x" + "0" * 64, "0x" + "0" * 64],
                "data": dados, "blockNumber": hex(b), "logIndex": hex(int(_h(b + 11 + sem) * 50)),
                "transactionHash": "0x" + "ab" * 32}

    # ------------------------------------------------------------------ contratos
    def _call(self, para, dados, topo):
        p = para.lower()
        sel = dados[:10]
        if p == PL.UNI_FABRICA.lower() or p in (f.lower() for f in PL.AERO_FABRICAS):
            if sel not in (PL.SEL_GETPOOL_UNI, PL.SEL_GETPOOL_AERO):
                raise rede.Erro("RPC eth_call: execution reverted", codigo=3)
            a, b_ = "0x" + dados[34:74], "0x" + dados[98:138]
            k = int(dados[138:202], 16)
            sa, sb = SIM.get(a.lower()), SIM.get(b_.lower())
            tab = FABRICA_UNI if p == PL.UNI_FABRICA.lower() else FABRICA_AERO
            end = tab.get((sa, sb, k)) or tab.get((sb, sa, k))
            return _end_palavra(end or PL.ZERO)
        if p in SIM:  # um token
            sim = SIM[p]
            if sel == PL.SEL_DECIMAIS:
                return "0x" + _palavra(DECIMAIS[sim])
            if sel == PL.SEL_SALDO:
                quem = ("0x" + dados[34:74]).lower()
                if quem in POR_END:
                    end = POR_END[quem]
                    t0, t1, *_r, tvl = POOLS[end]
                    if sim in (t0, t1):
                        return "0x" + _palavra(int(tvl / 2 / self._usd(sim, topo) * 10 ** DECIMAIS[sim]))
                return "0x" + _palavra(0)
            raise rede.Erro("RPC eth_call: execution reverted", codigo=3)
        if p in POR_END:
            end = POR_END[p]
            if end in self.pools_fora:
                raise rede.Erro("RPC eth_call: execution reverted", codigo=3)
            t0, t1, fee, esp, _c, _s, _r, gauge, liq, _tvl = POOLS[end]
            if sel == PL.SEL_TOKEN0:
                return _end_palavra(T[t0])
            if sel == PL.SEL_TOKEN1:
                return _end_palavra(T[t1])
            if sel == PL.SEL_FEE:
                return "0x" + _palavra(fee)
            if sel == PL.SEL_ESPACO:
                return "0x" + _palavra(esp)
            if gauge:
                if sel == PL.SEL_GAUGE:
                    return _end_palavra(gauge)
                if sel == PL.SEL_STAKED:
                    return "0x" + _palavra(int(liq * 0.6))
                if sel == PL.SEL_LIQ:
                    return "0x" + _palavra(liq)
                if sel == PL.SEL_UNSTAKED:
                    return "0x" + _palavra(100_000)
            raise rede.Erro("RPC eth_call: execution reverted", codigo=3)
        if p in GAUGES:
            if sel == PL.SEL_RATE:
                return "0x" + _palavra(int(GAUGES[p] * 1e18))
            if sel == PL.SEL_FIM:
                return "0x" + _palavra(int(self._t_de(topo) / 1000) + 5 * 86400)
            raise rede.Erro("RPC eth_call: execution reverted", codigo=3)
        return None

    # ------------------------------------------------------------------ RPC
    def rpc(self, metodo, params, rede_=None):
        self._contar("rpc:" + metodo, 1)
        if metodo in self.rpc_falhar:
            raise rede.Erro(f"RPC {metodo}: falha de teste")
        topo = self._bloco_de(self.agora)
        if metodo == "eth_getBlockByNumber":
            return {"number": hex(topo), "timestamp": hex(self._t_de(topo) // 1000)}
        if metodo == "eth_blockNumber":
            return hex(topo)
        if metodo == "eth_gasPrice":
            return hex(int(6e6 + 4e6 * _h(self.agora // 3_600_000)))
        if metodo == "eth_call":
            para, dados = params[0]["to"], params[0]["data"]
            r = self._call(para, dados, topo)
            if r is not None:
                return r
            if hasattr(self, "_eth_call_aave"):
                return self._eth_call_aave(para, dados)
            raise rede.Erro("RPC eth_call: execution reverted", codigo=3)
        if metodo == "eth_getLogs":
            f = params[0]
            a, b = int(f["fromBlock"], 16), min(int(f["toBlock"], 16), topo)
            if a < topo - 30 * PL.BLOCOS_DIA:
                raise rede.Erro("RPC eth_getLogs: Archive requests require a personal token", 403, -32000)
            end = POR_END.get(str(f.get("address", "")).lower())
            if not end or PL.TOPICO_SWAP not in (f.get("topics") or []):
                return []
            cada, sem = POOLS[end][4], POOLS[end][5]
            ini = a - a % cada + cada if a % cada else a
            blocos = [x for x in range(ini, b + 1, cada) if _h(x + sem) < 0.9]
            if len(blocos) > self.max_eventos:
                raise rede.Erro(f"RPC eth_getLogs: query exceeds max results {self.max_eventos}, retry with a smaller range", codigo=-32602)
            return [self._evento_pool(end, x) for x in blocos]
        raise rede.Erro(f"RPC {metodo}: método de mentira desconhecido")

    def gecko(self, caminho):
        self._contar("gecko", 1)
        if caminho.startswith("/networks/base/pools/"):
            return {"data": {"id": "base_" + PL.POOL.lower(), "type": "pool",
                             "attributes": {"volume_usd": {"h24": "23500000.5"}, "reserve_in_usd": "30500000.1",
                                            "base_token_price_usd": f"{self.mundo.px('ETH', self.agora):.2f}"}}}
        if caminho.startswith("/networks/base/tokens/") and caminho.endswith(T["AERO"].lower()):
            return {"data": {"id": "base_" + T["AERO"].lower(), "type": "token",
                             "attributes": {"symbol": "AERO", "price_usd": f"{AERO_PRECO:.4f}"}}}
        if hasattr(self, "_gecko_memes"):
            return self._gecko_memes(caminho)
        raise rede.Erro("HTTP 404 em GeckoTerminal", 404)
