"""Memecoins do pump.fun (Solana) como OBSERVATÓRIO, NO PAPEL (plano: docs/plano-testes-mercado-2.md, seção 6; formato:
tools/papel/FORMATO.md). Nenhuma carteira, nenhuma ordem, nenhuma chave: só fontes públicas e gratuitas.

O papel não consegue imitar quem compra no mesmo bloco do lançamento (os robôs de quem lança), e os golpes acontecem em
segundos. Por isso esta forma é um observatório honesto, sem viés de sobrevivência: "de N lançamentos, quantos
dobraram, quantos morreram, quantos foram golpe, e quanto cada regra simples teria dado". A conta de cada regra existe
(para o Placar), mas o aviso é que o real tende a ser pior.

Como funciona ("amostra de 24 h atrás"; job próprio, `memes.yml`, 2 vezes por dia):
1. **Ouvir**: o websocket do PumpPortal (`subscribeNewToken`, grátis) por até `OUVIR_S` s; guarda uma amostra SORTEADA
   de `AMOSTRA` lançamentos (todos têm a mesma chance, inclusive os que vão morrer) com o preço da curva logo depois da
   compra do criador (`vSolInBondingCurve` ÷ `vTokensInBondingCurve`) e o tamanho dessa compra (`initialBuy`). Logo
   depois, o RugCheck de cada um (os riscos "danger" do resumo).
2. **24 h depois**: a DexScreener (até 30 tokens por pedido) diz quais tiveram negociações, os pares (a curva do pump.fun
   e, se graduou, a PumpSwap) e o preço de agora; para os que negociaram, as velas de minuto do GeckoTerminal (`currency=
   token`: o preço em SOL; uma chamada por par, com o freio de `rede.py`; as primeiras `VELAS` minutos).
3. **As regras**: entrada de US$ 10 por token (a conta de US$ 1.000 dividida em 100 apostas). Na curva, a compra e a
   venda saem da conta da própria curva (reservas virtuais de 30 SOL e 1,073 bi de tokens: k = vSol × vTokens; dado o
   preço, vSol = √(preço × k)), então o deslize da nossa compra é exato; taxa de `TAXA_CURVA` por lado (a tabela do
   pump.fun muda com o valor de mercado: conferir) e `REDE_SOL` SOL de rede por operação. Depois da graduação (PumpSwap),
   taxa `TAXA_AMM` + deslize `DESLIZE_AMM`. Saída: dobrou → vende; −50% → vende; 30 min → vende (dentro de uma vela, a
   pior hipótese: o −50% antes do dobro). Token sem negociações depois do lançamento = entrou e só conseguiu sair na
   curva vazia (perde as taxas e o deslize).
4. **Contagens**: dobrou (máxima ≥ 2× o preço do lançamento nas primeiras ~16 h), 10×, graduou (passou de `P_GRAD` ou tem
   par na PumpSwap), golpe (queda de mais de 90% em até 5 min, na 1ª hora), morreu (sem negociações depois do 1º minuto
   ou valendo menos de 10% do lançamento em ~24 h), criador comprou muito (≥ 10% do total na criação), RugCheck "alto".

Nomes e símbolos dos tokens NÃO são guardados nem mostrados (qualquer um escolhe o nome, inclusive ofensivos): só o
endereço encurtado.

Amostras conferidas (Teste de alcance, 03/11/2026): o PumpPortal manda os lançamentos (21 em 2 min) "com as reservas
virtuais da curva e o tamanho da compra do criador"; DexScreener com `dexId: pumpfun`; GeckoTerminal com velas de minuto
de um pool pump.fun de 1 min; RugCheck `/report/summary`. NÃO conferidos (a 1ª rodada de verdade registra no log): os
nomes exatos dos campos (`mint`, `vSolInBondingCurve`, `vTokensInBondingCurve`, `initialBuy`, `marketCapSol`, `txType`;
`pairAddress`, `dexId`, `priceNative`, `liquidity`; `ohlcv_list`; `risks[].level`) e a tabela de taxas do pump.fun.
"""
from __future__ import annotations

import copy
import datetime as dt
import math
import random

import rede
from conta import CAPITAL, DIA, HORA, Curva, Eventos, dia_de, moeda_br

try:
    import hl
    ERROS = (rede.Erro, hl.Erro)
except ImportError:  # pragma: no cover
    ERROS = (rede.Erro,)

NOME = "Memecoins"
# 2 (09/11/2026): a 1ª rodada real mostrou que o PumpPortal manda também lançamentos de outras plataformas (a curva
# delas é outra: um deles saiu "28.904 vezes" por erro de unidade) e que a DexScreener não lista boa parte dos tokens
# pequenos (25 de 32 viraram "sem negócios"); a amostra agora é só do pump.fun, quem falta na DexScreener é procurado no
# GeckoTerminal e o que nenhum dos dois conhece fica "sem dados" (fora das apostas). Recomeça do zero.
VERSAO = 2

