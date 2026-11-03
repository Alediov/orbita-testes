"""Robôs de grade e DCA, NO PAPEL (plano: docs/plano-testes-mercado-2.md, seção 5; formato: tools/papel/FORMATO.md).
Nenhuma ordem, nenhuma conta, nenhuma chave: só as velas públicas da Hyperliquid (à vista e perpétuo) e o
financiamento de hora em hora.

Como a simulação anda:
- ao vivo, nas velas de 1 minuto: cada rodada continua do último minuto já processado (guardado no estado) até agora;
  se o buraco for maior do que as velas de 1 minuto alcançam (~3,5 dias), usa o intervalo mais fino que ainda cobre
  (5 min, 15 min, 1 h; `hl.intervalo_para`);
- teste no passado nas velas de 1 hora, ~180 dias, refeito no máximo uma vez por semana;
- dentro de cada vela o caminho do preço é o PIOR para o robô: abre → mínima → máxima → fecha ou abre → máxima →
  mínima → fecha (simula os dois e fica com o de menor patrimônio no fechamento);
- ordem limite só executa se o preço passar um tique além dela (`TIQUE`, 0,01%: a fila do livro);
- taxas: ordem limite 0,015% no perpétuo e 0,04% no à vista; a mercado 0,045% e 0,07%, mais um deslize de 0,05%
  (como no sim.py para BTC e ETH);
- perpétuo: financiamento de hora em hora (comprado paga a taxa positiva), margem isolada da conta e liquidação quando
  o patrimônio cai abaixo da manutenção, mmr = 1 / (2 × alavancagem máxima do ativo), como no sim.py; liquidada, a
  conta perde a margem e para.

Estado (`ctx.est`):
    {"pares": {"BTC": "@142", …}, "paresEm": ms, "levMax": {"BTC": 40}, "levEm": ms,
     "vivo": {id: {"curva": Curva.para_json(), "bot": {estado do robô, "ate": ms já processado}}},
     "hist": {"em": ms, "contas": {id: conta do teste no passado}}, "eventos": [...]}
"""
from __future__ import annotations

import bisect
import copy
import math

import hl
from conta import CAPITAL, DIA, HORA, Curva, Eventos, dia_de, moeda_br, num_br, pct_br

NOME = "Robôs"
VERSAO = 1

MIN = 60_000
TIQUE = 0.0001          # a ordem limite só executa se o preço passar 0,01% além dela
TAXAS = {"perp": {"limite": 0.00015, "mercado": 0.00045}, "spot": {"limite": 0.0004, "mercado": 0.0007}}
DESLIZE = 0.0005        # ordens a mercado em BTC e ETH (o mesmo do sim.py)
ALAV_MAX = 3            # regra do Alediov para os robôs
HIST_DIAS = 180
REFAZER_HIST_MS = 7 * DIA
AQUECER_DIAS = 7        # a máxima de 7 dias do "DCA na queda" precisa dos 7 dias anteriores
SEG_MIN_HIST = 240      # sem esse tempo sobrando na rodada, o teste no passado fica para a próxima
LEV_MAX_PADRAO = {"BTC": 40, "ETH": 25, "SOL": 20, "HYPE": 10}
PARES_PADRAO = {"BTC": "@142", "ETH": "@151", "SOL": "@156", "HYPE": "@107"}
TOKENS = {"BTC": "UBTC", "ETH": "UETH", "SOL": "USOL", "HYPE": "HYPE"}
REFAZER_META_MS = DIA

NOTA_HIST = ("Teste no passado com velas de 1 hora: dentro de cada hora o preço pode ter ido e voltado mais vezes do "
             "que a simulação vê, então a grade pode ter executado mais degraus (para o bem ou para o mal).")

