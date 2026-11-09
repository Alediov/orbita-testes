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

Revisão de 09/11/2026 (pedido do Alediov, pelos 6 primeiros dias ao vivo):
- réguas (`grupo` "Referência"): só segurar BTC (que é também o "tudo no dia 1" do DCA: os US$ 1.000 que o DCA compra em
  20 semanas, de uma vez) e só segurar ETH;
- grade com saída (`saida`): fecha tudo quando o preço passa SAIDA_ALEM degrau além da borda OU a conta cai SAIDA_QUEDA
  do melhor momento desde a montagem; remonta em volta do preço depois de SAIDA_ESPERA, quando o vai e vem das últimas
  24 h (máxima − mínima ÷ preço) fica em SAIDA_CALMA ou menos;
- grade pela oscilação (`vol` = k): meia-largura = k × a oscilação diária (desvio dos retornos de hora em hora dos
  últimos 7 dias × √24), recentrada toda segunda (Brasília), pagando a troca;
- grade neutra 1× em SOL e HYPE; DCA com o caixa na Aave (os custos e o juro do funding.py);
- a conta por dentro (`extra.porDentro`) em toda conta e as janelas de 30 dias a cada 7 no teste no passado
  (`historico.janelas`, contra o CDI do mesmo período).

Estado (`ctx.est`):
    {"pares": {"BTC": "@142", …}, "paresEm": ms, "levMax": {"BTC": 40}, "levEm": ms,
     "vivo": {id: {"curva": Curva.para_json(), "bot": {estado do robô, "ate": ms já processado}}},
     "hist": {"em": ms, "contas": {id: conta do teste no passado}}, "eventos": [...]}
