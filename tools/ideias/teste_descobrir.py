"""Teste dos canais parecidos (descobrir.py) com páginas de mentira: python3 tools/ideias/teste_descobrir.py"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import descobrir as D  # noqa: E402

AGORA = dt.datetime(2026, 11, 11, 12, tzinfo=dt.timezone.utc)


def pagina(dados):
    return "<html><script>var ytInitialData = " + json.dumps(dados) + ";</script></html>"


def canal_r(cid, nome, handle, insc="12,5 mil inscritos"):
    return {"channelRenderer": {"channelId": cid, "title": {"simpleText": nome},
                                "navigationEndpoint": {"browseEndpoint": {"canonicalBaseUrl": "/@" + handle}},
                                "subscriberCountText": {"simpleText": "@" + handle}, "videoCountText": {"simpleText": insc}}}


def feed_xml(nome, titulos, dias):
    es = "".join(f"<entry><title>{t}</title><published>{(AGORA - dt.timedelta(days=d)).isoformat()}</published></entry>"
                 for t, d in zip(titulos, dias))
    return f'<feed xmlns="http://www.w3.org/2005/Atom"><title>{nome}</title>{es}</feed>'


def escrever(pasta, url, texto):
    with open(os.path.join(pasta, D.RedeFalsa.nome(url)), "w", encoding="utf-8") as f:
        f.write(texto)


def montar(tmp):
    pags = os.path.join(tmp, "pags")
    dados = os.path.join(tmp, "dados")
    os.makedirs(pags)
    os.makedirs(os.path.join(dados, "videos"))
    cfg = {"canais": [
        {"chave": "marinho", "nome": "Canal do Marinho", "handle": "canaldomarinho", "channel_id": "UC" + "m" * 22,
         "foco": "pools de liquidez; renda passiva em cripto"},
        {"chave": "craftgold", "nome": "Craft Gold", "handle": "craftgold", "channel_id": "UC" + "c" * 22,
         "foco": "apps que pagam", "buscas": ["apps que pagam no pix"]},
    ], "dispensados": [{"channel_id": "UC" + "d" * 22, "nome": "Dispensado"}], "buscas": ["airdrop cripto"]}
    with open(os.path.join(tmp, "cfg.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    # o que a antena já guardou dos seguidos
    tm = ["pool de liquidez na uniswap rende quanto", "pools de liquidez concentrada na base", "renda passiva com pools de liquidez",
          "aerodrome pool de liquidez vale a pena"]
    tc = ["app que paga no pix de verdade", "aplicativo pagando dinheiro no pix", "apps que pagam para andar", "ganhar dinheiro com app no celular"]
    for i, t in enumerate(tm):
        json.dump({"id": f"m{i}", "canal": "marinho", "titulo": t, "descricao": "Segue também o @CanalDaPool e youtube.com/@CanalDaPool"},
                  open(os.path.join(dados, "videos", f"m{i}.json"), "w"))
    for i, t in enumerate(tc):
        json.dump({"id": f"c{i}", "canal": "craftgold", "titulo": t, "descricao": "contato: fulano@gmail.com"},
                  open(os.path.join(dados, "videos", f"c{i}.json"), "w"))
    # destaque do Marinho: o próprio Marinho (fora), um parecido e um dispensado
    escrever(pags, D.DESTAQUE.format("canaldomarinho"), pagina({"x": [
        {"gridChannelRenderer": {"channelId": "UC" + "m" * 22, "title": {"simpleText": "Canal do Marinho"}}},
        canal_r("UC" + "p" * 22, "Pool Lab", "poollab"),
        canal_r("UC" + "d" * 22, "Dispensado", "dispensado"),
        canal_r("UC" + "c" * 22, "Craft Gold", "craftgold"),
    ]}))
    # Craft Gold sem destaque (página fora do ar): vira erro e a rodada segue
    escrever(pags, D.BUSCA.format(urllib.parse.quote_plus("apps que pagam no pix")), pagina({"c": [
        canal_r("UC" + "a" * 22, "Apps Pagando", "appspagando", "230 mil inscritos"),
        canal_r("UC" + "e" * 22, "Cooking English", "cookingen"),
        canal_r("UC" + "v" * 22, "Canal Velho", "canalvelho"),
    ]}))
    # o @CanalDaPool citado: precisa achar o channel_id pela página
    escrever(pags, D.PAGINA.format("CanalDaPool"), '<meta itemprop="identifier"><script>{"externalId":"UC' + "q" * 22 + '"}</script>')
    feeds = {
        "p": ("Pool Lab", ["pools de liquidez concentrada explicadas", "uniswap pool de liquidez na base", "renda passiva com pool"], [1, 6, 12]),
        "a": ("Apps Pagando", ["app pagando no pix hoje", "aplicativo que paga dinheiro", "apps que pagam de verdade", "novo app pagando"], [0, 3, 5, 9]),
        "e": ("Cooking English", ["how to bake bread at home", "the best pasta recipe ever", "kitchen tips for beginners"], [2, 4, 8]),
        "v": ("Canal Velho", ["app que paga no pix", "aplicativo pagando"], [120, 200]),
        "q": ("Canal da Pool", ["pool de liquidez na aerodrome", "liquidez concentrada vale a pena", "pools para iniciantes"], [2, 9, 20]),
    }
    for k, (nome, ts, ds) in feeds.items():
        escrever(pags, D.FEED.format("UC" + k * 22), feed_xml(nome, ts, ds))
    return pags, dados, os.path.join(tmp, "cfg.json")


def teste_rodada():
    tmp = tempfile.mkdtemp()
    try:
        pags, dados, cfg = montar(tmp)
        log = D.Log(eco=False)
        rede = D.RedeFalsa(pags, log)
        rede.pausa = 0
        out = D.rodada(dados, cfg, rede, log, AGORA)
        ids = [c["channel_id"] for c in out["canais"]]
        assert "UC" + "p" * 22 in ids, out
        assert "UC" + "a" * 22 in ids, out
        assert "UC" + "q" * 22 in ids, "citado na descrição, achado pela página do @handle"
        assert "UC" + "d" * 22 not in ids, "dispensado não volta"
        assert "UC" + "m" * 22 not in ids and "UC" + "c" * 22 not in ids, "seguidos ficam de fora"
        assert "UC" + "e" * 22 not in ids, "em inglês fica de fora"
        assert "UC" + "v" * 22 not in ids, "sem postar há 60 dias fica de fora"
        pool = next(c for c in out["canais"] if c["channel_id"] == "UC" + "p" * 22)
        assert pool["parecidoComChave"] == "marinho", pool
        assert "destaque" in pool["origens"] and pool["novo"]
        apps = next(c for c in out["canais"] if c["channel_id"] == "UC" + "a" * 22)
        assert apps["parecidoComChave"] == "craftgold" and apps["inscritos"] == 230000, apps
        assert all(0 <= c["nota"] <= 100 for c in out["canais"])
        assert out["erros"], "a página fora do ar vira erro"
        assert not any("gmail" in json.dumps(c) for c in out["canais"]), "e-mail na descrição não vira canal"
        assert os.path.exists(os.path.join(dados, "sugestoes.json"))
        # a próxima rodada: os já sugeridos não são mais "novos"; com --cada 7 não roda antes de uma semana
        out2 = D.rodada(dados, cfg, rede, log, AGORA + dt.timedelta(days=7))
        assert not any(c["novo"] for c in out2["canais"] if c["channel_id"] in ids)
        assert not D.precisa(dados, 7, AGORA + dt.timedelta(days=8))
        assert D.precisa(dados, 7, AGORA + dt.timedelta(days=14, hours=1))
    finally:
        shutil.rmtree(tmp)


def teste_pecas():
    assert D.inscritos_num("1,2 mi de inscritos") == 1200000
    assert D.inscritos_num("12,5 mil inscritos") == 12500
    assert D.inscritos_num("987 inscritos") == 987
    assert D.parece_portugues(["como ganhar dinheiro com app"]) > 0.2
    assert D.parece_portugues(["how to bake bread"]) < 0.06
    assert D.chave_de("Canal.Da-Pool") == "canaldapool"
    assert D.dados_iniciais("nada aqui") is None


if __name__ == "__main__":
    teste_pecas()
    teste_rodada()
    print("descobrir: ok")
