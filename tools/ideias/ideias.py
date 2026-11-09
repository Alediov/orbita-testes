"""Antena de ideias do Órbita: os vídeos novos dos canais de `config/ideias-canais.json`, com a transcrição em texto.

Pedido do Alediov (09/11/2026): achar cedo, nos canais que ele acompanha, as ideias que viram macros novas (faucets,
check-ins, airdrops que duram pouco) ou testes novos no papel. Este programa só COLETA (público, sem chave, sem conta):
a leitura e a classificação são da tarefa agendada do repositório privado (roteiro `gerador/IDEIAS.md` de lá), que lê
o ramo `ideias` daqui pelo raw.githubusercontent, sem token.

Saída (pasta `--dados`, que o workflow ideias.yml grava no ramo órfão `ideias` num commit único):
- `videos/<id>.json`: {canal, id, titulo, publicado, url, duracao, descricao, transcricao | null, idioma, fonte,
  motivoSemTranscricao, tentativas, visto, atualizado};
- `indice.json`: os canais (com o channel_id usado e se o feed respondeu), os vídeos (sem o texto; mais novo primeiro),
  as últimas rodadas e como cada método de transcrição se saiu;
- `log.txt`: o log desta rodada.

Descoberta: o feed RSS de cada canal (`/feeds/videos.xml?channel_id=…`, os 15 últimos); se o feed falhar, o
channel_id é procurado de novo na página do @handle. Na 1ª rodada de um canal (nenhum vídeo dele no índice) também a
lista dos últimos `--inicio` (30) envios pelo yt-dlp (`--flat-playlist` na playlist de envios "UU…", que inclui os
Shorts). Transcrição: legendas (automáticas ou não, pt e depois en) pelo yt-dlp; se falhar, pelo
youtube-transcript-api. O YouTube às vezes bloqueia IPs de datacenter: o motivo vai para o vídeo e para o log, os
metadados ficam assim mesmo e o vídeo é tentado de novo nas rodadas seguintes (`MAX_TENTATIVAS`).

Só biblioteca padrão; o yt-dlp e o youtube-transcript-api são opcionais (o workflow instala os dois).
Uso: python3 -I tools/ideias/ideias.py --dados dados [--config config/ideias-canais.json] [--inicio 30]
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.normpath(os.path.join(AQUI, "..", ".."))
CONFIG = os.path.join(RAIZ, "config", "ideias-canais.json")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
CANAL = "https://www.youtube.com/@{}"
VIDEO = "https://www.youtube.com/watch?v={}"
UPLOADS = "https://www.youtube.com/playlist?list=UU{}"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}

IDIOMAS = ["pt", "pt-BR", "pt-PT", "en", "en-US"]
MAX_TENTATIVAS = 6        # sem transcrição: tenta de novo em até 6 rodadas (~3 dias com 2 por dia)
MAX_POR_RODADA = 40       # transcrições tentadas por rodada (as mais novas primeiro)
PAUSA = 4.0               # s entre dois vídeos, para não parecer robô
GUARDAR_DIAS = 200        # vídeos publicados há mais que isso saem do ramo
MAX_RODADAS = 30
VERSAO = 1


def agora_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Log:
    def __init__(self, eco=True):
        self.linhas, self.eco = [], eco

    def __call__(self, *partes):
        s = " ".join(str(p) for p in partes)
        self.linhas.append(f"{dt.datetime.now(dt.timezone.utc):%H:%M:%S} {s}")
        if self.eco:
            print(s, flush=True)


# ------------------------------------------------------------------------------------------------ rede
def baixar(url, prazo=30):
    """GET simples; devolve o texto. Erros sobem como Exception com o código."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                                               "Cookie": "SOCS=CAI; CONSENT=YES+"})
    with urllib.request.urlopen(req, timeout=prazo) as r:
        return r.read().decode("utf-8", "replace")


def channel_id_da_pagina(texto):
    for pad in (r'"externalId":"(UC[\w-]{22})"', r'<meta itemprop="identifier" content="(UC[\w-]{22})"',
                r'"channelId":"(UC[\w-]{22})"', r'channel_id=(UC[\w-]{22})', r'/channel/(UC[\w-]{22})'):
        m = re.search(pad, texto)
        if m:
            return m.group(1)
    return None


