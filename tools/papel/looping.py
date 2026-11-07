"""Empréstimo em cascata (looping) no Aave v3 da Base, NO PAPEL (plano: docs/plano-testes-mercado-2.md, seção 8;
formato: tools/papel/FORMATO.md). Nenhuma carteira, nenhuma ordem, nenhuma chave: só leituras públicas.

A ideia: depositar uma moeda, tomar outra emprestada contra o depósito, trocar pela primeira e depositar de novo,
várias vezes (na vida real, de uma vez só, com um empréstimo relâmpago). O rendimento do depósito e o juro do empréstimo
ficam multiplicados. Se a garantia passar a valer pouco perto da dívida (fator de saúde < 1), o protocolo vende parte
dela com multa: a liquidação.

- **wstETH × WETH** (modo eficiente do Aave, "e-mode" das moedas ligadas ao ether): o wstETH é ether em staking (rende
  ~3% ao ano pelo próprio preço em ether); a dívida é em ether. O preço do ether não importa: o Aave avalia o wstETH
  pela taxa de troca do staking (não pelo mercado), então o fator de saúde só anda pelo juro contra o staking. O perigo
  é o juro do ether passar o rendimento do staking (aí cada × multiplica o prejuízo). Até 6× (regra do Alediov).
  **A conta destas versões é medida em ether**, convertida em dólar pelo preço do ether no dia em que a conta começou
  (`pref`): o que sobra é só o laço (staking contra juro), comparável com o CDI. Em dólar de verdade a conta subiria e
  cairia junto com o ether (quem começa com dólar compra ether); esse valor vai em `extra.emDolar`.
- **ETH × USDC**: deposita ether, toma dólar, compra mais ether: uma aposta alavancada na alta, com liquidação de
  verdade quando o ether cai. 1,5× e 2×, uma delas com defesa (desalavanca quando o fator de saúde cai a 1,3).
- **Só USDC**: depositar dólar sem laço, a régua.

Simulação: juros compostos dos dois lados com a taxa diária do Aave (`supplyAPYHistory`/`borrowAPYHistory`, 365 dias);
o staking do wstETH pela taxa diária do Lido na DefiLlama; o ether pelas velas da Hyperliquid (1 h ao vivo, 1 dia no
teste no passado), com o fator de saúde = garantia × limite de liquidação ÷ dívida conferido pela MÍNIMA da vela;
liquidação pela regra do Aave v3 (metade da dívida, ou toda abaixo de 0,95, com o bônus do ativo para o liquidante),
em cascata enquanto o fator continuar abaixo de 1. Montar e desmontar: troca de 0,05% + deslize de 0,03% sobre o que é
trocado, empréstimo relâmpago de 0,05% sobre a dívida e o gás da Base.

Amostras conferidas (Teste de alcance, 03/11/2026): `{ markets(request:{chainIds:[8453]}) { name address reserves {
underlyingToken { symbol } supplyInfo { apy { value } } borrowInfo { apy { value } } } } }` → `{"name": "AaveV3Base",
"address": "0xA238…d1c5", "reserves": [{"underlyingToken": {"symbol": "EURC"}, "supplyInfo": {"apy": {"value":
"0.0195…"}}, …}]}` (fração); `supplyAPYHistory(request:{market, underlyingToken, window: LAST_YEAR, chainId: 8453})
{ date avgRate { value } }` → 365 itens `{"date": "2026-11-03T00:00:00+00:00", "avgRate": {"value": "0.01485…"}}`;
`getReserveData(WETH)` no RPC (o 1º campo, a configuração, deu LTV 81%, limite 84% e bônus 5%); DefiLlama `/chart/<pool>`
→ `{"status": "success", "data": [{"timestamp": "…Z", "apy": 5.4, "apyBase": …}]}`.
NÃO conferidos (a 1ª rodada de verdade registra no log): o campo `address` de `underlyingToken` (sem ele, os endereços
fixos de `ENDERECOS`) e o `eModeCategories` (sem ele, o e-mode de `EMODE_PADRAO`: 90% / 93% / 1%).
"""
from __future__ import annotations

import copy
import math

import rede
from conta import CAPITAL, DIA, HORA, Curva, Eventos, dia_de, moeda_br, num_br, pct_br

try:
    import hl
    ERROS = (rede.Erro, hl.Erro)
except ImportError:  # pragma: no cover
    ERROS = (rede.Erro,)

NOME = "Looping"
VERSAO = 1