MIN = 60_000
OUVIR_S = 180
OUVIR_MAX = 400
AMOSTRA = 24
CADA_AMOSTRA = 10 * HORA          # uma amostra nova se a última tem 10 h ou mais (o job roda 2 vezes por dia)
ESPERA = 24 * HORA                # a análise de uma amostra, 24 h depois
ANALISES_POR_RODADA = 3
DESISTIR = 72 * HORA              # sem a DexScreener por 3 dias, a amostra é descartada (com aviso)
VELAS = 1000                      # minutos de velas por par (~16,7 h; o máximo de um pedido do GeckoTerminal)
APOSTA = 10.0                     # US$ por token
K_CURVA = 30.0 * 1_073_000_000    # reservas virtuais iniciais do pump.fun: 30 SOL × 1,073 bi de tokens
OFERTA = 1_000_000_000            # tokens de cada memecoin do pump.fun
P_GRAD = 115.0 ** 2 / K_CURVA     # SOL por token quando a curva junta ~85 SOL de verdade (vSol ≈ 115): a graduação
P_60 = 60.0 / OFERTA              # valor de mercado de 60 SOL (a regra "momento")
TAXA_CURVA = 0.0125               # por lado na curva (a tabela do pump.fun varia com o valor de mercado: conferir)
TAXA_AMM, DESLIZE_AMM = 0.0025, 0.01
REDE_SOL = 0.001                  # rede + prioridade por operação, em SOL (estimativa; a medida vai no config)
SAIDA_ALTA, SAIDA_BAIXA, SAIDA_MIN = 2.0, 0.5, 30
CRIADOR_GRANDE = 0.10
MAX_TOKENS = 3000                 # o resumo de cada token analisado (para as contagens), os mais novos
MAX_ITENS = 40
SOL_PADRAO = 150.0
X_ABSURDO = 1e5                   # máxima ÷ lançamento acima disso = erro de unidade (outra moeda de cotação): fora
DEX_GECKO = {"pump-fun": "pumpfun", "pumpfun": "pumpfun"}

# (id, nome, entrada, filtro RugCheck, saída, risco, frase)
VERSOES = [
    ("min1", "1º minuto", "min1", False, "regras", "alto",
     "Compra US$ 10 de cada lançamento da amostra no 1º minuto; vende quando dobra, quando cai 50% ou depois de 30 min."),
    ("min5", "5º minuto", "min5", False, "regras", "alto",
     "A mesma coisa, mas compra no 5º minuto (os que já morreram no começo ficam de fora)."),
    ("momento", "Momento (60 SOL)", "momento", False, "regras", "alto",
     "Só compra quando o valor de mercado chega a 60 SOL (mais ou menos o dobro do lançamento): aposta em quem já subiu."),
    ("graduacao", "Na graduação", "graduacao", False, "regras", "alto",
     "Só compra os que se formam (a curva enche e o token vai para a PumpSwap), no momento da graduação."),
    ("min1rc", "1º minuto + RugCheck", "min1", True, "regras", "alto",
     "O 1º minuto, mas só nos tokens sem risco alto no RugCheck logo depois do lançamento."),
    ("segura", "1º minuto e segura", "min1", False, "segura", "alto",
     "Referência: compra no 1º minuto e só vende cerca de 24 h depois. Mostra o que acontece com a maioria."),
]
FRASE = ("Observatório das moedas novas do pump.fun: de cada lote de lançamentos, quantas dobram, quantas morrem, quantas "
         "são golpe, e quanto cada regra simples teria dado.")
COMO_FUNCIONA = [
    "Qualquer pessoa cria uma memecoin no pump.fun em segundos; são uns 15 mil lançamentos por dia na Solana. O preço "
    "segue uma curva: cada compra deixa o próximo mais caro. Se a curva enche, o token se forma e passa a ser negociado "
    "numa corretora (a graduação).",
    "Duas vezes por dia o papel ouve os lançamentos por 3 minutos e sorteia uma amostra de 24, todos com a mesma chance, "
    "inclusive os que vão morrer. 24 horas depois, olha o que aconteceu com cada um e simula as regras com US$ 10 por "
    "token.",
    "As regras compram no 1º ou no 5º minuto, quando o token já dobrou ou na graduação, e vendem quando dobra, quando cai "
    "50% ou depois de 30 minutos. A taxa do pump.fun, a da rede e o deslize da própria compra estão descontados.",
    "É um observatório, não uma estratégia: o papel não compra no mesmo segundo do lançamento como os robôs, então o "
    "real tende a ser pior do que estes números.",
]
AVISOS = [
    "Robôs compram no mesmo bloco do lançamento e vendem em cima de quem chega depois: o papel entra pelo preço do minuto, "
    "como se não houvesse essa disputa.",
    "Em minutos de euforia a fila de transações da Solana atrasa compras e vendas; o papel executa sempre no preço da "
    "vela.",
    "Alguns tokens fora do pump.fun não deixam vender; aqui todos são da curva do pump.fun, mas golpes de outros tipos "
    "existem.",
    "Num token de US$ 2 mil de valor, uma compra de US$ 10 já mexe no preço: a conta da curva desconta isso, mas a dos "
    "outros compradores ao mesmo tempo não.",
    "O resultado é de 24 h atrás (a amostra de agora só é analisada amanhã).",
    "Os nomes dos tokens não aparecem: qualquer um escolhe o nome, inclusive ofensivo ou enganoso.",
]


