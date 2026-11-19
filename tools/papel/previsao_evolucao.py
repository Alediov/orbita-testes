"""Evolução dos Mercados de previsão, NO PAPEL (pedido do Alediov, 15/11/2026; item 4 do plano de melhorias, "Previsões
e Opções por último"; feito em 19/11/2026, junto do resto das Finanças e dos Testes antes do APK).

A espécie é a **colheita** (comprar um lado perto do fim e esperar a resolução, como "Favorito ≥ 90%", que é o
controle): toda versão começa com US$ 1.000 fictícios. Os genes (o que evolui):

- `lado`: o favorito (o lado caro, que quase sempre ganha) ou o azarão (o barato, que quase sempre perde);
- `piso` e `teto` (só no favorito): compra o lado entre esses preços (de 80% a 97%, até 97/98/99%);
- `faixa` (só no azarão): o preço do lado (2–10%, 5–15% ou 10–25%);
- `dias`: entra faltando até N dias para o fim (1, 3, 7, 14 ou 30);
- `cat`: só uma categoria (Esportes, Política, Cripto, Economia, Cultura, Ciência e tecnologia, Outros) ou todas;
- `vol`: o volume mínimo do mercado (US$ 5 mil, 20 mil ou 100 mil);
- `aposta`: quanto por posição (US$ 10, 20 ou 40) e `max`, quantas abertas ao mesmo tempo (10, 25 ou 50).

Não precisa de rede a mais: as contas saem do **observatório de calibração** que a forma já guarda (`est["cal"]`): de
cada mercado encerrado (até 180 dias, volume ≥ US$ 5 mil), o preço do "Sim" em cada um dos 30 dias antes do fim, o
resultado, a categoria e o volume. Um mercado por evento (`um_por_evento`, as linhas do mesmo jogo andam juntas). A
entrada é o preço do dia + 1 centavo de deslize (como o teste no passado da forma), sem taxa; a saída é a resolução.

Limitação (nos avisos): o banco só tem os mercados que JÁ acabaram. Uma posição só entra na conta quando o mercado
dela acaba; o dinheiro das posições ainda abertas aparece como parado até lá. Vale para todas as versões e para o
controle, que é o "Favorito ≥ 90%" REFEITO aqui (não bate centavo a centavo com a conta fav90 ao vivo, que compra pelo
livro com o deslize medido e marca pela oferta de compra).

O laboratório e a liga são os do motor comum (`evolucao_series.py`). Estado em `est["evolucao"]` (o da forma);
saída em `previsao.json` → `evolucao` (FORMATO.md, "Evolução"). Teste: `teste_previsao_evolucao.py`.
"""
from __future__ import annotations

import datetime as dt

import evolucao_series as ES
from conta import CAPITAL, DIA, cdi_ano_da_serie, dia_de, metricas
from genetica import reparar

VERSAO = 1
CDI_PADRAO = 0.149
DESLIZE = 0.01           # 1 centavo, o mesmo do teste no passado da forma
PRECO_MAX = 0.999
MIN_MERCADOS = 30        # menos que isso no observatório: sem a espécie ainda
CATS = ["Esportes", "Política", "Cripto", "Economia", "Cultura", "Ciência e tecnologia", "Outros"]
FAIXAS = {"2-10": (0.02, 0.10), "5-15": (0.05, 0.15), "10-25": (0.10, 0.25)}

FRASE = ("Versões da colheita que evoluem: toda semana as piores regras saem, as melhores se cruzam e, às vezes, um "
         "gene muda. Só observação: o Brasil bloqueou as casas de previsão.")
AVISOS = ["Só observação, com saldo fictício: nenhuma conta, nenhuma ordem (a Polymarket e a Kalshi estão bloqueadas "
          "no Brasil desde abril de 2026).",
          "As contas saem dos mercados que o observatório já viu acabar: uma posição só aparece quando o mercado dela "
          "acaba; até lá o dinheiro dela fica como parado.",
          "Entrada pelo preço do dia + 1 centavo, sem taxa; o controle é o Favorito ≥ 90% refeito por este simulador.",
          "Um mercado por evento: as linhas do mesmo jogo não contam como apostas diferentes."]

