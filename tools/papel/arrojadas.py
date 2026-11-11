"""Pools arrojadas pelo filtro do Marinho (pedido do Alediov, 11/11/2026, pelo vídeo de 04/11 do Canal do Marinho:
"escolhe pool de risco, ~300% ao ano, por filtro: volume de US$ 100 mil+ por dia e constante, não só picos; meses de
histórico; a maior carteira abaixo de ~10% do supply; site e redes vivos"). SÓ no papel, como o resto do pools.py.

Uma vez por dia (o dia fechado do GeckoTerminal, em UTC), na mesma rodada do pools.py:

1. **Atualiza** as posições abertas com a vela diária de cada pool (`/ohlcv/day`, o preço da base em US$; a cotação
   pelo preço do ether ou do bitcoin do dia, ou 1 nos dólares estáveis): posição de faixa inteira (como um pool v2):
   valor = segurar × 2√k/(1+k), k = a variação da base ÷ a da cotação; taxas = (nossa parte da liquidez) × volume do
   dia × taxa do pool. Aproximado: num pool v3 a liquidez concentrada de outros ganha mais que a nossa de faixa inteira,
   e o volume é o do GeckoTerminal (não troca a troca).
2. **Sai** das posições que completaram os 7 dias (ou cujo pool sumiu / caiu 95%: conta como perda).
3. **Escolhe** o pool do dia: a lista dos pools da Base de maior volume (`/networks/base/pools`, 2 páginas) →
   pré-filtro pelos atributos (um token fora dos grandes, volume 24 h ≥ US$ 100 mil, liquidez ≥ US$ 50 mil, idade ≥ 60
   dias, taxas estimadas ≥ 100% ao ano) → para até `MAX_FUNDO` deles, as velas de 30 dias (mediana ≥ US$ 100 mil, ≥ 24
   de 30 dias com US$ 50 mil+, a última semana ≥ metade da mediana: "constante, não só picos") e os donos do token
   (`/tokens/<x>/info`: os 10 maiores com até 40% — o GeckoTerminal não dá a maior carteira sozinha; aproximação do "abaixo
   de 10%"). Entre os que passam, um sorteado pela data. O CONTROLE sorteia entre os do pré-filtro de volume e taxa, sem
   idade, constância nem donos: diz se o filtro ajuda.
4. **Entra** no preço de fechamento do dia, pagando a troca de metade (taxa do pool + deslize pelo tamanho + 0,2%) e o gás.

Versões (US$ 1.000 cada, grupo "Arrojada (Marinho)"): `arrEscada` (o padrão: o saldo em 7 partes, cada dia uma parte
entra no pool do dia por 7 dias), `arrSemana` (tudo num pool por semana, toda segunda), `arrControle` (a escada sem o
filtro). Sem teste no passado: não dá para saber quais pools passariam no filtro em cada dia de antes sem cair no viés de
só ver os que sobreviveram (`historico` null, com a nota). Os campos das respostas do GeckoTerminal foram escritos sem
acesso daqui: a 1ª rodada registra a estrutura no log.
"""
from __future__ import annotations

import datetime as dt
import math
import random

import rede
from conta import CAPITAL, DIA, Curva, dia_de, moeda_br, num_br

POOL_ID = "arrojada"
GRUPO = "Arrojada (Marinho)"
GRANDES = {"WETH", "ETH", "USDC", "USDT", "USDBC", "DAI", "CBBTC", "WBTC", "TBTC", "EURC", "WSTETH", "CBETH", "RETH",
           "WEETH", "EZETH", "USDS", "USDE", "SUSDE", "GHO", "LUSD", "FRAX", "PYUSD"}
ESTAVEIS = {"USDC", "USDT", "USDBC", "DAI", "USDS", "USDE", "GHO", "LUSD", "FRAX", "PYUSD"}
VOL_MIN = 100_000
VOL_DIA_MIN = 50_000
DIAS_CONSTANTE = 24
LIQ_MIN = 50_000
IDADE_DIAS = 60
APR_MIN = 1.0
TOP10_MAX = 40.0
PAGINAS = 2
MAX_FUNDO = 8
SEGURA_DIAS = 7
PARTES = 7
DESLIZE_FIXO = 0.002
GAS_USD = 0.05
QUEDA_SUMIU = 0.95
MAX_HIST_ESCOLHAS = 30