VERSOES = [
    {"id": "gbtc10", "nome": "Grade BTC ±10%", "tipo": "grade", "mercado": "spot", "moeda": "BTC", "faixa": 0.10,
     "degraus": 20, "recentrar": False, "alav": 1, "risco": "médio", "grupo": "Grade",
     "frase": "20 degraus de compra e venda entre 10% abaixo e 10% acima do preço do início, no à vista: ganha um "
              "pouquinho a cada sobe e desce."},
    {"id": "geth10", "nome": "Grade ETH ±10%", "tipo": "grade", "mercado": "spot", "moeda": "ETH", "faixa": 0.10,
     "degraus": 20, "recentrar": False, "alav": 1, "risco": "médio", "grupo": "Grade",
     "frase": "A mesma grade de 20 degraus, ±10%, no ether: mais vai e vem, mas também quedas maiores."},
    {"id": "gbtc20r", "nome": "Grade BTC ±20% recentrada", "tipo": "grade", "mercado": "spot", "moeda": "BTC",
     "faixa": 0.20, "degraus": 20, "recentrar": True, "alav": 1, "risco": "médio", "grupo": "Grade",
     "frase": "Grade larga (±20%) que, quando o preço sai dela, monta uma nova em volta do preço de agora, pagando a "
              "troca."},
    {"id": "gneutra1", "nome": "Grade neutra 1×", "tipo": "grade", "mercado": "perp", "moeda": "BTC", "faixa": 0.10,
     "degraus": 20, "recentrar": False, "alav": 1, "risco": "médio", "grupo": "Grade",
     "frase": "Grade no perpétuo que começa sem posição: compra abaixo e vende acima do preço do início, sem "
              "alavancagem."},
    {"id": "gneutra3", "nome": "Grade neutra 3×", "tipo": "grade", "mercado": "perp", "moeda": "BTC", "faixa": 0.10,
     "degraus": 20, "recentrar": False, "alav": 3, "risco": "alto", "grupo": "Grade",
     "frase": "A grade neutra com 3× de alavancagem: degraus três vezes maiores, e pode ser liquidada numa queda ou "
              "alta muito forte."},
    {"id": "dca", "nome": "DCA semanal", "tipo": "dca", "mercado": "spot", "moeda": "BTC", "partes": 20,
     "cada": 7 * DIA, "alav": 1, "risco": "médio", "grupo": "DCA",
     "frase": "Compra US$ 50 de bitcoin toda semana, em 20 semanas; o que ainda não foi usado fica parado em dólar."},
    {"id": "dcaqueda", "nome": "DCA na queda", "tipo": "queda", "mercado": "spot", "moeda": "BTC", "partes": 20,
     "cada": 7 * DIA, "queda": 0.05, "janela": 7 * DIA, "alav": 1, "risco": "médio", "grupo": "DCA",
     "frase": "Compra US$ 50 de bitcoin só quando o preço está 5% ou mais abaixo da máxima dos últimos 7 dias (no "
              "máximo uma compra por semana)."},
    {"id": "dcam1", "nome": "DCA com proteção 1×", "tipo": "martingale", "mercado": "spot", "moeda": "BTC",
     "passo": 0.02, "seguranca": 5, "mult": 1.5, "alvo": 0.015, "alav": 1, "risco": "médio", "grupo": "DCA",
     "frase": "Compra, e compra mais (1,5× maior) a cada 2% de queda, até 5 vezes; vende tudo com 1,5% acima do "
              "preço médio e recomeça."},
    {"id": "dcam3", "nome": "DCA com proteção 3×", "tipo": "martingale", "mercado": "perp", "moeda": "BTC",
     "passo": 0.02, "seguranca": 5, "mult": 1.5, "alvo": 0.015, "alav": 3, "risco": "alto", "grupo": "DCA",
     "frase": "O mesmo DCA com proteção no perpétuo com 3× de alavancagem: lucro maior por ciclo, mas uma queda "
              "longa pode liquidar a conta."},
]
PADRAO = "gbtc10"

FRASE = ("Robôs que compram e vendem sozinhos: a grade ganha no sobe e desce do preço; o DCA compra aos poucos "
         "para não acertar o pior momento.")
COMO_FUNCIONA = [
    "Grade: o robô espalha ordens de compra abaixo do preço e de venda acima, em degraus. Cada vez que o preço desce "
    "um degrau e volta a subir, ele compra barato e vende um pouco mais caro: é um \"par\" fechado com lucro.",
    "Se o preço sai da grade, o robô para de ganhar: por cima, vendeu tudo e fica em dólar; por baixo, comprou tudo e "
    "fica com a moeda, que pode continuar caindo. A versão recentrada monta uma grade nova em volta do preço, pagando "
    "a troca.",
    "Grade neutra: no perpétuo (contrato que acompanha o preço), começa sem posição; abaixo do preço ela fica comprada, "
    "acima fica vendida (ganha se o preço cair). Com alavancagem, pode ser liquidada.",
    "DCA: compra um pouco de tempos em tempos (toda semana, ou só nas quedas) para não colocar tudo no pior momento. "
    "O DCA com proteção (a \"martingale\" dos robôs prontos) compra mais a cada queda de 2% e vende tudo com 1,5% de "
    "lucro sobre o preço médio; se a queda passar de 10%, o caixa acaba e ele só espera.",
    "Tudo com US$ 1.000 fictícios por versão, taxas da Hyperliquid e o pior caminho do preço dentro de cada vela. Ao "
    "vivo usa velas de 1 minuto. " + NOTA_HIST,
]
AVISOS = [
    "Tendência forte: o preço pode sair da grade e não voltar. Por cima, a grade vendeu tudo e não ganha com a alta; "
    "por baixo, fica tudo comprado no alto e o prejuízo é o da moeda.",
    "No DCA com proteção, uma sequência de quedas maior que 10% esgota o caixa e o robô fica parado esperando; o "
    "papel mostra quando isso acontece, mas o período medido pode não ter tido uma queda dessas.",
    "Corretora fora do ar, ordens que não entram ou atrasam e mudanças nas regras: o papel supõe que a Hyperliquid "
    "sempre respondeu na hora.",
    "Dentro de cada vela o papel supõe o caminho do preço pior para o robô e que a ordem limite só executa quando o "
    "preço passa um pouquinho dela; a execução real ainda pode ser diferente (fila maior, ordem parcial).",
    NOTA_HIST,
]


def preco_br(px: float) -> str:
    return moeda_br(px, 0 if px >= 1000 else 2)


def dia_curto(d: str) -> str:
    return f"{d[8:10]}/{d[5:7]}"


