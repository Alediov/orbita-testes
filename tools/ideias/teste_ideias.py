"""Testes da antena de ideias (sem rede: feed, página do canal, yt-dlp e youtube-transcript-api de mentira).
Uso: python3 tools/ideias/teste_ideias.py"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import ideias as I  # noqa: E402

CONFIG = {"canais": [
    {"chave": "a", "nome": "Canal A", "handle": "canala", "channel_id": "UC" + "a" * 22},
    {"chave": "b", "nome": "Canal B", "handle": "canalb", "channel_id": "UC" + "x" * 22},  # id velho: feed 404
]}
ID_B = "UC" + "b" * 22


def feed(ids, base="2026-11-0"):
    entradas = "".join(f"""
 <entry><id>yt:video:{v}</id><yt:videoId>{v}</yt:videoId><title>Vídeo {v} &amp; mais</title>
  <published>{base}{i + 1}T12:00:00+00:00</published>
  <media:group><media:title>Vídeo {v}</media:title><media:description>Link: https://exemplo.test/{v}</media:description></media:group>
 </entry>""" for i, v in enumerate(ids))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/"
 xmlns="http://www.w3.org/2005/Atom"><title>Canal</title>{entradas}</feed>"""


VTT = """WEBVTT
Kind: captions
Language: pt

00:00:00.000 --> 00:00:02.000 align:start position:0%

olá<00:00:00.500><c> pessoal</c><00:00:01.000><c> hoje</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
olá pessoal hoje


00:00:02.010 --> 00:00:04.000 align:start position:0%
olá pessoal hoje
vamos<00:00:02.500><c> ver</c><00:00:03.000><c> a</c><00:00:03.500><c> faucet</c>

00:00:04.000 --> 00:00:06.000
[Música]
"""


class Rede:
    def __init__(self, feeds):
        self.feeds, self.pedidos = feeds, []

    def __call__(self, url, prazo=30):
        self.pedidos.append(url)
        if "feeds/videos.xml" in url:
            cid = url.split("channel_id=")[1]
            if cid not in self.feeds:
                raise RuntimeError("HTTP Error 404: Not Found")
            return self.feeds[cid]
        if url.endswith("/@canalb"):
            return '<html>..."externalId":"' + ID_B + '"...</html>'
        raise RuntimeError("URL inesperada " + url)


class YtFalso(I.YtDlp):
    """Responde como o yt-dlp: a lista dos envios e, na transcrição, grava .vtt e .info.json na pasta do -o."""

    def __init__(self, envios, sem_legenda=(), bloqueado=()):
        super().__init__(exe="yt-dlp", rodar=self.rodar_falso)
        self.envios, self.sem, self.bloq, self.chamadas = envios, set(sem_legenda), set(bloqueado), []

    def rodar_falso(self, args, prazo=180):
        self.chamadas.append(args)
        url = args[-1]
        if "--flat-playlist" in args:
            cid = "UC" + url.split("list=UU")[1]
            return 0, json.dumps({"entries": [{"id": v, "title": f"Antigo {v}", "duration": 61}
                                              for v in self.envios.get(cid, [])]}), ""
        vid = url.split("v=")[1]
        if vid in self.bloq:
            return 1, "", "ERROR: [youtube] " + vid + ": Sign in to confirm you're not a bot."
        pasta = os.path.dirname(args[args.index("-o") + 1])
        with open(os.path.join(pasta, f"{vid}.info.json"), "w") as fh:
            json.dump({"id": vid, "duration": 754, "upload_date": "20261020", "title": f"Título {vid}",
                       "description": "desc " + vid}, fh)
        if vid in self.sem:
            return 0, "", ""
        with open(os.path.join(pasta, f"{vid}.pt.vtt"), "w") as fh:
            fh.write(VTT)
        return 0, "", ""


