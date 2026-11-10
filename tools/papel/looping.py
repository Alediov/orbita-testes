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
  (`pref`): o que sobra é só o laço (staking contra juro), comparável com a régua "Só wstETH". Em dólar de verdade a
  conta subiria e cairia junto com o ether (quem começa com dólar compra ether); esse valor vai em `extra.emDolar` e o
  retorno e a pior queda em dólar em `extra.dolar`.
- **ETH × USDC**: deposita ether, toma dólar, compra mais ether: uma aposta alavancada na alta, com liquidação de
  verdade quando o ether cai. 1,5× e 2×, uma delas com defesa (desalavanca quando o fator de saúde cai a 1,3).
- **Só USDC**: depositar dólar sem laço, a régua (na Aave e, desde 09/11/2026, num cofre de USDC da Morpho e na
  Moonwell).

Simulação: juros compostos dos dois lados com a taxa diária do Aave (`supplyAPYHistory`/`borrowAPYHistory`, 365 dias);
o staking do wstETH pela taxa diária do Lido na DefiLlama; o ether pelas velas da Hyperliquid (1 h ao vivo, 1 dia no
teste no passado), com o fator de saúde = garantia × limite de liquidação ÷ dívida conferido pela MÍNIMA da vela;
liquidação pela regra do Aave v3 (metade da dívida, ou toda abaixo de 0,95, com o bônus do ativo para o liquidante),
em cascata enquanto o fator continuar abaixo de 1. Montar e desmontar: troca de 0,05% + deslize de 0,03% sobre o que é
trocado, empréstimo relâmpago de 0,05% sobre a dívida e o gás da Base.

**Revisão de 09/11/2026** (pedido do Alediov, depois de ver o teste no passado):

- **Por que wst1, wst3 e wst6 davam quase o mesmo no passado (+2,35%, +2,36%, +2,36% em ether)**: NÃO era defeito.
  As taxas já eram as de cada dia (o staking do Lido muda todo dia na DefiLlama, e o juro do ether também; refazendo a
  conta pelas curvas do looping.json real de 09/11/2026, o staking implícito andou entre 2,2% e 2,6% e o juro do ether
  entre 1,6% e 2,5% ao longo do ano). O que aconteceu: na média do ano o staking pagou só uns 0,14 ponto ao ano a mais
  que o juro do ether (e em 36% dos dias o juro passou o staking), então cada × a mais rendeu ~0,14% do dinheiro no
  ano, e montar custa ~0,13% do dinheiro por × a mais (troca 0,05% + deslize 0,03% + relâmpago 0,05%). Um empatou com o
  outro: o laço só ganhou da régua nos meses
  em que a diferença foi maior, e devolveu nos meses em que o juro do ether passou o staking. Hoje (09/11) a diferença
  é ~0,25 ponto e por isso o "rende agora" do 6× (3,26%) é maior que o do 1× (2,26%). Para ver isso de perto: a conta
  por dentro (`extra.porDentro`) e o empate (`extra.empate`).
- **Laço quando compensa** (`wstAuto3`, `wstAuto6`): começa no 1× (só wstETH) e monta o laço quando o ganho extra dele,
  (alavancagem − 1) × (staking + depósito do wstETH − juro do ether), passa de `AUTO_ENTRA` (0,5 ponto ao ano) na média
  dos últimos 7 dias, com o juro de hoje abaixo do staking; desmonta para 1× quando esse ganho, na média de 3 dias, cai
  abaixo de `AUTO_SAI` (0,1 ponto: a diferença sumiu) ou o juro do ether do dia passa o staking por `AUTO_DISPARA` (2
  pontos: disparou). Decide uma vez por dia (UTC), paga montar e desmontar (troca + deslize sobre o que muda, relâmpago
  sobre a dívida que muda, gás) e o evento leva o `motivo` ("compensa", "diferenca", "juro").
- **ETH 2× só na alta** (`eth2tend`): 2× (ETH × USDC) só com o ether acima da média de `MEDIA_DIAS` (50) dias de
  fechamentos (com menos dias, a dos que houver, mínimo `MEDIA_MIN`); abaixo, vende tudo, paga a dívida e deixa o
  dólar no depósito de USDC do Aave. Decide uma vez por dia pelo fechamento do dia anterior; motivo "alta" ou "queda".
- **Onde o dólar rende mais** (`morpho`, `moonwell`, réguas): o mesmo "Só USDC", num cofre grande de USDC da Morpho na
  Base (API GraphQL pública `blue-api.morpho.org`; reserva pela DefiLlama) e na Moonwell (pela DefiLlama, `/pools` e
  `/chart`). Os nomes dos campos foram escritos sem acesso às fontes: a 1ª rodada registra a estrutura no log. Fonte que
  falha: a versão fica com `semDados` (o motivo) e `aoVivo`/`historico` null; nunca derruba a forma.
- **Teste de estresse** (`estresse` em cada versão de laço): o juro em que o laço passa a perder, quantos dias de juro
  a 2× e 5× o de hoje apagam um ano de ganho, e no wstETH o efeito de um desvio de −2%, −5% e −6% do wstETH no mercado
  (como o stETH em 2022) no fator de saúde: o oráculo do Aave para o wstETH usa a taxa de câmbio do staking (wstETH →
  stETH, com o stETH = ether), não o preço de mercado; então um desvio NÃO liquida, mas quem precisar sair na hora
  vende com o desconto, e o desconto pesa alavancagem × desvio no patrimônio (6% × 6 = 36%).
- **Empate** (`extra.empate`): quanto custou montar e em quantos meses o ganho extra do laço sobre a régua paga isso,
  pelas taxas de agora; `jaPagou` pelo acumulado.
- **A conta por dentro** (`extra.porDentro`): staking, juro recebido, juro pago, troca, deslize, relâmpago, gás,
  liquidações, preço (o que sobra) e o resultado.
- **Janelas de 30 dias** (`historico.janelas`): contra a régua certa (as de ether contra "Só wstETH", o "Só wstETH"
  contra o ether parado, as de dólar contra o CDI).