def _f(x, padrao=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return padrao


def _buf():
    return {"ops": 0, "taxas": 0.0, "fech": [], "liq": [], "ev": []}


# ====================================================================== dados
class Funding:
    """Financiamento de hora em hora: [(ms, taxa)] em ordem."""

    def __init__(self, pares=None):
        self.t = [a for a, _ in pares or []]
        self.r = [b for _, b in pares or []]

    @classmethod
    def da_api(cls, lista):
        d = {}
        for x in lista or []:
            try:
                d[int(x["time"])] = float(x["fundingRate"])
            except (KeyError, TypeError, ValueError):
                continue
        return cls(sorted(d.items()))

    def entre(self, a, b):
        i = bisect.bisect_left(self.t, a)
        j = bisect.bisect_right(self.t, b)
        return list(zip(self.t[i:j], self.r[i:j]))


def velas_da_api(lista, intervalo, agora):
    """[(t, T, o, h, l, c)] só das velas já fechadas antes de `agora`, em ordem, sem as quebradas."""
    passo = hl.INTERVALO_MS[intervalo]
    out = {}
    for c in lista or []:
        try:
            t = int(c["t"])
            o, h, l, f = float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])
        except (KeyError, TypeError, ValueError):
            continue
        if t + passo > agora or min(o, h, l, f) <= 0:
            continue
        h, l = max(h, o, f), min(l, o, f)
        out[t] = (t, t + passo - 1, o, h, l, f)
    return [out[k] for k in sorted(out)]