"""
from __future__ import annotations

import bisect
import copy
import math

import datetime as dt

import hl
import conta as CT
from conta import CAPITAL, DIA, FUSO_MS, HORA, Curva, Eventos, dia_de, moeda_br, num_br, pct_br

try:  # o juro do dólar na Aave e os custos de ir e voltar (os mesmos do funding)
    import funding as FD
except ImportError:  # pragma: no cover
    FD = None

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
HIST_V = 3              # mudar o teste no passado (versões, regras, contas): subir para refazer na próxima rodada
ANO_MS = 365 * DIA

# grade com saída (09/11/2026): fecha tudo quando o preço passa SAIDA_ALEM degraus além da borda da grade OU a conta
# cai SAIDA_QUEDA do melhor momento desde que a grade foi montada; remonta em volta do preço quando, passadas
# SAIDA_ESPERA, a oscilação das últimas 24 h (máxima − mínima, ÷ preço) fica em SAIDA_CALMA ou menos
SAIDA_ALEM = 1
SAIDA_QUEDA = 0.15
SAIDA_CALMA = 0.04
SAIDA_ESPERA = DIA
# grade pela oscilação: largura = k × a oscilação diária (desvio dos retornos de hora em hora × √24) dos últimos 7 dias,
# entre VOL_MIN e VOL_MAX; recentrada toda segunda (Brasília), pagando a troca; sem 24 h de dados, VOL_PADRAO
VOL_DIAS = 7
VOL_PADRAO = 0.025
VOL_MIN, VOL_MAX = 0.02, 0.30
BUF_DIAS = 8            # as velas de 1 h guardadas no estado das versões que precisam delas
# várias janelas no teste no passado
JANELA_DIAS = 30
JANELA_PASSO = 7
JANELA_LISTA = 30

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
    # ---- revisão de 09/11/2026
    {"id": "gsaida1", "nome": "Grade neutra com saída 1×", "tipo": "grade", "mercado": "perp", "moeda": "BTC",
     "faixa": 0.10, "degraus": 20, "recentrar": False, "alav": 1, "risco": "médio", "grupo": "Grade com saída",
     "saida": True,
     "frase": "A grade neutra 1×, mas fecha tudo quando o preço passa um degrau além da grade ou a conta cai 15% do "
              "melhor momento, e só remonta quando o preço acalma (24 h com menos de 4% de vai e vem)."},
    {"id": "gsaida3", "nome": "Grade neutra com saída 3×", "tipo": "grade", "mercado": "perp", "moeda": "BTC",
     "faixa": 0.10, "degraus": 20, "recentrar": False, "alav": 3, "risco": "alto", "grupo": "Grade com saída",
     "saida": True,
     "frase": "A grade neutra 3× com a mesma saída: corta o prejuízo antes da liquidação, mas paga a saída e a volta."},
    {"id": "gvol2", "nome": "Grade BTC pela oscilação (2 dias)", "tipo": "grade", "mercado": "spot", "moeda": "BTC",
     "vol": 2, "degraus": 20, "recentrar": "semana", "alav": 1, "risco": "médio", "grupo": "Grade pela oscilação",
     "frase": "A largura da grade é 2 vezes a oscilação de um dia normal da última semana; toda segunda ela é medida "
              "de novo e a grade é remontada em volta do preço, pagando a troca."},
    {"id": "gvol4", "nome": "Grade BTC pela oscilação (4 dias)", "tipo": "grade", "mercado": "spot", "moeda": "BTC",
     "vol": 4, "degraus": 20, "recentrar": "semana", "alav": 1, "risco": "médio", "grupo": "Grade pela oscilação",
     "frase": "A mesma ideia com a largura de 4 dias normais de oscilação: degraus maiores, sai menos da grade."},
    {"id": "gsol1", "nome": "Grade neutra SOL 1×", "tipo": "grade", "mercado": "perp", "moeda": "SOL", "faixa": 0.10,
     "degraus": 20, "recentrar": False, "alav": 1, "risco": "alto", "grupo": "Grade",
     "frase": "A grade neutra 1× (±10%, 20 degraus) no solana, que sobe e desce mais que o bitcoin."},
    {"id": "ghype1", "nome": "Grade neutra HYPE 1×", "tipo": "grade", "mercado": "perp", "moeda": "HYPE",
     "faixa": 0.10, "degraus": 20, "recentrar": False, "alav": 1, "risco": "alto", "grupo": "Grade",
     "frase": "A grade neutra 1× no HYPE, a moeda da própria Hyperliquid: muito vai e vem, e quedas fortes."},
    {"id": "dcaC", "nome": "DCA semanal com caixa na Aave", "tipo": "dca", "mercado": "spot", "moeda": "BTC",
     "partes": 20, "cada": 7 * DIA, "alav": 1, "risco": "médio", "grupo": "DCA", "caixa": True,
     "frase": "O DCA semanal, mas o dinheiro que espera a vez fica no empréstimo de dólar da Aave (rede Base) rendendo "
              "juro; toda semana saca os US$ 50 da compra, pagando o saque, a ponte e o gás."},
    {"id": "segbtc", "nome": "Só segurar BTC (tudo no dia 1)", "tipo": "segurar", "mercado": "spot", "moeda": "BTC",
     "alav": 1, "risco": "médio", "grupo": "Referência",
     "frase": "Régua: compra US$ 1.000 de bitcoin no primeiro dia e só segura. É também o \"tudo no dia 1\" do DCA: "
              "o mesmo total que o DCA compra em 20 semanas, de uma vez no começo."},
    {"id": "segeth", "nome": "Só segurar ETH", "tipo": "segurar", "mercado": "spot", "moeda": "ETH", "alav": 1,
     "risco": "médio", "grupo": "Referência",
     "frase": "Régua: compra US$ 1.000 de ether no primeiro dia e só segura (para comparar com a grade do ether)."},
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
    "Grade com saída: a grade neutra que fecha tudo quando o preço passa um degrau além dela ou a conta cai 15% do "
    "melhor momento; remonta em volta do preço depois de um dia, quando o vai e vem das últimas 24 h fica abaixo de 4%. "
    "Grade pela oscilação: a largura é k vezes a oscilação de um dia normal da última semana, medida de novo toda "
    "segunda.",
    "Réguas: só segurar bitcoin (o mesmo que pôr de uma vez, no primeiro dia, o total que o DCA compra em 20 semanas) e "
    "só segurar ether. Servem para ver se o robô ganhou de simplesmente comprar e esperar.",
    "Janelas: além dos 180 dias inteiros, o teste no passado é cortado em janelas de 30 dias, uma começando a cada 7, e "
    "cada uma é comparada com o CDI do mesmo período: mostra se o resultado depende de um mês de sorte.",
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
    "Grade com saída: a saída e a volta pagam taxa e deslize, e o preço pode voltar logo depois da saída (o robô fica "
    "de fora). Caixa na Aave: o juro é a média do dia e o custo de ir e voltar é aproximado (o gás muda).",
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


def _acc():
    """A conta por dentro (US$): `tx` taxas da corretora, `des` deslize, `pares` lucro bruto (sem taxas) dos pares fechados
    da grade ou dos ciclos do DCA com proteção, `liq` margem perdida em liquidações, `juros` da Aave, `ponte` saque,
    ponte e gás da Aave. O financiamento vem de `s["fund"]`."""
    return {"tx": 0.0, "des": 0.0, "pares": 0.0, "liq": 0.0, "juros": 0.0, "ponte": 0.0}


def semana_de(t):
    """O número da semana (segunda a domingo, em Brasília)."""
    return ((t + FUSO_MS) // DIA + 3) // 7


def _hora(t):
    return str(t // HORA * HORA)


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
        self.saida = bool(cfg.get("saida"))
        self.vol = cfg.get("vol")
        self.caixa_aave = bool(cfg.get("caixa"))
        self.juro = lambda t: 0.0  # o juro ao ano do dólar na Aave em t (a rodada troca pelo da Aave)

    @property
    def usa_buffer(self):
        return self.tipo == "grade" and (self.saida or bool(self.vol))

    # ------------------------------------------------------------------ contabilidade
    def novo(self, ate):
        s = {"ate": int(ate), "ini": False, "morta": False, "px": None, "degraus": 0, "compras": 0, "ciclos": 0,
             "fund": 0.0, "dia": {"d": None, "n": 0, "lucro": 0.0}, "buf": _buf(), "acc": _acc()}
        if self.spot:
            s.update(caixa=CAPITAL, moeda=0.0, base=0.0, aave=0.0)
        else:
            s.update(C=CAPITAL, p=0.0, e=0.0)
        return s

    def patrimonio(self, s, px):
        if s["morta"]:
            return 0.0
        if self.spot:
            return s["caixa"] + s["moeda"] * px + s.get("aave", 0.0)
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
        a = s.setdefault("acc", _acc())
        a["tx"] += taxa
        a["des"] += abs(qtd) * px * des
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
        # a perda da LIQUIDAÇÃO é o que ainda restava na conta no preço de liquidação (≈ a margem de manutenção); o
        # prejuízo da posição até ali já estava no patrimônio (até 09/11/2026 contava o colateral inteiro, `C`, e a
        # conta por dentro punha na liquidação o que era o preço)
        perda = max(0.0, self.patrimonio(s, px))
        s["buf"]["liq"].append({"em": t, "moeda": self.moeda, "perda": round(perda, 2)})
        s.setdefault("acc", _acc())["liq"] += perda
        lado = "comprada" if s["p"] > 0 else "vendida"
        self.evento(s, t, "liquidou", f"{self.nome}: liquidada a {preco_br(px)} (posição {lado}); a conta perdeu os "
                                      f"{moeda_br(perda)} que restavam e parou.")
        s.update(morta=True, C=0.0, p=0.0, e=0.0)

    def evento(self, s, t, tipo, texto, motivo=None):
        s["buf"]["ev"].append([int(t), tipo, texto] + ([motivo] if motivo else []))

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
        elif self.tipo == "segurar":
            q = self.comprar_dolares(s, s["caixa"], px, "mercado", t)
            s["compras"] += 1
            self.evento(s, t, "comprou", f"{self.nome}: comprou {num_br(q, 6)} {self.moeda} a {preco_br(px)} com o dinheiro "
                                         f"todo; agora só segura.")

    # ------------------------------------------------------------------ buffer de velas de 1 h (saída e oscilação)
    def guardar_vela(self, s, t, h, l, c):
        hb = s.setdefault("hb", {})
        k = _hora(t)
        x = hb.get(k)
        hb[k] = [max(x[0], h), min(x[1], l), c] if x else [h, l, c]
        if len(hb) > BUF_DIAS * 24 + 4:
            corte = t - BUF_DIAS * DIA
            for kk in [kk for kk in hb if int(kk) < corte]:
                del hb[kk]

    def vol_dia(self, s, t):
        """A oscilação diária dos últimos VOL_DIAS dias: desvio dos retornos de hora em hora × √24 (None sem 24 h)."""
        hb = s.get("hb") or {}
        corte = t - VOL_DIAS * DIA
        cs = [hb[k][2] for k in sorted(hb, key=int) if int(k) >= corte]
        rs = [math.log(b / a) for a, b in zip(cs, cs[1:]) if a > 0 and b > 0]
        if len(rs) < 24:
            return None
        m = sum(rs) / len(rs)
        return math.sqrt(sum((r - m) ** 2 for r in rs) / (len(rs) - 1)) * math.sqrt(24)

    def oscilacao_24h(self, s, t, px):
        hb = s.get("hb") or {}
        corte = t - DIA + HORA
        xs = [v for k, v in hb.items() if int(k) >= corte]
        if not xs or px <= 0:
            return None
        return (max(x[0] for x in xs) - min(x[1] for x in xs)) / px

    def largura(self, s, t):
        """A meia-largura da grade (fração): fixa ou, nas versões pela oscilação, k × a oscilação diária."""
        if not self.vol:
            return self.cfg["faixa"]
        v = self.vol_dia(s, t)
        s["volDia"] = round(v, 6) if v is not None else None
        return min(VOL_MAX, max(VOL_MIN, self.vol * (v if v is not None else VOL_PADRAO)))

    # ------------------------------------------------------------------ grade
    def montar_grade(self, s, px, t):
        """Monta (ou remonta) a grade em volta de `px`: linhas L[0..n], intervalo k entre L[k] e L[k+1]; `cheio[k]`
        = o intervalo tem a moeda (ordem de venda em L[k+1]); vazio = ordem de compra em L[k]. Abaixo do preço,
        vazios; acima, cheios. No à vista compra a mercado a moeda das vendas; no perpétuo (neutra) começa sem
        posição: "cheio" acima quer dizer ordem de venda que abre a posição vendida."""
        n, a = self.cfg["degraus"], self.largura(s, t)
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
                ab[k] = {"l": "c", "px": custo, "raw": px}
        else:
            q = self.patrimonio(s, px) * self.alav / (max(meio, acima) * px) * 0.999
        s.update(L=L, q=q, cheio=cheio, ab=ab, fora=None, centro=px, faixa=a, picoG=self.patrimonio(s, px),
                 sem=semana_de(t))

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
            s["ab"][k] = {"l": lado, "px": eff, "raw": px}
        else:
            lucro = q * (eff - ab["px"]) if ab["l"] == "c" else q * (ab["px"] - eff)
            raw = ab.get("raw", ab["px"])
            s.setdefault("acc", _acc())["pares"] += q * (px - raw) if ab["l"] == "c" else q * (raw - px)
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
        if fora and self.cfg.get("recentrar") is True:
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

    def _sair_grade(self, s, t, c):
        """Grade com saída: fecha tudo se o preço passou SAIDA_ALEM degraus além da borda ou a conta caiu SAIDA_QUEDA do
        melhor momento desde a montagem. Devolve True se saiu."""
        L = s["L"]
        degrau = L[1] - L[0]
        eq = self.patrimonio(s, c)
        s["picoG"] = max(s.get("picoG") or eq, eq)
        motivo = None
        if c > L[-1] + SAIDA_ALEM * degrau:
            motivo, txt = "grade", f"o preço passou {SAIDA_ALEM} degrau acima da grade ({preco_br(c)})"
        elif c < L[0] - SAIDA_ALEM * degrau:
            motivo, txt = "grade", f"o preço passou {SAIDA_ALEM} degrau abaixo da grade ({preco_br(c)})"
        elif s["picoG"] > 0 and eq < s["picoG"] * (1 - SAIDA_QUEDA):
            motivo, txt = "stop", f"a conta caiu {pct_br(1 - eq / s['picoG'])} do melhor momento"
        if not motivo:
            return False
        antes = s["acc"]["tx"] + s["acc"]["des"]
        q = s["moeda"] if self.spot else s["p"]
        if abs(q) > 1e-12:
            self.negociar(s, -q, c, "mercado", t)
        custo = s["acc"]["tx"] + s["acc"]["des"] - antes
        s["parada"] = {"desde": int(t), "motivo": motivo}
        s.update(fora=None)
        self.evento(s, t, "saiu", f"{self.nome}: {txt}; fechou tudo (custo de {moeda_br(custo)}) e espera o preço "
                                  f"acalmar para montar de novo.", motivo)
        return True

    def _remontar(self, s, t, c):
        """Grade parada: remonta em volta do preço depois de SAIDA_ESPERA, com a oscilação de 24 h ≤ SAIDA_CALMA."""
        p = s["parada"]
        if t - p["desde"] < SAIDA_ESPERA:
            return
        osc = self.oscilacao_24h(s, t, c)
        if osc is None or osc > SAIDA_CALMA:
            return
        s["parada"] = None
        self.montar_grade(s, c, t)
        s["remontes"] = s.get("remontes", 0) + 1
        self.evento(s, t, "entrou", f"{self.nome}: o preço acalmou ({pct_br(osc)} de vai e vem em 24 h); montou a grade de "
                                    f"novo em volta de {preco_br(c)}.")

    def _recentrar_semana(self, s, t, c):
        if s.get("sem") == semana_de(t):
            return
        antes = s["acc"]["tx"] + s["acc"]["des"]
        self.montar_grade(s, c, t)
        custo = s["acc"]["tx"] + s["acc"]["des"] - antes
        v = s.get("volDia")
        self.evento(s, t, "reequilibrou", f"{self.nome}: segunda-feira; mediu a oscilação ({pct_br(v) if v is not None else 'sem dados'} "
                                          f"por dia) e remontou a grade com ±{pct_br(s['faixa'])} em volta de {preco_br(c)} "
                                          f"(custo de {moeda_br(custo)}).")

    # ------------------------------------------------------------------ caixa na Aave (DCA)
    def _custo_caixa(self, v, ida):
        if FD is None:
            return 0.0
        return FD.custo_caixa(v, ida)

    def _para_aave(self, s, t):
        v = s["caixa"]
        if v <= 1:
            return
        c = self._custo_caixa(v, True)
        s["caixa"] = 0.0
        s["aave"] = s.get("aave", 0.0) + max(0.0, v - c)
        s["acc"]["ponte"] += c
        s["buf"]["ops"] += 1
        s["buf"]["taxas"] += c
        self.evento(s, t, "caixa", f"{self.nome}: pôs {moeda_br(v - c)} no empréstimo de dólar da Aave a "
                                   f"{pct_br(self.juro(t))} ao ano (saque, ponte e gás: {moeda_br(c)}).")

    def _da_aave(self, s, t, dolares, tudo=False):
        a = s.get("aave", 0.0)
        if a <= 0:
            return
        volta = 0.10 if FD is None else FD.CAIXA_VOLTA
        ponte = 0.0 if FD is None else FD.PONTE
        v = a if tudo else min(a, (dolares + volta) / max(1e-9, 1 - ponte))
        c = self._custo_caixa(v, False)
        s["aave"] = a - v
        if s["aave"] < 0.01:
            s["aave"] = 0.0
        s["caixa"] += max(0.0, v - c)
        s["acc"]["ponte"] += c
        s["buf"]["ops"] += 1
        s["buf"]["taxas"] += c

    def _render(self, s, t, T):
        a = s.get("aave", 0.0)
        if a <= 0:
            return
        j = a * ((1 + max(0.0, self.juro(t))) ** ((T + 1 - t) / ANO_MS) - 1)
        s["aave"] = a + j
        s["acc"]["juros"] += j

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
        a = s.setdefault("acc", _acc())
        s.update(fase="ciclo", ref=px, k=0, B=B, eq0=eq, c0=a["tx"] + a["des"] + s["fund"])

    def _exec_mart(self, s, chave, px, t):
        cfg = self.cfg
        if chave == "tp":
            q = s["moeda"] if self.spot else s["p"]
            if q <= 0:
                return False
            self.negociar(s, -q, px, "limite", t)
            lucro = self.patrimonio(s, px) - s["eq0"]
            a = s.setdefault("acc", _acc())
            a["pares"] += lucro + (a["tx"] + a["des"] + s["fund"] - s.get("c0", a["tx"] + a["des"] + s["fund"]))
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
        if s["morta"] or not s["ini"] or s.get("parada"):
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
        s.setdefault("acc", _acc())
        if self.usa_buffer:
            self.guardar_vela(s, t, h, l, c)
        if not s["ini"]:
            self.iniciar(s, t, o)
        # o juro do dinheiro parado na Aave
        if self.spot and s.get("aave"):
            self._render(s, t, T)
        # grade parada (com saída): sem ordens; só espera o preço acalmar
        if s.get("parada"):
            if not self.spot and abs(s["p"]) > 1e-12:
                s["parada"] = None  # (não deveria acontecer: a saída zera a posição)
            else:
                self._remontar(s, T, c)
                return
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
            if self.saida and self._sair_grade(s, T, c):
                return
            if self.cfg.get("recentrar") == "semana":
                self._recentrar_semana(s, T, c)
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
        """A máxima de 7 dias antes do início (DCA na queda) e as velas de 1 h (grade com saída e pela oscilação)."""
        if self.usa_buffer:
            for t, T, o, h, l, c in velas:
                self.guardar_vela(s, t, h, l, c)
            return
        if self.tipo != "queda":
            return
        mx = s.setdefault("max", {})
        for t, T, o, h, l, c in velas:
            hr = str(t // HORA * HORA)
            mx[hr] = max(mx.get(hr, 0.0), h)

    def _compra_dca(self, s, t, px, onde):
        dol = CAPITAL / self.cfg["partes"]
        ultima = s["compras"] + 1 >= self.cfg["partes"]
        if self.caixa_aave and s["caixa"] < dol - 0.01:
            self._da_aave(s, t, dol - s["caixa"], tudo=ultima)
        if s["caixa"] < 1:
            return
        gasto = min(dol, s["caixa"])
        self.comprar_dolares(s, gasto, px, "mercado", t)
        s["compras"] += 1
        if self.caixa_aave and not s.get("foiAave") and not ultima:
            s["foiAave"] = True
            self._para_aave(s, t)
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
        if self.saida:
            out["parada"] = bool(s.get("parada"))
            out["remontes"] = s.get("remontes", 0)
        if self.vol or self.saida:
            out["faixaAgora"] = round(s["faixa"], 6) if s.get("faixa") else None
        if self.vol:
            out["volDia"] = s.get("volDia")
        if self.caixa_aave:
            out["naAave"] = round(s.get("aave", 0.0), 2)
        out["porDentro"] = self.por_dentro(s, px)
        return out

    def por_dentro(self, s, px):
        """De onde veio o resultado (US$), ver FORMATO.md: resultado = pares + financiamento + juros − taxas − deslize −
        ponte − liquidações + preço (o `preco` é o que sobra: o ganho ou a perda da moeda que a conta segura)."""
        a = s.get("acc") or _acc()
        resultado = self.patrimonio(s, px) - CAPITAL if px else 0.0
        fin = -s.get("fund", 0.0)
        custos = a["tx"] + a["des"] + a["ponte"]
        preco = resultado - (a["pares"] + fin + a["juros"] - custos - a["liq"])
        r = lambda x: round(x, 4) + 0.0  # noqa: E731  (+ 0.0: sem "-0.0" no JSON)
        out = {"pares": r(a["pares"]), "preco": r(preco), "financiamento": r(fin), "juros": r(a["juros"]),
               "taxas": r(a["tx"]), "deslize": r(a["des"]), "ponte": r(a["ponte"]), "liquidacoes": r(a["liq"]),
               "custos": r(custos), "resultado": r(resultado)}
        if a.get("estimado"):
            out["estimado"] = True
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
        for x in b["ev"]:
            ev.add(x[0], x[1], x[2], vid)
            if len(x) > 3 and x[3]:
                ev.lista[-1]["motivo"] = x[3]
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


# ====================================================================== várias janelas
def janelas(conta, cdi, cdi_ano, dias=JANELA_DIAS, passo=JANELA_PASSO):
    """Janelas de `dias` dias começando a cada `passo` dias dentro da série diária da conta (o teste no passado): o
    retorno de cada uma, o CDI no MESMO período (a série do BC dia a dia, como em conta.metricas) e se ganhou dele.
    None com menos de uma janela inteira."""
    if not conta or not conta.get("serie"):
        return None
    pts = {dt.date.fromisoformat(d): float(v) for d, v in conta["serie"]}
    ini, fim = min(pts), max(pts)
    if (fim - ini).days < dias:
        return None
    valores, v, d = {}, None, ini
    while d <= fim:
        v = pts.get(d, v)
        valores[d] = v
        d += dt.timedelta(days=1)
    ultimo, primeiro = (max(cdi), min(cdi)) if cdi else ("", "")
    diaria = (1 + cdi_ano) ** (1 / 252) - 1
    fator = {}
    d = ini
    while d <= fim:
        fator[d] = 1 + CT._cdi_do_dia(cdi, d, primeiro, ultimo, diaria)
        d += dt.timedelta(days=1)
    lista = []
    a = ini
    while a + dt.timedelta(days=dias) <= fim:
        b = a + dt.timedelta(days=dias)
        va, vb = valores[a], valores[b]
        ind = 1.0
        x = a
        while x < b:
            ind *= fator[x]
            x += dt.timedelta(days=1)
        ret = vb / va - 1 if va > 0 else -1.0
        lista.append([a.isoformat(), round(ret, 6), round(ind - 1, 6)])
        a += dt.timedelta(days=passo)
    if not lista:
        return None
    rets = sorted(x[1] for x in lista)
    n = len(rets)
    mediana = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    vence = sum(1 for x in lista if (1 + x[1]) > (1 + x[2]))
    pior = min(lista, key=lambda x: x[1])
    melhor = max(lista, key=lambda x: x[1])
    return {"dias": dias, "passo": passo, "n": n, "venceCdi": vence, "mediana": round(mediana, 6),
            "pior": {"de": pior[0], "retorno": pior[1], "cdi": pior[2]},
            "melhor": {"de": melhor[0], "retorno": melhor[1], "cdi": melhor[2]},
            "lista": lista[-JANELA_LISTA:]}


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
    # o juro do dólar na Aave (só se alguma versão guarda o caixa lá)
    juro = lambda t: 0.0  # noqa: E731
    aave_agora = None
    if FD is not None and any(c.get("caixa") for c in VERSOES):
        g = FD.ler_aave(ctx, est, log, erros)
        tx_aave = FD.taxas_aave(g)
        if tx_aave is not None:
            juro = lambda t: max(0.0, float(tx_aave.taxa("sup:USDC", t) or 0.0))  # noqa: E731
            aave_agora = g.get("atual")

    def robo_de(cfg, moeda=None):
        r = Robo(cfg, lev.get(moeda or cfg["moeda"], 40))
        r.juro = juro
        return r

    # contas ao vivo de antes de 09/11/2026: a conta por dentro começa estimada (sem separar taxa e deslize)
    for vid, vv in vivo.items():
        b = vv.get("bot") or {}
        if "acc" not in b:
            c = Curva.de_json(vv.get("curva"))
            a = _acc()
            a["tx"] = float(c.taxas) if c else 0.0
            a["liq"] = sum(float(x.get("perda") or 0) for x in (c.liq if c else []))
            a["pares"] = sum(c.ganhos) if c else 0.0
            a["estimado"] = True
            b["acc"] = a

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
        robo = robo_de(cfg)
        s = robo.novo(inicio_min)
        curva = Curva(inicio=agora)
        curva.marcar(agora, CAPITAL)
        if cfg["tipo"] == "queda" or robo.usa_buffer:
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
            robo = robo_de(cfg, moeda)
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
    sem_dados = dict(hist.get("semDados") or {})
    faltam = [c for c in VERSOES if c["id"] not in (hist.get("contas") or {})]
    velho = agora - hist.get("em", 0) >= REFAZER_HIST_MS or hist.get("hv") != HIST_V
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
            if velas is not None and not [v for v in velas if v[0] >= ini]:
                for c in cfgs:
                    sem_dados[c["id"]] = (f"A Hyperliquid não devolveu velas de 1 h de {moeda} "
                                          f"{'no perpétuo' if merc == 'perp' else 'no à vista'} nos últimos {HIST_DIAS} dias.")
                continue
            if not velas or (merc == "perp" and fund is None):
                continue
            dados[(merc, moeda)] = (velas, fund)
        for (merc, moeda), (velas, fund) in dados.items():
            antes = [v for v in velas if v[0] < ini]
            depois = [v for v in velas if v[0] >= ini]
            if not depois:
                continue
            dias_dados = (depois[-1][1] - depois[0][0]) / DIA
            for cfg in mercados[(merc, moeda)]:
                try:
                    robo = robo_de(cfg, moeda)
                    s = robo.novo(depois[0][0])
                    robo.aquecer(s, antes)
                    curva = Curva(inicio=depois[0][0])
                    processar(robo, s, curva, depois, fund, None)
                    nota = NOTA_HIST
                    if dias_dados < HIST_DIAS - 10:
                        nota += (f" Só há {dias_dados:.0f} dias de velas de {moeda} na Hyperliquid: o teste no passado é "
                                 f"mais curto que os {HIST_DIAS} dias das outras versões.")
                    contas[cfg["id"]] = curva.resumo(de=dia_de(depois[0][0]), ate=dia_de(depois[-1][1]),
                                                     aproximado=False, nota=nota)
                    sem_dados.pop(cfg["id"], None)
                    refeitas += 1
                except Exception as e:  # noqa: BLE001
                    erros.append(f"robos: {cfg['id']} teste no passado ({e})")
        if refeitas or sem_dados != (hist.get("semDados") or {}):
            est["hist"] = {"em": agora if (velho and refeitas) or not hist.get("em") else hist["em"], "contas": contas,
                           "hv": HIST_V if refeitas else hist.get("hv"), "semDados": sem_dados}
            log(f"  robos: teste no passado refeito ({refeitas} versões)")
    elif velho or faltam:
        log("  robos: pouco tempo na rodada; o teste no passado fica para a próxima")

    if falhas and not sucessos:
        raise hl.Erro("sem dados da Hyperliquid: " + "; ".join(falhas[:3]))

    # ---------------------------------------------------------------- saída
    contas_h = (est.get("hist") or {}).get("contas") or {}
    sem_h = (est.get("hist") or {}).get("semDados") or {}
    cdi = (ctx.ref or {}).get("cdi") or {}
    cdi_ano = CT.cdi_ano_da_serie(cdi, 0.149)
    versoes = []
    for cfg in VERSOES:
        vv = vivo.get(cfg["id"])
        curva = Curva.de_json(vv["curva"]) if vv else None
        if curva is not None:
            curva.extra = robo_de(cfg).extra(vv["bot"])
            vv["curva"] = curva.para_json()
        h = contas_h.get(cfg["id"])
        if h is not None:
            h = dict(h)
            try:
                h["janelas"] = janelas(h, cdi, cdi_ano)
            except (TypeError, ValueError, ZeroDivisionError, OverflowError, KeyError):
                h["janelas"] = None
        v = {"id": cfg["id"], "nome": cfg["nome"], "frase": cfg["frase"], "risco": cfg["risco"],
             "alav": cfg["alav"], "grupo": cfg["grupo"], "moeda": cfg["moeda"],
             "aoVivo": curva.resumo() if curva else None, "historico": h}
        if h is None and sem_h.get(cfg["id"]):
            v["semDados"] = sem_h[cfg["id"]]
        elif vv and curva is not None and vv["bot"].get("ate", 0) <= curva.inicio // MIN * MIN and agora - curva.inicio > DIA:
            v["semDados"] = f"Ainda sem velas de {cfg['moeda']} ao vivo: a Hyperliquid não respondeu desde o começo."
        versoes.append(v)
    est["eventos"] = ev.para_json()
    return {"frase": FRASE, "comoFunciona": COMO_FUNCIONA, "padrao": PADRAO, "versoes": versoes,
            "eventos": est["eventos"], "itens": [], "avisos": AVISOS,
            "config": {"frequencia": "a cada 6 h", "moedas": ["BTC", "ETH", "SOL", "HYPE"], "alavMax": ALAV_MAX,
                       "velas": {"aoVivo": "1m", "historico": "1h"}, "historicoDias": HIST_DIAS,
                       "taxas": TAXAS, "deslize": DESLIZE, "tique": TIQUE,
                       "pares": {k: pares.get(k) for k in ("BTC", "ETH")},
                       "janelas": {"dias": JANELA_DIAS, "passo": JANELA_PASSO},
                       "saida": {"alemDegraus": SAIDA_ALEM, "queda": SAIDA_QUEDA, "calma": SAIDA_CALMA,
                                 "esperaHoras": SAIDA_ESPERA // HORA},
                       "vol": {"dias": VOL_DIAS, "padrao": VOL_PADRAO, "min": VOL_MIN, "max": VOL_MAX},
                       "caixa": {"ida": FD.CAIXA_IDA if FD else None, "volta": FD.CAIXA_VOLTA if FD else None,
                                 "ponte": FD.PONTE if FD else None, "juroAgora": aave_agora}},
            "erros": erros}
