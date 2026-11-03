"""Cofres da Hyperliquid NO PAPEL (plano: docs/plano-testes-mercado-2.md, seção 1; formato: tools/papel/FORMATO.md).

Um cofre é uma conta que negocia pelos depositantes: o HLP (da própria corretora: faz mercado e liquidações, sem
comissão) e os cofres de traders (o líder fica com 10% do lucro de quem sai). Aqui o depósito é fictício (US$ 1.000 por
versão) e nada é enviado à corretora: só leitura da API pública.

Simulação
- O depósito segue o RETORNO POR COTA do cofre, não o patrimônio dele (que sobe e desce com os depósitos e saques dos
  outros): entre dois pontos seguidos de `vaultDetails`, r = Δlucro ÷ patrimônio anterior (pnlHistory e
  accountValueHistory alinhados pelo horário). Cada cofre acompanhado tem uma "cota" (índice que começa em 1) guardada
  no estado; uma posição é quantas cotas compramos. A cada rodada a cota anda pelos pontos novos da janela "week"
  (~58 pontos, a cada ~3 h); se a rodada anterior ficou mais longe que a semana, usa "month" e depois "allTime" e
  avisa no log (o trecho que nenhuma janela cobre fica com retorno zero). Um ponto que começa antes do último
  processado conta só a parte depois dele (proporcional ao tempo).
- Comissão: o valor mostrado é o valor das cotas menos comissão do líder × lucro da nossa entrada (como se saísse
  agora); ao sair, a comissão é paga de verdade (entra em `taxas` e em `comissaoPaga`). O HLP não tem.
- Trava: depois de entrar, não dá para sair antes de 4 dias no HLP e 1 dia nos outros; uma saída pedida antes espera.
  Cofre FECHADO devolve o dinheiro na hora (sem trava); cofre que SUMIU da API também sai pelo último valor (aviso).
- Saque maior que `maxWithdrawable` do cofre sai em partes (o resto sai na próxima rodada). Com US$ 1.000 isso quase
  nunca acontece.

Escolha (toda segunda-feira, na 1ª rodada da semana; os escolhidos ficam pelo menos 4 semanas, a não ser que o cofre
feche, pare de aceitar depósitos ou suma): aberto, aceitando depósito, TVL ≥ US$ 100 mil, ≥ 30 dias de vida, líder com
≥ 5% do cofre, lucro (por cota) no mês e no total, pior queda do topo (por cota) ≤ 30%, não ser filho do HLP. A lista
(`stats-data …/vaults`, ~14 MB) é baixada só na escolha e pré-filtra de graça; `vaultDetails` (peso 20) só dos ~40
melhores pelo lucro do mês e dos que já seguimos.

Nota (para ordenar): (0,6 × lucro do mês × 12 + 0,4 × lucro anualizado desde o início) ÷ (pior queda + 5%), com os
lucros limitados a 300% ao ano e um bônus pequeno pelo tamanho (até +40%: 1 + 0,1 × log10(TVL ÷ 100 mil)). É uma
"Calmar" simples: ganha quem rende bem caindo pouco.

Versões: hlp (HLP sozinho), top5 (5 melhores, partes iguais; padrão), top10, top5s (5 melhores saindo de um cofre que
cair 15% do NOSSO topo nele; o dinheiro vai para o próximo da fila na mesma rodada), semana (o melhor da semana passada,
troca toda segunda) e fixos (os que ele fixou em config/cofres-fixos.json, partes iguais). Uma posição sai quando o
cofre deixa a lista da versão; o dinheiro liberado vai, dividido igualmente, para os que entram (sem reequilíbrio
periódico). Cada cofre seguido ou fixado também é um item com conta própria (US$ 1.000 só nele).

Teste no passado (`historico`, refeito a cada 7 dias na escolha): as mesmas regras, dia a dia nos últimos 180 dias,
sobre os cofres que existem HOJE e foram detalhados (viés de sobrevivência; os pontos "allTime" são grossos) →
aproximado.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import os
import re

import hl
from conta import CAPITAL, DIA, FUSO_MS, Curva, Eventos, dia_de, moeda_br, num_br, pct_br

NOME = "Cofres"
VERSAO = 1

AQUI = os.path.dirname(os.path.abspath(__file__))
ARQ_FIXOS = os.path.join(AQUI, "..", "..", "config", "cofres-fixos.json")
HLP = "0xdfc24b077bc1425ad1dea75bcb6f8158e10df303"

# regra da escolha
TVL_MIN = 100_000.0
IDADE_MIN_DIAS = 30
PARTE_LIDER_MIN = 0.05
QUEDA_MAX = 0.30
FICA_MS = 28 * DIA          # o escolhido fica pelo menos 4 semanas
SEGUIR = 10                 # quantos seguimos (a versão dos 10 usa todos)
DETALHAR = 40               # vaultDetails na escolha (os melhores pelo lucro do mês na lista)
MAX_CANDIDATOS = 40
COMISSAO_PADRAO = 0.10
TRAVA_HLP = 4 * DIA
TRAVA = 1 * DIA
STOP = 0.15                 # top5s: sai quando cai 15% do nosso topo no cofre
BAN_MS = 28 * DIA           # top5s: não volta ao cofre de que saiu por 4 semanas
HIST_DIAS = 180
HIST_A_CADA = 7 * DIA
MAX_SAIDOS = 10
TEMPO_MIN_ESCOLHA = 150     # s: menos que isso, a escolha detalha só o que já tem
TEMPO_MIN_HIST = 90         # s: menos que isso, não refaz o teste no passado
R_MAX = 5.0                 # um passo de +500% é erro de dado: limita

VERSOES = [
    ("top5", "5 melhores", "Os 5 melhores cofres pela regra, com partes iguais; troca só quando um sai da lista.", 5),
    ("top10", "10 melhores", "Os 10 melhores cofres pela regra, com partes iguais: mais espalhado.", 10),
    ("top5s", "5 melhores com saída", "Os 5 melhores, mas sai de um cofre que cair 15% do topo (depois da trava) e põe o dinheiro no próximo.", 5),
    ("hlp", "HLP", "Só o HLP, o cofre da própria corretora (faz mercado e liquidações; sem comissão; trava de 4 dias).", 1),
    ("semana", "Melhor da semana", "Toda segunda, troca para o cofre que mais rendeu na semana passada: mostra o custo de correr atrás.", 1),
    ("fixos", "Os que você fixou", "Os cofres que você fixou no app, com partes iguais; não saem pela regra.", 0),
]
RISCO = {"top5": "médio", "top10": "médio", "top5s": "médio", "hlp": "médio", "semana": "alto"}


# ---------------------------------------------------------------------------------------------- utilidades
def numero(x, padrao=None):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return padrao
    return v if math.isfinite(v) else padrao


def curto(e):
    return f"{e[:6]}…{e[-4:]}" if isinstance(e, str) and len(e) > 12 else str(e)


def dinheiro_curto(v):
    v = v or 0.0
    if v >= 1e9:
        return f"US$ {num_br(v / 1e9, 1)} bi"
    if v >= 1e6:
        return f"US$ {num_br(v / 1e6, 1)} mi"
    if v >= 1e3:
        return f"US$ {num_br(v / 1e3, 0)} mil"
    return moeda_br(v)


def quando_br(ms):
    return dt.datetime.fromtimestamp((ms + FUSO_MS) / 1000, dt.timezone.utc).strftime("%d/%m às %Hh")


def semana_de(ms):
    """A segunda-feira (AAAA-MM-DD, Brasília) da semana de `ms`."""
    d = dt.date.fromisoformat(dia_de(ms))
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def lista_nomes(nomes):
    nomes = list(nomes)
    return nomes[0] if len(nomes) == 1 else ", ".join(nomes[:-1]) + " e " + nomes[-1]


def ler_fixos(caminho=None):
    """Os endereços fixados (config/cofres-fixos.json); arquivo ausente ou inválido = nenhum."""
    try:
        with open(caminho or ARQ_FIXOS) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for x in (d.get("fixos") if isinstance(d, dict) else None) or []:
        e = (x.get("endereco") if isinstance(x, dict) else x) or ""
        if isinstance(e, str) and re.fullmatch(r"0x[0-9a-fA-F]{40}", e.strip()) and e.strip().lower() not in out:
            out.append(e.strip().lower())
    return out


# ---------------------------------------------------------------------------------------------- dados da API
def linha_lista(x):
    """Um item da lista do site → dict simples (None se não der para ler)."""
    if not isinstance(x, dict):
        return None
    s = x.get("summary") or {}
    e = s.get("vaultAddress")
    if not isinstance(e, str):
        return None
    rel = s.get("relationship") or {}
    pnls = {}
    for par in x.get("pnls") or []:
        if isinstance(par, (list, tuple)) and len(par) == 2 and isinstance(par[1], list) and par[1]:
            pnls[par[0]] = numero(par[1][-1], 0.0)
    return {"endereco": e.lower(), "nome": str(s.get("name") or curto(e)), "tvl": numero(s.get("tvl"), 0.0),
            "fechado": bool(s.get("isClosed")), "tipo": rel.get("type") or "normal",
            "pai": ((rel.get("data") or {}).get("parent") or "").lower() or None,
            "criado": int(numero(s.get("createTimeMillis"), 0) or 0) or None, "apr": numero(x.get("apr"), 0.0),
            "lucroMesUS": pnls.get("month", 0.0), "lucroTotalUS": pnls.get("allTime", 0.0), "lucroSemanaUS": pnls.get("week", 0.0)}


def janela(det, nome):
    """[(ms, patrimônio, lucro acumulado)] de uma janela do portfolio do cofre, só os horários com os dois números."""
    for par in (det or {}).get("portfolio") or []:
        if not (isinstance(par, (list, tuple)) and len(par) == 2 and par[0] == nome and isinstance(par[1], dict)):
            continue
        av, pnl = {}, {}
        for dest, chave in ((av, "accountValueHistory"), (pnl, "pnlHistory")):
            for p in par[1].get(chave) or []:
                if isinstance(p, (list, tuple)) and len(p) == 2:
                    t, v = numero(p[0]), numero(p[1])
                    if t is not None and v is not None:
                        dest[int(t)] = v
        comuns = [t for t in av if t in pnl]
        if pnl and len(comuns) < len(av) / 2:
            # horários diferentes nas duas curvas: o lucro de cada horário do patrimônio é o do último ponto antes dele
            tp = sorted(pnl)
            out = []
            for t in sorted(av):
                k = bisect.bisect_right(tp, t) - 1
                if k >= 0:
                    out.append((t, av[t], pnl[tp[k]]))
            return out
        return sorted((t, av[t], pnl[t]) for t in comuns)
    return []


def encadear(pts, t0, i0):
    """Anda a cota desde (t0, i0) pelos pontos da janela: r = Δlucro ÷ patrimônio anterior. O 1º trecho, se começa
    antes de t0, conta só a parte depois dele. Devolve ([(ms, cota)] dos pontos depois de t0, lacuna), em que lacuna =
    a janela começa depois de t0 (o trecho entre os dois fica sem retorno)."""
    out = []
    if not pts:
        return out, False
    k = None
    for j, p in enumerate(pts):
        if p[0] <= t0:
            k = j
        else:
            break
    lacuna = k is None
    k = 0 if lacuna else k
    i = i0
    for j in range(k + 1, len(pts)):
        a, b = pts[j - 1], pts[j]
        if b[0] <= t0:
            continue
        r = (b[2] - a[2]) / a[1] if a[1] > 0 else 0.0
        if a[0] < t0 < b[0]:
            r *= (b[0] - t0) / (b[0] - a[0])
        i *= 1 + max(-1.0, min(R_MAX, r))
        out.append((b[0], i))
    return out, lacuna


def serie_cota(det):
    """A cota do cofre desde o início ("allTime", grosso) com o último mês mais fino ("month"): ([(ms, cota)],
    [(ms, patrimônio)])."""
    allt, mes = janela(det, "allTime"), janela(det, "month")
    s, av = [], []
    if allt:
        s = [(allt[0][0], 1.0)] + encadear(allt, allt[0][0], 1.0)[0]
        av = [(t, v) for t, v, _ in allt]
    if mes:
        m0 = mes[0][0]
        s = [p for p in s if p[0] <= m0] or [(m0, 1.0)]
        if s[-1][0] < m0:
            s.append((m0, s[-1][1]))
        s += encadear(mes, m0, s[-1][1])[0]
        av = [p for p in av if p[0] < m0] + [(t, v) for t, v, _ in mes]
    return s, av


def valor_em(pts, t):
    """O valor do último ponto ≤ t (None antes do 1º)."""
    if not pts or t < pts[0][0]:
        return None
    k = bisect.bisect_right([p[0] for p in pts], t) - 1
    return pts[k][1]


def numeros(det, inf, agora):
    """lucroMes, lucroTotal e piorQueda pela cota (para os textos e os itens)."""
    s, av = serie_cota(det)
    md = medidas(s, av, inf.get("criado"), agora, tvl=inf.get("tvl")) or {}
    return {k: md.get(k) for k in ("lucroMes", "lucroTotal", "piorQueda")}


def interp(pts, t):
    """A cota em `t` interpolada entre os pontos vizinhos (os pontos do passado são esparsos: ligar em linha reta
    evita o "parado e depois salta" no teste no passado). None antes do 1º; o último depois do fim."""
    if not pts or t < pts[0][0]:
        return None
    k = bisect.bisect_right([p[0] for p in pts], t) - 1
    if k >= len(pts) - 1:
        return pts[-1][1]
    (ta, a), (tb, b) = pts[k], pts[k + 1]
    return a + (b - a) * (t - ta) / (tb - ta) if tb > ta else b


def info_detalhe(det, linha=None, agora=None):
    """Os números do cofre que a simulação e a escolha usam (de vaultDetails, completados pela lista)."""
    e = str(det.get("vaultAddress") or (linha or {}).get("endereco") or "").lower()
    rel = det.get("relationship") or {}
    tipo = rel.get("type") or (linha or {}).get("tipo") or "normal"
    pai = ((rel.get("data") or {}).get("parent") or (linha or {}).get("pai") or "").lower() or None
    sem = janela(det, "week") or janela(det, "day") or janela(det, "month") or janela(det, "allTime")
    com = numero(det.get("leaderCommission"), COMISSAO_PADRAO)
    if e == HLP:
        com = 0.0
    fech = det.get("isClosed")
    fech = bool((linha or {}).get("fechado")) if fech is None else bool(fech)
    aceita = det.get("allowDeposits")
    seg = det.get("followers")
    allt = janela(det, "allTime")
    criado = (linha or {}).get("criado") or (allt[0][0] if allt else None)
    return {"endereco": e, "nome": str(det.get("name") or (linha or {}).get("nome") or curto(e)),
            "com": max(0.0, min(0.5, com)), "lf": numero(det.get("leaderFraction"), 0.0),
            "aceita": True if aceita is None else bool(aceita), "fechado": fech,
            "tvl": sem[-1][1] if sem else (linha or {}).get("tvl", 0.0), "apr": numero(det.get("apr"), (linha or {}).get("apr", 0.0)),
            "maxSaque": numero(det.get("maxWithdrawable")), "seguidores": len(seg) if isinstance(seg, list) else None,
            "filhoHLP": tipo == "child" and (pai is None or pai == HLP), "criado": criado}


# ---------------------------------------------------------------------------------------------- medidas e regra
def medidas(s, av, criado, t, tvl=None):
    """Números da cota até `t`: lucroMes, lucroTotal, lucroSemana, piorQueda, idadeDias, tvl e nota."""
    pts = [p for p in s if p[0] <= t]
    if len(pts) < 2:
        return None
    i_t, i_0 = pts[-1][1], pts[0][1]
    i_m = interp(s, t - 30 * DIA) or i_0
    i_s = interp(s, t - 7 * DIA) or i_0
    i_t = interp(s, t) or i_t
    pico = queda = 0.0
    for _, i in pts:
        pico = max(pico, i)
        if pico > 0:
            queda = max(queda, 1 - i / pico)
    idade = (t - (criado or pts[0][0])) / DIA
    lm = i_t / i_m - 1 if i_m > 0 else -1.0
    lt = i_t / i_0 - 1 if i_0 > 0 else -1.0
    ls = i_t / i_s - 1 if i_s > 0 else -1.0
    ano = (1 + lt) ** (365 / max(idade, 30)) - 1 if lt > -1 else -1.0
    if tvl is None:
        tvl = valor_em(av, t) or 0.0
    bonus = min(1.4, max(1.0, 1 + 0.1 * math.log10(max(tvl, 1) / TVL_MIN)))
    nota = (0.6 * max(-1.0, min(3.0, lm * 12)) + 0.4 * max(-1.0, min(3.0, ano))) / (queda + 0.05) * bonus
    return {"lucroMes": lm, "lucroTotal": lt, "lucroSemana": ls, "piorQueda": queda, "idadeDias": idade, "tvl": tvl,
            "nota": nota}


def motivo_regra(m):
    """None se o cofre passa na regra; senão, o motivo em português."""
    if m.get("endereco") == HLP:
        return "é o HLP (tem versão própria)"
    if m.get("filhoHLP"):
        return "é um cofre filho do HLP (entra pelo HLP)"
    if m.get("fechado"):
        return "fechado"
    if not m.get("aceita", True):
        return "não aceita depósitos"
    if (m.get("tvl") or 0) < TVL_MIN:
        return f"TVL abaixo de {dinheiro_curto(TVL_MIN)}"
    if m.get("idadeDias") is not None and m["idadeDias"] < IDADE_MIN_DIAS:
        return f"tem menos de {IDADE_MIN_DIAS} dias"
    if m.get("lf") is not None and m["lf"] < PARTE_LIDER_MIN:
        return f"o líder tem só {pct_br(m['lf'])} do cofre (mínimo 5%)"
    if m.get("piorQueda") is not None and m["piorQueda"] > QUEDA_MAX:
        return f"caiu {pct_br(m['piorQueda'], 0)} do topo (máximo 30%)"
    if m.get("lucroMes") is not None and m["lucroMes"] <= 0:
        return "prejuízo no mês"
    if m.get("lucroTotal") is not None and m["lucroTotal"] <= 0:
        return "prejuízo desde o início"
    return None


def motivo_lista(l, agora):
    """O pré-filtro barato pela lista (sem vaultDetails)."""
    if l["endereco"] == HLP:
        return "é o HLP (tem versão própria)"
    if l["tipo"] == "child" and (l["pai"] in (None, HLP)):
        return "é um cofre filho do HLP (entra pelo HLP)"
    if l["fechado"]:
        return "fechado"
    if l["tvl"] < TVL_MIN:
        return f"TVL abaixo de {dinheiro_curto(TVL_MIN)}"
    if l["criado"] and (agora - l["criado"]) < IDADE_MIN_DIAS * DIA:
        return f"tem menos de {IDADE_MIN_DIAS} dias"
    if l["lucroMesUS"] <= 0:
        return "prejuízo no mês"
    if l["lucroTotalUS"] <= 0:
        return "prejuízo desde o início"
    return None


def texto_motivo(m):
    return (f"TVL de {dinheiro_curto(m['tvl'])}; lucro de {pct_br(m['lucroMes'])} no mês e {pct_br(m['lucroTotal'], 0)} "
            f"desde o início; pior queda de {pct_br(m['piorQueda'])}; comissão de {pct_br(m.get('com', COMISSAO_PADRAO), 0)}")


# ---------------------------------------------------------------------------------------------- a conta de uma versão
class Carteira:
    """Caixa + posições em cofres (cotas), sobre um dict do estado. `info(a)` dá nome, com, aceita, fechado, tvl,
    lucroMes do cofre; `cota(a)` a cota dele agora (ou None)."""

    def __init__(self, d, inicio):
        self.d = d
        d.setdefault("caixa", CAPITAL)
        d.setdefault("h", {})
        d.setdefault("ban", {})
        d.setdefault("pago", 0.0)
        self.curva = Curva.de_json(d.get("curva")) or Curva(inicio)

    @property
    def h(self):
        return self.d["h"]

    def liquido(self, a, i=None):
        p = self.h[a]
        i = p["i"] if i is None else i
        v = p["q"] * i
        return v - p["com"] * max(0.0, v - p["custo"])

    def valor(self, cota):
        tot = self.d["caixa"]
        for a, p in self.h.items():
            i = cota(a)
            if i is not None:
                p["i"] = i
            tot += self.liquido(a)
        return tot

    def entrar(self, a, valor, t, i, com, trava):
        valor = min(valor, self.d["caixa"])
        if valor <= 0.01 or not i or i <= 0:
            return False
        self.d["caixa"] -= valor
        self.h[a] = {"q": valor / i, "custo": valor, "i": i, "com": com, "pico": valor, "ate": t + trava, "desde": t}
        self.curva.operou()
        return True

    def sair(self, a, t, i=None, fracao=1.0):
        """Saca `fracao` da posição; devolve (dinheiro que voltou, comissão)."""
        p = self.h[a]
        if i is not None:
            p["i"] = i
        v = p["q"] * p["i"] * fracao
        custo = p["custo"] * fracao
        com = p["com"] * max(0.0, v - custo)
        self.d["caixa"] += v - com
        self.d["pago"] += com
        self.curva.operou(taxa=com)
        self.curva.fechou(v - com - custo)
        if fracao >= 0.999999:
            del self.h[a]
        else:
            p["q"] *= 1 - fracao
            p["custo"] *= 1 - fracao
            p["pico"] *= 1 - fracao
        return v - com, com

    def aportar(self, a, valor, t, i, trava):
        """Põe mais dinheiro num cofre que já tem (a trava recomeça)."""
        valor = min(valor, self.d["caixa"])
        if valor <= 0.01 or not i or i <= 0:
            return
        p = self.h[a]
        self.d["caixa"] -= valor
        p["q"] += valor / i
        p["custo"] += valor
        p["pico"] += valor
        p["i"] = i
        p["ate"] = max(p["ate"], t + trava)
        self.curva.operou()

    def marcar(self, t, cota):
        if t >= self.curva.t:
            self.curva.marcar(t, self.valor(cota))

    def resumo(self, agora):
        travas = [p["ate"] for p in self.h.values() if p["ate"] > agora]
        self.curva.extra = {"cofres": len(self.h), "travadoAte": max(travas) if travas else None,
                            "comissaoPaga": round(self.d["pago"], 4)}
        return self.curva.resumo()

    def para_json(self):
        self.d["curva"] = self.curva.para_json()
        return self.d


def trava_de(a):
    return TRAVA_HLP if a == HLP else TRAVA


def ajustar(cart, vid, t, desejados, n, info, cota, ev=None, motivos=None, limite=None, forcar=(), reequilibrar=False):
    """Leva a versão para os `desejados` (em ordem de preferência; `n` vagas): marca para sair o que saiu da lista,
    sai do que já pode (trava), entra nos que faltam com o caixa dividido igualmente. `forcar`: sair agora (cofre
    fechado ou sumido). `limite(a)`: o máximo que dá para sacar agora (maxWithdrawable) ou None. `reequilibrar`
    (na escolha da semana): os novos entram com a parte igual (tirando dos outros, se o caixa não der) e o dinheiro
    parado vai para os cofres que já tem."""
    motivos = motivos or {}
    saidas, entradas = [], []
    for a in list(cart.h):
        p = cart.h[a]
        if a in forcar:
            p["sair"] = motivos.get(a) or "o cofre fechou"
        elif a not in desejados and not p.get("sair"):
            p["sair"] = motivos.get(a) or "saiu da lista"
    for a in list(cart.h):
        p = cart.h[a]
        if not p.get("sair"):
            continue
        if a not in forcar and t < p["ate"]:
            if not p.get("avisou") and ev is not None:
                ev.add(t, "aviso", f"Quer sair do cofre {info(a)['nome']} ({p['sair']}), mas o dinheiro fica travado até "
                                   f"{quando_br(p['ate'])}.", vid)
            p["avisou"] = True
            continue
        i = cota(a)
        v = p["q"] * (i if i is not None else p["i"])
        lim = limite(a) if limite else None
        # sem limite, limite zero (a API sem `user` às vezes não diz) ou maior que o saque: sai tudo
        fr = 1.0 if (not lim or a in forcar or lim >= v or v <= 0) else lim / v
        motivo = p["sair"]
        volta, com = cart.sair(a, t, i, fr)
        saidas.append((a, motivo, volta, com, fr < 1.0))
    vagas = n - sum(1 for p in cart.h.values() if not p.get("sair"))
    ban = {a: x for a, x in cart.d["ban"].items() if x > t}
    cart.d["ban"] = ban
    novos = []
    for a in desejados:
        if len(novos) >= vagas:
            break
        if a in cart.h or a in ban or a in forcar:
            continue
        inf = info(a)
        if not inf or inf.get("fechado") or not inf.get("aceita", True) or cota(a) is None:
            continue
        novos.append(a)
    primeira = cart.curva.ops == 0
    tirado = aportado = 0.0
    ativos = [a for a, p in cart.h.items() if not p.get("sair")]
    alvo = cart.valor(cota) / max(1, len(ativos) + len(novos)) if reequilibrar else None
    if novos and reequilibrar:
        # partes iguais: o que falta para os novos sai dos cofres que já pode sacar (proporcional)
        falta = alvo * len(novos) - cart.d["caixa"]
        livres = [a for a in ativos if t >= cart.h[a]["ate"]]
        soma = sum(cart.liquido(a, cota(a)) for a in livres)
        if falta > 1 and soma > 0:
            fr = min(0.95, falta / soma)
            for a in livres:
                tirado += cart.sair(a, t, cota(a), fr)[0]
    if novos and cart.d["caixa"] > 0.01:
        parte = cart.d["caixa"] / len(novos)
        if alvo is not None:
            parte = min(parte, alvo)
        for a in novos:
            if cart.entrar(a, parte, t, cota(a), info(a).get("com", COMISSAO_PADRAO), trava_de(a)):
                entradas.append((a, parte))
    if reequilibrar and cart.d["caixa"] > max(1.0, 0.01 * cart.valor(cota)):
        # dinheiro parado (cofre que fechou sem substituto): vai para os cofres que já tem, em partes iguais
        abertos = [a for a, p in cart.h.items() if not p.get("sair") and cota(a) and info(a).get("aceita", True)
                   and not info(a).get("fechado") and a not in forcar]
        if abertos:
            parte = cart.d["caixa"] / len(abertos)
            for a in abertos:
                cart.aportar(a, parte, t, cota(a), trava_de(a))
                aportado += parte
    if ev is not None:
        eventos_ajuste(ev, vid, t, saidas, entradas, info, primeira=primeira and len(entradas) > 1)
        if tirado > 1:
            ev.add(t, "reequilibrou", f"Reequilibrou as partes: tirou {moeda_br(tirado)} dos outros cofres para "
                                      f"entrar em {lista_nomes([info(a)['nome'] for a, _ in entradas])}.", vid)
        if aportado > 1:
            ev.add(t, "reequilibrou", f"Pôs {moeda_br(aportado)} que estavam parados nos cofres que já tinha.", vid)
    return saidas, entradas


def eventos_ajuste(ev, vid, t, saidas, entradas, info, primeira=False):
    def desc_entrada(a):
        m = info(a)
        return f"TVL de {dinheiro_curto(m.get('tvl'))}; lucro de {pct_br(m.get('lucroMes') or 0)} no mês"

    if primeira:
        nomes = [info(a)["nome"] for a, _ in entradas]
        ev.add(t, "entrou", f"Montou a carteira com {len(entradas)} cofres ({lista_nomes(nomes)}): "
                            f"{moeda_br(entradas[0][1])} em cada.", vid)
        return
    if len(saidas) == 1 and len(entradas) == 1 and not saidas[0][4]:
        a, motivo, volta, com, _ = saidas[0]
        b, valor = entradas[0]
        ev.add(t, "trocou", f"Trocou de cofre: saiu de {info(a)['nome']} ({motivo}; voltaram {moeda_br(volta)}"
                            f"{', comissão de ' + moeda_br(com) if com > 0.005 else ''}) e entrou em {info(b)['nome']} "
                            f"({desc_entrada(b)}).", vid)
        return
    for a, motivo, volta, com, parcial in saidas:
        ev.add(t, "saiu", f"{'Sacou parte do' if parcial else 'Saiu do'} cofre {info(a)['nome']}: {motivo}. Voltaram "
                          f"{moeda_br(volta)}{' (comissão de ' + moeda_br(com) + ')' if com > 0.005 else ''}.", vid)
    for a, valor in entradas:
        ev.add(t, "entrou", f"Entrou no cofre {info(a)['nome']} ({desc_entrada(a)}) com {moeda_br(valor)}.", vid)


def conferir_stop(cart, vid, t, cota, info, ev=None):
    """top5s: atualiza o nosso topo em cada cofre e marca para sair o que caiu 15% dele (e sai, se a trava já
    passou). Devolve os cofres que saíram."""
    sairam = []
    for a in list(cart.h):
        p = cart.h[a]
        i = cota(a)
        if i is not None:
            p["i"] = i
        v = cart.liquido(a)
        p["pico"] = max(p["pico"], v)
        if not p.get("sair") and p["pico"] > 0 and v <= (1 - STOP) * p["pico"]:
            p["sair"] = f"caiu {pct_br(1 - v / p['pico'], 0)} do topo"
            cart.d["ban"][a] = t + BAN_MS
        if p.get("sair") and t >= p["ate"] and p["sair"].startswith("caiu"):
            motivo = p["sair"]
            volta, com = cart.sair(a, t)
            sairam.append(a)
            if ev is not None:
                ev.add(t, "saiu", f"Saiu do cofre {info(a)['nome']}: {motivo}. Voltaram {moeda_br(volta)}"
                                  f"{' (comissão de ' + moeda_br(com) + ')' if com > 0.005 else ''}.", vid)
    return sairam


# ---------------------------------------------------------------------------------------------- a rodada
def rodar(ctx):
    est, agora, cli, log = ctx.est, ctx.agora, ctx.cli, ctx.log
    erros = []
    ev = Eventos(est.get("eventos"))
    fixos = list(getattr(ctx, "fixos", None) or ler_fixos())
    cof = est.setdefault("cofres", {})          # os acompanhados: cota, conta própria (item) e números
    seg = est.setdefault("seguidos", {})        # endereço → {desde, nota, motivo}
    vers = est.setdefault("versoes", {})
    primeira_vez = not vers
    antes = est.get("fixos") or []
    for a in antes:
        if a not in fixos:
            ev.add(agora, "aviso", f"Você tirou o cofre {(cof.get(a) or {}).get('nome') or curto(a)} dos fixados.", "fixos")
            est.setdefault("motivoSaida", {}).setdefault(a, "você tirou dos fixados")
    est["fixos"] = fixos

    # 1) vaultDetails dos acompanhados (os seguidos, os das posições, os fixados e o HLP)
    acomp = set(cof) | set(fixos) | {HLP}
    dets, tentou, falhou = {}, 0, 0
    for a in sorted(acomp):
        tentou += 1
        try:
            d = cli.cofre(a)
        except hl.Erro as e:
            falhou += 1
            erros.append(f"vaultDetails {curto(a)}: {e}")
            continue
        if not isinstance(d, dict) or not d.get("portfolio"):
            if a in cof and not cof[a].get("sumiu"):
                cof[a]["sumiu"] = agora
                log(f"  cofre {curto(a)} sumiu da API")
            elif a not in cof:
                erros.append(f"cofre fixado {curto(a)} não existe na API")
            continue
        dets[a] = d
    if tentou and falhou == tentou:
        raise hl.Erro(f"vaultDetails falhou em todos os {tentou} cofres")

    # 2) a cota de cada um anda até agora (os pontos novos ficam em `pts` para as versões)
    pts = {}
    for a, d in dets.items():
        c = cof.get(a)
        inf = info_detalhe(d, agora=agora)
        if c is None:
            continue  # novo: entra depois, se for seguido, fixado ou o HLP
        c.update({k: inf[k] for k in ("nome", "com", "lf", "aceita", "fechado", "tvl", "apr", "maxSaque", "seguidores", "filhoHLP")})
        c.update(numeros(d, inf, agora))
        c.pop("sumiu", None)
        novos = []
        for nome_j in ("week", "month", "allTime"):
            jan = janela(d, nome_j)
            if not jan:
                continue
            novos, lacuna = encadear(jan, c["t"], c["i"])
            if not lacuna:
                if nome_j != "week":
                    log(f"  {c['nome']}: a semana não cobre desde a última rodada; usou a janela {nome_j}")
                break
        else:
            if novos:
                log(f"  {c['nome']}: nenhuma janela cobre desde {quando_br(c['t'])}; o trecho sem dados fica sem retorno")
        pts[a] = [(c["t"], c["i"])] + novos
        if novos:
            c["t"], c["i"] = novos[-1]
        # o item (US$ 1.000 só neste cofre)
        it = Curva.de_json(c.get("curva")) or Curva(agora)
        for t, i in novos:
            if t > it.t:
                v = c["q"] * i
                it.marcar(t, v - c["com"] * max(0.0, v - CAPITAL))
        c["curva"] = it.para_json()

    def novo_acompanhado(a, d, linha=None, extra=None):
        inf = info_detalhe(d, linha, agora)
        # a cota começa agora (o 1º ponto novo conta só a parte depois de agora)
        c = {"t": agora, "i": 1.0, "q": CAPITAL, "desde": agora, **{k: inf[k] for k in inf if k != "endereco"},
             **numeros(d, inf, agora)}
        if extra:
            c.update(extra)
        it = Curva(agora)
        it.marcar(agora, CAPITAL)
        it.operou()
        c["curva"] = it.para_json()
        cof[a] = c
        pts[a] = [(agora, 1.0)]
        return c

    for a in [HLP] + fixos:
        if a not in cof and a in dets:
            novo_acompanhado(a, dets[a], extra={"motivo": "o cofre da própria corretora" if a == HLP else "você fixou"})
    for a in fixos:
        if a not in antes and not primeira_vez:
            ev.add(agora, "aviso", f"Você fixou o cofre {(cof.get(a) or {}).get('nome') or curto(a)}.", "fixos")

    def info(a):
        return cof.get(a) or {"nome": curto(a), "aceita": False}

    def cota_agora(a):
        c = cof.get(a)
        return c["i"] if c and "i" in c else None

    # 3) escolha da semana (1ª rodada de cada semana) e o teste no passado
    motivos_saida = {}
    escolheu = False
    if primeira_vez or est.get("selecaoEm") is None or semana_de(agora) != semana_de(est["selecaoEm"]):
        try:
            escolheu = escolher(ctx, est, dets, fixos, erros, ev, novo_acompanhado, motivos_saida, pts)
        except Exception as e:  # noqa: BLE001
            if primeira_vez:
                raise
            erros.append(f"escolha: {e}")
            log(f"  escolha adiada: {e}")
    # cofres seguidos que fecharam ou sumiram saem já
    for a in list(seg):
        c = cof.get(a) or {}
        if c.get("fechado") or c.get("sumiu"):
            motivos_saida[a] = "o cofre fechou" if c.get("fechado") else "o cofre sumiu da corretora"
            sair_dos_seguidos(est, a, agora, motivos_saida[a], ev)
    ordem = [a for a, _ in sorted(seg.items(), key=lambda x: -(x[1].get("nota") or 0))]

    # 4) as versões andam pelos pontos novos e se ajustam agora
    def cota_em(t):
        def f(a):
            p = pts.get(a)
            if not p:
                return cota_agora(a)
            v = valor_em(p, t)
            return v if v is not None else p[0][1]
        return f

    forcar = {a for a, c in cof.items() if c.get("fechado") or c.get("sumiu")}
    for a in forcar:
        motivos_saida.setdefault(a, "o cofre fechou" if cof[a].get("fechado") else "o cofre sumiu da corretora (saída pelo último valor)")
    limite = lambda a: (cof.get(a) or {}).get("maxSaque")  # noqa: E731
    desejo = {"top5": ordem, "top10": ordem, "top5s": ordem, "hlp": [HLP], "semana": [est.get("semanaAlvo")] if est.get("semanaAlvo") else [],
              "fixos": fixos}
    saida_versoes = []
    for vid, nome, frase, n in VERSOES:
        if vid == "fixos" and not fixos and vid not in vers:
            continue
        cart = Carteira(vers.setdefault(vid, {}), agora)
        try:
            tempos = sorted({t for a in cart.h for t, _ in pts.get(a, [])[1:] if t > cart.curva.t and t <= agora})
            for t in tempos:
                if vid == "top5s":
                    conferir_stop(cart, vid, t, cota_em(t), info, ev)
                cart.marcar(t, cota_em(t))
            mot = dict(motivos_saida)
            if vid == "semana":
                for a in cart.h:
                    mot.setdefault(a, "deixou de ser o melhor da semana")
            if vid == "fixos":
                for a in cart.h:
                    mot.setdefault(a, "você tirou dos fixados")
            if vid == "top5s":
                conferir_stop(cart, vid, agora, cota_agora, info, ev)
            ajustar(cart, vid, agora, desejo[vid], n or len(fixos), info, cota_agora, ev, mot, limite, forcar,
                    reequilibrar=escolheu or (vid == "fixos" and fixos != antes))
            cart.marcar(agora, cota_agora)
        except Exception as e:  # noqa: BLE001
            erros.append(f"versão {vid}: {e}")
            log(f"  versão {vid}: {e}")
        cart.para_json()
        if vid == "fixos" and not fixos:
            continue
        saida_versoes.append((vid, nome, frase, cart))

    # 5) os que ninguém mais usa deixam de ser acompanhados
    usados = set(seg) | set(fixos) | {HLP, est.get("semanaAlvo")} | {a for v in vers.values() for a in (v.get("h") or {})}
    for a in [a for a in cof if a not in usados]:
        guardar_saido(est, a, agora, est.get("motivoSaida", {}).get(a) or motivos_saida.get(a) or "saiu da lista")
        del cof[a]
    est["motivoSaida"] = {a: m for a, m in (est.get("motivoSaida") or {}).items() if a in cof}

    # 6) o teste no passado dos itens (a cada 7 dias, com os detalhes desta rodada)
    for a, c in cof.items():
        if a in dets and (not c.get("hist") or agora - c.get("histEm", 0) >= HIST_A_CADA):
            try:
                c["hist"], c["histEm"] = historico_item(dets[a], agora, c.get("com", COMISSAO_PADRAO)), agora
            except Exception as e:  # noqa: BLE001
                erros.append(f"teste no passado de {c.get('nome')}: {e}")

    # 7) a saída
    hist = (est.get("hist") or {}).get("versoes") or {}
    versoes = []
    for vid, nome, frase, cart in saida_versoes:
        v = {"id": vid, "nome": nome, "frase": frase, "alav": 1, "aoVivo": cart.resumo(agora), "historico": hist.get(vid)}
        if vid == "fixos":
            v["fixa"] = True
            v["risco"] = "alto" if len(fixos) < 3 else "médio"
        else:
            v["risco"] = RISCO[vid]
        versoes.append(v)
    est["eventos"] = ev.para_json()
    if escolheu:
        log(f"  escolha: {len(seg)} seguidos; melhor da semana: {info(est['semanaAlvo'])['nome'] if est.get('semanaAlvo') else '-'}")
    return {
        "frase": "Você deposita dólares num cofre e ele negocia por você: o HLP, da própria corretora, ou o de um trader, que fica com 10% do lucro.",
        "comoFunciona": [
            "Cada versão começa com US$ 1.000 fictícios. O dinheiro segue o rendimento por cota do cofre (como uma "
            "cota de fundo): o que os outros depositam ou sacam não muda o seu resultado.",
            "Toda segunda o robô escolhe os cofres: abertos, aceitando depósito, com pelo menos US$ 100 mil, 30 dias de "
            "vida, o líder com 5% ou mais do próprio dinheiro dentro, lucro no mês e desde o início e queda máxima de "
            "30%. Ganha quem rende bem caindo pouco. Um escolhido fica pelo menos 4 semanas.",
            "O valor mostrado já desconta a comissão do líder (10% do lucro, como se você sacasse agora). Depois de "
            "entrar, o dinheiro fica travado: 4 dias no HLP e 1 dia nos outros.",
            "O teste no passado usa poucos pontos por cofre e só os cofres que existem hoje: é aproximado.",
        ],
        "padrao": "top5",
        "versoes": versoes,
        "eventos": est["eventos"],
        "itens": itens_saida(est, fixos, agora),
        "candidatos": est.get("candidatos") or [],
        "avisos": [
            "Um cofre pode perder muito num dia só: em março de 2025 (caso JELLY) o HLP herdou posições ruins de uma "
            "manipulação de preço. O papel só vê isso depois que acontece.",
            "O líder pode fechar o cofre ou parar de aceitar depósitos a qualquer hora.",
            "Um saque grande pode sair em partes ou com deslize; aqui o depósito é pequeno e sai pelo valor da cota.",
            "Há o risco da própria corretora e da ponte do USDC (Arbitrum), que o papel não mede.",
            "O teste no passado escolhe entre os cofres que existem hoje (os que quebraram e sumiram não entram) e "
            "supõe que a parte do líder e os depósitos eram como hoje: tende a sair melhor que a realidade.",
        ],
        "config": {"frequencia": "a cada 6 h", "escolha": "toda segunda-feira",
                   "regra": {"tvlMin": TVL_MIN, "idadeMinDias": IDADE_MIN_DIAS, "parteLiderMin": PARTE_LIDER_MIN,
                             "quedaMax": QUEDA_MAX, "ficaSemanas": FICA_MS // (7 * DIA), "stop": STOP},
                   "travaDias": {"hlp": TRAVA_HLP // DIA, "outros": TRAVA // DIA}, "fixos": len(fixos)},
        "erros": erros,
    }


def sair_dos_seguidos(est, a, agora, motivo, ev):
    seg = est["seguidos"]
    if a not in seg:
        return
    del seg[a]
    est.setdefault("motivoSaida", {})[a] = motivo
    guardar_saido(est, a, agora, motivo)
    nome = (est["cofres"].get(a) or {}).get("nome") or curto(a)
    ev.add(agora, "saiu", f"O cofre {nome} saiu da lista dos seguidos: {motivo}.", None)


def guardar_saido(est, a, agora, motivo):
    c = est["cofres"].get(a)
    if not c:
        return
    saidos = [x for x in est.get("saidos") or [] if x["endereco"] != a]
    item = item_de(a, c, agora, fixo=False)
    item["saiu"] = {"em": agora, "motivo": motivo}
    est["saidos"] = (saidos + [item])[-MAX_SAIDOS:]


def item_de(a, c, agora, fixo):
    it = Curva.de_json(c.get("curva"))
    criado = c.get("criado")
    return {"endereco": a, "nome": c.get("nome") or curto(a), "tvl": round(c.get("tvl") or 0, 2), "apr": c.get("apr"),
            "idadeDias": int((agora - criado) / DIA) if criado else None, "comissao": c.get("com"),
            "seguidoresMax": None, "seguidores": c.get("seguidores"), "fixo": fixo, "motivo": c.get("motivo") or "",
            "desde": c.get("desde"), "aoVivo": it.resumo() if it else None, "historico": c.get("hist"), "saiu": None}


def itens_saida(est, fixos, agora):
    cof, seg = est["cofres"], est["seguidos"]
    out, vistos = [], set()
    ordem = [HLP] + fixos + [a for a, _ in sorted(seg.items(), key=lambda x: -(x[1].get("nota") or 0))]
    for a in ordem:
        if a in vistos or a not in cof:
            continue
        vistos.add(a)
        it = item_de(a, cof[a], agora, fixo=a in fixos)
        if a in seg:
            it["motivo"] = seg[a].get("motivo") or it["motivo"]
            it["desde"] = seg[a].get("desde") or it["desde"]
        out.append(it)
    for x in reversed(est.get("saidos") or []):
        if x["endereco"] not in vistos:
            vistos.add(x["endereco"])
            out.append(x)
    return out


# ---------------------------------------------------------------------------------------------- a escolha
def escolher(ctx, est, dets, fixos, erros, ev, novo_acompanhado, motivos_saida, pts):
    cli, agora, log = ctx.cli, ctx.agora, ctx.log
    cof, seg = est["cofres"], est["seguidos"]
    lista = cli.cofres()
    linhas = {}
    for x in lista:
        l = linha_lista(x)
        if l:
            linhas[l["endereco"]] = l
    if not linhas:
        raise hl.Erro("a lista de cofres veio vazia")
    pre = []
    recusas = {}
    for l in linhas.values():
        m = motivo_lista(l, agora)
        if m:
            recusas[m] = recusas.get(m, 0) + 1
        else:
            pre.append(l)
    pre.sort(key=lambda l: -min(0.3, l["lucroMesUS"] / max(1.0, l["tvl"] - l["lucroMesUS"])))
    analisar = [l["endereco"] for l in pre[:DETALHAR]]
    analisar += [a for a in seg if a not in analisar]
    # vaultDetails do que falta (o tempo da rodada é dividido com as outras formas)
    for a in analisar:
        if a in dets:
            continue
        if ctx.restante() < TEMPO_MIN_ESCOLHA:
            log("  pouco tempo: a escolha usa só os cofres já detalhados")
            break
        try:
            d = cli.cofre(a)
        except hl.Erro as e:
            erros.append(f"vaultDetails {curto(a)}: {e}")
            continue
        if isinstance(d, dict) and d.get("portfolio"):
            dets[a] = d
    metas = {}
    for a in set(analisar) | set(seg) | set(fixos) | {HLP}:
        d = dets.get(a)
        if not d:
            continue
        inf = info_detalhe(d, linhas.get(a), agora)
        s, av = serie_cota(d)
        md = medidas(s, av, inf["criado"], agora, tvl=inf["tvl"]) or {}
        sem = janela(d, "week")
        if sem:
            ch, _ = encadear(sem, sem[0][0], 1.0)
            md["lucroSemana"] = ch[-1][1] - 1 if ch else 0.0
        m = {**inf, **md, "s": s, "av": av}
        m["motivoRecusa"] = motivo_regra(m) if md else "sem histórico"
        metas[a] = m
    passam = sorted((a for a, m in metas.items() if not m["motivoRecusa"]), key=lambda a: -metas[a]["nota"])

    # os seguidos: os de menos de 4 semanas ficam (menos os fechados, sem depósito ou sumidos); os outros, se passam
    sairam, entraram = [], []
    for a in list(seg):
        c, m = cof.get(a) or {}, metas.get(a)
        motivo = None
        if c.get("fechado") or (m and m["fechado"]):
            motivo = "o cofre fechou"
        elif c.get("sumiu"):
            motivo = "o cofre sumiu da corretora"
        elif (m and not m["aceita"]) or not c.get("aceita", True):
            motivo = "parou de aceitar depósitos"
        elif agora - seg[a]["desde"] >= FICA_MS:
            if m is None:
                pass  # sem dados agora: fica até a próxima
            elif m["motivoRecusa"]:
                motivo = f"não passa mais na regra ({m['motivoRecusa']})"
        if motivo:
            motivos_saida[a] = motivo
            sairam.append((a, motivo))
            sair_dos_seguidos(est, a, agora, motivo, ev)
        elif m and not m["motivoRecusa"]:
            seg[a]["nota"] = m["nota"]
    vagas = SEGUIR - len(seg)
    sairam_agora = {a for a, _ in sairam}
    for a in passam:
        if vagas <= 0:
            break
        if a in seg or a in sairam_agora:
            continue
        m = metas[a]
        m["com"] = m.get("com", COMISSAO_PADRAO)
        seg[a] = {"desde": agora, "nota": m["nota"], "motivo": texto_motivo(m)}
        if a not in cof:
            novo_acompanhado(a, dets[a], linhas.get(a), extra={"motivo": texto_motivo(m)})
        else:
            cof[a]["motivo"] = texto_motivo(m)
        cof[a].update({"lucroMes": m["lucroMes"], "lucroTotal": m["lucroTotal"], "piorQueda": m["piorQueda"]})
        est["saidos"] = [x for x in est.get("saidos") or [] if x["endereco"] != a]
        entraram.append(a)
        vagas -= 1
    for a in list(seg):
        if a in metas and a in cof:
            cof[a].update({"lucroMes": metas[a].get("lucroMes"), "lucroTotal": metas[a].get("lucroTotal"),
                           "piorQueda": metas[a].get("piorQueda")})
            if linhas.get(a, {}).get("criado"):
                cof[a]["criado"] = linhas[a]["criado"]
    if entraram:
        nomes = [metas[a]["nome"] for a in entraram]
        ev.add(agora, "entrou", f"Escolha da semana: {'entrou' if len(nomes) == 1 else 'entraram'} {lista_nomes(nomes)} "
                                f"na lista dos {SEGUIR} seguidos.", None)

    # o melhor da semana passada (entre os que passam na regra)
    melhores = sorted((a for a in passam if metas[a].get("lucroSemana") is not None), key=lambda a: -metas[a]["lucroSemana"])
    antes = est.get("semanaAlvo")
    if melhores:
        alvo = melhores[0]
        est["semanaAlvo"] = alvo
        if alvo not in cof:
            novo_acompanhado(alvo, dets[alvo], linhas.get(alvo), extra={"motivo": texto_motivo(metas[alvo])})
        cof[alvo]["lucroMes"] = metas[alvo]["lucroMes"]
        if alvo != antes:
            ev.add(agora, "aviso", f"O melhor da semana passada é {metas[alvo]['nome']} "
                                   f"({'+' if metas[alvo]['lucroSemana'] >= 0 else ''}{pct_br(metas[alvo]['lucroSemana'])} em 7 dias).", "semana")
    est["selecaoEm"] = agora

    # candidatos: os detalhados (os que passam primeiro) e, se sobrar espaço, os maiores abertos
    cands = []
    for a in passam + sorted((a for a in metas if metas[a]["motivoRecusa"]), key=lambda a: -(metas[a].get("tvl") or 0)):
        m = metas[a]
        cands.append({"endereco": a, "nome": m["nome"], "tvl": round(m.get("tvl") or 0, 2), "apr": m.get("apr"),
                      "idadeDias": int(m["idadeDias"]) if m.get("idadeDias") is not None else None,
                      "lucroMes": r6(m.get("lucroMes")), "lucroTotal": r6(m.get("lucroTotal")), "piorQueda": r6(m.get("piorQueda")),
                      "comissao": m.get("com"), "passou": not m["motivoRecusa"],
                      "motivo": texto_motivo(m) if not m["motivoRecusa"] else m["motivoRecusa"]})
    vistos = {c["endereco"] for c in cands}
    for l in sorted((l for l in linhas.values() if not l["fechado"]), key=lambda l: -l["tvl"]):
        if len(cands) >= MAX_CANDIDATOS:
            break
        if l["endereco"] in vistos:
            continue
        cands.append({"endereco": l["endereco"], "nome": l["nome"], "tvl": round(l["tvl"], 2), "apr": l["apr"],
                      "idadeDias": int((agora - l["criado"]) / DIA) if l["criado"] else None,
                      "lucroMes": r6(l["lucroMesUS"] / max(1.0, l["tvl"] - l["lucroMesUS"])), "lucroTotal": None,
                      "piorQueda": None, "comissao": None, "passou": False,
                      "motivo": motivo_lista(l, agora) or "não ficou entre os detalhados nesta semana"})
    est["candidatos"] = cands[:MAX_CANDIDATOS]
    est["funil"] = {"lista": len(linhas), "preFiltro": len(pre), "detalhados": len(metas), "passaram": len(passam),
                    "recusas": recusas}
    log(f"  escolha: {len(linhas)} cofres na lista, {len(pre)} no pré-filtro, {len(metas)} detalhados, {len(passam)} passaram; "
        f"saíram {len(sairam)}, entraram {len(entraram)}")

    # o teste no passado (a cada 7 dias)
    h = est.get("hist") or {}
    if agora - h.get("em", 0) >= HIST_A_CADA:
        if ctx.restante() < TEMPO_MIN_HIST:
            log("  pouco tempo: teste no passado fica para a próxima")
        else:
            try:
                est["hist"] = {"em": agora, "versoes": historico_versoes(metas, agora, fixos)}
            except Exception as e:  # noqa: BLE001
                erros.append(f"teste no passado: {e}")
    return True


def r6(x):
    return round(x, 6) if isinstance(x, (int, float)) else None


# ---------------------------------------------------------------------------------------------- teste no passado
def historico_item(det, agora, com):
    """US$ 1.000 só neste cofre nos últimos HIST_DIAS dias, pela cota (allTime + month): aproximado."""
    s, _ = serie_cota(det)
    ini = agora - HIST_DIAS * DIA
    s = [p for p in s if p[0] <= agora]
    if len(s) < 2:
        return None
    base = valor_em(s, ini)
    if base is None:
        base, t0 = s[0][1], s[0][0]
    else:
        t0 = ini
    if not base or base <= 0:
        return None
    c = Curva(t0)
    c.marcar(t0, CAPITAL)
    c.operou()
    for t, i in s:
        if t > t0:
            v = CAPITAL * i / base
            c.marcar(t, v - com * max(0.0, v - CAPITAL))
    return c.resumo(de=dia_de(t0), ate=dia_de(agora), aproximado=True)


def historico_versoes(metas, agora, fixos):
    """As versões dia a dia nos últimos HIST_DIAS dias com as mesmas regras, sobre os cofres detalhados agora."""
    inicio_dados = min((m["s"][0][0] for m in metas.values() if m.get("s")), default=agora)
    ini = max(agora - HIST_DIAS * DIA, inicio_dados + IDADE_MIN_DIAS * DIA)
    if ini >= agora - 7 * DIA:
        return {}
    tempos = list(range(ini, agora + 1, DIA))
    contas = {vid: Carteira({}, ini) for vid, *_ in VERSOES if vid != "fixos" or fixos}
    seg, alvo = {}, None
    m_t = {}

    def info(a):
        m = metas[a]
        return {"nome": m["nome"], "com": m.get("com", COMISSAO_PADRAO), "aceita": m.get("aceita", True), "fechado": False,
                "tvl": (m_t.get(a) or {}).get("tvl"), "lucroMes": (m_t.get(a) or {}).get("lucroMes")}

    for k, t in enumerate(tempos):
        def cota(a, t=t):
            m = metas.get(a)
            return interp(m["s"], t) if m else None
        if k % 7 == 0:
            m_t.clear()
            for a, m in metas.items():
                md = medidas(m["s"], m["av"], m.get("criado"), t)
                if md:
                    md["lucroSemana"] = md.get("lucroSemana")
                    m_t[a] = {**{x: m.get(x) for x in ("endereco", "fechado", "aceita", "lf", "filhoHLP", "com")}, **md}
            passam = sorted((a for a, x in m_t.items() if not motivo_regra(x)), key=lambda a: -m_t[a]["nota"])
            for a in list(seg):
                if t - seg[a]["desde"] >= FICA_MS and (a not in m_t or motivo_regra(m_t[a])):
                    del seg[a]
                elif a in m_t:
                    seg[a]["nota"] = m_t[a]["nota"]
            for a in passam:
                if len(seg) >= SEGUIR:
                    break
                if a not in seg:
                    seg[a] = {"desde": t, "nota": m_t[a]["nota"]}
            if passam:
                alvo = max(passam, key=lambda a: m_t[a]["lucroSemana"])
        ordem = [a for a, _ in sorted(seg.items(), key=lambda x: -x[1]["nota"])]
        desejo = {"top5": ordem, "top10": ordem, "top5s": ordem, "hlp": [HLP] if HLP in metas else [],
                  "semana": [alvo] if alvo else [], "fixos": [a for a in fixos if a in metas]}
        for vid, _, _, n in VERSOES:
            cart = contas.get(vid)
            if cart is None:
                continue
            if vid == "top5s":
                conferir_stop(cart, vid, t, cota, info)
            if k % 7 == 0 or vid in ("top5s", "fixos") or any(p.get("sair") for p in cart.h.values()) or cart.d["caixa"] > 1:
                ajustar(cart, vid, t, desejo[vid], n or len(desejo["fixos"]), info, cota, reequilibrar=k % 7 == 0)
            cart.marcar(t, cota)
    out = {}
    for vid, cart in contas.items():
        if cart.curva.ops == 0:
            continue
        r = cart.resumo(agora)
        r.update({"de": dia_de(ini), "ate": dia_de(agora), "aproximado": True})
        out[vid] = r
    return out