"""
from __future__ import annotations

import bisect
import copy
import datetime as dt
import math

import rede
import conta as CT
from conta import CAPITAL, DIA, HORA, Curva, Eventos, dia_de, moeda_br, num_br, pct_br

try:
    import hl
    ERROS = (rede.Erro, hl.Erro)
except ImportError:  # pragma: no cover
    ERROS = (rede.Erro,)

NOME = "Looping"
VERSAO = 1
HIST_V = 3                # subir refaz o teste no passado (3: a regra nova do laço quando compensa, 09/11/2026)

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
DOLAR_REFAZER = 12 * HORA
POOL_LLAMA_REFAZER = 7 * DIA
ALCANCE_MAX = 195 * DIA   # as velas de 1 h só vão até ~200 dias atrás
FOLGA_MS = 5 * 60_000

# laço quando compensa (wstAuto*)
# Rodada real de 09/11/2026: com a regra de antes (0,5 ponto de ganho extra em 7 dias, sai abaixo de 0,1 em 3 dias) o
# wstAuto6 montou 14 vezes no ano e perdeu 13,5% em custos. Agora só monta se a diferença dos últimos 14 dias pagar a ida
# e a volta em `AUTO_PAGA_DIAS` dias, sai só quando a diferença fica negativa (7 dias) ou o juro dispara, e fica montado
# pelo menos `AUTO_FICA_DIAS` dias (menos no disparo).
AUTO_ENTRA = 0.005        # diferença staking − juro do ether (por × a mais, média de 14 dias) mínima para montar
AUTO_PAGA_DIAS = 60       # e o ganho extra desses dias precisa pagar montar + desmontar
AUTO_SAI = 0.0            # média de 7 dias abaixo disso: desmonta
AUTO_DISPARA = 0.02       # juro do ether do dia acima do staking por isso: desmonta já
AUTO_DIAS_ENTRA, AUTO_DIAS_SAI = 14, 7
AUTO_FICA_DIAS = 30
# ETH só na alta (eth2tend)
MEDIA_DIAS, MEDIA_MIN = 50, 20
# estresse
ESTRESSE_JURO = (2, 5)
ESTRESSE_DESVIO = (0.02, 0.05, 0.06)
ESTRESSE_QUEDA = (0.2, 0.4)
# janelas
JANELA_DIAS, JANELA_PASSO, JANELA_LISTA = 30, 7, 30

# (id, nome, tipo, alavancagem, defesa (fator de saúde) ou None, risco, frase)
VERSOES = [
    ("wst3", "wstETH 3×", "wst", 3, None, "baixo",
     "Deposita wstETH (ether em staking), toma ether emprestado e deposita de novo até 3× o dinheiro: ganha o staking "
     "3 vezes e paga o juro do ether 2 vezes."),
    ("wst6", "wstETH 6×", "wst", 6, None, "médio",
     "O mesmo laço até 6×: o ganho e o perigo (o juro do ether passar o staking) ficam maiores."),
    ("wstAuto3", "wstETH 3× quando compensa", "wst", 3, None, "baixo",
     "Fica só no wstETH e monta o laço de 3× quando o staking paga pelo menos 0,5 ponto ao ano a mais que o juro do "
     "ether (média de 7 dias); desmonta quando a diferença some ou o juro dispara."),
    ("wstAuto6", "wstETH 6× quando compensa", "wst", 6, None, "médio",
     "A mesma regra com o laço de 6×: monta e desmonta pela diferença entre o staking e o juro do ether."),
    ("eth15", "ETH 1,5×", "eth", 1.5, None, "alto",
     "Deposita ether, toma dólar emprestado e compra mais ether até 1,5×: aposta na alta, liquidada se o ether cair uns 60%."),
    ("eth2", "ETH 2×", "eth", 2, None, "alto",
     "O mesmo com 2×: liquidada se o ether cair uns 40%."),
    ("eth2def", "ETH 2× com defesa", "eth", 2, 1.3, "alto",
     "2×, mas quando o fator de saúde cai a 1,3 vende um pouco do ether e paga a dívida, voltando a 2×."),
    ("eth2tend", "ETH 2× só na alta", "eth", 2, None, "alto",
     "2× só com o ether acima da média de 50 dias; abaixo dela, vende tudo, paga a dívida e deixa o dólar rendendo no Aave."),
    ("wst1", "Só wstETH", "wst", 1, None, "baixo",
     "Régua do laço: só compra wstETH e deixa no Aave, sem empréstimo. Mostra quanto do laço é só o staking."),
    ("eth1", "Só ETH", "eth", 1, None, "alto",
     "Régua do ether × dólar: só compra ether e deixa no Aave, sem empréstimo. Mostra quanto das outras é só o ether."),
    ("usdc", "Só USDC", "usdc", 1, None, "baixo",
     "Só deposita os dólares no Aave e recebe o juro, sem laço: a régua das outras."),
    ("morpho", "Só USDC na Morpho", "usdc", 1, None, "baixo",
     "Deixa os dólares num cofre grande de USDC da Morpho, na mesma rede: a régua de onde o dólar parado rende mais."),
    ("moonwell", "Só USDC na Moonwell", "usdc", 1, None, "baixo",
     "Deixa os dólares no depósito de USDC da Moonwell, na mesma rede: outra régua do dólar parado."),
]
# o que cada versão nova tem a mais (as de antes não aparecem aqui)
OPCOES = {
    "wstAuto3": {"auto": True, "grupo": "Laço quando compensa"},
    "wstAuto6": {"auto": True, "grupo": "Laço quando compensa"},
    "eth2tend": {"tend": True},
    "morpho": {"taxa": "sup:morpho", "onde": "Morpho"},
    "moonwell": {"taxa": "sup:moonwell", "onde": "Moonwell"},
}
GRUPO = {"wst": "wstETH × ETH", "eth": "ETH × USDC"}
MOTIVO = {"compensa": "o laço passou a compensar", "diferenca": "a diferença sumiu", "juro": "o juro disparou",
          "alta": "o ether passou a média", "queda": "o ether caiu abaixo da média"}
FRASE = ("Deposita, toma emprestado contra o depósito e deposita de novo: multiplica o rendimento e o juro, e uma queda "
         "forte da garantia leva à liquidação.")
COMO_FUNCIONA = [
    "No Aave, um banco automático da rede Base, quem deposita recebe juro e pode tomar emprestado até uma parte do que "
    "depositou. O laço deposita, toma emprestado, troca e deposita de novo, até a alavancagem escolhida.",
    "No wstETH × ether, o depósito é ether em staking (rende uns 3% ao ano) e a dívida é em ether: o preço do ether "
    "não leva à liquidação. Sobra a diferença entre o staking e o juro do ether, multiplicada. Se o juro passar o "
    "staking, a conta perde dia a dia. Por isso estas versões são medidas em ether (convertido pelo preço do primeiro "
    "dia) e comparadas com a régua \"Só wstETH\", não com o CDI: em dólar, elas sobem e caem junto com o ether.",
    "O laço \"quando compensa\" só fica montado enquanto o staking paga pelo menos 0,5 ponto ao ano a mais que o juro "
    "do ether, multiplicado pela alavancagem; no resto do tempo fica no 1×. Montar e desmontar custam a troca, o "
    "deslize, o empréstimo relâmpago e o gás.",
    "No ether × dólar, a conta fica com mais ether do que o dinheiro dava: ganha mais na alta, perde mais na queda e, "
    "se o ether cair demais, o Aave vende parte do ether com multa (a liquidação). A versão com defesa vende um pouco "
    "antes disso; a \"só na alta\" só fica alavancada com o ether acima da média de 50 dias.",
    "O fator de saúde é garantia × limite ÷ dívida: abaixo de 1, liquidação. Juros do dia do próprio Aave, staking do "
    "Lido, troca de 0,05% + deslize, empréstimo relâmpago de 0,05% e o gás da Base já estão descontados.",
    "As réguas de dólar mostram onde o dólar parado rende mais na mesma rede: o depósito do Aave, um cofre de USDC da "
    "Morpho e o depósito da Moonwell (sem as recompensas em moedas dos próprios protocolos).",
]
AVISOS = [
    "O wstETH pode descolar do ether no mercado (como o stETH em 2022); o Aave usa a taxa do staking e não liquida por "
    "isso, mas quem precisar sair na hora vende com desconto (no 6×, um desconto de 6% leva uns 36% do patrimônio).",
    "O juro do Aave muda a cada bloco; o papel usa a média de cada dia, que esconde picos de horas em que pegar "
    "emprestado fica muito caro.",
    "Falha de oráculo, erro de contrato ou um ataque ao protocolo podem levar o dinheiro todo; nenhum teste no papel mede "
    "isso. Os cofres da Morpho dependem também de quem cuida deles (os mercados em que emprestam).",
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


def grupo_de(cfg):
    vid, tipo, alav = cfg[0], cfg[2], cfg[3]
    return OPCOES.get(vid, {}).get("grupo") or ("Referência" if alav == 1 else GRUPO[tipo])


def chave_taxa(vid):
    """A chave da taxa do depósito de dólar da versão ("sup:USDC" no Aave; "sup:morpho"…)."""
    return OPCOES.get(vid, {}).get("taxa", "sup:USDC")


# ---------------------------------------------------------------------------------------------------- dados
class Taxas:
    """As taxas ao ano por dia (UTC): `serie[chave] = {dia: taxa}` e a de agora `atual[chave]`. Chaves: "sup:WETH",
    "bor:WETH", "sup:wstETH", "sup:USDC", "bor:USDC", "stake" (o staking do Lido), "sup:morpho" e "sup:moonwell"."""

    def __init__(self, serie=None, atual=None):
        self.serie = {k: dict(v) for k, v in (serie or {}).items()}
        self.atual = dict(atual or {})
        self._dias = {k: sorted(v) for k, v in self.serie.items()}

    def tem(self, chave):
        return bool(self.serie.get(chave)) or self.atual.get(chave) is not None

    def taxa(self, chave, t):
        d = dia_utc(t)
        s = self.serie.get(chave) or {}
        if d in s:
            return s[d]
        dias = self._dias.get(chave) or []
        if dias and d > dias[-1] and self.atual.get(chave) is not None:
            return self.atual[chave]
        i = bisect.bisect_right(dias, d) - 1
        if i >= 0:
            return s[dias[i]]
        if dias:
            return s[dias[0]]
        v = self.atual.get(chave)
        return v if v is not None else (STAKING_PADRAO if chave == "stake" else 0.0)

    def diferenca(self, t):
        """Staking + depósito do wstETH − juro do ether, ao ano, no dia de `t`."""
        return self.taxa("stake", t) + self.taxa("sup:wstETH", t) - self.taxa("bor:WETH", t)


def _cresce(taxa, ms):
    return (1 + max(-0.99, taxa)) ** (ms / ANO_MS)


def media_movel(diarias, t, dias=MEDIA_DIAS, minimo=MEDIA_MIN):
    """(fechamento do último dia fechado até `t`, média dos últimos `dias` fechamentos) pelas velas de 1 dia
    [(t do fim, fechamento, mínima)]; (None, None) sem `minimo` dias."""
    if not diarias:
        return None, None
    ts = [x[0] for x in diarias]
    i = bisect.bisect_right(ts, t)
    fech = [x[1] for x in diarias[max(0, i - dias):i]]
    if len(fech) < minimo:
        return (fech[-1] if fech else None), None
    return fech[-1], sum(fech) / len(fech)


# ---------------------------------------------------------------------------------------------------- conta
ACC = ("ganho", "custo", "defesas", "stake", "rec", "pag", "troca", "desl", "rel", "gas", "liq", "regua",
       "montagens", "desmontagens")


class Conta:
    """Uma versão: `a` = depósito (unidades da garantia), `b` = dívida (unidades da dívida); no wstETH, `r` = o wstETH em
    ether (cresce com o staking; começa em 1); `u` = dólar no depósito de USDC (só no ETH 2× só na alta, quando fora);
    `L` = a alavancagem em que a conta está montada (no laço quando compensa, 1 ou a da versão; no só na alta, 0 = fora)."""

    def __init__(self, cfg, inicio, params, estado=None):
        self.id, self.nome, self.tipo, self.alav, self.defesa, self.risco, self.frase = cfg
        assert self.alav <= ALAV_MAX
        self.opc = OPCOES.get(self.id, {})
        self.auto, self.tend = bool(self.opc.get("auto")), bool(self.opc.get("tend"))
        self.chave_usdc = chave_taxa(self.id)
        e = estado or {}
        self.curva = Curva.de_json(e.get("curva")) or Curva(inicio=inicio)
        self.a, self.b, self.r = float(e.get("a", 0.0)), float(e.get("b", 0.0)), float(e.get("r", 1.0))
        self.u = float(e.get("u", 0.0))
        self.L = e.get("L", 1 if self.auto else self.alav)
        self.dec = e.get("dec")
        self.montouEm = e.get("montouEm")
        self.montada = bool(e.get("montada"))
        self.t = int(e.get("t") or inicio)
        self.p = e.get("p")  # último preço do ether
        self.pref = e.get("pref")  # wstETH: o preço do ether quando a conta começou (a conta é medida em ether)
        acc = e.get("acc") or {}
        self.acc = {k: float(acc.get(k, 0.0)) for k in ACC}
        # contas de antes de 09/11/2026: não separavam staking, juro recebido e os custos (estimados pelo que havia)
        self.estimado = bool(e.get("estimado")) or (bool(estado) and "troca" not in acc)
        if bool(estado) and "troca" not in acc:
            self.acc["troca"] = self.curva.taxas
            self.acc["rec"] = self.acc["ganho"]
            self.acc["pag"] = self.acc["custo"]
            self.acc["montagens"] = 1.0 if self.montada and self.alav > 1 else 0.0
        self.dol = dict(e.get("dol") or {})
        self.params = params
        self.novo = not estado

    def para_json(self):
        return {"curva": self.curva.para_json(), "a": self.a, "b": self.b, "r": self.r, "u": self.u, "L": self.L, "montouEm": self.montouEm,
                "dec": self.dec, "montada": self.montada, "t": self.t, "p": self.p, "pref": self.pref, "acc": self.acc,
                "estimado": self.estimado, "dol": self.dol}

    def _ev(self, ev, t, tipo, texto, motivo=None):
        if ev is not None:
            ev.add(t, tipo, texto, self.id)
            if motivo:
                ev.lista[-1]["motivo"] = motivo

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
        return self.garantia_us(p) - self.divida_us(p) + (self.u if self.tipo == "eth" else 0.0)

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

    def _custos(self, troca_us, relampago_us, gas=True):
        tr, de, re_ = troca_us * TAXA_TROCA, troca_us * DESLIZE, relampago_us * TAXA_RELAMPAGO
        g = GAS_US if gas else 0.0
        self.acc["troca"] += tr
        self.acc["desl"] += de
        self.acc["rel"] += re_
        self.acc["gas"] += g
        return tr + de + re_ + g

    # ------------------------------------------------------------------ montar
    def montar(self, t, p, ev, tx=None, tend=None):
        E = self.curva.ultimo if self.curva.ultimo > 0 else CAPITAL
        if self.auto and tx is not None:
            self.L = self.alav if self._compensa(t, tx) else 1
        if self.tend:
            fech, media = tend or (None, None)
            self.L = self.alav if (media is not None and fech is not None and fech > media) else 0
        L = self.L
        if self.tipo == "usdc" or (self.tend and L == 0):
            custo = self._custos(0, 0)
            if self.tipo == "usdc":
                self.a, self.b = E - custo, 0.0
            else:
                self.a, self.b, self.u = 0.0, 0.0, E - custo
        else:
            if self.tipo == "wst" and not self.pref:
                self.pref = p
            custo = self._custos(L * E, (L - 1) * E)
            if self.tipo == "wst":
                self.a, self.b = (L * E - custo) / (self.r * p), (L - 1) * E / p
            else:
                self.a, self.b = (L * E - custo) / p, (L - 1) * E
            if L > 1:
                self.acc["montagens"] += 1
        self.curva.operou(custo, 1)
        self.montada = True
        if self.tipo == "usdc":
            onde = self.opc.get("onde", "Aave")
            self._ev(ev, t, "abriu", f"Depositou {moeda_br(self.a)} em USDC na {onde}." if onde != "Aave"
                     else f"Depositou {moeda_br(self.a)} em USDC no Aave.")
        elif self.tend and L == 0:
            self._ev(ev, t, "abriu", f"O ether está abaixo da média de {MEDIA_DIAS} dias (ou ainda sem a média): deixou "
                                     f"{moeda_br(self.u)} em USDC no Aave, esperando a alta.", "queda")
        elif L == 1:
            moeda = "wstETH" if self.tipo == "wst" else "ether"
            extra = (" O laço espera o staking pagar mais que o juro do ether." if self.auto else "")
            self._ev(ev, t, "abriu", f"Comprou {moeda_br(self.garantia_us(p))} em {moeda} e depositou no Aave, sem "
                                     f"empréstimo (custou {moeda_br(custo)}).{extra}")
        else:
            moeda = "wstETH" if self.tipo == "wst" else "ether"
            divida = f"{num_br(self.b, 4)} ETH" if self.tipo == "wst" else moeda_br(self.b)
            hf = self.saude(p)
            self._ev(ev, t, "abriu", f"Montou o laço de {num_br(L, 1)}×: {moeda_br(self.garantia_us(p))} em {moeda} de garantia e "
                                     f"{divida} de dívida (fator de saúde {num_br(hf, 2) if hf else '—'}; custou {moeda_br(custo)}).",
                     "compensa" if self.auto else ("alta" if self.tend else None))
        self.dec = dia_utc(t)

    def _rebalancear(self, t, p, L_novo, motivo, texto, ev):
        """Muda a alavancagem montada para `L_novo` (0 = tudo em USDC, só no ETH só na alta), pagando a troca e o
        deslize sobre o que muda na garantia, o relâmpago sobre a dívida que muda e o gás."""
        E = self.valor(p)
        if E <= 0:
            return
        C, D = self.garantia_us(p), self.divida_us(p)
        C1, D1 = L_novo * E, max(0.0, L_novo - 1) * E
        custo = self._custos(abs(C1 - C), abs(D1 - D))
        E1 = E - custo
        C1, D1 = L_novo * E1, max(0.0, L_novo - 1) * E1
        if self.tipo == "wst":
            self.a, self.b = C1 / (self.r * self.pref), D1 / self.pref
        else:
            self.a, self.b = C1 / p, D1
            self.u = E1 if L_novo == 0 else 0.0
        subiu = L_novo > self.L
        self.L = L_novo
        self.acc["montagens" if subiu else "desmontagens"] += 1
        self.curva.operou(custo, 1)
        self._ev(ev, t, "reequilibrou", f"{texto} (custou {moeda_br(custo)}).", motivo)

    # ------------------------------------------------------------------ as regras novas
    def _ganho_extra(self, t, tx, dias):
        """(alavancagem − 1) × a diferença média staking − juro dos últimos `dias` dias até `t`, ao ano."""
        difs = [tx.diferenca(t - i * DIA) for i in range(dias)]
        return (self.alav - 1) * sum(difs) / len(difs)

    def _custo_ida_volta(self):
        """Montar e desmontar, em fração do dinheiro: (troca + deslize + relâmpago) × (alavancagem − 1), duas vezes."""
        por_x = TAXA_TROCA + DESLIZE + TAXA_RELAMPAGO
        return 2 * por_x * (self.alav - 1)

    def _compensa(self, t, tx):
        g = self._ganho_extra(t, tx, AUTO_DIAS_ENTRA)
        return (g / max(1e-9, self.alav - 1) >= AUTO_ENTRA
                and g * AUTO_PAGA_DIAS / 365 >= self._custo_ida_volta()
                and tx.taxa("bor:WETH", t) < tx.taxa("stake", t) + tx.taxa("sup:wstETH", t))

    def _decidir_auto(self, t, p, tx, ev):
        if self.L <= 1:
            if self._compensa(t, tx):
                g = self._ganho_extra(t, tx, AUTO_DIAS_ENTRA)
                self.montouEm = t
                self._rebalancear(t, p, self.alav, "compensa",
                                  f"Montou o laço de {num_br(self.alav, 0)}×: o staking passou a pagar "
                                  f"{num_br(g / (self.alav - 1) * 100, 2)} ponto ao ano a mais que o juro do ether (média de "
                                  f"{AUTO_DIAS_ENTRA} dias), {num_br(g * 100, 2)} pontos a mais no laço", ev)
            return
        s = tx.taxa("stake", t) + tx.taxa("sup:wstETH", t)
        b = tx.taxa("bor:WETH", t)
        montou = getattr(self, "montouEm", None)
        cedo = montou is not None and t - montou < AUTO_FICA_DIAS * DIA
        if b >= s + AUTO_DISPARA:
            self._rebalancear(t, p, 1, "juro", f"Desmontou para 1×: o juro do ether disparou a {pct_br(b, 2)} ao ano, "
                                               f"contra {pct_br(s, 2)} do staking", ev)
        elif not cedo and self._ganho_extra(t, tx, AUTO_DIAS_SAI) < AUTO_SAI:
            self._rebalancear(t, p, 1, "diferenca", f"Desmontou para 1×: a diferença entre o staking e o juro do ether "
                                                    f"sumiu (média de {AUTO_DIAS_SAI} dias)", ev)

    def _decidir_tend(self, t, p, tend, ev):
        fech, media = tend or (None, None)
        if media is None or fech is None:
            return
        alvo = self.alav if fech > media else 0
        if alvo == self.L:
            return
        if alvo:
            self._rebalancear(t, p, alvo, "alta", f"O ether fechou a {moeda_br(fech, 0)}, acima da média de "
                                                  f"{MEDIA_DIAS} dias ({moeda_br(media, 0)}): montou o 2× de novo", ev)
        else:
            self._rebalancear(t, p, 0, "queda", f"O ether fechou a {moeda_br(fech, 0)}, abaixo da média de "
                                                f"{MEDIA_DIAS} dias ({moeda_br(media, 0)}): vendeu tudo, pagou a dívida e "
                                                f"deixou o dólar no Aave", ev)

    # ------------------------------------------------------------------ passo
    def passo(self, t, dt_ms, p, minima, tx, ev=None, tend=None):
        """O período que termina em `t` (`dt_ms` de duração), com o ether fechando em `p` e a mínima `minima`. `tend` =
        (fechamento do dia anterior, média de 50 dias), só para o ETH só na alta."""
        self.t = t
        if p:
            self.p = p
        p = self.p
        if not p:
            return
        if not self.montada:
            self.montar(t, p, ev, tx, tend)
            self.curva.marcar(t, self.valor(p))
            self._dolar(p)
            self._extra(p, tx, t)
            return
        E0 = self.valor(p)
        # juros e staking do período
        if self.tipo == "wst":
            a0, r0, b0 = self.a, self.r, self.b
            self.a *= _cresce(tx.taxa("sup:wstETH", t), dt_ms)
            self.r *= _cresce(tx.taxa("stake", t), dt_ms)
            self.b *= _cresce(tx.taxa("bor:WETH", t), dt_ms)
            self.acc["ganho"] += (self.a * self.r - a0 * r0) * self.pref
            self.acc["custo"] += (self.b - b0) * self.pref
            self.acc["stake"] += a0 * (self.r - r0) * self.pref
            self.acc["rec"] += (self.a - a0) * self.r * self.pref
            self.acc["pag"] += (self.b - b0) * self.pref
            self.acc["regua"] += max(0.0, E0) * (_cresce(tx.taxa("stake", t) + tx.taxa("sup:wstETH", t), dt_ms) - 1)
        elif self.tipo == "eth":
            a0, b0, u0 = self.a, self.b, self.u
            self.a *= _cresce(tx.taxa("sup:WETH", t), dt_ms)
            self.b *= _cresce(tx.taxa("bor:USDC", t), dt_ms)
            self.u *= _cresce(tx.taxa("sup:USDC", t), dt_ms)
            self.acc["ganho"] += (self.a - a0) * p + (self.u - u0)
            self.acc["custo"] += self.b - b0
            self.acc["rec"] += (self.a - a0) * p + (self.u - u0)
            self.acc["pag"] += self.b - b0
            self.acc["regua"] += max(0.0, E0) * (_cresce(tx.taxa("sup:WETH", t), dt_ms) - 1)
        else:
            a0 = self.a
            self.a *= _cresce(tx.taxa(self.chave_usdc, t), dt_ms)
            self.acc["ganho"] += self.a - a0
            self.acc["rec"] += self.a - a0
        # liquidação (pela mínima, em cascata)
        self._liquidar(t, minima or p, ev)
        # defesa (pelo fechamento)
        hf = self.saude(p)
        if self.defesa and hf is not None and hf < self.defesa and self.valor(p) > 0:
            self._desalavancar(t, p, hf, ev)
        # as regras novas: uma decisão por dia (UTC)
        hoje = dia_utc(t)
        if (self.auto or self.tend) and hoje != self.dec and self.valor(p) > 0:
            self.dec = hoje
            if self.auto:
                self._decidir_auto(t, p, tx, ev)
            else:
                self._decidir_tend(t, p, tend, ev)
        self.curva.marcar(t, self.valor(minima or p) if self.tipo == "eth" else self.valor(p))
        self.curva.marcar(t, self.valor(p))
        self._dolar(p)
        self._extra(p, tx, t)

    def _dolar(self, p):
        """wstETH: o patrimônio em dólar de verdade (com o ether de agora): pico e pior queda."""
        if self.tipo != "wst" or not self.pref:
            return
        v = (self.a * self.r - self.b) * p
        pico = max(float(self.dol.get("pico") or CAPITAL), v)
        self.dol = {"pico": pico, "queda": max(float(self.dol.get("queda") or 0.0), 1 - v / pico if pico > 0 else 0.0)}

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
            self.acc["liq"] += perda
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
        custo = self._custos(venda, 0)
        # vende `venda` em ether e paga a dívida em dólar
        self.a -= venda / p
        self.b -= venda - custo
        self.curva.operou(custo, 1)
        self.acc["defesas"] += 1
        self._ev(ev, t, "reequilibrou", f"Defesa: o fator de saúde caiu a {num_br(hf, 2)}; vendeu {moeda_br(venda)} de ether "
                                        f"e pagou a dívida, voltando a {num_br(self.alav, 1)}× (custou {moeda_br(custo)}).", "defesa")

    # ------------------------------------------------------------------ números para o app
    def taxa_regua(self, tx, t):
        """O que a régua do mesmo tipo rende ao ano agora (só o carrego, sem o preço)."""
        if self.tipo == "wst":
            return tx.taxa("stake", t) + tx.taxa("sup:wstETH", t)
        if self.tipo == "eth":
            return tx.taxa("sup:WETH", t)
        return tx.taxa(self.chave_usdc, t)

    def rende_ano(self, p, tx, t):
        E = self.valor(p)
        if E <= 0:
            return None
        C = self.garantia_us(p)
        if self.tipo == "wst":
            return (C * (tx.taxa("sup:wstETH", t) + tx.taxa("stake", t)) - self.divida_us(p) * tx.taxa("bor:WETH", t)) / E
        if self.tipo == "eth":
            return (C * tx.taxa("sup:WETH", t) - self.b * tx.taxa("bor:USDC", t) + self.u * tx.taxa("sup:USDC", t)) / E
        return tx.taxa(self.chave_usdc, t)

    def por_dentro(self, p):
        """De onde veio o resultado (US$; ver FORMATO.md): resultado = staking + juroRecebido − juroPago − custos −
        liquidações + preço (o preço é o que sobra: o ether na conta ETH × USDC; ~0 no wstETH, medido em ether)."""
        a = self.acc
        resultado = self.valor(p) - CAPITAL
        custos = a["troca"] + a["desl"] + a["rel"] + a["gas"]
        preco = resultado - (a["stake"] + a["rec"] - a["pag"] - custos - a["liq"])
        r = lambda x: round(x, 4) + 0.0  # noqa: E731  (+ 0.0: sem "-0.0" no JSON)
        out = {"staking": r(a["stake"]), "juroRecebido": r(a["rec"]), "juroPago": r(a["pag"]), "troca": r(a["troca"]),
               "deslize": r(a["desl"]), "relampago": r(a["rel"]), "gas": r(a["gas"]), "custos": r(custos),
               "liquidacoes": r(a["liq"]), "preco": r(preco), "resultado": r(resultado),
               "montagens": int(a["montagens"]), "desmontagens": int(a["desmontagens"])}
        if self.estimado:
            out["estimado"] = True
        return out

    def empate(self, p, tx, t, rende):
        """Montar custou `custo` a mais que a régua (que também compra a moeda uma vez; `custoTotal` = tudo) e o laço rende `ganhoAno` (US$ ao ano) a mais que a régua do mesmo tipo pelas taxas de
        agora: paga em `meses` (None se não paga pelo juro); `sobra` = o que o laço já ganhou além da régua, pagos os
        custos (≥ 0: `jaPagou`). Só nas versões de laço (alavancagem > 1)."""
        if self.alav <= 1 or self.tipo == "usdc":
            return None
        a = self.acc
        E = self.valor(p)
        total = a["troca"] + a["desl"] + a["rel"] + a["gas"]
        # o que a régua também paga (comprar a moeda uma vez) não conta contra o laço
        custo = max(0.0, total - (CAPITAL * (TAXA_TROCA + DESLIZE) + GAS_US))
        ganho = (rende - self.taxa_regua(tx, t)) * E if rende is not None and E > 0 else None
        if self.L <= 1 or (self.tend and self.L == 0):
            ganho_txt = 0.0  # no 1× ou fora, o laço não está ganhando nada a mais agora
        else:
            ganho_txt = ganho
        meses = custo / (ganho_txt / 12) if ganho_txt and ganho_txt > 0 else None
        sobra = (a["stake"] + a["rec"] - a["pag"]) - a["regua"] - custo - a["liq"]
        if self.tipo == "eth":
            sobra = None  # no ether × dólar o ganho do laço é o preço, não o juro
        return {"custo": round(custo, 4), "custoTotal": round(total, 4), "ganhoAno": round(ganho_txt, 4) if ganho_txt is not None else None,
                "meses": round(meses, 1) if meses is not None else None,
                "sobra": round(sobra, 4) if sobra is not None else None,
                "jaPagou": (sobra >= 0) if sobra is not None else None,
                "pelo": "juro" if self.tipo == "wst" else "preco"}

    def _extra(self, p, tx, t):
        E = self.valor(p)
        C = self.garantia_us(p)
        hf = self.saude(p)
        liq = self.rende_ano(p, tx, t)
        if self.tipo == "wst":
            g, d = "wstETH", "ETH"
        elif self.tipo == "eth":
            g, d = "ETH", "USDC"
        else:
            g, d = "USDC", None
        pl = self.preco_liquidacao()
        self.curva.extra = {"hf": round(hf, 4) if hf is not None else None, "alavAgora": round(C / E, 3) if E > 0 else None,
                            "rendeAno": round(liq, 5) if liq is not None else None, "ganhoJuros": round(self.acc["ganho"], 4),
                            "custoJuros": round(self.acc["custo"], 4), "defesas": int(self.acc["defesas"]),
                            "garantia": g, "divida": d, "precoLiquidacao": round(pl, 2) if pl else None,
                            "porDentro": self.por_dentro(p)}
        emp = self.empate(p, tx, t, liq)
        if emp:
            self.curva.extra["empate"] = emp
        if self.auto or self.tend:
            self.curva.extra["montadaEm"] = self.L
            self.curva.extra["laco"] = ("montado" if self.L > 1 else "1×") if self.auto else ("alta" if self.L else "fora")
            if self.tend and self.u:
                self.curva.extra["emUsdc"] = round(self.u, 2)
        if self.tipo == "usdc":
            self.curva.extra["onde"] = self.opc.get("onde", "Aave")
        if self.tipo == "wst" and self.pref:
            em_dolar = (self.a * self.r - self.b) * p
            self.curva.extra["emDolar"] = round(em_dolar, 2)
            self.curva.extra["precoRef"] = round(self.pref, 2)
            self.curva.extra["dolar"] = {"retorno": round(em_dolar / CAPITAL - 1, 6),
                                         "piorQueda": round(float(self.dol.get("queda") or 0.0), 6),
                                         "ether": round(p / self.pref - 1, 6)}


# ---------------------------------------------------------------------------------------------------- estresse
def estresse(cfg, conta, tx, t, params, p):
    """O teste de estresse de uma versão de laço pelas taxas de agora (ver o começo do arquivo e o FORMATO.md). Conta
    pelo estado de agora quando a conta está montada no laço; senão (laço quando compensa no 1×, só na alta fora), pela
    conta teórica da versão montada."""
    vid, _, tipo, L, _, _, _ = cfg
    if L <= 1 or tipo == "usdc":
        return None
    montada = conta is not None and conta.montada and conta.b > 1e-9 and conta.valor(p) > 0
    if tipo == "wst":
        s = tx.taxa("stake", t) + tx.taxa("sup:wstETH", t)
        b = tx.taxa("bor:WETH", t)
        lt = params["emode"]["lt"]
        if montada:
            E = conta.valor(p)
            C, D = conta.garantia_us(p) / E, conta.divida_us(p) / E
            hf = conta.saude(p)
        else:
            C, D = L, L - 1
            hf = C * lt / D
        rende = C * s - D * b
        juro_alto = []
        for k in ESTRESSE_JURO:
            r_k = C * s - D * k * b
            dias = 365 * rende / -r_k if rende > 0 and r_k < 0 else None
            juro_alto.append({"vezes": k, "juro": round(k * b, 5), "rendeAno": round(r_k, 5),
                              "diasApagam": round(dias, 1) if dias is not None else None})
        desvio = []
        for x in ESTRESSE_DESVIO:
            hm = hf * (1 - x)
            desvio.append({"desvio": x, "hfAave": round(hf, 4), "hfSeMercado": round(hm, 4), "liquidariaSeMercado": hm < 1,
                           "perdaSaindo": round(C * x, 4)})
        return {"tipo": "wst", "alav": L, "base": "agora" if montada else "teorica", "juroAgora": round(b, 5),
                "stakingAgora": round(s, 5), "rendeAno": round(rende, 5),
                "juroPerde": round(C * s / D, 5), "juroRegua": round(s, 5),
                "juroAlto": juro_alto, "desvio": desvio,
                "desvioLiquida": round(1 - 1 / hf, 4) if hf and hf > 1 else 0.0,
                "oraculo": "câmbio do staking"}
    # ETH × USDC
    supw, bu = tx.taxa("sup:WETH", t), tx.taxa("bor:USDC", t)
    lt = params["WETH"]["lt"]
    if montada:
        E = conta.valor(p)
        C, D = conta.garantia_us(p) / E, conta.divida_us(p) / E
        hf = conta.saude(p)
        pl = conta.preco_liquidacao()
        queda_liq = 1 - pl / p if pl else None
    else:
        C, D = L, L - 1
        hf = C * lt / D
        queda_liq = 1 - D / (C * lt)
    rende = C * supw - D * bu
    juro_alto = []
    for k in ESTRESSE_JURO:
        r_k = C * supw - D * k * bu
        dias = 365 * rende / -r_k if rende > 0 and r_k < 0 else None
        juro_alto.append({"vezes": k, "juro": round(k * bu, 5), "rendeAno": round(r_k, 5),
                          "diasApagam": round(dias, 1) if dias is not None else None})
    quedas = []
    for x in ESTRESSE_QUEDA:
        hq = hf * (1 - x)
        quedas.append({"queda": x, "hf": round(hq, 4), "liquida": hq < 1, "perda": round(C * x, 4)})
    return {"tipo": "eth", "alav": L, "base": "agora" if montada else "teorica", "juroAgora": round(bu, 5),
            "depositoAgora": round(supw, 5), "rendeAno": round(rende, 5),
            "juroPerde": round(C * supw / D, 5), "juroAlto": juro_alto, "quedas": quedas,
            "quedaLiquida": round(queda_liq, 4) if queda_liq is not None else None, "hfAgora": round(hf, 4),
            "oraculo": "preço de mercado (Chainlink)"}


# ---------------------------------------------------------------------------------------------------- janelas
def janelas(conta, contra, cdi=None, cdi_ano=0.149, regua=None, dias=JANELA_DIAS, passo=JANELA_PASSO):
    """Janelas de `dias` dias começando a cada `passo` dias na série diária da conta (o teste no passado), cada uma
    comparada com a referência do MESMO período: `contra` = "cdi" (a série do BC dia a dia, como em conta.metricas),
    "ether" (o ether parado: 0%) ou o id de uma régua (a série `regua`, {dia: valor}). None com menos de uma janela."""
    if not conta or not conta.get("serie"):
        return None
    pts = {dt.date.fromisoformat(d): float(v) for d, v in conta["serie"]}
    ini, fim = min(pts), max(pts)
    if (fim - ini).days < dias:
        return None

    def preencher(p):
        out, v, d = {}, None, ini
        while d <= fim:
            v = p.get(d, v)
            out[d] = v
            d += dt.timedelta(days=1)
        return out

    valores = preencher(pts)
    ref_val = preencher({dt.date.fromisoformat(d): float(v) for d, v in (regua or {}).items()}) if contra not in ("cdi", "ether") else None
    if contra not in ("cdi", "ether") and not any(v for v in (ref_val or {}).values()):
        return None
    fator = {}
    if contra == "cdi":
        cdi = cdi or {}
        ultimo, primeiro = (max(cdi), min(cdi)) if cdi else ("", "")
        diaria = (1 + cdi_ano) ** (1 / 252) - 1
        d = ini
        while d <= fim:
            fator[d] = 1 + CT._cdi_do_dia(cdi, d, primeiro, ultimo, diaria)
            d += dt.timedelta(days=1)
    lista = []
    a = ini
    while a + dt.timedelta(days=dias) <= fim:
        b = a + dt.timedelta(days=dias)
        va, vb = valores[a], valores[b]
        ret = vb / va - 1 if va and va > 0 else -1.0
        if contra == "cdi":
            ind, x = 1.0, a
            while x < b:
                ind *= fator[x]
                x += dt.timedelta(days=1)
            rr = ind - 1
        elif contra == "ether":
            rr = 0.0
        else:
            ra, rb = ref_val.get(a), ref_val.get(b)
            if not ra or not rb:
                a += dt.timedelta(days=passo)
                continue
            rr = rb / ra - 1
        lista.append([a.isoformat(), round(ret, 6), round(rr, 6)])
        a += dt.timedelta(days=passo)
    if not lista:
        return None
    rets = sorted(x[1] for x in lista)
    n = len(rets)
    mediana = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    vence = sum(1 for x in lista if (1 + x[1]) > (1 + x[2]) + 1e-12)
    pior = min(lista, key=lambda x: x[1])
    melhor = max(lista, key=lambda x: x[1])
    nomes = {"cdi": "CDI", "ether": "o ether parado", "wst1": "Só wstETH", "eth1": "Só ETH"}
    out = {"dias": dias, "passo": passo, "n": n, "contra": {"id": contra, "nome": nomes.get(contra, contra)},
           "vence": vence, "mediana": round(mediana, 6),
           "pior": {"de": pior[0], "retorno": pior[1], "ref": pior[2]},
           "melhor": {"de": melhor[0], "retorno": melhor[1], "ref": melhor[2]},
           "lista": lista[-JANELA_LISTA:]}
    if contra == "cdi":  # o mesmo nome dos robôs, para quem já sabe ler
        out["venceCdi"] = vence
        out["pior"]["cdi"], out["melhor"]["cdi"] = pior[2], melhor[2]
    return out


def contra_de(cfg):
    """A referência certa de cada versão: as de ether (wstETH) contra a régua em ether, as de dólar contra o CDI."""
    vid, tipo, alav = cfg[0], cfg[2], cfg[3]
    if tipo == "wst":
        return "ether" if vid == "wst1" else "wst1"
    return "cdi"


# ---------------------------------------------------------------------------------------------------- API
Q_MERCADOS = "{ markets(request:{chainIds:[%d]}) { name address reserves { underlyingToken { symbol address } supplyInfo { apy { value } } borrowInfo { apy { value } } } } }"
Q_MERCADOS_CONFERIDA = "{ markets(request:{chainIds:[%d]}) { name address reserves { underlyingToken { symbol } supplyInfo { apy { value } } borrowInfo { apy { value } } } } }"
Q_EMODE = "{ markets(request:{chainIds:[%d]}) { address eModeCategories { id label maxLTV { value } liquidationThreshold { value } liquidationPenalty { value } } } }"
Q_HIST = '{ %s(request:{market:"%s", underlyingToken:"%s", window: LAST_YEAR, chainId: %d}) { date avgRate { value } } }'
SIMBOLOS = {"WETH": ["WETH"], "wstETH": ["wstETH", "WSTETH"], "USDC": ["USDC"]}
SERIES = [("sup:WETH", "supplyAPYHistory", "WETH"), ("bor:WETH", "borrowAPYHistory", "WETH"),
          ("sup:wstETH", "supplyAPYHistory", "wstETH"), ("sup:USDC", "supplyAPYHistory", "USDC"),
          ("bor:USDC", "borrowAPYHistory", "USDC")]
# Morpho (blue-api, GraphQL público). NÃO conferidos daqui (a rede da sessão não alcança): os nomes vêm da documentação
# pública da API; a 1ª rodada registra a estrutura no log. Os campos do histórico são tentados em ordem.
Q_MORPHO_COFRES = ('{ vaults(first: 10, orderBy: TotalAssetsUsd, orderDirection: Desc, where: { chainId_in: [%d], '
                   'assetSymbol_in: ["USDC"] }) { items { address name symbol state { totalAssetsUsd %s } } } }')
MORPHO_CAMPOS_AGORA = ["netApyWithoutRewards netApy apy fee", "netApy apy fee", "apy"]
Q_MORPHO_HIST = ('{ vaultByAddress(address: "%s", chainId: %d) { address historicalState { %s(options: '
                 '{ startTimestamp: %d, endTimestamp: %d, interval: DAY }) { x y } } } }')
MORPHO_CAMPOS_HIST = ["netApyWithoutRewards", "netApy", "apy"]
MORPHO_TVL_MIN = 1_000_000


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
        return _chart_llama(fonte, LIDO_LLAMA)
    except ERROS as e:
        erros.append(f"staking (DefiLlama): {e}")
        log(f"  looping: staking (DefiLlama): {e}; usando {pct_br(STAKING_PADRAO)} ao ano")
        return {}


def _chart_llama(fonte, pool):
    """O histórico diário de um pool da DefiLlama (`/chart/<pool>`): {dia: taxa ao ano (fração)}, pelo `apyBase` (sem
    as recompensas em moedas do protocolo) ou, sem ele, o `apy`."""
    r = fonte.llama(f"/chart/{pool}") or {}
    d = {}
    for x in r.get("data") or []:
        v = _f((x or {}).get("apyBase"), _f((x or {}).get("apy")))
        if v is not None and x.get("timestamp"):
            d[str(x["timestamp"])[:10]] = v / 100
    return d


def _pool_llama(fonte, projeto, est_d, log, agora):
    """O pool de USDC na Base de um projeto da DefiLlama com mais TVL (`/pools`, guardado por 7 dias)."""
    g = est_d.get("llama") or {}
    if g.get("pool") and agora - int(g.get("em") or 0) < POOL_LLAMA_REFAZER:
        return g
    r = fonte.llama("/pools") or {}
    if not est_d.get("llamaVisto"):
        amostra = next((x for x in r.get("data") or [] if isinstance(x, dict)), None)
        log(f"  looping: formato da DefiLlama /pools: {rede.estrutura(amostra, 2)}")
        est_d["llamaVisto"] = True
    cands = [x for x in r.get("data") or [] if isinstance(x, dict) and str(x.get("chain", "")).lower() == "base"
             and str(x.get("project", "")).lower().startswith(projeto) and str(x.get("symbol", "")).upper() == "USDC"
             and _f(x.get("tvlUsd"), 0) > 0]
    if not cands:
        raise rede.Erro(f"DefiLlama: nenhum pool de USDC na Base do projeto {projeto}")
    m = max(cands, key=lambda x: _f(x.get("tvlUsd"), 0))
    g = {"pool": m.get("pool"), "projeto": m.get("project"), "tvl": _f(m.get("tvlUsd")),
         "apyBase": _f(m.get("apyBase")), "apyReward": _f(m.get("apyReward")), "em": agora}
    est_d["llama"] = g
    return g


def ler_morpho(ctx, est_d, log, erros, agora):
    """O cofre de USDC da Morpho na Base com mais dinheiro (TVL ≥ US$ 1 mi): (série {dia: taxa}, taxa de agora, info).
    Pela blue-api; se ela falhar, pela DefiLlama (projeto "morpho")."""
    fonte = rede.fonte_de(ctx, "morpho")
    try:
        cofres, campos = None, None
        ultimo_erro = None
        for campos in MORPHO_CAMPOS_AGORA:
            try:
                cofres = fonte.morpho(Q_MORPHO_COFRES % (CHAIN, campos))
                break
            except ERROS as e:
                ultimo_erro = e
                if getattr(e, "status", None) or "rede em" in str(e) or "sem resposta" in str(e):
                    break  # fora do ar: não adianta tentar outros campos
        if cofres is None:
            raise ultimo_erro or rede.Erro("Morpho: sem resposta")
        itens = (((cofres or {}).get("vaults") or {}).get("items")) or []
        if not est_d.get("formatoVisto"):
            log(f"  looping: formato da Morpho (cofres, campos '{campos}'): {rede.estrutura(itens[:1], 4)}")
        ok = [x for x in itens if isinstance(x, dict) and _f(((x.get("state") or {}).get("totalAssetsUsd")), 0) >= MORPHO_TVL_MIN]
        if not ok:
            raise rede.Erro("Morpho: nenhum cofre de USDC na Base com US$ 1 mi ou mais")
        c = max(ok, key=lambda x: _f(x["state"].get("totalAssetsUsd"), 0))
        st = c.get("state") or {}
        agora_tx = next((_apy(st.get(k)) for k in ("netApyWithoutRewards", "netApy", "apy") if _apy(st.get(k)) is not None), None)
        serie, campo_h = {}, None
        ini, fim = int((agora - (HIST_DIAS + 2) * DIA) / 1000), int(agora / 1000)
        for campo_h in MORPHO_CAMPOS_HIST:
            try:
                h = fonte.morpho(Q_MORPHO_HIST % (c["address"], CHAIN, campo_h, ini, fim))
            except ERROS:
                continue
            pts = ((((h or {}).get("vaultByAddress") or {}).get("historicalState") or {}).get(campo_h)) or []
            if not est_d.get("formatoVisto"):
                log(f"  looping: formato do histórico da Morpho ({campo_h}): {rede.estrutura(pts[:2], 3)}")
            for x in pts:
                v, ts = _apy((x or {}).get("y")), _f((x or {}).get("x"))
                if v is not None and ts:
                    serie[dia_utc(ts * 1000 if ts < 1e12 else ts)] = v
            if serie:
                break
        est_d["formatoVisto"] = True
        info = {"fonte": "Morpho (blue-api)", "nome": c.get("name"), "endereco": c.get("address"),
                "tvl": _f(st.get("totalAssetsUsd")), "taxa": agora_tx, "comRecompensas": _apy(st.get("netApy")),
                "comissao": _f(st.get("fee")), "campoHistorico": campo_h if serie else None}
        if agora_tx is None and serie:
            agora_tx = serie[max(serie)]
            info["taxa"] = agora_tx
        if agora_tx is None:
            raise rede.Erro("Morpho: o cofre veio sem taxa")
        return serie, agora_tx, info
    except ERROS as e:
        erros.append(f"Morpho (blue-api): {e}")
        log(f"  looping: Morpho (blue-api): {e}; tentando a DefiLlama")
    llama = rede.fonte_de(ctx, "llama")
    g = _pool_llama(llama, "morpho", est_d, log, agora)
    serie = _chart_llama(llama, g["pool"])
    tx = (g.get("apyBase") / 100) if g.get("apyBase") is not None else (serie[max(serie)] if serie else None)
    if tx is None:
        raise rede.Erro("DefiLlama: o pool da Morpho veio sem taxa")
    return serie, tx, {"fonte": "DefiLlama (Morpho)", "nome": g.get("projeto"), "tvl": g.get("tvl"), "taxa": tx,
                       "recompensa": (g.get("apyReward") or 0) / 100 if g.get("apyReward") else None}


def ler_moonwell(ctx, est_d, log, erros, agora):
    """O depósito de USDC da Moonwell na Base, pela DefiLlama (o pool de USDC do projeto "moonwell" com mais TVL)."""
    llama = rede.fonte_de(ctx, "llama")
    g = _pool_llama(llama, "moonwell", est_d, log, agora)
    serie = _chart_llama(llama, g["pool"])
    tx = (g.get("apyBase") / 100) if g.get("apyBase") is not None else (serie[max(serie)] if serie else None)
    if tx is None:
        raise rede.Erro("DefiLlama: o pool da Moonwell veio sem taxa")
    return serie, tx, {"fonte": "DefiLlama (Moonwell)", "nome": g.get("projeto"), "tvl": g.get("tvl"), "taxa": tx,
                       "recompensa": (g.get("apyReward") or 0) / 100 if g.get("apyReward") else None}


def ler_dolar(ctx, est, log, erros, agora):
    """Morpho e Moonwell (a cada 12 h; na falha, fica o da leitura anterior e `motivo` diz o porquê)."""
    d = est.setdefault("dolar", {})
    fm = rede.fonte_de(ctx, "morpho")
    antes = getattr(fm, "pedidos", 0)
    for nome, ler in (("morpho", ler_morpho), ("moonwell", ler_moonwell)):
        g = d.setdefault(nome, {})
        if g.get("serie") is not None and g.get("taxa") is not None and agora - int(g.get("em") or 0) < DOLAR_REFAZER:
            continue
        try:
            serie, tx, info = ler(ctx, g, log, erros, agora)
            g.update({"serie": serie or g.get("serie") or {}, "taxa": tx, "info": info, "em": agora, "motivo": None})
        except ERROS as e:
            erros.append(f"{nome}: {e}")
            log(f"  looping: {nome}: {e}")
            g["motivo"] = str(e)[:200]
            g["em"] = agora
        except (TypeError, ValueError, KeyError, AttributeError) as e:  # formato inesperado: nunca derruba a forma
            erros.append(f"{nome}: formato inesperado ({type(e).__name__}: {e})")
            log(f"  looping: {nome}: formato inesperado ({e})")
            g["motivo"] = f"formato inesperado da fonte ({type(e).__name__})"
            g["em"] = agora
    if fm is not rede.fonte_de(ctx, "aave"):  # o mesmo Cliente das outras fontes já é somado no fim da rodada
        rede.somar_pedidos(ctx, fm, antes)
    return d


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


def sem_dados_de(cfg, tx, dolar):
    """O motivo de uma versão não poder rodar (só as réguas de fora do Aave: Morpho e Moonwell sem taxa)."""
    ch = chave_taxa(cfg[0])
    if ch == "sup:USDC" or tx.tem(ch):
        return None
    nome = OPCOES[cfg[0]]["onde"]
    m = ((dolar or {}).get(cfg[0]) or {}).get("motivo")
    return f"Sem a taxa da {nome}: {m}" if m else f"Sem a taxa da {nome} ainda."


def teste_no_passado(diarias, tx, params, inicio=None, versoes=None):
    """`diarias` pode começar antes de `inicio` (os dias a mais só servem à média de 50 dias do só na alta)."""
    out = {}
    janela = [x for x in diarias if inicio is None or x[0] >= inicio]
    if len(janela) < 3:
        return out
    ini = janela[0][0]
    for cfg in versoes or VERSOES:
        c = Conta(cfg, ini, params)
        ant = None
        for t, p, mi in janela:
            tend = media_movel(diarias, t - 1) if c.tend else None
            c.passo(t, DIA if ant else 0, p, mi, tx, tend=tend)
            ant = t
        nota = ("Aproximado: juros do Aave e staking pela média de cada dia e o ether pelas velas de 1 dia (a liquidação "
                "confere a mínima do dia).")
        if c.tipo == "usdc" and c.chave_usdc != "sup:USDC":
            nota = f"Aproximado: a taxa de cada dia da {c.opc['onde']}, sem as recompensas em moedas do protocolo."
        out[cfg[0]] = c.curva.resumo(de=dia_de(ini), ate=dia_de(janela[-1][0]), aproximado=True, nota=nota)
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
        # onde o dólar rende mais: Morpho e Moonwell (nunca derrubam a forma)
        dolar = ler_dolar(ctx, est, log, erros, agora)
        serie_tx = dict(tc["serie"])
        for nome in ("morpho", "moonwell"):
            g = dolar.get(nome) or {}
            if g.get("serie"):
                serie_tx["sup:" + nome] = g["serie"]
            if g.get("taxa") is not None:
                atual["sup:" + nome] = g["taxa"]
        tx = Taxas(serie_tx, atual)
        params = est.get("params")
        if not params or agora - int(params.get("em") or 0) >= PARAMS_REFAZER:
            params = ler_parametros(fonte, rede.fonte_de(ctx, "rpc").rpc, ends, est, log, erros)
            params["em"] = agora
            est["params"] = params
        est["formatoVisto"] = True

        # ---------------------------------------------------------------- velas de 1 dia (média de 50 dias e o passado)
        diarias = [x for x in velas(cli, "1d", agora - (HIST_DIAS + 1 + MEDIA_DIAS + 5) * DIA, agora, erros) if x[0] <= agora]

        # ---------------------------------------------------------------- ao vivo (de hora em hora)
        fim = hora_de(agora - FOLGA_MS)
        vivo = est.setdefault("vivo", {})
        cursores = [int(v.get("t") or fim) for v in vivo.values()] + [fim]
        ini_vivo = max(min(cursores), fim - ALCANCE_MAX)
        horarias = velas(cli, "1h", ini_vivo - HORA, agora, erros)
        if not horarias:
            raise rede.Erro("sem as velas do ether: " + "; ".join(erros[-2:]))
        ev = Eventos(est.get("eventos"))
        sem_dados = {}
        for cfg in VERSOES:
            vid = cfg[0]
            motivo = sem_dados_de(cfg, tx, dolar)
            if motivo:
                sem_dados[vid] = motivo
                if vid not in vivo:
                    continue
            try:
                c = Conta(cfg, fim, params, vivo.get(vid))
                if c.novo:
                    ult = [x for x in horarias if x[0] <= fim]
                    if ult:
                        t, p, mi = ult[-1]
                        c.passo(fim, 0, p, p, tx, ev, tend=media_movel(diarias, fim) if c.tend else None)
                else:
                    for t, p, mi in horarias:
                        if c.t < t <= fim:
                            c.passo(t, t - c.t, p, mi, tx, ev, tend=media_movel(diarias, t) if c.tend else None)
                vivo[vid] = c.para_json()
            except Exception as e:  # noqa: BLE001
                erros.append(f"{vid} ao vivo: {e}")
                log(f"  looping: {vid} ao vivo: {e}")

        # ---------------------------------------------------------------- teste no passado (velas de 1 dia)
        hist = est.get("hist") or {}
        if not hist or agora - int(hist.get("em") or 0) >= HIST_REFAZER or hist.get("v") != HIST_V:
            inicio = agora - (HIST_DIAS + 1) * DIA
            res = teste_no_passado(diarias, tx, params, inicio=inicio,
                                   versoes=[c for c in VERSOES if not sem_dados_de(c, tx, dolar)])
            if res:
                hist = {"v": HIST_V, "em": agora, "versoes": res}
                est["hist"] = hist
                jan = [x for x in diarias if x[0] >= inicio]
                log(f"  looping: teste no passado refeito ({dia_de(jan[0][0])} a {dia_de(jan[-1][0])})")
                # a explicação do 1×/3×/6× parecidos (ver o começo do arquivo): a diferença média do ano
                difs = [tx.diferenca(t) for t, _, _ in jan]
                if difs:
                    log(f"  looping: staking − juro do ether no ano: média {pct_br(sum(difs) / len(difs), 2)} ao ano "
                        f"(de {pct_br(min(difs), 2)} a {pct_br(max(difs), 2)}); montar custa ~"
                        f"{pct_br(TAXA_TROCA + DESLIZE + TAXA_RELAMPAGO, 2)} do dinheiro por × a mais")

        # ---------------------------------------------------------------- saída
        cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}
        cdi_ano = CT.cdi_ano_da_serie(cdi, 0.149)
        hv = hist.get("versoes") or {}
        versoes = []
        for cfg in VERSOES:
            vid, nome, tipo, alav, defesa, risco, frase = cfg
            e = vivo.get(vid)
            h = hv.get(vid)
            if h is not None:
                h = dict(h)
                contra = contra_de(cfg)
                try:
                    h["janelas"] = janelas(h, contra, cdi, cdi_ano, regua=dict((hv.get(contra) or {}).get("serie") or []))
                except (TypeError, ValueError, ZeroDivisionError, OverflowError, KeyError):
                    h["janelas"] = None
            v = {"id": vid, "nome": nome, "frase": frase, "risco": risco, "alav": alav, "grupo": grupo_de(cfg),
                 "medida": "ether" if tipo == "wst" else "dolar", "contra": contra_de(cfg),
                 "aoVivo": Curva.de_json(e["curva"]).resumo() if e else None, "historico": h}
            if tipo == "usdc":
                v["onde"] = OPCOES.get(vid, {}).get("onde", "Aave")
            if sem_dados.get(vid) and not e:
                v["semDados"] = sem_dados[vid]
            try:
                c = Conta(cfg, fim, params, e) if e else None
                pe = (c.p if c else None) or horarias[-1][1]
                es = estresse(cfg, c, tx, fim, params, pe)
                if es:
                    v["estresse"] = es
            except (TypeError, ValueError, ZeroDivisionError, KeyError) as x:
                erros.append(f"{vid} estresse: {x}")
            versoes.append(v)
        itens = [{"ativo": "wstETH", "deposito": atual.get("sup:wstETH"), "staking": atual.get("stake"),
                  "lt": params["emode"]["lt"], "bonus": params["emode"]["bonus"], "nota": "no e-mode do ether"},
                 {"ativo": "WETH", "deposito": atual.get("sup:WETH"), "emprestimo": atual.get("bor:WETH"),
                  "lt": params["WETH"]["lt"], "bonus": params["WETH"]["bonus"]},
                 {"ativo": "USDC", "deposito": atual.get("sup:USDC"), "emprestimo": atual.get("bor:USDC"),
                  "lt": params["USDC"]["lt"], "bonus": params["USDC"]["bonus"]}]
        # onde o dólar rende mais (agora e a média de 30 e 365 dias de cada um)
        onde = []
        for vid, nome_o, ch in (("usdc", "Aave", "sup:USDC"), ("morpho", "Morpho", "sup:morpho"), ("moonwell", "Moonwell", "sup:moonwell")):
            s = serie_tx.get(ch) or {}
            dias = sorted(s)
            med = lambda n: round(sum(s[d] for d in dias[-n:]) / len(dias[-n:]), 5) if dias else None  # noqa: E731
            g = (dolar.get(vid) or {}) if vid != "usdc" else {}
            info = g.get("info") or {}
            onde.append({"id": vid, "nome": nome_o, "agora": atual.get(ch), "media30": med(30), "media365": med(365),
                         "fonte": info.get("fonte") or ("Aave (GraphQL)" if vid == "usdc" else None),
                         "cofre": info.get("nome") if vid == "morpho" else None, "tvl": info.get("tvl"),
                         "recompensa": info.get("recompensa"), "comRecompensas": info.get("comRecompensas"),
                         "semDados": sem_dados.get(vid)})
        est["eventos"] = ev.para_json()
        ctx.est.clear()
        ctx.est.update(est)
        return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": "wst3", "versoes": versoes,
                "eventos": est["eventos"], "itens": itens, "avisos": AVISOS, "dolar": onde,
                "config": {"frequencia": "a cada 6 h (de hora em hora pelas velas)", "rede": "Base", "protocolo": "Aave v3",
                           "pool": POOL, "alavMax": ALAV_MAX, "emode": params["emode"], "fontesParametros": params.get("fontes"),
                           "custos": {"troca": TAXA_TROCA, "deslize": DESLIZE, "relampago": TAXA_RELAMPAGO, "gas": GAS_US},
                           "stakingFonte": "DefiLlama (Lido)" if tc["serie"].get("stake") else "fixo",
                           "auto": {"entra": AUTO_ENTRA, "sai": AUTO_SAI, "dispara": AUTO_DISPARA,
                                    "diasEntra": AUTO_DIAS_ENTRA, "diasSai": AUTO_DIAS_SAI,
                                    "pagaDias": AUTO_PAGA_DIAS, "ficaDias": AUTO_FICA_DIAS},
                           "tendencia": {"dias": MEDIA_DIAS, "minimo": MEDIA_MIN},
                           "estresse": {"juro": list(ESTRESSE_JURO), "desvio": list(ESTRESSE_DESVIO), "queda": list(ESTRESSE_QUEDA)},
                           "janelas": {"dias": JANELA_DIAS, "passo": JANELA_PASSO}},
                "erros": erros}
    finally:
        for f, p0 in fontes.values():
            rede.somar_pedidos(ctx, f, p0)