def _f(x, padrao=None):
    try:
        v = float(x)
        return v if math.isfinite(v) else padrao
    except (TypeError, ValueError):
        return padrao


def curto(mint):
    m = str(mint or "")
    return f"{m[:4]}…{m[-4:]}" if len(m) > 10 else m


# ---------------------------------------------------------------------------------------------------- a curva
def comprar_curva(sol, p):
    """Tokens recebidos com `sol` (já sem a taxa) na curva com o preço `p` (SOL por token)."""
    vS = math.sqrt(p * K_CURVA)
    vT = K_CURVA / vS
    return vT - K_CURVA / (vS + sol)


def vender_curva(q, p):
    """SOL recebido (sem a taxa) vendendo `q` tokens na curva com o preço `p`."""
    vS = math.sqrt(p * K_CURVA)
    vT = K_CURVA / vS
    return vS - K_CURVA / (vT + q)


def entrar(sol, p, graduado):
    """(tokens, sol gasto) de uma compra de `sol` (com a taxa e a rede) pelo preço `p`."""
    liquido = max(0.0, sol - REDE_SOL)
    if graduado:
        return liquido * (1 - TAXA_AMM) / (p * (1 + DESLIZE_AMM)), sol
    return comprar_curva(liquido * (1 - TAXA_CURVA), p), sol


def sair(q, p, graduado):
    """SOL líquido vendendo `q` tokens pelo preço `p` (com a taxa e a rede)."""
    if q <= 0 or p <= 0:
        return -REDE_SOL
    if graduado:
        bruto = q * p * (1 - DESLIZE_AMM) * (1 - TAXA_AMM)
    else:
        bruto = vender_curva(q, p) * (1 - TAXA_CURVA)
    return bruto - REDE_SOL


# ---------------------------------------------------------------------------------------------------- velas e regras
def juntar_velas(listas):
    """[(t ms, abre, máx., mín., fecha, volume)] em ordem, sem repetir o minuto (a curva vale até a graduação)."""
    por_t = {}
    for lst in listas:
        for v in lst:
            por_t.setdefault(v[0], v)
    return [por_t[k] for k in sorted(por_t)]


def preco_em(velas, t, p0):
    """O fechamento da última vela até `t` (sem vela, o preço do lançamento)."""
    p = p0
    for v in velas:
        if v[0] > t:
            break
        p = v[4]
    return p


def entrada(versao_entrada, tok, velas):
    """(t, preço) da entrada da regra ou None."""
    t0, p0 = tok["t"], tok["p0"]
    if versao_entrada in ("min1", "min5"):
        m = 1 if versao_entrada == "min1" else 5
        t = t0 + m * MIN
        return t, preco_em(velas, t, p0)
    alvo = P_60 if versao_entrada == "momento" else P_GRAD
    if versao_entrada == "graduacao" and tok.get("tGrad"):
        t = tok["tGrad"]
        return t, preco_em(velas, t, max(p0, P_GRAD))
    for v in velas:
        if v[2] >= alvo and v[0] >= t0:
            return v[0], max(alvo, v[1])
    return None


def simular(tok, velas, versao, sol_usd):
    """Uma aposta de US$ 10 num token: (resultado em US$, saída (t), motivo, entrada (t)) ou None se a regra não
    entrou."""
    _vid, _nome, ent, filtro, saida, _r, _fr = versao
    if filtro and tok.get("rc") != "ok":
        return None
    e = entrada(ent, tok, velas)
    if not e:
        return None
    te, pe = e
    grad = lambda t: bool(tok.get("tGrad")) and t >= tok["tGrad"]  # noqa: E731
    sol = APOSTA / sol_usd
    q, gasto = entrar(sol, pe, grad(te))
    if saida == "segura":
        p24 = tok.get("p24")
        if p24 is None:
            p24 = preco_em(velas, te + ESPERA, pe) if velas else pe
        ts = te + ESPERA
        recebido = sair(q, p24, grad(ts)) if p24 > 0 else -REDE_SOL
        return (recebido - gasto) * sol_usd, ts, "24 h", te
    for v in velas:
        if v[0] <= te:
            continue
        if v[0] > te + SAIDA_MIN * MIN:
            break
        if v[3] <= pe * SAIDA_BAIXA:
            return (sair(q, pe * SAIDA_BAIXA, grad(v[0])) - gasto) * sol_usd, v[0], "−50%", te
        if v[2] >= pe * SAIDA_ALTA:
            return (sair(q, pe * SAIDA_ALTA, grad(v[0])) - gasto) * sol_usd, v[0], "dobrou", te
    ts = te + SAIDA_MIN * MIN
    return (sair(q, preco_em(velas, ts, pe), grad(ts)) - gasto) * sol_usd, ts, "30 min", te