POOL = "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"  # Pool do Aave v3 na Base (conferido no Teste de alcance)
CHAIN = 8453
ENDERECOS = {  # reserva, se o GraphQL não trouxer o endereço (o WETH foi conferido; os outros são os conhecidos)
    "WETH": "0x4200000000000000000000000000000000000006",
    "wstETH": "0xc1CBa3fCea344f92D9239c08C0568f6F2F0ee452",
    "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
}
LIDO_LLAMA = "747c1d2a-c668-4682-b9f9-296708a3dd90"  # Lido stETH na DefiLlama (conferido na lista de pools)
PARAMS_PADRAO = {"WETH": {"lt": 0.84, "bonus": 0.05}, "wstETH": {"lt": 0.79, "bonus": 0.06}, "USDC": {"lt": 0.78, "bonus": 0.05}}
EMODE_PADRAO = {"lt": 0.93, "bonus": 0.01, "ltv": 0.90, "nome": "ETH correlated"}
STAKING_PADRAO = 0.028
ANO_MS = 365 * DIA
TAXA_TROCA = 0.0005
DESLIZE = 0.0003
TAXA_RELAMPAGO = 0.0005
GAS_US = 0.05             # montar ou desmontar (várias transações na Base)
ALAV_MAX = 6              # regra do Alediov: só no looping, até 6×
FECHAMENTO_PARCIAL, HF_TODA = 0.5, 0.95
HIST_DIAS = 365
HIST_REFAZER = DIA
TAXAS_REFAZER = 12 * HORA
PARAMS_REFAZER = 7 * DIA
ALCANCE_MAX = 195 * DIA   # as velas de 1 h só vão até ~200 dias atrás
FOLGA_MS = 5 * 60_000

# (id, nome, tipo, alavancagem, defesa (fator de saúde) ou None, risco, frase)
VERSOES = [
    ("wst3", "wstETH 3×", "wst", 3, None, "baixo",
     "Deposita wstETH (ether em staking), toma ether emprestado e deposita de novo até 3× o dinheiro: ganha o staking "
     "3 vezes e paga o juro do ether 2 vezes."),
    ("wst6", "wstETH 6×", "wst", 6, None, "médio",
     "O mesmo laço até 6×: o ganho e o perigo (o juro do ether passar o staking) ficam maiores."),
    ("eth15", "ETH 1,5×", "eth", 1.5, None, "alto",
     "Deposita ether, toma dólar emprestado e compra mais ether até 1,5×: aposta na alta, liquidada se o ether cair uns 60%."),
    ("eth2", "ETH 2×", "eth", 2, None, "alto",
     "O mesmo com 2×: liquidada se o ether cair uns 40%."),
    ("eth2def", "ETH 2× com defesa", "eth", 2, 1.3, "alto",
     "2×, mas quando o fator de saúde cai a 1,3 vende um pouco do ether e paga a dívida, voltando a 2×."),
    ("usdc", "Só USDC", "usdc", 1, None, "baixo",
     "Só deposita os dólares no Aave e recebe o juro, sem laço: a régua das outras."),
]
FRASE = ("Deposita, toma emprestado contra o depósito e deposita de novo: multiplica o rendimento e o juro, e uma queda "
         "forte da garantia leva à liquidação.")
COMO_FUNCIONA = [
    "No Aave, um banco automático da rede Base, quem deposita recebe juro e pode tomar emprestado até uma parte do que "
    "depositou. O laço deposita, toma emprestado, troca e deposita de novo, até a alavancagem escolhida.",
    "No wstETH × ether, o depósito é ether em staking (rende uns 3% ao ano) e a dívida é em ether: o preço do ether "
    "não leva à liquidação. Sobra a diferença entre o staking e o juro do ether, multiplicada. Se o juro passar o "
    "staking, a conta perde dia a dia. Por isso estas versões são medidas em ether (convertido pelo preço do primeiro "
    "dia): em dólar, elas subiriam e cairiam junto com o ether.",
    "No ether × dólar, a conta fica com mais ether do que o dinheiro dava: ganha mais na alta, perde mais na queda e, "
    "se o ether cair demais, o Aave vende parte do ether com multa (a liquidação). A versão com defesa vende um pouco "
    "antes disso.",
    "O fator de saúde é garantia × limite ÷ dívida: abaixo de 1, liquidação. Juros do dia do próprio Aave, staking do "
    "Lido, troca de 0,05% + deslize, empréstimo relâmpago de 0,05% e o gás da Base já estão descontados.",
]
AVISOS = [
    "O wstETH pode descolar do ether no mercado (como o stETH em 2022); o Aave usa a taxa do staking e não liquida por "
    "isso, mas quem precisar sair na hora vende com desconto.",
    "O juro do Aave muda a cada bloco; o papel usa a média de cada dia, que esconde picos de horas em que pegar "
    "emprestado fica muito caro.",
    "Falha de oráculo, erro de contrato ou um ataque ao protocolo podem levar o dinheiro todo; nenhum teste no papel mede "
    "isso.",
    "Na liquidação de verdade há fila e concorrência entre robôs; o papel liquida exatamente no preço em que o fator de "
    "saúde chega a 1.",
    "Pôr dinheiro na Base exige carteira própria, ponte e gás em ether; o papel começa com o dinheiro já lá.",
]


