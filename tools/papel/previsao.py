"""Mercados de previsão, NO PAPEL (formato: tools/papel/FORMATO.md, "Mercados de previsão"). Pedido do Alediov,
09/11/2026. **Só observação**: desde abril de 2026 o Brasil bloqueou a Polymarket e a Kalshi; aqui não há conta,
ordem, carteira nem chave de verdade. Só dados públicos e gratuitos, lidos pela `rede.py` (com o freio por fonte):

- Polymarket Gamma (`gamma-api.polymarket.com/markets`): os mercados abertos (preço, melhor compra/venda, volume,
  liquidez, fim) e os encerrados (a resolução: `outcomePrices` vira ["1","0"] ou ["0","1"]);
- Polymarket CLOB (`clob.polymarket.com`): o livro de cada lado (`/book?token_id=`), para o preço de entrada com o
  deslize, e o histórico de preços (`/prices-history?market=<token>&startTs&endTs&fidelity`);
- Polymarket Data (`data-api.polymarket.com`): o ranking da semana (`/v1/leaderboard`; reserva `lb-api…/profit`) e as
  negociações públicas de cada carteira (`/trades?user=`);
- Kalshi (`api.elections.kalshi.com/trade-api/v2/markets`, a lista pública) e Manifold (`api.manifold.markets/v0`,
  dinheiro de mentira) só como referência de preço no mesmo evento.

Os nomes dos campos foram escritos SEM acesso a essas fontes (a rede desta sessão as bloqueia): cada resposta tem a
estrutura registrada no log na 1ª vez (`estrutura`) e os campos são lidos com alternativas. Fonte que falha vira
`semDados` com o motivo; a forma continua com o resto.

As versões (contas fictícias de US$ 1.000; US$ 20 por posição; entrada = melhor oferta de venda do livro + o deslize
de andar pelo livro com os US$ 20; taxa da Polymarket onde o mercado tiver; saída pela resolução oficial; marcadas pela
melhor oferta de compra, o que se receberia vendendo agora):

1. **Observatório de calibração** (sem conta, `calibracao`): de cada mercado encerrado (volume ≥ US$ 5 mil, aberto por
   2 dias ou mais, sim ou não), o preço do "Sim" 24 h, 7 dias e 30 dias antes do fim × o que aconteceu; por faixa de
   10 pontos, a frequência real com o intervalo de Wilson, e o Brier score por categoria. "A multidão acerta?".
2. **Favorito perto do fim** (`fav90`, `fav95`): compra o lado a 90% (95%) ou mais faltando até 7 dias, até 99%. A
   "colheita de centavos": ganha pouco quase sempre; a conta mede a cauda (`extra.cauda`).
3. **Azarão** (`azarao`): compra o lado entre 2% e 10% faltando até 30 dias (para medir o viés do azarão: espera-se
   perder).
4. **Diferença entre casas** (`difK`, `difM`): quando o mesmo evento está na Kalshi (ou na Manifold) e a Polymarket
   está 5 pontos ou mais mais barata num lado, compra esse lado na Polymarket. O casamento é conservador (`casar`): os
   mesmos números na pergunta, as mesmas negações, ≥ 70% das palavras em comum e o fim a até 3 dias; na dúvida, não casa.
5. **Seguir os melhores** (`seguir`): toda segunda (Brasília), as 10 carteiras de maior lucro da semana anterior no
   ranking; na semana seguinte, cada compra delas (≥ US$ 50) é copiada com US$ 20 pelo preço 5 min depois (o histórico
   de preços) + 1 centavo de deslize estimado, e a venda delas fecha a nossa (fora da amostra: escolhe com a semana
   passada, mede na seguinte). Só o endereço público e contagens; nunca o apelido. `aproximado: true`.
6. **Réguas** (`cdi`, `usdc`): o CDI do Banco Central e o dólar digital parado.

Teste no passado (aproximado, só fav90, fav95 e azarão): os mesmos mercados encerrados do observatório (até 180 dias),
com o preço de cada dia antes do fim (o histórico de 12 em 12 h) e 1 centavo de deslize; `historico.janelas` de 30 dias.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import time
import unicodedata
import urllib.parse

import rede
from conta import CAPITAL, DIA, HORA, Curva, Eventos, _cdi_do_dia, cdi_ano_da_serie, dia_de, moeda_br, pct_br

try:  # o falso da Hyperliquid levanta hl.Erro quando um pedido "falha" nos testes
    import hl
    ERROS = (rede.Erro, hl.Erro)
except ImportError:  # pragma: no cover
    ERROS = (rede.Erro,)

NOME = "Previsão"
VERSAO = 1

# ---------------------------------------------------------------------------------------------------- regras
APOSTA = 20.0                 # US$ por posição
FAV_DIAS = 7
FAV_MAX = 0.99
AZ_MIN, AZ_MAX, AZ_DIAS = 0.02, 0.10, 30
DIF_MIN = 0.05                # 5 pontos de diferença (já com o deslize)
DIF_FIM_DIAS = 3              # o fim dos dois mercados a até 3 dias
DIF_JACCARD = 0.70
DIF_SPREAD_MAX = 0.10         # a referência só vale com compra e venda a até 10 pontos
MANIFOLD_MIN_APOSTADORES = 20
MANIFOLD_BUSCAS = 25          # perguntas da Polymarket procuradas na Manifold por rodada
KALSHI_PAGINAS = 3
LIQ_MIN, VOL24_MIN = 5000.0, 1000.0
MAX_NOVAS = 8                 # posições novas por versão por rodada
ABERTOS_PAGINAS = 2
SEG_N = 10
SEG_ATRASO = 5 * 60_000       # a cópia entra 5 min depois da carteira
SEG_DESLIZE = 0.01            # 1 centavo estimado (o livro daquela hora não existe mais)
SEG_MIN_US = 50.0             # compra mínima da carteira para ser copiada
SEG_MAX_RODADA = 30           # cópias novas por rodada (cada uma pede o histórico de preços)
SEG_MAX_DIA = 3               # cópias novas por carteira por dia (as de muito giro não tomam a conta inteira)
CAL_DIAS = 180
CAL_POR_RODADA = 80           # históricos de preço pedidos por rodada no observatório
CAL_MAX = 3000                # mercados guardados
CAL_VOL_MIN = 5000.0
CAL_DURACAO_MIN = 2 * DIA
CAL_PULADOS_MAX = 4000
HORIZONTES = [("24h", "1 dia antes", 1), ("7d", "7 dias antes", 7), ("30d", "30 dias antes", 30)]
SPREAD_HIST = 0.01            # o deslize do teste no passado (1 centavo)
ORCAMENTO_S = 420             # tempo máximo da forma por rodada (a rodada do papel.yml tem 24 min)
JANELA_DIAS, JANELA_PASSO = 30, 7
MAX_EVENTOS_RODADA = 25
ITENS_MAX = 80
SEMANA_MS = 7 * DIA
# os jeitos de pedir o prices-history, em ordem (startTs/endTs OU interval; fidelity em minutos)
HIST_JEITOS = [
    lambda a, b, f: f"startTs={a}&endTs={b}&fidelity={f}",
    lambda a, b, f: f"startTs={a}&endTs={b}",
    lambda a, b, f: f"interval=max&fidelity={max(f, 720) if b - a > 7 * 86400 else max(f, 60)}",
    lambda a, b, f: "interval=1w&fidelity=60" if b - a <= 7 * 86400 else "interval=1m&fidelity=720",
]
PMDATA = "/v2"                # a Data API v1 foi aposentada (HTTP 410 com "migration": ".../v2/") na 2ª rodada real
RANK_MERCADOS = 15            # mercados resolvidos na semana anterior lidos para montar o ranking
RANK_MIN_NEGOCIOS = 3

CATEGORIAS = ["Esportes", "Política", "Cripto", "Economia", "Cultura", "Ciência e tecnologia", "Outros"]
_PALAVRAS = [  # (categoria, palavras) na ordem de prioridade; casa palavra inteira, sem acento e sem maiúscula
    ("Esportes", ["sports", "sport", "nba", "nfl", "mlb", "nhl", "soccer", "football", "tennis", "ufc", "f1", "formula 1",
                  "premier league", "champions league", "la liga", "serie a", "bundesliga", "world cup", "match",
                  "vs", "vs.", "game", "golf", "cricket", "boxing", "olympics", "esports", "grand prix", "super bowl",
                  "playoffs", "finals", "beat", "brasileirao", "copa"]),
    ("Cripto", ["crypto", "bitcoin", "btc", "ethereum", "eth", "solana", "sol", "token", "coin", "airdrop", "fdv",
                "memecoin", "stablecoin", "binance", "xrp", "doge", "nft", "etf"]),
    ("Economia", ["fed", "interest rate", "interest rates", "rates", "inflation", "cpi", "gdp", "recession", "stocks",
                  "s&p", "nasdaq", "dow", "unemployment", "earnings", "tariff", "tariffs", "central bank", "economy",
                  "economics", "oil", "gold", "treasury", "ipo", "market cap"]),
    ("Política", ["politics", "election", "elections", "president", "presidential", "senate", "congress", "governor",
                  "prime minister", "parliament", "vote", "nominee", "primary", "mayor", "government", "minister",
                  "geopolitics", "war", "ceasefire", "nato", "party", "impeach", "supreme court", "referendum",
                  "trump", "putin", "zelensky", "candidate"]),
    ("Cultura", ["culture", "pop culture", "oscar", "oscars", "grammy", "grammys", "movie", "film", "album",
                 "box office", "award", "awards", "tv", "song", "spotify", "youtube", "celebrity", "netflix", "music",
                 "billboard", "emmy", "tweet", "tweets", "best picture"]),
    ("Ciência e tecnologia", ["science", "tech", "technology", "ai", "openai", "gpt", "spacex", "launch", "nasa",
                              "apple", "google", "climate", "temperature", "weather", "hurricane", "earthquake",
                              "pandemic", "vaccine", "rocket", "mars"]),
]
STOP = {"will", "the", "a", "an", "of", "in", "on", "by", "be", "to", "for", "before", "after", "at", "is", "are",
        "does", "do", "and", "or", "than", "this", "that", "with", "from", "as", "end", "who", "what", "which",
        "it", "its", "has", "have", "happen", "occur", "reach", "hit", "get", "any", "there"}
NEGACOES = {"not", "no", "never", "without", "nao", "fail", "fails", "lose", "loses", "below", "under", "less"}

VERSOES = [
    {"id": "fav90", "nome": "Favorito ≥ 90%", "grupo": "Favorito perto do fim", "risco": "médio",
     "frase": "Compra o lado a 90% ou mais quando faltam até 7 dias para o fim: ganha pouco quase sempre e perde US$ 20 de vez em quando."},
    {"id": "fav95", "nome": "Favorito ≥ 95%", "grupo": "Favorito perto do fim", "risco": "médio",
     "frase": "Igual, só com o lado a 95% ou mais: ganha ainda menos por vez; a cauda é a mesma."},
    {"id": "azarao", "nome": "Azarão ≤ 10%", "grupo": "Azarão", "risco": "alto",
     "frase": "Compra o lado entre 2% e 10% quando faltam até 30 dias. Mede o viés do azarão: espera-se perder."},
    {"id": "difK", "nome": "Mais barato que a Kalshi", "grupo": "Diferença entre casas", "risco": "médio",
     "frase": "Quando o mesmo evento está na Kalshi e a Polymarket está 5 pontos ou mais mais barata num lado, compra esse lado."},
    {"id": "difM", "nome": "Mais barato que a Manifold", "grupo": "Diferença entre casas", "risco": "médio",
     "frase": "O mesmo contra a Manifold, que é de dinheiro de mentira: a referência é mais fraca."},
    {"id": "seguir", "nome": "Seguir os 10 da semana", "grupo": "Seguir os melhores", "risco": "alto", "aproximado": True,
     "frase": "Copia, 5 min depois, as compras das 10 carteiras que mais lucraram na semana anterior (escolhidas toda segunda)."},
    {"id": "cdi", "nome": "CDI", "grupo": "Referência", "risco": "baixo",
     "frase": "Os US$ 1.000 rendendo o CDI do Banco Central: a régua de sempre."},
    {"id": "usdc", "nome": "Dólar digital parado", "grupo": "Referência", "risco": "baixo",
     "frase": "Os US$ 1.000 em USDC sem fazer nada (é a moeda da Polymarket)."},
]
IDS = [v["id"] for v in VERSOES]
PADRAO = "fav90"
COM_PASSADO = {"fav90": ("fav", 0.90), "fav95": ("fav", 0.95), "azarao": ("az", AZ_MAX)}

FRASE = ("Mercados de previsão: apostas em sim ou não sobre eventos (eleições, jogos, economia), em que o preço "
         "é a chance que a multidão dá. Aqui só observando e no papel: a Polymarket e a Kalshi estão bloqueadas no "
         "Brasil desde abril de 2026.")
COMO_FUNCIONA = [
    "Cada mercado paga US$ 1 por cota se o lado escolhido acontecer e nada se não acontecer. Uma cota a 90 centavos "
    "diz que a multidão vê 90% de chance; quem compra ganha 10 centavos por cota se der certo e perde os 90 se der errado.",
    "Só no papel e só observando: desde abril de 2026 o Brasil bloqueou a Polymarket e a Kalshi. Aqui não há conta, "
    "carteira, ordem nem chave; são lidos só os dados públicos e gratuitos (preços, livros, resoluções, o ranking).",
    "O observatório de calibração confere se a multidão acerta: dos mercados que já acabaram, os que estavam a 80% "
    "um dia antes aconteceram mesmo 80% das vezes? A tabela mostra cada faixa com o intervalo de 95%, e o Brier score "
    "(0 = perfeito, 0,25 = chute de 50%) por categoria.",
    "As contas começam com US$ 1.000 e põem US$ 20 em cada posição, ao preço de quem vende no livro (andando pelo "
    "livro com os US$ 20, o que dá o deslize) e pagando a taxa da Polymarket nos mercados que cobram. Valem pelo preço "
    "de quem compra (o que se receberia vendendo agora) e terminam na resolução oficial.",
    "Favorito perto do fim compra o lado a 90% ou 95% quando faltam até 7 dias; Azarão, o lado a 10% ou menos. Diferença "
    "entre casas compra na Polymarket quando ela está 5 pontos mais barata que a Kalshi ou a Manifold no MESMO evento "
    "(só os casamentos seguros: mesmos números, mesmo fim). Seguir os melhores copia as 10 carteiras de maior lucro da "
    "semana anterior, escolhidas toda segunda e medidas na semana seguinte.",
    "O teste no passado (só Favorito e Azarão) usa os mercados que o observatório já leu, com o preço de cada dia antes "
    "do fim: é aproximado, porque o livro daquela hora não existe mais (1 centavo de deslize no lugar).",
]
AVISOS = [
    "A Polymarket e a Kalshi estão bloqueadas no Brasil desde abril de 2026: isto é só observação, sem conta nem ordem.",
    "O preço de entrada é o do livro na hora da rodada (a cada 6 h); quem acompanha o mercado o dia todo pega preços "
    "melhores ou piores.",
    "Mercados podem ser resolvidos com atraso ou contestados (o oráculo da UMA); a conta espera a resolução oficial e "
    "mercados anulados devolvem 50 centavos por cota.",
    "Favorito perto do fim parece ganhar sempre até o dia em que o improvável acontece: olhe a cauda, não o acerto.",
    "Seguir os melhores copia pelo preço do histórico 5 min depois, com 1 centavo estimado de deslize: é aproximado.",
    "Os casamentos entre casas podem errar o evento (regras de resolução diferentes): a regra é conservadora e casa pouco.",
    "Taxas: a fórmula usada é a das taxas da Polymarket (base × min(preço, 1 − preço) × cotas), só nos mercados que cobram.",
]


# ---------------------------------------------------------------------------------------------------- utilidades
def estrutura(x, prof=3):
    return rede.estrutura(x, prof)


def _f(x, padrao=None):
    try:
        if x is None or x == "":
            return padrao
        v = float(x)
        return v if math.isfinite(v) else padrao
    except (TypeError, ValueError):
        return padrao


def _lista_json(x):
    """Os campos da Gamma que vêm como texto JSON ('["Yes","No"]') ou já como lista."""
    if isinstance(x, list):
        return x
    if isinstance(x, str) and x.strip().startswith("["):
        try:
            v = json.loads(x)
            return v if isinstance(v, list) else []
        except ValueError:
            return []
    return []


def ms_de(x):
    """ms UTC de um ISO ("2026-11-03T12:00:00Z", "2026-11-03 12:00:00+00", "2026-11-03"), de segundos ou de ms."""
    if x is None or x == "":
        return None
    if isinstance(x, (int, float)):
        v = float(x)
        return int(v if v > 1e11 else v * 1000)
    s = str(x).strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return ms_de(float(s))
    s = s.replace(" ", "T").replace("Z", "+00:00")
    if re.search(r"[+-]\d\d$", s):
        s += ":00"
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        try:
            d = dt.datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp() * 1000)


def iso(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn").lower()


def curta(texto, n=90):
    t = re.sub(r"\s+", " ", str(texto or "")).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def cent(p):
    """0,956 → "95,6" (o preço em centavos, com vírgula)."""
    return f"{p * 100:.1f}".replace(".", ",")


def carteira_curta(end):
    e = str(end or "")
    return f"{e[:6]}…{e[-4:]}" if len(e) > 12 else e


def semana_de(ms):
    """A segunda-feira (Brasília) da semana de `ms`, AAAA-MM-DD."""
    d = dt.date.fromisoformat(dia_de(ms))
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(max(0.0, c - m), 4), round(min(1.0, c + m), 4)]


def categoria(m):
    """A categoria do mercado: a da própria Polymarket (campo `category`, do evento ou as etiquetas) traduzida, senão
    pelas palavras da pergunta. Esportes entram, marcados."""
    textos = []
    for k in ("category", "categoria"):
        if m.get(k):
            textos.append(str(m[k]))
    for e in m.get("events") or []:
        if isinstance(e, dict):
            if e.get("category"):
                textos.append(str(e["category"]))
            for t in e.get("tags") or []:
                if isinstance(t, dict):
                    textos.append(str(t.get("label") or t.get("slug") or ""))
    for t in m.get("tags") or []:
        if isinstance(t, dict):
            textos.append(str(t.get("label") or t.get("slug") or ""))
        elif isinstance(t, str):
            textos.append(t)
    for fonte in (" | ".join(textos), str(m.get("question") or m.get("title") or "")):
        alvo = " " + re.sub(r"[^a-z0-9&.+ ]+", " ", _sem_acento(fonte)) + " "
        for cat, palavras in _PALAVRAS:
            for p in palavras:
                if f" {p} " in alvo:
                    return cat
    return "Outros"


# ---------------------------------------------------------------------------------------------------- mercados
def mercado_de(m):
    """Um mercado da Gamma num dicionário curto. None se não for de sim ou não, ou faltar o essencial."""
    if not isinstance(m, dict):
        return None
    nomes = _lista_json(m.get("outcomes"))
    toks = [str(t) for t in _lista_json(m.get("clobTokenIds"))]
    precos = [_f(p) for p in _lista_json(m.get("outcomePrices"))]
    if len(nomes) != 2 or len(toks) != 2:
        return None
    # o lado 0 é sempre o 1º de `outcomes` (a ordem de `clobTokenIds` e de `outcomePrices` segue a dele); se vier
    # ["No", "Yes"], troca para o "Sim" ser o lado 0. Outcomes com nome (times, pessoas) ficam na ordem da fonte.
    if [str(x).strip().lower() for x in nomes] == ["no", "yes"]:
        nomes, toks = nomes[::-1], toks[::-1]
        precos = precos[::-1] if len(precos) == 2 else precos
    mid = str(m.get("id") or m.get("conditionId") or "")
    if not mid:
        return None
    fim = ms_de(m.get("endDate") or m.get("end_date_iso") or m.get("endDateIso"))
    fechou = ms_de(m.get("closedTime") or m.get("closed_time"))
    ini = ms_de(m.get("startDate") or m.get("createdAt") or m.get("start_date_iso"))
    fechado = bool(m.get("closed"))
    resultado = None
    if fechado and len(precos) == 2 and None not in precos:
        if precos[0] >= 0.99 and precos[1] <= 0.01:
            resultado = 1.0
        elif precos[1] >= 0.99 and precos[0] <= 0.01:
            resultado = 0.0
        elif abs(precos[0] - 0.5) < 0.01 and abs(precos[1] - 0.5) < 0.01:
            resultado = 0.5
    st = str(m.get("umaResolutionStatus") or "").lower()
    if st and st not in ("resolved", "") and resultado is not None and st in ("proposed", "disputed", "challenged"):
        resultado = None  # ainda pode mudar
    return {
        "id": mid, "q": str(m.get("question") or m.get("title") or ""), "cond": str(m.get("conditionId") or ""),
        "nomes": [str(x) for x in nomes], "toks": toks, "precos": precos,
        "bid": _f(m.get("bestBid")), "ask": _f(m.get("bestAsk")),
        "vol24": _f(m.get("volume24hr"), _f(m.get("volume24hrClob"), 0.0)),
        "vol": _f(m.get("volumeNum"), _f(m.get("volume"), 0.0)),
        "liq": _f(m.get("liquidityNum"), _f(m.get("liquidity"), 0.0)),
        "fechouEm": fechou, "ini": ini, "fim": min(x for x in (fim, fechou) if x) if (fim or fechou) else None, "fimPrevisto": fim,
        "fechado": fechado, "resultado": resultado, "cat": categoria(m),
        "evento": str(((m.get("events") or [{}])[0] or {}).get("id") or ((m.get("events") or [{}])[0] or {}).get("slug")
                      or m.get("eventSlug") or m.get("groupItemTitle") or "") if isinstance(m.get("events"), list) else
                  str(m.get("eventSlug") or ""),
        "negRisk": bool(m.get("negRisk") or m.get("neg_risk")),
        "taxaBps": _f(m.get("takerBaseFee"), 0.0) if m.get("feesEnabled", True) is not False else 0.0,
        "livro": m.get("enableOrderBook") is not False,
        "aberto": (not fechado) and m.get("active", True) is not False and m.get("acceptingOrders", True) is not False,
    }


def marca(mk, lado):
    """O valor de uma cota do lado agora: a melhor compra (o que se recebe vendendo); sem ela, o preço exibido."""
    if mk.get("resultado") is not None:
        r = mk["resultado"]
        return r if lado == 0 else 1 - r
    if lado == 0 and mk.get("bid") is not None:
        return mk["bid"]
    if lado == 1 and mk.get("ask") is not None:
        return 1 - mk["ask"]
    p = (mk.get("precos") or [None, None])[lado]
    return p if p is not None else 0.0


def ask_lado(mk, lado):
    """A melhor oferta de venda do lado pela Gamma (o lado "Não" = 1 − melhor compra do "Sim")."""
    if lado == 0:
        return mk.get("ask")
    return None if mk.get("bid") is None else 1 - mk["bid"]


def taxa(preco, cotas, bps):
    """Taxa da Polymarket nos mercados que cobram: base (bps) × min(preço, 1 − preço) × cotas (conferir na fonte)."""
    if not bps:
        return 0.0
    return bps / 10_000 * min(preco, 1 - preco) * cotas


def comprar_no_livro(asks, valor):
    """Anda pelas ofertas de venda (preço crescente) gastando `valor` US$. Devolve (cotas, preço médio, melhor) ou None
    se o livro não tem o bastante."""
    nivs = []
    for a in asks or []:
        if isinstance(a, dict):
            p, s = _f(a.get("price")), _f(a.get("size"))
        elif isinstance(a, (list, tuple)) and len(a) >= 2:
            p, s = _f(a[0]), _f(a[1])
        else:
            continue
        if p and s and 0 < p < 1:
            nivs.append((p, s))
    nivs.sort()
    if not nivs:
        return None
    falta, cotas = valor, 0.0
    for p, s in nivs:
        custo = p * s
        if custo >= falta:
            cotas += falta / p
            falta = 0
            break
        cotas += s
        falta -= custo
    if falta > 1e-9 or cotas <= 0:
        return None
    return cotas, valor / cotas, nivs[0][0]


def _palavras(q):
    t = _sem_acento(q)
    t = re.sub(r"(?<![a-z0-9])\$?(\d[\d,]*(?:\.\d+)?)\s*([km%])?", lambda m: " #" + m.group(1).replace(",", "") + (m.group(2) or "") + " ", t)
    t = re.sub(r"[^a-z0-9# ]+", " ", t)
    ws = t.split()
    nums = {w[1:] for w in ws if w.startswith("#")}
    neg = {w for w in ws if w in NEGACOES}
    resto = {w for w in ws if not w.startswith("#") and w not in STOP and len(w) > 1}
    return resto, nums, neg


def casar(q1, fim1, q2, fim2, dias=DIF_FIM_DIAS):
    """O mesmo evento em duas casas? Conservador: os mesmos números, as mesmas negações, ≥ 70% das palavras em comum
    (Jaccard, sem as palavras vazias) e o fim a até `dias` dias (quando as duas dizem). Devolve a nota (0 a 1) ou 0."""
    a, na, ga = _palavras(q1)
    b, nb, gb = _palavras(q2)
    if not a or not b or na != nb or ga != gb:
        return 0.0
    j = len(a & b) / len(a | b)
    if j < DIF_JACCARD:
        return 0.0
    if fim1 and fim2 and abs(fim1 - fim2) > dias * DIA:
        return 0.0
    return round(j, 3)


# ---------------------------------------------------------------------------------------------------- a conta
class Carteira:
    """Uma versão: caixa, posições ({chave: {...}}), a curva e os contadores da conta por dentro."""
    ACC = ("ganhos", "perdas", "taxas", "deslize", "entradas", "resolvidas", "ganhas", "apostado", "somaPreco",
           "vendidas", "anuladas")

    def __init__(self, inicio, capital=CAPITAL):
        self.caixa = capital
        self.pos = {}
        self.curva = Curva(inicio, capital)
        self.ac = {k: 0.0 for k in self.ACC}
        self.cauda = []      # resultado de cada posição fechada perdendo (as últimas 200)
        self.ganhosLista = []  # e ganhando (as últimas 200)
        self.cat = {}

    def valor(self, marcas):
        v = self.caixa
        for p in self.pos.values():
            v += p["sh"] * marcas.get(p["k"], p.get("ult", p["ent"]))
        return v

    def comprar(self, chave, info, cotas, preco, melhor, t, bps):
        tx = taxa(preco, cotas, bps)
        desl = max(0.0, (preco - melhor) * cotas) if melhor else 0.0
        if self.caixa < APOSTA + tx:
            return None
        self.caixa -= APOSTA + tx
        self.pos[chave] = {**info, "k": chave, "sh": round(cotas, 6), "ent": round(preco, 5), "custo": APOSTA,
                           "tx": round(tx, 6), "em": int(t), "ult": round(preco, 5)}
        self.ac["entradas"] += 1
        self.ac["apostado"] += APOSTA
        self.ac["taxas"] += tx
        self.ac["deslize"] += desl
        self.ac["somaPreco"] += preco
        c = info.get("cat") or "Outros"
        self.cat[c] = self.cat.get(c, 0) + 1
        self.curva.operou(taxa=tx + desl)
        return self.pos[chave]

    def fechar(self, chave, preco, t, resolveu=True, bps=0.0):
        p = self.pos.pop(chave)
        tx = 0.0 if resolveu else taxa(preco, p["sh"], bps)
        recebe = p["sh"] * preco - tx
        pnl = recebe - p["custo"] - p.get("tx", 0.0)
        self.caixa += recebe
        self.ac["taxas"] += tx
        if pnl >= 0:
            self.ac["ganhos"] += pnl
            self.ganhosLista.append(round(pnl, 4))
            del self.ganhosLista[:-200]
        else:
            self.ac["perdas"] += -pnl
            self.cauda.append(round(pnl, 4))
            del self.cauda[:-200]
        if resolveu:
            self.ac["resolvidas"] += 1
            if abs(preco - 0.5) < 1e-9:
                self.ac["anuladas"] += 1
            elif preco > 0.5:
                self.ac["ganhas"] += 1
        else:
            self.ac["vendidas"] += 1
            if tx:
                self.curva.operou(taxa=tx)
        self.curva.fechou(pnl)
        return p, pnl

    def extra(self, marcas):
        fech = self.ac["resolvidas"] + self.ac["vendidas"]
        aberto = sum(p["sh"] * marcas.get(p["k"], p.get("ult", p["ent"])) - p["custo"] - p.get("tx", 0) for p in self.pos.values())
        realizado = self.ac["ganhos"] - self.ac["perdas"]
        resultado = self.valor(marcas) - self.curva.capital
        out = {
            "posicoes": int(self.ac["entradas"]), "abertas": len(self.pos), "resolvidas": int(self.ac["resolvidas"]),
            "vendidas": int(self.ac["vendidas"]), "ganhas": int(self.ac["ganhas"]), "anuladas": int(self.ac["anuladas"]),
            "acerto": round(self.ac["ganhas"] / self.ac["resolvidas"], 4) if self.ac["resolvidas"] else None,
            "apostado": round(self.ac["apostado"], 2),
            "roi": round(realizado / (fech * APOSTA), 4) if fech else None,
            "precoMedio": round(self.ac["somaPreco"] / self.ac["entradas"], 4) if self.ac["entradas"] else None,
            "porCategoria": dict(sorted(self.cat.items(), key=lambda x: -x[1])),
            "porDentro": {"ganhos": round(self.ac["ganhos"], 2), "perdas": round(self.ac["perdas"], 2),
                          "taxas": round(self.ac["taxas"], 2), "deslize": round(self.ac["deslize"], 2),
                          "emAberto": round(aberto, 2), "realizado": round(realizado, 2),
                          "custos": round(self.ac["taxas"] + self.ac["deslize"], 2), "resultado": round(resultado, 2)},
        }
        if self.cauda or self.ganhosLista:
            gm = sum(self.ganhosLista) / len(self.ganhosLista) if self.ganhosLista else None
            maior = min(self.cauda) if self.cauda else None
            out["cauda"] = {"perdas": len(self.cauda), "maiorPerda": maior, "ganhoMedio": round(gm, 4) if gm else None,
                            "perdaMedia": round(sum(self.cauda) / len(self.cauda), 4) if self.cauda else None,
                            "vitoriasPorPerda": round(-maior / gm, 1) if maior is not None and gm else None}
        return out

    def para_json(self):
        return {"caixa": self.caixa, "pos": self.pos, "curva": self.curva.para_json(), "ac": self.ac,
                "cauda": self.cauda, "ganhosLista": self.ganhosLista, "cat": self.cat}

    @classmethod
    def de_json(cls, d):
        if not d:
            return None
        c = cls(d["curva"]["inicio"], d["curva"].get("capital", CAPITAL))
        c.caixa, c.pos = d.get("caixa", CAPITAL), dict(d.get("pos") or {})
        c.curva = Curva.de_json(d["curva"])
        c.ac.update(d.get("ac") or {})
        c.cauda, c.ganhosLista, c.cat = list(d.get("cauda") or []), list(d.get("ganhosLista") or []), dict(d.get("cat") or {})
        return c


# ---------------------------------------------------------------------------------------------------- a rodada
class Rodada:
    def __init__(self, ctx, fonte, prazo_s):
        self.ctx, self.f, self.log = ctx, fonte, ctx.log
        self.t0, self.prazo = time.monotonic(), prazo_s
        self.sem = {}           # fonte → motivo
        self.erros = []
        self.livros = {}
        self.vistas = set(ctx.est.setdefault("estruturas", []))

    def tempo(self, sobra=0):
        return time.monotonic() - self.t0 < self.prazo - sobra

    def pedir(self, metodo, caminho, rotulo, fonte_sem=None):
        """Um pedido; registra a estrutura na 1ª resposta de cada `rotulo` e, no erro, anota `semDados`."""
        self.ultimo_status = None
        try:
            r = getattr(self.f, metodo)(caminho)
        except ERROS as e:
            self.ultimo_status = getattr(e, "status", None)
            if fonte_sem:
                self.sem.setdefault(fonte_sem, str(e)[:160])
            self.log(f"  previsão: {rotulo}: {e}")
            return None
        if rotulo not in self.vistas:
            self.vistas.add(rotulo)
            self.log(f"  previsão: estrutura de {rotulo}: {json.dumps(estrutura(r), ensure_ascii=False)[:700]}")
        return r

    def lista(self, r, *chaves):
        if isinstance(r, list):
            return r
        if isinstance(r, dict):
            for k in chaves:
                if isinstance(r.get(k), list):
                    return r[k]
        return []

    # -------------------------------------------------- Polymarket
    def abertos(self):
        out, vistos = [], set()
        for pg in range(ABERTOS_PAGINAS):
            if not self.tempo(120):
                break
            r = self.pedir("gamma", f"/markets?active=true&closed=false&limit=500&offset={pg * 500}&order=volume24hr"
                                    f"&ascending=false&liquidity_num_min={int(LIQ_MIN)}", "gamma /markets (abertos)", "gamma")
            xs = self.lista(r, "data", "markets")
            for m in xs:
                mk = mercado_de(m)
                if mk and mk["id"] not in vistos and mk["aberto"] and mk["livro"]:
                    vistos.add(mk["id"])
                    out.append(mk)
            if len(xs) < 500:
                break
        return out

    def por_ids(self, ids):
        out = {}
        ids = list(dict.fromkeys(ids))
        for i in range(0, len(ids), 40):
            parte = ids[i:i + 40]
            for extra in ("", "&closed=true"):
                falta = [x for x in parte if x not in out]
                if not falta:
                    break
                r = self.pedir("gamma", "/markets?" + "&".join(f"id={urllib.parse.quote(x)}" for x in falta)
                               + f"&limit={len(falta)}" + extra, "gamma /markets (por id)", "gamma")
                for m in self.lista(r, "data", "markets"):
                    mk = mercado_de(m)
                    if mk:
                        out[mk["id"]] = mk
        return out

    def por_condicao(self, cond):
        r = self.pedir("gamma", f"/markets?condition_ids={urllib.parse.quote(cond)}&limit=5", "gamma /markets (condição)", "gamma")
        for m in self.lista(r, "data", "markets"):
            mk = mercado_de(m)
            if mk and (not cond or mk["cond"].lower() == cond.lower() or len(self.lista(r)) == 1):
                return mk
        return None

    def livro(self, tok):
        if tok in self.livros:
            return self.livros[tok]
        r = self.pedir("clob", f"/book?token_id={urllib.parse.quote(tok)}", "clob /book", "clob")
        asks = (r or {}).get("asks") if isinstance(r, dict) else None
        self.livros[tok] = asks
        return asks

    def historico(self, tok, ini, fim, fidelidade):
        """O histórico do token do CLOB (o id de `clobTokenIds`, nunca o conditionId) entre `ini` e `fim`. A API aceita
        `startTs`/`endTs` OU `interval`, e `fidelity` em minutos; a 1ª rodada real deu HTTP 400 no 1º jeito, então há
        jeitos de reserva (`HIST_JEITOS`), e o que funcionou fica guardado (`est.histJeito`). Os pontos fora de
        [ini, fim] saem aqui. None se nenhum jeito respondeu (ou a fonte já falhou nesta rodada)."""
        if getattr(self, "hist_fora", False):
            return None
        est = self.ctx.est
        ordem = list(range(len(HIST_JEITOS)))
        j0 = est.get("histJeito")
        if isinstance(j0, int) and 0 <= j0 < len(ordem):
            ordem.remove(j0)
            ordem.insert(0, j0)
        r = None
        for j in ordem:
            q = HIST_JEITOS[j](ini // 1000, fim // 1000, fidelidade)
            r = self.pedir("clob", f"/prices-history?market={urllib.parse.quote(str(tok))}&{q}", "clob /prices-history")
            if r is not None:
                if est.get("histJeito") != j:
                    self.log(f"  previsão: prices-history respondeu do jeito {j} ({q.split('&')[0]}…)")
                est["histJeito"] = j
                break
            if self.ultimo_status != 400:
                break
        if r is None:
            self.hist_falhas = getattr(self, "hist_falhas", 0) + 1
            if self.hist_falhas >= 2:  # dois mercados sem histórico: para nesta rodada (o motivo fica no log)
                self.hist_fora = True
                self.sem.setdefault("clob", "o histórico de preços (prices-history) não respondeu em nenhum jeito")
            return None
        self.hist_falhas = 0
        pts = []
        for x in self.lista(r, "history", "data"):
            if isinstance(x, dict):
                t, p = ms_de(x.get("t")), _f(x.get("p"))
            elif isinstance(x, (list, tuple)) and len(x) >= 2:
                t, p = ms_de(x[0]), _f(x[1])
            else:
                continue
            if t and p is not None and ini - HORA <= t <= fim + HORA:
                pts.append((t, p))
        pts.sort()
        return pts


# ---------------------------------------------------------------------------------------------------- entradas
def entrar(R, conta, mk, lado, agora, vid, ev, extra=None, faixa=None, n=None):
    """Compra US$ 20 do lado `lado` de `mk` pelo livro. `faixa` = (mín, máx) do preço médio aceito."""
    chave = f"{mk['id']}:{lado}"
    if chave in conta.pos or f"{mk['id']}:{1 - lado}" in conta.pos:
        return None
    asks = R.livro(mk["toks"][lado])
    r = comprar_no_livro(asks, APOSTA)
    if not r:
        return None
    cotas, preco, melhor = r
    if faixa and not (faixa[0] <= preco <= faixa[1]):
        return None
    info = {"mid": mk["id"], "lado": lado, "nome": mk["nomes"][lado], "q": curta(mk["q"]), "cat": mk["cat"],
            "fim": mk["fim"], "tok": mk["toks"][lado], **(extra or {})}
    p = conta.comprar(chave, info, cotas, preco, melhor, agora, mk.get("taxaBps") or 0)
    if p and (n is None or n[0] < MAX_EVENTOS_RODADA):
        ev.add(agora, "entrou", f"Comprou “{mk['nomes'][lado]}” a {cent(preco)} centavos em “{curta(mk['q'], 70)}” "
                                f"({moeda_br(APOSTA)}).", vid)
        if n is not None:
            n[0] += 1
    return p


def candidatos_fav(abertos, agora, limiar):
    out = []
    for mk in abertos:
        if not mk["fim"] or not (agora < mk["fim"] <= agora + FAV_DIAS * DIA):
            continue
        if mk["vol24"] < VOL24_MIN or mk["liq"] < LIQ_MIN:
            continue
        for lado in (0, 1):
            a = ask_lado(mk, lado)
            if a is not None and limiar <= a <= FAV_MAX:
                out.append((mk["fim"], mk, lado))
    out.sort(key=lambda x: (x[0], -x[1]["vol24"]))
    return [(mk, lado) for _, mk, lado in out]


def candidatos_az(abertos, agora):
    out = []
    for mk in abertos:
        if not mk["fim"] or not (agora < mk["fim"] <= agora + AZ_DIAS * DIA):
            continue
        if mk["vol24"] < VOL24_MIN or mk["liq"] < LIQ_MIN:
            continue
        for lado in (0, 1):
            a = ask_lado(mk, lado)
            if a is not None and AZ_MIN <= a <= AZ_MAX:
                out.append((-mk["vol24"], mk, lado))
    out.sort(key=lambda x: x[0])
    return [(mk, lado) for _, mk, lado in out]


# ---------------------------------------------------------------------------------------------------- outras casas
def kalshi_mercados(R):
    out, cursor = [], ""
    for _ in range(KALSHI_PAGINAS):
        if not R.tempo(100):
            break
        r = R.pedir("kalshi", f"/markets?status=open&limit=1000&mve_filter=exclude{('&cursor=' + urllib.parse.quote(cursor)) if cursor else ''}",
                    "kalshi /markets", "kalshi")
        if r is None:
            return None
        for m in R.lista(r, "markets"):
            if not isinstance(m, dict):
                continue
            bid = _f(m.get("yes_bid_dollars"))
            ask = _f(m.get("yes_ask_dollars"))
            if bid is None and _f(m.get("yes_bid")) is not None:
                bid = _f(m.get("yes_bid")) / 100
            if ask is None and _f(m.get("yes_ask")) is not None:
                ask = _f(m.get("yes_ask")) / 100
            if not bid or not ask or ask - bid > DIF_SPREAD_MAX or not (0 < bid < ask < 1):
                continue
            titulo = str(m.get("title") or "")
            sub = str(m.get("yes_sub_title") or m.get("subtitle") or "")
            q = titulo if not sub or sub.lower() in titulo.lower() else f"{titulo} {sub}"
            out.append({"casa": "Kalshi", "q": q, "p": (bid + ask) / 2, "fim": ms_de(m.get("close_time") or m.get("expiration_time")),
                        "id": str(m.get("ticker") or "")})
        cursor = (r or {}).get("cursor") if isinstance(r, dict) else ""
        if not cursor:
            break
    return out


def manifold_mercados(R, perguntas):
    out, falhou = [], 0
    for q in perguntas[:MANIFOLD_BUSCAS]:
        if not R.tempo(90) or falhou >= 3:
            break
        # a busca casa TODAS as palavras: com 5 ela voltava vazia na 1ª rodada real; 3 palavras distintivas e, sem nada, 2
        palavras = [w for w in sorted(_palavras(q)[0], key=len, reverse=True) if not w.isdigit()]
        achou = []
        for n in (3, 2):
            termo = " ".join(palavras[:n])
            if not termo:
                break
            r = R.pedir("manifold", f"/search-markets?term={urllib.parse.quote(termo)}&filter=open&contractType=BINARY"
                                    f"&sort=score&limit=10", "manifold /search-markets", "manifold")
            if r is None:
                falhou += 1
                break
            achou = R.lista(r, "markets", "data")
            if achou or not R.tempo(90):
                break
        for m in achou:
            if not isinstance(m, dict) or m.get("isResolved") or str(m.get("outcomeType") or "BINARY") != "BINARY":
                continue
            if (_f(m.get("uniqueBettorCount"), 0) or 0) < MANIFOLD_MIN_APOSTADORES:
                continue
            p = _f(m.get("probability"))
            if p is None or not (0 < p < 1):
                continue
            out.append({"casa": "Manifold", "q": str(m.get("question") or ""), "p": p, "fim": ms_de(m.get("closeTime")),
                        "id": str(m.get("id") or "")})
    return out if (out or falhou < 3) else None


def pares_de(abertos, outros):
    """Cada mercado da Polymarket com o melhor par da outra casa (só os casamentos seguros; um par por mercado)."""
    pares = []
    usados = set()
    for mk in abertos:
        melhor = None
        for o in outros:
            if o["id"] in usados:
                continue
            nota = casar(mk["q"], mk["fimPrevisto"] or mk["fim"], o["q"], o["fim"])
            if nota and (not melhor or nota > melhor[0]):
                melhor = (nota, o)
        if melhor:
            usados.add(melhor[1]["id"])
            pares.append((mk, melhor[1], melhor[0]))
    return pares


# ---------------------------------------------------------------------------------------------------- seguir
def ranking(R, agora):
    """O ranking da semana anterior, montado pelas negociações públicas (o `/v1/leaderboard` da Data API e o `lb-api`
    responderam HTTP 410, aposentados, na 1ª rodada real): os `RANK_MERCADOS` mercados de maior volume resolvidos de
    segunda a domingo da semana passada (Gamma), as negociações de cada um (`/trades?market=<conditionId>`) e, por
    carteira, o resultado se ficou até a resolução: compra = cotas × (pagamento − preço), venda = cotas × (preço −
    pagamento). Devolve ([(carteira, resultado, negócios)], o número de mercados lidos, o motivo se ficou vazio)."""
    seg_ = ms_de(semana_de(agora) + "T03:00:00Z")
    de, ate = seg_ - SEMANA_MS, seg_
    r = R.pedir("gamma", f"/markets?closed=true&end_date_min={iso(de)}&end_date_max={iso(ate)}&volume_num_min=10000"
                         f"&order=volumeNum&ascending=false&limit={RANK_MERCADOS * 2}", "gamma /markets (semana passada)", "gamma")
    if r is None:
        return [], 0, "os mercados da semana passada não vieram"
    mercados = [mk for mk in (mercado_de(m) for m in R.lista(r, "data", "markets"))
                if mk and mk["cond"] and mk["resultado"] in (0.0, 1.0)]
    mercados.sort(key=lambda mk: -mk["vol"])
    soma, conta, lidos, pediu_chave = {}, {}, 0, None
    for mk in mercados[:RANK_MERCADOS]:
        if not R.tempo(80):
            break
        t = R.pedir("pmdata", f"{PMDATA}/trades?market={mk['cond']}&limit=500&takerOnly=false", "pmdata /trades (mercado)", "pmdata")
        if t is None:
            if R.ultimo_status in (401, 403):
                pediu_chave = R.ultimo_status
                break
            continue
        lidos += 1
        for x in R.lista(t, "data", "trades"):
            if not isinstance(x, dict):
                continue
            end = str(x.get("proxyWallet") or x.get("user") or "").lower()
            asset = str(x.get("asset") or x.get("asset_id") or "")
            preco, tam = _f(x.get("price")), _f(x.get("size"), 0.0)
            if not re.fullmatch(r"0x[0-9a-f]{40}", end) or preco is None or not tam:
                continue
            k = mk["toks"].index(asset) if asset in mk["toks"] else _f(x.get("outcomeIndex"))
            if k not in (0, 1, 0.0, 1.0):
                continue
            paga = mk["resultado"] if int(k) == 0 else 1 - mk["resultado"]
            lado = str(x.get("side") or "").upper()
            res = tam * (paga - preco) if lado == "BUY" else tam * (preco - paga) if lado == "SELL" else 0.0
            soma[end] = soma.get(end, 0.0) + res
            conta[end] = conta.get(end, 0) + 1
    out = [(e, round(v, 2), conta[e]) for e, v in soma.items() if conta[e] >= RANK_MIN_NEGOCIOS]
    out.sort(key=lambda x: -x[1])
    motivo = None
    if not mercados:
        motivo = "nenhum mercado resolvido na semana passada com volume"
    elif not lidos and pediu_chave:
        motivo = f"a Data API v2 pede chave (HTTP {pediu_chave}); o seguir fica parado"
    elif not lidos:
        motivo = "as negociações públicas (Data API v2 /trades) não vieram"
    elif not out:
        motivo = "nenhuma carteira com negócios suficientes nos mercados da semana passada"
    return out, lidos, motivo


def preco_em(pts, t):
    """O 1º preço do histórico em `t` ou depois (até 2 h); sem ele, o último antes."""
    depois = [p for tt, p in pts if t <= tt <= t + 2 * HORA]
    if depois:
        return depois[0]
    antes = [p for tt, p in pts if tt <= t]
    return antes[-1] if antes else None


# ---------------------------------------------------------------------------------------------------- calibração
def pontos_diarios(pts, fim):
    """O preço do "Sim" k dias antes do fim (k = 0…30), em milésimos; -1 = o mercado ainda não tinha preço."""
    out = []
    for k in range(31):
        t = fim - k * DIA
        antes = [p for tt, p in pts if tt <= t]
        out.append(int(round(antes[-1] * 1000)) if antes else -1)
    return out


def um_por_evento(merc):
    """Um mercado por evento (o de maior volume): as linhas de um mesmo jogo (spreads, mais/menos, empate) e os
    candidatos de um evento de vários resultados (neg_risk) andam juntos, e 10 linhas de uma zebra só pareciam 10
    acertos do azarão (2ª rodada real, 09/11/2026: Brier 0,27 com 80 mercados de poucos jogos)."""
    por = {}
    for k, m in merc.items():
        ev = m.get("ev") or k
        if ev not in por or m.get("vol", 0) > merc[por[ev]].get("vol", 0):
            por[ev] = k
    return {k: merc[k] for k in por.values()}


def conferir_lado(merc):
    """O último preço do histórico (já depois do fim) concorda com o resultado? Perto de 100% = o lado lido é o
    mesmo do resultado; bem abaixo, sinal de lado trocado. None com menos de 10 mercados."""
    xs = [m for m in merc.values() if m.get("ult") is not None and m["ult"] >= 0 and abs(m["ult"] - 500) >= 200]
    if len(xs) < 10:
        return None
    ok = sum(1 for m in xs if (m["ult"] > 500) == (m["o"] == 1))
    return {"n": len(xs), "concordam": ok, "fracao": round(ok / len(xs), 4)}


def tabela_calibracao(merc):
    """As faixas por horizonte (frequência real × preço, Wilson) e o Brier por categoria."""
    out = []
    for hid, nome, k in HORIZONTES:
        fx = [{"de": i / 10, "ate": (i + 1) / 10, "n": 0, "soma": 0.0, "sim": 0} for i in range(10)]
        brier, cat = [], {}
        for m in merc.values():
            o = m.get("o")
            if o not in (0, 1):
                continue
            p = m["pts"][k] if len(m["pts"]) > k else -1
            if p is None or p < 0:
                continue
            p /= 1000
            b = fx[min(9, int(p * 10))]
            b["n"] += 1
            b["soma"] += p
            b["sim"] += o
            e = (p - o) ** 2
            brier.append(e)
            c = cat.setdefault(m.get("cat") or "Outros", [0, 0.0])
            c[0] += 1
            c[1] += e
        faixas = []
        for b in fx:
            faixas.append({"de": b["de"], "ate": b["ate"], "n": b["n"],
                           "previsto": round(b["soma"] / b["n"], 4) if b["n"] else None,
                           "real": round(b["sim"] / b["n"], 4) if b["n"] else None,
                           "sim": b["sim"], "ic": wilson(b["sim"], b["n"])})
        out.append({"id": hid, "nome": nome, "dias": k, "n": len(brier),
                    "brier": round(sum(brier) / len(brier), 4) if brier else None, "faixas": faixas,
                    "porCategoria": sorted([{"cat": c, "n": v[0], "brier": round(v[1] / v[0], 4)} for c, v in cat.items()],
                                           key=lambda x: -x["n"])})
    return out


def coletar_calibracao(R, cal, agora, erros):
    """Lê os mercados encerrados novos (e, para trás, até 180 dias) e guarda o preço de cada dia antes do fim."""
    if any("ev" not in m for m in (cal.get("mercados") or {}).values()):
        # lidos antes de 10/11/2026, sem o evento nem o último preço: lê de novo (a tabela passou a ser um por evento)
        R.log(f"  previsão: o observatório recomeça ({len(cal.get('mercados') or {})} mercados sem o evento)")
        cal.clear()
    merc = cal.setdefault("mercados", {})
    pulados = cal.setdefault("pulados", [])
    ps = set(pulados)
    limite_velho = agora - CAL_DIAS * DIA
    cal.setdefault("novo", agora - 2 * DIA)      # os encerrados depois disso
    cal.setdefault("velho", cal["novo"])         # e, para trás, até o limite
    feitos, lidos = 0, 0

    def buscar(de, ate, asc):
        r = R.pedir("gamma", f"/markets?closed=true&end_date_min={iso(de)}&end_date_max={iso(ate)}&volume_num_min={int(CAL_VOL_MIN)}"
                             f"&order=endDate&ascending={'true' if asc else 'false'}&limit=100", "gamma /markets (encerrados)", "gamma")
        return None if r is None else [mercado_de(m) for m in R.lista(r, "data", "markets")]

    def processar(mk):
        nonlocal feitos
        if not mk or mk["id"] in merc or mk["id"] in ps:
            return True
        dur = (mk["fim"] or 0) - (mk["ini"] or mk["fim"] or 0)
        if not mk["fim"] or mk["resultado"] not in (0.0, 1.0) or dur < CAL_DURACAO_MIN or mk["vol"] < CAL_VOL_MIN:
            pulados.append(mk["id"])
            ps.add(mk["id"])
            return True
        if feitos >= CAL_POR_RODADA or not R.tempo(45):
            return False
        feitos += 1
        pts = R.historico(mk["toks"][0], mk["fim"] - 31 * DIA, max(mk["fim"], mk.get("fechouEm") or 0) + 2 * HORA, 720)
        if pts is None:
            return False
        if not pts:
            pulados.append(mk["id"])
            ps.add(mk["id"])
            return True
        merc[mk["id"]] = {"fim": mk["fim"], "o": int(mk["resultado"]), "cat": mk["cat"], "q": curta(mk["q"], 80),
                          "vol": round(mk["vol"]), "pts": pontos_diarios(pts, mk["fim"]), "ev": mk["evento"] or mk["id"],
                          "ult": int(round(pts[-1][1] * 1000))}
        return True

    # os novos (do mais antigo ao mais novo)
    if R.tempo(60):
        xs = buscar(cal["novo"], agora, True)
        if xs is not None:
            lidos += len(xs)
            ult = cal["novo"]
            completo = True
            for mk in sorted([x for x in xs if x and x["fim"]], key=lambda x: x["fim"]):
                if not processar(mk):
                    completo = False
                    break
                ult = max(ult, mk["fim"])
            cal["novo"] = agora if completo and len(xs) < 100 else ult
    # para trás
    if cal["velho"] > limite_velho and R.tempo(60) and feitos < CAL_POR_RODADA:
        xs = buscar(limite_velho, cal["velho"], False)
        if xs is not None:
            lidos += len(xs)
            ult = cal["velho"]
            completo = True
            for mk in sorted([x for x in xs if x and x["fim"]], key=lambda x: -x["fim"]):
                if not processar(mk):
                    completo = False
                    break
                ult = min(ult, mk["fim"])
            cal["velho"] = limite_velho if completo and len(xs) < 100 else ult
    # o limite de tamanho: fica com os mais novos
    for k in sorted(merc, key=lambda k: merc[k]["fim"])[:-CAL_MAX] if len(merc) > CAL_MAX else []:
        del merc[k]
    for k in [k for k, m in merc.items() if m["fim"] < limite_velho]:
        del merc[k]
    del pulados[:-CAL_PULADOS_MAX]
    return {"lidosAgora": feitos, "listados": lidos,
            "alcancouDias": round((agora - cal["velho"]) / DIA, 1), "meta": CAL_DIAS}


# ---------------------------------------------------------------------------------------------------- passado
def simular_passado(merc, regra, limiar, cdi, cdi_ano):
    """O teste no passado (aproximado) de uma regra com os mercados encerrados do observatório."""
    entradas = []
    for mid, m in merc.items():
        pts = m["pts"]
        ks = range(FAV_DIAS, 0, -1) if regra == "fav" else range(AZ_DIAS, 0, -1)
        for k in ks:
            if k >= len(pts) or pts[k] < 0:
                continue
            p = pts[k] / 1000
            lado = None
            if regra == "fav":
                if limiar <= p <= FAV_MAX:
                    lado = 0
                elif limiar <= 1 - p <= FAV_MAX:
                    lado = 1
            else:
                if AZ_MIN <= p <= AZ_MAX:
                    lado = 0
                elif AZ_MIN <= 1 - p <= AZ_MAX:
                    lado = 1
            if lado is not None:
                pl = p if lado == 0 else 1 - p
                entradas.append((m["fim"] - k * DIA, mid, lado, min(0.999, pl + SPREAD_HIST), k))
                break
    if not entradas:
        return None
    entradas.sort()
    ini = entradas[0][0]
    fim_tot = max(merc[e[1]]["fim"] for e in entradas)
    c = Carteira(ini)
    dia = ini
    pend = list(entradas)
    while dia <= fim_tot + DIA:
        # resolve o que acabou até hoje
        for ch in [ch for ch, p in c.pos.items() if merc[p["mid"]]["fim"] <= dia]:
            p = c.pos[ch]
            o = merc[p["mid"]]["o"]
            c.fechar(ch, float(o if p["lado"] == 0 else 1 - o), dia)
        while pend and pend[0][0] <= dia:
            t, mid, lado, preco, _ = pend.pop(0)
            if c.caixa >= APOSTA:
                c.comprar(f"{mid}:{lado}", {"mid": mid, "lado": lado, "cat": merc[mid]["cat"]}, APOSTA / preco, preco, preco - SPREAD_HIST, t, 0)
        marcas = {}
        for ch, p in c.pos.items():
            m = merc[p["mid"]]
            k = int(round((m["fim"] - dia) / DIA))
            v = m["pts"][k] if 0 <= k < len(m["pts"]) and m["pts"][k] >= 0 else None
            if v is not None:
                pv = v / 1000
                p["ult"] = pv if p["lado"] == 0 else 1 - pv
            marcas[ch] = p["ult"]
        c.curva.marcar(dia, c.valor(marcas))
        dia += DIA
    r = c.curva.resumo(de=dia_de(ini), ate=dia_de(fim_tot), aproximado=True,
                       nota=(f"Aproximado: {len(merc)} mercados encerrados dos últimos {CAL_DIAS} dias que o observatório "
                             f"já leu, o preço de cada dia (histórico de 12 em 12 h) e 1 centavo de deslize; sem taxas."))
    r["extra"] = c.extra({})
    try:
        from robos import janelas
        r["janelas"] = janelas(r, cdi, cdi_ano, JANELA_DIAS, JANELA_PASSO)
    except Exception:  # noqa: BLE001
        r["janelas"] = None
    return r


# ---------------------------------------------------------------------------------------------------- réguas
def indice_cdi(cdi, de_ms, ate_ms, cdi_ano):
    ultimo, primeiro = (max(cdi), min(cdi)) if cdi else ("", "")
    diaria = (1 + cdi_ano) ** (1 / 252) - 1
    d, fim, v = dt.date.fromisoformat(dia_de(de_ms)), dt.date.fromisoformat(dia_de(ate_ms)), 1.0
    while d < fim:
        v *= 1 + _cdi_do_dia(cdi, d, primeiro, ultimo, diaria)
        d += dt.timedelta(days=1)
    return v


# ---------------------------------------------------------------------------------------------------- rodar
def rodar(ctx):
    est, agora = ctx.est, ctx.agora
    fonte = rede.fonte_de(ctx, "gamma")
    antes = getattr(fonte, "pedidos", 0)
    R = Rodada(ctx, fonte, min(ORCAMENTO_S, max(30.0, ctx.restante() - 60)))
    ev = Eventos(est.get("eventos"))
    cdi = (ctx.ref or {}).get("cdi") or {}
    cdi_ano = cdi_ano_da_serie(cdi, 0.149)
    contas = {}
    for v in VERSOES:
        c = Carteira.de_json((est.get("contas") or {}).get(v["id"]))
        if c is None:
            c = Carteira(agora)
            if est.get("contas"):
                ev.add(agora, "aviso", f"Versão nova: {v['nome']} começa hoje.", v["id"])
        contas[v["id"]] = c
    if not est.get("contas"):
        ev.add(agora, "aviso", "Começou o teste dos mercados de previsão, só no papel (Polymarket e Kalshi estão "
                               "bloqueadas no Brasil).", None)

    # 1. os abertos e as posições de cada versão
    abertos = R.abertos()
    por_id = {mk["id"]: mk for mk in abertos}
    precisa = {p["mid"] for c in contas.values() for p in c.pos.values()}
    faltam = [m for m in precisa if m not in por_id]
    if faltam and R.tempo(60):
        por_id.update(R.por_ids(faltam))
    marcas_glob = {}
    for vid, c in contas.items():
        for ch in list(c.pos):
            p = c.pos[ch]
            mk = por_id.get(p["mid"])
            if not mk:
                continue
            if mk["resultado"] is not None:
                pr = mk["resultado"] if p["lado"] == 0 else 1 - mk["resultado"]
                _, pnl = c.fechar(ch, pr, agora)
                if p.get("de"):
                    sc = est.setdefault("seguir", {}).setdefault("contas", {}).setdefault(p["de"], {"copiadas": 0, "ganhas": 0, "fechadas": 0})
                    sc["fechadas"] += 1
                    sc["ganhas"] += 1 if pnl > 0 else 0
                ev.add(agora, "ganhou" if pnl > 0 else "perdeu" if pnl < 0 else "anulou",
                       f"“{curta(p['q'], 70)}” terminou {'a favor' if pr > 0.5 else 'contra' if pr < 0.5 else 'anulado'}: "
                       f"“{p['nome']}” {'pagou US$ 1 por cota' if pr > 0.5 else 'não pagou' if pr < 0.5 else 'devolveu 50 centavos'} "
                       f"({moeda_br(pnl)}).", vid)
            else:
                p["ult"] = round(marca(mk, p["lado"]), 5)
                marcas_glob[ch] = p["ult"]

    n_ev = [0]
    # 2. favorito perto do fim e azarão
    if abertos:
        for vid, lim in (("fav90", 0.90), ("fav95", 0.95)):
            novas = 0
            for mk, lado in candidatos_fav(abertos, agora, lim):
                if novas >= MAX_NOVAS or not R.tempo(150) or contas[vid].caixa < APOSTA:
                    break
                if entrar(R, contas[vid], mk, lado, agora, vid, ev, faixa=(lim, FAV_MAX), n=n_ev):
                    novas += 1
        novas = 0
        for mk, lado in candidatos_az(abertos, agora):
            if novas >= MAX_NOVAS or not R.tempo(150) or contas["azarao"].caixa < APOSTA:
                break
            if entrar(R, contas["azarao"], mk, lado, agora, "azarao", ev, faixa=(AZ_MIN, AZ_MAX), n=n_ev):
                novas += 1

    # 3. diferença entre casas
    casas = {"pares": [], "fontes": {}}
    if abertos:
        base = [mk for mk in abertos if mk["fim"] and mk["fim"] > agora + DIA]
        kal = kalshi_mercados(R) if R.tempo(120) else None
        casas["fontes"]["Kalshi"] = {"ok": kal is not None, "mercados": len(kal or []),
                                     "motivo": None if kal is not None else R.sem.get("kalshi", "sem tempo na rodada")}
        sem_esporte = [mk for mk in base if mk["cat"] != "Esportes"]
        man = manifold_mercados(R, [mk["q"] for mk in sorted(sem_esporte, key=lambda x: -x["vol24"])]) if R.tempo(110) else None
        casas["fontes"]["Manifold"] = {"ok": man is not None, "mercados": len(man or []),
                                       "motivo": None if man is not None else R.sem.get("manifold", "sem tempo na rodada")}
        for vid, outros in (("difK", kal or []), ("difM", man or [])):
            novas = 0
            for mk, o, nota in pares_de(base, outros):
                ay, an = ask_lado(mk, 0), ask_lado(mk, 1)
                lado = None
                if ay is not None and o["p"] - ay >= DIF_MIN:
                    lado = 0
                elif an is not None and (1 - o["p"]) - an >= DIF_MIN:
                    lado = 1
                casas["pares"].append({"pergunta": curta(mk["q"]), "outra": o["casa"], "outraPergunta": curta(o["q"]),
                                       "polymarket": round(mk["precos"][0], 4) if mk["precos"][0] is not None else None,
                                       "outraPreco": round(o["p"], 4), "diferenca": round(o["p"] - (mk["precos"][0] or 0), 4),
                                       "nota": nota, "fim": mk["fim"], "cat": mk["cat"], "comprou": None})
                ja = [ch for ch in contas[vid].pos if ch.startswith(mk["id"] + ":")]
                if ja:
                    casas["pares"][-1]["comprou"] = contas[vid].pos[ja[0]]["nome"]
                if lado is None or ja or novas >= MAX_NOVAS or not R.tempo(80) or contas[vid].caixa < APOSTA:
                    continue
                ref = o["p"] if lado == 0 else 1 - o["p"]
                pos = entrar(R, contas[vid], mk, lado, agora, vid, ev, faixa=(0.01, ref - DIF_MIN),
                             extra={"outra": o["casa"], "outraPreco": round(ref, 4)}, n=n_ev)
                if pos:
                    novas += 1
                    casas["pares"][-1]["comprou"] = mk["nomes"][lado]
        casas["pares"].sort(key=lambda x: -abs(x["diferenca"]))
        casas["pares"] = casas["pares"][:30]
        casas["regra"] = {"diferenca": DIF_MIN, "fimDias": DIF_FIM_DIAS, "palavras": DIF_JACCARD,
                          "manifoldApostadores": MANIFOLD_MIN_APOSTADORES}

    # 4. seguir os melhores
    seg = est.setdefault("seguir", {})
    for k, v0 in (("semana", None), ("carteiras", []), ("cursor", {}), ("contas", {})):
        seg.setdefault(k, v0)
    sem_atual = semana_de(agora)
    if seg.get("semana") != sem_atual and R.tempo(90):
        rk, lidos, motivo = ranking(R, agora)
        if rk and any(pnl > 0 for _, pnl, _ in rk):
            antigas = set(seg.get("carteiras") or [])
            novas = [e for e, pnl, _ in rk if pnl > 0][:SEG_N]
            seg.update({"semana": sem_atual, "carteiras": novas, "escolhidaEm": agora, "mercadosLidos": lidos,
                        "cursor": {e: agora for e in novas}, "contas": {e: (seg.get("contas") or {}).get(e, {"copiadas": 0, "ganhas": 0, "fechadas": 0}) for e in novas}})
            entraram, sairam = len(set(novas) - antigas), len(antigas - set(novas))
            ev.add(agora, "trocou", f"Escolheu as {len(novas)} carteiras de maior lucro da semana passada (nas negociações de "
                                    f"{lidos} mercados resolvidos) para copiar nesta ({entraram} novas, {sairam} saíram).", "seguir")
        else:
            R.sem.setdefault("ranking", motivo or "nenhuma carteira com lucro na semana passada")
            seg["motivo"] = motivo or "nenhuma carteira com lucro na semana passada"
    copiadas = 0
    conta_s = contas["seguir"]
    seg["porDia"] = {k: n for k, n in (seg.get("porDia") or {}).items() if k.split("|")[-1] >= dia_de(agora - 3 * DIA)}
    for end in seg.get("carteiras") or []:
        if not R.tempo(70) or copiadas >= SEG_MAX_RODADA:
            break
        r = R.pedir("pmdata", f"{PMDATA}/trades?user={end}&limit=100", "pmdata /trades", "pmdata")
        if r is None:
            continue
        cur = seg["cursor"].get(end, agora)
        trs = []
        for x in R.lista(r, "data", "trades"):
            if not isinstance(x, dict):
                continue
            t = ms_de(x.get("timestamp") or x.get("time"))
            if not t or t <= cur or t > agora:
                continue
            trs.append((t, x))
        trs.sort(key=lambda y: y[0])
        for t, x in trs:
            if copiadas >= SEG_MAX_RODADA or not R.tempo(60):
                break
            lado_txt, asset = str(x.get("side") or "").upper(), str(x.get("asset") or x.get("asset_id") or "")
            preco_c, tam = _f(x.get("price")), _f(x.get("size"), 0.0)
            cond = str(x.get("conditionId") or x.get("market") or "")
            if not asset:
                seg["cursor"][end] = t
                continue
            chave_abertas = [ch for ch, p in conta_s.pos.items() if p.get("tok") == asset]
            if lado_txt == "SELL" and chave_abertas:
                ch = chave_abertas[0]
                if conta_s.pos[ch].get("de") != end:
                    seg["cursor"][end] = t
                    continue
                pts = R.historico(asset, t, t + 3 * HORA, 1)
                px = preco_em(pts or [], t + SEG_ATRASO) or preco_c
                if px is not None:
                    pv = max(0.001, px - SEG_DESLIZE)
                    p, pnl = conta_s.fechar(ch, pv, agora, resolveu=False)
                    sc = seg["contas"].setdefault(end, {"copiadas": 0, "ganhas": 0, "fechadas": 0})
                    sc["fechadas"] += 1
                    sc["ganhas"] += 1 if pnl > 0 else 0
                    if n_ev[0] < MAX_EVENTOS_RODADA:
                        ev.add(agora, "saiu", f"A carteira {carteira_curta(end)} vendeu: vendemos “{p['nome']}” em "
                                              f"“{curta(p['q'], 60)}” a {cent(pv)} centavos ({moeda_br(pnl)}).", "seguir")
                        n_ev[0] += 1
                    copiadas += 1
            elif (lado_txt == "BUY" and not chave_abertas and (tam or 0) * (preco_c or 0) >= SEG_MIN_US and conta_s.caixa >= APOSTA
                  and seg.setdefault("porDia", {}).get(f"{end}|{dia_de(t)}", 0) < SEG_MAX_DIA):
                mk = R.por_condicao(cond) if cond else None
                if mk and mk["aberto"] and asset in mk["toks"]:
                    lado = mk["toks"].index(asset)
                    pts = R.historico(asset, t, t + 3 * HORA, 1)
                    px = preco_em(pts or [], t + SEG_ATRASO) or preco_c
                    copiadas += 1
                    if px is not None and 0.01 <= px <= 0.98:
                        pe = min(0.999, px + SEG_DESLIZE)
                        info = {"mid": mk["id"], "lado": lado, "nome": mk["nomes"][lado], "q": curta(mk["q"]), "cat": mk["cat"],
                                "fim": mk["fim"], "tok": asset, "de": end, "carteira": carteira_curta(end)}
                        if conta_s.comprar(f"{mk['id']}:{lado}", info, APOSTA / pe, pe, px, agora, mk.get("taxaBps") or 0):
                            por_id[mk["id"]] = mk
                            marcas_glob[f"{mk['id']}:{lado}"] = round(marca(mk, lado), 5)
                            conta_s.pos[f"{mk['id']}:{lado}"]["ult"] = marcas_glob[f"{mk['id']}:{lado}"]
                            sc = seg["contas"].setdefault(end, {"copiadas": 0, "ganhas": 0, "fechadas": 0})
                            sc["copiadas"] += 1
                            seg["porDia"][f"{end}|{dia_de(t)}"] = seg["porDia"].get(f"{end}|{dia_de(t)}", 0) + 1
                            if n_ev[0] < MAX_EVENTOS_RODADA:
                                ev.add(agora, "entrou", f"Copiou a carteira {carteira_curta(end)}: “{mk['nomes'][lado]}” a "
                                                        f"{cent(pe)} centavos em “{curta(mk['q'], 60)}”.", "seguir")
                                n_ev[0] += 1
            seg["cursor"][end] = t

    # 5. réguas
    cc = contas["cdi"]
    cc.caixa = CAPITAL * indice_cdi(cdi, cc.curva.inicio, agora, cdi_ano)
    contas["usdc"].caixa = CAPITAL

    # 6. observatório de calibração (o que sobrar do tempo)
    cal = est.setdefault("cal", {})
    andamento = coletar_calibracao(R, cal, agora, R.erros) if R.tempo(40) else {"lidosAgora": 0}
    merc = cal.get("mercados") or {}
    unicos = um_por_evento(merc)
    lado = conferir_lado(merc)
    if lado and lado["fracao"] < 0.8:
        R.log(f"  previsão: AVISO: só {lado['concordam']} de {lado['n']} últimos preços concordam com o resultado (lado trocado?)")
    calib = {"mercados": len(merc), "eventos": len(unicos), "conferenciaLado": lado, "horizontes": tabela_calibracao(unicos),
             "desde": min((m["fim"] for m in merc.values()), default=None),
             "ate": max((m["fim"] for m in merc.values()), default=None),
             "porCategoria": {}, "andamento": andamento,
             "criterio": {"volumeMin": CAL_VOL_MIN, "duracaoMinDias": CAL_DURACAO_MIN // DIA, "dias": CAL_DIAS},
             "nota": "O preço do 1º lado (o “Sim”, ou o 1º nome nos mercados de times e pessoas; histórico de 12 em 12 h) "
                     "antes do fim × o que aconteceu, nos mercados de dois lados encerrados com resultado (os anulados "
                     "ficam de fora), um por evento (o de maior volume): as linhas de um mesmo jogo andam juntas."}
    for m in merc.values():
        calib["porCategoria"][m["cat"]] = calib["porCategoria"].get(m["cat"], 0) + 1
    calib["porCategoria"] = dict(sorted(calib["porCategoria"].items(), key=lambda x: -x[1]))
    vies = [f for f in calib["horizontes"][0]["faixas"] if f["n"]]
    if vies:
        az = calib["horizontes"][0]["faixas"][0]
        calib["azarao"] = {"previsto": az["previsto"], "real": az["real"], "n": az["n"], "ic": az["ic"]}

    # 7. as curvas
    versoes = []
    for v in VERSOES:
        c = contas[v["id"]]
        mc = {ch: p.get("ult", p["ent"]) for ch, p in c.pos.items()}
        c.curva.marcar(agora, c.valor(mc))
        ao = c.curva.resumo()
        if v["id"] not in ("cdi", "usdc"):
            ao["extra"] = c.extra(mc)
        else:
            ao.pop("extra", None)
        if v.get("aproximado"):
            ao["aproximado"] = True
        out = {k: v[k] for k in ("id", "nome", "frase", "risco", "grupo")}
        out["alav"] = 1
        if v.get("aproximado"):
            out["aproximado"] = True
        out["aoVivo"] = ao
        out["historico"] = None
        if v["id"] in COM_PASSADO and merc:
            regra, lim = COM_PASSADO[v["id"]]
            try:
                out["historico"] = simular_passado(unicos, regra, lim, cdi, cdi_ano)
            except (KeyError, ValueError, ZeroDivisionError) as e:
                R.erros.append(f"passado {v['id']}: {e}")
        if v["id"] == "seguir":
            out["soAoVivo"] = True
        versoes.append(out)
        est.setdefault("contas", {})[v["id"]] = c.para_json()

    itens = []
    for vid in IDS:
        for p in contas[vid].pos.values():
            it = {"versao": vid, "mercado": p["mid"], "pergunta": p["q"], "lado": p["nome"], "preco": p["ent"],
                  "agora": p.get("ult", p["ent"]), "valor": APOSTA, "em": p["em"], "fim": p.get("fim"), "cat": p.get("cat")}
            if p.get("outra"):
                it["outra"], it["outraPreco"] = p["outra"], p.get("outraPreco")
            if p.get("carteira"):
                it["carteira"] = p["carteira"]
            itens.append(it)
    itens.sort(key=lambda x: (x.get("fim") or 9e15))
    seguir = {"semana": seg.get("semana"), "escolhidaEm": seg.get("escolhidaEm"), "mercadosLidos": seg.get("mercadosLidos"),
              "motivo": None if seg.get("carteiras") else (seg.get("motivo") or R.sem.get("ranking")),
              "fonte": "negociações públicas dos mercados resolvidos na semana anterior",
              "proxima": ms_de(semana_de(agora) + "T03:00:00Z") + SEMANA_MS,
              "carteiras": [{"carteira": carteira_curta(e), **(seg.get("contas") or {}).get(e, {}),
                             "abertas": sum(1 for p in conta_s.pos.values() if p.get("de") == e)}
                            for e in seg.get("carteiras") or []],
              "regra": {"n": SEG_N, "atrasoMin": SEG_ATRASO // 60_000, "deslize": SEG_DESLIZE, "minimo": SEG_MIN_US}}
    est["eventos"] = ev.para_json()
    est["estruturas"] = sorted(R.vistas)
    rede.somar_pedidos(ctx, fonte, antes)
    sem_dados = [{"fonte": k, "motivo": v} for k, v in R.sem.items()]
    if not abertos and "gamma" not in R.sem:
        sem_dados.append({"fonte": "gamma", "motivo": "nenhum mercado aberto veio"})
    return {
        "frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": PADRAO, "versoes": versoes,
        "eventos": ev.para_json(), "itens": itens[:ITENS_MAX], "avisos": AVISOS,
        "calibracao": calib, "casas": casas, "seguir": seguir, "semDados": sem_dados,
        "abertos": {"lidos": len(abertos), "porCategoria": _contar_cat(abertos)},
        "config": {"frequencia": "a cada 6 h", "moeda": "US$", "aposta": APOSTA, "bloqueio": "abril de 2026",
                   "soObservacao": True,
                   "fav": {"dias": FAV_DIAS, "limiares": [0.90, 0.95], "max": FAV_MAX},
                   "azarao": {"min": AZ_MIN, "max": AZ_MAX, "dias": AZ_DIAS},
                   "dif": {"min": DIF_MIN, "fimDias": DIF_FIM_DIAS, "palavras": DIF_JACCARD},
                   "filtros": {"liquidezMin": LIQ_MIN, "volume24hMin": VOL24_MIN, "maxNovas": MAX_NOVAS},
                   "taxas": {"formula": "base × min(preço, 1 − preço) × cotas", "fonte": "takerBaseFee do mercado (conferir)"},
                   "janelas": {"dias": JANELA_DIAS, "passo": JANELA_PASSO}},
        "erros": R.erros,
    }


def _contar_cat(xs):
    out = {}
    for mk in xs:
        out[mk["cat"]] = out.get(mk["cat"], 0) + 1
    return dict(sorted(out.items(), key=lambda x: -x[1]))