def api_falsa(ok):
    def buscar(vid, idiomas):
        if vid in ok:
            return [{"text": "texto"}, {"text": "pela &amp; API"}], "pt"
        raise RuntimeError("NoTranscriptFound: no transcript")
    return buscar


def teste_vtt():
    t = I.vtt_para_texto(VTT)
    assert t == "olá pessoal hoje vamos ver a faucet", t
    srt = "1\n00:00:01,000 --> 00:00:02,000\nUm <i>dois</i>\n\n2\n00:00:02,000 --> 00:00:03,000\ntrês\n"
    assert I.vtt_para_texto(srt) == "Um dois três"


def teste_erros():
    assert I.classificar_erro("Sign in to confirm you're not a bot") == "bloqueio do YouTube a este IP"
    assert I.classificar_erro("HTTP Error 429: Too Many Requests") == "bloqueio do YouTube a este IP"
    assert I.classificar_erro("NoTranscriptFound") == "sem legendas"
    assert I.classificar_erro("This live event will begin in 3 hours") == "estreia ou ao vivo ainda não aconteceu"
    assert I.classificar_erro("Private video").startswith("vídeo indisponível")


def teste_channel_id():
    assert I.channel_id_da_pagina('x "externalId":"' + ID_B + '" y') == ID_B
    assert I.channel_id_da_pagina('<link href="https://www.youtube.com/channel/' + ID_B + '">') == ID_B
    assert I.channel_id_da_pagina("nada") is None


def teste_rodada():
    d = tempfile.mkdtemp()
    try:
        ida = CONFIG["canais"][0]["channel_id"]
        rede = Rede({ida: feed(["a1", "a2"]), ID_B: feed(["b1"])})
        yt = YtFalso({ida: ["a1", "a2", "a3", "a4"], ID_B: ["b1", "b2"]}, sem_legenda={"a3"}, bloqueado={"b2"})
        api = I.TranscriptApi(buscar=api_falsa({"b2"}))
        log = I.Log(eco=False)
        idx = I.rodada(d, CONFIG, baixar_fn=rede, ytdlp=yt, api=api, inicio=30, pausa=0, log=log,
                       agora="2026-11-09T10:00:00Z")
        assert idx["canais"]["b"]["channel_id"] == ID_B, idx["canais"]["b"]  # achou o id novo pelo handle
        assert idx["canais"]["b"]["feed"] is True
        ids = {v["id"] for v in idx["videos"]}
        assert ids == {"a1", "a2", "a3", "a4", "b1", "b2"}, ids
        v = json.load(open(os.path.join(d, "videos", "a1.json")))
        assert v["transcricao"] == "olá pessoal hoje vamos ver a faucet" and v["fonte"] == "yt-dlp", v
        assert v["titulo"] == "Vídeo a1 & mais" and v["descricao"] == "Link: https://exemplo.test/a1"
        assert v["publicado"].startswith("2026-11-01") and v["duracao"] == 754 and v["url"].endswith("v=a1")
        a3 = json.load(open(os.path.join(d, "videos", "a3.json")))
        assert a3["transcricao"] is None and "sem legendas" in a3["motivoSemTranscricao"], a3
        assert a3["publicado"].startswith("2026-10-20") and a3["tentativas"] == 1  # data pelo info.json
        b2 = json.load(open(os.path.join(d, "videos", "b2.json")))
        assert b2["fonte"] == "youtube-transcript-api" and b2["transcricao"] == "texto pela & API", b2
        assert idx["comTranscricao"] == 5 and idx["total"] == 6
        assert idx["rodadas"][-1]["metodos"]["yt-dlp"]["falhas"] == 2
        assert os.path.exists(os.path.join(d, "indice.json"))
        # índice sem o texto, mais novo primeiro (os sem data no fim)
        assert "transcricao" in idx["videos"][0] and idx["videos"][0]["transcricao"] is True
        assert idx["videos"][0]["id"] == "a2"

        # 2ª rodada: sem a 1ª lista (o canal já tem vídeos), só o feed novo; a3 é tentado de novo
        rede.feeds[ida] = feed(["a5", "a1", "a2"])
        yt.chamadas.clear()
        yt.sem.discard("a3")
        idx = I.rodada(d, CONFIG, baixar_fn=rede, ytdlp=yt, api=api, pausa=0, log=log, agora="2026-11-09T22:00:00Z")
        assert not any("--flat-playlist" in c for c in yt.chamadas)
        vistos = [c[-1].split("v=")[1] for c in yt.chamadas]
        assert vistos == ["a5", "a3"], vistos  # nunca tentado antes; só os sem transcrição
        assert idx["comTranscricao"] == 7 and idx["total"] == 7
        a5 = json.load(open(os.path.join(d, "videos", "a5.json")))
        assert a5["visto"] == "2026-11-09T22:00:00Z"
        a1 = json.load(open(os.path.join(d, "videos", "a1.json")))
        assert a1["visto"] == "2026-11-09T10:00:00Z"  # não muda
        assert len(idx["rodadas"]) == 2
    finally:
        shutil.rmtree(d)


