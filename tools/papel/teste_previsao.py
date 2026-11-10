"""Testes dos mercados de previsão (previsao.py) no mercado de mentira (falso_previsao.py), sem rede.
Uso: python3 tools/papel/teste_previsao.py"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)

import previsao as P  # noqa: E402


def teste_livro_e_taxa():
    asks = [{"price": "0.93", "size": "500"}, {"price": "0.91", "size": "10"}, {"price": "0.92", "size": "5"}]
    cotas, preco, melhor = P.comprar_no_livro(asks, 20)
    assert melhor == 0.91 and 0.91 < preco < 0.93, (preco, melhor)
    assert abs(cotas * preco - 20) < 1e-9
    assert P.comprar_no_livro([{"price": "0.5", "size": "10"}], 20) is None  # livro curto: não entra
    assert P.taxa(0.9, 100, 0) == 0
    assert abs(P.taxa(0.9, 100, 100) - 0.01 * 0.1 * 100) < 1e-12  # base × min(p, 1 − p) × cotas


def teste_wilson_e_categoria():
    lo, hi = P.wilson(8, 10)
    assert 0.44 < lo < 0.5 and 0.94 < hi < 0.98
    assert P.wilson(0, 0) is None
    assert P.categoria({"question": "Will Flamengo beat Vasco in the match?"}) == "Esportes"
    assert P.categoria({"question": "Will Bitcoin reach $150k by December?"}) == "Cripto"
    assert P.categoria({"question": "Will the Fed cut interest rates in December?"}) == "Economia"
    assert P.categoria({"question": "Who will win the presidential election?"}) == "Política"
    assert P.categoria({"question": "Algo qualquer", "events": [{"tags": [{"label": "Sports"}]}]}) == "Esportes"
    assert P.categoria({"question": "Will it snow in Lisbon?"}) in P.CATEGORIAS


def teste_casar():
    d = P.DIA
    assert P.casar("Will Bitcoin reach $100k by December?", 10 * d, "Bitcoin reach $100k by December?", 11 * d) > 0.9
    assert P.casar("Will Bitcoin reach $100k by December?", 10 * d, "Will Bitcoin reach $120k by December?", 10 * d) == 0
    assert P.casar("Will Bitcoin reach $100k by December?", 10 * d, "Will Bitcoin not reach $100k by December?", 10 * d) == 0
    assert P.casar("Will Bitcoin reach $100k by December?", 10 * d, "Bitcoin reach $100k by December?", 20 * d) == 0
    assert P.casar("Will the Fed cut rates in December?", None, "Will Brazil win the World Cup?", None) == 0
    # nome com número grudado não vira número solto
    assert P.casar("Will TESTCOIN12 hit $5k?", None, "Will TESTCOIN13 hit $5k?", None) == 0


def teste_mercado_de():
    m = {"id": "1", "question": "Q?", "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]',
         "clobTokenIds": '["11", "12"]', "closed": True, "endDate": "2026-11-01T00:00:00Z",
         "closedTime": "2026-10-30 12:00:00+00", "umaResolutionStatus": "resolved"}
    mk = P.mercado_de(m)
    assert mk["resultado"] == 1.0 and mk["fim"] == P.ms_de("2026-10-30T12:00:00Z")
    assert P.marca(mk, 0) == 1.0 and P.marca(mk, 1) == 0.0
    assert P.mercado_de({**m, "outcomes": '["A", "B", "C"]'}) is None
    assert P.ms_de(1793000000) == 1793000000000 and P.ms_de("2026-11-01") == P.ms_de("2026-11-01T00:00:00Z")


def teste_tabela():
    merc = {}
    for i in range(100):
        o = 1 if i < 80 else 0
        merc[str(i)] = {"fim": 0, "o": o, "cat": "Política" if i % 2 else "Cripto", "pts": [850] * 31}
    t = P.tabela_calibracao(merc)
    f = t[0]["faixas"][8]
    assert f["n"] == 100 and f["sim"] == 80 and abs(f["real"] - 0.8) < 1e-9 and f["ic"][0] < 0.8 < f["ic"][1]
    assert abs(t[0]["brier"] - (0.8 * 0.15 ** 2 + 0.2 * 0.85 ** 2)) < 1e-4
    assert {c["cat"] for c in t[0]["porCategoria"]} == {"Política", "Cripto"}


def rodadas(n, falhar=()):
    import falso
    import papel
    pasta = tempfile.mkdtemp(prefix="prev-")
    cli = falso.ClientePapelFalso()
    cli.falhar = set(falhar)
    t0 = cli.agora
    for k in range(n):
        cli.agora = t0 + k * 6 * falso.HORA
        ind = papel.rodada(cli, pasta, cli.agora, formas=["previsao"], exemplo=True, buscar_cdi=False,
                           log=papel.Log(quieto=True))
    with open(os.path.join(pasta, "previsao.json")) as f:
        d = json.load(f)
    with open(os.path.join(pasta, "log.txt")) as f:
        log = f.read()
    shutil.rmtree(pasta, ignore_errors=True)
    return ind, d, log


def teste_rodadas():
    ind, d, log = rodadas(24)
    assert ind["formas"]["previsao"]["ok"], ind
    por = {v["id"]: v for v in d["versoes"]}
    assert set(por) == set(P.IDS) and d["padrao"] == "fav90"
    for vid in ("fav90", "fav95", "azarao", "seguir", "difK"):
        assert por[vid]["aoVivo"]["extra"]["posicoes"] > 0, vid
    # o favorito só comprou entre 90% e 99%; o azarão entre 2% e 10%
    for it in d["itens"]:
        if it["versao"] == "fav90":
            assert 0.90 <= it["preco"] <= 0.99, it
        if it["versao"] == "azarao":
            assert 0.02 <= it["preco"] <= 0.10, it
    assert any(it.get("carteira", "").startswith("0x") and "…" in it["carteira"] for it in d["itens"])
    # o teste no passado (aproximado) só no favorito e no azarão
    for vid in ("fav90", "fav95", "azarao"):
        h = por[vid]["historico"]
        assert h and h["aproximado"] and h["de"] < h["ate"] and "janelas" in h, vid
    assert all(por[v]["historico"] is None for v in ("difK", "difM", "seguir", "cdi", "usdc"))
    assert por["seguir"]["aoVivo"]["aproximado"] and por["seguir"]["soAoVivo"]
    pd = por["fav90"]["aoVivo"]["extra"]["porDentro"]
    assert {"ganhos", "perdas", "taxas", "deslize", "emAberto", "resultado"} <= set(pd)
    assert por["azarao"]["aoVivo"]["extra"]["porDentro"]["deslize"] > 0  # andou pelo livro
    # a régua do CDI anda; a do dólar parado não
    assert por["cdi"]["aoVivo"]["retorno"] > 0 and por["usdc"]["aoVivo"]["retorno"] == 0
    # calibração com as 3 janelas e as 10 faixas
    c = d["calibracao"]
    assert c["mercados"] > 100 and [h["id"] for h in c["horizontes"]] == ["24h", "7d", "30d"]
    assert all(len(h["faixas"]) == 10 and h["brier"] is not None for h in c["horizontes"])
    # diferença entre casas: casou e nenhum par casou o "parecido" com outro número
    assert any(p["outra"] == "Manifold" for p in d["casas"]["pares"]), "a Manifold achou par"
    assert d["casas"]["pares"] and all(p["nota"] >= P.DIF_JACCARD for p in d["casas"]["pares"])
    assert not any("5k" in p["outraPergunta"] and "0k" in p["pergunta"] for p in d["casas"]["pares"])
    # seguir: só endereço encurtado e contagens, nunca o apelido
    s = json.dumps(d, ensure_ascii=False)
    assert "Apelido" not in s and len(d["seguir"]["carteiras"]) == P.SEG_N
    assert all(len(x["carteira"]) < 15 for x in d["seguir"]["carteiras"])
    # a estrutura de cada fonte ficou no log da 1ª rodada; nada de vírgula decimal em ponto nos eventos
    for r in ("gamma /markets (abertos)", "clob /book", "clob /prices-history", "kalshi /markets", "pmdata /trades",
              "manifold /search-markets"):
        assert f"estrutura de {r}" in log, r
    assert not any(" centavos" in e["texto"] and "." in e["texto"].split(" centavos")[0][-5:] for e in d["eventos"])
    assert d["semDados"] == []


def teste_historico_reserva():
    """O 1º jeito do prices-history dando 400 (como na 1ª rodada real): a reserva por `interval` responde e fica guardada."""
    import falso
    import papel
    pasta = tempfile.mkdtemp(prefix="prev-")
    try:
        cli = falso.ClientePapelFalso()
        cli.pv_so_intervalo = True
        for k in range(3):
            cli.agora += 6 * falso.HORA
            papel.rodada(cli, pasta, cli.agora, formas=["previsao"], exemplo=True, buscar_cdi=False, log=papel.Log(quieto=True))
        with open(os.path.join(pasta, "previsao.json")) as f:
            d = json.load(f)
        with open(os.path.join(pasta, "estado.json")) as f:
            est = json.load(f)
        assert d["calibracao"]["mercados"] > 50, d["calibracao"]["andamento"]
        assert est["formas"]["previsao"]["histJeito"] >= 2
        assert not any(x["fonte"] == "clob" for x in d["semDados"])
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def teste_ranking_pelas_negociacoes():
    """O ranking sai das negociações públicas dos mercados resolvidos na semana anterior (o leaderboard morreu)."""
    _, d, log = rodadas(2)
    assert d["seguir"]["mercadosLidos"] and len(d["seguir"]["carteiras"]) == P.SEG_N, d["seguir"]
    assert "leaderboard" not in log and "estrutura de pmdata /trades (mercado)" in log


def teste_fonte_falhando():
    ind, d, _ = rodadas(3, falhar={"kalshi", "pmdata"})
    assert ind["formas"]["previsao"]["ok"]
    fontes = {x["fonte"] for x in d["semDados"]}
    assert {"kalshi", "pmdata"} <= fontes or "ranking" in fontes, d["semDados"]
    assert d["casas"]["fontes"]["Kalshi"]["ok"] is False
    por = {v["id"]: v for v in d["versoes"]}
    assert por["fav90"]["aoVivo"]["extra"]["posicoes"] > 0  # o resto continua
    ind, d, _ = rodadas(2, falhar={"gamma"})
    assert ind["formas"]["previsao"]["ok"] and any(x["fonte"] == "gamma" for x in d["semDados"])


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("teste_") and callable(f):
            f()
            print(f"{nome}: ok")