# ====================================================================== o robô
class Robo:
    """Um robô (uma versão). O estado `s` é um dict simples (vai para o JSON do estado); os métodos o mudam no lugar."""

    def __init__(self, cfg, lev_max=40):
        self.cfg = cfg
        self.id = cfg["id"]
        self.nome = cfg["nome"]
        self.tipo = cfg["tipo"]
        self.moeda = cfg["moeda"]
        self.spot = cfg["mercado"] == "spot"
        self.alav = min(ALAV_MAX, cfg.get("alav", 1))
        self.mmr = 1 / (2 * max(1, lev_max))
        tx = TAXAS[cfg["mercado"]]
        self.f_lim, self.f_mer = tx["limite"], tx["mercado"]

    # ------------------------------------------------------------------ contabilidade
    def novo(self, ate):
        s = {"ate": int(ate), "ini": False, "morta": False, "px": None, "degraus": 0, "compras": 0, "ciclos": 0,
             "fund": 0.0, "dia": {"d": None, "n": 0, "lucro": 0.0}, "buf": _buf()}
        if self.spot:
            s.update(caixa=CAPITAL, moeda=0.0, base=0.0)
        else:
            s.update(C=CAPITAL, p=0.0, e=0.0)
        return s

    def patrimonio(self, s, px):
        if s["morta"]:
            return 0.0
        if self.spot:
            return s["caixa"] + s["moeda"] * px
        return s["C"] + s["p"] * (px - s["e"])

    def preco_medio(self, s):
        if self.spot:
            return s["base"] / s["moeda"] if s["moeda"] > 1e-12 else None
        return s["e"] if abs(s["p"]) > 1e-12 else None

    def negociar(self, s, qtd, px, tipo, t):
        """Compra (qtd > 0) ou vende (qtd < 0) `qtd` da moeda a `px`; a mercado com deslize. Devolve o resultado
        realizado (venda no à vista ou redução no perpétuo; 0 nas outras)."""
        if abs(qtd) <= 0:
            return 0.0
        f = self.f_lim if tipo == "limite" else self.f_mer
        des = DESLIZE if tipo == "mercado" else 0.0
        exe = px * (1 + des) if qtd > 0 else px * (1 - des)
        taxa = abs(qtd) * exe * f
        b = s["buf"]
        b["ops"] += 1
        b["taxas"] += taxa + abs(qtd) * px * des
        res = 0.0
        if self.spot:
            if qtd > 0:
                s["caixa"] -= qtd * exe + taxa
                s["moeda"] += qtd
                s["base"] += qtd * exe
            else:
                q = min(-qtd, s["moeda"])
                medio = s["base"] / s["moeda"] if s["moeda"] > 0 else exe
                s["caixa"] += q * exe - taxa
                s["base"] -= q * medio
                s["moeda"] -= q
                res = q * (exe - medio) - taxa
                if s["moeda"] < 1e-12:
                    s["moeda"], s["base"] = 0.0, 0.0
        else:
            p, e = s["p"], s["e"]
            s["C"] -= taxa
            if p == 0 or (p > 0) == (qtd > 0):
                s["e"] = (abs(p) * e + abs(qtd) * exe) / (abs(p) + abs(qtd))
                s["p"] = p + qtd
            else:
                fecha = min(abs(qtd), abs(p))
                res = fecha * (exe - e) * (1 if p > 0 else -1)
                s["C"] += res
                novo = p + qtd
                if abs(novo) < 1e-12:
                    s["p"], s["e"] = 0.0, 0.0
                elif (novo > 0) != (p > 0):  # virou de lado
                    s["p"], s["e"] = novo, exe
                else:
                    s["p"] = novo
                res -= taxa
        return res

    def comprar_dolares(self, s, dolares, px, tipo, t):
        f = self.f_lim if tipo == "limite" else self.f_mer
        exe = px * (1 + (DESLIZE if tipo == "mercado" else 0.0))
        if self.spot:
            dolares = min(dolares, s["caixa"])
        if dolares <= 0.01:
            return 0.0
        q = dolares / (exe * (1 + f))
        self.negociar(s, q, px, tipo, t)
        return q

    def liq(self, s):
        """Preço de liquidação da posição do perpétuo (None sem posição ou no à vista)."""
        if self.spot or s["morta"] or abs(s["p"]) < 1e-12:
            return None
        p, e, C, mmr = s["p"], s["e"], s["C"], self.mmr
        if p > 0:
            return max(0.0, (p * e - C) / (p * (1 - mmr)))
        return (C - p * e) / (-p * (1 + mmr))

    def liquidar(self, s, t, px):
        perda = max(0.0, s["C"])
        s["buf"]["liq"].append({"em": t, "moeda": self.moeda, "perda": round(perda, 2)})
        lado = "comprada" if s["p"] > 0 else "vendida"
        self.evento(s, t, "liquidou", f"{self.nome}: liquidada a {preco_br(px)} (posição {lado}); a conta perdeu os "
                                      f"{moeda_br(perda)} de margem e parou.")
        s.update(morta=True, C=0.0, p=0.0, e=0.0)

    def evento(self, s, t, tipo, texto):
        s["buf"]["ev"].append([int(t), tipo, texto])

    # ------------------------------------------------------------------ resumo do dia (eventos agregados)
    def _virar_dia(self, s, t):
        d = dia_de(t)
        dd = s["dia"]
        if dd["d"] is None:
            dd["d"] = d
            return
        if d == dd["d"]:
            return
        n, lucro = dd["n"], dd["lucro"]
        if n:
            dia = dia_curto(dd["d"])
            if self.tipo == "grade":
                par = (f"lucro de {moeda_br(lucro)} nos pares que fecharam" if abs(lucro) >= 0.005
                       else "nenhum par fechou")
                self.evento(s, t - 1, "fechou" if abs(lucro) >= 0.005 else "comprou",
                            f"{self.nome}: {n} {'degrau executado' if n == 1 else 'degraus executados'} no dia {dia}, {par}.")
            elif self.tipo == "martingale":
                if n == 1:
                    self.evento(s, t - 1, "fechou", f"{self.nome}: ciclo fechado com +{pct_br(self.cfg['alvo'])} "
                                                    f"({moeda_br(lucro)}) no dia {dia}.")
                else:
                    self.evento(s, t - 1, "fechou", f"{self.nome}: {n} ciclos fechados no dia {dia}, lucro de "
                                                    f"{moeda_br(lucro)}.")
        s["dia"] = {"d": d, "n": 0, "lucro": 0.0}

    # ------------------------------------------------------------------ início
    def iniciar(self, s, t, px):
        s["ini"] = True
        if self.tipo == "grade":
            self.montar_grade(s, px, t)
        elif self.tipo == "dca":
            s["prox"] = t
        elif self.tipo == "queda":
            s.setdefault("prox", 0)
            s.setdefault("max", {})
        elif self.tipo == "martingale":
            s["fase"] = "esperando"

    # ------------------------------------------------------------------ grade
    def montar_grade(self, s, px, t):
        """Monta (ou remonta) a grade em volta de `px`: linhas L[0..n], intervalo k entre L[k] e L[k+1]; `cheio[k]`
        = o intervalo tem a moeda (ordem de venda em L[k+1]); vazio = ordem de compra em L[k]. Abaixo do preço,
        vazios; acima, cheios. No à vista compra a mercado a moeda das vendas; no perpétuo (neutra) começa sem
        posição: "cheio" acima quer dizer ordem de venda que abre a posição vendida."""
        n, a = self.cfg["degraus"], self.cfg["faixa"]
        lo, hi = px * (1 - a), px * (1 + a)
        L = [lo + (hi - lo) * i / n for i in range(n + 1)]
        meio = n // 2
        acima = n - meio
        cheio = [k >= meio for k in range(n)]
        ab = [None] * n
        if self.spot:
            s_eff = sum(L[k] * (1 + self.f_lim) for k in range(meio))
            pb = px * (1 + DESLIZE) * (1 + self.f_mer)
            ps = px * (1 - DESLIZE) * (1 - self.f_mer)
            q = (s["caixa"] + s["moeda"] * pb) / (s_eff + acima * pb)
            if acima * q < s["moeda"]:
                q = (s["caixa"] + s["moeda"] * ps) / (s_eff + acima * ps)
            q *= 0.999
            delta = acima * q - s["moeda"]
            res = 0.0
            if abs(delta) * px > 0.01:
                res = self.negociar(s, delta, px, "mercado", t)
            if delta < 0 and abs(delta) * px > 0.01:
                s["buf"]["fech"].append(res)
            custo = (s["base"] / s["moeda"] if s["moeda"] > 0 else px) * (1 + self.f_mer)
            for k in range(meio, n):
                ab[k] = {"l": "c", "px": custo}
        else:
            q = self.patrimonio(s, px) * self.alav / (max(meio, acima) * px) * 0.999
        s.update(L=L, q=q, cheio=cheio, ab=ab, fora=None, centro=px)

    def _exec_grade(self, s, k, lado, t):
        L, q = s["L"], s["q"]
        if lado == "c":
            px = L[k]
            if self.spot and s["caixa"] < q * px * (1 + self.f_lim) - 1e-9:
                return False
            self.negociar(s, q, px, "limite", t)
            s["cheio"][k] = True
            eff = px * (1 + self.f_lim)
        else:
            px = L[k + 1]
            if self.spot and s["moeda"] < q * 0.999:
                return False
            self.negociar(s, -min(q, s["moeda"]) if self.spot else -q, px, "limite", t)
            s["cheio"][k] = False
            eff = px * (1 - self.f_lim)
        ab = s["ab"][k]
        if ab is None:
            s["ab"][k] = {"l": lado, "px": eff}
        else:
            lucro = q * (eff - ab["px"]) if ab["l"] == "c" else q * (ab["px"] - eff)
            s["buf"]["fech"].append(lucro)
            s["dia"]["lucro"] += lucro
            s["ab"][k] = None
        s["degraus"] += 1
        s["dia"]["n"] += 1
        return True

    def _fecha_grade(self, s, t, c):
        L = s["L"]
        degrau = L[1] - L[0]
        antes = s.get("fora")
        # volta para dentro só quando o preço entra um degrau inteiro (para não piscar a cada minuto na borda)
        if c > L[-1]:
            fora = "cima"
        elif c < L[0]:
            fora = "baixo"
        elif (antes == "cima" and c > L[-1] - degrau) or (antes == "baixo" and c < L[0] + degrau):
            fora = antes
        else:
            fora = None
        if fora == antes:
            return
        if fora and self.cfg.get("recentrar"):
            antes = s["buf"]["taxas"]
            self.montar_grade(s, c, t)
            custo = s["buf"]["taxas"] - antes
            lado = "por cima" if fora == "cima" else "por baixo"
            self.evento(s, t, "reequilibrou", f"{self.nome}: o preço saiu da grade {lado}; recentrou a grade em "
                                              f"{preco_br(c)} (custo de {moeda_br(custo)}).")
            return
        s["fora"] = fora
        if fora == "cima":
            txt = "ficou tudo em dólar" if self.spot else "a grade ficou toda vendida (ganha só se o preço cair)"
            self.evento(s, t, "saiu", f"{self.nome}: o preço saiu da grade por cima ({preco_br(c)}): {txt}.")
        elif fora == "baixo":
            txt = f"ficou tudo em {self.moeda}" if self.spot else "a grade ficou toda comprada"
            self.evento(s, t, "saiu", f"{self.nome}: o preço saiu da grade por baixo ({preco_br(c)}): {txt}.")
        else:
            self.evento(s, t, "entrou", f"{self.nome}: o preço voltou para dentro da grade ({preco_br(c)}).")

    # ------------------------------------------------------------------ DCA com proteção (martingale)
    def _comeca_ciclo(self, s, t, px):
        cfg = self.cfg
        eq = self.patrimonio(s, px)
        soma = sum(cfg["mult"] ** j for j in range(cfg["seguranca"] + 1))
        B = eq * self.alav / soma / 1.003
        if B < 1:
            return
        if self.spot:
            self.comprar_dolares(s, B, px, "mercado", t)
        else:
            self.negociar(s, B / px, px, "mercado", t)
        s.update(fase="ciclo", ref=px, k=0, B=B, eq0=eq)

    def _exec_mart(self, s, chave, px, t):
        cfg = self.cfg
        if chave == "tp":
            q = s["moeda"] if self.spot else s["p"]
            if q <= 0:
                return False
            self.negociar(s, -q, px, "limite", t)
            lucro = self.patrimonio(s, px) - s["eq0"]
            s["buf"]["fech"].append(lucro)
            s["dia"]["n"] += 1
            s["dia"]["lucro"] += lucro
            s["ciclos"] += 1
            s["fase"] = "esperando"
            return True
        j = int(chave[1:])
        dol = s["B"] * cfg["mult"] ** j
        if self.spot:
            if self.comprar_dolares(s, dol, px, "limite", t) <= 0:
                return False
        else:
            self.negociar(s, dol / px, px, "limite", t)
        s["k"] = max(s["k"], j)
        s["compras"] += 1
        if j == cfg["seguranca"]:
            alvo = self.preco_medio(s) * (1 + cfg["alvo"])
            self.evento(s, t, "aviso", f"{self.nome}: usou as {cfg['seguranca']} compras de proteção (queda de "
                                       f"{pct_br(cfg['passo'] * j, 0)}); o caixa acabou e agora espera o preço voltar "
                                       f"a {preco_br(alvo)}.")
        return True

    # ------------------------------------------------------------------ ordens abertas
    def ordens(self, s):
        """[(preço, lado "c"|"v", chave)] das ordens limite abertas."""
        if s["morta"] or not s["ini"]:
            return []
        if self.tipo == "grade":
            L = s["L"]
            return [(L[k + 1], "v", k) if ch else (L[k], "c", k) for k, ch in enumerate(s["cheio"])]
        if self.tipo == "martingale" and s.get("fase") == "ciclo":
            cfg = self.cfg
            out = [(s["ref"] * (1 - cfg["passo"] * j), "c", f"s{j}") for j in range(s["k"] + 1, cfg["seguranca"] + 1)]
            pm = self.preco_medio(s)
            if pm:
                out.append((pm * (1 + cfg["alvo"]), "v", "tp"))
            return out
        return []

    def executar(self, s, chave, px, t):
        if self.tipo == "grade":
            return self._exec_grade(s, chave, "c" if not s["cheio"][chave] else "v", t)
        return self._exec_mart(s, chave, px, t)

    def faixa(self, s):
        """(lo, hi): vela com mínima > lo e máxima < hi não executa nada (nem liquida)."""
        lo, hi = -math.inf, math.inf
        for px, lado, _ in self.ordens(s):
            if lado == "c":
                lo = max(lo, px * (1 - TIQUE))
            else:
                hi = min(hi, px * (1 + TIQUE))
        lq = self.liq(s)
        if lq is not None:
            if s["p"] > 0:
                lo = max(lo, lq)
            else:
                hi = min(hi, lq)
        return lo, hi

    # ------------------------------------------------------------------ o caminho dentro da vela
    def segmento(self, s, t, a, b):
        if b == a:
            return
        falhou = set()
        desce = b < a
        for _ in range(1000):
            if s["morta"]:
                return
            if desce:
                cands = [(px, ch) for px, lado, ch in self.ordens(s) if lado == "c" and ch not in falhou and px * (1 - TIQUE) >= b]
                melhor = max(cands, key=lambda x: x[0]) if cands else None
            else:
                cands = [(px, ch) for px, lado, ch in self.ordens(s) if lado == "v" and ch not in falhou and px * (1 + TIQUE) <= b]
                melhor = min(cands, key=lambda x: x[0]) if cands else None
            lq = self.liq(s)
            if lq is not None:
                if desce and s["p"] > 0 and lq >= b and (melhor is None or lq >= melhor[0]):
                    self.liquidar(s, t, lq)
                    return
                if not desce and s["p"] < 0 and lq <= b and (melhor is None or lq <= melhor[0]):
                    self.liquidar(s, t, lq)
                    return
            if melhor is None:
                return
            if not self.executar(s, melhor[1], melhor[0], t):
                falhou.add(melhor[1])

    def caminho(self, s, t, pts):
        for a, b in zip(pts, pts[1:]):
            self.segmento(s, t, a, b)

    # ------------------------------------------------------------------ uma vela
    def vela(self, s, v, fund=None):
        t, T, o, h, l, c = v
        self._virar_dia(s, t)
        if s["morta"]:
            return
        if not s["ini"]:
            self.iniciar(s, t, o)
        # financiamento (perpétuo), no preço de abertura da vela que começa na hora dele
        if not self.spot and fund is not None and abs(s["p"]) > 1e-12:
            for _, taxa in fund.entre(t, T):
                pag = s["p"] * o * taxa
                s["C"] -= pag
                s["fund"] += pag
            if self.patrimonio(s, o) <= self.mmr * abs(s["p"]) * o:
                self.liquidar(s, t, o)
                return
        # ordens a mercado na abertura
        if self.tipo == "dca":
            if s["compras"] < self.cfg["partes"] and t >= s["prox"]:
                self._compra_dca(s, t, o, f"compra {s['compras'] + 1} de {self.cfg['partes']}")
                s["prox"] += self.cfg["cada"]
        elif self.tipo == "martingale" and s.get("fase") == "esperando":
            self._comeca_ciclo(s, t, o)
        # o caminho do preço: o pior dos dois
        lo, hi = self.faixa(s)
        if not (l > lo and h < hi):
            a = copy.deepcopy(s)
            self.caminho(a, t, [o, l, h, c])
            b = copy.deepcopy(s)
            self.caminho(b, t, [o, h, l, c])
            final = a if self.patrimonio(a, c) <= self.patrimonio(b, c) else b
            s.clear()
            s.update(final)
        if s["morta"]:
            return
        # no fechamento
        if self.tipo == "grade":
            self._fecha_grade(s, t, c)
        elif self.tipo == "queda":
            hr = str(t // HORA * HORA)
            mx = s["max"]
            mx[hr] = max(mx.get(hr, 0.0), h)
            corte = t - self.cfg["janela"]
            for k in [k for k in mx if int(k) + HORA <= corte]:
                del mx[k]
            topo = max(mx.values())
            if (s["compras"] < self.cfg["partes"] and t >= s["prox"] and s["caixa"] > 1
                    and c <= topo * (1 - self.cfg["queda"])):
                abaixo = 1 - c / topo
                self._compra_dca(s, T, c, f"{pct_br(abaixo)} abaixo da máxima de 7 dias; compra {s['compras'] + 1} de "
                                          f"{self.cfg['partes']}")
                s["prox"] = t + self.cfg["cada"]

    def aquecer(self, s, velas):
        """A máxima de 7 dias antes do início (só o DCA na queda)."""
        if self.tipo != "queda":
            return
        mx = s.setdefault("max", {})
        for t, T, o, h, l, c in velas:
            hr = str(t // HORA * HORA)
            mx[hr] = max(mx.get(hr, 0.0), h)

    def _compra_dca(self, s, t, px, onde):
        dol = CAPITAL / self.cfg["partes"]
        if s["caixa"] < 1:
            return
        gasto = min(dol, s["caixa"])
        self.comprar_dolares(s, gasto, px, "mercado", t)
        s["compras"] += 1
        s["degraus"] += 1
        fim = "; agora só segura o bitcoin" if s["compras"] >= self.cfg["partes"] else ""
        self.evento(s, t, "comprou", f"{self.nome}: comprou {moeda_br(gasto)} de {self.moeda} a {preco_br(px)} "
                                     f"({onde}){fim}.")

    # ------------------------------------------------------------------ números para o app
    def extra(self, s):
        px = s.get("px") or 0.0
        pm = self.preco_medio(s)
        if self.spot:
            comprado, caixa = s["moeda"] * px, s["caixa"]
        else:
            comprado, caixa = s["p"] * px, self.patrimonio(s, px)
        out = {"comprado": round(comprado, 2), "caixa": round(caixa, 2),
               "degrausExecutados": s["compras"] if self.tipo == "martingale" else s["degraus"],
               "precoMedio": round(pm, 4) if pm else None,
               "foraDaGrade": bool(s.get("fora")) if self.tipo == "grade" else False}
        if not self.spot:
            out["fundingPago"] = round(s["fund"], 4)
        if self.tipo == "martingale":
            out["ciclos"] = s["ciclos"]
        return out


# ====================================================================== passar velas numa conta
def descarregar(s, curva, ev=None, vid=None):
    b = s["buf"]
    if b["ops"] or b["taxas"]:
        curva.operou(taxa=b["taxas"], n=b["ops"])
    for r in b["fech"]:
        curva.fechou(r)
    for x in b["liq"]:
        curva.liquidou(x["em"], x["moeda"], x["perda"])
    if ev is not None:
        for em, tipo, texto in b["ev"]:
            ev.add(em, tipo, texto, vid)
    s["buf"] = _buf()


def processar(robo, s, curva, velas, fund=None, ev=None):
    """Passa as velas (só as depois de s["ate"]) pela conta. Devolve quantas velas usou."""
    n = 0
    for v in velas:
        t, T, o, h, l, c = v
        if t < s["ate"]:
            continue
        robo.vela(s, v, fund)
        descarregar(s, curva, ev, robo.id)
        if s["morta"]:
            curva.marcar(T, 0.0)
        else:
            curva.marcar(T, min(robo.patrimonio(s, l), robo.patrimonio(s, h)))
            curva.marcar(T, robo.patrimonio(s, c))
        s["px"] = c
        s["ate"] = T + 1
        n += 1
    curva.extra = robo.extra(s)
    return n


# ====================================================================== a rodada
def resolver_pares(ctx, est, erros):
    """Os pares do à vista ("@142"…) pelo spotMetaAndAssetCtxs: o token (UBTC…) contra o USDC (token 0)."""
    if est.get("pares") and ctx.agora - est.get("paresEm", 0) < REFAZER_META_MS:
        return est["pares"]
    pares = dict(est.get("pares") or PARES_PADRAO)
    try:
        r = ctx.cli.spot_meta_e_contextos()
        meta = r[0] if isinstance(r, list) and r else r if isinstance(r, dict) else {}
        idx = {}
        for tk in meta.get("tokens") or []:
            if isinstance(tk, dict) and tk.get("name") not in idx:
                idx[tk.get("name")] = tk.get("index")
        for moeda, nome in TOKENS.items():
            i = idx.get(nome)
            if i is None:
                continue
            for u in meta.get("universe") or []:
                tks = u.get("tokens") if isinstance(u, dict) else None
                if tks and len(tks) == 2 and int(tks[0]) == int(i) and int(tks[1]) == 0 and u.get("name"):
                    pares[moeda] = u["name"]
                    break
        est["pares"], est["paresEm"] = pares, ctx.agora
    except (hl.Erro, KeyError, TypeError, ValueError, IndexError) as e:
        erros.append(f"robos: pares do à vista ({e}); usando {', '.join(f'{k} {v}' for k, v in pares.items())}")
    return pares


def resolver_lev(ctx, est, erros):
    if est.get("levMax") and ctx.agora - est.get("levEm", 0) < REFAZER_META_MS:
        return est["levMax"]
    lev = dict(est.get("levMax") or LEV_MAX_PADRAO)
    try:
        r = ctx.cli.meta_e_contextos()
        meta = r[0] if isinstance(r, list) and r else {}
        for u in meta.get("universe") or []:
            if isinstance(u, dict) and u.get("name") in LEV_MAX_PADRAO and u.get("maxLeverage"):
                lev[u["name"]] = int(_f(u["maxLeverage"], LEV_MAX_PADRAO[u["name"]]))
        est["levMax"], est["levEm"] = lev, ctx.agora
    except (hl.Erro, KeyError, TypeError, ValueError, IndexError) as e:
        erros.append(f"robos: alavancagem máxima ({e}); usando a padrão")
    return lev


def moeda_api(cfg, pares):
    return pares.get(cfg["moeda"], PARES_PADRAO[cfg["moeda"]]) if cfg["mercado"] == "spot" else cfg["moeda"]


def rodar(ctx):
    est, agora, log = ctx.est, ctx.agora, ctx.log
    erros = []
    falhas, sucessos = [], 0
    ev = Eventos(est.get("eventos"))
    pares = resolver_pares(ctx, est, erros)
    lev = resolver_lev(ctx, est, erros)
    vivo = est.setdefault("vivo", {})

    def buscar(coin, intervalo, ini, fim):
        nonlocal sucessos
        try:
            r = velas_da_api(ctx.cli.velas(coin, intervalo, int(ini), int(fim)), intervalo, agora)
            sucessos += 1
            return r
        except hl.Erro as e:
            falhas.append(f"velas {coin} {intervalo}: {e}")
            erros.append(f"robos: velas {coin} {intervalo} ({e})")
            return None

    def buscar_funding(coin, ini, fim):
        nonlocal sucessos
        try:
            r = Funding.da_api(ctx.cli.financiamento(coin, int(ini), int(fim)))
            sucessos += 1
            return r
        except hl.Erro as e:
            falhas.append(f"funding {coin}: {e}")
            erros.append(f"robos: financiamento {coin} ({e})")
            return None

    # ---------------------------------------------------------------- versões novas
    inicio_min = agora // MIN * MIN
    for cfg in VERSOES:
        if cfg["id"] in vivo:
            continue
        robo = Robo(cfg, lev.get(cfg["moeda"], 40))
        s = robo.novo(inicio_min)
        curva = Curva(inicio=agora)
        curva.marcar(agora, CAPITAL)
        if cfg["tipo"] == "queda":
            aq = buscar(moeda_api(cfg, pares), "1h", agora - AQUECER_DIAS * DIA, agora)
            if aq:
                robo.aquecer(s, aq)
        vivo[cfg["id"]] = {"curva": curva.para_json(), "bot": s}
        ev.add(agora, "abriu", f"{cfg['nome']}: começou ao vivo com {moeda_br(CAPITAL)} fictícios.", cfg["id"])
        log(f"  robos: {cfg['id']} começou ao vivo")

    # ---------------------------------------------------------------- ao vivo: alcança de onde parou até agora
    mercados = {}
    for cfg in VERSOES:
        mercados.setdefault((cfg["mercado"], cfg["moeda"]), []).append(cfg)
    for (merc, moeda), cfgs in mercados.items():
        coin = moeda_api(cfgs[0], pares)
        ini = min(vivo[c["id"]]["bot"]["ate"] for c in cfgs if not vivo[c["id"]]["bot"]["morta"]) \
            if any(not vivo[c["id"]]["bot"]["morta"] for c in cfgs) else agora
        if agora - ini < MIN:
            continue
        intervalo = hl.intervalo_para(ini, agora, agora)
        velas = buscar(coin, intervalo, ini, agora)
        if velas is None:
            continue
        fund = None
        if merc == "perp":
            fund = buscar_funding(moeda, ini - HORA, agora)
            if fund is None:
                continue  # sem o financiamento, o perpétuo espera a próxima rodada
        if velas and velas[0][0] > ini + hl.INTERVALO_MS[intervalo]:
            log(f"  robos: {coin} sem velas de {dia_de(ini)} até {dia_de(velas[0][0])} (a API não guarda mais que isso)")
        if intervalo != "1m":
            log(f"  robos: {coin} alcançou o atraso com velas de {intervalo}")
        for cfg in cfgs:
            vv = vivo[cfg["id"]]
            robo = Robo(cfg, lev.get(moeda, 40))
            s, curva = vv["bot"], Curva.de_json(vv["curva"])
            try:
                n = processar(robo, s, curva, velas, fund, ev)
            except Exception as e:  # noqa: BLE001  (uma versão com defeito não derruba as outras)
                erros.append(f"robos: {cfg['id']} ao vivo ({e})")
                continue
            vv["curva"] = curva.para_json()
            log(f"  robos: {cfg['id']} {n} velas de {intervalo}, patrimônio {num_br(curva.ultimo)}")

    # ---------------------------------------------------------------- teste no passado (1 h, ~180 dias)
    hist = est.get("hist") or {}
    faltam = [c for c in VERSOES if c["id"] not in (hist.get("contas") or {})]
    velho = agora - hist.get("em", 0) >= REFAZER_HIST_MS
    if (velho or faltam) and ctx.restante() > SEG_MIN_HIST:
        contas = dict(hist.get("contas") or {})
        refeitas = 0
        ini = agora - HIST_DIAS * DIA
        dados = {}
        for (merc, moeda), cfgs in mercados.items():
            if not velho and not any(c in faltam for c in cfgs):
                continue
            coin = moeda_api(cfgs[0], pares)
            velas = buscar(coin, "1h", ini - AQUECER_DIAS * DIA, agora)
            fund = buscar_funding(moeda, ini - HORA, agora) if merc == "perp" and velas else None
            if not velas or (merc == "perp" and fund is None):
                continue
            dados[(merc, moeda)] = (velas, fund)
        for (merc, moeda), (velas, fund) in dados.items():
            antes = [v for v in velas if v[0] < ini]
            depois = [v for v in velas if v[0] >= ini]
            if not depois:
                continue
            for cfg in mercados[(merc, moeda)]:
                try:
                    robo = Robo(cfg, lev.get(moeda, 40))
                    s = robo.novo(depois[0][0])
                    robo.aquecer(s, antes)
                    curva = Curva(inicio=depois[0][0])
                    processar(robo, s, curva, depois, fund, None)
                    contas[cfg["id"]] = curva.resumo(de=dia_de(depois[0][0]), ate=dia_de(depois[-1][1]),
                                                     aproximado=False, nota=NOTA_HIST)
                    refeitas += 1
                except Exception as e:  # noqa: BLE001
                    erros.append(f"robos: {cfg['id']} teste no passado ({e})")
        if refeitas:
            est["hist"] = {"em": agora if velho or not hist.get("em") else hist["em"], "contas": contas}
            log(f"  robos: teste no passado refeito ({refeitas} versões)")
    elif velho or faltam:
        log("  robos: pouco tempo na rodada; o teste no passado fica para a próxima")

    if falhas and not sucessos:
        raise hl.Erro("sem dados da Hyperliquid: " + "; ".join(falhas[:3]))

    # ---------------------------------------------------------------- saída
    contas_h = (est.get("hist") or {}).get("contas") or {}
    versoes = []
    for cfg in VERSOES:
        vv = vivo.get(cfg["id"])
        curva = Curva.de_json(vv["curva"]) if vv else None
        if curva is not None:
            curva.extra = Robo(cfg, lev.get(cfg["moeda"], 40)).extra(vv["bot"])
            vv["curva"] = curva.para_json()
        versoes.append({"id": cfg["id"], "nome": cfg["nome"], "frase": cfg["frase"], "risco": cfg["risco"],
                        "alav": cfg["alav"], "grupo": cfg["grupo"],
                        "aoVivo": curva.resumo() if curva else None, "historico": contas_h.get(cfg["id"])})
    est["eventos"] = ev.para_json()
    return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": PADRAO, "versoes": versoes,
            "eventos": est["eventos"], "itens": [], "avisos": AVISOS,
            "config": {"frequencia": "a cada 6 h", "moedas": ["BTC", "ETH"], "alavMax": ALAV_MAX,
                       "velas": {"aoVivo": "1m", "historico": "1h"}, "historicoDias": HIST_DIAS,
                       "taxas": TAXAS, "deslize": DESLIZE, "tique": TIQUE,
                       "pares": {k: pares.get(k) for k in ("BTC", "ETH")}},
            "erros": erros}