def ler_feed(texto, canal):
    """Os vídeos de um feed Atom do YouTube: [{id, titulo, publicado, descricao}]."""
    raiz = ET.fromstring(texto)
    out = []
    for e in raiz.findall("a:entry", NS):
        vid = e.findtext("yt:videoId", None, NS)
        if not vid:
            continue
        grupo = e.find("media:group", NS)
        desc = grupo.findtext("media:description", "", NS) if grupo is not None else ""
        out.append({"id": vid, "canal": canal, "titulo": (e.findtext("a:title", "", NS) or "").strip(),
                    "publicado": e.findtext("a:published", None, NS), "descricao": desc or ""})
    return out


# ------------------------------------------------------------------------------------------- legendas
_TAG = re.compile(r"<[^>]+>")
_TEMPO = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?[.,]\d{3}\s+-->")


def vtt_para_texto(vtt):
    """Legenda WebVTT (ou SRT) → texto corrido, sem tempos, marcas nem as repetições das legendas automáticas.

    As automáticas do YouTube "rolam": cada bloco repete a linha anterior e acrescenta a nova (que vem com as marcas de
    tempo por palavra). Fica a 1ª vez de cada linha, comparando com as últimas emitidas."""
    linhas, ultimas = [], []
    for bruta in vtt.splitlines():
        s = bruta.strip()
        if (not s or s == "WEBVTT" or s.isdigit() or _TEMPO.match(s) or s.startswith(("Kind:", "Language:", "NOTE"))
                or s.startswith(("STYLE", "REGION"))):
            continue
        t = html.unescape(_TAG.sub("", s)).strip()
        t = re.sub(r"\s+", " ", t)
        if not t or t in ultimas or t in ("[Música]", "[Music]", "[Aplausos]", "[Applause]"):
            continue
        linhas.append(t)
        ultimas = (ultimas + [t])[-3:]
    texto = " ".join(linhas)
    # sobreposição entre linhas seguidas ("a b c" + "b c d" → "a b c d") quase não acontece no VTT novo; o texto já
    # sai legível assim
    return re.sub(r"\s+", " ", texto).strip()


def classificar_erro(msg):
    m = (msg or "").lower()
    if any(k in m for k in ("sign in to confirm", "not a bot", "429", "too many requests", "ipblocked", "ip blocked",
                            "requestblocked", "blocked")):
        return "bloqueio do YouTube a este IP"
    if any(k in m for k in ("no subtitles", "there are no subtitles", "transcriptsdisabled", "subtitles are disabled",
                            "notranscriptfound", "no transcript", "sem legendas")):
        return "sem legendas"
    if any(k in m for k in ("premiere", "live event", "upcoming", "will begin", "this live")):
        return "estreia ou ao vivo ainda não aconteceu"
    if any(k in m for k in ("private video", "video unavailable", "members-only", "join this channel")):
        return "vídeo indisponível"
    return "erro: " + (msg or "?").strip().splitlines()[-1][:200]


class YtDlp:
    """O yt-dlp pela linha de comando (instalado pelo workflow). `rodar` é trocado nos testes."""

    def __init__(self, exe=None, rodar=None, log=print):
        self.exe = exe or shutil.which("yt-dlp")
        self.rodar = rodar or self._rodar
        self.log = log

    def disponivel(self):
        return bool(self.exe)

    def _rodar(self, args, prazo=180):
        p = subprocess.run([self.exe] + args, capture_output=True, text=True, timeout=prazo)
        return p.returncode, p.stdout, p.stderr

    def lista(self, channel_id, n):
        """Os últimos n envios (vídeos e Shorts) pela playlist de envios: [{id, titulo, duracao}]."""
        cod, out, err = self.rodar(["--flat-playlist", "-J", "--playlist-end", str(n), "--no-warnings",
                                    UPLOADS.format(channel_id[2:])])
        if cod != 0:
            raise RuntimeError(err or f"yt-dlp saiu com {cod}")
        j = json.loads(out)
        return [{"id": e["id"], "titulo": e.get("title") or "", "duracao": e.get("duration")}
                for e in j.get("entries") or [] if e.get("id")]

    def transcrever(self, vid):
        """{texto, idioma, info} ou levanta com a mensagem do yt-dlp."""
        pasta = tempfile.mkdtemp(prefix="ideias-")
        try:
            cod, out, err = self.rodar(["--skip-download", "--write-subs", "--write-auto-subs", "--write-info-json",
                                        "--sub-langs", "pt.*,pt,en.*,en,-live_chat", "--sub-format", "vtt/srt/best",
                                        "--no-warnings", "--no-progress", "-o", os.path.join(pasta, "%(id)s.%(ext)s"),
                                        VIDEO.format(vid)])
            info = {}
            for f in glob.glob(os.path.join(pasta, "*.info.json")):
                with open(f, encoding="utf-8") as fh:
                    info = json.load(fh)
            subs = sorted(glob.glob(os.path.join(pasta, "*.vtt")) + glob.glob(os.path.join(pasta, "*.srt")))
            escolhida = None
            for pref in ("pt", "en"):
                # a legenda manual (sem "-orig"/auto no nome não dá para saber; o yt-dlp põe a manual por cima da
                # automática quando as duas existem com o mesmo idioma)
                cand = [s for s in subs if re.search(rf"\.{pref}([-.][\w-]+)?\.(vtt|srt)$", s)]
                if cand:
                    escolhida = cand[0]
                    break
            if not escolhida and subs:
                escolhida = subs[0]
            if not escolhida:
                e = RuntimeError((err or f"yt-dlp saiu com {cod}") if cod != 0 else "no subtitles")
                e.info = info  # os metadados servem mesmo sem legenda
                raise e
            with open(escolhida, encoding="utf-8", errors="replace") as fh:
                texto = vtt_para_texto(fh.read())
            idioma = re.search(r"\.([\w-]+)\.(vtt|srt)$", escolhida).group(1)
            if not texto:
                raise RuntimeError("no subtitles (legenda vazia)")
            return {"texto": texto, "idioma": idioma, "info": info}
        finally:
            shutil.rmtree(pasta, ignore_errors=True)