def teste_limites():
    d = tempfile.mkdtemp()
    try:
        ida = CONFIG["canais"][0]["channel_id"]
        cfg = {"canais": [CONFIG["canais"][0]]}
        rede = Rede({ida: feed(["v1", "v2", "v3", "v4", "v5", "v6", "v7"])})
        yt = YtFalso({}, bloqueado={f"v{i}" for i in range(1, 8)})
        log = I.Log(eco=False)
        idx = I.rodada(d, cfg, baixar_fn=rede, ytdlp=yt, api=I.TranscriptApi(buscar=api_falsa(set())), pausa=0,
                       log=log, inicio=0)
        assert len([c for c in yt.chamadas if "--flat-playlist" not in c]) == 5  # para depois de 5 bloqueios
        assert idx["total"] == 7 and idx["comTranscricao"] == 0
        v = json.load(open(os.path.join(d, "videos", "v7.json")))  # metadados guardados mesmo sem transcrição
        assert v["titulo"] and v["transcricao"] is None
        assert any("bloqueio" in l for l in log.linhas)
        # depois de MAX_TENTATIVAS, desiste
        for x in idx["videos"]:
            p = os.path.join(d, "videos", x["id"] + ".json")
            j = json.load(open(p))
            j["tentativas"] = I.MAX_TENTATIVAS
            json.dump(j, open(p, "w"))
        yt.chamadas.clear()
        I.rodada(d, cfg, baixar_fn=rede, ytdlp=yt, api=I.TranscriptApi(buscar=api_falsa(set())), pausa=0, log=log)
        assert not yt.chamadas
        # vídeo velho sai
        p = os.path.join(d, "videos", "v1.json")
        j = json.load(open(p))
        j["publicado"] = "2020-01-01T00:00:00Z"
        json.dump(j, open(p, "w"))
        rede.feeds[ida] = feed(["v2"])
        idx = I.rodada(d, cfg, baixar_fn=rede, ytdlp=yt, api=I.TranscriptApi(buscar=api_falsa(set())), pausa=0,
                       log=log)
        assert not os.path.exists(p) and idx["total"] == 6
    finally:
        shutil.rmtree(d)


def teste_sem_ferramentas():
    d = tempfile.mkdtemp()
    try:
        ida = CONFIG["canais"][0]["channel_id"]
        yt = I.YtDlp(exe=None)
        yt.exe = None
        api = I.TranscriptApi(buscar=None)
        api._yta = None
        idx = I.rodada(d, {"canais": [CONFIG["canais"][0]]}, baixar_fn=Rede({ida: feed(["z1"])}), ytdlp=yt, api=api,
                       pausa=0, log=I.Log(eco=False))
        v = json.load(open(os.path.join(d, "videos", "z1.json")))
        assert v["motivoSemTranscricao"] == "nenhum método disponível" and idx["total"] == 1
    finally:
        shutil.rmtree(d)