VERSOES = [
    {"id": "arrEscada", "nome": "Escada de 7 (padrão)", "risco": "alto", "modo": "escada", "filtro": True,
     "frase": "Divide o saldo em 7 partes: todo dia uma parte entra no pool do dia que passou no filtro do Marinho e "
              "fica 7 dias."},
    {"id": "arrSemana", "nome": "Uma por semana", "risco": "alto", "modo": "semana", "filtro": True,
     "frase": "Toda segunda põe o saldo inteiro no pool sorteado entre os que passaram no filtro, por 7 dias."},
    {"id": "arrControle", "nome": "Sem o filtro (controle)", "risco": "alto", "modo": "escada", "filtro": False,
     "frase": "A mesma escada, mas sorteando entre os pools de muito volume e taxa alta, sem olhar idade, constância "
              "nem donos: mostra se o filtro ajuda."},
]
COMO_FUNCIONA = [
    "Pools arrojadas: pares com uma moeda pequena, que pagam muito de taxa (100% ao ano ou mais) porque a moeda oscila e "
    "é muito trocada. O risco é a moeda despencar (perda impermanente) ou ser golpe.",
    "O filtro do Marinho (Canal do Marinho, 04/11/2026): volume de US$ 100 mil por dia e constante, meses de história e "
    "nenhuma carteira dona de boa parte da moeda. Aqui: 24 dos últimos 30 dias com US$ 50 mil ou mais, mediana de US$ "
    "100 mil, a última semana sem cair pela metade, 60 dias de idade e os 10 maiores donos com até 40% (o site só dá os "
    "10 juntos). 'Site e redes vivos' não dá para conferir daqui.",
    "A conta é aproximada: faixa inteira, pelo volume diário do GeckoTerminal e os preços de fechamento; sem teste no "
    "passado (os pools que morreram não aparecem mais nas listas, e o passado sairia otimista).",
    "Ele recomenda arriscar só uma parte pequena do dinheiro (3 a 10%); aqui cada versão usa os US$ 1.000 inteiros para "
    "medir o jeito, não para dizer quanto pôr.",
]


# ------------------------------------------------------------------------------------------------ contas puras
def fator_lp(k: float) -> float:
    """O valor de uma posição de faixa inteira ÷ o de segurar as duas moedas, com a razão de preços k."""
    if k <= 0:
        return 0.0
    return 2 * math.sqrt(k) / (1 + k)


def valor_posicao(p: dict, pb: float, pq: float) -> float:
    """O valor da posição (sem as taxas) com os preços em US$ da base e da cotação."""
    if not p["pb0"] or not p["pq0"]:
        return 0.0
    rb, rq = pb / p["pb0"], pq / p["pq0"]
    segurar = p["v0"] / 2 * rb + p["v0"] / 2 * rq
    return segurar * fator_lp(rb / rq if rq > 0 else 0.0)


def custo_troca(v: float, taxa: float, liquidez: float) -> float:
    """Trocar metade de `v`: a taxa do pool + o deslize pelo tamanho + 0,2% fixo."""
    meia = v / 2
    desl = meia / liquidez if liquidez else 0.01
    return meia * (taxa + DESLIZE_FIXO + min(0.05, desl)) + GAS_USD


def taxa_do_nome(nome: str, padrao: float = 0.003) -> float:
    """"AAA / WETH 1%" → 0,01. Sem a taxa no nome, 0,3% (os pools v2 da Base)."""
    import re
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%\s*$", nome or "")
    if not m:
        return padrao
    return float(m.group(1).replace(",", ".")) / 100


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def simbolos(nome: str) -> tuple[str, str]:
    partes = [p.strip() for p in (nome or "").split("/")]
    if len(partes) < 2:
        return ("", "")
    b = partes[0].split()[0] if partes[0] else ""
    q = partes[1].split()[0] if partes[1] else ""
    return (b, q)


