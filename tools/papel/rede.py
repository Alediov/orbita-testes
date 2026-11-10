"""Cliente HTTP pequeno das formas da fase 2 e 3 (looping, opções e pools), só leitura, só biblioteca padrão, sem chave.

Fontes gratuitas, todas testadas de dentro do GitHub Actions no "Teste de alcance" de 03/11/2026 (plano em
odonto-quest/docs/plano-testes-mercado-2.md; as amostras das respostas estão anotadas em cada módulo):

- Deribit pública (`www.deribit.com/api/v2/public/<método>`): cadeia de opções, índice, DVOL e preços de entrega;
- API GraphQL do Aave (`api.v3.aave.com/graphql`): mercados da Base e o histórico diário de juros;
- API GraphQL da Morpho (`blue-api.morpho.org/graphql`, pública, sem chave): os cofres de USDC na Base e o histórico
  diário da taxa (looping, régua "Só USDC na Morpho"; os nomes dos campos não foram conferidos daqui);
- DefiLlama (`yields.llama.fi`): o histórico diário do rendimento do staking (Lido) e, pelo `/pools` e `/chart`, o
  depósito de USDC da Moonwell na Base (e a reserva da Morpho);
- RPC público da Base (`base-rpc.publicnode.com`): eventos do pool da Uniswap, leitura de contratos e preço do gás.
  (O `mainnet.base.org` devolveu 429 no getLogs; o publicnode serviu. Mais de ~30 dias para trás o publicnode pede
  chave: "Archive requests require a personal token"; no máximo 20.000 eventos por pedido.)
- GeckoTerminal (`api.geckoterminal.com/api/v2`): pools e velas de minuto. Limite público de 30/min, mas o IP do
  Actions é dividido com outros (de 25 pedidos seguidos só 6 passaram): um pedido a cada `INTERVALO["gecko"]` e, no 429,
  espera de 30 s, 60 s e 90 s;
- DexScreener (`api.dexscreener.com`): os pares de até 30 tokens por pedido; RugCheck (`api.rugcheck.xyz`): os riscos
  de um token; RPC público da Solana (`solana-rpc.publicnode.com`): a taxa de prioridade;
- PumpPortal (`wss://pumpportal.fun/api/data`): os lançamentos do pump.fun (grátis; as negociações por token são pagas
  e não são usadas), por um cliente de websocket mínimo (`ws.py`, só biblioteca padrão);
- Jito (`bundles.jito.wtf/api/v1/bundles/tip_floor`, público, sem chave): as gorjetas que entraram nos últimos blocos
  (percentis, em SOL), para o custo de cada operação dos memecoins;
- gateway IPFS público (`ipfs.io`): os metadados de um token (só para saber SE tem site ou redes; o link nunca é
  guardado), lidos até `LIMITE_META` bytes. O endereço vem do próprio lançamento e só é aberto quando aponta para um
  CID do IPFS (pedido sempre ao ipfs.io) ou para o arweave.net.

`pedidos` conta todas as tentativas; `contagem` separa por fonte. `Erro.codigo` traz o código do erro do JSON-RPC
(o publicnode diz no texto o intervalo menor quando a resposta passaria de 20.000 eventos).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

UA = "orbita-testes/1"
URL = {
    "deribit": "https://www.deribit.com/api/v2/public/",
    "aave": "https://api.v3.aave.com/graphql",
    "morpho": "https://blue-api.morpho.org/graphql",
    "llama": "https://yields.llama.fi",
    "base": "https://base-rpc.publicnode.com",
    "gecko": "https://api.geckoterminal.com/api/v2",
    "dex": "https://api.dexscreener.com",
    "rugcheck": "https://api.rugcheck.xyz/v1",
    "solana": "https://solana-rpc.publicnode.com",
    "pumpportal": "wss://pumpportal.fun/api/data",
    "jito": "https://bundles.jito.wtf/api/v1/bundles/tip_floor",
    "ipfs": "https://ipfs.io/ipfs/",
}
REPETIR = (429, 500, 502, 503, 504)
# intervalo mínimo entre dois pedidos à mesma fonte (s): o freio contra o 429
INTERVALO = {"base": 0.12, "gecko": 2.5, "dex": 1.1, "rugcheck": 1.1, "solana": 0.3, "jito": 1.0, "ipfs": 0.5}
LIMITE_META = 32_768  # bytes lidos dos metadados de um token (um JSON pequeno; o resto é cortado)
# espera no 429 (s), por tentativa; as outras fontes usam 5 × 2^k
ESPERA_429 = {"gecko": [30, 60, 90]}


class Erro(Exception):
    def __init__(self, msg, status=None, codigo=None):
        super().__init__(msg)
        self.status = status
        self.codigo = codigo


def estrutura(x, prof=3):
    """As chaves de uma resposta (sem valores), para conferir o formato na primeira rodada de verdade."""
    if prof <= 0:
        return "…"
    if isinstance(x, dict):
        return {str(k): estrutura(x[k], prof - 1) for k in list(x)[:10]}
    if isinstance(x, list):
        return [estrutura(x[0], prof - 1)] if x else []
    return type(x).__name__


class Cliente:
    def __init__(self, tentativas=3, prazo=60, dormir=time.sleep, log=print, relogio=time.monotonic):
        self.tentativas, self.prazo, self.dormir, self.log, self.relogio = tentativas, prazo, dormir, log, relogio
        self.pedidos = 0
        self.contagem = Counter()
        self._ultimo = {}

    def _freio(self, tipo):
        i = INTERVALO.get(tipo)
        if not i:
            return
        falta = self._ultimo.get(tipo, -1e9) + i - self.relogio()
        if falta > 0:
            self.dormir(falta)
        self._ultimo[tipo] = self.relogio()

    def _http(self, url, tipo, rotulo, corpo=None, aceitar="application/json", limite=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        cab = {"User-Agent": UA, "Accept": aceitar}
        if dados:
            cab["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=dados, headers=cab, method="POST" if dados else "GET")
        tentativas = self.tentativas + (1 if tipo in ESPERA_429 else 0)
        for k in range(tentativas):
            self._freio(tipo)
            self.pedidos += 1
            self.contagem[tipo] += 1
            try:
                with urllib.request.urlopen(req, timeout=self.prazo) as r:
                    b = r.read(limite) if limite else r.read()
                try:
                    return json.loads(b.decode("utf-8", errors="replace"))
                except ValueError:
                    raise Erro(f"JSON inválido em {rotulo}") from None
            except urllib.error.HTTPError as e:
                corpo_erro = b""
                try:
                    corpo_erro = e.read()[:600]
                except Exception:  # noqa: BLE001
                    pass
                if e.code in REPETIR and k < tentativas - 1:
                    s = ESPERA_429[tipo][min(k, len(ESPERA_429[tipo]) - 1)] if e.code == 429 and tipo in ESPERA_429 else min(60, 5 * 2 ** k)
                    self.log(f"  HTTP {e.code} em {rotulo}; espera {s}s")
                    self.dormir(s)
                    continue
                # o publicnode responde 403 com o erro do JSON-RPC no corpo (ex.: "Archive requests require…")
                try:
                    j = json.loads(corpo_erro.decode("utf-8", errors="replace"))
                    if isinstance(j, dict) and isinstance(j.get("error"), dict):
                        raise Erro(f"{rotulo}: {str(j['error'].get('message'))[:200]}", e.code, j["error"].get("code"))
                except ValueError:
                    pass
                raise Erro(f"HTTP {e.code} em {rotulo}", e.code) from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if k < tentativas - 1:
                    self.dormir(min(30, 3 * 2 ** k))
                    continue
                raise Erro(f"rede em {rotulo}: {getattr(e, 'reason', None) or type(e).__name__}") from None
        raise Erro(f"sem resposta em {rotulo}")

    # ------------------------------------------------------------------ fontes
    def deribit(self, metodo, **params):
        """GET público da Deribit; devolve o `result` (a resposta vem como {"jsonrpc", "result", "usIn"…})."""
        consulta = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        j = self._http(f"{URL['deribit']}{metodo}?{consulta}", "deribit", f"Deribit {metodo}")
        if isinstance(j, dict) and j.get("error"):
            raise Erro(f"Deribit {metodo}: {str(j['error'])[:200]}")
        return (j or {}).get("result")

    def aave(self, query):
        """POST na API GraphQL do Aave; devolve o `data`. Erros do GraphQL (campo que não existe…) viram Erro com as
        mensagens, que dizem o que mudou no esquema."""
        j = self._http(URL["aave"], "aave", "Aave GraphQL", {"query": query})
        if not isinstance(j, dict):
            raise Erro("Aave GraphQL: resposta sem objeto")
        if j.get("errors"):
            msgs = "; ".join(str((e or {}).get("message"))[:160] for e in j["errors"][:3])
            raise Erro(f"Aave GraphQL: {msgs}")
        return j.get("data") or {}

    def morpho(self, query):
        """POST na API GraphQL pública da Morpho; devolve o `data` (erros do GraphQL viram Erro com as mensagens)."""
        j = self._http(URL["morpho"], "morpho", "Morpho GraphQL", {"query": query})
        if not isinstance(j, dict):
            raise Erro("Morpho GraphQL: resposta sem objeto")
        if j.get("errors"):
            msgs = "; ".join(str((e or {}).get("message"))[:160] for e in j["errors"][:3])
            raise Erro(f"Morpho GraphQL: {msgs}")
        return j.get("data") or {}

    def llama(self, caminho):
        """GET na DefiLlama (yields), ex.: "/chart/<id do pool>"."""
        return self._http(URL["llama"] + caminho, "llama", f"DefiLlama {caminho.split('/')[1] if '/' in caminho else caminho}")

    def rpc(self, metodo, params, rede="base"):
        """JSON-RPC na Base (ou na Solana, `rede="solana"`), pelo publicnode; devolve o `result`."""
        j = self._http(URL[rede], rede, f"RPC {metodo}", {"jsonrpc": "2.0", "id": 1, "method": metodo, "params": params})
        if isinstance(j, dict) and j.get("error"):
            e = j["error"] if isinstance(j["error"], dict) else {"message": str(j["error"])}
            raise Erro(f"RPC {metodo}: {str(e.get('message'))[:200]}", codigo=e.get("code"))
        return (j or {}).get("result")

    def solana(self, metodo, params):
        return self.rpc(metodo, params, rede="solana")

    def gecko(self, caminho):
        """GET no GeckoTerminal, ex.: "/networks/base/pools/0x…" (com o freio do IP dividido do Actions)."""
        return self._http(URL["gecko"] + caminho, "gecko", f"GeckoTerminal {caminho.split('?')[0][:60]}",
                          aceitar="application/json;version=20230302")

    def dexscreener(self, caminho):
        """GET na DexScreener, ex.: "/tokens/v1/solana/<mint1>,<mint2>" (até 30 tokens)."""
        return self._http(URL["dex"] + caminho, "dex", "DexScreener " + caminho.split("/")[1] if "/" in caminho else caminho)

    def rugcheck(self, mint):
        """O resumo dos riscos de um token da Solana (RugCheck)."""
        return self._http(f"{URL['rugcheck']}/tokens/{mint}/report/summary", "rugcheck", "RugCheck")

    def jito(self):
        """As gorjetas da Jito que entraram nos últimos blocos (lista com os percentis, em SOL)."""
        return self._http(URL["jito"], "jito", "Jito (gorjetas)")

    def metadados(self, url):
        """O JSON de metadados de um token (só os primeiros `LIMITE_META` bytes; o endereço já vem conferido)."""
        tentativas, self.tentativas = self.tentativas, 1  # metadado que não abre de primeira fica sem dados
        try:
            return self._http(url, "ipfs", "metadados (IPFS)", limite=LIMITE_META)
        finally:
            self.tentativas = tentativas

    def pumpportal_ouvir(self, segundos, maximo, assinar=("subscribeNewToken", "subscribeMigration")):
        """Ouve o websocket do PumpPortal por até `segundos` (ou `maximo` mensagens) e devolve as mensagens (dicts, com
        `_t` = ms da chegada)."""
        import ws
        self.pedidos += 1
        self.contagem["pumpportal"] += 1
        try:
            brutas = ws.ouvir(URL["pumpportal"], [json.dumps({"method": m}) for m in assinar], segundos, maximo,
                              prazo=min(self.prazo, 30), com_hora=True)
        except (OSError, ws.ErroWs) as e:
            raise Erro(f"PumpPortal: {e}") from None
        out = []
        for ms, b in brutas:
            try:
                j = json.loads(b)
            except ValueError:
                continue
            if isinstance(j, dict):
                j["_t"] = ms  # a hora da chegada (as mensagens de criação não trazem a hora)
                out.append(j)
        return out


def fonte_de(ctx, metodo):
    """O cliente que tem `metodo`: o próprio cliente da rodada (o falso, com os mixins) ou um Cliente de verdade."""
    cli = ctx.cli
    if hasattr(cli, metodo):
        return cli
    f = getattr(ctx, "_rede", None)
    if f is None:
        f = Cliente(log=ctx.log)
        try:
            ctx._rede = f
        except AttributeError:
            pass
    return f


def somar_pedidos(ctx, fonte, antes):
    """Soma ao cliente da rodada os pedidos feitos por fora dele (para o `rodada.pedidos` e o log contarem estes)."""
    if fonte is not ctx.cli and hasattr(ctx.cli, "pedidos"):
        ctx.cli.pedidos += getattr(fonte, "pedidos", 0) - antes