def teste_feeds_de_fora():
    """Blogs, newsletters e podcasts (11/11/2026): RSS e Atom, palavras, máximo por rodada, sem yt-dlp."""
    longo = "<p>" + "Um app novo que paga no Pix por tarefas simples. " * 12 + "</p>"
    rss = f"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel><title>Blog</title>
      <item><title>Airdrop novo da semana</title><link>https://blog.test/1</link><pubDate>Tue, 10 Nov 2026 12:00:00 -0300</pubDate>
        <description>Resumo curto</description><content:encoded><![CDATA[{longo}]]></content:encoded></item>
      <item><title>Política hoje</title><link>https://blog.test/2</link><pubDate>Tue, 10 Nov 2026 13:00:00 -0300</pubDate><description>nada</description></item>
      <item><title>App que paga airdrop curto</title><link>https://blog.test/3</link><pubDate>Mon, 09 Nov 2026 12:00:00 -0300</pubDate><description>só isso</description></item>
    </channel></rss>"""
    pod = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Ep. 12: renda passiva</title>
      <link href="https://pod.test/12"/><published>2026-11-08T10:00:00Z</published><summary>Notas do episódio</summary></entry></feed>"""
    rede = Rede({})
    rede.feeds = {}
    base = rede.__call__
    def chamar(url, prazo=30):
        if url == "https://blog.test/feed":
            return rss
        if url == "https://pod.test/feed":
            return pod
        if url == "https://quebrado.test/feed":
            raise RuntimeError("HTTP Error 500")
        return base(url)
    cfg = {"canais": [], "feeds": [
        {"chave": "blog", "nome": "Blog", "url": "https://blog.test/feed", "tipo": "blog", "palavras": ["airdrop", "app"], "max": 5},
        {"chave": "pod", "nome": "Pod", "url": "https://pod.test/feed", "tipo": "podcast"},
        {"chave": "quebrado", "nome": "Quebrado", "url": "https://quebrado.test/feed"},
        {"chave": "off", "nome": "Off", "url": "https://off.test/feed", "ativo": False},
    ]}
    d = tempfile.mkdtemp()
    try:
        yt = YtFalso({})
        idx = I.rodada(d, cfg, baixar_fn=chamar, ytdlp=yt, api=I.TranscriptApi(buscar=api_falsa(set())), pausa=0, log=I.Log(eco=False))
        ids = {v["id"]: v for v in idx["videos"]}
        assert len(ids) == 3, ids   # a de política fica de fora pelas palavras
        assert not yt.chamadas, "nada de yt-dlp para os feeds"
        v1 = json.load(open(os.path.join(d, "videos", I.id_do_item("https://blog.test/1") + ".json")))
        assert v1["tipo"] == "blog" and v1["fonte"] == "feed" and "Pix" in v1["transcricao"] and v1["url"] == "https://blog.test/1"
        v3 = ids[I.id_do_item("https://blog.test/3")]
        assert v3["transcricao"] is False and v3["motivoSemTranscricao"] == "só o resumo do feed"
        assert ids[I.id_do_item("https://pod.test/12")]["tipo"] == "podcast"
        assert idx["canais"]["quebrado"]["feed"] is False and "off" not in idx["canais"] and idx["canais"]["blog"]["fora"]
        # a 2ª rodada não repete
        idx2 = I.rodada(d, cfg, baixar_fn=chamar, ytdlp=yt, api=I.TranscriptApi(buscar=api_falsa(set())), pausa=0, log=I.Log(eco=False))
        assert idx2["rodadas"][-1]["novos"] == 0 and idx2["total"] == 3
    finally:
        shutil.rmtree(d)


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("teste_") and callable(f):
            f()
            print("ok", nome)
    print("tudo certo")