def pre_filtro(at: dict, agora_ms: int) -> tuple[bool, list[str], dict]:
    """Os atributos de um pool da lista → (passa no controle, motivos de recusa do filtro, números)."""
    nome = at.get("name") or ""
    b, q = simbolos(nome)
    vol = num((at.get("volume_usd") or {}).get("h24")) or 0.0
    liq = num(at.get("reserve_in_usd")) or 0.0
    taxa = taxa_do_nome(nome)
    apr = vol * taxa * 365 / liq if liq > 0 else 0.0
    idade = None
    criado = at.get("pool_created_at")
    if criado:
        try:
            t = dt.datetime.fromisoformat(str(criado).replace("Z", "+00:00"))
            idade = (agora_ms / 1000 - t.timestamp()) / 86400
        except ValueError:
            idade = None
    nums = {"nome": nome, "base": b, "cot": q, "volume24h": round(vol), "liquidez": round(liq), "taxa": taxa,
            "apr": round(apr, 3), "idadeDias": round(idade, 1) if idade is not None else None}
    grande = b.upper() in GRANDES and q.upper() in GRANDES
    controle = (not grande) and vol >= VOL_MIN and liq >= LIQ_MIN and apr >= APR_MIN and q.upper() in GRANDES
    motivos = []
    if not controle:
        motivos.append("pré-filtro")
    if idade is None or idade < IDADE_DIAS:
        motivos.append("novo demais")
    return controle, motivos, nums