def classificar(tok, velas, faltou=False):
    """O resumo do que aconteceu com um token (as contagens do observatório). `faltou`: tinha par, mas as velas não
    vieram (conta como negociado e não morto, e fica fora das apostas)."""
    p0, t0 = tok["p0"], tok["t"]
    maxp = max([v[2] for v in velas] + [tok.get("p24") or 0, p0])
    p24 = tok.get("p24")
    if p24 is None:
        p24 = velas[-1][4] if velas else p0
    golpe = False
    for i, v in enumerate(velas):
        if v[0] > t0 + HORA:
            break
        pico = max(x[2] for x in velas[max(0, i - 5):i + 1])
        if v[3] <= 0.1 * pico and pico > p0 * 1.05:
            golpe = True
            break
    negociou = faltou or any(v[0] >= t0 + MIN for v in velas)
    grad = bool(tok.get("tGrad")) or maxp >= P_GRAD
    morto = (not negociou) or (p24 < 0.1 * p0 and not grad)
    return {"t": t0, "m": curto(tok["mint"]), "x": round(maxp / p0, 3), "x24": round(p24 / p0, 4) if negociou else None, "g": grad,
            "gp": golpe, "mo": morto, "sv": not negociou, "rc": tok.get("rc"), "cr": round(tok.get("cr") or 0, 4),
            "vf": faltou}