ESP = {
    "id": "colheita", "nome": "Colheita", "icone": "🌽", "prefixo": "p", "controle": "fav90",
    "frase": "Compra um lado perto do fim e espera a resolução: o lado (favorito ou azarão), a faixa de preço, quanto "
             "falta para o fim, a categoria, o volume e o tamanho das apostas evoluem.",
    "genes": [
        {"k": "lado", "nome": "Lado", "tipo": "op", "opcoes": ["fav", "az"], "rotulos": {"fav": "Favorito", "az": "Azarão"},
         "neutro": "fav"},
        {"k": "piso", "nome": "Compra a partir de", "tipo": "op", "opcoes": [0.8, 0.85, 0.9, 0.93, 0.95, 0.97], "un": "%",
         "neutro": 0.9, "so": {"lado": "fav"}},
        {"k": "teto", "nome": "Até", "tipo": "op", "opcoes": [0.97, 0.98, 0.99], "un": "%", "neutro": 0.99,
         "so": {"lado": "fav"}},
        {"k": "faixa", "nome": "Faixa do azarão", "tipo": "op", "opcoes": list(FAIXAS),
         "rotulos": {"2-10": "2% a 10%", "5-15": "5% a 15%", "10-25": "10% a 25%"}, "neutro": "2-10", "so": {"lado": "az"}},
        {"k": "dias", "nome": "Faltando até", "tipo": "op", "opcoes": [1, 3, 7, 14, 30], "un": "d", "neutro": 7},
        {"k": "cat", "nome": "Categoria", "tipo": "op", "opcoes": ["todas"] + CATS, "rotulos": {"todas": "Todas"},
         "neutro": "todas"},
        {"k": "vol", "nome": "Volume mínimo", "tipo": "op", "opcoes": [5000, 20000, 100000], "un": "US$", "neutro": 5000},
        {"k": "aposta", "nome": "Por aposta", "tipo": "op", "opcoes": [10, 20, 40], "un": "US$", "neutro": 20},
        {"k": "max", "nome": "Abertas no máximo", "tipo": "op", "opcoes": [10, 25, 50], "neutro": 50},
    ],
}


class Definicao:
    """A espécie como o motor comum espera."""
    versao, nome_controle, da_liga, rotulo, esp = VERSAO, "Favorito ≥ 90%", "da colheita", "previsão", ESP

    def genes_controle(self):
        """"Favorito ≥ 90%": o lado a 90% ou mais (até 99%) faltando até 7 dias, US$ 20 por posição."""
        return reparar(ESP, {g["k"]: g["neutro"] for g in ESP["genes"]})

    def sementes(self):
        """As outras versões que a forma já roda (Favorito ≥ 95% e o Azarão ≤ 10%) e duas vizinhas."""
        b = self.genes_controle()
        return [(de, reparar(ESP, {**b, **m})) for de, m in (
            ("fav95", {"piso": 0.95}), ("azarao", {"lado": "az", "faixa": "2-10", "dias": 30}),
            ("fav90_3d", {"dias": 3}), ("fav85", {"piso": 0.85}))]

    def descrever(self, genes):
        pc = lambda x: f"{round(x * 100)}%"  # noqa: E731
        if genes["lado"] == "fav":
            out = [f"Favorito de {pc(genes['piso'])} a {pc(genes['teto'])}"]
        else:
            a, b = FAIXAS[genes["faixa"]]
            out = [f"Azarão de {pc(a)} a {pc(b)}"]
        out.append("faltando 1 dia" if genes["dias"] == 1 else f"faltando até {genes['dias']} dias")
        if genes["cat"] != "todas":
            out.append(genes["cat"])
        out.append(f"US$ {genes['aposta']} cada")
        return " · ".join(out)


# ====================================================================== os dados
def _fim_do_dia(dia):
    """O último instante (ms UTC) de um dia de Brasília (UTC−3)."""
    d = dt.datetime.fromisoformat(dia) + dt.timedelta(days=1, hours=3)
    return int(d.replace(tzinfo=dt.timezone.utc).timestamp() * 1000) - 1


def _ord(dia):
    return dt.date.fromisoformat(dia).toordinal()


class Dados:
    """O observatório de calibração para o simulador (um mercado por evento)."""

    def __init__(self, est, P=None):
        try:
            import previsao as PR
            merc = PR.um_por_evento((est.get("cal") or {}).get("mercados") or {})
        except Exception:  # noqa: BLE001 (sem o módulo da forma, nada)
            merc = {}
        self.merc = [dict(m, id=k) for k, m in merc.items() if m.get("o") in (0, 1) and m.get("pts") and m.get("fim")]
        self.merc.sort(key=lambda m: m["fim"])
        self.primeiro = dia_de(self.merc[0]["fim"] - 30 * DIA) if self.merc else None

    @property
    def tem_dados(self):
        return len(self.merc) >= MIN_MERCADOS

    def simular(self, genes, inicio, hoje):
        return simular(self, genes, inicio, hoje)

    @staticmethod
    def extras(c):
        return {"membros": c["membros"], "custos": c["custos"], "largadas": 0, "acertos": c["acertos"],
                "resolvidas": c["resolvidas"]}