# ---------------------------------------------------------------------------------------------------- utilidades
def _f(x, padrao=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else padrao
    except (TypeError, ValueError):
        return padrao


def _apy(v):
    """A taxa do GraphQL vem em fração ("0.0148…" = 1,48%); um número acima de 1,5 só pode estar em %."""
    v = _f(v)
    if v is None:
        return None
    return v / 100 if v > 1.5 else v


def hora_de(ms):
    return (int(ms) // HORA) * HORA


def dia_utc(ms):
    import datetime as dt
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def config_reserva(hexa):
    """O 1º campo do getReserveData (a configuração, bits do Aave v3): LTV 0–15, limite 16–31, bônus 32–47 (em
    centésimos de %); o bônus vem como 10500 = 105% (5% para o liquidante)."""
    if not isinstance(hexa, str) or not hexa.startswith("0x") or len(hexa) < 66:
        return None
    c = int(hexa[2:66], 16)
    ltv, lt, bonus = c & 0xFFFF, (c >> 16) & 0xFFFF, (c >> 32) & 0xFFFF
    if not lt or bonus < 10000:
        return None
    return {"ltv": ltv / 10000, "lt": lt / 10000, "bonus": bonus / 10000 - 1}


# ---------------------------------------------------------------------------------------------------- dados
class Taxas:
    """As taxas ao ano por dia (UTC): `serie[chave] = {dia: taxa}` e a de agora `atual[chave]`. Chaves: "sup:WETH",
    "bor:WETH", "sup:wstETH", "sup:USDC", "bor:USDC" e "stake" (o staking do Lido)."""

    def __init__(self, serie=None, atual=None):
        self.serie = {k: dict(v) for k, v in (serie or {}).items()}
        self.atual = dict(atual or {})
        self._dias = {k: sorted(v) for k, v in self.serie.items()}

    def taxa(self, chave, t):
        d = dia_utc(t)
        s = self.serie.get(chave) or {}
        if d in s:
            return s[d]
        dias = self._dias.get(chave) or []
        if dias and d > dias[-1] and chave in self.atual:
            return self.atual[chave]
        import bisect
        i = bisect.bisect_right(dias, d) - 1
        if i >= 0:
            return s[dias[i]]
        if dias:
            return s[dias[0]]
        return self.atual.get(chave, STAKING_PADRAO if chave == "stake" else 0.0)


def _cresce(taxa, ms):
    return (1 + max(-0.99, taxa)) ** (ms / ANO_MS)


# ---------------------------------------------------------------------------------------------------- conta
class Conta:
    """Uma versão: `a` = depósito (unidades da garantia), `b` = dívida (unidades da dívida); no wstETH, `r` = o wstETH em
    ether (cresce com o staking; começa em 1)."""

    def __init__(self, cfg, inicio, params, estado=None):
        self.id, self.nome, self.tipo, self.alav, self.defesa, self.risco, self.frase = cfg
        assert self.alav <= ALAV_MAX
        e = estado or {}
        self.curva = Curva.de_json(e.get("curva")) or Curva(inicio=inicio)
        self.a, self.b, self.r = float(e.get("a", 0.0)), float(e.get("b", 0.0)), float(e.get("r", 1.0))
        self.montada = bool(e.get("montada"))
        self.t = int(e.get("t") or inicio)
        self.p = e.get("p")  # último preço do ether
        self.pref = e.get("pref")  # wstETH: o preço do ether quando a conta começou (a conta é medida em ether)
        acc = e.get("acc") or {}
        self.acc = {k: float(acc.get(k, 0.0)) for k in ("ganho", "custo", "defesas")}
        self.params = params
        self.novo = not estado

    def para_json(self):
        return {"curva": self.curva.para_json(), "a": self.a, "b": self.b, "r": self.r, "montada": self.montada,
                "t": self.t, "p": self.p, "pref": self.pref, "acc": self.acc}

    def _ev(self, ev, t, tipo, texto):
        if ev is not None:
            ev.add(t, tipo, texto, self.id)

    @property
    def lt(self):
        return self.params["emode"]["lt"] if self.tipo == "wst" else self.params["WETH"]["lt"]

    @property
    def bonus(self):
        return self.params["emode"]["bonus"] if self.tipo == "wst" else self.params["WETH"]["bonus"]

    def garantia_us(self, p):
        """Em US$; no wstETH, pelo preço de quando a conta começou (`pref`): a conta é medida em ether."""
        if self.tipo == "wst":
            return self.a * self.r * (self.pref or p)
        return self.a * (p if self.tipo == "eth" else 1.0)

    def divida_us(self, p):
        return self.b * (self.pref or p) if self.tipo == "wst" else self.b

    def valor(self, p):
        return self.garantia_us(p) - self.divida_us(p)

    def saude(self, p):
        if self.b <= 1e-12:
            return None
        if self.tipo == "wst":
            return self.a * self.r * self.lt / self.b
        return self.a * p * self.lt / self.b

    def preco_liquidacao(self):
        if self.tipo != "eth" or self.b <= 0 or self.a <= 0:
            return None
        return self.b / (self.a * self.lt)

    # ------------------------------------------------------------------ montar
    def montar(self, t, p, ev):
        E = self.curva.ultimo if self.curva.ultimo > 0 else CAPITAL
        L = self.alav
        if self.tipo == "usdc":
            custo = GAS_US
            self.a, self.b = E - custo, 0.0
        else:
            if self.tipo == "wst" and not self.pref:
                self.pref = p
            custo = L * E * (TAXA_TROCA + DESLIZE) + TAXA_RELAMPAGO * (L - 1) * E + GAS_US
            if self.tipo == "wst":
                self.a, self.b = (L * E - custo) / (self.r * p), (L - 1) * E / p
            else:
                self.a, self.b = (L * E - custo) / p, (L - 1) * E
        self.curva.operou(custo, 1)
        self.montada = True
        if self.tipo == "usdc":
            self._ev(ev, t, "abriu", f"Depositou {moeda_br(self.a)} em USDC no Aave.")
        else:
            moeda = "wstETH" if self.tipo == "wst" else "ether"
            divida = f"{num_br(self.b, 4)} ETH" if self.tipo == "wst" else moeda_br(self.b)
            hf = self.saude(p)
            self._ev(ev, t, "abriu", f"Montou o laço de {num_br(L, 1)}×: {moeda_br(self.garantia_us(p))} em {moeda} de garantia e "
                                     f"{divida} de dívida (fator de saúde {num_br(hf, 2) if hf else '—'}; custou {moeda_br(custo)}).")

    # ------------------------------------------------------------------ passo
    def passo(self, t, dt_ms, p, minima, tx, ev=None):
        """O período que termina em `t` (`dt_ms` de duração), com o ether fechando em `p` e a mínima `minima`."""
        self.t = t
        if p:
            self.p = p
        p = self.p
        if not p:
            return
        if not self.montada:
            self.montar(t, p, ev)
            self.curva.marcar(t, self.valor(p))
            self._extra(p, tx, t)
            return
        # juros e staking do período
        if self.tipo == "wst":
            a0, r0, b0 = self.a, self.r, self.b
            self.a *= _cresce(tx.taxa("sup:wstETH", t), dt_ms)
            self.r *= _cresce(tx.taxa("stake", t), dt_ms)
            self.b *= _cresce(tx.taxa("bor:WETH", t), dt_ms)
            self.acc["ganho"] += (self.a * self.r - a0 * r0) * self.pref
            self.acc["custo"] += (self.b - b0) * self.pref
        elif self.tipo == "eth":
            a0, b0 = self.a, self.b
            self.a *= _cresce(tx.taxa("sup:WETH", t), dt_ms)
            self.b *= _cresce(tx.taxa("bor:USDC", t), dt_ms)
            self.acc["ganho"] += (self.a - a0) * p
            self.acc["custo"] += self.b - b0
        else:
            a0 = self.a
            self.a *= _cresce(tx.taxa("sup:USDC", t), dt_ms)
            self.acc["ganho"] += self.a - a0
        # liquidação (pela mínima, em cascata)
        self._liquidar(t, minima or p, ev)
        # defesa (pelo fechamento)
        hf = self.saude(p)
        if self.defesa and hf is not None and hf < self.defesa and self.valor(p) > 0:
            self._desalavancar(t, p, hf, ev)
        self.curva.marcar(t, self.valor(minima or p) if self.tipo == "eth" else self.valor(p))
        self.curva.marcar(t, self.valor(p))
        self._extra(p, tx, t)

    def _liquidar(self, t, pmin, ev):
        for _ in range(8):
            hf = self.saude(pmin)
            if hf is None or hf >= 1 or self.a <= 0:
                return
            # o liquidante age no preço em que o fator chega a 1 (no wstETH, o fator não depende do preço)
            if self.tipo == "eth":
                pl = max(pmin, self.preco_liquidacao())
                hf_pl = self.a * pl * self.lt / self.b
                fator = FECHAMENTO_PARCIAL if hf_pl >= HF_TODA else 1.0
                paga = fator * self.b
                tomado = min(self.a, paga * (1 + self.bonus) / pl)
                perda = tomado * pl - paga
                self.b -= paga
                self.a -= tomado
                txt = f"o ether caiu a {moeda_br(pl, 0)}"
                pref = pl
            else:
                fator = FECHAMENTO_PARCIAL if hf >= HF_TODA else 1.0
                paga = fator * self.b
                tomado = min(self.a, paga * (1 + self.bonus) / self.r)
                perda = (tomado * self.r - paga) * (self.pref or self.p or 0)
                self.b -= paga
                self.a -= tomado
                txt = "o juro do ether passou o staking por tempo demais"
                pref = self.pref or self.p or 0
            self.curva.liquidou(t, "ETH" if self.tipo == "eth" else "wstETH", perda)
            self._ev(ev, t, "liquidou", f"Liquidada em parte: {txt} e o Aave vendeu {moeda_br(tomado * (pref if self.tipo == 'eth' else self.r * pref))} "
                                        f"da garantia para pagar metade da dívida; a multa custou {moeda_br(perda)}.")
            if fator >= 1:
                return

    def _desalavancar(self, t, p, hf, ev):
        E = self.valor(p)
        C = self.garantia_us(p)
        alvo_c = self.alav * E
        venda = C - alvo_c
        if venda <= 1:
            return
        custo = venda * (TAXA_TROCA + DESLIZE) + GAS_US
        # vende `venda` em ether e paga a dívida em dólar
        self.a -= venda / p
        self.b -= venda - custo
        self.curva.operou(custo, 1)
        self.acc["defesas"] += 1
        self._ev(ev, t, "reequilibrou", f"Defesa: o fator de saúde caiu a {num_br(hf, 2)}; vendeu {moeda_br(venda)} de ether "
                                        f"e pagou a dívida, voltando a {num_br(self.alav, 1)}× (custou {moeda_br(custo)}).")

    def _extra(self, p, tx, t):
        E = self.valor(p)
        C = self.garantia_us(p)
        hf = self.saude(p)
        if self.tipo == "wst":
            liq = (C * (tx.taxa("sup:wstETH", t) + tx.taxa("stake", t)) - self.divida_us(p) * tx.taxa("bor:WETH", t)) / E if E > 0 else None
            g, d = "wstETH", "ETH"
        elif self.tipo == "eth":
            liq = (C * tx.taxa("sup:WETH", t) - self.b * tx.taxa("bor:USDC", t)) / E if E > 0 else None
            g, d = "ETH", "USDC"
        else:
            liq, g, d = tx.taxa("sup:USDC", t), "USDC", None
        pl = self.preco_liquidacao()
        self.curva.extra = {"hf": round(hf, 4) if hf is not None else None, "alavAgora": round(C / E, 3) if E > 0 else None,
                            "rendeAno": round(liq, 5) if liq is not None else None, "ganhoJuros": round(self.acc["ganho"], 4),
                            "custoJuros": round(self.acc["custo"], 4), "defesas": int(self.acc["defesas"]),
                            "garantia": g, "divida": d, "precoLiquidacao": round(pl, 2) if pl else None}
        if self.tipo == "wst" and self.pref:
            self.curva.extra["emDolar"] = round((self.a * self.r - self.b) * p, 2)
            self.curva.extra["precoRef"] = round(self.pref, 2)


# ---------------------------------------------------------------------------------------------------- API
Q_MERCADOS = "{ markets(request:{chainIds:[%d]}) { name address reserves { underlyingToken { symbol address } supplyInfo { apy { value } } borrowInfo { apy { value } } } } }"
Q_MERCADOS_CONFERIDA = "{ markets(request:{chainIds:[%d]}) { name address reserves { underlyingToken { symbol } supplyInfo { apy { value } } borrowInfo { apy { value } } } } }"
Q_EMODE = "{ markets(request:{chainIds:[%d]}) { address eModeCategories { id label maxLTV { value } liquidationThreshold { value } liquidationPenalty { value } } } }"
Q_HIST = '{ %s(request:{market:"%s", underlyingToken:"%s", window: LAST_YEAR, chainId: %d}) { date avgRate { value } } }'
SIMBOLOS = {"WETH": ["WETH"], "wstETH": ["wstETH", "WSTETH"], "USDC": ["USDC"]}
SERIES = [("sup:WETH", "supplyAPYHistory", "WETH"), ("bor:WETH", "borrowAPYHistory", "WETH"),
          ("sup:wstETH", "supplyAPYHistory", "wstETH"), ("sup:USDC", "supplyAPYHistory", "USDC"),
          ("bor:USDC", "borrowAPYHistory", "USDC")]


def _mercado(dados):
    ms = (dados or {}).get("markets") or []
    for m in ms:
        if str((m or {}).get("address", "")).lower() == POOL.lower():
            return m
    return next((m for m in ms if "Base" in str((m or {}).get("name", ""))), ms[0] if ms else None)


def ler_mercado(fonte, est, log, erros):
    """(taxas de agora {chave: taxa}, endereços {símbolo: endereço})."""
    try:
        dados = fonte.aave(Q_MERCADOS % CHAIN)
        com_endereco = True
    except ERROS as e:
        log(f"  looping: o GraphQL recusou o endereço dos tokens ({e}); usando a consulta conferida e os endereços fixos")
        erros.append(f"mercados com endereço: {e}")
        dados = fonte.aave(Q_MERCADOS_CONFERIDA % CHAIN)
        com_endereco = False
    m = _mercado(dados)
    if not m:
        raise rede.Erro("o GraphQL do Aave não trouxe o mercado da Base")
    if not est.get("formatoVisto"):
        log(f"  looping: formato do mercado: {rede.estrutura(m, 4)}")
    atual, ends = {}, dict(ENDERECOS)
    for r in m.get("reserves") or []:
        tok = (r or {}).get("underlyingToken") or {}
        sim = tok.get("symbol")
        nome = next((k for k, v in SIMBOLOS.items() if sim in v), None)
        if not nome:
            continue
        if com_endereco and isinstance(tok.get("address"), str) and tok["address"].startswith("0x"):
            ends[nome] = tok["address"]
        s = _apy((((r.get("supplyInfo") or {}).get("apy")) or {}).get("value"))
        b = _apy((((r.get("borrowInfo") or {}).get("apy")) or {}).get("value"))
        if s is not None:
            atual["sup:" + nome] = s
        if b is not None:
            atual["bor:" + nome] = b
    return atual, ends


def ler_historicos(fonte, ends, log, erros):
    serie = {}
    for chave, campo, nome in SERIES:
        try:
            dados = fonte.aave(Q_HIST % (campo, POOL, ends[nome], CHAIN))
            d = {}
            for x in dados.get(campo) or []:
                v = _apy(((x or {}).get("avgRate") or {}).get("value"))
                if v is not None and x.get("date"):
                    d[str(x["date"])[:10]] = v
            if d:
                serie[chave] = d
            else:
                erros.append(f"histórico {chave} vazio")
        except ERROS as e:
            erros.append(f"histórico {chave}: {e}")
            log(f"  looping: histórico {chave}: {e}")
    return serie


def ler_staking(fonte, log, erros):
    try:
        r = fonte.llama(f"/chart/{LIDO_LLAMA}") or {}
        d = {}
        for x in r.get("data") or []:
            v = _f((x or {}).get("apyBase"), _f((x or {}).get("apy")))
            if v is not None and x.get("timestamp"):
                d[str(x["timestamp"])[:10]] = v / 100
        return d
    except ERROS as e:
        erros.append(f"staking (DefiLlama): {e}")
        log(f"  looping: staking (DefiLlama): {e}; usando {pct_br(STAKING_PADRAO)} ao ano")
        return {}


def ler_parametros(fonte, rpc, ends, est, log, erros):
    """O limite de liquidação e o bônus de cada reserva (getReserveData no RPC) e o e-mode (GraphQL, não conferido)."""
    p = {k: dict(v) for k, v in PARAMS_PADRAO.items()}
    p["emode"] = dict(EMODE_PADRAO)
    fontes = {"reservas": "padrão", "emode": "padrão"}
    for nome, end in ends.items():
        try:
            r = rpc("eth_call", [{"to": POOL, "data": "0x35ea6a75" + end[2:].lower().rjust(64, "0")}, "latest"])
            c = config_reserva(r)
            if c:
                p[nome] = c
                fontes["reservas"] = "getReserveData"
        except ERROS as e:
            erros.append(f"getReserveData {nome}: {e}")
    try:
        m = _mercado(fonte.aave(Q_EMODE % CHAIN))
        for cat in (m or {}).get("eModeCategories") or []:
            rot = str(cat.get("label") or "").lower()
            if "eth" in rot and "stable" not in rot:
                lt = _apy(((cat.get("liquidationThreshold") or {}).get("value")))
                pen = _f(((cat.get("liquidationPenalty") or {}).get("value")))
                if lt and 0.5 < lt < 1:
                    p["emode"] = {"lt": lt, "bonus": (pen - 1 if pen and pen > 1 else pen) if pen else EMODE_PADRAO["bonus"],
                                  "ltv": _apy(((cat.get("maxLTV") or {}).get("value"))) or EMODE_PADRAO["ltv"],
                                  "nome": cat.get("label")}
                    fontes["emode"] = "GraphQL"
                    break
        if fontes["emode"] != "GraphQL":
            log(f"  looping: e-mode não achado no GraphQL ({rede.estrutura(m, 3)}); usando o padrão")
    except ERROS as e:
        log(f"  looping: e-mode pelo GraphQL: {e}; usando o padrão (90% / 93% / 1%)")
    p["fontes"] = fontes
    return p


def velas(cli, intervalo, ini, fim, erros):
    """[(t do fim da vela, fechamento, mínima)] do ether na Hyperliquid."""
    passo = HORA if intervalo == "1h" else DIA
    out = []
    try:
        for c in cli.velas("ETH", intervalo, ini, fim):
            fe, mi = _f(c.get("c")), _f(c.get("l"))
            if fe:
                out.append((int(c["t"]) + passo, fe, mi or fe))
    except ERROS as e:
        erros.append(f"velas {intervalo} do ether: {e}")
    return sorted(out)


def teste_no_passado(diarias, tx, params):
    out = {}
    if len(diarias) < 3:
        return out
    ini = diarias[0][0]
    for cfg in VERSOES:
        c = Conta(cfg, ini, params)
        ant = None
        for t, p, mi in diarias:
            c.passo(t, DIA if ant else 0, p, mi, tx)
            ant = t
        out[cfg[0]] = c.curva.resumo(de=dia_de(ini), ate=dia_de(diarias[-1][0]), aproximado=True,
                                     nota="Aproximado: juros do Aave e staking pela média de cada dia e o ether pelas velas "
                                          "de 1 dia (a liquidação confere a mínima do dia).")
    return out


def rodar(ctx):
    erros = []
    est = copy.deepcopy(ctx.est)
    agora, log, cli = int(ctx.agora), ctx.log, ctx.cli
    fonte = rede.fonte_de(ctx, "aave")
    fontes = {id(f): (f, getattr(f, "pedidos", 0)) for f in (fonte, rede.fonte_de(ctx, "llama"), rede.fonte_de(ctx, "rpc"))}
    try:
        # ---------------------------------------------------------------- taxas e parâmetros
        atual, ends = ler_mercado(fonte, est, log, erros)
        tc = est.get("taxas") or {}
        if not tc.get("serie") or agora - int(tc.get("em") or 0) >= TAXAS_REFAZER:
            serie = ler_historicos(fonte, ends, log, erros)
            stake = ler_staking(rede.fonte_de(ctx, "llama"), log, erros)
            if stake:
                serie["stake"] = stake
            velha = tc.get("serie") or {}
            for k, v in velha.items():  # o que falhou agora fica com o da rodada anterior
                serie.setdefault(k, v)
            tc = {"em": agora, "serie": serie}
            est["taxas"] = tc
        if not tc.get("serie"):
            raise rede.Erro("sem o histórico de juros do Aave: " + "; ".join(erros[:2]))
        stake_atual = None
        st = tc["serie"].get("stake") or {}
        if st:
            stake_atual = st[max(st)]
        atual = dict(atual, stake=stake_atual if stake_atual is not None else STAKING_PADRAO)
        tx = Taxas(tc["serie"], atual)
        params = est.get("params")
        if not params or agora - int(params.get("em") or 0) >= PARAMS_REFAZER:
            params = ler_parametros(fonte, rede.fonte_de(ctx, "rpc").rpc, ends, est, log, erros)
            params["em"] = agora
            est["params"] = params
        est["formatoVisto"] = True

        # ---------------------------------------------------------------- ao vivo (de hora em hora)
        fim = hora_de(agora - FOLGA_MS)
        vivo = est.setdefault("vivo", {})
        cursores = [int(v.get("t") or fim) for v in vivo.values()] + [fim]
        ini_vivo = max(min(cursores), fim - ALCANCE_MAX)
        horarias = velas(cli, "1h", ini_vivo - HORA, agora, erros)
        if not horarias:
            raise rede.Erro("sem as velas do ether: " + "; ".join(erros[-2:]))
        ev = Eventos(est.get("eventos"))
        for cfg in VERSOES:
            vid = cfg[0]
            try:
                c = Conta(cfg, fim, params, vivo.get(vid))
                if c.novo:
                    ult = [x for x in horarias if x[0] <= fim]
                    if ult:
                        t, p, mi = ult[-1]
                        c.passo(fim, 0, p, p, tx, ev)
                else:
                    for t, p, mi in horarias:
                        if c.t < t <= fim:
                            c.passo(t, t - c.t, p, mi, tx, ev)
                vivo[vid] = c.para_json()
            except Exception as e:  # noqa: BLE001
                erros.append(f"{vid} ao vivo: {e}")
                log(f"  looping: {vid} ao vivo: {e}")

        # ---------------------------------------------------------------- teste no passado (velas de 1 dia)
        hist = est.get("hist") or {}
        if not hist or agora - int(hist.get("em") or 0) >= HIST_REFAZER or hist.get("v") != VERSAO:
            diarias = [x for x in velas(cli, "1d", agora - (HIST_DIAS + 1) * DIA, agora, erros) if x[0] <= agora]
            res = teste_no_passado(diarias, tx, params)
            if res:
                hist = {"v": VERSAO, "em": agora, "versoes": res}
                est["hist"] = hist
                log(f"  looping: teste no passado refeito ({dia_de(diarias[0][0])} a {dia_de(diarias[-1][0])})")

        # ---------------------------------------------------------------- saída
        versoes = []
        for cfg in VERSOES:
            vid, nome, tipo, alav, defesa, risco, frase = cfg
            e = vivo.get(vid)
            versoes.append({"id": vid, "nome": nome, "frase": frase, "risco": risco, "alav": alav,
                            "grupo": {"wst": "wstETH × ETH", "eth": "ETH × USDC", "usdc": "Referência"}[tipo],
                            "aoVivo": Curva.de_json(e["curva"]).resumo() if e else None,
                            "historico": (hist.get("versoes") or {}).get(vid)})
        itens = [{"ativo": "wstETH", "deposito": atual.get("sup:wstETH"), "staking": atual.get("stake"),
                  "lt": params["emode"]["lt"], "bonus": params["emode"]["bonus"], "nota": "no e-mode do ether"},
                 {"ativo": "WETH", "deposito": atual.get("sup:WETH"), "emprestimo": atual.get("bor:WETH"),
                  "lt": params["WETH"]["lt"], "bonus": params["WETH"]["bonus"]},
                 {"ativo": "USDC", "deposito": atual.get("sup:USDC"), "emprestimo": atual.get("bor:USDC"),
                  "lt": params["USDC"]["lt"], "bonus": params["USDC"]["bonus"]}]
        est["eventos"] = ev.para_json()
        ctx.est.clear()
        ctx.est.update(est)
        return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": "wst3", "versoes": versoes,
                "eventos": est["eventos"], "itens": itens, "avisos": AVISOS,
                "config": {"frequencia": "a cada 6 h (de hora em hora pelas velas)", "rede": "Base", "protocolo": "Aave v3",
                           "pool": POOL, "alavMax": ALAV_MAX, "emode": params["emode"], "fontesParametros": params.get("fontes"),
                           "custos": {"troca": TAXA_TROCA, "deslize": DESLIZE, "relampago": TAXA_RELAMPAGO, "gas": GAS_US},
                           "stakingFonte": "DefiLlama (Lido)" if tc["serie"].get("stake") else "fixo"},
                "erros": erros}
    finally:
        for f, p0 in fontes.values():
            rede.somar_pedidos(ctx, f, p0)
