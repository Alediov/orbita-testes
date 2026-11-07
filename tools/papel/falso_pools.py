"""Pool e RPC da Base de MENTIRA (sem rede; semente fixa): as trocas do pool WETH/USDC 0,05% sobre o ether do mundo de
mentira (tools/mercado/falso.py), no formato dos eventos `Swap` do Uniswap v3 (ABI), mais `eth_getBlockByNumber`,
`eth_gasPrice`, `token0()`/`fee()` e o `getReserveData` do Aave (de falso_looping.py). Nada aqui é dado real.

Imita os limites do publicnode: mais de 20.000 eventos num pedido → erro; blocos de mais de 30 dias atrás → "Archive
requests require a personal token". Uma troca a cada `CADA` blocos, sorteada pelo número do bloco (sempre a mesma), com
o preço do ether do mundo e um ruído pequeno (o vai e vem que faz as faixas estreitas saírem e voltarem).
"""
from __future__ import annotations

import math

import pools as PL
import rede

B0 = 20_000_000          # o bloco no começo do mundo de mentira
CADA = 9                 # em média uma troca a cada 9 blocos (18 s), ~4.800 por dia
LIQ = 3 * 10 ** 18       # liquidez ativa crua (mais ou menos a do pool de verdade)


def _h(b):
    """Um número de 0 a 1 sorteado pelo bloco (sempre o mesmo)."""
    x = (b * 2654435761) & 0xFFFFFFFF
    x ^= x >> 13
    x = (x * 1274126177) & 0xFFFFFFFF
    return (x ^ (x >> 16)) / 0xFFFFFFFF


def _palavra(v):
    return f"{v % (1 << 256):064x}"


class Falso:
    def preparar(self):
        import falso_mercado
        self._t0_bloco = falso_mercado.T0
        self.rpc_falhar = set()   # métodos do RPC que dão erro (testes)
        self.max_eventos = PL.MAX_EVENTOS_PEDIDO

    # ------------------------------------------------------------------ tempo dos blocos
    def _bloco_de(self, t):
        return B0 + (int(t) - self._t0_bloco) // PL.BLOCO_MS

    def _t_de(self, b):
        return self._t0_bloco + (b - B0) * PL.BLOCO_MS

    def _px(self, b):
        t = self._t_de(b)
        p = self.mundo.px("ETH", t)
        return p * (1 + 0.0012 * math.sin(b / 37.0) + 0.0008 * (_h(b + 7) - 0.5))

    def _evento(self, b):
        p = self._px(b)
        s_cru = math.sqrt(p / 10 ** (PL.DEC0 - PL.DEC1))
        sx96 = int(s_cru * PL.Q96)
        sobe = self._px(b) >= self._px(b - CADA)
        usd = 50 + 20_000 * _h(b + 3) ** 3
        a1 = int(usd * 10 ** PL.DEC1) * (1 if sobe else -1)
        a0 = -int(usd / p * 10 ** PL.DEC0) * (1 if sobe else -1)
        tick = math.floor(math.log(s_cru ** 2) / PL.BASE_TICK)
        dados = "0x" + "".join(_palavra(v) for v in (a0, a1, sx96, LIQ, tick))
        return {"address": PL.POOL.lower(), "topics": [PL.TOPICO_SWAP, "0x" + "0" * 64, "0x" + "0" * 64],
                "data": dados, "blockNumber": hex(b), "logIndex": hex(int(_h(b + 11) * 50)), "transactionHash": "0x" + "ab" * 32}

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
            para, dados = params[0]["to"].lower(), params[0]["data"]
            if para == PL.POOL.lower():
                if dados.startswith(PL.SEL_TOKEN0):
                    return "0x" + "0" * 24 + PL.WETH[2:].lower()
                if dados.startswith(PL.SEL_FEE):
                    return "0x" + _palavra(500)
            if hasattr(self, "_eth_call_aave"):
                return self._eth_call_aave(params[0]["to"], dados)
            raise rede.Erro("RPC eth_call: execution reverted", codigo=3)
        if metodo == "eth_getLogs":
            f = params[0]
            a, b = int(f["fromBlock"], 16), min(int(f["toBlock"], 16), topo)
            if a < topo - 30 * PL.BLOCOS_DIA:
                raise rede.Erro("RPC eth_getLogs: Archive requests require a personal token", 403, -32000)
            if str(f.get("address", "")).lower() != PL.POOL.lower() or PL.TOPICO_SWAP not in (f.get("topics") or []):
                return []
            blocos = [x for x in range(a - a % CADA + CADA if a % CADA else a, b + 1, CADA) if _h(x) < 0.9]
            if len(blocos) > self.max_eventos:
                raise rede.Erro(f"RPC eth_getLogs: query exceeds max results {self.max_eventos}, retry with a smaller range", codigo=-32602)
            return [self._evento(x) for x in blocos]
        raise rede.Erro(f"RPC {metodo}: método de mentira desconhecido")

    def gecko(self, caminho):
        self._contar("gecko", 1)
        if caminho.startswith("/networks/base/pools/"):
            return {"data": {"id": "base_" + PL.POOL.lower(), "type": "pool",
                             "attributes": {"volume_usd": {"h24": "151000000.5"}, "reserve_in_usd": "30500000.1",
                                            "base_token_price_usd": f"{self.mundo.px('ETH', self.agora):.2f}"}}}
        if hasattr(self, "_gecko_memes"):
            return self._gecko_memes(caminho)
        raise rede.Erro("HTTP 404 em GeckoTerminal", 404)