class TranscriptApi:
    """youtube-transcript-api (1.x: `YouTubeTranscriptApi().fetch`; 0.x: `get_transcript`). `buscar` é trocado nos
    testes por uma função (vid, idiomas) → [{text}] ou (lista, idioma)."""

    def __init__(self, buscar=None):
        self.buscar = buscar
        if buscar is None:
            try:
                import youtube_transcript_api as yta  # noqa: F401
                self._yta = yta
            except Exception:  # noqa: BLE001
                self._yta = None

    def disponivel(self):
        return self.buscar is not None or self._yta is not None

    def transcrever(self, vid):
        if self.buscar is not None:
            r = self.buscar(vid, IDIOMAS)
            itens, idioma = r if isinstance(r, tuple) else (r, None)
        else:
            api = self._yta.YouTubeTranscriptApi
            if hasattr(api, "get_transcript"):
                itens, idioma = api.get_transcript(vid, languages=IDIOMAS), None
            else:
                f = api().fetch(vid, languages=IDIOMAS)
                itens, idioma = [{"text": s.text} for s in f], getattr(f, "language_code", None)
        texto = re.sub(r"\s+", " ", " ".join(html.unescape(i.get("text", "")) for i in itens
                                             if i.get("text") not in ("[Música]", "[Music]"))).strip()
        if not texto:
            raise RuntimeError("no transcript (vazia)")
        return {"texto": texto, "idioma": idioma, "info": {}}


# ---------------------------------------------------------------------------------------------- rodada
def ler_json(caminho, padrao=None):
    try:
        with open(caminho, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return padrao


def gravar_json(caminho, obj):
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    tmp = caminho + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, caminho)


def data_iso_de(info):
    """upload_date (AAAAMMDD) ou timestamp do info.json do yt-dlp → ISO."""
    if info.get("timestamp"):
        return dt.datetime.fromtimestamp(info["timestamp"], dt.timezone.utc).isoformat().replace("+00:00", "Z")
    d = info.get("upload_date") or info.get("release_date")
    if d and len(d) == 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:]}T00:00:00Z"
    return None


def aplicar_info(v, info):
    """Completa o vídeo com o info.json do yt-dlp (duração, data, descrição, título)."""
    if info.get("duration"):
        v["duracao"] = info["duration"]  # o da página do vídeo vale mais que o da lista
    if not v.get("publicado"):
        v["publicado"] = data_iso_de(info)
    if info.get("description") and not v.get("descricao"):
        v["descricao"] = info["description"]
    if info.get("title") and not v.get("titulo"):
        v["titulo"] = info["title"]