def entrada(m, genes, t0, t1):
    """O 1º dia (ms, preço do lado, lado) em que a regra compra o mercado `m` entre `t0` e `t1`, ou None."""
    if m.get("vol", 0) < genes["vol"] or (genes["cat"] != "todas" and (m.get("cat") or "Outros") != genes["cat"]):
        return None
    pts = m["pts"]
    if genes["lado"] == "fav":
        lo, hi = genes["piso"], genes["teto"]
    else:
        lo, hi = FAIXAS[genes["faixa"]]
    for k in range(min(genes["dias"], len(pts) - 1), 0, -1):
        t = m["fim"] - k * DIA
        if t < t0 or t > t1 or pts[k] is None or pts[k] < 0:
            continue
        p = pts[k] / 1000
        for lado, pl in ((0, p), (1, 1 - p)):
            if lo <= pl <= hi:
                return t, min(PRECO_MAX, pl + DESLIZE), lado
    return None


def simular(D, genes, inicio, hoje):
    """A conta de uma versão de `inicio` a `hoje` (dias de Brasília), um ponto por dia: { serie: [[dia, US$]], retorno,
    piorQueda, ops (compras), custos (o deslize), membros (as abertas no fim), montou, acertos, resolvidas }."""
    t0, t1 = _fim_do_dia(inicio) - DIA + 1, _fim_do_dia(hoje)
    ent = []
    for m in D.merc:
        if m["fim"] < t0 or m["fim"] - 31 * DIA > t1:
            continue
        e = entrada(m, genes, t0, t1)
        if e:
            ent.append((e[0], m, e[1], e[2]))
    ent.sort(key=lambda x: (x[0], x[1]["id"]))
    caixa, abertas, serie = float(CAPITAL), [], []
    ops, custos, acertos, resolvidas, i = 0, 0.0, 0, 0, 0
    pico, queda = float(CAPITAL), 0.0
    for o in range(_ord(inicio), _ord(hoje) + 1):
        dia = dt.date.fromordinal(o).isoformat()
        fim = _fim_do_dia(dia)
        # resolve o que acabou até o fim do dia
        fica = []
        for p in abertas:
            if p["m"]["fim"] <= fim:
                ganhou = (p["m"]["o"] == 1) == (p["lado"] == 0)
                caixa += p["cotas"] if ganhou else 0.0
                acertos += int(ganhou)
                resolvidas += 1
            else:
                fica.append(p)
        abertas = fica
        # compra o que a regra pede hoje
        while i < len(ent) and ent[i][0] <= fim:
            t, m, preco, lado = ent[i]
            i += 1
            if len(abertas) >= genes["max"] or caixa < genes["aposta"] or m["fim"] <= t:
                continue
            caixa -= genes["aposta"]
            abertas.append({"m": m, "lado": lado, "cotas": genes["aposta"] / preco})
            custos += genes["aposta"] / preco * DESLIZE
            ops += 1
        # marca pelo preço do dia (o do lado comprado)
        v = caixa
        for p in abertas:
            k = int(round((p["m"]["fim"] - fim) / DIA))
            pts = p["m"]["pts"]
            pr = pts[k] / 1000 if 0 <= k < len(pts) and pts[k] is not None and pts[k] >= 0 else None
            if pr is None:
                pr = p.get("ult", genes["aposta"] / p["cotas"])
            else:
                pr = pr if p["lado"] == 0 else 1 - pr
            p["ult"] = pr
            v += p["cotas"] * pr
        serie.append([dia, round(v, 2)])
        pico = max(pico, v)
        queda = max(queda, 1 - v / pico if pico > 0 else 0.0)
    fim_v = serie[-1][1] if serie else CAPITAL
    membros = [f"{len(abertas)} {'aberta' if len(abertas) == 1 else 'abertas'}"] if abertas else []
    return {"serie": serie, "retorno": round(fim_v / CAPITAL - 1, 5), "piorQueda": round(queda, 4), "ops": ops,
            "custos": round(custos, 2), "montou": ops > 0, "membros": membros, "acertos": acertos,
            "resolvidas": resolvidas}


# ====================================================================== a rodada
def _met(ctx):
    cdi = (getattr(ctx, "ref", None) or {}).get("cdi") or {}

    def f(c):
        return metricas(c, cdi, cdi_ano_da_serie(cdi, CDI_PADRAO))
    return f


def avancar(ctx, est, agora):
    """O laboratório e a liga da colheita pelo observatório desta rodada. Devolve o bloco `evolucao` do previsao.json
    (None enquanto o observatório não tem MIN_MERCADOS mercados)."""
    D = Dados(est)
    if not D.tem_dados:
        return None
    ev = ES.rodar(est, Definicao(), D, agora, ES.parametros(bool(getattr(ctx, "exemplo", False))), ctx.log)
    return ES.resumo(ev, D, agora, "previsao", "Previsão", FRASE, AVISOS, _met(ctx), VERSAO,
                     mercados=len(D.merc))


__all__ = ["avancar", "simular", "entrada", "Dados", "Definicao", "ESP"]