def constancia(velas: list) -> tuple[bool, dict]:
    """As velas diárias [[ts, o, h, l, c, v]…] (qualquer ordem) → (constante?, números)."""
    vs = [num(v[5]) or 0.0 for v in sorted(velas, key=lambda v: v[0])][-30:]
    if len(vs) < 20:
        return False, {"dias": len(vs)}
    srt = sorted(vs)
    med = srt[len(srt) // 2]
    bons = sum(1 for v in vs if v >= VOL_DIA_MIN)
    ult = sorted(vs[-7:])[3]
    ok = med >= VOL_MIN and bons >= DIAS_CONSTANTE and ult >= med / 2
    return ok, {"mediana": round(med), "diasBons": bons, "ultimaSemana": round(ult)}


def sortear(lista: list, semente: str):
    if not lista:
        return None
    return random.Random(semente).choice(sorted(lista, key=lambda c: c["endereco"]))


# ------------------------------------------------------------------------------------------------ a rodada
class Arrojadas:
    def __init__(self, est: dict, gecko, agora: int, log, erros: list, ev, tempo):
        self.est, self.g, self.agora, self.log, self.erros, self.ev, self.tempo = est, gecko, agora, log, erros, ev, tempo
        self.velas: dict[str, dict] = {}
        self.vistos = est.setdefault("formatos", {})

    # ---------------------------------------------------------------- GeckoTerminal
    def pedir(self, caminho, rotulo):
        r = self.g.gecko(caminho)
        if rotulo not in self.vistos:
            self.vistos[rotulo] = True
            self.log(f"  pools arrojadas: formato do GeckoTerminal ({rotulo}): {rede.estrutura(r, 4)}")
        return r

    def velas_de(self, endereco: str, token: str = "base") -> dict:
        """{dia UTC: (fechamento, volume)} das últimas 40 velas diárias (guardadas na rodada)."""
        chave = f"{endereco}|{token}"
        if chave in self.velas:
            return self.velas[chave]
        r = self.pedir(f"/networks/base/pools/{endereco}/ohlcv/day?aggregate=1&limit=40&currency=usd&token={token}",
                       "ohlcv")
        lista = (((r or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        out = {}
        for v in lista:
            try:
                d = dt.datetime.fromtimestamp(int(v[0]), dt.timezone.utc).strftime("%Y-%m-%d")
                out[d] = (float(v[4]), float(v[5]), int(v[0]) * 1000)
            except (TypeError, ValueError, IndexError):
                continue
        self.velas[chave] = out
        self.velas[chave + "|cru"] = lista
        return out

    def preco_cot(self, p: dict, dia: str) -> float | None:
        """O preço da cotação em US$ no dia: 1 nos dólares estáveis; senão a vela da cotação do próprio pool."""
        if p["cot"].upper() in ESTAVEIS:
            return 1.0
        v = self.velas_de(p["endereco"], "quote").get(dia)
        return v[0] if v else None

    # ---------------------------------------------------------------- dia
    def dia_fechado(self) -> str:
        return dt.datetime.fromtimestamp(self.agora / 1000 - 86400, dt.timezone.utc).strftime("%Y-%m-%d")

    def rodar(self) -> None:
        dia = self.dia_fechado()
        if self.est.get("dia") == dia:
            return
        if not self.tempo():
            return
        try:
            self.atualizar_posicoes(dia)
            esc = self.escolher(dia)
            self.est["escolhas"] = ([esc] + [e for e in self.est.get("escolhas") or [] if e.get("dia") != dia])[:MAX_HIST_ESCOLHAS]
            self.entrar(dia, esc)
            self.marcar()
            self.est["dia"] = dia
        except rede.Erro as e:
            self.erros.append(f"pools arrojadas: {e}")
            self.log(f"  pools arrojadas: parou nesta rodada ({e}); continua na próxima")

    def conta(self, vid) -> dict:
        c = self.est.setdefault("contas", {}).setdefault(vid, {})
        c.setdefault("caixa", CAPITAL)
        c.setdefault("pos", [])
        c.setdefault("curva", None)
        return c

    def atualizar_posicoes(self, dia: str):
        for cfg in VERSOES:
            c = self.conta(cfg["id"])
            curva = Curva.de_json(c["curva"]) or Curva(inicio=self.agora)
            for p in c["pos"]:
                self.andar(p, dia)
            ficam = []
            for p in c["pos"]:
                if p["dias"] >= SEGURA_DIAS or p.get("sumiu"):
                    sai = p["valor"] + p["taxas"]
                    custo = 0.0 if p.get("sumiu") else custo_troca(p["valor"], p["taxa"], p["liquidez"])
                    sai = max(0.0, sai - custo)
                    c["caixa"] += sai
                    curva.extra["taxasHist"] = round(curva.extra.get("taxasHist", 0.0) + p["taxas"], 4)
                    curva.operou(taxa=custo)
                    curva.fechou(sai - p["v0"] - p["custoEntrada"])
                    r = sai / (p["v0"] + p["custoEntrada"]) - 1 if p["v0"] else 0
                    self.ev.add(self.agora, "saiu", f"Saiu de {p['nome']} depois de {p['dias']} dias: "
                                f"{'+' if r >= 0 else ''}{num_br(r * 100, 1)}% ({moeda_br(sai)}"
                                f"{', o pool sumiu ou despencou' if p.get('sumiu') else ''}).", cfg["id"])
                else:
                    ficam.append(p)
            c["pos"] = ficam
            c["curva"] = curva.para_json()

    def marcar(self):
        """O patrimônio de cada versão no fim do dia (depois das saídas e da entrada do dia)."""
        for cfg in VERSOES:
            c = self.conta(cfg["id"])
            curva = Curva.de_json(c["curva"]) or Curva(inicio=self.agora)
            total = c["caixa"] + sum(p["valor"] + p["taxas"] for p in c["pos"])
            curva.marcar(self.agora, total)
            ex = curva.extra
            ex["emPools"] = len(c["pos"])
            ex["caixa"] = round(c["caixa"], 2)
            ex["taxasGanhas"] = round(ex.get("taxasHist", 0.0) + sum(p["taxas"] for p in c["pos"]), 2)
            ex["perdaImp"] = round(sum(p["valor"] - p["segurar"] for p in c["pos"]), 2)
            ex["arrPosicoes"] = [{"nome": p["nome"], "endereco": p["endereco"], "desde": p["desde"], "dias": p["dias"],
                               "valor": round(p["valor"] + p["taxas"], 2), "taxas": round(p["taxas"], 2),
                               "v0": round(p["v0"], 2)} for p in c["pos"]]
            c["curva"] = curva.para_json()

    def andar(self, p: dict, ate: str):
        """Aplica as velas diárias depois do último dia aplicado, até `ate`."""
        if p.get("sumiu"):
            return
        try:
            velas = self.velas_de(p["endereco"], "base")
        except rede.Erro as e:
            if getattr(e, "codigo", None) == 404 or "404" in str(e):
                p["sumiu"] = True
                p["valor"] = 0.0
                return
            raise
        for d in sorted(x for x in velas if p["ultimo"] < x <= ate):
            pb, vol, _ = velas[d]
            pq = self.preco_cot(p, d)
            if pq is None:
                continue
            v = valor_posicao(p, pb, pq)
            seg = p["v0"] / 2 * pb / p["pb0"] + p["v0"] / 2 * pq / p["pq0"]
            if p["liquidez"] > 0:
                p["taxas"] += min(1.0, v / p["liquidez"]) * vol * p["taxa"]
            p["valor"], p["segurar"], p["ultimo"] = v, seg, d
            p["dias"] += 1
            if pb <= p["pb0"] * (1 - QUEDA_SUMIU):
                p["sumiu"] = True
                break

    def escolher(self, dia: str) -> dict:
        agora = self.agora
        lista = []
        for pg in range(1, PAGINAS + 1):
            r = self.pedir(f"/networks/base/pools?page={pg}&sort=h24_volume_usd_desc", "lista")
            lista += (r or {}).get("data") or []
        candidatos, controle, motivos = [], [], {}
        for it in lista:
            at = (it or {}).get("attributes") or {}
            end = (at.get("address") or str(it.get("id", "")).split("_")[-1]).lower()
            if not end.startswith("0x"):
                continue
            ok_ctl, mot, nums = pre_filtro(at, agora)
            nums["endereco"] = end
            if ok_ctl:
                controle.append(nums)
            for m in mot:
                motivos[m] = motivos.get(m, 0) + 1
            if not mot:
                candidatos.append(nums)
        # o fundo (velas e donos) só nos de maior taxa, até MAX_FUNDO
        passaram = []
        for c in sorted(candidatos, key=lambda x: -x["apr"])[:MAX_FUNDO]:
            if not self.tempo():
                break
            ok, cn = constancia(self.velas.get(f"{c['endereco']}|base|cru") or self._cru(c["endereco"]))
            c.update(cn)
            if not ok:
                motivos["volume não constante"] = motivos.get("volume não constante", 0) + 1
                continue
            top = self.top10(c)
            c["top10"] = top
            if top is not None and top > TOP10_MAX:
                motivos["donos concentrados"] = motivos.get("donos concentrados", 0) + 1
                continue
            passaram.append(c)
        filtro = sortear(passaram, f"arrojada|{dia}")
        ctl = sortear(controle, f"controle|{dia}")
        self.log(f"  pools arrojadas: {len(lista)} na lista, {len(controle)} no pré-filtro, {len(passaram)} no filtro; "
                 f"do dia: {filtro['nome'] if filtro else 'nenhum'} (controle: {ctl['nome'] if ctl else 'nenhum'})")
        return {"dia": dia, "em": agora, "vistos": len(lista), "preFiltro": len(controle), "filtro": len(passaram),
                "motivos": motivos, "escolhido": filtro, "controle": ctl,
                "passaram": [{k: p.get(k) for k in ("nome", "endereco", "apr", "volume24h", "liquidez", "idadeDias",
                                                    "mediana", "diasBons", "top10")} for p in passaram[:8]]}

    def _cru(self, endereco):
        self.velas_de(endereco, "base")
        return self.velas.get(f"{endereco}|base|cru") or []

    def top10(self, c) -> float | None:
        """A parte dos 10 maiores donos do token pequeno (o GeckoTerminal, quando informa)."""
        try:
            r = self.pedir(f"/networks/base/pools/{c['endereco']}?include=base_token,quote_token", "pool")
            rel = ((r or {}).get("data") or {}).get("relationships") or {}
            alvo = "base_token" if c["base"].upper() not in GRANDES else "quote_token"
            tid = str(((rel.get(alvo) or {}).get("data") or {}).get("id", "")).split("_")[-1]
            if not tid.startswith("0x"):
                return None
            info = self.pedir(f"/networks/base/tokens/{tid}/info", "info")
            h = ((((info or {}).get("data") or {}).get("attributes") or {}).get("holders") or {})
            d = h.get("distribution_percentage") or {}
            v = num(d.get("top_10"))
            return round(v, 2) if v is not None else None
        except rede.Erro:
            return None

    def entrar(self, dia: str, esc: dict):
        segunda = dt.date.fromisoformat(dia).weekday() == 0
        for cfg in VERSOES:
            alvo = esc.get("escolhido") if cfg["filtro"] else esc.get("controle")
            if not alvo:
                continue
            c = self.conta(cfg["id"])
            if cfg["modo"] == "semana":
                if not segunda or c["pos"]:
                    continue
                v = c["caixa"]
            else:
                total = c["caixa"] + sum(p["valor"] + p["taxas"] for p in c["pos"])
                v = min(c["caixa"], total / PARTES)
            if v < 5:
                continue
            try:
                velas = self.velas_de(alvo["endereco"], "base")
                pb = (velas.get(dia) or (None,))[0]
                tmp = {"cot": alvo["cot"], "endereco": alvo["endereco"]}
                pq = self.preco_cot(tmp, dia)
            except rede.Erro as e:
                self.erros.append(f"pools arrojadas: preço de {alvo['nome']}: {e}")
                continue
            if not pb or not pq:
                continue
            custo = custo_troca(v, alvo["taxa"], alvo["liquidez"])
            p = {"nome": alvo["nome"], "endereco": alvo["endereco"], "cot": alvo["cot"], "taxa": alvo["taxa"],
                 "liquidez": alvo["liquidez"], "desde": dia, "ultimo": dia, "dias": 0, "pb0": pb, "pq0": pq,
                 "v0": v - custo, "valor": v - custo, "segurar": v - custo, "taxas": 0.0, "custoEntrada": custo}
            c["caixa"] -= v
            c["pos"].append(p)
            curva = Curva.de_json(c["curva"]) or Curva(inicio=self.agora)
            curva.operou(taxa=custo)
            c["curva"] = curva.para_json()
            self.ev.add(self.agora, "entrou", f"Entrou em {alvo['nome']} com {moeda_br(v)} (taxas estimadas "
                        f"{num_br(alvo['apr'] * 100, 0)}% ao ano, liquidez {moeda_br(alvo['liquidez'], 0)}).", cfg["id"])

    # ---------------------------------------------------------------- saída
    def saida(self) -> tuple[dict, list]:
        esc = (self.est.get("escolhas") or [None])[0]
        pool = {"id": POOL_ID, "nome": "Arrojadas (Marinho)", "par": "varia", "dex": "vários", "protocolo": "vários",
                "endereco": None, "taxa": None, "medida": "usd", "padrao": "arrEscada",
                "versoes": [v["id"] for v in VERSOES], "observador": False, "variavel": True, "aproximado": True,
                "preco": None, "volume24h": None, "tvl": None, "giro": None,
                "escolhaDoDia": esc, "escolhas": [{k: e.get(k) for k in ("dia", "vistos", "preFiltro", "filtro")} | {
                    "nome": (e.get("escolhido") or {}).get("nome"), "controle": (e.get("controle") or {}).get("nome")}
                    for e in (self.est.get("escolhas") or [])[:14]],
                "regras": {"volumeMin": VOL_MIN, "volumeDiaMin": VOL_DIA_MIN, "diasConstante": DIAS_CONSTANTE,
                           "liquidezMin": LIQ_MIN, "idadeDias": IDADE_DIAS, "aprMin": APR_MIN, "top10Max": TOP10_MAX,
                           "seguraDias": SEGURA_DIAS, "partes": PARTES},
                "comoFunciona": COMO_FUNCIONA,
                "nota": ("Aproximado: posição de faixa inteira pelo volume diário do GeckoTerminal. Sem teste no passado "
                         "(o passado só mostraria os pools que sobreviveram).")}
        versoes = []
        for cfg in VERSOES:
            c = self.est.get("contas", {}).get(cfg["id"])
            curva = Curva.de_json((c or {}).get("curva"))
            versoes.append({"id": cfg["id"], "nome": cfg["nome"], "frase": cfg["frase"], "risco": cfg["risco"], "alav": 1,
                            "pool": POOL_ID, "grupo": GRUPO, "aproximado": True,
                            "aoVivo": curva.resumo(aproximado=True) if curva else None,
                            "historico": None,
                            "semHistorico": "Sem teste no passado: os pools que morreram somem das listas, e o passado "
                                            "sairia otimista."})
        return pool, versoes


def rodar(est: dict, gecko, agora: int, log, erros: list, ev, tempo) -> tuple[dict, list]:
    """Chamado pelo pools.py no fim da rodada. → (o item de `pools[]`, as versões)."""
    a = Arrojadas(est, gecko, agora, log, erros, ev, tempo)
    if hasattr(gecko, "gecko"):
        a.rodar()
    return a.saida()