def publicado_ts(v):
    p = v.get("publicado")
    if not p:
        return 0.0
    try:
        return dt.datetime.fromisoformat(p.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def rodada(dados, config, baixar_fn=baixar, ytdlp=None, api=None, inicio=30, max_rodada=MAX_POR_RODADA,
           pausa=PAUSA, dormir=time.sleep, agora=None, log=None):
    log = log or Log()
    agora = agora or agora_iso()
    ytdlp = ytdlp or YtDlp(log=log)
    api = api if api is not None else TranscriptApi()
    pasta_v = os.path.join(dados, "videos")
    os.makedirs(pasta_v, exist_ok=True)
    indice = ler_json(os.path.join(dados, "indice.json"), {}) or {}
    canais_ant = indice.get("canais", {})
    metodos = {"yt-dlp": {"ok": 0, "falhas": 0, "disponivel": ytdlp.disponivel()},
               "youtube-transcript-api": {"ok": 0, "falhas": 0, "disponivel": api.disponivel()}}
    log(f"rodada {agora}; yt-dlp {'sim' if metodos['yt-dlp']['disponivel'] else 'não'}, "
        f"youtube-transcript-api {'sim' if metodos['youtube-transcript-api']['disponivel'] else 'não'}")

    # os vídeos já guardados
    videos = {}
    for f in glob.glob(os.path.join(pasta_v, "*.json")):
        v = ler_json(f)
        if v and v.get("id"):
            videos[v["id"]] = v

    # 1) descobrir
    canais_out, novos = {}, 0
    for c in config["canais"]:
        chave, cid = c["chave"], c.get("channel_id") or canais_ant.get(c["chave"], {}).get("channel_id")
        st = {"nome": c["nome"], "handle": c.get("handle"), "channel_id": cid, "foco": c.get("foco"),
              "feed": None, "erro": None, "achados": 0}
        achados = []
        for vez in range(2):
            if not cid and c.get("handle"):
                try:
                    cid = channel_id_da_pagina(baixar_fn(CANAL.format(c["handle"])))
                    st["channel_id"] = cid
                    log(f"{chave}: channel_id pela página do @{c['handle']}: {cid}")
                except Exception as e:  # noqa: BLE001
                    st["erro"] = f"página do canal: {e}"
                    log(f"{chave}: não deu para abrir a página do @{c['handle']}: {e}")
                    break
            if not cid:
                break
            try:
                achados = ler_feed(baixar_fn(FEED.format(cid)), chave)
                st["feed"] = True
                break
            except Exception as e:  # noqa: BLE001
                st["feed"], st["erro"] = False, f"feed: {e}"
                log(f"{chave}: feed falhou ({e})")
                if vez == 0 and c.get("handle"):
                    cid = None  # procura o id de novo pelo handle
        # 1ª rodada do canal: os últimos `inicio` envios
        primeira = not any(v.get("canal") == chave for v in videos.values())
        if primeira and cid and ytdlp.disponivel() and inicio:
            try:
                lista = ytdlp.lista(cid, inicio)
                log(f"{chave}: 1ª rodada, {len(lista)} envios pela playlist")
                por_id = {a["id"]: a for a in achados}
                for e in lista:
                    if e["id"] in por_id:
                        por_id[e["id"]].setdefault("duracao", e.get("duracao"))
                    else:
                        achados.append({"id": e["id"], "canal": chave, "titulo": e["titulo"], "publicado": None,
                                        "descricao": "", "duracao": e.get("duracao")})
            except Exception as e:  # noqa: BLE001
                log(f"{chave}: lista pelo yt-dlp falhou: {classificar_erro(str(e))}")
        for a in achados:
            v = videos.get(a["id"])
            if v is None:
                v = {"canal": chave, "id": a["id"], "titulo": a["titulo"], "publicado": a.get("publicado"),
                     "url": VIDEO.format(a["id"]), "duracao": a.get("duracao"), "descricao": a.get("descricao", ""),
                     "transcricao": None, "idioma": None, "fonte": None, "motivoSemTranscricao": "ainda não tentada",
                     "tentativas": 0, "visto": agora, "atualizado": agora}
                videos[a["id"]] = v
                novos += 1
            else:
                for k in ("titulo", "publicado", "descricao", "duracao"):
                    if a.get(k) and not v.get(k):
                        v[k] = a[k]
        st["achados"] = len(achados)
        canais_out[chave] = st
        log(f"{chave}: {len(achados)} no feed/lista, channel_id {cid}")
    log(f"{novos} vídeos novos")

    # 2) transcrever (mais novos primeiro; os nunca tentados antes dos que já falharam)
    fila = [v for v in videos.values() if not v.get("transcricao") and v.get("tentativas", 0) < MAX_TENTATIVAS
            and v.get("motivoSemTranscricao") != "vídeo indisponível"]
    fila.sort(key=lambda v: (v.get("tentativas", 0) > 0, -publicado_ts(v)))
    bloqueios = 0
    for i, v in enumerate(fila[:max_rodada]):
        if i and pausa:
            dormir(pausa)
        motivos = []
        resultado = None
        for nome, met in (("yt-dlp", ytdlp), ("youtube-transcript-api", api)):
            if not met.disponivel():
                continue
            try:
                resultado = met.transcrever(v["id"])
                resultado["fonte"] = nome
                metodos[nome]["ok"] += 1
                break
            except Exception as e:  # noqa: BLE001
                metodos[nome]["falhas"] += 1
                motivos.append((nome, classificar_erro(str(e))))
                aplicar_info(v, getattr(e, "info", None) or {})
        v["tentativas"] = v.get("tentativas", 0) + 1
        v["atualizado"] = agora
        if resultado:
            v.update(transcricao=resultado["texto"], idioma=resultado.get("idioma"), fonte=resultado["fonte"],
                     motivoSemTranscricao=None)
            aplicar_info(v, resultado.get("info") or {})
            log(f"ok {v['canal']} {v['id']} ({resultado['fonte']}, {resultado.get('idioma')}, "
                f"{len(resultado['texto'])} caracteres)")
        else:
            v["motivoSemTranscricao"] = "; ".join(f"{n}: {m}" for n, m in motivos) or "nenhum método disponível"
            log(f"sem transcrição {v['canal']} {v['id']}: {v['motivoSemTranscricao']}")
            if any("bloqueio" in m for _, m in motivos):
                bloqueios += 1
                if bloqueios >= 5 and bloqueios == i + 1:
                    log("5 bloqueios seguidos desde o começo: o resto fica para a próxima rodada")
                    break
    if len(fila) > max_rodada:
        log(f"{len(fila) - max_rodada} ficaram para a próxima rodada")

    # 3) limpar os velhos e gravar
    limite = time.time() - GUARDAR_DIAS * 86400
    for vid, v in list(videos.items()):
        if v.get("publicado") and publicado_ts(v) < limite:
            del videos[vid]
            try:
                os.remove(os.path.join(pasta_v, f"{vid}.json"))
            except OSError:
                pass
    for v in videos.values():
        gravar_json(os.path.join(pasta_v, f"{v['id']}.json"), v)
    lista = sorted(videos.values(), key=lambda v: (-publicado_ts(v), v["id"]))
    com = sum(1 for v in lista if v.get("transcricao"))
    rodadas = (indice.get("rodadas") or []) + [{
        "em": agora, "novos": novos, "transcritos": metodos["yt-dlp"]["ok"] + metodos["youtube-transcript-api"]["ok"],
        "metodos": metodos}]
    indice = {
        "versao": VERSAO, "atualizado": agora,
        "sobre": "Antena de ideias do Órbita: vídeos dos canais acompanhados, com a transcrição em videos/<id>.json.",
        "canais": canais_out,
        "total": len(lista), "comTranscricao": com,
        "videos": [{k: v.get(k) for k in ("id", "canal", "titulo", "publicado", "url", "duracao", "visto",
                                          "atualizado", "idioma", "fonte", "motivoSemTranscricao", "tentativas")}
                   | {"transcricao": bool(v.get("transcricao")), "caracteres": len(v.get("transcricao") or "")}
                   for v in lista],
        "rodadas": rodadas[-MAX_RODADAS:],
    }
    gravar_json(os.path.join(dados, "indice.json"), indice)
    log(f"fim: {len(lista)} vídeos, {com} com transcrição")
    return indice


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dados", required=True)
    ap.add_argument("--config", default=CONFIG)
    ap.add_argument("--inicio", type=int, default=30, help="envios por canal na 1ª rodada dele")
    ap.add_argument("--max", type=int, default=MAX_POR_RODADA, help="transcrições tentadas nesta rodada")
    a = ap.parse_args(argv)
    log = Log()
    try:
        rodada(a.dados, ler_json(a.config), inicio=a.inicio, max_rodada=a.max, log=log)
    finally:
        os.makedirs(a.dados, exist_ok=True)
        with open(os.path.join(a.dados, "log.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(log.linhas) + "\n")


if __name__ == "__main__":
    sys.exit(main())