def contagens(lista):
    n = len(lista)
    if not n:
        return {"tokens": 0}
    c = lambda f: sum(1 for x in lista if f(x))  # noqa: E731
    x24 = sorted(x["x24"] for x in lista if x["x24"] is not None)
    return {"tokens": n, "dobraram": c(lambda x: x["x"] >= 2), "dezVezes": c(lambda x: x["x"] >= 10),
            "graduaram": c(lambda x: x["g"]), "golpes": c(lambda x: x["gp"]), "morreram": c(lambda x: x["mo"]),
            "semNegocios": c(lambda x: x["sv"]), "rugcheckAlto": c(lambda x: x["rc"] == "alto"),
            "rugcheckSem": c(lambda x: x["rc"] is None), "criadorGrande": c(lambda x: x["cr"] >= CRIADOR_GRANDE),
            "medianaX24": x24[len(x24) // 2] if x24 else None, "semVelas": c(lambda x: x.get("vf") and not x.get("sd")),
            "semDados": c(lambda x: x.get("sd")),
            "vivos24h": c(lambda x: x["x24"] is not None and x["x24"] >= 1 and not x["mo"])}


# ---------------------------------------------------------------------------------------------------- fontes
def eh_pumpfun(m):
    """O PumpPortal manda também os lançamentos de outras plataformas (o campo `pool`: "pump", "bonk"…). Só os do
    pump.fun entram (a curva da simulação é a dele); sem o campo, vale o endereço terminado em "pump"."""
    pool = m.get("pool")
    if pool is not None:
        return str(pool).lower() == "pump"
    return str(m.get("mint") or "").endswith("pump")


def ler_lancamento(m, agora):
    """Uma mensagem de criação do PumpPortal → o token (só números e o endereço) ou None."""
    if not isinstance(m, dict) or m.get("txType") not in ("create", None) or not m.get("mint"):
        return None
    if not eh_pumpfun(m):
        return None
    vS, vT = _f(m.get("vSolInBondingCurve")), _f(m.get("vTokensInBondingCurve"))
    if not vS or not vT:
        return None
    t = _f(m.get("timestamp")) or _f(m.get("_t")) or agora
    if t < 1e11:  # em segundos
        t *= 1000
    return {"mint": str(m["mint"]), "curva": m.get("bondingCurveKey"), "t": int(t),
            "p0": vS / vT, "mc": _f(m.get("marketCapSol")), "cr": (_f(m.get("initialBuy"), 0.0) or 0.0) / OFERTA,
            "pool": m.get("pool")}


def ouvir(fonte, agora, est, log, erros):
    """(lançamentos, migrações, segundos ouvidos)."""
    try:
        msgs = fonte.pumpportal_ouvir(OUVIR_S, OUVIR_MAX)
    except ERROS as e:
        erros.append(f"PumpPortal: {e}")
        log(f"  memes: PumpPortal: {e}")
        return [], [], 0
    if not est.get("formatoVisto") and msgs:
        amostra = next((m for m in msgs if m.get("txType") == "create"), msgs[0])
        log(f"  memes: formato do PumpPortal: {rede.estrutura(amostra, 2)}")
        est["formatoVisto"] = True
    lanc, migr = [], []
    outras = sum(1 for m in msgs if isinstance(m, dict) and m.get("txType") == "create" and m.get("mint")
                 and not eh_pumpfun(m))
    if outras:
        est["outrasPlataformas"] = int(est.get("outrasPlataformas") or 0) + outras
    ts = sorted(int(m["_t"]) for m in msgs if isinstance(m, dict) and m.get("_t"))
    seg = round((ts[-1] - ts[0]) / 1000) if len(ts) > 1 else OUVIR_S
    for m in msgs:
        if m.get("txType") == "migrate" or "migrat" in str(m.get("txType") or "").lower():
            if m.get("mint"):
                migr.append(str(m["mint"]))
            continue
        tok = ler_lancamento(m, agora)
        if tok:
            lanc.append(tok)
    return lanc, migr, max(1, seg)


def rugcheck(fonte, tok, erros):
    """"alto" (algum risco "danger"), "ok" ou None (sem resposta)."""
    try:
        r = fonte.rugcheck(tok["mint"]) or {}
    except ERROS as e:
        if len(erros) < 30:
            erros.append(f"RugCheck: {str(e)[:80]}")
        return None
    riscos = r.get("risks") if isinstance(r, dict) else None
    if not isinstance(riscos, list):
        return None
    return "alto" if any(str((x or {}).get("level", "")).lower() == "danger" for x in riscos) else "ok"


def ler_pares(fonte, mints, log, est, erros):
    """{mint: {"pares": [(dex, endereço, criado ms)], "preco": SOL por token ou None, "liq": US$}} pela DexScreener."""
    out = {}
    for i in range(0, len(mints), 30):
        grupo = mints[i:i + 30]
        r = fonte.dexscreener(f"/tokens/v1/solana/{','.join(grupo)}")  # um erro aqui deixa a amostra para a próxima
        lista = r if isinstance(r, list) else (r or {}).get("pairs") or []
        if lista and not est.get("formatoDex"):
            log(f"  memes: formato da DexScreener: {rede.estrutura(lista[0], 2)}")
            est["formatoDex"] = True
        for p in lista:
            if not isinstance(p, dict):
                continue
            mint = ((p.get("baseToken") or {}).get("address"))
            if mint not in grupo:
                continue
            o = out.setdefault(mint, {"pares": [], "preco": None, "liq": 0.0})
            o["pares"].append((str(p.get("dexId") or ""), p.get("pairAddress"), int(_f(p.get("pairCreatedAt"), 0) or 0)))
            preco = _f(p.get("priceNative"))
            liq = _f(((p.get("liquidity") or {}).get("usd")), 0.0) or 0.0
            if preco is not None and (o["preco"] is None or liq >= o["liq"]):
                o["preco"], o["liq"] = preco, liq
    return out


def pares_gecko(fonte, mint, log, est, erros):
    """Os pares de um token pelo GeckoTerminal (quando a DexScreener não o conhece): {"pares": [...], "preco": SOL por
    token ou None} ou {"pares": []} se o GeckoTerminal também não conhece (404 ou lista vazia: ninguém negociou), ou None
    se ele falhou (o token fica "sem dados": fora das apostas)."""
    try:
        r = fonte.gecko(f"/networks/solana/tokens/{mint}/pools?page=1")
    except ERROS as e:
        if getattr(e, "status", None) == 404:
            return {"pares": [], "preco": None}
        if len(erros) < 30:
            erros.append(f"GeckoTerminal (pares): {str(e)[:80]}")
        return None
    lst = (r or {}).get("data") or []
    if lst and not est.get("formatoGeckoPares"):
        log(f"  memes: formato dos pares do GeckoTerminal: {rede.estrutura(lst[0], 3)}")
        est["formatoGeckoPares"] = True
    out = {"pares": [], "preco": None, "liq": 0.0}
    for x in lst:
        if not isinstance(x, dict):
            continue
        at = x.get("attributes") or {}
        dex = (((x.get("relationships") or {}).get("dex") or {}).get("data") or {}).get("id") or ""
        end = at.get("address")
        if not end:
            continue
        criado = at.get("pool_created_at")
        try:
            criado = int(dt.datetime.fromisoformat(str(criado).replace("Z", "+00:00")).timestamp() * 1000) if criado else 0
        except ValueError:
            criado = 0
        out["pares"].append((DEX_GECKO.get(dex, dex or "?"), end, criado))
        preco = _f(at.get("base_token_price_native_currency"))
        liq = _f(at.get("reserve_in_usd"), 0.0) or 0.0
        if preco is not None and (out["preco"] is None or liq >= out["liq"]):
            out["preco"], out["liq"] = preco, liq
    return out


def ler_velas(fonte, par, mint, t0, log, est, erros):
    """[(t ms, abre, máx., mín., fecha, volume)] em SOL por token, as primeiras VELAS minutos depois de `t0`; [] se o
    GeckoTerminal não conhece o par (404) e None se ele falhou (o token fica sem apostas, mas não conta como morto)."""
    antes = (t0 + VELAS * MIN) // 1000
    try:
        r = fonte.gecko(f"/networks/solana/pools/{par}/ohlcv/minute?aggregate=1&limit={VELAS}&currency=token"
                        f"&token={mint}&before_timestamp={antes}")
    except ERROS as e:
        if getattr(e, "status", None) == 404:
            return []
        if len(erros) < 30:
            erros.append(f"GeckoTerminal: {str(e)[:80]}")
        return None
    lst = ((((r or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list")) or []
    if lst and not est.get("formatoGecko"):
        log(f"  memes: formato das velas do GeckoTerminal: {rede.estrutura(r, 4)}")
        est["formatoGecko"] = True
    out = []
    for x in lst:
        if isinstance(x, list) and len(x) >= 5:
            v = [_f(y) for y in x[:6]] + [0.0] * (6 - len(x[:6]))
            if v[0] and all(y is not None and y > 0 for y in v[1:5]):
                out.append((int(v[0]) * 1000, v[1], v[2], v[3], v[4], v[5] or 0.0))
    return sorted(out)


def preco_sol(cli, t, erros):
    """O preço do SOL em US$ na hora `t` (velas de 1 h da Hyperliquid)."""
    try:
        vs = cli.velas("SOL", "1h", t - 2 * HORA, t + HORA)
        if vs:
            return float(min(vs, key=lambda c: abs(int(c["t"]) - t))["c"])
    except ERROS as e:
        erros.append(f"preço do SOL: {e}")
    return None


def taxa_prioridade(fonte, erros):
    """A mediana da taxa de prioridade recente (micro-lamports por unidade de computação) ou None."""
    try:
        r = fonte.solana("getRecentPrioritizationFees", []) or []
        xs = sorted(int(x.get("prioritizationFee") or 0) for x in r if isinstance(x, dict))
        return xs[len(xs) // 2] if xs else None
    except (ERROS + (TypeError, ValueError, AttributeError)) as e:
        erros.append(f"taxa de prioridade: {e}")
        return None


# ---------------------------------------------------------------------------------------------------- rodada
def analisar(amostra, fonte, cli, est, contas, ev, log, erros, restante):
    """Os tokens de uma amostra 24 h depois: pares, velas, classificação e as apostas de cada versão."""
    toks = amostra["tokens"]
    pares = ler_pares(fonte, [t["mint"] for t in toks], log, est, erros)
    sol_usd = amostra.get("sol") or preco_sol(cli, amostra["t"], erros) or SOL_PADRAO
    migr = set(amostra.get("migr") or [])
    resumos, por_versao = [], {v[0]: [] for v in VERSOES}
    for tok in toks:
        info = pares.get(tok["mint"])
        sem_dados = False
        if info is None:
            # a DexScreener não lista boa parte dos tokens pequenos: o GeckoTerminal confirma se ninguém negociou
            info = pares_gecko(fonte, tok["mint"], log, est, erros) if restante() > 60 else None
            if info is None:
                info, sem_dados = {"pares": [], "preco": None}, True
        velas_lst = []
        amm = [p for p in info["pares"] if p[0] and p[0] != "pumpfun" and p[1]]
        curva = [p for p in info["pares"] if p[0] == "pumpfun" and p[1]]
        faltou = False
        if curva or amm:
            for dex, end, criado in (curva[:1] + amm[:1]):
                vs = ler_velas(fonte, end, tok["mint"], tok["t"], log, est, erros) if restante() > 60 else None
                if vs is None:
                    faltou = True
                else:
                    velas_lst.append(vs)
        if amm:
            tok["tGrad"] = min((p[2] for p in amm if p[2]), default=None) or tok.get("tGrad")
        if tok["mint"] in migr and not tok.get("tGrad"):
            tok["tGrad"] = tok["t"] + HORA  # migrou enquanto ouvíamos (raro): a hora exata não vem
        velas = juntar_velas(velas_lst)
        if not tok.get("tGrad"):
            tok["tGrad"] = next((v[0] for v in velas if v[2] >= P_GRAD), None)
        tok["p24"] = info.get("preco")
        if tok["p24"] is None and not info["pares"]:
            tok["p24"] = 0.0 if velas else None
        if velas and max(v[2] for v in velas) / tok["p0"] > X_ABSURDO:
            faltou, velas = True, []  # erro de unidade (cotado em outra moeda): fica fora, sem contar como 10×
            if len(erros) < 30:
                erros.append(f"velas fora de escala em {curto(tok['mint'])}")
        res = classificar(tok, velas, faltou or sem_dados)
        res["sd"] = sem_dados
        if sem_dados:  # não se sabe o que aconteceu: nem morto, nem vivo, nem sem negócios
            res.update({"x24": None, "mo": False, "sv": False, "x": 1.0})
        resumos.append(res)
        if faltou or sem_dados:
            continue  # sem as velas não dá para simular as regras (nem dizer que morreu)
        for v in VERSOES:
            r = simular(tok, velas, v, sol_usd)
            if r:
                por_versao[v[0]].append((r[1], r[0], r[2], tok["mint"], r[3]))
    # a conta de cada versão: as apostas fecham ao longo das 24 h; a curva é marcada no fim da análise da amostra
    fim = amostra["t"] + ESPERA
    for v in VERSOES:
        c = contas[v[0]]
        # as apostas de uma amostra ficam abertas ao mesmo tempo: só cabem tantas quantas o dinheiro da conta paga
        cabem = int(max(0.0, c.ultimo) // APOSTA)
        res = sorted(por_versao[v[0]], key=lambda r: r[4])[:cabem]
        if len(por_versao[v[0]]) > cabem:
            c.extra["semDinheiro"] = c.extra.get("semDinheiro", 0) + len(por_versao[v[0]]) - cabem
        for _ts, ganho, _motivo, _m, _te in res:
            c.operou(0.0, 2)
            c.fechou(ganho)
        total = sum(x[1] for x in res)
        c.marcar(fim, c.ultimo + total)
        x = c.extra
        x["apostas"] = x.get("apostas", 0) + len(res)
        x["ganhas"] = x.get("ganhas", 0) + sum(1 for r in res if r[1] > 0)
        x["dobrou"] = x.get("dobrou", 0) + sum(1 for r in res if r[2] == "dobrou")
        x["stop"] = x.get("stop", 0) + sum(1 for r in res if r[2] == "−50%")
        x["apostado"] = round(x.get("apostado", 0.0) + APOSTA * len(res), 2)
        x["resultado"] = round(x.get("resultado", 0.0) + total, 4)
        if res:
            x["melhor"] = round(max(x.get("melhor", -1e9), max(r[1] for r in res)), 2)
            x["pior"] = round(min(x.get("pior", 1e9), min(r[1] for r in res)), 2)
        x["acerto"] = round(x["ganhas"] / x["apostas"], 4) if x["apostas"] else None
        x["roi"] = round(x["resultado"] / x["apostado"], 4) if x["apostado"] else None
        if v[0] == "min1" and res:
            ev.add(fim, "resumo", f"Amostra de {dia_de(amostra['t'])[8:10]}/{dia_de(amostra['t'])[5:7]} "
                                   f"({len(toks)} lançamentos): {len(res)} apostas, {sum(1 for r in res if r[1] > 0)} com lucro, "
                                   f"resultado {moeda_br(total)}.", v[0])
    c = contagens(resumos)
    ev.add(fim, "resumo", f"Dos {c['tokens']} lançamentos sorteados há 24 h: {c.get('dobraram', 0)} dobraram, "
                          f"{c.get('graduaram', 0)} se formaram, {c.get('golpes', 0)} caíram mais de 90% em minutos e "
                          f"{c.get('morreram', 0)} morreram.", None)
    return resumos, sol_usd


def rodar(ctx):
    erros = []
    est = copy.deepcopy(ctx.est)
    agora, log, cli = int(ctx.agora), ctx.log, ctx.cli
    fonte = rede.fonte_de(ctx, "pumpportal_ouvir")
    fontes = {id(f): (f, getattr(f, "pedidos", 0)) for f in
              (fonte, rede.fonte_de(ctx, "dexscreener"), rede.fonte_de(ctx, "gecko"), rede.fonte_de(ctx, "rugcheck"),
               rede.fonte_de(ctx, "solana"))}
    try:
        ev = Eventos(est.get("eventos"))
        vivo = est.setdefault("vivo", {})
        inicio = int(est.get("inicio") or agora)
        est["inicio"] = inicio
        contas = {}
        for v in VERSOES:
            c = Curva.de_json(vivo.get(v[0]))
            if c is None:
                c = Curva(inicio=inicio)
                c.marcar(inicio, CAPITAL)
            contas[v[0]] = c
        tokens = est.setdefault("tokens", [])
        pend = est.setdefault("pendentes", [])

        # ---------------------------------------------------------------- 1. as amostras de 24 h atrás
        feitas = 0
        for am in sorted(pend, key=lambda a: a["t"]):
            if am["t"] + ESPERA > agora or feitas >= ANALISES_POR_RODADA or ctx.restante() < 120:
                continue
            try:
                resumos, sol = analisar(am, rede.fonte_de(ctx, "dexscreener"), cli, est, contas, ev, log, erros, ctx.restante)
            except ERROS as e:
                erros.append(f"análise da amostra de {dia_de(am['t'])}: {e}")
                log(f"  memes: a amostra de {dia_de(am['t'])} fica para a próxima rodada ({e})")
                if agora - am["t"] > DESISTIR:
                    pend.remove(am)
                    ev.add(agora, "aviso", f"A amostra de {dia_de(am['t'])[8:10]}/{dia_de(am['t'])[5:7]} foi descartada: "
                                           "a DexScreener não respondeu por 3 dias.", None)
                break
            tokens.extend(resumos)
            est["nAmostras"] = int(est.get("nAmostras") or 0) + 1
            pend.remove(am)
            feitas += 1
            log(f"  memes: amostra de {dia_de(am['t'])} analisada ({len(resumos)} tokens)")
        del tokens[:-MAX_TOKENS]

        # ---------------------------------------------------------------- 2. uma amostra nova
        ultima = max([a["t"] for a in pend] + [int(est.get("ultimaAmostra") or 0)])
        if agora - ultima >= CADA_AMOSTRA and ctx.restante() > OUVIR_S + 120:
            lanc, migr, seg = ouvir(fonte, agora, est, log, erros)
            if lanc:
                rnd = random.Random(agora)
                escolha = rnd.sample(lanc, min(AMOSTRA, len(lanc)))
                rc_fonte = rede.fonte_de(ctx, "rugcheck")
                for tok in escolha:
                    tok["rc"] = rugcheck(rc_fonte, tok, erros) if ctx.restante() > 90 else None
                prio = taxa_prioridade(rede.fonte_de(ctx, "solana"), erros)
                am = {"t": agora, "tokens": escolha, "migr": migr, "lancamentos": len(lanc), "seg": seg,
                      "sol": preco_sol(cli, agora, erros), "prio": prio}
                pend.append(am)
                est["ultimaAmostra"] = agora
                taxa = len(lanc) / max(1.0, seg / 60)
                est["ritmo"] = (est.get("ritmo") or [])[-29:] + [[agora, round(taxa, 2)]]
                if prio is not None:
                    est["prio"] = (est.get("prio") or [])[-29:] + [[agora, prio]]
                log(f"  memes: amostra nova: {len(escolha)} de {len(lanc)} lançamentos em {seg} s")
            else:
                erros.append("nenhum lançamento ouvido")

        # ---------------------------------------------------------------- saída
        for k, c in contas.items():
            vivo[k] = c.para_json()
        est["eventos"] = ev.para_json()
        semana = [x for x in tokens if x["t"] >= agora - 8 * DIA]
        regras = []
        for v in VERSOES:
            x = contas[v[0]].extra
            regras.append({"id": v[0], "nome": v[1], "apostas": x.get("apostas", 0), "acerto": x.get("acerto"),
                           "roi": x.get("roi"), "resultado": x.get("resultado", 0.0), "melhor": x.get("melhor"),
                           "pior": x.get("pior"), "dobrou": x.get("dobrou", 0), "stop": x.get("stop", 0)})
        ritmo = [r for _, r in est.get("ritmo") or []]
        prios = [p for _, p in est.get("prio") or []]
        obs = {"tudo": contagens(tokens), "semana": contagens(semana), "desde": tokens[0]["t"] if tokens else None,
               "amostras": int(est.get("nAmostras") or 0), "esperando": sum(len(a["tokens"]) for a in pend),
               "proxima": min((a["t"] + ESPERA for a in pend), default=None), "regras": regras,
               "lancamentosPorMin": round(sorted(ritmo)[len(ritmo) // 2], 1) if ritmo else None,
               "lancamentosPorDia": round(sorted(ritmo)[len(ritmo) // 2] * 1440) if ritmo else None,
               "outrasPlataformas": int(est.get("outrasPlataformas") or 0)}
        itens = [{"mint": x["m"], "lancado": x["t"], "maxX": x["x"], "x24": x["x24"], "graduou": x["g"], "golpe": x["gp"],
                  "morreu": x["mo"], "rugcheck": x["rc"], "criadorGrande": x["cr"] >= CRIADOR_GRANDE,
                  "semDados": bool(x.get("sd"))}
                 for x in sorted(tokens, key=lambda y: -y["t"])[:MAX_ITENS]]
        versoes = [{"id": v[0], "nome": v[1], "frase": v[6], "risco": v[5], "alav": 1,
                    "grupo": "Referência" if v[4] == "segura" else "Regras",
                    "aoVivo": contas[v[0]].resumo() if contas[v[0]].serie else None, "historico": None} for v in VERSOES]
        cfg = {"frequencia": "2 vezes por dia (cada amostra é analisada 24 h depois)", "rede": "Solana", "plataforma": "pump.fun",
               "aposta": APOSTA, "amostra": AMOSTRA, "ouvirSegundos": OUVIR_S,
               "taxas": {"curva": TAXA_CURVA, "amm": TAXA_AMM, "deslizeAmm": DESLIZE_AMM, "redeSol": REDE_SOL},
               "prioridade": sorted(prios)[len(prios) // 2] if prios else None,
               "saida": {"alta": SAIDA_ALTA, "baixa": SAIDA_BAIXA, "minutos": SAIDA_MIN}, "observatorio": True}
        ctx.est.clear()
        ctx.est.update(est)
        return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": "min1", "versoes": versoes,
                "eventos": est["eventos"], "itens": itens, "observatorio": obs, "avisos": AVISOS, "config": cfg,
                "erros": erros}
    finally:
        for f, p0 in fontes.values():
            rede.somar_pedidos(ctx, f, p0)
